"""Tender design checks: requirements read from an invitation for bids, compared with policy and with peers.

Pure Python (no Spark). Two parts:

1. extract_requirements(text, method_name) reads, with rules, what an IFB / RFB notice states about the market
   approach, bid security, lots, bid validity, electronic submission, a pre-bid meeting and qualification
   thresholds (turnover, years of experience, similar contracts).
2. check_tender_design(notice, peers) compares a notice (or a planned package) with the policy minimum
   advertising period and with peer statistics of past tenders, and returns a list of flags. Each flag names the
   rule, the value, the reference it was compared with and the peer group the reference came from, so an agent
   can cite it.
"""
from __future__ import annotations

import html
import re

# Procurement Regulations for IPF Borrowers (7th edition, September 2025): para 5.36, minimum bid preparation period
# of 30 Business Days for open international competitive procurement; Annex XII, expressions of interest normally
# no less than 10 Business Days. Calendar-day equivalents (5 business days per week, holidays ignored).
POLICY_MIN_BUSINESS_DAYS = {"international": 30, "reoi": 10}
POLICY_SOURCE = "Procurement Regulations for IPF Borrowers, 7th ed. (Sep 2025), para 5.36 / Annex XII"
MIN_PEERS = 20

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")"
ISO_CODES = ["USD", "EUR", "GBP", "KES", "TZS", "UGX", "NGN", "GHS", "ETB", "PKR", "INR", "NPR", "BDT", "LKR", "AFN", "MVR",
             "IDR", "PHP", "VND", "CNY", "RMB", "MZN", "ZMW", "MWK", "RWF", "XOF", "XAF", "MAD", "EGP", "TND", "JOD", "IQD",
             "LBP", "YER", "TRY", "UAH", "GEL", "AMD", "AZN", "KZT", "KGS", "UZS", "TJS", "MNT", "BRL", "ARS", "COP", "PEN",
             "MXN", "BOB", "HNL", "NIO", "GTQ", "DOP", "HTG", "JMD", "XCD", "LSL", "SZL", "MGA", "CDF", "SLL", "SLE", "LRD",
             "GMD", "GNF", "SDG", "SSP", "SOS", "DJF", "BIF", "MUR", "SCR", "KMF", "CVE", "AOA", "NAD", "BWP", "ZAR", "FJD",
             "PGK", "SBD", "TOP", "WST", "VUV", "KHR", "LAK", "MMK", "BTN", "IRR", "ALL", "MKD", "RSD", "BAM", "MDL", "BYN",
             "XPF", "UYU", "PYG", "CRC"]
CURRENCY_NAMES = {"shilling": None, "naira": "NGN", "cedi": "GHS", "birr": "ETB", "taka": "BDT", "rupee": None, "kwacha": None,
                  "dirham": "MAD", "dinar": None, "som": None, "tenge": "KZT", "lari": "GEL", "dram": "AMD", "hryvnia": "UAH",
                  "meticais": "MZN", "metical": "MZN", "rupiah": "IDR", "dong": "VND", "riel": "KHR", "kip": "LAK", "afghani": "AFN"}
# Currency codes are matched case-sensitively ((?-i:...)) so that 'for 3,000' or 'Lot 2' are never read as currencies.
CURRENCY = (r"(US\s?\$|U\.S\.\s?Dollars?|US\s?Dollars?|Euros?|€|£|Rs\.?|GH¢|GH₵|F\s?CFA|CFAF|"
            r"(?-i:\b(?:" + "|".join(ISO_CODES) + r")\b)|"
            r"(?:[A-Z][a-z]+\s)?(?:" + "|".join(CURRENCY_NAMES) + r")s?\b)")
