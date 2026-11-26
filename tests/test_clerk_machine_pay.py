"""clerk.machine_pay 测试：402 账单签发 / 凭证校验 / 防重放 / 交付顺序——全部离线。

与 pay_vibe 测试同一套路：自造密钥对扮演支付宝，网关调用被 monkeypatch，
密码学与状态流转走的都是生产代码路径。
"""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import clerk.db as db
from clerk import config, machine_pay, pay_vibe
from clerk.pay import PayError
from clerk.server import app

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIV_B64 = base64.b64encode(
    _KEY.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
).decode()

SELLER_ID = "2088000000000002"
APP_ID = "app_test_001"
SERVICE_ID = "svc_test_001"


@pytest.fixture()
def mp_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MACHINE_PAY_SELLER_ID", SELLER_ID)
    monkeypatch.setenv("MACHINE_PAY_SELLER_APP_ID", APP_ID)
    monkeypatch.setenv("MACHINE_PAY_SERVICE_ID", SERVICE_ID)
    monkeypatch.setenv("ALIPAY_PRIVATE_KEY", PRIV_B64)
    monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
    pay_vibe.reset_key_cache()
    yield
    pay_vibe.reset_key_cache()


@pytest.fixture()
def client(mp_env):
    with TestClient(app) as test_client:
        yield test_client


