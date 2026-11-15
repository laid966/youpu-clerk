# 32 · API 契约与数据模型（clerk 工作台）

> **本文件是并行开发的唯一协调物**。后端 / 演示 / 前端三条线都按这份契约写代码，
> 集成时以本文件为准。要改契约：先改这里，再通知所有人（Lead 负责）。
> 状态：v1（2026-11-12）。范围：MVP（粘贴模式 + 演示模式 + 扩展建议面板共用同一套 API）。

## 0. 全局约定

- **金额**：一律字符串、两位小数（`"95.00"`）。API、数据库、前端展示都不许出现 float。
  违反 = 缺陷（本仓库的老规矩：金额经过 float 就是事故的开始）。
- **ID**：uuid4 hex 字符串。**时间戳**：ISO-8601 UTC（`2026-11-12T14:00:00Z`）。
- **用户**：MVP 无账号体系。客户端生成 UUID 存 localStorage，每个请求带 `X-Clerk-User: <uuid>`。
  服务端按 token 隔离数据。付费权益挂在 token 上。
- **多语言**：
  - UI 文案 → 前端字典（zh / en），用户自由切换（见 docs/31）。
  - **回复话术语言 = 买家消息语言**（分类器判定），这是产品的跨境卖点：
    中文店主卖海外，AI 用英文接待；界面语言与回复语言**互不影响**。
  - API 错误：`code` 稳定不变（前端按 code 查字典），`message` 为中文兜底。
- **错误形状**：`{"error": {"code": "ITEM_NOT_FOUND", "message": "没有这个商品档案"}}`
  额度用尽返回 **HTTP 402** + `code: QUOTA_EXCEEDED`（向 Machine Pay 的 402 语义致敬，
  body 里带 `pricing` 字段供前端弹付费引导）。
- **LLM 依赖**：service 只认 `agent.judge.Judge` 协议。
  有 `DEEPSEEK_API_KEY` → DeepSeek+缓存；没有 → `clerk.templates.TemplateJudge`（确定性降级，
  演示模式**必须**在无 key 时完整可跑——评委现场没有我们的 key）。

## 1. 数据流与模块边界

```
POST /api/inquiry
   └► service.suggest(token, item_id, conversation_id, message, source)
        1) classify  ── LLM/模板 ──► {kind, language, offer}
        2) decide    ── 仅当 kind=="bargain" 且 offer 非空 ──► clerk.bargain.decide_bargain()
        3) draft     ── LLM/模板，用买家语言起草 ──► reply_text
        4) guardrail ── 禁语 + 数字白名单 ──► 命中则整段替换为安全模板
        5) record    ── messages + decisions 落库，usage_daily +1
   ◄── Suggestion（完整形状见 §3）
```

**模块所有权（写权限，越界=冲突）**：

| 文件 | 归属 |
|---|---|
| `clerk/bargain.py`、`clerk/config.py`、`clerk/__init__.py`、`domain/clerk-bargain/` | Lead（已冻结，要改找 Lead） |
| `clerk/db.py`、`clerk/service.py`、`clerk/prompts.py`、`clerk/guardrails.py`、`clerk/templates.py` | backend-clerk |
| `clerk/demo.py`、`clerk/demo_data/` | demo-content |
| `clerk/web/**` | frontend-web |
| `clerk/server.py`、`clerk/pay.py` | Lead（集成层） |

## 2. 数据库（SQLite，`data/clerk.db`；`clerk/db.py` 建表与访问）

