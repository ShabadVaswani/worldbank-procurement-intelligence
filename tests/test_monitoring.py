from datetime import date

from proc_intel import monitoring as m

SORT_2025 = """
5. SYSTEMATIC OPERATIONS RISK-RATING TOOL

                                                   Rating at Approval      Last Approved Rating
Risk Category                                      Approval Package -      ISR Seq. 016 - 29 May   Proposed Rating
                                                   30 Jan 2017             2025

Political and Governance                           Low                    Moderate               Moderate

Institutional Capacity for Implementation and
                                                   Moderate               Moderate               Moderate
Sustainability

Fiduciary                                          Substantial            Moderate               Moderate

Overall                                            Moderate               Moderate            Moderate
"""


def test_parse_sort_ratings():
    r = m.parse_sort_ratings(SORT_2025)
    assert r["Fiduciary"] == {"approval": "Substantial", "current": "Moderate", "ratings": ["Substantial", "Moderate", "Moderate"]}
    assert r["Institutional Capacity for Implementation and Sustainability"]["current"] == "Moderate"
    assert r["Overall"]["current"] == "Moderate"
    assert m.parse_sort_ratings(None) == {}


def test_parse_sort_ignores_icon_glyphs():
    text = "Risk Category   Rating\nFiduciary   Substantial   High\n"
    assert m.parse_sort_ratings(text)["Fiduciary"]["current"] == "High"


def test_disbursement_position():
    loans = [{"original_amount": 100, "cancelled_amount": 20, "disbursed_amount": 40,
              "approval_date": date(2020, 1, 1), "closing_date": date(2024, 1, 1)},
             {"original_amount": 20, "cancelled_amount": 0, "disbursed_amount": 0,
              "approval_date": date(2021, 1, 1), "closing_date": date(2025, 1, 1)}]
    p = m.disbursement_position(loans, date(2022, 7, 2))
    assert p["net_commitment"] == 100 and p["disbursed_share"] == 0.4
    assert abs(p["elapsed_share"] - 0.5) < 0.01
    assert m.disbursement_position([{"original_amount": 0}], date(2022, 1, 1)) is None


def test_expected_share_and_months():
    assert m.expected_share({0: 0.0, 5: 0.4, 9: 0.9}, 0.55) == 0.4
    assert m.expected_share({9: 0.9}, 1.0) == 0.9
    assert round(m.months_between(date(2024, 1, 1), date(2025, 1, 1))) == 12
    assert m.months_between(None, date(2025, 1, 1)) is None


def test_isr_and_fiduciary_signals():
    s = m.isr_signal("Satisfactory", "Moderately Satisfactory", "Moderately Satisfactory", "Moderately Unsatisfactory")
    assert s["unsatisfactory"] == ["IP"] and s["downgraded"] == ["PDO", "IP"] and s["triggered"]
    assert not m.isr_signal("Satisfactory", "Satisfactory", None, "Satisfactory")["triggered"]
    assert m.fiduciary_signal("Moderate", "Substantial")["triggered"]
    assert not m.fiduciary_signal("Substantial", "Substantial")["triggered"]
    assert m.fiduciary_signal("High", "High")["triggered"]


def _project(**kw):
    base = {"as_of": date(2026, 10, 1), "stalled_tenders": [], "recent_timed": 4, "recent_slow": 1,
            "disbursed_share": 0.5, "elapsed_share": 0.5, "expected_share": 0.45, "loan_ids": ["IDA61230"],
            "closing_now": date(2027, 6, 30), "closing_before": date(2027, 6, 30), "window_start": date(2024, 9, 30),
            "isr": {"doc_id": "D1", "as_of": date(2026, 6, 1), "pdo_prev": "Satisfactory", "pdo_cur": "Satisfactory",
                    "ip_prev": "Satisfactory", "ip_cur": "Satisfactory", "fiduciary_approval": "Moderate",
                    "fiduciary_current": "Moderate"}}
    base.update(kw)
    return base


