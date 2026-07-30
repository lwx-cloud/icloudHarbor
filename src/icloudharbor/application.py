"""Composition root for the CLI and foreground scheduler."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog

from icloudharbor.auth.manager import AuthManager
from icloudharbor.auth.session_store import SessionStore
from icloudharbor.config.loader import config_snapshot, load_config
from icloudharbor.config.models import AccountConfig, AppConfig
from icloudharbor.database.repository import StateRepository
from icloudharbor.database.session import Database
from icloudharbor.notify import NotificationEvent, NotifierHub
from icloudharbor.notify.base import NotificationType
from icloudharbor.observability.health import HealthService
from icloudharbor.photos.engine import PhotosEngine, SyncExecution
from icloudharbor.protocol.base import ICloudProtocol
from icloudharbor.protocol.models import AuthResult, AuthStatus
from icloudharbor.protocol.pyicloud_adapter import PyicloudProtocolAdapter
from icloudharbor.scheduler.locks import LockCoordinator
from icloudharbor.security.credentials import CredentialStore

ProtocolFactory = Callable[[AccountConfig], ICloudProtocol]
LOGGER = structlog.get_logger(__name__)


class HarborApplication:
    def __init__(
        self,
        config: AppConfig,
        *,
        protocol_factory: ProtocolFactory | None = None,
    ) -> None:
        self.config = config
        self.database = Database(config.runtime.database)
        self.database.initialize()
        self.repository = StateRepository(self.database)
        for account in config.accounts:
            self.repository.sync_account(account)
        self.repository.save_config_revision(config_snapshot(config))
        self.config_root = (
            config.runtime.database.parent.parent
            if config.runtime.database.parent.name == "database"
            else config.runtime.database.parent
        )
        self.session_root = self.config_root / "sessions"
        self.credential_root = self.config_root / "credentials"
        self.lock_root = self.config_root / "locks"
        config.runtime.temp_path.mkdir(parents=True, exist_ok=True)
        self.locks = LockCoordinator(self.lock_root, self.repository)
        self.health = HealthService(config, self.database)
        self.notifier = NotifierHub(config.notifications)
        self._protocol_factory = protocol_factory or self._default_protocol
        self._protocols: dict[str, ICloudProtocol] = {}

    @classmethod
    def from_path(
        cls,
        path: Path | None = None,
        *,
        protocol_factory: ProtocolFactory | None = None,
    ) -> HarborApplication:
        return cls(load_config(path), protocol_factory=protocol_factory)

    def protocol(self, account: AccountConfig) -> ICloudProtocol:
        if account.id not in self._protocols:
            self._protocols[account.id] = self._protocol_factory(account)
        return self._protocols[account.id]

    def auth_manager(self, account: AccountConfig) -> AuthManager:
        return AuthManager(
            account,
            self.protocol(account),
            self.repository,
            SessionStore(self.session_root, account.id),
        )

    def credential_store(self, account: AccountConfig) -> CredentialStore:
        return CredentialStore(self.credential_root, account.id)

    def login(self, account: AccountConfig, password: str | None) -> AuthResult:
        return self.auth_manager(account).login(password)

    def ensure_session(self, account: AccountConfig) -> AuthStatus:
        protocol = self.protocol(account)
        if protocol.auth_status() == AuthStatus.AUTHENTICATED:
            return AuthStatus.AUTHENTICATED
        result = self.login(account, self.credential_store(account).read())
        return result.status

    def run_sync(
        self,
        account: AccountConfig,
        *,
        dry_run: bool = False,
        force_full_scan: bool = False,
        authenticate: bool = True,
    ) -> SyncExecution:
        started = time.monotonic()
        LOGGER.info(f"同步开始：{account.name}")
        if authenticate:
            with suppress(Exception):
                self.ensure_session(account)
                # The engine records a stable AUTH_REQUIRED result and keeps
                # long-running containers alive.
        try:
            self._notify_auth_expiration(account)
        except Exception as exc:
            LOGGER.warning(
                "auth_expiration_check_failed",
                account_id=account.id,
                error=f"{type(exc).__name__}: {exc}",
            )
        result = PhotosEngine(
            self.protocol(account),
            self.repository,
            self.database,
            self.locks,
        ).run(account, dry_run=dry_run, force_full_scan=force_full_scan)
        elapsed = int(time.monotonic() - started)
        LOGGER.info(
            f"同步结束：状态={result.status}；下载={result.downloaded_count}；"
            f"跳过={result.skipped_count}；失败={result.failed_count}；"
            f"用时={elapsed // 3600:02d}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
        )
        expires_at = self.protocol(account).session_expires_at()
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            local_expiry = expires_at.astimezone(ZoneInfo(self.config.runtime.timezone))
            remaining = max(0, math.ceil((expires_at - datetime.now(UTC)).total_seconds() / 86400))
            LOGGER.info(
                f"Apple 认证到期时间：{local_expiry:%Y-%m-%d %H:%M:%S}；剩余约 {remaining} 天"
            )
        self._notify_sync(account, result)
        return result

    def _notify_auth_expiration(self, account: AccountConfig) -> None:
        protocol = self.protocol(account)
        if protocol.auth_status() != AuthStatus.AUTHENTICATED:
            return
        expires_at = protocol.session_expires_at()
        if expires_at is None:
            return
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        remaining = expires_at - datetime.now(UTC)
        notification_window = timedelta(days=self.config.notifications.notification_days)
        if remaining <= timedelta(0) or remaining > notification_window:
            return

        days_remaining = max(1, math.ceil(remaining.total_seconds() / 86400))
        local_day = datetime.now(ZoneInfo(self.config.runtime.timezone)).date().isoformat()
        claim = f"auth-expiring:{account.id}:{local_day}"
        if not self.repository.claim_notification(claim):
            return

        results = self.notifier.send(
            NotificationEvent(
                NotificationType.AUTH_EXPIRING,
                f"{self.config.notifications.title} 认证即将到期",
                (
                    f"账号：{account.name}\n"
                    f"认证将在 {days_remaining} 天内到期，请运行 session renew。"
                ),
                {
                    "account_id": account.id,
                    "days_remaining": days_remaining,
                    "expires_at": expires_at.isoformat(),
                },
            )
        )
        if not any(result.success for result in results):
            self.repository.release_notification_claim(claim)
            return
        LOGGER.warning(
            "auth_expiration_warning_sent",
            account_id=account.id,
            days_remaining=days_remaining,
        )

    def _default_protocol(self, account: AccountConfig) -> ICloudProtocol:
        return PyicloudProtocolAdapter(
            self.session_root / account.id,
            account.id,
            account.download.timeout,
        )

    def _notify_sync(self, account: AccountConfig, result: SyncExecution) -> None:
        if result.status in {"DRY_RUN", "SKIPPED_ALREADY_RUNNING"}:
            return
        if result.status == "COMPLETED":
            event_type = NotificationType.SYNC_COMPLETED
            title = f"{self.config.notifications.title} 同步完成"
        elif result.error_code in {
            "AUTH_REQUIRED",
            "TERMS_REQUIRED",
            "WEB_ACCESS_DISABLED",
            "ADP_APPROVAL_REQUIRED",
        }:
            event_type = NotificationType.AUTH_REQUIRED
            title = f"{self.config.notifications.title} 需要重新认证"
        elif result.status == "PARTIAL":
            event_type = NotificationType.SYNC_PARTIAL
            title = f"{self.config.notifications.title} 同步部分失败"
        else:
            event_type = NotificationType.SYNC_FAILED
            title = f"{self.config.notifications.title} 同步失败"
        self.notifier.send(
            NotificationEvent(
                event_type,
                title,
                (
                    f"账号：{account.name}\n状态：{result.status}\n"
                    f"下载：{result.downloaded_count}\n跳过：{result.skipped_count}\n"
                    f"失败：{result.failed_count}\n数据：{result.bytes_downloaded} 字节"
                ),
                {"run_id": result.run_id, "error_code": result.error_code},
            )
        )
