from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from structlog.testing import capture_logs
from tests.conftest import FakeProtocol, make_asset

from icloudharbor.application import HarborApplication
from icloudharbor.config.models import AppConfig
from icloudharbor.notify.base import DeliveryResult, NotificationType
from icloudharbor.protocol.models import RemoteResource


def test_first_run_downloads_and_second_run_is_idempotent(
    app_config: AppConfig,
) -> None:
    asset, content = make_asset()
    fake = FakeProtocol([asset], content)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    account = app_config.accounts[0]

    with capture_logs() as logs:
        first = application.run_sync(account)
        second = application.run_sync(account, force_full_scan=True)

    target = account.destination.path / "2026/07/29/IMG_0001.JPG"
    assert first.status == "COMPLETED"
    assert first.downloaded_count == 1
    assert target.read_bytes() == content["resource-1"]
    assert second.downloaded_count == 0
    assert second.skipped_count == 1
    assert fake.calls.count("open_resource:resource-1") == 1
    events = [entry["event"] for entry in logs]
    assert "download_started" in events
    assert "download_completed" in events
    assert "delete_disabled" in events
    assert next(entry for entry in logs if entry["event"] == "download_started")["file"] == (
        "2026/07/29/IMG_0001.JPG"
    )


def test_auth_expiration_notification_is_sent_at_most_once_per_day(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProtocol(session_expires_at=datetime.now(UTC) + timedelta(days=2))
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    events: list[NotificationType] = []

    def send(event: object) -> list[DeliveryResult]:
        events.append(event.type)  # type: ignore[attr-defined]
        return [DeliveryResult("wecom", True, 200)]

    monkeypatch.setattr(application.notifier, "send", send)

    application.run_sync(app_config.accounts[0])
    application.run_sync(app_config.accounts[0], force_full_scan=True)

    assert events.count(NotificationType.AUTH_EXPIRING) == 1
    assert events.count(NotificationType.SYNC_COMPLETED) == 2


def test_dry_run_does_not_create_formal_or_partial_file(
    app_config: AppConfig,
) -> None:
    asset, content = make_asset()
    fake = FakeProtocol([asset], content)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)

    result = application.run_sync(app_config.accounts[0], dry_run=True)

    assert result.status == "DRY_RUN"
    assert result.plan.download_count == 1
    assert not list(app_config.accounts[0].destination.path.rglob("*.JPG"))
    assert not list(app_config.accounts[0].destination.path.rglob("*.part"))


def test_missing_mount_marker_stops_before_remote_scan(app_config: AppConfig) -> None:
    account = app_config.accounts[0]
    (account.destination.path / account.destination.mounted_marker).unlink()
    asset, content = make_asset()
    fake = FakeProtocol([asset], content)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)

    result = application.run_sync(account)

    assert result.status == "FAILED"
    assert result.error_code == "MOUNT_MISSING"
    assert "list_libraries" not in fake.calls


def test_plan_stops_when_download_would_exhaust_space(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FullDisk:
        free = 0

    monkeypatch.setattr(
        "icloudharbor.photos.engine.shutil.disk_usage",
        lambda _: FullDisk(),
    )
    asset, content = make_asset()
    fake = FakeProtocol([asset], content)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)

    result = application.run_sync(app_config.accounts[0])

    assert result.status == "FAILED"
    assert result.error_code == "STORAGE_FULL"
    assert not any(call.startswith("open_resource:") for call in fake.calls)


def test_partial_file_resumes_with_range(app_config: AppConfig) -> None:
    data = b"abcdefghij"
    asset, content = make_asset(data=data)
    fake = FakeProtocol([asset], content)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    account = app_config.accounts[0]
    partial = account.destination.path / "2026/07/29/IMG_0001.JPG.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(data[:4])

    with capture_logs() as logs:
        result = application.run_sync(account)

    assert result.status == "COMPLETED"
    assert fake.offsets == [4]
    assert partial.with_suffix("").read_bytes() == data
    assert (
        next(entry for entry in logs if entry["event"] == "download_resumed")["offset_bytes"] == 4
    )


def test_same_remote_filename_does_not_overwrite(app_config: AppConfig) -> None:
    first, first_content = make_asset(
        asset_id="asset-AAA11111",
        resource_id="resource-a",
        data=b"first",
    )
    second, second_content = make_asset(
        asset_id="asset-BBB22222",
        resource_id="resource-b",
        data=b"second",
    )
    content = {**first_content, **second_content}
    fake = FakeProtocol([first, second], content)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)

    result = application.run_sync(app_config.accounts[0])

    folder = app_config.accounts[0].destination.path / "2026/07/29"
    assert result.downloaded_count == 2
    assert (folder / "IMG_0001.JPG").read_bytes() == b"first"
    assert (folder / "IMG_0001_BBB22222.JPG").read_bytes() == b"second"


def test_live_photo_is_complete_only_after_both_resources_download(
    app_config: AppConfig,
) -> None:
    resources = (
        RemoteResource(
            "live-image",
            "asset-live",
            "live_photo_image",
            "live_image",
            "IMG_0002.HEIC",
            size=17,
        ),
        RemoteResource(
            "live-video",
            "asset-live",
            "live_photo_video",
            "live_video",
            "IMG_0002.MOV",
            size=17,
        ),
    )
    asset, _ = make_asset(
        asset_id="asset-live",
        resource_id="unused",
        filename="IMG_0002.HEIC",
        resources=resources,
    )
    content = {"live-image": b"companion-content", "live-video": b"companion-content"}
    fake = FakeProtocol([asset], content)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)

    result = application.run_sync(app_config.accounts[0])

    assert result.status == "COMPLETED"
    assert result.downloaded_count == 2
    folder = app_config.accounts[0].destination.path / "2026/07/29"
    assert (folder / "IMG_0002.HEIC").is_file()
    assert (folder / "IMG_0002.MOV").is_file()
