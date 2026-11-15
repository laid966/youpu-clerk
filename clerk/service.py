"""编排层：询价 → 分类 → 决策 → 起草 → 护栏 → 落账。

## 管线（契约 docs/32 §1）

    买家消息 ─①classify─► {kind, language, offer}
                ②decide   仅当 kind=="bargain" 且 offer 非空 → clerk.bargain（engine，无模型）
                ③draft    LLM 或模板，用**买家的语言**起草
                ④guardrail 禁语 + 数字白名单；命中 → 整段替换安全模板
                ⑤record   messages + decisions（台账）落库，额度 +1

## 两个架构决定
1. **引擎只在有数字时介入**：其他消息没东西可"判"。这是"钱由程序算"的另一半——
   **模型永远不决定钱**，它只决定措辞。
2. **护栏是最后一道闸，不是第一道**：prompt 约束是第一道防线，但最后兜底的是
   程序化的数字白名单——模型无论怎么幻觉，授权集合外的数字出不去。

## judge 注入
`suggest(judge=None)` 自动选（有 key → DeepSeek+缓存；无 key → TemplateJudge）。
测试**必须**显式注入（TemplateJudge 或 FakeJudge），绝不联网、绝不确定性漂移。
演示模式（demo）由 server 层强制 TemplateJudge——评委现场没有我们的 key，
而且演示必须逐字节可复现。
"""

from __future__ import annotations

import sqlite3
import time
from decimal import Decimal
from typing import Any

from clerk import config, db
from clerk.bargain import BargainDecision, BargainError, BargainFacts, decide_bargain
from clerk.guardrails import scan_all
from clerk.prompts import (
    build_classify_prompt,
    build_draft_prompt,
    parse_classification,
    sanitize_draft,
)
from clerk.templates import (
    Classification,
    TemplateJudge,
    select_judge,
    template_classify,
    template_draft,
)

__all__ = [
    "ClerkError",
    "ItemNotFound",
    "QuotaExceeded",
    "SuggestionNotFound",
    "SOURCES",
    "adopt",
    "daily_report",
    "suggest",
]

SOURCES = ("paste", "extension", "demo")

_ENGINE_KINDS = ("accept", "counter", "firm", "human")


class ClerkError(ValueError):
    """业务层错误基类。server 把子类映射成契约的错误形状。"""


class ItemNotFound(ClerkError):
    def __init__(self, item_id: str) -> None:
        super().__init__(f"没有这个商品档案：{item_id}")
        self.item_id = item_id


class SuggestionNotFound(ClerkError):
    def __init__(self, suggestion_id: str) -> None:
        super().__init__(f"没有这条建议/决策：{suggestion_id}")
        self.suggestion_id = suggestion_id


class QuotaExceeded(ClerkError):
    """免费额度用尽。server 映射成 HTTP 402（契约 §0）——body 里带定价，前端直接弹付费引导。"""

    def __init__(self, used: int, limit: int) -> None:
        super().__init__(f"今日免费额度已用完（{used}/{limit}）")
        self.used = used
        self.limit = limit
        self.pricing = {
            "price_30d": str(config.PRICE_30D),
            "early_bird": str(config.PRICE_30D_EARLY_BIRD),
        }


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #


