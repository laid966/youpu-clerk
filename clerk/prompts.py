"""★ 这是你的文件 ★ 分类与起草提示词 + 它们的解析器。

## 分工
- CLASSIFY_PROMPT：买家消息 → {kind, language, offer}。offer 提取不到必须 null——**绝不猜**。
- DRAFT_PROMPT：决策 + 商品 + 买家消息 → 一句买家语言的话术。

## 硬约束写在 prompt 里，但**不指望 prompt**
提示词只是第一道防线。最后一道闸是 clerk/guardrails.py 的数字白名单——
**程序拦截，不靠模型自觉**。模型幻觉出底价？出授权外的价格？话术会被整段替换。
这是 auditkit 的老教训："配置看着生效了，实际永远匹配不到"的反面——
这里的约束是结构性的，不依赖任何一方的自觉。

## 迭代方式（auditkit 老规矩）
- 改完跑 `pytest -q -k clerk`；
- CachedJudge 的缓存键含提示词哈希——改了提示词必然重新调用模型，重跑不花钱的前提是**没改**；
- 真实坏例收进 tests/test_clerk_service.py，让它变成回归测试。
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

from clerk.bargain import BargainError, to_money
from clerk.templates import KINDS, Classification

__all__ = [
    "CLASSIFY_PROMPT",
    "DRAFT_PROMPT",
    "PROMPT_VERSION",
    "build_classify_prompt",
    "build_draft_prompt",
    "parse_classification",
    "sanitize_draft",
]

PROMPT_VERSION = "clerk-v1"

CLASSIFY_PROMPT = """你是二手交易平台的消息分类器。读买家消息，只输出一个 JSON 对象，不要任何别的文字：

{{"kind": "<bargain|opening|chitchat|aftersale|other>", "language": "<zh|en>", "offer": "<数字字符串或null>"}}

判定规则：
- bargain：买家给出了具体出价（数字）；offer 填该数字（单位元，字符串，如 "150.00"）
- opening：买家问"能不能便宜/刀吗"但没有具体数字；offer 必须为 null
- aftersale：退货/换货/破损/投诉类
- chitchat：打招呼、问"还在吗"
- other：以上都不是
- language：买家消息的主要语言，只能是 zh 或 en
- offer 提取不到确切数字时必须为 null——**绝不猜测，绝不把与价格无关的数字（数量、日期、成色）当作出价**

买家消息：
{message}"""

DRAFT_PROMPT = """你是二手卖家的客服助手，替店主回复买家。只输出回复文本本身，不要引号、不要解释。

硬约束（违反任何一条都是事故，程序会拦截并整段替换）：
1. 只许引用这些数字：决策价 {decision_price}、挂牌价 {asking_price}、买家出价 {buyer_offer}。
   底价绝对不能提，其他任何数字绝对不能出现。
2. 决策类型：{decision_kind}。你的话术必须与它一致：
   - accept = 答应按买家出价成交
   - counter = 还价到决策价
   - firm = 价格已到底，守住不再降
   - human = 这单需要店主亲自确认，先礼貌稳住（不报任何价格）
   - opening/chitchat/aftersale/other = 按消息类型自然应对，不主动报价
3. 不许承诺决策之外的事（不承诺包邮、退换、到货时效）。
4. 用{language_desc}回复，语气像友善的二手卖家，简短（中文≤50字 / 英文≤35词），最多一个表情符号。

商品：{item_title}（挂牌价 {asking_price} 元）
买家消息：{message}

直接回复："""

_LANGUAGE_DESC = {"zh": "中文", "en": "English"}


def build_classify_prompt(message: str) -> str:
    return CLASSIFY_PROMPT.format(message=message)


def build_draft_prompt(*, decision, classification: Classification, item: dict, message: str) -> str:
    """decision 可以为 None（非议价消息）：此时 decision_kind 用分类类型、决策价为"无"。"""
    decision_kind = decision.kind if decision is not None else classification.kind
    decision_price = (
        str(decision.price)
        if decision is not None and decision.price is not None
        else "无"
    )
    buyer_offer = str(classification.offer) if classification.offer is not None else "无"
    return DRAFT_PROMPT.format(
        decision_price=decision_price,
        asking_price=item["asking_price"],
        buyer_offer=buyer_offer,
        decision_kind=decision_kind,
        language_desc=_LANGUAGE_DESC.get(classification.language, "中文"),
        item_title=item["title"],
        message=message,
    )


def parse_classification(raw: str) -> Classification | None:
    """解析 LLM 的分类输出。任何解析失败都返回 None（调用方降级模板），绝不猜。

    容错：剥 ```json 围栏、从杂质文本里捞第一个 {...}。
    但**语义**不容错：kind 不认识、offer 不是合法金额 → 一律 None。
    """
    text = (raw or "").strip()
    if not text:
        return None
    text = text.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", text, re.S)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    kind = str(data.get("kind", "")).strip().lower()
    if kind not in KINDS:
        return None

    language = str(data.get("language", "")).strip().lower()
    language = "en" if language.startswith("en") else "zh"

    offer_raw = data.get("offer")
    offer: Decimal | None = None
    if offer_raw not in (None, "", "null", "None"):
        try:
            offer = to_money(str(offer_raw))
        except BargainError:
            return None
    return Classification(kind=kind, language=language, offer=offer)


def sanitize_draft(raw: str) -> str | None:
    """清洗 LLM 起草的回复。太短/为空 → None（调用方降级安全模板）。"""
    text = (raw or "").strip().strip('"“”「」『』')
    for prefix in ("回复：", "回复:", "Reply:", "reply:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    if len(text) < 2:
        return None
    return text