```sql
CREATE TABLE IF NOT EXISTS users(
  token TEXT PRIMARY KEY, created_at TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'free',            -- free | paid30
  plan_expires_at TEXT);                        -- paid30 的到期时间，NULL=未付费
CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY, token TEXT NOT NULL, title TEXT NOT NULL,
  asking_price TEXT NOT NULL, floor_price TEXT NOT NULL,   -- 两位小数字符串
  platform TEXT NOT NULL DEFAULT 'xianyu',      -- xianyu | ebay | demo（为多平台预留）
  status TEXT NOT NULL DEFAULT 'active',        -- active | sold | archived
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY, token TEXT NOT NULL, item_id TEXT NOT NULL,
  buyer_alias TEXT NOT NULL DEFAULT '买家', language TEXT NOT NULL DEFAULT 'zh',
  status TEXT NOT NULL DEFAULT 'open',          -- open | closed | escalated
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
  direction TEXT NOT NULL,                      -- buyer | seller
  body TEXT NOT NULL, language TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(
  id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, item_id TEXT NOT NULL,
  message_id TEXT NOT NULL,                     -- 触发本决策的买家消息
  kind TEXT NOT NULL,                           -- accept|counter|firm|human|none（none=未走引擎）
  price TEXT, rule_id TEXT,
  citations_json TEXT NOT NULL DEFAULT '[]', reasons_json TEXT NOT NULL DEFAULT '[]',
  requires_human_review INTEGER NOT NULL DEFAULT 0,
  judgement_json TEXT,                          -- engine Judgement.to_dict() 全量
  classification_json TEXT NOT NULL,            -- {kind, language, offer}
  reply_text TEXT NOT NULL, guardrail_json TEXT NOT NULL DEFAULT '[]',
  adopted TEXT,                                 -- NULL|sent|edited|discarded|escalated
  final_text TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage_daily(
  token TEXT NOT NULL, day TEXT NOT NULL,       -- day: 2026-11-12（Asia/Shanghai 日历日）
  suggestions_used INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(token, day));
CREATE TABLE IF NOT EXISTS orders(              -- pay 骨架，G2 之后激活
  id TEXT PRIMARY KEY, token TEXT NOT NULL, out_trade_no TEXT UNIQUE NOT NULL,
  product_code TEXT NOT NULL,                   -- pass30 | pass30_early
  amount TEXT NOT NULL, status TEXT NOT NULL,   -- created|paid|refunded
  created_at TEXT NOT NULL, paid_at TEXT, notify_json TEXT);
```

**不变量（必须有测试盯着）**：
- I1 `concessions_used`（喂给引擎的）= 本会话本商品 `decisions` 里
  `kind=='counter' AND adopted IN ('sent','edited')` 的行数。**discarded 不算**（没真还出去）。
- I2 `guardrail_json` 非空时，`reply_text` 必须等于安全模板（命中的词不许出现在回复里）。
- I3 数字白名单：`reply_text` 里出现的价格状数字（`\d+(\.\d{1,2})?` 且带货币语境）只允许来自
  `{decision.price, item.asking_price}`。**floor_price 永远不许出现在回复里**（泄露底价=事故）。
  违规 → 整段替换安全模板并记 guardrail。
- I4 免费额度：`plan=='free'` 且当日 `suggestions_used >= FREE_DAILY_SUGGESTIONS` → 拒绝并 402。
- I5 每次 `/api/inquiry` 成功都恰好新增 1 行 messages(buyer) + 1 行 decisions；采纳时若卖家
  发送了回复，追加 1 行 messages(seller)。

## 3. 核心 API

### POST /api/inquiry —— 一切的主入口
```jsonc
// 请求
{ "item_id": "…", "conversation_id": "…|null",   // null=新会话
  "message": "150 出不出？", "source": "paste|extension|demo" }
// 响应 200（Suggestion 形状——demo 与真实链路**完全同形**，前端只认这一个形状）
{
  "suggestion_id": "…", "conversation_id": "…",
  "item": { "id": "…", "title": "…", "asking_price": "399.00", "floor_price": "339.15" },
  "classification": { "kind": "bargain", "language": "zh", "offer": "150.00" },
  "decision": {                                  // kind!="bargain" 或无出价时为 null
    "kind": "counter", "price": "379.05", "rule_id": "BARGAIN-COUNTER-T1",
    "citations": ["第 1 轮让步：按挂牌价 95% 还价（让步梯度第 1 档）"],
    "reasons": [], "requires_human_review": false
  },
  "reply_text": "亲，150 真的出不了…379 给您包邮带走～",
  "guardrail_hits": [],
  "trace": [                                     // "看得见的工作过程"——评委演示的核心
    {"step":"classify","ok":true,"ms":120,"note":"bargain / zh / offer=150.00"},
    {"step":"decide","ok":true,"ms":2,"note":"counter 379.05 · BARGAIN-COUNTER-T1"},
    {"step":"draft","ok":true,"ms":800,"note":"zh 话术生成"},
    {"step":"guardrail","ok":true,"ms":1,"note":"0 命中"}
  ],
  "quota": { "used_today": 3, "free_limit": 10, "plan": "free" }
}
```
`classification.kind ∈ bargain|opening|chitchat|aftersale|other`；
`opening`（"能刀吗"但没数字）不进引擎，回复引导买家出价。

