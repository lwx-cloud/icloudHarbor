from __future__ import annotations

import logging
from pathlib import Path

import pytest

from icloudharbor.config.models import AccountConfig, AppConfig, RuntimeConfig, ScheduleConfig
from icloudharbor.observability.logging import configure_logging
from icloudharbor.observability.startup import startup_summary


def test_standard_library_logs_redact_secrets_and_suppress_http_info(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(RuntimeConfig())

    logging.getLogger("httpx").info(
        "HTTP Request: GET https://example.test/?corpsecret=must-not-appear"
    )
    logging.getLogger("third-party").warning(
        "GET https://example.test/?access_token=must-not-appear"
    )

    output = capsys.readouterr().out
    assert "HTTP Request" not in output
    assert "must-not-appear" not in output
    assert "access_token=[REDACTED]" in output


def test_startup_summary_is_readable_and_redacts_account(
    app_config: AppConfig,
    account_config: AccountConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_config.destination.path = Path("/photos/personal")
    account_config.sync.schedule = ScheduleConfig(interval="24h")
    monkeypatch.setenv("IH_PHOTOS_PATH", "/volume2/ceshi/icloudharbor")

    lines = startup_summary(app_config, account_config, Path("/config/config.yaml"))
    output = "\n".join(lines)

    assert "user@example.com" not in output
    assert "u***@example.com" in output
    assert "/volume2/ceshi/icloudharbor/personal" in output
    assert "Live Photo 尺寸=original" in output
    assert "同步计划：每 24h" in output
    assert "Cron" not in output
