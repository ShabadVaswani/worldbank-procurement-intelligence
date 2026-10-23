import pytest

from proc_intel.names import (
    compact_key,
    digit_tokens,
    drop_self_acronym,
    is_acronym_of,
    is_ambiguous_person_name,
    is_consortium,
    is_person_like,
    normalise_supplier_name,
    token_index,
)


@pytest.mark.parametrize("raw, expected", [
    ("M/S. AIRES INGEGNERIA", "AIRES INGEGNERIA"),
    ("Aires Ingegneria S.p.A.", "AIRES INGEGNERIA"),
    ("SOCIÉTÉ AFRILUX S.A.", "AFRILUX"),
    ("ENTREPRISE SOGOBA BTP", "SOGOBA BTP"),
    ("ZHEJIANG DUOPU DETECTION TECHNOLOGY CO. LTD", "ZHEJIANG DUOPU DETECTION TECHNOLOGY"),
    ("HUNAN BOSHANG CONSTRUCTION ENGINEERING CO., LTD", "HUNAN BOSHANG CONSTRUCTION ENGINEERING"),
    ("FOUNDATION & WATERWELL ENGINEERING (PVT) LTD", "FOUNDATION AND WATERWELL ENGINEERING"),
    ("PAPELERÍA HONDURAS S DE R.L", "PAPELERIA HONDURAS"),
    ("MULTICOMERCIAL, SOCIEDAD ANÓNIMA", "MULTICOMERCIAL"),
    ("CÔNG TY TNHH XÂY DỰNG HỒNG CHÂU", "XAY DUNG HONG CHAU"),
    ("ETS LIBRA", "LIBRA"),
    ("PT CIPTA ESA UNGGUL", "CIPTA ESA UNGGUL"),
    ("\tJET EQUIPE", "JET EQUIPE"),
    ("A.B.C. Construction Ltd", "ABC CONSTRUCTION"),
    ("ROHLET TRADING PLC (LEAD)", "ROHLET TRADING"),
    ("SMEC INTERNATIONAL PTY LTD (LEAD PARTNER)", "SMEC INTERNATIONAL"),
])
def test_normalise_supplier_name(raw, expected):
    assert normalise_supplier_name(raw) == expected


def test_spelling_variants_share_a_key():
    a = normalise_supplier_name("Medicom Co., Ltd")
    b = normalise_supplier_name("MEDICOM COMPANY LIMITED")
    assert a == b == "MEDICOM"


def test_name_that_is_only_a_legal_form_is_kept():
    assert normalise_supplier_name("LIMITED") == "LIMITED"


def test_initials_are_not_mistaken_for_legal_forms():
    # "AB" (Swedish aktiebolag) is not stripped: it is far more often a firm's initials
    assert normalise_supplier_name("A.B. TRADERS") == "AB TRADERS"


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_names(empty):
    assert normalise_supplier_name(empty) == ""


def test_compact_key_ignores_spacing():
    assert compact_key("ABC CONSULT") == compact_key("ABCCONSULT")


@pytest.mark.parametrize("raw, expected", [
    ("UNIQUE ENTERPRISE LIMITED\tJV WITH\tREY INTERNATIONAL FZC", True),
    ("GROUPEMENT LINPICO-YONS ASSOCIATES", True),
    ("CONSORCIO VIAL DEL SUR", True),
    ("ROYAL INDUSTRIAL TRADING CO.", False),
    ("JVR ENGINEERING", False),
])
def test_is_consortium(raw, expected):
    assert is_consortium(raw) is expected


@pytest.mark.parametrize("raw, expected", [
    ("AJAY KUMAR", True),
    ("MONICA VALLEJOS PIÑA", True),
    ("BALAJI ENTERPRISES", False),
    ("ROYAL TRADING CO", False),
    ("NEWTECH", False),                 # one token: could be either, not treated as a person
    ("HAI HIEN 145", False),            # digits
    ("PAPELERIA HONDURAS S DE RL", False),
])
def test_is_person_like(raw, expected):
    assert is_person_like(raw) is expected


def test_digit_tokens():
    assert digit_tokens("TRUONG SON 145") == {"145"}
    assert digit_tokens("TRUONG SON") == frozenset()


@pytest.mark.parametrize("short, long_, expected", [
    ("SAHE", "SOCIETE AFRICAINE D'HYDRAULIQUE ET D'ELECTRICITE-SARL", True),
    ("LCS", "LES CABLERIES DU SENEGAL - S.A", True),
    ("UPS LTD", "UNION PETROLEUM SERVICES LTD", True),
    ("ITCS S.A.", "INFORMATION TECHNOLOGY CONSULTING SUPPORT S.A.", True),
    ("BAANA", "ENTREPRISE SATU-SA", False),
    ("SATU", "SATU", False),                                   # a one-word name is not an expansion
])
def test_is_acronym_of(short, long_, expected):
    assert is_acronym_of(short, long_) is expected


def test_ambiguity_counts_names_without_the_other_words():
    names = ["ARUN KUMAR", "ARUN SHARMA", "ARUN DAS", "ARUN RAO", "ARUN PAL",
             "RAJ KUMAR", "SUNIL KUMAR", "AMIT KUMAR", "VIJAY KUMAR",
             "SEC DIARRA", "SEC DIARRA AUDIT", "SEC DIARRA CONSEIL", "SEC DIARRA EXPERTISE", "SEC DIARRA MALI"]
    index = token_index(names)
    assert is_ambiguous_person_name("ARUN KUMAR", "ARUN KUMAR", index)
    # all five names with SEC also contain DIARRA: its own variants do not make it common
    assert not is_ambiguous_person_name("SEC DIARRA", "SEC DIARRA", index)


def test_drop_self_acronym():
    assert drop_self_acronym("ECONOMIC CONSULTING ASSOCIATES ECA") == "ECONOMIC CONSULTING ASSOCIATES"
    assert drop_self_acronym("LEA ASSOCIATION SOUTH ASIA LASA") == "LEA ASSOCIATION SOUTH ASIA"
    assert drop_self_acronym("ABIL MULTISERVICES") == "ABIL MULTISERVICES"
