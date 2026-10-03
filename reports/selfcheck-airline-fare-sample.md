# 规则自检报告 · `airline-fare-sample`

- 取样数量：**3000**（固定 seed `20261003`，结果可复现）
- 结论：✅ 未发现错误级问题
- 规则覆盖：**99.6%**（2988 / 3000 个样本至少命中一条规则）

> 说明：本自检是**反例搜索**，不是逻辑证明。
> 措辞严格为「在 3000 个样本中未发现」，不代表数学上不存在。

## 错误级问题

- 无

## 警告

- ⚠️ 在 3000 个样本中有 12 个（0.4%）没有任何规则覆盖。本项目故意不写兜底规则，所以缺口是可见的、而不是被掩盖的；但比例过高说明规则集不完整。

## 规则命中与胜出次数

| 规则 | 命中次数 | 生效（胜出）次数 | 备注 |
|---|---|---|---|
| `R-001` | 2451 | 13 |  |
| `R-002` | 160 | 4 |  |
| `R-003` | 61 | 8 |  |
| `R-004` | 279 | 22 |  |
| `R-011` | 2216 | 49 |  |
| `R-014` | 249 | 131 |  |
| `R-006` | 846 | 81 |  |
| `R-007` | 865 | 63 |  |
| `R-013` | 105 | 12 |  |
| `R-012` | 261 | 128 |  |
| `R-009` | 991 | 512 |  |
| `R-008` | 1003 | 518 |  |
| `R-005` | 1447 | 1447 |  |

## 最终结论分布

| 结论 | 次数 |
|---|---|
| `needs_review` | 2669 |
| `not_refundable` | 178 |
| `refundable` | 153 |

## 转人工原因分布

| 原因 | 次数 |
|---|---|
| 退票手续费超出自动处理阈值（5000 元），需人工复核 | 1633 |
| 联程票已使用部分航段，折算规则需人工确认 | 1114 |
| 已使用航段数大于总航段数，数据自相矛盾，需人工核查 | 883 |
| 关键信息缺失（used_segments），不得猜测 | 33 |
| 关键信息缺失（is_noshow），不得猜测 | 28 |
| 关键信息缺失（discount_rate），不得猜测 | 28 |
| 关键信息缺失（hours_before_departure），不得猜测 | 27 |
| 关键信息缺失（cabin_class），不得猜测 | 25 |
| 关键信息缺失（total_segments），不得猜测 | 24 |
| 关键信息缺失（fare_type），不得猜测 | 24 |
| 关键信息缺失（is_through_ticket），不得猜测 | 23 |
| 关键信息缺失（order_amount），不得猜测 | 22 |
| 没有任何规则覆盖该情形（规则缺口），不得编造结论 | 12 |

## 规则缺口举例（前 3 条）

1. cabin_class=premium, discount_rate=0.3673, fare_type=standard, is_noshow=False, is_through_ticket=True, order_amount=5973.413, total_segments=3, used_segments=4
2. cabin_class=business, discount_rate=0.3736, fare_type=promotional, hours_before_departure=1269.5172, is_noshow=False, is_through_ticket=True, total_segments=3, used_segments=1
3. cabin_class=premium, discount_rate=0.3075, fare_type=standard, hours_before_departure=594.101, is_noshow=False, is_through_ticket=True, total_segments=3, used_segments=1
