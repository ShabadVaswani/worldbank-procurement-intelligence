import pytest

from proc_intel.references import (
    TIER_EXACT,
    TIER_STEP,
    TIER_VARIANT,
    is_reference_variant,
    match_tier,
    normalise_reference,
    step_activity_id,
    variant_keys,
)


def test_normalise_reference_removes_separators_and_case():
    assert normalise_reference("MZ-UEM- FA-474115-GO-RFB") == "MZUEMFA474115GORFB"
    assert normalise_reference("mz uem fa 474115 go rfb") == "MZUEMFA474115GORFB"
    assert normalise_reference(None) == ""


@pytest.mark.parametrize("ref, expected", [
    ("MZ-MISAU-458432-GO-RFB", "458432"),
    ("IN-DPO, KANGRA-494415-CW-RFQ", "494415"),
    ("AR-MEYSP-509667-CS-QCBS-2", "509667"),
    ("MZ-UEM- FA-474115 - GO-RFB", "474115"),
    ("BJ-WAPP-429366-NC-DIR", "429366"),
    ("45/C/PRAPS/2019", None),
    ("UDP PPG-QCBS-2016-4-12", None),
    ("1234567890-GO-RFB", None),        # 10 digits: not an activity id
    (None, None),
])
def test_step_activity_id(ref, expected):
    assert step_activity_id(ref) == expected


@pytest.mark.parametrize("a, b, expected", [
    ("EMCRPG06A", "EMCRPG06", True),                       # lot suffix
    ("17BWDNAAS2018", "17WDNAAS2018", True),               # lot letter inside
    ("NEPARIISNE104287BISGORFB", "NEPARIISNE104287GORFB", True),
    ("TCPCONQCBSB1G", "TCPCONQCBSB1D", False),             # substitution: different package
    ("TENDER12", "TENDER1", False),                        # inserted digit: different lot
    ("LOT1A", "LOT1", False),                              # too short to be specific
    ("ABCDEFGHIJ", "ABCDEFGHIJKLMN", False),               # four letters inserted
])
def test_is_reference_variant(a, b, expected):
    assert is_reference_variant(a, b) is expected
    assert is_reference_variant(b, a) is expected


def test_exact_match_ignores_formatting():
    assert match_tier("ET-SWE-RPCU-571277-CW-RFB", "et swe rpcu 571277 cw rfb") == TIER_EXACT


def test_step_id_match_when_suffix_differs():
    assert match_tier("AR-MEYSP-509667-CS-QCBS", "AR-MEYSP-509667-CS-QCBS-2") == TIER_STEP


def test_different_step_activities_never_match():
    assert match_tier("MZ-MISAU-458432-GO-RFB", "MZ-MISAU-458433-GO-RFB") is None


def test_lot_variant_of_free_text_reference():
    assert match_tier("EMCRP/G-06", "EMCRP/G-06a") == TIER_VARIANT
    assert match_tier("SLU-DATA-NC-SD-ENU-02-22", "SLU-DATA-NC-SD-ENU-03-22") is None


def test_missing_reference():
    assert match_tier(None, "ABC") is None


def test_variant_keys_agree_with_is_reference_variant():
    longer = "EMCRPG06A"
    keys = variant_keys(longer)
    assert "EMCRPG06" in keys and "EMCRPG0A" not in keys      # digits are never deleted
    assert all(is_reference_variant(longer, k) for k in keys)
    assert variant_keys("ABC12") == []                         # too short to have variants
