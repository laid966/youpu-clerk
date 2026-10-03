"""rag 命令行入口。

    python -m rag eval                 # 跑检索评测，产出 Recall@k / MRR
    python -m rag eval --top-k 5
    python -m rag search "ALT 偏高怎么办"   # 手动看一眼检索结果
"""

from __future__ import annotations

import argparse
from pathlib import Path

from engine.console import ensure_utf8_console
from rag.knowledge import load_knowledge
from rag.retrieval_eval import build_eval_set, evaluate_retrieval
from rag.retriever import build_retriever

ROOT = Path(__file__).resolve().parents[1]


def cmd_eval(args: argparse.Namespace) -> int:
    knowledge = load_knowledge()
    retriever = build_retriever(knowledge)
    all_cases = build_eval_set(knowledge)

    template_cases = tuple(c for c in all_cases if c.source == "template")
    user_cases = tuple(c for c in all_cases if c.source == "user")

    template_report = evaluate_retrieval(retriever, template_cases, k_values=(1, 3, 5))
    user_report = (
        evaluate_retrieval(retriever, user_cases, k_values=(1, 3, 5)) if user_cases else None
    )

    layers: dict[str, int] = {}
    for chunk in knowledge.chunks:
        layers[chunk.layer] = layers.get(chunk.layer, 0) + 1

    print(
        f"知识库：{len(knowledge.chunks)} 条 chunk"
        f"（指标解释 {layers.get('explanation', 0)} / 指南要点 {layers.get('guideline', 0)}）"
        f"，参考区间 {len(knowledge.reference_table)} 项**不进索引**"
    )
    print("检索方法：BM25（jieba 分词）")
    print()

    def show(name: str, report, count: int) -> None:
        if count == 0:
            print(f"  {name}：0 条（还没有内容）")
            return
        print(
            f"  {name}（{count} 条）：Recall@1 {report.recall_at(1):.1%}"
            f" · Recall@3 {report.recall_at(3):.1%} · MRR {report.mrr:.3f}"
        )

    show("模板集", template_report, len(template_cases))
    show("真实问句集", user_report, len(user_cases))
    print()

    if not user_cases:
        print("  ⚠️ 还没有真实问句。模板题太干净，分数会虚高——")
        print("     请在 eval/questions.jsonl 里写你自己的问法（目标 100 条）。")
        print()

    if template_report.misses:
        print("模板集里没进前 5 的用例：")
        for case in template_report.misses:
            print(f"  {case.case_id}  {case.query}  →  期望 {case.relevant[0]}")

    # 报告以模板集为主，真实问句集单独一节
    report_text = template_report.to_markdown("BM25（jieba 分词）+ 模板问句")
    if user_report is not None:
        report_text += "\n\n---\n\n" + user_report.to_markdown(
            "BM25（jieba 分词）+ 真实问句"
        )
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_text, encoding="utf-8")
    print()
    print(f"  报告 -> {out}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    knowledge = load_knowledge()
    retriever = build_retriever(knowledge)
    hits = retriever.search(args.query, top_k=args.top_k)

    print(f"问句：{args.query}")
    print()
    if not hits:
        print("没有命中任何 chunk。")
        return 0
    for position, hit in enumerate(hits, start=1):
        print(f"{position}. [{hit.score:.3f}] {hit.chunk_id}  {hit.title}")
        print(f"   {hit.text[:80]}…")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rag", description="知识库与检索")
    subparsers = parser.add_subparsers(dest="command", required=True)

    eval_cmd = subparsers.add_parser("eval", help="跑检索评测（Recall@k / MRR）")
    eval_cmd.add_argument("--report", default=str(ROOT / "reports" / "retrieval-report.md"))
    eval_cmd.set_defaults(func=cmd_eval)

    search = subparsers.add_parser("search", help="手动检索一条问句")
    search.add_argument("query", help="问句")
    search.add_argument("--top-k", type=int, default=5)
    search.set_defaults(func=cmd_search)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = build_parser().parse_args(argv)
    return int(args.func(args))