### POST /api/inquiries/{id}/adopt
`{ "action": "sent|edited|discarded|escalated", "final_text": "…|null" }` →
`{ "ok": true, "concessions_used": 1 }`（I1 口径）。**采纳动作是台账闭环的关键**，前端必须提供四个按钮。

### 其余端点（形状从简，实现按 §2 表直接映射）
```
POST /api/items {title, asking_price, floor_price?}     # floor 缺省 → default_floor_price
GET  /api/items            PATCH /api/items/{id}
GET  /api/conversations    GET /api/conversations/{id}   # 含 messages + decisions
GET  /api/ledger?day=      # 台账：当日全部决策（含 rule_id/citations/adopted）
GET  /api/report/daily?day=  → {inquiries, bargains, counters, accepts, humans, concessions_total, adopt_rate}
GET  /api/health → {status, product, version, has_api_key, languages:["zh","en"]}
GET  /api/demo/bootstrap → {shop:{name,items:[…3件…]}, personas:[…5个…]}
POST /api/demo/step {persona_id, conversation_id?} → Suggestion + {persona_message, finished, step_index}
```

## 4. 分类与起草（backend-clerk 实现；prompts.py 是★作者文件★）

- **classify**（LLM，JSON 严格输出）：`{"kind": …, "language": "zh|en", "offer": "150.00"|null}`。
  提取不出数字时 offer=null，**绝不猜**。TemplateJudge 降级：正则提价
  （`(\d+(?:\.\d{1,2})?)\s*(?:块|元|¥|rmb|yuan|dollars?|\$)?` + 关键词 刀/砍/出/收/lowest/offer/take）+ 简易语种判定（ASCII 占比）。
- **draft**（LLM）：输入 = 决策 + 商品信息 + 买家原话 + 目标语言；硬约束写进 prompt：
  **只许引用 decision.price 或挂牌价这两个数字；不许承诺授权之外的事；不许泄露底价**；
  语气 = 友善的二手卖家（英文 persona 用 casual reseller 语气）。
- **安全模板**（templates.py，中英各一组，按 decision.kind 选）：护栏命中或 LLM 缺位时的兜底，
  保证"任何决策都有话可说"。

## 5. 支付（G2 闸门后激活，pay.py 归 Lead）

契约占位：`POST /api/pay/order {product_code}` → `{order_id, pay_url|qr}`；
回调 `POST /api/pay/notify`（验签+幂等，写 orders + 升级 users.plan）；
`GET /api/entitlements/me` → `{plan, expires_at, quota}`。
backend 侧只需保证：`users.plan` 从 free 变 paid30 后 I4 立即放行（有测试）。

## 6. 验收（集成时 Lead 按此清单跑）

1. 无 API key 环境：`pytest -q` 全绿；demo bootstrap→step×N 全链路可跑（TemplateJudge）。
2. I1-I5 各有专门测试；金额字符串正则测试扫全 API 响应。
3. 英文 persona（Emma）走完整议价：分类 language=en → 英文回复 → 台账含英文消息。
4. 同一输入（同 persona 同步数）重放，决策与价格逐字节一致（缓存/模板均确定性）。
5. 评委 60 秒路径：打开首页 → 点「试试演示」→ 选 Emma → 连点下一步 → 看到英文建议+trace+台账+战报卡。
