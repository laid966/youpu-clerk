"""判定稳健性审计：**这个结论离临界值有多近？**

## 这是什么（一类全新的发现）

到目前为止，我们所有的召回率都建立在"**缺陷是我注入的**"之上。
所以那个数字永远可以被人说成"你只测了你造的题"。

**稳健性审计不一样：它发现的是性质，不是造出来的题。**

    某一份解读说"肌酐轻度偏离"——
    但如果实测偏差 1%，判定就会变成"正常"。那这条结论就不该被当成定论。

## 为什么只有我们能做

这需要**独立 oracle**：必须能拿扰动后的数值**重算**判定。
引用类 / groundedness 工具（查"这句话有没有依据"）**原理上做不了**——它们没有重算能力。
所以这一类发现是**本架构独有的产出**。

## 它产出什么

- **判定脆弱率**：脆弱探测点 / 全部探测点
- 每个脆弱项**翻转所需的最小相对偏差**（"离临界值还有 0.5%"）与**翻转方向**
- **未计入的探测点**分三类单独计数（见下），不混进脆弱率

产品话术：**"这个结果离临界值太近，不宜作为定论。"**
—— 这句话任何 groundedness 工具都产不出来。

## 三条纪律（都是踩过坑之后立的）

**① 绝不混进召回率/误报率。** 脆弱项是**风险提示**，不是"AI 抄错了"。
混进去会让基准语义变浑，"召回 95%"这句话就不成立了。

**② 脆弱项算不算缺陷是产品判断**，不是技术判断 —— 归 `docs/02-metrics.md`。
本模块只负责把事实算出来。

**③ 算不出来的必须显式计数，不能静默跳过。**
静默跳过会缩小分母、让脆弱率虚高。三类"算不出来"分别是：

| 情况 | 为什么算不出来 |
|---|---|
| 域里没有这个指标的 `boundaries` | 没有阈值就无从谈"离临界值多近" |
| 扰动会越出 `Fact.minimum..maximum` | 不能凭空造出域声明范围外的输入 |
| 判定落在 `needs_review` | 域规则引用了别的指标，`judge_metric` 只喂一个事实 |

第三类是**真实存在**的：`judge_metric` 只放**一个**指标的事实进去，
所以任何"规则引用第二个指标"的域，在这个扫描里都会落到转人工。
目前三个插件都是单指标域，不受影响——但必须计数，否则以后新增多指标域时脆弱率会悄悄失真。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from audit.artifact import Artifact
from audit.pipeline import Metric, judge_metric

__all__ = [
    "DEFAULT_TOLERANCE",
    "DELTA_LADDER",
    "NEEDS_REVIEW",
    "BOUNDARY_ADJACENT",
    "Fragility",
    "RobustnessReport",
    "probe_values",
    "scan_artifact",
    "scan_boundaries",
    "scan_uniform",
    "verdict_at",
]

#: 判定阈值的默认"误差"量级：1%。
#: 医学检验的批间差异通常在这个量级；插件可以覆盖它（`measurement_tolerance`）。
DEFAULT_TOLERANCE = 0.01

#: 由小到大的相对偏差阶梯，用来报"翻转需要多小的偏差"。
#:
#: **刻意没有 0.0**：`judge(value)` 是确定性的，0 偏差永远得到同一个判定，
#: 所以"0 偏差就翻转"是**不可达**的状态。
#: （规划阶段我写错过这一点，测试把它暴露了。）
DELTA_LADDER: tuple[float, ...] = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05)

#: 偏差小于这个值就算"紧贴临界值"。
BOUNDARY_ADJACENT = 0.002

#: 引擎保留的"缺事实、转人工"判定。它不是结论，更谈不上脆弱。
NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class Fragility:
    target: str
    name: str
    value: float
    unit: str
    verdict: str
    flipped_to: str
    direction: str  # 往低偏 / 往高偏
    smallest_delta: float

    @property
    def is_boundary_adjacent(self) -> bool:
        """紧贴临界值——偏差不到 0.2% 就会翻转。"""
        return self.smallest_delta <= BOUNDARY_ADJACENT

    def describe(self) -> str:
        if self.is_boundary_adjacent:
            return (
                f"{self.name} 紧贴判定临界值（{self.value:g} {self.unit} → {self.verdict}）："
                f"{self.direction} {self.smallest_delta:.1%} 就会翻成 {self.flipped_to}"
            )
        return (
            f"{self.name} 的判定 {self.verdict} 在 {self.direction} {self.smallest_delta:.1%} "
            f"的偏差下会翻转成 {self.flipped_to}（当前 {self.value:g} {self.unit}）"
        )


@dataclass(frozen=True)
class RobustnessReport:
    probes: int
    tolerance: float
    findings: tuple[Fragility, ...] = ()
    skipped_no_boundaries: int = 0
    skipped_out_of_range: int = 0
    skipped_needs_review: int = 0
    unevaluable_metrics: tuple[str, ...] = field(default=())
    mode: str = "thresholds"
    """探测方式。**它决定这个脆弱率能怎么读**，所以必须显示出来。"""

    @property
    def mode_label(self) -> str:
        if self.mode == "thresholds":
            return "阈值附近扫描"
        if self.mode == "uniform":
            return "取值范围内均匀取样"
        if self.mode == "artifact":
            return "单份真实产物"
        return self.mode

    @property
    def caveat(self) -> str:
        """这个数字的偏差在哪 —— **必须写在报告里，不能让人误读。**"""
        if self.mode == "thresholds":
            return (
                "⚠️ **探测点是刻意放在判定阈值上的**，所以这个比例必然偏高——"
                "它度量的是「**每个阈值有多敏感**」，用来复核阈值设定；"
                "**不能读成「真实报告里有多少结论是脆的」**。"
                "要看后者，请用 `--mode uniform`（范围内均匀取样）"
                "或 `--artifact`（扫一份真实产物）。"
            )
        if self.mode == "uniform":
            return (
                "取样是在**参考区间上下两倍的窄带里均匀**做的，所以它不受阈值位置影响。"
                "但它**仍然不等于真实报告分布**——真实分布要靠每个场景自己的样本生成器"
                "（那是内容插件的工作，见 `docs/15`）。"
                "**不要把这里的比例直接当成「真实报告的脆弱率」。**"
            )
        return "数据来自一份具体产物，没有取样偏差。"

    @property
    def fragile(self) -> int:
        return len(self.findings)

    @property
    def fragile_rate(self) -> float:
        """脆弱率 = 脆弱探测点 / 可评估探测点。

        分母用**可评估**的点数，不算那些"根本算不出来"的——但它们在报告里显式列出。

        ⚠️ **这个比例怎么读，取决于 `mode`**（见 `caveat`）。
        阈值扫描模式下它必然偏高，因为探测点是刻意放在阈值上的。
        """
        evaluable = self.probes - self.skipped_needs_review
        return self.fragile / evaluable if evaluable else 0.0

    @property
    def boundary_adjacent(self) -> tuple[Fragility, ...]:
        return tuple(item for item in self.findings if item.is_boundary_adjacent)

    @property
    def skipped_total(self) -> int:
        return self.skipped_no_boundaries + self.skipped_out_of_range + self.skipped_needs_review

    def to_markdown(self) -> str:
        lines = [
            "# 判定稳健性报告",
            "",
            "> **这个结论离临界值有多近？**",
            ">",
            "> 与召回/误报**完全分开统计**：脆弱项是风险提示，不是「AI 抄错了」。",
            "> 这一类发现**不是注入的，是算出来的**——只有独立 oracle 能给出。",
            "> 零模型调用、零成本、完全确定性。",
            "",
            f"**探测方式：{self.mode_label}**",
            "",
            self.caveat,
            "",
            "## 总览",
            "",
            "| 指标 | 数值 |",
            "|---|---|",
            f"| 探测点 | {self.probes} |",
            f"| 判定会翻转的点 | **{self.fragile}** |",
            f"| **判定脆弱率** | **{self.fragile_rate:.1%}** |",
            f"| 其中紧贴临界值（偏差 ≤{BOUNDARY_ADJACENT:.1%}） | {len(self.boundary_adjacent)} |",
            f"| 判定所用的误差量级 | ±{self.tolerance:.2%} |",
            "",
            "## 没算出来的部分（显式列出，不静默跳过）",
            "",
            "| 原因 | 探测点 |",
            "|---|---|",
            f"| 域里没有这个指标的阈值 | {self.skipped_no_boundaries} |",
            f"| 扰动会越出域声明的取值范围 | {self.skipped_out_of_range} |",
            f"| 判定落在「缺事实转人工」 | {self.skipped_needs_review} |",
            "",
        ]
        if self.unevaluable_metrics:
            lines += [
                "**以下指标完全无法参与稳健性扫描**（域里没有它们的阈值）：",
                "",
            ]
            lines += [f"- `{code}`" for code in self.unevaluable_metrics]
            lines.append("")

        if not self.findings:
            lines += ["## 结论", "", "- 所有可评估探测点的判定在给定误差范围内都稳定。", ""]
            return "\n".join(lines)

        lines += [
            "## 脆弱的判定（按离临界值的距离排序）",
            "",
            "| 指标 | 当前值 | 当前判定 | 方向 | 会翻转成 | 需要多小的偏差 |",
            "|---|---|---|---|---|---|",
        ]
        for item in sorted(self.findings, key=lambda x: (x.smallest_delta, x.target)):
            lines.append(
                f"| {item.name} | {item.value:g} {item.unit} | {item.verdict} "
                f"| {item.direction} | {item.flipped_to} | {item.smallest_delta:.1%} |"
            )
        lines += [
            "",
            "## 怎么用这个数字",
            "",
            "- **对用户**：离临界值越近，越应当给「单次结果仅供参考、建议复查」的措辞，",
            "  而不是给一个硬结论。",
            "- **对产线**：脆弱率高的指标说明它的参考区间与结论口径**过于敏感**，",
            "  需要复核阈值设定或提高测量精度。",
            "- **对评测**：它和召回率**互不替代**。召回率问「有没有漏掉错」，",
            "  它问「结论有多硬」。",
            "",
            "> ⚠️ 脆弱项**算不算缺陷**是产品判断（见 `docs/02-metrics.md`）。",
            "> 本报告只给事实，不替你下结论。",
            "",
        ]
        return "\n".join(lines)


def verdict_at(metric: Metric, sex: str, age: int, value: float) -> str:
    """用独立 oracle 重算一个数值对应的判定。"""
    return str(judge_metric(metric, sex, age, float(value))["final_verdict"])


def _metric_fact(metric: Metric):
    """取该指标在判定域里的 Fact。

    ⚠️ `Domain.facts` 是 **Mapping[str, Fact]**（按名字索引），不是序列。
    直接 `for fact in domain.facts` 会遍历到字符串键——这是实现时踩过的坑，
    `tests/test_robustness.py` 里有一条守卫测试专门盯它。
    """
    from engine.domain import load_domain

    return load_domain(metric.domain_path).facts.get(metric.code)


def probe_values(metric: Metric) -> tuple[float, ...]:
    """该指标会被探测的数值：每个阈值上、以及紧贴它的两侧。

    为什么钉着阈值测：**离临界值越近，结论越脆**。
    阈值本来就在域的 `boundaries` 里声明过，不用另外维护一份。
    """
    fact = _metric_fact(metric)
    if fact is None:
        return ()
    values: list[float] = []
    for boundary in fact.boundaries or ():
        boundary = float(boundary)
        if boundary <= 0:
            continue
        for offset in (-0.002, 0.0, 0.002):
            values.append(round(boundary * (1 + offset), 6))
    return tuple(values)


def _within_range(fact, value: float) -> bool:
    if fact.minimum is not None and value < fact.minimum:
        return False
    if fact.maximum is not None and value > fact.maximum:
        return False
    return True


def _smallest_flip(
    metric: Metric,
    sex: str,
    age: int,
    value: float,
    base_verdict: str,
    tolerance: float,
    fact,
) -> tuple[str, str, float] | None:
    """找出让判定翻转所需的最小相对偏差。返回 (方向, 翻转后的判定, 偏差)。"""
    if value == 0:
        return None
    for delta in DELTA_LADDER:
        if delta > tolerance:
            break
        for sign, direction in ((-1, "往低偏"), (1, "往高偏")):
            probe = value * (1 + sign * delta)
            if probe == value or not _within_range(fact, probe):
                continue
            verdict = verdict_at(metric, sex, age, probe)
            if verdict != base_verdict:
                return direction, verdict, delta
    return None


def scan_boundaries(
    metrics: Sequence[Metric],
    sex: str = "male",
    age: int = 35,
    tolerance: float = DEFAULT_TOLERANCE,
) -> RobustnessReport:
    """把每个指标放在它**自己的判定阈值附近**，看结论稳不稳。

    **确定性、零模型调用、零成本。** 阈值来自插件的判定域，所以换插件也能跑。
    """
    findings: list[Fragility] = []
    probes = skipped_no_boundaries = skipped_out_of_range = skipped_needs_review = 0
    unevaluable: list[str] = []

    for metric in metrics:
        fact = _metric_fact(metric)
        values = probe_values(metric)
        if fact is None or not values:
            skipped_no_boundaries += 1
            unevaluable.append(metric.code)
            continue

        for value in values:
            if not _within_range(fact, value):
                skipped_out_of_range += 1
                continue
            base = verdict_at(metric, sex, age, value)
            if base == NEEDS_REVIEW:
                skipped_needs_review += 1
                continue
            probes += 1
            flip = _smallest_flip(metric, sex, age, value, base, tolerance, fact)
            if flip is None:
                continue
            direction, flipped_to, delta = flip
            findings.append(
                Fragility(
                    target=metric.code,
                    name=metric.name,
                    value=value,
                    unit=metric.unit,
                    verdict=base,
                    flipped_to=flipped_to,
                    direction=direction,
                    smallest_delta=delta,
                )
            )

    return RobustnessReport(
        probes=probes,
        tolerance=tolerance,
        findings=tuple(findings),
        skipped_no_boundaries=skipped_no_boundaries,
        skipped_out_of_range=skipped_out_of_range,
        skipped_needs_review=skipped_needs_review,
        unevaluable_metrics=tuple(unevaluable),
        mode="thresholds",
    )


def scan_uniform(
    metrics: Sequence[Metric],
    sex: str = "male",
    age: int = 35,
    tolerance: float = DEFAULT_TOLERANCE,
    samples_per_metric: int = 1000,
    seed: int = 20261003,
) -> RobustnessReport:
    """在**参考区间上下各两倍的窄带里均匀取点**，看多少比例的判定是脆的。

    为什么是这个带而不是整个取值范围：真实报告里绝大部分数值落在参考区间附近，
    在整个 `[minimum, maximum]`（比如 0–2000）上均匀取点几乎永远碰不到阈值，
    那样算出来的脆弱率恒等于 0，**是个没有信息量的数字**。

    ⚠️ 但它**仍然不等于真实报告分布**。真实分布要靠每个场景自己的样本生成器
    （那是内容插件的工作，见 `docs/15`）。所以报告里会写明这是**窄带均匀取样**，
    不会冒充"真实报告的脆弱率"。

    ## 为什么默认取 1000 个点（这是个真实教训）

    第一版默认每个指标只取 12 个点，信贷场景跑出来是 **0.0%**——
    看着像"很稳健"，其实是**取样太稀碰不到阈值**。
    阈值之间的间隔大约只占取值带的 1%，12 个点命中它的概率极低。

    改成 1000 个点后：探测点 2000、脆弱率 **0.6%**、用时 **0.5 秒**。

    **纯计算不值钱，没有理由省样本。** 这和前面"24 条样本只能声称 ≥88.3%"
    是同一个教训：**样本太少的结论，看起来越干净越可疑。**
    """
    import random

    rng = random.Random(seed)
    findings: list[Fragility] = []
    probes = skipped_out_of_range = skipped_needs_review = 0
    unevaluable: list[str] = []

    for metric in metrics:
        fact = _metric_fact(metric)
        if fact is None:
            unevaluable.append(metric.code)
            continue

        low, high = metric.reference.get(sex, metric.reference.get("male", (0.0, 0.0)))
        band_low, band_high = low * 0.5, high * 2.0
        if fact.minimum is not None:
            band_low = max(band_low, fact.minimum)
        if fact.maximum is not None:
            band_high = min(band_high, fact.maximum)
        if band_high <= band_low:
            unevaluable.append(metric.code)
            continue

        for _ in range(samples_per_metric):
            value = round(rng.uniform(band_low, band_high), 6)
            if value <= 0 or not _within_range(fact, value):
                skipped_out_of_range += 1
                continue
            base = verdict_at(metric, sex, age, value)
            if base == NEEDS_REVIEW:
                skipped_needs_review += 1
                continue
            probes += 1
            flip = _smallest_flip(metric, sex, age, value, base, tolerance, fact)
            if flip is None:
                continue
            direction, flipped_to, delta = flip
            findings.append(
                Fragility(
                    target=metric.code,
                    name=metric.name,
                    value=value,
                    unit=metric.unit,
                    verdict=base,
                    flipped_to=flipped_to,
                    direction=direction,
                    smallest_delta=delta,
                )
            )

    return RobustnessReport(
        probes=probes,
        tolerance=tolerance,
        findings=tuple(findings),
        skipped_out_of_range=skipped_out_of_range,
        skipped_needs_review=skipped_needs_review,
        unevaluable_metrics=tuple(unevaluable),
        mode="uniform",
    )


def scan_artifact(
    artifact: Artifact,
    report_values: Mapping[str, float],
    sex: str,
    age: int,
    metrics: Sequence[Metric],
    tolerance: float = DEFAULT_TOLERANCE,
) -> RobustnessReport:
    """审计一份**具体产物**：它给出的这些判定，各有多硬。"""
    by_code = {metric.code: metric for metric in metrics}
    findings: list[Fragility] = []
    probes = skipped_needs_review = skipped_out_of_range = 0

    for item in artifact.items:
        metric = by_code.get(item.code)
        if metric is None:
            continue
        fact = _metric_fact(metric)
        if fact is None:
            continue
        value = float(report_values.get(item.code, item.value))
        if not _within_range(fact, value):
            skipped_out_of_range += 1
            continue
        base = verdict_at(metric, sex, age, value)
        if base == NEEDS_REVIEW:
            skipped_needs_review += 1
            continue
        probes += 1
        flip = _smallest_flip(metric, sex, age, value, base, tolerance, fact)
        if flip is None:
            continue
        direction, flipped_to, delta = flip
        findings.append(
            Fragility(
                target=item.code,
                name=metric.name,
                value=value,
                unit=metric.unit,
                verdict=base,
                flipped_to=flipped_to,
                direction=direction,
                smallest_delta=delta,
            )
        )

    return RobustnessReport(
        probes=probes,
        tolerance=tolerance,
        findings=tuple(findings),
        skipped_out_of_range=skipped_out_of_range,
        skipped_needs_review=skipped_needs_review,
        mode="artifact",
    )
