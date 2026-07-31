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

`.env.example` 已经包含下面这些参数和中文说明，可以直接复制使用。只有 `IH_APPLE_ID`
必填；路径、UID/GID 和时区按群晖实际情况修改。读表时先看“控制什么”，再决定自己是否属于
“什么时候改”的情况；没有明确需求就保留默认值。

`true` 表示开启，`false` 表示关闭。照片本身始终下载，没有“下载照片”开关。

| 变量名 | 控制什么 | 默认值与可选值 | 什么时候改 | 改后会发生什么 |
| --- | --- | --- | --- | --- |
| `IH_APPLE_ID` | 指定要备份哪一个 Apple Account 的 iCloud 照片。 | 无，首次启动必填；填写 Apple Account 邮箱。 | 第一次安装时填写。已经完成同步后如需换成另一个 Apple Account，应使用新的 `IH_CONFIG_PATH`，最好也使用独立的 `IH_PHOTOS_PATH`，按新实例初始化。 | 程序用这个账号生成配置并进行认证。不要只在旧实例中替换邮箱，否则相同内部账号 ID 可能复用旧数据库状态和下载目录。密码和验证码不要写在这里。 |
| `IH_CONTAINER_NAME` | 指定 Docker 创建出来的容器名称，方便用 `docker logs`、`docker exec` 或群晖界面找到它。 | `icloudharbor`；可填写未被其他容器占用的名称。 | 同一台 NAS 已有同名容器，或想用自己的命名规则时修改。 | 只改变容器名称，不改变账号、照片目录或同步行为；后续命令中的容器名也要跟着改。 |
| `IH_CONFIG_PATH` | 指定 NAS 上保存配置、数据库、登录 Session、本地续期凭据和通知密钥的目录。 | `./data/config`；填写宿主机绝对或相对路径。 | 群晖通常改成 `/volume1/docker/icloudharbor` 这类长期保存的目录。 | 该目录会挂载到容器的 `/config`。换到空目录会被视为全新安装，需要重新认证，也看不到旧同步记录。 |
| `IH_PHOTOS_PATH` | 指定照片和视频最终保存到 NAS 的哪个目录。 | `./data/photos`；填写宿主机绝对或相对路径。 | 第一次安装时按实际存储池填写。已有下载后要迁移目录，应先停止容器并把原目录连同挂载标记完整搬过去。 | 该目录会挂载到容器的 `/photos`，下载文件都写到这里；目录里必须有 `.icloudharbor-mounted` 标记文件。只改变量不会搬旧文件，指向空目录后程序会把数据库记录对应的本地文件视为缺失并重新核对或下载。 |
| `IH_PUID` | 指定容器内下载进程使用哪个 Linux 用户 ID 读写文件。 | `1000`；大于 `0` 的整数 UID。 | NAS 上的目标目录不属于 UID `1000`，或日志提示没有权限时修改；群晖可用 `id 用户名` 查询。 | 新文件会由该 UID 创建，程序也用它访问 `/config` 和 `/photos`。填错会导致配置不可读或下载失败。 |
| `IH_PGID` | 指定容器内下载进程使用哪个 Linux 用户组 ID。 | `1000`；大于 `0` 的整数 GID。 | 需要让某个群组共同管理照片，或目标目录按组授权时修改。 | 新文件会归属该 GID；应与目录的群组权限配套，否则可能出现无权写入。 |
| `IH_TIMEZONE` | 指定自动同步计划和“今天”按哪个时区计算。 | `.env.example` 为 `Asia/Shanghai`；可填写 IANA 时区，例如 `Asia/Shanghai`、`Europe/London`。 | NAS 不在中国时修改为所在地时区。 | Cron 固定时刻、下次任务时间和每日认证提醒会按该时区计算；它不会改变照片原有的拍摄时间。 |
| `IH_REGION` | 指定连接 Apple 全球 iCloud 还是中国大陆 iCloud 服务。 | `auto`；可选 `auto`、`global`、`china`。 | 通常不改；中国大陆账号在 `auto` 下认证失败时改为 `china`，非中国区账号需要强制全球端点时改为 `global`。 | 改变登录和读取照片所使用的 Apple 服务端点，不会改变本地保存目录。 |
| `IH_SYNC_INTERVAL` | 控制容器每隔多久检查一次 iCloud，并把新照片、视频或变化下载到本地。 | `24`；填写 `1`–`168` 的整数小时，常用 `6`、`12`、`24`。 | 想一天检查多次时填 `6` 或 `12`；一天一次保持 `24`。低于 `12` 小时可能更容易遇到 Apple 限流。 | `12` 表示“每隔 12 小时同步一次”，约每天两次；不是“每天 12 点”。需要固定钟点才使用高级 Cron。 |
| `IH_RUN_ON_START` | 控制容器每次启动或重启后，是否安排一次 iCloud 检查。 | `true`；可选 `true`、`false`。 | 一般保持 `true`；不希望 NAS 每次重启就访问 iCloud 时改为 `false`。 | `true` 在默认延迟为 `0` 时会立即同步，设置了 `IH_DOWNLOAD_DELAY` 则等指定分钟；`false` 会等待下一次间隔或 Cron 时间。 |
| `IH_DOWNLOAD_VIDEOS` | 控制是否下载普通视频资源。 | `true`；可选 `true`、`false`。 | 只想保存照片、需要节省空间或流量时改为 `false`。 | `false` 会跳过普通视频；不会删除已经下载的视频，也不控制 Live Photo 的短视频资源。 |
| `IH_DOWNLOAD_LIVE_PHOTOS` | 控制是否备份 Apple Live Photo 项目。 | `true`；可选 `true`、`false`。 | 不需要动态照片、只想减少占用空间时改为 `false`。 | `true` 会保存 Live Photo 的图片和配套短视频；`false` 会跳过整个 Live Photo 项目，已经下载的文件不会被删除。 |
| `IH_CONVERT_HEIC_TO_JPEG` | 控制下载 HEIC/HEIF 后是否额外生成一份普通 JPEG，便于旧设备或软件查看。 | `false`；可选 `true`、`false`。 | 查看设备不支持 HEIC，或其他软件只识别 JPEG 时开启。 | 开启后仍保留 HEIC 原片，并额外生成 JPEG，因此会增加磁盘占用；已有同名 JPEG 绝不会被覆盖。 |
| `IH_SYNOLOGY_PHOTOS_APP_FIX` | 控制下载完成后是否更新文件时间，帮助 Synology Photos 更快发现新文件。 | `false`；可选 `true`、`false`。 | 文件已经下载成功，但 Synology Photos 迟迟不显示时开启。 | 开启后会对新下载文件执行索引兼容处理；它不安装套件，也不改变照片的 EXIF 拍摄时间。 |
| `IH_ALBUMS` | 限定只扫描哪些 iCloud 相册。 | 空，表示不按相册限制；多个 ID 或名称用英文逗号分隔。 | 只想备份“家庭”“旅行”等指定相册时填写。 | 只读取列出的相册，其他相册和图库全量入口不会被扫描；可用 `albums list` 查询准确 ID/名称。 |
| `IH_EXCLUDE_ALBUMS` | 指定哪些 iCloud 相册不参与备份。 | 空，表示不排除；多个 ID 或名称用英文逗号分隔。 | 大部分内容都要备份，只想排除“屏幕快照”等少数相册时填写。 | 被列出的相册会跳过；同一个相册不能同时出现在 `IH_ALBUMS` 和本参数中。 |
| `IH_RECENT_ONLY` | 限制本次只处理 iCloud“最近项目”中的前 N 个项目。 | 空，表示处理全部；填写大于 `0` 的整数。 | 第一次试运行，想先用少量文件确认路径、命名和权限时填写，例如 `100`。 | 只扫描最近 N 个项目。以后删掉此参数会重新安全地全量扫描，不会把较早项目永久漏掉。 |

