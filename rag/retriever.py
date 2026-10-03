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

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "layer": self.layer,
            "title": self.title,
            "text": self.text,
            "score": round(self.score, 4),
        }


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
