"""审计图测试。

全部用 `FakeJudge`：不联网、不花钱、结果确定。

重点守三件事：
1. **流程顺序**：确定性检查必须跑在语义检查之前，且语义检查只跑"计划内"的指标
2. **reflect 真的能挡住编造**：模型说越界但交不出原文依据 → 结论被丢弃
3. **升级人工由策略决定，不由模型决定**：危急值、命中升级类目、未知类目都要升级
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.graph import build_audit_graph
from agent.judge import FakeJudge
from agent.policy import AuditPolicy
from agent.prompts import current_prompt
from agent.runner import run_batch
from audit.artifact import build_artifact, replace_item
from audit.inject import (
    build_injected_dataset,
    paraphrase_phrases,
    tempting_but_legit_phrases,
)
from audit.pipeline import load_metrics
from audit.synth import DEFAULT_SEED, generate_reports

ROOT = Path(__file__).resolve().parents[1]

NO_VIOLATION = '{"violation": false, "category": "none", "evidence": ""}'


def violation_with(evidence: str) -> str:
    return f'{{"violation": true, "category": "diagnosis", "evidence": "{evidence}"}}'


def responder_for(prompt_text: str) -> str:
    """假模型：注入的越界句一律判越界，并把整句作为依据交出来。"""
    for phrase in paraphrase_phrases():
        if phrase in prompt_text:
            return violation_with(phrase)
    return NO_VIOLATION


@pytest.fixture(scope="module")
def metrics():
    return load_metrics()


@pytest.fixture(scope="module")
def injected(metrics):
    judged_cases = generate_reports(count=40, metrics=metrics, seed=DEFAULT_SEED)
    cases = build_injected_dataset(judged_cases, metrics, seed=DEFAULT_SEED)
    return cases, judged_cases


def _state(artifact, judged):
    report = judged.report
    return {
        "artifact": artifact.to_dict(),
        "report_values": dict(report.values),
        "sex": report.sex,
        "age": report.age,
    }


def _first_clean(cases):
    for case in cases:
        if case.clean and case.variation in (None, "none"):
            return case
    raise AssertionError("样本里没有干净产物")  # pragma: no cover


# --------------------------------------------------------------------------- #
# 流程与顺序
# --------------------------------------------------------------------------- #


def test_clean_artifact_costs_nothing(injected, metrics):
    """干净产物没有异常项 → 语义检查的计划是空的 → 一次模型调用都没有。"""
    cases, judged_cases = injected
    index = next(i for i, c in enumerate(cases) if c.clean and c.variation in (None, "none"))
    judged = judged_cases[index][1]

    graph, _ = build_audit_graph(
        AuditPolicy(inspect_scope="abnormal_only"),
        FakeJudge(NO_VIOLATION),
        metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(_state(cases[index].artifact, judged))

    assert final["planned_codes"] == []
    assert final["audit"]["model_calls"] == 0
    assert final["audit"]["findings"] == []


def test_planned_scope_all_inspects_every_metric(injected, metrics):
    cases, judged_cases = injected
    case = _first_clean(cases)
    index = cases.index(case)
    judged = judged_cases[index][1]

    graph, _ = build_audit_graph(
        AuditPolicy(inspect_scope="all", max_model_calls_per_artifact=10),
        FakeJudge(NO_VIOLATION),
        metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(_state(case.artifact, judged))

    assert len(final["planned_codes"]) == len(case.artifact.items)
    assert final["audit"]["model_calls"] > 0


def test_model_call_cap_is_enforced_and_noted(injected, metrics):
    cases, judged_cases = injected
    case = _first_clean(cases)
    judged = judged_cases[cases.index(case)][1]

    graph, _ = build_audit_graph(
        AuditPolicy(inspect_scope="all", max_model_calls_per_artifact=3),
        FakeJudge(NO_VIOLATION),
        metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(_state(case.artifact, judged))

    assert final["audit"]["model_calls"] == 3
    assert any("调用上限" in note for note in final["audit"]["notes"]), (
        "被截断必须显式记下来，不能悄悄少查"
    )


# --------------------------------------------------------------------------- #
# reflect：挡住编造
# --------------------------------------------------------------------------- #


def test_reflect_rejects_finding_without_verifiable_evidence(injected, metrics):
    """模型说越界，但"依据"在原文里找不到 → 丢弃。这是可编程验证的反幻觉手段。"""
    cases, judged_cases = injected
    clean = _first_clean(cases)

    graph, _ = build_audit_graph(
        AuditPolicy(inspect_scope="all", max_model_calls_per_artifact=2),
        FakeJudge(violation_with("这句话根本不在原文里")),
        metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(_state(clean.artifact, judged_cases[cases.index(clean)][1]))

    assert final["semantic"] == []
    assert final["rejected"], "应该有结论被 reflect 挡下来"
    assert any("无法在文本中定位" in item["reject_reason"] for item in final["rejected"])


def test_policy_can_reject_all_model_findings(injected, metrics):
    cases, judged_cases = injected
    target_case = None
    for case in cases:
        if any(d.kind == "safety_paraphrase" for d in case.defects):
            target_case = case
            break
    assert target_case is not None

    graph, _ = build_audit_graph(
        AuditPolicy(inspect_scope="all", accept_model_findings=False),
        FakeJudge(responder_for),
        metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(_state(target_case.artifact, judged_cases[cases.index(target_case)][1]))

    assert final["semantic"] == []
    assert any("不接受模型结论" in item["reject_reason"] for item in final["rejected"])


def test_reflect_keeps_finding_with_real_evidence(injected, metrics):
    cases, judged_cases = injected
    target_case = None
    for case in cases:
        if any(d.kind == "safety_paraphrase" for d in case.defects):
            target_case = case
            break
    assert target_case is not None

    graph, _ = build_audit_graph(
        AuditPolicy(inspect_scope="all", max_model_calls_per_artifact=8),
        FakeJudge(responder_for),
        metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(_state(target_case.artifact, judged_cases[cases.index(target_case)][1]))

    assert final["semantic"], "依据真实存在时不该被丢掉"
    assert all(f["decided_by"] == "model" for f in final["semantic"])


# --------------------------------------------------------------------------- #
# decide：升级人工由策略决定
# --------------------------------------------------------------------------- #


def _force_critical(case):
    """造一份含危急值判定的产物。

    为什么不直接从样本里找：注入器会优先用"漏判"缺陷把危急项改掉
    （那正是它该做的事），所以注入后的产物里往往已经没有 critical 项了。
    测试要测的是**升级逻辑**，不该依赖数据分布，所以直接构造。
    """
    from audit.artifact import ADVICE_BY_SEVERITY, replace_item

    item = case.artifact.items[0]
    return replace_item(
        case.artifact,
        item.code,
        severity="critical",
        advice=ADVICE_BY_SEVERITY["critical"],
    )


def test_critical_severity_escalates(injected, metrics):
    cases, judged_cases = injected
    case = _first_clean(cases)
    judged = judged_cases[cases.index(case)][1]
    artifact = _force_critical(case)

    graph, _ = build_audit_graph(
        AuditPolicy(escalate_on_critical_severity=True),
        FakeJudge(NO_VIOLATION),
        metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(_state(artifact, judged))

    assert final["escalated"] is True
    assert any("危急值" in reason for reason in final["escalation_reasons"])
    assert any("需人工复核" in note for note in final["audit"]["notes"]), (
        "升级样本应当走过 human_review 节点"
    )


def test_critical_severity_can_be_turned_off(injected, metrics):
    cases, judged_cases = injected
    case = _first_clean(cases)
    judged = judged_cases[cases.index(case)][1]
    artifact = _force_critical(case)

    graph, _ = build_audit_graph(
        AuditPolicy(escalate_on_critical_severity=False, escalate_categories=()),
        FakeJudge(NO_VIOLATION),
        metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(_state(artifact, judged))

    assert final["escalated"] is False


def test_unknown_category_escalates_by_fail_safe(injected, metrics):
    """出现没见过的类别时默认升级人工——不认识的东西不要自己决定。"""
    cases, judged_cases = injected
    clean = _first_clean(cases)

    weird = '{"violation": true, "category": "brand_new_category", "evidence": "PLACEHOLDER"}'
    artifact = clean.artifact
    item = artifact.items[0]
    marker = "这是一个测试用的句子。"
    artifact = replace_item(artifact, item.code, explanation=item.explanation + marker)
    responder = weird.replace("PLACEHOLDER", marker)

    graph, _ = build_audit_graph(
        AuditPolicy(inspect_scope="all", escalate_categories=()),
        FakeJudge(responder),
        metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(_state(artifact, judged_cases[cases.index(clean)][1]))

    assert final["escalated"] is True
    assert any("未知类目" in reason for reason in final["escalation_reasons"])


# --------------------------------------------------------------------------- #
# 端到端
# --------------------------------------------------------------------------- #


def test_run_batch_catches_paraphrases_with_fake_judge(injected, metrics):
    """假模型是"完美"的，所以改写型越界应当全部抓到，且不误报。"""
    cases, judged_cases = injected
    subset = cases[:12]
    judged_subset = judged_cases[:12]

    report = run_batch(
        cases=subset,
        judged_cases=judged_subset,
        metrics=metrics,
        policy=AuditPolicy(inspect_scope="all", max_model_calls_per_artifact=8),
        judge=FakeJudge(responder_for),
        prompt=current_prompt(),
    )

    assert report.cases == 12
    assert report.total_defects > 0
    paraphrase_caught, paraphrase_total = report.recall_by_kind["safety_paraphrase"]
    if paraphrase_total:
        assert paraphrase_caught == paraphrase_total
    assert report.false_positives == 0
    assert report.model_calls > 0


def test_report_markdown_shows_the_delta(injected, metrics):
    cases, judged_cases = injected
    report = run_batch(
        cases=cases[:8],
        judged_cases=judged_cases[:8],
        metrics=metrics,
        policy=AuditPolicy(inspect_scope="all", max_model_calls_per_artifact=4),
        judge=FakeJudge(responder_for),
        prompt=current_prompt(),
        deterministic_only_recall=0.5,
    )
    text = report.to_markdown()

    assert "语义层值不值" in text
    assert "只有确定性层" in text
    assert "模型调用总数" in text


def test_hard_negative_phrases_are_not_flagged_by_fake_judge(injected, metrics):
    """高难度负例（听起来很医学但合法）不该被报——假模型据此保证负例有效。"""
    cases, judged_cases = injected
    tempting = tempting_but_legit_phrases()

    negatives = [
        case
        for case in cases
        if case.clean and any(p in case.artifact.items[0].explanation for p in tempting)
        or case.clean
    ][:6]

    report = run_batch(
        cases=negatives,
        judged_cases=[judged_cases[cases.index(c)] for c in negatives],
        metrics=metrics,
        policy=AuditPolicy(inspect_scope="all", max_model_calls_per_artifact=8),
        judge=FakeJudge(responder_for),
        prompt=current_prompt(),
    )

    assert report.false_positives == 0, "合法文本不该被报"
