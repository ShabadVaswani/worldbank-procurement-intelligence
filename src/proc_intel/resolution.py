"""Supplier entity resolution: records -> candidate pairs -> match decisions -> entities.

A *record* is one (supplier_id, name, country_code) combination. Records are linked by three
kinds of evidence, then grouped into entities as connected components:

  same_id     the two records share a supplier_id AND their names are similar (cosine >= 0.5)
              or one is the acronym of the other ('SAHE' / 'SOCIETE AFRICAINE D'HYDRAULIQUE ...')
  exact_name  same comparison string, ignoring spaces, in the same country
  fuzzy_name  character-trigram cosine >= threshold in the same country, with the same numbers in
              the name, the same joint-venture status and matching *distinctive* words

Refinements that came from reading wrong merges on the real data (see p04):
- A shared supplier_id is not trusted when the names disagree: one prolific Niger contractor's
  id also carried eight partner firms' names, which chained nine firms into one entity.
- Within a country block the country's own name is noise ('ERNST & YOUNG NIGERIA').
- Long generic phrases inflate the trigram cosine ('LAND REGISTRATION OFFICE OF LAO CAI PROVINCE'
  vs '... OF THAI BINH PROVINCE'). Words common among a country's names are generic; the
  remaining distinctive words must match word by word at 0.9 (one-letter differences such as
  'KARANJEET' / 'CHARANJEET SINGH' stay apart), allowing one extra word on the longer side when
  at least two words match; a word that is only the initials of the others ('... ASSOCIATES ECA')
  is dropped first.
- Ambiguous personal names ('ARUN KUMAR' in India) get no name links: spelling cannot tell two
  people apart. Records without a supplier country get no name links either: without a country the
  block mixes the whole world, and one-word names became hubs ('MULTISERVICES' joined hundreds of
  'X MULTISERVICES' firms).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations, pairwise

import numpy as np
import pandas as pd

from .names import (
    compact_key,
    digit_tokens,
    drop_self_acronym,
    is_acronym_of,
    is_ambiguous_person_name,
    is_consortium,
    normalise_supplier_name,
    token_index,
)
from .similarity import candidate_pairs, char_ngram_tfidf, connected_components, soft_word_match

NO_COUNTRY = "<none>"


@dataclass(frozen=True)
class MatchRules:
    fuzzy_threshold: float = 0.70       # cosine needed for a fuzzy_name link (chosen on labelled pairs in p04)
    candidate_floor: float = 0.50       # pairs below this cosine are never scored as name candidates
    same_id_min_cosine: float = 0.50    # names under one supplier_id must be at least this similar (or an acronym)
    ambiguous_max_others: int = 3       # see names.is_ambiguous_person_name
    generic_min_df: int = 10            # a word found in more than max(generic_min_df,
    generic_share: float = 0.005        #   generic_share * distinct names) of a country's names is generic
    core_min_similarity: float = 0.90   # distinctive words of the two names must match at this ratio


def strip_country_name(normalised: str, country_name: str | None, country_code: str | None) -> str:
    """Remove the block's own country from a name: its name anywhere, its code as the last word."""
    text = normalised
    if country_name:
        phrase = normalise_supplier_name(country_name)
        if phrase:
            text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text)
    tokens = text.split()
    # the code only as the last word ("ACME BUILDERS NG"); elsewhere two letters are more likely initials
    if country_code and len(tokens) > 1 and tokens[-1] == country_code.upper():
        tokens = tokens[:-1]
    return " ".join(tokens) or normalised


def distinctive_words(comparison: str, token_df: Mapping[str, int], generic_df: float) -> str:
    """The words of a name that are not generic in its country, sorted (order-insensitive).

    Singular and plural count together ('SOLUTION' is generic if 'SOLUTIONS' is), so two spellings
    of one firm do not end up with different distinctive words.
    """
    def frequency(word: str) -> int:
        variants = {word, word + "S", word[:-1] if word.endswith("S") else word}
        return max(token_df.get(v, 0) for v in variants)
    return " ".join(sorted(t for t in comparison.split() if frequency(t) <= generic_df))


def prepare_records(records: pd.DataFrame, rules: MatchRules = MatchRules(),
                    country_names: Mapping[str, str] | None = None) -> pd.DataFrame:
    """Add comparison strings and flags to records with columns supplier_id, name, country_code.

    `country_names` maps country_code -> country name (used by strip_country_name). Rows are sorted
    by (supplier_id, name, country_code) so that positions, and therefore entity ids, are deterministic.
    Extra columns (e.g. a usage weight) are kept.
    """
    country_names = country_names or {}
    # positions become node ids in the union-find, and the first record of a component names its entity: sort first so
    # ids are stable across runs
    out = records.sort_values(["supplier_id", "name", "country_code"], na_position="last").reset_index(drop=True)
    out["block"] = out["country_code"].fillna(NO_COUNTRY)
    out["normalised"] = out["name"].map(normalise_supplier_name)
    out["comparison"] = [drop_self_acronym(strip_country_name(n, country_names.get(c), c) if isinstance(c, str) else n)
                         for n, c in zip(out["normalised"], out["country_code"], strict=True)]
    out["key"] = out["comparison"].map(compact_key)
    out["is_consortium"] = out["name"].map(is_consortium)
    out["digits"] = out["normalised"].map(digit_tokens)
    ambiguous = pd.Series(False, index=out.index)
    distinctive = pd.Series("", index=out.index)
    for _, idx in out.groupby("block").groups.items():
        names = out.loc[idx, "comparison"]
        index = token_index(names)
        token_df = {t: len(v) for t, v in index.items()}
        # a floor of 10 names for small countries, 0.5% of the distinct names for large ones
        generic_df = max(rules.generic_min_df, rules.generic_share * names.nunique())
        ambiguous.loc[idx] = [is_ambiguous_person_name(name, comp, index, rules.ambiguous_max_others)
                              for name, comp in zip(out.loc[idx, "name"], names, strict=True)]
        distinctive.loc[idx] = [distinctive_words(comp, token_df, generic_df) for comp in names]
    out["ambiguous_person"] = ambiguous
    out["distinctive"] = distinctive
    return out


