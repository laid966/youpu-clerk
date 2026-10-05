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

from agent.heldout import load_heldout
from agent.mutants import MUTANTS
from agent.policy import AUDIT_POLICY, INSPECT_SCOPES
from audit.detect import Finding
from audit.evaluate import _matches
from audit.inject import Defect

ROOT = Path(__file__).resolve().parents[1]


def _defect(
    target: str = "alt",
    detector: str = "safety_terms",
    kind: str = "safety_violation",
) -> Defect:
    return Defect(
        defect_id="D-TEST",
        kind=kind,
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


# --------------------------------------------------------------------------- #
# 6. 跨文件一致性：提示词声明的类别 vs 策略认识的类别
# --------------------------------------------------------------------------- #


def test_prompt_categories_match_policy_known_categories():
    """提示词里声明可输出的类别，必须都在 policy 的 `KNOWN_CATEGORIES` 里。

    **为什么需要这条测试**：如果提示词引入了新类别，而 `agent/policy.py` 不知道，
    系统不会报错——它会走 fail-safe，把这条结论**升级人工**。

    结果是：**改提示词悄悄改变了"谁需要人工复核"，而没有人发现。**

    这个盲区真实发生过：提示词加了 `relastic_execution` 类，
    而 `KNOWN_CATEGORIES` 里没有它，于是这一类结论全部靠"未知类目"的兜底升级人工。
    结果是**对的**（确实该人工看），但**理由是错的**——一旦有人把
    `escalate_unknown_category` 关掉，或者把类别名改成别的写法，
    这个保护就会无声消失。

    经验：**跨文件的约定必须有测试守着**，靠注释提醒（"记得在这里补上"）是不可靠的。
    """
    import re

    from agent.policy import KNOWN_CATEGORIES
    from agent.prompts import _REGISTRY

    known = set(KNOWN_CATEGORIES)
    problems: list[str] = []

    for version, text in _REGISTRY.items():
        # 只取 category 那一小段，到下一个字段（", "evidence"）为止。
        # 不然会把同一行后面的 "evidence" 也当成类别。
        match = re.search(r'"category"\s*:\s*(.*?),\s*"', text)
        if not match:
            continue
        declared = set(re.findall(r'"([a-z_]+)"', match.group(1))) - {"category", "none"}
        unknown = declared - known
        if unknown:
            problems.append(
                f"提示词 {version} 声明了 {sorted(declared)}，"
                f"但 KNOWN_CATEGORIES 里没有 {sorted(unknown)}"
            )

    assert not problems, (
        "\n".join(problems)
        + "\n\n改法二选一（都是改一个词）：\n"
        "  A. 把新类别加进 agent/policy.py 的 KNOWN_CATEGORIES\n"
        "  B. 在提示词里改用已有类别名（diagnosis / treatment / dosage / guidance / prognosis）"
    )


# --------------------------------------------------------------------------- #
# 7. 留出集自身的完整性
# --------------------------------------------------------------------------- #


def test_heldout_set_is_wellformed():
    """留出集必须同时有足够的违规句和合法句，否则算不出有意义的召回/误报。"""
    from agent.heldout import load_heldout

    cases = load_heldout()

    positives = [case for case in cases if case.is_positive]
    negatives = [case for case in cases if not case.is_positive]

    assert len(positives) >= 8, f"违规句太少（{len(positives)}），召回率不可信"
    assert len(negatives) >= 8, f"合法句太少（{len(negatives)}），误报率不可信"
    assert len({case.case_id for case in cases}) == len(cases), "编号有重复"


def test_heldout_covers_all_four_violation_types():
    """四类越界都要有留出句，否则某一类没被判到也看不出来。"""
    from agent.heldout import load_heldout

    cases = load_heldout()
    texts = " ".join(case.text for case in cases if case.is_positive)

    assert "已经达到了" in texts or "符合典型" in texts, "缺少诊断类留出句"
    assert "他汀" in texts or "降尿酸药" in texts, "缺少用药类留出句"
    assert "主食" in texts or "快走" in texts, "缺少治疗方案类留出句"
    assert "不用挂专家号" in texts or "没必要再复查" in texts, "缺少就医误导类留出句"


def test_mirror_groups_reference_existing_ids():
    """镜像组里写的编号必须真的存在——否则那一组会静默变成 0 条。"""
    from agent.heldout import MIRROR_GROUPS, load_heldout

    ids = {case.case_id for case in load_heldout()}
    for name, group in MIRROR_GROUPS.items():
        missing = set(group) - ids
        assert not missing, f"镜像组「{name}」引用了不存在的编号：{sorted(missing)}"


def test_heldout_loader_rejects_bad_rows(tmp_path):
    bad = tmp_path / "heldout.jsonl"

    bad.write_text('{"id": "X1", "label": "maybe", "text": "随便一句"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="label 必须是"):
        load_heldout(bad)

    bad.write_text('{"id": "X1", "label": "clean"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="缺少 id 或 text"):
        load_heldout(bad)

    bad.write_text('{"id": "X1", "label": "clean", "text": "句子"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="第 1 行"):
        load_heldout(bad)


def test_heldout_report_separates_mirror_groups():
    """报告必须把镜像组单独列出来——那一组的成绩比总召回更能说明泛化。"""
    from agent.heldout import HeldoutOutcome, HeldoutReport

    outcomes = (
        HeldoutOutcome("P7", "不用去医院", "violation", "guidance", "", True, "model", None),
        HeldoutOutcome("N1", "建议就诊", "clean", "", "", False, "none", None),
    )
    text = HeldoutReport(prompt_version="vX", outcomes=outcomes).to_markdown()

    assert "镜像组" in text
    assert "劝阻就医 vs 引导就医" in text
    assert "逐条明细" in text


# --------------------------------------------------------------------------- #
# 8. 基准构成不得因无关的内容改动而漂移
# --------------------------------------------------------------------------- #


def test_content_edits_do_not_change_the_benchmark_composition(monkeypatch):
    """给注入句表加一句，**数据集的构成必须一点不变**。

    真实缺陷回归（这一条是修完 bug 之后补的）：

    原先所有注入算子**共用一条顺序随机流**（`random.Random(seed + 131)`），
    而 `random.choice` 消耗的随机字数量**取决于列表长度**。
    于是"给注入句表加一句话"这种**纯内容改动**，会把整条流往后推——
    实测让带合法变体的干净样本从 19 份掉到 14 份，
    **误报率的真正考验被悄悄削弱，而所有既有指标看起来毫无变化。**

    这就是"基准构成漂移"：你分不清数字变了是因为你的改动，还是因为题目换了。
    现在每个算子用 `(seed, 报告编号, 算子名)` 派生的独立随机流，这条测试盯着它。
    """
    from audit.inject import build_injected_dataset, paraphrase_phrases
    from audit.pipeline import load_metrics
    from audit.synth import DEFAULT_SEED, generate_reports
    import audit.inject as inject_module

    metrics = load_metrics()
    judged = generate_reports(count=40, metrics=metrics, seed=DEFAULT_SEED)

    def signature(cases):
        """只取"构成"：样本编号、是否干净、变体名、缺陷的种类与目标。

        **刻意不含 defect.observed**（注入了哪句话）——句表改了，那句话本就该变。
        """
        return [
            (
                case.case_id,
                case.clean,
                case.variation,
                tuple((defect.kind, defect.target) for defect in case.defects),
            )
            for case in cases
        ]

    before = signature(build_injected_dataset(judged, metrics, seed=DEFAULT_SEED))
    assert before, "基准不该是空的"

    monkeypatch.setattr(
        inject_module,
        "_PARAPHRASE_PHRASES",
        paraphrase_phrases() + ("这条是测试新增的越界句，用来验证构成不漂移。",),
    )
    after = signature(build_injected_dataset(judged, metrics, seed=DEFAULT_SEED))

    assert before == after, (
        "加了一句注入句之后基准构成变了——说明随机流又被耦合了。\n"
        "改内容不该改题目：否则指标一变，你分不清是改动导致的还是题目换了。"
    )


# --------------------------------------------------------------------------- #
# 9. 护栏规则不许静默失效
# --------------------------------------------------------------------------- #


def test_guardrail_rule_with_empty_patterns_is_refused():
    """**空规则必须在构造时就报错。**

    真实事故：作者用「从 SAFETY_TERMS 里筛新词」的写法加规则，筛出来是空元组。
    规则看着加上了，实际永远匹配不到——改完跑命令"没有变化"，查了半天查不出来。

    静默失效比报错贵得多，所以这里盯着它：空 patterns 直接抛。
    """
    from agent.guardrails import GuardrailRule

    with pytest.raises(ValueError, match="patterns 是空的"):
        GuardrailRule(
            name="G-EMPTY",
            category="conclusion",
            patterns=(),
            note="只有说明没有词——永远匹配不到",
        )


def test_guardrail_rule_without_note_is_refused():
    from agent.guardrails import GuardrailRule

    with pytest.raises(ValueError, match="必须写 note"):
        GuardrailRule(name="G-NONOTE", category="other", patterns=("某个词",), note="   ")


def test_guardrail_rule_with_duplicate_patterns_is_refused():
    from agent.guardrails import GuardrailRule

    with pytest.raises(ValueError, match="重复"):
        GuardrailRule(
            name="G-DUP",
            category="other",
            patterns=("同一个词", "同一个词"),
            note="重复没有意义，通常是复制粘贴出的错",
        )


def test_extra_patterns_slot_is_actually_wired():
    """`EXTRA_PATTERNS` 必须真的被拼进 `GUARDRAIL_RULES`。

    文件开头写着"在 EXTRA_PATTERNS 里加规则"，但**第一版文件里根本没有这个变量**——
    文档和代码不一致，作者照着说明填也填不进去。这条测试盯着它们保持一致。
    """
    from agent.guardrails import _BASE_RULES, EXTRA_PATTERNS, GUARDRAIL_RULES

    assert GUARDRAIL_RULES == _BASE_RULES + EXTRA_PATTERNS
    for rule in EXTRA_PATTERNS:
        assert rule in GUARDRAIL_RULES, f"{rule.name} 没被拼进规则表"


def test_author_rules_are_not_inert():
    """作者加的每条**字面**规则都必须真的能匹配到东西。

    做法：把这条规则自己的词拼成一段文本喂给 `apply_guardrails`——
    字面规则必须命中。命不中说明这条规则是死的（词写错了，或者被筛空了）。
    """
    from agent.guardrails import EXTRA_PATTERNS, apply_guardrails

    checked = 0
    for rule in EXTRA_PATTERNS:
        if rule.is_regex:
            continue  # 正则没法这样反问，靠 check 命令人工验证
        probe = "、".join(rule.patterns)
        hits = apply_guardrails(probe)
        assert hits, f"规则 {rule.name} 是死的：用它自己的词组成的文本一条都没命中"
        assert any(hit.rule == rule.name for hit in hits), f"{rule.name} 没被触发"
        checked += 1
    assert checked >= 1, "至少应当有一条字面规则被检查到"


def test_check_command_can_report_which_pattern_matched():
    """`python -m agent check` 必须能说清**哪条规则、哪个词**命中。

    没有这个信息，作者无法验证"我加的规则生效没有"——只能靠感觉。
    """
    from agent.guardrails import apply_guardrails

    hits = apply_guardrails("目前已经属于糖尿病范围了")

    assert hits, "这句应当命中护栏"
    assert hits[0].rule == "G-CONCLUSION-KEYWORD"
    assert hits[0].pattern == "已经属于"
    assert hits[0].category == "conclusion"
    assert hits[0].to_dict()["pattern"] == "已经属于"


# --------------------------------------------------------------------------- #
# 10. 更便宜的一层先抓到 → 算抓到，不算误报
# --------------------------------------------------------------------------- #


def test_guardrail_catching_a_paraphrase_counts_as_caught():
    """真实陷阱：往护栏加规则会让端到端审计**多出一批"误报"**。

    因为改写型越界（`safety_paraphrase`）的预期检查器是语义检查，
    而护栏抓到它时会被记在 `safety_terms` 名下——不放宽匹配的话，
    **"改进护栏"看起来像"把系统改坏了"**。

    这是评测口径的漏洞，不是护栏的问题。所以允许一条有据可查的替代关系。
    """
    from audit.evaluate import ALTERNATE_DETECTORS

    paraphrase = _defect(detector="semantic_check", kind="safety_paraphrase")
    by_guardrail = _finding(detector="safety_terms")

    assert _matches(by_guardrail, paraphrase) is True, "护栏先抓到应当算抓到"
    assert ALTERNATE_DETECTORS["safety_paraphrase"] == frozenset({"safety_terms"})


def test_alternates_do_not_leak_to_other_defect_kinds():
    """替代关系只对声明过的缺陷类型生效，不能变成"随便哪个检查器都算抓到"。"""
    value_defect = _defect(detector="value_consistency", kind="value_mismatch")
    safety_finding = _finding(detector="safety_terms")

    assert _matches(safety_finding, value_defect) is False
