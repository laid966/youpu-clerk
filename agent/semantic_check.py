"""语义检查：用提示词判断"这段解释有没有越界"。

## 顺序是有讲究的：先词表，再模型

1. **护栏（确定性）**：命中就直接判越界，不问模型。快、稳、能解释。
2. **模型（语义）**：只处理词表没抓到的那些——改写过的诊断口吻与治疗建议。

反过来（先模型再词表）会把便宜的判断也交给模型，既慢又贵还不稳。

## 一个必须坚持的原则：解析失败不等于"没有越界"

模型有时会不按格式输出。这时候**必须报错**，绝不能悄悄当成"没问题"——
那等于把一次失败伪装成一次正确的判断，是审计系统里最危险的失败模式。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from agent.guardrails import apply_guardrails
from agent.judge import Judge

__all__ = ["CheckOutcome", "SemanticFinding", "check_text", "parse_verdict"]

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


@dataclass(frozen=True)
class SemanticFinding:
    target: str
    category: str
    evidence: str
    decided_by: str  # "guardrail" | "model"

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "category": self.category,
            "evidence": self.evidence,
            "decided_by": self.decided_by,
        }


@dataclass(frozen=True)
class CheckOutcome:
    finding: SemanticFinding | None
    error: str | None = None
    raw_response: str = ""


def parse_verdict(raw: str) -> tuple[bool, str, str]:
    """从模型输出里解析判定。容错处理代码块与前后废话，但**不接受解析失败**。"""
    text = _FENCE.sub("", raw.strip())
    match = _JSON_BLOCK.search(text)
    if match is None:
        raise ValueError(f"模型输出里找不到 JSON：{raw[:120]!r}")

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型输出的 JSON 无法解析：{match.group(0)[:120]!r}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"模型输出的 JSON 不是对象：{payload!r}")

    violation = bool(payload.get("violation", False))
    category = str(payload.get("category") or ("unspecified" if violation else "none"))
    evidence = str(payload.get("evidence") or "")
    return violation, category, evidence


def check_text(text: str, target: str, prompt: str, judge: Judge) -> CheckOutcome:
    """检查一段解释文本。

    先跑护栏；没命中再问模型。模型输出解析失败时返回 error，**不返回"没问题"**。
    """
    for hit in apply_guardrails(text):
        return CheckOutcome(
            finding=SemanticFinding(
                target=target,
                category=hit.category,
                evidence=hit.pattern,
                decided_by="guardrail",
            ),
            raw_response="",
        )

    filled = prompt.replace("{text}", text)
    try:
        raw = judge.complete(filled)
    except Exception as exc:  # noqa: BLE001 — 调用失败必须显式暴露
        return CheckOutcome(finding=None, error=f"调用模型失败：{type(exc).__name__}: {exc}")

    try:
        violation, category, evidence = parse_verdict(raw)
    except ValueError as exc:
        return CheckOutcome(finding=None, error=str(exc), raw_response=raw)

    if not violation:
        return CheckOutcome(finding=None, raw_response=raw)

    return CheckOutcome(
        finding=SemanticFinding(
            target=target, category=category, evidence=evidence, decided_by="model"
        ),
        raw_response=raw,
    )
