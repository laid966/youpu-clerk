"""RAG 链路的各级阶段：查询理解 → 融合 → 重排 → 拒答。

**每个阶段都是纯函数**（输入输出都是数据），所以可以单独测、单独开关、单独量化。
这是"每级到底值不值"能被算出来的前提。

边界与判定口径不在这里（那些是内容，在 `rag/boundary.py`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from rag.boundary import METRIC_ALIASES
from rag.knowledge import LAYER_EXPLANATION, LAYER_GUIDELINE
from rag.retriever import Hit

__all__ = [
    "QueryPlan",
    "apply_metric_boost",
    "rrf_fuse",
    "understand_query",
]

#: 命中指标线索时给该指标的 chunk 加分（用于重排）。
#: 取值是一个**排序偏好**，不是概率，所以它只要"能稳住顺序"就够；
#: 具体大小靠 `python -m rag eval --stages` 看有没有用。
METRIC_BOOST = 0.35

#: **软路由**的优先层加权。比指标加权小——因为意图判断比指标识别更容易错，
#: 而且我们实测过：**硬路由（直接排除一层）会掉 19.4 个百分点**。
LAYER_BOOST = 0.2


@dataclass(frozen=True)
class QueryPlan:
    """查询理解的产物：这条问句在问什么、**优先**去哪一层找。"""

    query: str
    metric_code: str | None
    intent: str
    layers: tuple[str, ...]
    """**允许检索**的层。默认是全部可检索层——见下面的「硬路由」说明。"""

    priority_layer: str | None = None
    """**优先**的层（软路由）：只在重排时加权，不排除其他层。"""

    matched_terms: tuple[str, ...] = ()
    note: str = ""

    @property
    def routed(self) -> bool:
        return self.priority_layer is not None

    def describe(self) -> str:
        metric = self.metric_code or "未识别"
        layers = "+".join(self.layers) or "全部"
        priority = self.priority_layer or "无"
        return f"指标={metric} 意图={self.intent} 层={layers} 优先层={priority}"


def understand_query(
    query: str,
    metrics: Sequence = (),
    routing: Mapping[str, tuple[str, ...]] | None = None,
    aliases: Mapping[str, tuple[str, ...]] | None = None,
    hard_routing: bool = False,
) -> QueryPlan:
    """规则版查询理解：**确定性、免费、可解释**。

    做两件事：

    1. **认指标**：用户写 `ALT`、写"转氨酶"、写"谷丙"，都指同一个指标。
    2. **认意图**：问"是什么"该去 L2 指标解释层，问"怎么办/能不能吃"该去 L3 指南层。

    ## ⚠️ 硬路由是一次已知的失败（实测 -19.4 个百分点）

    第一版这里做的是**硬路由**：按关键词只查一层，把另一层整个排除。

    实测结果（36 条用例）：

       ① 只开 BM25（基线）    Recall@1 91.7%
       ② + 查询理解（硬路由）  Recall@1 72.2%   ← 掉了 19.4 个点
       ③ + 指标重排           72.2%（硬路由的错误没有机会被纠正）

    **根因**：模板问句「ALT 偏高怎么办」里同时有"偏高"（解释层）和"怎么办"（指南层），
    平局时按名字排序选中了指南层，于是**正确答案所在的解释层被整个排除了**。

    **教训**：意图判断天然会错，**错的时候不能让它造成不可挽回的损失**。
    所以默认改成**软路由**——优先层只在重排时加权，不排除任何层。
    `hard_routing=True` 保留下来复现那个实验（`rag stage_eval` 里有记录）。

    这是"每一级都要有数字"这条纪律的直接回报：
    **如果没有那张增益表，我会一直以为硬路由是个好功能。**
    """
    from rag.boundary import INTENT_ROUTING

    table = dict(routing) if routing is not None else dict(INTENT_ROUTING)
    alias_table = dict(aliases) if aliases is not None else dict(METRIC_ALIASES)

    text = query.lower()
    matched: list[str] = []

    # ---- ① 认指标：先看指标代码/缩写（精确信号），再看口语别名 ----
    metric_code: str | None = None
    for metric in metrics:
        candidates = [metric.code.lower(), metric.abbr.lower(), metric.name.lower()]
        candidates.extend(alias.lower() for alias in alias_table.get(metric.code, ()))
        for candidate in candidates:
            if candidate and candidate in text:
                metric_code = metric.code
                matched.append(candidate)
                break
        if metric_code:
            break

    # ---- ② 认意图：按关键字命中数选，平局按名字排序（保证确定性）----
    intent_hits: dict[str, list[str]] = {}
    for intent, keywords in table.items():
        hits = [word for word in keywords if word.lower() in text]
        if hits:
            intent_hits[intent] = hits

    all_layers = (LAYER_EXPLANATION, LAYER_GUIDELINE)

    if intent_hits:
        intent = sorted(intent_hits, key=lambda name: (-len(intent_hits[name]), name))[0]
        matched.extend(intent_hits[intent])
        priority = LAYER_GUIDELINE if intent == "guideline" else LAYER_EXPLANATION
        if hard_routing:
            return QueryPlan(
                query=query,
                metric_code=metric_code,
                intent=intent,
                layers=(priority,),
                priority_layer=priority,
                matched_terms=tuple(dict.fromkeys(matched)),
                note=f"硬路由：只查 {priority} 层（**实测会掉 19.4 个点，默认关闭**）",
            )
        return QueryPlan(
            query=query,
            metric_code=metric_code,
            intent=intent,
            layers=all_layers,
            priority_layer=priority,
            matched_terms=tuple(dict.fromkeys(matched)),
            note=f"软路由：两层都查，重排时优先 {priority} 层（错的代价可控）",
        )

    return QueryPlan(
        query=query,
        metric_code=metric_code,
        intent="unknown",
        layers=all_layers,
        priority_layer=None,
        matched_terms=tuple(dict.fromkeys(matched)),
        note="没有可用的意图关键字 → 全库检索，不加层偏好",
    )


def rrf_fuse(
    rankings: Sequence[Sequence[str]],
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[str, float]]:
    """RRF（Reciprocal Rank Fusion）：**按名次融合多路检索结果**。

        score(d) = Σ_r  w_r / (k + rank_r(d))

    为什么必须按名次、不能把分数加起来：
    BM25 的分数是**无界**的（可以是 0.3 也可以是 30），
    向量相似度在 [0,1] 之间。两者相加等于让其中一路随机主宰排序——
    换个语料，占主导的那一路就变了，而且没人看得出来。

    `weights` 是**每一路的权重**，默认等权。等权有一个前提：
    **两路的质量相当**。质量差很多时等权融合会把强的那一路拖下来——
    本项目实测过：BM25 单腿 91.7%、语义单腿 75.0%，等权融合后掉到 77.8%。
    所以权重必须可调，而且要**用数字调**，不能凭感觉。
    """
    if k <= 0:
        raise ValueError("k 必须为正——否则分母会退化")

    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError(f"weights 有 {len(weights)} 个，但 rankings 有 {len(rankings)} 路")

    scores: dict[str, float] = {}
    for weight, ranking in zip(weights, rankings):
        for position, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + position)

    # 分数相同时按 chunk_id 稳定排序，保证可复现
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def apply_metric_boost(
    hits: Sequence[Hit],
    plan: QueryPlan,
    boost: float = METRIC_BOOST,
    layer_boost: float = LAYER_BOOST,
) -> list[Hit]:
    """重排：**认出来的指标**和**优先层**加权，但**不排除任何东西**。

    两个加权分开放，是因为它们的可靠性不同：

    - **指标识别**靠的是"指标名/缩写/别名出现在问句里"，这是**精确信号**（boost 大一点）
    - **意图判断**靠关键词，会错（见 `understand_query` 的实测记录），
      所以它只轻推一下（boost 小一点），错了也不会造成不可挽回的损失

    这就是"软路由"：**判断错了顶多排序差一点，不会把正确答案直接删掉。**
    """
    if plan.metric_code is None and plan.priority_layer is None:
        return list(hits)

    preferred_chunk = f"kb://metric/{plan.metric_code}" if plan.metric_code else None

    def weight(hit: Hit) -> float:
        total = hit.score
        if preferred_chunk and hit.chunk_id == preferred_chunk:
            total += boost
        if plan.priority_layer and hit.layer == plan.priority_layer:
            total += layer_boost
        return total

    return sorted(hits, key=lambda hit: (-weight(hit), hit.chunk_id))
