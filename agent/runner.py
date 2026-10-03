"""端到端跑审计图，并对整批样本算指标。

这份报告回答一个具体问题：**把确定性与语义两层合起来，审计器到底能到多少？**

对照口径：
- **确定性层单独**：`python -m audit eval` 的召回（实测 87.9%）
- **加上语义层**：本报告

两者之差就是语义层挣来的分。如果差值为 0，那语义层就该被砍掉——
**一个不带来增量的模块留在系统里只是成本和风险。**
"""

from __future__ import annotations

from collections import Counter  # noqa: F401  (保留以便将来做分布统计)
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from agent.graph import build_audit_graph
from agent.judge import Judge
from agent.policy import AuditPolicy
from agent.prompts import current_prompt
from audit.inject import DEFECT_KINDS, InjectedCase
from audit.pipeline import JudgedReport, Metric

__all__ = ["AuditOutcome", "BatchAuditReport", "run_batch"]


@dataclass(frozen=True)
class AuditOutcome:
    report_id: str
    audit: dict[str, Any]
    caught: tuple[str, ...]
    missed: tuple[str, ...]
    false_positives: int


@dataclass(frozen=True)
class BatchAuditReport:
    cases: int
    total_defects: int
    caught: int
    findings: int
    false_positives: int
    clean_cases: int
    escalated_cases: int
    model_calls: int
    recall_by_kind: Mapping[str, tuple[int, int]]
    policy: str
    prompt_version: str
    deterministic_only_recall: float | None = None

    @property
    def recall(self) -> float:
        return self.caught / self.total_defects if self.total_defects else 0.0

    @property
    def precision(self) -> float:
        denominator = self.caught + self.false_positives
        return self.caught / denominator if denominator else 0.0

    def to_markdown(self) -> str:
        lines = [
            "# 审计 agent 端到端报告（A5）",
            "",
            f"- 策略：`{self.policy}`",
            f"- 提示词版本：`{self.prompt_version}`",
            f"- 样本：{self.cases} 份（其中干净样本 {self.clean_cases} 份）",
            "",
            "## 总览",
            "",
            "| 指标 | 数值 |",
            "|---|---|",
            f"| 已知缺陷 | {self.total_defects} |",
            f"| 抓到 | **{self.caught}** |",
            f"| **召回率** | **{self.recall:.1%}** |",
            f"| 报出的条目 | {self.findings} |",
            f"| 误报 | {self.false_positives} |",
            f"| **精确率** | **{self.precision:.1%}** |",
            f"| 需人工复核的样本 | {self.escalated_cases} |",
            f"| **模型调用总数** | **{self.model_calls}** |",
            "",
        ]

        if self.deterministic_only_recall is not None:
            delta = self.recall - self.deterministic_only_recall
            lines += [
                "## 语义层值不值",
                "",
                "| | 召回率 |",
                "|---|---|",
                f"| 只有确定性层 | {self.deterministic_only_recall:.1%} |",
                f"| 加上语义层 | **{self.recall:.1%}** |",
                f"| **增量** | **{delta:+.1%}**（代价：{self.model_calls} 次模型调用）|",
                "",
            ]

        lines += ["## 按缺陷类型的召回", "", "| 缺陷类型 | 抓到 / 总数 |", "|---|---|"]
        for kind in DEFECT_KINDS:
            caught, total = self.recall_by_kind.get(kind, (0, 0))
            lines.append(f"| `{kind}` | {caught} / {total} |")
        lines.append("")
        return "\n".join(lines)


def run_batch(
    cases: Sequence[InjectedCase],
    judged_cases: Sequence[tuple[str, JudgedReport]],
    metrics: Sequence[Metric],
    policy: AuditPolicy,
    judge: Judge,
    prompt: str | None = None,
    checkpointer: Any = None,
    deterministic_only_recall: float | None = None,
) -> BatchAuditReport:
    prompt_text = prompt or current_prompt()
    graph, _nodes = build_audit_graph(
        policy=policy, judge=judge, metrics=metrics, prompt=prompt_text, checkpointer=checkpointer
    )

    recall_by_kind: dict[str, list[int]] = {kind: [0, 0] for kind in DEFECT_KINDS}
    total_defects = caught = findings_total = false_positives = 0
    clean_cases = escalated_cases = model_calls = 0

    for case, (_profile, judged) in zip(cases, judged_cases):
        report = judged.report
        config = (
            {"configurable": {"thread_id": f"audit-{report.report_id}"}}
            if checkpointer is not None
            else None
        )
        final = graph.invoke(
            {
                "artifact": case.artifact.to_dict(),
                "report_values": dict(report.values),
                "sex": report.sex,
                "age": report.age,
            },
            config,
        )
        audit = final["audit"]
        accepted = audit["findings"]

        for defect in case.defects:
            recall_by_kind[defect.kind][1] += 1
            hit = any(
                finding["detector"] == defect.expected_detector
                and finding["target"] == defect.target
                for finding in accepted
            )
            if hit:
                recall_by_kind[defect.kind][0] += 1
                caught += 1

        case_fp = 0
        for finding in accepted:
            if not any(
                finding["detector"] == defect.expected_detector
                and finding["target"] == defect.target
                for defect in case.defects
            ):
                case_fp += 1

        total_defects += len(case.defects)
        findings_total += len(accepted)
        false_positives += case_fp
        if case.clean:
            clean_cases += 1
        if audit["escalated"]:
            escalated_cases += 1
        model_calls += int(audit.get("model_calls", 0))

    return BatchAuditReport(
        cases=len(cases),
        total_defects=total_defects,
        caught=caught,
        findings=findings_total,
        false_positives=false_positives,
        clean_cases=clean_cases,
        escalated_cases=escalated_cases,
        model_calls=model_calls,
        recall_by_kind={kind: (value[0], value[1]) for kind, value in recall_by_kind.items()},
        policy=policy.describe(),
        prompt_version=_prompt_version(prompt_text),
        deterministic_only_recall=deterministic_only_recall,
    )


def _prompt_version(prompt_text: str) -> str:
    from agent.prompts import _REGISTRY, CURRENT_VERSION

    for version, text in _REGISTRY.items():
        if text == prompt_text:
            return version
    return f"{CURRENT_VERSION}(custom)"
