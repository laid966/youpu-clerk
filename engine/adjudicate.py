"""判定引擎：给定事实，算出结论与金额。

这是本项目的**正确性核心**，也是"模型不许碰算术"这句话的落地点。

设计上的四条硬规矩：

1. **金额只用 Decimal 算，且四舍五入到分**。全程不碰 float——
   `0.1 + 0.2 != 0.3` 这种事在金额上是事故，不是知识点。
2. **缺字段不算**。规则需要某个字段而这次没给，这条规则直接不可用并转人工，
   绝不拿缺省值硬算一个"看起来对"的金额。
3. **同优先级冲突不许偷偷选一个**。两条同优先级规则给出不同结论时，
   这是规则集的缺陷，运行时必须转人工，而不是按字典序随便挑一个。
4. **没有规则覆盖时明确说"不知道"**。宁可承认规则有缺口，也不编一个结论。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from engine.domain import Domain, Fee, Rule

__all__ = ["AdjudicationError", "Judgement", "adjudicate"]

# 金额的精度：分
MONEY_QUANTUM = Decimal("0.01")


class AdjudicationError(ValueError):
    """输入的事实不合法（字段名不认识、类型不对）。这类问题必须立刻炸，不能悄悄吞掉。"""


@dataclass(frozen=True)
class MatchedRule:
    id: str
    verdict: str
    cite: str
    priority: int
    fee_amount: Decimal | None


@dataclass(frozen=True)
class Judgement:
    """一次判定的完整结果。字段刻意保留"过程"，因为判定类业务必须可审计。"""

    domain: str
    final_verdict: str
    computed_verdict: str | None
    fee_amount: Decimal | None
    winning_rule_id: str | None
    matched_rules: tuple[MatchedRule, ...]
    citations: tuple[str, ...]
    escalated: bool
    requires_human_review: bool
    escalate_reasons: tuple[str, ...]
    missing_facts: tuple[str, ...]
    out_of_range_facts: tuple[str, ...]
    skipped_rules: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """转成可直接写进评测集 JSON 的形式（Decimal → 字符串，避免精度损失）。"""
        return {
            "domain": self.domain,
            "final_verdict": self.final_verdict,
            "computed_verdict": self.computed_verdict,
            "fee_amount": None if self.fee_amount is None else str(self.fee_amount),
            "winning_rule_id": self.winning_rule_id,
            "matched_rules": [
                {
                    "id": m.id,
                    "verdict": m.verdict,
                    "priority": m.priority,
                    "fee_amount": None if m.fee_amount is None else str(m.fee_amount),
                    "cite": m.cite,
                }
                for m in self.matched_rules
            ],
            "citations": list(self.citations),
            "escalated": self.escalated,
            "requires_human_review": self.requires_human_review,
            "escalate_reasons": list(self.escalate_reasons),
            "missing_facts": list(self.missing_facts),
            "out_of_range_facts": list(self.out_of_range_facts),
            "skipped_rules": list(self.skipped_rules),
        }


def adjudicate(domain: Domain, facts: Mapping[str, Any]) -> Judgement:
    """对一组事实做判定。同一个输入永远得到同一个输出。"""
    normalized, missing, out_of_range = _normalize_facts(domain, facts)

    matched: list[MatchedRule] = []
    skipped: list[str] = []

    for rule in domain.rules:
        reason = _why_unusable(rule, domain, normalized)
        if reason is not None:
            skipped.append(f"{rule.id}: {reason}")
            continue
        if rule.expression.evaluate(normalized):
            matched.append(_to_matched(rule, domain, normalized))

    # 优先级从高到低；同优先级按 id 稳定排序，保证结果可复现
    matched.sort(key=lambda item: (-item.priority, item.id))

    reasons: list[str] = []
    notes_missing = missing

    # 缺字段 / 取值越界：一律转人工
    if missing:
        reasons.append(f"关键信息缺失（{', '.join(missing)}），不得猜测")
    if out_of_range:
        reasons.append(f"取值超出已知范围（{', '.join(out_of_range)}），需人工确认")

    if matched:
        winner = matched[0]
        # 只比较"结论"是否真的不同：**必须只比 (verdict, fee_amount)**。
        # 曾经这里是 `item != winner`，而 MatchedRule 里含 id，
        # 于是任何同优先级的第二条规则都会被误判成冲突——
        # 学位审核域里 U-002 与 U-003 结论完全相同（都是 not_eligible、都无金额），
        # 却被报了 1172 次"优先级冲突"。
        winner_outcome = (winner.verdict, winner.fee_amount)
        conflicting = [
            item
            for item in matched[1:]
            if item.priority == winner.priority
            and (item.verdict, item.fee_amount) != winner_outcome
        ]
        if conflicting:
            # 规则集缺陷：同优先级、不同结论。运行时唯一安全的做法是交给人。
            reasons.append(
                f"规则优先级冲突：{winner.id} 与 {conflicting[0].id} 同为优先级 "
                f"{winner.priority} 但结论不同，需人工裁决"
            )
            computed_verdict: str | None = winner.verdict
            fee_amount = winner.fee_amount
            winning_rule_id = None
        else:
            computed_verdict = winner.verdict
            fee_amount = winner.fee_amount
            winning_rule_id = winner.id
    else:
        if domain.default_verdict is not None:
            # 域声明了"默认结论"：没有规则命中就是这个结论。
            # 例如医学分级域里"所有指标都在参考区间内"是最理想的情况，
            # 而不是规则集有缺口。这个含义由域声明，引擎不替它猜。
            computed_verdict = domain.default_verdict
            fee_amount = None
            winning_rule_id = None
        else:
            computed_verdict = None
            fee_amount = None
            winning_rule_id = None
            reasons.append("没有任何规则覆盖该情形（规则缺口），不得编造结论")

    # 转人工条件的求值上下文：事实 + 引擎提供的两个字段
    escalate_context: dict[str, Any] = {
        **normalized,
        "missing_any_fact": bool(missing),
        "fee_amount": fee_amount,
    }
    evaluable_names = set(escalate_context)
    for escalation in domain.escalations:
        # 和规则一样，转人工条件也要先做依赖检查。
        # 例如 `used_segments > total_segments`：这两个字段没提供时它不是"假"，
        # 而是"无法判断"。此时静默跳过是安全的——因为"关键信息缺失"本身就是
        # 一条一定会命中的转人工条件，结论同样会走向 needs_review。
        if not escalation.expression.used_names <= evaluable_names:
            continue
        if escalation.expression.evaluate(escalate_context):
            reasons.append(escalation.reason)

    escalated = bool(reasons)
    if escalated:
        final_verdict = "needs_review"
    elif computed_verdict is None:  # pragma: no cover — 上面的"规则缺口"已经兜住了
        final_verdict = "needs_review"
    else:
        final_verdict = computed_verdict

    # "必须有人接住"这件事由域声明，引擎来保证。
    # 注意：即使被 escalate 覆盖成 needs_review，只要规则本来给出的是危急结论，
    # 也一样要进人工队列——不能因为另一个原因转了人工，就把危急这个事实漏掉。
    requires_human_review = bool(
        escalated
        or final_verdict in domain.critical_verdicts
        or computed_verdict in domain.critical_verdicts
    )

    return Judgement(
        domain=domain.name,
        final_verdict=final_verdict,
        computed_verdict=computed_verdict,
        fee_amount=fee_amount,
        winning_rule_id=winning_rule_id,
        matched_rules=tuple(matched),
        citations=tuple(dict.fromkeys(item.cite for item in matched)),
        escalated=escalated,
        requires_human_review=requires_human_review,
        escalate_reasons=tuple(dict.fromkeys(reasons)),
        missing_facts=tuple(notes_missing),
        out_of_range_facts=tuple(out_of_range),
        skipped_rules=tuple(skipped),
    )


# --------------------------------------------------------------------------- #
# 事实校验
# --------------------------------------------------------------------------- #


def _normalize_facts(
    domain: Domain, facts: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str], list[str]]:
    """校验并归一化事实，返回（可用事实, 缺失字段, 越界字段）。"""
    unknown = sorted(set(facts) - set(domain.facts))
    if unknown:
        # 不认识的字段说明调用方和规则集已经脱节了，这属于程序缺陷，必须立刻暴露
        raise AdjudicationError(
            f"提供了判定域 {domain.name} 未声明的字段：{', '.join(unknown)}"
        )

    normalized: dict[str, Any] = {}
    missing: list[str] = []
    out_of_range: list[str] = []

    for name, fact in domain.facts.items():
        if name not in facts or facts[name] is None:
            missing.append(name)
            continue

        value = facts[name]

        if fact.type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                raise AdjudicationError(f"字段 {name} 应该是数字，实际是 {type(value).__name__}")
            number = float(value)
            if fact.integer and number != int(number):
                raise AdjudicationError(f"字段 {name} 应该是整数，实际是 {number}")
            if fact.minimum is not None and number < fact.minimum:
                out_of_range.append(f"{name}={number} 低于下限 {fact.minimum}")
            if fact.maximum is not None and number > fact.maximum:
                out_of_range.append(f"{name}={number} 高于上限 {fact.maximum}")
            normalized[name] = int(number) if fact.integer else number
            continue

        if fact.type == "bool":
            if not isinstance(value, bool):
                raise AdjudicationError(f"字段 {name} 应该是布尔值，实际是 {type(value).__name__}")
            normalized[name] = value
            continue

        # enum
        text = str(value)
        if text not in fact.values:
            out_of_range.append(f"{name}={text} 不在允许取值 {list(fact.values)} 内")
        normalized[name] = text

    return normalized, missing, out_of_range


def _why_unusable(rule: Rule, domain: Domain, available: Mapping[str, Any]) -> str | None:
    """判断一条规则在当前事实下能不能用。返回 None 表示可用，否则返回不可用的原因。"""
    needed = set(rule.expression.used_names)
    materialized = set(available) | {"missing_any_fact", "fee_amount"}
    absent = sorted(needed - materialized)
    if absent:
        return f"缺少字段 {', '.join(absent)}"

    if rule.fee is None:
        return None

    fee = rule.fee
    if fee.form == "fixed":
        return None

    if fee.form == "rate_of_amount":
        assert fee.base_fact is not None
        if fee.base_fact not in available:
            return f"缺少金额基数 {fee.base_fact}"
        return None

    # table_lookup
    assert fee.key_fact is not None
    if fee.key_fact not in available:
        return f"缺少查表键 {fee.key_fact}"
    key_value = str(available[fee.key_fact])
    if key_value not in fee.table:
        return f"查表缺少键 {key_value}"
    return None


# --------------------------------------------------------------------------- #
# 金额计算
# --------------------------------------------------------------------------- #


def _to_matched(rule: Rule, domain: Domain, facts: Mapping[str, Any]) -> MatchedRule:
    return MatchedRule(
        id=rule.id,
        verdict=rule.verdict,
        cite=rule.cite,
        priority=rule.priority,
        fee_amount=_compute_fee(rule.fee, facts),
    )


def _compute_fee(fee: Fee | None, facts: Mapping[str, Any]) -> Decimal | None:
    if fee is None:
        return None

    if fee.form == "fixed":
        assert fee.amount is not None
        return _round_money(fee.amount)

    if fee.form == "rate_of_amount":
        assert fee.rate is not None and fee.base_fact is not None
        base = Decimal(str(facts[fee.base_fact]))
        return _round_money(base * fee.rate)

    # table_lookup：表里存的是费率
    assert fee.key_fact is not None
    rate = fee.table[str(facts[fee.key_fact])]
    base = Decimal(str(facts.get("order_amount", 0)))
    return _round_money(base * rate)


def _round_money(value: Decimal) -> Decimal:
    """四舍五入到分。用 ROUND_HALF_UP 是因为财务惯例如此，而不是银行家舍入。"""
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
