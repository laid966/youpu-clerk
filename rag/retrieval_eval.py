"""检索评测：Recall@k 与 MRR 基线。

## 为什么指标要报好几个 k

语料只有十几条 chunk，**Recall@5 几乎是白送的**（随便返回 5 条就能覆盖小语料的一大半），
它在这个规模下没有区分度。所以同时报：

- **Recall@1**：正确答案排第一的比例——小语料下这才是真正有区分度的指标
- Recall@3 / Recall@5：看"有没有被排进前几"
- **MRR**（平均倒数排名）：排名越靠前分越高，对排序质量更敏感

## 标准答案的诚实说明

这里的问句是**模板生成的**，而且每条的正确答案只有一个 chunk，
属于"干净但简单"的评测集。真实用户的问法会更模糊、会带错别字、会跨多个指标——
所以**:这份数字是基线，不是最终成绩**。

扩到真实问句是分工里"人的部分"（`eval/questions.jsonl`），
届时用同一套指标重跑，就能看出 BM25 在真实问法下掉多少。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from rag.knowledge import KnowledgeBase
from rag.retriever import Retriever

__all__ = [
    "MisRanked",
    "RetrievalCase",
    "RetrievalReport",
    "build_eval_set",
    "evaluate_retrieval",
    "load_user_questions",
]

DEFAULT_K_VALUES = (1, 3, 5)
ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_FILE = ROOT / "eval" / "questions.jsonl"

SOURCE_TEMPLATE = "template"
SOURCE_USER = "user"


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    relevant: tuple[str, ...]
    note: str = ""
    source: str = SOURCE_TEMPLATE


@dataclass(frozen=True)
class MisRanked:
    case: RetrievalCase
    rank: int
    top1_chunk_id: str


@dataclass(frozen=True)
class RetrievalReport:
    k_values: tuple[int, ...]
    cases: int
    hits_at: Mapping[int, int]
    mrr: float
    misses: tuple[RetrievalCase, ...]
    mis_ranked: tuple[MisRanked, ...]
    first_hit_ranks: Mapping[str, int]

    def recall_at(self, k: int) -> float:
        return self.hits_at.get(k, 0) / self.cases if self.cases else 0.0

    def to_markdown(self, retriever_note: str = "BM25（jieba 分词）") -> str:
        lines: list[str] = []
        lines.append("# 检索评测报告（A4 基线）")
        lines.append("")
        lines.append(f"- 检索方法：**{retriever_note}**")
        lines.append(f"- 评测用例：**{self.cases}** 条（模板生成，单条标准答案）")
        lines.append("")
        lines.append("## 指标")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|---|---|")
        for k in self.k_values:
            lines.append(f"| Recall@{k} | **{self.recall_at(k):.1%}** |")
        lines.append(f"| MRR | **{self.mrr:.3f}** |")
        lines.append("")
        lines.append("> 语料只有十几条 chunk，Recall@5 几乎没有区分度；**Recall@1 才是这个规模下的关键指标**。")
        lines.append("")

        lines.append("## 排序诊断：正确答案没排第一的用例")
        lines.append("")
        lines.append("这一节比总分更有用——它告诉你 BM25 到底在什么问法上会输。")
        lines.append("")
        if self.mis_ranked:
            lines.append("| 编号 | 问句 | 期望 | 实际排第一 | 名次 |")
            lines.append("|---|---|---|---|---|")
            for item in self.mis_ranked:
                lines.append(
                    f"| {item.case.case_id} | {item.case.query} | `{item.case.relevant[0]}` "
                    f"| `{item.top1_chunk_id}` | {item.rank} |"
                )
        else:
            lines.append("- 无")
        lines.append("")

        lines.append("## 未进前 5 的用例")
        lines.append("")
        if self.misses:
            lines.append("| 编号 | 问句 | 期望 chunk |")
            lines.append("|---|---|---|")
            for case in self.misses:
                lines.append(f"| {case.case_id} | {case.query} | `{case.relevant[0]}` |")
        else:
            lines.append("- 无")
        lines.append("")
        return "\n".join(lines)


def load_user_questions(
    path: str | Path = QUESTIONS_FILE, knowledge: KnowledgeBase | None = None
) -> tuple[RetrievalCase, ...]:
    """读**真实问句**（`eval/questions.jsonl`）。

    格式（每行一个 JSON）：
        {"query": "转氨酶高是不是熬夜熬的", "metric": "alt", "note": "口语化"}
        {"query": "尿酸高能不能吃海鲜", "guideline": "urate-diet"}

    `metric` 与 `guideline` **必须写且只能写一个**——它就是标准答案。
    这样你写问句时不需要知道内部 chunk id 长什么样，只写指标代码或指南 id 就行。

    格式错了会直接报错（带上行号），不会静默跳过——
    静默跳过会让你的评测集悄悄变少，而你毫无察觉。
    """
    path = Path(path)
    if not path.is_file():
        return ()
    if knowledge is None:
        from rag.knowledge import load_knowledge

        knowledge = load_knowledge()

    cases: list[RetrievalCase] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} 第 {line_no} 行不是合法 JSON：{exc}") from exc

        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError(f"{path.name} 第 {line_no} 行缺少 query")

        metric = payload.get("metric")
        guideline = payload.get("guideline")
        if bool(metric) == bool(guideline):
            raise ValueError(
                f"{path.name} 第 {line_no} 行必须且只能给出 metric 或 guideline 之一"
            )

        if metric:
            chunk_id = f"kb://metric/{metric}"
        else:
            chunk_id = f"kb://guideline/{guideline}"

        if knowledge.by_id(chunk_id) is None:
            raise ValueError(
                f"{path.name} 第 {line_no} 行指向了不存在的知识条目：{chunk_id}"
            )

        cases.append(
            RetrievalCase(
                case_id=f"U-{len(cases) + 1:03d}",
                query=query,
                relevant=(chunk_id,),
                note=str(payload.get("note", "")),
                source=SOURCE_USER,
            )
        )
    return tuple(cases)


def build_eval_set(
    knowledge: KnowledgeBase, user_questions_path: str | Path | None = QUESTIONS_FILE
) -> tuple[RetrievalCase, ...]:
    """模板集 + 真实问句集。

    模板集保证基准稳定、每次都能跑；真实问句集才是真正说明问题的那个数字。
    两者分开展示，不混在一起平均——否则真实问法的效果会被模板题稀释掉。
    """
    metric_chunks = [chunk for chunk in knowledge.chunks if chunk.layer == "explanation"]
    guideline_chunks = [chunk for chunk in knowledge.chunks if chunk.layer == "guideline"]

    cases: list[RetrievalCase] = []
    index = 0

    for chunk in sorted(metric_chunks, key=lambda item: item.metric_code or ""):
        code = chunk.metric_code or ""
        name = chunk.title.split("（", 1)[0]
        abbr = chunk.title.split("（", 1)[1].split("，", 1)[0] if "（" in chunk.title else code.upper()

        for template, note in (
            (f"{abbr} 偏高怎么办", "只用缩写提问"),
            (f"{name} 是什么意思", "只用全称提问"),
            (f"{name} 高了要紧吗", "口语化提问"),
        ):
            index += 1
            cases.append(
                RetrievalCase(
                    case_id=f"Q-{index:03d}",
                    query=template,
                    relevant=(chunk.chunk_id,),
                    note=note,
                    source=SOURCE_TEMPLATE,
                )
            )

    guideline_queries = {
        "critical-value": (
            "危急值是什么，看到危急值应该怎么办",
            (),
        ),
        "recheck": ("复查有什么意义，一般隔多久复查一次", ()),
        "fasting": ("抽血前需要空腹多久", ()),
        "urate-diet": ("尿酸高在饮食上要注意什么", ()),
        "lipid-lifestyle": ("血脂偏高生活方式上要注意什么", ()),
        # 这条是**真的模棱两可**：问"血红蛋白偏低和哪些因素有关"，
        # 指南里那条"血红蛋白偏低的一般说明"是直接答案，
        # 而血红蛋白指标卡里也写了"常见相关因素"。两个都是合理答案，
        # 所以标准答案标两个——这不是为了让分数好看，是标准答案本来就该是它。
        "anemia": ("血红蛋白偏低可能和哪些因素有关", ("kb://metric/hgb",)),
        "disclaimer": ("这个工具能做什么，不能做什么", ()),
    }
    for chunk in sorted(guideline_chunks, key=lambda item: item.chunk_id):
        note_id = chunk.chunk_id.rsplit("/", 1)[-1]
        if note_id not in guideline_queries:
            raise ValueError(f"指南要点 {note_id} 还没有对应的评测问句")
        query, extra_relevant = guideline_queries[note_id]
        index += 1
        cases.append(
            RetrievalCase(
                case_id=f"Q-{index:03d}",
                query=query,
                relevant=(chunk.chunk_id,) + extra_relevant,
                note="指南要点类提问",
                source=SOURCE_TEMPLATE,
            )
        )

    if user_questions_path is not None:
        cases.extend(load_user_questions(user_questions_path, knowledge))

    return tuple(cases)


def evaluate_retrieval(
    retriever: Retriever,
    cases: Sequence[RetrievalCase],
    k_values: tuple[int, ...] = DEFAULT_K_VALUES,
) -> RetrievalReport:
    max_k = max(k_values)
    hits_at: dict[int, int] = {k: 0 for k in k_values}
    reciprocal_ranks: list[float] = []
    misses: list[RetrievalCase] = []
    mis_ranked: list[MisRanked] = []
    first_hit_ranks: dict[str, int] = {}

    for case in cases:
        results = retriever.search(case.query, top_k=max_k)
        ranked_ids = [hit.chunk_id for hit in results]
        top1 = ranked_ids[0] if ranked_ids else "(无结果)"

        rank = 0
        for position, chunk_id in enumerate(ranked_ids, start=1):
            if chunk_id in case.relevant:
                rank = position
                break

        if rank:
            first_hit_ranks[case.case_id] = rank
            reciprocal_ranks.append(1.0 / rank)
            for k in k_values:
                if rank <= k:
                    hits_at[k] += 1
            if rank > 1:
                mis_ranked.append(MisRanked(case=case, rank=rank, top1_chunk_id=top1))
        else:
            reciprocal_ranks.append(0.0)
            misses.append(case)

    return RetrievalReport(
        k_values=tuple(k_values),
        cases=len(cases),
        hits_at=hits_at,
        mrr=sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0,
        misses=tuple(misses),
        mis_ranked=tuple(mis_ranked),
        first_hit_ranks=first_hit_ranks,
    )
