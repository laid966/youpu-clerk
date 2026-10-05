"""★ 这是你的文件 ★ 确定性护栏规则表。

放在模型前面的第一道闸。凡是命中这里的，**不必问模型**就直接判越界。
理由：护栏要快、要稳、要能解释，而这三点模型都不占。

## 分工要清楚

- **词表（这里）**：抓写法露骨的越界，如"诊断为""建议服用""每日三次"。
- **语义检查（`agent/prompts.py`）**：抓改写过的越界，如
  「这个结果通常提示肝脏已经出现了实质性的损伤」。

实测：我们注入的改写型越界，**最原始那 10 句**词表一条都抓不到（召回 0%）。
所以这个文件的目的不是"覆盖所有情况"，而是"把明显的那批便宜地挡掉"，
让模型只处理真正难的。

## 你要做的（两步，别跳过第二步）

1. 在文件末尾的 **`EXTRA_PATTERNS`** 里加规则。
2. **验证它真的命中了**：

       .\\.venv\\Scripts\\python.exe -m agent check "你想试的文本"

   输出里会列出**哪条规则、哪个词**命中。**没命中就是没生效**，不要靠感觉。

## ⚠️ 两个真实踩过的坑（都在这个文件里）

**坑一：用"从 `SAFETY_TERMS` 里筛"的写法加新词，筛出来永远是空的。**

```python
# ❌ 错：新词当然不在已有词表里，筛出来是 ()
_CONCLUSION_TERMS = tuple(t for t in SAFETY_TERMS if t in {"基本可以确定", "已经属于"})

# ✅ 对：新词直接写进去
patterns=("基本可以确定", "已经属于")
```

这种写法会**静默失效**——规则看起来加上了，实际永远匹配不到。
所以现在 `GuardrailRule` 会在 `patterns` 为空时**直接报错**，不让它悄悄躺着。

**坑二：`category` 出现新值时，策略层认不出来。**
护栏给出的类别如果不在 `agent/policy.py` 的 `KNOWN_CATEGORIES` 里，
端到端审计会按"未知类目"走 fail-safe —— **这类结论会全部升级人工**。
那通常是**对的行为**（该人工看），但要**知道它是有意还是意外**。
参考 `docs/10-你的任务.md` 的 T8。

## 如果你觉得某个**词**该进基础词表

改 `audit/artifact.py` 里的 `SAFETY_TERMS`——**只有那一处是权威来源**。
但注意：`SAFETY_TERMS` 里的词不能出现在注入基准的改写句里，
有测试逐句检查（`tests/test_inject.py`），改了就要跑全量测试。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from audit.artifact import SAFETY_TERMS

__all__ = [
    "EXTRA_PATTERNS",
    "GUARDRAIL_RULES",
    "GuardrailHit",
    "GuardrailRule",
    "apply_guardrails",
    "all_patterns",
    "categories",
]


@dataclass(frozen=True)
class GuardrailRule:
    name: str
    category: str  # diagnosis | treatment | dosage | conclusion | other
    patterns: tuple[str, ...]
    note: str
    is_regex: bool = False

    def __post_init__(self) -> None:
        """**空规则直接报错，不让它静默躺着。**

        真实事故：`patterns` 用"从 SAFETY_TERMS 里筛新词"的写法，筛出来是空元组。
        规则看着加上了，实际永远匹配不到——改完跑命令"没有变化"，查半天查不出来。
        静默失效比报错贵得多，所以在**构造时**就炸掉。
        """
        if not self.patterns:
            raise ValueError(
                f"护栏规则 {self.name} 的 patterns 是空的——它永远匹配不到任何东西。\n"
                "最常见的原因：用「从 SAFETY_TERMS 里筛」的写法加**新词**（新词当然筛不出来）。\n"
                '改法：把词直接写进去，例如 patterns=("基本可以确定", "已经属于")。'
            )
        if not self.note.strip():
            raise ValueError(f"护栏规则 {self.name} 必须写 note：它防的是什么错？")
        duplicates = [p for p in self.patterns if self.patterns.count(p) > 1]
        if duplicates:
            raise ValueError(f"护栏规则 {self.name} 有重复的 pattern：{sorted(set(duplicates))}")

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
# 基础规则（别动这部分）：按类别拆分基础词表。这些是"露骨写法"，命中即判越界。
#
# ⚠️ 注意这里的 `_X_TERMS` 都是**从 SAFETY_TERMS 里筛**的，这是刻意的：
# 它们只负责覆盖基础词表，新词请写进下面的 EXTRA_PATTERNS。
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

_BASE_RULES: tuple[GuardrailRule, ...] = (
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
)


# ============================================================================
# ★★★ 你的扩展位：往下加你的规则 ★★★
#
# 加完**不用改别的地方** —— `GUARDRAIL_RULES` 会自动带上这里的内容。
#
# 每种写法各一个例子：
#
#   字面词（最简单，也最不容易出错）：
#     GuardrailRule(
#         name="G-CONCLUSION-KEYWORD",
#         category="conclusion",
#         patterns=("基本可以确定", "已经属于", "可以认定为", "不用就医"),
#         note="结论性表达：替医生给病情定性，或劝阻就医。",
#     ),
#
#   正则（需要"中间隔几个字也算"时用）：
#     GuardrailRule(
#         name="G-CERTAINTY-PATTERN",
#         category="conclusion",
#         patterns=(r"已经属于.{0,6}(范围|阶段)",),
#         note="把不确定的结果说成确定结论。",
#         is_regex=True,
#     ),
#
# 加完**务必验证**：python -m agent check "你的一句话"
# ============================================================================

EXTRA_PATTERNS: tuple[GuardrailRule, ...] = (
    GuardrailRule(
        name="G-CONCLUSION-KEYWORD",
        category="conclusion",
        patterns=(
            "基本可以确定",
            "已经属于",
            "可以认定为",
            "不用就医",
        ),
        note=(
            "结论性表达：替医生给病情定性（基本可以确定 / 已经属于 / 可以认定为），"
            "以及劝阻就医（不用就医）。本工具只做科普与就医准备，这两类都不允许。"
        ),
    ),
)


# 由基础规则 + 你的扩展位拼成完整规则表
GUARDRAIL_RULES: tuple[GuardrailRule, ...] = _BASE_RULES + EXTRA_PATTERNS


def all_patterns() -> Iterable[str]:
    for rule in GUARDRAIL_RULES:
        yield from rule.patterns


def categories() -> tuple[str, ...]:
    return tuple(sorted({rule.category for rule in GUARDRAIL_RULES}))


def apply_guardrails(text: str) -> list[GuardrailHit]:
    """跑全部护栏规则。返回命中列表（可能为空）。

    `hit.pattern` 就是**命中的那个词/正则** —— `python -m agent check` 会把它打出来，
    这是你验证"规则到底生效没有"的唯一依据。
    """
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
