# Where the review-pack numbers appear

A checklist for updating the docs after the 30 review briefs are re-measured (panel on `review_briefs_v2.csv`, then
`apply_adjudication.py ... --out final_labels_v2.csv --pairs-from final_labels.csv`). Line numbers are those of
2026-10-23 01:00 EDT; the quoted text is exact, so a search finds it if lines have moved.

## Metric keys

| Key | Metric | Current value | Source in `apply_adjudication.py` output (`review_pack`) |
|---|---|---|---|
| U | briefs with an unsupported claim | 5/30 (17%) | `any_unsupported_claim.rate` x `n` |
| C | briefs whose citations support every claim (= 30 - U) | 25 of 30 | 30 - U |
| T | actual duration inside the cited P10-P90 range | 20/30 | `timeline_ok.rate` x `n` |
| P | relevant precedents per brief that lists any; share of listed precedents relevant | 3.3; 90% | `precedents_relevant.mean`; `share_of_listed_precedents_relevant` |
| L | briefs that list precedents | 22 | 30 - N |
| N | briefs that list no precedents | 8 | `briefs_without_precedents` |
| R | relevant risks per brief | 3.4 | `risks_relevant.mean` |
| A | tier-3 adjudication counts | 24 decisions (10 pairs + 14 questions on 13 briefs), 7 overturned, 15 confirmed, 2 without majority, 2 real errors (r06, r10), 106 brief fields settled | `adjudication_log.md`, `fields_by_source` |
| S | panel statistics of the run (tier 2) | briefs: timeline 30/30 unanimous, precedents 26/30, risks 19/30, claims 21/30, kappa 0.42 | p15 section 5 output |
| K | brief status | 22 complete, 8 partial | `review_briefs*.csv` column `status` |
| G | p11's automatic single-judge scores | inside range 20 of 30; 2.4 precedents; 8 none; unsupported 9 of 30 | p11 section 5 output |

U, T, P, N and R are the headline numbers. C, L follow from them. A and S change with every panel run and
adjudication. K and G change only if p11's review pack itself is regenerated.

## Files to edit by hand

### README.md

| Line | Keys | Current text |
|---|---|---|
| 11 | U | `and 5 of 30 full briefs contain an unsupported claim (final escalated labels).` |
| 192 | T, U | `(final: actual inside the cited range 20/30, unsupported claim 5/30)` |
| 202 | A | `Briefs: 120 fields (30 briefs x 4 questions; timeline decided by code) -> 106 settled, 14 escalated on 13 briefs. Tier 3 made 24 decisions, ...` `It overturned 7 of 24 panel majorities (pairs 54, 68, 89; claim verdicts r05, r06; risk counts r19, r21), confirmed 15, and settled 2 items where the judges had no majority. It confirmed 2 real errors in the agent's briefs from the data: ... (r06) ... (r10: ...)` |
| 203 | S | `timeline 30/30 (1.00); precedents 26/30 unanimous (within one 0.98); risks 19/30 (within one 0.92); unsupported claim 21/30 (kappa 0.42)` |
| 204 | T, L, P, N, R, U | `Review pack, 30 replayed briefs: actual duration inside the cited range 20/30; 22 briefs list precedents, 3.3 relevant on average, 90% of listed precedents relevant, 8 list none; 3.4 relevant risks per brief; an unsupported claim in 5/30 (17%).` |

### docs/proposal.md

| Line | Keys | Current text |
|---|---|---|
| 89 | A | `\| Settled by the panel \| 90, unanimous \| 106 \|` |
| 90 | A | `\| Escalated to the adjudicator \| 10 \| 14, on 13 briefs \|` |
| 92 | A | `only real disagreements get the deeper look, 24 of 220 fields` |
| 93 | A | `It overturned 7 of 24 panel majorities, confirmed 15, and settled 2 items where the judges had no majority. ... it confirmed 2 real errors in the agent's briefs from the data: a precedent wrongly described as "same project" (r06) and an overstated firm-count range (r10).` |
| 239 | K, T, L, P, N, R, U, A | `22 complete and 8 partial; the actual duration fell inside the cited range in 20 of 30. On the final three-tier labels, 22 briefs list precedents (3.3 relevant on average, 90% of those listed) and 8 list none; there are 3.4 relevant risks per brief; and 5 of 30 (17%) contain an unsupported claim. The p11 judge alone had flagged 9: ... and confirmed two real errors, ... (r06), and ... (r10).` |
| 391 | C | `supports: 25 of 30 replayed briefs (final three-tier labels)` |

Not review-pack numbers (leave): 232 (`3.3 per package, 77% relevant` is the 300-package backtest), 241 / 268 (section numbers 3.3 / 3.4), 288 and 296 (`90%` is the p08 judge agreement). After editing proposal.md, run `python docs/build_mermaid_md.py` (Mermaid copy) and `python docs/build_docs.py` (PDF).

### docs/speaker_notes.md

| Line | Keys | Current text |
|---|---|---|
| 51 | U, A | `on the final labels 5 of the 30 full briefs contain an unsupported claim, two of them confirmed against the data (a precedent called "same project" that is not, and an overstated firm-count range)` |
| 109 | A | `and confirmed 2 real errors.` |
| 144 | A | `(24 of 220 fields)` |
| 145 | A, U | `the adjudicator overturned 7 of 24 panel majorities and confirmed 2 real errors in the agent's briefs from the data, ... an unsupported claim in 5 of 30 briefs.` |

