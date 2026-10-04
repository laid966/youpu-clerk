"""★ 理赔插件自带的提示词 ★

与信贷插件的提示词**完全不同**：理赔场景的越界是"承诺赔付、诱导多报"，
信贷场景是"承诺放款、绕开政策"。**这就是提示词必须随场景走的原因。**
"""

from __future__ import annotations

__all__ = ["CURRENT_VERSION", "PROMPT_V1", "prompt_for"]

PROMPT_V1 = """你是一名理赔说明的合规审查员。判断下面这段给客户看的说明有没有**越界**。

越界有以下几类：
1. 承诺赔付：向客户保证一定赔、全额赔，而当前结论还没出来。
2. 诱导多报：暗示客户可以提高报损金额、把不属于保障范围的项目报进来。
3. 代替核赔：直接替核赔人下结论，而不是说明当前进度与所需材料。

以下**不算**越界，必须放过：
- 对条款、免赔额、赔付比例的一般性解释
- 说明当前进度、还缺哪些材料
- 提示以核赔结论为准
- 提醒如实告知、避免影响后续理赔

只在**明确**越界时判 true。拿不准就判 false。

待审查文本：
{text}

只输出一个 JSON，不要任何其他文字：
{{"violation": true 或 false, "category": "promise" 或 "induce" 或 "override" 或 "none", "evidence": "越界的那句原文，没有就给空字符串"}}
"""

_REGISTRY = {
    "v1": PROMPT_V1,
}

CURRENT_VERSION = "v1"


def prompt_for(version: str) -> str:
    if version not in _REGISTRY:
        raise KeyError(f"没有这个提示词版本：{version}（现有：{', '.join(sorted(_REGISTRY))}）")
    return _REGISTRY[version]
