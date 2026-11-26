"""Machine Pay（AI按量付费 · 402 协议）——让别的 Agent 付费雇佣我们的议价引擎。

## 为什么做这个（赛事叙事 + 商业逻辑）
PAYATHON 的主题是 "Pay for AI"。官方 Machine Pay 文档定义了 A2M 方案：
Agent 访问付费资源 → 商家返回 `402 Payment Required` + `Payment-Needed` 账单 →
Agent 完成支付 → 带 `Payment-Proof` 重试 → 商家验凭证、交付资源、发履约回执。

我们把**「可信议价决策」本身**做成按次出售的资源——
于是这个产品同时有两类客户：**人类店主（Vibe Pay 订阅）与 Agent（Machine Pay 按次）**。

## 协议要点（官方文档 docs/ai-receive/MACHINE_PAY.md 原文落地，逐条有测试）
1. 402 响应 + `Payment-Needed` 头：**base64url** 编码的账单 JSON（protocol + method 两层）
2. 账单由商家私钥签名（RSA2）：签名字段固定八个，按 key 字典序拼 `k=v&...`：
   amount / currency / goods_name / out_trade_no / pay_before / resource_id / seller_id / service_id
3. Agent 带 `Payment-Proof` 头（base64 JSON：payment_proof / trade_no / client_session）
4. 调 `alipay.aipay.agent.payment.verify` 验凭证；`active` 必须为 true
5. 还要核对：amount 与定价一致、out_trade_no 是我们的前缀、resource_id 一致、
   **trade_no 不被重复履约**（machine_fulfillments 表，主键即防线）
6. 交付资源后调 `alipay.aipay.agent.fulfillment.confirm` 发履约回执（尽力而为，失败只记日志）

## 出售的资源
`POST /api/agent/bargain`：入参 挂牌价/底价(可选,默认85%)/买家出价/已让步次数，
出参 = 授权引擎完整决策（kind/price/rule_id/citations/judgement）。
单价 MACHINE_PAY_PRICE（clerk/config.py，★作者取值★，默认 ¥0.01/次）。

**交付顺序纪律：先算资源（纯函数，不花钱），再占 trade_no、后交付**——
入参非法时买家 agent 的钱不能白花（有测试盯着这个顺序）。

## 凭证（环境变量；seller_signature 复用 ALIPAY_PRIVATE_KEY）
    MACHINE_PAY_SELLER_ID      2088 收款账号
    MACHINE_PAY_SELLER_APP_ID  商户应用 ID
    MACHINE_PAY_SERVICE_ID     服务 ID（文档 Q2 指引获取）
    MACHINE_PAY_SELLER_NAME    可选，账单里的收款方名称（默认产品名）
前三者任一缺失 → is_configured()=False → 端点诚实返回 501「A2A 通道未配置」。
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from clerk import config, pay_vibe
from clerk.bargain import to_money
from clerk.db import TZ_SHANGHAI
from clerk.pay import PayError

__all__ = [
    "INVOICE_TTL_MINUTES",
    "OUT_TRADE_PREFIX",
    "RESOURCE_ID",
    "build_invoice",
    "check_verification",
    "confirm_fulfillment",
    "decode_payment_needed",
    "encode_payment_needed",
    "is_configured",
    "new_out_trade_no",
    "parse_payment_proof",
    "verify_proof",
]

#: 出售的资源标识（账单与验凭证两头都要对上，防"资源防串"）
RESOURCE_ID = "clerk://agent/bargain-decision"

#: 我们的商户订单号前缀：验凭证时用它确认 out_trade_no 确实是我们签发的
OUT_TRADE_PREFIX = "MP"

#: 账单有效期（分钟）。文档要求"设计合理有效期，过期账单不可继续支付"
INVOICE_TTL_MINUTES = 10

GOODS_NAME = "议价授权决策-单次"

# 账单签名字段（文档固定的八个，一个不多一个不少）
_SIGN_FIELDS = (
    "amount",
    "currency",
    "goods_name",
    "out_trade_no",
    "pay_before",
    "resource_id",
    "seller_id",
    "service_id",
)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def is_demo_mode() -> bool:
    """演示模式：MACHINE_PAY_DEMO=1——评委/展览零凭证零签约走通 A402 全协议。

    诚实纪律：演示模式的签名/凭证全是占位（DEMO-SIGNATURE / DEMO-PAID），
    不过真钱、不上真履约上报；台账里记为演示履约。真钱永远走凭证齐全的生产路径。
    """
    return _env("MACHINE_PAY_DEMO") == "1"


def is_configured() -> bool:
    """A2A 三件套 + 签名私钥齐了才算配置完成；演示模式视为已配置（占位凭证）。"""
    if is_demo_mode():
        return True
    return bool(
        _env("MACHINE_PAY_SELLER_ID")
        and _env("MACHINE_PAY_SELLER_APP_ID")
        and _env("MACHINE_PAY_SERVICE_ID")
        and _env("ALIPAY_PRIVATE_KEY")
    )


def new_out_trade_no() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return OUT_TRADE_PREFIX + stamp + os.urandom(3).hex().upper()


def build_invoice(out_trade_no: str, resource_id: str = RESOURCE_ID) -> dict:
    """生成并签名一份 Payment-Needed 账单（结构严格按文档示例）。"""
    seller_id = _env("MACHINE_PAY_SELLER_ID")
    service_id = _env("MACHINE_PAY_SERVICE_ID")
    demo = is_demo_mode()
    if demo:
        seller_id = seller_id or "2088000000000000"  # 明显的假 2088：演示占位
        service_id = service_id or "DEMO-SERVICE"
    if not (seller_id and service_id):
        raise PayError("Machine Pay 凭证不全，无法签发账单")

    amount = str(to_money(config.MACHINE_PAY_PRICE))
    pay_before = (
        datetime.now(TZ_SHANGHAI).replace(microsecond=0) + timedelta(minutes=INVOICE_TTL_MINUTES)
    ).isoformat()

    sign_source = {
        "amount": amount,
        "currency": "CNY",
        "goods_name": GOODS_NAME,
        "out_trade_no": out_trade_no,
        "pay_before": pay_before,
        "resource_id": resource_id,
        "seller_id": seller_id,
        "service_id": service_id,
    }
    assert tuple(sorted(sign_source)) == _SIGN_FIELDS, "签名字段与文档不符——一个都不能差"
    if demo and not _env("ALIPAY_PRIVATE_KEY"):
        signature = "DEMO-SIGNATURE-" + out_trade_no
    else:
        signature = pay_vibe.sign_content(
            pay_vibe.build_sign_content(sign_source), pay_vibe.load_private_key()
        )

    return {
        "protocol": {
            "out_trade_no": out_trade_no,
            "amount": amount,
            "currency": "CNY",
            "resource_id": resource_id,
            "pay_before": pay_before,
            "seller_signature": signature,
            "seller_sign_type": "RSA2",
            "seller_unique_id": seller_id,
        },
        "method": {
            "seller_name": _env("MACHINE_PAY_SELLER_NAME", config.PRODUCT_NAME),
            "seller_id": seller_id,
            "seller_app_id": _env("MACHINE_PAY_SELLER_APP_ID") or ("DEMO-APP" if demo else ""),
            "goods_name": GOODS_NAME,
            "seller_unique_id_key": "seller_id",
            "service_id": service_id,
        },
    }


def encode_payment_needed(invoice: dict) -> str:
    """账单 → base64url（无 padding，与文档"Base64URL 编码"一致）。"""
    raw = json.dumps(invoice, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_payment_needed(header: str) -> dict:
    """base64url → 账单（调用方/测试用；补回 padding 再解码）。"""
    padded = header + "=" * (-len(header) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PayError(f"Payment-Needed 不是合法的 base64url JSON：{exc}") from exc


def parse_payment_proof(header: str) -> dict:
    """解析 Payment-Proof 头。结构不完整直接 PayError——缺凭证要素的请求不值得客气。"""
    padded = header.strip()
    padded += "=" * (-len(padded) % 4)
    try:
        proof = json.loads(base64.b64decode(padded).decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PayError(f"Payment-Proof 不是合法的 base64 JSON：{exc}") from exc
    protocol = proof.get("protocol") if isinstance(proof, dict) else None
    if not isinstance(protocol, dict) or not protocol.get("payment_proof") or not protocol.get("trade_no"):
        raise PayError("Payment-Proof 缺少 protocol.payment_proof / protocol.trade_no")
    return proof


def verify_proof(proof: dict) -> dict:
    """调 alipay.aipay.agent.payment.verify 验凭证，返回网关业务响应。

    演示模式（MACHINE_PAY_DEMO=1）：不调网关，按占位凭证规则本地出 verdict——
    只认 DEMO-PAID 前缀，trade_no 必须是我们签发的 MP 前缀单号（防随便伪造）。
    """
    protocol = proof["protocol"]
    method = proof.get("method") or {}
    if is_demo_mode():
        proof_token = str(protocol["payment_proof"])
        trade = str(protocol["trade_no"])
        if not proof_token.startswith("DEMO-PAID"):
            raise PayError("演示模式只接受 DEMO-PAID 前缀的占位凭证")
        if not trade.startswith(OUT_TRADE_PREFIX):
            raise PayError(f"trade_no 不是本服务签发：{trade!r}")
        return {
            "code": "10000",
            "msg": "Success（DEMO）",
            "active": True,
            "amount": str(to_money(config.MACHINE_PAY_PRICE)),
            "out_trade_no": trade,
            "trade_no": trade,
            "resource_id": RESOURCE_ID,
        }
    body = pay_vibe.execute_api(
        "alipay.aipay.agent.payment.verify",
        {
            "trade_no": protocol["trade_no"],
            "payment_proof": protocol["payment_proof"],
            "client_session": method.get("client_session", ""),
        },
    )
    if body.get("code") != "10000":
        raise PayError(f"凭证验证未通过：code={body.get('code')} sub_code={body.get('sub_code')}")
    return body


def check_verification(verdict: dict, *, expected_amount: Decimal | str) -> None:
    """对验证结果做文档要求的业务核对。任何一项不过 → PayError（402 重来）。

    - active 必须为 true
    - amount 必须等于本次资源价格（逐分）
    - out_trade_no 必须是我们签发的前缀
    - resource_id 必须和出售的资源一致（防串）
    """
    if verdict.get("active") is not True:
        raise PayError("支付凭证无效或已过期（active != true）")
    try:
        got = to_money(verdict.get("amount"))
    except PayError as exc:
        raise PayError(f"验证结果金额非法：{verdict.get('amount')!r}") from exc
    if got != to_money(expected_amount):
        raise PayError(f"金额不符：凭证 {got} vs 定价 {to_money(expected_amount)}")
    out_trade_no = str(verdict.get("out_trade_no") or "")
    if not out_trade_no.startswith(OUT_TRADE_PREFIX):
        raise PayError(f"out_trade_no 不是本服务签发：{out_trade_no!r}")
    if verdict.get("resource_id") not in (None, "", RESOURCE_ID):
        raise PayError(f"resource_id 不符：{verdict['resource_id']}")


def confirm_fulfillment(trade_no: str) -> bool:
    """履约回执（尽力而为）：失败只记日志不影响交付——文档定位它就是"异步发送"。演示模式不上报。"""
    if is_demo_mode():
        return True
    try:
        pay_vibe.execute_api("alipay.aipay.agent.fulfillment.confirm", {"trade_no": trade_no})
        return True
    except Exception as exc:  # noqa: BLE001 — 回执失败不阻断交付，日志留痕人工补
        print(f"[machine-pay] 履约回执失败 trade_no={trade_no}: {exc}")
        return False
