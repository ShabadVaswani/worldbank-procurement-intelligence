from proc_intel import doc_parse as dp


def test_running_lines_ignore_page_numbers():
    pages = [["The World Bank", f"Page {i} of 9", f"text {i * 7} words"] for i in range(1, 10)]
    running = dp.running_lines(pages)
    assert dp.is_noise_line("Page 3 of 9", running)
    assert dp.is_noise_line("The World Bank", running)
    assert not dp.is_noise_line("A. Country Context", running)


def test_contents_lines_and_template_codes():
    assert dp.is_noise_line("III. IMPLEMENTATION ARRANGEMENTS .............. 23", set())
    assert dp.clean_line("BASIC INFORMATION BASIC_INFO_TABLE") == "BASIC INFORMATION"


def test_body_font_size_weights_characters():
    assert dp.body_font_size([(11.04, 900), (14.0, 40), (9.0, 100)]) == 11.0


def test_heading_levels():
    body = 11.0
    assert dp.heading_level("ANNEX 4: Procurement", 12, True, body) == 1
    assert dp.heading_level("IV. PROJECT APPRAISAL SUMMARY", 12, True, body) == 1
    assert dp.heading_level("B. Fiduciary", 11, True, body) == 2
    assert dp.heading_level("3.2 Procurement Arrangements", 11, True, body) == 2
    assert dp.heading_level("Procurement Plan", 11, True, body) == 2


def test_not_headings():
    body = 11.0
    assert dp.heading_level("B. Fiduciary", 11, False, body) is None                       # looks like body text
    assert dp.heading_level("Total", 11, True, body) is None                               # one bold table label
    assert dp.heading_level("The project will finance three components.", 11, True, body) is None
    assert dp.heading_level("from IDA; US$2.2 million from GFF)", 11, True, body) is None  # wrapped heading tail
    assert dp.heading_level("7 World Bank, 2018, Systematic Country Diagnostic", 12, True, body) is None


def test_caption():
    assert dp.is_caption("Table A4.3: Thresholds for Procurement")
    assert dp.is_caption("Figure 2. Results chain")
    assert not dp.is_caption("Tables are listed in Annex 2")


def test_assign_sections_paths_and_annex_flag():
    els = [{"kind": "text", "text": "cover"},
           {"kind": "heading", "level": 1, "text": "II. PROJECT DESCRIPTION"},
           {"kind": "heading", "level": 2, "text": "A. Components"},
           {"kind": "text", "text": "x"},
           {"kind": "heading", "level": 1, "text": "ANNEX 4: Procurement"},
           {"kind": "text", "text": "y"}]
    out = dp.assign_sections(els)
    assert out[0]["section_path"] == ["Front matter"]
    assert out[3]["section_path"] == ["II. PROJECT DESCRIPTION", "A. Components"]
    assert not out[3]["is_annex"] and out[5]["is_annex"]
    assert out[2]["section_id"] == out[3]["section_id"] != out[5]["section_id"]


def test_clean_table_drops_empty_rows_and_columns():
    grid = [["Type", None, "Threshold"], ["", None, ""], ["Works ", None, "5,000,000\n"], ["Goods", "", "1,500,000"]]
    assert dp.clean_table(grid) == [["Type", "Threshold"], ["Works", "5,000,000"], ["Goods", "1,500,000"]]


def test_table_quality_gate():
    good = [["Type", "Threshold"], ["Works", "5,000,000"], ["Goods", "1,500,000"]]
    assert dp.is_data_table(dp.table_quality(good))
    sparse = [["Acronyms", ""], ["", ""], ["", ""], ["", "x"]]
    assert not dp.is_data_table(dp.table_quality(dp.clean_table(sparse) + [["", ""]] * 3))
    prose = [["146.", " ".join(["word"] * 90)], ["147.", " ".join(["word"] * 80)]]
    assert not dp.is_data_table(dp.table_quality(prose))


