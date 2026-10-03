"""审计图的装配。

    plan ─► inspect_deterministic ─► inspect_semantic ─► reflect ─► decide
                                                                      │
                                          escalated? ──是──► human_review ┘
                                                      └─否──► finalize ─► END

两条设计约束：
1. **确定性检查永远在语义检查之前**。能用程序判的先判完，模型只处理剩下的。
   顺序反了会把便宜、稳定、可解释的部分也交给模型。
2. **`decide` 之后有条件分支**。是否升级人工不由模型决定，由策略决定——
   所以它是图上的一个节点，而不是提示词里的一句话。
"""

from __future__ import annotations

from typing import Any, Sequence

from langgraph.graph import END, StateGraph

from agent.judge import Judge
from agent.nodes import AuditNodes
from agent.policy import AuditPolicy
from agent.state import AuditState
from audit.pipeline import Metric

__all__ = ["build_audit_graph"]


def build_audit_graph(
    policy: AuditPolicy,
    judge: Judge,
    metrics: Sequence[Metric],
    prompt: str | None = None,
    checkpointer: Any = None,
):
    """装配并编译审计图。返回 (编译后的图, 节点对象)。

    返回节点对象是为了方便测试：可以单独调某个节点，不必跑整张图。
    """
    nodes = AuditNodes(policy=policy, judge=judge, metrics=metrics, prompt=prompt)

    graph: StateGraph = StateGraph(AuditState)
    graph.add_node("plan", nodes.plan)
    graph.add_node("inspect_deterministic", nodes.inspect_deterministic)
    graph.add_node("inspect_semantic", nodes.inspect_semantic)
    graph.add_node("reflect", nodes.reflect)
    graph.add_node("decide", nodes.decide)
    graph.add_node("human_review", nodes.human_review)
    graph.add_node("finalize", nodes.finalize)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "inspect_deterministic")
    graph.add_edge("inspect_deterministic", "inspect_semantic")
    graph.add_edge("inspect_semantic", "reflect")
    graph.add_edge("reflect", "decide")
    graph.add_conditional_edges(
        "decide",
        lambda state: "human_review" if state.get("escalated") else "finalize",
        {"human_review": "human_review", "finalize": "finalize"},
    )
    graph.add_edge("human_review", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer), nodes
