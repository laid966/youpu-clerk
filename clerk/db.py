"""SQLite 持久化：商品、会话、消息、台账（decisions）、额度、订单骨架。

## 为什么存在
台账是"每次让步都有据可查"的本体：每个决策、依据、是否被采纳，都必须活过进程重启、
可事后追查——这是聊天机器人给不了的（聊天记录不是审计日志，本仓库 README 的老规矩）。

## 三条纪律
1. **金额列一律 TEXT 两位小数字符串**（"95.00"），写入前用正则校验。
   float 永远不许进数据库——钱经过 float 就是事故的开始（契约 §0）。
2. **每个操作自己开/关连接**：FastAPI 多线程共享 sqlite 连接是经典事故；
   单机产品连接开销可忽略。测试用 CLERK_DB 环境变量指向临时文件。
3. **大声失败**：违反约束直接抛 DbError，绝不静默修数据。

## 一个刻意的不可变性
`adopt_decision` 只允许把 NULL 改成采纳动作，**已采纳的决策不许二次改判**——
台账要是能改写，"有据可查"就成了笑话（同 freeze_audit 的哲学）。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

__all__ = [
    "ADOPT_ACTIONS",
    "DbError",
    "add_decision",
    "add_message",
    "adopt_decision",
    "assert_money",
    "connect",
    "count_adopted_counters",
    "create_item",
    "db_path",
    "ensure_user",
    "get_conversation",
    "get_conversation_decisions",
    "get_conversation_messages",
    "get_decision",
    "get_item",
    "get_or_create_conversation",
    "get_usage",
    "bump_usage",
    "init_schema",
    "ledger_by_day",
    "list_conversations",
    "list_items",
    "new_id",
    "now_iso",
    "open_db",
    "record_machine_fulfillment",
    "get_machine_fulfillment",
    "set_conversation_language",
    "today_shanghai",
    "update_item",
]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "clerk.db"

MONEY_RE = re.compile(r"^\d+\.\d{2}$")
TZ_SHANGHAI = timezone(timedelta(hours=8))

ADOPT_ACTIONS = frozenset({"sent", "edited", "discarded", "escalated"})

_ITEM_UPDATABLE = frozenset({"title", "asking_price", "floor_price", "status"})
_ITEM_STATUSES = frozenset({"active", "sold", "archived"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  token TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'free',
  plan_expires_at TEXT);

CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  title TEXT NOT NULL,
  asking_price TEXT NOT NULL,
  floor_price TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'xianyu',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  item_id TEXT NOT NULL,
  buyer_alias TEXT NOT NULL DEFAULT '买家',
  language TEXT NOT NULL DEFAULT 'zh',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  direction TEXT NOT NULL,
  body TEXT NOT NULL,
  language TEXT,
  created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS decisions(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  price TEXT,
  rule_id TEXT,
  citations_json TEXT NOT NULL DEFAULT '[]',
  reasons_json TEXT NOT NULL DEFAULT '[]',
  requires_human_review INTEGER NOT NULL DEFAULT 0,
  judgement_json TEXT,
  classification_json TEXT NOT NULL,
  reply_text TEXT NOT NULL,
  guardrail_json TEXT NOT NULL DEFAULT '[]',
  adopted TEXT,
  final_text TEXT,
  day TEXT NOT NULL,
  created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS usage_daily(
  token TEXT NOT NULL,
  day TEXT NOT NULL,
  suggestions_used INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(token, day));

CREATE TABLE IF NOT EXISTS orders(
  id TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  out_trade_no TEXT NOT NULL UNIQUE,
  product_code TEXT NOT NULL,
  amount TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  paid_at TEXT,
  notify_json TEXT);

CREATE TABLE IF NOT EXISTS machine_fulfillments(
  trade_no TEXT PRIMARY KEY,
  out_trade_no TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  amount TEXT NOT NULL,
  created_at TEXT NOT NULL);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_decisions_conv ON decisions(conversation_id, item_id);
CREATE INDEX IF NOT EXISTS idx_decisions_day ON decisions(day);
CREATE INDEX IF NOT EXISTS idx_items_token ON items(token);
CREATE INDEX IF NOT EXISTS idx_conv_token ON conversations(token);
"""


class DbError(ValueError):
    """数据层约束被违反（金额格式、行不存在、非法枚举、重复采纳）。立刻炸，不静默。"""


# --------------------------------------------------------------------------- #
# 连接与基础工具
# --------------------------------------------------------------------------- #


