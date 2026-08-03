# iCloudHarbor 配置参数

配置只需记住一句话：

> **复制 `.env.example`，填写 Apple ID 和群晖路径；同步间隔直接填小时数字，开关只填 `true` 或 `false`。**

- 首次启动用 `IH_APPLE_ID` 自动生成 `/config/config.yaml`；
- 优先级：非空 `IH_*` 环境变量 > `config.yaml` > 默认值；
- Apple 密码、验证码、Cookie 永远不进 `.env`，由 `icloudharbor setup` 以星号遮罩交互输入；
- 新配置中的布尔值统一写 `true` 或 `false`；旧部署的 `yes/no`、`on/off`、`1/0` 仍兼容。

**目录**：[新手参数](#一新手参数) · [三分钟上手](#二三分钟上手) · [常见场景](#三常见场景) · [config.yaml 示例](#四configyaml-完整示例) · [通知渠道](#五通知渠道配置) · [文件名模板](#六文件名模板) · [管理命令](#七常用管理命令) · [FAQ](#八常见问题) · [安全](#九安全说明) · [icloudpd 迁移](#十从-docker-icloudpd-迁移)

---

## 一、新手参数

本章参数表统一为五列。`true` 表示开启，`false` 表示关闭；没有明确需求就保留默认值。

| 参数名 | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_APPLE_ID` | 是 | 无 | Apple Account 邮箱，不超过 220 个 UTF-8 字节 | 指定要备份的 iCloud 账号，并直接作为默认账号 ID 和终端、通知中的显示名称；密码和验证码不写在 `.env`。 |
| `IH_CONTAINER_NAME` | 否 | `icloudharbor` | 未占用的容器名 | 设置 Compose 创建的容器名，供 `docker logs`、`docker exec` 和日志中的认证命令使用；不影响账号、配置或照片目录。只有同一主机运行多个独立实例或名称冲突时才需修改。 |
| `IH_CONFIG_PATH` | 否 | `./data/config` | 宿主机路径 | 保存配置、数据库、Session、凭据和通知密钥。 |
| `IH_PHOTOS_PATH` | 否 | `./data/photos` | 宿主机路径 | 设置照片保存目录，并挂载到容器 `/photos`。 |
| `IH_PUID` | 否 | `1000` | 大于 `0` 的 UID | 设置容器进程和新文件使用的用户 ID。 |
| `IH_PGID` | 否 | `1000` | 大于 `0` 的 GID | 设置容器进程和新文件使用的组 ID。 |
| `IH_TIMEZONE` | 否 | `UTC`（`.env.example` 为 `Asia/Shanghai`） | IANA 时区 | 设置同步计划和每日提醒使用的时区。 |
| `IH_REGION` | 否 | `auto` | `auto`、`global`、`china` | 选择 Apple 全球区或中国大陆区服务；通常保持 `auto`。 |
| `IH_SYNC_INTERVAL` | 否 | `24` | 只能是 `6`、`12`、`24` | 设置两次自动检查 iCloud 的间隔小时数；`12` 表示每 12 小时一次，不是每天 12 点。推荐 `12` 或 `24`；`6` 请求更频繁，可能增加 Apple 限流或风控概率。 |
| `IH_RUN_ON_START` | 否 | `true` | `true`、`false` | 是否在容器启动后安排一次同步。 |
| `IH_AUTO_DELETE` | 否 | `false` | `true`、`false` | 是否读取 iCloud“最近删除”并清理精确匹配、内容未变化的本地文件；只删除本地，不删除 iCloud。 |
| `IH_DOWNLOAD_VIDEOS` | 否 | `true` | `true`、`false` | 是否下载普通视频，不控制 Live Photo。 |
| `IH_DOWNLOAD_LIVE_PHOTOS` | 否 | `true` | `true`、`false` | 是否下载 Live Photo；`false` 会跳过整个 Live Photo 项目。 |
| `IH_CONVERT_HEIC_TO_JPEG` | 否 | `false` | `true`、`false` | 是否保留 HEIC 原片并额外生成 JPEG。 |
| `IH_SYNOLOGY_PHOTOS_APP_FIX` | 否 | `false` | `true`、`false` | 是否额外触发文件时间变更，帮助 Synology Photos 发现新文件；最终修改时间仍恢复为 iCloud 拍摄时间。 |
| `IH_ALBUMS` | 否 | 空（全部） | 相册 ID/名称，多个用英文逗号分隔 | 只扫描指定相册。 |
| `IH_EXCLUDE_ALBUMS` | 否 | 空 | 相册 ID/名称，多个用英文逗号分隔 | 跳过指定相册，不能与 `IH_ALBUMS` 重复。 |
| `IH_RECENT_ONLY` | 否 | 空（全部） | 大于 `0` 的整数 | 只处理最近加入的 N 个项目，适合首次试运行。 |

修改已有实例的 `IH_PHOTOS_PATH` 不会自动搬文件；先停容器并搬完整目录。默认情况下，更换
`IH_APPLE_ID` 也会直接更换账号 ID，旧数据库记录、Session 和凭据不会自动迁移；请使用新的
`IH_CONFIG_PATH`，最好也使用独立的 `IH_PHOTOS_PATH`。

`0.3.5` 起所有下载资源和转换生成的 JPEG 都会把文件修改时间恢复为 iCloud 拍摄时间。
定期全量扫描会自动校正升级前已下载的文件，无需重新下载或额外命令。

### 企业微信（可选）

不用企业微信时全部留空。启用后前四项必须同时填写。

| 参数名 | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_WECOM_ID` | 否 | 无 | 企业 ID（CORPID） | 指定企业微信企业。 |
| `IH_WECOM_SECRET` | 否 | 无 | 自建应用 Secret | 用于获取企业微信访问令牌；`.env` 建议设为 `0600`。 |
| `IH_WECOM_AGENT_ID` | 否 | 无 | 正整数 Agent ID | 指定发送消息的自建应用。 |
| `IH_WECOM_TO_USER` | 否 | 无 | 成员 ID；多人用 `\|`；全部用 `@all` | 指定通知接收人。 |
| `IH_WECOM_PROXY` | 否 | `https://qyapi.weixin.qq.com` | 完整 URL | 设置企业微信 API 代理地址。 |
| `IH_WECOM_CONTENT_SOURCE_URL` | 否 | 空 | 完整 URL | 设置通知中的“查看详情”链接。 |
| `IH_WECOM_NAME` | 否 | 空 | 任意文本 | 设置消息中显示的来源名称。 |
| `MEDIA_ID_DOWNLOAD` | 否 | 空 | 企业微信素材 ID | 设置同步成功通知封面。 |
| `MEDIA_ID_STARTUP` | 否 | 空 | 企业微信素材 ID | 设置容器启动和认证恢复通知封面。 |
| `MEDIA_ID_WARNING` | 否 | 空 | 企业微信素材 ID | 设置失败和认证失效通知封面。 |
| `MEDIA_ID_EXPIRATION` | 否 | 空 | 企业微信素材 ID | 设置认证临期通知封面。 |

任意企业微信参数非空都视为启用；此时 `IH_WECOM_ID`、`IH_WECOM_SECRET`、
`IH_WECOM_AGENT_ID`、`IH_WECOM_TO_USER` 四项缺一不可。

### 高级配置

下面的参数用于特殊需求。环境变量和括号中的 YAML 路径控制同一件事；两边都写时，非空环境
变量优先。新用户没有对应需求时不要添加。

#### 日志与账号标识

| 参数名（YAML 路径） | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_LOG_LEVEL`（`runtime.log_level`） | 否 | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL` | 设置日志详细程度。 |
| `IH_LOG_FORMAT`（`runtime.log_format`） | 否 | `text` | `text`、`json` | 设置普通文本或结构化 JSON 日志。 |
| `IH_ACCOUNT_ID`（`accounts[].id`） | 否 | 与 `IH_APPLE_ID` 相同 | 不超过 220 个 UTF-8 字节的安全文件名 | 显式覆盖数据库、Session 和凭据使用的账号 ID；通常无需设置，修改后需重新认证。 |
| `IH_ACCOUNT_NAME`（`accounts[].name`） | 否 | 与 `IH_APPLE_ID` 相同 | 任意文本 | 显式覆盖终端和通知中显示的账号名称；通常无需设置。 |
| `IH_LIBRARIES`（`accounts[].libraries`） | 否 | `root` | 图库 ID/名称，多个用英文逗号分隔 | 设置要扫描的个人或共享图库。 |

#### 存储空间与权限

| 参数名（YAML 路径） | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_MINIMUM_FREE_SPACE`（`accounts[].destination.minimum_free_space`） | 否 | `10GB` | 字节数或 `500MB`、`20GiB`、`1TB` | 设置下载后必须保留的最低磁盘空间；不足时停止同步。 |
| `IH_DIRECTORY_PERMISSIONS`（`accounts[].destination.directory_permissions`） | 否 | 空（通常 `755`） | 环境变量填 `750`；YAML 填 `"0750"` | 设置照片目录权限。 |
| `IH_FILE_PERMISSIONS`（`accounts[].destination.file_permissions`） | 否 | 空（通常 `644`） | 环境变量填 `640`；YAML 填 `"0640"` | 设置下载文件和生成 JPEG 的权限。 |

#### 媒体版本与转换

| 参数名（YAML 路径） | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_PHOTO_SIZE`（`accounts[].media.photo_size`） | 否 | 空（按原始版本处理） | `original`、`medium`、`thumb`、`adjusted`、`alternative`，多个用英文逗号分隔 | 指定普通照片和普通视频要下载的 iCloud 资源版本；选择多个会分别保存多个文件。 |
| `IH_LIVE_PHOTO_SIZE`（`accounts[].media.live_photo_size`） | 否 | `original` | `original`、`medium`、`thumb` | 指定 Live Photo 静态图片和配对短视频共同使用的尺寸版本。 |
| `IH_RAW_MODE`（`accounts[].media.raw.mode`） | 否 | `both` | `raw_only`、`jpeg_only`、`both`、`prefer_raw`、`prefer_jpeg` | 决定 RAW 项目中 RAW、JPEG 伴随资源和普通原始资源如何保留。 |
| `IH_JPEG_PATH`（`accounts[].media.jpeg_path`） | 否 | 空（与 HEIC 同目录） | 容器内路径，如 `/photos/jpeg` | 设置 HEIC 转换后 JPEG 的保存目录。 |
| `IH_JPEG_QUALITY`（`accounts[].media.jpeg_quality`） | 否 | `100` | `0`–`100` 的整数 | 设置 HEIC 转 JPEG 的质量。 |

`IH_PHOTO_SIZE` 的每个值含义如下。Apple 没有提供某个版本时，程序不会自行缩放生成该版本：

| 值 | 下载内容 | 适用场景 |
| --- | --- | --- |
| `original` | Apple 提供的原始尺寸、未编辑资源。 | 正式备份的默认选择，通常画质最高、文件最大。 |
| `medium` | Apple 提供的中等尺寸预览资源，具体分辨率由 Apple 决定。 | 只需浏览且想节省空间；不能替代原片备份。 |
| `thumb` | Apple 提供的缩略图资源。 | 测试目录或快速预览；不建议作为唯一备份。 |
| `adjusted` | 在 Apple Photos 中编辑后由 iCloud 提供的版本。 | 与 `original` 组合为 `original,adjusted`，同时保留原片和编辑效果。 |
| `alternative` | 允许选择 RAW/JPEG 伴随资源，本身不是分辨率。 | 显式设置 `IH_PHOTO_SIZE` 后仍需 RAW/JPEG 伴随文件时加入，最终保留哪种格式由 `IH_RAW_MODE` 决定。 |

不设置 `IH_PHOTO_SIZE` 时，会按 `original` 处理，并继续根据 `IH_RAW_MODE` 选择 RAW/JPEG
伴随资源。只要显式填写了尺寸列表，就必须把 `alternative` 加入列表，RAW/JPEG 伴随资源才会
进入下载计划。

`IH_LIVE_PHOTO_SIZE` 的三个值会同时作用于静态图片和配对短视频：

| 值 | 下载内容 | 适用场景 |
| --- | --- | --- |
| `original` | 两部分都选择 Apple 提供的原始尺寸版本。 | 默认且最适合作为完整备份。 |
| `medium` | 两部分都选择中等尺寸版本。 | 希望降低画质和空间占用时使用。 |
| `thumb` | 两部分都选择缩略尺寸版本。 | 只适合预览或测试，不建议作为唯一备份。 |

`IH_RAW_MODE` 的选择结果：

| 值 | RAW/JPEG 资源处理 | 适用场景 |
| --- | --- | --- |
| `raw_only` | 选择 RAW 伴随资源，跳过 JPEG 伴随资源和普通 `photo_original`。没有 RAW 的普通照片可能因此没有可下载资源。 | 只做 RAW 后期，并明确接受跳过非 RAW 原片。 |
| `jpeg_only` | 选择 JPEG 伴随资源，不选择 RAW；普通原始资源仍按 `IH_PHOTO_SIZE` 处理。 | 只需常规图片格式，不保留 RAW。 |
| `both` | RAW 和 JPEG 伴随资源都选择，普通原始资源也照常处理。 | 默认且最完整，但空间占用最大。 |
| `prefer_raw` | 选择 RAW 伴随资源，不选择 JPEG 伴随资源；普通原始资源仍照常处理。 | 保留 RAW，同时减少一份 JPEG 伴随文件。 |
| `prefer_jpeg` | 选择 JPEG 伴随资源，不选择 RAW；普通原始资源仍照常处理。 | 优先兼容查看并节省 RAW 空间。 |

#### 日期与内容筛选

| 参数名（YAML 路径） | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_CREATED_AFTER`（`accounts[].filters.created_after`） | 否 | 空 | 带时区的 ISO 8601 时间 | 只下载拍摄时间不早于该时间的项目。 |
| `IH_CREATED_BEFORE`（`accounts[].filters.created_before`） | 否 | 空 | 带时区的 ISO 8601 时间 | 只下载拍摄时间不晚于该时间的项目。 |
| `IH_FAVORITES_ONLY`（`accounts[].filters.favorites_only`） | 否 | `false` | `true`、`false` | 是否只下载个人收藏项目。 |
| `IH_INCLUDE_HIDDEN`（`accounts[].filters.include_hidden`） | 否 | `false` | `true`、`false` | 是否包含 iCloud 隐藏项目。 |
| `IH_UNTIL_FOUND`（`accounts[].filters.until_found`） | 否 | 空 | 大于 `0` 的整数 | 连续遇到 N 个本地已有项目后停止扫描。 |

#### 目录、文件名与重名处理

| 参数名（YAML 路径） | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_FOLDER_STRUCTURE`（`accounts[].naming.folder_structure`） | 否 | `{created:%Y/%m/%d}` | 目标照片目录内的相对路径模板 | 决定每个资源放入哪些子目录。默认会把拍摄于 2026-07-31 的文件放入 `2026/07/31/`；可改为 `{library}/{created:%Y/%m}` 等组合。模板字段见[第六章](#六文件名模板)。 |
| `IH_FILENAME_TEMPLATE`（`accounts[].naming.filename`） | 否 | `{original_name}` | 不含 `/`、`\` 的文件名模板 | 决定每个下载资源的文件名。可使用 `{stem}_{created:%Y%m%d}` 等模板；程序始终保留该资源自己的扩展名，避免把 Live Photo 视频或 RAW 文件误命名为照片扩展名。 |
| `IH_CONFLICT_POLICY`（`accounts[].naming.conflict_policy`） | 否 | `suffix_asset_id` | `suffix_asset_id`、`always_asset_id`、`timestamp`、`error` | 决定两个不同 iCloud 资源渲染到同一本地路径时如何处理。 |

修改目录或文件名模板不会搬动已经下载的文件；数据库仍沿用旧文件路径，新资源才使用新模板。
命名字段中的非法字符会替换为 `_`。四种重名策略如下：

| 值 | 处理方式 |
| --- | --- |
| `suffix_asset_id` | 仅发生冲突时，在扩展名前追加清理后的 Asset ID 末 8 位，例如 `IMG_1234ABCD.JPG`。 |
| `always_asset_id` | 每个文件都追加 Asset ID 末 8 位，即使当前没有重名；路径从一开始就保持唯一。 |
| `timestamp` | 仅发生冲突时追加拍摄时间，例如 `IMG_20260731_153000.JPG`。同一秒仍冲突时再追加数字序号。 |
| `error` | 遇到冲突立即报错并让本次同步失败，适合希望人工检查所有重名的场景。 |

#### 调度与扫描方式

| 参数名（YAML 路径） | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_SYNC_STRATEGY`（`accounts[].sync.strategy`） | 否 | `cursor` | `cursor`、`full` | 设置增量扫描或每次完整扫描。 |
| `IH_FULL_SCAN_INTERVAL`（`accounts[].sync.full_scan_interval`） | 否 | `30d` | 时长，如 `12h`、`7d`、`4w` | 设置增量模式下定期完整扫描的间隔。 |
| `IH_DOWNLOAD_DELAY`（`accounts[].sync.download_delay`） | 否 | `0` | `0`–`60` 的整数分钟 | 设置容器启动后首次同步的延迟。 |

`IH_AUTO_DELETE=true` 时，每次正式同步和 `plan` 都会读取个人图库的“最近删除”。程序只按
账号、图库和 iCloud Asset ID 查找自己记录过的本地文件，不会仅凭文件名删除；删除前还会确认
路径仍在受管目录内、不是符号链接，并重新校验大小和 SHA-256。文件被本地修改、路径存在归属
冲突或无法安全确认时，本轮会失败关闭并保留文件。共享图库的“最近删除”当前不会参与清理。

Apple 的“最近删除”只保留有限时间，因此已经从该相册永久移除的旧项目无法再被识别。建议首次
开启前先保持持久配置为 `false`，备份 SQLite 和照片目录，再临时预览候选项：

```bash
docker compose exec -e IH_AUTO_DELETE=true icloudharbor icloudharbor plan
```

计划模式只展示、不删除文件。确认后再把 `.env` 改为 `IH_AUTO_DELETE=true` 并重建容器。

#### 下载可靠性

| 参数名（YAML 路径） | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_DOWNLOAD_CONCURRENCY`（`accounts[].download.concurrency`） | 否 | `1` | `1`–`8` 的整数 | 设置同时下载的资源数。 |
| `IH_DOWNLOAD_TIMEOUT`（`accounts[].download.timeout`） | 否 | `300` | `1`–`3600` 秒 | 设置单次下载请求超时。 |
| `IH_MAX_RETRIES`（`accounts[].download.max_retries`） | 否 | `5` | `0`–`20` 的整数 | 设置下载失败后的重试次数。 |

#### 通知行为

这些开关只决定“什么事件要通知”；还必须在 `notifications.channels` 中配置至少一个通知渠道。

| 参数名（YAML 路径） | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `IH_NOTIFICATION_TITLE`（`notifications.title`） | 否 | `iCloudHarbor` | 任意非空文本 | 设置通知标题前缀。 |
| `IH_SILENT_NOTIFICATIONS`（`notifications.silent`） | 否 | `false` | `true`、`false` | 设置 Bark、Telegram 和 Webhook 是否静默通知。 |
| `IH_NOTIFY_STARTUP`（`notifications.startup`） | 否 | `false` | `true`、`false` | 是否发送普通容器启动通知；关闭认证通知时，也控制首次未认证的合并启动消息。 |
| `IH_NOTIFY_SUCCESS`（`notifications.success`） | 否 | `true` | `true`、`false` | 是否发送同步成功通知，包括没有新文件。 |
| `IH_NOTIFY_FAILURE`（`notifications.failure`） | 否 | `true` | `true`、`false` | 是否发送同步失败、空间不足和限流通知。 |
| `IH_NOTIFY_AUTH_REQUIRED`（`notifications.auth_required`） | 否 | `true` | `true`、`false` | 是否发送等待认证、认证失效、认证临期和认证恢复通知。 |
| `IH_NOTIFICATION_DAYS`（`notifications.notification_days`） | 否 | `7` | `1`–`30` 天 | 设置认证到期前多少天开始提醒。 |

已认证状态下的启动通知会根据实际配置显示“正在检查 iCloud”、延迟分钟数或下一次同步时间。
首次未认证启动只发送一条“容器已启动，等待 Apple 认证”的合并消息，不再紧接着发送第二条
认证失败消息。启用 `auth_required` 时，同一认证问题会在 SQLite 中持久去重，因此容器重启和
后续调度都不会重复提醒；`setup` 完成首次认证或自动续期后会发送认证恢复消息，说明后台同步
请求已提交，并重新允许未来新的认证问题触发提醒。关闭 `auth_required` 但开启 `startup` 时，
合并消息仍作为普通启动消息发送；两个开关都关闭时不发送。同步成功但没有新文件时标题为
“已是最新”；有下载时显示文件数和易读的数据量，不展示内部状态码。开启本地清理且实际删除
文件后，通知摘要继续显示数量和释放空间，展开详情可查看成功删除的文件名。Bark、Server酱、
Telegram 和企业微信正文最多列出 50 个文件名，超出部分提示查看容器日志；Webhook 的
`message` 保持摘要，`details` 提供同样的可读详情，`data.deleted_files` 携带完整文件名列表。

注意事项：

- 非空 `IH_*` 每次启动都会覆盖 YAML；从 `.env` 删掉变量后，之前写入 `config.yaml` 的值仍保留，需要同时改 YAML。
- 通知渠道（`notifications.channels`）为空时，所有 `IH_NOTIFY_*` 开关不会产生任何消息。
- 任意账号级 `IH_*` 覆盖都要求 YAML 的 `accounts` 列表恰好只有一个账号；当前版本也只支持一个启用账号。
- 相册、`recent_only`、`until_found` 扫描不会推进完整图库游标——以后移除这些限制时会安全地重新全量扫描，不会漏掉旧项目。

### 仅 `config.yaml` 可用的参数

| 参数名 | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `notifications.channels` | 否 | `[]` | 通知渠道列表 | 设置 Bark、Server酱、Telegram、企业微信或 Webhook 渠道。 |
| `version` | 否 | `1` | 只能是 `1` | 配置结构版本，不是软件版本。 |
| `runtime.database` | 否 | `/config/database/icloudharbor.db` | 容器内路径 | 设置 SQLite 数据库路径。 |
| `runtime.temp_path` | 否 | `/config/tmp` | 容器内路径 | 设置运行时临时目录，程序会自动创建。 |
| `accounts[].enabled` | 否 | `true` | `true`、`false` | 是否启用账号；当前必须且只能启用一个账号。 |
| `accounts[].destination.path` | 是 | `/photos`（自动生成） | 容器内路径 | 设置容器内照片下载目录。 |
| `accounts[].sync.mode` | 否 | `backup` | 只能是 `backup` | 固定为 iCloud 到本地的单向备份；是否同步“最近删除”由 `auto_delete` 单独控制。 |
| `accounts[].sync.schedule.interval` | 否 | 空 | 时长，如 `12h`、`1d`、`1w` | 设置同步间隔，与 `cron` 二选一。 |
| `accounts[].sync.schedule.cron` | 否 | 空 | 五段 Cron，如 `0 3 * * *` | 设置固定时间同步，与 `interval` 二选一。 |
| `security.redact_apple_id` | 否 | `true` | `true`、`false` | 是否在用户可见输出中隐藏 Apple ID。 |
| `security.session_encryption` | 否 | `false` | 只能是 `false` | 当前未实现 Session 加密。 |
| `security.allow_remote_delete` | 否 | `false` | 只能是 `false` | 固定禁止删除 iCloud 内容。 |

`IH_CONFIG_FILE=/config/config.yaml` 是 Compose 内部使用的配置文件位置，不是普通用户参数；
修改它会脱离默认持久化布局。

配置为严格模式：写错参数名会直接报错，不会静默忽略。

---

## 二、三分钟上手

已经安装 Docker Engine 和 `docker compose` 插件的 Linux/群晖用户，可以直接启动一键向导：

```bash
curl -fsSL https://raw.githubusercontent.com/lwx-cloud/icloudHarbor/main/deploy/install.sh | sudo bash
```

向导会询问本章的新手参数、创建挂载标记、启动容器并运行 `status`，随后可直接进入交互认证。
Apple 密码和验证码始终只由容器内的 `icloudharbor setup` 读取，不会写入 `.env` 或命令参数。
重复运行安装器只更新 Compose 和镜像，不覆盖现有配置、数据库、Session、凭据或照片。下面是
等价的手动部署步骤。一键安装默认把运行数据放在安装目录的 `data/config`，让 root 管理的
`.env`、Compose 与容器可写数据分离；因此配置目录不能与安装目录完全相同。

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
docker compose logs -f icloudharbor
```

`setup` 会读取密码 → 输入双重认证验证码 → 通知容器后台立即同步 → 发送认证恢复通知（已启用
认证通知时）→ 结束交互命令。下载过程继续显示在主容器日志中。

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
mkdir -p /volume1/docker/icloudharbor /volume2/photos/iCloud
touch /volume2/photos/iCloud/.icloudharbor-mounted
chown -R 99:100 /volume1/docker/icloudharbor /volume2/photos/iCloud
```

### 场景 2：改同步频率

```dotenv
# 数字就是小时，只能选择：6、12、24
IH_SYNC_INTERVAL=12
```

推荐选择 `12` 或 `24`。`6` 小时请求更频繁，可能增加 Apple 限流或风控概率。

必须固定在某个钟点运行时，才需要在高级 `config.yaml` 中使用 Cron：

```yaml
schedule: "0 3 * * *"
```

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

认证后可用 `docker compose exec icloudharbor icloudharbor list` 一次查看所有图库和相册的准确名称与 ID。
相册筛选必须全量扫描；同一照片属于多个所选相册时只下载一次。

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

**企业微信**（最简单，全走 `.env`，参数见[第一章](#一新手参数) `IH_WECOM_*`）：

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
  - id: your-account@example.com
    name: your-account@example.com
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
      mode: backup            # 只能是 backup，永不删除 iCloud 内容
      auto_delete: false      # true 时把 iCloud“最近删除”同步为安全的本地删除
      strategy: cursor
      full_scan_interval: 30d
      schedule: 24h
      run_on_start: true
      download_delay: 0

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
  channels: []               # 为空 = 完全关闭通知

security:
  redact_apple_id: true      # 用户可见输出中隐藏 Apple ID
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

文件路径都是容器内路径，密钥目录通常为 `/config/notification-keys/`。

| 字段名 | 必填 | 默认值 | 可选值或格式 | 说明 |
| --- | --- | --- | --- | --- |
| `type` | 是 | 无 | `bark`、`serverchan`、`telegram`、`wecom`、`webhook` | 设置通知渠道类型。 |
| `enabled` | 否 | `true` | `true`、`false` | 是否启用该渠道。 |
| `timeout` | 否 | `10` | `1`–`60` 秒 | 设置通知请求超时。 |
| `device_key_file`（Bark） | 是 | 无 | 容器内文件路径 | 设置 Bark Device Key 文件。 |
| `server` | 否 | Bark/企业微信官方 API | 完整 URL | 设置 Bark 或企业微信服务地址。 |
| `send_key_file`（Server酱） | 是 | 无 | 容器内文件路径 | 设置 Server酱 SendKey 文件。 |
| `token_file`（Telegram） | 是 | 无 | 容器内文件路径 | 设置 Telegram Bot Token 文件。 |
| `chat_id`（Telegram） | 是 | 无 | Chat ID | 设置 Telegram 接收会话。 |
| `corp_id`（企业微信） | 是 | 无 | 企业 ID | 设置企业微信企业。 |
| `corp_secret_file`（企业微信） | 是 | 无 | 容器内文件路径 | 设置企业微信应用 Secret 文件。 |
| `agent_id`（企业微信） | 是 | 无 | 正整数 | 设置企业微信应用 Agent ID。 |
| `to_user`（企业微信） | 是 | 无 | 成员 ID；多人用 `\|`；全部用 `@all` | 设置企业微信接收人。 |
| `content_source_url` | 否 | 空 | 完整 URL | 设置企业微信“查看详情”链接。 |
| `name` | 否 | 空 | 任意文本 | 设置企业微信消息来源名称。 |
| `media_id_download` | 否 | 空 | 素材 ID | 设置企业微信成功通知封面。 |
| `media_id_startup` | 否 | 空 | 素材 ID | 设置企业微信启动和认证恢复通知封面。 |
| `media_id_warning` | 否 | 空 | 素材 ID | 设置企业微信警告通知封面。 |
| `media_id_expiration` | 否 | 空 | 素材 ID | 设置企业微信认证临期通知封面。 |
| `url`（Webhook） | 是 | 无 | 完整 URL | 设置 Webhook 接收地址。 |
| `secret_file` | 否 | 空 | 容器内文件路径 | 设置 Webhook HMAC-SHA256 签名密钥。 |

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
| `{account}` / `{library}` / `{album}` | 账号 ID（默认就是 `IH_APPLE_ID`）/ 图库 ID / 相册名（未按相册扫描时为空）。 |
| `{media_type}` | `photo` 或 `video`。 |
| `{resource_type}` | 资源类型。 |
| `{version}` | `original` / `adjusted` 等版本名。 |

示例——图库 ID 做一级目录、照片再按年月分目录（效果等同 icloudpd 的 `libraries_with_dates`）：

```dotenv
IH_FOLDER_STRUCTURE={library}/{created:%Y/%m}
```

---

## 七、常用管理命令

公开命令只保留下面 7 个单词，不再使用多层子命令或日常操作参数：

| 命令 | 作用 |
| --- | --- |
| `setup` | 首次运行时询问密码并建立认证；已有本地凭据时自动续期，Apple 要求时只问验证码。 |
| `sync` | 向主容器提交一次后台同步请求；已有等待任务时不重复提交。 |
| `plan` | 只读扫描 Apple 并列出下载、修复和本地删除候选；不下载、不删除、不通知、不写运行记录或游标。 |
| `status` | 合并显示服务健康、认证、最近同步、调度和后台任务；只在异常时展开详情。 |
| `list` | 一次列出所有可访问图库及其相册。 |
| `backup` | 创建带 UTC 时间戳的 SQLite 在线备份，只输出备份路径。 |
| `reset` | 确认后清除 Session、Cookie 和保存的密码；不删除照片、数据库或配置。 |

```bash
docker compose exec icloudharbor icloudharbor status
docker compose exec icloudharbor icloudharbor list
docker compose exec icloudharbor icloudharbor plan
docker compose exec icloudharbor icloudharbor sync
docker compose exec icloudharbor icloudharbor backup
docker compose exec icloudharbor icloudharbor reset
docker compose exec icloudharbor icloudharbor setup
```

`daemon`、`healthcheck` 和 `bootstrap` 是 Docker 内部入口，对普通帮助隐藏，不是日常管理命令。

---

## 八、常见问题

**提示首次启动需要 `IH_APPLE_ID`**
`.env` 必须与 `docker-compose.yml` 同目录，值不能是空字符串。如果只是首次认证前修正邮箱，也可改
现有 YAML 的 `apple_id` 和 `id`；已经认证或同步后不要直接换邮箱。默认账号 ID 与
`IH_APPLE_ID` 相同，旧状态不会自动迁移，因此应为新账号使用新的 `IH_CONFIG_PATH`，最好也使用
独立的 `IH_PHOTOS_PATH`。

**提示挂载标记不存在**
默认配置的实际下载目录就是 `IH_PHOTOS_PATH`：`touch <IH_PHOTOS_PATH>/.icloudharbor-mounted`。
只有手工把 `accounts[].destination.path` 改成 `/photos/某个子目录` 时，标记才应放在对应子目录。

**权限错误**
确认 `IH_PUID:IH_PGID` 对 `IH_CONFIG_PATH` 和 `IH_PHOTOS_PATH` 都有读写权限；群晖用
`id 用户名` 查 UID/GID。

**改了 `.env` 没效果**
非空 `IH_*` 每次启动都覆盖 YAML。删掉某个环境变量后，之前写进 `config.yaml` 的值仍保留，需要同时改 YAML。

**容器异常停止后提示数据库锁被占用**
不用手工处理。下一次同步取得独占文件锁后会自动清理异常终止留下的租约；仍存活的同步进程不会被误清。

**没收到通知**
依次检查：① `channels` 有至少一个 `enabled: true` 的渠道；② 对应事件开关为 `true`；③ 密钥文件存在且容器 UID 可读；④ 企业微信应用允许该成员接收消息；⑤ 可信 IP/代理地址正确。

**Apple 要求重新认证**
直接运行 `setup`；已保存凭据时会自动续期。如果 Apple 密码已修改或凭据损坏，先运行 `reset`，再运行 `setup`。

---

## 九、安全说明

- `/config` 包含数据库、Apple Session、本地续期凭据和通知密钥，**必须限制访问并纳入备份**；升级或迁移前至少备份整个 `IH_CONFIG_PATH`。
- Apple 密码以 AES-256-GCM 保存，但密钥和密文都在 `/config/credentials`，宿主机 root 仍可恢复——它防的是意外明文泄露，不是硬件级保护。
- Apple Session 当前未加密。
- 永远不删除 iCloud 内容，也不把本地删除同步到远端。默认不清理本地；只有显式设置
  `IH_AUTO_DELETE=true`，才会把个人图库“最近删除”中的精确 Asset ID 匹配同步为本地删除。
- 本地自动删除前会校验受管路径、归属、文件类型、大小和 SHA-256；人工修改过的文件、符号链接、
  未被 SQLite 跟踪的文件和空目录都不会删除。开启前应备份 `/config` 和照片目录。
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
| 同步频率 | `download_interval=86400` | `IH_SYNC_INTERVAL=24` | 数字直接表示小时；高级 YAML 仍可用 Cron。 |
| 挂载标记 | `.mounted` | `.icloudharbor-mounted` | 文件名不同，需重新创建。 |
| 区域开关 | `icloud_china` + `auth_china` 两个 | `IH_REGION=china` 一个 | 更简洁。 |

### icloudpd 有、本项目用更好方式覆盖的

- `skip_videos`/`skip_live_photos` 反向开关 → `IH_DOWNLOAD_VIDEOS` 等正向开关；
- `photo_album="all albums"` → 默认就是全量，不需要特殊值；
- `align_raw`（3 档）→ `IH_RAW_MODE`（5 档）；
- `file_match_policy=name-id7` → `IH_CONFLICT_POLICY=always_asset_id`；
- `webhook_server/port/path/id/https` 五个参数拼 URL → 一个 `url` 搞定；
- `single_pass` → 需要立即检查时使用 `icloudharbor sync` 提交一次后台任务，仍由常驻容器执行；
- `albums_with_dates`/`libraries_with_dates` → 模板直接实现：`IH_FOLDER_STRUCTURE={album}/{created:%Y/%m/%d}`。
- `auto_delete` → `IH_AUTO_DELETE`；只按 SQLite 中的 iCloud Asset ID 精确匹配，并在删除本地文件前
  重新校验路径和 SHA-256，不使用同名猜测。

### 不会照搬的 icloudpd 参数

- `delete_after_download`、`keep_icloud_recent_days`：会主动删除 iCloud 内容，违反远端只读原则；
- `delete_accompanying`、`delete_empty_directories`：自动清理本地文件，不做；
- `nextcloud_*`、`sideways_copy_videos*`：上传/二次搬运，超出本地备份范围；
- `set_exif_datetime`：修改下载后的原始媒体，会破坏哈希幂等判断；
- `skip_check`、`file_match_policy`：固定使用 SQLite + 文件大小 + SHA-256 校验，不允许跳过安全检查。
