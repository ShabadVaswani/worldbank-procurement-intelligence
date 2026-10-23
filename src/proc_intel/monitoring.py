"""Execution monitoring: early-warning indicators for active projects and a rule-based alert.

Pure Python (no Spark). The notebook (p14) computes the inputs from the procurement tables, the FinancesOne loan
and credit statements and the latest ISR of each project; these functions turn them into indicators and an alert
with reasons and citations.
"""
from __future__ import annotations

import re
from datetime import date

from proc_intel.evidence import SCALE

RISK_SCALE = {"Low": 1, "Moderate": 2, "Substantial": 3, "High": 4}
_RISK = r"(Low|Moderate|Substantial|High)"
SORT_CATEGORIES = ("Political and Governance", "Macroeconomic", "Sector Strategies and Policies",
                   "Technical Design of Project or Program", "Institutional Capacity for Implementation and Sustainability",
                   "Fiduciary", "Environment and Social", "Stakeholders", "Other", "Overall")

# Thresholds of the alert rules (documented in p14).
STALLED_MIN = 1                 # open tenders past their P90 duration
SLOW_MIN_CONTRACTS = 3          # recent timed contracts needed to judge the signing record
SLOW_SHARE = 0.5                # share of them slower than their peer group's slow threshold
DISBURSEMENT_GAP = -0.20        # disbursed share minus the peer median at the same elapsed time
MIN_ELAPSED = 0.25              # disbursement is not judged in the first quarter of the implementation period
EXTENSION_MONTHS = 6            # closing date moved by at least this much in the comparison window
ISR_STALE_DAYS = 365


def parse_sort_ratings(text: str | None) -> dict:
    """Ratings of the Systematic Operations Risk-rating Tool (SORT) table of an ISR.

    Each category row prints up to three ratings (at approval, last approved, proposed / current). Returns
    {category: {"approval": str | None, "current": str | None, "ratings": [..]}}. A category name wrapped over two
    lines ("Institutional Capacity for Implementation and" / "Sustainability") is matched by its first words.
    """
    out: dict = {}
    if not text:
        return out
    start = re.search(r"RISK-RATING TOOL|Risk Category|SYSTEMATIC OPERATIONS", text, re.I)
    # read only a window after the table title, so risk words elsewhere in the ISR are not taken as ratings
    body = text[start.start(): start.start() + 6000] if start else text
    lines = [re.sub(r"[-]", " ", ln) for ln in body.splitlines()]
    for cat in SORT_CATEGORIES:
        # match on the first four words: long category names wrap onto a second line
        head = " ".join(cat.split()[:4])
        for i, ln in enumerate(lines):
            if not re.match(rf"\s*{re.escape(head)}\b", ln):
                continue
            ratings = re.findall(rf"\b{_RISK}\b", ln[len(ln) - len(ln.lstrip()) + len(head):])
            if not ratings:
                # Ratings on the following lines: one wrapped-name line in the fixed-width layout, or one rating per
                # line in the 2026 cell-per-line layout. Stop at the first line that is neither.
                for nxt in lines[i + 1: i + 12]:
                    s = nxt.strip()
                    if not s:
                        continue
                    found = re.findall(rf"\b{_RISK}\b", s)
                    if found:
                        ratings += found
                        if len(ratings) >= 3:
                            break
                    elif ratings or len(s.split()) > 3:
                        break
            if ratings:
                # first printed rating = at approval, last = current; with a single rating the approval value is unknown
                out[cat] = {"approval": ratings[0] if len(ratings) >= 2 else None, "current": ratings[-1], "ratings": ratings}
                break
    return out


_RATING = re.compile(r"(?:Highly|Moderately)\s+(?:Satisfactory|Unsatisfactory)|Unsatisfactory|Satisfactory", re.I)