def test_quiet_project_has_no_alert():
    a = m.alert(m.indicators(_project()))
    assert a["level"] == "none" and a["n_no_data"] == 0


def test_red_alert_with_reasons_and_citations():
    isr = {**_project()["isr"], "ip_cur": "Moderately Unsatisfactory"}
    p = _project(disbursed_share=0.1, expected_share=0.45, isr=isr,
                 stalled_tenders=[{"notice_id": "OP1", "days_elapsed": 400, "p90_days": 300}])
    a = m.alert(m.indicators(p))
    assert a["level"] == "red"
    assert a["triggered"] == ["disbursement_lag", "isr_ratings", "stalled_tenders"]
    assert "notice:OP1" in a["citations"] and "document:D1" in a["citations"] and "loan:IDA61230" in a["citations"]
    assert any("OP1 open 400 days vs P90 300" in r for r in a["reasons"])


def test_missing_data_is_counted_not_triggered():
    p = _project(isr=None, disbursed_share=None, recent_timed=1, closing_before=None)
    inds = {i["indicator"]: i for i in m.indicators(p)}
    assert inds["isr_ratings"]["status"] == "no_data" and inds["slow_signings"]["status"] == "no_data"
    assert m.alert(list(inds.values()))["n_no_data"] == 5


def test_disbursement_not_judged_early_and_extension():
    early = {i["indicator"]: i for i in m.indicators(_project(disbursed_share=0.0, expected_share=0.25, elapsed_share=0.2))}
    assert early["disbursement_lag"]["status"] == "ok"
    ext = {i["indicator"]: i for i in m.indicators(_project(closing_now=date(2028, 6, 30)))}
    assert ext["closing_extended"]["status"] == "triggered" and ext["closing_extended"]["value"] == 12.0


CELLS_2026 = """FSM Skills and Employability Enhancement Project (P176965)
EAST ASIA AND PACIFIC | Micronesia | IBRD/IDA | Investment Project Financing (IPF) | FY 2022 | Seq
No: 9 | Archived on 03-Jul-2026 | ISR08323
3. OVERALL RATINGS
Name

Previous

Current

Progress towards achievement of PDO

Moderately Unsatisfactory

Moderately Satisfactory

Overall Implementation Progress (IP)

Moderately Satisfactory

Moderately Satisfactory

5. SYSTEMATIC OPERATIONS RISK-RATING TOOL

Risk Category

Rating at Approval

Institutional Capacity for Implementation and
Sustainability

\uf06cSubstantial

\uf06cSubstantial

\uf06cSubstantial

Fiduciary

\uf06cModerate

\uf06cSubstantial

\uf06cHigh

Environment and Social

\uf06cModerate
"""


def test_parse_isr_cells_layout_2026():
    r = m.parse_isr_cells(CELLS_2026)
    assert r["pdo_previous"] == "Moderately Unsatisfactory" and r["pdo_current"] == "Moderately Satisfactory"
    assert r["ip_current"] == "Moderately Satisfactory"
    assert r["seq_no"] == 9 and r["archived_on"] == date(2026, 7, 3)
    assert m.parse_isr_cells(SORT_2025)["pdo_current"] is None          # fixed-width layout is not this parser's job


def test_parse_sort_cells_layout_2026():
    s = m.parse_sort_ratings(CELLS_2026)
    assert s["Fiduciary"] == {"approval": "Moderate", "current": "High", "ratings": ["Moderate", "Substantial", "High"]}
    assert s["Institutional Capacity for Implementation and Sustainability"]["current"] == "Substantial"
    assert s["Environment and Social"]["current"] == "Moderate"


def test_alert_citations_are_unique():
    isr = {**_project()["isr"], "ip_cur": "Moderately Unsatisfactory", "fiduciary_current": "High"}
    a = m.alert(m.indicators(_project(isr=isr)))
    assert a["citations"].count("document:D1") == 1
