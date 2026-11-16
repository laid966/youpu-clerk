"""一次性工具：从真实后端抓取响应，生成前端 mock 数据（clerk/web/mock.js）。

## 为什么 mock 数据要"抓"而不是手写
手写的 mock 会与真实 API 悄悄漂移——漂移之后，前端在 mock 模式下自欺欺人，
集成时才发现全是坑。抓取式 mock 保证：**mock 里的每个字节都是后端真实输出**。

## 用法（前端集成前/后端契约变更后重跑）
    .venv\\Scripts\\python.exe -m clerk.capture_mock
生成物：clerk/web/mock.js（带"勿手改"头注释，重新生成即覆盖）。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# 必须在 import clerk.server 之前指向临时库：抓 mock 不许污染真实 data/clerk.db
os.environ["CLERK_DB"] = str(Path(tempfile.mkdtemp(prefix="clerk-mock-")) / "clerk.db")

from fastapi.testclient import TestClient  # noqa: E402

from clerk.server import app  # noqa: E402
from clerk.templates import TemplateJudge  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "clerk" / "web" / "mock.js"


def main() -> None:
    app.state.judge = TemplateJudge()  # 抓取用确定性路径：mock 数据必须可复现
    client = TestClient(app)

    def play(persona_id: str) -> list[dict]:
        steps: list[dict] = []
        conversation_id = None
        while True:
            response = client.post(
                "/api/demo/step",
                json={"persona_id": persona_id, "conversation_id": conversation_id},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            conversation_id = body["conversation_id"]
            steps.append(body)
            if body["finished"]:
                break
        return steps

    bootstrap = client.get("/api/demo/bootstrap").json()
    data = {
        "health": client.get("/api/health").json(),
        "bootstrap": bootstrap,
        "payProducts": client.get("/api/pay/products").json(),
        "scripts": {
            persona["id"]: play(persona["id"]) for persona in bootstrap["personas"]
        },
    }

    payload = json.dumps(data, ensure_ascii=False, indent=1)
    OUT.write_text(
        "// 由 `python -m clerk.capture_mock` 从真实后端抓取生成——勿手改，改了就与 API 漂移。\n"
        f"export default {payload};\n",
        encoding="utf-8",
    )
    print(f"mock.js 已生成：{OUT}（{OUT.stat().st_size} 字节，{sum(len(s) for s in data['scripts'].values())} 步剧本）")


if __name__ == "__main__":
    main()