def parse_isr_cells(text: str | None) -> dict:
    """PDO and IP ratings of an ISR text rendered one table cell per line (the layout of 2026 renderings):
    'Progress towards achievement of PDO' / 'Moderately Satisfactory' / 'Satisfactory' (previous, then current).
    Returns the same keys as evidence.parse_isr_ratings; ratings are canonical labels or None."""
    out = {"seq_no": None, "archived_on": None, "pdo_current": None, "pdo_previous": None, "ip_current": None, "ip_previous": None}
    if not text:
        return out
    clean = re.sub(r"[-]", " ", text)
    m = re.search(r"Seq\s*No:\s*(\d+)", clean)
    out["seq_no"] = int(m.group(1)) if m else None
    m = re.search(r"Archived\s+on\s+(\d{2})-([A-Za-z]{3})-(\d{4})", clean)
    if m:
        months = {mo: i for i, mo in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
        mon_num = months.get(m.group(2).lower())
        out["archived_on"] = date(int(m.group(3)), mon_num, int(m.group(1))) if mon_num else None
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    canon = {k.lower(): k for k in SCALE}
    for key, label in (("pdo", r"Progress towards achievement of PDO"), ("ip", r"Overall Implementation Progress \(IP\)")):
        for i, ln in enumerate(lines):
            if re.fullmatch(label, ln, re.I):
                # the two lines after the label are previous then current; fullmatch so a sentence that merely contains
                # a rating word is ignored
                vals = [canon[" ".join(x.split()).lower()] for x in lines[i + 1: i + 3] if _RATING.fullmatch(x)]
                if len(vals) == 2:
                    out[f"{key}_previous"], out[f"{key}_current"] = vals
                elif len(vals) == 1:
                    out[f"{key}_current"] = vals[0]
                break
    return out


def disbursement_position(loans: list[dict], as_of: date) -> dict | None:
    """Disbursed share and elapsed share of the implementation period of one project, over its loans / credits.

    loans: dicts with original_amount, cancelled_amount, disbursed_amount, approval_date, closing_date (dates).
    elapsed = (as_of - first approval) / (latest closing - first approval), capped to [0, 1].
    """
    net = sum((x.get("original_amount") or 0) - (x.get("cancelled_amount") or 0) for x in loans)
    # fully cancelled (or zero) commitments have no meaningful disbursed share
    if net <= 0:
        return None
    disbursed = sum(x.get("disbursed_amount") or 0 for x in loans)
    starts = [x["approval_date"] for x in loans if x.get("approval_date")]
    ends = [x["closing_date"] for x in loans if x.get("closing_date")]
    if not starts or not ends or max(ends) <= min(starts):
        return None
    elapsed = (as_of - min(starts)).days / (max(ends) - min(starts)).days
    return {"net_commitment": net, "disbursed": disbursed, "disbursed_share": min(disbursed / net, 1.0),
            "elapsed_share": min(max(elapsed, 0.0), 1.0), "start": min(starts), "closing": max(ends)}


def expected_share(curve: dict[int, float], elapsed: float) -> float | None:
    """Peer median disbursed share at an elapsed share, from a curve {decile 0..9: median share}."""
    return curve.get(min(int(elapsed * 10), 9))


def months_between(a: date | None, b: date | None) -> float | None:
    if not a or not b:
        return None
    # average month length (365.25 / 12)
    return (b - a).days / 30.44


def isr_signal(pdo_prev: str | None, pdo_cur: str | None, ip_prev: str | None, ip_cur: str | None) -> dict:
    """Whether the latest ISR rates PDO or implementation progress below satisfactory, or downgraded either."""
    s = {k: SCALE.get(v) if v else None for k, v in
         {"pdo_prev": pdo_prev, "pdo_cur": pdo_cur, "ip_prev": ip_prev, "ip_cur": ip_cur}.items()}
    # 3 = Moderately Unsatisfactory on the six-point scale: below the satisfactory line
    unsat = [name for name, cur in (("PDO", s["pdo_cur"]), ("IP", s["ip_cur"])) if cur is not None and cur <= 3]
    down = [name for name, prev, cur in (("PDO", s["pdo_prev"], s["pdo_cur"]), ("IP", s["ip_prev"], s["ip_cur"]))
            if prev is not None and cur is not None and cur < prev]
    return {"unsatisfactory": unsat, "downgraded": down, "triggered": bool(unsat or down)}


def fiduciary_signal(approval: str | None, current: str | None) -> dict:
    """SORT fiduciary risk: High, or Substantial and raised since approval."""
    a, c = RISK_SCALE.get(approval or ""), RISK_SCALE.get(current or "")
    raised = a is not None and c is not None and c > a
    return {"triggered": c is not None and (c >= 4 or (c >= 3 and raised)), "raised": raised, "current": current}


def indicators(p: dict) -> list[dict]:
    """The early-warning indicators of one project.

    p keys (any may be missing): stalled_tenders [{notice_id, days_elapsed, p90_days}], recent_timed, recent_slow,
    recent_slow_ids, disbursed_share, elapsed_share, expected_share, loan_ids, closing_now, closing_before,
    window_start, isr {doc_id, as_of, pdo_prev, pdo_cur, ip_prev, ip_cur, fiduciary_approval, fiduciary_current},
    as_of (date).
    Returns one dict per indicator: {indicator, status ('triggered' / 'ok' / 'no_data'), value, reason, citations}.
    """
    out = []
    st = p.get("stalled_tenders") or []
    worst = sorted(st, key=lambda t: t["days_elapsed"] - t["p90_days"], reverse=True)[:3]
    out.append({"indicator": "stalled_tenders", "status": "triggered" if len(st) >= STALLED_MIN else "ok", "value": len(st),
                "reason": (f"{len(st)} open tender(s) past their P90 duration, e.g. "
                           + "; ".join(f"{t['notice_id']} open {t['days_elapsed']} days vs P90 {t['p90_days']}" for t in worst))
                if st else "no open tender past its P90",
                "citations": [f"notice:{t['notice_id']}" for t in worst]})
    n, slow = p.get("recent_timed") or 0, p.get("recent_slow") or 0
    if n >= SLOW_MIN_CONTRACTS:
        share = slow / n
        out.append({"indicator": "slow_signings", "status": "triggered" if share >= SLOW_SHARE else "ok", "value": round(share, 2),
                    "reason": f"{slow} of {n} contracts signed in the last 24 months took longer than their peer group's slow threshold",
                    "citations": [f"contract:{c}" for c in (p.get("recent_slow_ids") or [])[:3]]})
    else:
        out.append({"indicator": "slow_signings", "status": "no_data", "value": None,
                    "reason": f"only {n} timed contracts in the last 24 months", "citations": []})
    ds, el, ex = p.get("disbursed_share"), p.get("elapsed_share"), p.get("expected_share")
    if ds is None or el is None or ex is None:
        out.append({"indicator": "disbursement_lag", "status": "no_data", "value": None,
                    "reason": "no loan or credit statement", "citations": []})
    else:
        gap = ds - ex
        # early in a project every loan disburses slowly, so the first quarter of the period is never flagged
        trig = el >= MIN_ELAPSED and gap <= DISBURSEMENT_GAP
        out.append({"indicator": "disbursement_lag", "status": "triggered" if trig else "ok", "value": round(gap, 2),
                    "reason": f"{ds:.0%} disbursed at {el:.0%} of the implementation period; peers at that point: {ex:.0%}",
                    "citations": [f"loan:{x}" for x in (p.get("loan_ids") or [])[:3]]})
    moved = months_between(p.get("closing_before"), p.get("closing_now"))
    if moved is None:
        out.append({"indicator": "closing_extended", "status": "no_data", "value": None,
                    "reason": "closing date not in both statements", "citations": []})
    else:
        out.append({"indicator": "closing_extended", "status": "triggered" if moved >= EXTENSION_MONTHS else "ok",
                    "value": round(moved, 1),
                    "reason": f"closing date {p['closing_before']} in the statement of {p.get('window_start')}, now {p['closing_now']}",
                    "citations": [f"loan:{x}" for x in (p.get("loan_ids") or [])[:3]]})
    isr = p.get("isr")
    if not isr:
        out += [{"indicator": k, "status": "no_data", "value": None, "reason": "no ISR read", "citations": []}
                for k in ("isr_ratings", "fiduciary_risk")]
    else:
        stale = p.get("as_of") and isr.get("as_of") and (p["as_of"] - isr["as_of"]).days > ISR_STALE_DAYS
        note = f" (ISR of {isr.get('as_of')}, older than 12 months)" if stale else ""
        sig = isr_signal(isr.get("pdo_prev"), isr.get("pdo_cur"), isr.get("ip_prev"), isr.get("ip_cur"))
        parts = ([f"{'/'.join(sig['unsatisfactory'])} rated below Moderately Satisfactory"] if sig["unsatisfactory"] else []) + \
                ([f"{'/'.join(sig['downgraded'])} downgraded since the previous ISR"] if sig["downgraded"] else [])
        out.append({"indicator": "isr_ratings", "status": "triggered" if sig["triggered"] else "ok",
                    "value": f"PDO {isr.get('pdo_cur')}, IP {isr.get('ip_cur')}",
                    "reason": ("; ".join(parts) or "PDO and IP satisfactory, no downgrade") + note,
                    "citations": [f"document:{isr['doc_id']}"]})
        fid = fiduciary_signal(isr.get("fiduciary_approval"), isr.get("fiduciary_current"))
        if isr.get("fiduciary_current") is None:
            out.append({"indicator": "fiduciary_risk", "status": "no_data", "value": None,
                        "reason": "no SORT fiduciary rating in the ISR", "citations": [f"document:{isr['doc_id']}"]})
        else:
            out.append({"indicator": "fiduciary_risk", "status": "triggered" if fid["triggered"] else "ok",
                        "value": isr.get("fiduciary_current"),
                        "reason": (f"SORT fiduciary risk {isr.get('fiduciary_current')} "
                                   f"(at approval: {isr.get('fiduciary_approval')})" + note),
                        "citations": [f"document:{isr['doc_id']}"]})
    return out


def alert(inds: list[dict]) -> dict:
    """Rule-based alert from the indicators.

    red: 3+ indicators triggered, or unsatisfactory/downgraded ISR ratings together with a disbursement lag;
    amber: 2 triggered; watch: 1; none: 0. Also returns the triggered indicators' reasons and citations, and how many
    indicators had no data (an alert with many unknowns is less certain).
    """
    trig = [i for i in inds if i["status"] == "triggered"]
    names = {i["indicator"] for i in trig}
    # weak ratings together with money not flowing is the combination treated as most serious, even with only two
    # indicators
    if len(trig) >= 3 or {"isr_ratings", "disbursement_lag"} <= names:
        level = "red"
    else:
        level = {0: "none", 1: "watch", 2: "amber"}[len(trig)]
    return {"level": level, "n_triggered": len(trig), "triggered": sorted(names),
            "n_no_data": sum(i["status"] == "no_data" for i in inds),
            "reasons": [f"{i['indicator']}: {i['reason']}" for i in trig],
            # dict.fromkeys removes duplicate citations but keeps their order
            "citations": list(dict.fromkeys(c for i in trig for c in i["citations"]))}
