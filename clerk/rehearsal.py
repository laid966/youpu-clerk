"""评委旅程排练：对着**真实运行中的服务器**走完整产品旅程，逐项断言。

与 pytest 的区别：pytest 打的是 TestClient（进程内）；本脚本打的是**部署产物**——
提交前/评审期每天早上跑一遍，确认"评委点开会发生什么"真的会发生。

用法：
    .venv\\Scripts\\python.exe -m clerk.rehearsal http://127.0.0.1:8100
    .venv\\Scripts\\python.exe -m clerk.rehearsal https://你的域名

旅程清单（对应 docs/34 视频脚本的镜头）：
  1 演示·老王全剧本 6 步（human→counter×3→firm→accept，价格逐字节）
  2 演示·Emma 英文链路（分类 language=en）
  3 卖家·新账户建商品（底价自动 85%）→ 粘贴询价 → 建议+依据 → 采纳 → 战报
  4 支付·下单（金额两位小数）→ dev 回调安全线状态（生产应 403）
  5 权益·entitlements 可读
任何一项失败退出码 1——可以直接当 CI/ cron 门禁。
"""

from __future__ import annotations

import sys
import uuid

import httpx

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'ok' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail and not ok else ""))


def main(base_url: str) -> int:
    # Windows 默认 GBK 控制台打不出 ¥/● 等字符——重配 UTF-8（本仓库老规矩的第 N 次教训）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — 重配失败不该挡住排练
            pass
    base = base_url.rstrip("/")
    client = httpx.Client(base_url=base, timeout=20.0, trust_env=False)
    print(f"排练目标：{base}\n")

    print("镜头 1 · 评委演示：老王全剧本")
    conversation_id = None
    expected = [
        ("human", None, "BARGAIN-HUMAN-LOWBALL"),
        ("counter", "379.05", "BARGAIN-COUNTER-T1"),
        ("counter", "367.08", "BARGAIN-COUNTER-T2"),
        ("counter", "359.10", "BARGAIN-COUNTER-T3"),
        ("firm", None, "BARGAIN-FIRM-EXHAUSTED"),
        ("accept", None, "BARGAIN-ACCEPT"),
    ]
    for index, (kind, price, rule) in enumerate(expected, start=1):
        body = client.post(
            "/api/demo/step", json={"persona_id": "wang", "conversation_id": conversation_id}
        ).json()
        conversation_id = body["conversation_id"]
        decision = body["decision"] or {}
        check(
            f"第{index}步 {kind}" + (f" ¥{price}" if price else ""),
            decision.get("kind") == kind
            and (price is None or decision.get("price") == price)
            and decision.get("rule_id") == rule
            and body["decision"] is not None
            and body["expected"]["kind"] == kind,  # 实际 == 剧本预期
        )
    check("战报聚合可算", body.get("concessions_used") == 3, str(body.get("concessions_used")))

    print("镜头 2 · 跨境：Emma 英文链路")
    emma = client.post("/api/demo/step", json={"persona_id": "emma"}).json()
    check("分类 language=en", emma["classification"]["language"] == "en")
    check("英文回复无中文字符", not any("\u4e00" <= ch <= "\u9fff" for ch in emma["reply_text"]))

    print("镜头 3 · 卖家旅程：新账户从 0 到台账")
    token = "rehearsal-" + uuid.uuid4().hex[:12]
    headers = {"X-Clerk-User": token}
    item = client.post(
        "/api/items", json={"title": "排练用键盘", "asking_price": "399"}, headers=headers
    ).json()["item"]
    check("底价自动 85% = 339.15", item["floor_price"] == "339.15", item["floor_price"])
    suggestion = client.post(
        "/api/inquiry", json={"item_id": item["id"], "message": "300行不行"}, headers=headers
    ).json()
    check(
        "还价 379.05 且带规则依据",
        suggestion["decision"]["price"] == "379.05" and len(suggestion["decision"]["citations"]) > 0,
    )
    check("工作过程四步齐全", [s["step"] for s in suggestion["trace"]] == ["classify", "decide", "draft", "guardrail"])
    adopted = client.post(
        f"/api/inquiries/{suggestion['suggestion_id']}/adopt", json={"action": "sent"}, headers=headers
    ).json()
    check("采纳入账 concessions=1", adopted["concessions_used"] == 1)
    report = client.get("/api/report/daily", headers=headers).json()
    check("战报 counters=1/adopted=1", report["counters"] == 1 and report["adopted"] == 1)
    ledger = client.get("/api/ledger", headers=headers).json()
    check("台账留痕 1 条", len(ledger["entries"]) == 1)

    print("镜头 4 · 商业闭环：下单与安全线")
    order = client.post("/api/pay/order", json={"product_code": "pass30_early"}, headers=headers).json()
    check("早鸟单金额 6.90", order["order"]["amount"] == "6.90", order["order"]["amount"])
    notify = client.post(
        "/api/pay/notify-dev",
        json={"out_trade_no": order["order"]["out_trade_no"], "amount": "6.90"},
        headers=headers,
    )
    # 生产服务器必须 403（安全线）；dev 环境 200 也合法——两种都算"行为正确"，但要写明是哪种
    check(
        "dev 回调安全线行为正确",
        notify.status_code in (403, 200),
        f"status={notify.status_code}",
    )
    print(f"    （notify-dev 返回 {notify.status_code}：403=生产安全线关闭中，200=dev 联调模式）")

    print("镜头 5 · 权益可读")
    entitlements = client.get("/api/entitlements/me", headers=headers).json()
    check("entitlements 形状", entitlements["plan"] in ("free", "paid30") and "quota" in entitlements)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n排练结果：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过" + (f"；失败：{failed}" if failed else " ✅ 评委旅程完整"))
    client.close()
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
