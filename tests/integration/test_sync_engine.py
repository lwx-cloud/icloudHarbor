from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from structlog.testing import capture_logs
from tests.conftest import FakeProtocol, make_asset

from icloudharbor.application import HarborApplication
from icloudharbor.config.models import AppConfig
from icloudharbor.notify.base import DeliveryResult, NotificationType
from icloudharbor.observability.paths import display_download_path
from icloudharbor.protocol.models import (
    AssetQuery,
    RemoteAlbum,
    RemoteAsset,
    RemoteLibrary,
    RemoteResource,
)


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
    assert f"正在下载：{target.as_posix()}" in events
    assert not any("下载完成" in event or "已下载到" in event for event in events)


def test_download_log_uses_docker_host_photo_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IH_PHOTOS_PATH", "/volume2/ceshi/icloudharbor")

    path = display_download_path(
        Path("/photos/personal"),
        Path("2021/08/28/IMG_4969.HEIC"),
    )

    assert path == "/volume2/ceshi/icloudharbor/personal/2021/08/28/IMG_4969.HEIC"


def test_missing_recorded_file_is_downloaded_again_to_the_same_path(
    app_config: AppConfig,
) -> None:
    asset, content = make_asset()
    fake = FakeProtocol([asset], content)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    account = app_config.accounts[0]
    target = account.destination.path / "2026/07/29/IMG_0001.JPG"

    first = application.run_sync(account)
    target.unlink()
    second = application.run_sync(account, force_full_scan=True)

    assert first.status == "COMPLETED"
    assert second.status == "COMPLETED"
    assert second.downloaded_count == 1
    assert second.skipped_count == 0
    assert target.read_bytes() == content["resource-1"]
    assert fake.calls.count("open_resource:resource-1") == 2


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


def test_notification_title_is_configurable(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = HarborApplication(app_config, protocol_factory=lambda _: FakeProtocol())
    app_config.notifications.title = "家庭相册"
    titles: list[str] = []

    def send(event: object) -> list[DeliveryResult]:
        titles.append(event.title)  # type: ignore[attr-defined]
        return [DeliveryResult("wecom", True, 200)]

    monkeypatch.setattr(application.notifier, "send", send)

    application.run_sync(app_config.accounts[0])

    assert "家庭相册 同步完成" in titles


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

    result = application.run_sync(account)

    assert result.status == "COMPLETED"
    assert fake.offsets == [4]
    assert partial.with_suffix("").read_bytes() == data


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


def test_album_include_and_exclude_filters_are_applied(app_config: AppConfig) -> None:
    included, included_content = make_asset(
        asset_id="asset-included",
        resource_id="resource-included",
        filename="INCLUDED.JPG",
        data=b"included",
    )
    excluded, excluded_content = make_asset(
        asset_id="asset-excluded",
        resource_id="resource-excluded",
        filename="EXCLUDED.JPG",
        data=b"excluded",
    )

    class AlbumProtocol(FakeProtocol):
        def list_albums(self, library_id: str) -> list[RemoteAlbum]:
            return [
                RemoteAlbum("family-id", library_id, "家庭"),
                RemoteAlbum("excluded-id", library_id, "排除"),
            ]

        def list_assets(self, query: AssetQuery) -> list[RemoteAsset]:
            if query.album_id == "family-id":
                return [included, excluded]
            if query.album_id == "excluded-id":
                return [excluded]
            return [included, excluded]

    fake = AlbumProtocol(content={**included_content, **excluded_content})
    account = app_config.accounts[0]
    account.filters.albums = ["家庭"]
    account.filters.exclude_albums = ["排除"]
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)

    result = application.run_sync(account, force_full_scan=True)

    folder = account.destination.path / "2026/07/29"
    assert result.status == "COMPLETED"
    assert result.downloaded_count == 1
    assert (folder / "INCLUDED.JPG").is_file()
    assert not (folder / "EXCLUDED.JPG").exists()
    library_state = application.repository.library_state(account.id, "root")
    assert library_state is not None
    assert library_state[1] is None


def test_multiple_libraries_are_scanned_in_one_plan(app_config: AppConfig) -> None:
    personal, personal_content = make_asset(
        asset_id="asset-personal",
        resource_id="resource-personal",
        filename="PERSONAL.JPG",
    )
    shared, shared_content = make_asset(
        asset_id="asset-shared",
        resource_id="resource-shared",
        filename="SHARED.JPG",
    )

    class LibraryProtocol(FakeProtocol):
        def list_libraries(self) -> list[RemoteLibrary]:
            return [
                RemoteLibrary("root", "个人图库", "personal"),
                RemoteLibrary("SharedSync", "共享图库", "shared-library"),
            ]

        def list_assets(self, query: AssetQuery) -> list[RemoteAsset]:
            return [personal] if query.library_id == "root" else [shared]

    fake = LibraryProtocol(content={**personal_content, **shared_content})
    account = app_config.accounts[0]
    account.libraries = ["个人图库", "共享图库"]
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)

    result = application.run_sync(account, force_full_scan=True)

    folder = account.destination.path / "2026/07/29"
    assert result.status == "COMPLETED"
    assert result.downloaded_count == 2
    assert (folder / "PERSONAL.JPG").is_file()
    assert (folder / "SHARED.JPG").is_file()


def test_until_found_stops_after_configured_consecutive_existing_assets(
    app_config: AppConfig,
) -> None:
    existing, existing_content = make_asset(
        asset_id="asset-existing",
        resource_id="resource-existing",
        filename="EXISTING.JPG",
    )
    first_new, first_content = make_asset(
        asset_id="asset-new-1",
        resource_id="resource-new-1",
        filename="NEW_1.JPG",
    )
    later_new, later_content = make_asset(
        asset_id="asset-new-2",
        resource_id="resource-new-2",
        filename="NEW_2.JPG",
    )
    fake = FakeProtocol([existing], existing_content)
    account = app_config.accounts[0]
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    application.run_sync(account)
    fake.assets = [first_new, existing, later_new]
    fake.content.update({**first_content, **later_content})
    account.filters.until_found = 1

    result = application.run_sync(account, force_full_scan=True)

    folder = account.destination.path / "2026/07/29"
    assert result.downloaded_count == 1
    assert (folder / "NEW_1.JPG").is_file()
    assert not (folder / "NEW_2.JPG").exists()
    library_state = application.repository.library_state(account.id, "root")
    assert library_state is not None
    assert library_state[1] is None


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
