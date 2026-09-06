"""Offline fixtures: a small seeded corpus, the scripted gold-derived model, an app client.
Nothing downloads; no real model is ever loaded."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from filenote.config import FakeSettings, Settings
from filenote.corpus import Meeting, generate_corpus
from filenote.fake import Corruption, GoldFakeChatModel
from filenote.verify import Verifier
from filenote.web import create_app

FakeFactory = Callable[..., GoldFakeChatModel]


@pytest.fixture
def corpus() -> list[Meeting]:
    """Regenerated per test (a few milliseconds) so no test can mutate another's gold."""
    return generate_corpus(12, 11)


@pytest.fixture
def meeting(corpus: list[Meeting]) -> Meeting:
    return corpus[0]


@pytest.fixture
def gold_map(corpus: list[Meeting]) -> dict[str, Meeting]:
    return {m.id: m for m in corpus}


@pytest.fixture
def verifier() -> Verifier:
    return Verifier()


@pytest.fixture
def settings() -> Settings:
    return Settings(fake=FakeSettings(corpus_n=4, corpus_seed=11))


@pytest.fixture
def make_fake(gold_map: dict[str, Meeting]) -> FakeFactory:
    def factory(
        p: float = 0.0, *, seed: int = 0, kinds: frozenset[str] | None = None
    ) -> GoldFakeChatModel:
        corruption = (
            Corruption(p=p, seed=seed, kinds=kinds)
            if kinds is not None
            else Corruption(p=p, seed=seed)
        )
        return GoldFakeChatModel(gold_map, corruption=corruption)

    return factory


@pytest.fixture
def flagged_model(make_fake: FakeFactory) -> GoldFakeChatModel:
    """Every note gets exactly one invented decision that the model refuses to drop, so one
    unsupported claim is guaranteed to reach the adviser."""
    return make_fake(1.0, kinds=frozenset({"invented_decision", "repair_keep"}))


@pytest.fixture
def client(settings: Settings, flagged_model: GoldFakeChatModel) -> Iterator[TestClient]:
    app = create_app(settings, model=flagged_model)
    with TestClient(app) as c:
        yield c


def read_sse(
    client: TestClient, draft_id: str, *, last_id: int | None = None
) -> list[dict[str, Any]]:
    """Read one SSE stream to its terminal event and parse the frames."""
    headers = {"Last-Event-ID": str(last_id)} if last_id is not None else {}
    frames: list[dict[str, Any]] = []
    with client.stream("GET", f"/api/drafts/{draft_id}/events", headers=headers) as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        buffer = ""
        for chunk in stream.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                parsed: dict[str, Any] = {}
                for line in frame.splitlines():
                    if line.startswith(":"):
                        parsed["comment"] = line
                        continue
                    key, _, value = line.partition(":")
                    parsed[key.strip()] = value.strip()
                if "data" in parsed:
                    parsed["data"] = json.loads(parsed["data"])
                frames.append(parsed)
    return frames


def wait_done(client: TestClient, draft_id: str) -> dict[str, Any]:
    frames = read_sse(client, draft_id)
    assert frames[-1]["event"] in ("done", "error"), frames[-1]
    payload: dict[str, Any] = client.get(f"/api/drafts/{draft_id}").json()
    return payload
