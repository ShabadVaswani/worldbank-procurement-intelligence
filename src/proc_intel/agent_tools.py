"""Pure helpers behind the procurement agent (notebook p08 / proc_rag_core).

The agent's tools run Spark and model calls in the notebook; everything here is plain Python so it can be
unit-tested on tiny inputs:

- record ids: every record a tool returns carries a stable id in the knowledge-graph style
  `<type>:<key>` (contract:1543858, supplier_entity:SE-1000002, document_chunk:P123456_D1_0012,
  lesson_chunk:..., benchmark:..., forecast:...), and the brief may cite only those ids;
- contract search: TF-IDF retrieval with a small same-country / same-region bonus;
- peer-group choice for the timeline benchmark (most specific group with enough contracts);
- tool-call argument checking (the model's JSON is validated before any tool runs);
- the brief's JSON schema and its validation in code: invented ids are dropped, uncited claims removed,
  timeline numbers checked against the forecast and benchmark records they cite, precedents limited to the
  contracts the search marked as close (0 to 5);
- choosing the precedent relevance threshold from judged pairs, and small evaluation helpers.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, HashingVectorizer, TfidfTransformer
from sklearn.pipeline import make_pipeline

# ---------------------------------------------------------------------------------------------------------
# Record ids
# ---------------------------------------------------------------------------------------------------------

RECORD_TYPES = ("contract", "supplier_entity", "document_chunk", "lesson_chunk", "benchmark", "forecast", "tool_log")
_ID_RE = re.compile(r"^(contract|supplier_entity|document_chunk|lesson_chunk|benchmark|forecast|tool_log):[A-Za-z0-9_.\-|]+$")
# a record id written inside free text (evidence gaps cite the tool_log record that states an absence)
_INLINE_ID = re.compile(r"\b(?:contract|supplier_entity|document_chunk|lesson_chunk|benchmark|forecast|tool_log):[A-Za-z0-9_.\-|]+")
NO_PRECEDENT_GAP = "no close precedent found"


def record_id(kind: str, key: Any) -> str:
    """'<kind>:<key>', the same convention as proc_gold.kg_nodes.node_id."""
    assert kind in RECORD_TYPES, kind
    return f"{kind}:{key}"


def is_record_id(text: str) -> bool:
    return bool(_ID_RE.match(text or ""))


def tool_log_record(tool: str, label: str, **facts: Any) -> dict:
    """A citable record of what a tool did NOT find ('no contract passed the precedent rule, 30 candidates checked',
    'peer group skipped: 12 contracts < 20'), so an evidence gap can cite its source like any other statement."""
    # the id hashes the tool, label and facts, so the same absence gets the same id on every run
    key = hashlib.sha1(json.dumps([tool, label, facts], sort_keys=True, default=str).encode()).hexdigest()[:10]
    return {"record_id": record_id("tool_log", f"{tool}-{key}"), "type": "tool_log", "tool": tool, "label": label, **facts}


def benchmark_key(level: str, country: str | None, method: str | None, category: str | None) -> str:
    """Readable, stable benchmark id key: level plus a short hash of the peer-group values."""
    raw = "|".join(str(x or "*") for x in (level, country, method, category))
    return f"{level}-{hashlib.sha1(raw.encode()).hexdigest()[:8]}"


# ---------------------------------------------------------------------------------------------------------
# Contract search (TF-IDF, location bonus)
# ---------------------------------------------------------------------------------------------------------

_WS = re.compile(r"\s+")


def search_text(contract_description: str | None, notice_description: str | None = None,
                project_name: str | None = None) -> str:
    """Text indexed for one contract: its description, the tender notice description when it adds words,
    and the project name (sector context such as 'Rural Roads Project')."""
    parts: list[str] = []
    for p in (contract_description, notice_description, project_name):
        p = _WS.sub(" ", (p or "")).strip()
        # skip a part already contained in an earlier one (notice descriptions often repeat the contract description)
        if p and not any(p.lower() in q.lower() for q in parts):
            parts.append(p)
    return " | ".join(parts)


# descriptions come in English, French, Spanish and Portuguese: function words of all four are dropped
STOP_WORDS = sorted(ENGLISH_STOP_WORDS | {
    "de", "des", "du", "la", "le", "les", "un", "une", "et", "en", "au", "aux", "pour", "par", "sur", "dans", "avec",
    "l", "d", "el", "los", "las", "del", "y", "para", "por", "con", "una", "al", "o", "da", "do", "dos", "das", "e",
    "em", "no", "na", "nos", "nas", "com", "um", "uma"})


WORD_PATTERN = r"(?u)\b[^\W\d_]{2,}\b"     # words of 2+ letters


def fit_search_index(texts: Sequence[str], n_features: int = 2 ** 20):
    """Word unigram + bigram TF-IDF (sublinear tf, accents and function words dropped), rows L2-normalised.

    Bigrams keep phrases such as 'rural roads' or 'water supply' together; sublinear tf stops a word repeated
    in a long description from dominating; tokens are words of 2+ letters (reference numbers carry no meaning
    across contracts). The vocabulary is hashed into n_features columns instead of being stored: over 280k
    descriptions a stored unigram + bigram vocabulary needs several GB of driver memory while being counted,
    and with 2^20 columns hash collisions between meaningful terms are rare.
    Returns (fitted transformer with .transform(texts), csr matrix).
    """
    vec = make_pipeline(
        # alternate_sign=False keeps every weight positive; norm=None leaves normalisation to the TF-IDF step after it
        HashingVectorizer(ngram_range=(1, 2), n_features=n_features, alternate_sign=False, norm=None,
                          strip_accents="unicode", lowercase=True, stop_words=STOP_WORDS, token_pattern=WORD_PATTERN,
                          dtype=np.float32),
        TfidfTransformer(sublinear_tf=True))
    return vec, vec.fit_transform(texts).astype(np.float32).tocsr()


def query_scores(vec, matrix: sparse.csr_matrix, query: str) -> np.ndarray:
    """Cosine similarity of the query to every indexed row (rows and query are unit length)."""
    q = vec.transform([query])
    # (n_rows x n_features) @ (n_features x 1) is a sparse column of dot products; flattened to one score per row
    return np.asarray((matrix @ q.T).todense()).ravel()


def boosted_top_k(scores: np.ndarray, boosts: np.ndarray, k: int, min_score: float = 0.0,
                  allowed: np.ndarray | None = None) -> list[tuple[int, float]]:
    """Top-k rows by score + boost, among `allowed` rows whose raw score reaches min_score.

    The boost is a small bonus for the same country / region (e.g. +0.05 / +0.02): a near-identical precedent
    from another region still wins, but among comparable matches local ones come first, because they share the
    implementing agencies, market and regulations. Returns [(row, raw score)] best first.
    """
    # the min_score floor is applied to the raw score, so the boost cannot lift a weak match over it
    keep = scores >= min_score
    if allowed is not None:
        keep &= allowed
    idx = np.flatnonzero(keep)                             # row numbers of the candidates
    if not len(idx):
        return []
    total = scores[idx] + boosts[idx]                      # ranking score, aligned with idx
    if len(idx) > k:
        # argpartition finds the k best in linear time without sorting all candidates; only those k are sorted below
        part = np.argpartition(-total, k - 1)[:k]
        idx, total = idx[part], total[part]
    order = np.lexsort((idx, -total))                      # ties broken by row number: deterministic
    # the boost only sets the order; the score returned is the raw one
    return [(int(idx[o]), float(scores[idx[o]])) for o in order]


def location_boost(row_country: np.ndarray, row_region: np.ndarray, country: str | None, region: str | None,
                   same_country: float = 0.05, same_region: float = 0.02) -> np.ndarray:
    """Per-row bonus: same_country for the package's country, same_region for its region (not both)."""
    boost = np.zeros(len(row_country), dtype=np.float32)
    if region:
        boost[row_region == region] = same_region
    if country:
        # assigned after the region bonus so a same-country row gets the country bonus only, not both
        boost[row_country == country] = same_country
    return boost


