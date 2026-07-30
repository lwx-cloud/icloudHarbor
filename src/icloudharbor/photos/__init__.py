from __future__ import annotations

__all__ = ["PhotosEngine", "SyncPlan"]


def __getattr__(name: str) -> object:
    if name == "PhotosEngine":
        from icloudharbor.photos.engine import PhotosEngine

        return PhotosEngine
    if name == "SyncPlan":
        from icloudharbor.photos.planner import SyncPlan

        return SyncPlan
    raise AttributeError(name)
