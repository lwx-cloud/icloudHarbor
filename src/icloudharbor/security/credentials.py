"""Local encrypted credential storage for unattended session renewal."""

from __future__ import annotations

import base64
import json
import os
import secrets
from contextlib import suppress
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialStore:
    """Store one Apple Account password under the protected config volume.

    The encryption key and ciphertext intentionally live in the same ACL-protected
    volume so the daemon can renew sessions without user interaction. Encryption
    prevents accidental plaintext disclosure, but host root can still recover it.
    """

    def __init__(self, root: Path, account_id: str) -> None:
        self.root = root
        self.account_id = account_id
        self.key_path = root / "vault.key"
        self.credential_path = root / f"{account_id}.json"
        self._associated_data = f"icloudharbor:{account_id}:v1".encode()

    def read(self) -> str | None:
        if not self.credential_path.is_file():
            return None
        key = self._read_key(create=False)
        try:
            payload: Any = json.loads(self.credential_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != 1:
                raise ValueError("凭据文件版本无效")
            nonce = base64.b64decode(payload["nonce"], validate=True)
            ciphertext = base64.b64decode(payload["ciphertext"], validate=True)
            password = AESGCM(key).decrypt(nonce, ciphertext, self._associated_data).decode("utf-8")
        except (
            OSError,
            UnicodeError,
            ValueError,
            KeyError,
            TypeError,
            InvalidTag,
        ) as exc:
            raise ValueError(f"账号 {self.account_id!r} 的本地凭据无法读取或校验") from exc
        if not password:
            raise ValueError("本地凭据为空")
        self._secure_permissions()
        return password

    def write(self, password: str) -> None:
        if not password:
            raise ValueError("不能保存空密码")
        self._ensure_root()
        key = self._read_key(create=True)
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(key).encrypt(
            nonce,
            password.encode("utf-8"),
            self._associated_data,
        )
        payload = {
            "version": 1,
            "algorithm": "AES-256-GCM",
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        self._atomic_write(
            self.credential_path,
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(),
        )
        self._secure_permissions()

    def clear(self) -> bool:
        existed = self.credential_path.is_file()
        self.credential_path.unlink(missing_ok=True)
        self._secure_permissions()
        return existed

    def exists(self) -> bool:
        return self.credential_path.is_file()

    def _read_key(self, *, create: bool) -> bytes:
        if not self.key_path.is_file():
            if not create:
                raise ValueError("本地凭据密钥不存在")
            self._ensure_root()
            try:
                descriptor = os.open(
                    self.key_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(secrets.token_bytes(32))
                    handle.flush()
                    os.fsync(handle.fileno())
        key = self.key_path.read_bytes()
        if len(key) != 32:
            raise ValueError("本地凭据密钥格式无效")
        self._secure_permissions()
        return key

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            self.root.chmod(0o700)

    def _secure_permissions(self) -> None:
        try:
            if self.root.exists():
                self.root.chmod(0o700)
            for path in (self.key_path, self.credential_path):
                if path.is_file():
                    path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
