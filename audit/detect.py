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

## 扩展接缝：检查器现在是可注册的

第一版这 6 个检查器的逻辑全部内联在 `detect()` 的一个 for 循环里，
共享局部变量。**想加第 7 个检查器必须改核心文件** —— 那是横向扩展的硬阻塞。

现在每个检查器是独立函数 + 注册表（见 `audit/registry.py`）：

```python
from audit.detect import Finding, register_detector
from audit.registry import DetectorSpec

def my_detector(ctx):
    for item, metric in ctx.items():
        if 条件成立(item, metric):
            yield Finding(detector="my_detector", target=item.code, ...)

register_detector(DetectorSpec(
    name="my_detector",
    kinds=("my_defect_kind",),   # 不在基准覆盖内就写 ()
    run=my_detector,
    description="它防的是什么错",
))
```

注册之后 `detect()` 自动带上它——**核心调度代码一行都不用改**。

> ⚠️ 发现的**顺序不构成契约**（按检查器分组，不是按明细分组）。
> 不要写依赖顺序的断言。要断言就用 "存在某条 Finding 满足…"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from audit.artifact import ADVICE_BY_SEVERITY, SAFETY_TERMS, Artifact
from audit.pipeline import Metric, judge_metric
from audit.registry import DetectorContext, DetectorRegistry, DetectorSpec

__all__ = [
    "DEFAULT_REGISTRY",
    "DETECTORS",
    "DETECTOR_TO_KINDS",
    "Finding",
    "SEMANTIC_DETECTOR",
    "VALUE_TOLERANCE",
    "detect",
    "register_detector",
]

# 数值一致性的相对容差：1%
VALUE_TOLERANCE = 0.01

# 第七个检查器：`semantic_check`（语义检查）。
#
# 它**故意不注册在默认注册表里**，因为它不是确定性的——要用模型，
# 而且它的召回率取决于提示词写得好不好。
# 它的评测在 `agent/eval_semantic.py`，单独一套指标。
# 这样分层是有意为之：先量出确定性检查器的天花板，剩下的缺口才是语义检查要补的。
SEMANTIC_DETECTOR = "semantic_check"


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


# --------------------------------------------------------------------------- #
# 六个检查器，各自独立
# --------------------------------------------------------------------------- #


def oracle_differential(ctx: DetectorContext) -> Iterable[Finding]:
    """拿报告原值重算，比对判定等级。**只有差分审计能做这件事。**"""
    for item, metric in ctx.items():
        oracle = judge_metric(metric, ctx.sex, ctx.age, float(ctx.report_values[item.code]))
        oracle_verdict = str(oracle["final_verdict"])
        if oracle_verdict != item.severity:
            yield Finding(
                detector="oracle_differential",
                target=item.code,
                location="items[].severity",
                message=f"{metric.name} 的判定与独立重算的结果不一致",
                expected=oracle_verdict,
                observed=item.severity,
            )


def value_consistency(ctx: DetectorContext) -> Iterable[Finding]:
    """数值抄错。带相对容差，容忍正常的显示取整。"""
    for item, metric in ctx.items():
        true_value = float(ctx.report_values[item.code])
        if abs(item.value - true_value) > max(1e-9, abs(true_value) * VALUE_TOLERANCE):
            yield Finding(
                detector="value_consistency",
                target=item.code,
                location="items[].value",
                message=f"{metric.name} 的数值与报告原值不一致",
                expected=f"{true_value:g}",
                observed=f"{item.value:g}",
            )


def unit_consistency(ctx: DetectorContext) -> Iterable[Finding]:
    """单位错误，以及"产物里出现了指标清单之外的条目"。"""
    by_code = ctx.by_code
    for item in ctx.artifact.items:
        metric = by_code.get(item.code)
        if metric is None:
            yield Finding(
                detector="unit_consistency",
                target=item.code,
                location="items[].code",
                message="产物里出现了指标清单之外的指标",
                expected="指标清单内的指标",
                observed=item.code,
            )
            continue
        if item.unit != metric.unit:
            yield Finding(
                detector="unit_consistency",
                target=item.code,
                location="items[].unit",
                message=f"{metric.name} 的单位与指标清单不一致",
                expected=metric.unit,
                observed=item.unit,
            )


def citation_existence(ctx: DetectorContext) -> Iterable[Finding]:
    """引用编造：依据必须落在合法引用集合内。"""
    known = ctx.known_citations
    for item, metric in ctx.items():
        for cite in item.citations:
            if cite not in known:
                yield Finding(
                    detector="citation_existence",
                    target=item.code,
                    location="items[].citations",
                    message=f"{metric.name} 的依据不在合法引用集合内",
                    expected="合法引用集合内的文号",
                    observed=cite,
                )


def advice_contract(ctx: DetectorContext) -> Iterable[Finding]:
    """内部矛盾：判定等级与建议动作必须匹配。

    「判定 → 应有建议」这张表**由场景插件提供**，本体不写死——
    体检是"危急→建议立即就医"，信贷是"拒绝→不予放款"。
    """
    advice_map = ctx.advice_by_verdict
    for item, metric in ctx.items():
        expected_advice = advice_map.get(item.severity)
        if expected_advice is not None and item.advice != expected_advice:
            yield Finding(
                detector="advice_contract",
                target=item.code,
                location="items[].advice",
                message=f"{metric.name} 的判定等级与建议动作不一致",
                expected=expected_advice,
                observed=item.advice,
            )


