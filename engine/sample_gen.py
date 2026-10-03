"""评测用例自动生成。

## 为什么这件事很重要

招聘方点名扣分的一种情况是："准确率提升 15%，来自 20 条自测数据、无基线"。
手写用例永远写不了几条，而且写的人会不自觉地只写自己实现覆盖到的情形。

本项目因为**规则是形式化的**，所以标准答案可以被程序算出来，
于是评测集可以自动生成到**上千条**，并且天然包含边界情况。

## 一个必须说清楚的方法论问题

引擎既是"被测对象"又在这里充当"标准答案"，这是不是自欺欺人？不是，但必须分清两层：

| 层次 | 谁保证它的正确性 |
|---|---|
| **引擎算得对不对** | `tests/test_adjudicate.py` 里**手工复算**的金额断言（数量少但精确） |
| **agent 层能不能稳定复现引擎的判定** | 这里生成的 1000 条用例（数量大、覆盖广） |

也就是说：这 1000 条保证的是"**模型层没有把已经算对的东西搞错**"，
它们**不能**用来证明规则本身正确。两层的证据不能互相替代——
把这两句话写清楚，比多跑 1000 条更能说明问题。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

from engine.adjudicate import adjudicate
from engine.domain import Domain, Fact

__all__ = [
    "GeneratedCase",
    "TEMPLATES",
    "generate_cases",
    "iterate_fact_samples",
    "write_dataset",
]

TEMPLATES = (
    "threshold_sweep",
    "rule_positive",
    "random",
    "boundary",
    "enum_sweep",
    "bool_sweep",
    "missing_fact",
    "extreme",
)

# 只给"随机类"模板配权重；threshold_sweep 是系统性扫边界，不参与权重分配。
DEFAULT_WEIGHTS: Mapping[str, float] = {
    "random": 0.30,  # 像真实流量那样随机
    "boundary": 0.30,  # 多个数值字段同时贴边，专抓字段之间的交互
    "enum_sweep": 0.10,  # 每个枚举取值都走到
    "bool_sweep": 0.10,  # 每个布尔字段的两种取值都走到
    "missing_fact": 0.08,  # 缺字段必须转人工，而不是硬算
    "extreme": 0.12,  # 取极值，压出金额阈值转人工这类路径
}

DEFAULT_SEED = 20261003


@dataclass(frozen=True)
class GeneratedCase:
    id: str
    template: str
    facts: Mapping[str, Any]
    expected: Mapping[str, Any]

    def to_json_line(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "domain": self.expected["domain"],
                "template": self.template,
                "facts": dict(self.facts),
                "expected": dict(self.expected),
            },
            ensure_ascii=False,
            sort_keys=False,
        )


# --------------------------------------------------------------------------- #
# 取值层面：怎么造一个事实字典
# --------------------------------------------------------------------------- #


def _epsilon(fact: Fact) -> float:
    """边界扰动步长：整数字段用 1，其余用 0.01。

    为什么需要它：`hours_before_departure >= 168` 这种条件，
    只测 168 是测不出"把 >= 写成 >"的。必须同时测 167.99 和 168.01。
    """
    return 1.0 if fact.integer else 0.01


def _clamp(fact: Fact, value: float) -> float:
    assert fact.minimum is not None and fact.maximum is not None
    return min(max(value, fact.minimum), fact.maximum)


def _boundary_candidates(fact: Fact) -> list[float]:
    assert fact.minimum is not None and fact.maximum is not None
    step = _epsilon(fact)
    raw: list[float] = []
    for boundary in fact.boundaries or (fact.minimum, fact.maximum):
        for offset in (0.0, -step, step):
            raw.append(_clamp(fact, boundary + offset))
    if fact.integer:
        return sorted({float(int(round(value))) for value in raw})
    return sorted({round(value, 4) for value in raw})


def _random_value(rng: random.Random, fact: Fact) -> Any:
    if fact.type == "bool":
        return rng.choice([True, False])
    if fact.type == "enum":
        return rng.choice(list(fact.values))
    assert fact.minimum is not None and fact.maximum is not None
    if fact.integer:
        return rng.randint(int(fact.minimum), int(fact.maximum))
    return round(rng.uniform(fact.minimum, fact.maximum), 4)


def _extreme_value(rng: random.Random, fact: Fact) -> Any:
    if fact.type == "bool":
        return rng.choice([True, False])
    if fact.type == "enum":
        return rng.choice(list(fact.values))
    assert fact.minimum is not None and fact.maximum is not None
    return float(fact.minimum) if rng.random() < 0.5 else float(fact.maximum)


def _full_facts(rng: random.Random, domain: Domain, value_picker) -> dict[str, Any]:
    return {name: value_picker(rng, fact) for name, fact in domain.facts.items()}


def _threshold_sweep(
    domain: Domain, rng: random.Random
) -> Iterator[tuple[str, dict[str, Any]]]:
    """系统性地扫过每个数值字段的每个阈值：阈值本身、略低于、略高于。

    这一段是**刻意非随机**的。如果靠随机取样去撞边界，
    "刚好差一点"的取值就可能永远不出现，而 `>=` 误写成 `>` 这种 bug
    恰恰只有靠这些取值才能发现——覆盖率不能靠运气。
    """
    seen: set[str] = set()
    for fact in domain.facts_of_type("number"):
        assert fact.minimum is not None and fact.maximum is not None
        boundaries = fact.boundaries or (fact.minimum, fact.maximum)
        step = _epsilon(fact)

        for boundary in boundaries:
            for offset in (-step, 0.0, step):
                value = _clamp(fact, boundary + offset)
                value = float(int(round(value))) if fact.integer else round(value, 4)

                key = f"{fact.name}={value}"
                if key in seen:
                    continue
                seen.add(key)

                facts = _full_facts(rng, domain, _random_value)
                facts[fact.name] = value
                yield "threshold_sweep", facts


def _sample_for_template(
    rng: random.Random, domain: Domain, template: str
) -> dict[str, Any]:
    numeric = domain.facts_of_type("number")

    if template == "random":
        return _full_facts(rng, domain, _random_value)

    if template == "extreme":
        return _full_facts(rng, domain, _extreme_value)

    if template == "boundary":
        facts = _full_facts(rng, domain, _random_value)
        if not numeric:
            return facts
        chosen = rng.sample(numeric, k=min(len(numeric), rng.choice([1, 1, 2])))
        for fact in chosen:
            facts[fact.name] = rng.choice(_boundary_candidates(fact))
        return facts

    if template == "enum_sweep":
        facts = _full_facts(rng, domain, _random_value)
        enums = domain.facts_of_type("enum")
        if enums:
            fact = rng.choice(enums)
            facts[fact.name] = rng.choice(list(fact.values))
        return facts

    if template == "bool_sweep":
        facts = _full_facts(rng, domain, _random_value)
        bools = domain.facts_of_type("bool")
        if bools:
            fact = rng.choice(bools)
            facts[fact.name] = rng.choice([True, False])
        return facts

    if template == "missing_fact":
        facts = _full_facts(rng, domain, _random_value)
        if facts:
            del facts[rng.choice(sorted(facts))]
        return facts

    raise ValueError(f"未知模板：{template}")


# --------------------------------------------------------------------------- #
# 用例层面
# --------------------------------------------------------------------------- #


def _rule_positive_samples(
    domain: Domain, rng: random.Random, budget: int = 3000
) -> Iterator[tuple[str, dict[str, Any]]]:
    """为每条规则定向找至少一个"正例"。

    为什么需要这一步：像
        `total_credits >= 60 and core_credits >= 36 and ... and campus == "main"`
    这种多条件与（AND）的规则，在均匀随机取样下命中概率可能只有千分之一量级。
    实测就是这么发生的：生成 50 条时 `eligible` 一次都没出现——
    于是"规则算得对"这件事在数据集里根本没有正例可查。

    做法：一次预算内跑一批随机样本（只跑一遍，所有规则共用），
    为每条规则记下第一个命中它的样本。这样既省算力又不失完备性。
    """
    first_hit: dict[str, dict[str, Any]] = {}
    pending = {rule.id for rule in domain.rules}

    for _ in range(budget):
        if not pending:
            break
        facts = _full_facts(rng, domain, _random_value)
        matched = {match.id for match in adjudicate(domain, facts).matched_rules}
        for rule_id in pending & matched:
            first_hit[rule_id] = facts
        pending -= matched

    for rule in domain.rules:
        if rule.id in first_hit:
            yield "rule_positive", first_hit[rule.id]


def iterate_fact_samples(
    domain: Domain, count: int, seed: int = DEFAULT_SEED
) -> Iterator[tuple[str, dict[str, Any]]]:
    """产出 (模板名, 事实字典)。同一 seed 必然产出同一序列。

    顺序是有意为之：**先跑完备的阈值扫描，再补每条规则的正例，最后才随机**。
    这样即使 count 很小（比如只生成 100 条），边界与正例也已经覆盖到了。
    """
    if count <= 0:
        return

    rng = random.Random(seed)
    produced = 0

    for template, facts in _threshold_sweep(domain, rng):
        if produced >= count:
            return
        yield template, facts
        produced += 1

    for template, facts in _rule_positive_samples(domain, rng):
        if produced >= count:
            return
        yield template, facts
        produced += 1

    remaining = count - produced
    if remaining <= 0:
        return

    # 按权重分配剩余额度，再把余数补齐，保证总数精确等于 count
    raw = {name: remaining * weight for name, weight in DEFAULT_WEIGHTS.items()}
    allocated = {name: int(value) for name, value in raw.items()}
    remainder = remaining - sum(allocated.values())
    for name, _ in sorted(raw.items(), key=lambda item: (-(item[1] - int(item[1])), item[0])):
        if remainder <= 0:
            break
        allocated[name] += 1
        remainder -= 1

    per_template = {
        name: [_sample_for_template(rng, domain, name) for _ in range(allocated[name])]
        for name in DEFAULT_WEIGHTS
    }

    # 交错输出：抽查数据集开头几条时能同时看到各种模板
    cursors = {name: 0 for name in DEFAULT_WEIGHTS}
    emitted = 0
    while emitted < remaining:
        for name in DEFAULT_WEIGHTS:
            if cursors[name] < len(per_template[name]):
                yield name, per_template[name][cursors[name]]
                cursors[name] += 1
                emitted += 1
                if emitted >= remaining:
                    break


def generate_cases(
    domain: Domain, count: int = 1000, seed: int = DEFAULT_SEED
) -> list[GeneratedCase]:
    cases: list[GeneratedCase] = []
    for index, (template, facts) in enumerate(iterate_fact_samples(domain, count, seed), start=1):
        expected = adjudicate(domain, facts).to_dict()
        cases.append(
            GeneratedCase(
                id=f"case-{index:04d}",
                template=template,
                facts=facts,
                expected=expected,
            )
        )
    return cases


def write_dataset(
    cases: list[GeneratedCase],
    out_path: str | Path,
    sample_out: str | Path | None = None,
    sample_size: int = 20,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            handle.write(case.to_json_line() + "\n")

    if sample_out is not None:
        sample_out = Path(sample_out)
        sample_out.parent.mkdir(parents=True, exist_ok=True)
        sample_out.write_text(render_sample(cases, sample_size), encoding="utf-8")

    return out_path


def render_sample(cases: list[GeneratedCase], size: int) -> str:
    """把前若干条渲染成人能读的 Markdown，方便你抽查生成器是不是合理。"""
    lines = [
        "# 评测用例抽样（人读版）",
        "",
        "> 这个文件是给人抽查用的。完整数据集在 `eval/dataset.jsonl`（JSON Lines，程序读）。",
        "> 生成器会按固定 seed 产出完全相同的用例，所以它是可复现的。",
        "",
        f"共 {len(cases)} 条，下面展示前 {min(size, len(cases))} 条。",
        "",
    ]
    for case in cases[:size]:
        expected = case.expected
        lines.append(f"## {case.id} · 模板 `{case.template}`")
        lines.append("")
        lines.append("**输入事实**")
        lines.append("")
        lines.append("| 字段 | 取值 |")
        lines.append("|---|---|")
        for key in sorted(case.facts):
            lines.append(f"| `{key}` | {case.facts[key]} |")
        lines.append("")
        lines.append("**期望结果**")
        lines.append("")
        lines.append(f"- 最终结论：`{expected['final_verdict']}`")
        lines.append(f"- 规则算出的结论：`{expected['computed_verdict']}`")
        lines.append(f"- 费用：`{expected['fee_amount']}`")
        lines.append(f"- 命中并生效的规则：`{expected['winning_rule_id']}`")
        lines.append(f"- 是否转人工：`{expected['escalated']}`")
        if expected["escalate_reasons"]:
            lines.append("- 转人工原因：")
            for reason in expected["escalate_reasons"]:
                lines.append(f"  - {reason}")
        lines.append("")
    return "\n".join(lines)
