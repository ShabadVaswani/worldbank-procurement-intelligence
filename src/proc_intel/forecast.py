"""Planning-time features for the tender-duration model (p07's `ml.proc_tender_duration`), for the agent's
`forecast_timeline` tool (p08 / proc_rag_core).

The model was trained on features known on the tender notice date (p07 section 3). A task team asking for a
brief is earlier still: the notice is not written yet. This module rebuilds the same feature row from what a
planner knows (country, method, category, optionally the project and a planned notice date) and replaces every
notice-level value it cannot know by a documented default, listed in `assumptions`:

    notice type        most common tender-notice type of the method in the training cohort
    advertising days   median deadline-minus-notice days of the method x category (else method) in the cohort
    notice length      median notice text length of the method x category (else method)
    notice language    most common language of the country's tender notices (else English)
    notice date        today, when the package gives no planned date
    project features   from dim_project when a project id is given, else missing (the model handles missing values)
    governance         WGI / GDP of the year before the notice, or the latest year available

Market history (contracts, winners, foreign share, firms per award notice, past median duration) is computed
exactly as in p07: the 36 months before the notice month, from small pre-aggregated frames.

Everything here is pure pandas / Python, so it can be unit-tested on tiny frames.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

CATEGORICAL = ["procurement_method_name", "procurement_category_code", "notice_type", "region", "country_code",
               "major_sector", "env_category", "notice_language"]
NUMERIC = ["advertising_days", "log_notice_chars", "notice_month", "project_age_years", "log_commitment",
           "project_prior_tenders", "wgi_gov_effectiveness", "wgi_control_corruption", "wgi_rule_of_law",
           "wgi_regulatory_quality", "wgi_political_stability", "wgi_voice_accountability", "log_gdp_pc",
           "mkt_contracts_3y", "mkt_winners_3y", "mkt_foreign_share_3y", "mkt_mean_named_firms_3y",
           "hist_median_days_cm", "hist_n_cm"]
FEATURES = CATEGORICAL + NUMERIC            # the same columns, in the same order, as p07's FEATURES
GOVERNANCE = ["wgi_gov_effectiveness", "wgi_control_corruption", "wgi_rule_of_law", "wgi_regulatory_quality",
              "wgi_political_stability", "wgi_voice_accountability", "log_gdp_pc"]
HISTORY_MONTHS = 36
MISSING = "(missing)"                       # p07's placeholder for a missing category (not a training category)


def month_index(d: date) -> int:
    """Months since year 0, the same index p07 uses for its as-of windows."""
    return d.year * 12 + d.month - 1


def _window(frame: pd.DataFrame, keys: Mapping[str, Any], n_month: int, months: int = HISTORY_MONTHS) -> pd.DataFrame:
    """Rows of `frame` with the given key values and h_month in [n_month - months, n_month - 1]."""
    m = (frame["h_month"] >= n_month - months) & (frame["h_month"] <= n_month - 1)
    for k, v in keys.items():
        m &= frame[k] == v
    return frame[m]


def _lower_median(values) -> float:
    """The smallest value with at least half of the values at or below it: what Spark's percentile_approx(x, 0.5)
    returns on small groups (p07 uses it for hist_median_days_cm)."""
    v = np.sort(np.asarray(values, dtype=float))
    return float(v[math.ceil(0.5 * len(v)) - 1]) if len(v) else float("nan")


def market_features(hist_contracts: pd.DataFrame, hist_winners: pd.DataFrame, hist_bidders: pd.DataFrame,
                    past_durations: pd.DataFrame, country: str | None, category: str | None, method: str | None,
                    n_month: int) -> dict:
    """p07's market-history features for one (country, category, method, notice month).

    Frames (columns):
      hist_contracts  country_code, procurement_category_code, h_month, n_contracts
      hist_winners    country_code, procurement_category_code, h_month, supplier_entity_id, rows, foreign_rows
      hist_bidders    country_code, procurement_category_code, h_month, notices, firms
      past_durations  country_code, procurement_method_name, h_month, days_notice_to_signing
    Counts are 0 without history (p07 fills them with 0); ratios and the median stay missing (NaN).
    """
    cc = {"country_code": country, "procurement_category_code": category}
    vol = _window(hist_contracts, cc, n_month)
    win = _window(hist_winners, cc, n_month)
    bid = _window(hist_bidders, cc, n_month)
    dur = _window(past_durations, {"country_code": country, "procurement_method_name": method}, n_month)
    rows = float(win["rows"].sum())
    notices = float(bid["notices"].sum())
    return {"mkt_contracts_3y": float(vol["n_contracts"].sum()),
            "mkt_winners_3y": float(win["supplier_entity_id"].nunique()),
            "mkt_foreign_share_3y": float(win["foreign_rows"].sum()) / rows if rows else float("nan"),
            "mkt_mean_named_firms_3y": float(bid["firms"].sum()) / notices if notices else float("nan"),
            "hist_median_days_cm": _lower_median(dur["days_notice_to_signing"]),
            "hist_n_cm": float(len(dur))}


def notice_defaults(defaults: Mapping, method: str | None, category: str | None) -> tuple[dict | None, str]:
    """Typical notice of a method x category (falling back to the method alone) from the training cohort.

    `defaults` maps (method, category) and (method, None) to {"notice_type", "advertising_days", "notice_chars", "n"}.
    Returns (values, scope label) or (None, "") when the method has no history.
    """
    for key, scope in (((method, category), f"{method} x {category}"), ((method, None), f"{method}, all categories")):
        if key in defaults:
            return dict(defaults[key]), scope
    return None, ""


def _num(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return f


def _as_date(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def planning_features(package: Mapping, *, method: str | None, category: str | None, country: str | None,
                      region: str | None, today: date, defaults: Mapping, language_by_country: Mapping[str, str],
                      governance: Mapping[tuple[str, int], Mapping], market: Mapping, project: Mapping | None = None,
                      prior_tenders: int | None = None) -> tuple[dict, list[str]]:
    """One model input row for a package at planning time, and the assumptions made to fill it.

    `method`, `category`, `country`, `region` are already resolved (codes / names used in the tables).
    Optional package fields override the defaults: planned_notice_date, advertising_days, notice_type,
    notice_language. `governance` maps (country, year) to the GOVERNANCE values; `market` is the output of
    market_features() for the notice month; `project` a dim_project row (dict) or None.
    """
    assumptions: list[str] = []
    notice_date = _as_date(package.get("planned_notice_date"))
    if notice_date is None:
        notice_date = today
        assumptions.append(f"notice date: {today.isoformat()} (today; no planned notice date was given)")
    nd, scope = notice_defaults(defaults, method, category)

    row: dict[str, Any] = {"procurement_method_name": method, "procurement_category_code": category,
                           "country_code": country, "region": region or "Other"}
    if package.get("notice_type"):
        row["notice_type"] = package["notice_type"]
    elif nd:
        row["notice_type"] = nd["notice_type"]
        assumptions.append(f"notice type: {nd['notice_type']} (most common for {scope} tenders)")
    else:
        row["notice_type"] = None
    if package.get("advertising_days") is not None:
        row["advertising_days"] = _num(package["advertising_days"])
    elif nd:
        row["advertising_days"] = _num(nd["advertising_days"])
        assumptions.append(f"advertising period: {nd['advertising_days']:.0f} days (median deadline minus notice date "
                           f"of {scope} tenders)")
    else:
        row["advertising_days"] = float("nan")
        assumptions.append("advertising period: unknown (no history for this method)")
    row["log_notice_chars"] = math.log1p(nd["notice_chars"]) if nd and nd.get("notice_chars") else float("nan")
    if nd and nd.get("notice_chars"):
        assumptions.append(f"notice length: {nd['notice_chars']:.0f} characters (median of {scope} tender notices)")
    if package.get("notice_language"):
        row["notice_language"] = package["notice_language"]
    else:
        row["notice_language"] = language_by_country.get(country or "", "English")
        lang_scope = "the country's tender notices" if country in language_by_country else "default; no notices for the country"
        assumptions.append(f"notice language: {row['notice_language']} (most common in {lang_scope})")
    row["notice_month"] = float(notice_date.month)

    if project:
        row["major_sector"] = project.get("major_sector")
        row["env_category"] = project.get("env_category")
        appr = _as_date(project.get("approval_date"))
        row["project_age_years"] = (notice_date - appr).days / 365.25 if appr else float("nan")
        cm = _num(project.get("commitment_musd"))
        row["log_commitment"] = math.log1p(cm) if cm == cm else float("nan")
        row["project_prior_tenders"] = float(prior_tenders) if prior_tenders is not None else float("nan")
    else:
        row.update(major_sector=None, env_category=None, project_age_years=float("nan"), log_commitment=float("nan"),
                   project_prior_tenders=float("nan"))
        assumptions.append("project: none given, so sector, environmental category, project age, size and earlier "
                           "tenders are unknown (the model treats them as missing)")

    gov_year = notice_date.year - 1
    years = sorted(y for (c, y) in governance if c == country)
    use = gov_year if gov_year in years else (max((y for y in years if y <= gov_year), default=None))
    if use is None:
        row.update({g: float("nan") for g in GOVERNANCE})
        assumptions.append("governance indicators: none for this country (missing)")
    else:
        row.update({g: _num(governance[(country, use)].get(g)) for g in GOVERNANCE})
        if use != gov_year:
            assumptions.append(f"governance indicators: {use}, the latest available (the model uses the year before "
                               f"the notice, {gov_year})")
    row.update({k: _num(market.get(k)) for k in ("mkt_contracts_3y", "mkt_winners_3y", "mkt_foreign_share_3y",
                                                 "mkt_mean_named_firms_3y", "hist_median_days_cm", "hist_n_cm")})
    for k in CATEGORICAL:
        row.setdefault(k, None)
    return {k: row[k] for k in FEATURES}, assumptions


def scoring_problems(row: Mapping, categories: Mapping[str, list]) -> tuple[list[str], list[str]]:
    """(blocking problems, warnings) for scoring a feature row with the model.

    The model cannot give a meaningful forecast without a method and a category it was trained on (they set the
    whole duration scale); any other unseen or missing category is only a warning (treated as missing)."""
    blocking, warnings = [], []
    for col in ("procurement_method_name", "procurement_category_code"):
        v = row.get(col)
        if v in (None, "", MISSING):
            blocking.append(f"{col} unknown")
        elif v not in categories.get(col, []):
            blocking.append(f"{col} '{v}' not seen in the model's training data")
    for col in ("country_code", "notice_type", "notice_language"):
        v = row.get(col)
        if v not in (None, "", MISSING) and v not in categories.get(col, []):
            warnings.append(f"{col} '{v}' not seen in training (treated as missing)")
    return blocking, warnings


def model_frame(row: Mapping) -> pd.DataFrame:
    """The feature row as the registered pyfunc takes it (missing categories become the placeholder string)."""
    X = pd.DataFrame([{k: row.get(k) for k in FEATURES}])
    X[CATEGORICAL] = X[CATEGORICAL].astype(object).where(X[CATEGORICAL].notna(), MISSING)
    X[NUMERIC] = X[NUMERIC].astype(float)
    return X


def forecast_key(row: Mapping, model_version: str) -> str:
    """Stable short hash of the feature row and the model version: the forecast record's id key."""
    clean = {k: (None if isinstance(v, float) and v != v else (round(v, 6) if isinstance(v, float) else v))
             for k, v in sorted(row.items())}
    raw = json.dumps({"v": model_version, "x": clean}, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]
