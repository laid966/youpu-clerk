"""clerk.pay_vibe 测试：签名/验签/下单参数/异步通知——全部离线。

真实通道的测试替身：现场生成一对 RSA 密钥扮演"支付宝"——
用测试私钥给异步通知签名，用配置进去的测试公钥验签。
**密码学路径与生产完全一致，只是密钥是我们自己的**；一个字节都不出网。
"""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import clerk.db as db
from clerk import pay, pay_vibe
from clerk.server import app

# 一对测试密钥扮演支付宝（模块级生成一次，2048 位约 0.1s）
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIV_B64 = base64.b64encode(
    _KEY.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
).decode()
PUB_B64 = base64.b64encode(
    _KEY.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
).decode()

APP_ID = "2021000000000001"
SELLER_ID = "2088000000000001"


@pytest.fixture()
def vibe_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALIPAY_APP_ID", APP_ID)
    monkeypatch.setenv("ALIPAY_PRIVATE_KEY", PRIV_B64)
    monkeypatch.setenv("ALIPAY_PUBLIC_KEY", PUB_B64)
    monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://example.com/api/pay/notify")
    monkeypatch.setenv("ALIPAY_RETURN_URL", "https://example.com/?pay_return=1")
    monkeypatch.setenv("ALIPAY_SELLER_ID", SELLER_ID)
    monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
    monkeypatch.delenv("CLERK_PAY_DEV", raising=False)
    pay_vibe.reset_key_cache()
    yield
    pay_vibe.reset_key_cache()


@pytest.fixture()
def client(vibe_env):
    with TestClient(app) as test_client:
        test_client.headers.update({"X-Clerk-User": "tok-vibe"})
        yield test_client


def make_notify(out_trade_no: str, amount: str, trade_status: str = "TRADE_SUCCESS", **overrides) -> dict:
    """伪造一条"来自支付宝"的异步通知：结构按官方文档，签名用测试私钥。"""
    params = {
        "notify_time": "2026-11-16 20:00:00",
        "notify_type": "trade_status_sync",
        "notify_id": "notify-" + out_trade_no,
        "trade_no": "2026111621001004680000000001",
        "app_id": APP_ID,
        "out_trade_no": out_trade_no,
        "seller_id": SELLER_ID,
        "trade_status": trade_status,
        "total_amount": amount,
        "receipt_amount": amount,
        "gmt_payment": "2026-11-16 20:00:01",
    }
    params.update(overrides)
    content = pay_vibe.build_sign_content(params, exclude=("sign", "sign_type"))
    params["sign"] = pay_vibe.sign_content(content, pay_vibe.load_private_key(PRIV_B64))
    params["sign_type"] = "RSA2"
    return params


class TestConfiguration:
    def test_configured_with_full_credentials(self, vibe_env):
        assert pay_vibe.is_configured() is True

    def test_not_configured_without_keys(self, monkeypatch):
        for name in ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY", "ALIPAY_NOTIFY_URL"):
            monkeypatch.delenv(name, raising=False)
        assert pay_vibe.is_configured() is False

    def test_adapter_selection_follows_configuration(self, vibe_env):
        assert isinstance(pay.get_adapter(), pay_vibe.VibePayAdapter)


class TestPagePay:
    def test_pay_url_signature_verifiable(self, vibe_env, tmp_path):
        conn = db.open_db()
        try:
            db.ensure_user(conn, "tok")
            order = pay.create_order(conn, "tok", "pass30_early")
            result = pay_vibe.build_page_pay(order)

            parsed = urlparse(result["pay_url"])
            query = parse_qs(parsed.query, keep_blank_values=True)
            sign = query.pop("sign")[0]
            flat = {key: values[0] for key, values in query.items()}

            # 请求签名口径：exclude 只有 sign（sign_type 参与签名）
            content = pay_vibe.build_sign_content(flat)
            assert pay_vibe.verify_content(content, sign, pay_vibe.load_public_key(PUB_B64))

            assert flat["method"] == "alipay.trade.page.pay"
            assert flat["sign_type"] == "RSA2"
            assert flat["charset"] == "utf-8"
            biz = json.loads(flat["biz_content"])
            assert biz["product_code"] == "FAST_INSTANT_TRADE_PAY"  # 文档唯一枚举值
            assert biz["total_amount"] == "6.90"
            assert biz["out_trade_no"] == order["out_trade_no"]
            assert biz["subject"]  # 非空标题
        finally:
            conn.close()

    def test_form_html_auto_submits(self, vibe_env):
        conn = db.open_db()
        try:
            db.ensure_user(conn, "tok")
            order = pay.create_order(conn, "tok", "pass30")
            form = pay_vibe.build_page_pay(order)["form_html"]
            assert 'method="post"' in form
            assert "document.forms[0].submit()" in form
            assert 'name="biz_content"' in form
        finally:
            conn.close()

    def test_subject_special_chars_sanitized(self):
        assert pay_vibe._sanitize_subject("a/b=c&d") == "a-b-c-d"


