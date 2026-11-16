"""桥接层测试：inbox → link → suggest → send → outbox → ack 全闭环 + 三条铁律。

铁律的测试形态：
1. 凭据隔离——桥接端点全部 token 作用域，跨 token 不可见（有测试）
2. 无后台自动发送——send 只入发件箱，**ack 之后**决策才记为已发送（有测试）
3. 桥断不残废——命令 10 分钟过期不堆积；未关联商品时 send 明确报错而非静默丢弃（有测试）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import clerk.db as db
from clerk.server import app

HEADERS = {"X-Clerk-User": "tok-bridge"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
    app.state.judge = None
    with TestClient(app) as test_client:
        test_client.headers.update(HEADERS)
        yield test_client
    app.state.judge = None


def _item(client) -> str:
    body = client.post("/api/items", json={"title": "机械键盘", "asking_price": "399"}).json()
    return body["item"]["id"]


def _inbox(client, message="300行不行", conv_key="xianyu-conv-1", **kwargs) -> str:
    body = client.post(
        "/api/bridge/inbox",
        json={"platform": "xianyu", "conv_key": conv_key, "message": message, **kwargs},
    ).json()
    return body["bridge_conv_id"]


class TestInbox:
    def test_inbox_creates_and_appends(self, client):
        first = _inbox(client, "在吗")
        second = _inbox(client, "300行不行", conv_key="xianyu-conv-1")
        assert first == second  # 同平台同 conv_key = 同一桥接会话
        detail = client.get(f"/api/bridge/conversations/{first}").json()
        bodies = [m["body"] for m in detail["messages"]]
        assert bodies == ["在吗", "300行不行"]

    def test_queue_shows_last_message_and_alias(self, client):
        _inbox(client, "300行不行", buyer_alias="砍价党老王")
        queue = client.get("/api/bridge/conversations").json()["conversations"]
        assert queue[0]["buyer_alias"] == "砍价党老王"
        assert queue[0]["last_message"] == "300行不行"
        assert queue[0]["linked_conversation_id"] is None

    def test_inbox_isolated_between_tokens(self, client):
        bridge_id = _inbox(client)
        other = client.get("/api/bridge/conversations", headers={"X-Clerk-User": "intruder"}).json()
        assert other["conversations"] == []
        detail = client.get(
            f"/api/bridge/conversations/{bridge_id}", headers={"X-Clerk-User": "intruder"}
        )
        assert detail.status_code == 400  # BridgeError：不存在（不泄露存在性细节给跨权者）


class TestLinkAndSuggest:
    def test_link_seeds_thread_and_suggest_reuses_message(self, client):
        item_id = _item(client)
        bridge_id = _inbox(client, "300行不行")
        linked = client.post(
            "/api/bridge/link", json={"bridge_conv_id": bridge_id, "item_id": item_id}
        ).json()
        conversation_id = linked["conversation_id"]

        # 播种：普通会话里已有那条买家消息，且只有一条（不重复）
        thread = client.get(f"/api/conversations/{conversation_id}").json()
        assert [m["body"] for m in thread["messages"]] == ["300行不行"]

        suggestion = client.post(
            "/api/bridge/suggest", json={"bridge_conv_id": bridge_id}
        ).json()
        assert suggestion["decision"]["kind"] == "counter"
        assert suggestion["decision"]["price"] == "379.05"
        assert suggestion["conversation_id"] == conversation_id

        # 建议不重复插买家消息：线程仍然只有一条 buyer
        thread = client.get(f"/api/conversations/{conversation_id}").json()
        buyers = [m for m in thread["messages"] if m["direction"] == "buyer"]
        assert len(buyers) == 1

    def test_link_is_idempotent(self, client):
        item_id = _item(client)
        bridge_id = _inbox(client)
        first = client.post("/api/bridge/link", json={"bridge_conv_id": bridge_id, "item_id": item_id}).json()
        second = client.post("/api/bridge/link", json={"bridge_conv_id": bridge_id, "item_id": item_id}).json()
        assert first["conversation_id"] == second["conversation_id"]
        assert second["already"] is True

    def test_suggest_before_link_rejected(self, client):
        bridge_id = _inbox(client)
        response = client.post("/api/bridge/suggest", json={"bridge_conv_id": bridge_id})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BRIDGE_ERROR"

    def test_inbox_after_link_flows_into_thread(self, client):
        """关联后再来的消息必须同步进普通会话——线程不分裂是桥接的命。"""
        item_id = _item(client)
        bridge_id = _inbox(client, "300行不行")
        linked = client.post("/api/bridge/link", json={"bridge_conv_id": bridge_id, "item_id": item_id}).json()
        _inbox(client, "320吧朋友", conv_key="xianyu-conv-1")
        thread = client.get(f"/api/conversations/{linked['conversation_id']}").json()
        assert [m["body"] for m in thread["messages"]] == ["300行不行", "320吧朋友"]


class TestSendOutboxAck:
    def _prepared(self, client):
        item_id = _item(client)
        bridge_id = _inbox(client)
        client.post("/api/bridge/link", json={"bridge_conv_id": bridge_id, "item_id": item_id})
        suggestion = client.post("/api/bridge/suggest", json={"bridge_conv_id": bridge_id}).json()
        return bridge_id, suggestion

    def test_send_requires_link(self, client):
        _item(client)
        bridge_id = _inbox(client, conv_key="unlinked")
        response = client.post("/api/bridge/send", json={"bridge_conv_id": bridge_id, "body": "hi"})
        assert response.status_code == 400

    def test_full_loop_ack_closes_ledger(self, client):
        bridge_id, suggestion = self._prepared(client)
        sent = client.post(
            "/api/bridge/send",
            json={
                "bridge_conv_id": bridge_id,
                "body": suggestion["reply_text"],
                "decision_id": suggestion["suggestion_id"],
            },
        ).json()
        assert sent["status"] == "pending"

        # 发件箱：扩展能看到且只看到自己的
        outbox = client.get("/api/bridge/outbox").json()["commands"]
        assert len(outbox) == 1 and outbox[0]["id"] == sent["command_id"]
        assert client.get("/api/bridge/outbox", headers={"X-Clerk-User": "intruder"}).json()["commands"] == []

        # ack 之前：决策**不**记为已发送（铁律 2：没有后台自动发送，也就没有未确认的台账）
        thread = client.get(f"/api/conversations/{suggestion['conversation_id']}").json()
        assert thread["decisions"][0]["adopted"] is None

        ack = client.post("/api/bridge/ack", json={"command_id": sent["command_id"], "status": "acked"}).json()
        assert ack["adopted"] is True

        thread = client.get(f"/api/conversations/{suggestion['conversation_id']}").json()
        assert thread["decisions"][0]["adopted"] == "sent"
        sellers = [m for m in thread["messages"] if m["direction"] == "seller"]
        assert len(sellers) == 1 and sellers[0]["body"] == suggestion["reply_text"]

        # 发件箱清空
        assert client.get("/api/bridge/outbox").json()["commands"] == []

    def test_double_ack_is_idempotent(self, client):
        bridge_id, suggestion = self._prepared(client)
        command_id = client.post(
            "/api/bridge/send",
            json={"bridge_conv_id": bridge_id, "body": suggestion["reply_text"], "decision_id": suggestion["suggestion_id"]},
        ).json()["command_id"]
        first = client.post("/api/bridge/ack", json={"command_id": command_id, "status": "acked"}).json()
        second = client.post("/api/bridge/ack", json={"command_id": command_id, "status": "acked"}).json()
        assert first["already"] is False and second["already"] is True
        thread = client.get(f"/api/conversations/{suggestion['conversation_id']}").json()
        sellers = [m for m in thread["messages"] if m["direction"] == "seller"]
        assert len(sellers) == 1  # 台账不因重复回执写两笔

    def test_failed_ack_does_not_adopt(self, client):
        bridge_id, suggestion = self._prepared(client)
        command_id = client.post(
            "/api/bridge/send",
            json={"bridge_conv_id": bridge_id, "body": suggestion["reply_text"], "decision_id": suggestion["suggestion_id"]},
        ).json()["command_id"]
        ack = client.post("/api/bridge/ack", json={"command_id": command_id, "status": "failed"}).json()
        assert ack["adopted"] is False
        thread = client.get(f"/api/conversations/{suggestion['conversation_id']}").json()
        assert thread["decisions"][0]["adopted"] is None

    def test_stale_commands_expire(self, client):
        """桥断了（扩展离线）：命令 10 分钟过期，不堆积幽灵发送（铁律 3）。"""
        bridge_id, suggestion = self._prepared(client)
        command_id = client.post(
            "/api/bridge/send", json={"bridge_conv_id": bridge_id, "body": suggestion["reply_text"]}
        ).json()["command_id"]
        conn = db.open_db()
        try:
            conn.execute(
                "UPDATE bridge_commands SET created_at = '2020-01-01T00:00:00Z' WHERE id = ?", (command_id,)
            )
            conn.commit()
        finally:
            conn.close()
        assert client.get("/api/bridge/outbox").json()["commands"] == []
