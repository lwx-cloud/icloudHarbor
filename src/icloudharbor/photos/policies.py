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
    explicit_sizes = media.photo_size is not None
    requested_sizes = set(media.photo_size or ("original",))
    is_live_photo = bool(asset.metadata.get("is_live_photo"))
    # 记录已选中 Live Photo 版本, 同版本泛型资源不再重复选取
    live_photo_versions: set[str] = set()
    known_types = {
        "live_photo_image",
        "live_photo_video",
        "video_original",
        "video_medium",
        "video_thumbnail",
        "video_adjusted",
        "raw_original",
        "jpeg_alternative",
        "photo_original",
        "photo_medium",
        "photo_thumbnail",
        "photo_adjusted",
        "xmp_sidecar",
    }

    for resource in asset.resources:
        resource_type = resource.resource_type
        if resource_type in {"live_photo_image", "live_photo_video"}:
            if media.live_photos and _resource_size(resource) == media.live_photo_size:
                selected.append(resource)
                live_photo_versions.add(resource.version)
            continue
        # 泛型 photo_*/video_*: 同版本已有 live_photo 资源则跳过
        if (
            is_live_photo
            and resource_type.startswith(("photo_", "video_"))
            and media.live_photos
            and _resource_size(resource) == media.live_photo_size
            and resource.version not in live_photo_versions
        ):
            selected.append(resource)
            continue
        # RAW/JPEG companions follow raw.mode; an explicit photo_size list must
        # also contain "alternative" to include them.
        if resource_type == "raw_original":
            if media.raw.mode in {"raw_only", "both", "prefer_raw"} and (
                not explicit_sizes or "alternative" in requested_sizes
            ):
                selected.append(resource)
            continue
        if resource_type == "jpeg_alternative":
            if media.raw.mode in {"jpeg_only", "both", "prefer_jpeg"} and (
                not explicit_sizes or "alternative" in requested_sizes
            ):
                selected.append(resource)
            continue
        if resource_type == "photo_original" and media.raw.mode == "raw_only":
            continue
        if resource_type.startswith("video_") and not media.videos:
            continue
        size_by_type = {
            "photo_original": "original",
            "photo_medium": "medium",
            "photo_thumbnail": "thumb",
            "photo_adjusted": "adjusted",
            "video_original": "original",
            "video_medium": "medium",
            "video_thumbnail": "thumb",
            "video_adjusted": "adjusted",
        }
        if size_by_type.get(resource_type) in requested_sizes:
            selected.append(resource)

    # If a third-party adapter only offered an unknown generic original
    # resource, retain it without overriding explicit media policies.
    if not selected and asset.resources:
        originals = [
            resource
            for resource in asset.resources
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
