import pytest

from proc_intel.evidence import disconnect, normalise_rating, parse_icrr_ratings, parse_isr_ratings, resolve_evidence

# Snippets written for these tests that copy the fixed-width layouts of the documents' .txt renderings.
ISR_TEXT = """
 EASTERN AND SOUTHERN AFRICA | Congo | Urban Global Practice | FY 2017 | Seq No: 12 | ARCHIVED on 12-Jan-2023 | ISR54772 |

 Overall Ratings

 Name                                                                        Previous Rating                          Current Rating

 Progress towards achievement of PDO                                         Moderately Satisfactory                 Moderately Unsatisfactory

 Overall Implementation Progress (IP)                                        Satisfactory                            Moderately Satisfactory

 Overall Risk Rating                                                         Substantial                             Substantial
"""

FIRST_ISR_TEXT = """Seq No: 1 | ARCHIVED on 10-Jul-2017
Overall Ratings
Name                                                                      Previous Rating                          Current Rating

Progress towards achievement of PDO                                        --                                      Satisfactory
Overall Implementation Progress (IP)                                       --                                      Highly Unsatisfactory
Overall Risk Rating                                                        --                                      Substantial
"""

# Wrapped cells: ICR outcome "Moderately / Satisfactory" around the row label, a reason column on the right.
ICRR_WRAPPED = """11. Ratings
                                                                                   Reason for
Ratings                          ICR                    IEG
                                                                                   Disagreements/Comment
                                 Moderately
Outcome                                                Moderately Satisfactory
                                 Satisfactory
                                                                                   Due to shortcomings of quality at
Bank Performance                 Satisfactory          Moderately Satisfactory
                                                                                   entry, Unsatisfactory M&E
Quality of M&E                   Substantial           Modest
Quality of ICR                   ---                   Substantial
"""

# IEG cell wrapped, ICR cell on one line, and a disagreement comment that contains a rating word.
ICRR_IEG_WRAPPED = """11. Ratings
                                                                                  Reason for
Ratings                         ICR                    IEG
                                                                                  Disagreements/Comment
                                Highly
Outcome                                               Highly Unsatisfactory
                                Unsatisfactory
                                                                                  Satisfactory factors outside
                                                      Moderately
Bank Performance                Unsatisfactory                                    the WB control
                                                      Unsatisfactory
Quality of M&E                  Modest                Modest
"""

# 2024+ ISR template: "Previous / Current" header, an icon glyph (U+F06C) glued to each rating, date wrapped.
ICON = chr(0xF06C)
ISR_2024 = f"""WESTERN AND CENTRAL AFRICA | Nigeria | IBRD/IDA | FY 2014 | Seq No: 24 | Archived
on 23-Apr-2025 | ISR03050

3. OVERALL RATINGS

 Name                                             Previous                             Current

 Progress towards achievement of PDO              {ICON}Moderately Satisfactory             {ICON}Satisfactory

 Overall Implementation Progress (IP)             {ICON}Moderately Satisfactory             {ICON}Moderately Unsatisfactory

 Overall Risk Rating                              {ICON}Moderate                            {ICON}Moderate
"""

# IEG cells start 4 characters LEFT of the "IEG" title, and a page break falls inside the table.
ICRR_LEFT_OF_TITLE = """11. Ratings
                                                                                Reason for
Ratings                         ICR                       IEG
                                                                                Disagreements/Comment

                                                                                                   Page 26 of 28
     Independent Evaluation Group (IEG)                                Implementation Completion Report (ICR) Review
     Naghlu Hydropower Rehabilitation Project (P132944)

                                Moderately            Moderately
Outcome
                                Unsatisfactory        Unsatisfactory
                                Moderately
Bank Performance                                      Moderately Satisfactory
                                Satisfactory
Quality of M&E                  Modest                Modest
"""

ICRR_NOT_RATED = """Ratings                        ICR                    IEG
Outcome                        ---                    Moderately Unsatisfactory

Bank Performance               Satisfactory           Moderately Unsatisfactory

Quality of M&E                 Substantial            Modest
"""


