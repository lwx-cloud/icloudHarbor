#!/usr/bin/env bash

set -Eeuo pipefail
umask 0022

REPOSITORY="lwx-cloud/icloudHarbor"
INSTALLER_REF="${IH_INSTALLER_REF:-main}"
RAW_COMPOSE_URL="https://raw.githubusercontent.com/${REPOSITORY}/${INSTALLER_REF}/docker-compose.yml"
INSTALL_DIR="$(pwd -P)"
CONFIG_DIR="$INSTALL_DIR/config"
ENV_FILE="$INSTALL_DIR/.env"
COMPOSE_FILE="$INSTALL_DIR/docker-compose.yaml"
HOST_UID="${SUDO_UID:-}"
HOST_GID="${SUDO_GID:-}"

if [[ ! "$HOST_UID" =~ ^[1-9][0-9]*$ ]] || [[ ! "$HOST_GID" =~ ^[1-9][0-9]*$ ]]; then
    HOST_UID="$(stat -c '%u' "$INSTALL_DIR")"
    HOST_GID="$(stat -c '%g' "$INSTALL_DIR")"
fi

if [[ "$HOST_UID" =~ ^[1-9][0-9]*$ ]] && [[ "$HOST_GID" =~ ^[1-9][0-9]*$ ]]; then
    ENV_PUID="$HOST_UID"
    ENV_PGID="$HOST_GID"
else
    ENV_PUID="请填写宿主机管理员UID"
    ENV_PGID="请填写宿主机管理员GID"
fi

failed() {
    printf '[失败] iCloudHarbor 部署文件生成失败。\n' >&2
}
trap failed ERR

mkdir -p -- "$CONFIG_DIR"
chmod 0777 "$INSTALL_DIR" "$CONFIG_DIR"
rm -f -- \
    "$INSTALL_DIR/.env.example" \
    "$INSTALL_DIR/.icloudharbor-installer" \
    "$INSTALL_DIR/docker-compose.yml"

cat > "$ENV_FILE" <<EOF
# 请填写 Apple Account 邮箱
IH_APPLE_ID="请填写 Apple Account 邮箱"

IH_CONFIG_PATH="$CONFIG_DIR"

# 请填写照片保存目录，例如 /volume2/photos/iCloud
IH_PHOTOS_PATH="请填写照片保存目录"

IH_PUID="$ENV_PUID"
IH_PGID="$ENV_PGID"
IH_TIMEZONE="Asia/Shanghai"
IH_REGION="auto"
IH_SYNC_INTERVAL="12"
IH_RUN_ON_START="true"
IH_PHOTO_SIZE="original"
IH_NOTIFY="false"
EOF
chmod 0666 "$ENV_FILE"

curl --fail --silent --location \
    "$RAW_COMPOSE_URL" \
    --output "$COMPOSE_FILE"
chmod 0666 "$COMPOSE_FILE"

if [[ "$(id -u)" == "0" ]] && [[ "$ENV_PUID" =~ ^[1-9][0-9]*$ ]]; then
    chown "$ENV_PUID:$ENV_PGID" "$CONFIG_DIR" "$ENV_FILE" "$COMPOSE_FILE"
fi

trap - ERR
printf '[成功] 已在 %s 生成 config/、.env 和 docker-compose.yaml。\n' "$INSTALL_DIR"
