#!/usr/bin/env bash

set -Eeuo pipefail
umask 0022

if [[ "${BASH_VERSINFO[0]:-0}" -lt 4 ]]; then
    printf 'iCloudHarbor 安装器需要 Bash 4.0 或更高版本。\n' >&2
    exit 1
fi

REPOSITORY="lwx-cloud/icloudHarbor"
INSTALLER_REF="${IH_INSTALLER_REF:-main}"
RAW_BASE_URL="${IH_INSTALLER_RAW_BASE_URL:-https://raw.githubusercontent.com/${REPOSITORY}/${INSTALLER_REF}}"
SERVICE_NAME="icloudharbor"
IMAGE_NAME="lwxcloud/icloudharbor:latest"
ASSUME_YES="${IH_INSTALLER_ASSUME_YES:-false}"
ASSUME_YES="${ASSUME_YES,,}"

if [[ -t 1 ]]; then
    COLOR_BLUE=$'\033[0;34m'
    COLOR_GREEN=$'\033[0;32m'
    COLOR_YELLOW=$'\033[1;33m'
    COLOR_RED=$'\033[0;31m'
    COLOR_RESET=$'\033[0m'
else
    COLOR_BLUE=""
    COLOR_GREEN=""
    COLOR_YELLOW=""
    COLOR_RED=""
    COLOR_RESET=""
fi

TEMP_DIR=""
STAGED_COMPOSE=""
STAGED_ENV=""
STAGED_EXAMPLE=""
STAGED_MARKER=""
PROJECT_NAME=""

cleanup() {
    [[ -z "$STAGED_COMPOSE" ]] || rm -f -- "$STAGED_COMPOSE"
    [[ -z "$STAGED_ENV" ]] || rm -f -- "$STAGED_ENV"
    [[ -z "$STAGED_EXAMPLE" ]] || rm -f -- "$STAGED_EXAMPLE"
    [[ -z "$STAGED_MARKER" ]] || rm -f -- "$STAGED_MARKER"
    [[ -z "$TEMP_DIR" ]] || rm -rf -- "$TEMP_DIR"
}
trap cleanup EXIT

info() {
    printf '%s[信息]%s %s\n' "$COLOR_BLUE" "$COLOR_RESET" "$*"
}

success() {
    printf '%s[成功]%s %s\n' "$COLOR_GREEN" "$COLOR_RESET" "$*"
}

warn() {
    printf '%s[注意]%s %s\n' "$COLOR_YELLOW" "$COLOR_RESET" "$*" >&2
}

die() {
    printf '%s[错误]%s %s\n' "$COLOR_RED" "$COLOR_RESET" "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
iCloudHarbor Docker 一键安装器

用法：
  curl -fsSL https://raw.githubusercontent.com/lwx-cloud/icloudHarbor/main/deploy/install.sh | sudo bash
  sudo bash install.sh [--yes]

选项：
  -y, --yes  接受确认提示；首次认证仍必须在终端输入密码和验证码
  -h, --help 显示帮助

可选环境变量：
  IH_INSTALL_DIR                Compose 与 .env 的安装目录
  IH_APPLE_ID                  Apple Account 邮箱
  IH_CONFIG_PATH               配置、数据库和 Session 的宿主机目录
  IH_PHOTOS_PATH               照片保存目录
  IH_PUID / IH_PGID            容器运行 UID/GID，必须为非零正整数
  IH_TIMEZONE                  IANA 时区，例如 Asia/Shanghai
  IH_REGION                    auto、global 或 china
  IH_SYNC_INTERVAL             6、12 或 24
  IH_SYNOLOGY_PHOTOS_APP_FIX   true 或 false
  IH_CONTAINER_NAME            Docker 容器名
  IH_INSTALLER_REF             下载部署文件的 Git ref，默认 main

脚本不会读取或保存 Apple 密码、验证码。
EOF
}

for argument in "$@"; do
    case "$argument" in
        -y | --yes)
            ASSUME_YES="true"
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            die "未知参数：$argument"
            ;;
    esac
