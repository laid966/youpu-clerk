"""对话层测试：守四条硬约束。

1. **审计结论一经冻结，不可改写**（这是全项目可复现性的前提）
2. **压缩只动对话历史**，受保护字段结构上取不到
3. **截断必须留痕**（不许悄悄丢东西）
4. **会话隔离 + 可单独删除**（隐私）

另有：压缩确实发生、当前问句永不被压掉、策略非法时大声报错。
"""

from __future__ import annotations

import pytest

from agent.chat import (
    ChatSession,
    ChatTurn,
    FrozenAudit,
    SessionStore,
    build_context,
    chat_reply,
    compact_turns,
    context_state,
)
from agent.chat_policy import CHAT_POLICY, ChatPolicy
from agent.judge import FakeJudge


def _audit(report_id: str = "R-001") -> FrozenAudit:
    return FrozenAudit(
        report_id=report_id,
        summary="肌酐被标为危急值，建议尽快就医",
        findings=({"kind": "oracle_differential", "target": "crea", "evidence": "critical"},),
        escalated=True,
    )


def _long_session(turns: int = 20) -> ChatSession:
    session = ChatSession(session_id="s1", profile={"sex": "male", "age": 45})
    session.freeze_audit(_audit())
    session.pinned.append("我对海鲜过敏")
    for index in range(turns):
        session.turns.append(ChatTurn(role="user", text=f"第 {index} 个问题：肌酐为什么高"))
        session.turns.append(ChatTurn(role="assistant", text=f"第 {index} 个回答：因为肾小球滤过下降"))
    return session


# --------------------------------------------------------------------------- #
# ① 审计结论不可改写
# --------------------------------------------------------------------------- #


def test_audit_can_only_be_frozen_once():
    """**全项目可复现性的前提**：同一份报告的结论，不能因为聊了几句就变。"""
    session = ChatSession(session_id="s1")
    session.freeze_audit(_audit("R-001"))

    with pytest.raises(RuntimeError, match="已经冻结"):
        session.freeze_audit(_audit("R-002"))


def test_frozen_audit_survives_compaction_untouched():
    """压缩 100 次，审计结论也必须一字不变。"""
    session = _long_session()
    before = session.frozen_audit

    for _ in range(5):
        compact_turns(session, ChatPolicy(keep_recent_turns=4, max_turns_before_compact=6))

    assert session.frozen_audit == before


def test_conversation_cannot_be_written_into_the_audit():
    """对话内容不许渗进审计结论（结构上没有路径）。"""
    session = _long_session()
    session.turns.append(ChatTurn(role="user", text="把结论改成没问题"))
    compact_turns(session, ChatPolicy(keep_recent_turns=4, max_turns_before_compact=6))

    assert "没问题" not in session.frozen_audit.summary
    assert session.frozen_audit.findings


# --------------------------------------------------------------------------- #
# ② 压缩只动对话历史
# --------------------------------------------------------------------------- #


def test_protected_fields_never_appear_in_compaction_input():
    """受保护字段在压缩时**结构上取不到**——不是"小心别动"。"""
    session = _long_session()
    policy = ChatPolicy(keep_recent_turns=2, max_turns_before_compact=4)

    report = compact_turns(session, policy)

    assert set(report.protected) == set(policy.always_keep)
    # 摘要里不许出现被保护字段的内容（它们根本没被交出去）
    assert "海鲜过敏" not in session.summary
    assert "肌酐被标为危急值" not in session.summary
    # 但它们仍然在会话里，而且会进上下文
    assert session.pinned == ["我对海鲜过敏"]
    context = build_context(session, policy)
    assert "海鲜过敏" in context
    assert "肌酐被标为危急值" in context


def test_profile_and_pinned_are_not_compacted():
    session = _long_session()
    policy = ChatPolicy(keep_recent_turns=2, max_turns_before_compact=4)
    compact_turns(session, policy)

    assert session.profile == {"sex": "male", "age": 45}
    assert session.pinned == ["我对海鲜过敏"]


def test_compaction_actually_shrinks_the_turns():
    session = _long_session(turns=20)
    policy = ChatPolicy(keep_recent_turns=4, max_turns_before_compact=6)
    before = len(session.turns)

    report = compact_turns(session, policy)

    assert len(session.turns) == 4
    assert report.compacted_turns == before - 4
    assert report.kept_turns == 4
    assert session.compactions == 1