Not review-pack numbers: 50 (`agreed 90% of the time` is the p08 judge).

### slides/build_deck.py

| Line | Keys | Current text |
|---|---|---|
| 196 | T, U | `"30 full briefs: actual inside the cited range 20/30; unsupported claim 5/30",` |

### docs/figures/build_figures.py

No review-pack numbers (checked: the `results()` figure shows the duration error and the lessons check only).

### notebooks/p11_backtest.py (markdown) and executed/p11_backtest.ipynb

| File | Line | Keys | Current text |
|---|---|---|---|
| notebooks/p11_backtest.py | 1468 | K, G, T, P, R, U | `30 full briefs (22 complete, 8 partial) ... Automatic scores in this run: ... for 20 of 30; 2.4 of the listed precedents judged relevant on average (8 briefs list none); the groundedness judge finds an unsupported statement in 9 of 30. Final three-tier labels (p15): inside the range 20 of 30; 3.3 relevant precedents per brief that lists any (90% of those listed); 3.4 relevant risks; an unsupported claim in 5 of 30` |
| executed/p11_backtest.ipynb | 2348 | same | the same cell (markdown in JSON; keep `\n` and the escaping) |

The p11 output cells (for example line 2261, `30 full briefs with actual outcomes`) are run output; they change only if p11 is re-run.

### notebooks/p15_label_panel.py (markdown) and executed/p15_label_panel.ipynb

| .py line | executed line | Keys | Current text |
|---|---|---|---|
| 89 | 102 | S | `Now 30 of 30 are unanimous and equal p11's rule-based check on 30 of 30.` (v1 history; true as written) |
| 93-94 | 106-107 | S | `17 of 30 briefs split (Fleiss' kappa 0.19)` / `9 briefs split (kappa 0.42)` (v1 history) |
| 103-104 | 116-117 | S | `exact agreement on counts is 0.74 (risks) and 0.91 (precedents), within one 0.92 and 0.98` / `4 risk counts and 1 precedent count escalate.` (v1 history) |
| 593-596 | 880-883 | S | section 9 table rows `briefs: timeline_ok`, `precedents relevant`, `risks relevant`, `any unsupported claim` |
| 598 | 885 | A | `Escalated to tier 3:** 10 pairs and 13 briefs (14 questions)` |
| 600 | 887 | T, P, R, U | `the actual duration lies inside the brief's range in 20 of 30 briefs; 3.3 relevant precedents per brief that lists any (92% of listed precedents); 3.6 relevant risks per brief; an unsupported claim in 3 of 21 settled briefs.` (settled fields before tier 3) |
| 608 | 895 | S | `(unsupported claims: 0.80 agreement, kappa 0.42)` |
| 626 | 944 | A | `the 24 escalated fields (10 pairs; 14 questions on 13 briefs)` ... `final_labels.csv` (220 rows: 196 from the panel, 24 from tier 3) |
| 632 | 950 | A | `\| Tier 3 decisions \| 24: 7 panel majorities overturned (pairs 54, 68, 89; claims r05, r06; risk counts r19, r21), 15 confirmed, 2 settled where the judges had no majority (pair 87, the risk count of r12) \|` |
| 633 | 951 | A | `\| Real errors in the agent's briefs, confirmed from the data \| 2: r06 ... r10 ... \|` |
| 634 | 952 | A | `\| Flagged claims cleared against award-notice firm counts \| r03, r05, r07, r09, r18, r20 \|` |
| 637 | 955 | T, L, P, N, R, U | `\| Review pack, 30 briefs \| actual duration inside the cited range 20/30; 22 briefs list precedents, 3.3 relevant on average, 90% of listed precedents relevant, 8 list none; 3.4 relevant risks per brief; an unsupported claim in 5/30 (17%) \|` |

The executed p15 copy is the v1 run (its code cells predate the `briefs_file` parameter). A v2 run is a separate
execution; its numbers belong in a new sentence or row rather than in place of the v1 run's output.

### data/human_review/adjudication_log.md

| Line | Keys | Current text |
|---|---|---|
| 9 | A | `Escalated items: **10 supplier pairs** and **14 questions on 13 briefs** (24 decisions).` |
| 61-66 | A | the brief-claims table (one row per disputed claim, r03 ... r26) |
| 87-92 | A | `**Panel majorities overturned:** 7 of 24 decisions.` and its sub-bullets (pairs 54, 68, 89; r05, r06; r19, r21; 15 confirmed; pair 87, r12) |
| 93 | A | `**Real errors in the agent's briefs confirmed by data:** r06 ... r10 ...` |
| 96 | T, P, R, U | `**Review pack, 30 briefs:** actual duration inside the cited range 20/30; 90% of listed precedents relevant; 3.4 relevant risks per brief; an unsupported claim in 5/30.` |

For v2 this log describes the v1 adjudication; the v2 decisions get their own section or file.

## Generated files (rebuild, do not edit)

| File | Rebuilt by |
|---|---|
| docs/proposal_mermaid.md (lines 149, 150, 152, 153, 374, 590 mirror proposal.md 89, 90, 92, 93, 239, 391) | `python docs/build_mermaid_md.py` |
| docs/proposal.pdf | `python docs/build_docs.py` |
| slides/procurement_intelligence.pptx, .pdf | `slides/build_deck.py` |
| data/human_review/adjudicate_v2.html | `build_adjudicate.py panel_labels_v2.csv` (scratch builder of the panel component) |
