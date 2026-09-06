"""Append-only JSON-lines audit trail. Every string is passed through the PII redactor before
it is written (TFN, phone, e-mail, DOB, address), so the log itself cannot become a leak; the
approver's identity is preserved because accountability is the point of the log."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from filenote.pii import redact_any


class AuditLog:
    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._memory: list[dict[str, Any]] = []
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path | None:
        return self._path

    def record(self, kind: str, draft_id: str, **fields: Any) -> dict[str, Any]:
        entry = {
            "ts": dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds"),
            "kind": kind,
            "draft_id": draft_id,
            **redact_any(fields),
        }
        if self._path is None:
            self._memory.append(entry)
        else:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return entry

    def entries(self, draft_id: str | None = None) -> list[dict[str, Any]]:
        if self._path is None:
            rows = list(self._memory)
        elif not self._path.exists():
            rows = []
        else:
            with self._path.open(encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
        if draft_id is not None:
            rows = [r for r in rows if r.get("draft_id") == draft_id]
        return rows

    def export(self, out: Path | str, *, draft_id: str | None = None) -> int:
        """Write the (already redacted) entries as JSONL; returns the number of entries."""
        rows = self.entries(draft_id)
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(redact_any(r), ensure_ascii=False, default=str) + "\n")
        return len(rows)

    def timeline(self, draft_id: str) -> str:
        lines = [f"# draft {draft_id}"]
        for e in self.entries(draft_id):
            rest = {k: v for k, v in e.items() if k not in ("ts", "kind", "draft_id")}
            lines.append(f"[{e['ts']}] {e['kind']}: {json.dumps(rest, ensure_ascii=False)}")
        return "\n".join(lines) + "\n"
