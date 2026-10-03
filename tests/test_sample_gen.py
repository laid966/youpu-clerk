"""`engine/sample_gen.py` 的测试。

这个生成器是"上千条评测用例"的来源，所以它自己必须可复现、覆盖到位、答案自洽。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.adjudicate import adjudicate
from engine.domain import load_domain
from engine.sample_gen import DEFAULT_SEED, TEMPLATES, generate_cases, write_dataset

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def airline():
    return load_domain(ROOT / "domain" / "airline-fare-sample" / "domain.yaml")


@pytest.fixture(scope="module")
def cases(airline):
    return generate_cases(airline, count=400, seed=DEFAULT_SEED)


def test_generates_exact_count(cases):
    assert len(cases) == 400


def test_case_ids_are_unique_and_ordered(cases):
    ids = [case.id for case in cases]
    assert len(set(ids)) == len(ids)
    assert ids[0] == "case-0001"
    assert ids[-1] == "case-0400"


def test_same_seed_gives_byte_identical_output(airline, cases):
    """可复现性：同一个 seed 必须产出完全一样的数据集，否则"基线对比"没有意义。"""
    again = generate_cases(airline, count=400, seed=DEFAULT_SEED)
    assert [c.to_json_line() for c in again] == [c.to_json_line() for c in cases]


def test_different_seed_gives_different_output(airline):
    other = generate_cases(airline, count=400, seed=DEFAULT_SEED + 1)
    baseline = generate_cases(airline, count=400, seed=DEFAULT_SEED)
    assert [c.to_json_line() for c in other] != [c.to_json_line() for c in baseline]


def test_every_template_is_exercised(cases):
    used = {case.template for case in cases}
    assert used == set(TEMPLATES), f"未被覆盖的模板：{set(TEMPLATES) - used}"


def test_expected_answers_come_from_the_engine(cases, airline):
    """逐条回算：数据集里的标准答案必须与引擎当前输出一致（防止生成过程本身有 bug）。"""
    for case in cases:
        recomputed = adjudicate(airline, dict(case.facts)).to_dict()
        assert dict(case.expected) == recomputed, f"{case.id} 的标准答案与引擎不一致"


def test_fee_amount_is_string_or_none(cases):
    for case in cases:
        value = case.expected["fee_amount"]
        assert value is None or isinstance(value, str), f"{case.id}: {type(value).__name__}"


def test_missing_fact_template_actually_omits_a_fact(cases, airline):
    missing_cases = [case for case in cases if case.template == "missing_fact"]
    assert missing_cases, "应当生成缺字段样本"
    for case in missing_cases:
        assert len(case.facts) < len(airline.facts), f"{case.id} 并没有真的缺字段"
        assert case.expected["missing_facts"], f"{case.id} 缺字段却没被标出来"
        assert case.expected["final_verdict"] == "needs_review"


def test_threshold_sweep_covers_just_below_and_above_every_boundary(cases):
    """生成器最有价值的地方：必须造出"刚好差一点"和"刚好超一点"的取值。

    R-002 的条件是 `hours_before_departure >= 48`。如果评测集里只有 48 而没有 47.99，
    那么把 `>=` 误写成 `>` 这种 bug 永远不会被发现。

    注意：这里断言的是**完备覆盖**，不是"抽到了"。阈值扫描刻意不依赖随机。
    """
    swept = [
        case.facts["hours_before_departure"]
        for case in cases
        if case.template == "threshold_sweep" and "hours_before_departure" in case.facts
    ]

    for boundary in (24, 48, 168, 336):
        assert boundary in swept, f"缺少恰好等于阈值 {boundary} 的样本"
        assert any(boundary - 0.01 <= value < boundary for value in swept), (
            f"缺少略低于阈值 {boundary} 的样本"
        )
        assert any(boundary < value <= boundary + 0.01 for value in swept), (
            f"缺少略高于阈值 {boundary} 的样本"
        )


def test_threshold_sweep_starts_the_dataset(cases):
    """阈值扫描必须排在最前，这样即使只生成很少的用例，边界也已覆盖。"""
    assert cases[0].template == "threshold_sweep"


def test_dataset_exercises_escalation(cases):
    escalated = [case for case in cases if case.expected["escalated"]]
    assert escalated, "数据集必须覆盖转人工路径，否则安全边界等于没测"
    reasons = {reason for case in escalated for reason in case.expected["escalate_reasons"]}
    assert len(reasons) >= 3, f"转人工原因太单调：{reasons}"


def test_dataset_covers_all_three_outcome_kinds(cases):
    final = {case.expected["final_verdict"] for case in cases}
    assert {"refundable", "not_refundable", "needs_review"} <= final


def test_write_dataset_creates_jsonl_and_human_sample(tmp_path, cases):
    out = tmp_path / "dataset.jsonl"
    sample = tmp_path / "dataset.sample.md"

    write_dataset(cases, out, sample, sample_size=5)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(cases)

    payload = json.loads(lines[0])
    assert set(payload) == {"id", "domain", "template", "facts", "expected"}

    text = sample.read_text(encoding="utf-8")
    assert "评测用例抽样" in text
    assert text.count("## case-") == 5


def test_university_domain_generates_cases_without_money():
    domain = load_domain(ROOT / "domain" / "university-credit-sample" / "domain.yaml")
    generated = generate_cases(domain, count=300, seed=DEFAULT_SEED)

    assert len(generated) == 300
    assert all(case.expected["fee_amount"] is None for case in generated)
    assert any(case.expected["final_verdict"] == "eligible" for case in generated), (
        "多条件与（AND）的规则在随机取样下几乎撞不上，"
        "必须靠 rule_positive 定向补正例，否则「规则算得对」这件事在数据集里没有正例可查"
    )
    assert any(case.expected["final_verdict"] == "not_eligible" for case in generated)


def test_rule_positive_template_appears_for_every_rule(cases, airline):
    """每条规则都应该至少有一个正例在数据集里。"""
    positive_rule_ids = set()
    for case in cases:
        if case.template != "rule_positive":
            continue
        recomputed = adjudicate(airline, dict(case.facts))
        positive_rule_ids |= {match.id for match in recomputed.matched_rules}

    expected = {rule.id for rule in airline.rules}
    assert expected <= positive_rule_ids, f"缺少正例的规则：{sorted(expected - positive_rule_ids)}"
