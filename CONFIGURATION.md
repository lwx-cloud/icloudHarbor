# iCloudHarbor 配置

普通 Docker 部署只需要编辑 `.env`。高级 YAML 只用于 Cron、多渠道通知或精细事件控制。

配置优先级：

```text
非空 IH_* 环境变量 > /config/config.yaml > 程序默认值
```

配置采用严格校验：参数名写错、值越界或使用已删除参数时会直接停止，不会静默忽略。
Apple 密码和验证码不属于配置参数，只由 `icloudharbor setup` 在终端读取。

## 基础参数

### 部署

这些参数由 Docker Compose 使用：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_APPLE_ID` | 无，必填 | Apple Account 邮箱，同时作为默认账号 ID 和显示名称。 |
| `IH_CONTAINER_NAME` | `icloudharbor` | 容器名称；通常不需要修改。 |
| `IH_CONFIG_PATH` | `./data/config` | 配置、数据库、Session、凭据和通知密钥目录。 |
| `IH_PHOTOS_PATH` | `./data/photos` | 照片保存目录，挂载到容器 `/photos`。 |
| `IH_PUID` | `1000` | 容器进程和新文件使用的宿主机 UID，必须大于 0。 |
| `IH_PGID` | `1000` | 容器进程和新文件使用的宿主机 GID，必须大于 0。 |
| `IH_TIMEZONE` | `UTC` | IANA 时区；中国常用 `Asia/Shanghai`。 |
| `IH_REGION` | `auto` | `auto`、`global` 或 `china`。 |

群晖运行 `id <管理员用户名>` 查询实际 UID/GID。容器会把 `/config` 和应用管理的子目录
交给这组 ID，但不会递归修改已有照片库或 NAS ACL。

### 同步

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_SYNC_INTERVAL` | `24` | 只能填 `6`、`12`、`24`，单位是小时，不要写 `6h`。 |
| `IH_RUN_ON_START` | `true` | 容器启动后是否安排一次同步。 |
| `IH_AUTO_DELETE` | `false` | 是否按 iCloud“最近删除”安全清理精确匹配的本地文件。 |
| `IH_DOWNLOAD_DELAY` | `0` | 启动同步延迟分钟数，范围 0–60。 |
| `IH_SYNC_STRATEGY` | `cursor` | `cursor` 增量扫描或 `full` 全量扫描。 |
| `IH_FULL_SCAN_INTERVAL` | `30d` | 增量模式下定期全量校正间隔。 |

`IH_AUTO_DELETE=true` 只删除数据库精确匹配且哈希未变化的本地文件，不删除 iCloud 内容，
不按同名猜测，也不删除未跟踪文件和空目录。

### 媒体

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_DOWNLOAD_VIDEOS` | `true` | 是否下载普通视频。 |
| `IH_DOWNLOAD_LIVE_PHOTOS` | `true` | 是否下载 Live Photo。 |
| `IH_PHOTO_SIZE` | `original` | `original`、`medium`、`thumb`、`adjusted`、`alternative`，可用逗号组合。 |
| `IH_LIVE_PHOTO_SIZE` | `original` | `original`、`medium` 或 `thumb`。 |
| `IH_RAW_MODE` | `both` | `raw_only`、`jpeg_only`、`both`、`prefer_raw`、`prefer_jpeg`。 |
| `IH_CONVERT_HEIC_TO_JPEG` | `false` | 保留 HEIC 原片并额外生成 JPEG。 |
| `IH_JPEG_PATH` | 与原片相同 | JPEG 的容器内目录，例如 `/photos/jpeg`。 |
| `IH_JPEG_QUALITY` | `100` | JPEG 质量，范围 0–100。 |

显式填写 `IH_PHOTO_SIZE` 后，只有列表中包含 `alternative`，RAW/JPEG 伴随资源才会进入计划。

### 相册和筛选

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_LIBRARIES` | `root` | 图库 ID 或名称，多个用英文逗号分隔。 |
| `IH_ALBUMS` | 全部 | 只扫描指定相册，多个用英文逗号分隔。 |
| `IH_EXCLUDE_ALBUMS` | 空 | 排除相册，不能与 `IH_ALBUMS` 重复。 |
| `IH_CREATED_AFTER` | 空 | 只保留该时间之后的内容，使用 ISO 8601。 |
| `IH_CREATED_BEFORE` | 空 | 只保留该时间之前的内容，使用 ISO 8601。 |
| `IH_FAVORITES_ONLY` | `false` | 只下载收藏。 |
| `IH_INCLUDE_HIDDEN` | `false` | 是否包含隐藏项目。 |
| `IH_RECENT_ONLY` | 空 | 只处理最近加入的 N 个项目。 |
| `IH_UNTIL_FOUND` | 空 | 连续遇到 N 个已存在项目后停止扫描。 |

