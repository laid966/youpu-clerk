"""分级域的引擎能力：域自声明判定值、默认结论、危急结论必须人工。

这一组能力是为了让引擎能服务"分级/审核"类场景（医学分级、风险评级、合规等级）而加的。
三条设计判断值得记住：

1. **判定值是域的语言**：费用域说 refundable，医学域说 critical。引擎不该替它规定词汇表。
2. **"没有规则命中"的含义是域相关的**：费用域里它意味着规则集有缺口（必须转人工）；
   医学域里它恰恰是最理想的情况（所有指标都正常）。所以由域声明，引擎不猜。
3. **"必须有人接住"是引擎的内置不变量**：和"缺事实必须转人工"一样，
   写进配置就总有一天会被人删掉。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.adjudicate import adjudicate
from engine.domain import DomainError, load_domain
from engine.selfcheck import run_selfcheck


def _grading_domain(tmp_path: Path, **overrides):
    """一个最小的"分级域"：把数值分成 normal / mild / critical 三级。"""
    data = {
        "domain": "grading-test",
        "version": "0.1.0",
        "note": "测试用",
        "verdicts": ["normal", "mild", "critical"],
        "default_verdict": "normal",
        "critical_verdicts": ["critical"],
        "facts": [
            {"name": "alt", "type": "number", "minimum": 0, "maximum": 1000,
             "boundaries": [40, 200]},
        ],
        "rules": [
            {
                "id": "G-MILD",
                "when": "alt > 40",
                "verdict": "mild",
                "cite": "参考区间上限 40",
                "priority": 10,
            },
            {
                "id": "G-CRIT",
                "when": "alt > 200",
                "verdict": "critical",
                "cite": "危急值 200",
                "priority": 20,
            },
        ],
        "escalate": [
            {"when": "missing_any_fact == true", "reason": "关键信息缺失"},
        ],
    }
    data.update(overrides)
    path = tmp_path / "domain.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return load_domain(path)


# --------------------------------------------------------------------------- #
# 域自声明判定值
# --------------------------------------------------------------------------- #


def test_domain_can_declare_its_own_verdicts(tmp_path):
    domain = _grading_domain(tmp_path)

    assert domain.verdicts == frozenset({"normal", "mild", "critical"})
    assert "refundable" not in domain.verdicts, "不该混进引擎默认的那组费用域词汇"


def test_rule_verdict_outside_declared_set_is_rejected(tmp_path):
    with pytest.raises(DomainError, match="不在本域声明的判定值里"):
        _grading_domain(
            tmp_path,
            rules=[
                {"id": "X", "when": "alt > 40", "verdict": "refundable",
                 "cite": "x", "priority": 1},
            ],
        )


def test_domain_without_verdicts_falls_back_to_engine_default(tmp_path):
    """没声明就沿用引擎默认值——旧的两个判定域因此一行都不用改。"""
    domain = _grading_domain(
        tmp_path,
        verdicts=None,
        default_verdict=None,
        critical_verdicts=[],
        rules=[
            {"id": "F-1", "when": "alt > 40", "verdict": "refundable",
             "cite": "x", "priority": 1},
        ],
    )

    assert "refundable" in domain.verdicts
    assert domain.default_verdict is None


# --------------------------------------------------------------------------- #
# 默认结论
# --------------------------------------------------------------------------- #


def test_default_verdict_applies_when_no_rule_matches(tmp_path):
    """alt=30 谁都不命中 → 结论是 normal，而不是"规则缺口"。"""
    domain = _grading_domain(tmp_path)

    result = adjudicate(domain, {"alt": 30})

    assert result.final_verdict == "normal"
    assert result.computed_verdict == "normal"
    assert result.escalated is False
    assert result.requires_human_review is False
    assert not any("规则缺口" in reason for reason in result.escalate_reasons)


def test_without_default_verdict_rule_gap_still_escalates():
    """对照：费用域（无默认结论）里"没有规则命中"仍然是缺口、仍然转人工。"""
    root = Path(__file__).resolve().parents[1]
    airline = load_domain(root / "domain" / "airline-fare-sample" / "domain.yaml")

    assert airline.default_verdict is None


def test_default_verdict_must_be_declared(tmp_path):
    with pytest.raises(DomainError, match="default_verdict"):
        _grading_domain(tmp_path, default_verdict="unknown_level")


# --------------------------------------------------------------------------- #
# 危急结论必须人工
# --------------------------------------------------------------------------- #


def test_critical_verdict_forces_human_review(tmp_path):
    """alt=300 命中危急规则：即使没有任何转人工条件被触发，也必须进人工队列。"""
    domain = _grading_domain(tmp_path)

    result = adjudicate(domain, {"alt": 300})

    assert result.final_verdict == "critical"
    assert result.escalated is False
    assert result.requires_human_review is True, "危急结论不允许自动放行"


def test_critical_flag_survives_escalation(tmp_path):
    """另一个原因导致转人工时，不能把"本来是危急"这个事实吞掉。"""
    domain = _grading_domain(
        tmp_path,
        escalate=[
            {"when": "missing_any_fact == true", "reason": "关键信息缺失"},
            {"when": "alt > 1000", "reason": "超出本域覆盖范围"},
        ],
    )

    result = adjudicate(domain, {"alt": 1100})

    assert result.final_verdict == "needs_review"
    assert result.computed_verdict == "critical"
    assert result.requires_human_review is True


def test_mild_verdict_does_not_require_human(tmp_path):
    domain = _grading_domain(tmp_path)

    result = adjudicate(domain, {"alt": 100})

    assert result.final_verdict == "mild"
    assert result.requires_human_review is False


def test_critical_verdicts_must_be_declared(tmp_path):
    with pytest.raises(DomainError, match="critical_verdicts"):
        _grading_domain(tmp_path, critical_verdicts=["emergency"])


def test_requires_human_review_is_exported_to_dict(tmp_path):
    domain = _grading_domain(tmp_path)

    payload = adjudicate(domain, {"alt": 300}).to_dict()

    assert payload["requires_human_review"] is True


# --------------------------------------------------------------------------- #
# 自检：默认结论不算缺口
# --------------------------------------------------------------------------- #


def test_selfcheck_does_not_report_gaps_when_default_verdict_set(tmp_path):
    domain = _grading_domain(tmp_path)

    report = run_selfcheck(domain, samples=300)

    assert report.uncovered == 0, "有默认结论时不存在「没规则覆盖」这回事"
    assert report.default_hits > 0
    assert not any("没有任何规则覆盖" in warning for warning in report.warnings)
    assert "默认结论命中" in report.to_markdown()
