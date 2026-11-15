"""确定性降级层：没有 API key 时，整个产品必须仍然完整可用。

## 为什么这是硬需求，不是"锦上添花"
1. 评委的演示环境里没有我们的 API key；
2. CI 里没有；
3. 模型服务欠费/宕机时（我们亲眼见过），店主的客服不能跟着挂。

"无 key 能跑"与"有 key 能跑"的差别只在话术的人味儿——**决策路径（engine）完全相同**，
因为决策本来就不归模型管。这正是"钱由程序算"架构的红利：模型只是可更换的话术皮。

## TemplateJudge 是标记类，不是真 Judge
service 检测到这个类型就走确定性模板路径，不会调 complete()。
若有人真调了 complete()，那是接线错误——直接 RuntimeError（大声失败），
而不是返回一段假文本骗过调用方。

## 模板分类的口径（LLM 分类的降级替身）
- 语种：拉丁字母占比 > 60% → en，否则 zh
- 售后词命中 → aftersale；能提出价格数字 → bargain；议价词但无数字 → opening；其余 → chitchat
- 价格提取带量词排除（"还剩2件吗"的 2 是数量不是价格）；提取不到就是 None，**绝不猜**
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from clerk.bargain import BargainDecision, BargainError, to_money

__all__ = [
    "KINDS",
    "LANGUAGES",
    "Classification",
    "TemplateJudge",
    "detect_language",
    "extract_offer",
    "select_judge",
    "template_classify",
    "template_draft",
]

KINDS = ("bargain", "opening", "chitchat", "aftersale", "other")
LANGUAGES = ("zh", "en")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# 价格提取：数字 + 可选货币词。负向断言挡掉两类假阳性：
#   1) 数字还有后续位（防止 95 被拆成 9）
#   2) 量词/成色词（"2件""95新""8折""3天"里的数字不是出价）
_PRICE_RE = re.compile(
    r"(\d+(?:\.\d{1,2})?)(?![\d.件个只台张盒袋瓶双打成新折天号周年月日点])"
    r"(?:\s*(?:块钱|块|元|¥|￥|yuan|Yuan|YUAN|rmb|RMB|人民币))?"
)

_AFTERSALE_WORDS = (
    "退货", "退款", "换货", "坏了", "坏的", "破损", "有问题", "投诉", "骗",
    "用不了", "充不上", "开不了机", "无法使用",
    "refund", "return", "broken", "damaged", "complaint", "scam",
    "not working", "doesn't work", "won't charge", "defective",
)
# 注意：这里曾经放过单字"收"——"收到货了"会被误判成议价（opening）。
# 教训：中文单字词做关键词几乎必然过宽，至少两字、且躲开高频动词组合。
_BARGAIN_WORDS = (
    "刀", "砍", "便宜", "少点", "低点", "优惠", "出不出", "出不", "行不行", "行吗",
    "我收", "收一个", "求购", "想要",
    "offer", "lowest", "discount", "cheaper", "deal", "would you take", "can you do",
    "best price",
)


@dataclass(frozen=True)
class Classification:
    """一条买家消息的分类结果。

    offer 提取不到必须是 None——**绝不猜**。kind=bargain 且 offer 非空时，
    service 才会唤起议价授权引擎。
    """

    kind: str
    language: str
    offer: Decimal | None


class TemplateJudge:
    """标记类：告诉 service "走确定性模板路径"。见模块 docstring。"""

    model_name = "template"

    def complete(self, prompt: str, temperature: float = 0.0) -> str:
        raise RuntimeError(
            "TemplateJudge 不做文本补全——service 检测到该类型时应走模板路径"
            "（isinstance 判断）。走到这个调用说明接线错了：大声失败好过返回假文本。"
        )


def select_judge():
    """选 judge：有 key 用真模型（带缓存），没有则 TemplateJudge。

    先 import agent.judge 再查环境变量——agent.judge 在 import 时会 load_dotenv，
    顺序反了就会"密钥明明在 .env 里却读不到"（本仓库踩过的坑，见 agent/judge.py 注释）。
    """
    import os

    import agent.judge  # noqa: F401 — 触发 .env 加载

    if os.getenv("DEEPSEEK_API_KEY"):
        return agent.judge.build_judge(use_cache=True)
    return TemplateJudge()


def detect_language(message: str) -> str:
    latin = len(_LATIN_RE.findall(message))
    cjk = len(_CJK_RE.findall(message))
    if latin == 0 and cjk == 0:
        return "zh"
    return "en" if latin / (latin + cjk) > 0.6 else "zh"


def extract_offer(message: str) -> Decimal | None:
    """从消息里提取买家出价。提不到返回 None；多个数字取第一个合法价格。"""
    for match in _PRICE_RE.finditer(message or ""):
        try:
            value = to_money(match.group(1))
        except BargainError:
            continue
        if Decimal("0.01") <= value <= Decimal("1000000"):
            return value
    return None


def template_classify(message: str) -> Classification:
    text = (message or "").strip()
    language = detect_language(text)
    lowered = text.lower()

    if any(word in text or word in lowered for word in _AFTERSALE_WORDS):
        return Classification("aftersale", language, None)

    offer = extract_offer(text)
    if offer is not None:
        return Classification("bargain", language, offer)

    if any(word in text or word in lowered for word in _BARGAIN_WORDS):
        return Classification("opening", language, None)

    return Classification("chitchat", language, None)


# --------------------------------------------------------------------------- #
# 安全话术模板：(决策类型, 语言) → 文案
#
# 三个用途：①无 key 时的正常起草 ②LLM 失败时的降级 ③护栏命中后的整段替换。
# 纪律：**模板里的数字只许来自 {price}/{asking}/{offer} 三个占位符**——
# 模板自己必须能通过数字白名单护栏（tests/test_clerk_guardrails.py 有测试盯着）。
# 也不许做授权之外的承诺（包邮/退换/时效）——prompt 里禁的，模板里同样禁。
# --------------------------------------------------------------------------- #

_TEMPLATES: dict[tuple[str, str], str] = {
    ("accept", "zh"): "好嘞，就按您说的 {offer} 出！我这就改价，您直接拍就行～",
    ("accept", "en"): "Deal at {offer}! I'll update the price — go ahead and place the order.",
    ("counter", "zh"): "亲，这个价真出不了～{price} 已经是诚意价了，真心喜欢就带走吧！",
    ("counter", "en"): "Sorry, I can't go that low. The best I can do is {price} — it's a really fair price!",
    ("firm", "zh"): "价格已经降到底啦，{asking} 真不刀了，抱歉哈～",
    ("firm", "en"): "I've already dropped the price as far as I can — {asking} is firm. Sorry!",
    ("human", "zh"): "这个我需要确认一下，稍后回复您哈～",
    ("human", "en"): "Let me double-check on that and get back to you shortly!",
    ("opening", "zh"): "在的在的～诚心要的话您出个价，我看看能不能出？",
    ("opening", "en"): "Yes it's available! Feel free to make me a reasonable offer.",
    ("aftersale", "zh"): "真不好意思给您添麻烦了！您别急，把订单号和问题照片发我，我马上处理。",
    ("aftersale", "en"): "So sorry about that! Please send me your order number and a photo of the issue — I'll make it right.",
    ("chitchat", "zh"): "在的，亲～有什么想了解的随时问。",
    ("chitchat", "en"): "Hi there! Happy to answer any questions.",
    ("other", "zh"): "在的，亲～有什么想了解的随时问。",
    ("other", "en"): "Hi there! Happy to answer any questions.",
}


def template_draft(
    *, decision: BargainDecision | None, classification: Classification, item: dict
) -> str:
    """按 (决策类型, 买家语言) 选安全模板。任何决策都有话可说——这是产品的兜底承诺。"""
    lang = classification.language if classification.language in LANGUAGES else "zh"
    key = (decision.kind if decision is not None else classification.kind, lang)
    template = _TEMPLATES.get(key) or _TEMPLATES[("chitchat", lang)]
    asking = str(item["asking_price"])
    price = (
        str(decision.price)
        if decision is not None and decision.price is not None
        else asking
    )
    offer = str(classification.offer) if classification.offer is not None else asking
    return template.format(asking=asking, price=price, offer=offer)
