"""红线守卫：只有两条，故意保持极简。

规则的格式校验已经搬进 `engine/domain.py`（见 `tests/test_domain.py`），
不在这里重复。这个文件只守两件"就算功能全对也不能破"的事。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_FILES = sorted((ROOT / "domain").glob("**/domain.yaml"))

# 回归夹具：这两个域曾经是"门面场景"，现在退居为"换域即复用"的证明。
REGRESSION_FIXTURES = {"airline-fare-sample", "university-credit-sample"}


def test_all_domains_are_discovered():
    """至少要有：2 个回归夹具 + 8 个医学分级域。"""
    names = {path.parent.name for path in DOMAIN_FILES}
    assert REGRESSION_FIXTURES <= names, f"回归夹具缺失：{REGRESSION_FIXTURES - names}"
    assert len(names - REGRESSION_FIXTURES) >= 8, (
        f"医学分级域不足 8 个，实际 {sorted(names - REGRESSION_FIXTURES)}"
    )


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.parent.name)
def test_domain_contains_no_external_links(path: Path):
    """仓库里不出现任何真实机构线索。

    用"是否包含外部链接"这个通用特征来检查，因此代码里不需要写下任何真实名称，
    检查本身也不会泄露什么。
    """
    text = path.read_text(encoding="utf-8")
    for marker in ("http://", "https://", "www."):
        assert marker not in text, f"{path.parent.name}: 不应包含外部链接（命中 {marker}）"
