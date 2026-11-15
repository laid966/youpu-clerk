"""议价授权决策：「钱由程序算、模型只说话」的落地点。

## 它在整个产品里的位置

    买家消息 ──LLM分类/提取出价──► BargainFacts ──本模块──► BargainDecision ──LLM起草──► 建议回复
                                    （纯数字）   │(engine判定)   （决策+价格+依据）
                                                 ▼
                                          台账（judgement 全量序列化）

本模块从头到尾**没有模型调用**。它只做三件事：

1. **校验**：金额为正、底价 ≤ 挂牌、让步次数非负整数——非法输入直接报错（大声失败），
   绝不拿错误的数字硬算出一个"看起来对"的决策。
2. **构造事实**：`offer_floor_ratio` 这类派生事实由这里用 Decimal 算好——
   它是"程序算的"，不是模型给的，也不是调用方随手填的。
3. **翻译判定**：engine 的 Judgement → 产品语义的四种决策（accept/counter/firm/human），
   保留 rule_id 与 citations——这是"每次让步都有据可查"的数据来源。

## 为什么 counter 的价格走 engine 的 fee 机制

`fee.rate_of_amount` 用 Decimal 算 `挂牌价 × 梯度` 并四舍五入到分（ROUND_HALF_UP）。
金额计算集中在 engine/adjudicate.py 一处、被同一批测试覆盖——
这是本仓库的老规矩：**金额逻辑一旦漏出引擎，就是事故的开始。**

## 决策语义约定（UI 与台账都按这个来）

    accept   买家出价 ≥ 底价，可以成交
    counter  还价；price 必非空，且要么 ≥ 底价，要么已升级 human（破底价会被 escalate 拦下）
    firm     让步梯度用尽，守价不再降
    human    超出授权（低价甩卖 / 还价破底价 / 引擎升级），必须有人接手
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from engine.adjudicate import Judgement, adjudicate
from engine.domain import Domain, load_domain

from clerk.config import DEFAULT_FLOOR_RATIO

__all__ = [
    "BARGAIN_DOMAIN_PATH",
    "KIND_ACCEPT",
    "KIND_COUNTER",
    "KIND_FIRM",
    "KIND_HUMAN",
    "BargainDecision",
    "BargainError",
    "BargainFacts",
    "decide_bargain",
    "default_floor_price",
    "load_bargain_domain",
    "to_money",
]

ROOT = Path(__file__).resolve().parents[1]
BARGAIN_DOMAIN_PATH = ROOT / "domain" / "clerk-bargain" / "domain.yaml"

MONEY_QUANTUM = Decimal("0.01")
RATIO_QUANTUM = Decimal("0.0001")

KIND_ACCEPT = "accept"
KIND_COUNTER = "counter"
KIND_FIRM = "firm"
KIND_HUMAN = "human"

#: engine 的升级判定 needs_review 在产品层并入 human（都是"必须有人接手"）
_ENGINE_NEEDS_REVIEW = "needs_review"


class BargainError(ValueError):
    """议价事实不合法（金额非正、底价高于挂牌、让步数为负……）。

    继承 engine 的纪律：这类问题必须立刻炸，绝不静默吞——
    拿错误事实算出一个"看起来正常"的建议，比报错贵得多。
    """


def to_money(value: Any) -> Decimal:
    """把金额统一成"分"精度的 Decimal。

    经过 str 构造，绝不经过 float 的二进制运算：`to_money(39.9)` 得到 39.90。
    float 输入用 repr 取最短往返表示，避免 39.900000000000006 这类脏东西进账本。
    """
    if isinstance(value, bool):
        raise BargainError(f"金额不能是布尔值：{value!r}")
    text = repr(value) if isinstance(value, float) else str(value)
    try:
        return Decimal(text.strip()).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise BargainError(f"不是合法金额：{value!r}") from exc


@dataclass(frozen=True)
class BargainFacts:
    """一次议价决策的完整输入。构造时即校验并归一化——**能构造出来的实例就是合法的**。

    concessions_used 口径：本会话对该商品已做出的 kind == "counter" 决策次数（从台账数）。
    accept 结束议价不计入；firm / human 也不计入。
    """

    asking_price: Decimal
    buyer_offer: Decimal
    floor_price: Decimal
    concessions_used: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "asking_price", to_money(self.asking_price))
        object.__setattr__(self, "buyer_offer", to_money(self.buyer_offer))
        object.__setattr__(self, "floor_price", to_money(self.floor_price))

        if isinstance(self.concessions_used, bool) or not isinstance(self.concessions_used, int):
            raise BargainError(
                f"concessions_used 必须是整数，实际是 {type(self.concessions_used).__name__}"
            )
        if self.concessions_used < 0:
            raise BargainError(f"concessions_used 不能为负：{self.concessions_used}")

        for name in ("asking_price", "buyer_offer", "floor_price"):
            amount = getattr(self, name)
            if amount <= 0:
                raise BargainError(f"{name} 必须为正数，实际是 {amount}")

        if self.floor_price > self.asking_price:
            raise BargainError(
                f"底价（{self.floor_price}）不能高于挂牌价（{self.asking_price}）——"
                "这是档案配置错误，请先修档案再议价"
            )

    def offer_floor_ratio(self) -> Decimal:
        """买家出价 / 底价，保留 4 位小数（ROUND_HALF_UP）。

        除法在 Decimal 上下文里可能产生超长小数，quantize 立即收敛，
        保证同一输入永远得到同一比值（确定性）。
        """
        return (self.buyer_offer / self.floor_price).quantize(
            RATIO_QUANTUM, rounding=ROUND_HALF_UP
        )

    def to_engine_facts(self) -> dict[str, Any]:
        """交给 engine 的事实。字段名与域 YAML 的 facts 一一对应——多一个引擎都会报错。"""
        return {
            "asking_price": self.asking_price,
            "buyer_offer": self.buyer_offer,
            "floor_price": self.floor_price,
            "offer_floor_ratio": self.offer_floor_ratio(),
            "concessions_used": self.concessions_used,
        }


@dataclass(frozen=True)
class BargainDecision:
    """产品语义的决策结果。

    rule_id + citations 是"留痕"的本体；judgement 保留引擎的完整判定过程，
    台账直接序列化它——**事后任何一个决策都能回答"当时为什么这么判"**。
    """

    kind: str
    price: Decimal | None
    rule_id: str | None
    citations: tuple[str, ...]
    reasons: tuple[str, ...]
    requires_human_review: bool
    judgement: Judgement

    def to_dict(self) -> dict[str, Any]:
        """台账 / API 的序列化形状。金额用字符串，避免 JSON 浮点精度损失（与 engine 同款规矩）。"""
        return {
            "kind": self.kind,
            "price": None if self.price is None else str(self.price),
            "rule_id": self.rule_id,
            "citations": list(self.citations),
            "reasons": list(self.reasons),
            "requires_human_review": self.requires_human_review,
            "judgement": self.judgement.to_dict(),
        }


_domain_cache: dict[Path, Domain] = {}


def load_bargain_domain(path: str | Path = BARGAIN_DOMAIN_PATH) -> Domain:
    """加载议价授权域（按解析后的路径缓存；加载即校验由 engine.domain 保证）。"""
    resolved = Path(path).resolve()
    if resolved not in _domain_cache:
        _domain_cache[resolved] = load_domain(resolved)
    return _domain_cache[resolved]


def decide_bargain(facts: BargainFacts, domain: Domain | None = None) -> BargainDecision:
    """做一次议价决策。同一输入永远得到同一输出，全程无模型调用。"""
    if domain is None:
        domain = load_bargain_domain()

    judgement = adjudicate(domain, facts.to_engine_facts())
    final = judgement.final_verdict

    price: Decimal | None = None
    if final == KIND_COUNTER:
        if judgement.fee_amount is None:  # 防御：counter 规则必带 fee，缺了是域配置缺陷
            raise BargainError(
                f"规则 {judgement.winning_rule_id} 判了 counter 却没算出还价金额——检查域 YAML 的 fee 配置"
            )
        kind = KIND_COUNTER
        price = judgement.fee_amount
    elif final in (KIND_ACCEPT, KIND_FIRM):
        kind = final
    else:
        # human（低价甩卖，critical）与 needs_review（升级/缺口/冲突）合并：都要"有人接手"
        kind = KIND_HUMAN

    return BargainDecision(
        kind=kind,
        price=price,
        rule_id=judgement.winning_rule_id,
        citations=judgement.citations,
        reasons=judgement.escalate_reasons,
        requires_human_review=judgement.requires_human_review,
        judgement=judgement,
    )


def default_floor_price(asking_price: Any, ratio: Decimal = DEFAULT_FLOOR_RATIO) -> Decimal:
    """智能默认：底价 = 挂牌价 × DEFAULT_FLOOR_RATIO（0.85），四舍五入到分。

    ratio 的取值在 clerk/config.py（★作者文件★）；这里只是机制。
    """
    return to_money(to_money(asking_price) * Decimal(str(ratio)))
