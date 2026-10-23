import pytest

from proc_intel.countries import is_regional, to_iso2
from proc_intel.procurement import category_code, clean_method_name, method_competition


@pytest.mark.parametrize("code, name, expected", [
    ("KE", "Kenya", "KE"),
    ("ZR", "Congo, Democratic Republic of", "CD"),
    ("YF", "Serbia", "RS"),
    ("GZ", "West Bank and Gaza", "PS"),
    (None, "Cote d'Ivoire", "CI"),
    ("", "Somalia, Federal Republic of", "SO"),
    ("3W", "Western and Central Africa", "3W"),
    ("1W", "World", "99"),
    (None, "Western Balkans", None),
    ("null", None, None),
])
def test_to_iso2(code, name, expected):
    assert to_iso2(code, name) == expected


def test_is_regional():
    assert is_regional("3E") and not is_regional("KE") and not is_regional(None)


def test_method_names_and_competition():
    assert clean_method_name("Consultant Qualification  Selection") == "Consultant Qualification Selection"
    assert method_competition("Consultant Qualification  Selection") == "limited"
    assert method_competition("Request for Bids") == "open"
    assert method_competition("Direct Selection") == "direct"
    assert method_competition("Something New") is None
    assert method_competition(None) is None


@pytest.mark.parametrize("value, expected", [
    ("Works", "CW"), ("CW", "CW"), ("cs", "CS"), ("Non-consulting Services", "NC"), ("Other", None), (None, None),
])
def test_category_code(value, expected):
    assert category_code(value) == expected
