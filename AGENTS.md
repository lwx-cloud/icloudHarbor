# iCloudHarbor 项目状态与开发约定

本文是项目内部的长期上下文，供维护者和自动化开发代理使用。公开用户的安装与使用说明见
[`README.md`](README.md)，全部配置项见 [`CONFIGURATION.md`](CONFIGURATION.md)。

## 1. 项目定位

iCloudHarbor 是一个只运行在 Docker 中的 iCloud Photos 本地备份工具，主要面向 Linux、
群晖等 NAS 环境。它没有 Web 页面，也不监听业务端口；容器前台进程是定时调度器，管理工作
通过 `icloudharbor` 命令完成。

项目只做“远端到本地”的备份：

- 从 Apple iCloud Photos 的个人/共享图库读取照片、视频、Live Photo 和 RAW 伴随资源。
- 根据日期、媒体类型和命名规则生成确定的本地路径。
- 使用 `.part` 文件、断点续传、重试、大小与 SHA-256 校验完成下载。
- 使用 SQLite 保存远端资源、本地文件、同步游标、运行结果和锁状态。
- 不删除 iCloud 中的内容，不把本地删除同步到远端，也不提供双向同步。

它是独立实现，不调用其他 iCloud 下载容器的脚本或命令。第三方 Apple 协议适配集中在
`protocol/pyicloud_adapter.py`，其余业务代码不直接依赖 `pyicloud`。

## 2. 当前支持范围

当前版本为 `0.3.4`，支持：

- 一个启用的 Apple Account。
- 个人图库 `root`、协议层可见的共享图库、多图库聚合以及相册包含/排除。
- 中国大陆和全球 iCloud 服务端点，`region=auto` 会优先复用 Session 中的区域信息。
- Apple 双重认证验证码。
- Docker 首次启动时从 `IH_*` 参数自动生成 `/config/config.yaml`。
- `icloudharbor setup` 以星号遮罩读取密码、完成认证并保存本地续期凭据，然后把首次同步
  持久化交给容器后台并退出；下载过程统一显示在主容器日志。
- `icloudharbor session renew` 使用已保存凭据续期，Apple 要求时只询问验证码；成功后同样
  请求后台立即同步。
- 普通 Docker 参数用整数小时配置同步间隔；高级 YAML 支持 Cron、增量游标与定期全量扫描。
- 容器异常终止后，在独占文件锁保护下自动恢复同名 SQLite 残留租约。
- 照片、视频、Live Photo、RAW/JPEG、原片/编辑版/尺寸选择和 HEIC 转 JPEG。
- 日期、收藏、隐藏、最近项目及连续已有项目停止筛选。
- 可选的文件/目录权限和 Synology Photos touch 索引兼容。
- 可选的 Bark、Server酱、Telegram、企业微信和通用 Webhook 通知。
- 企业微信兼容 icloudpd 的四个媒体 ID，并按真实 Cookie 到期时间提前 7 天每日提醒一次。
- 每次同步任务结束都发送结果通知，包括首次、手动、调度以及没有新文件的成功同步；通知
  没有独立定时器，认证临期只在同步时检查并单独按天去重。
- 容器 INFO 日志输出脱敏启动摘要，每个文件只显示一次“正在下载”，并汇总结果和下次任务；
  断点与内部资源信息仅在 DEBUG 输出。
- amd64 与 arm64 Docker 构建。

明确未支持：

- 多个启用账号。
- 安全密钥和旧式两步认证的交互流程。
- iCloud Session 文件加密。
- 任何远端删除、本地清理、镜像同步或 Web UI。

配置模型会对危险或未实现能力“失败关闭”：`session_encryption` 必须为 `false`，
`allow_remote_delete` 只能为 `false`。

## 3. 运行流程

容器启动时依次执行：

1. `docker/entrypoint.sh` 校验 UID 和 GID，固定 umask 0022。
2. 调整 `/config` 内运行目录的属主与权限。
3. 如果 `/config/config.yaml` 不存在，执行 `icloudharbor config bootstrap`。
4. 以配置的非 root UID/GID 启动 `tini` 和 `icloudharbor daemon`。
5. 调度器按 Cron/间隔触发同步，并每秒接收认证进程写入 SQLite 的立即同步请求；同一账号
   最多运行一个认证或同步操作。

