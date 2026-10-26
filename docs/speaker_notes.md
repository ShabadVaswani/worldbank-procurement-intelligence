# Likely panel questions

Questions a panel may ask about the prototype, with short answers. The slide deck (`slides/procurement_intelligence.pptx`, PDF copy next to it) carries its own speaker cues in the slide notes; the full design is in [proposal.md](proposal.md).

1. **Why keep the knowledge graph in Delta tables and not a graph database?**
   - The questions are batch, two to four hops, over a few million edges; Spark joins and GraphFrames answer in seconds and gave identical answers in a check.
   - One copy means one set of permissions, lineage and time travel.
   - If an interactive product needs millisecond deep traversal, export the same node and edge tables to a graph database as a read replica.

2. **Walk me through the grain of your core tables. Why separate `contracts` and `contract_suppliers`?**
   - The feed is one row per contract and supplier. Contract attributes were constant within a contract on all 282,890, so they moved up a level without loss.
   - The amount is the contract value repeated per joint-venture member, not a share. Keeping it once per contract prevents double counting.
   - `contract_suppliers` is a bridge table with a composite key; supplier totals are "value of contracts won as a member" and say so.

3. **How would you model lots, framework agreements and re-tenders?**
   - One tender notice can cover many lots: notice to contract is one-to-many, and one reference appeared on 188 contracts.
   - Add a `tender_package` entity keyed by the STEP activity id where present, with lots as children; contracts link to a lot.
   - A re-tender is a new notice for the same package: an edge `RE_ADVERTISES` between notices, which needs the STEP id because re-tenders under a new reference are invisible today.

4. **How would you design a star schema for procurement analytics on sample data?**
   - Facts at clear grains: `fact_contract` (one row per contract), `fact_bid` (one row per bidder per notice), `fact_tender_event` (one row per notice).
   - Conformed dimensions: date (role-played as notice, deadline, signing), country, project, method, category, supplier entity.
   - Bridge for joint ventures; supplier as a type-2 slowly changing dimension so a firm's name and country are correct as of each contract.
   - Measures that are not additive, such as contract value across joint-venture members, are documented on the fact.

5. **How do you handle a supplier whose name changes, or two firms that merge?**
   - Entity ids are deterministic from the first supplier id of a component, so they stay stable across runs.
   - A type-2 history of the entity map records when an id joined or left an entity; merges and splits become events, not silent rewrites.
   - Disputed merges go to a review queue; a manual override table wins over the rules.

6. **How do you know entity resolution is good beyond 100 labelled pairs?**
   - The labelled pairs chose the threshold, so 40 random produced links were also audited: 34 same firm or group, 30 same legal entity.
   - The pair labels come from the three-tier escalation (question 16): 90 of 100 settled unanimously by three judges, 10 decided by the adjudicator with written evidence.
   - Cluster sizes are a second check: one rule change raised recall on labels but created a 412-record hub, which I caught from the size distribution and fixed.
   - In production: sample links weekly, track precision by country, and watch the largest clusters.

7. **What stops the duration model from leaking the outcome?**
   - Only features known on the notice date: no contract amount, no review type, no outcome score that exists only for still-active projects.
   - Governance indicators from the year before; market history from the 36 months before the notice.
   - Time-based validation with rolling origins, and a test set of newer notices.
   - The trap I did hit: the deployed champion was refit on everything, test period included. The backtest caught it (50 days in-sample vs 75 fair) and now always refits at the cutoff.

8. **Why gradient-boosted quantiles rather than a survival model?**
   - LightGBM was more accurate on test (concordance 0.721 against 0.694 for the Weibull model).
   - The survival view is kept for what it does best: using unsigned tenders as censored and giving readable time ratios.
   - Quantiles plus a conformal step give a calibrated range, which is what a planner needs.

