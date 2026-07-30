from __future__ import annotations

__all__ = ["DownloadManager", "DownloadReport"]


def __getattr__(name: str) -> object:
    if name in __all__:
        from icloudharbor.download.manager import DownloadManager, DownloadReport

        return {"DownloadManager": DownloadManager, "DownloadReport": DownloadReport}[name]
    raise AttributeError(name)
