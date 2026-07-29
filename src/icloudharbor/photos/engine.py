"""Fixed-stage synchronization orchestration."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from icloudharbor.config.models import AccountConfig
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
from icloudharbor.protocol.models import AssetQuery, AuthStatus, RemoteAsset
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
        lock_name = f"sync:{account.id}:root"
        try:
            with self.locks.acquire(lock_name):
                self._event(run_id, "PRECHECK", "开始同步前安全检查")
                self._precheck(account)
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
                available = {item.library_id: item for item in self.protocol.list_libraries()}
                selected = [
                    available[library_id]
                    for library_id in account.libraries
                    if library_id in available
                ]
                if not selected:
                    raise HarborError("配置的图库不存在或不可访问", ErrorCode.ACCESS_DENIED)

                cursor_updates: list[tuple[str, str | None, bool]] = []
                for library in selected:
                    self.repository.upsert_library(account.id, library)
                    assets, cursor, was_full = self._scan_library(
                        account,
                        library.library_id,
                        force_full_scan=force_full_scan,
                    )
                    cursor_updates.append((library.library_id, cursor, was_full))
                    library_plan = self.planner.build(assets, account)
                    plan.downloads.extend(library_plan.downloads)
                    plan.updates.extend(library_plan.updates)
                    plan.skips.extend(library_plan.skips)
                    plan.warnings.extend(library_plan.warnings)

                self._event(
                    run_id,
                    "PLAN",
                    "同步计划已生成",
                    payload={
                        "downloads": plan.download_count,
                        "skips": len(plan.skips),
                        "estimated_bytes": plan.estimated_bytes,
                    },
                )
                LOGGER.info(
                    "delete_disabled",
                    run_id=run_id,
                    account_id=account.id,
                    message="备份模式：不会删除 iCloud 或本地照片",
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
                LOGGER.info(
                    "sync_skipped_already_running",
                    run_id=run_id,
                    account_id=account.id,
                )
            else:
                LOGGER.error(
                    "sync_failed",
                    run_id=run_id,
                    account_id=account.id,
                    error_code=code_value,
                    error=str(exc),
                )
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
        query = AssetQuery(account.id, library_id)
        assets = self.protocol.list_assets(query)
        return assets, self.protocol.get_sync_cursor(library_id), True

    def _precheck(self, account: AccountConfig) -> None:
        destination = account.destination.path
        if not destination.is_dir():
            raise HarborError(
                f"下载目录不存在：{destination}",
                ErrorCode.MOUNT_MISSING,
            )
        marker = destination / account.destination.mounted_marker
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
        LOGGER.info(
            event_type.lower(),
            run_id=run_id,
            asset_id=asset_id,
            message=message,
        )

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)
