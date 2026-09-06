"""Prompt registry (hash stability, resolution by label or hash, lint, diff, StrictUndefined),
curation from traces, versioned datasets (hash, dedup, immutability, slices, diff)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opsloop.dataset.curate import (
    build_review_queue,
    curate_from_trace,
    read_review_queue,
    write_review_queue,
)
from opsloop.dataset.versioning import (
    DatasetStore,
    content_hash,
    find_near_duplicates,
    normalise_input,
)
from opsloop.prompts.registry import PromptRegistry, PromptSpec, parse_ref
from opsloop.store import TraceStore


def spec(
    version: str = "v1", template: str = "Hello {{ name }}, today is {{ today }}.", **kw: object
) -> PromptSpec:
    return PromptSpec(
        name="greeter",
        version=version,
        template=template,
        inputs=["name", "today"],
        metadata={"max_prompt_tokens": 50},
        **kw,
    )


def test_hash_is_stable_and_content_based() -> None:
    a, b = spec(), spec()
    assert a.content_hash == b.content_hash and len(a.content_hash) == 12
    assert spec(template="Hi {{ name }} {{ today }}").content_hash != a.content_hash
    assert spec(version="v2").content_hash == a.content_hash  # the label is not the identity
    assert a.ref == "greeter@v1" and a.declared_placeholders() == {"name", "today"}


def test_registry_register_get_list_and_conflicts(tmp_path: Path) -> None:
    reg = PromptRegistry(tmp_path / "prompts")
    assert reg.list_prompts() == []
    path = reg.register(spec())
    assert path.exists() and "content_hash" in path.read_text(encoding="utf-8")
    reg.register(spec())  # same content: idempotent
    with pytest.raises(FileExistsError):
        reg.register(spec(template="changed {{ name }} {{ today }}"))
    reg.register(spec(template="changed {{ name }} {{ today }}"), overwrite=True)
    reg.register(spec(version="v2", template="V2 {{ name }} {{ today }}"))
    assert [s.ref for s in reg.list_prompts()] == ["greeter@v1", "greeter@v2"] and reg.list_prompts(
        "nope"
    ) == []
    v2 = reg.get("greeter@v2")
    assert reg.get(f"greeter@{v2.content_hash[:6]}").version == "v2"
    with pytest.raises(KeyError):
        reg.get("greeter@v9")
    with pytest.raises(KeyError):
        reg.get("greeter")
    assert parse_ref("a@v1") == parse_ref("a@@v1") and parse_ref("a").version is None
    file = tmp_path / "loose.yaml"
    file.write_text(path.read_text(encoding="utf-8").replace("greeter", "other"), encoding="utf-8")
    assert reg.register_file(file).name == "other"


def test_render_strict_undefined_and_diff(registry: PromptRegistry) -> None:
    assert "Priya" in registry.render(
        "adviser_assistant@v1",
        {
            "adviser_name": "Priya",
            "today": "2026-09-01",
            "client_name": "C",
            "risk_profile": "Balanced",
        },
    )
    with pytest.raises(KeyError, match="client_name"):
        registry.render("adviser_assistant@v1", {"adviser_name": "Priya", "today": "2026-09-01"})
    diff = registry.diff("adviser_assistant@v1", "adviser_assistant@v2")
    assert diff.startswith("--- adviser_assistant@v1") and "+- Quote figures exactly" in diff
    reg = PromptRegistry(Path("unused"))
    a, b = spec(), spec(version="v2")
    b.metadata["temperature"] = 0.7
    reg.get = lambda ref: a if str(ref).endswith("v1") else b  # type: ignore[method-assign]
    assert "metadata.temperature: None -> 0.7" in reg.diff("greeter@v1", "greeter@v2")


def test_lint_findings(tmp_path: Path) -> None:
    reg = PromptRegistry(tmp_path)
    reg.register(spec())
    assert reg.lint("greeter@v1") == []
    reg.register(
        PromptSpec(
            name="bad",
            version="v1",
            template="Hi {{ name }} {missing} {{ extra }} guaranteed return " * 3,
            inputs=["name", "unused"],
            metadata={"max_prompt_tokens": 10, "forbidden_phrases": ["extra"]},
        )
    )
    codes = {f.code for f in reg.lint("bad@v1")}
    assert codes == {
        "undeclared_placeholder",
        "unused_input",
        "single_brace",
        "token_budget",
        "forbidden_phrase",
        "render_failed",
    }
    assert any(f.level == "error" for f in reg.lint("bad@v1"))
    reg.register(PromptSpec(name="broken", version="v1", template="{% if %}", inputs=[]))
    assert [f.code for f in reg.lint("broken@v1")] == ["syntax_error"]
    assert (
        reg.lint(
            "greeter@v1", sample_variables={"name": "x" * 400, "today": "t"}, max_prompt_tokens=5
        )[0].code
        == "token_budget"
    )


def test_project_prompts_lint_clean(registry: PromptRegistry) -> None:
    for s in registry.list_prompts():
        assert [f for f in registry.lint(s.ref) if f.level == "error"] == [], s.ref


def test_curate_from_trace_and_review_queue(make_trace, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    trace = make_trace("abc123456789xyz")
    case = curate_from_trace(trace, reviewer="c.he", now=1.0)
    assert (
        case.id == "case-abc123456789"
        and case.input == trace.input_text
        and case.reference == trace.output_text
    )
    assert (
        case.expected.numeric_facts == [123456.78, 2]
        and case.expected.must_not_contain
        and not case.expected.allow_refusal
    )
    assert (
        set(case.tags) >= {"balances", "total_balance", "prompt:v1"}
        and case.provenance.trace_id == trace.trace_id
    )
    oos = make_trace(
        "oos",
        output="I can only help with platform data.",
        attributes={
            "app.intent": "cgt_estimate",
            "app.category": "out_of_scope",
            "prompt.variables": {},
        },
    )
    oos_case = curate_from_trace(oos, reviewer="r", now=1.0)
    assert (
        oos_case.expected.allow_refusal
        and oos_case.expected.must_contain == ["can only help"]
        and oos_case.reference is None
        and "out_of_scope" in oos_case.tags
    )
    js = make_trace("js", json_expected=True, output='{"a": 1}')
    assert (
        curate_from_trace(js, reviewer="r", now=1.0).expected.json_expected
        and "json" in curate_from_trace(js, reviewer="r", now=1.0).tags
    )
    blocked = make_trace("blk", json_expected=True, attributes={"guardrail.blocked": True})
    assert curate_from_trace(blocked, reviewer="r", now=1.0).expected.json_expected is False
    store = TraceStore(":memory:")
    store.insert_trace(trace)
    store.insert_trace(make_trace("err", status="error"))
    store.add_feedback(trace.trace_id, 1.0, True, {"thumbs": "down"})
    items = build_review_queue(store, [trace.trace_id, "err", "missing"], reviewer="c.he", now=1.0)
    assert (
        len(items) == 1
        and items[0].feedback[0]["thumbs"] == "down"
        and items[0].status == "pending"
    )
    queue = tmp_path / "q" / "review.jsonl"
    assert write_review_queue(items, queue) == 1
    assert read_review_queue(queue)[0].case.id == case.id


def test_dataset_versions_hash_dedup_slices_diff(make_trace, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from opsloop.demo.questions import QUESTION_TYPES

    cases = [
        curate_from_trace(
            make_trace(
                f"case{i:02d}",
                question=QUESTION_TYPES[i].text.format(
                    client=f"Client {i}", risk_profile="Balanced"
                ),
            ),
            reviewer="r",
            now=1.0,
        )
        for i in range(6)
    ]
    ds = DatasetStore(tmp_path / "datasets")
    assert ds.names() == [] and ds.versions("x") == []
    with pytest.raises(FileNotFoundError):
        ds.load("adviser")
    v1 = ds.build("adviser", cases[:4], now="2026-09-06", changelog="seed")
    assert (
        v1.manifest.version == 1
        and v1.manifest.n_cases == 4
        and v1.manifest.content_hash == content_hash(cases[:4])
    )
    assert (
        v1.manifest.slices["balances"] == 4
        and "seed" in v1.manifest.changelog[0]
        and ds.names() == ["adviser"]
    )
    dup = cases[0].model_copy(update={"id": "dup", "input": cases[0].input + " "})
    v2 = ds.build("adviser", [dup, *cases[4:]], now="2026-09-07")
    assert v2.manifest.version == 2 and v2.manifest.n_cases == 6 and v2.manifest.parent_version == 1
    assert v2.manifest.duplicates_rejected[0]["duplicate_of"] == cases[0].id
    assert ds.load("adviser").manifest.version == 2 and ds.load("adviser", 1).manifest.version == 1
    with pytest.raises(FileExistsError):
        ds.build("adviser", [], version=2, now="x")
    diff = ds.diff("adviser", 1, 2)
    assert (
        diff["added"] == ["case-case04", "case-case05"]
        and diff["removed"] == []
        and diff["to"]["n"] == 6
    )
    fresh = ds.build("adviser", cases[:2], now="2026-09-08", extend_previous=False)
    assert fresh.manifest.n_cases == 2 and fresh.manifest.parent_version is None
    assert fresh.slice("balances") and fresh.slices(min_cases=3) == {}
    kept, rejected = find_near_duplicates(cases[:2], [], threshold=50.0)
    assert (
        len(kept) == 1 and rejected[0]["id"] == cases[1].id and normalise_input("  A   b ") == "a b"
    )
    path = tmp_path / "datasets" / "adviser" / "v1.jsonl"
    path.write_text(
        path.read_text(encoding="utf-8").replace("total balance", "TOTAL balance"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        ds.load("adviser", 1)
    with pytest.raises(FileNotFoundError):
        ds.load("adviser", 9)
    manifest = json.loads(
        (tmp_path / "datasets" / "adviser" / "v2.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["parent_hash"] == v1.manifest.content_hash
