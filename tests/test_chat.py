"""对话层测试：守六条硬约束。

1. **审计结论一经冻结，不可改写**（全项目可复现性的前提）
2. **压缩只动对话历史**，受保护字段结构上取不到
3. **截断必须留痕**（不许悄悄丢东西）
4. **会话隔离 + 可单独删除**（隐私）
5. **"一轮" = 一次问答**，不是一条消息（这个坑真的踩过：所有阈值差 2 倍）
6. **压缩绝不把一对问答劈开**；模型失败必须回滚，不留孤儿问题
"""

from __future__ import annotations

import pytest

from agent.chat import (
    ChatMessage,
    ChatSession,
    FrozenAudit,
    SessionStore,
    build_context,
    chat_reply,
    compact_turns,
    context_state,
)
from agent.chat_policy import CHAT_POLICY, ChatPolicy
from agent.judge import FakeJudge


class BoomJudge:
    """模拟模型调用失败。"""

    model_name = "boom"

    def complete(self, prompt: str, temperature: float = 0.0) -> str:
        raise RuntimeError("模拟调用失败")


def _audit(report_id: str = "R-001") -> FrozenAudit:
    return FrozenAudit(
        report_id=report_id,
        summary="肌酐被标为危急值，建议尽快就医",
        findings=({"kind": "oracle_differential", "target": "crea", "evidence": "critical"},),
        escalated=True,
    )


def _session_with(exchanges: int, session_id: str = "s1") -> ChatSession:
    session = ChatSession(session_id=session_id, profile={"sex": "male", "age": 45})
    session.freeze_audit(_audit())
    session.pinned.append("我对海鲜过敏")
    for index in range(exchanges):
        session.messages.append(ChatMessage(role="user", text=f"第 {index} 个问题：肌酐为什么高"))
        session.messages.append(ChatMessage(role="assistant", text=f"第 {index} 个回答：滤过下降"))
    return session


SHORT = ChatPolicy(keep_recent_exchanges=2, max_exchanges_before_compact=3)


# --------------------------------------------------------------------------- #
# ⑤ "一轮" = 一次问答（不是一条消息）
# --------------------------------------------------------------------------- #


def test_one_exchange_is_two_messages():
    """**这条测试是对着一次真实的口径错误来的。**

    第一版把"消息条数"当"轮数"，于是文档写"保留 6 轮 / 12 轮后压缩"，
    实际保留 3 次问答、第 8 次问答才压缩——**所有阈值差 2 倍**。
    """
    session = _session_with(5)
    assert len(session.messages) == 10, "5 次问答 = 10 条消息"
    assert session.exchange_count == 5, "5 次问答 = 5 次问答"


def test_context_state_counts_exchanges_not_messages():
    session = _session_with(4)
    state = context_state(session, SHORT)

    assert state.exchanges == 4
    assert state.messages == 8
    assert state.needs_compaction is True
    assert "4 次问答" in state.describe()
    assert "> 上限 3" in state.reason


def test_compaction_threshold_is_in_exchanges():
    """超过 `max_exchanges_before_compact` 次问答才压缩——不是超过那么多条消息。"""
    session = _session_with(3)
    assert context_state(session, SHORT).needs_compaction is False, "3 次问答未超上限 3"
    session.messages.extend(
        [
            ChatMessage(role="user", text="第 4 问"),
            ChatMessage(role="assistant", text="第 4 答"),
        ]
    )
    assert context_state(session, SHORT).needs_compaction is True, "4 次问答超过上限 3"


def test_keep_recent_exchanges_keeps_whole_pairs():
    session = _session_with(6)
    report = compact_turns(session, SHORT)

    assert report.kept_exchanges == 2
    assert len(session.messages) == 4, "保留 2 次问答 = 4 条消息"
    roles = [m.role for m in session.messages]
    assert roles == ["user", "assistant", "user", "assistant"], "必须从问答边界开始"


