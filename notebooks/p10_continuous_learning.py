# Databricks notebook source
# MAGIC %md
# MAGIC # p10_continuous_learning — incremental updates, refresh rules and the pilot KPIs
# MAGIC
# MAGIC The platform is only useful if new notices, awards, supervision documents and amendments reach the graph, the models and the retrieval index without a full rebuild every day, and if someone can tell when a model has gone stale. This notebook shows the loop on real tables:

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <pre class="mermaid">
# MAGIC ---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC ---
# MAGIC flowchart TD
# MAGIC     apis["APIs (awards, notices, documents)"]
# MAGIC     bronze["bronze"]
# MAGIC     keys["changed keys"]
# MAGIC     silver["silver rows of those keys"]
# MAGIC     kg["KG nodes / edges<br/>(incremental MERGE, section 3)"]
# MAGIC     stats["timelines, supplier stats<br/>(refresh queue of affected contracts / entities)"]
# MAGIC     chunks["document chunks<br/>(embed only new or changed chunks, section 6)"]
# MAGIC     drift["drift checks (section 4)"]
# MAGIC     chall["challenger trained (p07)"]
# MAGIC     champ["@champion"]
# MAGIC     kpis["pilot KPIs + user feedback (section 7)"]
# MAGIC     backlog["back to the backlog"]
# MAGIC     apis -->|"daily MERGE (row hash: unchanged rows are not rewritten)"| bronze
# MAGIC     bronze -->|"Change Data Feed"| keys --> silver
# MAGIC     silver --> kg
# MAGIC     silver --> stats
# MAGIC     silver --> chunks
# MAGIC     kg --> drift
# MAGIC     stats --> drift
# MAGIC     chunks --> drift
# MAGIC     drift -->|"retrain trigger"| chall
# MAGIC     chall -->|"gate (section 5)"| champ
# MAGIC     chall --> kpis --> backlog
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
# MAGIC   APIs (awards, notices, documents)
# MAGIC        | daily MERGE (row hash: unchanged rows are not rewritten)
# MAGIC        v
# MAGIC   bronze  --Change Data Feed-->  changed keys  --> silver rows of those keys
# MAGIC                                                         |
# MAGIC                       +---------------------------------+------------------------------+
# MAGIC                       v                                 v                              v
# MAGIC               KG nodes / edges              timelines, supplier stats          document chunks
# MAGIC               (incremental MERGE,           (refresh queue of affected         (embed only new or
# MAGIC                section 3)                    contracts / entities)              changed chunks, section 6)
# MAGIC                       |                                 |                              |
# MAGIC                       +------------> drift checks (section 4) <------------------------+
# MAGIC                                            | retrain trigger
# MAGIC                                            v
# MAGIC                            challenger trained (p07)  --gate (section 5)-->  @champion
# MAGIC                                            |
# MAGIC                                            v
# MAGIC                               pilot KPIs + user feedback (section 7) --> back to the backlog
# MAGIC ```
# MAGIC
# MAGIC </details>
# MAGIC
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | Change Data Feed on the proc bronze, silver and gold tables | table property | - |
# MAGIC | `proc_gold.pipeline_checkpoints` | last bronze version processed per table | `table_name` |
# MAGIC | `proc_sandbox.notices_replay`, `kg_notice_nodes_replay`, `kg_notice_edges_replay` | replay copies for the incremental proof | as in silver / gold |
# MAGIC | `proc_gold.drift_reports` | one drift measure per run and feature | `run_id, feature` |
# MAGIC | `proc_gold.pilot_kpis` | one KPI with definition, baseline, target and latest value | `kpi_id` |
# MAGIC | `proc_gold.pilot_feedback` | one user rating of one agent answer (empty until the pilot) | `feedback_id` |
# MAGIC
# MAGIC The notebook has two modes (widget `mode`): `demo` runs everything, including the replay proof and the policy demos; `monitor` (the daily job in `databricks.yml`) runs only the checks that belong in production: Change Data Feed status, bronze changes since the last checkpoint, drift report, freshness and KPI refresh.

# COMMAND ----------

# MAGIC %md
# MAGIC ## How it was built and tested
# MAGIC
# MAGIC **Step 1 — Is Change Data Feed already on?**
# MAGIC - **Question:** can downstream steps read "what changed since yesterday" from the tables?
# MAGIC - **What we found:** no table in `proc_bronze`, `proc_silver` or `proc_gold` had `delta.enableChangeDataFeed` set. The bronze tables are loaded with `MERGE` and a row hash, so their change feed will contain only real changes. Silver and gold are rebuilt with `overwrite`, so their change feed would list every row as deleted and re-inserted.
# MAGIC - **Decision:** turn the feed on for all of them (it is a table property, no data changes), read it on bronze, and make the downstream update incremental with `MERGE` on the affected keys. Silver steps that still overwrite are the next candidates for the same treatment.
# MAGIC
# MAGIC **Step 2 — How big is a real day?**
# MAGIC - **Question:** is incremental processing worth it?
# MAGIC - **What we found:** section 2 reads the newest notices from the API and compares them with bronze; a day brings a few hundred notices against about 417,000 stored ones (silver notices per notice date in October 2026: 21 to 226).
# MAGIC - **Decision:** for the knowledge graph, recompute only the neighbourhood of changed notices.
# MAGIC
# MAGIC **Step 3 — Proving incremental = full rebuild without touching production**
# MAGIC - **Question:** how can the incremental path be tested on real data while two other components read the production tables?
# MAGIC - **What we found:** writing a test batch into the production silver and gold tables would change what the delay model and the agent read mid-run.
# MAGIC - **Decision:** a replay in a separate schema `proc_sandbox`: yesterday's state = silver notices without the last 7 days and with 100 older notices in an earlier "draft" version (half without a project id, half filed under a wrong project); today's batch = the held-back notices plus the corrected versions. The batch is merged, the change feed gives the affected notices, the notice neighbourhood of the graph is updated by one `MERGE`, and the result is compared with a full rebuild and with the production graph that `p06` built.
# MAGIC
# MAGIC **Step 4 — Drift on durations is partly an artefact**
# MAGIC - **Question:** which windows should drift checks compare?
# MAGIC - **What we found:** cohorts by **notice** date make recent durations look short: a tender advertised last month appears only if it was already signed. Cohorts by **signing** date avoid that censoring.
# MAGIC - **Decision:** windows by signing date (current = the latest 12 months, reference = the 24 months before).
# MAGIC
# MAGIC **Step 5 — Is the incremental path faster?**
# MAGIC - **Question:** what does incremental buy on this cluster?
# MAGIC - **What we found:** not in wall time at this size. Over two runs on the shared cluster the incremental update took 65-70 s and the full rebuild of the 1.36 million-edge neighbourhood 30-76 s: the incremental path still scans the whole link and bidder tables to find the rows of the changed notices, and the `MERGE` reads the whole target. What it does save is writes: 3,290 inserts and 50 deletes instead of rewriting 1.36 million rows, so downstream readers of the change feed see 3,340 changes instead of a full replacement.
# MAGIC - **Decision:** keep the incremental path for correctness of the change feed and for scale (the daily batch stays a few hundred notices while the tables grow), and before relying on it for speed, cluster the link, bidder and edge tables by `notice_id` / `src_id` (liquid clustering) so that finding the changed rows stops being a full scan.
# MAGIC
# MAGIC **Step 6 — Freshness must ignore metadata commits**
# MAGIC - **Question:** how old is each table?
# MAGIC - **What we found:** the first version took the newest commit and reported every table as 0.5 hours old: the newest commit was this notebook's own `SET TBLPROPERTIES`.
# MAGIC - **Decision:** freshness = the newest *data* commit (write, merge, update, delete, create-as-select).

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