一次同步依次经过：

1. 检查目标目录、挂载标记、可写性、剩余空间、inode 和 SQLite。
2. 恢复 Apple Session，并确认所选图库和相册可访问。
3. 根据图库、相册与筛选策略执行游标扫描或全量扫描。
4. 标准化远端 Asset/Resource，应用媒体和日期策略。
5. 与 SQLite 和磁盘状态比对，生成下载、修复和跳过计划。
6. 并发流式下载到同目录 `.part` 文件，校验后原子替换正式文件。
7. 记录结果；只有全部资源成功时才提交新同步游标。

这样可以避免部分失败时越过未完成的远端变更。

## 4. 目录与模块职责

### 根目录

- `Dockerfile`：多阶段生产镜像；构建依赖与运行镜像分离。
- `docker-compose.yml`：从 Docker Hub 拉取生产镜像，并配置必需参数与持久化卷。
- `docker-compose.build.yml`：开发者从当前源码进行本地镜像构建时使用的 Compose 覆盖文件。
- `docker/entrypoint.sh`：权限初始化、配置引导和非 root 降权。
- `docker/icloudharbor-cli.sh`：让 `docker exec` 与镜像健康检查自动使用运行 UID/GID。
- `.env.example`：可直接照填的新手参数参考，包含整数小时同步、常用布尔开关和可选企业微信
  参数，不包含 Apple 密码。
- `pyproject.toml`、`uv.lock`：固定的 Python 依赖和开发工具版本。
- `.github/workflows/ci.yml`：Python 3.12/3.13 检查、amd64/arm64 镜像构建，以及版本标签
  触发的 Docker Hub 发布。
- `tests/`：单元和集成测试，不连接真实 Apple 服务。

### `src/icloudharbor`

- `cli.py`：全部公开命令、交互认证和守护进程入口。
- `application.py`：依赖装配中心，创建数据库、协议适配器、锁、健康检查和通知器。
- `config/models.py`：严格的 Pydantic 配置结构、默认值、取值范围和安全约束；固定行为
  （挂载标记、下载块大小、校验、断点续传）为模块常量而非配置项。
- `config/loader.py`：YAML 加载、首次生成、`IH_*` 覆盖、0.2→0.3 遗留参数自动迁移和原子写入。
- `config/validation.py`：容量、时长等人类可读值解析。
- `auth/manager.py`：认证状态与协议调用的协调。
- `auth/session_store.py`：保存非敏感的认证状态元数据。
- `security/prompt.py`：TTY 星号密码输入。
- `security/credentials.py`：AES-256-GCM 本地续期凭据存储。
- `security/redaction.py`：日志和 CLI 中的邮箱、令牌与请求头脱敏。
- `security/secrets.py`：读取通知通道的令牌文件；不用于 Apple Account 密码。
- `protocol/base.py`：Apple 协议抽象接口。
- `protocol/models.py`：与具体协议库无关的认证、图库、Asset 和 Resource 模型。
- `protocol/exceptions.py`：稳定的业务错误码。
- `protocol/pyicloud_adapter.py`：`pyicloud` 兼容边界、2FA、资源标准化和流式下载。
- `photos/engine.py`：固定阶段的同步编排和安全检查。
- `photos/planner.py`：幂等计划、本地完整性判断和修复决策。
- `photos/policies.py`：媒体、RAW、版本、收藏、隐藏和日期策略。
- `photos/naming.py`：安全路径渲染、跨平台字符清理和冲突处理。
- `download/manager.py`：并发下载、断点续传、重试和原子落盘。
- `download/postprocess.py`：文件权限、HEIC 转 JPEG 和 Synology Photos 索引触发。
- `download/verifier.py`：大小与 SHA-256 校验。
- `download/retry.py`：带随机抖动的指数退避。
- `database/models.py`：SQLite 数据结构，包括跨进程同步请求的代次状态。
- `database/repository.py`：账号、图库、资源、运行记录、游标、锁和同步请求的数据访问。
- `database/session.py`：SQLite 连接、WAL、外键和完整性检查。
- `scheduler/service.py`：Cron/间隔、启动时任务和进程内合并的立即任务。
- `scheduler/locks.py`：进程锁、文件锁和数据库租约三层互斥，以及崩溃残留租约恢复。
- `notify/base.py`：通知事件路由和五种通知通道。
- `observability/logging.py`：文本/JSON 结构化日志、第三方日志降噪和标准日志脱敏。
- `observability/health.py`：存活与就绪检查。
- `observability/paths.py`：把容器内照片路径映射为宿主机展示路径。
- `observability/startup.py`：脱敏启动与认证配置摘要。

