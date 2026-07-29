from __future__ import annotations

import logging

import pytest

from icloudharbor.config.models import RuntimeConfig
from icloudharbor.observability.logging import configure_logging


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
