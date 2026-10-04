"""审计算法服务：把 A5 的图包成一个能点的网页。

## 这个服务的最小职责

1. 列出可选的演示样本（**只给编号和档案，不给标准答案**）
2. 对选中的样本跑审计图，**逐节点流式**把进度推给前端
3. 返回缺陷清单
4. 允许前端"揭示标准答案"，把审计结果与注入的已知缺陷并排对照

## 为什么"对照标准答案"这个功能很重要

审计器的价值全在"找得全不全都不知道"上。把**审计结果**和**注入的已知缺陷**并排显示，
一眼就能看出漏了什么、误报了什么——这比任何一段描述都有说服力。

## 为什么用样本而不是上传真实报告

系统里没有也不该有真实体检数据（见 README 的红线）。
演示用的是**程序合成**的产物，所以每一步都能给出精确的标准答案。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from agent.graph import build_audit_graph
from agent.judge import FakeJudge, build_judge
from agent.policy import AUDIT_POLICY
from agent.prompts import CURRENT_VERSION, current_prompt
from audit.inject import build_injected_dataset
from audit.pipeline import load_metrics
from audit.synth import DEFAULT_SEED, generate_reports

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parent / "web"

DEMO_CASE_COUNT = 60
DEMO_SEED = DEFAULT_SEED

app = FastAPI(title="auditkit", description="判定类 AI 输出的差分审计器")

_metrics = None
_cases = None
_judged = None


def _load_demo_data():
    """懒加载 + 缓存演示数据。生成一次就够，不必每次请求重算。"""
    global _metrics, _cases, _judged
    if _cases is None:
        _metrics = load_metrics()
        _judged = generate_reports(count=DEMO_CASE_COUNT, metrics=_metrics, seed=DEMO_SEED)
        _cases = build_injected_dataset(_judged, _metrics, seed=DEMO_SEED)
    return _metrics, _cases, _judged


def _judge_for_request(dry_run: bool):
    """默认走真实模型；`?dry_run=1` 或没有 key 时退化成假模型。

    让服务在**没有 API key 的情况下也能起来并跑通流程**——
    否则别人 clone 下来第一件事就是启动失败，这对开源项目很致命。
    """
    if dry_run or not os.getenv("DEEPSEEK_API_KEY"):
        return FakeJudge('{"violation": false, "category": "none", "evidence": ""}')
    return build_judge(use_cache=True)


def _case_index(case_id: str) -> int:
    _m, cases, _j = _load_demo_data()
    for index, case in enumerate(cases):
        if case.case_id == case_id:
            return index
    raise HTTPException(status_code=404, detail=f"没有这个样本：{case_id}")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "prompt_version": CURRENT_VERSION,
        "policy": AUDIT_POLICY.describe(),
        "has_api_key": bool(os.getenv("DEEPSEEK_API_KEY")),
    }


@app.get("/api/cases")
def list_cases() -> dict[str, Any]:
    """列出演示样本。**刻意不返回标准答案**——先看审计器怎么说，再揭示答案。"""
    _m, cases, _j = _load_demo_data()
    return {
        "cases": [
            {
                "case_id": case.case_id,
                "profile": case.profile,
                "clean": case.clean,
                "variation": case.variation,
            }
            for case in cases
        ]
    }


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict[str, Any]:
    """返回被审计的产物本身（不含标准答案）。"""
    index = _case_index(case_id)
    _m, cases, _j = _load_demo_data()
    return {"case_id": case_id, "artifact": cases[index].artifact.to_dict()}


@app.get("/api/cases/{case_id}/truth")
def get_truth(case_id: str) -> dict[str, Any]:
    """揭示标准答案：这个样本里到底注入了什么缺陷。"""
    index = _case_index(case_id)
    _m, cases, _j = _load_demo_data()
    case = cases[index]
    return {
        "case_id": case_id,
        "clean": case.clean,
        "variation": case.variation,
        "defects": [defect.to_dict() for defect in case.defects],
    }


@app.get("/api/audit/{case_id}")
def audit(case_id: str, dry_run: bool = False) -> dict[str, Any]:
    """跑一次完整审计（非流式）。"""
    metrics, cases, judged_cases = _load_demo_data()
    index = _case_index(case_id)
    case = cases[index]
    report = judged_cases[index][1].report

    graph, _nodes = build_audit_graph(
        policy=AUDIT_POLICY,
        judge=_judge_for_request(dry_run),
        metrics=metrics,
        prompt=current_prompt(),
    )
    final = graph.invoke(
        {
            "artifact": case.artifact.to_dict(),
            "report_values": dict(report.values),
            "sex": report.sex,
            "age": report.age,
        }
    )
    return {"case_id": case_id, "audit": final["audit"]}


@app.get("/api/audit/{case_id}/stream")
def audit_stream(case_id: str, dry_run: bool = False) -> StreamingResponse:
    """逐节点流式推送审计进度。

    用 LangGraph 的 `stream()` 而不是 `invoke()`：每个节点跑完就把增量推出去，
    前端能看到"正在做什么"，而不是盯着转圈等十几秒。
    """
    metrics, cases, judged_cases = _load_demo_data()
    index = _case_index(case_id)
    case = cases[index]
    report = judged_cases[index][1].report

    graph, _nodes = build_audit_graph(
        policy=AUDIT_POLICY,
        judge=_judge_for_request(dry_run),
        metrics=metrics,
        prompt=current_prompt(),
    )
    payload = {
        "artifact": case.artifact.to_dict(),
        "report_values": dict(report.values),
        "sex": report.sex,
        "age": report.age,
    }

    def events() -> Iterator[str]:
        collected: dict[str, dict[str, Any]] = {}
        try:
            for chunk in graph.stream(payload):
                for node_name, update in chunk.items():
                    collected[node_name] = update
                    yield _sse("node", {"node": node_name, "summary": _summarize(node_name, update)})
            yield _sse("done", {"audit": collected.get("finalize", {}).get("audit", {})})
        except Exception as exc:  # noqa: BLE001 — 出错也要让前端看到，而不是静默断流
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(events(), media_type="text/event-stream")


def _summarize(node_name: str, update: dict[str, Any]) -> str:
    if node_name == "plan":
        return f"计划检查 {len(update.get('planned_codes', []))} 个指标"
    if node_name == "inspect_deterministic":
        return f"确定性检查发现 {len(update.get('deterministic', []))} 条"
    if node_name == "inspect_semantic":
        return f"语义检查发现 {len(update.get('semantic', []))} 条，调用模型 {update.get('model_calls', 0)} 次"
    if node_name == "reflect":
        return f"反思后保留 {len(update.get('semantic', []))} 条，否掉 {len(update.get('rejected', []))} 条"
    if node_name == "decide":
        return "裁决：" + ("需人工复核" if update.get("escalated") else "可自动放行")
    if node_name == "human_review":
        return "已标记人工复核"
    if node_name == "finalize":
        return "生成审计结果"
    return node_name


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def main() -> None:  # pragma: no cover — 手动启动用
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":  # pragma: no cover
    main()
