"""读取并校验一个"判定域"（domain）配置。

一个域 = 一套规则 + 判定需要的事实字段 + 转人工条件。
**规则是 YAML 数据，不是代码**，所以换一个域只需要换一个文件，引擎一行不改。

加载即校验：任何格式错误、字段拼写错误、悬空引用，都在 `load_domain` 阶段报错，
而不是等到"算出错误金额"的时候才发现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import yaml

from engine.expr import CompiledExpression, ExpressionError, compile_expression

__all__ = [
    "Domain",
    "DomainError",
    "Escalation",
    "Fact",
    "Fee",
    "Rule",
    "load_domain",
]

# 由引擎在运行时提供、不需要写在 facts 里的字段：
#   missing_any_fact —— 关键事实是否缺失
#   fee_amount       —— 本引擎算出的费用（用于"金额超阈值转人工"这类条件）
ENGINE_PROVIDED_NAMES = frozenset({"missing_any_fact", "fee_amount"})

_ALLOWED_FACT_TYPES = frozenset({"number", "enum", "bool"})
# 引擎自带的一组判定值，只作为**默认值**。
# 判定值是"域的语言"：费用域说 refundable，医学域说 critical。
# 所以域可以自己声明 `verdicts`，引擎不该替它规定词汇表。
_DEFAULT_VERDICTS = frozenset(
    {
        "refundable",
        "not_refundable",
        "needs_review",
        "eligible",
        "not_eligible",
    }
)
_ALLOWED_FEE_FORMS = frozenset({"fixed", "rate_of_amount", "table_lookup"})


class DomainError(ValueError):
    """判定域配置不合法。消息里一定带上"哪个文件的哪条规则"。"""


@dataclass(frozen=True)
class Fact:
    """判定需要的一项事实。缺任何一项都不许猜，只能转人工。"""

    name: str
    type: str
    unit: str | None = None
    values: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    boundaries: tuple[float, ...] = ()
    integer: bool = False

    def generation_range(self) -> tuple[float, float]:
        """取值范围，交给评测集生成器使用。"""
        assert self.minimum is not None and self.maximum is not None
        return (self.minimum, self.maximum)


@dataclass(frozen=True)
class Fee:
    """费用计算方式。只允许三种形式，不允许任意公式——任意公式就不可审计了。"""

    form: str
    amount: Decimal | None = None
    rate: Decimal | None = None
    base_fact: str | None = None
    key_fact: str | None = None
    table: Mapping[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    id: str
    when: str
    verdict: str
    cite: str
    priority: int
    fee: Fee | None
    expression: CompiledExpression


@dataclass(frozen=True)
class Escalation:
    when: str
    reason: str
    expression: CompiledExpression


@dataclass(frozen=True)
class Domain:
    name: str
    version: str
    note: str
    facts: Mapping[str, Fact]
    rules: tuple[Rule, ...]
    escalations: tuple[Escalation, ...]
    source: Path
    verdicts: frozenset[str] = _DEFAULT_VERDICTS
    """本域允许出现的判定值。域可以自己声明，否则用引擎默认的一组。"""

    default_verdict: str | None = None
    """**没有规则命中时的结论**。这是域相关的语义：

    - 费用域：没有规则命中说明规则集有缺口 → 保持为 None，引擎会转人工、明说"规则缺口"
    - 医学分级域：没有规则命中恰恰是**最理想的情况**（所有指标都正常）→ 声明为 "normal"

    引擎不替域猜这个含义，必须由域显式声明。
    """

    critical_verdicts: frozenset[str] = frozenset()
    """必须有人接住的结论（例如医学域的 critical）。

    与 missing_any_fact 一样，这是**引擎的内置不变量**而不是可配置的策略：
    声明在这里的结论，一定会在结果里被标成 requires_human_review。
    """

    @property
    def fact_names(self) -> frozenset[str]:
        return frozenset(self.facts)

    @property
    def allowed_expression_names(self) -> frozenset[str]:
        """条件表达式里允许出现的字段 = 声明的事实 + 引擎提供的字段。"""
        return self.fact_names | ENGINE_PROVIDED_NAMES

    def facts_of_type(self, fact_type: str) -> tuple[Fact, ...]:
        return tuple(fact for fact in self.facts.values() if fact.type == fact_type)


# --------------------------------------------------------------------------- #
# 加载与校验
# --------------------------------------------------------------------------- #


def load_domain(path: str | Path) -> Domain:
    """从 YAML 文件加载一个判定域。"""
    path = Path(path)
    if not path.is_file():
        raise DomainError(f"找不到判定域文件：{path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DomainError(f"{path} 不是合法的 YAML：{exc}") from exc
    if not isinstance(raw, dict):
        raise DomainError(f"{path} 的顶层必须是一个映射（mapping）")
    return _build_domain(raw, path)


def _build_domain(raw: Mapping[str, Any], source: Path) -> Domain:
    where = source.as_posix()

    for key in ("domain", "version", "note", "facts", "rules", "escalate"):
        if key not in raw:
            raise DomainError(f"{where} 缺少顶层字段：{key}")

    verdicts = _build_verdicts(raw, where)
    facts = _build_facts(raw["facts"], where)
    allowed = frozenset(facts) | ENGINE_PROVIDED_NAMES

    rules = _build_rules(raw["rules"], allowed, facts, verdicts, where)
    escalations = _build_escalations(raw["escalate"], allowed, where)
    default_verdict = _build_default_verdict(raw, verdicts, where)
    critical_verdicts = _build_critical_verdicts(raw, verdicts, where)

    return Domain(
        name=str(raw["domain"]),
        version=str(raw["version"]),
        note=str(raw["note"]),
        facts=facts,
        rules=rules,
        escalations=escalations,
        source=source,
        verdicts=verdicts,
        default_verdict=default_verdict,
        critical_verdicts=critical_verdicts,
    )


def _build_verdicts(raw: Mapping[str, Any], where: str) -> frozenset[str]:
    """判定值是"域的语言"。域不声明就用引擎默认的那一组。"""
    declared = raw.get("verdicts")
    if declared is None:
        return _DEFAULT_VERDICTS
    if not isinstance(declared, list) or not declared:
        raise DomainError(f"{where}: verdicts 必须是非空列表，或整个字段省略以使用引擎默认值")
    values = frozenset(str(item) for item in declared)
    if len(values) != len(declared):
        raise DomainError(f"{where}: verdicts 里有重复项")
    return values


def _build_default_verdict(
    raw: Mapping[str, Any], verdicts: frozenset[str], where: str
) -> str | None:
    declared = raw.get("default_verdict")
    if declared is None:
        return None
    value = str(declared)
    if value not in verdicts:
        raise DomainError(
            f"{where}: default_verdict {value!r} 不在本域声明的判定值里"
            f"（{', '.join(sorted(verdicts))}）"
        )
    return value


def _build_critical_verdicts(
    raw: Mapping[str, Any], verdicts: frozenset[str], where: str
) -> frozenset[str]:
    declared = raw.get("critical_verdicts", []) or []
    if not isinstance(declared, list):
        raise DomainError(f"{where}: critical_verdicts 必须是列表")
    values = frozenset(str(item) for item in declared)
    unknown = values - verdicts
    if unknown:
        raise DomainError(
            f"{where}: critical_verdicts 里有未声明的判定值：{', '.join(sorted(unknown))}"
        )
    return values


def _build_facts(raw_facts: Any, where: str) -> dict[str, Fact]:
    if not isinstance(raw_facts, list) or not raw_facts:
        raise DomainError(f"{where}: facts 必须是非空列表")

    facts: dict[str, Fact] = {}
    for index, item in enumerate(raw_facts):
        if not isinstance(item, dict) or "name" not in item or "type" not in item:
            raise DomainError(f"{where}: facts[{index}] 必须包含 name 与 type")

        name = str(item["name"])
        fact_type = str(item["type"])
        if name in facts:
            raise DomainError(f"{where}: 事实字段名重复：{name}")
        if fact_type not in _ALLOWED_FACT_TYPES:
            raise DomainError(
                f"{where}: 字段 {name} 的类型 {fact_type!r} 不支持"
                f"（允许：{', '.join(sorted(_ALLOWED_FACT_TYPES))}）"
            )

        minimum = item.get("minimum")
        maximum = item.get("maximum")
        boundaries = tuple(float(v) for v in item.get("boundaries", []) or [])
        integer = bool(item.get("integer", False))

        if fact_type == "number":
            # 强制要求取值范围：否则评测集生成器不知道该生成什么，会退化成"随便编"
            if minimum is None or maximum is None:
                raise DomainError(
                    f"{where}: 数值字段 {name} 必须给出 minimum 与 maximum，"
                    "评测集生成器靠它确定取值范围"
                )
            if float(minimum) >= float(maximum):
                raise DomainError(f"{where}: 数值字段 {name} 的 minimum 必须小于 maximum")
            for value in boundaries:
                if not (float(minimum) <= value <= float(maximum)):
                    raise DomainError(
                        f"{where}: 字段 {name} 的边界值 {value} 超出范围"
                        f" [{minimum}, {maximum}]"
                    )
            if integer:
                for value in boundaries:
                    if value != int(value):
                        raise DomainError(f"{where}: 整数字段 {name} 的边界值 {value} 不是整数")

        values: tuple[str, ...] = ()
        if fact_type == "enum":
            raw_values = item.get("values")
            if not isinstance(raw_values, list) or not raw_values:
                raise DomainError(f"{where}: 枚举字段 {name} 必须给出非空的 values")
            values = tuple(str(v) for v in raw_values)
            if len(set(values)) != len(values):
                raise DomainError(f"{where}: 枚举字段 {name} 的 values 有重复")

        facts[name] = Fact(
            name=name,
            type=fact_type,
            unit=item.get("unit"),
            values=values,
            minimum=float(minimum) if minimum is not None else None,
            maximum=float(maximum) if maximum is not None else None,
            boundaries=boundaries,
            integer=integer,
        )
    return facts


def _build_rules(
    raw_rules: Any,
    allowed_names: frozenset[str],
    facts: Mapping[str, Fact],
    verdicts: frozenset[str],
    where: str,
) -> tuple[Rule, ...]:
    if not isinstance(raw_rules, list) or not raw_rules:
        raise DomainError(f"{where}: rules 必须是非空列表")

    rules: list[Rule] = []
    seen_ids: set[str] = set()

    for index, item in enumerate(raw_rules):
        if not isinstance(item, dict):
            raise DomainError(f"{where}: rules[{index}] 必须是一个映射")
        rule_id = str(item.get("id", "")).strip()
        if not rule_id:
            raise DomainError(f"{where}: rules[{index}] 缺少 id")
        if rule_id in seen_ids:
            raise DomainError(f"{where}: 规则 id 重复：{rule_id}")
        seen_ids.add(rule_id)

        for key in ("when", "verdict", "cite", "priority"):
            if key not in item:
                raise DomainError(f"{where}: 规则 {rule_id} 缺少字段 {key}")

        verdict = str(item["verdict"])
        if verdict not in verdicts:
            raise DomainError(
                f"{where}: 规则 {rule_id} 的判定值 {verdict!r} 不在本域声明的判定值里"
                f"（{', '.join(sorted(verdicts))}）"
            )

        cite = str(item["cite"]).strip()
        if not cite:
            raise DomainError(f"{where}: 规则 {rule_id} 的 cite 不能为空——没有依据的判定视为缺陷")

        when = str(item["when"])
        try:
            expression = compile_expression(when, allowed_names)
        except ExpressionError as exc:
            raise DomainError(f"{where}: 规则 {rule_id} 的条件不合法：{exc}") from exc

        try:
            priority = int(item["priority"])
        except (TypeError, ValueError) as exc:
            raise DomainError(f"{where}: 规则 {rule_id} 的 priority 必须是整数") from exc

        fee = _build_fee(item.get("fee"), rule_id, facts, where)
        rules.append(
            Rule(
                id=rule_id,
                when=when,
                verdict=verdict,
                cite=cite,
                priority=priority,
                fee=fee,
                expression=expression,
            )
        )
    return tuple(rules)


def _build_fee(raw_fee: Any, rule_id: str, facts: Mapping[str, Fact], where: str) -> Fee | None:
    """费用是可选字段：像"学位资格审核"这类域根本没有金额。"""
    if raw_fee is None:
        return None
    if not isinstance(raw_fee, dict):
        raise DomainError(f"{where}: 规则 {rule_id} 的 fee 必须是一个映射")

    form = str(raw_fee.get("form", ""))
    if form not in _ALLOWED_FEE_FORMS:
        raise DomainError(
            f"{where}: 规则 {rule_id} 的 fee.form {form!r} 不支持"
            f"（允许：{', '.join(sorted(_ALLOWED_FEE_FORMS))}）"
        )

    if form == "fixed":
        if "amount" not in raw_fee:
            raise DomainError(f"{where}: 规则 {rule_id} 的 fixed 费用必须给出 amount")
        return Fee(form=form, amount=_to_decimal(raw_fee["amount"], where, rule_id, "amount"))

    if form == "rate_of_amount":
        if "rate" not in raw_fee:
            raise DomainError(f"{where}: 规则 {rule_id} 的 rate_of_amount 必须给出 rate")
        base_fact = str(raw_fee.get("base_fact", "order_amount"))
        if base_fact not in facts:
            raise DomainError(
                f"{where}: 规则 {rule_id} 的 base_fact {base_fact!r} 不是已声明的事实字段"
            )
        if facts[base_fact].type != "number":
            raise DomainError(f"{where}: 规则 {rule_id} 的 base_fact {base_fact!r} 必须是数值字段")
        return Fee(
            form=form,
            rate=_to_decimal(raw_fee["rate"], where, rule_id, "rate"),
            base_fact=base_fact,
        )

    # table_lookup
    key_fact = str(raw_fee.get("key_fact", ""))
    if key_fact not in facts:
        raise DomainError(
            f"{where}: 规则 {rule_id} 的 table_lookup 必须给出已声明的 key_fact"
        )
    raw_table = raw_fee.get("table")
    if not isinstance(raw_table, dict) or not raw_table:
        raise DomainError(f"{where}: 规则 {rule_id} 的 table_lookup 必须给出非空 table")
    table = {
        str(key): _to_decimal(value, where, rule_id, f"table[{key}]")
        for key, value in raw_table.items()
    }
    return Fee(form=form, key_fact=key_fact, table=table)


def _build_escalations(
    raw_escalations: Any, allowed_names: frozenset[str], where: str
) -> tuple[Escalation, ...]:
    if not isinstance(raw_escalations, list) or not raw_escalations:
        raise DomainError(f"{where}: escalate 必须是非空列表——转人工条件是安全边界的最后一道闸")

    escalations: list[Escalation] = []
    for index, item in enumerate(raw_escalations):
        if not isinstance(item, dict) or "when" not in item or "reason" not in item:
            raise DomainError(f"{where}: escalate[{index}] 必须同时给出 when 与 reason")
        when = str(item["when"])
        reason = str(item["reason"]).strip()
        if not reason:
            raise DomainError(f"{where}: escalate[{index}] 的 reason 不能为空（要写清为什么转人工）")
        try:
            expression = compile_expression(when, allowed_names)
        except ExpressionError as exc:
            raise DomainError(f"{where}: escalate[{index}] 的条件不合法：{exc}") from exc
        escalations.append(Escalation(when=when, reason=reason, expression=expression))
    return tuple(escalations)


def _to_decimal(value: Any, where: str, rule_id: str, field_name: str) -> Decimal:
    """把配置里的数字转成 Decimal。

    注意：**不经过 float**。`Decimal(str(0.05))` 得到精确的 Decimal('0.05')，
    而 `Decimal(0.05)` 会得到 0.05000000000000000277...——涉及金额时这是原则问题。
    """
    if isinstance(value, bool) or value is None:
        raise DomainError(f"{where}: 规则 {rule_id} 的 {field_name} 必须是数字")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(
            f"{where}: 规则 {rule_id} 的 {field_name} 不是合法数字：{value!r}"
        ) from exc
