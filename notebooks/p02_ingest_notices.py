# Databricks notebook source
# MAGIC %md
# MAGIC # p02_ingest_notices — procurement notices → `proc_bronze.procurement_notices`
# MAGIC
# MAGIC Source: World Bank **procurement notices** search API (`search.worldbank.org/api/v2/procnotices`): every notice published through STEP since 2005 — invitations for bids, requests for expressions of interest, contract award notices, general procurement notices. About 423k notices.
# MAGIC
# MAGIC | Step | Output |
# MAGIC |---|---|
# MAGIC | 1. List the partitions (one per project country) with their sizes | `raw/notices/<snapshot>/_partitions.json` |
# MAGIC | 2. Page each country newest-first until a whole page predates 2018 (resumable, 4 countries in parallel) | `raw/notices/<snapshot>/<country>/page_*.json` |
# MAGIC | 3. Read the pages with an explicit schema, add lineage, `MERGE` on the notice `id` | `proc_bronze.procurement_notices` |
# MAGIC | 4. Checks: per-country completeness, duplicates, notice types and years | printed |
# MAGIC
# MAGIC Bronze grain: **one row per notice id**. The HTML `notice_text` is kept (useful later for retrieval and for the bidder lists inside award notices). Contact person names, e-mails, phone numbers and addresses are **not requested** (data minimisation).

# COMMAND ----------

# MAGIC %md
# MAGIC ## How it was built and tested
# MAGIC
# MAGIC **Step 1 — Plain offset paging cannot reach most of the data**
# MAGIC - **Question:** can we page through all 423k notices with `rows` and `os` (offset)?
# MAGIC - **What we found:** no. The API sits on Azure Cognitive Search, and an offset above 100,000 fails with "Value must be between 0 and 100000 ($skip)". A simple loop would silently stop at about a quarter of the notices. Pages are also capped at 1,000 rows.
# MAGIC - **Decision:** split the work into partitions that each hold fewer than 100,000 notices.
# MAGIC
# MAGIC **Step 2 — How to partition**
# MAGIC - **Question:** which filter splits the data reliably? We wanted a date filter (only notices from 2018 are needed).
# MAGIC - **What we found:** the date parameters (`strdate`/`enddate`, `fq=noticedate:[...]`, `noticedate_exact`) are ignored or rejected. The facet filter `project_ctry_name_exact` works: 184 values whose counts add up **exactly** to the total, the largest being India with 47,452.
# MAGIC - **Alternatives considered:**
# MAGIC   - *Date windows* (the preferred design): split adaptively, halving any window that returns more than 100,000, and reconcile the windows' sum with the total. Not possible here, because the API ignores date filters.
# MAGIC   - *Id ranges or `id % n`*: also even and complete, but the API offers no range or modulo filter on `id`; splitting after download does not help, because the full set cannot be downloaded in the first place.
# MAGIC - **Decision:** one partition per project country, the only filter the API honours. The 2018 cutoff is applied by ordering instead (Step 3), and a completeness check against the total guards the gaps a facet split can leave (Step 5).
# MAGIC
# MAGIC **Step 3 — A stable order, and the 2018 cutoff**
# MAGIC - **Question:** how do we page without skipping or repeating notices, and stop at 2018?
# MAGIC - **What we found:** the default order is by notice date, which has many ties, so the same offset can return different rows on two calls. Sorting by `id` is unique, and ids are issued in time order (`OP00000005` is from September 2005; about 50k ids predate mid-2018).
# MAGIC - **Decision:** sort by `id` newest first and stop a country when a whole page is older than 2018-01-01. Newest-first also tolerates notices published *during* the run: a new notice pushes everything down by one, which repeats a row (removed by the `MERGE` key) but never skips one.
# MAGIC
# MAGIC **Step 4 — Page size and politeness**
# MAGIC - **Question:** how big should a page be?
# MAGIC - **What we found:** 1,000 rows with `notice_text` took 17 s once and 3 s another time; 500 rows consistently took about 2 s (about 2 MB).
# MAGIC - **Decision:** 500 rows per page, 4 countries in parallel, retries with exponential backoff. Every page is saved as a file, so a restart skips finished pages and finished countries.
# MAGIC
# MAGIC **Step 5 — Notices without a country**
# MAGIC - **Question:** do the country partitions still cover everything on a later run?
# MAGIC - **What we found:** no. On the first run the facet counts added up exactly to the total; on a re-run about 20 hours later 200 notices were missing from every facet. They were recent notices published without a project country (184 of the newest 1,000 had none; the last of the 200 was found about 37,500 notices deep). The completeness assert caught it.
# MAGIC - **Decision:** measure the gap (total minus facet counts) and read the unfiltered feed newest-first until that many country-less notices are saved, instead of asserting that the gap is zero.

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

