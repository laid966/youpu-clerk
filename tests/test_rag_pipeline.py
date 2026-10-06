"""RAG 链路测试。

守五件事：

1. **基线不许动**：全关新级时，`RagPipeline.search` 必须与原来的 `build_retriever` 逐条一致
   ——否则"新链路提升了多少"这个说法就不成立（基线被偷偷改了）
2. **开关是真的**：关掉/打开某一级，结果必须变（防止开关是装饰）
3. **接口兼容**：`evaluate_retrieval(pipeline, ...)` 能直接跑（这是逐级量化的地基）
4. **软路由不排除**：意图判断错了也不能把正确答案删掉（硬路由的教训）
5. **边界不许静默**：a) `audit/` 不许 import `rag/`；b) 未实现的向量级要明确报错而不是假装打开
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from rag.boundary import REFUSAL, CorrectnessRule, RefusalBoundary
from rag.knowledge import LAYER_EXPLANATION, LAYER_GUIDELINE, load_knowledge
from rag.pipeline import PipelineFlags, RagPipeline, build_pipeline
from rag.retrieval_eval import build_eval_set, evaluate_retrieval
from rag.retriever import build_retriever
from rag.stage_eval import (
    candidate_thresholds,
    compare_stages,
    evaluate_refusal,
    load_refusal_questions,
    sweep_thresholds,
)
from rag.stages import QueryPlan, rrf_fuse, understand_query

ROOT = Path(__file__).resolve().parents[1]
CORE_PACKAGES = ("engine", "rag", "audit", "agent", "plugin")


@pytest.fixture(scope="module")
def knowledge():
    return load_knowledge()


@pytest.fixture(scope="module")
def metrics():
    from audit.pipeline import load_metrics

    return load_metrics()


@pytest.fixture(scope="module")
def template_cases(knowledge):
    return tuple(c for c in build_eval_set(knowledge) if c.source == "template")


# --------------------------------------------------------------------------- #
# 1. 基线不许动
# --------------------------------------------------------------------------- #


def test_all_stages_off_equals_the_original_retriever(knowledge, metrics, template_cases):
    """**全关新级时，结果必须与原来的 `build_retriever` 逐条一致。**

    这是整份工作的地基：如果"基线"被偷偷改了，
    "查询理解把 Recall@1 提了 5.6 个百分点"这句话就没有意义。
    """
    baseline = build_retriever(knowledge)
    pipeline = build_pipeline(
        knowledge=knowledge,
        flags=PipelineFlags(query_understanding=False, metric_rerank=False),
        metrics=metrics,
    )

    for case in template_cases:
        old = [hit.chunk_id for hit in baseline.search(case.query, top_k=5)]
        new = [hit.chunk_id for hit in pipeline.search(case.query, top_k=5)]
        assert old == new, f"{case.case_id} 的基线结果被改动了：{old} != {new}"


def test_pipeline_works_with_the_existing_evaluator(knowledge, metrics, template_cases):
    """`evaluate_retrieval` 要能直接评测新链路（接口兼容）。"""
    pipeline = build_pipeline(knowledge=knowledge, metrics=metrics)
    report = evaluate_retrieval(pipeline, template_cases, k_values=(1, 3, 5))

    assert report.cases == len(template_cases)
    assert 0.0 <= report.recall_at(1) <= 1.0


# --------------------------------------------------------------------------- #
# 2. 开关是真的 + 3. 每级的实际效果
# --------------------------------------------------------------------------- #


def test_stage_switches_actually_change_results(knowledge, metrics, template_cases):
    """关掉/打开某一级，结果必须变——否则开关是装饰。"""
    off = build_pipeline(
        knowledge=knowledge,
        flags=PipelineFlags(query_understanding=False, metric_rerank=False),
        metrics=metrics,
    )
    on = build_pipeline(knowledge=knowledge, flags=PipelineFlags(), metrics=metrics)

    changed = 0
    for case in template_cases:
        if [h.chunk_id for h in off.search(case.query)] != [
            h.chunk_id for h in on.search(case.query)
        ]:
            changed += 1
    assert changed > 0, "开关打开后一条结果都没变——开关是假的"


def test_soft_routing_beats_hard_routing_on_a_known_failure(knowledge, metrics):
    """**硬路由的教训要变成测试。**

    实测：硬路由把 Recall@1 从 91.7% 打到 72.2%（-19.4 个点），
    因为它把"没被选中的那一层"整个排除，而意图判断是会错的。

    这条测试保证：**软路由永远不会比硬路由差**（在层过滤这件事上）。
    """
    cases = tuple(c for c in build_eval_set(knowledge))
    soft = compare_stages(knowledge=knowledge, cases=cases, metrics=metrics)
    rows = {row.label: row for row in soft.rows}

    soft_row = next(row for label, row in rows.items() if "软路由" in label)
    hard_row = next(row for label, row in rows.items() if "硬路由" in label)

    assert soft_row.recall(1) > hard_row.recall(1), (
        f"软路由 {soft_row.recall(1):.1%} 竟然不高于硬路由 {hard_row.recall(1):.1%}——"
        "说明软路由没起作用，或者层过滤又回来了"
    )


def test_soft_routing_does_not_exclude_any_layer(knowledge, metrics):
    """软路由下，计划里必须仍然包含全部可检索层。"""
    pipeline = build_pipeline(knowledge=knowledge, metrics=metrics)
    plan = pipeline.plan("ALT 偏高怎么办")

    assert plan.priority_layer is not None, "这句应当能判断出优先层"
    assert set(plan.layers) == {LAYER_EXPLANATION, LAYER_GUIDELINE}, (
        "软路由不许排除任何层——排除就是硬路由，实测会掉 19 个点"
    )


def test_determinism(knowledge, metrics, template_cases):
    pipeline = build_pipeline(knowledge=knowledge, metrics=metrics)
    for case in template_cases[:8]:
        first = [h.chunk_id for h in pipeline.search(case.query)]
        second = [h.chunk_id for h in pipeline.search(case.query)]
        assert first == second


# --------------------------------------------------------------------------- #
# 4. 查询理解
# --------------------------------------------------------------------------- #


def test_understand_query_recognizes_metric_aliases(metrics):
    """口语别名要认出来——这是"转氨酶"能匹配到"丙氨酸氨基转移酶"的前提。"""
    plan = understand_query("转氨酶高是不是熬夜熬的", metrics)
    assert plan.metric_code == "alt"

    plan = understand_query("尿酸高能不能吃海鲜", metrics)
    assert plan.metric_code == "ua"

    plan = understand_query("肌酐多少算高", metrics)
    assert plan.metric_code == "crea"


def test_understand_query_detects_intent(metrics):
    guideline = understand_query("抽血前能喝水吗", metrics)
    assert guideline.priority_layer == LAYER_GUIDELINE

    explanation = understand_query("ALT 是什么", metrics)
    assert explanation.priority_layer == LAYER_EXPLANATION


def test_understand_query_degrades_to_no_preference(metrics):
    """认不出意图时不该硬猜——不加层偏好，全库检索。"""
    plan = understand_query("嗯嗯嗯", metrics)
    assert plan.intent == "unknown"
    assert plan.priority_layer is None
    assert set(plan.layers) == {LAYER_EXPLANATION, LAYER_GUIDELINE}


def test_understand_query_is_deterministic(metrics):
    first = understand_query("ALT 偏高怎么办", metrics)
    second = understand_query("ALT 偏高怎么办", metrics)
    assert first == second


# --------------------------------------------------------------------------- #
# 5. RRF 只看名次
# --------------------------------------------------------------------------- #


def test_rrf_uses_rank_not_score():
    """两路融合必须**只按名次**——分数尺度不同（BM25 无界 vs 余弦 [0,1]）时，
    分数相加等于让其中一路随机主宰排序。"""
    fused = rrf_fuse([["a", "b", "c"], ["a", "c", "b"]])

    assert fused[0][0] == "a", "两路都排第一的必须整体第一"
    # b 与 c 在两名次上对称，分数相同 → 按 id 稳定排序
    assert [doc for doc, _score in fused[1:]] == ["b", "c"]


def test_rrf_rejects_bad_k():
    with pytest.raises(ValueError, match="k 必须为正"):
        rrf_fuse([["a"]], k=0)


# --------------------------------------------------------------------------- #
# 6. 拒答：双向 + 数据驱动的阈值
# --------------------------------------------------------------------------- #


def test_refusal_boundary_validates_itself():
    with pytest.raises(ValueError, match="不能是负数"):
        RefusalBoundary(min_top_score=-1.0)
    with pytest.raises(ValueError, match="min_hits"):
        RefusalBoundary(min_hits=0)


def test_should_refuse_logic():
    boundary = RefusalBoundary(min_top_score=2.0, min_hits=1)
    assert boundary.should_refuse([]) is True
    assert boundary.should_refuse([1.9]) is True
    assert boundary.should_refuse([2.0]) is False
    assert boundary.should_refuse([5.0]) is False


def test_refusal_is_two_sided(knowledge, metrics, template_cases):
    """拒答必须**双向测量**：只报"挡了多少"是骗自己。"""
    out_kb = load_refusal_questions()
    assert out_kb, "拒答问句集不该为空"

    report = evaluate_refusal(
        knowledge, template_cases, out_kb, boundary=RefusalBoundary(min_top_score=0.0), metrics=metrics
    )

    assert 0.0 <= report.refusal_accuracy <= 1.0
    assert 0.0 <= report.false_refusal_rate <= 1.0
    # 阈值为 0（几乎不拒答）时，库内问题不该被误拒
    assert report.false_refusal_rate == 0.0


def test_thresholds_are_derived_from_the_score_distribution(knowledge, metrics, template_cases):
    """候选阈值必须**从实际分数分布推导**，不是硬编码网格。

    踩过的坑：固定网格 `[0, 0.5, 1, 1.5, 2, 3, 4]` 与 BM25 的真实分数
    （2.9～13.5）完全错开，扫描表 7 行里只有 1 行有信息。
    """
    out_kb = load_refusal_questions()
    thresholds = candidate_thresholds(knowledge, template_cases, out_kb, metrics)

    assert len(thresholds) >= 2, "至少要能区分出两个候选点"
    assert thresholds == tuple(sorted(thresholds)), "候选阈值必须有序"
    assert max(thresholds) > 2.0, (
        "候选阈值全都小于 2，说明没落在真实分数分布上——又回到硬编码网格的老路了"
    )


def test_sweep_produces_a_monotone_curve(knowledge, metrics, template_cases):
    """阈值越大 → 越倾向拒答：库外拒答率与库内误伤率都应当**单调不降**。"""
    out_kb = load_refusal_questions()
    rows = sweep_thresholds(knowledge, template_cases, out_kb, metrics=metrics)

    accuracies = [row.refusal_accuracy for row in rows]
    damages = [row.false_refusal_rate for row in rows]
    assert accuracies == sorted(accuracies), "库外拒答率应当随阈值单调不降"
    assert damages == sorted(damages), "库内误伤率应当随阈值单调不降"


# --------------------------------------------------------------------------- #
# 7. 边界：不许静默
# --------------------------------------------------------------------------- #


def test_audit_does_not_import_rag():
    """`audit/` 不许 import `rag/` —— 否则形成循环依赖。

    `rag/knowledge.py` 已经有一个反向的延迟导入在打补丁，
    所以这个方向必须守住。合法引用的扩大由**调用方**完成（见 `extra_citations`）。
    """
    offenders: list[str] = []
    for path in (ROOT / "audit").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{path.name}:{node.lineno} {alias.name}"
                    for alias in node.names
                    if alias.name == "rag" or alias.name.startswith("rag.")
                ]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "rag" or module.startswith("rag."):
                    offenders.append(f"{path.name}:{node.lineno} from {module}")
    assert not offenders, f"audit 里出现了对 rag 的导入：{offenders}"


def test_extra_citations_are_merged(metrics, knowledge):
    """知识库的引用要能通过 `extra_citations` 并进合法引用集合。"""
    from audit.pipeline import known_citations

    base = known_citations(metrics)
    merged = known_citations(metrics, knowledge.citation_ids())

    assert len(merged) > len(base)
    sample = sorted(knowledge.citation_ids())[0]
    assert sample not in base
    assert sample in merged


def test_unimplemented_dense_stage_fails_loudly():
    """向量级还没实现——打开它必须**明确报错**，不能假装打开了。"""
    with pytest.raises(NotImplementedError, match="向量级还没实现"):
        PipelineFlags(dense=True)


def test_recall_stage_cannot_be_disabled():
    with pytest.raises(ValueError, match="什么都不返回"):
        PipelineFlags(recall=False)


def test_correctness_rule_validates_itself():
    with pytest.raises(ValueError, match="必须声明哪些层算数"):
        CorrectnessRule(strict=False, tolerant_layers=())


# --------------------------------------------------------------------------- #
# 8. 拒答问句集的格式
# --------------------------------------------------------------------------- #


def test_refusal_questions_include_hard_near_misses():
    """拒答集里必须混入"医学相关但知识库没有"的难例。

    只测"股票明天涨吗"这种明显无关的问题等于没测——系统不瞎猜就能过。
    """
    raw = (ROOT / "eval" / "refusal-questions.jsonl").read_text(encoding="utf-8")
    assert "near-miss" in raw, "拒答集里必须有 near-miss 难例"
    assert load_refusal_questions()


def test_refusal_loader_rejects_bad_rows(tmp_path):
    bad = tmp_path / "r.jsonl"
    bad.write_text('{"query": ""}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="缺少 query"):
        load_refusal_questions(bad)

    bad.write_text('{"query": "x"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="第 1 行"):
        load_refusal_questions(bad)
