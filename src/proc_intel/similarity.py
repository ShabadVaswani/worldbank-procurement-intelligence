"""Candidate generation, pairwise scoring, clustering and evaluation for entity resolution.

Scoring choice: cosine similarity of TF-IDF weighted character 3-grams of the normalised name.
- character n-grams tolerate typos and spacing ("PRICEWTERHOUSECOOPERS", "ABCCONSULT"),
- TF-IDF down-weights n-grams from words every supplier uses ("CONSTRUCTION", "TRADING"),
- cosine ignores word order ("KUMAR AJAY" vs "AJAY KUMAR"),
- one number per pair, easy to threshold and to explain.
Jaro-Winkler and token-set ratios are computed alongside as explanatory features only.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Hashable, Iterable, Iterator, Sequence

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer


def char_ngram_tfidf(names: Sequence[str], ngram: int = 3) -> sparse.csr_matrix:
    """L2-normalised TF-IDF matrix of character n-grams (word-boundary aware), one row per name."""
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(ngram, ngram), sublinear_tf=True,
                                 dtype=np.float32)
    return vectorizer.fit_transform(names).tocsr()


def _block_scores(matrix: sparse.csr_matrix, blocks: Sequence[Hashable], min_score: float, chunk_size: int
                  ) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Yield (i, j, cosine) arrays, i < j, same block, cosine >= min_score, one row chunk at a time.

    Within a block almost every pair shares some trigram, so a chunk's product has about
    chunk_size x block_size non-zeros; the chunk size bounds that memory.
    """
    by_block: dict[Hashable, list[int]] = defaultdict(list)
    for idx, block in enumerate(blocks):
        by_block[block].append(idx)
    for members in by_block.values():
        if len(members) < 2:
            continue
        ids = np.asarray(members)
        sub = matrix[ids]
        for start in range(0, len(ids), chunk_size):
            scores = (sub[start:start + chunk_size] @ sub.T).tocoo()
            rows = scores.row + start
            keep = (scores.data >= min_score) & (rows < scores.col)
            yield ids[rows[keep]], ids[scores.col[keep]], scores.data[keep]


def candidate_pairs(matrix: sparse.csr_matrix, blocks: Sequence[Hashable], min_score: float,
                    chunk_size: int = 500) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """All pairs with i < j, same block and cosine >= min_score, as three arrays (i, j, cosine).

    Blocking (comparing only names within the same block, e.g. the same supplier country)
    keeps the work far below n^2; within a block the sparse product computes every cosine exactly.
    Arrays rather than a list of tuples: tens of millions of pairs stay a few hundred MB.
    """
    parts = list(_block_scores(matrix, blocks, min_score, chunk_size))
    if not parts:
        return np.array([], dtype=np.int64), np.array([], dtype=np.int64), np.array([], dtype=np.float32)
    return tuple(np.concatenate(arrays) for arrays in zip(*parts, strict=True))


def score_band_counts(matrix: sparse.csr_matrix, blocks: Sequence[Hashable], groups: Sequence[Hashable],
                      min_score: float, band_width: float = 0.1, chunk_size: int = 500) -> dict[float, int]:
    """Number of same-block pairs per cosine band (floor to band_width), skipping pairs of one group.

    Used to weight a stratified labelled sample: counts are accumulated chunk by chunk, so the
    pairs themselves are never held in memory.
    """
    codes = pd.factorize(pd.Series(list(groups)))[0]
    counts: dict[float, int] = defaultdict(int)
    for i, j, score in _block_scores(matrix, blocks, min_score, chunk_size):
        keep = codes[i] != codes[j]
        bands = np.minimum(np.floor(score[keep].astype(np.float64) / band_width) * band_width, 1.0).round(2)
        for band, n in zip(*np.unique(bands, return_counts=True), strict=True):
            counts[float(band)] += int(n)
    return dict(counts)


def explain_pair(a: str, b: str) -> dict[str, float]:
    """Secondary string scores for a pair of normalised names (0-1), for review tables."""
    return {"jaro_winkler": JaroWinkler.similarity(a, b),
            "token_set": fuzz.token_set_ratio(a, b) / 100.0,
            "ratio": fuzz.ratio(a, b) / 100.0}


def soft_word_match(words_a: str, words_b: str, extra_words: int = 1) -> float:
    """How well two word lists match word by word, allowing typos and a few extra words (0-1).

    Every word of the shorter list is compared with its best counterpart (fuzz.ratio) in the
    other list, and so is every word of the longer list except its `extra_words` worst-matched
    ones (forgiven only when the shorter list has two or more words). The result is the worst
    remaining score. 'TOUCHE TOHMATSU' vs 'TOUCH TOMATSU' -> 0.91; 'BAC GIANG' vs 'AN GIANG' -> 0.4
    (BAC has no counterpart). 0.0 if either list is empty.
    """
    a, b = words_a.split(), words_b.split()
    if not a or not b:
        return 0.0
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    short_scores = [max(fuzz.ratio(w, v) for v in long_) for w in short]
    long_scores = sorted(max(fuzz.ratio(w, v) for v in short) for w in long_)
    # an extra word is only forgiven next to at least two matched words: a one-word name such as
    # 'MULTISERVICES' would otherwise match every 'X MULTISERVICES' and become a hub
    allowed = min(extra_words, len(long_) - len(short)) if len(short) >= 2 else 0
    kept = long_scores[allowed:]
    return min(short_scores + kept) / 100.0


class UnionFind:
    """Disjoint sets with path halving and union by size."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.size = [1] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]


def connected_components(n: int, edges: Iterable[tuple[int, int]]) -> list[int]:
    """Component label for each of n nodes; the label is the smallest node index in the component."""
    uf = UnionFind(n)
    for a, b in edges:
        uf.union(a, b)
    smallest: dict[int, int] = {}
    roots = [uf.find(i) for i in range(n)]
    for i, root in enumerate(roots):
        smallest.setdefault(root, i)
    return [smallest[root] for root in roots]


def precision_recall(labels: Sequence[bool], predicted: Sequence[bool],
                     weights: Sequence[float] | None = None) -> dict[str, float]:
    """Precision, recall and F1 of `predicted` against hand `labels` (True = same entity).

    With `weights`, each pair counts as that many pairs: used when the labelled sample was drawn
    stratified by score band, so each pair stands for (pairs in its band / pairs sampled from it).
    The tp/fp/fn counts are always unweighted.
    """
    if len(labels) != len(predicted) or (weights is not None and len(weights) != len(labels)):
        raise ValueError("labels, predictions and weights must have the same length")
    w = [1.0] * len(labels) if weights is None else [float(x) for x in weights]
    tp = sum(wi for y, p, wi in zip(labels, predicted, w, strict=True) if y and p)
    fp = sum(wi for y, p, wi in zip(labels, predicted, w, strict=True) if not y and p)
    fn = sum(wi for y, p, wi in zip(labels, predicted, w, strict=True) if y and not p)
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if tp else 0.0
    counts = {"tp": sum(1 for y, p in zip(labels, predicted, strict=True) if y and p),
              "fp": sum(1 for y, p in zip(labels, predicted, strict=True) if not y and p),
              "fn": sum(1 for y, p in zip(labels, predicted, strict=True) if y and not p)}
    return {**counts, "precision": precision, "recall": recall, "f1": f1}


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion; sensible even for small samples or p near 0/1."""
    if trials == 0:
        return float("nan"), float("nan")
    p = successes / trials
    centre = (p + z * z / (2 * trials)) / (1 + z * z / trials)
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / (1 + z * z / trials)
    return centre - half, centre + half
