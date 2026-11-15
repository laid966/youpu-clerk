"""议价授权决策的测试 —— 产品命门的"授权"那一半。

对应实施计划第八节的验收标准：

- 网格扫描 725 组议价组合，决策 **100% 落在授权域内**：
  counter 价 ≥ 底价且 ≤ 挂牌价；accept 只出现在出价 ≥ 底价时；每个决策都有依据（citations 非空）
- 金额精确到分（Decimal + ROUND_HALF_UP，财务惯例而非银行家舍入）
- 同一输入永远同一输出（确定性）
- 非法输入大声失败，绝不硬算

注意：梯度断言（95%/92%/90%）与 domain/clerk-bargain/domain.yaml 的取值**刻意耦合**——
测试就是取值的验证纸。作者改梯度时，这里必须一起改，改完两边都对才算数。
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from clerk.bargain import (
    BARGAIN_DOMAIN_PATH,
    BargainError,
    BargainFacts,
    decide_bargain,
    default_floor_price,
    load_bargain_domain,
    to_money,
)
from clerk.config import DEFAULT_FLOOR_RATIO


@pytest.fixture(scope="module")
def domain():
    return load_bargain_domain()


def facts(asking="100.00", offer="70.00", floor="80.00", used=0) -> BargainFacts:
    """默认场景：挂牌 100、底价 80、买家出 70（ratio 0.875，不算低价甩卖）→ 应还价。"""
    return BargainFacts(
        asking_price=Decimal(asking),
        buyer_offer=Decimal(offer),
        floor_price=Decimal(floor),
        concessions_used=used,
    )


class TestDomain:
    def test_domain_file_exists(self):
        assert BARGAIN_DOMAIN_PATH.is_file(), "议价授权域 YAML 必须存在——规则是数据"

    def test_verdicts_and_critical(self, domain):
        assert domain.name == "clerk-bargain"
        assert set(domain.verdicts) == {"accept", "counter", "firm", "human"}
        assert domain.critical_verdicts == frozenset({"human"})

    def test_no_default_verdict_so_gaps_go_human(self, domain):
        # 不声明 default_verdict 是刻意的：没被规则覆盖 = 规则缺口 = 转人工，绝不编结论
        assert domain.default_verdict is None


class TestAccept:
    def test_offer_equal_floor_accepts(self, domain):
        d = decide_bargain(facts(offer="80.00", floor="80.00"), domain)
        assert d.kind == "accept"
        assert d.rule_id == "BARGAIN-ACCEPT"
        assert d.price is None
        assert d.citations, "accept 也必须带依据"
        assert not d.requires_human_review

    def test_offer_above_asking_accepts(self, domain):
        d = decide_bargain(facts(offer="120.00"), domain)
        assert d.kind == "accept"


class TestCounter:
    def test_first_counter_is_95_percent(self, domain):
        d = decide_bargain(facts(used=0), domain)
        assert d.kind == "counter"
        assert d.price == Decimal("95.00")
        assert d.rule_id == "BARGAIN-COUNTER-T1"
        assert any("梯度第 1 档" in c for c in d.citations)

    def test_ladder_descends(self, domain):
        prices = [decide_bargain(facts(used=n), domain).price for n in (0, 1, 2)]
        assert prices == [Decimal("95.00"), Decimal("92.00"), Decimal("90.00")]

    def test_counter_price_rounds_half_up_to_cent(self, domain):
        # 39.90 × 0.95 = 37.905 → 37.91（ROUND_HALF_UP；银行家舍入会给 37.90，那是错的）
        d = decide_bargain(facts(asking="39.90", offer="29.00", floor="30.00"), domain)
        assert d.kind == "counter"
        assert d.price == Decimal("37.91")

    def test_every_counter_carries_rule_and_citation(self, domain):
        for used in (0, 1, 2):
            d = decide_bargain(facts(used=used), domain)
            assert d.rule_id and d.citations, f"第 {used} 轮让步缺依据——留痕断裂"


class TestFirm:
    def test_exhausted_ladder_holds_firm(self, domain):
        d = decide_bargain(facts(used=3), domain)
        assert d.kind == "firm"
        assert d.rule_id == "BARGAIN-FIRM-EXHAUSTED"
        assert d.price is None

    def test_firm_yields_to_accept_when_offer_meets_floor(self, domain):
        # ACCEPT 优先级更高：梯度用尽但买家出价到底价了，该卖就卖
        d = decide_bargain(facts(offer="80.00", used=5), domain)
        assert d.kind == "accept"


class TestHumanEscalation:
    def test_extreme_lowball_goes_human(self, domain):
        d = decide_bargain(facts(offer="40.00", floor="80.00"), domain)  # ratio 0.5 < 0.8
        assert d.kind == "human"
        assert d.requires_human_review
        assert d.rule_id == "BARGAIN-HUMAN-LOWBALL"

    def test_counter_below_floor_escalates(self, domain):
        # 挂牌 100、底价 98：梯度第 1 档还价 95 < 98 → 不许还价，转人工
        d = decide_bargain(facts(offer="90.00", floor="98.00"), domain)
        assert d.kind == "human"
        assert d.requires_human_review
        assert any("底价" in r for r in d.reasons)

    def test_offer_at_80_percent_boundary_is_not_lowball(self, domain):
        # offer/floor 恰好 = 0.8：规则是 < 0.8，边界不转人工。这个语义被本测试锁定
        d = decide_bargain(facts(offer="64.00", floor="80.00"), domain)
        assert d.kind == "counter"


class TestValidation:
    def test_floor_above_asking_raises(self):
        with pytest.raises(BargainError, match="底价"):
            facts(asking="100.00", floor="120.00")

    @pytest.mark.parametrize("bad", ["0", "-5.00"])
    def test_nonpositive_money_raises(self, bad):
        with pytest.raises(BargainError):
            facts(offer=bad)

    def test_negative_concessions_raises(self):
        with pytest.raises(BargainError):
            facts(used=-1)

    def test_bool_concessions_raises(self):
        with pytest.raises(BargainError):
            BargainFacts(Decimal("100"), Decimal("70"), Decimal("80"), True)

    def test_garbage_money_raises(self):
        with pytest.raises(BargainError):
            to_money("ninety")


class TestDeterminismAndSerialization:
    def test_same_input_same_output(self, domain):
        a = decide_bargain(facts(), domain).to_dict()
        b = decide_bargain(facts(), domain).to_dict()
        assert a == b

    def test_to_dict_is_json_friendly(self, domain):
        d = decide_bargain(facts(), domain)
        text = json.dumps(d.to_dict(), ensure_ascii=False)
        assert '"price": "95.00"' in text


class TestSmartDefaults:
    def test_default_floor_is_85_percent(self):
        assert default_floor_price("100.00") == Decimal("85.00")

    def test_default_floor_rounds_to_cent(self):
        # 39.90 × 0.85 = 33.915 → 33.92（ROUND_HALF_UP）
        assert default_floor_price("39.90") == Decimal("33.92")

    def test_ratio_comes_from_config(self):
        assert DEFAULT_FLOOR_RATIO == Decimal("0.85")

    def test_to_money_normalizes_inputs(self):
        assert to_money(39.9) == Decimal("39.90")
        assert to_money("39.9") == Decimal("39.90")
        assert to_money(Decimal("39.900")) == Decimal("39.90")


class TestAuthorizationInvariant:
    """验收硬指标（计划第八节）：决策 100% 落在授权域内。

    扫 5 档底价 × 29 档出价 × 5 档让步数 = 725 个组合，断言零违规。
    这个测试是产品承诺"永不越权"的测试形态：

    - counter 的价必须 ≥ 底价 且 ≤ 挂牌价（破底价的组合必须已经变成 human）
    - accept 只在出价 ≥ 底价时出现
    - firm 只在梯度用尽且出价未达底价时出现
    - human 必须标记 requires_human_review
    - **每个决策都有依据**（citations 非空）——没有依据的决策视为缺陷
    """

    def test_grid_scan_never_leaves_authorization(self, domain):
        asking = Decimal("200.00")
        violations: list[str] = []
        combos = 0

        for floor_text in ("200.00", "170.00", "160.00", "120.00", "100.00"):
            floor = Decimal(floor_text)
            for offer_units in range(10, 211, 7):
                offer = Decimal(offer_units)
                for used in range(0, 5):
                    combos += 1
                    d = decide_bargain(BargainFacts(asking, offer, floor, used), domain)
                    where = f"floor={floor} offer={offer} used={used}"

                    if not d.citations:
                        violations.append(f"{where}: 决策没有依据")
                    if d.kind == "counter":
                        if d.price is None or d.price < floor or d.price > asking:
                            violations.append(f"{where}: 还价 {d.price} 越权")
                    elif d.kind == "accept":
                        if offer < floor:
                            violations.append(f"{where}: 低于底价却 accept")
                    elif d.kind == "firm":
                        if used < 3 or offer >= floor:
                            violations.append(f"{where}: firm 条件不符")
                    elif d.kind == "human":
                        if not d.requires_human_review:
                            violations.append(f"{where}: human 未标记需人工")
                    else:
                        violations.append(f"{where}: 未知决策类型 {d.kind}")

        assert combos >= 100, "网格规模不够，验收无效"
        assert violations == []
