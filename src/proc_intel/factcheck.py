"""Code fact-check of a written brief against the records each sentence cites.

The tier-3 adjudication of the 30-brief review pack (data/human_review/adjudication_log.md) found the writer's
errors were small factual embellishments next to correct citations: a precedent called "same project" when its
project id differs, a firm-count range ("2 to 6 in the same project") that the cited records do not give. The
citation check cannot see these (the ids are real); this module checks the facts themselves.

For every cited sentence of a validated brief (timeline summary, market approach, each risk, each precedent's
reason; not the mitigations, which are advice, and not the package summary, which restates the package):

- **checkable claims** are read with regular expressions: firm counts ("8 firms", "up to 11 bidders") and ranges
  ("between 2 and 6 bidding firms"), days, percentages, project ids, procurement methods, and the relations
  "same project", "same country", "in the region";
- a **relation** narrows the records the numbers are checked against ("in the same project ... 2 to 6 firms" is
  checked against the cited contracts of the package's project only) and is itself unsupported when no cited
  contract has the package's project id / country / region;
- a **firm range** must equal the min-max of the in-scope records' `n_firms_in_award_notice` (records without an
  award notice are left out); "up to N" must be the maximum; a single count must be one of the values;
- **days and percentages** must appear in an in-scope record (or the package); a method must be the package's
  planned method or appear in a cited record; a project id must be the package's or a cited record's.

A wrong count or range that the records can correct is **replaced by the verified value** (`factcheck_fixed`);
any other unsupported claim **removes the sentence** (`factcheck_removed`). Interpretive phrases ("similar scope",
"similar regional context") and advice ("invite at least 5 firms") are not claims and are left alone.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from proc_intel.agent_tools import numbers_in, timeline_summary

# ---------------------------------------------------------------------------------------------------------
# Record facts
# ---------------------------------------------------------------------------------------------------------


def contract_facts(rec: dict) -> str:
    """The checkable facts of a contract record as one line the writer can quote, e.g.
    'project P146314 | LK | South Asia | Request for Bids | 2019 | firms in award notice: 3'."""
    year = str(rec.get("signing_date") or "")[:4] or "year not recorded"
    n = rec.get("n_firms_in_award_notice")
    return " | ".join([f"project {rec.get('project_id') or 'not recorded'}", rec.get("country_code") or "country not recorded",
                       rec.get("region") or "region not recorded", rec.get("method") or "method not recorded", year,
                       f"firms in award notice: {'not recorded' if n is None else int(n)}"])


# ---------------------------------------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------------------------------------

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")


def split_sentences(text: str) -> list[str]:
    """Sentences of a brief field ('e.g. as' does not split: the next word must start with a capital)."""
    return [s.strip() for s in _SENTENCE_END.split((text or "").strip()) if s.strip()]


# canonical method name (as in proc_silver.contracts) -> (pattern of the name, abbreviation or None)
_METHODS = {
    "Request for Bids": (r"requests? for bids?", r"RFBs?"),
    "Request for Quotations": (r"requests? for quotations?", r"RFQs?"),
    "Request for Proposals": (r"requests? for proposals?", r"RFPs?"),
    "Quality And Cost-Based Selection": (r"quality[- ]and[- ]cost[- ]based selection", r"QCBS"),
    "Quality Based Selection": (r"quality[- ]based selection", r"QBS"),
    "Fixed Budget Selection": (r"fixed[- ]budget selection", r"FBS"),
    "Least Cost Selection": (r"least[- ]cost selection", r"LCS"),
    "Consultant Qualification Selection": (r"consultants?['’]?s?['’]? qualifications? (?:based )?selection"
                                           r"|selection based on (?:the )?consultants?['’]?s?['’]? qualifications?",
                                           r"CQS"),
    "Individual Consultant Selection": (r"individual consultants? selection", r"ICS"),
    "Direct Selection": (r"direct selection", None),
    "Force Account": (r"force account", None),
    "E-Auctions": (r"e-auctions?", None),
}
_METHOD_RES = [(name, re.compile(rf"\b(?:{pat})\b", re.I), re.compile(rf"\b{abbr}\b") if abbr else None)
               for name, (pat, abbr) in _METHODS.items()]


def _method_spans(text: str) -> list[tuple[str, int, int]]:
    out = []
    for name, long_re, abbr_re in _METHOD_RES:
        for rx in (long_re, abbr_re):
            if rx is not None:
                out += [(name, m.start(), m.end()) for m in rx.finditer(text or "")]
    return out


def canonical_methods(text: Any) -> set[str]:
    """Procurement methods named in a text (full names or the usual abbreviations), as canonical names."""
    return {name for name, _, _ in _method_spans(str(text or ""))}


_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "twenty": 20}
_N = r"(\d+|" + "|".join(_WORDS) + r")"
_FIRM = r"(?:firms?|bidders?|bids|companies|suppliers|tenderers|offers|proposals)"
# up to two descriptive words between the number and the noun ("2 to 6 bidding firms"), but not "30 days for bids"
_GAP = r"(?:(?!(?:days?|months?|weeks?|years?|lots?|contracts?|packages?|for|of|per|and|to|in)\b)[A-Za-z-]+\s+){0,2}?"
_FIRM_RANGE = re.compile(rf"\b(?:between\s+|from\s+)?{_N}\s*(?:to|and|-|–|—)\s*{_N}\s+{_GAP}{_FIRM}\b", re.I)
_FIRM_ONE = re.compile(rf"\b(up to\s+|a maximum of\s+|only\s+)?{_N}\s+{_GAP}{_FIRM}\b", re.I)
_FIRM_SINGLE = re.compile(rf"\b(?:a\s+)?single\s+{_GAP}(?:firm|bidder|bid|company|supplier|tenderer|offer)\b"
                          r"|\bsole (?:bidder|tenderer)\b", re.I)
_DAY_RANGE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:to|and|-|–|—)\s*(\d+(?:\.\d+)?)(?:\s+|-)(?:calendar\s+)?days?\b", re.I)
_DAY_ONE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?:\s+|-)(?:calendar\s+)?days?\b", re.I)
_PERCENT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:%|per\s?cent\b)", re.I)
_PROJECT = re.compile(r"\bP\d{6}\b")
_RELATIONS = {"same_project": re.compile(r"\bsame project\b", re.I),
              "same_country": re.compile(r"\bsame (?:borrower )?country\b", re.I),
              "same_region": re.compile(r"\bsame region\b|\b(?:in|from|within|across) the region\b", re.I)}
_RELATION_FIELD = {"same_project": "project_id", "same_country": "country_code", "same_region": "region"}
# "all five close precedents", "each contract", "both precedents", "all of them": a claim about EVERY cited contract
_ANAPHOR = re.compile(r"\b(?:this|that|the same) (?:selection |procurement )?method\b", re.I)
_RECORDED_N = re.compile(rf"\bamong the {_N}\s+(?:[A-Za-z-]+\s+){{0,2}}?with (?:a )?recorded (?:firm )?counts?\b", re.I)
_QUALIFIED = re.compile(r"\b\d+ of \d+\b|recorded count|where recorded|among the\b", re.I)   # already says "4 of 5"
_QUANT = re.compile(rf"\b(all|each|every|both)\s+(?:of\s+(?:the\s+)?)?(?:{_N}\s+)?(?:[A-Za-z-]+\s+){{0,2}}?"
                    r"(?:precedents?|contracts?|records?|cases|awards?|tenders?|them)\b", re.I)
# advice, not a claim about the records: "invite at least 5 firms", "allow at least 30 days"
_ADVICE = re.compile(r"(?:at least|minimum(?: of)?|no (?:less|fewer) than|within|allow(?:ing)?|more than|over|fewer than|"
                     r"less than|target(?:ing)?|aim for)\s+$", re.I)
_GENERIC = {10.0, 50.0, 75.0, 80.0, 90.0}       # percentile names (P90, 80% interval) need no record


def _num(s: str) -> float:
    return float(_WORDS[s.lower()]) if s.lower() in _WORDS else float(s)


def _is_advice(text: str, start: int) -> bool:
    return bool(_ADVICE.search(text[max(0, start - 30):start]))


def extract_claims(sentence: str) -> list[dict]:
    """Checkable claims in one sentence, each {kind, text, start, end, values, ...}. Kinds: firm_range,
    firm_count (mode 'eq' or 'max'), days_range, days, percent, project_id, method, same_project, same_country,
    same_region."""
    s, claims, taken = sentence or "", [], []

    def free(a, b):
        return all(b <= x or a >= y for x, y in taken)

    def add(kind, m, values=(), **kw):
        claims.append({"kind": kind, "text": m.group(0), "start": m.start(), "end": m.end(), "values": values, **kw})
        taken.append((m.start(), m.end()))

    for m in _FIRM_RANGE.finditer(s):
        if not _is_advice(s, m.start()):
            add("firm_range", m, (_num(m.group(1)), _num(m.group(2))), spans=[m.span(1), m.span(2)])
    for m in _FIRM_ONE.finditer(s):
        if free(*m.span()) and not _is_advice(s, m.start()):
            mode = "max" if (m.group(1) or "").lower().strip() in ("up to", "a maximum of") else "eq"
            add("firm_count", m, (_num(m.group(2)),), spans=[m.span(2)], mode=mode)
    for m in _FIRM_SINGLE.finditer(s):
        if free(*m.span()):
            add("firm_count", m, (1.0,), spans=[], mode="eq")
    for m in _DAY_RANGE.finditer(s):
        if free(*m.span()) and not _is_advice(s, m.start()):
            add("days_range", m, (float(m.group(1)), float(m.group(2))), spans=[m.span(1), m.span(2)])
    for m in _DAY_ONE.finditer(s):
        if free(*m.span()) and not _is_advice(s, m.start()):
            add("days", m, (float(m.group(1)),))
    for m in _PERCENT.finditer(s):
        if not _is_advice(s, m.start()):
            add("percent", m, (float(m.group(1)),))
    for m in _PROJECT.finditer(s):
        add("project_id", m, (m.group(0),))
    for kind, rx in _RELATIONS.items():
        for m in rx.finditer(s):
            add(kind, m)
    for m in _QUANT.finditer(s):
        n = 2.0 if m.group(1).lower() == "both" else (_num(m.group(2)) if m.group(2) else None)
        add("quantifier", m, (n,))
    for m in _RECORDED_N.finditer(s):
        add("recorded_n", m, (_num(m.group(1)),), spans=[m.span(1)])
    spans = sorted(_method_spans(s), key=lambda x: x[1])
    for name, a, b in spans:
        claims.append({"kind": "method", "text": s[a:b], "start": a, "end": b, "values": (name,)})
    for m in _ANAPHOR.finditer(s):            # "this method" = the last method named before it
        before = [name for name, a, _ in spans if a < m.start()]
        if before:
            claims.append({"kind": "method", "text": m.group(0), "start": m.start(), "end": m.end(), "values": (before[-1],)})
    return sorted(claims, key=lambda c: c["start"])


# ---------------------------------------------------------------------------------------------------------
# Checking one sentence
# ---------------------------------------------------------------------------------------------------------

def _close(x: float, allowed: set[float]) -> bool:
    return any(abs(x - a) <= 0.5 for a in allowed)


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def factcheck_sentence(sentence: str, cited: Sequence[dict], package: dict) -> tuple[str | None, list[dict]]:
    """Check one sentence against the records it cites and the package facts ({project_id, country_code, region,
    method}). Returns (sentence, []) when every claim holds, (corrected sentence, [fixed event]) when wrong counts
    could be replaced by the records' values, (None, [removed event]) when a claim is unsupported."""
    claims = extract_claims(sentence)
    if not claims:
        return sentence, []
    package = package or {}
    scope, problems, fixes = [r for r in cited if r], [], []
    for rel, field in _RELATION_FIELD.items():
        if any(c["kind"] == rel for c in claims):
            want = package.get(field)
            match = [r for r in scope if r.get("type") == "contract" and want and r.get(field) == want]
            if not match:
                problems.append(f"'{rel.replace('_', ' ')}' but no cited contract has the package's {field} ({want})")
            scope = match or scope
    firms = sorted(int(r["n_firms_in_award_notice"]) for r in scope if r.get("n_firms_in_award_notice") is not None)
    allowed = numbers_in(package)
    for r in scope:
        allowed |= numbers_in({k: v for k, v in r.items() if k != "record_id"})
    contract_days = [float(r["days_notice_to_signing"]) for r in scope
                     if r.get("type") == "contract" and r.get("days_notice_to_signing") is not None]
    planned = canonical_methods(package.get("method"))
    methods = set(planned)
    projects = {package.get("project_id")}
    # a quantified sentence ("all five precedents ...") claims its count / method for EVERY cited contract
    quant = next((c for c in claims if c["kind"] == "quantifier"), None)
    contracts = [r for r in scope if r.get("type") == "contract"]
    qscope = [r for r in contracts if r.get("close_precedent")] or contracts
    qfirms = [r.get("n_firms_in_award_notice") for r in qscope]
    qualified = bool(_QUALIFIED.search(sentence))
    if quant and quant["values"][0] is not None and quant["values"][0] not in (len(contracts), len(qscope)):
        problems.append(f"'{quant['text']}' but {len(qscope)} such contracts are cited")
    for r in cited:
        methods |= canonical_methods(r.get("method")) | canonical_methods(r.get("label")) | canonical_methods(r.get("text"))
        projects |= {r.get("project_id")} | set(_PROJECT.findall(str(r.get("record_id", ""))))

    for c in claims:
        k, v = c["kind"], c["values"]
        if k == "firm_range":
            if not firms:
                problems.append(f"'{c['text']}': no cited record gives the firms in its award notice")
            elif (v[0], v[1]) != (firms[0], firms[-1]):
                if firms[0] == firms[-1]:
                    fixes.append((c["start"], c["spans"][1][1], str(firms[0])))
                else:
                    fixes += [(*c["spans"][0], str(firms[0])), (*c["spans"][1], str(firms[-1]))]
            if firms and quant and None in qfirms and not qualified:
                n_rec = sum(x is not None for x in qfirms)
                fixes.append((c["end"], c["end"], f" (among the {n_rec} with a recorded count)"))
        elif k == "firm_count" and quant and c["mode"] == "eq":
            known = {int(x) for x in qfirms if x is not None}
            if known != {int(v[0])}:
                problems.append(f"'{quant['text']} ... {c['text']}': the cited contracts give {sorted(known) or 'no count'}")
            elif None in qfirms and not qualified:
                fixes.append((c["end"], c["end"], f" (among the {sum(x is not None for x in qfirms)} with a recorded count)"))
        elif k == "recorded_n":
            n_rec = sum(r.get("n_firms_in_award_notice") is not None for r in (qscope if quant else contracts))
            if n_rec and v[0] != n_rec:
                fixes.append((*c["spans"][0], str(n_rec)))
            elif not n_rec:
                problems.append(f"'{c['text']}': no cited contract has a recorded count")
        elif k == "firm_count":
            if not firms:
                problems.append(f"'{c['text']}': no cited record gives the firms in its award notice")
            elif c["mode"] == "max" and v[0] != firms[-1]:
                fixes.append((*c["spans"][0], str(firms[-1])))
            elif c["mode"] == "eq" and v[0] not in firms:
                if len(set(firms)) == 1 and c["spans"]:
                    fixes.append((*c["spans"][0], str(firms[0])))
                else:
                    problems.append(f"'{c['text']}': cited records give {firms}")
        elif k == "days_range":
            if not (_close(v[0], allowed) and _close(v[1], allowed)):
                if contract_days and len(contract_days) == len(scope):
                    lo, hi = min(contract_days), max(contract_days)
                    fixes += [(*c["spans"][0], _fmt(lo)), (*c["spans"][1], _fmt(hi))]
                else:
                    problems.append(f"'{c['text']}': not in the cited records")
        elif k in ("days", "percent"):
            if not _close(v[0], allowed | (_GENERIC if k == "percent" else set())):
                problems.append(f"'{c['text']}': not in the cited records")
        elif k == "project_id" and v[0] not in projects:
            problems.append(f"'{c['text']}': neither the package's project nor a cited record's")
        elif k == "method" and v[0] not in methods:
            problems.append(f"'{c['text']}': not the planned method and in no cited record")
        elif k == "method" and quant and quant["end"] <= c["start"] and ";" not in sentence[quant["end"]:c["start"]]:
            # the method is said of the quantified contracts ("all five precedents used X", "all 5 ... this method")
            other = sorted({r.get("method") or "not recorded" for r in qscope if v[0] not in canonical_methods(r.get("method"))})
            if other:
                problems.append(f"'{quant['text']} ... {c['text']}': some cited contracts used {other}")

    if problems:
        return None, [{"action": "removed", "before": sentence, "after": None, "reason": "; ".join(problems),
                       "n_claims": len(claims)}]
    if fixes:
        new = sentence
        for a, b, rep in sorted(set(fixes), reverse=True):
            new = new[:a] + rep + new[b:]
        if new != sentence:
            return new, [{"action": "fixed", "before": sentence, "after": new,
                          "reason": f"counts corrected from the cited records (firms in award notices {firms}, "
                                    f"{sum(x is None for x in qfirms) if quant else 0} without a count)",
                          "n_claims": len(claims)}]
    return sentence, []


