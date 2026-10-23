# Databricks notebook source
# MAGIC %md
# MAGIC # p14_execution_monitoring — early warnings for active projects
# MAGIC
# MAGIC During execution a task team wants to know, before the next supervision mission, which projects are slipping: tenders stuck long past their expected signing, contracts that took far longer than their peers, money not flowing, closing dates being pushed, supervision ratings turning, fiduciary risk going up. This notebook builds those six indicators from open data for every active project with procurement activity, combines them into a rule-based alert with reasons and citations, and checks on closed projects whether the ISR-based signals foreshadowed a poor final evaluation.

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <pre class="mermaid">
# MAGIC ---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC ---
# MAGIC flowchart LR
# MAGIC     s1["proc_gold.open_tender_scores (p07)"]
# MAGIC     s2["proc_gold.tender_timelines + benchmarks"]
# MAGIC     s3["FinancesOne loan / credit statements<br/>(IBRD DS00975, IDA DS00976;<br/>Sep 2026 and Sep 2024 snapshots)"]
# MAGIC     s5["latest ISR text (Documents API)"]
# MAGIC     subgraph ind["indicators"]
# MAGIC         i1["1 stalled tenders<br/>open longer than their P90"]
# MAGIC         i2["2 slow signings<br/>recent contracts above the slow threshold"]
# MAGIC         i3["3 disbursement lag<br/>disbursed share vs peers at the same point in time"]
# MAGIC         i4["4 closing extended<br/>closing date moved since the Sep 2024 statement"]
# MAGIC         i5["5 ISR ratings<br/>PDO / IP below MS, or downgraded"]
# MAGIC         i6["6 fiduciary risk<br/>SORT fiduciary High, or Substantial and raised"]
# MAGIC     end
# MAGIC     alert["proc_intel.monitoring.indicators() then alert():<br/>red / amber / watch / none"]
# MAGIC     ew["proc_gold.early_warnings<br/>(reasons + citations per project)"]
# MAGIC     s1 --> i1
# MAGIC     s2 --> i2
# MAGIC     s3 --> i3
# MAGIC     s3 --> i4
# MAGIC     s5 --> i5
# MAGIC     s5 --> i6
# MAGIC     ind --> alert --> ew
# MAGIC </pre>
# MAGIC <script type="module">
# MAGIC   import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.esm.min.mjs";
# MAGIC   import elkLayouts from "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.1.7/dist/mermaid-layout-elk.esm.min.mjs";
# MAGIC   mermaid.registerLayoutLoaders(elkLayouts);
# MAGIC   mermaid.initialize({ startOnLoad: true });
# MAGIC </script>

# COMMAND ----------

