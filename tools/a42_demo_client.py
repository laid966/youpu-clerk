"""A402 按量付费演示客户端（评委/Agent 零凭证体验用）。

## why
Machine Pay / Skill Pay 赛道的评委体验不该依赖签约或沙箱账号：
本脚本对着一个 MACHINE_PAY_DEMO=1 的服务端，完整走一遍官方 A2M 时序——
  1 请求资源 → 收 402 + Payment-Needed 账单
  2 （演示模式）构造 DEMO-PAID 占位凭证（真钱路径此处是 alipay-pay-for-402-service 技能付款）
  3 带 Payment-Proof 重试 → 验过 → 拿到议价授权决策
  4 再重放同一凭证 → 必须被拒（PROOF_REUSED，防重放是产品的命）

用法：
    set MACHINE_PAY_DEMO=1 && python -m uvicorn clerk.server:app --port 8100
    python tools/a42_demo_client.py [base_url] [asking] [offer]
"""

from __future__ import annotations

import base64
import json
import sys

import httpx


def b64url(obj: dict) -> str:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — 老 Windows GBK 控制台不许挡演示
            pass
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8100").rstrip("/")
    asking = sys.argv[2] if len(sys.argv) > 2 else "399.00"
    offer = sys.argv[3] if len(sys.argv) > 3 else "300.00"
    body = {"asking_price": asking, "buyer_offer": offer}
    client = httpx.Client(base_url=base, timeout=20.0, trust_env=False)

    print(f"[1] 请求议价决策资源 {base}/api/agent/bargain （asking={asking} offer={offer}）")
    r1 = client.post("/api/agent/bargain", json=body)
    if r1.status_code != 402:
        print(f"    期望 402，实际 {r1.status_code}: {r1.text[:200]}")
        print("    提示：服务端需以 MACHINE_PAY_DEMO=1 启动（演示）或配齐 MACHINE_PAY_* 凭证（真钱）")
        return 1
    invoice = json.loads(base64.urlsafe_b64decode(r1.headers["payment-needed"] + "=="))
    proto = invoice["protocol"]
    print(f"    402 ✅ 账单：{proto['amount']} {proto['currency']} · 单号 {proto['out_trade_no']}")
    print(f"        商品：{invoice['method']['goods_name']} · 截止 {proto['pay_before']}")

    print("[2] 构造支付凭证（演示占位 DEMO-PAID；真钱路径由 alipay-pay-for-402-service 技能完成付款）")
    proof = b64url(
        {
            "protocol": {"payment_proof": "DEMO-PAID", "trade_no": proto["out_trade_no"]},
            "method": {"client_session": "demo-judge-session"},
        }
    )

    print("[3] 带 Payment-Proof 重试 → 验凭证 → 交付决策")
    r2 = client.post("/api/agent/bargain", json=body, headers={"Payment-Proof": proof})
    if r2.status_code != 200:
        print(f"    期望 200，实际 {r2.status_code}: {r2.text[:300]}")
        return 1
    payload = r2.json()
    decision = payload["decision"]
    cites = [c.get("rule") if isinstance(c, dict) else c for c in decision.get("citations", [])]
    print(f"    200 ✅ 决策={decision['kind']} 价格={decision.get('price')} 依据规则={cites}")

    print("[4] 重放同一凭证 → 必须被拒（防重放）")
    r3 = client.post("/api/agent/bargain", json=body, headers={"Payment-Proof": proof})
    ok = r3.status_code == 402 and "PROOF_REUSED" in r3.text
    print(f"    {'✅ 402 PROOF_REUSED' if ok else '❌ 未拒绝: ' + str(r3.status_code)}")
    print("\nA402 时序走完：402 账单 → 凭证 → 交付 → 防重放。真钱路径把第 2 步换成支付宝付款即可。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
