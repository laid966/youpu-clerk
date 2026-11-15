"""演示模式：演示店铺 + 5 个双语买家人设 + 逐句剧本。

## 为什么演示模式是一等公民，不是"顺便做的 demo"
1. **评委只有 60 秒**：不装扩展、不注册闲鱼、不扫码——打开网页就能玩通全流程。
   产品完整度那 30% 里，演示体验就是评委的全部印象。
2. **演示必须无 key 可跑**：全程强制 TemplateJudge（确定性），评委现场没有我们的
   API key，而且每一步都必须可复现——同一剧本重放，决策逐字节一致。
3. **"揭示标准答案"是 auditkit 演示的老传统**：每一步剧本都带 expected
   （引擎应该判什么），演示时并排展示"实际判定 vs 预期判定"——
   观众看到的不是"AI 说了句话"，而是"程序按制度算出了一个可核对的结果"。

## 剧本与实现的一致性由测试锁死
tests/test_clerk_demo.py 会把每条剧本消息喂给 template_classify 和 decide_bargain，
逐步重放整个砍价旅程。**剧本改一句、梯度改一档，测试立刻炸**——
演示现场翻车是最贵的翻车，所以在 CI 里先翻。

## 已知边界（诚实声明，剧本 note 里也写了）
- Emma 的英文剧本里数字按人民币口径处理：MVP 不做汇率换算，
  跨境币种是 roadmap（eBay 适配器接入时一起做）。
- 张姐的售后剧本走模板话术：真实 LLM 在线时会更有人味儿，但决策路径完全一致
  ——因为售后消息本来就不进引擎（没有数字可判）。
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from clerk import db
from clerk.bargain import default_floor_price

__all__ = [
    "DEMO_TOKEN",
    "DemoError",
    "bootstrap",
    "get_persona",
    "next_step",
    "persona_ids",
    "seed_demo",
    "step_index_for_conversation",
]

DEMO_TOKEN = "demo-token"

SHOP_NAME_ZH = "深夜杂货铺"
SHOP_NAME_EN = "Midnight Thrift Shop"

# 商品全虚构；挂牌价贴近真实二手行情。底价不手写——由 default_floor_price 现算，
# 防止"配置里的 0.85 改了、演示数据还停在旧底价"的漂移。
_ITEMS = (
    {
        "key": "keyboard",
        "title": "机械键盘 87 键 茶轴",
        "title_en": "Mechanical Keyboard 87-Key",
        "asking_price": "399.00",
    },
    {
        "key": "gamecard",
        "title": "Switch 游戏卡带",
        "title_en": "Switch Game Card",
        "asking_price": "180.00",
    },
    {
        "key": "band",
        "title": "小米手环 8",
        "title_en": "Xiaomi Smart Band 8",
        "asking_price": "129.00",
    },
)


class DemoError(ValueError):
    """演示层的非法请求（不认识的 persona、越界的步数）。"""


def _items_with_floor() -> list[dict]:
    return [
        {
            **item,
            "floor_price": str(default_floor_price(item["asking_price"])),
        }
        for item in _ITEMS
    ]


# --------------------------------------------------------------------------- #
# 五个人设。每人一份剧本：message 是买家原话，expected 是引擎应给的判定，
# note 是演示旁白（前端步进时展示"这一步为什么这么判"）。
#
# expected.used = 走到这一步时"已被卖家采纳的 counter 次数"（I1 口径）。
# 演示里卖家永远采纳（server 自动 adopt sent），所以 used 按剧本单调递推。
# --------------------------------------------------------------------------- #

_PERSONAS: tuple[dict, ...] = (
    {
        "id": "wang",
        "name_zh": "砍价党老王",
        "name_en": "Haggler Wang",
        "style_zh": "开口对半砍，被拒了就一点点往上磨",
        "style_en": "Opens at half price, then grinds upward",
        "language": "zh",
        "avatar_color": "#DC2626",
        "item_key": "keyboard",
        "steps": (
            {
                "message": "老板，对半砍，200出不出？",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "200.00"},
                "expected": {"kind": "human", "rule_id": "BARGAIN-HUMAN-LOWBALL", "used": 0},
                "note_zh": "开口对半砍：200 只有底价 339.15 的 59%，低于 80% 授权线 → 不还价，直接转人工",
                "note_en": "Opens at half price: 200 is only 59% of the 339.15 floor — below the 80% authorization line, so it escalates to human instead of auto-countering",
            },
            {
                "message": "哎呀贵了嘛，300行不？",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "300.00"},
                "expected": {"kind": "counter", "price": "379.05", "rule_id": "BARGAIN-COUNTER-T1", "used": 0},
                "note_zh": "300 过了授权线，进让步梯度第 1 档：还价 = 399 × 95% = 379.05——引擎算的，不是模型口算的",
                "note_en": "300 passes the authorization line, entering concession tier 1: counter = 399 × 95% = 379.05 — computed by the engine, not improvised by a model",
            },
            {
                "message": "320，我现在就拍！",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "320.00"},
                "expected": {"kind": "counter", "price": "367.08", "rule_id": "BARGAIN-COUNTER-T2", "used": 1},
                "note_zh": "上一次还价被卖家采纳 → 已让步 1 次；梯度第 2 档：399 × 92% = 367.08",
                "note_en": "Previous counter was adopted → 1 concession used; tier 2: 399 × 92% = 367.08",
            },
            {
                "message": "你太狠了，335行不行？",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "335.00"},
                "expected": {"kind": "counter", "price": "359.10", "rule_id": "BARGAIN-COUNTER-T3", "used": 2},
                "note_zh": "梯度第 3 档：399 × 90% = 359.10——授权梯度的最后一档",
                "note_en": "Tier 3: 399 × 90% = 359.10 — the last rung of the authorized ladder",
            },
            {
                "message": "338，到底出不出嘛？",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "338.00"},
                "expected": {"kind": "firm", "rule_id": "BARGAIN-FIRM-EXHAUSTED", "used": 3},
                "note_zh": "338 距底价 339.15 只差 1.15 元，但让步已达上限 3 次 → 守价不再降。制度比话术可靠：AI 不会被磨到破底",
                "note_en": "338 is just 1.15 below the floor, but the 3-concession cap is reached → price holds. The system beats persuasion: the AI can't be ground down past its authorization",
            },
            {
                "message": "行行行，就340吧！",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "340.00"},
                "expected": {"kind": "accept", "rule_id": "BARGAIN-ACCEPT", "used": 3},
                "note_zh": "340 ≥ 底价 339.15 → 授权内直接成交。让步用尽也不挡成交：ACCEPT 优先级永远高于 FIRM",
                "note_en": "340 ≥ floor 339.15 → deal closes within authorization. ACCEPT always outranks FIRM — a good offer is never blocked by the concession cap",
            },
        ),
    },
    {
        "id": "li",
        "name_zh": "沉默寡言 Li",
        "name_en": "Man-of-Few-Words Li",
        "style_zh": "消息极短，惜字如金",
        "style_en": "Terse, minimal messages",
        "language": "zh",
        "avatar_color": "#78716C",
        "item_key": "gamecard",
        "steps": (
            {
                "message": "还在吗",
                "language": "zh",
                "expected_classify": {"kind": "chitchat", "offer": None},
                "expected": {"kind": "none"},
                "note_zh": "打招呼不进引擎——没有数字可判。引擎只在「有钱要算」时介入，这是「钱由程序算」的另一半",
                "note_en": "Greetings never reach the engine — there is no number to adjudicate. The engine only steps in when money is on the table",
            },
            {
                "message": "140行不",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "140.00"},
                "expected": {"kind": "counter", "price": "171.00", "rule_id": "BARGAIN-COUNTER-T1", "used": 0},
                "note_zh": "卡带底价 = 180 × 85% = 153.00；140 < 153 但过了 80% 线 → 梯度第 1 档：180 × 95% = 171.00",
                "note_en": "Card floor = 180 × 85% = 153.00; 140 < floor but above the 80% line → tier 1: 180 × 95% = 171.00",
            },
            {
                "message": "150",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "150.00"},
                "expected": {"kind": "counter", "price": "165.60", "rule_id": "BARGAIN-COUNTER-T2", "used": 1},
                "note_zh": "两个字也是一条完整事实：150 < 153 → 梯度第 2 档：180 × 92% = 165.60",
                "note_en": "Two characters still make a complete fact: 150 < 153 → tier 2: 180 × 92% = 165.60",
            },
            {
                "message": "好吧那就155",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "155.00"},
                "expected": {"kind": "accept", "rule_id": "BARGAIN-ACCEPT", "used": 2},
                "note_zh": "155 ≥ 底价 153.00 → 成交。全程卖家只打了四个字，剩下的都是店员的事",
                "note_en": "155 ≥ floor 153.00 → deal. The seller typed four characters in total; the clerk did the rest",
            },
        ),
    },
    {
        "id": "zhang",
        "name_zh": "售后抱怨张姐",
        "name_en": "Upset Customer Zhang",
        "style_zh": "收货后来投诉，情绪逐步升级",
        "style_en": "Post-purchase complaints, escalating",
        "language": "zh",
        "avatar_color": "#D97706",
        "item_key": "band",
        "steps": (
            {
                "message": "收到的手环是坏的，充不上电",
                "language": "zh",
                "expected_classify": {"kind": "aftersale", "offer": None},
                "expected": {"kind": "none"},
                "note_zh": "售后消息不议价、不进引擎；模板话术先稳住并索要订单号与照片。LLM 在线时这一步会更有人味儿，但决策路径完全一致",
                "note_en": "After-sales messages never reach the engine; the template calms the buyer and asks for order number + photos. A live LLM would sound warmer, but the decision path is identical",
            },
            {
                "message": "我要退货，退款怎么弄？",
                "language": "zh",
                "expected_classify": {"kind": "aftersale", "offer": None},
                "expected": {"kind": "none"},
                "note_zh": "退货诉求：AI 只收集信息、不承诺退款——承诺超出授权的事会被护栏拦下",
                "note_en": "Return request: the AI collects facts but never promises refunds — unauthorized promises get blocked by the guardrail",
            },
            {
                "message": "我要投诉你们，赶紧给我退款",
                "language": "zh",
                "expected_classify": {"kind": "aftersale", "offer": None},
                "expected": {"kind": "none"},
                "note_zh": "情绪升级——真实工作台里店主可以一键「转人工」接管；AI 的职责是不火上浇油",
                "note_en": "Emotion escalates — in the real workbench the seller can take over with one click; the AI's job is to never pour oil on the fire",
            },
        ),
    },
    {
        "id": "emma",
        "name_zh": "海外买家 Emma",
        "name_en": "Emma (overseas buyer)",
        "style_zh": "英文询价，礼貌直接",
        "style_en": "English-speaking, polite and direct",
        "language": "en",
        "avatar_color": "#1677FF",
        "item_key": "keyboard",
        "steps": (
            {
                "message": "Hi, is this still available?",
                "language": "en",
                "expected_classify": {"kind": "chitchat", "offer": None},
                "expected": {"kind": "none"},
                "note_zh": "分类器识别 language=en——接下来所有回复自动用英文起草，店主不用会英语",
                "note_en": "The classifier detects language=en — every reply from here is drafted in English, so the seller doesn't have to speak it",
            },
            {
                "message": "Would you take 300 for it?",
                "language": "en",
                "expected_classify": {"kind": "bargain", "offer": "300.00"},
                "expected": {"kind": "counter", "price": "379.05", "rule_id": "BARGAIN-COUNTER-T1", "used": 0},
                "note_zh": "英文买家、中文店主、同一套授权引擎：钱由程序算，语言只是话术的皮。这就是跨境场景的全部秘密",
                "note_en": "English buyer, Chinese seller, one authorization engine: money is computed by the program — language is just the wrapper. That's the whole trick for cross-border selling",
            },
            {
                "message": "OK, would you take 340?",
                "language": "en",
                "expected_classify": {"kind": "bargain", "offer": "340.00"},
                "expected": {"kind": "accept", "rule_id": "BARGAIN-ACCEPT", "used": 1},
                "note_zh": "340 ≥ 底价 339.15 → 英文成交话术。（MVP 边界：数字按人民币口径，汇率换算是 roadmap）",
                "note_en": "340 ≥ floor 339.15 → deal, in English. (MVP boundary: amounts are CNY-denominated; FX conversion is on the roadmap)",
            },
        ),
    },
    {
        "id": "chen",
        "name_zh": "爽快人小陈",
        "name_en": "Quick-Trigger Chen",
        "style_zh": "开口就是能成交的价",
        "style_en": "Opens with a deal-closing price",
        "language": "zh",
        "avatar_color": "#16A34A",
        "item_key": "band",
        "steps": (
            {
                "message": "老板，120包邮的话我现在就拍",
                "language": "zh",
                "expected_classify": {"kind": "bargain", "offer": "120.00"},
                "expected": {"kind": "accept", "rule_id": "BARGAIN-ACCEPT", "used": 0},
                "note_zh": "120 ≥ 底价 109.65 → 直接成交，从收到消息到给出建议不到一秒。快，本身就是转化率",
                "note_en": "120 ≥ floor 109.65 → instant deal; suggestion ready in under a second. Speed itself is conversion",
            },
        ),
    },
)

_PERSONA_INDEX = {persona["id"]: persona for persona in _PERSONAS}


def bootstrap() -> dict:
    """契约 /api/demo/bootstrap 的响应体：演示店铺 + 全部人设与剧本。

    剧本直接给前端（含 expected）——"揭示标准答案"是刻意的：
    演示的说服力来自"实际判定与预期判定并排、逐字节一致"。
    """
    return {
        "shop": {"name": SHOP_NAME_ZH, "name_en": SHOP_NAME_EN, "items": _items_with_floor()},
        "personas": [dict(persona) for persona in _PERSONAS],
    }


def persona_ids() -> tuple[str, ...]:
    return tuple(_PERSONA_INDEX)


def get_persona(persona_id: str) -> dict:
    persona = _PERSONA_INDEX.get(persona_id)
    if persona is None:
        raise DemoError(f"没有这个人设：{persona_id}（可选：{'/'.join(_PERSONA_INDEX)}）")
    return persona


def next_step(persona_id: str, step_index: int) -> dict:
    """取出剧本的下一步。越界即报错——演示不允许"即兴发挥"。"""
    persona = get_persona(persona_id)
    steps = persona["steps"]
    if not isinstance(step_index, int) or isinstance(step_index, bool):
        raise DemoError(f"step_index 必须是整数：{step_index!r}")
    if step_index < 0 or step_index >= len(steps):
        raise DemoError(
            f"人设 {persona_id} 的剧本只有 {len(steps)} 步，收到 step_index={step_index}"
        )
    step = steps[step_index]
    return {
        "persona_id": persona_id,
        "item_key": persona["item_key"],
        "step_index": step_index,
        "total_steps": len(steps),
        "message": step["message"],
        "language": step["language"],
        "note_zh": step["note_zh"],
        "note_en": step["note_en"],
        "expected_classify": step["expected_classify"],
        "expected": step["expected"],
        "finished": step_index == len(steps) - 1,
    }


def seed_demo(conn: sqlite3.Connection, token: str = DEMO_TOKEN) -> dict[str, dict]:
    """把演示商品种进数据库（幂等：已存在则复用）。返回 {item_key: item_row}。"""
    existing = {row["title"]: row for row in db.list_items(conn, token)}
    seeded: dict[str, dict] = {}
    for spec in _items_with_floor():
        title = spec["title"]
        if title in existing:
            seeded[spec["key"]] = existing[title]
            continue
        seeded[spec["key"]] = db.create_item(
            conn, token, title, spec["asking_price"], spec["floor_price"], platform="demo"
        )
    return seeded


def step_index_for_conversation(conn: sqlite3.Connection, conversation_id: str) -> int:
    """服务端推导剧本进度：会话里已有几条买家消息 = 下一步的 index。

    进度不存客户端——刷新页面、换设备，剧本都从真实台账接着走（状态在服务端）。
    """
    messages = db.get_conversation_messages(conn, conversation_id)
    return sum(1 for message in messages if message["direction"] == "buyer")


def demo_floor_prices() -> dict[str, Decimal]:
    """{item_key: floor}——测试与前端旁白共用，防止手抄漂移。"""
    return {
        spec["key"]: default_floor_price(spec["asking_price"])
        for spec in _ITEMS
    }