### 路径、权限和下载

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_MINIMUM_FREE_SPACE` | `10GB` | 下载后必须保留的空间，如 `500MB`、`20GiB`。 |
| `IH_DIRECTORY_PERMISSIONS` | 空，通常 755 | 照片目录权限，例如 `750`。 |
| `IH_FILE_PERMISSIONS` | 空，通常 644 | 下载文件和生成 JPEG 的权限，例如 `640`。 |
| `IH_SYNOLOGY_PHOTOS_APP_FIX` | `false` | 触发 Synology Photos 索引兼容处理。 |
| `IH_FOLDER_STRUCTURE` | `{created:%Y/%m/%d}` | 相对目录模板。 |
| `IH_FILENAME_TEMPLATE` | `{original_name}` | 文件名模板。 |
| `IH_CONFLICT_POLICY` | `suffix_asset_id` | `suffix_asset_id`、`always_asset_id`、`timestamp`、`error`。 |
| `IH_DOWNLOAD_CONCURRENCY` | `1` | 并发下载数，范围 1–8。Apple 限流时保持 1。 |
| `IH_DOWNLOAD_TIMEOUT` | `300` | 单次下载超时秒数。 |
| `IH_MAX_RETRIES` | `5` | 单个资源最大重试次数，范围 0–20。 |

### 日志和账号显示

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_LOG_LEVEL` | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`。 |
| `IH_LOG_FORMAT` | `text` | `text` 或 `json`。 |
| `IH_ACCOUNT_ID` | 与 Apple Account 相同 | 数据库、Session 和凭据使用的稳定 ID；通常不要修改。 |
| `IH_ACCOUNT_NAME` | 与 Apple Account 相同 | 日志和通知中的显示名称。 |

更换 `IH_APPLE_ID` 或 `IH_ACCOUNT_ID` 不会迁移旧数据库、Session 和凭据，应使用新的
`IH_CONFIG_PATH`，最好也使用独立照片目录。

## 通知配置

### 简单模式

普通用户只使用：

```dotenv
IH_NOTIFY=true
IH_NOTIFY_TYPE=wecom
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_NOTIFY` | `false` | 通知总开关。关闭时保留其他通知参数也不会发送。 |
| `IH_NOTIFY_TYPE` | 无 | `bark`、`serverchan`、`telegram`、`wecom`、`webhook`。一次选择一个。 |
| `IH_NOTIFY_TITLE` | `iCloudHarbor` | 通知标题前缀。 |
| `IH_NOTIFY_SILENT` | `false` | Bark、Telegram 和 Webhook 是否静默。 |
| `IH_NOTIFY_DAYS` | `7` | 认证到期前多少天开始提醒，范围 1–30。 |

`IH_NOTIFY=true` 默认发送启动、同步成功、同步失败和认证状态通知。Docker 简单模式不再提供
四组事件开关；需要逐事件控制或多个渠道时，使用本章末尾的高级 YAML，并从 `.env` 删除
`IH_NOTIFY`。

### Bark

```dotenv
IH_NOTIFY=true
IH_NOTIFY_TYPE=bark
IH_BARK_KEY=your-device-key
# IH_BARK_SERVER=https://api.day.app
```

### Server酱

```dotenv
IH_NOTIFY=true
IH_NOTIFY_TYPE=serverchan
IH_SERVERCHAN_KEY=your-send-key
```

### Telegram

```dotenv
IH_NOTIFY=true
IH_NOTIFY_TYPE=telegram
IH_TELEGRAM_TOKEN=your-bot-token
IH_TELEGRAM_CHAT=-1001234567890
```

### 企业微信

```dotenv
IH_NOTIFY=true
IH_NOTIFY_TYPE=wecom
IH_WECOM_CORP_ID=ww0000000000000000
IH_WECOM_CORP_SECRET=your-enterprise-application-secret
IH_WECOM_AGENT_ID=1000001
IH_WECOM_TO_USER=@all

