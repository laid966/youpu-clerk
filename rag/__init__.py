"""rag：知识库与检索（一条可分级开关的 RAG 链路）。

    knowledge.py      三层知识库（L1 参考区间不进索引；L2 解释库 / L3 指南要点进索引）
                      两种索引文本：index_text() 给关键词腿，dense_text() 给语义腿
    tokenize.py       中文/英文混合分词（BM25 按词算分）
    bm25.py           BM25 检索（关键词腿）
    dense.py          语义腿：本地 ONNX + BGE 小模型（离线、零成本）
    stages.py         链路各级：查询理解 / RRF 融合（可加权）/ 腿内重排
    llm_stages.py     LLM 两级：查询改写 + listwise 重排（走缓存）
    llm_prompts.py    ★作者的文件★ 上面那两级的提示词
    pipeline.py       多级链路（search 兼容基线接口，explain 带拒答）
    stage_eval.py     分级增益 + 拒答双向测量 + 两条腿互补性诊断
    boundary.py       ★作者的文件★ 拒答边界、判定口径、融合权重
    retrieval_eval.py Recall@k 与 MRR 评测

核心分工：**数值判断走确定性，语义解释走检索。**

## 三条用数字换来的纪律

1. **每一级都要有自己的数字。** 没有增益的级要写明原因——
   实测：硬路由 -25 个点（只作可复现的反例保留），
   语义腿在 15 条语料上**零独占正确**（因此默认关闭）。
2. **同一条文本不能服务两种检索器。** 实测：两条腿共用 `index_text()`
   让语义腿只有 75.0%；拆出 `dense_text()` 后升到 86.1%。
3. **弱腿和强腿等权融合会拖后腿。** 实测：关键词单腿 91.7%、语义单腿 86.1%，
   等权融合掉到 83.3%；权重 ≤0.2 才不亏（`rag/boundary.py` 的 `FUSION_WEIGHTS`）。
"""

from rag.boundary import CORRECTNESS, FUSION_WEIGHTS, REFUSAL, CorrectnessRule, RefusalBoundary
from rag.dense import DenseBackend, NullBackend, OnnxBgeBackend, build_dense_backend
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
    "FUSION_WEIGHTS",
    "REFUSAL",
    "Chunk",
    "CorrectnessRule",
    "DenseBackend",
    "Hit",
    "KnowledgeBase",
    "LAYER_EXPLANATION",
    "LAYER_GUIDELINE",
    "LAYER_REFERENCE",
    "NullBackend",
    "OnnxBgeBackend",
    "PipelineFlags",
    "PipelineResult",
    "QueryPlan",
    "RagPipeline",
    "RefusalBoundary",
    "RetrievalCase",
    "RetrievalReport",
    "Retriever",
    "build_dense_backend",
    "build_eval_set",
    "build_pipeline",
    "build_retriever",
    "evaluate_retrieval",
    "load_knowledge",
    "rrf_fuse",
    "understand_query",
]
