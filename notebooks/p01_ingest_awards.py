# Databricks notebook source
# MAGIC %md
# MAGIC # p01_ingest_awards — contract awards → `proc_bronze.contract_awards`
# MAGIC
# MAGIC Source: World Bank **Contract Awards in Investment Project Financing** (FinancesOne dataset `DS00005`): every contract signed under an IPF project since FY2020, about 295k rows, refreshed daily.
# MAGIC
# MAGIC | Step | Output |
# MAGIC |---|---|
# MAGIC | 1. Download every page, saving each page as it arrives (resumable) | `proc_bronze.raw/awards/<snapshot>/page_*.json` |
# MAGIC | 2. Read the pages with an explicit schema, add lineage columns and a deterministic key | DataFrame |
# MAGIC | 3. `MERGE` into bronze (insert new, update changed, flag withdrawn) | `proc_bronze.contract_awards` |
# MAGIC | 4. Checks: row count vs the API's `count`, key uniqueness, a second `MERGE` that must change nothing | printed |
# MAGIC
# MAGIC Bronze grain: **one row per (contract, supplier)** exactly as delivered. Nothing is cleaned here; `p03_silver_model` builds the contract and supplier tables.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key design decisions
# MAGIC
# MAGIC | Decision | Rationale | Evidence |
# MAGIC |---|---|---|
# MAGIC | Page the API at 10,000 rows per call (30 calls of about 10 MB); the retry helper reads the HTTP 429 retry hint | No bulk file is available; large pages are close to bulk speed and still cheap to retry | The old Socrata CSV link redirects to FinancesOne and returns 404; `top=50000` returned 50,000 rows (52 MB) in about 6 seconds; the API answered HTTP 429 "Try again in 24 seconds" once during probing |
# MAGIC | Bronze key = SHA-256 of `wb_contract_number`, `supplier_id` and `supplier` | Bronze grain is one row per (contract, supplier); the key must stay unique even for the row without a `supplier_id` | 295,058 rows, 282,890 distinct `wb_contract_number`s; 8,864 joint-venture contracts have 2 to 10+ rows; `(wb_contract_number, supplier_id)` is unique; one row has no `supplier_id` (its supplier text is a broken fragment, "EMPHNET)") |
# MAGIC | `_row_hash` covers the business columns only; changed rows are updated, unchanged rows left alone, rows missing from a full snapshot get `_removed_at_source` (soft delete) | Re-runs must not rewrite the table daily | `as_of_date` changes every day on every row; the notebook runs the same `MERGE` twice and the second run changes nothing |
# MAGIC
# MAGIC Full reasoning: docs/decision_log.md

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

# MAGIC %md
# MAGIC ## Settings
# MAGIC
# MAGIC **What:** page size and the snapshot folder.
# MAGIC
# MAGIC **Why:** the snapshot folder is named by the UTC date, so a run that fails halfway and is restarted the same day reuses the pages already saved instead of downloading them again.

# COMMAND ----------

import json
import time
from datetime import datetime, timezone

from proc_intel.http import get_json
from proc_intel.ingest import page_file_name, page_offsets

# 10k rows is about 10 MB per call: near bulk speed, cheap to retry (top=50000 also works but one failure costs more)
PAGE_SIZE = 10_000
# UTC date, so a restart later the same day lands in the same folder and reuses the saved pages
SNAPSHOT = datetime.now(timezone.utc).strftime("%Y-%m-%d")
SNAPSHOT_DIR = f"{RAW_VOLUME}/awards/{SNAPSHOT}"
TARGET = f"{BRONZE}.contract_awards"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Download every page (resumable)
# MAGIC
# MAGIC **What:** asks the API for one row to learn the total `count`, then fetches each 10,000-row page that is not already saved and writes the untouched response to its own file. Finally checks that the saved pages add up to `count`.
# MAGIC
# MAGIC **Why:** one file per page means a failure loses at most one page, and a restart skips finished pages. The final check makes a partial download fail loudly instead of quietly loading half the data. `sleep(1)` between calls is polite to a public API.

# COMMAND ----------

os.makedirs(SNAPSHOT_DIR, exist_ok=True)
# a one-row call is the cheapest way to learn the total row count
total = get_json(AWARDS_URL, {**AWARDS_PARAMS, "top": 1, "skip": 0})["count"]

fetched = 0
for skip in page_offsets(total, PAGE_SIZE):
    path = f"{SNAPSHOT_DIR}/{page_file_name(skip)}"
    # resume: pages saved by an earlier, interrupted run are not downloaded again
    if os.path.exists(path):
        continue
    body = get_json(AWARDS_URL, {**AWARDS_PARAMS, "top": PAGE_SIZE, "skip": skip})
    with open(path, "w") as f:
        json.dump(body, f)
    fetched += 1
    # public API that has already answered 429 once; one second between pages keeps us polite
    time.sleep(1)

saved_rows = 0
for name in sorted(os.listdir(SNAPSHOT_DIR)):
    with open(f"{SNAPSHOT_DIR}/{name}") as f:
        saved_rows += len(json.load(f)["data"])
print(f"API count {total:,} | pages fetched now {fetched} | rows in snapshot {saved_rows:,}")
# fail here rather than load a partial snapshot, which would then soft-delete the rows we did not fetch
assert saved_rows == total, "snapshot is incomplete"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Read the pages into a DataFrame with lineage
# MAGIC
# MAGIC **What:** reads all page files with an **explicit schema**, explodes the `data` array into rows and adds:
# MAGIC - `award_row_key` — the deterministic key (Step 2 above);
# MAGIC - `_row_hash` — change detector over the business columns;
# MAGIC - lineage: `_source` (dataset id), `_source_file` (the page file), `_ingested_at`, `_snapshot_date`, and `as_of_date` parsed to a date.
# MAGIC
# MAGIC **Why:** an explicit schema stops Spark guessing types differently from one snapshot to the next (for example reading `supplier_id` as a number would turn hashed ids into nulls). Lineage columns let anyone trace a bronze row back to the exact file and day it came from.

