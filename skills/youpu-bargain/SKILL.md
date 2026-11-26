---
name: youpu-bargain
description: 当用户想要获取二手商品议价的授权决策（接受/还价到精确金额/守价/转人工，附规则依据与让步台账）时，你应该调用此技能。买家通过本 Skill 向卖家服务端发起请求，完成支付后获取相关结果。
---

## 技能概述

本 Skill 提供**二手议价授权决策 API**：输入挂牌价与买家出价，返回授权引擎算出的决策
（accept / counter / firm / human）、精确到分的金额、逐条规则依据——钱是程序算的，话是 AI 说的。
该服务是基于 A2M 智能收协议（HTTP 402）的付费资源，按次计费 ¥0.01/次。
买家（消费者 Agent）通过本 Skill 向卖家服务端发起资源请求，服务端将返回 402 Payment-Needed 响应报文，
买家需将该报文传递给支付宝的 alipay-pay-for-402-service 技能以完成付款。

## 工作流程

有谱掌柜的议价授权引擎：确定性规则域（restricted-expression YAML）计算决策与金额，
LLM 只负责按买家语言起草话术，护栏词表拦截站外导流/绝对化承诺，全过程 append-only 台账留痕。
当用户向你请求该服务时，按以下步骤执行：

### 第一步：请求资源

向以下 URL 发起请求（JSON 体：asking_price 挂牌价、buyer_offer 买家出价、可选 floor_price 底价与 concessions_used 已让步次数）：

```
curl -v https://zcc.tail408b90.ts.net/api/agent/bargain -X POST -H "Content-Type: application/json" -d "{\"asking_price\":\"399.00\",\"buyer_offer\":\"300.00\"}"
```

### 第二步：处理 402 响应

你将收到一个**状态码为 402 的响应报文，其中包含 `Payment-Needed` 响应头**。此时你需要将**整个 402 响应报文**传递给支付宝的 **alipay-pay-for-402-service** 技能，引导用户完成付款。

### 第三步：携带凭证重试

付款完成后，把支付宝返回的 Payment-Proof 放入请求头 `Payment-Proof`，重发第一步的请求：
验证通过后服务端返回 200 与决策 JSON（kind/price/citations/trace）。
同一凭证只能用一次——重放会收到 402 PROOF_REUSED。

### 后续

完全转移到 alipay-pay-for-402-service 技能的工作流。

## 异常情况处理

- **用户拒绝付款**：尊重用户选择，告知用户该内容为付费资源，如需获取请完成支付。
- **请求返回非 402 状态码**：如返回 200，直接展示内容；如返回 4xx/5xx 错误，告知用户服务暂时不可用，建议稍后重试。
- **零凭证体验**：服务端以 `MACHINE_PAY_DEMO=1` 启动时，可用仓库内 `tools/a42_demo_client.py` 走完整协议时序（占位凭证，不过真钱）。
- 其余异常情况将由 alipay-pay-for-402-service 技能处理。
