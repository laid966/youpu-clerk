"""`engine/domain.py` 的测试：判定域加载与校验。

核心主张是"规则是数据"。**数据一旦写错，必须在加载阶段就炸**，
而不是等到算出一笔错误金额、并且已经发给客户之后才发现。
所以这里的重点同样是"挡得住什么"。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.domain import DomainError, load_domain

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DOMAINS = sorted((ROOT / "domain").glob("**/domain.yaml"))


def _base_domain(**overrides):
    data = {
        "domain": "test-domain",
        "version": "0.1.0",
        "note": "测试用",
        "facts": [
            {"name": "amount", "type": "number", "minimum": 0, "maximum": 100},
        ],
        "rules": [
            {
                "id": "T-1",
                "when": "amount > 10",
                "verdict": "refundable",
                "cite": "测试条款",
                "priority": 1,
                "fee": {"form": "fixed", "amount": 5},
            }
        ],
        "escalate": [{"when": "missing_any_fact == true", "reason": "缺信息"}],
    }
    data.update(overrides)
    return data


def _write(tmp_path: Path, data) -> Path:
    path = tmp_path / "domain.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# 两个真实示例域
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", SAMPLE_DOMAINS, ids=lambda p: p.parent.name)
def test_sample_domain_loads(path: Path):
    domain = load_domain(path)

    assert domain.name
    assert domain.version
    assert domain.facts, "必须有事实字段"
    assert domain.rules, "必须有规则"
    assert domain.escalations, "必须有转人工条件"

    for rule in domain.rules:
        assert rule.cite.strip(), f"{rule.id} 的 cite 不能为空"


def test_airline_domain_structure():
    domain = load_domain(ROOT / "domain" / "airline-fare-sample" / "domain.yaml")

    assert len(domain.rules) >= 13
    assert "fee_amount" in domain.allowed_expression_names
    assert "order_amount" in domain.facts

    # 优先级必须能区分出高低：存在一条比通用档位更高的规则
    priorities = {rule.priority for rule in domain.rules}
    assert len(priorities) >= 3


def test_university_domain_has_no_money():
    """副场景证明引擎不依赖"必须有金额"这个假设。"""
    domain = load_domain(ROOT / "domain" / "university-credit-sample" / "domain.yaml")

    assert all(rule.fee is None for rule in domain.rules)
    assert all(fact.type != "number" or fact.minimum is not None for fact in domain.facts.values())


# --------------------------------------------------------------------------- #
# 必须挡住的配置错误
# --------------------------------------------------------------------------- #


def test_duplicate_rule_id_is_rejected(tmp_path):
    data = _base_domain()
    data["rules"] = data["rules"] + [dict(data["rules"][0])]
    with pytest.raises(DomainError, match="id 重复"):
        load_domain(_write(tmp_path, data))


def test_unknown_verdict_is_rejected(tmp_path):
    data = _base_domain()
    data["rules"][0]["verdict"] = "maybe"
    with pytest.raises(DomainError, match="判定值"):
        load_domain(_write(tmp_path, data))


def test_empty_cite_is_rejected(tmp_path):
    """没有依据的判定视为缺陷——这条是硬性的。"""
    data = _base_domain()
    data["rules"][0]["cite"] = "   "
    with pytest.raises(DomainError, match="cite"):
        load_domain(_write(tmp_path, data))


def test_typo_in_field_name_is_caught_at_load_time(tmp_path):
    """把 amount 拼成 amout，加载就必须失败——这正是最容易被漏掉的一类 bug。"""
    data = _base_domain()
    data["rules"][0]["when"] = "amout > 10"
    with pytest.raises(DomainError, match="未声明的字段"):
        load_domain(_write(tmp_path, data))


def test_number_fact_requires_range(tmp_path):
    data = _base_domain()
    data["facts"][0].pop("minimum")
    with pytest.raises(DomainError, match="minimum"):
        load_domain(_write(tmp_path, data))


def test_boundary_outside_range_is_rejected(tmp_path):
    data = _base_domain()
    data["facts"][0]["boundaries"] = [500]
    with pytest.raises(DomainError, match="超出范围"):
        load_domain(_write(tmp_path, data))


def test_enum_requires_values(tmp_path):
    data = _base_domain()
    data["facts"] = [{"name": "kind", "type": "enum"}]
    data["rules"][0]["when"] = 'kind == "a"'
    with pytest.raises(DomainError, match="values"):
        load_domain(_write(tmp_path, data))


def test_rate_of_amount_requires_rate(tmp_path):
    data = _base_domain()
    data["rules"][0]["fee"] = {"form": "rate_of_amount"}
    with pytest.raises(DomainError, match="rate"):
        load_domain(_write(tmp_path, data))


def test_rate_of_amount_base_fact_must_exist(tmp_path):
    data = _base_domain()
    data["rules"][0]["fee"] = {"form": "rate_of_amount", "rate": 0.1, "base_fact": "nope"}
    with pytest.raises(DomainError, match="base_fact"):
        load_domain(_write(tmp_path, data))


def test_empty_escalate_is_rejected(tmp_path):
    data = _base_domain(escalate=[])
    with pytest.raises(DomainError, match="escalate"):
        load_domain(_write(tmp_path, data))


def test_escalate_requires_reason(tmp_path):
    data = _base_domain(escalate=[{"when": "amount > 1"}])
    with pytest.raises(DomainError, match="reason"):
        load_domain(_write(tmp_path, data))


def test_missing_top_level_key_is_rejected(tmp_path):
    data = _base_domain()
    data.pop("note")
    with pytest.raises(DomainError, match="note"):
        load_domain(_write(tmp_path, data))


def test_nonexistent_file_is_rejected(tmp_path):
    with pytest.raises(DomainError, match="找不到"):
        load_domain(tmp_path / "nope.yaml")


def test_table_lookup_is_supported(tmp_path):
    """第三种费用形式也要能用——否则"规则只允许三种形式"这句话就是假的。"""
    data = _base_domain()
    data["facts"] = [
        {"name": "amount", "type": "number", "minimum": 0, "maximum": 100},
        {"name": "tier", "type": "enum", "values": ["gold", "silver"]},
    ]
    data["rules"][0]["when"] = 'tier == "gold"'
    data["rules"][0]["fee"] = {
        "form": "table_lookup",
        "key_fact": "tier",
        "table": {"gold": 0.3, "silver": 0.1},
    }
    domain = load_domain(_write(tmp_path, data))

    fee = domain.rules[0].fee
    assert fee is not None
    assert str(fee.table["gold"]) == "0.3"
