"""Project performance ratings from several Bank sources, and a policy for resolving conflicts.

Three kinds of evidence rate the same project at different times and with different independence:

| source_type      | document                                         | who rates            | dimension(s)                              |
|------------------|--------------------------------------------------|----------------------|-------------------------------------------|
| isr_last         | last Implementation Status and Results Report    | task team (self)     | pdo_progress, implementation_progress     |
| isr_earlier      | an earlier ISR (here: the mid-period one)         | task team (self)     | pdo_progress, implementation_progress     |
| icr_self_rating  | Implementation Completion and Results Report      | Bank team (self)     | outcome                                   |
| ieg_validation   | IEG's ICR Review                                  | IEG (independent)    | outcome                                   |

All ratings use the Bank's six-point scale, normalised to a score: Highly Satisfactory 6, Satisfactory 5,
Moderately Satisfactory 4, Moderately Unsatisfactory 3, Unsatisfactory 2, Highly Unsatisfactory 1.
A score of 4 or more is "satisfactory" (the line the Bank's own outcome statistics use).

Parsing works on the plain-text renderings that documents.worldbank.org serves (".txt"). Both rating
tables are laid out in fixed-width columns, and the ICR Review wraps cell text over several lines
("Moderately" above the row label, "Satisfactory" below it), so words are assigned to a column by
their character offset under the header, and the column's text is then read in order.

`resolve_evidence()` is the resolution policy: a pure function from evidence records to an answer with
its supporting and conflicting records, a flag and a confidence label (see its docstring).
"""
from __future__ import annotations

import re
from datetime import date
from itertools import pairwise

# ---------------------------------------------------------------------------------------------
# Rating scale
# ---------------------------------------------------------------------------------------------

SCALE = {"Highly Satisfactory": 6, "Satisfactory": 5, "Moderately Satisfactory": 4,
         "Moderately Unsatisfactory": 3, "Unsatisfactory": 2, "Highly Unsatisfactory": 1}
ABBREVIATION = {"HS": "Highly Satisfactory", "S": "Satisfactory", "MS": "Moderately Satisfactory",
                "MU": "Moderately Unsatisfactory", "U": "Unsatisfactory", "HU": "Highly Unsatisfactory"}
SHORT = {label: abbr for abbr, label in ABBREVIATION.items()}
SATISFACTORY_FROM = 4

# A rating phrase, or a placeholder for "no rating" ("---", "Not Rated", "Non-Evaluable", "N/A").
# Placeholders are matched too, so that an empty cell does not shift the next row's rating up.
_PHRASE = re.compile(r"(?:Highly|Moderately)\s+(?:Satisfactory|Unsatisfactory)|Unsatisfactory|Satisfactory"
                     r"|Not\s+Rated|Non[\s-]*Evaluable|Not\s+Applicable|N/A|-{2,}", re.I)