# MAGIC %md
# MAGIC ## Settings
# MAGIC
# MAGIC **What:** the mode, the tables that get a change feed, the replay sizes and the drift windows.
# MAGIC
# MAGIC **Why:** one place to see what the notebook may alter: only tables in `proc_*` schemas, and only their properties, except for the sandbox copies and the monitoring tables it owns.

# COMMAND ----------

import json
import time
from datetime import datetime, timedelta, timezone

from delta.tables import DeltaTable
from pyspark.sql import Window

from proc_intel.freshness import (champion_challenger_gate, drift_level, freshness_status, index_refresh_plan,
                                  ks_statistic, psi_categorical, psi_numeric, retrain_decision)
from proc_intel.http import get_json
from proc_intel.ingest import parse_wb_date

dbutils.widgets.dropdown("mode", "demo", ["demo", "monitor"])
MODE = dbutils.widgets.get("mode")
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
SANDBOX = f"{CATALOG}.proc_sandbox"
CDF_TABLES = [f"{BRONZE}.contract_awards", f"{BRONZE}.procurement_notices",
              f"{SILVER}.contracts", f"{SILVER}.notices", f"{SILVER}.notice_contract_links", f"{SILVER}.notice_bidders",
              f"{GOLD}.tender_timelines", f"{GOLD}.kg_nodes", f"{GOLD}.kg_edges"]
