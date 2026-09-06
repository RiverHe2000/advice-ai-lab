"""Two invariants of the demo worth stating as tests: every in-scope answer template quotes
only figures that exist in the tool outputs (v2, exact figures) and the v1 defect is confined
to the fee-percentage templates; plus settings from the environment."""

from __future__ import annotations

import pytest

from opsloop.config import Settings
from opsloop.demo.app import build_messages
from opsloop.demo.book import ClientBook
from opsloop.demo.model import DemoFakeModel
from opsloop.demo.questions import QUESTION_TYPES, QuestionType, render_question
from opsloop.demo.tools import Tools
from opsloop.prompts.registry import PromptRegistry
from opsloop.quality.scorers import score_answer

IN_SCOPE = [q for q in QUESTION_TYPES if q.in_scope]
V1_ROUNDING_TEMPLATES = {"fee_pct", "fds_summary", "total_fees"}


@pytest.mark.parametrize("qt", IN_SCOPE, ids=[q.name for q in IN_SCOPE])
def test_every_answer_template_is_grounded_under_v2(
    qt: QuestionType, registry: PromptRegistry, book: ClientBook
) -> None:
    model = DemoFakeModel()
    tools = Tools(book)
    spec = registry.get("adviser_assistant@v2")
    checked = 0
    for client in book.clients:
        if qt.requires is not None and not qt.requires(client):
            continue
        outputs = {name: tools.call(name, client.client_id) for name in qt.tools}
        variables = {
            "adviser_name": client.adviser_name,
            "today": book.today,
            "client_name": client.name,
            "risk_profile": client.risk_profile,
        }
        question = render_question(qt, client)
        answer = model.chat(build_messages(spec, variables, question, outputs)).text
        scores = score_answer(
            answer, tool_outputs=outputs, question=question, json_expected=qt.json_expected
        )
        assert scores.grounded, (qt.name, client.client_id, scores.ungrounded_numbers, answer)
        assert not scores.refusal and not scores.pii_leak and scores.passed, (qt.name, answer)
        if qt.json_expected:
            assert scores.json_valid
        checked += 1
        if checked >= 12:
            break
    assert checked > 0


def test_v1_defect_is_confined_to_fee_percentage_templates(
    registry: PromptRegistry, book: ClientBook
) -> None:
    model = DemoFakeModel()
    tools = Tools(book)
    spec = registry.get("adviser_assistant@v1")
    ungrounded_templates: set[str] = set()
    for qt in IN_SCOPE:
        for client in book.clients[:15]:
            if qt.requires is not None and not qt.requires(client):
                continue
            outputs = {name: tools.call(name, client.client_id) for name in qt.tools}
            variables = {
                "adviser_name": client.adviser_name,
                "today": book.today,
                "client_name": client.name,
                "risk_profile": client.risk_profile,
            }
            question = render_question(qt, client)
            answer = model.chat(build_messages(spec, variables, question, outputs)).text
            if not score_answer(answer, tool_outputs=outputs, question=question).grounded:
                ungrounded_templates.add(qt.name)
    assert ungrounded_templates and ungrounded_templates <= V1_ROUNDING_TEMPLATES


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPSLOOP_STORE_PATH", "x/y.sqlite")
    monkeypatch.setenv("OPSLOOP_MODEL__KIND", "openai")
    monkeypatch.setenv("OPSLOOP_MODEL__BASE_URL", "http://gateway:8080/v1")
    s = Settings()
    assert str(s.store_path).replace("\\", "/") == "x/y.sqlite"
    assert s.model.kind == "openai" and s.model.base_url == "http://gateway:8080/v1"
    assert Settings(environment="staging").environment == "staging"
