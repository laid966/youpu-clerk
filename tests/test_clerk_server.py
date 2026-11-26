"""clerk.server 集成测试：HTTP 层契约（docs/32 §3/§6）。

用 TestClient 打真 HTTP 栈：错误码映射、402 额度墙、演示模式全剧本端到端、
静态托管。judge 一律 TemplateJudge（app.state.judge 覆盖位）——离线、确定性。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import clerk.db as db
from clerk import config, demo
from clerk.server import app
from clerk.templates import TemplateJudge

HEADERS = {"X-Clerk-User": "tok-web"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
    app.state.judge = TemplateJudge()
    with TestClient(app) as test_client:
        test_client.headers.update(HEADERS)
        yield test_client
    app.state.judge = None


def _create_item(client, title="机械键盘 87 键", asking="399.00", floor=None):
    payload = {"title": title, "asking_price": asking}
    if floor is not None:
        payload["floor_price"] = floor
    response = client.post("/api/items", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["item"]


class TestHealthAndStatic:
    def test_health(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["product"] == config.PRODUCT_NAME
        assert body["judge_mode"] == "template"
        assert body["languages"] == ["zh", "en"]

    def test_static_assets_served(self, client):
        index = client.get("/")
        assert index.status_code == 200
        assert "有谱掌柜" in index.text
        assert "app.js" in index.text
        for asset in ("/styles.css", "/app.js", "/api.js", "/mock.js", "/i18n/zh.js", "/i18n/en.js"):
            response = client.get(asset)
            assert response.status_code == 200, asset
            assert len(response.content) > 0, asset

    def test_no_heuristic_caching(self, client):
        """弗兰肯斯坦页面事故的回归测试：每个响应都必须带 no-cache 重验证头。"""
        for path in ("/", "/styles.css", "/app.js"):
            assert "no-cache" in client.get(path).headers["cache-control"], path


class TestItemsApi:
    def test_create_with_smart_default_floor(self, client):
        item = _create_item(client, asking="399")  # 宽松输入也要归一成两位小数
        assert item["asking_price"] == "399.00"
        assert item["floor_price"] == "339.15"  # 399 × 0.85，default_floor_price 口径

    def test_list_and_patch(self, client):
        item = _create_item(client)
        assert len(client.get("/api/items").json()["items"]) == 1
        patched = client.patch(
            f"/api/items/{item['id']}", json={"floor_price": "300.00"}
        ).json()["item"]
        assert patched["floor_price"] == "300.00"

    def test_patch_floor_above_asking_rejected(self, client):
        item = _create_item(client)
        response = client.patch(f"/api/items/{item['id']}", json={"floor_price": "999.00"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "DB_REJECTED"

    def test_missing_token_rejected(self, client):
        response = client.get("/api/items", headers={"X-Clerk-User": ""})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "USER_TOKEN_REQUIRED"


class TestInquiryFlow:
    def test_full_loop(self, client):
        item = _create_item(client)
        result = client.post(
            "/api/inquiry", json={"item_id": item["id"], "message": "300行不行"}
        ).json()
        assert result["decision"]["kind"] == "counter"
        assert result["decision"]["price"] == "379.05"

        adopted = client.post(
            f"/api/inquiries/{result['suggestion_id']}/adopt", json={"action": "sent"}
        ).json()
        assert adopted["concessions_used"] == 1

        conversation = client.get(f"/api/conversations/{result['conversation_id']}").json()
        assert len(conversation["messages"]) == 2  # buyer + seller(I5)
        assert conversation["decisions"][0]["citations"]  # 台账里依据完整

        ledger = client.get("/api/ledger").json()
        assert len(ledger["entries"]) == 1

        report = client.get("/api/report/daily").json()
        assert report["counters"] == 1 and report["adopted"] == 1

    def test_item_not_found_404(self, client):
        response = client.post(
            "/api/inquiry", json={"item_id": "nonexistent", "message": "300行不行"}
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ITEM_NOT_FOUND"

    def test_conversation_isolated_between_users(self, client):
        item = _create_item(client)
        result = client.post(
            "/api/inquiry", json={"item_id": item["id"], "message": "300行不行"}
        ).json()
        response = client.get(
            f"/api/conversations/{result['conversation_id']}",
            headers={"X-Clerk-User": "someone-else"},
        )
        assert response.status_code == 404  # 越权报"不存在"，不泄露资源存在性


class TestQuotaWall:
    def test_402_with_pricing(self, client, monkeypatch):
        monkeypatch.setattr(config, "FREE_DAILY_SUGGESTIONS", 1)
        item = _create_item(client)
        first = client.post("/api/inquiry", json={"item_id": item["id"], "message": "300行不行"})
        assert first.status_code == 200
        second = client.post("/api/inquiry", json={"item_id": item["id"], "message": "290行不行"})
        assert second.status_code == 402
        body = second.json()["error"]
        assert body["code"] == "QUOTA_EXCEEDED"
        assert body["pricing"]["price_30d"] == "9.90"  # 金额纪律：两位小数，处处一致

    def test_entitlements_report_quota(self, client):
        item = _create_item(client)
        client.post("/api/inquiry", json={"item_id": item["id"], "message": "300行不行"})
        body = client.get("/api/entitlements/me").json()
        assert body["plan"] == "free"
        assert body["quota"]["used_today"] == 1


class TestCopyEndpoint:
    def test_copy_returns_draft(self, client):
        body = client.post("/api/copy", json={"title": "机械键盘 87 键", "hints": "九成新"}).json()
        assert body["source"] == "template"  # client fixture 注入 TemplateJudge
        assert "机械键盘 87 键" in body["text"]
        assert "九成新" in body["text"]

    def test_copy_requires_title(self, client):
        response = client.post("/api/copy", json={"title": "  "})
        assert response.status_code == 400


class TestPayFlow:
    @pytest.fixture(autouse=True)
    def force_fake_adapter(self, monkeypatch):
        """支付流测试必须与宿主 .env 无关：清掉真凭证，强制 FakeAdapter（诚实未接通路径）。

        2026-11-26 事故：作者 .env 填入真凭证后适配器自动切 Vibe，
        本类"诚实未接通"断言反被真配置打红——测试的确定性高于环境的便利性。
        """
        for key in ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY", "ALIPAY_NOTIFY_URL"):
            monkeypatch.delenv(key, raising=False)
    def test_products_lists_tiers(self, client):
        body = client.get("/api/pay/products").json()
        codes = {tier["code"] for tier in body["tiers"]}
        assert codes == {"pass30", "pass30_early"}
        for tier in body["tiers"]:
            assert db.MONEY_RE.match(tier["price"]), tier  # 金额纪律延伸到定价 API

    def test_order_created_with_honest_payment_info(self, client):
        body = client.post("/api/pay/order", json={"product_code": "pass30_early"}).json()
        assert body["order"]["status"] == "created"
        assert body["order"]["amount"] == "6.90"
        assert body["payment"]["channel"] == "fake"  # 不假装接了真实渠道

    def test_unknown_product_rejected(self, client):
        response = client.post("/api/pay/order", json={"product_code": "gold"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "PAY_REJECTED"

    def test_dev_notify_closed_by_default(self, client):
        """生产安全线：CLERK_PAY_DEV 未设置时，未签名回调入口必须 403。"""
        response = client.post(
            "/api/pay/notify-dev", json={"out_trade_no": "YPWHATEVER", "amount": "6.90"}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "DEV_NOTIFY_DISABLED"

    def test_orders_list_is_own_only(self, client):
        """订单流水：只看自己的（G3 取证与对账入口）。"""
        client.post("/api/pay/order", json={"product_code": "pass30_early"})
        mine = client.get("/api/orders").json()["orders"]
        assert len(mine) == 1
        assert mine[0]["status"] == "created"
        assert mine[0]["amount"] == "6.90"
        assert "notify_json" not in mine[0]  # 展示字段白名单，不泄露通知原文
        theirs = client.get("/api/orders", headers={"X-Clerk-User": "someone-else"}).json()
        assert theirs["orders"] == []

    def test_full_payment_loop_in_dev_mode(self, client, monkeypatch):
        monkeypatch.setenv("CLERK_PAY_DEV", "1")
        order = client.post("/api/pay/order", json={"product_code": "pass30_early"}).json()["order"]

        paid = client.post(
            "/api/pay/notify-dev",
            json={"out_trade_no": order["out_trade_no"], "amount": order["amount"]},
        )
        assert paid.status_code == 200
        assert paid.json()["already"] is False

        replayed = client.post(
            "/api/pay/notify-dev",
            json={"out_trade_no": order["out_trade_no"], "amount": order["amount"]},
        )
        assert replayed.json()["already"] is True  # HTTP 层重放同样幂等

        entitlements = client.get("/api/entitlements/me").json()
        assert entitlements["plan"] == "paid30"
        assert entitlements["active"] is True

        # 付费后额度墙放行（FREE=0 也拦不住）
        monkeypatch.setattr(config, "FREE_DAILY_SUGGESTIONS", 0)
        item = _create_item(client)
        inquiry = client.post("/api/inquiry", json={"item_id": item["id"], "message": "300行不行"})
        assert inquiry.status_code == 200
        assert inquiry.json()["decision"]["kind"] == "counter"


class TestDemoEndpoints:
    def test_bootstrap_shape(self, client):
        body = client.get("/api/demo/bootstrap").json()
        assert len(body["shop"]["items"]) == 3
        assert len(body["personas"]) == 5

    def test_wang_full_script_end_to_end(self, client):
        """评委路径的代码形态：连点 6 次「下一步」，决策序列与剧本 expected 完全一致。"""
        expected_kinds = ["human", "counter", "counter", "counter", "firm", "accept"]
        conversation_id = None
        for index in range(6):
            response = client.post(
                "/api/demo/step",
                json={"persona_id": "wang", "conversation_id": conversation_id},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            conversation_id = body["conversation_id"]
            assert body["step_index"] == index
            assert body["decision"]["kind"] == expected_kinds[index]
            assert body["decision"]["kind"] == body["expected"]["kind"]
            if body["expected"]["kind"] == "counter":
                assert body["decision"]["price"] == body["expected"]["price"]
            assert body["persona_message"]
        assert body["finished"] is True
        # 剧本走完再点 → 明确的 400，不是崩溃或静默重复
        over = client.post(
            "/api/demo/step", json={"persona_id": "wang", "conversation_id": conversation_id}
        )
        assert over.status_code == 400
        assert over.json()["error"]["code"] == "DEMO_ERROR"

    def test_emma_english_flow(self, client):
        first = client.post("/api/demo/step", json={"persona_id": "emma"}).json()
        assert first["classification"]["language"] == "en"
        second = client.post(
            "/api/demo/step",
            json={"persona_id": "emma", "conversation_id": first["conversation_id"]},
        ).json()
        assert second["decision"]["kind"] == "counter"
        assert second["decision"]["price"] == "379.05"
        # 回复语言跟买家走：英文买家拿到英文话术（不含中文字符即算通过；
        # 不用 isascii 是因为英文模板里有排版用的 em-dash）
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in second["reply_text"])

    def test_demo_is_deterministic_across_replays(self, tmp_path, monkeypatch):
        """同一剧本重放两次（各自全新库），决策逐字节一致——演示可复现性。"""
        runs = []
        for name in ("a", "b"):
            monkeypatch.setenv("CLERK_DB", str(tmp_path / f"clerk-{name}.db"))
            with TestClient(app) as replay_client:
                decisions = []
                conversation_id = None
                for _ in range(6):
                    body = replay_client.post(
                        "/api/demo/step",
                        json={"persona_id": "wang", "conversation_id": conversation_id},
                    ).json()
                    conversation_id = body["conversation_id"]
                    decisions.append(body["decision"])
                runs.append(decisions)
        assert runs[0] == runs[1]

    def test_demo_state_survives_page_refresh(self, client):
        """进度在服务端（从台账推导）：不带 conversation_id 重开 = 新剧本，
        带上 = 接着走。模拟"刷新页面后继续"。"""
        first = client.post("/api/demo/step", json={"persona_id": "li"}).json()
        assert first["step_index"] == 0
        resumed = client.post(
            "/api/demo/step", json={"persona_id": "li", "conversation_id": first["conversation_id"]}
        ).json()
        assert resumed["step_index"] == 1
