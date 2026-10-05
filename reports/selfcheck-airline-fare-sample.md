# 规则自检报告 · `airline-fare-sample`

- 取样数量：**2000**（固定 seed `20261003`，结果可复现）
- 结论：✅ 未发现错误级问题
- 规则覆盖：**99.5%**（1990 / 2000 个样本至少命中一条规则）

> 说明：本自检是**反例搜索**，不是逻辑证明。
> 措辞严格为「在 2000 个样本中未发现」，不代表数学上不存在。

## 错误级问题

- 无

## 警告

- ⚠️ 在 2000 个样本中有 10 个（0.5%）没有任何规则覆盖。本项目故意不写兜底规则，所以缺口是可见的、而不是被掩盖的；但比例过高说明规则集不完整。

## 规则命中与胜出次数

| 规则 | 命中次数 | 生效（胜出）次数 | 备注 |
|---|---|---|---|
| `R-001` | 1633 | 7 |  |
| `R-002` | 119 | 5 |  |
| `R-003` | 41 | 4 |  |
| `R-004` | 178 | 14 |  |
| `R-011` | 1476 | 41 |  |
| `R-014` | 162 | 89 |  |
| `R-006` | 548 | 45 |  |
| `R-007` | 612 | 50 |  |
| `R-013` | 56 | 7 |  |
| `R-012` | 165 | 89 |  |
| `R-009` | 654 | 342 |  |
| `R-008` | 687 | 348 |  |
| `R-005` | 949 | 949 |  |

## 最终结论分布

| 结论 | 次数 |
|---|---|
| `needs_review` | 1763 |
| `not_refundable` | 131 |
| `refundable` | 106 |

## 转人工原因分布

| 原因 | 次数 |
|---|---|
| 退票手续费超出自动处理阈值（5000 元），需人工复核 | 1081 |
| 联程票已使用部分航段，折算规则需人工确认 | 755 |
| 已使用航段数大于总航段数，数据自相矛盾，需人工核查 | 580 |
| 关键信息缺失（is_noshow），不得猜测 | 23 |
| 关键信息缺失（is_through_ticket），不得猜测 | 22 |
| 关键信息缺失（used_segments），不得猜测 | 20 |
| 关键信息缺失（cabin_class），不得猜测 | 17 |
| 关键信息缺失（order_amount），不得猜测 | 16 |
| 关键信息缺失（total_segments），不得猜测 | 16 |
| 关键信息缺失（discount_rate），不得猜测 | 14 |
| 关键信息缺失（hours_before_departure），不得猜测 | 13 |
| 关键信息缺失（fare_type），不得猜测 | 13 |
| 没有任何规则覆盖该情形（规则缺口），不得编造结论 | 10 |

## 规则缺口举例（前 3 条）

1. cabin_class=business, discount_rate=0.753, fare_type=promotional, hours_before_departure=2151.4541, is_noshow=True, is_through_ticket=False, total_segments=2, used_segments=2
2. cabin_class=business, discount_rate=0.522, fare_type=promotional, hours_before_departure=940.493, is_noshow=False, is_through_ticket=True, total_segments=4, used_segments=2
3. cabin_class=business, discount_rate=0.773, fare_type=standard, is_noshow=False, is_through_ticket=False, order_amount=16989.5169, total_segments=3, used_segments=0
