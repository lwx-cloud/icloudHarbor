from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tests.conftest import FakeProtocol
from typer.testing import CliRunner

from icloudharbor.application import HarborApplication
from icloudharbor.cli import app
from icloudharbor.config.models import AppConfig
from icloudharbor.protocol.models import AuthStatus


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
    assert "验证码: 123456" in result.stdout
    assert "AUTHENTICATED" in result.stdout


def test_cli_setup_saves_password_and_validates_photo_access(
    app_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProtocol()
    application = HarborApplication(app_config, protocol_factory=lambda _: fake)
    monkeypatch.setattr("icloudharbor.cli._load_application", lambda _: application)
    monkeypatch.setattr("icloudharbor.cli.masked_password_prompt", lambda _: "not-stored")

    result = CliRunner().invoke(app, ["setup", "--account", "personal"])

    assert result.exit_code == 0
    assert fake.calls == ["logout", "authenticate", "list_libraries", "list_assets"]
    assert application.credential_store(app_config.accounts[0]).read() == "not-stored"
    assert "5/5 设置完成" in result.stdout
    assert "个人图库: ok" in result.stdout


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
