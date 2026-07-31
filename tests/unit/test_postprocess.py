from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import call, patch

from PIL import Image
from pillow_heif import register_heif_opener

from icloudharbor.config.models import AccountConfig
from icloudharbor.download.postprocess import MediaPostProcessor

CAPTURED_AT = datetime(2026, 6, 10, 8, 30, 15, tzinfo=UTC)


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

    processor.process_download(
        source,
        Path("2026/07/30/IMG_0001.HEIC"),
        CAPTURED_AT,
    )

    jpeg = tmp_path / "jpeg/2026/07/30/IMG_0001.JPG"
    assert source.is_file()
    assert jpeg.is_file()
    assert source.stat().st_mtime == CAPTURED_AT.timestamp()
    assert jpeg.stat().st_mtime == CAPTURED_AT.timestamp()
    with Image.open(jpeg) as converted:
        assert converted.format == "JPEG"
        assert converted.size == (8, 8)

    original_jpeg = jpeg.read_bytes()
    Image.new("RGB", (8, 8), color=(200, 10, 20)).save(source, format="HEIF")
    processor.process_download(
        source,
        Path("2026/07/30/IMG_0001.HEIC"),
        CAPTURED_AT,
    )
    assert jpeg.read_bytes() == original_jpeg
    assert source.stat().st_mtime == CAPTURED_AT.timestamp()
    assert jpeg.stat().st_mtime == CAPTURED_AT.timestamp()


def test_heic_conversion_does_not_overwrite_selected_jpeg(
    account_config: AccountConfig,
) -> None:
    source = account_config.destination.path / "IMG_0002.HEIC"
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color=(20, 40, 60)).save(source, format="HEIF")
    account_config.media.convert_heic_to_jpeg = True
    processor = MediaPostProcessor(account_config)
    processor.protect_download_paths({Path("IMG_0002.JPG")})

    processor.process_download(source, Path("IMG_0002.HEIC"), CAPTURED_AT)

    assert not (account_config.destination.path / "IMG_0002.JPG").exists()
    jpeg = account_config.destination.path / "IMG_0002_from_HEIC.JPG"
    assert jpeg.is_file()
    assert jpeg.stat().st_mtime == CAPTURED_AT.timestamp()


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
        processor.process_download(target, relative, CAPTURED_AT)

    if os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o640
        assert target.parent.stat().st_mode & 0o777 == 0o750
    assert touch.call_args_list == [
        call(target, None),
        call(target, (CAPTURED_AT.timestamp(), CAPTURED_AT.timestamp())),
    ]


def test_existing_media_and_generated_jpeg_get_capture_time(
    account_config: AccountConfig,
) -> None:
    relative = Path("2026/06/10/IMG_0003.HEIC")
    source = account_config.destination.path / relative
    source.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), color=(20, 40, 60)).save(source, format="HEIF")
    account_config.media.convert_heic_to_jpeg = True
    processor = MediaPostProcessor(account_config)

    processor.process_existing(source, relative, CAPTURED_AT)

    jpeg = source.with_suffix(".JPG")
    assert source.stat().st_mtime == CAPTURED_AT.timestamp()
    assert jpeg.stat().st_mtime == CAPTURED_AT.timestamp()
