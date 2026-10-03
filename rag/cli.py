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
    cases = build_eval_set(knowledge)
    report = evaluate_retrieval(retriever, cases, k_values=(1, 3, 5))

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.to_markdown(), encoding="utf-8")

    layers = {}
    for chunk in knowledge.chunks:
        layers[chunk.layer] = layers.get(chunk.layer, 0) + 1

    print(
        f"知识库：{len(knowledge.chunks)} 条 chunk"
        f"（指标解释 {layers.get('explanation', 0)} / 指南要点 {layers.get('guideline', 0)}）"
        f"，参考区间 {len(knowledge.reference_table)} 项**不进索引**"
    )
    print(f"检索方法：BM25（jieba 分词） · 评测用例 {report.cases} 条")
    print()
    for k in report.k_values:
        print(f"  Recall@{k}   {report.recall_at(k):.1%}")
    print(f"  MRR        {report.mrr:.3f}")
    print()
    if report.misses:
        print("未进前 5 的用例：")
        for case in report.misses:
            print(f"  {case.case_id}  {case.query}  →  期望 {case.relevant[0]}")
    else:
        print("全部用例都进了前 5。")
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
