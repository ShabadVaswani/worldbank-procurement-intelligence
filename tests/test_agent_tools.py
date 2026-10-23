import json

import numpy as np
import pytest

from proc_intel.agent_tools import (
    BRIEF_SCHEMA,
    NO_PRECEDENT_GAP,
    TIMELINE_NUMBERS,
    benchmark_key,
    boosted_top_k,
    check_tool_call,
    choose_peer_group,
    choose_precedent_rule,
    compact,
    compare_medians,
    diverse_top_k,
    fit_search_index,
    is_close_precedent,
    is_record_id,
    location_boost,
    numbers_in,
    parse_brief,
    precedent_rule_metrics,
    precision_at_k,
    query_scores,
    record_id,
    render_brief,
    resolve_country,
    resolve_method,
    search_text,
    tool_log_record,
    unsupported_numbers,
    validate_brief,
)
from proc_intel.lessons import chunk_report, decode_report, heading, lesson_chunks, paragraphs_with_sections, relevance

# ---- record ids ---------------------------------------------------------------------------------------------

def test_record_ids_follow_kg_convention():
    assert record_id("contract", 1543858) == "contract:1543858"
    assert is_record_id("supplier_entity:SE-1000002")
    assert is_record_id("document_chunk:P123456_D789_0012") and is_record_id("forecast:0123456789ab")
    assert not is_record_id("contract 1543858") and not is_record_id("invented:1")
    with pytest.raises(AssertionError):
        record_id("project", "P1")


def test_benchmark_key_is_stable_and_level_specific():
    a = benchmark_key("country_method_category", "KE", "Request for Bids", "CW")
    assert a == benchmark_key("country_method_category", "KE", "Request for Bids", "CW")
    assert a != benchmark_key("country_method_category", "TZ", "Request for Bids", "CW")
    assert a.startswith("country_method_category-")


# ---- contract search ----------------------------------------------------------------------------------------

def test_search_text_skips_repeated_parts():
    assert search_text("Rehabilitation of rural roads", "rehabilitation of rural roads", "Rural Access Project") == \
        "Rehabilitation of rural roads | Rural Access Project"
    assert search_text(None, "  Supply of  laptops ", None) == "Supply of laptops"


def _toy_index():
    texts = ["rehabilitation of rural roads lot 2", "rural roads maintenance works", "supply of laptops and printers",
             "rehabilitation of rural roads lot 1", "school construction works"]
    vec, m = fit_search_index(texts, n_features=2 ** 12)
    return texts, vec, m


def test_query_scores_rank_the_obvious_match_first():
    texts, vec, m = _toy_index()
    s = query_scores(vec, m, "Rehabilitation of 120 km rural roads")
    assert int(np.argmax(s)) in (0, 3) and s[2] == 0.0
    norms = np.asarray(m.multiply(m).sum(axis=1)).ravel()
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_boosted_top_k_prefers_local_matches_among_comparable_ones():
    scores = np.array([0.90, 0.60, 0.58, 0.30, 0.05])
    country = np.array(["TZ", "KE", "UG", "KE", "KE"])
    region = np.array(["AFE", "AFE", "AFE", "AFE", "AFE"])
    boost = location_boost(country, region, "KE", "AFE")
    assert boost.tolist() == pytest.approx([0.02, 0.05, 0.02, 0.05, 0.05])
    out = boosted_top_k(scores, boost, k=3, min_score=0.1)
    assert [i for i, _ in out] == [0, 1, 2] and out[1][1] == pytest.approx(0.60)
    out = boosted_top_k(np.array([0.50, 0.52, 0.10]), location_boost(country[:3], region[:3], "KE", None), k=2)
    assert [i for i, _ in out] == [1, 0]                    # 0.50 + 0.05 (KE) beats 0.52 (TZ, no bonus)


def test_boosted_top_k_respects_allowed_and_min_score():
    scores = np.array([0.9, 0.1, 0.7])
    out = boosted_top_k(scores, np.zeros(3), k=3, min_score=0.2, allowed=np.array([False, True, True]))
    assert out == [(2, pytest.approx(0.7))]
    assert boosted_top_k(scores, np.zeros(3), k=3, min_score=0.95) == []