AMOUNT = r"(\d{1,3}(?:[ ,.' ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(million|mn|billion|bn)?"
MONEY_RE = re.compile(CURRENCY + r"\s*" + AMOUNT + "|" + AMOUNT + r"\s*" + CURRENCY, re.I)
SECURITY_RE = re.compile(r"bid[\s-]*secur(?:ity|ities)|tender[\s-]*security|bid[\s-]*guarantee|earnest money|\bEMD\b", re.I)
DECLARATION_RE = re.compile(r"(?:bid|proposal|tender)[\s-]*securing[\s-]*declaration", re.I)
NOT_REQUIRED_RE = re.compile(r"\W{0,3}(?:is|are|shall|will)?\s*(?:be\s+)?not\s+(?:be\s+)?(?:applicable|required)", re.I)
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent|per\s?cent)", re.I)


def notice_text(raw_html: str | None) -> str:
    """Plain text of a notice's HTML: block tags become line breaks, entities are decoded, spaces collapsed."""
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", raw_html or "")
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", t).strip()


def _num(token: str) -> float:
    token = token.lower()
    return float(NUMBER_WORDS[token]) if token in NUMBER_WORDS else float(token)


def parse_amount(number: str, scale: str | None) -> float:
    """'1,500,000.00' -> 1500000.0, '25 000,00' -> 25000.0, '2.5' + 'million' -> 2500000.0."""
    s = number.replace(" ", " ").replace("'", " ")
    if re.fullmatch(r"\d{1,3}(?:[ ,.]\d{3})+(?:[.,]\d{1,2})?", s):
        head, tail = (s[:-3], s[-2:]) if re.search(r"[.,]\d{2}$", s) and not re.search(r"[ ,.]\d{3}$", s) else (s, "")
        value = float(re.sub(r"[ ,.]", "", head) + ("." + tail if tail else ""))
    else:
        value = float(s.replace(",", "."))
    mult = {"million": 1e6, "mn": 1e6, "billion": 1e9, "bn": 1e9}.get((scale or "").lower(), 1.0)
    return value * mult


def normalise_currency(token: str) -> str:
    """ISO-like code for a currency token; local names without a unique code ('Tanzania Shillings') keep their name."""
    t = token.upper().replace(" ", "").replace(".", "")
    if t in {"US$", "USD"} or "DOLLAR" in t:
        return "USD"
    if t in {"EUR", "EURO", "EUROS", "€"}:
        return "EUR"
    if t in {"RS", "INR"}:
        return "INR"
    if t in {"FCFA", "CFAF"}:
        return "XOF"
    if t in {"RMB", "CNY"}:
        return "CNY"
    name = token.lower().split()[-1].rstrip("s")
    if name in CURRENCY_NAMES:
        return CURRENCY_NAMES[name] or token.strip().title()
    return t


def money_mentions(window: str) -> list[tuple[float, str]]:
    """(amount, currency) pairs in a text window; amounts below 100 are ignored (they are lot or clause numbers)."""
    out = []
    for m in MONEY_RE.finditer(window):
        # MONEY_RE has two alternatives (currency before or after the amount); whichever matched fills its own groups
        if m.group(1):
            cur, num, scale = m.group(1), m.group(2), m.group(3)
        else:
            num, scale, cur = m.group(4), m.group(5), m.group(6)
        try:
            value = parse_amount(num, scale)
        except ValueError:
            continue
        if value >= 100:
            out.append((value, normalise_currency(cur)))
    return out


def market_approach(text: str, method_name: str | None = None) -> str | None:
    """'international' or 'national' as stated in the notice ('Open - International', 'National Competitive
    Bidding', 'NCB'); the first statement wins. None if the notice does not say."""
    pat = re.compile(r"(open[\s\-–:]*international|international[\s\-]*(?:competitive|open|competition|bidding)|\bICB\b|"
                     r"open[\s\-–:]*national|national[\s\-]*(?:competitive|open|competition|bidding)|\bNCB\b)", re.I)
    m = pat.search(text or "")
    if m:
        return "international" if re.search(r"international|ICB", m.group(0), re.I) else "national"
    if method_name and re.search(r"international", method_name, re.I):
        return "international"
    if method_name and re.search(r"national", method_name, re.I):
        return "national"
    return None


