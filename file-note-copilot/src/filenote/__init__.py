"""filenote: draft, verify and approve a financial adviser's file note from a meeting transcript.

Layers:

* ``schema`` — the typed file note (every claim cites transcript segment ids) and the transcript
* ``numbers`` — spoken / written number and date normalisation used by the verifier
* ``corpus`` — seeded synthetic meetings with gold notes and known small talk / deferrals
* ``llm`` — chat-model protocol with scripted (gold-derived, corruptible), OpenAI-compatible
  and Hugging Face backends; tolerant JSON repair
* ``draft`` — ``single_shot``, ``extract_then_compose`` and ``verified`` drafting strategies
* ``verify`` — deterministic claim verifier and its self-evaluation on planted hallucinations
* ``pii`` — reversible pseudonymisation before the model, redaction for anything logged
* ``eval`` — metrics against gold, bootstrap / paired statistics, reports and gates
* ``store`` / ``audit`` — SQLite drafts, versions, approvals, feedback; redacted JSONL audit
* ``web`` — FastAPI + Server-Sent Events + a framework-free HTML/CSS/JS front end
"""

__version__ = "0.1.0"
