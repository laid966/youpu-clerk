"""rag：知识库与检索（一条可分级开关的 RAG 链路）。

    knowledge.py      三层知识库（L1 参考区间不进索引；L2 解释库 / L3 指南要点进索引）
    tokenize.py       中文/英文混合分词（BM25 按词算分）
    bm25.py           BM25 检索（基线，单腿）
    retriever.py      单腿检索器（基线，保留用于对比）
    stages.py         链路各级：查询理解 / RRF 融合 / 重排
    pipeline.py       多级链路（search 兼容基线接口，explain 带拒答）
    stage_eval.py     分级增益 + 拒答双向测量
    boundary.py       ★作者的文件★ 拒答边界与「什么算答对」的判定口径
    retrieval_eval.py Recall@k 与 MRR 评测

核心分工：**数值判断走确定性，语义解释走检索。**

一条纪律：**每一级都要有自己的数字。**
没有增益的级要写明原因，不许留在那里假装有用（实测：硬路由 -25 个点，
所以它只作为可复现的反例保留，默认关闭）。
"""

from rag.boundary import CORRECTNESS, REFUSAL, CorrectnessRule, RefusalBoundary
from rag.knowledge import (
    LAYER_EXPLANATION,
    LAYER_GUIDELINE,
    LAYER_REFERENCE,
    Chunk,
    KnowledgeBase,
    load_knowledge,
)
from rag.pipeline import PipelineFlags, PipelineResult, RagPipeline, build_pipeline
from rag.retriever import Hit, Retriever, build_retriever
from rag.retrieval_eval import (
    RetrievalCase,
    RetrievalReport,
    build_eval_set,
    evaluate_retrieval,
)
from rag.stages import QueryPlan, rrf_fuse, understand_query

__all__ = [
    "CORRECTNESS",
    "REFUSAL",
    "Chunk",
    "CorrectnessRule",
    "Hit",
    "KnowledgeBase",
    "LAYER_EXPLANATION",
    "LAYER_GUIDELINE",
    "LAYER_REFERENCE",
    "PipelineFlags",
    "PipelineResult",
    "QueryPlan",
    "RagPipeline",
    "RefusalBoundary",
    "RetrievalCase",
    "RetrievalReport",
    "Retriever",
    "build_eval_set",
    "build_pipeline",
    "build_retriever",
    "evaluate_retrieval",
    "load_knowledge",
    "rrf_fuse",
    "understand_query",
]
