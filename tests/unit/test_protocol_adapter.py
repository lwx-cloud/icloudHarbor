from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import ClassVar

import pytest

from icloudharbor.protocol.exceptions import (
    AuthenticationRequired,
    CursorInvalid,
    ErrorCode,
    ProtocolError,
)
from icloudharbor.protocol.models import AssetQuery, AuthStatus, Credentials, RemoteResource
from icloudharbor.protocol.pyicloud_adapter import PyicloudProtocolAdapter


class DummyAsset:
    id = "asset-123"
    filename = "IMG_0001.HEIC"
    asset_date = datetime(2026, 7, 29, tzinfo=UTC)
    added_date = asset_date
    modified = asset_date
    is_favorite = True
    is_hidden = False
    width = 4032
    height = 3024
    duration = None
    item_type = "image"
    is_live_photo = True
    versions: ClassVar[dict[str, dict[str, object]]] = {
        "original": {
            "filename": "IMG_0001.HEIC",
            "url": "https://example.test/signed",
            "size": 123,
            "type": "image/heic",
        },
        "live_video": {
            "filename": "IMG_0001.MOV",
            "url": "https://example.test/live",
            "size": 456,
            "type": "video/quicktime",
        },
        "alternative": {
            "filename": "IMG_0001.JPG",
            "url": "https://example.test/jpeg",
            "size": 100,
            "type": "image/jpeg",
        },
    }

    def download(self, version: str) -> bytes:
        return f"download:{version}".encode()


class DummyLibrary:
    def __init__(self) -> None:
        self.all = [DummyAsset()]
        self.events: list[object] = []

    def iter_changes(self, *, since: str) -> object:
        assert since == "cursor-1"
        return iter(self.events)

    def sync_cursor(self) -> str:
        return "cursor-2"


class DummyAlbum:
    id = "album-1"

    def __iter__(self) -> Iterator[DummyAsset]:
        yield DummyAsset()


class DummyPhotos:
    def __init__(self) -> None:
        self.all = [DummyAsset()]
        self.libraries = {"root": DummyLibrary()}
        self.albums = {"家庭": DummyAlbum()}


class DummyApi:
    requires_2fa = False
    requires_2sa = False

    def __init__(self) -> None:
        self.photos = DummyPhotos()
        self.session = DummySession()


class DummyResponse:
    status_code = 206
    headers: ClassVar[dict[str, str]] = {
        "Content-Length": "4",
        "Accept-Ranges": "bytes",
    }

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        assert chunk_size > 0
        yield b"data"

    def close(self) -> None:
        return None


class DummySession:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, object] = {}

    def get(self, *_: object, **kwargs: object) -> DummyResponse:
        self.last_kwargs = kwargs
        return DummyResponse()


def install_fake_pyicloud(
    monkeypatch: pytest.MonkeyPatch,
    *,
    requires_2fa: bool = False,
    delivery_method: str = "unknown",
    trusted_session: bool | None = None,
    private_requires_mfa: bool = False,
    trust_result: bool = True,
) -> type[object]:
    class FakeService:
        requires_2sa = False
        last_kwargs: ClassVar[dict[str, object]] = {}

        def __init__(self, *_: object, **kwargs: object) -> None:
            type(self).last_kwargs = kwargs
            self.requires_2fa = requires_2fa
            self.two_factor_delivery_method = delivery_method
            self.is_trusted_session = (
                trusted_session
                if trusted_session is not None
                else not requires_2fa and delivery_method == "unknown"
            )
            self._requires_mfa = private_requires_mfa
            self._password_raw = "secret"
            self.trusted = False

        def validate_2fa_code(self, code: str) -> bool:
            return code == "123456"

        def trust_session(self) -> bool:
            self.trusted = True
            if trust_result:
                self.is_trusted_session = True
                self._requires_mfa = False
            return trust_result

    module = ModuleType("pyicloud")
    module.PyiCloudService = FakeService  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyicloud", module)
    return FakeService


def test_adapter_normalizes_without_leaking_pyicloud_types(tmp_path: Path) -> None:
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")
    asset = adapter._normalize_asset(AssetQuery("personal", "root"), DummyAsset())
    assert asset.asset_id == "asset-123"
    assert asset.favorite is True
    assert {resource.resource_type for resource in asset.resources} == {
        "live_photo_image",
        "live_photo_video",
        "jpeg_alternative",
    }


def test_adapter_uses_cursor_to_short_circuit_unchanged_library(
    tmp_path: Path,
) -> None:
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions", "personal")
    adapter._api = DummyApi()

    batch = adapter.iter_changes("root", "cursor-1")

    assert batch.assets == ()
    assert batch.cursor == "cursor-2"


