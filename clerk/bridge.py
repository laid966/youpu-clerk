"""桥接层：让本站成为卖家的唯一驾驶舱，闲鱼退化为"运输管"。

## 为什么存在
卖家的终极问题永远是："我为什么还要开着闲鱼页面？"
答案的现实约束：闲鱼不给个人开放 API；逆向协议代管 cookie 会封卖家的吃饭账号。
所以桥是**跑在卖家自己浏览器里的扩展**：它在卖家自己的登录会话中监听闲鱼页面，
把买家消息搬进本站（inbox）；卖家在本站点"发送"，命令进发件箱（outbox），
扩展回闲鱼页面执行发送并回执（ack）。本站 = 大脑 + 收件箱 + 发件箱 + 台账。

## 三条铁律（都有测试盯着）
1. 扩展只跑在卖家自己的浏览器、自己的会话里——**服务器永远不碰闲鱼凭据**
2. 每条发送都由卖家在本站亲手点击触发（outbox 命令 → 扩展执行 → ack 入账）——
   不存在后台自动发送；ack 成功后才把对应决策记为"已发送"（台账闭环）
3. 桥断了（闲鱼页没开/扩展离线）产品降级为粘贴模式，**功能不残废**——
   命令 10 分钟无人执行自动过期，不会堆积成"幽灵发送"

## 数据流

    闲鱼页面 ──扩展监听──► POST /api/bridge/inbox ──► bridge_conversations/bridge_messages
        │                                                │（卖家关联商品后）
        │                                                ▼
        │                                     普通 conversations（复用建议/台账/额度全管线）
        │                                                │
        └──扩展执行发送◄── GET /api/bridge/outbox ◄── POST /api/bridge/send（卖家点击）
                 │
                 └──► POST /api/bridge/ack ──► 决策记为已发送（台账闭环）
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from clerk import db, service

__all__ = [
    "COMMAND_TTL_MINUTES",
    "ack_command",
    "enqueue_send",
    "get_bridge_conversation",
    "inbox",
    "link_item",
    "list_bridge_conversations",
    "pending_commands",
]

#: 发件箱命令的寿命：扩展离线时命令不会永远挂着等一个不会来的执行
COMMAND_TTL_MINUTES = 10


class BridgeError(ValueError):
    """桥接层错误（会话不存在/未关联商品/命令状态非法）。"""


def _touch(conn: sqlite3.Connection, bridge_conv_id: str) -> None:
    conn.execute(
        "UPDATE bridge_conversations SET updated_at = ? WHERE id = ?",
        (db.now_iso(), bridge_conv_id),
    )


def inbox(
    conn: sqlite3.Connection,
    *,
    token: str,
    platform: str,
    conv_key: str,
    message: str,
    buyer_alias: str = "买家",
    language: str | None = None,
) -> dict:
    """扩展搬来一条买家消息。已关联商品的会话会同步进普通会话线程（不分裂）。"""
    if not message or not message.strip():
        raise BridgeError("消息不能为空")
    db.ensure_user(conn, token)
    row = conn.execute(
        "SELECT * FROM bridge_conversations WHERE token = ? AND platform = ? AND conv_key = ?",
        (token, platform, conv_key),
    ).fetchone()
    if row is None:
        bridge_conv_id = db.new_id()
        conn.execute(
            "INSERT INTO bridge_conversations(id, token, platform, conv_key, buyer_alias,"
            " language, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                bridge_conv_id, token, platform, conv_key, buyer_alias,
                language or "zh", db.now_iso(), db.now_iso(),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM bridge_conversations WHERE id = ?", (bridge_conv_id,)
        ).fetchone()
    bridge_conv_id = row["id"]

    message_id = db.new_id()
    conn.execute(
        "INSERT INTO bridge_messages(id, bridge_conv_id, direction, body, created_at)"
        " VALUES(?,?,?,?,?)",
        (message_id, bridge_conv_id, "buyer", message, db.now_iso()),
    )
    _touch(conn, bridge_conv_id)

    # 已关联商品：同步进普通会话，让建议/台账管线看到完整线程
    if row["linked_conversation_id"]:
        db.add_message(conn, row["linked_conversation_id"], "buyer", message, language)
    conn.commit()
    return {"bridge_conv_id": bridge_conv_id, "message_id": message_id}


def get_bridge_conversation(conn: sqlite3.Connection, token: str, bridge_conv_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM bridge_conversations WHERE id = ? AND token = ?",
        (bridge_conv_id, token),
    ).fetchone()
    return dict(row) if row else None


def list_bridge_conversations(conn: sqlite3.Connection, token: str) -> list[dict]:
    rows = conn.execute(
        "SELECT b.*,"
        " (SELECT m.body FROM bridge_messages m WHERE m.bridge_conv_id = b.id AND m.direction = 'buyer'"
        "  ORDER BY m.rowid DESC LIMIT 1) AS last_message,"
        " (SELECT COUNT(*) FROM bridge_commands c WHERE c.bridge_conv_id = b.id AND c.status = 'pending') AS pending_sends"
        " FROM bridge_conversations b WHERE b.token = ? ORDER BY b.updated_at DESC, b.rowid DESC",
        (token,),
    ).fetchall()
    return [dict(r) for r in rows]


def bridge_messages(conn: sqlite3.Connection, bridge_conv_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM bridge_messages WHERE bridge_conv_id = ? ORDER BY rowid", (bridge_conv_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def link_item(conn: sqlite3.Connection, *, token: str, bridge_conv_id: str, item_id: str) -> dict:
    """把桥接会话关联到商品档案：创建普通会话并把已有买家消息按序播种进去。

    幂等：已关联则直接返回现有普通会话（扩展重发/卖家重点不会造出重复线程）。
    """
    bridge = get_bridge_conversation(conn, token, bridge_conv_id)
    if bridge is None:
        raise BridgeError(f"桥接会话不存在：{bridge_conv_id}")
    if bridge["linked_conversation_id"]:
        return {"conversation_id": bridge["linked_conversation_id"], "already": True}
    if db.get_item(conn, token, item_id) is None:
        raise BridgeError(f"商品档案不存在或不属于你：{item_id}")

    conversation = db.get_or_create_conversation(
        conn, token, item_id, conversation_id=None, buyer_alias=bridge["buyer_alias"]
    )
    for message in bridge_messages(conn, bridge_conv_id):
        if message["direction"] == "buyer":
            db.add_message(conn, conversation["id"], "buyer", message["body"], bridge["language"])
    conn.execute(
        "UPDATE bridge_conversations SET linked_conversation_id = ?, updated_at = ? WHERE id = ?",
        (conversation["id"], db.now_iso(), bridge_conv_id),
    )
    conn.commit()
    return {"conversation_id": conversation["id"], "already": False}


def enqueue_send(
    conn: sqlite3.Connection,
    *,
    token: str,
    bridge_conv_id: str,
    body: str,
    decision_id: str | None = None,
) -> dict:
    """卖家在本站点"发送到闲鱼"：命令进发件箱，等扩展来取。"""
    bridge = get_bridge_conversation(conn, token, bridge_conv_id)
    if bridge is None:
        raise BridgeError(f"桥接会话不存在：{bridge_conv_id}")
    if not bridge["linked_conversation_id"]:
        raise BridgeError("先关联商品档案，再发送——发送内容要进台账，台账要挂在会话上")
    if not body or not body.strip():
        raise BridgeError("发送内容不能为空")
    command_id = db.new_id()
    conn.execute(
        "INSERT INTO bridge_commands(id, bridge_conv_id, body, decision_id, status, created_at)"
        " VALUES(?,?,?,?, 'pending', ?)",
        (command_id, bridge_conv_id, body, decision_id, db.now_iso()),
    )
    conn.commit()
    return {"command_id": command_id, "status": "pending"}


def pending_commands(conn: sqlite3.Connection, token: str) -> list[dict]:
    """扩展轮询的发件箱。顺带把超时的 pending 懒标记为 expired——不堆积幽灵命令。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=COMMAND_TTL_MINUTES)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn.execute(
        "UPDATE bridge_commands SET status = 'expired' WHERE status = 'pending' AND created_at < ?",
        (cutoff,),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT c.* FROM bridge_commands c JOIN bridge_conversations b ON b.id = c.bridge_conv_id"
        " WHERE b.token = ? AND c.status = 'pending' ORDER BY c.rowid",
        (token,),
    ).fetchall()
    return [dict(r) for r in rows]


