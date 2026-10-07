# 审计 agent 端到端报告（A5）

- 策略：`范围=all | 单份模型调用上限=8 | 接受模型结论=True | 证据必须可验证=True | 升级类目=diagnosis,treatment,plan,conclusion | 危急必升级=True`
- 提示词版本：`v2`
- 样本：30 份（其中干净样本 14 份）

## 总览

| 指标 | 数值 |
|---|---|
| 已知缺陷 | 25 |
| 抓到 | **25** |
| **召回率** | **100.0%** |
| 报出的条目 | 25 |
| 误报 | 0 |
| **精确率** | **100.0%** |
| 需人工复核的样本 | 2 |
| **模型调用总数** | **237** |

## 语义层值不值

| | 召回率 |
|---|---|
| 只有确定性层 | 92.0% |
| 加上语义层 | **100.0%** |
| **增量** | **+8.0%**（代价：237 次模型调用）|

## 按缺陷类型的召回

| 缺陷类型 | 抓到 / 总数 |
|---|---|
| `missed_critical` | 1 / 1 |
| `downgraded` | 2 / 2 |
| `wrong_sex_threshold` | 5 / 5 |
| `value_mismatch` | 4 / 4 |
| `unit_mismatch` | 3 / 3 |
| `fabricated_citation` | 3 / 3 |
| `internal_contradiction` | 2 / 2 |
| `safety_violation` | 3 / 3 |
| `safety_paraphrase` | 2 / 2 |
