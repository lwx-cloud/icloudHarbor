from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tests.conftest import FakeProtocol
from typer.testing import CliRunner

from icloudharbor.application import HarborApplication
from icloudharbor.cli import (
    _dispatch_pending_sync_requests,
    _log_auth_guidance,
    _run_daemon_sync,
    _startup_notification,
    app,
)
from icloudharbor.config.models import AccountConfig, AppConfig, ScheduleConfig
from icloudharbor.photos.engine import SyncExecution
from icloudharbor.photos.planner import SyncPlan
from icloudharbor.protocol.models import AuthStatus
from icloudharbor.scheduler.service import SchedulerService


def test_two_factor_state_is_persisted(app_config: AppConfig) -> None:
    fake = FakeProtocol(status=AuthStatus.TWO_FACTOR_REQUIRED)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    account = app_config.accounts[0]
    manager = application.auth_manager(account)

    challenge = manager.login("not-stored")
    result = manager.verify(challenge.challenge_id or "", "123456")

    assert result.status == AuthStatus.AUTHENTICATED
    assert application.repository.get_auth_status(account.id) == AuthStatus.AUTHENTICATED


def test_cli_validates_config(tmp_path: Path, app_config: AppConfig) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(app_config.model_dump(mode="json"), allow_unicode=True),
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(app, ["--config", str(path), "config", "validate"])

    assert result.exit_code == 0
    assert "配置有效" in result.stdout


@pytest.mark.parametrize(
    ("redact_apple_id", "expected"),
    [(True, "u***@example.com"), (False, "user@example.com")],
)
def test_accounts_list_honors_apple_id_redaction(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    redact_apple_id: bool,
    expected: str,
) -> None:
    app_config.security.redact_apple_id = redact_apple_id
    application = HarborApplication(app_config, protocol_factory=lambda _: FakeProtocol())
    monkeypatch.setattr("icloudharbor.cli._load_application", lambda _: application)

    result = CliRunner().invoke(app, ["accounts", "list"])

    assert result.exit_code == 0
    assert expected in result.stdout


