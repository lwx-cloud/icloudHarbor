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


def test_resource_policy_selects_requested_photo_and_live_sizes(
    account_config: AccountConfig,
) -> None:
    resources = (
        RemoteResource("photo-original", "a", "photo_original", "original", "a.heic"),
        RemoteResource("photo-medium", "a", "photo_medium", "medium", "a.heic"),
        RemoteResource("photo-thumb", "a", "photo_thumbnail", "thumb", "a.heic"),
        RemoteResource("video-thumb", "a", "video_thumbnail", "thumb", "a.mov"),
        RemoteResource("live-original", "a", "live_photo_video", "original_video", "a.mov"),
        RemoteResource("live-medium", "a", "live_photo_video", "medium_video", "a.mov"),
        RemoteResource("live-thumb", "a", "live_photo_video", "thumb_video", "a.mov"),
    )
    asset, _ = make_asset(asset_id="a", resources=resources)
    account_config.media.photo_size = ["medium", "thumb"]
    account_config.media.live_photo_size = "original"

    selected = select_resources(asset, account_config)

    assert {resource.resource_id for resource in selected} == {
        "photo-medium",
        "photo-thumb",
        "video-thumb",
        "live-original",
    }


def test_live_photo_size_selects_matching_image_and_video_companions(
    account_config: AccountConfig,
) -> None:
    resources = (
        RemoteResource("image-original", "a", "live_photo_image", "original", "a.heic"),
        RemoteResource("image-medium", "a", "photo_medium", "medium", "a.heic"),
        RemoteResource("video-original", "a", "live_photo_video", "original_video", "a.mov"),
        RemoteResource("video-medium", "a", "live_photo_video", "medium_video", "a.mov"),
    )
    asset, _ = make_asset(asset_id="a", resources=resources)
    asset = replace(asset, metadata={"is_live_photo": True})
    account_config.media.live_photo_size = "medium"

    selected = select_resources(asset, account_config)

    assert {resource.resource_id for resource in selected} == {
        "image-medium",
        "video-medium",
    }
