# iCloudHarbor AI 维护指南

本文是仓库级长期上下文，供维护者和自动化开发代理理解项目、定位代码和判断改动范围。公开
用户的安装与使用说明见 [`README.md`](README.md)，全部配置项见
[`CONFIGURATION.md`](CONFIGURATION.md)。

## 0. 阅读方式与事实优先级

开始修改前按以下顺序建立上下文：

1. 先读本文件，确认产品边界、依赖方向和不可破坏规则。
2. 涉及配置或公开命令时，再读 `CONFIGURATION.md` 和 `README.md` 的对应章节。
3. 用 `rg` 定位实现和测试；不要仅凭文档中的版本号、测试数量或历史调查推断当前行为。
4. 先执行 `git status --short`。工作区可能已有维护者修改，必须在现有内容上继续，不得回退
   无关改动。

判断“当前实现是什么”时，事实优先级为：

1. `src/` 的实现与本机存在的对应测试；
2. `docker-compose.yml`、`Dockerfile`、入口脚本和 CI；
3. `CONFIGURATION.md` 与 `README.md`；
4. 本文件末尾带日期的历史验证和外部项目调查。

若代码、测试和文档不一致，应先确认任务是在修复实现还是更新公开契约，再同步所有受影响面。
项目只保留 `AGENTS.md`、`CONFIGURATION.md`、`README.md` 三个 Markdown 文件，不要为计划、
调查记录或临时说明新增 Markdown。

## 1. 项目定位

iCloudHarbor 的生产部署只支持 Docker，主要面向 Linux、群晖等 NAS 环境；本地 Python 环境
仅用于开发、测试和构建。项目没有 Web 页面，也不监听业务端口；容器前台进程是定时调度器，
管理工作通过 `icloudharbor` 命令完成。

项目只做“远端到本地”的备份：

- 从 Apple iCloud Photos 的个人/共享图库读取照片、视频、Live Photo 和 RAW 伴随资源。
- 根据日期、媒体类型和命名规则生成确定的本地路径。
- 使用 `.part` 文件、断点续传、重试、大小与 SHA-256 校验完成下载。
- 使用 SQLite 保存远端资源、本地文件、同步游标、运行结果和锁状态。
- 不删除 iCloud 中的内容，不把本地删除同步到远端，也不提供双向同步；可选的本地清理只读取
  iCloud“最近删除”，按已记录的 Asset ID 和文件哈希删除精确匹配项。

它是独立实现，不调用其他 iCloud 下载容器的脚本或命令。第三方 Apple 协议适配集中在
`protocol/pyicloud_adapter.py`，其余业务代码不直接依赖 `pyicloud`。

## 2. 当前支持范围

当前源码版本为 `0.4.0`；是否已经发布到 Docker Hub 以 Git tag 和发布工作流为准。源码支持：

- 一个启用的 Apple Account。
- 默认账号 ID 和终端、通知中的显示名称都直接使用 `IH_APPLE_ID`；只有显式设置
  `IH_ACCOUNT_NAME` 时才覆盖显示名称。
- 个人图库 `root`、协议层可见的共享图库、多图库聚合以及相册包含/排除。
- 中国大陆和全球 iCloud 服务端点，`region=auto` 会优先复用 Session 中的区域信息。
- Apple 双重认证验证码。
- Docker 首次启动时从 `IH_*` 参数自动生成 `/config/config.yaml`。
- `deploy/install.sh` 提供面向 Linux 和群晖 SSH 的 `curl | sudo bash` 安装向导：通过
  `/dev/tty` 收集非敏感部署参数，创建挂载标记，拉取并启动生产镜像，运行 `doctor` 后再把
  Apple 密码和验证码输入交给容器内的 `setup`。
- `icloudharbor setup` 以星号遮罩读取密码、完成认证并保存本地续期凭据，然后把首次同步
  持久化交给容器后台并退出；下载过程统一显示在主容器日志。
- `icloudharbor session renew` 使用已保存凭据续期，Apple 要求时只询问验证码；成功后同样
  请求后台立即同步。
- 普通 Docker 参数只接受 `6`、`12`、`24` 三种整数小时；高级 YAML 支持其他间隔、Cron、
  增量游标与定期全量扫描。
