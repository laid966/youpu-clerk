"""Web 服务测试。

用 FastAPI 的 TestClient（走 ASGI，不真起服务器、不占端口）。

**全部请求都带 `dry_run=true`**，强制走假模型：测试不联网、不花钱、结果确定。
真实模型路径由 `python -m agent eval-semantic` 与 `agent audit` 覆盖
（那两条命令是给人跑的，不是给 CI 跑的）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.server import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_configuration(client):
    payload = client.get("/api/health").json()

    assert payload["status"] == "ok"
    assert payload["prompt_version"]
    assert "范围=" in payload["policy"]
    assert isinstance(payload["has_api_key"], bool)


def test_index_serves_the_page(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "auditkit" in response.text
    assert "api/cases" in response.text, "页面必须真的去调接口"


def test_cases_list_does_not_leak_ground_truth(client):
    """列表接口**刻意不返回标准答案**——先看审计器怎么说，再揭示答案。"""
    payload = client.get("/api/cases").json()

    assert payload["cases"], "应当有演示样本"
    for case in payload["cases"]:
        assert set(case) == {"case_id", "profile", "clean", "variation"}, (
            "列表里不许出现 defects 之类的答案字段"
        )


def test_artifact_endpoint_returns_items(client):
    case_id = client.get("/api/cases").json()["cases"][0]["case_id"]

    artifact = client.get(f"/api/cases/{case_id}").json()["artifact"]

    assert artifact["items"], "产物必须有指标明细"
    # 注意两个编号是不同的东西：C-xxxx 是**注入样本编号**，R-xxxx 是底层报告编号。
    # 一份报告可能对应多个注入样本，所以不能混用。
    assert artifact["report_id"].startswith("R-"), artifact["report_id"]
    assert case_id.startswith("C-")


def test_truth_endpoint_reveals_defects(client):
    payload = client.get("/api/cases/C-0001/truth").json()

    assert "defects" in payload and "clean" in payload


def test_unknown_case_returns_404(client):
    assert client.get("/api/cases/NOPE").status_code == 404
    assert client.get("/api/audit/NOPE").status_code == 404


def test_audit_runs_without_api_key(client):
    """没有 API key 也必须能跑通流程。

    否则别人 clone 下来第一件事就是启动失败——这对开源项目很致命。
    """
    case_id = client.get("/api/cases").json()["cases"][0]["case_id"]

    payload = client.get(f"/api/audit/{case_id}?dry_run=true").json()

    assert payload["case_id"] == case_id
    audit = payload["audit"]
    assert {"findings", "counts", "model_calls", "policy", "escalated"} <= set(audit)


def test_stream_emits_node_events_then_done(client):
    case_id = client.get("/api/cases").json()["cases"][0]["case_id"]

    with client.stream("GET", f"/api/audit/{case_id}/stream?dry_run=true") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: node" in body
    assert "event: done" in body
    # 每个节点都要报进度，否则前端只会干等
    for node in ("plan", "inspect_deterministic", "inspect_semantic", "reflect", "finalize"):
        assert f'"node": "{node}"' in body, f"缺少节点进度：{node}"
    assert "event: error" not in body
