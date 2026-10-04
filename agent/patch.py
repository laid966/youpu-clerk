"""补丁闭环：从漏掉的案例里提取候选规则 → 验证不误伤 → 产出**待人审批**的建议。

## 它做什么

护栏层是**字面匹配**。漏掉的改写型越界往往有共同的语言碎片
（"已经属于…范围""按…来管理""基本可以确定"）。这个闭环：

1. **提取候选**：从漏掉的文本里切出 n-gram 片段
2. **过滤**：丢掉在干净语料里也出现的（那会造成误报）
3. **贪心覆盖**：优先选"能覆盖最多漏例"的片段
4. **验证**：在完整干净语料上复核误报数
5. **出建议**：生成可以直接粘进 `agent/guardrails.py` 的规则片段

## 两条必须说清的边界

**① 它只能补字面模式，补不了泛化能力。**
改写说法无穷无尽，字面规则永远追不上。所以它产出的是**减速带**，
真正解决问题的还是提示词的泛化能力（那是 `agent/prompts.py` 的活，也是人的活）。

**② 它绝不自动应用任何改动。**
`PatchProposal` 只是一份建议，必须由人审阅后**手工**加进护栏文件。
一个会自动修改自身安全规则的系统，迟早会把自己改坏——
这条和项目里其他所有"关键动作要人审批"的设计是一致的。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = [
    "PatchProposal",
    "PatchReport",
    "evaluate_pattern",
    "extract_candidates",
    "propose_patches",
]

MIN_PATTERN_LENGTH = 6
"""候选片段的最短字符数。

