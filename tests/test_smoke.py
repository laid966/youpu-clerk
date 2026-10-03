"""M0 最小测试：证明测试链路可用，并守住两条底线。

跑法：
    .\\.venv\\Scripts\\python.exe -m pytest -q

为什么 M0 就要写测试：招聘方把"有没有评估与回归"当成及格线，而不是加分项。
现在这一步只是把习惯立起来——以后的判定引擎每一行都必须有测试兜着。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_main():
    """按路径加载 main.py。用文件名而不是包名，避免为了一个冒烟脚本搞出包结构。"""
    spec = importlib.util.spec_from_file_location("rulecheck_main", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def main_module():
    return _load_main()


def test_estimate_cost_matches_hand_calculation(main_module):
    # 100 万输入 + 100 万输出 → 正好是输入单价 + 输出单价
    cost = main_module.estimate_cost(1_000_000, 1_000_000)
    assert cost == pytest.approx(main_module.PRICE_IN + main_module.PRICE_OUT)


def test_estimate_cost_is_zero_without_tokens(main_module):
    assert main_module.estimate_cost(0, 0) == 0.0


def test_missing_api_key_exits_gracefully(main_module, monkeypatch, capsys):
    """没有 key 时必须给人话提示并以退出码 2 结束，而不是抛一堆堆栈。

    注意：这个测试故意删掉环境变量，所以它永远不会真的去调模型、不会花钱。
    """
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    code = main_module.main()

    assert code == 2
    assert "DEEPSEEK_API_KEY" in capsys.readouterr().out
