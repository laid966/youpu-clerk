# 规则自检报告 · `clerk-bargain`

- 取样数量：**1000**（固定 seed `20261003`，结果可复现）
- 结论：✅ 未发现错误级问题
- 规则覆盖：**99.4%**（994 / 1000 个样本至少命中一条规则）

> 说明：本自检是**反例搜索**，不是逻辑证明。
> 措辞严格为「在 1000 个样本中未发现」，不代表数学上不存在。

## 错误级问题

- 无

## 警告

- ⚠️ 在 1000 个样本中有 6 个（0.6%）没有任何规则覆盖。本项目故意不写兜底规则，所以缺口是可见的、而不是被掩盖的；但比例过高说明规则集不完整。

## 规则命中与胜出次数

| 规则 | 命中次数 | 生效（胜出）次数 | 备注 |
|---|---|---|---|
| `BARGAIN-HUMAN-LOWBALL` | 88 | 88 |  |
| `BARGAIN-ACCEPT` | 488 | 430 |  |
| `BARGAIN-FIRM-EXHAUSTED` | 849 | 423 |  |
| `BARGAIN-COUNTER-T1` | 89 | 24 |  |
| `BARGAIN-COUNTER-T2` | 26 | 14 |  |
| `BARGAIN-COUNTER-T3` | 19 | 15 |  |

## 最终结论分布

| 结论 | 次数 |
|---|---|
| `accept` | 401 |
| `firm` | 382 |
| `needs_review` | 119 |
| `human` | 88 |
| `counter` | 10 |

## 转人工原因分布

| 原因 | 次数 |
|---|---|
| 按让步梯度算出的还价低于店主底价，超出授权，转人工 | 41 |
| 关键信息缺失（floor_price），不得猜测 | 22 |
| 关键信息缺失（offer_floor_ratio），不得猜测 | 17 |
| 关键信息缺失（concessions_used），不得猜测 | 17 |
| 关键信息缺失（asking_price），不得猜测 | 13 |
| 关键信息缺失（buyer_offer），不得猜测 | 9 |
| 没有任何规则覆盖该情形（规则缺口），不得编造结论 | 6 |

## 规则缺口举例（前 3 条）

1. asking_price=143665.0029, buyer_offer=775225.0482, floor_price=959909.6797, offer_floor_ratio=76.4049
2. asking_price=451502.7597, buyer_offer=565325.1514, floor_price=919286.6954, offer_floor_ratio=96.7797
3. asking_price=449089.8815, buyer_offer=333891.6235, floor_price=509449.8232, offer_floor_ratio=29.1894
