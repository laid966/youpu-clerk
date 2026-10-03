"""模型调用的最小封装：可缓存、可替换、测试不花钱。

三个实现：

| 实现 | 用途 | 花钱吗 |
|---|---|---|
| `DeepSeekJudge` | 真的调模型 | 花，但极便宜 |
| `CachedJudge` | 包住任意 judge，把 `prompt -> 回答` 存进 SQLite | 第一次花，之后不花 |
| `FakeJudge` | 测试用，返回预设回答 | 不花，不联网 |

**为什么必须有缓存**：提示词迭代要跑很多次。缓存让"同一版提示词重跑"变成免费的，
于是你可以放心地反复验证；只有真正改了提示词的那次才会产生新调用。

缓存键 = 模型名 + 温度 + 提示词的哈希。所以改了提示词必然重新调用——
这是对的：改提示词就是要看新结果。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

from dotenv import load_dotenv

__all__ = ["CachedJudge", "DeepSeekJudge", "FakeJudge", "Judge", "build_judge"]

ROOT = Path(__file__).resolve().parents[1]
CACHE_DB = ROOT / "data" / "judge-cache.db"

# 读 .env。放在这里而不是只在 main.py 里读——
# 因为 `python -m agent ...` 是另一条入口，之前就漏了这一步，
# 结果真调模型时报"没有 key"。**密钥的加载必须跟着用它的模块走。**
load_dotenv(ROOT / ".env")


@runtime_checkable
class Judge(Protocol):
    def complete(self, prompt: str, temperature: float = 0.0) -> str: ...


class DeepSeekJudge:
    """真的调模型。只有这里会花钱。"""

    def __init__(self, model: str | None = None, max_retries: int = 2, timeout: int = 60) -> None:
        from langchain_deepseek import ChatDeepSeek

        if not os.getenv("DEEPSEEK_API_KEY"):
            raise RuntimeError(
                "没有读到 DEEPSEEK_API_KEY。\n"
                "  1) 把 .env.example 复制成 .env\n"
                "  2) 填入你自己申请的 key\n"
                "  3) 重新运行"
            )

        self.model_name = model or os.getenv("MODEL_NAME", "deepseek-chat")
        self._model = ChatDeepSeek(
            model=self.model_name, temperature=0, max_retries=max_retries, timeout=timeout
        )

    def complete(self, prompt: str, temperature: float = 0.0) -> str:
        message = self._model.invoke(prompt)
        content = message.content
        if isinstance(content, list):  # 有的实现会返回分块内容
            return "".join(str(part) for part in content)
        return str(content)


class CachedJudge:
    """把回答缓存到 SQLite。键里含提示词哈希，所以改提示词必然重新调用。"""

    def __init__(self, inner: Judge, path: str | Path = CACHE_DB) -> None:
        self.inner = inner
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS judge_cache ("
                "  key TEXT PRIMARY KEY,"
                "  prompt TEXT NOT NULL,"
                "  response TEXT NOT NULL"
                ")"
            )
        self.hits = 0
        self.misses = 0

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _key(self, prompt: str, temperature: float) -> str:
        payload = f"{getattr(self.inner, 'model_name', 'unknown')}|{temperature}|{prompt}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def complete(self, prompt: str, temperature: float = 0.0) -> str:
        key = self._key(prompt, temperature)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response FROM judge_cache WHERE key = ?", (key,)
            ).fetchone()
        if row is not None:
            self.hits += 1
            return str(row[0])

        self.misses += 1
        response = self.inner.complete(prompt, temperature)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO judge_cache (key, prompt, response) VALUES (?, ?, ?)",
                (key, prompt, response),
            )
        return response

    @property
    def model_name(self) -> str:
        return getattr(self.inner, "model_name", "cached")


class FakeJudge:
    """测试用：给一个函数决定回答，或者一个固定回答。不联网、不花钱。"""

    def __init__(self, responder: Callable[[str], str] | str = '{"violation": false, "category": "none", "evidence": ""}') -> None:
        self.model_name = "fake"
        self.responder = responder
        self.prompts: list[str] = []

    def complete(self, prompt: str, temperature: float = 0.0) -> str:
        self.prompts.append(prompt)
        if callable(self.responder):
            return self.responder(prompt)
        return self.responder


def build_judge(use_cache: bool = True) -> Judge:
    """按需组装 judge。默认带缓存。"""
    judge: Judge = DeepSeekJudge()
    if use_cache:
        judge = CachedJudge(judge)
    return judge
