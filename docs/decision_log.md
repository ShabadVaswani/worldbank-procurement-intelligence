# Decision log

Original "How it was built and tested" notes for each notebook, kept verbatim for reference. Each notebook now opens with a condensed "Key design decisions" table that links here.

---

# p01_ingest_awards

## How it was built and tested

**Step 1 — Is there a bulk file?**
- **Question:** is there a CSV/JSON bulk download that is faster than about 300 paged calls of 1,000 rows?
- **What we found:** the old Socrata CSV link for this dataset now redirects to FinancesOne and returns 404. But the API itself accepts big pages: `top=50000` returned 50,000 rows (52 MB) in about 6 seconds.
- **Decision:** page with 10,000 rows (30 calls of about 10 MB): close to bulk speed, small enough to retry cheaply. The API answered HTTP 429 "Try again in 24 seconds" once during probing, so the retry helper reads that hint.

**Step 2 — What is one row?**
- **Question:** what makes a row unique, so that `MERGE` has a key?
- **What we found:** 295,058 rows, 282,890 distinct `wb_contract_number`s. A contract with a joint venture has one row per member (8,864 contracts have 2 to 10+ rows). `(wb_contract_number, supplier_id)` is unique; one row has no `supplier_id` (its supplier text is a broken fragment, "EMPHNET)").
- **Decision:** key = SHA-256 of `wb_contract_number | supplier_id | supplier`, which stays unique even for that row.

**Step 3 — Re-runs and withdrawn records**
- **Question:** what happens on the next run, when most rows are unchanged and a few were corrected or withdrawn?
- **What we found:** `as_of_date` changes every day on every row, so hashing the whole row would rewrite the table daily.
- **Decision:** `_row_hash` covers the business columns only. Changed rows are updated, unchanged rows are left alone, and rows missing from a full snapshot get `_removed_at_source` (a soft delete). The notebook runs the same `MERGE` twice to prove the second run changes nothing.

---

# p02_ingest_notices

## How it was built and tested

**Step 1 — Plain offset paging cannot reach most of the data**
- **Question:** can we page through all 423k notices with `rows` and `os` (offset)?
- **What we found:** no. The API sits on Azure Cognitive Search, and an offset above 100,000 fails with "Value must be between 0 and 100000 ($skip)". A simple loop would silently stop at about a quarter of the notices. Pages are also capped at 1,000 rows.
- **Decision:** split the work into partitions that each hold fewer than 100,000 notices.

**Step 2 — How to partition**
- **Question:** which filter splits the data reliably? We wanted a date filter (only notices from 2018 are needed).
- **What we found:** the date parameters (`strdate`/`enddate`, `fq=noticedate:[...]`, `noticedate_exact`) are ignored or rejected. The facet filter `project_ctry_name_exact` works: 184 values whose counts add up **exactly** to the total, the largest being India with 47,452.
- **Alternatives considered:**
  - *Date windows* (the preferred design): split adaptively, halving any window that returns more than 100,000, and reconcile the windows' sum with the total. Not possible here, because the API ignores date filters.
  - *Id ranges or `id % n`*: also even and complete, but the API offers no range or modulo filter on `id`; splitting after download does not help, because the full set cannot be downloaded in the first place.
- **Decision:** one partition per project country, the only filter the API honours. The 2018 cutoff is applied by ordering instead (Step 3), and a completeness check against the total guards the gaps a facet split can leave (Step 5).

**Step 3 — A stable order, and the 2018 cutoff**
- **Question:** how do we page without skipping or repeating notices, and stop at 2018?
- **What we found:** the default order is by notice date, which has many ties, so the same offset can return different rows on two calls. Sorting by `id` is unique, and ids are issued in time order (`OP00000005` is from September 2005; about 50k ids predate mid-2018).
- **Decision:** sort by `id` newest first and stop a country when a whole page is older than 2018-01-01. Newest-first also tolerates notices published *during* the run: a new notice pushes everything down by one, which repeats a row (removed by the `MERGE` key) but never skips one.

**Step 4 — Page size and politeness**
- **Question:** how big should a page be?
- **What we found:** 1,000 rows with `notice_text` took 17 s once and 3 s another time; 500 rows consistently took about 2 s (about 2 MB).
- **Decision:** 500 rows per page, 4 countries in parallel, retries with exponential backoff. Every page is saved as a file, so a restart skips finished pages and finished countries.

**Step 5 — Notices without a country**
- **Question:** do the country partitions still cover everything on a later run?
- **What we found:** no. On the first run the facet counts added up exactly to the total; on a re-run about 20 hours later 200 notices were missing from every facet. They were recent notices published without a project country (184 of the newest 1,000 had none; the last of the 200 was found about 37,500 notices deep). The completeness assert caught it.
- **Decision:** measure the gap (total minus facet counts) and read the unfiltered feed newest-first until that many country-less notices are saved, instead of asserting that the gap is zero.

---

# p03_silver_model

## How it was built and tested

**Step 1 — Is the amount per supplier or per contract?**
- **Question:** a joint-venture contract has one row per member, each with `supplier_contract_amount_usd`. Is that the member's share, or the contract value repeated?
- **What we found:** in 7,083 of the 8,864 multi-supplier contracts every row carries the identical amount. In the other 1,781 the two values differ by a fixed ratio, almost always exactly 1.0303 or 1.0003 — a conversion artefact, not a split. Example: contract 1543858 lists AIRES INGEGNERIA and ALL INGEGNERIA, both at US$161,538.89.
- **Decision:** the amount is the **contract value repeated per member**. `contracts.contract_amount_usd` holds it once (the maximum of the rows, with `amount_spread_ratio` kept as a quality flag). Summing the raw column would double-count every joint venture.

**Step 2 — Contract attributes really are contract-level**
- **Question:** can project, method, category, dates and reference move from the row level to one row per contract without losing information?
- **What we found:** for all 282,890 contracts each of these columns has exactly one value (re-checked below in the quality table).
- **Decision:** `contracts` holds them once; `contract_suppliers` keeps only what varies by member.