# MAGIC %md
# MAGIC ## Settings
# MAGIC
# MAGIC **What:** the field list, page size, parallelism and snapshot folder.
# MAGIC
# MAGIC **Why:** `fl` asks only for the fields we use and leaves out personal contact data. The snapshot folder is named by the UTC date, so a same-day restart resumes.

# COMMAND ----------

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from proc_intel.http import get_json
from proc_intel.ingest import page_file_name, page_is_older_than, partition_folder, slugify

NOTICE_FIELDS = [
    "id", "notice_type", "noticedate", "notice_lang_name", "notice_status",
    "submission_date", "submission_deadline_date", "submission_deadline_time",
    "project_ctry_name", "project_id", "project_name", "bid_reference_no", "bid_description",
    "procurement_group", "procurement_method_code", "procurement_method_name",
    "contact_organization", "contact_ctry_name", "notice_text",
]
PAGE_SIZE = 500
MAX_OFFSET = 100_000          # API limit on `os`
PARALLEL_COUNTRIES = 4
SNAPSHOT = datetime.now(timezone.utc).strftime("%Y-%m-%d")
SNAPSHOT_DIR = f"{RAW_VOLUME}/notices/{SNAPSHOT}"
TARGET = f"{BRONZE}.procurement_notices"
BASE_PARAMS = {"format": "json", "srt": "id", "order": "desc", "fl": ",".join(NOTICE_FIELDS)}

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Partitions
# MAGIC
# MAGIC **What:** asks the API for the facet counts of `project_ctry_name_exact`, saves them, measures how many notices no country facet covers (notices published without a project country), and checks that no country exceeds the offset limit.
# MAGIC
# MAGIC **Why:** these counts are the yardstick for the completeness check at the end. If a country ever grew past 100,000 notices, this assert would say so before any data went missing. Each country gets a folder named by a readable slug plus a short hash of the exact name, because two facet values can share a slug.

# COMMAND ----------

os.makedirs(SNAPSHOT_DIR, exist_ok=True)
facet_body = get_json(NOTICES_URL, {"format": "json", "rows": 1, "fl": "id", "fct": "project_ctry_name_exact"})
partitions = {v["name"]: int(v["count"]) for v in facet_body["facets"]["project_ctry_name_exact"].values()}
with open(f"{SNAPSHOT_DIR}/_partitions.json", "w") as f:
    json.dump({"total": int(facet_body["total"]), "partitions": partitions}, f)

API_TOTAL = int(facet_body["total"])
NO_COUNTRY_GAP = API_TOTAL - sum(partitions.values())   # notices the country facet cannot reach
print(f"API total {API_TOTAL:,} | covered by country facets {sum(partitions.values()):,} | without a country: {NO_COUNTRY_GAP:,}")
assert max(partitions.values()) < MAX_OFFSET, "a country is too large for offset paging"
print(f"{len(partitions)} countries, {sum(partitions.values()):,} notices, largest {max(partitions.values()):,}")
names = pd.Series(sorted(partitions))
by_slug = names.groupby(names.map(slugify)).agg(list)
print("names that share a slug:", by_slug[by_slug.map(len) > 1].tolist())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Page each country (resumable, parallel)
# MAGIC
# MAGIC **What:** `fetch_country()` pages one country newest-first. A page already on disk is read instead of fetched. It stops when a page is short (the country is exhausted) or entirely older than the cutoff, then writes a `_COMPLETE` file with the row count and the reason it stopped. Countries run 4 at a time, largest first.
# MAGIC
# MAGIC **Why:** the `_COMPLETE` marker lets a restart skip whole countries; the stop reason is evidence that each country was read to its end or to the cutoff, not abandoned. Each page file also records the API's `total` for that country, which must equal the facet count. A last pass reads the unfiltered feed newest-first until it has the notices that carry no country (see Step 5 above); its stop reason says whether all were found.

