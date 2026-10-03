"""控制台编码适配。

Windows 上中文 CLI 最常见的体验问题就是乱码：终端代码页是 936（GBK），
而 Python 的输出编码可能是 UTF-8，于是"当前状态"变成"褰撳墠鐘舵€"。

这里统一处理两件事：
    1. 把控制台代码页切到 65001（UTF-8）
    2. 把 stdout / stderr 的输出编码设为 UTF-8

失败无妨——这只是显示优化，绝不能让程序因为"改不了代码页"而崩掉。
"""

from __future__ import annotations

import sys

__all__ = ["ensure_utf8_console"]


def ensure_utf8_console() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:  # noqa: BLE001 — 纯显示优化，失败不影响功能
        pass

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