def test_adapter_reconciles_assets_when_cursor_has_changes(tmp_path: Path) -> None:
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions", "personal")
    api = DummyApi()
    api.photos.libraries["root"].events.append(object())
    adapter._api = api

    batch = adapter.iter_changes("root", "cursor-1")

    assert len(batch.assets) == 1
    assert batch.assets[0].account_id == "personal"
    assert adapter.get_sync_cursor("root") == "cursor-2"


def test_adapter_lists_albums_and_streams_signed_resource(tmp_path: Path) -> None:
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions", download_timeout=42)
    adapter._api = DummyApi()
    resource = RemoteResource(
        "r1",
        "asset-123",
        "photo_original",
        "original",
        "IMG.JPG",
        download_url="https://example.test/signed",
    )

    albums = adapter.list_albums("root")
    with adapter.open_resource(resource, offset=2) as stream:
        body = b"".join(stream.iter_chunks(1024))

    assert albums[0].name == "家庭"
    assert body == b"data"
    assert stream.supports_range is True
    assert adapter._api.session.last_kwargs["timeout"] == 42


def test_adapter_reads_trusted_session_cookie_expiration(tmp_path: Path) -> None:
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions", "personal")
    adapter._api = DummyApi()
    expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=6)
    adapter._api.session.cookies = [
        SimpleNamespace(
            name="X-APPLE-WEBAUTH-USER",
            expires=int(expires_at.timestamp()),
        )
    ]

    assert adapter.session_expires_at() == expires_at


def test_adapter_lists_libraries_and_album_assets_with_limit(tmp_path: Path) -> None:
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions", "personal")
    adapter._api = DummyApi()

    libraries = adapter.list_libraries()
    assets = adapter.list_assets(AssetQuery("personal", "root", album_id="家庭", limit=1))

    assert libraries[0].library_id == "root"
    assert [asset.asset_id for asset in assets] == ["asset-123"]
    assert adapter.list_assets(AssetQuery("personal", "shared")) == []


def test_adapter_requires_authentication_and_classifies_runtime_states(tmp_path: Path) -> None:
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")
    with pytest.raises(AuthenticationRequired):
        adapter.list_libraries()

    api = DummyApi()
    adapter._api = api
    api.requires_2fa = True
    assert adapter.auth_status() == AuthStatus.TWO_FACTOR_REQUIRED
    api.requires_2fa = False
    api.requires_2sa = True
    assert adapter.auth_status() == AuthStatus.SECURITY_KEY_REQUIRED


def test_adapter_rejects_missing_cursor_library(tmp_path: Path) -> None:
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")
    adapter._api = DummyApi()

    assert adapter.get_sync_cursor("missing") is None
    with pytest.raises(CursorInvalid):
        adapter.iter_changes("missing", "cursor-1")


def test_adapter_can_fall_back_to_asset_download_bytes(tmp_path: Path) -> None:
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")
    adapter._api = DummyApi()
    adapter._asset_versions[("asset-123", "original")] = DummyAsset()
    resource = RemoteResource("r1", "asset-123", "photo_original", "original", "IMG.JPG")

    with adapter.open_resource(resource) as stream:
        assert b"".join(stream.iter_chunks(1024)) == b"download:original"


def test_adapter_falls_back_to_generic_original_resource(tmp_path: Path) -> None:
    class EmptyVersionsAsset:
        id = "asset-empty"
        filename = "CLIP.MOV"
        asset_date = datetime(2026, 7, 29, tzinfo=UTC)
        versions: ClassVar[dict[str, object]] = {}

    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")
    asset = adapter._normalize_asset(
        AssetQuery("personal", "root"),
        EmptyVersionsAsset(),
    )

    assert asset.media_type == "video"
    assert asset.resources[0].resource_type == "video_original"


def test_expired_signed_url_is_refreshed(tmp_path: Path) -> None:
    class ExpiredResponse(DummyResponse):
        status_code = 403

    class FreshAsset(DummyAsset):
        versions: ClassVar[dict[str, dict[str, object]]] = {
            "original": {
                "filename": "IMG.JPG",
                "url": "https://example.test/fresh",
            }
        }

    class RefreshAlbum:
        def get(self, asset_id: str) -> FreshAsset | None:
            return FreshAsset() if asset_id == "asset-123" else None

        def __iter__(self) -> Iterator[FreshAsset]:
            yield FreshAsset()

    class RefreshSession:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, **__: object) -> DummyResponse:
            self.urls.append(url)
            return ExpiredResponse() if url.endswith("/expired") else DummyResponse()

    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")
    api = DummyApi()
    api.session = RefreshSession()
    api.photos.all = RefreshAlbum()
    adapter._api = api
    resource = RemoteResource(
        "r1",
        "asset-123",
        "photo_original",
        "original",
        "IMG.JPG",
        download_url="https://example.test/expired",
    )

    with adapter.open_resource(resource) as stream:
        body = b"".join(stream.iter_chunks(1024))

    assert body == b"data"
    assert api.session.urls == [
        "https://example.test/expired",
        "https://example.test/fresh",
    ]


