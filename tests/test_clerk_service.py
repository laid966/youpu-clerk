"""clerk.service 编排层的测试：管线五步、不变量 I1-I5、双语、降级、额度。

全部测试显式注入 judge（TemplateJudge / FakeJudge）——**绝不联网、绝不花钱、
结果逐字节可复现**。这是本仓库的老纪律（agent/judge.py），clerk 原样继承。
"""

from __future__ import annotations

import pytest
from agent.judge import FakeJudge

import clerk.db as db
from clerk import config
from clerk.service import (
    ClerkError,
    ItemNotFound,
    QuotaExceeded,
    adopt,
    daily_report,
    make_listing,
    suggest,
)
from clerk.templates import TemplateJudge

TOKEN = "tok-test"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
    conn = db.open_db()
    db.ensure_user(conn, TOKEN)
    # 挂牌 399.00，底价 = 399 × 0.85 = 339.15（default_floor_price 的口径）
    item = db.create_item(conn, TOKEN, "机械键盘 87 键", "399.00", "339.15")
    yield {"conn": conn, "item": item}
    conn.close()


def _suggest(env, message, conversation_id=None, judge=None, source="paste"):
    return suggest(
        token=TOKEN,
        item_id=env["item"]["id"],
        message=message,
        conversation_id=conversation_id,
        source=source,
        judge=judge if judge is not None else TemplateJudge(),
        conn=env["conn"],
    )


def _adopt(env, suggestion_id, action, final_text=None):
    return adopt(
        suggestion_id=suggestion_id,
        action=action,
        final_text=final_text,
        token=TOKEN,
        conn=env["conn"],
    )


def _fake_judge(classify_reply=None, draft_reply=None):
    """按 prompt 内容分流：分类 prompt 含"分类器"，起草 prompt 含"客服助手"。

    注意用 `is not None` 而不是 `or`：draft_reply="" 是合法输入（测空回复降级），
    `"" or default` 会把它悄悄换成默认值——第一版就栽在这里。
    """

    def responder(prompt: str) -> str:
        if "分类器" in prompt:
            if classify_reply is not None:
                return classify_reply
            return '{"kind": "bargain", "language": "zh", "offer": "300.00"}'
        if draft_reply is not None:
            return draft_reply
        return "亲，379.05 给您，真心价～"

    return FakeJudge(responder)


class TestPipeline:
    def test_counter_flow_shape(self, env):
        result = _suggest(env, "300行不行")
        assert result["classification"] == {"kind": "bargain", "language": "zh", "offer": "300.00"}
        decision = result["decision"]
        assert decision["kind"] == "counter"
        assert decision["price"] == "379.05"  # 399 × 0.95，引擎算的
        assert decision["rule_id"] == "BARGAIN-COUNTER-T1"
        assert decision["citations"]
        assert [step["step"] for step in result["trace"]] == [
            "classify",
            "decide",
            "draft",
            "guardrail",
        ]
        assert result["quota"]["used_today"] == 1
        assert result["reply_text"]

    def test_english_buyer_gets_english_reply(self, env):
        result = _suggest(env, "Would you take 340?")
        assert result["classification"]["language"] == "en"
        assert result["classification"]["offer"] == "340.00"
        assert result["decision"]["kind"] == "accept"  # 340 ≥ 底价 339.15
        assert "Deal at 340.00" in result["reply_text"]

    def test_lowball_goes_human_with_reason(self, env):
        result = _suggest(env, "150出不出")
        decision = result["decision"]
        assert decision["kind"] == "human"
        assert decision["requires_human_review"] is True
        assert decision["rule_id"] == "BARGAIN-HUMAN-LOWBALL"
        assert "339.15" not in result["reply_text"]  # 稳住话术里不许有数字

    def test_chitchat_and_opening_skip_engine(self, env):
        chitchat = _suggest(env, "还在吗")
        assert chitchat["classification"]["kind"] == "chitchat"
        assert chitchat["decision"] is None
        opening = _suggest(env, "能刀吗")
        assert opening["classification"]["kind"] == "opening"
        assert opening["decision"] is None

    def test_aftersale_detected(self, env):
        result = _suggest(env, "收到货是坏的，我要退货")
        assert result["classification"]["kind"] == "aftersale"
        assert result["decision"] is None

    def test_determinism(self, env):
        first = _suggest(env, "300行不行")
        second = _suggest(env, "300行不行")
        assert first["decision"] == second["decision"]
        assert first["reply_text"] == second["reply_text"]
        assert first["classification"] == second["classification"]


