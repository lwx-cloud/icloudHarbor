# iCloudHarbor 配置参数

本文列出 iCloudHarbor 当前版本支持的全部配置参数，并明确哪些参数必填。

iCloudHarbor 推荐采用与 docker-icloudpd 类似的方式：

1. `.env` 只填写首次启动必需的参数；
2. 首次启动自动生成 `/config/config.yaml`；
3. 其他功能从本文查找参数，按需加入 `.env` 或 `config.yaml`；
4. Apple 密码、验证码、Cookie 和 Bot Token 不进入 `.env`；企业微信 Secret 可从
   `IH_WECOM_SECRET` 输入，容器会写入 `/config` 下权限为 `0600` 的密钥文件。

> 当前版本仅支持一个 Apple Account、个人图库 `root` 和单向备份，不支持远端删除。

## 1. 必填规则

参数表中的“必填”有四种状态：

| 标记 | 含义 |
| --- | --- |
| **是** | 使用该配置结构时必须填写。 |
| **首次启动** | 仅在还没有 `/config/config.yaml` 时必填。 |
| **条件必填** | 启用对应功能后必填，例如启用企业微信后必须填写企业应用凭据。 |
| 否 | 可省略，程序会使用默认值。 |

配置优先级从高到低：

1. 非空的 `IH_*` Docker 环境变量；
2. `/config/config.yaml`；
3. 程序默认值。

空环境变量不会覆盖 YAML。已经生成 `config.yaml` 后，建议把长期配置写入 YAML，`.env`
只保留宿主机挂载和确实需要覆盖的少量参数。

## 2. 最小 `.env`

复制示例文件：

```bash
cp .env.example .env
```

默认只需要填写：

```dotenv
IH_APPLE_ID=your-account@example.com
```

如果宿主机不使用默认的 `./data` 目录，再按需追加：

```dotenv
IH_CONFIG_PATH=/volume1/docker/icloudharbor
IH_PHOTOS_PATH=/volume2/photos/iCloud
IH_PUID=99
IH_PGID=100
IH_TIMEZONE=Asia/Shanghai
IH_REGION=china
```

不要把 Apple 密码、双重认证验证码、Cookie 或其他通知 Token 写入 `.env`。若使用
`IH_WECOM_SECRET`，请把 `.env` 权限设为 `0600`；Docker 管理员仍可通过容器配置读取它。

可选企业微信通知：

```dotenv
IH_WECOM_ID=ww0000000000000000
IH_WECOM_SECRET=your-enterprise-application-secret
IH_WECOM_AGENT_ID=1000001
IH_WECOM_TO_USER=@all
```

## 3. 首次启动

默认容器路径：

| 用途 | 容器路径 | 默认宿主机路径 |
| --- | --- | --- |
| 配置、数据库、Session、凭据 | `/config` | `./data/config` |
| 照片根目录 | `/photos` | `./data/photos` |
| 默认账号下载目录 | `/photos/personal` | `./data/photos/personal` |

创建挂载保护标记：

```bash
mkdir -p ./data/photos/personal
touch ./data/photos/personal/.icloudharbor-mounted
```

私有 Docker Hub 仓库需要先登录：

```bash
docker login -u lwxcloud
```

拉取并启动：

```bash
docker compose pull
docker compose up -d
docker compose exec icloudharbor icloudharbor setup
```

`setup` 会以星号遮罩读取 Apple 密码，把本地续期凭据写入 `/config/credentials`，并在验证码
通过、图库检查成功后立即执行首次正式同步。Apple 密码不会进入 `.env`、Compose、命令参数
或镜像层。

## 4. Docker 环境变量完整列表

### 4.1 容器与宿主机

