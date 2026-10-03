"""`engine/selfcheck.py` 的测试。

自检工具最容易犯的错是"永远报没问题"。所以这里最重要的一组用例是：
**造一个真的有毛病的规则集，验证自检能把它抓出来。**
检测器本身也要被测——否则它只是一段看起来很专业的话。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.domain import load_domain
from engine.selfcheck import SelfCheckReport, run_selfcheck

ROOT = Path(__file__).resolve().parents[1]


def _inline_domain(tmp_path: Path, rules, facts):
    data = {
        "domain": "inline-selfcheck",
        "version": "0.1.0",
        "note": "测试用",
        "facts": facts,
        "rules": rules,
        "escalate": [{"when": "missing_any_fact == true", "reason": "缺信息"}],
    }
    path = tmp_path / "domain.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return load_domain(path)


@pytest.fixture(scope="module")
def airline():
    return load_domain(ROOT / "domain" / "airline-fare-sample" / "domain.yaml")


@pytest.fixture(scope="module")
def airline_report(airline):
    return run_selfcheck(airline, samples=3000)


# --------------------------------------------------------------------------- #
# 真实规则集的自检结果
# --------------------------------------------------------------------------- #


def test_airline_domain_has_no_same_priority_conflict(airline_report: SelfCheckReport):
    assert airline_report.errors == (), (
        "示例域不该有同优先级冲突。若有，说明规则设计需要调整：\n"
        + "\n".join(airline_report.errors)
    )
    assert airline_report.ok is True


def test_airline_coverage_is_high(airline_report: SelfCheckReport):
    """覆盖率不必是 100%（本项目故意不写兜底规则），但必须足够高。"""
    assert airline_report.coverage_rate > 0.9, f"覆盖率过低：{airline_report.coverage_rate:.1%}"


def test_every_airline_rule_is_reachable(airline_report: SelfCheckReport):
    """13 条规则都应该是活的——死规则说明条件写错了，或者设计意图没落地。"""
    assert airline_report.never_matched == (), (
        "以下规则从未命中，请检查条件：" + ", ".join(airline_report.never_matched)
    )


def test_airline_report_shows_both_hit_and_win_counts(airline_report: SelfCheckReport):
    """必须能看出"命中但从不生效"这种白写的规则。"""
    assert airline_report.matched_counts
    assert airline_report.win_counts
    for rule_id, matched in airline_report.matched_counts.items():
        assert airline_report.win_counts.get(rule_id, 0) <= matched


def test_report_renders_markdown_with_key_sections(airline_report: SelfCheckReport):
    text = airline_report.to_markdown()

    assert "规则自检报告" in text
    assert "反例搜索" in text, "必须写明这是反例搜索而不是逻辑证明"
    assert "## 错误级问题" in text
    assert "## 转人工原因分布" in text
    assert "规则覆盖" in text


# --------------------------------------------------------------------------- #
# 检测器必须真的能检测
# --------------------------------------------------------------------------- #


def test_detects_same_priority_conflict(tmp_path):
    domain = _inline_domain(
        tmp_path,
        rules=[
            {
                "id": "C-1",
                "when": "amount > 10",
                "verdict": "refundable",
                "cite": "条款 1",
                "priority": 5,
            },
            {
                "id": "C-2",
                "when": "amount > 20",
                "verdict": "not_refundable",
                "cite": "条款 2",
                "priority": 5,
            },
        ],
        facts=[{"name": "amount", "type": "number", "minimum": 0, "maximum": 100}],
    )

    report = run_selfcheck(domain, samples=500)

    assert report.errors, "同优先级冲突必须被报为错误"
    assert report.conflicts
    assert "C-1" in report.conflicts[0] and "C-2" in report.conflicts[0]
    assert "反例" in report.conflicts[0], "报告必须给出反例，否则用户无从下手"
    assert report.ok is False


def test_detects_never_matched_rule(tmp_path):
    """条件里用了一个永远不会成立的区间，属于典型的写错。"""
    domain = _inline_domain(
        tmp_path,
        rules=[
            {
                "id": "N-1",
                "when": "amount > 10",
                "verdict": "refundable",
                "cite": "条款",
                "priority": 1,
            },
            {
                "id": "N-2",
                "when": "amount < 0",
                "verdict": "not_refundable",
                "cite": "条款",
                "priority": 2,
            },
        ],
        facts=[{"name": "amount", "type": "number", "minimum": 0, "maximum": 100}],
    )

    report = run_selfcheck(domain, samples=300)

    assert "N-2" in report.never_matched
    assert any("从未命中" in warning for warning in report.warnings)


def test_detects_fully_shadowed_rule(tmp_path):
    """S-2 会命中，但因为优先级更低、永远被 S-1 压住，等于白写。"""
    domain = _inline_domain(
        tmp_path,
        rules=[
            {
                "id": "S-1",
                "when": "amount > 10",
                "verdict": "refundable",
                "cite": "条款 1",
                "priority": 10,
            },
            {
                "id": "S-2",
                "when": "amount > 50",
                "verdict": "refundable",
                "cite": "条款 2",
                "priority": 1,
            },
        ],
        facts=[{"name": "amount", "type": "number", "minimum": 0, "maximum": 100}],
    )

    report = run_selfcheck(domain, samples=500)

    assert "S-2" not in report.never_matched, "它确实被命中过"
    assert "S-2" in report.never_won, "但从没生效，必须被标出来"
    assert any("遮蔽" in warning for warning in report.warnings)


def test_reports_rule_gaps_with_examples(tmp_path):
    """一半的取值区间没有规则覆盖——缺口必须被看见，而不是被兜底规则悄悄填掉。"""
    domain = _inline_domain(
        tmp_path,
        rules=[
            {
                "id": "G-1",
                "when": "amount < 20",
                "verdict": "refundable",
                "cite": "条款",
                "priority": 1,
            }
        ],
        facts=[{"name": "amount", "type": "number", "minimum": 0, "maximum": 100}],
    )

    report = run_selfcheck(domain, samples=300)

    assert report.uncovered > 0
    assert report.coverage_rate < 1.0
    assert report.gap_examples, "必须给出缺口的具体例子"
    assert any("没有任何规则覆盖" in warning for warning in report.warnings)


def test_selfcheck_is_deterministic(airline):
    first = run_selfcheck(airline, samples=500)
    second = run_selfcheck(airline, samples=500)

    assert first.to_markdown() == second.to_markdown()