def diverse_top_k(order: Sequence[int], groups: Sequence, k: int, per_group: int = 2) -> list[int]:
    """The first k items of `order` (best first) with at most per_group items from one group (e.g. one document),
    so that six evidence passages do not all come from the same report."""
    # seen: group -> number of items already taken from it; an item from a full group is skipped, not deferred
    seen: dict = {}
    out = []
    for i in order:
        g = groups[i]
        if seen.get(g, 0) >= per_group:
            continue
        seen[g] = seen.get(g, 0) + 1
        out.append(int(i))
        if len(out) >= k:
            break
    return out


# ---------------------------------------------------------------------------------------------------------
# Resolving the package fields
# ---------------------------------------------------------------------------------------------------------

def resolve_country(value: str | None, names_by_code: dict[str, str]) -> str | None:
    """'KE', 'ke', 'Kenya' or 'kenya' -> 'KE'; None if unknown. names_by_code: country code -> display name."""
    if not value:
        return None
    v = value.strip()
    if v.upper() in names_by_code:
        return v.upper()
    # not a code: look the value up by display name, case-insensitively (lowercase name -> code)
    by_name = {n.lower(): c for c, n in names_by_code.items() if n}
    return by_name.get(v.lower())


def resolve_method(value: str | None, names_by_code: dict[str, str]) -> str | None:
    """'RFB' or 'request for bids' -> 'Request for Bids'; None if unknown. names_by_code: method code -> name."""
    if not value:
        return None
    v = value.strip()
    if v.upper() in names_by_code:
        return names_by_code[v.upper()]
    by_name = {n.lower(): n for n in names_by_code.values()}
    return by_name.get(v.lower())