def ack_command(conn: sqlite3.Connection, *, token: str, command_id: str, status: str) -> dict:
    """扩展执行回执。acked 且带 decision_id → 把决策记为已发送（台账闭环，幂等）。"""
    if status not in ("acked", "failed"):
        raise BridgeError(f"非法回执状态：{status!r}（允许 acked|failed）")
    row = conn.execute(
        "SELECT c.*, b.token AS token FROM bridge_commands c"
        " JOIN bridge_conversations b ON b.id = c.bridge_conv_id WHERE c.id = ?",
        (command_id,),
    ).fetchone()
    if row is None or row["token"] != token:
        raise BridgeError(f"命令不存在：{command_id}")
    if row["status"] != "pending":
        # 重复回执（扩展重试/网络抖动）：幂等吞掉，不改已定状态
        return {"command_id": command_id, "status": row["status"], "already": True}

    conn.execute(
        "UPDATE bridge_commands SET status = ?, acked_at = ? WHERE id = ?",
        (status, db.now_iso(), command_id),
    )
    conn.commit()

    adopted = False
    if status == "acked" and row["decision_id"]:
        try:
            service.adopt(
                suggestion_id=row["decision_id"],
                action="sent",
                final_text=row["body"],
                token=token,
                conn=conn,
            )
            adopted = True
        except (db.DbError, service.ClerkError):
            # 决策已被人工采纳过/不存在：发送本身成功，台账保持第一次的记录（不可改写）
            adopted = False
    return {"command_id": command_id, "status": status, "already": False, "adopted": adopted}
