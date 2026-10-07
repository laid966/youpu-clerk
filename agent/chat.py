"""对话层的**机制**：会话状态、上下文组装、压缩执行器、持久化。

策略全在 `agent/chat_policy.py`（★你的文件★）。这里只负责"照策略执行"。

## 四条硬约束（都有测试守着）

### ① 审计结论**一经冻结，不可改写**

`ChatSession.freeze_audit()` 只能调用一次，之后 `frozen_audit` 是**只读属性**。
对话层没有、也不会提供任何修改它的路径。

**为什么必须这么硬**：如果对话能改结论，那"这份报告被判有问题"就取决于
用户跟你聊了什么——**审计器的可复现性就没了**，简历上那个 87.9% 也就不成立。

**方向是单向的：审计结论 → 对话（只读）。**

### ② 压缩**只动对话历史**，不碰受保护的字段

`always_keep` 里列的字段（profile / frozen_audit / pinned）**根本不参与压缩**——
不是"摘要时小心一点"，而是**结构上取不到**。

**为什么**：靠摘要保住"我对海鲜过敏"是不可验证的承诺；字段保护是可测的。

### ③ 截断必须留下痕迹

摘要超长时截断，**必须写出"有东西被截断了"**。
悄悄截断 = 让用户以为系统记得全部 —— 这比丢东西更危险。

### ④ 会话互相隔离

每个会话有独立 id 与独立存储行，互不影响；可以单独删除。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from agent.chat_policy import CHAT_POLICY, CHAT_PROMPT, ChatPolicy
from agent.judge import Judge

__all__ = [
    "ChatSession",
    "ChatTurn",
    "CompactReport",
    "ContextState",
    "FrozenAudit",
    "SessionStore",
    "build_context",
    "chat_reply",
    "compact_turns",
    "context_state",
]

ROOT = Path(__file__).resolve().parents[1]
SESSION_DB = ROOT / "data" / "chat-sessions.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# 数据
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ChatTurn:
    role: str  # "user" | "assistant"
    text: str
    at: str = field(default_factory=_now)


@dataclass(frozen=True)
class FrozenAudit:
    """**冻结的**审计结论。对话层只能读它。"""

    report_id: str
    summary: str
    findings: tuple[dict, ...] = ()
    escalated: bool = False
    frozen_at: str = field(default_factory=_now)

    def as_context(self) -> str:
        lines = [
            f"【本报告的审计结论（只读事实）】报告 {self.report_id}",
            f"结论摘要：{self.summary}",
        ]
        if self.escalated:
            lines.append("该报告已被标记为**需要人工复核**。")
        if self.findings:
            lines.append("报出的条目：")
            for index, finding in enumerate(self.findings, start=1):
                kind = finding.get("kind", "?")
                target = finding.get("target", "?")
                evidence = finding.get("evidence", "")
                lines.append(f"  {index}. [{kind}] {target}　{evidence}")
        else:
            lines.append("未报出任何条目。")
        return "\n".join(lines)


class ChatSession:
    """一个会话。**审计结论的写入路径只有一条，且只能走一次。**"""

    def __init__(
        self,
        session_id: str,
        profile: dict | None = None,
        pinned: Sequence[str] = (),
        turns: Sequence[ChatTurn] = (),
        summary: str = "",
        created_at: str | None = None,
        model_calls: int = 0,
        compactions: int = 0,
    ) -> None:
        self.session_id = session_id
        self.profile: dict = dict(profile or {})
        self.pinned: list[str] = list(pinned)
        self.turns: list[ChatTurn] = list(turns)
        self.summary = summary
        self.created_at = created_at or _now()
        self.model_calls = model_calls
        self.compactions = compactions
        self._frozen_audit: FrozenAudit | None = None

    # ---- ① 冻结：只能设一次 ----

    @property
    def frozen_audit(self) -> FrozenAudit | None:
        return self._frozen_audit

    def freeze_audit(self, audit: FrozenAudit) -> None:
        """把审计结论写进会话。**只能调用一次。**

        第二次调用会报错——这是有意的：结论一旦进入对话就不该再变，
        否则"同一份报告永远得到同一个结论"这条不变量就没了。
        """
        if self._frozen_audit is not None:
            raise RuntimeError(
                f"会话 {self.session_id} 的审计结论已经冻结（{self._frozen_audit.report_id}）。\n"
                "  要换结论请**新建会话**，不要在对话里改已冻结的结论。"
            )
        self._frozen_audit = audit

    # ---- 受保护字段（压缩取不到） ----

    def protected(self, policy: ChatPolicy) -> dict:
        """`always_keep` 声明的字段。**压缩只接受这个函数返回之外的东西处理。**"""
        available = {
            "profile": self.profile,
            "frozen_audit": self._frozen_audit.as_context() if self._frozen_audit else None,
            "pinned": list(self.pinned),
        }
        return {name: available[name] for name in policy.always_keep if name in available}

    # ---- 序列化 ----

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "profile": self.profile,
            "pinned": self.pinned,
            "turns": [asdict(turn) for turn in self.turns],
            "summary": self.summary,
            "created_at": self.created_at,
            "model_calls": self.model_calls,
            "compactions": self.compactions,
            "frozen_audit": asdict(self._frozen_audit) if self._frozen_audit else None,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ChatSession":
        session = cls(
            session_id=payload["session_id"],
            profile=payload.get("profile"),
            pinned=payload.get("pinned", ()),
            turns=[ChatTurn(**turn) for turn in payload.get("turns", [])],
            summary=payload.get("summary", ""),
            created_at=payload.get("created_at"),
            model_calls=payload.get("model_calls", 0),
            compactions=payload.get("compactions", 0),
        )
        frozen = payload.get("frozen_audit")
        if frozen:
            session._frozen_audit = FrozenAudit(
                report_id=frozen["report_id"],
                summary=frozen["summary"],
                findings=tuple(frozen.get("findings", ())),
                escalated=frozen.get("escalated", False),
                frozen_at=frozen.get("frozen_at", _now()),
            )
        return session


# --------------------------------------------------------------------------- #
# 上下文预算与压缩
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ContextState:
    turns: int
    chars: int
    needs_compaction: bool
    reason: str

    def describe(self) -> str:
        flag = "**需要压缩**" if self.needs_compaction else "不需要压缩"
        return f"对话 {self.turns} 轮 / {self.chars} 字 → {flag}（{self.reason}）"


def _turns_chars(turns: Sequence[ChatTurn]) -> int:
    return sum(len(turn.text) for turn in turns)


def context_state(session: ChatSession, policy: ChatPolicy | None = None) -> ContextState:
    """当前上下文占了多少、要不要压缩。"""
    policy = policy or CHAT_POLICY
    turns = len(session.turns)
    chars = _turns_chars(session.turns) + len(session.summary)

    if policy.compact_mode == "off":
        return ContextState(turns, chars, False, "compact_mode=off，按你的设置不压缩")

    if turns > policy.max_turns_before_compact:
        return ContextState(
            turns, chars, True, f"{turns} 轮 > 上限 {policy.max_turns_before_compact}"
        )
    if chars > policy.context_char_budget:
        return ContextState(turns, chars, True, f"{chars} 字 > 预算 {policy.context_char_budget}")
    return ContextState(turns, chars, False, "在预算内")


@dataclass(frozen=True)
class CompactReport:
    compacted_turns: int
    kept_turns: int
    summary_chars: int
    mode: str
    truncated: bool
    protected: tuple[str, ...]

    def describe(self) -> str:
        text = (
            f"压缩 {self.compacted_turns} 轮 → 保留 {self.kept_turns} 轮原文，"
            f"摘要 {self.summary_chars} 字（{self.mode}）"
        )
        if self.truncated:
            text += "；摘要超长**已截断**（报告里留了标记）"
        text += f"；受保护未参与压缩：{list(self.protected)}"
        return text


def _rule_summary(old_turns: Sequence[ChatTurn], policy: ChatPolicy) -> str:
    """规则压缩：**确定性、免费、可测**。

    只做两件事（都不需要"理解"）：
    1. 保留用户**问过什么**（它定义了这个会话在聊什么）
    2. 保留回答的**开头片段**（要点通常在开头）

    刻意不做的事：不做真正的概括。规则做不了概括，
    **假装能做才是问题**——所以质量上限就是"能想起聊过什么"。
    """
    lines: list[str] = []
    if policy.compact_keep_user_questions:
        questions = [turn.text for turn in old_turns if turn.role == "user"]
        if questions:
            joined = "；".join(q.strip().replace("\n", " ")[:40] for q in questions[-12:])
            lines.append(f"用户问过：{joined}")
    answers = [turn.text for turn in old_turns if turn.role == "assistant"]
    if answers:
        joined = "；".join(a.strip().replace("\n", " ")[:40] for a in answers[-6:])
        lines.append(f"已答要点：{joined}")
    return "\n".join(lines)


def _merge_summary(old: str, new: str, limit: int) -> tuple[str, bool]:
    """把新摘要接到旧摘要后面，超长就**截断并留标记**（保留较新的部分）。"""
    merged = f"{old}\n{new}".strip() if old else new.strip()
    if len(merged) <= limit:
        return merged, False
    # 保留靠后的（较新的）内容——最近说过的更相关
    kept = merged[-limit:]
    return f"…（更早的摘要已被截断）\n{kept}", True


def compact_turns(
    session: ChatSession,
    policy: ChatPolicy | None = None,
    judge: Judge | None = None,
) -> CompactReport:
    """执行一次压缩。**只动 `turns` 与 `summary`。**

    受保护字段（`policy.always_keep`）**在这个函数里取不到**——
    不是"小心别动"，是结构上拿不到。
    """
    policy = policy or CHAT_POLICY
    protected = tuple(session.protected(policy))

    if policy.compact_mode == "off":
        return CompactReport(0, len(session.turns), len(session.summary), "off", False, protected)

    keep = policy.keep_recent_turns
    if len(session.turns) <= keep:
        return CompactReport(0, len(session.turns), len(session.summary), policy.compact_mode, False, protected)

    old_turns = session.turns[:-keep]
    kept_turns = session.turns[-keep:]

    if policy.compact_mode == "model":
        if judge is None:
            raise ValueError("compact_mode=model 需要注入 judge（见 agent/judge.py 的 build_judge）")
        prompt = (
            "把下面这段体检解读对话压缩成要点，保留：用户问过什么、给出了什么结论、"
            "有没有未解决的问题。不要新增任何信息。\n\n"
            + "\n".join(f"[{t.role}] {t.text}" for t in old_turns)
        )
        new_summary = judge.complete(prompt)
        session.model_calls += 1
    else:
        new_summary = _rule_summary(old_turns, policy)

    merged, truncated = _merge_summary(session.summary, new_summary, policy.compact_summary_chars)
    session.summary = merged
    session.turns = list(kept_turns)
    session.compactions += 1

    return CompactReport(
        compacted_turns=len(old_turns),
        kept_turns=len(kept_turns),
        summary_chars=len(merged),
        mode=policy.compact_mode,
        truncated=truncated,
        protected=protected,
    )


# --------------------------------------------------------------------------- #
# 组装上下文 + 对话
# --------------------------------------------------------------------------- #


def build_context(session: ChatSession, policy: ChatPolicy | None = None) -> str:
    """把会话组装成送进模型的文本。**受保护字段永远在最前面。**"""
    policy = policy or CHAT_POLICY
    blocks: list[str] = []

    profile = session.profile
    if profile:
        blocks.append(
            "【用户档案】" + "，".join(f"{key}={value}" for key, value in profile.items())
        )
    if session.pinned:
        blocks.append("【用户要求记住的事】" + "；".join(session.pinned))
    if session.frozen_audit is not None:
        blocks.append(session.frozen_audit.as_context())
    if session.summary:
        blocks.append(f"【较早对话的摘要】\n{session.summary}")
    if session.turns:
        blocks.append(
            "【最近的对话】\n"
            + "\n".join(f"[{turn.role}] {turn.text}" for turn in session.turns)
        )

    return "\n\n".join(blocks)


def chat_reply(
    session: ChatSession,
    user_text: str,
    judge: Judge,
    policy: ChatPolicy | None = None,
) -> str:
    """一轮对话：**先按需压缩 → 组装上下文 → 调模型 → 记录**。

    ⚠️ 压缩发生在"把新问题加进去之前"，所以**当前这一句永远不会被压掉**。
    """
    policy = policy or CHAT_POLICY

    state = context_state(session, policy)
    if state.needs_compaction:
        compact_turns(session, policy=policy, judge=judge)

    session.turns.append(ChatTurn(role="user", text=user_text))
    context = build_context(session, policy)
    prompt = CHAT_PROMPT.replace("{context}", context)

    reply = judge.complete(prompt)
    session.model_calls += 1
    session.turns.append(ChatTurn(role="assistant", text=str(reply)))
    return str(reply)


# --------------------------------------------------------------------------- #
# 持久化（可单独删除）
# --------------------------------------------------------------------------- #


class SessionStore:
    """会话的 SQLite 存储。**每个会话一行，可以单独删。**"""

    def __init__(self, path: str | Path = SESSION_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_sessions ("
                "  session_id TEXT PRIMARY KEY,"
                "  payload TEXT NOT NULL,"
                "  updated_at TEXT NOT NULL"
                ")"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(self, session: ChatSession) -> None:
        payload = json.dumps(session.to_dict(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chat_sessions (session_id, payload, updated_at) "
                "VALUES (?, ?, ?)",
                (session.session_id, payload, _now()),
            )

    def load(self, session_id: str) -> ChatSession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM chat_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return ChatSession.from_dict(json.loads(row[0])) if row else None

    def list_ids(self) -> tuple[str, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id FROM chat_sessions ORDER BY updated_at DESC"
            ).fetchall()
        return tuple(row[0] for row in rows)

    def delete(self, session_id: str) -> bool:
        """单独删除一个会话（隐私要求）。"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM chat_sessions WHERE session_id = ?", (session_id,)
            )
        return bool(cursor.rowcount)

    def delete_all(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM chat_sessions")
        return int(cursor.rowcount)

    def purge_older_than(self, days: int) -> int:
        """按留存策略清理。`days=0` 表示不自动清理。"""
        if days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
        removed = 0
        with self._connect() as conn:
            rows = conn.execute("SELECT session_id, updated_at FROM chat_sessions").fetchall()
        for session_id, updated_at in rows:
            try:
                stamp = datetime.fromisoformat(updated_at).timestamp()
            except ValueError:
                continue
            if stamp < cutoff:
                if self.delete(session_id):
                    removed += 1
        return removed
