"""Keeping models and indices current: drift measures, retrain triggers, a champion/challenger gate,
an index refresh plan and table freshness checks.

All functions are pure (numbers and dicts in, numbers and dicts out) so that the policy can be unit-tested
and read on its own; the notebook p10_continuous_learning feeds them from Delta tables.

Conventions used:
- Population stability index (PSI) = sum over bins of (actual% - expected%) * ln(actual% / expected%).
  Below 0.10 is "stable", 0.10-0.25 "moderate", 0.25 or more "significant" (the usual credit-risk bands).
- Two-sample Kolmogorov-Smirnov statistic D = the largest gap between the two empirical CDFs; used for
  the target (duration) distribution, where the shape matters more than the binning.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

import numpy as np

PSI_MODERATE, PSI_SIGNIFICANT = 0.10, 0.25


# ---------------------------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------------------------

def quantile_edges(reference: Sequence[float], n_bins: int = 10) -> np.ndarray:
    """Inner bin edges at the reference sample's quantiles (duplicates removed, so ties make fewer bins)."""
    values = np.asarray([v for v in reference if v is not None and not math.isnan(v)], dtype=float)
    if values.size == 0:
        return np.array([])
    return np.unique(np.quantile(values, np.linspace(0, 1, n_bins + 1)[1:-1]))


def bin_counts(values: Sequence[float], edges: np.ndarray) -> np.ndarray:
    """Counts per bin; bin i holds edges[i-1] < v <= edges[i] (first and last bins are open-ended)."""
    values = np.asarray([v for v in values if v is not None and not math.isnan(v)], dtype=float)
    return np.bincount(np.searchsorted(edges, values, side="left"), minlength=len(edges) + 1)


def psi(expected_counts: Sequence[float], actual_counts: Sequence[float], eps: float = 1e-4) -> float:
    """PSI between two aligned count vectors. Empty bins are floored at `eps` share so the log stays finite."""
    e, a = np.asarray(expected_counts, dtype=float), np.asarray(actual_counts, dtype=float)
    if e.shape != a.shape:
        raise ValueError("count vectors must be aligned")
    if e.sum() == 0 or a.sum() == 0:
        return float("nan")
    pe, pa = np.maximum(e / e.sum(), eps), np.maximum(a / a.sum(), eps)
    return float(np.sum((pa - pe) * np.log(pa / pe)))


def psi_numeric(reference: Sequence[float], current: Sequence[float], n_bins: int = 10) -> float:
    """PSI of a numeric feature, binned at the reference window's deciles."""
    edges = quantile_edges(reference, n_bins)
    return psi(bin_counts(reference, edges), bin_counts(current, edges))


def psi_categorical(reference: Mapping[str, int], current: Mapping[str, int]) -> float:
    """PSI of a categorical feature from category -> count maps (a category missing on one side counts 0)."""
    keys = sorted(set(reference) | set(current), key=str)
    return psi([reference.get(k, 0) for k in keys], [current.get(k, 0) for k in keys])


