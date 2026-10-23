# Databricks notebook source
# MAGIC %md
# MAGIC # proc_common: shared settings and Spark helpers for the procurement notebooks
# MAGIC
# MAGIC Every `p0x` notebook starts with `%run ./proc_common`. It holds three things:
# MAGIC
# MAGIC | Item | Purpose |
# MAGIC |---|---|
# MAGIC | constants | catalog, schema, volume and table names, API addresses, the notice date cutoff |
# MAGIC | `sys.path` entry for `../src` (and the same package shipped to Spark's Python workers) | so notebooks and UDFs `import proc_intel`, the pure-Python package that pytest covers locally |
# MAGIC | Spark helpers | UDF wrapper, idempotent `MERGE`, publishing a documented table, primary/foreign keys, a data-quality table |
# MAGIC
# MAGIC Pure logic (name normalisation, reference matching, similarity, clustering) lives in `src/proc_intel/` and is imported, not copied, so the tested code and the code that runs here are the same file.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Settings
# MAGIC
# MAGIC **What:** names of every catalog object the procurement notebooks create or read, plus the API addresses.
# MAGIC
# MAGIC **Why:** one source of truth. The new work lives in three new schemas (`proc_bronze`, `proc_silver`, `proc_gold`) of the existing catalog; the outcome project's tables are only ever **read** (joined to), never changed.

# COMMAND ----------

import os
import shutil
import sys
import tempfile
from datetime import date

