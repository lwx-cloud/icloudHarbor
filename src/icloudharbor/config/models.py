"""Validated public configuration model."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from icloudharbor.config.validation import parse_duration, parse_file_mode, parse_size

MOUNTED_MARKER = ".icloudharbor-mounted"
"""Fixed mount-guard marker name inside the download destination."""

DOWNLOAD_CHUNK_SIZE = 1_000_000
"""Fixed streaming chunk size (1MB) for downloads and checksum verification."""

ACCOUNT_ID_MAX_BYTES = 220
"""Leave room for credential and lock suffixes under 255-byte path component limits."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RuntimeConfig(StrictModel):
    timezone: str = "UTC"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["text", "json"] = "text"
    database: Path = Path("/config/database/icloudharbor.db")
    temp_path: Path = Path("/config/tmp")


class DestinationConfig(StrictModel):
    path: Path
    minimum_free_space: int = 10_000_000_000
    directory_permissions: int | None = None
    file_permissions: int | None = None
    synology_photos_app_fix: bool = False

    @field_validator("minimum_free_space", mode="before")
    @classmethod
    def validate_minimum_space(cls, value: object) -> int:
        if not isinstance(value, str | int) or isinstance(value, bool):
            raise ValueError("minimum_free_space 必须是字节数或 10GB 形式")
        return parse_size(value)

    @field_validator("directory_permissions", "file_permissions", mode="before")
    @classmethod
    def validate_permissions(cls, value: object) -> int | None:
        if value is None:
            return None
        if not isinstance(value, str | int) or isinstance(value, bool):
            raise ValueError("权限必须是 0750 形式的八进制模式")
        return parse_file_mode(value)


class RawConfig(StrictModel):
    mode: Literal["raw_only", "jpeg_only", "both", "prefer_raw", "prefer_jpeg"] = "both"


