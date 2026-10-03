"""命令行入口。

用法（在本项目根目录下运行）：

    python -m engine check  --all                      # 自检全部判定域，报告写到 reports/
    python -m engine check  --domain domain/airline-fare-sample/domain.yaml --samples 5000
    python -m engine gen    --all --count 1000         # 生成评测用例
    python -m engine decide --domain domain/airline-fare-sample/domain.yaml --facts facts.json

设计意图：所有"能跑出数字"的操作都必须有一条命令能一键复现。
评测如果不能一键重跑，就等于没有评测。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.adjudicate import AdjudicationError, adjudicate
from engine.console import ensure_utf8_console
from engine.domain import DomainError, load_domain
from engine.sample_gen import DEFAULT_SEED, generate_cases, write_dataset
from engine.selfcheck import DEFAULT_SAMPLES, run_selfcheck

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOMAIN_GLOB = "domain/**/domain.yaml"


def _read_json_text(source: str) -> str:
    """读 JSON 文本。

    用 utf-8-sig 而不是 utf-8：Windows 上的记事本、PowerShell 的
    `Set-Content -Encoding UTF8` 等工具会在文件开头写一个 BOM（\\ufeff），
    用 utf-8 解出来的第一个字符就是 BOM，`json.loads` 会直接报
    "Expecting value: line 1 column 1"。这不是用户写错了，是工具习惯问题，
    所以由引擎这边消化掉——真实用户一定会遇到。
    """
    if source == "-":
        return sys.stdin.buffer.read().decode("utf-8-sig")

    path = Path(source)
    if not path.is_file():
        raise SystemExit(f"找不到事实文件：{path}")
    return path.read_bytes().decode("utf-8-sig")


def _resolve_domain_paths(args: argparse.Namespace) -> list[Path]:
    if getattr(args, "all", False):
        paths = sorted(ROOT.glob(DEFAULT_DOMAIN_GLOB))
        if not paths:
            raise SystemExit(f"没有找到任何判定域（模式：{ROOT / DEFAULT_DOMAIN_GLOB}）")
        return paths

    if not getattr(args, "domain", None):
        raise SystemExit("请用 --domain 指定一个判定域，或用 --all 处理全部")

    path = Path(args.domain)
    if not path.is_absolute() and not path.exists():
        candidate = ROOT / path
        if candidate.exists():
            path = candidate
    return [path]


def cmd_check(args: argparse.Namespace) -> int:
    failed = False
    for path in _resolve_domain_paths(args):
        domain = load_domain(path)
        report = run_selfcheck(domain, samples=args.samples, seed=args.seed)

        out = (
            Path(args.report)
            if args.report
            else ROOT / "reports" / f"selfcheck-{domain.name}.md"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.to_markdown(), encoding="utf-8")

        print(
            f"[{domain.name}] 样本 {report.samples} | "
            f"覆盖率 {report.coverage_rate:.1%} | "
            f"错误 {len(report.errors)} | 警告 {len(report.warnings)} | 报告 -> {out}"
        )
        for item in report.errors:
            print(f"    [x] {item}")
        for item in report.warnings:
            print(f"    [!] {item}")

        failed = failed or not report.ok

    return 1 if failed else 0


def cmd_gen(args: argparse.Namespace) -> int:
    for path in _resolve_domain_paths(args):
        domain = load_domain(path)
        cases = generate_cases(domain, count=args.count, seed=args.seed)

        out = Path(args.out).parent / f"{Path(args.out).stem}-{domain.name}.jsonl"
        sample_out = Path(args.sample_out).parent / f"{Path(args.sample_out).stem}-{domain.name}.md"
        write_dataset(cases, out, sample_out)

        verdicts: dict[str, int] = {}
        escalate = 0
        for case in cases:
            verdicts[case.expected["final_verdict"]] = (
                verdicts.get(case.expected["final_verdict"], 0) + 1
            )
            escalate += 1 if case.expected["escalated"] else 0

        summary = "  ".join(f"{key}={value}" for key, value in sorted(verdicts.items()))
        print(f"[{domain.name}] 生成 {len(cases)} 条 | 需转人工 {escalate} 条 | {summary}")
        print(f"    数据集 -> {out}")
        print(f"    人读抽样 -> {sample_out}")

    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    domain = load_domain(_resolve_domain_paths(args)[0])

    text = _read_json_text(args.facts or "-")
    try:
        facts = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"[x] 事实文件不是合法 JSON：{exc}", file=sys.stderr)
        return 2

    if not isinstance(facts, dict):
        print("[x] 事实文件的最外层必须是一个 JSON 对象（字段名 -> 取值）", file=sys.stderr)
        return 2

    result = adjudicate(domain, facts)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m engine",
        description="rulecheck 确定性引擎：规则自检、评测用例生成、单次判定",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="对规则集做自检（反例搜索）")
    check.add_argument("--domain", help="判定域 YAML 路径")
    check.add_argument("--all", action="store_true", help="检查全部示例域")
    check.add_argument("--samples", type=int, default=DEFAULT_SAMPLES, help="取样数量")
    check.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子（固定即可复现）")
    check.add_argument("--report", help="报告输出路径")
    check.set_defaults(func=cmd_check)

    gen = subparsers.add_parser("gen", help="自动生成评测用例（含标准答案）")
    gen.add_argument("--domain", help="判定域 YAML 路径")
    gen.add_argument("--all", action="store_true", help="为全部示例域生成")
    gen.add_argument("--count", type=int, default=1000, help="用例数量")
    gen.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")
    gen.add_argument("--out", default=str(ROOT / "eval" / "dataset.jsonl"))
    gen.add_argument("--sample-out", default=str(ROOT / "eval" / "dataset.sample.md"))
    gen.set_defaults(func=cmd_gen)

    decide = subparsers.add_parser("decide", help="对一组事实做一次判定")
    decide.add_argument("--domain", required=True, help="判定域 YAML 路径")
    decide.add_argument("--facts", help="事实 JSON 文件路径（省略则从标准输入读）")
    decide.set_defaults(func=cmd_decide)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (DomainError, AdjudicationError) as exc:
        print(f"[x] {exc}", file=sys.stderr)
        return 2
