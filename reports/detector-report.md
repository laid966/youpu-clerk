# 审计器评测报告（A3：确定性检查器）

> 检查器全部是确定性程序，**没有任何模型参与**。
> 标准答案来自缺陷注入器，固定 seed 可逐字节复现。

## 总览

| 指标 | 数值 |
|---|---|
| 已知缺陷总数 | 30 |
| 抓到 | **26** |
| **召回率** | **86.7%** |
| 检查器报出的条目总数 | 26 |
| 误报（报了但不是缺陷） | **0** |
| **精确率** | **100.0%** |
| 干净样本数 | 12 |
| **每份干净样本平均误报** | **0.000 条** |
| 有误报的干净样本数 | 0 |
| 其中「合法变体」样本 | 2（承担 0 条误报）|

## 按缺陷类型的召回

| 缺陷类型 | 抓到 / 总数 | 召回率 |
|---|---|---|
| `missed_critical` | 2 / 2 | 100.0% |
| `downgraded` | 3 / 3 | 100.0% |
| `wrong_sex_threshold` | 4 / 4 | 100.0% |
| `value_mismatch` | 3 / 3 | 100.0% |
| `unit_mismatch` | 3 / 3 | 100.0% |
| `fabricated_citation` | 3 / 3 | 100.0% |
| `internal_contradiction` | 4 / 4 | 100.0% |
| `safety_violation` | 4 / 4 | 100.0% |
| `safety_paraphrase` | 0 / 4 | 0.0% |

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
| D-0006 | `safety_paraphrase` | `hgb` | `semantic_check` |
| D-0018 | `safety_paraphrase` | `hgb` | `semantic_check` |
| D-0022 | `safety_paraphrase` | `tc` | `semantic_check` |
| D-0029 | `safety_paraphrase` | `hgb` | `semantic_check` |
