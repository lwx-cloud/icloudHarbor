"""Translate container photo paths into Docker host paths for user-facing logs."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath


def display_host_path(path: Path) -> str:
    container_path = PurePosixPath(path.as_posix())
    host_photos_path = os.environ.get("IH_PHOTOS_PATH", "").strip()
    if host_photos_path:
        try:
            inside_photo_volume = container_path.relative_to("/photos")
        except ValueError:
            pass
        else:
            host_root = PurePosixPath(host_photos_path.replace("\\", "/"))
            return (host_root / inside_photo_volume).as_posix()
    return path.as_posix()


def display_download_path(destination: Path, relative_path: Path) -> str:
    return display_host_path(destination / relative_path)
