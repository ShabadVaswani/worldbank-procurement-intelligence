# Missing and incomplete reporting: what the open data does not say, and how the prototype handles it

Rubric line: *"realistic handling of missing or incomplete reporting"*. This page lists every gap met while building phases 1-3, how it was detected, what the pipeline does about it, and what it still costs. Every number was re-checked with a query on the Delta tables (snapshot 2026-10-20/21) or comes from the executed notebook named in the row.

**Principles applied throughout**

- **Measure, then decide.** Every gap below was found by a check (a count, an assert, an audit of a sample, a failed run), not assumed.
- **Never impute silently.** Unknown values stay null and are counted; derived flags say `no_data`, never `ok` (p14). Where a value is reconstructed (a country from a crosswalk, a rating from text) the source is stored next to it.
- **State the denominator.** Coverage is reported against the population that could have the value (e.g. openly competed contracts for "has a tender notice"), not against everything.
- **Prefer bounded cohorts to biased averages.** Truncated feeds are cut to fully observable windows (p07); rare or invisible events are labelled as lower bounds.
- **Keep the gap visible to the user.** The agent's brief has an "evidence gaps" field (p08), benchmark records below 20 contracts say "too few, not used", early-warning rows carry `n_no_data`.

## 1. Source APIs and ingestion

| Gap | How it was detected | How it is handled | Residual impact | Numbers |
|---|---|---|---|---|
| Procurement notices API cannot page past offset 100,000 (`$skip` limit) and ignores date filters | probe: `os` > 100,000 returns an Azure Search error; date parameters had no effect | partition by project country (facet `project_ctry_name_exact`, 184 values, largest India 47,452 < 100k); sort by id within a country; stop at the 2018 cutoff | none for country-tagged notices | 416,745 bronze notices = sum of facet counts (p02) |
| Newest notices are published without a project country, so the country partitions miss them | p02 re-run: facet counts summed 200 below the API total | an extra pass over the unfiltered feed, newest first, until that many country-less notices are saved (75 pages) | the gap reappears at every refresh and is re-measured each run | 200 at the re-run; 45 bronze notices still have no `project_ctry_name` today |
| The facet list holds two spellings of one country ("Turkiye", "Türkiye") that slugify to the same folder | own assert on folder uniqueness failed | folder = slug + hash of the exact name; unit test | none | 4,520 + 4 notices |
| Notice fields missing at source | DQ counts in p02/p03 | kept, nulls counted; notices without a date are excluded from timelines | small | 734 notices without `noticedate`, 33 without `notice_type` (bronze) |
| Accented characters stripped in the source text ("Seleccin", "Evaluacin") | reading award notices | matching rules use ASCII-folded, accent-free patterns; nothing is repaired | French/Spanish/Portuguese text matching is slightly weaker | 1,049 notices contain "Seleccin" |
| Rate limits: FinancesOne / data catalog answer HTTP 429 ("try again in N seconds"); the GTE embedding endpoint's QPS limit is shared by all users | 429 responses in probes (phase 1, phase 3) and in p08 re-ranking | `retry_delay()` honours the server hint; embeddings paced at 10 texts/s with 12 retries | runs take longer, never fail on throttling | p08, p12 logs |
| Documents listed without a text rendering (404 on `txturl`) | p09 run 1 failed on a 404 | 403/404/410 -> "unavailable", a `.missing` marker, next candidate of the same role | that document is not read | 17 of 400 projects' ICR Reviews listed but unreadable; 2 list none (p09, `rating_documents`: 381 of 400 readable) |

## 2. Structured records: contract awards and notices

**Scope decision: contract awards from FY2020 only.** Older contract-award data was reviewed before fixing the scope. The retired FinancesOne dataset DS01004 covers FY2001–FY2016 (146,802 rows) but only *major*, prior-reviewed contracts; a third-party copy of the former "Major Contract Awards" feed (last updated November 2019) may cover FY2017–FY2019 with the same restriction, and no official source clearly covers that gap. The current dataset DS00005 (FY2020 onward) covers *all* reported contracts. Mixing the two would bias every benchmark and model towards large contracts and leave a three-year hole, so the project uses the complete FY2020+ series only. The older data remains a possible extension for long-run supplier histories, kept separate.

