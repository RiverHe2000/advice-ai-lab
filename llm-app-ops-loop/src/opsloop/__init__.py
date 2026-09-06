"""opsloop: the operations loop around an LLM application after it ships.

Layers (each a package or module under ``opsloop``):

* ``sdk`` — tracing context managers, spans, pricing, PII redaction, sampling, exporters
  (SQLite / HTTP / OTLP-style JSON with ``gen_ai.*`` attribute names)
* ``store`` / ``collector`` — SQLite trace store with retention and a FastAPI ingest + query API
* ``demo`` — a scripted "Northshore Adviser Assistant" with seeded failure injection, the
  ground truth the monitor is measured against
* ``monitor`` — YAML SLOs, multi-window burn-rate alerts, text-input drift, self-evaluation
  (time-to-detect / detection / false alarms), Prometheus exporter
* ``quality`` / ``feedback`` — stratified sampling, heuristic scorers, an LLM rubric judge,
  explicit and implicit user feedback
* ``dataset`` / ``prompts`` — review queue → versioned JSONL evaluation sets; a prompt registry
  with content hashes, lint and diff
* ``regression`` / ``release`` — the paired-statistics prompt regression gate and the prompt
  canary with automatic rollback
* ``replay`` / ``incident`` — deterministic trace replay and incident-report generation
"""

__version__ = "0.1.0"
