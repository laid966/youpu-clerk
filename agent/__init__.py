"""agent：模型相关的层（听与说、护栏、语义检查）。

    prompts.py        ★你的文件★ 审计提示词，带版本管理
    guardrails.py     ★你的文件★ 确定性护栏规则表
    judge.py          模型调用的最小封装（可缓存、可替换、测试用假实现）
    semantic_check.py 用提示词判定"这段解释有没有越界"
    eval_semantic.py  评测你的提示词：召回、误报、错误

分层原则（与 engine 一致）：
**能用确定性规则判的，绝不交给模型。** 这里只处理词表抓不住的那部分——
比如「这个结果通常提示肝脏已经出现了实质性的损伤」这种改写过的诊断口吻。
"""

from agent.eval_semantic import SemanticEvalReport, evaluate_semantic
from agent.judge import CachedJudge, DeepSeekJudge, FakeJudge, Judge, build_judge
from agent.semantic_check import SemanticFinding, check_text

__all__ = [
    "CachedJudge",
    "DeepSeekJudge",
    "FakeJudge",
    "Judge",
    "SemanticEvalReport",
    "SemanticFinding",
    "build_judge",
    "check_text",
    "evaluate_semantic",
]
