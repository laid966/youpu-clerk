"""不变量：**这个文件是变异测试的产出**。

变异测试（`python -m agent mutate`）第一次跑出 77.8% 时，暴露了四个测试盲区。
其中三个是真缺陷，补在这里；第四个是刻意留给人的可调旋钮，改为只校验取值合法。

这个文件的存在方式本身就是一条经验：

> **"测试全绿"和"测试有用"是两件事。**
> 240 个测试全过的时候，把缺省策略里的"危急值必须升级人工"关掉，
> 一个测试都不会报警——因为所有测试都自己构造配置，没人测过**真正会跑的那份默认值**。

所以这个文件专门钉三件东西：
1. **安全不变量**（出厂默认必须是安全的）
2. **可调旋钮的合法性**（不钉具体值，但必须合法）
3. **基准自身的完整性**（评测口径不能被放宽）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.mutants import MUTANTS
from agent.policy import AUDIT_POLICY, INSPECT_SCOPES
from audit.detect import Finding
from audit.evaluate import _matches
from audit.inject import Defect

ROOT = Path(__file__).resolve().parents[1]


def _defect(target: str = "alt", detector: str = "safety_terms") -> Defect:
    return Defect(
        defect_id="D-TEST",
        kind="safety_violation",
        target=target,
        location="items[].explanation",
        description="测试用",
        expected="期望",
        observed="实际",
        expected_detector=detector,
    )


def _finding(target: str = "alt", detector: str = "safety_terms") -> Finding:
    return Finding(
        detector=detector,
        target=target,
        location="items[].explanation",
        message="测试用",
        expected="期望",
        observed="实际",
    )


# --------------------------------------------------------------------------- #
# 1. 安全不变量：出厂默认必须是安全的
# --------------------------------------------------------------------------- #


def test_shipped_policy_keeps_safety_invariants():
    """出厂默认就是**真正会跑**的那套配置，安全项必须为 True。

    变异测试发现：把 `escalate_on_critical_severity` 或 `require_verifiable_evidence`
    的默认值改成 False，全部测试照过。这两个是安全相关的默认值，绝不能无人看守。
    """
    assert AUDIT_POLICY.escalate_on_critical_severity is True, (
        "危急值默认必须升级人工——这个默认值关了，系统就会悄悄放行危急判定"
    )
    assert AUDIT_POLICY.require_verifiable_evidence is True, (
        "「模型结论必须交得出原文依据」默认必须开着——关掉等于允许模型编造"
    )
    assert AUDIT_POLICY.escalate_unknown_category is True, (
        "不认识的类别必须默认升级人工（fail-safe）"
    )


# --------------------------------------------------------------------------- #
# 2. 可调旋钮：不钉具体值，但要钉合法性
# --------------------------------------------------------------------------- #


def test_shipped_policy_knobs_are_valid():
    """成本/范围类参数是**刻意留给人的旋钮**，不该钉死取值。

    但必须保证：取值在允许集合内、成本上限在一个理智范围内。
    这样你在 `docs/10-你的任务.md` 的任务 T5 里怎么调都不会把系统调坏。
    """
    assert AUDIT_POLICY.inspect_scope in INSPECT_SCOPES, (
        f"检查范围必须是 {INSPECT_SCOPES} 之一，实际是 {AUDIT_POLICY.inspect_scope!r}"
    )
    assert 0 < AUDIT_POLICY.max_model_calls_per_artifact <= 32, (
        "单份模型调用上限必须在 1–32 之间——这是成本护栏"
    )
    assert isinstance(AUDIT_POLICY.escalate_categories, tuple)


def test_policy_describe_is_readable():
    text = AUDIT_POLICY.describe()
    assert "范围=" in text and "调用上限=" in text


# --------------------------------------------------------------------------- #
# 3. 基准自身的完整性
# --------------------------------------------------------------------------- #


def test_evaluation_matching_requires_same_detector():
    """评测的匹配规则必须**同时**看检查器与指标。

    变异测试发现：把匹配放宽成"只看指标名"，全部测试照过。
    后果很严重——任何一个乱报的检查器都能蹭到召回率，
    而基准看起来依然完美。**基准本身也需要被测试守住。**
    """
    assert _matches(_finding(), _defect()) is True, "检查器与指标都一致 → 算抓到"
    assert _matches(_finding(detector="advice_contract"), _defect()) is False, (
        "指标相同但检查器不同 → **不算抓到**（否则乱报也能蹭召回）"
    )
    assert _matches(_finding(target="ggt"), _defect()) is False, "指标不同 → 不算抓到"


# --------------------------------------------------------------------------- #
# 4. 检索参数：改动必须是有意的
# --------------------------------------------------------------------------- #


def test_bm25_parameters_are_pinned():
    """BM25 的两个参数有明确依据，不是随手写的数。

    变异测试发现：把 b 改成 0（关掉长度归一化）没有任何测试报警。
    检索质量会悄悄退化，而"Recall@1 ≥ 0.90"这个门槛太宽，兜不住。
    """
    from rag.bm25 import B, K1

    assert B == 0.75, (
        "b 控制文档长度归一化的强度，0.75 是常用取值；"
        "改成 0 意味着长文档不再被惩罚，排序会变——这个改动必须是有意的"
    )
    assert 1.0 <= K1 <= 2.0, (
        f"k1 控制词频饱和速度，常用区间 1.2–2.0；实际 {K1} 已超出安全范围"
    )
    from rag.bm25 import EPSILON

    assert 0 < EPSILON < 1, "IDF 的兜底项，用于避免某个词全文档出现时 IDF 变负"


# --------------------------------------------------------------------------- #
# 5. 变异体定义本身必须精确
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.mutant_id)
def test_mutant_targets_are_precise(mutant):
    """每个变异体的目标片段必须在其文件里**恰好出现一次**。

    ⚠️ 这是一条**元测试**：它校验的是变异体定义，不是产品代码。
    因此它被 `agent/mutation.py` 的 `_META_TESTS` 排除在变异运行之外——
    否则变异体一被应用，这条测试就必然失败，**每个变异体都会显示为"被杀死"**，
    变异得分退化成人造的 100%。（这个坑真实踩过。）

    它在这里的价值是：防止某个变异体的目标片段过期或不够精确，
    导致那个变异体**悄悄测不到东西**。
    """
    target = ROOT / mutant.target
    assert target.is_file(), f"{mutant.mutant_id} 的目标文件不存在：{mutant.target}"

    text = target.read_text(encoding="utf-8")
    occurrences = text.count(mutant.old_snippet)
    assert occurrences == 1, (
        f"{mutant.mutant_id} 的目标片段在 {mutant.target} 里出现 {occurrences} 次（必须恰好 1 次）。"
        "片段过期或不够精确，都会让这个变异体测不到东西。"
    )
    assert mutant.old_snippet != mutant.new_snippet, "变异前后不能一样"
    assert mutant.invariant.strip(), f"{mutant.mutant_id} 缺少 invariant 说明"


def test_mutants_have_unique_ids():
    ids = [mutant.mutant_id for mutant in MUTANTS]
    assert len(ids) == len(set(ids))


def test_at_least_one_knob_is_marked_allowed_to_survive():
    """至少要有一个"允许存活"的旋钮，否则说明设计上把人的调整空间也钉死了。"""
    allowed = [mutant for mutant in MUTANTS if not mutant.must_kill]
    assert allowed, "应当有刻意留给人的可调旋钮（见 agent/policy.py）"
    for mutant in allowed:
        assert "旋钮" in mutant.invariant or "可调" in mutant.invariant, (
            "允许存活的变异体必须写明为什么允许——否则就是事后找借口"
        )
