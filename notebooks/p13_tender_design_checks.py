# Databricks notebook source
# MAGIC %md
# MAGIC # p13_tender_design_checks — tender design and packaging checked against policy and past tenders
# MAGIC
# MAGIC Before an invitation for bids goes out, a procurement specialist asks: is the advertising period long enough, is the package sized for the market, are the bid security and qualification requirements in line with similar tenders? This notebook answers those questions from data: it reads the requirements printed in real IFB / RFB notices, builds peer statistics from past tenders, flags unusual designs, and checks against observed outcomes (number of bidders, time to signing, re-advertisement) whether a flag is worth raising.

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <pre class="mermaid">
# MAGIC ---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC ---
# MAGIC flowchart TD
# MAGIC     html["proc_bronze.procurement_notices.notice_text (HTML)"]
# MAGIC     rules["rules (proc_intel.tender_checks.extract_requirements)<br/>+ Qwen JSON extraction only where the rules found<br/>a mention without a value"]
# MAGIC     req["proc_silver.tender_requirements (400 notices)"]
# MAGIC     adv["advertising period, market approach<br/>(all 10,000+ notices)"]
# MAGIC     tt["proc_gold.tender_timelines (signed contracts, outcomes)"]
# MAGIC     outc["bidders named in award notices, days to signing,<br/>re-advertised reference, value per lot"]
# MAGIC     peers["peer statistics per country / region / category x market approach<br/>(proc_gold.tender_design_peers) + policy minimum (Regulations para 5.36)"]
# MAGIC     chk["check_tender_design(notice_or_package, peers): flags"]
# MAGIC     flags["proc_gold.tender_design_flags"]
# MAGIC     ev["flagged vs not flagged: bidders, single-bidder share,<br/>days to signing, re-advertisement"]
# MAGIC     html --> rules --> req --> peers
# MAGIC     adv --> peers
# MAGIC     tt --> outc --> peers
# MAGIC     peers --> chk --> flags --> ev
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
# MAGIC  proc_bronze.procurement_notices.notice_text (HTML)        proc_gold.tender_timelines (signed contracts, outcomes)
# MAGIC        |                                                          |
# MAGIC  rules (proc_intel.tender_checks.extract_requirements)    bidders named in award notices, days to signing,
# MAGIC  + Qwen JSON extraction only where the rules found         re-advertised reference, value per lot
# MAGIC    a mention without a value                                       |
# MAGIC        v                                                          v
# MAGIC  proc_silver.tender_requirements (400 notices)   +   advertising period, market approach (all 10,000+ notices)
# MAGIC                                    \                 /
# MAGIC                       peer statistics per country / region / category x market approach
# MAGIC                       (proc_gold.tender_design_peers)  +  policy minimum (Regulations para 5.36)
# MAGIC                                           v
# MAGIC              check_tender_design(notice_or_package, peers) -> flags  -->  proc_gold.tender_design_flags
# MAGIC                                           v
# MAGIC              flagged vs not flagged: bidders, single-bidder share, days to signing, re-advertisement
# MAGIC ```
# MAGIC
# MAGIC </details>
# MAGIC
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_silver.tender_requirements` | one sampled notice with the requirements read from its text and the source of each value | `notice_id` |
# MAGIC | `proc_gold.tender_design_peers` | one metric x peer group with P10-P90 | `metric, peer_group` |
# MAGIC | `proc_gold.tender_design_flags` | one flag raised on one notice | `notice_id, check` |
# MAGIC
# MAGIC **Interface for an agent tool: `check_tender_design(notice, peers) -> list[flag]`** in `src/proc_intel/tender_checks.py` (pure, tested in `tests/test_tender_checks.py`). `peers` is built from `proc_gold.tender_design_peers` with `load_peers()` (section 7).
# MAGIC
# MAGIC | Input key | Meaning |
# MAGIC |---|---|
# MAGIC | `category` | CW, GO or NC (required) |
# MAGIC | `market_approach` | `international` or `national` |
# MAGIC | `country`, `region` | ISO2 code, region name (for the most specific peer group) |
# MAGIC | `advertising_days` | days from publication to the bid deadline |
# MAGIC | `avg_lot_usd`, `n_lots` | estimated value per lot (US$) and number of lots |
# MAGIC | `bid_security_percent`, `bid_validity_days`, `turnover_multiple`, `experience_years`, `electronic_submission` | requirements, when known |
# MAGIC | `notice_id` | optional; cited as the flag's source |
# MAGIC
# MAGIC | Flag key | Meaning |
# MAGIC |---|---|
# MAGIC | `check` | e.g. `advertising_below_policy_minimum`, `advertising_short_vs_peers`, `package_large_vs_market`, `bid_security_high_vs_peers` |
# MAGIC | `severity` | `high` (policy), `medium` (unusual vs peers), `info` |
# MAGIC | `value`, `reference`, `rule` | the notice's value, the threshold it was compared with, the rule in words |
# MAGIC | `peer_group`, `source` | the peer group the threshold came from (`region/<name>/CW/national`), the notice id |

# COMMAND ----------

# MAGIC %md
# MAGIC ## How it was built and tested
# MAGIC
# MAGIC **Step 1 — What do notices actually state?**
# MAGIC - **Question:** can technical specifications and qualification criteria be read from the notices?
# MAGIC - **What we found:** IFB notices are short (median about 3,900 characters for English IFBs) and mostly point to the bidding document. In a 400-notice sample, about 75% mention bid security, 74% state national or international competition, but only about 7% print a turnover requirement and 3% a number of years of experience. Specifications and the full qualification criteria are in the bidding documents, which are not published as open data.
# MAGIC - **Decision:** check what the notices do carry (advertising period, market approach, package value, bid security, bid validity, electronic submission) and treat qualification thresholds as a small-sample check. The data gap is stated in `docs/data_gaps.md`.
# MAGIC
# MAGIC **Step 2 — Rules first, a model only for the leftovers**
# MAGIC - **Question:** rules or an LLM for the extraction?
# MAGIC - **What we found:** the formats repeat ("Bid Security of US$ 22,000", "2% of the bid price", "Bid-Securing Declaration", "valid for 90 days"), so rules read most fields. The first currency rule read any three capital letters before a number as a currency ("FOR 3,000", "LOT 2"); currency codes are now a whitelist matched case-sensitively. About 30% of notices name bid security without a readable value (tables flattened into text, amounts in words).
# MAGIC - **Decision:** rules for all 400; Qwen 3.5 (thinking off, strict JSON schema) only for notices where the rules found a mention without a value, plus a random 40 of the others to measure agreement between rules and model. A model value never overwrites a rule value.
# MAGIC
# MAGIC **Step 3 — Peers and policy**
# MAGIC - **Question:** what is "short" or "large"?
# MAGIC - **What we found:** the Procurement Regulations (7th edition, September 2025, para 5.36) set a minimum of 30 Business Days (about 42 calendar days) for open international competitive procurement; national competition follows national rules, so only peers can judge it.
# MAGIC - **Decision:** a policy check for international tenders, and peer checks everywhere: peers are notices of the same country (else region, else all) x category x market approach with at least 20 observations, over the cohort p07 also used (notices 2019-07-01 to 2024-10-13, fully observable).
# MAGIC
# MAGIC **Step 4 — Does a flag matter?**
# MAGIC - **Question:** which checks are associated with worse outcomes?
# MAGIC - **What we found:** outcomes are only observable for tenders that ended in a signed contract in the awards feed; cancelled tenders are invisible, and the bidder count is the number of firms named in the award notice.
# MAGIC - **Decision:** compare flagged and unflagged notices on these outcomes with bootstrap intervals, by check, and read them as associations (a large package is also a complex one), not effects.

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

# MAGIC %md
# MAGIC ## Settings
# MAGIC
# MAGIC **What:** sample size, cohort window, table names, the extraction model and its token cap.
# MAGIC
# MAGIC **Why:** the window equals p07's fully observable cohort, so outcomes are not biased by truncation of the awards feed at either end.

# COMMAND ----------

import collections
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from proc_intel import tender_checks as tc

SAMPLE_SIZE = 400
LLM_CHECK_SAMPLE = 40
WINDOW = ("2019-07-01", "2024-10-13")
CATEGORIES = ("CW", "GO", "NC")
LLM_MODEL = "databricks-qwen35-122b-a10b"
MAX_TEXT_CHARS = 6000
REQ_TABLE = f"{SILVER}.tender_requirements"
PEERS_TABLE = f"{GOLD}.tender_design_peers"
FLAGS_TABLE = f"{GOLD}.tender_design_flags"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The population: IFBs that led to signed, timed contracts
# MAGIC
# MAGIC **What:** English Invitations for Bids (works, goods, non-consulting services) published in the window that p05 linked as the tender notice of openly competed, timed contracts. Per notice: number of contracts (lots signed), the earliest days to signing, the mean number of firms named in the award notices, whether all its contracts had one named firm, whether a contract had a second tender notice (re-advertisement), and the value per lot. The advertising period comes from the notice's structured dates; the market approach is read from its text.
# MAGIC
# MAGIC **Why:** these are the tenders whose outcome we can observe, so every check can be related to an outcome. All English IFBs of the window (with or without a signed contract) are the peer pool for the advertising period.

# COMMAND ----------

approach_udf = as_udf(lambda html, method: tc.market_approach(tc.notice_text(html), method), "string")
texts = spark.table(f"{BRONZE}.procurement_notices").select(F.col("id").alias("notice_id"), "notice_text")
ifb = (spark.table(f"{SILVER}.notices")
       .filter(f"notice_type = 'Invitation for Bids' AND notice_language = 'English' AND notice_date BETWEEN '{WINDOW[0]}' AND '{WINDOW[1]}'")
       .filter(F.col("procurement_category_code").isin(*CATEGORIES))
       .withColumn("advertising_days", F.datediff("submission_deadline", "notice_date"))
       .withColumn("advertising_days", F.when(F.col("advertising_days").between(1, 365), F.col("advertising_days")))
       .join(texts, "notice_id")
       .withColumn("market_approach", approach_udf("notice_text", "procurement_method_name"))
       .join(spark.table(f"{SILVER}.dim_project").select("project_id", "region"), "project_id", "left")
       .select("notice_id", "project_id", "country_code", "region", F.col("procurement_category_code").alias("category"),
               "procurement_method_name", "notice_date", "advertising_days", "market_approach", "notice_text_chars")
       .cache())
tt = spark.table(f"{GOLD}.tender_timelines").filter("is_timed AND competition = 'open' AND tender_notice_type = 'Invitation for Bids'")
outcomes = (tt.groupBy(F.col("tender_notice_id").alias("notice_id"))
            .agg(F.count("*").alias("n_contracts"), F.min("days_notice_to_signing").alias("days_to_signing"),
                 F.avg("n_named_firms_in_award_notice").alias("bidders"),
                 F.min(F.when(F.col("n_named_firms_in_award_notice").isNotNull(),
                              (F.col("n_named_firms_in_award_notice") == 1).cast("int"))).alias("single_bidder"),
                 F.max((F.col("n_tender_notices") > 1).cast("int")).alias("readvertised"),
                 (F.sum("contract_amount_usd") / F.count("*")).alias("avg_lot_usd")))
pool = ifb.join(outcomes, "notice_id").cache()
print(f"English IFBs in the window: {ifb.count():,}; with a signed, timed contract: {pool.count():,}")
display(pool.groupBy("category", "market_approach").agg(
    F.count("*").alias("notices"), F.expr("percentile(advertising_days, 0.5)").alias("median_advertising_days"),
    F.round(F.avg("bidders"), 2).alias("mean_bidders"), F.round(F.avg("single_bidder"), 3).alias("single_bidder_share"),
    F.expr("percentile(days_to_signing, 0.5)").alias("median_days_to_signing")).orderBy("category", "market_approach"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Requirements read from 400 notices: rules
# MAGIC
# MAGIC **What:** 400 notices of the population in hash order of the notice id; `tc.extract_requirements()` on each notice's text.
# MAGIC
# MAGIC **Why:** a bounded sample keeps the hand checks and the model calls small; hash order is unrelated to the outcomes.

# COMMAND ----------

sample = (pool.orderBy(F.sha2("notice_id", 256)).limit(SAMPLE_SIZE).join(texts, "notice_id")
          .select("notice_id", "category", "country_code", "procurement_method_name", "notice_text").toPandas())
sample["text"] = sample.notice_text.map(tc.notice_text)
rules = pd.DataFrame([tc.extract_requirements(t, m) for t, m in zip(sample.text, sample.procurement_method_name)])
rules.insert(0, "notice_id", sample.notice_id)
FIELDS = [c for c in rules.columns if c != "notice_id"]
display(pd.DataFrame({"share of notices with a value (rules)": rules[FIELDS].notna().mean().round(3)}).reset_index())
display(rules.bid_security_kind.value_counts(dropna=False).rename_axis("bid_security_kind").reset_index())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Model extraction only where the rules stopped short, and a rules-vs-model check
# MAGIC
# MAGIC **What:** Qwen 3.5 (thinking off, strict JSON schema, temperature 0) reads the first 6,000 characters of
# MAGIC - every notice whose bid security the rules found mentioned but without a value, or that mentions turnover or experience without a parsed value ("fill" set), and
# MAGIC - 40 random other notices ("check" set),
# MAGIC
# MAGIC and returns the same fields. Model values fill only fields the rules left empty. On the check set, rules and model are compared field by field where both give a value.
# MAGIC
# MAGIC **Why:** the model handles the irregular layouts the rules cannot, but it is slower, costs tokens and can invent values; using it as a filler with a measured agreement keeps the rules as the auditable default.

# COMMAND ----------

_HOST = spark.conf.get("spark.databricks.workspaceUrl")
_TOKEN = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
USAGE, _lock = collections.Counter(), threading.Lock()


def _invoke(endpoint: str, body: dict, timeout: int = 180, max_retries: int = 8) -> dict:
    for attempt in range(max_retries):
        try:
            r = requests.post(f"https://{_HOST}/serving-endpoints/{endpoint}/invocations",
                              headers={"Authorization": f"Bearer {_TOKEN}"}, json=body, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            retry, err = r.status_code == 429 or r.status_code >= 500, f"HTTP {r.status_code}: {r.text[:300]}"
        except requests.exceptions.RequestException as e:
            retry, err = True, f"{type(e).__name__}: {str(e)[:200]}"
        if not retry or attempt == max_retries - 1:
            raise RuntimeError(f"{endpoint} failed: {err}")
        time.sleep(min(30, 0.5 * 2 ** attempt) + random.random() * 0.5)


_num = {"type": ["number", "null"]}
_str = {"type": ["string", "null"]}
SCHEMA = {"type": "json_schema", "json_schema": {"name": "tender_requirements", "strict": True, "schema": {
    "type": "object", "additionalProperties": False,
    "properties": {"market_approach": {"type": ["string", "null"], "enum": ["international", "national", None]},
                   "bid_security_kind": {"type": "string", "enum": ["percent", "amount", "declaration", "not_required", "not_stated"]},
                   "bid_security_percent": _num, "bid_security_amount": _num, "bid_security_currency": _str,
                   "n_lots": _num, "bid_validity_days": _num, "turnover_amount": _num, "turnover_currency": _str,
                   "experience_years": _num, "similar_contracts": _num},
    "required": ["market_approach", "bid_security_kind", "bid_security_percent", "bid_security_amount", "bid_security_currency",
                 "n_lots", "bid_validity_days", "turnover_amount", "turnover_currency", "experience_years", "similar_contracts"]}}}
SYSTEM = ("You extract tender requirements from one World Bank procurement notice (invitation for bids). Return only values the "
          "notice states; use null when it does not state one, never guess. market_approach: 'international' or 'national' "
          "competition as stated. bid_security_*: the bid security (bid guarantee) asked for; for several lots give the largest "
          "amount; currency as an ISO code (USD, KES, ...); a bid-securing declaration is kind 'declaration'. n_lots: number of "
          "lots. bid_validity_days: bid validity period. turnover_*: minimum average annual turnover required (largest if per lot). "
          "experience_years: minimum years of experience required. similar_contracts: minimum number of similar contracts.")


def llm_extract(text: str) -> dict:
    body = {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"<notice>\n{text[:MAX_TEXT_CHARS]}\n</notice>"}],
            "max_tokens": 400, "temperature": 0.0, "reasoning_effort": "none", "response_format": SCHEMA}
    resp = _invoke(LLM_MODEL, body)
    u = resp.get("usage") or {}
    with _lock:
        USAGE["prompt_tokens"] += u.get("prompt_tokens", 0)
        USAGE["completion_tokens"] += u.get("completion_tokens", 0)
        USAGE["calls"] += 1
    content = resp["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    out = json.loads(content)
    out["n_lots_stated"] = out.pop("n_lots")
    if out["bid_security_kind"] == "not_stated":
        out["bid_security_kind"] = None
    return out


mentions_qual = sample.text.str.contains(r"turnover|years of (?:general |specific )?experience", case=False, regex=True)
fill_mask = (rules.bid_security_kind == "mentioned") | (mentions_qual & rules.turnover_amount.isna() & rules.experience_years.isna())
others = rules.index[~fill_mask].tolist()
check_idx = sorted(random.Random(13).sample(others, min(LLM_CHECK_SAMPLE, len(others))))
llm_idx = sorted(set(rules.index[fill_mask]) | set(check_idx))
t0 = time.time()
with ThreadPoolExecutor(max_workers=3) as pool_exec:
    llm_out = dict(zip(llm_idx, pool_exec.map(lambda i: llm_extract(sample.text[i]), llm_idx)))
print(f"model calls: {len(llm_idx)} (fill {int(fill_mask.sum())}, check {len(check_idx)}) in {time.time() - t0:.0f} s; "
      f"tokens {USAGE['prompt_tokens']:,} in / {USAGE['completion_tokens']:,} out")

# COMMAND ----------

def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 0.01 * max(abs(a), abs(b), 1)
    return str(a).strip().upper() == str(b).strip().upper()


agree = []
for f in ["market_approach", "bid_security_kind", "bid_security_percent", "bid_security_amount", "n_lots_stated",
          "bid_validity_days", "turnover_amount", "experience_years"]:
    both = [(rules.at[i, f], llm_out[i].get(f)) for i in check_idx
            if pd.notna(rules.at[i, f]) and llm_out[i].get(f) is not None]
    rules_only = sum(1 for i in check_idx if pd.notna(rules.at[i, f]) and llm_out[i].get(f) is None)
    model_only = sum(1 for i in check_idx if pd.isna(rules.at[i, f]) and llm_out[i].get(f) is not None)
    agree.append({"field": f, "both_have_value": len(both), "agree": sum(same(a, b) for a, b in both),
                  "rules_only": rules_only, "model_only": model_only})
print(f"rules vs model on the {len(check_idx)} check notices:")
display(pd.DataFrame(agree))

merged = rules.copy()
source = pd.DataFrame("rules", index=rules.index, columns=FIELDS).where(rules[FIELDS].notna(), None)
for i in llm_idx:
    if i in check_idx:
        continue                               # the check set measures agreement; its values stay rule values
    for f in FIELDS:
        v = llm_out[i].get(f)
        if pd.isna(merged.at[i, f]) and v is not None or (f == "bid_security_kind" and merged.at[i, f] == "mentioned" and v):
            merged.at[i, f] = v
            source.at[i, f] = "model"
display(pd.DataFrame({"with a value after fill": merged[FIELDS].notna().mean().round(3),
                      "from the model": (source == "model").mean().round(3)}).reset_index())

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** `proc_silver.tender_requirements`: the merged fields per sampled notice, ratios to the awarded value where the currency allows (bid security and turnover in US$ divided by the largest awarded contract in US$), and a JSON map of each field's source (rules / model).
# MAGIC
# MAGIC **Why:** a percentage of contract value is comparable across countries; local-currency amounts would need exchange rates per notice date, which this prototype does not load, so they are kept but not compared.

# COMMAND ----------

amounts = (tt.groupBy(F.col("tender_notice_id").alias("notice_id")).agg(F.max("contract_amount_usd").alias("max_contract_usd"))
           .toPandas().set_index("notice_id").max_contract_usd)
merged["max_contract_usd"] = merged.notice_id.map(amounts)
usd = merged.bid_security_currency.eq("USD") & merged.bid_security_amount.notna()
merged["bid_security_pct_of_award"] = np.where(merged.bid_security_kind.eq("percent"), merged.bid_security_percent,
                                               np.where(usd, 100 * merged.bid_security_amount / merged.max_contract_usd, np.nan))
merged.loc[~merged.bid_security_pct_of_award.between(0.05, 10), "bid_security_pct_of_award"] = np.nan   # parsing errors
merged["turnover_multiple"] = np.where(merged.turnover_currency.eq("USD"), merged.turnover_amount / merged.max_contract_usd, np.nan)
merged.loc[~merged.turnover_multiple.between(0.1, 20), "turnover_multiple"] = np.nan
merged["field_sources"] = [json.dumps({f: s for f, s in row.items() if s}) for row in source.to_dict("records")]
merged["electronic_submission"] = merged.electronic_submission.map(lambda v: None if v is None or pd.isna(v) else bool(v))
req_cols = ["notice_id"] + FIELDS + ["max_contract_usd", "bid_security_pct_of_award", "turnover_multiple", "field_sources"]
req_schema = ("notice_id string, market_approach string, bid_security_kind string, bid_security_percent double, "
              "bid_security_amount double, bid_security_currency string, n_lots_stated double, bid_validity_days double, "
              "electronic_submission boolean, pre_bid_meeting string, turnover_amount double, turnover_currency string, "
              "experience_years double, similar_contracts double, max_contract_usd double, bid_security_pct_of_award double, "
              "turnover_multiple double, field_sources string")
req_records = [[None if (not isinstance(v, (str, bool, dict, list)) and pd.isna(v)) else
                (float(v) if isinstance(v, (int, float, np.floating, np.integer)) and not isinstance(v, bool) else v)
                for v in row] for row in merged[req_cols].itertuples(index=False)]
n_req = publish_table(
    spark.createDataFrame(req_records, req_schema), REQ_TABLE,
    "Tender requirements read from 400 sampled IFB notices (p13): rules first, Qwen JSON extraction only for fields the "
    "rules left empty. Grain: one notice.",
    {"notice_id": "PK, FK notices", "market_approach": "international or national, as stated",
     "bid_security_kind": "percent, amount, declaration, not_required, mentioned (no value read) or null",
     "bid_security_percent": "Bid security as % of the bid price, if stated", "bid_security_amount": "Largest bid security amount",
     "bid_security_currency": "Its currency", "n_lots_stated": "Lots named in the notice", "bid_validity_days": "Bid validity",
     "electronic_submission": "True: electronic submission allowed/required; False: excluded; null: not stated",
     "pre_bid_meeting": "mandatory, held or null", "turnover_amount": "Minimum annual turnover required (largest)",
     "turnover_currency": "Its currency", "experience_years": "Minimum years of experience", "similar_contracts": "Minimum similar contracts",
     "max_contract_usd": "Largest awarded contract of the notice (US$)",
     "bid_security_pct_of_award": "Bid security % (stated, or US$ amount / largest awarded contract)",
     "turnover_multiple": "Required turnover (US$) / largest awarded contract", "field_sources": "JSON: field -> rules or model"},
    primary_key=["notice_id"])
add_foreign_key(REQ_TABLE, ["notice_id"], f"{SILVER}.notices", ["notice_id"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Peer statistics: `proc_gold.tender_design_peers`
# MAGIC
# MAGIC **What:** P10-P90 per peer group for
# MAGIC - `advertising_days`: all English IFBs of the window (country / region / category x market approach),
# MAGIC - `lot_size_usd`: every openly competed contract in the awards feed (country / region / category; the market approach is not known for contracts, so the key uses `any`),
# MAGIC - `bid_security_percent`, `bid_validity_days`, `turnover_multiple`, `experience_years`: the 400-notice sample (category only, too few for finer groups).
# MAGIC
# MAGIC **Why:** one small table is what an agent tool needs at run time; `load_peers()` turns it into the dict `check_tender_design()` expects.

# COMMAND ----------

def stats_rows(pdf: pd.DataFrame, metric: str, value_col: str, levels: list[list[str]]) -> list[dict]:
    out = []
    for cols in levels:
        for key, g in pdf.dropna(subset=[value_col] + [c for c in cols if c not in ("_lvl",)]).groupby(cols):
            key = key if isinstance(key, tuple) else (key,)
            s = tc.peer_stats(g[value_col].tolist())
            out.append({"metric": metric, "peer_group": "/".join(str(k) for k in key), "n": s["n"],
                        **{k: s[k] for k in ("p10", "p25", "p50", "p75", "p90")}})
    return out


adv = ifb.select("country_code", "region", "category", "market_approach", "advertising_days").toPandas()
adv["market_approach"] = adv.market_approach.fillna("unknown")
adv["lvl_country"], adv["lvl_region"], adv["lvl_category"] = "country", "region", "category"
lots = (spark.table(f"{GOLD}.tender_timelines").filter("competition = 'open' AND contract_amount_usd > 0")
        .filter(F.col("procurement_category_code").isin(*CATEGORIES))
        .select(F.col("borrower_country_code").alias("country_code"), "region", F.col("procurement_category_code").alias("category"),
                F.col("contract_amount_usd").alias("lot_size_usd")).toPandas())
lots["market_approach"] = "any"
lots["lvl_country"], lots["lvl_region"], lots["lvl_category"] = "country", "region", "category"
smp = merged.merge(sample[["notice_id", "category"]], on="notice_id")
smp["lvl_category"], smp["any"] = "category", "any"
smp = smp.rename(columns={"bid_security_pct_of_award": "bid_security_percent_v"})
peer_rows = (stats_rows(adv, "advertising_days", "advertising_days",
                        [["lvl_country", "country_code", "category", "market_approach"],
                         ["lvl_region", "region", "category", "market_approach"], ["lvl_category", "category", "market_approach"]])
             + stats_rows(lots, "lot_size_usd", "lot_size_usd",
                          [["lvl_country", "country_code", "category", "market_approach"],
                           ["lvl_region", "region", "category", "market_approach"], ["lvl_category", "category", "market_approach"]]))
for metric, col in [("bid_security_percent", "bid_security_percent_v"), ("bid_validity_days", "bid_validity_days"),
                    ("turnover_multiple", "turnover_multiple"), ("experience_years", "experience_years")]:
    peer_rows += stats_rows(smp, metric, col, [["lvl_category", "category", "any"]])
peers_df = pd.DataFrame(peer_rows)
n_peers = publish_table(
    spark.createDataFrame(peers_df), PEERS_TABLE,
    "Peer statistics for tender design checks (p13). Grain: one metric x peer group (country|region|category/.../category/approach).",
    {"metric": "PK. advertising_days, lot_size_usd, bid_security_percent, bid_validity_days, turnover_multiple, experience_years",
     "peer_group": "PK. level/key/category/market approach, e.g. region/Eastern and Southern Africa/CW/national",
     "n": "Observations", "p10": "10th percentile", "p25": "25th percentile", "p50": "Median", "p75": "75th percentile",
     "p90": "90th percentile"},
    primary_key=["metric", "peer_group"])


def load_peers(table: str = PEERS_TABLE) -> dict:
    """{metric: {group key tuple: stats}} as check_tender_design() expects."""
    out: dict = {}
    for r in spark.table(table).collect():
        parts = r.peer_group.split("/")
        out.setdefault(r.metric, {})[tuple(parts)] = r.asDict()
    return out


PEERS = load_peers()
display(peers_df[peers_df.peer_group.str.startswith("category/")].round(2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Flags for every notice of the population: `proc_gold.tender_design_flags`
# MAGIC
# MAGIC **What:** `check_tender_design()` on each of the population's notices with what is known for it: advertising period, market approach, value per lot and number of lots for all; the text-derived requirements for the 400 sampled notices.
# MAGIC
# MAGIC **Why:** the same pure function an agent tool would call, run over history, so its flags can be counted and related to outcomes.

# COMMAND ----------

pop = pool.select("notice_id", "country_code", "region", "category", "market_approach", "advertising_days", "avg_lot_usd",
                  "n_contracts", "notice_date", "bidders", "single_bidder", "days_to_signing", "readvertised").toPandas()
req_by_id = merged.set_index("notice_id")
flag_rows = []
for r in pop.itertuples():
    notice = {"notice_id": r.notice_id, "category": r.category, "market_approach": r.market_approach, "country": r.country_code,
              "region": r.region, "advertising_days": None if pd.isna(r.advertising_days) else int(r.advertising_days),
              "avg_lot_usd": r.avg_lot_usd, "n_lots": int(r.n_contracts)}
    if r.notice_id in req_by_id.index:
        q = req_by_id.loc[r.notice_id]
        notice.update({k: (None if pd.isna(q[c]) else q[c]) for k, c in
                       [("bid_security_percent", "bid_security_pct_of_award"), ("bid_validity_days", "bid_validity_days"),
                        ("turnover_multiple", "turnover_multiple"), ("experience_years", "experience_years"),
                        ("electronic_submission", "electronic_submission")]})
    for f in tc.check_tender_design(notice, PEERS):
        flag_rows.append({**f, "notice_id": r.notice_id, "value": str(f["value"]), "reference": str(f["reference"]),
                          "category": r.category, "country_code": r.country_code, "notice_date": r.notice_date,
                          "in_text_sample": r.notice_id in req_by_id.index})
flags_df = pd.DataFrame(flag_rows)
n_flags = publish_table(
    spark.createDataFrame(flags_df[["notice_id", "check", "severity", "value", "reference", "rule", "peer_group", "source",
                                    "category", "country_code", "notice_date", "in_text_sample"]]), FLAGS_TABLE,
    "Tender design flags (p13) from proc_intel.tender_checks.check_tender_design() over English IFBs 2019-07..2024-10 with a "
    "signed, timed contract. Grain: one flag on one notice.",
    {"notice_id": "PK, FK notices", "check": "PK. Name of the check", "severity": "high (policy), medium (vs peers), info",
     "value": "The notice's value", "reference": "Threshold it was compared with", "rule": "Rule in words (policy source for policy checks)",
     "peer_group": "Peer group of the threshold", "source": "Cited record (notice id)", "category": "CW, GO or NC",
     "country_code": "Borrower country", "notice_date": "Publication date", "in_text_sample": "Notice is one of the 400 read in full"},
    primary_key=["notice_id", "check"])
add_foreign_key(FLAGS_TABLE, ["notice_id"], f"{SILVER}.notices", ["notice_id"])
FL = spark.table(FLAGS_TABLE)
display(dq_report([
    (REQ_TABLE, "notices read", n_req, f"== {SAMPLE_SIZE}"),
    (PEERS_TABLE, "peer groups", n_peers, "info"),
    (FLAGS_TABLE, "flags", n_flags, "info"),
    (FLAGS_TABLE, "duplicate keys", duplicate_keys(FL, ["notice_id", "check"]), "== 0"),
    (FLAGS_TABLE, "orphan notice_id", orphan_count(FL, "notice_id", spark.table(f"{SILVER}.notices"), "notice_id"), "== 0"),
]))
display(FL.groupBy("check", "severity").agg(F.count("*").alias("flags"), F.countDistinct("notice_id").alias("notices")).orderBy(F.desc("flags")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Which checks matter? Flagged vs not flagged notices
# MAGIC
# MAGIC **What:** for each check, among the notices where it could be evaluated (the input exists and a peer group was found), the mean number of firms named in the award notices, the share of single-bidder tenders, the median days to signing and the re-advertisement share, flagged vs not flagged, with a bootstrap 95% interval for the difference in mean bidders. The policy check is also shown within international tenders only.
# MAGIC
# MAGIC **Why:** a check that is not associated with fewer bidders or slower signing is noise to a user. These are associations on signed tenders only (cancelled tenders are invisible, and big packages are also complex ones), so they rank checks, they do not prove effects.

# COMMAND ----------

def evaluable(check: str) -> pd.Series:
    """Notices where the check's input exists (peer availability is approximated by the input)."""
    if check.startswith("advertising_below"):
        return pop.advertising_days.notna() & pop.market_approach.eq("international")
    if check.startswith("advertising"):
        return pop.advertising_days.notna()
    if check.startswith("package"):
        return pop.avg_lot_usd.notna()
    col = {"bid_security_high_vs_peers": "bid_security_pct_of_award", "bid_validity_long_vs_peers": "bid_validity_days",
           "turnover_requirement_high_vs_peers": "turnover_multiple", "experience_requirement_high_vs_peers": "experience_years",
           "no_electronic_submission_international": "electronic_submission"}[check]
    ok = set(merged.loc[merged[col].notna(), "notice_id"])
    return pop.notice_id.isin(ok)


rng = np.random.default_rng(3)
flagged_by_check = flags_df.groupby("check").notice_id.apply(set)
out = []
for check, ids in flagged_by_check.items():
    base = pop[evaluable(check)]
    f, nf = base[base.notice_id.isin(ids)], base[~base.notice_id.isin(ids)]
    if len(f) < 5 or len(nf) < 5:
        continue
    fb, nb = f.bidders.dropna().to_numpy(), nf.bidders.dropna().to_numpy()
    boot = [rng.choice(fb, len(fb)).mean() - rng.choice(nb, len(nb)).mean() for _ in range(1000)] if len(fb) and len(nb) else [np.nan]
    out.append({"check": check, "evaluable": len(base), "flagged": len(f),
                "bidders flagged / not": f"{fb.mean():.2f} / {nb.mean():.2f}",
                "difference (95% CI)": f"{fb.mean() - nb.mean():+.2f} ({np.nanpercentile(boot, 2.5):+.2f} to {np.nanpercentile(boot, 97.5):+.2f})",
                "single bidder flagged / not": f"{f.single_bidder.mean():.1%} / {nf.single_bidder.mean():.1%}",
                "median days to signing flagged / not": f"{f.days_to_signing.median():.0f} / {nf.days_to_signing.median():.0f}",
                "re-advertised flagged / not": f"{f.readvertised.mean():.1%} / {nf.readvertised.mean():.1%}"})
impact = pd.DataFrame(out)
display(impact)

# COMMAND ----------

# MAGIC %md
# MAGIC **What:** the advertising-period association within each category and market approach (the strongest confounders: works tenders are both longer and better contested).
# MAGIC
# MAGIC **Why:** if the gap holds within strata, it is not just the category mix.

# COMMAND ----------

short_ids = flagged_by_check.get("advertising_short_vs_peers", set())
strata = []
for (cat, appr), g in pop[pop.advertising_days.notna()].groupby(["category", pop.market_approach.fillna("unknown")]):
    f, nf = g[g.notice_id.isin(short_ids)], g[~g.notice_id.isin(short_ids)]
    if len(f) >= 10:
        strata.append({"category": cat, "market_approach": appr, "notices": len(g), "short": len(f),
                       "bidders short / other": f"{f.bidders.mean():.2f} / {nf.bidders.mean():.2f}",
                       "single bidder short / other": f"{f.single_bidder.mean():.1%} / {nf.single_bidder.mean():.1%}",
                       "median days short / other": f"{f.days_to_signing.median():.0f} / {nf.days_to_signing.median():.0f}"})
display(pd.DataFrame(strata))

# COMMAND ----------

# MAGIC %md
# MAGIC **What the numbers say (run of 2026-10-21; 8,146 English IFBs with a signed, timed contract, 400 read in full).**
# MAGIC - **What notices state:** after rules and model, 74% state the market approach, 73% describe the bid security (54% with an amount or a percentage), 64% say whether electronic submission is possible, 17% the bid validity, and only 10% a turnover requirement and 5% years of experience. Rules and model agree on 23 of 24 market approaches, 20 of 20 bid-security kinds and 13 of 13 amounts on the 40 check notices; the model adds values mainly for amounts printed in tables and for lot counts.
# MAGIC - **Advertising below the policy minimum** (international tenders, < 42 calendar days): 672 of 1,939 (35%). Some of these are artefacts: the notice date here is the date of publication on the World Bank site, which can be later than the first publication, and 30 business days can be 40-41 calendar days; but 555 of the 672 were advertised for under 40 days (median 30.5). Flagged tenders drew fewer bidders (4.9 vs 5.6, difference -0.67, interval -1.18 to -0.18) and more single-bidder outcomes (28.5% vs 20.3%), the clearest association of all checks.
# MAGIC - **Advertising short vs peers** (< 60% of the peer median): 958 notices; no difference in mean bidders overall, but more single-bidder outcomes (27.4% vs 23.0%), and within national works the gap holds (4.5 vs 5.2 bidders, 21.8% vs 17.7% single bidder). Short tenders sign sooner: they are also smaller.
# MAGIC - **Large package vs the market** (value per lot above the P90 of past contracts in the country): 1,494 notices; these draw **more** bidders (5.8 vs 4.4) and take much longer to sign (median 196 vs 115 days). So package size is a schedule-risk signal, not a competition-risk signal, and the check's wording in an agent brief should say so.
# MAGIC - **Requirement checks** (bid security, bid validity, turnover) can only be evaluated on the 400 notices and flag 1-8 notices each; bid security above the peer P90 goes with fewer bidders (3.4 vs 4.7 on 8 notices), which is suggestive at best. Re-advertisement is too rare (1-3%) to separate any check.
# MAGIC - **Which checks matter:** the advertising-period checks (policy and peer) for competition, package size for duration. The requirement checks need bidding documents, not notices, to be useful.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. The agent-tool interface on a planned package
# MAGIC
# MAGIC **What:** `check_tender_design()` for two planned packages that are not in the data: a national works tender in Kenya advertised for 21 days as one US$ 30 million lot, and an international goods tender advertised for 30 days with a 5% bid security and no electronic submission.
# MAGIC
# MAGIC **Why:** shows the output an agent (or a task team's checklist) would receive, with the thresholds and peer groups it can cite.

# COMMAND ----------

planned = [
    {"notice_id": "planned-1", "category": "CW", "market_approach": "national", "country": "KE", "region": "Eastern and Southern Africa",
     "advertising_days": 21, "avg_lot_usd": 30e6, "n_lots": 1},
    {"notice_id": "planned-2", "category": "GO", "market_approach": "international", "country": "BD", "region": "South Asia",
     "advertising_days": 30, "avg_lot_usd": 2e6, "n_lots": 3, "bid_security_percent": 5, "electronic_submission": False},
]
for p in planned:
    print(p["notice_id"])
    for f in tc.check_tender_design(p, PEERS):
        print("  ", json.dumps(f))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC **What:** the headline numbers as the notebook's exit value.
# MAGIC
# MAGIC **Why:** a job run shows them without opening the notebook.

# COMMAND ----------

summary = {"population_notices": len(pop), "sample_notices": n_req, "model_calls": USAGE["calls"],
           "model_tokens_in": USAGE["prompt_tokens"], "model_tokens_out": USAGE["completion_tokens"],
           "peer_groups": n_peers, "flags": n_flags, "flags_by_check": flags_df.check.value_counts().to_dict()}
print(summary)

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary, default=str))
