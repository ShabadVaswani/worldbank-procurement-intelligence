import json

import pytest

from proc_intel.panel import (
    BRIEF_RUBRIC,
    BRIEF_RUBRIC_V2,
    BRIEF_SCHEMA,
    CLAIM_RUBRIC,
    CLAIM_RUBRIC_V2,
    CLAIM_SCHEMA,
    NOT_APPLICABLE,
    PAIR_SCHEMA,
    agreement_with,
    brief_message,
    brief_votes,
    candidate_claims,
    claim_message,
    claim_vote,
    count_majority,
    disagreement,
    er_labels,
    final_value,
    fleiss_kappa,
    listed_items,
    majority,
    normalise,
    output_tag,
    package_facts,
    pair_message,
    pairwise_agreement,
    panel_value,
    parse_json_object,
    review_summary,
    run_tag,
    timeline_vote,
)

BRIEF = """Package: x
Status: complete

Risks and mitigations:
  1. Delays in evaluation. -> Plan early. [lesson_chunk:a]
  2. Weak contractor capacity. -> Post-qualify. [document_chunk:b]
  3. Rain. -> Sequence works. [lesson_chunk:c]

Similar precedents:
  - contract:1 Road works: same kind of works.
  - contract:2 Bridge works: similar.

Evidence gaps:
  - none"""

NO_PRECEDENT_BRIEF = """Risks and mitigations:
  1. Delays. -> Plan.

Similar precedents:
  none (no close precedent found)
"""

# --- messages and listed items ------------------------------------------------------------------------------

def test_listed_items_counts_numbered_and_dash_lines_until_blank_line():
    assert listed_items(BRIEF, "Risks and mitigations") == 3
    assert listed_items(BRIEF, "Similar precedents") == 2
    assert listed_items(NO_PRECEDENT_BRIEF, "Similar precedents") == 0
    assert listed_items("no such heading", "Similar precedents") == 0


def test_messages_carry_every_input():
    m = pair_message("ACME LTD", "ACME LIMITED", "GH", "  2021 P1 roads", "")
    assert "ACME LTD" in m and "ACME LIMITED" in m and "GH" in m and "2021 P1 roads" in m and "(none on record)" in m
    row = {"country": "NE", "category": "CS", "method": "QCBS", "notice_date": "2024-02-05", "description": "supervision",
           "brief_text": BRIEF, "cited_records": json.dumps([{"record_id": "contract:1", "text": "road works"}]),
           "actual_outcome": "signed, 717 days"}
    b = brief_message(row)
    assert "[contract:1] road works" in b and "717 days" in b and "supervision" in b
    assert "(none)" in brief_message({**row, "cited_records": "not json"})


def test_schemas_are_strict_and_list_all_properties_as_required():
    for schema in (PAIR_SCHEMA, BRIEF_SCHEMA, CLAIM_SCHEMA):
        s = schema["json_schema"]["schema"]
        assert schema["json_schema"]["strict"] and set(s["required"]) == set(s["properties"])


# --- parsing and normalising --------------------------------------------------------------------------------

def test_parse_json_object_handles_fences_and_surrounding_text():
    assert parse_json_object('```json\n{"answer": "same"}\n```') == {"answer": "same"}
    assert parse_json_object('Here: {"a": 1} done') == {"a": 1}
    assert parse_json_object("no json") is None
    assert parse_json_object("{broken") is None
    assert parse_json_object(None) is None


@pytest.mark.parametrize("field,value,expected", [
    ("same_firm", "Same", "same"), ("same_firm", "not sure", "unsure"), ("same_firm", "maybe", None),
    ("timeline_ok", True, "yes"), ("timeline_ok", "No", "no"), ("any_unsupported_claim", "0", "no"),
    ("precedents_relevant", 3, "3"), ("precedents_relevant", "2.0", "2"), ("precedents_relevant", "N/A", NOT_APPLICABLE),
    ("risks_relevant", 6, None), ("risks_relevant", -1, None), ("risks_relevant", "two", None), ("risks_relevant", None, None),
])
def test_normalise(field, value, expected):
    assert normalise(field, value) == expected


