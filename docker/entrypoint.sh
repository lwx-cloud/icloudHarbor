#!/bin/sh
set -eu

IH_RUNTIME_UID="${IH_PUID:-1000}"
IH_RUNTIME_GID="${IH_PGID:-1000}"

case "$IH_RUNTIME_UID:$IH_RUNTIME_GID" in
  *[!0-9:]*|:*|*:) echo "IH_PUID 和 IH_PGID 必须是正整数" >&2; exit 2 ;;
esac
if [ "$IH_RUNTIME_UID" -lt 1 ] || [ "$IH_RUNTIME_GID" -lt 1 ]; then
  echo "IH_PUID 和 IH_PGID 必须是正整数" >&2
  exit 2
fi
umask 0022

groupmod --non-unique --gid "$IH_RUNTIME_GID" icloudharbor
usermod --non-unique --uid "$IH_RUNTIME_UID" --gid "$IH_RUNTIME_GID" \
  --home /nonexistent icloudharbor

mkdir -p \
  /config/credentials /config/database /config/sessions /config/locks /config/tmp \
  /config/notification-keys
chown -R "$IH_RUNTIME_UID:$IH_RUNTIME_GID" \
  /config/credentials /config/database /config/sessions /config/locks /config/tmp \
  /config/notification-keys
/usr/sbin/gosu "$IH_RUNTIME_UID:$IH_RUNTIME_GID" \
  chmod 0700 \
  /config/credentials /config/database /config/sessions /config/locks /config/tmp \
  /config/notification-keys

if [ -n "${IH_WECOM_SECRET:-}" ]; then
  IH_WECOM_SECRET_PATH=/config/notification-keys/wecom-secret
  printf '%s' "$IH_WECOM_SECRET" > "$IH_WECOM_SECRET_PATH"
  chown "$IH_RUNTIME_UID:$IH_RUNTIME_GID" "$IH_WECOM_SECRET_PATH"
  /usr/sbin/gosu "$IH_RUNTIME_UID:$IH_RUNTIME_GID" chmod 0600 "$IH_WECOM_SECRET_PATH"
fi

IH_RUNTIME_CONFIG="${IH_CONFIG_FILE:-/config/config.yaml}"
if [ ! -e "$IH_RUNTIME_CONFIG" ]; then
  /app/.venv/bin/icloudharbor config bootstrap
fi

if [ -e "$IH_RUNTIME_CONFIG" ]; then
  chown "$IH_RUNTIME_UID:$IH_RUNTIME_GID" "$IH_RUNTIME_CONFIG"
  /usr/sbin/gosu "$IH_RUNTIME_UID:$IH_RUNTIME_GID" chmod 0600 "$IH_RUNTIME_CONFIG"
fi
if ! /usr/sbin/gosu "$IH_RUNTIME_UID:$IH_RUNTIME_GID" test -r "$IH_RUNTIME_CONFIG"; then
  echo "配置文件不存在或不可读：$IH_RUNTIME_CONFIG" >&2
  exit 2
fi

exec /usr/bin/tini -- /usr/sbin/gosu \
  "$IH_RUNTIME_UID:$IH_RUNTIME_GID" "$@"
