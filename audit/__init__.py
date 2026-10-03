"""auditkit：判定类 AI 输出的差分审计器。

分层（与 engine 保持同样的纪律）：

    engine/   确定性内核：规则、判定、自检、用例生成   ← 不含模型
    audit/    审计系统：判决流水线、缺陷注入、检查器、裁决、评测
    rag/      知识库与检索
    agent/    LangGraph 编排、提示词、护栏

本包当前只包含 A1 阶段的内容：判决流水线与判决样本生成。
"""

from audit.pipeline import (
    JudgedReport,
    Metric,
    Report,
    judge_metric,
    judge_report,
    known_citations,
    load_metrics,
    severity_rank,
)

__all__ = [
    "JudgedReport",
    "Metric",
    "Report",
    "judge_metric",
    "judge_report",
    "known_citations",
    "load_metrics",
    "severity_rank",
]