# ---------------------------------------------------------------------------------------------------------
# Timeline benchmark: choose the peer group
# ---------------------------------------------------------------------------------------------------------

PEER_LEVELS = ("country_method_category", "region_method_category", "method_category", "category")


def choose_peer_group(groups: Sequence[dict], min_n: int = 20) -> dict | None:
    """The most specific peer group with at least min_n timed contracts.

    groups: dicts with at least 'level' (one of PEER_LEVELS) and 'n'. Order of preference is PEER_LEVELS.
    Returns None when no group is large enough (the agent then says there is no reliable benchmark).
    """
    # by_level: level -> group dict; groups with no contract count are left out
    by_level = {g["level"]: g for g in groups if g.get("n") is not None}
    # walk from the most specific level to the broadest and stop at the first one that is large enough
    for level in PEER_LEVELS:
        g = by_level.get(level)
        if g is not None and g["n"] >= min_n:
            return g
    return None


# ---------------------------------------------------------------------------------------------------------
# Tool-call argument checking
# ---------------------------------------------------------------------------------------------------------

_ARTICLE = {"string": "a string", "integer": "an integer", "number": "a number", "boolean": "a boolean",
            "object": "an object", "array": "an array"}
_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def check_tool_call(name: str, raw_arguments: str | dict | None, tool_specs: dict[str, dict]
                    ) -> tuple[dict | None, str | None]:
    """Validate a model's tool call against the tool's JSON-schema parameters.

    Returns (arguments, None) or (None, error). Unknown arguments are dropped (models sometimes add some),
    null values are treated as absent, missing required ones, wrong types and values outside an enum are
    errors. The error text is sent back to the model as the tool result so it can correct itself.
    """
    if name not in tool_specs:
        return None, f"unknown tool '{name}'; available: {sorted(tool_specs)}"
    try:
        # a dict is used as given; a JSON string is parsed, and None or "" means no arguments
        args = raw_arguments if isinstance(raw_arguments, dict) else json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as e:
        return None, f"arguments are not valid JSON: {e.msg}"
    if not isinstance(args, dict):
        return None, "arguments must be a JSON object"
    params = tool_specs[name].get("parameters", {})
    props = params.get("properties", {})
    clean = {}
    # each argument is dropped (unknown or null), coerced (quoted numbers) or rejected (wrong type, not in the enum);
    # clean collects the accepted ones and the first rejection returns an error at once
    for key, value in args.items():
        if key not in props or value is None:
            continue
        spec = props[key]
        want = _JSON_TYPES.get(spec.get("type", "string"), object)   # Python type(s) to accept; an unknown type accepts anything
        typ = spec.get("type", "string")
        if typ in ("integer", "number") and isinstance(value, str) and re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", value):
            value = float(value)                                 # models often quote numbers: "k": "5"
        # 5.0 (or "5" after the line above) becomes 5; 2.5 stays a float and fails the type check below
        if typ == "integer" and isinstance(value, float) and value.is_integer():
            value = int(value)
        # bool is a subclass of int in Python, so True would otherwise pass as the integer 1
        if isinstance(value, bool) and typ in ("integer", "number"):
            return None, f"argument '{key}' must be {_ARTICLE[typ]}"
        if not isinstance(value, want):
            return None, f"argument '{key}' must be {_ARTICLE.get(typ, typ)}"
        if "enum" in spec and value not in spec["enum"]:
            return None, f"argument '{key}' must be one of {spec['enum']}"
        clean[key] = value
    # checked on the cleaned arguments, so a required argument sent as null counts as missing
    missing = [r for r in params.get("required", []) if r not in clean]
    if missing:
        return None, f"missing required argument(s): {missing}"
    return clean, None


# ---------------------------------------------------------------------------------------------------------
# The brief: schema and validation in code
# ---------------------------------------------------------------------------------------------------------

STATUSES = ("complete", "partial", "insufficient_evidence")
# timeline field -> (record type it must come from, field of that record)
TIMELINE_SOURCES = {"forecast_p10_days": ("forecast", "p10_days"), "forecast_p50_days": ("forecast", "p50_days"),
                    "forecast_p90_days": ("forecast", "p90_days"), "slow_probability": ("forecast", "slow_probability"),
                    "peer_p50_days": ("benchmark", "p50_days"), "peer_p90_days": ("benchmark", "p90_days")}
TIMELINE_NUMBERS = tuple(TIMELINE_SOURCES)

