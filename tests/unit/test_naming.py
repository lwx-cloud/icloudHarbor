from __future__ import annotations

from pathlib import Path

from tests.conftest import make_asset

from icloudharbor.config.models import AccountConfig
from icloudharbor.photos.naming import PathNamer, sanitize_segment


def test_safe_unicode_name_and_date_folder(account_config: AccountConfig) -> None:
    asset, _ = make_asset(filename="家庭:照片.JPG")
    resource = asset.resources[0]
    path = PathNamer(account_config).relative_path(asset, resource)
    assert path == Path("2026/07/29/家庭_照片.JPG")


def test_reserved_and_control_names_are_sanitized() -> None:
    assert sanitize_segment("NUL") == "_NUL"
    assert sanitize_segment("a/b\x00c") == "a_b_c"


def test_conflict_suffix_is_deterministic(account_config: AccountConfig) -> None:
    asset, _ = make_asset(asset_id="some-A1B2C3D4")
    namer = PathNamer(account_config)
    assert namer.resolve_conflict(Path("IMG.JPG"), asset) == Path("IMG_A1B2C3D4.JPG")
