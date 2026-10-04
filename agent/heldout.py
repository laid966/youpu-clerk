"""留出集：用**提示词没见过的新句子**测泛化能力。

## 为什么必须单独做这件事

基准里的改写型越界只有 **10 个固定句子**。而 V2（或任何改法）往往是
**看着其中几句写出来的**。于是：

    在那 24 条上拿 100%  →  只能说明"学会了这 10 句"
                           **不能说明"学会了这两类越界"**

泛化能力只能用一个办法测：**拿没见过的新句子去问**。
这个模块就读 `eval/semantic-heldout.jsonl` 里的新句子。

## 为什么要专门分组看"镜像句"

最容易骗过提示词的是**意思相反、只差几个字**的一对句子：

    ❌ "这个结果不用挂专家号，自己在家观察就行。"   ← 劝阻就医，违规
    ✅ "建议到内分泌科门诊，让医生结合情况判断。"   ← 引导就医，合法

如果提示词只写了"是否就医属于越界"（没区分"劝阻"和"引导"），
它很可能**两句都报**或**两句都不报**。所以报告里把这类句子单独成组统计——
**这一组的分数，比总召回率更能说明问题。**
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from agent.eval_semantic import SemanticCase
from agent.judge import Judge
from agent.semantic_check import check_text

__all__ = [
    "HELDOUT_FILE",
    "MIRROR_GROUPS",
    "HeldoutReport",
    "load_heldout",
    "run_heldout",
]

ROOT = Path(__file__).resolve().parents[1]
HELDOUT_FILE = ROOT / "eval" / "semantic-heldout.jsonl"

#: 需要单独看的成组句子（镜像对）。**这一组的成绩比总召回率更能说明泛化能力。**
MIRROR_GROUPS: dict[str, tuple[str, ...]] = {
    "劝阻就医 vs 引导就医": ("P7", "P8", "N1", "N2", "N3"),
    "把决定权交给医生（不该报）": ("N4", "N5"),
    "新的治疗方案类越界（该报）": ("P5", "P6"),
}


@dataclass(frozen=True)
class HeldoutOutcome:
    case_id: str
    text: str
    label: str  # violation | clean
    category: str
    note: str
    flagged: bool
    decided_by: str
    error: str | None

    @property
    def correct(self) -> bool:
        if self.error:
            return False
        return self.flagged == (self.label == "violation")


@dataclass(frozen=True)
class HeldoutReport:
    prompt_version: str
    outcomes: tuple[HeldoutOutcome, ...]

    @property
    def positives(self) -> tuple[HeldoutOutcome, ...]:
        return tuple(item for item in self.outcomes if item.label == "violation")

    @property
    def negatives(self) -> tuple[HeldoutOutcome, ...]:
        return tuple(item for item in self.outcomes if item.label == "clean")

    @property
    def caught(self) -> int:
        return sum(1 for item in self.positives if item.flagged and not item.error)

    @property
    def recall(self) -> float:
        return self.caught / len(self.positives) if self.positives else 0.0

    @property
    def false_positives(self) -> int:
        return sum(1 for item in self.negatives if item.flagged)

    @property
    def false_positive_rate(self) -> float:
        return self.false_positives / len(self.negatives) if self.negatives else 0.0

    @property
    def errors(self) -> int:
        return sum(1 for item in self.outcomes if item.error)

    @property
    def accuracy(self) -> float:
        return sum(1 for item in self.outcomes if item.correct) / len(self.outcomes) if self.outcomes else 0.0

    def group(self, case_ids: Sequence[str]) -> tuple[HeldoutOutcome, ...]:
        wanted = set(case_ids)
        return tuple(item for item in self.outcomes if item.case_id in wanted)

    def to_markdown(self) -> str:
        lines = [
            f"# 留出集报告 · 提示词 `{self.prompt_version}`",
            "",
            "> 用**提示词没见过的新句子**测泛化能力。",
            "> 在基准那 24 条上拿高分，只说明「学会了那 10 句」；",
            "> **只有这份报告里的数字才说明「学会了这一类」。**",
            "",
            "## 总览",
            "",
            "| 指标 | 数值 |",
            "|---|---|",
            f"| 违规句（该报） | {len(self.positives)} |",
            f"| 抓住 | **{self.caught}** |",
            f"| **召回率** | **{self.recall:.1%}** |",
            f"| 合法句（不该报） | {len(self.negatives)} |",
            f"| 误报 | **{self.false_positives}** |",
            f"| **误报率** | **{self.false_positive_rate:.1%}** |",
            f"| 解析失败 | {self.errors} |",
            f"| **逐条正确率** | **{self.accuracy:.1%}** |",
            "",
        ]

        lines += ["## 镜像组（最能看出泛化）", ""]
        for name, ids in MIRROR_GROUPS.items():
            items = self.group(ids)
            ok = sum(1 for item in items if item.correct)
            lines.append(f"**{name}**：{ok} / {len(items)} 条判对")
            for item in items:
                mark = "✅" if item.correct else "❌"
                expect = "该报" if item.label == "violation" else "不该报"
                actual = "报了" if item.flagged else "没报"
                lines.append(f"- {mark} `{item.case_id}`（{expect}，实际{actual}）{item.text}")
            lines.append("")

        lines += [
            "## 逐条明细",
            "",
            "| 编号 | 期望 | 实际 | 谁判的 | 模型给的类别 | 句子 |",
            "|---|---|---|---|---|---|",
        ]
        for item in self.outcomes:
            expect = "该报" if item.label == "violation" else "不该报"
            if item.error:
                actual = "**解析失败**"
            else:
                actual = "报了" if item.flagged else "没报"
            mark = "✅" if item.correct else "❌"
            category = item.category or "—"
            lines.append(
                f"| {mark} {item.case_id} | {expect} | {actual} | {item.decided_by} "
                f"| `{category}` | {item.text} |"
            )

        lines += [
            "",
            "## 怎么读这份报告",
            "",
            "- **召回低**：提示词对新说法不够狠 → 在定义里补语言特征，而不是补例句",
            "- **误报高**：白名单不够清楚 → 尤其检查「引导就医」和「劝阻就医」有没有分开写",
            "- **镜像组判错**：这说明提示词没抓住那一对句子的**区别**，只抓住了主题词",
            "- **解析失败 >0**：输出格式要求有问题，优先修这个（它比漏报更危险）",
            "",
            "> 你可以往 `eval/semantic-heldout.jsonl` 里继续加句子——",
            "> **加得越狠，这个数字越可信。**",
            "",
        ]
        return "\n".join(lines)


def load_heldout(path: str | Path = HELDOUT_FILE) -> tuple[SemanticCase, ...]:
    """读留出集。格式错会带行号报错，不静默跳过。"""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"没有这个文件：{path}")

    cases: list[SemanticCase] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} 第 {line_no} 行不是合法 JSON：{exc}") from exc

        case_id = str(payload.get("id", "")).strip()
        text = str(payload.get("text", "")).strip()
        label = str(payload.get("label", "")).strip()
        if not case_id or not text:
            raise ValueError(f"{path.name} 第 {line_no} 行缺少 id 或 text")
        if label not in ("violation", "clean"):
            raise ValueError(f"{path.name} 第 {line_no} 行 label 必须是 violation 或 clean")

        cases.append(
            SemanticCase(
                case_id=case_id,
                target="heldout",
                text=text,
                is_positive=label == "violation",
                note=str(payload.get("note", "")),
            )
        )
    return tuple(cases)


def run_heldout(
    cases: Sequence[SemanticCase],
    prompt: str,
    prompt_version: str,
    judge: Judge,
) -> HeldoutReport:
    """逐条跑检查并收集结果。

    这里没有复用 `evaluate_semantic`，是刻意的：留出集报告需要**逐条明细**
    （哪一句判错了、是谁判的），那是这份报告的主要价值。
    基准评测仍然走 `evaluate_semantic`，那边是权威口径。
    """
    outcomes: list[HeldoutOutcome] = []
    for case in cases:
        outcome = check_text(case.text, case.case_id, prompt, judge)
        finding = outcome.finding
        outcomes.append(
            HeldoutOutcome(
                case_id=case.case_id,
                text=case.text,
                label="violation" if case.is_positive else "clean",
                category=(finding.category if finding else ""),
                note=case.note,
                flagged=finding is not None,
                decided_by=(finding.decided_by if finding else "none"),
                error=outcome.error,
            )
        )
    return HeldoutReport(prompt_version=prompt_version, outcomes=tuple(outcomes))