#### `IH_SYNC_INTERVAL` 应该怎么选

这个参数控制的是**容器两次自动检查 iCloud 之间相隔多少小时**。检查时，容器会寻找新照片、
新视频和需要修复的本地文件，再把它们下载到 NAS。它不控制 iPhone 什么时候上传到 iCloud：
iPhone 会按自身的 iCloud Photos、网络和电源条件上传，`IH_SYNC_INTERVAL` 只决定 NAS 多久
再从云端检查并下载一次。

直接填写小时数字，不要换算成秒：

| 填写值 | 实际频率 | 适合谁 | 取舍 |
| --- | --- | --- | --- |
| `6` | 每 6 小时一次，约每天 4 次 | 确实需要较快生成本地副本，并能接受更频繁访问 Apple 的用户 | 请求最频繁，更容易遇到 Apple 限流，不推荐普通用户使用。 |
| `12` | 每 12 小时一次，约每天 2 次 | 希望当天较早在 NAS 上看到新照片的用户 | 时效性更好，但请求次数是默认值的两倍；不建议再低于这个值。 |
| `24` | 每 24 小时一次，约每天 1 次 | 绝大多数家庭和群晖用户 | **默认且推荐**；本地备份时效、网络请求次数和 Apple 限流风险较平衡。 |
| `36` | 每 36 小时一次 | 不要求每天固定出现一份本地副本的用户 | 请求更少，但运行时刻会在白天和夜间轮换。 |
| `48` | 每 48 小时一次，约每 2 天一次 | 照片变化不多、希望减少外部请求的用户 | 最坏可能接近两天后才在 NAS 上看到新文件。 |
| `168` | 每 168 小时一次，即每 7 天一次 | 只需要每周本地归档的用户 | 请求最少，但手机或 iCloud 出现问题前，最新内容可能还没有落到 NAS。 |

程序允许 `1`–`168` 之间的任意整数，但上表是更容易理解的常用选择。没有设置时使用 `24`；
小于 `12` 小时不会更快让手机上传，只会让容器更频繁访问 Apple，可能触发限流。超出范围时
程序会直接指出配置错误，不会悄悄改成另一个值。

`IH_RUN_ON_START=true` 还会让容器在启动时额外检查一次。因此默认体验是“容器启动时检查，
之后每 24 小时检查”，而不是必须等满 24 小时才进行首次下载。

`IH_ALBUMS`、`IH_EXCLUDE_ALBUMS` 和 `IH_RECENT_ONLY` 没有明确需求时保持注释。筛选参数只决定
以后扫描什么，不会删除已经下载到 NAS 的文件。

### 企业微信（可选）

不用企业微信时整段保持注释。启用时前四项必须同时填写，少一项容器都会明确报错：

