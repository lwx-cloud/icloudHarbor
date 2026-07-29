from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[^@\s]+)\b")
_QUERY_SECRET_RE = re.compile(r"(?i)([?&](?:token|signature|sig|auth|x-apple-[^=]+)=)[^&\s]+")
_HEADER_RE = re.compile(
    r"(?i)\b(authorization|cookie|x-apple-session-token|password|verification_code)"
    r"\s*[:=]\s*([^\s,;]+)"
)


def redact(value: object, *, redact_email: bool = True) -> str:
    text = str(value)
    text = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = _HEADER_RE.sub(r"\1=[REDACTED]", text)
    if redact_email:
        text = _EMAIL_RE.sub(r"\1***\2", text)
    return text
