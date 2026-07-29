from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from tests.conftest import make_asset

from icloudharbor.config.models import AccountConfig
from icloudharbor.photos.policies import asset_allowed, select_resources
from icloudharbor.protocol.models import RemoteResource


def test_asset_filters_cover_hidden_favorite_and_date(
    account_config: AccountConfig,
) -> None:
    asset, _ = make_asset()
    assert asset_allowed(asset, account_config)
    assert not asset_allowed(replace(asset, hidden=True), account_config)

    account_config.filters.include_hidden = True
    account_config.filters.favorites_only = True
    assert not asset_allowed(asset, account_config)
    favorite = replace(asset, favorite=True)
    assert asset_allowed(favorite, account_config)

    account_config.filters.created_after = datetime.now(UTC) + timedelta(days=1)
    assert not asset_allowed(favorite, account_config)


def test_resource_policy_selects_live_raw_jpeg_and_video(
    account_config: AccountConfig,
) -> None:
    resources = (
        RemoteResource("photo", "a", "photo_original", "original", "a.heic"),
        RemoteResource("raw", "a", "raw_original", "original_raw", "a.dng"),
        RemoteResource("jpeg", "a", "jpeg_alternative", "alternative", "a.jpg"),
        RemoteResource("live", "a", "live_photo_video", "original_video", "a.mov"),
        RemoteResource("video", "a", "video_original", "original", "a.mov"),
    )
    asset, _ = make_asset(asset_id="a", resources=resources)

    selected = select_resources(asset, account_config)

    assert {resource.resource_id for resource in selected} == {
        "photo",
        "raw",
        "jpeg",
        "live",
        "video",
    }

    account_config.media.raw.mode = "raw_only"
    selected = select_resources(asset, account_config)
    assert "jpeg" not in {resource.resource_id for resource in selected}
    assert "photo" not in {resource.resource_id for resource in selected}
