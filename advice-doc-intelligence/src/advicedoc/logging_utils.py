"""Logging with PII redaction: emails, phone numbers, TFN-shaped numbers and any client
names registered with the redactor are masked before a line is written."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable
from typing import Any

from advicedoc.identifiers import find_tfn_like

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+61|0)[2-9](?:[ -]?\d){8}(?!\d)")


class Redactor(logging.Filter):
    def __init__(self) -> None:
        super().__init__("redact")
        self._names: set[str] = set()

    def register_names(self, names: Iterable[str]) -> None:
        self._names.update(n for n in names if n and len(n) > 2)

    def redact(self, text: str) -> str:
        out = _EMAIL.sub("[email]", text)
        out = _PHONE.sub("[phone]", out)
        for tfn in find_tfn_like(out):
            out = out.replace(tfn, "[tfn]")
        for name in sorted(self._names, key=len, reverse=True):
            out = re.sub(re.escape(name), "[name]", out, flags=re.IGNORECASE)
        return out

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(str(record.getMessage()))
        record.args = ()
        return True


REDACTOR = Redactor()


def configure_logging(level: str = "INFO") -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":  # pragma: no cover
        sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(REDACTOR)
    root = logging.getLogger("advicedoc")
    root.handlers = [handler]
    root.setLevel(level.upper())
    root.propagate = False


def log_event(log: logging.Logger, event: str, **fields: Any) -> None:
    parts = [event, *[f"{k}={v}" for k, v in fields.items()]]
    log.info(" ".join(parts))
