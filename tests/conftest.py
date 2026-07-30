from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest

from icloudharbor.config.models import (
    AccountConfig,
    AppConfig,
    DestinationConfig,
    DownloadConfig,
    NamingConfig,
    RuntimeConfig,
    SyncConfig,
)
from icloudharbor.protocol.base import ICloudProtocol
from icloudharbor.protocol.models import (
    AssetQuery,
    AuthResult,
    AuthStatus,
    ChangeBatch,
    Credentials,
    RemoteAlbum,
    RemoteAsset,
    RemoteLibrary,
    RemoteResource,
    ResourceStream,
)


class FakeProtocol(ICloudProtocol):
    capability_version = "fake/1"

    def __init__(
        self,
        assets: list[RemoteAsset] | None = None,
        content: dict[str, bytes] | None = None,
        *,
        status: AuthStatus = AuthStatus.AUTHENTICATED,
        cursor: str | None = None,
        require_two_factor_on_authenticate: bool = False,
        session_expires_at: datetime | None = None,
    ) -> None:
        self.assets = assets or []
        self.content = content or {}
        self.status = status
        self.cursor = cursor
        self.require_two_factor_on_authenticate = require_two_factor_on_authenticate
        self._session_expires_at = session_expires_at
        self.calls: list[str] = []
        self.offsets: list[int] = []
        self.challenge_id = "fake-challenge"

    def authenticate(self, credentials: Credentials) -> AuthResult:
        self.calls.append("authenticate")
        if self.status == AuthStatus.TWO_FACTOR_REQUIRED or self.require_two_factor_on_authenticate:
            self.status = AuthStatus.TWO_FACTOR_REQUIRED
            return AuthResult(self.status, self.challenge_id, "需要验证码")
        self.status = AuthStatus.AUTHENTICATED
        return AuthResult(self.status, message="认证成功")

    def submit_2fa(self, challenge_id: str, code: str) -> AuthResult:
        self.calls.append("submit_2fa")
        if challenge_id == self.challenge_id and code == "123456":
            self.status = AuthStatus.AUTHENTICATED
            return AuthResult(self.status, message="认证成功")
        return AuthResult(AuthStatus.AUTH_FAILED, message="验证码无效")

    def trust_session(self) -> bool:
        return True

    def auth_status(self) -> AuthStatus:
        return self.status

    def session_expires_at(self) -> datetime | None:
        return self._session_expires_at

    def list_libraries(self) -> list[RemoteLibrary]:
        self.calls.append("list_libraries")
        return [RemoteLibrary("root", "个人图库")]

    def list_albums(self, library_id: str) -> list[RemoteAlbum]:
        return [RemoteAlbum("favorites", library_id, "个人收藏")]

    def list_assets(self, query: AssetQuery) -> list[RemoteAsset]:
        self.calls.append("list_assets")
        return self.assets[: query.limit]

    def get_sync_cursor(self, library_id: str) -> str | None:
        return self.cursor

    def iter_changes(self, library_id: str, cursor: str) -> ChangeBatch:
        self.calls.append("iter_changes")
        return ChangeBatch(tuple(self.assets), self.cursor)

    def open_resource(self, resource: RemoteResource, offset: int = 0) -> ResourceStream:
        self.calls.append(f"open_resource:{resource.resource_id}")
        self.offsets.append(offset)
        data = self.content[resource.resource_id][offset:]
        return ResourceStream(
            io.BytesIO(data),
            status_code=206 if offset else 200,
            total_size=len(data),
            supports_range=bool(offset),
        )

    def logout(self) -> None:
        self.calls.append("logout")
        self.status = AuthStatus.CREDENTIALS_REQUIRED


@pytest.fixture
def account_config(tmp_path: Path) -> AccountConfig:
    destination = tmp_path / "photos"
    destination.mkdir()
    (destination / ".icloudharbor-mounted").touch()
    return AccountConfig(
        id="personal",
        name="测试图库",
        apple_id="user@example.com",
        destination=DestinationConfig(
            path=destination,
            minimum_free_space=0,
        ),
        naming=NamingConfig(folder_structure="{created:%Y/%m/%d}"),
        sync=SyncConfig(full_scan_interval="30d"),
        download=DownloadConfig(
            concurrency=1,
            timeout=10,
            max_retries=0,
        ),
    )


@pytest.fixture
def app_config(tmp_path: Path, account_config: AccountConfig) -> AppConfig:
    return AppConfig(
        version=1,
        runtime=RuntimeConfig(
            timezone="Asia/Shanghai",
            database=tmp_path / "config" / "database" / "icloudharbor.db",
            temp_path=tmp_path / "config" / "tmp",
        ),
        accounts=[account_config],
    )


def make_asset(
    *,
    asset_id: str = "asset-A1B2C3D4",
    filename: str = "IMG_0001.JPG",
    resource_id: str = "resource-1",
    resource_type: str = "photo_original",
    version: str = "original",
    data: bytes = b"test-photo-content",
    media_type: str = "photo",
    resources: tuple[RemoteResource, ...] | None = None,
) -> tuple[RemoteAsset, dict[str, bytes]]:
    if resources is None:
        resources = (
            RemoteResource(
                resource_id=resource_id,
                asset_id=asset_id,
                resource_type=resource_type,
                version=version,
                filename=filename,
                size=len(data),
                mime_type="image/jpeg",
            ),
        )
    asset = RemoteAsset(
        account_id="personal",
        library_id="root",
        asset_id=asset_id,
        filename=filename,
        media_type=media_type,
        created_at=datetime(2026, 7, 29, 3, 0, tzinfo=UTC),
        resources=resources,
    )
    content = {
        resource.resource_id: (
            data if resource.resource_id == resource_id else b"companion-content"
        )
        for resource in resources
    }
    return asset, content
