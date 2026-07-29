from __future__ import annotations

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

from icloudharbor.config.models import RuntimeConfig
from icloudharbor.security.redaction import redact


def _redact_event(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            event_dict[key] = redact(value)
    return event_dict


def configure_logging(config: RuntimeConfig) -> None:
    logging.basicConfig(
        level=getattr(logging, config.log_level),
        stream=sys.stdout,
        format="%(message)s",
        force=True,
    )
    renderer: object
    if config.log_format == "json":
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_event,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, config.log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
