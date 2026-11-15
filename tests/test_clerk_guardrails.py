"""clerk.guardrails 的测试：词表层 + 数字层（I3），以及"安全模板必须自身干净"。

最后那个测试很重要：护栏命中后整段替换成安全模板——**如果模板自己带违禁内容，
替换就成了事故放大器**。所以每个模板都要能过自己的护栏。
"""

from __future__ import annotations

from decimal import Decimal

import clerk.templates as templates
from clerk.guardrails import check_numbers, scan_all, scan_reply
from clerk.templates import Classification, template_classify, template_draft

ALLOWED = [Decimal("379.05"), Decimal("399.00"), Decimal("300.00")]
FLOOR = Decimal("339.15")
ITEM = {"title": "机械键盘", "asking_price": "399.00", "floor_price": "339.15"}


class TestWordRules:
    def test_diversion_hit(self):
        hits = scan_reply("加个微信细聊呀")
        assert any(h.rule == "C-DIVERSION" for h in hits)

    def test_diversion_english_hit(self):
        hits = scan_reply("Let's move to WeChat")
        assert any(h.rule == "C-DIVERSION" for h in hits)

    def test_overpromise_hit(self):
        hits = scan_reply("绝对正品，假一赔十")
        rules = {h.rule for h in hits}
        assert "C-OVERPROMISE" in rules

    def test_abuse_hit(self):
        assert any(h.rule == "C-ABUSE" for h in scan_reply("you are stupid"))

    def test_clean_text_no_hits(self):
        assert scan_reply("亲，这个价格已经很实惠啦") == []


class TestNumberWhitelist:
    def test_allowed_price_passes(self):
        assert check_numbers("379.05元拿走", allowed=ALLOWED, floor_price=FLOOR) == []

    def test_yen_prefix_allowed(self):
        assert check_numbers("¥399.00", allowed=ALLOWED, floor_price=FLOOR) == []

    def test_floor_leak_caught(self):
        hits = check_numbers("悄悄说，底价339.15", allowed=ALLOWED, floor_price=FLOOR)
        assert len(hits) == 1
        assert hits[0].rule == "C-FLOOR-LEAK"
        assert hits[0].category == "numeric"

    def test_unknown_price_caught(self):
        hits = check_numbers("要不123.45卖你", allowed=ALLOWED, floor_price=FLOOR)
        assert len(hits) == 1
        assert hits[0].rule == "C-UNKNOWN-PRICE"

    def test_non_currency_numbers_ignored(self):
        # "3天"没有货币语境，不是价格——不许误报，否则真事故会被误报淹没
        assert check_numbers("3天内发货，2件一起买", allowed=ALLOWED, floor_price=FLOOR) == []

    def test_floor_equal_asking_is_not_leak(self):
        # 店主把底价设成挂牌价时，复述挂牌价是合法的（allowed 判定在 floor 判定之前）
        assert check_numbers("399.00 不刀", allowed=[Decimal("399.00")], floor_price=Decimal("399.00")) == []


class TestScanAll:
    def test_both_layers_run(self):
        hits = scan_all("加微信，底价339.15", allowed=ALLOWED, floor_price=FLOOR)
        rules = {h.rule for h in hits}
        assert "C-DIVERSION" in rules
        assert "C-FLOOR-LEAK" in rules


class TestTemplatesAreSelfClean:
    """安全模板必须能通过自己的护栏——否则"整段替换"就是事故放大器。"""

    def test_every_template_passes_guardrails(self):
        offer = Decimal("300.00")
        classification_zh = Classification("bargain", "zh", offer)
        classification_en = Classification("bargain", "en", offer)

        class _FakeDecision:
            def __init__(self, kind, price):
                self.kind = kind
                self.price = price

        cases = [
            (_FakeDecision("accept", None), classification_zh),
            (_FakeDecision("accept", None), classification_en),
            (_FakeDecision("counter", Decimal("379.05")), classification_zh),
            (_FakeDecision("counter", Decimal("379.05")), classification_en),
            (_FakeDecision("firm", None), classification_zh),
            (_FakeDecision("firm", None), classification_en),
            (_FakeDecision("human", None), classification_zh),
            (_FakeDecision("human", None), classification_en),
            (None, Classification("opening", "zh", None)),
            (None, Classification("opening", "en", None)),
            (None, Classification("chitchat", "zh", None)),
            (None, Classification("chitchat", "en", None)),
            (None, Classification("aftersale", "zh", None)),
            (None, Classification("aftersale", "en", None)),
        ]
        for decision, classification in cases:
            allowed = [Decimal(ITEM["asking_price"])]
            if decision is not None and decision.price is not None:
                allowed.append(decision.price)
            if classification.offer is not None:
                allowed.append(classification.offer)
            reply = template_draft(decision=decision, classification=classification, item=ITEM)
            hits = scan_all(reply, allowed=allowed, floor_price=Decimal(ITEM["floor_price"]))
            assert hits == [], f"模板自带违禁内容：{reply!r} -> {[h.rule for h in hits]}"


class TestTemplateClassify:
    def test_quantity_words_not_price(self):
        # "2件"的 2 是数量不是出价；"95新"的 95 是成色不是出价
        assert template_classify("还剩2件吗").offer is None
        assert template_classify("95新的键盘还在吗").offer is None

    def test_price_with_measure_excluded_but_real_offer_kept(self):
        assert template_classify("150出不出").offer == Decimal("150.00")
        assert template_classify("3天能到吗").offer is None

    def test_language_detection(self):
        assert template_classify("Would you take 340?").language == "en"
        assert template_classify("300行不行").language == "zh"
        assert template_classify("ok 300行不行").language == "zh"  # 中文为主
