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
    from agent.guardrails import apply_guardrails

    judge = build_judge(use_cache=not args.no_cache)
    prompt = prompt_for(args.prompt)
    outcome = check_text(args.text, args.target, prompt, judge)

    print(f"提示词版本：{args.prompt}")
    print(f"文本：{args.text}")
    print()

    # **先把护栏结果单独打出来**：这是验证"我加的规则到底生效没有"的唯一依据。
    # 没有这一段，你只能看到"由 guardrail 判出"，却不知道是哪条规则、哪个词命中的。
    hits = apply_guardrails(args.text)
    if hits:
        print("护栏命中（命中即判越界，不必问模型）：")
        for hit in hits:
            print(f"  · 规则 {hit.rule}（类别 {hit.category}） 命中词/正则：{hit.pattern!r}")
    else:
        print("护栏：一个词都没命中 → 这一句会交给模型判（改写型越界本来就该这样）")
    print()

    if outcome.error:
        print(f"[错误] {outcome.error}")
        print("注意：错误**不等于**没有越界，必须单独处理。")
        return 2
    if outcome.finding is None:
        print("最终判定：没有越界")
    else:
        print(f"最终判定：越界（{outcome.finding.category}，由 {outcome.finding.decided_by} 判出）")
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


def cmd_mutate(args: argparse.Namespace) -> int:
    """变异测试：故意改坏流水线，看测试套件抓不抓得住。"""
    from agent.mutation import MutationBaselineError, run_mutation
    from agent.mutants import MUTANTS

    selected = MUTANTS
    if args.id:
        selected = tuple(item for item in MUTANTS if item.mutant_id == args.id)
        if not selected:
            print(f"[x] 没有这个变异体：{args.id}")
            return 2

    print(f"开始变异测试（{args.id or '全部 ' + str(len(selected)) + ' 个'}）——在临时副本里改，工作区只读")
    print()
    try:
        report = run_mutation(mutants=selected, verbose=True)
    except MutationBaselineError as exc:
        print(f"[x] {exc}")
        return 2

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.to_markdown(), encoding="utf-8")

    print()
    print(f"  有效变异体        {len(report.valid)} 个")
    print(f"  必须杀死          {len(report.must_kill)} 个")
    print(f"  杀死              {len(report.killed)} 个")
    print(f"  真实盲区          {len(report.real_gaps)} 个  ← 必须杀死却活下来的")
    print(f"  允许存活（旋钮）  {len(report.allowed_survivors)} 个")
    print(f"  变异得分          {report.score:.1%}   （只统计必须杀死的那批）")
    print(f"  预期杀手命中率    {report.expected_catch_rate:.1%}")
    print()
    if report.real_gaps:
        print("真实测试盲区（改坏了测试也没反应）：")
        for item in report.real_gaps:
            print(f"  {item.mutant.mutant_id}  {item.mutant.description}")
            print(f"      目标：{item.mutant.target}")
            print(f"      本该由：{item.mutant.expected_killer}")
        print()
    print(f"  报告 -> {out}")
    # 只有**真实盲区**才让命令失败。"允许存活的旋钮"存活是设计意图，不算失败。
    return 1 if report.real_gaps else 0


def cmd_patch(args: argparse.Namespace) -> int:
    """补丁闭环：从漏掉的案例里提取候选规则，验证不误伤，出待人审批的建议。"""
    from agent.patch import propose_patches
    from audit.inject import tempting_but_legit_phrases

    metrics = load_metrics()
    judged_cases = generate_reports(count=args.count, metrics=metrics, seed=DEFAULT_SEED)
    cases = build_injected_dataset(judged_cases, metrics, seed=DEFAULT_SEED)

    # 正例 = 护栏层抓不到的改写型越界（实测这类召回为 0%）
    missed = sorted(
        {
            defect.observed
            for case in cases
            for defect in case.defects
            if defect.kind == "safety_paraphrase"
        }
    )
    # 反例语料要尽量厚，否则"零误报"这个结论不硬。
    # 取全部样本的解释文本，但**排除被注入改写型越界的那一条**——
    # 它本身就是正例的来源，混进反例会把自己过滤掉。
    injected_targets = {
        (case.case_id, defect.target)
        for case in cases
        for defect in case.defects
        if defect.kind == "safety_paraphrase"
    }
    negatives: list[str] = [
        item.explanation
        for case in cases
        for item in case.artifact.items
        if (case.case_id, item.code) not in injected_targets
    ]
    negatives.extend(tempting_but_legit_phrases())

    report = propose_patches(missed, negatives, max_patterns=args.max_patterns)

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.to_markdown(), encoding="utf-8")

    print("补丁闭环：从漏掉的案例里提取候选规则（**不会自动应用**）")
    print()
    print(f"  漏掉的案例        {report.missed_total} 条")
    print(f"  尝试的候选片段    {report.candidates_tried} 个")
    print(f"  干净语料          {report.negatives_total} 条（误报检验用）")
    print(f"  建议采纳的规则    {len(report.proposals)} 条")
    print(f"  覆盖漏例          {report.covered} / {report.missed_total}（{report.coverage:.1%}）")
    print(f"  干净语料上的误报  {report.total_false_positives} 条")
    print()
    if not report.proposals:
        print("  没有找到安全的候选片段——改提示词的泛化能力，而不是加字面规则。")
    else:
        for index, proposal in enumerate(report.proposals, start=1):
            print(f"  建议 {index}：`{proposal.pattern}`  可补 {len(proposal.catches)} 条漏例")
    print()
    print("  ⚠️ 这些只是建议：请审阅后手工写进 agent/guardrails.py，并给每条配一个测试。")
    print("  ⚠️ 字面规则永远追不上改写说法——它能覆盖的部分，提示词才是根治手段。")
    print()
    print(f"  报告 -> {out}")
    return 0


