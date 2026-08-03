"""Concise, redacted configuration summaries for setup and container logs."""

from __future__ import annotations

import os
import platform
from pathlib import Path

import structlog

from icloudharbor import __version__
from icloudharbor.config.models import AccountConfig, AppConfig, ScheduleConfig
from icloudharbor.observability.paths import display_host_path
from icloudharbor.security.redaction import redact

LOGGER = structlog.get_logger(__name__)


def startup_summary(
    config: AppConfig,
    account: AccountConfig,
    config_path: Path,
) -> list[str]:
    apple_id = redact(account.apple_id) if config.security.redact_apple_id else account.apple_id
    config_root = (
        config.runtime.database.parent.parent
        if config.runtime.database.parent.name == "database"
        else config.runtime.database.parent
    )
    destination = display_host_path(account.destination.path)
    region = {
        "global": "全球（icloud.com）",
        "china": "中国大陆（icloud.com.cn）",
    }[account.region]
    configured_sizes: tuple[str, ...] = (
        tuple(str(size) for size in account.media.photo_size)
        if account.media.photo_size
        else ("original",)
    )
    photo_size = ",".join(configured_sizes)
    notifications = [channel.type for channel in config.notifications.channels if channel.enabled]
    directory_mode = _mode(account.destination.directory_permissions)
    file_mode = _mode(account.destination.file_permissions)
    album_scope = ",".join(account.filters.albums) if account.filters.albums else "全部相册"
    exclusions = (
        ",".join(account.filters.exclude_albums) if account.filters.exclude_albums else "无"
    )
    jpeg_path = display_host_path(account.media.jpeg_path or account.destination.path)

    lines = [
        f"iCloudHarbor 版本：{__version__}",
        f"运行环境：{platform.system()} {platform.release()} / Python {platform.python_version()}",
        f"配置文件：{config_path}",
        f"Apple Account：{apple_id}",
        f"Session 目录：{config_root / 'sessions' / account.id}",
        f"运行身份：UID={_uid()}，GID={_gid()}",
        f"iCloud 区域：{region}",
        f"下载目录：{destination}",
        f"目录结构：{account.naming.folder_structure}",
        f"文件名规则：{account.naming.filename}",
        f"同步计划：{_schedule(account)}",
        f"图库：{','.join(account.libraries)}",
    ]

    if account.filters.albums:
        lines.append(f"包含相册：{album_scope}")
    if account.filters.exclude_albums:
        lines.append(f"排除相册：{exclusions}")

    media_parts: list[str] = []
    if not account.media.videos:
        media_parts.append("视频=关闭")
    if not account.media.live_photos:
        media_parts.append("Live Photo=关闭")
    if account.media.raw.mode != "both":
        media_parts.append(f"RAW={account.media.raw.mode}")
    if media_parts:
        lines.append(f"媒体覆盖：{'; '.join(media_parts)}")

    lines.append(f"媒体尺寸：照片={photo_size}；Live Photo 尺寸={account.media.live_photo_size}")

    if account.media.convert_heic_to_jpeg:
        lines.append(f"HEIC 转 JPEG：启用；目录={jpeg_path}；质量={account.media.jpeg_quality}")

    if (
        account.destination.directory_permissions is not None
        or account.destination.file_permissions is not None
    ):
        lines.append(f"文件权限：目录={directory_mode}，文件={file_mode}")

    if account.filters.recent_only:
        lines.append(f"最近项目：{account.filters.recent_only}")
    if account.filters.until_found:
        lines.append(f"连续已有停止：{account.filters.until_found}")
    if account.filters.favorites_only:
        lines.append("收藏：仅下载收藏")
    if account.filters.include_hidden:
        lines.append("已隐藏：包含")

    if account.sync.download_delay > 0:
        lines.append(f"启动延迟：{account.sync.download_delay} 分钟")

    lines.append(f"iCloud 最近删除同步：{_switch(account.sync.auto_delete)}")

    if account.destination.synology_photos_app_fix:
        lines.append("Synology Photos 索引兼容：启用")

    if notifications:
        lines.append(f"通知：{','.join(notifications)}；标题={config.notifications.title}")
    else:
        lines.append("通知：关闭")

    if config.notifications.notification_days != 7:
        lines.append(f"认证临期提醒：提前 {config.notifications.notification_days} 天")

    return lines


def log_startup_summary(
    config: AppConfig,
    account: AccountConfig,
    config_path: Path,
) -> None:
    LOGGER.info("***** iCloudHarbor 容器启动 *****")
    for line in startup_summary(config, account, config_path):
        LOGGER.info(line)


def _schedule(account: AccountConfig) -> str:
    schedule = account.sync.schedule
    if schedule is None:
        return "未配置定时同步"
    if isinstance(schedule, str):
        return f"Cron {schedule}"
    if isinstance(schedule, ScheduleConfig) and schedule.interval:
        return f"每 {schedule.interval}"
    assert isinstance(schedule, ScheduleConfig)
    return f"Cron {schedule.cron}"


def _mode(value: int | None) -> str:
    return f"{value:04o}" if value is not None else "默认（umask 0022）"


def _switch(value: bool) -> str:
    return "启用" if value else "关闭"


def _uid() -> int | str:
    getter = getattr(os, "getuid", None)
    return getter() if callable(getter) else os.environ.get("IH_PUID", "unknown")


def _gid() -> int | str:
    getter = getattr(os, "getgid", None)
    return getter() if callable(getter) else os.environ.get("IH_PGID", "unknown")