| 参数 | 必填 | 默认值 | 可选值/格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_CONTAINER_NAME` | 否 | `icloudharbor` | Docker 容器名 | `docker exec` 等命令使用的名称。 |
| `IH_CONFIG_PATH` | 否 | `./data/config` | 宿主机绝对或相对路径 | 挂载到 `/config`，必须持久化并按敏感数据保护。 |
| `IH_PHOTOS_PATH` | 否 | `./data/photos` | 宿主机绝对或相对路径 | 挂载到 `/photos`。 |
| `IH_PUID` | 否 | `1000` | 大于 `0` 的数字 UID | 容器内业务进程和新文件的用户 ID。 |
| `IH_PGID` | 否 | `1000` | 大于 `0` 的数字 GID | 容器内业务进程和新文件的组 ID。 |
| `IH_UMASK` | 否 | `0022` | `0000`–`0777` | 新文件和目录的权限掩码。 |
| `IH_TIMEZONE` | 否 | `UTC` | IANA 时区 | 同时控制容器时区、日志时间和调度时间。 |
| `IH_CONFIG_FILE` | 否 | `/config/config.yaml` | 容器内路径 | Compose 已固定，通常不要修改。 |

### 4.2 日志

| 参数 | 必填 | 默认值 | 可选值 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_LOG_LEVEL` | 否 | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` | 日志等级。 |
| `IH_LOG_FORMAT` | 否 | `text` | `text`、`json` | NAS 控制台建议使用 `text`，日志平台建议使用 `json`。 |

### 4.3 Apple Account 与目标目录

| 参数 | 必填 | 默认值 | 可选值/格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_APPLE_ID` | **首次启动** | 无 | Apple Account 邮箱 | 生成首份 `config.yaml` 的唯一必填环境变量。 |
| `IH_ACCOUNT_ID` | 否 | `personal` | 字母/数字开头，后接字母、数字、`_`、`-`，最长 64 | 数据库中的稳定账号 ID，部署后不建议修改。 |
| `IH_ACCOUNT_NAME` | 否 | `我的 iCloud` | 任意非空文本 | 日志和通知中显示的名称。 |
| `IH_REGION` | 否 | `auto` | `auto`、`global`、`china` | 中国大陆账号建议使用 `china`；`auto` 会优先复用 Session 区域。 |
| `IH_DESTINATION` | 否 | `/photos/personal` | 容器内绝对路径 | 下载目标。不要填写 `/volume1/...` 或 `/volume2/...` 宿主机路径。 |
| `IH_MOUNTED_MARKER` | 否 | `.icloudharbor-mounted` | 单个安全文件名 | 目标目录内必须存在的挂载保护标记。 |
| `IH_MINIMUM_FREE_SPACE` | 否 | `10GB` | 字节数或 `10GB`、`2GiB` | 下载后必须保留的最小可用空间。 |

### 4.4 媒体选择

| 参数 | 必填 | 默认值 | 可选值 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_DOWNLOAD_PHOTOS` | 否 | `true` | 布尔值 | 下载普通照片。 |
| `IH_DOWNLOAD_VIDEOS` | 否 | `true` | 布尔值 | 下载普通视频。 |
| `IH_DOWNLOAD_LIVE_PHOTOS` | 否 | `true` | 布尔值 | 保留 Live Photo 的图片和视频资源。 |
| `IH_PHOTO_VERSION` | 否 | `original` | `original`、`adjusted`、`both` | 下载原片、编辑版或两者。 |
| `IH_RAW_MODE` | 否 | `both` | `raw_only`、`jpeg_only`、`both`、`prefer_raw`、`prefer_jpeg` | RAW/JPEG 伴随资源策略。 |

### 4.5 筛选

| 参数 | 必填 | 默认值 | 可选值/格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_CREATED_AFTER` | 否 | 空 | 带时区的 ISO 8601 时间 | 只下载不早于此时间的项目。 |
| `IH_CREATED_BEFORE` | 否 | 空 | 带时区的 ISO 8601 时间 | 只下载不晚于此时间的项目。 |
| `IH_FAVORITES_ONLY` | 否 | `false` | 布尔值 | 只下载收藏项目。 |
| `IH_INCLUDE_HIDDEN` | 否 | `false` | 布尔值 | 是否包含隐藏项目。 |

示例：

```dotenv
IH_CREATED_AFTER=2026-01-01T00:00:00+08:00
IH_CREATED_BEFORE=2026-12-31T23:59:59+08:00
```

当前版本不支持相册包含/排除环境变量。

### 4.6 文件夹和文件名

