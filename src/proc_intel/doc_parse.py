"""Structure-aware parsing and chunking of long project documents (PADs, ICRs).

Pure Python, no PDF library: the notebook (p12) reads the PDF with PyMuPDF and passes plain lines, spans and
table cell grids to these functions, so the rules can be tested on hand-made inputs.

Element  = one heading, paragraph line group or table of a document, in reading order.
Chunk    = what is embedded: a narrative chunk (sentences of one section) or a table chunk (a whole small table,
           or a group of rows of a large one with the header row repeated), both prefixed with a contextual header
           "<document title> > <section path> [> <table caption>]".
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

ROMAN = r"(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)"
ANNEX_RE = re.compile(r"^(?:ANNEX|Annex|APPENDIX|Appendix)\s+[0-9IVX]+[A-Z]?\b")
NUMBERED_RE = re.compile(rf"^(?P<num>{ROMAN}|[A-H]|\d{{1,2}}(?:\.\d{{1,2}}){{0,2}})[.):]?\s+(?P<title>\S.*)$")
CAPTION_RE = re.compile(r"^(?:Table|Figure|Box|Chart|Graph)\s*[A-Z]?\d+(?:\.\d+)*[A-Za-z]?\s*[:.\-–—]?\s*\S", re.I)
PAGE_RE = re.compile(r"^\s*(?:page\s*)?\d{1,3}(?:\s*(?:of|/)\s*\d{1,3})?\s*$", re.I)
DOT_LEADER = re.compile(r"(?:\.\s?){4,}|_{4,}")                  # table-of-contents leaders
TEMPLATE_CODE = re.compile(r"\b[A-Z0-9]+(?:_[A-Z0-9]+)+\b")      # Word template field codes: BASIC_INFO_TABLE
SENT_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")
TOKEN_RE = re.compile(r"[a-z]{3,}|\d+(?:[.,]\d+)*")
SMALL_WORDS = {"and", "of", "the", "for", "to", "in", "on", "a", "an", "with", "by", "or", "at", "from", "as"}
ABBREV = {"e.g", "i.e", "mr", "ms", "dr", "no", "nos", "para", "paras", "vs", "etc", "fig", "approx", "u.s", "art",
          "sec", "al", "p", "pp", "vol"}


# ----------------------------------------------------------------------------------------------- page clean-up
def running_lines(pages: list[list[str]], min_share: float = 0.3, min_pages: int = 4) -> set[str]:
    """Short lines that repeat on many pages (running headers and footers such as the project name or
    "The World Bank"), compared with digits removed so that "Page 7 of 107" matches "Page 8 of 107"."""
    counts = Counter()
    for lines in pages:
        counts.update({_digitless(line) for line in lines if 0 < len(line.strip()) <= 120})
    # at least 4 pages and 30% of them, so a short document's real lines are not taken for headers
    threshold = max(min_pages, min_share * len(pages))
    return {key for key, n in counts.items() if n >= threshold and key}


def _digitless(line: str) -> str:
    return re.sub(r"\d+", "#", " ".join(line.split()))


def is_noise_line(line: str, running: set[str]) -> bool:
    """Page numbers, running headers/footers and table-of-contents entries (dot leaders)."""
    text = " ".join(line.split())
    return (not text or bool(PAGE_RE.match(text)) or _digitless(text) in running or bool(DOT_LEADER.search(text)))


def clean_line(line: str) -> str:
    """Whitespace collapsed and Word template field codes (BASIC_INFO_TABLE, RESULT_FRAME_TBL_PDO) removed."""
    return " ".join(TEMPLATE_CODE.sub(" ", line).split())


# ----------------------------------------------------------------------------------------------- headings
def body_font_size(spans: list[tuple[float, int]]) -> float:
    """The font size that carries the most characters: (size, n_chars) pairs -> size (rounded to 0.5 pt)."""
    weight = Counter()
    for size, n_chars in spans:
        # rounded to half points: the same body font is reported as 10.0, 10.02, 9.98 ... on different lines
        weight[round(size * 2) / 2] += n_chars
    return weight.most_common(1)[0][0] if weight else 10.0


def heading_level(text: str, size: float, bold: bool, body_size: float) -> int | None:
    """1 or 2 if a line is a section heading, else None.

    A heading must look different from body text (at least 1 pt larger, or bold) AND look like a title: short,
    no sentence end, mostly capitalised words, no year or citation commas. Level 1: ANNEX / APPENDIX headings,
    Roman-numbered headings and ALL-CAPS titles; level 2: lettered or numbered sub-headings ("B. Fiduciary",
    "3.2 Procurement") and other emphasised titles.
    """
    text = " ".join(text.split())
    words = text.split()
    if not (3 <= len(text) <= 120) or len(words) > 16 or text[-1] in ".,;:" and not ANNEX_RE.match(text):
        return None
    larger = size >= body_size + 1.0
    if not (larger or bold) or not text[0].isupper() and not text[0].isdigit():
        return None
    if ANNEX_RE.match(text):
        return 1
    # a year or several commas suggest a citation or a sentence fragment, not a heading
    if re.search(r"\b(19|20)\d\d\b", text) and not NUMBERED_RE.match(text) or text.count(",") >= 2:
        return None
    if text[-1].isdigit() and not NUMBERED_RE.match(text):        # table-of-contents entry "Risks ...... 12"
        return None
    m = NUMBERED_RE.match(text)
    title = m.group("title") if m else text
    content = [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", title) if w.lower() not in SMALL_WORDS]
    if not content or sum(w[0].isupper() for w in content) < 0.6 * len(content):
        return None
    if m:
        num = m.group("num")
        # a bare number in bold is a list or paragraph number, not a heading
        if num.isdigit() and len(words) == 1:
            return None
        return 1 if re.fullmatch(ROMAN, num) else 2
    letters = [c for c in title if c.isalpha()]
    if len(letters) >= 4 and sum(c.isupper() for c in letters) >= 0.9 * len(letters):
        return 1 if larger else 2
    return 2 if len(words) >= 2 else None              # one bold word ("Total", "Annual") is a table label


def is_caption(text: str) -> bool:
    """"Table 3: Project cost by component", "Figure 2.1 - ..." (a table/figure title)."""
    return bool(CAPTION_RE.match(" ".join(text.split())))


def is_annex(section_path: list[str]) -> bool:
    return bool(section_path) and bool(ANNEX_RE.match(section_path[0]))


def assign_sections(elements: list[dict]) -> list[dict]:
    """Give every element the path of headings above it (level 1, level 2) and a section id.

    Elements are dicts with at least 'kind' ('heading', 'text', 'table') and, for headings, 'level' and 'text'.
    Returns new dicts with 'section_path' (list of str), 'section_id' (stable hash) and 'is_annex'.
    """
    path: list[str] = []
    out = []
    for el in elements:
        if el["kind"] == "heading":
            level = el.get("level", 1)
            # a level-1 heading starts a new path; a level-2 heading replaces only the second part
            path = [el["text"]] if level == 1 or not path else [path[0], el["text"]]
        sp = list(path) or ["Front matter"]
        out.append({**el, "section_path": sp, "section_id": short_hash(" > ".join(sp)), "is_annex": is_annex(sp)})
    return out


def short_hash(text: str, n: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


# ----------------------------------------------------------------------------------------------- tables
def clean_cell(cell) -> str:
    return " ".join(str(cell).split()) if cell is not None else ""


def clean_table(grid: list[list]) -> list[list[str]]:
    """Cell text with whitespace collapsed; empty rows and empty columns removed. None (a merged cell) -> ''."""
    rows = [[clean_cell(c) for c in row] for row in grid]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any(r[j] for r in rows)]
    return [[r[j] for j in keep] for r in rows]


def table_quality(rows: list[list[str]]) -> dict:
    """Shape and fill of a cleaned table, used to tell real tables from layout boxes."""
    n_rows, n_cols = len(rows), (len(rows[0]) if rows else 0)
    cells = n_rows * n_cols
    filled = sum(1 for r in rows for c in r if c)
    words = sum(len(c.split()) for r in rows for c in r)
    longest = max((len(c.split()) for r in rows for c in r), default=0)
    return {"n_rows": n_rows, "n_cols": n_cols, "fill": filled / cells if cells else 0.0, "n_words": words,
            "longest_cell_words": longest}


def is_data_table(q: dict, min_rows: int = 2, min_cols: int = 2, min_fill: float = 0.4) -> bool:
    """A real table: at least 2 x 2, at least 40% of cells filled, and not one big text box drawn as a frame
    (a 'table' whose cells hold whole paragraphs is prose in a box)."""
    filled = max(1, round(q["fill"] * q["n_rows"] * q["n_cols"]))
    # over 40 words per filled cell in a one- or two-column frame is a paragraph drawn in a box
    prose_box = q["n_cols"] <= 2 and q["n_words"] / filled > 40
    return (q["n_rows"] >= min_rows and q["n_cols"] >= min_cols and q["fill"] >= min_fill
            and q["longest_cell_words"] <= 120 and not prose_box)


def header_rows(rows: list[list[str]]) -> int:
    """Number of header rows: the first row, plus a second one when the first has merged (empty) cells and the
    second holds no numbers (a two-line header such as 'Cost' over 'IDA | Government')."""
    if len(rows) < 3:
        return 1
    first, second = rows[0], rows[1]
    has_number = any(re.search(r"\d", c) for c in second[1:])
    return 2 if ("" in first and not has_number and sum(1 for c in second if c) >= 2) else 1


def table_markdown(header: list[list[str]], body: list[list[str]]) -> str:
    """Markdown table; a multi-row header is joined column-wise ('Cost / IDA')."""
    width = len((header or body)[0])
    head = [" / ".join(h[j] for h in header if h[j]) or f"col{j + 1}" for j in range(width)]
    def esc(c):
        return c.replace("|", "/")
    lines = ["| " + " | ".join(esc(c) for c in head) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(esc(c) for c in r) + " |" for r in body]
    return "\n".join(lines)


def table_chunks(rows: list[list[str]], max_words: int = 300) -> list[dict]:
    """One chunk for a table that fits in max_words; otherwise groups of consecutive rows, each with the header
    repeated, never cutting a row. Returns dicts with 'text' (markdown), 'row_start', 'row_end' (body row
    indexes, end exclusive)."""
    n_head = header_rows(rows)
    header, body = rows[:n_head], rows[n_head:]
    if not body:
        return [{"text": table_markdown(header, []), "row_start": 0, "row_end": 0}]
    head_words = sum(len(c.split()) for r in header for c in r)
    groups, cur, cur_words = [], [], head_words
    for i, r in enumerate(body):
        # + len(r): each cell also costs a separator, so wide rows of short numbers are not undercounted
        w = sum(len(c.split()) for c in r) + len(r)
        if cur and cur_words + w > max_words:
            groups.append(cur)
            cur, cur_words = [], head_words
        cur.append(i)
        cur_words += w
    groups.append(cur)
    return [{"text": table_markdown(header, [body[i] for i in g]), "row_start": g[0], "row_end": g[-1] + 1}
            for g in groups]


# ----------------------------------------------------------------------------------------------- narrative
def split_sentences(par: str) -> list[str]:
    parts, start = [], 0
    for m in SENT_END.finditer(par):
        prev = par[start:m.start()].rsplit(" ", 1)[-1].rstrip(".!?\"')]").lower()
        # no split after "e.g.", "para." or an initial ("J. Smith"): those full stops do not end a sentence
        if prev in ABBREV or (len(prev) == 1 and prev.isalpha()):
            continue
        parts.append(par[start:m.start()].strip())
        start = m.end()
    parts.append(par[start:].strip())
    out: list[str] = []
    for p in parts:
        if out and len(out[-1].split()) <= 2:          # "116." paragraph numbers glue to the next sentence
            out[-1] = out[-1] + " " + p
        elif p:
            out.append(p)
    return out


def pack_sentences(sentences: list[str], target_words: int = 260, max_words: int = 320,
                   overlap_words: int = 40) -> list[str]:
    """Pack sentences into chunks of about target_words, never cutting a sentence (a single sentence longer than
    max_words is cut into target_words pieces); each chunk after the first starts with the last ~overlap_words of
    whole sentences of the previous one."""
    units: list[str] = []
    for s in sentences:
        w = s.split()
        units += [s] if len(w) <= max_words else [" ".join(w[i:i + target_words]) for i in range(0, len(w), target_words)]
    chunks, cur, n_new = [], [], 0
    for u in units:
        uw = len(u.split())
        if n_new and sum(len(x.split()) for x in cur) + uw > max_words:
            chunks.append(" ".join(cur))
            keep, kw = [], 0
            # overlap: carry the last whole sentences (about overlap_words, at most twice that) into the next chunk
            for x in reversed(cur):
                if kw + len(x.split()) > 2 * overlap_words:
                    break
                keep.insert(0, x)
                kw += len(x.split())
                if kw >= overlap_words:
                    break
            cur, n_new = keep, 0
        cur.append(u)
        n_new += 1
        if sum(len(x.split()) for x in cur) >= target_words:
            chunks.append(" ".join(cur))
            cur, n_new = [], 0
    if n_new:
        chunks.append(" ".join(cur))
    return chunks


def context_header(doc_title: str, section_path: list[str], caption: str | None = None) -> str:
    parts = [doc_title] + [p for p in section_path if p != "Front matter"] + ([caption] if caption else [])
    return " > ".join(parts)


def build_chunks(elements: list[dict], doc_title: str, target_words: int = 260, max_words: int = 320,
                 table_max_words: int = 300) -> list[dict]:
    """Structure-aware chunks from section-assigned elements (see assign_sections).

    Narrative: consecutive 'text' elements of one section are joined, split into sentences and packed; a chunk
    never spans two sections. Tables: table_chunks() per table, captioned. Every chunk carries the contextual
    header (also prepended to its embed_text), its section path and id (the parent for parent-child retrieval),
    the annex flag and the pages it covers.
    """
    chunks: list[dict] = []
    buf: list[dict] = []

    def flush():
        if not buf:
            return
        text = " ".join(e["text"] for e in buf)
        text = re.sub(r"(\w)- (\w)", r"\1\2", text)
        first = buf[0]
        for piece in pack_sentences(split_sentences(text), target_words, max_words):
            # fragments under 8 words (stray labels, page furniture) carry nothing worth retrieving
            if len(piece.split()) < 8:
                continue
            chunks.append(_chunk("narrative", piece, first, doc_title, None, [e["page"] for e in buf]))
        buf.clear()

    for el in elements:
        if el["kind"] == "text":
            if buf and buf[-1]["section_id"] != el["section_id"]:
                flush()
            buf.append(el)
        elif el["kind"] == "heading":
            flush()
        elif el["kind"] == "table":
            flush()
            for part in table_chunks(el["rows"], table_max_words):
                c = _chunk("table", part["text"], el, doc_title, el.get("caption"), [el["page"]])
                c.update(table_id=el["table_id"], row_start=part["row_start"], row_end=part["row_end"])
                chunks.append(c)
    flush()
    return chunks


def _chunk(kind: str, text: str, el: dict, doc_title: str, caption: str | None, pages: list[int]) -> dict:
    header = context_header(doc_title, el["section_path"], caption)
    # the header is embedded with the text (the p12 ablation shows retrieval depends on it) but kept separate for
    # display
    return {"chunk_type": kind, "text": text, "context_header": header, "embed_text": f"{header}\n{text}",
            "section_path": " > ".join(el["section_path"]), "section_id": el["section_id"], "is_annex": el["is_annex"],
            "page_start": min(pages), "page_end": max(pages), "n_words": len(text.split()),
            "table_id": None, "row_start": None, "row_end": None}


# ----------------------------------------------------------------------------------------------- old-vs-new check
def row_tokens(row: list[str]) -> set[str]:
    """Distinctive tokens of a table row: words of 3+ letters and numbers, lower case."""
    return set(TOKEN_RE.findall(" ".join(row).lower()))


def distinctive_tokens(tokens: set[str], chunk_tokens: list[set[str]], max_df: int = 3) -> set[str]:
    """Tokens that occur in at most max_df of the chunks (or in none): the words and numbers that identify a row,
    unlike 'procurement' or '2021', which occur everywhere and would match by chance."""
    return {t for t in tokens if sum(t in ct for ct in chunk_tokens) <= max_df}


def locate_row(tokens: set[str], chunk_tokens: list[set[str]], min_share: float = 0.9, min_tokens: int = 3) -> str:
    """Where a table row ended up in a set of chunks: 'intact' (one chunk holds >= 90% of its tokens), 'split'
    (only the union of chunks does) or 'missing' (dropped). Rows with fewer than min_tokens tokens are 'trivial'.
    Pass the row's distinctive_tokens() for a strict test."""
    if len(tokens) < min_tokens:
        return "trivial"
    best = max((len(tokens & ct) for ct in chunk_tokens), default=0)
    if best >= min_share * len(tokens):
        return "intact"
    union = set().union(*chunk_tokens) if chunk_tokens else set()
    return "split" if len(tokens & union) >= min_share * len(tokens) else "missing"


def answer_in(answer: str, text: str) -> bool:
    """Is a short answer string in a chunk? Whitespace and case are ignored."""
    def norm(s):
        return " ".join(s.lower().split())
    return norm(answer) in norm(text)