**Step 3 — Country codes do not line up**
- **Question:** does the awards feed's country code join to the governance indicators?
- **What we found:** the feed uses the Bank's own codes. DR Congo is `ZR`, Serbia `YF`, Yemen `RY`, Timor-Leste `TP`, West Bank and Gaza `GZ`, while the indicators use ISO (`CD`, `RS`, `YE`, `TL`, `PS`). Côte d'Ivoire and Somalia rows arrive with **no code at all** (4,972 and 2,837 rows). Regional programmes have codes such as `3W` (Western and Central Africa). The notices feed only has names, with its own spellings ("Turkey", "Türkiye", "Vietnam", "Somalia").
- **Decision:** one crosswalk (`proc_intel.countries`) maps every code and name to ISO alpha-2, or to the Bank's regional code. Without it, five borrowers would silently lose their governance indicators.

**Step 4 — Who is a supplier?**
- **Question:** is `supplier_id` an identity?
- **What we found:** individual consultants are anonymised: supplier "INDIVIDUAL CONSULTANT" with a 16-character hashed id (65,121 rows). Otherwise `supplier_id` is a registration id: stable in spelling for most ids, but one firm often holds several ids (6,648 names occur under more than one id).
- **Decision:** `suppliers` has one row per `supplier_id` (with a flag for anonymised individuals); grouping ids into real firms is entity resolution, done in `p04`. One award row has no id (its supplier text is a broken fragment); it gets a surrogate id `NOID-<hash>` so the bridge keeps its key.

**Step 5 — Award notices name the losing bidders too**
- **Question:** what is inside a Contract Award notice besides the winner?
- **What we found:** the HTML lists awarded, evaluated and rejected firms, each as "NAME (supplier id)", plus the date the award notification was issued and the contract duration. Some notices also carry beneficial-ownership tables naming private persons.
- **Decision:** parse firm ids, names, countries and roles into `notice_bidders` (a competition signal for phase 2), and **never** read the ownership tables. Bidders that never won a contract in the awards feed still get a `suppliers` row, so the foreign key holds.

**Step 6 — Keys that are declared but not enforced**
- **Question:** what do primary and foreign keys guarantee on Databricks?
- **What we found:** Unity Catalog keys are informational. Nothing stops a duplicate or an orphan from being written.
- **Decision:** declare them (documentation, lineage, optimizer hints) **and** count duplicates and orphans in the quality table at the end of this notebook.

---

# p04_supplier_resolution

## How it was built and tested

**Step 1 — How reliable is `supplier_id`?**
- **Question:** can we trust "same id = same firm", and "different id = different firm"?
- **What we found:** the second is false: 6,648 names appear under more than one id. The first is *mostly* true: of the ids that carry several names (awards plus award notices), about 97% are spelling variants. The dissimilar rest are partly acronyms or translations of one firm ("SAHE" = "SOCIETE AFRICAINE D'HYDRAULIQUE ET D'ELECTRICITE"), partly two parties under one id ("SANJEEV KUMAR" / "SUSHIL KUMAR"). The first run trusted every shared id: ENTREPRISE SATU-SA (Niger) shared ids with eight partner firms, which chained nine firms (BAANA, EGAM, ENISAB, ...) into one entity of 77 records.
- **Decision:** a shared id links two names only if they are similar (cosine >= 0.5) or one is the other's acronym; otherwise the id is split and follows its most used name. The splits are counted below.

**Step 2 — Choosing the similarity score**
- **Question:** token-set ratio, Jaro-Winkler, or TF-IDF character n-grams?
- **What we found:** the variants are typos ("PRICEWTERHOUSECOOPERS"), spacing ("ABCCONSULT"), word order and extra words ("(DWP GROUP)"). Jaro-Winkler rewards a shared prefix, so every "CONSTRUCTION ..." pair scores high. Token-set ratio scores 1.0 whenever one name is contained in the other, so "AGRITCHAD" would match "GROUPEMENT SETI AGRITCHAD".
- **Decision:** cosine of TF-IDF weighted character trigrams. Trigrams tolerate typos and spacing, cosine ignores word order, and TF-IDF down-weights words every supplier uses. Jaro-Winkler and token-set ratio are kept as explanatory columns only. Comparing only within the same supplier country (blocking) keeps the work small (minutes for 370k records on one node) and matches how firms register: "PWC ALBANIA" and "PRICEWATERHOUSECOOPERS" (Poland) are different legal entities.

**Step 3 — The first threshold produced giant clusters**
- **Question:** with a plain cosine threshold, what do the clusters look like?
- **What we found:** at 0.6 the largest cluster had 2,540 records, at 0.7 still 433. Chains of near-neighbours joined different firms: Vietnamese names that share a long generic phrase ("CONG TY CO PHAN XAY DUNG VA THUONG MAI ..." = construction and trade joint-stock company) and 12 provincial "LAND REGISTRATION OFFICE OF <province> PROVINCE"s became one entity.
- **Decision:** a fuzzy link must also agree on the **distinctive words** — the words that are rare among that country's supplier names ("LAO CAI" vs "THAI BINH" do not). In the first prototype (award names only) this check raised precision on the labelled pairs from 0.73 to 1.00 at the same threshold and shrank the largest cluster from 433 records to a real firm.

**Step 4 — Personal names**
- **Question:** can two records named "ARUN KUMAR" be merged?
- **What we found:** no. One third of the records look like personal names (small works and supplies, many in India and Ethiopia). "AJAY KUMAR" alone appears under 24 ids; the labelled "ARUN KUMAR" pair are contractors in two different forest divisions. But "UASSI MWEMA" (Comoros) is the same contractor in two contracts of one project.
- **Decision:** a personal-looking name whose every word also appears in more than 3 *other* names of that country (names without its remaining words: ARUN SHARMA, RAJ KUMAR, ...) gets **no name links**; rare personal names may still match exactly. The first version counted all names containing the word, so a firm's own spelling variants made it look common ("SEC DIARRA", an audit firm with 40 ids, was kept apart); counting only names without the other words fixed that. Fuzzy links need the distinctive words to match at 0.9, so one-letter differences such as "KARANJEET" / "CHARANJEET" stay apart.

