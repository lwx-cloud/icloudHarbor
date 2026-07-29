"""Concurrent, resumable downloads with verification and atomic placement."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import structlog

from icloudharbor.config.models import AccountConfig
from icloudharbor.database.repository import StateRepository
from icloudharbor.download.retry import retry_delay
from icloudharbor.download.verifier import verify_file
from icloudharbor.photos.planner import DownloadTask, SyncPlan
from icloudharbor.protocol.base import ICloudProtocol
from icloudharbor.protocol.exceptions import ErrorCode, HarborError, ProtocolError

LOGGER = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class DownloadOutcome:
    task: DownloadTask
    success: bool
    bytes_downloaded: int = 0
    error_code: str | None = None
    message: str | None = None


@dataclass(slots=True, frozen=True)
class DownloadReport:
    downloaded_count: int
    failed_count: int
    bytes_downloaded: int
    outcomes: tuple[DownloadOutcome, ...]


class DownloadManager:
    def __init__(
        self,
        protocol: ICloudProtocol,
        repository: StateRepository,
        account: AccountConfig,
    ) -> None:
        self.protocol = protocol
        self.repository = repository
        self.account = account
        self.destination = account.destination.path.resolve()

    def execute(self, plan: SyncPlan) -> DownloadReport:
        tasks = [*plan.downloads, *plan.updates]
        if not tasks:
            return DownloadReport(0, 0, 0, ())
        outcomes: list[DownloadOutcome] = []
        with ThreadPoolExecutor(
            max_workers=self.account.download.concurrency,
            thread_name_prefix="icloudharbor-download",
        ) as executor:
            futures = {executor.submit(self._download_with_retry, task): task for task in tasks}
            for future in as_completed(futures):
                try:
                    outcomes.append(future.result())
                except Exception as exc:  # defensive containment for worker failures
                    task = futures[future]
                    LOGGER.error(
                        "download_failed",
                        account_id=self.account.id,
                        asset_id=task.asset.asset_id,
                        resource_id=task.resource.resource_id,
                        file=task.relative_path.as_posix(),
                        error_code=ErrorCode.UNKNOWN_PROTOCOL_ERROR.value,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    outcomes.append(
                        DownloadOutcome(
                            task,
                            False,
                            error_code=ErrorCode.UNKNOWN_PROTOCOL_ERROR.value,
                            message=f"{type(exc).__name__}: {exc}",
                        )
                    )
        return DownloadReport(
            downloaded_count=sum(outcome.success for outcome in outcomes),
            failed_count=sum(not outcome.success for outcome in outcomes),
            bytes_downloaded=sum(outcome.bytes_downloaded for outcome in outcomes),
            outcomes=tuple(outcomes),
        )

    def _download_with_retry(self, task: DownloadTask) -> DownloadOutcome:
        last_error: Exception | None = None
        for attempt in range(self.account.download.max_retries + 1):
            LOGGER.info(
                "download_started",
                account_id=self.account.id,
                asset_id=task.asset.asset_id,
                resource_id=task.resource.resource_id,
                file=task.relative_path.as_posix(),
                expected_bytes=task.resource.size,
                attempt=attempt + 1,
                repair=task.repair,
            )
            try:
                size = self._download_once(task)
                LOGGER.info(
                    "download_completed",
                    account_id=self.account.id,
                    asset_id=task.asset.asset_id,
                    resource_id=task.resource.resource_id,
                    file=task.relative_path.as_posix(),
                    bytes_downloaded=size,
                )
                return DownloadOutcome(task, True, bytes_downloaded=size)
            except (HarborError, ProtocolError, OSError) as exc:
                last_error = exc
                if attempt >= self.account.download.max_retries or not self._retryable(exc):
                    break
                delay = retry_delay(attempt)
                LOGGER.warning(
                    "download_retry",
                    account_id=self.account.id,
                    asset_id=task.asset.asset_id,
                    resource_id=task.resource.resource_id,
                    file=task.relative_path.as_posix(),
                    attempt=attempt + 1,
                    retry_in_seconds=round(delay, 2),
                    error=str(exc),
                )
                time.sleep(delay)
        code = getattr(last_error, "code", ErrorCode.UNKNOWN_PROTOCOL_ERROR)
        code_value = code.value if isinstance(code, ErrorCode) else str(code)
        LOGGER.error(
            "download_failed",
            account_id=self.account.id,
            asset_id=task.asset.asset_id,
            resource_id=task.resource.resource_id,
            file=task.relative_path.as_posix(),
            error_code=code_value,
            error=str(last_error) if last_error else "未知下载错误",
        )
        return DownloadOutcome(
            task,
            False,
            error_code=code_value,
            message=str(last_error) if last_error else "未知下载错误",
        )

    def _download_once(self, task: DownloadTask) -> int:
        target = (self.destination / task.relative_path).resolve()
        if not target.is_relative_to(self.destination):
            raise HarborError("下载路径越过目标目录", ErrorCode.FILE_PERMISSION_ERROR)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f"{target.name}.part")
        offset = (
            partial.stat().st_size if partial.exists() and self.account.download.keep_partial else 0
        )
        if partial.exists() and not self.account.download.keep_partial:
            partial.unlink()

        stream = self.protocol.open_resource(task.resource, offset=offset)
        if offset and not (stream.supports_range or stream.status_code == 206):
            stream.close()
            partial.unlink(missing_ok=True)
            offset = 0
            stream = self.protocol.open_resource(task.resource, offset=0)
        if offset:
            LOGGER.info(
                "download_resumed",
                account_id=self.account.id,
                asset_id=task.asset.asset_id,
                resource_id=task.resource.resource_id,
                file=task.relative_path.as_posix(),
                offset_bytes=offset,
            )

        mode = "ab" if offset else "wb"
        try:
            with stream, partial.open(mode) as output:
                for chunk in stream.iter_chunks(self.account.download.chunk_size):
                    if chunk:
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            size, sha256 = verify_file(
                partial,
                expected_size=task.resource.size,
                expected_checksum=task.resource.checksum,
                chunk_size=self.account.download.chunk_size,
            )
        except Exception:
            if (
                partial.exists()
                and task.resource.size is not None
                and partial.stat().st_size >= task.resource.size
            ):
                partial.unlink(missing_ok=True)
            raise

        # Commit intent before rename. If the process dies between these two
        # operations, the next plan sees a missing formal file and repairs the
        # same deterministic path rather than creating a duplicate.
        self.repository.record_download(
            task.asset,
            task.resource,
            task.relative_path.as_posix(),
            size,
            sha256,
        )
        os.replace(partial, target)
        return size

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        if isinstance(exc, OSError):
            return True
        code = getattr(exc, "code", None)
        return code in {
            ErrorCode.RATE_LIMITED,
            ErrorCode.SERVICE_UNAVAILABLE,
            ErrorCode.NETWORK_TIMEOUT,
            ErrorCode.DOWNLOAD_URL_EXPIRED,
            ErrorCode.DATA_INTEGRITY_ERROR,
        }
