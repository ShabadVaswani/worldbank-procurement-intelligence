"""Backtest helpers for p11_backtest: sampling, metrics, the precedent-relevance proxy, judge parsing, agreement.

The backtest replays historical tenders as if each were a new package on its notice date:

  sample      stratified (region x category) draw of openly competed tenders from the p07 test period,
              hash-ordered with a fixed seed so the same rows come out on every run and on every machine
  timeline    model and peer-benchmark forecasts vs the actual notice -> signing days
  precedents  similar_past_contracts with the package's own project and everything signed after the
              notice hidden; relevance by a rule-based proxy and by an LLM judge
  lessons     lessons_learned with the project's own documents and later documents hidden; an LLM judge
              checks them against what the project's completion report says went wrong
  review      a human review pack of full agent briefs, and the agreement between owner labels and judges

Everything here is pure Python (no Spark), covered by tests/test_backtest.py.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

import numpy as np

from proc_intel.risk import pinball_loss

# ---------------------------------------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------------------------------------

def stable_hash(seed: int | str, key: Any) -> str:
    """Hex SHA-1 of 'seed|key': a sort key that gives the same order on every run (unlike Spark's rand())."""
    return hashlib.sha1(f"{seed}|{key}".encode()).hexdigest()


def allocate_sample(sizes: Mapping[Any, int], n_total: int, floor: int = 5) -> dict:
    """Sample size per stratum: at least min(size, floor) each, the rest proportional to size.

    Largest-remainder rounding; no stratum gets more than its size. If the floors alone exceed n_total, the
    floors are kept (the sample is then larger than n_total) because a stratum with no rows cannot be reported.
    """
    sizes = {k: int(v) for k, v in sizes.items() if v > 0}
    alloc = {k: min(v, floor) for k, v in sizes.items()}
    remaining = n_total - sum(alloc.values())
    # loop because a stratum can hit its size cap; the places it cannot take are shared out again in the next round
    while remaining > 0:
        room = {k: sizes[k] - alloc[k] for k in sizes if sizes[k] > alloc[k]}
        if not room:
            break
        total = sum(sizes[k] for k in room)
        quota = {k: remaining * sizes[k] / total for k in room}
        add = {k: min(int(math.floor(q)), room[k]) for k, q in quota.items()}
        left = remaining - sum(add.values())
        # largest remainders first; ties broken by stratum key for determinism
        for k in sorted(room, key=lambda k: (-(quota[k] - math.floor(quota[k])), str(k))):
            if left <= 0:
                break
            if add[k] < room[k]:
                add[k] += 1
                left -= 1
        # no stratum can grow any more: stop instead of looping forever
        if sum(add.values()) == 0:
            break
        for k, a in add.items():
            alloc[k] += a
        remaining = n_total - sum(alloc.values())
    return alloc


def stratified_pick(rows: Sequence[Mapping], stratum: Callable[[Mapping], Any], alloc: Mapping[Any, int],
                    seed: int | str, id_key: str = "row_id", unique_keys: Sequence[str] = ("notice_id", "project_id")
                    ) -> list[dict]:
    """Pick alloc[s] rows per stratum in hash order of id_key.

    First pass: no two picks share any of `unique_keys` (one lot per tender notice, one tender per project), so the
    sample spreads over many projects. Second pass, only for strata still short: repeats of the last key (the
    project) are allowed, the first (the notice) still not.
    """
    ordered = sorted(rows, key=lambda r: stable_hash(seed, r[id_key]))
    by_stratum: dict[Any, list[Mapping]] = {}
    for r in ordered:
        by_stratum.setdefault(stratum(r), []).append(r)
    used = {k: set() for k in unique_keys}
    picked: dict[Any, list[dict]] = {s: [] for s in alloc}
    # pass 1 enforces every unique key, pass 2 only the first (the notice); `used` is shared, so pass 2 never repeats a
    # pass-1 pick
    for keys in (tuple(unique_keys), tuple(unique_keys[:1])):
        for s in sorted(alloc, key=str):
            for r in by_stratum.get(s, []):
                if len(picked[s]) >= alloc[s]:
                    break
                if any(r[k] in used[k] for k in keys) or any(r[id_key] == p[id_key] for p in picked[s]):
                    continue
                picked[s].append(dict(r))
                for k in unique_keys:
                    used[k].add(r[k])
    return [r for s in sorted(picked, key=str) for r in picked[s]]


def design_weights(sample_strata: Sequence[Any], population_sizes: Mapping[Any, int]) -> np.ndarray:
    """Inverse-probability weight N_h / n_h of each sampled row, so weighted means estimate the population."""
    counts: dict[Any, int] = {}
    for s in sample_strata:
        counts[s] = counts.get(s, 0) + 1
    return np.array([population_sizes[s] / counts[s] for s in sample_strata], dtype=float)


def weighted_mean(values, weights=None) -> float:
    v = np.asarray(values, dtype=float)
    w = np.ones_like(v) if weights is None else np.asarray(weights, dtype=float)
    ok = ~np.isnan(v)
    return float(np.sum(v[ok] * w[ok]) / np.sum(w[ok])) if ok.any() else float("nan")


def bootstrap_ci(values, stat: Callable[[np.ndarray], float] = np.mean, n_boot: int = 2000, alpha: float = 0.05,
                 seed: int = 7) -> tuple[float, float]:
    """Percentile bootstrap interval of `stat` over rows (NaNs dropped)."""
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    # resample rows with replacement; a fixed seed makes the interval identical on every run
    stats = np.array([stat(v[rng.integers(0, len(v), len(v))]) for _ in range(n_boot)])
    return float(np.quantile(stats, alpha / 2)), float(np.quantile(stats, 1 - alpha / 2))


# ---------------------------------------------------------------------------------------------------------
# Timeline metrics
# ---------------------------------------------------------------------------------------------------------

def interval_metrics(y, lo, mid, hi) -> dict:
    """Point and interval quality of a P10 / P50 / P90 forecast against outcomes y (days).
    Rows where any input is missing are dropped and counted in n."""
    y, lo, mid, hi = (np.asarray(a, dtype=float) for a in (y, lo, mid, hi))
    ok = ~(np.isnan(y) | np.isnan(lo) | np.isnan(mid) | np.isnan(hi))
    y, lo, mid, hi = y[ok], lo[ok], mid[ok], hi[ok]
    if len(y) == 0:
        return {"n": 0}
    out = {"n": int(len(y)), "mae_days": float(np.mean(np.abs(y - mid))),
           "median_ae_days": float(np.median(np.abs(y - mid))),
           "pinball_p10": pinball_loss(y, lo, 0.1), "pinball_p50": pinball_loss(y, mid, 0.5),
           "pinball_p90": pinball_loss(y, hi, 0.9),
           "coverage_p10_p90": float(np.mean((y >= lo) & (y <= hi))),
           "below_p10": float(np.mean(y < lo)), "above_p90": float(np.mean(y > hi)),
           "mean_width_days": float(np.mean(hi - lo))}
    out["mean_pinball"] = (out["pinball_p10"] + out["pinball_p50"] + out["pinball_p90"]) / 3
    return out


def roc_auc(y, score) -> float:
    """ROC-AUC by the rank-sum formula (ties get average ranks); NaN when only one class is present."""
    y = np.asarray(y, dtype=int)
    s = np.asarray(score, dtype=float)
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    # stable sort, so tied scores stay contiguous and get the same average rank below
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    sorted_s = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    # Mann-Whitney U of the positives divided by the number of positive-negative pairs equals the ROC-AUC
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


# ---------------------------------------------------------------------------------------------------------
# Time-leak guard
# ---------------------------------------------------------------------------------------------------------

def _as_date(value) -> date | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def leak_violations(records: Iterable[Mapping], cutoff, excluded_projects: Iterable[str] = (),
                    date_key: str = "signing_date") -> list[str]:
    """Record ids that a backtest must not see: from an excluded project, dated on or after the cutoff, or with
    no usable date. Used as an assertion after every retrieval call, whatever the tool does internally."""
    cut = _as_date(cutoff)
    excluded = set(excluded_projects)
    bad = []
    for r in records:
        d = _as_date(r.get(date_key))
        # undated records count as leaks: without a date the backtest cannot prove the record existed at the cutoff
        if r.get("project_id") in excluded or d is None or d >= cut:
            bad.append(r.get("record_id"))
    return bad


# ---------------------------------------------------------------------------------------------------------
# Precedent relevance proxy
# ---------------------------------------------------------------------------------------------------------

METHOD_FAMILIES = {
    "bids": ("Request for Bids", "Request for Proposals", "E-Auctions"),
    "consultant_firm": ("Quality And Cost-Based Selection", "Quality Based Selection", "Least Cost Selection",
                        "Fixed Budget Selection", "Consultant Qualification Selection"),
    "individual": ("Individual Consultant Selection",),
    "quotations": ("Request for Quotations", "Commercial Practices"),
    "direct": ("Direct Selection", "UN Agencies (Direct)", "Non-Profit Organizations"),
}
_FAMILY_OF = {m.lower(): f for f, ms in METHOD_FAMILIES.items() for m in ms}


def method_family(method: str | None) -> str:
    """Selection family of a procurement method: bids (open bidding for goods, works, non-consulting services),
    consultant_firm (QCBS, QBS, LCS, FBS, CQS), individual, quotations (RFQ: small, simple purchases), direct,
    or other (force account, CDD, PPP, unknown)."""
    return _FAMILY_OF.get((method or "").strip().lower(), "other")


# canonical sector -> words that identify it in dim_project.major_sector ("FY17 - Transportation", "Transportation")
# and in the awards feed's ';'-separated sector tags ("Public Admin;Info & Communication", "Water/Sanit/Waste")
SECTOR_PATTERNS = {
    "agriculture": r"agricult",
    "education": r"educat",
    "energy": r"energy",
    "public_administration": r"public admin",
    "health": r"health",
    "transport": r"transport",
    "ict": r"information and communication|info & communication|digital",
    "industry_trade": r"industry",
    "social_protection": r"social protection",
    "finance": r"financ",
    "water": r"water",
    "social_sustainability": r"social sustainab",
}


def canonical_sectors(*texts: str | None) -> frozenset:
    """Canonical sectors named in any of the texts (major sector, sector tags)."""
    found = set()
    for t in texts:
        low = (t or "").lower()
        for name, pattern in SECTOR_PATTERNS.items():
            if re.search(pattern, low):
                found.add(name)
    return frozenset(found)


def proxy_relevant(package: Mapping, precedent: Mapping, use_method: bool = True, use_sector: bool = True) -> bool | None:
    """Rule-based relevance of a precedent for a package (no LLM):
    same procurement category AND same method family AND at least one shared canonical sector.
    Both mappings carry 'category', 'method' and 'sectors' (a set). None when the sector rule is used and the package
    has no known sector (the rule cannot be applied). `use_method` / `use_sector` switch a condition off, to see
    which condition drives disagreements with human labels."""
    if use_sector and not package.get("sectors"):
        return None
    ok = package.get("category") == precedent.get("category")
    if use_method:
        ok = ok and method_family(package.get("method")) == method_family(precedent.get("method"))
    if use_sector:
        ok = ok and bool(set(package["sectors"]) & set(precedent.get("sectors") or ()))
    return bool(ok)


def precision_of_returned(relevant: Sequence[bool | None]) -> float | None:
    """Share relevant among the records actually returned (None when nothing was returned)."""
    vals = [bool(r) for r in relevant if r is not None]
    return sum(vals) / len(vals) if vals else None


# ---------------------------------------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------------------------------------

def agreement(a: Sequence, b: Sequence) -> dict:
    """Raw agreement and Cohen's kappa between two labelings (pairs where either is None are dropped)."""
    pairs = [(x, y) for x, y in zip(a, b, strict=True) if x is not None and y is not None
             and not (isinstance(x, float) and math.isnan(x)) and not (isinstance(y, float) and math.isnan(y))]
    n = len(pairs)
    if n == 0:
        return {"n": 0, "agreement": None, "kappa": None}
    po = sum(x == y for x, y in pairs) / n
    labels = sorted({x for x, _ in pairs} | {y for _, y in pairs}, key=str)
    # chance agreement: product of the two labelings' marginal shares, summed over labels
    pe = sum((sum(x == lab for x, _ in pairs) / n) * (sum(y == lab for _, y in pairs) / n) for lab in labels)
    kappa = None if pe == 1 else (po - pe) / (1 - pe)
    return {"n": n, "agreement": po, "kappa": kappa}


# ---------------------------------------------------------------------------------------------------------
# Lessons judge
# ---------------------------------------------------------------------------------------------------------

LESSON_VERDICTS = ("yes", "partial", "no", "none_occurred")
_JSON_OBJ = re.compile(r"\{.*\}", re.S)


def _short_list(x) -> list[str]:
    if isinstance(x, list):
        return [str(i)[:200] for i in x][:6]
    return [str(x)[:200]] if x else []


def parse_lesson_verdict(text: str) -> dict | None:
    """The judge's JSON reply -> {"verdict", "materialised", "matched", "rationale"}; None when unusable."""
    m = _JSON_OBJ.search(text or "")
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    verdict = str(v.get("verdict", "")).strip().lower()
    if verdict not in LESSON_VERDICTS:
        return None
    return {"verdict": verdict, "materialised": _short_list(v.get("materialised")), "matched": _short_list(v.get("matched")),
            "rationale": str(v.get("rationale", ""))[:600]}


def lesson_score(verdict: str | None) -> float | None:
    """yes = 1, partial = 0.5, no = 0; None for none_occurred or a failed judgement (not scorable)."""
    # "partial" (a generic warning) earns half: it would have pointed a team at the area, not at the mechanism
    return {"yes": 1.0, "partial": 0.5, "no": 0.0}.get(verdict or "")


# ---------------------------------------------------------------------------------------------------------
# Human review pack
# ---------------------------------------------------------------------------------------------------------

LABEL_COLUMNS = ("timeline_ok", "precedents_relevant", "risks_relevant", "any_unsupported_claim", "notes")


def _to_bool(v) -> bool | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y"):
        return True
    if s in ("0", "false", "no", "n"):
        return False
    return None


def _to_int(v) -> int | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else int(round(f))


def review_agreement(rows: Sequence[Mapping]) -> dict:
    """Agreement between the owner's labels and the automatic scores, over rows the owner labelled.

    timeline_ok (owner) vs auto_timeline_ok (actual duration inside the brief's cited P10-P90 range);
    precedents_relevant 0-5 (owner) vs auto_precedents_relevant (cited precedents the LLM judge called relevant);
    any_unsupported_claim (owner) vs auto_unsupported_claim (groundedness judge said "no").
    """
    out = {}
    t_h = [_to_bool(r.get("timeline_ok")) for r in rows]
    t_a = [_to_bool(r.get("auto_timeline_ok")) for r in rows]
    out["timeline_ok"] = agreement(t_h, t_a)
    u_h = [_to_bool(r.get("any_unsupported_claim")) for r in rows]
    u_a = [_to_bool(r.get("auto_unsupported_claim")) for r in rows]
    out["any_unsupported_claim"] = agreement(u_h, u_a)
    p = [(_to_int(r.get("precedents_relevant")), _to_int(r.get("auto_precedents_relevant"))) for r in rows]
    p = [(h, a) for h, a in p if h is not None and a is not None]
    if p:
        diff = [abs(h - a) for h, a in p]
        out["precedents_relevant"] = {"n": len(p), "exact": sum(d == 0 for d in diff) / len(p),
                                      "within_1": sum(d <= 1 for d in diff) / len(p), "mae": sum(diff) / len(p),
                                      "mean_owner": sum(h for h, _ in p) / len(p),
                                      "mean_judge": sum(a for _, a in p) / len(p)}
    else:
        out["precedents_relevant"] = {"n": 0}
    r = [_to_int(x.get("risks_relevant")) for x in rows]
    r = [x for x in r if x is not None]
    out["risks_relevant"] = {"n": len(r), "mean_owner": (sum(r) / len(r)) if r else None}
    out["n_labelled"] = sum(any(_to_bool(x.get(c)) is not None or _to_int(x.get(c)) is not None
                                for c in LABEL_COLUMNS[:4]) for x in rows)
    return out


def render_review_html(rows: Sequence[Mapping], title: str = "Procurement agent: human review pack") -> str:
    """A self-contained, readable HTML page: one section per package with the brief, cited records, the actual
    outcome and empty label fields to fill in the CSV. All text is escaped."""
    # all text comes from model output and source documents; escape it so nothing in it can act as HTML
    def e(s) -> str:
        return html.escape("" if s is None else str(s))

    parts = [f"<!doctype html><html><head><meta charset='utf-8'><title>{e(title)}</title>",
             "<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;"
             "color:#1b1b1b;background:#fff}h2{border-top:2px solid #ccc;padding-top:14px}pre{white-space:pre-wrap;"
             "background:#f6f6f6;padding:10px;border-radius:4px}table{border-collapse:collapse;width:100%}"
             "td,th{border:1px solid #ddd;padding:4px 6px;vertical-align:top;font-size:13px}.k{color:#555}</style>",
             f"</head><body><h1>{e(title)}</h1>",
             "<p>Fill the label columns in <code>review_briefs.csv</code>: timeline_ok (1/0), precedents_relevant "
             "(0-5), risks_relevant (0-5), any_unsupported_claim (1/0), notes.</p>"]
    for r in rows:
        parts.append(f"<h2>{e(r.get('review_id'))}: {e(r.get('country'))} / {e(r.get('category'))} / "
                     f"{e(r.get('method'))}</h2>")
        parts.append(f"<p><span class='k'>Package (notice {e(r.get('notice_id'))}, {e(r.get('notice_date'))}):</span> "
                     f"{e(r.get('description'))}</p>")
        parts.append(f"<p><span class='k'>Actual outcome:</span> {e(r.get('actual_outcome'))}</p>")
        parts.append(f"<pre>{e(r.get('brief_text'))}</pre>")
        cited = r.get("cited_records") or []
        if isinstance(cited, str):
            try:
                cited = json.loads(cited)
            except json.JSONDecodeError:
                cited = []
        if cited:
            parts.append("<table><tr><th>cited record</th><th>short text</th></tr>")
            parts += [f"<tr><td>{e(c.get('record_id'))}</td><td>{e(c.get('text'))}</td></tr>" for c in cited]
            parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts)