def test_brief_votes_counts_per_item_verdicts_and_caps_at_listed():
    answer = {"timeline_p10": 198, "timeline_p90": 757, "actual_days": 717, "timeline_reason": "inside",
              "precedents": [{"id": "contract:1", "relevant": True}, {"id": "contract:2", "relevant": False}],
              "precedents_reason": "bridge is not road", "unsupported_claims": [], "unsupported_reason": "",
              "risks": [{"number": i, "relevant": True} for i in (1, 2, 3, 4)], "risks_reason": "all apply"}
    v = brief_votes(answer, n_precedents=2, n_risks=3)
    assert v["timeline_ok"][0] == "yes" and "717 vs range 198-757" in v["timeline_ok"][1]
    assert v["any_unsupported_claim"][0] == "no"
    assert v["precedents_relevant"][0] == "1" and "contract:1" in v["precedents_relevant"][1]
    assert v["risks_relevant"][0] == "3"                       # a fourth verdict for a 3-risk brief is ignored
    assert brief_votes(answer, n_precedents=0, n_risks=3)["precedents_relevant"][0] == NOT_APPLICABLE
    assert all(vote is None for vote, _ in brief_votes(None, 2, 3).values())
    assert brief_votes({**answer, "risks": "bad"}, 2, 3)["risks_relevant"][0] is None
    flagged = brief_votes({**answer, "unsupported_claims": ["used QCBS", " "]}, 2, 3)["any_unsupported_claim"]
    assert flagged[0] == "yes" and '"used QCBS"' in flagged[1]
    assert brief_votes({**answer, "actual_days": 84, "timeline_p10": 96}, 2, 3)["timeline_ok"][0] == "no"


@pytest.mark.parametrize("p10,p90,actual,expected", [
    (96, 262, 84, "no"), (96, 262, 96, "yes"), (96, 262, 262, "yes"), (-1, 300, 120, "yes"), (-1, -1, 120, "no"),
    (50, 100, -1, None), (None, 100, 50, None), ("50", "100", "75", "yes"),
])
def test_timeline_vote_is_computed_from_the_numbers_read(p10, p90, actual, expected):
    assert timeline_vote(p10, p90, actual) == expected


# --- majority and disagreement ------------------------------------------------------------------------------

def test_majority_needs_more_than_half():
    assert majority(["same", "same", "different"]) == "same"
    assert majority(["same", "different", "unsure"]) is None
    assert majority(["yes", None, "yes"]) == "yes"
    assert majority(["yes", None, None]) is None
    assert majority([]) is None


def test_count_majority_is_median_or_na():
    assert count_majority(["1", "4", "2"]) == "2"
    assert count_majority([NOT_APPLICABLE, NOT_APPLICABLE, "1"]) == NOT_APPLICABLE
    assert count_majority([NOT_APPLICABLE, "3", "2"]) == "2"         # lower middle of the numeric votes
    assert count_majority([None, None, None]) is None
    assert panel_value("risks_relevant", ["3", "3", "4"]) == "3" and panel_value("timeline_ok", ["no", "no", "yes"]) == "no"


def test_disagreement_labels_and_binary():
    assert disagreement("same_firm", ["same", "same", "same"]) == ""
    assert disagreement("same_firm", ["same", "same", "different"]) == "judges differ"
    assert disagreement("same_firm", ["unsure"] * 3) == "all judges unsure"
    assert disagreement("timeline_ok", ["yes", None, "yes"]) == "a judge gave no valid answer"


