"""判决样本生成：造出"像真实体检报告"的样本，并给出确定性判决。

## 为什么配比要显式设计

M1 时踩过一次坑（见 `docs/03-failure-modes.md` 的 FM-003）：生成器把布尔字段按 50/50 均匀取样，
结果"误机""联程用了一半"这些现实中罕见的情形被大量制造出来，整个数据集 89.5% 都是"转人工"，
数字根本读不出来。

所以这里**显式声明档案配比**，并且必须接近现实门诊分布：

| 档案 | 含义 | 配比 |
|---|---|---|
| `normal` | 全部指标在参考区间内 | 50% |
| `single_mild` | 单一指标轻度异常 | 20% |
| `multi_mild` | 多项轻度异常 | 15% |
| `marked` | 至少一项明显异常 | 10% |
| `critical` | 至少一项危急值 | 5% |

## 阈值只在域的规则里定义一次

生成器不维护自己的阈值表。它的做法是：拿参考区间推出候选数值，
再**问引擎**这个数值算第几级，直到命中目标严重度。
这样"生成器以为的阈值"和"引擎实际用的阈值"不可能不一致——
而这个不一致恰恰是后续审计器要抓的缺陷之一，不能让它先在生成器里出现。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from audit.pipeline import (
    JudgedReport,
    Metric,
    Report,
    judge_metric,
    judge_report,
    severity_rank,
)

__all__ = [
    "PROFILE_WEIGHTS",
    "build_dataset",
    "generate_reports",
    "render_dataset_sample",
    "to_json_line",
    "write_dataset",
]

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = 20261003

# 档案 -> 权重。刻意接近现实门诊分布，避免重演 FM-003 的分布失真。
PROFILE_WEIGHTS: Mapping[str, float] = {
    "normal": 0.50,
    "single_mild": 0.20,
    "multi_mild": 0.15,
    "marked": 0.10,
    "critical": 0.05,
}

# 从参考区间推候选数值的倍数阶梯。
# 先试"刚刚越界"，再逐级放大，这样"轻度异常"拿到的是最小的越界值。
_LADDER = (1.05, 1.1, 1.15, 1.3, 1.5, 2.0, 2.5, 3.0, 5.0, 8.0, 12.0, 20.0, 50.0)


@dataclass(frozen=True)
class Profile:
    """一个档案：整体正常程度 + 明确指定严重度的指标。"""

    name: str
    normal_count: int
    targets: Mapping[str, str]  # 指标 code -> 目标严重度


def _candidate_values(metric: Metric, sex: str) -> list[float]:
    """由参考区间推出候选数值：上限方向放大、下限方向缩小。"""
    low, high = metric.reference_for(sex)
    values: list[float] = []
    for factor in _LADDER:
        if high > 0:
            values.append(round(high * factor, 4))
        if low > 0:
            values.append(round(low / factor, 4))
    return [value for value in values if value > 0]


# 缓存：某个指标在某个性别下，能达到某个严重度的全部候选数值。
#
# 键里不含年龄：本生成器只产出成人（20–75 岁），而年龄只通过 escalate 条件
# （<18 / >100）影响结论，在这段区间内不影响严重度。generate_reports 里有断言守着这个前提。
_MATCH_CACHE: dict[tuple[str, str, str], tuple[float, ...]] = {}


def _matching_values(metric: Metric, sex: str, age: int, target: str) -> tuple[float, ...]:
    key = (metric.code, sex, target)
    cached = _MATCH_CACHE.get(key)
    if cached is None:
        cached = tuple(
            value
            for value in _candidate_values(metric, sex)
            if judge_metric(metric, sex, age, value)["final_verdict"] == target
        )
        _MATCH_CACHE[key] = cached
    return cached


def supports_severity(metric: Metric, sex: str, age: int, target: str) -> bool:
    """该指标在这个性别下，能不能被判成目标严重度。

    为什么需要它：尿酸（UA）域只定义了轻度/明显升高，**没有危急阈值**。
    如果不做这个判断，"危急"档案里抽到尿酸的报告就永远到不了危急，
    档案名与实际结果不一致——那种数据用于评测会让指标变成一个说不清的东西。
    """
    return bool(_matching_values(metric, sex, age, target))


def _normal_value(metric: Metric, sex: str, rng: random.Random, age: int) -> float:
    """参考区间内取值，并向中间收 10%，避免贴着边界。"""
    low, high = metric.reference_for(sex)
    span = high - low
    inner_low = low + span * 0.10
    inner_high = high - span * 0.10
    value = round(rng.uniform(inner_low, inner_high), 4)

    # 用引擎验一下：万一"区间内"仍被判成异常（例如参考区间与规则阈值不一致），
    # 就退回中间值——这本身就是一种对规则集的隐式检查。
    if judge_metric(metric, sex, age, value)["final_verdict"] != "normal":
        value = round((low + high) / 2, 4)
    return value


def _value_for_severity(
    metric: Metric, sex: str, age: int, target: str, rng: random.Random
) -> float | None:
    """反查一个能产生目标严重度的数值。找不到就返回 None（调用方会退级）。"""
    matched = _matching_values(metric, sex, age, target)
    if not matched:
        return None
    # 轻度异常倾向取最小的越界值，明显的倾向取较大值
    if target == "mild" and rng.random() < 0.7:
        return matched[0]
    return rng.choice(matched)


def _plan_profiles(count: int) -> list[str]:
    """按权重分配档案数量，保证总数精确等于 count。"""
    raw = {name: count * weight for name, weight in PROFILE_WEIGHTS.items()}
    allocated = {name: int(value) for name, value in raw.items()}
    remainder = count - sum(allocated.values())
    for name, _ in sorted(raw.items(), key=lambda item: (-(item[1] - int(item[1])), item[0])):
        if remainder <= 0:
            break
        allocated[name] += 1
        remainder -= 1

    plan: list[str] = []
    for name in PROFILE_WEIGHTS:
        plan.extend([name] * allocated[name])
    return plan


def generate_reports(
    count: int,
    metrics: Sequence[Metric],
    seed: int = DEFAULT_SEED,
) -> list[tuple[str, JudgedReport]]:
    """生成 count 份判决样本。同一个 seed 必然产出完全相同的序列。"""
    if count <= 0:
        return []

    rng = random.Random(seed)
    codes = [metric.code for metric in metrics]
    by_code = {metric.code: metric for metric in metrics}
    plans = _plan_profiles(count)
    rng.shuffle(plans)

    results: list[tuple[str, JudgedReport]] = []

    for index, profile_name in enumerate(plans, start=1):
        age = rng.randint(20, 75)
        # 前提：只产出成人。年龄只通过 escalate 条件（<18 / >100）影响结论，
        # 这段区间内不影响严重度，所以 _MATCH_CACHE 的键里可以不含年龄。
        assert 18 <= age <= 100, f"生成器只覆盖成人，实际 age={age}"
        sex = rng.choice(["male", "female"])

        # 每个指标的默认取值：正常
        values = {code: _normal_value(by_code[code], sex, rng, age) for code in codes}

        if profile_name != "normal":
            pool = codes
            primary_target = _target_for(profile_name, 0)
            eligible = [
                code
                for code in codes
                if supports_severity(by_code[code], sex, age, primary_target)
            ]
            if eligible:
                # 只在"做得到这个严重度"的指标里抽，保证档案名与实际结果一致
                pool = eligible

            picked = rng.sample(pool, k=min(len(pool), _how_many(profile_name, rng)))
            for position, code in enumerate(picked):
                target = _target_for(profile_name, position)
                metric = by_code[code]
                value = _value_for_severity(metric, sex, age, target, rng)
                if value is None:
                    # 该指标做不到这个严重度（例如它没有定义危急阈值），退一级
                    value = _value_for_severity(metric, sex, age, "mild", rng)
                if value is not None:
                    values[code] = value

        report = Report(
            report_id=f"R-{index:04d}",
            age=age,
            sex=sex,
            values=dict(sorted(values.items())),
        )
        results.append((profile_name, judge_report(report, tuple(metrics))))

    return results


def _how_many(profile_name: str, rng: random.Random) -> int:
    if profile_name == "single_mild":
        return 1
    if profile_name == "multi_mild":
        return rng.choice([2, 3])
    if profile_name == "marked":
        return rng.choice([1, 2])
    if profile_name == "critical":
        return rng.choice([1, 1, 2])
    return 0


def _target_for(profile_name: str, position: int) -> str:
    """档案里第 position 个被选中的指标，目标严重度是什么。"""
    if profile_name == "critical":
        return "critical" if position == 0 else "mild"
    if profile_name == "marked":
        return "marked" if position == 0 else "mild"
    return "mild"


def to_json_line(profile: str, judged: JudgedReport) -> str:
    payload: dict[str, Any] = {"profile": profile}
    payload.update(judged.to_dict())
    return json.dumps(payload, ensure_ascii=False, sort_keys=False)


def write_dataset(
    cases: Sequence[tuple[str, JudgedReport]],
    out_path: str | Path,
    sample_out: str | Path | None = None,
    sample_size: int = 3,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for profile, judged in cases:
            handle.write(to_json_line(profile, judged) + "\n")

    if sample_out is not None:
        sample_out = Path(sample_out)
        sample_out.parent.mkdir(parents=True, exist_ok=True)
        sample_out.write_text(render_dataset_sample(cases, sample_size), encoding="utf-8")
    return out_path


def render_dataset_sample(
    cases: Sequence[tuple[str, JudgedReport]],
    size: int,
    metrics: Sequence[Metric] | None = None,
) -> str:
    """渲染成人能读的 Markdown：像一份检验报告，后面附上引擎给出的判决。"""
    from audit.pipeline import load_metrics as _load_metrics

    metrics = tuple(metrics) if metrics is not None else _load_metrics()
    by_code = {metric.code: metric for metric in metrics}

    lines = [
        "# 判决样本抽样（人读版）",
        "",
        "> 给人抽查用的。完整数据集在 `eval/judged-reports.jsonl`。",
        "> 判决全部由 `engine/` 的确定性规则给出，**本阶段没有模型参与**。",
        "> 同一 seed 可逐字节复现。",
        "",
        f"共 {len(cases)} 份，下面展示前 {min(size, len(cases))} 份。",
        "",
    ]

    for profile, judged in cases[:size]:
        report = judged.report
        lines.append(f"## {report.report_id} · 档案 `{profile}`")
        lines.append("")
        lines.append(f"- 年龄 {report.age} / 性别 {report.sex}")
        lines.append(f"- 整份报告最严重：`{judged.worst_verdict()}`")
        lines.append(f"- 需人工接住：{', '.join(judged.needs_human_review()) or '无'}")
        lines.append("")
        lines.append("| 指标 | 数值 | 单位 | 参考区间 | 引擎判决 |")
        lines.append("|---|---|---|---|---|")
        for code in sorted(report.values):
            metric = by_code[code]
            verdict = judged.verdict_of(code)
            flag = " ⚠️" if severity_rank(verdict) > 0 else ""
            lines.append(
                f"| {metric.name} | {report.values[code]:g} | {metric.unit} "
                f"| {metric.display_range(report.sex)} | `{verdict}`{flag} |"
            )
        lines.append("")

        abnormal = judged.abnormal_codes()
        if abnormal:
            lines.append("**异常指标的判定依据**")
            lines.append("")
            for code in abnormal:
                payload = judged.judgements[code]
                citations = payload.get("citations") or []
                lines.append(f"- `{code}` → `{payload['final_verdict']}`（规则 {payload['winning_rule_id']}）")
                for cite in citations:
                    lines.append(f"  - 依据：{cite}")
            lines.append("")

    return "\n".join(lines)
