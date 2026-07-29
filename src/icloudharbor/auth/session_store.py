"""Non-secret local authentication status metadata."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from icloudharbor.protocol.models import AuthStatus


class SessionStore:
    def __init__(self, root: Path, account_id: str) -> None:
        self.directory = root / account_id
        self.path = self.directory / "harbor-auth-state.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._secure()

    def write_status(self, status: AuthStatus) -> None:
        payload = {"status": status.value, "updated_at": datetime.now(UTC).isoformat()}
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._secure()

    def read_status(self) -> AuthStatus:
        if not self.path.is_file():
            return AuthStatus.UNCONFIGURED
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return AuthStatus(payload["status"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return AuthStatus.REAUTHENTICATION_REQUIRED

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _secure(self) -> None:
        try:
            self.directory.chmod(0o700)
            for path in self.directory.iterdir():
                if path.is_file():
                    path.chmod(0o600)
        except OSError:
            pass
