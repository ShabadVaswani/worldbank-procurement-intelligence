# Databricks notebook source
# MAGIC %md
# MAGIC # p12_document_parsing — structure-aware parsing and chunking of long project reports
# MAGIC
# MAGIC Project Appraisal Documents (PADs) and completion reports run to 60-140 pages: a datasheet, numbered narrative sections, a results framework, and annexes full of tables (costs, procurement thresholds, procurement packages, risk matrices). The document chunks reused from the outcome project were cut from the **plain-text rendering** by sentence packing, and chunks that looked like tables were filtered out. This notebook parses the **PDF layout** of 10 real PADs instead, keeps headings, annexes and tables as structure, and measures what the plain-text chunks lost on the same documents.

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <pre class="mermaid">
# MAGIC ---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC ---
# MAGIC flowchart TD
# MAGIC     api["Documents API (pdfurl)"]
# MAGIC     pdf["PDF in volume"]
# MAGIC     lay["PyMuPDF layout: text lines with font size / bold, ruled tables"]
# MAGIC     hd["running headers, page numbers, contents lines dropped<br/>headings to section path (level 1 / 2), annex flag"]
# MAGIC     tb["tables: cells cleaned, quality gate, caption attached,<br/>continued tables merged across page breaks"]
# MAGIC     el["proc_silver.doc_elements<br/>(heading / text / table, in reading order, with section path and page)"]
# MAGIC     nc["narrative chunks<br/>(sentences of ONE section)"]
# MAGIC     tc["table chunks<br/>(whole table, or row groups with the header repeated)"]
# MAGIC     hdr["each prefixed by a contextual header<br/>project > section > sub-section [> table caption]"]
# MAGIC     out["proc_silver.doc_chunks_v2<br/>(+ GTE embedding; section_id = parent for parent-child retrieval)"]
# MAGIC     api --> pdf --> lay --> hd --> tb --> el
# MAGIC     el --> nc --> hdr
# MAGIC     el --> tc --> hdr
# MAGIC     hdr --> out
# MAGIC </pre>
# MAGIC <script type="module">
# MAGIC   import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.esm.min.mjs";
# MAGIC   import elkLayouts from "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.1.7/dist/mermaid-layout-elk.esm.min.mjs";
# MAGIC   mermaid.registerLayoutLoaders(elkLayouts);
# MAGIC   mermaid.initialize({ startOnLoad: true });
# MAGIC </script>

# COMMAND ----------

