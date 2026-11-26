"""Vibe Pay（AI网页应用收款）真实通道适配器 —— 按官方文档逐条落地。

文档来源（2026-11-16 抓取，页面标注更新于 2026-11-15）：
- 接入指南 /docs/vibe-pay/ai-web-app-payment-qianyi/ai-web-app-payment-integration-guide.md
  首句即"适用于在商家网页应用中使用支付宝支付功能，**支持个人收款场景**"（G2 的官方答案）
- 异步通知 /api-list/async-notify-verify.md
- 下单接口 /api-list/alipay-trade-page-pay.md

## 遵守的文档纪律（每条都有实现与测试对应）
1. product_code 仅 `FAST_INSTANT_TRADE_PAY`（文档唯一枚举值）
2. subject 不可含 `/ = &` 等特殊字符 → 构造时清洗
3. total_amount 两位小数、[0.01, 100000000] → 本项目金额纪律天然满足
4. **支付结果以异步通知或查询接口为准，不信同步跳转** →
   权益变更只发生在 notify / query 两个入口，return_url 只做前端展示
5. 通知必须验签（RSA2）+ 二次校验（app_id / seller_id；金额与订单核对在状态机里）
6. 只有 `TRADE_SUCCESS` / `TRADE_FINISHED` 算付款成功
7. 通知应答纯文本 `success`/`failure`；非 success 支付宝按 4m/10m/10m/1h/2h/6h/15h 重发
   → clerk.pay 状态机的幂等保证重发安全

## 凭证全部来自环境变量（绝不入库；.env 已在 .gitignore）
    ALIPAY_APP_ID        开放平台应用 ID
    ALIPAY_PRIVATE_KEY   应用私钥（PKCS8；base64 DER 或 PEM 均可）
    ALIPAY_PUBLIC_KEY    支付宝公钥（X509；base64 DER 或 PEM）——验通知签名用
    ALIPAY_GATEWAY       默认生产 https://openapi.alipay.com/gateway.do；沙箱换沙箱网关
    ALIPAY_NOTIFY_URL    https://你的域名/api/pay/notify（公网可达、无重定向、无多余字符）
    ALIPAY_RETURN_URL    支付完成后的前端回跳地址
    ALIPAY_SELLER_ID     可选：自己的 2088 账号，配置后对通知 seller_id 强校验

任一项缺失 → is_configured()=False → server 自动回落 FakeAdapter。
**凭证不齐时产品诚实显示"通道接入中"，绝不假装能收款。**

## 响应验签的说明（诚实声明）
对网关响应做字符串切片验签（官方 SDK 同款做法）；同时我们只对官方网关走
HTTPS 直连（httpx 默认校验证书），两层保障。切片找不到 sign 时跳过验签
（网关级错误响应没有 sign），业务错误照常按 code 处理。
"""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from clerk.db import TZ_SHANGHAI
from clerk.pay import PRODUCTS, PayError

__all__ = [
    "DEFAULT_GATEWAY",
    "PRODUCT_CODE",
    "VibePayAdapter",
    "build_page_pay",
    "build_sign_content",
    "execute_api",
    "is_configured",
    "load_private_key",
    "load_public_key",
    "query_trade",
    "refund_trade",
    "reset_key_cache",
    "sign_content",
    "verify_content",
    "verify_notify",
]

DEFAULT_GATEWAY = "https://openapi.alipay.com/gateway.do"
SIGN_TYPE = "RSA2"
PRODUCT_CODE = "FAST_INSTANT_TRADE_PAY"
ORDER_EXPIRE_MINUTES = 30  # 文档允许 1m~15d；30 分钟足够完成支付，又不至于挂着僵尸单

_key_cache: dict[tuple[str, str], Any] = {}


# --------------------------------------------------------------------------- #
# 配置与密钥
# --------------------------------------------------------------------------- #


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def is_configured() -> bool:
    """四件套齐了才算配置完成：app_id、私钥、支付宝公钥、公网 notify_url。"""
    return bool(
        _env("ALIPAY_APP_ID")
        and _env("ALIPAY_PRIVATE_KEY")
        and _env("ALIPAY_PUBLIC_KEY")
        and _env("ALIPAY_NOTIFY_URL")
    )


def reset_key_cache() -> None:
    """测试专用：换密钥后清缓存（生产进程密钥不变，缓存安全）。"""
    _key_cache.clear()


def _load_key(kind: str, material: str, loader_pem, loader_der):
    cached = _key_cache.get((kind, material))
    if cached is not None:
        return cached
    text = material.strip()
    if not text:
        raise PayError(f"缺少{kind}密钥材料")
    try:
        if text.startswith("-----"):
            key = loader_pem(text.encode("utf-8"))
        else:
            # 控制台复制出来的 base64 常带换行/空格，全部剥掉再解码
            key = loader_der(base64.b64decode("".join(text.split())))
    except (ValueError, TypeError) as exc:
        raise PayError(f"{kind}密钥解析失败（支持 base64 DER 或 PEM）：{exc}") from exc
    _key_cache[(kind, material)] = key
    return key


