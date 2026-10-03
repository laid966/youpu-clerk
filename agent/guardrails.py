"""★ 这是你的文件 ★ 确定性护栏规则表。

放在模型前面的第一道闸。凡是命中这里的，**不必问模型**就直接判越界。
理由：护栏要快、要稳、要能解释，而这三点模型都不占。

## 分工要清楚

- **词表（这里）**：抓写法露骨的越界，如"诊断为""建议服用""每日三次"。
- **语义检查（`agent/prompts.py`）**：抓改写过的越界，如
  「这个结果通常提示肝脏已经出现了实质性的损伤」。

实测：我们注入的改写型越界，词表**一条都抓不到**（召回 0%）。
所以这个文件的目的不是"覆盖所有情况"，而是"把明显的那批便宜地挡掉"，
让模型只处理真正难的。

## 你要做的

1. 补充 `EXTRA_PATTERNS`（正则）：你见过的、词表漏掉的露骨写法。
2. 给每条规则写清 `note`：它防的是什么错。没有 note 的规则在评审时不予接受。
3. 每条规则都配一个测试用例（`tests/test_agent.py` 里已有模板）。

⚠️ 如果你觉得某个**词**该进基础词表，改 `audit/artifact.py` 里的 `SAFETY_TERMS`（只有那一处是权威来源）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from audit.artifact import SAFETY_TERMS

__all__ = ["GUARDRAIL_RULES", "GuardrailHit", "apply_guardrails", "categories"]


@dataclass(frozen=True)
class GuardrailRule:
    name: str
    category: str  # diagnosis | treatment | dosage | other
    patterns: tuple[str, ...]
    note: str
    is_regex: bool = False

    def matches(self, text: str) -> list[str]:
        hits: list[str] = []
        for pattern in self.patterns:
            if self.is_regex:
                if re.search(pattern, text):
                    hits.append(pattern)
            elif pattern in text:
                hits.append(pattern)
        return hits


@dataclass(frozen=True)
class GuardrailHit:
    rule: str
    category: str
    pattern: str
    note: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "category": self.category,
            "pattern": self.pattern,
            "note": self.note,
        }


# --------------------------------------------------------------------------- #
# 基础规则：按类别拆分基础词表。这些是"露骨写法"，命中即判越界。
# --------------------------------------------------------------------------- #

_DIAGNOSIS_TERMS = tuple(
    term for term in SAFETY_TERMS if term in {"诊断为", "确诊", "考虑为", "提示患有"}
)
_TREATMENT_TERMS = tuple(
    term for term in SAFETY_TERMS if term in {"建议服用", "建议口服", "护肝片"}
)
_DOSAGE_TERMS = tuple(
    term for term in SAFETY_TERMS if term in {"每日", "剂量", "片剂", "胶囊"}
)

GUARDRAIL_RULES: tuple[GuardrailRule, ...] = (
    GuardrailRule(
        name="G-DIAGNOSIS-KEYWORD",
        category="diagnosis",
        patterns=_DIAGNOSIS_TERMS,
        note="露骨的诊断口吻。改写型不由这里负责，交给语义检查。",
    ),
    GuardrailRule(
        name="G-TREATMENT-KEYWORD",
        category="treatment",
        patterns=_TREATMENT_TERMS,
        note="直接推荐用药。本工具不允许给用药建议。",
    ),
    GuardrailRule(
        name="G-DOSAGE-KEYWORD",
        category="dosage",
        patterns=_DOSAGE_TERMS,
        note="出现用法用量，说明已经越到治疗方案层面。",
    ),
    # ========================================================================
    # ★ 在这里往下加你的规则。示例（当前是空的，等你去填）：
    #
    # GuardrailRule(
    #     name="G-CERTAINTY-PHRASE",
    #     category="diagnosis",
    #     patterns=(r"基本可以确定", r"已经属于.{0,6}(范围|阶段)", r"可以认定为"),
    #     note="把不确定的检验结果说成确定结论，属于诊断口吻的常见改写。",
    #     is_regex=True,
    # ),
    # ========================================================================
)


# 由规则表推导出的"扩展词/正则"，方便别处直接复用
def all_patterns() -> Iterable[str]:
    for rule in GUARDRAIL_RULES:
        yield from rule.patterns


def categories() -> tuple[str, ...]:
    return tuple(sorted({rule.category for rule in GUARDRAIL_RULES}))


def apply_guardrails(text: str) -> list[GuardrailHit]:
    """跑全部护栏规则。返回命中列表（可能为空）。"""
    hits: list[GuardrailHit] = []
    for rule in GUARDRAIL_RULES:
        for pattern in rule.matches(text):
            hits.append(
                GuardrailHit(
                    rule=rule.name,
                    category=rule.category,
                    pattern=pattern,
                    note=rule.note,
                )
            )
    return hits