def test_authentication_and_two_factor_do_not_retain_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_pyicloud(monkeypatch, requires_2fa=True)
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")

    challenge = adapter.authenticate(Credentials("user@example.com", "secret", region="global"))
    verified = adapter.submit_2fa(challenge.challenge_id or "", "123456")

    assert challenge.status == AuthStatus.TWO_FACTOR_REQUIRED
    assert verified.status == AuthStatus.AUTHENTICATED
    assert adapter._api._password_raw is None


def test_authentication_detects_active_delivery_when_pyicloud_flag_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_pyicloud(
        monkeypatch,
        requires_2fa=False,
        delivery_method="trusted_device",
        trusted_session=False,
    )
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")

    challenge = adapter.authenticate(Credentials("user@example.com", "secret"))

    assert challenge.status == AuthStatus.TWO_FACTOR_REQUIRED
    assert challenge.challenge_id
    assert adapter.auth_status() == AuthStatus.TWO_FACTOR_REQUIRED


def test_authentication_detects_internal_mfa_when_hsa_version_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_pyicloud(
        monkeypatch,
        requires_2fa=False,
        delivery_method="unknown",
        trusted_session=False,
        private_requires_mfa=True,
    )
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")

    challenge = adapter.authenticate(Credentials("user@example.com", "secret"))
    verified = adapter.submit_2fa(challenge.challenge_id or "", "123456")

    assert challenge.status == AuthStatus.TWO_FACTOR_REQUIRED
    assert verified.status == AuthStatus.AUTHENTICATED


def test_two_factor_does_not_report_success_when_session_trust_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_pyicloud(
        monkeypatch,
        requires_2fa=True,
        trusted_session=False,
        trust_result=False,
    )
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")

    challenge = adapter.authenticate(Credentials("user@example.com", "secret"))
    verified = adapter.submit_2fa(challenge.challenge_id or "", "123456")

    assert verified.status == AuthStatus.AUTH_FAILED
    assert "受信任会话" in (verified.message or "")


@pytest.mark.parametrize(
    ("region", "expected"),
    [("auto", None), ("global", False), ("china", True)],
)
def test_authentication_maps_region_without_guessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    region: str,
    expected: bool | None,
) -> None:
    service = install_fake_pyicloud(monkeypatch)
    adapter = PyicloudProtocolAdapter(tmp_path / region)

    adapter.authenticate(Credentials("user@example.com", "secret", region=region))

    assert service.last_kwargs["china_mainland"] is expected


def test_authentication_auto_detects_china_from_persisted_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = install_fake_pyicloud(monkeypatch)
    session_directory = tmp_path / "auto"
    session_directory.mkdir()
    (session_directory / "account.session").write_text(
        '{"account_country": "CHN"}',
        encoding="utf-8",
    )
    adapter = PyicloudProtocolAdapter(session_directory)

    adapter.authenticate(Credentials("user@example.com", "secret", region="auto"))

    assert service.last_kwargs["china_mainland"] is True


def test_security_key_challenge_is_classified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_pyicloud(
        monkeypatch,
        requires_2fa=True,
        delivery_method="security_key",
    )
    adapter = PyicloudProtocolAdapter(tmp_path / "sessions")

    result = adapter.authenticate(Credentials("user@example.com", "secret"))

    assert result.status == AuthStatus.SECURITY_KEY_REQUIRED


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("accept new terms", ErrorCode.TERMS_REQUIRED),
        ("web access disabled", ErrorCode.WEB_ACCESS_DISABLED),
        ("advanced data protection approval", ErrorCode.ADP_APPROVAL_REQUIRED),
        ("password invalid", ErrorCode.AUTH_ERROR),
        ("request timed out", ErrorCode.NETWORK_TIMEOUT),
    ],
)
def test_protocol_errors_are_stable(
    message: str,
    code: ErrorCode,
) -> None:
    error = PyicloudProtocolAdapter._map_exception(Exception(message))
    assert isinstance(error, ProtocolError)
    assert error.code == code


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, ErrorCode.AUTH_ERROR),
        (403, ErrorCode.ACCESS_DENIED),
        (404, ErrorCode.REMOTE_NOT_FOUND),
        (429, ErrorCode.RATE_LIMITED),
        (503, ErrorCode.SERVICE_UNAVAILABLE),
    ],
)
def test_http_protocol_errors_are_stable(status: int, code: ErrorCode) -> None:
    class HttpError(Exception):
        def __init__(self) -> None:
            self.response = type("Response", (), {"status_code": status})()

    assert PyicloudProtocolAdapter._map_exception(HttpError()).code == code


def test_logout_removes_only_session_files(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions"
    adapter = PyicloudProtocolAdapter(session_dir)
    (session_dir / "cookie").write_text("secret", encoding="utf-8")

    adapter.logout()

    assert list(session_dir.iterdir()) == []
