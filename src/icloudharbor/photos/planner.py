"""Pure-ish synchronization planning with local idempotency checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from icloudharbor.config.models import AccountConfig
from icloudharbor.database.repository import LocalFileState, ManagedLocalFile, StateRepository
from icloudharbor.photos.naming import PathNamer
from icloudharbor.photos.policies import asset_allowed, select_resources
from icloudharbor.protocol.models import RemoteAsset, RemoteResource

ResourceIdentity = tuple[str, str, str, str]


@dataclass(slots=True, frozen=True)
class DownloadTask:
    asset: RemoteAsset
    resource: RemoteResource
    relative_path: Path
    repair: bool = False


@dataclass(slots=True, frozen=True)
class LocalDeletionTask:
    asset: RemoteAsset
    local_files: tuple[ManagedLocalFile, ...]

    @property
    def file_count(self) -> int:
        return sum(1 + len(item.artifacts) for item in self.local_files)


@dataclass(slots=True)
class SyncPlan:
    downloads: list[DownloadTask] = field(default_factory=list)
    updates: list[DownloadTask] = field(default_factory=list)
    skips: list[DownloadTask] = field(default_factory=list)
    adoptions: list[DownloadTask] = field(default_factory=list)
    local_quarantines: list[Path] = field(default_factory=list)
    remote_delete_candidates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    local_deletions: list[LocalDeletionTask] = field(default_factory=list)
    unmatched_deleted_count: int = 0

    @property
    def download_count(self) -> int:
        return len(self.downloads) + len(self.updates)

    @property
    def estimated_bytes(self) -> int:
        return sum(task.resource.size or 0 for task in [*self.downloads, *self.updates])

    @property
    def local_delete_count(self) -> int:
        return sum(task.file_count for task in self.local_deletions)

    @property
    def local_delete_asset_count(self) -> int:
        return len(self.local_deletions)


class AssetPlanner:
    def __init__(self, repository: StateRepository) -> None:
        self.repository = repository

    def build(
        self,
        assets: list[RemoteAsset],
        account: AccountConfig,
        *,
        persist_adoptions: bool = True,
        reserved_paths: dict[Path, ResourceIdentity] | None = None,
    ) -> SyncPlan:
        plan = SyncPlan()
        namer = PathNamer(account)
        reserved = reserved_paths if reserved_paths is not None else {}
        destination = account.destination.path
        local_files = self.repository.local_files_for_assets(
            account.id,
            {(asset.library_id, asset.asset_id) for asset in assets},
        )

        for asset in assets:
            if not asset_allowed(asset, account):
                continue
            resources = select_resources(asset, account)
            if not resources:
                plan.warnings.append(f"Asset {asset.asset_id} 没有符合策略的资源")
            for resource in resources:
                identity: ResourceIdentity = (
                    asset.library_id,
                    asset.asset_id,
                    resource.resource_type,
                    resource.version,
                )
                base_relative = namer.relative_path(asset, resource)
                relative = base_relative
                state = local_files.get(
                    (
                        asset.library_id,
                        asset.asset_id,
                        resource.resource_type,
                        resource.version,
                    )
                )
                if state:
                    relative = Path(state.relative_path)
                    owner = reserved.get(relative)
                    if owner is not None and owner != identity:
                        relative = self._conflict_path(
                            namer,
                            destination,
                            base_relative,
                            asset,
                            resource,
                            reserved,
                            same_asset=owner[1] == asset.asset_id,
                        )
                        plan.updates.append(DownloadTask(asset, resource, relative, repair=True))
                        reserved[relative] = identity
                        continue
                    task = DownloadTask(asset, resource, relative)
                    if self._is_complete(destination / relative, state, resource):
                        plan.skips.append(task)
                        reserved[relative] = identity
                        continue
                    plan.updates.append(DownloadTask(asset, resource, relative, repair=True))
                    reserved[relative] = identity
                    continue

                owner = reserved.get(relative)
                if owner is not None and owner != identity:
                    relative = self._conflict_path(
                        namer,
                        destination,
                        base_relative,
                        asset,
                        resource,
                        reserved,
                        same_asset=owner[1] == asset.asset_id,
                    )
                candidate = destination / relative
                if candidate.is_file() and relative not in reserved:
                    database_owners = self.repository.local_file_owners_for_path(
                        account.id,
                        relative.as_posix(),
                    )
                    foreign_owner = next(
                        (path_owner for path_owner in database_owners if path_owner != identity),
                        None,
                    )
                    if foreign_owner is not None:
                        relative = self._conflict_path(
                            namer,
                            destination,
                            base_relative,
                            asset,
                            resource,
                            reserved,
                            same_asset=foreign_owner[1] == asset.asset_id,
                        )
                        candidate = destination / relative
                if candidate.exists():
                    # 磁盘上已有文件, 直接认领到数据库避免重下.
                    # 不要求远端 size 匹配: 远端可能不返回 size,
                    # 且网络文件系统的 stat 可能不准确.
                    # 重新下载并重命名(旧行为)远比认领更差.
                    if relative not in reserved and candidate.is_file():
                        sha256_hash = file_sha256(candidate)
                        if persist_adoptions:
                            self.repository.record_download(
                                asset,
                                resource,
                                str(relative).replace("\\", "/"),
                                candidate.stat().st_size,
                                sha256_hash,
                            )
                        task = DownloadTask(asset, resource, relative)
                        plan.skips.append(task)
                        plan.adoptions.append(task)
                        reserved[relative] = identity
                        continue
                    # Disk conflict: path exists as something other than a regular
                    # file (e.g. a directory with the same name).
                    relative = self._conflict_path(
                        namer,
                        destination,
                        base_relative,
                        asset,
                        resource,
                        reserved,
                        same_asset=False,
                    )
                    candidate = destination / relative
                    if candidate.is_file():
                        sha256_hash = file_sha256(candidate)
                        if persist_adoptions:
                            self.repository.record_download(
                                asset,
                                resource,
                                str(relative).replace("\\", "/"),
                                candidate.stat().st_size,
                                sha256_hash,
                            )
                        task = DownloadTask(asset, resource, relative)
                        plan.skips.append(task)
                        plan.adoptions.append(task)
                        reserved[relative] = identity
                        continue
                reserved[relative] = identity
                plan.downloads.append(DownloadTask(asset, resource, relative))
        return plan

    @staticmethod
    def _conflict_path(
        namer: PathNamer,
        destination: Path,
        relative: Path,
        asset: RemoteAsset,
        resource: RemoteResource,
        reserved: dict[Path, ResourceIdentity],
        *,
        same_asset: bool,
    ) -> Path:
        candidate = namer.resolve_conflict(
            relative,
            asset,
            resource,
            same_asset=same_asset,
        )
        counter = 2
        while candidate in reserved or (
            (destination / candidate).exists() and not (destination / candidate).is_file()
        ):
            candidate = candidate.with_name(f"{candidate.stem}_{counter}{candidate.suffix}")
            counter += 1
        return candidate

    def add_local_deletions(
        self,
        plan: SyncPlan,
        deleted_assets: list[RemoteAsset],
        account: AccountConfig,
        active_asset_ids: set[tuple[str, str]],
    ) -> None:
        for asset in deleted_assets:
            identity = (asset.library_id, asset.asset_id)
            if identity in active_asset_ids:
                plan.warnings.append(
                    f"Asset {asset.asset_id} 同时出现在正常图库和最近删除，已拒绝本地删除"
                )
                continue
            local_files = self.repository.managed_files_for_asset(
                account.id,
                asset.library_id,
                asset.asset_id,
            )
            if not local_files:
                plan.unmatched_deleted_count += 1
                continue
            plan.local_deletions.append(LocalDeletionTask(asset, tuple(local_files)))

    @staticmethod
    def _is_complete(
        path: Path,
        state: LocalFileState,
        resource: RemoteResource,
    ) -> bool:
        if state.status != "VERIFIED" or not path.is_file():
            return False
        actual_size = path.stat().st_size
        if actual_size != state.size:
            return False
        # Match iCloudPD's hot-path behavior: an already tracked regular file
        # with the recorded/remote size is considered present. SHA-256 is
        # calculated once during download or adoption and checked again only
        # before destructive local cleanup, not on every synchronization.
        return resource.size is None or actual_size == resource.size


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