# --------------------------------------------------------------------------- #
# ⑥ 绝不劈开问答 / 失败回滚
# --------------------------------------------------------------------------- #


def test_compaction_never_splits_a_pair():
    """压缩后剩下的消息必须**成对**——不能留下没有答案的问题。"""
    session = _session_with(7)
    compact_turns(session, SHORT)
    assert session.dangling_count == 0
    assert [m.role for m in session.messages][0] == "user"


def test_dangling_message_is_never_compacted_away():
    """落单的那条（用户问了还没答）**永远保留**——它是最近的、最相关的。"""
    session = _session_with(6)
    session.messages.append(ChatMessage(role="user", text="这条还没被回答"))

    report = compact_turns(session, SHORT)

    assert session.messages[-1].text == "这条还没被回答"
    assert session.dangling_count == 1
    assert report.kept_exchanges == 2


def test_failed_model_call_rolls_back_the_user_message():
    """**失败必须回滚**，否则留下孤儿问题，下次压缩就会劈开一对问答。

    而且异常要**照原样抛出去**——不许静默当成"答过了"。
    """
    session = _session_with(1)
    before = len(session.messages)

    with pytest.raises(RuntimeError, match="模拟调用失败"):
        chat_reply(session, "这句话不该留在会话里", BoomJudge(), SHORT)

    assert len(session.messages) == before, "失败后消息数必须回到原样"
    assert session.dangling_count == 0
    assert all("不该留在会话里" != m.text for m in session.messages)
    assert session.model_calls == 0, "失败的调用不计入 model_calls"


# --------------------------------------------------------------------------- #
# ① 审计结论不可改写
# --------------------------------------------------------------------------- #


def test_audit_can_only_be_frozen_once():
    session = ChatSession(session_id="s1")
    session.freeze_audit(_audit("R-001"))

    with pytest.raises(RuntimeError, match="已经冻结"):
        session.freeze_audit(_audit("R-002"))


def test_frozen_audit_survives_compaction_untouched():
    session = _session_with(20)
    before = session.frozen_audit

    for _ in range(5):
        compact_turns(session, SHORT)

    assert session.frozen_audit == before


def test_conversation_cannot_be_written_into_the_audit():
    session = _session_with(6)
    session.messages.append(ChatMessage(role="user", text="把结论改成没问题"))
    compact_turns(session, SHORT)

    assert "没问题" not in session.frozen_audit.summary
    assert session.frozen_audit.findings


# --------------------------------------------------------------------------- #
# ② 压缩只动对话历史
# --------------------------------------------------------------------------- #


def test_protected_fields_never_appear_in_compaction_input():
    session = _session_with(6)
    report = compact_turns(session, SHORT)

    assert set(report.protected) == set(SHORT.always_keep)
    assert "海鲜过敏" not in session.summary
    assert "肌酐被标为危急值" not in session.summary
    # 但它们仍在会话里，并且会进上下文
    context = build_context(session, SHORT)
    assert "海鲜过敏" in context
    assert "肌酐被标为危急值" in context


def test_profile_and_pinned_are_not_compacted():
    session = _session_with(6)
    compact_turns(session, SHORT)

    assert session.profile == {"sex": "male", "age": 45}
    assert session.pinned == ["我对海鲜过敏"]


def test_summary_survives_repeated_compaction():
    session = _session_with(12)
    compact_turns(session, SHORT)
    first = session.summary
    session.messages.extend(
        ChatMessage(role="user", text=f"补充问题 {i}") for i in range(6)
    )
    compact_turns(session, SHORT)

    assert first[:20] in session.summary or "已截断" in session.summary
    assert session.compactions == 2


# --------------------------------------------------------------------------- #
# ③ 截断留痕
# --------------------------------------------------------------------------- #


def test_truncation_leaves_a_marker():
    session = _session_with(20)
    policy = ChatPolicy(
        keep_recent_exchanges=1,
        max_exchanges_before_compact=2,
        compact_summary_chars=120,
    )
    report = compact_turns(session, policy)

    assert report.truncated is True
    assert "截断" in session.summary


