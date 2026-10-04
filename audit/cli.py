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

from audit.evaluate import evaluate
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


def cmd_eval(args: argparse.Namespace) -> int:
    metrics = load_metrics()
    judged_cases = generate_reports(count=args.count, metrics=metrics, seed=args.seed)
    cases = build_injected_dataset(judged_cases, metrics, seed=args.seed)
    report = evaluate(cases, judged_cases, metrics)

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.to_markdown(), encoding="utf-8")

    print(f"评测完成：{len(cases)} 份产物，其中干净样本 {report.clean_cases} 份")
    print()
    print(f"  已知缺陷      {report.total_defects} 条")
    print(f"  抓到          {report.caught_total} 条")
    print(f"  召回率        {report.recall_overall:.1%}")
    print(f"  精确率        {report.precision:.1%}")
    print(f"  误报          {report.false_positives} 条（每份干净样本 {report.false_positives_per_clean_case:.3f} 条）")
    print(
        f"  合法变体样本  {report.hard_negative_cases} 份，承担 {report.hard_negative_false_positives} 条误报"
        "  ← 误报率真正的考验"
    )
    print()
    print("按缺陷类型的召回：")
    for kind in DEFECT_KINDS:
        caught, total = report.recall_by_kind.get(kind, (0, 0))
        rate = f"{caught / total:5.1%}" if total else "    —"
        print(f"  {kind:<22} {caught:>3} / {total:<4} {rate}")
    print()
    print(f"  报告 -> {out}")
    return 0


def cmd_fragility(args: argparse.Namespace) -> int:
    """判定稳健性审计：这个结论离临界值有多近。

    **与召回/误报完全分开**：脆弱项是风险提示，不是"AI 抄错了"。
    零模型调用、零成本、完全确定性。
    """
    from audit.robustness import scan_artifact, scan_boundaries, scan_uniform
    from plugin.spec import PluginError, find_plugin

    # 场景内容来自插件（阈值、误差量级都随插件走），本体不写死
    try:
        spec = find_plugin(args.plugin)
    except PluginError as exc:
        print(f"[x] {exc}")
        return 2

    metrics = load_metrics(spec.metrics)
    tolerance = args.tolerance if args.tolerance is not None else spec.measurement_tolerance

    if args.artifact:
        import json

        payload = json.loads(Path(args.artifact).read_text(encoding="utf-8-sig"))
        from audit.artifact import Artifact

        artifact = Artifact.from_dict(payload["artifact"])
        values = payload.get("report_values", {})
        sex = payload.get("sex", args.sex)
        age = int(payload.get("age", args.age))
        report = scan_artifact(
            artifact, values, sex, age, metrics, tolerance=tolerance
        )
    elif args.mode == "uniform":
        report = scan_uniform(
            metrics,
            sex=args.sex,
            age=args.age,
            tolerance=tolerance,
            samples_per_metric=args.samples,
        )
    else:
        report = scan_boundaries(
            metrics, sex=args.sex, age=args.age, tolerance=tolerance
        )

    out = (
        Path(args.report)
        if args.report
        else (ROOT / "reports" / f"fragility-{spec.name}.md")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# 判定稳健性报告 · 插件 `{spec.name}`\n\n"
        f"> 探测方式：**{report.mode_label}** · 年龄 {args.age} · 性别 {args.sex}\n\n---\n\n"
    )
    out.write_text(header + report.to_markdown(), encoding="utf-8")

    print(f"插件 `{spec.name}` · {spec.title}")
    print(f"探测方式：{report.mode_label} · 误差量级 ±{tolerance:.2%}（来自插件声明）")
    print()
    print(f"  探测点            {report.probes}")
    print(f"  判定会翻转        {report.fragile}")
    print(f"  判定脆弱率        {report.fragile_rate:.1%}")
    print(f"  紧贴临界值        {len(report.boundary_adjacent)}")
    print()
    print("⚠️ 这个比例怎么读：")
    for line in report.caveat.splitlines():
        print(f"   {line}")
    print()
    print("没算出来的部分（不静默跳过）：")
    print(f"  域里没有该指标的阈值   {report.skipped_no_boundaries}")
    print(f"  扰动会越出取值范围     {report.skipped_out_of_range}")
    print(f"  判定落在缺事实转人工   {report.skipped_needs_review}")
    print()
    if report.findings:
        print("最脆弱的几项：")
        for item in sorted(report.findings, key=lambda x: x.smallest_delta)[:5]:
            print(f"  {item.describe()}")
    else:
        print("所有可评估探测点的判定在给定误差范围内都稳定。")
    print()
    print("⚠️ 脆弱项算不算缺陷是产品判断，见 docs/02-metrics.md —— 本工具只给事实。")
    print(f"  报告 -> {out}")
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

    eval_cmd = subparsers.add_parser(
        "eval", help="跑评测：检查器 vs 注入的标准答案，算召回率与误报率"
    )
    eval_cmd.add_argument("--count", type=int, default=200, help="样本数量")
    eval_cmd.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")
    eval_cmd.add_argument(
        "--report", default=str(ROOT / "reports" / "detector-report.md")
    )
    eval_cmd.set_defaults(func=cmd_eval)

    fragility = subparsers.add_parser(
        "fragility",
        help="判定稳健性审计：这个结论离临界值有多近（零成本、与召回分开统计）",
    )
    fragility.add_argument(
        "--plugin", default="med-checkup", help="场景插件（阈值与误差量级随它走）"
    )
    fragility.add_argument(
        "--tolerance", type=float, default=None, help="覆盖插件声明的误差量级，如 0.01"
    )
    fragility.add_argument(
        "--mode",
        default="thresholds",
        choices=["thresholds", "uniform"],
        help="thresholds=钉着阈值测（看阈值多敏感）；uniform=参考区间窄带均匀取样（无阈值偏差）",
    )
    fragility.add_argument(
        "--samples",
        type=int,
        default=1000,
        help="uniform 模式下每个指标取多少个点（默认 1000；纯计算，0.5 秒。"
        "取样太少会得到假的 0%%，见 audit/robustness.py 的说明）",
    )
    fragility.add_argument("--sex", default="male", choices=["male", "female"])
    fragility.add_argument("--age", type=int, default=35)
    fragility.add_argument(
        "--artifact", default=None, help="改为扫描单份产物（JSON：artifact/report_values/sex/age）"
    )
    fragility.add_argument(
        "--report", default=None, help="报告路径（默认 reports/fragility-<插件>.md）"
    )
    fragility.set_defaults(func=cmd_fragility)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
