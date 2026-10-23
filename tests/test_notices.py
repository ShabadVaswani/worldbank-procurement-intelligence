from datetime import date

from proc_intel.notices import html_to_text, parse_award_notice

AWARD_HTML = (
    "<div><h4>Contract Award</h4><p><b>Bid/Contract Reference No:</b>MG-M2PATE-438961-CW-RFQ<br/></p></div>"
    "<div class='col-sm-4'><b>Date Notification of Award Issued</b><br/>(YYYY/MM/DD)<br/>2024/11/20<br/></div>"
    "<div class='col-sm-4'><b>Duration of Contract</b><br/><br/>97 Day(s)<br/></div>"
    "<div><u><b>Awarded Bidder(s):</b></u></div>"
    "<div><b>ENTREPRISE NASOHA (917854)</b><br/>Lot IAA 81<br/>Country: Madagascar<br/></div>"
    "<div><b>Beneficial Ownership Details</b></div><div><b>ENTREPRISE NASOHA (917854)</b>"
    "<table><tr><td>A PRIVATE PERSON (12345)</td><td>MG</td></tr></table></div>"
    "<div><u><b>Evaluated Bidder(s):</b></u></div>"
    "<div><b>SOCIETE MANDIMBISOA S.A.R.L. (917855)</b><br/>Country: Madagascar<br/></div>"
    "<div><b>PT. WIJAYA KARYA (PERSERO) TBK (346407)</b><br/>Country: Indonesia</div>"
    "<div><b>HIDUP INDAH BERKAH (723890)</b></div>"
    "<div><u><b>Rejected Bidder(s):</b></u></div>"
    "<div><b>BINA NUSA LESTARI (621934)</b><br/>Reason for Rejection<br/>Non Responsive</div>"
)


def test_parse_award_notice_dates():
    parsed = parse_award_notice(AWARD_HTML)
    assert parsed["award_notification_date"] == date(2024, 11, 20)
    assert parsed["contract_duration_days"] == 97


def test_parse_award_notice_firms_and_roles():
    firms = parse_award_notice(AWARD_HTML)["firms"]
    assert [(f["supplier_id"], f["role"]) for f in firms] == [
        ("917854", "awarded"), ("917855", "evaluated"), ("346407", "evaluated"),
        ("723890", "evaluated"), ("621934", "rejected")]
    assert firms[0]["name"] == "ENTREPRISE NASOHA" and firms[0]["country_name"] == "Madagascar"
    assert firms[2]["name"] == "PT. WIJAYA KARYA (PERSERO) TBK"
    assert firms[3]["country_name"] is None          # no country line before the next firm


def test_beneficial_ownership_is_never_read():
    ids = {f["supplier_id"] for f in parse_award_notice(AWARD_HTML)["firms"]}
    assert "12345" not in ids


def test_consultant_template_uses_firms_heading():
    markup = ("<u><b>Awarded Firm(s):</b></u><b>HIDROESTRUCTURAS S.A. - GRIMAUX (1109420)</b><br/>Country: Argentina<br/>"
              "<b>Scores</b><u><b>Evaluated Firm(s):</b></u><b>IATASA - 5 DE SEPTIEMBRE (1109421)</b>")
    firms = parse_award_notice(markup)["firms"]
    assert [(f["supplier_id"], f["role"], f["country_name"]) for f in firms] == [
        ("1109420", "awarded", "Argentina"), ("1109421", "evaluated", None)]


def test_anonymous_individual_consultant_has_no_id():
    assert parse_award_notice("<u><b>Awarded Firm(s):</b></u><b>Individual Consultant</b>")["firms"] == []


def test_non_award_notice_and_empty_input():
    assert parse_award_notice("<p>SPECIFIC PROCUREMENT NOTICE</p>")["firms"] == []
    assert parse_award_notice(None)["award_notification_date"] is None


def test_invalid_award_date_is_none():
    assert parse_award_notice("Date Notification of Award Issued 2024/13/45")["award_notification_date"] is None


def test_html_to_text():
    assert html_to_text("<p>Lot&nbsp;1 <b>Roads</b></p>\n<br/>") == "Lot 1 Roads"
    assert html_to_text(None) == ""


def test_small_assignment_template():
    markup = ("<h4>Small Assignment Contract Award</h4><b>Contract Signature Date</b><br/>2017/11/06<br/>"
              "<b>Duration of Contract</b><br/><br/>4 Month(s)<br/>"
              "<u><b>Awarded Firm/Individual:</b></u><b>ENTREPRISE MTC (479517)</b><br/>Country: Centrafrique<br/>")
    parsed = parse_award_notice(markup)
    assert parsed["contract_duration_days"] == 120
    assert parsed["award_notification_date"] is None
    assert [(f["supplier_id"], f["role"]) for f in parsed["firms"]] == [("479517", "awarded")]


def test_firm_without_id_is_skipped():
    markup = "<u><b>Awarded Firm/Individual:</b></u><b>HELVETAS SWISS INTERCOOPERATION</b><br/>Country: Ethiopia"
    assert parse_award_notice(markup)["firms"] == []