## 5. 持久化数据

默认容器路径：

```text
/config/
├── config.yaml
├── credentials/
│   ├── vault.key
│   └── personal.json
├── database/
│   └── icloudharbor.db
├── sessions/
│   └── personal/
├── locks/
└── tmp/

/photos/
└── personal/
    └── .icloudharbor-mounted
```

重要约束：

- `/config` 与 `/photos` 必须持久化。
- `destination.path` 必须位于照片卷内，默认 `/photos/personal`。
- 挂载标记是防止卷未挂载时误写容器层的保护，不得省略。
- Apple 密码不会进入 `.env`、Compose 或命令参数。
- 保存的密码使用 AES-256-GCM，但密钥和密文都在 `/config/credentials`，宿主机 root
  仍可恢复密码；此设计用于无人值守续期和防止意外明文泄露，不等同于硬件密钥保护。
- Apple Cookie/Session 由底层协议库保存，当前未加密；整个 `/config` 应按敏感数据保护。

## 6. 不可破坏的生产规则

- 不得增加远端删除调用。
- 不得在没有挂载标记时下载。
- 不得把 Apple 密码、验证码、Cookie、令牌或真实账号写入日志、测试、Git 或镜像层。
- 不得让业务模块直接导入 `pyicloud`；协议变化只能在 `protocol/` 内处理。
- 不得在部分下载失败后提交同步游标。
- 正式文件必须由已校验的同文件系统 `.part` 文件原子替换。
- 配置必须保持 `extra="forbid"`，未知参数应报错而不是静默忽略。
- 新增 Docker 参数时，必须同步更新 loader、Compose、`.env.example`、测试和
  `CONFIGURATION.md`。
- 项目只保留 `AGENTS.md`、`CONFIGURATION.md`、`README.md` 三个 Markdown 文件。

## 7. 开发与发布检查

在仓库根目录执行：

```bash
uv sync --frozen --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src/icloudharbor
uv run pytest --cov=icloudharbor --cov-report=term-missing
uv build
docker compose config
docker build .
```

提交前还必须：

- 扫描仓库中可能的邮箱、密码、Apple Cookie、私钥和 `.env`。
- 确认 Git 只包含源码、测试、三份 Markdown、许可证和构建/部署元数据。
- 确认 shell 文件为 LF，镜像以非 root 账号运行，Compose 未增加业务端口。
- 确认 README 中的命令可以从一个全新克隆目录执行。

## 8. 当前验证状态

- 已在 Synology Docker 环境完成真实 Apple Account 双重认证和个人图库下载闭环。
- 已验证中国大陆服务区域、星号密码输入、Session 续期、配置自动生成和下载目录保护。
- 已验证真实日期范围样本能完成照片资源下载。
- 2026-07-30 的 0.2.0 发布检查：103 项自动化测试全部通过，覆盖率 81%；包含多图库、
  相册、尺寸、HEIC 转换、权限、调度延迟和通知回归测试。
- 2026-07-30 的 0.3.0 参数精简：删除 11 个伪参数、合并 4 组重叠参数（photo_version→
  photo_size、interval→schedule、no_changes→success、umask→固定 0022），旧 `.env` 与
  `config.yaml` 自动迁移或警告忽略；108 项测试、Ruff 与严格 mypy 全部通过。