done

has_tty() {
    [[ -c /dev/tty ]] && ( : < /dev/tty > /dev/tty ) 2> /dev/null
}

prompt_value() {
    local label="$1"
    local default_value="$2"
    local entered=""

    if ! has_tty; then
        PROMPT_RESULT="$default_value"
        return
    fi
    if [[ -n "$default_value" ]]; then
        printf '%s [%s]: ' "$label" "$default_value" > /dev/tty
    else
        printf '%s: ' "$label" > /dev/tty
    fi
    IFS= read -r entered < /dev/tty || true
    PROMPT_RESULT="${entered:-$default_value}"
}

confirm() {
    local message="$1"
    local default_answer="${2:-yes}"
    local answer=""

    if [[ "$ASSUME_YES" == "true" ]]; then
        return 0
    fi
    if ! has_tty; then
        return 1
    fi
    if [[ "$default_answer" == "yes" ]]; then
        printf '%s [Y/n]: ' "$message" > /dev/tty
    else
        printf '%s [y/N]: ' "$message" > /dev/tty
    fi
    IFS= read -r answer < /dev/tty || true
    answer="${answer,,}"
    if [[ -z "$answer" ]]; then
        [[ "$default_answer" == "yes" ]]
        return
    fi
    [[ "$answer" == "y" || "$answer" == "yes" ]]
}

validate_positive_id() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

validate_apple_id() {
    local value="$1"
    local length

    [[ "$value" =~ ^[^@]+@[^@]+$ ]] || return 1
    [[ ! "$value" =~ [[:space:][:cntrl:]] ]] || return 1
    [[ "$value" != *. ]] || return 1
    case "$value" in
        *'<'* | *'>'* | *':'* | *'"'* | *'/'* | *'\'* | *'|'* | *'?'* | *'*'* | *'$'*)
            return 1
            ;;
    esac
    length=$(LC_ALL=C printf '%s' "$value" | wc -c | tr -d '[:space:]')
    [[ "$length" -le 220 ]]
}

normalize_path() {
    local value="$1"

    while [[ "$value" != "/" && "$value" == */ ]]; do
        value="${value%/}"
    done
    NORMALIZED_PATH="$value"
}

