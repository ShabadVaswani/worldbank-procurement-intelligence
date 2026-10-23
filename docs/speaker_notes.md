# Speaker notes

Talk of about 20 minutes over 5 slides, then 10 minutes of questions. The deck is `slides/procurement_intelligence.pptx` (PDF copy next to it); the full design is in [proposal.md](proposal.md).

| Slide | Topic | Minutes | Cumulative |
|---|---|---|---|
| 1 | Problem and what I built | 4 | 4 |
| 2 | Data model and knowledge graph | 4.5 | 8.5 |
| 3 | AI methods: duration model and cited agent | 4.5 | 13 |
| 4 | Trust: evaluation, conflicting evidence, data gaps | 4 | 17 |
| 5 | Rollout: continuous learning, pilot, next steps | 3 | 20 |
| | Questions | 10 | 30 |

## Slide 1. Problem and what I built

- Open with the problem in one sentence. The registry says what happened, the notices say how, and the completion reports say why, but they sit in three places and nobody reads the third one at planning time.
- I chose to build, not only design. Everything on the slide runs on Azure Databricks on the real public data: the awards feed, procurement notices, project data, ISRs, ICRs and IEG reviews.
- Walk the architecture left to right in one breath: sources, bronze with idempotent loads, a keyed silver model, gold tables and the graph, then the engines and the users. The bottom band is governance: Unity Catalog, MLflow, Workflows.
- Point at the dashed boxes. They are designed but not built, for example disbursements and CPIA. I would rather show the gap than hide it.
- The four numbers: 282,890 contracts linked to notices and projects; 261,169 firms resolved at precision 1.00 and recall 0.90; a duration model 13 days better than the lookup an analyst would use, measured on tenders it never saw; and a backtest that replays 300 real tenders as of their notice date.
- If asked about 75 vs 76: p07 logged 76 on the same test set; the backtest refit the same recipe and got 75.5. Same model recipe, different row order in bagging.
- Transition: "The thing that makes the rest possible is the data model, so let me start there."

## Slide 2. Data model and knowledge graph

