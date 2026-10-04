# 审计器评测报告（A3：确定性检查器）

> 检查器全部是确定性程序，**没有任何模型参与**。
> 标准答案来自缺陷注入器，固定 seed 可逐字节复现。

## 总览

| 指标 | 数值 |
|---|---|
| 已知缺陷总数 | 99 |
| 抓到 | **87** |
| **召回率** | **87.9%** |
| 检查器报出的条目总数 | 87 |
| 误报（报了但不是缺陷） | **0** |
| **精确率** | **100.0%** |
| 干净样本数 | 40 |
| **每份干净样本平均误报** | **0.000 条** |
| 有误报的干净样本数 | 0 |
| 其中「合法变体」样本 | 13（承担 0 条误报）|

## 按缺陷类型的召回

| 缺陷类型 | 抓到 / 总数 | 召回率 |
|---|---|---|
| `missed_critical` | 5 / 5 | 100.0% |
| `downgraded` | 10 / 10 | 100.0% |
| `wrong_sex_threshold` | 12 / 12 | 100.0% |
| `value_mismatch` | 12 / 12 | 100.0% |
| `unit_mismatch` | 12 / 12 | 100.0% |
| `fabricated_citation` | 12 / 12 | 100.0% |
| `internal_contradiction` | 12 / 12 | 100.0% |
| `safety_violation` | 12 / 12 | 100.0% |
| `safety_paraphrase` | 0 / 12 | 0.0% |

## 误报分布（按检查器）

| 检查器 | 误报条数 |
|---|---|
| `oracle_differential` | 0 |
| `value_consistency` | 0 |
| `unit_consistency` | 0 |
| `citation_existence` | 0 |
| `advice_contract` | 0 |
| `safety_terms` | 0 |

## 漏掉的缺陷

| 编号 | 类型 | 指标 | 应由谁发现 |
|---|---|---|---|
| D-0005 | `safety_paraphrase` | `alt` | `semantic_check` |
| D-0017 | `safety_paraphrase` | `tc` | `semantic_check` |
| D-0029 | `safety_paraphrase` | `fpg` | `semantic_check` |
| D-0033 | `safety_paraphrase` | `hgb` | `semantic_check` |
| D-0042 | `safety_paraphrase` | `tc` | `semantic_check` |
| D-0047 | `safety_paraphrase` | `hgb` | `semantic_check` |
| D-0061 | `safety_paraphrase` | `crea` | `semantic_check` |
| D-0065 | `safety_paraphrase` | `crea` | `semantic_check` |
| D-0070 | `safety_paraphrase` | `hgb` | `semantic_check` |
| D-0082 | `safety_paraphrase` | `crea` | `semantic_check` |
| D-0088 | `safety_paraphrase` | `alt` | `semantic_check` |
| D-0097 | `safety_paraphrase` | `fpg` | `semantic_check` |
