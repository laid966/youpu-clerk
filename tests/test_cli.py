"""`engine/cli.py` 的测试。

CLI 是用户真正接触的接口，所以它也得有测试。
这里只测三件最容易坏、且坏了最让人恼火的事：
1. 从文件读事实时，Windows 工具写出的 BOM 不能让程序崩掉；
2. 输入坏了要给一句人话，而不是甩一堆堆栈；
3. 生成命令真的产出指定条数的数据集。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.cli import main

ROOT = Path(__file__).resolve().parents[1]
AIRLINE = str(ROOT / "domain" / "airline-fare-sample" / "domain.yaml")

VALID_FACTS = {
    "order_amount": 15000,
    "cabin_class": "business",
    "fare_type": "standard",
    "hours_before_departure": 100,
    "discount_rate": 0.4,
    "is_through_ticket": False,
    "is_noshow": False,
    "used_segments": 0,
    "total_segments": 1,
}


def test_decide_reads_plain_utf8_file(tmp_path, capsys):
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(json.dumps(VALID_FACTS), encoding="utf-8")

    code = main(["decide", "--domain", AIRLINE, "--facts", str(facts_file)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["winning_rule_id"] == "R-006"
    assert payload["fee_amount"] == "750.00"


def test_decide_reads_file_with_utf8_bom(tmp_path, capsys):
    """真实回归：PowerShell 的 `Set-Content -Encoding UTF8` 会写 BOM。

    用 utf-8 去解，第一个字符就是 BOM，json.loads 报
    "Expecting value: line 1 column 1"——用户会一脸问号。
    """
    facts_file = tmp_path / "facts.json"
    facts_file.write_bytes(b"\xef\xbb\xbf" + json.dumps(VALID_FACTS).encode("utf-8"))

    code = main(["decide", "--domain", AIRLINE, "--facts", str(facts_file)])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["fee_amount"] == "750.00"


def test_decide_reports_bad_json_without_traceback(tmp_path, capsys):
    facts_file = tmp_path / "facts.json"
    facts_file.write_text("{ 这不是 JSON", encoding="utf-8")

    code = main(["decide", "--domain", AIRLINE, "--facts", str(facts_file)])

    assert code == 2
    assert "不是合法 JSON" in capsys.readouterr().err


def test_decide_rejects_non_object_json(tmp_path, capsys):
    facts_file = tmp_path / "facts.json"
    facts_file.write_text("[1, 2, 3]", encoding="utf-8")

    code = main(["decide", "--domain", AIRLINE, "--facts", str(facts_file)])

    assert code == 2
    assert "JSON 对象" in capsys.readouterr().err


def test_decide_reports_missing_file(tmp_path):
    with pytest.raises(SystemExit, match="找不到事实文件"):
        main(["decide", "--domain", AIRLINE, "--facts", str(tmp_path / "nope.json")])


def test_decide_reports_unknown_fact_as_friendly_error(capsys):
    """走管道输入：多给一个没声明的字段，必须是人话报错（退出码 2），不是堆栈。"""
    import io
    import sys

    payload = {**VALID_FACTS, "whatever": 1}
    fake_stdin = type("S", (), {"buffer": io.BytesIO(json.dumps(payload).encode("utf-8"))})()
    original = sys.stdin
    sys.stdin = fake_stdin
    try:
        code = main(["decide", "--domain", AIRLINE, "--facts", "-"])
    finally:
        sys.stdin = original

    assert code == 2
    assert "未声明的字段" in capsys.readouterr().err


def test_check_writes_report(tmp_path, capsys):
    report = tmp_path / "report.md"

    code = main(
        ["check", "--domain", AIRLINE, "--samples", "300", "--report", str(report)]
    )

    assert code == 0
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "规则自检报告" in text
    assert "反例搜索" in text


def test_gen_writes_expected_number_of_cases(tmp_path, capsys):
    out = tmp_path / "dataset.jsonl"
    sample = tmp_path / "dataset.sample.md"

    code = main(
        [
            "gen",
            "--domain",
            AIRLINE,
            "--count",
            "40",
            "--out",
            str(out),
            "--sample-out",
            str(sample),
        ]
    )

    assert code == 0
    produced = sorted(tmp_path.glob("dataset-*.jsonl"))
    assert len(produced) == 1
    lines = produced[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 40
    assert json.loads(lines[0])["id"] == "case-0001"


def test_check_with_unknown_domain_returns_error_code(capsys):
    code = main(["check", "--domain", "domain/does-not-exist/domain.yaml"])

    assert code == 2
    assert "找不到判定域文件" in capsys.readouterr().err
