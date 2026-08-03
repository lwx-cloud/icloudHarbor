# iCloudHarbor

[![CI](https://github.com/lwx-cloud/icloudHarbor/actions/workflows/ci.yml/badge.svg)](https://github.com/lwx-cloud/icloudHarbor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

iCloudHarbor 是一个面向 Linux 和 NAS 的 iCloud Photos Docker 备份工具。它在容器中定时
读取个人或共享 iCloud 图库，把照片、视频、Live Photo 和 RAW 资源可靠地保存到本地磁盘。

Docker 镜像发布为 `lwxcloud/icloudharbor`，支持 `linux/amd64` 和 `linux/arm64`。

项目没有 Web 界面，不开放业务端口。Docker 参数负责部署和日常配置，认证、检查与手动同步
通过容器内的 `icloudharbor` 命令完成。

> 本文档对应源码版本 `0.5.0`。项目已经完成真实双重认证与下载验证，但 Apple 私有接口可能
> 随时变化；请保留其他可靠备份。

[快速开始](#快速开始) · [群晖部署](#群晖部署示例) · [认证续期](#认证续期与密码) ·
[完整配置](CONFIGURATION.md) · [更新](#更新) · [故障排查](#故障排查)

本文中的 Compose 命令都应在部署目录执行：手动安装时是克隆的仓库目录，一键安装时是向导
最后显示的安装目录。命令使用固定的服务名 `icloudharbor`；即使修改了 `IH_CONTAINER_NAME`，
这些命令也不需要跟着修改。

## 核心能力

- 首次启动从 Docker `IH_*` 参数自动生成 `config.yaml`，无需手工创建。
- 终端以 `*` 显示密码输入，不把密码放入 `.env`、Compose 或命令行参数。
- 保存本地加密续期凭据；重新运行 `setup` 会自动续期 Session。
- 普通用户直接按小时设置同步频率；高级 YAML 仍支持 Cron、增量游标和定期全量扫描。
- 支持个人/共享图库与相册包含、排除，并可用 ID 或名称选择。
- 支持照片、视频、Live Photo、RAW/JPEG、原片、缩略图和编辑版。
- 可保留 HEIC/HEIF 原片并额外生成 JPEG。
- 支持日期、收藏、隐藏、最近 N 项和连续已有项目停止筛选。
- 支持自定义目录结构、文件名和重名策略。
- 可指定下载目录和文件权限。
- 下载后恢复 iCloud 拍摄时间作为文件修改时间，并兼容 Synology Photos 索引触发。
- 流式下载、断点续传、指数退避、大小/SHA-256 校验和原子落盘。
- SQLite 状态库、运行记录、数据库备份和三层并发锁。
- 挂载标记、剩余空间、inode、写权限和数据库完整性保护。
- 可选读取 iCloud“最近删除”，按 Asset ID 和 SHA-256 安全清理对应的本地文件。
- 可选的 Bark、Server酱、Telegram、企业微信和通用 Webhook 通知。

## 使用边界

- 只支持一个启用的 Apple Account；可同时选择该账号可访问的多个图库。
- 暂不支持安全密钥认证和旧式两步认证。
- 只执行 iCloud 到本地的单向备份，永不删除 iCloud 内容。默认保留本地文件；只有显式开启
  `IH_AUTO_DELETE` 时才同步个人图库“最近删除”中的精确匹配项。
- Apple Session 文件当前未加密。
- 项目与 Apple Inc. 无隶属、认可或赞助关系。

## 快速开始

### 一键安装

Linux 或群晖 SSH 已经安装 Docker Engine 和 `docker compose` 插件时，运行：

```bash
curl -fsSL https://raw.githubusercontent.com/lwx-cloud/icloudHarbor/main/deploy/install.sh | sudo bash
```

这是一条命令启动安装向导，不是把 Apple 认证改成无人值守。向导会询问 Apple Account、配置
目录、照片目录、UID/GID、时区和同步频率，然后：

1. 检查 Linux、amd64/arm64、Docker daemon 和 Compose 插件；
2. 写入权限为 `0600` 的 `.env`，但绝不读取或保存 Apple 密码、验证码；
3. 创建持久化目录和 `.icloudharbor-mounted` 挂载标记；
4. 拉取 `lwxcloud/icloudharbor:latest`，启动容器并运行 `icloudharbor status`；
5. 询问是否立即进入 `icloudharbor setup`，在终端中完成密码和双重认证验证码输入。

普通 Linux 默认安装到 `/opt/icloudharbor`，运行数据位于其中的 `data/config`，照片目录默认
`/srv/icloudharbor/photos`。在群晖上检测到对应存储卷时，安装目录优先使用
`/volume1/docker/icloudharbor`，运行数据位于 `/volume1/docker/icloudharbor/data/config`，照片
目录优先使用 `/volume2/photos/iCloud`；所有路径都会在执行前显示并允许修改。默认下载根目录
就是所选照片目录，不会再追加 Apple ID 子目录。

一键安装会让部署目录和容器可写的运行数据目录保持分离：`.env` 与 Compose 文件只允许 root
修改，容器只写 `data/config`。因此向导不会接受把配置目录直接设成安装目录。以后从该目录
手动执行认证、日志等 Compose 命令时需要加 `sudo`；手动克隆部署仍按下文命令执行。

重复运行同一条命令会保留已有 `.env`、`config.yaml`、SQLite、Session、凭据和照片，只更新
受管理的 Compose 文件并拉取最新镜像。安装器不会递归修改已有照片库的属主或群晖 ACL；若
当前 UID/GID 无法写入，`status` 会停止向导并给出具体检查结果。

直接执行远程脚本前应确认仓库来源。希望先审阅脚本时使用：

```bash
curl -fsSLO https://raw.githubusercontent.com/lwx-cloud/icloudHarbor/main/deploy/install.sh
less install.sh
sudo bash install.sh
```

### 手动安装

#### 1. 准备环境

需要：

- 较新的 Docker Engine；
- Docker Compose 插件，可使用 `docker compose`；
- 已启用 iCloud Photos 和双重认证的 Apple Account；
- 两个可持久化目录：一个保存程序状态，一个保存照片。

克隆仓库：

```bash
git clone https://github.com/lwx-cloud/icloudHarbor.git
cd icloudHarbor
cp .env.example .env
chmod 600 .env
```

默认目录对应关系：

| 用途 | 宿主机默认路径 | 容器路径 | 保护要求 |
| --- | --- | --- | --- |
| 配置、数据库、Session 和凭据 | `./data/config` | `/config` | 高敏感，需完整安全备份 |
| 照片下载目录 | `./data/photos` | `/photos` | 私人内容，需持久化并限制访问 |

创建两个专用目录，并在实际照片目录根部创建挂载标记：

```bash
mkdir -p ./data/config ./data/photos
touch ./data/photos/.icloudharbor-mounted
```

挂载标记是安全开关。没有它时程序会拒绝下载，避免照片卷未挂载后误写容器层。

查看运行用户的数字 UID/GID：

```bash
id -u
id -g
```

编辑 `.env`。示例文件已经逐项写明用途，普通用户通常只需确认下面这些值：

```dotenv
IH_APPLE_ID=your-account@example.com
IH_CONFIG_PATH=./data/config
IH_PHOTOS_PATH=./data/photos
IH_PUID=1000
IH_PGID=1000
IH_TIMEZONE=Asia/Shanghai
IH_REGION=auto
IH_SYNC_INTERVAL=24
IH_RUN_ON_START=true
IH_AUTO_DELETE=false
IH_DOWNLOAD_VIDEOS=true
IH_DOWNLOAD_LIVE_PHOTOS=true
```

`IH_SYNC_INTERVAL` 只能填写 `6`、`12` 或 `24`，数字就是小时，不需要写 Cron。推荐使用
`12` 或 `24`；`6` 小时请求更频繁，可能增加 Apple 限流或风控概率。
所有开关只需填写 `true` 或 `false`。照片默认始终下载；视频和 Live Photo 默认也会下载。
`IH_AUTO_DELETE` 默认关闭。开启后只会删除数据库中 Asset ID 精确匹配且内容未被修改的本地
文件；不会仅凭同名猜测，也不会删除 iCloud 内容。首次开启前先保持 `.env` 中的值为 `false`，
备份 `/config` 和照片目录，再临时预览候选项：

```bash
docker compose exec -e IH_AUTO_DELETE=true icloudharbor icloudharbor plan
```

确认计划后再把 `.env` 改为 `IH_AUTO_DELETE=true` 并重建容器。
`IH_PUID` 和 `IH_PGID` 必须对配置目录和照片目录具有读写权限。只对刚创建的 iCloudHarbor
专用目录调整属主，不要对已有的共享照片库盲目递归执行：

```bash
sudo chown -R 1000:1000 ./data/config ./data/photos
```

#### 2. 拉取并启动

先检查 Compose 配置是否有效。不要省略 `--quiet`；普通 `docker compose config` 会展开
`.env`，可能把 Apple Account 或通知密钥打印到终端：

```bash
docker compose config --quiet
```

拉取镜像并启动：

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose exec icloudharbor icloudharbor --version
docker compose logs --tail=50 icloudharbor
```

如果拉取镜像时提示无权访问，再执行 `docker login` 后重试。

首次启动会生成 `./data/config/config.yaml`。已有配置文件不会被覆盖。配置型 `IH_*` 参数会在
运行时覆盖对应 YAML 字段；`IH_CONFIG_PATH`、`IH_PHOTOS_PATH`、`IH_PUID`、`IH_PGID` 和
`IH_CONTAINER_NAME` 属于 Compose 或容器入口参数，不写入 YAML。

`IH_APPLE_ID` 会直接作为内部账号 ID，并默认作为终端和通知中的账号显示名称；它不会拼进
照片保存路径，默认下载根目录仍是 `/photos`，也就是宿主机的 `IH_PHOTOS_PATH`。只有显式
设置高级参数 `IH_ACCOUNT_NAME` 时才会覆盖显示名称。

需要从当前源码进行本地构建时，使用开发覆盖文件：

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

#### 3. 完成 Apple 认证

```bash
docker compose exec icloudharbor icloudharbor setup
```

`docker compose up -d` 已经脱离终端，不能直接读取密码和验证码。首次登录未完成时，容器
日志会明确显示认证命令。`docker compose exec` 启动独立的交互进程；认证完成后该命令
立即退出，容器后台随即接手首次同步。启用认证通知后，首次未认证启动只发送一条“容器已启动，
等待 Apple 认证”的合并消息；认证状态没有变化时，后续调度不会重复提醒。

程序会：

1. 检查配置、SQLite、照片目录、挂载标记和剩余空间；
2. 以星号遮罩读取 Apple Account 密码；
3. 在需要时显示验证码输入提示；
4. 验证已配置的 iCloud Photos 图库和相册可访问；
5. 保存本地加密续期凭据；
6. 把首次同步交给容器后台，并结束当前认证命令。

验证码必须在出现 `验证码:` 提示后输入。请勿把验证码直接当作 shell 命令输入。

认证命令退出后直接查看下载：

```bash
docker compose logs -f icloudharbor
```

首次同步和每个文件的“正在下载”都由主容器输出，不需要再手动执行 `sync`。
之后默认在容器启动时检查一次，并按 `IH_SYNC_INTERVAL` 的小时数自动同步。

## 群晖部署示例

假设项目与运行状态目录位于 `/volume1/docker/icloudharbor`，照片保存到
`/volume2/photos/iCloud`：

```bash
mkdir -p /volume1/docker/icloudharbor
mkdir -p /volume2/photos/iCloud
touch /volume2/photos/iCloud/.icloudharbor-mounted
```

项目目录中的 `.env` 示例；`IH_APPLE_ID` 必填，其余项按群晖实际环境修改：

```dotenv
IH_APPLE_ID=your-account@example.com
IH_CONFIG_PATH=/volume1/docker/icloudharbor
IH_PHOTOS_PATH=/volume2/photos/iCloud
IH_PUID=1026
IH_PGID=100
IH_TIMEZONE=Asia/Shanghai
IH_SYNC_INTERVAL=24
IH_RUN_ON_START=true

# 可选企业微信通知；启用时前四项必须填写
IH_WECOM_ID=ww0000000000000000
IH_WECOM_SECRET=your-enterprise-application-secret
IH_WECOM_AGENT_ID=1000001
IH_WECOM_TO_USER=@all
# IH_WECOM_PROXY=https://qyapi.weixin.qq.com
# IH_WECOM_CONTENT_SOURCE_URL=https://example.com
# IH_WECOM_NAME=iCloudHarbor
```

`1026:100` 只是示例。请在群晖终端运行 `id <用户名>`，填写实际数字 UID/GID，并确保它能
写入上面两个目录。`IH_PHOTOS_PATH` 会挂载为容器内默认下载目标 `/photos`，因此挂载标记
必须放在这个宿主机目录的根部。

如果这两个目录是刚为 iCloudHarbor 新建的专用目录，可以在确认实际 UID/GID 后设置属主：

```bash
chown -R 1026:100 /volume1/docker/icloudharbor /volume2/photos/iCloud
```

如果使用群晖 ACL，则在 DSM 中授予同一用户读写权限。不要对已有的共享照片目录盲目递归
修改属主。

`.env` 至少包含 Apple Account，启用企业微信时还包含应用 Secret，请设置为仅管理员可读。
Docker 管理员仍能查看容器环境变量；需要把通知密钥改为文件保存时，请使用
[`CONFIGURATION.md`](CONFIGURATION.md) 中的高级 YAML 配置。

## 认证续期与密码

查看认证状态：

```bash
docker compose exec icloudharbor icloudharbor status
```

Session 过期时重新运行同一个设置命令：

```bash
docker compose exec icloudharbor icloudharbor setup
```

已保存本地凭据时，`setup` 会自动进入续期流程，不重新询问密码；Apple 要求双重认证时
只输入验证码。续期成功后会向容器后台提交一次同步任务，下载日志仍在主容器中。

如果 Apple 密码已修改、本地凭据损坏，或希望强制重新输入密码，先运行：

```bash
docker compose exec icloudharbor icloudharbor reset
```

`reset` 会清除 Apple Session、Cookie 和保存的密码，但不删除照片、SQLite 数据库或配置。
完成后再运行 `setup` 即会重新询问密码。启用认证通知时，首次认证和续期成功都会发送恢复消息。

下载过程显示在：

```bash
docker compose logs -f icloudharbor
```

凭据密文和加密密钥都保存在 `/config/credentials`。这可以避免意外明文泄露，但拥有宿主机
root 权限的人仍可恢复密码，因此 `/config` 必须按敏感数据保护。

## 通知

配置并启用通知通道后，正式同步会按开关发送成功、部分完成、失败或认证处理结果；只生成计划
和“已有任务正在运行”不会发送结果通知。程序会读取 Apple 受信任 Session Cookie 的真实到期
时间，并在可配置的提醒窗口内每天最多提醒一次，默认提前 7 天。

企业微信可复用与 icloudpd 相同的 `MEDIA_ID_*` 配置显示下载、启动/认证恢复、警告和认证临期封面。
已完成认证的正常启动会说明当前是立即检查、延迟启动、后台请求还是等待下一次计划。首次未
认证启动不会再先发普通启动消息、随后再发认证消息，而是只发送一条等待认证的合并消息；同一
认证问题作为认证事件发送后会在 SQLite 中持久去重，容器重启和后续调度都不会重复提醒。
`setup` 完成首次认证或自动续期后会发送认证恢复消息，并说明后台同步请求已提交，同时重新允许
未来新的认证问题触发提醒。普通通知正文使用“同步完成”“已是最新”等可读状态，并显示文件数
和易读的数据量。通知没有独立定时器，认证临期只会在同步时检查。

`IH_NOTIFY_AUTH_REQUIRED` 控制等待认证、认证失效、认证临期和认证恢复事件。关闭它但开启
`IH_NOTIFY_STARTUP` 时，首次未认证的合并消息仍会作为普通启动消息发送；两个开关都关闭时
不发送该消息。成功、失败和认证通知默认开启；普通启动通知默认关闭，需要显式设置
`IH_NOTIFY_STARTUP=true`。完整渠道配置见 [`CONFIGURATION.md`](CONFIGURATION.md)。

## 常用运维命令

```bash
# 查看服务、认证、最近同步和调度状态
docker compose exec icloudharbor icloudharbor status

# 查看所有远端图库及其相册
docker compose exec icloudharbor icloudharbor list

# 只读预览下载、修复和本地删除候选
docker compose exec icloudharbor icloudharbor plan

# 向容器后台提交一次同步任务
docker compose exec icloudharbor icloudharbor sync

# 创建 SQLite 在线备份，终端只输出备份路径
docker compose exec icloudharbor icloudharbor backup

# 清除 Session 和保存的密码，不删除照片、数据库或配置
docker compose exec icloudharbor icloudharbor reset

# 容器日志
docker compose logs --tail=200 icloudharbor

# 持续查看当前正在处理的照片
docker compose logs -f icloudharbor
```

`plan` 会访问 Apple 读取当前图库，但不创建同步运行记录、不认领磁盘文件、不通知、不下载、
不删除文件且不提交游标。开启 `IH_AUTO_DELETE` 时，它会逐个列出可验证的本地删除路径；没有本地记录的项目
只显示汇总数，不再逐条刷屏。

`0.3.5` 起，照片、视频、Live Photo、RAW 和转换生成的 JPEG 都会保留 iCloud 拍摄时间作为
文件修改时间。定期全量扫描会自动校正历史文件，无需额外命令。

`INFO` 日志对每个文件只显示一条简洁的“正在下载”消息，并使用 `IH_PHOTOS_PATH` 显示
文件在 Docker 宿主机上的实际路径，例如：

```text
正在下载：/volume2/photos/iCloud/2026/07/29/IMG_0001.JPG
```

下载成功后不重复输出完成消息；只有重试或失败时才会增加简短警告。日志不会输出资源 ID
或签名下载链接。
容器启动日志会明确显示 iCloud“最近删除”同步是否开启；程序始终不会删除 iCloud 内容。默认
不会清理本地照片，只有开启 `IH_AUTO_DELETE` 后才执行已校验的精确本地删除。同步计划中的已
存在文件只显示跳过总数，避免全量扫描时产生海量日志。发生实际清理时，同步结果通知的详情
会列出成功删除的文件名；通知正文最多显示 50 个，更多文件会提示查看容器日志，Webhook 的
`data.deleted_files` 保留本轮完整列表。

所有 Docker 参数、取值、默认值、YAML 高级配置和完整命令说明见
[`CONFIGURATION.md`](CONFIGURATION.md)。

## 更新

先使用内置命令创建一致的 SQLite 在线备份：

```bash
docker compose exec icloudharbor icloudharbor backup
```

整个 `IH_CONFIG_PATH` 还包含 Session、加密密钥和续期凭据；如需完整备份，应先停止容器，再对
该宿主机目录创建快照或副本。不要公开备份内容。

一键安装的用户完成备份后，可重新运行安装命令；安装器会保留持久化数据并更新 Compose 与
镜像：

```bash
curl -fsSL https://raw.githubusercontent.com/lwx-cloud/icloudHarbor/main/deploy/install.sh | sudo bash
```

自定义过安装目录时，把原目录传给安装器：

```bash
curl -fsSL https://raw.githubusercontent.com/lwx-cloud/icloudHarbor/main/deploy/install.sh | \
  sudo env IH_INSTALL_DIR=/实际/目录 bash
```

手动克隆仓库的用户更新部署文件并拉取新镜像：

```bash
git pull --ff-only
docker compose pull
docker compose up -d --force-recreate --remove-orphans
docker compose exec icloudharbor icloudharbor --version
docker compose exec icloudharbor icloudharbor status
```

镜像升级不会修改照片卷，但照片仍是私人数据，应纳入自己的备份和访问控制策略。`/config`
包含 SQLite、Session 和本地续期凭据，必须持久化并纳入安全备份。

## 故障排查

### 拉取后仍显示旧版本

先确认 Compose 实际使用生产镜像，然后显式拉取并重建容器：

```bash
docker compose config --images
docker compose pull
docker compose up -d --force-recreate --remove-orphans
docker compose exec icloudharbor icloudharbor --version
```

`config --images` 应输出 `lwxcloud/icloudharbor:latest`。如果输出
`icloudharbor:local`，说明启动时使用了仅供源码构建的 `docker-compose.build.yml`。

若命令行版本已更新而群晖 Container Manager 页面仍显示旧信息，以容器内版本为准；页面可能
显示旧的创建时间或缓存。若容器内仍是旧版，比较运行容器和本地 `latest` 的镜像 ID：

```bash
docker inspect "$(docker compose ps -q icloudharbor)" --format '{{.Image}}'
docker image inspect lwxcloud/icloudharbor:latest --format '{{.Id}}'
```

两者不一致表示只拉取了镜像但没有替换旧容器。私有仓库还应确认已执行 `docker login`；
如果 pull 得到的仍是旧摘要，再检查群晖配置的 registry mirror 或代理缓存。

### 容器首次启动后退出

检查 `.env` 中是否设置了非空 `IH_APPLE_ID`：

```bash
docker compose logs --tail=100 icloudharbor
```

### `marker_missing`

在实际下载目标中创建标记文件。默认目标就是宿主机的 `IH_PHOTOS_PATH`：

```bash
touch ./data/photos/.icloudharbor-mounted
```

上面是默认路径；修改过 `IH_PHOTOS_PATH` 时，应替换为 `.env` 中的真实宿主机路径。不要通过
修改配置绕过挂载保护。

### `not_writable`

核对 `IH_PUID`、`IH_PGID` 与宿主机目录权限。容器正常运行时业务进程不是 root。

### `AUTH_REQUIRED`

运行：

```bash
docker compose exec icloudharbor icloudharbor setup
```

如果密码已修改或本地凭据无法使用，先运行 `reset`，再运行 `setup`。

### 其他 Apple 认证状态

- `TERMS_REQUIRED`：登录 iCloud 网页接受新的 Apple 服务条款，然后重新运行 `setup`。
- `WEB_ACCESS_DISABLED`：先为 Apple Account 开启通过网页访问 iCloud 数据。
- `ADP_APPROVAL_REQUIRED`：在受信任 Apple 设备上批准高级数据保护访问，再重新认证。

### 下载部分失败

网络、限流和过期下载地址会自动重试。修复原因后再次运行：

```bash
docker compose exec icloudharbor icloudharbor sync
```

已经校验完成的资源会跳过，可续传的 `.part` 文件会继续使用。

### 容器异常停止后提示数据库锁被占用

不要手工删除 SQLite 锁。新同步会先取得持久化目录中的独占文件锁；确认没有仍在运行的同步
进程后，程序会自动恢复同一账号和图库的残留数据库租约。若仍看到
`SKIPPED_ALREADY_RUNNING`，说明确实有另一个认证或同步任务正在运行。

## 安全说明

- 不要提交 `.env`、`/config`、数据库、Session、凭据、通知令牌或真实 Apple ID。
- 不要通过环境变量、Compose `command` 或 shell 历史传递 Apple 密码和验证码。
- `.env` 应限制为仅管理员可读；Docker 管理员仍可查看其中的环境变量。
- 只从可信源码构建镜像，并限制配置目录的宿主机访问权限。
- 开启 `IH_AUTO_DELETE` 前备份 `/config` 与照片目录，并先用 `plan` 核对候选项；人工修改、
  符号链接、同路径归属冲突和未被数据库跟踪的文件会被安全拒绝。
- Webhook 可使用 HMAC-SHA256 签名；通知令牌应放在权限受限的文件中。
- 发现安全问题时，请使用
  [GitHub Security Advisory](https://github.com/lwx-cloud/icloudHarbor/security/advisories/new)
  私下报告，不要在公开 Issue 中附带账号、Cookie、日志原文或照片信息。

## License

[MIT](LICENSE)
