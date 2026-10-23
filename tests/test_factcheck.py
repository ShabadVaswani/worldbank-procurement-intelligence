"""Tests for the code fact-check of written briefs (src/proc_intel/factcheck.py).

The cases are the review-pack errors found by the tier-3 adjudication (data/human_review/adjudication_log.md)
and the claims it confirmed as correct, so the check removes the first and keeps the second."""
from proc_intel.factcheck import canonical_methods, contract_facts, extract_claims, factcheck_brief, factcheck_sentence, split_sentences


def contract(cid, project, country, method, firms, days=None, region="LCR", signed="2023-05-01"):
    return {"record_id": f"contract:{cid}", "type": "contract", "project_id": project, "country_code": country,
            "region": region, "method": method, "n_firms_in_award_notice": firms, "days_notice_to_signing": days,
            "signing_date": signed, "label": f"contract {cid}", "close_precedent": True}


PERU = {"project_id": "P174177", "country_code": "PE", "region": "LCR", "method": "Quality And Cost-Based Selection"}
R10 = {r["record_id"]: r for r in [
    contract(1869249, "P174177", "PE", "Quality And Cost-Based Selection", 2),
    contract(1869269, "P174177", "PE", "Quality And Cost-Based Selection", 5),
    contract(1755956, "P163255", "PE", "Quality And Cost-Based Selection", 6),
]}


# ------------------------------------------------------------------ record facts and parsing

def test_contract_facts_names_every_checkable_field():
    rec = contract(1597637, "P146314", "LK", "Request for Bids", 3, region="South Asia", signed="2019-02-11")
    assert contract_facts(rec) == "project P146314 | LK | South Asia | Request for Bids | 2019 | firms in award notice: 3"
    rec["n_firms_in_award_notice"] = None
    assert contract_facts(rec).endswith("firms in award notice: not recorded")


def test_split_sentences_keeps_abbreviations_together():
    s = split_sentences("Use RFB, e.g. as in 2021. Precedents had 2 to 5 firms. Done")
    assert s == ["Use RFB, e.g. as in 2021.", "Precedents had 2 to 5 firms.", "Done"]


def test_canonical_methods_reads_names_and_abbreviations():
    assert canonical_methods("used RFQ and Quality and Cost-Based Selection (QCBS)") == {
        "Request for Quotations", "Quality And Cost-Based Selection"}
    assert canonical_methods("physics lessons") == set()          # 'ics' inside a word is not ICS


def test_extract_claims_kinds():
    kinds = [c["kind"] for c in extract_claims(
        "In the same project 2 to 6 firms bid, up to 11 bidders, 158 days, 31% slow, project P163255, via RFB.")]
    assert kinds.count("firm_range") == 1 and kinds.count("firm_count") == 1
    assert {"same_project", "days", "percent", "project_id", "method"} <= set(kinds)


def test_advice_and_interpretation_are_not_claims():
    assert extract_claims("Invite at least 5 firms and allow at least 30 days for bids.") == []
    assert extract_claims("A precedent in a similar regional context with similar scope.") == []


# ------------------------------------------------------------------ the adjudicated cases

def test_r10_same_project_range_is_fixed_to_the_project_records():
    s = "Recent similar contracts in the same project attracted between 2 and 6 bidding firms."
    new, events = factcheck_sentence(s, list(R10.values()), PERU)
    assert new == "Recent similar contracts in the same project attracted between 2 and 5 bidding firms."
    assert [e["action"] for e in events] == ["fixed"]


def test_range_over_all_cited_records_holds():
    s = "Similar QCBS contracts attracted 2 to 6 firms."
    new, events = factcheck_sentence(s, list(R10.values()), PERU)
    assert new == s and events == []


def test_r06_same_project_with_other_project_id_is_removed():
    rec = contract(1597637, "P146314", "LK", "Request for Quotations", None, region="SAR")
    pkg = {"project_id": "P160005", "country_code": "LK", "region": "SAR", "method": "Request for Bids"}
    new, events = factcheck_sentence("Similar canal improvement works in Sri Lanka under the same project ID.", [rec], pkg)
    assert new is None and events[0]["action"] == "removed" and "same project" in events[0]["reason"]


def test_same_project_without_package_project_is_unsupported():
    new, _ = factcheck_sentence("Done in the same project.", list(R10.values()), {**PERU, "project_id": None})
    assert new is None


def test_r05_range_ignores_records_without_an_award_notice():
    recs = [contract(1686805, "P1", "PH", "Request for Quotations", 1), contract(1727398, "P2", "PH", "Request for Quotations", 3),
            contract(1753945, "P3", "PH", "Request for Quotations", 1), contract(1624879, "P4", "PH", "Request for Quotations", None)]
    s = "Similar vehicle packages used Request for Quotations with 1 to 3 firms."
    assert factcheck_sentence(s, recs, {"project_id": "P9", "country_code": "PH", "method": "Request for Bids"}) == (s, [])


