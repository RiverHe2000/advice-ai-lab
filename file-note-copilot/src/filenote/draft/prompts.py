"""Prompts. Every system prompt starts with a machine-readable ``# task:`` line and every user
message with ``# meeting:``; real models ignore them, the scripted model keys on them."""

from __future__ import annotations

import json
import re
from typing import Any

from filenote.llm import ChatMessage
from filenote.schema import MeetingMeta, Segment, Transcript

TASK_RE = re.compile(r"^#\s*task:\s*(?P<task>\w+)", re.MULTILINE)
MEETING_RE = re.compile(r"^#\s*meeting:\s*(?P<id>\S+)", re.MULTILINE)
WINDOW_RE = re.compile(r"^#\s*window:\s*(?P<k>\d+)\s*/\s*(?P<n>\d+)", re.MULTILINE)
SEGMENT_LINE_RE = re.compile(r"^(?P<id>s\d{3,}) \[", re.MULTILINE)
JSON_BLOCK_RE = re.compile(r"```json\s*(?P<body>.*?)```", re.DOTALL)

NOTE_SCHEMA = """{
  "summary": "two or three sentences",
  "circumstance_changes": [{"text": "...", "evidence": ["s012"]}],
  "goals": [{"text": "...", "evidence": ["s020", "s021"]}],
  "topics_discussed": [{"text": "...", "evidence": ["s030"]}],
  "advice_discussed": [{"text": "...", "evidence": ["s031"]}],
  "decisions": [{"text": "...", "evidence": ["s033", "s034"]}],
  "action_items": [{"description": "...", "owner": "adviser|client|paraplanner",
                    "due": "YYYY-MM-DD or null",
                    "evidence": ["s040"]}],
  "compliance": {"risk_profile_confirmed": true, "risk_profile": "Balanced",
                 "fee_consent_discussed": false, "conflicts_disclosed": null,
                 "vulnerability_indicators": [{"text": "...", "evidence": ["s050"]}]},
  "follow_up": {"text": "...", "evidence": ["s060"]}
}"""

FACT_SCHEMA = """{"facts": [
  {"category": "one of circumstance_change, goal, topic, advice, decision, action_item,
                vulnerability, follow_up",
   "text": "one atomic fact with its figures", "evidence": ["s012"],
   "owner": "adviser|client|paraplanner (action_item only)", "due": "YYYY-MM-DD or null"},
  {"category": "compliance",
   "key": "risk_profile_confirmed|risk_profile|fee_consent_discussed|conflicts_disclosed",
   "value": true, "evidence": ["s050"]}
]}"""

RULES = """Rules:
- Every item must cite the ids of the transcript segments that support it; never invent ids.
- Write figures exactly as canonical numbers ($85,000, 9.5%), never change them.
- A decision is recorded only when the client explicitly agreed ("go ahead", "agreed",
  "let's do it"). Advice the client deferred ("think about it", "next time", "not yet")
  belongs in advice_discussed only.
- Small talk, pleasantries and contact-detail updates are not note content.
- Compliance flags: true if it happened, false if the transcript shows it did not, null if unknown.
- Output only JSON. No prose, no markdown."""


def render_segments(segments: list[Segment]) -> str:
    return "\n".join(f"{s.id} [{s.timestamp}] {s.speaker} ({s.role}): {s.text}" for s in segments)


def meeting_header(transcript: Transcript, meeting: MeetingMeta) -> str:
    who = ", ".join(f"{a.name} ({a.role})" for a in meeting.attendees)
    return (
        f"# meeting: {transcript.meeting_id}\n"
        f"# date: {meeting.date.isoformat()}\n# type: {meeting.type}\n# attendees: {who}"
    )


