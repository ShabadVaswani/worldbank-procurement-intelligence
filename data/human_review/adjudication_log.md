# Tier-3 adjudication log

Evaluation labels come from a three-tier escalation:

1. **Automatic:** checks that code can decide, such as whether the actual duration falls inside the brief's cited P10–P90 range.
2. **Judge panel:** three LLM judges from different model families label each item independently (notebook `p15_label_panel`).
3. **AI adjudicator:** items where the judges disagree escalate to an AI agent with access to the warehouse tables and the web. This log records how each escalated item was decided.

Escalated items: **10 supplier pairs** and **14 questions on 13 briefs** (24 decisions). The machine-readable copy is `adjudication_decisions.csv`. `apply_adjudication.py` merges it with the panel's settled labels into `final_labels.csv`.

**How each decision was made**
- The adjudicator read the panel's three votes and rationales, then went back to the source: the names and contracts for supplier pairs, and the brief with its cited records for briefs.
- Where a claim was checkable, it queried the warehouse, typically firm counts in award notices and project ids.
- For two company names it ran a web search.
- When the evidence could not settle a pair, it was labelled **unsure** and left out of precision and recall rather than forced.

**Queries used for the brief checks** (SQL warehouse, catalog `dbw_wb_outcome`):

```sql
-- firms named in each contract's award notice, and the contract's project
SELECT c.contract_id, c.project_id, c.borrower_country_code,
       count(DISTINCT b.supplier_id) AS firms_in_award_notice
FROM proc_silver.contracts c
LEFT JOIN proc_silver.notice_contract_links l
       ON c.contract_id = l.contract_id AND l.link_role = 'award'
LEFT JOIN proc_silver.notice_bidders b ON l.notice_id = b.notice_id
WHERE c.contract_id IN (...)            -- the contracts cited by the disputed briefs
GROUP BY ALL;
```

---

## Part A: supplier pairs (question: are these the same real-world firm?)

