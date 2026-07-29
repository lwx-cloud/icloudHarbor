# iCloudHarbor 配置与命令参考

本文列出 iCloudHarbor `0.1.0` 的全部公开配置参数、取值、默认值和命令。普通单账号部署只需
编辑 `.env`；程序会在首次启动时自动生成 `/config/config.yaml`。

## 1. 配置工作方式

配置来源按优先级从高到低为：

1. CLI 全局参数 `--config /path/to/config.yaml`；
2. `IH_CONFIG_FILE` 指定的配置文件路径；
3. 默认配置文件 `/config/config.yaml`；
4. 加载 YAML 后，所有非空 `IH_*` 业务环境变量覆盖对应 YAML 值。

Docker Compose 已把 `IH_CONFIG_FILE` 固定为 `/config/config.yaml`，通常不需要修改。

首次启动：

- 如果配置文件不存在，必须提供非空 `IH_APPLE_ID`。
- 入口程序根据环境变量和默认值生成完整 YAML。
- 新文件权限设为 `0600`。

后续启动：

- 已有 YAML 不会被重新生成或覆盖。
- 非空环境变量仍会在每次运行时覆盖 YAML，但不会回写文件。
- 空字符串被视为“未设置”。

需要特别注意：首次生成时的环境变量值会写入 YAML。例如第一次启动就设置了日期筛选，之后
仅把 `.env` 中的日期清空，YAML 里的日期仍然存在；此时应编辑 `config.yaml` 将值改为
`null`，或在确认不需要保留状态后重新生成配置。

查看当前实际生效配置：

```bash
docker exec icloudharbor icloudharbor config show
```

该输出包含 Apple ID，请勿直接粘贴到公开 Issue。

## 2. 通用值格式

### 布尔值

以下写法均可，不区分大小写：

- 真：`true`、`yes`、`on`、`1`
- 假：`false`、`no`、`off`、`0`

### 容量

可直接写非负字节数，也可以使用：

- 十进制：`KB`、`MB`、`GB`、`TB`
- 二进制：`KiB`、`MiB`、`GiB`、`TiB`

示例：`1048576`、`1MB`、`64 MiB`、`10GB`。

### 时长

可写非负秒数、单单位简写或 ISO 8601：

- `s` 秒、`m` 分钟、`h` 小时、`d` 天、`w` 周
- 示例：`30m`、`6h`、`30d`、`P30D`、`PT6H`

### 日期时间

使用 ISO 8601，并建议明确时区：

```text
2026-07-18T00:00:00+08:00
2026-07-18T23:59:59+08:00
```

`created_after` 和 `created_before` 都包含边界时刻。

### Cron

使用 5 段 Cron：

```text
分钟 小时 日 月 星期
```

示例 `0 3 * * *` 表示按 `IH_TIMEZONE` 每天 03:00。

## 3. Docker 与宿主机参数

这些参数控制容器本身，不写入应用 YAML。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_CONTAINER_NAME` | `icloudharbor` | 容器名称，也是 README 中 `docker exec` 使用的名称。 |
| `IH_CONFIG_PATH` | `./data/config` | 宿主机状态目录，挂载到容器 `/config`。必须持久化并限制访问。 |
| `IH_PHOTOS_PATH` | `./data/photos` | 宿主机照片根目录，挂载到容器 `/photos`。 |
| `IH_PUID` | `1000` | 容器业务进程的数字 UID，必须大于 0。 |
| `IH_PGID` | `1000` | 容器业务进程的数字 GID，必须大于 0。 |
| `IH_UMASK` | `0022` | 新文件权限掩码，范围 `0000` 到 `0777`。 |
| `IH_TIMEZONE` | `UTC` | 同时设置容器 `TZ` 和调度器时区，例如 `Asia/Shanghai`。 |

`IH_CONFIG_PATH` 和 `IH_PHOTOS_PATH` 是宿主机路径；`IH_DESTINATION` 是容器内路径，不要混用。

容器不需要 `privileged`，不应添加业务端口。Compose 默认丢弃全部 Linux capabilities，只保留
入口阶段调整 UID/GID 和属主所需的 `CHOWN`、`SETGID`、`SETUID`，随后业务进程以非 root
用户运行。

## 4. 运行与日志参数

| 环境变量 | YAML 字段 | 默认值 | 可选值/说明 |
| --- | --- | --- | --- |
| `IH_TIMEZONE` | `runtime.timezone` | `UTC` | IANA 时区，如 `Asia/Shanghai`。 |
| `IH_LOG_LEVEL` | `runtime.log_level` | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`。 |
| `IH_LOG_FORMAT` | `runtime.log_format` | `text` | `text` 或适合日志平台的 `json`。 |