def _within_groups(records: pd.DataFrame, columns: list[str], chain: bool) -> set[tuple[int, int]]:
    """Index pairs inside each group: consecutive members (chain) or all pairs."""
    pairs: set[tuple[int, int]] = set()
    for _, idx in records.groupby(columns if len(columns) > 1 else columns[0]).groups.items():
        members = sorted(idx)
        pairs.update(pairwise(members) if chain else combinations(members, 2))
    return pairs


def score_candidates(records: pd.DataFrame, rules: MatchRules = MatchRules()) -> pd.DataFrame:
    """Pairs to decide on, with their cosine and the features the rules use.

    Name candidates: same block and cosine >= candidate_floor, plus records with an identical key.
    Same-id pairs: every pair of records sharing a supplier_id, in any block, whatever the cosine.
    """
    matrix = char_ngram_tfidf(records["comparison"].tolist())
    i, j, cosine = candidate_pairs(matrix, records["block"].tolist(), rules.candidate_floor)
    pairs = pd.DataFrame({"i": i, "j": j})
    named = records[records["key"] != ""]
    # identical keys are chained (n-1 pairs instead of n^2: one link each is enough to connect them);
    # shared ids need every pair, because each pair is checked for similar names separately
    extra = _within_groups(named, ["block", "key"], chain=True) | _within_groups(records, ["supplier_id"], chain=False)
    extra = pd.DataFrame(sorted(extra), columns=["i", "j"])
    pairs = pd.concat([pairs, extra], ignore_index=True).drop_duplicates(["i", "j"], ignore_index=True)
    if pairs.empty:
        return pairs.assign(cosine=0.0, same_id=False, acronym=False, same_key=False, digits_agree=False,
                            consortium_agree=False, ambiguous=False, no_country=False, core_similarity=0.0)
    pairs["cosine"] = np.asarray(matrix[pairs["i"].to_numpy()].multiply(matrix[pairs["j"].to_numpy()]).sum(axis=1)).ravel()
    a, b = records.loc[pairs["i"]].reset_index(drop=True), records.loc[pairs["j"]].reset_index(drop=True)
    pairs["same_id"] = (a["supplier_id"] == b["supplier_id"]).to_numpy()
    pairs["acronym"] = [same and (is_acronym_of(x, y) or is_acronym_of(y, x))
                        for same, x, y in zip(pairs["same_id"], a["name"], b["name"], strict=True)]
    pairs["same_key"] = ((a["key"] == b["key"]) & (a["key"] != "") & (a["block"] == b["block"])).to_numpy()
    pairs["digits_agree"] = (a["digits"] == b["digits"]).to_numpy()
    pairs["consortium_agree"] = (a["is_consortium"] == b["is_consortium"]).to_numpy()
    pairs["ambiguous"] = (a["ambiguous_person"] | b["ambiguous_person"]).to_numpy()
    pairs["no_country"] = (a["block"] == NO_COUNTRY).to_numpy()
    pairs["core_similarity"] = [soft_word_match(x, y) for x, y in zip(a["distinctive"], b["distinctive"], strict=True)]
    return pairs


def decide(pairs: pd.DataFrame, rules: MatchRules = MatchRules()) -> pd.Series:
    """Rule that links each pair ('same_id' / 'exact_name' / 'fuzzy_name'), or None."""
    # a shared id links only names that look alike; otherwise one id carrying partner firms' names would chain them
    # together
    same_id = pairs["same_id"] & ((pairs["cosine"] >= rules.same_id_min_cosine) | pairs["acronym"])
    # same-id pairs are decided by the rule above only; name rules apply to pairs of different ids
    usable = ~pairs["ambiguous"] & ~pairs["same_id"] & ~pairs["no_country"]
    exact = usable & pairs["same_key"]
    fuzzy = (usable & ~pairs["same_key"] & (pairs["cosine"] >= rules.fuzzy_threshold)
             & pairs["digits_agree"] & pairs["consortium_agree"]
             & (pairs["core_similarity"] >= rules.core_min_similarity))
    # np.select takes the first true condition, so a pair records its strongest rule
    return pd.Series(np.select([same_id, exact, fuzzy], ["same_id", "exact_name", "fuzzy_name"], default=None),
                     index=pairs.index, dtype=object)


def resolve(records: pd.DataFrame, pairs: pd.DataFrame, rule: pd.Series) -> pd.Series:
    """Entity id per record: 'SE-' + the supplier_id of the first record of its component.

    When a supplier_id is split across components (its names were not trusted to be one firm),
    the later components get a suffix: 'SE-510', 'SE-510-2'.
    """
    linked = rule.notna()
    labels = connected_components(len(records), zip(pairs.loc[linked, "i"], pairs.loc[linked, "j"], strict=True))
    first_id = records["supplier_id"].to_numpy()
    names: dict[int, str] = {}
    used: dict[str, int] = {}
    for label in sorted(set(labels)):
        base = f"SE-{first_id[label]}"
        used[base] = used.get(base, 0) + 1
        # labels are visited in sorted order, so which component gets the suffix is deterministic
        names[label] = base if used[base] == 1 else f"{base}-{used[base]}"
    return pd.Series([names[label] for label in labels], index=records.index)