- 容器异常终止后，在独占文件锁保护下自动恢复同名 SQLite 残留租约。
- 照片、视频、Live Photo、RAW/JPEG、原片/编辑版/尺寸选择和 HEIC 转 JPEG。
- 同一 Asset 的多资源并发下载使用 SQLite 原子 UPSERT 记录 Asset、Resource 和本地文件，
  不会因 Live Photo、RAW/JPEG 或多尺寸资源同时完成而触发唯一键竞态。
- 原始资源和转换 JPEG 的文件修改时间统一恢复为 iCloud 拍摄时间，全量扫描会校正历史文件。
- 日期、收藏、隐藏、最近项目及连续已有项目停止筛选。
- 可选 `IH_AUTO_DELETE` 本地清理，默认关闭；只扫描个人图库“最近删除”，按账号、图库和 Asset
  ID 精确匹配 SQLite 记录，并在删除前复核路径归属、文件类型、大小与 SHA-256。
- 可选的文件/目录权限和 Synology Photos touch 索引兼容。
- 可选的 Bark、Server酱、Telegram、企业微信和通用 Webhook 通知。
- 企业微信兼容 icloudpd 的四个媒体 ID。认证临期窗口可配置，默认提前 7 天，同一天只成功
  提醒一次。
- 首次、手动和调度的正式同步都会路由结果事件，包括没有新文件的成功同步；`DRY_RUN` 和
  `SKIPPED_ALREADY_RUNNING` 不发送结果，实际发送还取决于通知开关和已启用渠道。
- 通知没有独立定时器，认证临期只在同步时检查。启动通知按立即同步、延迟同步、后台请求或
  下一次计划显示真实状态；普通正文使用中文状态、易读数据量和明确原因，Webhook 的结构化
  payload 仍可携带 `error_code` 供自动化处理。
- 首次未认证启动把“容器已启动”和“等待认证”合并为一条消息；同一认证问题使用 SQLite
  跨进程持久去重，容器重启和后续调度不会重复提醒。`setup` 与 `session renew` 成功后发送
  `AUTH_RECOVERED`，明确后台同步请求已提交，并清除去重状态以允许未来新的认证问题再次提醒。
  认证通知关闭而普通启动通知开启时，首次合并消息回退为 `APP_STARTED`；两个开关都关闭时
  不发送。认证恢复、失效与临期仍由 `auth_required` 开关控制。
- 容器 INFO 日志输出脱敏启动摘要，每个文件只显示一次“正在下载”，并汇总结果和下次任务；
  断点与内部资源信息仅在 DEBUG 输出。
- amd64 与 arm64 Docker 构建。

明确未支持：

- 多个启用账号。
- 安全密钥和旧式两步认证的交互流程。
- iCloud Session 文件加密。
- 任何远端删除、同名猜测删除、未跟踪文件或空目录清理、完整镜像同步或 Web UI。

配置模型会对危险或未实现能力“失败关闭”：`session_encryption` 必须为 `false`，
`allow_remote_delete` 只能为 `false`。

## 3. 运行流程

主要依赖方向如下：

```text
cli.py / scheduler.service
            │
            ▼
       application.py
       ├── auth.manager ───────────────┐
       ├── photos.engine               │
       │   ├── photos.policies/naming  │
       │   ├── photos.planner          │
       │   └── download.manager        │
       ├── database.repository         │
       ├── notify.base                 │
       └── observability.*             │
                                       ▼
protocol.base + protocol.models ◄── protocol.pyicloud_adapter
```

`application.py` 是装配边界，CLI 和调度器不自行创建零散依赖。`photos/`、`download/`、`auth/`
等业务层只依赖稳定协议模型和接口；只有 `protocol/pyicloud_adapter.py` 可以导入或接触
`pyicloud` 对象。数据库访问统一经过 `StateRepository`，不要在业务模块散写 SQL。

容器启动时依次执行：