以下运行字段只可在 YAML 中设置：

| YAML 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `runtime.database` | `/config/database/icloudharbor.db` | SQLite 状态库路径。修改前应停止容器并迁移数据库。 |
| `runtime.temp_path` | `/config/tmp` | 内部工作目录；启动时创建，并纳入可写性就绪检查。 |

## 5. 账号与目标目录参数

| 环境变量 | YAML 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `IH_ACCOUNT_ID` | `accounts[0].id` | `personal` | 稳定账号 ID；1–64 个字母、数字、`_`、`-`，首字符必须是字母或数字。创建状态库后不建议修改。 |
| `IH_ACCOUNT_NAME` | `accounts[0].name` | `我的 iCloud` | 账号显示名称，用于状态和通知。 |
| `IH_APPLE_ID` | `accounts[0].apple_id` | 无 | Apple Account 邮箱；首次生成配置时必填。 |
| `IH_REGION` | `accounts[0].region` | `auto` | `auto`、`global` 或 `china`。 |
| `IH_DESTINATION` | `accounts[0].destination.path` | `/photos/personal` | 容器内下载目标。通常应位于 `/photos` 下。 |
| `IH_MOUNTED_MARKER` | `accounts[0].destination.mounted_marker` | `.icloudharbor-mounted` | 目标目录内必须存在的空标记文件名。只能是单个安全文件名。 |
| `IH_MINIMUM_FREE_SPACE` | `accounts[0].destination.minimum_free_space` | `10GB` | 同步结束后必须保留的最小空间；计划大小也会计入检查。 |

仅 YAML 可设置：

| YAML 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `accounts[0].enabled` | `true` | 是否启用。当前版本必须且只能有一个启用账号。 |
| `accounts[0].libraries` | `[root]` | 图库 ID。当前版本只能是个人图库 `[root]`。 |

挂载标记示例：

```bash
mkdir -p ./data/photos/personal
touch ./data/photos/personal/.icloudharbor-mounted
```

该保护用于避免照片卷挂载失败时把数据误写进容器可写层。

## 6. 媒体参数

| 环境变量 | YAML 字段 | 默认值 | 可选值/说明 |
| --- | --- | --- | --- |
| `IH_DOWNLOAD_PHOTOS` | `accounts[0].media.photos` | `true` | 是否下载照片 Asset。 |
| `IH_DOWNLOAD_VIDEOS` | `accounts[0].media.videos` | `true` | 是否下载普通视频 Asset。 |
| `IH_DOWNLOAD_LIVE_PHOTOS` | `accounts[0].media.live_photos` | `true` | 是否保留 Live Photo 的图片与视频伴随资源。 |
| `IH_PHOTO_VERSION` | `accounts[0].media.photo_version` | `original` | `original` 原片、`adjusted` 编辑版、`both` 两者。也用于视频原版/编辑版选择。 |
| `IH_RAW_MODE` | `accounts[0].media.raw.mode` | `both` | RAW 与 JPEG 伴随资源策略，见下表。 |

RAW 模式：