# ---------------------------------------------------------------------------------------------------------
# The whole brief
# ---------------------------------------------------------------------------------------------------------

def _check_text(text: str, cited: list[dict], package: dict, field: str, events: list[dict], counter: list[int]) -> str:
    kept = []
    for s in split_sentences(text):
        counter[0] += len(extract_claims(s))
        new, ev = factcheck_sentence(s, cited, package)
        events += [{**e, "field": field} for e in ev]
        if new:
            kept.append(new)
    return " ".join(kept)


def factcheck_brief(brief: dict, records: dict[str, dict], package: dict) -> tuple[dict, dict]:
    """Fact-check a validated brief (after `validate_brief`) against its cited records.

    Checked: timeline summary, market-approach recommendation, each risk (not its mitigation), each precedent's
    reason. A field emptied by removals is replaced: the timeline summary by one written from its fields, the
    recommendation by a neutral line on the planned method, a precedent's reason by its record's facts; a risk
    left empty is dropped (and 'complete' becomes 'partial' when no risk is left).
    Returns (checked brief, report with flags factcheck_removed / factcheck_fixed, the events and counts)."""
    b = json.loads(json.dumps(brief))
    events: list[dict] = []
    counter = [0]

    def recs(ids):
        return [records[i] for i in ids if i in records]

    tl = b["timeline"]
    if tl.get("summary"):
        new = _check_text(tl["summary"], recs(tl.get("citations", [])), package, "timeline.summary", events, counter)
        tl["summary"] = new or timeline_summary(tl, records)
    ma = b["market_approach"]
    new = _check_text(ma.get("recommendation", ""), recs(ma.get("citations", [])), package,
                      "market_approach.recommendation", events, counter)
    if not new and ma.get("recommendation"):
        planned = package.get("method")
        m = (sorted(canonical_methods(planned)) or [planned]) if planned else []
        new = (f"Proceed with the planned method ({m[0]}); the cited records are listed with this brief." if m
               else "No market-approach statement could be verified against the cited records.")
    ma["recommendation"] = new
    risks = []
    for i, r in enumerate(b["risks"]):
        r["risk"] = _check_text(r.get("risk", ""), recs(r.get("citations", [])), package, f"risks[{i}].risk", events, counter)
        if r["risk"]:
            risks.append(r)
    b["risks"] = risks
    for i, p in enumerate(b["precedents"]):
        rec = records.get(p["record_id"])
        new = _check_text(p.get("why_relevant", ""), recs([p["record_id"]]), package, f"precedents[{i}].why_relevant",
                          events, counter)
        p["why_relevant"] = new or (contract_facts(rec) if rec else "")
    if b.get("status") == "complete" and not risks:
        b["status"] = "partial"
    n_removed = sum(e["action"] == "removed" for e in events)
    n_fixed = sum(e["action"] == "fixed" for e in events)
    flags = (["factcheck_removed"] if n_removed else []) + (["factcheck_fixed"] if n_fixed else [])
    return b, {"flags": flags, "events": events, "n_removed": n_removed, "n_fixed": n_fixed,
               "n_claims_checked": counter[0]}
