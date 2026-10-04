"""检查器注册表测试。

这里要证明的核心只有一件事：

    **注册一个新检查器，不需要改 `audit/detect.py` 的任何一行。**

如果不能证明这一点，那"注册表"就只是换了个写法而已。

## 一个必须小心的地方

注册表是**模块级全局状态**。测试里注册了不清理，就会污染后面的测试——
那正是本项目吃过的亏（变异测试里出现过"元测试对所有变异体都失败"）。
所以每个注册测试都必须用 fixture 在结束时反注册。
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from audit.artifact import Artifact, ArtifactItem, replace_item
from audit.detect import (
    DEFAULT_REGISTRY,
    DETECTORS,
    Finding,
    detect,
    detector_kind_map,
    detector_names,
    register_detector,
)
from audit.inject import build_injected_dataset
from audit.pipeline import load_metrics
from audit.registry import DetectorContext, DetectorRegistry, DetectorSpec
from audit.synth import DEFAULT_SEED, generate_reports


@pytest.fixture(scope="module")
def metrics():
    return load_metrics()


@pytest.fixture(scope="module")
def sample(metrics):
    """一份产物 + 它对应的真实报告。"""
    judged = generate_reports(count=5, metrics=metrics, seed=DEFAULT_SEED)
    cases = build_injected_dataset(judged, metrics, seed=DEFAULT_SEED)
    report = judged[0][1].report
    return cases[0].artifact, report


@pytest.fixture
def clean_registry():
    """测试里注册的检查器，结束后一定要摘掉。

    注册表是模块级全局状态，不清理会污染后面的测试——
    那正是本项目吃过的亏。
    """
    before = set(DEFAULT_REGISTRY.names())
    yield
    for name in set(DEFAULT_REGISTRY.names()) - before:
        DEFAULT_REGISTRY.unregister(name)


def _with_unknown_item(artifact: Artifact) -> Artifact:
    """在产物最前面插一条"指标清单之外"的明细。"""
    stray = ArtifactItem(
        code="NOT_A_METRIC",
        name="清单外的项目",
        value=1.0,
        unit="x",
        reference_text="",
        severity="normal",
        explanation="",
        advice="",
        citations=(),
    )
    return replace(artifact, items=(stray,) + artifact.items)


# --------------------------------------------------------------------------- #
# 核心：扩展不需要改核心代码
# --------------------------------------------------------------------------- #


def test_new_detector_is_picked_up_without_touching_core(sample, clean_registry):
    """**这是注册表存在的唯一理由。**

    写一个函数、注册进去，`detect()` 就自动带上它——
    `audit/detect.py` 的调度逻辑一行都不用改。
    """
    artifact, report = sample
    baseline = detect(artifact, report.values, report.sex, report.age, load_metrics())
    baseline_names = {finding.detector for finding in baseline}
    assert "brand_new_check" not in baseline_names

    def brand_new_check(ctx: DetectorContext):
        # 一个刻意简单的检查器：第一条明细的名称不能为空
        for item, _metric in ctx.items():
            if not item.name.strip():
                yield Finding(
                    detector="brand_new_check",
                    target=item.code,
                    location="items[].name",
                    message="指标名称为空",
                    expected="非空",
                    observed=item.name,
                )
            else:
                # 保证这个测试一定有东西可断言（真实检查器不会这样写）
                yield Finding(
                    detector="brand_new_check",
                    target=item.code,
                    location="items[].name",
                    message="测试用：总是报一条",
                    expected="",
                    observed=item.name,
                )

    register_detector(
        DetectorSpec(
            name="brand_new_check",
            kinds=("some_future_defect",),
            run=brand_new_check,
            description="测试用：证明注册即生效",
        )
    )

    after = detect(artifact, report.values, report.sex, report.age, load_metrics())
    after_names = {finding.detector for finding in after}

    assert "brand_new_check" in after_names, "注册之后 detect() 应当自动带上它"
    # ⚠️ 用**活清单**，不要用 `DETECTORS`——那是导入时的快照。
    # （第一版这里断言 DETECTORS，失败了；这个坑正好证明快照与活清单必须分开。）
    assert "brand_new_check" in detector_names()
    assert detector_kind_map()["brand_new_check"] == ("some_future_defect",)
    # 原有检查器一个都没少
    assert baseline_names <= after_names


def test_detectors_constant_is_a_snapshot_not_a_live_view(clean_registry):
    """把"快照"这件事明确写进测试，免得以后有人误用它。"""
    register_detector(
        DetectorSpec(
            name="snapshot_probe", kinds=(), run=lambda ctx: (), description="探针"
        )
    )
    assert "snapshot_probe" not in DETECTORS, "DETECTORS 是导入时的快照，不该变"
    assert "snapshot_probe" in detector_names(), "活清单必须能看到它"


def test_registration_updates_the_kind_map(sample, clean_registry):
    """检查器 -> 缺陷类型的映射从注册表推出，不再手工维护第二份。"""
    register_detector(
        DetectorSpec(
            name="kinds_probe",
            kinds=("alpha", "beta"),
            run=lambda ctx: (),
            description="测试用：验证 kinds 能推出来",
        )
    )
    assert DEFAULT_REGISTRY.kinds_for("kinds_probe") == ("alpha", "beta")
    assert DEFAULT_REGISTRY.detector_for_kind("beta") == "kinds_probe"


def test_unregister_removes_it(sample, clean_registry):
    register_detector(
        DetectorSpec(
            name="temporary", kinds=(), run=lambda ctx: (), description="临时"
        )
    )
    assert "temporary" in DEFAULT_REGISTRY.names()
    DEFAULT_REGISTRY.unregister("temporary")
    assert "temporary" not in DEFAULT_REGISTRY.names()


# --------------------------------------------------------------------------- #
# 防误用
# --------------------------------------------------------------------------- #


def test_duplicate_registration_is_refused(clean_registry):
    """重名注册必须报错。

    **静默覆盖会让旧行为无声消失** —— 这正是本项目里"提示词引入新类别
    而 policy 不认识"那类问题的同一形状。
    """
    spec = DetectorSpec(name="dup", kinds=(), run=lambda ctx: (), description="第一次")
    register_detector(spec)

    with pytest.raises(ValueError, match="已经注册过了"):
        register_detector(
            DetectorSpec(name="dup", kinds=(), run=lambda ctx: (), description="第二次")
        )

    # 显式覆盖才行
    replaced = register_detector(
        DetectorSpec(name="dup", kinds=(), run=lambda ctx: (), description="显式覆盖"),
        replace=True,
    )
    assert replaced.description == "显式覆盖"


def test_spec_requires_a_description():
    """没写说明的检查器不予接受——它防的是什么必须能说出来。"""
    with pytest.raises(ValueError, match="description"):
        DetectorSpec(name="x", kinds=(), run=lambda ctx: (), description="   ")


def test_spec_rejects_unknown_scope():
    with pytest.raises(ValueError, match="scope"):
        DetectorSpec(
            name="x", kinds=(), run=lambda ctx: (), description="ok", scope="magic"
        )


def test_unknown_detector_lookup_raises():
    with pytest.raises(KeyError, match="没有这个检查器"):
        DEFAULT_REGISTRY.get("nope_not_here")


# --------------------------------------------------------------------------- #
# 上下文对象
# --------------------------------------------------------------------------- #


def test_context_items_skips_unknown_codes(sample):
    """`items()` 自动跳过指标清单之外的条目。

    原版循环用 `continue` 跳过未知指标，但那是因为所有检查共用一个循环。
    拆成独立检查器后，每个检查器都要自己防住 KeyError——
    把这件事收进 `items()`，新检查器就不用各自重复防一遍。
    """
    artifact, report = sample
    broken = _with_unknown_item(artifact)
    ctx = DetectorContext(
        artifact=broken,
        report_values=report.values,
        sex=report.sex,
        age=report.age,
        metrics=load_metrics(),
    )

    assert "NOT_A_METRIC" in ctx.unknown_codes()
    assert all(code != "NOT_A_METRIC" for code, _metric in ctx.items())


def test_unknown_code_does_not_crash_other_detectors(sample):
    """清单外的指标不该让其他检查器崩掉（原版是靠 continue 保住的）。"""
    artifact, report = sample
    broken = _with_unknown_item(artifact)

    findings = detect(broken, report.values, report.sex, report.age, load_metrics())

    assert any(f.detector == "unit_consistency" for f in findings), "应当报出清单外的指标"
    assert all(f.target for f in findings)


def test_report_values_flag_marks_the_differential_detectors():
    """标注哪些检查器需要原始数据——这是差分审计与普通核查的分界。"""
    needs = {spec.name for spec in DEFAULT_REGISTRY.all() if spec.requires_report_values}
    assert needs == {"oracle_differential", "value_consistency"}


def test_describe_renders_every_detector():
    text = DEFAULT_REGISTRY.describe()
    for name in DEFAULT_REGISTRY.names():
        assert name in text
    assert "负责的缺陷" in text


def test_registry_can_be_scoped_per_call(sample):
    """可以传一个自己的注册表跑检测——为的是"不同场景用不同检查器"。"""
    artifact, report = sample
    only_safety = DetectorRegistry(
        [spec for spec in DEFAULT_REGISTRY.all() if spec.name == "safety_terms"]
    )
    findings = detect(
        artifact, report.values, report.sex, report.age, load_metrics(), registry=only_safety
    )
    assert {f.detector for f in findings} <= {"safety_terms"}
