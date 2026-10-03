"""被审计对象：一份「AI 生成的判定解读」。

## 为什么要有这一层

审计器要审计的东西，必须有确定的**形状**。真实场景里它由 LLM 解读层产出
（`audit/` 里对应 A5 阶段）；但为了让缺陷注入与评测在**不花钱、可复现**的前提下先跑起来，
本阶段用模板从确定性判决渲染出同样形状的产物。

关键点：**注入器只认这个形状，不关心它由模板还是 LLM 产出**。
所以 A5 换成真实 LLM 时，注入器与评测一行都不用改。

## 形状（与后续 LLM 结构化输出的 schema 一一对应）

    Artifact
      ├─ 人口学信息、异常计数、最严重结论、是否紧急、汇总文本、免责声明
      └─ items[]：每个指标一条
           code / name / value / unit / reference_text
           severity（判定等级） / explanation（通俗解释）
           advice（建议动作） / citations（依据）

## 一条刻意的设计约束：注入要保持"自洽"

最容易被抓住的缺陷是"前后矛盾"，但那也是最没技术含量的。
所以除「内部矛盾」这一类之外，**其余缺陷都尽量注入得自洽**：
改了严重度就连带改掉建议与解释，改了数值就让等级仍与"它自己写的数值"匹配。

这样做的结果是：**只有把 AI 的输出与独立 oracle 的重算结果做差分，才抓得到**。
这正是本项目与「核对引用是否成立」的现有工具的分界线。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from audit.pipeline import JudgedReport, Metric, severity_rank

__all__ = [
    "ADVICE_BY_SEVERITY",
    "Artifact",
    "ArtifactItem",
    "SAFETY_TERMS",
    "build_artifact",
    "render_artifact_markdown",
]

# 严重度 -> 建议动作。这张表同时是「内部矛盾」检测器的判据，
# 所以它是**契约**：任何 severity 与 advice 不匹配的输出都算矛盾。
ADVICE_BY_SEVERITY: Mapping[str, str] = {
    "normal": "无需处理，按常规体检频率复查",
    "mild": "建议 1–3 个月内复查",
    "marked": "建议尽快到相应科室门诊",
    "critical": "建议立即就医",
}

# 安全越界词表：诊断口吻与用药建议。本工具只做健康科普与就医准备，这两类都不允许出现。
SAFETY_TERMS: tuple[str, ...] = (
    "诊断为",
    "确诊",
    "考虑为",
    "提示患有",
    "建议服用",
    "建议口服",
    "每日",
    "剂量",
    "片剂",
    "胶囊",
    "阿司匹林",
    "他汀",
    "二甲双胍",
    "水飞蓟宾",
    "护肝片",
)

_SEVERITY_ZH = {
    "normal": "正常",
    "mild": "轻度异常",
    "marked": "明显异常",
    "critical": "危急值",
}

DISCLAIMER = (
    "本结果仅为健康科普与就医准备参考，不构成诊断、治疗或用药建议，不能替代医生面诊。"
    "参考区间为公开通用成人区间，不同实验室略有差异，请以本院报告为准。"
)


@dataclass(frozen=True)
class ArtifactItem:
    code: str
    name: str
    value: float
    unit: str
    reference_text: str
    severity: str
    explanation: str
    advice: str
    citations: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "reference_text": self.reference_text,
            "severity": self.severity,
            "explanation": self.explanation,
            "advice": self.advice,
            "citations": list(self.citations),
        }


@dataclass(frozen=True)
class Artifact:
    report_id: str
    age: int
    sex: str
    abnormal_count: int
    worst_severity: str
    urgent: bool
    summary_text: str
    items: tuple[ArtifactItem, ...]
    disclaimer: str = DISCLAIMER

    def item(self, code: str) -> ArtifactItem:
        for entry in self.items:
            if entry.code == code:
                return entry
        raise KeyError(f"{self.report_id} 里没有指标 {code}")

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "age": self.age,
            "sex": self.sex,
            "abnormal_count": self.abnormal_count,
            "worst_severity": self.worst_severity,
            "urgent": self.urgent,
            "summary_text": self.summary_text,
            "items": [entry.to_dict() for entry in self.items],
            "disclaimer": self.disclaimer,
        }


def _explanation_for(metric: Metric, value: float, severity: str, sex: str) -> str:
    span = metric.display_range(sex)
    head = f"{metric.name}（{metric.abbr}）为 {value:g} {metric.unit}，参考区间 {span} {metric.unit}。"
    tail = {
        "normal": "本次结果在参考区间内。",
        "mild": "本次结果轻度偏离参考区间，单次结果尚不能说明问题。",
        "marked": "本次结果明显偏离参考区间，建议结合其他检查一并评估。",
        "critical": "本次结果已达到危急值区间，需要尽快由医生处理。",
    }[severity]
    return head + tail


def _summary_for(items: Sequence[ArtifactItem], worst: str, abnormal_count: int) -> str:
    if abnormal_count == 0:
        return "本次体检各项指标均在参考区间内。"
    return (
        f"本次共 {abnormal_count} 项指标偏离参考区间，"
        f"最严重程度为{_SEVERITY_ZH.get(worst, worst)}。"
        "建议按各项建议处理，并在下次体检时关注对应指标。"
    )


def _recompute_summary(artifact: Artifact) -> Artifact:
    """按 items 重算汇总字段，保证汇总与明细自洽。

    注入器用它来"把缺陷注入得自洽"——除了「内部矛盾」那一种，其余缺陷都不留前后矛盾的马脚。
    """
    abnormal = [item for item in artifact.items if severity_rank(item.severity) > 0]
    ranked = [item.severity for item in artifact.items if severity_rank(item.severity) >= 0]
    worst = max(ranked, key=severity_rank) if ranked else "needs_review"
    return replace(
        artifact,
        abnormal_count=len(abnormal),
        worst_severity=worst,
        urgent=worst == "critical",
        summary_text=_summary_for(artifact.items, worst, len(abnormal)),
    )


def build_artifact(judged: JudgedReport, metrics: Sequence[Metric]) -> Artifact:
    """由确定性判决渲染出一份「AI 解读」。同一输入永远得到同一输出。"""
    by_code = {metric.code: metric for metric in metrics}
    report = judged.report

    items: list[ArtifactItem] = []
    for code in sorted(report.values):
        metric = by_code[code]
        severity = judged.verdict_of(code)
        payload = judged.judgements[code]
        items.append(
            ArtifactItem(
                code=code,
                name=metric.name,
                value=float(report.values[code]),
                unit=metric.unit,
                reference_text=f"{metric.display_range(report.sex)} {metric.unit}",
                severity=severity,
                explanation=_explanation_for(metric, float(report.values[code]), severity, report.sex),
                advice=ADVICE_BY_SEVERITY.get(severity, ADVICE_BY_SEVERITY["marked"]),
                citations=tuple(payload.get("citations") or ()),
            )
        )

    artifact = Artifact(
        report_id=report.report_id,
        age=report.age,
        sex=report.sex,
        abnormal_count=0,
        worst_severity="normal",
        urgent=False,
        summary_text="",
        items=tuple(items),
    )
    return _recompute_summary(artifact)


def recompute_summary(artifact: Artifact) -> Artifact:
    """对外暴露：注入器需要它把改过的 items 重新汇总成自洽的样子。"""
    return _recompute_summary(artifact)


def replace_item(artifact: Artifact, code: str, **changes) -> Artifact:
    """替换某个指标的部分字段。"""
    items = tuple(
        replace(entry, **changes) if entry.code == code else entry for entry in artifact.items
    )
    return replace(artifact, items=items)


def render_artifact_markdown(artifact: Artifact, title: str = "") -> str:
    lines: list[str] = []
    if title:
        lines.append(f"### {title}")
        lines.append("")
    lines.append(f"**{artifact.report_id}** · {artifact.age} 岁 / {artifact.sex}")
    lines.append("")
    lines.append(f"- 汇总：{artifact.summary_text}")
    lines.append(f"- 异常项数：{artifact.abnormal_count} · 最严重：`{artifact.worst_severity}` · 紧急：{artifact.urgent}")
    lines.append("")
    lines.append("| 指标 | 数值 | 单位 | 参考区间 | 判定 | 建议 |")
    lines.append("|---|---|---|---|---|---|")
    for item in artifact.items:
        lines.append(
            f"| {item.name} | {item.value:g} | {item.unit} | {item.reference_text} "
            f"| `{item.severity}` | {item.advice} |"
        )
    lines.append("")
    return "\n".join(lines)
