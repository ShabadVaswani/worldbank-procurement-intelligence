# Databricks notebook source
# MAGIC %md
# MAGIC # p09_conflicting_evidence — when supervision ratings and the final evaluation disagree
# MAGIC
# MAGIC A project is rated several times in its life, by different people, for different purposes. The agent and the analysts will meet all of these ratings in documents, and they often disagree. This notebook collects them for a sample of closed projects, **measures** how often they disagree, and implements a resolution policy that never hides the disagreement.

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <img src="data:image/png;base64,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" alt="evidence_timeline diagram" style="max-width:100%; width:1620px"/>
# MAGIC
# MAGIC <details><summary>Diagram source (Mermaid)</summary>
# MAGIC
# MAGIC <pre><code>---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC   htmlLabels: false
# MAGIC   flowchart:
# MAGIC     htmlLabels: false
# MAGIC     wrappingWidth: 600
# MAGIC ---
# MAGIC flowchart LR
# MAGIC     ap["approval"]
# MAGIC     isr["mid-term to last ISR&lt;br/&gt;ISR ... ISR (isr_earlier) ... ISR (isr_last)&lt;br/&gt;task team: progress towards the PDO,&lt;br/&gt;implementation progress (forward-looking)"]
# MAGIC     cl["closing"]
# MAGIC     icr["ICR (self)&lt;br/&gt;outcome rating, Bank team&lt;br/&gt;(backward-looking, self-reported)"]
# MAGIC     ieg["IEG ICR Review&lt;br/&gt;outcome rating, independent"]
# MAGIC     ap --&gt;|"time"| isr --&gt;|"time"| cl --&gt;|"time"| icr --&gt;|"time"| ieg
# MAGIC </code></pre>
# MAGIC
# MAGIC </details>

# COMMAND ----------