# COMMAND ----------

from pyspark.sql.types import DoubleType, LongType, StringType, StructField, StructType, ArrayType

# explicit types: schema inference could read supplier_id as a number on some snapshot and null the hashed ids
AWARD_FIELDS = {
    "as_of_date": StringType(), "borrower_contract_reference_number": StringType(),
    "borrower_country": StringType(), "borrower_country_code": StringType(),
    "contract_description": StringType(), "contract_signing_date": StringType(),
    "fiscal_year": LongType(), "contract_signed___calendar_year": LongType(),
    "procurement_category": StringType(), "procurement_method": StringType(),
    "project_global_practice": StringType(), "project_id": StringType(), "project_name": StringType(),
    "region": StringType(), "review_type": StringType(), "supplier": StringType(),
    "supplier_contract_amount_usd": DoubleType(), "supplier_country": StringType(),
    "supplier_country_code": StringType(), "supplier_id": StringType(), "wb_contract_number": StringType(),
}
page_schema = StructType([
    StructField("count", LongType()),
    StructField("data", ArrayType(StructType([StructField(k, t) for k, t in AWARD_FIELDS.items()]))),
])

raw = (spark.read.schema(page_schema).option("multiLine", True).json(f"{SNAPSHOT_DIR}/*.json")
       # one input row per page file; explode turns its data array into one row per award, keeping the page path as
       # lineage
       .select(F.explode("data").alias("r"), F.col("_metadata.file_path").alias("_source_file"))
       .select("r.*", "_source_file")
       .withColumnRenamed("contract_signed___calendar_year", "contract_signed_calendar_year"))
# compare business columns only: as_of_date changes daily, so hashing it would rewrite every row on every run
business_cols = [c for c in raw.columns if c not in ("as_of_date", "_source_file")]
awards = (raw
          # grain is contract x supplier (joint ventures have one row per member); supplier text is included because one
          # row has no supplier_id
          .withColumn("award_row_key", F.sha2(F.concat_ws("|", "wb_contract_number",
                                                            F.coalesce("supplier_id", F.lit("")), "supplier"), 256))
          .withColumn("_row_hash", row_hash(business_cols))
          .withColumn("as_of_date", F.to_date("as_of_date", "dd-MMM-yyyy"))
          .withColumn("_source", F.lit(AWARDS_SOURCE))
          .withColumn("_snapshot_date", F.lit(SNAPSHOT).cast("date"))
          .withColumn("_ingested_at", F.current_timestamp()))
print("rows read:", awards.count())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. MERGE into bronze
# MAGIC
# MAGIC **What:** upserts on `award_row_key` with `merge_upsert()` (from `proc_common`), soft-deleting rows that are no longer in this full snapshot.
# MAGIC
# MAGIC **Why:** the first run inserts everything; later runs insert only new contracts and update only corrected ones. This is a full snapshot, so marking missing rows as withdrawn is safe.

# COMMAND ----------

# mark_removed is safe only because this is a full snapshot (checked by the assert above)
first = merge_upsert(awards, TARGET, key="award_row_key", mark_removed=True)
spark.sql(f"COMMENT ON TABLE {TARGET} IS 'Contract awards (FinancesOne DS00005) as delivered: one row per contract x supplier. "
          "supplier_contract_amount_usd repeats the contract amount on each joint-venture member row. "
          "Key award_row_key = sha256(wb_contract_number|supplier_id|supplier).'")
print("first MERGE :", first)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Checks
# MAGIC
# MAGIC **What:** runs the identical `MERGE` again, then counts rows, keys and withdrawn rows.
# MAGIC
# MAGIC **Why:** the second `MERGE` must insert 0 and update 0 rows — that is what "idempotent" means in practice. The key checks prove the key really is unique; the snapshot comparison proves bronze holds exactly what the API reported.

# COMMAND ----------

# same input again: an idempotent MERGE must insert 0 and update 0 rows
second = merge_upsert(awards, TARGET, key="award_row_key", mark_removed=True)
print("second MERGE:", second)

bronze = spark.table(TARGET)
current = bronze.filter("_removed_at_source IS NULL")
checks = [
    (TARGET, "rows (current)", current.count(), f"== {total}"),
    (TARGET, "rows withdrawn at source", bronze.count() - current.count(), "info"),
    (TARGET, "duplicate award_row_key", duplicate_keys(bronze, ["award_row_key"]), "== 0"),
    # rows without supplier_id are excluded: the one such row is unique only through its supplier text
    (TARGET, "duplicate (wb_contract_number, supplier_id)", duplicate_keys(current.filter("supplier_id IS NOT NULL"),
                                                                          ["wb_contract_number", "supplier_id"]), "== 0"),
    (TARGET, "distinct wb_contract_number", current.select("wb_contract_number").distinct().count(), "info"),
    (TARGET, "second MERGE inserted + updated", second["numTargetRowsInserted"] + second["numTargetRowsUpdated"], "== 0"),
]
display(dq_report(checks))
display(current.groupBy("fiscal_year").count().orderBy("fiscal_year"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run summary
# MAGIC
# MAGIC **What:** returns the key counts as the notebook's exit value.
# MAGIC
# MAGIC **Why:** a job run shows the exit value without opening the notebook.

# COMMAND ----------

summary = {"api_count": total, "bronze_rows": current.count(), "snapshot": SNAPSHOT,
           "first_merge": first, "second_merge": second}
print(summary)
dbutils.notebook.exit(json.dumps(summary))
