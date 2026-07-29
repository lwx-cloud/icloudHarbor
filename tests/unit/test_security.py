from __future__ import annotations

from pathlib import Path

import pytest

from icloudharbor.security.credentials import CredentialStore
from icloudharbor.security.prompt import _read_masked
from icloudharbor.security.redaction import redact


def test_redacts_account_headers_and_signed_query() -> None:
    value = "user@example.com Authorization:BearerSecret https://example.test/a?token=abc&x=1"
    result = redact(value)
    assert "BearerSecret" not in result
    assert "token=abc" not in result
    assert "user@example.com" not in result
    assert "u***@example.com" in result


def test_credential_store_encrypts_round_trips_and_clears(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials", "personal")

    store.write("apple-password")

    assert store.exists() is True
    assert store.read() == "apple-password"
    assert b"apple-password" not in store.credential_path.read_bytes()
    assert store.key_path.stat().st_size == 32
    assert store.clear() is True
    assert store.read() is None


def test_credential_store_rejects_tampered_ciphertext(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path / "credentials", "personal")
    store.write("apple-password")
    store.credential_path.write_text('{"version":1,"nonce":"AA==","ciphertext":"AA=="}')

    with pytest.raises(ValueError, match="无法读取或校验"):
        store.read()


def test_masked_reader_renders_stars_and_supports_backspace() -> None:
    characters = iter(["s", "e", "\b", "c", "\n"])
    output: list[str] = []

    result = _read_masked(lambda: next(characters), output.append)

    assert result == "sc"
    assert "".join(output) == "**\b \b*\n"