def suggest(
    *,
    token: str,
    item_id: str,
    message: str,
    conversation_id: str | None = None,
    source: str = "paste",
    judge: Any = None,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """处理一条买家消息，返回契约 §3 的 Suggestion dict。

    只有走到 ⑤record 才消耗额度：前面任何一步抛错（商品不存在、额度已尽），
    台账和额度都不动——**失败不留半截账**。
    """
    if not message or not message.strip():
        raise ClerkError("message 不能为空")
    if source not in SOURCES:
        raise ClerkError(f"非法来源：{source!r}（允许：{'/'.join(SOURCES)}）")

    own_conn = conn is None
    conn = conn if conn is not None else db.open_db()
    try:
        user = db.ensure_user(conn, token)
        _enforce_quota(conn, user)

        item = db.get_item(conn, token, item_id)
        if item is None:
            raise ItemNotFound(item_id)
        conv = db.get_or_create_conversation(conn, token, item_id, conversation_id or None)

        if judge is None:
            judge = select_judge()

        trace: list[dict] = []
        classification = _classify(message, judge, trace)
        db.set_conversation_language(conn, conv["id"], classification.language)
        decision = _decide(conn, item, conv, classification, trace)
        reply = _draft(message, item, classification, decision, judge, trace)
        reply, hits = _guard(reply, item, classification, decision, trace)

        message_id = db.add_message(conn, conv["id"], "buyer", message, classification.language)
        suggestion_id = db.add_decision(
            conn,
            conversation_id=conv["id"],
            item_id=item["id"],
            message_id=message_id,
            kind=decision.kind if decision is not None else "none",
            price=str(decision.price) if decision is not None and decision.price is not None else None,
            rule_id=decision.rule_id if decision is not None else None,
            citations=decision.citations if decision is not None else (),
            reasons=decision.reasons if decision is not None else (),
            requires_human_review=bool(decision is not None and decision.requires_human_review),
            judgement=decision.judgement.to_dict() if decision is not None else None,
            classification={
                "kind": classification.kind,
                "language": classification.language,
                "offer": str(classification.offer) if classification.offer is not None else None,
            },
            reply_text=reply,
            guardrail_hits=[hit.to_dict() for hit in hits],
        )
        used_today = db.bump_usage(conn, token, db.today_shanghai())

        return {
            "suggestion_id": suggestion_id,
            "conversation_id": conv["id"],
            "item": {
                "id": item["id"],
                "title": item["title"],
                "asking_price": item["asking_price"],
                "floor_price": item["floor_price"],
            },
            "classification": {
                "kind": classification.kind,
                "language": classification.language,
                "offer": str(classification.offer) if classification.offer is not None else None,
            },
            "decision": None
            if decision is None
            else {
                "kind": decision.kind,
                "price": str(decision.price) if decision.price is not None else None,
                "rule_id": decision.rule_id,
                "citations": list(decision.citations),
                "reasons": list(decision.reasons),
                "requires_human_review": decision.requires_human_review,
            },
            "reply_text": reply,
            "guardrail_hits": [hit.to_dict() for hit in hits],
            "trace": trace,
            "quota": {
                "used_today": used_today,
                "free_limit": config.FREE_DAILY_SUGGESTIONS,
                "plan": user["plan"],
            },
        }
    finally:
        if own_conn:
            conn.close()


def adopt(
    *,
    suggestion_id: str,
    action: str,
    final_text: str | None = None,
    token: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """采纳一条建议：sent/edited/discarded/escalated（一次性，不许改判）。

    sent/edited 会把实际发出的文本追加为 seller 消息（台账闭环）；
    edited 必须带 final_text——改成了什么必须留痕。
    返回按 I1 口径重新数出的 concessions_used。
    """
    own_conn = conn is None
    conn = conn if conn is not None else db.open_db()
    try:
        row = db.get_decision(conn, suggestion_id)
        if row is None:
            raise SuggestionNotFound(suggestion_id)
        if token is not None and row["token"] != token:
            # 越权访问报"不存在"而不是"无权限"——不向探测者泄露资源存在性
            raise SuggestionNotFound(suggestion_id)

        db.adopt_decision(conn, suggestion_id, action, final_text)
        if action in ("sent", "edited"):
            db.add_message(
                conn, row["conversation_id"], "seller", final_text or row["reply_text"], None
            )
        used = db.count_adopted_counters(conn, row["conversation_id"], row["item_id"])
        return {"ok": True, "concessions_used": used}
    finally:
        if own_conn:
            conn.close()


def daily_report(*, token: str, day: str | None = None, conn: sqlite3.Connection | None = None) -> dict:
    """战报卡的数据源：当天的台账汇总（契约 /api/report/daily）。"""
    own_conn = conn is None
    conn = conn if conn is not None else db.open_db()
    try:
        day = day or db.today_shanghai()
        rows = db.ledger_by_day(conn, token, day)
        kinds = [row["kind"] for row in rows]
        adopted = [row for row in rows if row["adopted"] in ("sent", "edited")]
        return {
            "day": day,
            "inquiries": len(rows),
            "bargain_related": sum(1 for kind in kinds if kind in _ENGINE_KINDS),
            "counters": kinds.count("counter"),
            "accepts": kinds.count("accept"),
            "firms": kinds.count("firm"),
            "humans": kinds.count("human"),
            "concessions_adopted": sum(
                1 for row in rows if row["kind"] == "counter" and row["adopted"] in ("sent", "edited")
            ),
            "adopted": len(adopted),
            "adopt_rate": round(len(adopted) / len(rows), 3) if rows else 0.0,
        }
    finally:
        if own_conn:
            conn.close()


# --------------------------------------------------------------------------- #
# 管线各步（每个函数写自己那一段 trace——"过程可见"是产品卖点，不是日志
# --------------------------------------------------------------------------- #


def _enforce_quota(conn: sqlite3.Connection, user: dict) -> None:
    if user["plan"] != "free":
        return
    used = db.get_usage(conn, user["token"], db.today_shanghai())
    if used >= config.FREE_DAILY_SUGGESTIONS:
        raise QuotaExceeded(used, config.FREE_DAILY_SUGGESTIONS)


def _classify(message: str, judge: Any, trace: list[dict]) -> Classification:
    started = time.perf_counter()
    if isinstance(judge, TemplateJudge):
        classification = template_classify(message)
        ok, note = True, f"模板分类 {classification.kind}/{classification.language}"
    else:
        classification = None
        try:
            raw = judge.complete(build_classify_prompt(message))
            classification = parse_classification(raw)
        except Exception:  # noqa: BLE001 — 网络/模型故障降级，不能让店主的客服跟着挂
            classification = None
        if classification is None:
            classification = template_classify(message)
            ok, note = False, "LLM 分类失败，降级模板"
        else:
            ok, note = True, f"LLM 分类 {classification.kind}/{classification.language}"
    if classification.offer is not None:
        note += f" offer={classification.offer}"
    trace.append({"step": "classify", "ok": ok, "ms": _ms(started), "note": note})
    return classification


def _decide(
    conn: sqlite3.Connection, item: dict, conv: dict, classification: Classification, trace: list[dict]
) -> BargainDecision | None:
    started = time.perf_counter()
    if classification.kind != "bargain" or classification.offer is None:
        trace.append(
            {"step": "decide", "ok": True, "ms": _ms(started), "note": "非议价消息，引擎未介入"}
        )
        return None

    used = db.count_adopted_counters(conn, conv["id"], item["id"])
    try:
        facts = BargainFacts(
            asking_price=Decimal(item["asking_price"]),
            buyer_offer=classification.offer,
            floor_price=Decimal(item["floor_price"]),
            concessions_used=used,
        )
        decision = decide_bargain(facts)
    except BargainError as exc:
        trace.append(
            {
                "step": "decide",
                "ok": False,
                "ms": _ms(started),
                "note": f"出价不构成合法事实，引擎未介入：{exc}",
            }
        )
        return None

    price_text = f" {decision.price}" if decision.price is not None else ""
    trace.append(
        {
            "step": "decide",
            "ok": True,
            "ms": _ms(started),
            "note": f"{decision.kind}{price_text} · {decision.rule_id or 'escalated'} · 已让步 {used} 次",
        }
    )
    return decision


def _draft(
    message: str,
    item: dict,
    classification: Classification,
    decision: BargainDecision | None,
    judge: Any,
    trace: list[dict],
) -> str:
    started = time.perf_counter()
    if isinstance(judge, TemplateJudge):
        reply = template_draft(decision=decision, classification=classification, item=item)
        trace.append(
            {"step": "draft", "ok": True, "ms": _ms(started), "note": f"模板话术（{classification.language}）"}
        )
        return reply

    reply: str | None = None
    try:
        raw = judge.complete(
            build_draft_prompt(
                decision=decision, classification=classification, item=item, message=message
            )
        )
        reply = sanitize_draft(raw)
    except Exception:  # noqa: BLE001 — 同上：模型挂了，客服不能挂
        reply = None

    if reply is None:
        reply = template_draft(decision=decision, classification=classification, item=item)
        trace.append(
            {"step": "draft", "ok": False, "ms": _ms(started), "note": "LLM 起草失败，降级安全模板"}
        )
    else:
        trace.append(
            {"step": "draft", "ok": True, "ms": _ms(started), "note": f"LLM 起草（{classification.language}）"}
        )
    return reply


def _guard(
    reply: str,
    item: dict,
    classification: Classification,
    decision: BargainDecision | None,
    trace: list[dict],
) -> tuple[str, list]:
    started = time.perf_counter()
    allowed: list[Decimal] = [Decimal(item["asking_price"])]
    if decision is not None and decision.price is not None:
        allowed.append(decision.price)
    if classification.offer is not None:
        allowed.append(classification.offer)

    hits = scan_all(reply, allowed=allowed, floor_price=Decimal(item["floor_price"]))
    if hits:
        # 整段替换，不做"局部打补丁"：被污染的文本修修补补只会漏——
        # 安全模板保证任何决策都有话可说（templates.py 的兜底承诺）
        reply = template_draft(decision=decision, classification=classification, item=item)
    trace.append(
        {
            "step": "guardrail",
            "ok": not hits,
            "ms": _ms(started),
            "note": "0 命中" if not hits else f"{len(hits)} 命中 → 已整段替换安全模板",
        }
    )
    return reply, hits
