"""插件系统测试。

三条底线：

1. **本体不认识行业**：核心代码里不许出现具体场景的名字（有测试扫源码守着）
2. **清单错就报错**：不静默兜底
3. **换插件能跑通**：三个插件用同一套本体机制跑出结果，且干净产物零误报
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugin.demo import build_clean_artifact, misjudge_one, run_demo, verdict_ladder
from plugin.spec import (
    PluginError,
    discover_plugins,
    find_plugin,
    load_plugin,
    load_prompts,
)

ROOT = Path(__file__).resolve().parents[1]

#: 本体（机制）所在的包。`plugins/` 刻意不在其中——那里的内容本来就该是行业专属的。
CORE_PACKAGES = ("engine", "rag", "audit", "agent", "plugin")


@pytest.fixture(scope="module")
def plugins():
    return discover_plugins()


# --------------------------------------------------------------------------- #
# 1. 本体不认识行业
# --------------------------------------------------------------------------- #


def test_core_does_not_mention_scenario_names():
    """**这是整个插件化最重要的守卫。**

    如果哪天有人图省事，在核心代码里写一句
    `if plugin.name == "credit-approval": ...`，本体就又不独立了——
    而且这个退化是**静默的**：所有测试照样通过，只是第二、第三个场景开始要改核心代码。

    所以这里扫源码。**只扫"代码里的字符串"，不扫文档字符串**——
    文档里举例说明是正常的，写进逻辑里才是依赖。
    """
    import ast

    forbidden = ("credit-approval", "credit_approval", "claim-review", "claim_review")
    offenders: list[str] = []

    for package in CORE_PACKAGES:
        for path in (ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                    body = getattr(node, "body", [])
                    if (
                        body
                        and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)
                    ):
                        docstrings.add(id(body[0].value))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings
                ):
                    for needle in forbidden:
                        if needle in node.value:
                            offenders.append(
                                f"{path.relative_to(ROOT)}:{node.lineno} 出现了 {needle!r}"
                            )

    assert not offenders, (
        "本体代码里出现了具体场景的名字，说明行业知识漏回核心了：\n  "
        + "\n  ".join(offenders)
        + "\n\n应当把这些差异放进插件清单，而不是写进核心代码。"
    )


def test_core_does_not_hardcode_scenario_verdicts():
    """本体的默认建议映射只覆盖医学场景，且**不被非医学插件依赖**。

    非医学插件的判定等级（approved/review/rejected、eligible/review/excluded）
    必须由插件自己声明——如果核心常量里出现了它们，说明等级表被写死了。
    """
    from audit.artifact import ADVICE_BY_SEVERITY

    for verdict in ("approved", "rejected", "eligible", "excluded"):
        assert verdict not in ADVICE_BY_SEVERITY, (
            f"核心的建议映射里出现了 {verdict!r}——那是信贷/理赔场景的判定等级，"
            "不该写进本体"
        )


# --------------------------------------------------------------------------- #
# 2. 清单读得对
# --------------------------------------------------------------------------- #


def test_three_plugins_are_discovered(plugins):
    names = [spec.name for spec in plugins]
    assert names == ["claim-review", "credit-approval", "med-checkup"]


def test_every_plugin_declares_what_the_core_needs(plugins):
    for spec in plugins:
        assert spec.title and spec.summary
        assert spec.metrics.is_file()
        assert spec.advice_by_verdict, f"{spec.name} 没声明 判定→建议 映射"
        assert spec.benign_templates, f"{spec.name} 没声明合法说法模板"
        assert spec.citation_catalogue, f"{spec.name} 没声明合法引用目录"


def test_med_plugin_matches_core_defaults(plugins):
    """医学插件声明的词表与建议，必须与本体默认常量一致。

    两处同源是刻意的（老调用方不传插件时用默认值），
    但**同源必须由测试守着**，否则改了一处忘了另一处会静默分叉。
    """
    from audit.artifact import ADVICE_BY_SEVERITY, SAFETY_TERMS

    med = find_plugin("med-checkup")
    assert set(med.safety_terms) == set(SAFETY_TERMS)
    assert dict(med.advice_by_verdict) == dict(ADVICE_BY_SEVERITY)


def test_plugin_verdict_ladders_come_from_the_plugin(plugins):
    """判定等级由插件的判定域声明，三个场景各不相同。"""
    ladders = {spec.name: verdict_ladder(spec) for spec in plugins}

    assert ladders["med-checkup"] == ("normal", "mild", "marked", "critical")
    assert ladders["credit-approval"] == ("approved", "review", "rejected")
    assert ladders["claim-review"] == ("eligible", "review", "excluded")


def test_plugin_prompts_are_loaded_per_scenario(plugins):
    """提示词随插件走：两个非医学插件的提示词内容必须不同。"""
    credit = load_prompts(find_plugin("credit-approval"))
    claim = load_prompts(find_plugin("claim-review"))

    assert credit and claim
    assert set(credit) == {"v1"} and set(claim) == {"v1"}
    assert credit["v1"] != claim["v1"], "两个场景的提示词不该是一样的"
    for text in (*credit.values(), *claim.values()):
        assert "{text}" in text


# --------------------------------------------------------------------------- #
# 3. 清单错就报错
# --------------------------------------------------------------------------- #


def _write_manifest(tmp_path: Path, name: str, body: str) -> Path:
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    # 这些测试都要走到"字段校验"，所以先备好会被引用的真实文件
    (directory / "metrics.yaml").write_text("metrics: []\n", encoding="utf-8")
    (directory / "plugin.yaml").write_text(body, encoding="utf-8")
    return directory


BASE = """
name: {name}
title: 测试插件
version: 1.0.0
summary: 测试
metrics: plugins/x/metrics.yaml
domain_glob: plugins/x/domain/*.yaml
verdict_ladder: [ok, bad]
advice_by_verdict:
  ok: 通过
"""


def test_missing_required_field_is_loud(tmp_path):
    directory = _write_manifest(
        tmp_path, "broken", "name: broken\ntitle: 缺字段\nversion: 1.0.0\n"
    )
    with pytest.raises(PluginError, match="缺少必需字段"):
        load_plugin(directory)


def test_name_must_match_directory(tmp_path):
    directory = _write_manifest(
        tmp_path,
        "actual-dir",
        BASE.format(name="other-name").replace("plugins/x", "plugins/credit-approval"),
    )
    with pytest.raises(PluginError, match="目录名"):
        load_plugin(directory)


def test_missing_file_is_loud(tmp_path):
    directory = _write_manifest(
        tmp_path,
        "nofile",
        """
name: nofile
title: 路径不存在
version: 1.0.0
summary: 测试
metrics: plugins/does-not-exist/metrics.yaml
domain_glob: plugins/x/domain/*.yaml
verdict_ladder: [ok, bad]
advice_by_verdict:
  ok: 通过
""",
    )
    with pytest.raises(PluginError, match="不存在的文件"):
        load_plugin(directory)


def test_empty_advice_map_is_refused(tmp_path):
    """没有"判定→建议"映射，`advice_contract` 这个检查器就失效了，所以要报错。"""
    directory = _write_manifest(
        tmp_path,
        "noadvice",
        """
name: noadvice
title: 缺建议映射
version: 1.0.0
summary: 测试
metrics: plugins/credit-approval/metrics.yaml
domain_glob: plugins/x/domain/*.yaml
verdict_ladder: [ok, bad]
advice_by_verdict: {}
""",
    )
    with pytest.raises(PluginError, match="advice_by_verdict"):
        load_plugin(directory)


def test_unknown_plugin_name_lists_what_exists():
    with pytest.raises(PluginError, match="没有这个插件"):
        find_plugin("not-a-plugin")


# --------------------------------------------------------------------------- #
# 4. 换插件能跑通（最核心的一条）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["claim-review", "credit-approval", "med-checkup"])
def test_every_plugin_runs_on_the_same_core(name):
    """**同一套本体机制，三个场景都跑通。**

    这是"本体独立"的直接证据：换插件、本体一行代码不改。
    """
    result = run_demo(find_plugin(name))

    assert result.items >= 2
    assert result.clean, f"{name} 的干净产物上出现了误报：{result.clean_findings}"
    assert result.caught, f"{name} 的错误判定没被抓到"


def test_demo_uses_the_plugin_advice_map(plugins):
    """产物里的建议来自插件，而不是本体的默认映射。"""
    plugin = find_plugin("credit-approval")
    artifact, _values = build_clean_artifact(plugin)

    for item in artifact.items:
        assert item.advice == plugin.advice_by_verdict[item.severity]


def test_demo_is_deterministic(plugins):
    first = run_demo(find_plugin("credit-approval"))
    second = run_demo(find_plugin("credit-approval"))

    assert first.clean_findings == second.clean_findings
    assert first.broken_findings == second.broken_findings


def test_misjudge_changes_verdict_and_advice_together(plugins):
    """刻意同时改判定与建议，让它是"纯粹的判错"，不会顺带触发别的检查器。"""
    plugin = find_plugin("claim-review")
    artifact, _values = build_clean_artifact(plugin)

    broken, wrong = misjudge_one(artifact, plugin)

    assert broken.items[0].severity == wrong
    assert broken.items[0].advice == plugin.advice_by_verdict[wrong]
    assert broken.items[0].severity != artifact.items[0].severity


def test_plugin_with_missing_verdict_mapping_is_loud():
    """插件声明了判定，却没给对应的建议 → 直接报错，不兜底。

    静默兜底会让这个检查器"看起来在工作、实际永远不报警"。
    """
    from dataclasses import replace

    plugin = replace(find_plugin("credit-approval"), advice_by_verdict={"rejected": "不予放款"})
    with pytest.raises(PluginError, match="advice_by_verdict"):
        build_clean_artifact(plugin)