1. `docker/entrypoint.sh` 校验 UID 和 GID，固定 umask 0022。
2. 调整 `/config` 内运行目录的属主与权限。
3. 如果 `/config/config.yaml` 不存在，执行 `icloudharbor config bootstrap`。
4. 以配置的非 root UID/GID 启动 `tini` 和 `icloudharbor daemon`。
5. 调度器按 Cron/间隔触发同步，并每秒接收认证进程写入 SQLite 的立即同步请求；同一账号
   最多运行一个认证或同步操作。

`setup` 和 `session renew` 通常由 `docker compose exec` 启动为独立进程。`setup` 还会验证
配置的图库和相册；`renew` 只使用已保存凭据重建认证。成功后两者都会增加 SQLite 同步请求
代次并发送 `AUTH_RECOVERED`；daemon 观察到新代次后重建协议对象并执行正式同步。因此交互
命令退出不代表下载结束，下载进度属于 daemon 日志。认证问题通知的去重状态也保存在 SQLite，
认证恢复后必须重新放行，不能只做进程内去重。

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
- `deploy/install.sh`：幂等 Docker 安装/更新向导；首次生成 root 管理的 `.env`，默认把容器
  可写状态放在安装目录的 `data/config`，重跑必须保留所有现有配置和持久化数据，只更新受
  管理的 Compose 文件与镜像。
- `docker/entrypoint.sh`：权限初始化、配置引导和非 root 降权。
- `docker/icloudharbor-cli.sh`：让 `docker exec` 与镜像健康检查自动使用运行 UID/GID。
- `.env.example`：可直接照填的新手参数参考，包含整数小时同步、常用布尔开关和可选企业微信
  参数，不包含 Apple 密码。
- `pyproject.toml`、`uv.lock`：固定的 Python 依赖和开发工具版本。
- `.github/workflows/ci.yml`：Python 3.12/3.13 静态检查、本地测试存在时的测试、
  amd64/arm64 镜像构建，以及版本标签触发的 Docker Hub 发布。
- `tests/`：仅在维护者本机保留的单元和集成测试，不连接真实 Apple 服务；目录被
  `.gitignore` 排除，不上传到 GitHub。

### `src/icloudharbor`

- `cli.py`：全部公开命令、交互认证和守护进程入口。
- `application.py`：依赖装配中心，创建数据库、协议适配器、锁、健康检查和通知器。
- `config/models.py`：严格的 Pydantic 配置结构、默认值、取值范围和安全约束；挂载标记名与
  下载块大小是固定常量，不是公开配置项。
- `config/loader.py`：YAML 加载、首次生成、`IH_*` 覆盖、严格校验和原子写入。
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
- `download/deletion.py`：把“最近删除”的精确 Asset ID 匹配安全执行为本地删除，包含路径、归属
  和 SHA-256 复核。
- `download/postprocess.py`：文件权限、HEIC 转 JPEG 和 Synology Photos 索引触发。
- `download/verifier.py`：始终计算本地大小与 SHA-256；远端提供有效期望值时再执行比较。
- `download/retry.py`：带随机抖动的指数退避。
- `database/models.py`：SQLite 数据结构，包括跨进程同步请求代次和转换 JPEG 等派生文件记录。
- `database/repository.py`：账号、图库、资源、运行记录、游标、锁和同步请求的数据访问。
- `database/session.py`：SQLite 连接、WAL、外键、建表和完整性检查；当前没有独立迁移框架。
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
│   └── <account-id>.json
├── database/
│   └── icloudharbor.db
├── sessions/
│   └── <account-id>/
│       ├── harbor-auth-state.json
│       └── ...                     # pyicloud Cookie/Session
├── notification-keys/
│   └── wecom-secret                # 仅在配置企业微信时存在
├── locks/
└── tmp/