class MediaConfig(StrictModel):
    videos: bool = True
    live_photos: bool = True
    photo_size: list[Literal["original", "medium", "thumb", "adjusted", "alternative"]] | None = (
        None
    )
    live_photo_size: Literal["original", "medium", "thumb"] = "original"
    raw: RawConfig = Field(default_factory=RawConfig)
    convert_heic_to_jpeg: bool = False
    jpeg_path: Path | None = None
    jpeg_quality: Annotated[int, Field(ge=0, le=100)] = 100

    @field_validator("photo_size")
    @classmethod
    def validate_photo_size(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("photo_size 不能为空")
        return list(dict.fromkeys(value))


class FilterConfig(StrictModel):
    albums: list[str] = Field(default_factory=list)
    exclude_albums: list[str] = Field(default_factory=list)
    created_after: datetime | None = None
    created_before: datetime | None = None
    favorites_only: bool = False
    include_hidden: bool = False
    recent_only: Annotated[int, Field(ge=1)] | None = None
    until_found: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> FilterConfig:
        if self.created_after and self.created_before and self.created_after > self.created_before:
            raise ValueError("created_after 不能晚于 created_before")
        overlap = set(self.albums) & set(self.exclude_albums)
        if overlap:
            raise ValueError(f"相册不能同时包含和排除：{', '.join(sorted(overlap))}")
        return self


class NamingConfig(StrictModel):
    folder_structure: str = "{created:%Y/%m/%d}"
    filename: str = "{original_name}"
    conflict_policy: Literal["suffix_asset_id", "always_asset_id", "timestamp", "error"] = (
        "suffix_asset_id"
    )

    @field_validator("folder_structure")
    @classmethod
    def validate_folder_template(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or any(part == ".." for part in normalized.split("/")):
            raise ValueError("folder_structure 必须是目标目录内的相对路径")
        return value

    @field_validator("filename")
    @classmethod
    def validate_filename_template(cls, value: str) -> str:
        if not value or "/" in value or "\\" in value:
            raise ValueError("filename 模板不能包含目录分隔符")
        return value


class ScheduleConfig(StrictModel):
    interval: str | None = None
    cron: str | None = None

    @model_validator(mode="after")
    def exactly_one_schedule(self) -> ScheduleConfig:
        if bool(self.interval) == bool(self.cron):
            raise ValueError("schedule 必须且只能配置 interval 或 cron")
        if self.interval and parse_duration(self.interval) <= timedelta(0):
            raise ValueError("同步间隔必须大于 0")
        return self


class SyncConfig(StrictModel):
    mode: Literal["backup"] = "backup"
    strategy: Literal["cursor", "full"] = "cursor"
    full_scan_interval: timedelta = timedelta(days=30)
    schedule: str | ScheduleConfig | None = None
    run_on_start: bool = True
    download_delay: Annotated[int, Field(ge=0, le=60)] = 0

    @field_validator("full_scan_interval", mode="before")
    @classmethod
    def validate_full_scan_interval(cls, value: object) -> timedelta:
        if not isinstance(value, str | int | timedelta) or isinstance(value, bool):
            raise ValueError("full_scan_interval 必须是 30d 形式的时长")
        return parse_duration(value)

    @field_validator("schedule")
    @classmethod
    def validate_schedule_string(
        cls, value: str | ScheduleConfig | None
    ) -> str | ScheduleConfig | None:
        if isinstance(value, str):
            if len(value.split()) == 5:
                return value
            parse_duration(value)
            return ScheduleConfig(interval=value)
        return value


class DownloadConfig(StrictModel):
    concurrency: Annotated[int, Field(ge=1, le=8)] = 2
    timeout: Annotated[int, Field(ge=1, le=3600)] = 300
    max_retries: Annotated[int, Field(ge=0, le=20)] = 5


class AccountConfig(StrictModel):
    id: str = Field(min_length=1, max_length=ACCOUNT_ID_MAX_BYTES)
    name: str
    apple_id: str
    region: Literal["auto", "global", "china"] = "auto"
    enabled: bool = True
    libraries: list[str] = Field(default_factory=lambda: ["root"])
    destination: DestinationConfig
    media: MediaConfig = Field(default_factory=MediaConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    naming: NamingConfig = Field(default_factory=NamingConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        value = value.strip()
        unsafe = '<>:"/\\|?*'
        if (
            not value
            or value in {".", ".."}
            or value.endswith(".")
            or any(character.isspace() for character in value)
            or any(character in unsafe or ord(character) < 32 for character in value)
            or len(value.encode("utf-8")) > ACCOUNT_ID_MAX_BYTES
        ):
            raise ValueError("账号 id 必须是安全的文件名，可直接使用 Apple Account 邮箱")
        return value

    @field_validator("apple_id")
    @classmethod
    def validate_apple_id(cls, value: str) -> str:
        value = value.strip()
        if (
            value.count("@") != 1
            or value.startswith("@")
            or value.endswith("@")
            or any(character.isspace() or ord(character) < 32 for character in value)
            or len(value.encode("utf-8")) > ACCOUNT_ID_MAX_BYTES
        ):
            raise ValueError("apple_id 格式无效")
        return value

    @field_validator("libraries")
    @classmethod
    def validate_libraries(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("libraries 至少需要一个图库 ID 或名称")
        return list(dict.fromkeys(cleaned))


class NotificationChannelConfig(StrictModel):
    type: Literal["bark", "serverchan", "telegram", "wecom", "webhook"]
    enabled: bool = True
    server: HttpUrl | None = None
    url: HttpUrl | None = None
    device_key_file: Path | None = None
    send_key_file: Path | None = None
    token_file: Path | None = None
    chat_id: str | None = None
    corp_id: str | None = None
    corp_secret_file: Path | None = None
    agent_id: Annotated[int, Field(gt=0)] | None = None
    to_user: str | None = None
    content_source_url: HttpUrl | None = None
    name: str | None = None
    media_id_download: str | None = None
    media_id_startup: str | None = None
    media_id_warning: str | None = None
    media_id_expiration: str | None = None
    secret_file: Path | None = None
    timeout: Annotated[int, Field(ge=1, le=60)] = 10

    @model_validator(mode="after")
    def validate_required_fields(self) -> NotificationChannelConfig:
        if not self.enabled:
            return self
        if self.type == "bark" and not self.device_key_file:
            raise ValueError("Bark 通知必须配置 device_key_file")
        if self.type == "serverchan" and not self.send_key_file:
            raise ValueError("Server酱通知必须配置 send_key_file")
        if self.type == "telegram" and (not self.token_file or not self.chat_id):
            raise ValueError("Telegram 通知必须配置 token_file 和 chat_id")
        if self.type == "wecom" and (
            not self.corp_id or not self.corp_secret_file or not self.agent_id or not self.to_user
        ):
            raise ValueError("企业微信通知必须配置 corp_id、corp_secret_file、agent_id 和 to_user")
        if self.type == "webhook" and not self.url:
            raise ValueError("Webhook 通知必须配置 url")
        return self


class NotificationsConfig(StrictModel):
    title: str = "iCloudHarbor"
    silent: bool = False
    startup: bool = False
    success: bool = True
    failure: bool = True
    auth_required: bool = True
    notification_days: Annotated[int, Field(ge=1, le=30)] = 7
    channels: list[NotificationChannelConfig] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("通知标题不能为空")
        return value


class SecurityConfig(StrictModel):
    redact_apple_id: bool = True
    session_encryption: bool = False
    allow_remote_delete: Literal[False] = False


class AppConfig(StrictModel):
    version: Literal[1] = 1
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    accounts: list[AccountConfig]
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    @model_validator(mode="after")
    def validate_unique_accounts(self) -> AppConfig:
        if self.security.session_encryption:
            raise ValueError("当前版本尚未实现 Session 加密，请保持 session_encryption=false")
        enabled = [account for account in self.accounts if account.enabled]
        if len(enabled) != 1:
            raise ValueError("当前版本必须且只能启用一个账号")
        ids = [account.id for account in self.accounts]
        if len(ids) != len(set(ids)):
            raise ValueError("账号 id 必须唯一")
        destinations = [
            str(account.destination.path.resolve()) for account in self.accounts if account.enabled
        ]
        if len(destinations) != len(set(destinations)):
            raise ValueError("已启用账号的 destination.path 不能重复")
        return self

    def account(self, account_id: str | None = None) -> AccountConfig:
        enabled = [account for account in self.accounts if account.enabled]
        if account_id is None:
            if len(enabled) != 1:
                raise ValueError("请用 --account 指定一个已启用账号")
            return enabled[0]
        for account in self.accounts:
            if account.id == account_id:
                if not account.enabled:
                    raise ValueError(f"账号 {account_id!r} 已禁用")
                return account
        raise ValueError(f"未找到账号 {account_id!r}")