class TestLadderAndAdoption:
    def test_ladder_descends_as_concessions_accumulate(self, env):
        s1 = _suggest(env, "300行不行")
        conv = s1["conversation_id"]
        assert s1["decision"]["price"] == "379.05"
        assert _adopt(env, s1["suggestion_id"], "sent")["concessions_used"] == 1

        s2 = _suggest(env, "290行不行", conversation_id=conv)
        assert s2["decision"]["price"] == "367.08"  # 399 × 0.92
        assert _adopt(env, s2["suggestion_id"], "sent")["concessions_used"] == 2

        s3 = _suggest(env, "280行不行", conversation_id=conv)
        assert s3["decision"]["price"] == "359.10"  # 399 × 0.90
        assert _adopt(env, s3["suggestion_id"], "sent")["concessions_used"] == 3

        s4 = _suggest(env, "275行不行", conversation_id=conv)
        assert s4["decision"]["kind"] == "firm"

    def test_discarded_does_not_count_as_concession(self, env):
        s1 = _suggest(env, "300行不行")
        conv = s1["conversation_id"]
        assert _adopt(env, s1["suggestion_id"], "discarded")["concessions_used"] == 0
        s2 = _suggest(env, "300行不行", conversation_id=conv)
        assert s2["decision"]["rule_id"] == "BARGAIN-COUNTER-T1"  # 仍是第 1 档

    def test_i5_rows_per_suggestion_and_adoption(self, env):
        result = _suggest(env, "300行不行")
        conv = result["conversation_id"]
        assert len(db.get_conversation_messages(env["conn"], conv)) == 1
        assert len(db.get_conversation_decisions(env["conn"], conv)) == 1
        _adopt(env, result["suggestion_id"], "sent")
        messages = db.get_conversation_messages(env["conn"], conv)
        assert len(messages) == 2
        assert messages[-1]["direction"] == "seller"

    def test_edited_records_final_text(self, env):
        result = _suggest(env, "300行不行")
        _adopt(env, result["suggestion_id"], "edited", final_text="380 行吗亲")
        row = db.get_decision(env["conn"], result["suggestion_id"])
        assert row["final_text"] == "380 行吗亲"
        # edited 也算真让步（I1）
        assert db.count_adopted_counters(env["conn"], result["conversation_id"], env["item"]["id"]) == 1

    def test_double_adoption_rejected(self, env):
        result = _suggest(env, "300行不行")
        _adopt(env, result["suggestion_id"], "sent")
        with pytest.raises(db.DbError, match="不能重复改判"):
            _adopt(env, result["suggestion_id"], "discarded")