BRIEF_SCHEMA = {"type": "json_schema", "json_schema": {"name": "procurement_brief", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["package_summary", "timeline", "market_approach", "risks", "precedents", "evidence_gaps", "status"],
    "properties": {
        "package_summary": {"type": "string"},
        "timeline": {"type": "object", "additionalProperties": False,
                     "required": ["summary", *TIMELINE_NUMBERS, "citations"],
                     "properties": {"summary": {"type": "string"},
                                    **{f: {"type": ["number", "null"]} for f in TIMELINE_NUMBERS},
                                    "citations": {"type": "array", "items": {"type": "string"}}}},
        "market_approach": {"type": "object", "additionalProperties": False,
                            "required": ["recommendation", "citations"],
                            "properties": {"recommendation": {"type": "string"},
                                           "citations": {"type": "array", "items": {"type": "string"}}}},
        "risks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["risk", "mitigation", "citations"],
            "properties": {"risk": {"type": "string"}, "mitigation": {"type": "string"},
                           "citations": {"type": "array", "items": {"type": "string"}}}}},
        "precedents": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["record_id", "why_relevant"],
            "properties": {"record_id": {"type": "string"}, "why_relevant": {"type": "string"}}}},
        "evidence_gaps": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": list(STATUSES)}}}}}


def parse_brief(text: str) -> tuple[dict | None, str | None]:
    """Parse the model's reply into a brief dict; (None, error) when it is not a schema-shaped object."""
    try:
        s = (text or "").strip()
        # some models wrap the JSON in prose or code fences; take the outermost {...}
        if not s.startswith("{"):
            m = re.search(r"\{.*\}", s, re.S)
            s = m.group(0) if m else s
        b = json.loads(s)
    except Exception as e:
        return None, f"invalid JSON: {type(e).__name__}: {str(e)[:100]}"
    problems = []
    if not isinstance(b, dict):
        return None, "the reply is not a JSON object"
    for key, typ in (("package_summary", str), ("timeline", dict), ("market_approach", dict), ("risks", list),
                     ("precedents", list), ("evidence_gaps", list), ("status", str)):
        if not isinstance(b.get(key), typ):
            problems.append(f"'{key}' must be a {typ.__name__}")
    # the checks below index into these fields, so they run only when every top-level field has the right type
    if not problems:
        # a timeline without the number fields (an older brief shape) gets them as None
        for f in TIMELINE_NUMBERS:
            b["timeline"].setdefault(f, None)
        if not isinstance(b["timeline"].get("citations"), list) or not isinstance(b["market_approach"].get("citations"), list):
            problems.append("timeline and market_approach need a 'citations' list")
        if any(not isinstance(r, dict) or not isinstance(r.get("citations"), list) for r in b["risks"]):
            problems.append("every risk needs a 'citations' list")
        if any(not isinstance(p, dict) or not isinstance(p.get("record_id"), str) for p in b["precedents"]):
            problems.append("every precedent needs a 'record_id' string")
        if b["status"] not in STATUSES:
            problems.append(f"'status' must be one of {list(STATUSES)}")
    return (None, "; ".join(problems)) if problems else (b, None)


def _clean_ids(ids: Iterable, known: set[str], invalid: list[str]) -> list[str]:
    # returns the known ids in first-seen order without duplicates; every unknown one is appended to `invalid`
    out = []
    for c in ids:
        # writers sometimes copy the brackets from "[contract:123]"; strip them before matching
        c = str(c).strip().strip("[]")
        if c in known:
            if c not in out:
                out.append(c)
        else:
            invalid.append(c)
    return out


def _num_equal(a, b, tol: float = 0.5) -> bool:
    # None or a non-numeric value on either side never counts as equal
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


# standalone numbers only: digits inside ids or words ("P123456", "FY2024") are not checked
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w)")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")      # a thousands comma ("1,200"), removed so the number reads as 1200
# percentile and interval names a timeline summary may use without a record holding them ("P90", "90th", "80% interval")
_GENERIC_NUMBERS = {10.0, 50.0, 75.0, 80.0, 90.0}
# the writer must not compare the two medians (the code does, see compare_medians)
_COMPARISON_RE = re.compile(r"\b(?:faster|slower|shorter|longer|quicker|lower|higher|below|above|exceeds?|less|more) than\b"
                            r"|\b(?:below|above) the (?:country |regional )?peer", re.I)
# a summary that says there is no forecast while a scored one is cited contradicts its own numbers
_NO_FORECAST_PHRASES = ("peer group only", "peer-group only", "forecast is not available", "forecast not available",
                        "could not score")
# flags that mean something was wrong or missing (they lower 'complete' to 'partial'); the others record repairs
_PROBLEM_FLAGS = {"invalid_citation", "uncited_risk", "timeline_uncited", "timeline_corrected", "timeline_text_replaced",
                  "market_uncited", "precedent_not_close", "no_close_precedent"}