| 参数 | 必填 | 默认值 | 可选值 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_FOLDER_STRUCTURE` | 否 | `{created:%Y/%m/%d}` | 相对路径模板 | 按拍摄时间创建目录。不能使用绝对路径或 `..`。 |
| `IH_FILENAME_TEMPLATE` | 否 | `{original_name}` | 文件名模板 | 不能包含 `/` 或 `\`。 |
| `IH_CONFLICT_POLICY` | 否 | `suffix_asset_id` | `suffix_asset_id`、`always_asset_id`、`timestamp`、`error` | 同名文件处理方式。 |
| `IH_KEEP_UNICODE` | 否 | `true` | 布尔值 | 是否保留中文等 Unicode 字符。 |

支持的模板字段：

| 字段 | 含义 |
| --- | --- |
| `{created:%Y/%m/%d}` | 按拍摄时间格式化。格式遵循 Python `strftime`。 |
| `{original_name}` | iCloud 返回的原始文件名。 |
| `{asset_id}` | 稳定的远端 Asset ID。 |
| `{resource_type}` | 资源类型。 |
| `{version}` | `original` 或 `adjusted` 等版本名称。 |

### 4.7 调度

| 参数 | 必填 | 默认值 | 可选值/格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_SYNC_STRATEGY` | 否 | `cursor` | `cursor`、`full` | 增量游标或每次全量扫描。 |
| `IH_FULL_SCAN_INTERVAL` | 否 | `30d` | `30d`、`12h` 等时长 | 增量模式下强制全量校准的间隔。 |
| `IH_SCHEDULE` | 否 | `0 3 * * *` | 五段 Cron | 与 `IH_SYNC_INTERVAL` 只能填写一个。 |
| `IH_SYNC_INTERVAL` | 否 | 空 | `6h`、`12h`、`1d` | 固定间隔，与 `IH_SCHEDULE` 只能填写一个。 |
| `IH_RUN_ON_START` | 否 | `false` | 布尔值 | 容器启动后是否立即同步一次。 |

布尔值接受 `true/false`、`yes/no`、`on/off` 或 `1/0`。

### 4.8 下载与校验

