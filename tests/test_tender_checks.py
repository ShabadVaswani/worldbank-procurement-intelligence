from proc_intel import tender_checks as tc


def test_notice_text_strips_html():
    assert tc.notice_text("<p>Bid&nbsp;Security</p><br/>of <b>US$&nbsp;5,000</b>") == "Bid Security\n\nof US$ 5,000"


def test_parse_amount_formats():
    assert tc.parse_amount("1,500,000.00", None) == 1_500_000.0
    assert tc.parse_amount("25 000,00", None) == 25_000.0
    assert tc.parse_amount("2.5", "million") == 2_500_000.0
    assert tc.parse_amount("425,000", None) == 425_000.0


def test_money_mentions_currencies_and_false_codes():
    assert tc.money_mentions("Bid Security of USD 5,000.00 /USD Five Thousand/") == [(5000.0, "USD")]
    assert tc.money_mentions("of 6,000,000.00 Tanzania Shillings.") == [(6_000_000.0, "Tanzania Shillings")]
    assert tc.money_mentions("a Bid Security of KES 6,000,000.00 in the form") == [(6_000_000.0, "KES")]
    assert tc.money_mentions("valid for 3,000 days for lot 2,500") == []          # 'for' and 'lot' are not currencies


def test_bid_security_kinds():
    assert tc.bid_security("Bid Security shall be Two (2%) percent of the bidder's tender price")["percent"] == 2.0
    sec = tc.bid_security("Bid Security in amount of: Lot #1 - 500 US dollars; Lot #2 - US$ 3,000; Lot #3 - USD 1,500")
    assert sec["kind"] == "amount" and sec["amount"] == 3000.0 and sec["currency"] == "USD" and sec["n_amounts"] == 3
    assert tc.bid_security("must be accompanied by a Bid-Securing Declaration.")["kind"] == "declaration"
    assert tc.bid_security("Bid Security is not applicable.")["kind"] == "not_required"
    assert tc.bid_security("Bids must be accompanied by a Bid Security in the acceptable format")["kind"] == "mentioned"
    assert tc.bid_security("Bids will be opened in public.")["kind"] is None


def test_market_approach():
    assert tc.market_approach("RFB - OPEN NATIONAL IFB No.: MLGDRD/SOCO") == "national"
    assert tc.market_approach("Market approach: Open - International") == "international"
    assert tc.market_approach("conducted through International Competitive Bidding (ICB)") == "international"
    assert tc.market_approach("no statement", "Request for Bids") is None


def test_lots_validity_submission_prebid():
    assert tc.n_lots("Lot 1: dams. Lot 2: roads. LOT 3 - boreholes") == 3
    assert tc.n_lots("The works are divided into four lots") == 4
    assert tc.n_lots("one package") is None
    assert tc.bid_validity_days("Bids shall be valid for a period of 90 days after bid opening") == 90
    assert tc.bid_validity_days("valid for 7 days") is None
    assert tc.electronic_submission("Electronic Bidding will not be permitted.") is False
    assert tc.electronic_submission("Bids must be submitted online on the e-procurement portal") is True
    assert tc.electronic_submission("Bids must be delivered to the address below") is None
    assert tc.pre_bid_meeting("A Mandatory Pre-Bid Meeting shall be held on July 24") == "mandatory"
    assert tc.pre_bid_meeting("A pre-bid conference will be held") == "held"


def test_qualification():
    q = tc.qualification("Minimum average annual construction turnover of US$ 2,000,000 over the last 3 years. "
                         "Bidders shall have at least five (5) years of experience and at least two similar contracts.")
    assert q["turnover_amount"] == 2_000_000.0 and q["turnover_currency"] == "USD"
    assert q["experience_years"] == 5 and q["similar_contracts"] == 2


def test_policy_minimum():
    assert tc.policy_min_calendar_days("international") == 42
    assert tc.policy_min_calendar_days("national") is None
    assert tc.policy_min_calendar_days(None, "Request for Expression of Interest") == 14


def test_quantile_and_peer_lookup():
    assert tc.quantile([1, 2, 3, 4, 5], 0.5) == 3
    assert tc.quantile([], 0.5) is None
    peers = {"advertising_days": {("country", "KE", "CW", "national"): tc.peer_stats(list(range(5))),
                                  ("category", "CW", "national"): tc.peer_stats(list(range(10, 60)))}}
    stats, key = tc.peer_lookup(peers, "advertising_days", tc.peer_keys({"country": "KE", "category": "CW",
                                                                         "market_approach": "national"}))
    assert key == ("category", "CW", "national") and stats["n"] == 50       # the country group has too few peers


def _peers():
    return {"advertising_days": {("category", "CW", "international"): tc.peer_stats([40 + i % 20 for i in range(100)])},
            "lot_size_usd": {("region", "AFE", "CW", "any"): tc.peer_stats([1e5 * (1 + i) for i in range(100)])},
            "bid_security_percent": {("category", "CW", "any"): tc.peer_stats([1, 1.5, 2, 2, 2, 2, 2, 2.5, 2.5, 3, 3])}}


def test_check_tender_design_flags():
    notice = {"notice_id": "OP1", "category": "CW", "market_approach": "international", "region": "AFE", "advertising_days": 21,
              "avg_lot_usd": 2.5e7, "bid_security_percent": 5, "electronic_submission": False}
    flags = {f["check"]: f for f in tc.check_tender_design(notice, _peers())}
    assert flags["advertising_below_policy_minimum"]["reference"] == 42
    assert flags["advertising_below_policy_minimum"]["severity"] == "high"
    assert flags["advertising_short_vs_peers"]["peer_group"] == "category/CW/international"
    assert flags["package_large_vs_market"]["peer_group"] == "region/AFE/CW/any"
    assert "bid_security_high_vs_peers" in flags
    assert "no_electronic_submission_international" in flags
    assert all(f["source"] == "OP1" for f in flags.values())


def test_check_tender_design_clean_notice():
    notice = {"category": "CW", "market_approach": "international", "region": "AFE", "advertising_days": 50, "avg_lot_usd": 3e6,
              "bid_security_percent": 2}
    assert tc.check_tender_design(notice, _peers()) == []
