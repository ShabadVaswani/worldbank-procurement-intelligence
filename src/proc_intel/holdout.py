"""A small, fresh holdout of review packages (phase 5, p17).

The fact-check changes of phase 5 were tuned on the 30 review packages of p11. A holdout checks that they work on
packages nobody looked at: openly competed test-period tenders outside p11's 300-package sample, spread over
regions, categories and methods, in a fixed hash order so every run picks the same ones.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import cycle

from proc_intel.backtest import stable_hash

CATEGORIES = ("CW", "GO", "CS", "NC")


def usable_description(text: str | None, min_chars: int = 40) -> bool:
    """A package text a planner could search with: at least `min_chars` characters and at least four words."""
    if not isinstance(text, str):                       # None or a pandas NaN
        return False
    t = text.strip()
    return len(t) >= min_chars and len(t.split()) >= 4


def pick_holdout(rows: Sequence[Mapping], n: int, seed: int | str, categories: Sequence[str] = CATEGORIES,
                 key_prefix: str = "holdout") -> list[dict]:
    """Pick n packages, one slot at a time, cycling through `categories`.

    For each slot, candidates of that category are read in the order of sha1(f"{seed}|{key_prefix}|{row_id}") and the
    first one with the best (new region, new region x category stratum, new method) preference is taken; a row whose
    tender notice or project is already picked is never taken (one lot per tender, one tender per project). A category
    with no candidates left is skipped. Rows need row_id, notice_id, project_id, region, category, method.
    """
    ordered = sorted(rows, key=lambda r: stable_hash(seed, f"{key_prefix}|{r['row_id']}"))
    by_cat = {c: [r for r in ordered if r["category"] == c] for c in categories}
    picked: list[dict] = []
    regions, strata, methods, notices, projects = set(), set(), set(), set(), set()
    empty = set()
    for cat in cycle(categories):
        if len(picked) >= n or len(empty) == len(categories):
            break
        if cat in empty:
            continue
        free = [r for r in by_cat[cat] if r["notice_id"] not in notices and r["project_id"] not in projects]
        if not free:
            empty.add(cat)
            continue
        best = max(free, key=lambda r: (r["region"] not in regions, (r["region"], cat) not in strata,
                                        r["method"] not in methods))       # max keeps the first of equal keys
        picked.append(dict(best))
        regions.add(best["region"])
        strata.add((best["region"], cat))
        methods.add(best["method"])
        notices.add(best["notice_id"])
        projects.add(best["project_id"])
    return picked


def full_cited_text(rec: Mapping, short: str) -> str:
    """A cited record's text for the labeller: its facts line (contracts carry one) before the short text."""
    facts = (rec.get("facts") or "").strip()
    return f"{facts} | {short}" if facts else short