class TestNotifyVerification:
    def test_roundtrip(self, vibe_env):
        signed = make_notify("YP20261116000001ABCDEF", "6.90")
        info = pay_vibe.verify_notify(signed)
        assert info["out_trade_no"] == "YP20261116000001ABCDEF"
        assert info["amount"] == "6.90"
        assert info["trade_status"] == "TRADE_SUCCESS"
        assert info["has_refund"] is False

    def test_tampered_amount_fails(self, vibe_env):
        signed = make_notify("YP20261116000001ABCDEF", "6.90")
        signed["total_amount"] = "0.01"  # 篡改金额 → 签名覆盖不住
        with pytest.raises(pay.PayError, match="验签失败"):
            pay_vibe.verify_notify(signed)

    def test_wrong_app_id_rejected(self, vibe_env):
        signed = make_notify("YPX1", "6.90", app_id="2099999999999999")
        with pytest.raises(pay.PayError, match="app_id"):
            pay_vibe.verify_notify(signed)

    def test_wrong_seller_rejected(self, vibe_env):
        signed = make_notify("YPX2", "6.90", seller_id="2088999999999999")
        with pytest.raises(pay.PayError, match="seller_id"):
            pay_vibe.verify_notify(signed)

    def test_missing_sign_rejected(self, vibe_env):
        signed = make_notify("YPX3", "6.90")
        del signed["sign"]
        with pytest.raises(pay.PayError, match="sign"):
            pay_vibe.verify_notify(signed)

    def test_garbage_sign_rejected(self, vibe_env):
        signed = make_notify("YPX4", "6.90")
        signed["sign"] = base64.b64encode(b"forged" * 40).decode()
        with pytest.raises(pay.PayError, match="验签失败"):
            pay_vibe.verify_notify(signed)

    def test_refund_flags_detected(self, vibe_env):
        signed = make_notify(
            "YPX5", "6.90", trade_status="TRADE_CLOSED",
            gmt_refund="2026-11-16 21:00:00", refund_fee="6.90",
        )
        info = pay_vibe.verify_notify(signed)
        assert info["trade_status"] == "TRADE_CLOSED"
        assert info["has_refund"] is True


class TestNotifyEndpoint:
    def _order(self, client) -> dict:
        body = client.post("/api/pay/order", json={"product_code": "pass30_early"}).json()
        assert body["payment"]["channel"] == "alipay_page_pay"  # 凭证齐全 → 真实适配器
        return body["order"]

    def test_paid_notification_activates_entitlement(self, client):
        order = self._order(client)
        response = client.post("/api/pay/notify", data=make_notify(order["out_trade_no"], order["amount"]))
        assert response.text == "success"  # 纯文本，无引号无 JSON
        entitlement = client.get("/api/entitlements/me").json()
        assert entitlement["plan"] == "paid30"
        assert entitlement["active"] is True

    def test_replayed_notification_stays_success_and_idempotent(self, client):
        order = self._order(client)
        form = make_notify(order["out_trade_no"], order["amount"])
        assert client.post("/api/pay/notify", data=form).text == "success"
        expiry = client.get("/api/entitlements/me").json()["expires_at"]
        # 支付宝会按 4m/10m/10m/1h/2h/6h/15h 重发——重发必须安全
        for _ in range(3):
            assert client.post("/api/pay/notify", data=form).text == "success"
        assert client.get("/api/entitlements/me").json()["expires_at"] == expiry

    def test_forged_notification_gets_failure(self, client):
        order = self._order(client)
        forged = make_notify(order["out_trade_no"], order["amount"])
        forged["sign"] = base64.b64encode(b"x" * 256).decode()
        assert client.post("/api/pay/notify", data=forged).text == "failure"
        assert client.get("/api/entitlements/me").json()["plan"] == "free"

    def test_amount_mismatch_gets_failure(self, client):
        order = self._order(client)
        # 签名合法但金额与订单不符：验签过、状态机拒——返回 failure，权益不动
        signed = make_notify(order["out_trade_no"], "0.01")
        assert client.post("/api/pay/notify", data=signed).text == "failure"
        assert client.get("/api/entitlements/me").json()["plan"] == "free"

    def test_wait_buyer_pay_is_acknowledged_without_effect(self, client):
        order = self._order(client)
        signed = make_notify(order["out_trade_no"], order["amount"], trade_status="WAIT_BUYER_PAY")
        assert client.post("/api/pay/notify", data=signed).text == "success"
        assert client.get("/api/entitlements/me").json()["plan"] == "free"

    def test_refund_notification_revokes(self, client):
        order = self._order(client)
        client.post("/api/pay/notify", data=make_notify(order["out_trade_no"], order["amount"]))
        refund = make_notify(
            order["out_trade_no"], order["amount"], trade_status="TRADE_CLOSED",
            gmt_refund="2026-11-16 21:00:00", refund_fee=order["amount"],
            out_biz_no="REFUND001",
        )
        assert client.post("/api/pay/notify", data=refund).text == "success"
        assert client.get("/api/entitlements/me").json()["plan"] == "free"


class TestQueryEndpoint:
    def test_query_activates_from_gateway_result(self, client, monkeypatch):
        """文档：可以不依赖异步通知，直接查询兜底。模拟网关返回 TRADE_SUCCESS。"""
        monkeypatch.setattr(
            pay_vibe,
            "query_trade",
            lambda out_trade_no: {
                "code": "10000",
                "trade_status": "TRADE_SUCCESS",
                "total_amount": "6.90",
                "trade_no": "T-GATEWAY-1",
            },
        )
        order = client.post("/api/pay/order", json={"product_code": "pass30_early"}).json()["order"]
        body = client.post("/api/pay/query", json={"out_trade_no": order["out_trade_no"]}).json()
        assert body["order"]["status"] == "paid"
        assert body["entitlement"]["active"] is True

    def test_query_rejects_other_users_order(self, client):
        order = client.post("/api/pay/order", json={"product_code": "pass30_early"}).json()["order"]
        response = client.post(
            "/api/pay/query",
            json={"out_trade_no": order["out_trade_no"]},
            headers={"X-Clerk-User": "intruder"},
        )
        assert response.status_code == 400  # 越权与不存在同一个错，不泄露订单号存在性
