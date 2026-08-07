# iCloudHarbor

[![CI](https://github.com/lwx-cloud/icloudHarbor/actions/workflows/ci.yml/badge.svg)](https://github.com/lwx-cloud/icloudHarbor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

iCloudHarbor 是面向 Linux 和 NAS 的 iCloud Photos Docker 备份工具。它定时把照片、视频、
Live Photo 和 RAW 资源从 iCloud 下载到本地，支持断点续传、文件校验、拍摄时间恢复以及
安全的本地清理。

本项目参考了 [docker-icloudpd](https://github.com/boredazfcuk/docker-icloudpd) 的容器化备份
思路，但为独立实现。

> 当前源码版本：`0.6.0`。项目不提供 Web 页面，也不会删除 iCloud 中的内容。

[快速开始](#快速开始) · [通知](#通知) · [常用命令](#常用命令) ·
[完整参数](CONFIGURATION.md) · [更新](#更新)

## 主要功能

- 支持个人图库、共享图库和相册筛选；
- 支持照片、视频、Live Photo、RAW/JPEG、原片与编辑版；
- 使用 SQLite 按 Asset ID 保存状态；容器重启后已下载文件不会重复下载；
- 下载时同步计算 SHA-256，资源身份相同才续传 `.part`，校验后原子写入正式文件；
- 同名 Asset 和同一 Asset 的多尺寸资源使用稳定冲突路径，不覆盖也不永久跳过；
- 可选在连续遇到已有项目后立即停止 iCloud 分页，加快日常扫描；
- Apple 临时下载地址返回 410 时自动重新获取最新地址；
- 恢复 iCloud 拍摄时间，兼容 Synology Photos 索引；
- 支持 Bark、Server酱、Telegram、企业微信和 Webhook；
- 可选读取 iCloud“最近删除”，只清理精确匹配且未被修改的本地文件；
- 支持 amd64 和 arm64 Docker 镜像。

## 快速开始

### 1. 生成部署文件

进入准备部署 iCloudHarbor 的目录：

```bash
mkdir -p /volume1/docker/icloudharbor
cd /volume1/docker/icloudharbor
curl -fsSL https://raw.githubusercontent.com/lwx-cloud/icloudHarbor/main/deploy/install.sh | sudo bash
```

脚本只生成三个项目：

```text
config/
.env
docker-compose.yaml
```

它不会询问参数、创建照片目录、启动容器或执行认证，也不会生成 `.env.example`。即使用 root
执行，部署目录和 `config/` 也允许本机普通用户进入和写入，生成的 `.env` 与
`docker-compose.yaml` 可以直接读写、重命名或删除。

### 2. 编辑 `.env`

至少确认这些参数：

```dotenv
IH_APPLE_ID=your-account@example.com
IH_CONFIG_PATH=/volume1/docker/icloudharbor/config
IH_PHOTOS_PATH=/volume2/photos/iCloud
IH_PUID=1026
IH_PGID=100
IH_TIMEZONE=Asia/Shanghai
IH_REGION=global
IH_SYNC_INTERVAL=12
IH_RUN_ON_START=true
IH_PHOTO_SIZE=original
IH_NOTIFY=false
```

群晖运行 `id <管理员用户名>` 查看实际 UID/GID。不要照抄示例中的 `1026:100`，
也不要直接使用其他设备的 `99:100` 或 `1000:1000`。UID 必须对应需要管理这些文件的
宿主机用户。

`IH_SYNC_INTERVAL` 只填写 `6`、`12` 或 `24`，数字代表小时，不要填写 `6h`。

`IH_REGION` 必须明确填写：普通全球账号使用 `global`；iCloud 数据由云上贵州运营的中国大陆
账号使用 `china`。`auto` 已不再支持，避免首次认证时选择错误端点。

### 3. 准备照片目录

```bash
mkdir -p /volume2/photos/iCloud
touch /volume2/photos/iCloud/.icloudharbor-mounted
```

`.icloudharbor-mounted` 是防止照片卷未挂载时误写容器磁盘的安全标记，必须位于
`IH_PHOTOS_PATH` 根目录。

### 4. 启动并认证

```bash
docker compose pull
docker compose up -d
docker compose exec icloudharbor icloudharbor setup
docker compose logs -f icloudharbor
```

`setup` 会在终端用星号遮罩密码，并在需要时询问双重认证验证码。密码不会写入 `.env`。
认证完成后，同步交给主容器后台执行，下载进度统一显示在容器日志中。

### 手动安装

需要从源码或自定义 Compose 时：

```bash
git clone https://github.com/lwx-cloud/icloudHarbor.git
cd icloudHarbor
cp .env.example .env
mkdir -p ./data/config ./data/photos
touch ./data/photos/.icloudharbor-mounted
docker compose pull
docker compose up -d
docker compose exec icloudharbor icloudharbor setup
```

启动前请修改 `.env` 中的账号、路径和 UID/GID。

容器每次启动都会把 `.env` 中非空的 `IH_*` 配置同步到持久化的 `config/config.yaml`；修改后
使用 `docker compose up -d --force-recreate` 重建容器即可。通知 Secret 不会写入 YAML。

## 通知

普通用户只需要记住两个参数：

```dotenv
IH_NOTIFY=true
IH_NOTIFY_TYPE=wecom
```

`IH_NOTIFY=false` 会关闭所有通知；设为 `true` 后，从 `bark`、`serverchan`、
`telegram`、`wecom`、`webhook` 中选择一个渠道。开启后默认发送：

- 容器启动；
- 同步成功，包括没有新文件；
- 同步失败、空间不足和 Apple 限流；
- 等待认证、认证恢复和认证临期。

企业微信示例：

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

其他渠道所需参数：

| 渠道 | `IH_NOTIFY_TYPE` | 必填参数 |
| --- | --- | --- |
| Bark | `bark` | `IH_BARK_KEY` |
| Server酱 | `serverchan` | `IH_SERVERCHAN_KEY` |
| Telegram | `telegram` | `IH_TELEGRAM_TOKEN`、`IH_TELEGRAM_CHAT` |
| 企业微信 | `wecom` | `IH_WECOM_CORP_ID`、`IH_WECOM_CORP_SECRET`、`IH_WECOM_AGENT_ID`、`IH_WECOM_TO_USER` |
| Webhook | `webhook` | `IH_WEBHOOK_URL` |

完整示例、多渠道和按事件开关见 [CONFIGURATION.md](CONFIGURATION.md#通知配置)。

## 本地清理

`IH_AUTO_DELETE` 默认是 `false`。开启后，程序读取个人图库的“最近删除”，只删除满足以下
条件的本地文件：

- Asset ID 与数据库记录完全一致；
- 路径仍在受管照片目录内；
- 文件不是符号链接；
- 大小和 SHA-256 与下载完成时一致。

首次开启前先备份 `/config` 和照片目录，并预览计划：

```bash
docker compose exec -e IH_AUTO_DELETE=true icloudharbor icloudharbor plan
```

确认后再把 `.env` 改为 `IH_AUTO_DELETE=true` 并重建容器。iCloudHarbor 永远不会调用
远端删除接口。

## 常用命令

```bash
# 状态
docker compose exec icloudharbor icloudharbor status

# 图库与相册
docker compose exec icloudharbor icloudharbor list

# 只读计划
docker compose exec icloudharbor icloudharbor plan

# 请求后台立即同步
docker compose exec icloudharbor icloudharbor sync

# 重新认证或续期
docker compose exec icloudharbor icloudharbor setup

# 备份数据库
docker compose exec icloudharbor icloudharbor backup

# 清除 Session 和保存的密码，不删除照片
docker compose exec icloudharbor icloudharbor reset

# 查看日志
docker compose logs -f icloudharbor
```

## 更新

```bash
cd /volume1/docker/icloudharbor
docker compose pull
docker compose up -d --force-recreate --remove-orphans
docker compose exec icloudharbor icloudharbor --version
```

一键部署脚本只用于首次生成文件，会覆盖 `.env` 和 `docker-compose.yaml`，不要把它当作
更新命令。Docker Hub 镜像只有在 GitHub 的 `v*` 版本标签触发发布工作流后才会更新。

从 0.5.x 升级到 0.6.0 不需要重建数据库。为了补回旧版本可能跳过的极少数同名 Asset，升级后
建议临时删除 `IH_UNTIL_FOUND`，完整同步一次，再恢复该参数。0.6.0 的断点文件绑定远端资源
身份；升级时遗留的旧格式 `.part` 不会续传，以免把旧资源片段接到新文件。

## 故障排查

### 管理员打不开或删不掉目录

一键脚本会把部署目录和 `config/` 设为 `0777`，把 `.env`、`docker-compose.yaml` 设为
`0666`，因此普通用户可以打开、修改、重命名或删除这些项目。容器启动后创建的应用子目录会按
`.env` 中的 `IH_PUID`、`IH_PGID` 管理；如果这些子目录打不开，请确认它们与
`id <管理员用户名>` 一致。程序不会递归接管已有共享照片库。

### `marker_missing`

在真实 `IH_PHOTOS_PATH` 根目录创建：

```bash
touch /实际照片目录/.icloudharbor-mounted
```

### `AUTH_REQUIRED`

```bash
docker compose exec icloudharbor icloudharbor setup
```

### 拉取镜像后版本没变

`docker compose pull` 只下载镜像，不替换已有容器。继续执行：

```bash
docker compose up -d --force-recreate --remove-orphans
```

若 `docker compose config --images` 显示 `icloudharbor:local`，说明使用了
`docker-compose.build.yml`，不是 Docker Hub 镜像。

### 下载部分失败

程序只在全部资源成功后提交同步游标。网络、限流或 Apple 服务恢复后会自动重试，不需要删除
数据库或正式文件。

## 安全说明

- `/config` 包含 Apple Session、加密凭据、数据库和通知密钥，必须限制访问并备份；
- Apple 密码只在认证终端读取，不要写入 `.env`、Compose 或命令参数；
- 通知密钥从 Docker 环境写入 `/config/notification-keys`，文件权限为 `0600`；
- 不要对已有共享照片库盲目递归 `chown`；
- 自动化测试不会连接真实 Apple 服务。

## License

[MIT](LICENSE)