def normalise_rating(text: str | None) -> tuple[str, int] | None:
    """('Moderately Satisfactory', 4) for any spelling or abbreviation; None for no rating."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    if cleaned.upper() in ABBREVIATION:
        cleaned = ABBREVIATION[cleaned.upper()]
    label = next((k for k in SCALE if k.lower() == cleaned.lower()), None)
    return (label, SCALE[label]) if label else None


def is_satisfactory(score: int | None) -> bool | None:
    return None if score is None else score >= SATISFACTORY_FROM


# ---------------------------------------------------------------------------------------------
# Fixed-width column tables
# ---------------------------------------------------------------------------------------------

_WORD = re.compile(r"\S+")


def _column_phrases(lines: list[str], bounds: dict[str, tuple[int, float]]) -> dict[str, list[str | None]]:
    """For each column (start, end offset), the rating phrases found in it, top to bottom.

    Words are assigned to the column whose span contains their first character; each column's words are
    joined in reading order and scanned for rating phrases. A placeholder ('---') yields None.
    """
    text = {name: [] for name in bounds}
    for line in lines:
        for word in _WORD.finditer(line):
            for name, (start, end) in bounds.items():
                if start <= word.start() < end:
                    text[name].append(word.group())
                    break
    out = {}
    for name, words in text.items():
        out[name] = [(normalise_rating(m.group()) or (None,))[0] for m in _PHRASE.finditer(" ".join(words))]
    return out


HEADER_SLACK = 8        # cells may start up to this many characters left of their column title
SECOND_WORD = 12        # ... but never before the second word of the previous cell ("Moderately " is 11 characters)


def _bounds(header: str, columns: list[str], tail: int | None) -> dict[str, tuple[int, float]]:
    """Column spans from the header line.

    Titles are not left-aligned with their cells: in ICR Reviews the IEG cells start up to 5 characters left
    of "IEG". A column therefore starts HEADER_SLACK characters before its title, but no earlier than
    SECOND_WORD characters after the previous title, so the second word of a two-word rating in the previous
    column stays there. The free-text column (`tail`) starts 3 characters before its title.
    """
    titles = [header.index(c) for c in columns]
    starts = [max(0, titles[0] - HEADER_SLACK)] + [max(t - HEADER_SLACK, prev + SECOND_WORD)
                                                    for prev, t in pairwise(titles)]
    ends = starts[1:] + [tail - 3 if tail is not None else float("inf")]
    return {c: (s, e) for c, s, e in zip(columns, starts, ends, strict=True)}


# ---------------------------------------------------------------------------------------------
# ISR: "Overall Ratings" block
# ---------------------------------------------------------------------------------------------

# Header "Previous Rating  Current Rating" (to 2023) or "Previous  Current" (2024+ template).
_ISR_HEADER = re.compile(r"^.*\bPrevious(?: Rating)?[ \t]+Current(?: Rating)?[ \t]*$", re.M)
# The 2024+ template prefixes each rating with an icon from the Private Use Area (U+F06C); replacing such
# characters by a space keeps every other character at its column offset.
_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")
_ISR_STOP = re.compile(r"Overall Risk Rating|Implementation Status and Key Decisions", re.I)
_SEQ = re.compile(r"Seq\s*No:\s*(\d+)", re.I)
_ARCHIVED = re.compile(r"ARCHIVED\s+on\s+(\d{1,2})-([A-Za-z]{3})-(\d{4})", re.I)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                         "nov", "dec"], start=1)}


def _archived_date(text: str) -> date | None:
    m = _ARCHIVED.search(text)
    if not m or m.group(2).lower() not in _MONTHS:
        return None
    try:
        return date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


def parse_isr_ratings(text: str | None) -> dict:
    """PDO and implementation-progress ratings (previous and current) of one ISR, plus its sequence number.

    Returns {'seq_no', 'archived_on', 'pdo_current', 'pdo_previous', 'ip_current', 'ip_previous'}; ratings are
    canonical labels or None when absent or unreadable.
    """
    out = {"seq_no": None, "archived_on": None, "pdo_current": None, "pdo_previous": None,
           "ip_current": None, "ip_previous": None}
    if not text:
        return out
    text = _PRIVATE_USE.sub(" ", text.replace("\r", ""))
    seq = _SEQ.search(text)
    out["seq_no"] = int(seq.group(1)) if seq else None
    out["archived_on"] = _archived_date(text)
    header = _ISR_HEADER.search(text)
    if not header:
        return out
    lines = text[header.end():].split("\n")
    block = []
    for line in lines[:40]:
        if _ISR_STOP.search(line):
            break
        block.append(line)
    # Only lines between the PDO row and the stop line: the row labels themselves contain no rating words.
    phrases = _column_phrases(block, _bounds(header.group(), ["Previous", "Current"], None))
    prev, cur = phrases["Previous"], phrases["Current"]
    out["pdo_current"], out["ip_current"] = (cur + [None, None])[:2]
    # The first ISR prints '--' as the previous rating, which is a placeholder (None) and keeps the order.
    out["pdo_previous"], out["ip_previous"] = (prev + [None, None])[:2]
    return out


# ---------------------------------------------------------------------------------------------
# ICR Review: "Ratings  ICR  IEG  Reason for Disagreements/Comment" table
# ---------------------------------------------------------------------------------------------

_ICRR_HEADER = re.compile(r"^[ \t]*Ratings[ \t]+ICR[ \t]+IEG\b.*$", re.M)
_ICRR_STOP = re.compile(r"^\s*(Quality of M&E|Quality of ICR|12\.\s|Lessons)", re.I)


def parse_icrr_ratings(text: str | None) -> dict:
    """Outcome and Bank-performance ratings as the ICR stated them and as IEG validated them.

    Returns {'icr_outcome', 'ieg_outcome', 'icr_bank_performance', 'ieg_bank_performance'} (canonical labels
    or None). The 'Reason for Disagreements/Comment' column is cut off so that its free text cannot be read
    as a rating.
    """
    out = {"icr_outcome": None, "ieg_outcome": None, "icr_bank_performance": None, "ieg_bank_performance": None}
    if not text:
        return out
    text = _PRIVATE_USE.sub(" ", text.replace("\r", ""))
    header = _ICRR_HEADER.search(text)
    if not header:
        return out
    before = text[:header.start()].rstrip("\n").split("\n")[-1]
    after = text[header.end():].lstrip("\n").split("\n")
    reason = next((ln.find(word) for ln, word in [(before, "Reason"), (after[0] if after else "", "Disagreements")]
                   if word in ln), None)
    block = []
    for line in after[:40]:
        if _ICRR_STOP.search(line):
            break
        block.append(line)
    phrases = _column_phrases(block, _bounds(header.group(), ["ICR", "IEG"], reason))
    out["icr_outcome"], out["icr_bank_performance"] = (phrases["ICR"] + [None, None])[:2]
    out["ieg_outcome"], out["ieg_bank_performance"] = (phrases["IEG"] + [None, None])[:2]
    return out


# ---------------------------------------------------------------------------------------------
# Resolution policy
# ---------------------------------------------------------------------------------------------

INDEPENDENCE = {"ieg_validation": "independent", "icr_self_rating": "self_reported",
                "isr_last": "self_reported", "isr_earlier": "self_reported"}

# For each question type: the (source_type, dimension) pairs that may answer it, best first.
# Specificity 'direct' = the source rates exactly what is asked; 'proxy' = a related rating.
HIERARCHY = {
    "outcome": [("ieg_validation", "outcome", "direct"),
                ("icr_self_rating", "outcome", "direct"),
                ("isr_last", "pdo_progress", "proxy"),
                ("isr_earlier", "pdo_progress", "proxy")],
    "current_status": [("isr_last", "implementation_progress", "direct"),
                       ("isr_last", "pdo_progress", "direct"),
                       ("isr_earlier", "implementation_progress", "direct"),
                       ("isr_earlier", "pdo_progress", "direct")],
}
CONFLICT_POINTS = 2          # scores this far apart (or more) are a conflict
STALE_STATUS_DAYS = 365      # a status older than this is stale


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _citation(rec: dict, rank: int, specificity: str) -> dict:
    return {"source_type": rec["source_type"], "dimension": rec["dimension"], "rating": rec["rating"],
            "score": rec["score"], "as_of": rec["as_of"].isoformat() if rec["as_of"] else None,
            "independence": INDEPENDENCE.get(rec["source_type"], "self_reported"), "rank": rank,
            "specificity": specificity, "doc_id": rec.get("doc_id"), "url": rec.get("url") or rec.get("doc_url"),
            "source": rec.get("source")}


def _describe(c: dict) -> str:
    return (f"{c['source_type']} {c['dimension']} = {SHORT.get(c['rating'], c['rating'])}"
            f" ({c['as_of'] or 'undated'}, doc {c['doc_id'] or 'n/a'})")


def resolve_evidence(records: list[dict], question_type: str, reference_date=None) -> dict:
    """Resolve possibly conflicting ratings of ONE project for one question type. Pure function.

    records: dicts with keys project_id, source_type (ieg_validation | icr_self_rating | isr_last |
        isr_earlier), dimension (outcome | pdo_progress | implementation_progress), rating (label or
        abbreviation), as_of (date or ISO string), and citation fields doc_id, url, source (optional).
        `score` is recomputed from `rating`. Rows of proc_silver.project_ratings_evidence fit as they are.
    question_type: 'outcome' (how did the project do?) or 'current_status' (how is implementation going?).
    reference_date: optional 'today' for the staleness rule of current_status.

    Policy:
    1. Never pick silently: every usable record is returned, as supporting or conflicting, with its date
       and citation; records the question cannot use are listed in `not_used`.
    2. Rank by the documented hierarchy (HIERARCHY): for outcome, IEG validation > ICR self-rating >
       last ISR > earlier ISR; for current status, the most recent ISR. Within a rank, the newest wins.
    3. The answer is the best-ranked record. Every other record is compared with it:
       - conflict: scores differ by >= 2 points (e.g. Satisfactory vs Moderately Unsatisfactory);
       - disagreement: 1 point apart but on opposite sides of the satisfactory line (MS vs MU);
       - otherwise it supports the answer.
       For current_status only records of the same ISR are compared; older ISRs are `superseded` history.
    4. Confidence: high = answer from the top tier for the question (IEG for outcome; a fresh last ISR for
       status) and no conflict; medium = top tier with a conflict, or a lower tier without disagreement;
       low = everything else (a lower tier contradicted, only ISR evidence for an outcome question, or a
       stale status).

    Returns {question_type, project_id, answer, supporting, conflicting, superseded, not_used, flag,
             confidence, rationale}; flag is one of consistent, disagreement, conflict, insufficient.
    """
    if question_type not in HIERARCHY:
        raise ValueError(f"question_type must be one of {sorted(HIERARCHY)}")
    rules = HIERARCHY[question_type]
    rank_of = {(s, d): (i, spec) for i, (s, d, spec) in enumerate(rules)}
    usable, not_used = [], []
    for raw in records:
        norm = normalise_rating(raw.get("rating"))
        rec = {**raw, "rating": norm[0] if norm else raw.get("rating"), "score": norm[1] if norm else None,
               "as_of": _as_date(raw.get("as_of"))}
        key = (rec.get("source_type"), rec.get("dimension"))
        if key in rank_of and norm:
            usable.append((rank_of[key][0], rank_of[key][1], rec))
        else:
            not_used.append(_citation(rec, -1, "not_applicable" if key not in rank_of else "unrated"))
    project_ids = sorted({r.get("project_id") for r in records if r.get("project_id")})
    result = {"question_type": question_type, "project_id": project_ids[0] if len(project_ids) == 1 else project_ids,
              "answer": None, "supporting": [], "conflicting": [], "superseded": [], "not_used": not_used,
              "flag": "insufficient", "confidence": "low", "rationale": ""}
    if not usable:
        result["rationale"] = f"No usable rating for a {question_type} question."
        return result

    # Best rank first; within a rank, newest first (undated records last).
    usable.sort(key=lambda t: (t[0], -(t[2]["as_of"].toordinal() if t[2]["as_of"] else 0)))
    top_rank, top_spec, top = usable[0]
    answer = _citation(top, top_rank, top_spec)
    result["answer"] = answer
    def same_doc(r):
        return (r.get("doc_id"), r["as_of"]) == (top.get("doc_id"), top["as_of"])

    for rank, spec, rec in usable[1:]:
        c = _citation(rec, rank, spec)
        if question_type == "current_status" and not same_doc(rec):
            result["superseded"].append(c)
            continue
        gap = abs(rec["score"] - top["score"])
        crosses = is_satisfactory(rec["score"]) != is_satisfactory(top["score"])
        c["points_from_answer"] = gap
        (result["conflicting"] if gap >= CONFLICT_POINTS or crosses else result["supporting"]).append(c)

    gaps = [c["points_from_answer"] for c in result["conflicting"]]
    flag = "conflict" if any(g >= CONFLICT_POINTS for g in gaps) else "disagreement" if gaps else "consistent"
    result["flag"] = flag

    is_top_tier = top_rank == 0 and (question_type != "outcome" or top["source_type"] == "ieg_validation")
    stale = False
    if question_type == "current_status" and reference_date is not None and top["as_of"] is not None:
        stale = (_as_date(reference_date) - top["as_of"]).days > STALE_STATUS_DAYS
    if is_top_tier and flag != "conflict" and not stale:
        confidence = "high"
    elif (is_top_tier and not stale) or (top_spec == "direct" and flag == "consistent" and not stale):
        confidence = "medium"
    else:
        confidence = "low"
    result["confidence"] = confidence

    parts = [f"Answer: {SHORT[top['rating']]} from {_describe(answer)}, the highest-ranked available source "
             f"for a {question_type} question ({answer['independence']}, {top_spec})."]
    if result["conflicting"]:
        parts.append("Conflicting: " + "; ".join(f"{_describe(c)}, {c['points_from_answer']} point(s) apart"
                                                 for c in result["conflicting"]) + ".")
    if result["supporting"]:
        parts.append("Supporting: " + "; ".join(_describe(c) for c in result["supporting"]) + ".")
    if result["superseded"]:
        parts.append(f"{len(result['superseded'])} older ISR rating(s) kept as history.")
    if stale:
        parts.append(f"The latest ISR is older than {STALE_STATUS_DAYS} days; status may be out of date.")
    if question_type == "outcome" and top["source_type"] != "ieg_validation":
        parts.append("No independent (IEG) validation yet; the answer is a self-rating.")
    parts.append(f"Flag {flag}, confidence {confidence}.")
    result["rationale"] = " ".join(parts)
    return result


def disconnect(isr_score: int | None, ieg_score: int | None) -> bool | None:
    """The Bank's 'disconnect': the last ISR rated progress satisfactory (MS or better), IEG rated the
    outcome moderately unsatisfactory or worse. None when either rating is missing."""
    if isr_score is None or ieg_score is None:
        return None
    return isr_score >= SATISFACTORY_FROM and ieg_score < SATISFACTORY_FROM
