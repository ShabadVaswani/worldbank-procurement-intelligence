"""Country codes: the World Bank's operational codes versus ISO 3166 alpha-2.

The contract-awards feed uses the Bank's own two-character codes. Most equal ISO alpha-2, but a
few are legacy codes, and the World Development Indicators / WGI tables (silver.country_year)
use ISO. Without this crosswalk the DR Congo, Serbia, Yemen, Timor-Leste and West Bank and Gaza
would silently lose their governance indicators.
"""
from __future__ import annotations

WB_TO_ISO2 = {
    "ZR": "CD",   # Congo, Democratic Republic of (former Zaire)
    "YF": "RS",   # Serbia (former Yugoslavia)
    "RY": "YE",   # Yemen, Republic of
    "TP": "TL",   # Timor-Leste (former East Timor)
    "GZ": "PS",   # West Bank and Gaza
    "1W": "99",   # "World": supplier rows use the WDI aggregate code 1W, borrower rows the Bank code 99
}

# Codes the Bank uses for multi-country (regional) programmes; they have no country indicators.
REGIONAL_CODES = {
    "3E": "Eastern and Southern Africa", "3W": "Western and Central Africa", "3T": "Central Africa",
    "4P": "Pacific Islands", "5M": "Middle East and North Africa", "6O": "OECS Countries",
    "7C": "Central Asia", "CB": "Caribbean", "99": "World",
}

# Country names whose code is missing (awards rows for these two borrowers have an empty code)
# or that are spelled differently in the notices feed than in the awards / indicators data.
NAME_TO_ISO2 = {
    "Cote d'Ivoire": "CI",
    "Somalia, Federal Republic of": "SO",
    "Federal Republic of Somalia": "SO",
    "Somalia": "SO",
    "Turkey": "TR",
    "Turkiye": "TR",
    "Türkiye": "TR",
    "Vietnam": "VN",
}


def to_iso2(code: str | None, name: str | None = None) -> str | None:
    """ISO alpha-2 (or Bank regional code) for a code/name pair from the awards feed; None if unknown."""
    code = (code or "").strip().upper()
    if code and code != "NULL":
        return WB_TO_ISO2.get(code, code)
    return NAME_TO_ISO2.get((name or "").strip())


def is_regional(code: str | None) -> bool:
    return (code or "").strip().upper() in REGIONAL_CODES
