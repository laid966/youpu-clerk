"""agent 命令行入口。

    python -m agent prompts                        # 看有哪些提示词版本
    python -m agent check "这段解释文本"             # 手动试一条
    python -m agent eval-semantic --positives 24 --negatives 20

`eval-semantic` 就是**你的提示词的成绩单**：跑一次，看召回、误报、错误三个数字。
第一次会真调模型（花钱，但极少）；之后同一版提示词重跑会走缓存，不再花钱。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agent.eval_semantic import build_semantic_cases, evaluate_semantic
from agent.judge import CachedJudge, build_judge
from agent.prompts import CURRENT_VERSION, current_prompt, prompt_for
from agent.semantic_check import check_text
from audit.inject import DEFECT_KINDS, build_injected_dataset
from audit.pipeline import load_metrics
from audit.synth import DEFAULT_SEED, generate_reports
from engine.console import ensure_utf8_console

ROOT = Path(__file__).resolve().parents[1]


def cmd_prompts(args: argparse.Namespace) -> int:
    from agent.prompts import _REGISTRY

    print(f"当前版本：{CURRENT_VERSION}")
    print(f"可用版本：{', '.join(sorted(_REGISTRY))}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    judge = build_judge(use_cache=not args.no_cache)
    prompt = prompt_for(args.prompt)
    outcome = check_text(args.text, args.target, prompt, judge)

    print(f"提示词版本：{args.prompt}")
    print(f"文本：{args.text}")
    print()
    if outcome.error:
        print(f"[错误] {outcome.error}")
        print("注意：错误**不等于**没有越界，必须单独处理。")
        return 2
    if outcome.finding is None:
        print("判定：没有越界")
    else:
        print(f"判定：越界（{outcome.finding.category}，由 {outcome.finding.decided_by} 判出）")
        print(f"证据：{outcome.finding.evidence}")
    return 0


def cmd_eval_semantic(args: argparse.Namespace) -> int:
    metrics = load_metrics()
    judged_cases = generate_reports(count=args.count, metrics=metrics, seed=DEFAULT_SEED)
    injected = build_injected_dataset(judged_cases, metrics, seed=DEFAULT_SEED)
    semantic_cases = build_semantic_cases(
        injected, positives=args.positives, negatives=args.negatives
    )

    judge = build_judge(use_cache=not args.no_cache)
    prompt = prompt_for(args.prompt)
    report = evaluate_semantic(semantic_cases, prompt, judge, args.prompt)

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.to_markdown(), encoding="utf-8")

    print(f"提示词版本 {report.prompt_version} · 用例 {len(semantic_cases)} 条")
    print()
    print(f"  正例（改写型越界）  {report.positives} 条")
    print(f"  抓住                {report.caught} 条")
    print(f"  召回率              {report.recall:.1%}   ← 词表在这里是 0%")
    print()
    print(f"  负例（正常解释）    {report.negatives} 条")
    print(f"  误报                {report.false_positives} 条")
    print(f"  误报率              {report.false_positive_rate:.1%}   ← 死穴，越低越好")
    print()
    print(f"  错误（解析/调用失败）{report.errors} 条   ← 单独统计，不算「无越界」")
    if isinstance(judge, CachedJudge):
        print(f"  缓存命中 / 未命中   {judge.hits} / {judge.misses}")
    print()
    if report.missed:
        print("漏掉的越界（你的改进空间）：")
        for case in report.missed[:5]:
            print(f"  {case.case_id}  {case.target}  …{case.text[-50:]}")
        if len(report.missed) > 5:
            print(f"  …还有 {len(report.missed) - 5} 条，见报告")
    print()
    print(f"  报告 -> {out}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """端到端跑审计图，产出「确定性层 vs 加语义层」的对比数字。"""
    from agent.policy import AUDIT_POLICY
    from agent.runner import run_batch
    from audit.evaluate import evaluate

    # 允许在命令行上临时换策略，用来对比不同取舍的代价——
    # 这样"该用哪个策略"是一个**可以拿数字回答的问题**，而不是拍脑袋。
    policy = AUDIT_POLICY
    if args.scope or args.max_calls is not None:
        from dataclasses import replace

        policy = replace(
            policy,
            inspect_scope=args.scope or policy.inspect_scope,
            max_model_calls_per_artifact=(
                args.max_calls if args.max_calls is not None else policy.max_model_calls_per_artifact
            ),
        )

    metrics = load_metrics()
    judged_cases = generate_reports(count=args.count, metrics=metrics, seed=DEFAULT_SEED)
    injected = build_injected_dataset(judged_cases, metrics, seed=DEFAULT_SEED)

    cases = injected[: args.limit]
    judged_subset = judged_cases[: args.limit]

    checkpointer = None
    if args.persist:
        import sqlite3

        from langgraph.checkpoint.sqlite import SqliteSaver

        conn = sqlite3.connect(args.persist, check_same_thread=False)
        checkpointer = SqliteSaver(conn)

    # 确定性层单独的成绩（不花模型钱），用于对比语义层的增量
    deterministic_only = None
    if not args.no_compare:
        deterministic_only = evaluate(cases, judged_subset, metrics).recall_overall

    judge = build_judge(use_cache=not args.no_cache)
    report = run_batch(
        cases=cases,
        judged_cases=judged_subset,
        metrics=metrics,
        policy=policy,
        judge=judge,
        prompt=prompt_for(args.prompt),
        checkpointer=checkpointer,
        deterministic_only_recall=deterministic_only,
    )

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.to_markdown(), encoding="utf-8")

    print(f"审计 {report.cases} 份产物 · 策略：{report.policy}")
    print(f"提示词：{report.prompt_version}")
    print()
    print(f"  已知缺陷      {report.total_defects} 条")
    print(f"  抓到          {report.caught} 条")
    print(f"  召回率        {report.recall:.1%}")
    print(f"  误报          {report.false_positives} 条（干净样本 {report.clean_cases} 份）")
    print(f"  精确率        {report.precision:.1%}")
    print(f"  需人工复核    {report.escalated_cases} 份")
    print(f"  模型调用      {report.model_calls} 次  ← 这是语义层的成本")
    if deterministic_only is not None:
        print()
        print(f"  只有确定性层  {deterministic_only:.1%}")
        print(f"  加上语义层    {report.recall:.1%}")
        print(f"  语义层增量    {report.recall - deterministic_only:+.1%}")
    print()
    print("按缺陷类型的召回：")
    for kind in DEFECT_KINDS:
        caught, total = report.recall_by_kind.get(kind, (0, 0))
        rate = f"{caught / total:5.1%}" if total else "    —"
        print(f"  {kind:<22} {caught:>3} / {total:<4} {rate}")
    print()
    print(f"  报告 -> {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agent", description="审计 agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prompts = subparsers.add_parser("prompts", help="列出提示词版本")
    prompts.set_defaults(func=cmd_prompts)

    check = subparsers.add_parser("check", help="手动检查一段文本")
    check.add_argument("text", help="待检查的解释文本")
    check.add_argument("--target", default="manual", help="指标标识（用于报告）")
    check.add_argument("--prompt", default=CURRENT_VERSION)
    check.add_argument("--no-cache", action="store_true")
    check.set_defaults(func=cmd_check)

    eval_cmd = subparsers.add_parser("eval-semantic", help="评测语义检查（你的提示词）")
    eval_cmd.add_argument("--count", type=int, default=200, help="注入样本数量（用于取样）")
    eval_cmd.add_argument("--positives", type=int, default=24, help="正例条数（改写型越界）")
    eval_cmd.add_argument("--negatives", type=int, default=20, help="负例条数（正常解释）")
    eval_cmd.add_argument("--prompt", default=CURRENT_VERSION, help="提示词版本")
    eval_cmd.add_argument("--no-cache", action="store_true", help="不走缓存（真的重调模型）")
    eval_cmd.add_argument(
        "--report", default=str(ROOT / "reports" / "semantic-report.md")
    )
    eval_cmd.set_defaults(func=cmd_eval_semantic)

    audit_cmd = subparsers.add_parser(
        "audit", help="端到端跑审计图（确定性层 + 语义层），产出两层对比数字"
    )
    audit_cmd.add_argument("--count", type=int, default=60, help="生成多少份注入样本供取样")
    audit_cmd.add_argument("--limit", type=int, default=20, help="实际审计多少份（控制成本）")
    audit_cmd.add_argument("--prompt", default=CURRENT_VERSION, help="提示词版本")
    audit_cmd.add_argument("--no-cache", action="store_true", help="不走缓存")
    audit_cmd.add_argument("--no-compare", action="store_true", help="不算确定性层对照")
    audit_cmd.add_argument("--persist", help="SQLite 路径：持久化图状态（可续跑、可回放）")
    audit_cmd.add_argument(
        "--scope",
        choices=["abnormal_only", "all", "with_citations_only"],
        help="临时覆盖策略里的检查范围（用于对比不同取舍的代价）",
    )
    audit_cmd.add_argument(
        "--max-calls", type=int, default=None, help="临时覆盖单份模型调用上限"
    )
    audit_cmd.add_argument(
        "--report", default=str(ROOT / "reports" / "audit-report.md")
    )
    audit_cmd.set_defaults(func=cmd_audit)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except RuntimeError as exc:  # 例如缺 API key
        print(f"[x] {exc}")
        return 2
