from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from icloudharbor.config.loader import bootstrap_config, config_snapshot, load_config
from icloudharbor.config.models import (
    AccountConfig,
    AppConfig,
    NotificationChannelConfig,
    ScheduleConfig,
)
from icloudharbor.config.validation import parse_duration, parse_file_mode, parse_size


def test_human_values() -> None:
    assert parse_size("1MB") == 1_000_000
    assert parse_size("1 MiB") == 1_048_576
    assert parse_duration("30d").days == 30
    assert parse_file_mode("0750") == 0o750
    assert parse_file_mode("0o640") == 0o640


def test_config_snapshot_keeps_permission_modes_human_readable(
    app_config: AppConfig,
) -> None:
    destination = app_config.accounts[0].destination
    destination.directory_permissions = 0o750
    destination.file_permissions = 0o640

    snapshot = config_snapshot(app_config)

    assert "directory_permissions: '0750'" in snapshot
    assert "file_permissions: '0640'" in snapshot
    assert AppConfig.model_validate(yaml.safe_load(snapshot)) == app_config


def test_only_backup_mode_is_accepted(account_config: AccountConfig) -> None:
    payload = account_config.model_dump()
    payload["sync"]["mode"] = "mirror"
    with pytest.raises(ValidationError):
        AccountConfig.model_validate(payload)


def test_account_id_accepts_apple_account_email(account_config: AccountConfig) -> None:
    payload = account_config.model_dump()
    payload["id"] = "photos+archive@example.com"

    configured = AccountConfig.model_validate(payload)

    assert configured.id == "photos+archive@example.com"


@pytest.mark.parametrize(
    "account_id",
    ["../escape", "nested/account", "nested\\account", "bad:name", "bad account"],
)
def test_account_id_rejects_unsafe_path_characters(
    account_config: AccountConfig,
    account_id: str,
) -> None:
    payload = account_config.model_dump()
    payload["id"] = account_id

    with pytest.raises(ValidationError, match="安全的文件名"):
        AccountConfig.model_validate(payload)


def test_account_id_rejects_values_too_long_for_internal_paths(
    account_config: AccountConfig,
) -> None:
    payload = account_config.model_dump()
    payload["id"] = "a" * 221

    with pytest.raises(ValidationError, match="220"):
        AccountConfig.model_validate(payload)


@pytest.mark.parametrize(
    "apple_id",
    ["two@@example.com", "has space@example.com", f"{'a' * 210}@example.com"],
)
def test_apple_id_rejects_unsafe_or_oversized_values(
    account_config: AccountConfig,
    apple_id: str,
) -> None:
    payload = account_config.model_dump()
    payload["apple_id"] = apple_id

    with pytest.raises(ValidationError, match="apple_id 格式无效"):
        AccountConfig.model_validate(payload)


def test_unimplemented_session_encryption_fails_closed(
    account_config: AccountConfig,
) -> None:
    with pytest.raises(ValidationError, match="尚未实现 Session 加密"):
        AppConfig.model_validate(
            {
                "version": 1,
                "accounts": [account_config.model_dump(mode="json")],
                "security": {"session_encryption": True},
            }
        )


def test_library_and_album_scopes_are_configurable(account_config: AccountConfig) -> None:
    payload = account_config.model_dump(mode="json")
    payload["libraries"] = ["root", "SharedSync"]
    payload["filters"] = {
        "albums": ["家庭"],
        "exclude_albums": ["截图"],
        "recent_only": 500,
        "until_found": 20,
    }

    configured = AccountConfig.model_validate(payload)

    assert configured.libraries == ["root", "SharedSync"]
    assert configured.filters.albums == ["家庭"]
    assert configured.filters.exclude_albums == ["截图"]
    assert configured.filters.recent_only == 500
    assert configured.filters.until_found == 20


def test_v01_requires_exactly_one_enabled_account(account_config: AccountConfig) -> None:
    disabled = account_config.model_copy(update={"enabled": False})
    with pytest.raises(ValidationError, match="只能启用一个账号"):
        AppConfig(version=1, accounts=[disabled])


@pytest.mark.parametrize("channel_type", ["bark", "serverchan", "telegram", "wecom", "webhook"])
def test_enabled_notification_channels_require_credentials(channel_type: str) -> None:
    with pytest.raises(ValidationError):
        NotificationChannelConfig(type=channel_type)