def bid_security(text: str) -> dict:
    """What the notice says about bid security.

    kind: 'percent' (a share of the bid price), 'amount' (fixed amounts; the largest is kept, a per-lot list gives
    several), 'declaration' (a bid-securing declaration instead of a guarantee), 'not_required', 'mentioned' (named
    without a value) or None (not mentioned).
    """
    text = text or ""
    out = {"kind": None, "percent": None, "amount": None, "currency": None, "n_amounts": 0}
    matches = list(SECURITY_RE.finditer(text))
    windows = [text[m.start(): m.end() + 220] for m in matches]
    # "bid security is not required" must win over any amount printed elsewhere in the notice
    if any(NOT_REQUIRED_RE.match(text, m.end()) for m in matches):
        out["kind"] = "not_required"
        return out
    if not windows:
        if DECLARATION_RE.search(text):
            out["kind"] = "declaration"
        return out
    for w in windows:
        p = PERCENT_RE.search(w[:140])
        # bid security is a small share of the bid price; a larger percentage near the phrase is something else (e.g. a
        # price preference)
        if p and 0 < float(p.group(1)) <= 10:
            out.update(kind="percent", percent=float(p.group(1)))
            return out
    amounts = [a for w in windows for a in money_mentions(w)]
    if amounts:
        # several amounts usually means one per lot; the largest is kept and the count is reported
        value, cur = max(amounts)
        out.update(kind="amount", amount=value, currency=cur, n_amounts=len({a for a, _ in amounts}))
        return out
    out["kind"] = "declaration" if DECLARATION_RE.search(text) else "mentioned"
    return out


def n_lots(text: str) -> int | None:
    """Number of lots the notice describes: the highest 'Lot N', or 'in N lots'. None if no lots are named."""
    text = text or ""
    nums = [int(x) for x in re.findall(r"\blot\s*(?:no\.?|number|#)?\s*(\d{1,3})\b", text, re.I) if 0 < int(x) < 500]
    words = [int(_num(x)) for x in re.findall(rf"\b{_NUM}\s*(?:\(\d+\)\s*)?lots\b", text, re.I)]
    found = nums + words
    return max(found) if found else None


def bid_validity_days(text: str) -> int | None:
    m = re.search(r"valid(?:ity)?\s+(?:for\s+)?(?:a\s+)?(?:period\s+of\s+)?(\d{2,3})\s*(?:\(\w+\)\s*)?(?:calendar\s+)?days",
                  text or "", re.I)
    # outside 28-365 days the number is more likely another period (e.g. a contract duration) than a bid validity
    return int(m.group(1)) if m and 28 <= int(m.group(1)) <= 365 else None


def electronic_submission(text: str) -> bool | None:
    """True if bids can or must be submitted electronically, False if the notice excludes it, None if silent."""
    text = text or ""
    if re.search(r"electronic\s+(?:bidding|submission|bids?)\s+(?:will|shall)\s+not\s+be\s+(?:permitted|allowed|accepted)", text, re.I):
        return False
    if re.search(r"e-?procurement|e-?tender|e-?GP\b|electronic(?:ally)?\s+(?:bid|submi)|submi\w*\s+(?:online|electronically)|"
                 r"online\s+(?:bid|submission)", text, re.I):
        return True
    return None


def pre_bid_meeting(text: str) -> str | None:
    m = re.search(r"pre[\s-]?bid\s+(?:meeting|conference)|pre[\s-]?proposal\s+(?:meeting|conference)", text or "", re.I)
    if not m:
        return None
    around = (text or "")[max(0, m.start() - 60): m.end() + 80]
    return "mandatory" if re.search(r"mandatory|compulsory|obligatory", around, re.I) else "held"


