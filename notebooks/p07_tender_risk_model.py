# Databricks notebook source
# MAGIC %md
# MAGIC # p07_tender_risk_model — how long will a tender take, and will it run late?
# MAGIC
# MAGIC Module 2 of the brief (timeline benchmarking and risk scoring). For an openly competed tender, predict the days from the tender notice to the signed contract as a **range** (P10 / P50 / P90), and the probability that it is **slow** for its kind of procurement. Every input is known on the day the notice is published.

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <pre class="mermaid">
# MAGIC ---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC ---
# MAGIC flowchart TD
# MAGIC     tt["proc_gold.tender_timelines (open, timed)<br/>notice date to signing date"]
# MAGIC     subgraph feats["notice-time features"]
# MAGIC         f1["notice: method, category, type,<br/>advertising days, language, length"]
# MAGIC         f2["project: region, sector, age, size, earlier tenders"]
# MAGIC         f3["country: governance (WGI) and income,<br/>year before the notice"]
# MAGIC         f4["market: past contracts, winners, bidders,<br/>durations (3 years before)"]
# MAGIC     end
# MAGIC     cohort["cohort with full follow-up<br/>notices 2019-07 .. 2024-10, durations capped at 730 days"]
# MAGIC     base["peer-group baseline<br/>quantiles of country x method x category, with fallbacks"]
# MAGIC     lgbm["LightGBM quantile models P10 / P50 / P90<br/>+ slow-tender classifier<br/>(time split, rolling-origin CV)"]
# MAGIC     surv["survival view<br/>Kaplan-Meier per notice (unsigned = censored), Weibull AFT"]
# MAGIC     subgraph outs["outputs"]
# MAGIC         o1["proc_gold.tender_benchmarks<br/>(peer groups)"]
# MAGIC         o2["proc_gold.open_tender_scores<br/>(open notices)"]
# MAGIC         o3["UC model ml.proc_tender_duration"]
# MAGIC     end
# MAGIC     tt --> cohort
# MAGIC     feats --> cohort
# MAGIC     cohort --> base
# MAGIC     cohort --> lgbm
# MAGIC     cohort --> surv
# MAGIC     base --> outs
# MAGIC     lgbm --> outs
# MAGIC     surv --> outs
# MAGIC </pre>
# MAGIC <script type="module">
# MAGIC   import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.esm.min.mjs";
# MAGIC   import elkLayouts from "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.1.7/dist/mermaid-layout-elk.esm.min.mjs";
# MAGIC   mermaid.registerLayoutLoaders(elkLayouts);
# MAGIC   mermaid.initialize({ startOnLoad: true });
# MAGIC </script>

# COMMAND ----------

# MAGIC %md
# MAGIC ### Output tables (the interface for the agent's tools)
# MAGIC
# MAGIC `proc_gold.tender_benchmarks` — one row per peer group. Read it with `proc_intel.risk.benchmark_lookup(rows, country, method, category)`, which returns the finest group with at least 30 contracts and says which level it used.
# MAGIC
# MAGIC | Column | Type | Meaning |
# MAGIC |---|---|---|
# MAGIC | `benchmark_key` | string, PK | `level|country|region|method|category` (`ALL` where the level does not use the column; country rows keep their region) |
# MAGIC | `benchmark_level` | string | `country_method_category`, `region_method_category`, `method_category` or `category` |
# MAGIC | `country_code`, `region`, `procurement_method_name`, `procurement_category_code` | string | the peer group (`ALL` = any) |
# MAGIC | `n_contracts` | int | contracts in the group (notices 2019-07-01 .. 2024-10-13) |
# MAGIC | `p10_days`, `p50_days`, `p90_days` | int | notice -> signing days, capped at 730 |
# MAGIC | `slow_threshold_days` | int | the method x category P75 of the training years; above it a tender counts as slow |
# MAGIC | `slow_rate` | double | share of the group's contracts above that threshold |
# MAGIC | `window_start`, `window_end` | date | notice dates covered |
# MAGIC | `built_at` | timestamp | build time |
# MAGIC
# MAGIC `proc_gold.open_tender_scores` — one row per open tender notice (published in the last 730 days, openly competed method, no contract linked yet).
# MAGIC
# MAGIC | Column | Type | Meaning |
# MAGIC |---|---|---|
# MAGIC | `notice_id` | string, PK | FK `proc_silver.notices` |
# MAGIC | `project_id`, `country_code`, `region`, `procurement_method_name`, `procurement_category_code`, `notice_type` | string | the tender |
# MAGIC | `notice_date`, `submission_deadline` | date | from the notice |
# MAGIC | `days_elapsed` | int | snapshot date minus notice date |
# MAGIC | `p10_days`, `p50_days`, `p90_days` | int | model range for notice -> signing |
# MAGIC | `expected_signing_date` | date | notice date + `p50_days` |
# MAGIC | `slow_probability` | double | model probability of exceeding `slow_threshold_days` |
# MAGIC | `slow_threshold_days` | int | as in `tender_benchmarks` |
# MAGIC | `peer_p50_days`, `peer_level` | int, string | the benchmark the model is compared with |
# MAGIC | `past_p90` | boolean | already open longer than the model's P90 |
# MAGIC | `model_version`, `scored_at` | string, timestamp | provenance |
# MAGIC
# MAGIC No language model is used in this notebook.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key design decisions
# MAGIC
# MAGIC | Decision | Rationale | Evidence |
# MAGIC |---|---|---|
# MAGIC | Model notices from 2019-07-01 to 730 days before the snapshot, duration capped at 730 days; newer notices are scored, not trained on, and handled as censored in the survival view (section 9) | The awards feed holds contracts signed from 2019-07-01 to the snapshot, so edge cohorts are biased; within the window every duration up to the cap is observable | Median notice -> signing time by notice year: 465 days (2018), 154-189 (2019-2024), 135 (2025), 95 (2026); 1.5% took longer than 730 days |
# MAGIC | Risk target = slow: duration above the P75 of the same method x category in the training years; re-advertisement rates reported, not modelled | Re-advertisement is rare and mostly invisible in the data | 1.3% of training contracts (1.5% of test) have more than one tender notice linked; only 135 of 81,600 (project, reference) pairs repeat exactly; only 10 IFB notices carry a "Revised" status; base rate 25.0% in training, 22.4% in the test notices |
# MAGIC | Contract amount, review type and the outcome-model risk score excluded; governance indicators for the year before the notice; market history for the 36 months before the notice month | Features must be known on the notice date | The amount is known only at award (no pre-award estimate); review type is not on the notice; the outcome-model score exists only for projects still active in 2026 |
# MAGIC | Interval calibrated with conformalised quantile regression on the last training half-year; model registered as `@champion` | The model beats the peer-group lookup, but its raw interval under-covers | Pinball loss of the median 38.1-42.1 vs 44.5-49.2 on all four rolling-origin folds; test MAE 76 vs 88 days, mean pinball 24.6 vs 29.1; raw P10-P90 coverage 68% (16% below, 15% above); after calibration (lower bound -0.136, upper +0.112 log-days, about 13% and 12% in days) 80.7% (9.8% below, 9.5% above), interval still 12% narrower than the peer table's |
# MAGIC | Publish the slow-tender probability with the threshold it refers to | The classifier ranks tenders better than the peer group's historical slow rate | ROC-AUC 0.747 vs 0.584, PR-AUC 0.494 vs 0.295 (base rate 0.224) |
# MAGIC | Kaplan-Meier used to compare timing across groups and cohorts, not to estimate how many tenders fail; Weibull AFT for readable time ratios | Censoring is valid for young notices; for old notices, cancellations and link failures look the same | KM share signed within 180 days 0.30-0.38 for every notice year 2019-2025, while naive medians fall to 144 days (2025) and 91 (2026); curves flatten at 0.56-0.67 (the share p05 links); KM medians among linked notices: consulting 319 days, works 132, goods 127, non-consulting 125; AFT: Request for Bids 0.42x the other open methods, Latin America 1.28x vs Europe and Central Asia, +1.2% per advertising day; test concordance 0.694 vs LightGBM's 0.721 |
# MAGIC
# MAGIC Limitations: predicted slow probabilities run slightly high in the lower deciles (consistent with the lower test base rate); recalibrating on recent data is the first maintenance task.
# MAGIC
# MAGIC Full reasoning: docs/decision_log.md

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC
# MAGIC **What:** libraries (`lifelines` for the survival models), shared helpers, the time windows and the MLflow names.
# MAGIC
# MAGIC **Why:** the windows are the core design decision (section 1 shows why): the awards feed only contains contracts signed from 2019-07-01 to the snapshot, so a notice is only fully observable if it falls after the feed starts and at least 730 days before the snapshot.

