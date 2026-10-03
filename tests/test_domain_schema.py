"""守住 domain/ 的规则格式。

思路：本项目的核心设计是"**规则是数据，不是代码**"。
所以规则文件的格式一旦被写坏，必须在这里炸掉，而不是等到判定引擎算错钱才发现。

跑法：
    .\\.venv\\Scripts\\python.exe -m pytest -q
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_FILES = sorted((ROOT / "domain").glob("*/domain.yaml"))

REQUIRED_DOMAIN_KEYS = {"domain", "version", "note", "facts", "rules", "escalate"}
REQUIRED_RULE_KEYS = {"id", "when", "verdict", "fee", "cite", "priority"}
ALLOWED_VERDICTS = {
    "refundable",
    "not_refundable",
    "needs_review",
    "eligible",
    "not_eligible",
}
ALLOWED_FEE_FORMS = {"fixed", "rate_of_amount", "table_lookup"}


def test_two_sample_domains_exist():
    """两个域是有意为之：主场景（判定） + 副场景（可迁移性证明）。"""
    assert len(DOMAIN_FILES) == 2, f"期望 2 个示例域，实际找到 {len(DOMAIN_FILES)}"


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.parent.name)
def test_domain_file_shape(path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    where = path.parent.name

    assert REQUIRED_DOMAIN_KEYS <= set(data), f"{where} 缺少顶层字段"
    assert data["facts"], f"{where}: facts 不能为空——判定需要的事实必须显式列出"
    assert data["rules"], f"{where}: rules 不能为空"

    fact_names = [fact["name"] for fact in data["facts"]]
    assert len(fact_names) == len(set(fact_names)), f"{where}: 事实字段名重复"

    rule_ids = [rule["id"] for rule in data["rules"]]
    assert len(rule_ids) == len(set(rule_ids)), f"{where}: 规则 id 重复"

    for rule in data["rules"]:
        missing = REQUIRED_RULE_KEYS - set(rule)
        assert not missing, f"{where} 的 {rule.get('id')} 缺少字段：{sorted(missing)}"
        assert rule["verdict"] in ALLOWED_VERDICTS, f"{rule['id']}: 未知判定值"
        assert rule["fee"]["form"] in ALLOWED_FEE_FORMS, f"{rule['id']}: 未知费用形式"
        assert str(rule["cite"]).strip(), f"{rule['id']}: 没有 cite，视为缺陷判定"


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.parent.name)
def test_escalate_entries_are_complete(path: Path):
    """转人工条件是安全边界的最后一道闸，不允许写空。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["escalate"], f"{path.parent.name}: 必须至少有一条转人工条件"
    for item in data["escalate"]:
        assert item.get("when"), f"{path.parent.name}: 转人工条件缺少 when"
        assert item.get("reason"), f"{path.parent.name}: 转人工条件缺少 reason（要写清为什么）"


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.parent.name)
def test_domain_files_contain_no_external_links(path: Path):
    """红线守卫：判定域里不允许出现任何外部链接或真实机构线索。

    这是"仓库内不出现真实机构"这条约定的自动化检查——
    用通用规则实现，因此不需要在代码里写下任何真实名称。
    """
    text = path.read_text(encoding="utf-8")
    for marker in ("http://", "https://", "www."):
        assert marker not in text, f"{path.parent.name}: 不应包含外部链接（命中 {marker}）"