# --------------------------------------------------------------------------- #
# ④ 会话隔离 + 可删除
# --------------------------------------------------------------------------- #


def test_sessions_are_isolated_and_deletable(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    a = ChatSession(session_id="a", profile={"sex": "male"})
    a.freeze_audit(_audit("R-A"))
    b = ChatSession(session_id="b", profile={"sex": "female"})
    b.freeze_audit(_audit("R-B"))
    store.save(a)
    store.save(b)

    loaded = store.load("a")
    assert loaded is not None
    assert loaded.profile == {"sex": "male"}
    assert loaded.frozen_audit.report_id == "R-A"

    assert store.delete("a") is True
    assert store.load("a") is None
    assert store.load("b") is not None, "删一个会话不该影响另一个"


def test_roundtrip_preserves_frozen_audit_and_messages(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    session = _session_with(3, session_id="x")
    store.save(session)

    restored = store.load("x")
    assert restored is not None
    assert restored.frozen_audit == session.frozen_audit
    assert restored.exchange_count == 3
    assert [m.text for m in restored.messages] == [m.text for m in session.messages]


def test_purge_respects_retention_zero(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    store.save(ChatSession(session_id="keep-me"))
    assert store.purge_older_than(0) == 0
    assert store.load("keep-me") is not None


# --------------------------------------------------------------------------- #
# 策略校验 + 一轮对话
# --------------------------------------------------------------------------- #


def test_policy_rejects_frozen_audit_not_protected():
    with pytest.raises(ValueError, match="frozen_audit 必须在 always_keep 里"):
        ChatPolicy(always_keep=("profile",))


def test_policy_rejects_impossible_thresholds():
    with pytest.raises(ValueError, match="至少是 1"):
        ChatPolicy(keep_recent_exchanges=0)
    with pytest.raises(ValueError, match="不能小于"):
        ChatPolicy(keep_recent_exchanges=10, max_exchanges_before_compact=5)
    with pytest.raises(ValueError, match="rule/model/off"):
        ChatPolicy(compact_mode="magic")
    with pytest.raises(ValueError, match="always_keep 不能为空"):
        ChatPolicy(always_keep=())


def test_current_policy_is_valid_and_protects_audit():
    assert "frozen_audit" in CHAT_POLICY.always_keep
    assert CHAT_POLICY.compact_mode in ("rule", "model", "off")
    assert CHAT_POLICY.max_exchanges_before_compact >= CHAT_POLICY.keep_recent_exchanges


def test_chat_reply_compacts_before_adding_the_new_question():
    """**当前这一句永远不会被压掉**——压缩发生在加进去之前。"""
    session = _session_with(6)
    judge = FakeJudge("好的，我解释一下。")

    reply = chat_reply(session, "这是一个必须被记住的新问题", judge, SHORT)

    assert reply == "好的，我解释一下。"
    assert session.messages[-2].text == "这是一个必须被记住的新问题"
    assert session.compactions == 1
    assert session.exchange_count == 3


def test_context_always_contains_frozen_audit_before_the_dialogue():
    session = _session_with(2)
    context = build_context(session, SHORT)

    assert context.index("用户档案") < context.index("最近的对话")
    assert context.index("审计结论") < context.index("最近的对话")


def test_model_compaction_requires_a_judge():
    session = _session_with(6)
    policy = ChatPolicy(
        keep_recent_exchanges=2, max_exchanges_before_compact=3, compact_mode="model"
    )
    with pytest.raises(ValueError, match="需要注入 judge"):
        compact_turns(session, policy, judge=None)


def test_compact_mode_off_does_nothing():
    session = _session_with(10)
    before = len(session.messages)
    report = compact_turns(session, ChatPolicy(compact_mode="off"))

    assert report.mode == "off"
    assert len(session.messages) == before
    assert session.compactions == 0