def single_shot_messages(transcript: Transcript, meeting: MeetingMeta) -> list[ChatMessage]:
    system = (
        "# task: single_shot\n"
        "You are a paraplanner at Northshore Financial Advice drafting the adviser's file note "
        "from a client-meeting transcript. Produce a JSON file note with exactly this shape:\n"
        f"{NOTE_SCHEMA}\n{RULES}"
    )
    user = f"{meeting_header(transcript, meeting)}\n\n{render_segments(transcript.segments)}"
    return [ChatMessage("system", system), ChatMessage("user", user)]


def extract_messages(
    transcript: Transcript, meeting: MeetingMeta, window: list[Segment], k: int, n: int
) -> list[ChatMessage]:
    system = (
        "# task: extract\n"
        "You extract atomic facts from one window of a client-meeting transcript for a "
        "financial adviser's file note. Return JSON with exactly this shape:\n"
        f"{FACT_SCHEMA}\n{RULES}\n"
        "Extract only what this window supports; other windows are handled separately."
    )
    user = f"{meeting_header(transcript, meeting)}\n# window: {k}/{n}\n\n{render_segments(window)}"
    return [ChatMessage("system", system), ChatMessage("user", user)]


def compose_messages(
    transcript: Transcript, meeting: MeetingMeta, facts: list[dict[str, Any]]
) -> list[ChatMessage]:
    system = (
        "# task: compose\n"
        "You compose a financial adviser's file note from a list of extracted facts. You do not "
        "have the transcript: use only the facts, keep their evidence ids and figures exactly, "
        "merge duplicates, and put each fact in the section matching its category. Return JSON "
        f"with exactly this shape:\n{NOTE_SCHEMA}\n{RULES}"
    )
    body = json.dumps({"facts": facts}, ensure_ascii=False, indent=1, default=str)
    user = f"{meeting_header(transcript, meeting)}\n\n```json\n{body}\n```"
    return [ChatMessage("system", system), ChatMessage("user", user)]


def repair_messages(
    transcript: Transcript,
    meeting: MeetingMeta,
    claims: list[dict[str, Any]],
    candidates: list[Segment],
) -> list[ChatMessage]:
    system = (
        "# task: repair\n"
        "Some claims in a draft file note are not supported by the segments they cite. For each "
        "claim, either cite the segment ids (from the candidates below) that actually support "
        'it, or drop it. Return JSON: {"resolutions": [{"index": 0, "action": "cite", '
        '"evidence": ["s012"]}, {"index": 1, "action": "drop"}]}. Never invent evidence.'
    )
    body = json.dumps({"claims": claims}, ensure_ascii=False, indent=1, default=str)
    user = (
        f"{meeting_header(transcript, meeting)}\n\n```json\n{body}\n```\n\n"
        f"Candidate segments:\n{render_segments(candidates)}"
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def retry_message(error: str) -> ChatMessage:
    return ChatMessage(
        "user", f"Your previous output was not valid: {error[:300]}. Return only the JSON object."
    )


# ----- parsing helpers used by the scripted model ------------------------------------------


def task_of(messages: list[ChatMessage] | tuple[ChatMessage, ...]) -> str:
    for m in messages:
        if m.role == "system":
            found = TASK_RE.search(m.content)
            if found:
                return found["task"]
    return "unknown"


def meeting_id_of(messages: list[ChatMessage] | tuple[ChatMessage, ...]) -> str | None:
    for m in messages:
        if m.role == "user":
            found = MEETING_RE.search(m.content)
            if found:
                return found["id"]
    return None


def last_user(messages: list[ChatMessage] | tuple[ChatMessage, ...]) -> str:
    for m in reversed(messages):
        if m.role == "user" and not m.content.startswith("Your previous output"):
            return m.content
    return ""


def segment_ids_in(text: str) -> list[str]:
    return SEGMENT_LINE_RE.findall(text)


def json_block_in(text: str) -> dict[str, Any] | None:
    found = JSON_BLOCK_RE.search(text)
    if not found:
        return None
    try:
        obj = json.loads(found["body"])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
