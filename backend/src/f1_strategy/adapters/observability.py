"""Logs as one JSON object per line, each carrying the id of the request it belongs to
(ADR 0016)."""

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Literal

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# nginx sends 32 hex characters; anything else from a client is replaced, so a header cannot
# write text into the logs.
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")
FIELDS = "fields"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)


def request_id_from(header: str | None) -> str:
    """The header's id when it is one, a new id otherwise."""
    if header is not None and REQUEST_ID_PATTERN.fullmatch(header):
        return header
    return uuid.uuid4().hex


def log_fields(**fields: object) -> dict[str, dict[str, object]]:
    """The `extra` of a log call: its fields become keys of the JSON line."""
    return {FIELDS: fields}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "request_id": current_request_id.get(),
        }
        fields = getattr(record, FIELDS, None)
        if isinstance(fields, dict):
            line.update(fields)
        if record.exc_info is not None:
            line["traceback"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(level: LogLevel) -> None:
    """Every logger, uvicorn's included, writes through one JSON handler on stdout. uvicorn's
    access log is off: the request middleware writes one line per request instead."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
