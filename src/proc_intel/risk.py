"""Tender duration benchmarks and slippage risk: pure helpers for p07_tender_risk_model.

The question a planner asks is "how long will this tender take from notice to signed contract,
and is it likely to run late?". p07 answers it at two grains:

  proc_gold.tender_benchmarks   one row per peer group (country x method x category, and coarser
                                fallbacks): empirical P10 / P50 / P90 days and the slow-tender rate
  proc_gold.open_tender_scores  one row per open tender notice: model P10 / P50 / P90 days and the
                                probability of being slow

`benchmark_lookup()` is the interface other components (the agent's tool call) use on the first
table: it walks from the most specific peer group to the coarsest one and returns the first group
with enough contracts, saying which level it used.

Durations are measured up to a horizon (HORIZON_DAYS): a tender still unsigned after two years is
counted as "730 or more". This keeps cohorts comparable: every notice in the modelling window has
been observable for at least that long, so recent notices are not biased towards fast tenders.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd

HORIZON_DAYS = 730
QUANTILES = (0.1, 0.5, 0.9)
ALL = "ALL"
MIN_PEER_N = 30

# finest first; each level lists the columns that must match (the others are ALL)
LEVELS = (
    ("country_method_category", ("country_code", "procurement_method_name", "procurement_category_code")),
    ("region_method_category", ("region", "procurement_method_name", "procurement_category_code")),
    ("method_category", ("procurement_method_name", "procurement_category_code")),
    ("category", ("procurement_category_code",)),
)
KEY_COLUMNS = ("country_code", "region", "procurement_method_name", "procurement_category_code")


def cap_at_horizon(days, horizon: int = HORIZON_DAYS) -> tuple[np.ndarray, np.ndarray]:
    """Durations capped at the horizon, and whether the event (signing) was seen within it."""
    d = np.asarray(days, dtype=float)
    return np.minimum(d, horizon), d <= horizon


def pinball_loss(y, pred, alpha: float) -> float:
    """Mean quantile (pinball) loss: under-prediction costs alpha, over-prediction 1 - alpha."""
    diff = np.asarray(y, dtype=float) - np.asarray(pred, dtype=float)
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def interval_coverage(y, lo, hi) -> float:
    """Share of outcomes inside [lo, hi]."""
    y = np.asarray(y, dtype=float)
    return float(np.mean((y >= np.asarray(lo, dtype=float)) & (y <= np.asarray(hi, dtype=float))))


def sort_quantiles(*preds) -> tuple[np.ndarray, ...]:
    """Remove quantile crossing: per row, sort the predictions so P10 <= P50 <= P90."""
    stacked = np.sort(np.column_stack([np.asarray(p, dtype=float) for p in preds]), axis=1)
    return tuple(stacked[:, i] for i in range(stacked.shape[1]))


def slow_label(days, threshold) -> np.ndarray:
    """1 when the tender took longer than its peer group's threshold (the P75 of the training years)."""
    return (np.asarray(days, dtype=float) > np.asarray(threshold, dtype=float)).astype(int)


def benchmark_key(level: str, country: str = ALL, region: str = ALL, method: str = ALL, category: str = ALL) -> str:
    """Primary key of a tender_benchmarks row: 'level|country|region|method|category' (ALL where not used;
    country rows keep their region for information)."""
    return "|".join([level, country, region, method, category])


def benchmark_lookup(rows, country: str | None, method: str | None, category: str | None,
                     region: str | None = None, min_n: int = MIN_PEER_N) -> dict:
    """Benchmark for one tender from tender_benchmarks rows (a DataFrame or an iterable of dicts).

    Tries country x method x category, then region x method x category, then method x category,
    then category alone, and returns the first group with at least `min_n` contracts:
        {"found": True, "benchmark_level": ..., "benchmark_key": ..., "n_contracts": ...,
         "p10_days": ..., "p50_days": ..., "p90_days": ..., "slow_threshold_days": ..., "slow_rate": ...,
         "skipped": [levels that matched but had too few contracts]}
    When `region` is not given it is taken from the country's own rows. Returns {"found": False, ...}
    when not even the category is known.
    """
    records: Iterable[Mapping] = rows.to_dict("records") if isinstance(rows, pd.DataFrame) else rows
    level_cols = dict(LEVELS)
    # a row is found by its level and the columns that level matches on (country rows also carry their region)
    index = {(r["benchmark_level"], tuple(r[c] for c in level_cols[r["benchmark_level"]])): r for r in records}
    if region is None and country:
        region = next((r["region"] for (level, _), r in index.items()
                       if level == LEVELS[0][0] and r["country_code"] == country), None)
    wanted = {"country_code": country, "region": region, "procurement_method_name": method,
              "procurement_category_code": category}
    skipped = []
    for level, cols in LEVELS:
        if any(wanted[c] in (None, "") for c in cols):
            continue
        row = index.get((level, tuple(wanted[c] for c in cols)))
        if row is None:
            continue
        if row["n_contracts"] < min_n:
            skipped.append(level)
            continue
        out = {k: row.get(k) for k in ("benchmark_key", "benchmark_level", "n_contracts", "p10_days", "p50_days",
                                        "p90_days", "slow_threshold_days", "slow_rate")}
        return {"found": True, **out, "skipped": skipped}
    return {"found": False, "skipped": skipped}