def test_environment_override_supports_common_docker_parameters(
    tmp_path: Path,
    account_config: AccountConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.yaml"
    payload = {
        "version": 1,
        "runtime": {
            "database": str(tmp_path / "state.db"),
            "temp_path": str(tmp_path / "tmp"),
        },
        "accounts": [account_config.model_dump(mode="json")],
    }
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    monkeypatch.setenv("IH_LOG_LEVEL", "debug")
    monkeypatch.setenv("IH_LOG_FORMAT", "JSON")
    monkeypatch.setenv("IH_APPLE_ID", "docker@example.com")
    monkeypatch.setenv("IH_REGION", "china")
    monkeypatch.setenv("IH_LIBRARIES", "root,SharedSync")
    monkeypatch.setenv("IH_DIRECTORY_PERMISSIONS", "0750")
    monkeypatch.setenv("IH_FILE_PERMISSIONS", "0640")
    monkeypatch.setenv("IH_SYNOLOGY_PHOTOS_APP_FIX", "true")
    monkeypatch.setenv("IH_DOWNLOAD_VIDEOS", "false")
    monkeypatch.setenv("IH_PHOTO_SIZE", "original,adjusted")
    monkeypatch.setenv("IH_LIVE_PHOTO_SIZE", "thumb")
    monkeypatch.setenv("IH_CONVERT_HEIC_TO_JPEG", "true")
    monkeypatch.setenv("IH_JPEG_PATH", "/photos/jpeg")
    monkeypatch.setenv("IH_JPEG_QUALITY", "85")
    monkeypatch.setenv("IH_ALBUMS", "家庭,旅行")
    monkeypatch.setenv("IH_EXCLUDE_ALBUMS", "截图")
    monkeypatch.setenv("IH_RECENT_ONLY", "500")
    monkeypatch.setenv("IH_UNTIL_FOUND", "20")
    monkeypatch.setenv("IH_FOLDER_STRUCTURE", "{created:%Y/%m}")
    monkeypatch.setenv("IH_SYNC_INTERVAL", "12")
    monkeypatch.setenv("IH_DOWNLOAD_DELAY", "15")
    monkeypatch.setenv("IH_DOWNLOAD_CONCURRENCY", "4")
    monkeypatch.setenv("IH_NOTIFICATION_TITLE", "家庭 iCloud")
    monkeypatch.setenv("IH_SILENT_NOTIFICATIONS", "true")
    monkeypatch.setenv("IH_NOTIFY_FAILURE", "yes")
    config = load_config(path)

    assert config.runtime.log_level == "DEBUG"
    assert config.runtime.log_format == "json"
    assert config.accounts[0].id == "docker@example.com"
    assert config.accounts[0].apple_id == "docker@example.com"
    assert config.accounts[0].region == "china"
    assert config.accounts[0].libraries == ["root", "SharedSync"]
    assert config.accounts[0].destination.path == account_config.destination.path
    assert config.accounts[0].destination.directory_permissions == 0o750
    assert config.accounts[0].destination.file_permissions == 0o640
    assert config.accounts[0].destination.synology_photos_app_fix is True
    assert config.accounts[0].media.videos is False
    assert config.accounts[0].media.photo_size == ["original", "adjusted"]
    assert config.accounts[0].media.live_photo_size == "thumb"
    assert config.accounts[0].media.convert_heic_to_jpeg is True
    assert config.accounts[0].media.jpeg_path == Path("/photos/jpeg")
    assert config.accounts[0].media.jpeg_quality == 85
    assert config.accounts[0].filters.albums == ["家庭", "旅行"]
    assert config.accounts[0].filters.exclude_albums == ["截图"]
    assert config.accounts[0].filters.recent_only == 500
    assert config.accounts[0].filters.until_found == 20
    assert config.accounts[0].naming.folder_structure == "{created:%Y/%m}"
    assert config.accounts[0].sync.schedule == ScheduleConfig(interval="12h")
    assert config.accounts[0].sync.download_delay == 15
    assert config.accounts[0].download.concurrency == 4
    assert config.notifications.title == "家庭 iCloud"
    assert config.notifications.silent is True
    assert config.notifications.failure is True


def test_environment_override_builds_wecom_channel_without_persisting_secret(
    tmp_path: Path,
    account_config: AccountConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "accounts": [account_config.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IH_WECOM_ID", "ww123456")
    monkeypatch.setenv("IH_WECOM_SECRET", "must-not-enter-config")
    monkeypatch.setenv("IH_WECOM_AGENT_ID", "1000001")
    monkeypatch.setenv("IH_WECOM_TO_USER", "@all")
    monkeypatch.setenv("IH_WECOM_PROXY", "https://qyapi.weixin.qq.com")
    monkeypatch.setenv("IH_WECOM_NAME", "iCloudHarbor")
    monkeypatch.setenv("media_id_download", "download-media")
    monkeypatch.setenv("media_id_startup", "startup-media")
    monkeypatch.setenv("media_id_warning", "warning-media")
    monkeypatch.setenv("media_id_expiration", "expiration-media")
    monkeypatch.setenv("IH_NOTIFICATION_DAYS", "5")

    config = load_config(path)

    channel = config.notifications.channels[0]
    assert channel.type == "wecom"
    assert channel.corp_id == "ww123456"
    assert channel.agent_id == 1000001
    assert channel.to_user == "@all"
    assert channel.corp_secret_file == Path("/config/notification-keys/wecom-secret")
    assert channel.media_id_download == "download-media"
    assert channel.media_id_startup == "startup-media"
    assert channel.media_id_warning == "warning-media"
    assert channel.media_id_expiration == "expiration-media"
    assert config.notifications.notification_days == 5
    assert "must-not-enter-config" not in config_snapshot(config)


def test_environment_override_requires_complete_wecom_credentials(
    tmp_path: Path,
    account_config: AccountConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "accounts": [account_config.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IH_WECOM_ID", "ww123456")

    with pytest.raises(ValueError, match="IH_WECOM_SECRET"):
        load_config(path)


def test_environment_override_rejects_invalid_boolean(
    tmp_path: Path,
    account_config: AccountConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "accounts": [account_config.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IH_RUN_ON_START", "sometimes")

    with pytest.raises(ValueError, match="布尔环境变量"):
        load_config(path)


def test_bootstrap_config_generates_initial_yaml_from_docker_parameters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("IH_APPLE_ID", "docker@example.com")
    monkeypatch.setenv("IH_REGION", "china")
    monkeypatch.setenv("IH_DOWNLOAD_VIDEOS", "false")
    monkeypatch.setenv("IH_SYNC_INTERVAL", "12")

    config, created = bootstrap_config(path)

    assert created is True
    assert path.is_file()
    assert config.accounts[0].id == "docker@example.com"
    assert config.accounts[0].apple_id == "docker@example.com"
    assert config.accounts[0].region == "china"
    assert config.accounts[0].destination.path == Path("/photos")
    assert config.accounts[0].media.videos is False
    assert config.accounts[0].sync.schedule == ScheduleConfig(interval="12h")
    assert config.accounts[0].sync.run_on_start is True
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["accounts"][0]["id"] == (
        "docker@example.com"
    )


def test_explicit_account_id_overrides_apple_id_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IH_APPLE_ID", "docker@example.com")
    monkeypatch.setenv("IH_ACCOUNT_ID", "family-archive")

    config, _ = bootstrap_config(tmp_path / "config.yaml")

    assert config.accounts[0].id == "family-archive"
    assert config.accounts[0].apple_id == "docker@example.com"


def test_bootstrap_defaults_to_24_hour_interval_and_startup_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IH_APPLE_ID", "docker@example.com")

    config, _ = bootstrap_config(tmp_path / "config.yaml")

    assert config.accounts[0].sync.schedule == ScheduleConfig(interval="24h")
    assert config.accounts[0].sync.run_on_start is True


def test_bootstrap_config_never_overwrites_existing_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("IH_APPLE_ID", "first@example.com")
    bootstrap_config(path)
    original = path.read_bytes()
    monkeypatch.setenv("IH_APPLE_ID", "override@example.com")

    config, created = bootstrap_config(path)

    assert created is False
    assert path.read_bytes() == original
    assert config.accounts[0].id == "override@example.com"
    assert config.accounts[0].apple_id == "override@example.com"


def test_bootstrap_config_requires_apple_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IH_APPLE_ID", raising=False)

    with pytest.raises(ValueError, match="IH_APPLE_ID"):
        bootstrap_config(tmp_path / "config.yaml")


def test_removed_yaml_keys_are_rejected(
    tmp_path: Path,
    account_config: AccountConfig,
) -> None:
    path = tmp_path / "config.yaml"
    payload = account_config.model_dump(mode="json")
    payload["media"]["photo_version"] = "both"
    path.write_text(
        yaml.safe_dump({"version": 1, "accounts": [payload]}),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="photo_version"):
        load_config(path)


@pytest.mark.parametrize("hours", [6, 12, 24])
def test_sync_interval_plain_number_means_hours(
    tmp_path: Path,
    account_config: AccountConfig,
    monkeypatch: pytest.MonkeyPatch,
    hours: int,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "accounts": [account_config.model_dump(mode="json")]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("IH_SYNC_INTERVAL", str(hours))

    config = load_config(path)

    assert config.accounts[0].sync.schedule == ScheduleConfig(interval=f"{hours}h")


@pytest.mark.parametrize("value", ["0", "1", "8", "36", "168", "12h", "1.5", "often"])
def test_sync_interval_rejects_values_outside_supported_choices(
    tmp_path: Path,
    account_config: AccountConfig,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"version": 1, "accounts": [account_config.model_dump(mode="json")]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("IH_SYNC_INTERVAL", value)

    with pytest.raises(ValueError, match="IH_SYNC_INTERVAL"):
        load_config(path)


def test_explicit_run_on_start_false_is_preserved(
    tmp_path: Path,
    account_config: AccountConfig,
) -> None:
    path = tmp_path / "config.yaml"
    payload = account_config.model_dump(mode="json")
    payload["sync"]["run_on_start"] = False
    path.write_text(
        yaml.safe_dump({"version": 1, "accounts": [payload]}),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.accounts[0].sync.run_on_start is False


def test_schedule_string_accepts_duration_form(
    tmp_path: Path,
    account_config: AccountConfig,
) -> None:
    path = tmp_path / "config.yaml"
    payload = account_config.model_dump(mode="json")
    payload["sync"]["schedule"] = "6h"
    path.write_text(
        yaml.safe_dump({"version": 1, "accounts": [payload]}),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.accounts[0].sync.schedule == ScheduleConfig(interval="6h")
