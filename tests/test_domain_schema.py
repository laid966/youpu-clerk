"""红线守卫：只有两条，故意保持极简。

规则的格式校验已经搬进 `engine/domain.py`（见 `tests/test_domain.py`），
不在这里重复。这个文件只守两件"就算功能全对也不能破"的事。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_FILES = sorted((ROOT / "domain").glob("*/domain.yaml"))


def test_two_sample_domains_exist():
    """两个域是有意为之：主场景（有金额）+ 副场景（无金额、证明可迁移）。"""
    assert len(DOMAIN_FILES) == 2, f"期望 2 个示例域，实际 {len(DOMAIN_FILES)} 个"


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.parent.name)
def test_domain_contains_no_external_links(path: Path):
    """仓库里不出现任何真实机构线索。

    用"是否包含外部链接"这个通用特征来检查，因此代码里不需要写下任何真实名称，
    检查本身也不会泄露什么。
    """
    text = path.read_text(encoding="utf-8")
    for marker in ("http://", "https://", "www."):
        assert marker not in text, f"{path.parent.name}: 不应包含外部链接（命中 {marker}）"