BRONZE_TABLES = [f"{BRONZE}.contract_awards", f"{BRONZE}.procurement_notices"]
CHECKPOINTS = f"{GOLD}.pipeline_checkpoints"
DRIFT_TABLE = f"{GOLD}.drift_reports"
KPI_TABLE, FEEDBACK_TABLE = f"{GOLD}.pilot_kpis", f"{GOLD}.pilot_feedback"
HOLD_DAYS, N_CORRECTIONS = 7, 100
print(f"mode={MODE} run_id={RUN_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Change Data Feed: check, then enable
# MAGIC
# MAGIC **What:** reads `delta.enableChangeDataFeed` of each table, sets it where it is missing, and shows the before/after state with each table's current version.
# MAGIC
# MAGIC **Why:** the feed records, from the version where it is switched on, every inserted, updated (pre- and post-image) and deleted row with its commit version. It is the cheapest correct answer to "which keys changed since the last run". Setting it is idempotent; it never rewrites data.

# COMMAND ----------

def table_version(table: str) -> int:
    return DeltaTable.forName(spark, table).history(1).select("version").first()[0]


def cdf_enabled(table: str) -> bool:
    props = {r.key: r.value for r in spark.sql(f"SHOW TBLPROPERTIES {table}").collect()}
    return props.get("delta.enableChangeDataFeed", "false").lower() == "true"


def cdf_enabled_since(table: str):
    """(version, timestamp) of the commit that switched the feed on, from the table history."""
    hist = (DeltaTable.forName(spark, table).history().filter("operation = 'SET TBLPROPERTIES'")
            .filter(F.col("operationParameters")["properties"].contains("enableChangeDataFeed"))
            .orderBy(F.desc("version")).select("version", "timestamp").first())
    return (hist.version, str(hist.timestamp)[:19]) if hist else (None, None)


cdf_rows = []
for t in CDF_TABLES:
    before = cdf_enabled(t)
    if not before:
        spark.sql(f"ALTER TABLE {t} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
    since_v, since_ts = cdf_enabled_since(t)
    cdf_rows.append({"table": t, "cdf_before_this_run": before, "cdf_now": cdf_enabled(t), "version_now": table_version(t),
                     "feed_on_since_version": since_v, "feed_on_since": since_ts})
display(pd.DataFrame(cdf_rows))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Bronze changes since the last checkpoint, and the size of a real day
# MAGIC
# MAGIC **What:**
# MAGIC 1. For each bronze table, reads `table_changes()` from the version after the stored checkpoint to now, counts inserts, updates and deletes, counts the projects they touch, and moves the checkpoint forward. On the first run there is no checkpoint yet: the current version becomes the baseline.
# MAGIC 2. Asks the notices API for the newest notices (newest first, until a page is older than 3 days) and the awards API for its row count, and compares both with bronze.
# MAGIC
# MAGIC **Why:** (1) is the production hand-off: the daily job ingests with `MERGE`, then this step turns the change feed into a list of affected keys for the downstream refresh. (2) measures a real daily increment, which is what justifies incremental processing.

# COMMAND ----------

if not spark.catalog.tableExists(CHECKPOINTS):
    spark.sql(f"""CREATE TABLE {CHECKPOINTS} (table_name STRING NOT NULL COMMENT 'PK. Bronze table',
                  last_version BIGINT COMMENT 'Last table version whose changes were processed',
                  processed_at TIMESTAMP COMMENT 'When') COMMENT 'Change Data Feed checkpoints of the daily pipeline (p10). Grain: one row per source table.'""")
    spark.sql(f"ALTER TABLE {CHECKPOINTS} ADD CONSTRAINT pk_pipeline_checkpoints PRIMARY KEY (table_name)")
saved = {r.table_name: r.last_version for r in spark.table(CHECKPOINTS).collect()}
change_rows = []
for table in BRONZE_TABLES:
    now_v = table_version(table)
    start = saved.get(table)
    if start is None:
        change_rows.append({"table": table, "from_version": None, "to_version": now_v, "note": "baseline set (first run)"})
    elif now_v > start:
        ch = spark.sql(f"SELECT * FROM table_changes('{table}', {start + 1}, {now_v})")
        counts = {r._change_type: r["count"] for r in ch.groupBy("_change_type").count().collect()}
        projects = ch.filter("_change_type <> 'update_preimage'").select("project_id").distinct().count()
        change_rows.append({"table": table, "from_version": start + 1, "to_version": now_v, **counts,
                            "projects_touched": projects, "note": "changes read"})
    else:
        change_rows.append({"table": table, "from_version": start, "to_version": now_v, "note": "no new commits"})
    spark.createDataFrame([(table, now_v)], "table_name string, last_version long").createOrReplaceTempView("_cp")
    spark.sql(f"""MERGE INTO {CHECKPOINTS} t USING _cp s ON t.table_name = s.table_name
                  WHEN MATCHED THEN UPDATE SET last_version = s.last_version, processed_at = current_timestamp()
                  WHEN NOT MATCHED THEN INSERT (table_name, last_version, processed_at)
                  VALUES (s.table_name, s.last_version, current_timestamp())""")
display(pd.DataFrame(change_rows))

# COMMAND ----------

today = datetime.now(timezone.utc).date()
recent, pages = [], 0
while pages < 20:
    body = get_json(NOTICES_URL, {"format": "json", "srt": "id", "order": "desc", "rows": 500, "os": pages * 500,
                                  "fl": "id,noticedate,notice_type"})
    batch = [v for v in body.get("procnotices", [])]
    recent.extend(batch)
    pages += 1
    dates = [d for d in (parse_wb_date(v.get("noticedate")) for v in batch) if d]
    if not batch or (dates and max(dates) < today - timedelta(days=3)):
        break
api = spark.createDataFrame([(v["id"], v.get("noticedate"), v.get("notice_type")) for v in recent],
                            "id string, noticedate string, notice_type string")
known = api.join(spark.table(f"{BRONZE}.procurement_notices").select("id"), "id", "left_semi").count()
awards_body = get_json(AWARDS_URL, {**AWARDS_PARAMS, "top": 1})
awards_api = int(awards_body.get("count", 0))
awards_bronze = spark.table(f"{BRONZE}.contract_awards").filter("_removed_at_source IS NULL").count()
print(f"notices API, newest {len(recent):,} notices ({pages} pages): {len(recent) - known:,} not yet in bronze, {known:,} already loaded")
print(f"awards API row count {awards_api:,} vs bronze active rows {awards_bronze:,} (difference {awards_api - awards_bronze:+,})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Incremental update of the knowledge graph, proven against a full rebuild
# MAGIC
# MAGIC **What:** the notice neighbourhood of the graph (notice nodes; `FOR_PROJECT`, `ADVERTISES`, `ANNOUNCES`, `BID_ON` edges) built by the same rules as `p06`, in the sandbox:
# MAGIC
# MAGIC | Step | Content |
# MAGIC |---|---|
# MAGIC | yesterday | silver notices without the last 7 days of notice dates; 100 older notices (hash order) in a "draft" version: description prefixed `[draft]`; 50 without a project id, 50 filed under a wrong project |
# MAGIC | today's batch | the held-back notices and the corrected versions of the 100 |
# MAGIC | ingest | `MERGE` on `notice_id` with a row hash into `notices_replay` (change feed on) |
# MAGIC | changed keys | `table_changes()` since the version before the merge |
# MAGIC | incremental | recompute nodes and edges of the changed notices only; one atomic `MERGE` that inserts, updates and deletes (edges that no longer exist arrive as tombstones) |
# MAGIC | proof | incremental result = full rebuild (whole table and changed keys) and = the production `kg_nodes` / `kg_edges` |
# MAGIC
# MAGIC **Why:** the comparison with a full rebuild is the correctness test of the incremental path; the comparison with production shows the sandbox builder is the same as `p06`'s. Links and bidder rows of a notice come from the silver tables built by `p03` / `p05` (in production those steps produce them for the new notices before this one runs).

# COMMAND ----------

def props(*cols: str):
    """String map of the given columns, dropping nulls (as in p06)."""
    pairs = [x for c in cols for x in (F.lit(c), F.col(c).cast("string"))]
    return F.map_filter(F.create_map(*pairs), lambda k, v: v.isNotNull())


def canonical(df: DataFrame) -> DataFrame:
    """Adds properties_json: the property map as sorted JSON, comparable in EXCEPT and MERGE conditions."""
    return df.withColumn("properties_json", F.to_json(F.array_sort(F.map_entries("properties"))))


def notice_subgraph(notices: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Notice nodes and the edges that touch a notice, by p06's rules, for the given notices only."""
    ids = notices.select("notice_id")
    links = spark.table(f"{SILVER}.notice_contract_links").join(ids, "notice_id", "left_semi")
    bid_on = (spark.table(f"{SILVER}.notice_bidders").join(ids, "notice_id", "left_semi")
              .join(spark.table(f"{SILVER}.supplier_entity_map"), "supplier_id")
              .withColumn("_rank", F.when(F.col("role") == "awarded", 0).when(F.col("role") == "evaluated", 1).otherwise(2))
              .withColumn("_rn", F.row_number().over(Window.partitionBy("supplier_entity_id", "notice_id").orderBy("_rank")))
              .filter("_rn = 1"))
    nodes = notices.select(F.concat(F.lit("notice:"), "notice_id").alias("node_id"), F.lit("notice").alias("node_type"),
                           F.col("bid_description").alias("name"),
                           props("notice_type", "notice_date", "procurement_method_name", "procurement_category_code",
                                 "bid_reference", "submission_deadline").alias("properties"))

    def edge(df, src, src_key, etype, dst, dst_key, *cols):
        return (df.filter(F.col(src_key).isNotNull() & F.col(dst_key).isNotNull())
                .select(F.concat(F.lit(f"{src}:"), F.col(src_key)).alias("src_id"), F.lit(etype).alias("edge_type"),
                        F.concat(F.lit(f"{dst}:"), F.col(dst_key)).alias("dst_id"), props(*cols).alias("properties")))

    edges = (edge(notices, "notice", "notice_id", "FOR_PROJECT", "project", "project_id")
             .unionByName(edge(links.filter("link_role = 'tender'"), "notice", "notice_id", "ADVERTISES", "contract",
                               "contract_id", "match_tier", "notice_before_signing", "days_notice_to_signing"))
             .unionByName(edge(links.filter("link_role = 'award'"), "notice", "notice_id", "ANNOUNCES", "contract",
                               "contract_id", "match_tier", "supplier_confirmed"))
             .unionByName(edge(bid_on, "supplier_entity", "supplier_entity_id", "BID_ON", "notice", "notice_id", "role")))
    return canonical(nodes), canonical(edges)


NOTICE_EDGE_TYPES = ["FOR_PROJECT", "ADVERTISES", "ANNOUNCES", "BID_ON"]
EDGE_KEY, NODE_KEY = ["src_id", "edge_type", "dst_id"], ["node_id"]


def diff_count(a: DataFrame, b: DataFrame, cols: list[str]) -> int:
    """Rows in a but not b plus rows in b but not a (on the given columns)."""
    a, b = a.select(*cols), b.select(*cols)
    return a.exceptAll(b).count() + b.exceptAll(a).count()

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** yesterday's state in the sandbox: the replay notices table (change feed on) and the graph neighbourhood built from it.
# MAGIC
# MAGIC **Why:** a self-contained starting point whose "true" final state is known: after today's batch it must equal the current silver notices exactly.

# COMMAND ----------

if MODE == "demo":
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {SANDBOX} COMMENT 'Replay copies for testing incremental updates (p10). Not read by any other step.'")
    REPLAY_NOTICES = f"{SANDBOX}.notices_replay"
    REPLAY_NODES, REPLAY_EDGES = f"{SANDBOX}.kg_notice_nodes_replay", f"{SANDBOX}.kg_notice_edges_replay"
    silver_notices = spark.table(f"{SILVER}.notices")
    business_cols = silver_notices.columns
    hold_from = silver_notices.agg(F.max("notice_date")).first()[0] - timedelta(days=HOLD_DAYS - 1)
    corrected_ids = (silver_notices.filter((F.col("notice_date") < F.lit(hold_from)) & F.col("project_id").isNotNull())
                     .orderBy(F.sha2("notice_id", 256)).limit(N_CORRECTIONS).select("notice_id")
                     .withColumn("_corr", F.lit(True))
                     .withColumn("_corr_n", F.row_number().over(Window.orderBy(F.sha2("notice_id", 256)))))
    wrong_project = spark.table(f"{SILVER}.dim_project").agg(F.min("project_id")).first()[0]     # any real project
    yesterday = (silver_notices.filter((F.col("notice_date") < F.lit(hold_from)) | F.col("notice_date").isNull())
                 .join(corrected_ids, "notice_id", "left")
                 .withColumn("project_id", F.when(F.col("_corr") & (F.col("_corr_n") % 2 == 0), F.lit(None).cast("string"))
                             .when(F.col("_corr"), F.lit(wrong_project)).otherwise(F.col("project_id")))
                 .withColumn("bid_description", F.when(F.col("_corr"), F.concat(F.lit("[draft] "), "bid_description"))
                             .otherwise(F.col("bid_description")))
                 .select(*business_cols).withColumn("_row_hash", row_hash(business_cols)))
    spark.sql(f"DROP TABLE IF EXISTS {REPLAY_NOTICES}")
    yesterday.write.saveAsTable(REPLAY_NOTICES)
    spark.sql(f"ALTER TABLE {REPLAY_NOTICES} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
    y_nodes, y_edges = notice_subgraph(spark.table(REPLAY_NOTICES))
    y_nodes.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(REPLAY_NODES)
    y_edges.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(REPLAY_EDGES)
    for t, text in [(REPLAY_NOTICES, "Replay of proc_silver.notices: yesterday = without the last 7 days, 100 notices in draft form; then today's batch merged (p10)."),
                    (REPLAY_NODES, "Replay: notice nodes of the knowledge graph, maintained incrementally (p10)."),
                    (REPLAY_EDGES, "Replay: edges touching a notice (FOR_PROJECT, ADVERTISES, ANNOUNCES, BID_ON), maintained incrementally (p10).")]:
        spark.sql(f"COMMENT ON TABLE {t} IS '{_quote(text)}'")
    v_before = table_version(REPLAY_NOTICES)
    print(f"held back notices dated >= {hold_from}; yesterday: {spark.table(REPLAY_NOTICES).count():,} notices, "
          f"{spark.table(REPLAY_NODES).count():,} nodes, {spark.table(REPLAY_EDGES).count():,} edges; "
          f"replay table at version {v_before}, change feed {cdf_enabled(REPLAY_NOTICES)}")

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** today's batch merged into the replay notices, then the change feed since the version before the merge, and what it means downstream: which projects, contracts (and so `tender_timelines` rows) and supplier entities are touched.
# MAGIC
# MAGIC **Why:** this is the refresh queue a production run would hand to the timeline, supplier-statistics and graph steps. It also shows why the change feed beats a full comparison: the 100 corrected notices are found without comparing 380,000 rows.

# COMMAND ----------

if MODE == "demo":
    batch = (silver_notices.filter(F.col("notice_date") >= F.lit(hold_from))
             .unionByName(silver_notices.join(corrected_ids.select("notice_id"), "notice_id", "left_semi"))
             .withColumn("_row_hash", row_hash(business_cols)))
    merge_metrics = merge_upsert(batch, REPLAY_NOTICES, "notice_id")
    print("MERGE of today's batch:", merge_metrics)
    changes = spark.sql(f"SELECT * FROM table_changes('{REPLAY_NOTICES}', {v_before + 1})")
    display(changes.groupBy("_change_type").count())
    changed = changes.filter("_change_type <> 'update_preimage'").select("notice_id").distinct().cache()
    changed_nodes = changed.select(F.concat(F.lit("notice:"), "notice_id").alias("node_id"))
    new_nodes, new_edges = notice_subgraph(spark.table(REPLAY_NOTICES).join(changed, "notice_id", "left_semi"))
    old_edges = spark.table(REPLAY_EDGES)
    touching_old = (old_edges.join(changed_nodes.withColumnRenamed("node_id", "src_id"), "src_id", "left_semi")
                    .unionByName(old_edges.join(changed_nodes.withColumnRenamed("node_id", "dst_id"), "dst_id", "left_semi")))
    touched = new_edges.unionByName(touching_old)
    impact = {"changed notices": changed.count(),
              "projects (FOR_PROJECT, old or new)": touched.filter("edge_type = 'FOR_PROJECT'").select("dst_id").distinct().count(),
              "contracts (ADVERTISES / ANNOUNCES)": touched.filter("edge_type IN ('ADVERTISES', 'ANNOUNCES')").select("dst_id").distinct().count(),
              "tender_timelines rows to refresh": spark.table(f"{GOLD}.tender_timelines")
                  .join(touched.filter("edge_type IN ('ADVERTISES', 'ANNOUNCES')")
                        .select(F.regexp_replace("dst_id", "^contract:", "").alias("contract_id")).distinct(), "contract_id", "left_semi").count(),
              "supplier entities (BID_ON)": touched.filter("edge_type = 'BID_ON'").select("src_id").distinct().count()}
    display(pd.DataFrame([impact]))

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** the incremental update itself. The source of one `MERGE` per table is the recomputed rows of the changed notices plus *tombstones*: rows that touch a changed notice in the table but are no longer produced (here: the 50 `FOR_PROJECT` edges of draft notices filed under the wrong project; the 50 draft notices without a project get their edge inserted). Matched tombstones are deleted, changed rows updated, new rows inserted, all in one commit.
# MAGIC
# MAGIC **Why:** a reader never sees a half-updated neighbourhood (delete-then-insert would expose an intermediate state), and unchanged rows are not rewritten.

# COMMAND ----------

def incremental_merge(target: str, recomputed: DataFrame, touching: DataFrame, key: list[str]) -> dict:
    """MERGE recomputed rows into target; rows of `touching` that are not recomputed are deleted."""
    tomb = touching.join(recomputed.select(*key), key, "left_anti").withColumn("_delete", F.lit(True))
    source = recomputed.withColumn("_delete", F.lit(False)).unionByName(tomb)
    cond = " AND ".join(f"t.{k} = s.{k}" for k in key)
    cols = recomputed.columns
    changed_row = "t.properties_json <> s.properties_json" + (" OR NOT (t.name <=> s.name)" if "name" in cols else "")
    (DeltaTable.forName(spark, target).alias("t").merge(source.alias("s"), cond)
     .whenMatchedDelete(condition="s._delete")
     .whenMatchedUpdate(condition=f"NOT s._delete AND ({changed_row})", set={c: f"s.{c}" for c in cols})
     .whenNotMatchedInsert(condition="NOT s._delete", values={c: f"s.{c}" for c in cols})
     .execute())
    m = DeltaTable.forName(spark, target).history(1).select("operationMetrics").first()[0]
    return {k: int(m.get(k, 0)) for k in ["numTargetRowsInserted", "numTargetRowsUpdated", "numTargetRowsDeleted"]}


if MODE == "demo":
    t0 = time.time()
    old_nodes = spark.table(REPLAY_NODES).join(changed_nodes, "node_id", "left_semi")
    node_metrics = incremental_merge(REPLAY_NODES, new_nodes, old_nodes, NODE_KEY)
    edge_metrics = incremental_merge(REPLAY_EDGES, new_edges, touching_old, EDGE_KEY)   # no duplicates: an edge has a notice at one end only
    incremental_s = time.time() - t0
    t0 = time.time()
    full_nodes, full_edges = notice_subgraph(spark.table(REPLAY_NOTICES))
    full_edges.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{SANDBOX}._kg_notice_edges_rebuild")
    full_s = time.time() - t0
    rewritten = spark.table(f"{SANDBOX}._kg_notice_edges_rebuild").count()
    print(f"incremental: nodes {node_metrics}, edges {edge_metrics} in {incremental_s:.0f} s")
    print(f"full rebuild of the edges: {rewritten:,} rows rewritten in {full_s:.0f} s")

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** the proof: differences (rows in one but not the other, both ways) between the incrementally maintained tables and (a) a full rebuild from today's replay notices, overall and on the changed keys, and (b) the production graph built by `p06` from the current silver tables.
# MAGIC
# MAGIC **Why:** all must be 0. (b) also checks that the sandbox builder applies `p06`'s rules: after today's batch the replay notices equal silver, so the neighbourhood must equal production.

# COMMAND ----------

if MODE == "demo":
    inc_nodes, inc_edges = spark.table(REPLAY_NODES), spark.table(REPLAY_EDGES)
    full_edges = spark.table(f"{SANDBOX}._kg_notice_edges_rebuild")
    prod_nodes = canonical(spark.table(f"{GOLD}.kg_nodes").filter("node_type = 'notice'"))
    prod_edges = canonical(spark.table(f"{GOLD}.kg_edges").filter(F.col("edge_type").isin(NOTICE_EDGE_TYPES)))
    node_cols, edge_cols = ["node_id", "node_type", "name", "properties_json"], EDGE_KEY + ["properties_json"]
    on_changed = lambda df, col: df.join(changed_nodes.withColumnRenamed("node_id", col), col, "left_semi")
    proof = [
        (REPLAY_NODES, "incremental vs full rebuild: all notice nodes", diff_count(inc_nodes, full_nodes, node_cols), "== 0"),
        (REPLAY_EDGES, "incremental vs full rebuild: all notice edges", diff_count(inc_edges, full_edges, edge_cols), "== 0"),
        (REPLAY_EDGES, "incremental vs full rebuild: edges of changed notices",
         diff_count(on_changed(inc_edges, "src_id").unionByName(on_changed(inc_edges, "dst_id")),
                    on_changed(full_edges, "src_id").unionByName(on_changed(full_edges, "dst_id")), edge_cols), "== 0"),
        (REPLAY_NODES, "incremental vs production kg_nodes (notice)", diff_count(inc_nodes, prod_nodes, node_cols), "== 0"),
        (REPLAY_EDGES, "incremental vs production kg_edges (notice edge types)", diff_count(inc_edges, prod_edges, edge_cols), "== 0"),
        (REPLAY_NOTICES, "replay notices vs silver notices", diff_count(spark.table(REPLAY_NOTICES), silver_notices, business_cols), "== 0"),
        (REPLAY_EDGES, "edges in the neighbourhood", inc_edges.count(), "info"),
    ]
    display(dq_report(proof))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Drift checks on the modelling population
# MAGIC
# MAGIC **What:** openly competed, timed contracts of `tender_timelines` (the population of the delay model), in two windows by signing date: **current** = the latest 12 months, **reference** = the 24 months before. For each key feature the population stability index (PSI; numeric features binned at the reference deciles), and for the target (days from notice to signing) the Kolmogorov-Smirnov statistic and the medians. Appended to `proc_gold.drift_reports`.
# MAGIC
# MAGIC **Why:** the model learns "how long does a tender like this take"; if the mix of contracts (size, category, method, region, governance) or the durations themselves move, the champion's errors on new tenders will move too. PSI bands: below 0.10 stable, 0.10-0.25 moderate, 0.25 or more significant.

# COMMAND ----------

pop = (spark.table(f"{GOLD}.tender_timelines").filter("is_timed AND competition = 'open'")
       .select("signing_date", "contract_amount_usd", "procurement_category_code", "procurement_method_name", "region",
               "wgi_gov_effectiveness", "days_notice_to_signing"))
last_signing = pop.agg(F.max("signing_date")).first()[0]
cur_from, ref_from = last_signing - timedelta(days=365), last_signing - timedelta(days=3 * 365)
windowed = (pop.withColumn("window", F.when(F.col("signing_date") > F.lit(cur_from), "current")
                           .when(F.col("signing_date") > F.lit(ref_from), "reference"))
            .filter("window IS NOT NULL")
            .withColumn("log10_amount", F.log10(F.greatest(F.col("contract_amount_usd"), F.lit(1.0)))))
wp = windowed.drop("signing_date", "contract_amount_usd").toPandas()          # about 20k rows, 7 columns
ref, cur = wp[wp.window == "reference"], wp[wp.window == "current"]
drift = []
for feat in ["log10_amount", "wgi_gov_effectiveness"]:
    drift.append({"feature": feat, "kind": "numeric", "metric": "psi", "value": psi_numeric(ref[feat].tolist(), cur[feat].tolist())})
for feat in ["procurement_category_code", "procurement_method_name", "region"]:
    drift.append({"feature": feat, "kind": "categorical", "metric": "psi",
                  "value": psi_categorical(ref[feat].fillna("(none)").value_counts().to_dict(),
                                           cur[feat].fillna("(none)").value_counts().to_dict())})
target_ks = ks_statistic(ref["days_notice_to_signing"].tolist(), cur["days_notice_to_signing"].tolist())
drift.append({"feature": "days_notice_to_signing", "kind": "target", "metric": "ks", "value": target_ks})
drift.append({"feature": "days_notice_to_signing", "kind": "target", "metric": "psi",
              "value": psi_numeric(ref["days_notice_to_signing"].tolist(), cur["days_notice_to_signing"].tolist())})
for d in drift:
    d.update({"run_id": RUN_ID, "reference_window": f"{ref_from + timedelta(days=1)}..{cur_from}",
              "current_window": f"{cur_from + timedelta(days=1)}..{last_signing}", "n_reference": len(ref), "n_current": len(cur),
              "level": drift_level(d["value"]) if d["metric"] == "psi" else ("shift" if d["value"] >= 0.10 else "stable"),
              "value": round(float(d["value"]), 4)})
drift_df = spark.createDataFrame(pd.DataFrame(drift)[["run_id", "feature", "kind", "metric", "value", "level",
                                                     "reference_window", "current_window", "n_reference", "n_current"]])
drift_df = drift_df.withColumn("feature", F.concat_ws(":", "feature", "metric")).withColumn("measured_at", F.current_timestamp())
DRIFT_COMMENTS = {"run_id": "PK. Run timestamp (UTC)", "feature": "PK. <feature>:<metric>", "kind": "numeric, categorical or target",
                  "metric": "psi or ks", "value": "Measured value", "level": "stable / moderate / significant (PSI); stable / shift (KS >= 0.10)",
                  "reference_window": "Signing dates of the reference window", "current_window": "Signing dates of the current window",
                  "n_reference": "Contracts in the reference window", "n_current": "Contracts in the current window", "measured_at": "Timestamp"}
if spark.catalog.tableExists(DRIFT_TABLE):
    drift_df.write.mode("append").saveAsTable(DRIFT_TABLE)
else:
    publish_table(drift_df, DRIFT_TABLE, "Drift checks of the delay-model population (p10). Grain: one row per run and feature:metric. Appended daily.",
                  DRIFT_COMMENTS, primary_key=["run_id", "feature"])
display(drift_df.drop("run_id", "measured_at"))
print(f"median days notice->signing: reference {ref['days_notice_to_signing'].median():.0f}, current {cur['days_notice_to_signing'].median():.0f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Retrain trigger and champion/challenger gate
# MAGIC
# MAGIC **What:** `retrain_decision()` applied to the drift measured above, as if the champion had been trained on the reference window; then `champion_challenger_gate()` on two example metric sets (the gate takes metrics; the delay model itself and its evaluation belong to `p07`).
# MAGIC
# MAGIC | Rule | Trigger / requirement |
# MAGIC |---|---|
# MAGIC | retrain | any key feature PSI >= 0.25, target KS >= 0.10, live MAE more than 15% above the training MAE, or the model is 90+ days old ... |
# MAGIC | ... but only with data | at least 1,000 new labelled contracts; otherwise "investigate" (retraining on a handful of outcomes is noise) |
# MAGIC | promote | same evaluation window (the latest one) for both; at least 500 rows; challenger MAE at least 2% lower; no segment (category, region) with 50+ rows more than 10% worse; prediction-interval coverage within 5 points of nominal |
# MAGIC
# MAGIC **Why:** the trigger and the gate are separate on purpose. Drift says the world moved; only the gate decides whether a new model is better on the newest data. Promotion means moving the MLflow alias `@champion` to the challenger's version, so serving code never changes and a rollback is moving the alias back.

# COMMAND ----------

feature_psi = {d["feature"]: d["value"] for d in drift if d["metric"] == "psi" and d["kind"] != "target"}
decision = retrain_decision(feature_psi, target_ks, days_since_training=(today - cur_from).days, new_labels=len(cur))
print(json.dumps(decision, indent=1))
if MODE == "demo":
    champion = {"window": "latest-12m", "n": 4000, "mae": 62.0, "segments": {"CS": {"n": 900, "mae": 95.0}, "CW": {"n": 1500, "mae": 58.0}}}
    examples = {"better overall and in every segment": {"window": "latest-12m", "n": 4000, "mae": 58.5,
                                                        "segments": {"CS": {"n": 900, "mae": 93.0}, "CW": {"n": 1500, "mae": 55.0}},
                                                        "interval_coverage": 0.78, "nominal_coverage": 0.8},
                "better overall, worse on consulting": {"window": "latest-12m", "n": 4000, "mae": 57.0,
                                                        "segments": {"CS": {"n": 900, "mae": 108.0}, "CW": {"n": 1500, "mae": 50.0}}}}
    gate_rows = []
    for name, ch in examples.items():
        g = champion_challenger_gate(champion, ch)
        gate_rows.append({"challenger (example metrics)": name, "promote": g["promote"], "reason": g["reason"],
                          "checks": "; ".join(f"{n}: {'pass' if ok else 'FAIL'} ({d})" for n, ok, d in g["checks"])})
    display(pd.DataFrame(gate_rows))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Retrieval index refresh
# MAGIC
# MAGIC **What:** `index_refresh_plan()` compares chunk id -> text hash of what the index holds with the current chunk table and returns what to embed (new or changed chunks), what to delete (removed or changed) and how many stay. Shown on the outcome project's 50,000 chunks, with a simulated day: 3 documents re-chunked (text changed), 1 document withdrawn, and new chunks for the ISR and ICR Review texts collected in `p09` for 5 projects (counted as 1 chunk per document here).
# MAGIC
# MAGIC **Why:** embedding is the expensive step of an index refresh; hashing the chunk text makes "has this chunk changed?" exact and cheap, so a daily refresh embeds a few dozen chunks instead of 50,000. The FAISS index is then patched (remove ids, add vectors) or rebuilt from the stored embeddings, which needs no new embedding calls.

# COMMAND ----------

if MODE == "demo":
    chunk_rows = spark.table(RAG_CHUNKS).select("chunk_id", "doc_id", "text_hash").collect()     # 50k short rows
    indexed = {r.chunk_id: r.text_hash for r in chunk_rows}
    doc_of = {r.chunk_id: r.doc_id for r in chunk_rows}
    docs = sorted(set(doc_of.values()))[:4]                                    # first 4 documents by id
    rechunked, withdrawn = set(docs[:3]), docs[3]
    current = {cid: (h + "-v2" if doc_of[cid] in rechunked else h) for cid, h in indexed.items() if doc_of[cid] != withdrawn}
    if spark.catalog.tableExists(f"{BRONZE}.rating_documents"):
        first_projects = (spark.table(f"{BRONZE}.rating_documents").select("project_id").distinct()
                          .orderBy("project_id").limit(5))
        new_docs = (spark.table(f"{BRONZE}.rating_documents").filter("doc_id IS NOT NULL")
                    .join(first_projects, "project_id", "left_semi").select("doc_id").collect())
        current.update({f"{r.doc_id}_0": f"hash-{r.doc_id}" for r in new_docs})
    plan = index_refresh_plan(indexed, current)
    display(pd.DataFrame([{"chunks indexed": len(indexed), "chunks now": len(current), "to embed": len(plan["embed"]),
                           "of which new": len(plan["new"]), "of which changed": len(plan["changed"]),
                           "to delete": len(plan["delete"]), "of which removed": len(plan["removed"]),
                           "unchanged (no embedding call)": plan["unchanged"]}]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Pilot rollout and KPIs
# MAGIC
# MAGIC **Rollout in three phases**
# MAGIC
# MAGIC | Phase | Scope | Users | Duration | Go / no-go to the next phase |
# MAGIC |---|---|---|---|---|
# MAGIC | 0. Shadow | daily pipeline and monitoring live; agent answers logged, not shown | procurement analysts of the project team | 4-6 weeks | data freshness SLA met on 95% of days; benchmark MAE no worse than the naive peer-group median; retrieval precision@5 >= 0.7 on the evaluation set; >= 95% of answers with valid citations; no unresolved evidence conflict shown without its flag |
# MAGIC | 1. Assisted pilot | 2-3 regional procurement hubs; the agent drafts planning notes and benchmarks, staff decide | 15-30 procurement specialists | 3 months | weekly active use by >= 50% of pilot users; >= 70% thumbs-up; planning cycle time in pilot units not worse than baseline; zero incidents of fabricated citations; feedback triaged weekly |
# MAGIC | 2. Scale-out | all regions; integrated with STEP planning screens | procurement staff Bank-wide | ongoing | KPI targets below met for two consecutive quarters; champion/challenger gate and drift alerts in place; rollback = move `@champion` back and switch the agent to retrieval-only |
# MAGIC
# MAGIC Every phase can be stopped by the same rules that promote it: a breached go/no-go threshold for two consecutive weeks rolls back one phase.
# MAGIC
# MAGIC **KPIs** are stored in `proc_gold.pilot_kpis` with their definition, baseline, target and latest measured value. Where the data exists today the baseline is computed here; values owned by other components (benchmark error from `p07`, retrieval and citation metrics from `p08`) are filled from their evaluation tables when those exist, otherwise marked `pending`. User feedback has its own table, `proc_gold.pilot_feedback` (empty until the pilot starts).

# COMMAND ----------

open_timed = spark.table(f"{GOLD}.tender_timelines").filter("is_timed AND competition = 'open'")
cycle_12m = (open_timed.filter(F.col("signing_date") > F.lit(cur_from))
             .agg(F.expr("percentile_approx(days_notice_to_signing, 0.5)")).first()[0])
ifb = (spark.table(f"{SILVER}.notice_contract_links").filter("link_role = 'tender'")
       .join(spark.table(f"{SILVER}.notices").filter("notice_type = 'Invitation for Bids'").select("notice_id", "notice_date"), "notice_id")
       .groupBy("contract_id").agg(F.count("*").alias("k"), F.datediff(F.max("notice_date"), F.min("notice_date")).alias("span")))
n_ifb = ifb.count()
retender = ifb.filter("k > 1 AND span >= 30").count() / n_ifb
conflict_rate = None
if spark.catalog.tableExists(f"{GOLD}.project_evidence_resolution"):
    res = spark.table(f"{GOLD}.project_evidence_resolution").filter("question_type = 'outcome'")
    conflict_rate = res.filter("flag IN ('conflict', 'disagreement')").count() / res.count()
DATA_OPERATIONS = ["WRITE", "MERGE", "UPDATE", "DELETE", "CREATE TABLE AS SELECT", "REPLACE TABLE AS SELECT",
                   "CREATE OR REPLACE TABLE AS SELECT", "COPY INTO", "STREAMING UPDATE"]
fresh = []
for t in [f"{BRONZE}.contract_awards", f"{BRONZE}.procurement_notices", f"{GOLD}.tender_timelines", f"{GOLD}.kg_edges"]:
    # Last DATA commit: property changes, constraints and comments are commits too but bring no new data.
    ts = (DeltaTable.forName(spark, t).history().filter(F.col("operation").isin(DATA_OPERATIONS))
          .agg(F.max("timestamp")).first()[0])
    fresh.append({"table": t, **freshness_status(ts.replace(tzinfo=None), datetime.now(timezone.utc).replace(tzinfo=None),
                                                 24 if "bronze" in t else 30)})
display(pd.DataFrame(fresh))
fresh_share = sum(f["status"] == "fresh" for f in fresh) / len(fresh)


measured_on = today.isoformat()
kpis = [
    ("planning_cycle_time", "Planning cycle time", "Median days from first tender notice to contract signing, openly competed contracts signed in the last 12 months",
     "days", "lower", "proc_gold.tender_timelines", 0, cycle_12m, "-10% in pilot units after 2 quarters", cycle_12m, "measured"),
    ("benchmark_mae", "Benchmark error", "Mean absolute error (days) of the predicted vs actual notice-to-signing duration on the latest evaluation window",
     "days", "lower", "p07 evaluation (delay model)", 0, None, "below the naive peer-median baseline", None, "pending"),
    ("retrieval_precision_at_5", "Retrieval precision@5", "Share of the top 5 retrieved records judged relevant on the agent evaluation set",
     "share", "higher", "p08 evaluation (agent)", 0, None, ">= 0.70", None, "pending"),
    ("valid_citation_rate", "Recommendations with valid citations", "Share of agent answers whose every citation resolves to an existing record that supports the claim",
     "share", "higher", "p08 evaluation (agent)", 0, None, ">= 0.95", None, "pending"),
    ("retender_rate", "Re-tender rate (proxy)", "Share of contracts linked to an Invitation for Bids that were advertised by 2+ IFB notices at least 30 days apart; a lower bound, re-tenders under a new reference are not seen",
     "share", "lower", "proc_silver.notice_contract_links + notices", 0, retender, "-20% in pilot units", retender, "proxy"),
    ("evidence_conflict_rate", "Projects with conflicting performance evidence", "Share of sampled closed projects whose outcome evidence is flagged conflict or disagreement by resolve_evidence (p09); shown with its flag, never hidden",
     "share", "info", "proc_gold.project_evidence_resolution", 0, conflict_rate, "100% of conflicts surfaced with both sources", conflict_rate, "measured" if conflict_rate is not None else "pending"),
    ("data_freshness", "Data freshness SLA", "Share of monitored tables updated within their SLA (bronze 24 h, gold 30 h)",
     "share", "higher", "Delta table history", 0, fresh_share, ">= 0.95 of days", fresh_share, "measured"),
    ("weekly_active_users", "Adoption", "Share of pilot users with at least one agent session in the week",
     "share", "higher", "proc_gold.pilot_feedback / usage logs", 1, None, ">= 0.50", None, "pending"),
    ("positive_feedback_rate", "User feedback", "Share of rated answers with thumbs up",
     "share", "higher", "proc_gold.pilot_feedback", 1, None, ">= 0.70", None, "pending"),
]
kpi_df = (spark.createDataFrame([{"kpi_id": k[0], "kpi": k[1], "definition": k[2], "unit": k[3], "better": k[4], "source": k[5],
                                  "phase_introduced": k[6], "baseline_value": None if k[7] is None else float(k[7]), "target": k[8],
                                  "measured_value": None if k[9] is None else float(k[9]), "measured_on": measured_on, "status": k[10]} for k in kpis],
                                "kpi_id string, kpi string, definition string, unit string, better string, source string, phase_introduced int, "
                                "baseline_value double, target string, measured_value double, measured_on string, status string")
          .withColumn("measured_on", F.to_date("measured_on")))
publish_table(kpi_df, KPI_TABLE, "Pilot KPIs (p10). Grain: one row per KPI with definition, baseline, target and latest value. Refreshed by the daily monitor run.",
              {"kpi_id": "PK. KPI identifier", "kpi": "Name", "definition": "How it is measured", "unit": "days or share",
               "better": "lower, higher or info", "source": "Table or component that provides the value", "phase_introduced": "Rollout phase (0, 1, 2) from which it is tracked",
               "baseline_value": "Value before the pilot (null: not yet measurable)", "target": "Target or go/no-go threshold",
               "measured_value": "Latest measured value", "measured_on": "Date of the latest value", "status": "measured, proxy or pending"},
              primary_key=["kpi_id"])
display(spark.table(KPI_TABLE).select("kpi_id", "kpi", "unit", "baseline_value", "target", "status").orderBy("phase_introduced", "kpi_id"))

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** the feedback table: one row per user rating of one agent answer, with the cited record ids, so a thumbs-down can be traced to the evidence that produced the answer.
# MAGIC
# MAGIC **Why:** feedback closes the loop: low-rated answers with valid citations point at retrieval or ranking, low-rated answers with invalid citations at generation; both feed the evaluation set for the next challenger. Users are stored as a salted hash, not by name.

# COMMAND ----------

if not spark.catalog.tableExists(FEEDBACK_TABLE):
    spark.sql(f"""CREATE TABLE {FEEDBACK_TABLE} (
        feedback_id STRING NOT NULL COMMENT 'PK. Unique id of the rating',
        session_id STRING COMMENT 'Agent session',
        answer_id STRING COMMENT 'Id of the rated agent answer (joins to the answer log)',
        user_hash STRING COMMENT 'Salted hash of the user id (no names stored)',
        user_unit STRING COMMENT 'Organisational unit or regional hub of the pilot user',
        question_type STRING COMMENT 'benchmark, risk, lessons, supplier, evidence, other',
        rating INT COMMENT '+1 thumbs up, -1 thumbs down',
        reason_code STRING COMMENT 'wrong_fact, missing_source, irrelevant, outdated, other (thumbs down only)',
        comment STRING COMMENT 'Optional free text',
        cited_record_ids ARRAY<STRING> COMMENT 'Record ids the answer cited',
        evidence_flag STRING COMMENT 'resolve_evidence flag shown with the answer, if any',
        model_version STRING COMMENT 'Champion model version and prompt version that produced the answer',
        created_at TIMESTAMP COMMENT 'When the rating was given')
        COMMENT 'User feedback on agent answers during the pilot (p10). Grain: one row per rating. Empty until phase 1.'""")
    spark.sql(f"ALTER TABLE {FEEDBACK_TABLE} ADD CONSTRAINT pk_pilot_feedback PRIMARY KEY (feedback_id)")
print(f"{FEEDBACK_TABLE}: {spark.table(FEEDBACK_TABLE).count()} rows; columns {spark.table(FEEDBACK_TABLE).columns}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC **What:** the headline numbers as the notebook's exit value.
# MAGIC
# MAGIC **Why:** a job run shows them without opening the notebook. (In its own cell: output displayed in the same cell as `dbutils.notebook.exit` is dropped from the run record.)

# COMMAND ----------

summary = {"mode": MODE, "cdf_enabled": sum(r["cdf_now"] for r in cdf_rows), "new_notices_from_api": len(recent) - known,
           "retrain_action": decision["action"], "drift": {d["feature"] + ":" + d["metric"]: d["value"] for d in drift}}
if MODE == "demo":
    summary.update({"replay_merge": merge_metrics, "changed_notices": impact["changed notices"],
                    "proof_all_zero": all(int(v) == 0 for _, _, v, r in proof if r == "== 0"),
                    "incremental_s": round(incremental_s), "full_rebuild_s": round(full_s)})
print(summary)

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