def test_diverse_top_k_caps_items_per_group():
    groups = ["d1", "d1", "d1", "d2", "d1", "d3"]
    assert diverse_top_k([0, 1, 2, 3, 4, 5], groups, k=4, per_group=2) == [0, 1, 3, 5]
    assert diverse_top_k([5, 4], groups, k=4) == [5, 4]


def test_resolve_country_and_method():
    countries = {"KE": "Kenya", "CI": "Cote d'Ivoire"}
    assert resolve_country("ke", countries) == "KE" and resolve_country("cote d'ivoire", countries) == "CI"
    assert resolve_country("Atlantis", countries) is None and resolve_country(None, countries) is None
    methods = {"RFB": "Request for Bids", "QCBS": "Quality And Cost-Based Selection"}
    assert resolve_method("rfb", methods) == "Request for Bids"
    assert resolve_method("quality and cost-based selection", methods) == "Quality And Cost-Based Selection"
    assert resolve_method("Lottery", methods) is None


# ---- benchmark peer group -----------------------------------------------------------------------------------

def test_choose_peer_group_prefers_specific_group_with_enough_contracts():
    groups = [{"level": "category", "n": 5000}, {"level": "method_category", "n": 900},
              {"level": "region_method_category", "n": 45}, {"level": "country_method_category", "n": 12}]
    assert choose_peer_group(groups, min_n=20)["level"] == "region_method_category"
    assert choose_peer_group(groups, min_n=10)["level"] == "country_method_category"
    assert choose_peer_group([{"level": "category", "n": 3}], min_n=20) is None


# ---- tool-call checking -------------------------------------------------------------------------------------

SPECS = {"tender_benchmark": {"parameters": {"type": "object", "required": ["method", "category"], "properties": {
    "country": {"type": "string"}, "method": {"type": "string"},
    "category": {"type": "string", "enum": ["CW", "GO", "CS", "NC"]}, "k": {"type": "integer"}}}}}


def test_check_tool_call_accepts_valid_and_drops_unknown_and_null_args():
    args, err = check_tool_call("tender_benchmark", '{"method": "Request for Bids", "category": "CW", "x": 1, '
                                                    '"country": null, "k": "5"}', SPECS)
    assert err is None and args == {"method": "Request for Bids", "category": "CW", "k": 5}


@pytest.mark.parametrize("name,raw,msg", [
    ("nope", "{}", "unknown tool"),
    ("tender_benchmark", "{not json", "not valid JSON"),
    ("tender_benchmark", '{"method": "RFB"}', "missing required"),
    ("tender_benchmark", '{"method": "RFB", "category": "Works"}', "must be one of"),
    ("tender_benchmark", '{"method": 3, "category": "CW"}', "must be a string"),
    ("tender_benchmark", '{"method": "RFB", "category": "CW", "k": true}', "must be an integer"),
    ("tender_benchmark", '{"method": "RFB", "category": "CW", "k": "five"}', "must be an integer"),
    ("tender_benchmark", '{"method": "RFB", "category": "CW", "k": 2.5}', "must be an integer"),
])
def test_check_tool_call_errors(name, raw, msg):
    args, err = check_tool_call(name, raw, SPECS)
    assert args is None and msg in err


# ---- brief validation ---------------------------------------------------------------------------------------

BM = "benchmark:region_method_category-1a2b3c4d"
FC = "forecast:0123456789ab"
RECORDS = {BM: {"record_id": BM, "type": "benchmark", "p50_days": 150.0, "p90_days": 320.0, "n_contracts": 64,
                "chosen": True},
           "benchmark:category-ffff0000": {"record_id": "benchmark:category-ffff0000", "type": "benchmark",
                                           "p50_days": 140.0, "p90_days": 400.0, "chosen": False},
           FC: {"record_id": FC, "type": "forecast", "scored": True, "p10_days": 70.0, "p50_days": 128.0, "p90_days": 290.0,
                "slow_probability": 0.31, "assumptions": ["advertising period: 42 days (median of Request for Bids x CW)"]},
           "contract:111": {"type": "contract", "label": "Rural roads lot 1", "close_precedent": True},
           "contract:222": {"type": "contract", "label": "Feeder roads", "close_precedent": True},
           "contract:333": {"type": "contract", "label": "Another win of a profiled supplier", "close_precedent": False},
           "document_chunk:P1_D1_0001": {"type": "appraisal_passage"}, "lesson_chunk:P2-D2-0004": {"type": "lesson"},
           "supplier_entity:SE-9": {"type": "supplier_entity"}}