提到 6 是有原因的：第一版是 4，于是"这个数值"这种通用片段混进了建议里。
它在当时的反例语料上零误报，**但那只是因为语料里恰好没有它**——
放到真实文本上必然大量误报。**过短的片段没有泛化价值，只有误报风险。**
"""
MAX_PATTERN_LENGTH = 12
_SEPARATORS = "，。；：、！？（）【】《》\n\r\t ,.;:!?()[]"


@dataclass(frozen=True)
class PatchProposal:
    pattern: str
    catches: tuple[str, ...]
    false_positives: tuple[str, ...]
    verdict: str
    reason: str

    @property
    def is_safe(self) -> bool:
        return not self.false_positives

    def to_guardrail_snippet(self) -> str:
        """生成可以直接粘进 `agent/guardrails.py` 的规则片段。"""
        return (
            "    GuardrailRule(\n"
            '        name="G-<你来起名>",\n'
            '        category="diagnosis",\n'
            f'        patterns=({self.pattern!r},),\n'
            '        note="<写清它防的是什么错：什么改写说法会绕过原词表>",\n'
            "    ),"
        )


@dataclass(frozen=True)
class PatchReport:
    missed_total: int
    candidates_tried: int
    proposals: tuple[PatchProposal, ...]
    negatives_total: int

    @property
    def covered(self) -> int:
        covered: set[str] = set()
        for proposal in self.proposals:
            covered.update(proposal.catches)
        return len(covered)

    @property
    def coverage(self) -> float:
        return self.covered / self.missed_total if self.missed_total else 0.0

    @property
    def total_false_positives(self) -> int:
        return sum(len(proposal.false_positives) for proposal in self.proposals)

    def to_markdown(self) -> str:
        lines = [
            "# 补丁建议报告（补丁闭环）",
            "",
            "> 从**漏掉的案例**里自动提取候选规则，验证它在干净语料上不误伤，",
            "> 然后给出一份**待人审批**的建议。",
            "",
            "> ⚠️ **本工具不会自动应用任何改动。** 补丁必须由人审阅后手工写进 `agent/guardrails.py`。",
            "> ⚠️ 它只能补**字面模式**，补不了提示词的泛化能力——改写说法无穷无尽。",
            "",
            "## 总览",
            "",
            "| 项目 | 数值 |",
            "|---|---|",
            f"| 漏掉的案例 | {self.missed_total} |",
            f"| 尝试过的候选片段 | {self.candidates_tried} |",
            f"| 干净语料条数（误报检验用） | {self.negatives_total} |",
            f"| 建议采纳的规则 | {len(self.proposals)} |",
            f"| **覆盖的漏例** | **{self.covered} / {self.missed_total}（{self.coverage:.1%}）** |",
            f"| 在干净语料上的误报 | **{self.total_false_positives}** |",
            "",
        ]

        if not self.proposals:
            lines += ["## 结论", "", "- 没有找到安全的候选片段。改提示词的泛化能力，而不是加字面规则。", ""]
            return "\n".join(lines)

        lines += ["## 建议（按覆盖数排序）", ""]
        for index, proposal in enumerate(self.proposals, start=1):
            lines += [
                f"### 建议 {index}：`{proposal.pattern}`",
                "",
                f"- 判定：**{proposal.verdict}**",
                f"- 理由：{proposal.reason}",
                f"- 能抓到 {len(proposal.catches)} 条漏例：",
            ]
            for text in proposal.catches[:3]:
                lines.append(f"  - …{text[-50:]}")
            if len(proposal.catches) > 3:
                lines.append(f"  - …还有 {len(proposal.catches) - 3} 条")
            lines += ["", "可粘贴的规则片段：", "", "```python", proposal.to_guardrail_snippet(), "```", ""]

        lines += [
            "## 采纳前你必须做的三件事",
            "",
            "1. **起一个能说明意图的名字**（`G-<类别>-<特征>`），不要留 `<你来起名>`",
            "2. **写清 note**：这条规则防的是哪种改写说法，为什么原词表抓不到",
            "3. **加一个测试用例**：拿一条真实漏例断言它被这条规则捕获",
            "   （模板见 `tests/test_agent.py`）",
            "",
            "然后跑：`python -m pytest -q` 与 `python -m agent eval-semantic`，确认误报率没有上升。",
            "",
        ]
        return "\n".join(lines)


def extract_candidates(
    texts: Iterable[str],
    min_tokens: int = 2,
    max_tokens: int = 5,
    min_chars: int = MIN_PATTERN_LENGTH,
) -> Counter[str]:
    """切出候选片段：**先分词，再取 token n-gram**。

    第一版用的是字符滑窗（字符 n-gram），跑出来的建议惨不忍睹：

        `这个数值`              ← 通用到没有意义
        `以先自己把正在吃的降脂药`  ← 从词中间切出来的碎片

    改成 token n-gram 后自然解决了这两个问题：
    - 分词时停用词会被丢掉，所以"这个数值"根本拼不出来
    - 片段对齐到词边界，不会出现"以先自己把"这种碎片

    **这条迭代写在这里，是因为它本身就是"自动提取的字面规则质量很差"的证据**——
    所以补丁必须人审批，工具只能给候选。
    """
    from rag.tokenize import tokenize

    counter: Counter[str] = Counter()
    for text in texts:
        for clause in _split_clauses(text):
            tokens = tokenize(clause)
            for size in range(min_tokens, min(max_tokens, len(tokens)) + 1):
                for start in range(0, len(tokens) - size + 1):
                    phrase = "".join(tokens[start : start + size])
                    if len(phrase) >= min_chars:
                        counter[phrase] += 1
    return counter


def _split_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    current: list[str] = []
    for char in text:
        if char in _SEPARATORS:
            if current:
                clauses.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        clauses.append("".join(current))
    return [clause for clause in clauses if len(clause) >= MIN_PATTERN_LENGTH]


def evaluate_pattern(
    pattern: str, positives: Sequence[str], negatives: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """返回 (命中的正例, 误伤的反例)。"""
    catches = tuple(text for text in positives if pattern in text)
    false_positives = tuple(text for text in negatives if pattern in text)
    return catches, false_positives


def propose_patches(
    missed_texts: Sequence[str],
    negative_texts: Sequence[str],
    max_patterns: int = 3,
) -> PatchReport:
    """贪心覆盖：每轮挑"能覆盖最多尚未覆盖漏例、且在干净语料里零命中"的片段。"""
    if not missed_texts:
        return PatchReport(0, 0, (), len(negative_texts))

    candidates = extract_candidates(missed_texts)
    # 先做最便宜也最关键的过滤：在干净语料里出现过的片段一律不要
    safe = [
        (pattern, count)
        for pattern, count in candidates.items()
        if not any(pattern in text for text in negative_texts)
    ]
    safe.sort(key=lambda item: (-item[1], -len(item[0]), item[0]))

    uncovered = set(missed_texts)
    proposals: list[PatchProposal] = []

    for pattern, _count in safe:
        if len(proposals) >= max_patterns or not uncovered:
            break
        catches, false_positives = evaluate_pattern(pattern, tuple(uncovered), negative_texts)
        if not catches:
            continue
        if false_positives:  # pragma: no cover — safe 过滤已保证为空
            continue

        proposals.append(
            PatchProposal(
                pattern=pattern,
                catches=catches,
                false_positives=false_positives,
                verdict="建议采纳（待人工确认）",
                reason=(
                    f"在 {len(negative_texts)} 条干净文本上零命中，"
                    f"能补上 {len(catches)} 条漏例。"
                    "但它是字面规则——采纳后仍需靠提示词处理其他改写说法。"
                ),
            )
        )
        uncovered -= set(catches)

    return PatchReport(
        missed_total=len(missed_texts),
        candidates_tried=len(candidates),
        proposals=tuple(proposals),
        negatives_total=len(negative_texts),
    )