/photos/
├── .icloudharbor-mounted
└── YYYY/MM/DD/...                  # 默认命名模板
```

重要约束：

- `/config` 与 `/photos` 必须持久化。
- bootstrap 生成的 `destination.path` 是 `/photos`，对应宿主机 `IH_PHOTOS_PATH` 根目录；
  账号 ID 默认直接使用 `IH_APPLE_ID`，不会创建同名照片子目录。显式设置 `IH_ACCOUNT_ID`
  才会覆盖该 ID；账号 ID 同时用于 SQLite、Session 目录和凭据文件名。
- README 的标准群晖示例映射是 `/volume1/docker/icloudharbor` → `/config`、
  `/volume2/photos/iCloud` → `/photos`，挂载标记位于
  `/volume2/photos/iCloud/.icloudharbor-mounted`。
- 受支持的生产布局应把下载目标放在 `/photos` 卷内。当前 Pydantic 模型不强制路径前缀，
  预检只验证配置目标本身，因此不要误把“代码接受任意路径”当作受支持的 Docker 布局。
- 挂载标记必须位于实际 `destination.path` 内，是防止卷未挂载时误写容器层的保护，不得
  通过删除检查或更改常量绕过。
- Apple 密码不会进入 `.env`、Compose 或命令参数。
- 一键安装器必须从 `/dev/tty` 读取交互输入；经管道执行时不得从标准输入读取提示答案。
- 一键安装的控制目录和 `.env` 必须由 root 管理，不能把控制目录直接挂载为容器可写的
  `/config`；Compose 项目名保存在安装器管理标记中，重跑时不得重新推断或任意改变。
- 安装器只可调整自己新建的专用目录，不得递归 `chown` 已有照片库或擅自修改 NAS ACL。
- 检测到已有 `.env` 时，安装器不得覆盖账号、路径、通知密钥或任何持久化内容；只能更新
  Compose 文件、拉取镜像、重建容器并重新执行 `doctor`。
- 保存的密码使用 AES-256-GCM，但密钥和密文都在 `/config/credentials`，宿主机 root
  仍可恢复密码；此设计用于无人值守续期和防止意外明文泄露，不等同于硬件密钥保护。
- Apple Cookie/Session、SQLite、通知密钥、加密密钥和凭据都属于敏感数据；整个 `/config`
  应按敏感数据保护，日志或 Issue 中不得上传其原文。

## 6. 不可破坏的生产规则

- 不得增加远端删除调用。
- `auto_delete` 必须默认 `false`；开启时只能读取个人图库“最近删除”，不得把普通图库中暂时
  不可见的 Asset 推断为已删除。
- 本地自动删除只能使用账号、图库和 Asset ID 的精确 SQLite 记录；严禁按文件名或模糊信息猜测。
- 删除前必须确认路径位于受管根目录、不是符号链接或目录、没有多 Asset 归属冲突，并重新校验
  大小和 SHA-256。人工修改、未跟踪或无法确认的文件必须失败关闭，不删除空目录。
- 删除意图和 `remote_deleted` 状态必须先提交 SQLite，再执行 `unlink`；中途退出后下轮应能幂等
  继续，已删除项目恢复到普通图库时应重新下载。
- 不得在没有挂载标记时下载。
- 不得把 Apple 密码、验证码、Cookie、令牌或真实账号写入日志、测试、Git 或镜像层。
- 不得让业务模块直接导入 `pyicloud`；协议变化只能在 `protocol/` 内处理。
- 不得在部分下载失败后提交同步游标。
- 正式文件必须由已校验的同文件系统 `.part` 文件原子替换。
- `DownloadManager` 在 `os.replace()` 前先写入数据库提交意图是故障恢复设计：进程在两步间
  退出时，下次计划会发现正式文件缺失并修复确定路径。不要随意颠倒这两个操作。
- SHA-256 总会为本地文件计算并保存，但仅在 Apple 返回有效 SHA-256 时比较；远端大小为空时
  也不能伪造期望值。
- 配置必须保持 `extra="forbid"`，未知参数和已删除的旧参数应报错，不得静默忽略或恢复未经
  明确要求的迁移兼容。
- 新增 Docker 参数时，必须同步更新 loader、Compose、`.env.example`、测试和
  `CONFIGURATION.md`；若影响首次部署或日常命令，还要更新 `README.md`。
- 数据库当前只有 `create_all()`，没有 Alembic 等迁移框架。修改既有表结构前必须设计旧库
  升级路径，并用旧 schema/旧数据库夹具验证，不能只让全新数据库测试通过。
- 后处理顺序必须保证原始资源和转换 JPEG 最终都以 iCloud `created_at` 作为 mtime；
  Synology Photos 兼容 touch 不能把最终时间留成下载时刻。
- 项目只保留 `AGENTS.md`、`CONFIGURATION.md`、`README.md` 三个 Markdown 文件。

## 7. 变更导航与验证

先按改动类型确定联动面，不要只修改最先搜到的文件：

| 改动类型 | 主要实现 | 至少检查的测试与文档 |
| --- | --- | --- |
| Apple 认证、字段或资源兼容 | `protocol/base.py`、`models.py`、`exceptions.py`、`pyicloud_adapter.py` | `test_protocol_adapter.py`、认证集成测试；不得把底层对象扩散到业务层 |
| 配置字段或 Docker 参数 | `config/models.py`、`loader.py`、Compose、`.env.example` | `test_config.py`、`CONFIGURATION.md`；新手流程受影响时同步 `README.md` |
| `setup`、续期或后台交接 | `cli.py`、`application.py`、`auth/`、repository 的请求代次、scheduler | `test_auth_and_cli.py`、`test_scheduler.py`、`test_security.py`、README 命令 |
| 扫描、筛选、命名或游标 | `photos/engine.py`、`planner.py`、`policies.py`、`naming.py` | `test_sync_engine.py`、`test_policies.py`、`test_naming.py`；复核失败时不提交游标 |
| 下载、校验、时间戳或转换 | `download/`、planner 的修复判定 | `test_sync_engine.py`、`test_postprocess.py`；复核 `.part`、原子替换和 mtime |
| SQLite 模型、锁或调度 | `database/`、`scheduler/` | `test_repository.py`、`test_scheduler.py`、集成测试；必须考虑旧库升级 |
| 通知、日志或用户可见路径 | `notify/`、`application.py`、`observability/` | `test_notify.py`、`test_observability.py`；检查脱敏、开关和结构化 payload |
| 依赖、镜像或发布 | `pyproject.toml`、`uv.lock`、Dockerfile、Compose、CI | Python 3.12/3.13、两套 Compose 配置、amd64/arm64 构建 |
| 一键安装与升级 | `deploy/install.sh`、Compose、`.env.example` | `bash -n`、ShellCheck（可用时）、管道输入与 `/dev/tty`、首次/重跑两条路径、README 命令 |

开发环境使用 Python 3.12 或 3.13 与 `uv`。首次安装依赖：

```bash
uv sync --frozen --extra dev
```

`tests/` 仅在维护者本机存在。目录可用时按风险先运行聚焦测试，例如：

```bash
uv run pytest tests/unit/test_config.py
uv run pytest tests/unit/test_protocol_adapter.py
uv run pytest tests/integration/test_auth_and_cli.py
uv run pytest tests/integration/test_sync_engine.py
```

发布前完整门禁；没有本地 `tests/` 时跳过 pytest，但不得声称测试已通过：

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/icloudharbor
uv run pytest --cov=icloudharbor --cov-report=term-missing
uv build
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.build.yml config --quiet
docker build .
bash -n deploy/install.sh
```