**Step 5 — Measuring it**
- **Question:** how good is the result, in numbers?
- **What we found:** 100 labelled pairs, drawn from every similarity band (0.3 to 1.0) so that hard and easy cases are both present, plus a random audit of 40 produced fuzzy links; both label sets were made by an AI agent during the build. Results are in sections 4 and 7. p15 relabels the same 100 pairs with the project's three-tier escalation (code checks, a panel of three LLM judges, an AI adjudicator that records evidence) and reports the final figures: precision 1.00 (95% CI 0.90-1.00) and recall 0.90 (0.77-0.96) on 97 decided pairs.
- **What else we found:** the strict word match rejected true variants that add one word ("ECONOMIC CONSULTING ASSOCIATES LIMITED (ECA)", "PRICEWATERHOUSECOOPERS ... (PWC INDIA)", "... (LEAD)") or differ in singular/plural of a common word ("OMNI SOLUTION TECHNOLOGIE" vs "OMNI SOLUTIONS TECHNOLOGIES"). Now one extra word on the longer side is allowed, "(LEAD)" markers are dropped, and singular/plural share their generic status.
- **Decision:** threshold 0.70 (the sweep in section 4 shows the trade-off). These labels also chose the threshold, so the random link audit in section 7 is the less biased precision estimate.

---

# p05_link_notices_awards

## How it was built and tested

**Step 1 — How far does the exact reference go?**
- **Question:** what share of contracts can be matched to a tender notice by reference alone?
- **What we found:** exact project + reference matches found tender notices for about 61,500 contracts; the STEP activity id added only about 2,300 more (most STEP references are copied unchanged). About 6,000 links had the notice published **after** the contract was signed: a reference re-used for a later round, not the tender of this contract.
- **Decision:** keep both tiers; links where the notice comes after signing are stored but flagged, and never used for durations.

**Step 2 — Fuzzy reference matching was too loose**
- **Question:** can a string-similarity threshold catch the remaining typos?
- **What we found:** at ratio >= 0.9 most extra matches were lot markers ("17B/W/DNAAS/2018" for tender "17/W/DNAAS/2018"), but some were different packages one character apart ("TCP/CON/QCBS/B1/G" vs ".../B1/D", "ENU-02-22" vs "ENU-03-22").
- **Decision:** replace the ratio with an exact structural rule: the references must be equal after deleting one block of 1-3 **letters** (never digits) from the longer one. Implemented as an equi-join on generated deletion keys, so no pairwise comparison is needed.

**Step 3 — Description matching needs a guard**
- **Question:** for contracts with no matching reference, does the description find the tender?
- **What we found:** even at similarity >= 0.9, descriptions matched the wrong package where one project tenders near-identical packages ("Civil Work Package (CWP) 7" vs "CWP 8", "Fish Landing in Brgy. Taruk" vs "Brgy. Tapian"). Where the contract reference is the borrower's own contract number (no STEP id) and the notice carries the STEP reference, the description is the only bridge, and the matches read correctly ("Audit externe des comptes du projet PRAPS-II NE ...").
- **Decision:** use descriptions only for contracts **without** a STEP id, require >= 0.8 similarity and a clear margin over the second-best notice, and measure the tier separately in the hand audit.

**Step 4 — Award notices share references across lots**
- **Question:** can award notices be linked the same way?
- **What we found:** by reference alone, award notices and contracts formed about 980,000 pairs (section 3 shows the counts): one reference is shared by all lots and call-offs of a tender (one reference appears on 188 contracts).
- **Decision:** an award link is kept when the notice's awarded supplier id is one of the contract's suppliers (confirmed), or when the pair is one-to-one and the notice names no awardee (nothing contradicts it). Among one-to-one pairs whose notice names an awardee, the share confirmed is the automatic precision check for reference matching.

**Step 5 — What can be timed?**
- **Question:** which contracts should have a tender notice at all?
- **What we found:** most contracts are never publicly advertised: Request for Quotations, direct selection and individual consultants make up about 80% of contracts.
- **Decision:** coverage is reported per competition level, and the timeline model in phase 2 should be trained on openly competed contracts, where the notice is the norm.

---

# p06_knowledge_graph

## How it was built and tested

**Step 1 — Which entities become nodes?**
- **Question:** what grain should each node have?
- **What we found:** suppliers must be **resolved entities**, not supplier ids: Ernst & Young India alone holds many ids, and an id-level graph would split its history.
- **Decision:** supplier nodes are `supplier_entities` from `p04`; notices and contracts keep their own grain. Document chunks come from the outcome project's `silver.rag_chunks` (453 projects), linked by `project_id`; only chunks of projects that appear in the procurement data become nodes (the printed count shows the overlap).

**Step 2 — Typed properties without a schema per node type**
- **Question:** how can six node types share one table and still be queryable?
- **What we found:** a wide table with every attribute of every type would be mostly empty, and one table per type would make generic traversals awkward.
- **Decision:** common columns (`node_id`, `node_type`, `name`) plus a `properties` map of strings for type-specific attributes. Numbers stay one join away in the silver tables when exact types are needed.

**Step 3 — GraphFrames on this runtime**
- **Question:** can GraphFrames run here, or do we need recursive SQL?
- **What we found:** the GraphFrames Python package ships with the ML runtime (checked in `p00`); whether its JVM library loads is tested below.
- **Decision:** the demo questions are written as DataFrame joins, which work everywhere; one is repeated as a GraphFrames motif when the library is available, to show both styles give the same answer.

---

# p07_tender_risk_model

## How it was built and tested

**Step 1 — Which tenders can be used at all?**
- **Question:** is the duration of every timed contract a fair training example?
- **What we found:** no. The awards feed holds contracts signed from 2019-07-01 to the snapshot, so the median notice -> signing time by notice year is 465 days for 2018 (only slow tenders reached the feed), 154-189 days for 2019-2024, 135 for 2025 and 95 for 2026 (only fast tenders are signed yet). A plain "test on the newest year" split would report that tenders became twice as fast.
- **Decision:** model notices from 2019-07-01 to 730 days before the snapshot, with the duration capped at 730 days (1.5% took longer). Within that window every duration up to the cap is observable. Newer notices are scored, not trained on, and the survival view in section 9 handles them as censored.

**Step 2 — What does "re-bidding risk" mean in this data?**
- **Question:** can re-advertisement be the risk target?
- **What we found:** 1.3% of training contracts (1.5% of test) have more than one tender notice linked, and only 135 of 81,600 (project, reference) pairs of tender notices repeat exactly; a re-tender under a new reference is invisible, and only 10 IFB notices carry a "Revised" status.
- **Decision:** the risk target is **slow**: duration above the P75 of the same method x category in the training years. Base rate 25.0% in training, 22.4% in the test notices (newer tenders are faster). Re-advertisement rates are reported, not modelled.

