"""PII checksums and redaction, JSON repair, statistics against hand-computed values, time
helpers, and the chat-model backends."""

from __future__ import annotations

import math
import random

import httpx
import pytest

from opsloop import jsonrepair, pii, stats, timeutil
from opsloop.llm import (
    ChatMessage,
    FakeChatModel,
    ModelError,
    OpenAICompatibleChatModel,
    build_model,
    estimate_tokens,
    to_provider_messages,
)

# ----- PII ----------------------------------------------------------------------------------


def test_tfn_and_abn_checksums() -> None:
    assert pii.tfn_valid("123 456 782")
    assert not pii.tfn_valid("123 456 789")
    assert not pii.tfn_valid("12345")
    rng = random.Random(3)
    assert pii.tfn_valid(pii.generate_tfn(rng))
    abn = pii.generate_abn(rng)
    assert pii.abn_valid(abn) and not pii.abn_valid("12 345 678 901") and not pii.abn_valid("123")


def test_find_and_redact_pii_kinds() -> None:
    text = "TFN 123 456 782, ABN 51 824 753 556, mail me at x.y@example.com or 0412 345 678; balance 123456.78"
    kinds = [m.kind for m in pii.find_pii(text)]
    assert kinds == ["tfn", "abn", "email", "phone"]
    redacted, counts = pii.redact_text(text)
    assert counts == {"tfn": 1, "abn": 1, "email": 1, "phone": 1}
    assert "123456.78" in redacted and "[ABN]" in redacted and pii.contains_marker(redacted)
    assert pii.redact_text("nothing here") == ("nothing here", {})


def test_redact_value_recurses_and_leaves_numbers() -> None:
    counts: dict[str, int] = {}
    out = pii.redact_value({"a": ["x@y.io", 5, {"b": "0412 345 678"}], "n": 1.5}, counts)
    assert out == {"a": ["[EMAIL]", 5, {"b": "[PHONE]"}], "n": 1.5}
    assert counts == {"email": 1, "phone": 1}


# ----- JSON repair --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "repairs"),
    [
        ('{"a": 1}', {"a": 1}, 0),
        ('```json\n{"a": 1}\n```', {"a": 1}, 1),
        ('Sure! {"a": 1, "b": [1, 2]} hope that helps', {"a": 1, "b": [1, 2]}, 1),
        ('{"a": 1, "b": 2,}', {"a": 1, "b": 2}, 1),
        ("[1, 2, 3,]", [1, 2, 3], 1),
    ],
)
def test_repair_json_cases(text: str, value: object, repairs: int) -> None:
    result = jsonrepair.repair_json(text)
    assert result.ok and result.value == value and result.repairs == repairs


def test_repair_json_failure_is_explicit() -> None:
    assert jsonrepair.repair_json("no json here").error == "no JSON object found"
    broken = jsonrepair.repair_json('{"a": [1, 2')
    assert not broken.ok and broken.error is not None and broken.value is None
    assert jsonrepair.repair_json("```json\n{oops\n```").value is None
    assert jsonrepair.is_valid_json('{"x": 1}') and not jsonrepair.is_valid_json("{x}")


# ----- statistics ---------------------------------------------------------------------------


def test_bootstrap_mean_ci_brackets_mean_and_handles_edges() -> None:
    ci = stats.bootstrap_mean_ci([1.0, 2.0, 3.0, 4.0, 5.0], n_boot=500, seed=1)
    assert ci.low <= ci.mean == 3.0 <= ci.high and ci.n == 5
    assert ci.as_dict()["n"] == 5
    assert math.isnan(stats.bootstrap_mean_ci([]).mean)
    single = stats.bootstrap_mean_ci([2.0])
    assert single.low == single.high == 2.0
    same = stats.bootstrap_mean_ci([1.0, 2.0, 3.0], seed=4)
    assert same == stats.bootstrap_mean_ci([1.0, 2.0, 3.0], seed=4)


def test_paired_bootstrap_and_mcnemar() -> None:
    cand = [0.9, 0.8, 1.0, 0.7, 0.9, 0.95]
    base = [0.8, 0.8, 0.9, 0.6, 0.85, 0.9]
    r = stats.paired_bootstrap(cand, base, n_boot=500, seed=0)
    assert r.n == 6 and r.delta == pytest.approx(
        sum(c - b for c, b in zip(cand, base, strict=True)) / 6
    )
    assert r.low <= r.delta <= r.high and r.wins == 5 and r.losses == 0 and r.ties == 1
    assert r.p_improve == 1.0
    assert stats.paired_bootstrap([], []).n == 0
    one = stats.paired_bootstrap([1.0], [0.5])
    assert one.low == one.high == 0.5
    with pytest.raises(ValueError):
        stats.paired_bootstrap([1.0], [1.0, 2.0])
    assert stats.mcnemar_exact(0, 0) == 1.0
    assert stats.mcnemar_exact(5, 5) == 1.0
    assert stats.mcnemar_exact(10, 0) == pytest.approx(2 / 1024)
    assert stats.mcnemar_exact(0, 10) == pytest.approx(2 / 1024)


def test_two_proportion_test_directions() -> None:
    worse = stats.two_proportion_test(20, 100, 5, 100, alternative="greater")
    assert worse.diff == pytest.approx(0.15) and worse.p_value < 0.01 and worse.z > 0
    assert stats.two_proportion_test(5, 100, 20, 100, alternative="greater").p_value > 0.99
    assert stats.two_proportion_test(5, 100, 20, 100, alternative="less").p_value < 0.01
    two = stats.two_proportion_test(20, 100, 5, 100, alternative="two-sided")
    assert two.p_value == pytest.approx(2 * worse.p_value)
    assert stats.two_proportion_test(0, 0, 1, 10).p_value == 1.0
    assert stats.two_proportion_test(0, 10, 0, 10).p_value == 1.0