# COMMAND ----------

def fetch_country(country: str) -> dict:
    folder = f"{SNAPSHOT_DIR}/{partition_folder(country)}"
    marker = f"{folder}/_COMPLETE"
    if os.path.exists(marker):
        with open(marker) as f:
            return json.load(f)
    os.makedirs(folder, exist_ok=True)
    offset, rows, api_total = 0, 0, None
    while True:
        path = f"{folder}/{page_file_name(offset)}"
        if os.path.exists(path):
            with open(path) as f:
                page = json.load(f)
        else:
            body = get_json(NOTICES_URL, {**BASE_PARAMS, "project_ctry_name_exact": country,
                                          "rows": PAGE_SIZE, "os": offset})
            page = {"country": country, "offset": offset, "total": int(body.get("total", 0)),
                    "procnotices": body.get("procnotices", [])}
            with open(path, "w") as f:
                json.dump(page, f)
        api_total = page["total"]
        notices = page["procnotices"]
        rows += len(notices)
        if len(notices) < PAGE_SIZE:
            reason = "exhausted"
            break
        if page_is_older_than(notices, NOTICE_CUTOFF):
            reason = "reached cutoff"
            break
        offset += PAGE_SIZE
        if offset >= MAX_OFFSET:
            raise RuntimeError(f"{country}: offset limit reached before the cutoff")
    status = {"country": country, "rows": rows, "pages": offset // PAGE_SIZE + 1,
              "api_total": api_total, "facet_count": partitions[country], "stop": reason}
    with open(marker, "w") as f:
        json.dump(status, f)
    return status


def fetch_without_country(expected: int) -> dict:
    """Page the unfiltered feed newest-first until `expected` notices without a country are saved.

    Those notices are invisible to the country partitions. They are recent (on 2026-10-20 all 200
    were within the newest 37,500 notices), so the pass stops early; the stop rules match fetch_country.
    """
    folder = f"{SNAPSHOT_DIR}/_no_country"
    os.makedirs(folder, exist_ok=True)
    offset, found, rows = 0, 0, 0
    reason = "nothing to fetch" if expected <= 0 else None
    while reason is None:
        path = f"{folder}/{page_file_name(offset)}"
        if os.path.exists(path):
            with open(path) as f:
                page = json.load(f)
        else:
            body = get_json(NOTICES_URL, {**BASE_PARAMS, "rows": PAGE_SIZE, "os": offset})
            page = {"country": None, "offset": offset, "total": int(body.get("total", 0)),
                    "procnotices": body.get("procnotices", [])}
            with open(path, "w") as f:
                json.dump(page, f)
        notices = page["procnotices"]
        rows += len(notices)
        found += sum(1 for n in notices if not n.get("project_ctry_name"))
        offset += PAGE_SIZE
        if found >= expected:
            reason = "all found"
        elif len(notices) < PAGE_SIZE or page_is_older_than(notices, NOTICE_CUTOFF) or offset >= MAX_OFFSET:
            reason = "stopped before finding all"
    return {"country": "<no country>", "rows": rows, "pages": offset // PAGE_SIZE, "api_total": None,
            "facet_count": expected, "found_without_country": found, "stop": reason}


countries = sorted(partitions, key=partitions.get, reverse=True)
with ThreadPoolExecutor(max_workers=PARALLEL_COUNTRIES) as pool:
    fetch_status = pd.DataFrame(list(pool.map(fetch_country, countries)))
no_country_status = fetch_without_country(NO_COUNTRY_GAP)
print(fetch_status["stop"].value_counts().to_dict(), "| rows saved:", int(fetch_status["rows"].sum()))
print("notices without a project country:", no_country_status)
display(fetch_status.sort_values("facet_count", ascending=False).head(15))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Read the pages and MERGE into bronze
# MAGIC
# MAGIC **What:** reads every page file with an explicit all-string schema, keeps one row per `id` (a notice can be seen twice if it was published during the run), adds lineage (`_source`, `_source_file`, `_snapshot_date`, `_ingested_at`, `as_of_date` = snapshot date) and a `_row_hash`, then upserts on `id`.
# MAGIC
# MAGIC **Why:** strings in bronze keep the record exactly as delivered (dates are parsed in silver). The search API has no "as of" field, so the snapshot date is the as-of date. No soft delete here: the fetch is windowed (from 2018), so a notice missing from it has not necessarily been withdrawn.