**Step 3 — Which inputs are known on the notice date?**
- **Question:** which candidate features would leak the outcome?
- **What we found:** the contract amount is only known at award and no pre-award estimate exists; review type is not on the notice, so open notices could not be scored with it; the outcome-model risk score exists only for projects still active in 2026, so its presence reveals the project's future.
- **Decision:** all three are left out. Governance indicators are taken for the year before the notice, and market history for the 36 months before the notice month.

**Step 4 — Does the model beat the lookup table?**
- **Question:** is a model better than the peer-group quantiles an analyst would look up?
- **What we found:** on all four rolling-origin folds (pinball loss of the median 38.1-42.1 vs 44.5-49.2 for the peer table) and on the test notices: MAE 76 vs 88 days, mean pinball 24.6 vs 29.1. But the raw P10-P90 interval covered only 68% of test outcomes (target 80%): 16% fell below P10 and 15% above P90.
- **Decision:** calibrate the interval with conformalised quantile regression on the last training half-year (the lower bound moves down by 0.136 and the upper bound up by 0.112 log-days, about 13% and 12% in days). Test coverage is then 80.7% (9.8% below, 9.5% above), with the interval still 12% narrower than the peer table's. The model is registered as `@champion`.

**Step 5 — Is the slow-tender score useful, and is it calibrated?**
- **Question:** does the classifier rank tenders better than the peer group's historical slow rate?
- **What we found:** ROC-AUC 0.747 vs 0.584, PR-AUC 0.494 vs 0.295 (base rate 0.224). The predicted probabilities run slightly high in the lower deciles, consistent with the lower base rate of the test notices.
- **Decision:** publish the probability with the threshold it refers to; recalibrating on recent data is the first maintenance task.

**Step 6 — Can "not signed yet" be told apart from "never signed"?**
- **Question:** can unsigned notices be treated as censored in a survival model?
- **What we found:** for young notices, yes: the Kaplan-Meier share signed within 180 days is 0.30-0.38 for every notice year 2019-2025, while the naive median of the observed durations falls to 144 days (2025) and 91 (2026). For old notices, no: the curves flatten at 0.56-0.67, the share of notices p05 manages to link, so cancellations and link failures look the same.
- **Decision:** use KM to compare timing across groups and cohorts (median among linked notices: consulting 319 days, works 132, goods 127, non-consulting 125), not to estimate how many tenders fail. The Weibull AFT gives readable time ratios (Request for Bids 0.42x the time of the other open methods, which are mostly consultant selections; Latin America 1.28x vs Europe and Central Asia; +1.2% per advertising day); its test concordance (0.694) is below LightGBM's (0.721).

---

# p08_procurement_agent

## How it was built and tested

**Step 1 — Contract search: embeddings for everything, or keywords?**
- **Question:** what is a cost-sane way to find similar past contracts among 282,890?
- **What we found:** embedding every description would take about five hours at the workspace's embedding rate limit (about 15 texts per second, shared with every other job). TF-IDF over all of them builds in about a minute. A first TF-IDF version with a stored unigram + bigram vocabulary made the driver process balloon while counting the vocabulary, on a 16 GB driver shared with other jobs; hashing the terms (no stored vocabulary) kept the whole index at about 70 MB.
- **Decision:** hashed TF-IDF over all contracts, then GTE re-ranking of only the best 30 per query. Measured on the 20 evaluation packages (section 5b): precision@5 rose from about 0.6 with TF-IDF alone to about 0.75 with re-ranking (exact values in section 5b).

**Step 2 — Which completion-report passages are lessons about procurement?**
- **Question:** can headings and keywords pick the procurement-relevant passages out of 100-page reports?
- **What we found:** the first rules kept only 3,768 passages and mistook numbered paragraphs ("86. The concerned government agencies were ...") for headings, so passages got nonsense section names. All-capitals headings with commas ("IV. BANK PERFORMANCE, COMPLIANCE ISSUES, AND RISK ...") were then rejected by the fix, which moved the fiduciary passages under the wrong section. Some reports are Windows-1252, not UTF-8, and curly quotes turned into replacement characters. Monitoring-and-evaluation sub-sections sit inside the "compliance" section but say nothing about procurement.
- **Decision:** numbered digit headings must be capitalised and comma-free (all-capitals Roman or letter headings may contain commas); a cp1252 fallback; M&E sections are excluded. Result: 4,495 passages from 300 reports, mostly key factors during preparation and implementation, lessons, fiduciary compliance and quality of supervision. Unit tests cover each of these cases.

**Step 3 — A supplier profile in seconds**
- **Question:** can the knowledge graph answer "who is this firm and who does it compete with?" inside an interactive loop?
- **What we found:** Spark joins over the 2.3 million edges took 26 to 74 seconds per profile on the shared cluster, and caching the edges held driver memory for the whole session.
- **Decision:** the 970,000 bid and award edges are loaded once into integer-coded arrays (a few MB); a profile then takes about 4.5 seconds, mostly the two node look-ups. The co-bidder answer is identical to the join version.

**Step 4 — Tool-calling quirks of the planner models**
- **Question:** do the two candidate models call the tools correctly?
- **What we found:** both return well-formed tool calls and accept the strict JSON schema. Qwen 3.5 sends numbers as quoted strings (`"k": "5"`); the argument check rejected them ten times in one run and the coverage check had to add two core tools. Both models pass countries as names ("Kenya"), not codes.
- **Decision:** numeric strings are converted for integer parameters, and every tool resolves country names and method codes; after that fix the same run made 4 calls of its own and needed no forced tool. The model comparison (section 3) is run after these fixes.

**Step 5 — The shared embedding rate limit**
- **Question:** can the agent embed 31 texts per query while other jobs embed too?
- **What we found:** one request of 31 texts was refused with HTTP 429 eight times in a row: the workspace limit counts every text as a query and is shared by every user.
- **Decision:** batches of 8 and a pacing clock at 10 texts per second shared by all threads, with longer backoff.

**Step 6 — What the groundedness judge needs to see**
- **Question:** is "not grounded" from the judge a real hallucination?
- **What we found:** in a trial, the judge marked a brief ungrounded partly because it restated the package itself ("speedboats ... between islands"), which is in no tool record.
- **Decision:** the trace's evidence span also carries the package text as a non-citable "user input" document, so the judge checks the brief against everything the agent was given.

