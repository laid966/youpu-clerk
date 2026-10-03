# domain/ · 判定域配置

这里放**虚构的判定域**。一个"域"= 一套规则 + 需要的事实字段 + 判定输出。

**核心设计**：规则是**数据**，不是代码。所以
- 换一个域 = 换一个文件，引擎一行不改（这就是"可迁移"的证据）；
- 规则可以版本化、可审计、可 diff；
- 程序读规则、算判定，模型完全不参与计算。

> ⚠️ 本目录下所有规则、字段、示例**均为演示用虚构内容**，与任何真实机构、真实业务规则无关，不构成任何业务依据。请勿放入真实机构的数据、名称或内部条款。

---

## 目录

| 目录 | 用途 |
|---|---|
| `airline-fare-sample/` | 主场景：虚构的退改签费用与资格判定 |
| `university-credit-sample/` | 副场景：虚构的学分与毕业资格审核（证明换域即可复用） |

---

## 文件格式（M1 阶段会最终确定，先按这个写）

```yaml
domain: <域名>
version: 0.1.0
note: 纯虚构，仅用于演示。

# 1) 判定需要哪些事实。缺任何一项 → 不允许猜，直接标记转人工。
facts:
  - name: order_amount      # 字段名
    type: number            # number | enum | bool | date_offset_hours
    unit: CNY               # 可选
  - name: cabin_class
    type: enum
    values: [economy, premium, business]

# 2) 规则：条件 → 判定 + 费用。条件用受限表达式，不用自由代码。
rules:
  - id: R-001
    when: 'cabin_class == "economy" and hours_before_departure >= 168'
    verdict: refundable                      # refundable | not_refundable | needs_review
    fee:
      form: rate_of_amount                   # fixed | rate_of_amount | table_lookup
      rate: 0.05
    cite: '示例票规 第 3.1 条'                 # 依据，必须能指向原文
    priority: 10                             # 多条命中时谁优先

# 3) 转人工条件：满足则强制人工复核，模型不得自行决定。
escalate:
  - when: 'fee_amount > 5000'
    reason: 金额超出自动处理阈值
  - when: 'missing_any_fact == true'
    reason: 关键信息缺失
```

### 写法约定

1. **条件不许写自由代码**：只允许字段比较、布尔运算、`and/or/not`。这是为了可审计——规则能被非程序员读懂和复核。
2. **每条规则必须写 `cite`**：最终答复里引用的依据就来自这里。没有依据的判定视为缺陷。
3. **命中多条时**：按 `priority` 决定优先级；若两条同优先级且结论冲突，规则自检应当报错（M1 实现）。
4. **算不出来就说算不出来**：规则没覆盖、或事实缺失，一律 `needs_review`，**禁止沉默猜测**。这条是本项目的核心原则之一。
5. **费用只允许三种形式**：固定值、按比例、查表。不允许任意公式——避免引入不可审计的计算。
