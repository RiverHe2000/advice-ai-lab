"""SQLite trace store: traces (with denormalised quality / feedback signals so the monitor can
window them with one query), spans, feedback and judge scores; indexes on time, status, prompt
version and session; retention; JSONL export."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opsloop.sdk.models import Span, Trace

SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
  trace_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  app_version TEXT NOT NULL,
  prompt_name TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  start_ts REAL NOT NULL,
  end_ts REAL NOT NULL,
  latency_ms REAL NOT NULL,
  status TEXT NOT NULL,
  error_class TEXT,
  input_text TEXT NOT NULL,
  output_text TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL,
  completion_tokens INTEGER NOT NULL,
  cost_usd REAL,
  cost_missing INTEGER NOT NULL,
  json_expected INTEGER NOT NULL,
  sampled INTEGER NOT NULL,
  attributes TEXT NOT NULL,
  spans TEXT NOT NULL,
  quality REAL,
  judge REAL,
  refusal INTEGER,
  json_valid INTEGER,
  pii_leak INTEGER,
  grounded INTEGER,
  negative_feedback INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_traces_start ON traces(start_ts);
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status, start_ts);
CREATE INDEX IF NOT EXISTS idx_traces_prompt ON traces(prompt_version, start_ts);
CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
CREATE TABLE IF NOT EXISTS spans (
  span_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  start_ts REAL NOT NULL,
  latency_ms REAL NOT NULL,
  status TEXT NOT NULL,
  error_class TEXT,
  model TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  cost_usd REAL,
  cost_missing INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_kind ON spans(kind, name, start_ts);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id TEXT NOT NULL,
  ts REAL NOT NULL,
  negative INTEGER NOT NULL,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_trace ON feedback(trace_id);
CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id TEXT NOT NULL,
  scorer TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  ts REAL NOT NULL,
  missing INTEGER NOT NULL,
  repairs INTEGER NOT NULL,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scores_trace ON scores(trace_id);
"""

ROW_COLUMNS = (
    "trace_id, session_id, prompt_version, start_ts, end_ts, latency_ms, status, error_class, "
    "input_text, output_text, prompt_tokens, completion_tokens, cost_usd, cost_missing, "
    "json_expected, quality, judge, refusal, json_valid, pii_leak, grounded, negative_feedback, "
    "attributes"
)


@dataclass(slots=True)
class TraceRow:
    """A trace without its spans — what windowed monitoring, canary analysis and the incident
    report iterate over."""

    trace_id: str
    session_id: str
    prompt_version: str
    start_ts: float
    end_ts: float
    latency_ms: float
    status: str
    error_class: str | None
    input_text: str
    output_text: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    cost_missing: bool
    json_expected: bool
    quality: float | None
    judge: float | None
    refusal: bool | None
    json_valid: bool | None
    pii_leak: bool | None
    grounded: bool | None
    negative_feedback: bool
    attributes: dict[str, Any]

    @classmethod
    def from_sql(cls, r: tuple[Any, ...]) -> TraceRow:
        def _b(v: Any) -> bool | None:
            return None if v is None else bool(v)

        return cls(
            trace_id=r[0],
            session_id=r[1],
            prompt_version=r[2],
            start_ts=r[3],
            end_ts=r[4],
            latency_ms=r[5],
            status=r[6],
            error_class=r[7],
            input_text=r[8],
            output_text=r[9],
            prompt_tokens=r[10],
            completion_tokens=r[11],
            cost_usd=r[12],
            cost_missing=bool(r[13]),
            json_expected=bool(r[14]),
            quality=r[15],
            judge=r[16],
            refusal=_b(r[17]),
            json_valid=_b(r[18]),
            pii_leak=_b(r[19]),
            grounded=_b(r[20]),
            negative_feedback=bool(r[21]),
            attributes=json.loads(r[22]) if r[22] else {},
        )


@dataclass(frozen=True, slots=True)
class Signals:
    """Denormalised heuristic outcomes written next to the trace."""

    quality: float | None
    refusal: bool | None
    json_valid: bool | None
    pii_leak: bool | None
    grounded: bool | None


@dataclass(frozen=True, slots=True)
class SpanErrorRow:
    trace_id: str
    kind: str
    name: str
    start_ts: float
    error_class: str | None


class TraceStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ----- writes ---------------------------------------------------------------------------

    def insert_trace(self, trace: Trace, signals: Signals | None = None) -> None:
        self.insert_traces([trace], [signals] if signals else None)

    def insert_traces(
        self, traces: list[Trace], signals: list[Signals | None] | None = None
    ) -> None:
        sig = signals or [None] * len(traces)
        trace_rows: list[tuple[Any, ...]] = []
        span_rows: list[tuple[Any, ...]] = []
        for t, s in zip(traces, sig, strict=True):
            trace_rows.append(
                (
                    t.trace_id,
                    t.request_id,
                    t.session_id,
                    t.app_version,
                    t.prompt_name,
                    t.prompt_version,
                    t.start_ts,
                    t.end_ts,
                    t.latency_ms,
                    t.status,
                    t.error_class,
                    t.input_text,
                    t.output_text,
                    t.prompt_tokens,
                    t.completion_tokens,
                    t.cost_usd,
                    int(t.cost_missing),
                    int(t.json_expected),
                    int(t.sampled),
                    json.dumps(t.attributes, sort_keys=True, default=str),
                    json.dumps([sp.model_dump(mode="json") for sp in t.spans], default=str),
                    None if s is None else s.quality,
                    None if s is None or s.refusal is None else int(s.refusal),
                    None if s is None or s.json_valid is None else int(s.json_valid),
                    None if s is None or s.pii_leak is None else int(s.pii_leak),
                    None if s is None or s.grounded is None else int(s.grounded),
                )
            )
            span_rows.extend(
                (
                    sp.span_id,
                    t.trace_id,
                    sp.kind,
                    sp.name,
                    sp.start_ts,
                    sp.latency_ms,
                    sp.status,
                    sp.error_class,
                    sp.model,
                    sp.prompt_tokens,
                    sp.completion_tokens,
                    sp.cost_usd,
                    int(sp.cost_missing),
                )
                for sp in t.spans
            )
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO traces (trace_id, request_id, session_id, "
                "app_version, prompt_name, prompt_version, start_ts, end_ts, latency_ms, "
                "status, error_class, input_text, output_text, prompt_tokens, "
                "completion_tokens, cost_usd, cost_missing, json_expected, sampled, "
                "attributes, spans, quality, refusal, json_valid, pii_leak, grounded) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                trace_rows,
            )
            if span_rows:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", span_rows
                )
            self._conn.commit()

    def update_signals(self, trace_id: str, signals: Signals) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE traces SET quality=?, refusal=?, json_valid=?, pii_leak=?, grounded=? "
                "WHERE trace_id=?",
                (
                    signals.quality,
                    None if signals.refusal is None else int(signals.refusal),
                    None if signals.json_valid is None else int(signals.json_valid),
                    None if signals.pii_leak is None else int(signals.pii_leak),
                    None if signals.grounded is None else int(signals.grounded),
                    trace_id,
                ),
            )
            self._conn.commit()

    def add_feedback(
        self, trace_id: str, ts: float, negative: bool, payload: dict[str, Any]
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO feedback (trace_id, ts, negative, payload) VALUES (?,?,?,?)",
                (trace_id, ts, int(negative), json.dumps(payload, sort_keys=True, default=str)),
            )
            if negative:
                self._conn.execute(
                    "UPDATE traces SET negative_feedback=1 WHERE trace_id=?", (trace_id,)
                )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def add_score(
        self,
        trace_id: str,
        *,
        scorer: str,
        model: str,
        prompt_version: str,
        ts: float,
        missing: bool,
        repairs: int,
        payload: dict[str, Any],
        judge_mean: float | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO scores (trace_id, scorer, model, prompt_version, ts, missing, "
                "repairs, payload) VALUES (?,?,?,?,?,?,?,?)",
                (
                    trace_id,
                    scorer,
                    model,
                    prompt_version,
                    ts,
                    int(missing),
                    repairs,
                    json.dumps(payload, sort_keys=True, default=str),
                ),
            )
            if judge_mean is not None:
                self._conn.execute(
                    "UPDATE traces SET judge=? WHERE trace_id=?", (judge_mean, trace_id)
                )
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def prune(self, older_than_ts: float) -> int:
        with self._lock:
            ids = [
                r[0]
                for r in self._conn.execute(
                    "SELECT trace_id FROM traces WHERE start_ts < ?", (older_than_ts,)
                )
            ]
            for chunk_start in range(0, len(ids), 500):
                chunk = ids[chunk_start : chunk_start + 500]
                marks = ",".join("?" * len(chunk))
                for table in ("spans", "feedback", "scores", "traces"):
                    self._conn.execute(f"DELETE FROM {table} WHERE trace_id IN ({marks})", chunk)
            self._conn.commit()
        return len(ids)

    # ----- reads ----------------------------------------------------------------------------

    def get_trace(self, trace_id: str) -> Trace | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT trace_id, request_id, session_id, app_version, prompt_name, "
                "prompt_version, start_ts, end_ts, latency_ms, status, error_class, input_text, "
                "output_text, prompt_tokens, completion_tokens, cost_usd, cost_missing, "
                "json_expected, sampled, "
                "attributes, spans FROM traces WHERE trace_id=?",
                (trace_id,),
            ).fetchone()
        return None if row is None else self._trace_from_sql(row)

    @staticmethod
    def _trace_from_sql(r: tuple[Any, ...]) -> Trace:
        return Trace(
            trace_id=r[0],
            request_id=r[1],
            session_id=r[2],
            app_version=r[3],
            prompt_name=r[4],
            prompt_version=r[5],
            start_ts=r[6],
            end_ts=r[7],
            latency_ms=r[8],
            status=r[9],
            error_class=r[10],
            input_text=r[11],
            output_text=r[12],
            prompt_tokens=r[13],
            completion_tokens=r[14],
            cost_usd=r[15],
            cost_missing=bool(r[16]),
            json_expected=bool(r[17]),
            sampled=bool(r[18]),
            attributes=json.loads(r[19]),
            spans=[Span.model_validate(s) for s in json.loads(r[20])],
        )

    def query(
        self,
        *,
        since: float | None = None,
        until: float | None = None,
        status: str | None = None,
        prompt_version: str | None = None,
        session_id: str | None = None,
        limit: int = 1000,
    ) -> list[Trace]:
        where, params = self._where(since, until, status, prompt_version, session_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT trace_id, request_id, session_id, app_version, prompt_name, "
                "prompt_version, start_ts, end_ts, latency_ms, status, error_class, input_text, "
                "output_text, prompt_tokens, completion_tokens, cost_usd, cost_missing, "
                "json_expected, sampled, "
                f"attributes, spans FROM traces{where} ORDER BY start_ts LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [self._trace_from_sql(r) for r in rows]

    def rows(
        self,
        since: float | None = None,
        until: float | None = None,
        *,
        status: str | None = None,
        prompt_version: str | None = None,
        session_id: str | None = None,
    ) -> list[TraceRow]:
        where, params = self._where(since, until, status, prompt_version, session_id)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {ROW_COLUMNS} FROM traces{where} ORDER BY start_ts", params
            ).fetchall()
        return [TraceRow.from_sql(r) for r in rows]

    @staticmethod
    def _where(
        since: float | None,
        until: float | None,
        status: str | None,
        prompt_version: str | None,
        session_id: str | None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("start_ts >= ?")
            params.append(since)
        if until is not None:
            clauses.append("start_ts < ?")
            params.append(until)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if prompt_version is not None:
            clauses.append("prompt_version = ?")
            params.append(prompt_version)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params

    def span_errors(self, since: float, until: float) -> list[SpanErrorRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT trace_id, kind, name, start_ts, error_class FROM spans "
                "WHERE status='error' AND start_ts >= ? AND start_ts < ? ORDER BY start_ts",
                (since, until),
            ).fetchall()
        return [SpanErrorRow(*r) for r in rows]

    def feedback_for(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, negative, payload FROM feedback WHERE trace_id=? ORDER BY id",
                (trace_id,),
            ).fetchall()
        return [{"id": r[0], "ts": r[1], "negative": bool(r[2]), **json.loads(r[3])} for r in rows]

    def scores_for(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, scorer, model, prompt_version, ts, missing, repairs, payload "
                "FROM scores WHERE trace_id=? ORDER BY id",
                (trace_id,),
            ).fetchall()
        return [
            {
                "id": r[0],
                "scorer": r[1],
                "model": r[2],
                "prompt_version": r[3],
                "ts": r[4],
                "missing": bool(r[5]),
                "repairs": r[6],
                **json.loads(r[7]),
            }
            for r in rows
        ]

    def judged_ids(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT DISTINCT trace_id FROM scores").fetchall()
        return {r[0] for r in rows}

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0])

    def time_range(self) -> tuple[float, float] | None:
        with self._lock:
            row = self._conn.execute("SELECT MIN(start_ts), MAX(end_ts) FROM traces").fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0]), float(row[1])

    def iter_export(self, since: float | None = None) -> Iterator[dict[str, Any]]:
        for trace in self.query(since=since, limit=10_000_000):
            yield {
                **trace.model_dump(mode="json"),
                "feedback": self.feedback_for(trace.trace_id),
                "scores": self.scores_for(trace.trace_id),
            }

    def export_jsonl(self, path: Path, since: float | None = None) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with path.open("w", encoding="utf-8") as fh:
            for record in self.iter_export(since):
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                n += 1
        return n