def load_private_key(material: str | None = None):
    material = material if material is not None else _env("ALIPAY_PRIVATE_KEY")
    return _load_key(
        "应用私钥",
        material,
        lambda pem: serialization.load_pem_private_key(pem, password=None),
        # load_der_private_key 的 password 是必选位置参数——不能裸传函数引用
        lambda der: serialization.load_der_private_key(der, password=None),
    )


def load_public_key(material: str | None = None):
    material = material if material is not None else _env("ALIPAY_PUBLIC_KEY")
    return _load_key(
        "支付宝公钥",
        material,
        lambda pem: serialization.load_pem_public_key(pem),
        serialization.load_der_public_key,
    )


# --------------------------------------------------------------------------- #
# 签名 / 验签（RSA2 = SHA256withRSA）
# --------------------------------------------------------------------------- #


def build_sign_content(params: Mapping[str, Any], exclude: tuple[str, ...] = ("sign",)) -> str:
    """待签名串：剔除 exclude 与空值，按 key 字典序排序，k=v 用 & 连接（值不做 URL 编码）。

    两种口径（文档规定，不可混用）：
    - 请求签名：exclude=("sign",)——sign_type 参与签名
    - 通知验签：exclude=("sign", "sign_type")——两者都不参与
    """
    items = sorted(
        (key, str(value))
        for key, value in params.items()
        if key not in exclude and value is not None and str(value) != ""
    )
    return "&".join(f"{key}={value}" for key, value in items)


def sign_content(content: str, private_key) -> str:
    signature = private_key.sign(
        content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
    )
    return base64.b64encode(signature).decode("ascii")


