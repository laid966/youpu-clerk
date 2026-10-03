# 评测用例抽样（人读版）

> 这个文件是给人抽查用的。完整数据集在 `eval/dataset.jsonl`（JSON Lines，程序读）。
> 生成器会按固定 seed 产出完全相同的用例，所以它是可复现的。

共 1000 条，下面展示前 20 条。

## case-0001 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | economy |
| `discount_rate` | 0.8575 |
| `fare_type` | promotional |
| `hours_before_departure` | 1974.8872 |
| `is_noshow` | True |
| `is_through_ticket` | False |
| `order_amount` | 200.0 |
| `total_segments` | 4 |
| `used_segments` | 4 |

**期望结果**

- 最终结论：`not_refundable`
- 规则算出的结论：`not_refundable`
- 费用：`200.00`
- 命中并生效的规则：`R-005`
- 是否转人工：`False`

## case-0002 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | economy |
| `discount_rate` | 0.4391 |
| `fare_type` | standard |
| `hours_before_departure` | 1435.3893 |
| `is_noshow` | True |
| `is_through_ticket` | True |
| `order_amount` | 200.01 |
| `total_segments` | 1 |
| `used_segments` | 4 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`200.01`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 联程票已使用部分航段，折算规则需人工确认
  - 已使用航段数大于总航段数，数据自相矛盾，需人工核查

## case-0003 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | business |
| `discount_rate` | 0.3735 |
| `fare_type` | promotional |
| `hours_before_departure` | 311.4699 |
| `is_noshow` | True |
| `is_through_ticket` | False |
| `order_amount` | 999.99 |
| `total_segments` | 2 |
| `used_segments` | 2 |

**期望结果**

- 最终结论：`not_refundable`
- 规则算出的结论：`not_refundable`
- 费用：`999.99`
- 命中并生效的规则：`R-005`
- 是否转人工：`False`

## case-0004 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | business |
| `discount_rate` | 0.5067 |
| `fare_type` | group |
| `hours_before_departure` | 84.768 |
| `is_noshow` | True |
| `is_through_ticket` | True |
| `order_amount` | 1000.0 |
| `total_segments` | 3 |
| `used_segments` | 0 |

**期望结果**

- 最终结论：`not_refundable`
- 规则算出的结论：`not_refundable`
- 费用：`1000.00`
- 命中并生效的规则：`R-005`
- 是否转人工：`False`

## case-0005 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | premium |
| `discount_rate` | 0.7812 |
| `fare_type` | promotional |
| `hours_before_departure` | 991.6539 |
| `is_noshow` | False |
| `is_through_ticket` | False |
| `order_amount` | 1000.01 |
| `total_segments` | 3 |
| `used_segments` | 1 |

**期望结果**

- 最终结论：`not_refundable`
- 规则算出的结论：`not_refundable`
- 费用：`1000.01`
- 命中并生效的规则：`R-008`
- 是否转人工：`False`

## case-0006 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | premium |
| `discount_rate` | 0.2081 |
| `fare_type` | standard |
| `hours_before_departure` | 395.9609 |
| `is_noshow` | True |
| `is_through_ticket` | True |
| `order_amount` | 4999.99 |
| `total_segments` | 2 |
| `used_segments` | 4 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`4999.99`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 联程票已使用部分航段，折算规则需人工确认
  - 已使用航段数大于总航段数，数据自相矛盾，需人工核查

## case-0007 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | premium |
| `discount_rate` | 0.3032 |
| `fare_type` | standard |
| `hours_before_departure` | 1991.8923 |
| `is_noshow` | False |
| `is_through_ticket` | True |
| `order_amount` | 5000.0 |
| `total_segments` | 4 |
| `used_segments` | 0 |

**期望结果**

- 最终结论：`refundable`
- 规则算出的结论：`refundable`
- 费用：`500.00`
- 命中并生效的规则：`R-007`
- 是否转人工：`False`

## case-0008 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | business |
| `discount_rate` | 0.9428 |
| `fare_type` | group |
| `hours_before_departure` | 1607.6234 |
| `is_noshow` | False |
| `is_through_ticket` | False |
| `order_amount` | 5000.01 |
| `total_segments` | 1 |
| `used_segments` | 2 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`needs_review`
- 费用：`0.00`
- 命中并生效的规则：`R-009`
- 是否转人工：`True`
- 转人工原因：
  - 已使用航段数大于总航段数，数据自相矛盾，需人工核查

## case-0009 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | premium |
| `discount_rate` | 0.5484 |
| `fare_type` | standard |
| `hours_before_departure` | 1351.5754 |
| `is_noshow` | True |
| `is_through_ticket` | False |
| `order_amount` | 19999.99 |
| `total_segments` | 4 |
| `used_segments` | 1 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`19999.99`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核