def _timeline(**over):
    t = {"summary": "The model expects about 128 days; the peer-group median is 150 days.",
         "forecast_p10_days": 70, "forecast_p50_days": 128, "forecast_p90_days": 290, "slow_probability": 0.31,
         "peer_p50_days": 150, "peer_p90_days": 320, "citations": [FC, BM]}
    t.update(over)
    return t


def _brief(**over):
    b = {"package_summary": "Rural roads lot 2", "timeline": _timeline(),
         "market_approach": {"recommendation": "Open national RFB", "citations": ["contract:111"]},
         "risks": [{"risk": "Contractor capacity", "mitigation": "Post-qualification", "citations": ["lesson_chunk:P2-D2-0004"]}],
         "precedents": [{"record_id": "contract:111", "why_relevant": "same works"}],
         "evidence_gaps": [], "status": "complete"}
    b.update(over)
    return b


def test_tool_log_records_are_citable_and_stable():
    a = tool_log_record("similar_past_contracts", "no contract passed the precedent rule", candidates_checked=30)
    b = tool_log_record("similar_past_contracts", "no contract passed the precedent rule", candidates_checked=30)
    assert a == b and is_record_id(a["record_id"]) and a["record_id"].startswith("tool_log:similar_past_contracts-")
    assert a["type"] == "tool_log" and a["candidates_checked"] == 30


def test_validate_brief_checks_ids_cited_in_evidence_gaps():
    log = tool_log_record("tender_benchmark", "country peer group skipped: 12 contracts (< 20)")
    recs = {**RECORDS, log["record_id"]: log}
    b = _brief(evidence_gaps=[f"no country benchmark [{log['record_id']}]", "lessons thin [tool_log:lessons_learned-0000000000]"])
    clean, rep = validate_brief(b, recs)
    assert clean["evidence_gaps"] == [f"no country benchmark [{log['record_id']}]", "lessons thin"]
    assert log["record_id"] in rep["cited_ids"] and "tool_log:lessons_learned-0000000000" in rep["invalid_citations"]


def test_validate_brief_cites_the_search_log_in_the_added_no_precedent_gap():
    log = tool_log_record("similar_past_contracts", "no contract passed the precedent rule", candidates_checked=30)
    clean, rep = validate_brief(_brief(precedents=[]), {**RECORDS, log["record_id"]: log})
    assert clean["evidence_gaps"][0] == f"{NO_PRECEDENT_GAP} [{log['record_id']}]" and log["record_id"] in rep["cited_ids"]


def test_validate_brief_keeps_a_fully_cited_brief_unchanged():
    clean, rep = validate_brief(_brief(), RECORDS)
    assert clean == _brief() and rep["flags"] == [] and rep["citation_validity"] == 1.0


def test_validate_brief_drops_invented_ids_and_uncited_risks():
    b = _brief(risks=[{"risk": "Made up", "mitigation": "x", "citations": ["lesson_chunk:FAKE"]},
                      {"risk": "Real", "mitigation": "y", "citations": ["document_chunk:P1_D1_0001", "contract:999"]}],
               precedents=[{"record_id": "contract:999", "why_relevant": "?"},
                           {"record_id": "document_chunk:P1_D1_0001", "why_relevant": "not a contract"},
                           {"record_id": "[contract:222]", "why_relevant": "ok"}])
    clean, rep = validate_brief(b, RECORDS)
    assert [r["risk"] for r in clean["risks"]] == ["Real"]
    assert clean["risks"][0]["citations"] == ["document_chunk:P1_D1_0001"]
    assert [p["record_id"] for p in clean["precedents"]] == ["contract:222"]
    assert set(rep["invalid_citations"]) == {"lesson_chunk:FAKE", "contract:999"}
    assert {"invalid_citation", "uncited_risk"} <= set(rep["flags"]) and clean["status"] == "partial"


