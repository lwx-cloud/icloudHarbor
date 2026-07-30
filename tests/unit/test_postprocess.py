from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pillow_heif import register_heif_opener

from icloudharbor.config.models import AccountConfig
from icloudharbor.download.postprocess import MediaPostProcessor


def test_heic_is_converted_to_jpeg_in_configured_directory(
    account_config: AccountConfig,
    tmp_path: Path,
) -> None:
    register_heif_opener(thumbnails=False)
    source = account_config.destination.path / "2026/07/30/IMG_0001.HEIC"
    source.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), color=(20, 40, 60)).save(source, format="HEIF")
    account_config.media.convert_heic_to_jpeg = True
    account_config.media.jpeg_path = tmp_path / "jpeg"
    account_config.media.jpeg_quality = 85
    processor = MediaPostProcessor(account_config)

    processor.process_download(source, Path("2026/07/30/IMG_0001.HEIC"))

    jpeg = tmp_path / "jpeg/2026/07/30/IMG_0001.JPG"
    assert source.is_file()
    assert jpeg.is_file()
    with Image.open(jpeg) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (8, 8)

    original_jpeg = jpeg.read_bytes()
    Image.new("RGB", (8, 8), color=(200, 10, 20)).save(source, format="HEIF")
    processor.process_download(source, Path("2026/07/30/IMG_0001.HEIC"))
    assert jpeg.read_bytes() == original_jpeg


def test_heic_conversion_does_not_overwrite_selected_jpeg(
    account_config: AccountConfig,
) -> None:
    source = account_config.destination.path / "IMG_0002.HEIC"
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color=(20, 40, 60)).save(source, format="HEIF")
    account_config.media.convert_heic_to_jpeg = True
    processor = MediaPostProcessor(account_config)
    processor.protect_download_paths({Path("IMG_0002.JPG")})

    processor.process_download(source, Path("IMG_0002.HEIC"))

    assert not (account_config.destination.path / "IMG_0002.JPG").exists()
    assert (account_config.destination.path / "IMG_0002_from_HEIC.JPG").is_file()


def test_postprocessor_applies_modes_and_synology_touch(
    account_config: AccountConfig,
) -> None:
    relative = Path("2026/07/30/IMG_0002.JPG")
    target = account_config.destination.path / relative
    account_config.destination.directory_permissions = 0o750
    account_config.destination.file_permissions = 0o640
    account_config.destination.synology_photos_app_fix = True
    processor = MediaPostProcessor(account_config)

    processor.prepare_parent(target.parent)
    target.write_bytes(b"photo")
    with patch("icloudharbor.download.postprocess.os.utime") as touch:
        processor.process_download(target, relative)

    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o640
        assert target.parent.stat().st_mode & 0o777 == 0o750
    touch.assert_called_once_with(target, None)
