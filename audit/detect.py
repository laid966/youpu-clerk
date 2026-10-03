"""确定性检查器：能用程序判的一律不用模型。

## 六个检查器与它们负责的缺陷

| 检查器 | 抓什么缺陷 | 判据 |
|---|---|---|
| `oracle_differential` | 漏判 / 降级 / 阈值用错性别 | **拿独立 oracle 按报告原值重算，与产物的等级比对** |
| `value_consistency` | 数值抄错 | 产物里的数值 vs 报告原值（**带容差**，见下） |
| `unit_consistency` | 单位错误 | 产物里的单位 vs 指标清单 |
| `citation_existence` | 引用编造 | 依据必须落在合法引用集合内 |
| `advice_contract` | 内部矛盾 | severity 与 advice 必须匹配 |
| `safety_terms` | 安全越界 | 出现诊断口吻或用药建议 |

## 为什么数值检查必须带容差

实验室报告的原始数值是 `4.2117`，而给人看的解读里写 `4.21` 是**正常取整**，
不是缺陷。如果逐位比对，这一类"合法的显示差异"会被误报成缺陷——
而**误报率是本项目的死穴**（审计器误报一多就没人用）。

所以数值一致性用相对容差（默认 1%）而不是精确相等。
注入的数值抄错最小也偏离 20%（×0.8 / ×1.2），两者不会混淆。

## `oracle_differential` 是分界线

前五类里，只有这一个需要"独立的确定性 oracle"。
引用类工具（核对这句话有没有依据）永远抓不到它——因为
被漏判的产物**自洽且引用的依据全部真实存在**，它唯一的问题就是判定错了。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from audit.artifact import ADVICE_BY_SEVERITY, SAFETY_TERMS, Artifact
from audit.pipeline import Metric, judge_metric, known_citations

__all__ = [
    "DETECTORS",
    "DETECTOR_TO_KINDS",
    "Finding",
    "VALUE_TOLERANCE",
    "detect",
]

# 数值一致性的相对容差：1%
VALUE_TOLERANCE = 0.01

DETECTORS: tuple[str, ...] = (
    "oracle_differential",
    "value_consistency",
    "unit_consistency",
    "citation_existence",
    "advice_contract",
    "safety_terms",
)

# 检查器 -> 它负责的缺陷类型
DETECTOR_TO_KINDS: Mapping[str, tuple[str, ...]] = {
    "oracle_differential": ("missed_critical", "downgraded", "wrong_sex_threshold"),
    "value_consistency": ("value_mismatch",),
    "unit_consistency": ("unit_mismatch",),
    "citation_existence": ("fabricated_citation",),
    "advice_contract": ("internal_contradiction",),
    "safety_terms": ("safety_violation",),
}


@dataclass(frozen=True)
class Finding:
    detector: str
    target: str
    location: str
    message: str
    expected: str
    observed: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "target": self.target,
            "location": self.location,
            "message": self.message,
            "expected": self.expected,
            "observed": self.observed,
        }


def detect(
    artifact: Artifact,
    report_values: Mapping[str, float],
    sex: str,
    age: int,
    metrics: Sequence[Metric],
) -> tuple[Finding, ...]:
    """对一份产物跑全部确定性检查器。

    需要报告原值：这是**差分审计的前提**——审计器必须能看到源数据，
    否则它只能核对"话有没有依据"，无法核对"判定对不对"。
    """
    by_code = {metric.code: metric for metric in metrics}
    known = known_citations(metrics)
    findings: list[Finding] = []

    for item in artifact.items:
        metric = by_code.get(item.code)
        if metric is None:  # pragma: no cover — 产物里的指标一定来自指标清单
            findings.append(
                Finding(
                    detector="unit_consistency",
                    target=item.code,
                    location="items[].code",
                    message="产物里出现了指标清单之外的指标",
                    expected="指标清单内的指标",
                    observed=item.code,
                )
            )
            continue

        true_value = float(report_values[item.code])

        # 1) 数值一致性（带容差，容忍正常取整）
        if abs(item.value - true_value) > max(1e-9, abs(true_value) * VALUE_TOLERANCE):
            findings.append(
                Finding(
                    detector="value_consistency",
                    target=item.code,
                    location="items[].value",
                    message=f"{metric.name} 的数值与报告原值不一致",
                    expected=f"{true_value:g}",
                    observed=f"{item.value:g}",
                )
            )

        # 2) 单位一致性
        if item.unit != metric.unit:
            findings.append(
                Finding(
                    detector="unit_consistency",
                    target=item.code,
                    location="items[].unit",
                    message=f"{metric.name} 的单位与指标清单不一致",
                    expected=metric.unit,
                    observed=item.unit,
                )
            )

        # 3) 引用存在性
        for cite in item.citations:
            if cite not in known:
                findings.append(
                    Finding(
                        detector="citation_existence",
                        target=item.code,
                        location="items[].citations",
                        message=f"{metric.name} 的依据不在合法引用集合内",
                        expected="合法引用集合内的文号",
                        observed=cite,
                    )
                )

        # 4) 建议契约：severity 与 advice 必须匹配
        expected_advice = ADVICE_BY_SEVERITY.get(item.severity)
        if expected_advice is not None and item.advice != expected_advice:
            findings.append(
                Finding(
                    detector="advice_contract",
                    target=item.code,
                    location="items[].advice",
                    message=f"{metric.name} 的判定等级与建议动作不一致",
                    expected=expected_advice,
                    observed=item.advice,
                )
            )

        # 5) 安全越界
        hit_terms = [term for term in SAFETY_TERMS if term in item.explanation]
        if hit_terms:
            findings.append(
                Finding(
                    detector="safety_terms",
                    target=item.code,
                    location="items[].explanation",
                    message=f"{metric.name} 的解释里出现禁用表达",
                    expected="只做科普与就医准备",
                    observed="、".join(hit_terms),
                )
            )

        # 6) oracle 差分：拿报告原值重算，比对等级
        oracle = judge_metric(metric, sex, age, true_value)
        oracle_verdict = str(oracle["final_verdict"])
        if oracle_verdict != item.severity:
            findings.append(
                Finding(
                    detector="oracle_differential",
                    target=item.code,
                    location="items[].severity",
                    message=f"{metric.name} 的判定与独立重算的结果不一致",
                    expected=oracle_verdict,
                    observed=item.severity,
                )
            )

    return tuple(findings)
