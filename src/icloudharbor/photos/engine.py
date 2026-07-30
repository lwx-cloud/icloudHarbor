"""Fixed-stage synchronization orchestration."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import structlog

from icloudharbor.config.models import MOUNTED_MARKER, AccountConfig
from icloudharbor.database.repository import StateRepository
from icloudharbor.database.session import Database
from icloudharbor.download.manager import DownloadManager
from icloudharbor.photos.planner import AssetPlanner, SyncPlan
from icloudharbor.protocol.base import ICloudProtocol
from icloudharbor.protocol.exceptions import (
    AuthenticationRequired,
    CursorInvalid,
    ErrorCode,
    HarborError,
)
from icloudharbor.protocol.models import (
    AssetQuery,
    AuthStatus,
    RemoteAlbum,
    RemoteAsset,
    RemoteLibrary,
)
from icloudharbor.scheduler.locks import LockCoordinator

LOGGER = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class SyncExecution:
    run_id: str
    status: str
    downloaded_count: int
    skipped_count: int
    failed_count: int
    bytes_downloaded: int
    plan: SyncPlan
    error_code: str | None = None
    message: str | None = None


class PhotosEngine:
    STAGES = (
        "PRECHECK",
        "AUTH_CHECK",
        "DISCOVER",
        "SCAN",
        "NORMALIZE",
        "PLAN",
        "DOWNLOAD",
        "VERIFY",
        "COMMIT",
        "REPORT",
    )

    def __init__(
        self,
        protocol: ICloudProtocol,
        repository: StateRepository,
        database: Database,
        locks: LockCoordinator,
    ) -> None:
        self.protocol = protocol
        self.repository = repository
        self.database = database
        self.locks = locks
        self.planner = AssetPlanner(repository)

    def run(
        self,
        account: AccountConfig,
        *,
        dry_run: bool = False,
        force_full_scan: bool = False,
    ) -> SyncExecution:
        run_id = self.repository.create_run(account.id, dry_run=dry_run)
        plan = SyncPlan()
        lock_name = f"sync:{account.id}"
        try:
            with self.locks.acquire(lock_name):
                self._event(run_id, "PRECHECK", "开始同步前安全检查")
                self._precheck(account)
                LOGGER.info("下载目录、挂载保护、剩余空间和数据库检查通过")
                self._event(run_id, "AUTH_CHECK", "检查 Apple 会话")
                if self.protocol.auth_status() != AuthStatus.AUTHENTICATED:
                    stored_status = self.repository.get_auth_status(account.id)
                    status_errors = {
                        AuthStatus.TERMS_REQUIRED: ErrorCode.TERMS_REQUIRED,
                        AuthStatus.WEB_ACCESS_DISABLED: ErrorCode.WEB_ACCESS_DISABLED,
                        AuthStatus.ADP_APPROVAL_REQUIRED: ErrorCode.ADP_APPROVAL_REQUIRED,
                    }
                    if stored_status in status_errors:
                        raise HarborError(
                            f"认证被阻止：{stored_status.value}",
                            status_errors[stored_status],
                        )
                    self.repository.set_auth_status(account.id, AuthStatus.AUTH_REQUIRED)
                    raise AuthenticationRequired()

                self._event(run_id, "DISCOVER", "发现远端图库")
                available_libraries = self.protocol.list_libraries()
                selected = self._select_libraries(account, available_libraries)
                if not selected:
                    raise HarborError("配置的图库不存在或不可访问", ErrorCode.ACCESS_DENIED)

                cursor_updates: list[tuple[str, str | None, bool]] = []
                discovered_assets: list[RemoteAsset] = []
                for library in selected:
                    LOGGER.info(f"正在扫描图库：{library.name}")
                    self.repository.upsert_library(account.id, library)
                    assets, cursor, was_full = self._scan_library(
                        account,
                        library.library_id,
                        force_full_scan=force_full_scan,
                    )
                    cursor_updates.append((library.library_id, cursor, was_full))
                    discovered_assets.extend(assets)

                limited_assets = self._limit_assets(account, discovered_assets)
                plan = self.planner.build(limited_assets, account)

                self._event(
                    run_id,
                    "PLAN",
                    "同步计划已生成",
                    payload={
                        "downloads": plan.download_count,
                        "skips": len(plan.skips),
                        "adoptions": len(plan.adoptions),
                        "estimated_bytes": plan.estimated_bytes,
                    },
                )
                skip_note = f"（含 {len(plan.adoptions)} 个认领已有文件）" if plan.adoptions else ""
                LOGGER.info(
                    f"扫描完成：项目={len(limited_assets)}；待下载={plan.download_count}；"
                    f"已存在={len(plan.skips)}{skip_note}；预计数据={plan.estimated_bytes} 字节"
                )
                self._check_plan_space(account, plan)

                if dry_run:
                    self.repository.finish_run(
                        run_id,
                        status="DRY_RUN",
                        skipped_count=len(plan.skips),
                    )
                    return SyncExecution(
                        run_id,
                        "DRY_RUN",
                        0,
                        len(plan.skips),
                        0,
                        0,
                        plan,
                    )

                report = DownloadManager(self.protocol, self.repository, account).execute(plan)
                for outcome in report.outcomes:
                    if not outcome.success:
                        self._event(
                            run_id,
                            "DOWNLOAD_FAILED",
                            outcome.message or "资源下载失败",
                            severity="ERROR",
                            asset_id=outcome.task.asset.asset_id,
                            payload={"error_code": outcome.error_code},
                        )
                status = "COMPLETED" if report.failed_count == 0 else "PARTIAL"
                if report.failed_count == 0:
                    for library_id, cursor, was_full in cursor_updates:
                        self.repository.update_library_cursor(
                            account.id,
                            library_id,
                            cursor,
                            full_scan=was_full,
                        )
                self.repository.finish_run(
                    run_id,
                    status=status,
                    downloaded_count=report.downloaded_count,
                    skipped_count=len(plan.skips),
                    failed_count=report.failed_count,
                    bytes_downloaded=report.bytes_downloaded,
                )
                self._event(run_id, "REPORT", f"同步结束：{status}")
                return SyncExecution(
                    run_id,
                    status,
                    report.downloaded_count,
                    len(plan.skips),
                    report.failed_count,
                    report.bytes_downloaded,
                    plan,
                )
        except Exception as exc:
            code = getattr(exc, "code", ErrorCode.UNKNOWN_PROTOCOL_ERROR)
            code_value = code.value if isinstance(code, ErrorCode) else str(code)
            already_running = code == ErrorCode.ALREADY_RUNNING
            status = "SKIPPED_ALREADY_RUNNING" if already_running else "FAILED"
            self.repository.finish_run(run_id, status=status, error_code=code_value)
            self._event(
                run_id,
                status,
                str(exc),
                severity="INFO" if already_running else "ERROR",
                payload={"error_code": code_value},
            )
            if already_running:
                LOGGER.info("已有同步任务正在运行，本次不重复启动")
            else:
                LOGGER.error(f"同步失败：错误码={code_value}；原因={exc}")
            return SyncExecution(
                run_id,
                status,
                0,
                len(plan.skips),
                0,
                0,
                plan,
                code_value,
                str(exc),
            )

    def _scan_library(
        self,
        account: AccountConfig,
        library_id: str,
        *,
        force_full_scan: bool,
    ) -> tuple[list[RemoteAsset], str | None, bool]:
        state = self.repository.library_state(account.id, library_id)
        if account.filters.albums or account.filters.exclude_albums:
            assets = self._scan_filtered_library(account, library_id)
            # A scoped album scan is not a complete view of the library. Clear
            # its cursor so removing the filter later forces a safe full scan.
            return assets, None, False
        cursor = state[1] if state else None
        last_full = self._aware(state[2]) if state and state[2] else None
        full_due = (
            last_full is None or datetime.now(UTC) - last_full >= account.sync.full_scan_interval
        )
        use_full = force_full_scan or account.sync.strategy == "full" or not cursor or full_due
        if not use_full:
            try:
                assert cursor is not None
                batch = self.protocol.iter_changes(library_id, cursor)
                return list(batch.assets), batch.cursor, False
            except CursorInvalid:
                use_full = True
        query = AssetQuery(
            account.id,
            library_id,
            limit=account.filters.recent_only,
        )
        assets = self.protocol.list_assets(query)
        if account.filters.recent_only is not None or account.filters.until_found is not None:
            # These options deliberately truncate the plan. Do not advance the
            # complete-library cursor beyond resources the user has not seen.
            return assets, None, False
        return assets, self.protocol.get_sync_cursor(library_id), True

    def _scan_filtered_library(
        self,
        account: AccountConfig,
        library_id: str,
    ) -> list[RemoteAsset]:
        available = self.protocol.list_albums(library_id)
        included = self._resolve_albums(account.filters.albums, available, library_id)
        excluded = self._resolve_albums(account.filters.exclude_albums, available, library_id)
        excluded_asset_ids: set[str] = set()
        for album in excluded:
            excluded_asset_ids.update(
                asset.asset_id
                for asset in self.protocol.list_assets(
                    AssetQuery(account.id, library_id, album_id=album.album_id)
                )
            )

        sources: list[tuple[RemoteAlbum | None, list[RemoteAsset]]]
        if included:
            sources = [
                (
                    album,
                    self.protocol.list_assets(
                        AssetQuery(
                            account.id,
                            library_id,
                            album_id=album.album_id,
                            limit=account.filters.recent_only,
                        )
                    ),
                )
                for album in included
            ]
        else:
            sources = [
                (
                    None,
                    self.protocol.list_assets(
                        AssetQuery(
                            account.id,
                            library_id,
                            limit=(None if excluded else account.filters.recent_only),
                        )
                    ),
                )
            ]

        result: list[RemoteAsset] = []
        seen: set[str] = set()
        for source_album, assets in sources:
            for asset in assets:
                if asset.asset_id in excluded_asset_ids or asset.asset_id in seen:
                    continue
                seen.add(asset.asset_id)
                if source_album is not None:
                    metadata = dict(asset.metadata)
                    metadata["album_id"] = source_album.album_id
                    metadata["album_name"] = source_album.name
                    asset = replace(asset, metadata=metadata)
                result.append(asset)
        return result

    def _limit_assets(
        self,
        account: AccountConfig,
        assets: list[RemoteAsset],
    ) -> list[RemoteAsset]:
        ordered = sorted(
            assets,
            key=lambda asset: asset.added_at or asset.created_at,
            reverse=True,
        )
        if account.filters.recent_only is not None:
            ordered = ordered[: account.filters.recent_only]
        if account.filters.until_found is None:
            return ordered

        selected: list[RemoteAsset] = []
        consecutive_existing = 0
        for asset in ordered:
            preview = self.planner.build([asset], account)
            selected.append(asset)
            if preview.download_count == 0 and preview.skips:
                consecutive_existing += 1
                if consecutive_existing >= account.filters.until_found:
                    break
            else:
                consecutive_existing = 0
        return selected

    @staticmethod
    def _select_libraries(
        account: AccountConfig,
        available: list[RemoteLibrary],
    ) -> list[RemoteLibrary]:
        by_selector: dict[str, RemoteLibrary] = {}
        for library in available:
            library_id = library.library_id
            name = library.name
            by_selector[library_id] = library
            by_selector.setdefault(name, library)
        missing = [selector for selector in account.libraries if selector not in by_selector]
        if missing:
            raise HarborError(
                f"图库不存在或不可访问：{', '.join(missing)}",
                ErrorCode.REMOTE_NOT_FOUND,
            )
        selected: list[RemoteLibrary] = []
        seen: set[str] = set()
        for selector in account.libraries:
            library = by_selector[selector]
            library_id = library.library_id
            if library_id not in seen:
                seen.add(library_id)
                selected.append(library)
        return selected

    @staticmethod
    def _resolve_albums(
        selectors: list[str],
        available: list[RemoteAlbum],
        library_id: str,
    ) -> list[RemoteAlbum]:
        if not selectors:
            return []
        by_selector: dict[str, RemoteAlbum] = {}
        for album in available:
            by_selector[album.album_id] = album
            by_selector.setdefault(album.name, album)
        missing = [selector for selector in selectors if selector not in by_selector]
        if missing:
            raise HarborError(
                f"图库 {library_id} 中不存在相册：{', '.join(missing)}",
                ErrorCode.REMOTE_NOT_FOUND,
            )
        result: list[RemoteAlbum] = []
        seen: set[str] = set()
        for selector in selectors:
            album = by_selector[selector]
            if album.album_id not in seen:
                seen.add(album.album_id)
                result.append(album)
        return result

    def _precheck(self, account: AccountConfig) -> None:
        destination = account.destination.path
        if not destination.is_dir():
            raise HarborError(
                f"下载目录不存在：{destination}",
                ErrorCode.MOUNT_MISSING,
            )
        marker = destination / MOUNTED_MARKER
        if not marker.is_file():
            raise HarborError(
                f"挂载标记不存在：{marker}",
                ErrorCode.MOUNT_MISSING,
            )
        if not os.access(destination, os.W_OK):
            raise HarborError(
                f"下载目录不可写：{destination}",
                ErrorCode.FILE_PERMISSION_ERROR,
            )
        free = shutil.disk_usage(destination).free
        if free < account.destination.minimum_free_space:
            raise HarborError(
                f"剩余空间不足：{free} 字节",
                ErrorCode.STORAGE_FULL,
            )
        statvfs = getattr(os, "statvfs", None)
        if statvfs is not None:
            filesystem = statvfs(destination)
            if filesystem.f_files > 0 and filesystem.f_favail <= 0:
                raise HarborError("目标文件系统 inode 已耗尽", ErrorCode.STORAGE_FULL)
        if self.database.check().lower() != "ok":
            raise HarborError("SQLite 完整性检查失败", ErrorCode.DATABASE_ERROR)

    @staticmethod
    def _check_plan_space(account: AccountConfig, plan: SyncPlan) -> None:
        free = shutil.disk_usage(account.destination.path).free
        required = account.destination.minimum_free_space + plan.estimated_bytes
        if free < required:
            raise HarborError(
                f"计划需要 {plan.estimated_bytes} 字节，无法保留最低剩余空间",
                ErrorCode.STORAGE_FULL,
            )

    def _event(
        self,
        run_id: str,
        event_type: str,
        message: str,
        *,
        severity: str = "INFO",
        asset_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.repository.add_event(
            run_id,
            event_type,
            message,
            severity=severity,
            asset_id=asset_id,
            payload=payload,
        )
        LOGGER.debug(
            event_type.lower(),
            run_id=run_id,
            asset_id=asset_id,
            message=message,
        )

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)