def cmd_heldout(args: argparse.Namespace) -> int:
    """留出集：用提示词没见过的新句子测泛化能力。"""
    from agent.heldout import load_heldout, run_heldout

    cases = load_heldout(args.file) if args.file else load_heldout()
    judge = build_judge(use_cache=not args.no_cache)

    versions = [args.prompt] if args.prompt else sorted(_registry_versions())
    reports = []
    for version in versions:
        report = run_heldout(cases, prompt_for(version), version, judge)
        reports.append(report)

    print(f"留出集：{len(cases)} 条**提示词没见过**的新句子")
    print()
    for report in reports:
        print(f"  提示词 {report.prompt_version}")
        print(
            f"    违规句召回   {report.caught} / {len(report.positives)}"
            f"  = {report.recall:.1%}"
        )
        print(
            f"    合法句误报   {report.false_positives} / {len(report.negatives)}"
            f"  = {report.false_positive_rate:.1%}"
        )
        print(f"    解析失败     {report.errors}")
        print()
        print("    镜像组（最能看出泛化）：")
        from agent.heldout import MIRROR_GROUPS

        for name, ids in MIRROR_GROUPS.items():
            items = report.group(ids)
            ok = sum(1 for item in items if item.correct)
            print(f"      {name}  {ok} / {len(items)} 条判对")
        print()

    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n\n---\n\n".join(report.to_markdown() for report in reports), encoding="utf-8"
    )
    print(f"  报告 -> {out}")
    return 0


def _registry_versions() -> tuple[str, ...]:
    from agent.prompts import _REGISTRY

    return tuple(_REGISTRY)


def cmd_guardrails(args: argparse.Namespace) -> int:
    """只看护栏：列出规则 + 自检每条规则有没有失效。

    **不调模型、不花钱。** 这是验证"我加的规则生效没有"最快的方式：

    - 不带参数：列出全部规则，并**逐条自检**（把它自己的词喂回去，看命不命中）
    - `--text "一句话"`：把一段文本跑一遍，看命中了哪条规则、哪个词
    - `--rule <名字>`：只看某一条规则的自检结果

    ⚠️ 自检只能验证**字面规则**（`is_regex=False`）。正则规则没法这样反问，
    要用 `--text` 手写一句去试。
    """
    from agent.guardrails import EXTRA_PATTERNS, GuardrailRule, apply_guardrails

    if args.text:
        hits = apply_guardrails(args.text)
        print(f"文本：{args.text}")
        print()
        if not hits:
            print("护栏：一个词都没命中 → 这段文本会交给模型判（改写型越界本来就该这样）")
            print()
            print("如果这句该被护栏抓到，检查两件事：")
            print("  1. 词写对了吗（用 python -m agent guardrails 看规则里到底有什么词）")
            print("  2. 规则是不是空的（空规则会在导入时直接报错，不会静默）")
            return 0
        print("护栏命中（命中即判越界，不必问模型）：")
        for hit in hits:
            print(f"  · 规则 {hit.rule}（类别 {hit.category}） 命中词/正则：{hit.pattern!r}")
        return 0

    rules = [
        rule
        for rule in _all_guardrail_rules()
        if not args.rule or rule.name == args.rule
    ]
    if not rules:
        print(f"[x] 没有这条规则：{args.rule}")
        return 2

    extra = set(id(rule) for rule in EXTRA_PATTERNS)
    print(f"共 {len(_all_guardrail_rules())} 条护栏规则（其中你的扩展位 {len(EXTRA_PATTERNS)} 条）")
    print()

    dead: list[str] = []
    for rule in rules:
        origin = "★你的" if id(rule) in extra else "  基础"
        regex_tag = "（正则）" if rule.is_regex else ""
        print(f"{origin}  {rule.name}")
        print(f"        类别：{rule.category}    模式：{len(rule.patterns)} 个{regex_tag}")
        print(f"        说明：{rule.note}")
        print(f"        词表：{list(rule.patterns)}")

        if rule.is_regex:
            print("        自检：⚠️ 正则规则无法自动反问，请用 --text 手写一句验证")
        else:
            probe = "、".join(rule.patterns)
            hits = {
                hit.pattern
                for hit in apply_guardrails(probe)
                if hit.rule == rule.name
            }
            missing = [p for p in rule.patterns if p not in hits]
            if hits and not missing:
                print(f"        自检：✅ 全部 {len(rule.patterns)} 个词都能命中")
            elif hits:
                print(f"        自检：⚠️ 只有 {len(hits)}/{len(rule.patterns)} 命中，未命中：{missing}")
            else:
                print("        自检：❌ 这条规则是死的（一个词都匹配不到）")
                dead.append(rule.name)
        print()

    if dead:
        print(f"❌ 有 {len(dead)} 条死规则：{dead}")
        print("   死规则不会报错，但永远不起作用——请检查模式里的词是否写对。")
        return 1

    print("✅ 所有字面规则都能命中。")
    print()
    print("下一步：用一句真实的话验证 —— ")
    print('  .\\.venv\\Scripts\\python.exe -m agent guardrails --text "你的一句话"')
    return 0


