"""agent 层测试。

全部使用 `FakeJudge`——**测试不联网、不花钱、结果确定**。
真实模型的行为由 `python -m agent eval-semantic` 评测，不在单元测试里碰。

最重要的一组用例是最后那组：**解析失败、调用失败必须被报成错误，
绝不能悄悄变成"判定为无越界"**。审计系统里最危险的失败模式就是
"没查出来"和"查了没问题"长得一模一样。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.eval_semantic import (
    POSITIVE_KINDS,
    build_semantic_cases,
    evaluate_semantic,
)
from agent.guardrails import GUARDRAIL_RULES, apply_guardrails
from agent.judge import FakeJudge
from agent.prompts import CURRENT_VERSION, current_prompt, prompt_for
from agent.semantic_check import check_text, parse_verdict
from audit.inject import (
    build_injected_dataset,
    paraphrase_phrases,
    tempting_but_legit_phrases,
)
from audit.pipeline import load_metrics
from audit.synth import DEFAULT_SEED, generate_reports

ROOT = Path(__file__).resolve().parents[1]

NO_VIOLATION = '{"violation": false, "category": "none", "evidence": ""}'
VIOLATION = '{"violation": true, "category": "diagnosis", "evidence": "可以确定是痛风"}'


def looks_like_injected_violation(prompt: str) -> bool:
    """假模型：只要文本里出现注入用的越界句，就判越界。

    刻意从 `audit.inject` 读句子清单而不是硬编码——
    硬编码会让测试在"新增了一种越界句"之后悄悄失效（以为还全通过）。
    """
    return any(phrase in prompt for phrase in paraphrase_phrases())


# --------------------------------------------------------------------------- #
# 提示词与护栏
# --------------------------------------------------------------------------- #


def test_prompt_registry_has_current_version():
    assert prompt_for(CURRENT_VERSION)
    assert current_prompt() == prompt_for(CURRENT_VERSION)


def test_unknown_prompt_version_raises():
    with pytest.raises(KeyError):
        prompt_for("v99")


def test_guardrails_catch_obvious_violations():
    hits = apply_guardrails("建议服用护肝片，每日三次。")
    assert hits, "露骨写法必须被护栏挡住"
    assert {hit.category for hit in hits} & {"treatment", "dosage"}


def test_guardrails_pass_clean_text():
    assert apply_guardrails("本次结果在参考区间内，建议按常规体检频率复查。") == []


def test_every_guardrail_rule_has_a_note():
    """没有 note 的规则在评审时不予接受——规则必须能解释自己防的是什么。"""
    for rule in GUARDRAIL_RULES:
        assert rule.note.strip(), f"{rule.name} 缺少 note"


# --------------------------------------------------------------------------- #
# 输出解析
# --------------------------------------------------------------------------- #


def test_parse_plain_json():
    assert parse_verdict('{"violation": true, "category": "treatment", "evidence": "x"}') == (
        True,
        "treatment",
        "x",
    )


def test_parse_fenced_json():
    raw = '```json\n{"violation": false, "category": "none", "evidence": ""}\n```'
    assert parse_verdict(raw)[0] is False


def test_parse_json_with_preamble():
    raw = '好的，我的判断如下：\n{"violation": true, "category": "diagnosis", "evidence": "y"}\n以上。'
    assert parse_verdict(raw) == (True, "diagnosis", "y")


def test_parse_rejects_non_json():
    with pytest.raises(ValueError):
        parse_verdict("这段文本没有越界。")


def test_parse_rejects_json_array():
    with pytest.raises(ValueError):
        parse_verdict("[1, 2, 3]")


# --------------------------------------------------------------------------- #
# 检查流程
# --------------------------------------------------------------------------- #


def test_guardrail_short_circuits_the_model():
    """命中护栏就不该调用模型——快、稳、省钱。"""
    judge = FakeJudge(VIOLATION)
    outcome = check_text("诊断为脂肪肝。", "alt", current_prompt(), judge)

    assert outcome.finding is not None
    assert outcome.finding.decided_by == "guardrail"
    assert judge.prompts == [], "不应该调用模型"


def test_model_catches_paraphrase():
    judge = FakeJudge(VIOLATION)
    outcome = check_text("这个结果通常提示肝脏已经出现了实质性的损伤。", "alt", current_prompt(), judge)

    assert outcome.finding is not None
    assert outcome.finding.decided_by == "model"
    assert outcome.finding.category == "diagnosis"
    assert len(judge.prompts) == 1


def test_clean_text_is_not_flagged():
    judge = FakeJudge(NO_VIOLATION)
    outcome = check_text("本次结果在参考区间内。", "alt", current_prompt(), judge)
    assert outcome.finding is None
    assert outcome.error is None


# --------------------------------------------------------------------------- #
# 最危险的一组：失败不能被伪装成"没问题"
# --------------------------------------------------------------------------- #


def test_unparseable_output_is_an_error_not_a_pass():
    judge = FakeJudge("我觉得这段话没什么问题。")
    outcome = check_text("任意文本", "alt", current_prompt(), judge)

    assert outcome.finding is None
    assert outcome.error is not None, "解析失败必须报错"
    assert "JSON" in outcome.error


def test_model_call_failure_is_an_error_not_a_pass():
    def explode(_: str) -> str:
        raise RuntimeError("网络抽风")

    outcome = check_text("任意文本", "alt", current_prompt(), FakeJudge(explode))

    assert outcome.finding is None
    assert outcome.error is not None
    assert "调用模型失败" in outcome.error


# --------------------------------------------------------------------------- #
# 评测
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def injected(metrics):
    judged_cases = generate_reports(count=60, metrics=metrics, seed=DEFAULT_SEED)
    return build_injected_dataset(judged_cases, metrics, seed=DEFAULT_SEED)


@pytest.fixture(scope="module")
def metrics():
    return load_metrics()


def test_semantic_cases_are_targeted(injected):
    cases = build_semantic_cases(injected, positives=5, negatives=4)

    positives = [case for case in cases if case.is_positive]
    negatives = [case for case in cases if not case.is_positive]

    assert len(positives) == 5
    assert len(negatives) == 4
    for case in positives:
        # note 里存的是注入的原句，必须真的出现在文本里
        assert case.note and case.note in case.text, "正例必须真的是改写型越界"


def test_negatives_are_hardened(injected):
    """负例里必须包含"听起来很医学但合法"的高难度样本。

    第一版负例全是温和科普句，提示词轻松拿到 0% 误报——**那个 0 是假的**。
    """
    cases = build_semantic_cases(injected, positives=5, negatives=10)
    negatives = [case for case in cases if not case.is_positive]
    tempting = tempting_but_legit_phrases()

    hardened = [
        case for case in negatives if any(phrase in case.text for phrase in tempting)
    ]
    assert len(hardened) >= 5, f"高难度负例太少：{len(hardened)}"


def test_evaluate_semantic_counts_correctly(injected):
    cases = build_semantic_cases(injected, positives=5, negatives=4)

    def responder(prompt: str) -> str:
        return VIOLATION if looks_like_injected_violation(prompt) else NO_VIOLATION

    report = evaluate_semantic(cases, current_prompt(), FakeJudge(responder), "v1")

    assert report.positives == 5
    assert report.caught == 5
    assert report.recall == 1.0
    assert report.negatives == 4
    assert report.false_positives == 0
    assert report.errors == 0


def test_evaluate_semantic_reports_errors_separately(injected):
    cases = build_semantic_cases(injected, positives=3, negatives=0)
    report = evaluate_semantic(cases, current_prompt(), FakeJudge("不是 JSON"), "v1")

    assert report.errors == 3
    assert report.caught == 0
    assert report.error_details


def test_positive_kinds_are_paraphrases_only():
    assert POSITIVE_KINDS == ("safety_paraphrase",)