def peer_aggregate(train: pd.DataFrame, test: pd.DataFrame, target: str, stats: dict,
                   min_n: int = MIN_PEER_N) -> pd.DataFrame:
    """For each test row, statistics of `target` over its finest training peer group with >= min_n rows.

    `stats` maps output column -> function of a Series (e.g. {"q0.5": lambda s: s.quantile(0.5)}).
    Uses the same levels as benchmark_lookup (country, region, method and category columns must exist).
    Returns one row per test row (same index) with the stats, the group size `n` and the `level` used
    (None when not even the category was seen in training).
    """
    out = pd.DataFrame(index=test.index, columns=[*stats, "n"], dtype=float)
    out["level"] = None
    for level, cols in LEVELS:
        todo = out["level"].isna()
        if not todo.any():
            break
        cols = list(cols)
        grouped = train.groupby(cols)[target]
        table = pd.concat([grouped.size().rename("n")] + [grouped.agg(fn).rename(name) for name, fn in stats.items()],
                          axis=1)
        table = table[table["n"] >= min_n].reset_index()
        hit = test.loc[todo, cols].rename_axis("_row").reset_index().merge(table, on=cols).set_index("_row")
        out.loc[hit.index, [*stats, "n"]] = hit[[*stats, "n"]].to_numpy(dtype=float)
        out.loc[hit.index, "level"] = level
    return out


def peer_baseline(train: pd.DataFrame, test: pd.DataFrame, target: str,
                  quantiles=QUANTILES, min_n: int = MIN_PEER_N) -> pd.DataFrame:
    """Naive benchmark forecast: the training quantiles (columns q0.1, q0.5, ...) of each test row's peer group."""
    return peer_aggregate(train, test, target, {f"q{q}": (lambda s, q=q: s.quantile(q)) for q in quantiles}, min_n)


def rolling_origin_folds(dates, origins, val_months: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window folds: train on dates before each origin, validate on the next `val_months`."""
    d = pd.to_datetime(pd.Series(dates)).to_numpy()
    folds = []
    for origin in origins:
        start = np.datetime64(pd.Timestamp(origin))
        end = np.datetime64(pd.Timestamp(origin) + pd.DateOffset(months=val_months))
        folds.append((d < start, (d >= start) & (d < end)))
    return folds


def calibration_table(y, p, n_bins: int = 10) -> pd.DataFrame:
    """Observed rate vs mean predicted probability per equal-count bin of the predictions."""
    frame = pd.DataFrame({"y": np.asarray(y, dtype=float), "p": np.asarray(p, dtype=float)})
    frame["bin"] = pd.qcut(frame["p"].rank(method="first"), n_bins, labels=False)
    return (frame.groupby("bin").agg(n=("y", "size"), mean_predicted=("p", "mean"), observed_rate=("y", "mean"))
            .reset_index())


def conformal_shift(scores, miss_rate: float) -> float:
    """Split-conformal correction for one side of a quantile interval (conformalised quantile regression).

    `scores` are calibration-set violations on that side, e.g. (predicted P10 - y) for the lower bound: positive
    when the outcome fell below the bound. Returns the shift to subtract from (lower) or add to (upper) the bound
    so that, for exchangeable data, at most `miss_rate` of new outcomes fall outside that side. Uses the
    finite-sample level ceil((n + 1)(1 - miss_rate)) / n; negative shifts narrow an interval that is too wide.
    """
    s = np.sort(np.asarray(scores, dtype=float))
    n = len(s)
    k = int(np.ceil((n + 1) * (1 - miss_rate)))
    return float(s[min(k, n) - 1])
