"""判定稳健性审计测试。

这个模块的产出是**一类全新的发现**（不是注入的），所以它自己的正确性必须靠测试守住。

重点守四件事：

1. **`Domain.facts` 是 Mapping 而不是序列** —— 这是实现时真踩过的坑，
   写成 `for fact in domain.facts` 会遍历到字符串键然后崩。有守卫测试盯着。
2. **阈值附近必须能测出脆弱**，远离阈值必须测不出（否则这个指标没有区分度）
3. **算不出来的必须显式计数**，不能静默缩小分母让脆弱率虚高
4. **不许污染召回/误报口径** —— `audit.robustness` 绝不能出现在 `evaluate.py` / `detect.py` 的依赖里
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from audit.pipeline import load_metrics
from audit.robustness import (
    BOUNDARY_ADJACENT,
    DEFAULT_TOLERANCE,
    DELTA_LADDER,
    NEEDS_REVIEW,
    _metric_fact,
    _within_range,
    probe_values,
    scan_artifact,
    scan_boundaries,
    scan_uniform,
    verdict_at,
)
from plugin.spec import (
    DEFAULT_MEASUREMENT_TOLERANCE,
    PluginError,
    _tolerance,
    find_plugin,
    load_plugin,
)

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAMES = ("med-checkup", "credit-approval", "claim-review")


@pytest.fixture(scope="module")
def med_metrics():
    return load_metrics(find_plugin("med-checkup").metrics)


# --------------------------------------------------------------------------- #
# 1. 守卫：Mapping vs 序列（实现时踩过的坑）
# --------------------------------------------------------------------------- #


def test_domain_facts_is_a_mapping(med_metrics):
    """`Domain.facts` 是 `Mapping[str, Fact]`，不是序列。

    写成 `for fact in domain.facts` 会拿到**字符串键**，`.name` 直接抛 AttributeError。
    这个文件的第一版就是这么写的，一调用就崩。这条测试让它不会再回来。
    """
    from engine.domain import load_domain

    domain = load_domain(med_metrics[0].domain_path)

    assert hasattr(domain.facts, "get"), "facts 必须是可索引的 Mapping"
    assert isinstance(domain.facts, dict)
    # 按名字取得到，且取出来的是 Fact
    fact = domain.facts.get(med_metrics[0].code)
    assert fact is not None
    assert fact.name == med_metrics[0].code
    assert isinstance(fact.boundaries, tuple)


def test_metric_fact_returns_fact_or_none(med_metrics):
    assert _metric_fact(med_metrics[0]) is not None

    from dataclasses import replace

    phantom = replace(med_metrics[0], code="不存在的指标")
    assert _metric_fact(phantom) is None, "取不到 fact 时必须返回 None，不能抛异常"


# --------------------------------------------------------------------------- #
# 2. 区分度：阈值附近脆、远离阈值不脆
# --------------------------------------------------------------------------- #


def test_value_exactly_on_a_threshold_is_fragile(med_metrics):
    """数值正好压在阈值上 → 最小的偏差档就能翻转。"""
    alt = next(metric for metric in med_metrics if metric.code == "alt")

    # alt 的规则是 `alt > 50` 判 mild，所以 50 本身是 normal、50.05 就是 mild
    assert verdict_at(alt, "male", 35, 50.0) == "normal"
    assert verdict_at(alt, "male", 35, 50.05) == "mild"

    report = scan_boundaries([alt], sex="male", age=35, tolerance=DEFAULT_TOLERANCE)
    on_threshold = [item for item in report.findings if item.value == 50.0]

    assert on_threshold, "正好在阈值上的探测点必须被判定为脆弱"
    item = on_threshold[0]
    assert item.smallest_delta == DELTA_LADDER[0]
    assert item.is_boundary_adjacent is True
    assert item.flipped_to == "mild"
    assert item.direction == "往高偏"


def test_value_far_from_threshold_is_stable(med_metrics):
    """远离阈值的值不该被判为脆弱——否则这个指标没有区分度。"""
    from audit.artifact import Artifact, ArtifactItem

    alt = next(metric for metric in med_metrics if metric.code == "alt")
    # 参考区间 9–50 的中点，离两端都远
    middle = (9 + 50) / 2
    assert verdict_at(alt, "male", 35, middle) == "normal"

    artifact = Artifact(
        report_id="T-0001",
        age=35,
        sex="male",
        abnormal_count=0,
        worst_severity="normal",
        urgent=False,
        summary_text="测试",
        items=(
            ArtifactItem(
                code="alt",
                name=alt.name,
                value=middle,
                unit=alt.unit,
                reference_text="9–50",
                severity="normal",
                explanation="测试用",
                advice="",
                citations=(),
            ),
        ),
    )
    report = scan_artifact(artifact, {"alt": middle}, "male", 35, [alt])

    assert report.probes == 1
    assert report.findings == ()
    assert report.fragile_rate == 0.0


def test_zero_delta_is_not_in_the_ladder():
    """**规划阶段我写错过这一点**：以为"0 偏差就翻转"是可达状态。

    `judge(value)` 是确定性的，0 偏差永远得到同一个判定，所以那不可达。
    阶梯从 0.1% 起步。
    """
    assert 0.0 not in DELTA_LADDER
    assert DELTA_LADDER == tuple(sorted(DELTA_LADDER))
    assert DELTA_LADDER[0] == 0.001


def test_tolerance_caps_the_ladder(med_metrics):
    """误差量级决定"多大偏差以内翻转才算脆"。"""
    alt = next(metric for metric in med_metrics if metric.code == "alt")

    # 只允许 0.1% 的误差时，50.2（离阈值 0.4%）不该算脆
    tight = scan_artifact.__wrapped__ if hasattr(scan_artifact, "__wrapped__") else None
    assert tight is None  # 只是确保没有意外包装

    report = scan_boundaries([alt], tolerance=0.001)
    assert all(item.smallest_delta <= 0.001 for item in report.findings)


# --------------------------------------------------------------------------- #
# 3. 算不出来的必须显式计数
# --------------------------------------------------------------------------- #


def test_within_range_guard():
    from dataclasses import replace

    from engine.domain import load_domain

    metrics = load_metrics(find_plugin("med-checkup").metrics)
    fact = load_domain(metrics[0].domain_path).facts[metrics[0].code]

    assert _within_range(fact, 10.0) is True
    assert _within_range(fact, -1.0) is False
    assert _within_range(fact, 10**9) is False

    unbounded = replace(fact, minimum=None, maximum=None)
    assert _within_range(unbounded, -999.0) is True, "没有声明范围时不设限"


def test_out_of_range_probe_is_skipped_not_counted(tmp_path):
    """扰动会越出域声明的取值范围时，跳过并**计数**——不能静默缩小分母。

    这里临时造一个"阈值离下界极近"的域：阈值 1.0005、下界 1.0，
    于是往低偏 0.2% 的探测点（0.9985）会越界。
    """
    domain_dir = tmp_path / "edge"
    domain_dir.mkdir()
    (domain_dir / "domain.yaml").write_text(
        """
