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
from audit.inject import build_injected_dataset
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

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except RuntimeError as exc:  # 例如缺 API key
        print(f"[x] {exc}")
        return 2
