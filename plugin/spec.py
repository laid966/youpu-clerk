"""插件清单：读、校验、发现。

清单（`plugins/<名字>/plugin.yaml`）是**唯一声明一个场景的地方**。
部署时要回答"我们上线了哪些场景、各用哪版规则和提示词"，答案就在这些清单里。

## 校验原则

**清单错就大声报错，不做静默兜底。** 一个字段名写错、一个路径不存在，
如果不报错而是悄悄用默认值，那"场景 A 和场景 B 其实用了同一套词表"这种事
可以瞒很久——**配置类的静默兜底是最贵的一类 bug。**
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

__all__ = [
    "MANIFEST_NAME",
    "PluginError",
    "PluginSpec",
    "discover_plugins",
    "load_plugin",
    "load_prompts",
]

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "plugins"
MANIFEST_NAME = "plugin.yaml"

#: 判定阈值附近的"误差"默认量级：1%。
#: 场景不同、误差来源也不同，所以这个值**由插件声明**：
#: 医学是检验批间差异，信贷是利率四舍五入/口径误差，理赔是金额计算精度。
#:
#: 与 `audit/robustness.py` 的 `DEFAULT_TOLERANCE` 是同一个数——
#: 那个是"没给插件时"的兜底，两处一致由测试守着（同 SAFETY_TERMS 的做法）。
DEFAULT_MEASUREMENT_TOLERANCE = 0.01

_REQUIRED = (
    "name",
    "title",
    "version",
    "summary",
    "metrics",
    "domain_glob",
    "advice_by_verdict",
    "verdict_ladder",
)


class PluginError(RuntimeError):
    """插件清单有问题。**一定是响亮地报错，不猜。**"""


@dataclass(frozen=True)
class PluginSpec:
    name: str
    title: str
    version: str
    summary: str
    root: Path
    metrics: Path
    domain_glob: str
    knowledge: tuple[Path, ...] = ()
    prompts: Path | None = None
    guardrails: Path | None = None
    safety_terms: tuple[str, ...] = ()
    advice_by_verdict: Mapping[str, str] = None  # type: ignore[assignment]
    benign_templates: tuple[str, ...] = ()
    citation_catalogue: tuple[str, ...] = ()
    verdict_ladder: tuple[str, ...] = ()
    """判定等级**由轻到重**的顺序。

    为什么必须显式声明：引擎里的 `verdicts` 是 **frozenset**，顺序会丢，
    而"哪个方向更严重"是有业务含义的（体检 normal→critical、信贷 approved→rejected）。
    **顺序属于场景知识，所以放在插件里，不放进本体。**
    """
    verdict_source_field: str = "severity"
    measurement_tolerance: float = DEFAULT_MEASUREMENT_TOLERANCE
    """判定阈值附近的**误差量级**，用于判定稳健性审计（"这个结论离临界值多近"）。

    场景不同、来源也不同：医学是检验批间差异，信贷是四舍五入/口径误差。
    **所以它属于场景知识，由插件声明，不写进本体。**
    """
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.advice_by_verdict is None:
            object.__setattr__(self, "advice_by_verdict", {})

    @property
    def relative_root(self) -> str:
        try:
            return str(self.root.relative_to(ROOT))
        except ValueError:  # pragma: no cover — 只在临时目录场景发生
            return str(self.root)

    @property
    def has_prompt(self) -> bool:
        return self.prompts is not None and self.prompts.is_file()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "version": self.version,
            "summary": self.summary,
            "root": self.relative_root,
            "metrics": _rel(self.metrics),
            "domain_glob": self.domain_glob,
            "knowledge": [_rel(path) for path in self.knowledge],
            "prompts": _rel(self.prompts) if self.prompts else None,
            "guardrails": _rel(self.guardrails) if self.guardrails else None,
            "safety_terms": list(self.safety_terms),
            "advice_by_verdict": dict(self.advice_by_verdict),
            "benign_templates": list(self.benign_templates),
            "citation_catalogue": list(self.citation_catalogue),
            "verdict_ladder": list(self.verdict_ladder),
            "verdict_source_field": self.verdict_source_field,
            "measurement_tolerance": self.measurement_tolerance,
            "notes": list(self.notes),
        }

    def describe(self) -> str:
        lines = [
            f"# 插件 `{self.name}` · {self.title}（v{self.version}）",
            "",
            self.summary,
            "",
            "| 项 | 值 |",
            "|---|---|",
            f"| 目录 | `{self.relative_root}/` |",
            f"| 字段清单 | `{_rel(self.metrics)}` |",
            f"| 判定规则 | `{self.domain_glob}` |",
            f"| 知识库 | {'、'.join('`' + _rel(p) + '`' for p in self.knowledge) or '（未配）'} |",
            f"| 提示词 | `{_rel(self.prompts)}` |" if self.prompts else "| 提示词 | （未配，用核心默认） |",
            f"| 安全词表 | {'、'.join(self.safety_terms) or '（空）'} |",
            f"| 判定→建议 | {'、'.join(f'{k}→{v}' for k, v in self.advice_by_verdict.items()) or '（空）'} |",
            f"| 判定等级（轻→重） | {' → '.join(self.verdict_ladder) or '（未声明）'} |",
            f"| 稳健性误差量级 | ±{self.measurement_tolerance:.2%} |",
            f"| 合法引用 | {'、'.join(self.citation_catalogue) or '（空，引用检查将始终报错）'} |",
        ]
        if self.notes:
            lines += ["", "## 说明"]
            lines += [f"- {note}" for note in self.notes]
        return "\n".join(lines)


def _rel(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:  # pragma: no cover
        return str(path)


def _resolve(raw: Any, field: str) -> Path:
    """清单里的路径**一律相对于仓库根**。

    为什么不是相对于插件目录：场景内容不一定住在插件目录里。
    比如 `med-checkup` 直接引用仓库既有的 `domain/med-metrics.yaml`，
    它的规则集是历史资产，不该为了插件化而搬来搬去。
    """
    path = Path(str(raw))
    resolved = (path if path.is_absolute() else (ROOT / path)).resolve()
    if not resolved.is_file():
        raise PluginError(
            f"插件清单里的 `{field}` 指向了不存在的文件：{resolved}"
            f"（清单里的路径一律相对仓库根 {ROOT}）"
        )
    return resolved


def _tolerance(raw: object) -> float:
    """校验插件声明的误差量级。**错值直接报错，不兜底。**"""
    if raw is None:
        return DEFAULT_MEASUREMENT_TOLERANCE
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise PluginError(f"measurement_tolerance 必须是数字，收到 {raw!r}") from exc
    if not 0 < value <= 0.5:
        raise PluginError(
            f"measurement_tolerance 必须在 (0, 0.5] 之间，收到 {value}。"
            "超过 50% 就不是「误差」而是「换了个数」，那样算出来的脆弱率没有意义。"
        )
    return value


def load_plugin(path: str | Path) -> PluginSpec:
    """读一个插件的清单并校验。`path` 可以是目录，也可以是 plugin.yaml。"""
    candidate = Path(path)
    manifest = candidate / MANIFEST_NAME if candidate.is_dir() else candidate
    if not manifest.is_file():
        raise PluginError(f"找不到插件清单：{manifest}")

    raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise PluginError(f"{manifest} 的顶层必须是一个映射")

    missing = [field for field in _REQUIRED if not raw.get(field)]
    if missing:
        raise PluginError(f"{manifest} 缺少必需字段：{', '.join(missing)}")

    root = manifest.parent
    advice = raw.get("advice_by_verdict") or {}
    if not isinstance(advice, Mapping):
        raise PluginError(f"{manifest} 的 advice_by_verdict 必须是映射（判定 → 建议动作）")
    if not advice:
        raise PluginError(
            f"{manifest} 必须声明 advice_by_verdict —— "
            "没有它，`advice_contract`（判定与建议是否自相矛盾）这个检查器无法工作"
        )

    knowledge_raw = raw.get("knowledge") or []
    if isinstance(knowledge_raw, str):
        knowledge_raw = [knowledge_raw]

    prompts_raw = raw.get("prompts")
    guardrails_raw = raw.get("guardrails")

    spec = PluginSpec(
        name=str(raw["name"]),
        title=str(raw["title"]),
        version=str(raw["version"]),
        summary=str(raw["summary"]),
        root=root,
        metrics=_resolve(raw["metrics"], "metrics"),
        domain_glob=str(raw["domain_glob"]),
        knowledge=tuple(_resolve(item, "knowledge") for item in knowledge_raw),
        prompts=_resolve(prompts_raw, "prompts") if prompts_raw else None,
        guardrails=_resolve(guardrails_raw, "guardrails") if guardrails_raw else None,
        safety_terms=tuple(str(term) for term in (raw.get("safety_terms") or ())),
        advice_by_verdict={str(k): str(v) for k, v in advice.items()},
        benign_templates=tuple(str(item) for item in (raw.get("benign_templates") or ())),
        citation_catalogue=tuple(str(item) for item in (raw.get("citation_catalogue") or ())),
        verdict_ladder=tuple(str(item) for item in (raw.get("verdict_ladder") or ())),
        verdict_source_field=str(raw.get("verdict_source_field") or "severity"),
        measurement_tolerance=_tolerance(raw.get("measurement_tolerance")),
        notes=tuple(str(item) for item in (raw.get("notes") or ())),
    )

    # 目录名和清单里的 name 必须一致：不一致时"我改了哪个"会变得很难查。
    if root.name != spec.name:
        raise PluginError(
            f"清单里的 name={spec.name!r} 与目录名 {root.name!r} 不一致。"
            "两者必须相同——不然出问题时你会不知道该看哪个目录。"
        )
    return spec


def discover_plugins(directory: str | Path = PLUGINS_DIR) -> tuple[PluginSpec, ...]:
    """扫描 `plugins/` 下所有插件，按名字排序。"""
    directory = Path(directory)
    if not directory.is_dir():
        return ()
    specs: list[PluginSpec] = []
    for entry in sorted(directory.iterdir()):
        if entry.is_dir() and (entry / MANIFEST_NAME).is_file():
            specs.append(load_plugin(entry))
    return tuple(specs)


def find_plugin(name: str, directory: str | Path = PLUGINS_DIR) -> PluginSpec:
    for spec in discover_plugins(directory):
        if spec.name == name:
            return spec
    available = ", ".join(spec.name for spec in discover_plugins(directory)) or "（没有）"
    raise PluginError(f"没有这个插件：{name}（现有：{available}）")


def load_prompts(plugin: PluginSpec) -> dict[str, str]:
    """加载插件自己的提示词模块。

    插件的 `prompts.py` 只要暴露 `_REGISTRY`（版本名 → 提示词文本）和
    `CURRENT_VERSION` 即可，和核心的 `agent/prompts.py` 同一个约定。
    **约定不变，内容随插件走** —— 这就是"提示词也作为插件"。
    """
    if not plugin.has_prompt:
        return {}
    assert plugin.prompts is not None
    spec = importlib.util.spec_from_file_location(
        f"plugin_{plugin.name}_prompts", plugin.prompts
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise PluginError(f"无法加载 {plugin.prompts}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    registry = getattr(module, "_REGISTRY", None)
    if not isinstance(registry, dict) or not registry:
        raise PluginError(
            f"{plugin.prompts} 必须暴露一个非空的 `_REGISTRY`（版本名 → 提示词文本）"
        )
    missing = [field for field in ("{text}",) if not any(field in text for text in registry.values())]
    if missing:
        raise PluginError(
            f"{plugin.prompts} 里的提示词缺少占位符 {missing[0]} —— 填充逻辑在核心，是固定接口"
        )
    return {str(k): str(v) for k, v in registry.items()}
