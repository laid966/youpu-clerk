"""插件：把「方向性内容」从 agent 本体里剥出来。

## 一句话分工

| | 谁提供 | 是什么 |
|---|---|---|
| **本体（core）** | 这个仓库的核心包（`engine` / `rag` / `audit` / `agent`） | **机制**：规则怎么算、缺陷怎么找、怎么调模型、怎么算指标 |
| **插件（plugin）** | `plugins/<名字>/` 一个目录 | **内容**：规则、字段清单、知识库、词表、提示词、模板 |

**本体不认识医学，也不认识信贷。** 它只认识"一份带判定的产物 + 一条可重算的规则"。

## 一个插件包含什么

```
plugins/credit-approval/
    plugin.yaml          ← 清单：声明这个场景用什么
    domain/*.yaml        ← 判定规则（引擎的输入）
    metrics.yaml         ← 字段清单：名称、单位、参考/合规区间、对应哪个判定域
    knowledge/*.yaml     ← 知识库（检索用）
    prompts.py           ← 该场景的提示词（可选）
```

加一个场景 = 加一个目录，**不改本体代码**。

## 为什么这样分（而不是按技术分层）

按技术分的项目（`models/` `utils/` `services/`）加第二场景时，改动会散落在所有目录里。
按"本体 vs 内容"分之后，场景差异全部落在一个目录里——
**这就是"能不能横向扩展"的分界线。**

## 现在有几个插件

`python -m plugin list`
"""

from plugin.spec import (
    DEFAULT_MEASUREMENT_TOLERANCE,
    PluginError,
    PluginSpec,
    discover_plugins,
    find_plugin,
    load_plugin,
    load_prompts,
)

__all__ = [
    "DEFAULT_MEASUREMENT_TOLERANCE",
    "PluginError",
    "PluginSpec",
    "discover_plugins",
    "find_plugin",
    "load_plugin",
    "load_prompts",
]