# MAGIC %md
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_bronze.rating_documents` | one document read per project and role (last ISR, earlier ISR, ICR Review), with the raw parsed ratings | `project_id, role` |
# MAGIC | `proc_silver.project_ratings_evidence` | one rating: project x source type x dimension, with score, date, independence and citation | `project_id, source_type, dimension` |
# MAGIC | `proc_gold.project_evidence_resolution` | the resolved answer per project and question type, with flag, confidence and rationale | `project_id, question_type` |
# MAGIC
# MAGIC ## Interface for the agent: `resolve_evidence()`
# MAGIC
# MAGIC `from proc_intel.evidence import resolve_evidence` — a pure function, no Spark, unit-tested in `tests/test_evidence.py`.
# MAGIC
# MAGIC **Input** `resolve_evidence(records, question_type, reference_date=None)`
# MAGIC
# MAGIC | Field of each record | Type | Values |
# MAGIC |---|---|---|
# MAGIC | `project_id` | str | `P123456` (one project per call) |
# MAGIC | `source_type` | str | `ieg_validation`, `icr_self_rating`, `isr_last`, `isr_earlier` |
# MAGIC | `dimension` | str | `outcome`, `pdo_progress`, `implementation_progress` |
# MAGIC | `rating` | str | six-point label or abbreviation (`Moderately Satisfactory`, `MS`); the score is recomputed from it |
# MAGIC | `as_of` | date or ISO string | date of the rating |
# MAGIC | `doc_id`, `url`, `source` | str, optional | citation, returned unchanged |
# MAGIC
# MAGIC `question_type` is `outcome` (how did the project do?) or `current_status` (how is implementation going?). `reference_date` (optional) is "today" for the staleness rule. Rows of `proc_silver.project_ratings_evidence` can be passed as they are: `[r.asDict() for r in rows]`.
# MAGIC
# MAGIC **Output** (a dict)
# MAGIC
# MAGIC | Key | Meaning |
# MAGIC |---|---|
# MAGIC | `answer` | the chosen record: `source_type, dimension, rating, score, as_of, independence, rank, specificity, doc_id, url, source` |
# MAGIC | `supporting` | other records within 1 point of the answer and on the same side of the satisfactory line (same fields, plus `points_from_answer`) |
# MAGIC | `conflicting` | records 2+ points away, or 1 point away across the satisfactory line |
# MAGIC | `superseded` | current_status only: ratings from older ISRs (history, not conflict) |
# MAGIC | `not_used` | records that cannot answer this question type, or carry no rating |
# MAGIC | `flag` | `consistent`, `disagreement` (1 point across the line), `conflict` (2+ points), `insufficient` |
# MAGIC | `confidence` | `high`, `medium`, `low` (rules in section 6) |
# MAGIC | `rationale` | one paragraph naming the chosen source and every conflicting one, with dates and document ids |
# MAGIC
# MAGIC The resolved answers for the sampled projects are also stored in `proc_gold.project_evidence_resolution` (with the full result as JSON), so the agent can read them with SQL.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key design decisions
# MAGIC
# MAGIC | Decision | Rationale | Evidence |
# MAGIC |---|---|---|
# MAGIC | Ratings read from the Documents API text of each project's ISRs, ICRs and ICR Reviews; parsed IEG ratings checked against `bronze.ieg_ratings` | No existing source holds the ICR self-rating; one ICR Review gives both the ICR and IEG ratings | `bronze.ieg_ratings` has IEG's outcome for 6,906 ICR Reviews but no ICR self-rating; existing chunks are appraisal documents only; the Projects API carries no ratings; the Documents API filters by `docty_exact` and every ISR and ICR Review has a plain-text rendering |
# MAGIC | One column-position parser for both tables: columns from the header line, words assigned to the column under which they start, placeholders (`---`, `Not Rated`) matched, the "Reason for disagreement" column cut off | A line regex reads the wrong column when cells wrap | In ICR Reviews a cell such as "Moderately Satisfactory" is often split over two lines, above and below the row label |
# MAGIC | A column starts 8 characters before its title (never before the second word of the previous column's rating); the header regex accepts both ISR templates; private-use characters replaced by a space; both layouts unit-tested | Two layout variants broke the parser; falling back to an older ISR would have silently replaced the last ISR for a quarter of the sample | Run 1 read IEG's outcome correctly for 364 of 376 ICR Reviews (all 12 mismatches: IEG cells up to 5 characters left of the title); for 91 of 400 projects the newest ISR had "no ratings" (2024 template: "Previous / Current" header, private-use icon prefixes); section 4 re-checks IEG |
# MAGIC | 400 of the eligible projects in hash order of `project_id`; per project the last ISR, the ISR nearest the middle of supervision and the ICR Review, with counted fallbacks | Reproducible and unrelated to the ratings, so disagreement rates are not biased by the selection | 1,368 closed projects in the procurement data have an IEG outcome rating (evaluated FY2019-2027) |
# MAGIC | A documented source hierarchy per question type; every other record returned as supporting or conflicting with its date and citation, plus a flag and a confidence label | The question decides the authoritative source: IEG for "how did the project do", the latest ISR for "how is it going now" | Tested on hand-made cases in `tests/test_evidence.py` |
# MAGIC
# MAGIC Full reasoning: docs/decision_log.md

# COMMAND ----------

# MAGIC %pip install -q rapidfuzz unidecode

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

# MAGIC %md
# MAGIC ## Settings
# MAGIC
# MAGIC **What:** the sample size, the Documents API address and document types, the folders for raw files, and the table names.
# MAGIC
# MAGIC **Why:** raw listings and texts are kept in the bronze volume, so the parse can be re-run or audited without calling the API again, and a restart skips everything already saved.

# COMMAND ----------

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from pyspark.sql import Window

from proc_intel.evidence import HIERARCHY, SCALE, SHORT, parse_icrr_ratings, parse_isr_ratings, resolve_evidence
from proc_intel.http import RETRYABLE_STATUS, get_json, retry_delay
from proc_intel.similarity import wilson_interval

SAMPLE_SIZE = 400
DOCS_URL = "https://search.worldbank.org/api/v3/wds"
DOC_TYPES = {"isr": "Implementation Status and Results Report",
             "icr": "Implementation Completion and Results Report",
             "icrr": "Implementation Completion Report Review"}
# some ISRs and ICR Reviews have no readable ratings block; try up to three documents before giving up on a role
MAX_TRIES_PER_ROLE = 3
EVIDENCE_DIR = f"{RAW_VOLUME}/evidence"
DOCS_TABLE = f"{BRONZE}.rating_documents"
EVIDENCE_TABLE = f"{SILVER}.project_ratings_evidence"
RESOLUTION_TABLE = f"{GOLD}.project_evidence_resolution"
IEG_RATINGS = f"{CATALOG}.bronze.ieg_ratings"           # outcome project, read only
for sub in ["lists", "docs"]:
    os.makedirs(f"{EVIDENCE_DIR}/{sub}", exist_ok=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The project sample
# MAGIC
# MAGIC **What:** closed projects of the procurement model (`proc_silver.dim_project`) with an IEG ICR Review outcome other than "Not Rated", ordered by a hash of the project id; the first 400.
# MAGIC
# MAGIC **Why:** these projects have both procurement data (contracts, notices) and an independent verdict, so the evidence can later be joined to the procurement graph. Hash order is reproducible and independent of the ratings.

# COMMAND ----------

# newest ICR Review per project; a project can have been re-evaluated
ieg = (spark.table(IEG_RATINGS).filter("evaluation_type = 'ICRR' AND outcome <> 'Not Rated'")
       .withColumn("_rn", F.row_number().over(Window.partitionBy("project_id").orderBy(F.desc("evaluation_fy"))))
       .filter("_rn = 1").select("project_id", F.col("outcome").alias("ieg_outcome_dataset"),
                                 F.col("evaluation_fy").cast("int").alias("evaluation_fy")))
eligible = (spark.table(f"{SILVER}.dim_project").filter("status = 'Closed'")
            .join(ieg, "project_id").select("project_id", "project_name", "region", "major_sector", "country_code",
                                            "approval_fy", "ieg_outcome_dataset", "evaluation_fy"))
# hash order is reproducible and unrelated to the ratings, so the disagreement rates below are not biased by the
# selection
sample = eligible.orderBy(F.sha2("project_id", 256)).limit(SAMPLE_SIZE).cache()
print(f"eligible closed projects with an IEG outcome: {eligible.count():,}; sampled: {sample.count()}")
display(sample.groupBy("region").count().orderBy(F.desc("count")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Find and read the documents (resumable, 4 projects in parallel)
# MAGIC
# MAGIC **What:** for each project, `collect_project()`
# MAGIC 1. lists its ISRs, ICRs and ICR Reviews (one Documents API call per type; the listing is saved as JSON),
# MAGIC 2. reads the **last ISR** (newest first; if a document has no readable ratings block, the next older one, up to 3),
# MAGIC 3. reads the **earlier ISR** nearest the middle of the supervision period (first ISR to last ISR),
# MAGIC 4. reads the newest **ICR Review** with a ratings table,
# MAGIC
# MAGIC saving every text file to the volume, and returns one small row per role with the parsed ratings. Only the ICR's date is needed (its rating is printed in the ICR Review), so ICRs are listed but not downloaded.
# MAGIC
# MAGIC **Why:** three small documents per project instead of all of them. Saved listings and texts make a re-run free and let anyone re-check a parsed rating against its source text.

# COMMAND ----------

HTTP = requests.Session()


def get_text(url: str, max_retries: int = 5) -> str | None:
    """GET a document's text rendering with the same retry rules as get_json; None if the server has no text
    for it (404/403/410: some listed documents have no text rendering)."""
    for attempt in range(max_retries + 1):
        try:
            resp = HTTP.get(url, timeout=120)
            # some listed documents simply have no text rendering; that is an answer, not an error to retry
            if resp.status_code in (403, 404, 410):
                return None
            if resp.status_code not in RETRYABLE_STATUS:
                resp.raise_for_status()
                return resp.content.decode("utf-8", errors="replace")
            delay = retry_delay(attempt, resp.text, resp.headers.get("Retry-After"))
        except (requests.ConnectionError, requests.Timeout):
            delay = retry_delay(attempt)
        # jitter so the four worker threads do not retry in lockstep
        time.sleep(delay + random.uniform(0, 1))
    raise RuntimeError(f"giving up on {url}")


def list_documents(project_id: str) -> dict:
    path = f"{EVIDENCE_DIR}/lists/{project_id}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    listing = {}
    for role, docty in DOC_TYPES.items():
        body = get_json(DOCS_URL, {"format": "json", "proid": project_id, "docty_exact": docty, "rows": 100,
                                   "fl": "id,docdt,docty,txturl,url"}, session=HTTP)
        # documents without a text URL cannot be parsed, so they are not candidates
        docs = [d for k, d in body.get("documents", {}).items() if k != "facets" and d.get("txturl")]
        listing[role] = sorted(docs, key=lambda d: d.get("docdt") or "", reverse=True)     # newest first
    with open(path, "w") as f:
        json.dump(listing, f)
    return listing


def read_document(doc: dict) -> tuple[str | None, str | None]:
    """The saved text of a document (fetched once). A '.missing' marker remembers documents without text."""
    path, missing = f"{EVIDENCE_DIR}/docs/{doc['id']}.txt", f"{EVIDENCE_DIR}/docs/{doc['id']}.missing"
    if os.path.exists(missing):
        return None, None
    if not os.path.exists(path):
        text = get_text(doc["txturl"])
        # remember "no text" on disk so a re-run does not ask the server again
        if text is None:
            open(missing, "w").close()
            return None, None
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    with open(path, encoding="utf-8") as f:
        return f.read(), path


def first_readable(candidates: list[dict], parse, has_rating) -> tuple[dict | None, dict, str | None, int, int]:
    """First candidate (in the given order) whose parsed ratings are usable; also how many were tried."""
    for tried, doc in enumerate(candidates[:MAX_TRIES_PER_ROLE], start=1):
        text, path = read_document(doc)
        parsed = parse(text)
        # a document counts only if its ratings parse; otherwise fall through to the next older one
        if text and has_rating(parsed):
            return doc, parsed, path, tried, len(text)
    return None, {}, None, min(len(candidates), MAX_TRIES_PER_ROLE), 0


def _date(doc: dict | None):
    return datetime.fromisoformat(doc["docdt"][:10]).date() if doc and doc.get("docdt") else None


def collect_project(project_id: str) -> list[dict]:
    listing = list_documents(project_id)
    isrs, icrs, icrrs = listing["isr"], listing["icr"], listing["icrr"]
    isr_ok = lambda p: bool(p.get("pdo_current") or p.get("ip_current"))
    rows = []

    def add(role, doc, parsed, path, tried, n_chars, n_candidates):
        rows.append({"project_id": project_id, "role": role, "doc_id": doc["id"] if doc else None,
                     "doc_date": _date(doc), "txt_url": doc["txturl"] if doc else None, "file_path": path,
                     "n_chars": n_chars, "n_candidates": n_candidates, "n_tried": tried,
                     **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in parsed.items()}})

    last, parsed, path, tried, n = first_readable(isrs, parse_isr_ratings, isr_ok)
    add("isr_last", last, parsed, path, tried, n, len(isrs))
    if last:
        # ISO date strings compare correctly as text
        older = [d for d in isrs if (d.get("docdt") or "") < last["docdt"]]
        if older:
            first_d, last_d = _date(older[-1]), _date(last)
            # the mid-period ISR: closest to halfway between the first ISR and the last readable one
            middle = first_d + (last_d - first_d) / 2
            by_distance = sorted(older, key=lambda d: abs((_date(d) - middle).days))
            mid, parsed, path, tried, n = first_readable(by_distance, parse_isr_ratings, isr_ok)
            add("isr_earlier", mid, parsed, path, tried, n, len(older))
    icrr, parsed, path, tried, n = first_readable(icrrs, parse_icrr_ratings,
                                                  lambda p: bool(p.get("ieg_outcome") or p.get("icr_outcome")))
    # the ICR itself is not downloaded: its rating is printed in the ICR Review, only its id and date are needed
    add("icrr", icrr, {**parsed, "icr_doc_id": icrs[0]["id"] if icrs else None,
                       "icr_doc_date": _date(icrs[0]).isoformat() if icrs else None}, path, tried, n, len(icrrs))
    return rows


started = time.time()
project_ids = [r.project_id for r in sample.select("project_id").collect()]
with ThreadPoolExecutor(max_workers=4) as pool:
    collected = [row for rows in pool.map(collect_project, project_ids) for row in rows]
print(f"{len(project_ids)} projects, {len(collected)} role rows in {time.time() - started:.0f} s")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Bronze: `proc_bronze.rating_documents`
# MAGIC
# MAGIC **What:** one row per project and role with the document read, its date, file path, how many candidates existed and were tried, and the raw parsed ratings.
# MAGIC
# MAGIC **Why:** the audit trail between the source text and the silver evidence. Every rating in silver can be traced to a file in the volume and a URL.

# COMMAND ----------

doc_schema = ("project_id string, role string, doc_id string, doc_date date, txt_url string, file_path string, "
              "n_chars int, n_candidates int, n_tried int, seq_no int, archived_on string, pdo_current string, "
              "pdo_previous string, ip_current string, ip_previous string, icr_outcome string, ieg_outcome string, "
              "icr_bank_performance string, ieg_bank_performance string, icr_doc_id string, icr_doc_date string")
fields = [f.split()[0] for f in doc_schema.split(", ")]
docs_df = (spark.createDataFrame([{k: r.get(k) for k in fields} for r in collected], doc_schema)
           .withColumn("archived_on", F.to_date("archived_on")).withColumn("icr_doc_date", F.to_date("icr_doc_date"))
           .withColumn("_fetched_at", F.current_timestamp()))
n_docs = publish_table(
    docs_df, DOCS_TABLE,
    "Rating documents read for the evidence sample (p09). Grain: one row per project and role (isr_last, isr_earlier, "
    "icrr). Source: World Bank Documents API (search.worldbank.org/api/v3/wds), text renderings saved in "
    "proc_bronze.raw/evidence.",
    {"project_id": "PK. Project id", "role": "PK. isr_last, isr_earlier or icrr",
     "doc_id": "Documents API id of the document read (null: none readable)", "doc_date": "Document date (docdt)",
     "txt_url": "Text rendering URL", "file_path": "Saved text in the bronze volume",
     "n_chars": "Characters in the text", "n_candidates": "Documents of this role available for the project",
     "n_tried": "Documents read until one had a readable ratings table",
     "seq_no": "ISR sequence number", "archived_on": "ISR archive date (the rating date)",
     "pdo_current": "ISR: progress towards the PDO, this ISR", "pdo_previous": "ISR: same, previous ISR",
     "ip_current": "ISR: overall implementation progress, this ISR", "ip_previous": "ISR: same, previous ISR",
     "icr_outcome": "ICR Review table: outcome as rated by the ICR (self)", "ieg_outcome": "ICR Review table: outcome as rated by IEG",
     "icr_bank_performance": "ICR Review table: Bank performance, ICR", "ieg_bank_performance": "ICR Review table: Bank performance, IEG",
     "icr_doc_id": "Newest ICR document id (date source for the self-rating)", "icr_doc_date": "Its date",
     "_fetched_at": "Load time"},
    primary_key=["project_id", "role"])
D = spark.table(DOCS_TABLE)
display(D.groupBy("role").agg(F.count("*").alias("projects"), F.count("doc_id").alias("with_readable_doc"),
                              F.sum(F.when(F.col("n_candidates") == 0, 1).otherwise(0)).alias("no_document_listed"),
                              F.sum(F.when(F.col("n_tried") > 1, 1).otherwise(0)).alias("needed_fallback"),
                              F.round(F.avg("n_chars")).alias("avg_chars")).orderBy("role"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Parser check against IEG's own dataset
# MAGIC
# MAGIC **What:** compares IEG's outcome as read from the ICR Review text with IEG's outcome in `bronze.ieg_ratings`, and lists the disagreements.
# MAGIC
# MAGIC **Why:** the dataset is an independent ground truth for one of the four columns the parser reads. A high match rate on IEG's column is evidence that the column assignment (and therefore the ICR column next to it) works; the mismatches show what the parser gets wrong.

# COMMAND ----------

# IEG's dataset is an independent ground truth for the IEG column; matching it shows the column assignment works
check = (D.filter("role = 'icrr' AND ieg_outcome IS NOT NULL").join(sample.select("project_id", "ieg_outcome_dataset"), "project_id"))
n_check, n_match = check.count(), check.filter("ieg_outcome = ieg_outcome_dataset").count()
low, high = wilson_interval(n_match, n_check)
print(f"IEG outcome parsed from the ICR Review = IEG dataset: {n_match} of {n_check} ({n_match / n_check:.1%}, "
      f"95% CI {low:.1%}-{high:.1%})")
display(check.filter("ieg_outcome <> ieg_outcome_dataset")
        .select("project_id", "doc_id", "ieg_outcome", "ieg_outcome_dataset", "icr_outcome").limit(15))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Silver: `proc_silver.project_ratings_evidence`
# MAGIC
# MAGIC **What:** one row per rating, in the long format `resolve_evidence()` takes:
# MAGIC
# MAGIC | source_type | dimension | rating from | as_of | citation |
# MAGIC |---|---|---|---|---|
# MAGIC | `ieg_validation` | outcome | `bronze.ieg_ratings` (IEG's dataset; the text parse only cross-checks it) | ICR Review date (else 30 June of the evaluation FY) | ICR Review document |
# MAGIC | `icr_self_rating` | outcome | ICR column of the ICR Review table | ICR date (else ICR Review date) | ICR Review document (where it was read) |
# MAGIC | `isr_last`, `isr_earlier` | pdo_progress, implementation_progress | "Overall Ratings" block, current column | ISR archive date (else document date) | ISR document |
# MAGIC
# MAGIC **Why:** a long table holds any number of sources and dimensions without schema changes; adding Aide-Memoire or restructuring-paper ratings later is new rows, not new columns. Every row carries its independence and a citation, which is what the resolution policy and the agent need.

# COMMAND ----------

score_map = F.create_map(*[x for k, v in SCALE.items() for x in (F.lit(k), F.lit(v))])
doc_url = lambda c: F.regexp_replace(F.col(c), r"/text/.*$", "")         # the document page, not the text file
icrr = D.filter("role = 'icrr'").alias("r")
isr = D.filter("role IN ('isr_last', 'isr_earlier') AND doc_id IS NOT NULL")
ieg_rows = (sample.select("project_id", "ieg_outcome_dataset", "evaluation_fy").join(icrr, "project_id", "left")
            .select("project_id", F.lit("ieg_validation").alias("source_type"), F.lit("outcome").alias("dimension"),
                    # the rating comes from IEG's dataset, not the text parse: the parse is only used to cross-check it
                    # above
                    F.col("ieg_outcome_dataset").alias("rating"),
                    # no ICR Review document found: date it at the end of the evaluation fiscal year (the Bank's FY ends
                    # 30 June)
                    F.coalesce("doc_date", F.make_date("evaluation_fy", F.lit(6), F.lit(30))).alias("as_of"),
                    F.concat(F.lit("IEG ICR Review, evaluation FY"), F.col("evaluation_fy").cast("string")).alias("source"),
                    F.coalesce("doc_id", F.lit("bronze.ieg_ratings")).alias("doc_id"), doc_url("txt_url").alias("doc_url")))
icr_rows = (icrr.filter("icr_outcome IS NOT NULL")
            .select("project_id", F.lit("icr_self_rating").alias("source_type"), F.lit("outcome").alias("dimension"),
                    F.col("icr_outcome").alias("rating"), F.coalesce("icr_doc_date", "doc_date").alias("as_of"),
                    F.concat(F.lit("ICR self-rating as printed in the ICR Review (ICR document "),
                             F.coalesce("icr_doc_id", F.lit("not listed")), F.lit(")")).alias("source"),
                    "doc_id", doc_url("txt_url").alias("doc_url")))
isr_rows = (isr.select("project_id", F.col("role").alias("source_type"),
                       F.explode(F.array(F.struct(F.lit("pdo_progress").alias("dimension"), F.col("pdo_current").alias("rating")),
                                         F.struct(F.lit("implementation_progress").alias("dimension"), F.col("ip_current").alias("rating")))).alias("r"),
                       # the archive date printed in the ISR is when the rating was given; the catalog date can be later
                       F.coalesce("archived_on", "doc_date").alias("as_of"),
                       F.concat(F.lit("ISR sequence "), F.coalesce(F.col("seq_no").cast("string"), F.lit("?"))).alias("source"),
                       "doc_id", doc_url("txt_url").alias("doc_url"))
            .select("project_id", "source_type", "r.dimension", "r.rating", "as_of", "source", "doc_id", "doc_url")
            .filter("rating IS NOT NULL"))
evidence = (ieg_rows.unionByName(icr_rows).unionByName(isr_rows)
            .withColumn("score", F.try_element_at(score_map, F.col("rating")).cast("int"))
            # 4 = Moderately Satisfactory: the satisfactory line used in the Bank's outcome statistics
            .withColumn("is_satisfactory", F.col("score") >= 4)
            .withColumn("independence", F.when(F.col("source_type") == "ieg_validation", "independent").otherwise("self_reported")))
n_evidence = publish_table(
    evidence, EVIDENCE_TABLE,
    "Project performance ratings from several sources (p09). Grain: one row per project x source_type x dimension. "
    "Scores: six-point scale, Highly Unsatisfactory 1 ... Highly Satisfactory 6. Input format of proc_intel.evidence.resolve_evidence().",
    {"project_id": "PK, FK dim_project", "source_type": "PK. ieg_validation, icr_self_rating, isr_last, isr_earlier",
     "dimension": "PK. outcome (ICR, IEG), pdo_progress or implementation_progress (ISR)",
     "rating": "Six-point rating label", "as_of": "Date of the rating",
     "source": "Human-readable source (ISR sequence number, evaluation FY, ICR document id)",
     "doc_id": "Documents API id of the document the rating was read from (IEG: the ICR Review)",
     "doc_url": "Document page on documents.worldbank.org", "score": "1 (Highly Unsatisfactory) to 6 (Highly Satisfactory)",
     "is_satisfactory": "score >= 4 (Moderately Satisfactory or better)",
     "independence": "independent (IEG) or self_reported (task team, ICR)"},
    primary_key=["project_id", "source_type", "dimension"])
add_foreign_key(EVIDENCE_TABLE, ["project_id"], f"{SILVER}.dim_project", ["project_id"])
E = spark.table(EVIDENCE_TABLE)
display(dq_report([
    (EVIDENCE_TABLE, "rows", n_evidence, "info"),
    (EVIDENCE_TABLE, "duplicate keys", duplicate_keys(E, ["project_id", "source_type", "dimension"]), "== 0"),
    (EVIDENCE_TABLE, "ratings outside the six-point scale", E.filter("score IS NULL").count(), "== 0"),
    (EVIDENCE_TABLE, "rows without a date", null_count(E, "as_of"), "== 0"),
    (EVIDENCE_TABLE, "orphan project_id", orphan_count(E, "project_id", spark.table(f"{SILVER}.dim_project"), "project_id"), "== 0"),
]))
display(E.groupBy("source_type", "dimension").agg(F.countDistinct("project_id").alias("projects"),
                                                 F.round(F.avg("score"), 2).alias("mean_score"),
                                                 F.round(F.avg(F.col("is_satisfactory").cast("int")), 3).alias("share_satisfactory"))
        .orderBy("source_type", "dimension"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. How often do the sources disagree?
# MAGIC
# MAGIC **What:** one wide row per project (last ISR PDO and IP, earlier ISR PDO, ICR, IEG), then
# MAGIC - the **confusion matrix** of the last ISR's PDO rating against IEG's outcome,
# MAGIC - the **disconnect**: the last ISR rated progress Moderately Satisfactory or better, IEG rated the outcome Moderately Unsatisfactory or worse, as a share of (a) satisfactory last ISRs and (b) projects IEG rated unsatisfactory,
# MAGIC - the same for the ICR self-rating and the mid-period ISR, and by region and sector.
# MAGIC
# MAGIC **Why:** the Bank's own evaluators have long reported that supervision ratings are more optimistic than final evaluations. Here it is measured on this sample, with confidence intervals, so the resolution policy rests on numbers rather than anecdote.

# COMMAND ----------

wide = (E.withColumn("k", F.concat_ws("|", "source_type", "dimension")).groupBy("project_id")
        .pivot("k", ["isr_last|pdo_progress", "isr_last|implementation_progress", "isr_earlier|pdo_progress",
                     "icr_self_rating|outcome", "ieg_validation|outcome"]).agg(F.first("score"))
        .toDF("project_id", "isr_pdo", "isr_ip", "mid_pdo", "icr", "ieg")
        .join(sample.select("project_id", "region", "major_sector", "evaluation_fy"), "project_id").cache())
pdf = wide.toPandas()            # 400 rows
both = pdf.dropna(subset=["isr_pdo", "ieg"])
SCORE_SHORT = {v: SHORT[k] for k, v in SCALE.items()}          # 6 -> 'HS', ..., 1 -> 'HU'
labels = [SCORE_SHORT[v] for v in range(6, 0, -1)]
matrix = (pd.crosstab(both["isr_pdo"].astype(int).map(SCORE_SHORT), both["ieg"].astype(int).map(SCORE_SHORT))
          .reindex(index=labels, columns=labels, fill_value=0))
matrix.index.name, matrix.columns.name = "last ISR PDO rating", "IEG outcome"
print(f"projects with both a last-ISR PDO rating and an IEG outcome: {len(both)}")
display(matrix.reset_index())

# COMMAND ----------

def rate_row(df, earlier: str, label: str) -> dict:
    """Disconnect between an earlier self-rating column and IEG, with Wilson intervals."""
    d = df.dropna(subset=[earlier, "ieg"])
    # two denominators, because they answer different questions: how often a good rating is wrong, and how often a bad
    # outcome was missed
    sat, ieg_unsat = d[d[earlier] >= 4], d[d["ieg"] < 4]
    n_dis = int(((d[earlier] >= 4) & (d["ieg"] < 4)).sum())
    lo1, hi1 = wilson_interval(n_dis, len(sat))
    lo2, hi2 = wilson_interval(n_dis, len(ieg_unsat))
    gap = d[earlier] - d["ieg"]
    return {"earlier rating": label, "projects": len(d), "rated satisfactory": len(sat),
            "IEG unsatisfactory": len(ieg_unsat), "disconnects": n_dis,
            "share of satisfactory ratings that IEG rated unsatisfactory": f"{n_dis / max(len(sat), 1):.1%} ({lo1:.1%}-{hi1:.1%})",
            "share of IEG-unsatisfactory projects still rated satisfactory": f"{n_dis / max(len(ieg_unsat), 1):.1%} ({lo2:.1%}-{hi2:.1%})",
            "mean score gap (earlier - IEG)": round(float(gap.mean()), 2),
            "2+ points apart": int((gap.abs() >= 2).sum()), "earlier lower than IEG": int((gap < 0).sum())}


display(pd.DataFrame([rate_row(pdf, "mid_pdo", "mid-period ISR, PDO"), rate_row(pdf, "isr_pdo", "last ISR, PDO"),
                      rate_row(pdf, "isr_ip", "last ISR, implementation"), rate_row(pdf, "icr", "ICR self-rating")]))

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** the last-ISR disconnect by region and by major sector (groups with at least 15 projects).
# MAGIC
# MAGIC **Why:** if the disconnect concentrates in some regions or sectors, the agent should be more sceptical of supervision ratings there. With 400 projects the groups are small, so the intervals are wide and are printed with the rates.

# COMMAND ----------

def by_group(col: str) -> pd.DataFrame:
    d = pdf.dropna(subset=["isr_pdo", "ieg"])
    rows = []
    for key, g in d.groupby(col):
        # fewer than 15 projects gives intervals too wide to say anything
        if len(g) < 15:
            continue
        n_dis = int(((g["isr_pdo"] >= 4) & (g["ieg"] < 4)).sum())
        n_unsat = int((g["ieg"] < 4).sum())
        lo, hi = wilson_interval(n_dis, int((g["isr_pdo"] >= 4).sum()))
        rows.append({col: key, "projects": len(g), "IEG unsatisfactory": n_unsat,
                     "last ISR satisfactory but IEG unsatisfactory": n_dis,
                     "disconnect rate (of satisfactory ISRs)": f"{n_dis / max(int((g['isr_pdo'] >= 4).sum()), 1):.1%} ({lo:.0%}-{hi:.0%})",
                     "IEG-unsatisfactory missed by the last ISR": f"{n_dis}/{n_unsat}"})
    return pd.DataFrame(rows).sort_values("projects", ascending=False)


display(by_group("region"))
display(by_group("major_sector"))

# COMMAND ----------

# MAGIC %md
# MAGIC **What the numbers say (run of 2026-10-20, 400 projects).**
# MAGIC - The last ISR is more optimistic than IEG: 90.8% of last ISRs rate PDO progress satisfactory, IEG rates 83.0% of outcomes satisfactory.
# MAGIC - Of the 68 projects IEG rated unsatisfactory, **35 (51%) still had a satisfactory PDO rating in their last ISR**; 9.6% of satisfactory last ISRs ended unsatisfactory. Only 4 projects went the other way (last ISR unsatisfactory, IEG satisfactory).
# MAGIC - Mid-period ISRs are noisier in both directions (51 projects 2+ points from IEG, 132 rated lower than IEG): they reflect implementation trouble that is later fixed as often as trouble that persists.
# MAGIC - The ICR is closer to IEG but still self-favourable: IEG rated the outcome lower than the ICR for 91 of 381 projects and higher for 6; 17 of 66 unsatisfactory outcomes (26%) were rated satisfactory by the ICR.
# MAGIC - Regional and sector rates (7%-15%) overlap within their intervals at this sample size; no group can be singled out with confidence. Agriculture has the most disconnects (12 of its 19 unsatisfactory outcomes).
# MAGIC
# MAGIC The consequence for the agent: a satisfactory supervision rating is weak evidence of a good outcome; for an outcome question it must defer to IEG, and where IEG has not rated yet it must say so.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. The resolution policy
# MAGIC
# MAGIC **Evidence attributes.** Every record carries four attributes the policy uses:
# MAGIC
# MAGIC | Attribute | Values | Used for |
# MAGIC |---|---|---|
# MAGIC | source type | ieg_validation, icr_self_rating, isr_last, isr_earlier | rank in the hierarchy |
# MAGIC | independence | independent (IEG) / self-reported (task team, ICR) | confidence; shown to the user |
# MAGIC | recency | `as_of` date | tie-break within a rank; staleness of a status |
# MAGIC | specificity | direct (rates what is asked) / proxy (a related rating, e.g. ISR progress for an outcome question) | confidence |
# MAGIC
# MAGIC **Hierarchy per question type** (best first; within a rank the newest record wins):
# MAGIC
# MAGIC | Question | 1 | 2 | 3 | 4 |
# MAGIC |---|---|---|---|---|
# MAGIC | outcome ("did it achieve its objectives?") | IEG validation | ICR self-rating | last ISR, PDO (proxy) | earlier ISR, PDO (proxy) |
# MAGIC | current status ("how is implementation going?") | newest ISR, implementation progress | newest ISR, PDO progress | older ISRs (history only) | - |
# MAGIC
# MAGIC **Rules.**
# MAGIC 1. **Never pick silently.** The answer comes with every other usable record, each labelled supporting or conflicting, with its date and document id; records the question cannot use are listed as not used.
# MAGIC 2. **Flag.** `conflict` if any record is 2 or more scale points from the answer; `disagreement` if a record is 1 point away but on the other side of the satisfactory line (MS vs MU, the line the Bank's outcome statistics use); else `consistent`; `insufficient` if nothing usable.
# MAGIC 3. **Confidence.** `high`: the answer comes from the top tier (IEG for outcome; a last ISR younger than 12 months for status) and there is no conflict. `medium`: top tier with a conflict, or a lower-tier direct rating with no disagreement (an ICR not yet validated). `low`: a lower tier contradicted, only ISR proxies for an outcome question, or a stale status.
# MAGIC 4. **Status questions compare like with like.** Only ratings of the same (newest) ISR are compared; an older ISR rating that differs is history (`superseded`), not a conflict.
# MAGIC
# MAGIC **Why this order.** IEG's rating is independent and made after closing with the full results framework in hand; the ICR is ex post but self-assessed (IEG downgrades a share of them, measured above); the ISR progress rating is a forward-looking judgement made during implementation, and section 6 shows it is the most optimistic. The policy does not throw the optimistic rating away: a conflict is itself information (the agent can say "supervision rated this Satisfactory until closing; IEG later rated it Moderately Unsatisfactory").

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Gold: `proc_gold.project_evidence_resolution`
# MAGIC
# MAGIC **What:** `resolve_evidence()` applied to every sampled project for both question types (the evidence of 400 projects is a few thousand rows, so it is collected and resolved in plain Python), stored with the full result as JSON.
# MAGIC
# MAGIC **Why:** the agent can read a ready answer with its rationale by SQL, or call the function itself on fresh evidence; both give the same result because both use the same tested code.

# COMMAND ----------

# "today" for the staleness rule: a last ISR older than 12 months cannot give high confidence on current status
REFERENCE_DATE = datetime.now(timezone.utc).date()
by_project: dict[str, list[dict]] = {}
# a few thousand rows: resolve in plain Python with the same tested function the agent calls
for r in E.collect():
    by_project.setdefault(r.project_id, []).append(r.asDict())
resolved = []
for pid, recs in by_project.items():
    for qt in HIERARCHY:
        res = resolve_evidence(recs, qt, reference_date=REFERENCE_DATE)
        ans = res["answer"] or {}
        resolved.append({"project_id": pid, "question_type": qt, "answer_rating": ans.get("rating"),
                         "answer_score": ans.get("score"), "answer_source_type": ans.get("source_type"),
                         "answer_as_of": ans.get("as_of"), "answer_doc_id": ans.get("doc_id"), "flag": res["flag"],
                         "confidence": res["confidence"], "n_supporting": len(res["supporting"]),
                         "n_conflicting": len(res["conflicting"]), "rationale": res["rationale"],
                         "resolution_json": json.dumps(res, default=str)})
res_schema = ("project_id string, question_type string, answer_rating string, answer_score int, answer_source_type string, "
              "answer_as_of string, answer_doc_id string, flag string, confidence string, n_supporting int, "
              "n_conflicting int, rationale string, resolution_json string")
res_df = spark.createDataFrame(resolved, res_schema).withColumn("answer_as_of", F.to_date("answer_as_of"))
n_res = publish_table(
    res_df, RESOLUTION_TABLE,
    "Resolved project rating per question type (p09), from proc_silver.project_ratings_evidence via "
    "proc_intel.evidence.resolve_evidence(). Grain: one row per project x question_type.",
    {"project_id": "PK, FK dim_project", "question_type": "PK. outcome or current_status",
     "answer_rating": "Rating chosen by the hierarchy", "answer_score": "Its score (1-6)",
     "answer_source_type": "Source of the answer", "answer_as_of": "Date of the answer's rating",
     "answer_doc_id": "Document the answer cites", "flag": "consistent, disagreement, conflict or insufficient",
     "confidence": "high, medium or low", "n_supporting": "Records supporting the answer",
     "n_conflicting": "Records conflicting with it", "rationale": "Explanation with dates and document ids",
     "resolution_json": "Full resolve_evidence() output"},
    primary_key=["project_id", "question_type"])
add_foreign_key(RESOLUTION_TABLE, ["project_id"], f"{SILVER}.dim_project", ["project_id"])
R = spark.table(RESOLUTION_TABLE)
display(R.groupBy("question_type", "flag", "confidence").count().orderBy("question_type", "flag", "confidence"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Demo: ten conflicting projects
# MAGIC
# MAGIC **What:** ten projects whose outcome evidence is flagged (conflict or disagreement), disconnect cases first (last ISR satisfactory, IEG unsatisfactory), then hash order, with the ratings side by side and the resolved answer and rationale.
# MAGIC
# MAGIC **Why:** shows what the agent would say for exactly the cases where a naive "take the latest document" or "take any rating" would mislead.

# COMMAND ----------

demo = (R.filter("question_type = 'outcome' AND flag IN ('conflict', 'disagreement')")
        .join(wide.select("project_id", "mid_pdo", "isr_pdo", "icr", "ieg"), "project_id")
        .withColumn("_disconnect", (F.col("isr_pdo") >= 4) & (F.col("ieg") < 4))
        .orderBy(F.desc("_disconnect"), F.sha2("project_id", 256)).limit(10)
        .join(spark.table(f"{SILVER}.dim_project").select("project_id", "project_name", "region"), "project_id"))
short_map = F.create_map(*[x for v, abbr in SCORE_SHORT.items() for x in (F.lit(v), F.lit(abbr))])
short = lambda c: F.try_element_at(short_map, F.col(c).cast("int"))
display(demo.select("project_id", F.substring("project_name", 1, 45).alias("project"), "region",
                    short("mid_pdo").alias("mid_ISR"), short("isr_pdo").alias("last_ISR"),
                    short("icr").alias("ICR"), short("ieg").alias("IEG"),
                    "answer_rating", "answer_source_type", "confidence", "rationale").orderBy("project_id"))

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** the full `resolve_evidence()` output for the first demo project, as the agent receives it.
# MAGIC
# MAGIC **Why:** the agent's answer template can quote the answer, list the conflicting sources with their dates and links, and carry the confidence label through to the user.

# COMMAND ----------

first = demo.orderBy("project_id").first()
print(json.dumps(json.loads(first.resolution_json), indent=1)[:3500])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC **What:** the headline numbers as the notebook's exit value.
# MAGIC
# MAGIC **Why:** a job run shows them without opening the notebook. (In its own cell: output displayed in the same cell as `dbutils.notebook.exit` is dropped from the run record.)

# COMMAND ----------

dis = rate_row(pdf, "isr_pdo", "last ISR, PDO")
summary = {"projects": len(project_ids), "evidence_rows": n_evidence, "ieg_parse_match": f"{n_match}/{n_check}",
           "last_isr_vs_ieg_projects": dis["projects"], "disconnects": dis["disconnects"],
           "outcome_flags": {r.flag: r["count"] for r in R.filter("question_type = 'outcome'").groupBy("flag").count().collect()}}
print(summary)

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
