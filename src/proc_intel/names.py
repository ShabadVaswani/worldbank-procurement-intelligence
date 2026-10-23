"""Supplier-name normalisation for entity resolution.

The goal is a *comparison key*, not a display name: two spellings of the same firm should
normalise to the same or very similar strings. The rules come from reading the most frequent
tokens among the 134k supplier names in the contract awards data (see p04).

Steps, in order:
 1. transliterate to ASCII (accents, Vietnamese, Turkish, Cyrillic, ...) and upper-case
 2. private-use / control characters become spaces (tabs, Word bullets such as U+F0FC)
 3. joint-venture role markers '(LEAD)' dropped, '&' -> AND, acronym dots removed (S.A. -> SA),
    other punctuation -> space
 4. runs of single letters joined (S A -> SA, A B C -> ABC)
 5. multi-word legal forms removed (S DE RL, SOCIEDAD ANONIMA, CONG TY, ...)
 6. one-word legal forms removed anywhere (LTD, LLC, SARL, GMBH, PVT, ...)
 7. leading designators removed (M/S, MESSRS, ETS, SOCIETE, ENTREPRISE, CABINET, PT, ...)
If steps 5-7 would leave nothing (the name *is* a legal form), the pre-removal tokens are kept.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping

from unidecode import unidecode

# Two-letter codes that are also common initials (AB, AS, KG, OY, ...) are deliberately absent:
# after "A.B." -> "AB" they would delete a firm's own initials.
LEGAL_FORMS = frozenset({
    # English / Commonwealth
    "LTD", "LIMITED", "LLC", "LLP", "PLC", "INC", "INCORPORATED", "CORP", "CORPORATION",
    "CO", "COMPANY", "PVT", "PRIVATE", "PTY", "PTE",
    # French / Belgian / African francophone
    "SARL", "SARLU", "SA", "SAS", "SASU", "SNC", "EURL", "SUARL",
    # Spanish / Portuguese / Italian
    "SRL", "SAC", "SL", "SLU", "LTDA", "LDA", "EIRELI", "SPA", "SAPI",
    # German / Dutch / Nordic / Central-Eastern Europe
    "GMBH", "AG", "BV", "NV", "KFT", "ZRT", "DOO", "SRO",
    # Former Soviet Union / Turkey / Vietnam / Indonesia / Arabic world
    "JSC", "OJSC", "CJSC", "PJSC", "OOO", "TOO", "STI", "TNHH", "JSCO", "WLL", "FZC", "FZE", "FZCO",
})

LEGAL_PHRASES = (
    ("S", "DE", "RL", "DE", "CV"), ("SA", "DE", "CV"), ("S", "DE", "RL"),
    ("SOCIEDAD", "ANONIMA"), ("SOCIEDAD", "LIMITADA"), ("SOCIEDADE", "ANONIMA"),
    ("SOCIETE", "ANONYME"), ("SOCIETE", "A", "RESPONSABILITE", "LIMITEE"),
    ("JOINT", "STOCK", "COMPANY"), ("PUBLIC", "LIMITED", "COMPANY"), ("LIMITED", "LIABILITY", "COMPANY"),
    ("PRIVATE", "LIMITED"), ("SP", "ZOO"), ("SPOLKA", "Z", "OO"),
    ("CONG", "TY"), ("CO", "PHAN"), ("TRACH", "NHIEM", "HUU", "HAN"), ("MOT", "THANH", "VIEN"),
    ("SAN", "VE", "TIC"), ("SAN", "TIC"),
)

LEADING_DESIGNATORS = frozenset({
    "MS", "MESSRS", "THE", "ETS", "ETABLISSEMENT", "ETABLISSEMENTS", "STE", "SOCIETE", "ENTREPRISE", "CABINET",
    "PT", "CV",
})

CONSORTIUM_PATTERN = re.compile(
    r"\b(JV|J V|JOINT VENTURE|GROUPEMENT|CONSORTIUM|CONSORCIO|CONSORCIUM|IN ASSOCIATION WITH|ASSOCIATION WITH)\b")

# Words that mark a business rather than a person (English, French, Portuguese, Spanish), used by
# `is_person_like`. Includes family-firm markers (FILS, FRERES, SONS) that follow a person's name.
BUSINESS_WORDS = frozenset({
    "AGENCE", "AGENCY", "AGRO", "ASSOCIATES", "ASSOCIATION", "AUDIT", "AUTO", "BROTHERS", "BTP", "BUILDERS",
    "BUILDING", "BUREAU", "BUSINESS", "CABINET", "CENTER", "CENTRE", "CHEMICALS", "COMERCIAL", "COMERCIO",
    "COMMERCE", "COMMERCIAL", "COMMUNICATION", "COMPUTER", "COMPUTERS", "CONSEIL", "CONSEILS", "CONSTRUCAO",
    "CONSTRUCCIONES", "CONSTRUCOES", "CONSTRUCTION", "CONSTRUCTIONS", "CONSULT", "CONSULTANCY", "CONSULTANTS",
    "CONSULTING", "CONSULTORES", "CONSULTORIA", "CONTRACTOR", "CONTRACTORS", "COOPERATIVE", "DEPARTMENT",
    "DESIGN", "DEVELOPMENT", "DISTRIBUTION", "DISTRIBUTORS", "ELECTRIC", "ELECTRICALS", "ELECTRONICS",
    "ENGENHARIA", "ENGINEERING", "ENGINEERS", "ENTERPRISE", "ENTERPRISES", "ENTREPRISE", "EQUIPMENT",
    "ETUDES", "EXPORT", "FILS", "FOUNDATION", "FRERES", "FURNITURE", "GARAGE", "GENERAL", "GLOBAL", "GROUP",
    "GROUPE", "HARDWARE", "HOLDINGS", "HOTEL", "IMPORT", "IMPRIMERIE", "INDUSTRIES", "INDUSTRY", "INFRA",
    "INGENIERIA", "INGENIERIE", "INGENIEURS", "INSTITUTE", "INTERNATIONAL", "INVESTMENT", "INVESTMENTS", "LABORATORIES", "LIBRAIRIE",
    "LOGISTICS", "MANAGEMENT", "MARKETING", "MEDIA", "MEDICAL", "MINISTRY", "MOTORS", "NETWORK", "OFFICE",
    "PHARMA", "PHARMACIE", "PHARMACY", "PRESS", "PRINTERS", "PRINTING", "PROJECTS", "QUINCAILLERIE",
    "RESEARCH", "SERVICE", "SERVICES", "SERVICIOS", "SERVICOS", "SOCIETE", "SOLUTION", "SOLUTIONS", "SONS",
    "STORE", "STORES", "SUPPLIER", "SUPPLIERS", "SUPPLIES", "SUPPLY", "SYSTEMS", "TECH", "TECHNOLOGIES",
    "TECHNOLOGY", "TRADE", "TRADERS", "TRADING", "TRANSPORT", "TRAVAUX", "TRAVEL", "TRAVELS", "UNIVERSITY",
    "VENTURES", "WORKS",
})

# Joint-venture role markers carry no identity: 'ROHLET TRADING PLC (LEAD)', 'SMEC (LEAD PARTNER)'.
_JV_ROLE = re.compile(r"\(\s*LEAD(?:\s+(?:PARTNER|FIRM|MEMBER|CONSULTANT))?\s*\)")
# Words skipped when reading an acronym from a name ('LES CABLERIES DU SENEGAL' -> LCS).
ACRONYM_STOPWORDS = frozenset({"AND", "OF", "THE", "FOR", "DE", "DU", "DES", "D", "ET", "EN", "POUR", "Y", "E",
                               "DA", "DO", "DI", "DEL", "LA", "LE", "L"})
_ACRONYM_DOT = re.compile(r"\b([A-Z0-9])\.")
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


def _ascii_upper(text: str) -> str:
    cleaned = "".join(" " if unicodedata.category(ch) in ("Co", "Cc", "Cf") else ch for ch in text)
    return unidecode(cleaned).upper()


def _join_single_letters(tokens: list[str]) -> list[str]:
    out: list[str] = []
    run = ""
    for tok in tokens:
        if len(tok) == 1 and tok.isalpha():
            run += tok
            continue
        if run:
            out.append(run)
            run = ""
        out.append(tok)
    if run:
        out.append(run)
    return out


def _remove_phrases(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        for phrase in LEGAL_PHRASES:
            if tuple(tokens[i:i + len(phrase)]) == phrase:
                i += len(phrase)
                break
        else:
            out.append(tokens[i])
            i += 1
    return out


def base_tokens(name: str | None) -> list[str]:
    """Steps 1-4: transliterated, upper-case, punctuation-free tokens (legal forms still present)."""
    if not name:
        return []
    text = _JV_ROLE.sub(" ", _ascii_upper(name)).replace("&", " AND ")
    text = _ACRONYM_DOT.sub(r"\1", text)
    return _join_single_letters(_NON_ALNUM.sub(" ", text).split())


def normalise_supplier_name(name: str | None) -> str:
    """Comparison key for a supplier name, e.g. 'M/S. Aires Ingegneria S.p.A.' -> 'AIRES INGEGNERIA'."""
    tokens = base_tokens(name)
    stripped = [t for t in _remove_phrases(tokens) if t not in LEGAL_FORMS]
    while stripped and stripped[0] in LEADING_DESIGNATORS:
        stripped = stripped[1:]
    return " ".join(stripped or tokens)


def compact_key(normalised: str) -> str:
    """Normalised name without spaces, so 'ABC CONSULT' and 'ABCCONSULT' collide."""
    return normalised.replace(" ", "")


def is_consortium(name: str | None) -> bool:
    """True for joint-venture / consortium names (one supplier record naming several firms)."""
    return bool(name) and bool(CONSORTIUM_PATTERN.search(" ".join(base_tokens(name))))


def is_person_like(name: str | None) -> bool:
    """Heuristic: 2-4 alphabetic tokens, no legal form, no business word, no digits.

    Matches 'AJAY KUMAR' or 'MONICA VALLEJOS PINA'; not 'BALAJI ENTERPRISES' or 'ROYAL TRADING CO'.
    Personal names are not identifying (many different people are called AJAY KUMAR), so the
    resolver refuses to merge such names on spelling alone.
    """
    tokens = base_tokens(name)
    if not 2 <= len(tokens) <= 4:
        return False
    if any(not t.isalpha() for t in tokens):
        return False
    if any(t in LEGAL_FORMS or t in BUSINESS_WORDS for t in tokens):
        return False
    return not any(tuple(tokens[i:i + len(p)]) == p for p in LEGAL_PHRASES for i in range(len(tokens)))


def token_index(normalised_names: Iterable[str]) -> dict[str, set[str]]:
    """Token -> the set of (distinct) normalised names containing it."""
    index: dict[str, set[str]] = defaultdict(set)
    for name in set(normalised_names):
        for token in name.split():
            index[token].add(name)
    return index


def is_ambiguous_person_name(name: str | None, normalised: str, index: Mapping[str, set[str]],
                             max_others: int = 3) -> bool:
    """A person-like name whose every word is shared with *other* names, e.g. 'ARUN KUMAR' in India.

    For each word, count the names of the same country that contain it but not the rest of this
    name: ARUN appears in ARUN SHARMA, ARUN DAS, ...; KUMAR in hundreds of names. When every word
    is shared with more than `max_others` such names, spelling cannot tell two people apart and
    the resolver will not merge the record on name evidence. Counting only names *without* the
    other words matters: the spelling variants of a firm ('SEC DIARRA', 'SEC DIARRA SARL MALI')
    all contain both of its words and must not make its name look common.
    """
    if not is_person_like(name):
        return False
    tokens = normalised.split()
    if not tokens:
        return False
    sharing_all = set.intersection(*(set(index.get(t, ())) for t in tokens))
    return min(len(index.get(t, ())) - len(sharing_all) for t in tokens) > max_others


def is_acronym_of(short_name: str | None, long_name: str | None) -> bool:
    """True if the short name is the initials of the long one: 'SAHE' / 'SOCIETE AFRICAINE D'HYDRAULIQUE
    ET D'ELECTRICITE SARL', 'UPS LTD' / 'UNION PETROLEUM SERVICES LTD'. Legal forms are ignored on both
    sides; small connecting words may be skipped or counted."""
    short = [t for t in base_tokens(short_name) if t not in LEGAL_FORMS]
    words = [t for t in base_tokens(long_name) if t not in LEGAL_FORMS]
    if len(short) != 1 or not 2 <= len(short[0]) <= 8 or not short[0].isalpha() or len(words) < 2:
        return False
    with_all = "".join(w[0] for w in words)
    without_small = "".join(w[0] for w in words if w not in ACRONYM_STOPWORDS)
    return short[0] in (with_all, without_small)


def drop_self_acronym(normalised: str) -> str:
    """Remove a word that is just the initials of the others: 'ECONOMIC CONSULTING ASSOCIATES ECA' ->
    'ECONOMIC CONSULTING ASSOCIATES'. Such an acronym repeats the name and must not count as an
    extra distinctive word."""
    tokens = normalised.split()
    if len(tokens) < 3:
        return normalised
    for k, tok in enumerate(tokens):
        others = [t for i, t in enumerate(tokens) if i != k]
        initials = {"".join(t[0] for t in others),
                    "".join(t[0] for t in others if t not in ACRONYM_STOPWORDS)}
        if len(tok) >= 2 and tok in initials:
            return " ".join(others)
    return normalised


def digit_tokens(normalised: str) -> frozenset[str]:
    """Number tokens in a name ('TRUONG SON 145' -> {'145'}); differing numbers usually mean different firms."""
    return frozenset(re.findall(r"\d+", normalised))
