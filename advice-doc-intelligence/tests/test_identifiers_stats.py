from __future__ import annotations

import math
import random

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from advicedoc.identifiers import (
    abn_is_valid,
    find_abn_like,
    find_tfn_like,
    format_abn,
    generate_abn,
    generate_tfn,
    tfn_is_valid,
)
from advicedoc.stats import (
    Interval,
    bootstrap_mean,
    bootstrap_statistic,
    expected_calibration_error,
    mcnemar_exact,
    paired_bootstrap,
    render_paired,
)

# ----- checksums ----------------------------------------------------------------------------


@settings(max_examples=60, deadline=None)
@given(st.integers(min_value=0, max_value=10**6))
def test_generated_abn_and_tfn_pass_their_checksums(seed: int) -> None:
    rng = random.Random(seed)
    abn = generate_abn(rng)
    tfn = generate_tfn(rng)
    assert abn_is_valid(abn)
    assert len(abn.replace(" ", "")) == 11
    assert tfn_is_valid(tfn)
    assert len(tfn.replace(" ", "")) == 9


@settings(max_examples=60, deadline=None)
@given(st.integers(min_value=0, max_value=10**6), st.integers(min_value=0, max_value=10))
def test_changing_one_abn_digit_breaks_the_checksum(seed: int, position: int) -> None:
    digits = generate_abn(random.Random(seed)).replace(" ", "")
    changed = str((int(digits[position]) + 1) % 10)
    if position == 0 and changed == "0":
        changed = "2"
    mutated = digits[:position] + changed + digits[position + 1 :]
    assert not abn_is_valid(mutated)


def test_known_invalid_identifiers() -> None:
    assert not abn_is_valid("00 000 000 000")
    assert not abn_is_valid("12 345")
    assert not tfn_is_valid("123")
    assert not tfn_is_valid("123 456 780")
    assert format_abn("12345678901") == "12 345 678 901"


def test_find_tfn_like_uses_the_checksum() -> None:
    tfn = generate_tfn(random.Random(4))
    text = f"Member number 1234-5678, TFN {tfn}, account 4471 8823"
    assert find_tfn_like(text) == [tfn]
    assert find_tfn_like("Account number 1234 5678 and phone 0412 345 678") == []
    assert find_abn_like("ABN 12 345 678 901 and 98765432109") == ["12 345 678 901", "98765432109"]


# ----- bootstrap ----------------------------------------------------------------------------


def test_bootstrap_mean_edge_cases() -> None:
    empty = bootstrap_mean([])
    assert math.isnan(empty.point) and empty.n == 0
    single = bootstrap_mean([0.7])
    assert single.point == single.low == single.high == 0.7
    constant = bootstrap_mean([1.0] * 20, n_boot=200)
    assert constant.low == constant.high == 1.0
    assert bootstrap_mean([0.0, 1.0] * 50, n_boot=0).low == 0.5


def test_bootstrap_interval_brackets_the_point_and_is_seeded() -> None:
    values = np.linspace(0, 1, 60)
    a = bootstrap_mean(values, n_boot=500, seed=3)
    b = bootstrap_mean(values, n_boot=500, seed=3)
    assert a == b
    assert a.low <= a.point <= a.high
    assert a.fmt(pct=True).startswith("50.000 %")
    assert Interval(math.nan, math.nan, math.nan, 0).fmt() == "n/a"
    stat = bootstrap_statistic(60, lambda idx: float(values[idx].max()), n_boot=100)
    assert stat.point == 1.0


def test_mcnemar_exact() -> None:
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(10, 0) == pytest.approx(2 / 1024)
    assert mcnemar_exact(0, 10) == mcnemar_exact(10, 0)


def test_paired_bootstrap_verdicts() -> None:
    better = paired_bootstrap([1.0] * 30, [0.0] * 30, n_boot=200)
    assert better.verdict == "better" and better.wins == 30 and better.mcnemar_p < 0.001
    worse = paired_bootstrap([0.0] * 30, [1.0] * 30, n_boot=200)
    assert worse.verdict == "worse"
    same = paired_bootstrap([1.0] * 10, [1.0] * 10, n_boot=50)
    assert same.verdict == "non-inferior" and same.mcnemar_p == 1.0
    rng = np.random.default_rng(0)
    a = rng.random(40)
    b = a + rng.normal(0, 0.5, 40)
    mixed = paired_bootstrap(
        a.tolist(), b.tolist(), n_boot=300, seed=1, non_inferiority_margin=0.01
    )
    assert mixed.verdict in {"inconclusive", "non-inferior", "better", "worse"}
    assert "|" in render_paired("a", "b", mixed)
    empty = paired_bootstrap([], [])
    assert empty.verdict == "no pairs"
    single = paired_bootstrap([1.0], [0.0], n_boot=10)
    assert single.p_improve == 1.0
    with pytest.raises(ValueError, match="equal lengths"):
        paired_bootstrap([1.0], [1.0, 2.0])


# ----- calibration --------------------------------------------------------------------------


def test_ece_matches_a_hand_computed_case() -> None:
    # bin [0.8,0.9): conf 0.85,0.85 acc 0.5 -> gap 0.35 ; bin [0.9,1.0]: conf 0.95 acc 1 -> gap 0.05
    result = expected_calibration_error([0.85, 0.85, 0.95], [True, False, True], n_bins=10)
    expected = (2 / 3) * 0.35 + (1 / 3) * 0.05
    assert result.ece == pytest.approx(expected)
    assert result.n == 3
    populated = [b for b in result.bins if b.count]
    assert [b.count for b in populated] == [2, 1]
    table = result.table_md()
    assert "| [0.8, 0.9) | 2 |" in table
    assert "| [0.0, 0.1) | 0 | - | - | - |" in table
    assert result.to_dict()["bins"][8]["count"] == 2


def test_ece_rejects_length_mismatch_and_handles_empty() -> None:
    with pytest.raises(ValueError, match="same length"):
        expected_calibration_error([0.5], [True, False])
    assert math.isnan(expected_calibration_error([], []).ece)