| 值 | 行为 |
| --- | --- |
| `raw_only` | 只选择 RAW 原始资源。 |
| `jpeg_only` | 只选择 JPEG 替代资源。 |
| `both` | RAW 与 JPEG 都选择。 |
| `prefer_raw` | 有 RAW 时优先纳入 RAW；适配器没有独立 RAW 标记时保留可用原始资源。 |
| `prefer_jpeg` | 有 JPEG 替代资源时优先纳入 JPEG；适配器没有独立标记时保留可用原始资源。 |

Live Photo 属于照片 Asset。关闭普通视频不会单独拆掉已启用 Live Photo 的视频伴随资源；如需
完全排除 Live Photo 视频，请关闭 `IH_DOWNLOAD_LIVE_PHOTOS`。

## 7. 筛选参数

| 环境变量 | YAML 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `IH_CREATED_AFTER` | `accounts[0].filters.created_after` | 空 | 只保留创建时间不早于该时刻的 Asset。 |
| `IH_CREATED_BEFORE` | `accounts[0].filters.created_before` | 空 | 只保留创建时间不晚于该时刻的 Asset。 |
| `IH_FAVORITES_ONLY` | `accounts[0].filters.favorites_only` | `false` | 只下载收藏项目。 |
| `IH_INCLUDE_HIDDEN` | `accounts[0].filters.include_hidden` | `false` | 是否包含隐藏项目。 |

只下载 2026 年 7 月 18 日（上海时区）的临时示例：

```dotenv
IH_CREATED_AFTER=2026-07-18T00:00:00+08:00
IH_CREATED_BEFORE=2026-07-18T23:59:59.999999+08:00
```

确认流程后若要恢复全量备份，需要同时清空环境覆盖，并检查生成的 `config.yaml` 是否仍保存
日期；如有，将 `created_after`、`created_before` 改为 `null`。

YAML 中还存在：

```yaml
filters:
  albums: []
  exclude_albums: []
```

当前版本尚未实现按相册筛选，这两个列表必须保持为空；配置其他值会直接报错。

## 8. 路径和文件名参数

