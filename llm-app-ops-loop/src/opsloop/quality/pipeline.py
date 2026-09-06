"""Ingest = store the trace + run the cheap heuristic scorers and write their outcome next to
it. Both the in-process SQLite exporter and the collector's ``POST /v1/traces`` go through
here, so the monitor sees the same signals whichever path a trace took."""

from __future__ import annotations

from opsloop.quality.scorers import HeuristicScores, score_trace
from opsloop.sdk.models import Trace
from opsloop.store import Signals, TraceStore


def signals_from(scores: HeuristicScores | None) -> Signals | None:
    if scores is None:
        return None
    return Signals(
        quality=scores.quality,
        refusal=scores.refusal,
        json_valid=scores.json_valid,
        pii_leak=scores.pii_leak,
        grounded=scores.grounded,
    )


def ingest_trace(store: TraceStore, trace: Trace) -> HeuristicScores | None:
    scores = score_trace(trace)
    signals = signals_from(scores)
    if signals is not None and int(trace.attributes.get("pii.output_redactions", 0)) > 0:
        signals = Signals(
            quality=signals.quality,
            refusal=signals.refusal,
            json_valid=signals.json_valid,
            pii_leak=True,
            grounded=signals.grounded,
        )
    store.insert_trace(trace, signals)
    return scores


class StoreExporter:
    """The default SDK exporter: ``Tracer(exporter=StoreExporter(store))``."""

    def __init__(self, store: TraceStore) -> None:
        self.store = store

    def __call__(self, trace: Trace) -> None:
        ingest_trace(self.store, trace)
