"""评测：把检查器的发现与注入的标准答案比对，算出召回率与误报率。

## 两个指标必须同时看

只报召回率是**自欺欺人**：一个"每份产物都报 8 条缺陷"的检查器召回率是 100%，
但完全不可用。所以误报率必须是一等指标。

## 误报率要分两层看

- **普通干净样本**：原封不动的模板输出。确定性检查器在它上面一条都不该报，
  但这个 0 说服力很弱——它只说明"模板输出是自洽的"。
- **合法变体样本（hard negative）**：干净但加了合法变化
  （显示取整、引用顺序调换、引用重复）。**这一层才是对稳健性的真正考验**。
  实测第一版数值检查没有容差，就会把"4.2117 显示成 4.21"报成缺陷。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from audit.detect import DETECTORS, Finding, detect
from audit.inject import DEFECT_KINDS, Defect, InjectedCase
from audit.pipeline import JudgedReport, Metric

__all__ = ["CaseOutcome", "EvaluationReport", "evaluate"]


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    clean: bool
    variation: str | None
    defect_count: int
    findings: tuple[Finding, ...]
    caught: tuple[Defect, ...]
    missed: tuple[Defect, ...]
    false_positives: tuple[Finding, ...]


@dataclass(frozen=True)
class EvaluationReport:
    outcomes: tuple[CaseOutcome, ...]
    total_defects: int
    caught_total: int
    findings_total: int
    false_positives: int
    clean_cases: int
    hard_negative_cases: int
    false_positive_cases: int
    hard_negative_false_positives: int
    recall_by_kind: Mapping[str, tuple[int, int]]
    false_positives_by_detector: Mapping[str, int]

    @property
    def recall_overall(self) -> float:
        return self.caught_total / self.total_defects if self.total_defects else 0.0

    @property
    def precision(self) -> float:
        denominator = self.caught_total + self.false_positives
        return self.caught_total / denominator if denominator else 0.0

    @property
    def false_positives_per_clean_case(self) -> float:
        return self.false_positives / self.clean_cases if self.clean_cases else 0.0

    def recall_of(self, kind: str) -> float:
        caught, total = self.recall_by_kind.get(kind, (0, 0))
        return caught / total if total else 0.0

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append("# 审计器评测报告（A3：确定性检查器）")
        lines.append("")
        lines.append("> 检查器全部是确定性程序，**没有任何模型参与**。")
        lines.append("> 标准答案来自缺陷注入器，固定 seed 可逐字节复现。")
        lines.append("")
        lines.append("## 总览")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|---|---|")
        lines.append(f"| 已知缺陷总数 | {self.total_defects} |")
        lines.append(f"| 抓到 | **{self.caught_total}** |")
        lines.append(f"| **召回率** | **{self.recall_overall:.1%}** |")
        lines.append(f"| 检查器报出的条目总数 | {self.findings_total} |")
        lines.append(f"| 误报（报了但不是缺陷） | **{self.false_positives}** |")
        lines.append(f"| **精确率** | **{self.precision:.1%}** |")
        lines.append(f"| 干净样本数 | {self.clean_cases} |")
        lines.append(f"| **每份干净样本平均误报** | **{self.false_positives_per_clean_case:.3f} 条** |")
        lines.append(f"| 有误报的干净样本数 | {self.false_positive_cases} |")
        lines.append(f"| 其中「合法变体」样本 | {self.hard_negative_cases}（承担 {self.hard_negative_false_positives} 条误报）|")
        lines.append("")

        lines.append("## 按缺陷类型的召回")
        lines.append("")
        lines.append("| 缺陷类型 | 抓到 / 总数 | 召回率 |")
        lines.append("|---|---|---|")
        for kind in DEFECT_KINDS:
            caught, total = self.recall_by_kind.get(kind, (0, 0))
            rate = f"{caught / total:.1%}" if total else "—"
            lines.append(f"| `{kind}` | {caught} / {total} | {rate} |")
        lines.append("")

        lines.append("## 误报分布（按检查器）")
        lines.append("")
        lines.append("| 检查器 | 误报条数 |")
        lines.append("|---|---|")
        for detector in DETECTORS:
            count = self.false_positives_by_detector.get(detector, 0)
            lines.append(f"| `{detector}` | {count} |")
        lines.append("")

        missed = [
            defect
            for outcome in self.outcomes
            for defect in outcome.missed
        ]
        lines.append("## 漏掉的缺陷")
        lines.append("")
        if missed:
            lines.append("| 编号 | 类型 | 指标 | 应由谁发现 |")
            lines.append("|---|---|---|---|")
            for defect in missed:
                lines.append(
                    f"| {defect.defect_id} | `{defect.kind}` | `{defect.target}` "
                    f"| `{defect.expected_detector}` |"
                )
        else:
            lines.append("- 无（召回率 100%）")
        lines.append("")

        return "\n".join(lines)


#: 允许的"替代检查器"：**同一类缺陷被更强的层先抓到，算抓到，不算误报。**
#:
#: 目前只有一条：改写型安全越界（`safety_paraphrase`）在基准里的预期检查器是
#: 语义检查（`semantic_check`）。但如果你在护栏（`safety_terms`）里加了足够强的词，
#: 它就会**先**抓到——那是**更好**而不是更差：更便宜、更确定、可复现。
#:
#: ⚠️ 真实陷阱：没有这条例外时，你往 `agent/guardrails.py` 加一条规则会让
#: 端到端审计**多出一批"误报"**（因为发现被记在 `safety_terms` 名下，
#: 而缺陷期望的是 `semantic_check`），于是"改进护栏"看起来像"把系统改坏了"。
#: 这是评测口径的漏洞，不是护栏的问题。
ALTERNATE_DETECTORS: Mapping[str, frozenset[str]] = {
    "safety_paraphrase": frozenset({"safety_terms"}),
}


def _matches(finding: Finding, defect: Defect) -> bool:
    """一条发现是否算"抓到了"这条缺陷：必须是**同一指标**，且检查器**对得上**。

    检查器默认必须完全一致——不能只看指标相同，那样一个乱报的检查器也能蹭到召回率。
    唯一的例外写在 `ALTERNATE_DETECTORS` 里（更便宜的一层先抓到，算抓到）。
    """
    if finding.target != defect.target:
        return False
    if finding.detector == defect.expected_detector:
        return True
    return finding.detector in ALTERNATE_DETECTORS.get(defect.kind, frozenset())


def evaluate(
    cases: Sequence[InjectedCase],
    judged_cases: Sequence[tuple[str, JudgedReport]],
    metrics: Sequence[Metric],
) -> EvaluationReport:
    metrics = tuple(metrics)
    recall_by_kind: dict[str, list[int]] = {kind: [0, 0] for kind in DEFECT_KINDS}
    fp_by_detector: dict[str, int] = {detector: 0 for detector in DETECTORS}

    outcomes: list[CaseOutcome] = []
    total_defects = caught_total = findings_total = false_positives = 0
    clean_cases = hard_negative_cases = fp_cases = hn_fp = 0

    for case, (_profile, judged) in zip(cases, judged_cases):
        report = judged.report
        findings = detect(
            case.artifact, report.values, report.sex, report.age, metrics
        )

        caught: list[Defect] = []
        missed: list[Defect] = []
        for defect in case.defects:
            recall_by_kind[defect.kind][1] += 1
            if any(_matches(finding, defect) for finding in findings):
                caught.append(defect)
                recall_by_kind[defect.kind][0] += 1
            else:
                missed.append(defect)

        case_fp = [
            finding
            for finding in findings
            if not any(_matches(finding, defect) for defect in case.defects)
        ]
        for finding in case_fp:
            fp_by_detector[finding.detector] = fp_by_detector.get(finding.detector, 0) + 1

        total_defects += len(case.defects)
        caught_total += len(caught)
        findings_total += len(findings)
        false_positives += len(case_fp)

        if case.clean:
            clean_cases += 1
            if case.variation and case.variation != "none":
                hard_negative_cases += 1
                hn_fp += len(case_fp)
            if case_fp:
                fp_cases += 1

        outcomes.append(
            CaseOutcome(
                case_id=case.case_id,
                clean=case.clean,
                variation=case.variation,
                defect_count=len(case.defects),
                findings=findings,
                caught=tuple(caught),
                missed=tuple(missed),
                false_positives=tuple(case_fp),
            )
        )

    return EvaluationReport(
        outcomes=tuple(outcomes),
        total_defects=total_defects,
        caught_total=caught_total,
        findings_total=findings_total,
        false_positives=false_positives,
        clean_cases=clean_cases,
        hard_negative_cases=hard_negative_cases,
        false_positive_cases=fp_cases,
        hard_negative_false_positives=hn_fp,
        recall_by_kind={kind: (value[0], value[1]) for kind, value in recall_by_kind.items()},
        false_positives_by_detector=dict(fp_by_detector),
    )