class TestQuota:
    def test_free_quota_enforced(self, env, monkeypatch):
        monkeypatch.setattr(config, "FREE_DAILY_SUGGESTIONS", 2)
        _suggest(env, "300行不行")
        _suggest(env, "290行不行")
        with pytest.raises(QuotaExceeded) as excinfo:
            _suggest(env, "280行不行")
        assert excinfo.value.pricing["price_30d"] == "9.90"

    def test_quota_not_consumed_on_failure(self, env, monkeypatch):
        monkeypatch.setattr(config, "FREE_DAILY_SUGGESTIONS", 2)
        with pytest.raises(ItemNotFound):
            suggest(
                token=TOKEN,
                item_id="nonexistent",
                message="300行不行",
                judge=TemplateJudge(),
                conn=env["conn"],
            )
        assert db.get_usage(env["conn"], TOKEN, db.today_shanghai()) == 0

    def test_demo_source_is_quota_exempt(self, env, monkeypatch):
        """演示是橱窗不是生意：demo 豁免额度、不计 usage（17 步全剧本实测抓出的 bug）。"""
        monkeypatch.setattr(config, "FREE_DAILY_SUGGESTIONS", 1)
        _suggest(env, "300行不行", source="demo")
        second = _suggest(env, "290行不行", source="demo")  # 超额也不许 402
        assert second["decision"]["kind"] == "counter"
        assert db.get_usage(env["conn"], TOKEN, db.today_shanghai()) == 0


class TestGlobalBudget:
    """全站日预算闸：单用户额度防君子，全局闸防"脚本换 token 薅 LLM 账单"。"""

    def test_global_cap_across_users(self, env, monkeypatch):
        from clerk.service import GlobalQuotaExhausted

        monkeypatch.setattr(config, "GLOBAL_DAILY_LLM_BUDGET", 1)
        # 商品按 token 隔离——每个用户建自己的档案（第一版测试在这里摔过：
        # 拿 env 的商品喂别的 token，撞上 ItemNotFound，测的根本不是预算闸）
        item_a = db.create_item(env["conn"], "user-a", "键盘A", "399.00", "339.15")
        item_b = db.create_item(env["conn"], "user-b", "键盘B", "399.00", "339.15")
        suggest(
            token="user-a", item_id=item_a["id"], message="300行不行",
            judge=TemplateJudge(), conn=env["conn"],
        )
        with pytest.raises(GlobalQuotaExhausted):
            suggest(
                token="user-b", item_id=item_b["id"], message="300行不行",
                judge=TemplateJudge(), conn=env["conn"],
            )

    def test_demo_exempt_from_global_budget(self, env, monkeypatch):
        monkeypatch.setattr(config, "GLOBAL_DAILY_LLM_BUDGET", 0)  # 全局闸关死
        result = _suggest(env, "300行不行", source="demo")  # 演示照样跑（不用 LLM 也不计数）
        assert result["decision"]["kind"] == "counter"
        assert db.get_usage(env["conn"], "__global__", db.today_shanghai()) == 0

    def test_global_usage_counted_per_real_suggestion(self, env):
        _suggest(env, "300行不行")
        _suggest(env, "290行不行")
        assert db.get_usage(env["conn"], "__global__", db.today_shanghai()) == 2


class TestGuardrailIntegration:
    def test_floor_leak_is_replaced(self, env):
        judge = _fake_judge(draft_reply="悄悄告诉您，底价339.15，您出379.05就行")
        result = _suggest(env, "300行不行", judge=judge)
        assert any(hit["rule"] == "C-FLOOR-LEAK" for hit in result["guardrail_hits"])
        assert "339.15" not in result["reply_text"]
        assert "379.05" in result["reply_text"]  # 安全模板带授权价
        assert result["trace"][-1]["ok"] is False

    def test_diversion_is_replaced(self, env):
        judge = _fake_judge(draft_reply="加个微信细聊呀")
        result = _suggest(env, "300行不行", judge=judge)
        assert any(hit["rule"] == "C-DIVERSION" for hit in result["guardrail_hits"])
        assert "微信" not in result["reply_text"]

    def test_hallucinated_price_is_replaced(self, env):
        judge = _fake_judge(draft_reply="给您个惊喜价 250.00 元！")
        result = _suggest(env, "300行不行", judge=judge)
        assert any(hit["rule"] == "C-UNKNOWN-PRICE" for hit in result["guardrail_hits"])
        assert "250.00" not in result["reply_text"]

    def test_good_llm_draft_passes_through(self, env):
        judge = _fake_judge(draft_reply="亲，379.05 给您，真心价～")
        result = _suggest(env, "300行不行", judge=judge)
        assert result["guardrail_hits"] == []
        assert result["reply_text"] == "亲，379.05 给您，真心价～"


