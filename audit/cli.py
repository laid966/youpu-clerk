"""auditkit 命令行入口。

    python -m audit synth --count 200          # 生成判决样本（当前阶段不含模型调用）
    python -m audit synth --count 50 --seed 7  # 换个种子

设计意图与 engine 保持一致：**所有能跑出数字的操作都必须一条命令可复现**。
评测如果不能一键重跑，就等于没有评测。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from audit.inject import (
    CLEAN_SHARE,
    DEFECT_KINDS,
    DEFECT_LABELS,
    build_injected_dataset,
    capability_report,
)
from audit.inject import write_dataset as write_injected_dataset
from audit.pipeline import load_metrics, severity_rank
from audit.synth import DEFAULT_SEED, generate_reports, write_dataset
from engine.console import ensure_utf8_console

ROOT = Path(__file__).resolve().parents[1]


def cmd_synth(args: argparse.Namespace) -> int:
    metrics = load_metrics()
    cases = generate_reports(count=args.count, metrics=metrics, seed=args.seed)

    out = Path(args.out)
    sample_out = Path(args.sample_out)
    write_dataset(cases, out, sample_out, sample_size=args.sample_size)

    profile_counts = Counter(profile for profile, _ in cases)
    worst_counts = Counter(judged.worst_verdict() for _, judged in cases)
    abnormal_counts: Counter[str] = Counter()
    human_review = 0
    for _, judged in cases:
        abnormal_counts.update(judged.abnormal_codes())
        human_review += 1 if judged.needs_human_review() else 0

    print(f"生成 {len(cases)} 份判决样本（seed={args.seed}，可逐字节复现）")
    print(f"  数据集   -> {out}")
    print(f"  人读抽样 -> {sample_out}")
    print()
    print("档案配比（计划值 vs 实际值）：")
    from audit.synth import PROFILE_WEIGHTS

    for name, weight in PROFILE_WEIGHTS.items():
        actual = profile_counts.get(name, 0)
        share = actual / len(cases) if cases else 0.0
        print(f"  {name:<12} 计划 {weight:5.0%}  实际 {actual:>4} 份（{share:5.1%}）")
    print()
    print("整份报告最严重结论分布：")
    for verdict, count in sorted(
        worst_counts.items(), key=lambda item: (-severity_rank(item[0]), item[0])
    ):
        print(f"  {verdict:<12} {count:>4} 份（{count / max(len(cases), 1):5.1%}）")
    print()
    print(f"需要人工接住的报告：{human_review} 份")
    print()
    print("各指标被判异常的次数：")
    for code, count in sorted(abnormal_counts.items(), key=lambda item: -item[1]):
        print(f"  {code:<6} {count:>4}")
    return 0


def cmd_inject(args: argparse.Namespace) -> int:
    metrics = load_metrics()
    judged_cases = generate_reports(count=args.count, metrics=metrics, seed=args.seed)
    cases = build_injected_dataset(judged_cases, metrics, seed=args.seed)

    out = Path(args.out)
    sample_out = Path(args.sample_out)
    write_injected_dataset(cases, out, sample_out, sample_size=args.sample_size)

    clean = sum(1 for case in cases if case.clean)
    count_dist: Counter[int] = Counter(len(case.defects) for case in cases)
    kinds: Counter[str] = Counter()
    for case in cases:
        for defect in case.defects:
            kinds[defect.kind] += 1
    total_defects = sum(kinds.values())

    print(f"生成 {len(cases)} 份注入样本（seed={args.seed}，可逐字节复现）")
    print(f"  数据集   -> {out}")
    print(f"  人读抽样 -> {sample_out}")
    print()
    print(
        f"干净样本：{clean} 份（{clean / max(len(cases), 1):.1%}，计划 {CLEAN_SHARE:.0%}）"
        "  ← 误报率的分母"
    )
    print("每份缺陷条数分布：")
    for n in sorted(count_dist):
        print(f"  {n} 条：{count_dist[n]:>4} 份")
    print()
    print(f"共注入缺陷 {total_defects} 条  ← 召回率的分母")
    ceiling = capability_report(judged_cases, metrics, seed=args.seed)
    print("按类型（实际条数 / 可注入上限，括号内为可检测性契约）：")
    detectors = {}
    for case in cases:
        for defect in case.defects:
            detectors.setdefault(defect.kind, defect.expected_detector)
    for kind in DEFECT_KINDS:
        label = DEFECT_LABELS[kind]
        detector = detectors.get(kind, "-")
        print(
            f"  {kind:<22} {kinds.get(kind, 0):>4} / {ceiling.get(kind, 0):<4} "
            f"{label}（{detector}）"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m audit",
        description="auditkit：判定类 AI 输出的差分审计器",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    synth = subparsers.add_parser("synth", help="生成判决样本（被审计对象）")
    synth.add_argument("--count", type=int, default=200, help="样本数量")
    synth.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")
    synth.add_argument("--out", default=str(ROOT / "eval" / "judged-reports.jsonl"))
    synth.add_argument("--sample-out", default=str(ROOT / "eval" / "judged-reports.sample.md"))
    synth.add_argument("--sample-size", type=int, default=3, help="人读抽样条数")
    synth.set_defaults(func=cmd_synth)

    inject = subparsers.add_parser(
        "inject", help="注入已知缺陷：产出被审计产物 + 标准答案"
    )
    inject.add_argument("--count", type=int, default=200, help="样本数量")
    inject.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")
    inject.add_argument(
        "--out", default=str(ROOT / "eval" / "injected-artifacts.jsonl")
    )
    inject.add_argument(
        "--sample-out", default=str(ROOT / "eval" / "injected-artifacts.sample.md")
    )
    inject.add_argument("--sample-size", type=int, default=2, help="人读抽样条数")
    inject.set_defaults(func=cmd_inject)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