def test_two_row_header_and_markdown():
    rows = [["Component", "Cost", ""], ["", "IDA", "Govt"], ["C1", "61.2", "0.1"], ["C2", "74.9", "1.8"]]
    assert dp.header_rows(rows) == 2
    md = dp.table_markdown(rows[:2], rows[2:])
    assert md.splitlines()[0] == "| Component | Cost / IDA | Govt |"
    assert md.splitlines()[2] == "| C1 | 61.2 | 0.1 |"


def test_table_chunks_repeat_header_and_never_cut_rows():
    rows = [["Item", "Description", "Cost"]] + [[f"{i}", "supply of equipment " * 5, f"{i}00"] for i in range(30)]
    parts = dp.table_chunks(rows, max_words=120)
    assert len(parts) > 1
    assert all(p["text"].startswith("| Item | Description | Cost |") for p in parts)
    covered = [i for p in parts for i in range(p["row_start"], p["row_end"])]
    assert covered == list(range(30))
    small = dp.table_chunks(rows[:4], max_words=300)
    assert len(small) == 1 and small[0]["row_end"] == 3


def test_split_and_pack_sentences():
    s = dp.split_sentences("116. All goods will be procured. The PPSD e.g. covers risks. Done now.")
    assert s == ["116. All goods will be procured.", "The PPSD e.g. covers risks.", "Done now."]
    sentences = [" ".join(["w"] * 50) + "." for _ in range(12)]
    chunks = dp.pack_sentences(sentences, target_words=120, max_words=160, overlap_words=40)
    assert all(len(c.split()) <= 160 for c in chunks)
    assert chunks[1].startswith(sentences[0][:20])          # overlap carried as whole sentences


def test_build_chunks_respects_sections_and_tables():
    els = dp.assign_sections([
        {"kind": "heading", "level": 1, "text": "ANNEX 4: Procurement", "page": 89},
        {"kind": "text", "text": "Procurement will follow the Regulations for all contracts financed.", "page": 89},
        {"kind": "table", "page": 91, "caption": "Table A4.3: Thresholds", "table_id": "d-t3",
         "rows": [["Type", "Threshold"], ["Works", "5,000,000"]]},
        {"kind": "heading", "level": 2, "text": "Procurement Plan", "page": 92},
        {"kind": "text", "text": "The procurement plan covers the first eighteen months of the project.", "page": 92},
    ])
    chunks = dp.build_chunks(els, "Demo Project")
    kinds = [c["chunk_type"] for c in chunks]
    assert kinds == ["narrative", "table", "narrative"]
    assert chunks[1]["context_header"] == "Demo Project > ANNEX 4: Procurement > Table A4.3: Thresholds"
    assert chunks[1]["embed_text"].startswith("Demo Project > ANNEX 4")
    assert chunks[2]["section_path"] == "ANNEX 4: Procurement > Procurement Plan"
    assert all(c["is_annex"] for c in chunks)
    assert chunks[1]["table_id"] == "d-t3" and chunks[1]["page_start"] == 91


def test_locate_row_states():
    chunks = [dp.row_tokens(["works threshold 5,000,000 goods 1,500,000"]), dp.row_tokens(["consulting 500,000"])]
    assert dp.locate_row(dp.row_tokens(["Works", "5,000,000", "goods"]), chunks) == "intact"
    assert dp.locate_row(dp.row_tokens(["Works", "5,000,000", "consulting", "500,000"]), chunks) == "split"
    assert dp.locate_row(dp.row_tokens(["Vehicles", "250,000", "Post"]), chunks) == "missing"
    assert dp.locate_row({"ab"}, chunks) == "trivial"


def test_distinctive_tokens_drop_common_words():
    chunks = [{"procurement", "2021", "x"}, {"procurement", "2021"}, {"procurement", "2021"}, {"procurement", "2021"}]
    assert dp.distinctive_tokens({"procurement", "2021", "vehicles"}, chunks) == {"vehicles"}


def test_answer_in_ignores_case_and_spaces():
    assert dp.answer_in("Notification of award  issued", "| Package 2 | notification of award issued |")