# 可选
# IH_WECOM_PROXY=https://qyapi.weixin.qq.com
# IH_WECOM_CONTENT_SOURCE_URL=https://example.com
# IH_WECOM_NAME=iCloudHarbor
# MEDIA_ID_DOWNLOAD=your-download-media-id
# MEDIA_ID_STARTUP=your-startup-media-id
# MEDIA_ID_WARNING=your-warning-media-id
# MEDIA_ID_EXPIRATION=your-expiration-media-id
```

| 参数 | 企业微信中的含义 | 必填 |
| --- | --- | --- |
| `IH_WECOM_CORP_ID` | 企业 ID（CorpID） | 是 |
| `IH_WECOM_CORP_SECRET` | 自建应用的 Secret（CorpSecret） | 是 |
| `IH_WECOM_AGENT_ID` | 自建应用的 AgentId | 是 |
| `IH_WECOM_TO_USER` | 接收成员账号，多个用 `\|`，全部成员用 `@all` | 是 |
| `IH_WECOM_PROXY` | 企业微信 API 地址或代理地址 | 否 |
| `IH_WECOM_CONTENT_SOURCE_URL` | 消息“查看详情/阅读原文”跳转地址 | 否 |
| `IH_WECOM_NAME` | 消息中显示的来源名称 | 否 |

`IH_WECOM_CONTENT_SOURCE_URL` 存在时，普通消息使用可点击详情卡片；配置对应媒体 ID 后使用图文消息。
同步清理通知的详情中会列出文件名，企业微信图文消息和详情卡片都能看到。

### Webhook

```dotenv
IH_NOTIFY=true
IH_NOTIFY_TYPE=webhook
IH_WEBHOOK_URL=https://example.com/webhook
# IH_WEBHOOK_SECRET=optional-signing-secret
```

Webhook 发送 JSON，包含 `event`、`title`、`message`、`data`、`timestamp` 和
`silent`；本地清理时还包含 `details` 与结构化文件名。设置 Secret 后，会增加
`X-iCloudHarbor-Signature` 请求头，值为请求正文的 SHA-256 HMAC 十六进制摘要。

通知密钥虽然从 `.env` 传入，但容器启动后会写入
`/config/notification-keys/` 对应文件并设为 `0600`，生成的 `config.yaml` 只保存文件路径。
Docker 管理员仍可查看容器环境，因此整个部署目录和 `/config` 都应按敏感数据保护。

### 高级 YAML：多渠道或逐事件控制

高级模式下，从 `.env` 删除所有 `IH_NOTIFY*`、渠道凭据和媒体 ID 参数，然后编辑
`/config/config.yaml`：

```yaml
notifications:
  title: iCloudHarbor
  silent: false
  startup: true
  success: true
  failure: true
  auth_required: true
  notification_days: 7
  channels:
    - type: bark
      device_key_file: /config/notification-keys/bark-key
      server: https://api.day.app
      timeout: 10

    - type: webhook
      url: https://example.com/webhook
      secret_file: /config/notification-keys/webhook-secret
      timeout: 10
```

渠道字段：

| 类型 | 必填 YAML 字段 |
| --- | --- |
| `bark` | `device_key_file`；`server` 可选。 |
| `serverchan` | `send_key_file`。 |
| `telegram` | `token_file`、`chat_id`。 |
| `wecom` | `corp_id`、`corp_secret_file`、`agent_id`、`to_user`。 |
| `webhook` | `url`；`secret_file` 可选。 |

每个渠道可使用 `enabled: false` 临时禁用，`timeout` 范围为 1–60 秒。密钥文件需要由容器
运行 UID 读取，建议目录权限 `0700`、文件权限 `0600`。

## 高级 `config.yaml`

首次启动会自动生成 `/config/config.yaml`。已有文件不会被 bootstrap 覆盖；非空环境变量
仍会在每次启动时覆盖对应字段。

下面是完整结构示例，未使用的可选字段可以删除：

```yaml
version: 1

runtime:
  timezone: Asia/Shanghai
  log_level: INFO
  log_format: text
  database: /config/database/icloudharbor.db
  temp_path: /config/tmp

accounts:
  - id: your-account@example.com
    name: 家庭相册
    apple_id: your-account@example.com
    region: auto
    enabled: true
    libraries: [root]

    destination:
      path: /photos
      minimum_free_space: 10GB
      directory_permissions: null
      file_permissions: null
      synology_photos_app_fix: false

    media:
      videos: true
      live_photos: true
      photo_size: [original]
      live_photo_size: original
      raw:
        mode: both
      convert_heic_to_jpeg: false
      jpeg_path: null
      jpeg_quality: 100

    filters:
      albums: []
      exclude_albums: []
      created_after: null
      created_before: null
      favorites_only: false
      include_hidden: false
      recent_only: null
      until_found: null

    naming:
      folder_structure: "{created:%Y/%m/%d}"
      filename: "{original_name}"
      conflict_policy: suffix_asset_id

    sync:
      mode: backup
      strategy: cursor
      full_scan_interval: 30d
      schedule:
        interval: 24h
      run_on_start: true
      download_delay: 0
      auto_delete: false

    download:
      concurrency: 1
      timeout: 300
      max_retries: 5

notifications:
  title: iCloudHarbor
  silent: false
  startup: false
  success: true
  failure: true
  auth_required: true
  notification_days: 7
  channels: []

security:
  redact_apple_id: true
  session_encryption: false
  allow_remote_delete: false