def test_disagreement_counts():
    assert disagreement("risks_relevant", ["3", "4", "3"], n_listed=4) == ""            # all "most relevant"
    assert disagreement("risks_relevant", ["1", "3", "2"], n_listed=4) == "counts differ by 2 or more"
    assert disagreement("risks_relevant", ["2", "3", "3"], n_listed=5) != ""            # 2 of 5 vs 3 of 5: split
    assert disagreement("risks_relevant", ["2", "3", "3"], n_listed=4) == ""            # exactly half sides with neither
    assert disagreement("precedents_relevant", [NOT_APPLICABLE] * 3) == ""
    assert disagreement("precedents_relevant", [NOT_APPLICABLE, "0", "0"]) == "n/a mixed with counts"


# --- agreement statistics -----------------------------------------------------------------------------------

def test_pairwise_agreement_with_and_without_tolerance():
    votes = {"a": ["yes", "no", "yes", None], "b": ["yes", "yes", "yes", "no"], "c": ["yes", "no", "no", "no"]}
    r = pairwise_agreement(votes)
    assert r["pairs"]["a vs b"] == pytest.approx(2 / 3) and r["pairs"]["b vs c"] == pytest.approx(2 / 4)
    assert r["mean"] == pytest.approx((2 / 3 + 2 / 3 + 1 / 2) / 3)
    counts = {"a": ["1", "3", NOT_APPLICABLE], "b": ["2", "5", "0"]}
    assert pairwise_agreement(counts, tolerance=1)["pairs"]["a vs b"] == pytest.approx(1 / 3)


