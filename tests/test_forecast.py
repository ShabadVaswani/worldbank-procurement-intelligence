import math
from datetime import date

import pandas as pd

from proc_intel.forecast import (
    CATEGORICAL,
    FEATURES,
    MISSING,
    NUMERIC,
    forecast_key,
    market_features,
    model_frame,
    month_index,
    notice_defaults,
    planning_features,
    scoring_problems,
)

N = month_index(date(2026, 10, 21))          # notice month

HIST_CONTRACTS = pd.DataFrame({"country_code": ["KE", "KE", "KE", "TZ"], "procurement_category_code": ["CW", "CW", "CW", "CW"],
                               "h_month": [N - 1, N - 36, N, N - 2], "n_contracts": [3, 2, 50, 7]})
HIST_WINNERS = pd.DataFrame({"country_code": ["KE"] * 4, "procurement_category_code": ["CW"] * 4,
                             "h_month": [N - 1, N - 2, N - 2, N - 40], "supplier_entity_id": ["SE-1", "SE-1", "SE-2", "SE-3"],
                             "rows": [1, 2, 1, 1], "foreign_rows": [1, 0, 1, 1]})
HIST_BIDDERS = pd.DataFrame({"country_code": ["KE", "KE"], "procurement_category_code": ["CW", "CW"],
                             "h_month": [N - 3, N - 4], "notices": [2, 2], "firms": [6, 2]})
PAST = pd.DataFrame({"country_code": ["KE"] * 4, "procurement_method_name": ["Request for Bids"] * 4,
                     "h_month": [N - 1, N - 2, N - 3, N + 1], "days_notice_to_signing": [100, 300, 200, 5]})
DEFAULTS = {("Request for Bids", "CW"): {"notice_type": "Invitation for Bids", "advertising_days": 42.0, "notice_chars": 6000.0, "n": 900},
            ("Request for Bids", None): {"notice_type": "Invitation for Bids", "advertising_days": 35.0, "notice_chars": 5000.0, "n": 4000}}
WGI = ("wgi_gov_effectiveness", "wgi_control_corruption", "wgi_rule_of_law", "wgi_regulatory_quality",
       "wgi_political_stability", "wgi_voice_accountability")
GOV = {("KE", 2024): dict.fromkeys(WGI, 0.1) | {"log_gdp_pc": 7.5}}


def _market():
    return market_features(HIST_CONTRACTS, HIST_WINNERS, HIST_BIDDERS, PAST, "KE", "CW", "Request for Bids", N)


def test_market_features_use_the_36_months_before_the_notice_month_only():
    m = _market()
    assert m["mkt_contracts_3y"] == 5.0                      # N-1 and N-36; not the notice month itself, not TZ
    assert m["mkt_winners_3y"] == 2.0                        # SE-3 is 40 months back
    assert m["mkt_foreign_share_3y"] == 2 / 4
    assert m["mkt_mean_named_firms_3y"] == 8 / 4
    assert m["hist_median_days_cm"] == 200.0 and m["hist_n_cm"] == 3.0     # lower median of 100, 200, 300


def test_market_features_without_history_are_zero_counts_and_missing_ratios():
    m = market_features(HIST_CONTRACTS, HIST_WINNERS, HIST_BIDDERS, PAST, "MV", "GO", "Request for Bids", N)
    assert m["mkt_contracts_3y"] == 0 and m["mkt_winners_3y"] == 0 and m["hist_n_cm"] == 0
    assert math.isnan(m["mkt_foreign_share_3y"]) and math.isnan(m["hist_median_days_cm"])


def test_notice_defaults_fall_back_to_the_method():
    assert notice_defaults(DEFAULTS, "Request for Bids", "CW")[0]["advertising_days"] == 42.0
    vals, scope = notice_defaults(DEFAULTS, "Request for Bids", "NC")
    assert vals["advertising_days"] == 35.0 and "all categories" in scope
    assert notice_defaults(DEFAULTS, "Direct Selection", "CW") == (None, "")


def _features(package=None, project=None, prior=None):
    return planning_features(package or {}, method="Request for Bids", category="CW", country="KE",
                             region="Eastern and Southern Africa", today=date(2026, 10, 21), defaults=DEFAULTS,
                             language_by_country={"KE": "English"}, governance=GOV, market=_market(),
                             project=project, prior_tenders=prior)


def test_planning_features_fill_every_model_column_and_list_each_default():
    row, assumptions = _features()
    assert list(row) == FEATURES and len(FEATURES) == 27
    assert row["notice_type"] == "Invitation for Bids" and row["advertising_days"] == 42.0
    assert row["log_notice_chars"] == math.log1p(6000.0) and row["notice_month"] == 10.0
    assert row["major_sector"] is None and math.isnan(row["project_age_years"])
    assert row["wgi_rule_of_law"] == 0.1                     # 2025 missing -> latest year 2024
    text = " | ".join(assumptions)
    for phrase in ("notice date: 2026-10-21", "notice type", "advertising period: 42 days", "notice length",
                   "notice language", "project: none given", "governance indicators: 2024"):
        assert phrase in text, phrase


def test_planning_features_take_package_values_and_project_facts_over_defaults():
    project = {"major_sector": "Transportation", "env_category": "B", "approval_date": "2024-10-21", "commitment_musd": 150.0}
    row, assumptions = _features({"planned_notice_date": "2025-03-01", "advertising_days": 60}, project=project, prior=4)
    assert row["advertising_days"] == 60.0 and row["notice_month"] == 3.0 and row["major_sector"] == "Transportation"
    assert abs(row["project_age_years"] - (date(2025, 3, 1) - date(2024, 10, 21)).days / 365.25) < 1e-9
    assert row["log_commitment"] == math.log1p(150.0) and row["project_prior_tenders"] == 4.0
    text = " | ".join(assumptions)
    assert "advertising period" not in text and "notice date" not in text and "project: none" not in text


def test_scoring_problems_block_unknown_method_and_warn_on_unseen_country():
    cats = {"procurement_method_name": ["Request for Bids"], "procurement_category_code": ["CW"], "country_code": ["TZ"],
            "notice_type": ["Invitation for Bids"], "notice_language": ["English"]}
    row, _ = _features()
    blocking, warnings = scoring_problems(row, cats)
    assert blocking == [] and any("country_code 'KE'" in w for w in warnings)
    blocking, _ = scoring_problems({**row, "procurement_method_name": "Direct Selection"}, cats)
    assert blocking and "Direct Selection" in blocking[0]
    blocking, _ = scoring_problems({**row, "procurement_category_code": None}, cats)
    assert blocking == ["procurement_category_code unknown"]


def test_model_frame_and_forecast_key():
    row, _ = _features()
    X = model_frame(row)
    assert list(X.columns) == CATEGORICAL + NUMERIC and X.loc[0, "major_sector"] == MISSING
    assert X[NUMERIC].dtypes.eq(float).all()
    k = forecast_key(row, "2")
    assert k == forecast_key(dict(row), "2") and k != forecast_key(row, "3") and len(k) == 12
    assert k != forecast_key({**row, "advertising_days": 60.0}, "2")
