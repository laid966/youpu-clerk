"""评测语义检查（也就是评测**你的提示词**）。

## 评测集怎么来

不重新造数据，直接从缺陷注入基准里取：

| 角色 | 取哪些 | 意义 |
|---|---|---|
| **正例** | 被注入 `safety_paraphrase` 的那条指标的解释 | 改写型越界，词表抓不到，看你能不能补上 |
| **负例** | 干净样本里的指标解释 | 正常文本，看你会不会误报 |

**不取全部指标**：一份产物有 8 个指标，200 份就是 1600 次调用，没必要。
只取定向的那几十条，既省钱又聚焦——这也是"定向评测"而不是"全量评测"的取舍。

## 数字怎么读

- **召回**：改写型越界抓住了多少。词表在这上面是 0%，这是你唯一能提升的地方。
- **误报**：正常解释被冤枉了多少。误报一多，审计器就没人用——这是死穴。
- **错误**：模型输出解析失败的次数。**单独统计、单独报告**，
  绝不允许被算成"判定为无越界"。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Mapping, Sequence

from agent.judge import Judge
from agent.semantic_check import check_text
from audit.inject import InjectedCase
from audit.pipeline import Metric

__all__ = ["SemanticCase", "SemanticEvalReport", "build_semantic_cases", "evaluate_semantic"]

POSITIVE_KINDS = ("safety_paraphrase",)


@dataclass(frozen=True)
class SemanticCase:
    case_id: str
    target: str
    text: str
    is_positive: bool
    note: str


@dataclass(frozen=True)
class SemanticEvalReport:
    prompt_version: str
    positives: int
    caught: int
    negatives: int
    false_positives: int
    errors: int
    error_details: tuple[str, ...]
    missed: tuple[SemanticCase, ...]
    false_positive_details: tuple[str, ...]
    cache_hits: int
    cache_misses: int

    @property
    def recall(self) -> float:
        return self.caught / self.positives if self.positives else 0.0

    @property
    def false_positive_rate(self) -> float:
        return self.false_positives / self.negatives if self.negatives else 0.0

    def to_markdown(self) -> str:
        lines = [
            f"# 语义检查评测报告 · 提示词 `{self.prompt_version}`",
            "",
            "> 只评模型负责的那部分：**改写型安全越界**（不含禁用词的诊断/治疗结论）。",
            "> 确定性词表在这类缺陷上的召回是 **0%**，所以这里的每一点提升都是净增益。",
            "",
            "## 总览",
            "",
            "| 指标 | 数值 |",
            "|---|---|",
            f"| 正例（改写型越界） | {self.positives} |",
            f"| 抓住 | **{self.caught}** |",
            f"| **召回率** | **{self.recall:.1%}** |",
            f"| 负例（正常解释） | {self.negatives} |",
            f"| 误报 | **{self.false_positives}** |",
            f"| **误报率** | **{self.false_positive_rate:.1%}** |",
            f"| 解析失败/调用失败 | **{self.errors}**（单独统计，不算作「无越界」） |",
            f"| 缓存命中 / 未命中 | {self.cache_hits} / {self.cache_misses} |",
            "",
        ]

        lines.append("## 漏掉的越界（这些是你可以改进的地方）")
        lines.append("")
        if self.missed:
            lines.append("| 编号 | 指标 | 文本片段 |")
            lines.append("|---|---|---|")
            for case in self.missed:
                snippet = case.text[-60:].replace("\n", " ")
                lines.append(f"| {case.case_id} | `{case.target}` | …{snippet} |")
        else:
            lines.append("- 无（全部抓住）")
        lines.append("")

        lines.append("## 误报（冤枉的正常解释）")
        lines.append("")
        if self.false_positive_details:
            for item in self.false_positive_details:
                lines.append(f"- {item}")
        else:
            lines.append("- 无")
        lines.append("")

        if self.error_details:
            lines.append("## 错误明细")
            lines.append("")
            for item in self.error_details:
                lines.append(f"- {item}")
            lines.append("")

        return "\n".join(lines)


def build_semantic_cases(
    cases: Sequence[InjectedCase],
    positives: int = 24,
    negatives: int = 20,
    seed: int = 20261003,
    hard_negative_share: float = 0.6,
) -> tuple[SemanticCase, ...]:
    """从注入基准里挑出定向的评测子集。

    **负例要故意加难度。** 第一版负例全是温和的科普句，提示词轻松拿到 0% 误报——
    那个 0 是假的。真实审计里最难的不是抓明显的诊断，而是
    **不冤枉那些听起来很医学、其实只是科普与就医引导的句子**。
    所以这里给一部分负例补上这类"合法但诱人"的文本（文本来自 `audit.inject` 的固定清单）。
    """
    from dataclasses import replace

    from audit.inject import tempting_but_legit_phrases

    rng = random.Random(seed + 4441)

    positive_cases: list[SemanticCase] = []
    for case in cases:
        for defect in case.defects:
            if defect.kind not in POSITIVE_KINDS:
                continue
            item = case.artifact.item(defect.target)
            positive_cases.append(
                SemanticCase(
                    case_id=f"{case.case_id}/{defect.defect_id}",
                    target=defect.target,
                    text=item.explanation,
                    is_positive=True,
                    note=defect.observed,
                )
            )

    negative_pool: list[SemanticCase] = []
    for case in cases:
        if not case.clean:
            continue
        for item in case.artifact.items:
            negative_pool.append(
                SemanticCase(
                    case_id=f"{case.case_id}/{item.code}",
                    target=item.code,
                    text=item.explanation,
                    is_positive=False,
                    note="干净样本，不该被报",
                )
            )

    rng.shuffle(positive_cases)
    rng.shuffle(negative_pool)

    phrases = tempting_but_legit_phrases()
    hard_count = int(negatives * hard_negative_share)
    chosen_negatives: list[SemanticCase] = []
    for index, case in enumerate(negative_pool[:negatives]):
        if index < hard_count:
            chosen_negatives.append(
                replace(
                    case,
                    text=case.text + phrases[index % len(phrases)],
                    note="高难度负例：含合法的医学化表述，不该被报",
                )
            )
        else:
            chosen_negatives.append(case)

    return tuple(positive_cases[:positives]) + tuple(chosen_negatives)


def evaluate_semantic(
    semantic_cases: Sequence[SemanticCase],
    prompt: str,
    judge: Judge,
    prompt_version: str,
) -> SemanticEvalReport:
    caught = false_positives = errors = 0
    positives = negatives = 0
    missed: list[SemanticCase] = []
    fp_details: list[str] = []
    error_details: list[str] = []

    for case in semantic_cases:
        outcome = check_text(case.text, case.target, prompt, judge)

        if outcome.error:
            errors += 1
            error_details.append(f"{case.case_id}（{case.target}）：{outcome.error[:120]}")

        if case.is_positive:
            positives += 1
            if outcome.finding is not None:
                caught += 1
            else:
                missed.append(case)
        else:
            negatives += 1
            if outcome.finding is not None:
                false_positives += 1
                fp_details.append(
                    f"{case.case_id}（{case.target}）：{outcome.finding.evidence[:80]}"
                )

    return SemanticEvalReport(
        prompt_version=prompt_version,
        positives=positives,
        caught=caught,
        negatives=negatives,
        false_positives=false_positives,
        errors=errors,
        error_details=tuple(error_details),
        missed=tuple(missed),
        false_positive_details=tuple(fp_details),
        cache_hits=int(getattr(judge, "hits", 0)),
        cache_misses=int(getattr(judge, "misses", 0)),
    )
