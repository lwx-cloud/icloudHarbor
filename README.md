# iCloudHarbor

[![CI](https://github.com/lwx-cloud/icloudHarbor/actions/workflows/ci.yml/badge.svg)](https://github.com/lwx-cloud/icloudHarbor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

iCloudHarbor 是一个运行在 Docker 中的 iCloud Photos 备份工具。它会定时把照片、视频、
Live Photo 和 RAW 下载到 Linux、群晖或其他 NAS。

> 当前版本：`0.6.1`。只支持从 iCloud 备份到本地，不会删除 iCloud 中的照片。

[立即部署](#最简单部署) · [日常使用](#日常使用) · [更新](#更新) ·
[完整配置](CONFIGURATION.md)

它支持断点续传和文件校验；容器重启后会继续同步，已经下载的照片不会重复下载。通知、
扫描加速、RAW、相册、命名等选项都在 [CONFIGURATION.md](CONFIGURATION.md) 中说明，首次
部署不需要配置。

## 最简单部署

下面以群晖路径为例：

- 程序配置保存在 `/volume1/docker/icloudharbor/config`；
- 照片保存在 `/volume2/photos/iCloud`。

请先确认设备已经安装 Docker 和 Docker Compose。

### 1. 生成部署文件

通过 SSH 进入 NAS，然后运行：

```bash
mkdir -p /volume1/docker/icloudharbor
cd /volume1/docker/icloudharbor
curl -fsSL https://raw.githubusercontent.com/lwx-cloud/icloudHarbor/main/deploy/install.sh | sudo bash
```

完成后会生成：

```text
config/
.env
docker-compose.yaml
```

> 安装脚本只用于首次部署。再次运行会覆盖 `.env` 和 `docker-compose.yaml`，更新程序时不要
> 重复执行安装脚本。

### 2. 编辑 `.env`

使用群晖 File Station 打开 `.env`，也可以在终端使用：

```bash
vi .env
```

只需要修改或确认下面这些参数：

| 参数 | 填什么 | 用途 |
| --- | --- | --- |
| `IH_APPLE_ID` | Apple Account 邮箱 | 指定需要备份的 iCloud 账号。 |
| `IH_PHOTOS_PATH` | 例如 `/volume2/photos/iCloud` | 照片在 NAS 上的保存目录。 |
| `IH_REGION` | `global` 或 `china` | 普通账号用 `global`；云上贵州账号用 `china`。 |
| `IH_PUID` | NAS 用户的 UID | 让下载文件属于正确的 NAS 用户。 |
| `IH_PGID` | NAS 用户组的 GID | 让下载文件属于正确的 NAS 用户组。 |

安装脚本通常会自动填写 UID/GID。群晖可以运行下面的命令核对：

```bash
id 管理员用户名
```

例如输出包含 `uid=1026`、`gid=100`，就分别填写 `1026` 和 `100`。不要直接照抄别人的数字。

其余参数保持默认即可：

| 参数 | 默认作用 |
| --- | --- |
| `IH_CONFIG_PATH` | 保存数据库、登录状态和程序配置，不要随意更换。 |
| `IH_TIMEZONE` | 日志和定时任务使用的时区。 |
| `IH_SYNC_INTERVAL=12` | 每 12 小时检查一次；只能填写 `6`、`12` 或 `24`。 |
| `IH_RUN_ON_START=true` | 容器启动后立即检查一次。 |
| `IH_PHOTO_SIZE=original` | 下载照片原始版本。 |
| `IH_NOTIFY=false` | 默认关闭通知。 |

Apple 密码不要写进 `.env`，认证时会在终端单独询问。

### 3. 创建照片目录和安全标记

这里的路径必须和 `IH_PHOTOS_PATH` 完全一致：

```bash
mkdir -p /volume2/photos/iCloud
touch /volume2/photos/iCloud/.icloudharbor-mounted
```

`.icloudharbor-mounted` 用于确认照片磁盘已经正确挂载。如果没有这个文件，程序会拒绝下载，
避免照片被误写进容器磁盘。

### 4. 启动并登录 iCloud

```bash
docker compose pull
docker compose up -d
docker compose exec icloudharbor icloudharbor setup
docker compose logs -f icloudharbor
```

`setup` 会询问 Apple 密码，并在需要时询问双重认证验证码。输入密码时终端只显示星号。
认证成功后可以退出操作界面，照片下载会在主容器后台继续执行。

看到日志开始扫描图库或下载照片，就说明部署完成。

## 日常使用

```bash
# 查看下载日志
docker compose logs -f icloudharbor

# 查看状态
docker compose exec icloudharbor icloudharbor status

# 立即请求一次后台同步
docker compose exec icloudharbor icloudharbor sync

# Apple 登录失效后重新认证
docker compose exec icloudharbor icloudharbor setup
```

其他参数见 [CONFIGURATION.md](CONFIGURATION.md)。

## 更新

进入部署目录后运行：

```bash
cd /volume1/docker/icloudharbor
docker compose pull
docker compose up -d --force-recreate --remove-orphans
docker compose exec icloudharbor icloudharbor --version
```

更新不会删除照片、数据库或登录状态。不要重新运行首次安装脚本。

从旧版本升级以及完整扫描一次的建议见
[CONFIGURATION.md 的常见配置](CONFIGURATION.md#常见配置)。

## 更多设置

| 想设置什么 | 查看位置 |
| --- | --- |
| 通知 | [通知配置](CONFIGURATION.md#通知配置) |
| 下载照片尺寸、Live Photo、RAW/JPEG | [媒体](CONFIGURATION.md#媒体) |
| 指定相册、日期或加快日常扫描 | [相册和筛选](CONFIGURATION.md#相册和筛选) |
| 下载目录、文件名、权限和并发数 | [路径、权限和下载](CONFIGURATION.md#路径权限和下载) |
| Cron、多通知渠道等高级功能 | [高级 config.yaml](CONFIGURATION.md#高级-configyaml) |

遇到 `marker_missing`、`AUTH_REQUIRED` 或目录权限问题，请查看
[CONFIGURATION.md 的常见问题](CONFIGURATION.md#常见问题)。

> `/config` 包含 Apple 登录状态和数据库，应当持久化并定期备份。不要公开 Apple 密码、
> Cookie、验证码或通知密钥。

## License

[MIT](LICENSE)
