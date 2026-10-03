"""rulecheck 的确定性计算层。

这一层**不包含任何模型调用**，是整个项目的正确性地基：
    engine/   ← 程序算。可以完整测试，永远不会"幻觉"
    agent/    ← 模型听与说。不参与计算

常用入口：
    from engine import load_domain, adjudicate
    python -m engine check --all
    python -m engine gen --all --count 1000
"""

from engine.adjudicate import AdjudicationError, Judgement, adjudicate
from engine.domain import Domain, DomainError, Fee, Rule, load_domain
from engine.expr import CompiledExpression, ExpressionError, compile_expression
from engine.sample_gen import GeneratedCase, generate_cases, write_dataset
from engine.selfcheck import SelfCheckReport, run_selfcheck

__all__ = [
    "AdjudicationError",
    "CompiledExpression",
    "Domain",
    "DomainError",
    "ExpressionError",
    "Fee",
    "GeneratedCase",
    "Judgement",
    "Rule",
    "SelfCheckReport",
    "adjudicate",
    "compile_expression",
    "generate_cases",
    "load_domain",
    "run_selfcheck",
    "write_dataset",
]