def verify_content(content: str, sign_b64: str, public_key) -> bool:
    try:
        public_key.verify(
            base64.b64decode(sign_b64),
            content.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# 下单：alipay.trade.page.pay
# --------------------------------------------------------------------------- #


def _beijing_now() -> datetime:
    return datetime.now(TZ_SHANGHAI)


def _sanitize_subject(text: str) -> str:
    """文档红线：subject 不可使用 /,=,& 等特殊字符。清洗而不是报错——标题不值得打断支付。"""
    return re.sub(r"[/=&]", "-", str(text))[:256]


def _common_params(method: str) -> dict[str, str]:
    return {
        "app_id": _env("ALIPAY_APP_ID"),
        "method": method,
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": SIGN_TYPE,
        "timestamp": _beijing_now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
    }


def _signed(params: dict[str, str]) -> dict[str, str]:
    params = dict(params)
    params["sign"] = sign_content(build_sign_content(params), load_private_key())
    return params


def _auto_submit_form(params: Mapping[str, str]) -> str:
    """POST 表单（文档推荐方式）：隐藏域 + 自动提交脚本，前端写入新标签页即可。"""
    from html import escape

    inputs = "".join(
        f'<input type="hidden" name="{escape(key)}" value="{escape(str(value))}"/>'
        for key, value in sorted(params.items())
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>正在跳转支付宝…</title></head>'
        f'<body><form id="alipay_page_pay" method="post" action="{escape(_gateway())}">{inputs}'
        '<input type="submit" value="立即支付" style="display:none"/></form>'
        "<script>document.forms[0].submit();</script></body></html>"
    )


def _gateway() -> str:
    return _env("ALIPAY_GATEWAY", DEFAULT_GATEWAY)


def build_page_pay(order: dict) -> dict:
    """为一笔本地订单生成支付宝收银台入口（GET 链接 + POST 表单两种，前端任选）。"""
    product = PRODUCTS.get(order["product_code"])
    subject = _sanitize_subject(product["name_zh"] if product else "有谱掌柜通行证")
    biz = {
        "out_trade_no": order["out_trade_no"],
        "total_amount": order["amount"],
        "subject": subject,
        "product_code": PRODUCT_CODE,
        "time_expire": (_beijing_now() + timedelta(minutes=ORDER_EXPIRE_MINUTES)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }
    params = _common_params("alipay.trade.page.pay")
    params["notify_url"] = _env("ALIPAY_NOTIFY_URL")
    return_url = _env("ALIPAY_RETURN_URL")
    if return_url:
        params["return_url"] = return_url
    params["biz_content"] = json.dumps(biz, ensure_ascii=False, separators=(",", ":"))
    signed = _signed(params)
    return {
        "channel": "alipay_page_pay",
        "out_trade_no": order["out_trade_no"],
        "amount": order["amount"],
        "pay_url": _gateway() + "?" + urlencode(signed),
        "form_html": _auto_submit_form(signed),
        "instructions": "将打开支付宝收银台（电脑网站支付），支付完成后回到本页自动确认",
    }


# --------------------------------------------------------------------------- #
# 异步通知验签
# --------------------------------------------------------------------------- #


def verify_notify(params: Mapping[str, str]) -> dict:
    """验签 + 身份二次校验，返回归一化通知信息。任何一步不过 → PayError。

    分工（与文档的"验签成功后再二次校验"对应）：
    - 这里管：签名真伪、app_id 是不是我们、seller_id 是不是我们、必备字段在不在
    - clerk.pay.handle_paid_notification 管：out_trade_no 是不是我们的订单、金额是否逐分一致、
      状态机流转与幂等——**金额核对刻意不放这里**，保证"钱的判断"只有一处。
    """
    sign = params.get("sign")
    if not sign:
        raise PayError("异步通知缺少 sign 参数")

    content = build_sign_content(params, exclude=("sign", "sign_type"))
    if not verify_content(content, sign, load_public_key()):
        raise PayError("异步通知验签失败——伪造通知或 ALIPAY_PUBLIC_KEY 配置错误")

    app_id = params.get("app_id")
    if app_id != _env("ALIPAY_APP_ID"):
        raise PayError(f"通知 app_id（{app_id}）与本应用不一致——忽略")

    seller_expected = _env("ALIPAY_SELLER_ID")
    seller_actual = params.get("seller_id")
    if seller_expected and seller_actual and seller_actual != seller_expected:
        raise PayError("通知 seller_id 与本商户不一致——忽略")

    trade_status = params.get("trade_status")
    out_trade_no = params.get("out_trade_no")
    total_amount = params.get("total_amount")
    if not trade_status or not out_trade_no or not total_amount:
        raise PayError("通知缺少 trade_status / out_trade_no / total_amount")

    has_refund = bool(params.get("gmt_refund"))
    if not has_refund:
        try:
            has_refund = Decimal(str(params.get("refund_fee") or "0")) > 0
        except ArithmeticError:
            has_refund = False

    return {
        "app_id": app_id,
        "out_trade_no": out_trade_no,
        "amount": total_amount,
        "trade_no": params.get("trade_no"),
        "trade_status": trade_status,
        "seller_id": seller_actual,
        "gmt_payment": params.get("gmt_payment"),
        "has_refund": has_refund,
        "notify_id": params.get("notify_id"),
    }


# --------------------------------------------------------------------------- #
# 服务端 API 调用（查询 / 退款）
# --------------------------------------------------------------------------- #


def _verify_gateway_response(text: str, node: str) -> None:
    """响应验签：切出 node 的原始 JSON 子串验签（官方 SDK 同款字符串切片做法）。"""
    marker = f'"{node}":'
    start = text.find(marker)
    sign_index = text.rfind('"sign"')
    if start < 0 or sign_index < 0:
        return  # 网关级错误响应没有 sign，可跳过（业务层按 code 处理）
    content = text[start + len(marker): sign_index].rstrip()
    if content.endswith(","):
        content = content[:-1]
    try:
        sign_b64 = json.loads(text[sign_index:].split(":", 1)[1].rsplit("}", 1)[0].strip().rstrip(","))
    except (json.JSONDecodeError, IndexError):
        return
    if not verify_content(content.strip(), sign_b64, load_public_key()):
        raise PayError(f"网关响应验签失败（{node}）——拒绝采信")


def execute_api(method: str, biz: dict) -> dict:
    """通用网关调用：签名 → POST → 响应验签 → 拆出业务 body。

    公开给 machine_pay 复用（alipay.aipay.agent.* 两个接口走同一条路）。
    """
    params = _common_params(method)
    params["biz_content"] = json.dumps(biz, ensure_ascii=False, separators=(",", ":"))
    signed = _signed(params)
    try:
        # trust_env=False：支付链路直连网关，绝不被本机/宿主的环境变量代理劫持或打断
        # （2026-11-26 真实事故：作者机器残留畸形代理环境变量，httpx 解析期就炸——
        #   支付是产品的命门，环境怪癖不许碰它）
        response = httpx.post(_gateway(), data=signed, timeout=15.0, trust_env=False)
    except httpx.HTTPError as exc:
        raise PayError(f"调用支付宝网关失败：{exc}") from exc
    text = response.text
    node = method.replace(".", "_") + "_response"
    _verify_gateway_response(text, node)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PayError(f"网关返回不是合法 JSON：{text[:200]}") from exc
    body = data.get(node)
    if not isinstance(body, dict):
        raise PayError(f"网关返回缺少 {node}：{text[:200]}")
    return body


def query_trade(out_trade_no: str) -> dict:
    """统一收单交易查询。文档：可以直接调查询接口，不需要依赖异步通知（兜底通道）。"""
    return execute_api("alipay.trade.query", {"out_trade_no": out_trade_no})


def refund_trade(out_trade_no: str, refund_amount: str, out_request_no: str, reason: str = "退款") -> dict:
    """统一收单交易退款（同步返回结果；部分退款需不同的 out_request_no）。"""
    return execute_api(
        "alipay.trade.refund",
        {
            "out_trade_no": out_trade_no,
            "refund_amount": refund_amount,
            "out_request_no": out_request_no,
            "refund_reason": _sanitize_subject(reason),
        },
    )


class VibePayAdapter:
    """clerk.pay 的适配器接口实现：create_payment 出收银台入口。

    notify/query 的接线在 server 层（HTTP 入口），适配器只管"把用户送去付钱"。
    """

    name = "alipay_page_pay"

    def create_payment(self, order: dict) -> dict:
        return build_page_pay(order)
