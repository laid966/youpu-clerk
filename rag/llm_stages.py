"""LLM 两级的机制：查询改写 与 listwise 重排。

**提示词在你的文件里**（`rag/llm_prompts.py`），这里只管：

- 填模板、调模型、解析输出
- **解析失败 = 错误**，绝不静默退回（否则失败会被伪装成成功）
- 计数：调用了几次、错了几次、真的改写了几次
- 全部走 `agent/judge.py` 的 `CachedJudge`，**同一问句重跑不花钱**

## 为什么必须走缓存

评测要反复跑。没有缓存，每次对比都要重新花钱，而且**结果不可复现**
（模型有随机性）。缓存让"同一版提示词重跑"免费且确定——
只有真的改了提示词才会产生新调用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Sequence

from agent.judge import Judge
from rag import llm_prompts
from rag.retriever import Hit

__all__ = ["LlmStages", "RerankOutcome", "RewriteOutcome"]

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")

#: 最多把多少条候选交给模型重排。太多既贵又容易让它分心。
RERANK_WINDOW = 10

#: 改写的词最多用几个（防止模型话多把原问题淹掉）。
MAX_REWRITE_TERMS = 8


@dataclass(frozen=True)
class RewriteOutcome:
    terms: tuple[str, ...] = ()
    error: str | None = None
    raw: str = ""


@dataclass(frozen=True)
class RerankOutcome:
    order: tuple[int, ...] = ()
    error: str | None = None
    raw: str = ""


@dataclass
class LlmStageStats:
    """这两级花了多少、错了多少。**错误要单独计数，不能藏。**"""

    rewrite_calls: int = 0
    rewrite_applied: int = 0
    rerank_calls: int = 0
    rerank_applied: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)

    def note_error(self, message: str) -> None:
        self.errors += 1
        if len(self.error_samples) < 5:
            self.error_samples.append(message)

    def to_dict(self) -> dict:
        return {
            "rewrite_calls": self.rewrite_calls,
            "rewrite_applied": self.rewrite_applied,
            "rerank_calls": self.rerank_calls,
            "rerank_applied": self.rerank_applied,
            "errors": self.errors,
        }


def _extract_json(raw: str) -> dict:
    """从模型输出里取 JSON。**取不到就抛，不猜。**"""
    text = _FENCE.sub("", raw.strip())
    match = _JSON_BLOCK.search(text)
    if match is None:
        raise ValueError(f"模型输出里找不到 JSON：{raw[:120]!r}")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型输出的 JSON 无法解析：{match.group(0)[:120]!r}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"模型输出的 JSON 不是对象：{payload!r}")
    return payload


class LlmStages:
    """把两个 LLM 级包成一个对象，便于注入 pipeline 和统计。"""

    def __init__(self, judge: Judge) -> None:
        self.judge = judge
        self.stats = LlmStageStats()

    # ------------------------------------------------------------------ #
    # 查询改写
    # ------------------------------------------------------------------ #

    def rewrite(self, query: str) -> RewriteOutcome:
        self.stats.rewrite_calls += 1
        prompt = llm_prompts.REWRITE_PROMPT.replace("{query}", query)
        try:
            raw = self.judge.complete(prompt)
        except Exception as exc:  # noqa: BLE001 — 调用失败要显式暴露
            message = f"改写调用失败：{type(exc).__name__}: {exc}"
            self.stats.note_error(message)
            return RewriteOutcome(error=message)

        try:
            payload = _extract_json(raw)
        except ValueError as exc:
            self.stats.note_error(str(exc))
            return RewriteOutcome(error=str(exc), raw=raw)

        raw_terms = payload.get("terms")
        if not isinstance(raw_terms, list):
            message = f"改写输出里 terms 不是列表：{payload!r}"
            self.stats.note_error(message)
            return RewriteOutcome(error=message, raw=raw)

        terms: list[str] = []
        for item in raw_terms:
            term = str(item).strip()
            # 丢掉空词和过长的"句子"——模型有时会写一整句话，那不是检索词
            if term and len(term) <= 12 and term not in terms:
                terms.append(term)
        terms = terms[:MAX_REWRITE_TERMS]

        self.stats.rewrite_applied += 1
        return RewriteOutcome(terms=tuple(terms), raw=raw)

    def expand_query(self, query: str) -> str:
        """把改写结果拼进检索问句。

        **用"拼接"而不是"替换"**：改写错了顶多引入一点噪音，
        不至于把原问题丢掉——和"软路由"同一个思路：
        **让判断错误可恢复。**
        """
        outcome = self.rewrite(query)
        if outcome.error or not outcome.terms:
            return query
        return f"{query} {' '.join(outcome.terms)}"

    # ------------------------------------------------------------------ #
    # 重排
    # ------------------------------------------------------------------ #

    def rerank(self, query: str, hits: Sequence[Hit]) -> tuple[list[Hit], RerankOutcome]:
        candidates = list(hits)[:RERANK_WINDOW]
        if len(candidates) <= 1:
            return list(hits), RerankOutcome(order=tuple(range(len(candidates))))

        self.stats.rerank_calls += 1
        items = "\n".join(
            f"{index}. {hit.title}｜{hit.text[:60]}"
            for index, hit in enumerate(candidates, start=1)
        )
        prompt = (
            llm_prompts.RERANK_PROMPT.replace("{query}", query)
            .replace("{count}", str(len(candidates)))
            .replace("{items}", items)
        )
        try:
            raw = self.judge.complete(prompt)
        except Exception as exc:  # noqa: BLE001
            message = f"重排调用失败：{type(exc).__name__}: {exc}"
            self.stats.note_error(message)
            return list(hits), RerankOutcome(error=message)

        try:
            payload = _extract_json(raw)
        except ValueError as exc:
            self.stats.note_error(str(exc))
            return list(hits), RerankOutcome(error=str(exc), raw=raw)

        raw_order = payload.get("order")
        if not isinstance(raw_order, list):
            message = f"重排输出里 order 不是列表：{payload!r}"
            self.stats.note_error(message)
            return list(hits), RerankOutcome(error=message, raw=raw)

        # 校验编号：必须是候选范围内的整数、不重复。
        # **越界或重复的编号一律整条作废**，不做部分采纳——
        # 部分采纳会让"模型给了半个有效答案"这种状态悄悄混进结果。
        order: list[int] = []
        for item in raw_order:
            if not isinstance(item, int) or isinstance(item, bool):
                message = f"重排输出的编号不是整数：{item!r}"
                self.stats.note_error(message)
                return list(hits), RerankOutcome(error=message, raw=raw)
            if not 1 <= item <= len(candidates):
                message = f"重排编号越界：{item}（候选共 {len(candidates)} 条）"
                self.stats.note_error(message)
                return list(hits), RerankOutcome(error=message, raw=raw)
            if item in order:
                message = f"重排编号重复：{item}"
                self.stats.note_error(message)
                return list(hits), RerankOutcome(error=message, raw=raw)
            order.append(item)

        # 模型只排了它认为相关的几条——**这是允许的，也是我们希望的**
        # （提示词里要求"不相关的不要出现"）。剩下的按原顺序接在后面。
        ranked = [candidates[index - 1] for index in order]
        remaining = [hit for position, hit in enumerate(candidates, start=1) if position not in order]
        tail = list(hits)[RERANK_WINDOW:]

        self.stats.rerank_applied += 1
        return ranked + remaining + tail, RerankOutcome(order=tuple(order), raw=raw)
