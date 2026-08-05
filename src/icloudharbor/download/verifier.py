from __future__ import annotations

import hashlib
from pathlib import Path

import structlog

from icloudharbor.protocol.exceptions import ErrorCode, HarborError

LOGGER = structlog.get_logger(__name__)


def verify_file(
    path: Path,
    *,
    expected_size: int | None,
    expected_checksum: str | None,
    chunk_size: int,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            size += len(chunk)
            digest.update(chunk)
    sha256 = digest.hexdigest()
    LOGGER.debug(
        f"校验完成：{path.name}；大小 {size}；SHA-256 {sha256[:12]}…",
    )
    if expected_size is not None and size != expected_size:
        raise HarborError(
            f"资源大小不一致：期望 {expected_size}，实际 {size}",
            ErrorCode.DATA_INTEGRITY_ERROR,
        )
    if expected_checksum:
        normalized = expected_checksum.lower().removeprefix("sha256:")
        if (
            len(normalized) == 64
            and all(c in "0123456789abcdef" for c in normalized)
            and sha256 != normalized
        ):
            raise HarborError("资源 SHA-256 校验失败", ErrorCode.DATA_INTEGRITY_ERROR)
    return size, sha256
