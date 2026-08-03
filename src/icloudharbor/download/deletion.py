"""Fail-closed deletion of local files whose iCloud assets are recently deleted."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

from icloudharbor.config.models import DOWNLOAD_CHUNK_SIZE, AccountConfig
from icloudharbor.database.repository import ManagedLocalFile, StateRepository
from icloudharbor.download.verifier import verify_file
from icloudharbor.observability.paths import display_host_path
from icloudharbor.photos.planner import LocalDeletionTask
from icloudharbor.protocol.exceptions import ErrorCode, HarborError

LOGGER = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class LocalDeletionOutcome:
    task: LocalDeletionTask
    success: bool
    deleted_count: int = 0
    bytes_deleted: int = 0
    error_code: str | None = None
    message: str | None = None


@dataclass(slots=True, frozen=True)
class LocalDeletionReport:
    deleted_count: int
    failed_count: int
    bytes_deleted: int
    outcomes: tuple[LocalDeletionOutcome, ...]


@dataclass(slots=True, frozen=True)
class _DeletionEntry:
    row_id: int
    row_type: str
    root: str
    relative_path: str
    path: Path
    size: int
    sha256: str | None


class LocalDeletionManager:
    def __init__(self, repository: StateRepository, account: AccountConfig) -> None:
        self.repository = repository
        self.account = account
        self.destination = account.destination.path.resolve()
        self.jpeg_root = (account.media.jpeg_path or self.destination).resolve()

    def execute(self, tasks: list[LocalDeletionTask]) -> LocalDeletionReport:
        outcomes = tuple(self._delete_asset(task) for task in tasks)
        return LocalDeletionReport(
            deleted_count=sum(outcome.deleted_count for outcome in outcomes),
            failed_count=sum(not outcome.success for outcome in outcomes),
            bytes_deleted=sum(outcome.bytes_deleted for outcome in outcomes),
            outcomes=outcomes,
        )

    def _delete_asset(self, task: LocalDeletionTask) -> LocalDeletionOutcome:
        try:
            local_files = list(task.local_files)
            entries = self._preflight(task.asset.asset_id, local_files)
            self.repository.prepare_local_deletion(
                self.account.id,
                task.asset.library_id,
                task.asset.asset_id,
                [item.id for item in local_files],
                [artifact.id for item in local_files for artifact in item.artifacts],
            )
        except (HarborError, OSError, KeyError, ValueError) as exc:
            code = getattr(exc, "code", ErrorCode.DATA_INTEGRITY_ERROR)
            code_value = code.value if isinstance(code, ErrorCode) else str(code)
            LOGGER.warning(
                f"跳过本地删除：{task.asset.filename}；Asset={task.asset.asset_id}；原因：{exc}"
            )
            return LocalDeletionOutcome(
                task,
                False,
                error_code=code_value,
                message=str(exc),
            )

        deleted_count = 0
        bytes_deleted = 0
        errors: list[str] = []
        for entry in entries:
            try:
                if entry.path.exists():
                    entry.path.unlink()
                    deleted_count += 1
                    bytes_deleted += entry.size
                    LOGGER.info(f"已删除本地文件：{display_host_path(entry.path)}")
                self._set_status(entry, "DELETED_REMOTE")
                if entry.row_type == "local_file":
                    self._delete_partial(entry.path)
            except OSError as exc:
                self._set_status(entry, "DELETE_FAILED")
                errors.append(f"{display_host_path(entry.path)}：{exc}")

        if errors:
            return LocalDeletionOutcome(
                task,
                False,
                deleted_count,
                bytes_deleted,
                ErrorCode.FILE_PERMISSION_ERROR.value,
                "；".join(errors),
            )
        return LocalDeletionOutcome(task, True, deleted_count, bytes_deleted)

    def _preflight(
        self,
        asset_id: str,
        local_files: list[ManagedLocalFile],
    ) -> list[_DeletionEntry]:
        entries: list[_DeletionEntry] = []
        for local_file in local_files:
            path = self._safe_path("destination", local_file.relative_path)
            entries.append(
                _DeletionEntry(
                    local_file.id,
                    "local_file",
                    "destination",
                    local_file.relative_path,
                    path,
                    local_file.size,
                    local_file.sha256,
                )
            )
            for artifact in local_file.artifacts:
                entries.append(
                    _DeletionEntry(
                        artifact.id,
                        "artifact",
                        artifact.root,
                        artifact.relative_path,
                        self._safe_path(artifact.root, artifact.relative_path),
                        artifact.size,
                        artifact.sha256,
                    )
                )
        for entry in entries:
            owners = self.repository.local_path_asset_ids(
                self.account.id,
                root=entry.root,
                relative_path=entry.relative_path,
            )
            if owners != {asset_id}:
                raise HarborError(
                    f"本地路径被多个 Asset 共用，拒绝删除：{entry.path}",
                    ErrorCode.DATA_INTEGRITY_ERROR,
                )
            if entry.path.is_symlink():
                raise HarborError(
                    f"拒绝删除符号链接：{entry.path}",
                    ErrorCode.FILE_PERMISSION_ERROR,
                )
            if not entry.path.exists():
                continue
            if not entry.path.is_file():
                raise HarborError(
                    f"本地删除目标不是普通文件：{entry.path}",
                    ErrorCode.FILE_PERMISSION_ERROR,
                )
            if not entry.sha256:
                raise HarborError(
                    f"本地文件缺少已验证哈希：{entry.path}",
                    ErrorCode.DATA_INTEGRITY_ERROR,
                )
            size, sha256 = verify_file(
                entry.path,
                expected_size=entry.size,
                expected_checksum=entry.sha256,
                chunk_size=DOWNLOAD_CHUNK_SIZE,
            )
            if size != entry.size or sha256 != entry.sha256:
                raise HarborError(
                    f"本地文件已修改，拒绝删除：{entry.path}",
                    ErrorCode.DATA_INTEGRITY_ERROR,
                )
        return entries

    def _safe_path(self, root_name: str, relative_path: str) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise HarborError("本地删除路径无效", ErrorCode.FILE_PERMISSION_ERROR)
        root = self.destination if root_name == "destination" else self.jpeg_root
        if root_name not in {"destination", "jpeg"}:
            raise HarborError("本地删除根目录无效", ErrorCode.FILE_PERMISSION_ERROR)
        target = root / relative
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise HarborError(
                    f"拒绝删除符号链接路径：{current}",
                    ErrorCode.FILE_PERMISSION_ERROR,
                )
        resolved = target.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise HarborError("本地删除路径越过允许目录", ErrorCode.FILE_PERMISSION_ERROR)
        return target

    def _set_status(self, entry: _DeletionEntry, status: str) -> None:
        if entry.row_type == "local_file":
            self.repository.set_local_file_status(entry.row_id, status)
        else:
            self.repository.set_local_artifact_status(entry.row_id, status)

    @staticmethod
    def _delete_partial(target: Path) -> None:
        partial = target.with_name(f"{target.name}.part")
        if partial.is_symlink():
            return
        if partial.is_file():
            partial.unlink()
