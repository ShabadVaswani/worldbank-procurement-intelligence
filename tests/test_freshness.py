import math
from datetime import datetime

import pytest

from proc_intel.freshness import (
    affected_keys,
    bin_counts,
    champion_challenger_gate,
    drift_level,
    freshness_status,
    index_refresh_plan,
    ks_statistic,
    psi,
    psi_categorical,
    psi_numeric,
    quantile_edges,
    retrain_decision,
)


def test_psi_is_zero_for_identical_and_grows_with_shift():
    assert psi([10, 20, 30], [10, 20, 30]) == pytest.approx(0.0)
    assert psi([10, 20, 30], [1, 2, 3]) == pytest.approx(0.0)              # shares, not counts
    small, large = psi([50, 50], [45, 55]), psi([50, 50], [10, 90])
    assert 0 < small < 0.1 < 0.25 < large
    # hand computation for [50, 50] -> [10, 90]: (0.1-0.5) ln(0.2) + (0.9-0.5) ln(1.8)
    assert large == pytest.approx((0.1 - 0.5) * math.log(0.2) + (0.9 - 0.5) * math.log(1.8))


def test_psi_empty_bin_is_finite_and_misaligned_raises():
    assert math.isfinite(psi([10, 0], [5, 5]))
    with pytest.raises(ValueError):
        psi([1, 2], [1, 2, 3])
    assert math.isnan(psi([0, 0], [1, 1]))


def test_bins_at_reference_quantiles():
    ref = list(range(1, 101))
    edges = quantile_edges(ref, n_bins=4)
    assert list(bin_counts(ref, edges)) == [25, 25, 25, 25]
    assert psi_numeric(ref, ref, n_bins=4) == pytest.approx(0.0)
    assert psi_numeric(ref, [v + 50 for v in ref], n_bins=4) > 0.25
    assert list(bin_counts([0, 1000, None, float("nan")], edges)) == [1, 0, 0, 1]   # open-ended, missing dropped


def test_psi_categorical_aligns_categories():
    assert psi_categorical({"GO": 50, "CW": 50}, {"CW": 50, "GO": 50}) == pytest.approx(0.0)
    assert psi_categorical({"GO": 50, "CW": 50}, {"GO": 50, "CW": 30, "CS": 20}) > 0.25     # a new category


def test_ks_statistic():
    assert ks_statistic([1, 2, 3], [1, 2, 3]) == 0.0
    assert ks_statistic([1, 2, 3], [10, 11, 12]) == 1.0
    assert ks_statistic([1, 2, 3, 4], [3, 4, 5, 6]) == pytest.approx(0.5)


def test_drift_level_bands():
    assert [drift_level(v) for v in (0.05, 0.1, 0.24, 0.25, float("nan"))] == [
        "stable", "moderate", "moderate", "significant", "unknown"]


def test_retrain_decision():
    keep = retrain_decision({"amount": 0.02}, target_ks=0.03, days_since_training=10, new_labels=5000)
    assert keep["action"] == "keep" and not keep["reasons"]
    drift = retrain_decision({"amount": 0.30, "region": 0.05}, target_ks=0.03, days_since_training=10, new_labels=5000)
    assert drift["retrain"] and "amount" in drift["reasons"][0]
    few = retrain_decision({"amount": 0.30}, target_ks=None, days_since_training=10, new_labels=40)
    assert few["action"] == "investigate" and not few["retrain"]
    old = retrain_decision({}, target_ks=0.0, days_since_training=120, new_labels=2000, live_mae=130, training_mae=100)
    assert old["retrain"] and len(old["reasons"]) == 2          # error increase + age


CHAMPION = {"window": "2026Q3", "n": 2000, "mae": 60.0,
            "segments": {"GO": {"n": 800, "mae": 50.0}, "CS": {"n": 300, "mae": 90.0}, "tiny": {"n": 10, "mae": 5.0}}}


def test_gate_promotes_a_clearly_better_challenger():
    challenger = {"window": "2026Q3", "n": 2000, "mae": 55.0, "interval_coverage": 0.79, "nominal_coverage": 0.8,
                  "segments": {"GO": {"n": 800, "mae": 47.0}, "CS": {"n": 300, "mae": 92.0}, "tiny": {"n": 10, "mae": 50.0}}}
    gate = champion_challenger_gate(CHAMPION, challenger)
    assert gate["promote"], gate["reason"]          # CS 2% worse is within tolerance; 'tiny' is too small to judge


@pytest.mark.parametrize("change, blocker", [
    ({"mae": 59.5}, "overall MAE improves"),                                   # < 2% better
    ({"window": "2026Q2"}, "same evaluation window"),
    ({"n": 100}, "enough evaluation rows"),
    ({"segments": {"CS": {"n": 300, "mae": 110.0}}}, "no segment regresses"),
    ({"interval_coverage": 0.6, "nominal_coverage": 0.8}, "interval coverage calibrated"),
])
def test_gate_blocks(change, blocker):
    challenger = {"window": "2026Q3", "n": 2000, "mae": 50.0, **change}
    gate = champion_challenger_gate(CHAMPION, challenger)
    assert not gate["promote"] and blocker in gate["reason"]


def test_index_refresh_plan():
    plan = index_refresh_plan({"a": "h1", "b": "h2", "c": "h3"}, {"a": "h1", "b": "h2x", "d": "h4"})
    assert plan["new"] == ["d"] and plan["changed"] == ["b"] and plan["removed"] == ["c"]
    assert plan["embed"] == ["d", "b"] and sorted(plan["delete"]) == ["b", "c"] and plan["unchanged"] == 1


def test_freshness_and_affected_keys():
    now = datetime(2026, 10, 20, 12)
    assert freshness_status(datetime(2026, 10, 20, 1), now, 24)["status"] == "fresh"
    assert freshness_status(datetime(2026, 10, 18, 1), now, 24)["status"] == "late"
    changes = [{"id": 1, "_change_type": "insert"}, {"id": 2, "_change_type": "update_preimage"},
               {"id": 2, "_change_type": "update_postimage"}, {"id": 3, "_change_type": "delete"}]
    assert affected_keys(changes, "id") == {1, 2, 3}
