"""变异体定义：故意把流水线改坏，看测试套件抓不抓得住。

## 这是个什么指标

普通测试只告诉你"现在通过"。**变异测试告诉你"测试有没有用"**：

    变异得分 = 被抓住的变异体 / 全部有效变异体

- **杀死（killed）**：改坏之后测试失败 → 说明这个不变量被测试守住了
- **存活（survived）**：改坏之后测试照样通过 → **测试盲区**，或者这个改动其实无害

存活的变异体比得分本身更有价值——它直接指出"哪条代码没有一个测试真正验证它"。

## 为什么这个数字比"240 个测试通过"有分量

"测试通过"可以在测试很弱的时候也成立。变异得分不能：
它要求测试**在代码被改坏时真的报警**。面试时说"我的测试能杀死 10/10 个变异体"，
比说"我有 240 个测试"硬得多。

## 已知边界（必须说清楚）

这里只覆盖**单元测试能杀的变异体**。提示词层面的弱化（比如把"只在明确越界时判 true"
改成"尽量判 true"）单元测试杀不掉——因为单元测试用的是假模型。
那类变异要靠**语义评测的指标门槛**来杀，属于后续工作。
**不写清楚这个边界，变异得分就会看起来比实际更强。**
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["MUTANTS", "Mutant"]


@dataclass(frozen=True)
class Mutant:
    mutant_id: str
    target: str  # 相对项目根的文件路径
    description: str
    old_snippet: str
    new_snippet: str
    expected_killer: str
    invariant: str = ""
    must_kill: bool = True
    """这个变异体**必须**被测试杀死吗？

    绝大多数是 True：它们是安全不变量或基准完整性约束，改坏就该报警。

    但也有少数是**允许存活**的——它们是刻意留给人的可调旋钮。
    用测试钉死具体取值会阻止正常调整；这类变异体只要仍有测试保证取值合法即可。
    """


MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        mutant_id="M01",
        target="audit/detect.py",
        description="去掉数值一致性检查的相对容差（0.01 → 0）",
        old_snippet="VALUE_TOLERANCE = 0.01",
        new_snippet="VALUE_TOLERANCE = 0.0",
        expected_killer="tests/test_detect.py::test_value_tolerance_allows_rounding",
        invariant="正常显示取整不该被误报成数值抄错",
    ),
    Mutant(
        mutant_id="M02",
        target="engine/adjudicate.py",
        description="忽略域声明的默认结论",
        old_snippet="        if domain.default_verdict is not None:",
        new_snippet="        if False:",
        expected_killer="tests/test_grading_domain.py::test_default_verdict_applies_when_no_rule_matches",
        invariant="分级域里「没有规则命中」等于全部正常，不是规则缺口",
    ),
    Mutant(
        mutant_id="M03",
        target="engine/adjudicate.py",
        description="关掉全部转人工判断（escalated 恒为 False）",
        old_snippet="    escalated = bool(reasons)",
        new_snippet="    escalated = False",
        expected_killer="tests/test_adjudicate.py::test_amount_threshold_triggers_escalation",
        invariant="该转人工的必须转人工",
    ),
    Mutant(
        mutant_id="M04",
        target="engine/adjudicate.py",
        description="忽略规则优先级（按 id 排序）",
        old_snippet="    matched.sort(key=lambda item: (-item.priority, item.id))",
        new_snippet="    matched.sort(key=lambda item: (item.id,))",
        expected_killer="tests/test_adjudicate.py::test_business_cabin_overrides_generic_tier",
        invariant="高优先级规则必须压过低优先级规则",
    ),
    Mutant(
        mutant_id="M05",
        target="engine/adjudicate.py",
        description="去掉金额四舍五入到分",
        old_snippet="    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)",
        new_snippet="    return value",
        expected_killer="tests/test_adjudicate.py::test_rounding_is_half_up_to_cent",
        invariant="金额必须四舍五入到分",
    ),
    Mutant(
        mutant_id="M06",
        target="audit/inject.py",
        description="把干净样本比例改成 0（消灭误报率的分母）",
        old_snippet="CLEAN_SHARE = 0.40",
        new_snippet="CLEAN_SHARE = 0.0",
        expected_killer="tests/test_inject.py::test_clean_share_is_exact",
        invariant="没有干净样本就测不出误报率",
    ),
    Mutant(
        mutant_id="M07",
        target="agent/guardrails.py",
        description="让护栏一条都匹配不上（词表失效）",
        old_snippet="    hits: list[GuardrailHit] = []\n    for rule in GUARDRAIL_RULES:",
        new_snippet="    hits: list[GuardrailHit] = []\n    for rule in ():",
        expected_killer="tests/test_agent.py::test_guardrails_catch_obvious_violations",
        invariant="露骨的越界写法必须被词表挡住",
    ),
    Mutant(
        mutant_id="M08",
        target="agent/nodes.py",
        description="关掉「模型结论必须交得出原文依据」的校验",
        old_snippet='            if self.policy.require_verifiable_evidence and finding["decided_by"] == "model":',
        new_snippet="            if False:",
        expected_killer="tests/test_agent_graph.py::test_reflect_rejects_finding_without_verifiable_evidence",
        invariant="模型编造的结论必须被挡住",
    ),
    Mutant(
        mutant_id="M09",
        target="rag/knowledge.py",
        description="去掉标题重复（检索的字段加权失效）",
        old_snippet=(
            '        return "\\n".join(part for part in (self.title, self.title, self.keywords, self.text) if part)'
        ),
        new_snippet=(
            '        return "\\n".join(part for part in (self.title, self.keywords, self.text) if part)'
        ),
        expected_killer="tests/test_rag.py::test_metric_chunk_carries_keywords_and_repeats_title",
        invariant="标题重复是对指标名的加权，去掉会改变排序",
    ),
    Mutant(
        mutant_id="M10",
        target="audit/inject.py",
        description="让改写型越界里混进禁用词（基准就失去意义了）",
        old_snippet='    "这个结果通常提示肝脏已经出现了实质性的损伤，需要按脂肪肝来管理。",',
        new_snippet='    "考虑为脂肪肝：这个结果通常提示肝脏已经出现了实质性的损伤。",',
        expected_killer="tests/test_inject.py::test_paraphrased_safety_violations_avoid_the_banned_word_list",
        invariant="改写型越界必须真的绕开词表，否则不能证明语义检查的必要性",
    ),
    # ==================================================================== #
    # 第二批：**盲测变异体**。
    #
    # 第一批是我照着现有测试挑的"肯定能杀掉"的目标，拿 100% 是自证。
    # 这一批刻意挑我**怀疑没被覆盖**的地方——尤其是那个真正会跑的缺省策略。
    # 存活下来的才是真发现。
    # ==================================================================== #
    Mutant(
        mutant_id="M11",
        target="agent/policy.py",
        description="缺省策略关掉「危急值必须升级人工」",
        old_snippet="    escalate_on_critical_severity: bool = True",
        new_snippet="    escalate_on_critical_severity: bool = False",
        expected_killer="tests/test_invariants.py::test_shipped_policy_keeps_safety_invariants",
        invariant="出厂默认就该是安全的：危急值默认必须人工",
    ),
    Mutant(
        mutant_id="M12",
        target="agent/policy.py",
        description="缺省策略把检查范围从「只查异常」改成「全查」（成本涨 10 倍）",
        old_snippet='    inspect_scope: str = "abnormal_only"',
        new_snippet='    inspect_scope: str = "all"',
        expected_killer="(不要求被杀死)",
        invariant=(
            "这是一个**成本旋钮**，刻意留给使用者调（见 docs/10-你的任务.md 的 T5）。"
            "用测试钉死具体取值会阻止正常调整——只要求有测试保证取值合法。"
        ),
        must_kill=False,
    ),
    Mutant(
        mutant_id="M13",
        target="agent/policy.py",
        description="缺省策略关掉「模型结论必须交得出原文依据」",
        old_snippet="    require_verifiable_evidence: bool = True",
        new_snippet="    require_verifiable_evidence: bool = False",
        expected_killer="tests/test_invariants.py::test_shipped_policy_keeps_safety_invariants",
        invariant="反幻觉校验默认必须开着",
    ),
    Mutant(
        mutant_id="M14",
        target="rag/bm25.py",
        description="关掉 BM25 的文档长度归一化（b=0.75 → 0）",
        old_snippet="B = 0.75",
        new_snippet="B = 0.0",
        expected_killer="tests/test_invariants.py::test_bm25_parameters_are_pinned",
        invariant="长度归一化影响排序质量，改坏应当被检索指标发现",
    ),
    Mutant(
        mutant_id="M15",
        target="rag/bm25.py",
        description="把 BM25 的词频饱和参数调到几乎无饱和（k1=1.5 → 50）",
        old_snippet="K1 = 1.5",
        new_snippet="K1 = 50.0",
        expected_killer="tests/test_invariants.py::test_bm25_parameters_are_pinned",
        invariant="k1 控制词频饱和，极端取值会让长文档被过度奖励",
    ),
    Mutant(
        mutant_id="M16",
        target="audit/evaluate.py",
        description="放宽评测的匹配规则：只看指标名，不看检查器",
        old_snippet=(
            "    if finding.detector == defect.expected_detector:\n"
            "        return True\n"
            "    return finding.detector in ALTERNATE_DETECTORS.get(defect.kind, frozenset())"
        ),
        new_snippet="    return finding.target == defect.target",
        expected_killer="tests/test_invariants.py::test_evaluation_matching_requires_same_detector",
        invariant=(
            "匹配必须同时看检查器与指标（替代关系只限声明过的那一条），"
            "否则乱报的检查器也能蹭到召回率"
        ),
    ),
    Mutant(
        mutant_id="M17",
        target="audit/detect.py",
        description="让数值一致性检查对任何偏差都放行（容差 1% → 100%）",
        old_snippet="VALUE_TOLERANCE = 0.01",
        new_snippet="VALUE_TOLERANCE = 1.0",
        expected_killer="tests/test_detect.py::test_value_mismatch_is_caught",
        invariant="数值抄错必须被抓到",
    ),
    Mutant(
        mutant_id="M18",
        target="agent/nodes.py",
        description="忽略单份模型调用上限（成本护栏失效）",
        old_snippet="            if calls >= limit:",
        new_snippet="            if False:",
        expected_killer="tests/test_agent_graph.py::test_model_call_cap_is_enforced_and_noted",
        invariant="成本上限必须真的生效",
    ),
)