Compose 校验要求仓库根目录已有 `.env`；缺少时可从 `.env.example` 复制测试值。不得使用不带
`--quiet` 的 `docker compose config`，否则 `env_file` 内容可能被展开到终端。

提交前还必须：

- 用 `git diff --check` 检查空白错误，确认只包含任务范围内的改动。
- 扫描 diff 和未跟踪文件中的邮箱、密码、Apple Cookie、私钥、通知令牌和 `.env`。
- 确认 shell 文件为 LF，镜像以非 root 账号运行，Compose 未增加业务端口。
- 从全新配置视角复核 README 命令、宿主机路径、容器路径和挂载标记是否互相一致。
- 自动化测试不得连接真实 Apple 服务；真实账号验证只能由维护者在受控环境执行。

## 8. 已验证事实与风险

以下带日期内容是历史验证快照，不替代当前分支测试结果；修改后必须重新运行与改动匹配的检查：

- 已在 Synology Docker 环境完成真实 Apple Account 双重认证和个人图库下载闭环。
- 已验证中国大陆服务区域、星号密码输入、Session 续期、配置自动生成和下载目录保护。
- 已验证真实日期范围样本能完成照片资源下载。
- 2026-07-30 的 0.3.0 参数精简：删除 11 个伪参数、合并 4 组重叠参数（photo_version→
  photo_size、interval→schedule、no_changes→success、umask→固定 0022）。0.3.0 当时提供过
  迁移提示；当前版本已经删除兼容逻辑，旧 YAML 键会被 `extra="forbid"` 拒绝。