# MAGIC %md
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_bronze.parsed_documents` | one PDF read: source URL, pages, tables found and kept, pages without a text layer | `doc_id` |
# MAGIC | `proc_silver.doc_elements` | one heading, text block or table of a document, in reading order | `doc_id, element_index` |
# MAGIC | `proc_silver.doc_chunks_v2` | one retrievable chunk (narrative or table) with its section path, pages and embedding | `chunk_id` |
# MAGIC
# MAGIC The pure rules (headings, section paths, table cleaning and quality, row-group chunking, sentence packing, the old-vs-new row check) are in `src/proc_intel/doc_parse.py`, tested in `tests/test_doc_parse.py`; only the PyMuPDF calls live here.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key design decisions
# MAGIC
# MAGIC | Decision | Rationale | Evidence |
# MAGIC |---|---|---|
# MAGIC | PyMuPDF, pinned; headings from typography (at least 1 pt above the body font, or bold, and title-like; level 1 for ANNEX / Roman-numbered / all-caps, level 2 for "B. Fiduciary"-style); OCR as the documented fallback for scanned reports | No PDF library is installed and no bookmarks exist; PyMuPDF gives font size, bold flags and `find_tables()` without heavy models | PyMuPDF, pdfplumber, pypdf and camelot are all missing on DBR 18 ML; PyMuPDF installs from a wheel in seconds; none of the 10 PADs carries PDF bookmarks; section 2 counts pages without a text layer |
# MAGIC | "lines" table strategy plus a quality gate (at least 2 x 2 after removing empty rows and columns, 40% of cells filled, no paragraph-sized cells in a two-column frame); tables split by a page break merged, repeated header row dropped | The "text" strategy over-detects; "lines" also catches layout frames | On the first PAD the text strategy turned every page of prose into a 40-row "table"; the lines strategy found the real tables but also the datasheet box, acronym lists and framed paragraphs |
# MAGIC | Dot-leader lines dropped as contents entries; an un-numbered bold heading needs 2+ words and a capital first letter; template codes removed; one document's section tree printed in section 3 | Initial heading rules were too generous | Contents lines ("III. IMPLEMENTATION ARRANGEMENTS ......"), single bold table labels ("Total", "Annual") and Word template codes (`BASIC_INFO_TABLE`, `RESULT_FRAME_TBL_PDO`) appeared as headings |
# MAGIC | Table rows identified by distinctive tokens (in at most 3 of the document's old chunks): intact = one old chunk holds 90%; split = only several chunks together; missing = dropped; ordinary narrative sentences as a control | Matching on all words labels almost every row "intact" | Words like "procurement" or "2021" occur in every chunk |
# MAGIC
# MAGIC Full reasoning: docs/decision_log.md

# COMMAND ----------

# MAGIC %pip install -q pymupdf==1.24.10

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

# MAGIC %md
# MAGIC ## Settings
# MAGIC
# MAGIC **What:** sample size, folders, table names, chunk sizes, the embedding endpoint.
# MAGIC
# MAGIC **Why:** chunk sizes match the old chunker (260-word target, 320 maximum; about 350-430 GTE tokens) so that the comparison measures structure, not size. PDFs are kept in the bronze volume; a re-run reads them from there.

# COMMAND ----------

import collections
import json
import random
import re
import threading
import time

import fitz
import numpy as np
import requests
from pyspark.sql import Window

from proc_intel import doc_parse as dp

N_DOCS, PER_REGION = 10, 2
PARSER_VERSION = "p12-v1"
# same sizes as the old chunker, so the comparison in section 5 measures structure, not chunk size
TARGET_WORDS, MAX_WORDS, TABLE_MAX_WORDS = 260, 320, 300
DOCS_URL = "https://search.worldbank.org/api/v3/wds"
PDF_DIR = f"{RAW_VOLUME}/doc_parse/pdf"
PARSED_TABLE = f"{BRONZE}.parsed_documents"
ELEMENTS_TABLE = f"{SILVER}.doc_elements"
CHUNKS_TABLE = f"{SILVER}.doc_chunks_v2"
OLD_CHUNKS = RAG_CHUNKS                                   # outcome project, read only
EMBED_ENDPOINT = "databricks-gte-large-en"
os.makedirs(PDF_DIR, exist_ok=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The documents: 10 PADs that the old chunks already cover
# MAGIC
# MAGIC **What:** PADs in `silver.rag_chunks` approved FY2018 or later, with at least 30,000 words (about 100 pages) and a procurement plan mentioned, in hash order of the document id, at most 2 per region; their PDFs are downloaded once from the Documents API (`pdfurl`).
# MAGIC
# MAGIC **Why:** the same documents exist in the old chunk table, so old and new chunking can be compared on identical content. FY2018+ PADs follow the current template (datasheet, numbered sections, procurement annex under the 2016 Procurement Framework).

# COMMAND ----------

old = spark.table(OLD_CHUNKS).filter("doc_type = 'Project Appraisal Document'")
per_doc = (old.groupBy("doc_id", "project_id", "project_name", "region", "approval_fy")
           .agg(F.count("*").alias("old_chunks"), F.sum("n_words").alias("old_words"),
                F.max(F.lower("chunk_text").contains("procurement plan").cast("int")).alias("mentions_pp")))
# FY2018+ PADs follow the current template; 30,000+ words is roughly 100 pages, the long reports this is about
cand = per_doc.filter("approval_fy >= 2018 AND old_words >= 30000 AND mentions_pp = 1")
docs = (cand.withColumn("_r", F.row_number().over(Window.partitionBy("region").orderBy(F.sha2("doc_id", 256))))
        # at most 2 per region so ten documents are not all from one template variant
        .filter(f"_r <= {PER_REGION}").orderBy(F.sha2("doc_id", 256)).limit(N_DOCS).drop("_r", "mentions_pp").toPandas())
print(f"candidate PADs: {cand.count()}; selected: {len(docs)}")
display(docs)

# COMMAND ----------

HTTP = requests.Session()


def fetch_pdf(doc_id: str) -> dict:
    """The PDF of a document, downloaded once into the volume (the Documents API gives its pdfurl)."""
    path = f"{PDF_DIR}/{doc_id}.pdf"
    meta = HTTP.get(DOCS_URL, params={"format": "json", "id": doc_id, "fl": "id,pdfurl"}, timeout=60).json()
    url = next(iter(v for k, v in meta["documents"].items() if k != "facets")).get("pdfurl", "").replace("http://", "https://")
    # PDFs are downloaded once; a re-run parses the copy in the volume
    if not os.path.exists(path):
        resp = HTTP.get(url, timeout=300)
        resp.raise_for_status()
        with open(path, "wb") as f:
            f.write(resp.content)
    return {"doc_id": doc_id, "pdf_url": url, "file_path": path, "bytes": os.path.getsize(path)}


files = {d: fetch_pdf(d) for d in docs.doc_id}
print(f"{len(files)} PDFs, {sum(f['bytes'] for f in files.values()) / 1e6:.1f} MB")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Layout parsing: elements in reading order
# MAGIC
# MAGIC **What:** `extract_elements()` reads each page with PyMuPDF:
# MAGIC 1. text lines with their largest font size and whether 60%+ of their characters are bold; the body font size is the size that carries the most characters in the document;
# MAGIC 2. ruled tables (`find_tables()`), cleaned and passed through the quality gate; lines inside a kept table are not repeated as text;
# MAGIC 3. running headers/footers (short lines on 30%+ of pages, digits ignored), page numbers and contents lines are dropped;
# MAGIC 4. each remaining line becomes a heading (`dp.heading_level`), a caption ("Table A4.3: ..."), or text joined with the other lines of its PyMuPDF block; a heading wrapped over two lines is joined;
# MAGIC 5. a table takes the caption printed just above it (within 80 pt), and a table continued on the next page is merged into the previous one.
# MAGIC
# MAGIC Pages with fewer than 50 characters of text but with images are counted as `pages_without_text` (a scanned page would need OCR).
# MAGIC
# MAGIC **Why:** the PDF knows what the plain text forgets: which line is a heading (font), where a table's cells are (ruling lines) and which caption belongs to it (position).

# COMMAND ----------

def page_lines(page) -> list[dict]:
    """Text lines of a page with font size, bold share and position (PyMuPDF 'dict' layout)."""
    out = []
    for b in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
        for ln in b.get("lines", []):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            n = sum(len(s["text"].strip()) for s in spans)
            # flag bit 16 is PyMuPDF's bold flag; some fonts only say "Bold" in their name, so both are checked
            bold = sum(len(s["text"].strip()) for s in spans if s["flags"] & 16 or "Bold" in s["font"]) >= 0.6 * n
            out.append({"text": dp.clean_line("".join(s["text"] for s in ln["spans"])), "size": max(s["size"] for s in spans),
                        "bold": bold, "bbox": ln["bbox"], "block": b["number"], "chars": n})
    return [l for l in out if l["text"]]


# a line belongs to a table when its centre lies inside the table box (2 pt slack for rounding)
def _inside(bbox, rect, pad=2) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return rect[0] - pad <= cx <= rect[2] + pad and rect[1] - pad <= cy <= rect[3] + pad


def extract_elements(doc, doc_id: str) -> tuple[list[dict], dict]:
    pages = [page_lines(p) for p in doc]
    running = dp.running_lines([[l["text"] for l in ls] for ls in pages])
    body = dp.body_font_size([(l["size"], l["chars"]) for ls in pages for l in ls])
    elements, prev_table = [], None
    stats = collections.Counter(pages=doc.page_count)
    for pno, page in enumerate(doc, start=1):
        # almost no text but an image: probably a scanned page that would need OCR; counted, not parsed
        if sum(l["chars"] for l in pages[pno - 1]) < 50 and page.get_images():
            stats["pages_without_text"] += 1
        tables = []
        for t in page.find_tables().tables:
            stats["tables_found"] += 1
            rows = dp.clean_table(t.extract())
            q = dp.table_quality(rows)
            # quality gate: the "lines" detector also returns layout frames (datasheet boxes, two-column text) that are
            # not tables
            if dp.is_data_table(q):
                tables.append({"bbox": t.bbox, "rows": rows, "q": q})
        items = [("line", l["bbox"][1], l) for l in pages[pno - 1]
                 # lines inside a kept table are skipped, or the table's text would appear twice (as table and as prose)
                 if not dp.is_noise_line(l["text"], running) and not any(_inside(l["bbox"], t["bbox"]) for t in tables)]
        items += [("table", t["bbox"][1], t) for t in tables]
        cur = None
        # lines and tables in one stream ordered by their top edge: reading order for single-column pages
        for kind, _, it in sorted(items, key=lambda x: x[1]):
            if kind == "table":
                cur = None
                # a caption counts only if it is printed just above the table (within 80 pt on the same page)
                caps = [e for e in elements[-4:] if e["kind"] == "caption" and e["page"] == pno
                        and 0 <= it["bbox"][1] - e["y1"] <= 80]
                caption = caps[-1]["text"] if caps else None
                # continuation: same column count, at the top of the next page, nothing in between and no caption of its
                # own
                if (prev_table is not None and elements and elements[-1] is prev_table and prev_table["page"] == pno - 1
                        and prev_table["n_cols"] == it["q"]["n_cols"] and it["bbox"][1] < 0.2 * page.rect.height and not caption):
                    # a repeated header row on the continued page is dropped
                    rows = it["rows"][1:] if it["rows"][0] == prev_table["rows"][0] else it["rows"]
                    prev_table.update(rows=prev_table["rows"] + rows, n_rows=len(prev_table["rows"]) + len(rows), continued=True)
                    stats["tables_merged_across_pages"] += 1
                    continue
                prev_table = {"kind": "table", "page": pno, "rows": it["rows"], "caption": caption, "y1": it["bbox"][3],
                              "n_rows": it["q"]["n_rows"], "n_cols": it["q"]["n_cols"], "continued": False}
                elements.append(prev_table)
                continue
            text, level = it["text"], dp.heading_level(it["text"], it["size"], it["bold"], body)
            if dp.is_caption(text) and len(text.split()) <= 25:
                elements.append({"kind": "caption", "page": pno, "text": text, "y1": it["bbox"][3]})
                cur = None
            elif level:
                last = elements[-1] if elements else None
                if (cur is None and last and last["kind"] == "heading" and last["page"] == pno and last["level"] == level
                        and it["bbox"][1] - last["y1"] < 1.6 * it["size"]):
                    last["text"] += " " + text                                  # a heading wrapped over two lines
                    last["y1"] = it["bbox"][3]
                else:
                    elements.append({"kind": "heading", "page": pno, "text": text, "level": level, "y1": it["bbox"][3]})
                cur = None
            elif cur is not None and cur["block"] == it["block"]:
                cur["text"] += " " + text
            else:
                cur = {"kind": "text", "page": pno, "text": text, "block": it["block"], "y1": it["bbox"][3]}
                elements.append(cur)
    # captions have done their job (attached to their tables) and are not kept as separate elements
    elements = dp.assign_sections([e for e in elements if e["kind"] != "caption"])
    for i, e in enumerate(elements):
        e["element_index"] = i
        if e["kind"] == "table":
            e["table_id"] = f"{doc_id}-t{i}"
    stats.update(body_font_size=body, running_lines=len(running),
                 tables_kept=sum(e["kind"] == "table" for e in elements), headings=sum(e["kind"] == "heading" for e in elements))
    return elements, dict(stats)


parsed, doc_rows = {}, []
for r in docs.itertuples():
    t0 = time.time()
    with fitz.open(files[r.doc_id]["file_path"]) as pdf:
        els, st = extract_elements(pdf, r.doc_id)
    chunks = dp.build_chunks(els, r.project_name, TARGET_WORDS, MAX_WORDS, TABLE_MAX_WORDS)
    parsed[r.doc_id] = (els, chunks)
    doc_rows.append({**files[r.doc_id], "project_id": r.project_id, "project_name": r.project_name, "region": r.region,
                     "approval_fy": int(r.approval_fy), "pages": st["pages"], "pages_without_text": st.get("pages_without_text", 0),
                     "tables_found": st.get("tables_found", 0), "tables_kept": st["tables_kept"],
                     "tables_merged_across_pages": st.get("tables_merged_across_pages", 0), "headings": st["headings"],
                     "body_font_size": float(st["body_font_size"]), "running_lines": st["running_lines"],
                     "parse_seconds": round(time.time() - t0, 1), "parser_version": PARSER_VERSION})
doc_df = pd.DataFrame(doc_rows)
display(doc_df[["doc_id", "project_id", "pages", "pages_without_text", "tables_found", "tables_kept",
                "tables_merged_across_pages", "headings", "parse_seconds"]])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. What the parser sees: the section tree and the tables of one document
# MAGIC
# MAGIC **What:** the level-1 / level-2 headings of the first document (page, level, text) and its tables with caption, section path and shape; then one procurement table as stored (markdown with its contextual header).
# MAGIC
# MAGIC **Why:** a human check of the structure. Heading detection is typographic, so some errors remain (a bold phrase taken for a sub-heading, a datasheet label); they are shown, not hidden.

# COMMAND ----------

first_id = docs.doc_id.iloc[0]
els, chunks = parsed[first_id]
tree = [(e["page"], e["level"], e["text"][:90]) for e in els if e["kind"] == "heading"]
print(f"{first_id}: {len(tree)} headings; level-1 headings:")
for p, lvl, t in tree:
    if lvl == 1:
        print(f"  p{p:>3}  {t}")
tabs = pd.DataFrame([{"table_id": e["table_id"], "page": e["page"], "shape": f"{e['n_rows']}x{e['n_cols']}",
                      "caption": (e.get("caption") or "")[:70], "section": " > ".join(e["section_path"])[:80],
                      "annex": e["is_annex"], "continued": e.get("continued", False)} for e in els if e["kind"] == "table"])
display(tabs)
proc_tab = next(c for c in chunks if c["chunk_type"] == "table" and "Procurement" in c["context_header"])
print(proc_tab["embed_text"][:1500])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Bronze and silver tables
# MAGIC
# MAGIC **What:** `parsed_documents` (one row per PDF), `doc_elements` (every heading, text block and table; a table's text is its markdown) and `doc_chunks_v2` (every chunk, embedding added in section 6).
# MAGIC
# MAGIC **Why:** elements are the reusable layer: a different chunking (larger parents, other row groups) can be rebuilt from them without parsing the PDFs again, and a citation can point to the page and the table.

# COMMAND ----------

parsed_df = spark.createDataFrame(doc_df).withColumn("_parsed_at", F.current_timestamp())
n_parsed = publish_table(
    parsed_df, PARSED_TABLE,
    "PDFs parsed by p12 (PyMuPDF layout). Grain: one document. Source: Documents API pdfurl; files in proc_bronze.raw/doc_parse/pdf.",
    {"doc_id": "PK. Documents API id", "pdf_url": "PDF address", "file_path": "Saved PDF in the bronze volume", "bytes": "File size",
     "project_id": "Project id", "project_name": "Project name", "region": "Region", "approval_fy": "Approval fiscal year",
     "pages": "Pages", "pages_without_text": "Pages with < 50 characters of text and an image (would need OCR)",
     "tables_found": "Ruled tables PyMuPDF found", "tables_kept": "Tables that passed the quality gate (after merging continuations)",
     "tables_merged_across_pages": "Table parts merged into the table on the previous page", "headings": "Headings detected",
     "body_font_size": "Most common font size (pt)", "running_lines": "Distinct running header/footer lines removed",
     "parse_seconds": "Parse time", "parser_version": "Parser version", "_parsed_at": "Load time"},
    primary_key=["doc_id"])

el_rows = []
for d, (els, _) in parsed.items():
    for e in els:
        is_table = e["kind"] == "table"
        # tables are stored as markdown so the element text stays readable and the header stays attached to the rows
        text = (dp.table_markdown(e["rows"][:dp.header_rows(e["rows"])], e["rows"][dp.header_rows(e["rows"]):])
                if is_table else e["text"])
        el_rows.append({"doc_id": d, "element_index": e["element_index"], "kind": e["kind"], "level": e.get("level"),
                        "page": e["page"], "text": text, "caption": e.get("caption"), "section_path": " > ".join(e["section_path"]),
                        "section_id": e["section_id"], "is_annex": e["is_annex"], "table_id": e.get("table_id"),
                        "n_rows": e.get("n_rows"), "n_cols": e.get("n_cols"), "continued": e.get("continued")})
el_schema = ("doc_id string, element_index int, kind string, level int, page int, text string, caption string, section_path string, "
             "section_id string, is_annex boolean, table_id string, n_rows int, n_cols int, continued boolean")
n_el = publish_table(
    spark.createDataFrame(el_rows, el_schema).withColumn("parser_version", F.lit(PARSER_VERSION)), ELEMENTS_TABLE,
    "Layout elements of the parsed PDFs (p12). Grain: one heading, text block or table, in reading order. Tables as markdown.",
    {"doc_id": "PK, FK parsed_documents", "element_index": "PK. Position in reading order", "kind": "heading, text or table",
     "level": "Heading level (1 or 2)", "page": "PDF page (1-based)", "text": "Text; for a table, its markdown",
     "caption": "Table caption printed above it", "section_path": "Headings above the element (level 1 > level 2)",
     "section_id": "Hash of the section path (parent id for chunks)", "is_annex": "Inside an ANNEX / APPENDIX section",
     "table_id": "Table id (doc_id-t<index>)", "n_rows": "Table rows", "n_cols": "Table columns",
     "continued": "Table merged with its continuation on the next page", "parser_version": "Parser version"},
    primary_key=["doc_id", "element_index"])
add_foreign_key(ELEMENTS_TABLE, ["doc_id"], PARSED_TABLE, ["doc_id"])
E = spark.table(ELEMENTS_TABLE)
display(E.groupBy("kind").agg(F.count("*").alias("elements"), F.sum(F.col("is_annex").cast("int")).alias("in_annexes")).orderBy("kind"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Old chunks vs new chunks on the same 10 documents
# MAGIC
# MAGIC **What:**
# MAGIC 1. **Shape:** chunk counts, words, chunk types, annex share, for the old (`silver.rag_chunks`) and the new chunks.
# MAGIC 2. **Table rows:** every body row of every kept table is looked up in the document's old chunks with `dp.locate_row` on its distinctive tokens: intact (one chunk), split (several chunks), missing (dropped by the old prose filter or lost in flattening). For intact rows, the check also tests whether the table's header words are in the same old chunk.
# MAGIC 3. **Control:** 150 random narrative sentences per document go through the same test.
# MAGIC
# MAGIC **Why:** the claim "plain-text chunking breaks tables" should be a number, and the control shows that the test itself does not invent losses: if narrative sentences come out intact, the losses on table rows are real.

# COMMAND ----------

oldc = (spark.table(OLD_CHUNKS).filter(F.col("doc_id").isin(list(docs.doc_id)))
        .select("doc_id", "chunk_id", "chunk_index", "section", "n_words", "chunk_text", "embedding").toPandas())
new_rows = []
for d, (_, chunks) in parsed.items():
    pid = docs.set_index("doc_id").loc[d, "project_id"]
    for i, c in enumerate(chunks):
        new_rows.append({**c, "doc_id": d, "project_id": pid, "chunk_index": i, "chunk_id": f"{d}-c{i:04d}"})
newc = pd.DataFrame(new_rows)
shape = pd.DataFrame([
    {"chunker": "old: plain text, sentence packing, prose filter", "chunks": len(oldc), "median_words": int(oldc.n_words.median()),
     "table_chunks": 0, "chunks_in_annexes": int(oldc.section.str.contains(r"(?i)^annex|> annex").sum()),
     "distinct_sections": oldc.groupby("doc_id").section.nunique().sum()},
    {"chunker": "new: PDF layout, sections + tables", "chunks": len(newc), "median_words": int(newc.n_words.median()),
     "table_chunks": int((newc.chunk_type == "table").sum()), "chunks_in_annexes": int(newc.is_annex.sum()),
     "distinct_sections": newc.groupby("doc_id").section_id.nunique().sum()}])
display(shape)

# COMMAND ----------

row_res, ctrl = [], collections.Counter()
for d, (els, _) in parsed.items():
    toks = [dp.row_tokens([t]) for t in oldc[oldc.doc_id == d].chunk_text]
    for e in els:
        if e["kind"] == "table":
            n_head = dp.header_rows(e["rows"])
            head = dp.distinctive_tokens(dp.row_tokens([c for h in e["rows"][:n_head] for c in h]), toks)
            for r in e["rows"][n_head:]:
                # only tokens rare among this document's old chunks identify a row; words like "procurement" occur
                # everywhere
                dt = dp.distinctive_tokens(dp.row_tokens(r), toks)
                state = dp.locate_row(dt, toks, min_tokens=2)
                with_head = None
                # for an intact row, check whether its column header landed in the same old chunk (the numbers mean
                # little without it)
                if state == "intact" and len(head) >= 2:
                    best = max(range(len(toks)), key=lambda i: len(dt & toks[i]))
                    with_head = len(head & toks[best]) >= 0.5 * len(head)
                row_res.append({"doc_id": d, "table_id": e["table_id"], "state": state, "header_in_same_chunk": with_head})
    sents = [s for e in els if e["kind"] == "text" for s in dp.split_sentences(e["text"]) if len(s.split()) >= 12]
    # control: narrative sentences through the same test; if they come out intact, the test is not inventing losses
    random.Random(7).shuffle(sents)
    for s in sents[:150]:
        ctrl[dp.locate_row(dp.distinctive_tokens(dp.row_tokens([s]), toks), toks, min_tokens=2)] += 1
rows_df = pd.DataFrame(row_res)
tested = rows_df[rows_df.state != "trivial"]
by_state = tested.state.value_counts()
n_ctrl = sum(v for k, v in ctrl.items() if k != "trivial")
summary_rows = pd.DataFrame([
    {"unit": "table rows (new parser) found in old chunks", "tested": len(tested),
     "intact": f"{by_state.get('intact', 0)} ({by_state.get('intact', 0) / len(tested):.1%})",
     "split": f"{by_state.get('split', 0)} ({by_state.get('split', 0) / len(tested):.1%})",
     "missing": f"{by_state.get('missing', 0)} ({by_state.get('missing', 0) / len(tested):.1%})",
     "untestable (< 2 distinctive tokens)": int((rows_df.state == "trivial").sum())},
    {"unit": "control: narrative sentences", "tested": n_ctrl,
     "intact": f"{ctrl['intact']} ({ctrl['intact'] / n_ctrl:.1%})", "split": f"{ctrl['split']} ({ctrl['split'] / n_ctrl:.1%})",
     "missing": f"{ctrl['missing']} ({ctrl['missing'] / n_ctrl:.1%})", "untestable (< 2 distinctive tokens)": ctrl["trivial"]}])
display(summary_rows)
hk = tested[tested.header_in_same_chunk.notna()]
per_table = tested.groupby("table_id").state.agg(lambda s: "all intact" if (s == "intact").all() else
                                                 ("some rows split" if not (s == "missing").any() else "some rows missing"))
print(f"intact rows whose table header is in the same old chunk: {int(hk.header_in_same_chunk.sum())} of {len(hk)} "
      f"({hk.header_in_same_chunk.mean():.1%}); in the new chunks: all (the header is repeated in every row group)")
print(f"tables with testable rows: {per_table.size}; {per_table.value_counts().to_dict()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Embeddings and a retrieval test on table facts
# MAGIC
# MAGIC **What:** the new chunks' `embed_text` (contextual header + text) are embedded with GTE-large (the model of the old chunks), paced at 10 texts per second. Then 12 questions written by hand from facts that sit **in tables** of these PADs (thresholds, costs, allocations, ratios, statuses), each with the exact answer string, are embedded and searched with cosine similarity
# MAGIC - within the right document (as the agent filters by project), and
# MAGIC - across all 10 documents,
# MAGIC
# MAGIC against the old chunks (stored embeddings) and the new chunks. A hit at k means one of the top-k chunks contains the answer string.
# MAGIC
# MAGIC **Why:** the point of keeping tables is that a question about a number in a table can be answered. 12 questions are a small test, so the result is reported as counts, not as a precise rate.

# COMMAND ----------

_HOST = spark.conf.get("spark.databricks.workspaceUrl")
# the notebook's own short-lived token; nothing is stored or printed
_TOKEN = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
EMBED_TEXTS_PER_S = 10
_clock, _lock, USAGE = {"t": 0.0}, threading.Lock(), collections.Counter()


def _invoke(endpoint: str, body: dict, timeout: int = 180, max_retries: int = 12) -> dict:
    for attempt in range(max_retries):
        try:
            r = requests.post(f"https://{_HOST}/serving-endpoints/{endpoint}/invocations",
                              headers={"Authorization": f"Bearer {_TOKEN}"}, json=body, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            # only rate limits and server errors are retried; a 4xx means a bad request and retrying will not help
            retry, err = r.status_code == 429 or r.status_code >= 500, f"HTTP {r.status_code}: {r.text[:300]}"
        except requests.exceptions.RequestException as e:
            retry, err = True, f"{type(e).__name__}: {str(e)[:200]}"
        if not retry or attempt == max_retries - 1:
            raise RuntimeError(f"{endpoint} failed: {err}")
        time.sleep(min(30, 0.5 * 2 ** attempt) + random.random() * 0.5)


def embed_texts(texts: list[str], batch_size: int = 8) -> np.ndarray:
    """Unit-length GTE vectors, paced so that a long run stays under the workspace's shared QPS limit."""
    out = []
    for i in range(0, len(texts), batch_size):
        batch = list(texts[i:i + batch_size])
        with _lock:
            wait = _clock["t"] - time.time()
            # a shared pacing clock: each batch books its slot, so the rate holds even across threads
            _clock["t"] = max(_clock["t"], time.time()) + len(batch) / EMBED_TEXTS_PER_S
        if wait > 0:
            time.sleep(wait)
        resp = _invoke(EMBED_ENDPOINT, {"input": batch})
        USAGE["embed_tokens"] += (resp.get("usage") or {}).get("prompt_tokens", 0)
        out.extend(d["embedding"] for d in sorted(resp["data"], key=lambda d: d["index"]))
    X = np.asarray(out, dtype="float32")
    # unit vectors, so a dot product is the cosine (as for the stored old embeddings)
    return X / np.linalg.norm(X, axis=1, keepdims=True)


t0 = time.time()
new_vecs = embed_texts(list(newc.embed_text))
newc["embedding"] = list(new_vecs)
print(f"embedded {len(newc)} new chunks in {time.time() - t0:.0f} s ({USAGE['embed_tokens']:,} tokens)")

# COMMAND ----------

# written by hand from facts that sit in tables of these PADs; the third value is the string a correct chunk must
# contain
QUESTIONS = [
    ("31084172", "What is the prior review threshold for works contracts in the DRC Multisectoral Nutrition and Health Project?", "5,000,000"),
    ("31084172", "How much of the credit is allocated to cash transfers in the DRC nutrition project's eligible expenditure categories?", "4,350,000"),
    ("34420173", "What was the average bid evaluation delay, in business days, in The Gambia's procurement performance assessment?", "216"),
    ("34420173", "What share of the value of 2021 procurements in The Gambia went through restricted tender?", "87.56%"),
    ("33107520", "What is the prior review threshold for goods and non-consulting services in the Mozambique Sustainable Rural Economy Program?", "2,000,000"),
    ("34045634", "What is the total estimated cost of the climate smart infrastructure component of the Burkina Faso livestock project?", "113.52"),
    ("34045634", "What is the economic internal rate of return in the baseline scenario of the Burkina Faso livestock project?", "18.4"),
    ("34217851", "What are the cumulative expected disbursements by FY2028 for the OECS Skills and Innovation Project?", "27.69"),
    ("33363501", "What is the status of the electromechanical equipment package of the Java-Bali pumped storage hydropower project?", "Notification of award issued"),
    ("32255231", "What is the economic internal rate of return of navigation investments in the Sava and Drina rivers program?", "10.1"),
    ("33815424", "How much Yemen national IDA financing goes to Component 2 of the Red Sea and Gulf of Aden fishery program?", "12.44"),
    ("32602938", "Who is responsible for the audited financial statements of the Morocco COVID-19 social protection project?", "Directorate of Budget"),
]
qdf = pd.DataFrame(QUESTIONS, columns=["doc_id", "question", "answer"])
qvecs = embed_texts(list(qdf.question))
old_vecs = np.asarray([np.asarray(v, dtype="float32") for v in oldc.embedding])
old_vecs /= np.linalg.norm(old_vecs, axis=1, keepdims=True)


def first_hit(qv, vecs, texts, doc_ids, doc_id, answer, within_doc: bool, k_max: int = 10):
    """Rank (1-based) of the first chunk that contains the answer, within the top k_max; None if none."""
    mask = (doc_ids == doc_id) if within_doc else np.ones(len(doc_ids), bool)
    idx = np.where(mask)[0]
    order = idx[np.argsort(-(vecs[idx] @ qv))][:k_max]
    for rank, i in enumerate(order, start=1):
        if dp.answer_in(answer, texts[i]):
            return rank
    return None


res = []
for qi, q in qdf.iterrows():
    row = {"doc_id": q.doc_id, "question": q.question[:80], "answer": q.answer,
           "answer_in_any_old_chunk": any(dp.answer_in(q.answer, t) for t in oldc[oldc.doc_id == q.doc_id].chunk_text),
           "answer_in_any_new_chunk": any(dp.answer_in(q.answer, t) for t in newc[newc.doc_id == q.doc_id].text)}
    for name, vecs, texts, ids in [("old", old_vecs, oldc.chunk_text.values, oldc.doc_id.values),
                                   ("new", new_vecs, newc.embed_text.values, newc.doc_id.values)]:
        for scope, within in [("doc", True), ("all", False)]:
            row[f"{name}_rank_{scope}"] = first_hit(qvecs[qi], vecs, texts, ids, q.doc_id, q.answer, within)
    res.append(row)
ret = pd.DataFrame(res)
display(ret)


def hits(col, k):
    return int(ret[col].apply(lambda r: r is not None and not pd.isna(r) and r <= k).sum())


display(pd.DataFrame([{"chunks": n, "scope": s, **{f"hit@{k}": f"{hits(f'{n}_rank_{s}', k)}/{len(ret)}" for k in (1, 3, 5, 10)}}
                      for n in ("old", "new") for s in ("doc", "all")]))

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** an ablation: the same new chunks embedded **without** their contextual header (chunk text only), searched within the right document with the same 12 questions.
# MAGIC
# MAGIC **Why:** a table chunk on its own is a grid of numbers with column names; the header (project, section, caption) is what tells the embedding what the numbers are about. This measures how much of the retrieval depends on it.

# COMMAND ----------

# ablation: the same chunks without their contextual header, to see how much retrieval depends on it
text_only = embed_texts(list(newc.text))
abl = [first_hit(qvecs[qi], text_only, newc.text.values, newc.doc_id.values, q.doc_id, q.answer, True)
       for qi, q in qdf.iterrows()]
ret["new_text_only_rank_doc"] = abl
display(pd.DataFrame([{"new chunks embedded as": label, **{f"hit@{k}": f"{hits(col, k)}/{len(ret)}" for k in (1, 3, 5, 10)}}
                      for label, col in [("contextual header + text", "new_rank_doc"), ("text only", "new_text_only_rank_doc")]]))

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** the new chunks with their embeddings are written to `doc_chunks_v2`, with data-quality checks.
# MAGIC
# MAGIC **Why:** the table is ready for a vector index (Delta Sync on `embedding`) next to the old one; `section_id` lets a retriever return the whole parent section of a matched child chunk, and `table_id` / `row_start` / `row_end` let a citation name the exact rows.

# COMMAND ----------

newc["text_hash"] = newc.text.map(lambda t: dp.short_hash(t, 16))
newc["embedding"] = newc.embedding.map(lambda v: [float(x) for x in v])
chunk_cols = ["chunk_id", "doc_id", "project_id", "chunk_index", "chunk_type", "section_path", "section_id", "is_annex",
              "page_start", "page_end", "table_id", "row_start", "row_end", "context_header", "text", "embed_text", "n_words",
              "text_hash", "embedding"]
chunk_schema = ("chunk_id string, doc_id string, project_id string, chunk_index int, chunk_type string, section_path string, "
                "section_id string, is_annex boolean, page_start int, page_end int, table_id string, row_start int, row_end int, "
                "context_header string, text string, embed_text string, n_words int, text_hash string, embedding array<float>")
# pandas turns missing ints into NaN floats; Spark's int columns need None
_int = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else int(v)
records = [[_int(r[c]) if c in ("chunk_index", "page_start", "page_end", "row_start", "row_end", "n_words") else
            (None if c == "table_id" and not isinstance(r[c], str) else r[c]) for c in chunk_cols] for r in newc.to_dict("records")]
cdf = (spark.createDataFrame(records, chunk_schema)
       .withColumnRenamed("text", "chunk_text")
       .withColumn("embedding_model", F.lit(EMBED_ENDPOINT)).withColumn("chunker_version", F.lit(PARSER_VERSION))
       .withColumn("updated_at", F.current_timestamp()))
n_chunks = publish_table(
    cdf, CHUNKS_TABLE,
    "Structure-aware document chunks (p12): narrative chunks within one section and table chunks (whole table or row groups "
    "with the header repeated), each with a contextual header and a GTE embedding. Grain: one chunk.",
    {"chunk_id": "PK. doc_id-c<index>", "doc_id": "FK parsed_documents", "project_id": "Project id",
     "chunk_index": "Position in the document", "chunk_type": "narrative or table",
     "section_path": "Headings above the chunk", "section_id": "Parent section id (doc_elements.section_id)",
     "is_annex": "Chunk is in an annex", "page_start": "First PDF page", "page_end": "Last PDF page",
     "table_id": "Table id for table chunks", "row_start": "First body row of the table in this chunk",
     "row_end": "Body row after the last one in this chunk", "context_header": "Document > section path [> caption]",
     "chunk_text": "Chunk text (markdown for tables)", "embed_text": "Contextual header + chunk text (what is embedded)",
     "n_words": "Words in chunk_text", "text_hash": "Hash of chunk_text (re-embed only when it changes)",
     "embedding": "GTE-large vector, unit length", "embedding_model": "Embedding endpoint",
     "chunker_version": "Parser/chunker version", "updated_at": "Load time"},
    primary_key=["chunk_id"])
add_foreign_key(CHUNKS_TABLE, ["doc_id"], PARSED_TABLE, ["doc_id"])
C = spark.table(CHUNKS_TABLE)
display(dq_report([
    (PARSED_TABLE, "documents", n_parsed, f"== {len(docs)}"),
    (ELEMENTS_TABLE, "elements", n_el, "info"),
    (ELEMENTS_TABLE, "duplicate keys", duplicate_keys(E, ["doc_id", "element_index"]), "== 0"),
    (CHUNKS_TABLE, "chunks", n_chunks, "info"),
    (CHUNKS_TABLE, "duplicate chunk_id", duplicate_keys(C, ["chunk_id"]), "== 0"),
    (CHUNKS_TABLE, "chunks without embedding", C.filter("size(embedding) <> 1024").count(), "== 0"),
    (CHUNKS_TABLE, "chunks over 400 words", C.filter("n_words > 400").count(), "== 0"),
    (CHUNKS_TABLE, "orphan doc_id", orphan_count(C, "doc_id", spark.table(PARSED_TABLE), "doc_id"), "== 0"),
    (CHUNKS_TABLE, "table chunks without a header row", C.filter("chunk_type = 'table' AND NOT chunk_text LIKE '| %'").count(), "== 0"),
]))

# COMMAND ----------

# MAGIC %md
# MAGIC **What the numbers say (run of 2026-10-21, 10 PADs, 941 pages).**
# MAGIC - **Structure:** 502 ruled tables found, 269 kept after the quality gate; 0 pages without a text layer (no OCR needed for these born-digital PADs). The new chunker gives 2,064 chunks (362 of them table chunks) in 703 distinct sections vs 1,700 chunks in 309 section labels for the old one; 846 new chunks carry the annex flag.
# MAGIC - **Tables in the old chunks:** of 1,290 table rows that can be identified, 886 (68.7%) are intact in one old chunk, 58 (4.5%) are split across chunks and **346 (26.8%) are missing** (dropped by the prose filter); 72 of 237 tables lost or split rows. Only 46% of the intact rows have their column header in the same chunk, so a number survives without its meaning. The control shows the test is fair: 97.2% of narrative sentences are intact.
# MAGIC - **Retrieval of table facts (12 questions):** hit@3 10/12 new vs 9/12 old, hit@10 12/12 vs 11/12; one fact (cumulative disbursements in a datasheet table) exists only in the new chunks. But hit@1 is lower for the new chunks (5/12 vs 8/12): a narrative chunk of the same section that restates the topic often ranks above the table chunk that holds the number. With a reader LLM that takes the top 3-5 chunks this costs nothing; for a top-1 use it would need a re-ranker.
# MAGIC - **The contextual header carries the retrieval:** the same chunks embedded without their header find the answer for only 3 of 12 questions within the top 10.
# MAGIC - **Remaining parser errors** are visible above: cover-page lines taken as level-1 headings, a few datasheet labels as sub-headings (e.g. "End Target", "BASIC INFORMATION" as section paths), unruled results-framework tables left as narrative.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. The production strategy for 100+ page reports
# MAGIC
# MAGIC | Step | Prototype here | Production |
# MAGIC |---|---|---|
# MAGIC | Acquire | Documents API `pdfurl`, one PDF per document into a volume | same, incremental by `docdt`/`lastupdate`; keep the text rendering too (cheap fallback, and the plain-text index keeps working) |
# MAGIC | Text layer | PyMuPDF lines with font size and bold | same; pages without a text layer (`pages_without_text`, 0 of the pages here) go to OCR only for those pages (Azure AI Document Intelligence layout model or Tesseract on a GPU-free pool), flagged `ocr = true` on their elements so citations can warn |
# MAGIC | Structure | typographic headings, 2 levels; ANNEX headings flag annexes | add PDF bookmarks when present (exact), a level-3 for "3.2" numbering, and the document-type template (PAD sections are standard) as a prior; measure heading precision on a labelled sample per document type |
# MAGIC | Tables | ruled tables with a quality gate, captions, page-break merges, markdown | add a layout model for unruled tables (results frameworks are often unruled and stay narrative here); keep each table also as rows (JSON) so numbers can be queried, not only embedded |
# MAGIC | Chunks | narrative within one section (260-320 words, 40-word overlap); table = whole or row groups with header repeated | same; plus **parent-child**: index the small chunks, return the parent section (`section_id`) or the whole table (`table_id`) to the LLM, capped by tokens |
# MAGIC | Context | contextual header "project > section > sub-section > caption" embedded with the chunk | same, plus country / sector / document type / date as filter columns, and an LLM-written one-line chunk summary only for table chunks (cheap: tables are about 15% of chunks) |
# MAGIC | Metadata for filtering and citation | doc_id, project_id, pages, section path, annex flag, table id and rows | same, plus `docdt`, language, document version; annex chunks can be excluded or boosted per question type (procurement questions -> procurement annex) |
# MAGIC | Refresh | full rebuild of 10 documents | `text_hash` per chunk: re-embed only changed chunks (the p10 index refresh plan); `parser_version` on every row so a new parser can run side by side |
# MAGIC | Quality gates | the row test and control above, 12 retrieval questions | the same row test on every new batch (share of table rows intact), a growing hand-written question set per document type, and alerts when a document yields no headings or no tables |

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC **What:** the headline numbers as the notebook's exit value.
# MAGIC
# MAGIC **Why:** a job run shows them without opening the notebook.

# COMMAND ----------

summary = {"documents": len(docs), "pages": int(doc_df.pages.sum()), "pages_without_text": int(doc_df.pages_without_text.sum()),
           "tables_found": int(doc_df.tables_found.sum()), "tables_kept": int(doc_df.tables_kept.sum()),
           "elements": n_el, "chunks_new": n_chunks, "chunks_old": len(oldc),
           "table_rows_tested": len(tested), "rows_intact_old": int(by_state.get("intact", 0)),
           "rows_split_old": int(by_state.get("split", 0)), "rows_missing_old": int(by_state.get("missing", 0)),
           "control_sentences_intact": f"{ctrl['intact']}/{n_ctrl}",
           **{f"hit{k}_doc_{n}": hits(f"{n}_rank_doc", k) for k in (1, 3, 10) for n in ("old", "new")},
           "hit10_doc_new_text_only": hits("new_text_only_rank_doc", 10), "questions": len(ret),
           "embed_tokens": USAGE["embed_tokens"]}
print(summary)

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