def test_r09_up_to_is_the_maximum():
    recs = [contract(1759454, "P1", "PH", "Request for Bids", 11), contract(2, "P2", "PH", "Request for Bids", 4)]
    assert factcheck_sentence("Up to 11 firms participated.", recs, {})[1] == []
    new, ev = factcheck_sentence("Up to 12 firms participated.", recs, {})
    assert new == "Up to 11 firms participated." and ev[0]["action"] == "fixed"


def test_r18_single_record_count_and_method():
    rec = contract(1611409, "P1", "TO", "Request for Bids", 8)
    assert factcheck_sentence("Awarded via Request for Bids with 8 firms.", [rec], {})[1] == []
    new, ev = factcheck_sentence("Awarded via Request for Bids with 6 firms.", [rec], {})
    assert new == "Awarded via Request for Bids with 8 firms." and ev[0]["action"] == "fixed"


def test_count_that_matches_no_record_is_removed_when_ambiguous():
    new, ev = factcheck_sentence("Precedents attracted 9 firms.", list(R10.values()), PERU)
    assert new is None and ev[0]["action"] == "removed"


def test_count_without_any_firm_field_is_removed():
    rec = contract(1, "P1", "PE", "Request for Bids", None)
    assert factcheck_sentence("The precedent attracted 4 bidders.", [rec], {})[0] is None


def test_r26_in_the_region_needs_a_record_from_the_package_region():
    recs = [contract(1638806, "P1", "KE", "Request for Quotations", 2, region="AFE"),
            contract(1755857, "P2", "3W", "Request for Quotations", 1, region="WCA")]
    pkg = {"project_id": "P159519", "country_code": "GY", "region": "LCR", "method": "Request for Bids"}
    s = ("Proceed with Request for Bids as planned. Smaller similar furniture contracts in the region often "
         "utilized Request for Quotations.")
    new, ev = factcheck_sentence(s.split(". ")[1], recs, pkg)
    assert new is None and "region" in ev[0]["reason"]


def test_method_must_be_planned_or_in_a_cited_record():
    recs = [contract(1, "P1", "IN", "Request for Quotations", 2)]
    pkg = {"method": "Request for Bids"}
    assert factcheck_sentence("Proceed with Request for Bids; precedents used RFQ.", recs, pkg)[1] == []
    assert factcheck_sentence("Precedents used QCBS.", recs, pkg)[0] is None


def test_same_country():
    recs = [contract(1, "P1", "KE", "Request for Bids", 2)]
    assert factcheck_sentence("A precedent in the same country.", recs, {"country_code": "KE"})[1] == []
    assert factcheck_sentence("A precedent in the same country.", recs, {"country_code": "UG"})[0] is None


def test_days_and_percent_and_project_id():
    bench = {"record_id": "benchmark:x", "type": "benchmark", "p10_days": 70.0, "p50_days": 158.0, "p90_days": 354.0,
             "slow_rate": 0.31}
    recs = [bench, contract(1755956, "P163255", "PE", "Request for Bids", 6, days=120)]
    assert factcheck_sentence("Peer tenders took 158 days (P90 354 days), 31% were slow.", recs, {})[1] == []
    assert factcheck_sentence("Peer tenders took 200 days.", recs, {})[0] is None
    assert factcheck_sentence("Peer tenders were 45% slow.", recs, {})[0] is None
    assert factcheck_sentence("As in project P163255.", recs, {})[1] == []
    assert factcheck_sentence("As in project P999999.", recs, {})[0] is None


def test_days_range_of_contracts_is_fixed():
    recs = [contract(1, "P1", "KE", "Request for Bids", 2, days=70), contract(2, "P2", "KE", "Request for Bids", 3, days=354)]
    new, ev = factcheck_sentence("Precedents took 90 to 354 days.", recs, {})
    assert new == "Precedents took 70 to 354 days." and ev[0]["action"] == "fixed"


# ------------------------------------------------------------------ the whole brief

def _brief():
    return {"package_summary": "Technical files for 2 to 9 schools.",              # not cited: not checked
            "timeline": {"summary": "The model forecasts the median.", "citations": []},
            "market_approach": {"recommendation": "Use QCBS. Recent similar contracts in the same project attracted "
                                                  "between 2 and 6 bidding firms.",
                                "citations": list(R10)},
            "risks": [{"risk": "In the same project 9 firms withdrew.", "mitigation": "Invite at least 5 firms.",
                       "citations": ["contract:1755956"]},
                      {"risk": "Delays in approvals.", "mitigation": "Plan approvals early.", "citations": ["contract:1869249"]}],
            "precedents": [{"record_id": "contract:1755956", "why_relevant": "Same project, similar files."},
                           {"record_id": "contract:1869249", "why_relevant": "Similar scope with 2 firms."}],
            "evidence_gaps": [], "status": "complete"}