**Step 7 — The benchmark table belongs to another component**
- **Question:** how can the agent use the risk component's benchmarks without depending on its code?
- **What we found:** `proc_gold.tender_benchmarks` appeared while this notebook was being built, with the same four peer-group levels; its `slow_rate` column is a decimal type.
- **Decision:** the tool reads only its documented columns (and stops with a clear message if one is missing), casts decimals, and falls back to computing the same peer groups from `tender_timelines` when the table does not exist.

**Step 8 — Fewer precedents when nothing comparable exists**
- **Question:** the first version always listed five precedents, even for speedboats to carry laboratory samples (0 of 5 relevant). Which score says when a candidate is close enough?
- **What we found:** on 200 judged pairs (top 10 re-ranked candidates of the 20 evaluation packages; 74% relevant), the GTE re-rank cosine separates relevant from not relevant best (ROC-AUC 0.77; TF-IDF 0.66; same method 0.56), but its level moves with the query: the best candidate for the technical-education study scores 0.70 and is relevant, the best for the speedboats scores 0.73 (sample-shipping kits) and is not. Any cosine-only cut that drops the speedboat candidates also empties briefs that had five relevant precedents (at 0.74, four packages lose all precedents and only one of them had nothing relevant). The speedboat look-alikes share few words with the package: the three closest in meaning have TF-IDF cosines of 0.05 to 0.07.
- **Decision:** a precedent needs re-rank cosine >= 0.68 **and** TF-IDF cosine >= 0.08, with lower-ranked candidates filling freed places; the pair has the best F0.5 on the grid (precision 0.83 vs 0.76 for an unfiltered top 5, recall 0.86), a leave-one-package-out check picked the same pair for 19 of 20 packages (out-of-fold precision 0.81), and only the speedboat package is left with none. The gain is modest; the writer is also told to list only genuinely similar records, and the code accepts only records the search marked as close.

**Step 9 — A forecast for a tender that has not been advertised yet**
- **Question:** the risk component's model needs 27 features known on the notice date; a planning brief comes before the notice. What can be filled in honestly?
- **What we found:** country, method, category, market history and governance are known at planning time; the advertising period, notice type, length and language are not, and project facts only when the user gives a project id. The training cohort's medians are clear by method x category (Request for Bids works: 28 days advertising, 7,862-character notices; QCBS: 18 days, expressions of interest). Methods the model was never trained on (direct selection, individual consultants) cannot be scored at all.
- **Decision:** `proc_intel.forecast.planning_features` fills each unknown with a documented default and lists it in the record's `assumptions`; unknown project facts stay missing, as LightGBM was trained with missing values. A method or category outside the training data returns an unscored record and the brief falls back to the peer group, saying so. Section 5f measures what the defaults cost against the real notice facts.

---

# p09_conflicting_evidence

## How it was built and tested

**Step 1 — Where do the ratings live?**
- **Question:** which source gives the last ISR rating, the ICR self-rating and IEG's rating most cheaply and reliably?
- **What we found:** the outcome project's `bronze.ieg_ratings` has IEG's outcome for 6,906 ICR Reviews but **no ICR self-rating**, and its document chunks are only appraisal documents (no ISRs, no ICRs). The Projects API carries no ratings. The Documents API filters by document type (`docty_exact`), and every ISR and ICR Review has a plain-text rendering.
- **Decision:** list each project's ISRs, ICRs and ICR Reviews from the Documents API and read the ratings from the text. The ICR Review prints the ICR's rating and IEG's rating side by side, so one document gives both, and IEG's rating read from the text can be **checked against** `bronze.ieg_ratings` (a free accuracy test of the parser).

**Step 2 — The rating tables are fixed-width columns with wrapped cells**
- **Question:** can a line regex read the ratings?
- **What we found:** for ISRs mostly yes (`Progress towards achievement of PDO   <previous>   <current>`), but in ICR Reviews a cell such as "Moderately Satisfactory" is often split over two lines, *above and below* the row label, while the neighbouring cell sits on the label line. A line regex reads the wrong column.
- **Decision:** one parser for both tables: take the column positions from the header line, assign every word to the column under which it starts, and read each column's text top to bottom for rating phrases. Placeholders (`---`, `Not Rated`) are matched too, so an empty cell cannot shift the next row's rating up. The "Reason for disagreement" column is cut off, because its free text contains rating words.

