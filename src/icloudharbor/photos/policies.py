"""Media and user filter policies."""

from __future__ import annotations

from icloudharbor.config.models import AccountConfig
from icloudharbor.protocol.models import RemoteAsset, RemoteResource


def asset_allowed(asset: RemoteAsset, account: AccountConfig) -> bool:
    filters = account.filters
    if bool(asset.metadata.get("is_live_photo")) and not account.media.live_photos:
        return False
    if asset.deleted:
        return False
    if asset.hidden and not filters.include_hidden:
        return False
    if filters.favorites_only and not asset.favorite:
        return False
    if filters.created_after and asset.created_at < filters.created_after:
        return False
    if filters.created_before and asset.created_at > filters.created_before:
        return False
    return not (asset.media_type == "video" and not account.media.videos)


def select_resources(asset: RemoteAsset, account: AccountConfig) -> tuple[RemoteResource, ...]:
    selected: list[RemoteResource] = []
    media = account.media
    requested_sizes = set(media.photo_size or ("original",))
    is_live_photo = bool(asset.metadata.get("is_live_photo"))
    resources = tuple(dict.fromkeys(asset.resources))
    handled: set[RemoteResource] = set()
    known_types = {
        "live_photo_image",
        "live_photo_video",
        "video_original",
        "video_medium",
        "video_thumbnail",
        "video_adjusted",
        "video_poster_medium",
        "video_poster_thumb",
        "raw_original",
        "jpeg_alternative",
        "photo_original",
        "photo_medium",
        "photo_thumbnail",
        "photo_adjusted",
        "xmp_sidecar",
    }

    # pyicloud/iCloudPD expose a Live Photo as an image and a companion video.
    # Select the same requested size for both components and do not also treat
    # their generic photo/video aliases as independent downloads.
    for resource in resources:
        resource_type = resource.resource_type
        live_component = resource_type in {"live_photo_image", "live_photo_video"} or (
            is_live_photo and resource_type.startswith(("photo_", "video_"))
        )
        if live_component:
            handled.add(resource)
            if media.live_photos and _resource_size(resource) == media.live_photo_size:
                selected.append(resource)

    # Match iCloudPD's RAW handling: Apple may put RAW and JPEG in either the
    # original or alternative slot, so choose by actual resource type rather
    # than assuming that "alternative" always means JPEG.
    raw_resources = [
        resource
        for resource in resources
        if resource not in handled and resource.resource_type == "raw_original"
    ]
    jpeg_companions = [
        resource
        for resource in resources
        if resource not in handled
        and resource.resource_type in {"photo_original", "jpeg_alternative"}
    ]
    if raw_resources:
        handled.update(raw_resources)
        handled.update(jpeg_companions)
        raw_mode = media.raw.mode
        if raw_mode == "raw_only":
            selected.extend(raw_resources)
        elif raw_mode == "jpeg_only":
            selected.extend(jpeg_companions)
        elif raw_mode == "both":
            selected.extend(raw_resources)
            selected.extend(jpeg_companions)
        elif raw_mode == "prefer_raw":
            selected.append(raw_resources[0])
        elif jpeg_companions:
            selected.append(jpeg_companions[0])
        else:
            selected.append(raw_resources[0])

    for resource in resources:
        if resource in handled:
            continue
        resource_type = resource.resource_type
        if media.raw.mode == "raw_only" and (
            resource_type.startswith("photo_") or resource_type == "jpeg_alternative"
        ):
            continue
        if resource_type.startswith("video_") and not media.videos:
            continue
        # Video poster frames (JPEG previews): opt-in, disabled by default.
        # When enabled, medium_image is preferred (higher quality than thumb_image).
        if resource_type in {"video_poster_thumb", "video_poster_medium"}:
            if media.video_poster_frames and resource_type == "video_poster_medium":
                selected.append(resource)
            continue
        size_by_type = {
            "photo_original": "original",
            "photo_medium": "medium",
            "photo_thumbnail": "thumb",
            "photo_adjusted": "adjusted",
            "jpeg_alternative": "alternative",
            "video_original": "original",
            "video_medium": "medium",
            "video_thumbnail": "thumb",
            "video_adjusted": "adjusted",
        }
        if size_by_type.get(resource_type) in requested_sizes:
            selected.append(resource)

    # If a third-party adapter only offered an unknown generic original
    # resource, retain it without overriding explicit media policies.
    if not selected and resources:
        originals = [
            resource
            for resource in resources
            if resource.version == "original" and resource.resource_type not in known_types
        ]
        selected.extend(originals[:1])
    return tuple(dict.fromkeys(selected))


def _resource_size(resource: RemoteResource) -> str:
    version = resource.version.lower()
    if "thumb" in version:
        return "thumb"
    if "medium" in version:
        return "medium"
    return "original"