def test_validate_brief_corrects_both_timeline_sources_from_their_records():
    b = _brief(timeline=_timeline(forecast_p50_days=100, slow_probability=0.6, peer_p50_days=120, peer_p90_days=None))
    clean, rep = validate_brief(b, RECORDS)
    t = clean["timeline"]
    assert (t["forecast_p50_days"], t["slow_probability"], t["peer_p50_days"], t["peer_p90_days"]) == (128.0, 0.31, 150.0, 320.0)
    assert "timeline_corrected" in rep["flags"] and clean["status"] == "partial"


def test_validate_brief_uses_the_chosen_benchmark_and_adds_a_missing_forecast():
    b = _brief(timeline=_timeline(citations=["benchmark:category-ffff0000"], forecast_p10_days=None, forecast_p50_days=None,
                                  forecast_p90_days=None, slow_probability=None, peer_p50_days=140, peer_p90_days=400,
                                  summary="Peer tenders took a median of 150 days."))
    clean, rep = validate_brief(b, RECORDS)
    t = clean["timeline"]
    assert FC in t["citations"] and BM in t["citations"] and t["forecast_p50_days"] == 128.0 and t["peer_p50_days"] == 150.0
    assert {"forecast_added", "benchmark_added"} <= set(rep["flags"])


def test_validate_brief_clears_uncited_timeline_numbers():
    records = {k: v for k, v in RECORDS.items() if v.get("type") not in ("forecast", "benchmark")}
    b = _brief(timeline=_timeline(citations=["benchmark:invented"], summary="No benchmark."))
    clean, rep = validate_brief(b, records)
    assert clean["timeline"]["peer_p50_days"] is None and clean["timeline"]["forecast_p50_days"] is None
    assert "timeline_uncited" in rep["flags"]


def test_validate_brief_rewrites_a_summary_with_an_invented_number():
    b = _brief(timeline=_timeline(summary="Expect about 4.5 months (128 days)."))
    clean, rep = validate_brief(b, RECORDS)
    assert "timeline_text_replaced" in rep["flags"] and "4.5" not in clean["timeline"]["summary"]
    assert "128" in clean["timeline"]["summary"] and "150" in clean["timeline"]["summary"]
    _, rep2 = validate_brief(_brief(timeline=_timeline(summary="A 42-day advertising period is assumed; 31% chance "
                                                               "of a slow tender; P90 290 days.")), RECORDS)
    assert "timeline_text_replaced" not in rep2["flags"]
    _, rep3 = validate_brief(_brief(timeline=_timeline(summary="The timeline rests on the peer group only.")), RECORDS)
    assert "timeline_text_replaced" in rep3["flags"]
    for wrong in ("The forecast of 129 days is faster than the peer group.", "slightly below the peer group median"):
        _, rep4 = validate_brief(_brief(timeline=_timeline(summary=wrong)), RECORDS)
        assert "timeline_text_replaced" in rep4["flags"], wrong
    assert compare_medians(128, 150) == "the forecast median is 22 days shorter than the peer-group median"
    assert "longer" in compare_medians(193, 118) and "equals" in compare_medians(100, 100.2)


def test_validate_brief_falls_back_when_the_model_could_not_score():
    records = {**{k: v for k, v in RECORDS.items() if k != FC},
               "forecast:ffffffffffff": {"record_id": "forecast:ffffffffffff", "type": "forecast", "scored": False,
                                         "label": "model forecast not available for this package: procurement_method_name "
                                                  "'Direct Selection' not seen in the model's training data",
                                         "p10_days": None, "p50_days": None, "p90_days": None, "slow_probability": None}}
    b = _brief(timeline=_timeline(citations=[BM], summary="Peer group median 150 days."))
    clean, rep = validate_brief(b, records)
    t = clean["timeline"]
    assert t["forecast_p50_days"] is None and t["peer_p50_days"] == 150.0 and "forecast_unavailable" in rep["flags"]
    assert any("Direct Selection" in g and "peer-group" in g for g in clean["evidence_gaps"])