# COMMAND ----------

from pyspark.sql import Window
from pyspark.sql.types import ArrayType, LongType, StringType, StructField, StructType

page_schema = StructType([
    StructField("country", StringType()), StructField("offset", LongType()), StructField("total", LongType()),
    StructField("procnotices", ArrayType(StructType([StructField(c, StringType()) for c in NOTICE_FIELDS]))),
])
newest_first = Window.partitionBy("id").orderBy(F.col("_source_file").desc())

notices = (spark.read.schema(page_schema).option("multiLine", True).json(f"{SNAPSHOT_DIR}/*/page_*.json")
           .select(F.explode("procnotices").alias("n"), F.col("_metadata.file_path").alias("_source_file"))
           .select("n.*", "_source_file")
           .withColumn("_rn", F.row_number().over(newest_first)).filter("_rn = 1").drop("_rn")
           .withColumn("_row_hash", row_hash(NOTICE_FIELDS))
           .withColumn("_source", F.lit(NOTICES_SOURCE))
           .withColumn("_snapshot_date", F.lit(SNAPSHOT).cast("date"))
           .withColumn("as_of_date", F.lit(SNAPSHOT).cast("date"))
           .withColumn("_ingested_at", F.current_timestamp()))

first = merge_upsert(notices, TARGET, key="id")
spark.sql(f"COMMENT ON TABLE {TARGET} IS 'World Bank procurement notices as delivered (search API v2 procnotices), "
          "one row per notice id, fetched per project country newest-first back to 2018-01-01. "
          "Contact person fields deliberately not ingested.'")
print("MERGE:", first)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Checks
# MAGIC
# MAGIC **What:**
# MAGIC - per country, the API's own `total` must equal the facet count (the filter returned exactly that country);
# MAGIC - countries that were read to the end must have saved exactly their facet count;
# MAGIC - ids are unique in bronze; notice types and years as a sanity view.
# MAGIC
# MAGIC **Why:** these are the strongest completeness checks the API allows. Countries stopped at the cutoff cannot be compared with a count (the API cannot count "since 2018"), but their stop reason is recorded.

# COMMAND ----------

bronze = spark.table(TARGET)
exhausted = fetch_status[fetch_status["stop"] == "exhausted"]
checks = [
    (TARGET, "countries fetched", len(fetch_status), f"== {len(partitions)}"),
    (TARGET, "notices without a country: expected", NO_COUNTRY_GAP, "info"),
    (TARGET, "notices without a country: saved", no_country_status.get("found_without_country", 0), f">= {NO_COUNTRY_GAP}"),
    (TARGET, "countries where API total != facet count", int((fetch_status["api_total"] != fetch_status["facet_count"]).sum()), "== 0"),
    (TARGET, "fully read countries with rows != facet count", int((exhausted["rows"] != exhausted["facet_count"]).sum()), "== 0"),
    (TARGET, "countries stopped at the 2018 cutoff", int((fetch_status["stop"] == "reached cutoff").sum()), "info"),
    (TARGET, "rows", bronze.count(), "info"),
    (TARGET, "duplicate id", duplicate_keys(bronze, ["id"]), "== 0"),
    (TARGET, "rows with noticedate >= 2018", bronze.filter(F.to_date("noticedate", "dd-MMM-yyyy") >= F.lit(NOTICE_CUTOFF)).count(), "info"),
]
display(dq_report(checks))
display(bronze.groupBy("notice_type").count().orderBy(F.desc("count")))
display(bronze.groupBy(F.year(F.to_date("noticedate", "dd-MMM-yyyy")).alias("notice_year")).count().orderBy("notice_year"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run summary
# MAGIC
# MAGIC **What:** returns the key counts as the notebook's exit value.
# MAGIC
# MAGIC **Why:** a job run shows the exit value without opening the notebook.

# COMMAND ----------

summary = {"countries": len(partitions), "pages_rows": int(fetch_status["rows"].sum()),
           "bronze_rows": bronze.count(), "snapshot": SNAPSHOT, "merge": first}
print(summary)
dbutils.notebook.exit(json.dumps(summary))
