"""Internal protocol-neutral domain models."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import BinaryIO


class AuthStatus(StrEnum):
    UNCONFIGURED = "UNCONFIGURED"
    CREDENTIALS_REQUIRED = "CREDENTIALS_REQUIRED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTHENTICATING = "AUTHENTICATING"
    TWO_FACTOR_REQUIRED = "TWO_FACTOR_REQUIRED"
    SECURITY_KEY_REQUIRED = "SECURITY_KEY_REQUIRED"
    TERMS_REQUIRED = "TERMS_REQUIRED"
    WEB_ACCESS_DISABLED = "WEB_ACCESS_DISABLED"
    ADP_APPROVAL_REQUIRED = "ADP_APPROVAL_REQUIRED"
    AUTH_FAILED = "AUTH_FAILED"
    AUTHENTICATED = "AUTHENTICATED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    REAUTHENTICATION_REQUIRED = "REAUTHENTICATION_REQUIRED"


@dataclass(slots=True, frozen=True)
class Credentials:
    apple_id: str
    password: str | None
    region: str = "auto"


@dataclass(slots=True, frozen=True)
class AuthResult:
    status: AuthStatus
    challenge_id: str | None = None
    message: str | None = None


@dataclass(slots=True, frozen=True)
class RemoteLibrary:
    library_id: str
    name: str
    library_type: str = "personal"


@dataclass(slots=True, frozen=True)
class RemoteAlbum:
    album_id: str
    library_id: str
    name: str
    album_type: str = "album"


@dataclass(slots=True, frozen=True)
class RemoteResource:
    resource_id: str
    asset_id: str
    resource_type: str
    version: str
    filename: str
    size: int | None = None
    mime_type: str | None = None
    checksum: str | None = None
    download_url: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None

    @property
    def idempotency_suffix(self) -> tuple[str, str, str]:
        return (self.asset_id, self.resource_type, self.version)


@dataclass(slots=True, frozen=True)
class RemoteAsset:
    account_id: str
    library_id: str
    asset_id: str
    filename: str
    media_type: str
    created_at: datetime
    added_at: datetime | None = None
    modified_at: datetime | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    favorite: bool = False
    hidden: bool = False
    deleted: bool = False
    resources: tuple[RemoteResource, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict, repr=False)


@dataclass(slots=True, frozen=True)
class AssetQuery:
    account_id: str
    library_id: str
    album_id: str | None = None
    limit: int | None = None


@dataclass(slots=True, frozen=True)
class ChangeBatch:
    assets: tuple[RemoteAsset, ...]
    cursor: str | None
    has_more: bool = False


class ResourceStream:
    """A closeable, protocol-neutral streaming HTTP response."""

    def __init__(
        self,
        source: BinaryIO | Iterator[bytes],
        *,
        status_code: int = 200,
        total_size: int | None = None,
        supports_range: bool = False,
        close_callback: object | None = None,
    ) -> None:
        self.source = source
        self.status_code = status_code
        self.total_size = total_size
        self.supports_range = supports_range
        self._close_callback = close_callback

    def iter_chunks(self, chunk_size: int) -> Iterator[bytes]:
        if hasattr(self.source, "read"):
            while chunk := self.source.read(chunk_size):
                yield chunk
            return
        yield from self.source

    def close(self) -> None:
        callback = self._close_callback
        if callable(callback):
            callback()
        elif hasattr(self.source, "close"):
            self.source.close()

    def __enter__(self) -> ResourceStream:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