def test_factcheck_brief_fixes_removes_and_reports():
    out, report = factcheck_brief(_brief(), R10, PERU)
    assert out["market_approach"]["recommendation"] == ("Use QCBS. Recent similar contracts in the same project "
                                                       "attracted between 2 and 5 bidding firms.")
    assert [r["risk"] for r in out["risks"]] == ["Delays in approvals."]          # the only sentence was wrong
    assert out["precedents"][0]["why_relevant"] == contract_facts(R10["contract:1755956"])
    assert out["precedents"][1]["why_relevant"] == "Similar scope with 2 firms."
    assert out["package_summary"] == "Technical files for 2 to 9 schools."
    assert set(report["flags"]) == {"factcheck_removed", "factcheck_fixed"}
    assert report["n_removed"] == 2 and report["n_fixed"] == 1 and report["n_claims_checked"] >= 5
    assert all({"field", "before", "after", "reason"} <= set(e) for e in report["events"])


def test_factcheck_brief_leaves_a_correct_brief_alone():
    b = _brief()
    b["market_approach"]["recommendation"] = "Use QCBS: similar contracts attracted 2 to 6 firms."
    b["risks"] = b["risks"][1:]
    b["precedents"] = b["precedents"][1:]
    out, report = factcheck_brief(b, R10, PERU)
    assert out == b and report["flags"] == [] and report["events"] == []


def test_factcheck_brief_empty_recommendation_gets_a_neutral_line():
    b = _brief()
    b["market_approach"]["recommendation"] = "Precedents in the same country used Fixed Budget Selection."
    out, _ = factcheck_brief(b, R10, PERU)
    assert out["market_approach"]["recommendation"].startswith("Proceed with the planned method (Quality And Cost-Based")


# ------------------------------------------------------------------ quantified claims (round 2: r30)

R30 = [contract(1673387, "P145309", "UG", "Request for Quotations", 6), contract(1697835, "P172176", "ZW", "Request for Quotations", 1),
       contract(1755584, "P169265", "3W", "Request for Quotations", 3), contract(1762765, "P127741", "PH", "Request for Quotations", 1),
       contract(1718615, "P153349", "KE", "Request for Quotations", None)]
ETHIOPIA = {"project_id": "P171034", "country_code": "ET", "region": "AFE", "method": "Request for Bids"}


def test_r30_all_five_with_a_missing_count_is_qualified():
    s = "All five close precedents used Request for Quotations with 1 to 6 firms in award notices."
    new, ev = factcheck_sentence(s, R30, ETHIOPIA)
    assert new == ("All five close precedents used Request for Quotations with 1 to 6 firms (among the 4 with a "
                   "recorded count) in award notices.")
    assert ev[0]["action"] == "fixed"


def test_quantified_range_with_every_count_recorded_is_unchanged():
    s = "All four precedents used Request for Quotations with 1 to 6 firms."
    assert factcheck_sentence(s, R30[:4], ETHIOPIA) == (s, [])


def test_quantifier_count_must_match_the_cited_contracts():
    assert factcheck_sentence("All four close precedents used Request for Quotations.", R30, ETHIOPIA)[0] is None
    assert factcheck_sentence("Both precedents used Request for Quotations.", R30[:2], ETHIOPIA)[1] == []


def test_quantified_method_must_hold_for_every_contract():
    recs = R30[:2] + [contract(9, "P9", "ET", "Request for Bids", 4)]
    new, ev = factcheck_sentence("All three precedents used Request for Quotations.", recs, ETHIOPIA)
    assert new is None and "Request for Bids" in ev[0]["reason"]
    # the planned method is a recommendation, not a claim about every precedent
    assert factcheck_sentence("Use Request for Bids, as for all three contracts' peer group.", recs, ETHIOPIA)[0] is not None


def test_each_with_a_single_count():
    recs = [contract(1, "P1", "ET", "Request for Bids", 3), contract(2, "P2", "ET", "Request for Bids", 3)]
    assert factcheck_sentence("Each contract attracted 3 firms.", recs, ETHIOPIA)[1] == []
    recs[1]["n_firms_in_award_notice"] = 4
    assert factcheck_sentence("Each contract attracted 3 firms.", recs, ETHIOPIA)[0] is None


