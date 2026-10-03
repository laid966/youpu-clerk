# 审计 agent 端到端报告（A5）

- 策略：`范围=abnormal_only | 单份模型调用上限=8 | 接受模型结论=True | 证据必须可验证=True | 升级类目=diagnosis,treatment | 危急必升级=True`
- 提示词版本：`v1`
- 样本：5 份（其中干净样本 3 份）

## 总览

| 指标 | 数值 |
|---|---|
| 已知缺陷 | 3 |
| 抓到 | **3** |
| **召回率** | **100.0%** |
| 报出的条目 | 3 |
| 误报 | 0 |
| **精确率** | **100.0%** |
| 需人工复核的样本 | 0 |
| **模型调用总数** | **3** |

## 按缺陷类型的召回

| 缺陷类型 | 抓到 / 总数 |
|---|---|
| `missed_critical` | 0 / 0 |
| `downgraded` | 1 / 1 |
| `wrong_sex_threshold` | 1 / 1 |
| `value_mismatch` | 0 / 0 |
| `unit_mismatch` | 0 / 0 |
| `fabricated_citation` | 1 / 1 |
| `internal_contradiction` | 0 / 0 |
| `safety_violation` | 0 / 0 |
| `safety_paraphrase` | 0 / 0 |