| 环境变量 | YAML 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `IH_FOLDER_STRUCTURE` | `accounts[0].naming.folder_structure` | `{created:%Y/%m/%d}` | 目标目录内的相对目录模板。不能是绝对路径，也不能包含 `..`。 |
| `IH_FILENAME_TEMPLATE` | `accounts[0].naming.filename` | `{original_name}` | 文件名模板，不能包含 `/` 或 `\`。 |
| `IH_CONFLICT_POLICY` | `accounts[0].naming.conflict_policy` | `suffix_asset_id` | 重名处理策略。 |
| `IH_KEEP_UNICODE` | `accounts[0].naming.keep_unicode` | `true` | 是否保留中文等 Unicode 字符；关闭时尽量转为 ASCII。 |

可用模板变量：

| 变量 | 含义 |
| --- | --- |
| `{account}` | 账号 ID。 |
| `{library}` | 图库 ID，当前为 `root`。 |
| `{album}` | 预留相册名；当前版本为空字符串。 |
| `{asset_id}` | 完整远端 Asset ID。 |
| `{asset_id_short}` | 清理后的 Asset ID 最后 8 位。 |
| `{created}` | 创建时间，支持 Python 日期格式，如 `{created:%Y-%m}`。 |
| `{added}` | 加入图库时间；缺失时回退到创建时间。 |
| `{original_name}` | 当前 Resource 的原始文件名。 |
| `{stem}` | 不含扩展名的原始文件名。 |
| `{extension}` | 含点的扩展名，如 `.HEIC`。 |
| `{media_type}` | `photo` 或 `video`。 |

示例：

```dotenv
IH_FOLDER_STRUCTURE={created:%Y/%m}
IH_FILENAME_TEMPLATE={created:%Y%m%d_%H%M%S}_{original_name}
```

程序会清理控制字符、Windows 非法字符和保留文件名，并限制单个路径段长度。Live Photo、RAW
等伴随资源会保留各自实际扩展名。

重名策略：

| 值 | 行为 |
| --- | --- |
| `suffix_asset_id` | 只有发生冲突时追加短 Asset ID。 |
| `always_asset_id` | 所有文件名都追加短 Asset ID。 |
| `timestamp` | 冲突时追加创建时间 `YYYYMMDD_HHMMSS`。 |
| `error` | 发现目标冲突时终止计划。 |

## 9. 同步与调度参数

| 环境变量 | YAML 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `IH_SYNC_STRATEGY` | `accounts[0].sync.strategy` | `cursor` | `cursor` 使用增量游标并定期全量校准；`full` 每次全量扫描。 |
| `IH_FULL_SCAN_INTERVAL` | `accounts[0].sync.full_scan_interval` | `30d` | `cursor` 策略下两次强制全量扫描的最大间隔。 |
| `IH_SCHEDULE` | `accounts[0].sync.schedule` | `0 3 * * *` | 5 段 Cron。与 `IH_SYNC_INTERVAL` 二选一。 |
| `IH_SYNC_INTERVAL` | `accounts[0].sync.schedule.interval` | 空 | 固定间隔，如 `6h`。与 `IH_SCHEDULE` 二选一。 |
| `IH_RUN_ON_START` | `accounts[0].sync.run_on_start` | `false` | 容器调度器启动后是否立即安排一次同步。 |

`accounts[0].sync.mode` 只可为 `backup`。当前没有镜像或双向模式。

若 `cursor` 无效、从未完成全量扫描，或超过 `full_scan_interval`，程序自动回退到全量扫描。
只有一次运行的全部下载成功时才更新游标。

示例：每 6 小时执行一次：

```dotenv
IH_SCHEDULE=
IH_SYNC_INTERVAL=6h
```

示例：上海时区每天 02:30：

```dotenv
IH_TIMEZONE=Asia/Shanghai
IH_SCHEDULE=30 2 * * *
IH_SYNC_INTERVAL=
```

## 10. 下载参数

| 环境变量 | YAML 字段 | 默认值 | 范围/说明 |
| --- | --- | --- | --- |
| `IH_DOWNLOAD_CONCURRENCY` | `accounts[0].download.concurrency` | `2` | 并发数 1–8。NAS 建议先使用 2。 |
| `IH_CHUNK_SIZE` | `accounts[0].download.chunk_size` | `1MB` | 流式块大小，64 KiB–64 MiB。 |
| `IH_DOWNLOAD_TIMEOUT` | `accounts[0].download.timeout` | `300` | 单次下载 HTTP 超时秒数，1–3600。 |
| `IH_MAX_RETRIES` | `accounts[0].download.max_retries` | `5` | 每个 Resource 的额外重试次数，0–20。 |
| `IH_VERIFY_HASH` | `accounts[0].download.verify_hash` | `true` | 判断已有文件是否完整时，使用数据库保存的 SHA-256 重新校验。新下载始终计算 SHA-256，并校验可用的远端大小/校验值。 |
| `IH_KEEP_PARTIAL` | `accounts[0].download.keep_partial` | `true` | 保留 `.part` 文件供下次断点续传。 |

可重试错误包括限流、Apple 服务暂不可用、网络超时、过期下载地址和数据完整性失败。退避采用
带随机抖动的指数策略，最长单次等待 60 秒。

## 11. 通知开关

| 环境变量 | YAML 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `IH_NOTIFY_STARTUP` | `notifications.startup` | `false` | 守护进程启动通知。 |
| `IH_NOTIFY_SUCCESS` | `notifications.success` | `true` | 有变化的成功同步通知。 |
| `IH_NOTIFY_NO_CHANGES` | `notifications.no_changes` | `false` | 成功但没有下载内容时也通知。 |
| `IH_NOTIFY_FAILURE` | `notifications.failure` | `true` | 失败和部分失败通知。 |
| `IH_NOTIFY_AUTH_REQUIRED` | `notifications.auth_required` | `true` | 需要重新认证时通知。 |

开关只决定哪些事件可以发送。还必须在 YAML 的 `notifications.channels` 中配置至少一个通道。
通道不能通过当前 Docker 环境变量定义。

### Bark

```yaml
notifications:
  channels:
    - type: bark
      enabled: true
      server: https://api.day.app
      device_key_file: /config/notification-keys/bark-device-key
      timeout: 10
