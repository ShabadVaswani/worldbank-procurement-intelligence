import math

import numpy as np
import pytest

from proc_intel.backtest import (
    agreement,
    allocate_sample,
    bootstrap_ci,
    canonical_sectors,
    design_weights,
    interval_metrics,
    leak_violations,
    lesson_score,
    method_family,
    parse_lesson_verdict,
    precision_of_returned,
    proxy_relevant,
    render_review_html,
    review_agreement,
    roc_auc,
    stable_hash,
    stratified_pick,
    weighted_mean,
)

# --- sampling ---------------------------------------------------------------------------------------------

def test_stable_hash_is_deterministic_and_seed_dependent():
    assert stable_hash(7, "1862004") == stable_hash(7, "1862004")
    assert stable_hash(7, "1862004") != stable_hash(8, "1862004")


def test_allocate_sample_gives_floors_then_proportional_shares():
    alloc = allocate_sample({"a": 1000, "b": 100, "c": 3}, 50, floor=5)
    assert alloc["c"] == 3                      # never more than the stratum holds
    assert alloc["b"] >= 5 and alloc["a"] > alloc["b"]
    assert sum(alloc.values()) == 50


def test_allocate_sample_never_exceeds_sizes_and_stops_when_exhausted():
    alloc = allocate_sample({"a": 4, "b": 2}, 100, floor=5)
    assert alloc == {"a": 4, "b": 2}


def test_allocate_sample_is_deterministic_on_ties():
    a1 = allocate_sample({"x": 10, "y": 10, "z": 10}, 16, floor=0)
    a2 = allocate_sample({"z": 10, "y": 10, "x": 10}, 16, floor=0)
    assert a1 == a2 and sum(a1.values()) == 16


def _rows():
    rows = []
    for i in range(40):
        rows.append({"row_id": f"c{i}", "notice_id": f"n{i // 2}", "project_id": f"P{i // 4}",
                     "stratum": "A" if i < 20 else "B"})
    return rows


def test_stratified_pick_respects_allocation_and_uniqueness():
    picked = stratified_pick(_rows(), lambda r: r["stratum"], {"A": 5, "B": 3}, seed=7)
    assert sum(r["stratum"] == "A" for r in picked) == 5 and sum(r["stratum"] == "B" for r in picked) == 3
    assert len({r["notice_id"] for r in picked}) == len(picked)        # one lot per notice
    assert len({r["project_id"] for r in picked}) == len(picked)       # one per project when possible


def test_stratified_pick_allows_repeated_projects_only_when_needed():
    # stratum A has 5 projects; asking for 8 forces repeats of projects but never of notices
    picked = stratified_pick(_rows(), lambda r: r["stratum"], {"A": 8}, seed=7)
    assert len(picked) == 8
    assert len({r["notice_id"] for r in picked}) == 8
    assert len({r["project_id"] for r in picked}) == 5


def test_stratified_pick_is_reproducible():
    a = stratified_pick(_rows(), lambda r: r["stratum"], {"A": 4, "B": 4}, seed=7)
    b = stratified_pick(list(reversed(_rows())), lambda r: r["stratum"], {"A": 4, "B": 4}, seed=7)
    assert [r["row_id"] for r in a] == [r["row_id"] for r in b]


def test_design_weights_and_weighted_mean():
    w = design_weights(["A", "A", "B"], {"A": 100, "B": 10})
    assert list(w) == [50.0, 50.0, 10.0]
    assert weighted_mean([1.0, 1.0, 0.0], w) == pytest.approx(100 / 110)
    assert weighted_mean([1.0, float("nan")]) == 1.0


def test_bootstrap_ci_brackets_the_mean():
    v = np.r_[np.zeros(50), np.ones(50)]
    lo, hi = bootstrap_ci(v, n_boot=500)
    assert lo < 0.5 < hi and lo > 0.3 and hi < 0.7


# --- timeline metrics -------------------------------------------------------------------------------------

def test_interval_metrics_on_a_hand_example():
    y = [100, 200, 300, 400]
    m = interval_metrics(y, [50, 150, 350, 300], [100, 180, 320, 400], [150, 250, 400, 450])
    assert m["n"] == 4
    assert m["mae_days"] == pytest.approx((0 + 20 + 20 + 0) / 4)
    assert m["coverage_p10_p90"] == 0.75 and m["below_p10"] == 0.25 and m["above_p90"] == 0.0
    assert m["mean_width_days"] == pytest.approx((100 + 100 + 50 + 150) / 4)


def test_interval_metrics_drops_missing_rows():
    m = interval_metrics([100, 200], [50, float("nan")], [100, 200], [150, 250])
    assert m["n"] == 1 and m["mae_days"] == 0


def test_roc_auc_matches_known_values():
    assert roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert roc_auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5
    assert roc_auc([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8]) == 0.75
    assert math.isnan(roc_auc([1, 1], [0.2, 0.3]))


# --- time-leak guard ----------------------------------------------------------------------------------------

