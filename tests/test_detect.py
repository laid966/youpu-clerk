"""确定性检查器测试。

分两组：
1. **该抓的要抓到**：每类缺陷造一份定向产物，验证对应检查器报出来。
2. **不该抓的不能抓**：合法变体（显示取整、引用顺序调换、引用重复）不许被报成缺陷。
   第二组更重要——误报率是本项目的死穴。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audit.artifact import ADVICE_BY_SEVERITY, build_artifact, replace_item
from audit.detect import DETECTORS, Finding, detect
from audit.inject import apply_legitimate_variation
from audit.pipeline import Metric, load_metrics
from audit.synth import DEFAULT_SEED, generate_reports

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def metrics() -> tuple[Metric, ...]:
    return load_metrics()


@pytest.fixture(scope="module")
def base(metrics):
    """取一份**含多项异常**的判决样本。

    特意不用第一份：第一份可能是"全正常"档案，那样的产物里一条引用都没有
    （没命中规则就没有依据），于是"引用顺序调换""引用重复"这两个合法变体
    根本没法施加，测试会被静默跳过——跳过的测试等于没测。
    """
    for _profile, judged in generate_reports(count=120, metrics=metrics, seed=DEFAULT_SEED):
        artifact = build_artifact(judged, metrics)
        if any(len(item.citations) >= 2 for item in artifact.items):
            return judged, artifact
    raise AssertionError("样本里没有找到带多条依据的指标")  # pragma: no cover


def run(artifact, judged, metrics) -> tuple[Finding, ...]:
    report = judged.report
    return detect(artifact, report.values, report.sex, report.age, metrics)


def detectors_of(findings) -> set[str]:
    return {finding.detector for finding in findings}


# --------------------------------------------------------------------------- #
# 干净产物：一条都不该报
# --------------------------------------------------------------------------- #


def test_clean_artifact_produces_no_findings(base, metrics):
    judged, artifact = base
    assert run(artifact, judged, metrics) == ()


@pytest.mark.parametrize("variation_name", ["rounded_value", "citation_reorder", "citation_duplicate"])
def test_legitimate_variations_are_not_flagged(base, metrics, variation_name, monkeypatch):
    """合法变体不许被报成缺陷——这是误报率的核心考验。

    真实问题回归：数值一致性检查最初没有容差，于是"4.2117 显示成 4.21"
    会被报成"数值抄错"。显示取整是正常行为，不是缺陷。
    """
    import random

    judged, artifact = base

    # 定向施加指定的合法变体
    for item in artifact.items:
        if variation_name == "rounded_value" and round(item.value, 2) != item.value:
            varied = replace_item(artifact, item.code, value=round(item.value, 2))
            break
        if variation_name == "citation_reorder" and len(item.citations) >= 2:
            varied = replace_item(artifact, item.code, citations=tuple(reversed(item.citations)))
            break
        if variation_name == "citation_duplicate" and item.citations:
            varied = replace_item(
                artifact, item.code, citations=(item.citations[0],) + item.citations
            )
            break
    else:  # pragma: no cover — 我们的样本一定满足条件
        pytest.skip("这份产物不满足该变体的施加条件")

    assert varied != artifact, "变体没有真正生效"
    assert run(varied, judged, metrics) == (), f"合法变体 {variation_name} 被误报了"


def test_apply_legitimate_variation_never_creates_findings(base, metrics):
    """随机施加合法变体，也不该产生任何发现。"""
    import random

    judged, artifact = base
    rng = random.Random(7)
    for _ in range(30):
        varied, name = apply_legitimate_variation(artifact, rng)
        if name == "none":
            continue
        assert run(varied, judged, metrics) == (), f"变体 {name} 被误报"


# --------------------------------------------------------------------------- #
# 每类缺陷都要被对应的检查器抓到
# --------------------------------------------------------------------------- #


def test_value_tolerance_allows_rounding(base, metrics):
    judged, artifact = base
    item = artifact.items[0]
    rounded = replace_item(artifact, item.code, value=round(item.value, 3))

    findings = run(rounded, judged, metrics)
    assert "value_consistency" not in detectors_of(findings)


def test_value_mismatch_is_caught(base, metrics):
    judged, artifact = base
    item = artifact.items[0]
    wrong = replace_item(artifact, item.code, value=item.value * 1.5)

    findings = run(wrong, judged, metrics)
    hits = [f for f in findings if f.detector == "value_consistency"]
    assert hits and hits[0].target == item.code


def test_unit_mismatch_is_caught(base, metrics):
    judged, artifact = base
    item = artifact.items[0]
    wrong = replace_item(artifact, item.code, unit="mmol/L" if item.unit != "mmol/L" else "U/L")

    findings = run(wrong, judged, metrics)
    assert "unit_consistency" in detectors_of(findings)


def test_fabricated_citation_is_caught(base, metrics):
    judged, artifact = base
    item = artifact.items[0]
    faked = replace_item(
        artifact, item.code, citations=item.citations + ("《不存在的指南》第 1 条",)
    )

    findings = run(faked, judged, metrics)
    assert "citation_existence" in detectors_of(findings)


def test_advice_contract_violation_is_caught(base, metrics):
    judged, artifact = base
    item = artifact.items[0]
    wrong_advice = next(
        advice for advice in ADVICE_BY_SEVERITY.values() if advice != item.advice
    )
    broken = replace_item(artifact, item.code, advice=wrong_advice)

    findings = run(broken, judged, metrics)
    assert "advice_contract" in detectors_of(findings)


def test_safety_violation_is_caught(base, metrics):
    judged, artifact = base
    item = artifact.items[0]
    unsafe = replace_item(
        artifact, item.code, explanation=item.explanation + "考虑为脂肪肝，建议服用护肝片。"
    )

    findings = run(unsafe, judged, metrics)
    assert "safety_terms" in detectors_of(findings)


def test_oracle_differential_catches_missed_critical(base, metrics):
    """把正常项改成危急（或反之），oracle 重算立刻发现不一致。"""
    judged, artifact = base
    item = artifact.items[0]
    tampered = replace_item(artifact, item.code, severity="critical", advice=ADVICE_BY_SEVERITY["critical"])

    findings = run(tampered, judged, metrics)
    hits = [f for f in findings if f.detector == "oracle_differential"]
    assert hits and hits[0].target == item.code

    # 自查：这条缺陷**没有触发任何其他检查器**，只有 oracle 能发现它
    others = detectors_of(findings) - {"oracle_differential"}
    assert others == set(), f"不该被其他检查器发现，实际还有 {others}"


def test_all_detectors_are_distinct_and_registered():
    assert len(set(DETECTORS)) == len(DETECTORS) == 6
