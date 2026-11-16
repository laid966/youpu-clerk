"""部署冒烟：对着任意已部署地址跑一遍，六项全过才算"站点活着"（G4 验收工具）。

用法：
    .venv\\Scripts\\python.exe -m clerk.smoke http://127.0.0.1:8100
    .venv\\Scripts\\python.exe -m clerk.smoke https://你的域名.com

纪律：
- 只打公开端点（health / 静态 / bootstrap / demo step / pay products），不产生真实订单；
- demo step 走演示通道，会在目标库留下演示记录——与评委点一遍演示完全等价，无害；
- 任何一项失败退出码非 0，部署脚本/CI 可以直接拿它当门禁。
"""

from __future__ import annotations

import re
import sys

import httpx

MONEY_RE = re.compile(r"^\d+\.\d{2}$")


class SmokeError(AssertionError):
    pass


def _check(name: str, fn, results: list) -> None:
    try:
        fn()
        results.append((name, True, ""))
        print(f"  [ok] {name}")
    except Exception as exc:  # noqa: BLE001 — 冒烟就是要兜住一切并汇报
        results.append((name, False, str(exc)))
        print(f"  [FAIL] {name}: {exc}")


def main(base_url: str) -> int:
    from engine.console import ensure_utf8_console  # Windows 控制台中文乱码的老朋友

    ensure_utf8_console()
    base = base_url.rstrip("/")
    # trust_env=False：冒烟必须直连目标地址。本机若配了系统代理，
    # httpx 默认会把 127.0.0.1 也塞给代理，拿回 502/HTML——冒烟工具自己先成了假警报。
    client = httpx.Client(base_url=base, timeout=15.0, follow_redirects=False, trust_env=False)
    results: list[tuple[str, bool, str]] = []
    print(f"冒烟目标：{base}")

    def health():
        body = client.get("/api/health").json()
        assert body.get("status") == "ok", body
        assert "zh" in body.get("languages", []) and "en" in body.get("languages", [])
        assert body.get("product"), "health 缺产品名"

    def static_assets():
        index = client.get("/")
        assert index.status_code == 200 and "有谱掌柜" in index.text
        for asset in ("/styles.css", "/app.js", "/api.js", "/mock.js", "/i18n/zh.js", "/i18n/en.js"):
            response = client.get(asset)
            assert response.status_code == 200, f"{asset} -> {response.status_code}"

    def bootstrap():
        body = client.get("/api/demo/bootstrap").json()
        assert len(body["shop"]["items"]) == 3, "演示店铺应有 3 件商品"
        assert len(body["personas"]) == 5, "应有 5 个买家人设"
        for item in body["shop"]["items"]:
            assert MONEY_RE.match(item["asking_price"]) and MONEY_RE.match(item["floor_price"]), item

    def demo_script_matches_engine():
        """评委 60 秒路径的头两步必须与剧本 expected 一致（决策确定性）。"""
        first = client.post("/api/demo/step", json={"persona_id": "wang", "conversation_id": None}).json()
        assert first["decision"]["kind"] == first["expected"]["kind"] == "human", first["decision"]
        second = client.post(
            "/api/demo/step",
            json={"persona_id": "wang", "conversation_id": first["conversation_id"]},
        ).json()
        assert second["decision"]["kind"] == "counter", second["decision"]
        assert second["decision"]["price"] == second["expected"]["price"] == "379.05"

    def pay_products():
        body = client.get("/api/pay/products").json()
        codes = {tier["code"] for tier in body["tiers"]}
        assert codes == {"pass30", "pass30_early"}, codes
        for tier in body["tiers"]:
            assert MONEY_RE.match(tier["price"]), tier

    def dev_endpoints_closed():
        """生产安全线：未签名模拟回调必须关着（部署环境不该设 CLERK_PAY_DEV）。"""
        response = client.post(
            "/api/pay/notify-dev", json={"out_trade_no": "YP-SMOKE", "amount": "0.01"}
        )
        assert response.status_code == 403, f"notify-dev 竟然返回 {response.status_code}——生产环境必须 403"

    _check("health", health, results)
    _check("静态资产 6 件套", static_assets, results)
    _check("演示 bootstrap", bootstrap, results)
    _check("演示剧本=引擎行为（老王头两步）", demo_script_matches_engine, results)
    _check("定价档位", pay_products, results)
    _check("dev 回调已关闭", dev_endpoints_closed, results)

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n结果：{len(results) - len(failed)}/{len(results)} 通过" + (f"；失败：{failed}" if failed else " ✅"))
    client.close()
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