```

只有 YAML 支持：

- Cron：`schedule: "0 3 * * *"`；
- 多个通知渠道；
- 启动、成功、失败、认证四类通知分别开关；
- 数据库和临时目录位置；
- `security` 安全字段。

`session_encryption` 和 `allow_remote_delete` 必须保持 `false`，当前版本不提供这些能力。

## 文件名模板

目录模板可用：

| 字段 | 含义 |
| --- | --- |
| `{created:%Y}`、`{created:%m}`、`{created:%d}` | 拍摄时间。 |
| `{library}` | 图库名称。 |
| `{album}` | 相册名称。 |
| `{media_type}` | 媒体类型。 |

文件名模板可用：

| 字段 | 含义 |
| --- | --- |
| `{original_name}` | iCloud 原始文件名。 |
| `{stem}` | 不含扩展名的原始文件名。 |
| `{extension}` | 不含点号的扩展名。 |
| `{asset_id}` | iCloud Asset ID。 |
| `{resource_type}` | 资源类型。 |
| `{created:%Y%m%d_%H%M%S}` | 拍摄时间格式。 |

模板必须是目标目录内的相对路径，不能包含 `..`。Windows 非法字符、控制字符和尾随点会被
清理；空名称会回退到 `asset_id`。

## 常见配置

### 群晖保存到 `/volume2`

```dotenv
IH_APPLE_ID=your-account@example.com
IH_CONFIG_PATH=/volume1/docker/icloudharbor/config
IH_PHOTOS_PATH=/volume2/photos/iCloud
IH_PUID=1026
IH_PGID=100
IH_TIMEZONE=Asia/Shanghai
IH_REGION=auto
IH_SYNC_INTERVAL=12
```

`1026:100` 只是示例，必须用 `id <管理员用户名>` 的实际结果。

### 首次只下载最近 100 项

```dotenv
IH_RECENT_ONLY=100
```

### 只下载指定相册

```dotenv
IH_ALBUMS=家庭,旅行
IH_EXCLUDE_ALBUMS=屏幕快照
```

### HEIC 额外生成 JPEG

```dotenv
IH_CONVERT_HEIC_TO_JPEG=true
IH_JPEG_QUALITY=95
```

## 常见问题

### 修改 `.env` 后没有生效

重建容器：

```bash
docker compose up -d --force-recreate
```

删除某个环境变量后，旧值可能仍保存在 `config.yaml`，需要同时修改 YAML。

### 管理员打不开目录

确认 `IH_PUID:IH_PGID` 与宿主机管理员一致。修正后重建容器，`/config` 和应用子目录会
自动修正属主。旧照片目录只应在确认属于 iCloudHarbor 后手工修复，不要递归修改共享照片库。

### 没收到通知

依次检查：

1. `IH_NOTIFY=true`；
2. `IH_NOTIFY_TYPE` 与填写的渠道参数一致；
3. 必填参数没有留空；
4. 容器能访问通知服务；
5. 企业微信应用成员、可信 IP 或代理设置正确。

启动摘要会显示当前启用的通知类型。需要查看发送失败原因时检查容器日志。

### 配置路径和照片路径

`IH_CONFIG_PATH` 是宿主机路径，挂载到容器 `/config`；`IH_PHOTOS_PATH` 是宿主机路径，
挂载到容器 `/photos`。YAML 的 `destination.path` 默认必须保持 `/photos`。

## 安全约束

- `/config` 包含 Cookie、Session、SQLite、凭据密钥和通知密钥，应完整备份并限制访问；
- Apple 密码不会进入 `.env`、Compose、日志或镜像层；
- 没有 `.icloudharbor-mounted` 时拒绝下载；
- 只有全部资源成功才提交同步游标；
- 正式文件只由已校验的同目录 `.part` 文件原子替换；
- 永远不删除 iCloud 内容；
- 本地自动清理默认关闭，并校验路径、归属、大小和 SHA-256。

## 从 docker-icloudpd 迁移

| 项目 | docker-icloudpd | iCloudHarbor |
| --- | --- | --- |
| 通知入口 | `notification_type` | `IH_NOTIFY=true` + `IH_NOTIFY_TYPE` |
| 目录权限 | 默认 750 | 默认通常 755，可设 `IH_DIRECTORY_PERMISSIONS=750` |
| 文件权限 | 默认 640 | 默认通常 644，可设 `IH_FILE_PERMISSIONS=640` |
| 同步间隔 | 秒数 | `6`、`12`、`24` 小时 |
| 挂载标记 | `.mounted` | `.icloudharbor-mounted` |
| 中国区 | 两个开关 | `IH_REGION=china` |
| 认证 | keyring/Cookie 初始化脚本 | `icloudharbor setup` |

iCloudHarbor 不提供远端删除、删除空目录或“本地缺失即删除”等镜像行为。