| 变量名 | 控制什么 | 默认值与填写方式 | 什么时候改 | 改后会发生什么 |
| --- | --- | --- | --- | --- |
| `IH_WECOM_ID` | 指定消息要通过哪个企业微信企业发送。 | 无；启用时必填企业 ID（CORPID）。 | 首次接入企业微信应用时填写。 | 程序用它向企业微信换取访问令牌；填错会导致通知发送失败。 |
| `IH_WECOM_SECRET` | 提供企业微信自建应用的 Secret。 | 无；启用时必填。 | 首次接入或企业微信后台重置 Secret 后修改。 | 容器启动时把它写入 `/config/notification-keys/wecom-secret`，不会写进 YAML；`.env` 本身仍含明文，建议权限设为 `0600`。 |
| `IH_WECOM_AGENT_ID` | 指定由企业微信中的哪一个自建应用发消息。 | 无；启用时必填正整数 Agent ID。 | 首次接入或更换自建应用时修改。 | 通知显示为该应用发送；Agent ID 与 Secret 不属于同一应用时会发送失败。 |
| `IH_WECOM_TO_USER` | 指定通知接收人。 | 无；启用时必填。单人填成员 ID，多人用 `\|` 分隔，全部成员填 `@all`。 | 需要改变接收范围时修改。 | 只有这里列出的成员会收到通知；成员还必须在该应用的可见范围内。 |
| `IH_WECOM_PROXY` | 指定企业微信 API 地址。 | 默认 `https://qyapi.weixin.qq.com`；填写完整 URL。 | 只有使用企业微信代理服务，或需要绕过可信 IP 限制时修改。 | 所有企业微信取令牌和发消息请求都会改走该地址；普通用户不要填写。 |
| `IH_WECOM_CONTENT_SOURCE_URL` | 指定通知中的“查看详情”跳转地址。 | 空；填写完整 URL。 | 有状态页、NAS 页面或其他详情页时填写。 | 没有素材 ID 时消息会变成带按钮的文本卡片；有素材 ID 时该地址会作为图文详情链接。 |
| `IH_WECOM_NAME` | 给消息正文增加一个自定义名称。 | 空；任意非敏感文本。 | 同一企业有多台 NAS、多个账号，需要区分消息来源时填写。 | 名称会显示在正文顶部；不影响企业微信应用名称。 |
| `MEDIA_ID_DOWNLOAD` | 指定“同步成功”通知使用的企业微信永久素材封面。 | 空；填写企业微信素材 ID。 | 想把成功通知从文本改成图文消息时填写。 | 每次成功同步，包括没有新文件时，都会使用该封面；留空则发送文本或文本卡片。 |
| `MEDIA_ID_STARTUP` | 指定“容器启动”通知的图文封面。 | 空；填写企业微信素材 ID。 | 已开启 `IH_NOTIFY_STARTUP=true` 且想使用图文消息时填写。 | 启动通知使用该封面；没有开启启动通知时，本参数不会单独产生消息。 |
| `MEDIA_ID_WARNING` | 指定失败、认证失效、空间不足等警告通知的图文封面。 | 空；填写企业微信素材 ID。 | 想让异常消息更醒目时填写。 | 各类失败和需要重新认证的通知使用该封面。 |
| `MEDIA_ID_EXPIRATION` | 指定“认证即将到期”通知的图文封面。 | 空；填写企业微信素材 ID。 | 开启认证临期提醒并想使用专用封面时填写。 | Cookie 到期提醒使用该封面；提醒只会在同步任务检查到临期时发送。 |

只要任意一个 `IH_WECOM_*` 或 `MEDIA_ID_*` 非空，就视为启用企业微信，前四项必须齐全；
这组环境变量还会替换 `config.yaml` 中已有的企业微信渠道。

### 高级配置

下面的参数用于特殊需求。环境变量和括号中的 YAML 路径控制同一件事；两边都写时，非空环境
变量优先。新用户没有对应需求时不要添加。

#### 日志与账号标识

| 环境变量（YAML 路径） | 控制什么 | 默认值与可选值 | 什么时候改、改后怎样 |
| --- | --- | --- | --- |
| `IH_LOG_LEVEL`（`runtime.log_level`） | 控制日志记录到多详细。 | `INFO`；`DEBUG` 最详细，`INFO` 显示正常进度，`WARNING` 只保留警告及错误，`ERROR` 只保留错误，`CRITICAL` 只保留致命错误。 | 正常使用保持 `INFO`；排查问题时临时改 `DEBUG` 会输出更多协议和断点信息，也会明显增加日志量。级别过高可能看不到“正在下载”等日常进度。 |
| `IH_LOG_FORMAT`（`runtime.log_format`） | 控制日志是给人阅读的文本，还是给日志系统解析的 JSON。 | `text`；可选 `text`、`json`。 | 群晖日志界面保持 `text`；接入 Loki、ELK 等日志平台时改 `json`，每条日志会变成结构化 JSON。 |
| `IH_ACCOUNT_ID`（`accounts[].id`） | 指定账号在数据库、Session、凭据、锁、路径模板和命令中的稳定内部 ID，不是 Apple 邮箱。 | `personal`；1–64 个字母、数字、`_`、`-`，首字符必须是字母或数字。 | 只在首次安装、还没有认证和下载前自定义。以后再改会被当成另一个内部账号，旧 Session 和凭据不会自动迁移，必须重新运行 `icloudharbor setup`，数据库中的旧账号状态也不会自动合并。 |
| `IH_ACCOUNT_NAME`（`accounts[].name`） | 指定日志和通知中显示的账号名称。 | `我的 iCloud`；任意易识别文本。 | 多台设备或通知来源难区分时修改，例如“家庭照片”。只改变显示文字，不改变 Apple Account。 |
| `IH_LIBRARIES`（`accounts[].libraries`） | 指定要扫描个人图库、共享图库中的哪些图库。 | `root`，表示个人图库；多个图库 ID/名称用英文逗号分隔。 | 需要备份共享图库或只扫描特定图库时填写；先用 `libraries list` 查询准确值。填写后只扫描列出的图库。 |

#### 存储空间与权限

