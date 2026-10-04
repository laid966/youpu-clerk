"""统计置信测试。

这个模块算的是"样本量够不够"的依据，**算错了整个结论就错了**。

验证方式：不抄自己算出来的数，而是拿**定义式反代**——
比如"下界"的定义是"真实率取这个值时，观测到 k 次成功的概率恰好是 α"，
那就把这个下界代回二项分布，看它是不是等于 α。
"""

from __future__ import annotations

import pytest

from audit.stats import (
    binomial_cdf,
    lower_bound,
    proof_lines,
    required_zero_failure_sample,
    upper_bound,
)


# --------------------------------------------------------------------------- #
# 二项分布
# --------------------------------------------------------------------------- #


def test_binomial_cdf_known_values():
    # 抛 2 次硬币，正面数 ≤ 1 的概率 = 0.75
    assert binomial_cdf(1, 2, 0.5) == pytest.approx(0.75)
    # 抛 10 次，≤ 9 次的概率 = 1 - 2^-10
    assert binomial_cdf(9, 10, 0.5) == pytest.approx(1 - 2**-10)
    assert binomial_cdf(0, 10, 0.0) == pytest.approx(1.0)


def test_binomial_cdf_monotone_in_p():
    assert binomial_cdf(3, 10, 0.2) > binomial_cdf(3, 10, 0.5) > binomial_cdf(3, 10, 0.8)


# --------------------------------------------------------------------------- #
# 下界：定义式反代
# --------------------------------------------------------------------------- #


def test_lower_bound_satisfies_its_definition():
    """下界的定义：真实率取下界时，观测到 ≥k 次成功的概率恰好是 α。"""
    for successes, trials in ((20, 24), (48, 60), (9, 12), (95, 100)):
        bound = lower_bound(successes, trials)
        tail = 1 - binomial_cdf(successes - 1, trials, bound)
        assert tail == pytest.approx(0.05, abs=1e-4), (
            f"{successes}/{trials} 的下界 {bound:.4f} 反代回去是 {tail:.4f}，不是 0.05"
        )


def test_lower_bound_closed_form_when_perfect():
    """全对时的闭式解：(1-置信度)^(1/n)。"""
    assert lower_bound(24, 24) == pytest.approx(0.05 ** (1 / 24))
    assert lower_bound(60, 60) == pytest.approx(0.05 ** (1 / 60))

    # 这两行是回答"24 条够不够"的核心数字
    assert lower_bound(24, 24) == pytest.approx(0.8827, abs=5e-4)
    assert lower_bound(60, 60) == pytest.approx(0.9513, abs=5e-4)


def test_lower_bound_increases_with_more_successes():
    assert lower_bound(20, 24) < lower_bound(24, 24)
    assert lower_bound(0, 24) == 0.0


# --------------------------------------------------------------------------- #
# 上界：读"零误报"
# --------------------------------------------------------------------------- #


def test_upper_bound_zero_failures_closed_form():
    """零误报时的上界：1 - (1-置信度)^(1/n)。

    这一条是回答"20 条零误报能说明什么"的核心：
    **只能说真实误报率不超过 13.9%。**
    """
    assert upper_bound(0, 20) == pytest.approx(1 - 0.05 ** (1 / 20))
    assert upper_bound(0, 20) == pytest.approx(0.1391, abs=5e-4)
    assert upper_bound(0, 60) == pytest.approx(0.0487, abs=5e-4)


def test_upper_bound_satisfies_its_definition():
    for successes, trials in ((3, 40), (0, 20), (7, 60)):
        bound = upper_bound(successes, trials)
        assert binomial_cdf(successes, trials, bound) == pytest.approx(0.05, abs=1e-4)


def test_more_samples_tighten_the_bound():
    """样本越多，区间越紧——这正是"为什么要加样本"。"""
    assert upper_bound(0, 200) < upper_bound(0, 20)
    assert lower_bound(200, 200) > lower_bound(20, 20)


# --------------------------------------------------------------------------- #
# 需要多少样本
# --------------------------------------------------------------------------- #


def test_required_sample_size_matches_the_table():
    assert required_zero_failure_sample(0.90) == 29
    assert required_zero_failure_sample(0.95) == 59
    assert required_zero_failure_sample(0.98) == 149
    assert required_zero_failure_sample(0.99) == 299


def test_required_sample_size_is_consistent_with_lower_bound():
    """自洽性：按这张表取的样本量，恰好能声称那个目标。"""
    for target in (0.90, 0.95, 0.99):
        need = required_zero_failure_sample(target)
        assert lower_bound(need, need) >= target
        assert lower_bound(need - 1, need - 1) < target


def test_required_sample_size_rejects_bad_target():
    with pytest.raises(ValueError):
        required_zero_failure_sample(1.5)
    with pytest.raises(ValueError):
        required_zero_failure_sample(0.0)


# --------------------------------------------------------------------------- #
# 报告段落
# --------------------------------------------------------------------------- #


def test_proof_lines_says_what_24_cannot_prove():
    """24 条全对**不能**声称 ≥95%——报告必须把这件事写出来。"""
    text = "\n".join(proof_lines(positives=24, caught=24, negatives=20, false_positives=0))

    assert "≥ 88.3%" in text
    assert "≤ 13.9%" in text
    assert "**还不能**声称 ≥95%" in text
    assert "需要 24 → 59 条正例" in text
    assert "还不能" in text and "≤5%" in text


def test_proof_lines_confirms_when_enough():
    text = "\n".join(
        proof_lines(positives=60, caught=60, negatives=60, false_positives=0)
    )
    assert "✅ 已经能声称 ≥95%" in text
    assert "✅ 已经能声称 ≤5%" in text


def test_proof_lines_handles_empty_sets():
    text = "\n".join(proof_lines(positives=0, caught=0, negatives=0, false_positives=0))
    assert "正例 0 条，什么都证明不了" in text
    assert "负例 0 条，什么都证明不了" in text