| 参数 | 必填 | 默认值 | 可选值/范围 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_DOWNLOAD_CONCURRENCY` | 否 | `2` | `1`–`8` | 并发下载数。Apple 限流或 NAS 较弱时保持 `2`。 |
| `IH_CHUNK_SIZE` | 否 | `1MB` | `64KiB`–`64MiB` | 流式下载块大小。 |
| `IH_DOWNLOAD_TIMEOUT` | 否 | `300` | `1`–`3600` 秒 | 单次 HTTP 下载超时。 |
| `IH_MAX_RETRIES` | 否 | `5` | `0`–`20` | 每个资源的额外重试次数。 |
| `IH_VERIFY_HASH` | 否 | `true` | 布尔值 | 使用数据库 SHA-256 检查已有文件。 |
| `IH_KEEP_PARTIAL` | 否 | `true` | 布尔值 | 保留 `.part` 文件以便断点续传。 |

### 4.9 通知事件开关

通知通道是可选的。`notifications.channels` 为空时，即使下列开关为 `true` 也不会发送任何
消息。

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `IH_NOTIFY_STARTUP` | 否 | `false` | 容器启动时通知。 |
| `IH_NOTIFY_SUCCESS` | 否 | `true` | 有变化且同步成功时通知。 |
| `IH_NOTIFY_NO_CHANGES` | 否 | `false` | 没有变化的成功同步也通知。 |
| `IH_NOTIFY_FAILURE` | 否 | `true` | 失败、部分失败、存储不足等事件通知。 |
| `IH_NOTIFY_AUTH_REQUIRED` | 否 | `true` | Apple 要求重新认证时通知。 |

企业微信可直接使用下一节的 `IH_WECOM_*` 参数。Bark、Server酱、Telegram 和 Webhook
仍通过 `config.yaml` 配置，敏感值放在独立密钥文件中。

### 4.10 企业微信 Docker 参数

企业微信通知是可选的。启用时前四项必须同时填写；含 Secret 的 `.env` 应设置为 `0600`。

| 参数 | 必填 | 默认值 | 对应 icloudpd | 说明 |
| --- | --- | --- | --- | --- |
| `IH_WECOM_ID` | **条件必填** | 无 | `wecom_id` | 企业 ID（CORPID）。 |
| `IH_WECOM_SECRET` | **条件必填** | 无 | `wecom_secret` | 企业应用 Secret；启动时写入权限 `0600` 的内部密钥文件。 |
| `IH_WECOM_AGENT_ID` | **条件必填** | 无 | `agentid` | 企业应用 Agent ID，必须是正整数。 |
| `IH_WECOM_TO_USER` | **条件必填** | 无 | `touser` | 接收成员 ID；多个成员用 `|` 分隔，`@all` 表示全部成员。 |
| `IH_WECOM_PROXY` | 否 | 官方 API | `wecom_proxy` | 企业微信代理 API 根地址。 |
| `IH_WECOM_CONTENT_SOURCE_URL` | 否 | 无 | `content_source_url` | 配置后发送带“查看详情”的文本卡片。 |
| `IH_WECOM_NAME` | 否 | 无 | `name` | 消息正文顶部显示的名称。 |

```dotenv
IH_WECOM_ID=ww0000000000000000
IH_WECOM_SECRET=your-enterprise-application-secret
IH_WECOM_AGENT_ID=1000001
IH_WECOM_TO_USER=@all
IH_WECOM_PROXY=https://qyapi.weixin.qq.com
IH_WECOM_CONTENT_SOURCE_URL=https://example.com
IH_WECOM_NAME=iCloudHarbor
```

## 5. `config.yaml` 完整示例

首次启动后生成：

```text
<IH_CONFIG_PATH>/config.yaml
```

以下示例展示全部非通知通道字段。通常只修改需要的项目：

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
    apple_id: your-account@example.com
    region: china
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

## 6. YAML 参数完整列表

### 6.1 顶层与运行时

| YAML 参数 | 必填 | 默认值 | 可选值/格式 | 说明 |
| --- | --- | --- | --- | --- |
| `version` | 否 | `1` | 只能是 `1` | 配置格式版本。 |
| `accounts` | **是** | 无 | 列表 | 当前必须且只能有一个 `enabled: true` 的账号。 |
| `notifications` | 否 | 默认事件开关、空通道 | 对象 | 通知设置；不配置通道就不发送消息。 |
| `security` | 否 | 安全默认值 | 对象 | 安全和危险能力开关。 |
| `runtime.timezone` | 否 | `UTC` | IANA 时区 | 日志和调度时区。 |
| `runtime.log_level` | 否 | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` | 日志等级。 |
| `runtime.log_format` | 否 | `text` | `text`、`json` | 日志格式。 |
| `runtime.database` | 否 | `/config/database/icloudharbor.db` | 容器内路径 | SQLite 数据库。 |
| `runtime.temp_path` | 否 | `/config/tmp` | 容器内路径 | 临时文件目录。 |

### 6.2 账号、目标与媒体

| YAML 参数 | 必填 | 默认值 | 可选值/格式 | 说明 |
| --- | --- | --- | --- | --- |
| `accounts[].id` | **是** | 无 | 安全 ID，最长 64 | 账号稳定标识。 |
| `accounts[].name` | **是** | 无 | 文本 | 日志和通知显示名称。 |
| `accounts[].apple_id` | **是** | 无 | 邮箱 | Apple Account。 |
| `accounts[].region` | 否 | `auto` | `auto`、`global`、`china` | iCloud 服务区域。 |
| `accounts[].enabled` | 否 | `true` | 布尔值 | 当前必须恰好启用一个账号。 |
| `accounts[].libraries` | 否 | `[root]` | 只能是 `[root]` | 当前只支持个人图库。 |
| `accounts[].destination.path` | **是** | 无 | 容器内绝对路径 | 下载目标。 |
| `accounts[].destination.mounted_marker` | 否 | `.icloudharbor-mounted` | 单个文件名 | 挂载保护标记。 |
| `accounts[].destination.minimum_free_space` | 否 | `10GB` | 容量 | 最小剩余空间。 |
| `accounts[].media.photos` | 否 | `true` | 布尔值 | 下载照片。 |
| `accounts[].media.videos` | 否 | `true` | 布尔值 | 下载视频。 |
| `accounts[].media.live_photos` | 否 | `true` | 布尔值 | 下载 Live Photo 资源。 |
| `accounts[].media.photo_version` | 否 | `original` | `original`、`adjusted`、`both` | 照片版本。 |
| `accounts[].media.raw.mode` | 否 | `both` | `raw_only`、`jpeg_only`、`both`、`prefer_raw`、`prefer_jpeg` | RAW/JPEG 策略。 |

