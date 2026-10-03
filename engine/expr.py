"""受限表达式求值：规则文件里的 `when` 条件只允许"字段比较 + 布尔组合"。

## 为什么不用 eval / exec

如果直接 `eval(rule.when)`，那么规则文件就变成了**任意代码执行入口**：
任何一个能改规则文件的人（或一个被污染的规则文件）都能读写你的磁盘、发网络请求。
本项目的核心主张是"规则是数据"，而**数据不允许有执行能力**——这是安全模型的地基。

所以这里自己走一遍 Python 的语法树（ast），只放行一小撮节点类型：

    允许：字段名、字面常量、比较（== != < <= > >= in not in）、and / or / not、列表字面量
    禁止：函数调用、属性访问、下标、赋值、lambda、推导式、f-string、算术运算

**连算术都禁止**是刻意的：条件的职责是"判断"，不是"计算"。
一旦允许 `a + b > c` 这种写法，金额逻辑就会悄悄从 engine/adjudicate.py 漏进规则文件里，
而金额计算必须集中在同一个地方、被同一批测试覆盖。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Mapping

__all__ = ["CompiledExpression", "ExpressionError", "compile_expression"]


class ExpressionError(ValueError):
    """表达式不合法（语法错误、用了不允许的语法、引用了未声明的字段）。"""


# 允许出现的语法树节点（必须精确列出，任何未列出的节点都会被拒绝）
_ALLOWED_NODE_TYPES: frozenset[type] = frozenset(
    {
        ast.Expression,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.Not,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.List,
        ast.Tuple,
    }
)

_COMPARISON_MAP = {
    ast.Eq: lambda left, right: left == right,
    ast.NotEq: lambda left, right: left != right,
    ast.Lt: lambda left, right: _ordered(left, right, lambda a, b: a < b),
    ast.LtE: lambda left, right: _ordered(left, right, lambda a, b: a <= b),
    ast.Gt: lambda left, right: _ordered(left, right, lambda a, b: a > b),
    ast.GtE: lambda left, right: _ordered(left, right, lambda a, b: a >= b),
    ast.In: lambda left, right: _membership(left, right, True),
    ast.NotIn: lambda left, right: _membership(left, right, False),
}

# YAML / JSON 的作者习惯写小写的 true / false / null。
# 但 Python 里这三个是 True / False / None，小写形式会被解析成"字段名"而报错。
# 规则作者不该为了迁就实现语言改自己的写法，所以在引擎这边认下来。
_LITERAL_NAMES: dict[str, object] = {
    "true": True,
    "false": False,
    "none": None,
    "null": None,
}


def _ordered(left, right, op) -> bool:
    """大小比较专用：任何一边是 None 一律判为 False，而不是抛异常。

    原因：`fee_amount` 这类字段在没有费用时是 None（比如学位审核域根本没有金额）。
    规则里写 `fee_amount > 5000` 却因为"没算钱"而崩掉，是设计问题，不是使用者的错。
    """
    if left is None or right is None:
        return False
    try:
        return bool(op(left, right))
    except TypeError:
        return False


def _membership(left, right, positive: bool) -> bool:
    """`in` / `not in` 的容错版本：右边不是容器时判为 False，而不是崩掉。"""
    try:
        result = left in right
    except TypeError:
        return False
    return bool(result) if positive else not bool(result)


@dataclass(frozen=True)
class CompiledExpression:
    """已通过校验的表达式。只有通过 `compile_expression` 才能构造出来。"""

    source: str
    used_names: frozenset[str]
    """表达式**实际引用**到的字段名。

    判定引擎靠它做依赖分析：如果一条规则需要的字段这次没提供，
    这条规则就"不可用"，必须跳过并转人工——而不是拿缺省值硬算一个金额出来。
    """

    tree: ast.Expression

    def evaluate(self, facts: Mapping[str, object]) -> bool:
        """求值。缺字段视为出错（缺字段应该在更早的地方被拦下并转人工）。"""
        result = _eval_node(self.tree.body, facts, self.source)
        if not isinstance(result, bool):
            raise ExpressionError(
                f"表达式 {self.source!r} 的结果不是布尔值，而是 {type(result).__name__}。"
                "条件的职责是判断真假，不是计算数值。"
            )
        return result


def compile_expression(source: str, allowed_names: set[str] | frozenset[str]) -> CompiledExpression:
    """解析并校验一个条件表达式。任何违规都在这里一次性报错。"""
    if not isinstance(source, str) or not source.strip():
        raise ExpressionError("条件表达式不能为空")

    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"条件表达式语法错误：{source!r}（{exc.msg}）") from exc

    for node in ast.walk(tree):
        node_type = type(node)

        # 字面常量：只允许基本类型
        if node_type is ast.Constant:
            if not isinstance(node.value, (bool, int, float, str, type(None))):
                raise ExpressionError(f"不允许的常量类型：{type(node.value).__name__}")
            continue

        # 字段名：必须在白名单里，且不允许下划线开头的名字（挡掉 __import__ 之类）
        if node_type is ast.Name:
            if node.id in _LITERAL_NAMES:
                continue  # true / false / null 等写法，当作字面量而不是字段
            if node.id.startswith("_"):
                raise ExpressionError(f"不允许以下划线开头的字段名：{node.id}")
            if node.id not in allowed_names:
                raise ExpressionError(
                    f"未声明的字段：{node.id}（可用字段：{', '.join(sorted(allowed_names))}）"
                )
            continue

        if node_type not in _ALLOWED_NODE_TYPES:
            raise ExpressionError(
                f"不允许的语法：{node_type.__name__}。"
                "规则条件只允许字段比较与 and / or / not 组合。"
            )

    # 只接受"一个表达式"这一种顶层形态
    if not isinstance(tree.body, (ast.BoolOp, ast.UnaryOp, ast.Compare)):
        raise ExpressionError(
            f"条件表达式的顶层必须是比较或布尔组合，而 {source!r} 不是（"
            f"实际是 {type(tree.body).__name__}）"
        )

    return CompiledExpression(
        source=source,
        used_names=frozenset(
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id not in _LITERAL_NAMES
        ),
        tree=tree,
    )


def _eval_node(node: ast.AST, facts: Mapping[str, object], source: str):
    node_type = type(node)

    if node_type is ast.Constant:
        return node.value

    if node_type is ast.Name:
        if node.id in _LITERAL_NAMES:
            return _LITERAL_NAMES[node.id]
        if node.id not in facts:
            raise ExpressionError(f"表达式 {source!r} 需要的字段 {node.id!r} 没有提供")
        return facts[node.id]

    if node_type in (ast.List, ast.Tuple):
        return [_eval_node(item, facts, source) for item in node.elts]

    if node_type is ast.UnaryOp:
        # 校验阶段已经保证了只可能是 Not
        return not _eval_node(node.operand, facts, source)

    if node_type is ast.BoolOp:
        if isinstance(node.op, ast.And):
            # 短路求值：左边为假就不再算右边
            for value_node in node.values:
                if not _eval_node(value_node, facts, source):
                    return False
            return True
        for value_node in node.values:
            if _eval_node(value_node, facts, source):
                return True
        return False

    if node_type is ast.Compare:
        left = _eval_node(node.left, facts, source)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, facts, source)
            handler = _COMPARISON_MAP.get(type(op))
            if handler is None:  # pragma: no cover — 校验阶段已拦下
                raise ExpressionError(f"不支持的比较运算符：{type(op).__name__}")
            if not handler(left, right):
                return False
            left = right
        return True

    raise ExpressionError(f"求值时遇到不允许的节点：{node_type.__name__}")  # pragma: no cover
