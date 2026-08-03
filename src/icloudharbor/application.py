"""Composition root for the CLI and foreground scheduler."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
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
from icloudharbor.photos.engine import PhotosEngine, SyncExecution, SyncPreview
from icloudharbor.photos.planner import SyncPlan
from icloudharbor.protocol.base import ICloudProtocol
from icloudharbor.protocol.exceptions import AuthenticationRequired, ErrorCode, HarborError
from icloudharbor.protocol.models import AuthResult, AuthStatus
from icloudharbor.protocol.pyicloud_adapter import PyicloudProtocolAdapter
from icloudharbor.scheduler.locks import LockCoordinator
from icloudharbor.security.credentials import CredentialStore

ProtocolFactory = Callable[[AccountConfig], ICloudProtocol]
LOGGER = structlog.get_logger(__name__)
SYNC_ERROR_MESSAGES = {
    "AUTH_REQUIRED": "Apple 会话已失效，请运行 icloudharbor setup。",
    "TERMS_REQUIRED": "Apple 要求接受新的服务条款，请先登录 iCloud 网页完成处理。",
    "WEB_ACCESS_DISABLED": "Apple Account 未开启网页访问 iCloud 数据。",
    "ADP_APPROVAL_REQUIRED": "Apple 高级数据保护阻止了访问，需要先在受信任设备上批准。",
    "ACCESS_DENIED": "Apple 拒绝访问所选图库或相册，请检查账号权限和配置。",
    "RATE_LIMITED": "Apple 服务正在限流，请稍后重试。",
    "SERVICE_UNAVAILABLE": "Apple 服务暂时不可用，请稍后重试。",
    "NETWORK_TIMEOUT": "连接 Apple 服务超时，请检查网络后重试。",
    "STORAGE_FULL": "照片目录剩余空间不足。",
    "MOUNT_MISSING": "照片目录未正确挂载，或缺少挂载标记文件。",
    "FILE_PERMISSION_ERROR": "容器没有权限写入照片目录。",
    "DATABASE_ERROR": "本地状态数据库异常。",
    "DATA_INTEGRITY_ERROR": "文件下载完成后校验失败。",
}
AUTH_REQUIRED_ERROR_CODES = {
    "AUTH_REQUIRED",
    "TERMS_REQUIRED",
    "WEB_ACCESS_DISABLED",
    "ADP_APPROVAL_REQUIRED",
}
MAX_NOTIFICATION_CLEANUP_FILES = 50
MAX_NOTIFICATION_CLEANUP_DETAILS_CHARS = 2000


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

    def notify_auth_required(
        self,
        account: AccountConfig,
        event: NotificationEvent,
    ) -> bool:
        claim = self.repository.auth_required_notification_key(account.id)
        if not self.repository.claim_notification(claim):
            return False
        try:
            results = self.notifier.send(event)
        except Exception as exc:
            self.repository.release_notification_claim(claim)
            LOGGER.warning(
                "auth_required_notification_failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return False
        if any(result.success for result in results):
            return True
        self.repository.release_notification_claim(claim)
        return False

    def notify_auth_recovered(
        self,
        account: AccountConfig,
        *,
        renewal: bool = False,
    ) -> bool:
        self.repository.release_notification_claim(
            self.repository.auth_required_notification_key(account.id)
        )
        action = "renew" if renewal else "setup"
        title = "认证续期成功" if renewal else "首次认证成功"
        message = (
            "Apple 认证续期已完成，后台同步请求已提交。"
            if renewal
            else "Apple 认证已完成，后台首次同步请求已提交。"
        )
        try:
            results = self.notifier.send(
                NotificationEvent(
                    NotificationType.AUTH_RECOVERED,
                    f"{self.config.notifications.title} {title}",
                    f"账号：{account.name}\n{message}",
                    {"account_id": account.id, "action": action},
                )
            )
        except Exception as exc:
            LOGGER.warning(
                "auth_recovered_notification_failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return False
        return any(result.success for result in results)

    @contextmanager
    def account_operation(self, account: AccountConfig) -> Iterator[None]:
        with self.locks.acquire(f"account-operation:{account.id}"):
            yield

    def discard_protocol(self, account: AccountConfig) -> None:
        self._protocols.pop(account.id, None)

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
        force_full_scan: bool = False,
        authenticate: bool = True,
        refresh_protocol: bool = False,
    ) -> SyncExecution:
        started = time.monotonic()
        LOGGER.info(f"同步开始：{account.name}")
        try:
            with self.account_operation(account):
                if refresh_protocol:
                    self.discard_protocol(account)
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
                ).run(account, force_full_scan=force_full_scan)
        except HarborError as exc:
            if exc.code != ErrorCode.ALREADY_RUNNING:
                raise
            result = self._skipped_sync(exc)
        elapsed = int(time.monotonic() - started)
        LOGGER.info(
            f"同步结束：状态={result.status}；下载={result.downloaded_count}；"
            f"删除本地={result.deleted_count}；跳过={result.skipped_count}；"
            f"失败={result.failed_count}；"
            f"用时={elapsed // 3600:02d}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
        )
        if result.status != "SKIPPED_ALREADY_RUNNING":
            expires_at = self.protocol(account).session_expires_at()
            if expires_at is not None:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                local_expiry = expires_at.astimezone(ZoneInfo(self.config.runtime.timezone))
                remaining = max(
                    0,
                    math.ceil((expires_at - datetime.now(UTC)).total_seconds() / 86400),
                )
                LOGGER.info(
                    f"Apple 认证到期时间：{local_expiry:%Y-%m-%d %H:%M:%S}；剩余约 {remaining} 天"
                )
        if self.protocol(account).auth_status() == AuthStatus.AUTHENTICATED:
            self.repository.release_notification_claim(
                self.repository.auth_required_notification_key(account.id)
            )
        self._notify_sync(account, result)
        return result

    def preview_sync(self, account: AccountConfig) -> SyncPreview:
        with self.account_operation(account):
            if self.ensure_session(account) != AuthStatus.AUTHENTICATED:
                raise AuthenticationRequired()
            return PhotosEngine(
                self.protocol(account),
                self.repository,
                self.database,
                self.locks,
            ).preview(account)

    @staticmethod
    def _skipped_sync(exc: HarborError) -> SyncExecution:
        LOGGER.info("已有账号操作正在运行，本次不重复启动")
        return SyncExecution(
            "",
            "SKIPPED_ALREADY_RUNNING",
            0,
            0,
            0,
            0,
            SyncPlan(),
            exc.code.value,
            str(exc),
        )

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
                    f"认证将在 {days_remaining} 天内到期，"
                    "请运行 icloudharbor setup。"
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
        if result.status == "SKIPPED_ALREADY_RUNNING":
            return
        if result.status == "COMPLETED":
            event_type = NotificationType.SYNC_COMPLETED
            title_suffix = (
                "同步完成" if result.downloaded_count or result.deleted_count else "已是最新"
            )
        elif result.error_code in AUTH_REQUIRED_ERROR_CODES:
            event_type = NotificationType.AUTH_REQUIRED
            title_suffix = "需要处理 Apple 认证"
        elif result.status == "PARTIAL":
            event_type = NotificationType.SYNC_PARTIAL
            title_suffix = "同步部分完成"
        else:
            event_type = NotificationType.SYNC_FAILED
            title_suffix = "同步失败"

        lines = [f"账号：{account.name}"]
        if result.status == "COMPLETED":
            if result.downloaded_count:
                lines.append(f"本次下载：{result.downloaded_count} 个文件")
                lines.append(f"下载数据：{self._format_data_size(result.bytes_downloaded)}")
            else:
                lines.append("本次检查完成，没有发现需要下载的新文件。")
            if result.skipped_count:
                lines.append(f"本地已有：{result.skipped_count} 个文件")
            if result.deleted_count:
                lines.append(f"按 iCloud 最近删除清理：{result.deleted_count} 个本地文件")
                lines.append(f"释放空间：{self._format_data_size(result.bytes_deleted)}")
        elif result.status == "PARTIAL":
            lines.extend(
                [
                    f"成功下载：{result.downloaded_count} 个文件",
                    f"下载失败：{result.failed_count} 个文件",
                ]
            )
            if result.skipped_count:
                lines.append(f"本地已有：{result.skipped_count} 个文件")
            if result.bytes_downloaded:
                lines.append(f"下载数据：{self._format_data_size(result.bytes_downloaded)}")
            if result.deleted_count:
                lines.append(f"已清理本地：{result.deleted_count} 个文件")
            if result.delete_failed_count:
                lines.append(f"本地删除失败：{result.delete_failed_count} 个 Asset")
            lines.append("部分文件未能完成，请查看容器日志后重试。")
        else:
            lines.append(
                SYNC_ERROR_MESSAGES.get(
                    result.error_code or "",
                    "同步未能完成，请查看容器日志确认原因。",
                )
            )

        payload: dict[str, object] = {
            "run_id": result.run_id,
            "error_code": result.error_code,
        }
        if result.deleted_files:
            payload["deleted_files"] = list(result.deleted_files)
        event = NotificationEvent(
            event_type,
            f"{self.config.notifications.title} {title_suffix}",
            "\n".join(lines),
            payload,
            self._cleanup_notification_details(result.deleted_files),
        )
        if event_type == NotificationType.AUTH_REQUIRED:
            self.notify_auth_required(account, event)
            return
        self.notifier.send(event)

    @staticmethod
    def _cleanup_notification_details(filenames: tuple[str, ...]) -> str | None:
        if not filenames:
            return None
        safe_names = tuple(
            " ".join(filename.replace("\t", " ").splitlines()).strip() or "（未命名文件）"
            for filename in filenames
        )
        shown: list[str] = []
        used_chars = 0
        for filename in safe_names:
            line = f"- {filename}"
            if len(shown) >= MAX_NOTIFICATION_CLEANUP_FILES:
                break
            if shown and used_chars + len(line) + 1 > MAX_NOTIFICATION_CLEANUP_DETAILS_CHARS:
                break
            shown.append(line)
            used_chars += len(line) + 1
        omitted = len(safe_names) - len(shown)
        heading = "清理文件明细："
        if omitted:
            heading = f"清理文件明细（显示 {len(shown)}/{len(safe_names)}）："
        details = [heading, *shown]
        if omitted:
            details.append(f"- 其余 {omitted} 个文件请查看容器日志")
        return "\n".join(details)

    @staticmethod
    def _format_data_size(size: int) -> str:
        value = float(size)
        units = ("B", "KB", "MB", "GB", "TB")
        unit = units[0]
        for unit in units:
            if value < 1024 or unit == units[-1]:
                break
            value /= 1024
        if unit == "B":
            return f"{size} B"
        return f"{value:.2f}".rstrip("0").rstrip(".") + f" {unit}"