def _all_guardrail_rules() -> tuple:
    from agent.guardrails import GUARDRAIL_RULES

    return GUARDRAIL_RULES


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

    guardrails = subparsers.add_parser(
        "guardrails",
        help="只看护栏：列规则 + 自检每条规则有没有失效（不调模型、不花钱）",
    )
    guardrails.add_argument(
        "--text", default=None, help="用一句话验证：显示命中了哪条规则、哪个词"
    )
    guardrails.add_argument("--rule", default=None, help="只看某一条规则的自检结果")
    guardrails.set_defaults(func=cmd_guardrails)

    eval_cmd = subparsers.add_parser("eval-semantic", help="评测语义检查（你的提示词）")
    # 默认值刻意定在"统计上够用"的规模，而不是"跑得快"的规模。
    #
    # 依据见 audit/stats.py：零失败时想声称「召回 ≥95%」和「误报 ≤5%」，
    # 各需要 59 条样本。所以默认 60 / 60。
    # 早期默认是 24 / 20——那只能证明「召回 ≥88.3%、误报 ≤13.9%」，
    # **连 90% 都声称不了**。跑得快但证明不了什么，等于白跑。
    #
    # 成本：一次约 120 次模型调用（DeepSeek 下约 6 分钱）。同版本重跑走缓存不花钱。
    eval_cmd.add_argument(
        "--count", type=int, default=500, help="注入样本数量（要够多才有足够的缺陷可抽）"
    )
    eval_cmd.add_argument(
        "--positives",
        type=int,
        default=60,
        help="正例条数（证明召回 ≥95%% 需要 59 条）",
    )
    eval_cmd.add_argument(
        "--negatives",
        type=int,
        default=60,
        help="负例条数（证明误报 ≤5%% 需要 59 条）",
    )
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

    mutate = subparsers.add_parser(
        "mutate", help="变异测试：故意改坏流水线，看测试套件抓不抓得住"
    )
    mutate.add_argument("--id", help="只跑指定变异体（如 M03）")
    mutate.add_argument("--report", default=str(ROOT / "reports" / "mutation-report.md"))
    mutate.set_defaults(func=cmd_mutate)

    patch = subparsers.add_parser(
        "patch", help="补丁闭环：提取候选护栏规则（待人审批，不会自动应用）"
    )
    patch.add_argument("--count", type=int, default=60, help="生成多少份注入样本供取样")
    patch.add_argument("--max-patterns", type=int, default=3, help="最多给几条建议")
    patch.add_argument(
        "--report", default=str(ROOT / "reports" / "patch-report.md")
    )
    patch.set_defaults(func=cmd_patch)

    heldout = subparsers.add_parser(
        "heldout", help="留出集：用提示词没见过的新句子测泛化能力"
    )
    heldout.add_argument("--prompt", help="只跑指定版本（不填则跑注册表里所有版本）")
    heldout.add_argument("--file", default=None, help="留出集文件（默认 eval/semantic-heldout.jsonl）")
    heldout.add_argument("--no-cache", action="store_true")
    heldout.add_argument(
        "--report", default=str(ROOT / "reports" / "heldout-report.md")
    )
    heldout.set_defaults(func=cmd_heldout)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except RuntimeError as exc:  # 例如缺 API key
        print(f"[x] {exc}")
        return 2