# notebooks run with the notebook folder as cwd, so ../src is the repo's src/ in both Repos and workspace copies
SRC_DIR = os.path.abspath(os.path.join(os.getcwd(), "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
# Python UDFs run in separate worker processes that do not see the sys.path change above,
# so the package is also shipped to them as a zip.
spark.sparkContext.addPyFile(shutil.make_archive(os.path.join(tempfile.mkdtemp(), "proc_intel"), "zip",
                                                 SRC_DIR, "proc_intel"))

CATALOG = "dbw_wb_outcome"
BRONZE = f"{CATALOG}.proc_bronze"
SILVER = f"{CATALOG}.proc_silver"
GOLD = f"{CATALOG}.proc_gold"
RAW_VOLUME = f"/Volumes/{CATALOG}/proc_bronze/raw"

# Outcome-project tables reused by joining (read only)
OUTCOME_PROJECTS = f"{CATALOG}.silver.projects"            # one row per project (cleaned)
OUTCOME_INDICATORS = f"{CATALOG}.bronze.indicators"        # WDI/WGI values with country names (long format)
COUNTRY_YEAR = f"{CATALOG}.silver.country_year"            # one row per country x year (WDI + WGI)
RISK_SCORES = f"{CATALOG}.gold.active_project_scores"      # outcome-model risk for active projects
RAG_CHUNKS = f"{CATALOG}.silver.rag_chunks"                # 50k document chunks with embeddings

AWARDS_URL = "https://datacatalogapi.worldbank.org/dexapps/fone/api/apiservice"
# FinancesOne addresses a dataset by dataset + resource id; DS00005/RS00005 is the IPF contract-awards table
AWARDS_PARAMS = {"datasetId": "DS00005", "resourceId": "RS00005", "type": "json"}
AWARDS_SOURCE = "financesone/DS00005"
NOTICES_URL = "https://search.worldbank.org/api/v2/procnotices"
NOTICES_SOURCE = "search.worldbank.org/api/v2/procnotices"
NOTICE_CUTOFF = date(2018, 1, 1)   # tenders that can lead to FY2020+ contracts

# COMMAND ----------

# MAGIC %md
# MAGIC ## Idempotent upsert: `merge_upsert()`
# MAGIC
# MAGIC **What:** `MERGE` a DataFrame into a Delta table on a deterministic key. New keys are inserted; an existing key is updated only when its `_row_hash` (a hash of the business columns) changed. With `mark_removed=True`, rows whose key is missing from a **full** snapshot get `_removed_at_source` set instead of being deleted. Returns the counts Delta records for the operation.
# MAGIC
# MAGIC **Why:** re-running an ingest must not duplicate rows, and should not rewrite unchanged rows. A soft-delete keeps history when the source withdraws a record, which matters for an audit trail. Only full snapshots may mark removals; a partial fetch would wrongly flag everything it did not request.

# COMMAND ----------

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, functions as F


def as_udf(fn, return_type):
    """Wrap a pure function from proc_intel as a Spark UDF.

    The lambda hides the function's type hints, which Spark 4 would otherwise try (and fail) to
    use for inferring an Arrow UDF type, printing a warning on every notebook run.
    """
    return F.udf(lambda *args: fn(*args), return_type)


def row_hash(columns: list[str]):
    """SHA-256 over the given columns, null-safe, as a change detector."""
    # coalesce to a placeholder first: concat_ws silently skips nulls, so (NULL, "x") and ("x", NULL) would hash the
    # same
    return F.sha2(F.concat_ws("||", *[F.coalesce(F.col(c).cast("string"), F.lit("<null>")) for c in columns]), 256)


def merge_upsert(df: DataFrame, target: str, key: str, mark_removed: bool = False) -> dict:
    """MERGE df into target on `key`; df must carry `_row_hash`. Returns Delta's operation metrics."""
    changed = "t._row_hash <> s._row_hash"
    if mark_removed:
        df = df.withColumn("_removed_at_source", F.lit(None).cast("timestamp"))
        changed += " OR t._removed_at_source IS NOT NULL"   # a withdrawn row that came back
    if not spark.catalog.tableExists(target):
        # create an empty table with the source schema so the first run can go through the same MERGE path as later runs
        df.limit(0).write.saveAsTable(target)
    merge = (DeltaTable.forName(spark, target).alias("t")
             .merge(df.alias("s"), f"t.{key} = s.{key}")
             .whenMatchedUpdateAll(condition=changed)
             .whenNotMatchedInsertAll())
    if mark_removed:
        # only rows not already flagged, so the original withdrawal timestamp is kept on later runs
        merge = merge.whenNotMatchedBySourceUpdate(condition="t._removed_at_source IS NULL",
                                                   set={"_removed_at_source": "current_timestamp()"})
    merge.execute()
    # history(1) is the MERGE just executed; Delta stores the counts there rather than returning them from execute()
    metrics = DeltaTable.forName(spark, target).history(1).select("operationMetrics").first()[0]
    wanted = ["numSourceRows", "numTargetRowsInserted", "numTargetRowsUpdated",
              "numTargetRowsNotMatchedBySourceUpdated"]
    return {k: int(metrics.get(k, 0)) for k in wanted}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Publishing a documented table: `publish_table()`, keys and comments
# MAGIC
# MAGIC **What:**
# MAGIC - `publish_table()` overwrites a table with a DataFrame, sets the table comment and one comment per column, makes the key columns `NOT NULL` and declares the **primary key**.
# MAGIC - `add_foreign_key()` declares a foreign key; `drop_foreign_keys()` removes every foreign key in a schema so a rebuild can replace parent tables.
# MAGIC
# MAGIC **Why:** Unity Catalog primary/foreign keys are *informational* (Databricks does not enforce them), but they document the model in Catalog Explorer, draw the relationships in the lineage/ER view, and let the optimizer use them. Because they are not enforced, every notebook also **counts** duplicates and orphans itself (see `dq_report`). Comments make each table self-describing for whoever browses the catalog next.

# COMMAND ----------

def _quote(text: str) -> str:
    return text.replace("'", "\\'")


def publish_table(df: DataFrame, table: str, comment: str, column_comments: dict[str, str],
                  primary_key: list[str] | None = None) -> int:
    """Overwrite `table` with df, document it, declare its primary key; returns the row count."""
    missing = set(df.columns) - set(column_comments)
    # refuse to publish an undocumented column rather than leave a gap in Catalog Explorer
    assert not missing, f"{table}: columns without a comment: {sorted(missing)}"
    (df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table))
    spark.sql(f"COMMENT ON TABLE {table} IS '{_quote(comment)}'")
    for col, text in column_comments.items():
        spark.sql(f"ALTER TABLE {table} ALTER COLUMN `{col}` COMMENT '{_quote(text)}'")
    if primary_key:
        name = f"pk_{table.split('.')[-1]}"
        # an overwrite keeps the old constraint, so drop it before re-adding (otherwise ADD fails on re-runs)
        spark.sql(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        for col in primary_key:
            # Unity Catalog only accepts a PRIMARY KEY on NOT NULL columns
            spark.sql(f"ALTER TABLE {table} ALTER COLUMN `{col}` SET NOT NULL")
        spark.sql(f"ALTER TABLE {table} ADD CONSTRAINT {name} PRIMARY KEY ({', '.join(primary_key)})")
    return spark.table(table).count()


def add_foreign_key(table: str, columns: list[str], parent: str, parent_columns: list[str]) -> None:
    name = f"fk_{table.split('.')[-1]}_{'_'.join(columns)}"
    spark.sql(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    spark.sql(f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({', '.join(columns)}) "
              f"REFERENCES {parent} ({', '.join(parent_columns)})")


def drop_foreign_keys(schema: str) -> int:
    """Drop every foreign key declared on tables of `schema` (catalog.schema); returns how many."""
    catalog, name = schema.split(".")
    fks = spark.sql(f"""
        SELECT table_name, constraint_name FROM {catalog}.information_schema.table_constraints
        WHERE table_schema = '{name}' AND constraint_type = 'FOREIGN KEY'""").collect()
    for r in fks:
        spark.sql(f"ALTER TABLE {schema}.{r.table_name} DROP CONSTRAINT IF EXISTS {r.constraint_name}")
    return len(fks)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data-quality checks: `dq_report()`
# MAGIC
# MAGIC **What:** small counting helpers (duplicate keys, nulls, orphan foreign keys) and `dq_report()`, which turns a list of `(table, check, value, expected)` tuples into one table with a pass/fail column.
# MAGIC
# MAGIC **Why:** one compact table per notebook is easier to read than scattered prints, and the `expected` column states the rule being checked, so a reader can see *why* a number is fine.

# COMMAND ----------

import pandas as pd


def duplicate_keys(df: DataFrame, key: list[str]) -> int:
    """Number of key values that occur more than once."""
    return df.groupBy(*key).count().filter("count > 1").count()


def null_count(df: DataFrame, col: str) -> int:
    return df.filter(F.col(col).isNull()).count()


def orphan_count(child: DataFrame, child_key: str, parent: DataFrame, parent_key: str) -> int:
    """Non-null child keys with no matching parent row."""
    keys = child.select(F.col(child_key).alias("_k")).filter(F.col("_k").isNotNull())
    return keys.join(parent.select(F.col(parent_key).alias("_k")), "_k", "left_anti").count()


def dq_report(checks: list[tuple]) -> pd.DataFrame:
    """checks: (table, check, value, rule) where rule is '== n', '<= n', '>= n' or 'info'."""
    rows = []
    for table, check, value, rule in checks:
        if rule == "info":
            # 'info' rows are context for the reader, never a pass/fail
            status = "info"
        else:
            op, bound = rule.split()
            ok = {"==": value == float(bound), "<=": value <= float(bound), ">=": value >= float(bound)}[op]
            status = "pass" if ok else "FAIL"
        rows.append({"table": table, "check": check, "value": str(value), "rule": rule, "status": status})
    return pd.DataFrame(rows)
