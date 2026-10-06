"""rag 命令行入口。

    python -m rag eval                      # 检索基线（BM25 一腿）
    python -m rag eval --stages             # 分级增益：每一级值不值
    python -m rag eval --refusal            # 拒答双向测量（该挡的挡住没有 / 该答的误伤没有）
    python -m rag eval --refusal --sweep    # 阈值扫描：看取舍曲线
    python -m rag stages                    # 看链路有哪些级、当前怎么配
    python -m rag trace "尿酸高能不能吃海鲜"  # 看一条问句走完整链路的每一步
    python -m rag search "ALT 偏高怎么办"     # 手动看一眼检索结果

**默认 `eval` 不带开关时，行为与改造前完全一致** ——
这样任何新东西的增益都能和它逐字对比（有测试守着这条）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from engine.console import ensure_utf8_console
from rag.knowledge import load_knowledge
from rag.retrieval_eval import build_eval_set, evaluate_retrieval
from rag.retriever import build_retriever

ROOT = Path(__file__).resolve().parents[1]


def _all_cases(knowledge):
    cases = build_eval_set(knowledge)
    return (
        tuple(c for c in cases if c.source == "template"),
        tuple(c for c in cases if c.source == "user"),
    )


def cmd_eval(args: argparse.Namespace) -> int:
    knowledge = load_knowledge()

    # ---- 分支一：分级增益（不改默认路径）----
    if args.stages:
        return _eval_stages(args, knowledge)

    # ---- 分支二：拒答双向测量 ----
    if args.refusal:
        return _eval_refusal(args, knowledge)

    # ---- 默认路径：与改造前完全一致 ----
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
    print("检索方法：BM25（jieba 分词，单腿基线）")
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
    print()
    print("  想看新链路值不值：python -m rag eval --stages")
    return 0


def _eval_stages(args: argparse.Namespace, knowledge) -> int:
    """分级增益：同一套问句集，逐级加开关。"""
    from rag.stage_eval import compare_stages

    template_cases, user_cases = _all_cases(knowledge)
    cases = template_cases + user_cases

    comparison = compare_stages(knowledge=knowledge, cases=cases)

    print(f"分级增益评测 · 用例 {comparison.cases} 条（模板 + 真实）")
    print()
    header = f"{'级':<24} Recall@1  Recall@3   MRR     ΔRecall@1"
    print(f"  {header}")
    print(f"  {'-' * len(header)}")
    previous = None
    for row in comparison.rows:
        delta = ""
        if previous is not None:
            change = row.recall(1) - previous.recall(1)
            delta = f"{change:+.1%}" if abs(change) >= 0.0005 else "无变化"
        print(
            f"  {row.label:<24} {row.recall(1):>7.1%}  {row.recall(3):>7.1%}  "
            f"{row.report.mrr:>5.3f}   {delta}"
        )
        previous = row
    print()

    out = Path(args.stages_report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(comparison.to_markdown(), encoding="utf-8")
    print(f"  报告 -> {out}")
    return 0


def _eval_refusal(args: argparse.Namespace, knowledge) -> int:
    """拒答：库外该挡的挡住没有、库内该答的误伤没有。**两个数一起看。**"""
    from rag.stage_eval import evaluate_refusal, load_refusal_questions, sweep_thresholds

    template_cases, user_cases = _all_cases(knowledge)
    in_kb = template_cases + user_cases
    out_kb = load_refusal_questions()

    if not out_kb:
        print("[x] 没有拒答问句集（eval/refusal-questions.jsonl）")
        return 2

    report = evaluate_refusal(knowledge, in_kb, out_kb)

    print(f"拒答测量 · 库内 {report.in_kb_total} 条 / 库外 {report.out_kb_total} 条")
    print()
    print(f"  库外问题被挡住   {report.refusal_accuracy:.1%}"
          f"  （{report.correctly_refused}/{report.out_kb_total}）  越高越安全")
    print(f"  库内问题被误拒   {report.false_refusal_rate:.1%}"
          f"  （{report.wrongly_refused}/{report.in_kb_total}）  越低越有用")
    print()

    text = report.to_markdown()

    if args.sweep:
        # 阈值候选**从实际分数分布推导**，不用硬编码网格——
        # 固定网格会错过真正的取舍区间（实测过：0→3.0 两个率一动不动）。
        rows = sweep_thresholds(knowledge, in_kb, out_kb)
        table = [
            "## 阈值扫描（取舍曲线）",
            "",
            "候选阈值**从实际分数分布里推导**（相邻最高分的中点），",
            "所以无论 BM25 分数是什么量级，曲线都会落在有信息的位置。",
            "",
            "**你要选的是「两个数都还能接受」的那个点。**",
            "",
            "| 阈值 | 库外拒答率 | 库内误伤率 |",
            "|---|---|---|",
        ]
        for row in rows:
            mark = " ← 当前" if abs(row.threshold - report.threshold) < 1e-9 else ""
            table.append(
                f"| {row.threshold:.3f}{mark} | {row.refusal_accuracy:.1%} "
                f"| {row.false_refusal_rate:.1%} |"
            )
        table.append("")
        table.append(
            "> 阈值越大 → 越倾向于拒答。库外拒答率会升到 100%，但库内误伤率也会升。"
        )
        table.append("> **没有免费的午餐**，这个点由你定（写在 `rag/boundary.py`）。")
        table.append("")
        text += "\n" + "\n".join(table)
        print("  阈值扫描：")
        for row in rows:
            print(
                f"    {row.threshold:>4.1f}  →  库外挡 {row.refusal_accuracy:>5.1%}"
                f"   库内误伤 {row.false_refusal_rate:>5.1%}"
            )
        print()

    out = Path(args.refusal_report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"  报告 -> {out}")
    print()
    print("  ⚠️ 阈值是产品判断，改在 rag/boundary.py —— 那里是你的文件。")
    return 0


def cmd_stages(args: argparse.Namespace) -> int:
    """看链路有哪些级、当前怎么配。"""
    from rag.pipeline import build_pipeline

    pipeline = build_pipeline()
    print(pipeline.describe())
    print()
    print("  跑分级增益：python -m rag eval --stages")
    print("  看一条问句：python -m rag trace \"尿酸高能不能吃海鲜\"")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    """看一条问句走完整链路的每一步。**这是排查检索问题最快的入口。**"""
    from rag.pipeline import build_pipeline

    pipeline = build_pipeline()
    plan = pipeline.plan(args.query)

    print(f"问句：{args.query}")
    print()
    print(f"① 查询理解：{plan.describe()}")
    print(f"   命中词：{list(plan.matched_terms) or '（无）'}")
    print(f"   说明：{plan.note}")
    print()

    hits = pipeline.search(args.query, top_k=args.top_k)
    print(f"② 召回 + ③ 重排（链路 {pipeline.name}）：")
    if not hits:
        print("   （没有命中）")
    for position, hit in enumerate(hits, start=1):
        print(f"   {position}. [{hit.score:.3f}] {hit.chunk_id}  {hit.title}")
    print()

    result = pipeline.explain(args.query, top_k=args.top_k)
    print(f"④ 拒答判断：{'拒答' if result.refused else '回答'}")
    print(f"   理由：{result.reason}")
    print(f"   阈值：最高分 < {pipeline.boundary.min_top_score}（改在 rag/boundary.py）")
    print()
    print(f"⑤ 回答：{result.answer}")
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
    eval_cmd.add_argument(
        "--stages", action="store_true", help="改跑分级增益：每一级值不值"
    )
    eval_cmd.add_argument(
        "--stages-report",
        default=str(ROOT / "reports" / "rag-stages-report.md"),
        help="分级增益报告路径",
    )
    eval_cmd.add_argument(
        "--refusal", action="store_true", help="改跑拒答双向测量"
    )
    eval_cmd.add_argument(
        "--sweep", action="store_true", help="配合 --refusal：打印阈值扫描表"
    )
    eval_cmd.add_argument(
        "--refusal-report",
        default=str(ROOT / "reports" / "refusal-report.md"),
        help="拒答报告路径",
    )
    eval_cmd.set_defaults(func=cmd_eval)

    stages = subparsers.add_parser("stages", help="看链路有哪些级、当前怎么配")
    stages.set_defaults(func=cmd_stages)

    trace = subparsers.add_parser("trace", help="看一条问句走完整链路的每一步")
    trace.add_argument("query")
    trace.add_argument("--top-k", type=int, default=5)
    trace.set_defaults(func=cmd_trace)

    search = subparsers.add_parser("search", help="手动检索一条问句（基线单腿）")
    search.add_argument("query", help="问句")
    search.add_argument("--top-k", type=int, default=5)
    search.set_defaults(func=cmd_search)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = build_parser().parse_args(argv)
    return int(args.func(args))