class TestLlmDegradation:
    def test_bad_classification_falls_back_to_template(self, env):
        judge = _fake_judge(classify_reply="我不知道该说什么")
        result = _suggest(env, "300行不行", judge=judge)
        assert result["trace"][0]["ok"] is False  # classify 降级
        assert result["classification"]["kind"] == "bargain"  # 模板兜住了
        assert result["classification"]["offer"] == "300.00"
        assert result["decision"]["kind"] == "counter"

    def test_empty_draft_falls_back_to_template(self, env):
        judge = _fake_judge(draft_reply="")
        result = _suggest(env, "300行不行", judge=judge)
        assert result["trace"][2]["ok"] is False  # draft 降级
        assert "379.05" in result["reply_text"]


class TestSelectJudge:
    def test_no_key_selects_template_judge(self, monkeypatch):
        # 空字符串也是 falsy；且 load_dotenv 默认不覆盖已存在的环境变量，
        # 所以 .env 里就算有 key 也不会漏进来
        monkeypatch.setenv("DEEPSEEK_API_KEY", "")
        from clerk.templates import select_judge

        assert isinstance(select_judge(), TemplateJudge)


class TestDailyReport:
    def test_report_counts(self, env):
        s1 = _suggest(env, "300行不行")
        _adopt(env, s1["suggestion_id"], "sent")
        _suggest(env, "还在吗", conversation_id=s1["conversation_id"])
        report = daily_report(token=TOKEN, conn=env["conn"])
        assert report["inquiries"] == 2
        assert report["counters"] == 1
        assert report["concessions_adopted"] == 1
        assert report["adopted"] == 1


class TestListing:
    """Listing 文案：免费钩子。事实只来自卖家输入，模型只搭骨架。"""

    def test_template_path_leaves_blanks(self, env):
        result = make_listing(token=TOKEN, title="机械键盘 87 键", judge=TemplateJudge(), conn=env["conn"])
        assert result["source"] == "template"
        assert "机械键盘 87 键" in result["text"]
        assert "【成色】" in result["text"]  # 没给的信息留空位，不编造

    def test_hints_are_appended_verbatim(self, env):
        result = make_listing(
            token=TOKEN, title="键盘", hints="九成新，带原盒", judge=TemplateJudge(), conn=env["conn"]
        )
        assert "九成新，带原盒" in result["text"]

    def test_llm_path(self, env):
        judge = FakeJudge("九成新仅用两次，带原盒，诚心出")
        result = make_listing(token=TOKEN, title="Switch 卡带", judge=judge, conn=env["conn"])
        assert result["source"] == "llm"
        assert result["text"] == "九成新仅用两次，带原盒，诚心出"

    def test_guardrail_replaces_diversion(self, env):
        judge = FakeJudge("加我微信私聊哈，绝对正品放心买")
        result = make_listing(token=TOKEN, title="键盘", judge=judge, conn=env["conn"])
        assert result["guardrail_hits"]
        assert result["source"] == "template"
        assert "微信" not in result["text"]

    def test_empty_title_raises(self, env):
        with pytest.raises(ClerkError):
            make_listing(token=TOKEN, title="   ", judge=TemplateJudge(), conn=env["conn"])

    def test_listing_does_not_consume_user_quota(self, env, monkeypatch):
        """获客钩子不设墙：个人额度为 0 也能生成（全站预算另算）。"""
        monkeypatch.setattr(config, "FREE_DAILY_SUGGESTIONS", 0)
        result = make_listing(token=TOKEN, title="键盘", judge=TemplateJudge(), conn=env["conn"])
        assert result["source"] == "template"
