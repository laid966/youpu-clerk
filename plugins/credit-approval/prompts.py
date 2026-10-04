"""★ 信贷插件自带的提示词 ★

**提示词也是插件件。** 约定和核心的 `agent/prompts.py` 完全一样：
暴露 `_REGISTRY`（版本名 → 文本）和 `CURRENT_VERSION`，文本里必须含 `{text}`。

为什么要按场景分开写：**"越界"在两个行业里是完全不同的东西。**
- 体检：不能替医生下诊断、不能给用药建议
- 信贷：不能承诺放款结果、不能暗示可以突破政策

用同一份提示词去管两个行业，必然两边都不准。
"""

from __future__ import annotations

__all__ = ["CURRENT_VERSION", "PROMPT_V1", "prompt_for"]

PROMPT_V1 = """你是一名信贷审批说明的合规审查员。判断下面这段给客户看的说明有没有**越界**。

越界有以下几类：
1. 承诺结果：向客户保证能放款、保证通过、暗示可以绕开政策。
2. 代替审批：直接替审批人下结论（"这个条件肯定能批"），而不是说明当前状态。
3. 指导规避：教客户如何规避材料要求、如何提高额度到不该有的水平。

以下**不算**越界，必须放过：
- 对利率、期限、还款方式的一般性解释
- 说明当前处于哪个环节、还缺哪些材料
- 提示以合同和最终审批结果为准
- 风险提示（逾期影响征信、提前还款可能有费用）

只在**明确**越界时判 true。拿不准就判 false。

待审查文本：
{text}

只输出一个 JSON，不要任何其他文字：
{{"violation": true 或 false, "category": "promise" 或 "override" 或 "evade" 或 "none", "evidence": "越界的那句原文，没有就给空字符串"}}
"""

_REGISTRY = {
    "v1": PROMPT_V1,
}

CURRENT_VERSION = "v1"


def prompt_for(version: str) -> str:
    if version not in _REGISTRY:
        raise KeyError(f"没有这个提示词版本：{version}（现有：{', '.join(sorted(_REGISTRY))}）")
    return _REGISTRY[version]
