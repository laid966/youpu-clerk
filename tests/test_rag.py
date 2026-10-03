"""知识库与检索测试。

重点守两类东西：
1. **检索机制本身**（分词、BM25 排序、分层过滤）——坏了会让所有下游全错。
2. **基线指标不许退化**——用回归守卫把 A4 的成绩钉住。
   （同时提醒：这些守卫只能防退化，不能证明检索质量；真实问句集才是检验。）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.bm25 import build_index
from rag.knowledge import (
    LAYER_EXPLANATION,
    LAYER_GUIDELINE,
    RETRIEVABLE_LAYERS,
    load_knowledge,
)
from rag.retrieval_eval import build_eval_set, evaluate_retrieval
from rag.retriever import build_retriever
from rag.tokenize import tokenize

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def knowledge():
    return load_knowledge()


@pytest.fixture(scope="module")
def retriever(knowledge):
    return build_retriever(knowledge)


@pytest.fixture(scope="module")
def report(retriever, knowledge):
    return evaluate_retrieval(retriever, build_eval_set(knowledge), k_values=(1, 3, 5))


# --------------------------------------------------------------------------- #
# 分词
# --------------------------------------------------------------------------- #


def test_ascii_abbreviations_stay_intact():
    """`ALT`、`U/L`、`13.9` 必须整块保留——它们是检索里最有价值的精确信号。"""
    assert "alt" in tokenize("ALT 偏高")
    assert "u/l" in tokenize("单位是 U/L")
    assert "13.9" in tokenize("空腹血糖 13.9")


def test_chinese_is_tokenized():
    tokens = tokenize("丙氨酸氨基转移酶偏高")
    assert tokens, "中文必须能切出词"
    assert all(isinstance(token, str) for token in tokens)


def test_question_words_are_dropped():
    """疑问词污染是实测踩过的坑：`怎么办` 曾把无关的指南条目顶上第一名。"""
    tokens = tokenize("ALT 偏高怎么办")
    assert "alt" in tokens
    assert "怎么办" not in tokens, "疑问词必须被丢掉，否则它会用高 IDF 污染排序"


def test_stopword_and_punctuation_are_dropped():
    tokens = tokenize("这个是什么，应该怎么办？")
    assert "这个" not in tokens
    assert "，" not in tokens
    assert "？" not in tokens


def test_empty_text_gives_no_tokens():
    assert tokenize("") == []


# --------------------------------------------------------------------------- #
# BM25
# --------------------------------------------------------------------------- #


def test_rare_term_identifies_the_right_document():
    index = build_index({"d1": "空腹血糖 偏高", "d2": "尿酸 尿酸 尿酸", "d3": "尿酸"})
    hits = index.search("血糖", top_k=3)
    assert hits and hits[0].doc_id == "d1"


def test_empty_query_returns_nothing():
    index = build_index({"d1": "尿酸"})
    assert index.search("") == []


def test_ranking_is_deterministic_on_ties():
    """分数相同时按 doc_id 稳定排序——否则评测结果不可复现。"""
    index = build_index({"b": "尿酸", "a": "尿酸"})
    assert [hit.doc_id for hit in index.search("尿酸")] == ["a", "b"]


def test_no_match_scores_zero_and_is_filtered():
    index = build_index({"d1": "尿酸"})
    assert index.search("完全不相关的词汇") == []


def test_empty_corpus_is_rejected():
    with pytest.raises(ValueError):
        build_index({})


# --------------------------------------------------------------------------- #
# 知识库
# --------------------------------------------------------------------------- #


def test_knowledge_has_three_layers(knowledge):
    metric_chunks = [c for c in knowledge.chunks if c.layer == LAYER_EXPLANATION]
    guideline_chunks = [c for c in knowledge.chunks if c.layer == LAYER_GUIDELINE]

    assert len(metric_chunks) == 8, "8 个指标各一张卡"
    assert len(guideline_chunks) == 7
    assert len(knowledge.reference_table) == 8


def test_reference_table_is_not_indexed(knowledge):
    """L1 参考区间是精确数值，**不进检索索引**——数值判断走确定性。"""
    indexed_ids = set(knowledge.documents())
    for chunk in knowledge.chunks:
        assert chunk.layer in RETRIEVABLE_LAYERS
    assert all(chunk_id.startswith("kb://") for chunk_id in indexed_ids)


def test_chunk_ids_are_unique(knowledge):
    ids = [chunk.chunk_id for chunk in knowledge.chunks]
    assert len(ids) == len(set(ids))


def test_metric_chunk_carries_keywords_and_repeats_title(knowledge):
    """两个被真实失败逼出来的设计，都要守住。"""
    chunk = knowledge.by_id("kb://metric/alt")
    assert chunk is not None
    assert "偏高" in chunk.keywords, "方向词必须补齐到每张指标卡上"

    text = chunk.index_text()
    assert text.count(chunk.title) == 2, "标题必须重复两次以起到加权作用"
    assert "alt" in text.lower(), "缩写必须进正文，用户可能只写 ALT"


def test_every_metric_has_a_chunk(knowledge):
    for code in knowledge.reference_table:
        assert knowledge.by_id(f"kb://metric/{code}") is not None


# --------------------------------------------------------------------------- #
# 检索器与评测
# --------------------------------------------------------------------------- #


def test_layer_filter_works(retriever):
    only_guideline = retriever.search("复查", top_k=5, layers=(LAYER_GUIDELINE,))
    assert only_guideline
    assert all(hit.layer == LAYER_GUIDELINE for hit in only_guideline)


def test_retrieval_eval_set_is_complete(knowledge):
    cases = build_eval_set(knowledge)
    assert len(cases) == 31, "8 指标 × 3 问法 + 7 指南 = 31"
    for case in cases:
        assert case.relevant, f"{case.case_id} 没有标准答案"
        for chunk_id in case.relevant:
            assert knowledge.by_id(chunk_id) is not None, f"{case.case_id} 指向了不存在的 chunk"


def test_baseline_does_not_regress(report):
    """回归守卫：A4 的基线成绩不许退化。

    ⚠️ 这只防退化，不证明质量。这些问句是模板生成的、标准答案大多只有一条，
    真实用户的问法会更模糊。真实问句集是分工里"人的部分"。
    """
    assert report.cases == 31
    assert report.recall_at(3) == 1.0, f"Recall@3 退化到 {report.recall_at(3):.1%}"
    assert report.recall_at(1) >= 0.90, f"Recall@1 退化到 {report.recall_at(1):.1%}"
    assert report.mrr >= 0.95, f"MRR 退化到 {report.mrr:.3f}"
    assert report.misses == (), f"有 {len(report.misses)} 条没进前 5"


def test_evaluation_is_deterministic(retriever, knowledge):
    cases = build_eval_set(knowledge)
    first = evaluate_retrieval(retriever, cases)
    second = evaluate_retrieval(retriever, cases)
    assert first.recall_at(1) == second.recall_at(1)
    assert first.mrr == second.mrr
