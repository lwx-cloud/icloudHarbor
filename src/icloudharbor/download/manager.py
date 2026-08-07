"""Concurrent, resumable downloads with verification and atomic placement."""

from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import structlog

from icloudharbor.config.models import DOWNLOAD_CHUNK_SIZE, AccountConfig
from icloudharbor.database.repository import StateRepository
from icloudharbor.download.postprocess import MediaPostProcessor
from icloudharbor.download.retry import retry_delay
from icloudharbor.download.verifier import verify_file, verify_metadata
from icloudharbor.observability.paths import display_download_path
from icloudharbor.photos.planner import DownloadTask, SyncPlan
from icloudharbor.protocol.base import ICloudProtocol
from icloudharbor.protocol.exceptions import ErrorCode, HarborError, ProtocolError
from icloudharbor.protocol.models import RemoteResource

LOGGER = structlog.get_logger(__name__)


def partial_path_for(target: Path, resource: RemoteResource) -> Path:
    """Bind resumable data to one stable remote resource identity."""
    identity = "\0".join(
        (
            resource.resource_id,
            resource.resource_type,
            resource.version,
            resource.checksum or "",
            str(resource.size) if resource.size is not None else "",
        )
    )
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return target.with_name(f".{target.name}.{fingerprint}.part")


def cleanup_stale_partials(target: Path, *, keep: Path | None = None) -> None:
    """Remove legacy or superseded partial files for one final target."""
    legacy = target.with_name(f"{target.name}.part")
    prefix = f".{target.name}."
    for candidate in target.parent.iterdir():
        fingerprint = (
            candidate.name[len(prefix) : -len(".part")]
            if candidate.name.startswith(prefix) and candidate.name.endswith(".part")
            else ""
        )
        managed_partial = candidate == legacy or (
            len(fingerprint) == 16
            and all(character in "0123456789abcdef" for character in fingerprint)
        )
        if not managed_partial or candidate == keep or candidate.is_symlink():
            continue
        if candidate.is_file():
            candidate.unlink()


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
        self.postprocessor = MediaPostProcessor(account)

    def execute(self, plan: SyncPlan) -> DownloadReport:
        tasks = [*plan.downloads, *plan.updates]
        self.postprocessor.protect_download_paths(
            {task.relative_path for task in [*tasks, *plan.skips]}
        )
        outcomes: list[DownloadOutcome] = []
        for task in plan.skips:
            source = self.destination / task.relative_path
            try:
                artifacts = self.postprocessor.process_existing(
                    source,
                    task.relative_path,
                    task.asset.created_at,
                )
                self._record_artifacts(task, artifacts)
            except (OSError, ValueError) as exc:
                path = display_download_path(
                    self.account.destination.path,
                    task.relative_path,
                )
                LOGGER.error(f"生成 JPEG 失败：{path}；原因：{exc}")
                outcomes.append(
                    DownloadOutcome(
                        task,
                        False,
                        error_code=ErrorCode.DATA_INTEGRITY_ERROR.value,
                        message=str(exc),
                    )
                )
        if not tasks:
            return DownloadReport(
                0,
                sum(not outcome.success for outcome in outcomes),
                0,
                tuple(outcomes),
            )
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
                    path = display_download_path(self.account.destination.path, task.relative_path)
                    LOGGER.error(
                        f"下载失败：{path}；原因：{type(exc).__name__}: {exc}",
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
        path = display_download_path(self.account.destination.path, task.relative_path)
        brief = task.relative_path.name
        started = time.monotonic()
        LOGGER.info(f"正在下载：{path}")
        for attempt in range(self.account.download.max_retries + 1):
            try:
                size = self._download_once(task)
                elapsed = time.monotonic() - started
                speed = size / elapsed if elapsed > 0 else 0
                LOGGER.debug(
                    f"完成下载：{brief}；"
                    f"耗时 {elapsed:.1f}s；"
                    f"大小 {size} 字节；"
                    f"速率 {speed / 1000:.0f}KB/s；"
                    f"重试 {attempt} 次",
                )
                target = (self.destination / task.relative_path).resolve()
                artifacts = self.postprocessor.process_download(
                    target,
                    task.relative_path,
                    task.asset.created_at,
                )
                self._record_artifacts(task, artifacts)
                return DownloadOutcome(task, True, bytes_downloaded=size)
            except (HarborError, ProtocolError, OSError) as exc:
                last_error = exc
                if attempt >= self.account.download.max_retries or not self._retryable(exc):
                    break
                delay = retry_delay(attempt)
                LOGGER.warning(
                    f"下载重试：{path}；{round(delay, 2)} 秒后重试；原因：{exc}",
                )
                time.sleep(delay)
        code = getattr(last_error, "code", ErrorCode.UNKNOWN_PROTOCOL_ERROR)
        code_value = code.value if isinstance(code, ErrorCode) else str(code)
        LOGGER.error(
            f"下载失败：{path}；错误码：{code_value}；"
            f"原因：{last_error if last_error else '未知下载错误'}",
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
        self.postprocessor.prepare_parent(target.parent)
        partial = partial_path_for(target, task.resource)
        cleanup_stale_partials(target, keep=partial)
        offset = partial.stat().st_size if partial.exists() else 0

        stream = self.protocol.open_resource(task.resource, offset=offset)
        if offset and not (stream.supports_range or stream.status_code == 206):
            stream.close()
            partial.unlink(missing_ok=True)
            offset = 0
            stream = self.protocol.open_resource(task.resource, offset=0)
        if offset:
            LOGGER.debug(f"从断点继续下载：{target.as_posix()}；已完成 {offset} 字节")

        mode = "ab" if offset else "wb"
        digest = hashlib.sha256()
        size = 0
        if offset:
            # Hash only the existing prefix. Newly received bytes are hashed as
            # they are written, avoiding a second full read after download.
            with partial.open("rb") as existing:
                while chunk := existing.read(DOWNLOAD_CHUNK_SIZE):
                    size += len(chunk)
                    digest.update(chunk)
        try:
            with stream, partial.open(mode) as output:
                for chunk in stream.iter_chunks(DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        output.write(chunk)
                        size += len(chunk)
                        digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            sha256 = digest.hexdigest()
            verify_metadata(
                size,
                sha256,
                expected_size=task.resource.size,
                expected_checksum=task.resource.checksum,
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

    def _record_artifacts(self, task: DownloadTask, paths: tuple[Path, ...]) -> None:
        jpeg_root = (self.account.media.jpeg_path or self.destination).resolve()
        for path in paths:
            resolved = path.resolve()
            if resolved.is_relative_to(self.destination):
                root = "destination"
                relative = resolved.relative_to(self.destination)
            elif resolved.is_relative_to(jpeg_root):
                root = "jpeg"
                relative = resolved.relative_to(jpeg_root)
            else:
                raise HarborError("派生文件路径越过允许目录", ErrorCode.FILE_PERMISSION_ERROR)
            size, sha256 = verify_file(
                resolved,
                expected_size=None,
                expected_checksum=None,
                chunk_size=DOWNLOAD_CHUNK_SIZE,
            )
            self.repository.record_local_artifact(
                task.asset.account_id,
                task.asset.library_id,
                task.asset.asset_id,
                task.resource.resource_type,
                task.resource.version,
                root=root,
                relative_path=relative.as_posix(),
                kind="converted_jpeg",
                size=size,
                sha256=sha256,
            )

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
            ErrorCode.UNKNOWN_PROTOCOL_ERROR,
        }
