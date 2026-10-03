"""审计图的状态。

刻意只放**数据**，不放策略与依赖：

- 策略（`AuditPolicy`）、模型（`Judge`）、指标清单通过图的闭包传进去，
  而不是塞在状态里。这样状态可以干净地被 checkpointer 序列化，
  也方便测试时换一套策略重跑同一份状态。
- 所有值都是可 JSON 化的基本类型（dict / list / str / int / bool）。
"""

from __future__ import annotations

from typing import Any, TypedDict

__all__ = ["AuditState"]


class AuditState(TypedDict, total=False):
    # ---- 输入 ----
    artifact: dict[str, Any]
    report_values: dict[str, float]
    sex: str
    age: int

    # ---- 计划 ----
    planned_codes: list[str]

    # ---- 检查结果 ----
    deterministic: list[dict[str, Any]]
    semantic: list[dict[str, Any]]
    rejected: list[dict[str, Any]]

    # ---- 裁决 ----
    accepted: list[dict[str, Any]]
    escalated: bool
    escalation_reasons: list[str]

    # ---- 收尾 ----
    model_calls: int
    notes: list[str]
    audit: dict[str, Any]
