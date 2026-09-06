"""SQLite system of record: drafts, note versions (AI draft, adviser edits), approvals with
the diff between the AI draft and the approved text, and feedback. Thread-safe behind one
lock; ``None`` path keeps it in memory (tests, CI)."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from filenote.schema import FileNote, Transcript

DraftStatus = Literal["queued", "drafting", "done", "failed", "approved"]
VersionSource = Literal["ai", "adviser"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL, strategy TEXT NOT NULL,
  model TEXT NOT NULL, meeting_id TEXT NOT NULL, pseudonymised INTEGER NOT NULL,
  transcript_json TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id TEXT NOT NULL, n INTEGER NOT NULL,
  source TEXT NOT NULL, editor TEXT, created_at TEXT NOT NULL, note_json TEXT NOT NULL,
  verification_json TEXT, UNIQUE(draft_id, n)
);
CREATE TABLE IF NOT EXISTS approvals (
  draft_id TEXT PRIMARY KEY, approver TEXT NOT NULL, approved_at TEXT NOT NULL,
  version_n INTEGER NOT NULL, diff TEXT NOT NULL, changed_lines INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id TEXT NOT NULL, thumbs TEXT NOT NULL,
  comment TEXT NOT NULL, wrong_claims_json TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")


class DraftRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: str
    status: DraftStatus
    strategy: str
    model: str
    meeting_id: str
    pseudonymised: bool
    transcript: Transcript
    error: str | None = None


class VersionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    n: int
    source: VersionSource
    editor: str | None = None
    created_at: str
    note: FileNote
    verification: dict[str, Any] | None = None


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    approver: str
    approved_at: str
    version_n: int
    diff: str
    changed_lines: int


class FeedbackRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    draft_id: str
    thumbs: Literal["up", "down"]
    comment: str = ""
    wrong_claims: list[str] = Field(default_factory=list)
    created_at: str


class DraftStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self._path = str(path) if path is not None else ":memory:"
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ----- drafts -----------------------------------------------------------------------------

    def create_draft(
        self,
        draft_id: str,
        transcript: Transcript,
        *,
        strategy: str,
        model: str,
        pseudonymised: bool,
    ) -> DraftRecord:
        with self._lock:
            self._conn.execute(
                "INSERT INTO drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    draft_id,
                    _now(),
                    "queued",
                    strategy,
                    model,
                    transcript.meeting_id,
                    int(pseudonymised),
                    transcript.model_dump_json(),
                ),
            )
            self._conn.commit()
        record = self.get_draft(draft_id)
        assert record is not None
        return record

    def set_status(self, draft_id: str, status: DraftStatus, *, error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE drafts SET status = ?, error = ? WHERE id = ?", (status, error, draft_id)
            )
            self._conn.commit()

    def get_draft(self, draft_id: str) -> DraftRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            return None
        return DraftRecord(
            id=row["id"],
            created_at=row["created_at"],
            status=row["status"],
            strategy=row["strategy"],
            model=row["model"],
            meeting_id=row["meeting_id"],
            pseudonymised=bool(row["pseudonymised"]),
            transcript=Transcript.model_validate_json(row["transcript_json"]),
            error=row["error"],
        )

    def list_drafts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, status, strategy, model, meeting_id FROM drafts "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ----- versions ---------------------------------------------------------------------------

    def add_version(
        self,
        draft_id: str,
        note: FileNote,
        *,
        source: VersionSource,
        editor: str | None = None,
        verification: dict[str, Any] | None = None,
    ) -> VersionRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(n), 0) AS n FROM versions WHERE draft_id = ?", (draft_id,)
            ).fetchone()
            n = int(row["n"]) + 1
            created = _now()
            self._conn.execute(
                "INSERT INTO versions (draft_id, n, source, editor, created_at, note_json, "
                "verification_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    draft_id,
                    n,
                    source,
                    editor,
                    created,
                    note.model_dump_json(),
                    json.dumps(verification) if verification is not None else None,
                ),
            )
            self._conn.commit()
        return VersionRecord(
            draft_id=draft_id,
            n=n,
            source=source,
            editor=editor,
            created_at=created,
            note=note,
            verification=verification,
        )

    def _version_from_row(self, row: sqlite3.Row) -> VersionRecord:
        return VersionRecord(
            draft_id=row["draft_id"],
            n=int(row["n"]),
            source=row["source"],
            editor=row["editor"],
            created_at=row["created_at"],
            note=FileNote.model_validate_json(row["note_json"]),
            verification=json.loads(row["verification_json"]) if row["verification_json"] else None,
        )

    def versions(self, draft_id: str) -> list[VersionRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM versions WHERE draft_id = ? ORDER BY n", (draft_id,)
            ).fetchall()
        return [self._version_from_row(r) for r in rows]

    def latest_version(self, draft_id: str) -> VersionRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM versions WHERE draft_id = ? ORDER BY n DESC LIMIT 1", (draft_id,)
            ).fetchone()
        return self._version_from_row(row) if row is not None else None

    def first_version(self, draft_id: str) -> VersionRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM versions WHERE draft_id = ? ORDER BY n ASC LIMIT 1", (draft_id,)
            ).fetchone()
        return self._version_from_row(row) if row is not None else None

    # ----- approvals --------------------------------------------------------------------------

    def approve(
        self, draft_id: str, *, approver: str, version_n: int, diff: str, changed_lines: int
    ) -> ApprovalRecord:
        approved_at = _now()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO approvals VALUES (?, ?, ?, ?, ?, ?)",
                (draft_id, approver, approved_at, version_n, diff, changed_lines),
            )
            self._conn.execute("UPDATE drafts SET status = 'approved' WHERE id = ?", (draft_id,))
            self._conn.commit()
        return ApprovalRecord(
            draft_id=draft_id,
            approver=approver,
            approved_at=approved_at,
            version_n=version_n,
            diff=diff,
            changed_lines=changed_lines,
        )

    def approval(self, draft_id: str) -> ApprovalRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM approvals WHERE draft_id = ?", (draft_id,)
            ).fetchone()
        if row is None:
            return None
        return ApprovalRecord(
            draft_id=row["draft_id"],
            approver=row["approver"],
            approved_at=row["approved_at"],
            version_n=int(row["version_n"]),
            diff=row["diff"],
            changed_lines=int(row["changed_lines"]),
        )

    # ----- feedback ---------------------------------------------------------------------------

    def add_feedback(
        self, draft_id: str, *, thumbs: Literal["up", "down"], comment: str, wrong_claims: list[str]
    ) -> FeedbackRecord:
        created = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO feedback (draft_id, thumbs, comment, wrong_claims_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (draft_id, thumbs, comment, json.dumps(wrong_claims), created),
            )
            self._conn.commit()
            fid = int(cur.lastrowid or 0)
        return FeedbackRecord(
            id=fid,
            draft_id=draft_id,
            thumbs=thumbs,
            comment=comment,
            wrong_claims=wrong_claims,
            created_at=created,
        )

    def feedback(self, draft_id: str) -> list[FeedbackRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM feedback WHERE draft_id = ? ORDER BY id", (draft_id,)
            ).fetchall()
        return [
            FeedbackRecord(
                id=int(r["id"]),
                draft_id=r["draft_id"],
                thumbs=r["thumbs"],
                comment=r["comment"],
                wrong_claims=json.loads(r["wrong_claims_json"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]