| Pair | Names (country) | Panel votes (gpt-oss / Llama 4 / Qwen 3.5) | What was checked | Decision |
|---|---|---|---|---|
| 33 | SOARAFITRA_AGEX_FID / SOAFIANATRA_AGEX_FID (Madagascar) | different / same / different | Names, contracts: both are FID implementing agencies (AGEX) on the same safety-net projects, but the distinctive Malagasy names differ in several letters, which is not a spelling variant | **different** |
| 35 | DATA TECHNOLOGIES / OBAIN TECHNOLOGIES (Côte d'Ivoire) | different / same / different | The distinctive word differs (DATA vs OBAIN). Web: Obain Technologies has its own directory listing in Marcory, Abidjan, and nothing links it to "Data Technologies" | **different** |
| 46 | SHREEJI ENTERPRISES / SHREE ENTERPRISES (India) | different / same / different | Very common generic trade names, contracts in different projects, nothing ties them together | **different** |
| 47 | ASIAN INISTITUTE OF TECHNOLOGY, THAILAND / M/S: ASIAN INSTITUTE OF TECHNOLOGY | same / same / different | Same institution with a typo ("INISTITUTE"). Qwen objected because B's contracts are in Pakistan, but AIT delivers consulting abroad, so the borrower country differs while the supplier is the same | **same** |
| 54 | GROUPEMENT SETI AGRITCHAD / AGRITCHAD (Chad) | same / same / different | A is a consortium that includes B. A consortium and one of its members are different legal entities: related, not the same firm | **different** (majority overturned) |
| 56 | TESFAY G/KIRSTOS G/HIWOT / FISAHA TESFAY G/KIRSTOS (Ethiopia) | same / different / different | Ethiopian names are given name + father + grandfather: A is Tesfay, son of G/Kirstos; B is Fisaha, son of Tesfay. Father and son, so two people | **different** |
| 64 | 1RA OLA POTOSI PERSONAL DE SALUD / 1RA OLA BENI PERSONAL DE SALUD (Bolivia) | different / same / different | Two departmental groups of health staff in the first COVID wave (Potosí vs Beni), not one supplier | **different** |
| 68 | MASTER OFFICE / MASTER OFFICE DECO (Senegal) | same / same / different | Web: "Master Office Déco" is an office and home-equipment retailer with showrooms in Dakar and Mbour, and a separate "Master Office SA" also appears in Senegalese job listings. Whether "Master Office" is the same company as "Master Office Déco" could not be established | **unsure** (excluded from precision and recall) |
| 87 | ARUN KUMAR / ARUN KUMAR (India) | different / same / unsure | A very common personal name; same project but different years, job types and locations. Not enough to say one person | **unsure** (excluded) |
| 89 | SANJEEV KUMAR / SANJEEV KUMAR (India) | unsure / same / same | A very common personal name; same project but different schemes and gram panchayats. Same project alone is not evidence of the same person | **unsure** (excluded; majority not followed) |

Web sources for pairs 35 and 68:
- [annuaireci.com: Obain Technologies, Abidjan](https://annuaireci.com/en/entreprises/obain-technologies-abidjan-cote-divoire/)
- [concoursn.com job listing: Master Office Déco](https://concoursn.com/?p=331734)
- [concoursn.com job listing: Master Office SA](https://concoursn.com/?p=194728)

---

## Part B: briefs

The questions were: how many risks are relevant (0–5); how many listed precedents are relevant (0–5); is any claim **not** supported by the cited records (yes/no).

### Unsupported-claim questions (decided by checking the claim against the warehouse)

| Brief | Claim in dispute | Panel (gpt-oss / Llama 4 / Llama 3.3) | Evidence | Decision |
|---|---|---|---|---|
| r03 (Chad, works) | "precedent of **20 firms** participating in similar electrical works framework agreements" | yes / no / no | Award notices for contracts 1663521, 1663544, 1663549, 1663550 and 1663562 each name **20 firms**; all were Request for Bids | **no unsupported claim** |
| r05 (Philippines, vehicles) | "similar vehicle packages … used Request for Quotations with **1 to 3 firms**" | yes / yes / no | All five precedents used Request for Quotations. Firms in award notices: 1686805 → 1, 1727398 → 3, 1753945 → 1; 1624879 and 1821008 have no linked award notice. The range 1–3 holds | **no** (panel majority overturned) |
| r06 (Sri Lanka, canal works) | precedent 1597637 is "similar canal improvement works … **under the same project ID**" | yes / no / no | Contract 1597637 belongs to project **P146314**; the package is project **P160005**. The claim is false | **yes, unsupported** (majority overturned) |
| r07 (Mozambique-type IT goods) | "precedents with **varying numbers of firms**" | yes / no / no | 1715931 → 7 firms, 1647016 → 1 firm. The claim holds | **no** |
| r09 (Philippines, road works) | "up to **11 firms** participated" | yes / no / no | Award notice for contract 1759454 names **11 firms** | **no** |
| r10 (Peru, consulting) | "recent similar contracts **in the same project** attracted between **2 and 6** bidding firms" | yes / yes / no | Only two cited contracts are in the package's project P174177: 1869249 (2 firms) and 1869269 (5 firms). The 6-firm contract (1755956) is in project P163255. The "same project, 2 to 6" claim is wrong | **yes, unsupported** |
| r16 (Kyrgyz Republic, goods) | precedent described as "in a **similar regional context**" (an Afghan contract) | no / yes / no | A loose characterisation, not a checkable fact; every factual statement in the brief matches its records | **no** |
| r18 (Tonga, ICT services) | precedent "awarded via **Request for Bids with 8 firms**" | yes / no / no | Contract 1611409: Request for Bids; award notice names **8 firms** | **no** |
| r20 (India, equipment) | precedents "ranging from **1 to 8** firms" | yes / no / no | 1650502 → 8 firms, 1777053 → 1 firm | **no** |

### Count questions (decided by reading each risk or precedent against the package)

| Brief | Question | Panel | Reasoning | Decision |
|---|---|---|---|---|
| r01 (Niger, Owner's Engineer for mini-grids) | relevant risks of 3 | 3 / 1 / 3 | Risk 1 (procurement capacity) fits directly. Risks 2 (contractor shortfalls) and 3 (contractor payment delays) concern the works, which the Owner's Engineer is hired to supervise, so they sit within its scope | **3** |
| r10 (Peru, technical-file consultancy) | relevant precedents of 5 | 5 / 3 / 3 | 1743691, 1743687 and 1755956 are QCBS technical-file (expediente técnico) contracts. 1629581 (an individual consultant writing terms of reference) and 1747934 (an individual cloud specialist) are a different kind of assignment | **3** |
| r12 (vehicle rental for a census) | relevant risks of 3 | 3 / 2 / 1 | Procurement-plan slippage and procurement fraud risks fit a large rental contract; cash handling for enumerator payments does not | **2** |
| r19 (Bangladesh, service provider to operate a training centre) | relevant risks of 3 | 3 / 1 / 3 | Client capacity and budget inclusion, and provider competence and subcontracting, fit; delays in finalising design drawings do not apply to an operating contract | **2** |
| r21 (Lao PDR, "refurbishment" procured as consulting) | relevant risks of 4 | 4 / 0 / 4 | The package is ambiguous (refurbishment under a consulting method, probably design or supervision). Seasonal timing and late design specifications are sensible; state-owned-enterprise prequalification and contractor payment delays are works-contract risks | **2** |

---

## What the escalation changed

- **Panel majorities overturned:** 7 of 24 decisions.
  - 3 pairs: 54 (same → different), 68 (same → unsure) and 89 (same → unsure).
  - 2 claim verdicts: r05 (unsupported → supported) and r06 (supported → unsupported).
  - 2 risk counts: r19 (3 → 2) and r21 (4 → 2).
  - 15 decisions confirmed the panel's majority.
  - 2 items had no majority: pair 87 (three different votes), decided as unsure, and r12's risk count (votes 3 / 2 / 1), decided as 2, the panel's median.
- **Real errors in the agent's briefs confirmed by data:** r06 described a precedent as being in the same project when it was not, and r10 overstated a firm-count range. Both are now counted as unsupported claims.
- **Final results on these labels:**
  - **Supplier matching:** precision 1.00 (95% CI 0.90–1.00) and recall 0.90 (0.77–0.96) on 97 decided pairs; 3 were left unsure.
  - **Review pack, 30 briefs:** actual duration inside the cited range 20/30; 90% of listed precedents relevant; 3.4 relevant risks per brief; an unsupported claim in 5/30.

## Limits

- The adjudicator is an AI agent (Claude, Anthropic), not a person. Its decisions carry written evidence so a person can audit them, but they are an AI agent's labels, not labels from people.
- Claude is the same model family as the coding agents that built the pipeline, which is why it was kept off the tier-2 panel. As adjudicator, it decided factual questions with database queries or web sources rather than judgement alone, so each of those decisions can be checked independently of the model.
- The rubrics for tiers 2 and 3 were sharpened after looking at these same items, so agreement figures are optimistic.
- Independent validation by procurement specialists is planned for the pilot.

---

## Round v1r: the original 30 briefs re-judged with rubric v2 and full record facts

The panel re-judged the first 30 briefs with the round-2 briefs rubric (mitigations count as advice, not claims; evidence gaps are checked against the cited records; judges see the package facts), and with each cited record shown with its facts line (project, country, region, method, signing year, firms in the award notice). That gives them the same information the round-2 briefs are judged with, so before and after are compared fairly. Escalated: **14 fields on 12 briefs**. Decisions are in `adjudication_decisions_v1r.csv`.

| Brief | Field | Panel (gpt-oss / Llama 4 / Llama 3.3) | Evidence | Decision |
|---|---|---|---|---|
| r01 | risks relevant (of 3) | 3 / 1 / 3 | Same as v1: contractor and payment risks are within an Owner's Engineer's supervision scope | **3** |
| r01 | unsupported claim | no / no / yes | "A similar precedent in Niger used this method": contract 1711519 is NE, QCBS | **no** |
| r03 | precedents relevant (of 5) | 5 / 0 / 5 | Five electrical-works framework agreements under Request for Bids; another country is not a relevance criterion | **5** |
| r07 | unsupported claim | yes / yes / no | Precedent 1742662 called "similar category and method" but used Request for Proposals; the package is Request for Bids | **yes** |
| r10 | precedents relevant (of 5) | 5 / 3 / 3 | Same as v1: 3 QCBS technical-file contracts; 2 individual-consultant assignments are a different kind | **3** |
| r12 | risks relevant (of 3) | 3 / 1 / 1 | Same as v1: enumerator cash payments do not fit a vehicle rental | **2** |
| r13 | precedents relevant (of 5) | 5 / 4 / 2 | All five are mini-grid or distribution-network works (the PV plants include their networks) | **5** |
| r14 | unsupported claim | yes / no / no | "Similar school supervision contracts in the region used CQS": the CQS contracts are in Armenia and North Macedonia; the regional one (Malawi) used QCBS | **yes** |
| r16 | precedents relevant (of 5) | 5 / 1 / 5 | All five procure engineering or materials-testing equipment | **5** |
| r16 | unsupported claim | no / yes / no | "Similar regional context": Afghanistan (South Asia) precedent for a Kyrgyz (Europe and Central Asia) package. Checkable now that region is in the facts; v1 had treated it as a loose phrase | **yes** |
| r19 | risks relevant (of 3) | 3 / 1 / 3 | Same as v1 | **2** |
| r20 | unsupported claim | no / no / yes | "Precedents … in the region": both precedents are Eastern and Southern Africa (3E); the package is India (South Asia). Missed in v1 because region was not visible | **yes** |
| r21 | risks relevant (of 4) | 4 / 2 / 4 | Same as v1 | **2** |
| r26 | risks relevant (of 4) | 4 / 2 / 4 | All four are procurement-process delays that apply to a goods contract | **4** |

**What this round shows:** with region facts visible, three region and method claims in the original briefs turn out to be unsupported (r14, r16, r20), plus r07's method claim. These are the same kind of embellishment the round-2 fixes target, so the fair "before" baseline is stricter than the first count of 5/30.

---

## Round v2 (final fact-checked briefs)

The 30 briefs of the final writer pass (`review_briefs_v2_full.csv`, r01–r30, every cited record with its facts line) were judged by the panel with rubric v2 (`panel_labels_v2.csv`). Escalated: **9 fields on 9 briefs**. Decisions are in `adjudication_decisions_v2.csv`; `final_labels_v2.csv` merges them with the settled panel labels (pair rows taken from `final_labels.csv`).

**Queries used** (SQL warehouse, catalog `dbw_wb_outcome`):

```sql
-- category and method of the precedents disputed in r06 and r22
SELECT contract_id, project_id, borrower_country_code, procurement_method_name, procurement_category_code
FROM proc_silver.contracts
WHERE contract_id IN ('1597637','1597245','1695181','1697391','1728096','1662293','1614656');

-- r26: award notices linked to the furniture precedents, and firms named in them
SELECT c.contract_id, l.notice_id, l.link_role, count(DISTINCT b.supplier_id) AS firms
FROM proc_silver.contracts c
LEFT JOIN proc_silver.notice_contract_links l ON c.contract_id = l.contract_id
LEFT JOIN proc_silver.notice_bidders b ON l.notice_id = b.notice_id
WHERE c.contract_id IN ('1638806','1638817','1741037','1755857','1765796') GROUP BY ALL;

-- r26: the unlinked contract 1638817 (signed the same day, same project as 1638806): furniture notices in P160083
SELECT n.notice_id, n.notice_type, n.bid_reference, b.role, b.firm_name
FROM proc_silver.notices n LEFT JOIN proc_silver.notice_bidders b ON n.notice_id = b.notice_id
WHERE n.project_id = 'P160083' AND lower(n.bid_description) LIKE '%furniture%';
```

| Brief | Field | Panel (gpt-oss / Llama 4 / Llama 3.3) | Question | Evidence | Decision |
|---|---|---|---|---|---|
| r01 (Niger, Owner's Engineer for mini-grid works) | precedents relevant (of 4) | 2 / 4 / 2 | Are the two mini-grid consultancies the same kind of service? | 1754608 (engineer assisting the client through study, bidding documents and works supervision) and 1711519 (supervision of distribution-network works) are works supervision. 1656065 is a willingness-to-pay survey and 1702498 technical assistance to mini-grid operators: same sector, another service | **2** |
| r05 (Philippines, vehicles) | precedents relevant (of 5) | 4 / 4 / 2 | Which precedents bought vehicles? | Four are vehicle purchases; 1821008 buys monitoring, control and surveillance "outfit and accessories", which is gear, not vehicles | **4** |
| r06 (Sri Lanka, canal works) | unsupported claim | yes / yes / no | Is "same country (LK) and category (CW) … South Asia" for precedent 1597637 supported? | Facts line: LK, South Asia. The facts line has no category, but `proc_silver.contracts` gives CW for 1597637 (and for all five precedents). Llama 4 objected that 1597637 used Request for Quotations, but the brief never says otherwise: it counts "4 of 5" under Request for Bids, which is right. "3 to 6 firms" matches 4, 6 and 3 in the facts lines | **no** (majority overturned) |
| r10 (Peru, technical-file consultancy) | precedents relevant (of 5) | 5 / 3 / 3 | Same as v1 and v1r | Three QCBS technical-file contracts; 1629581 (terms of reference) and 1747934 (cloud specialist) are individual-consultant assignments of another kind | **3** |
| r14 (Mozambique, school works supervision) | precedents relevant (of 5) | 5 / 1 / 5 | Do country and method make four precedents irrelevant? | All five are supervision of school renovation or construction works. The dissent rests on country and method, which the rubric excludes | **5** |
| r19 (Bangladesh, operator for a training centre) | risks relevant (of 4) | 4 / 2 / 4 | Do risks 1 (slow procurement after effectiveness) and 4 (invoice and payment delays) fit an operating-service contract? | Risk 1 is a procurement-timeline risk that applies to any package. Risk 4 is a client-side payment delay, which also hits a service provider paid on invoices. Its mitigation (faster invoice processing) addresses it; the guarantee clause is worded for works but does not undo that | **4** |
| r22 (Serbia, river training works) | unsupported claim | no / no / yes | Does the brief place the package in the Middle East and North Africa region? | No. The brief says both precedents are river-training civil works in Pakistan under Request for Bids. Facts lines: PK, Request for Bids; warehouse category CW. The package region is not misstated | **no** |
| r26 (Guyana, furniture) | unsupported claim | yes / no / yes | "4 used Request for Quotations (1638806, 1638817, 1755857, 1741037) with 3 firms in award notices": is the count supported for 1638817, whose facts line says "not recorded"? | Facts lines give 3 firms for 1638806, 1741037 and 1755857. 1638817 has no linked notice. Award notice OP00109336 is for the same RFQ (KE-MOE-68805-GO-RFQ, the reference of 1638806) and names 1638817's winner, PANESAR KENYA LTD, as awarded among the same 3 firms. The claim holds, and as in v1 r05 a firm count stated over the recorded notices is supported | **no** (majority overturned) |
| r27 (Tajikistan, audits) | unsupported claim | no / yes / no | Is "no Tajikistan-specific precedents (all precedents from UA, UZ, VC)" supported? | Facts lines: UA ×3, UZ, VC. "4 of 5 used Least Cost Selection" also holds (1633410 is CQS). Llama 4 misread the sentence | **no** |

**What this round changed:** 9 decisions.
- **Panel majorities overturned: 2**, both claim verdicts. r06 moves from unsupported to supported: the category is in the warehouse, and the method objection misread the brief. r26 also moves from unsupported to supported: the warehouse shows the missing firm count is 3.
- **Confirmed: 7.**
- **No majority to settle: 0.**

**Checked but not escalated** (left as the panel settled them):
- **r18:** unanimous unsupported, and the evidence agrees. The package uses Request for Proposals, yet the brief calls it "consistent with" precedent 1611409, whose facts line shows Request for Bids. This is the same method mismatch as v1r r07.
- **r30: overridden to unsupported (owner-approved).** The panel was unanimous "no", but the brief says Request for Quotations was used "in 4 of 5 contracts". All five facts lines show Request for Quotations, and the brief's own evidence gap says "All precedents used Request for Quotations". Only 3 of the 5 are biometric, so the count is wrong on either reading; the single backtest judge also flagged the sentence. Tier 3 normally decides only escalated fields, so this was raised with the owner, who approved counting it. It is recorded as a decision row in `adjudication_decisions_v2.csv` and the final label is "yes".
- **r10:** unanimous "no". The market approach gives "1 to 6 firms … in the 3 QCBS contracts" without the "(among the 2 with a recorded count)" qualifier: 1743691 is not recorded, while 1743687 has 1 and 1755956 has 6. The range holds over the recorded counts, which is consistent with r26 above and v1 r05.

---

## Round holdout

Ten new briefs (`review_briefs_holdout_full.csv`, h01–h10) were written by the final writer pass but never used to tune it. The panel judged them with rubric v2 (`panel_labels_holdout.csv`). Escalated: **6 fields on 5 briefs**. Decisions are in `adjudication_decisions_holdout.csv`; `final_labels_holdout.csv` holds the merged labels (briefs only, no pairs).

**Queries used** (SQL warehouse, catalog `dbw_wb_outcome`):

```sql
-- the forecast tool's notice defaults, recomputed exactly as notebooks/proc_rag_core.py builds them
WITH r AS (
  SELECT t.procurement_method_name AS m, t.procurement_category_code AS c, n.notice_type,
         CASE WHEN datediff(n.submission_deadline, n.notice_date) >= 0
              THEN datediff(n.submission_deadline, n.notice_date) END AS adv,
         n.notice_text_chars AS chars
  FROM proc_gold.tender_timelines t JOIN proc_silver.notices n ON n.notice_id = t.tender_notice_id
  WHERE t.is_timed AND t.competition = 'open' AND t.tender_notice_date BETWEEN '2019-07-01' AND '2024-10-13')
SELECT m, c, mode(notice_type), percentile(adv, 0.5), percentile(chars, 0.5), count(*) FROM r
WHERE (m, c) IN (('Request for Bids','CW'), ('Request for Bids','NC'), ('Least Cost Selection','CS')) GROUP BY m, c;
-- result: RFB x CW = Invitation for Bids, 28 days, 7862 chars; RFB x NC = Invitation for Bids, 27, 6103;
--         LCS x CS = Request for Expression of Interest, 15, 6267

-- most common tender-notice language per country (same filter as the tool)
SELECT country_code, mode(notice_language) FROM proc_silver.notices
WHERE notice_type IN ('Invitation for Bids','Request for Expression of Interest','Invitation for Prequalification')
  AND notice_language IS NOT NULL AND country_code IN ('TR','NP','JO','MZ') GROUP BY 1;
-- result: TR, NP, JO English; MZ Portuguese

-- h07: amounts of the Independent Verification Agent precedents and the package
SELECT contract_id, borrower_country_code, procurement_method_name, contract_amount_usd FROM proc_silver.contracts
WHERE contract_id IN ('1842441','1732390','1675345','1731924','1604969','1806403');
```

| Brief | Field | Panel (gpt-oss / Llama 4 / Llama 3.3) | Question | Evidence | Decision |
|---|---|---|---|---|---|
| h01 (Türkiye, rural housing works) | unsupported claim | yes / no / no | Is "model forecast assumes Invitation for Bids, 28-day advertising period, 7862-character notice, English" supported? The forecast record shows only P10/P50/P90 | These are the forecast tool's documented defaults (`proc_intel/forecast.py`). Recomputed in the warehouse with the tool's own query: RFB × CW gives Invitation for Bids, 28 days, 7862 characters, and English is the most common tender-notice language for TR. The other claims (all five Request for Bids, 3 to 13 firms, n = 25, all from Uzbekistan) match the facts lines | **no** |
| h02 (regional, wireless network for universities) | precedents relevant (of 4) | 3 / 4 / 1 | Which precedents bought wireless-network equipment? | 1760388 (access points and wireless network system) and 1747630 (backbone switch, wireless network access device) are network equipment. 1641903 is a "wireless presentation device", screen-sharing AV equipment rather than a network. 1705055 is an ERP system with hardware and change-management consultancy | **2** (no majority; a value no judge gave) |
| h03 (Belize, procurement-support consultancy for a 40 MW BESS) | risks relevant (of 4) | 4 / 2 / 4 | Are contractor-capacity (2) and equipment-supply (3) risks about another activity than this consultancy? | The consultant supports procurement of the BESS supply and installation contract. Setting contractor qualification criteria (risk 2's mitigation) and the procurement strategy for supply risk (risk 3's) are within its scope, as for the Owner's Engineer in v1 r01. Risks 1 and 4 (procurement capacity, technical specifications) fit directly | **4** |
| h05 (Nepal, market shed works) | precedents relevant (of 5) | 5 / 1 / 5 | Do region and method make four precedents irrelevant? | All five are market-shed construction works; the rubric excludes country and method | **5** |
| h05 | unsupported claim | no / no / yes | Is "using Request for Bids method in Eastern and Southern Africa" a misstatement of the package region? | It is the reason given for precedent 1767515 (MW, Eastern and Southern Africa, Request for Bids), not a statement about the package. "3 of 5 Request for Bids, 2 Request for Quotations" and "1 recorded 12 firms, 4 not recorded" match the facts lines. The forecast defaults (RFB × CW; English for NP) match the warehouse | **no** |
| h07 (Jordan, IT independent verification entity) | unsupported claim | yes / no / no | Is "Independent Verification Agent contract with larger amount ($1,972,700)" supported? No cited record shows an amount | `proc_silver.contracts`: 1842441 has contract_amount_usd 1,972,700. That is the largest of the five precedents (the others range from 60,000 to 561,890) and above the package's 10,000. The data supports the claim, although the amount is not visible in the cited record | **no** |

**What this round changed:** 6 decisions.
- **Panel majorities overturned: 0.**
- **Confirmed: 5.**
- **No majority settled: 1.** h02's precedent count had three different votes (3 / 4 / 1). It was decided as 2 on the record descriptions.

**Checked but not escalated:**
- **h08:** unanimous unsupported, with no rationale stored. Every checkable claim matches its records: 2 of 3 Request for Bids, 1 firm for 1833519, not recorded for 1620687, and the forecast defaults RFB × NC with Portuguese for MZ. The likely target is risk 2, "LiDAR tender annulment due to grievance for unfair disqualification requiring rebidding". Its cited record, lesson_chunk P147839-34302333-0086, is cut off in the brief's record before that sentence. The full chunk in `proc_silver.lesson_chunks` does contain it ("the initial LiDAR tender was annulled after a bidding firm filed a grievance for unfair disqualification … rebid a month later"). Under the rubric, a detail that appears nowhere in the visible records is unsupported, so the panel's label is consistent with what it saw. Against the full source the claim is supported.
- **h03:** the fact-check pass removed "QCBS or CQS" from the market approach, which now only says to proceed with the planned method. The cited precedents show 4 QCBS and 1 CQS (1646678), so the removed disjunction was true. This does not affect the labels (claims unanimous "no"), but the writer pass over-pruned a correct statement.

---

## Final metrics: v1, v1r, v2 and holdout

All four sets are on final labels: panel where it agreed, tier-3 decisions where it did not, no field pending. Computed with `apply_adjudication.py`. Re-running it on the v1 and v1r inputs reproduces `final_labels.csv` and `final_labels_v1r.csv` byte for byte.

| Metric | v1 final (`final_labels.csv`) | v1r final (rubric v2, facts lines) | **v2 final** (`final_labels_v2.csv`) | **Holdout final** (`final_labels_holdout.csv`) |
|---|---|---|---|---|
| Briefs | 30 | 30 | 30 | 10 |
| Actual duration inside the cited range | 20/30 | 20/30 | 20/30 | 7/10 |
| Briefs listing precedents | 22/30 | 22/30 | 23/30 | 9/10 |
| Mean relevant precedents (briefs listing any) | 3.32 | 3.23 | 3.30 | 4.11 |
| Share of listed precedents relevant | 90% | 88% | 88% | 93% |
| Relevant risks per brief | 3.40 | 3.33 | 3.60 | 3.40 |
| Briefs with an unsupported claim | **5/30** (r06, r10, r17, r26, r30) | **5/30** (r07, r14, r16, r20, r29) | **2/30** (r18, r30) | **1/10** (h08) |

**Reading the comparison:**
- Unsupported claims fall from 5/30 in v1 final to 2/30 in v2 final.
- The like-for-like baseline is v1r, judged with the same rubric and the same facts lines as v2. It is also 5/30, but on different briefs, because the facts lines exposed region and method claims that v1 had missed.
- On the holdout, which the writer pass was never tuned on, the rate is 1/10.
- Precedent and risk quality is level with v1: share relevant is 88–93%, and relevant risks per brief are 3.3–3.6.

**Sensitivity** (items noted above that the owner may want to revisit):
- **r30:** counted (owner-approved override, see Round v2). Without it v2 would be 1/30.
- **r26 and h07:** both were decided as supported on warehouse data that the cited records do not show. Under a visible-records-only reading, v2 would rise by one and the holdout to 2/10.
- **h08:** if it is judged against the full lesson chunk rather than the cut-off record, the holdout becomes 0/10.