### 6.3 筛选、命名、调度和下载

| YAML 参数 | 必填 | 默认值 | 可选值/格式 | 说明 |
| --- | --- | --- | --- | --- |
| `accounts[].filters.albums` | 否 | `[]` | 当前必须为空 | 相册包含尚未实现。 |
| `accounts[].filters.exclude_albums` | 否 | `[]` | 当前必须为空 | 相册排除尚未实现。 |
| `accounts[].filters.created_after` | 否 | `null` | ISO 8601 | 开始时间。 |
| `accounts[].filters.created_before` | 否 | `null` | ISO 8601 | 结束时间，不能早于开始时间。 |
| `accounts[].filters.favorites_only` | 否 | `false` | 布尔值 | 只下载收藏。 |
| `accounts[].filters.include_hidden` | 否 | `false` | 布尔值 | 包含隐藏项目。 |
| `accounts[].naming.folder_structure` | 否 | `{created:%Y/%m/%d}` | 相对路径模板 | 目录结构。 |
| `accounts[].naming.filename` | 否 | `{original_name}` | 文件名模板 | 文件名规则。 |
| `accounts[].naming.conflict_policy` | 否 | `suffix_asset_id` | `suffix_asset_id`、`always_asset_id`、`timestamp`、`error` | 同名策略。 |
| `accounts[].naming.keep_unicode` | 否 | `true` | 布尔值 | 保留 Unicode。 |
| `accounts[].sync.mode` | 否 | `backup` | 只能是 `backup` | 禁止镜像删除模式。 |
| `accounts[].sync.strategy` | 否 | `cursor` | `cursor`、`full` | 扫描策略。 |
| `accounts[].sync.full_scan_interval` | 否 | `30d` | 时长 | 强制全量校准间隔。 |
| `accounts[].sync.schedule` | 否 | `null` | 五段 Cron 或调度对象 | Bootstrap 默认生成 `0 3 * * *`。 |
| `accounts[].sync.schedule.interval` | **条件必填** | 无 | 时长 | 使用调度对象时，与 `cron` 二选一。 |
| `accounts[].sync.schedule.cron` | **条件必填** | 无 | 五段 Cron | 使用调度对象时，与 `interval` 二选一。 |
| `accounts[].sync.run_on_start` | 否 | `false` | 布尔值 | 启动即同步。 |
| `accounts[].download.concurrency` | 否 | `2` | `1`–`8` | 下载并发。 |
| `accounts[].download.chunk_size` | 否 | `1MB` | `64KiB`–`64MiB` | 下载块大小。 |
| `accounts[].download.timeout` | 否 | `300` | `1`–`3600` | 超时秒数。 |
| `accounts[].download.max_retries` | 否 | `5` | `0`–`20` | 重试次数。 |
| `accounts[].download.verify_hash` | 否 | `true` | 布尔值 | 校验已有文件 SHA-256。 |
| `accounts[].download.keep_partial` | 否 | `true` | 布尔值 | 保留断点文件。 |

### 6.4 通知事件

| YAML 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `notifications.startup` | 否 | `false` | 启动通知。 |
| `notifications.success` | 否 | `true` | 同步成功通知。 |
| `notifications.no_changes` | 否 | `false` | 无变化通知。 |
| `notifications.failure` | 否 | `true` | 失败和告警通知。 |
| `notifications.auth_required` | 否 | `true` | 需要重新认证时通知。 |
| `notifications.channels` | 否 | `[]` | 通知通道列表；为空表示完全关闭通知。 |

### 6.5 通知通道通用参数

