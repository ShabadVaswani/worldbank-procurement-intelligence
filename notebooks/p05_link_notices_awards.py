# Databricks notebook source
# MAGIC %md
# MAGIC # p05_link_notices_awards — from tender notice to signed contract
# MAGIC
# MAGIC Links each contract to the notices that advertised it (Invitation for Bids, Request for Expression of Interest, Invitation for Prequalification) and to the Contract Award notice that announced it, then derives the procurement timeline of every contract. The timeline table is the training target for the phase-2 delay and risk model.
# MAGIC
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_silver.notice_contract_links` | notice x contract, with role (tender / award) and how it was matched | `notice_id, contract_id` |
# MAGIC | `proc_gold.tender_timelines` | contract, with its milestones, durations, context and data-gap flags | `contract_id` |

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <pre class="mermaid">
# MAGIC ---
# MAGIC config:
# MAGIC   layout: elk
# MAGIC ---
# MAGIC flowchart LR
# MAGIC     tn["tender notice<br/>(IFB / REOI / IFP)"]
# MAGIC     bd["bid deadline<br/>(submission_deadline)"]
# MAGIC     an["award notification<br/>(award notice HTML)"]
# MAGIC     cs["contract signed<br/>(awards feed)"]
# MAGIC     tn -->|"advertising period"| bd
# MAGIC     bd --> an --> cs
# MAGIC     bd -.->|"evaluation, award and signature"| cs
# MAGIC     tn -.->|"days_notice_to_signing"| cs
# MAGIC </pre>
# MAGIC <script type="module">
# MAGIC   import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.6.0/dist/mermaid.esm.min.mjs";
# MAGIC   import elkLayouts from "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.1.7/dist/mermaid-layout-elk.esm.min.mjs";
# MAGIC   mermaid.registerLayoutLoaders(elkLayouts);
# MAGIC   mermaid.initialize({ startOnLoad: true });
# MAGIC </script>

# COMMAND ----------

# MAGIC %md
# MAGIC Match tiers, strongest first, always **within the same project**:
# MAGIC
# MAGIC | Tier | Rule |
# MAGIC |---|---|
# MAGIC | `exact_reference` | same reference after removing case, spaces and punctuation |
# MAGIC | `step_activity_id` | same STEP activity id (the 6-digit number in `MZ-MISAU-458432-GO-RFB`) |
# MAGIC | `reference_variant` | one reference is the other plus 1-3 letters (lot or re-issue marker: `EMCRP/G-06A`) |
# MAGIC | `description` | contract has no STEP id; same category; notice 0-3 years before signing; description similarity >= 0.8 and clearly the best candidate |
# MAGIC
# MAGIC Award notices are additionally checked against the **awarded supplier ids** printed in the notice.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key design decisions
# MAGIC
# MAGIC | Decision | Rationale | Evidence |
# MAGIC |---|---|---|
# MAGIC | Both exact tiers kept (project + reference, and STEP activity id); links where the notice is published after signing are stored, flagged, and never used for durations | A notice after signing indicates a reference re-used for a later round, not the tender of this contract | Exact project + reference matches found tender notices for about 61,500 contracts; the STEP id added only about 2,300 more; about 6,000 links had the notice published after signing |
# MAGIC | The similarity ratio replaced by a structural rule: references must be equal after deleting one block of 1-3 letters (never digits) from the longer one, implemented as an equi-join on generated deletion keys | Ratio >= 0.9 also matched different packages one character apart; the rule needs no pairwise comparison | Lot markers ("17B/W/DNAAS/2018" for tender "17/W/DNAAS/2018") versus false matches ("TCP/CON/QCBS/B1/G" vs ".../B1/D", "ENU-02-22" vs "ENU-03-22") |
# MAGIC | Description matching only for contracts without a STEP id, with >= 0.8 similarity and a clear margin over the second-best notice; the tier is measured separately in the hand audit | Descriptions are the only bridge when the contract reference is the borrower's own number, but they confuse near-identical packages | Even at >= 0.9, wrong-package matches occurred ("Civil Work Package (CWP) 7" vs "CWP 8", "Fish Landing in Brgy. Taruk" vs "Brgy. Tapian"); bridging matches read correctly ("Audit externe des comptes du projet PRAPS-II NE ...") |
# MAGIC | An award link is kept when the notice's awarded supplier id is one of the contract's suppliers (confirmed), or when the pair is one-to-one and the notice names no awardee | One reference is shared by all lots and call-offs of a tender | Reference-only matching produced about 980,000 award-notice/contract pairs (section 3); one reference appears on 188 contracts; the confirmed share among one-to-one pairs with a named awardee is the automatic precision check |
# MAGIC | Coverage reported per competition level; the phase 2 timeline model to be trained on openly competed contracts | Most contracts are never publicly advertised | Request for Quotations, direct selection and individual consultants make up about 80% of contracts |
# MAGIC
# MAGIC Full reasoning: docs/decision_log.md

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC
# MAGIC **What:** libraries, shared helpers, tier constants and the audit label file.
# MAGIC
# MAGIC **Why:** the reference rules are the tested functions in `proc_intel.references`, applied here as UDFs.

# COMMAND ----------

# MAGIC %pip install -q rapidfuzz unidecode

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

import json

import numpy as np
from pyspark.sql import Window
from pyspark.sql.types import ArrayType, StringType
from sklearn.feature_extraction.text import TfidfVectorizer

from proc_intel.references import TIER_EXACT, TIER_STEP, TIER_VARIANT, variant_keys
from proc_intel.similarity import wilson_interval

TIER_DESCRIPTION = "description"
# lower = stronger evidence; used to keep the best tier when one pair is found by several joins
TIER_ORDER = {TIER_EXACT: 1, TIER_STEP: 2, TIER_VARIANT: 3, TIER_DESCRIPTION: 4}
TENDER_TYPES = ["Invitation for Bids", "Request for Expression of Interest", "Invitation for Prequalification"]
# 0.9 still matched sibling packages ("CWP 7" vs "CWP 8"), so a looser floor plus a clear margin over the runner-up
# works better
DESCRIPTION_MIN = 0.80
DESCRIPTION_MARGIN = 0.10
MAX_TENDER_DAYS = 3 * 365          # a tender notice older than this before signing is not the same round
AUDIT_PATH = os.path.join(os.path.dirname(SRC_DIR), "data", "tender_link_audit.csv")
# more labels for the weaker tiers, where the precision is actually in doubt
AUDIT_PER_TIER = {TIER_EXACT: 15, TIER_STEP: 10, TIER_VARIANT: 8, TIER_DESCRIPTION: 12}
variant_keys_udf = as_udf(variant_keys, ArrayType(StringType()))

contracts = spark.table(f"{SILVER}.contracts").join(
    spark.table(f"{SILVER}.dim_procurement_method").select(F.col("method_name").alias("procurement_method_name"),
                                                            "competition"), "procurement_method_name", "left")
notices = spark.table(f"{SILVER}.notices")
c_keys = contracts.select("contract_id", "project_id", "reference_norm", "step_activity_id", "signing_date")
n_keys = notices.select("notice_id", "notice_type", "project_id", "reference_norm", "step_activity_id", "notice_date")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Reference tiers (exact, STEP id, variant)
# MAGIC
# MAGIC **What:** three equi-joins within the same project:
# MAGIC - on the normalised reference;
# MAGIC - on the STEP activity id;
# MAGIC - on deletion keys: each reference's "minus one block of 1-3 letters" versions joined to the other side's normalised reference, in both directions.
# MAGIC
# MAGIC Each (notice, contract) pair keeps its strongest tier.
# MAGIC
# MAGIC **Why:** joins scale to 283k contracts x 380k notices without comparing every pair.

# COMMAND ----------

# every tier joins inside the same project: references like "GO-01" repeat across projects
exact = (c_keys.join(n_keys, ["project_id", "reference_norm"])
         .select("notice_id", "contract_id", F.lit(TIER_EXACT).alias("match_tier")))
step = (c_keys.filter("step_activity_id IS NOT NULL").join(n_keys, ["project_id", "step_activity_id"])
        .select("notice_id", "contract_id", F.lit(TIER_STEP).alias("match_tier")))
c_var = c_keys.select("contract_id", "project_id", F.explode(variant_keys_udf("reference_norm")).alias("key"))
n_var = n_keys.select("notice_id", "project_id", F.explode(variant_keys_udf("reference_norm")).alias("key"))
# both directions: either side can carry the extra lot / re-issue letters (e.g. "17B/W/..." vs "17/W/...")
variant = (c_var.join(n_keys.withColumnRenamed("reference_norm", "key"), ["project_id", "key"])
           .select("notice_id", "contract_id")
           .union(n_var.join(c_keys.withColumnRenamed("reference_norm", "key"), ["project_id", "key"])
                  .select("notice_id", "contract_id"))
           .withColumn("match_tier", F.lit(TIER_VARIANT)))
# two different STEP ids are never the same tender, whatever the rest of the string says
variant = (variant.join(c_keys.select("contract_id", F.col("step_activity_id").alias("c_step")), "contract_id")
           .join(n_keys.select("notice_id", F.col("step_activity_id").alias("n_step")), "notice_id")
           .filter("c_step IS NULL OR n_step IS NULL OR c_step = n_step").drop("c_step", "n_step"))

tier_rank = F.create_map(*[x for k, v in TIER_ORDER.items() for x in (F.lit(k), F.lit(v))])
reference_links = (exact.union(step).union(variant)
                   .withColumn("_rank", tier_rank[F.col("match_tier")])
                   .withColumn("_rn", F.row_number().over(Window.partitionBy("notice_id", "contract_id").orderBy("_rank")))
                   .filter("_rn = 1").drop("_rank", "_rn")
                   .join(n_keys.select("notice_id", "notice_type", "notice_date"), "notice_id")
                   .join(c_keys.select("contract_id", "signing_date"), "contract_id")
                   .withColumn("link_role", F.when(F.col("notice_type").isin(TENDER_TYPES), "tender")
                               .when(F.col("notice_type") == "Contract Award", "award"))
                   # other notice types (general procurement notices, ...) do not advertise or award a single contract
                   .filter("link_role IS NOT NULL")
                   .cache())
display(reference_links.groupBy("link_role", "match_tier").agg(F.count("*").alias("links"),
                                                               F.countDistinct("contract_id").alias("contracts"),
                                                               F.countDistinct("notice_id").alias("notices"))
        .orderBy("link_role", "match_tier"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Description tier for contracts without a STEP reference
# MAGIC
# MAGIC **What:** for openly competed contracts that have no STEP id and no tender link yet, the candidate tender notices of the same project and category published 0-3 years before signing are scored by TF-IDF cosine of the descriptions (words and word pairs). The best candidate is accepted if it scores >= 0.8 and beats the second-best by >= 0.1.
# MAGIC
# MAGIC **Why:** these contracts carry the borrower's own contract number, so the reference cannot match; the guard against near-identical sibling packages is the margin and the restriction to contracts without a STEP id (Step 3).

# COMMAND ----------

# a notice published after signing is a reused reference, not this contract's tender
tender_linked = reference_links.filter("link_role = 'tender' AND notice_date <= signing_date").select("contract_id").distinct()
# only contracts without a STEP id: with one, a missing reference match is a real gap and descriptions mostly find
# siblings
open_unlinked = (contracts.filter("competition = 'open' AND step_activity_id IS NULL")
                 .join(tender_linked, "contract_id", "left_anti")
                 .select("contract_id", "project_id", "procurement_category_code", "signing_date", "contract_description"))
tender_notices = notices.filter(F.col("notice_type").isin(TENDER_TYPES)).select(
    "notice_id", "project_id", "procurement_category_code", "notice_date", "bid_description")
candidates = (open_unlinked.join(tender_notices, ["project_id", "procurement_category_code"])
              .filter(F.datediff("signing_date", "notice_date").between(0, MAX_TENDER_DAYS))
              .filter("contract_description IS NOT NULL AND bid_description IS NOT NULL")
              .select("contract_id", "notice_id", "contract_description", "bid_description")
              # candidate set is small after the project/category/date filters, so the TF-IDF scoring runs on the driver
              .toPandas())
vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, sublinear_tf=True, strip_accents="unicode")
# fit on distinct texts so a description repeated across many candidate pairs does not skew the idf weights
vectorizer.fit(pd.concat([candidates["contract_description"], candidates["bid_description"]]).drop_duplicates())
a = vectorizer.transform(candidates["contract_description"])
b = vectorizer.transform(candidates["bid_description"])
# row-wise dot product of L2-normalised vectors = cosine for each (contract, notice) pair, without a full matrix
candidates["description_similarity"] = np.asarray(a.multiply(b).sum(axis=1)).ravel()
ranked = candidates.sort_values(["contract_id", "description_similarity"], ascending=[True, False])
ranked["rank"] = ranked.groupby("contract_id").cumcount()
second = ranked[ranked["rank"] == 1].set_index("contract_id")["description_similarity"]
best = ranked[ranked["rank"] == 0].set_index("contract_id")
# a contract with a single candidate gets the full score as margin
best["margin"] = best["description_similarity"] - second.reindex(best.index).fillna(0.0)
accepted = best[(best["description_similarity"] >= DESCRIPTION_MIN) & (best["margin"] >= DESCRIPTION_MARGIN)].reset_index()
print(f"open contracts without STEP id or tender link: {open_unlinked.count():,} | with a candidate: {best.shape[0]:,} | "
      f"accepted: {len(accepted):,}")
description_links = (spark.createDataFrame(accepted[["notice_id", "contract_id", "description_similarity"]])
                     .withColumn("match_tier", F.lit(TIER_DESCRIPTION))
                     .join(n_keys.select("notice_id", "notice_type", "notice_date"), "notice_id")
                     .join(c_keys.select("contract_id", "signing_date"), "contract_id")
                     .withColumn("link_role", F.lit("tender")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Award links confirmed by supplier id
# MAGIC
# MAGIC **What:** for each reference-matched award link, checks whether a firm the notice lists as **awarded** is a supplier of the contract. A link is kept if confirmed, or if the notice and the contract are linked only to each other (one-to-one) and the notice names no awarded firm to contradict it. Prints the confirmation rate where the notice names an awarded firm.
# MAGIC
# MAGIC **Why:** shared references make award links many-to-many; the supplier id printed in the notice is independent evidence that picks the right lot. The confirmation rate on one-to-one pairs is a precision estimate for reference matching in general.

# COMMAND ----------

awarded = spark.table(f"{SILVER}.notice_bidders").filter("role = 'awarded'").select("notice_id", "supplier_id")
cs_ids = spark.table(f"{SILVER}.contract_suppliers").select("contract_id", "supplier_id")
award_ref = reference_links.filter("link_role = 'award'")
# the awarded firm's id in the notice HTML must be one of the contract's suppliers: independent of the reference text
confirmed = (award_ref.join(awarded, "notice_id").join(cs_ids, ["contract_id", "supplier_id"])
             .select("notice_id", "contract_id").distinct().withColumn("supplier_confirmed", F.lit(True)))
named = awarded.select("notice_id").distinct().withColumn("notice_names_awardee", F.lit(True))
degree_n = award_ref.groupBy("notice_id").agg(F.count("*").alias("n_contracts_for_notice"))
degree_c = award_ref.groupBy("contract_id").agg(F.count("*").alias("n_notices_for_contract"))
award_scored = (award_ref.join(confirmed, ["notice_id", "contract_id"], "left")
                .join(named, "notice_id", "left").join(degree_n, "notice_id").join(degree_c, "contract_id")
                .fillna(False, ["supplier_confirmed", "notice_names_awardee"])
                .withColumn("one_to_one", (F.col("n_contracts_for_notice") == 1) & (F.col("n_notices_for_contract") == 1)))
one_to_one_named = award_scored.filter("one_to_one AND notice_names_awardee")
rate = one_to_one_named.agg(F.avg(F.col("supplier_confirmed").cast("int"))).first()[0]
print(f"award links by reference: {award_ref.count():,} | one-to-one pairs whose notice names an awardee: "
      f"{one_to_one_named.count():,}, supplier confirmed in {rate:.1%}")
# one-to-one pairs whose notice names a different awardee are dropped: the id contradicts the reference
award_links = award_scored.filter("supplier_confirmed OR (one_to_one AND NOT notice_names_awardee)").select(
    "notice_id", "contract_id", "match_tier", "notice_type", "notice_date", "signing_date", "link_role", "supplier_confirmed")
display(award_scored.groupBy("one_to_one", "notice_names_awardee", "supplier_confirmed").count()
        .orderBy("one_to_one", "notice_names_awardee", "supplier_confirmed"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. `notice_contract_links`
# MAGIC
# MAGIC **What:** all tender links (reference and description tiers) and the kept award links in one bridge table, with the tier, the description similarity where used, supplier confirmation for award links, and whether the notice precedes the signing.
# MAGIC
# MAGIC **Why:** one bridge serves the timeline below and the knowledge graph (`notice -> contract` edges), and the tier column lets any consumer choose its own precision level.

# COMMAND ----------

tender_links = (reference_links.filter("link_role = 'tender'")
                .withColumn("description_similarity", F.lit(None).cast("double"))
                .unionByName(description_links)
                .withColumn("supplier_confirmed", F.lit(None).cast("boolean")))
links = (tender_links.unionByName(award_links.withColumn("description_similarity", F.lit(None).cast("double")))
         .withColumn("days_notice_to_signing", F.datediff("signing_date", "notice_date"))
         # links with the notice after signing are kept for the graph but flagged, and never used for durations
         .withColumn("notice_before_signing", F.col("days_notice_to_signing") >= 0)
         .select("notice_id", "contract_id", "link_role", "match_tier", "description_similarity", "supplier_confirmed",
                 "notice_before_signing", "days_notice_to_signing"))
n_links = publish_table(
    links, f"{SILVER}.notice_contract_links",
    "Bridge between procurement notices and contracts. Grain: one row per notice x contract. Tender links: the "
    "notice advertised the contract (several lots can share one notice). Award links: the Contract Award notice "
    "of the contract, kept when confirmed by awarded supplier id or one-to-one.",
    {"notice_id": "PK, FK notices", "contract_id": "PK, FK contracts",
     "link_role": "tender (IFB / REOI / prequalification) or award (Contract Award notice)",
     "match_tier": "exact_reference, step_activity_id, reference_variant or description (tender only)",
     "description_similarity": "TF-IDF cosine of the descriptions (description tier only)",
     "supplier_confirmed": "Award links: an awarded supplier id in the notice is a supplier of the contract",
     "notice_before_signing": "Notice date on or before the signing date (tender links: false means a re-used reference; award notices normally follow signing)",
     "days_notice_to_signing": "Signing date minus notice date, in days"},
    primary_key=["notice_id", "contract_id"])
add_foreign_key(f"{SILVER}.notice_contract_links", ["notice_id"], f"{SILVER}.notices", ["notice_id"])
add_foreign_key(f"{SILVER}.notice_contract_links", ["contract_id"], f"{SILVER}.contracts", ["contract_id"])
L = spark.table(f"{SILVER}.notice_contract_links")
display(L.groupBy("link_role", "match_tier").agg(F.count("*").alias("links"), F.countDistinct("contract_id").alias("contracts"),
                                                 F.round(F.avg(F.col("notice_before_signing").cast("int")), 3).alias("share_before_signing"))
        .orderBy("link_role", "match_tier"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Hand audit of tender links
# MAGIC
# MAGIC **What:** a reproducible sample per tier (ordered by a hash of the pair) with both descriptions side by side, labelled by hand in `data/tender_link_audit.csv` (1 = this notice advertised this contract, or the tender of which it is a lot). Prints the share correct per tier with a Wilson interval.
# MAGIC
# MAGIC **Why:** there is no ground truth for tender links; reading pairs is the only direct check, and doing it per tier shows which tiers can be trusted for the timeline.

# COMMAND ----------

sample = (L.filter("link_role = 'tender' AND notice_before_signing")
          .join(notices.select("notice_id", "bid_reference", "bid_description"), "notice_id")
          .join(contracts.select("contract_id", "borrower_reference", "contract_description"), "contract_id")
          # hash order: a sample that looks random but is the same on every run, so the saved labels still line up
          .withColumn("audit_order", F.sha1(F.concat_ws("#", "notice_id", "contract_id")))
          .withColumn("rn", F.row_number().over(Window.partitionBy("match_tier").orderBy("audit_order")))
          .toPandas())
sample = sample[sample["rn"] <= sample["match_tier"].map(AUDIT_PER_TIER)].sort_values(["match_tier", "rn"])
for col in ["contract_description", "bid_description"]:
    sample[col] = sample[col].str.replace(r"\s+", " ", regex=True).str.slice(0, 160)
if os.path.exists(AUDIT_PATH):
    audit = pd.read_csv(AUDIT_PATH, dtype={"contract_id": str})
    judged = sample.merge(audit[["notice_id", "contract_id", "label_correct", "note"]], on=["notice_id", "contract_id"], how="left")
    rows = []
    for tier, grp in judged.groupby("match_tier"):
        grp = grp[grp["label_correct"].notna()]
        ok = int(grp["label_correct"].sum())
        low, high = wilson_interval(ok, len(grp))
        rows.append({"match_tier": tier, "labelled": len(grp), "correct": ok,
                     "share_correct": round(ok / len(grp), 3) if len(grp) else None,
                     "ci_low": round(low, 2), "ci_high": round(high, 2)})
    display(pd.DataFrame(rows))
    display(judged[["match_tier", "borrower_reference", "bid_reference", "contract_description", "bid_description",
                    "label_correct", "note"]])
else:
    display(sample[["match_tier", "notice_id", "contract_id", "borrower_reference", "bid_reference",
                    "contract_description", "bid_description", "description_similarity"]])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. `proc_gold.tender_timelines`
# MAGIC
# MAGIC **What:** one row per contract with:
# MAGIC - milestones: first tender notice date (earliest linked tender notice before signing), its bid deadline, the award-notification date from the linked award notice, and the signing date;
# MAGIC - durations in days: notice -> deadline (advertising), deadline -> signing (evaluation to signature), notice -> signing (total);
# MAGIC - context: method, competition level, category, review type, amount, country, project, the number of tender notices (a re-advertisement signal), the number of firms named in the award notice, and the borrower's governance scores (WGI) for the year **before** signing, joined from the outcome project's `silver.country_year`; the project's outcome-model risk band;
# MAGIC - `is_timed` and `timing_gap`, which say why a contract has no measured duration.
# MAGIC
# MAGIC **Why:** this is the phase-2 modelling table. Indicators come from the year before signing so a model never sees information from after the event; implausible durations (> 3 years, deadline after signing) are flagged rather than silently dropped.

# COMMAND ----------

tender_first = (L.filter("link_role = 'tender' AND notice_before_signing")
                .join(notices.select("notice_id", "notice_type", "notice_date", "submission_deadline"), "notice_id")
                .withColumn("_rank", tier_rank[F.col("match_tier")])
                # earliest notice first (the original advertisement; later ones are re-advertisements), strongest tier
                # on ties
                .withColumn("_rn", F.row_number().over(Window.partitionBy("contract_id").orderBy("notice_date", "_rank")))
                .groupBy("contract_id").agg(
                    F.min(F.when(F.col("_rn") == 1, F.col("notice_id"))).alias("tender_notice_id"),
                    F.min(F.when(F.col("_rn") == 1, F.col("notice_type"))).alias("tender_notice_type"),
                    F.min(F.when(F.col("_rn") == 1, F.col("match_tier"))).alias("tender_match_tier"),
                    F.min("notice_date").alias("tender_notice_date"),
                    F.min(F.when(F.col("_rn") == 1, F.col("submission_deadline"))).alias("submission_deadline"),
                    F.countDistinct("notice_id").alias("n_tender_notices")))
award_first = (L.filter("link_role = 'award'")
               .join(notices.select("notice_id", "notice_date", "award_notification_date", "n_named_firms"), "notice_id")
               .groupBy("contract_id").agg(F.min("award_notification_date").alias("award_notification_date"),
                                           F.min("notice_date").alias("award_notice_date"),
                                           F.max("n_named_firms").alias("n_named_firms_in_award_notice")))
# leakage guard: year + 1 means a contract signed in year Y gets the indicators of Y-1, already published at signing
wgi = spark.table(COUNTRY_YEAR).select(
    F.col("country_iso2").alias("borrower_country_code"), (F.col("year") + 1).alias("signing_year"),
    "wgi_gov_effectiveness", "wgi_control_corruption", "wgi_rule_of_law", "wgi_regulatory_quality", "log_gdp_pc")
projects = spark.table(f"{SILVER}.dim_project").select("project_id", "region", "major_sector", "outcome_risk_band")

timelines = (contracts
    .select("contract_id", "project_id", "borrower_country_code", "procurement_method_name", "competition",
            "procurement_category_code", "review_type", "contract_amount_usd", "is_joint_venture", "signing_date",
            F.year("signing_date").alias("signing_year"), "fiscal_year")
    .join(tender_first, "contract_id", "left").join(award_first, "contract_id", "left")
    .join(wgi, ["borrower_country_code", "signing_year"], "left").join(projects, "project_id", "left")
    .withColumn("days_notice_to_deadline", F.datediff("submission_deadline", "tender_notice_date"))
    .withColumn("days_deadline_to_signing", F.datediff("signing_date", "submission_deadline"))
    .withColumn("days_notice_to_signing", F.datediff("signing_date", "tender_notice_date"))
    .withColumn("days_award_notice_to_signing", F.datediff("signing_date", "award_notification_date"))
    # implausible durations are labelled, not dropped, so the reason stays visible in the gold table
    .withColumn("timing_gap", F.when(F.col("tender_notice_date").isNull(),
                                     F.when(F.col("competition") == "open", "open method, no tender notice linked")
                                     .otherwise("method not normally advertised"))
                .when(F.col("days_notice_to_signing") > MAX_TENDER_DAYS, "notice more than 3 years before signing")
                .when(F.col("days_deadline_to_signing") < 0, "bid deadline after signing")
                .when(F.col("days_notice_to_deadline") < 0, "bid deadline before notice"))
    .withColumn("is_timed", F.col("timing_gap").isNull()))
n_timelines = publish_table(
    timelines, f"{GOLD}.tender_timelines",
    "Procurement timeline per contract: tender notice, bid deadline, award notification and signing, with durations, "
    "context and data-gap flags. Grain: one row per contract. Target table for the phase-2 delay/risk model.",
    {"contract_id": "PK, FK proc_silver.contracts", "project_id": "FK proc_silver.dim_project",
     "borrower_country_code": "FK proc_silver.dim_country", "procurement_method_name": "Procurement method",
     "competition": "open / limited / direct / other", "procurement_category_code": "CW / GO / CS / NC",
     "review_type": "Prior or Post review", "contract_amount_usd": "Contract value (US$, once per contract)",
     "is_joint_venture": "More than one supplier", "signing_date": "Contract signing date",
     "signing_year": "Calendar year of signing", "fiscal_year": "World Bank fiscal year of signing",
     "tender_notice_id": "Earliest tender notice linked before signing",
     "tender_notice_type": "Its type (IFB / REOI / prequalification)", "tender_match_tier": "How it was linked",
     "tender_notice_date": "Date of the earliest linked tender notice",
     "submission_deadline": "Bid / EOI deadline of that notice",
     "n_tender_notices": "Distinct tender notices linked before signing (more than 1 suggests re-advertisement)",
     "award_notification_date": "Award notification date from the linked award notice",
     "award_notice_date": "Publication date of the linked award notice",
     "n_named_firms_in_award_notice": "Firms named in the award notice (awarded + evaluated + rejected)",
     "wgi_gov_effectiveness": "WGI government effectiveness, borrower, year before signing",
     "wgi_control_corruption": "WGI control of corruption, year before signing",
     "wgi_rule_of_law": "WGI rule of law, year before signing",
     "wgi_regulatory_quality": "WGI regulatory quality, year before signing",
     "log_gdp_pc": "log GDP per capita (constant 2015 US$), year before signing",
     "region": "World Bank region", "major_sector": "Project major sector",
     "outcome_risk_band": "Outcome-model risk band of the project (active projects only)",
     "days_notice_to_deadline": "Advertising period: deadline minus notice date",
     "days_deadline_to_signing": "Evaluation to signature: signing minus deadline",
     "days_notice_to_signing": "Total: signing minus tender notice date",
     "days_award_notice_to_signing": "Signing minus award notification date",
     "timing_gap": "Why the contract is not timed (null when timed)",
     "is_timed": "True when a plausible tender-to-signing duration is available"},
    primary_key=["contract_id"])
add_foreign_key(f"{GOLD}.tender_timelines", ["contract_id"], f"{SILVER}.contracts", ["contract_id"])
print("tender_timelines:", n_timelines)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Coverage and durations
# MAGIC
# MAGIC **What:**
# MAGIC - coverage by competition level and by method: share of contracts with a measured duration, and why the rest are not timed;
# MAGIC - duration quantiles (days, notice -> signing) by category for openly competed, timed contracts;
# MAGIC - coverage by signing year.
# MAGIC
# MAGIC **Why:** the correct denominator matters: "40% of contracts are timed" means something different when 80% of contracts were never advertised.

# COMMAND ----------

tl = spark.table(f"{GOLD}.tender_timelines")
display(tl.groupBy("competition").agg(F.count("*").alias("contracts"), F.sum(F.col("is_timed").cast("int")).alias("timed"),
                                      F.round(F.avg(F.col("is_timed").cast("int")), 3).alias("share_timed"))
        .orderBy(F.desc("contracts")))
display(tl.groupBy("competition", "timing_gap").count().orderBy("competition", F.desc("count")))
display(tl.groupBy("procurement_method_name", "competition").agg(
            F.count("*").alias("contracts"), F.round(F.avg(F.col("is_timed").cast("int")), 3).alias("share_timed"))
        .orderBy(F.desc("contracts")).limit(15))
quantiles = F.expr("percentile_approx(days_notice_to_signing, array(0.1, 0.25, 0.5, 0.75, 0.9))")
display(tl.filter("is_timed AND competition = 'open'").groupBy("procurement_category_code").agg(
            F.count("*").alias("timed_contracts"), quantiles.alias("p10_p25_median_p75_p90_days"),
            F.round(F.avg("days_notice_to_deadline"), 1).alias("mean_advertising_days"),
            F.round(F.avg("n_tender_notices"), 2).alias("mean_tender_notices"))
        .orderBy("procurement_category_code"))
display(tl.filter("competition = 'open'").groupBy("signing_year").agg(
            F.count("*").alias("open_contracts"), F.round(F.avg(F.col("is_timed").cast("int")), 3).alias("share_timed"))
        .orderBy("signing_year"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Checks and summary
# MAGIC
# MAGIC **What:** keys, orphans, timeline consistency (no negative total durations among timed rows), and the headline numbers.
# MAGIC
# MAGIC **Why:** the gold table feeds a model; a negative duration or a duplicated contract would silently corrupt it.
# MAGIC
# MAGIC **How the counts fit together** (snapshot 2026-10-20):
# MAGIC
# MAGIC | Count | Value | Definition |
# MAGIC |---|---|---|
# MAGIC | contracts | 282,890 | rows of `tender_timelines` (one per contract) |
# MAGIC | tender notice before signing | 56,968 | contracts with a linked tender notice dated on or before signing (`days_notice_to_signing` not null; notices published after signing are never used) |
# MAGIC | timed, all methods | 56,156 | of those, `is_timed`: 812 dropped as implausible (notice > 3 years before signing 130, bid deadline after signing 378, bid deadline before notice 304); 19.9% of all contracts |
# MAGIC | timed, openly competed | **28,235** | `is_timed AND competition = 'open'`: 44.9% of the 62,828 openly competed contracts; the headline coverage and the phase-2 modelling population |
# MAGIC | median notice -> signing | 158 days (open) / 123 days (all timed) | the summary below prints the all-methods median; the per-category medians in section 7 (works 134, goods 129, consulting 314, non-consulting 120) are for openly competed contracts |

# COMMAND ----------

C = spark.table(f"{SILVER}.contracts")
timed = tl.filter("is_timed")
checks = [
    ("notice_contract_links", "duplicate PK", duplicate_keys(L, ["notice_id", "contract_id"]), "== 0"),
    ("notice_contract_links", "orphan notice_id", orphan_count(L, "notice_id", notices, "notice_id"), "== 0"),
    ("notice_contract_links", "orphan contract_id", orphan_count(L, "contract_id", C, "contract_id"), "== 0"),
    ("tender_timelines", "rows vs contracts", tl.count() - C.count(), "== 0"),
    ("tender_timelines", "duplicate contract_id", duplicate_keys(tl, ["contract_id"]), "== 0"),
    # can only fail if the "notice before signing" filter above is broken
    ("tender_timelines", "timed rows with negative notice->signing", timed.filter("days_notice_to_signing < 0").count(), "== 0"),
    ("tender_timelines", "contracts with a tender link", tl.filter("tender_notice_id IS NOT NULL").count(), "info"),
    ("tender_timelines", "contracts timed", timed.count(), "info"),
    ("tender_timelines", "share of all contracts timed", round(timed.count() / tl.count(), 3), "info"),
    ("tender_timelines", "share of open-competition contracts timed",
     round(timed.filter("competition = 'open'").count() / tl.filter("competition = 'open'").count(), 3), "info"),
    ("tender_timelines", "contracts with an award link", tl.filter("award_notice_date IS NOT NULL").count(), "info"),
    ("tender_timelines", "timed contracts without WGI (regional or missing year)", timed.filter("wgi_gov_effectiveness IS NULL").count(), "info"),
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

summary = {"links": n_links, "timelines": n_timelines, "timed": timed.count(),
           "timed_open_share": round(timed.filter("competition = 'open'").count() / tl.filter("competition = 'open'").count(), 3),
           "median_days_notice_to_signing": timed.agg(F.expr("percentile_approx(days_notice_to_signing, 0.5)")).first()[0]}
print(summary)
dbutils.notebook.exit(json.dumps(summary))