def test_normalise_rating_spellings_and_abbreviations():
    assert normalise_rating("Moderately  satisfactory") == ("Moderately Satisfactory", 4)
    assert normalise_rating("MU") == ("Moderately Unsatisfactory", 3)
    assert normalise_rating("HU") == ("Highly Unsatisfactory", 1)
    assert normalise_rating("Not Rated") is None and normalise_rating("---") is None and normalise_rating(None) is None


def test_parse_isr_previous_and_current():
    r = parse_isr_ratings(ISR_TEXT)
    assert r["seq_no"] == 12 and r["archived_on"].isoformat() == "2023-01-12"
    assert r["pdo_current"] == "Moderately Unsatisfactory" and r["pdo_previous"] == "Moderately Satisfactory"
    assert r["ip_current"] == "Moderately Satisfactory" and r["ip_previous"] == "Satisfactory"


def test_parse_first_isr_placeholder_keeps_order():
    r = parse_isr_ratings(FIRST_ISR_TEXT.replace("\n", "\r\n"))       # documents come with CRLF
    assert r["pdo_previous"] is None and r["ip_previous"] is None
    assert r["pdo_current"] == "Satisfactory" and r["ip_current"] == "Highly Unsatisfactory"


def test_parse_isr_2024_template():
    r = parse_isr_ratings(ISR_2024)
    assert r["seq_no"] == 24 and r["archived_on"].isoformat() == "2025-04-23"
    assert (r["pdo_previous"], r["pdo_current"]) == ("Moderately Satisfactory", "Satisfactory")
    assert (r["ip_previous"], r["ip_current"]) == ("Moderately Satisfactory", "Moderately Unsatisfactory")


def test_parse_isr_without_ratings_block():
    assert parse_isr_ratings("no ratings here")["pdo_current"] is None
    assert parse_isr_ratings(None)["seq_no"] is None


def test_parse_icrr_wrapped_icr_cell_and_reason_column_ignored():
    r = parse_icrr_ratings(ICRR_WRAPPED)
    assert r == {"icr_outcome": "Moderately Satisfactory", "ieg_outcome": "Moderately Satisfactory",
                 "icr_bank_performance": "Satisfactory", "ieg_bank_performance": "Moderately Satisfactory"}


def test_parse_icrr_wrapped_ieg_cell():
    r = parse_icrr_ratings(ICRR_IEG_WRAPPED)
    assert r["icr_outcome"] == "Highly Unsatisfactory" and r["ieg_outcome"] == "Highly Unsatisfactory"
    assert r["icr_bank_performance"] == "Unsatisfactory" and r["ieg_bank_performance"] == "Moderately Unsatisfactory"


def test_parse_icrr_cells_left_of_title_and_page_break():
    r = parse_icrr_ratings(ICRR_LEFT_OF_TITLE)
    assert r == {"icr_outcome": "Moderately Unsatisfactory", "ieg_outcome": "Moderately Unsatisfactory",
                 "icr_bank_performance": "Moderately Satisfactory", "ieg_bank_performance": "Moderately Satisfactory"}


def test_parse_icrr_placeholder_does_not_shift_rows():
    r = parse_icrr_ratings(ICRR_NOT_RATED)
    assert r["icr_outcome"] is None and r["icr_bank_performance"] == "Satisfactory"
    assert r["ieg_outcome"] == "Moderately Unsatisfactory"


def rec(source_type, dimension, rating, as_of, doc_id):
    return {"project_id": "P1", "source_type": source_type, "dimension": dimension, "rating": rating,
            "as_of": as_of, "doc_id": doc_id, "url": f"https://example.org/{doc_id}"}