| 环境变量（YAML 路径） | 控制什么 | 默认值与可选值 | 什么时候改、改后怎样 |
| --- | --- | --- | --- |
| `IH_MINIMUM_FREE_SPACE`（`accounts[].destination.minimum_free_space`） | 设置下载后必须为磁盘保留的最低可用空间。 | `10GB`；可填字节数或 `500MB`、`20GiB`、`1TB` 等容量。 | 照片卷还供其他应用使用时可提高；空间很小且确认可用时才降低。空间不足以容纳计划下载量并保留该余量时，本次同步会停止而不是写满磁盘。 |
| `IH_DIRECTORY_PERMISSIONS`（`accounts[].destination.directory_permissions`） | 指定程序创建或处理的照片目录权限。 | 空，使用系统默认权限（通常 `755`）。环境变量可填 `750`、`0750` 或 `0o750`；YAML 建议写成字符串 `"0750"` 或 `"0o750"`，不要写裸数字 `750`。 | 需要限制其他 NAS 用户浏览目录时修改。填 `750` 后只有属主和同组用户可进入，权限过严可能让 Synology Photos 无法索引。 |
| `IH_FILE_PERMISSIONS`（`accounts[].destination.file_permissions`） | 指定下载文件和生成 JPEG 的权限。 | 空，使用系统默认权限（通常 `644`）。环境变量可填 `640`、`0640` 或 `0o640`；YAML 建议写成字符串 `"0640"` 或 `"0o640"`，不要写裸数字 `640`。 | 需要限制其他用户读取照片时修改。填 `640` 后只有属主可写、同组可读；权限过严会影响相册软件读取。 |

#### 媒体版本与转换

| 环境变量（YAML 路径） | 控制什么 | 默认值与可选值 | 什么时候改、改后怎样 |
| --- | --- | --- | --- |
| `IH_PHOTO_SIZE`（`accounts[].media.photo_size`） | 指定普通照片和普通视频要下载哪些 iCloud 资源版本。 | 空，按原始版本处理；可用英文逗号组合 `original`、`medium`、`thumb`、`adjusted`、`alternative`。 | 通常保持空。要同时保存原片和编辑版可填 `original,adjusted`；只要较小预览可选 `medium` 或 `thumb`；显式列表要包含 `alternative` 才会选择 RAW/JPEG 伴随资源。选择越多，占用空间越大。 |
| `IH_LIVE_PHOTO_SIZE`（`accounts[].media.live_photo_size`） | 指定 Live Photo 图片和短视频使用哪个尺寸版本。 | `original`；可选 `original`、`medium`、`thumb`。 | 只有明确想节省空间时改为 `medium` 或 `thumb`。两部分会选择同一尺寸，画质和文件大小都会降低。 |
| `IH_RAW_MODE`（`accounts[].media.raw.mode`） | 决定遇到 RAW+JPEG 组合时选择哪些伴随资源。 | `both`；可选 `raw_only`、`jpeg_only`、`both`、`prefer_raw`、`prefer_jpeg`。 | 摄影工作流需要 RAW 时保持 `both` 或选 `raw_only`；只在普通设备查看可选 `jpeg_only`。`both` 同时选择 RAW 和 JPEG；两个 `prefer_*` 只选择对应的首选伴随格式。 |
| `IH_JPEG_PATH`（`accounts[].media.jpeg_path`） | 指定 HEIC 转换出的 JPEG 保存到哪里。 | 空，表示和 HEIC 使用相同相对目录；填写容器内路径，例如 `/photos/jpeg`。 | 想把兼容 JPEG 与原片分开放时填写。该路径必须位于持久化挂载中，否则重建容器后文件会丢失。 |
| `IH_JPEG_QUALITY`（`accounts[].media.jpeg_quality`） | 控制 HEIC 转 JPEG 的画质与文件大小。 | `100`；`0`–`100` 的整数。 | 只有开启 `IH_CONVERT_HEIC_TO_JPEG=true` 后才有作用。降低数值会减小 JPEG，但画质也会下降；不会改变 HEIC 原片。 |

`IH_PHOTO_SIZE` 的每个值含义不同：

| 值 | 下载什么 | 选择建议 |
| --- | --- | --- |
| `original` | Apple 提供的原始尺寸资源。 | 默认选择，适合正式备份；通常画质最好、文件也最大。 |
| `adjusted` | 用户在 Apple Photos 中编辑后由 iCloud 提供的版本。 | 想同时保留原片和编辑效果时使用 `original,adjusted`；服务端没有编辑版时不会凭空生成。 |
| `medium` | Apple 提供的中等尺寸资源。 | 只做快速浏览、磁盘空间有限时使用；不能替代原片备份。 |
| `thumb` | Apple 提供的缩略图资源。 | 只适合预览或测试路径，画质最低，不建议作为唯一备份。 |
| `alternative` | 允许显式选择 RAW/JPEG 伴随资源。 | 只有同时配置了 `IH_PHOTO_SIZE` 且仍想保留 RAW/JPEG 伴随文件时加入；它本身不是一种分辨率。 |

`IH_RAW_MODE` 的选择结果：

| 值 | RAW/JPEG 伴随资源的处理 | 选择建议 |
| --- | --- | --- |
| `raw_only` | 选择 RAW 伴随资源，并跳过普通 `photo_original` 与 JPEG 伴随资源；没有 RAW 的普通照片可能因此没有可下载资源。 | 只做 RAW 后期、明确接受跳过非 RAW 照片时使用。 |
| `jpeg_only` | 选择 JPEG 伴随资源，不选择 RAW；普通原始资源仍按 `IH_PHOTO_SIZE` 处理。 | 只在普通设备查看、不做 RAW 后期时使用。 |
| `both` | RAW 和 JPEG 伴随资源都选择，普通原始资源也照常处理。 | 默认且最完整，但占用空间最大。 |
| `prefer_raw` | 选择 RAW 伴随资源而不选择 JPEG 伴随资源，普通原始资源仍照常处理。 | 希望保留 RAW，同时减少一份 JPEG 伴随文件时使用。 |
| `prefer_jpeg` | 选择 JPEG 伴随资源而不选择 RAW，普通原始资源仍照常处理。 | 希望优先兼容查看并节省 RAW 空间时使用。 |