def qualification(text: str) -> dict:
    """Qualification thresholds stated in the notice (most notices refer to the bidding document instead)."""
    text = text or ""
    out = {"turnover_amount": None, "turnover_currency": None, "experience_years": None, "similar_contracts": None}
    for m in re.finditer(r"turnover", text, re.I):
        amounts = money_mentions(text[m.start(): m.end() + 250])
        if amounts:
            out["turnover_amount"], out["turnover_currency"] = max(amounts)
            break
    for m in re.finditer(r"experience", text, re.I):
        w = text[max(0, m.start() - 160): m.end() + 160]
        y = re.search(rf"(?:at\s+least|minimum(?:\s+of)?|not\s+less\s+than)\s+{_NUM}\s*(?:\(\d+\)\s*)?years", w, re.I) \
            or re.search(rf"\b{_NUM}\s*(?:\(\d+\)\s*)?years?\s+(?:of\s+)?(?:general\s+|specific\s+)?"
                         r"(?:construction\s+)?experience", w, re.I)
        if y and out["experience_years"] is None:
            out["experience_years"] = _num(y.group(1))
        c = re.search(rf"(?:at\s+least|minimum(?:\s+of)?)\s+{_NUM}\s*(?:\(\d+\)\s*)?(?:similar\s+)?contracts?", w, re.I)
        if c and out["similar_contracts"] is None:
            out["similar_contracts"] = _num(c.group(1))
    return out


def extract_requirements(text: str, method_name: str | None = None) -> dict:
    """All rule-based fields of one notice text (see the functions above)."""
    sec = bid_security(text)
    q = qualification(text)
    return {"market_approach": market_approach(text, method_name),
            "bid_security_kind": sec["kind"], "bid_security_percent": sec["percent"],
            "bid_security_amount": sec["amount"], "bid_security_currency": sec["currency"],
            "n_lots_stated": n_lots(text), "bid_validity_days": bid_validity_days(text),
            "electronic_submission": electronic_submission(text), "pre_bid_meeting": pre_bid_meeting(text), **q}