def numbers_in(value: Any) -> set[float]:
    """Every number written in a value (strings, numbers, nested lists and dicts). A fraction in [0, 1] also
    counts as its percentage (0.31 -> 31), and a float also as its rounded value."""
    out: set[float] = set()
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        v = float(value)
        if v == v:                                       # False only for NaN, which contributes nothing
            # the value itself, rounded to a whole number and to one decimal: a text may write 128.4 days as "128"
            out |= {v, float(round(v)), round(v, 1)}
            if 0 <= v <= 1:
                out |= {float(round(v * 100)), round(v * 100, 1)}
        return out
    if isinstance(value, str):
        return {float(x) for x in _NUMBER.findall(_THOUSANDS.sub("", value))}
    # a dict contributes its values only (its keys are field names); lists are searched recursively
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, (list, tuple)):
        for v in value:
            out |= numbers_in(v)
    return out


def unsupported_numbers(text: str, sources: Sequence[Any]) -> list[str]:
    """Numbers in `text` that appear in none of `sources` (records, the package text), within 0.5."""
    allowed = set(_GENERIC_NUMBERS)
    for s in sources:
        allowed |= numbers_in(s)
    bad = []
    # every standalone number in the text must be within 0.5 of an allowed one; the misses are returned as written
    for x in _NUMBER.findall(_THOUSANDS.sub("", text or "")):
        if not any(abs(float(x) - a) <= 0.5 for a in allowed):
            bad.append(x)
    return bad


def _equal(field: str, a, b) -> bool:
    # slow_probability is a fraction in [0, 1], so it gets a much tighter tolerance than the day counts
    return _num_equal(a, b, tol=0.005 if field == "slow_probability" else 0.5)


def timeline_summary(tl: dict, records: dict[str, dict]) -> str:
    """A summary written from the timeline fields only (used when the writer's summary has an unsupported number)."""
    parts = []
    # fc: the first cited forecast record, or None; it only decides whether to say that the model could not score
    fc = next((records[c] for c in tl["citations"] if records.get(c, {}).get("type") == "forecast"), None)
    if tl.get("forecast_p50_days") is not None:
        parts.append(f"The duration model forecasts a median of {tl['forecast_p50_days']:.0f} days from tender notice to "
                     f"signing for this package (80% interval {tl['forecast_p10_days']:.0f} to {tl['forecast_p90_days']:.0f} "
                     f"days), based on planning-time assumptions listed in the forecast record.")
    elif fc is not None:
        parts.append("The duration model could not score this package; the timeline rests on the peer group only.")
    if tl.get("peer_p50_days") is not None:
        parts.append(f"Comparable tenders in the peer group took a median of {tl['peer_p50_days']:.0f} days "
                     f"(90th percentile {tl['peer_p90_days']:.0f} days).")
    return " ".join(parts) or "No timeline evidence."


def compare_medians(forecast_p50: float, peer_p50: float) -> str:
    """The forecast-vs-peer comparison, computed in code (writers got the direction wrong: '129 days, faster than
    the peer median of 100')."""
    d = round(float(forecast_p50) - float(peer_p50))      # whole days; positive means the forecast is longer
    if d == 0:                                             # a difference under half a day counts as equal
        return "the forecast median equals the peer-group median"
    return f"the forecast median is {abs(d)} days {'longer' if d > 0 else 'shorter'} than the peer-group median"


def _timeline_refs(citations: list[str], records: dict[str, dict]) -> dict[str, dict | None]:
    """The record each timeline source is checked against: a scored forecast first, the chosen benchmark first."""
    cited = [records[c] for c in citations]
    # sort key `not scored` / `not chosen`: False sorts before True, so a scored forecast and a chosen benchmark
    # come first; otherwise the first one cited is used
    fc = sorted((r for r in cited if r.get("type") == "forecast"), key=lambda r: not r.get("scored"))
    bm = sorted((r for r in cited if r.get("type") == "benchmark"), key=lambda r: not r.get("chosen"))
    return {"forecast": fc[0] if fc else None, "benchmark": bm[0] if bm else None}