- 2026-07-31 的 0.3.4 交互改进：认证命令通过 SQLite 请求代次把首次/续期同步交给 daemon，
  下载日志统一进入主容器；新手同步参数恢复为纯数字小时，默认 24 小时并在启动时检查。
  130 项测试通过，覆盖率 80%，Ruff、格式检查与严格 mypy 全部通过。
- Ruff、格式检查、严格 mypy、源码包/Wheel 构建和未引用代码扫描通过。
- 锁定的生产依赖经漏洞数据库审计未发现已知漏洞。
- amd64/arm64 镜像构建结果以对应 GitHub Actions 发布提交为准。

主要外部风险是 Apple 私有接口与返回字段可能变化。出现协议异常时，应先在
`protocol/pyicloud_adapter.py` 添加兼容和回归测试，不能把底层对象泄露到业务层。


## 9. 发布与 icloudpd 认证流程调查

以下结论于 2026-07-31 核对，`icloudpd` 指
[`boredazfcuk/docker-icloudpd`](https://github.com/boredazfcuk/docker-icloudpd)，源码提交为
`e2d9aa01abe97f669fec6517cd44a251621d7560`，容器版本为 `1.0.1369_30-05-2026`，
其中固定 `icloudpd 1.32.3`。

### 9.1 GitHub 到 Docker Hub

- `.github/workflows/ci.yml` 会在每次 push 和 PR 上测试及构建，但只有 Git ref 以
  `refs/tags/v` 开头时才登录并推送 Docker Hub。普通 `git push` 不发布镜像。
- `v0.3.3` 生成 `0.3.3`、`0.3`、`latest` 和 `sha-d741f2b` 四个标签。调查时四者均指向
  清单摘要 `sha256:b289da7980cb2f4e50af635c681c095c54dfceb5ee1f3825f4a895c5fccc7f82`，
  OCI 标签中的版本为 `0.3.3`、revision 为 `d741f2bd5a67a3855dd251f992a975d0e2e1b31b`；
  amd64 和 arm64 均已发布。因此当时的群晖旧版本不是发布端仍为 0.3.2。
- `latest` 只是可变标签。`docker compose up -d` 不负责查询远端更新，群晖下载新镜像后也不会
  自动替换已经运行的旧容器。升级必须依次执行 `docker compose pull` 和
  `docker compose up -d --force-recreate --remove-orphans`，再以容器内
  `icloudharbor --version` 为准；Container Manager 页面可能仍显示旧创建时间或缓存信息。
- 若 `docker compose config --images` 输出 `icloudharbor:local`，说明误用了
  `docker-compose.build.yml`，运行的不是 Docker Hub 镜像。若私有仓库拉取失败，Docker
  也可能继续保留旧本地镜像，应先 `docker login` 并检查 pull 输出。仍取得旧摘要时再排查
  registry mirror 或代理缓存。
- 发布时应先同步 `pyproject.toml` 与 `src/icloudharbor/__init__.py`，创建带说明的版本标签，
  并只推送目标标签，例如 `git push origin v0.3.4`。不要使用 `git push --tags`：本地存在而
  远端已不存在的旧标签可能重新触发发布并把 `latest` 回退。
- 从 `v0.3.4` 起发布工作流只生成完整版本号和 `latest` 两个 Docker Hub 标签，不再生成
  `0.3` 和 `sha-*` 标签。

### 9.2 icloudpd 如何等待初始化

- 容器的 `launcher.sh` 最终 `exec` 前台 `sync-icloud.sh`。它不是在主容器进程的标准输入上
  等待密码或验证码，而是检查 `/config` 中的持久化文件。
- 缺少 `/config/python_keyring/keyring_pass.cfg` 时，前台脚本每 5 秒检查一次，最多等待
  30 分钟。另一个 `docker exec -it icloudpd sync-icloud.sh --Initialise` 进程负责交互并
  写入 keyring；前台看到文件后继续。超过 30 分钟仍没有文件便退出，由 Docker restart
  policy 重新启动后再次等待。
- keyring 已有但 MFA Cookie 缺失时，前台同样每 5 秒轮询 Cookie 文件，最多 30 分钟；
  Cookie 只有基础会话而没有 `X-APPLE-WEBAUTH-HSA-TRUST` 时则轮询该认证标志。初始化进程
  完成后，前台自然解除等待并进入下载循环。
- 所以它采用的是“两个进程通过 `/config` 文件交接”的方式，不是 `docker up -d` 后把同一个
  交互终端挂起。后台进程只消费 keyring/Cookie，`docker exec -it` 进程负责生产它们。

### 9.3 icloudpd 的 `--Initialise`

- 没有 keyring 时，`--Initialise` 先执行 `icloud --username ...`，由 keyring 后端询问并保存
  Apple 密码；然后把已有 Cookie/Session 移为备份，执行
  `icloudpd --auth-only --cookie-directory /config`，按需询问 MFA 验证码并生成新 Cookie。
  脚本只在 Cookie 含受信任会话标志时报告成功，然后退出；已等待的前台进程继续同步。
- 已有 keyring 时再次运行 `--Initialise`，不会再次询问或替换 Apple 密码。它直接复用 keyring
  中的密码，备份现有 Cookie/Session，并强制重新执行认证和生成 Cookie。若 Apple 密码已经
  修改，应先运行 `sync-icloud.sh --Remove-Keyring`，再运行 `--Initialise`。
- `--Initialise` 进程自身不进入长期下载循环，因为参数分支通过 `run_action` 在 Cookie 生成后
  退出；真正的同步仍由容器前台已有进程执行。

### 9.4 icloudpd 的 `reauth.sh`

- `reauth.sh` 从 `/config/icloudpd.conf` 读取运行用户、Apple ID 和中国区认证开关，删除当前
  Cookie 及 `.session`，再以配置的非 root 用户执行
  `icloudpd --auth-only --cookie-directory /config`。正常情况下它复用 keyring 密码，只在
  Apple 要求时交互读取 MFA 验证码；若 keyring 缺失，底层密码提供器仍可能回退到终端询问
  密码。
- 该脚本只重建认证文件，不直接重启容器，也不直接启动一次照片同步。前台若正在等待 Cookie
  会在文件出现后继续；若正在同步间隔休眠，则在下一轮使用新 Cookie。
- 前台发现 Cookie 已过期或格式无效时会删除 Cookie、等待 5 分钟并退出，随后依靠 restart
  policy 重启并等待新的 Cookie。若在这 5 分钟休眠期间运行 `reauth.sh`，旧前台不会立即
  同步，仍要等它退出并重启；重启后可发现新 Cookie。
- 上游的成功状态不能直接照搬：`--Initialise` 的 `run_action` 不检查 `generate_cookie`
  结果，认证失败也可能打印 `Container initialisation complete` 并以 0 退出；`reauth.sh`
  同样没有在退出前验证新 Cookie。iCloudHarbor 必须继续以协议认证状态和实际访问检查作为
  成功条件。

### 9.5 与 iCloudHarbor 的对应关系

- iCloudHarbor 的前台进程始终是独立调度器；没有凭据或 Session 时，容器日志会明确提示
  `docker exec -it icloudharbor icloudharbor setup`。交互进程通过 SQLite 请求代次与后台
  交接，不依赖主容器标准输入或强制重启。
- iCloudHarbor 的 `setup` 与 icloudpd 重复执行 `--Initialise` 不同：每次都先清除旧 Session、
  重新询问密码、覆盖本地 AES-256-GCM 凭据、完成 MFA、检查图库/相册，然后写入持久化请求
  并退出。主 daemon 刷新协议对象后立即执行正式同步，因此全部下载日志进入 `docker logs`。
- iCloudHarbor 的 `session renew` 对应 `reauth.sh`：清除旧 Session，复用保存的本地凭据，
  Apple 要求时只询问验证码，成功后请求后台立即同步并退出。若本地凭据不存在，则要求改用
  `setup`。