def safety_terms(ctx: DetectorContext) -> Iterable[Finding]:
    """安全越界：出现本场景的禁用表达。

    **词表由场景插件提供**，本体不写死——这是"本体不认识行业"的直接体现。
    这一层只能抓露骨写法；改写型越界要靠语义检查（那部分的提示词也是插件件）。
    """
    terms = ctx.safety_terms
    for item, metric in ctx.items():
        hit_terms = [term for term in terms if term in item.explanation]
        if hit_terms:
            yield Finding(
                detector="safety_terms",
                target=item.code,
                location="items[].explanation",
                message=f"{metric.name} 的解释里出现禁用表达",
                expected="只做科普与就医准备",
                observed="、".join(hit_terms),
            )


# --------------------------------------------------------------------------- #
# 默认注册表
# --------------------------------------------------------------------------- #

DEFAULT_REGISTRY = DetectorRegistry(
    [
        DetectorSpec(
            name="oracle_differential",
            kinds=("missed_critical", "downgraded", "wrong_sex_threshold"),
            run=oracle_differential,
            description="拿报告原值独立重算，比对判定等级",
            requires_report_values=True,
        ),
        DetectorSpec(
            name="value_consistency",
            kinds=("value_mismatch",),
            run=value_consistency,
            description="产物里的数值与报告原值不一致（带 1% 容差）",
            requires_report_values=True,
        ),
        DetectorSpec(
            name="unit_consistency",
            kinds=("unit_mismatch",),
            run=unit_consistency,
            description="单位与指标清单不一致，或出现清单外的指标",
        ),
        DetectorSpec(
            name="citation_existence",
            kinds=("fabricated_citation",),
            run=citation_existence,
            description="依据不在合法引用集合内（引用编造）",
        ),
        DetectorSpec(
            name="advice_contract",
            kinds=("internal_contradiction",),
            run=advice_contract,
            description="判定等级与建议动作互相矛盾",
        ),
        DetectorSpec(
            name="safety_terms",
            kinds=("safety_violation",),
            run=safety_terms,
            description="解释里出现禁用表达（露骨诊断口吻或用药建议）",
        ),
    ]
)

# 向后兼容的**快照**视图：从注册表推出，不再手工维护第二份。
#
# ⚠️ 注意这是一个**快照**，不是活清单。
# 如果谁写了 `from audit.detect import DETECTORS`，他手里就是导入那一刻的元组，
# 之后注册的新检查器**不会**出现在他手里——这是 Python 的绑定语义，不是 bug。
#
# 所以要拿"现在有哪些检查器"，请用 `detector_names()` 或 `DEFAULT_REGISTRY.names()`。
# 这个模块级常量只为了让老代码和报告还能照常读，**不要依赖它是实时的。**
# （这个坑真实存在过：注册表测试里断言 `DETECTORS` 含新检查器，结果失败。）
DETECTORS: tuple[str, ...] = DEFAULT_REGISTRY.names()

DETECTOR_TO_KINDS: Mapping[str, tuple[str, ...]] = {
    **DEFAULT_REGISTRY.kind_map(),
    SEMANTIC_DETECTOR: ("safety_paraphrase",),
}


def detector_names() -> tuple[str, ...]:
    """**活清单**：现在注册了哪些检查器。"""
    return DEFAULT_REGISTRY.names()


def detector_kind_map() -> Mapping[str, tuple[str, ...]]:
    """**活清单**：检查器 -> 它负责的缺陷类型。"""
    return {**DEFAULT_REGISTRY.kind_map(), SEMANTIC_DETECTOR: ("safety_paraphrase",)}


def register_detector(spec: DetectorSpec, *, replace: bool = False) -> DetectorSpec:
    """注册一个新检查器。**扩展点就在这里。**

    注册之后 `detect()` 自动带上它，核心调度代码不用改。

    要读"现在有哪些"，请用 `detector_names()`；`DETECTORS` 是导入时的快照。
    """
    return DEFAULT_REGISTRY.register(spec, replace=replace)


def detect(
    artifact: Artifact,
    report_values: Mapping[str, float],
    sex: str,
    age: int,
    metrics: Sequence[Metric],
    registry: DetectorRegistry | None = None,
    plugin: Any = None,
) -> tuple[Finding, ...]:
    """对一份产物跑全部已注册的检查器。

    需要报告原值：这是**差分审计的前提**——审计器必须能看到源数据，
    否则它只能核对"话有没有依据"，无法核对"判定对不对"。

    `plugin` 是场景插件清单：本体需要的行业知识（安全词表、判定→建议映射）
    从它读。**传不同的 plugin、跑同一套检查器** —— 这就是本体独立的样子。
    """
    ctx = DetectorContext(
        artifact=artifact,
        report_values=report_values,
        sex=sex,
        age=age,
        metrics=metrics,
        plugin=plugin,
    )
    active = registry or DEFAULT_REGISTRY
    return tuple(active.run_all(ctx))
