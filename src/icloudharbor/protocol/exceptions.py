"""Stable exceptions exposed to the rest of iCloudHarbor."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    AUTH_ERROR = "AUTH_ERROR"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TERMS_REQUIRED = "TERMS_REQUIRED"
    WEB_ACCESS_DISABLED = "WEB_ACCESS_DISABLED"
    ADP_APPROVAL_REQUIRED = "ADP_APPROVAL_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    DOWNLOAD_URL_EXPIRED = "DOWNLOAD_URL_EXPIRED"
    REMOTE_NOT_FOUND = "REMOTE_NOT_FOUND"
    STORAGE_FULL = "STORAGE_FULL"
    MOUNT_MISSING = "MOUNT_MISSING"
    FILE_PERMISSION_ERROR = "FILE_PERMISSION_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    DATA_INTEGRITY_ERROR = "DATA_INTEGRITY_ERROR"
    CURSOR_INVALID = "CURSOR_INVALID"
    ALREADY_RUNNING = "SKIPPED_ALREADY_RUNNING"
    UNKNOWN_PROTOCOL_ERROR = "UNKNOWN_PROTOCOL_ERROR"


class HarborError(RuntimeError):
    def __init__(self, message: str, code: ErrorCode) -> None:
        super().__init__(message)
        self.code = code


class ProtocolError(HarborError):
    pass


class AuthenticationRequired(ProtocolError):
    def __init__(self, message: str = "Apple 会话无效，需要重新认证") -> None:
        super().__init__(message, ErrorCode.AUTH_REQUIRED)


class CursorInvalid(ProtocolError):
    def __init__(self, message: str = "同步游标无效，需要全量扫描") -> None:
        super().__init__(message, ErrorCode.CURSOR_INVALID)


class RateLimited(ProtocolError):
    def __init__(self, message: str = "Apple 服务正在限流") -> None:
        super().__init__(message, ErrorCode.RATE_LIMITED)


class ServiceUnavailable(ProtocolError):
    def __init__(self, message: str = "Apple 服务暂时不可用") -> None:
        super().__init__(message, ErrorCode.SERVICE_UNAVAILABLE)
