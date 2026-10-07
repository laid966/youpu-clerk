"""对话层的**机制**：会话状态、上下文组装、压缩执行器、持久化。

策略全在 `agent/chat_policy.py`（★你的文件★）。这里只负责"照策略执行"。

## 单位约定（读代码前先看这段）

**一轮 = 一次问答 = 用户问 + 助手答。** 不是"一条消息"。

数据结构里 `messages` 是**消息列表**（用户一条、助手一条），因为那才是发给模型的东西；
但**所有策略阈值都按"次问答"算**，字段名里都带 `exchange`。

**为什么要区分**（这是踩过的坑）：

1. **问答是不可分割的语义单元**——保留问题却丢掉答案，用户看不到有用上下文
2. **消息数可能是奇数**（模型调用失败时只剩用户那句）——按"条"保留会把一对问答劈开，
   留下一个**没有答案的问题**

所以压缩按 `_split_exchanges()` **成对切**，落单的那条**永远保留、永不被压缩**。

## 四条硬约束（都有测试守着）

### ① 审计结论**一经冻结，不可改写**

`ChatSession.freeze_audit()` 只能调用一次，之后 `frozen_audit` 是**只读属性**。

**为什么必须这么硬**：如果对话能改结论，那"这份报告被判有问题"就取决于
用户跟你聊了什么——**审计器的可复现性就没了**，简历上那个 87.9% 也就不成立。

**方向是单向的：审计结论 → 对话（只读）。**

### ② 压缩**只动对话历史**，受保护字段**结构上取不到**

`always_keep` 里的字段（profile / frozen_audit / pinned）**根本不参与压缩**。
不是"摘要时小心一点"，而是**结构上拿不到**。

### ③ 截断必须留下痕迹

摘要超长时截断，**必须写出"有东西被截断了"**。
悄悄截断 = 让用户以为系统记得全部 —— 这比丢东西更危险。

### ④ 会话互相隔离，且可以单独删除

### ⑤ 模型调用失败必须**回滚**

失败时把已经加进去的用户消息**撤回**，让会话保持"问答成对"，
然后**把异常抛出去**（不静默）。
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
    "ChatMessage",
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
class ChatMessage:
    """**一条消息**（不是一轮对话）。一轮 = 两条消息（用户 + 助手）。"""

    role: str  # "user" | "assistant"
    text: str
    at: str = field(default_factory=_now)


#: 旧名字，保留以防外部引用。语义是**消息**，不是"轮"。
ChatTurn = ChatMessage


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
                lines.append(
                    f"  {index}. [{finding.get('kind', '?')}] "
                    f"{finding.get('target', '?')}　{finding.get('evidence', '')}"
                )
        else:
            lines.append("未报出任何条目。")
        return "\n".join(lines)


def _split_exchanges(
    messages: Sequence[ChatMessage],
) -> tuple[list[tuple[ChatMessage, ChatMessage]], tuple[ChatMessage, ...]]:
    """把消息列表切成**成对的问答** + 末尾可能落单的一条。

    **绝不把一对问答劈开。** 落单的那条（模型调用失败留下的）要单独处理，
    它代表"用户问了但还没答"，所以**永远保留、不参与压缩**。
    """
    pairs: list[tuple[ChatMessage, ChatMessage]] = []
    index = 0
    while index + 1 < len(messages):
        pairs.append((messages[index], messages[index + 1]))
        index += 2
    return pairs, tuple(messages[index:])


class ChatSession:
    """一个会话。**审计结论的写入路径只有一条，且只能走一次。**"""

    def __init__(
        self,
        session_id: str,
        profile: dict | None = None,
        pinned: Sequence[str] = (),
        messages: Sequence[ChatMessage] = (),
        summary: str = "",
        created_at: str | None = None,
        model_calls: int = 0,
        compactions: int = 0,
    ) -> None:
        self.session_id = session_id
        self.profile: dict = dict(profile or {})
        self.pinned: list[str] = list(pinned)
        self.messages: list[ChatMessage] = list(messages)
        self.summary = summary
        self.created_at = created_at or _now()
        self.model_calls = model_calls
        self.compactions = compactions
        self._frozen_audit: FrozenAudit | None = None

    # ---- 计数：一律按"次问答" ----

    @property
    def exchange_count(self) -> int:
        """已经完成的**问答次数**（用户问 + 助手答 = 1 次）。

        ⚠️ 不要用 `len(messages)` 代替它——那是消息条数，是它的两倍左右。
        """
        pairs, _dangling = _split_exchanges(self.messages)
        return len(pairs)

    @property
    def dangling_count(self) -> int:
        """落单的消息条数（正常情况下是 0；非 0 说明有一次失败留下了孤儿问题）。"""
        _pairs, dangling = _split_exchanges(self.messages)
        return len(dangling)

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
        """`always_keep` 声明的字段。**压缩只处理这个函数返回之外的东西。**"""
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
            "messages": [asdict(message) for message in self.messages],
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
            messages=[ChatMessage(**item) for item in payload.get("messages", [])],
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
    exchanges: int
    messages: int
    dangling: int
    chars: int
    needs_compaction: bool
    reason: str

    def describe(self) -> str:
        flag = "**需要压缩**" if self.needs_compaction else "不需要压缩"
        text = f"{self.exchanges} 次问答 / {self.messages} 条消息 / {self.chars} 字 → {flag}"
        if self.dangling:
            text += f"（⚠️ 有 {self.dangling} 条落单消息）"
        return f"{text}（{self.reason}）"


def _messages_chars(messages: Sequence[ChatMessage]) -> int:
    return sum(len(message.text) for message in messages)


def context_state(session: ChatSession, policy: ChatPolicy | None = None) -> ContextState:
    """当前上下文占了多少、要不要压缩。**按"次问答"判断。**"""
    policy = policy or CHAT_POLICY
    pairs, dangling = _split_exchanges(session.messages)
    exchanges = len(pairs)
    chars = _messages_chars(session.messages) + len(session.summary)

    def make(needs: bool, reason: str) -> ContextState:
        return ContextState(
            exchanges=exchanges,
            messages=len(session.messages),
            dangling=len(dangling),
            chars=chars,
            needs_compaction=needs,
            reason=reason,
        )

    if policy.compact_mode == "off":
        return make(False, "compact_mode=off，按你的设置不压缩")
    if exchanges > policy.max_exchanges_before_compact:
        return make(
            True, f"{exchanges} 次问答 > 上限 {policy.max_exchanges_before_compact}"
        )
    if chars > policy.context_char_budget:
        return make(True, f"{chars} 字 > 预算 {policy.context_char_budget}")
    return make(False, "在预算内")


@dataclass(frozen=True)
class CompactReport:
    compacted_exchanges: int
    kept_exchanges: int
    summary_chars: int
    mode: str
    truncated: bool
    protected: tuple[str, ...]

    def describe(self) -> str:
        text = (
            f"压缩 {self.compacted_exchanges} 次问答 → 保留 {self.kept_exchanges} 次问答原文"
            f"（{self.mode}）"
        )
        if self.truncated:
            text += "；摘要超长**已截断**（报告里留了标记）"
        text += f"；受保护未参与压缩：{list(self.protected)}"
        return text


def _rule_summary(messages: Sequence[ChatMessage], policy: ChatPolicy) -> str:
    """规则压缩：**确定性、免费、可测**。

    只做两件事（都不需要"理解"）：
    1. 保留用户**问过什么**（它定义了这个会话在聊什么）
    2. 保留回答的**开头片段**（要点通常在开头）

    刻意不做的事：不做真正的概括。规则做不了概括，
    **假装能做才是问题**——所以质量上限就是"能想起聊过什么"。
    """
    lines: list[str] = []
    if policy.compact_keep_user_questions:
        questions = [m.text for m in messages if m.role == "user"]
        if questions:
            joined = "；".join(q.strip().replace("\n", " ")[:40] for q in questions[-12:])
            lines.append(f"用户问过：{joined}")
    answers = [m.text for m in messages if m.role == "assistant"]
    if answers:
        joined = "；".join(a.strip().replace("\n", " ")[:40] for a in answers[-6:])
        lines.append(f"已答要点：{joined}")
    return "\n".join(lines)


def _merge_summary(old: str, new: str, limit: int) -> tuple[str, bool]:
    """把新摘要接到旧摘要后面，超长就**截断并留标记**（保留较新的部分）。"""
    merged = f"{old}\n{new}".strip() if old else new.strip()
    if len(merged) <= limit:
        return merged, False
    kept = merged[-limit:]
    return f"…（更早的摘要已被截断）\n{kept}", True


def compact_turns(
    session: ChatSession,
    policy: ChatPolicy | None = None,
    judge: Judge | None = None,
) -> CompactReport:
    """执行一次压缩。**只动 `messages` 与 `summary`，而且按"次问答"成对切。**

    受保护字段（`policy.always_keep`）在这个函数里**取不到**——
    不是"小心别动"，是结构上拿不到。
    """
    policy = policy or CHAT_POLICY
    protected = tuple(session.protected(policy))

    if policy.compact_mode == "off":
        return CompactReport(0, session.exchange_count, len(session.summary), "off", False, protected)

    pairs, dangling = _split_exchanges(session.messages)
    keep = policy.keep_recent_exchanges

    if len(pairs) <= keep:
        return CompactReport(
            0, len(pairs), len(session.summary), policy.compact_mode, False, protected
        )

    old_pairs = pairs[:-keep]
    kept_pairs = pairs[-keep:]
    old_messages = [message for pair in old_pairs for message in pair]
    kept_messages = [message for pair in kept_pairs for message in pair]

    if policy.compact_mode == "model":
        if judge is None:
            raise ValueError("compact_mode=model 需要注入 judge（见 agent/judge.py 的 build_judge）")
        prompt = (
            "把下面这段体检解读对话压缩成要点，保留：用户问过什么、给出了什么结论、"
            "有没有未解决的问题。不要新增任何信息。\n\n"
            + "\n".join(f"[{m.role}] {m.text}" for m in old_messages)
        )
        new_summary = judge.complete(prompt)
        session.model_calls += 1
    else:
        new_summary = _rule_summary(old_messages, policy)

    merged, truncated = _merge_summary(session.summary, new_summary, policy.compact_summary_chars)
    session.summary = merged
    # 落单的那条（用户问了还没答）**永远保留**，绝不被压掉
    session.messages = kept_messages + list(dangling)
    session.compactions += 1

    return CompactReport(
        compacted_exchanges=len(old_pairs),
        kept_exchanges=len(kept_pairs),
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

    if session.profile:
        blocks.append(
            "【用户档案】" + "，".join(f"{key}={value}" for key, value in session.profile.items())
        )
    if session.pinned:
        blocks.append("【用户要求记住的事】" + "；".join(session.pinned))
    if session.frozen_audit is not None:
        blocks.append(session.frozen_audit.as_context())
    if session.summary:
        blocks.append(f"【较早对话的摘要】\n{session.summary}")
    if session.messages:
        blocks.append(
            "【最近的对话】\n"
            + "\n".join(f"[{message.role}] {message.text}" for message in session.messages)
        )

    return "\n\n".join(blocks)


def chat_reply(
    session: ChatSession,
    user_text: str,
    judge: Judge,
    policy: ChatPolicy | None = None,
) -> str:
    """一轮对话：**先按需压缩 → 组装上下文 → 调模型 → 记录**。

    ⚠️ 两个刻意的顺序安排：

    1. **压缩发生在加入新问题之前**，所以当前这一句永远不会被压掉
    2. **模型调用失败时回滚**（撤掉刚加的用户消息）——否则会留下一个孤儿问题，
       破坏"问答成对"，下次压缩就会把一对问答劈开。**异常照原样抛出去，不静默。**
    """
    policy = policy or CHAT_POLICY

    state = context_state(session, policy)
    if state.needs_compaction:
        compact_turns(session, policy=policy, judge=judge)

    session.messages.append(ChatMessage(role="user", text=user_text))
    try:
        prompt = CHAT_PROMPT.replace("{context}", build_context(session, policy))
        reply = judge.complete(prompt)
    except Exception:
        session.messages.pop()  # 回滚：不留孤儿问题
        raise

    session.model_calls += 1
    session.messages.append(ChatMessage(role="assistant", text=str(reply)))
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
            if stamp < cutoff and self.delete(session_id):
                removed += 1
        return removed