| Gap | How it was detected | How it is handled | Residual impact | Numbers |
|---|---|---|---|---|
| Awards feed covers only FY2020+ signings, so both ends of the tender-duration distribution are truncated | median duration by notice year runs from 465 days (2018) to 95 days (2026) | p07 models only notices 2019-07-01 to 730 days before the snapshot (fully observable), durations capped at 730 days; Kaplan-Meier with censoring for the survival view | the newest cohorts are not used for training; the model is about 2 years behind | signing dates 2019-07-01 to 2026-10-13; 20,745 contracts in the modelling cohort (p07) |
| Individual consultants are anonymised (supplier "INDIVIDUAL CONSULTANT", hashed id) | profiling of `contract_awards` | excluded from entity resolution, kept as one entity per hash | no history or concentration analysis for individuals | 65,121 award rows, 55,228 hashed ids |
| Joint-venture rows repeat the contract amount on each member (not a share) | amounts identical (or a fixed ratio) across members | one amount per contract (max), spread kept as a quality column; supplier totals labelled "value won as member" | member shares unknown | 8,864 multi-supplier contracts, 1,781 with differing member amounts |
| Contracts with no borrower country (regional programmes) | null count in p03 | kept, excluded from country-level benchmarks (region / category levels used) | country peer groups miss them | 2,004 contracts; 217 in the p07 cohort |
| Aggregate codes in country data (World = 1W in suppliers vs 99 in borrowers; regional aggregates ZJ, 1W in WDI) | p03 asserts failed | crosswalk 1W -> 99; indicator names used only for codes seen in the awards | none | p03 log |
| Supplier id is a registration id, not an identity (one firm, many ids; one id, several names) | profiling | entity resolution (p04) with same-id links only when names agree | ER errors remain | 537 supplier ids carry 2+ distinct (upper-cased) names, 6,681 names carry 2+ ids (awards, individuals excluded); ER precision 0.97 / recall 0.90 on 100 labelled pairs; 30 of 40 audited fuzzy links strictly the same legal entity |
| Award notices that name no firm (individuals without an id, small-assignment template) | 89,562 award notices without a firm in the first parse; investigation by heading | second template recognised; firms without an id skipped (cannot be keyed) | bidder counts missing for those notices | 68,147 of 296,569 award notices name no firm today; 7,012 of 28,235 open timed contracts have no bidder count |
| Bid deadline before the notice date (data entry errors) | DQ check | flagged, excluded from timing | small | 849 notices; 304 timelines flagged |
| No contract amendments, variations or re-awards in the awards feed | schema: one row per contract, no amendment columns | amendment risk cannot be modelled; stated in p07 and p14 | the brief's "amendment probabilities" are not estimable from open data | 282,890 contracts, 0 amendment fields |
| No pre-award cost estimate on notices or contracts | schema | the awarded amount is used only where it is legitimate (benchmarks of lot size, ratios after award), never as a feature at notice time (p07) | packaging checks compare awarded values, not estimates (p13) | p07, p13 |

## 3. Linking notices, contracts and timelines

| Gap | How it was detected | How it is handled | Residual impact | Numbers |
|---|---|---|---|---|
| Most contracts are never advertised (RFQ, direct, individual consultants), so "share with a tender notice" needs the right denominator | p05 coverage by method | coverage reported for openly competed contracts only | none, if read correctly | 28,235 of 62,828 open contracts timed (44.9%); 191,692 contracts use methods not normally advertised |
| Open contracts whose tender notice cannot be linked | p05 `timing_gap` | kept in silver, excluded from duration statistics | durations come from the linked subset only | 34,230 open contracts with no tender notice linked |
| **Selection bias of linked contracts:** the linked share differs by method and year | timed share by year and method | reported with every duration statistic; p07's cohort and peer groups are per method x category | benchmarks lean towards the methods and years that link well | timed share of open contracts: 27.4% (2019) -> 60.0% (2026); Request for Bids 41.1%, QCBS 69.3% |
| Implausible timelines | p05 rules | excluded from `is_timed` | small | 812 excluded (notice > 3 years before signing 130, bid deadline after signing 378, before notice 304) |
| **Re-tenders under a new reference are invisible**; re-advertisement under the same reference is rare | p07 / p10 counts | re-advertisement not modelled; KPI labelled a lower bound | the true re-tender rate is unknown | 408 of 28,598 open contracts with a notice have 2+ tender notices (1.4%); p10: 440 of 35,252 IFB-linked contracts re-advertised 30+ days apart (1.2%) |
| **Cancelled tenders are invisible** (no cancellation feed), and open tenders look "stalled" when they were signed under a reference p05 could not link | Kaplan-Meier curves flatten at the link rate (0.56-0.67); many open notices exceed their P90 | stalled-tender flags are labelled as such (p07 table comment, p14 reasons); survival analysis censors unsigned notices | some "stalled" flags are false positives | 1,659 of 6,005 open notices past their P90 (p07); 429 of 1,340 active projects have one (p14) |
| Notice date = date of publication on the World Bank site, which can follow the first publication | p13 policy check flags 35% of international tenders | the policy check states the caveat; the peer check is relative and less sensitive to it | some policy flags are artefacts | 672 of 1,939 international IFBs under 42 days, but 555 under 40 days, median 30.5 (p13) |

## 4. Documents, ratings and text