- 2026-07-31 的 0.3.4 交互改进：认证命令通过 SQLite 请求代次把首次/续期同步交给 daemon，
  下载日志统一进入主容器；新手同步参数恢复为纯数字小时，默认 24 小时并在启动时检查。
  130 项测试通过，覆盖率 80%，Ruff、格式检查与严格 mypy 全部通过。
- 2026-07-31 的 0.3.5 时间戳、通知与账号 ID 改进：下载资源和转换 JPEG 的文件修改时间恢复
  为 iCloud 拍摄时间，群晖索引兼容处理后不再保留下载时间，全量扫描会校正历史文件；启动与
  同步结果通知按真实状态使用可读中文文案；默认账号 ID 直接使用 `IH_APPLE_ID`。145 项测试
  通过，覆盖率 81%，Ruff、格式检查与严格 mypy 全部通过。
- 2026-07-31 的 0.3.6 并发入库修复：Asset、Resource 和本地文件改用 SQLite 原子 UPSERT，
  修复同一 Asset 多资源并发完成时的唯一键竞态；未显式设置 `IH_ACCOUNT_NAME` 时，账号显示
  名称跟随 `IH_APPLE_ID`。
- 2026-07-31 的 0.3.7 认证通知改进：首次未认证启动合并启动与等待认证消息，使用 SQLite
  持久去重同一认证问题；`setup` 和 `session renew` 成功后发送认证恢复消息并提交后台同步
  请求，认证成功后重新允许未来的新认证问题触发提醒。
- 2026-08-01 的 0.3.8 认领策略放宽：Tier 2 文件认领不再要求远端 size 匹配或非空，
  磁盘上已有文件即哈希入库、跳过下载；消除数据库丢失后因 size 不匹配导致的 _AssetID
  重复文件。
- 2026-08-01 的 0.3.9 同轮冲突跳过：同一 sync 轮次内多个 Asset 竞争相同路径时，
  第二个直接跳过（下轮认领），不再重命名产生 _AssetID 副本。
- 2026-08-01 的 0.3.10 错误映射修复与默认串行下载：修复 pyicloud 丢失 HTTP response
  导致限流/服务不可用被误判为 UNKNOWN_PROTOCOL_ERROR 而不可重试的问题；_response_status
  增加 exc.code 整数回退识别 HTTP 状态码；UNKNOWN_PROTOCOL_ERROR 纳入可重试集合；
  兜底错误消息包含原始异常详情；默认并发下载数从 2 降为 1（串行），降低 Apple 限流概率。
- 2026-08-03 的 0.3.11 本地删除同步：新增默认关闭的 `IH_AUTO_DELETE`，读取个人图库“最近删除”
  并按账号、图库和 Asset ID 精确匹配已记录文件；删除前复核受管路径、归属、普通文件类型、
  大小与 SHA-256，拒绝同名猜测、符号链接、人工修改和多 Asset 路径冲突；`sync plan` 可安全预览，
  照片恢复到普通图库后会重新下载，始终不调用 iCloud 远端删除接口。
- 2026-08-03 的 0.4.0 发布：把最近删除本地同步作为 0.4 系列正式版本发布，统一源码、示例配置、
  README 和锁文件版本；`v0.4.0` 标签触发 amd64/arm64 镜像构建并更新 Docker Hub 的完整版本号
  与 `latest` 标签。
- amd64/arm64 镜像构建结果以对应 GitHub Actions 发布提交为准。

主要外部风险是 Apple 私有接口与返回字段可能变化。出现协议异常时，应先在
`protocol/pyicloud_adapter.py` 添加兼容和回归测试，不能把底层对象泄露到业务层。


## 9. 发布规则

- `.github/workflows/ci.yml` 会在每次 push 和 PR 上执行静态检查及构建；checkout 中存在
  `tests/` 时才运行 pytest。只有 Git ref 以 `refs/tags/v` 开头时才登录并推送 Docker Hub。
  普通 `git push` 不发布镜像。
