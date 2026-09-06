from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from filenote.numbers import (
    DateRef,
    find_dates,
    find_numbers,
    format_amount,
    number_set,
    number_to_words,
    strip_dates,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("eighty-five thousand dollars", [85000.0]),
        ("eighty five thousand", [85000.0]),
        ("$85k", [85000.0]),
        ("85,000", [85000.0]),
        ("85 thousand", [85000.0]),
        ("85,000 dollars", [85000.0]),
        ("AUD 30,000 cap", [30000.0]),
        ("one point two million", [1200000.0]),
        ("$1.2m", [1200000.0]),
        ("$2.5 million", [2500000.0]),
        ("twelve hundred", [1200.0]),
        ("two hundred and fifty thousand", [250000.0]),
        ("twenty-seven thousand five hundred", [27500.0]),
        ("a hundred thousand", [100000.0]),
        ("nine hundred and ninety", [990.0]),
        ("9.5 percent", [9.5]),
        ("nine point five percent", [9.5]),
        ("15%", [15.0]),
        ("fifteen per cent", [15.0]),
        ("retire at sixty-five in 2035", [65.0, 2035.0]),
        ("return of 7.", [7.0]),
        ("segment s034 about $1,200,000", [1200000.0]),
        ("CLIENT_2 expects an inheritance of about $75,000", [75000.0]),
        ("ADVISER_1 and PARAPLANNER_12 spoke", []),
        ("I'm 5kg heavier", []),
        ("in 5 months", [5.0]),
        ("no figures here", []),
        ("I have two kids and a dog", [2.0]),
        ("three thousand two hundred and ten", [3210.0]),
        ("2 billion", [2e9]),
    ],
)
def test_number_normalisation_table(text: str, expected: list[float]) -> None:
    assert find_numbers(text) == expected


def test_number_set_and_zero() -> None:
    assert number_set("zero and 0") == {0.0}
    assert number_set("$85k or 85,000 or eighty-five thousand") == {85000.0}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("due by 20 September 2026", ["2026-09-20"]),
        ("the 20th of September", ["????-09-20"]),
        ("20/09/2026 or 2026-09-20", ["2026-09-20", "2026-09-20"]),
        ("September 20, 2026", ["2026-09-20"]),
        ("Sept 3 2027", ["2027-09-03"]),
        ("June 2027", ["2027-06"]),
        ("30/13/2026 is not a date", []),
        ("32 March 2026 is only a month-year mention", ["2026-03"]),
    ],
)
def test_dates(text: str, expected: list[str]) -> None:
    assert [str(d) for d in find_dates(text)[0]] == expected


def test_date_agreement_rules() -> None:
    full = DateRef(9, 20, 2026)
    assert full.agrees(DateRef(9, 20, None))
    assert full.agrees(DateRef(9, None, 2026))
    assert not full.agrees(DateRef(9, 21, 2026))
    assert not full.agrees(DateRef(10, 20, 2026))
    assert not full.agrees(DateRef(9, 20, 2027))
    assert sorted([DateRef(10, 1), DateRef(9, 20, 2026)])[0].month == 9


def test_strip_dates_keeps_length_and_removes_numbers() -> None:
    text = "pay $500 by 20 September 2026 please"
    stripped = strip_dates(text)
    assert len(stripped) == len(text)
    assert find_numbers(text) == [500.0]
    assert find_numbers(text, skip_dates=False) == [500.0, 20.0, 2026.0]
    assert strip_dates("nothing") == "nothing"


@pytest.mark.parametrize(
    "value",
    [
        0,
        7,
        19,
        20,
        21,
        85,
        100,
        101,
        990,
        1200,
        27500,
        85000,
        250000,
        1000000,
        1200000,
        2500000,
        3_000_000_000,
    ],
)
def test_number_to_words_round_trip(value: int) -> None:
    assert find_numbers(number_to_words(value)) == [float(value)]


def test_number_to_words_decimals_and_negative() -> None:
    assert number_to_words(9.5) == "nine point five"
    assert number_to_words(2.25) == "two point two five"
    assert number_to_words(-3) == "minus three"
    assert find_numbers("nine point five percent") == [9.5]


@settings(max_examples=60, deadline=None)
@given(st.integers(min_value=0, max_value=999_999_999))
def test_words_round_trip_property(value: int) -> None:
    assert find_numbers(number_to_words(value)) == [float(value)]


@settings(max_examples=40, deadline=None)
@given(st.integers(min_value=1, max_value=5_000_000))
def test_amount_forms_agree(value: int) -> None:
    forms = [format_amount(value), f"{value:,} dollars", number_to_words(value) + " dollars"]
    if value % 1000 == 0:
        forms.append(f"${value // 1000}k")
    assert {find_numbers(f)[0] for f in forms} == {float(value)}


def test_format_amount() -> None:
    assert format_amount(85000) == "$85,000"
    assert format_amount(1234.5) == "$1,234.50"
