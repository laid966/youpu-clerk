"""分级评测：**每一级到底值不值**。

这个项目的一条纪律：任何新加的东西都要有基线对比，否则数字没有意义。

所以这里做两件事：

1. **逐级增益表**：同一套问句集，从"只开 BM25"跑到"全开"，
   每一级给出 Recall@1/@3、MRR 以及**相对上一级的增量 Δ**。
   增量为 0 或负的级，报告里会写明——**不隐藏**。
2. **拒答的双向测量**：拒答阈值是一个取舍，所以必须同时报
   **拒答正确率**（库外问题被挡住的）和**误伤率**（库内问题被误拒的）。
   只报一个数字等于骗自己。

   顺带给出**阈值扫描表**：横轴是阈值，纵轴是两个率，
   让你能看见取舍曲线，而不是拍一个数。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Sequence

from rag.boundary import REFUSAL, RefusalBoundary
from rag.knowledge import KnowledgeBase, load_knowledge
from rag.pipeline import PipelineFlags, RagPipeline, build_pipeline
from rag.retrieval_eval import RetrievalCase, RetrievalReport, evaluate_retrieval

__all__ = [
    "DEFAULT_STAGE_LADDER",
    "DENSE_STAGE_LADDER",
    "LLM_STAGE_LADDER",
    "REFUSAL_FILE",
    "LegOverlap",
    "RefusalReport",
    "StageComparison",
    "StageRow",
    "candidate_thresholds",
    "compare_stages",
    "evaluate_refusal",
    "leg_overlap",
    "load_refusal_questions",
    "sweep_thresholds",
]

ROOT = Path(__file__).resolve().parents[1]
REFUSAL_FILE = ROOT / "eval" / "refusal-questions.jsonl"

#: 逐级加开关的顺序。**顺序即"进阶路线"**：
#: 每一行相对上一行只多开一级，这样增量才能归因到那一级。
#:
#: ⚠️ 第三行是**反例（negative control）**，不是"更高级"：
#: 它把意图判断从软路由换成硬路由，用来**证明"做得更狠不等于更好"**。
#: 一个能被复现的失败，比一句"我们试过了"值钱。
DEFAULT_STAGE_LADDER: tuple[tuple[str, PipelineFlags], ...] = (
    (
        "① 基线：只有 BM25",
        PipelineFlags(query_understanding=False, metric_rerank=False),
    ),
    (
        "② + 软路由 + 指标重排",
        PipelineFlags(query_understanding=True, metric_rerank=True),
    ),
    (
        "③ 反例：硬路由（只查一层）",
        PipelineFlags(
            query_understanding=True, metric_rerank=True, hard_layer_routing=True
        ),
    ),
)


@dataclass(frozen=True)
class StageRow:
    label: str
    flags: PipelineFlags
    report: RetrievalReport

    def recall(self, k: int) -> float:
        return self.report.recall_at(k)


@dataclass(frozen=True)
class StageComparison:
    cases: int
    rows: tuple[StageRow, ...]
    correctness_label: str

    @property
    def baseline(self) -> StageRow:
        return self.rows[0]

    def _delta(self, row: StageRow, k: int) -> float | None:
        index = self.rows.index(row)
        if index == 0:
            return None
        return row.recall(k) - self.rows[index - 1].recall(k)

    def to_markdown(self) -> str:
        lines = [
            "# RAG 分级增益报告",
            "",
            "> 同一套问句集，从「只开 BM25」逐级加开关。",
            "> **每一行的 Δ 是相对上一行的增量**，所以能说清「这一级贡献了多少」。",
            "",
            f"- 用例：**{self.cases}** 条",
            f"- 判定口径：{self.correctness_label}",
            "",
            "| 级 | " + " | ".join(f"Recall@{k}" for k in self.baseline.report.k_values) + " | MRR | ΔRecall@1 |",
            "|---|" + "---|" * (len(self.baseline.report.k_values) + 2),
        ]
        for row in self.rows:
            recalls = " | ".join(
                f"{row.recall(k):.1%}" for k in row.report.k_values
            )
            delta = self._delta(row, 1)
            delta_text = "—" if delta is None else (
                f"**{delta:+.1%}**" if abs(delta) >= 0.0005 else f"{delta:+.1%}（无变化）"
            )
            lines.append(f"| {row.label} | {recalls} | {row.report.mrr:.3f} | {delta_text} |")

        lines.append("")
        lines += self._verdict()
        return "\n".join(lines)

    def _verdict(self) -> list[str]:
        """把"值不值"用数字说清楚，包括**没用的级**。"""
        lines = ["## 每一级值不值", ""]
        useless: list[str] = []
        for index, row in enumerate(self.rows):
            if index == 0:
                continue
            delta = self._delta(row, 1) or 0.0
            delta3 = row.recall(3) - self.rows[index - 1].recall(3)
            if abs(delta) < 0.0005 and abs(delta3) < 0.0005:
                useless.append(row.label)
                lines.append(f"- ⚠️ **{row.label}**：Recall@1 与 @3 都没有变化 —— **这一级当前没有收益**")
            elif delta < 0:
                lines.append(
                    f"- ❌ **{row.label}**：Recall@1 退化 {delta:.1%} —— 这一级引入了伤害"
                )
            else:
                lines.append(f"- ✅ **{row.label}**：Recall@1 {delta:+.1%}")

        lines.append("")
        if useless:
            lines.append(
                "> **没有收益不等于没用**：可能是当前语料太小（15 条）撑不出差异，"
                "也可能是这一级的开关压根没生效。两种情况的处理方式完全不同——"
                "所以下面给出「下一级还有没有空间」的判断依据。"
            )
        else:
            lines.append("> 每一级都有正收益。下一级的空间请看向量那一级（P1）。")
        lines.append("")
        lines.append(
            "> **怎么用这张表**：如果查询理解 + 重排已经把 Recall@1 顶到接近上限，"
            "向量检索（P1）的预期收益就有限——**这个判断现在有数字支撑了**，"
            "而不是拍脑袋决定要不要上向量。"
        )
        lines.append("")
        return lines


@dataclass(frozen=True)
class LegOverlap:
    """两条检索腿的**互补性**：它们各自答对了哪些、重叠多少。

    ⚠️ **这是决定"要不要留一条腿"的那个数字**，比 Recall@1 更直接。

    两条腿都答对 31 条、只有关键词对 2 条、**只有语义对 0 条**——
    那说明语义腿**没有提供关键词腿以外的任何信息**，
    融合它只会稀释（实测：Recall@1 从 97.2% 掉到 83.3%）。
    """

    both: int
    only_a: int
    only_b: int
    neither: int
    label_a: str
    label_b: str
    only_a_cases: tuple[RetrievalCase, ...] = ()
    only_b_cases: tuple[RetrievalCase, ...] = ()

    @property
    def complementary(self) -> bool:
        """B 腿有没有"独占的正确"——没有的话，融它没有意义。"""
        return self.only_b > 0

    def to_markdown(self) -> str:
        lines = [
            "## 两条腿的互补性（决定要不要融合的那个数字）",
            "",
            f"- **{self.label_a}** 与 **{self.label_b}** 都答对：{self.both} 条",
            f"- 只有 {self.label_a} 答对：{self.only_a} 条",
            f"- **只有 {self.label_b} 答对：{self.only_b} 条**",
            f"- 两条都答错：{self.neither} 条",
            "",
        ]
        if self.complementary:
            lines += [
                f"> ✅ {self.label_b} 有 {self.only_b} 条**独占正确**——融合它可能带来增量。",
                "",
            ]
            lines += [f"- {case.case_id} {case.query}" for case in self.only_b_cases]
            lines.append("")
        else:
            lines += [
                f"> ❌ **{self.label_b} 一条独占正确都没有**——它的正确是 "
                f"{self.label_a} 的子集。",
                "> 融合它不会带来新信息，只会稀释强的那一条腿"
                "（实测：Recall@1 从 97.2% 掉到 83.3%）。",
                "> **结论：当前语料规模下不要开这条腿；等语料长大再测一次。**",
                "",
            ]
        if self.only_a_cases:
            lines += [f"**只有 {self.label_a} 答对、{self.label_b} 漏掉的：**", ""]
            lines += [f"- {case.case_id} {case.query}" for case in self.only_a_cases]
            lines.append("")
        return "\n".join(lines)


def leg_overlap(
    knowledge: KnowledgeBase,
    cases: Sequence[RetrievalCase],
    a_label: str,
    b_label: str,
    a_flags: PipelineFlags,
    b_flags: PipelineFlags,
    metrics: Sequence = (),
) -> LegOverlap:
    """比较两条腿各自答对/答错的**用例集合**。

    为什么要单独做这件事：`Recall@1` 只告诉你"总体多少"，
    但**决定要不要融合的是"另一条腿有没有独占的正确"**。
    两条腿都答对同样的题时，融合只有稀释的份。
    """
    pipeline_a = build_pipeline(knowledge=knowledge, flags=a_flags, metrics=metrics)
    pipeline_b = build_pipeline(knowledge=knowledge, flags=b_flags, metrics=metrics)

    both = only_a = only_b = neither = 0
    only_a_cases: list[RetrievalCase] = []
    only_b_cases: list[RetrievalCase] = []

    for case in cases:
        top_a = pipeline_a.search(case.query, top_k=1)
        top_b = pipeline_b.search(case.query, top_k=1)
        hit_a = bool(top_a and top_a[0].chunk_id in case.relevant)
        hit_b = bool(top_b and top_b[0].chunk_id in case.relevant)

        if hit_a and hit_b:
            both += 1
        elif hit_a:
            only_a += 1
            only_a_cases.append(case)
        elif hit_b:
            only_b += 1
            only_b_cases.append(case)
        else:
            neither += 1

    return LegOverlap(
        both=both,
        only_a=only_a,
        only_b=only_b,
        neither=neither,
        label_a=a_label,
        label_b=b_label,
        only_a_cases=tuple(only_a_cases),
        only_b_cases=tuple(only_b_cases),
    )


#: 语义腿的进阶路线：先看单腿有多强，再看融合。
DENSE_STAGE_LADDER: tuple[tuple[str, PipelineFlags], ...] = (
    (
        "① 基线：只有 BM25",
        PipelineFlags(query_understanding=False, metric_rerank=False),
    ),
    (
        "② + 软路由 + 指标重排（当前最优）",
        PipelineFlags(query_understanding=True, metric_rerank=True),
    ),
    (
        "③ 只有语义腿（关掉关键词）",
        PipelineFlags(query_understanding=False, metric_rerank=False, dense=True),
    ),
    (
        "④ 两条腿融合 + 重排",
        PipelineFlags(query_understanding=True, metric_rerank=True, dense=True),
    ),
)

#: LLM 两级（**要花钱**，所以单独一条路线，必须显式 `--llm` 才跑）。
LLM_STAGE_LADDER: tuple[tuple[str, PipelineFlags], ...] = (
    (
        "① 基线：只有 BM25",
        PipelineFlags(query_understanding=False, metric_rerank=False),
    ),
    (
        "② + 软路由 + 指标重排",
        PipelineFlags(query_understanding=True, metric_rerank=True),
    ),
    (
        "③ + LLM 查询改写",
        PipelineFlags(query_understanding=True, metric_rerank=True, llm_rewrite=True),
    ),
    (
        "④ + LLM 重排",
        PipelineFlags(
            query_understanding=True,
            metric_rerank=True,
            llm_rewrite=True,
            llm_rerank=True,
        ),
    ),
)


def compare_stages(
    knowledge: KnowledgeBase | None = None,
    cases: Sequence[RetrievalCase] = (),
    metrics: Sequence = (),
    k_values: tuple[int, ...] = (1, 3, 5),
    ladder: Sequence[tuple[str, PipelineFlags]] = DEFAULT_STAGE_LADDER,
    llm: "LlmStages | None" = None,
) -> StageComparison:
    if knowledge is None:
        knowledge = load_knowledge()

    rows: list[StageRow] = []
    correctness_label = ""
    for label, flags in ladder:
        pipeline = build_pipeline(knowledge=knowledge, flags=flags, metrics=metrics, llm=llm)
        correctness_label = pipeline.correctness.label
        rows.append(
            StageRow(
                label=label,
                flags=flags,
                report=evaluate_retrieval(pipeline, cases, k_values=k_values),
            )
        )

    return StageComparison(
        cases=len(cases), rows=tuple(rows), correctness_label=correctness_label
    )


# --------------------------------------------------------------------------- #
# 拒答：双向测量
# --------------------------------------------------------------------------- #


def load_refusal_questions(path: str | Path = REFUSAL_FILE) -> tuple[str, ...]:
    """读"应该被拒答"的问句集。

    这些是**知识库范围之外**的问题（如"公司附近哪家咖啡好"）。
    它们的作用是检验"系统会不会硬答"——**这正是这个项目最在意的那类失败**。
    """
    path = Path(path)
    if not path.is_file():
        return ()
    questions: list[str] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} 第 {line_no} 行不是合法 JSON：{exc}") from exc
        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError(f"{path.name} 第 {line_no} 行缺少 query")
        questions.append(query)
    return tuple(questions)


@dataclass(frozen=True)
class RefusalReport:
    threshold: float
    in_kb_total: int
    wrongly_refused: int
    out_kb_total: int
    correctly_refused: int

    @property
    def refusal_accuracy(self) -> float:
        """库外问题被正确拒答的比例 —— **越高越安全**。"""
        return self.correctly_refused / self.out_kb_total if self.out_kb_total else 0.0

    @property
    def false_refusal_rate(self) -> float:
        """库内问题被错误拒答的比例 —— **越低越有用**。"""
        return self.wrongly_refused / self.in_kb_total if self.in_kb_total else 0.0

    def to_markdown(self) -> str:
        lines = [
            "## 拒答双向测量",
            "",
            f"当前阈值：最高检索分 < **{self.threshold:.3f}** 就拒答",
            "",
            "| 方向 | 数值 | 含义 |",
            "|---|---|---|",
            f"| 库外问题被挡住 | **{self.refusal_accuracy:.1%}**"
            f"（{self.correctly_refused}/{self.out_kb_total}）| 越高越安全：少硬答 |",
            f"| 库内问题被误拒 | **{self.false_refusal_rate:.1%}**"
            f"（{self.wrongly_refused}/{self.in_kb_total}）| 越低越有用：少漏答 |",
            "",
            "> **两个数必须一起看。** 把阈值调到无穷大，拒答正确率 100%、误伤率也 100%——",
            "> 那不是安全，那是系统完全不工作。",
            "",
        ]
        return "\n".join(lines)


def evaluate_refusal(
    knowledge: KnowledgeBase,
    in_kb_cases: Sequence[RetrievalCase],
    out_kb_questions: Sequence[str],
    boundary: RefusalBoundary | None = None,
    metrics: Sequence = (),
) -> RefusalReport:
    boundary = boundary or REFUSAL
    pipeline = build_pipeline(knowledge=knowledge, boundary=boundary, metrics=metrics)

    wrongly_refused = sum(
        1 for case in in_kb_cases if pipeline.explain(case.query).refused
    )
    correctly_refused = sum(
        1 for question in out_kb_questions if pipeline.explain(question).refused
    )

    return RefusalReport(
        threshold=boundary.min_top_score,
        in_kb_total=len(in_kb_cases),
        wrongly_refused=wrongly_refused,
        out_kb_total=len(out_kb_questions),
        correctly_refused=correctly_refused,
    )


def candidate_thresholds(
    knowledge: KnowledgeBase,
    in_kb_cases: Sequence[RetrievalCase],
    out_kb_questions: Sequence[str],
    metrics: Sequence = (),
    max_points: int = 10,
) -> tuple[float, ...]:
    """**从实际分数分布里取候选阈值**，而不是硬编码一张网格。

    ⚠️ 这是踩过一次的坑：第一版用 `[0, 0.5, 1, 1.5, 2, 3, 4]` 这种固定网格，
    结果**从 0 到 3.0 两个率一动不动**（一直是 66.7% / 0.0%），
    因为 BM25 的分数根本不是那个量级——真正的取舍发生在 3.0 到 4.0 之间，
    而网格恰好跳过了它。**扫描表看起来有 7 行，其实只有 1 行有信息。**

    所以改成：把库内/库外所有问句的最高分收上来，排序，取**相邻分数之间的中点**
    作为候选阈值。这样无论分数的量级是多少，曲线都落在有信息的位置上。
    """
    pipeline = build_pipeline(knowledge=knowledge, metrics=metrics)

    top_scores: set[float] = set()
    for case in in_kb_cases:
        hits = pipeline.search(case.query, top_k=1)
        top_scores.add(round(hits[0].score, 3) if hits else 0.0)
    for question in out_kb_questions:
        hits = pipeline.search(question, top_k=1)
        top_scores.add(round(hits[0].score, 3) if hits else 0.0)

    ordered = sorted(top_scores)
    if not ordered:
        return (0.0,)

    # 相邻分数的中点：阈值落在这里，才能把这两组分开
    midpoints = [
        round((low + high) / 2, 3) for low, high in zip(ordered, ordered[1:])
    ]
    candidates = [0.0, *midpoints, round(ordered[-1] + 0.001, 3)]

    if len(candidates) <= max_points:
        return tuple(candidates)
    # 太多就均匀采样，保证首尾都在
    step = len(candidates) / max_points
    picked = [candidates[min(int(index * step), len(candidates) - 1)] for index in range(max_points)]
    return tuple(dict.fromkeys(picked))


def sweep_thresholds(
    knowledge: KnowledgeBase,
    in_kb_cases: Sequence[RetrievalCase],
    out_kb_questions: Sequence[str],
    thresholds: Sequence[float] | None = None,
    metrics: Sequence = (),
) -> tuple[RefusalReport, ...]:
    """阈值扫描：让你看见**取舍曲线**，而不是拍一个数。

    横轴是阈值，两个率同时动。**你要选的是那个"两个数都还能接受"的点。**

    `thresholds=None` 时**从实际分数分布推导**候选值（见 `candidate_thresholds`），
    这样不会像固定网格那样错过真正的取舍区间。
    """
    if thresholds is None:
        thresholds = candidate_thresholds(knowledge, in_kb_cases, out_kb_questions, metrics)
    return tuple(
        evaluate_refusal(
            knowledge=knowledge,
            in_kb_cases=in_kb_cases,
            out_kb_questions=out_kb_questions,
            boundary=replace(REFUSAL, min_top_score=threshold),
            metrics=metrics,
        )
        for threshold in thresholds
    )