validate_path() {
    local value="$1"

    [[ "$value" == /* ]] || return 1
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || return 1
    [[ "$value" != *'"'* && "$value" != *'$'* && "$value" != *'\'* ]] || return 1
    [[ "$value" != *:* ]] || return 1
    [[ "$value" != *//* ]] || return 1
    [[ ! "$value" =~ (^|/)\.\.?(/|$) ]] || return 1
    case "$value" in
        / | /bin | /boot | /dev | /etc | /home | /lib | /lib64 | /media | /mnt | /opt | /proc | /root | /run | /sbin | /srv | /sys | /tmp | /usr | /var)
            return 1
            ;;
    esac
    [[ ! "$value" =~ ^/volume[0-9]+$ ]]
}

prompt_validated() {
    local label="$1"
    local default_value="$2"
    local validator="$3"
    local error_message="$4"

    while true; do
        prompt_value "$label" "$default_value"
        if "$validator" "$PROMPT_RESULT"; then
            return
        fi
        if ! has_tty; then
            die "$error_message"
        fi
        warn "$error_message"
        default_value=""
    done
}

detect_timezone() {
    local detected=""
    local zone_link=""

    if [[ -n "${TZ:-}" ]]; then
        detected="$TZ"
    elif [[ -r /etc/timezone ]]; then
        IFS= read -r detected < /etc/timezone || true
    elif [[ -L /etc/localtime ]]; then
        zone_link=$(readlink /etc/localtime || true)
        if [[ "$zone_link" == *zoneinfo/* ]]; then
            detected="${zone_link#*zoneinfo/}"
        fi
    fi
    if [[ ! "$detected" =~ ^[A-Za-z0-9_+./-]+$ ]]; then
        detected="Asia/Shanghai"
    fi
    DETECTED_TIMEZONE="$detected"
}

default_install_directory() {
    if [[ -d /volume1/docker ]]; then
        printf '%s' "/volume1/docker/icloudharbor"
    else
        printf '%s' "/opt/icloudharbor"
    fi
}

default_photos_directory() {
    if [[ -d /volume2/photos ]]; then
        printf '%s' "/volume2/photos/iCloud"
    elif [[ -d /volume1/photo ]]; then
        printf '%s' "/volume1/photo/iCloud"
    elif [[ -d /volume1/photos ]]; then
        printf '%s' "/volume1/photos/iCloud"
    else
        printf '%s' "/srv/icloudharbor/photos"
    fi
}

check_prerequisites() {
    local missing=()
    local architecture

    [[ "$(id -u)" -eq 0 ]] || die "请使用 sudo bash 运行安装器。"
    [[ "$(uname -s)" == "Linux" ]] || die "生产安装只支持 Linux。"
    architecture="$(uname -m)"
    case "$architecture" in
        x86_64 | amd64 | aarch64 | arm64)
            ;;
        *)
            die "不支持的架构：$architecture；镜像只提供 amd64 和 arm64。"
            ;;
    esac

    for command_name in cat chmod chown cp curl docker find grep id mkdir mktemp mv readlink rm sleep tr uname wc; do
        command -v "$command_name" > /dev/null 2>&1 || missing+=("$command_name")
    done
    if [[ "${#missing[@]}" -gt 0 ]]; then
        die "缺少依赖：${missing[*]}"
    fi
    docker info > /dev/null 2>&1 || die "Docker daemon 不可用，请先启动 Docker。"
    docker compose version > /dev/null 2>&1 || die "缺少 Docker Compose 插件；不支持旧 docker-compose 命令。"
}

download_deployment_files() {
    TEMP_DIR=$(mktemp -d)
    info "正在下载最新部署文件（ref: $INSTALLER_REF）"
    curl --fail --silent --show-error --location \
        --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 10 --max-time 120 \
        "$RAW_BASE_URL/docker-compose.yml" -o "$TEMP_DIR/docker-compose.yml"
    curl --fail --silent --show-error --location \
        --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 10 --max-time 120 \
        "$RAW_BASE_URL/.env.example" -o "$TEMP_DIR/.env.example"

    grep -Fq 'services:' "$TEMP_DIR/docker-compose.yml" || die "下载的 Compose 文件格式无效。"
    grep -Fq "$IMAGE_NAME" "$TEMP_DIR/docker-compose.yml" || die "下载的 Compose 文件镜像不匹配。"
    grep -Fq 'IH_APPLE_ID=' "$TEMP_DIR/.env.example" || die "下载的环境变量示例格式无效。"
}

install_managed_files() {
    local compose_target="$INSTALL_DIR/docker-compose.yml"
    local example_target="$INSTALL_DIR/.env.example"

    if [[ -e "$compose_target" || -L "$compose_target" ]]; then
        [[ -f "$compose_target" && ! -L "$compose_target" ]] || \
            die "Compose 目标必须是普通文件：$compose_target"
        cp -p -- "$compose_target" "$TEMP_DIR/docker-compose.yml.previous"
    fi
    if [[ -e "$example_target" || -L "$example_target" ]]; then
        [[ -f "$example_target" && ! -L "$example_target" ]] || \
            die "环境变量示例目标必须是普通文件：$example_target"
    fi
    STAGED_COMPOSE=$(mktemp "$INSTALL_DIR/.docker-compose.yml.XXXXXX")
    cp -- "$TEMP_DIR/docker-compose.yml" "$STAGED_COMPOSE"
    chmod 0644 "$STAGED_COMPOSE"
    mv -f -- "$STAGED_COMPOSE" "$compose_target"
    STAGED_COMPOSE=""

    STAGED_EXAMPLE=$(mktemp "$INSTALL_DIR/.env.example.XXXXXX")
    cp -- "$TEMP_DIR/.env.example" "$STAGED_EXAMPLE"
    chmod 0644 "$STAGED_EXAMPLE"
    mv -f -- "$STAGED_EXAMPLE" "$example_target"
    STAGED_EXAMPLE=""
}

write_new_environment() {
    STAGED_MARKER=$(mktemp "$INSTALL_DIR/.icloudharbor-installer.XXXXXX")
    printf 'project=%s\n' "$PROJECT_NAME" > "$STAGED_MARKER"
    chown 0:0 "$STAGED_MARKER"
    chmod 0644 "$STAGED_MARKER"
    mv -f -- "$STAGED_MARKER" "$INSTALL_DIR/.icloudharbor-installer"
    STAGED_MARKER=""

    STAGED_ENV=$(mktemp "$INSTALL_DIR/.env.XXXXXX")
    chmod 0600 "$STAGED_ENV"
    cat > "$STAGED_ENV" <<EOF
# 由 iCloudHarbor 一键安装器生成。Apple 密码和验证码不得写入本文件。
IH_APPLE_ID="$APPLE_ID"
IH_CONTAINER_NAME="$CONTAINER_NAME"
IH_CONFIG_PATH="$CONFIG_PATH"
IH_PHOTOS_PATH="$PHOTOS_PATH"
IH_PUID="$PUID"
IH_PGID="$PGID"
IH_TIMEZONE="$TIMEZONE"
IH_REGION="$REGION"
IH_SYNC_INTERVAL="$SYNC_INTERVAL"
IH_RUN_ON_START="true"
IH_DOWNLOAD_VIDEOS="true"
IH_DOWNLOAD_LIVE_PHOTOS="true"
IH_CONVERT_HEIC_TO_JPEG="false"
IH_SYNOLOGY_PHOTOS_APP_FIX="$SYNOLOGY_FIX"
EOF
    chown 0:0 "$STAGED_ENV"
    mv -f -- "$STAGED_ENV" "$INSTALL_DIR/.env"
    STAGED_ENV=""
}

prepare_directories() {
    local config_created="false"
    local photos_created="false"
    local marker="$PHOTOS_PATH/.icloudharbor-mounted"
    local install_real
    local config_real
    local photos_real

    if [[ ! -d "$INSTALL_DIR" ]]; then
        mkdir -p -- "$INSTALL_DIR"
    fi
    if [[ ! -d "$CONFIG_PATH" ]]; then
        mkdir -p -- "$CONFIG_PATH"
        config_created="true"
    fi
    if [[ ! -d "$PHOTOS_PATH" ]]; then
        mkdir -p -- "$PHOTOS_PATH"
        photos_created="true"
    fi

    install_real=$(readlink -f "$INSTALL_DIR") || die "无法解析安装目录：$INSTALL_DIR"
    config_real=$(readlink -f "$CONFIG_PATH") || die "无法解析配置目录：$CONFIG_PATH"
    photos_real=$(readlink -f "$PHOTOS_PATH") || die "无法解析照片目录：$PHOTOS_PATH"
    [[ "$install_real" != "$config_real" ]] || die "安装目录和配置目录解析后不能相同。"
    [[ "$config_real" != "$photos_real" ]] || die "配置目录和照片目录解析后不能相同。"
    case "$install_real/" in
        "$config_real/"*) die "安装目录不能位于容器可写的配置目录内部。" ;;
        "$photos_real/"*) die "安装目录不能位于容器可写的照片目录内部。" ;;
    esac
    case "$config_real/" in
        "$photos_real/"*) die "配置目录不能位于照片目录内部。" ;;
    esac
    case "$photos_real/" in
        "$config_real/"*) die "照片目录不能位于配置目录内部。" ;;
    esac

    chown 0:0 "$INSTALL_DIR"
    chmod 0755 "$INSTALL_DIR"
    if [[ "$config_created" == "true" ]]; then
        chown "$PUID:$PGID" "$CONFIG_PATH"
        chmod 0750 "$CONFIG_PATH"
    fi
    if [[ "$photos_created" == "true" ]]; then
        chown "$PUID:$PGID" "$PHOTOS_PATH"
        chmod 0750 "$PHOTOS_PATH"
    else
        warn "照片目录已经存在，安装器不会递归修改属主或 NAS ACL。"
    fi

    if [[ -L "$marker" || ( -e "$marker" && ! -f "$marker" ) ]]; then
        die "挂载标记必须是普通文件：$marker"
    fi
    if [[ ! -e "$marker" ]]; then
        : > "$marker"
        chown "$PUID:$PGID" "$marker"
        chmod 0644 "$marker"
    fi
}

compose() {
    docker compose --project-name "$PROJECT_NAME" --project-directory "$INSTALL_DIR" \
        -f "$INSTALL_DIR/docker-compose.yml" "$@"
}

restore_compose_after_invalid_config() {
    if [[ -f "$TEMP_DIR/docker-compose.yml.previous" ]]; then
        cp -p -- "$TEMP_DIR/docker-compose.yml.previous" "$INSTALL_DIR/docker-compose.yml"
    else
        rm -f -- "$INSTALL_DIR/docker-compose.yml"
    fi
}

deploy_container() {
    local version_output=""
    local attempt

    if ! compose config --quiet; then
        restore_compose_after_invalid_config
        die "Compose 配置校验失败；旧 Compose 文件已恢复。"
    fi

    info "正在拉取 $IMAGE_NAME"
    compose pull
    info "正在启动容器"
    compose up -d --force-recreate --remove-orphans

    for ((attempt = 1; attempt <= 30; attempt++)); do
        if version_output=$(compose exec -T "$SERVICE_NAME" icloudharbor --version 2> /dev/null); then
            break
        fi
        sleep 1
    done
    if [[ -z "$version_output" ]]; then
        compose logs --tail=100 "$SERVICE_NAME" || true
        die "容器未能正常启动；已保留全部配置和日志。"
    fi
    success "容器已启动：$version_output"

    info "正在检查数据库、目录、挂载标记、权限和剩余空间"
    if ! compose exec -T "$SERVICE_NAME" icloudharbor status; then
        compose logs --tail=100 "$SERVICE_NAME" || true
        die "安装检查未通过；请按 status 输出修复权限、ACL 或剩余空间后重新运行。"
    fi
}

print_commands() {
    cat <<EOF

安装目录：$INSTALL_DIR

首次认证：
  cd "$INSTALL_DIR"
  sudo docker compose exec icloudharbor icloudharbor setup

查看下载：
  cd "$INSTALL_DIR"
  sudo docker compose logs -f icloudharbor

以后升级可重新运行同一条一键安装命令；现有 .env、数据库、Session 和照片不会被覆盖。
EOF
}

collect_fresh_configuration() {
    local default_uid="1000"
    local default_gid="1000"
    local default_synology_fix="false"

    if validate_positive_id "${SUDO_UID:-}"; then
        default_uid="$SUDO_UID"
    fi
    if validate_positive_id "${SUDO_GID:-}"; then
        default_gid="$SUDO_GID"
    fi
    if [[ -f /etc/synoinfo.conf || -f /etc.defaults/synoinfo.conf ]]; then
        default_synology_fix="true"
    fi
    detect_timezone

    prompt_validated \
        "Apple Account 邮箱" "${IH_APPLE_ID:-}" validate_apple_id \
        "Apple Account 必须只有一个非首尾 @、没有路径保留字符，且不超过 220 字节。"
    APPLE_ID="$PROMPT_RESULT"

    CONFIG_PATH="${IH_CONFIG_PATH:-$INSTALL_DIR/data/config}"
    prompt_validated \
        "配置、数据库和 Session 目录" "$CONFIG_PATH" validate_path \
        "配置目录必须是安全的绝对 Linux 路径，不能使用系统顶层目录。"
    normalize_path "$PROMPT_RESULT"
    CONFIG_PATH="$NORMALIZED_PATH"

    PHOTOS_PATH="${IH_PHOTOS_PATH:-$(default_photos_directory)}"
    prompt_validated \
        "照片保存目录（不会追加账号子目录）" "$PHOTOS_PATH" validate_path \
        "照片目录必须是安全的绝对 Linux 路径，不能使用系统顶层目录。"
    normalize_path "$PROMPT_RESULT"
    PHOTOS_PATH="$NORMALIZED_PATH"

    if [[ "$CONFIG_PATH" == "$PHOTOS_PATH" ]]; then
        die "配置目录和照片目录不能相同。"
    fi
    if [[ "$CONFIG_PATH" == "$INSTALL_DIR" ]]; then
        die "配置目录不能与安装目录相同；请使用安装目录下的 data/config 等专用子目录。"
    fi
    case "$INSTALL_DIR/" in
        "$CONFIG_PATH/"*) die "安装目录不能位于容器可写的配置目录内部。" ;;
        "$PHOTOS_PATH/"*) die "安装目录不能位于容器可写的照片目录内部。" ;;
    esac
    case "$CONFIG_PATH/" in
        "$PHOTOS_PATH/"*) die "配置目录不能位于照片目录内部。" ;;
    esac
    case "$PHOTOS_PATH/" in
        "$CONFIG_PATH/"*) die "照片目录不能位于配置目录内部。" ;;
    esac

    prompt_validated "容器运行 UID" "${IH_PUID:-$default_uid}" validate_positive_id \
        "UID 必须是非零正整数。"
    PUID="$PROMPT_RESULT"
    prompt_validated "容器运行 GID" "${IH_PGID:-$default_gid}" validate_positive_id \
        "GID 必须是非零正整数。"
    PGID="$PROMPT_RESULT"

    TIMEZONE="${IH_TIMEZONE:-$DETECTED_TIMEZONE}"
    prompt_validated "时区" "$TIMEZONE" validate_timezone \
        "时区只能包含字母、数字、点、斜杠、加号、减号和下划线。"
    TIMEZONE="$PROMPT_RESULT"

    prompt_validated "iCloud 区域（auto/global/china）" "${IH_REGION:-auto}" validate_region \
        "区域只能是 auto、global 或 china。"
    REGION="$PROMPT_RESULT"

    prompt_validated "同步间隔小时（6/12/24）" "${IH_SYNC_INTERVAL:-24}" validate_interval \
        "同步间隔只能是 6、12 或 24。"
    SYNC_INTERVAL="$PROMPT_RESULT"

    prompt_validated \
        "启用 Synology Photos 兼容处理（true/false）" \
        "${IH_SYNOLOGY_PHOTOS_APP_FIX:-$default_synology_fix}" validate_boolean \
        "该选项只能是 true 或 false。"
    SYNOLOGY_FIX="${PROMPT_RESULT,,}"

    CONTAINER_NAME="${IH_CONTAINER_NAME:-icloudharbor}"
    validate_container_name "$CONTAINER_NAME" || die "IH_CONTAINER_NAME 不是有效的 Docker 容器名。"
}

validate_timezone() {
    [[ "$1" =~ ^[A-Za-z0-9_+./-]+$ ]]
}

validate_region() {
    [[ "$1" == "auto" || "$1" == "global" || "$1" == "china" ]]
}

validate_interval() {
    [[ "$1" == "6" || "$1" == "12" || "$1" == "24" ]]
}

validate_boolean() {
    local value="${1,,}"
    [[ "$value" == "true" || "$value" == "false" ]]
}

validate_container_name() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]
}

set_project_name() {
    PROJECT_NAME="${1,,}"
    PROJECT_NAME="${PROJECT_NAME//./-}"
}

load_managed_project() {
    local marker="$INSTALL_DIR/.icloudharbor-installer"
    local line=""

    [[ -f "$marker" && ! -L "$marker" ]] || return 1
    IFS= read -r line < "$marker" || true
    [[ "$line" =~ ^project=([a-z0-9][a-z0-9_-]*)$ ]] || return 1
    PROJECT_NAME="${BASH_REMATCH[1]}"
}

main() {
    local install_default
    local existing_install="false"
    local env_path
    local marker_path

    printf '\n%s========================================%s\n' "$COLOR_BLUE" "$COLOR_RESET"
    printf '        iCloudHarbor 一键安装向导\n'
    printf '%s========================================%s\n\n' "$COLOR_BLUE" "$COLOR_RESET"

    check_prerequisites
    install_default="${IH_INSTALL_DIR:-$(default_install_directory)}"
    prompt_validated "安装目录" "$install_default" validate_path \
        "安装目录必须是安全的绝对 Linux 路径，不能使用系统顶层目录。"
    normalize_path "$PROMPT_RESULT"
    INSTALL_DIR="$NORMALIZED_PATH"
    [[ ! -L "$INSTALL_DIR" ]] || die "安装目录不能是符号链接：$INSTALL_DIR"
    env_path="$INSTALL_DIR/.env"
    marker_path="$INSTALL_DIR/.icloudharbor-installer"

    if [[ -e "$env_path" || -L "$env_path" ]]; then
        [[ -f "$env_path" && ! -L "$env_path" ]] || \
            die "安装器管理的 .env 必须是普通文件：$env_path"
        load_managed_project || \
            die "目录包含非安装器管理的 .env；为避免覆盖手动部署或其他项目，已停止：$INSTALL_DIR"
        chown 0:0 "$INSTALL_DIR" "$env_path" "$marker_path"
        chmod 0755 "$INSTALL_DIR"
        chmod 0600 "$env_path"
        chmod 0644 "$marker_path"
        existing_install="true"
        info "检测到已有安装，将保留 .env、配置、数据库、Session 和照片。"
        confirm "更新 Compose 文件并拉取最新镜像？" "yes" || die "已取消更新。"
    else
        if [[ -e "$marker_path" || -L "$marker_path" ]]; then
            load_managed_project || die "安装器管理标记无效：$marker_path"
            info "检测到上次中断的安装，将重新收集参数并继续。"
        elif [[ -d "$INSTALL_DIR" ]] && \
            [[ -n "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
            die "安装目录非空且没有 .env，为避免覆盖未知文件已停止：$INSTALL_DIR"
        fi
        if ! has_tty && [[ -z "${IH_APPLE_ID:-}" ]]; then
            die "无交互终端时必须通过 IH_APPLE_ID 提供 Apple Account。"
        fi
        collect_fresh_configuration
        set_project_name "$CONTAINER_NAME"

        if docker container inspect "$CONTAINER_NAME" > /dev/null 2>&1; then
            die "已存在同名容器 $CONTAINER_NAME；请使用其他 IH_CONTAINER_NAME 或先确认旧容器归属。"
        fi

        printf '\n安装摘要：\n'
        printf '  Apple Account: %s\n' "$APPLE_ID"
        printf '  安装目录:      %s\n' "$INSTALL_DIR"
        printf '  配置目录:      %s\n' "$CONFIG_PATH"
        printf '  照片目录:      %s\n' "$PHOTOS_PATH"
        printf '  运行用户:      %s:%s\n' "$PUID" "$PGID"
        printf '  时区/区域:     %s / %s\n' "$TIMEZONE" "$REGION"
        printf '  同步间隔:      %s 小时\n\n' "$SYNC_INTERVAL"
        confirm "确认创建目录并启动 iCloudHarbor？" "yes" || die "已取消安装。"

        prepare_directories
        write_new_environment
    fi

    download_deployment_files
    install_managed_files
    deploy_container

    if [[ "$existing_install" == "false" ]] && has_tty; then
        if confirm "是否现在输入 Apple 密码和验证码完成首次认证？" "yes"; then
            if compose exec "$SERVICE_NAME" icloudharbor setup < /dev/tty; then
                success "首次认证完成，后台已经接手同步。"
            else
                warn "首次认证未完成；安装文件和容器已保留，可稍后重新运行 setup。"
                print_commands
                exit 1
            fi
        fi
    fi

    success "iCloudHarbor 安装完成。"
    print_commands
}

main "$@"
