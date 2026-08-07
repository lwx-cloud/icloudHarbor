"""Fixed-stage synchronization orchestration."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import structlog

from icloudharbor.config.models import MOUNTED_MARKER, AccountConfig
from icloudharbor.database.repository import StateRepository
from icloudharbor.database.session import Database
from icloudharbor.download.deletion import LocalDeletionManager, LocalDeletionReport
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
    deleted_count: int = 0
    delete_failed_count: int = 0
    bytes_deleted: int = 0
    deleted_files: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class SyncPreview:
    plan: SyncPlan
    asset_count: int
    recently_deleted_count: int


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
        "LOCAL_DELETE",
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

    def preview(self, account: AccountConfig) -> SyncPreview:
        """Build a synchronization plan without changing persistent state."""
        with self.locks.acquire(f"sync:{account.id}"):
            self._precheck(account)
            if self.protocol.auth_status() != AuthStatus.AUTHENTICATED:
                raise AuthenticationRequired()

            selected = self._select_libraries(account, self.protocol.list_libraries())
            if not selected:
                raise HarborError("配置的图库不存在或不可访问", ErrorCode.ACCESS_DENIED)

            discovered_assets: list[RemoteAsset] = []
            for library in selected:
                assets, _, _ = self._scan_library(
                    account,
                    library.library_id,
                    force_full_scan=False,
                    persist_adoptions=False,
                )
                discovered_assets.extend(assets)

            deleted_assets: list[RemoteAsset] = []
            deletion_warnings: list[str] = []
            if account.sync.auto_delete:
                for library in selected:
                    if library.library_id != "root":
                        deletion_warnings.append(
                            f"图库 {library.name} 暂不支持最近删除扫描，已跳过本地删除"
                        )
                        continue
                    deleted_assets.extend(self.protocol.list_recently_deleted(library.library_id))

            limited_assets = self._limit_assets(
                account,
                discovered_assets,
                persist_adoptions=False,
            )
            plan = self.planner.build(
                limited_assets,
                account,
                persist_adoptions=False,
            )
            plan.warnings.extend(deletion_warnings)
            self.planner.add_local_deletions(
                plan,
                deleted_assets,
                account,
                {(asset.library_id, asset.asset_id) for asset in discovered_assets},
            )
            self._check_plan_space(account, plan)
            return SyncPreview(plan, len(limited_assets), len(deleted_assets))

    def run(
        self,
        account: AccountConfig,
        *,
        force_full_scan: bool = False,
    ) -> SyncExecution:
        run_id = self.repository.create_run(account.id)
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
                        persist_adoptions=True,
                    )
                    cursor_updates.append((library.library_id, cursor, was_full))
                    discovered_assets.extend(assets)

                deleted_assets: list[RemoteAsset] = []
                deletion_warnings: list[str] = []
                if account.sync.auto_delete:
                    for library in selected:
                        if library.library_id != "root":
                            deletion_warnings.append(
                                f"图库 {library.name} 暂不支持最近删除扫描，已跳过本地删除"
                            )
                            continue
                        LOGGER.info("正在扫描 iCloud 最近删除")
                        deleted_assets.extend(
                            self.protocol.list_recently_deleted(library.library_id)
                        )

                limited_assets = self._limit_assets(account, discovered_assets)

                # Process downloads in batches so each asset's download URL is
                # consumed shortly after the iCloud scan, before it expires (410).
                # Each batch plans and downloads atomically; one shared path map
                # keeps collision assignments stable across all batches.
                batch_size = 50
                merged_plan = SyncPlan()
                merged_plan.warnings = list(deletion_warnings)
                total_downloaded = 0
                total_failed = 0
                total_bytes = 0
                total_skips = 0
                total_adoptions = 0
                reserved_paths: dict[Path, tuple[str, str, str, str]] = {}

                for start in range(0, len(limited_assets), batch_size):
                    batch = limited_assets[start : start + batch_size]
                    batch_plan = self.planner.build(
                        batch,
                        account,
                        reserved_paths=reserved_paths,
                    )
                    if start == 0:
                        # Rough space estimate: first batch scaled to total count.
                        self._check_plan_space(account, batch_plan)
                    batch_report = DownloadManager(self.protocol, self.repository, account).execute(
                        batch_plan
                    )
                    total_downloaded += batch_report.downloaded_count
                    total_failed += batch_report.failed_count
                    total_bytes += batch_report.bytes_downloaded
                    total_skips += len(batch_plan.skips)
                    total_adoptions += len(batch_plan.adoptions)
                    merged_plan.warnings.extend(batch_plan.warnings)
                    for outcome in batch_report.outcomes:
                        if not outcome.success:
                            self._event(
                                run_id,
                                "DOWNLOAD_FAILED",
                                outcome.message or "资源下载失败",
                                severity="ERROR",
                                asset_id=outcome.task.asset.asset_id,
                                payload={"error_code": outcome.error_code},
                            )

                self.planner.add_local_deletions(
                    merged_plan,
                    deleted_assets,
                    account,
                    {(asset.library_id, asset.asset_id) for asset in discovered_assets},
                )

                self._event(
                    run_id,
                    "PLAN",
                    "同步计划已生成",
                    payload={
                        "downloads": total_downloaded,
                        "skips": total_skips,
                        "adoptions": total_adoptions,
                        "local_deletions": merged_plan.local_delete_count,
                        "estimated_bytes": total_bytes,
                    },
                )
                skip_note = f"（含 {total_adoptions} 个认领已有文件）" if total_adoptions else ""
                LOGGER.info(
                    f"扫描完成：iCloud 项目={len(limited_assets)}；"
                    f"待下载文件={total_downloaded + total_failed}；"
                    f"已存在文件={total_skips}{skip_note}；"
                    f"待删除本地文件={merged_plan.local_delete_count}；"
                    f"预计数据={total_bytes} 字节"
                )
                if merged_plan.unmatched_deleted_count:
                    LOGGER.info(
                        f"最近删除：匹配 {merged_plan.local_delete_asset_count} 个项目、"
                        f"{merged_plan.local_delete_count} 个本地文件；另有 "
                        f"{merged_plan.unmatched_deleted_count} 个项目没有本地记录，已忽略"
                    )
                for warning in merged_plan.warnings:
                    self._event(run_id, "PLAN_WARNING", warning, severity="WARNING")

                deletion_report = LocalDeletionReport(0, 0, 0, ())
                if total_failed == 0 and merged_plan.local_deletions:
                    self._event(run_id, "LOCAL_DELETE", "开始处理 iCloud 最近删除对应本地文件")
                    deletion_report = LocalDeletionManager(
                        self.repository,
                        account,
                    ).execute(merged_plan.local_deletions)
                    for deletion_outcome in deletion_report.outcomes:
                        if not deletion_outcome.success:
                            self._event(
                                run_id,
                                "LOCAL_DELETE_FAILED",
                                deletion_outcome.message or "本地文件删除失败",
                                severity="ERROR",
                                asset_id=deletion_outcome.task.asset.asset_id,
                                payload={"error_code": deletion_outcome.error_code},
                            )
                total_failed += deletion_report.failed_count
                status = "COMPLETED" if total_failed == 0 else "PARTIAL"
                if total_failed == 0:
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
                    downloaded_count=total_downloaded,
                    skipped_count=total_skips,
                    failed_count=total_failed,
                    bytes_downloaded=total_bytes,
                )
                self._event(run_id, "REPORT", f"同步结束：{status}")
                return SyncExecution(
                    run_id,
                    status,
                    total_downloaded,
                    total_skips,
                    total_failed,
                    total_bytes,
                    merged_plan,
                    deleted_count=deletion_report.deleted_count,
                    delete_failed_count=deletion_report.failed_count,
                    bytes_deleted=deletion_report.bytes_deleted,
                    deleted_files=deletion_report.deleted_files,
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
        persist_adoptions: bool,
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
        if account.filters.until_found is not None:
            assets = self._scan_until_found(
                account,
                query,
                persist_adoptions=persist_adoptions,
            )
        else:
            assets = self.protocol.list_assets(query)
        if account.filters.recent_only is not None or account.filters.until_found is not None:
            # These options deliberately truncate the plan. Do not advance the
            # complete-library cursor beyond resources the user has not seen.
            return assets, None, False
        return assets, self.protocol.get_sync_cursor(library_id), True

    def _scan_until_found(
        self,
        account: AccountConfig,
        query: AssetQuery,
        *,
        persist_adoptions: bool,
    ) -> list[RemoteAsset]:
        """Stop remote iteration once enough consecutive tracked assets are seen."""
        threshold = account.filters.until_found
        assert threshold is not None
        selected: list[RemoteAsset] = []
        consecutive_existing = 0
        reserved_paths: dict[Path, tuple[str, str, str, str]] = {}
        for asset in self.protocol.iter_assets(query):
            selected.append(asset)
            preview = self.planner.build(
                [asset],
                account,
                persist_adoptions=persist_adoptions,
                reserved_paths=reserved_paths,
            )
            if preview.download_count == 0 and preview.skips:
                consecutive_existing += 1
                if consecutive_existing >= threshold:
                    LOGGER.info(f"连续遇到 {threshold} 个已有项目，提前结束 iCloud 扫描")
                    break
            else:
                consecutive_existing = 0
        return selected

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
        *,
        persist_adoptions: bool = True,
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
        reserved_paths: dict[Path, tuple[str, str, str, str]] = {}
        for asset in ordered:
            preview = self.planner.build(
                [asset],
                account,
                persist_adoptions=persist_adoptions,
                reserved_paths=reserved_paths,
            )
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
