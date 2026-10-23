"""Turning completion reports (ICRs) into procurement-relevant lesson chunks.

An Implementation Completion and Results Report is long (often 50-100 pages) and mostly about outcomes.
The agent needs the passages about how procurement and implementation went and what was learned:
"Key factors that affected implementation", "Fiduciary compliance / Procurement", "Lessons and
recommendations". So the text is split into sections by its headings, cut into ~220-word chunks along
paragraph and sentence boundaries, and only chunks that are procurement-relevant are kept:

- the chunk sits in a lessons / procurement / fiduciary / implementation-factor section and mentions at least
  one procurement or implementation word, or
- anywhere in the report, it mentions at least three distinct procurement words.
Tables, contents pages and lists (few lower-case words) are dropped.
"""
from __future__ import annotations

import re
from collections import Counter

TARGET_WORDS = 220
MAX_WORDS = 320
MIN_WORDS = 40
PROSE_MIN = 0.45

_ROMAN = r"(?:X{0,3})(?:IX|IV|V?I{0,3})"
_NUMBERED = re.compile(rf"^(?:(?P<num>{_ROMAN}|[A-H]|\d{{1,2}})[.)]|(?P<dotted>\d{{1,2}}(?:\.\d{{1,2}})+)\.?)\s+"
                       rf"(?P<title>[A-Za-z].*)$")
_PAGE = re.compile(r"^(page\s*)?\d{1,3}(\s*(of|/)\s*\d{1,3})?$", re.I)
_WS = re.compile(r"[ \t ]+")
_SENT_END = re.compile(r"(?<=[a-z0-9)%][.!?])\s+(?=[A-Z(])")
_DOTS = re.compile(r"\.{4,}\s*\d*")

FOCUS_SECTIONS = re.compile(r"LESSON|PROCUREMENT|FIDUCIAR|KEY FACTORS|IMPLEMENTATION|RISK TO DEVELOPMENT|"
                            r"BANK PERFORMANCE|COMPLIANCE", re.I)
NOT_FOCUS = re.compile(r"M&E|MONITORING AND EVALUATION|RESULTS FRAMEWORK", re.I)    # inside section IV, not procurement
PROCUREMENT_WORDS = ("procurement", "procure", "bidding", "bidder", "bids", "tender", "contractor", "contract award",
                     "contract management", "supplier", "consultant", "prior review", "procurement plan", "step",
                     "evaluation committee", "re-bid", "rebid", "price escalation", "variation order", "civil works",
                     "fiduciary", "single-source", "direct contracting", "no objection", "framework agreement")
IMPLEMENTATION_WORDS = ("delay", "implementation", "capacity", "slow", "late", "disburse", "supervision", "pmu", "piu",
                        "implementing agency", "contract")


_SMALL = {"and", "of", "the", "for", "to", "in", "on", "&", "a", "an", "by", "with", "at"}


def heading(line: str) -> tuple[int, str] | None:
    """(level, text) if the line looks like a section heading.

    Level 1: Roman-numbered ('V. LESSONS AND RECOMMENDATIONS'), 'ANNEX 3 ...', or an all-capitals line of 2-12
    words. Level 2: letter / digit numbered title ('B. Fiduciary Compliance', '3.2 Procurement') or a short
    title-case line of 1-6 words without a final full stop ('Procurement', 'Financial Management').
    """
    s = line.strip()
    if len(s) < 4 or len(s) > 110 or s.endswith((",", ";", ":")) or _DOTS.search(s):
        return None
    words = s.split()
    if re.match(r"^ANNEX\s+\d+", s, re.I) and len(words) <= 14:
        return 1, s
    m = _NUMBERED.match(s)
    if m and (m.group("num") or m.group("dotted")) and len(words) <= 14 and not m.group("title").rstrip().endswith("."):
        title = m.group("title")
        tw = [w for w in title.split() if w.lower() not in _SMALL]
        # numbered paragraphs ("86. The concerned agencies were ...") are prose: a heading is mostly capitalised, no commas
        num = m.group("num")
        caps = [c for c in title if c.isalpha()]
        all_caps = sum(c.isupper() for c in caps) >= 0.9 * max(1, len(caps))
        if not (num and not num.isdigit() and all_caps) and \
                ("," in title or sum(w[:1].isupper() for w in tw) < 0.6 * max(1, len(tw))):
            return None
        return (1 if num and re.fullmatch(_ROMAN, num) else 2), s
    letters = [c for c in s if c.isalpha()]
    if 2 <= len(words) <= 12 and len(letters) >= 0.7 * len(s.replace(" ", "")) and \
            sum(c.isupper() for c in letters) >= 0.9 * len(letters):
        return 1, s
    if 1 <= len(words) <= 6 and not s.endswith(".") and s[0].isupper() and \
            all(w[0].isupper() or w.lower() in {"and", "of", "the", "for", "to", "in", "on", "&"} for w in words) and \
            not any(ch.isdigit() for ch in s):
        return 2, s
    return None


