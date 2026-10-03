# 规则自检报告 · `airline-fare-sample`

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
| `R-001` | 402 | 3 |  |
| `R-002` | 34 | 1 |  |
| `R-003` | 14 | 3 |  |
| `R-004` | 44 | 2 |  |
| `R-011` | 367 | 9 |  |
| `R-014` | 50 | 26 |  |
| `R-006` | 160 | 9 |  |
| `R-007` | 141 | 6 |  |
| `R-013` | 15 | 5 |  |
| `R-012` | 48 | 21 |  |
| `R-009` | 170 | 88 |  |
| `R-008` | 150 | 66 |  |
| `R-005` | 256 | 256 |  |

## 最终结论分布

| 结论 | 次数 |
|---|---|
| `needs_review` | 455 |
| `not_refundable` | 25 |
| `refundable` | 20 |

## 转人工原因分布

| 原因 | 次数 |
|---|---|
| 退票手续费超出自动处理阈值（5000 元），需人工复核 | 272 |
| 联程票已使用部分航段，折算规则需人工确认 | 177 |
| 已使用航段数大于总航段数，数据自相矛盾，需人工核查 | 152 |
| 关键信息缺失（is_through_ticket），不得猜测 | 7 |
| 关键信息缺失（discount_rate），不得猜测 | 5 |
| 没有任何规则覆盖该情形（规则缺口），不得编造结论 | 5 |
| 关键信息缺失（cabin_class），不得猜测 | 5 |
| 关键信息缺失（used_segments），不得猜测 | 5 |
| 关键信息缺失（fare_type），不得猜测 | 3 |
| 关键信息缺失（order_amount），不得猜测 | 3 |
| 关键信息缺失（hours_before_departure），不得猜测 | 3 |
| 关键信息缺失（total_segments），不得猜测 | 2 |
| 关键信息缺失（is_noshow），不得猜测 | 1 |

## 规则缺口举例（前 3 条）

1. cabin_class=premium, discount_rate=0.3342, fare_type=promotional, hours_before_departure=1038.7082, is_noshow=False, is_through_ticket=False, total_segments=4, used_segments=3
2. cabin_class=economy, discount_rate=0.1764, fare_type=promotional, hours_before_departure=171.1778, is_noshow=True, is_through_ticket=True, total_segments=1, used_segments=4
3. cabin_class=economy, discount_rate=0.7083, fare_type=standard, is_noshow=False, is_through_ticket=True, order_amount=25531.1154, total_segments=2, used_segments=4
