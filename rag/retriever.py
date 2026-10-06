"""检索器：把知识库包成"给一个问句，返回最相关的几条 chunk"。

当前只有 **BM25 一条腿**（A4 的基线）。
A5 会接上向量检索，用**同一套评测集**跑一遍，就能说出"向量把 Recall@1 从 X 提到了 Y"。

分层过滤（`layers=`）是有意留的：指标解释与指南要点来自不同层，
真实使用时会按意图路由，而不是混在一起搜。
"""

from __future__ import annotations

from dataclasses import dataclass

from rag.bm25 import BM25Index, build_index
from rag.knowledge import Chunk, KnowledgeBase, RETRIEVABLE_LAYERS

__all__ = ["Hit", "Retriever", "build_retriever"]


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    layer: str
    title: str
    text: str
    score: float
    rrf_score: float | None = None
    """多路融合后的分数（只有开到两条腿以上时才有值）。

    **为什么和 `score` 分开**：`score` 是 BM25 分（无界，用来和拒答阈值比较），
    `rrf_score` 是按**名次**融合出来的分（约 1/61 量级）。
    两者量纲完全不同，混在一起用会让阈值判断失去意义——
    所以宁可多一个字段，也不做隐式换算。
    """

    def to_dict(self) -> dict:
        payload = {
            "chunk_id": self.chunk_id,
            "layer": self.layer,
            "title": self.title,
            "text": self.text,
            "score": round(self.score, 4),
        }
        if self.rrf_score is not None:
            payload["rrf_score"] = round(self.rrf_score, 6)
        return payload


class Retriever:
    def __init__(self, knowledge: KnowledgeBase, index: BM25Index) -> None:
        self.knowledge = knowledge
        self.index = index

    def search(
        self, query: str, top_k: int = 5, layers: tuple[str, ...] | None = None
    ) -> list[Hit]:
        wanted = layers if layers is not None else RETRIEVABLE_LAYERS
        allowed = {chunk.chunk_id for chunk in self.knowledge.layers(*wanted)}

        results: list[Hit] = []
        for scored in self.index.search(query, top_k=top_k, allowed_ids=allowed):
            chunk = self.knowledge.by_id(scored.doc_id)
            if chunk is None:  # pragma: no cover — 索引与知识库同源
                continue
            results.append(
                Hit(
                    chunk_id=chunk.chunk_id,
                    layer=chunk.layer,
                    title=chunk.title,
                    text=chunk.text,
                    score=scored.score,
                )
            )
        return results

    def by_metric(self, metric_code: str) -> Chunk | None:
        return self.knowledge.by_id(f"kb://metric/{metric_code}")


def build_retriever(knowledge: KnowledgeBase) -> Retriever:
    return Retriever(knowledge, build_index(knowledge.documents()))
