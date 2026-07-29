from __future__ import annotations

from pathlib import Path


def read_secret(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"Secret 文件为空：{path}")
    return value
