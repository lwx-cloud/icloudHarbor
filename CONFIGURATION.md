# iCloudHarbor 配置参数

配置只需记住一句话：

> **`.env` 里只填 Apple ID，其他全部有默认值。想改什么，从下表查到变量名，加进 `.env` 或 `config.yaml` 即可。**

- 首次启动用 `IH_APPLE_ID` 自动生成 `/config/config.yaml`；
- 优先级：非空 `IH_*` 环境变量 > `config.yaml` > 默认值；
- Apple 密码、验证码、Cookie 永远不进 `.env`，由 `icloudharbor setup` 以星号遮罩交互输入；
- 布尔值写法：`true/false`、`yes/no`、`on/off`、`1/0` 均可。

**目录**：[参数总表](#一参数总表) · [三分钟上手](#二三分钟上手) · [常见场景](#三常见场景) · [config.yaml 示例](#四-configyaml-完整示例) · [通知渠道](#五通知渠道配置) · [文件名模板](#六文件名模板) · [管理命令](#七常用管理命令) · [FAQ](#八常见问题) · [安全](#九安全说明) · [icloudpd 迁移](#十从-docker-icloudpd-迁移)

---

## 一、参数总表

按使用顺序排列，越靠上越常用。只有 `IH_APPLE_ID` 必填；启用企业微信时其四个参数必须同时填写。

| 变量名 | 默认值 | 可选值 | 说明 |
| --- | --- | --- | --- |
| `IH_APPLE_ID` | 无（**首次启动必填**） | Apple Account 邮箱 | 生成首份 `config.yaml` 的唯一必填项。 |
| `IH_CONFIG_PATH` | `./data/config` | 宿主机路径 | Compose 变量：配置目录，挂载到 `/config`；必须持久化并按敏感数据保护。 |
| `IH_PHOTOS_PATH` | `./data/photos` | 宿主机路径 | Compose 变量：照片目录，挂载到 `/photos`。 |
| `IH_PUID` | `1000` | 大于 `0` 的 UID | 业务进程和新文件的用户 ID；群晖用 `id 用户名` 查询。 |
| `IH_PGID` | `1000` | 大于 `0` 的 GID | 业务进程和新文件的组 ID。 |
| `IH_TIMEZONE` | `UTC` | IANA 时区，如 `Asia/Shanghai` | 同时控制容器时区、日志时间和调度时间。 |
| `IH_LOG_LEVEL` | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` | `DEBUG` 才输出资源 ID、断点等内部信息。 |
| `IH_LOG_FORMAT` | `text` | `text`、`json` | NAS 控制台用 `text`，日志平台用 `json`。 |
| `IH_ACCOUNT_ID` | `personal` | 字母/数字开头，后接字母数字、`_`、`-`，最长 64 | 数据库中的稳定账号 ID，部署后不要改。 |
| `IH_ACCOUNT_NAME` | `我的 iCloud` | 任意非空文本 | 日志和通知中显示的名称。 |
| `IH_REGION` | `auto` | `auto`、`global`、`china` | 中国大陆账号建议 `china`；`auto` 复用 Session 区域。 |
| `IH_LIBRARIES` | `root` | 逗号分隔的图库 ID/名称 | 下载一个或多个可访问图库；用 `libraries list` 查准确值。 |
| `IH_DESTINATION` | `/photos` | 容器内绝对路径 | 下载目标；不要写 `/volume1/...` 宿主机路径。 |
| `IH_MINIMUM_FREE_SPACE` | `10GB` | 字节数或 `10GB`、`2GiB` | 下载后必须保留的最小可用空间。 |
| `IH_DIRECTORY_PERMISSIONS` | 空（默认 `755`） | `750`、`0750`、`0o750` | 非空时强制设置下载目录权限。 |
| `IH_FILE_PERMISSIONS` | 空（默认 `644`） | `640`、`0640`、`0o640` | 非空时强制设置下载文件和生成 JPEG 的权限。 |
| `IH_SYNOLOGY_PHOTOS_APP_FIX` | `false` | `true`、`false` | 下载后 touch 文件，触发 Synology Photos 索引。 |
| `IH_DOWNLOAD_VIDEOS` | `true` | `true`、`false` | 下载普通视频。 |
| `IH_DOWNLOAD_LIVE_PHOTOS` | `true` | `true`、`false` | 保留 Live Photo 的图片和视频资源。 |
| `IH_PHOTO_SIZE` | 空（等同 `original`） | `original`、`medium`、`thumb`、`adjusted`、`alternative`，可逗号组合 | 要编辑版填 `original,adjusted`；要 RAW 伴随资源加 `alternative`。 |
| `IH_LIVE_PHOTO_SIZE` | `original` | `original`、`medium`、`thumb` | Live Photo 图片和视频伴随资源尺寸。 |
| `IH_RAW_MODE` | `both` | `raw_only`、`jpeg_only`、`both`、`prefer_raw`、`prefer_jpeg` | RAW/JPEG 伴随资源策略。 |
| `IH_CONVERT_HEIC_TO_JPEG` | `false` | `true`、`false` | 保留 HEIC 原片并额外生成 JPEG；永不覆盖已有 JPEG。 |
| `IH_JPEG_PATH` | 空（与 HEIC 同目录） | 容器内路径 | JPEG 单独输出目录；设到 `/photos` 外需额外挂载持久化卷。 |
| `IH_JPEG_QUALITY` | `100` | `0`–`100` | 生成 JPEG 的质量。 |
| `IH_ALBUMS` | 空（全部） | 逗号分隔的相册 ID/名称 | 只扫描指定相册；用 `albums list` 查准确值。 |
| `IH_EXCLUDE_ALBUMS` | 空 | 逗号分隔的相册 ID/名称 | 排除指定相册；不能与包含列表重复。 |
| `IH_CREATED_AFTER` | 空 | 带时区的 ISO 8601 时间 | 只下载不早于此时间的项目。 |
| `IH_CREATED_BEFORE` | 空 | 带时区的 ISO 8601 时间 | 只下载不晚于此时间的项目；不能早于起始时间。 |
| `IH_FAVORITES_ONLY` | `false` | `true`、`false` | 只下载收藏项目。 |
| `IH_INCLUDE_HIDDEN` | `false` | `true`、`false` | 包含隐藏项目。 |
| `IH_RECENT_ONLY` | 空（全部） | 大于 `0` 的整数 | 只处理最近加入的 N 个项目。 |
| `IH_UNTIL_FOUND` | 空（全部） | 大于 `0` 的整数 | 连续遇到 N 个已完整存在的项目后停止计划。 |
| `IH_FOLDER_STRUCTURE` | `{created:%Y/%m/%d}` | 相对路径模板，字段见[第六章](#六文件名模板) | 按拍摄时间创建目录；不能用绝对路径或 `..`。 |
| `IH_FILENAME_TEMPLATE` | `{original_name}` | 文件名模板，不能含 `/`、`\` | 文件名规则。 |
| `IH_CONFLICT_POLICY` | `suffix_asset_id` | `suffix_asset_id`、`always_asset_id`、`timestamp`、`error` | 同名文件处理方式。 |
| `IH_SCHEDULE` | `0 3 * * *` | 五段 Cron 或 `6h`、`12h`、`1d` 等时长 | 同步计划；两种写法自动识别。 |
| `IH_RUN_ON_START` | `false` | `true`、`false` | 容器启动后立即同步一次。 |
| `IH_DOWNLOAD_DELAY` | `0` | `0`–`60` 分钟 | 延迟首次执行，错开多个容器；Cron 时间不受影响。 |
| `IH_SYNC_STRATEGY` | `cursor` | `cursor`、`full` | 增量游标或每次全量扫描。 |
| `IH_FULL_SCAN_INTERVAL` | `30d` | `30d`、`12h` 等时长 | 增量模式下强制全量校准的间隔。 |
| `IH_DOWNLOAD_CONCURRENCY` | `2` | `1`–`8` | 并发下载数；Apple 限流或 NAS 较弱时保持 `2`。 |
| `IH_DOWNLOAD_TIMEOUT` | `300` | `1`–`3600` 秒 | 单次 HTTP 下载超时。 |
| `IH_MAX_RETRIES` | `5` | `0`–`20` | 每个资源的额外重试次数。 |
| `IH_NOTIFICATION_TITLE` | `iCloudHarbor` | 任意非空文本 | 通知标题前缀。 |
| `IH_SILENT_NOTIFICATIONS` | `false` | `true`、`false` | Bark/Telegram/Webhook 低打扰发送；企业微信无等价开关。 |
| `IH_NOTIFY_STARTUP` | `false` | `true`、`false` | 容器启动时通知。 |
| `IH_NOTIFY_SUCCESS` | `true` | `true`、`false` | 每次同步成功都通知（包括无变化），保证任务结束必有结果消息。 |
| `IH_NOTIFY_FAILURE` | `true` | `true`、`false` | 失败、部分失败、存储不足等通知。 |
| `IH_NOTIFY_AUTH_REQUIRED` | `true` | `true`、`false` | 认证临期或需重新认证时通知。 |
| `IH_NOTIFICATION_DAYS` | `7` | `1`–`30` | 认证到期前几天开始提醒，每天最多一次。 |
| `IH_WECOM_ID` | 无（启用企业微信时必填） | 企业 ID（CORPID） | 对应 icloudpd `wecom_id`。 |
| `IH_WECOM_SECRET` | 无（启用企业微信时必填） | 企业应用 Secret | 启动时写入权限 `0600` 的密钥文件，不留在 YAML；对应 `wecom_secret`。 |
| `IH_WECOM_AGENT_ID` | 无（启用企业微信时必填） | 正整数 | 企业应用 Agent ID；对应 `agentid`。 |
| `IH_WECOM_TO_USER` | 无（启用企业微信时必填） | 成员 ID，多人用 `\|` 分隔，`@all` 表示全部 | 对应 `touser`。 |
| `IH_WECOM_PROXY` | 官方 API | URL | 代理 API 根地址，绕过可信 IP 白名单；对应 `wecom_proxy`。 |
| `IH_WECOM_CONTENT_SOURCE_URL` | 空 | URL | 配置后发送带「查看详情」的文本卡片。 |
| `IH_WECOM_NAME` | 空 | 任意文本 | 消息正文顶部显示的名称。 |
| `MEDIA_ID_DOWNLOAD` | 空 | 企业微信素材 ID | 下载成功通知封面；填了就发图文消息，否则发文本。 |
| `MEDIA_ID_STARTUP` | 空 | 企业微信素材 ID | 启动通知封面。 |
| `MEDIA_ID_WARNING` | 空 | 企业微信素材 ID | 同步失败/认证失效通知封面。 |
| `MEDIA_ID_EXPIRATION` | 空 | 企业微信素材 ID | 认证临期通知封面。 |

注意事项：

- 非空 `IH_*` 每次启动都会覆盖 YAML；从 `.env` 删掉变量后，之前写入 `config.yaml` 的值仍保留，需要同时改 YAML。
- 通知渠道（`notifications.channels`）为空时，所有 `IH_NOTIFY_*` 开关不会产生任何消息。
- 为兼容早期版本，容器仍接受小写 `notification_days`，新部署统一用 `IH_NOTIFICATION_DAYS`。
- 相册、`recent_only`、`until_found` 扫描不会推进完整图库游标——以后移除这些限制时会安全地重新全量扫描，不会漏掉旧项目。

**0.3.0 删除的参数**：`IH_PHOTO_VERSION`（并入 `IH_PHOTO_SIZE`）、`IH_SYNC_INTERVAL`（并入 `IH_SCHEDULE`）、`IH_VERIFY_HASH`、`IH_KEEP_PARTIAL`、`IH_CHUNK_SIZE`、`IH_MOUNTED_MARKER`、`IH_DOWNLOAD_PHOTOS`、`IH_KEEP_UNICODE`、`IH_UMASK`、`IH_NOTIFY_NO_CHANGES`（并入 `IH_NOTIFY_SUCCESS`）、`MEDIA_ID_DELETE`。旧 `.env`/`config.yaml` 里的这些设置会在启动时自动迁移或忽略并给出警告，不会导致启动失败。

**0.3.2 变更**：Live Photo 专属资源与泛型 photo_*/video_* 同版本去重，修复重复下载；`IH_JPEG_QUALITY` 默认值从 90 改为 100；磁盘已有文件若大小匹配则自动认领；启动日志精简。

### 仅 `config.yaml` 可用的参数

| 参数 | 默认值 | 可选值 | 说明 |
| --- | --- | --- | --- |
| `notifications.channels` | `[]` | 通知渠道列表，见[第五章](#五通知渠道配置) | 为空 = 完全关闭通知。 |

生成文件中的 `version`、`runtime.database`、`runtime.temp_path`、`accounts[].enabled`、`accounts[].sync.mode` 和 `security.*` 由程序管理，保持默认值即可（`sync.mode` 只能是 `backup`，`session_encryption` 和 `allow_remote_delete` 只能是 `false`）。

配置为严格模式：写错参数名会直接报错，不会静默忽略。

---

## 二、三分钟上手

**1. 准备目录和挂载标记**（安全开关：没有它就拒绝下载，防止照片卷未挂载时写爆容器层）：

```bash
mkdir -p ./data/photos
touch ./data/photos/.icloudharbor-mounted
```

**2. 填写 `.env`**，最少只需一行：

```bash
cp .env.example .env
```

```dotenv
IH_APPLE_ID=your-account@example.com
```

**3. 启动并完成认证**：

```bash
docker compose pull
docker compose up -d
docker compose exec icloudharbor icloudharbor setup
```

`setup` 会读取密码 → 输入双重认证验证码 → 自动执行首次同步。完成。

默认路径对应关系：

| 用途 | 宿主机路径（默认） | 容器内路径（固定） |
| --- | --- | --- |
| 配置、数据库、Session、凭据 | `./data/config` | `/config` |
| 照片根目录 | `./data/photos` | `/photos` |
| 当前账号下载目录 | `./data/photos` | `/photos` |

---

## 三、常见场景

### 场景 1：群晖存到 /volume2，用户权限 99:100

```dotenv
IH_APPLE_ID=your-account@example.com
IH_CONFIG_PATH=/volume1/docker/icloudharbor
IH_PHOTOS_PATH=/volume2/photos/iCloud
IH_PUID=99
IH_PGID=100
IH_TIMEZONE=Asia/Shanghai
IH_REGION=china
```

```bash
mkdir -p /volume1/docker/icloudharbor /volume2/photos/iCloud/personal
touch /volume2/photos/iCloud/personal/.icloudharbor-mounted
chown -R 99:100 /volume1/docker/icloudharbor /volume2/photos/iCloud/personal
```

注意：`IH_DESTINATION` 是**容器内**路径（`/photos`），不要写 `/volume2/...` 宿主机路径。

### 场景 2：改同步频率

```dotenv
# 固定间隔或 Cron，同一个参数
IH_SCHEDULE=6h
# 或
IH_SCHEDULE=0 */6 * * *
```

低于 12 小时的频率可能触发 Apple 限流，不建议更密。

### 场景 3：先试试水，只下载最近 100 个文件

```dotenv
IH_RECENT_ONLY=100
```

确认一切正常后删掉这行，会安全地重新全量扫描，不会漏文件。

### 场景 4：只下载「家庭」和「旅行」相册，排除「屏幕快照」

```dotenv
IH_ALBUMS=家庭,旅行
IH_EXCLUDE_ALBUMS=屏幕快照
```

认证后可用命令查看准确的相册名：`docker compose exec icloudharbor icloudharbor albums list --library root`。相册筛选必须全量扫描；同一照片属于多个所选相册时只下载一次。

### 场景 5：HEIC 转成 JPEG 给老设备看

```dotenv
IH_CONVERT_HEIC_TO_JPEG=true
IH_JPEG_QUALITY=100
```

原片保留，JPEG 与 HEIC 同目录生成；同名已存在时自动使用 `_from_HEIC.JPG` 后缀，绝不覆盖。

### 场景 6：让 Synology Photos 立刻索引新照片

```dotenv
IH_SYNOLOGY_PHOTOS_APP_FIX=true
```

### 场景 7：我要通知

**企业微信**（最简单，全走 `.env`，参数见[第一章](#一参数总表) `IH_WECOM_*`）：

```dotenv
IH_WECOM_ID=ww0000000000000000
IH_WECOM_SECRET=your-enterprise-application-secret
IH_WECOM_AGENT_ID=1000001
IH_WECOM_TO_USER=@all
```

含 Secret 的 `.env` 建议 `chmod 600`。每次同步结束（无论有没有新文件）都会发结果；Cookie 到期前 7 天开始每天提醒一次。

**Bark / Server酱 / Telegram / Webhook**：写在 `config.yaml` 里，每种渠道一段示例见[第五章](#五通知渠道配置)。

### 场景 8：不要按日期分目录，想按「年/月」或扁平存放

```dotenv
IH_FOLDER_STRUCTURE={created:%Y/%m}
```

扁平结构不推荐：iCloud 里存在同名文件，平铺会导致后一个被重命名或跳过。

---

## 四、`config.yaml` 完整示例

首次启动自动生成，通常只改需要的部分：

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
      path: /photos
      minimum_free_space: 10GB
      directory_permissions: null
      file_permissions: null
      synology_photos_app_fix: false

    media:
      videos: true
      live_photos: true
      photo_size: null
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
      mode: backup            # 只能是 backup，禁止镜像删除
      strategy: cursor
      full_scan_interval: 30d
      schedule: "0 3 * * *"   # 也可直接写时长：schedule: 6h
      run_on_start: false
      download_delay: 0

    download:
      concurrency: 2
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
  channels: []               # 为空 = 完全关闭通知

security:
  redact_apple_id: true      # 日志中隐藏 Apple ID
  session_encryption: false  # 尚未实现，只能 false
  allow_remote_delete: false # 远端删除永久禁用，只能 false
```

---

## 五、通知渠道配置

通用流程：① 建密钥目录 → ② 写密钥文件 → ③ 在 `config.yaml` 的 `notifications.channels` 加一段。

```bash
mkdir -p ./data/config/notification-keys
chmod 700 ./data/config/notification-keys
# 把密钥写入对应文件后：
chmod 600 ./data/config/notification-keys/*
```

每个渠道都可加 `enabled: false` 临时禁用、`timeout: 10`（1–60 秒）调整超时。

**企业微信**（推荐直接用 `.env` 的 `IH_WECOM_*` 参数；以下为 YAML 高级写法）：

```yaml
channels:
  - type: wecom
    corp_id: ww0000000000000000
    corp_secret_file: /config/notification-keys/wecom-secret
    agent_id: 1000002
    to_user: "@all"
    name: 家庭 iCloud
    # server: https://your-wecom-proxy.example.com
    # content_source_url: https://your-status-page.example.com
    # media_id_download / media_id_startup / media_id_warning /
    # media_id_expiration: 按需填写素材 ID
```

**Bark**：

```yaml
- type: bark
  device_key_file: /config/notification-keys/bark-device-key
  # server: https://api.day.app   # 自建服务器时改这里
```

**Server酱**：

```yaml
- type: serverchan
  send_key_file: /config/notification-keys/serverchan-send-key
```

**Telegram**：

```yaml
- type: telegram
  token_file: /config/notification-keys/telegram-token
  chat_id: "-1001234567890"
```

**通用 Webhook**：

```yaml
- type: webhook
  url: https://example.com/hooks/icloudharbor
  # secret_file: /config/notification-keys/webhook-secret
```

配置 `secret_file` 后请求会带 `X-iCloudHarbor-Signature: HMAC-SHA256(body)` 签名。

---

## 六、文件名模板

`folder_structure` 和 `filename` 可用的字段：

| 字段 | 含义 |
| --- | --- |
| `{created:%Y/%m/%d}` | 按拍摄时间格式化（Python `strftime` 语法）。 |
| `{added:%Y/%m/%d}` | 按加入 iCloud 的时间格式化。 |
| `{original_name}` | iCloud 返回的原始文件名。 |
| `{stem}` / `{extension}` | 原文件名主体 / 扩展名。 |
| `{asset_id}` / `{asset_id_short}` | 完整远端 Asset ID / 清理后末 8 位。 |
| `{account}` / `{library}` / `{album}` | 账号 ID / 图库 ID / 相册名（未按相册扫描时为空）。 |
| `{media_type}` | `photo` 或 `video`。 |
| `{resource_type}` | 资源类型。 |
| `{version}` | `original` / `adjusted` 等版本名。 |

示例——图库名做一级目录、照片再按年月分目录（效果等同 icloudpd 的 `libraries_with_dates`）：

```dotenv
IH_FOLDER_STRUCTURE={library}/{created:%Y/%m}
```

---

## 七、常用管理命令

```bash
# 查看自动生成的配置
docker compose exec icloudharbor icloudharbor config show

# 查看认证状态 / 续期（Apple 要求时只问验证码）
docker compose exec icloudharbor icloudharbor session status
docker compose exec icloudharbor icloudharbor session renew

# 重新认证（密码或验证码失效时）
docker compose exec icloudharbor icloudharbor setup

# 手动同步一次 / 只看计划不下载
docker compose exec icloudharbor icloudharbor sync run
docker compose exec icloudharbor icloudharbor sync plan

# 查看图库和相册的准确 ID/名称
docker compose exec icloudharbor icloudharbor libraries list
docker compose exec icloudharbor icloudharbor albums list --library root

# 健康检查
docker compose exec icloudharbor icloudharbor healthcheck
```

---

## 八、常见问题

**提示首次启动需要 `IH_APPLE_ID`**
`.env` 必须与 `docker-compose.yml` 同目录，值不能是空字符串。已有 `config.yaml` 时也可直接改 YAML 里的 `apple_id`。

**提示挂载标记不存在**
标记必须在**实际下载目录**里，不是照片卷根目录：`touch <IH_PHOTOS_PATH>/personal/.icloudharbor-mounted`。

**权限错误**
确认 `IH_PUID:IH_PGID` 对 `IH_CONFIG_PATH` 和 `IH_PHOTOS_PATH/personal` 都有读写权限；群晖用 `id 用户名` 查 UID/GID。

**改了 `.env` 没效果**
非空 `IH_*` 每次启动都覆盖 YAML。删掉某个环境变量后，之前写进 `config.yaml` 的值仍保留，需要同时改 YAML。

**容器异常停止后提示数据库锁被占用**
不用手工处理。下一次同步取得独占文件锁后会自动清理异常终止留下的租约；仍存活的同步进程不会被误清。

**没收到通知**
依次检查：① `channels` 有至少一个 `enabled: true` 的渠道；② 对应事件开关为 `true`；③ 密钥文件存在且容器 UID 可读；④ 企业微信应用允许该成员接收消息；⑤ 可信 IP/代理地址正确。

**Apple 要求重新认证**
先 `session renew`；仍需密码或验证码就重新 `setup`。

---

## 九、安全说明

- `/config` 包含数据库、Apple Session、本地续期凭据和通知密钥，**必须限制访问并纳入备份**；升级或迁移前至少备份整个 `IH_CONFIG_PATH`。
- Apple 密码以 AES-256-GCM 保存，但密钥和密文都在 `/config/credentials`，宿主机 root 仍可恢复——它防的是意外明文泄露，不是硬件级保护。
- Apple Session 当前未加密。
- 下载只从 iCloud 写入本地：不删 iCloud 内容，不把本地删除同步到远端。
- 只有全部资源成功才提交新游标；下载先写同目录 `.part`，校验后原子替换正式文件。

---

## 十、从 docker-icloudpd 迁移

### 默认值差异（迁移前必读）

| 功能 | icloudpd | iCloudHarbor | 提示 |
| --- | --- | --- | --- |
| 目录权限 | `directory_permissions=750` | 空（默认 `755`） | 想要 750 请显式设置 `IH_DIRECTORY_PERMISSIONS=750`。 |
| 文件权限 | `file_permissions=640` | 空（默认 `644`） | 想要 640 请显式设置 `IH_FILE_PERMISSIONS=640`。 |
| Unicode 文件名 | `keep_unicode=false` | 固定保留 | 中文文件名始终保留，无开关。 |
| 启动通知 | `startup_notification=true` | `IH_NOTIFY_STARTUP=false` | 默认相反。 |
| 文件夹结构 | `{:%Y/%m/%d}` | `{created:%Y/%m/%d}` | 效果一致，字段名更明确。 |
| 同步频率 | `download_interval=86400` | `IH_SCHEDULE`（Cron 或时长） | 都是一天一次；你可用任意 Cron 或间隔。 |
| 挂载标记 | `.mounted` | `.icloudharbor-mounted` | 文件名不同，需重新创建。 |
| 区域开关 | `icloud_china` + `auth_china` 两个 | `IH_REGION=china` 一个 | 更简洁。 |

### icloudpd 有、本项目用更好方式覆盖的

- `skip_videos`/`skip_live_photos` 反向开关 → `IH_DOWNLOAD_VIDEOS` 等正向开关；
- `photo_album="all albums"` → 默认就是全量，不需要特殊值；
- `align_raw`（3 档）→ `IH_RAW_MODE`（5 档）；
- `file_match_policy=name-id7` → `IH_CONFLICT_POLICY=always_asset_id`；
- `webhook_server/port/path/id/https` 五个参数拼 URL → 一个 `url` 搞定；
- `single_pass` → 需要单次执行时直接 `icloudharbor sync run`，常驻容器模型不变；
- `albums_with_dates`/`libraries_with_dates` → 模板直接实现：`IH_FOLDER_STRUCTURE={album}/{created:%Y/%m/%d}`。

### 不会照搬的 icloudpd 参数

- `auto_delete`、`delete_after_download`、`keep_icloud_recent_days`：删 iCloud 内容，违反只读备份原则；
- `delete_accompanying`、`delete_empty_directories`：自动清理本地文件，不做；
- `nextcloud_*`、`sideways_copy_videos*`：上传/二次搬运，超出本地备份范围；
- `set_exif_datetime`：修改下载后的原始媒体，会破坏哈希幂等判断；
- `skip_check`、`file_match_policy`：固定使用 SQLite + 文件大小 + SHA-256 校验，不允许跳过安全检查。
