"""clerk.db 的测试：schema、金额纪律、台账不可改写、I1 口径。"""

from __future__ import annotations

import pytest

import clerk.db as db


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
    connection = db.open_db()
    yield connection
    connection.close()


def _seed(conn):
    db.ensure_user(conn, "tok")
    item = db.create_item(conn, "tok", "机械键盘", "399.00", "339.15")
    conv = db.get_or_create_conversation(conn, "tok", item["id"])
    return item, conv


def _add_decision(conn, conv, item, kind, adopted=None, price=None):
    message_id = db.add_message(conn, conv["id"], "buyer", "test")
    decision_id = db.add_decision(
        conn,
        conversation_id=conv["id"],
        item_id=item["id"],
        message_id=message_id,
        kind=kind,
        price=price,
        rule_id=None,
        citations=(),
        reasons=(),
        requires_human_review=False,
        judgement=None,
        classification={"kind": "bargain", "language": "zh", "offer": None},
        reply_text="r",
        guardrail_hits=[],
    )
    if adopted:
        db.adopt_decision(
            conn,
            decision_id,
            adopted,
            final_text="改后的话术" if adopted == "edited" else None,
        )
    return decision_id


class TestSchemaAndMoney:
    def test_open_db_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLERK_DB", str(tmp_path / "clerk.db"))
        first = db.open_db()
        first.close()
        second = db.open_db()  # 不应抛错
        second.close()

    def test_money_must_be_two_decimal_string(self, conn):
        with pytest.raises(db.DbError, match="两位小数"):
            db.create_item(conn, "tok", "键盘", "9.9", "8.00")

    def test_floor_above_asking_rejected(self, conn):
        with pytest.raises(db.DbError, match="底价"):
            db.create_item(conn, "tok", "键盘", "100.00", "120.00")

    def test_empty_title_rejected(self, conn):
        with pytest.raises(db.DbError):
            db.create_item(conn, "tok", "  ", "100.00", "80.00")

    def test_add_message_rejects_bad_direction(self, conn):
        item, conv = _seed(conn)
        with pytest.raises(db.DbError):
            db.add_message(conn, conv["id"], "robot", "hi")


class TestUsersAndUsage:
    def test_ensure_user_idempotent(self, conn):
        first = db.ensure_user(conn, "tok")
        second = db.ensure_user(conn, "tok")
        assert first["token"] == second["token"]
        rows = conn.execute("SELECT COUNT(*) AS n FROM users WHERE token='tok'").fetchone()
        assert rows["n"] == 1

    def test_usage_bump(self, conn):
        db.ensure_user(conn, "tok")
        day = db.today_shanghai()
        assert db.get_usage(conn, "tok", day) == 0
        assert db.bump_usage(conn, "tok", day) == 1
        assert db.bump_usage(conn, "tok", day) == 2


class TestItems:
    def test_update_item_floor_validation(self, conn):
        item, _ = _seed(conn)
        with pytest.raises(db.DbError, match="底价"):
            db.update_item(conn, "tok", item["id"], floor_price="500.00")

    def test_update_item_whitelist(self, conn):
        item, _ = _seed(conn)
        with pytest.raises(db.DbError):
            db.update_item(conn, "tok", item["id"], platform="ebay")

    def test_update_item_floor_slider(self, conn):
        item, _ = _seed(conn)
        updated = db.update_item(conn, "tok", item["id"], floor_price="300.00")
        assert updated["floor_price"] == "300.00"


class TestLedgerInvariants:
    def test_i1_counts_only_adopted_counters(self, conn):
        item, conv = _seed(conn)
        _add_decision(conn, conv, item, "counter", adopted="sent", price="379.05")
        _add_decision(conn, conv, item, "counter", adopted="discarded", price="379.05")
        _add_decision(conn, conv, item, "counter", adopted="edited", price="379.05")
        _add_decision(conn, conv, item, "accept", adopted="sent")
        _add_decision(conn, conv, item, "human", adopted="escalated")
        _add_decision(conn, conv, item, "counter", adopted=None, price="379.05")
        assert db.count_adopted_counters(conn, conv["id"], item["id"]) == 2

    def test_adoption_is_one_way(self, conn):
        """台账不许改写：已采纳的决策再改 = DbError（同 freeze_audit 哲学）。"""
        item, conv = _seed(conn)
        decision_id = _add_decision(conn, conv, item, "counter", adopted="sent", price="379.05")
        with pytest.raises(db.DbError, match="不能重复改判"):
            db.adopt_decision(conn, decision_id, "discarded")

    def test_edited_requires_final_text(self, conn):
        item, conv = _seed(conn)
        message_id = db.add_message(conn, conv["id"], "buyer", "300行不行")
        decision_id = db.add_decision(
            conn,
            conversation_id=conv["id"],
            item_id=item["id"],
            message_id=message_id,
            kind="counter",
            price="379.05",
            rule_id=None,
            citations=(),
            reasons=(),
            requires_human_review=False,
            judgement=None,
            classification={},
            reply_text="r",
            guardrail_hits=[],
        )
        with pytest.raises(db.DbError, match="final_text"):
            db.adopt_decision(conn, decision_id, "edited", None)

    def test_ledger_by_day(self, conn):
        item, conv = _seed(conn)
        _add_decision(conn, conv, item, "counter", adopted="sent", price="379.05")
        rows = db.ledger_by_day(conn, "tok", db.today_shanghai())
        assert len(rows) == 1
        assert rows[0]["kind"] == "counter"

    def test_get_decision_carries_token(self, conn):
        item, conv = _seed(conn)
        decision_id = _add_decision(conn, conv, item, "counter", price="379.05")
        row = db.get_decision(conn, decision_id)
        assert row["token"] == "tok"


class TestConversations:
    def test_conversation_isolated_by_item(self, conn):
        item, conv = _seed(conn)
        other = db.create_item(conn, "tok", "鼠标", "99.00", "80.00")
        with pytest.raises(db.DbError, match="不匹配"):
            db.get_or_create_conversation(conn, "tok", other["id"], conv["id"])

    def test_language_update(self, conn):
        item, conv = _seed(conn)
        db.set_conversation_language(conn, conv["id"], "en")
        assert db.get_conversation(conn, conv["id"])["language"] == "en"

    def test_last_human_signal_surfaces_in_list(self, conn):
        """卖家优先级信号：最后一条决策是 human 的会话，列表里要亮红灯。"""
        item, conv = _seed(conn)
        rows = db.list_conversations(conn, "tok")
        assert rows[0]["last_human"] is None or rows[0]["last_human"] == 0
        _add_decision(conn, conv, item, "human", adopted="escalated")
        rows = db.list_conversations(conn, "tok")
        assert rows[0]["last_kind"] == "human"
        assert rows[0]["last_human"] == 1
        # 后续又有一条普通决策 → 信号回落（只看最后一条）
        _add_decision(conn, conv, item, "counter", adopted="sent", price="379.05")
        rows = db.list_conversations(conn, "tok")
        assert rows[0]["last_kind"] == "counter"
        assert not rows[0]["last_human"]
