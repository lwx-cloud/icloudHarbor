"""Media and user filter policies."""

from __future__ import annotations

from icloudharbor.config.models import AccountConfig
from icloudharbor.protocol.models import RemoteAsset, RemoteResource


def asset_allowed(asset: RemoteAsset, account: AccountConfig) -> bool:
    filters = account.filters
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
    if asset.media_type == "photo" and not account.media.photos:
        return False
    return not (asset.media_type == "video" and not account.media.videos)


def select_resources(asset: RemoteAsset, account: AccountConfig) -> tuple[RemoteResource, ...]:
    selected: list[RemoteResource] = []
    media = account.media

    for resource in asset.resources:
        resource_type = resource.resource_type
        if resource_type in {"live_photo_image", "live_photo_video"}:
            if media.live_photos:
                selected.append(resource)
            continue
        if resource_type.startswith("video_"):
            if media.videos and (
                resource_type == "video_original"
                or (
                    media.photo_version in {"adjusted", "both"}
                    and resource_type == "video_adjusted"
                )
            ):
                selected.append(resource)
            continue
        if resource_type == "raw_original":
            if media.raw.mode in {"raw_only", "both", "prefer_raw"}:
                selected.append(resource)
            continue
        if resource_type == "jpeg_alternative":
            if media.raw.mode in {"jpeg_only", "both", "prefer_jpeg"}:
                selected.append(resource)
            continue
        if resource_type == "photo_original" and media.photo_version in {"original", "both"}:
            if media.photos and media.raw.mode != "raw_only":
                selected.append(resource)
            continue
        if (
            resource_type == "photo_adjusted"
            and media.photo_version in {"adjusted", "both"}
            and media.photos
        ):
            selected.append(resource)

    # If the adapter only offered a generic original resource, retain it.
    if not selected and asset.resources:
        originals = [r for r in asset.resources if r.version == "original"]
        selected.extend(originals[:1])
    return tuple(dict.fromkeys(selected))