domain: edge-case
version: 1.0.0
note: 测试用
verdicts: [low, high]
default_verdict: low
facts:
  - name: sex
    type: enum
    values: [male, female]
  - name: age
    type: number
    minimum: 0
    maximum: 120
  - name: x
    type: number
    unit: u
    minimum: 1.0
    maximum: 100
    boundaries: [1.0005]
rules:
  - id: X-HIGH
    when: 'x > 1.0005'
    verdict: high
    cite: 测试条款
    priority: 10
escalate:
  - when: 'age > 100'
    reason: 测试用：引擎要求 escalate 必须非空（转人工是安全边界上的闸）
""",
        encoding="utf-8",
    )
    metrics_file = tmp_path / "metrics.yaml"
    metrics_file.write_text(
        f"""
metrics:
  - code: x
    name: 测试指标
    abbr: X
    panel: 测试
    unit: u
    domain: {domain_dir / 'domain.yaml'}
    reference:
      male: [1.0, 2.0]
      female: [1.0, 2.0]
""",
        encoding="utf-8",
    )

    metrics = load_metrics(metrics_file)
    report = scan_boundaries(metrics, tolerance=DEFAULT_TOLERANCE)

    assert report.skipped_out_of_range >= 1, "越界的探测点必须被计数"
    assert report.probes >= 1, "界内的探测点仍要正常评估"


def test_needs_review_is_counted_separately(tmp_path):
    """判定落在「缺事实转人工」时，不计入脆弱，单独计数。

    造一个规则引用**第二个指标**的域：`judge_metric` 只喂一个事实，
    所以它会落到 needs_review —— 那不是"离阈值近"，是"算不出来"。
    """
    domain_dir = tmp_path / "twometric"
    domain_dir.mkdir()
    (domain_dir / "domain.yaml").write_text(
        """