def validate_brief(brief: dict, records: dict[str, dict], package_text: str = "", max_precedents: int = 5
                   ) -> tuple[dict, dict]:
    """Check every citation of a parsed brief against the records the tools returned in this run.

    - ids not returned by a tool are dropped (and listed in the report as invented);
    - a risk with no valid citation left is removed (`uncited_risk`);
    - timeline: the forecast fields must equal the cited forecast record (a scored one) and the peer fields the
      cited benchmark record (the chosen one); a differing value is replaced (`timeline_corrected`), a value
      without a cited source is cleared (`timeline_uncited`). A scored forecast or a chosen benchmark that the
      writer left out is added with its citation (`forecast_added`, `benchmark_added`), so the brief always shows
      both. When the model could not score the package, an evidence gap says so (`forecast_unavailable`).
      A summary with a number found in no cited timeline record (nor the package), or one that says there is no
      forecast while a scored forecast is cited, or one that compares the two medians in words (the code states the
      difference itself), is rewritten from the fields (`timeline_text_replaced`);
    - precedents: only contract records the search marked `close_precedent`, at most max_precedents
      (`precedent_not_close` for others); with none left, the evidence gaps must say "no close precedent found"
      (added if missing) and the brief is flagged `no_close_precedent`;
    - market approach without a valid citation is flagged (`market_uncited`);
    - status 'complete' is lowered to 'partial' when a problem flag is raised or no risk survived.
    Returns (cleaned brief, report).
    """
    # records: record_id -> record dict ('type' plus type-specific fields such as p50_days, scored, chosen,
    # close_precedent); known: the ids the tools returned in this run, the only ones the brief may cite
    known = set(records)
    invalid: list[str] = []                    # every invalid mention, repeats included (used in citation_validity)
    flags: list[str] = []
    b = json.loads(json.dumps(brief))          # deep copy

    tl = b["timeline"]
    tl["citations"] = _clean_ids(tl.get("citations", []), known, invalid)
    refs = _timeline_refs(tl["citations"], records)    # "forecast" / "benchmark" -> the cited record to check against
    # when a scored forecast (or the chosen benchmark) exists but the brief cites none, or cites only an unscored /
    # unchosen one, the best record is cited and becomes the reference
    for kind, flag in (("forecast", "forecast_added"), ("benchmark", "benchmark_added")):
        best = [r for r in records.values() if r.get("type") == kind and (r.get("scored") if kind == "forecast" else r.get("chosen"))]
        if best and (refs[kind] is None or not (refs[kind].get("scored") or refs[kind].get("chosen"))):
            tl["citations"].append(best[0]["record_id"])
            refs[kind] = best[0]
            flags.append(flag)
    # each timeline number against its source field: no reference record -> cleared; missing or different -> copied
    for field, (kind, src) in TIMELINE_SOURCES.items():
        ref = refs[kind]
        if ref is None:
            if tl.get(field) is not None:
                flags.append("timeline_uncited")
            tl[field] = None
        # the record is the source of truth: a number the writer changed is overwritten, not just flagged
        elif tl.get(field) is None or not _equal(field, tl[field], ref.get(src)):
            if tl.get(field) is not None:
                flags.append("timeline_corrected")
            tl[field] = ref.get(src)
    forecasts = [r for r in records.values() if r.get("type") == "forecast"]
    # the forecast tool ran but could not score the package: unless a gap already mentions the forecast, one is added
    # with the reason, taken from the record's label after "...: "
    if forecasts and not any(r.get("scored") for r in forecasts):
        flags.append("forecast_unavailable")
        if not any("forecast" in str(g).lower() for g in b["evidence_gaps"]):
            b["evidence_gaps"].append("model forecast not available (" + forecasts[0].get("label", "").split(": ", 1)[-1]
                                      + "); the timeline uses the peer-group benchmark only")
    says_no_forecast = any(x in tl.get("summary", "").lower() for x in _NO_FORECAST_PHRASES)
    # three reasons to rewrite the summary: a number that no cited record (nor the package text) holds, "no forecast"
    # while a forecast median is set, or a forecast-vs-peer comparison in words
    if (unsupported_numbers(tl.get("summary", ""), [records[c] for c in tl["citations"]] + [package_text])
            or (says_no_forecast and tl.get("forecast_p50_days") is not None)
            or _COMPARISON_RE.search(tl.get("summary", ""))):
        flags.append("timeline_text_replaced")
        tl["summary"] = timeline_summary(tl, records)

    ma = b["market_approach"]
    ma["citations"] = _clean_ids(ma.get("citations", []), known, invalid)
    if not ma["citations"]:
        flags.append("market_uncited")

    risks = []
    # a risk keeps only its valid citations and is dropped when none is left
    for r in b["risks"]:
        r["citations"] = _clean_ids(r.get("citations", []), known, invalid)
        if r["citations"]:
            risks.append(r)
        else:
            flags.append("uncited_risk")
    b["risks"] = risks

    precedents, seen = [], set()
    # each precedent: unknown id -> invalid; known but not a close-precedent contract -> flagged and dropped;
    # a repeat, or one past max_precedents, is dropped without a flag
    for p in b["precedents"]:
        rid = str(p.get("record_id", "")).strip().strip("[]")
        if rid not in known:
            invalid.append(rid)
        # a real record that is not a close precedent (e.g. a contract from a supplier profile) cannot be listed as one
        elif not (rid.startswith("contract:") and records[rid].get("close_precedent")):
            flags.append("precedent_not_close")
        elif rid not in seen and len(precedents) < max_precedents:
            seen.add(rid)
            p["record_id"] = rid
            precedents.append(p)
    b["precedents"] = precedents
    if not precedents:
        flags.append("no_close_precedent")
        # case-insensitive: a gap the writer already wrote ("No close precedent found outside ...") is kept as is
        if not any(NO_PRECEDENT_GAP in str(g).lower() for g in b["evidence_gaps"]):
            # cite the similar_past_contracts tool_log record so the added gap has a source too
            log = next((r["record_id"] for r in records.values()
                        if r.get("type") == "tool_log" and r.get("tool") == "similar_past_contracts"), None)
            b["evidence_gaps"].insert(0, NO_PRECEDENT_GAP + (f" [{log}]" if log else ""))

    # ids written inside gap text are checked like any citation: known ids count as cited, unknown ones are
    # removed from the text and counted as invalid
    gap_ids: list[str] = []
    gaps = []
    for g in b["evidence_gaps"]:
        g = str(g)
        for rid in _INLINE_ID.findall(g):
            if rid in known:
                gap_ids.append(rid)
            else:
                invalid.append(rid)
                g = g.replace(rid, "")
        # tidy the brackets a removed id leaves behind ("[, x]" -> "[x]", "[]" -> "")
        gaps.append(re.sub(r"\s*\[[\s,;]*\]", "", re.sub(r"\[\s*[,;]\s*", "[", g)).strip())
    b["evidence_gaps"] = [g for g in gaps if g]

    if invalid:
        flags.append("invalid_citation")
    # repair-only flags (forecast_added, benchmark_added, forecast_unavailable) are not in _PROBLEM_FLAGS and keep 'complete'
    if b["status"] == "complete" and (_PROBLEM_FLAGS & set(flags) or not risks):
        b["status"] = "partial"
    # cited: the distinct valid ids used anywhere in the cleaned brief, gap text included
    cited = sorted(set(tl["citations"] + ma["citations"] + [c for r in risks for c in r["citations"]]
                       + [p["record_id"] for p in precedents] + gap_ids))
    # validity = valid distinct ids / (valid distinct ids + invalid mentions)
    n_cited_raw = len(cited) + len(invalid)
    report = {"invalid_citations": sorted(set(invalid)), "flags": sorted(set(flags)), "cited_ids": cited,
              "n_citations": n_cited_raw, "citation_validity": (len(cited) / n_cited_raw) if n_cited_raw else None}
    return b, report


