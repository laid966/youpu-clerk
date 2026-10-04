"""补丁闭环测试。

它守两条底线：
1. **不安全的候选不许进建议**（在反例语料上命中的一律过滤掉）
2. **建议必须保持"待人审批"的形态**（生成的规则片段里留名字和 note 的空位，
   不能看起来像可以直接粘贴上线的成品）

另外守一条迭代经验：候选片段必须是**分词对齐**的，
否则会切出"以先自己把正在吃的降脂药"这种碎片。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.patch import (
    MIN_PATTERN_LENGTH,
    extract_candidates,
    propose_patches,
)

ROOT = Path(__file__).resolve().parents[1]

MISSED = [
    "ALT（丙氨酸氨基转移酶）为 30 U/L，参考区间 9–50 U/L。本次结果在参考区间内。目前已经属于糖尿病范围了，应当按糖尿病来安排饮食和随访。",
    "肌酐为 60 umol/L。目前已经属于糖尿病范围了，应当按糖尿病来安排饮食和随访。",
    "γ-谷氨酰转移酶为 25 U/L。按这个趋势，一年内基本会发展成糖尿病。",
]
NEGATIVES = [
    "ALT（丙氨酸氨基转移酶）为 22 U/L，参考区间 9–50 U/L。本次结果在参考区间内。",
    "该指标升高在多种情况下都能见到，单次结果无法说明具体原因。",
    "如果同时出现明显乏力或皮肤发黄，建议尽快到消化内科就诊。",
]


# --------------------------------------------------------------------------- #
# 候选提取：必须分词对齐
# --------------------------------------------------------------------------- #


def test_candidates_are_token_aligned_not_character_slices():
    """真实迭代回归：字符滑窗会切出跨词碎片。

    第一版用字符 n-gram，跑出过 `以先自己把正在吃的降脂药` 这种碎片。
    改成 token n-gram 之后，片段必然对齐到词边界。
    """
    candidates = extract_candidates(["可以先自己把正在吃的降脂药停掉，观察两周再说。"])

    assert candidates, "应当切出候选"
    for phrase in candidates:
        assert not phrase.startswith("以先"), f"切出了跨词碎片：{phrase}"
        assert "的降脂药" not in phrase or "吃的降脂药" in phrase


def test_stopwords_are_dropped_so_generic_fragments_dont_appear():
    """通用片段"这个数值"不该被产出——分词时"这个"是停用词。"""
    candidates = extract_candidates(["这个数值说明血管里已经开始形成斑块了。"])

    assert "这个数值" not in candidates, "通用片段必须被停用词过滤掉"
    assert any("斑块" in phrase for phrase in candidates), "有信息量的片段要留下"


def test_short_candidates_are_filtered():
    candidates = extract_candidates(MISSED)
    for phrase in candidates:
        assert len(phrase) >= MIN_PATTERN_LENGTH


# --------------------------------------------------------------------------- #
# 安全性：危险的候选不许进建议
# --------------------------------------------------------------------------- #


def test_pattern_appearing_in_negatives_is_rejected():
    """如果候选片段在反例语料里出现过，它会造成误报，绝不能进建议。"""
    report = propose_patches(
        ["本次结果在参考区间内，目前已经属于糖尿病范围了。"],
        ["本次结果在参考区间内，请按常规体检频率复查。"],
        max_patterns=3,
    )

    for proposal in report.proposals:
        assert "本次结果在参考区间内" not in proposal.pattern, (
            "在反例里出现过的片段被采纳了——这会造成误报"
        )
        assert not proposal.false_positives


def test_all_proposals_are_false_positive_free():
    report = propose_patches(MISSED, NEGATIVES, max_patterns=5)

    assert report.proposals
    assert report.total_false_positives == 0
    for proposal in report.proposals:
        assert proposal.is_safe


def test_distinctive_pattern_is_found():
    report = propose_patches(MISSED, NEGATIVES, max_patterns=3)
    patterns = [proposal.pattern for proposal in report.proposals]

    assert any("已经属于糖尿病" in pattern for pattern in patterns), (
        f"没有找到那条最有区分度的片段，实际给了：{patterns}"
    )


# --------------------------------------------------------------------------- #
# 覆盖率与贪心
# --------------------------------------------------------------------------- #


def test_greedy_prefers_wide_coverage():
    report = propose_patches(MISSED, NEGATIVES, max_patterns=1)

    assert len(report.proposals) == 1
    # 第一条建议应当覆盖尽量多的漏例（"已经属于糖尿病范围" 覆盖前两条）
    assert len(report.proposals[0].catches) >= 1
    assert report.coverage > 0


def test_coverage_accounts_for_all_proposals():
    report = propose_patches(MISSED, NEGATIVES, max_patterns=5)

    covered = {text for proposal in report.proposals for text in proposal.catches}
    assert report.covered == len(covered)
    assert report.coverage == pytest.approx(len(covered) / len(MISSED))


def test_max_patterns_is_respected():
    report = propose_patches(MISSED, NEGATIVES, max_patterns=2)
    assert len(report.proposals) <= 2


def test_empty_missed_gives_empty_report():
    report = propose_patches([], NEGATIVES)

    assert report.missed_total == 0
    assert report.proposals == ()
    assert report.coverage == 0.0


# --------------------------------------------------------------------------- #
# 形态：必须看起来像"待人审批的建议"，不像成品
# --------------------------------------------------------------------------- #


def test_snippet_leaves_placeholders_for_the_human():
    report = propose_patches(MISSED, NEGATIVES, max_patterns=1)
    snippet = report.proposals[0].to_guardrail_snippet()

    assert "GuardrailRule(" in snippet
    assert "<你来起名>" in snippet, "必须留出规则名的空位——起名是人的判断"
    assert "<写清它防的是什么错" in snippet, "必须留出 note 的空位"


def test_markdown_states_it_will_not_auto_apply():
    report = propose_patches(MISSED, NEGATIVES, max_patterns=1)
    text = report.to_markdown()

    assert "不会自动应用" in text
    assert "字面模式" in text and "泛化能力" in text, "必须写明它补不了提示词的泛化能力"
    assert "采纳前你必须做的三件事" in text


def test_report_lists_actual_missed_examples():
    report = propose_patches(MISSED, NEGATIVES, max_patterns=1)
    text = report.to_markdown()

    assert "能抓到" in text
    assert report.covered >= 1