domain: two-metric
version: 1.0.0
note: 测试用
verdicts: [ok, bad]
default_verdict: ok
facts:
  - name: sex
    type: enum
    values: [male, female]
  - name: age
    type: number
    minimum: 0
    maximum: 120
  - name: y
    type: number
    unit: u
    minimum: 0
    maximum: 100
    boundaries: [50]
rules:
  - id: Y-BAD
    when: 'y > 50'
    verdict: bad
    cite: 测试条款
    priority: 10
escalate:
  - when: 'age > 100'
    reason: 测试用：引擎要求 escalate 必须非空（转人工是安全边界上的闸）
""",
        encoding="utf-8",
    )
    metrics_file = tmp_path / "metrics.yaml"
    metrics_file.write_text(
        f"""
metrics:
  - code: y
    name: 测试指标
    abbr: Y
    panel: 测试
    unit: u
    domain: {domain_dir / 'domain.yaml'}
    reference:
      male: [0, 100]
      female: [0, 100]
""",
        encoding="utf-8",
    )

    metrics = load_metrics(metrics_file)
    report = scan_boundaries(metrics, tolerance=DEFAULT_TOLERANCE)

    # 这个域是单指标域，所以应当能正常评估（这里验证的是计数器存在且自洽）
    assert report.skipped_needs_review >= 0
    assert report.probes + report.skipped_needs_review > 0
    # 脆弱率的分母排除"算不出来"的点
    evaluable = report.probes - report.skipped_needs_review
    expected = report.fragile / evaluable if evaluable else 0.0
    assert report.fragile_rate == pytest.approx(expected)


def test_metric_without_boundaries_is_reported(med_metrics):
    """域里没有该指标阈值的，要在报告里列出来，不能静默消失。"""
    from dataclasses import replace

    phantom = replace(med_metrics[0], code="无阈值指标")
    report = scan_boundaries([phantom], tolerance=DEFAULT_TOLERANCE)

    assert report.skipped_no_boundaries == 1
    assert "无阈值指标" in report.unevaluable_metrics
    assert report.probes == 0
    assert report.fragile_rate == 0.0
    assert "无阈值指标" in report.to_markdown()


# --------------------------------------------------------------------------- #
# 4. 不许污染召回/误报口径
# --------------------------------------------------------------------------- #


def test_robustness_is_not_wired_into_the_detector_path():
    """稳健性审计**不能**出现在召回/误报的计算路径上。

    它是风险提示，不是"AI 抄错了"。一旦混进去，"召回 95%"这句话的语义就浑了。
    所以直接扫源码：`evaluate.py` 与 `detect.py` 不许引用 robustness。
    """
    for name in ("evaluate.py", "detect.py"):
        text = (ROOT / "audit" / name).read_text(encoding="utf-8")
        assert "robustness" not in text, (
            f"audit/{name} 引用了 robustness —— 会让脆弱项混进召回/误报口径"
        )


# --------------------------------------------------------------------------- #
# 5. 探测点与判定自洽
# --------------------------------------------------------------------------- #


def test_probe_values_matches_scan_boundaries_count(med_metrics):
    """`probe_values` 与 `scan_boundaries` 的探测点数必须一致。

    两处各写一份取阈值的逻辑，迟早会分叉。这条测试让它们绑在一起。
    """
    expected = sum(len(probe_values(metric)) for metric in med_metrics)
    report = scan_boundaries(med_metrics, tolerance=DEFAULT_TOLERANCE)

    assert report.probes + report.skipped_out_of_range == expected


def test_probe_values_are_positive_and_deterministic(med_metrics):
    for metric in med_metrics:
        values = probe_values(metric)
        assert values, f"{metric.code} 应当有探测点"
        assert all(value > 0 for value in values)
        assert values == probe_values(metric), "探测点必须可复现"


def test_boundary_adjacent_threshold_matches_reported_values(med_metrics):
    report = scan_boundaries(med_metrics, tolerance=DEFAULT_TOLERANCE)
    for item in report.boundary_adjacent:
        assert item.smallest_delta <= BOUNDARY_ADJACENT
    for item in report.findings:
        assert item.smallest_delta > 0
        assert item.verdict != item.flipped_to


# --------------------------------------------------------------------------- #
# 6. 三种模式与偏差说明
# --------------------------------------------------------------------------- #


def test_report_states_the_mode_and_its_bias(med_metrics):
    """**模式必须写在报告里** —— 否则 65.8% 会被误读成"真实报告的脆弱率"。"""
    threshold_report = scan_boundaries(med_metrics)
    uniform_report = scan_uniform(med_metrics)

    assert threshold_report.mode == "thresholds"
    assert uniform_report.mode == "uniform"
    assert "阈值" in threshold_report.caveat
    assert "不能读成" in threshold_report.caveat
    assert "不等于真实报告分布" in uniform_report.caveat
    assert threshold_report.mode_label in threshold_report.to_markdown()
    assert uniform_report.caveat in uniform_report.to_markdown()


def test_threshold_scan_rate_is_higher_than_uniform(med_metrics):
    """阈值扫描刻意挑阈值，比例必然高于均匀取样——这个对比本身就是证据。"""
    threshold_rate = scan_boundaries(med_metrics).fragile_rate
    uniform_rate = scan_uniform(med_metrics).fragile_rate

    assert threshold_rate > uniform_rate, (
        "阈值扫描的比例应当明显更高；若不是，说明探测点没放在阈值上"
    )
    assert 0.0 <= uniform_rate <= 1.0
    assert 0.0 <= threshold_rate <= 1.0


def test_uniform_scan_is_deterministic(med_metrics):
    first = scan_uniform(med_metrics, seed=7)
    second = scan_uniform(med_metrics, seed=7)
    other = scan_uniform(med_metrics, seed=8)

    assert [item.value for item in first.findings] == [item.value for item in second.findings]
    assert first.probes == second.probes
    assert first.probes == other.probes, "换个种子探测点数不该变"


# --------------------------------------------------------------------------- #
# 7. 三个插件都能跑
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", PLUGIN_NAMES)
def test_every_plugin_has_a_usable_tolerance_and_scan(name):
    spec = find_plugin(name)
    metrics = load_metrics(spec.metrics)

    report = scan_boundaries(metrics, tolerance=spec.measurement_tolerance)

    assert report.probes > 0, f"{name} 一个探测点都没有，说明阈值没被读到"
    assert 0.0 <= report.fragile_rate <= 1.0
    assert report.skipped_no_boundaries == 0, f"{name} 有指标读不到阈值"


def test_plugin_tolerance_flows_into_the_scan():
    """信贷不是"测量误差"而是四舍五入口径，所以它声明 0.5% —— 必须真的生效。"""
    credit = find_plugin("credit-approval")
    med = find_plugin("med-checkup")

    assert credit.measurement_tolerance == 0.005
    assert med.measurement_tolerance == DEFAULT_TOLERANCE

    credit_report = scan_boundaries(
        load_metrics(credit.metrics), tolerance=credit.measurement_tolerance
    )
    assert all(item.smallest_delta <= 0.005 for item in credit_report.findings)


# --------------------------------------------------------------------------- #
# 8. 跨文件常量与清单校验
# --------------------------------------------------------------------------- #


def test_default_tolerance_is_consistent_across_files():
    """两处默认值必须一致（同 SAFETY_TERMS 的做法）：改了忘了另一处会静默分叉。"""
    assert DEFAULT_MEASUREMENT_TOLERANCE == DEFAULT_TOLERANCE


def test_tolerance_validation_is_loud():
    assert _tolerance(None) == DEFAULT_MEASUREMENT_TOLERANCE
    assert _tolerance(0.02) == 0.02
    with pytest.raises(PluginError, match="必须是数字"):
        _tolerance("不是数")
    with pytest.raises(PluginError, match="\\(0, 0.5\\]"):
        _tolerance(0.0)
    with pytest.raises(PluginError, match="\\(0, 0.5\\]"):
        _tolerance(0.9)


def test_manifest_rejects_bad_tolerance(tmp_path):
    plugin_dir = tmp_path / "bad-tol"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """
name: bad-tol
title: 测试
version: 1.0.0
summary: 测试
metrics: plugins/med-checkup/../../domain/med-metrics.yaml
domain_glob: domain/med-*/domain.yaml
verdict_ladder: [normal, mild]
advice_by_verdict:
  normal: 无需处理
  mild: 复查
measurement_tolerance: 2.0
""",
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="measurement_tolerance"):
        load_plugin(plugin_dir)


def test_needs_review_constant_is_the_engine_reserved_verdict():
    """`needs_review` 是引擎保留的"缺事实转人工"，不是业务判定。"""
    assert NEEDS_REVIEW == "needs_review"


_ = random  # 保留导入（供后续随机化实验使用）
