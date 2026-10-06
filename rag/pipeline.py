"""RAG 链路：把一条 BM25 检索变成**多级、可开关、每级可单独量化**的链路。

## 为什么不是"加个向量就完事"

这个项目的知识库只有 **15 条 chunk**，BM25 已经 Recall@1 93.5%。
在这个规模上堆向量索引，数学上不可能有明显收益——那是工程表演。

**真正的缺口是"链路不完整"和"检索没接进审计"**，所以这条链路做三件事：

1. **把检索拆成可开关的级**（查询理解 / 召回 / 重排 / 拒答），
   每一级都能用同一套评测集单独量出增益 —— 见 `rag/stage_eval.py`
2. **把"该不该回答"变成一个显式判断**（`rag/boundary.py` 由你定边界），
   而不是让系统永远硬答
3. **留出向量那一级的接口**（`StageFlags.dense`），但要先有数字证明它值

## `search()` 为什么不应用拒答

因为 `search()` 是**检索质量**的口径：它回答"该找到的找到了没有"。
拒答是**回答策略**：它回答"该不该开口"。两者是不同的问题，混在一起
两个指标都会变得说不清。

所以：`search()` 只做检索；**拒答只在 `explain()` 里生效**。
拒答有自己的双向指标（正确率 / 误伤率），见 `python -m rag eval --refusal`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from rag.bm25 import BM25Index, build_index
from rag.boundary import CORRECTNESS, REFUSAL, CorrectnessRule, RefusalBoundary
from rag.knowledge import RETRIEVABLE_LAYERS, KnowledgeBase, load_knowledge
from rag.retriever import Hit
from rag.stages import QueryPlan, apply_metric_boost, understand_query

__all__ = [
    "PipelineFlags",
    "PipelineResult",
    "RagPipeline",
    "build_pipeline",
]


@dataclass(frozen=True)
class PipelineFlags:
    """链路里每一级的开关。**默认全部打开**（能用得上的就用上，再逐级量增益）。"""

    query_understanding: bool = True
    recall: bool = True
    """召回级：关掉它链路就什么都不返回了。留这个开关是为了让评测能诚实地报"0 级基线"。"""

    metric_rerank: bool = True
    refusal: bool = True
    """只影响 `explain()`，不影响 `search()`——见模块开头的说明。"""

    dense: bool = False
    """向量那一级。**目前还没有实现**（`rag/dense.py` 是 P1 的事）。

    留这个开关是为了让"要不要上向量"有据可依：
    先看 `rag eval --stages` 里查询理解与重排把 Recall@1 顶到多少，
    再决定向量还有没有空间。
    """

    hard_layer_routing: bool = False
    """意图判断用**硬路由**（只查一层）还是**软路由**（加权，不排除）。

    ⚠️ **默认 False，而且必须保持 False。** 实测：硬路由让 Recall@1
    从 91.7% 掉到 **72.2%（-19.4 个点）**——因为意图判断会错，
    而硬路由**在错的时候造成不可挽回的损失**（把正确答案整个排除）。

    这个开关保留下来是为了**复现那个实验**（`rag eval --stages` 里有一行反例），
    不是为了启用它。**一个能被复现的失败，比一句"我们试过了"值钱。**
    """

    def __post_init__(self) -> None:
        if not self.recall:
            raise ValueError(
                "recall=False 会让链路什么都不返回。"
                "要表达「只用基线」，请用 flags 里其他的开关，不要关召回。"
            )
        if self.dense:
            raise NotImplementedError(
                "向量级还没实现（P1）。要启用它需要先装 onnxruntime + 下载本地模型，"
                "见 docs/20-RAG链路.md 的说明。"
            )

    @property
    def label(self) -> str:
        parts = ["BM25"]
        if self.dense:
            parts.extend(["Dense", "RRF"])
        if self.query_understanding:
            parts.append("硬路由（反例）" if self.hard_layer_routing else "软路由")
        if self.metric_rerank:
            parts.append("指标重排")
        return "+".join(parts)


@dataclass(frozen=True)
class PipelineResult:
    """`explain()` 的产物：不只是结果，还有**为什么是这个结果**。"""

    query: str
    plan: QueryPlan
    hits: tuple[Hit, ...]
    refused: bool
    reason: str

    @property
    def answer(self) -> str:
        """受约束的回答：要么给出依据，要么明确拒答。**不许硬答。**"""
        if self.refused:
            return REFUSAL.refuse_message
        return "；".join(f"{hit.title}（{hit.chunk_id}）" for hit in self.hits)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "plan": {
                "metric_code": self.plan.metric_code,
                "intent": self.plan.intent,
                "layers": list(self.plan.layers),
                "matched_terms": list(self.plan.matched_terms),
            },
            "refused": self.refused,
            "reason": self.reason,
            "hits": [hit.to_dict() for hit in self.hits],
        }


class RagPipeline:
    """多级 RAG 链路。

    **`search()` 与 `Retriever.search()` 同签名**，所以现有的
    `evaluate_retrieval(pipeline, cases)` 一行都不用改就能评测新链路——
    这是整条链路能被"逐级量化"的地基。
    """

    def __init__(
        self,
        knowledge: KnowledgeBase,
        index: BM25Index,
        flags: PipelineFlags | None = None,
        boundary: RefusalBoundary | None = None,
        correctness: CorrectnessRule | None = None,
        metrics: Sequence = (),
    ) -> None:
        self.knowledge = knowledge
        self.index = index
        self.flags = flags or PipelineFlags()
        self.boundary = boundary or REFUSAL
        self.correctness = correctness or CORRECTNESS
        self.metrics = tuple(metrics)

    # ------------------------------------------------------------------ #
    # 兼容接口：现有评测直接能用
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return self.flags.label

    def search(
        self, query: str, top_k: int = 5, layers: tuple[str, ...] | None = None
    ) -> list[Hit]:
        """检索。**不应用拒答**（检索质量与回答策略是两件事，见模块开头）。"""
        plan = self.plan(query)

        wanted = layers if layers is not None else plan.layers
        allowed = {chunk.chunk_id for chunk in self.knowledge.layers(*wanted)}

        hits: list[Hit] = []
        for scored in self.index.search(query, top_k=max(top_k, len(allowed)), allowed_ids=allowed):
            chunk = self.knowledge.by_id(scored.doc_id)
            if chunk is None:  # pragma: no cover — 索引与知识库同源
                continue
            hits.append(
                Hit(
                    chunk_id=chunk.chunk_id,
                    layer=chunk.layer,
                    title=chunk.title,
                    text=chunk.text,
                    score=scored.score,
                )
            )

        if self.flags.metric_rerank:
            hits = apply_metric_boost(hits, plan)

        return hits[:top_k]

    # ------------------------------------------------------------------ #
    # 链路自己的接口
    # ------------------------------------------------------------------ #

    def plan(self, query: str) -> QueryPlan:
        """查询理解（或退化成"全库搜"）。"""
        if not self.flags.query_understanding:
            return QueryPlan(
                query=query,
                metric_code=None,
                intent="disabled",
                layers=tuple(RETRIEVABLE_LAYERS),
                note="查询理解已关闭 → 全库检索（这是基线）",
            )
        return understand_query(
            query, self.metrics, hard_routing=self.flags.hard_layer_routing
        )

    def explain(self, query: str, top_k: int = 5) -> PipelineResult:
        """**带拒答判断**的检索：回答"该不该开口"以及"依据是什么"。"""
        hits = self.search(query, top_k=top_k)
        plan = self.plan(query)

        if not self.flags.refusal:
            return PipelineResult(
                query=query, plan=plan, hits=tuple(hits), refused=False, reason="拒答判断已关闭"
            )

        if self.boundary.should_refuse([hit.score for hit in hits]):
            top = hits[0].score if hits else 0.0
            return PipelineResult(
                query=query,
                plan=plan,
                hits=(),
                refused=True,
                reason=(
                    f"最高检索分 {top:.3f} < 阈值 {self.boundary.min_top_score:.3f}"
                    if hits
                    else "一条都没命中"
                ),
            )

        return PipelineResult(
            query=query,
            plan=plan,
            hits=tuple(hits),
            refused=False,
            reason=f"最高检索分 {hits[0].score:.3f} ≥ 阈值",
        )

    def describe(self) -> str:
        lines = [
            f"链路：**{self.name}**",
            "",
            "| 级 | 状态 |",
            "|---|---|",
            f"| 查询理解 | {'开' if self.flags.query_understanding else '关'}"
            f"{'（**硬路由**，仅用于复现实验）' if self.flags.hard_layer_routing else '（软路由）' if self.flags.query_understanding else ''} |",
            f"| BM25 召回 | 开 |",
            f"| 向量召回 | {'开' if self.flags.dense else '关（未实现，P1）'} |",
            f"| 指标重排 | {'开' if self.flags.metric_rerank else '关'} |",
            f"| 拒答判断 | {'开' if self.flags.refusal else '关'}（只影响 explain，不影响 search）|",
            "",
            f"判定口径：{self.correctness.label}",
            f"拒答阈值：最高分 < {self.boundary.min_top_score}",
        ]
        return "\n".join(lines)


def build_pipeline(
    knowledge: KnowledgeBase | None = None,
    flags: PipelineFlags | None = None,
    boundary: RefusalBoundary | None = None,
    correctness: CorrectnessRule | None = None,
    metrics: Sequence = (),
) -> RagPipeline:
    if knowledge is None:
        knowledge = load_knowledge()
    if not metrics:
        from audit.pipeline import load_metrics  # 延迟导入：避免包之间互相牵扯

        metrics = load_metrics()
    return RagPipeline(
        knowledge=knowledge,
        index=build_index(knowledge.documents()),
        flags=flags,
        boundary=boundary,
        correctness=correctness,
        metrics=metrics,
    )
