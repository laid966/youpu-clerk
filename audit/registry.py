"""检查器注册表：让「加一个检查器」不用改核心代码。

## 为什么需要这个（这是扩展能力的第一个接缝）

第一版的 `detect()` 是一个大函数：6 个检查器的逻辑**全部内联在同一个 for 循环里**，
还共用一套局部变量（`by_code` / `true_value` / `known`）。

那是横向扩展的硬阻塞：

- 想加第 7 个检查器 → 必须改核心文件、读懂那个循环、小心不要踩到别人的局部变量
- 没有一个地方能回答「我们一共有哪些检查器」
- 检查器与缺陷类型的对应关系（`DETECTOR_TO_KINDS`）要**手工维护第二份**，迟早对不上

现在改成注册表：

| 好处 | 说明 |
|---|---|
| 加检查器不改核心 | 写一个函数 + `register`，`detect()` 的调度逻辑一行不动 |
| 单一事实来源 | 检查器清单、它能抓什么缺陷，都从注册表推出，不再手工同步 |
| 可以被测试证明 | `tests/test_registry.py` 里真的注册一个新检查器，**不碰 `detect.py`** |

## 大规模部署为什么卡在这一层

部署时要面对的是「**每个场景的检查点不一样**」：

- 体检解读要查参考区间、单位、判定等级
- 信贷审批要查利率口径、还款期、资格条件
- 理赔说明要查条款引用、免赔额、时效

如果每接一个场景都要改核心代码，那就永远只能做一个场景。
**注册表把场景差异落到数据与插件里**——这是"能不能横向扩展"的分界线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Sequence

from audit.artifact import Artifact, ArtifactItem
from audit.pipeline import Metric

if TYPE_CHECKING:  # pragma: no cover — 只给类型检查用，避免与 detect.py 循环导入
    from audit.detect import Finding

__all__ = [
    "Detector",
    "DetectorContext",
    "DetectorRegistry",
    "DetectorSpec",
]

#: 检查器函数签名：接收统一上下文，产出若干条发现。
#:
#: 刻意设计成**整个产物**级别（而不是单条明细级别）：
#: 有些检查需要跨明细才能判（比如"汇总与明细不一致"、"两份依据互相矛盾"）。
#: 只想逐条判的检查器可以用 `ctx.items()` 这个便捷方法。
Detector = Callable[["DetectorContext"], Iterable["Finding"]]


@dataclass(frozen=True)
class DetectorContext:
    """检查器能看到的全部输入。

    **为什么用上下文对象而不是一串参数**：原版 `detect()` 有 5 个参数，
    加一个检查器要用的字段就得改所有调用方。上下文对象让加字段变成加属性。
    """

    artifact: Artifact
    report_values: Mapping[str, float]
    sex: str
    age: int
    metrics: Sequence[Metric]
    plugin: Any = None
    """该场景的插件清单（`plugin.spec.PluginSpec`）。

    **这就是"本体不认识行业"的落点**：本体需要的行业知识（安全词表、判定→建议映射）
    全部从这里读。为 `None` 时退回核心默认常量（医学演示的那套），
    这样旧调用方一行都不用改。"""

    extra_citations: tuple[str, ...] = ()
    """调用方补充的合法引用（例如**知识库的 chunk id**）。

    用途：RAG 产出的解读，它的"依据"应当来自知识库里的 chunk。
    但 `audit/` **不许 import `rag/`**（会形成循环依赖），
    所以由**调用方**把集合扩大后传进来——审计器仍然只依赖
    "一个合法的引用集合"这个概念，而不依赖知识库怎么实现。

    这也让 `KnowledgeBase.citation_ids()` 从死代码变成真正被用上的一环。
    """

    @property
    def safety_terms(self) -> tuple[str, ...]:
        """本场景的禁用表达表。由插件提供，本体不写死。"""
        if self.plugin is not None:
            return tuple(self.plugin.safety_terms)
        from audit.artifact import SAFETY_TERMS

        return tuple(SAFETY_TERMS)

    @property
    def advice_by_verdict(self) -> Mapping[str, str]:
        """本场景的「判定 → 应有建议动作」映射。由插件提供，本体不写死。"""
        if self.plugin is not None:
            return dict(self.plugin.advice_by_verdict)
        from audit.artifact import ADVICE_BY_SEVERITY

        return dict(ADVICE_BY_SEVERITY)

    @property
    def by_code(self) -> Mapping[str, Metric]:
        return {metric.code: metric for metric in self.metrics}

    @property
    def known_citations(self) -> frozenset[str]:
        from audit.pipeline import known_citations

        return frozenset(known_citations(self.metrics))

    def items(self) -> Iterable[tuple[ArtifactItem, Metric]]:
        """逐条产出 (明细, 指标定义)，**自动跳过指标清单之外的条目**。

        这一条很重要：原版循环用 `continue` 跳过未知指标，
        但那是因为所有检查都在同一个循环里。拆成独立检查器之后，
        每个检查器都必须自己防住未知指标，否则 `report_values[code]` 会 KeyError。
        把这件事收进 `items()`，新检查器就不用各自重复防一遍。
        """
        by_code = self.by_code
        for item in self.artifact.items:
            metric = by_code.get(item.code)
            if metric is not None:
                yield item, metric

    def unknown_codes(self) -> tuple[str, ...]:
        """产物里出现了指标清单之外的条目。"""
        by_code = self.by_code
        return tuple(item.code for item in self.artifact.items if item.code not in by_code)


@dataclass(frozen=True)
class DetectorSpec:
    name: str
    kinds: tuple[str, ...]
    """它负责哪些缺陷类型。**评测配对要用**：只有"检查器 + 指标"都对上才算抓到。

    写 `()` 表示它不在注入式基准的覆盖范围内（比如它抓的缺陷还没法注入）。
    """
    run: Detector
    description: str
    scope: str = "deterministic"
    """`deterministic` 免费且可复现；`semantic` 要用模型、效果取决于提示词。"""
    requires_report_values: bool = False
    """是否需要原始数据。

    这是**差分审计与普通"事实核查"的分界线**：需要原值的检查器才能发现
    「判定错了但全文自洽、引用也都真实」这类缺陷。
    不需要原值的检查器可以跨场景复用（比如纯文本规范检查）。
    """

    def __post_init__(self) -> None:
        if self.scope not in ("deterministic", "semantic"):
            raise ValueError(f"scope 只能是 deterministic 或 semantic，收到 {self.scope!r}")
        if not self.description.strip():
            raise ValueError(f"检查器 {self.name} 必须写 description——它防的是什么？")


@dataclass
class DetectorRegistry:
    """检查器清单。注册即生效，`detect()` 不需要知道具体有哪些。"""

    _specs: dict[str, DetectorSpec] = field(default_factory=dict)

    def __init__(self, specs: Sequence[DetectorSpec] = ()) -> None:
        object.__setattr__(self, "_specs", {})
        for spec in specs:
            self.register(spec)

    # ---- 读 ----

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def all(self) -> tuple[DetectorSpec, ...]:
        return tuple(self._specs.values())

    def get(self, name: str) -> DetectorSpec:
        if name not in self._specs:
            raise KeyError(f"没有这个检查器：{name}（现有：{', '.join(self._specs)}）")
        return self._specs[name]

    def kinds_for(self, name: str) -> tuple[str, ...]:
        return self.get(name).kinds

    def kind_map(self) -> dict[str, tuple[str, ...]]:
        """检查器 -> 缺陷类型。**从注册表推出，不再手工维护。**"""
        return {spec.name: spec.kinds for spec in self._specs.values()}

    def detector_for_kind(self, kind: str) -> str | None:
        for spec in self._specs.values():
            if kind in spec.kinds:
                return spec.name
        return None

    # ---- 写 ----

    def register(self, spec: DetectorSpec, *, replace: bool = False) -> DetectorSpec:
        if spec.name in self._specs and not replace:
            raise ValueError(
                f"检查器 {spec.name} 已经注册过了。"
                "要覆盖它请显式传 replace=True——**静默覆盖会让旧行为无声消失。**"
            )
        self._specs[spec.name] = spec
        return spec

    def unregister(self, name: str) -> None:
        self._specs.pop(name, None)

    # ---- 跑 ----

    def run_all(self, ctx: DetectorContext) -> tuple[Any, ...]:
        findings: list[Any] = []
        for spec in self._specs.values():
            findings.extend(spec.run(ctx))
        return tuple(findings)

    def run_one(self, name: str, ctx: DetectorContext) -> tuple[Any, ...]:
        return tuple(self.get(name).run(ctx))

    def describe(self) -> str:
        lines = [
            f"已注册 {len(self._specs)} 个检查器：",
            "",
            "| 检查器 | 类型 | 负责的缺陷 | 需要原值 | 说明 |",
            "|---|---|---|---|---|",
        ]
        for spec in self._specs.values():
            kinds = "、".join(f"`{kind}`" for kind in spec.kinds) or "（不在基准覆盖内）"
            needs = "是" if spec.requires_report_values else "否"
            lines.append(
                f"| `{spec.name}` | {spec.scope} | {kinds} | {needs} | {spec.description} |"
            )
        return "\n".join(lines)
