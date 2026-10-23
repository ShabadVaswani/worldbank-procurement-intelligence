"""Reference data for procurement categories and methods (World Bank Procurement Regulations).

Both feeds use the same method names ('Request for Bids', 'Quality And Cost-Based Selection', ...);
the notices feed also carries short codes. `competition` is an analyst grouping used by the
timeline model and the knowledge graph:
  open     - publicly advertised, any eligible firm may bid or express interest
  limited  - quotations or a shortlist / CV comparison, no open advertisement of the contract
  direct   - a single firm or agency is approached
  other    - not a market approach (force account, community-driven, PPP, agents, ...)
"""
from __future__ import annotations

import re

CATEGORIES = {   # code -> name used in the awards feed
    "CW": "Works",
    "GO": "Goods",
    "CS": "Consultant Services",
    "NC": "Non-consulting Services",
}
CATEGORY_BY_NAME = {name.lower(): code for code, name in CATEGORIES.items()}

METHOD_COMPETITION = {
    "Request for Bids": "open",
    "International Competitive Bidding": "open",
    "National Competitive Bidding": "open",
    "Request for Proposals": "open",
    "E-Auctions": "open",
    "Quality And Cost-Based Selection": "open",
    "Quality Based Selection": "open",
    "Fixed Budget Selection": "open",
    "Least Cost Selection": "open",
    "Request for Quotations": "limited",
    "Consultant Qualification Selection": "limited",
    "Individual Consultant Selection": "limited",
    "Commercial Practices": "limited",
    "Direct Selection": "direct",
    "Single Source Selection": "direct",
    "UN Agencies (Direct)": "direct",
    "Non-Profit Organizations": "direct",
    "Force Account": "other",
    "Community Driven Development": "other",
    "Public Private Partnership": "other",
    "Procurement Agents": "other",
    "Imports": "other",
    "Alternative Procurement Arrangement": "other",
}


def clean_method_name(name: str | None) -> str | None:
    """Collapse repeated spaces ('Consultant Qualification  Selection' appears in both feeds)."""
    if not name or not name.strip():
        return None
    return re.sub(r"\s+", " ", name).strip()


def method_competition(name: str | None) -> str | None:
    """Competition level of a method name; None for an unknown method (reported, not guessed)."""
    cleaned = clean_method_name(name)
    return METHOD_COMPETITION.get(cleaned) if cleaned else None


def category_code(name_or_code: str | None) -> str | None:
    """'Works' or 'CW' -> 'CW'; None if unrecognised."""
    if not name_or_code:
        return None
    value = name_or_code.strip()
    if value.upper() in CATEGORIES:
        return value.upper()
    return CATEGORY_BY_NAME.get(value.lower())
