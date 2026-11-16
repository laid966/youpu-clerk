"""支付模块：订单/权益状态机 + 渠道适配器边界。

## 先写什么、后补什么
G2（收款路径调研）还没回来，所以 Vibe Pay 特有的部分（真实下单链接、回调验签、
接口字段）留在适配器边界之外——现在只有 FakeAdapter（联调与测试用）。
但**状态机、幂等、权益计算是平台无关的**，先写死写稳：
无论最终走基础收款能力、智能收款套件还是 Machine Pay 402，这一层都不作废。

## 状态机（orders.status）

    created ──(支付成功通知·校验通过)──► paid ──(退款通知)──► refunded

## 幂等与校验的三条纪律（每条都有测试）
1. 通知按 out_trade_no 定位订单；同一订单的 paid 通知**重放任意次，权益只发放一次**
2. 通知金额 ≠ 订单金额 → 拒绝并大声报错（防篡改，也防串单）
3. 权益 = users.plan + plan_expires_at；续费从"当前到期时间与现在的较晚者"往后加 30 天
   （叠加式续期，不吃掉用户已付的天数）

## 生产安全线
未签名回调入口在生产上绝不能开：/api/pay/notify-dev 只在 CLERK_PAY_DEV=1 时工作。
G2 之后由 VibePayAdapter.verify_notify()（验签）接管真实回调，这个开发入口保持关闭。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from clerk import config, db
from clerk.bargain import BargainError, to_money

__all__ = [
    "PAID_PLAN",
    "PRODUCTS",
    "FakeAdapter",
    "OrderRejected",
    "PayError",
    "UnknownProduct",
    "create_order",
    "dev_mode",
    "entitlement",
    "get_adapter",
    "get_order",
    "handle_paid_notification",
    "handle_refund_notification",
    "plan_is_active",
]

PAID_PLAN = "paid30"
_EXPIRY_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# 商品表：价格取值来自 clerk/config.py（★作者文件★），这里只登记结构。
# 价格入库前先 to_money 归一——"6.9" 必须变成 "6.90"，金额两位小数的纪律从定义处就开始。
PRODUCTS: dict[str, dict[str, Any]] = {
    "pass30_early": {
        "price": to_money(config.PRICE_30D_EARLY_BIRD),
        "days": 30,
        "name_zh": "30 天通行证（早鸟）",
        "name_en": "30-Day Pass (Early Bird)",
    },
    "pass30": {
        "price": to_money(config.PRICE_30D),
        "days": 30,
        "name_zh": "30 天通行证",
        "name_en": "30-Day Pass",
    },
}


class PayError(ValueError):
    """支付层错误基类（订单不存在、产品不存在、状态非法）。"""


class UnknownProduct(PayError):
    def __init__(self, product_code: str) -> None:
        super().__init__(f"没有这个商品代码：{product_code}（可选：{'/'.join(PRODUCTS)}）")
        self.product_code = product_code


class OrderRejected(PayError):
    """通知校验失败：金额不符、状态冲突。宁可拒绝也不含糊入账。"""


def dev_mode() -> bool:
    """联调通道开关。生产环境不设置 CLERK_PAY_DEV，未签名回调一律 403。"""
    return os.getenv("CLERK_PAY_DEV") == "1"


# --------------------------------------------------------------------------- #
# 适配器边界：G2 之后 VibePayAdapter 实现同样两个方法即可无缝替换
# --------------------------------------------------------------------------- #


class FakeAdapter:
    """联调适配器：不连任何真实渠道。

    create_payment 返回的是**说明**而不是支付链接——我们不假装能收款。
    真实接入（G2 后）要做的两件事：
    1. create_payment → 调 Vibe Pay 下单，返回收银台链接/二维码
    2. verify_notify → 验签真实异步通知，解析出 (out_trade_no, amount, trade_no)
    """

    name = "fake"

    def create_payment(self, order: dict) -> dict:
        if dev_mode():
            return {
                "channel": self.name,
                "dev": True,
                "out_trade_no": order["out_trade_no"],
                "amount": order["amount"],
                "instructions": "联调通道：调用 POST /api/pay/notify-dev 模拟支付成功（生产环境此入口关闭）",
            }
        return {
            "channel": self.name,
            "dev": False,
            "out_trade_no": order["out_trade_no"],
            "amount": order["amount"],
            "instructions": "真实支付通道接入中（G2 闸门）——签约完成后此处将跳转支付宝收银台",
        }


_ADAPTER = FakeAdapter()


def get_adapter() -> FakeAdapter:
    return _ADAPTER


# --------------------------------------------------------------------------- #
# 订单
# --------------------------------------------------------------------------- #


def _out_trade_no() -> str:
    return "YP" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + os.urandom(3).hex().upper()


def create_order(conn: sqlite3.Connection, token: str, product_code: str) -> dict:
    product = PRODUCTS.get(product_code)
    if product is None:
        raise UnknownProduct(product_code)
    db.ensure_user(conn, token)
    order_id = db.new_id()
    conn.execute(
        "INSERT INTO orders(id, token, out_trade_no, product_code, amount, status, created_at)"
        " VALUES(?,?,?,?,?, 'created', ?)",
        (order_id, token, _out_trade_no(), product_code, str(product["price"]), db.now_iso()),
    )
    conn.commit()
    order = get_order(conn, order_id=order_id)
    assert order is not None  # 刚插入必须能读回
    return order


def get_order(
    conn: sqlite3.Connection, *, order_id: str | None = None, out_trade_no: str | None = None
) -> dict | None:
    if order_id:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    elif out_trade_no:
        row = conn.execute("SELECT * FROM orders WHERE out_trade_no = ?", (out_trade_no,)).fetchone()
    else:
        raise PayError("get_order 需要 order_id 或 out_trade_no 之一")
    return dict(row) if row else None


# --------------------------------------------------------------------------- #
# 支付/退款通知（幂等状态机）
# --------------------------------------------------------------------------- #


def handle_paid_notification(
    conn: sqlite3.Connection,
    *,
    out_trade_no: str,
    amount: Any,
    trade_no: str | None = None,
    raw: dict | None = None,
) -> dict:
    """处理"支付成功"通知。可重放：同一订单第二次进来直接返回 already=True。

    校验顺序（每一步都有测试）：
    订单存在 → 金额逐分一致 → 状态允许（created→paid；paid→幂等；refunded→拒绝）
    → 落库（带 WHERE status='created' 的并发保护）→ 权益续期。
    """
    order = get_order(conn, out_trade_no=out_trade_no)
    if order is None:
        raise PayError(f"订单不存在：{out_trade_no}")

    try:
        notified = to_money(amount)
    except BargainError as exc:
        raise OrderRejected(f"通知金额不是合法金额：{amount!r}") from exc
    if notified != Decimal(order["amount"]):
        raise OrderRejected(
            f"金额不符：通知 {notified} vs 订单 {order['amount']}——拒绝入账（防篡改/防串单）"
        )

    if order["status"] == "paid":
        return {"already": True, "order": order, "entitlement": entitlement(conn, order["token"])}
    if order["status"] == "refunded":
        raise OrderRejected(f"订单 {out_trade_no} 已退款，不能再标记支付——需要人工核查")
    if order["status"] != "created":
        raise OrderRejected(f"订单状态非法：{order['status']}")

    notify_json = json.dumps(
        {"out_trade_no": out_trade_no, "amount": str(notified), "trade_no": trade_no, "raw": raw},
        ensure_ascii=False,
    )
    cursor = conn.execute(
        "UPDATE orders SET status = 'paid', paid_at = ?, notify_json = ?"
        " WHERE id = ? AND status = 'created'",
        (db.now_iso(), notify_json, order["id"]),
    )
    conn.commit()
    if cursor.rowcount == 0:
        # 并发重放：另一个请求刚刚把它置为 paid——同样是幂等成功
        order = get_order(conn, order_id=order["id"])
        return {"already": True, "order": order, "entitlement": entitlement(conn, order["token"])}

    _extend_entitlement(conn, order["token"], PRODUCTS[order["product_code"]]["days"])
    order = get_order(conn, order_id=order["id"])
    return {"already": False, "order": order, "entitlement": entitlement(conn, order["token"])}


def handle_refund_notification(
    conn: sqlite3.Connection, *, out_trade_no: str, raw: dict | None = None
) -> dict:
    """退款：paid → refunded，权益立即降回免费层。

    MVP 的诚实简化：多次续期后发生任一笔退款，权益整体降为 free——
    不做"退一笔扣一段"的比例核算（真实商户场景再引入）。
    """
    order = get_order(conn, out_trade_no=out_trade_no)
    if order is None:
        raise PayError(f"订单不存在：{out_trade_no}")
    if order["status"] != "paid":
        raise OrderRejected(f"只有 paid 订单能退款，当前状态：{order['status']}")
    conn.execute(
        "UPDATE orders SET status = 'refunded', notify_json = ? WHERE id = ?",
        (json.dumps({"refund": True, "raw": raw}, ensure_ascii=False), order["id"]),
    )
    conn.execute(
        "UPDATE users SET plan = 'free' WHERE token = ?",
        (order["token"],),
    )
    conn.commit()
    return {"order": get_order(conn, order_id=order["id"]), "entitlement": entitlement(conn, order["token"])}


# --------------------------------------------------------------------------- #
# 权益
# --------------------------------------------------------------------------- #


def _parse_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, _EXPIRY_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def plan_is_active(user: dict) -> bool:
    """纯函数：这个 user 行现在是不是付费态。service 的额度闸口只信它。"""
    if user.get("plan") != PAID_PLAN:
        return False
    expiry = _parse_expiry(user.get("plan_expires_at"))
    if expiry is None:
        return False  # 付费计划却没有到期时间 = 数据坏了 = 按免费处理（对用户宽、对账目严）
    return expiry > datetime.now(timezone.utc)


def _extend_entitlement(conn: sqlite3.Connection, token: str, days: int) -> None:
    """续期：从 max(now, 当前到期) 往后加 days 天——已付天数不被吃掉。"""
    user = db.ensure_user(conn, token)
    now = datetime.now(timezone.utc)
    current = _parse_expiry(user.get("plan_expires_at"))
    base = now if (current is None or current < now) else current
    new_expiry = (base + timedelta(days=days)).strftime(_EXPIRY_FORMAT)
    conn.execute(
        "UPDATE users SET plan = ?, plan_expires_at = ? WHERE token = ?",
        (PAID_PLAN, new_expiry, token),
    )
    conn.commit()


def entitlement(conn: sqlite3.Connection, token: str) -> dict:
    """当前权益（含懒惰降级：过期的 paid30 读到时顺手改回 free，别处代码就不用各自判过期）。"""
    user = db.ensure_user(conn, token)
    active = plan_is_active(user)
    if user["plan"] == PAID_PLAN and not active:
        conn.execute("UPDATE users SET plan = 'free' WHERE token = ?", (token,))
        conn.commit()
        user = db.ensure_user(conn, token)
    return {
        "plan": PAID_PLAN if active else "free",
        "expires_at": user["plan_expires_at"] if active else None,
        "active": active,
    }
