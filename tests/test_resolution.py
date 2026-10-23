import pandas as pd

from proc_intel.resolution import MatchRules, decide, distinctive_words, prepare_records, resolve, score_candidates, strip_country_name

RECORDS = pd.DataFrame([
    ("100", "AIRES INGEGNERIA S.p.A.", "IT"),
    ("101", "M/S. AIRES INGEGNERIA", "IT"),          # exact name after normalisation -> same entity
    ("102", "AIRES INGEGNERIA", "FR"),               # other country -> separate entity
    ("200", "TOKUN INTERNATIONAL LIMITED", "NG"),
    ("201", "TOKUNS INTERNATIONAL LTD", "NG"),       # typo -> fuzzy link
    ("300", "TRUONG SON 145", "VN"),
    ("301", "TRUONG SON 146", "VN"),                 # different number -> never linked
    ("400", "ALPHA BUILDERS", "KE"),
    ("401", "ALPHA BUILDERS JV BETA WORKS", "KE"),   # consortium vs member -> not linked
    ("500", "SAHE", "SN"),
    ("500", "SOCIETE AFRICAINE D'HYDRAULIQUE ET D'ELECTRICITE", "SN"),   # acronym, same id -> linked
    ("510", "ENTREPRISE SATU-SA", "NE"),
    ("510", "ENTREPRISE BAANA", "NE"),                                      # same id, unrelated names -> not linked
    ("511", "ENTREPRISE BAANA", "NE"),
] + [(f"6{i:02d}", "ARUN KUMAR", "IN") for i in range(5)]   # common personal name under 5 ids;
                                                                # both words occur in 5 distinct names
  + [(f"6{i:02d}", f"ARUN {s}", "IN") for i, s in enumerate(["SHARMA", "DAS", "RAO", "PAL"], start=10)]
  + [(f"6{i:02d}", f"{s} KUMAR", "IN") for i, s in enumerate(["RAJ", "SUNIL", "AMIT", "VIJAY"], start=20)]
  + [("700", "UASSI MWEMA", "KM"), ("701", "UASSI MWEMA", "KM")]     # rare personal name -> linked
  + [("800", "KARANJEET SINGH", "IN"), ("801", "CHARANJEET SINGH", "IN")],   # one letter apart: two people
    columns=["supplier_id", "name", "country_code"])


def run(threshold=0.8):
    rules = MatchRules(fuzzy_threshold=threshold)
    recs = prepare_records(RECORDS, rules)
    pairs = score_candidates(recs, rules)
    entity = resolve(recs, pairs, decide(pairs, rules))
    return recs.assign(entity=entity)


def entity_of(df, supplier_id, name=None):
    rows = df[df["supplier_id"] == supplier_id]
    if name is not None:
        rows = rows[rows["name"] == name]
    return rows["entity"].iloc[0]


def test_exact_and_country_blocking():
    df = run()
    assert entity_of(df, "100") == entity_of(df, "101")
    assert entity_of(df, "100") != entity_of(df, "102")


def test_fuzzy_link_and_guards():
    df = run()
    assert entity_of(df, "200") == entity_of(df, "201")
    assert entity_of(df, "300") != entity_of(df, "301")
    assert entity_of(df, "400") != entity_of(df, "401")


def test_same_id_links_acronym_and_full_name():
    df = run()
    assert df.loc[df["supplier_id"] == "500", "entity"].nunique() == 1


def test_same_id_with_unrelated_names_is_not_trusted():
    df = run()
    assert entity_of(df, "510", "ENTREPRISE SATU-SA") != entity_of(df, "510", "ENTREPRISE BAANA")
    assert entity_of(df, "510", "ENTREPRISE BAANA") == entity_of(df, "511")


def test_ambiguous_personal_names_stay_apart_rare_ones_merge():
    df = run()
    arun = df[df["name"] == "ARUN KUMAR"]
    assert arun["ambiguous_person"].all() and arun["entity"].nunique() == 5
    assert entity_of(df, "700") == entity_of(df, "701")


def test_one_letter_apart_is_not_a_typo_link():
    df = run(0.5)
    assert entity_of(df, "800") != entity_of(df, "801")


def test_threshold_controls_fuzzy_links():
    assert entity_of(run(0.99), "200") != entity_of(run(0.99), "201")


def test_entity_ids_are_deterministic():
    shuffled = RECORDS.sample(frac=1.0, random_state=7)
    rules = MatchRules(fuzzy_threshold=0.8)
    recs = prepare_records(shuffled, rules)
    pairs = score_candidates(recs, rules)
    ids = resolve(recs, pairs, decide(pairs, rules))
    assert ids.tolist() == run()["entity"].tolist()
    assert entity_of(run(), "101") == "SE-100"


def test_strip_country_name():
    assert strip_country_name("ERNST AND YOUNG NIGERIA", "Nigeria", "NG") == "ERNST AND YOUNG"
    assert strip_country_name("PLURIEX COTE D IVOIRE", "Cote d'Ivoire", "CI") == "PLURIEX"
    assert strip_country_name("ASCOMA CI", "Cote d'Ivoire", "CI") == "ASCOMA"
    assert strip_country_name("CI CONSTRUCTION", "Cote d'Ivoire", "CI") == "CI CONSTRUCTION"   # code only as last word
    assert strip_country_name("NIGERIA", "Nigeria", "NG") == "NIGERIA"                         # never empty


def test_distinctive_words():
    token_df = {"LAND": 40, "REGISTRATION": 40, "OFFICE": 60, "OF": 300, "PROVINCE": 50, "LAO": 2, "CAI": 2}
    assert distinctive_words("LAND REGISTRATION OFFICE OF LAO CAI PROVINCE", token_df, 10) == "CAI LAO"


def test_generic_phrase_does_not_link_different_offices():
    offices = [(f"9{i:02d}", f"LAND REGISTRATION OFFICE OF {p} PROVINCE", "VN")
               for i, p in enumerate(["LAO CAI", "THAI BINH", "LANG SON", "SON LA", "TIEN GIANG", "BAC GIANG",
                                      "LONG AN", "TRA VINH", "HA NAM", "NAM DINH", "BEN TRE", "AN GIANG"])]
    rules = MatchRules(fuzzy_threshold=0.7)
    recs = prepare_records(pd.DataFrame(offices, columns=["supplier_id", "name", "country_code"]), rules)
    pairs = score_candidates(recs, rules)
    assert (pairs["cosine"] >= 0.7).any()                       # the trigram cosine alone would link them
    assert resolve(recs, pairs, decide(pairs, rules)).nunique() == len(offices)


def test_records_without_country_get_no_name_links():
    recs = pd.DataFrame([("1", "MULTISERVICES", None), ("2", "ABIL MULTISERVICES", None), ("3", "ABIL MULTISERVICES", None)],
                        columns=["supplier_id", "name", "country_code"])
    rules = MatchRules(fuzzy_threshold=0.5)
    prepared = prepare_records(recs, rules)
    pairs = score_candidates(prepared, rules)
    assert resolve(prepared, pairs, decide(pairs, rules)).nunique() == 3
