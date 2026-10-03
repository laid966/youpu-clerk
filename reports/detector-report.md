# 审计器评测报告（A3：确定性检查器）

> 检查器全部是确定性程序，**没有任何模型参与**。
> 标准答案来自缺陷注入器，固定 seed 可逐字节复现。

## 总览

| 指标 | 数值 |
|---|---|
| 已知缺陷总数 | 198 |
| 抓到 | **174** |
| **召回率** | **87.9%** |
| 检查器报出的条目总数 | 174 |
| 误报（报了但不是缺陷） | **0** |
| **精确率** | **100.0%** |
| 干净样本数 | 80 |
| **每份干净样本平均误报** | **0.000 条** |
| 有误报的干净样本数 | 0 |
| 其中「合法变体」样本 | 37（承担 0 条误报）|

## 按缺陷类型的召回

| 缺陷类型 | 抓到 / 总数 | 召回率 |
|---|---|---|
| `missed_critical` | 10 / 10 | 100.0% |
| `downgraded` | 20 / 20 | 100.0% |
| `wrong_sex_threshold` | 24 / 24 | 100.0% |
| `value_mismatch` | 24 / 24 | 100.0% |
| `unit_mismatch` | 24 / 24 | 100.0% |
| `fabricated_citation` | 24 / 24 | 100.0% |
| `internal_contradiction` | 24 / 24 | 100.0% |
| `safety_violation` | 24 / 24 | 100.0% |
| `safety_paraphrase` | 0 / 24 | 0.0% |

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
| D-0019 | `safety_paraphrase` | `tc` | `semantic_check` |
| D-0020 | `safety_paraphrase` | `ua` | `semantic_check` |
| D-0030 | `safety_paraphrase` | `ggt` | `semantic_check` |
| D-0040 | `safety_paraphrase` | `alt` | `semantic_check` |
| D-0048 | `safety_paraphrase` | `tc` | `semantic_check` |
| D-0058 | `safety_paraphrase` | `ua` | `semantic_check` |
| D-0067 | `safety_paraphrase` | `hgb` | `semantic_check` |
| D-0073 | `safety_paraphrase` | `ua` | `semantic_check` |
| D-0082 | `safety_paraphrase` | `fpg` | `semantic_check` |
| D-0086 | `safety_paraphrase` | `hgb` | `semantic_check` |
| D-0095 | `safety_paraphrase` | `ua` | `semantic_check` |
| D-0101 | `safety_paraphrase` | `ua` | `semantic_check` |
| D-0110 | `safety_paraphrase` | `ua` | `semantic_check` |
| D-0116 | `safety_paraphrase` | `fpg` | `semantic_check` |
| D-0128 | `safety_paraphrase` | `ua` | `semantic_check` |
| D-0138 | `safety_paraphrase` | `ua` | `semantic_check` |
| D-0140 | `safety_paraphrase` | `fpg` | `semantic_check` |
| D-0147 | `safety_paraphrase` | `ast` | `semantic_check` |
| D-0152 | `safety_paraphrase` | `fpg` | `semantic_check` |
| D-0167 | `safety_paraphrase` | `fpg` | `semantic_check` |
| D-0170 | `safety_paraphrase` | `ast` | `semantic_check` |
| D-0181 | `safety_paraphrase` | `hgb` | `semantic_check` |
| D-0190 | `safety_paraphrase` | `tc` | `semantic_check` |
| D-0197 | `safety_paraphrase` | `tc` | `semantic_check` |