def test_region_check_uses_the_region_field():
    recs = [contract(1, "P1", "IN", "Request for Bids", 4, region="South Asia")]
    pkg = {"region": "South Asia", "country_code": "LK"}
    assert factcheck_sentence("A precedent from the same region.", recs, pkg)[1] == []
    assert factcheck_sentence("A precedent from the same region.", recs, {**pkg, "region": "East Asia and Pacific"})[0] is None


# ------------------------------------------------------------------ round-2 review of the regenerated pack

R17 = [contract(1800554, "P163461", "PK", "Request for Bids", 3), contract(1743544, "P152698", "IN", "Request for Quotations", 3),
       contract(1639517, "P146788", "UA", "Request for Bids", 5), contract(1706073, "P150220", "BD", "Request for Bids", 8),
       contract(1753939, "P163673", "RS", "Request for Bids", 3)]
R13 = [contract(1676530, "P171059", "SL", "Request for Bids", 1), contract(1722584, "P120014", "KE", "Request for Bids", 1),
       contract(1722590, "P120014", "KE", "Request for Bids", 1), contract(1773824, "P165183", "FM", "Request for Bids", None),
       contract(1889915, "P181253", "FM", "Direct Selection", 1)]


def test_r17_quantifier_after_the_methods_does_not_quantify_them():
    s = ("Use Request for Bids, consistent with 4 of 5 close precedents that used Request for Bids, while 1 precedent "
         "used Request for Quotations; firms in award notices ranged from 3 to 8 across all precedents.")
    assert factcheck_sentence(s, R17, {"method": "Request for Bids"}) == (s, [])


def test_r13_all_five_used_this_method_is_checked_against_every_precedent():
    s = ("Use Request for Bids method as all 5 close precedents employed this method for similar works, "
         "with 1 firm in award notice across 4 of 5 records.")
    new, ev = factcheck_sentence(s, R13, {"method": "Request for Bids"})
    assert new is None and "Direct Selection" in ev[0]["reason"]


def test_a_sentence_that_already_qualifies_its_count_gets_no_second_qualifier():
    s = "All four precedents used Request for Bids, with 1 firm in the award notice across 3 of 4 records."
    assert factcheck_sentence(s, R13[:4], {"method": "Request for Bids"}) == (s, [])


def test_among_the_n_with_recorded_counts_is_checked():
    s = "Precedents had 1 to 6 firms among the 2 with recorded counts."
    recs = [contract(1, "P1", "PE", "QCBS", 1), contract(2, "P2", "PE", "QCBS", 6), contract(3, "P3", "PE", "QCBS", None),
            contract(4, "P4", "PE", "QCBS", 1)]
    new, ev = factcheck_sentence(s, recs, {})
    assert new == "Precedents had 1 to 6 firms among the 3 with recorded counts." and ev[0]["action"] == "fixed"


# ------------------------------------------------------------------ holdout findings (h02, h06)

H02 = [contract(1760388, "P1", "BD", "Request for Bids", 3), contract(1747630, "P2", "BD", "Request for Bids", 5),
       contract(1641903, "P3", "BD", "Request for Bids", None), contract(1700000, "P4", "BD", "Request for Bids", 9)]


def test_h02_a_listed_set_of_contracts_is_quantified():
    s = "Contracts 1760388, 1747630 and 1641903 had 3 to 5 firms in their award notices."
    new, ev = factcheck_sentence(s, H02, {})
    assert new == ("Contracts 1760388, 1747630 and 1641903 had 3 to 5 firms (among the 2 with a recorded count) in "
                   "their award notices.") and ev[0]["action"] == "fixed"
    # the range is checked against the listed contracts, not every cited one (1700000 had 9)
    new, _ = factcheck_sentence("Contracts 1760388 and 1747630 had 3 to 9 firms.", H02, {})
    assert new == "Contracts 1760388 and 1747630 had 3 to 5 firms."


def test_h02_listed_contracts_and_a_method():
    s = "contract:1760388 and contract:1641903 used Request for Quotations."
    assert factcheck_sentence(s, H02, {"method": "Request for Quotations"})[0] is None


def test_h06_no_qualifier_when_the_missing_count_is_already_stated():
    for s in ("Contracts 1760388, 1747630 and 1641903 had 3 to 5 firms (1 not recorded).",
              "All four precedents had 3 to 9 firms, with no award notice for one of them.",
              "Firm counts ranged from 3 to 9 across 3 of 4 precedents."):
        assert factcheck_sentence(s, H02, {}) == (s, []), s


def test_a_project_id_inside_an_inline_record_id_is_not_a_claim():
    s = "Packaging should aim to attract international bids [lesson_chunk:P120788-34204838-0183]."
    assert factcheck_sentence(s, [contract(1, "P1", "TO", "Request for Bids", 2)], {}) == (s, [])