def test_fleiss_kappa_matches_the_textbook_example():
    # Fleiss (1971) worked example as reproduced on Wikipedia: 10 items, 14 raters, 5 categories, kappa 0.210
    table = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
             [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
    items = [[str(c) for c, k in enumerate(row) for _ in range(k)] for row in table]
    assert fleiss_kappa(items) == pytest.approx(0.20993, abs=1e-4)


def test_fleiss_kappa_edge_cases():
    assert fleiss_kappa([["yes", "yes", "yes"], ["no", "no", "no"]]) == pytest.approx(1.0)
    assert fleiss_kappa([["yes"] * 3, ["yes"] * 3]) is None                 # chance agreement 1
    assert fleiss_kappa([["yes", None, "no"]]) is None                      # no complete item
    with pytest.raises(ValueError):
        fleiss_kappa([["yes", "no"], ["yes", "no", "no"]])


def test_agreement_with_reference_skips_missing():
    assert agreement_with(["same", "different", None], ["same", "same", "same"]) == {"n": 2, "agreement": 0.5}
    assert agreement_with([None], ["same"]) == {"n": 0, "agreement": None}


# --- final labels and summaries -----------------------------------------------------------------------------

def test_final_value_prefers_owner_then_panel():
    assert final_value("same_firm", "same", True, "different") == ("different", "owner")
    assert final_value("same_firm", "same", False, "") == ("same", "panel")
    assert final_value("same_firm", "same", True, None) == (None, "pending")
    assert final_value("risks_relevant", "3", True, "4") == ("4", "owner")
    assert final_value("risks_relevant", "3", False, "seven") == ("3", "panel")     # invalid decision is ignored


def test_er_labels_and_review_summary():
    assert er_labels(["same", "different", "unsure", None]) == [True, False, None, None]
    rows = [{"timeline_ok": "yes", "precedents_relevant": "2", "risks_relevant": "3", "any_unsupported_claim": "no", "n_precedents": "4"},
            {"timeline_ok": "no", "precedents_relevant": NOT_APPLICABLE, "risks_relevant": "4", "any_unsupported_claim": "yes",
             "n_precedents": "0"},
            {"timeline_ok": None, "precedents_relevant": "4", "risks_relevant": None, "any_unsupported_claim": "no", "n_precedents": "4"}]
    s = review_summary(rows)
    assert s["timeline_ok"] == {"n": 2, "rate": 0.5}
    assert s["precedents_relevant"] == {"n": 2, "mean": 3.0} and s["briefs_without_precedents"] == 1
    assert s["share_of_listed_precedents_relevant"] == pytest.approx(6 / 8)
    assert s["risks_relevant"] == {"n": 2, "mean": 3.5}
    assert s["any_unsupported_claim"]["rate"] == pytest.approx(1 / 3)


# --- claim check --------------------------------------------------------------------------------------------

def test_candidate_claims_pool_and_deduplicate():
    lists = [['"20 firms participated"', "used QCBS"], ["20 firms participated in similar works"], None, ["", "used QCBS!"]]
    assert candidate_claims(lists) == ["20 firms participated", "used QCBS"]
    assert len(candidate_claims([[f"claim number {i} here" for i in range(20)]], limit=8)) == 8


def test_claim_message_and_vote():
    row = {"country": "NE", "category": "CS", "method": "QCBS", "notice_date": "2024-02-05", "description": "d",
           "brief_text": "b", "cited_records": "[]", "actual_outcome": "o"}
    m = claim_message(row, ["a claim", "another"])
    assert m.endswith("CLAIMS TO CHECK:\n1. a claim\n2. another")
    claims = ["a claim", "another"]
    vote, why = claim_vote({"claims": [{"number": 1, "supported": True}, {"number": 2, "supported": False}], "reason": "x"}, claims)
    assert vote == "yes" and '"another"' in why
    assert claim_vote({"claims": [{"number": 1, "supported": True}, {"number": 9, "supported": False}]}, claims)[0] == "no"
    assert claim_vote({"claims": "bad"}, claims) == (None, "no valid answer")
    assert claim_vote(None, claims)[0] is None


def test_run_tag():
    assert run_tag("review_briefs.csv") == ""
    assert run_tag(" review_briefs_v2.csv ") == "_v2"
    assert run_tag("review_briefs_v2_full.csv") == "_v2_full"
    for bad in ("review_briefs_.csv", "briefs_v2.csv", "review_briefs_v2.csv.bak", "", "review_briefs_V2.csv", "../review_briefs.csv",
                "review_briefs__v2.csv", "review_briefs_v2_.csv"):
        with pytest.raises(ValueError):
            run_tag(bad)


def test_rubric_v2_and_package_facts():
    for rubric in (BRIEF_RUBRIC_V2, CLAIM_RUBRIC_V2):
        assert "tool_log" in rubric and "advice" in rubric
    assert BRIEF_RUBRIC_V2 != BRIEF_RUBRIC and CLAIM_RUBRIC_V2 != CLAIM_RUBRIC
    assert BRIEF_RUBRIC_V2.split("4. any_unsupported_claim")[0] == BRIEF_RUBRIC.split("4. any_unsupported_claim")[0]
    row = {"project_id": "P174034", "country": "NE", "region": "Western and Central Africa", "method": "QCBS",
           "category": "CS", "notice_date": "2024-02-05", "description": "d", "brief_text": "b", "cited_records": "[]",
           "actual_outcome": "o"}
    assert package_facts(row) == "project P174034 | NE | Western and Central Africa | QCBS"
    assert brief_message(row) == brief_message(row, False) and "PACKAGE FACTS" not in brief_message(row)
    assert "\nPACKAGE FACTS: project P174034 | NE | Western and Central Africa | QCBS\nd\n" in brief_message(row, True)
    assert "PACKAGE FACTS" in claim_message(row, ["c"], True) and "PACKAGE FACTS" not in claim_message(row, ["c"])
    assert package_facts({}) == "project not recorded | country not recorded | region not recorded | method not recorded"


def test_output_tag():
    assert output_tag("review_briefs.csv") == ""
    assert output_tag("review_briefs_v1_full.csv", "v2", "_v1r") == "_v1r"
    assert output_tag("review_briefs_v2_full.csv", "v2", "_v2") == "_v2"
    assert output_tag("review_briefs_holdout_full.csv", "v2") == "_holdout_full"
    for args in (("review_briefs.csv", "v2"), ("review_briefs.csv", "v3"), ("review_briefs_v2.csv", "v2", "v2"),
                 ("review_briefs_v2.csv", "v2", "_V2"), ("bad.csv", "v2", "_x")):
        with pytest.raises(ValueError):
            output_tag(*args)