DISCONNECT = [rec("isr_last", "pdo_progress", "Satisfactory", "2022-12-19", "isr12"),
              rec("isr_last", "implementation_progress", "Moderately Satisfactory", "2022-12-19", "isr12"),
              rec("isr_earlier", "pdo_progress", "Satisfactory", "2020-06-24", "isr6"),
              rec("icr_self_rating", "outcome", "Moderately Unsatisfactory", "2023-07-11", "icr"),
              rec("ieg_validation", "outcome", "Moderately Unsatisfactory", "2023-12-07", "icrr")]


def test_outcome_question_prefers_ieg_and_surfaces_conflicts():
    r = resolve_evidence(DISCONNECT, "outcome")
    assert r["answer"]["source_type"] == "ieg_validation" and r["answer"]["rating"] == "Moderately Unsatisfactory"
    assert [c["source_type"] for c in r["supporting"]] == ["icr_self_rating"]
    assert sorted(c["doc_id"] for c in r["conflicting"]) == ["isr12", "isr6"]
    assert r["flag"] == "conflict" and r["confidence"] == "medium"       # IEG answers, but S vs MU is 2 points
    assert [c["doc_id"] for c in r["not_used"]] == ["isr12"]             # IP does not answer an outcome question
    assert "isr12" in r["rationale"] and "2022-12-19" in r["rationale"]
    assert r["answer"]["url"] == "https://example.org/icrr"


def test_doc_url_column_is_accepted_as_url():
    row = {**rec("ieg_validation", "outcome", "S", "2024-01-01", "icrr"), "url": None, "doc_url": "https://d/1"}
    assert resolve_evidence([row], "outcome")["answer"]["url"] == "https://d/1"


def test_one_point_across_the_line_is_a_disagreement():
    records = [rec("ieg_validation", "outcome", "MU", "2024-01-01", "icrr"),
               rec("isr_last", "pdo_progress", "MS", "2023-01-01", "isr")]
    r = resolve_evidence(records, "outcome")
    assert r["flag"] == "disagreement" and r["confidence"] == "high"
    assert r["conflicting"][0]["points_from_answer"] == 1


def test_without_ieg_the_icr_self_rating_answers_with_lower_confidence():
    records = [rec("icr_self_rating", "outcome", "S", "2024-01-01", "icr"),
               rec("isr_last", "pdo_progress", "MS", "2023-06-01", "isr")]
    r = resolve_evidence(records, "outcome")
    assert r["answer"]["source_type"] == "icr_self_rating"
    assert r["flag"] == "consistent" and r["confidence"] == "medium"
    assert "No independent (IEG) validation" in r["rationale"]


def test_only_isr_evidence_for_outcome_is_low_confidence():
    r = resolve_evidence([rec("isr_last", "pdo_progress", "S", "2023-06-01", "isr")], "outcome")
    assert r["answer"]["specificity"] == "proxy" and r["confidence"] == "low"


def test_current_status_uses_newest_isr_and_keeps_history():
    r = resolve_evidence(DISCONNECT, "current_status", reference_date="2023-03-01")
    assert r["answer"]["doc_id"] == "isr12" and r["answer"]["dimension"] == "implementation_progress"
    assert [c["dimension"] for c in r["supporting"]] == ["pdo_progress"]       # same ISR, 1 point, same side
    assert [c["doc_id"] for c in r["superseded"]] == ["isr6"]
    assert r["confidence"] == "high"
    stale = resolve_evidence(DISCONNECT, "current_status", reference_date="2026-10-20")
    assert stale["confidence"] == "low" and "out of date" in stale["rationale"]


def test_unrated_and_unknown_inputs():
    r = resolve_evidence([rec("ieg_validation", "outcome", "Not Rated", "2024-01-01", "icrr")], "outcome")
    assert r["flag"] == "insufficient" and r["answer"] is None and r["not_used"][0]["specificity"] == "unrated"
    with pytest.raises(ValueError):
        resolve_evidence([], "forecast")


def test_disconnect_definition():
    assert disconnect(4, 3) is True and disconnect(5, 4) is False and disconnect(3, 2) is False
    assert disconnect(None, 3) is None
