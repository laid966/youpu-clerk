"""缺陷注入器测试。

这个文件里最重要的一组用例是 **「标准答案必须与产物真的对得上」**：
如果基准自己错了（说埋了缺陷、实际没埋，或埋的与记录的不一致），
那后面算出来的召回率、误报率全都是假的。

所以每条断言都直接用**独立的 oracle 重算**来核对，而不是信任注入器的自述。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from audit.artifact import ADVICE_BY_SEVERITY, SAFETY_TERMS, build_artifact
from audit.inject import (
    CLEAN_SHARE,
    DEFECT_KINDS,
    DEFECT_COUNT_WEIGHTS,
    LEGITIMATE_VARIATIONS,
    build_injected_dataset,
    capability_report,
    to_json_line,
    write_dataset,
)
from audit.pipeline import judge_metric, known_citations, load_metrics
from audit.synth import DEFAULT_SEED, generate_reports

ROOT = Path(__file__).resolve().parents[1]
COUNT = 200


@pytest.fixture(scope="module")
def metrics():
    return load_metrics()


@pytest.fixture(scope="module")
def judged_cases(metrics):
    return generate_reports(count=COUNT, metrics=metrics, seed=DEFAULT_SEED)


@pytest.fixture(scope="module")
def cases(judged_cases, metrics):
    return build_injected_dataset(judged_cases, metrics, seed=DEFAULT_SEED)


# --------------------------------------------------------------------------- #
# 基准的形状
# --------------------------------------------------------------------------- #


def test_clean_share_is_exact(cases):
    """干净样本是误报率的分母，比例必须精确。"""
    clean = sum(1 for case in cases if case.clean)
    assert clean == round(COUNT * CLEAN_SHARE) == 80


def test_defect_count_distribution_matches_plan(cases):
    counts = Counter(len(case.defects) for case in cases)
    non_clean = COUNT - round(COUNT * CLEAN_SHARE)
    expected = {n: round(non_clean * w) for n, w in DEFECT_COUNT_WEIGHTS.items()}
    # 余数补齐后会有一个类型多一条，允许 1 的误差
    for n, want in expected.items():
        assert abs(counts.get(n, 0) - want) <= 1, f"{n} 条缺陷：期望约 {want}，实际 {counts[n]}"
    assert counts.get(0, 0) == 80


def test_all_kinds_are_present(cases):
    kinds = {defect.kind for case in cases for defect in case.defects}
    assert kinds == set(DEFECT_KINDS), f"缺失类型：{set(DEFECT_KINDS) - kinds}"


def test_paraphrased_safety_violations_avoid_the_banned_word_list(cases):
    """改写型越界必须**真的绕开禁用词表**，否则它就和普通越界没区别，
    "为什么还需要语义检查"这个问题也就没有证据了。"""
    from audit.artifact import SAFETY_TERMS

    paraphrases = [
        defect
        for case in cases
        for defect in case.defects
        if defect.kind == "safety_paraphrase"
    ]
    assert paraphrases, "应当注入改写型越界"
    for defect in paraphrases:
        hits = [term for term in SAFETY_TERMS if term in defect.observed]
        assert hits == [], f"改写型越界里不该出现禁用词，实际命中：{hits}"


def test_paraphrased_safety_violation_requires_semantic_check(cases):
    """它的可检测性契约必须是语义检查——确定性词表抓不到它。"""
    for case in cases:
        for defect in case.defects:
            if defect.kind == "safety_paraphrase":
                assert defect.expected_detector == "semantic_check"


def test_scarce_kinds_reach_their_ceiling(cases, judged_cases, metrics):
    """稀缺机会必须被吃满——这是基准有没有意义的关键。

    真实问题回归：漏判（missed_critical）只在 10 份危急档案上可注入，
    而第一版实现因为"槽位随机分配 + 配额随机挑选"只注入了 1 条、第二版 5 条，
    「漏判召回率」这个指标因此毫无意义。
    """
    ceiling = capability_report(judged_cases, metrics, seed=DEFAULT_SEED)
    actual = Counter(defect.kind for case in cases for defect in case.defects)

    assert ceiling["missed_critical"] == 10
    assert actual["missed_critical"] == ceiling["missed_critical"], "漏判的机会必须全部用掉"

    # 降级的上限是 30，但实际拿到 20 左右——这是**结构性结果，不是缺陷**：
    # 漏判与降级争抢同一批指标（只有危急/明显异常项才能降级），
    # 而"一个指标最多一条缺陷"意味着优先级更高的漏判先拿走危急项。
    # 门槛设成"足够让单类召回率有意义"的量级（≥15 条），而不是强行逼近上限。
    assert actual["downgraded"] >= 15, (
        f"降级的注入量 {actual['downgraded']} 太少（上限 {ceiling['downgraded']}），"
        "单类召回率会失去意义"
    )


def test_no_two_defects_share_the_same_item(cases):
    """一个指标最多一条缺陷。

    真实 bug 回归：第一版允许两条缺陷落在同一指标上，
    先注入的漏判记录写的是 critical→normal，后注入的算子又把该指标改成 marked，
    **标准答案当场失真**——基准自述与实际不符，召回率就是假的。
    """
    for case in cases:
        targets = [defect.target for defect in case.defects]
        assert len(targets) == len(set(targets)), (
            f"{case.case_id} 有两条缺陷落在同一指标上：{targets}"
        )


def test_oracle_dependent_kinds_are_well_represented(cases):
    """三类"只有 oracle 重算才能发现"的缺陷必须占到有意义的比例。"""
    total = sum(len(case.defects) for case in cases)
    oracle_kinds = {"missed_critical", "downgraded", "wrong_sex_threshold"}
    oracle_defects = sum(
        1 for case in cases for defect in case.defects if defect.kind in oracle_kinds
    )
    assert oracle_defects / total >= 0.25, (
        f"oracle 类缺陷只占 {oracle_defects / total:.1%}，基准会偏向简单检查"
    )


def test_no_duplicate_kind_within_one_case(cases):
    for case in cases:
        kinds = [defect.kind for defect in case.defects]
        assert len(kinds) == len(set(kinds)), f"{case.case_id} 里同一类型注入了多次"


def test_only_expected_detectors_are_used(cases):
    allowed = {
        "oracle_differential",
        "value_consistency",
        "unit_consistency",
        "citation_existence",
        "advice_contract",
        "safety_terms",
        "semantic_check",
    }
    for case in cases:
        for defect in case.defects:
            assert defect.expected_detector in allowed


# --------------------------------------------------------------------------- #
# 标准答案必须与产物真的对得上（最重要的一组）
# --------------------------------------------------------------------------- #


def test_clean_cases_are_untouched_or_legitimately_varied(judged_cases, cases, metrics):
    """干净样本要么原封不动，要么只带一个**合法变体**（hard negative）。

    合法变体（显示取整 / 引用顺序调换 / 引用重复）不构成缺陷，
    它们是用来给误报率加难度的——没有它们，确定性检查器在干净样本上一条都不会报，
    误报率永远是 0，而**那个 0 是假的**：它只说明测试没难度。
    """
    for (_profile, judged), case in zip(judged_cases, cases):
        if not case.clean:
            continue
        original = build_artifact(judged, metrics)
        if case.variation in (None, "none"):
            assert case.artifact == original, f"{case.case_id} 没有变体却被改动了"
        else:
            assert case.variation in LEGITIMATE_VARIATIONS
            assert case.artifact != original, f"{case.case_id} 标了变体却没有任何改动"


def test_hard_negatives_exist(cases):
    """合法变体必须真的存在，否则误报率的测试没有难度。"""
    varied = [case for case in cases if case.clean and case.variation not in (None, "none")]
    assert len(varied) >= 10, f"合法变体样本太少：{len(varied)}"


def test_every_recorded_defect_actually_exists(judged_cases, cases, metrics):
    """逐条核对：记录里说埋了什么，产物里就必须真是什么。"""
    known = known_citations(metrics)
    by_code = {metric.code: metric for metric in metrics}
    other_sex = {"male": "female", "female": "male"}

    checked = 0
    for (_profile, judged), case in zip(judged_cases, cases):
        sex = judged.report.sex
        age = judged.report.age
        for defect in case.defects:
            item = case.artifact.item(defect.target)
            metric = by_code[defect.target]
            oracle = judge_metric(metric, sex, age, float(judged.report.values[defect.target]))
            checked += 1

            if defect.kind == "missed_critical":
                assert oracle["final_verdict"] == "critical"
                assert item.severity == "normal"

            elif defect.kind == "downgraded":
                assert oracle["final_verdict"] != item.severity
                assert severity_position(oracle["final_verdict"]) > severity_position(
                    item.severity
                )

            elif defect.kind == "wrong_sex_threshold":
                flipped = judge_metric(
                    metric, other_sex[sex], age, float(judged.report.values[defect.target])
                )["final_verdict"]
                assert item.severity == flipped, "等级应当等于异性阈值下的结论"
                assert item.severity != oracle["final_verdict"], "两者本应不同，否则不构成缺陷"

            elif defect.kind == "value_mismatch":
                assert item.value != float(judged.report.values[defect.target])

            elif defect.kind == "unit_mismatch":
                assert item.unit != metric.unit

            elif defect.kind == "fabricated_citation":
                assert any(cite not in known for cite in item.citations)

            elif defect.kind == "internal_contradiction":
                assert item.advice != ADVICE_BY_SEVERITY[item.severity]

            elif defect.kind == "safety_violation":
                assert any(term in item.explanation for term in SAFETY_TERMS)

            elif defect.kind == "safety_paraphrase":
                # 改写型越界：必须真的存在于文本里，而且**不能**被词表抓到。
                # 后者是关键——如果词表能抓，它就不是"改写型"，也就不能证明语义检查的必要性。
                assert defect.observed in item.explanation
                assert not any(term in item.explanation for term in SAFETY_TERMS), (
                    f"改写型越界被词表抓到了，说明短语里混进了禁用词：{defect.observed}"
                )

            else:  # pragma: no cover
                pytest.fail(f"未知缺陷类型：{defect.kind}")

    assert checked == sum(len(case.defects) for case in cases)


def severity_position(verdict: str) -> int:
    order = ["normal", "mild", "marked", "critical"]
    return order.index(verdict) if verdict in order else -1


def test_ground_truth_is_self_consistent_with_counts(cases):
    for case in cases:
        payload = case.to_dict()
        assert payload["defect_count"] == len(case.defects)
        assert payload["clean"] == (not case.defects)


# --------------------------------------------------------------------------- #
# 可复现与落盘
# --------------------------------------------------------------------------- #


def test_same_seed_is_byte_identical(judged_cases, metrics):
    first = build_injected_dataset(judged_cases[:60], metrics, seed=DEFAULT_SEED)
    second = build_injected_dataset(judged_cases[:60], metrics, seed=DEFAULT_SEED)
    assert [to_json_line(c) for c in first] == [to_json_line(c) for c in second]


def test_write_dataset_outputs_jsonl_and_sample(tmp_path, cases):
    out = tmp_path / "injected.jsonl"
    sample = tmp_path / "injected.sample.md"

    write_dataset(cases[:12], out, sample, sample_size=2)

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 12
    payload = json.loads(lines[0])
    assert {"case_id", "clean", "artifact", "defects"} <= set(payload)

    text = sample.read_text(encoding="utf-8")
    assert "标准答案" in text
    assert "误报率" in text, "抽样说明里必须点明干净样本是用来测误报的"