- `latest` 只是可变标签。`docker compose up -d` 不负责查询远端更新，群晖下载新镜像后也不会
  自动替换已经运行的旧容器。升级必须依次执行 `docker compose pull` 和
  `docker compose up -d --force-recreate --remove-orphans`，再以容器内
  `icloudharbor --version` 为准；Container Manager 页面可能仍显示旧创建时间或缓存信息。
- 若 `docker compose config --images` 输出 `icloudharbor:local`，说明误用了
  `docker-compose.build.yml`，运行的不是 Docker Hub 镜像。若私有仓库拉取失败，Docker
  也可能继续保留旧本地镜像，应先 `docker login` 并检查 pull 输出。仍取得旧摘要时再排查
  registry mirror 或代理缓存。
- 发布时先同步 `pyproject.toml` 与 `src/icloudharbor/__init__.py`，再运行 `uv lock` 更新
  `uv.lock`；同时更新 `.env.example`、`README.md` 与本文件中的展示版本，并全仓搜索旧版本号。
- 完整门禁通过后创建带说明的版本标签，只推送目标标签，例如
  `git push origin v0.4.0`。不要使用 `git push --tags`：本地存在而远端已不存在的旧标签可能
  重新触发发布并把 `latest` 回退。
- 从 `v0.3.4` 起发布工作流只生成完整版本号和 `latest` 两个 Docker Hub 标签，不再生成
  `0.3` 和 `sha-*` 标签。

## 10. icloudpd 认证调查附录

以下结论只用于解释既有设计决策，不是 iCloudHarbor 的运行契约。它们于 2026-07-31 基于
[`boredazfcuk/docker-icloudpd`](https://github.com/boredazfcuk/docker-icloudpd) 提交
`e2d9aa01abe97f669fec6517cd44a251621d7560`、容器 `1.0.1369_30-05-2026`（固定
`icloudpd 1.32.3`）核对；若要依赖上游当前行为，必须重新检查最新源码。

### 10.1 icloudpd 如何等待初始化

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

### 10.2 icloudpd 的 `--Initialise`

- 没有 keyring 时，`--Initialise` 先执行 `icloud --username ...`，由 keyring 后端询问并保存
  Apple 密码；然后把已有 Cookie/Session 移为备份，执行
  `icloudpd --auth-only --cookie-directory /config`，按需询问 MFA 验证码并生成新 Cookie。
  脚本只在 Cookie 含受信任会话标志时报告成功，然后退出；已等待的前台进程继续同步。
- 已有 keyring 时再次运行 `--Initialise`，不会再次询问或替换 Apple 密码。它直接复用 keyring
  中的密码，备份现有 Cookie/Session，并强制重新执行认证和生成 Cookie。若 Apple 密码已经
  修改，应先运行 `sync-icloud.sh --Remove-Keyring`，再运行 `--Initialise`。
- `--Initialise` 进程自身不进入长期下载循环，因为参数分支通过 `run_action` 在 Cookie 生成后
  退出；真正的同步仍由容器前台已有进程执行。

### 10.3 icloudpd 的 `reauth.sh`

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

### 10.4 与 iCloudHarbor 的对应关系

- iCloudHarbor 的前台进程始终是独立调度器；没有凭据或 Session 时，容器日志会明确提示
  `docker exec -it icloudharbor icloudharbor setup`。交互进程通过 SQLite 请求代次与后台
  交接，不依赖主容器标准输入或强制重启。
- iCloudHarbor 的 `setup` 与 icloudpd 重复执行 `--Initialise` 不同：每次都先清除旧 Session、
  重新询问密码、覆盖本地 AES-256-GCM 凭据、完成 MFA、检查图库/相册，然后写入持久化请求
  并退出。主 daemon 刷新协议对象后立即执行正式同步，因此全部下载日志进入 `docker logs`。
- iCloudHarbor 的 `session renew` 对应 `reauth.sh`：清除旧 Session，复用保存的本地凭据，
  Apple 要求时只询问验证码，成功后请求后台立即同步并退出。若本地凭据不存在，则要求改用
  `setup`。
