import math

import numpy as np
import pytest

from proc_intel.similarity import (
    UnionFind,
    candidate_pairs,
    char_ngram_tfidf,
    connected_components,
    explain_pair,
    precision_recall,
    score_band_counts,
    soft_word_match,
    wilson_interval,
)


def test_tfidf_rows_are_unit_length():
    m = char_ngram_tfidf(["AIRES INGEGNERIA", "ALL INGEGNERIA", "MEDICOM"])
    norms = np.asarray(m.multiply(m).sum(axis=1)).ravel()
    assert all(math.isclose(float(n), 1.0, rel_tol=1e-5) for n in norms)


def test_candidate_pairs_respects_blocks_and_threshold():
    names = ["PRICEWATERHOUSECOOPERS", "PRICEWTERHOUSECOOPERS", "PRICEWATERHOUSECOOPERS", "MEDICOM"]
    blocks = ["AL", "AL", "PL", "AL"]
    i, j, score = candidate_pairs(char_ngram_tfidf(names), blocks, min_score=0.5)
    assert list(zip(i.tolist(), j.tolist(), strict=True)) == [(0, 1)]       # 0-2 is identical but in another block
    assert 0.5 <= score[0] < 1.0


def test_candidate_pairs_small_chunks_give_same_result():
    names = [f"SUPPLIER {c}" for c in "ABCDEFG"] + ["SUPPLIER A"]
    m = char_ngram_tfidf(names)
    full = set(zip(*[a.tolist() for a in candidate_pairs(m, ["X"] * len(names), min_score=0.3)[:2]], strict=True))
    chunked = set(zip(*[a.tolist() for a in candidate_pairs(m, ["X"] * len(names), min_score=0.3, chunk_size=3)[:2]], strict=True))
    assert full == chunked and (0, 7) in full


def test_candidate_pairs_empty():
    i, j, score = candidate_pairs(char_ngram_tfidf(["A B", "C D"]), ["X", "Y"], min_score=0.5)
    assert len(i) == len(j) == len(score) == 0


def test_score_band_counts_skips_same_group():
    names = ["ALPHA TRADING", "ALPHA TRADING", "ALPHA TRADNG", "BETA"]
    m = char_ngram_tfidf(names)
    counts = score_band_counts(m, ["X"] * 4, groups=["1", "1", "2", "3"], min_score=0.3)
    i, j, score = candidate_pairs(m, ["X"] * 4, min_score=0.3)
    expected = sum(1 for a, b in zip(i, j, strict=True) if (a, b) != (0, 1))
    assert sum(counts.values()) == expected and 1.0 not in counts


def test_word_order_does_not_matter_much():
    m = char_ngram_tfidf(["AJAY KUMAR", "KUMAR AJAY"])
    assert float((m[0] @ m[1].T).toarray()[0, 0]) > 0.8


def test_explain_pair_ranges():
    scores = explain_pair("AIRES INGEGNERIA", "AIRES INGEGNERIA SRL")
    assert all(0.0 <= v <= 1.0 for v in scores.values())
    assert scores["token_set"] == 1.0


def test_union_find_and_components():
    uf = UnionFind(4)
    uf.union(0, 1)
    assert uf.find(0) == uf.find(1) != uf.find(2)
    assert connected_components(6, [(0, 1), (1, 2), (4, 5)]) == [0, 0, 0, 3, 4, 4]


def test_components_without_edges():
    assert connected_components(3, []) == [0, 1, 2]


def test_precision_recall():
    labels = [True, True, False, False, True]
    predicted = [True, False, True, False, True]
    r = precision_recall(labels, predicted)
    assert (r["tp"], r["fp"], r["fn"]) == (2, 1, 1)
    assert r["precision"] == pytest.approx(2 / 3) and r["recall"] == pytest.approx(2 / 3)


def test_precision_recall_length_mismatch():
    with pytest.raises(ValueError):
        precision_recall([True], [True, False])


def test_weighted_precision_recall():
    labels = [True, False, True]
    predicted = [True, True, False]
    r = precision_recall(labels, predicted, weights=[1.0, 3.0, 1.0])
    assert r["precision"] == pytest.approx(0.25) and r["recall"] == pytest.approx(0.5)
    assert (r["tp"], r["fp"], r["fn"]) == (1, 1, 1)


def test_wilson_interval():
    low, high = wilson_interval(9, 10)
    assert 0.55 < low < 0.6 and 0.98 < high < 0.99
    assert wilson_interval(10, 10)[1] == pytest.approx(1.0)
    assert all(math.isnan(x) for x in wilson_interval(0, 0))


def test_soft_word_match():
    assert soft_word_match("TOUCHE TOHMATSU", "TOUCH TOMATSU") > 0.9
    assert soft_word_match("BAC GIANG", "AN GIANG") < 0.5
    assert soft_word_match("ANHUI ANZE", "ANHUI ANZE PARTNERS") == 1.0   # one extra word next to two matches
    assert soft_word_match("ANHUI ANZE", "ANHUI ANZE PARTNERS GROUP") <= 0.5  # two extra words are not
    assert soft_word_match("MULTISERVICES", "ABIL MULTISERVICES") < 0.5    # one-word names get no allowance
    assert soft_word_match("DAOUDA TANKARI", "TANKARI DAOUDA") == 1.0
    assert soft_word_match("", "ANY") == 0.0
