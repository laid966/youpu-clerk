"""插件命令行：`python -m plugin list | show | validate | demo`

    list      我们有哪些场景插件
    show      某个插件的清单（部署时要能回答"它用哪版规则、哪版提示词"）
    validate  校验全部插件（清单错就报错，不静默兜底）
    demo      用插件的数据 + 本体的机制，跑一次真实审计

`demo` 是这份工作里最重要的命令：**换插件跑通、本体不改一行代码**，
就是"本体独立"的证据。
"""

from __future__ import annotations

import argparse
import sys

from engine.console import ensure_utf8_console
from plugin.spec import (
    PluginError,
    discover_plugins,
    find_plugin,
    load_prompts,
)

__all__ = ["build_parser", "main"]


def cmd_list(args: argparse.Namespace) -> int:
    specs = discover_plugins()
    if not specs:
        print("没有找到任何插件（plugins/ 下没有 plugin.yaml）")
        return 1
    print(f"共 {len(specs)} 个内容插件（本体不包含其中任何场景知识）：")
    print()
    for spec in specs:
        versions = load_prompts(spec)
        print(f"  {spec.name:<18} {spec.title}")
        print(
            f"  {'':<18} v{spec.version} · 字段 {_count_metrics(spec)} 项"
            f" · 安全词表 {len(spec.safety_terms)} 条"
            f" · 提示词 {len(versions)} 版"
        )
    print()
    print("  看某一个：python -m plugin show <名字>")
    print("  跑一次：  python -m plugin demo <名字>")
    return 0


def _count_metrics(spec) -> int:
    from audit.pipeline import load_metrics

    try:
        return len(load_metrics(spec.metrics))
    except Exception:  # noqa: BLE001 — 列表视图不该因为一个坏插件整体失败
        return -1


def cmd_show(args: argparse.Namespace) -> int:
    spec = find_plugin(args.name)
    print(spec.describe())

    versions = load_prompts(spec)
    print()
    print("## 该插件自带的提示词")
    print()
    if not versions:
        print("- （未配 prompts.py，语义检查会用核心默认提示词）")
    else:
        for name, text in versions.items():
            print(f"- `{name}`：{len(text)} 字")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    specs = discover_plugins()
    print(f"校验 {len(specs)} 个插件……")
    print()
    failed = 0
    for spec in specs:
        problems: list[str] = []
        try:
            from audit.pipeline import load_metrics

            metrics = load_metrics(spec.metrics)
            if not metrics:
                problems.append("字段清单是空的")
            for metric in metrics:
                if not metric.domain_path.is_file():
                    problems.append(f"{metric.code} 的判定域不存在：{metric.domain_path}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"字段清单读取失败：{type(exc).__name__}: {exc}")
        try:
            load_prompts(spec)
        except PluginError as exc:
            problems.append(str(exc))

        if problems:
            failed += 1
            print(f"  ✗ {spec.name}")
            for problem in problems:
                print(f"      - {problem}")
        else:
            print(f"  ✓ {spec.name}")

    print()
    print(f"通过 {len(specs) - failed} / {len(specs)}")
    return 1 if failed else 0


def cmd_demo(args: argparse.Namespace) -> int:
    from plugin.demo import run_demo

    specs = [find_plugin(args.name)] if args.name else list(discover_plugins())
    if not specs:
        print("没有插件可以跑")
        return 1

    failures = 0
    for spec in specs:
        print("=" * 72)
        print(f"插件 `{spec.name}` · {spec.title}")
        print("=" * 72)
        try:
            result = run_demo(spec)
        except PluginError as exc:
            print(f"  ✗ 跑不起来：{exc}")
            failures += 1
            continue

        print(f"  用插件声明的规则，合成了 {result.items} 项判定")
        print(
            f"  干净产物上，本体的检查器报了 {len(result.clean_findings)} 条"
            f"  {'✅ 零误报' if result.clean else '❌ 有误报（插件数据自相矛盾）'}"
        )
        for finding in result.clean_findings:
            print(f"      - {finding.detector}: {finding.message}")

        print()
        print(f"  注入一个错误判定：把 {result.target} 改成 {result.wrong_verdict!r}")
        print(f"  本体检查器报了 {len(result.broken_findings)} 条")
        for finding in result.broken_findings:
            print(
                f"      - [{finding.detector}] {finding.message}"
                f"（应为 {finding.expected}，实际 {finding.observed}）"
            )
        print()
        print(f"  结果：{'✅ 抓到了' if result.caught else '❌ 没抓到'}")
        print()

    if failures:
        print(f"{failures} 个插件跑不起来")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m plugin", description="内容插件管理（本体不含任何行业知识）"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_cmd = subparsers.add_parser("list", help="列出全部插件")
    list_cmd.set_defaults(func=cmd_list)

    show_cmd = subparsers.add_parser("show", help="查看某个插件的清单")
    show_cmd.add_argument("name")
    show_cmd.set_defaults(func=cmd_show)

    validate_cmd = subparsers.add_parser("validate", help="校验全部插件")
    validate_cmd.set_defaults(func=cmd_validate)

    demo_cmd = subparsers.add_parser(
        "demo", help="用插件的数据 + 本体的机制跑一次真实审计"
    )
    demo_cmd.add_argument("name", nargs="?", help="不填则跑全部插件")
    demo_cmd.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except PluginError as exc:
        print(f"[x] {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