# ----------------------------------------------------------------------------------------------- peer statistics
def quantile(values: list[float], q: float) -> float | None:
    """Linear-interpolated quantile of a non-empty list (None for an empty one)."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    # same linear interpolation as numpy's default quantile, without needing numpy here
    pos = (len(v) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def peer_stats(values: list[float]) -> dict:
    return {"n": len([v for v in values if v is not None]), "p10": quantile(values, 0.1), "p25": quantile(values, 0.25),
            "p50": quantile(values, 0.5), "p75": quantile(values, 0.75), "p90": quantile(values, 0.9)}


def peer_lookup(peers: dict, metric: str, keys: list[tuple], min_n: int = MIN_PEERS) -> tuple[dict | None, tuple | None]:
    """The first peer group (most specific first) with at least min_n observations for the metric.

    peers: {metric: {group_key_tuple: stats_dict}}; keys: candidate group keys, e.g.
    [("country", "KE", "CW", "national"), ("region", "AFE", "CW", "national"), ("category", "CW", "national")].
    """
    table = peers.get(metric, {})
    for key in keys:
        stats = table.get(key)
        if stats and stats.get("n", 0) >= min_n:
            return stats, key
    return None, None


def policy_min_calendar_days(approach: str | None, notice_type: str = "Invitation for Bids") -> int | None:
    if notice_type == "Request for Expression of Interest":
        bd = POLICY_MIN_BUSINESS_DAYS["reoi"]
    elif approach == "international":
        bd = POLICY_MIN_BUSINESS_DAYS["international"]
    else:
        return None
    # business days to calendar days: 5 working days per 7, public holidays ignored (30 -> 42)
    return round(bd * 7 / 5)


# ----------------------------------------------------------------------------------------------- the check
def _flag(check, severity, value, reference, rule, group=None, source=None) -> dict:
    return {"check": check, "severity": severity, "value": value, "reference": reference, "rule": rule,
            "peer_group": "/".join(str(k) for k in group) if group else None, "source": source}


def peer_keys(notice: dict, approach: str | None = None) -> list[tuple]:
    """Candidate peer groups, most specific first: country, region, category (each x category x market approach).
    approach='any' builds keys for metrics whose peers have no market approach (contract values)."""
    cat, appr = notice.get("category"), approach or notice.get("market_approach") or "unknown"
    keys = []
    if notice.get("country"):
        keys.append(("country", notice["country"], cat, appr))
    if notice.get("region"):
        keys.append(("region", notice["region"], cat, appr))
    keys.append(("category", cat, appr))
    if appr != "any":
        keys.append(("category", cat, "any"))
    return keys


def check_tender_design(notice: dict, peers: dict) -> list[dict]:
    """Flags for one notice or planned package.

    notice keys (all optional except category): category (CW/GO/NC), market_approach, country, region, notice_type,
    advertising_days, avg_lot_usd (estimated or awarded value per lot), n_lots, bid_security_percent (of the bid or
    contract value), bid_validity_days, turnover_multiple (required turnover / contract value), experience_years,
    electronic_submission, pre_bid_meeting, notice_id (cited in the flags' source).
    peers: {metric: {group_key: peer_stats()}} for the metrics advertising_days, lot_size_usd, bid_security_percent,
    bid_validity_days, turnover_multiple, experience_years.

    Returns a list of flags {check, severity ('high' / 'medium' / 'info'), value, reference, rule, peer_group, source}.
    """
    flags: list[dict] = []
    src = notice.get("notice_id")
    keys = peer_keys(notice)
    adv = notice.get("advertising_days")
    if adv is not None:
        minimum = policy_min_calendar_days(notice.get("market_approach"), notice.get("notice_type", "Invitation for Bids"))
        if minimum is not None and adv < minimum:
            flags.append(_flag("advertising_below_policy_minimum", "high", adv, minimum,
                               f"advertising days < {minimum} calendar days ({POLICY_SOURCE})", source=src))
        stats, group = peer_lookup(peers, "advertising_days", keys)
        # 60% of the peer median: clearly short for its peers, not just below the middle
        if stats and adv < 0.6 * stats["p50"]:
            flags.append(_flag("advertising_short_vs_peers", "medium", adv, round(stats["p50"]),
                               "advertising days < 60% of the peer median", group, src))
    lot = notice.get("avg_lot_usd")
    if lot:
        stats, group = peer_lookup(peers, "lot_size_usd", peer_keys(notice, approach="any"))
        if stats and lot > stats["p90"]:
            flags.append(_flag("package_large_vs_market", "medium", round(lot), round(stats["p90"]),
                               "value per lot above the P90 of past contracts in the peer group", group, src))
        elif stats and lot < stats["p10"] and (notice.get("n_lots") or 1) >= 5:
            flags.append(_flag("package_fragmented", "info", round(lot), round(stats["p10"]),
                               "5+ lots each below the P10 of past contracts in the peer group", group, src))
    for metric, check, label in [("bid_security_percent", "bid_security_high_vs_peers", "bid security %"),
                                 ("bid_validity_days", "bid_validity_long_vs_peers", "bid validity days"),
                                 ("turnover_multiple", "turnover_requirement_high_vs_peers", "required turnover / contract value"),
                                 ("experience_years", "experience_requirement_high_vs_peers", "years of experience required")]:
        value = notice.get(metric)
        if value is None:
            continue
        # these metrics come from the 400-notice text sample only, so a lower minimum group size (10) is accepted
        stats, group = peer_lookup(peers, metric, keys, min_n=10)
        # the second test avoids flagging when P50 = P90 (a group where almost every notice states the same value)
        if stats and value > stats["p90"] and value > stats["p50"]:
            flags.append(_flag(check, "medium", value, stats["p90"], f"{label} above the peer P90", group, src))
    if notice.get("market_approach") == "international" and notice.get("electronic_submission") is False:
        flags.append(_flag("no_electronic_submission_international", "info", False, True,
                           "international tender that excludes electronic submission (harder for foreign bidders)", source=src))
    return flags
