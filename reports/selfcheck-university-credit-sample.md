# 规则自检报告 · `university-credit-sample`

- 取样数量：**3000**（固定 seed `20261003`，结果可复现）
- 结论：✅ 未发现错误级问题
- 规则覆盖：**99.1%**（2974 / 3000 个样本至少命中一条规则）

> 说明：本自检是**反例搜索**，不是逻辑证明。
> 措辞严格为「在 3000 个样本中未发现」，不代表数学上不存在。

## 错误级问题

- 无

## 警告

- ⚠️ 在 3000 个样本中有 26 个（0.9%）没有任何规则覆盖。本项目故意不写兜底规则，所以缺口是可见的、而不是被掩盖的；但比例过高说明规则集不完整。

## 规则命中与胜出次数

| 规则 | 命中次数 | 生效（胜出）次数 | 备注 |
|---|---|---|---|
| `U-001` | 13 | 13 |  |
| `U-002` | 2047 | 2047 |  |
| `U-003` | 1735 | 563 |  |
| `U-004` | 1864 | 222 |  |
| `U-005` | 1467 | 82 |  |
| `U-006` | 1485 | 47 |  |

## 最终结论分布

| 结论 | 次数 |
|---|---|
| `needs_review` | 2290 |
| `not_eligible` | 704 |
| `eligible` | 6 |

## 转人工原因分布

| 原因 | 次数 |
|---|---|
| 异地校区能否计入尚不明确，需人工确认 | 1493 |
| 部分课程时间表尚未公布，结论需标注"待复核" | 1474 |
| 关键信息缺失（has_timetable_conflict），不得猜测 | 42 |
| 关键信息缺失（workshop_count），不得猜测 | 40 |
| 关键信息缺失（core_credits），不得猜测 | 37 |
| 关键信息缺失（total_credits），不得猜测 | 35 |
| 关键信息缺失（campus），不得猜测 | 30 |
| 关键信息缺失（capstone_credits），不得猜测 | 28 |
| 没有任何规则覆盖该情形（规则缺口），不得编造结论 | 26 |
| 关键信息缺失（has_unpublished_schedule），不得猜测 | 24 |

## 规则缺口举例（前 3 条）

1. campus=main, core_credits=44.0635, has_timetable_conflict=False, has_unpublished_schedule=False, total_credits=72.5741, workshop_count=3
2. campus=branch, capstone_credits=13.4669, core_credits=37.104, has_timetable_conflict=False, has_unpublished_schedule=False, total_credits=60.0, workshop_count=2
3. campus=branch, capstone_credits=13.0031, core_credits=59.1857, has_timetable_conflict=False, has_unpublished_schedule=False, total_credits=64.5385, workshop_count=3
