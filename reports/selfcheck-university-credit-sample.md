# 规则自检报告 · `university-credit-sample`

- 取样数量：**500**（固定 seed `20261003`，结果可复现）
- 结论：✅ 未发现错误级问题
- 规则覆盖：**99.0%**（495 / 500 个样本至少命中一条规则）

> 说明：本自检是**反例搜索**，不是逻辑证明。
> 措辞严格为「在 500 个样本中未发现」，不代表数学上不存在。

## 错误级问题

- 无

## 警告

- ⚠️ 在 500 个样本中有 5 个（1.0%）没有任何规则覆盖。本项目故意不写兜底规则，所以缺口是可见的、而不是被掩盖的；但比例过高说明规则集不完整。

## 规则命中与胜出次数

| 规则 | 命中次数 | 生效（胜出）次数 | 备注 |
|---|---|---|---|
| `U-001` | 4 | 4 |  |
| `U-002` | 338 | 338 |  |
| `U-003` | 306 | 91 |  |
| `U-004` | 315 | 39 |  |
| `U-005` | 240 | 16 |  |
| `U-006` | 249 | 7 |  |

## 最终结论分布

| 结论 | 次数 |
|---|---|
| `needs_review` | 378 |
| `not_eligible` | 120 |
| `eligible` | 2 |

## 转人工原因分布

| 原因 | 次数 |
|---|---|
| 部分课程时间表尚未公布，结论需标注"待复核" | 240 |
| 异地校区能否计入尚不明确，需人工确认 | 237 |
| 关键信息缺失（capstone_credits），不得猜测 | 9 |
| 关键信息缺失（core_credits），不得猜测 | 7 |
| 关键信息缺失（has_unpublished_schedule），不得猜测 | 6 |
| 关键信息缺失（has_timetable_conflict），不得猜测 | 5 |
| 没有任何规则覆盖该情形（规则缺口），不得编造结论 | 5 |
| 关键信息缺失（campus），不得猜测 | 4 |
| 关键信息缺失（total_credits），不得猜测 | 4 |
| 关键信息缺失（workshop_count），不得猜测 | 1 |

## 规则缺口举例（前 3 条）

1. campus=branch, capstone_credits=18.0, core_credits=60.0, has_timetable_conflict=False, has_unpublished_schedule=True, total_credits=80.0, workshop_count=3.0
2. capstone_credits=16.5114, core_credits=54.7388, has_timetable_conflict=False, has_unpublished_schedule=True, total_credits=79.9745, workshop_count=3
3. campus=branch, capstone_credits=13.0031, core_credits=59.1857, has_timetable_conflict=False, has_unpublished_schedule=False, total_credits=64.5385, workshop_count=3
