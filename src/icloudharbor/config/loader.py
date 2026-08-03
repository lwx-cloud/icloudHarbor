"""YAML loading and the Docker environment override surface."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from icloudharbor.config.models import AppConfig

DEFAULT_CONFIG_PATH = Path("/config/config.yaml")

Parser = Callable[[str], object]


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"布尔环境变量必须是 true/false、yes/no、on/off 或 1/0：{value}")


def _parse_int(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"整数环境变量格式无效：{value}") from exc


def _identity(value: str) -> str:
    return value


def _lower(value: str) -> str:
    return value.lower()


def _upper(value: str) -> str:
    return value.upper()


def _parse_csv(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("逗号分隔参数至少需要一个非空值")
    return items


def _parse_csv_lower(value: str) -> list[str]:
    return [item.lower() for item in _parse_csv(value)]


def _parse_sync_interval(value: str) -> str:
    normalized = value.strip()
    if normalized in {"6h", "12h", "24h"}:
        hours = normalized.removesuffix("h")
        raise ValueError(
            f"IH_SYNC_INTERVAL 只填写小时数字；请将 IH_SYNC_INTERVAL={normalized} "
            f"改为 IH_SYNC_INTERVAL={hours}"
        )
    if normalized not in {"6", "12", "24"}:
        raise ValueError(
            "IH_SYNC_INTERVAL 只能填写 6、12 或 24（例如 IH_SYNC_INTERVAL=6，不要填写 6h）"
        )
    return f"{normalized}h"


RUNTIME_ENV_OVERRIDES: tuple[tuple[str, tuple[str, ...], Parser], ...] = (
    ("IH_TIMEZONE", ("timezone",), _identity),
    ("IH_LOG_LEVEL", ("log_level",), _upper),
    ("IH_LOG_FORMAT", ("log_format",), _lower),
)

ACCOUNT_ENV_OVERRIDES: tuple[tuple[str, tuple[str, ...], Parser], ...] = (
    ("IH_ACCOUNT_ID", ("id",), _identity),
    ("IH_ACCOUNT_NAME", ("name",), _identity),
    ("IH_APPLE_ID", ("apple_id",), _identity),
    ("IH_REGION", ("region",), _lower),
    ("IH_LIBRARIES", ("libraries",), _parse_csv),
    ("IH_MINIMUM_FREE_SPACE", ("destination", "minimum_free_space"), _identity),
    ("IH_DIRECTORY_PERMISSIONS", ("destination", "directory_permissions"), _identity),
    ("IH_FILE_PERMISSIONS", ("destination", "file_permissions"), _identity),
    (
        "IH_SYNOLOGY_PHOTOS_APP_FIX",
        ("destination", "synology_photos_app_fix"),
        _parse_bool,
    ),
    ("IH_DOWNLOAD_VIDEOS", ("media", "videos"), _parse_bool),
    ("IH_DOWNLOAD_LIVE_PHOTOS", ("media", "live_photos"), _parse_bool),
    ("IH_PHOTO_SIZE", ("media", "photo_size"), _parse_csv_lower),
    ("IH_LIVE_PHOTO_SIZE", ("media", "live_photo_size"), _lower),
    ("IH_RAW_MODE", ("media", "raw", "mode"), _lower),
    ("IH_CONVERT_HEIC_TO_JPEG", ("media", "convert_heic_to_jpeg"), _parse_bool),
    ("IH_JPEG_PATH", ("media", "jpeg_path"), _identity),
    ("IH_JPEG_QUALITY", ("media", "jpeg_quality"), _parse_int),
    ("IH_ALBUMS", ("filters", "albums"), _parse_csv),
    ("IH_EXCLUDE_ALBUMS", ("filters", "exclude_albums"), _parse_csv),
    ("IH_CREATED_AFTER", ("filters", "created_after"), _identity),
    ("IH_CREATED_BEFORE", ("filters", "created_before"), _identity),
    ("IH_FAVORITES_ONLY", ("filters", "favorites_only"), _parse_bool),
    ("IH_INCLUDE_HIDDEN", ("filters", "include_hidden"), _parse_bool),
    ("IH_RECENT_ONLY", ("filters", "recent_only"), _parse_int),
    ("IH_UNTIL_FOUND", ("filters", "until_found"), _parse_int),
    ("IH_FOLDER_STRUCTURE", ("naming", "folder_structure"), _identity),
    ("IH_FILENAME_TEMPLATE", ("naming", "filename"), _identity),
    ("IH_CONFLICT_POLICY", ("naming", "conflict_policy"), _lower),
    ("IH_SYNC_STRATEGY", ("sync", "strategy"), _lower),
    ("IH_FULL_SCAN_INTERVAL", ("sync", "full_scan_interval"), _identity),
    ("IH_RUN_ON_START", ("sync", "run_on_start"), _parse_bool),
    ("IH_DOWNLOAD_DELAY", ("sync", "download_delay"), _parse_int),
    ("IH_AUTO_DELETE", ("sync", "auto_delete"), _parse_bool),
    ("IH_DOWNLOAD_CONCURRENCY", ("download", "concurrency"), _parse_int),
    ("IH_DOWNLOAD_TIMEOUT", ("download", "timeout"), _parse_int),
    ("IH_MAX_RETRIES", ("download", "max_retries"), _parse_int),
)

NOTIFICATION_ENV_OVERRIDES: tuple[tuple[str, tuple[str, ...], Parser], ...] = (
    ("IH_NOTIFY_TITLE", ("title",), _identity),
    ("IH_NOTIFY_SILENT", ("silent",), _parse_bool),
    ("IH_NOTIFY_DAYS", ("notification_days",), _parse_int),
)

NOTIFICATION_TYPES = frozenset({"bark", "serverchan", "telegram", "wecom", "webhook"})
NOTIFICATION_SECRET_FILES = {
    "bark": "/config/notification-keys/bark-key",
    "serverchan": "/config/notification-keys/serverchan-key",
    "telegram": "/config/notification-keys/telegram-token",
    "wecom": "/config/notification-keys/wecom-secret",
    "webhook": "/config/notification-keys/webhook-secret",
}
NOTIFICATION_CHANNEL_ENVIRONMENT_VARIABLES = frozenset(
    {
        "IH_NOTIFY_TYPE",
        "IH_NOTIFY_TITLE",
        "IH_NOTIFY_SILENT",
        "IH_NOTIFY_DAYS",
        "IH_BARK_KEY",
        "IH_BARK_SERVER",
        "IH_SERVERCHAN_KEY",
        "IH_TELEGRAM_TOKEN",
        "IH_TELEGRAM_CHAT",
        "IH_WECOM_CORP_ID",
        "IH_WECOM_CORP_SECRET",
        "IH_WECOM_AGENT_ID",
        "IH_WECOM_TO_USER",
        "IH_WECOM_PROXY",
        "IH_WECOM_CONTENT_SOURCE_URL",
        "IH_WECOM_NAME",
        "MEDIA_ID_DOWNLOAD",
        "MEDIA_ID_STARTUP",
        "MEDIA_ID_WARNING",
        "MEDIA_ID_EXPIRATION",
        "IH_WEBHOOK_URL",
        "IH_WEBHOOK_SECRET",
    }
)

UNSUPPORTED_ENVIRONMENT_VARIABLES = frozenset(
    {
        "IH_SCHEDULE",
        "IH_DESTINATION",
        "IH_PHOTO_VERSION",
        "IH_NOTIFY_NO_CHANGES",
        "IH_VERIFY_HASH",
        "IH_KEEP_PARTIAL",
        "IH_CHUNK_SIZE",
        "IH_MOUNTED_MARKER",
        "IH_DOWNLOAD_PHOTOS",
        "IH_KEEP_UNICODE",
        "IH_UMASK",
        "IH_NOTIFICATION_TITLE",
        "IH_SILENT_NOTIFICATIONS",
        "IH_NOTIFY_STARTUP",
        "IH_NOTIFY_SUCCESS",
        "IH_NOTIFY_FAILURE",
        "IH_NOTIFY_AUTH_REQUIRED",
        "IH_NOTIFICATION_DAYS",
        "IH_WECOM_ID",
        "IH_WECOM_SECRET",
        "MEDIA_ID_DELETE",
        "notification_days",
    }
)


def config_path_from_env(explicit: Path | None = None) -> Path:
    return explicit or Path(os.environ.get("IH_CONFIG_FILE", DEFAULT_CONFIG_PATH))


def load_config(path: Path | None = None) -> AppConfig:
    resolved = config_path_from_env(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"配置文件不存在：{resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("配置文件根节点必须是 YAML 对象")
    data: dict[str, Any] = raw
    apply_environment_overrides(data)
    return AppConfig.model_validate(data)


def bootstrap_config(path: Path | None = None) -> tuple[AppConfig, bool]:
    """Create the initial persisted YAML from Docker parameters and defaults."""

    resolved = config_path_from_env(path)
    if resolved.is_file():
        return load_config(resolved), False

    _reject_unsupported_environment_variables()

    apple_id = _environment_value("IH_APPLE_ID")
    if apple_id is None:
        raise ValueError(f"首次启动需要设置 IH_APPLE_ID；程序会据此自动生成 {resolved}")
    apple_id = apple_id.strip()

    data: dict[str, Any] = {
        "version": 1,
        "runtime": {
            "timezone": "UTC",
            "database": "/config/database/icloudharbor.db",
            "temp_path": "/config/tmp",
        },
        "accounts": [
            {
                "id": apple_id,
                "name": apple_id,
                "apple_id": apple_id,
                "region": "auto",
                "enabled": True,
                "libraries": ["root"],
                "destination": {
                    "path": "/photos",
                    "minimum_free_space": "10GB",
                },
                "sync": {
                    "mode": "backup",
                    "strategy": "cursor",
                    "full_scan_interval": "30d",
                    "schedule": "24h",
                    "run_on_start": True,
                    "auto_delete": False,
                },
            }
        ],
    }
    apply_environment_overrides(data)
    config = AppConfig.model_validate(data)
    _write_new_config(resolved, config_snapshot(config))
    return config, True


def apply_environment_overrides(data: dict[str, Any]) -> None:
    """Apply non-secret Docker overrides on top of the YAML configuration."""

    _reject_unsupported_environment_variables()

    runtime = _mapping(data, "runtime")
    _apply_mapping(runtime, RUNTIME_ENV_OVERRIDES)

    account_names = {
        name for name, _, _ in ACCOUNT_ENV_OVERRIDES if _environment_value(name) is not None
    }
    sync_interval = _environment_value("IH_SYNC_INTERVAL")
    if sync_interval is not None:
        account_names.add("IH_SYNC_INTERVAL")

    if account_names:
        accounts = data.get("accounts")
        if not isinstance(accounts, list) or len(accounts) != 1:
            raise ValueError("账号环境变量覆盖要求 YAML 中恰好有一个账号")
        account = accounts[0]
        if not isinstance(account, dict):
            raise ValueError("YAML accounts[0] 必须是对象")
        _apply_mapping(account, ACCOUNT_ENV_OVERRIDES)
        apple_id = _environment_value("IH_APPLE_ID")
        if apple_id is not None:
            apple_id = apple_id.strip()
            if _environment_value("IH_ACCOUNT_ID") is None:
                account["id"] = apple_id
            if _environment_value("IH_ACCOUNT_NAME") is None:
                account["name"] = apple_id
        sync = _mapping(account, "sync")
        if sync_interval is not None:
            sync["schedule"] = _parse_sync_interval(sync_interval)

    notifications = _mapping(data, "notifications")
    _apply_notification_environment(notifications)


def _apply_notification_environment(notifications: dict[str, Any]) -> None:
    master = _environment_value("IH_NOTIFY")
    configured = sorted(
        name
        for name in NOTIFICATION_CHANNEL_ENVIRONMENT_VARIABLES
        if _environment_value(name) is not None
    )
    if master is None:
        if configured:
            raise ValueError("填写通知参数前必须设置 IH_NOTIFY=true 或 false")
        return

    enabled = cast(
        bool,
        _parse_environment_value("IH_NOTIFY", master, _parse_bool),
    )
    _apply_mapping(notifications, NOTIFICATION_ENV_OVERRIDES)

    channel_type = _environment_value("IH_NOTIFY_TYPE")
    if channel_type is not None:
        channel_type = channel_type.strip().lower()
        if channel_type not in NOTIFICATION_TYPES:
            supported = "、".join(sorted(NOTIFICATION_TYPES))
            raise ValueError(f"IH_NOTIFY_TYPE 只支持：{supported}")

    if not enabled:
        notifications.update(
            {
                "startup": False,
                "success": False,
                "failure": False,
                "auth_required": False,
                "channels": [],
            }
        )
        return

    if channel_type is None:
        raise ValueError("IH_NOTIFY=true 时必须设置 IH_NOTIFY_TYPE")

    notifications.update(
        {
            "startup": True,
            "success": True,
            "failure": True,
            "auth_required": True,
            "channels": [_notification_channel_from_environment(channel_type)],
        }
    )


def _notification_channel_from_environment(channel_type: str) -> dict[str, object]:
    if channel_type == "bark":
        _require_notification_environment("IH_BARK_KEY")
        channel: dict[str, object] = {
            "type": "bark",
            "device_key_file": NOTIFICATION_SECRET_FILES["bark"],
        }
        if server := _environment_value("IH_BARK_SERVER"):
            channel["server"] = server
        return channel

    if channel_type == "serverchan":
        _require_notification_environment("IH_SERVERCHAN_KEY")
        return {
            "type": "serverchan",
            "send_key_file": NOTIFICATION_SECRET_FILES["serverchan"],
        }

    if channel_type == "telegram":
        values = _require_notification_environment("IH_TELEGRAM_TOKEN", "IH_TELEGRAM_CHAT")
        return {
            "type": "telegram",
            "token_file": NOTIFICATION_SECRET_FILES["telegram"],
            "chat_id": values["IH_TELEGRAM_CHAT"],
        }

    if channel_type == "webhook":
        values = _require_notification_environment("IH_WEBHOOK_URL")
        channel = {"type": "webhook", "url": values["IH_WEBHOOK_URL"]}
        if _environment_value("IH_WEBHOOK_SECRET") is not None:
            channel["secret_file"] = NOTIFICATION_SECRET_FILES["webhook"]
        return channel

    values = _require_notification_environment(
        "IH_WECOM_CORP_ID",
        "IH_WECOM_CORP_SECRET",
        "IH_WECOM_AGENT_ID",
        "IH_WECOM_TO_USER",
    )
    channel = {
        "type": "wecom",
        "corp_id": values["IH_WECOM_CORP_ID"],
        "corp_secret_file": NOTIFICATION_SECRET_FILES["wecom"],
        "agent_id": _parse_environment_value(
            "IH_WECOM_AGENT_ID",
            values["IH_WECOM_AGENT_ID"],
            _parse_int,
        ),
        "to_user": values["IH_WECOM_TO_USER"],
    }
    optional = {
        "server": "IH_WECOM_PROXY",
        "content_source_url": "IH_WECOM_CONTENT_SOURCE_URL",
        "name": "IH_WECOM_NAME",
        "media_id_download": "MEDIA_ID_DOWNLOAD",
        "media_id_startup": "MEDIA_ID_STARTUP",
        "media_id_warning": "MEDIA_ID_WARNING",
        "media_id_expiration": "MEDIA_ID_EXPIRATION",
    }
    for key, name in optional.items():
        if value := _environment_value(name):
            channel[key] = value
    return channel


def _require_notification_environment(*names: str) -> dict[str, str]:
    values = {name: _environment_value(name) for name in names}
    missing = [name for name, value in values.items() if value is None]
    if missing:
        raise ValueError(f"通知参数缺少：{', '.join(missing)}")
    return {name: cast(str, value) for name, value in values.items()}


def _environment_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value


def _reject_unsupported_environment_variables() -> None:
    unsupported = sorted(
        name for name in UNSUPPORTED_ENVIRONMENT_VARIABLES if _environment_value(name) is not None
    )
    if unsupported:
        names = "、".join(unsupported)
        raise ValueError(
            f"检测到当前版本不支持的环境变量：{names}。"
            "请删除这些变量，并按照当前 README.md 或 CONFIGURATION.md 重新配置"
        )


def _parse_environment_value(name: str, value: str, parser: Parser) -> object:
    try:
        return parser(value)
    except ValueError as exc:
        message = str(exc)
        if message.startswith(name):
            raise
        raise ValueError(f"{name} 配置无效：{message}") from exc


def _apply_mapping(
    target: dict[str, Any],
    overrides: tuple[tuple[str, tuple[str, ...], Parser], ...],
) -> None:
    for name, path, parser in overrides:
        raw = _environment_value(name)
        if raw is None:
            continue
        _set_nested(target, path, _parse_environment_value(name, raw, parser))


def _set_nested(target: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    node = target
    for key in path[:-1]:
        node = _mapping(node, key)
    node[path[-1]] = value


def _mapping(target: dict[str, Any], key: str) -> dict[str, Any]:
    value = target.setdefault(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"YAML {key} 必须是对象")
    return value


def _write_new_config(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def config_snapshot(config: AppConfig) -> str:
    """Return stable YAML suitable for revision history (contains no password)."""
    payload = config.model_dump(mode="json", exclude_none=False)
    for account in payload["accounts"]:
        destination = account["destination"]
        for key in ("directory_permissions", "file_permissions"):
            mode = destination[key]
            if isinstance(mode, int):
                destination[key] = f"{mode:04o}"
    return cast(str, yaml.safe_dump(payload, allow_unicode=True, sort_keys=True))