- Grain first. One row per contract; joint-venture members live in `contract_suppliers`, because the feed repeats the whole contract value on every member's row. Summing it would double-count 8,864 contracts.
- Keys are declared in Unity Catalog, but Unity Catalog does not enforce them, so every notebook counts duplicates and orphans and stops on a breach. Those checks caught three real defects during the build.
- Entity resolution in three sentences: block by country, TF-IDF character trigrams, and rules that stop chaining. The rules came from failures: twelve provincial land registries merged into one firm, and "Ajay Kumar" under 24 ids. Measured on 100 labelled pairs: precision 1.00 and recall 0.90 on the final three-tier labels (0.97 on the build's first labels, where the threshold was chosen), plus a random audit of 40 links.
- Tender timelines: notices and contracts share no key, so links are tiered and each tier was audited on a sample. 44.9% of openly competed contracts get a measured duration, median 158 days.
- The graph is Delta tables built from those keys: 1.03 million nodes and 2.28 million edges with zero dangling edges. Why not Neo4j: the questions are two to four hops in batch, and one copy keeps one set of permissions.
- Answer the brief's example on the slide: contract, then project, then the completion-report passage, with time deciding whether a lesson is an explanation or a precedent.

## Slide 3. AI methods

- Duration model. Start with the trap: the feed starts in FY2020, so old tenders look slow and new ones look fast, and a naive test says tenders got twice as fast. I trained only on cohorts that can be fully observed.
- LightGBM quantiles for P10, P50 and P90, then a conformal step because the raw interval covered 68% instead of 80%. After it, 80.7%.
- Re-bidding risk: I looked, and only 1.3 to 1.5% of contracts show a second tender notice. I report the rate instead of modelling noise, and model "slow tender" instead: ROC-AUC 0.747 against 0.584 for the peer rate.
- Agent: input guard from a different model family, a planner limited to six tool calls, five tools, a writer, and then code that checks the brief. The model is never the last check.
- Read the excerpt aloud. The timeline sentence cites a benchmark row; the rainy-season risk cites a completion-report passage. A reviewer can open both.
- Precedents: only close ones are shown, 0 to 5, by a rule on two similarity scores. 82% of cited precedents are relevant, up from 74%, and a package with nothing comparable gets none instead of five weak ones.
- forecast_timeline: honest finding. From the package fields alone the model is no better than the peer group (91 vs 85 days on 20 cases, and 17 of those were in training, so indicative only). With the project id it is 80, with real notice facts 60. So the brief asks for those details.
- Tender checks: 672 of 1,939 international tenders were advertised for less than the Regulations' 30 business days; they drew fewer bidders (4.9 vs 5.6) and more single-bidder outcomes (28.5% vs 20.3%). Correlation, not proof, and part of it is the publication date on the Bank site.
- Early warnings: 1,340 active projects, 73 red and 238 amber, each with its reasons. A weak mid-term ISR rating went with IEG-unsatisfactory 23.8% of the time vs 14.0%.

## Slide 4. Trust

- Lead with the leak, because it shows how I test. The registered @champion was refit on all data after evaluation, which is normal before deployment. Scored on the test tenders it gets 50 days and 95% coverage, because it has seen them. So every evaluation number comes from a refit at the cutoff: 75 days vs 88 for the peer lookup, coverage 81% vs 77%.
- The backtest replays 300 real tenders on their notice date with everything later hidden: 87 days (CI 77-98) vs 100; slow-flag AUC 0.74 vs 0.58; the model does not beat the peer table for consulting (134 vs 127), so the brief leads with the peer group there.
- Lessons: retrieved passages named a problem that the project's own completion report says happened in 38% of cases vs 8% for random passages.
- Be straight about the evaluation size: 20 packages, and an LLM judge that agreed 90% of the time with 30 reference labels made by an AI agent during the build and is not deterministic. Evaluation labels come from a three-tier escalation: code decides what it can, a panel of three judges from different model families labels the rest, and disagreements go to an AI adjudicator that records its evidence. The pilot's first job is a larger labelled set with procurement specialists, who also validate these labels.
- Weak spots, said plainly: 19% of packages get no precedent; on the final labels 5 of the 30 full briefs contain an unsupported claim, two of them confirmed against the data (a precedent called "same project" that is not, and an overstated firm-count range); a rule-based relevance check failed (kappa 0.21), so relevance needs a judge or a person.
- Conflicting evidence is the most interesting finding. Half of the projects IEG rated unsatisfactory still looked satisfactory in their last ISR. So the platform cannot just "pick the best source"; the source depends on the question. Outcome: IEG first. Current status: the newest ISR. Both sides are always shown with a flag.
- Data gaps: contract amendments, milestones and payments are not public (production would read STEP, Client Connection, PRAMS); no CPIA; awards only from FY2020; 300 of about 8,100 ICRs. Plain-text chunking had lost 26.8% of table rows in PADs; the table-aware parser fixes that, though it is worse at rank 1 (5 vs 8 of 12). Each gap has a stated workaround in data_gaps.md.

## Slide 5. Rollout

- The loop is real, not a diagram: Change Data Feed on nine tables, the graph updated by one MERGE, and the result equals a full rebuild row for row. Re-embedding is driven by content hashes.
- Retraining needs a reason and data: drift, error or age, plus at least 1,000 new labelled contracts. Promotion is an alias move after a challenger beats the champion on the same window, so rollback is one alias move.
- Pilot in three phases with go/no-go thresholds. Phase 0 shadow mode is where the hard trust KPIs must pass before any user sees an answer.
- KPIs: planning cycle time baseline 160 days today; compare pilot hubs with similar non-pilot hubs, because durations depend on much more than this tool.
- Close: what I would do in the first 90 days. Full ICR and PAD corpus, an amendment feed, the labelled evaluation set with specialists, and shadow mode.

## Likely panel questions

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
    - It earns its keep: the adjudicator overturned 7 of 24 panel majorities and confirmed 2 real errors in the agent's briefs from the data, a precedent wrongly called "same project" and an overstated firm-count range. Final numbers: entity resolution precision 1.00 and recall 0.90 on 97 decided pairs; an unsupported claim in 5 of 30 briefs.
    - Next: independent validation by procurement specialists is part of the pilot plan. Their labels become the next evaluation set and a check on the panel itself.
