from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from icloudharbor.config.loader import bootstrap_config, config_snapshot, load_config
from icloudharbor.config.models import AccountConfig, AppConfig, NotificationChannelConfig
from icloudharbor.config.validation import parse_duration, parse_size


def test_human_values() -> None:
    assert parse_size("1MB") == 1_000_000
    assert parse_size("1 MiB") == 1_048_576
    assert parse_duration("30d").days == 30


def test_only_backup_mode_is_accepted(account_config: AccountConfig) -> None:
    payload = account_config.model_dump()
    payload["sync"]["mode"] = "mirror"
    with pytest.raises(ValidationError):
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


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("libraries", ["root", "shared"], "仅支持个人图库"),
        ("filters", {"albums": ["家庭"]}, "尚未实现按相册筛选"),
    ],
)
def test_unimplemented_library_scopes_fail_closed(
    account_config: AccountConfig,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = account_config.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError, match=message):
        AccountConfig.model_validate(payload)


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
    monkeypatch.setenv("IH_DESTINATION", "/photos/docker")
    monkeypatch.setenv("IH_DOWNLOAD_VIDEOS", "false")
    monkeypatch.setenv("IH_FOLDER_STRUCTURE", "{created:%Y/%m}")
    monkeypatch.setenv("IH_SYNC_INTERVAL", "12h")
    monkeypatch.setenv("IH_DOWNLOAD_CONCURRENCY", "4")
    monkeypatch.setenv("IH_NOTIFY_NO_CHANGES", "yes")
    config = load_config(path)

    assert config.runtime.log_level == "DEBUG"
    assert config.runtime.log_format == "json"
    assert config.accounts[0].apple_id == "docker@example.com"
    assert config.accounts[0].region == "china"
    assert config.accounts[0].destination.path == Path("/photos/docker")
    assert config.accounts[0].media.videos is False
    assert config.accounts[0].naming.folder_structure == "{created:%Y/%m}"
    assert config.accounts[0].sync.schedule
    assert config.accounts[0].download.concurrency == 4
    assert config.notifications.no_changes is True


def test_environment_override_rejects_ambiguous_schedule(
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
    monkeypatch.setenv("IH_SCHEDULE", "0 3 * * *")
    monkeypatch.setenv("IH_SYNC_INTERVAL", "12h")

    with pytest.raises(ValueError, match="不能同时设置"):
        load_config(path)


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
    monkeypatch.setenv("media_id_delete", "delete-media")
    monkeypatch.setenv("notification_days", "5")

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
    assert channel.media_id_delete == "delete-media"
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
    monkeypatch.setenv("IH_DESTINATION", "/photos/docker")
    monkeypatch.setenv("IH_DOWNLOAD_VIDEOS", "false")
    monkeypatch.setenv("IH_SYNC_INTERVAL", "12h")

    config, created = bootstrap_config(path)

    assert created is True
    assert path.is_file()
    assert config.accounts[0].apple_id == "docker@example.com"
    assert config.accounts[0].region == "china"
    assert config.accounts[0].destination.path == Path("/photos/docker")
    assert config.accounts[0].media.videos is False
    assert config.accounts[0].sync.schedule


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
    assert config.accounts[0].apple_id == "override@example.com"


def test_bootstrap_config_requires_apple_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IH_APPLE_ID", raising=False)

    with pytest.raises(ValueError, match="IH_APPLE_ID"):
        bootstrap_config(tmp_path / "config.yaml")
