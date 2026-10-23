# Databricks notebook source
# MAGIC %md
# MAGIC # p00_setup — schemas, volume and libraries for the procurement work
# MAGIC
# MAGIC Creates three new schemas next to the outcome project's `bronze` / `silver` / `gold` in catalog `dbw_wb_outcome`, plus a volume for raw API snapshots, then smoke-tests the libraries and both APIs. Safe to re-run: every step is idempotent, and nothing outside the three new schemas is created or changed.

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <pre class="mermaid">
# MAGIC ---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC ---
# MAGIC flowchart TD
# MAGIC     cat["dbw_wb_outcome"]
# MAGIC     old["bronze / silver / gold / ml<br/>outcome project (read only from here)"]
# MAGIC     pb["proc_bronze<br/>raw records as delivered by the APIs"]
# MAGIC     raw["raw (volume)<br/>untouched JSON pages, one folder per snapshot"]
# MAGIC     ps["proc_silver<br/>cleaned, typed, keyed model (contracts, suppliers, notices, ...)"]
# MAGIC     pg["proc_gold<br/>tender timelines and the knowledge graph (nodes / edges)"]
# MAGIC     cat --> old
# MAGIC     cat --> pb --> raw
# MAGIC     cat --> ps
# MAGIC     cat --> pg
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
# MAGIC  dbw_wb_outcome
# MAGIC   +-- bronze / silver / gold / ml      outcome project (read only from here)
# MAGIC   +-- proc_bronze                      raw records as delivered by the APIs
# MAGIC   |     +-- raw (volume)               untouched JSON pages, one folder per snapshot
# MAGIC   +-- proc_silver                      cleaned, typed, keyed model (contracts, suppliers, notices, ...)
# MAGIC   +-- proc_gold                        tender timelines and the knowledge graph (nodes / edges)
# MAGIC ```
# MAGIC
# MAGIC </details>

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Schemas and volume
# MAGIC
# MAGIC **What:** creates `proc_bronze`, `proc_silver`, `proc_gold` and the volume `proc_bronze.raw`.
# MAGIC
# MAGIC **Why:** separate schemas keep the procurement work apart from the outcome project, so it can be rebuilt or dropped without touching the evaluated tables, while still living in the same catalog and joining to them directly. `IF NOT EXISTS` makes re-runs harmless.

# COMMAND ----------

# MAGIC %sql
# MAGIC USE CATALOG dbw_wb_outcome;
# MAGIC
# MAGIC CREATE SCHEMA IF NOT EXISTS proc_bronze COMMENT 'Procurement: raw contract awards and procurement notices as delivered by World Bank APIs';
# MAGIC CREATE SCHEMA IF NOT EXISTS proc_silver COMMENT 'Procurement: cleaned, typed, keyed data model (contracts, suppliers, notices, dimensions)';
# MAGIC CREATE SCHEMA IF NOT EXISTS proc_gold   COMMENT 'Procurement: tender timelines and knowledge-graph node/edge tables';
# MAGIC
# MAGIC CREATE VOLUME IF NOT EXISTS proc_bronze.raw COMMENT 'Untouched API responses, one folder per source and snapshot date';

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Libraries
# MAGIC
# MAGIC **What:** installs `rapidfuzz` (fast string similarity) and `unidecode` (transliteration to ASCII); then restarts Python.
# MAGIC
# MAGIC **Why:** the ML runtime already ships pandas, scikit-learn, scipy and requests, but not these two. Both are small, pure-wheel packages used by the entity-resolution code in `src/proc_intel`.

# COMMAND ----------

# MAGIC %pip install -q rapidfuzz unidecode

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Smoke test
# MAGIC
# MAGIC **What:** imports the shared package from `../src`, calls each API for one row, writes/reads/deletes a test file in the volume, and checks whether GraphFrames is available on this runtime.
# MAGIC
# MAGIC **Why:** proves imports, internet access and volume permissions work *before* the long ingests run. The GraphFrames check decides how `p06_knowledge_graph` runs its multi-hop queries.

# COMMAND ----------

import importlib.util
import rapidfuzz, unidecode, sklearn
from proc_intel.http import get_json

print("proc_intel loaded from", SRC_DIR)
print("rapidfuzz", rapidfuzz.__version__, "| scikit-learn", sklearn.__version__,
      "| unidecode check:", unidecode.unidecode("Côte d’Ivoire"))

awards = get_json(AWARDS_URL, {**AWARDS_PARAMS, "top": 1, "skip": 0})
print("awards API count:", awards["count"], "| as_of_date:", awards["data"][0]["as_of_date"])
notices = get_json(NOTICES_URL, {"format": "json", "rows": 1, "os": 0, "fl": "id,noticedate"})
print("notices API total:", notices["total"])

probe = f"{RAW_VOLUME}/_smoke_test.txt"
with open(probe, "w") as f:
    f.write("hello volume")
print(open(probe).read())
dbutils.fs.rm(probe)

print("graphframes python package:", importlib.util.find_spec("graphframes") is not None)
