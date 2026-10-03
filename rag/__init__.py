"""rag：知识库与检索。

    knowledge.py     三层知识库（L1 参考区间不进索引；L2 解释库 / L3 指南要点进索引）
    tokenize.py      中文/英文混合分词（BM25 按词算分）
    bm25.py          BM25 检索（基线）
    retriever.py     检索器（分层过滤）
    retrieval_eval.py  Recall@k 与 MRR 评测

核心分工：**数值判断走确定性，语义解释走检索。**
"""

from rag.knowledge import (
    LAYER_EXPLANATION,
    LAYER_GUIDELINE,
    LAYER_REFERENCE,
    Chunk,
    KnowledgeBase,
    load_knowledge,
)
from rag.retriever import Hit, Retriever, build_retriever
from rag.retrieval_eval import (
    RetrievalCase,
    RetrievalReport,
    build_eval_set,
    evaluate_retrieval,
)

__all__ = [
    "Chunk",
    "Hit",
    "KnowledgeBase",
    "LAYER_EXPLANATION",
    "LAYER_GUIDELINE",
    "LAYER_REFERENCE",
    "RetrievalCase",
    "RetrievalReport",
    "Retriever",
    "build_eval_set",
    "build_retriever",
    "evaluate_retrieval",
    "load_knowledge",
]