def ks_statistic(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sample Kolmogorov-Smirnov D: the largest vertical gap between the two empirical CDFs."""
    a, b = np.sort(np.asarray(a, dtype=float)), np.sort(np.asarray(b, dtype=float))
    if a.size == 0 or b.size == 0:
        return float("nan")
    grid = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, grid, side="right") / a.size
    cdf_b = np.searchsorted(b, grid, side="right") / b.size
    return float(np.max(np.abs(cdf_a - cdf_b)))


def drift_level(value: float) -> str:
    if value is None or math.isnan(value):
        return "unknown"
    return "significant" if value >= PSI_SIGNIFICANT else "moderate" if value >= PSI_MODERATE else "stable"


# ---------------------------------------------------------------------------------------------
# Retraining and promotion
# ---------------------------------------------------------------------------------------------

RETRAIN_POLICY = {
    "feature_psi_significant": PSI_SIGNIFICANT,   # any key feature at or above this -> retrain
    "target_ks": 0.10,                            # duration distribution moved this much -> retrain
    "error_increase": 0.15,                       # live MAE 15% above the MAE at training -> retrain
    "max_age_days": 90,                           # scheduled refresh ...
    "min_new_labels": 1000,                       # ... only when enough new outcomes exist to learn from
}


def retrain_decision(feature_psi: Mapping[str, float], target_ks: float | None, days_since_training: int,
                     new_labels: int, live_mae: float | None = None, training_mae: float | None = None,
                     policy: Mapping[str, float] = RETRAIN_POLICY) -> dict:
    """Whether to train a challenger, with the reasons. Drift alone never retrains on too few new labels:
    a model retrained on a handful of new outcomes is noise, so that case is reported as 'investigate'."""
    reasons = []
    drifted = sorted(f for f, v in feature_psi.items() if v is not None and not math.isnan(v)
                     and v >= policy["feature_psi_significant"])
    if drifted:
        reasons.append(f"feature drift (PSI >= {policy['feature_psi_significant']}): {', '.join(drifted)}")
    if target_ks is not None and not math.isnan(target_ks) and target_ks >= policy["target_ks"]:
        reasons.append(f"target distribution shift (KS {target_ks:.3f} >= {policy['target_ks']})")
    if live_mae is not None and training_mae and live_mae > training_mae * (1 + policy["error_increase"]):
        reasons.append(f"live MAE {live_mae:.1f} is more than {policy['error_increase']:.0%} above training MAE {training_mae:.1f}")
    if days_since_training >= policy["max_age_days"]:
        reasons.append(f"model is {days_since_training} days old (scheduled refresh at {policy['max_age_days']})")
    enough = new_labels >= policy["min_new_labels"]
    action = "retrain" if reasons and enough else "investigate" if reasons else "keep"
    if reasons and not enough:
        reasons.append(f"only {new_labels} new labelled outcomes (< {policy['min_new_labels']}): review before retraining")
    return {"action": action, "retrain": action == "retrain", "reasons": reasons}


GATE_POLICY = {
    "min_rel_improvement": 0.02,     # challenger MAE must be at least 2% lower on the same window
    "max_segment_regression": 0.10,  # and no segment more than 10% worse
    "min_eval_rows": 500,            # on enough rows to mean something
    "min_segment_rows": 50,          # segments smaller than this are not judged
    "coverage_tolerance": 0.05,      # prediction-interval coverage within 5 points of nominal (if reported)
}


def champion_challenger_gate(champion: Mapping, challenger: Mapping, policy: Mapping[str, float] = GATE_POLICY) -> dict:
    """Promote the challenger only if it beats the current @champion on the latest evaluation window.

    Each side: {"window": id of the evaluation window, "n": rows, "mae": overall MAE,
                "segments": {name: {"n": rows, "mae": MAE}} (optional),
                "interval_coverage": share of actuals inside the nominal interval (optional),
                "nominal_coverage": e.g. 0.8 (optional)}.
    Returns {"promote": bool, "checks": [(name, passed, detail)], "reason": str}.
    """
    checks = []
    checks.append(("same evaluation window", champion.get("window") == challenger.get("window"),
                   f"{champion.get('window')} vs {challenger.get('window')}"))
    checks.append(("enough evaluation rows", challenger.get("n", 0) >= policy["min_eval_rows"],
                   f"n={challenger.get('n', 0)} (min {policy['min_eval_rows']})"))
    target = champion["mae"] * (1 - policy["min_rel_improvement"])
    checks.append(("overall MAE improves", challenger["mae"] <= target,
                   f"{challenger['mae']:.2f} vs champion {champion['mae']:.2f} (needs <= {target:.2f})"))
    worse = []
    for seg, ch in (challenger.get("segments") or {}).items():
        base = (champion.get("segments") or {}).get(seg)
        if not base or min(ch.get("n", 0), base.get("n", 0)) < policy["min_segment_rows"]:
            continue
        if ch["mae"] > base["mae"] * (1 + policy["max_segment_regression"]):
            worse.append(f"{seg} {base['mae']:.1f} -> {ch['mae']:.1f}")
    checks.append(("no segment regresses", not worse, "; ".join(worse) or "all judged segments within tolerance"))
    if challenger.get("interval_coverage") is not None and challenger.get("nominal_coverage") is not None:
        gap = abs(challenger["interval_coverage"] - challenger["nominal_coverage"])
        checks.append(("interval coverage calibrated", gap <= policy["coverage_tolerance"],
                       f"{challenger['interval_coverage']:.1%} vs nominal {challenger['nominal_coverage']:.0%}"))
    failed = [name for name, ok, _ in checks if not ok]
    return {"promote": not failed, "checks": checks,
            "reason": "all checks passed" if not failed else "blocked by: " + ", ".join(failed)}


# ---------------------------------------------------------------------------------------------
# Retrieval index and table freshness
# ---------------------------------------------------------------------------------------------

def index_refresh_plan(indexed: Mapping[str, str], current: Mapping[str, str]) -> dict:
    """Which chunks to embed, re-embed or remove, from chunk_id -> content-hash maps of the index and the
    current chunk table. Unchanged chunks are never re-embedded (embedding is the expensive step)."""
    new = sorted(k for k in current if k not in indexed)
    changed = sorted(k for k in current if k in indexed and indexed[k] != current[k])
    removed = sorted(k for k in indexed if k not in current)
    return {"embed": new + changed, "new": new, "changed": changed, "delete": removed + changed,
            "removed": removed, "unchanged": len(current) - len(new) - len(changed)}


def freshness_status(last_updated: datetime, now: datetime, sla_hours: float) -> dict:
    """'fresh' if the table was updated within its SLA, else 'late', with the age in hours."""
    age = (now - last_updated).total_seconds() / 3600
    return {"age_hours": round(age, 1), "sla_hours": sla_hours, "status": "fresh" if age <= sla_hours else "late"}


def affected_keys(changes: Iterable[Mapping], key: str) -> set:
    """Keys touched by a batch of Change Data Feed rows (inserts, update post-images and deletes);
    update pre-images are skipped because the post-image carries the same key."""
    return {c[key] for c in changes if c.get("_change_type") != "update_preimage" and c.get(key) is not None}
