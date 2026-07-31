"""Pure-ish synchronization planning with local idempotency checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from icloudharbor.config.models import AccountConfig
from icloudharbor.database.repository import LocalFileState, StateRepository
from icloudharbor.photos.naming import PathNamer
from icloudharbor.photos.policies import asset_allowed, select_resources
from icloudharbor.protocol.models import RemoteAsset, RemoteResource


@dataclass(slots=True, frozen=True)
class DownloadTask:
    asset: RemoteAsset
    resource: RemoteResource
    relative_path: Path
    repair: bool = False


@dataclass(slots=True)
class SyncPlan:
    downloads: list[DownloadTask] = field(default_factory=list)
    updates: list[DownloadTask] = field(default_factory=list)
    skips: list[DownloadTask] = field(default_factory=list)
    adoptions: list[DownloadTask] = field(default_factory=list)
    local_quarantines: list[Path] = field(default_factory=list)
    remote_delete_candidates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def download_count(self) -> int:
        return len(self.downloads) + len(self.updates)

    @property
    def estimated_bytes(self) -> int:
        return sum(task.resource.size or 0 for task in [*self.downloads, *self.updates])


class AssetPlanner:
    def __init__(self, repository: StateRepository) -> None:
        self.repository = repository

    def build(self, assets: list[RemoteAsset], account: AccountConfig) -> SyncPlan:
        plan = SyncPlan()
        namer = PathNamer(account)
        reserved: set[Path] = set()
        destination = account.destination.path

        for asset in assets:
            if not asset_allowed(asset, account):
                continue
            resources = select_resources(asset, account)
            if not resources:
                plan.warnings.append(f"Asset {asset.asset_id} 没有符合策略的资源")
            for resource in resources:
                relative = namer.relative_path(asset, resource)
                state = self.repository.get_local_file(
                    account.id,
                    asset.library_id,
                    asset.asset_id,
                    resource.resource_type,
                    resource.version,
                )
                if state:
                    relative = Path(state.relative_path)
                    task = DownloadTask(asset, resource, relative)
                    if self._is_complete(destination / relative, state, resource):
                        plan.skips.append(task)
                        reserved.add(relative)
                        continue
                    plan.updates.append(DownloadTask(asset, resource, relative, repair=True))
                    reserved.add(relative)
                    continue

                candidate = destination / relative
                if relative in reserved or candidate.exists():
                    # 磁盘上已有文件, 直接认领到数据库避免重下.
                    # 不要求远端 size 匹配: 远端可能不返回 size,
                    # 且网络文件系统的 stat 可能不准确.
                    # 重新下载并重命名(旧行为)远比认领更差.
                    if relative not in reserved and candidate.is_file():
                        sha256_hash = file_sha256(candidate)
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
                        reserved.add(relative)
                        continue
                    relative = namer.resolve_conflict(relative, asset)
                    counter = 2
                    while relative in reserved or (destination / relative).exists():
                        relative = relative.with_name(f"{relative.stem}_{counter}{relative.suffix}")
                        counter += 1
                reserved.add(relative)
                plan.downloads.append(DownloadTask(asset, resource, relative))
        return plan

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
        if resource.size is not None and actual_size != resource.size:
            return False
        expected_hash = state.sha256
        if expected_hash:
            return file_sha256(path) == expected_hash
        return True


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
