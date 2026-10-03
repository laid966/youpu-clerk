"""rulecheck · 冒烟脚本

它只证明三件事：
  1. 能读到你的 API key
  2. 能连上模型并拿到回答
  3. 能看到这次调用花了多少 token、大约多少钱

它不包含任何业务逻辑。跑通之后就可以进入 M1（判定引擎）。

用法：
    .\\.venv\\Scripts\\python.exe main.py

关于本项目最重要的一条设计原则（先记住这一句）：
    大模型不负责算数。它只负责"听懂人话"和"把结果解释成人话"。
    所有涉及金额与资格的计算，一律交给 engine/ 里的程序完成。
    这个冒烟脚本故意只做一次最简单的调用，不碰任何计算。
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

from engine.console import ensure_utf8_console

# Windows 控制台按 UTF-8 显示中文（与引擎 CLI 共用同一份实现）
ensure_utf8_console()

# 读取同目录下的 .env（该文件被 .gitignore 排除，永远不会提交）
load_dotenv()

MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-chat")
PRICE_IN = float(os.getenv("PRICE_INPUT_PER_MTOK", "2.00"))
PRICE_OUT = float(os.getenv("PRICE_OUTPUT_PER_MTOK", "8.00"))
MAX_CNY_PER_CALL = float(os.getenv("MAX_CNY_PER_CALL", "0.10"))

QUESTION = "用一句话说明：为什么不应该让大语言模型负责计算金额？"


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """按单价估算本次花费（元）。单价写在 .env 里，厂商调价时不用改代码。"""
    return (input_tokens * PRICE_IN + output_tokens * PRICE_OUT) / 1_000_000


def main() -> int:
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("[x] 没有读到 DEEPSEEK_API_KEY。")
        print("    1) 把 .env.example 复制成 .env")
        print("    2) 在 .env 里填上你自己申请的 key")
        print("    3) 重新运行这条命令")
        return 2

    # temperature=0：冒烟也保持确定性，便于对比两次运行是否一致
    # max_retries=1：失败不要重试太多次，冒烟脚本要快速给出结论
    model = ChatDeepSeek(model=MODEL_NAME, temperature=0, max_retries=1, timeout=30)

    print(f"-> 正在调用模型 {MODEL_NAME} ...")
    try:
        message = model.invoke(QUESTION)
    except Exception as exc:  # noqa: BLE001 — 冒烟脚本的职责就是把故障翻译成人话
        detail = str(exc)
        lowered = detail.lower()
        print("\n[x] 调用失败。常见原因对照：")
        if "401" in detail or "invalid_api_key" in lowered or "authentication" in lowered:
            print("    key 无效或未生效（HTTP 401）→ 检查 .env 里的 DEEPSEEK_API_KEY")
        elif "402" in detail or "insufficient" in lowered or "balance" in lowered:
            print("    余额不足（HTTP 402）→ 去模型厂商后台充值")
        elif "timeout" in lowered or "connect" in lowered:
            print("    网络问题 → 确认能否访问模型服务地址")
        else:
            print("    未归类的错误，原始信息见下方")
        print(f"\n    原始错误：{type(exc).__name__}: {detail[:300]}")
        return 4

    print("\n--- 模型回答 ---")
    print(message.content)

    usage = getattr(message, "usage_metadata", None) or {}
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cost = estimate_cost(input_tokens, output_tokens)

    print("\n--- 本次消耗 ---")
    print(f"输入 token : {input_tokens}")
    print(f"输出 token : {output_tokens}")
    print(f"估算花费   : CNY {cost:.6f}")

    if cost > MAX_CNY_PER_CALL:
        print(f"\n[x] 单次花费超过护栏 CNY {MAX_CNY_PER_CALL}（在 .env 里可调）。已中止。")
        return 3

    print("\n[ok] 环境通了。下一步是 M1：判定引擎 + 自动生成评测集。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