def test_cli_session_renew_uses_saved_password_without_prompt(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProtocol(require_two_factor_on_authenticate=True)
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    application.credential_store(app_config.accounts[0]).write("not-stored")
    monkeypatch.setattr("icloudharbor.cli._load_application", lambda _: application)
    monkeypatch.setattr(
        "icloudharbor.cli.masked_password_prompt",
        lambda _: pytest.fail("session renew 不应再次询问密码"),
    )

    result = CliRunner().invoke(
        app,
        ["session", "renew", "--account", "personal"],
        input="123456\n",
    )

    assert result.exit_code == 0
    assert fake.calls == ["logout", "authenticate", "submit_2fa"]
    assert "正在使用本地凭据续期" in result.stdout
    assert "Apple 双重认证验证码: 123456" in result.stdout
    assert "认证成功：Apple 会话已建立并受信任" in result.stdout
    assert "已通知容器后台同步" in result.stdout
    requests = application.repository.pending_sync_requests("personal")
    assert len(requests) == 1
    assert requests[0].generation == 1


def test_cli_setup_saves_password_then_queues_background_sync_and_exits(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProtocol()
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    monkeypatch.setattr("icloudharbor.cli._load_application", lambda _: application)
    monkeypatch.setattr("icloudharbor.cli.masked_password_prompt", lambda _: "not-stored")
    monkeypatch.setattr(
        application,
        "run_sync",
        lambda *_args, **_kwargs: pytest.fail("setup 不应在交互终端执行同步"),
    )

    result = CliRunner().invoke(app, ["setup", "--account", "personal"])

    assert result.exit_code == 0
    assert fake.calls == ["logout", "authenticate", "list_libraries", "list_assets"]
    assert application.credential_store(app_config.accounts[0]).read() == "not-stored"
    requests = application.repository.pending_sync_requests("personal")
    assert len(requests) == 1
    assert requests[0].generation == 1
    assert "5/5 设置完成，已通知容器后台开始首次同步" in result.stdout
    assert "个人图库: ok" in result.stdout
    assert "当前认证命令现在退出" in result.stdout
    assert "docker logs -f icloudharbor" in result.stdout


def test_daemon_sync_acknowledges_request_and_refreshes_protocol(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = HarborApplication(app_config, protocol_factory=lambda _: FakeProtocol())
    request = application.repository.request_sync("personal")
    calls: list[tuple[str, bool]] = []

    def run_sync(
        account: AccountConfig,
        *,
        refresh_protocol: bool = False,
    ) -> SyncExecution:
        calls.append((account.id, refresh_protocol))
        return SyncExecution("run-id", "COMPLETED", 0, 0, 0, 0, SyncPlan())

    monkeypatch.setattr(
        application,
        "run_sync",
        run_sync,
    )

    result = _run_daemon_sync(application, "personal")

    assert result.status == "COMPLETED"
    assert calls == [("personal", True)]
    assert application.repository.ack_sync_request("personal", request.generation) is False
    assert application.repository.pending_sync_requests("personal") == []


def test_startup_notification_describes_immediate_sync(app_config: AppConfig) -> None:
    application = HarborApplication(app_config, protocol_factory=lambda _: FakeProtocol())
    account = app_config.accounts[0]
    scheduler = SchedulerService(app_config, lambda _: None)

    event = _startup_notification(application, account, scheduler)

    assert event.title == "iCloudHarbor 容器已启动"
    assert event.message == "账号：测试图库\n正在检查 iCloud，有新内容时会自动下载。"
    assert "等待下一次" not in event.message


def test_startup_notification_shows_next_run_when_startup_sync_is_disabled(
    app_config: AppConfig,
) -> None:
    application = HarborApplication(app_config, protocol_factory=lambda _: FakeProtocol())
    account = app_config.accounts[0]
    account.sync.run_on_start = False
    account.sync.schedule = ScheduleConfig(interval="24h")
    scheduler = SchedulerService(app_config, lambda _: None)
    scheduler.start()
    try:
        event = _startup_notification(application, account, scheduler)
    finally:
        scheduler.shutdown()

    assert event.title == "iCloudHarbor 容器已启动"
    assert event.message.startswith("账号：测试图库\n下一次同步：")


def test_daemon_sync_retains_request_when_account_is_already_running(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = HarborApplication(app_config, protocol_factory=lambda _: FakeProtocol())
    request = application.repository.request_sync("personal")
    refresh_flags: list[bool] = []

    def run_sync(
        _account: object,
        *,
        refresh_protocol: bool = False,
    ) -> SyncExecution:
        refresh_flags.append(refresh_protocol)
        return SyncExecution(
            "run-id",
            "SKIPPED_ALREADY_RUNNING",
            0,
            0,
            0,
            0,
            SyncPlan(),
        )

    monkeypatch.setattr(application, "run_sync", run_sync)

    result = _run_daemon_sync(application, "personal")

    assert result.status == "SKIPPED_ALREADY_RUNNING"
    assert refresh_flags == [True]
    assert application.repository.pending_sync_requests("personal") == [request]


def test_daemon_scheduled_sync_without_request_reuses_protocol(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = HarborApplication(app_config, protocol_factory=lambda _: FakeProtocol())
    refresh_flags: list[bool] = []

    def run_sync(
        _account: object,
        *,
        refresh_protocol: bool = False,
    ) -> SyncExecution:
        refresh_flags.append(refresh_protocol)
        return SyncExecution("run-id", "COMPLETED", 0, 0, 0, 0, SyncPlan())

    monkeypatch.setattr(application, "run_sync", run_sync)

    _run_daemon_sync(application, "personal")

    assert refresh_flags == [False]


def test_daemon_discards_removed_account_request_before_dispatching_valid_request(
    app_config: AppConfig,
) -> None:
    application = HarborApplication(app_config, protocol_factory=lambda _: FakeProtocol())
    removed = app_config.accounts[0].model_copy(update={"id": "removed", "name": "Removed account"})
    application.repository.sync_account(removed)
    removed_request = application.repository.request_sync(removed.id)
    application.repository.request_sync("personal")
    scheduler = SchedulerService(app_config, lambda _: None)

    dispatched = _dispatch_pending_sync_requests(application, scheduler)

    assert dispatched == 1
    assert (
        application.repository.ack_sync_request(
            removed.id,
            removed_request.generation,
        )
        is False
    )
    assert application.repository.pending_sync_requests(removed.id) == []
    assert [job.id for job in scheduler.scheduler.get_jobs()] == ["sync-now:personal"]


def test_requested_sync_replaces_cached_protocol_without_logging_out(
    app_config: AppConfig,
) -> None:
    protocols: list[FakeProtocol] = []

    def factory(_account: AccountConfig) -> FakeProtocol:
        protocol = FakeProtocol()
        protocols.append(protocol)
        return protocol

    application = HarborApplication(app_config, protocol_factory=factory)
    account = app_config.accounts[0]
    cached = application.protocol(account)

    result = application.run_sync(account, refresh_protocol=True)

    assert result.status == "COMPLETED"
    assert len(protocols) == 2
    assert "logout" not in cached.calls
    assert "list_libraries" in protocols[1].calls


def test_cli_setup_does_not_clear_session_while_account_operation_is_busy(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProtocol()
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    monkeypatch.setattr("icloudharbor.cli._load_application", lambda _: application)
    monkeypatch.setattr(
        "icloudharbor.cli.masked_password_prompt",
        lambda _: pytest.fail("账号忙时不应询问密码"),
    )

    with application.account_operation(app_config.accounts[0]):
        result = CliRunner().invoke(app, ["setup", "--account", "personal"])

    assert result.exit_code == 1
    assert "当前账号正在同步或认证" in result.stderr
    assert fake.calls == []


def test_daemon_auth_guidance_uses_setup_then_renew(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = HarborApplication(app_config, protocol_factory=lambda _: FakeProtocol())
    account = app_config.accounts[0]
    warnings: list[str] = []

    class RecordingLogger:
        def warning(self, message: str) -> None:
            warnings.append(message)

    monkeypatch.setattr("icloudharbor.cli.LOGGER", RecordingLogger())

    _log_auth_guidance(application, account)
    assert any("icloudharbor setup" in message for message in warnings)

    warnings.clear()
    application.credential_store(account).write("not-stored")
    _log_auth_guidance(application, account)
    assert any("icloudharbor session renew" in message for message in warnings)


def test_sqlite_online_backup_is_consistent(
    tmp_path: Path,
    app_config: AppConfig,
) -> None:
    application = HarborApplication(
        app_config,
        protocol_factory=lambda _: FakeProtocol(),
    )
    target = tmp_path / "backup.db"

    application.repository.backup(target)

    assert target.is_file()
    assert target.stat().st_size > 0