9. **How do you detect a claim that cites a real record that does not support it?**
   - Today: the groundedness judge, then the three-tier labels on the review pack: the adjudicator checks each disputed claim against the warehouse (firm counts in award notices, project ids) and confirmed 2 real errors.
   - Next: a sentence-level entailment check between each risk and its cited passage, plus specialist review in the pilot.
   - Numbers never come from the model; they come from the benchmark or the model forecast and are checked in code.

10. **What if the ICR and ISR disagree and IEG has not reviewed the project yet?**
    - The policy falls back to the ICR self-rating for outcome questions, marks confidence lower and shows the last ISR as conflicting.
    - The measured gap shows why this matters: IEG rated 91 of 381 projects below the ICR.

11. **How do you handle missing or incomplete reporting?**
    - Training windows only where the outcome is observable; survival analysis for open tenders.
    - Coverage reported with its denominator, such as 44.9% of openly competed contracts, not of all contracts.
    - Gaps are listed with their workaround in data_gaps.md, and the agent writes "evidence gaps" as a separate field.

12. **How does this scale to every PAD and ICR?**
    - About 1 to 2 million passages, a rough estimate: move from exact search to Databricks Vector Search with Delta sync and metadata filters.
    - Ingestion and graph updates are incremental; embedding cost is proportional to new and changed passages only.
    - Job clusters per task and serverless SQL for dashboards.

13. **How do you protect personal data and control access?**
    - Individual consultants arrive hashed and are never re-identified; contact fields are never requested; ownership tables in notices are never parsed.
    - Unity Catalog: pipeline writes, analysts read gold and silver, the agent identity reads only what its tools need; tags and column masks for personal fields.
    - Audit logs, lineage and one MLflow trace per agent run.

14. **How would you prove the platform reduced planning cycle time?**
    - Compare pilot hubs with similar non-pilot hubs over the same quarters, a difference-in-differences design, not before and after.
    - Track intermediate KPIs the tool controls: benchmark error, citation validity, use, feedback.
    - Baseline today: median 160 days for openly competed contracts signed in the last 12 months.

15. **Why Qwen and Llama, and could you switch models?**
    - They were the serving endpoints available in the workspace; Qwen matched Llama's quality on trial packages and was faster.
    - The agent uses the standard chat-completions format of the serving endpoints and the checks are in code, so the model is a setting; a switch reruns the same evaluation set before promotion.

16. **Who labelled your evaluation data?**
    - If asked which model adjudicated: Claude (Anthropic). It is the same family as the coding agents I used, so it was kept off the panel, and as adjudicator it settled factual questions with SQL or web evidence, recorded in the log, rather than its own opinion.
    - No person labelled items by hand, and I say so up front. The labels come from a three-tier escalation. Code decides what code can: is the actual duration inside the cited P10-P90 range, is every citation valid. A panel of three LLM judges from different model families labels the rest independently: gpt-oss-120b, Llama 4 Maverick, and Qwen 3.5 on supplier pairs or Llama 3.3 70B on briefs, because Qwen wrote the briefs. Where the judges disagree, an AI adjudicator agent with access to the warehouse tables and the web decides and writes down its evidence.
    - Why this design: every item gets the same rubric, so the labels are consistent; it is cheap, because only real disagreements get the deeper look (24 of 220 fields); judges from different families are calibrated against each other (kappa 0.86 on pairs); and every escalated decision has written evidence anyone can audit, in data/human_review/adjudication_log.md.
    - It earns its keep: the adjudicator overturned 7 of 24 panel majorities and confirmed 2 real errors in the agent's briefs from the data, a precedent wrongly called "same project" and an overstated firm-count range. Final numbers: entity resolution precision 1.00 and recall 0.90 on 97 decided pairs; an unsupported claim in 5 of 30 briefs in the first version, 2 of 30 after the facts lines and the code fact-check, and 1 of 10 on a holdout.
    - Next: independent validation by procurement specialists is part of the pilot plan. Their labels become the next evaluation set and a check on the panel itself.
