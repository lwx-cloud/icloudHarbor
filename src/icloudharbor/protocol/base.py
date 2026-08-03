"""The only Apple/iCloud interface visible to business code."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

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


class ICloudProtocol(ABC):
    capability_version = "icloudharbor-protocol/1"

    @abstractmethod
    def authenticate(self, credentials: Credentials) -> AuthResult: ...

    @abstractmethod
    def submit_2fa(self, challenge_id: str, code: str) -> AuthResult: ...

    @abstractmethod
    def trust_session(self) -> bool: ...

    @abstractmethod
    def auth_status(self) -> AuthStatus: ...

    @abstractmethod
    def session_expires_at(self) -> datetime | None: ...

    @abstractmethod
    def list_libraries(self) -> list[RemoteLibrary]: ...

    @abstractmethod
    def list_albums(self, library_id: str) -> list[RemoteAlbum]: ...

    @abstractmethod
    def list_assets(self, query: AssetQuery) -> list[RemoteAsset]: ...

    @abstractmethod
    def list_recently_deleted(self, library_id: str) -> list[RemoteAsset]: ...

    @abstractmethod
    def get_sync_cursor(self, library_id: str) -> str | None: ...

    @abstractmethod
    def iter_changes(self, library_id: str, cursor: str) -> ChangeBatch: ...

    @abstractmethod
    def open_resource(self, resource: RemoteResource, offset: int = 0) -> ResourceStream: ...

    @abstractmethod
    def logout(self) -> None: ...
