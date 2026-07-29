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

from icloudharbor.config.validation import parse_duration, parse_size


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
    mounted_marker: str = ".icloudharbor-mounted"
    minimum_free_space: int = 10_000_000_000

    @field_validator("minimum_free_space", mode="before")
    @classmethod
    def validate_minimum_space(cls, value: object) -> int:
        if not isinstance(value, str | int) or isinstance(value, bool):
            raise ValueError("minimum_free_space 必须是字节数或 10GB 形式")
        return parse_size(value)

    @field_validator("mounted_marker")
    @classmethod
    def validate_marker(cls, value: str) -> str:
        if not value or Path(value).name != value or value in {".", ".."}:
            raise ValueError("mounted_marker 必须是单个安全文件名")
        return value


class RawConfig(StrictModel):
    mode: Literal["raw_only", "jpeg_only", "both", "prefer_raw", "prefer_jpeg"] = "both"


class MediaConfig(StrictModel):
    photos: bool = True
    videos: bool = True
    live_photos: bool = True
    photo_version: Literal["original", "adjusted", "both"] = "original"
    raw: RawConfig = Field(default_factory=RawConfig)


class FilterConfig(StrictModel):
    albums: list[str] = Field(default_factory=list)
    exclude_albums: list[str] = Field(default_factory=list)
    created_after: datetime | None = None
    created_before: datetime | None = None
    favorites_only: bool = False
    include_hidden: bool = False

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
    keep_unicode: bool = True

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
        if self.interval:
            parse_duration(self.interval)
        return self


class SyncConfig(StrictModel):
    mode: Literal["backup"] = "backup"
    strategy: Literal["cursor", "full"] = "cursor"
    full_scan_interval: timedelta = timedelta(days=30)
    schedule: str | ScheduleConfig | None = None
    run_on_start: bool = False

    @field_validator("full_scan_interval", mode="before")
    @classmethod
    def validate_full_scan_interval(cls, value: object) -> timedelta:
        if not isinstance(value, str | int | timedelta) or isinstance(value, bool):
            raise ValueError("full_scan_interval 必须是 30d 形式的时长")
        return parse_duration(value)

    @field_validator("schedule")
    @classmethod
    def validate_cron_string(
        cls, value: str | ScheduleConfig | None
    ) -> str | ScheduleConfig | None:
        if isinstance(value, str) and len(value.split()) != 5:
            raise ValueError("Cron 表达式必须包含 5 个字段")
        return value


class DownloadConfig(StrictModel):
    concurrency: Annotated[int, Field(ge=1, le=8)] = 2
    chunk_size: int = 1_000_000
    timeout: Annotated[int, Field(ge=1, le=3600)] = 300
    max_retries: Annotated[int, Field(ge=0, le=20)] = 5
    verify_hash: bool = True
    keep_partial: bool = True

    @field_validator("chunk_size", mode="before")
    @classmethod
    def validate_chunk_size(cls, value: object) -> int:
        if not isinstance(value, str | int) or isinstance(value, bool):
            raise ValueError("chunk_size 必须是字节数或 1MB 形式")
        parsed = parse_size(value)
        if parsed < 64 * 1024 or parsed > 64 * 1024 * 1024:
            raise ValueError("chunk_size 必须在 64KiB 到 64MiB 之间")
        return parsed


class AccountConfig(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
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

    @field_validator("apple_id")
    @classmethod
    def validate_apple_id(cls, value: str) -> str:
        value = value.strip()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("apple_id 格式无效")
        return value

    @model_validator(mode="after")
    def validate_v01_scope(self) -> AccountConfig:
        if self.libraries != ["root"]:
            raise ValueError("v0.1 仅支持个人图库 libraries: [root]")
        if self.filters.albums or self.filters.exclude_albums:
            raise ValueError("v0.1 尚未实现按相册筛选，请保持相册筛选为空")
        return self


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
    startup: bool = False
    success: bool = True
    no_changes: bool = False
    failure: bool = True
    auth_required: bool = True
    channels: list[NotificationChannelConfig] = Field(default_factory=list)


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
            raise ValueError("v0.1 尚未实现 Session 加密，请保持 session_encryption=false")
        enabled = [account for account in self.accounts if account.enabled]
        if len(enabled) != 1:
            raise ValueError("v0.1 必须且只能启用一个账号")
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
