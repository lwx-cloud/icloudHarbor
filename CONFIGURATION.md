# iCloudHarbor 配置与命令手册

本文面向使用 Docker 或 NAS 部署 iCloudHarbor 的用户，包含首次配置、常见调整、全部参数、
通知配置、命令参考和故障排查。

如果你只是第一次安装，请先看“1. 五分钟完成配置”。普通单账号用户通常只需要修改
`.env`，不需要手写 `config.yaml`。

> 当前版本为 `0.1.0`。只支持一个启用的 Apple Account 和个人图库，不会删除 iCloud
> 中的内容，也不会把本地删除同步到远端。

按需求查阅：

| 你想做什么 | 从哪里开始 |
| --- | --- |
| 第一次部署并完成认证 | [1. 五分钟完成配置](#1-五分钟完成配置) |
| 搞清楚宿主机路径和容器路径 | [3. 路径、挂载和权限](#3-路径挂载和权限) |
| 设置定时、媒体、日期或文件名 | [4. 常见配置场景](#4-常见配置场景) |
| 查询某个 `IH_*` 参数 | [5. Docker 环境变量完整参考](#5-docker-环境变量完整参考) |
| 配置通知或直接编辑 YAML | [7. 通知配置](#7-通知配置)、[8. 高级 YAML 配置](#8-高级-yaml-配置) |
| 查询命令或解决报错 | [9. 命令参考](#9-命令参考)、[10. 故障排查](#10-故障排查) |

## 1. 五分钟完成配置

### 1.1 复制环境变量模板

在项目目录执行：

```bash
cp .env.example .env
```

打开 `.env`，第一次部署只需要重点填写以下内容：

```dotenv
IH_APPLE_ID=your-account@example.com
IH_CONFIG_PATH=./data/config
IH_PHOTOS_PATH=./data/photos
IH_PUID=1000
IH_PGID=1000
IH_TIMEZONE=Asia/Shanghai
```

这些值分别表示：

| 参数 | 用途 |
| --- | --- |
| `IH_APPLE_ID` | 要备份的 Apple Account 邮箱。 |
| `IH_CONFIG_PATH` | 宿主机上保存配置、数据库、Session 和凭据的目录。 |
| `IH_PHOTOS_PATH` | 宿主机上保存照片的根目录。 |
| `IH_PUID` / `IH_PGID` | 写入文件时使用的宿主机用户和组 ID。 |
| `IH_TIMEZONE` | 日志、Cron 和日期目录使用的时区。 |

Apple 密码和验证码不要写入 `.env`。程序会在后面的交互式认证中读取密码。

### 1.2 创建目录和挂载标记

默认下载目标是容器内的 `/photos/personal`，对应宿主机的
`./data/photos/personal`：

```bash
mkdir -p ./data/config ./data/photos/personal
touch ./data/photos/personal/.icloudharbor-mounted
```

`.icloudharbor-mounted` 是下载保护标记。没有这个文件时，iCloudHarbor 会拒绝下载，防止
照片卷挂载失败后把大量文件写进容器层。

如果使用绝对路径，例如群晖上的 `/volume2/photos/iCloud`，标记应创建在：

```text
/volume2/photos/iCloud/personal/.icloudharbor-mounted
```

### 1.3 启动容器

如果 Docker Hub 仓库当前为私有，先登录一次：

```bash
docker login
```

然后拉取镜像并启动：

```bash
docker compose pull
docker compose up -d
docker compose ps
```

第一次启动会根据 `.env` 自动生成：

```text
<IH_CONFIG_PATH>/config.yaml
```

如果 `config.yaml` 已存在，容器不会覆盖它。

### 1.4 完成 Apple 认证

```bash
docker exec -it icloudharbor icloudharbor setup
```

程序会依次：

1. 检查配置、数据库、照片目录、挂载标记、空间和写权限；
2. 以星号遮罩读取 Apple Account 密码；
3. 在 Apple 要求时询问双重认证验证码；
4. 保存本地续期凭据；
5. 验证个人 iCloud Photos 图库是否可访问。

### 1.5 先预览，再同步

```bash
docker exec -it icloudharbor icloudharbor sync plan
docker exec -it icloudharbor icloudharbor sync run
```

`sync plan` 只扫描并显示计划，不下载文件，也不更新同步游标。建议第一次正式同步前始终先
运行它。

## 2. `.env` 和 `config.yaml` 是什么关系

iCloudHarbor 有两层配置：

| 配置 | 适合谁 | 作用 |
| --- | --- | --- |
| `.env` | 普通 Docker/NAS 用户 | 设置挂载路径、UID/GID，以及常用业务参数。 |
| `/config/config.yaml` | 需要高级配置的用户 | 保存完整应用配置，以及通知通道等高级设置。 |

配置加载分为两个阶段。

第一阶段决定读取哪个 YAML 文件：

1. 命令行 `--config /path/to/config.yaml`；
2. 环境变量 `IH_CONFIG_FILE`；
3. 默认 `/config/config.yaml`。

第二阶段加载 YAML，然后用所有非空的 `IH_*` 业务环境变量覆盖对应字段。

### 首次启动

- `config.yaml` 不存在时，必须设置非空的 `IH_APPLE_ID`。
- 程序把当时的环境变量和默认值写入新的 `config.yaml`。
- 新文件权限设置为 `0600`。

### 后续启动

- 已存在的 `config.yaml` 不会被重新生成或覆盖。
- `.env` 中的非空值仍会在每次启动时覆盖 YAML，但不会写回 YAML。
- `.env` 中的空字符串表示“没有覆盖”，不是“清除 YAML 中的值”。

例如，第一次启动时设置了日期范围，日期会被写入 `config.yaml`。以后仅把 `.env` 中的日期
留空，不会删除 YAML 中已经保存的日期。此时需要编辑 `config.yaml`，把相应字段改成
`null`。

查看当前真正生效的配置：

```bash
docker exec icloudharbor icloudharbor config show
```

检查配置是否合法：

```bash
docker exec icloudharbor icloudharbor config validate
```

`config show` 不显示密码，但包含 Apple Account 邮箱，不要把完整输出直接粘贴到公开 Issue。

## 3. 路径、挂载和权限

这是最容易混淆的部分。宿主机路径和容器内路径不是同一个概念：

| 名称 | 示例 | 在哪里使用 |
| --- | --- | --- |
| 配置宿主机路径 | `/volume1/docker/icloudharbor-data` | `.env` 的 `IH_CONFIG_PATH`。 |
| 照片宿主机路径 | `/volume2/photos/iCloud` | `.env` 的 `IH_PHOTOS_PATH`。 |
| 配置容器路径 | `/config` | Compose 固定挂载点。 |
| 照片容器路径 | `/photos` | Compose 固定挂载点。 |
| 下载目标 | `/photos/personal` | `IH_DESTINATION` 或 YAML。 |

下面的配置：

```dotenv
IH_CONFIG_PATH=/volume1/docker/icloudharbor-data
IH_PHOTOS_PATH=/volume2/photos/iCloud
IH_DESTINATION=/photos/personal
```

表示照片最终保存在：

```text
/volume2/photos/iCloud/personal
```

不要把宿主机路径 `/volume2/...` 填入 `IH_DESTINATION`。`IH_DESTINATION` 必须使用容器内路径。

### PUID、PGID 和目录权限

在 Linux 上查看当前用户的数字 UID/GID：

```bash
id -u
id -g
```

群晖可以使用：

```bash
id <用户名>
```

然后把数字填写到 `.env`：

```dotenv
IH_PUID=1026
IH_PGID=100
```

确保该 UID/GID 能写入配置目录和照片目录。必要时调整宿主机目录属主：

```bash
sudo chown -R 1026:100 /volume1/docker/icloudharbor-data
sudo chown -R 1026:100 /volume2/photos/iCloud
```

`1026:100` 只是示例，请使用宿主机上的真实值。

容器不需要 `privileged`，也不需要映射任何业务端口。入口阶段只使用 `CHOWN`、`SETGID` 和
`SETUID` 调整权限，随后业务进程以配置的非 root 用户运行。

## 4. 常见配置场景

以下示例都可以直接写入 `.env`。修改后重新应用 Compose 配置：

```bash
docker compose up -d
docker exec icloudharbor icloudharbor config validate
```

### 4.1 中国大陆 iCloud

推荐先使用自动判断：

```dotenv
IH_REGION=auto
```

如果需要强制使用中国大陆端点：

```dotenv
IH_REGION=china
```

全球端点使用：

```dotenv
IH_REGION=global
```

### 4.2 启动后立即同步

```dotenv
IH_RUN_ON_START=true
```

默认是 `false`，容器启动后等待下一个计划时间。

### 4.3 每天定时同步

上海时区每天凌晨 02:30：

```dotenv
IH_TIMEZONE=Asia/Shanghai
IH_SCHEDULE=30 2 * * *
IH_SYNC_INTERVAL=
```

`IH_SCHEDULE` 使用五段 Cron：

```text
分钟 小时 日 月 星期
```

### 4.4 固定间隔同步

每 6 小时运行一次：

```dotenv
IH_SCHEDULE=
IH_SYNC_INTERVAL=6h
```

`IH_SCHEDULE` 和 `IH_SYNC_INTERVAL` 只能设置一个。

### 4.5 只下载照片，不下载普通视频

```dotenv
IH_DOWNLOAD_PHOTOS=true
IH_DOWNLOAD_VIDEOS=false
```

Live Photo 属于照片 Asset。即使关闭普通视频，启用 Live Photo 时仍会保留其视频伴随资源。
如果连 Live Photo 视频也不需要：

```dotenv
IH_DOWNLOAD_LIVE_PHOTOS=false
```

### 4.6 原片、编辑版和 RAW

只下载原片：

```dotenv
IH_PHOTO_VERSION=original
```

原片和编辑版都下载：

```dotenv
IH_PHOTO_VERSION=both
```

RAW 与 JPEG 都保留：

```dotenv
IH_RAW_MODE=both
```

只选择 RAW：

```dotenv
IH_RAW_MODE=raw_only
```

完整可选值见“6.3 媒体选择”。

### 4.7 只下载指定日期范围

只处理 2026 年 7 月 18 日（上海时区）：

```dotenv
IH_CREATED_AFTER=2026-07-18T00:00:00+08:00
IH_CREATED_BEFORE=2026-07-18T23:59:59.999999+08:00
```

两个边界都包含在结果内。恢复全量备份时，还要检查 `config.yaml` 中是否保留了日期；如有，
把 `created_after` 和 `created_before` 改成 `null`。

### 4.8 只下载收藏或包含隐藏项目

```dotenv
IH_FAVORITES_ONLY=true
IH_INCLUDE_HIDDEN=true
```

两项互不依赖，可以单独开启。

### 4.9 修改目录结构和文件名

按年月存放，并在文件名前添加拍摄时间：

```dotenv
IH_FOLDER_STRUCTURE={created:%Y/%m}
IH_FILENAME_TEMPLATE={created:%Y%m%d_%H%M%S}_{original_name}
```

默认值为：

```dotenv
IH_FOLDER_STRUCTURE={created:%Y/%m/%d}
IH_FILENAME_TEMPLATE={original_name}
```

修改命名规则不会自动移动已经下载的文件。建议先运行 `sync plan` 查看新路径，再决定是否正式
同步。

### 4.10 调整下载并发

普通 NAS 建议先保持默认值：

```dotenv
IH_DOWNLOAD_CONCURRENCY=2
IH_CHUNK_SIZE=1MB
IH_DOWNLOAD_TIMEOUT=300
IH_MAX_RETRIES=5
```

网络和磁盘性能充足时可以逐步提高并发，最大为 `8`。并发越高不一定越快，也可能更容易触发
Apple 限流。

### 4.11 查看详细日志

```dotenv
IH_LOG_LEVEL=DEBUG
IH_LOG_FORMAT=text
```

适合日志平台采集时可以使用：

```dotenv
IH_LOG_FORMAT=json
```

公开日志前应再次检查其中是否含有账号、路径、Cookie 或通知地址。

## 5. Docker 环境变量完整参考

没有特殊需求的参数可以在 `.env` 中保持空白。空白值不会覆盖自动生成的 YAML。

### 5.1 容器和宿主机

这些参数控制容器本身，不写入应用 YAML：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_CONTAINER_NAME` | `icloudharbor` | 容器名称，也是文档中 `docker exec` 使用的名称。 |
| `IH_CONFIG_PATH` | `./data/config` | 宿主机状态目录，挂载到 `/config`，必须持久化。 |
| `IH_PHOTOS_PATH` | `./data/photos` | 宿主机照片根目录，挂载到 `/photos`。 |
| `IH_PUID` | `1000` | 业务进程使用的数字 UID，必须大于 `0`。 |
| `IH_PGID` | `1000` | 业务进程使用的数字 GID，必须大于 `0`。 |
| `IH_UMASK` | `0022` | 新文件权限掩码，可用范围 `0000`–`0777`。 |
| `IH_TIMEZONE` | `UTC` | 同时设置容器时区和应用调度时区。 |
| `IH_CONFIG_FILE` | `/config/config.yaml` | 容器内 YAML 路径；Compose 已固定，通常不要修改。 |

### 5.2 账号和下载目标

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_ACCOUNT_ID` | `personal` | 稳定账号 ID。建立数据库后不建议修改。 |
| `IH_ACCOUNT_NAME` | `我的 iCloud` | 状态和通知中显示的账号名称。 |
| `IH_APPLE_ID` | 无 | Apple Account 邮箱；首次生成配置时必填。 |
| `IH_REGION` | `auto` | `auto`、`global` 或 `china`。 |
| `IH_DESTINATION` | `/photos/personal` | 容器内下载目标，通常应位于 `/photos` 下。 |
| `IH_MOUNTED_MARKER` | `.icloudharbor-mounted` | 下载目标内必须存在的保护标记文件。 |
| `IH_MINIMUM_FREE_SPACE` | `10GB` | 下载完成后必须保留的最小磁盘空间。 |

`IH_ACCOUNT_ID` 长度为 1–64 个字符，只能包含字母、数字、下划线和连字符，首字符必须是
字母或数字。

### 5.3 媒体、筛选和命名

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_DOWNLOAD_PHOTOS` | `true` | 是否下载照片 Asset。 |
| `IH_DOWNLOAD_VIDEOS` | `true` | 是否下载普通视频 Asset。 |
| `IH_DOWNLOAD_LIVE_PHOTOS` | `true` | 是否保留 Live Photo 图片和视频资源。 |
| `IH_PHOTO_VERSION` | `original` | `original`、`adjusted` 或 `both`。 |
| `IH_RAW_MODE` | `both` | RAW/JPEG 选择策略。 |
| `IH_CREATED_AFTER` | 空 | 只保留不早于该时间的 Asset。 |
| `IH_CREATED_BEFORE` | 空 | 只保留不晚于该时间的 Asset。 |
| `IH_FAVORITES_ONLY` | `false` | 只下载收藏项目。 |
| `IH_INCLUDE_HIDDEN` | `false` | 是否包含隐藏项目。 |
| `IH_FOLDER_STRUCTURE` | `{created:%Y/%m/%d}` | 目标目录内的相对目录模板。 |
| `IH_FILENAME_TEMPLATE` | `{original_name}` | 文件名模板，不能包含 `/` 或 `\`。 |
| `IH_CONFLICT_POLICY` | `suffix_asset_id` | 文件重名处理策略。 |
| `IH_KEEP_UNICODE` | `true` | 是否在路径中保留中文等 Unicode 字符。 |

### 5.4 同步和调度

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_SYNC_STRATEGY` | `cursor` | `cursor` 增量同步，`full` 每次执行全量扫描。 |
| `IH_FULL_SCAN_INTERVAL` | `30d` | 增量策略下强制全量校准的最大间隔。 |
| `IH_SCHEDULE` | `0 3 * * *` | 五段 Cron，与 `IH_SYNC_INTERVAL` 二选一。 |
| `IH_SYNC_INTERVAL` | 空 | 固定间隔，例如 `6h`。 |
| `IH_RUN_ON_START` | `false` | 容器启动后是否立即安排一次同步。 |

`cursor` 无效、从未完成全量扫描，或距离上次全量扫描超过
`IH_FULL_SCAN_INTERVAL` 时，程序会自动执行全量扫描。只有本次全部资源成功时才提交新游标。

### 5.5 下载和校验

| 环境变量 | 默认值 | 范围或说明 |
| --- | --- | --- |
| `IH_DOWNLOAD_CONCURRENCY` | `2` | 并发下载数，范围 `1`–`8`。 |
| `IH_CHUNK_SIZE` | `1MB` | 流式块大小，范围 `64KiB`–`64MiB`。 |
| `IH_DOWNLOAD_TIMEOUT` | `300` | 单次下载超时秒数，范围 `1`–`3600`。 |
| `IH_MAX_RETRIES` | `5` | 每个资源的额外重试次数，范围 `0`–`20`。 |
| `IH_VERIFY_HASH` | `true` | 判断已有文件时是否使用数据库 SHA-256 重新校验。 |
| `IH_KEEP_PARTIAL` | `true` | 是否保留 `.part` 文件供下次断点续传。 |

新下载始终计算 SHA-256，并校验远端能够提供的大小或校验值。网络超时、限流、Apple 服务
暂不可用、过期下载地址和数据完整性失败会自动重试。

### 5.6 运行和通知开关

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `IH_LOG_LEVEL` | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR` 或 `CRITICAL`。 |
| `IH_LOG_FORMAT` | `text` | `text` 或 `json`。 |
| `IH_NOTIFY_STARTUP` | `false` | 是否发送容器启动通知。 |
| `IH_NOTIFY_SUCCESS` | `true` | 是否发送有变化的成功同步通知。 |
| `IH_NOTIFY_NO_CHANGES` | `false` | 无变化的成功同步是否也通知。 |
| `IH_NOTIFY_FAILURE` | `true` | 是否发送失败和部分失败通知。 |
| `IH_NOTIFY_AUTH_REQUIRED` | `true` | 需要重新认证时是否通知。 |

通知开关只决定发送哪些事件。要真正发送通知，还需要在 `config.yaml` 中配置至少一个通知
通道，见“7. 通知配置”。

## 6. 参数取值说明

### 6.1 布尔值、容量和时长

布尔值不区分大小写：

- 真：`true`、`yes`、`on`、`1`
- 假：`false`、`no`、`off`、`0`

容量可以写为字节数或人类可读格式：

```text
1048576
1MB
64 MiB
10GB
```

支持十进制 `KB`、`MB`、`GB`、`TB`，以及二进制 `KiB`、`MiB`、`GiB`、`TiB`。

时长可以写为秒数、单单位简写或 ISO 8601：

```text
1800
30m
6h
30d
P30D
PT6H
```

简写单位包括 `s`、`m`、`h`、`d`、`w`。

### 6.2 日期和 Cron

日期使用 ISO 8601，建议明确写出时区：

```text
2026-07-18T00:00:00+08:00
2026-07-18T23:59:59+08:00
```

Cron 必须是五段格式：

```text
分钟 小时 日 月 星期
```

例如：

```text
0 3 * * *
```

表示按 `IH_TIMEZONE` 每天凌晨 03:00 执行。

### 6.3 媒体选择

`IH_PHOTO_VERSION`：

| 值 | 行为 |
| --- | --- |
| `original` | 选择原片或原始视频资源。 |
| `adjusted` | 选择在 Apple Photos 中编辑后的版本。 |
| `both` | 原片和编辑版都选择。 |

`IH_RAW_MODE`：

| 值 | 行为 |
| --- | --- |
| `raw_only` | 只选择 RAW 原始资源。 |
| `jpeg_only` | 只选择 JPEG 替代资源。 |
| `both` | RAW 与 JPEG 都选择。 |
| `prefer_raw` | 有 RAW 时优先选择 RAW。 |
| `prefer_jpeg` | 有 JPEG 时优先选择 JPEG。 |

Apple 返回的某些资源没有独立 RAW 标记；在这种情况下，`prefer_raw` 和 `prefer_jpeg` 会保留
适配器能够识别的可用原始资源。

### 6.4 路径和文件名模板

可用变量：

| 变量 | 含义 |
| --- | --- |
| `{account}` | 账号 ID。 |
| `{library}` | 图库 ID，当前为 `root`。 |
| `{album}` | 预留相册名，当前为空字符串。 |
| `{asset_id}` | 完整远端 Asset ID。 |
| `{asset_id_short}` | 清理后的 Asset ID 最后 8 位。 |
| `{created}` | 创建时间，可用日期格式，例如 `{created:%Y-%m}`。 |
| `{added}` | 加入图库时间；缺失时回退到创建时间。 |
| `{original_name}` | 当前资源的原始文件名。 |
| `{stem}` | 不含扩展名的原始文件名。 |
| `{extension}` | 带点的扩展名，例如 `.HEIC`。 |
| `{media_type}` | `photo` 或 `video`。 |

`folder_structure` 必须是下载目标内的相对路径，不能以 `/` 开头，也不能包含 `..` 路径段。
`filename` 不能为空，不能包含 `/` 或 `\`。

程序会清理控制字符、Windows 非法字符和保留文件名，并限制单个路径段长度。Live Photo、
RAW 等伴随资源会保留自己的实际扩展名。

文件重名策略：

| 值 | 行为 |
| --- | --- |
| `suffix_asset_id` | 仅在冲突时追加短 Asset ID。 |
| `always_asset_id` | 所有文件名都追加短 Asset ID。 |
| `timestamp` | 冲突时追加创建时间 `YYYYMMDD_HHMMSS`。 |
| `error` | 发现目标冲突时终止计划。 |

## 7. 通知配置

通知通道只能在 `config.yaml` 中配置。Apple 密码不使用这些文件。

### 7.1 创建通知密钥目录

假设宿主机配置目录是 `./data/config`：

```bash
mkdir -p ./data/config/notification-keys
chmod 700 ./data/config/notification-keys
```

每个令牌文件只写一行令牌，并确保 `IH_PUID:IH_PGID` 可以读取：

```bash
chmod 600 ./data/config/notification-keys/*
```

### 7.2 Bark

宿主机创建：

```text
./data/config/notification-keys/bark-device-key
```

然后在 `config.yaml` 的 `notifications.channels` 中添加：

```yaml
- type: bark
  enabled: true
  server: https://api.day.app
  device_key_file: /config/notification-keys/bark-device-key
  timeout: 10
```

`server` 可省略，默认使用 `https://api.day.app`。

### 7.3 Server酱

```yaml
- type: serverchan
  enabled: true
  send_key_file: /config/notification-keys/serverchan-send-key
  timeout: 10
```

对应的宿主机文件：

```text
./data/config/notification-keys/serverchan-send-key
```

### 7.4 Telegram

```yaml
- type: telegram
  enabled: true
  token_file: /config/notification-keys/telegram-token
  chat_id: "123456789"
  timeout: 10
```

对应的宿主机文件：

```text
./data/config/notification-keys/telegram-token
```

`chat_id` 建议始终加引号，避免 YAML 把它当成数字处理。

### 7.5 Webhook

不签名：

```yaml
- type: webhook
  enabled: true
  url: https://example.com/icloudharbor/events
  timeout: 10
```

需要 HMAC-SHA256 签名时：

```yaml
- type: webhook
  enabled: true
  url: https://example.com/icloudharbor/events
  secret_file: /config/notification-keys/webhook-secret
  timeout: 10
```

十六进制签名放在 `X-iCloudHarbor-Signature` 请求头。Webhook 不自动跟随重定向。

所有通道的 `timeout` 范围是 1–60 秒。`enabled: false` 的通道可以保留不完整参数，程序不会
加载它的凭据。

## 8. 高级 YAML 配置

普通部署只用 `.env` 即可。以下情况需要直接修改 `config.yaml`：

- 配置 Bark、Server酱、Telegram 或 Webhook；
- 修改数据库和临时目录；
- 审计完整生效配置；
- 清除首次启动时已经写入 YAML 的筛选值。

### 8.1 安全修改流程

先停止容器并备份：

```bash
docker compose stop
cp ./data/config/config.yaml ./data/config/config.yaml.backup
```

编辑后，在不启动守护进程的情况下校验：

```bash
docker compose run --rm icloudharbor icloudharbor config validate
```

校验通过后重新启动并执行完整检查：

```bash
docker compose up -d
docker exec icloudharbor icloudharbor doctor
```

配置模型使用严格模式。拼错或未知字段会直接报错，不会被静默忽略。

### 8.2 完整示例

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

### 8.3 调度的三种 YAML 写法

直接写五段 Cron：

```yaml
schedule: "0 3 * * *"
```

显式 Cron 对象：

```yaml
schedule:
  cron: "0 3 * * *"
```

固定间隔：

```yaml
schedule:
  interval: 6h
```

对象形式必须且只能设置 `interval`、`cron` 中的一个。

### 8.4 仅 YAML 可设置的字段

| YAML 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `runtime.database` | `/config/database/icloudharbor.db` | SQLite 数据库路径。 |
| `runtime.temp_path` | `/config/tmp` | 内部临时目录。 |
| `accounts[0].enabled` | `true` | 当前版本必须且只能启用一个账号。 |
| `accounts[0].libraries` | `[root]` | 当前版本只能是个人图库。 |
| `filters.albums` | `[]` | 尚未实现，必须保持为空。 |
| `filters.exclude_albums` | `[]` | 尚未实现，必须保持为空。 |
| `notifications.channels` | `[]` | 通知通道列表。 |
| `security.redact_apple_id` | `true` | CLI 中是否遮盖 Apple Account 邮箱。 |
| `security.session_encryption` | `false` | 尚未实现，设置为 `true` 会拒绝启动。 |
| `security.allow_remote_delete` | `false` | 只能为 `false`。 |

修改数据库路径前应停止容器并迁移现有数据库。数据库必须位于持久化目录；数据库和临时目录
都必须是容器内可写路径。

## 9. 命令参考

容器内程序名是 `icloudharbor`。在 Compose 部署中，交互式命令使用：

```bash
docker exec -it icloudharbor icloudharbor <命令>
```

只读查询通常不需要 `-it`：

```bash
docker exec icloudharbor icloudharbor status
```

查看总帮助或子命令帮助：

```bash
docker exec icloudharbor icloudharbor --help
docker exec icloudharbor icloudharbor sync --help
```

### 9.1 初始化和认证

| 命令 | 用途 |
| --- | --- |
| `setup [--account ID]` | 检查环境、读取密码、完成 2FA、保存续期凭据并探测图库。 |
| `session renew [--account ID]` | 用已保存密码续期；Apple 要求时只询问验证码。 |
| `session status [--account ID]` | 显示当前认证状态。 |
| `session clear [--account ID]` | 清除 Session、Cookie 和认证状态，不删除保存的密码。 |
| `credentials status [--account ID]` | 显示本地密码是 `SAVED` 还是 `MISSING`。 |
| `credentials clear [--account ID]` | 删除本地保存的密码。 |

如果 Apple 密码已修改、凭据不存在或无法解密，请重新运行 `setup`，不要反复执行
`session renew`。

### 9.2 配置、账号和远端信息

| 命令 | 用途 |
| --- | --- |
| `config bootstrap` | 配置不存在时从环境生成；已有配置只校验，不覆盖。 |
| `config validate` | 严格校验 YAML 和环境变量覆盖。 |
| `config show` | 显示当前生效配置。 |
| `accounts list` | 显示账号、认证状态和下载目标。 |
| `libraries list [--account ID]` | 认证后列出可见图库。 |
| `albums list [--account ID] [--library root]` | 列出相册；当前不能用于同步筛选。 |

### 9.3 同步

| 命令 | 用途 |
| --- | --- |
| `sync plan [--account ID] [--full-scan]` | 生成只读计划，不下载、不提交游标。 |
| `sync run [--account ID] [--dry-run] [--full-scan]` | 执行同步；`--dry-run` 等同只读计划。 |
| `sync status [--limit 10]` | 查看最近 1–100 次运行记录。 |

常用示例：

```bash
# 强制全量扫描，但不下载
docker exec -it icloudharbor icloudharbor sync plan --full-scan

# 强制全量扫描并下载
docker exec -it icloudharbor icloudharbor sync run --full-scan
```

### 9.4 数据库、健康和守护进程

| 命令 | 用途 |
| --- | --- |
| `database check` | 执行 SQLite 完整性检查。 |
| `database backup [--output PATH]` | 使用 SQLite 在线备份 API 创建一致性备份。 |
| `doctor` | 检查数据库、目录、挂载标记、权限、空间和认证状态。 |
| `status` | 显示健康状态和最近一次同步。 |
| `healthcheck [--liveness\|--readiness]` | 执行容器存活或完整就绪检查。 |
| `daemon` | 启动前台调度器，也是镜像默认命令。 |

所有命令都支持全局配置路径：

```text
icloudharbor --config /path/to/config.yaml <命令>
icloudharbor --version
```

## 10. 故障排查

### 10.1 容器首次启动后退出

查看日志：

```bash
docker compose logs --tail=100 icloudharbor
```

如果提示首次启动需要 `IH_APPLE_ID`，检查：

- 是否已经把 `.env.example` 复制为 `.env`；
- `IH_APPLE_ID` 是否仍是示例值或空值；
- 执行 `docker compose` 时是否位于项目目录。

### 10.2 `marker_missing`

程序没有在实际下载目标中找到挂载标记。

默认配置应执行：

```bash
mkdir -p ./data/photos/personal
touch ./data/photos/personal/.icloudharbor-mounted
```

如果修改了 `IH_PHOTOS_PATH` 或 `IH_DESTINATION`，请根据“3. 路径、挂载和权限”重新确认宿主机
对应目录。不要通过关闭保护来绕过这个错误。

### 10.3 `not_writable`

确认 `IH_PUID`、`IH_PGID` 是数字，并且对应用户能够写入：

- `IH_CONFIG_PATH`
- `IH_PHOTOS_PATH`
- 实际下载目标目录

群晖上应使用 `id <用户名>` 查看真实 UID/GID，不要直接照抄示例值。

### 10.4 `AUTH_REQUIRED`

Session 过期时运行：

```bash
docker exec -it icloudharbor icloudharbor session renew
```

如果仍然失败：

```bash
docker exec icloudharbor icloudharbor session clear
docker exec -it icloudharbor icloudharbor setup
```

`session clear` 不会删除已保存密码。需要同时删除密码时，另行执行
`credentials clear`。

### 10.5 修改 `.env` 后配置没有恢复默认值

空环境变量只表示“不覆盖”，不会清除 `config.yaml` 里已经保存的值。

查看当前生效配置：

```bash
docker exec icloudharbor icloudharbor config show
```

停止容器并备份 `config.yaml`，然后把需要清除的可空字段改成 `null`，或把其他字段改回本手册
列出的默认值。

### 10.6 同步没有自动运行

依次检查：

```bash
docker exec icloudharbor icloudharbor config show
docker exec icloudharbor icloudharbor status
docker compose logs --tail=200 icloudharbor
```

确认：

- `IH_RUN_ON_START` 是否按预期设置；
- Cron 是否是五段格式；
- `IH_TIMEZONE` 是否正确；
- `IH_SCHEDULE` 和 `IH_SYNC_INTERVAL` 是否只设置了一个。

### 10.7 下载部分失败

网络、限流、Apple 服务异常和过期下载地址会自动重试。修复原因后再次执行：

```bash
docker exec -it icloudharbor icloudharbor sync run
```

已经校验完成的文件会跳过；保留的 `.part` 文件会在条件允许时继续下载。只要存在失败资源，
本次同步就不会提交新游标。

### 10.8 完整自检

```bash
docker exec icloudharbor icloudharbor doctor
docker exec icloudharbor icloudharbor database check
docker exec icloudharbor icloudharbor session status
```

Apple 使用私有接口，字段和认证流程可能变化。如果本地检查全部正常，但认证或图库扫描突然
失败，请先查看项目最新版本和已知问题。

## 11. 安全和当前限制

- 只支持一个启用的 Apple Account。
- 只支持个人图库 `root`。
- 暂不支持共享图库和按相册包含或排除。
- 不支持安全密钥和旧式两步认证的交互流程。
- 不执行远端删除、本地清理、镜像同步或双向同步。
- `allow_remote_delete` 永远只能是 `false`。
- Apple Session 文件当前未加密，整个 `/config` 都应视为敏感数据。
- Apple 密码使用 AES-256-GCM 保存，但密钥和密文都在 `/config/credentials`；拥有宿主机
  root 权限的人仍可恢复密码。
- 不要把 `.env`、`config.yaml`、数据库、Session、凭据、验证码、Cookie 或通知令牌提交到
  Git、镜像或公开 Issue。

更新或迁移容器前，至少备份整个 `IH_CONFIG_PATH`。照片目录可以单独备份，但不能代替
`/config` 中的数据库、Session 和凭据。
