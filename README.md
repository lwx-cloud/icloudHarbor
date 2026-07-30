# iCloudHarbor

[![CI](https://github.com/lwx-cloud/icloudHarbor/actions/workflows/ci.yml/badge.svg)](https://github.com/lwx-cloud/icloudHarbor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

iCloudHarbor 是一个面向 Linux 和 NAS 的 iCloud Photos Docker 备份工具。它在容器中定时
读取个人或共享 iCloud 图库，把照片、视频、Live Photo 和 RAW 资源可靠地保存到本地磁盘。

Docker 镜像发布为 `lwxcloud/icloudharbor`，支持 `linux/amd64` 和 `linux/arm64`。

项目没有 Web 界面，不开放业务端口。Docker 参数负责部署和日常配置，认证、检查与手动同步
通过容器内的 `icloudharbor` 命令完成。

> 当前版本为 `0.3.2`。已经完成真实双重认证与下载验证，但 Apple 私有接口可能随时变化；
> 请保留其他可靠备份。

## 功能

- 首次启动从 Docker `IH_*` 参数自动生成 `config.yaml`，无需手工创建。
- 终端以 `*` 显示密码输入，不把密码放入 `.env`、Compose 或命令行参数。
- 保存本地加密续期凭据；Session 过期后可运行 `session renew`。
- 支持 Cron、固定间隔、启动时同步、增量游标和定期全量扫描。
- 支持个人/共享图库与相册包含、排除，并可用 ID 或名称选择。
- 支持照片、视频、Live Photo、RAW/JPEG、原片、缩略图和编辑版。
- 可保留 HEIC/HEIF 原片并额外生成 JPEG。
- 支持日期、收藏、隐藏、最近 N 项和连续已有项目停止筛选。
- 支持自定义目录结构、文件名和重名策略。
- 可指定目录/文件权限，并可 touch 新媒体触发 Synology Photos 索引。
- 并发流式下载、断点续传、指数退避、大小/SHA-256 校验和原子落盘。
- SQLite 状态库、运行记录、数据库备份和三层并发锁。
- 挂载标记、剩余空间、inode、写权限和数据库完整性保护。
- 可选的 Bark、Server酱、Telegram、企业微信和通用 Webhook 通知。
- 支持 `linux/amd64` 和 `linux/arm64`。

## 当前限制

- 只支持一个启用的 Apple Account；可同时选择该账号可访问的多个图库。
- 暂不支持安全密钥认证和旧式两步认证。
- 不执行远端删除、本地清理或双向同步。
- Apple Session 文件当前未加密。
- 项目与 Apple Inc. 无隶属、认可或赞助关系。

## 快速部署

### 1. 准备环境

需要：

- 较新的 Docker Engine；
- Docker Compose v2 插件，可使用 `docker compose`；
- 已启用 iCloud Photos 和双重认证的 Apple Account；
- 两个可持久化目录：一个保存程序状态，一个保存照片。

克隆仓库：

```bash
git clone git@github.com:lwx-cloud/icloudHarbor.git
cd icloudHarbor
cp .env.example .env
```

创建默认目录和挂载标记：

```bash
mkdir -p ./data/config ./data/photos
touch ./data/photos/.icloudharbor-mounted
```

查看运行用户的数字 UID/GID：

```bash
id -u
id -g
```

编辑 `.env`。首次启动唯一必填项是：

```dotenv
IH_APPLE_ID=your-account@example.com
```

其他参数不要整份复制，请从
[`CONFIGURATION.md`](CONFIGURATION.md) 的完整参数表中按需添加。常见宿主机参数示例：

```dotenv
IH_PUID=1000
IH_PGID=1000
IH_TIMEZONE=Asia/Shanghai
```

`IH_PUID` 和 `IH_PGID` 必须对配置目录和照片目录具有读写权限。必要时在宿主机调整属主：

```bash
sudo chown -R 1000:1000 ./data/config ./data/photos
```

### 2. 拉取并启动

先检查 Compose 最终配置：

```bash
docker compose config
```

如果 Docker Hub 仓库当前为私有，先登录一次：

```bash
docker login
```

拉取镜像并启动：

```bash
docker compose pull
docker compose up -d
docker compose ps
```

首次启动会生成 `./data/config/config.yaml`。已有配置文件不会被覆盖；非空 `IH_*`
环境变量会在运行时覆盖对应 YAML 值。

需要从当前源码进行本地构建时，使用开发覆盖文件：

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

### 3. 完成 Apple 认证

```bash
docker exec -it icloudharbor icloudharbor setup
```

程序会：

1. 检查配置、SQLite、照片目录、挂载标记和剩余空间；
2. 以星号遮罩读取 Apple Account 密码；
3. 在需要时显示验证码输入提示；
4. 保存本地加密续期凭据；
5. 验证已配置的 iCloud Photos 图库和相册可访问；
6. 验证码通过后立即执行首次正式同步。

验证码必须在出现 `验证码:` 提示后输入。请勿把验证码直接当作 shell 命令输入。

`setup` 会持续运行到首次同步结束，不需要再执行 `sync plan` 或 `sync run`。之后容器会按照
`config.yaml` 中的调度设置自动同步；计划和手动同步命令只用于高级运维。

## 群晖示例

假设项目代码位于 `/volume1/docker/icloudharbor`，建议把运行状态放在单独目录，照片保存到
`/volume2/photos/iCloud/personal`：

```bash
mkdir -p /volume1/docker/icloudharbor-data
mkdir -p /volume2/photos/iCloud/personal
touch /volume2/photos/iCloud/personal/.icloudharbor-mounted
```

项目目录中的 `.env` 示例；第一项必填，其余项按群晖实际路径和用户添加：

```dotenv
IH_CONFIG_PATH=/volume1/docker/icloudharbor-data
IH_PHOTOS_PATH=/volume2/photos/iCloud
IH_PUID=1026
IH_PGID=100
IH_TIMEZONE=Asia/Shanghai
IH_APPLE_ID=your-account@example.com

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
写入上面两个目录。容器内默认下载目标是 `/photos`，对应宿主机 `IH_PHOTOS_PATH`。

## Session 与密码

查看 Session 状态：

```bash
docker exec icloudharbor icloudharbor session status
```

Session 过期时：

```bash
docker exec -it icloudharbor icloudharbor session renew
```

启用通知通道后，程序会读取 Apple 受信任 Session Cookie 的真实到期时间，默认从到期前
7 天开始每天最多提醒一次。企业微信可使用与 icloudpd 相同的 `MEDIA_ID_*` 配置显示
下载、启动、警告和认证临期封面。每次正式同步结束都会立即发送一次同步结果（包括无变化），
前提是通知通道已启用；这不是额外的通知定时任务。

该命令读取 `setup` 保存的本地凭据；Apple 要求双重认证时，只需再输入验证码。如果 Apple
密码已经修改、凭据不存在或无法解密，请重新运行：

```bash
docker exec -it icloudharbor icloudharbor setup
```

清除 Session 不会删除保存的密码：

```bash
docker exec icloudharbor icloudharbor session clear
```

单独删除保存的密码：

```bash
docker exec icloudharbor icloudharbor credentials clear
```

凭据密文和加密密钥都保存在 `/config/credentials`。这可以避免意外明文泄露，但拥有宿主机
root 权限的人仍可恢复密码，因此 `/config` 必须按敏感数据保护。

## 常用运维命令

```bash
# 配置校验与生效值
docker exec icloudharbor icloudharbor config validate
docker exec icloudharbor icloudharbor config show

# 完整就绪检查
docker exec icloudharbor icloudharbor doctor

# 强制全量扫描的只读计划
docker exec icloudharbor icloudharbor sync plan --full-scan

# 强制全量扫描并下载
docker exec icloudharbor icloudharbor sync run --full-scan

# SQLite 完整性检查与备份
docker exec icloudharbor icloudharbor database check
docker exec icloudharbor icloudharbor database backup

# 容器日志
docker compose logs --tail=200 icloudharbor

# 持续查看当前正在处理的照片
docker logs -f icloudharbor
```

`INFO` 日志对每个文件只显示一条简洁的“正在下载”消息，并使用 `IH_PHOTOS_PATH` 显示
文件在 Docker 宿主机上的实际路径，例如：

```text
正在下载：/volume2/photos/iCloud/personal/2026/07/29/IMG_0001.JPG
```

下载成功后不重复输出完成消息；只有重试或失败时才会增加简短警告。日志不会输出资源 ID
或签名下载链接。
容器启动日志会明确显示当前是单向备份安全模式：程序不会删除 iCloud 或本地照片。同步
计划中的已存在文件只显示跳过总数，避免全量扫描时产生海量日志。

所有 Docker 参数、取值、默认值、YAML 高级配置和完整命令说明见
[`CONFIGURATION.md`](CONFIGURATION.md)。

## 更新

建议先备份整个配置目录，然后更新部署文件并拉取新镜像：

```bash
git pull --ff-only
docker compose pull
docker compose up -d --remove-orphans
docker exec icloudharbor icloudharbor doctor
```

照片目录不需要随镜像备份，但 `/config` 中包含 SQLite、Session 和本地续期凭据，必须持久化
并纳入安全备份。

## 故障排查

### 容器首次启动后退出

检查 `.env` 中是否设置了非空 `IH_APPLE_ID`：

```bash
docker compose logs --tail=100 icloudharbor
```

### `marker_missing`

在实际下载目标中创建标记文件。默认目标为宿主机照片卷下的 `personal`：

```bash
touch ./data/photos/.icloudharbor-mounted
```

不要通过修改配置绕过挂载保护。

### `not_writable`

核对 `IH_PUID`、`IH_PGID` 与宿主机目录权限。容器正常运行时业务进程不是 root。

### `AUTH_REQUIRED`

运行：

```bash
docker exec -it icloudharbor icloudharbor session renew
```

如果仍失败，清除旧 Session 后重新设置：

```bash
docker exec icloudharbor icloudharbor session clear
docker exec -it icloudharbor icloudharbor setup
```

### 下载部分失败

网络、限流和过期下载地址会自动重试。修复原因后再次运行 `sync run`；已经校验完成的资源会
跳过，可续传的 `.part` 文件会继续使用。

### 容器异常停止后提示数据库锁被占用

`0.1.4` 起不需要手工删除 SQLite 锁。新同步会先取得持久化目录中的独占文件锁；确认没有
仍在运行的同步进程后，只清除同一账号和图库的残留数据库租约并立即继续。若仍看到
`sync_skipped_already_running`，说明确实有另一个同步任务正在运行。

## 安全说明

- 不要提交 `.env`、`/config`、数据库、Session、凭据、通知令牌或真实 Apple ID。
- 不要通过环境变量、Compose `command` 或 shell 历史传递 Apple 密码和验证码。
- 只从可信源码构建镜像，并限制配置目录的宿主机访问权限。
- Webhook 可使用 HMAC-SHA256 签名；通知令牌应放在权限受限的文件中。
- 发现安全问题时，请使用 GitHub Security Advisory 私下报告，不要在公开 Issue 中附带账号、
  Cookie、日志原文或照片信息。

## License

[MIT](LICENSE)
