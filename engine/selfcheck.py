"""规则自检：在跑评测之前，先问规则集自己有没有毛病。

规则是数据，数据会写错。这个模块用"大量随机取样 + 反例"的方式找四类问题：

1. **同优先级冲突**（错误级）：两条同优先级规则给出不同结论，同时命中。
   这不是"选一个"的问题，是规则集有缺陷——运行时引擎会转人工，但你必须知道它存在。
2. **规则缺口**（警告）：某些输入没有任何规则覆盖。本项目**故意不写兜底规则**，
   所以缺口是预期内的现象；但缺口比例太高说明规则集不完整。
3. **永不命中的规则**（警告）：条件写错了，或者写了一条永远不会触发的规则。
4. **被完全遮蔽的规则**（警告）：这条规则会命中，但在所有命中的样本里都被更高优先级压住，
   等于白写。

它不做逻辑证明——做的是**反例搜索**。所以报告里的措辞是
"在 N 个样本中（未）发现"，而不是"保证没有"。这个区别很重要，写进报告里。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping

from engine.adjudicate import adjudicate
from engine.domain import Domain
from engine.sample_gen import DEFAULT_SEED, iterate_fact_samples

__all__ = ["SelfCheckReport", "run_selfcheck"]

DEFAULT_SAMPLES = 2000


@dataclass(frozen=True)
class SelfCheckReport:
    domain: str
    samples: int
    seed: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    uncovered: int = 0
    coverage_rate: float = 0.0
    matched_counts: Mapping[str, int] = field(default_factory=dict)
    win_counts: Mapping[str, int] = field(default_factory=dict)
    verdict_counts: Mapping[str, int] = field(default_factory=dict)
    escalate_counts: Mapping[str, int] = field(default_factory=dict)
    never_matched: tuple[str, ...] = ()
    never_won: tuple[str, ...] = ()
    gap_examples: tuple[Mapping[str, Any], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"# 规则自检报告 · `{self.domain}`")
        lines.append("")
        lines.append(
            f"- 取样数量：**{self.samples}**（固定 seed `{self.seed}`，结果可复现）"
        )
        lines.append(f"- 结论：{'✅ 未发现错误级问题' if self.ok else '❌ 发现错误级问题'}")
        lines.append(f"- 规则覆盖：**{self.coverage_rate:.1%}**（{self.samples - self.uncovered} / {self.samples} 个样本至少命中一条规则）")
        lines.append("")

        lines.append("> 说明：本自检是**反例搜索**，不是逻辑证明。")
        lines.append(f"> 措辞严格为「在 {self.samples} 个样本中未发现」，不代表数学上不存在。")
        lines.append("")

        lines.append("## 错误级问题")
        lines.append("")
        if self.errors:
            for item in self.errors:
                lines.append(f"- ❌ {item}")
        else:
            lines.append("- 无")
        lines.append("")

        lines.append("## 警告")
        lines.append("")
        if self.warnings:
            for item in self.warnings:
                lines.append(f"- ⚠️ {item}")
        else:
            lines.append("- 无")
        lines.append("")

        lines.append("## 规则命中与胜出次数")
        lines.append("")
        lines.append("| 规则 | 命中次数 | 生效（胜出）次数 | 备注 |")
        lines.append("|---|---|---|---|")
        for rule_id in self.matched_counts:
            matched = self.matched_counts[rule_id]
            won = self.win_counts.get(rule_id, 0)
            note = ""
            if matched == 0:
                note = "从未命中"
            elif won == 0:
                note = "被更高优先级完全遮蔽"
            lines.append(f"| `{rule_id}` | {matched} | {won} | {note} |")
        lines.append("")

        lines.append("## 最终结论分布")
        lines.append("")
        lines.append("| 结论 | 次数 |")
        lines.append("|---|---|")
        for verdict, count in sorted(self.verdict_counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{verdict}` | {count} |")
        lines.append("")

        lines.append("## 转人工原因分布")
        lines.append("")
        lines.append("| 原因 | 次数 |")
        lines.append("|---|---|")
        for reason, count in sorted(self.escalate_counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {reason} | {count} |")
        lines.append("")

        if self.gap_examples:
            lines.append("## 规则缺口举例（前 3 条）")
            lines.append("")
            for index, facts in enumerate(self.gap_examples, start=1):
                rendered = ", ".join(f"{key}={value}" for key, value in sorted(facts.items()))
                lines.append(f"{index}. {rendered}")
            lines.append("")

        return "\n".join(lines)


def run_selfcheck(
    domain: Domain, samples: int = DEFAULT_SAMPLES, seed: int = DEFAULT_SEED
) -> SelfCheckReport:
    matched_counts: Counter[str] = Counter({rule.id: 0 for rule in domain.rules})
    win_counts: Counter[str] = Counter({rule.id: 0 for rule in domain.rules})
    verdict_counts: Counter[str] = Counter()
    escalate_counts: Counter[str] = Counter()

    conflicts: list[str] = []
    uncovered = 0
    gap_examples: list[Mapping[str, Any]] = []
    seen_conflict_keys: set[str] = set()

    checked = 0
    for template, facts in iterate_fact_samples(domain, samples, seed):
        checked += 1
        # 自检要能看穿"缺字段"的情况，但也要有足够多的完整样本，这里保留模板原样
        result = adjudicate(domain, facts)

        for match in result.matched_rules:
            matched_counts[match.id] += 1
        if result.winning_rule_id:
            win_counts[result.winning_rule_id] += 1

        verdict_counts[result.final_verdict] += 1
        for reason in result.escalate_reasons:
            escalate_counts[reason] += 1

        if not result.matched_rules:
            uncovered += 1
            if len(gap_examples) < 3:
                gap_examples.append(dict(facts))
            continue

        # 同优先级冲突：只看真正"并列第一"的两条
        top_priority = max(item.priority for item in result.matched_rules)
        top = [item for item in result.matched_rules if item.priority == top_priority]
        if len({(item.verdict, item.fee_amount) for item in top}) > 1:
            key = "-".join(sorted(item.id for item in top))
            if key not in seen_conflict_keys:
                seen_conflict_keys.add(key)
                ids = ", ".join(sorted(item.id for item in top))
                rendered = ", ".join(
                    f"{name}={facts[name]}" for name in sorted(facts)
                )
                conflicts.append(
                    f"同优先级（{top_priority}）冲突：规则 {ids} 同时命中但结论不同。"
                    f"反例：{rendered}"
                )

    never_matched = tuple(sorted(rule_id for rule_id, count in matched_counts.items() if count == 0))
    never_won = tuple(
        sorted(
            rule_id
            for rule_id, count in matched_counts.items()
            if count > 0 and win_counts.get(rule_id, 0) == 0
        )
    )

    warnings: list[str] = []
    if uncovered:
        warnings.append(
            f"在 {checked} 个样本中有 {uncovered} 个（{uncovered / max(checked, 1):.1%}）"
            "没有任何规则覆盖。本项目故意不写兜底规则，所以缺口是可见的、而不是被掩盖的；"
            "但比例过高说明规则集不完整。"
        )
    if never_matched:
        warnings.append(
            "以下规则在样本中从未命中，可能是条件写错，也可能是永远不会触发的死规则："
            + ", ".join(never_matched)
        )
    if never_won:
        warnings.append(
            "以下规则会命中，但在所有命中样本里都被更高优先级完全遮蔽（等于白写）："
            + ", ".join(never_won)
        )

    errors: list[str] = list(conflicts)

    return SelfCheckReport(
        domain=domain.name,
        samples=checked,
        seed=seed,
        errors=tuple(errors),
        warnings=tuple(warnings),
        conflicts=tuple(conflicts),
        uncovered=uncovered,
        coverage_rate=(checked - uncovered) / checked if checked else 0.0,
        matched_counts=dict(matched_counts),
        win_counts=dict(win_counts),
        verdict_counts=dict(verdict_counts),
        escalate_counts=dict(escalate_counts),
        never_matched=never_matched,
        never_won=never_won,
        gap_examples=tuple(gap_examples),
    )