def db_path() -> Path:
    return Path(os.getenv("CLERK_DB") or DEFAULT_DB_PATH)


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    # 顺序有讲究：**busy_timeout 必须先设**。journal_mode 切 WAL 本身需要拿锁，
    # 若此时 busy_timeout 还是默认的 0，并发首连会当场 "database is locked"
    # （这个顺序 bug 被并发写回归测试抓了个正着）。
    # WAL 让读写并发；busy_timeout 把写写竞争变成最多等 5 秒而不是立刻报错。
    # （journal_mode 是库级持久设置，切过一次后后续连接只是确认，不再需要排他锁。）
    conn.execute("PRAGMA busy_timeout=5000")
    # 切 WAL 需要排他锁，而**这次锁获取不走 busy_timeout 等待**（Windows 实测：
    # 多连接并发首开会互撞出 database is locked）。对策：退避重试；
    # WAL 是库级持久设置，切过一次后续连接只是确认；
    # 生产侧 server 启动时还会单连接预热（clerk/server.py lifespan），把切换留在流量之前。
    for attempt in range(5):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            break
        except sqlite3.OperationalError:
            time.sleep(0.05 * (attempt + 1))
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def open_db(path: str | Path | None = None) -> sqlite3.Connection:
    """connect + 建表。测试与服务启动的统一入口（幂等）。"""
    conn = connect(path)
    init_schema(conn)
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_shanghai() -> str:
    """额度与台账的日历日按上海时区数——卖家的"今天"不是 UTC 的今天。"""
    return datetime.now(TZ_SHANGHAI).date().isoformat()


def new_id() -> str:
    return uuid.uuid4().hex


def assert_money(value: Any, field: str) -> str:
    """金额必须是两位小数字符串。float 进库 = 事故，所以在门口就拦下。"""
    if not isinstance(value, str) or not MONEY_RE.match(value):
        raise DbError(f"{field} 必须是两位小数的金额字符串（如 '95.00'），实际是：{value!r}")
    return value


# --------------------------------------------------------------------------- #
# 用户与额度
# --------------------------------------------------------------------------- #


