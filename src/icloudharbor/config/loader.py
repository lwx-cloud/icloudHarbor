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
    if normalized not in {"6", "12", "24"}:
        raise ValueError("IH_SYNC_INTERVAL 只能填写 6、12 或 24，单位固定为小时")
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
    ("IH_DOWNLOAD_CONCURRENCY", ("download", "concurrency"), _parse_int),
    ("IH_DOWNLOAD_TIMEOUT", ("download", "timeout"), _parse_int),
    ("IH_MAX_RETRIES", ("download", "max_retries"), _parse_int),
)

NOTIFICATION_ENV_OVERRIDES: tuple[tuple[str, tuple[str, ...], Parser], ...] = (
    ("IH_NOTIFICATION_TITLE", ("title",), _identity),
    ("IH_SILENT_NOTIFICATIONS", ("silent",), _parse_bool),
    ("IH_NOTIFY_STARTUP", ("startup",), _parse_bool),
    ("IH_NOTIFY_SUCCESS", ("success",), _parse_bool),
    ("IH_NOTIFY_FAILURE", ("failure",), _parse_bool),
    ("IH_NOTIFY_AUTH_REQUIRED", ("auth_required",), _parse_bool),
    ("IH_NOTIFICATION_DAYS", ("notification_days",), _parse_int),
)

WECOM_SECRET_FILE = "/config/notification-keys/wecom-secret"


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

    apple_id = _environment_value("IH_APPLE_ID")
    if apple_id is None:
        raise ValueError("首次启动需要设置 IH_APPLE_ID；程序会据此自动生成 /config/config.yaml")
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
                "name": "我的 iCloud",
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
        if apple_id is not None and _environment_value("IH_ACCOUNT_ID") is None:
            account["id"] = apple_id
        sync = _mapping(account, "sync")
        if sync_interval is not None:
            sync["schedule"] = _parse_sync_interval(sync_interval)

    notifications = _mapping(data, "notifications")
    _apply_mapping(notifications, NOTIFICATION_ENV_OVERRIDES)
    _apply_wecom_environment(notifications)


def _apply_wecom_environment(notifications: dict[str, Any]) -> None:
    values = {
        "corp_id": _environment_value("IH_WECOM_ID"),
        "secret": _environment_value("IH_WECOM_SECRET"),
        "agent_id": _environment_value("IH_WECOM_AGENT_ID"),
        "to_user": _environment_value("IH_WECOM_TO_USER"),
        "server": _environment_value("IH_WECOM_PROXY"),
        "content_source_url": _environment_value("IH_WECOM_CONTENT_SOURCE_URL"),
        "name": _environment_value("IH_WECOM_NAME"),
        "media_id_download": _environment_value("media_id_download"),
        "media_id_startup": _environment_value("media_id_startup"),
        "media_id_warning": _environment_value("media_id_warning"),
        "media_id_expiration": _environment_value("media_id_expiration"),
    }
    if not any(values.values()):
        return

    required = {
        "IH_WECOM_ID": values["corp_id"],
        "IH_WECOM_SECRET": values["secret"],
        "IH_WECOM_AGENT_ID": values["agent_id"],
        "IH_WECOM_TO_USER": values["to_user"],
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise ValueError(f"企业微信 Docker 参数缺少：{', '.join(missing)}")

    channel: dict[str, object] = {
        "type": "wecom",
        "enabled": True,
        "corp_id": values["corp_id"],
        "corp_secret_file": WECOM_SECRET_FILE,
        "agent_id": _parse_int(values["agent_id"] or ""),
        "to_user": values["to_user"],
    }
    for key in (
        "server",
        "content_source_url",
        "name",
        "media_id_download",
        "media_id_startup",
        "media_id_warning",
        "media_id_expiration",
    ):
        if values[key] is not None:
            channel[key] = values[key]

    channels = notifications.setdefault("channels", [])
    if not isinstance(channels, list):
        raise ValueError("YAML notifications.channels 必须是数组")
    channels[:] = [
        item for item in channels if not isinstance(item, dict) or item.get("type") != "wecom"
    ]
    channels.append(channel)


def _environment_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value


def _apply_mapping(
    target: dict[str, Any],
    overrides: tuple[tuple[str, tuple[str, ...], Parser], ...],
) -> None:
    for name, path, parser in overrides:
        raw = _environment_value(name)
        if raw is None:
            continue
        _set_nested(target, path, parser(raw))


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
