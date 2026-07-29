from __future__ import annotations

from icloudharbor.auth.session_store import SessionStore
from icloudharbor.config.models import AccountConfig
from icloudharbor.database.repository import StateRepository
from icloudharbor.protocol.base import ICloudProtocol
from icloudharbor.protocol.exceptions import ErrorCode, ProtocolError
from icloudharbor.protocol.models import AuthResult, AuthStatus, Credentials


class AuthManager:
    def __init__(
        self,
        account: AccountConfig,
        protocol: ICloudProtocol,
        repository: StateRepository,
        session_store: SessionStore,
    ) -> None:
        self.account = account
        self.protocol = protocol
        self.repository = repository
        self.session_store = session_store

    def login(self, password: str | None) -> AuthResult:
        self._set_status(AuthStatus.AUTHENTICATING)
        try:
            result = self.protocol.authenticate(
                Credentials(
                    apple_id=self.account.apple_id,
                    password=password,
                    region=self.account.region,
                )
            )
        except Exception as exc:
            status = AuthStatus.AUTH_FAILED
            if isinstance(exc, ProtocolError):
                status = {
                    ErrorCode.TERMS_REQUIRED: AuthStatus.TERMS_REQUIRED,
                    ErrorCode.WEB_ACCESS_DISABLED: AuthStatus.WEB_ACCESS_DISABLED,
                    ErrorCode.ADP_APPROVAL_REQUIRED: AuthStatus.ADP_APPROVAL_REQUIRED,
                    ErrorCode.AUTH_REQUIRED: AuthStatus.AUTH_REQUIRED,
                }.get(exc.code, status)
            self._set_status(status)
            raise
        self._set_status(result.status)
        return result

    def verify(self, challenge_id: str, code: str) -> AuthResult:
        result = self.protocol.submit_2fa(challenge_id, code)
        self._set_status(result.status)
        return result

    def status(self) -> AuthStatus:
        runtime_status = self.protocol.auth_status()
        if runtime_status == AuthStatus.AUTHENTICATED:
            return runtime_status
        return self.repository.get_auth_status(self.account.id)

    def logout(self) -> None:
        self.protocol.logout()
        self.session_store.clear()
        self._set_status(AuthStatus.CREDENTIALS_REQUIRED)

    def _set_status(self, status: AuthStatus) -> None:
        self.repository.set_auth_status(self.account.id, status)
        self.session_store.write_status(status)