```

`server` 可省略，默认使用 `https://api.day.app`。

### Server酱

```yaml
notifications:
  channels:
    - type: serverchan
      enabled: true
      send_key_file: /config/notification-keys/serverchan-send-key
      timeout: 10
```

### Telegram

```yaml
notifications:
  channels:
    - type: telegram
      enabled: true
      token_file: /config/notification-keys/telegram-token
      chat_id: "123456789"
      timeout: 10
```

### Webhook

```yaml
notifications:
  channels:
    - type: webhook
      enabled: true
      url: https://example.com/icloudharbor/events
      secret_file: /config/notification-keys/webhook-secret
      timeout: 10
```

设置 `secret_file` 后，请求体使用 HMAC-SHA256 签名，十六进制签名放在
`X-iCloudHarbor-Signature` 请求头。Webhook 不自动跟随重定向。

通知令牌文件与 Apple 密码无关。请在宿主机配置目录创建这些文件，只写一行令牌，并让
`IH_PUID:IH_PGID` 可读：

```bash
mkdir -p ./data/config/notification-keys
chmod 700 ./data/config/notification-keys
chmod 600 ./data/config/notification-keys/*
```

通道 `timeout` 范围为 1–60 秒。`enabled: false` 的通道可以保留不完整参数且不会加载凭据。

## 12. 安全配置

这些字段只可在 YAML 中设置：

| YAML 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `security.redact_apple_id` | `true` | 在账号列表和设置提示中遮盖 Apple ID 中间部分。设为 `false` 会显示完整邮箱，不建议。 |
| `security.session_encryption` | `false` | 当前未实现；设为 `true` 会拒绝启动。 |
| `security.allow_remote_delete` | `false` | 只能为 `false`；用于保证配置不能开启远端删除。 |

Apple 密码不属于 YAML 参数。`icloudharbor setup` 在 TTY 中读取密码，认证成功后把密码以
AES-256-GCM 保存到 `/config/credentials`，权限为目录 `0700`、文件 `0600`。密钥和密文位于
同一配置卷，因此宿主机 root 仍可恢复密码。

## 13. 完整 YAML 示例

普通部署不需要手工创建此文件。该示例用于高级通知配置、审计和故障排查：

```yaml
version: 1

runtime:
  timezone: Asia/Shanghai
  log_level: INFO
  log_format: text
  database: /config/database/icloudharbor.db
  temp_path: /config/tmp

accounts:
  - id: personal
    name: 我的 iCloud
    apple_id: user@example.com
    region: auto
    enabled: true
    libraries:
      - root

    destination:
      path: /photos/personal
      mounted_marker: .icloudharbor-mounted
      minimum_free_space: 10GB

    media:
      photos: true
      videos: true
      live_photos: true
      photo_version: original
      raw:
        mode: both

    filters:
      albums: []
      exclude_albums: []
      created_after: null
      created_before: null
      favorites_only: false
      include_hidden: false

    naming:
      folder_structure: "{created:%Y/%m/%d}"
      filename: "{original_name}"
      conflict_policy: suffix_asset_id
      keep_unicode: true

    sync:
      mode: backup
      strategy: cursor
      full_scan_interval: 30d
      schedule: "0 3 * * *"
      run_on_start: false

    download:
      concurrency: 2
      chunk_size: 1MB
      timeout: 300
      max_retries: 5
      verify_hash: true
      keep_partial: true

notifications:
  startup: false
  success: true
  no_changes: false
  failure: true
  auth_required: true
  channels: []

security:
  redact_apple_id: true
  session_encryption: false
  allow_remote_delete: false
```

