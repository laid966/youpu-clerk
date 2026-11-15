"""★ 这是你的文件 ★ 客服护栏：禁语词表 + 数字白名单。

## 两道闸（机制复用 agent.guardrails.GuardrailRule；词表归你）
1. **词表层**：平台红线（引导站外交易）、辱骂、绝对化承诺——把明显的便宜地挡掉。
2. **数字层（本产品的灵魂）**：回复里的每个价格数字都必须来自授权集合。
   - 允许：decision.price（引擎算的还价）、asking_price（挂牌价）、买家自己的出价（复述无妨）
   - **禁止：floor_price——底价泄露 = 帮买家对付店主，最高级事故**
   - 其他任何价格数字 = 模型幻觉 = 整段替换安全模板
   这是"AI 店员的每句话有据可查"在护栏层的体现：不靠提示词自觉，靠程序拦截。

## 你要做的
- 增删词表（字面量或正则；空 patterns 会在构造时直接报错——auditkit 踩过的坑，机制帮你兜着）
- 改完验证：`pytest tests/test_clerk_guardrails.py -q`，以及工作台里拿真话术试

## 与 agent/guardrails.py 的关系
只复用它的 GuardrailRule / GuardrailHit **机制**；医疗词表与 clerk 无关，
clerk 的规则组独立在下面定义。内核零行业代码的老规矩，产品层同样遵守。
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Iterable

from agent.guardrails import GuardrailHit, GuardrailRule

from clerk.bargain import BargainError, to_money

__all__ = ["CLERK_GUARDRAIL_RULES", "check_numbers", "scan_all", "scan_reply"]

CLERK_GUARDRAIL_RULES: tuple[GuardrailRule, ...] = (
    GuardrailRule(
        name="C-DIVERSION",
        category="diversion",
        patterns=(
            "加微信", "加个微信", "加V", "加v", "vx", "VX", "微信联系", "微信交易",
            "QQ联系", "加QQ", "加qq", "站外", "线下交易", "私下交易",
            "wechat", "WeChat", "WhatsApp", "off platform", "off-platform", "pay outside",
        ),
        note="引导站外交易：平台红线，轻则删msg重则封号",
    ),
    GuardrailRule(
        name="C-ABUSE",
        category="abuse",
        patterns=("傻逼", "sb", "SB", "滚蛋", "神经病", "idiot", "stupid", "shut up"),
        note="辱骂买家：无论买家多难缠，回骂就是公关事故",
    ),
    GuardrailRule(
        name="C-OVERPROMISE",
        category="overpromise",
        patterns=(
            "假一赔十", "绝对正品", "百分百正品", "100%正品",
            "永远不会坏", "终身免费换新", "无任何瑕疵",
        ),
        note="绝对化承诺：广告法风险，且兑现不了就是纠纷",
    ),
)


def scan_reply(text: str) -> list[GuardrailHit]:
    """词表层：跑全部 clerk 客服禁语规则。返回命中列表（可能为空）。"""
    hits: list[GuardrailHit] = []
    for rule in CLERK_GUARDRAIL_RULES:
        for pattern in rule.matches(text):
            hits.append(
                GuardrailHit(rule=rule.name, category=rule.category, pattern=pattern, note=rule.note)
            )
    return hits


# 价格状数字的三种形态：¥379.05 / 379.05元 / 裸的两位小数 379.05。
# 刻意**不**抓无货币语境的整数（"3天内发货"的 3 不是价格），否则误报会淹死真事故。
_CURRENCY_NUM_RE = re.compile(
    r"(?:[¥￥]\s*(\d+(?:\.\d{1,2})?))"
    r"|(?:(\d+(?:\.\d{1,2})?)\s*(?:元|块钱|块|yuan|Yuan|YUAN|rmb|RMB|人民币|CNY))"
    r"|(?<![\d.])(\d+\.\d{2})(?![\d.])"
)


def check_numbers(
    text: str, *, allowed: Iterable[Decimal | str], floor_price: Decimal | str
) -> list[GuardrailHit]:
    """数字层（不变量 I3）：回复里的价格数字只许来自 allowed 集合。

    floor_price 单独比对：它泄露时的命中规则名是 C-FLOOR-LEAK（最高级事故），
    其余未知价格是 C-UNKNOWN-PRICE（模型幻觉）。两者都导致整段替换安全模板。

    注意 allowed 判定在 floor 判定**之前**：店主把底价设成等于挂牌价时，
    复述挂牌价是合法的，不该被误判成泄底。
    """
    allowed_set = {to_money(value) for value in allowed}
    floor = to_money(floor_price)
    hits: list[GuardrailHit] = []
    for match in _CURRENCY_NUM_RE.finditer(text or ""):
        raw = next(group for group in match.groups() if group)
        try:
            value = to_money(raw)
        except BargainError:  # pragma: no cover — 正则已保证形状，防御性跳过
            continue
        if value in allowed_set:
            continue
        if value == floor:
            hits.append(
                GuardrailHit(
                    rule="C-FLOOR-LEAK",
                    category="numeric",
                    pattern=raw,
                    note="回复泄露底价——最高级事故，整段替换安全模板",
                )
            )
        else:
            hits.append(
                GuardrailHit(
                    rule="C-UNKNOWN-PRICE",
                    category="numeric",
                    pattern=raw,
                    note="回复出现非授权引擎产出的价格数字（模型幻觉），整段替换安全模板",
                )
            )
    return hits


def scan_all(
    text: str, *, allowed: Iterable[Decimal | str], floor_price: Decimal | str
) -> list[GuardrailHit]:
    """两道闸一起跑。service 只用这个入口。"""
    return scan_reply(text) + check_numbers(text, allowed=allowed, floor_price=floor_price)
