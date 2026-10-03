"""BM25：按关键词匹配程度给文档打分。零训练、零成本、可解释。

    这是检索的**基线**，不是终点。

公式（Okapi BM25）对每个查询词 t 与文档 d：

    score(t, d) = IDF(t) · ( f(t,d) · (k1 + 1) )
                  ────────────────────────────────────────────
                  ( f(t,d) + k1 · (1 - b + b · |d| / avgdl) )

三层直觉：
1. **词出现越多越相关**，但会饱和 —— k1 管这个（出现 100 次不该比 10 次相关 10 倍）
2. **越稀有的词越值钱** —— IDF 管这个（"的"没用，"尿酸"很值钱）
3. **文档越长越吃亏，要归一化** —— b 管这个

参数默认取 k1=1.5、b=0.75（常用取值）。这两个数要能在面试里解释：
k1 越大越奖励重复出现（容易过拟合长文档），b=1 表示完全按长度惩罚、b=0 表示不惩罚。

**它的局限**：完全不懂语义。搜"转氨酶高"匹配不到只写了"丙氨酸氨基转移酶"的文档；
同义词、缩写、语序变化都处理不了。这正是后面要接向量检索的原因——
届时用**同一套评测集**跑一遍，就能说出"向量把 Recall@5 从 X 提到了 Y"。
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from rag.tokenize import tokens_for_index

__all__ = ["BM25Index", "ScoredDocument", "build_index"]

K1 = 1.5
B = 0.75
EPSILON = 0.25  # 防止某个词在全部文档里都出现时 IDF 变成负数


@dataclass(frozen=True)
class ScoredDocument:
    doc_id: str
    score: float


class BM25Index:
    """极简 BM25 实现。语料只有几十到几万条时，纯 Python 足够快。"""

    def __init__(self, documents: Mapping[str, str], k1: float = K1, b: float = B) -> None:
        if not documents:
            raise ValueError("语料不能为空")

        self.k1 = k1
        self.b = b
        self.doc_ids: tuple[str, ...] = tuple(documents)
        self.term_frequencies: dict[str, Counter[str]] = {}
        self.lengths: dict[str, int] = {}
        document_frequency: Counter[str] = Counter()

        for doc_id, text in documents.items():
            tokens = tokens_for_index(text)
            counts = Counter(tokens)
            self.term_frequencies[doc_id] = counts
            self.lengths[doc_id] = max(len(tokens), 1)
            for term in counts:
                document_frequency[term] += 1

        total = len(self.doc_ids)
        self.average_length = sum(self.lengths.values()) / total
        self.idf: dict[str, float] = {
            term: math.log(1 + (total - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

    def score(self, doc_id: str, query_tokens: Sequence[str]) -> float:
        counts = self.term_frequencies[doc_id]
        length = self.lengths[doc_id]
        total = 0.0
        for token in query_tokens:
            frequency = counts.get(token, 0)
            if not frequency:
                continue
            idf = self.idf.get(token, 0.0)
            denominator = frequency + self.k1 * (
                1 - self.b + self.b * length / self.average_length
            )
            total += idf * (frequency * (self.k1 + 1)) / denominator
        return total

    def search(
        self, query: str, top_k: int = 5, allowed_ids: Iterable[str] | None = None
    ) -> list[ScoredDocument]:
        query_tokens = tokens_for_index(query)
        if not query_tokens:
            return []

        allowed = set(allowed_ids) if allowed_ids is not None else None
        scored = [
            ScoredDocument(doc_id=doc_id, score=self.score(doc_id, query_tokens))
            for doc_id in self.doc_ids
            if allowed is None or doc_id in allowed
        ]
        scored = [item for item in scored if item.score > 0]
        # 分数相同时按 doc_id 稳定排序，保证结果可复现
        scored.sort(key=lambda item: (-item.score, item.doc_id))
        return scored[:top_k]


def build_index(documents: Mapping[str, str], k1: float = K1, b: float = B) -> BM25Index:
    return BM25Index(documents, k1=k1, b=b)