固定间隔也可以写成：

```yaml
schedule:
  interval: 6h
```

或显式 Cron 对象：

```yaml
schedule:
  cron: "0 3 * * *"
```

对象形式必须且只能设置 `interval`、`cron` 其中一个。

修改 YAML 的安全流程：

```bash
docker compose stop
cp ./data/config/config.yaml ./data/config/config.yaml.backup
# 编辑 ./data/config/config.yaml
docker compose run --rm icloudharbor icloudharbor config validate
docker compose up -d
docker exec icloudharbor icloudharbor doctor
```

## 14. 命令参考

所有命令都支持全局配置参数：

```text
icloudharbor --config /path/to/config.yaml <命令>
icloudharbor --version
```

### 初始化与认证

| 命令 | 说明 |
| --- | --- |
| `icloudharbor setup [--account ID]` | 检查环境、星号读取密码、完成 2FA、保存续期凭据并探测个人图库。 |
| `icloudharbor session renew [--account ID]` | 清除旧 Session，使用本地保存密码重新认证；需要时询问验证码。 |
| `icloudharbor session status [--account ID]` | 显示数据库中的认证状态。 |
| `icloudharbor session clear [--account ID]` | 删除 Session、Cookie 和认证状态，不删除保存的密码。 |
| `icloudharbor credentials status [--account ID]` | 显示 `SAVED` 或 `MISSING`。 |
| `icloudharbor credentials clear [--account ID]` | 删除当前账号的本地保存密码。 |

如果密码已修改或凭据丢失，运行 `setup`，不要反复运行 `session renew`。

### 配置与远端信息

| 命令 | 说明 |
| --- | --- |
| `icloudharbor config bootstrap` | 配置不存在时从环境生成；已存在时只校验，不覆盖。容器入口会自动调用。 |
| `icloudharbor config validate` | 严格校验 YAML 和环境覆盖。 |
| `icloudharbor config show` | 输出当前生效配置，不包含密码，但包含 Apple ID。 |
| `icloudharbor accounts list` | 显示账号、启用状态、认证状态和目标目录。 |
| `icloudharbor libraries list [--account ID]` | 认证后列出可见图库。 |
| `icloudharbor albums list [--account ID] [--library root]` | 列出图库相册；当前不能把相册用于同步筛选。 |

### 同步

| 命令 | 说明 |
| --- | --- |
| `icloudharbor sync plan [--account ID] [--full-scan]` | 只扫描和生成计划，不下载、不提交游标。 |
| `icloudharbor sync run [--account ID] [--dry-run] [--full-scan]` | 执行同步；`--dry-run` 等同只读计划。 |
| `icloudharbor sync status [--limit 10]` | 查看最近 1–100 次运行记录。 |

### 数据库、健康与守护进程

| 命令 | 说明 |
| --- | --- |
| `icloudharbor database check` | 执行 SQLite 完整性检查。 |
| `icloudharbor database backup [--output PATH]` | 使用 SQLite 在线备份 API 创建一致性备份。 |
| `icloudharbor doctor` | 检查数据库、临时目录、下载目录、挂载标记、写权限、空间和认证状态。 |
| `icloudharbor status` | 显示健康状态和最近一次同步。 |
| `icloudharbor healthcheck [--liveness\|--readiness]` | 容器存活或完整就绪检查。 |
| `icloudharbor daemon` | 启动前台调度器；这是镜像默认命令。 |

在 Compose 部署中，把上面的命令放在：

```bash
docker exec -it icloudharbor <命令>
```

非交互查询可去掉 `-it`。