def make_proof(payment_proof: str = "proof-abc", trade_no: str = "T-AGENT-1") -> str:
    payload = {
        "protocol": {"payment_proof": payment_proof, "trade_no": trade_no},
        "method": {"client_session": "session-xyz"},
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def stub_verify(monkeypatch, **overrides):
    """替换网关验证调用，返回一条"验证通过"的结果（可用 overrides 注水）。"""
    calls: list[dict] = []
    result = {
        "code": "10000",
        "active": True,
        "amount": str(config.MACHINE_PAY_PRICE),
        "out_trade_no": machine_pay.OUT_TRADE_PREFIX + "TEST",
        "trade_no": "T-AGENT-1",
        "resource_id": machine_pay.RESOURCE_ID,
    }
    result.update(overrides)

    def fake_execute(method: str, biz: dict) -> dict:
        calls.append({"method": method, "biz": biz})
        if method.endswith("payment.verify"):
            return result
        return {"code": "10000", "msg": "Success", "trade_no": biz.get("trade_no")}

    monkeypatch.setattr(pay_vibe, "execute_api", fake_execute)
    return calls


class TestConfiguration:
    def test_not_configured_without_env(self, monkeypatch):
        for name in ("MACHINE_PAY_SELLER_ID", "MACHINE_PAY_SELLER_APP_ID", "MACHINE_PAY_SERVICE_ID", "ALIPAY_PRIVATE_KEY"):
            monkeypatch.delenv(name, raising=False)
        assert machine_pay.is_configured() is False

    def test_endpoint_honest_501_when_not_configured(self, monkeypatch):
        monkeypatch.delenv("MACHINE_PAY_SELLER_ID", raising=False)
        with TestClient(app) as bare_client:
            response = bare_client.post(
                "/api/agent/bargain",
                json={"asking_price": "399.00", "buyer_offer": "300.00"},
            )
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "MACHINE_PAY_NOT_CONFIGURED"


class TestInvoice:
    def test_invoice_structure_and_signature(self, mp_env):
        invoice = machine_pay.build_invoice(machine_pay.new_out_trade_no())
        protocol = invoice["protocol"]
        method = invoice["method"]

        assert protocol["currency"] == "CNY"
        assert protocol["seller_sign_type"] == "RSA2"
        assert protocol["seller_unique_id"] == SELLER_ID
        assert protocol["amount"] == "0.01"  # = config.MACHINE_PAY_PRICE 两位小数
        assert method["seller_id"] == SELLER_ID
        assert method["seller_app_id"] == APP_ID
        assert method["service_id"] == SERVICE_ID
        assert method["seller_unique_id_key"] == "seller_id"

        # 签名可被公钥验证：签的正是文档规定的八个字段（字典序 k=v&）
        sign_source = {
            "amount": protocol["amount"],
            "currency": protocol["currency"],
            "goods_name": method["goods_name"],
            "out_trade_no": protocol["out_trade_no"],
            "pay_before": protocol["pay_before"],
            "resource_id": protocol["resource_id"],
            "seller_id": SELLER_ID,
            "service_id": method["service_id"],
        }
        content = pay_vibe.build_sign_content(sign_source)
        public_key = pay_vibe.load_public_key(
            base64.b64encode(
                _KEY.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            ).decode()
        )
        assert pay_vibe.verify_content(content, protocol["seller_signature"], public_key)

    def test_payment_needed_base64url_roundtrip(self, mp_env):
        invoice = machine_pay.build_invoice("MP20261116TEST01")
        header = machine_pay.encode_payment_needed(invoice)
        assert "+" not in header and "/" not in header and "=" not in header  # base64url 无 padding
        assert machine_pay.decode_payment_needed(header) == invoice

    def test_out_trade_no_prefix_and_uniqueness(self, mp_env):
        first = machine_pay.new_out_trade_no()
        second = machine_pay.new_out_trade_no()
        assert first.startswith(machine_pay.OUT_TRADE_PREFIX)
        assert first != second


class TestProofValidation:
    def test_parse_proof_requires_protocol_fields(self):
        broken = base64.b64encode(json.dumps({"protocol": {}}).encode()).decode()
        with pytest.raises(PayError, match="payment_proof"):
            machine_pay.parse_payment_proof(broken)

    def test_check_verification_rejects_inactive(self):
        with pytest.raises(PayError, match="active"):
            machine_pay.check_verification(
                {"active": False, "amount": "0.01", "out_trade_no": "MPX", "resource_id": machine_pay.RESOURCE_ID},
                expected_amount="0.01",
            )

    def test_check_verification_rejects_wrong_amount(self):
        with pytest.raises(PayError, match="金额不符"):
            machine_pay.check_verification(
                {"active": True, "amount": "0.02", "out_trade_no": "MPX", "resource_id": machine_pay.RESOURCE_ID},
                expected_amount="0.01",
            )

    def test_check_verification_rejects_foreign_order(self):
        with pytest.raises(PayError, match="不是本服务签发"):
            machine_pay.check_verification(
                {"active": True, "amount": "0.01", "out_trade_no": "ORDER_OTHER", "resource_id": machine_pay.RESOURCE_ID},
                expected_amount="0.01",
            )

    def test_check_verification_rejects_wrong_resource(self):
        with pytest.raises(PayError, match="resource_id"):
            machine_pay.check_verification(
                {"active": True, "amount": "0.01", "out_trade_no": "MPX", "resource_id": "clerk://other"},
                expected_amount="0.01",
            )


class TestEndpointFlow:
    BARGAIN_PAYLOAD = {"asking_price": "399.00", "buyer_offer": "300.00"}

    def test_no_proof_gets_402_with_invoice(self, client):
        response = client.post("/api/agent/bargain", json=self.BARGAIN_PAYLOAD)
        assert response.status_code == 402
        header = response.headers.get("payment-needed")
        assert header, "402 必须带 Payment-Needed 账单头"
        invoice = machine_pay.decode_payment_needed(header)
        assert invoice["protocol"]["amount"] == "0.01"
        assert invoice["protocol"]["resource_id"] == machine_pay.RESOURCE_ID
        assert response.json()["error"] == "Payment Needed"

    def test_paid_delivery_and_fulfillment_receipt(self, client, monkeypatch):
        calls = stub_verify(monkeypatch)
        response = client.post(
            "/api/agent/bargain",
            json=self.BARGAIN_PAYLOAD,
            headers={"Payment-Proof": make_proof()},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        decision = body["decision"]
        # 与人类通道同一颗引擎：399 挂牌、默认底价 339.15、出价 300 → 梯度第 1 档 379.05
        assert decision["kind"] == "counter"
        assert decision["price"] == "379.05"
        assert decision["rule_id"] == "BARGAIN-COUNTER-T1"
        assert decision["citations"]
        # 履约回执已发（文档：交付后异步 confirm）
        assert any(call["method"].endswith("fulfillment.confirm") for call in calls)

    def test_replayed_proof_rejected(self, client, monkeypatch):
        stub_verify(monkeypatch)
        proof = make_proof(trade_no="T-REPLAY")
        first = client.post("/api/agent/bargain", json=self.BARGAIN_PAYLOAD, headers={"Payment-Proof": proof})
        assert first.status_code == 200
        second = client.post("/api/agent/bargain", json=self.BARGAIN_PAYLOAD, headers={"Payment-Proof": proof})
        assert second.status_code == 402
        assert second.json()["error"]["code"] == "PROOF_REUSED"

    def test_inactive_proof_gets_402(self, client, monkeypatch):
        stub_verify(monkeypatch, active=False)
        response = client.post(
            "/api/agent/bargain", json=self.BARGAIN_PAYLOAD, headers={"Payment-Proof": make_proof(trade_no="T-INACTIVE")}
        )
        assert response.status_code == 402
        assert response.json()["error"]["code"] == "PROOF_INVALID"

    def test_bad_facts_do_not_burn_the_payment(self, client, monkeypatch):
        """先算资源再占 trade_no：坏入参 → 400，且同一凭证仍然可用（钱不白花）。"""
        stub_verify(monkeypatch)
        proof = make_proof(trade_no="T-REUSE-OK")
        bad = client.post(
            "/api/agent/bargain",
            json={"asking_price": "100.00", "buyer_offer": "0", "floor_price": "200.00"},
            headers={"Payment-Proof": proof},
        )
        assert bad.status_code == 400
        good = client.post("/api/agent/bargain", json=self.BARGAIN_PAYLOAD, headers={"Payment-Proof": proof})
        assert good.status_code == 200


class TestMachineDemoMode:
    """演示模式（MACHINE_PAY_DEMO=1）：评委零凭证零签约走通 A402 全时序，占位凭证不过真钱。"""

    BODY = {"asking_price": "399.00", "buyer_offer": "300.00"}

    @staticmethod
    def _demo_proof(out_trade_no: str, token: str = "DEMO-PAID") -> str:
        return base64.urlsafe_b64encode(
            json.dumps(
                {"protocol": {"payment_proof": token, "trade_no": out_trade_no}, "method": {"client_session": "demo"}},
                separators=(",", ":"),
            ).encode("utf-8")
        ).rstrip(b"=").decode("ascii")

    def test_demo_flow_and_replay_guard(self, client, monkeypatch):
        monkeypatch.setenv("MACHINE_PAY_DEMO", "1")
        first = client.post("/api/agent/bargain", json=self.BODY)
        assert first.status_code == 402
        invoice = machine_pay.decode_payment_needed(first.headers["payment-needed"])
        assert invoice["protocol"]["amount"] == "0.01"
        assert invoice["protocol"]["seller_signature"], "账单必须带签名（真钥或占位）"
        # 无私钥时演示模式落占位签名（评委机器零 .env 也能签账单）
        monkeypatch.delenv("ALIPAY_PRIVATE_KEY", raising=False)
        placeholder = machine_pay.build_invoice("MPDEMO0000000000PLACEHLD")
        assert placeholder["protocol"]["seller_signature"].startswith("DEMO-SIGNATURE-")
        monkeypatch.setenv("ALIPAY_PRIVATE_KEY", "")

        proof = self._demo_proof(invoice["protocol"]["out_trade_no"])
        second = client.post("/api/agent/bargain", json=self.BODY, headers={"Payment-Proof": proof})
        assert second.status_code == 200, second.text
        assert second.json()["decision"]["kind"] == "counter"

        replay = client.post("/api/agent/bargain", json=self.BODY, headers={"Payment-Proof": proof})
        assert replay.status_code == 402
        assert "PROOF_REUSED" in replay.text

    def test_demo_rejects_foreign_proof(self, client, monkeypatch):
        monkeypatch.setenv("MACHINE_PAY_DEMO", "1")
        proof = self._demo_proof("MP20260101000000AAAAAA", token="REAL-LOOKING")
        response = client.post("/api/agent/bargain", json=self.BODY, headers={"Payment-Proof": proof})
        assert response.status_code == 402
        assert "PROOF_INVALID" in response.text
