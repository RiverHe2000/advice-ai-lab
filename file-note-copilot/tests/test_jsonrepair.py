from __future__ import annotations

import pytest

from filenote.jsonrepair import outermost_object, repair_json


@pytest.mark.parametrize(
    ("text", "expected", "repaired"),
    [
        ('{"a": 1}', {"a": 1}, False),
        ('Sure!\n```json\n{"a": [1, 2]}\n```\nDone.', {"a": [1, 2]}, True),
        ('prefix {"a": {"b": "}"}} suffix', {"a": {"b": "}"}}, True),
        ('{"a": 1, "b": [1, 2,], }', {"a": 1, "b": [1, 2]}, True),
        ('{"a": "esc\\"aped"}', {"a": 'esc"aped'}, False),
    ],
)
def test_repairs(text: str, expected: dict[str, object], repaired: bool) -> None:
    assert repair_json(text) == (expected, repaired)


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2, 3]", '{"a": 1', '{"truncated": "str'])
def test_failures_are_missing_not_defaulted(text: str) -> None:
    assert repair_json(text) == (None, True)


def test_outermost_object() -> None:
    assert outermost_object("x") is None
    assert outermost_object('{"a": 1} {"b": 2}') == '{"a": 1}'
    assert outermost_object('{"a": 1') is None
