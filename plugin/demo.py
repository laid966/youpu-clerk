"""插件演示：**用插件的数据 + 本体的机制，跑通一次完整审计。**

## 这个演示证明什么

它要回答的是那个问题——"本体独立了吗？"

流程里本体做的事：

1. 读插件声明的判定域，调 `engine` 重算判定（**oracle**）
2. 用插件的安全词表和"判定→建议"映射组装一份自洽的产物
3. 跑**本体的六个检查器**（一个都不认识这个行业）
4. 故意把一个判定改成错的（场景无关的注入），再跑一次 → 应当被抓到

**如果换插件能跑通、且本体一行代码不改，那"本体独立"就成立。**

## 这个演示**没有**证明什么（必须说清）

`audit/inject.py` 那 9 类注入目前还是医学场景专用的（措辞、阈值用错性别等）。
本演示只用**场景无关**的那一类：判定被改成错的。
其余缺陷类型的插件化是下一步——**这里不假装已经做完。**
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from audit.artifact import Artifact, ArtifactItem, replace_item
from audit.detect import Finding, detect
from audit.pipeline import load_metrics, judge_metric
from plugin.spec import PluginError, PluginSpec

__all__ = ["DemoResult", "build_clean_artifact", "misjudge_one", "run_demo"]

DEMO_SEED = 20261003


@dataclass(frozen=True)
class DemoResult:
    plugin: str
    title: str
    items: int
    clean_findings: tuple[Finding, ...]
    target: str
    wrong_verdict: str
    broken_findings: tuple[Finding, ...]

    @property
    def caught(self) -> bool:
        """注入的那个错误判定有没有被本体的检查器抓到。"""
        return any(
            finding.detector == "oracle_differential" and finding.target == self.target
            for finding in self.broken_findings
        )

    @property
    def clean(self) -> bool:
        """干净产物上一条误报都没有。"""
        return self.clean_findings == ()


def _reference_text(metric: Any) -> str:
    low, high = metric.reference.get("male", (0.0, 0.0))
    return f"应落在 {low:g}–{high:g} {metric.unit}".strip()


def verdict_ladder(plugin: PluginSpec) -> tuple[str, ...]:
    """该场景的判定等级顺序（由轻到重），**由插件清单声明**。

    为什么必须显式声明：引擎里的 `verdicts` 是 **frozenset**，顺序会丢，
    而"哪个方向更严重"是有业务含义的——
    体检 normal→mild→marked→critical，信贷 approved→review→rejected。
    **顺序属于场景知识，所以放在插件里，不放进本体。**

    但声明必须和判定域对得上，否则就是两处各说各话——所以这里做一致性校验。
    """
    from engine.domain import load_domain

    declared = tuple(plugin.verdict_ladder)
    if len(declared) < 2:
        raise PluginError(
            f"插件 {plugin.name} 的 verdict_ladder 至少要有两个判定等级"
            "（否则没法定义「哪一个方向更严重」，也就无法造出「判错」这个缺陷）"
        )

    metrics = load_metrics(plugin.metrics)
    if not metrics:
        raise PluginError(f"插件 {plugin.name} 的字段清单是空的")
    for metric in metrics:
        domain = load_domain(metric.domain_path)
        missing = set(domain.verdicts) - set(declared)
        if missing:
            raise PluginError(
                f"插件 {plugin.name} 的 verdict_ladder 漏了 {sorted(missing)}——"
                f"判定域 {domain.name} 会给出这些判定，清单里却没有。"
                "两处必须对得上，否则「等级顺序」就是假的。"
            )
    return declared


def build_clean_artifact(plugin: PluginSpec) -> tuple[Artifact, dict[str, float]]:
    """用插件声明的字段清单和规则，合成一份**自洽**的产物。

    "自洽"= 判定来自引擎重算、建议来自插件的映射表、依据来自插件的引用目录。
    所以本体的检查器跑上去应当**一条都不报**。
    如果有报，说明插件的数据之间互相打架（比如"判定→建议"映射缺了一项）。
    """
    metrics = load_metrics(plugin.metrics)
    ladder = verdict_ladder(plugin)
    items: list[ArtifactItem] = []
    values: dict[str, float] = {}

    for index, metric in enumerate(metrics):
        low, high = metric.reference.get("male", (0.0, 0.0))
        value = round((low + high) / 2, 4)
        values[metric.code] = value

        verdict = str(judge_metric(metric, "male", 35, value)["final_verdict"])
        if verdict not in plugin.advice_by_verdict:
            raise PluginError(
                f"插件 {plugin.name} 的 advice_by_verdict 里没有 {verdict!r} 这个判定。"
                "**缺一项就会让「判定与建议是否矛盾」这个检查器失效，"
                "所以这里直接报错而不是兜底。**"
            )
        if not plugin.benign_templates:
            raise PluginError(f"插件 {plugin.name} 没有声明 benign_templates（合法说法模板）")

        items.append(
            ArtifactItem(
                code=metric.code,
                name=metric.name,
                value=value,
                unit=metric.unit,
                reference_text=_reference_text(metric),
                severity=verdict,
                explanation=plugin.benign_templates[index % len(plugin.benign_templates)],
                advice=plugin.advice_by_verdict[verdict],
                citations=(plugin.citation_catalogue[0],) if plugin.citation_catalogue else (),
            )
        )

    worst = max((item.severity for item in items), key=ladder.index) if items else "unknown"
    return (
        Artifact(
            report_id=f"{plugin.name.upper()}-0001",
            age=35,
            sex="male",
            abnormal_count=sum(1 for item in items if item.severity != ladder[0]),
            worst_severity=worst,
            urgent=False,
            summary_text=f"{plugin.title}：共 {len(items)} 项，判定均按规则重算。",
            items=tuple(items),
        ),
        values,
    )


def misjudge_one(artifact: Artifact, plugin: PluginSpec, code: str | None = None) -> tuple[Artifact, str]:
    """把一个字段的判定改成**错误的**另一个判定。返回 (新产物, 改成了什么)。

    这是**场景无关**的一类缺陷：任何"判定类产物"都可能判错。
    刻意同时改掉建议，让它成为一次"纯粹的判错"——
    只会触发 `oracle_differential`（判定与重算不一致），
    不会顺带触发"判定与建议矛盾"。
    """
    ladder = verdict_ladder(plugin)
    target = artifact.items[0] if code is None else artifact.item(code)
    current = ladder.index(target.severity)
    wrong = ladder[-1] if current != len(ladder) - 1 else ladder[0]
    updated = replace_item(
        artifact, target.code, severity=wrong, advice=plugin.advice_by_verdict[wrong]
    )
    return updated, wrong


def run_demo(plugin: PluginSpec) -> DemoResult:
    artifact, values = build_clean_artifact(plugin)
    metrics = load_metrics(plugin.metrics)

    clean = detect(artifact, values, artifact.sex, artifact.age, metrics, plugin=plugin)

    broken, wrong = misjudge_one(artifact, plugin)
    broken_findings = detect(broken, values, broken.sex, broken.age, metrics, plugin=plugin)

    return DemoResult(
        plugin=plugin.name,
        title=plugin.title,
        items=len(artifact.items),
        clean_findings=clean,
        target=artifact.items[0].code,
        wrong_verdict=wrong,
        broken_findings=broken_findings,
    )
