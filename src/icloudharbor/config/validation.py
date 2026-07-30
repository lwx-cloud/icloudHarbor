"""Human-readable configuration value parsing."""

from __future__ import annotations

import re
from datetime import timedelta

_SIZE_UNITS = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}
_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


def parse_size(value: int | str) -> int:
    """Return a byte count from values such as ``1MB`` or ``10 GiB``."""
    if isinstance(value, bool):
        raise ValueError("布尔值不是合法的容量")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("容量不能为负数")
        return value
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?i?b)\s*", value, re.I)
    if not match:
        raise ValueError(f"无法识别容量：{value!r}")
    return int(float(match.group(1)) * _SIZE_UNITS[match.group(2).upper()])


def parse_duration(value: int | str | timedelta) -> timedelta:
    """Return a timedelta from seconds or compact values such as ``30d``."""
    if isinstance(value, timedelta):
        return value
    if isinstance(value, bool):
        raise ValueError("布尔值不是合法的时长")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("时长不能为负数")
        return timedelta(seconds=value)
    iso = re.fullmatch(
        r"\s*P(?:(\d+(?:\.\d+)?)D)?"
        r"(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?"
        r"(?:(\d+(?:\.\d+)?)S)?)?\s*",
        value,
        re.I,
    )
    if iso and any(part is not None for part in iso.groups()):
        days, hours, minutes, seconds = (
            float(part) if part is not None else 0.0 for part in iso.groups()
        )
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*", value, re.I)
    if not match:
        raise ValueError(f"无法识别时长：{value!r}")
    return timedelta(seconds=float(match.group(1)) * _DURATION_UNITS[match.group(2).lower()])


def parse_file_mode(value: int | str) -> int:
    """Return a POSIX permission mode from ``750``, ``0750`` or an integer."""

    if isinstance(value, bool):
        raise ValueError("布尔值不是合法的权限模式")
    if isinstance(value, int):
        if 0 <= value <= 0o777:
            return value
        raise ValueError("权限模式必须在 0000 到 0777 之间")
    normalized = value.strip().lower()
    if normalized.startswith("0o"):
        normalized = normalized[2:]
    if not re.fullmatch(r"[0-7]{3,4}", normalized):
        raise ValueError(f"无法识别权限模式：{value!r}")
    parsed = int(normalized, 8)
    if parsed > 0o777:
        raise ValueError("权限模式必须在 0000 到 0777 之间")
    return parsed
