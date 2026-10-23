# Databricks notebook source
# MAGIC %md
# MAGIC # p15_label_panel — evaluation labels from a three-tier escalation: code checks, a panel of three model judges, an AI adjudicator for disagreements
# MAGIC
# MAGIC Two evaluations in this project rest on labelled items: the 100 supplier-name pairs that chose the entity-resolution threshold in p04, and the 30 replayed agent briefs of the p11 review pack. The pair labels were first written by the AI agent that built the pipeline, and the briefs were scored by single judges. This notebook replaces both with the project's labelling method, a three-tier escalation that can be audited: (1) what code can decide is computed, such as the timeline check from the numbers the judges read; (2) three judges from different model families label every item independently with one written rubric, and where they agree their answer is the label; (3) where they disagree, the item escalates to an AI adjudicator agent with access to the warehouse tables and the web, which records written evidence for each decision (section 10). `adjudicate.html` shows only the escalated items (blind first, the judges' votes on request) and remains usable by a human reviewer; independent validation by procurement specialists is part of the pilot plan.

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <pre class="mermaid">
# MAGIC ---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC ---
# MAGIC flowchart TD
# MAGIC     pairs["data/supplier_pair_labels.csv (100 pairs)<br/>+ up to 3 contracts per record (proc_silver)"]
# MAGIC     prub["PAIR_RUBRIC: same / different / unsure"]
# MAGIC     pj["judges: gpt-oss-120b, Llama 4 Maverick, Qwen 3.5 122B"]
# MAGIC     briefs["data/human_review/review_briefs.csv (30 briefs)<br/>package, brief, cited records, actual outcome"]
# MAGIC     brub["BRIEF_RUBRIC: timeline_ok, precedents (each),<br/>risks (each), any_unsupported_claim"]
# MAGIC     bj["judges: gpt-oss-120b, Llama 4 Maverick, Llama 3.3 70B<br/>(Qwen wrote the briefs: excluded)"]
# MAGIC     panel["proc_gold.label_panel<br/>one vote per item x judge x field"]
# MAGIC     agg["proc_intel.panel: majority, disagreement rule,<br/>pairwise agreement, Fleiss' kappa"]
# MAGIC     pl["data/human_review/panel_labels.csv"]
# MAGIC     adj["tier 3: AI adjudicator (disagreements only)"]
# MAGIC     fin["adjudication_decisions.csv + apply_adjudication.py<br/>final_labels.csv, ER precision / recall, review pack"]
# MAGIC     pairs --> prub --> pj --> panel
# MAGIC     briefs --> brub --> bj --> panel
# MAGIC     panel --> agg --> pl --> adj --> fin
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
# MAGIC  data/supplier_pair_labels.csv (100 pairs)        data/human_review/review_briefs.csv (30 briefs)
# MAGIC   + up to 3 contracts per record (proc_silver)      package, brief, cited records, actual outcome
# MAGIC        |                                                   |
# MAGIC  PAIR_RUBRIC: same / different / unsure            BRIEF_RUBRIC: timeline_ok, precedents (each),
# MAGIC        |                                            risks (each), any_unsupported_claim
# MAGIC  judges: gpt-oss-120b, Llama 4 Maverick,                   |
# MAGIC          Qwen 3.5 122B                              judges: gpt-oss-120b, Llama 4 Maverick, Llama 3.3 70B
# MAGIC        \                                                  /   (Qwen wrote the briefs: excluded)
# MAGIC         +---------------- proc_gold.label_panel ---------+    one vote per item x judge x field
# MAGIC                                     |
# MAGIC        proc_intel.panel: majority, disagreement rule, pairwise agreement, Fleiss' kappa
# MAGIC                                     |
# MAGIC        data/human_review/panel_labels.csv  ->  tier 3: AI adjudicator (disagreements only)
# MAGIC                                     |
# MAGIC        adjudication_decisions.csv + apply_adjudication.py  ->  final_labels.csv, ER precision / recall, review pack
# MAGIC ```
# MAGIC
# MAGIC </details>
# MAGIC
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_gold.label_panel` | one judge's answer to one question about one item, with its one-line rationale | `item_type, item_id, judge, field` |
# MAGIC | `/Volumes/.../proc_bronze/raw/label_panel/panel_labels.csv` (copied to `data/human_review/`) | one item x field: panel value, the three votes, the disagreement flag and reason, the earlier automated label | `item_type, item_id, field` |
# MAGIC | `data/human_review/adjudication_decisions.csv` (written after this run by the tier-3 adjudicator) | one escalated item x field: decision, adjudicator, written evidence | `item_type, item_id, field` |
# MAGIC
# MAGIC Rubrics, parsing, majority, disagreement rule and agreement statistics are pure functions in `src/proc_intel/panel.py`, tested in `tests/test_panel.py`; the adjudication page and the merge script read the same rubric text.

# COMMAND ----------

# MAGIC %md
# MAGIC ## How it was built and tested
# MAGIC
# MAGIC **Step 1 — Which judges?**
# MAGIC - **Question:** which served models can label independently of the models whose output is being labelled?
# MAGIC - **What we found:** the workspace serves gpt-oss-120b (OpenAI), Llama 4 Maverick and Llama 3.3 70B (Meta), Qwen 3.5 122B (Alibaba), Claude models (Anthropic) and Gemma 3 12B (Google). Qwen 3.5 wrote the briefs; a Claude agent built the pipeline and wrote the earlier pair labels. All four judges used accept a strict JSON schema at temperature 0.
# MAGIC - **Decision:** pairs: gpt-oss, Maverick, Qwen 3.5; briefs: gpt-oss, Maverick, Llama 3.3 (Qwen out: it wrote the briefs; Claude out: it is the family of the earlier labeller; Gemma 3 12B is much smaller than the rest). Panel B therefore has two Meta judges, and section 9 shows they err together.
# MAGIC
# MAGIC **Step 2 — Give the judges the evidence the original labeller had**
# MAGIC - **Question:** can "same firm?" be answered from two names?
# MAGIC - **What we found:** the p04 labels were made from the names and, where unclear, the contracts; pairs such as "ARUN KUMAR" / "ARUN KUMAR" (two forest divisions) cannot be decided from names at all.
# MAGIC - **Decision:** each record carries up to three of its contracts (year, project, category, description), or award notices for a bidder that never signed; all 200 records have at least one line.
# MAGIC
# MAGIC **Step 3 — The judges' arithmetic**
# MAGIC - **Question:** is "does the actual duration lie inside the brief's P10-P90?" safe to ask a model?
# MAGIC - **What we found:** in the first complete run both Llama models said 84 days lies inside 96-262 days (and 28 inside 77-290, 48 inside 55-225); with two Meta judges on the panel, the majority was wrong on 3 of 30 briefs.
# MAGIC - **Decision:** the judges read the three numbers and the code compares them (`timeline_vote`). Now 30 of 30 are unanimous and equal p11's rule-based check on 30 of 30. The same pattern for the counts: a verdict per listed precedent and risk, counted in code.
# MAGIC
# MAGIC **Step 4 — Finding unsupported claims is noisy, checking them is not**
# MAGIC - **Question:** why do the judges disagree on "any unsupported claim?"
# MAGIC - **What we found:** asked yes/no, the judges almost never said yes (2, 3 and 0 of 30 briefs; the single p11 judge had flagged 9). Asked to quote the claims, 17 of 30 briefs split (Fleiss' kappa 0.19), mostly because each judge found a different claim.
# MAGIC - **Decision:** section 3b pools every quoted claim and has every judge check every pooled claim; 9 briefs split (kappa 0.42). The verdicts stay independent; the list of claims to check is shared.
# MAGIC
# MAGIC **Step 5 — A rubric rule that made the panel unanimously wrong**
# MAGIC - **Question:** where do settled panel labels differ from the earlier labels, and why?
# MAGIC - **What we found:** the first pair rubric said identical personal names on the same project are one person. The panel then called three pairs "same" unanimously that the earlier labeller had separated with evidence (two "ARUN KUMAR" in different forest divisions; an Ethiopian father and son, "TESFAY G/KIRSTOS G/HIWOT" and "FISAHA TESFAY G/KIRSTOS"; a common Bangladeshi name in different districts).
# MAGIC - **Decision:** names of people now need the same place or the same specific assignment; an added or dropped given or father's name is another person; no place shown means "unsure". Two of the three now escalate to tier 3; the third stays unanimous ("MOMINUL HOQUE": its contract lines show no district) and is listed in section 9. The rubric was revised after seeing answers on these same 100 items, so its agreement here is optimistic.
# MAGIC
# MAGIC **Step 6 — When does a count need escalation?**
# MAGIC - **Question:** two judges saying 3 and 4 relevant risks is not a real disagreement; 1 and 4 is.
# MAGIC - **What we found:** exact agreement on counts is 0.74 (risks) and 0.91 (precedents), within one 0.92 and 0.98.
# MAGIC - **Decision:** a count escalates when the votes differ by 2 or more, when "n/a" is mixed with numbers, or when judges fall on both sides of "most listed items are relevant" (exactly half sides with neither). 4 risk counts and 1 precedent count escalate.

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
# MAGIC **What:** the two panels, the label files, the cache of raw judge answers and the output table. The briefs file is a parameter: `review_briefs.csv` (the default) labels pairs and briefs into `proc_gold.label_panel` and `panel_labels.csv`; a re-measured review pack such as `review_briefs_v2.csv` is labelled by the same panel B with the same rubric into outputs with the same suffix (`proc_gold.label_panel_v2`, `panel_labels_v2.csv`), and its pairs are not relabelled (their final labels are those of the first run). The briefs rubric is versioned: v1 is the rubric of the first run; v2 (`BRIEF_RUBRIC_V2`, `CLAIM_RUBRIC_V2`) adds a facts line for the package and for each cited contract, treats every mitigation or piece of advice as no claim, and checks evidence-gap statements against cited tool-log records, or else only for consistency with the cited records. A v2 run on the first run's briefs gets its own suffix (for example `_v1r`), so v1 and v2 briefs are compared under the same rubric.
# MAGIC
# MAGIC **Why:** the panels are fixed here so that every number below names its judges. Part B leaves out Qwen 3.5 because it wrote the briefs (a judge tends to prefer text from its own model); that puts two Meta models on panel B. The workspace also serves Anthropic (Claude) and Google (Gemma 3 12B) models: Claude is left out because a Claude agent built this pipeline and wrote the earlier pair labels the panel is compared with, and Gemma 3 12B is a much smaller model than the rest. Raw answers are cached in the volume, so a re-run reuses them instead of asking again. The same three judge models can also be called through OpenRouter (the `backend` parameter) to label faster; every answer records which service and provider served it, and a throttled or failed OpenRouter call falls back to the workspace endpoint of the same model.

# COMMAND ----------

import hashlib
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from pyspark.sql import functions as F

from proc_intel import panel as pn
from proc_intel.similarity import precision_recall, wilson_interval

PANEL_A = ["databricks-gpt-oss-120b", "databricks-llama-4-maverick", "databricks-qwen35-122b-a10b"]
PANEL_B = ["databricks-gpt-oss-120b", "databricks-llama-4-maverick", "databricks-meta-llama-3-3-70b-instruct"]
FAMILY = {"databricks-gpt-oss-120b": "OpenAI", "databricks-llama-4-maverick": "Meta",
          "databricks-meta-llama-3-3-70b-instruct": "Meta", "databricks-qwen35-122b-a10b": "Alibaba"}
SHORT = {"databricks-gpt-oss-120b": "gpt-oss-120b", "databricks-llama-4-maverick": "llama-4-maverick",
         "databricks-meta-llama-3-3-70b-instruct": "llama-3.3-70b", "databricks-qwen35-122b-a10b": "qwen3.5-122b"}
dbutils.widgets.text("briefs_file", "review_briefs.csv")
dbutils.widgets.dropdown("rubric", "v1", ["v1", "v2"])
dbutils.widgets.text("out_tag", "")
BRIEFS_FILE = dbutils.widgets.get("briefs_file").strip() or "review_briefs.csv"
RUBRIC = dbutils.widgets.get("rubric")
TAG = pn.output_tag(BRIEFS_FILE, RUBRIC, dbutils.widgets.get("out_tag"))   # "" only for review_briefs.csv + rubric v1
BRIEF_RUBRIC, CLAIM_RUBRIC, PACKAGE_FACTS = pn.RUBRIC_VERSIONS[RUBRIC]
WITH_PAIRS = TAG == ""            # a re-measured review pack relabels the briefs only
DATA_DIR = os.path.join(os.path.dirname(SRC_DIR), "data")
PAIRS_PATH = os.path.join(DATA_DIR, "supplier_pair_labels.csv")
BRIEFS_PATH = os.path.join(DATA_DIR, "human_review", BRIEFS_FILE)
OUT_DIR = f"{RAW_VOLUME}/label_panel"
CACHE_PATH = f"{OUT_DIR}/judge_cache.json"
PANEL_TABLE = f"{GOLD}.label_panel{TAG}"
PANEL_CSV = f"{OUT_DIR}/panel_labels{TAG}.csv"
JUDGES = sorted(set(PANEL_A) | set(PANEL_B)) if WITH_PAIRS else sorted(PANEL_B)
CONTRACTS_PER_RECORD = 3
dbutils.widgets.dropdown("backend", "databricks", ["databricks", "openrouter"])
BACKEND = dbutils.widgets.get("backend")    # openrouter: the same models through OpenRouter, Databricks as fallback
WORKERS = 30 if BACKEND == "openrouter" else 4
MAX_DBU = 15.0                    # hard stop for the panel's token spend
OR_MAX_USD = 0.5                  # hard stop for one run's OpenRouter spend, then Databricks endpoints
OR_SLUG = {"databricks-gpt-oss-120b": "openai/gpt-oss-120b", "databricks-llama-4-maverick": "meta-llama/llama-4-maverick",
           "databricks-meta-llama-3-3-70b-instruct": "meta-llama/llama-3.3-70b-instruct",
           "databricks-qwen35-122b-a10b": "qwen/qwen3.5-122b-a10b"}
# DBU per million tokens (input, output) of the pay-per-token endpoints; Maverick assumed equal to Llama 3.3
DBU_PER_M = {"databricks-gpt-oss-120b": (2.143, 8.571), "databricks-llama-4-maverick": (7.143, 21.429),
             "databricks-meta-llama-3-3-70b-instruct": (7.143, 21.429), "databricks-qwen35-122b-a10b": (3.143, 31.429)}
os.makedirs(OUT_DIR, exist_ok=True)
assert set(PANEL_A) | set(PANEL_B) <= set(DBU_PER_M)
print(f"briefs: {BRIEFS_FILE} | briefs rubric {RUBRIC} | pairs relabelled: {WITH_PAIRS} | backend {BACKEND} | "
      f"outputs: {PANEL_TABLE}, {PANEL_CSV}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The endpoints: present and callable
# MAGIC
# MAGIC **What:** checks that every judge is a serving endpoint of this workspace and in state READY, then sends each a tiny structured request (the strict JSON schema of the pair rubric). `chat()` posts with a timeout and backoff on throttling, temperature 0, thinking off for Qwen 3.5 (`reasoning_effort="none"`) and low effort for gpt-oss (a reasoning model that cannot switch thinking off); every call adds its tokens to a ledger.
# MAGIC
# MAGIC **Why:** a misspelt or missing endpoint should stop the notebook before any labelling, and an endpoint that rejects the JSON schema is detected here and falls back to plain JSON in the prompt (the answer is then parsed and validated the same way).

# COMMAND ----------

from databricks.sdk import WorkspaceClient

_HOST = spark.conf.get("spark.databricks.workspaceUrl")
_TOKEN = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
_LOCK = threading.Lock()
LEDGER = {}                       # endpoint -> [prompt tokens, completion tokens, calls]
SCHEMA_OK = {}                    # endpoint -> accepts response_format json_schema

served = {e.name: (e.state.ready.value if e.state and e.state.ready else None) for e in WorkspaceClient().serving_endpoints.list()}
for name in JUDGES:
    print(f"{name:42s} {FAMILY[name]:8s} {served.get(name)}")
missing = [n for n in JUDGES if served.get(n) != "READY"]
assert not missing, f"endpoints missing or not ready: {missing}"


def dbu_spent():
    with _LOCK:
        return sum((p * DBU_PER_M[m][0] + c * DBU_PER_M[m][1]) / 1e6 for m, (p, c, _) in LEDGER.items())


def _post(endpoint, body, timeout=180, max_retries=8):
    for attempt in range(max_retries):
        try:
            r = requests.post(f"https://{_HOST}/serving-endpoints/{endpoint}/invocations",
                              headers={"Authorization": f"Bearer {_TOKEN}"}, json=body, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 400:
                raise ValueError(f"HTTP 400: {r.text[:300]}")
            err = f"HTTP {r.status_code}: {r.text[:200]}"
            retry = r.status_code == 429 or r.status_code >= 500
        except requests.exceptions.RequestException as e:
            err, retry = f"{type(e).__name__}: {str(e)[:200]}", True
        if not retry or attempt == max_retries - 1:
            raise RuntimeError(f"{endpoint} failed: {err}")
        time.sleep(min(30, 0.5 * 2 ** attempt) + random.random() * 0.5)


_LOCAL = threading.local()        # served_by of the last answer on this thread
OR_STATE = {"usd": 0.0, "off": None, "fallbacks": 0}
OR_LEDGER = {}                    # endpoint -> [prompt tokens, completion tokens, calls, USD]
if BACKEND == "openrouter":
    _OR_KEY = dbutils.secrets.get("procurement", "openrouter_api_key")
    _k = requests.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {_OR_KEY}"}, timeout=30).json()["data"]
    print(f"OpenRouter key: usage {_k.get('usage')} of limit {_k.get('limit')} (remaining {_k.get('limit_remaining')})")


class _Fallback(Exception):
    pass


def _openrouter_chat(endpoint, system, user, schema, max_tokens):
    """The same model through OpenRouter (strict schema required of the provider); _Fallback -> Databricks endpoint."""
    with _LOCK:
        if OR_STATE["usd"] > OR_MAX_USD:
            OR_STATE["off"] = "run budget reached"
        if OR_STATE["off"]:
            raise _Fallback(OR_STATE["off"])
    body = {"model": OR_SLUG[endpoint], "max_tokens": max_tokens, "temperature": 0.0, "response_format": schema,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "usage": {"include": True}, "provider": {"require_parameters": True}}
    if "gpt-oss" in endpoint:
        body["reasoning"] = {"effort": "low"}
    if "qwen" in endpoint:
        body["reasoning"] = {"enabled": False}
    j, err = None, ""
    for attempt in range(3):
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions", json=body, timeout=120,
                              headers={"Authorization": f"Bearer {_OR_KEY}"})
            if r.status_code == 402:
                with _LOCK:
                    OR_STATE["off"] = "HTTP 402 (credit)"
                raise _Fallback("402")
            if r.status_code == 429:
                raise _Fallback("429")
            if r.status_code == 200 and "choices" in (r.json() or {}):
                j = r.json()
                break
            err = f"HTTP {r.status_code}: {r.text[:120]}"
        except requests.exceptions.RequestException as e:
            err = type(e).__name__
        time.sleep(1 + attempt * 2)
    if j is None:
        raise _Fallback(f"3 failed attempts ({err})")
    content = j["choices"][0]["message"].get("content")
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    if not (content or "").strip():
        raise _Fallback("empty answer")
    u = j.get("usage") or {}
    with _LOCK:
        row = OR_LEDGER.setdefault(endpoint, [0, 0, 0, 0.0])
        row[0] += u.get("prompt_tokens") or 0
        row[1] += u.get("completion_tokens") or 0
        row[2] += 1
        row[3] += u.get("cost") or 0.0
        OR_STATE["usd"] += u.get("cost") or 0.0
    _LOCAL.served_by = f"openrouter:{j.get('provider') or 'unknown'}"
    return content.strip()


def chat(endpoint, system, user, schema, max_tokens):
    """Text of one judge answer; the strict schema is sent when the endpoint accepts it."""
    if BACKEND == "openrouter":
        try:
            return _openrouter_chat(endpoint, system, user, schema, max_tokens)
        except _Fallback:
            with _LOCK:
                OR_STATE["fallbacks"] += 1
    _LOCAL.served_by = "databricks"
    if dbu_spent() > MAX_DBU:
        raise RuntimeError("panel spend cap reached")
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens, "temperature": 0.0}
    if "qwen35" in endpoint:
        body["reasoning_effort"] = "none"
    if "gpt-oss" in endpoint:
        body["reasoning_effort"] = "low"
    if SCHEMA_OK.get(endpoint, True):
        try:
            resp = _post(endpoint, {**body, "response_format": schema})
        except ValueError:
            SCHEMA_OK[endpoint] = False
            resp = _post(endpoint, body)
    else:
        resp = _post(endpoint, body)
    content = resp["choices"][0]["message"].get("content")
    if isinstance(content, list):                     # reasoning models answer with typed blocks
        content = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    u = resp.get("usage") or {}
    with _LOCK:
        row = LEDGER.setdefault(endpoint, [0, 0, 0])
        row[0] += u.get("prompt_tokens") or 0
        row[1] += u.get("completion_tokens") or 0
        row[2] += 1
    return (content or "").strip()


for name in JUDGES:
    t0 = time.time()
    text = chat(name, pn.PAIR_RUBRIC, pn.pair_message("ACME TRADING LTD", "ACME TRADING LIMITED", "GH"), pn.PAIR_SCHEMA, 600)
    print(f"{SHORT[name]:18s} schema accepted: {SCHEMA_OK.get(name, True)!s:5s} {time.time() - t0:5.1f} s  {text[:140]}")
    assert pn.parse_json_object(text), f"{name}: no JSON in the test answer"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. The items
# MAGIC
# MAGIC **What:** the 100 pairs with up to three contracts per record (signing year, project, category, description; for a record that never signed a contract, up to three award notices that name it), and the 30 briefs with the number of precedents and risks each lists.
# MAGIC
# MAGIC **Why:** the original pair labels were made "by reading the names and, where unclear, the contracts" (p04), and identical personal names ("ARUN KUMAR" in two forest divisions) cannot be decided from names alone; the judges and the adjudicator get the same evidence. The listed counts are needed by the disagreement rule for counts ("most listed items relevant" or not).

# COMMAND ----------

pairs = pd.read_csv(PAIRS_PATH, dtype=str, keep_default_na=False)
if not WITH_PAIRS:                # a re-measured review pack: the pairs keep the first run's final labels
    pairs = pairs.iloc[0:0].copy()
briefs = pd.read_csv(BRIEFS_PATH, dtype=str, keep_default_na=False)
briefs["n_precedents"] = briefs["n_precedents"].astype(int)
briefs["n_risks"] = [pn.listed_items(t, "Risks and mitigations") for t in briefs["brief_text"]]
assert (briefs["n_precedents"] == [pn.listed_items(t, "Similar precedents") for t in briefs["brief_text"]]).all()


def record_lines(pairs):
    """(supplier_id, name) -> (kind, up to CONTRACTS_PER_RECORD lines, newest first) for every record of the pairs."""
    records = spark.createDataFrame(
        pd.concat([pairs[["supplier_id_a", "name_a"]].set_axis(["supplier_id", "name"], axis=1),
                   pairs[["supplier_id_b", "name_b"]].set_axis(["supplier_id", "name"], axis=1)]).drop_duplicates())
    contract_lines = (spark.table(f"{SILVER}.contract_suppliers").select("contract_id", "supplier_id", F.col("supplier_name").alias("name"))
                      .join(records, ["supplier_id", "name"])
                      .join(spark.table(f"{SILVER}.contracts").select("contract_id", "project_id", "signing_date",
                                                                      "procurement_category_code", "contract_description"), "contract_id")
                      .select("supplier_id", "name", F.col("signing_date").alias("d"),
                              F.concat_ws(" ", F.year("signing_date"), "project_id", "procurement_category_code",
                                          F.substring("contract_description", 1, 90)).alias("line")))
    notice_lines = (spark.table(f"{SILVER}.notice_bidders").select("notice_id", "supplier_id", F.col("firm_name").alias("name"), "role")
                    .join(records, ["supplier_id", "name"])
                    .join(spark.table(f"{SILVER}.notices").select("notice_id", "project_id", "notice_date", "bid_description"), "notice_id")
                    .select("supplier_id", "name", F.col("notice_date").alias("d"),
                            F.concat_ws(" ", F.year("notice_date"), "project_id", F.concat(F.lit("award notice, "), "role"),
                                        F.substring("bid_description", 1, 90)).alias("line")))
    ctx = {}
    for source in (contract_lines, notice_lines):
        for r in source.orderBy(F.desc("d")).collect():
            key = (r.supplier_id, r.name)
            if source is notice_lines and key in ctx and ctx[key][0] == "contract":
                continue
            kind, lines = ctx.setdefault(key, ("contract" if source is contract_lines else "notice", []))
            if len(lines) < CONTRACTS_PER_RECORD:
                lines.append("  " + r.line)
    return ctx


ctx = record_lines(pairs) if WITH_PAIRS else {}
n_records = len(pd.concat([pairs[["supplier_id_a", "name_a"]].set_axis(["supplier_id", "name"], axis=1),
                           pairs[["supplier_id_b", "name_b"]].set_axis(["supplier_id", "name"], axis=1)]).drop_duplicates())
pairs["contracts_a"] = ["\n".join(ctx.get((s, n), ("", []))[1]) for s, n in zip(pairs["supplier_id_a"], pairs["name_a"])]
pairs["contracts_b"] = ["\n".join(ctx.get((s, n), ("", []))[1]) for s, n in zip(pairs["supplier_id_b"], pairs["name_b"])]
print(f"pairs {len(pairs)} | records with contract or notice lines: {len(ctx)} of {n_records} | "
      f"briefs {len(briefs)}, precedents listed {briefs['n_precedents'].sum()}, risks listed {briefs['n_risks'].sum()}")
if WITH_PAIRS:
    print(pn.pair_message(*pairs.loc[87, ["name_a", "name_b", "country_code", "contracts_a", "contracts_b"]]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. The panel labels every item, independently
# MAGIC
# MAGIC **What:** one request per item and judge (100 x 3 pairs, 30 x 3 briefs), each with only the rubric and the item: no judge sees another judge's answer or the earlier labels. Four requests run at a time; answers are parsed (`parse_json_object`), validated (`normalise`) and kept in a cache keyed by judge, rubric and message.
# MAGIC
# MAGIC **Why:** independence is what makes agreement between judges informative. An answer that is not valid JSON or has an invalid value is asked once more and otherwise recorded as "no valid answer", which escalates the item rather than letting two judges decide.

# COMMAND ----------

try:
    CACHE = json.load(open(CACHE_PATH))
except FileNotFoundError:
    CACHE = {}
SERVED = []                       # (endpoint, served_by, from cache) per judgement of this run


def judge(endpoint, system, user, schema, max_tokens):
    """(parsed answer or None, raw text) for one item and judge, cached by content."""
    key = hashlib.sha1(json.dumps([endpoint, system, user]).encode()).hexdigest()
    with _LOCK:
        if key in CACHE:
            SERVED.append((endpoint, CACHE[key].get("served_by", "databricks"), True))
            return CACHE[key]["answer"], CACHE[key]["text"]
    answer, text = None, ""
    for _ in (1, 2):
        try:
            text = chat(endpoint, system, user, schema, max_tokens)
        except RuntimeError as e:
            text = f"ERROR {e}"[:300]
            continue
        answer = pn.parse_json_object(text)
        if answer is not None:
            break
    served_by = getattr(_LOCAL, "served_by", "databricks")
    with _LOCK:
        CACHE[key] = {"answer": answer, "text": text[:4000], "served_by": served_by}
        SERVED.append((endpoint, served_by, False))
    return answer, text


jobs = ([("pair", r.pair_id, j, pn.PAIR_RUBRIC,
          pn.pair_message(r.name_a, r.name_b, r.country_code, r.contracts_a, r.contracts_b), pn.PAIR_SCHEMA, 700)
         for r in pairs.itertuples() for j in PANEL_A]
        + [("brief", r["review_id"], j, BRIEF_RUBRIC, pn.brief_message(r, PACKAGE_FACTS), pn.BRIEF_SCHEMA, 2000)
           for r in briefs.to_dict("records") for j in PANEL_B])
t0 = time.time()
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    answers = list(pool.map(lambda job: judge(*job[2:]), jobs))
json.dump(CACHE, open(CACHE_PATH, "w"))
print(f"{len(jobs)} judgements in {time.time() - t0:.0f} s; schema accepted: {SCHEMA_OK or 'all'}; "
      f"no JSON: {sum(a is None for a, _ in answers)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3b. Unsupported claims: every judge checks every claim any judge quoted
# MAGIC
# MAGIC **What:** the claims the three judges quoted as unsupported in step 3 are pooled per brief (`candidate_claims`: duplicates once, at most 8). Each judge then checks each pooled claim against the records (`CLAIM_RUBRIC`), told neither who quoted it nor what the others decided. A judge's `any_unsupported_claim` is "yes" when it calls at least one pooled claim unsupported; a brief where no judge quoted a claim is "no" for all three.
# MAGIC
# MAGIC **Why:** with each judge searching a brief on its own, 17 of the 30 briefs split (Fleiss' kappa 0.19), mostly because one judge noticed a claim the others never looked at, not because they disagreed about it. Finding a claim and checking it are different tasks: the pool keeps every judge's finds, and the check makes the verdicts comparable. The verdicts stay independent; only the list of claims to check is shared.

# COMMAND ----------

brief_answer = {(job[1], job[2]): a for job, (a, _) in zip(jobs, answers, strict=True) if job[0] == "brief"}
pooled = {}
for r in briefs.to_dict("records"):
    found = [(brief_answer.get((r["review_id"], j)) or {}).get("unsupported_claims") for j in PANEL_B]
    pooled[r["review_id"]] = pn.candidate_claims([f if isinstance(f, list) else [] for f in found])
claim_jobs = [(r["review_id"], j, pn.claim_message(r, pooled[r["review_id"]], PACKAGE_FACTS))
              for r in briefs.to_dict("records") if pooled[r["review_id"]] for j in PANEL_B]
t0 = time.time()
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    claim_answers = list(pool.map(lambda job: judge(job[1], CLAIM_RUBRIC, job[2], pn.CLAIM_SCHEMA, 1200), claim_jobs))
json.dump(CACHE, open(CACHE_PATH, "w"))
claim_vote = {(rid, j): pn.claim_vote(a, pooled[rid]) for (rid, j, _), (a, _) in zip(claim_jobs, claim_answers, strict=True)}
print(f"briefs with a quoted claim: {sum(bool(c) for c in pooled.values())} of {len(briefs)}; pooled claims: "
      f"{sum(map(len, pooled.values()))}; {len(claim_jobs)} checks in {time.time() - t0:.0f} s")
served_df = (pd.DataFrame(SERVED, columns=["judge", "served_by", "from_cache"]).assign(judge=lambda d: d["judge"].map(SHORT))
             .value_counts().rename("answers").reset_index().sort_values(["judge", "served_by", "from_cache"]))
served_df.to_csv(f"{OUT_DIR}/panel_providers{TAG}.csv", index=False)
print(served_df.to_string(index=False))
if OR_LEDGER:
    print("OpenRouter:", {SHORT[m]: {"calls": c, "prompt_tokens": p, "completion_tokens": o, "usd": round(u, 4)}
                          for m, (p, o, c, u) in OR_LEDGER.items()}, "| fallbacks to Databricks:", OR_STATE["fallbacks"],
          "| switched off:", OR_STATE["off"])
if LEDGER:                        # Databricks endpoint calls of this run (none when OpenRouter served everything)
    display(pd.DataFrame([{"endpoint": m, "calls": c, "prompt_tokens": p, "completion_tokens": o,
                           "dbu": round((p * DBU_PER_M[m][0] + o * DBU_PER_M[m][1]) / 1e6, 3)} for m, (p, o, c) in LEDGER.items()]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. `proc_gold.label_panel`: one row per item x judge x field
# MAGIC
# MAGIC **What:** each answer becomes one vote per field: `same_firm` for a pair; `timeline_ok`, `precedents_relevant`, `risks_relevant`, `any_unsupported_claim` for a brief. For a brief the judge reads and the code decides (`brief_votes`): `timeline_ok` is computed from the P10, P90 and actual days the judge read; the two counts from its verdict on each listed precedent and risk; `any_unsupported_claim` comes from the check of the pooled claims (3b). The rationale shows the numbers read, the items accepted or the claims quoted. An invalid answer is stored with an empty value.
# MAGIC
# MAGIC **Why:** a long table keeps every vote and its reason queryable, so any final label can be traced to who said what. Computing the yes/no from the numbers removes the judges' arithmetic slips (in the first run both Llama models called 84 days "inside" a 96-262 day range).

# COMMAND ----------

brief_of = briefs.set_index("review_id")
vote_rows = []
for (item_type, item_id, endpoint, *_), (answer, text) in zip(jobs, answers, strict=True):
    if item_type == "pair":
        v = pn.normalise("same_firm", (answer or {}).get("answer"))
        votes = {"same_firm": (v, str((answer or {}).get("reason", "")) if v else f"no valid answer: {text[:150]}")}
    else:
        b = brief_of.loc[item_id]
        votes = pn.brief_votes(answer, int(b["n_precedents"]), int(b["n_risks"]))
        if votes["any_unsupported_claim"][0] is not None:          # the check of the pooled claims decides
            votes["any_unsupported_claim"] = claim_vote.get((item_id, endpoint), ("no", "no judge quoted an unsupported claim"))
    for field, (value, why) in votes.items():
        vote_rows.append({"item_type": item_type, "item_id": str(item_id), "judge": endpoint, "field": field,
                          "value": value, "rationale": " ".join(why.split())[:300]})
votes_df = pd.DataFrame(vote_rows)
n_panel = publish_table(
    spark.createDataFrame(votes_df.astype(object).where(votes_df.notna(), None),
                          "item_type string, item_id string, judge string, field string, value string, rationale string"),
    PANEL_TABLE,
    "Label panel (p15): one judge's answer to one rubric question about one evaluation item. "
    "Grain: item_type x item_id x judge x field.",
    {"item_type": f"pair (data/supplier_pair_labels.csv) or brief (data/human_review/{BRIEFS_FILE})",
     "item_id": "pair_id or review_id",
     "judge": "Serving endpoint that answered",
     "field": "same_firm | timeline_ok | precedents_relevant | risks_relevant | any_unsupported_claim",
     "value": "same/different/unsure, yes/no, 0-5 or n/a; null when the judge gave no valid answer",
     "rationale": "The judge's one-line reason (for counts: the items it judged relevant)"},
    primary_key=["item_type", "item_id", "judge", "field"])
print(f"{PANEL_TABLE}: {n_panel} rows; invalid votes: {int(votes_df['value'].isna().sum())}")
display(votes_df.groupby(["item_type", "field", "judge"])["value"].value_counts().unstack(fill_value=0))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Panel value, disagreements and agreement
# MAGIC
# MAGIC **What:** per item and field the panel value (majority; median for counts) and whether it escalates to tier 3 (`disagreement`): any differing vote for same/different/unsure and yes/no (and unanimous "unsure"); for counts a spread of 2 or more, "n/a" mixed with numbers, or judges on both sides of "most listed items are relevant". Agreement between judges: pairwise share of equal votes and Fleiss' kappa (chance-corrected; 1 = perfect, 0 = chance), for counts also within one. Then the panel value against the earlier automated labels (the building agent's pair labels; p11's rule and single-judge scores).
# MAGIC
# MAGIC **Why:** the number of disagreements is tier 3's workload; the agreement statistics say how much the settled labels can be trusted without escalation. Agreement with the earlier labels is not accuracy: neither side is ground truth.

# COMMAND ----------

vote_of = {(r["item_type"], r["item_id"], r["field"], r["judge"]): r["value"] for r in vote_rows}
keys = list(dict.fromkeys((r["item_type"], r["item_id"], r["field"]) for r in vote_rows))     # job order
items = []
for item_type, item_id, field in keys:
    judges = PANEL_A if item_type == "pair" else PANEL_B
    v = [vote_of[(item_type, item_id, field, j)] for j in judges]
    n_listed = None
    if item_type == "brief":
        b = brief_of.loc[item_id]
        n_listed = {"precedents_relevant": int(b["n_precedents"]), "risks_relevant": int(b["n_risks"])}.get(field)
    reason = pn.disagreement(field, v, n_listed)
    items.append({"item_type": item_type, "item_id": item_id, "field": field, "n_listed": n_listed, "votes": v,
                  "judges": judges, "panel_value": pn.panel_value(field, v), "needs_owner": bool(reason), "reason": reason})
agg = pd.DataFrame(items)

earlier = {("pair", p, "same_firm"): {"1": "same", "0": "different"}.get(v) for p, v in zip(pairs["pair_id"], pairs["label_same_entity"])}
for b in briefs.to_dict("records"):
    earlier[("brief", b["review_id"], "timeline_ok")] = pn.normalise("timeline_ok", b["auto_timeline_ok"])
    earlier[("brief", b["review_id"], "precedents_relevant")] = (
        pn.NOT_APPLICABLE if b["n_precedents"] == 0 else pn.normalise("precedents_relevant", b["auto_precedents_relevant"]))
    earlier[("brief", b["review_id"], "any_unsupported_claim")] = pn.normalise("any_unsupported_claim", b["auto_unsupported_claim"])
agg["earlier_label"] = [earlier.get((t, i, f)) for t, i, f in zip(agg["item_type"], agg["item_id"], agg["field"])]

stats = []
for (item_type, field), g in agg.groupby(["item_type", "field"], sort=False):
    judges = g["judges"].iloc[0]
    by_judge = {SHORT[j]: [v[k] for v in g["votes"]] for k, j in enumerate(judges)}
    kind = pn.FIELD_KIND[field]
    pw = pn.pairwise_agreement(by_judge)
    row = {"item_type": item_type, "field": field, "items": len(g), "unanimous": int(g["votes"].map(lambda v: len(set(v)) == 1).sum()),
           "needs_owner": int(g["needs_owner"].sum()), "pairwise_agreement": pw["mean"],
           **{f"agree {k}": v for k, v in pw["pairs"].items()},
           "fleiss_kappa": pn.fleiss_kappa(list(g["votes"])) if kind != "count" else None,
           "pairwise_within_1": pn.pairwise_agreement(by_judge, tolerance=1)["mean"] if kind == "count" else None}
    if g["earlier_label"].notna().any():
        settled = g[~g["needs_owner"]]
        row["agree_with_earlier_all"] = pn.agreement_with(list(g["earlier_label"]), list(g["panel_value"]))["agreement"]
        a = pn.agreement_with(list(settled["earlier_label"]), list(settled["panel_value"]))
        row["agree_with_earlier_settled"], row["n_settled_compared"] = a["agreement"], a["n"]
    stats.append(row)
stats_df = pd.DataFrame(stats)
display(stats_df.round(3))
print("items the owner must adjudicate:",
      {t: int(g.groupby("item_id")["needs_owner"].any().sum()) for t, g in agg.groupby("item_type")},
      "| fields:", agg.groupby("item_type")["needs_owner"].sum().to_dict())
display(agg[agg["needs_owner"]].groupby(["item_type", "field", "reason"]).size().reset_index(name="items"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. The pipeline's decision on each pair, and ER precision / recall on settled pairs
# MAGIC
# MAGIC **What:** for each labelled pair, whether the published `supplier_entity_map` puts both supplier ids in one entity (the p04 decision at threshold 0.70, chained merges included). Check: against the earlier labels this must reproduce p04's 36 true positives, 1 false positive and 4 misses. Then precision and recall against the panel on the pairs the panel settled (the final numbers, after adjudication, come from `apply_adjudication.py`).
# MAGIC
# MAGIC **Why:** the merge script runs locally on tiny CSVs, so the pipeline's decision is exported with the labels instead of being recomputed from the full trigram matrix.

# COMMAND ----------

if WITH_PAIRS:                    # a re-measured review pack keeps the first run's pair labels and metrics
    ids = list(set(pairs["supplier_id_a"]) | set(pairs["supplier_id_b"]))
    entity = {r.supplier_id: r.supplier_entity_id for r in
              spark.table(f"{SILVER}.supplier_entity_map").filter(F.col("supplier_id").isin(ids)).collect()}
    pairs["pipeline_same"] = [entity.get(a) is not None and entity.get(a) == entity.get(b)
                              for a, b in zip(pairs["supplier_id_a"], pairs["supplier_id_b"])]
    old = precision_recall(pairs["label_same_entity"].eq("1").tolist(), pairs["pipeline_same"].tolist())
    print(f"pipeline vs earlier labels: tp {old['tp']} fp {old['fp']} fn {old['fn']} | precision {old['precision']:.3f} recall {old['recall']:.3f}")
    assert (old["tp"], old["fp"], old["fn"]) == (36, 1, 4), "the published entity map no longer matches p04's evaluation"

    pa = agg[agg["item_type"] == "pair"].set_index("item_id")
    settled = pairs[pairs["pair_id"].map(lambda p: not pa.at[p, "needs_owner"])]
    y = pn.er_labels([pa.at[p, "panel_value"] for p in settled["pair_id"]])
    keep = [v is not None for v in y]
    pr = precision_recall([v for v, k in zip(y, keep) if k], [p for p, k in zip(settled["pipeline_same"], keep) if k])
    p_lo, p_hi = wilson_interval(pr["tp"], pr["tp"] + pr["fp"])
    r_lo, r_hi = wilson_interval(pr["tp"], pr["tp"] + pr["fn"])
    print(f"pipeline vs panel on {sum(keep)} settled pairs: tp {pr['tp']} fp {pr['fp']} fn {pr['fn']} | "
          f"precision {pr['precision']:.3f} ({p_lo:.2f}-{p_hi:.2f}) recall {pr['recall']:.3f} ({r_lo:.2f}-{r_hi:.2f})")
else:
    print("pairs not relabelled in this run: entity resolution is scored on the first run's final pair labels")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. `panel_labels.csv` for the adjudication page
# MAGIC
# MAGIC **What:** one row per item x field: panel value, disagreement flag and reason, the earlier automated label, the pipeline's decision (pairs), and the three votes. Rationales and the contract lines are included only for escalated rows, to keep the file small.
# MAGIC
# MAGIC **Why:** this file is all the adjudication page and the merge script need; the votes of settled rows stay visible for anyone checking the panel.

# COMMAND ----------

why = {(r["item_type"], r["item_id"], r["judge"], r["field"]): r["rationale"] for r in vote_rows}
pair_of = pairs.set_index("pair_id")
out_rows = []
for r in agg.to_dict("records"):                     # job order: pairs by pair_id, then briefs by review_id
    row = {"item_type": r["item_type"], "item_id": r["item_id"], "field": r["field"], "panel_value": r["panel_value"],
           "needs_owner": int(r["needs_owner"]), "reason": r["reason"], "earlier_label": r["earlier_label"],
           "n_listed": r["n_listed"], "pipeline_same": None, "contracts_a": "", "contracts_b": ""}
    if r["item_type"] == "pair":
        p = pair_of.loc[r["item_id"]]
        row["pipeline_same"] = int(p["pipeline_same"])
        if r["needs_owner"]:
            row["contracts_a"], row["contracts_b"] = p["contracts_a"], p["contracts_b"]
    for k, (j, v) in enumerate(zip(r["judges"], r["votes"]), 1):
        row[f"judge_{k}"], row[f"vote_{k}"] = SHORT[j], v
        row[f"why_{k}"] = why.get((r["item_type"], r["item_id"], j, r["field"]), "")[:200] if r["needs_owner"] else ""
    out_rows.append(row)
panel_csv = pd.DataFrame(out_rows)
panel_csv.to_csv(PANEL_CSV, index=False)
print(f"{PANEL_CSV}: {len(panel_csv)} rows, {os.path.getsize(PANEL_CSV) / 1024:.0f} KB, "
      f"{int(panel_csv['needs_owner'].sum())} to adjudicate")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Data quality checks
# MAGIC
# MAGIC **What:** one vote per item x judge x field and no duplicate keys, three judges per part, one CSV row per item x field with a value on every settled row, and the token spend under its cap.
# MAGIC
# MAGIC **Why:** a missing or duplicated vote would silently change a majority.

# COMMAND ----------

P = spark.table(PANEL_TABLE)
checks = [
    (PANEL_TABLE, "rows == items x judges x fields", n_panel, f"== {len(pairs) * 3 + len(briefs) * 3 * 4}"),
    (PANEL_TABLE, "duplicate keys", duplicate_keys(P, ["item_type", "item_id", "judge", "field"]), "== 0"),
    (PANEL_TABLE, "invalid votes (no valid answer)", P.filter(F.col("value").isNull()).count(), "info"),
    (PANEL_TABLE, "judges per item_type", P.groupBy("item_type").agg(F.countDistinct("judge").alias("n")).agg(F.min("n")).first()[0], "== 3"),
    ("panel_labels.csv", "rows == pairs + briefs x 4", len(panel_csv), f"== {len(pairs) + len(briefs) * 4}"),
    ("panel_labels.csv", "panel value missing on a settled row", int((panel_csv["panel_value"].isna() & (panel_csv["needs_owner"] == 0)).sum()), "== 0"),
    ("label spend", "DBU (estimate)", round(dbu_spent(), 2), f"<= {MAX_DBU}"),
]
dq = dq_report(checks)
display(dq)
assert (dq["status"] != "FAIL").all()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Results and limitations
# MAGIC
# MAGIC | Field | Items | Unanimous | Escalated | Pairwise agreement | Fleiss' kappa | Panel vs earlier automated labels (settled items) |
# MAGIC |---|---|---|---|---|---|---|
# MAGIC | pairs: same firm | 100 | 90 | 10 | 0.93 | 0.86 | 89 of 90 (the building agent's labels) |
# MAGIC | briefs: timeline_ok | 30 | 30 | 0 | 1.00 | 1.00 | 30 of 30 (p11 rule) |
# MAGIC | briefs: precedents relevant (0-5) | 30 | 26 | 1 | 0.91 (within one 0.98) | - | 25 of 29 (p11 single judge) |
# MAGIC | briefs: risks relevant (0-5) | 30 | 19 | 4 | 0.74 (within one 0.92) | - | no earlier score |
# MAGIC | briefs: any unsupported claim | 30 | 21 | 9 | 0.80 | 0.42 | 13 of 21 (p11 single judge) |
# MAGIC
# MAGIC - **Escalated to tier 3:** 10 pairs and 13 briefs (14 questions), out of 100 pairs and 30 briefs x 4 questions.
# MAGIC - **Entity resolution on the 90 pairs the panel settled:** the pipeline's decision at threshold 0.70 has precision 1.00 (95% CI 0.90-1.00) and recall 0.90 (0.76-0.96): 35 merged correctly, 0 wrongly, 4 missed. On the earlier labels of all 100 pairs it was 0.97 / 0.90. The final numbers, after tier 3, come from `apply_adjudication.py` (section 10).
# MAGIC - **Review pack on the settled fields:** the actual duration lies inside the brief's range in 20 of 30 briefs; 3.3 relevant precedents per brief that lists any (92% of listed precedents); 3.6 relevant risks per brief; an unsupported claim in 3 of 21 settled briefs.
# MAGIC
# MAGIC Limitations:
# MAGIC - Agreement is not accuracy. The panel can be unanimously wrong: pair 80 ("M/S MOMINUL HOQUE" / "MD MOMINUL HOQUE") is "same" for all three judges, while the earlier labeller separated them by district, which the contract lines do not show.
# MAGIC - The two Meta judges on panel B err together (Step 3), so a 2-1 majority there is weaker evidence than on panel A.
# MAGIC - Judges differ in strictness: Maverick calls names that share only generic words the same firm ("DATA TECHNOLOGIES" / "OBAIN TECHNOLOGIES"); Llama 3.3 sometimes calls a claim supported "because the brief says so". These show up as disagreements and escalate to tier 3.
# MAGIC - The review pack shows the cited records cut short (lesson passages of about 300 characters, contract records without the number of bidders), so some claims flagged as unsupported (for example "20 firms participated") may be supported by the fuller records the writer saw; tier 3 therefore checked those claims against the full award notices in the warehouse (section 10).
# MAGIC - Both rubrics were sharpened after seeing the panel's answers on these same items (Steps 3-5); a fresh sample would test them without that advantage.
# MAGIC - Fleiss' kappa is low for a rare answer even at high raw agreement (unsupported claims: 0.80 agreement, kappa 0.42), which is why both are shown.

# COMMAND ----------

summary = {"panel_rows": n_panel, "to_adjudicate": {t: int(g.groupby("item_id")["needs_owner"].any().sum()) for t, g in agg.groupby("item_type")},
           "agreement": stats_df[["item_type", "field", "pairwise_agreement", "fleiss_kappa"]].round(3).to_dict("records"),
           "calls": {SHORT[m]: c for m, (_, _, c) in LEDGER.items()}, "dbu": round(dbu_spent(), 2),
           "openrouter_calls": {SHORT[m]: c for m, (_, _, c, _) in OR_LEDGER.items()},
           "openrouter_usd": round(OR_STATE["usd"], 4), "openrouter_fallbacks": OR_STATE["fallbacks"]}
print(json.dumps(summary, default=str))

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 10. Tier 3: the escalated items, and the final labels
# MAGIC
# MAGIC **What:** the 24 escalated fields (10 pairs; 14 questions on 13 briefs) were decided after this run by an AI adjudicator agent with full access to the warehouse tables and the web. It read the three votes and rationales, went back to the sources (the names and contracts of a pair; the brief and its cited records), queried the warehouse where a claim was checkable (firm counts in award notices, project ids) and ran a web check on two firm names. Each decision is a row of `data/human_review/adjudication_decisions.csv` with its written evidence, and `data/human_review/adjudication_log.md` shows the votes, the queries and the web sources for every one. `apply_adjudication.py` merges the decisions with the settled panel labels into `data/human_review/final_labels.csv` (220 rows: 196 from the panel, 24 from tier 3).
# MAGIC
# MAGIC **Why:** a disagreement between three judges is the signal that an item needs evidence rather than another vote; the adjudicator answers it from the data and leaves a written trail a reviewer can check.
# MAGIC
# MAGIC | Result on the final labels | Value |
# MAGIC |---|---|
# MAGIC | Tier 3 decisions | 24: 7 panel majorities overturned (pairs 54, 68, 89; claims r05, r06; risk counts r19, r21), 15 confirmed, 2 settled where the judges had no majority (pair 87, the risk count of r12) |
# MAGIC | Real errors in the agent's briefs, confirmed from the data | 2: r06 describes a precedent as "same project", but it belongs to another project; r10's "2 to 6 firms in the same project" is wrong, the same-project contracts had 2 and 5 |
# MAGIC | Flagged claims cleared against award-notice firm counts | r03, r05, r07, r09, r18, r20 |
# MAGIC | Entity resolution at threshold 0.70 | 97 pairs decided, 3 "unsure" (two common personal names, one firm whose relation could not be established); precision 1.00 (95% CI 0.90-1.00), recall 0.90 (0.77-0.96): 36 merged correctly, 0 wrongly, 4 missed |
# MAGIC | Panel majority vs the earlier build labels | 96 of 100 pairs agree |
# MAGIC | Review pack, 30 briefs | actual duration inside the cited range 20/30; 22 briefs list precedents, 3.3 relevant on average, 90% of listed precedents relevant, 8 list none; 3.4 relevant risks per brief; an unsupported claim in 5/30 (17%) |
# MAGIC
# MAGIC Limitations: the adjudicator is an AI agent, so its decisions carry written evidence but have not been validated by procurement specialists; that validation is part of the pilot plan. Pairs that stay "unsure" are left out of precision and recall rather than forced.
