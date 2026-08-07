"""Safe and deterministic local path rendering."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from icloudharbor.config.models import AccountConfig
from icloudharbor.protocol.models import RemoteAsset, RemoteResource

_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*]')


def sanitize_segment(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = _CONTROL_RE.sub("_", value)
    value = _ILLEGAL_RE.sub("_", value)
    value = value.rstrip(" .")
    if not value or value in {".", ".."}:
        value = "_"
    stem = value.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        value = f"_{value}"
    return value[:240]


def append_suffix(filename: str, suffix: str) -> str:
    path = Path(filename)
    return f"{path.stem}_{suffix}{path.suffix}"


class PathNamer:
    def __init__(self, account: AccountConfig) -> None:
        self.account = account

    def relative_path(self, asset: RemoteAsset, resource: RemoteResource) -> Path:
        original = Path(resource.filename or asset.filename).name
        extension = Path(original).suffix
        context: dict[str, Any] = {
            "account": self.account.id,
            "library": asset.library_id,
            "album": str(asset.metadata.get("album_name", "")),
            "asset_id": asset.asset_id,
            "asset_id_short": self.short_id(asset.asset_id),
            "created": asset.created_at,
            "added": asset.added_at or asset.created_at,
            "original_name": original,
            "stem": Path(original).stem,
            "extension": extension,
            "media_type": asset.media_type,
            "resource_type": resource.resource_type,
            "version": resource.version,
        }
        try:
            folder_raw = self.account.naming.folder_structure.format_map(context)
            filename_raw = self.account.naming.filename.format_map(context)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"命名模板无法渲染：{exc}") from exc

        folder_parts = [
            sanitize_segment(part)
            for part in folder_raw.replace("\\", "/").split("/")
            if part not in {"", "."}
        ]
        filename = sanitize_segment(filename_raw)
        # A template based on the Asset image name must still preserve the
        # resource extension for Live Photo video and RAW companions.
        if Path(filename).suffix.lower() != Path(original).suffix.lower():
            filename = f"{Path(filename).stem}{Path(original).suffix}"
        if self.account.naming.conflict_policy == "always_asset_id":
            filename = append_suffix(filename, self.short_id(asset.asset_id))
        result = Path(*folder_parts, filename)
        if result.is_absolute() or ".." in result.parts:
            raise ValueError("命名模板生成了目标目录外的路径")
        return result

    def resolve_conflict(
        self,
        relative: Path,
        asset: RemoteAsset,
        resource: RemoteResource | None = None,
        *,
        same_asset: bool = False,
    ) -> Path:
        policy = self.account.naming.conflict_policy
        if policy == "error":
            raise FileExistsError(f"目标文件已存在：{relative}")
        asset_suffix = self.short_id(asset.asset_id)
        if same_asset and resource is not None:
            version = sanitize_segment(resource.version).strip("_") or sanitize_segment(
                resource.resource_type
            ).strip("_")
            suffix = f"{version}_{asset_suffix}"
        elif policy == "timestamp":
            suffix = f"{asset.created_at:%Y%m%d_%H%M%S}_{asset_suffix}"
        else:
            suffix = asset_suffix
        return relative.with_name(append_suffix(relative.name, suffix))

    @staticmethod
    def short_id(asset_id: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9]", "", asset_id)
        return (cleaned[-8:] if cleaned else "UNKNOWN").upper()