def render_brief(brief: dict, records: dict[str, dict] | None = None) -> str:
    """Plain-text rendering of a validated brief (for display and for the groundedness judge)."""
    records = records or {}
    tl, ma = brief["timeline"], brief["market_approach"]

    def cites(ids):
        return " [" + ", ".join(ids) + "]" if ids else ""      # " [a, b]", or nothing when there is no id

    def of_type(kind):
        # the cited timeline ids of one record type, read from the record or, for an id not in records, from its prefix
        return [c for c in tl["citations"] if records.get(c, {}).get("type") == kind or c.startswith(kind + ":")]

    lines = [f"Package: {brief['package_summary']}", f"Status: {brief['status']}", "",
             f"Timeline: {tl['summary']}{cites(tl['citations'])}"]
    if tl.get("forecast_p50_days") is not None:
        slow = f"; probability of a slow tender {tl['slow_probability']:.0%}" if tl.get("slow_probability") is not None else ""
        lines.append(f"  model forecast for this package: median {tl['forecast_p50_days']:.0f} days from tender notice to "
                     f"signing (P10 {tl['forecast_p10_days']:.0f}, P90 {tl['forecast_p90_days']:.0f}){slow}"
                     f"{cites(of_type('forecast'))}")
    elif of_type("forecast"):
        lines.append(f"  model forecast: not available for this package{cites(of_type('forecast'))}")
    if tl.get("peer_p50_days") is not None:
        p90 = f"; 90th percentile {tl['peer_p90_days']:.0f} days" if tl.get("peer_p90_days") is not None else ""
        lines.append(f"  peer group: median {tl['peer_p50_days']:.0f} days{p90}{cites(of_type('benchmark'))}")
    if tl.get("forecast_p50_days") is not None and tl.get("peer_p50_days") is not None:
        lines.append("  " + compare_medians(tl["forecast_p50_days"], tl["peer_p50_days"]))
    lines += ["", f"Market approach: {ma['recommendation']}{cites(ma['citations'])}", "", "Risks and mitigations:"]
    for i, r in enumerate(brief["risks"], 1):
        lines.append(f"  {i}. {r['risk']} -> {r['mitigation']}{cites(r['citations'])}")
    lines += ["", "Similar precedents:"]
    if not brief["precedents"]:
        lines.append(f"  none ({NO_PRECEDENT_GAP})")
    for p in brief["precedents"]:
        rec = records.get(p["record_id"], {})
        label = rec.get("label", "")
        lines.append(f"  - {p['record_id']} {label}: {p['why_relevant']}")
    if brief["evidence_gaps"]:
        lines += ["", "Evidence gaps:"] + [f"  - {g}" for g in brief["evidence_gaps"]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------------------------------------

def precision_at_k(relevant: Sequence[bool | None], k: int = 5) -> float | None:
    """Share of relevant items among the first k judged items; None when nothing was judged.
    Fewer than k results count as misses (an empty slot is not a relevant precedent)."""
    judged = list(relevant)[:k]
    if not judged:
        return None
    # divide by k, not len(judged): an empty slot counts as a miss
    return sum(bool(r) for r in judged) / k


def compact(records: Sequence[dict], keep: Sequence[str], max_text: int = 400) -> list[dict]:
    """Records reduced to the given keys for the model, long strings cut to max_text characters."""
    out = []
    for r in records:
        d = {}
        for k in keep:
            v = r.get(k)
            if v is None:
                continue
            if isinstance(v, float):
                v = round(v, 3)
            if isinstance(v, str) and len(v) > max_text:
                # cut back to the last whole word within max_text and mark the cut
                v = v[:max_text].rsplit(" ", 1)[0] + " ..."
            d[k] = v
        out.append(d)
    return out


def is_close_precedent(rerank_cosine: float | None, tfidf_similarity: float, min_cosine: float, min_tfidf: float) -> bool:
    """A contract counts as a close precedent when it is near in meaning (GTE re-rank cosine) AND shares some
    vocabulary with the package (TF-IDF cosine). Either alone lets through look-alikes: 'triple packs for shipping
    infectious samples' is near 'speedboats to transport laboratory samples' in meaning but shares no words with it."""
    return rerank_cosine is not None and rerank_cosine >= min_cosine and tfidf_similarity >= min_tfidf


def precedent_rule_metrics(rows: Sequence[dict], min_cosine: float, min_tfidf: float, k: int = 5) -> dict:
    """How a precedent rule does on judged candidates, the way the tool applies it.

    rows: dicts with 'group' (package), 'rank' (re-ranked position), 'cosine', 'tfidf', 'relevant' (bool).
    Per package the first k candidates that pass the rule are taken (the tool fills up from lower ranks).
    precision = relevant taken / taken; recall = relevant taken / sum over packages of min(k, relevant candidates);
    zero_groups = packages left with no precedent."""
    # by_group: package -> its candidate rows in re-ranked order
    by_group: dict = {}
    for r in sorted(rows, key=lambda r: (str(r["group"]), r["rank"])):
        by_group.setdefault(r["group"], []).append(r)
    # taken: precedents listed; tp: relevant ones among them; cap: the most relevant ones that k slots could hold
    taken = tp = cap = 0
    zero = []
    for g, rs in by_group.items():
        keep = [r for r in rs if is_close_precedent(r["cosine"], r["tfidf"], min_cosine, min_tfidf)][:k]   # the tool's list
        taken += len(keep)
        tp += sum(bool(r["relevant"]) for r in keep)
        cap += min(k, sum(bool(r["relevant"]) for r in rs))
        if not keep:
            zero.append(g)
    return {"min_cosine": min_cosine, "min_tfidf": min_tfidf, "taken": taken, "relevant_taken": tp,
            "precision": tp / taken if taken else None, "recall": tp / cap if cap else None, "zero_groups": sorted(zero)}


def choose_precedent_rule(rows: Sequence[dict], cosine_grid: Iterable[float], tfidf_grid: Iterable[float],
                          beta: float = 0.5, k: int = 5) -> dict:
    """The (min_cosine, min_tfidf) pair with the best F-beta of precedent_rule_metrics. beta < 1 weighs precision
    over recall: a listed precedent that is not comparable misleads, a missed one only costs coverage. Ties keep
    the first (lowest) thresholds in grid order. Returns the metrics of the chosen pair with its f_beta."""
    best = None
    tfidf_grid = list(tfidf_grid)               # a list, since an iterator would be used up after the first cosine value
    for a in cosine_grid:
        for b in tfidf_grid:
            m = precedent_rule_metrics(rows, float(a), float(b), k)
            p, r = m["precision"], m["recall"]
            # F-beta = (1 + beta^2) P R / (beta^2 P + R); 0 when precision or recall is None or 0
            m["f_beta"] = (1 + beta ** 2) * p * r / (beta ** 2 * p + r) if p and r else 0.0
            # strictly better only (with a float tolerance), so ties keep the first, lowest thresholds
            if best is None or m["f_beta"] > best["f_beta"] + 1e-12:
                best = m
    return best
