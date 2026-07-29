#!/bin/sh
set -eu

if [ "$(id -u)" -eq 0 ]; then
    runtime_uid="${IH_PUID:-1000}"
    runtime_gid="${IH_PGID:-1000}"
    exec /usr/sbin/gosu "$runtime_uid:$runtime_gid" /app/.venv/bin/icloudharbor "$@"
fi

exec /app/.venv/bin/icloudharbor "$@"