def ensure_user(conn: sqlite3.Connection, token: str) -> dict:
    if not token or not str(token).strip():
        raise DbError("token 不能为空")
    row = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users(token, created_at, plan) VALUES(?, ?, 'free')",
            (token, now_iso()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    return dict(row)


def get_usage(conn: sqlite3.Connection, token: str, day: str) -> int:
    row = conn.execute(
        "SELECT suggestions_used FROM usage_daily WHERE token = ? AND day = ?", (token, day)
    ).fetchone()
    return int(row["suggestions_used"]) if row else 0


def bump_usage(conn: sqlite3.Connection, token: str, day: str) -> int:
    conn.execute(
        "INSERT INTO usage_daily(token, day, suggestions_used) VALUES(?, ?, 1) "
        "ON CONFLICT(token, day) DO UPDATE SET suggestions_used = suggestions_used + 1",
        (token, day),
    )
    conn.commit()
    return get_usage(conn, token, day)


# --------------------------------------------------------------------------- #
# 商品档案
# --------------------------------------------------------------------------- #


def create_item(
    conn: sqlite3.Connection,
    token: str,
    title: str,
    asking_price: str,
    floor_price: str,
    platform: str = "xianyu",
) -> dict:
    if not title or not title.strip():
        raise DbError("商品标题不能为空")
    assert_money(asking_price, "asking_price")
    assert_money(floor_price, "floor_price")
    if Decimal(floor_price) > Decimal(asking_price):
        raise DbError(f"底价（{floor_price}）不能高于挂牌价（{asking_price}）")
    item_id = new_id()
    ts = now_iso()
    conn.execute(
        "INSERT INTO items(id, token, title, asking_price, floor_price, platform, status,"
        " created_at, updated_at) VALUES(?,?,?,?,?,?, 'active', ?, ?)",
        (item_id, token, title.strip(), asking_price, floor_price, platform, ts, ts),
    )
    conn.commit()
    item = get_item(conn, token, item_id)
    assert item is not None  # 刚插入的行必须能读回，读不回说明库坏了
    return item


def get_item(conn: sqlite3.Connection, token: str, item_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM items WHERE id = ? AND token = ?", (item_id, token)
    ).fetchone()
    return dict(row) if row else None


def list_items(conn: sqlite3.Connection, token: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM items WHERE token = ? ORDER BY created_at, rowid", (token,)
    ).fetchall()
    return [dict(r) for r in rows]


def update_item(conn: sqlite3.Connection, token: str, item_id: str, **fields: Any) -> dict:
    """白名单字段更新（前端底价滑杆走这里）。None 值视为"没传"。"""
    fields = {k: v for k, v in fields.items() if v is not None}
    unknown = set(fields) - _ITEM_UPDATABLE
    if unknown:
        raise DbError(f"不可更新的字段：{sorted(unknown)}")
    item = get_item(conn, token, item_id)
    if item is None:
        raise DbError(f"商品档案不存在：{item_id}")
    if not fields:
        return item

    merged = {**{k: item[k] for k in _ITEM_UPDATABLE}, **fields}
    assert_money(merged["asking_price"], "asking_price")
    assert_money(merged["floor_price"], "floor_price")
    if merged["status"] not in _ITEM_STATUSES:
        raise DbError(f"非法商品状态：{merged['status']!r}")
    if not str(merged["title"]).strip():
        raise DbError("商品标题不能为空")
    if Decimal(merged["floor_price"]) > Decimal(merged["asking_price"]):
        raise DbError(
            f"底价（{merged['floor_price']}）不能高于挂牌价（{merged['asking_price']}）"
        )

    conn.execute(
        "UPDATE items SET title=?, asking_price=?, floor_price=?, status=?, updated_at=? "
        "WHERE id=? AND token=?",
        (
            str(merged["title"]).strip(),
            merged["asking_price"],
            merged["floor_price"],
            merged["status"],
            now_iso(),
            item_id,
            token,
        ),
    )
    conn.commit()
    updated = get_item(conn, token, item_id)
    assert updated is not None
    return updated


# --------------------------------------------------------------------------- #
# 会话与消息
# --------------------------------------------------------------------------- #


def get_or_create_conversation(
    conn: sqlite3.Connection,
    token: str,
    item_id: str,
    conversation_id: str | None = None,
    buyer_alias: str = "买家",
) -> dict:
    if conversation_id:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND token = ?",
            (conversation_id, token),
        ).fetchone()
        if row is None:
            raise DbError(f"会话不存在或无权访问：{conversation_id}")
        if row["item_id"] != item_id:
            raise DbError("会话与商品不匹配——一个会话只围绕一件商品")
        return dict(row)

    conv_id = new_id()
    ts = now_iso()
    conn.execute(
        "INSERT INTO conversations(id, token, item_id, buyer_alias, language, status,"
        " created_at, updated_at) VALUES(?,?,?,?,?, 'open', ?, ?)",
        (conv_id, token, item_id, buyer_alias, "zh", ts, ts),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    return dict(row)


def get_conversation(conn: sqlite3.Connection, conversation_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()
    return dict(row) if row else None


def list_conversations(conn: sqlite3.Connection, token: str) -> list[dict]:
    """会话列表，附带"最后一条决策"的信号位。

    last_human 是给卖家的优先级信号：哪条会话正等着**你**接手（越权/低价甩卖/售后升级）。
    用子查询而不是 JOIN 全量 decisions：会话数 × 决策数都可能上千，列表只该扫每会话一行。
    """
    rows = conn.execute(
        "SELECT c.*,"
        " (SELECT d.kind FROM decisions d WHERE d.conversation_id = c.id ORDER BY d.rowid DESC LIMIT 1) AS last_kind,"
        " (SELECT d.requires_human_review FROM decisions d WHERE d.conversation_id = c.id"
        "  ORDER BY d.rowid DESC LIMIT 1) AS last_human"
        " FROM conversations c WHERE c.token = ? ORDER BY c.updated_at DESC, c.rowid DESC",
        (token,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_conversation_language(conn: sqlite3.Connection, conversation_id: str, language: str) -> None:
    conn.execute(
        "UPDATE conversations SET language = ?, updated_at = ? WHERE id = ? AND language != ?",
        (language, now_iso(), conversation_id, language),
    )
    conn.commit()


def add_message(
    conn: sqlite3.Connection,
    conversation_id: str,
    direction: str,
    body: str,
    language: str | None = None,
) -> str:
    if direction not in ("buyer", "seller"):
        raise DbError(f"非法消息方向：{direction!r}（只许 buyer|seller）")
    if not body or not body.strip():
        raise DbError("消息正文不能为空")
    message_id = new_id()
    conn.execute(
        "INSERT INTO messages(id, conversation_id, direction, body, language, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (message_id, conversation_id, direction, body, language, now_iso()),
    )
    conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now_iso(), conversation_id),
    )
    conn.commit()
    return message_id


def get_conversation_messages(conn: sqlite3.Connection, conversation_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY rowid", (conversation_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# 台账（decisions）
# --------------------------------------------------------------------------- #


def add_decision(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    item_id: str,
    message_id: str,
    kind: str,
    price: str | None,
    rule_id: str | None,
    citations: Any,
    reasons: Any,
    requires_human_review: bool,
    judgement: dict | None,
    classification: dict,
    reply_text: str,
    guardrail_hits: list,
) -> str:
    """写入一条台账。judgement 是 engine Judgement.to_dict() 的全量——事后追问
    "当时为什么这么判"，答案必须在这里找得到。"""
    if price is not None:
        assert_money(price, "price")
    decision_id = new_id()
    conn.execute(
        "INSERT INTO decisions(id, conversation_id, item_id, message_id, kind, price, rule_id,"
        " citations_json, reasons_json, requires_human_review, judgement_json,"
        " classification_json, reply_text, guardrail_json, day, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            decision_id,
            conversation_id,
            item_id,
            message_id,
            kind,
            price,
            rule_id,
            json.dumps(list(citations), ensure_ascii=False),
            json.dumps(list(reasons), ensure_ascii=False),
            1 if requires_human_review else 0,
            json.dumps(judgement, ensure_ascii=False) if judgement is not None else None,
            json.dumps(classification, ensure_ascii=False),
            reply_text,
            json.dumps(list(guardrail_hits), ensure_ascii=False),
            today_shanghai(),
            now_iso(),
        ),
    )
    conn.commit()
    return decision_id


def get_decision(conn: sqlite3.Connection, decision_id: str) -> dict | None:
    """带出会话的 token（越权检查用）。"""
    row = conn.execute(
        "SELECT d.*, c.token AS token FROM decisions d"
        " JOIN conversations c ON c.id = d.conversation_id WHERE d.id = ?",
        (decision_id,),
    ).fetchone()
    return dict(row) if row else None


def adopt_decision(
    conn: sqlite3.Connection, decision_id: str, action: str, final_text: str | None = None
) -> None:
    """采纳动作只许写一次：NULL → action。已采纳再改 = DbError。

    台账不可改写是产品承诺（"有据可查"的前提），不是实现细节。
    """
    if action not in ADOPT_ACTIONS:
        raise DbError(f"非法采纳动作：{action!r}（允许：{'/'.join(sorted(ADOPT_ACTIONS))}）")
    if action == "edited" and not (final_text and final_text.strip()):
        raise DbError("action='edited' 必须提供 final_text——改成了什么必须留痕")
    cursor = conn.execute(
        "UPDATE decisions SET adopted = ?, final_text = ? WHERE id = ? AND adopted IS NULL",
        (action, final_text, decision_id),
    )
    if cursor.rowcount == 0:
        existing = conn.execute(
            "SELECT adopted FROM decisions WHERE id = ?", (decision_id,)
        ).fetchone()
        if existing is None:
            raise DbError(f"决策不存在：{decision_id}")
        raise DbError(f"决策已被采纳（{existing['adopted']}），不能重复改判——台账不许改写")
    conn.commit()


def count_adopted_counters(conn: sqlite3.Connection, conversation_id: str, item_id: str) -> int:
    """不变量 I1：让步次数 = 本会话本商品被真正发出去的 counter 数。

    discarded（没用）与 escalated（转人工）不算——没真还出去的价不是让步。
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM decisions WHERE conversation_id = ? AND item_id = ?"
        " AND kind = 'counter' AND adopted IN ('sent','edited')",
        (conversation_id, item_id),
    ).fetchone()
    return int(row["n"])


def get_conversation_decisions(conn: sqlite3.Connection, conversation_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM decisions WHERE conversation_id = ? ORDER BY rowid", (conversation_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def ledger_by_day(conn: sqlite3.Connection, token: str, day: str) -> list[dict]:
    rows = conn.execute(
        "SELECT d.* FROM decisions d JOIN conversations c ON c.id = d.conversation_id"
        " WHERE c.token = ? AND d.day = ? ORDER BY d.rowid",
        (token, day),
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Machine Pay（A2A）履约记录：同一 trade_no 只许履约一次
# --------------------------------------------------------------------------- #


def record_machine_fulfillment(
    conn: sqlite3.Connection, trade_no: str, out_trade_no: str, resource_id: str, amount: str
) -> bool:
    """登记一笔 A2A 履约。返回 False = 该 trade_no 已履约过（同一笔支付不许用两次）。"""
    assert_money(amount, "amount")
    cursor = conn.execute(
        "INSERT OR IGNORE INTO machine_fulfillments(trade_no, out_trade_no, resource_id, amount, created_at)"
        " VALUES(?,?,?,?,?)",
        (trade_no, out_trade_no, resource_id, amount, now_iso()),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_machine_fulfillment(conn: sqlite3.Connection, trade_no: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM machine_fulfillments WHERE trade_no = ?", (trade_no,)
    ).fetchone()
    return dict(row) if row else None


def list_orders(conn: sqlite3.Connection, token: str, limit: int = 100) -> list[dict]:
    """卖家自己的订单流水（透明度 + G3 取证 + 客服对账用）。只返回展示字段，不含 notify 原文。"""
    rows = conn.execute(
        "SELECT id, out_trade_no, product_code, amount, status, created_at, paid_at"
        " FROM orders WHERE token = ? ORDER BY rowid DESC LIMIT ?",
        (token, limit),
    ).fetchall()
    return [dict(r) for r in rows]