## case-0010 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | economy |
| `discount_rate` | 0.5542 |
| `fare_type` | promotional |
| `hours_before_departure` | 36.5225 |
| `is_noshow` | True |
| `is_through_ticket` | True |
| `order_amount` | 20000.0 |
| `total_segments` | 1 |
| `used_segments` | 1 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`20000.00`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核
  - 联程票已使用部分航段，折算规则需人工确认

## case-0011 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | premium |
| `discount_rate` | 0.8916 |
| `fare_type` | promotional |
| `hours_before_departure` | 2142.3677 |
| `is_noshow` | False |
| `is_through_ticket` | True |
| `order_amount` | 20000.01 |
| `total_segments` | 2 |
| `used_segments` | 2 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`20000.01`
- 命中并生效的规则：`R-008`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核
  - 联程票已使用部分航段，折算规则需人工确认

## case-0012 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | economy |
| `discount_rate` | 0.9332 |
| `fare_type` | promotional |
| `hours_before_departure` | 616.1894 |
| `is_noshow` | True |
| `is_through_ticket` | False |
| `order_amount` | 49999.99 |
| `total_segments` | 4 |
| `used_segments` | 0 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`49999.99`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核

## case-0013 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | economy |
| `discount_rate` | 0.1267 |
| `fare_type` | standard |
| `hours_before_departure` | 1256.5061 |
| `is_noshow` | True |
| `is_through_ticket` | False |
| `order_amount` | 50000.0 |
| `total_segments` | 1 |
| `used_segments` | 0 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`50000.00`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核

## case-0014 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | economy |
| `discount_rate` | 0.7559 |
| `fare_type` | group |
| `hours_before_departure` | 1.0 |
| `is_noshow` | True |
| `is_through_ticket` | True |
| `order_amount` | 32589.0692 |
| `total_segments` | 4 |
| `used_segments` | 4 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`32589.07`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核
  - 联程票已使用部分航段，折算规则需人工确认

## case-0015 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | economy |
| `discount_rate` | 0.7185 |
| `fare_type` | promotional |
| `hours_before_departure` | 1.01 |
| `is_noshow` | True |
| `is_through_ticket` | False |
| `order_amount` | 22555.7294 |
| `total_segments` | 3 |
| `used_segments` | 4 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`22555.73`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核
  - 已使用航段数大于总航段数，数据自相矛盾，需人工核查

## case-0016 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | economy |
| `discount_rate` | 0.6643 |
| `fare_type` | group |
| `hours_before_departure` | 3.99 |
| `is_noshow` | False |
| `is_through_ticket` | False |
| `order_amount` | 36183.8774 |
| `total_segments` | 3 |
| `used_segments` | 3 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`needs_review`
- 费用：`0.00`
- 命中并生效的规则：`R-009`
- 是否转人工：`False`

## case-0017 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | business |
| `discount_rate` | 0.7196 |
| `fare_type` | standard |
| `hours_before_departure` | 4.0 |
| `is_noshow` | False |
| `is_through_ticket` | False |
| `order_amount` | 40784.2809 |
| `total_segments` | 1 |
| `used_segments` | 2 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`refundable`
- 费用：`20392.14`
- 命中并生效的规则：`R-013`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核
  - 已使用航段数大于总航段数，数据自相矛盾，需人工核查

## case-0018 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | business |
| `discount_rate` | 0.8966 |
| `fare_type` | group |
| `hours_before_departure` | 4.01 |
| `is_noshow` | False |
| `is_through_ticket` | False |
| `order_amount` | 45365.6315 |
| `total_segments` | 2 |
| `used_segments` | 3 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`needs_review`
- 费用：`0.00`
- 命中并生效的规则：`R-009`
- 是否转人工：`True`
- 转人工原因：
  - 已使用航段数大于总航段数，数据自相矛盾，需人工核查

## case-0019 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | business |
| `discount_rate` | 0.4932 |
| `fare_type` | promotional |
| `hours_before_departure` | 23.99 |
| `is_noshow` | True |
| `is_through_ticket` | True |
| `order_amount` | 18999.8838 |
| `total_segments` | 4 |
| `used_segments` | 0 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`18999.88`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核

## case-0020 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `cabin_class` | economy |
| `discount_rate` | 0.6437 |
| `fare_type` | promotional |
| `hours_before_departure` | 24.0 |
| `is_noshow` | True |
| `is_through_ticket` | True |
| `order_amount` | 31207.9541 |
| `total_segments` | 1 |
| `used_segments` | 0 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_refundable`
- 费用：`31207.95`
- 命中并生效的规则：`R-005`
- 是否转人工：`True`
- 转人工原因：
  - 退票手续费超出自动处理阈值（5000 元），需人工复核
