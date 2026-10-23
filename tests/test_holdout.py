from proc_intel.holdout import full_cited_text, pick_holdout, usable_description


def _rows():
    rows = []
    regions = ["Africa East", "Africa West", "South Asia", "Latin America", "Europe", "East Asia", "Middle East"]
    methods = {"CW": ["Request for Bids", "Request for Quotations"], "GO": ["Request for Bids", "Request for Quotations"],
               "CS": ["Quality And Cost-Based Selection", "Consultant Qualification Selection"],
               "NC": ["Request for Bids", "Request for Quotations"]}
    i = 0
    for reg in regions:
        for cat in ("CW", "GO", "CS", "NC"):
            for m in methods[cat]:
                for _ in range(2):
                    i += 1
                    rows.append({"row_id": str(i), "notice_id": f"OP{i}", "project_id": f"P{i:06d}", "region": reg,
                                 "category": cat, "method": m})
    return rows


def test_pick_holdout_spreads_over_categories_regions_methods():
    picked = pick_holdout(_rows(), 10, seed=11)
    assert len(picked) == 10
    cats = [p["category"] for p in picked]
    assert {c: cats.count(c) for c in set(cats)} == {"CW": 3, "GO": 3, "CS": 2, "NC": 2}
    assert len({p["region"] for p in picked}) == 7                  # every region before any repeat
    assert len({(p["region"], p["category"]) for p in picked}) == 10
    assert len({p["method"] for p in picked}) >= 4


def test_pick_holdout_is_repeatable_and_order_free():
    rows = _rows()
    a = [p["row_id"] for p in pick_holdout(rows, 10, seed=11)]
    b = [p["row_id"] for p in pick_holdout(list(reversed(rows)), 10, seed=11)]
    assert a == b
    assert a != [p["row_id"] for p in pick_holdout(rows, 10, seed=12)]


def test_pick_holdout_one_per_notice_and_project():
    rows = _rows()
    for r in rows:                                   # every row now shares a project with its twin
        r["project_id"] = f"P{(int(r['row_id']) + 1) // 2}"
    picked = pick_holdout(rows, 10, seed=11)
    assert len({p["project_id"] for p in picked}) == len(picked)
    assert len({p["notice_id"] for p in picked}) == len(picked)


def test_pick_holdout_skips_empty_category_and_stops_when_out_of_rows():
    rows = [r for r in _rows() if r["category"] != "NC"][:6]
    picked = pick_holdout(rows, 10, seed=11)
    assert len(picked) == 6
    assert all(p["category"] != "NC" for p in picked)


def test_usable_description():
    assert usable_description("Supply and installation of solar pumps for 20 schools")
    assert not usable_description("Consultant")
    assert not usable_description("     ")
    assert not usable_description(None)
    assert not usable_description(float("nan"))
    assert not usable_description("A" * 60)                         # one long token is not a description


def test_full_cited_text():
    rec = {"facts": "project P1 | KE | Africa East | Request for Bids | 2021 | firms in award notice: 3"}
    assert full_cited_text(rec, "Road works | KE, ...") == (
        "project P1 | KE | Africa East | Request for Bids | 2021 | firms in award notice: 3 | Road works | KE, ...")
    assert full_cited_text({"type": "benchmark"}, "P10/P50/P90 1/2/3") == "P10/P50/P90 1/2/3"