def test_validate_brief_keeps_only_close_precedents_and_says_when_there_are_none():
    b = _brief(precedents=[{"record_id": "contract:333", "why_relevant": "a profiled supplier's win, not a search hit"}])
    clean, rep = validate_brief(b, RECORDS)
    assert clean["precedents"] == [] and {"precedent_not_close", "no_close_precedent"} <= set(rep["flags"])
    assert clean["evidence_gaps"][0] == NO_PRECEDENT_GAP and clean["status"] == "partial"
    already = _brief(precedents=[], evidence_gaps=["No close precedent found outside the held-out project"])
    clean, rep = validate_brief(already, RECORDS)
    assert clean["evidence_gaps"] == already["evidence_gaps"] and "no_close_precedent" in rep["flags"]


def test_validate_brief_caps_precedents_at_five():
    recs = {**RECORDS, **{f"contract:{i}": {"type": "contract", "close_precedent": True} for i in range(10)}}
    b = _brief(precedents=[{"record_id": f"contract:{i}", "why_relevant": "x"} for i in range(8)])
    clean, _ = validate_brief(b, recs)
    assert len(clean["precedents"]) == 5


def test_numbers_in_and_unsupported_numbers():
    assert {128.0, 31.0, 0.31} <= numbers_in({"a": 128, "b": [0.31], "c": "a 1,200-day wait"})
    assert 1200.0 in numbers_in("1,200")
    assert unsupported_numbers("P50 of 128 days, P90 290 (80% interval)", [{"p50_days": 128.0, "p90_days": 290.0}]) == []
    assert unsupported_numbers("about 4 months", [{"p50_days": 128.0}]) == ["4"]


def test_parse_brief_accepts_schema_shape_and_rejects_others():
    ok, err = parse_brief("```json\n" + json.dumps(_brief()) + "\n```")
    assert err is None and ok["status"] == "complete"
    old, err = parse_brief(json.dumps(_brief(timeline={"summary": "x", "citations": []})))
    assert err is None and old["timeline"]["forecast_p50_days"] is None
    bad, err = parse_brief(json.dumps({**_brief(), "status": "great"}))
    assert bad is None and "status" in err
    bad, err = parse_brief('{"package_summary": 1}')
    assert bad is None
    schema = BRIEF_SCHEMA["json_schema"]["schema"]
    assert schema["required"][0] == "package_summary"
    assert "minItems" not in schema["properties"]["precedents"]          # an empty precedent list is valid
    assert set(TIMELINE_NUMBERS) <= set(schema["properties"]["timeline"]["required"])


def test_render_brief_shows_both_timeline_sources_and_no_precedent():
    text = render_brief(_brief(), RECORDS)
    assert f"[{FC}]" in text and f"[{BM}]" in text and "contract:111 Rural roads lot 1" in text
    assert "model forecast for this package: median 128 days" in text and "peer group: median 150 days" in text
    assert NO_PRECEDENT_GAP in render_brief(_brief(precedents=[]), RECORDS)


def _cand(group, rank, cosine, tfidf, relevant):
    return {"group": group, "rank": rank, "cosine": cosine, "tfidf": tfidf, "relevant": relevant}


CANDIDATES = [_cand("a", 1, 0.80, 0.20, True), _cand("a", 2, 0.75, 0.05, False), _cand("a", 3, 0.70, 0.15, True),
              _cand("b", 1, 0.73, 0.06, False), _cand("b", 2, 0.69, 0.07, False),
              _cand("c", 1, 0.66, 0.30, True), _cand("c", 2, 0.60, 0.25, False)]


def test_close_precedent_needs_both_meaning_and_shared_words():
    assert is_close_precedent(0.80, 0.20, 0.68, 0.08)
    assert not is_close_precedent(0.80, 0.05, 0.68, 0.08) and not is_close_precedent(0.60, 0.50, 0.68, 0.08)
    assert not is_close_precedent(None, 0.50, 0.68, 0.08)


def test_precedent_rule_metrics_fill_up_per_package_and_report_empty_ones():
    m = precedent_rule_metrics(CANDIDATES, 0.68, 0.08, k=5)
    assert (m["taken"], m["relevant_taken"]) == (2, 2) and m["precision"] == 1.0
    assert m["recall"] == 2 / 3 and m["zero_groups"] == ["b", "c"]
    assert precedent_rule_metrics(CANDIDATES, 0.0, 0.0, k=1)["taken"] == 3