def decode_report(data: bytes) -> str:
    """Report text files are mostly UTF-8, some Windows-1252 (curly quotes become '�' when forced to UTF-8)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def prose_ratio(text: str) -> float:
    toks = text.split()
    return sum(t[:1].islower() for t in toks) / max(1, len(toks))


def _sentences(par: str) -> list[str]:
    return [p.strip() for p in _SENT_END.split(par) if p.strip()]


def paragraphs_with_sections(raw: str) -> list[tuple[str, str]]:
    """[(section path, paragraph text)] in reading order. Section path = 'LEVEL1 > Level2'."""
    lines = [_WS.sub(" ", l).strip() for l in raw.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n").split("\n")]
    counts = Counter(l for l in lines if l and len(l) <= 120)
    repeated = {l for l, c in counts.items() if c >= 4}            # running headers / footers
    sec1, sec2 = None, None
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def section() -> str:
        return (f"{sec1} > {sec2}" if sec1 and sec2 else (sec1 or sec2 or "Front matter"))[:160]

    def flush():
        if buf:
            par = re.sub(r"(\w)- (\w)", r"\1\2", " ".join(buf))
            out.append((section(), par))
            buf.clear()

    for l in lines:
        if not l:
            flush()
            continue
        if _PAGE.match(l) or l in repeated:
            continue
        h = heading(l)
        if h and not buf:
            flush()
            if h[0] == 1:
                sec1, sec2 = h[1], None
            else:
                sec2 = h[1]
            continue
        if h and buf and h[0] == 1:
            flush()
            sec1, sec2 = h[1], None
            continue
        buf.append(l)
    flush()
    return out


def chunk_report(raw: str, target: int = TARGET_WORDS, max_words: int = MAX_WORDS) -> list[dict]:
    """Chunks of about `target` words that never cross a section boundary: [{section, text, n_words}]."""
    chunks: list[dict] = []
    cur: list[str] = []
    cur_sec = None

    def emit():
        nonlocal cur
        if cur:
            text = " ".join(cur)
            chunks.append({"section": cur_sec, "text": text, "n_words": len(text.split())})
        cur = []

    for sec, par in paragraphs_with_sections(raw):
        if sec != cur_sec:
            emit()
            cur_sec = sec
        pieces = [par] if len(par.split()) <= max_words else _sentences(par)
        for piece in pieces:
            words = piece.split()
            if len(words) > max_words:                             # one huge 'sentence' (a flattened table)
                pieces_w = [" ".join(words[i:i + target]) for i in range(0, len(words), target)]
            else:
                pieces_w = [piece]
            for p in pieces_w:
                n_cur = sum(len(c.split()) for c in cur)
                if cur and n_cur + len(p.split()) > max_words:
                    emit()
                cur.append(p)
                if sum(len(c.split()) for c in cur) >= target:
                    emit()
    emit()
    return chunks


def _hits(text: str, words: tuple[str, ...]) -> set[str]:
    t = " " + text.lower() + " "
    return {w for w in words if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t)}


def relevance(section: str, text: str) -> tuple[bool, int]:
    """(keep, score). score = distinct procurement words (+2 in a focus section) for ranking within a report."""
    if len(text.split()) < MIN_WORDS or prose_ratio(text) < PROSE_MIN:
        return False, 0
    proc = _hits(text, PROCUREMENT_WORDS)
    impl = _hits(text, IMPLEMENTATION_WORDS)
    focus = bool(FOCUS_SECTIONS.search(section or "")) and not NOT_FOCUS.search(section or "")
    keep = (focus and (len(proc) >= 1 or len(impl) >= 2)) or len(proc) >= 3 or \
           (focus and re.search(r"LESSON", section or "", re.I) is not None)
    return keep, len(proc) + (2 if focus else 0)


def lesson_chunks(raw: str, max_per_doc: int = 60) -> list[dict]:
    """Procurement-relevant chunks of one report, best-scoring first up to max_per_doc, then back in reading
    order: [{chunk_index, section, text, n_words, score}] (chunk_index = position in the full report)."""
    scored = []
    for i, c in enumerate(chunk_report(raw)):
        keep, score = relevance(c["section"], c["text"])
        if keep:
            scored.append({**c, "chunk_index": i, "score": score})
    scored.sort(key=lambda c: (-c["score"], c["chunk_index"]))
    return sorted(scored[:max_per_doc], key=lambda c: c["chunk_index"])