**Step 3 — The first full run found two layout variants**
- **Question:** does the parser read the real documents, not just the probes?
- **What we found:** run 1 read IEG's outcome correctly for only 364 of 376 ICR Reviews, and for 91 of 400 projects the newest ISR had "no ratings". Two causes: (1) in some ICR Reviews the IEG cells start up to 5 characters **left** of the "IEG" title, so "Moderately" fell into the ICR column and IEG kept only "Satisfactory" (all 12 mismatches had that pattern); (2) ISRs from 2024 use a new template: the header says "Previous / Current" instead of "Previous Rating / Current Rating", and each rating is prefixed by an icon character from the Unicode private-use area. Falling back to an older ISR would have silently replaced the *last* ISR with an earlier one for a quarter of the sample.
- **Decision:** a column starts 8 characters before its title (but never before the second word of the previous column's rating), the header regex accepts both templates, and private-use characters are replaced by a space (which keeps the column offsets). Both layouts are now unit tests; section 4 re-checks IEG against the dataset.

**Step 4 — A bounded, unbiased sample**
- **Question:** which projects?
- **What we found:** 1,368 closed projects in the procurement data have an IEG outcome rating (evaluated FY2019-2027).
- **Decision:** 400 of them in hash order of `project_id` (reproducible and unrelated to the ratings, so the disagreement rates are not biased by the selection). For each: the last ISR, the ISR nearest the middle of the supervision period, and the ICR Review. If a document has no readable ratings block, the next candidate of the same role is tried and counted.

**Step 5 — Resolution as a policy, not a pick**
- **Question:** what should the agent say when sources disagree?
- **What we found:** the question decides which source is authoritative. For "how did the project do", IEG's independent ex-post rating is the Bank's official verdict; for "how is it going now", only the latest ISR speaks to the present.
- **Decision:** a documented hierarchy per question type, every other record returned as supporting or conflicting with its date and citation, a flag and a confidence label. Tested on hand-made cases in `tests/test_evidence.py`.

---

# p10_continuous_learning

## How it was built and tested

**Step 1 — Is Change Data Feed already on?**
- **Question:** can downstream steps read "what changed since yesterday" from the tables?
- **What we found:** no table in `proc_bronze`, `proc_silver` or `proc_gold` had `delta.enableChangeDataFeed` set. The bronze tables are loaded with `MERGE` and a row hash, so their change feed will contain only real changes. Silver and gold are rebuilt with `overwrite`, so their change feed would list every row as deleted and re-inserted.
- **Decision:** turn the feed on for all of them (it is a table property, no data changes), read it on bronze, and make the downstream update incremental with `MERGE` on the affected keys. Silver steps that still overwrite are the next candidates for the same treatment.

**Step 2 — How big is a real day?**
- **Question:** is incremental processing worth it?
- **What we found:** section 2 reads the newest notices from the API and compares them with bronze; a day brings a few hundred notices against about 417,000 stored ones (silver notices per notice date in October 2026: 21 to 226).
- **Decision:** for the knowledge graph, recompute only the neighbourhood of changed notices.

**Step 3 — Proving incremental = full rebuild without touching production**
- **Question:** how can the incremental path be tested on real data while two other components read the production tables?
- **What we found:** writing a test batch into the production silver and gold tables would change what the delay model and the agent read mid-run.
- **Decision:** a replay in a separate schema `proc_sandbox`: yesterday's state = silver notices without the last 7 days and with 100 older notices in an earlier "draft" version (half without a project id, half filed under a wrong project); today's batch = the held-back notices plus the corrected versions. The batch is merged, the change feed gives the affected notices, the notice neighbourhood of the graph is updated by one `MERGE`, and the result is compared with a full rebuild and with the production graph that `p06` built.

**Step 4 — Drift on durations is partly an artefact**
- **Question:** which windows should drift checks compare?
- **What we found:** cohorts by **notice** date make recent durations look short: a tender advertised last month appears only if it was already signed. Cohorts by **signing** date avoid that censoring.
- **Decision:** windows by signing date (current = the latest 12 months, reference = the 24 months before).

**Step 5 — Is the incremental path faster?**
- **Question:** what does incremental buy on this cluster?
- **What we found:** not in wall time at this size. Over two runs on the shared cluster the incremental update took 65-70 s and the full rebuild of the 1.36 million-edge neighbourhood 30-76 s: the incremental path still scans the whole link and bidder tables to find the rows of the changed notices, and the `MERGE` reads the whole target. What it does save is writes: 3,290 inserts and 50 deletes instead of rewriting 1.36 million rows, so downstream readers of the change feed see 3,340 changes instead of a full replacement.
- **Decision:** keep the incremental path for correctness of the change feed and for scale (the daily batch stays a few hundred notices while the tables grow), and before relying on it for speed, cluster the link, bidder and edge tables by `notice_id` / `src_id` (liquid clustering) so that finding the changed rows stops being a full scan.

**Step 6 — Freshness must ignore metadata commits**
- **Question:** how old is each table?
- **What we found:** the first version took the newest commit and reported every table as 0.5 hours old: the newest commit was this notebook's own `SET TBLPROPERTIES`.
- **Decision:** freshness = the newest *data* commit (write, merge, update, delete, create-as-select).

---

# p11_backtest

## How it was built and tested

**Step 1 — Which model is being backtested?**
- **Question:** can the registered `@champion` simply be scored on the test-period tenders?
- **What we found:** no. p07 refits the champion on the whole cohort, test period included, before registering it. Scored on the test notices it reaches a P50 error of 50 days and 95% interval coverage, against 75 days and 81% for the same recipe fitted without them: the leak a naive backtest would have reported as a result.
- **Decision:** the backtest refits the champion's recipe (features, hyper-parameters and rounds from its MLflow run) at the cutoff (model A), checks that it reproduces p07's logged test metrics (MAE within 1 day, coverage within 0.001), and adds a stricter model B trained only on tenders whose outcome was fully known on the cutoff date. The champion and the deployed benchmark table appear only as labelled in-sample contrasts. During the agent replays, the agent's own forecast tool is pointed at model A.

**Step 2 — Hiding the future from tools that have no date parameter**
- **Question:** how can the agent's tools be replayed "as of" a date without changing their code (another component owns it and was changing it at the same time)?
- **What we found:** every tool reads cached arrays: blanking the category of later contracts makes the search's own category filter skip them, and the passage matrix can be swapped for a filtered copy. A first version imported a helper with the same name as one in the agent's code; because `%run` shares one namespace, it silently replaced the agent's helper and the benchmark tool crashed.
- **Decision:** the swap lives in one context manager (`as_of`), every returned record is re-checked for its date and project after the call (`leak_violations`, the run stops on any hit), and `assert_core_intact()` fails if this notebook rebinds any name the agent's code defined.

**Step 3 — Does a metadata rule measure precedent relevance?**
- **Question:** can "same category, same method family, shared sector" stand in for a relevance judgement, so precedents can be scored without a model?
- **What we found:** no. It agrees with p08's 30 reference labels (made by an AI agent during the build) on 16 of 30 pairs (kappa 0.21) and with the LLM judge barely above chance (kappa about 0.1): it calls 28% of precedents relevant where the judge calls 63%. Both conditions are too strict: classroom blocks are built by social-protection and community-driven projects too, and a request for quotations for pickups is a fine precedent for a bid for pickups. The judge, checked again against agent reference labels on 23 pairs of this backtest's real notice texts, agrees on 20.
- **Decision:** the proxy is reported with its failure (and with each condition switched off), and the LLM judge is the relevance measure.

**Step 4 — A fair test for lessons**
- **Question:** how to tell whether retrieved lessons "would have warned" about what then went wrong, when nearly every project has some procurement trouble?
- **What we found:** only 20 projects with test-period tenders have a completion report yet. Taking a random tender per project put most replays in 2019-2020, when almost no completion report existed, so the test would only have exercised appraisal passages. Generic warnings ("procurement may be delayed") match almost anything.
- **Decision:** each project's last tender before its report is replayed, the judge's rubric counts generic warnings as "partial" only, and a random-passage control from the same visible pool is judged blind. Fifteen judge verdicts were checked by an AI agent without seeing the judge (agent reference labels): 13 agree, the two disagreements are about whether a project had any problem at all.

**Step 5 — Running on a shared cluster and a mobile connection**
- **Question:** what made the runs slow or fragile?
- **What we found:** the relevance judge is the slowest step (about 2,400 distinct pairs, about 4 s each at three threads); a dropped connection killed the local poller of a prototype run while the cluster kept working; Databricks autologging logged each LightGBM refit as a run in the agent's experiment.
- **Decision:** every judge verdict is cached in the volume under a hash of its prompt, so a re-run (for example after the agent changed) pays only for new pairs; autologging is switched off in this notebook.

---

# p12_document_parsing

## How it was built and tested

**Step 1 — Which library, on this cluster?**
- **Question:** what can read PDF layout on DBR 18 ML without heavy models?
- **What we found:** no PDF library is installed (PyMuPDF, pdfplumber, pypdf, camelot all missing). PyMuPDF installs from a wheel in seconds and gives, per text line, font size and bold flags, plus `find_tables()` for ruled tables. None of the 10 PADs carries PDF bookmarks, so the section hierarchy has to come from typography.
- **Decision:** PyMuPDF, pinned. Headings are lines at least 1 pt larger than the body font, or bold, that also look like titles; level 1 for ANNEX / Roman-numbered / all-caps titles, level 2 for "B. Fiduciary"-style sub-headings. OCR is not needed here (section 2 counts pages without a text layer) and is the documented fallback for scanned reports.

**Step 2 — Which table detector?**
- **Question:** PyMuPDF offers a "lines" strategy (ruling lines) and a "text" strategy (aligned words).
- **What we found:** on the first PAD the text strategy turned every page of prose into a 40-row "table"; the lines strategy found the real tables (costs, thresholds, procurement packages, risk matrices) but also layout frames: the datasheet drawn as one big box, acronym lists, paragraphs inside a frame.
- **Decision:** lines strategy plus a quality gate (at least 2 x 2 after removing empty rows and columns, 40% of cells filled, no paragraph-sized cells in a two-column frame). Tables that a page break cuts in two (same columns, at the top of the next page, no caption of their own) are merged, and a repeated header row is dropped.

**Step 3 — The first heading rules were too generous**
- **Question:** do the detected headings form a readable section tree?
- **What we found:** the first run took contents-page lines ("III. IMPLEMENTATION ARRANGEMENTS ......") and single bold table labels in the datasheet ("Total", "Annual") for headings, and Word template codes (`BASIC_INFO_TABLE`, `RESULT_FRAME_TBL_PDO`) leaked into headings.
- **Decision:** dot-leader lines are dropped as contents entries, an un-numbered bold heading needs 2+ words and a capital first letter, template codes are removed. The section tree of one document is printed in section 3 so the remaining errors are visible.

**Step 4 — A fair test of "the old chunks broke the tables"**
- **Question:** how do we tell, for a table row found in the PDF, whether the plain-text chunks kept it whole?
- **What we found:** matching rows by all their words says almost every row is "intact", because words like "procurement" or "2021" occur in every chunk.
- **Decision:** a row is identified by its **distinctive** tokens (words and numbers that occur in at most 3 of the document's old chunks). Intact = one old chunk holds 90% of them; split = only several chunks together do; missing = dropped. As a control the same test is run on ordinary narrative sentences, which the old chunker handled well.

---

# p13_tender_design_checks

## How it was built and tested

**Step 1 — What do notices actually state?**
- **Question:** can technical specifications and qualification criteria be read from the notices?
- **What we found:** IFB notices are short (median about 3,900 characters for English IFBs) and mostly point to the bidding document. In a 400-notice sample, about 75% mention bid security, 74% state national or international competition, but only about 7% print a turnover requirement and 3% a number of years of experience. Specifications and the full qualification criteria are in the bidding documents, which are not published as open data.
- **Decision:** check what the notices do carry (advertising period, market approach, package value, bid security, bid validity, electronic submission) and treat qualification thresholds as a small-sample check. The data gap is stated in `docs/data_gaps.md`.

**Step 2 — Rules first, a model only for the leftovers**
- **Question:** rules or an LLM for the extraction?
- **What we found:** the formats repeat ("Bid Security of US$ 22,000", "2% of the bid price", "Bid-Securing Declaration", "valid for 90 days"), so rules read most fields. The first currency rule read any three capital letters before a number as a currency ("FOR 3,000", "LOT 2"); currency codes are now a whitelist matched case-sensitively. About 30% of notices name bid security without a readable value (tables flattened into text, amounts in words).
- **Decision:** rules for all 400; Qwen 3.5 (thinking off, strict JSON schema) only for notices where the rules found a mention without a value, plus a random 40 of the others to measure agreement between rules and model. A model value never overwrites a rule value.

**Step 3 — Peers and policy**
- **Question:** what is "short" or "large"?
- **What we found:** the Procurement Regulations (7th edition, September 2025, para 5.36) set a minimum of 30 Business Days (about 42 calendar days) for open international competitive procurement; national competition follows national rules, so only peers can judge it.
- **Decision:** a policy check for international tenders, and peer checks everywhere: peers are notices of the same country (else region, else all) x category x market approach with at least 20 observations, over the cohort p07 also used (notices 2019-07-01 to 2024-10-13, fully observable).

**Step 4 — Does a flag matter?**
- **Question:** which checks are associated with worse outcomes?
- **What we found:** outcomes are only observable for tenders that ended in a signed contract in the awards feed; cancelled tenders are invisible, and the bidder count is the number of firms named in the award notice.
- **Decision:** compare flagged and unflagged notices on these outcomes with bootstrap intervals, by check, and read them as associations (a large package is also a complex one), not effects.

---

# p14_execution_monitoring

## How it was built and tested

**Step 1 — Is there a procurement rating in the ISR?**
- **Question:** the brief asks for procurement-specific supervision signals; do ISRs rate procurement?
- **What we found:** in the 400 last ISRs that p09 read (closed projects, 2017-2025), not one prints a "Procurement" rating line (older ISR templates had one; these do not). 398 of 400 print the SORT risk table, whose **Fiduciary** row (financial management and procurement together) gives the rating at approval, the last approved rating and the proposed one.
- **Decision:** the procurement signal from the ISR is the SORT fiduciary rating, next to PDO and implementation-progress ratings (previous and current in the same ISR, so a downgrade is visible from one document).

**Step 2 — Where is disbursement data?**
- **Question:** the Projects API has disbursement fields; are they usable?
- **What we found:** the Projects API's financial fields lag: for P160446 its disbursement (US$ 90.08 million on one loan) and closing date (30 June 2025) equal the FinancesOne statement of September **2024**, while the September 2026 statement says US$ 133.9 million and 31 December 2025. Its rating fields are lists without the ISR they came from, and it keeps no history. The FinancesOne statements of IBRD loans and IDA credits are monthly snapshots (end of period 30 September 2026) with original, cancelled and disbursed amounts and the current closing date per loan, and an older snapshot can be selected with a filter.
- **Decision:** disbursement and closing dates from FinancesOne (latest and two years earlier); the Projects API only for the lending instrument, which does not change. Disbursement lag is judged for investment projects only: development policy and Program-for-Results operations disburse in tranches or against results.

**Step 3 — Thresholds and the alert**
- **Question:** what counts as a warning?
- **What we found:** fixed thresholds are easy to explain and to audit; the disbursement threshold needs a peer reference because projects disburse slowly at first.
- **Decision:** stalled = at least one open tender past its P90; slow signings = half or more of 3+ recent timed contracts above their peer group's slow threshold; disbursement lag = disbursed share at least 20 points below the peer median at the same elapsed decile (after the first quarter of the period); closing extended = moved 6+ months in two years; ISR = PDO or IP below Moderately Satisfactory, or downgraded; fiduciary = High, or Substantial and raised since approval. Red = 3+ indicators, or ISR ratings together with a disbursement lag; amber = 2; watch = 1.

**Step 4 — Do the ISR signals warn early?**
- **Question:** is an ISR signal at mid-term informative about the final outcome?
- **What we found:** the 400 closed projects of p09 have a mid-period ISR text in the volume and IEG's outcome rating.
- **Decision:** section 6 parses the same signals from those mid-period ISRs and compares IEG's unsatisfactory rate for flagged and unflagged projects: a backtest of indicators 5 and 6 at no extra download.

**Step 5 — The ISR text layout changed again in 2026**
- **Question:** why did the first run need an older ISR for 119 of 300 projects?
- **What we found:** for 127 of the 300 projects the newest ISR's text rendering prints the ratings table one cell per line ("Progress towards achievement of PDO" / "Moderately Unsatisfactory" / "Moderately Satisfactory") instead of fixed-width columns, so p09's parser read nothing and the code silently fell back to an older ISR (8 more projects list no ISR at all). The same happened in p09 with the 2024 template.
- **Decision:** a second parser for the cell-per-line layout (`monitoring.parse_isr_cells`; the SORT parser reads both layouts), the layout stored per ISR, and the fallback count shown in section 4, so a third layout change would show up as a jump in `needed_fallback` instead of passing unnoticed.

---

# p15_label_panel

## How it was built and tested

**Step 1 — Which judges?**
- **Question:** which served models can label independently of the models whose output is being labelled?
- **What we found:** the workspace serves gpt-oss-120b (OpenAI), Llama 4 Maverick and Llama 3.3 70B (Meta), Qwen 3.5 122B (Alibaba), Claude models (Anthropic) and Gemma 3 12B (Google). Qwen 3.5 wrote the briefs; a Claude agent built the pipeline and wrote the earlier pair labels. All four judges used accept a strict JSON schema at temperature 0.
- **Decision:** pairs: gpt-oss, Maverick, Qwen 3.5; briefs: gpt-oss, Maverick, Llama 3.3 (Qwen out: it wrote the briefs; Claude out: it is the family of the earlier labeller; Gemma 3 12B is much smaller than the rest). Panel B therefore has two Meta judges, and section 9 shows they err together.

**Step 2 — Give the judges the evidence the original labeller had**
- **Question:** can "same firm?" be answered from two names?
- **What we found:** the p04 labels were made from the names and, where unclear, the contracts; pairs such as "ARUN KUMAR" / "ARUN KUMAR" (two forest divisions) cannot be decided from names at all.
- **Decision:** each record carries up to three of its contracts (year, project, category, description), or award notices for a bidder that never signed; all 200 records have at least one line.

**Step 3 — The judges' arithmetic**
- **Question:** is "does the actual duration lie inside the brief's P10-P90?" safe to ask a model?
- **What we found:** in the first complete run both Llama models said 84 days lies inside 96-262 days (and 28 inside 77-290, 48 inside 55-225); with two Meta judges on the panel, the majority was wrong on 3 of 30 briefs.
- **Decision:** the judges read the three numbers and the code compares them (`timeline_vote`). Now 30 of 30 are unanimous and equal p11's rule-based check on 30 of 30. The same pattern for the counts: a verdict per listed precedent and risk, counted in code.

**Step 4 — Finding unsupported claims is noisy, checking them is not**
- **Question:** why do the judges disagree on "any unsupported claim?"
- **What we found:** asked yes/no, the judges almost never said yes (2, 3 and 0 of 30 briefs; the single p11 judge had flagged 9). Asked to quote the claims, 17 of 30 briefs split (Fleiss' kappa 0.19), mostly because each judge found a different claim.
- **Decision:** section 3b pools every quoted claim and has every judge check every pooled claim; 9 briefs split (kappa 0.42). The verdicts stay independent; the list of claims to check is shared.

**Step 5 — A rubric rule that made the panel unanimously wrong**
- **Question:** where do settled panel labels differ from the earlier labels, and why?
- **What we found:** the first pair rubric said identical personal names on the same project are one person. The panel then called three pairs "same" unanimously that the earlier labeller had separated with evidence (two "ARUN KUMAR" in different forest divisions; an Ethiopian father and son, "TESFAY G/KIRSTOS G/HIWOT" and "FISAHA TESFAY G/KIRSTOS"; a common Bangladeshi name in different districts).
- **Decision:** names of people now need the same place or the same specific assignment; an added or dropped given or father's name is another person; no place shown means "unsure". Two of the three now escalate to tier 3; the third stays unanimous ("MOMINUL HOQUE": its contract lines show no district) and is listed in section 9. The rubric was revised after seeing answers on these same 100 items, so its agreement here is optimistic.

**Step 6 — When does a count need escalation?**
- **Question:** two judges saying 3 and 4 relevant risks is not a real disagreement; 1 and 4 is.
- **What we found:** exact agreement on counts is 0.74 (risks) and 0.91 (precedents), within one 0.92 and 0.98.
- **Decision:** a count escalates when the votes differ by 2 or more, when "n/a" is mixed with numbers, or when judges fall on both sides of "most listed items are relevant" (exactly half sides with neither). 4 risk counts and 1 precedent count escalate.
