import numpy as np
import pandas as pd
import pytest

from proc_intel.risk import (
    ALL,
    benchmark_key,
    benchmark_lookup,
    calibration_table,
    cap_at_horizon,
    conformal_shift,
    interval_coverage,
    peer_aggregate,
    peer_baseline,
    pinball_loss,
    rolling_origin_folds,
    slow_label,
    sort_quantiles,
)


def _row(level, country=ALL, region=ALL, method=ALL, category=ALL, n=100, p50=100):
    return {"benchmark_key": benchmark_key(level, country, region, method, category), "benchmark_level": level,
            "country_code": country, "region": region, "procurement_method_name": method,
            "procurement_category_code": category, "n_contracts": n, "p10_days": p50 // 2, "p50_days": p50,
            "p90_days": p50 * 2, "slow_threshold_days": int(p50 * 1.5), "slow_rate": 0.25}


ROWS = [
    _row("country_method_category", "KE", "Eastern and Southern Africa", "Request for Bids", "CW", n=45, p50=120),
    _row("country_method_category", "TZ", "Eastern and Southern Africa", "Request for Bids", "CW", n=12, p50=300),
    _row("region_method_category", region="Eastern and Southern Africa", method="Request for Bids", category="CW",
         n=400, p50=140),
    _row("method_category", method="Request for Bids", category="CW", n=7000, p50=133),
    _row("category", category="CW", n=7500, p50=134),
]


def test_benchmark_lookup_uses_the_finest_group_with_enough_contracts():
    hit = benchmark_lookup(ROWS, "KE", "Request for Bids", "CW")
    assert hit["found"] and hit["benchmark_level"] == "country_method_category" and hit["p50_days"] == 120
    assert hit["skipped"] == []


def test_benchmark_lookup_falls_back_to_region_when_the_country_group_is_small():
    hit = benchmark_lookup(ROWS, "TZ", "Request for Bids", "CW")    # 12 contracts < 30
    assert hit["benchmark_level"] == "region_method_category" and hit["p50_days"] == 140
    assert hit["skipped"] == ["country_method_category"]


def test_benchmark_lookup_unknown_country_and_method_fall_back_further():
    assert benchmark_lookup(ROWS, "XX", "Request for Bids", "CW")["benchmark_level"] == "method_category"
    assert benchmark_lookup(ROWS, None, None, "CW")["benchmark_level"] == "category"
    assert benchmark_lookup(ROWS, "KE", "Request for Bids", "GO") == {"found": False, "skipped": []}


def test_benchmark_lookup_accepts_a_dataframe_and_an_explicit_region():
    hit = benchmark_lookup(pd.DataFrame(ROWS), "XX", "Request for Bids", "CW", region="Eastern and Southern Africa")
    assert hit["benchmark_level"] == "region_method_category"


def test_cap_at_horizon_marks_unseen_events():
    capped, event = cap_at_horizon([100, 730, 900], horizon=730)
    assert capped.tolist() == [100, 730, 730] and event.tolist() == [True, True, False]


def test_pinball_loss_is_asymmetric():
    # under-predicting by 10 at the 90th percentile costs 9; over-predicting by 10 costs 1
    assert pinball_loss([110], [100], 0.9) == pytest.approx(9.0)
    assert pinball_loss([90], [100], 0.9) == pytest.approx(1.0)
    assert pinball_loss([90, 110], [100, 100], 0.5) == pytest.approx(5.0)


def test_interval_coverage_counts_bounds_as_inside():
    assert interval_coverage([1, 5, 10, 11], [1, 1, 1, 1], [10, 10, 10, 10]) == 0.75


def test_sort_quantiles_removes_crossing():
    p10, p50, p90 = sort_quantiles([50, 10], [40, 20], [100, 30])
    assert p10.tolist() == [40, 10] and p50.tolist() == [50, 20] and p90.tolist() == [100, 30]


def test_slow_label_is_strictly_above_threshold():
    assert slow_label([100, 200, 201], [200, 200, 200]).tolist() == [0, 0, 1]


def test_peer_baseline_uses_training_quantiles_with_fallback():
    train = pd.DataFrame({"country_code": ["KE"] * 30 + ["TZ"] * 5, "region": ["ESA"] * 35,
                          "procurement_method_name": ["RFB"] * 35, "procurement_category_code": ["CW"] * 35,
                          "days": list(range(1, 31)) + [1000] * 5})
    test = pd.DataFrame({"country_code": ["KE", "TZ", "UG"], "region": ["ESA", "ESA", "WCA"],
                         "procurement_method_name": ["RFB"] * 3, "procurement_category_code": ["CW"] * 3})
    out = peer_baseline(train, test, "days", quantiles=(0.5,), min_n=30)
    assert out["level"].tolist() == ["country_method_category", "region_method_category", "method_category"]
    assert out.loc[0, "q0.5"] == pytest.approx(15.5)                       # KE alone
    assert out.loc[1, "q0.5"] == pytest.approx(np.median(train["days"]))    # TZ has 5 < 30: region


def test_peer_aggregate_returns_group_rates_and_sizes():
    train = pd.DataFrame({"country_code": ["KE"] * 4, "region": ["ESA"] * 4, "procurement_method_name": ["RFB"] * 4,
                          "procurement_category_code": ["CW"] * 4, "slow": [1, 0, 0, 0]})
    test = pd.DataFrame({"country_code": ["KE", "KE"], "region": ["ESA", "ESA"], "procurement_method_name": ["RFB"] * 2,
                         "procurement_category_code": ["CW", "GO"]}, index=[10, 11])
    out = peer_aggregate(train, test, "slow", {"rate": "mean"}, min_n=2)
    assert out.loc[10, "rate"] == 0.25 and out.loc[10, "n"] == 4 and out.loc[10, "level"] == "country_method_category"
    assert out.loc[11, "level"] is None and np.isnan(out.loc[11, "rate"])


def test_rolling_origin_folds_are_expanding_and_disjoint():
    dates = pd.date_range("2020-01-01", periods=36, freq="MS")
    folds = rolling_origin_folds(dates, ["2021-01-01", "2022-01-01"], val_months=6)
    (tr1, va1), (tr2, va2) = folds
    assert tr1.sum() == 12 and va1.sum() == 6 and tr2.sum() == 24 and va2.sum() == 6
    assert not (tr2 & va2).any() and tr1.sum() < tr2.sum()


def test_calibration_table_bins_by_prediction():
    table = calibration_table([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9], n_bins=2)
    assert table["observed_rate"].tolist() == [0.0, 1.0] and table["n"].tolist() == [2, 2]


def test_conformal_shift_uses_the_finite_sample_rank():
    scores = np.arange(1, 20)                     # 19 calibration scores 1..19
    assert conformal_shift(scores, 0.1) == 18     # ceil(20 * 0.9) = 18th smallest
    assert conformal_shift([-5, -4, -3], 0.5) == -4   # all outcomes inside: the bound may move inwards
    assert conformal_shift([1, 2], 0.01) == 2     # rank capped at n
