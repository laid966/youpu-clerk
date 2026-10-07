"""agent：模型相关的层（听与说、护栏、语义检查、对话）。

    prompts.py        ★你的文件★ 审计提示词，带版本管理
    guardrails.py     ★你的文件★ 确定性护栏规则表
    chat_policy.py    ★你的文件★ 对话层策略：上下文预算、压缩口径、留存
    judge.py          模型调用的最小封装（可缓存、可替换、测试用假实现）
    semantic_check.py 用提示词判定"这段解释有没有越界"
    eval_semantic.py  评测你的提示词：召回、误报、错误
    chat.py           对话层机制：会话、上下文组装、压缩执行器、持久化

分层原则（与 engine 一致）：
**能用确定性规则判的，绝不交给模型。** 这里只处理词表抓不住的那部分——
比如「这个结果通常提示肝脏已经出现了实质性的损伤」这种改写过的诊断口吻。

对话层的原则（另一条）：
**审计器的判定必须无状态。** 审计结论进入对话后**冻结且只读**——
否则同一份报告在不同对话顺序下会得到不同结论，召回率就不再是确定的数字。
"""

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
from agent.eval_semantic import SemanticEvalReport, evaluate_semantic
from agent.judge import CachedJudge, DeepSeekJudge, FakeJudge, Judge, build_judge
from agent.semantic_check import SemanticFinding, check_text

__all__ = [
    "CHAT_POLICY",
    "CachedJudge",
    "ChatPolicy",
    "ChatSession",
    "ChatTurn",
    "DeepSeekJudge",
    "FakeJudge",
    "FrozenAudit",
    "Judge",
    "SemanticEvalReport",
    "SemanticFinding",
    "SessionStore",
    "build_context",
    "build_judge",
    "chat_reply",
    "check_text",
    "compact_turns",
    "context_state",
    "evaluate_semantic",
]
