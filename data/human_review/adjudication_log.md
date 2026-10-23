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

- The adjudicator is an AI agent (Claude, Anthropic), not a person. Its decisions carry written evidence so a person can audit them, but they are not human labels.
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