# COMMAND ----------

# MAGIC %pip install -q lifelines

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

import json
from datetime import timedelta

import lightgbm as lgb
import matplotlib.pyplot as plt
import mlflow
import numpy as np
from mlflow.models import infer_signature
from pyspark.sql import Window
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from proc_intel.risk import (ALL, HORIZON_DAYS, LEVELS, MIN_PEER_N, QUANTILES, benchmark_key, benchmark_lookup,
                             calibration_table, cap_at_horizon, conformal_shift, interval_coverage, peer_aggregate, peer_baseline,
                             pinball_loss, rolling_origin_folds, slow_label, sort_quantiles)

# the data's own last date, not today's date, so a re-run on an old snapshot gives the same windows
SNAPSHOT = spark.table(f"{SILVER}.contracts").agg(F.max("signing_date")).first()[0]   # last signing in the feed
WINDOW_START = date(2019, 7, 1)                                # first signing date in the awards feed
WINDOW_END = SNAPSHOT - timedelta(days=HORIZON_DAYS)           # notices after this are not yet fully observable
TEST_START = date(2023, 7, 1)                                  # train on older notices, test on the newest
# all four origins fall before TEST_START, so tuning never looks at the test notices
CV_ORIGINS = ["2021-07-01", "2022-01-01", "2022-07-01", "2023-01-01"]   # rolling origin, 6-month validation
CAL_START = date(2023, 1, 1)                                   # last training half-year calibrates the interval
TENDER_TYPES = ["Invitation for Bids", "Request for Expression of Interest", "Invitation for Prequalification"]
EXPERIMENT = "/Users/shabadvaswani2002@outlook.com/wb-procurement/proc_risk_experiment"
MODEL_NAME = f"{CATALOG}.ml.proc_tender_duration"
THREADS = 2          # the cluster is shared
SEED = 7
print(f"snapshot {SNAPSHOT} | cohort notices {WINDOW_START} .. {WINDOW_END} | test from {TEST_START}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Why a cohort window: the feed truncates both ends
# MAGIC
# MAGIC **What:** duration quantiles of openly competed, timed contracts by the year of their tender notice.
# MAGIC
# MAGIC **Why:** a contract enters the data only when it is signed inside the feed's window. Notices from 2018 appear only if they took long enough to be signed after 2019-07-01 (biased slow); notices from 2025-26 appear only if they were already signed (biased fast). A model trained or tested on those cohorts would learn the window, not the process.

# COMMAND ----------

tl = spark.table(f"{GOLD}.tender_timelines")
open_timed = tl.filter("is_timed AND competition = 'open'")
display(open_timed.groupBy(F.year("tender_notice_date").alias("notice_year")).agg(
            F.count("*").alias("contracts"),
            F.expr("percentile(days_notice_to_signing, array(0.1, 0.5, 0.9))").alias("p10_p50_p90_days"))
        .orderBy("notice_year"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Rows to model and rows to score
# MAGIC
# MAGIC **What:**
# MAGIC - **training rows:** openly competed, timed contracts whose first tender notice falls in the cohort window; target = notice -> signing days (capped at 730). Method, category and country come from the contract (the procurement plan fixes them before advertising), with the notice's values as fallback.
# MAGIC - **scoring rows:** tender notices of an openly competed method published in the 730 days before the snapshot that have no linked contract yet.
# MAGIC
# MAGIC **Why:** both kinds of row get exactly the same notice-time features, so the model is trained on what it will see when scoring. The contract amount is left out on purpose: it is only known at award, and no pre-award estimate exists in the data. Review type (prior / post) is also left out because notices do not carry it.

# COMMAND ----------

notices = spark.table(f"{SILVER}.notices")
methods = spark.table(f"{SILVER}.dim_procurement_method").select(
    F.col("method_name").alias("procurement_method_name"), "competition")
links = spark.table(f"{SILVER}.notice_contract_links")
notice_cols = ["notice_id", "notice_date", "notice_type", "submission_deadline", "notice_text_chars", "notice_language",
               "project_id"]

train_rows = (open_timed
    # the cohort: older notices are biased slow, newer ones biased fast (section 1), so both ends are cut off
    .filter(F.col("tender_notice_date").between(WINDOW_START, WINDOW_END))
    .select(F.col("contract_id").alias("row_id"), F.col("tender_notice_id").alias("notice_id"),
            F.col("borrower_country_code").alias("c_country"), F.col("procurement_method_name").alias("c_method"),
            F.col("procurement_category_code").alias("c_category"), "days_notice_to_signing", "n_tender_notices",
            "signing_date")
    .join(notices.select(*notice_cols, F.col("country_code").alias("n_country"),
                         F.col("procurement_method_name").alias("n_method"),
                         F.col("procurement_category_code").alias("n_category")), "notice_id")
    # contract values first: the procurement plan fixes method, category and country before the notice goes out
    .withColumn("country_code", F.coalesce("c_country", "n_country"))
    .withColumn("procurement_method_name", F.coalesce("c_method", "n_method"))
    .withColumn("procurement_category_code", F.coalesce("c_category", "n_category"))
    .drop("c_country", "n_country", "c_method", "n_method", "c_category", "n_category"))

linked_notices = links.filter("link_role = 'tender'").select("notice_id").distinct()
score_rows = (notices
    .filter(F.col("notice_type").isin(TENDER_TYPES))
    .filter(F.col("notice_date").between(SNAPSHOT - timedelta(days=HORIZON_DAYS), SNAPSHOT))
    .join(methods.filter("competition = 'open'"), "procurement_method_name")
    # only notices still waiting for a contract are scored
    .join(linked_notices, "notice_id", "left_anti")
    .select(F.col("notice_id").alias("row_id"), *notice_cols, "country_code", "procurement_method_name",
            "procurement_category_code"))
print(f"training rows: {train_rows.count():,} | open notices to score: {score_rows.count():,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Features as of the notice date
# MAGIC
# MAGIC **What:** one feature builder for both kinds of row:
# MAGIC - notice: type, method, category, advertising period (deadline minus notice date), language, length of the notice text, month of the year;
# MAGIC - project (`dim_project`): region, major sector, environmental category, age at the notice, log commitment, number of tender notices the project published before this one;
# MAGIC - country (`silver.country_year`, **year before the notice**): the six WGI governance scores and log GDP per capita;
# MAGIC - market, from the **36 months before the notice month** in the same country x category: contracts signed, distinct winning supplier entities (p04), share of foreign winners, mean firms named per award notice; and the median notice -> signing duration of contracts with the same country x method signed in that window.
# MAGIC
# MAGIC **Why:** market history is computed per (country, category, month) on a window that ends before the notice month, so no feature can see the outcome or anything published after the notice. The project's outcome-risk score from the earlier project is **not** used: it exists only for projects still active in 2026, so its presence leaks whether a project was later extended.

# COMMAND ----------

def month_index(col):
    return F.year(col) * 12 + F.month(col) - 1


all_tenders = notices.filter(F.col("notice_type").isin(TENDER_TYPES) & F.col("notice_date").isNotNull())
# rank, not row_number: notices published the same day do not count each other as "earlier"
prior_tenders = all_tenders.select("notice_id", (F.rank().over(Window.partitionBy("project_id").orderBy("notice_date")) - 1)
                                   .alias("project_prior_tenders"))
projects = spark.table(f"{SILVER}.dim_project").select("project_id", "region", "major_sector", "env_category",
                                                       "approval_date", "commitment_musd")
governance = spark.table(COUNTRY_YEAR).select(
    # leakage guard: a notice in year Y gets the indicators of Y-1, which were already published
    F.col("country_iso2").alias("country_code"), (F.col("year") + 1).alias("notice_year"),
    "wgi_gov_effectiveness", "wgi_control_corruption", "wgi_rule_of_law", "wgi_regulatory_quality",
    "wgi_political_stability", "wgi_voice_accountability", "log_gdp_pc")

# market history, pre-aggregated per month (small, cached: both row sets reuse it)
contracts = spark.table(f"{SILVER}.contracts")
cc = ["country_code", "procurement_category_code"]
hist_contracts = (contracts.select(F.col("borrower_country_code").alias("country_code"), "procurement_category_code",
                                   month_index("signing_date").alias("h_month"))
                  .groupBy(*cc, "h_month").agg(F.count("*").alias("n_contracts")).cache())
hist_winners = (spark.table(f"{SILVER}.contract_suppliers").join(spark.table(f"{SILVER}.supplier_entity_map"), "supplier_id")
                .join(contracts.select("contract_id", "borrower_country_code", "procurement_category_code", "signing_date"),
                      "contract_id")
                .select(F.col("borrower_country_code").alias("country_code"), "procurement_category_code",
                        month_index("signing_date").alias("h_month"), "supplier_entity_id",
                        # null when either country is missing; count() and sum() below skip nulls, so the share uses
                        # known rows only
                        (F.col("supplier_country_code") != F.col("borrower_country_code")).cast("int").alias("is_foreign"))
                .groupBy(*cc, "h_month", "supplier_entity_id")
                .agg(F.count("is_foreign").alias("rows"), F.sum("is_foreign").alias("foreign_rows")).cache())
hist_bidders = (notices.filter("notice_type = 'Contract Award' AND n_named_firms > 0")
                .select("country_code", "procurement_category_code", month_index("notice_date").alias("h_month"),
                        "n_named_firms")
                .groupBy(*cc, "h_month").agg(F.count("*").alias("notices"), F.sum("n_named_firms").alias("firms")).cache())
past_durations = (tl.filter("is_timed")
                  .select(F.col("borrower_country_code").alias("country_code"), "procurement_method_name",
                          month_index("signing_date").alias("h_month"), "days_notice_to_signing").cache())


def as_of_history(need, history, keys, aggs):
    """Aggregate `history` rows of the same keys in the 36 months before each needed month."""
    # ends the month before the notice month: nothing signed in the notice's own month (possibly after it) can leak in
    window = (F.col("h_month") >= F.col("n_month") - 36) & (F.col("h_month") <= F.col("n_month") - 1)
    return need.join(history, keys).filter(window).groupBy(*keys, "n_month").agg(*aggs)


def add_features(rows):
    base = (rows.withColumn("n_month", month_index("notice_date"))
            .withColumn("notice_year", F.year("notice_date")))
    # aggregate once per distinct (key, month) rather than per row, then join back
    need_cc = base.select("country_code", "procurement_category_code", "n_month").distinct()
    need_cm = base.select("country_code", "procurement_method_name", "n_month").distinct()
    volume = as_of_history(need_cc, hist_contracts, cc, [F.sum("n_contracts").alias("mkt_contracts_3y")])
    market = as_of_history(need_cc, hist_winners, cc,
                           [F.countDistinct("supplier_entity_id").alias("mkt_winners_3y"),
                            (F.sum("foreign_rows") / F.sum("rows")).alias("mkt_foreign_share_3y")])
    bidders = as_of_history(need_cc, hist_bidders, cc,
                            [(F.sum("firms") / F.sum("notices")).alias("mkt_mean_named_firms_3y")])
    durations = as_of_history(need_cm, past_durations, ["country_code", "procurement_method_name"],
                              [F.expr("percentile_approx(days_notice_to_signing, 0.5)").alias("hist_median_days_cm"),
                               F.count("*").alias("hist_n_cm")])
    return (base
            .join(projects, "project_id", "left").join(prior_tenders, "notice_id", "left")
            .join(governance, ["country_code", "notice_year"], "left")
            .join(volume, [*cc, "n_month"], "left")
            .join(market, [*cc, "n_month"], "left")
            .join(bidders, [*cc, "n_month"], "left")
            .join(durations, ["country_code", "procurement_method_name", "n_month"], "left")
            .withColumn("region", F.coalesce("region", F.lit("Other")))
            # a deadline before the notice date is a data error; leave it missing instead of feeding a negative period
            .withColumn("advertising_days", F.when(F.datediff("submission_deadline", "notice_date") >= 0,
                                                   F.datediff("submission_deadline", "notice_date")))
            .withColumn("log_notice_chars", F.log1p("notice_text_chars"))
            .withColumn("notice_month", F.month("notice_date"))
            .withColumn("project_age_years", F.datediff("notice_date", "approval_date") / 365.25)
            .withColumn("log_commitment", F.log1p("commitment_musd"))
            # no history in the window really means zero contracts; ratios and medians stay missing instead
            .fillna(0, subset=["mkt_contracts_3y", "mkt_winners_3y", "hist_n_cm"]))


CATEGORICAL = ["procurement_method_name", "procurement_category_code", "notice_type", "region", "country_code",
               "major_sector", "env_category", "notice_language"]
NUMERIC = ["advertising_days", "log_notice_chars", "notice_month", "project_age_years", "log_commitment",
           "project_prior_tenders", "wgi_gov_effectiveness", "wgi_control_corruption", "wgi_rule_of_law",
           "wgi_regulatory_quality", "wgi_political_stability", "wgi_voice_accountability", "log_gdp_pc",
           "mkt_contracts_3y", "mkt_winners_3y", "mkt_foreign_share_3y", "mkt_mean_named_firms_3y",
           "hist_median_days_cm", "hist_n_cm"]
FEATURES = CATEGORICAL + NUMERIC
keep = ["row_id", "notice_id", "notice_date", "project_id", "submission_deadline"] + FEATURES
# tens of thousands of rows x ~30 columns: small enough for LightGBM on the driver
data = add_features(train_rows).select(*keep, "days_notice_to_signing", "n_tender_notices").toPandas()
scoring = add_features(score_rows).select(*keep).toPandas()
for frame in (data, scoring):
    frame["notice_date"] = pd.to_datetime(frame["notice_date"])
for frame in (data, scoring):
    frame[NUMERIC] = frame[NUMERIC].astype(float)
assert data["row_id"].is_unique and scoring["row_id"].is_unique
print(f"training rows {len(data):,} | scoring rows {len(scoring):,}")
display(data[NUMERIC].describe().T.round(2).reset_index())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Time split, slow-tender label and baselines
# MAGIC
# MAGIC **What:**
# MAGIC - target `y` = notice -> signing days capped at 730 (1.5% of the cohort took longer);
# MAGIC - train = notices before 2023-07-01, test = notices 2023-07-01 .. 2024-10-13 (the newest fully observable ones);
# MAGIC - **slow** = `y` above the P75 of its method x category in the training years (category P75 when the group has fewer than 30 contracts). The threshold is fixed on training data, so the test base rate can drift;
# MAGIC - baselines: the global training quantiles, and the **peer-group** quantiles (country x method x category, falling back to region, method x category, category; at least 30 contracts) — the benchmark a procurement analyst would look up today.
# MAGIC
# MAGIC **Why:** a planner's question is relative ("slow for an RFB works contract?"), so slowness is defined against the peer group, not in absolute days. The peer-group table is the baseline a model has to beat.

# COMMAND ----------

data["y"], _ = cap_at_horizon(data["days_notice_to_signing"])
# the whole cohort, used for the final refit and the benchmark table after testing
train_all = data.copy()
is_test = data["notice_date"] >= pd.Timestamp(TEST_START)
train, test = data[~is_test].copy(), data[is_test].copy()


def slow_thresholds(frame: pd.DataFrame) -> pd.DataFrame:
    """P75 of y per method x category (>= MIN_PEER_N contracts), else the category P75."""
    mc = frame.groupby(["procurement_method_name", "procurement_category_code"])["y"].agg(["size", lambda s: s.quantile(0.75)])
    mc.columns = ["n", "thr_mc"]
    cat = frame.groupby("procurement_category_code")["y"].quantile(0.75).rename("thr_cat")
    return mc[mc["n"] >= MIN_PEER_N][["thr_mc"]].reset_index(), cat.reset_index()


# thresholds from the training years only; they are then applied unchanged to test and scoring rows
thr_mc, thr_cat = slow_thresholds(train)


def attach_threshold(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.merge(thr_mc, on=["procurement_method_name", "procurement_category_code"], how="left") \
               .merge(thr_cat, on="procurement_category_code", how="left")
    out["slow_threshold_days"] = out["thr_mc"].fillna(out["thr_cat"]).round()
    return out.drop(columns=["thr_mc", "thr_cat"]).set_axis(frame.index)


train, test, train_all, scoring = (attach_threshold(f) for f in (train, test, train_all, scoring))
for f in (train, test, train_all):
    f["slow"] = slow_label(f["y"], f["slow_threshold_days"])
print(f"train {len(train):,} rows ({train['notice_date'].min():%Y-%m} .. {train['notice_date'].max():%Y-%m}) | "
      f"test {len(test):,} rows ({test['notice_date'].min():%Y-%m} .. {test['notice_date'].max():%Y-%m})")
print(f"slow base rate: train {train['slow'].mean():.3f} | test {test['slow'].mean():.3f}")
print(f"re-advertised (more than one tender notice linked): train {(train['n_tender_notices'] > 1).mean():.4f} | "
      f"test {(test['n_tender_notices'] > 1).mean():.4f}")

global_q = {q: train["y"].quantile(q) for q in QUANTILES}
peer_test = peer_baseline(train, test, "y")
for q in QUANTILES:
    # a test row whose peer group never appears in training falls back to the global quantiles
    peer_test[f"q{q}"] = peer_test[f"q{q}"].fillna(global_q[q])
display(peer_test["level"].value_counts().rename_axis("baseline_level").reset_index())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Quantile models, tuned with rolling-origin validation
# MAGIC
# MAGIC **What:** LightGBM with the quantile (pinball) objective for P10, P50 and P90, trained on `log(1 + days)` (quantiles survive a monotone transform, and the log tames the long right tail). Categorical columns use LightGBM's native handling with the training categories fixed, so unseen countries become missing. Tuning: a small grid of tree sizes, each scored on four expanding-window folds inside the training years (validation = the next 6 months), with early stopping; the peer-group baseline is scored on the same folds.
# MAGIC
# MAGIC **Why:** a random split would let lots of the same tender, and the same months, sit on both sides. Rolling origins mimic how the model is used: trained on the past, asked about the next half-year.

# COMMAND ----------

# a fixed category list keeps LightGBM's category codes identical between training, test and the registered model
CATEGORIES = {c: sorted(train_all[c].dropna().unique()) for c in CATEGORICAL}


def model_input(frame: pd.DataFrame) -> pd.DataFrame:
    """Raw feature columns as the registered model takes them (a missing category becomes a placeholder string,
    which is not a training category, so the model treats it as missing)."""
    X = frame[FEATURES].copy()
    X[CATEGORICAL] = X[CATEGORICAL].fillna("(missing)")
    return X


def make_X(frame: pd.DataFrame) -> pd.DataFrame:
    X = frame[FEATURES].copy()
    for c in CATEGORICAL:
        X[c] = pd.Categorical(X[c], categories=CATEGORIES[c])
    for c in NUMERIC:
        X[c] = X[c].astype(float)
    return X


BASE_PARAMS = {"learning_rate": 0.05, "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1,
               "lambda_l2": 1.0, "cat_smooth": 20, "verbose": -1, "num_threads": THREADS, "seed": SEED}
GRID = [{"num_leaves": nl, "min_data_in_leaf": md} for nl in (15, 31, 63) for md in (30, 100)]


def fit_quantile(X, y, alpha, params, rounds, X_val=None, y_val=None):
    p = {**BASE_PARAMS, **params, "objective": "quantile", "alpha": alpha, "metric": "quantile"}
    # quantiles survive a monotone transform, so fitting on log(1 + days) and converting back keeps them valid
    dtrain = lgb.Dataset(X, np.log1p(y))
    if X_val is None:
        return lgb.train(p, dtrain, num_boost_round=rounds)
    dval = lgb.Dataset(X_val, np.log1p(y_val), reference=dtrain)
    return lgb.train(p, dtrain, num_boost_round=rounds, valid_sets=[dval],
                     callbacks=[lgb.early_stopping(50, verbose=False)])


def predict_days(model, X):
    return np.expm1(model.predict(X, num_iteration=model.best_iteration or None))


folds = rolling_origin_folds(train["notice_date"], CV_ORIGINS, val_months=6)
cv_rows = []
for params in GRID:
    for k, (tr, va) in enumerate(folds):
        m = fit_quantile(make_X(train[tr]), train["y"][tr], 0.5, params, 2000, make_X(train[va]), train["y"][va])
        cv_rows.append({**params, "fold": k, "best_iter": m.best_iteration,
                        "pinball50": pinball_loss(train["y"][va], predict_days(m, make_X(train[va])), 0.5)})
cv = pd.DataFrame(cv_rows)
for k, (tr, va) in enumerate(folds):
    base = peer_baseline(train[tr], train[va], "y", quantiles=(0.5,))["q0.5"]
    cv_rows.append({"num_leaves": "peer baseline", "min_data_in_leaf": "", "fold": k,
                    "pinball50": pinball_loss(train["y"][va], base, 0.5)})
cv_all = pd.DataFrame(cv_rows).astype({"num_leaves": str, "min_data_in_leaf": str})
cv_summary = (cv_all.groupby(["num_leaves", "min_data_in_leaf"], dropna=False)
              .agg(mean_pinball50=("pinball50", "mean"), per_fold=("pinball50", lambda s: [round(v, 1) for v in s]),
                   median_best_iter=("best_iter", "median")).reset_index().sort_values("mean_pinball50"))
display(cv_summary)
best = cv.groupby(["num_leaves", "min_data_in_leaf"])["pinball50"].mean().idxmin()
BEST_PARAMS = {"num_leaves": int(best[0]), "min_data_in_leaf": int(best[1])}
# the final fit has no validation set to stop on; use the folds' median best iteration, +10% for the larger training set
ROUNDS = int(cv[(cv["num_leaves"] == best[0]) & (cv["min_data_in_leaf"] == best[1])]["best_iter"].median() * 1.1)
print("chosen:", BEST_PARAMS, "rounds:", ROUNDS)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Test-set results: model vs baselines
# MAGIC
# MAGIC **What:**
# MAGIC - the three quantile models refit on all training notices and scored on the held-out newest notices;
# MAGIC - **conformal calibration of the interval** (conformalised quantile regression): P10 and P90 models fitted on training notices before 2023-01-01 are scored on the last training half-year; the violations on each side (in log-days) give a shift that makes each tail miss at most 10% on that half-year, and the same shifts are applied to the final models' bounds. The P50 is unchanged;
# MAGIC - metrics: mean and median absolute error of the P50 in days, pinball loss at each quantile, the share of outcomes inside P10-P90 (target 80%), the shares below P10 and above P90 (target 10% each) and the mean interval width; then the same by category.
# MAGIC
# MAGIC **Why:** a benchmark range is only useful if it is both calibrated (coverage near 80%) and narrower or more accurate than the lookup table people already have. Raw quantile trees are usually over-confident, and the newest notices are faster than older ones, so the interval needs a correction measured on data the model did not train on.

# COMMAND ----------

X_train, X_test = make_X(train), make_X(test)
q_models = {q: fit_quantile(X_train, train["y"], q, BEST_PARAMS, ROUNDS) for q in QUANTILES}
# three separate models can cross on some rows; sorting restores P10 <= P50 <= P90
p10_raw, p50, p90_raw = sort_quantiles(*(predict_days(q_models[q], X_test) for q in QUANTILES))

# calibration models are fitted without the last half-year so their misses on it are honest, out-of-sample
pre, cal = train["notice_date"] < pd.Timestamp(CAL_START), train["notice_date"] >= pd.Timestamp(CAL_START)
X_pre, X_cal, ly_cal = make_X(train[pre]), make_X(train[cal]), np.log1p(train["y"][cal].to_numpy())
lo_cal = fit_quantile(X_pre, train["y"][pre], 0.1, BEST_PARAMS, ROUNDS).predict(X_cal)
hi_cal = fit_quantile(X_pre, train["y"][pre], 0.9, BEST_PARAMS, ROUNDS).predict(X_cal)
# one shift per side, since the raw model missed both tails by different amounts
LO_SHIFT, HI_SHIFT = conformal_shift(lo_cal - ly_cal, 0.1), conformal_shift(ly_cal - hi_cal, 0.1)
print(f"calibration rows {int(cal.sum()):,} | raw miss on calibration: below P10 {np.mean(ly_cal < lo_cal):.3f}, "
      f"above P90 {np.mean(ly_cal > hi_cal):.3f} | shifts (log-days): lower {LO_SHIFT:+.3f}, upper {HI_SHIFT:+.3f}")


def widen(lo, hi):
    return np.expm1(np.log1p(lo) - LO_SHIFT), np.expm1(np.log1p(hi) + HI_SHIFT)


p10, p90 = widen(p10_raw, p90_raw)
p10, p50, p90 = sort_quantiles(p10, p50, p90)


def duration_metrics(name, y, lo, mid, hi):
    return {"forecast": name, "mae_days": np.mean(np.abs(y - mid)), "median_ae_days": np.median(np.abs(y - mid)),
            "pinball_p10": pinball_loss(y, lo, 0.1), "pinball_p50": pinball_loss(y, mid, 0.5),
            "pinball_p90": pinball_loss(y, hi, 0.9), "coverage_p10_p90": interval_coverage(y, lo, hi),
            "below_p10": np.mean(y < lo), "above_p90": np.mean(y > hi), "mean_width_days": np.mean(hi - lo)}


yt = test["y"].to_numpy()
n = len(test)
results = pd.DataFrame([
    duration_metrics("global quantiles", yt, np.full(n, global_q[0.1]), np.full(n, global_q[0.5]), np.full(n, global_q[0.9])),
    duration_metrics("peer-group quantiles", yt, peer_test["q0.1"].to_numpy(), peer_test["q0.5"].to_numpy(),
                     peer_test["q0.9"].to_numpy()),
    duration_metrics("LightGBM quantile (raw interval)", yt, p10_raw, p50, p90_raw),
    duration_metrics("LightGBM quantile + conformal interval", yt, p10, p50, p90)])
results["mean_pinball"] = results[["pinball_p10", "pinball_p50", "pinball_p90"]].mean(axis=1)
display(results.round(3))

by_cat = test.assign(err_model=np.abs(yt - p50), err_peer=np.abs(yt - peer_test["q0.5"].to_numpy()),
                     inside=(yt >= p10) & (yt <= p90))
display(by_cat.groupby("procurement_category_code").agg(
    contracts=("y", "size"), median_days=("y", "median"), mae_model=("err_model", "mean"),
    mae_peer=("err_peer", "mean"), coverage_model=("inside", "mean")).round(2).reset_index())

model_row, peer_row = results.iloc[3], results.iloc[1]
# the registration gate in section 10: no champion unless the model beats the lookup table on both measures
BEATS_BASELINE = bool(model_row["mean_pinball"] < peer_row["mean_pinball"] and model_row["mae_days"] < peer_row["mae_days"])
print("model beats the peer-group baseline on mean pinball and MAE:", BEATS_BASELINE)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. What drives the duration (SHAP)
# MAGIC
# MAGIC **What:** TreeSHAP contributions of the P50 model on the test rows (LightGBM's `pred_contrib`, in log-days), as the mean absolute contribution per feature; for numeric features, the sign of the correlation between the feature and its contribution says whether higher values lengthen (+) or shorten (-) the tender.
# MAGIC
# MAGIC **Why:** a benchmark that cannot say why a tender is expected to be slow is hard to act on; drivers also expose leakage (a feature that is "too good" would top the list).

# COMMAND ----------

# the last column of pred_contrib is the bias term, not a feature
contrib = q_models[0.5].predict(X_test, pred_contrib=True)[:, :-1]
shap_table = pd.DataFrame({"feature": FEATURES, "mean_abs_shap_log_days": np.abs(contrib).mean(axis=0)})
direction = {}
for i, f in enumerate(FEATURES):
    if f in NUMERIC and X_test[f].notna().sum() > 30 and X_test[f].nunique() > 1:
        direction[f] = "+" if np.corrcoef(X_test[f].fillna(X_test[f].median()), contrib[:, i])[0, 1] > 0 else "-"
shap_table["direction"] = shap_table["feature"].map(direction).fillna("categorical")
shap_table = shap_table.sort_values("mean_abs_shap_log_days", ascending=False).reset_index(drop=True)
display(shap_table.head(12).round(4))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Slow-tender risk
# MAGIC
# MAGIC **What:** a LightGBM classifier for `slow` with the same features and tree size, its rounds chosen by early stopping on the same rolling-origin folds. Test metrics: ROC-AUC, PR-AUC (against the base rate), Brier score, and a calibration table (observed vs predicted by decile). Baselines: the peer group's historical slow rate, and the quantile model's own P50 relative to the threshold.
# MAGIC
# MAGIC **Why:** re-advertisement would be the natural "re-bidding" target, but it is too rare and too poorly observed to model (printed in section 4: about 1 in 70 contracts has a second tender notice linked, and a re-tender under a new reference is invisible). Running slow against the peer group is observable for every timed contract and is what a planner can act on.

# COMMAND ----------

def fit_classifier(X, y, rounds, X_val=None, y_val=None):
    p = {**BASE_PARAMS, **BEST_PARAMS, "objective": "binary", "metric": "binary_logloss"}
    dtrain = lgb.Dataset(X, y)
    if X_val is None:
        return lgb.train(p, dtrain, num_boost_round=rounds)
    return lgb.train(p, dtrain, num_boost_round=rounds, valid_sets=[lgb.Dataset(X_val, y_val, reference=dtrain)],
                     callbacks=[lgb.early_stopping(50, verbose=False)])


clf_iters, clf_cv_auc = [], []
for tr, va in folds:
    m = fit_classifier(make_X(train[tr]), train["slow"][tr], 2000, make_X(train[va]), train["slow"][va])
    clf_iters.append(m.best_iteration)
    clf_cv_auc.append(roc_auc_score(train["slow"][va], m.predict(make_X(train[va]), num_iteration=m.best_iteration)))
CLF_ROUNDS = int(np.median(clf_iters) * 1.1)
clf = fit_classifier(X_train, train["slow"], CLF_ROUNDS)
p_slow = clf.predict(X_test)
yt_slow = test["slow"].to_numpy()

peer_rate = peer_aggregate(train, test, "slow", {"rate": "mean"})["rate"].fillna(train["slow"].mean()).to_numpy()
p50_ratio = p50 / test["slow_threshold_days"].to_numpy()
risk_results = pd.DataFrame([
    {"score": name, "roc_auc": roc_auc_score(yt_slow, s), "pr_auc": average_precision_score(yt_slow, s),
     # a ratio is a ranking score, not a probability, so a Brier score would be meaningless for it
     "brier": brier_score_loss(yt_slow, s) if name != "quantile model P50 / threshold" else np.nan}
    for name, s in [("peer-group slow rate", peer_rate), ("quantile model P50 / threshold", p50_ratio),
                    ("LightGBM classifier", p_slow)]])
print(f"test base rate {yt_slow.mean():.3f} (= PR-AUC of a random score) | classifier CV ROC-AUC per fold: "
      f"{[round(a, 3) for a in clf_cv_auc]} | rounds {CLF_ROUNDS}")
display(risk_results.round(3))
display(calibration_table(yt_slow, p_slow, n_bins=10).round(3))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Survival view: unsigned tenders as censored observations
# MAGIC
# MAGIC **What:**
# MAGIC - **Kaplan-Meier per tender notice:** every openly competed tender notice since 2019-07-01; the event is the signing of its first linked contract; a notice without one is censored at the snapshot (at most 1,095 days). Curves by category, and a table by notice year comparing the KM share signed within 180 and 365 days with the naive median of the durations that happen to be observed.
# MAGIC - **Weibull AFT** on the training contracts (durations capped at 730 = censored there), with a few interpretable covariates; `exp(coef)` is a time ratio (1.2 = 20% longer), and the concordance is measured on the test rows.
# MAGIC
# MAGIC **Why:** survival analysis is the correct treatment for recent notices that have not been signed **yet**. The catch is identification: an old notice with no linked contract is either a cancelled tender or a contract the linker could not match (p05 links about 6 in 10 mature notices), and the data cannot tell them apart. So the KM curve estimates "signed **and linked** by day t" and flattens near the link rate; it is reliable for comparing timing across groups and cohorts, not for the share of tenders that fail.

# COMMAND ----------

from lifelines import KaplanMeierFitter, WeibullAFTFitter
from lifelines.utils import concordance_index

first_signing = (links.filter("link_role = 'tender' AND notice_before_signing")
                 .join(contracts.select("contract_id", "signing_date"), "contract_id")
                 .groupBy("notice_id").agg(F.min("signing_date").alias("first_signing")))
km_rows = (notices.filter(F.col("notice_type").isin(TENDER_TYPES) & (F.col("notice_date") >= WINDOW_START)
                          & (F.col("notice_date") <= SNAPSHOT))
           .join(methods.filter("competition = 'open'"), "procurement_method_name")
           .join(first_signing, "notice_id", "left")
           .withColumn("t_event", F.datediff("first_signing", "notice_date"))
           # follow-up capped at 3 years for every notice, so old and young cohorts are compared on the same horizon
           .withColumn("event", (F.col("t_event").isNotNull() & (F.col("t_event") <= 1095)).cast("int"))
           .withColumn("duration", F.when(F.col("event") == 1, F.col("t_event"))
                       .otherwise(F.least(F.datediff(F.lit(SNAPSHOT), "notice_date"), F.lit(1095))))
           .select("notice_id", F.year("notice_date").alias("notice_year"), "procurement_category_code",
                   "notice_type", "duration", "event")
           .toPandas())
print(f"notices: {len(km_rows):,} | linked signing observed: {km_rows['event'].mean():.3f}")

fig, ax = plt.subplots(figsize=(7, 4))
km_cat = []
for cat, grp in km_rows.dropna(subset=["procurement_category_code"]).groupby("procurement_category_code"):
    kmf = KaplanMeierFitter().fit(grp["duration"], grp["event"], label=cat)
    (1 - kmf.survival_function_).plot(ax=ax)
    signed = {t: 1 - float(kmf.survival_function_at_times(t).iloc[0]) for t in (180, 365, 730, 1095)}
    # the curve never reaches 1 (unlinked notices), so the median is taken among notices signed within 3 years
    half = 0.5 * signed[1095]
    cdf = 1 - kmf.survival_function_[cat]
    km_cat.append({"category": cat, "notices": len(grp), **{f"signed_by_{t}d": round(v, 3) for t, v in signed.items()},
                   "median_days_among_linked": int(cdf[cdf >= half].index[0])})
ax.set_xlabel("days since tender notice"); ax.set_ylabel("share signed (linked contract)"); ax.set_xlim(0, 1095)
ax.set_title("Kaplan-Meier: tender notice -> first linked signing")
plt.tight_layout(); plt.show()
display(pd.DataFrame(km_cat))

km_year = []
for year, grp in km_rows.groupby("notice_year"):
    kmf = KaplanMeierFitter().fit(grp["duration"], grp["event"])
    observed = grp.loc[grp["event"] == 1, "duration"]
    km_year.append({"notice_year": year, "notices": len(grp), "max_follow_up_days": int(grp["duration"].max()),
                    "km_signed_by_180d": round(1 - float(kmf.survival_function_at_times(180).iloc[0]), 3),
                    "km_signed_by_365d": round(1 - float(kmf.survival_function_at_times(365).iloc[0]), 3),
                    "naive_median_observed_days": int(observed.median()) if len(observed) else None})
display(pd.DataFrame(km_year))

# COMMAND ----------

def aft_frame(frame: pd.DataFrame, medians: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=frame.index)
    for cat in ("CS", "CW", "NC"):                      # goods is the reference
        out[f"cat_{cat}"] = (frame["procurement_category_code"] == cat).astype(int)
    out["method_rfb"] = (frame["procurement_method_name"] == "Request for Bids").astype(int)
    for region in ("Western and Central Africa", "Eastern and Southern Africa", "South Asia",
                   "Middle East, North Africa, Afghanistan, and Pakistan", "Latin America and Caribbean",
                   "East Asia and Pacific"):                # Europe and Central Asia is the reference
        out["region_" + region.split(",")[0].replace(" ", "_").lower()] = (frame["region"] == region).astype(int)
    for c in ("wgi_gov_effectiveness", "log_commitment", "project_age_years", "advertising_days"):
        out[c] = frame[c].fillna(medians[c])
    out["log_hist_median_days"] = np.log1p(frame["hist_median_days_cm"].fillna(medians["hist_median_days_cm"]))
    return out


aft_medians = train[["wgi_gov_effectiveness", "log_commitment", "project_age_years", "advertising_days",
                     "hist_median_days_cm"]].median().to_dict()
duration_tr, event_tr = cap_at_horizon(train["days_notice_to_signing"])
# Weibull needs strictly positive durations; same-day signings become 1 day
aft_train = aft_frame(train, aft_medians).assign(duration=np.maximum(duration_tr, 1), event=event_tr.astype(int))
aft = WeibullAFTFitter(penalizer=0.01).fit(aft_train, duration_col="duration", event_col="event")
aft_test = aft_frame(test, aft_medians)
aft_c = concordance_index(test["y"], aft.predict_median(aft_test).to_numpy().ravel())
lgb_c = concordance_index(test["y"], p50)
ratios = aft.summary.loc["lambda_"].reset_index()[["covariate", "exp(coef)", "exp(coef) lower 95%", "exp(coef) upper 95%", "p"]]
display(ratios[ratios["covariate"] != "Intercept"].rename(columns={"exp(coef)": "time_ratio"}).round(3))
print(f"test concordance: Weibull AFT {aft_c:.3f} | LightGBM P50 {lgb_c:.3f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 10. Log to MLflow and register the champion
# MAGIC
# MAGIC **What:** one MLflow run per forecast (the two baselines and the model, with its conformal interval) with the same test metrics, so the experiment page compares them side by side; the model run also logs the CV table, the SHAP table and the risk metrics. The registered model is a `pyfunc` that takes the raw feature columns and returns `p10_days`, `p50_days`, `p90_days` and `slow_probability`; it is refit on the whole cohort (train + test) before logging. It is registered as `ml.proc_tender_duration` with alias `@champion` **only if** it beat the peer-group baseline on the test set.
# MAGIC
# MAGIC **Why:** the alias is what scoring code loads, so an inferior model never becomes the default by accident; the metrics in the run are those of the model fitted without the test rows.

# COMMAND ----------

class TenderDurationModel(mlflow.pyfunc.PythonModel):
    """P10 / P50 / P90 notice -> signing days and the slow-tender probability from notice-time features."""

    def __init__(self, quantile_models: dict, classifier: str, categories: dict, categorical: list, numeric: list,
                 lower_shift: float, upper_shift: float):
        self.quantile_models, self.classifier = quantile_models, classifier     # LightGBM model strings
        self.lower_shift, self.upper_shift = lower_shift, upper_shift          # conformal shifts, log-days
        self.categories, self.categorical, self.numeric = categories, categorical, numeric
        self._boosters = None

    def _load(self):
        if self._boosters is None:
            # boosters are rebuilt from the stored model strings on first use, so only plain text is pickled with the
            # pyfunc
            self._boosters = {q: lgb.Booster(model_str=s) for q, s in self.quantile_models.items()}
            self._boosters["slow"] = lgb.Booster(model_str=self.classifier)
        return self._boosters

    def __getstate__(self):          # pickle the model strings only, not the loaded boosters
        return {**self.__dict__, "_boosters": None}

    def predict(self, context, model_input, params=None):
        boosters = self._load()
        X = model_input[self.categorical + self.numeric].copy()
        for c in self.categorical:
            X[c] = pd.Categorical(X[c], categories=self.categories[c])
        for c in self.numeric:
            X[c] = X[c].astype(float)
        lo, mid, hi = (boosters[k].predict(X) for k in sorted(self.quantile_models))
        q = sort_quantiles(np.expm1(lo - self.lower_shift), np.expm1(mid), np.expm1(hi + self.upper_shift))
        return pd.DataFrame({"p10_days": q[0], "p50_days": q[1], "p90_days": q[2],
                             "slow_probability": boosters["slow"].predict(X)}, index=model_input.index)


mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(EXPERIMENT)
metric_cols = ["mae_days", "median_ae_days", "pinball_p10", "pinball_p50", "pinball_p90", "mean_pinball",
               "coverage_p10_p90", "below_p10", "above_p90", "mean_width_days"]
window_tags = {"cohort": f"{WINDOW_START}..{WINDOW_END}", "test_from": str(TEST_START), "horizon_days": HORIZON_DAYS,
               "snapshot": str(SNAPSHOT)}
for _, r in results.iloc[:2].iterrows():
    with mlflow.start_run(run_name=f"baseline: {r['forecast']}"):
        mlflow.log_params(window_tags)
        mlflow.log_metrics({f"test_{c}": float(r[c]) for c in metric_cols})

# test metrics above come from the train-only fit; this refit only adds the newest notices for scoring
# refit on the whole cohort for scoring
X_all = make_X(train_all)
final_q = {q: fit_quantile(X_all, train_all["y"], q, BEST_PARAMS, ROUNDS) for q in QUANTILES}
final_clf = fit_classifier(X_all, train_all["slow"], CLF_ROUNDS)
pyfunc_model = TenderDurationModel({q: m.model_to_string() for q, m in final_q.items()}, final_clf.model_to_string(),
                                   CATEGORIES, CATEGORICAL, NUMERIC, LO_SHIFT, HI_SHIFT)
example = model_input(train_all.head(5))
with mlflow.start_run(run_name="lightgbm quantile + slow classifier") as run:
    mlflow.log_params({**window_tags, **BEST_PARAMS, "rounds": ROUNDS, "classifier_rounds": CLF_ROUNDS,
                       "conformal_lower_shift": round(LO_SHIFT, 4), "conformal_upper_shift": round(HI_SHIFT, 4),
                       "features": len(FEATURES), "train_rows": len(train), "test_rows": len(test)})
    mlflow.log_metrics({f"test_{c}": float(model_row[c]) for c in metric_cols})
    mlflow.log_metrics({f"test_raw_{c}": float(results.iloc[2][c]) for c in ("coverage_p10_p90", "mean_pinball")})
    mlflow.log_metrics({"test_slow_roc_auc": float(risk_results.iloc[2]["roc_auc"]),
                        "test_slow_pr_auc": float(risk_results.iloc[2]["pr_auc"]),
                        "test_slow_brier": float(risk_results.iloc[2]["brier"]),
                        "test_slow_base_rate": float(yt_slow.mean()),
                        "test_concordance_p50": float(lgb_c), "test_concordance_weibull_aft": float(aft_c)})
    mlflow.log_table(cv_summary.astype(str), "cv_rolling_origin.json")
    mlflow.log_table(shap_table, "shap_p50.json")
    info = mlflow.pyfunc.log_model(
        name="model", python_model=pyfunc_model, input_example=example,
        signature=infer_signature(example, pyfunc_model.predict(None, example)),
        pip_requirements=[f"lightgbm=={lgb.__version__}", f"pandas=={pd.__version__}", f"numpy=={np.__version__}"],
        code_paths=[os.path.join(SRC_DIR, "proc_intel")])
    run_id = run.info.run_id

MODEL_VERSION = "not registered"
if BEATS_BASELINE:
    version = mlflow.register_model(info.model_uri, MODEL_NAME)
    client = mlflow.MlflowClient()
    client.set_registered_model_alias(MODEL_NAME, "champion", version.version)
    MODEL_VERSION = f"{MODEL_NAME}/{version.version}"
print(f"run {run_id} | model: {MODEL_VERSION}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 11. Publish `tender_benchmarks` and `open_tender_scores`
# MAGIC
# MAGIC **What:**
# MAGIC - `tender_benchmarks`: empirical quantiles and slow rates of the whole cohort for every peer group at the four levels (schema at the top);
# MAGIC - `open_tender_scores`: the champion's range and slow probability for each open notice, next to its peer benchmark; when no model is registered the peer benchmark fills the range and the probability is left empty.
# MAGIC
# MAGIC **Why:** the benchmark table answers "what is normal for this kind of tender?" and needs no model; the scores answer "what about this tender?". The agent's tool reads both through `benchmark_lookup` and a key lookup.

# COMMAND ----------

bench_rows = []
for level, cols in LEVELS:
    for keys, grp in train_all.groupby(list(cols)):
        keys = dict(zip(cols, keys if isinstance(keys, tuple) else (keys,)))
        values = {c: keys.get(c, ALL) for c in ("country_code", "region", "procurement_method_name",
                                                 "procurement_category_code")}
        if level == "country_method_category":
            # the country level keeps its region in the key so benchmark_lookup can fall back to region without another
            # lookup
            values["region"] = grp["region"].mode().iloc[0]
        thr = grp["slow_threshold_days"].iloc[0]
        # at category level the group mixes methods, each with its own threshold, so there is no single value to show
        thr = None if level == "category" or pd.isna(thr) else float(thr)
        bench_rows.append({"benchmark_key": benchmark_key(level, *values.values()), "benchmark_level": level, **values,
                           "n_contracts": float(len(grp)), "p10_days": round(grp["y"].quantile(0.1)),
                           "p50_days": round(grp["y"].quantile(0.5)), "p90_days": round(grp["y"].quantile(0.9)),
                           "slow_threshold_days": thr, "slow_rate": round(float(grp["slow"].mean()), 3)})
benchmarks = pd.DataFrame(bench_rows)
assert benchmarks["benchmark_key"].is_unique
n_bench = publish_table(
    spark.createDataFrame(benchmarks.astype(object).where(benchmarks.notna(), None),
                          "benchmark_key string, benchmark_level string, country_code string, region string, "
                          "procurement_method_name string, procurement_category_code string, n_contracts double, "
                          "p10_days double, p50_days double, p90_days double, slow_threshold_days double, slow_rate double")
        .select(*[F.col(c).cast("int").alias(c) if c.endswith("_days") or c == "n_contracts" else F.col(c)
                  for c in benchmarks.columns])
        .withColumn("window_start", F.lit(WINDOW_START)).withColumn("window_end", F.lit(WINDOW_END))
        .withColumn("built_at", F.current_timestamp()),
    f"{GOLD}.tender_benchmarks",
    "Peer-group benchmarks of tender notice -> contract signing days for openly competed contracts (notices "
    f"{WINDOW_START} to {WINDOW_END}, durations capped at {HORIZON_DAYS} days). Grain: one row per peer group and level. "
    "Read with proc_intel.risk.benchmark_lookup (finest level with >= 30 contracts). Built by p07.",
    {"benchmark_key": "PK. level|country|region|method|category (ALL where the level does not use the column)",
     "benchmark_level": "country_method_category, region_method_category, method_category or category",
     "country_code": "Borrower country (ALL above country level)", "region": "World Bank region (ALL above region level)",
     "procurement_method_name": "Procurement method (ALL at category level)",
     "procurement_category_code": "CW / GO / CS / NC", "n_contracts": "Contracts in the peer group",
     "p10_days": "10th percentile of notice -> signing days (capped at 730)", "p50_days": "Median days",
     "p90_days": "90th percentile of days", "slow_threshold_days": "Method x category P75 of the training years; above = slow",
     "slow_rate": "Share of the group's contracts above the threshold", "window_start": "First notice date covered",
     "window_end": "Last notice date covered", "built_at": "Build time"},
    primary_key=["benchmark_key"])

if BEATS_BASELINE:
    scored = mlflow.pyfunc.load_model(f"models:/{MODEL_NAME}@champion").predict(model_input(scoring))
    scored.index = scoring.index
else:
    scored = pd.DataFrame({"p10_days": np.nan, "p50_days": np.nan, "p90_days": np.nan, "slow_probability": np.nan},
                          index=scoring.index)
# same lookup the agent tool uses, so the table and the tool agree on the peer group
peer = [benchmark_lookup(bench_rows, r.country_code, r.procurement_method_name, r.procurement_category_code, r.region)
        for r in scoring.itertuples()]
scores = scoring[["row_id", "project_id", "country_code", "region", "procurement_method_name",
                  "procurement_category_code", "notice_type", "notice_date", "submission_deadline",
                  "slow_threshold_days"]].rename(columns={"row_id": "notice_id"}).copy()
scores["peer_p50_days"] = [p.get("p50_days") for p in peer]
scores["peer_level"] = [p.get("benchmark_level") for p in peer]
for c in ("p10_days", "p50_days", "p90_days"):
    fallback = [p.get(c) for p in peer]
    scores[c] = np.where(scored[c].notna(), scored[c].round(), fallback)
scores["slow_probability"] = scored["slow_probability"].round(4)
scores["days_elapsed"] = (pd.Timestamp(SNAPSHOT) - scores["notice_date"]).dt.days.astype(float)
scores["past_p90"] = scores["days_elapsed"] > scores["p90_days"]
scores["expected_signing_date"] = (scores["notice_date"] + pd.to_timedelta(scores["p50_days"], unit="D")).dt.date
scores["notice_date"] = scores["notice_date"].dt.date
scores["model_version"] = MODEL_VERSION
n_scores = publish_table(
    spark.createDataFrame(scores.astype(object).where(scores.notna(), None),
                          "notice_id string, project_id string, country_code string, region string, "
                          "procurement_method_name string, procurement_category_code string, notice_type string, "
                          "notice_date date, submission_deadline date, slow_threshold_days double, peer_p50_days double, "
                          "peer_level string, p10_days double, p50_days double, p90_days double, slow_probability double, "
                          "days_elapsed double, past_p90 boolean, expected_signing_date date, model_version string")
        .select("notice_id", "project_id", "country_code", "region", "procurement_method_name",
                "procurement_category_code", "notice_type", "notice_date", "submission_deadline",
                F.col("days_elapsed").cast("int"),
                *[F.col(c).cast("int").alias(c) for c in ("p10_days", "p50_days", "p90_days")],
                "expected_signing_date", "slow_probability", F.col("slow_threshold_days").cast("int"),
                F.col("peer_p50_days").cast("int"), "peer_level", "past_p90", "model_version")
        .withColumn("scored_at", F.current_timestamp()),
    f"{GOLD}.open_tender_scores",
    f"Open tender notices (openly competed method, published in the {HORIZON_DAYS} days before {SNAPSHOT}, no linked "
    "contract yet) with the predicted notice -> signing range and slow-tender probability. Grain: one row per notice. "
    "About 4 in 10 mature notices never get a linked contract, so some of these may be signed or cancelled already. Built by p07.",
    {"notice_id": "PK, FK proc_silver.notices", "project_id": "FK proc_silver.dim_project",
     "country_code": "Country of the notice", "region": "World Bank region of the project",
     "procurement_method_name": "Method on the notice", "procurement_category_code": "CW / GO / CS / NC",
     "notice_type": "IFB / REOI / prequalification", "notice_date": "Notice publication date",
     "submission_deadline": "Bid / EOI deadline", "days_elapsed": "Snapshot date minus notice date",
     "p10_days": "Model P10 of notice -> signing days (peer benchmark when no model is registered)",
     "p50_days": "Model median days", "p90_days": "Model P90 days",
     "expected_signing_date": "Notice date + p50_days", "slow_probability": "Probability of exceeding slow_threshold_days",
     "slow_threshold_days": "Method x category P75 of the training years", "peer_p50_days": "Peer-group median (tender_benchmarks)",
     "peer_level": "Benchmark level used", "past_p90": "Open longer than the P90 already",
     "model_version": "Registered model version used", "scored_at": "Scoring time"},
    primary_key=["notice_id"])
add_foreign_key(f"{GOLD}.open_tender_scores", ["notice_id"], f"{SILVER}.notices", ["notice_id"])
print(f"tender_benchmarks {n_bench:,} | open_tender_scores {n_scores:,}")
display(spark.table(f"{GOLD}.open_tender_scores").orderBy(F.desc("slow_probability")).limit(5))
print(json.dumps(benchmark_lookup(bench_rows, "KE", "Request for Bids", "CW"), default=str))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 12. Checks and summary
# MAGIC
# MAGIC **What:** keys, quantile order (P10 <= P50 <= P90 in both tables), every open notice scored, no leakage-prone columns among the features, and the headline numbers.
# MAGIC
# MAGIC **Why:** the agent will quote these tables; a crossed interval or a missing score would surface as a wrong answer.

# COMMAND ----------

B, S = spark.table(f"{GOLD}.tender_benchmarks"), spark.table(f"{GOLD}.open_tender_scores")
checks = [
    ("tender_benchmarks", "duplicate benchmark_key", duplicate_keys(B, ["benchmark_key"]), "== 0"),
    ("tender_benchmarks", "rows with p10 > p50 or p50 > p90", B.filter("p10_days > p50_days OR p50_days > p90_days").count(), "== 0"),
    ("tender_benchmarks", "category-level contracts vs cohort rows",
     B.filter("benchmark_level = 'category'").agg(F.sum("n_contracts")).first()[0] - len(train_all), "== 0"),
    ("open_tender_scores", "duplicate notice_id", duplicate_keys(S, ["notice_id"]), "== 0"),
    ("open_tender_scores", "rows vs notices to score", S.count() - len(scoring), "== 0"),
    ("open_tender_scores", "rows with p10 > p50 or p50 > p90", S.filter("p10_days > p50_days OR p50_days > p90_days").count(), "== 0"),
    ("open_tender_scores", "rows without a range", S.filter("p50_days IS NULL").count(), "info"),
    ("open_tender_scores", "orphan notice_id", orphan_count(S, "notice_id", notices, "notice_id"), "== 0"),
    # leakage guard: none of these is known on the notice date
    ("model", "award-time columns among features (amount, review type, signing)",
     len({"contract_amount_usd", "review_type", "signing_date", "n_tender_notices"} & set(FEATURES)), "== 0"),
    ("model", "test rows: notices on or after test start", int((test["notice_date"] < pd.Timestamp(TEST_START)).sum()), "== 0"),
    ("model", "beats peer baseline (mean pinball and MAE)", BEATS_BASELINE, "info"),
]
display(dq_report(checks))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run summary
# MAGIC
# MAGIC **What:** the headline numbers as the notebook's exit value.
# MAGIC
# MAGIC **Why:** a job run shows them without opening the notebook. (In its own cell: output displayed in the same cell as `dbutils.notebook.exit` is dropped from the run record.)

# COMMAND ----------

summary = {"train_rows": len(train), "test_rows": len(test), "scored_open_notices": n_scores, "benchmark_rows": n_bench,
           "test_mae_model": round(float(model_row["mae_days"]), 1), "test_mae_peer": round(float(peer_row["mae_days"]), 1),
           "test_mean_pinball_model": round(float(model_row["mean_pinball"]), 2),
           "test_mean_pinball_peer": round(float(peer_row["mean_pinball"]), 2),
           "test_coverage_p10_p90": round(float(model_row["coverage_p10_p90"]), 3),
           "test_coverage_raw": round(float(results.iloc[2]["coverage_p10_p90"]), 3),
           "slow_base_rate_test": round(float(yt_slow.mean()), 3),
           "slow_roc_auc": round(float(risk_results.iloc[2]["roc_auc"]), 3),
           "slow_roc_auc_peer": round(float(risk_results.iloc[0]["roc_auc"]), 3),
           "model": MODEL_VERSION, "mlflow_run": run_id}
print(summary)

# COMMAND ----------

dbutils.notebook.exit(json.dumps(summary))
