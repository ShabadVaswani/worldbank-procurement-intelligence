# Databricks notebook source
# MAGIC %md
# MAGIC # p14_execution_monitoring — early warnings for active projects
# MAGIC
# MAGIC During execution a task team wants to know, before the next supervision mission, which projects are slipping: tenders stuck long past their expected signing, contracts that took far longer than their peers, money not flowing, closing dates being pushed, supervision ratings turning, fiduciary risk going up. This notebook builds those six indicators from open data for every active project with procurement activity, combines them into a rule-based alert with reasons and citations, and checks on closed projects whether the ISR-based signals foreshadowed a poor final evaluation.

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <img src="data:image/png;base64,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" alt="execution_monitoring diagram" style="max-width:100%; width:1630px"/>
# MAGIC

# COMMAND ----------

# MAGIC %md
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_bronze.loan_statements` | one IBRD loan or IDA credit in one monthly statement snapshot | `loan_id, end_of_period` |
# MAGIC | `proc_bronze.monitoring_isr_documents` | the latest ISR read for a sampled active project, with parsed ratings | `project_id` |
# MAGIC | `proc_gold.early_warnings` | one active project: indicators, alert level, reasons, citations | `project_id` |
# MAGIC
# MAGIC Indicator and alert rules are pure functions in `src/proc_intel/monitoring.py` (`indicators(p)`, `alert(indicators)`, `parse_sort_ratings(text)`), tested in `tests/test_monitoring.py`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key design decisions
# MAGIC
# MAGIC | Decision | Rationale | Evidence |
# MAGIC |---|---|---|
# MAGIC | The ISR procurement signal is the SORT Fiduciary rating, next to PDO and implementation-progress ratings (previous and current in the same ISR) | Current ISR templates have no procurement rating line; a downgrade is visible from one document | In the 400 last ISRs that p09 read (closed projects, 2017-2025) none prints a "Procurement" rating line; 398 of 400 print the SORT risk table, whose Fiduciary row gives the rating at approval, the last approved and the proposed one |
# MAGIC | Disbursement and closing dates from FinancesOne (latest and two years earlier); the Projects API only for the lending instrument; disbursement lag judged for investment projects only | The Projects API's financial fields lag and keep no history; development policy and Program-for-Results operations disburse in tranches or against results | For P160446 the Projects API shows US$ 90.08 million on one loan and closing 30 June 2025, equal to the FinancesOne statement of September 2024, while September 2026 says US$ 133.9 million and 31 December 2025; FinancesOne statements are monthly snapshots (end of period 30 September 2026) and older snapshots can be selected |
# MAGIC | Fixed thresholds: stalled = an open tender past its P90; slow signings = half or more of 3+ recent timed contracts above the peer slow threshold; disbursement lag = disbursed share at least 20 points below the peer median at the same elapsed decile (after the first quarter); closing extended = moved 6+ months in two years; ISR = PDO or IP below Moderately Satisfactory, or downgraded; fiduciary = High, or Substantial and raised since approval. Red = 3+ indicators, or ISR ratings with a disbursement lag; amber = 2; watch = 1 | Fixed thresholds are easy to explain and audit; disbursement needs a peer reference | Projects disburse slowly at first |
# MAGIC | Indicators 5 and 6 backtested on the mid-period ISRs of p09's 400 closed projects against IEG's unsatisfactory rate (section 6) | Tests whether ISR signals warn early, at no extra download | These projects have a mid-period ISR text in the volume and IEG's outcome rating |
# MAGIC | A second parser for the cell-per-line layout (`monitoring.parse_isr_cells`; the SORT parser reads both layouts); layout stored per ISR; fallback count shown in section 4 | A layout change otherwise causes a silent fallback to older ISRs; a further change would show as a jump in `needed_fallback` | An initial run needed an older ISR for 119 of 300 projects: for 127 of the 300 the newest ISR used the 2026 cell-per-line layout (8 more list no ISR at all); p09 saw the same with the 2024 template |
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
# "recent" signings for indicator 2: the last 24 months before the statement date
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
    # the FinancesOne filter expects the end_of_period date in the feed's own dd-Mon-yyyy text format
    label = period.strftime("%d-%b-%Y")
    path = f"{MON_DIR}/statements/{ds}_{period.isoformat()}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows, skip = [], 0
    while True:
        # same FinancesOne endpoint as the awards feed, different dataset; the resource id mirrors the dataset id
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
    # the IDA statement has amounts in several currencies; its US$ columns end in "_us_"
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
# active by the loan statement: an active status and a closing date not yet passed on the statement date
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
# p07's slow threshold is defined per method x category, so only that level is read
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

# cancelled and terminated loans would pull the disbursed share down without saying anything about progress
stmt = L.filter(~F.col("status").isin("Fully Cancelled", "Terminated")).toPandas()
now, before = stmt[stmt.end_of_period == AS_OF], stmt[stmt.end_of_period == BEFORE]
position, closing = {}, {}
for pid, g in now[now.project_id.isin(pids)].groupby("project_id"):
    pos = mon.disbursement_position(g.to_dict("records"), AS_OF)
    if pos:
        position[pid] = {**pos, "loan_ids": sorted(g.loan_id)}
    # compare closing dates only over loans present in both statements; a new loan added later is not an extension
    common = before[(before.project_id == pid) & before.loan_id.isin(g.loan_id)]
    if len(common):
        closing[pid] = (g[g.loan_id.isin(common.loan_id)].closing_date.max(), common.closing_date.max())
# the peer curve uses investment projects only: development policy and program-for-results financing disburse on a
# different pattern
ipf = [p for p in position if info[p].get("instrument") == "Investment Project Financing"]
# min(..., 9): a project exactly at (or past) its closing date belongs in the last decile
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
            # some listed documents have no text rendering; that is an answer, not an error to retry
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
    # up to three newest ISRs: the newest one sometimes has no readable ratings block
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
        # the 2026 text renderings print one table cell per line; fall back to that parser when the fixed-width one
        # finds nothing
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
# hash order keeps the sample unrelated to how the projects are doing
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
         # non-investment projects get no disbursement-lag judgement (no_data), as their disbursement pattern differs
         "disbursed_share": pos["disbursed_share"] if pos and is_ipf else None,
         "elapsed_share": pos["elapsed_share"] if pos and is_ipf else None,
         "expected_share": mon.expected_share(curve, pos["elapsed_share"]) if pos and is_ipf else None,
         "loan_ids": pos["loan_ids"] if pos else [],
         "closing_now": closing[pid][0] if pid in closing else None, "closing_before": closing[pid][1] if pid in closing else None,
         "window_start": BEFORE,
         "isr": None if not isr else {"doc_id": isr["doc_id"], "pdo_prev": isr["pdo_previous"], "pdo_cur": isr["pdo_current"],
                                      "ip_prev": isr["ip_previous"], "ip_cur": isr["ip_current"],
                                      "fiduciary_approval": isr["fiduciary_approval"], "fiduciary_current": isr["fiduciary_current"],
                                      # the archive date is when the ratings were given; the document date is only a
                                      # fallback
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
    # every triggered indicator must point to a record a user can open
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
# backtest ground truth: IEG's outcome from p09; below 4 (Moderately Satisfactory) counts as unsatisfactory
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
# fiduciary signals are compared only where the mid-period ISR printed a SORT table, so "unknown" is not counted as "no
# signal"
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
