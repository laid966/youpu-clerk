"""判决流水线：把一份体检报告的事实，变成逐指标的确定性判决。

这是「被审计对象」的来源——审计器要审计的，就是这条流水线（以及后续的 LLM 解读层）
产出的东西。所以它必须**先真实存在**，否则审计就成了空转。

**本模块不含任何模型调用。** 判决全部来自 engine 的确定性规则。
这条边界是刻意的：审计器需要一个独立的 oracle，而 oracle 必须是确定的——
如果 oracle 自己也用模型，那"差分审计"就退化成"两个模型互相看谁更像"。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from engine.adjudicate import adjudicate
from engine.domain import Domain, load_domain

__all__ = [
    "JudgedReport",
    "Metric",
    "Report",
    "judge_report",
    "load_metrics",
    "severity_rank",
]

ROOT = Path(__file__).resolve().parents[1]
METRICS_FILE = ROOT / "domain" / "med-metrics.yaml"

# 严重度排序：数字越大越严重。用于"这份报告最坏到哪一级"以及后续审计排序。
_SEVERITY_ORDER = ("normal", "mild", "marked", "critical")


def severity_rank(verdict: str) -> int:
    """把判定值转成可比较的严重度序号；不认识的判定值（如 needs_review）排在最后讨论。"""
    if verdict in _SEVERITY_ORDER:
        return _SEVERITY_ORDER.index(verdict)
    return -1


@dataclass(frozen=True)
class Metric:
    code: str
    name: str
    abbr: str
    panel: str
    unit: str
    domain_path: Path
    reference: Mapping[str, tuple[float, float]]

    def reference_for(self, sex: str) -> tuple[float, float]:
        if sex not in self.reference:
            raise KeyError(f"指标 {self.code} 没有为性别 {sex!r} 定义参考区间")
        return self.reference[sex]

    def display_range(self, sex: str) -> str:
        low, high = self.reference_for(sex)
        return f"{low:g}–{high:g}"


@dataclass(frozen=True)
class Report:
    """一份体检报告（结构化）。真实场景里它来自 PDF 解析，这里是合成出来的。"""

    report_id: str
    age: int
    sex: str
    values: Mapping[str, float]

    def facts_for(self, metric: Metric) -> dict[str, Any]:
        """组装成某个指标判定域需要的事实。"""
        if metric.code not in self.values:
            raise KeyError(f"报告 {self.report_id} 缺少指标 {metric.code}")
        return {"sex": self.sex, "age": self.age, metric.code: self.values[metric.code]}


@dataclass(frozen=True)
class JudgedReport:
    """判决结果：每个指标一个确定性结论。"""

    report: Report
    judgements: Mapping[str, Mapping[str, Any]]  # 指标 code -> Judgement.to_dict()

    @property
    def report_id(self) -> str:
        return self.report.report_id

    def verdict_of(self, code: str) -> str:
        return str(self.judgements[code]["final_verdict"])

    def severity_of(self, code: str) -> int:
        return severity_rank(self.verdict_of(code))

    def worst_verdict(self) -> str:
        """整份报告最严重的结论（不含 needs_review）。"""
        verdicts = [self.verdict_of(code) for code in self.judgements]
        ranked = [verdict for verdict in verdicts if verdict in _SEVERITY_ORDER]
        if not ranked:
            return "needs_review"
        return max(ranked, key=severity_rank)

    def abnormal_codes(self) -> tuple[str, ...]:
        return tuple(
            sorted(code for code in self.judgements if severity_rank(self.verdict_of(code)) > 0)
        )

    def needs_human_review(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                code
                for code, payload in self.judgements.items()
                if payload.get("requires_human_review")
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report.report_id,
            "age": self.report.age,
            "sex": self.report.sex,
            "values": dict(self.report.values),
            "judgements": {code: dict(payload) for code, payload in self.judgements.items()},
            "worst_verdict": self.worst_verdict(),
            "abnormal_codes": list(self.abnormal_codes()),
            "needs_human_review": list(self.needs_human_review()),
        }


def load_metrics(path: str | Path = METRICS_FILE) -> tuple[Metric, ...]:
    """读取指标清单。"""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw.get("metrics"):
        raise ValueError(f"{path} 里没有 metrics")

    metrics: list[Metric] = []
    seen: set[str] = set()
    for item in raw["metrics"]:
        code = str(item["code"])
        if code in seen:
            raise ValueError(f"{path}: 指标 code 重复：{code}")
        seen.add(code)

        reference = {
            str(sex): (float(bounds[0]), float(bounds[1]))
            for sex, bounds in dict(item["reference"]).items()
        }
        domain_path = Path(item["domain"])
        if not domain_path.is_absolute():
            domain_path = ROOT / domain_path
        if not domain_path.is_file():
            raise ValueError(f"{path}: 指标 {code} 指向的判定域不存在：{domain_path}")

        metrics.append(
            Metric(
                code=code,
                name=str(item["name"]),
                abbr=str(item.get("abbr", code.upper())),
                panel=str(item.get("panel", "")),
                unit=str(item["unit"]),
                domain_path=domain_path,
                reference=reference,
            )
        )
    return tuple(metrics)


_DOMAIN_CACHE: dict[Path, Domain] = {}


def _domain_for(metric: Metric) -> Domain:
    """判定域加载带缓存：一份报告要判 8 次，重复读 YAML 是浪费。"""
    cached = _DOMAIN_CACHE.get(metric.domain_path)
    if cached is None:
        cached = load_domain(metric.domain_path)
        _DOMAIN_CACHE[metric.domain_path] = cached
    return cached


def judge_report(report: Report, metrics: tuple[Metric, ...]) -> JudgedReport:
    """对一份报告逐指标做确定性判决。

    同一个输入永远得到同一个输出——这是后续"差分审计"能成立的前提。
    """
    judgements: dict[str, Mapping[str, Any]] = {}
    for metric in metrics:
        result = adjudicate(_domain_for(metric), report.facts_for(metric))
        judgements[metric.code] = result.to_dict()
    return JudgedReport(report=report, judgements=judgements)


def judge_metric(metric: Metric, sex: str, age: int, value: float) -> Mapping[str, Any]:
    """只判一个指标。

    主要给样本生成器用：它需要"给定一个数值，问引擎这算第几级"，
    以便反查出能产生目标严重度的数值——**阈值只在域的规则里定义一次**，
    生成器不重复维护一份，避免两处不一致。
    """
    report = Report(report_id="<probe>", age=age, sex=sex, values={metric.code: float(value)})
    return adjudicate(_domain_for(metric), report.facts_for(metric)).to_dict()