#### 日期与内容筛选

| 环境变量（YAML 路径） | 控制什么 | 默认值与可选值 | 什么时候改、改后怎样 |
| --- | --- | --- | --- |
| `IH_CREATED_AFTER`（`accounts[].filters.created_after`） | 只允许拍摄时间不早于指定时间的项目。 | 空，不限制；填写带时区的 ISO 8601 时间，例如 `2025-01-01T00:00:00+08:00`。 | 只想备份某个时间之后的媒体时填写，边界时间本身也包含。更早的项目会跳过，但本地已有文件不会删除。 |
| `IH_CREATED_BEFORE`（`accounts[].filters.created_before`） | 只允许拍摄时间不晚于指定时间的项目。 | 空，不限制；填写带时区的 ISO 8601 时间，例如 `2025-12-31T23:59:59+08:00`。 | 想备份某一历史时间段时填写，边界时间本身也包含。更晚的项目会跳过；不能早于 `IH_CREATED_AFTER`。 |
| `IH_FAVORITES_ONLY`（`accounts[].filters.favorites_only`） | 控制是否只备份 iCloud 中标记为“个人收藏”的项目。 | `false`；可选 `true`、`false`。 | 只想保留精选内容时设为 `true`。未收藏项目会跳过，之后改回 `false` 可重新扫描。 |
| `IH_INCLUDE_HIDDEN`（`accounts[].filters.include_hidden`） | 控制是否把 iCloud“已隐藏”相册中的项目也纳入备份。 | `false`；可选 `true`、`false`。 | 明确需要备份隐藏内容时设为 `true`。这些文件会像普通媒体一样写入目标目录，应确认目录访问权限足够严格。 |
| `IH_UNTIL_FOUND`（`accounts[].filters.until_found`） | 扫描时连续遇到多少个本地已存在项目后提前停止。 | 空，不提前停止；填写大于 `0` 的整数。 | 仅适合已完整备份、且新项目通常排在前面的超大图库。它能缩短扫描，但设置过小可能使更早的变化留到以后扫描才发现。 |

#### 目录、文件名与重名处理