def test_js_distance_and_chi_square() -> None:
    assert stats.js_distance([1, 0], [1, 0]) == 0.0
    assert stats.js_distance([1, 0], [0, 1]) == pytest.approx(1.0)
    assert 0 < stats.js_distance([3, 1], [1, 3]) < 1
    assert stats.js_distance([0, 0], [1, 1]) == 0.0
    stat, p = stats.chi_square_two_sample([50, 50, 0], [10, 90, 0])
    assert stat > 30 and p < 1e-6
    assert stats.chi_square_two_sample([5, 0], [0, 0]) == (0.0, 1.0)
    assert stats.chi_square_two_sample([10], [10]) == (0.0, 1.0)


def test_ece_reliability_table() -> None:
    perfect = stats.expected_calibration_error([0.1, 0.1, 0.9, 0.9], [0, 0, 1, 1])
    assert perfect.ece == pytest.approx(0.1) and perfect.n == 4 and len(perfect.bins) == 2
    assert perfect.bins[0].mean_prob == pytest.approx(0.1) and perfect.bins[0].mean_outcome == 0.0
    assert math.isnan(stats.expected_calibration_error([], []).ece)
    edge = stats.expected_calibration_error([1.0, 0.0], [True, False], n_bins=2)
    assert edge.ece == 0.0
    assert stats.percentile([1, 2, 3, 4], 50) == 2.5 and math.isnan(stats.percentile([], 50))


# ----- time ---------------------------------------------------------------------------------


def test_time_helpers() -> None:
    assert timeutil.parse_duration("30d") == 30 * 86400 and timeutil.parse_duration("1.5h") == 5400
    assert timeutil.parse_duration("15m") == 900 and timeutil.parse_duration("90s") == 90
    with pytest.raises(ValueError):
        timeutil.parse_duration("soon")
    ts = timeutil.from_iso("2026-09-01T00:00:00Z")
    assert ts == timeutil.DEMO_EPOCH and timeutil.iso(ts) == "2026-09-01T00:00:00Z"
    clock = timeutil.SimClock(10.0)
    assert clock.advance(2.5) == 12.5 and clock.now() == 12.5
    clock.set(1.0)
    assert clock.now() == 1.0 and timeutil.minutes_between(0.0, 120.0) == 2.0


# ----- models -------------------------------------------------------------------------------


def test_fake_chat_model_resolution_order() -> None:
    model = FakeChatModel(
        responses=["first"],
        rules=[(r"hello", "hi there"), (r".*", lambda ms: f"echo {ms[-1].content}")],
    )
    msgs = [ChatMessage("user", "hello")]
    assert model.chat(msgs).text == "first"
    assert model.chat(msgs).text == "hi there"
    assert model.chat([ChatMessage("user", "other")]).text == "echo other"
    assert FakeChatModel().chat([]).text == "I don't know." and model.name == "fake"
    assert estimate_tokens("") == 1 and estimate_tokens("a" * 40) == 10
    assert to_provider_messages([ChatMessage("tool", "x")]) == [{"role": "user", "content": "x"}]


def test_openai_compatible_model_retries_usage_and_errors() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, text="slow down")
        assert request.headers["Authorization"] == "Bearer key"
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    model = OpenAICompatibleChatModel(
        "http://llm/v1/",
        "m",
        api_key="key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        max_retries=1,
    )
    resp = model.chat([ChatMessage("user", "q")])
    assert (
        resp.text == "ok"
        and resp.prompt_tokens == 3
        and len(calls) == 2
        and model.name == "openai[m]"
    )

    def bad(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    with pytest.raises(ModelError) as exc:
        OpenAICompatibleChatModel(
            "http://llm/v1", "m", client=httpx.Client(transport=httpx.MockTransport(bad))
        ).chat([])
    assert exc.value.status == 400

    def malformed(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ModelError, match="malformed"):
        OpenAICompatibleChatModel(
            "http://llm/v1", "m", client=httpx.Client(transport=httpx.MockTransport(malformed))
        ).chat([])

    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ModelError) as exc2:
        OpenAICompatibleChatModel(
            "http://llm/v1",
            "m",
            client=httpx.Client(transport=httpx.MockTransport(timeout)),
            sleep=lambda _: None,
            max_retries=1,
        ).chat([])
    assert exc2.value.kind == "timeout"

    def transport(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    m = OpenAICompatibleChatModel(
        "http://llm/v1",
        "m",
        client=httpx.Client(transport=httpx.MockTransport(transport)),
        sleep=lambda _: None,
        max_retries=0,
    )
    with pytest.raises(ModelError, match="transport"):
        m.chat([])
    m.close()


def test_build_model_factory() -> None:
    fake = FakeChatModel(name_="scripted")
    assert build_model("fake", fake=fake) is fake
    assert isinstance(build_model("fake"), FakeChatModel)
    assert build_model("openai", model_name="x", base_url="http://h/v1").name == "openai[x]"
    assert (
        build_model("hf", model_name="Qwen/Qwen2.5-1.5B-Instruct").name
        == "hf[Qwen/Qwen2.5-1.5B-Instruct]"
    )
    with pytest.raises(ValueError):
        build_model("nope")
