"""演示剧本与真实实现的一致性测试。

演示现场翻车是最贵的翻车，所以每条剧本都在 CI 里先"演"一遍：

1. 每句台词过 template_classify —— 演示强制无 key（TemplateJudge），
   剧本措辞必须能被**模板分类器**正确理解，不能指望 LLM 救场。
2. 每个带出价的步骤过 decide_bargain —— expected 里写的 kind/price/rule_id
   必须与引擎实际输出逐字段一致；used（已让步次数）按"卖家总是采纳"递推。
3. 商品底价必须等于 default_floor_price 现算值 —— 防止配置改了、剧本旁白还引用旧数字。

改剧本、改梯度、改默认底价比例，任何一样动了对不上，这里立刻炸。
"""

from __future__ import annotations

from decimal import Decimal

import pytest

import clerk.db as db
from clerk import demo
from clerk.bargain import BargainFacts, decide_bargain, default_floor_price
from clerk.templates import template_classify


class TestBootstrapShape:
    def test_shop_and_personas(self):
        data = demo.bootstrap()
        assert data["shop"]["name"]
        assert len(data["shop"]["items"]) == 3
        assert len(data["personas"]) == 5

    def test_money_strings_two_decimals(self):
        data = demo.bootstrap()
        for item in data["shop"]["items"]:
            assert db.MONEY_RE.match(item["asking_price"]), item
            assert db.MONEY_RE.match(item["floor_price"]), item

    def test_floor_is_computed_not_handwritten(self):
        for item in demo.bootstrap()["shop"]["items"]:
            assert Decimal(item["floor_price"]) == default_floor_price(item["asking_price"])

    def test_languages_cover_zh_and_en(self):
        languages = {persona["language"] for persona in demo.bootstrap()["personas"]}
        assert languages == {"zh", "en"}

    def test_every_step_has_bilingual_notes(self):
        for persona in demo.bootstrap()["personas"]:
            for index, step in enumerate(persona["steps"]):
                assert step["note_zh"].strip(), f"{persona['id']}#{index} 缺中文旁白"
                assert step["note_en"].strip(), f"{persona['id']}#{index} 缺英文旁白"


class TestScriptsMatchImplementation:
    """核心：逐句重放每条剧本，分类器与引擎的实际行为必须等于 expected。"""

    @pytest.mark.parametrize("persona_id", demo.persona_ids())
    def test_persona_script_replay(self, persona_id):
        persona = demo.get_persona(persona_id)
        item = next(
            entry
            for entry in demo.bootstrap()["shop"]["items"]
            if entry["key"] == persona["item_key"]
        )
        asking = Decimal(item["asking_price"])
        floor = Decimal(item["floor_price"])

        used = 0  # I1 口径：演示里卖家永远采纳，counter 被采纳即计入
        for index, step in enumerate(persona["steps"]):
            where = f"{persona_id}#{index}({step['message']!r})"
            expected_classify = step["expected_classify"]
            expected = step["expected"]

            classification = template_classify(step["message"])
            assert classification.kind == expected_classify["kind"], where
            assert classification.language == step["language"], where
            if expected_classify["offer"] is None:
                assert classification.offer is None, where
            else:
                assert classification.offer == Decimal(expected_classify["offer"]), where

            if expected["kind"] == "none":
                # 不进引擎的消息：不允许被分类成"带出价的议价"
                assert not (classification.kind == "bargain" and classification.offer), where
                continue

            assert classification.kind == "bargain" and classification.offer is not None, where
            assert expected.get("used", used) == used, f"{where}: 剧本标注的 used 与递推不符"

            decision = decide_bargain(
                BargainFacts(
                    asking_price=asking,
                    buyer_offer=classification.offer,
                    floor_price=floor,
                    concessions_used=used,
                )
            )
            assert decision.kind == expected["kind"], where
            assert decision.rule_id == expected["rule_id"], where
            if expected["kind"] == "counter":
                assert decision.price is not None, where
                assert str(decision.price) == expected["price"], where
                used += 1

    def test_wang_covers_the_full_journey(self):
        """老王的剧本必须打遍全部决策类型——他是演示的"考卷"。"""
        kinds = [step["expected"]["kind"] for step in demo.get_persona("wang")["steps"]]
        assert kinds == ["human", "counter", "counter", "counter", "firm", "accept"]

    def test_zhang_never_reaches_engine(self):
        persona = demo.get_persona("zhang")
        assert all(step["expected"]["kind"] == "none" for step in persona["steps"])


class TestNextStep:
    def test_unknown_persona_raises(self):
        with pytest.raises(demo.DemoError):
            demo.next_step("nobody", 0)

    def test_out_of_range_raises(self):
        persona = demo.get_persona("chen")
        with pytest.raises(demo.DemoError, match="剧本只有"):
            demo.next_step("chen", len(persona["steps"]))

    def test_finished_flag_on_last_step(self):
        persona = demo.get_persona("chen")
        result = demo.next_step("chen", len(persona["steps"]) - 1)
        assert result["finished"] is True

    def test_step_payload_shape(self):
        result = demo.next_step("emma", 1)
        for key in (
            "persona_id", "item_key", "step_index", "total_steps", "message",
            "language", "note_zh", "note_en", "expected_classify", "expected", "finished",
        ):
            assert key in result


class TestSeedDemo:
    def test_seed_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
        conn = db.open_db()
        try:
            first = demo.seed_demo(conn)
            second = demo.seed_demo(conn)
            assert set(first) == {"keyboard", "gamecard", "band"}
            assert first["keyboard"]["id"] == second["keyboard"]["id"]
            assert len(db.list_items(conn, demo.DEMO_TOKEN)) == 3
        finally:
            conn.close()

    def test_step_index_counts_buyer_messages(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
        conn = db.open_db()
        try:
            items = demo.seed_demo(conn)
            conv = db.get_or_create_conversation(conn, demo.DEMO_TOKEN, items["keyboard"]["id"])
            assert demo.step_index_for_conversation(conn, conv["id"]) == 0
            db.add_message(conn, conv["id"], "buyer", "200出不出？")
            db.add_message(conn, conv["id"], "seller", "亲，出不了")
            assert demo.step_index_for_conversation(conn, conv["id"]) == 1
        finally:
            conn.close()