| 环境变量（YAML 路径） | 控制什么 | 默认值与可选值 | 什么时候改、改后怎样 |
| --- | --- | --- | --- |
| `IH_FOLDER_STRUCTURE`（`accounts[].naming.folder_structure`） | 决定照片在目标目录下如何分文件夹。 | `{created:%Y/%m/%d}`；填写相对路径模板，字段见[第六章](#六文件名模板)。 | 想按年月、图库或相册整理时修改，例如 `{library}/{created:%Y/%m}`。程序不会主动搬走旧路径中的文件，可能按新路径再保存一份，因此长期使用后不要随意更换。 |
| `IH_FILENAME_TEMPLATE`（`accounts[].naming.filename`） | 决定每个下载文件的文件名。 | `{original_name}`；填写不含 `/` 或 `\` 的模板。 | 想在文件名中加入拍摄时间或资源 ID 时修改。模板会保留每个资源自己的扩展名，避免把 Live Photo 视频误命名为图片。 |
| `IH_CONFLICT_POLICY`（`accounts[].naming.conflict_policy`） | 决定两个不同 iCloud 项目得到同一路径时如何处理。 | `suffix_asset_id`；可选 `suffix_asset_id`、`always_asset_id`、`timestamp`、`error`。 | 通常保持默认：仅冲突时追加短 Asset ID。`always_asset_id` 总是追加 ID；`timestamp` 冲突时追加拍摄时间；`error` 遇到冲突就让任务失败，适合人工严格检查。 |

#### 调度与扫描方式

| 环境变量（YAML 路径） | 控制什么 | 默认值与可选值 | 什么时候改、改后怎样 |
| --- | --- | --- | --- |
| `IH_SCHEDULE`（`accounts[].sync.schedule`） | 用高级时长或 Cron 表达式安排自动同步。 | 新部署由 `IH_SYNC_INTERVAL=24` 控制；可填 `12h`、`1d` 或五段 Cron，例如 `0 3 * * *`。 | 只有必须每天固定时刻、固定星期运行时才使用。不能与 `IH_SYNC_INTERVAL` 同时设置；Cron 按 `IH_TIMEZONE` 执行。 |
| `IH_SYNC_STRATEGY`（`accounts[].sync.strategy`） | 控制平时使用增量游标扫描，还是每次都完整扫描图库。 | `cursor`；可选 `cursor`、`full`。 | 通常保持 `cursor`，速度快且仍会定期全量检查。怀疑游标漏掉服务端变化时可临时用 `full`；大型图库每次完整扫描会明显更慢。 |
| `IH_FULL_SCAN_INTERVAL`（`accounts[].sync.full_scan_interval`） | 在 `cursor` 模式下，控制多久额外做一次完整图库扫描。 | `30d`；可填 `12h`、`7d`、`4w` 等时长。 | 想更快发现游标之外的相册变化时缩短，超大图库想减少完整扫描时延长。它不改变日常同步间隔。 |
| `IH_DOWNLOAD_DELAY`（`accounts[].sync.download_delay`） | 让容器启动后的首次自动同步延迟几分钟。 | `0`；`0`–`60` 的整数分钟。 | 多个容器同时随 NAS 启动，想错开访问 Apple 时设置不同分钟数。它不会让每个文件之间等待，也不会替代同步间隔。 |

#### 下载可靠性

| 环境变量（YAML 路径） | 控制什么 | 默认值与可选值 | 什么时候改、改后怎样 |
| --- | --- | --- | --- |
| `IH_DOWNLOAD_CONCURRENCY`（`accounts[].download.concurrency`） | 控制同时下载多少个资源。 | `2`；`1`–`8` 的整数。 | 网络和磁盘性能较好时可小幅提高；遇到 Apple 限流、NAS 负载高或网络不稳定时降低。数值越高不一定越快，也会增加瞬时带宽和请求数。 |
| `IH_DOWNLOAD_TIMEOUT`（`accounts[].download.timeout`） | 控制单次下载网络请求最多等待多少秒。 | `300`；`1`–`3600` 秒。 | 大视频经常因慢速网络超时时提高；网络断开后想更快进入重试时降低。超时只结束当前尝试，仍会按重试次数继续。 |
| `IH_MAX_RETRIES`（`accounts[].download.max_retries`） | 控制一次下载失败后最多再尝试多少次。 | `5`；`0`–`20` 的整数。 | 网络偶发中断时可提高；希望错误尽快暴露时降低。`0` 表示首次失败后不重试；重试会使用退避等待并复用 `.part` 断点。 |

#### 通知行为

这些开关只决定“什么事件要通知”；还必须在 `notifications.channels` 中配置至少一个通知渠道。

| 环境变量（YAML 路径） | 控制什么 | 默认值与可选值 | 什么时候改、改后怎样 |
| --- | --- | --- | --- |
| `IH_NOTIFICATION_TITLE`（`notifications.title`） | 设置所有通知标题的统一前缀。 | `iCloudHarbor`；任意非空文本。 | 多台 NAS 或多个实例共用通知应用时修改，例如“家中 NAS”。同步结果和认证提醒标题都会使用它。 |
| `IH_SILENT_NOTIFICATIONS`（`notifications.silent`） | 控制支持静默模式的渠道是否发出声音。 | `false`；可选 `true`、`false`。 | 不想被频繁打扰时设为 `true`。当前会让 Bark、Telegram 和 Webhook 使用静默标记；企业微信和 Server酱不支持该开关。 |
| `IH_NOTIFY_STARTUP`（`notifications.startup`） | 控制容器调度器启动时是否通知。 | `false`；可选 `true`、`false`。 | 需要监控 NAS 重启或容器反复重启时开启。每次 daemon 启动都会发一条，不代表已经同步完成。 |
| `IH_NOTIFY_SUCCESS`（`notifications.success`） | 控制成功同步结束后是否通知。 | `true`；可选 `true`、`false`。 | 不需要日常成功消息时关闭。开启时即使没有新文件，也会在每次同步成功后发送结果。 |
| `IH_NOTIFY_FAILURE`（`notifications.failure`） | 控制同步失败、部分失败、空间不足、限流等异常是否通知。 | `true`；可选 `true`、`false`。 | 推荐保持开启。关闭后这些异常只写日志，不发外部消息；认证类提醒仍由下一项单独控制。 |
| `IH_NOTIFY_AUTH_REQUIRED`（`notifications.auth_required`） | 控制需要重新认证和认证即将到期时是否通知。 | `true`；可选 `true`、`false`。 | 推荐保持开启，避免 Session 失效后长期停止备份。关闭后仍可从容器日志看到认证提示。 |
| `IH_NOTIFICATION_DAYS`（`notifications.notification_days`） | 设置在 Apple Cookie 到期前多少天开始提醒续期。 | `7`；`1`–`30` 天。 | 希望预留更多处理时间时提高。提醒只在同步任务运行时检查，同一天最多一次，不会另开独立定时器。 |

注意事项：

- 非空 `IH_*` 每次启动都会覆盖 YAML；从 `.env` 删掉变量后，之前写入 `config.yaml` 的值仍保留，需要同时改 YAML。
- 通知渠道（`notifications.channels`）为空时，所有 `IH_NOTIFY_*` 开关不会产生任何消息。
- 为兼容早期版本，容器仍接受小写 `notification_days`，新部署统一用 `IH_NOTIFICATION_DAYS`。
- 任意账号级 `IH_*` 覆盖都要求 YAML 的 `accounts` 列表恰好只有一个账号；当前版本也只支持一个启用账号。
- 相册、`recent_only`、`until_found` 扫描不会推进完整图库游标——以后移除这些限制时会安全地重新全量扫描，不会漏掉旧项目。

#### 旧版本参数怎么处理

下面这些参数已经不能改变当前行为。旧 `.env` 里保留它们不会恢复旧功能，程序只会迁移或
给出警告；新配置不要再填写：

| 旧参数 | 过去控制什么 | 当前替代方式与实际结果 |
| --- | --- | --- |
| `IH_PHOTO_VERSION` | 选择原片、编辑版或两者。 | 已并入 `IH_PHOTO_SIZE`：原片用 `original`，编辑版用 `adjusted`，两者都要用 `original,adjusted`。旧值会尽量自动迁移。 |
| `IH_VERIFY_HASH` | 是否校验下载文件哈希。 | 已删除开关，SHA-256 校验固定开启，不能为了速度关闭。旧值会被忽略并显示警告。 |
| `IH_KEEP_PARTIAL` | 失败后是否保留未完成下载。 | 已删除开关，`.part` 断点续传固定开启。重试或下次运行会继续使用安全的部分文件。 |
| `IH_CHUNK_SIZE` | 每次从网络读取多大的下载块。 | 已固定为 `1MB`，不再让用户调节，避免错误值造成内存或性能问题。 |
| `IH_MOUNTED_MARKER` | 自定义照片卷挂载标记文件名。 | 已固定为 `.icloudharbor-mounted`。只有这个文件名能通过下载目录安全检查。 |
| `IH_DOWNLOAD_PHOTOS` | 是否下载照片。 | 照片下载固定开启；项目是照片备份工具，不支持只运行但跳过全部照片。 |
| `IH_KEEP_UNICODE` | 文件名是否保留中文等 Unicode 字符。 | Unicode 固定保留，同时仍会清理跨平台非法字符。 |
| `IH_UMASK` | 控制容器默认文件权限掩码。 | 固定为 `0022`；需要明确权限时使用 `IH_DIRECTORY_PERMISSIONS` 和 `IH_FILE_PERMISSIONS`。 |
| `IH_NOTIFY_NO_CHANGES` | 没有新文件时是否通知。 | 已并入 `IH_NOTIFY_SUCCESS`。现在每次成功同步都按该开关通知，包括没有新文件。 |
| `MEDIA_ID_DELETE` | 删除类通知的企业微信封面。 | 已删除且没有替代项，因为项目不会删除 iCloud 或自动清理本地文件。 |
| `IH_DESTINATION` | 直接设置容器内下载路径。 | 已删除。容器内路径固定为 `/photos`，NAS 上的位置通过 `IH_PHOTOS_PATH` 控制。 |

**0.3.3 变更**：移除 `IH_DESTINATION`，下载目录固定为 `/photos`（`IH_PHOTOS_PATH` 指哪下哪）；Live Photo 同版本去重；`jpeg_quality` 默认 100；认领已有文件；精简启动日志。

**0.3.4 变更**：重新提供面向普通用户的 `IH_SYNC_INTERVAL`，纯数字按小时解释；新部署默认
每 24 小时同步并在容器启动后立即检查。旧的 `12h`、`1d` 以及 `IH_SCHEDULE`/Cron 继续兼容。

### 仅 `config.yaml` 可用的参数

这些字段没有面向普通用户的环境变量入口。除通知渠道外，都是程序管理项：

| YAML 参数 | 控制什么 | 默认值与可选值 | 什么时候改、改后怎样 |
| --- | --- | --- | --- |
| `notifications.channels` | 指定通知实际发送到 Bark、Server酱、Telegram、企业微信或 Webhook 中的哪些渠道。 | `[]`；通知渠道列表，见[第五章](#五通知渠道配置)。 | 需要外部通知时至少添加一个 `enabled: true` 的渠道。保持空列表时，即使所有 `IH_NOTIFY_*` 都是 `true`，也不会发送消息。 |
| `version` | 标记配置文件结构版本，供程序判断如何读取配置。 | 只能是 `1`。 | 不要修改。它不是软件版本号，改成其他数字会使配置校验失败。 |
| `runtime.database` | 指定 SQLite 数据库在容器内的位置。 | `/config/database/icloudharbor.db`。 | 正常 Docker 部署不要修改。换路径会像使用另一份同步历史，可能重新扫描和核对已有文件。 |
| `runtime.temp_path` | 指定容器运行时临时目录。 | `/config/tmp`。 | 正常 Docker 部署不要修改。目录必须存在且可写；容器停止时清理其内容不会删除正式照片，但运行中不要清理。 |
| `accounts[].enabled` | 标记账号是否启用。 | `true`；布尔值。 | 当前版本必须且只能启用一个账号，因此不要改为 `false`，否则容器会拒绝启动。 |
| `accounts[].destination.path` | 指定照片卷在容器内的下载根目录。 | `/photos`。 | Docker 用户应通过 `IH_PHOTOS_PATH` 改 NAS 上的实际目录，不要改这里；改到未挂载路径可能把文件写进容器层，并会因缺少挂载标记而被安全检查阻止。 |
| `accounts[].sync.mode` | 限制同步只能做“iCloud 到本地”的只读备份。 | 只能是 `backup`。 | 不要修改。项目不支持镜像删除、双向同步或把本地变化上传到 iCloud。 |
| `accounts[].sync.schedule.interval` | 用结构化 YAML 写“两次同步之间相隔多久”。 | 与 `cron` 二选一；填写 `12h`、`1d`、`1w` 等时长。 | 只有维护高级 YAML 时使用；普通用户用 `IH_SYNC_INTERVAL` 更直观。它仍表示间隔，不表示固定钟点。 |
| `accounts[].sync.schedule.cron` | 用结构化 YAML 写固定钟点的同步计划。 | 与 `interval` 二选一；填写标准五段 Cron，例如 `0 3 * * *`。 | 只有必须按固定时刻运行时使用。按 `IH_TIMEZONE` 解释，不能同时再填写 `schedule.interval`。 |
| `security.redact_apple_id` | 控制账号列表等用户可见输出是否隐藏 Apple Account 邮箱。 | `true`；可选 `true`、`false`。 | 推荐保持 `true`。改为 `false` 可能让真实邮箱出现在终端输出中，分享命令结果前必须自行脱敏；全局敏感日志过滤仍会继续工作。 |
| `security.session_encryption` | 预留的 Apple Session 文件加密开关。 | 只能是 `false`。 | 当前未实现，设为 `true` 会直接报错；不要用它判断 `/config` 是否安全。 |
| `security.allow_remote_delete` | 远端删除安全闸。 | 只能是 `false`。 | 永远不要修改。程序不会删除 iCloud 内容，设为其他值会校验失败。 |

`IH_CONFIG_FILE=/config/config.yaml` 是 Compose 内部使用的配置文件位置，不是普通用户参数；
修改它会脱离默认持久化布局。为兼容早期版本，容器仍接受小写 `notification_days`，新部署统一
使用 `IH_NOTIFICATION_DAYS`。

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
docker compose logs -f icloudharbor
```

`setup` 会读取密码 → 输入双重认证验证码 → 通知容器后台立即同步 → 结束交互命令。
下载过程继续显示在主容器日志中。

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
# 数字就是小时，常用选择：6、12、24
IH_SYNC_INTERVAL=12
```

低于 12 小时的频率可能触发 Apple 限流，不建议更密。

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
      schedule: 24h
      run_on_start: true
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

下面是通知渠道中每个字段的作用。文件路径都是**容器内路径**；默认把宿主机
`<IH_CONFIG_PATH>/notification-keys/` 挂载为 `/config/notification-keys/`。

| YAML 字段 | 用于哪个渠道 | 控制什么 | 什么时候填写、填写后怎样 |
| --- | --- | --- | --- |
| `type` | 全部 | 选择用哪一种通知服务。 | 每个渠道必填一个：`bark`、`serverchan`、`telegram`、`wecom` 或 `webhook`。程序据此决定请求格式。 |
| `enabled` | 全部 | 临时启用或停用这一条渠道配置。 | 默认 `true`。改成 `false` 后保留配置和密钥文件，但不再向该渠道发送消息。 |
| `timeout` | 全部 | 设置每次通知网络请求最多等待多少秒。 | 默认 `10`，可填 `1`–`60`。通知服务较慢时提高；超时只会让本次通知失败，不会让已完成的照片同步回滚。 |
| `device_key_file` | Bark | 指向保存 Bark Device Key 的文件。 | Bark 渠道必填，例如 `/config/notification-keys/bark-device-key`。程序从文件读取密钥，不把密钥直接写进 YAML。 |
| `server` | Bark | 指定 Bark 服务地址。 | 默认 `https://api.day.app`；使用自建 Bark 服务时填写完整 URL。之后 Bark 消息全部发往该地址。 |
| `send_key_file` | Server酱 | 指向保存 Server酱 SendKey 的文件。 | Server酱渠道必填，例如 `/config/notification-keys/serverchan-send-key`。程序用它调用 Server酱发送接口。 |
| `token_file` | Telegram | 指向保存 Telegram Bot Token 的文件。 | Telegram 渠道必填，例如 `/config/notification-keys/telegram-token`。Token 不应直接写在 YAML 或日志里。 |
| `chat_id` | Telegram | 指定机器人把消息发到哪个用户、群组或频道。 | Telegram 渠道必填。私聊和群组填对应 Chat ID，频道或超级群组常见为以 `-100` 开头的 ID；填错会发不到目标会话。 |
| `corp_id` | 企业微信 | 指定企业微信企业 ID。 | 企业微信渠道必填，必须与下面的 Secret 和 Agent ID 属于同一企业及应用。 |
| `corp_secret_file` | 企业微信 | 指向保存自建应用 Secret 的文件。 | 企业微信渠道必填，例如 `/config/notification-keys/wecom-secret`。程序从文件读取 Secret 并换取访问令牌。 |
| `agent_id` | 企业微信 | 指定发送消息的自建应用。 | 企业微信渠道必填正整数。填错或与 Secret 不匹配会导致发送失败。 |
| `to_user` | 企业微信 | 指定消息接收成员。 | 企业微信渠道必填；单人填成员 ID，多人用 `\|` 分隔，`@all` 表示全部可见成员。 |
| `server` | 企业微信 | 指定企业微信 API 或代理服务的根地址。 | 默认 `https://qyapi.weixin.qq.com`。只有已有可用代理服务时修改；改地址本身不保证绕过企业微信的可信 IP 要求。 |
| `content_source_url` | 企业微信 | 指定图文或文本卡片的详情链接。 | 可选。填写后消息可显示“查看详情”入口；必须是接收人能访问的完整 URL。 |
| `name` | 企业微信 | 给消息正文和图文作者增加来源名称。 | 可选。多台 NAS 或多个实例共用一个应用时填写，方便接收人区分。 |
| `media_id_download` | 企业微信 | 指定成功同步通知的永久素材封面。 | 可选。填写后成功通知使用图文消息，包括没有新文件的成功同步。 |
| `media_id_startup` | 企业微信 | 指定容器启动通知的永久素材封面。 | 可选。只有 `notifications.startup: true` 时会用到。 |
| `media_id_warning` | 企业微信 | 指定同步失败、部分失败和认证失效等警告的永久素材封面。 | 可选。填写后这些异常通知使用图文消息。 |
| `media_id_expiration` | 企业微信 | 指定认证即将到期提醒的永久素材封面。 | 可选。进入 `notification_days` 提醒窗口后，在同步检查时使用。 |
| `url` | Webhook | 指定接收 iCloudHarbor JSON 消息的完整地址。 | Webhook 渠道必填。每个启用事件都会向该 URL 发送包含事件类型、标题、正文、数据和时间戳的 POST 请求。 |
| `secret_file` | Webhook | 指向 Webhook 签名密钥文件。 | 可选。填写后请求会带 HMAC-SHA256 签名，接收端可验证消息没有被篡改；留空则不签名。 |

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

示例——图库 ID 做一级目录、照片再按年月分目录（效果等同 icloudpd 的 `libraries_with_dates`）：

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
`.env` 必须与 `docker-compose.yml` 同目录，值不能是空字符串。如果只是首次认证前修正邮箱，也可改
现有 YAML 的 `apple_id`；已经认证或同步后不要直接换邮箱，应为新账号使用新的
`IH_CONFIG_PATH`，最好也使用独立的 `IH_PHOTOS_PATH`。

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
| 同步频率 | `download_interval=86400` | `IH_SYNC_INTERVAL=24` | 数字直接表示小时；高级 YAML 仍可用 Cron。 |
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
