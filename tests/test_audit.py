"""auditkit A1 阶段测试：判决流水线与判决样本生成。

这一层是「被审计对象」的来源，所以它自己必须先站得住：
确定性、可复现、档案意图与引擎判决一致、不产生超出事实范围的取值。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit.pipeline import (
    Report,
    judge_metric,
    judge_report,
    load_metrics,
    severity_rank,
)
from audit.synth import (
    DEFAULT_SEED,
    PROFILE_WEIGHTS,
    generate_reports,
    supports_severity,
    to_json_line,
    write_dataset,
)

ROOT = Path(__file__).resolve().parents[1]

# 档案名 -> 该档案**应当**达到的最严重结论
EXPECTED_WORST = {
    "normal": "normal",
    "single_mild": "mild",
    "multi_mild": "mild",
    "marked": "marked",
    "critical": "critical",
}


@pytest.fixture(scope="module")
def metrics():
    return load_metrics()


@pytest.fixture(scope="module")
def cases(metrics):
    return generate_reports(count=200, metrics=metrics, seed=DEFAULT_SEED)


# --------------------------------------------------------------------------- #
# 指标清单与判决流水线
# --------------------------------------------------------------------------- #


def test_eight_metrics_are_loaded(metrics):
    assert len(metrics) == 8
    assert {metric.code for metric in metrics} == {
        "alt",
        "ast",
        "ggt",
        "crea",
        "ua",
        "tc",
        "fpg",
        "hgb",
    }


def test_every_metric_domain_file_exists(metrics):
    for metric in metrics:
        assert metric.domain_path.is_file(), f"{metric.code} 的判定域不存在"
        assert {"male", "female"} <= set(metric.reference), f"{metric.code} 缺少分性别参考区间"


def test_severity_rank_is_ordered():
    assert severity_rank("normal") < severity_rank("mild") < severity_rank("marked")
    assert severity_rank("marked") < severity_rank("critical")
    assert severity_rank("needs_review") == -1, "未知判定值不能混进严重度排序"


def test_normal_report_is_judged_normal(metrics):
    values = {}
    for metric in metrics:
        low, high = metric.reference_for("male")
        values[metric.code] = round((low + high) / 2, 4)

    judged = judge_report(Report("R-TEST", 40, "male", values), metrics)

    assert judged.worst_verdict() == "normal"
    assert judged.abnormal_codes() == ()
    assert judged.needs_human_review() == ()


def test_critical_value_is_flagged_and_needs_human(metrics):
    by_code = {metric.code: metric for metric in metrics}
    alt = by_code["alt"]

    payload = judge_metric(alt, "male", 40, 400)

    assert payload["final_verdict"] == "critical"
    assert payload["requires_human_review"] is True, "危急结论必须有人接住"


def test_sex_specific_thresholds_differ(metrics):
    """同一数值在男女身上结论不同——这正是审计器以后最该抓的一类缺陷（用错性别阈值）。

    肌酐：男性参考区间 57–97，女性 41–73，轻度阈值分别 >97 / >73，明显阈值 >133 / >106。

    - 80：男性正常，女性轻度升高（最鲜明的对比）
    - 110：男性轻度，女性明显升高
    """
    by_code = {metric.code: metric for metric in metrics}
    crea = by_code["crea"]

    assert judge_metric(crea, "male", 40, 80)["final_verdict"] == "normal"
    assert judge_metric(crea, "female", 40, 80)["final_verdict"] == "mild"

    assert judge_metric(crea, "male", 40, 110)["final_verdict"] == "mild"
    assert judge_metric(crea, "female", 40, 110)["final_verdict"] == "marked"


def test_ua_cannot_reach_critical_but_alt_can(metrics):
    """能力图：尿酸域没有定义危急阈值，所以它做不出危急结论。

    生成器依赖这个判断来避免"档案名叫 critical、实际却到不了 critical"。
    """
    by_code = {metric.code: metric for metric in metrics}

    assert supports_severity(by_code["ua"], "male", 40, "critical") is False
    assert supports_severity(by_code["alt"], "male", 40, "critical") is True


# --------------------------------------------------------------------------- #
# 样本生成
# --------------------------------------------------------------------------- #


def test_generates_exact_count(cases):
    assert len(cases) == 200


def test_same_seed_is_byte_identical(metrics):
    first = generate_reports(count=50, metrics=metrics, seed=DEFAULT_SEED)
    second = generate_reports(count=50, metrics=metrics, seed=DEFAULT_SEED)

    assert [to_json_line(p, j) for p, j in first] == [to_json_line(p, j) for p, j in second]


def test_different_seed_differs(metrics):
    first = generate_reports(count=50, metrics=metrics, seed=DEFAULT_SEED)
    second = generate_reports(count=50, metrics=metrics, seed=DEFAULT_SEED + 1)

    assert [to_json_line(p, j) for p, j in first] != [to_json_line(p, j) for p, j in second]


def test_profile_distribution_matches_plan(cases):
    """配比必须精确命中计划值——这是对 FM-003（分布失真）的直接防范。"""
    from collections import Counter

    counts = Counter(profile for profile, _ in cases)
    for name, weight in PROFILE_WEIGHTS.items():
        expected = round(len(cases) * weight)
        assert counts.get(name, 0) == expected, (
            f"{name} 期望 {expected} 份，实际 {counts.get(name, 0)} 份"
        )


def test_profile_intent_matches_engine_verdict(cases):
    """档案名与引擎判决必须一致。

    真实 bug 回归：尿酸域没有危急阈值，最初随机抽到尿酸的"危急"档案
    永远到不了危急，档案名就变成了一个说不清的东西。
    修法是让生成器只在"做得到该严重度"的指标里抽。
    """
    for profile, judged in cases:
        assert judged.worst_verdict() == EXPECTED_WORST[profile], (
            f"{judged.report_id}（档案 {profile}）最严重结论是 {judged.worst_verdict()}"
        )


def test_no_value_falls_outside_declared_fact_range(cases):
    """生成器不能产出超出事实声明范围的取值——否则会被引擎标为越界并转人工。"""
    for _, judged in cases:
        for code, payload in judged.judgements.items():
            assert payload["out_of_range_facts"] == [], (
                f"{judged.report_id} 的 {code} 取值越界：{payload['out_of_range_facts']}"
            )


def test_critical_cases_require_human_review(cases):
    critical_cases = [judged for profile, judged in cases if profile == "critical"]
    assert critical_cases, "应当生成危急档案"
    for judged in critical_cases:
        assert judged.needs_human_review(), f"{judged.report_id} 有危急值却没有进人工队列"


def test_normal_cases_have_no_abnormal_metric(cases):
    normal_cases = [judged for profile, judged in cases if profile == "normal"]
    assert len(normal_cases) == 100
    for judged in normal_cases:
        assert judged.abnormal_codes() == ()


def test_json_line_has_expected_keys(cases):
    profile, judged = cases[0]
    payload = json.loads(to_json_line(profile, judged))

    assert {"profile", "report_id", "age", "sex", "values", "judgements"} <= set(payload)
    assert payload["profile"] in PROFILE_WEIGHTS
    assert payload["worst_verdict"] == EXPECTED_WORST[payload["profile"]]


def test_write_dataset_produces_jsonl_and_sample(tmp_path, cases):
    out = tmp_path / "judged.jsonl"
    sample = tmp_path / "judged.sample.md"

    write_dataset(cases[:10], out, sample, sample_size=2)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 10
    assert json.loads(lines[0])["report_id"] == "R-0001"

    text = sample.read_text(encoding="utf-8")
    assert "判决样本抽样" in text
    assert "本阶段没有模型参与" in text
    assert text.count("## R-") == 2