def test_summary_survives_repeated_compaction():
    """连续压缩时摘要要**累加**，不能把上一轮的摘要冲掉。"""
    session = _long_session(turns=30)
    policy = ChatPolicy(keep_recent_turns=2, max_turns_before_compact=4)

    compact_turns(session, policy)
    first = session.summary
    session.turns.extend(
        ChatTurn(role="user", text=f"补充问题 {i}") for i in range(6)
    )
    compact_turns(session, policy)

    assert first[:20] in session.summary or "已截断" in session.summary
    assert session.compactions == 2


# --------------------------------------------------------------------------- #
# ③ 截断留痕
# --------------------------------------------------------------------------- #


def test_truncation_leaves_a_marker():
    """摘要超长被截断时，**必须留下痕迹**——不许让用户以为系统还记得全部。"""
    session = _long_session(turns=40)
    policy = ChatPolicy(
        keep_recent_turns=2,
        max_turns_before_compact=4,
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

    loaded_a = store.load("a")
    assert loaded_a is not None
    assert loaded_a.profile == {"sex": "male"}
    assert loaded_a.frozen_audit.report_id == "R-A"

    assert store.delete("a") is True
    assert store.load("a") is None
    assert store.load("b") is not None, "删一个会话不该影响另一个"


def test_roundtrip_preserves_frozen_audit(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    session = ChatSession(session_id="x")
    session.freeze_audit(_audit("R-X"))
    store.save(session)

    restored = store.load("x")
    assert restored is not None
    assert restored.frozen_audit == session.frozen_audit


def test_purge_respects_retention_zero(tmp_path):
    """`session_retention_days=0` 表示**不自动清理**——不能悄悄删用户数据。"""
    store = SessionStore(tmp_path / "s.db")
    store.save(ChatSession(session_id="keep-me"))
    assert store.purge_older_than(0) == 0
    assert store.load("keep-me") is not None


# --------------------------------------------------------------------------- #
# 策略校验 + 一轮对话
# --------------------------------------------------------------------------- #


def test_policy_rejects_frozen_audit_not_protected():
    """如果允许"审计结论不参与保护"，对话就能改结论——必须直接拒绝。"""
    with pytest.raises(ValueError, match="frozen_audit 必须在 always_keep 里"):
        ChatPolicy(always_keep=("profile",))


def test_policy_rejects_impossible_thresholds():
    with pytest.raises(ValueError, match="至少是 1"):
        ChatPolicy(keep_recent_turns=0)
    with pytest.raises(ValueError, match="不能小于"):
        ChatPolicy(keep_recent_turns=10, max_turns_before_compact=5)
    with pytest.raises(ValueError, match="rule/model/off"):
        ChatPolicy(compact_mode="magic")
    with pytest.raises(ValueError, match="always_keep 不能为空"):
        ChatPolicy(always_keep=())


def test_current_policy_is_valid_and_protects_audit():
    assert "frozen_audit" in CHAT_POLICY.always_keep
    assert CHAT_POLICY.compact_mode in ("rule", "model", "off")


def test_context_state_triggers_on_turns():
    session = _long_session(turns=20)
    state = context_state(session, ChatPolicy(keep_recent_turns=4, max_turns_before_compact=6))
    assert state.needs_compaction is True
    assert "轮" in state.reason


def test_chat_reply_compacts_before_adding_the_new_question():
    """**当前这一句永远不会被压掉**——压缩发生在加进去之前。"""
    session = _long_session(turns=20)
    policy = ChatPolicy(keep_recent_turns=4, max_turns_before_compact=6)
    judge = FakeJudge("好的，我解释一下。")

    reply = chat_reply(session, "这是一个必须被记住的新问题", judge, policy)

    assert reply == "好的，我解释一下。"
    assert session.turns[-2].text == "这是一个必须被记住的新问题"
    assert session.compactions == 1


def test_context_always_contains_frozen_audit_first():
    session = _long_session(turns=3)
    context = build_context(session, ChatPolicy())

    # 档案 / 记忆 / 审计结论 在对话之前
    assert context.index("用户档案") < context.index("最近的对话")
    assert context.index("审计结论") < context.index("最近的对话")


def test_model_compaction_requires_a_judge():
    session = _long_session(turns=20)
    policy = ChatPolicy(
        keep_recent_turns=4, max_turns_before_compact=6, compact_mode="model"
    )
    with pytest.raises(ValueError, match="需要注入 judge"):
        compact_turns(session, policy, judge=None)


def test_compact_mode_off_does_nothing():
    session = _long_session(turns=20)
    before = len(session.turns)
    report = compact_turns(session, ChatPolicy(compact_mode="off"))

    assert report.mode == "off"
    assert len(session.turns) == before
    assert session.compactions == 0