def test_leak_violations_flags_future_own_project_and_undated_records():
    recs = [{"record_id": "contract:1", "project_id": "P1", "signing_date": "2023-01-05"},
            {"record_id": "contract:2", "project_id": "P2", "signing_date": "2023-07-01"},   # on the cutoff
            {"record_id": "contract:3", "project_id": "P9", "signing_date": "2022-01-01"},   # held-out project
            {"record_id": "contract:4", "project_id": "P3", "signing_date": None}]
    assert leak_violations(recs, "2023-07-01", ["P9"]) == ["contract:2", "contract:3", "contract:4"]


# --- precedent proxy --------------------------------------------------------------------------------------

def test_method_family():
    assert method_family("Request for Bids") == "bids"
    assert method_family("Quality And Cost-Based Selection") == method_family("Consultant Qualification Selection")
    assert method_family("Request for Quotations") == "quotations"
    assert method_family(None) == "other"


def test_canonical_sectors_reads_major_sector_and_tags():
    assert canonical_sectors("FY17 - Transportation") == {"transport"}
    assert canonical_sectors("Digital Development", "Public Admin;Info & Communication") == {"ict", "public_administration"}
    assert canonical_sectors(None, "") == frozenset()


def test_proxy_relevant_needs_category_method_family_and_sector():
    pkg = {"category": "GO", "method": "Request for Bids", "sectors": {"health"}}
    assert proxy_relevant(pkg, {"category": "GO", "method": "E-Auctions", "sectors": {"health", "education"}})
    assert not proxy_relevant(pkg, {"category": "GO", "method": "Request for Quotations", "sectors": {"health"}})
    assert not proxy_relevant(pkg, {"category": "GO", "method": "Request for Bids", "sectors": {"agriculture"}})
    assert not proxy_relevant(pkg, {"category": "CW", "method": "Request for Bids", "sectors": {"health"}})
    assert proxy_relevant({**pkg, "sectors": set()}, {"category": "GO"}) is None
    other_sector = {"category": "GO", "method": "Request for Bids", "sectors": {"agriculture"}}
    assert proxy_relevant(pkg, other_sector, use_sector=False)
    assert proxy_relevant({**pkg, "sectors": set()}, other_sector, use_sector=False)
    assert proxy_relevant(pkg, {"category": "GO", "method": "Request for Quotations"}, use_method=False, use_sector=False)


def test_precision_of_returned():
    assert precision_of_returned([True, False, None]) == 0.5
    assert precision_of_returned([]) is None


# --- agreement --------------------------------------------------------------------------------------------

def test_agreement_and_kappa():
    a = agreement([True, True, False, False], [True, False, False, False])
    assert a["n"] == 4 and a["agreement"] == 0.75
    assert a["kappa"] == pytest.approx(0.5)
    assert agreement([None, True], [True, None])["n"] == 0
    assert agreement(["yes", "no"], ["yes", "no"])["kappa"] == 1.0


# --- lessons judge ----------------------------------------------------------------------------------------

def test_parse_lesson_verdict_accepts_wrapped_json_and_rejects_bad_verdicts():
    v = parse_lesson_verdict('Here: {"verdict": "Partial", "materialised": ["contractor delays"], '
                             '"matched": [], "rationale": "generic"}')
    assert v["verdict"] == "partial" and v["materialised"] == ["contractor delays"]
    assert parse_lesson_verdict('{"verdict": "maybe"}') is None
    assert parse_lesson_verdict("no json") is None


def test_lesson_score():
    assert [lesson_score(v) for v in ("yes", "partial", "no", "none_occurred", None)] == [1.0, 0.5, 0.0, None, None]


# --- review pack ------------------------------------------------------------------------------------------

def test_review_agreement_ignores_unlabelled_rows():
    rows = [{"timeline_ok": "1", "auto_timeline_ok": True, "precedents_relevant": 4, "auto_precedents_relevant": 3,
             "any_unsupported_claim": 0, "auto_unsupported_claim": False, "risks_relevant": 3},
            {"timeline_ok": "0", "auto_timeline_ok": True, "precedents_relevant": 2, "auto_precedents_relevant": 2,
             "any_unsupported_claim": 1, "auto_unsupported_claim": True, "risks_relevant": 5},
            {"timeline_ok": None, "auto_timeline_ok": False, "precedents_relevant": float("nan"),
             "auto_precedents_relevant": 1}]
    out = review_agreement(rows)
    assert out["n_labelled"] == 2
    assert out["timeline_ok"]["n"] == 2 and out["timeline_ok"]["agreement"] == 0.5
    assert out["precedents_relevant"] == {"n": 2, "exact": 0.5, "within_1": 1.0, "mae": 0.5,
                                          "mean_owner": 3.0, "mean_judge": 2.5}
    assert out["any_unsupported_claim"]["agreement"] == 1.0
    assert out["risks_relevant"]["mean_owner"] == 4.0


def test_render_review_html_escapes_text():
    page = render_review_html([{"review_id": "r01", "description": "<script>x</script>", "brief_text": "a & b",
                                "cited_records": '[{"record_id": "contract:1", "text": "<b>"}]'}])
    assert "<script>x" not in page and "&lt;script&gt;" in page and "a &amp; b" in page and "&lt;b&gt;" in page
