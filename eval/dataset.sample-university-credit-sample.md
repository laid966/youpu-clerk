# 评测用例抽样（人读版）

> 这个文件是给人抽查用的。完整数据集在 `eval/dataset.jsonl`（JSON Lines，程序读）。
> 生成器会按固定 seed 产出完全相同的用例，所以它是可复现的。

共 1000 条，下面展示前 20 条。

## case-0001 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 6.0991 |
| `core_credits` | 55.3056 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | True |
| `total_credits` | 47.99 |
| `workshop_count` | 1 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认
  - 部分课程时间表尚未公布，结论需标注"待复核"

## case-0002 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 0.9158 |
| `core_credits` | 30.9661 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | True |
| `total_credits` | 48.0 |
| `workshop_count` | 3 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认
  - 部分课程时间表尚未公布，结论需标注"待复核"

## case-0003 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | main |
| `capstone_credits` | 12.1469 |
| `core_credits` | 30.6981 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | False |
| `total_credits` | 48.01 |
| `workshop_count` | 3 |

**期望结果**

- 最终结论：`not_eligible`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`False`

## case-0004 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 4.5363 |
| `core_credits` | 19.9711 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | False |
| `total_credits` | 53.99 |
| `workshop_count` | 0 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认

## case-0005 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 12.2495 |
| `core_credits` | 11.4044 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | False |
| `total_credits` | 54.0 |
| `workshop_count` | 2 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认

## case-0006 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 5.6419 |
| `core_credits` | 7.5287 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | False |
| `total_credits` | 54.01 |
| `workshop_count` | 1 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认

## case-0007 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | main |
| `capstone_credits` | 9.3331 |
| `core_credits` | 59.063 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | False |
| `total_credits` | 59.99 |
| `workshop_count` | 0 |

**期望结果**

- 最终结论：`not_eligible`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`False`

## case-0008 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | main |
| `capstone_credits` | 13.6723 |
| `core_credits` | 58.2078 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | False |
| `total_credits` | 60.0 |
| `workshop_count` | 1 |

**期望结果**

- 最终结论：`not_eligible`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-005`
- 是否转人工：`False`

## case-0009 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 14.3438 |
| `core_credits` | 44.7908 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | False |
| `total_credits` | 60.01 |
| `workshop_count` | 1 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-005`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认

## case-0010 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | main |
| `capstone_credits` | 17.4931 |
| `core_credits` | 10.312 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | True |
| `total_credits` | 65.99 |
| `workshop_count` | 0 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-003`
- 是否转人工：`True`
- 转人工原因：
  - 部分课程时间表尚未公布，结论需标注"待复核"

## case-0011 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | main |
| `capstone_credits` | 7.9986 |
| `core_credits` | 11.049 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | True |
| `total_credits` | 66.0 |
| `workshop_count` | 3 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-003`
- 是否转人工：`True`
- 转人工原因：
  - 部分课程时间表尚未公布，结论需标注"待复核"

## case-0012 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | main |
| `capstone_credits` | 17.7533 |
| `core_credits` | 32.067 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | False |
| `total_credits` | 66.01 |
| `workshop_count` | 1 |

**期望结果**

- 最终结论：`not_eligible`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-003`
- 是否转人工：`False`

## case-0013 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 11.9101 |
| `core_credits` | 52.7721 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | True |
| `total_credits` | 71.99 |
| `workshop_count` | 2 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-004`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认
  - 部分课程时间表尚未公布，结论需标注"待复核"

## case-0014 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 5.129 |
| `core_credits` | 11.0692 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | True |
| `total_credits` | 72.0 |
| `workshop_count` | 1 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-003`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认
  - 部分课程时间表尚未公布，结论需标注"待复核"

## case-0015 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | main |
| `capstone_credits` | 0.4255 |
| `core_credits` | 56.1261 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | True |
| `total_credits` | 72.01 |
| `workshop_count` | 1 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-004`
- 是否转人工：`True`
- 转人工原因：
  - 部分课程时间表尚未公布，结论需标注"待复核"

## case-0016 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 4.133 |
| `core_credits` | 23.99 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | True |
| `total_credits` | 16.9178 |
| `workshop_count` | 0 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认
  - 部分课程时间表尚未公布，结论需标注"待复核"

## case-0017 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 0.1199 |
| `core_credits` | 24.0 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | False |
| `total_credits` | 78.3121 |
| `workshop_count` | 3 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-003`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认

## case-0018 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | main |
| `capstone_credits` | 8.914 |
| `core_credits` | 24.01 |
| `has_timetable_conflict` | True |
| `has_unpublished_schedule` | False |
| `total_credits` | 39.9364 |
| `workshop_count` | 2 |

**期望结果**

- 最终结论：`not_eligible`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`False`

## case-0019 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | branch |
| `capstone_credits` | 12.1696 |
| `core_credits` | 29.99 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | True |
| `total_credits` | 50.1568 |
| `workshop_count` | 3 |

**期望结果**

- 最终结论：`needs_review`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-002`
- 是否转人工：`True`
- 转人工原因：
  - 异地校区能否计入尚不明确，需人工确认
  - 部分课程时间表尚未公布，结论需标注"待复核"

## case-0020 · 模板 `threshold_sweep`

**输入事实**

| 字段 | 取值 |
|---|---|
| `campus` | main |
| `capstone_credits` | 7.5453 |
| `core_credits` | 30.0 |
| `has_timetable_conflict` | False |
| `has_unpublished_schedule` | False |
| `total_credits` | 79.7178 |
| `workshop_count` | 2 |

**期望结果**

- 最终结论：`not_eligible`
- 规则算出的结论：`not_eligible`
- 费用：`None`
- 命中并生效的规则：`U-003`
- 是否转人工：`False`