def test_choose_precedent_rule_prefers_precision():
    best = choose_precedent_rule(CANDIDATES, [0.0, 0.65, 0.68], [0.0, 0.08], beta=0.5)
    assert best["precision"] == 1.0 and best["min_cosine"] == 0.65 and best["min_tfidf"] == 0.08 and best["recall"] == 1.0


# ---- evaluation helpers -------------------------------------------------------------------------------------

def test_precision_at_k_counts_missing_slots_as_misses():
    assert precision_at_k([True, False, True, True, True]) == 0.8
    assert precision_at_k([True, True]) == 0.4
    assert precision_at_k([]) is None


def test_compact_keeps_keys_and_cuts_text():
    out = compact([{"a": 1.23456, "b": "word " * 200, "c": None, "d": 1}], keep=["a", "b", "c"], max_text=20)
    assert out[0]["a"] == 1.235 and out[0]["b"].endswith(" ...") and "c" not in out[0] and "d" not in out[0]


# ---- lesson chunks from completion reports ------------------------------------------------------------------

ICR = """IMPLEMENTATION COMPLETION AND RESULTS REPORT

III. KEY FACTORS THAT AFFECTED IMPLEMENTATION AND OUTCOME

A. Key Factors during Implementation

""" + ("Procurement of the civil works contracts was delayed by fourteen months because the bidding documents were "
       "revised twice and the evaluation committee lacked experience. The contractor mobilised late and the "
       "implementing agency had limited capacity to manage contracts. ") * 3 + """

12

V. LESSONS AND RECOMMENDATIONS

""" + ("Early preparation of designs and bidding documents before effectiveness reduces procurement delays, and "
       "framework agreements helped the project buy goods quickly. ") * 4 + """

ANNEX 1. RESULTS FRAMEWORK

Indicator 1 10 20 30
"""


def test_heading_levels():
    assert heading("V. LESSONS AND RECOMMENDATIONS") == (1, "V. LESSONS AND RECOMMENDATIONS")
    assert heading("B. Fiduciary Compliance") == (2, "B. Fiduciary Compliance")
    assert heading("Procurement") == (2, "Procurement")
    assert heading("ANNEX 1. RESULTS FRAMEWORK")[0] == 1
    assert heading("The project was restructured in 2019 to add a component.") is None
    assert heading("Contents ........ 12") is None
    assert heading("86. The concerned government agencies were highly committed, engaged, and well-coordinated") is None
    assert heading("3.2 Procurement and Contract Management") == (2, "3.2 Procurement and Contract Management")
    head = "IV. BANK PERFORMANCE, COMPLIANCE ISSUES, AND RISK TO DEVELOPMENT OUTCOME"
    assert heading(head) == (1, head)
    assert heading("B. ENVIRONMENTAL, SOCIAL, AND FIDUCIARY COMPLIANCE")[0] == 2


def test_decode_report_falls_back_to_cp1252():
    assert decode_report("Borrower’s report".encode()) == "Borrower’s report"
    assert decode_report("Borrower’s report".encode("cp1252")) == "Borrower’s report"


def test_paragraphs_carry_their_section_and_drop_page_numbers():
    pars = paragraphs_with_sections(ICR)
    secs = [s for s, _ in pars]
    assert any(s.startswith("III. KEY FACTORS") and s.endswith("A. Key Factors during Implementation") for s in secs)
    assert all(p.strip() != "12" for _, p in pars)


def test_chunks_respect_sections_and_size():
    chunks = chunk_report(ICR, target=60, max_words=90)
    assert all(c["n_words"] <= 90 for c in chunks)
    assert len({c["section"] for c in chunks}) >= 2


def test_lesson_chunks_keep_procurement_passages_only():
    kept = lesson_chunks(ICR)
    assert kept and all("LESSON" in c["section"] or "KEY FACTORS" in c["section"] for c in kept)
    assert not relevance("ANNEX 1. RESULTS FRAMEWORK", "Indicator 1 10 20 30")[0]
    me = "The M&E system tracked implementation delays and capacity of the PIU in each district office. " * 5
    assert not relevance("IV. BANK PERFORMANCE, COMPLIANCE ISSUES > A. QUALITY OF M&E > M&E Utilization", me)[0]
    keep, score = relevance("Front matter", "The weather was good and the team met often to discuss the results "
                                            "of the survey with local communities and the ministry staff. " * 3)
    assert not keep
