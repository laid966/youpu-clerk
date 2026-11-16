"""clerk.pay 状态机测试：幂等、金额校验、续期叠加、过期降级、额度联动。

G3（真钱收款）之前把这层钉死：钱的状态机出错，比功能缺失严重一个量级。
这里全部用 FakeAdapter/dev 通道测——**状态机是平台无关的**，
G2 之后换 VibePayAdapter 时这批测试原样复用（这正是先写它的理由）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import clerk.db as db
from clerk import config, pay
from clerk.service import QuotaExceeded, suggest
from clerk.templates import TemplateJudge

EXPIRY_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
    connection = db.open_db()
    db.ensure_user(connection, "tok")
    yield connection
    connection.close()


class TestOrders:
    def test_create_order_money_two_decimals(self, conn):
        order = pay.create_order(conn, "tok", "pass30_early")
        assert order["amount"] == "6.90"  # Decimal("6.9") 必须归一成两位小数
        assert order["status"] == "created"
        assert order["out_trade_no"].startswith("YP")

    def test_unknown_product_raises(self, conn):
        with pytest.raises(pay.UnknownProduct):
            pay.create_order(conn, "tok", "gold-membership")


class TestPaidNotification:
    def test_activation(self, conn):
        order = pay.create_order(conn, "tok", "pass30_early")
        result = pay.handle_paid_notification(
            conn, out_trade_no=order["out_trade_no"], amount="6.90", trade_no="T1"
        )
        assert result["already"] is False
        assert result["order"]["status"] == "paid"
        assert result["entitlement"]["active"] is True
        assert result["entitlement"]["plan"] == "paid30"

    def test_replay_ten_times_grants_once(self, conn):
        """验收硬指标（计划第八节）：同一通知重放 10 次，权益只发 1 次、到期时间不多延一秒。"""
        order = pay.create_order(conn, "tok", "pass30_early")
        first = pay.handle_paid_notification(conn, out_trade_no=order["out_trade_no"], amount="6.90")
        expiry = first["entitlement"]["expires_at"]
        for _ in range(9):
            again = pay.handle_paid_notification(conn, out_trade_no=order["out_trade_no"], amount="6.90")
            assert again["already"] is True
        assert again["entitlement"]["expires_at"] == expiry

    def test_amount_mismatch_rejected(self, conn):
        order = pay.create_order(conn, "tok", "pass30_early")
        with pytest.raises(pay.OrderRejected, match="金额不符"):
            pay.handle_paid_notification(conn, out_trade_no=order["out_trade_no"], amount="0.01")
        # 拒绝后订单必须还停在 created——半途状态不许出现
        assert pay.get_order(conn, out_trade_no=order["out_trade_no"])["status"] == "created"

    def test_amount_mismatch_overpay_also_rejected(self, conn):
        """多付也拒绝：金额"不符"就是不符，方向不重要（防串单）。"""
        order = pay.create_order(conn, "tok", "pass30_early")
        with pytest.raises(pay.OrderRejected):
            pay.handle_paid_notification(conn, out_trade_no=order["out_trade_no"], amount="999.00")

    def test_unknown_order_raises(self, conn):
        with pytest.raises(pay.PayError):
            pay.handle_paid_notification(conn, out_trade_no="YPNOTREAL", amount="6.90")

    def test_renewal_stacks_from_current_expiry(self, conn):
        o1 = pay.create_order(conn, "tok", "pass30_early")
        r1 = pay.handle_paid_notification(conn, out_trade_no=o1["out_trade_no"], amount="6.90")
        o2 = pay.create_order(conn, "tok", "pass30_early")
        r2 = pay.handle_paid_notification(conn, out_trade_no=o2["out_trade_no"], amount="6.90")
        e1 = datetime.strptime(r1["entitlement"]["expires_at"], EXPIRY_FORMAT)
        e2 = datetime.strptime(r2["entitlement"]["expires_at"], EXPIRY_FORMAT)
        # 续期从当前到期时间往后叠 30 天，不吃掉已付天数
        assert 29 <= (e2 - e1).days <= 31


class TestRefund:
    def test_refund_revokes_entitlement(self, conn):
        order = pay.create_order(conn, "tok", "pass30")
        pay.handle_paid_notification(conn, out_trade_no=order["out_trade_no"], amount="9.90")
        result = pay.handle_refund_notification(conn, out_trade_no=order["out_trade_no"])
        assert result["order"]["status"] == "refunded"
        assert result["entitlement"]["active"] is False

    def test_paid_after_refund_rejected(self, conn):
        order = pay.create_order(conn, "tok", "pass30")
        pay.handle_paid_notification(conn, out_trade_no=order["out_trade_no"], amount="9.90")
        pay.handle_refund_notification(conn, out_trade_no=order["out_trade_no"])
        with pytest.raises(pay.OrderRejected):
            pay.handle_paid_notification(conn, out_trade_no=order["out_trade_no"], amount="9.90")

    def test_refund_unpaid_order_rejected(self, conn):
        order = pay.create_order(conn, "tok", "pass30")
        with pytest.raises(pay.OrderRejected):
            pay.handle_refund_notification(conn, out_trade_no=order["out_trade_no"])


class TestEntitlement:
    def test_expired_paid_downgrades_lazily(self, conn):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(EXPIRY_FORMAT)
        conn.execute(
            "UPDATE users SET plan='paid30', plan_expires_at=? WHERE token='tok'", (past,)
        )
        conn.commit()
        result = pay.entitlement(conn, "tok")
        assert result["active"] is False
        assert result["plan"] == "free"
        # 懒惰降级要落库：其他地方直接读 users.plan 也不会被骗
        assert db.ensure_user(conn, "tok")["plan"] == "free"

    def test_plan_is_active_requires_expiry(self, conn):
        assert pay.plan_is_active({"plan": "paid30", "plan_expires_at": None}) is False
        future = (datetime.now(timezone.utc) + timedelta(days=1)).strftime(EXPIRY_FORMAT)
        assert pay.plan_is_active({"plan": "paid30", "plan_expires_at": future}) is True
        assert pay.plan_is_active({"plan": "free", "plan_expires_at": future}) is False


class TestQuotaIntegration:
    """额度闸口与支付状态的联动：付费放行、过期收回。"""

    def _item(self, conn):
        return db.create_item(conn, "tok", "机械键盘", "399.00", "339.15")

    def test_paid_user_bypasses_quota(self, conn, monkeypatch):
        monkeypatch.setattr(config, "FREE_DAILY_SUGGESTIONS", 0)  # 免费额度=0：免费用户一步都走不了
        item = self._item(conn)
        order = pay.create_order(conn, "tok", "pass30_early")
        pay.handle_paid_notification(conn, out_trade_no=order["out_trade_no"], amount="6.90")
        result = suggest(
            token="tok", item_id=item["id"], message="300行不行", judge=TemplateJudge(), conn=conn
        )
        assert result["decision"]["kind"] == "counter"

    def test_expired_paid_user_blocked_again(self, conn, monkeypatch):
        monkeypatch.setattr(config, "FREE_DAILY_SUGGESTIONS", 0)
        item = self._item(conn)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(EXPIRY_FORMAT)
        conn.execute(
            "UPDATE users SET plan='paid30', plan_expires_at=? WHERE token='tok'", (past,)
        )
        conn.commit()
        with pytest.raises(QuotaExceeded):
            suggest(
                token="tok", item_id=item["id"], message="300行不行", judge=TemplateJudge(), conn=conn
            )