# MAGIC %md
# MAGIC <details><summary>Text version of the diagram</summary>
# MAGIC
# MAGIC ```
# MAGIC  proc_gold.open_tender_scores (p07) ------> 1 stalled tenders      open longer than their P90
# MAGIC  proc_gold.tender_timelines + benchmarks -> 2 slow signings       recent contracts above the slow threshold
# MAGIC  FinancesOne loan / credit statements ----> 3 disbursement lag    disbursed share vs peers at the same point in time
# MAGIC   (IBRD DS00975, IDA DS00976; Sep 2026  -> 4 closing extended   closing date moved since the Sep 2024 statement
# MAGIC    and Sep 2024 snapshots)
# MAGIC  latest ISR text (Documents API) ---------> 5 ISR ratings        PDO / IP below MS, or downgraded
# MAGIC                                         -> 6 fiduciary risk      SORT fiduciary High, or Substantial and raised
# MAGIC                                                    |
# MAGIC                         proc_intel.monitoring.indicators() -> alert(): red / amber / watch / none
# MAGIC                                                    v
# MAGIC                          proc_gold.early_warnings (reasons + citations per project)
# MAGIC ```
# MAGIC
# MAGIC </details>
# MAGIC
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_bronze.loan_statements` | one IBRD loan or IDA credit in one monthly statement snapshot | `loan_id, end_of_period` |
# MAGIC | `proc_bronze.monitoring_isr_documents` | the latest ISR read for a sampled active project, with parsed ratings | `project_id` |
# MAGIC | `proc_gold.early_warnings` | one active project: indicators, alert level, reasons, citations | `project_id` |
# MAGIC
# MAGIC Indicator and alert rules are pure functions in `src/proc_intel/monitoring.py` (`indicators(p)`, `alert(indicators)`, `parse_sort_ratings(text)`), tested in `tests/test_monitoring.py`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## How it was built and tested
# MAGIC
# MAGIC **Step 1 — Is there a procurement rating in the ISR?**
# MAGIC - **Question:** the brief asks for procurement-specific supervision signals; do ISRs rate procurement?
# MAGIC - **What we found:** in the 400 last ISRs that p09 read (closed projects, 2017-2025), not one prints a "Procurement" rating line (older ISR templates had one; these do not). 398 of 400 print the SORT risk table, whose **Fiduciary** row (financial management and procurement together) gives the rating at approval, the last approved rating and the proposed one.
# MAGIC - **Decision:** the procurement signal from the ISR is the SORT fiduciary rating, next to PDO and implementation-progress ratings (previous and current in the same ISR, so a downgrade is visible from one document).
# MAGIC
# MAGIC **Step 2 — Where is disbursement data?**
# MAGIC - **Question:** the Projects API has disbursement fields; are they usable?
# MAGIC - **What we found:** the Projects API's financial fields lag: for P160446 its disbursement (US$ 90.08 million on one loan) and closing date (30 June 2025) equal the FinancesOne statement of September **2024**, while the September 2026 statement says US$ 133.9 million and 31 December 2025. Its rating fields are lists without the ISR they came from, and it keeps no history. The FinancesOne statements of IBRD loans and IDA credits are monthly snapshots (end of period 30 September 2026) with original, cancelled and disbursed amounts and the current closing date per loan, and an older snapshot can be selected with a filter.
# MAGIC - **Decision:** disbursement and closing dates from FinancesOne (latest and two years earlier); the Projects API only for the lending instrument, which does not change. Disbursement lag is judged for investment projects only: development policy and Program-for-Results operations disburse in tranches or against results.
# MAGIC
# MAGIC **Step 3 — Thresholds and the alert**
# MAGIC - **Question:** what counts as a warning?
# MAGIC - **What we found:** fixed thresholds are easy to explain and to audit; the disbursement threshold needs a peer reference because projects disburse slowly at first.
# MAGIC - **Decision:** stalled = at least one open tender past its P90; slow signings = half or more of 3+ recent timed contracts above their peer group's slow threshold; disbursement lag = disbursed share at least 20 points below the peer median at the same elapsed decile (after the first quarter of the period); closing extended = moved 6+ months in two years; ISR = PDO or IP below Moderately Satisfactory, or downgraded; fiduciary = High, or Substantial and raised since approval. Red = 3+ indicators, or ISR ratings together with a disbursement lag; amber = 2; watch = 1.
# MAGIC
# MAGIC **Step 4 — Do the ISR signals warn early?**
# MAGIC - **Question:** is an ISR signal at mid-term informative about the final outcome?
# MAGIC - **What we found:** the 400 closed projects of p09 have a mid-period ISR text in the volume and IEG's outcome rating.
# MAGIC - **Decision:** section 6 parses the same signals from those mid-period ISRs and compares IEG's unsatisfactory rate for flagged and unflagged projects: a backtest of indicators 5 and 6 at no extra download.
# MAGIC
# MAGIC **Step 5 — The ISR text layout changed again in 2026**
# MAGIC - **Question:** why did the first run need an older ISR for 119 of 300 projects?
# MAGIC - **What we found:** for 127 of the 300 projects the newest ISR's text rendering prints the ratings table one cell per line ("Progress towards achievement of PDO" / "Moderately Unsatisfactory" / "Moderately Satisfactory") instead of fixed-width columns, so p09's parser read nothing and the code silently fell back to an older ISR (8 more projects list no ISR at all). The same happened in p09 with the 2024 template.
# MAGIC - **Decision:** a second parser for the cell-per-line layout (`monitoring.parse_isr_cells`; the SORT parser reads both layouts), the layout stored per ISR, and the fallback count shown in section 4, so a third layout change would show up as a jump in `needed_fallback` instead of passing unnoticed.

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
# MAGIC **What:** snapshot dates, the ISR sample size, folders and table names.
# MAGIC
# MAGIC **Why:** all raw responses (statement pages, project instruments, ISR listings and texts) are saved in the bronze volume, so a re-run reads them instead of calling the APIs again.

# COMMAND ----------

import hashlib
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests

from proc_intel import monitoring as mon
from proc_intel.evidence import parse_isr_ratings
from proc_intel.http import RETRYABLE_STATUS, get_json, retry_delay
from proc_intel.ingest import parse_wb_date
from proc_intel.similarity import wilson_interval

AS_OF = date(2026, 9, 30)                    # latest FinancesOne statement
BEFORE = date(2024, 9, 30)                   # comparison statement for closing-date moves
STATEMENTS = {"DS00975": "IBRD loans", "DS00976": "IDA credits and grants"}
ACTIVE_STATUSES = ("Disbursing", "Disbursing&Repaying", "Effective", "Signed", "Approved")
ISR_SAMPLE = 300
RECENT_DAYS = 730
DOCS_URL = "https://search.worldbank.org/api/v3/wds"
PROJECTS_URL = "https://search.worldbank.org/api/v2/projects"
MON_DIR = f"{RAW_VOLUME}/monitoring"
LOANS_TABLE = f"{BRONZE}.loan_statements"
ISR_TABLE = f"{BRONZE}.monitoring_isr_documents"
WARN_TABLE = f"{GOLD}.early_warnings"
for sub in ["statements", "isr_lists", "isr_docs"]:
    os.makedirs(f"{MON_DIR}/{sub}", exist_ok=True)
HTTP = requests.Session()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Loan and credit statements: `proc_bronze.loan_statements`
# MAGIC
# MAGIC **What:** the IBRD and IDA statements for 30 September 2026 and 30 September 2024 (FinancesOne `filter=end_of_period='...'`, pages of 5,000), normalised to one schema: loan id, project, status, original / cancelled / disbursed / undisbursed amount (US$), approval and current closing date.
# MAGIC
# MAGIC **Why:** these are the Bank's own monthly figures per loan; the two snapshots show how closing dates moved. IDA amounts are the US$ columns of the IDA statement.

# COMMAND ----------

def pull_statement(ds: str, period: date) -> list[dict]:
    label = period.strftime("%d-%b-%Y")
    path = f"{MON_DIR}/statements/{ds}_{period.isoformat()}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows, skip = [], 0
    while True:
        body = get_json(AWARDS_URL, {"datasetId": ds, "resourceId": ds.replace("DS", "RS"), "type": "json", "top": 5000,
                                     "skip": skip, "filter": f"end_of_period='{label}'"}, session=HTTP)
        rows += body["data"]
        skip += 5000
        if skip >= body["count"]:
            break
    with open(path, "w") as f:
        json.dump(rows, f)
    return rows


def normalise(r: dict, ds: str) -> dict:
    ida = ds == "DS00976"
    g = (lambda k: r.get(f"{k}_us_")) if ida else r.get
    return {"loan_id": r.get("credit_number") if ida else r.get("loan_number"), "source": STATEMENTS[ds],
            "project_id": r.get("project_id"), "status": r.get("credit_status") if ida else r.get("loan_status"),
            "end_of_period": parse_wb_date(r.get("end_of_period")), "original_amount": float(g("original_principal_amount") or 0),
            "cancelled_amount": float(g("cancelled_amount") or 0), "disbursed_amount": float(g("disbursed_amount") or 0),
            "undisbursed_amount": float(g("undisbursed_amount") or 0), "approval_date": parse_wb_date(r.get("board_approval_date")),
            "closing_date": parse_wb_date(r.get("closed_date_most_recent")), "country_code": r.get("country_code")}


loan_rows = [normalise(r, ds) for ds in STATEMENTS for period in (AS_OF, BEFORE) for r in pull_statement(ds, period)]
loan_schema = ("loan_id string, source string, project_id string, status string, end_of_period date, original_amount double, "
               "cancelled_amount double, disbursed_amount double, undisbursed_amount double, approval_date date, "
               "closing_date date, country_code string")
loans_df = spark.createDataFrame(loan_rows, loan_schema).filter("loan_id IS NOT NULL").dropDuplicates(["loan_id", "end_of_period"])
n_loans = publish_table(
    loans_df.withColumn("_loaded_at", F.current_timestamp()), LOANS_TABLE,
    "IBRD loan and IDA credit statements (FinancesOne DS00975 / DS00976), snapshots 2026-09-30 and 2024-09-30 (p14). "
    "Grain: one loan or credit in one statement.",
    {"loan_id": "PK. Loan or credit number", "source": "IBRD loans or IDA credits and grants", "project_id": "Project id",
     "status": "Loan status (Disbursing, Repaying, ...)", "end_of_period": "PK. Statement date",
     "original_amount": "Original principal (US$)", "cancelled_amount": "Cancelled (US$)", "disbursed_amount": "Disbursed (US$)",
     "undisbursed_amount": "Undisbursed (US$)", "approval_date": "Board approval date", "closing_date": "Closing date (most recent)",
     "country_code": "Country code", "_loaded_at": "Load time"},
    primary_key=["loan_id", "end_of_period"])
L = spark.table(LOANS_TABLE)
display(L.groupBy("end_of_period", "source").agg(F.count("*").alias("loans"),
                                                 F.sum(F.col("status").isin(*ACTIVE_STATUSES).cast("int")).alias("active")).orderBy("end_of_period", "source"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Active projects and the lending instrument
# MAGIC
# MAGIC **What:** projects of the procurement model (`dim_project`) with at least one loan or credit in an active status and a closing date on or after 30 September 2026; their lending instrument from the Projects API (active projects, pages of 1,000).
# MAGIC
# MAGIC **Why:** "active" by the Bank's own loan statement is current to the month; `dim_project.status` comes from the Projects API extract of 15 October 2026 and does not say whether money can still be disbursed.

# COMMAND ----------

def project_instruments() -> dict:
    path = f"{MON_DIR}/project_instruments.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    out, os_ = {}, 0
    while True:
        body = get_json(PROJECTS_URL, {"format": "json", "status_exact": "Active", "fl": "id,lendinginstr", "rows": 1000, "os": os_},
                        session=HTTP)
        for p in body.get("projects", {}).values():
            out[p["id"]] = p.get("lendinginstr")
        os_ += 1000
        if os_ >= int(body["total"]):
            break
    with open(path, "w") as f:
        json.dump(out, f)
    return out


instruments = project_instruments()
active_loans = L.filter((F.col("end_of_period") == F.lit(AS_OF)) & F.col("status").isin(*ACTIVE_STATUSES)
                        & (F.col("closing_date") >= F.lit(AS_OF)))
active = (spark.table(f"{SILVER}.dim_project").select("project_id", "project_name", "country_code", "region", "major_sector",
                                                       "outcome_risk_band")
          .join(active_loans.select("project_id").distinct(), "project_id"))
instr_df = spark.createDataFrame([(k, v) for k, v in instruments.items()], "project_id string, instrument string")
active = active.join(instr_df, "project_id", "left").cache()
n_dim_active = spark.table(f"{SILVER}.dim_project").filter("status = 'Active'").count()
print(f"active projects (loan statement 2026-09-30) in the procurement model: {active.count():,}; "
      f"dim_project status 'Active' (Projects API): {n_dim_active:,}")
display(active.groupBy(F.coalesce("instrument", F.lit("(not in the Projects API)")).alias("instrument")).count().orderBy(F.desc("count")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Indicators 1-4 from tables and statements
# MAGIC
# MAGIC **What:**
# MAGIC 1. **stalled tenders:** open notices of the project in `open_tender_scores` with `past_p90` (scored by p07's model on 2026-10-20);
# MAGIC 2. **slow signings:** contracts of the project signed in the last 24 months with a measured duration, and how many exceeded the slow threshold of their method x category (`tender_benchmarks`, P75 of the training years);
# MAGIC 3. **disbursement position:** `monitoring.disbursement_position()` over the project's non-cancelled loans in the latest statement; the peer curve is the median disbursed share per elapsed decile over active investment projects;
# MAGIC 4. **closing date** now and in the September 2024 statement (latest closing date over the project's loans present in both).
# MAGIC
# MAGIC **Why:** each indicator is computed from a source that a monitoring job could refresh daily (scores, timelines) or monthly (statements).

# COMMAND ----------

pids = [r.project_id for r in active.select("project_id").collect()]
info = {r.project_id: r.asDict() for r in active.collect()}
stalled = {}
for r in (spark.table(f"{GOLD}.open_tender_scores").filter("past_p90").filter(F.col("project_id").isin(pids))
          .select("project_id", "notice_id", "days_elapsed", "p90_days").collect()):
    stalled.setdefault(r.project_id, []).append({"notice_id": r.notice_id, "days_elapsed": int(r.days_elapsed), "p90_days": int(r.p90_days)})
slow_thr = (spark.table(f"{GOLD}.tender_benchmarks").filter("benchmark_level = 'method_category'")
            .select("procurement_method_name", "procurement_category_code", "slow_threshold_days"))
recent = (spark.table(f"{GOLD}.tender_timelines")
          .filter(F.col("is_timed") & (F.col("signing_date") >= F.date_sub(F.lit(AS_OF), RECENT_DAYS)))
          .filter(F.col("project_id").isin(pids))
          .join(slow_thr, ["procurement_method_name", "procurement_category_code"])
          .withColumn("slow", F.col("days_notice_to_signing") > F.col("slow_threshold_days")))
recent_by = {r.project_id: r for r in recent.groupBy("project_id").agg(
    F.count("*").alias("n"), F.sum(F.col("slow").cast("int")).alias("n_slow"),
    F.slice(F.collect_list(F.when(F.col("slow"), F.col("contract_id"))), 1, 3).alias("slow_ids")).collect()}

stmt = L.filter(~F.col("status").isin("Fully Cancelled", "Terminated")).toPandas()
now, before = stmt[stmt.end_of_period == AS_OF], stmt[stmt.end_of_period == BEFORE]
position, closing = {}, {}
for pid, g in now[now.project_id.isin(pids)].groupby("project_id"):
    pos = mon.disbursement_position(g.to_dict("records"), AS_OF)
    if pos:
        position[pid] = {**pos, "loan_ids": sorted(g.loan_id)}
    common = before[(before.project_id == pid) & before.loan_id.isin(g.loan_id)]
    if len(common):
        closing[pid] = (g[g.loan_id.isin(common.loan_id)].closing_date.max(), common.closing_date.max())
ipf = [p for p in position if info[p].get("instrument") == "Investment Project Financing"]
deciles = pd.DataFrame([{"d": min(int(position[p]["elapsed_share"] * 10), 9), "s": position[p]["disbursed_share"]} for p in ipf])
curve = deciles.groupby("d").s.median().to_dict()
display(deciles.groupby("d").s.agg(["count", "median"]).rename_axis("elapsed decile").reset_index().round(3))
print(f"projects with a disbursement position: {len(position)} (investment projects {len(ipf)}); "
      f"with a closing date in both statements: {len(closing)}; with stalled tenders: {len(stalled)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Indicators 5-6: the latest ISR of 300 sampled projects
# MAGIC
# MAGIC **What:** active projects with procurement activity (a stalled or open tender, or a contract signed in the last 24 months), in hash order, the first 300; for each, the newest ISR from the Documents API (listing and text saved in the volume), parsed with `parse_isr_ratings()` (p09's parser: PDO and IP, previous and current) and `monitoring.parse_sort_ratings()` (fiduciary rating at approval and now). If the newest ISR has no readable ratings, the next older one is tried (up to 3).
# MAGIC
# MAGIC **Why:** one document per project keeps the download bounded; hash order keeps the sample unrelated to the outcome.

# COMMAND ----------

def get_text(url: str, max_retries: int = 5) -> str | None:
    for attempt in range(max_retries + 1):
        try:
            resp = HTTP.get(url, timeout=120)
            if resp.status_code in (403, 404, 410):
                return None
            if resp.status_code not in RETRYABLE_STATUS:
                resp.raise_for_status()
                return resp.content.decode("utf-8", errors="replace")
            delay = retry_delay(attempt, resp.text, resp.headers.get("Retry-After"))
        except (requests.ConnectionError, requests.Timeout):
            delay = retry_delay(attempt)
        time.sleep(delay + random.uniform(0, 1))
    raise RuntimeError(f"giving up on {url}")


def latest_isr(project_id: str) -> dict:
    lpath = f"{MON_DIR}/isr_lists/{project_id}.json"
    if os.path.exists(lpath):
        with open(lpath) as f:
            docs = json.load(f)
    else:
        body = get_json(DOCS_URL, {"format": "json", "proid": project_id, "docty_exact": "Implementation Status and Results Report",
                                   "rows": 20, "srt": "docdt", "order": "desc", "fl": "id,docdt,txturl"}, session=HTTP)
        docs = sorted([d for k, d in body.get("documents", {}).items() if k != "facets" and d.get("txturl")],
                      key=lambda d: d.get("docdt") or "", reverse=True)
        with open(lpath, "w") as f:
            json.dump(docs, f)
    for tried, d in enumerate(docs[:3], start=1):
        path = f"{MON_DIR}/isr_docs/{d['id']}.txt"
        if os.path.exists(path + ".missing"):
            continue
        if not os.path.exists(path):
            text = get_text(d["txturl"].replace("http://", "https://"))
            if text is None:
                open(path + ".missing", "w").close()
                continue
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        r, s, layout = parse_isr_ratings(text), mon.parse_sort_ratings(text), "fixed-width"
        if not (r.get("pdo_current") or r.get("ip_current")):
            r, layout = mon.parse_isr_cells(text), "cell-per-line"
        if r.get("pdo_current") or r.get("ip_current"):
            fid = s.get("Fiduciary", {})
            return {"project_id": project_id, "doc_id": d["id"], "doc_date": d["docdt"][:10], "n_listed": len(docs), "n_tried": tried,
                    "layout": layout,
                    "archived_on": r["archived_on"].isoformat() if r.get("archived_on") else None, "seq_no": r.get("seq_no"),
                    "pdo_previous": r.get("pdo_previous"), "pdo_current": r.get("pdo_current"),
                    "ip_previous": r.get("ip_previous"), "ip_current": r.get("ip_current"),
                    "fiduciary_approval": fid.get("approval"), "fiduciary_current": fid.get("current"),
                    "overall_risk_current": s.get("Overall", {}).get("current"), "file_path": path}
    return {"project_id": project_id, "doc_id": None, "n_listed": len(docs), "n_tried": min(len(docs), 3)}


recent_ids = {r.project_id for r in recent.select("project_id").distinct().collect()}
open_ids = {r.project_id for r in spark.table(f"{GOLD}.open_tender_scores").select("project_id").distinct().collect()}
with_activity = sorted(p for p in pids if p in recent_ids or p in open_ids)
isr_pids = sorted(with_activity, key=lambda p: hashlib.sha256(p.encode()).hexdigest())[:ISR_SAMPLE]
t0 = time.time()
with ThreadPoolExecutor(max_workers=4) as pool:
    isr_rows = list(pool.map(latest_isr, isr_pids))
print(f"active projects with procurement activity: {len(with_activity)}; ISRs read for {len(isr_rows)} in {time.time() - t0:.0f} s")
isr_schema = ("project_id string, doc_id string, doc_date string, n_listed int, n_tried int, layout string, archived_on string, seq_no int, "
              "pdo_previous string, pdo_current string, ip_previous string, ip_current string, fiduciary_approval string, "
              "fiduciary_current string, overall_risk_current string, file_path string")
cols = [c.split()[0] for c in isr_schema.split(", ")]
isr_df = (spark.createDataFrame([{c: r.get(c) for c in cols} for r in isr_rows], isr_schema)
          .withColumn("doc_date", F.to_date("doc_date")).withColumn("archived_on", F.to_date("archived_on")))
n_isr = publish_table(
    isr_df, ISR_TABLE,
    "Latest ISR read for sampled active projects (p14), with PDO / IP ratings and the SORT fiduciary rating. Grain: one project.",
    {"project_id": "PK, FK dim_project", "doc_id": "Documents API id (null: no readable ISR)", "doc_date": "Document date",
     "n_listed": "ISRs listed (up to 20 newest)", "n_tried": "ISRs read until one had ratings",
     "layout": "Text rendering layout: fixed-width (columns) or cell-per-line (2026 renderings)", "archived_on": "ISR archive date",
     "seq_no": "ISR sequence number", "pdo_previous": "PDO rating, previous ISR", "pdo_current": "PDO rating, this ISR",
     "ip_previous": "Implementation progress, previous ISR", "ip_current": "Implementation progress, this ISR",
     "fiduciary_approval": "SORT fiduciary risk at approval", "fiduciary_current": "SORT fiduciary risk, proposed / current",
     "overall_risk_current": "SORT overall risk, current", "file_path": "Saved text in the bronze volume"},
    primary_key=["project_id"])
add_foreign_key(ISR_TABLE, ["project_id"], f"{SILVER}.dim_project", ["project_id"])
I = spark.table(ISR_TABLE)
display(I.agg(F.count("*").alias("projects"), F.count("doc_id").alias("readable_isr"), F.count("fiduciary_current").alias("with_fiduciary"),
              F.sum((F.col("n_tried") > 1).cast("int")).alias("needed_fallback"),
              F.sum((F.col("layout") == "cell-per-line").cast("int")).alias("cell_per_line_layout"),
              F.sum((F.datediff(F.lit(AS_OF), "archived_on") > 365).cast("int")).alias("older_than_12_months")))
display(I.groupBy("fiduciary_approval", "fiduciary_current").count().orderBy(F.desc("count")).limit(12))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Indicators, alerts and `proc_gold.early_warnings`
# MAGIC
# MAGIC **What:** for every active project, the inputs above go into `monitoring.indicators()`, then `monitoring.alert()`; the result is stored with each indicator's status and value (JSON), the alert level, the reasons and the citations (`notice:`, `contract:`, `loan:`, `document:` ids).
# MAGIC
# MAGIC **Why:** a project manager reads the reasons; an agent can quote them and cite the records; a dashboard can filter by level and indicator. Projects without an ISR read show those two indicators as `no_data`, never as "ok".

# COMMAND ----------

isr_by = {r["project_id"]: r for r in isr_rows if r.get("doc_id")}
warn_rows = []
for pid in pids:
    pos, rec, isr = position.get(pid), recent_by.get(pid), isr_by.get(pid)
    is_ipf = info[pid].get("instrument") == "Investment Project Financing"
    p = {"as_of": AS_OF, "stalled_tenders": stalled.get(pid, []),
         "recent_timed": rec.n if rec else 0, "recent_slow": rec.n_slow if rec else 0, "recent_slow_ids": rec.slow_ids if rec else [],
         "disbursed_share": pos["disbursed_share"] if pos and is_ipf else None,
         "elapsed_share": pos["elapsed_share"] if pos and is_ipf else None,
         "expected_share": mon.expected_share(curve, pos["elapsed_share"]) if pos and is_ipf else None,
         "loan_ids": pos["loan_ids"] if pos else [],
         "closing_now": closing[pid][0] if pid in closing else None, "closing_before": closing[pid][1] if pid in closing else None,
         "window_start": BEFORE,
         "isr": None if not isr else {"doc_id": isr["doc_id"], "pdo_prev": isr["pdo_previous"], "pdo_cur": isr["pdo_current"],
                                      "ip_prev": isr["ip_previous"], "ip_cur": isr["ip_current"],
                                      "fiduciary_approval": isr["fiduciary_approval"], "fiduciary_current": isr["fiduciary_current"],
                                      "as_of": date.fromisoformat(isr["archived_on"] or isr["doc_date"])}}
    inds = mon.indicators(p)
    a = mon.alert(inds)
    st = {i["indicator"]: i["status"] for i in inds}
    warn_rows.append({"project_id": pid, "as_of": AS_OF, "alert_level": a["level"], "n_triggered": a["n_triggered"],
                      "n_no_data": a["n_no_data"], "triggered": a["triggered"], "reasons": a["reasons"], "citations": a["citations"],
                      **{f"ind_{k}": v for k, v in st.items()},
                      "disbursed_share": pos["disbursed_share"] if pos else None, "elapsed_share": pos["elapsed_share"] if pos else None,
                      "n_stalled_tenders": len(stalled.get(pid, [])), "isr_doc_id": isr["doc_id"] if isr else None,
                      "instrument": info[pid].get("instrument"), "indicators_json": json.dumps(inds, default=str)})
warn = pd.DataFrame(warn_rows)
ind_names = [c for c in warn.columns if c.startswith("ind_")]
w_schema = ("project_id string, as_of date, alert_level string, n_triggered int, n_no_data int, triggered array<string>, "
            "reasons array<string>, citations array<string>, " + ", ".join(f"{c} string" for c in ind_names)
            + ", disbursed_share double, elapsed_share double, n_stalled_tenders int, isr_doc_id string, instrument string, "
              "indicators_json string")
w_cols = [c.split()[0] for c in w_schema.split(", ")]
w_records = [[r.get(c) for c in w_cols] for r in warn_rows]
n_warn = publish_table(
    spark.createDataFrame(w_records, w_schema).withColumn("built_at", F.current_timestamp()), WARN_TABLE,
    "Early-warning view of active projects (p14): six indicators (stalled tenders, slow signings, disbursement lag, closing "
    "extended, ISR ratings, fiduciary risk), a rule-based alert, reasons and citations. Grain: one active project.",
    {"project_id": "PK, FK dim_project", "as_of": "Statement date the indicators refer to", "alert_level": "red, amber, watch or none",
     "n_triggered": "Indicators triggered", "n_no_data": "Indicators without data (not counted as ok)",
     "triggered": "Names of the triggered indicators", "reasons": "One sentence per triggered indicator",
     "citations": "Record ids behind the reasons (notice:, contract:, loan:, document:)",
     **{c: f"Status of indicator {c[4:]}: triggered, ok or no_data" for c in ind_names},
     "disbursed_share": "Disbursed / (original - cancelled), all loans", "elapsed_share": "Share of the approval-to-closing period elapsed",
     "n_stalled_tenders": "Open tenders past their P90", "isr_doc_id": "ISR read (sampled projects only)",
     "instrument": "Lending instrument (Projects API)", "indicators_json": "Full indicator output", "built_at": "Build time"},
    primary_key=["project_id"])
add_foreign_key(WARN_TABLE, ["project_id"], f"{SILVER}.dim_project", ["project_id"])
W = spark.table(WARN_TABLE)
display(dq_report([
    (LOANS_TABLE, "statement rows", n_loans, "info"),
    (ISR_TABLE, "sampled projects", n_isr, f"<= {ISR_SAMPLE}"),
    (WARN_TABLE, "active projects", n_warn, "info"),
    (WARN_TABLE, "duplicate project_id", duplicate_keys(W, ["project_id"]), "== 0"),
    (WARN_TABLE, "triggered alerts without a citation", W.filter("n_triggered > 0 AND size(citations) = 0").count(), "== 0"),
    (WARN_TABLE, "orphan project_id", orphan_count(W, "project_id", spark.table(f"{SILVER}.dim_project"), "project_id"), "== 0"),
]))
coverage = pd.DataFrame([{"indicator": c[4:], **warn[c].value_counts().to_dict()} for c in ind_names]).fillna(0)
display(coverage)
display(W.groupBy("alert_level").agg(F.count("*").alias("projects"),
                                     F.sum(F.col("isr_doc_id").isNotNull().cast("int")).alias("with_isr")).orderBy("alert_level"))

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** the red alerts among the projects with an ISR read, with their reasons and citations.
# MAGIC
# MAGIC **Why:** this is what the early-warning view would put in front of a manager.

# COMMAND ----------

display(W.filter("alert_level = 'red' AND isr_doc_id IS NOT NULL")
        .join(spark.table(f"{SILVER}.dim_project").select("project_id", "project_name", "country_code"), "project_id")
        .select("project_id", F.substring("project_name", 1, 45).alias("project"), "country_code", "triggered", "reasons", "citations")
        .orderBy(F.desc(F.size("triggered")), "project_id").limit(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Backtest of the ISR signals on closed projects
# MAGIC
# MAGIC **What:** the 400 closed projects of p09: the mid-period ISR (role `isr_earlier`, already in the volume) is parsed for the same two signals (PDO / IP below MS or downgraded; fiduciary High, or Substantial and raised), and IEG's outcome rating (`project_ratings_evidence`) is the target. For each signal: IEG-unsatisfactory share among flagged and unflagged projects, with Wilson intervals.
# MAGIC
# MAGIC **Why:** an early warning is only useful if it comes before the outcome. Mid-period ISRs are written years before IEG rates the project.

# COMMAND ----------

mid = (spark.table(f"{BRONZE}.rating_documents").filter("role = 'isr_earlier' AND file_path IS NOT NULL")
       .select("project_id", "file_path", "pdo_previous", "pdo_current", "ip_previous", "ip_current").toPandas())
ieg = {r.project_id: r.score for r in spark.table(f"{SILVER}.project_ratings_evidence").filter("source_type = 'ieg_validation'").collect()}
bt = []
for r in mid.itertuples():
    if r.project_id not in ieg:
        continue
    with open(r.file_path, encoding="utf-8") as f:
        fid = mon.parse_sort_ratings(f.read()).get("Fiduciary", {})
    bt.append({"project_id": r.project_id, "ieg_unsat": ieg[r.project_id] < 4,
               "isr_signal": mon.isr_signal(r.pdo_previous, r.pdo_current, r.ip_previous, r.ip_current)["triggered"],
               "fiduciary_known": fid.get("current") is not None,
               "fiduciary_signal": mon.fiduciary_signal(fid.get("approval"), fid.get("current"))["triggered"],
               "fiduciary_substantial_or_high": mon.RISK_SCALE.get(fid.get("current") or "", 0) >= 3})
bt = pd.DataFrame(bt)
rows = []
for sig, base in [("isr_signal", bt), ("fiduciary_signal", bt[bt.fiduciary_known]), ("fiduciary_substantial_or_high", bt[bt.fiduciary_known])]:
    for flag in (True, False):
        g = base[base[sig] == flag]
        lo, hi = wilson_interval(int(g.ieg_unsat.sum()), len(g))
        rows.append({"signal at mid-period ISR": sig, "flagged": flag, "projects": len(g), "IEG unsatisfactory": int(g.ieg_unsat.sum()),
                     "share (95% CI)": f"{g.ieg_unsat.mean():.1%} ({lo:.1%}-{hi:.1%})" if len(g) else "-"})
display(pd.DataFrame(rows))

# COMMAND ----------

# MAGIC %md
# MAGIC **What the numbers say (run of 2026-10-21; statements of 30 September 2026).**
# MAGIC - **Population:** 1,340 projects of the procurement model have an active loan or credit; 1,053 of them show procurement activity, 300 of those had their latest ISR read (286 readable; 120 in the new cell-per-line layout, 1 needed an older ISR).
# MAGIC - **Indicators triggered** (of the projects with data): stalled tenders 429 of 1,340; slow signings 121 of 512; disbursement lag 175 of 979 investment projects; closing date moved 6+ months 315 of 1,012; ISR ratings 62 of 286; fiduciary risk 51 of 285.
# MAGIC - **Alerts:** red 73, amber 238, watch 447, none 582. Projects without an ISR read can reach at most four indicators, so their alerts are a lower bound; `n_no_data` says how many indicators were unknown.
# MAGIC - **Backtest on 400 closed projects:** when the mid-period ISR rated PDO or IP below Moderately Satisfactory or downgraded it, IEG later rated the outcome unsatisfactory in 23.8% of cases (17.1-32.1%) vs 14.0% (10.4-18.6%) otherwise, a 1.7x lift; the fiduciary signal gives 24.1% vs 15.9%, with overlapping intervals. Both are early signals worth surfacing, neither is a forecast on its own.
# MAGIC - **Caveat on stalled tenders:** an open notice past its P90 is either slow, cancelled, or signed under a reference p05 could not link; the reason text says "past its P90", not "late".

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. What open data cannot show, and what production would connect
# MAGIC
# MAGIC | Need for contract-level monitoring | Open data here | Production source |
# MAGIC |---|---|---|
# MAGIC | Contract milestones (planned vs actual: bid opening, evaluation, award, signature, delivery, completion) | only notice dates and the signing date; nothing after signing | **STEP** (Systematic Tracking of Exchanges in Procurement): every activity of the procurement plan with planned and actual dates per step, and contract management records for prior-review contracts |
# MAGIC | Contract amendments, variations, time extensions, price adjustments | none (the awards feed has one row per contract, no amendment history) | STEP amendment records; the borrower's contract management system |
# MAGIC | Payments against contracts, retention, advance payments | none (disbursement only per loan, monthly) | **Client Connection** / loan disbursement system (withdrawal applications, direct payments per contract, statements of expenditure) |
# MAGIC | Procurement risk and capacity of the implementing agency | the ISR's SORT fiduciary rating (FM and procurement together) | **PRAMS** (Procurement Risk Assessment and Management System) ratings from project preparation, updated during supervision; procurement post-review reports |
# MAGIC | Complaints, misprocurement, debarment of the winning firm | debarment list is public but not joined here | STEP complaints module; the World Bank debarment list joined on supplier entity (p04) |
# MAGIC | Supervision findings between ISRs | none | Aide-memoires and back-to-office reports (internal) |
# MAGIC
# MAGIC With those feeds the same design applies: each source becomes one or more indicators in `monitoring.indicators()`, each with a status, a reason and the record ids, and the alert rule stays a small, auditable function. Contract-level slippage would compare actual milestone dates with the planned dates in STEP and with the p07 duration benchmarks of the peer group.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC **What:** the headline numbers as the notebook's exit value.
# MAGIC
# MAGIC **Why:** a job run shows them without opening the notebook.

# COMMAND ----------

summary = {"active_projects": n_warn, "isr_sampled": n_isr, "isr_readable": len(isr_by),
           "alerts": warn.alert_level.value_counts().to_dict(),
           "triggered_by_indicator": {c[4:]: int((warn[c] == "triggered").sum()) for c in ind_names},
           "backtest_projects": len(bt)}
print(summary)

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
