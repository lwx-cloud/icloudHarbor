"""Transactional state repository used by planning and download workers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from icloudharbor.config.models import AccountConfig
from icloudharbor.database.models import (
    AccountRow,
    AssetRow,
    ConfigRevisionRow,
    LibraryRow,
    LocalFileRow,
    LockRow,
    ResourceRow,
    SyncEventRow,
    SyncRunRow,
)
from icloudharbor.database.session import Database
from icloudharbor.protocol.models import AuthStatus, RemoteAsset, RemoteLibrary, RemoteResource


@dataclass(slots=True, frozen=True)
class LocalFileState:
    relative_path: str
    size: int
    sha256: str | None
    status: str


@dataclass(slots=True, frozen=True)
class RunSummary:
    id: str
    account_id: str
    library_id: str | None
    mode: str
    dry_run: bool
    started_at: datetime
    finished_at: datetime | None
    status: str
    downloaded_count: int
    skipped_count: int
    failed_count: int
    bytes_downloaded: int
    error_code: str | None


class StateRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def sync_account(self, account: AccountConfig) -> None:
        with self.database.sessions.begin() as session:
            row = session.get(AccountRow, account.id)
            if row is None:
                row = AccountRow(
                    id=account.id,
                    name=account.name,
                    apple_id=account.apple_id,
                    region=account.region,
                    enabled=account.enabled,
                )
                session.add(row)
            else:
                row.name = account.name
                row.apple_id = account.apple_id
                row.region = account.region
                row.enabled = account.enabled

    def set_auth_status(self, account_id: str, status: AuthStatus) -> None:
        with self.database.sessions.begin() as session:
            row = session.get(AccountRow, account_id)
            if row is None:
                raise KeyError(account_id)
            row.auth_status = status.value
            if status == AuthStatus.AUTHENTICATED:
                row.last_auth_at = datetime.now(UTC)

    def get_auth_status(self, account_id: str) -> AuthStatus:
        with self.database.sessions() as session:
            row = session.get(AccountRow, account_id)
            if not row:
                return AuthStatus.UNCONFIGURED
            try:
                return AuthStatus(row.auth_status)
            except ValueError:
                return AuthStatus.REAUTHENTICATION_REQUIRED

    def upsert_library(self, account_id: str, library: RemoteLibrary) -> int:
        with self.database.sessions.begin() as session:
            row = session.scalar(
                select(LibraryRow).where(
                    LibraryRow.account_id == account_id,
                    LibraryRow.remote_library_id == library.library_id,
                )
            )
            if row is None:
                row = LibraryRow(
                    account_id=account_id,
                    remote_library_id=library.library_id,
                    name=library.name,
                    library_type=library.library_type,
                )
                session.add(row)
                session.flush()
            else:
                row.name = library.name
                row.library_type = library.library_type
            return row.id

    def library_state(
        self, account_id: str, remote_library_id: str
    ) -> tuple[int, str | None, datetime | None] | None:
        with self.database.sessions() as session:
            row = session.scalar(
                select(LibraryRow).where(
                    LibraryRow.account_id == account_id,
                    LibraryRow.remote_library_id == remote_library_id,
                )
            )
            return (row.id, row.last_cursor, row.last_full_scan_at) if row else None

    def update_library_cursor(
        self,
        account_id: str,
        library_id: str,
        cursor: str | None,
        *,
        full_scan: bool,
    ) -> None:
        with self.database.sessions.begin() as session:
            row = session.scalar(
                select(LibraryRow).where(
                    LibraryRow.account_id == account_id,
                    LibraryRow.remote_library_id == library_id,
                )
            )
            if not row:
                raise KeyError((account_id, library_id))
            row.last_cursor = cursor
            if full_scan:
                row.last_full_scan_at = datetime.now(UTC)

    def get_local_file(
        self,
        account_id: str,
        library_id: str,
        asset_id: str,
        resource_type: str,
        version: str,
    ) -> LocalFileState | None:
        with self.database.sessions() as session:
            row = session.scalar(
                select(LocalFileRow)
                .join(ResourceRow)
                .join(AssetRow)
                .join(LibraryRow)
                .where(
                    LibraryRow.account_id == account_id,
                    LibraryRow.remote_library_id == library_id,
                    AssetRow.remote_asset_id == asset_id,
                    ResourceRow.resource_type == resource_type,
                    ResourceRow.version == version,
                )
            )
            if not row:
                return None
            return LocalFileState(row.relative_path, row.size, row.sha256, row.status)

    def record_download(
        self,
        asset: RemoteAsset,
        resource: RemoteResource,
        relative_path: str,
        size: int,
        sha256: str,
    ) -> None:
        with self.database.sessions.begin() as session:
            library = session.scalar(
                select(LibraryRow).where(
                    LibraryRow.account_id == asset.account_id,
                    LibraryRow.remote_library_id == asset.library_id,
                )
            )
            if library is None:
                raise KeyError((asset.account_id, asset.library_id))
            asset_row = session.scalar(
                select(AssetRow).where(
                    AssetRow.library_id == library.id,
                    AssetRow.remote_asset_id == asset.asset_id,
                )
            )
            metadata = json.dumps(dict(asset.metadata), ensure_ascii=False, default=str)
            if asset_row is None:
                asset_row = AssetRow(
                    library_id=library.id,
                    remote_asset_id=asset.asset_id,
                    filename=asset.filename,
                    media_type=asset.media_type,
                    created_at=asset.created_at,
                    modified_at=asset.modified_at,
                    favorite=asset.favorite,
                    hidden=asset.hidden,
                    remote_deleted=asset.deleted,
                    metadata_json=metadata,
                )
                session.add(asset_row)
                session.flush()
            else:
                asset_row.filename = asset.filename
                asset_row.media_type = asset.media_type
                asset_row.modified_at = asset.modified_at
                asset_row.favorite = asset.favorite
                asset_row.hidden = asset.hidden
                asset_row.remote_deleted = asset.deleted
                asset_row.metadata_json = metadata
            resource_row = session.scalar(
                select(ResourceRow).where(
                    ResourceRow.asset_id == asset_row.id,
                    ResourceRow.resource_type == resource.resource_type,
                    ResourceRow.version == resource.version,
                )
            )
            if resource_row is None:
                resource_row = ResourceRow(
                    asset_id=asset_row.id,
                    remote_resource_id=resource.resource_id,
                    resource_type=resource.resource_type,
                    version=resource.version,
                    remote_size=resource.size,
                    remote_checksum=resource.checksum,
                    mime_type=resource.mime_type,
                )
                session.add(resource_row)
                session.flush()
            else:
                resource_row.remote_resource_id = resource.resource_id
                resource_row.remote_size = resource.size
                resource_row.remote_checksum = resource.checksum
                resource_row.mime_type = resource.mime_type
            local = resource_row.local_file
            if local is None:
                local = LocalFileRow(
                    resource_id=resource_row.id,
                    relative_path=relative_path,
                    size=size,
                    sha256=sha256,
                    status="VERIFIED",
                    verified_at=datetime.now(UTC),
                )
                session.add(local)
            else:
                local.relative_path = relative_path
                local.size = size
                local.sha256 = sha256
                local.status = "VERIFIED"
                local.downloaded_at = datetime.now(UTC)
                local.verified_at = datetime.now(UTC)

    def create_run(
        self,
        account_id: str,
        library_id: str | None = None,
        *,
        dry_run: bool = False,
    ) -> str:
        run_id = str(uuid.uuid4())
        with self.database.sessions.begin() as session:
            session.add(
                SyncRunRow(
                    id=run_id,
                    account_id=account_id,
                    library_id=library_id,
                    mode="backup",
                    dry_run=dry_run,
                )
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        downloaded_count: int = 0,
        skipped_count: int = 0,
        failed_count: int = 0,
        bytes_downloaded: int = 0,
        error_code: str | None = None,
    ) -> None:
        with self.database.sessions.begin() as session:
            row = session.get(SyncRunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            row.finished_at = datetime.now(UTC)
            row.status = status
            row.downloaded_count = downloaded_count
            row.skipped_count = skipped_count
            row.failed_count = failed_count
            row.bytes_downloaded = bytes_downloaded
            row.error_code = error_code

    def add_event(
        self,
        run_id: str,
        event_type: str,
        message: str,
        *,
        severity: str = "INFO",
        asset_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.database.sessions.begin() as session:
            session.add(
                SyncEventRow(
                    run_id=run_id,
                    event_type=event_type,
                    severity=severity,
                    asset_id=asset_id,
                    message=message,
                    payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str),
                )
            )

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        with self.database.sessions() as session:
            rows = session.scalars(
                select(SyncRunRow).order_by(SyncRunRow.started_at.desc()).limit(limit)
            ).all()
            return [
                RunSummary(
                    id=row.id,
                    account_id=row.account_id,
                    library_id=row.library_id,
                    mode=row.mode,
                    dry_run=row.dry_run,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                    status=row.status,
                    downloaded_count=row.downloaded_count,
                    skipped_count=row.skipped_count,
                    failed_count=row.failed_count,
                    bytes_downloaded=row.bytes_downloaded,
                    error_code=row.error_code,
                )
                for row in rows
            ]

    def list_errors(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.sessions() as session:
            rows = session.scalars(
                select(SyncEventRow)
                .where(SyncEventRow.severity.in_(["ERROR", "CRITICAL"]))
                .order_by(SyncEventRow.created_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "id": row.id,
                    "run_id": row.run_id,
                    "event_type": row.event_type,
                    "asset_id": row.asset_id,
                    "message": row.message,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def save_config_revision(self, snapshot: str) -> str:
        digest = hashlib.sha256(snapshot.encode()).hexdigest()
        with self.database.sessions.begin() as session:
            existing = session.scalar(
                select(ConfigRevisionRow).where(ConfigRevisionRow.config_hash == digest)
            )
            if existing is None:
                session.add(ConfigRevisionRow(config_hash=digest, config_snapshot=snapshot))
        return digest

    def acquire_lock(self, name: str, owner: str, ttl: timedelta) -> bool:
        now = datetime.now(UTC)
        expires = now + ttl
        try:
            with self.database.sessions.begin() as session:
                session.execute(delete(LockRow).where(LockRow.expires_at < now))
                if session.get(LockRow, name):
                    return False
                session.add(
                    LockRow(
                        name=name,
                        owner=owner,
                        acquired_at=now,
                        expires_at=expires,
                    )
                )
                session.flush()
        except IntegrityError:
            return False
        return True

    def release_lock(self, name: str, owner: str) -> None:
        with self.database.sessions.begin() as session:
            session.execute(delete(LockRow).where(LockRow.name == name, LockRow.owner == owner))

    def backup(self, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            sqlite3.connect(self.database.path) as source,
            sqlite3.connect(target) as destination,
        ):
            source.backup(destination)
        return target

    @staticmethod
    def summary_dict(summary: RunSummary) -> dict[str, Any]:
        return asdict(summary)
