"""判定引擎测试。**金额全部是手工算出来的**，不是从引擎输出反抄的。

这是整个项目最关键的一份测试：如果这里的数字错了，那么后面 1000 条自动生成的
评测用例都在校验一个错误的标准答案，整个"可验证"的主张就是空的。

所以规则是：每一条金额断言，都必须能用纸笔复算一遍。
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from engine.adjudicate import AdjudicationError, adjudicate
from engine.domain import load_domain

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def airline():
    return load_domain(ROOT / "domain" / "airline-fare-sample" / "domain.yaml")


@pytest.fixture(scope="module")
def university():
    return load_domain(ROOT / "domain" / "university-credit-sample" / "domain.yaml")


def airline_facts(**overrides):
    facts = {
        "order_amount": 15000,
        "cabin_class": "economy",
        "fare_type": "standard",
        "hours_before_departure": 200,
        "discount_rate": 0.4,
        "is_through_ticket": False,
        "is_noshow": False,
        "used_segments": 0,
        "total_segments": 1,
    }
    facts.update(overrides)
    return facts


def _inline_domain(tmp_path: Path, rules, facts, escalate):
    data = {
        "domain": "inline-test",
        "version": "0.1.0",
        "note": "测试用",
        "facts": facts,
        "rules": rules,
        "escalate": escalate,
    }
    path = tmp_path / "domain.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return load_domain(path)


# --------------------------------------------------------------------------- #
# 金额：逐条手工复算
# --------------------------------------------------------------------------- #


def test_generic_tier_7_days(airline):
    """15000 × 5% = 750.00"""
    result = adjudicate(airline, airline_facts())

    assert result.final_verdict == "refundable"
    assert result.fee_amount == Decimal("750.00")
    assert result.winning_rule_id == "R-001"
    assert result.escalated is False


def test_14_day_rule_beats_generic_tier(airline):
    """400 小时命中 R-001(5%) 与 R-011(2%)，优先级更高者胜：15000 × 2% = 300.00"""
    result = adjudicate(airline, airline_facts(hours_before_departure=400))

    assert result.winning_rule_id == "R-011"
    assert result.fee_amount == Decimal("300.00")
    assert {m.id for m in result.matched_rules} == {"R-001", "R-011"}


def test_business_cabin_overrides_generic_tier(airline):
    """100 小时命中 R-002(15%) 与 R-006(公务舱 5%)，后者优先：15000 × 5% = 750.00

    如果优先级机制失效，这里会算成 2250.00——正好是 3 倍的差异，所以这个用例很值钱。
    """
    result = adjudicate(
        airline, airline_facts(cabin_class="business", hours_before_departure=100)
    )

    assert result.winning_rule_id == "R-006"
    assert result.fee_amount == Decimal("750.00")
    assert {m.id for m in result.matched_rules} == {"R-002", "R-006"}


def test_premium_cabin(airline):
    """60 小时，超级经济舱 10%：15000 × 10% = 1500.00"""
    result = adjudicate(airline, airline_facts(cabin_class="premium", hours_before_departure=60))

    assert result.winning_rule_id == "R-007"
    assert result.fee_amount == Decimal("1500.00")


def test_rounding_is_half_up_to_cent(airline):
    """333.33 × 15% = 49.9995 → 四舍五入到分 = 50.00（不是 49.99，也不是 49.9995）"""
    result = adjudicate(airline, airline_facts(order_amount=333.33, hours_before_departure=72))

    assert result.winning_rule_id == "R-002"
    assert result.fee_amount == Decimal("50.00")


def test_no_float_artifacts(airline):
    """1234.56 × 5% = 61.728 → 61.73。全程 Decimal，不出现 61.72800000000001 这种尾巴。"""
    result = adjudicate(airline, airline_facts(order_amount=1234.56))

    assert result.fee_amount == Decimal("61.73")


def test_money_is_exact_not_approximate():
    """0.1 + 0.2 那个经典坑：用 Decimal 时必须精确等于 0.3。"""
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")


def test_low_discount_standard_fare_needs_review(airline):
    """折扣低于 3 折的标准票命中 R-012（优先级 20），压过通用档位。"""
    result = adjudicate(airline, airline_facts(discount_rate=0.2))

    assert result.winning_rule_id == "R-012"
    assert result.computed_verdict == "needs_review"
    assert result.fee_amount == Decimal("0.00")
    assert result.escalated is False, '结论本身就是"需人工复核"，但不是被转人工条件触发的'


def test_full_fare_early_refund_gets_better_rate(airline):
    """全价标准票提前退：15000 × 3% = 450.00（R-014 优先级 18 压过 R-001）"""
    result = adjudicate(airline, airline_facts(discount_rate=0.9, hours_before_departure=200))

    assert result.winning_rule_id == "R-014"
    assert result.fee_amount == Decimal("450.00")


# --------------------------------------------------------------------------- #
# 转人工：安全边界
# --------------------------------------------------------------------------- #


def test_amount_threshold_triggers_escalation(airline):
    """20000 × 50% = 10000.00 > 5000 → 必须转人工，且模型不得自行决定"""
    result = adjudicate(airline, airline_facts(order_amount=20000, hours_before_departure=10))

    assert result.computed_verdict == "refundable"
    assert result.fee_amount == Decimal("10000.00")
    assert result.final_verdict == "needs_review"
    assert result.escalated is True
    assert any("超出自动处理阈值" in reason for reason in result.escalate_reasons)


def test_promotional_ticket_is_not_refundable(airline):
    """促销票全额手续费 15000.00，同时因为超过阈值而转人工。"""
    result = adjudicate(airline, airline_facts(fare_type="promotional"))

    assert result.winning_rule_id == "R-008"
    assert result.computed_verdict == "not_refundable"
    assert result.fee_amount == Decimal("15000.00")
    assert result.final_verdict == "needs_review"


def test_noshow_beats_promotional(airline):
    """误机的优先级最高（30），压过促销票（25）。两者结论相同，金额也相同。"""
    result = adjudicate(airline, airline_facts(fare_type="promotional", is_noshow=True))

    assert result.winning_rule_id == "R-005"
    assert result.fee_amount == Decimal("15000.00")


def test_missing_fact_escalates_and_skips_amount_rules(airline):
    """缺 order_amount 时，凡是要算钱的规则一律"不可用"，不许拿缺省值硬算。"""
    facts = airline_facts(fare_type="group")
    del facts["order_amount"]

    result = adjudicate(airline, facts)

    assert result.missing_facts == ("order_amount",)
    assert result.final_verdict == "needs_review"
    assert "R-009" in {m.id for m in result.matched_rules}, "团队票规则不需要金额，仍应命中"
    assert any(item.startswith("R-001:") for item in result.skipped_rules)
    assert any("关键信息缺失" in reason for reason in result.escalate_reasons)


def test_out_of_range_value_escalates(airline):
    """5000 小时超出声明范围，但仍能算出金额（≥336 → R-011 的 2% = 300.00），
    结论必须转人工——"算得出"不等于"可以照此执行"。
    """
    result = adjudicate(airline, airline_facts(hours_before_departure=5000))

    assert result.winning_rule_id == "R-011"
    assert result.fee_amount == Decimal("300.00")
    assert result.out_of_range_facts, "越界必须在结果里显式记录"
    assert any("高于上限" in item for item in result.out_of_range_facts)
    assert any("超出已知范围" in reason for reason in result.escalate_reasons)
    assert result.final_verdict == "needs_review"


def test_unknown_enum_value_escalates(airline):
    result = adjudicate(airline, airline_facts(cabin_class="shuttle"))

    assert any("不在允许取值" in item for item in result.out_of_range_facts)
    assert result.final_verdict == "needs_review"


def test_used_segments_exceeding_total_escalates(airline):
    """已使用航段数大于总航段数：数据自相矛盾，必须交给人。"""
    result = adjudicate(airline, airline_facts(used_segments=3, total_segments=2))

    assert any("自相矛盾" in reason for reason in result.escalate_reasons)
    assert result.final_verdict == "needs_review"


def test_through_ticket_partially_used_escalates(airline):
    result = adjudicate(
        airline, airline_facts(is_through_ticket=True, used_segments=1, total_segments=2)
    )

    assert any("联程" in reason for reason in result.escalate_reasons)
    assert result.final_verdict == "needs_review"


# --------------------------------------------------------------------------- #
# 规则缺口与优先级冲突：运行时最后的自我保护
# --------------------------------------------------------------------------- #


def test_rule_gap_is_stated_explicitly(tmp_path):
    """没有任何规则覆盖时，引擎必须说"不知道"，而不是编一个结论。"""
    domain = _inline_domain(
        tmp_path,
        rules=[
            {
                "id": "X-1",
                "when": "amount > 1000",
                "verdict": "refundable",
                "cite": "测试",
                "priority": 1,
            }
        ],
        facts=[{"name": "amount", "type": "number", "minimum": 0, "maximum": 5000}],
        escalate=[{"when": "missing_any_fact == true", "reason": "缺信息"}],
    )

    result = adjudicate(domain, {"amount": 10})

    assert result.computed_verdict is None
    assert result.final_verdict == "needs_review"
    assert any("规则缺口" in reason for reason in result.escalate_reasons)


def test_same_priority_same_conclusion_is_not_a_conflict(tmp_path):
    """同优先级、**结论相同**的规则并存是允许的：它们只是同一结论的两条依据。

    这是真实 bug 回归：曾经用 `item != winner` 比较整条记录（含规则 id），
    导致任何同优先级的第二条规则都被误报成"优先级冲突"，
    而且报错理由会灌满整个转人工原因分布。判定只应比较 (verdict, fee_amount)。
    """
    domain = _inline_domain(
        tmp_path,
        rules=[
            {
                "id": "A-1",
                "when": "amount > 10",
                "verdict": "not_refundable",
                "cite": "条款 1",
                "priority": 5,
            },
            {
                "id": "A-2",
                "when": "amount > 20",
                "verdict": "not_refundable",
                "cite": "条款 2",
                "priority": 5,
            },
        ],
        facts=[{"name": "amount", "type": "number", "minimum": 0, "maximum": 100}],
        escalate=[{"when": "missing_any_fact == true", "reason": "缺信息"}],
    )

    result = adjudicate(domain, {"amount": 50})

    assert not any("优先级冲突" in reason for reason in result.escalate_reasons)
    assert result.final_verdict == "not_refundable"
    assert result.winning_rule_id == "A-1", "同结论时按 id 稳定取第一条"
    assert {item.id for item in result.matched_rules} == {"A-1", "A-2"}


def test_same_priority_conflict_escalates_instead_of_guessing(tmp_path):
    """两条同优先级、结论不同的规则同时命中：这是规则集的缺陷，必须转人工。"""
    domain = _inline_domain(
        tmp_path,
        rules=[
            {
                "id": "C-1",
                "when": "amount > 10",
                "verdict": "refundable",
                "cite": "测试 1",
                "priority": 5,
            },
            {
                "id": "C-2",
                "when": "amount > 20",
                "verdict": "not_refundable",
                "cite": "测试 2",
                "priority": 5,
            },
        ],
        facts=[{"name": "amount", "type": "number", "minimum": 0, "maximum": 100}],
        escalate=[{"when": "missing_any_fact == true", "reason": "缺信息"}],
    )

    result = adjudicate(domain, {"amount": 50})

    assert result.winning_rule_id is None
    assert any("优先级冲突" in reason for reason in result.escalate_reasons)
    assert result.final_verdict == "needs_review"


# --------------------------------------------------------------------------- #
# 输入校验
# --------------------------------------------------------------------------- #


def test_unknown_fact_is_rejected(airline):
    with pytest.raises(AdjudicationError, match="未声明的字段"):
        adjudicate(airline, airline_facts(whatever=1))


def test_wrong_type_is_rejected(airline):
    with pytest.raises(AdjudicationError, match="应该是数字"):
        adjudicate(airline, airline_facts(order_amount="很多钱"))


def test_bool_is_not_a_number(airline):
    """Python 里 True == 1，所以布尔值必须显式挡住，否则会悄悄变成 1 元票面。"""
    with pytest.raises(AdjudicationError, match="应该是数字"):
        adjudicate(airline, airline_facts(order_amount=True))


def test_integer_field_rejects_fraction(airline):
    with pytest.raises(AdjudicationError, match="应该是整数"):
        adjudicate(airline, airline_facts(used_segments=1.5))


# --------------------------------------------------------------------------- #
# 可复现性与可审计性
# --------------------------------------------------------------------------- #


def test_same_input_gives_identical_output(airline):
    facts = airline_facts(cabin_class="premium", hours_before_departure=60)
    assert adjudicate(airline, facts).to_dict() == adjudicate(airline, facts).to_dict()


def test_judgement_carries_citations(airline):
    """判定必须带依据：没有 cite 的结论在策略上视为缺陷。"""
    result = adjudicate(airline, airline_facts())

    assert result.citations
    assert "示例票规 第 3.1 条" in result.citations[0]


def test_to_dict_is_json_friendly(airline):
    import json

    payload = adjudicate(airline, airline_facts()).to_dict()
    text = json.dumps(payload, ensure_ascii=False)

    assert '"fee_amount": "750.00"' in text, "金额必须是字符串，避免浮点精度问题"


# --------------------------------------------------------------------------- #
# 副场景：没有金额的域
# --------------------------------------------------------------------------- #


def university_facts(**overrides):
    facts = {
        "total_credits": 60,
        "core_credits": 36,
        "capstone_credits": 12,
        "workshop_count": 2,
        "campus": "main",
        "has_timetable_conflict": False,
        "has_unpublished_schedule": False,
    }
    facts.update(overrides)
    return facts


def test_university_eligible_case_has_no_money(university):
    result = adjudicate(university, university_facts())

    assert result.final_verdict == "eligible"
    assert result.fee_amount is None
    assert result.escalated is False


def test_university_insufficient_credits(university):
    result = adjudicate(university, university_facts(total_credits=54))

    assert result.final_verdict == "not_eligible"
    assert result.winning_rule_id == "U-002"


def test_university_branch_campus_falls_into_gap_and_escalates(university):
    """全部条件都满足、但校区是异地：既没有规则覆盖，又命中转人工条件。

    这个用例专门验证"不写兜底规则"这个设计决定——缺口必须被看见，
    而不是被一条 `else: eligible` 悄悄填掉。
    """
    result = adjudicate(university, university_facts(campus="branch"))

    assert result.computed_verdict is None
    assert result.final_verdict == "needs_review"
    assert any("规则缺口" in reason for reason in result.escalate_reasons)
    assert any("异地校区" in reason for reason in result.escalate_reasons)


def test_university_unpublished_schedule_is_flagged(university):
    result = adjudicate(university, university_facts(has_unpublished_schedule=True))

    assert result.final_verdict == "needs_review"
    assert any("时间表" in reason for reason in result.escalate_reasons)