| YAML 参数 | 必填 | 默认值 | 适用通道 | 说明 |
| --- | --- | --- | --- | --- |
| `channels[].type` | **是** | 无 | 全部 | `bark`、`serverchan`、`telegram`、`wecom`、`webhook`。 |
| `channels[].enabled` | 否 | `true` | 全部 | 临时禁用该通道。 |
| `channels[].timeout` | 否 | `10` | 全部 | 请求超时秒数，范围 `1`–`60`。 |
| `channels[].server` | 否 | 通道官方地址 | Bark、企业微信 | 自建 Bark 地址或企业微信代理 API 根地址。 |
| `channels[].url` | **条件必填** | 无 | Webhook | 完整 Webhook URL。 |
| `channels[].device_key_file` | **条件必填** | 无 | Bark | Bark Device Key 文件。 |
| `channels[].send_key_file` | **条件必填** | 无 | Server酱 | SendKey 文件。 |
| `channels[].token_file` | **条件必填** | 无 | Telegram | Bot Token 文件。 |
| `channels[].chat_id` | **条件必填** | 无 | Telegram | 用户或群组 Chat ID。 |
| `channels[].secret_file` | 否 | 无 | Webhook | HMAC-SHA256 签名密钥文件。 |

### 6.6 企业微信参数

Docker 部署推荐使用 `IH_WECOM_*` 参数；启动脚本会自动创建 Secret 文件并构造通道。
下列 YAML 是不使用 Docker 环境变量时的高级配置方式。只有添加 `type: wecom` 后，核心字段
才是条件必填。
参数含义对应 docker-icloudpd 的 `wecom_id`、`wecom_secret`、`agentid`、`touser` 和
`wecom_proxy`。

| YAML 参数 | 必填 | 默认值 | 对应 icloudpd | 说明 |
| --- | --- | --- | --- | --- |
| `channels[].corp_id` | **条件必填** | 无 | `wecom_id` | 企业 ID（CORPID）。 |
| `channels[].corp_secret_file` | **条件必填** | 无 | `wecom_secret` | 企业应用 Secret 文件；不接受明文 Secret 字段。 |
| `channels[].agent_id` | **条件必填** | 无 | `agentid` | 企业应用 Agent ID，必须是正整数。 |
| `channels[].to_user` | **条件必填** | 无 | `touser` | 接收成员 ID；多个成员用 `|` 分隔，`@all` 表示全部成员。 |
| `channels[].server` | 否 | `https://qyapi.weixin.qq.com` | `wecom_proxy` | 代理时填写完整 API 根地址。 |
| `channels[].content_source_url` | 否 | 无 | `content_source_url` | 配置后发送带“查看详情”的文本卡片。 |
| `channels[].name` | 否 | 无 | `name` | 消息正文顶部显示的账号所有人或设备名称。 |

创建 Secret 文件：

```bash
mkdir -p ./data/config/notification-keys
chmod 700 ./data/config/notification-keys
```

将企业应用 Secret 写入：

```text
./data/config/notification-keys/wecom-secret
```

设置权限：

```bash
chmod 600 ./data/config/notification-keys/wecom-secret
```

然后编辑 `config.yaml`：

```yaml
notifications:
  startup: false
  success: true
  no_changes: false
  failure: true
  auth_required: true
  channels:
    - type: wecom
      enabled: true
      corp_id: ww0000000000000000
      corp_secret_file: /config/notification-keys/wecom-secret
      agent_id: 1000002
      to_user: "@all"
      name: 家庭 iCloud
      # server: https://your-wecom-proxy.example.com
      # content_source_url: https://your-status-page.example.com
      timeout: 10
```

企业微信应用必须允许对应成员接收消息。如果企业微信启用了可信 IP 白名单，可在
`server` 填写与 docker-icloudpd `wecom_proxy` 等价的代理根地址。

### 6.7 其他通知通道

Bark：

```yaml
- type: bark
  device_key_file: /config/notification-keys/bark-device-key
  # server: https://api.day.app
```

Server酱：

```yaml
- type: serverchan
  send_key_file: /config/notification-keys/serverchan-send-key
```

Telegram：

```yaml
- type: telegram
  token_file: /config/notification-keys/telegram-token
  chat_id: "-1001234567890"
```

通用 Webhook：

```yaml
- type: webhook
  url: https://example.com/hooks/icloudharbor
  # secret_file: /config/notification-keys/webhook-secret
```

配置 `secret_file` 后，请求会增加
`X-iCloudHarbor-Signature: HMAC-SHA256(body)`。

### 6.8 安全参数

| YAML 参数 | 必填 | 默认值 | 允许值 | 说明 |
| --- | --- | --- | --- | --- |
| `security.redact_apple_id` | 否 | `true` | 布尔值 | 日志中隐藏 Apple ID。 |
| `security.session_encryption` | 否 | `false` | 当前只能是 `false` | Apple Session 文件加密尚未实现。 |
| `security.allow_remote_delete` | 否 | `false` | 只能是 `false` | 远端删除永久禁用。 |