| Gap | How it was detected | How it is handled | Residual impact | Numbers |
|---|---|---|---|---|
| Reused RAG chunks hold only appraisal-stage documents (no ISRs, ICRs) | profiling `silver.rag_chunks` | ICRs chunked in p08; ISRs and ICR Reviews read in p09 / p14 | lessons corpus is a sample (300 ICRs) | 50,000 chunks, 453 documents: PAD / PID / Program Document only |
| Plain-text chunking dropped or broke tables (costs, thresholds, procurement packages) | p12 row test against the PDF tables, with a control on narrative sentences | structure-aware chunks: table chunks with headers repeated, contextual header, annex flag (p12) | only 10 PADs re-parsed so far; unruled tables (results frameworks) still narrative | of 1,290 identifiable table rows, 346 (26.8%) missing and 58 (4.5%) split in the old chunks; control: 97.2% of sentences intact |
| PDFs carry no bookmarks; scanned pages would have no text layer | p12: `get_toc()` empty for 10 of 10 PADs; text-layer count | typographic headings; OCR only as a fallback for pages without text | heading errors (cover lines, datasheet labels) remain and are shown | 0 of 941 pages without a text layer (p12) |
| IEG's dataset has no ICR self-rating column | profiling `bronze.ieg_ratings` | read from the ICR Review's ratings table; IEG's own rating read from the same table is checked against the dataset | none measurable | IEG parse = dataset for 381 of 381 reviews (p09) |
| **ISR template changes** silently break parsers: 2024 template ("Previous / Current" header, icon glyphs); 2026 renderings print one table cell per line | p09 run 1: 91 of 400 newest ISRs had "no ratings"; p14 run 1: 127 of 300 newest ISRs unreadable, 119 fell back to an older ISR | a parser per layout (evidence.py, monitoring.py), layout stored per ISR, fallback counts shown in every run | the next template change will again show up first as a jump in fallbacks | p09: 3 fallbacks after the fix; p14 after the fix: 120 of 300 latest ISRs in the cell-per-line layout, 1 fallback, 286 readable |
| ISRs no longer rate procurement separately | p14 probe of 400 ISRs | the SORT **fiduciary** rating (FM + procurement) is used instead | procurement and FM risk cannot be told apart | 0 of 400 ISRs with a procurement rating line; 398 with a SORT table |
| Supervision ratings are optimistic relative to IEG | p09 measurement | resolution policy ranks IEG first and always returns the conflicting records | an outcome question for a project not yet evaluated gets "low" confidence | 35 of 68 IEG-unsatisfactory projects (51.5%) had a satisfactory last ISR (p09) |
| IFB notices rarely state qualification criteria or specifications; those are in bidding documents, which are not open data | p13 extraction on 400 notices | requirement checks run where values exist and say how many could be evaluated | tender-design checks on specifications are not possible from open data | turnover in 9.8%, experience years in 5.2% of notices; bid security amount or % in 54.3% (p13) |
| Bid security and turnover amounts in local currency without an exchange-rate table | p13 | only stated percentages and US$ amounts are compared with contract values | most local-currency amounts are stored but unused | 89 of 400 notices with a comparable bid-security %, 18 with a turnover multiple (p13) |

## 5. Projects, finance and execution

| Gap | How it was detected | How it is handled | Residual impact | Numbers |
|---|---|---|---|---|
| Projects in the procurement data missing from the outcome project's project table | p03 join | kept with null attributes | no outcome-model risk for them | 116 of 3,768 projects |
| Outcome-model risk exists only for projects still active in 2026 | p07 leakage review | excluded as a model feature (its presence leaks the future) | not used for prediction | 1,401 projects with a risk band |
| Projects API financial fields lag the Bank's loan statements | p14: P160446 disbursement and closing date in the API equal the September 2024 statement | disbursement and closing dates from FinancesOne monthly statements (IBRD DS00975, IDA DS00976), latest and two years earlier | closing-date moves are visible only between the two snapshots read | 40,842 statement rows; 1,012 of 1,340 active projects have a closing date in both snapshots (p14) |
| Disbursement profiles differ by instrument; instrument missing for recent projects | p14 | disbursement lag judged only for investment projects (IPF), `no_data` otherwise | development-policy and results-based operations get no disbursement signal | 979 IPF, 70 PforR, 291 not in the Projects API active list (p14) |
| ISRs cover a sample, and an ISR can be stale | p14 design | 300 sampled projects; ISRs older than 12 months are marked in the reasons | ISR-based indicators are `no_data` for the other active projects, so their alerts are a lower bound | 300 of 1,053 active projects with procurement activity sampled; ISR indicator `no_data` for 1,054 of 1,340 (p14) |
| **Contract-level milestones, amendments, payments and procurement risk ratings are not public** | schema of every open source | p14 documents the production feeds (STEP, Client Connection, PRAMS) and keeps indicators pluggable | the prototype warns at project level only | p14 section 7 |

## 6. Where to see each gap in the data

| Table / artefact | Columns that expose the gap |
|---|---|
| `proc_gold.tender_timelines` | `timing_gap`, `is_timed`, `n_tender_notices`, `n_named_firms_in_award_notice` (null = not stated) |
| `proc_silver.contracts` | `borrower_country_code` (null = regional), `amount_spread_ratio`, `is_individual_consultant` |
| `proc_gold.open_tender_scores` | `past_p90` (stalled or unlinked) |
| `proc_silver.tender_requirements` | `field_sources` (rules / model), nulls per field |
| `proc_bronze.rating_documents`, `proc_bronze.monitoring_isr_documents` | `n_tried` (fallbacks), `doc_id` null (unreadable), `layout` |
| `proc_gold.early_warnings` | `ind_*` = `no_data`, `n_no_data` |
| `proc_bronze.parsed_documents` | `pages_without_text`, `tables_found` vs `tables_kept` |
