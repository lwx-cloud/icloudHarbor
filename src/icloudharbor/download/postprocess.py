"""Safe local post-processing for downloaded media."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import structlog

from icloudharbor.config.models import AccountConfig
from icloudharbor.observability.paths import display_host_path

LOGGER = structlog.get_logger(__name__)


class MediaPostProcessor:
    def __init__(self, account: AccountConfig) -> None:
        self.account = account
        self.destination = account.destination.path.resolve()
        self.protected_relative_paths: set[Path] = set()

    def protect_download_paths(self, paths: set[Path]) -> None:
        self.protected_relative_paths = {Path(path.as_posix()) for path in paths}

    def prepare_parent(self, parent: Path) -> None:
        parent.mkdir(parents=True, exist_ok=True)
        mode = self.account.destination.directory_permissions
        if mode is None:
            return
        current = parent.resolve()
        roots = [self.destination]
        if self.account.media.jpeg_path is not None:
            roots.insert(0, self.account.media.jpeg_path.resolve())
        root = next((candidate for candidate in roots if current.is_relative_to(candidate)), None)
        if root is None:
            return
        while current.is_relative_to(root):
            current.chmod(mode)
            if current == root:
                break
            current = current.parent

    def process_download(self, target: Path, relative_path: Path) -> None:
        self._apply_file_mode(target)
        jpeg, jpeg_created = self.ensure_jpeg(target, relative_path)
        if self.account.destination.synology_photos_app_fix:
            os.utime(target, None)
            if jpeg is not None and jpeg_created:
                os.utime(jpeg, None)

    def process_existing(self, target: Path, relative_path: Path) -> None:
        self.prepare_parent(target.parent)
        self._apply_file_mode(target)
        jpeg, _ = self.ensure_jpeg(target, relative_path)
        if jpeg is not None:
            self._apply_file_mode(jpeg)

    def ensure_jpeg(self, source: Path, relative_path: Path) -> tuple[Path | None, bool]:
        media = self.account.media
        if not media.convert_heic_to_jpeg or source.suffix.lower() not in {".heic", ".heif"}:
            return None, False
        target = self._jpeg_target(relative_path)
        if target.is_file():
            return target, False
        self.prepare_parent(target.parent)
        temporary = target.with_name(f".{target.name}.part")
        try:
            self._convert_heic(source, temporary, media.jpeg_quality)
            self._apply_file_mode(temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        LOGGER.info(f"已生成 JPEG：{display_host_path(target)}")
        return target, True

    def _jpeg_target(self, relative_path: Path) -> Path:
        root = (self.account.media.jpeg_path or self.destination).resolve()
        jpeg_relative = relative_path.with_suffix(".JPG")
        if root == self.destination and jpeg_relative in self.protected_relative_paths:
            jpeg_relative = jpeg_relative.with_name(f"{jpeg_relative.stem}_from_HEIC.JPG")
            counter = 2
            while jpeg_relative in self.protected_relative_paths:
                jpeg_relative = jpeg_relative.with_name(
                    f"{relative_path.stem}_from_HEIC_{counter}.JPG"
                )
                counter += 1
        target = (root / jpeg_relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("JPEG 输出路径越过目标目录")
        return target

    def _apply_file_mode(self, path: Path) -> None:
        mode = self.account.destination.file_permissions
        if mode is not None:
            path.chmod(mode)

    @staticmethod
    def _convert_heic(source: Path, target: Path, quality: int) -> None:
        from PIL import Image
        from pillow_heif import register_heif_opener  # type: ignore[import-untyped]

        register_heif_opener(thumbnails=False)
        with Image.open(source) as image:
            exif = image.info.get("exif")
            icc_profile = image.info.get("icc_profile")
            output = image.convert("RGB")
            options: dict[str, Any] = {
                "format": "JPEG",
                "quality": quality,
                "optimize": True,
            }
            if exif:
                options["exif"] = exif
            if icc_profile:
                options["icc_profile"] = icc_profile
            output.save(target, **options)
        with target.open("r+b") as handle:
            os.fsync(handle.fileno())