## 7. Synology 路径示例

假设：

```text
/volume1/docker/icloudharbor       配置目录
/volume2/photos/iCloud            照片卷
/volume2/photos/iCloud/personal   当前账号下载目录
```

`.env`：

```dotenv
IH_APPLE_ID=your-account@example.com
IH_CONFIG_PATH=/volume1/docker/icloudharbor
IH_PHOTOS_PATH=/volume2/photos/iCloud
IH_PUID=99
IH_PGID=100
IH_TIMEZONE=Asia/Shanghai
IH_REGION=china
```

容器内仍然是：

```text
/config
/photos
/photos/personal
```

不要把 `IH_DESTINATION` 写成 `/volume2/photos/iCloud/personal`；正确值是
`/photos/personal`。

准备目录：

```bash
mkdir -p /volume1/docker/icloudharbor
mkdir -p /volume2/photos/iCloud/personal
touch /volume2/photos/iCloud/personal/.icloudharbor-mounted
chown -R 99:100 /volume1/docker/icloudharbor /volume2/photos/iCloud/personal
```

## 8. 配置检查与管理命令

检查 Compose：

```bash
docker compose config --quiet
```

查看自动生成的配置：

```bash
docker compose exec icloudharbor icloudharbor config show
```

检查认证：

```bash
docker compose exec icloudharbor icloudharbor session status
```

首次认证或重新认证：

```bash
docker compose exec icloudharbor icloudharbor setup
```

验证码通过后会立即执行首次正式同步，此命令会持续运行到同步结束。

续期：

```bash
docker compose exec icloudharbor icloudharbor session renew
```

手动同步：

```bash
docker compose exec icloudharbor icloudharbor sync run
```

查看计划：

```bash
docker compose exec icloudharbor icloudharbor sync plan
```

健康检查：

```bash
docker compose exec icloudharbor icloudharbor healthcheck
```

## 9. 常见问题

### 提示首次启动需要 `IH_APPLE_ID`

检查 `.env` 是否与 `docker-compose.yml` 位于同一目录，并确认值不是空字符串。已有
`config.yaml` 时也可以直接在 YAML 的 `accounts[].apple_id` 中配置。

### 提示挂载标记不存在

标记必须位于实际下载目标中。默认目标对应：

```bash
touch <IH_PHOTOS_PATH>/personal/.icloudharbor-mounted
```

不要把标记只放在照片卷根目录。

### 出现权限错误

确认 `IH_PUID:IH_PGID` 对以下目录有读写权限：

```text
IH_CONFIG_PATH
IH_PHOTOS_PATH/personal
```

群晖常见用户/组 ID 可以通过 `id 用户名` 查询。

### 修改 `.env` 后没有效果

非空 `IH_*` 会在每次启动时覆盖 YAML。删除某个环境变量后，之前生成在 `config.yaml` 中的值
仍会保留，需要同时修改 YAML。

### 没有收到通知

依次检查：

1. `notifications.channels` 是否至少有一个 `enabled: true` 的通道；
2. 对应事件开关是否为 `true`；
3. 密钥文件是否存在且容器 UID 可以读取；
4. 企业微信应用是否允许目标成员接收消息；
5. 企业微信可信 IP 或代理地址是否正确。

### Apple 要求重新认证

执行：

```bash
docker compose exec icloudharbor icloudharbor session renew
```

如果仍需密码或验证码：

```bash
docker compose exec icloudharbor icloudharbor setup
```

## 10. 数据与安全

- `/config` 包含数据库、Apple Session、本地续期凭据和通知密钥，必须限制访问并备份。
- Apple 密码以 AES-256-GCM 保存，但密钥和密文都位于 `/config/credentials`；宿主机 root
  仍可恢复密码。
- Apple Session 当前未加密。
- 下载只从 iCloud 写入本地，不会删除 iCloud 内容，也不会把本地删除同步到远端。
- 只有一次同步的全部资源成功时才会提交新游标。
- 下载先写同目录 `.part` 文件，校验后原子替换正式文件。

更新或迁移前，至少备份整个 `IH_CONFIG_PATH`。
