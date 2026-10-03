"""`engine/expr.py` 的测试：受限表达式求值器。

这一层的价值全在"**拒绝**"上——它必须挡住任何试图在规则文件里执行代码的写法。
所以这里测试的重点不是"能算什么"，而是"挡得住什么"。
"""

from __future__ import annotations

import pytest

from engine.expr import ExpressionError, compile_expression

ALLOWED = frozenset(
    {"hours_before_departure", "cabin_class", "is_noshow", "fee_amount", "missing_any_fact"}
)


def compile_ok(source: str):
    return compile_expression(source, ALLOWED)


# --------------------------------------------------------------------------- #
# 正常用法
# --------------------------------------------------------------------------- #


def test_simple_comparison():
    expr = compile_ok("hours_before_departure >= 168")
    assert expr.evaluate({"hours_before_departure": 200}) is True
    assert expr.evaluate({"hours_before_departure": 100}) is False


def test_boundary_is_inclusive():
    expr = compile_ok("hours_before_departure >= 168")
    assert expr.evaluate({"hours_before_departure": 168}) is True


def test_and_or_not():
    expr = compile_ok('cabin_class == "business" and not is_noshow')
    assert expr.evaluate({"cabin_class": "business", "is_noshow": False}) is True
    assert expr.evaluate({"cabin_class": "business", "is_noshow": True}) is False
    assert expr.evaluate({"cabin_class": "economy", "is_noshow": False}) is False


def test_chained_comparison():
    expr = compile_ok("hours_before_departure >= 48 and hours_before_departure < 168")
    assert expr.evaluate({"hours_before_departure": 72}) is True
    assert expr.evaluate({"hours_before_departure": 168}) is False


def test_membership():
    expr = compile_ok('cabin_class in ["business", "premium"]')
    assert expr.evaluate({"cabin_class": "business"}) is True
    assert expr.evaluate({"cabin_class": "economy"}) is False


def test_none_on_either_side_is_false_not_crash():
    """没有费用的域里 fee_amount 是 None，规则不该因此崩掉。"""
    expr = compile_ok("fee_amount > 5000")
    assert expr.evaluate({"fee_amount": None}) is False
    assert expr.evaluate({"fee_amount": 9000}) is True


def test_lowercase_literal_names_are_accepted():
    """YAML 作者会写小写 true / false，引擎必须认，否则等于强迫对方改写法。

    这个用例是真实 bug 回归：最初的规则文件里写了 `missing_any_fact == true`，
    结果 `true` 被当成未声明的字段，加载直接失败。
    """
    assert compile_ok("missing_any_fact == true").evaluate({"missing_any_fact": True}) is True
    assert compile_ok("missing_any_fact == false").evaluate({"missing_any_fact": True}) is False
    assert compile_ok("is_noshow == true").evaluate({"is_noshow": True}) is True


# --------------------------------------------------------------------------- #
# 必须挡住的写法
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source",
    [
        '__import__("os").system("echo pwned")',  # 函数调用
        "open('/etc/passwd')",  # 函数调用
        "cabin_class.__class__",  # 属性访问
        "cabin_class[0]",  # 下标
        "len(cabin_class) > 0",  # 函数调用
        "hours_before_departure + 1 > 10",  # 算术运算
        "hours_before_departure * 2 > 10",  # 算术运算
        "lambda: True",  # lambda
        "[x for x in [1, 2]]",  # 推导式
        "f'{cabin_class}' == 'x'",  # f-string
        "hours_before_departure := 5",  # 海象运算符
    ],
)
def test_dangerous_or_unsupported_syntax_is_rejected(source):
    with pytest.raises(ExpressionError):
        compile_ok(source)


def test_unknown_field_is_rejected():
    with pytest.raises(ExpressionError, match="未声明的字段"):
        compile_ok("unknown_field > 1")


def test_underscore_prefixed_name_is_rejected():
    with pytest.raises(ExpressionError, match="下划线"):
        compile_ok("__builtins__ > 1")


def test_empty_expression_is_rejected():
    with pytest.raises(ExpressionError):
        compile_ok("   ")


def test_bare_field_is_rejected():
    """条件必须是一个判断，不能只是把字段名写上去。"""
    with pytest.raises(ExpressionError, match="顶层必须是比较或布尔组合"):
        compile_ok("hours_before_departure")


def test_syntax_error_is_reported_clearly():
    with pytest.raises(ExpressionError, match="语法错误"):
        compile_ok("hours_before_departure >=")


def test_missing_field_at_evaluation_time_raises():
    expr = compile_ok("hours_before_departure >= 168")
    with pytest.raises(ExpressionError, match="没有提供"):
        expr.evaluate({})
