// 由 `python -m clerk.capture_mock` 从真实后端抓取生成——勿手改，改了就与 API 漂移。
export default {
 "health": {
  "status": "ok",
  "product": "有谱掌柜",
  "tagline": "话是 AI 说的，钱是程序算的，每次让步都有据可查。",
  "version": "0.1.0",
  "languages": [
   "zh",
   "en"
  ],
  "judge_mode": "template",
  "has_api_key": true
 },
 "bootstrap": {
  "shop": {
   "name": "深夜杂货铺",
   "name_en": "Midnight Thrift Shop",
   "items": [
    {
     "key": "keyboard",
     "title": "机械键盘 87 键 茶轴",
     "title_en": "Mechanical Keyboard 87-Key",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    {
     "key": "gamecard",
     "title": "Switch 游戏卡带",
     "title_en": "Switch Game Card",
     "asking_price": "180.00",
     "floor_price": "153.00"
    },
    {
     "key": "band",
     "title": "小米手环 8",
     "title_en": "Xiaomi Smart Band 8",
     "asking_price": "129.00",
     "floor_price": "109.65"
    }
   ]
  },
  "personas": [
   {
    "id": "wang",
    "name_zh": "砍价党老王",
    "name_en": "Haggler Wang",
    "style_zh": "开口对半砍，被拒了就一点点往上磨",
    "style_en": "Opens at half price, then grinds upward",
    "language": "zh",
    "avatar_color": "#DC2626",
    "item_key": "keyboard",
    "steps": [
     {
      "message": "老板，对半砍，200出不出？",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "200.00"
      },
      "expected": {
       "kind": "human",
       "rule_id": "BARGAIN-HUMAN-LOWBALL",
       "used": 0
      },
      "note_zh": "开口对半砍：200 只有底价 339.15 的 59%，低于 80% 授权线 → 不还价，直接转人工",
      "note_en": "Opens at half price: 200 is only 59% of the 339.15 floor — below the 80% authorization line, so it escalates to human instead of auto-countering"
     },
     {
      "message": "哎呀贵了嘛，300行不？",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "300.00"
      },
      "expected": {
       "kind": "counter",
       "price": "379.05",
       "rule_id": "BARGAIN-COUNTER-T1",
       "used": 0
      },
      "note_zh": "300 过了授权线，进让步梯度第 1 档：还价 = 399 × 95% = 379.05——引擎算的，不是模型口算的",
      "note_en": "300 passes the authorization line, entering concession tier 1: counter = 399 × 95% = 379.05 — computed by the engine, not improvised by a model"
     },
     {
      "message": "320，我现在就拍！",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "320.00"
      },
      "expected": {
       "kind": "counter",
       "price": "367.08",
       "rule_id": "BARGAIN-COUNTER-T2",
       "used": 1
      },
      "note_zh": "上一次还价被卖家采纳 → 已让步 1 次；梯度第 2 档：399 × 92% = 367.08",
      "note_en": "Previous counter was adopted → 1 concession used; tier 2: 399 × 92% = 367.08"
     },
     {
      "message": "你太狠了，335行不行？",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "335.00"
      },
      "expected": {
       "kind": "counter",
       "price": "359.10",
       "rule_id": "BARGAIN-COUNTER-T3",
       "used": 2
      },
      "note_zh": "梯度第 3 档：399 × 90% = 359.10——授权梯度的最后一档",
      "note_en": "Tier 3: 399 × 90% = 359.10 — the last rung of the authorized ladder"
     },
     {
      "message": "338，到底出不出嘛？",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "338.00"
      },
      "expected": {
       "kind": "firm",
       "rule_id": "BARGAIN-FIRM-EXHAUSTED",
       "used": 3
      },
      "note_zh": "338 距底价 339.15 只差 1.15 元，但让步已达上限 3 次 → 守价不再降。制度比话术可靠：AI 不会被磨到破底",
      "note_en": "338 is just 1.15 below the floor, but the 3-concession cap is reached → price holds. The system beats persuasion: the AI can't be ground down past its authorization"
     },
     {
      "message": "行行行，就340吧！",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "340.00"
      },
      "expected": {
       "kind": "accept",
       "rule_id": "BARGAIN-ACCEPT",
       "used": 3
      },
      "note_zh": "340 ≥ 底价 339.15 → 授权内直接成交。让步用尽也不挡成交：ACCEPT 优先级永远高于 FIRM",
      "note_en": "340 ≥ floor 339.15 → deal closes within authorization. ACCEPT always outranks FIRM — a good offer is never blocked by the concession cap"
     }
    ]
   },
   {
    "id": "li",
    "name_zh": "沉默寡言 Li",
    "name_en": "Man-of-Few-Words Li",
    "style_zh": "消息极短，惜字如金",
    "style_en": "Terse, minimal messages",
    "language": "zh",
    "avatar_color": "#78716C",
    "item_key": "gamecard",
    "steps": [
     {
      "message": "还在吗",
      "language": "zh",
      "expected_classify": {
       "kind": "chitchat",
       "offer": null
      },
      "expected": {
       "kind": "none"
      },
      "note_zh": "打招呼不进引擎——没有数字可判。引擎只在「有钱要算」时介入，这是「钱由程序算」的另一半",
      "note_en": "Greetings never reach the engine — there is no number to adjudicate. The engine only steps in when money is on the table"
     },
     {
      "message": "140行不",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "140.00"
      },
      "expected": {
       "kind": "counter",
       "price": "171.00",
       "rule_id": "BARGAIN-COUNTER-T1",
       "used": 0
      },
      "note_zh": "卡带底价 = 180 × 85% = 153.00；140 < 153 但过了 80% 线 → 梯度第 1 档：180 × 95% = 171.00",
      "note_en": "Card floor = 180 × 85% = 153.00; 140 < floor but above the 80% line → tier 1: 180 × 95% = 171.00"
     },
     {
      "message": "150",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "150.00"
      },
      "expected": {
       "kind": "counter",
       "price": "165.60",
       "rule_id": "BARGAIN-COUNTER-T2",
       "used": 1
      },
      "note_zh": "两个字也是一条完整事实：150 < 153 → 梯度第 2 档：180 × 92% = 165.60",
      "note_en": "Two characters still make a complete fact: 150 < 153 → tier 2: 180 × 92% = 165.60"
     },
     {
      "message": "好吧那就155",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "155.00"
      },
      "expected": {
       "kind": "accept",
       "rule_id": "BARGAIN-ACCEPT",
       "used": 2
      },
      "note_zh": "155 ≥ 底价 153.00 → 成交。全程卖家只打了四个字，剩下的都是店员的事",
      "note_en": "155 ≥ floor 153.00 → deal. The seller typed four characters in total; the clerk did the rest"
     }
    ]
   },
   {
    "id": "zhang",
    "name_zh": "售后抱怨张姐",
    "name_en": "Upset Customer Zhang",
    "style_zh": "收货后来投诉，情绪逐步升级",
    "style_en": "Post-purchase complaints, escalating",
    "language": "zh",
    "avatar_color": "#D97706",
    "item_key": "band",
    "steps": [
     {
      "message": "收到的手环是坏的，充不上电",
      "language": "zh",
      "expected_classify": {
       "kind": "aftersale",
       "offer": null
      },
      "expected": {
       "kind": "none"
      },
      "note_zh": "售后消息不议价、不进引擎；模板话术先稳住并索要订单号与照片。LLM 在线时这一步会更有人味儿，但决策路径完全一致",
      "note_en": "After-sales messages never reach the engine; the template calms the buyer and asks for order number + photos. A live LLM would sound warmer, but the decision path is identical"
     },
     {
      "message": "我要退货，退款怎么弄？",
      "language": "zh",
      "expected_classify": {
       "kind": "aftersale",
       "offer": null
      },
      "expected": {
       "kind": "none"
      },
      "note_zh": "退货诉求：AI 只收集信息、不承诺退款——承诺超出授权的事会被护栏拦下",
      "note_en": "Return request: the AI collects facts but never promises refunds — unauthorized promises get blocked by the guardrail"
     },
     {
      "message": "我要投诉你们，赶紧给我退款",
      "language": "zh",
      "expected_classify": {
       "kind": "aftersale",
       "offer": null
      },
      "expected": {
       "kind": "none"
      },
      "note_zh": "情绪升级——真实工作台里店主可以一键「转人工」接管；AI 的职责是不火上浇油",
      "note_en": "Emotion escalates — in the real workbench the seller can take over with one click; the AI's job is to never pour oil on the fire"
     }
    ]
   },
   {
    "id": "emma",
    "name_zh": "海外买家 Emma",
    "name_en": "Emma (overseas buyer)",
    "style_zh": "英文询价，礼貌直接",
    "style_en": "English-speaking, polite and direct",
    "language": "en",
    "avatar_color": "#1677FF",
    "item_key": "keyboard",
    "steps": [
     {
      "message": "Hi, is this still available?",
      "language": "en",
      "expected_classify": {
       "kind": "chitchat",
       "offer": null
      },
      "expected": {
       "kind": "none"
      },
      "note_zh": "分类器识别 language=en——接下来所有回复自动用英文起草，店主不用会英语",
      "note_en": "The classifier detects language=en — every reply from here is drafted in English, so the seller doesn't have to speak it"
     },
     {
      "message": "Would you take 300 for it?",
      "language": "en",
      "expected_classify": {
       "kind": "bargain",
       "offer": "300.00"
      },
      "expected": {
       "kind": "counter",
       "price": "379.05",
       "rule_id": "BARGAIN-COUNTER-T1",
       "used": 0
      },
      "note_zh": "英文买家、中文店主、同一套授权引擎：钱由程序算，语言只是话术的皮。这就是跨境场景的全部秘密",
      "note_en": "English buyer, Chinese seller, one authorization engine: money is computed by the program — language is just the wrapper. That's the whole trick for cross-border selling"
     },
     {
      "message": "OK, would you take 340?",
      "language": "en",
      "expected_classify": {
       "kind": "bargain",
       "offer": "340.00"
      },
      "expected": {
       "kind": "accept",
       "rule_id": "BARGAIN-ACCEPT",
       "used": 1
      },
      "note_zh": "340 ≥ 底价 339.15 → 英文成交话术。（MVP 边界：数字按人民币口径，汇率换算是 roadmap）",
      "note_en": "340 ≥ floor 339.15 → deal, in English. (MVP boundary: amounts are CNY-denominated; FX conversion is on the roadmap)"
     }
    ]
   },
   {
    "id": "chen",
    "name_zh": "爽快人小陈",
    "name_en": "Quick-Trigger Chen",
    "style_zh": "开口就是能成交的价",
    "style_en": "Opens with a deal-closing price",
    "language": "zh",
    "avatar_color": "#16A34A",
    "item_key": "band",
    "steps": [
     {
      "message": "老板，120包邮的话我现在就拍",
      "language": "zh",
      "expected_classify": {
       "kind": "bargain",
       "offer": "120.00"
      },
      "expected": {
       "kind": "accept",
       "rule_id": "BARGAIN-ACCEPT",
       "used": 0
      },
      "note_zh": "120 ≥ 底价 109.65 → 直接成交，从收到消息到给出建议不到一秒。快，本身就是转化率",
      "note_en": "120 ≥ floor 109.65 → instant deal; suggestion ready in under a second. Speed itself is conversion"
     }
    ]
   }
  ]
 },
 "payProducts": {
  "tiers": [
   {
    "code": "pass30_early",
    "name_zh": "30 天通行证（早鸟）",
    "name_en": "30-Day Pass (Early Bird)",
    "price": "6.9"
   },
   {
    "code": "pass30",
    "name_zh": "30 天通行证",
    "name_en": "30-Day Pass",
    "price": "9.9"
   }
  ],
  "free": {
   "daily_suggestions": 10,
   "max_items": 1
  }
 },
 "scripts": {
  "wang": [
   {
    "suggestion_id": "2b4e8c953a414a48bdb8113481be0e57",
    "conversation_id": "de75da31d1cf4cb48c9f250e3bb8f372",
    "item": {
     "id": "5d1ad72b49774ca6a8349ebf48353a8c",
     "title": "机械键盘 87 键 茶轴",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "200.00"
    },
    "decision": {
     "kind": "human",
     "price": null,
     "rule_id": "BARGAIN-HUMAN-LOWBALL",
     "citations": [
      "买家出价低于底价的 80%，超出授权范围，转人工处理",
      "第 1 轮让步：按挂牌价 95% 还价（让步梯度第 1 档）"
     ],
     "reasons": [],
     "requires_human_review": true
    },
    "reply_text": "这个我需要确认一下，稍后回复您哈～",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=200.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 5,
      "note": "human · BARGAIN-HUMAN-LOWBALL · 已让步 0 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "老板，对半砍，200出不出？",
    "note_zh": "开口对半砍：200 只有底价 339.15 的 59%，低于 80% 授权线 → 不还价，直接转人工",
    "note_en": "Opens at half price: 200 is only 59% of the 339.15 floor — below the 80% authorization line, so it escalates to human instead of auto-countering",
    "expected": {
     "kind": "human",
     "rule_id": "BARGAIN-HUMAN-LOWBALL",
     "used": 0
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "200.00"
    },
    "step_index": 0,
    "total_steps": 6,
    "finished": false,
    "concessions_used": 0,
    "persona": {
     "id": "wang",
     "name_zh": "砍价党老王",
     "name_en": "Haggler Wang",
     "style_zh": "开口对半砍，被拒了就一点点往上磨",
     "style_en": "Opens at half price, then grinds upward",
     "language": "zh",
     "avatar_color": "#DC2626",
     "item_key": "keyboard"
    }
   },
   {
    "suggestion_id": "f9d75d2141bb45529088e27ba026e547",
    "conversation_id": "de75da31d1cf4cb48c9f250e3bb8f372",
    "item": {
     "id": "5d1ad72b49774ca6a8349ebf48353a8c",
     "title": "机械键盘 87 键 茶轴",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "300.00"
    },
    "decision": {
     "kind": "counter",
     "price": "379.05",
     "rule_id": "BARGAIN-COUNTER-T1",
     "citations": [
      "第 1 轮让步：按挂牌价 95% 还价（让步梯度第 1 档）"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "亲，这个价真出不了～379.05 已经是诚意价了，真心喜欢就带走吧！",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=300.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "counter 379.05 · BARGAIN-COUNTER-T1 · 已让步 0 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "哎呀贵了嘛，300行不？",
    "note_zh": "300 过了授权线，进让步梯度第 1 档：还价 = 399 × 95% = 379.05——引擎算的，不是模型口算的",
    "note_en": "300 passes the authorization line, entering concession tier 1: counter = 399 × 95% = 379.05 — computed by the engine, not improvised by a model",
    "expected": {
     "kind": "counter",
     "price": "379.05",
     "rule_id": "BARGAIN-COUNTER-T1",
     "used": 0
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "300.00"
    },
    "step_index": 1,
    "total_steps": 6,
    "finished": false,
    "concessions_used": 1,
    "persona": {
     "id": "wang",
     "name_zh": "砍价党老王",
     "name_en": "Haggler Wang",
     "style_zh": "开口对半砍，被拒了就一点点往上磨",
     "style_en": "Opens at half price, then grinds upward",
     "language": "zh",
     "avatar_color": "#DC2626",
     "item_key": "keyboard"
    }
   },
   {
    "suggestion_id": "10622b60c3e34383b6aaa12b562b5a75",
    "conversation_id": "de75da31d1cf4cb48c9f250e3bb8f372",
    "item": {
     "id": "5d1ad72b49774ca6a8349ebf48353a8c",
     "title": "机械键盘 87 键 茶轴",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "320.00"
    },
    "decision": {
     "kind": "counter",
     "price": "367.08",
     "rule_id": "BARGAIN-COUNTER-T2",
     "citations": [
      "第 2 轮让步：按挂牌价 92% 还价（让步梯度第 2 档）"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "亲，这个价真出不了～367.08 已经是诚意价了，真心喜欢就带走吧！",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=320.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "counter 367.08 · BARGAIN-COUNTER-T2 · 已让步 1 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "320，我现在就拍！",
    "note_zh": "上一次还价被卖家采纳 → 已让步 1 次；梯度第 2 档：399 × 92% = 367.08",
    "note_en": "Previous counter was adopted → 1 concession used; tier 2: 399 × 92% = 367.08",
    "expected": {
     "kind": "counter",
     "price": "367.08",
     "rule_id": "BARGAIN-COUNTER-T2",
     "used": 1
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "320.00"
    },
    "step_index": 2,
    "total_steps": 6,
    "finished": false,
    "concessions_used": 2,
    "persona": {
     "id": "wang",
     "name_zh": "砍价党老王",
     "name_en": "Haggler Wang",
     "style_zh": "开口对半砍，被拒了就一点点往上磨",
     "style_en": "Opens at half price, then grinds upward",
     "language": "zh",
     "avatar_color": "#DC2626",
     "item_key": "keyboard"
    }
   },
   {
    "suggestion_id": "1489d15c67214f81a8ff8db4179850b8",
    "conversation_id": "de75da31d1cf4cb48c9f250e3bb8f372",
    "item": {
     "id": "5d1ad72b49774ca6a8349ebf48353a8c",
     "title": "机械键盘 87 键 茶轴",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "335.00"
    },
    "decision": {
     "kind": "counter",
     "price": "359.10",
     "rule_id": "BARGAIN-COUNTER-T3",
     "citations": [
      "第 3 轮让步：按挂牌价 90% 还价（让步梯度第 3 档）"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "亲，这个价真出不了～359.10 已经是诚意价了，真心喜欢就带走吧！",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=335.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "counter 359.10 · BARGAIN-COUNTER-T3 · 已让步 2 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "你太狠了，335行不行？",
    "note_zh": "梯度第 3 档：399 × 90% = 359.10——授权梯度的最后一档",
    "note_en": "Tier 3: 399 × 90% = 359.10 — the last rung of the authorized ladder",
    "expected": {
     "kind": "counter",
     "price": "359.10",
     "rule_id": "BARGAIN-COUNTER-T3",
     "used": 2
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "335.00"
    },
    "step_index": 3,
    "total_steps": 6,
    "finished": false,
    "concessions_used": 3,
    "persona": {
     "id": "wang",
     "name_zh": "砍价党老王",
     "name_en": "Haggler Wang",
     "style_zh": "开口对半砍，被拒了就一点点往上磨",
     "style_en": "Opens at half price, then grinds upward",
     "language": "zh",
     "avatar_color": "#DC2626",
     "item_key": "keyboard"
    }
   },
   {
    "suggestion_id": "e5425dafc09549879e4874502a26aae2",
    "conversation_id": "de75da31d1cf4cb48c9f250e3bb8f372",
    "item": {
     "id": "5d1ad72b49774ca6a8349ebf48353a8c",
     "title": "机械键盘 87 键 茶轴",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "338.00"
    },
    "decision": {
     "kind": "firm",
     "price": null,
     "rule_id": "BARGAIN-FIRM-EXHAUSTED",
     "citations": [
      "让步次数已达上限 3 次，不再降价；守住挂牌价沟通或转人工"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "价格已经降到底啦，399.00 真不刀了，抱歉哈～",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=338.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "firm · BARGAIN-FIRM-EXHAUSTED · 已让步 3 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "338，到底出不出嘛？",
    "note_zh": "338 距底价 339.15 只差 1.15 元，但让步已达上限 3 次 → 守价不再降。制度比话术可靠：AI 不会被磨到破底",
    "note_en": "338 is just 1.15 below the floor, but the 3-concession cap is reached → price holds. The system beats persuasion: the AI can't be ground down past its authorization",
    "expected": {
     "kind": "firm",
     "rule_id": "BARGAIN-FIRM-EXHAUSTED",
     "used": 3
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "338.00"
    },
    "step_index": 4,
    "total_steps": 6,
    "finished": false,
    "concessions_used": 3,
    "persona": {
     "id": "wang",
     "name_zh": "砍价党老王",
     "name_en": "Haggler Wang",
     "style_zh": "开口对半砍，被拒了就一点点往上磨",
     "style_en": "Opens at half price, then grinds upward",
     "language": "zh",
     "avatar_color": "#DC2626",
     "item_key": "keyboard"
    }
   },
   {
    "suggestion_id": "0fe45cf352c04290ae34e93979b62ba8",
    "conversation_id": "de75da31d1cf4cb48c9f250e3bb8f372",
    "item": {
     "id": "5d1ad72b49774ca6a8349ebf48353a8c",
     "title": "机械键盘 87 键 茶轴",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "340.00"
    },
    "decision": {
     "kind": "accept",
     "price": null,
     "rule_id": "BARGAIN-ACCEPT",
     "citations": [
      "买家出价已达到您设定的底价，按授权可以成交",
      "让步次数已达上限 3 次，不再降价；守住挂牌价沟通或转人工"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "好嘞，就按您说的 340.00 出！我这就改价，您直接拍就行～",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=340.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "accept · BARGAIN-ACCEPT · 已让步 3 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "行行行，就340吧！",
    "note_zh": "340 ≥ 底价 339.15 → 授权内直接成交。让步用尽也不挡成交：ACCEPT 优先级永远高于 FIRM",
    "note_en": "340 ≥ floor 339.15 → deal closes within authorization. ACCEPT always outranks FIRM — a good offer is never blocked by the concession cap",
    "expected": {
     "kind": "accept",
     "rule_id": "BARGAIN-ACCEPT",
     "used": 3
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "340.00"
    },
    "step_index": 5,
    "total_steps": 6,
    "finished": true,
    "concessions_used": 3,
    "persona": {
     "id": "wang",
     "name_zh": "砍价党老王",
     "name_en": "Haggler Wang",
     "style_zh": "开口对半砍，被拒了就一点点往上磨",
     "style_en": "Opens at half price, then grinds upward",
     "language": "zh",
     "avatar_color": "#DC2626",
     "item_key": "keyboard"
    }
   }
  ],
  "li": [
   {
    "suggestion_id": "683573287ee64002a08a45039ba26c80",
    "conversation_id": "95a67311e14c4166aa78f7367d8b2031",
    "item": {
     "id": "c86c1b029a2c4b3f97aaed9e3ca3da5c",
     "title": "Switch 游戏卡带",
     "asking_price": "180.00",
     "floor_price": "153.00"
    },
    "classification": {
     "kind": "chitchat",
     "language": "zh",
     "offer": null
    },
    "decision": null,
    "reply_text": "在的，亲～有什么想了解的随时问。",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 chitchat/zh"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "非议价消息，引擎未介入"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "还在吗",
    "note_zh": "打招呼不进引擎——没有数字可判。引擎只在「有钱要算」时介入，这是「钱由程序算」的另一半",
    "note_en": "Greetings never reach the engine — there is no number to adjudicate. The engine only steps in when money is on the table",
    "expected": {
     "kind": "none"
    },
    "expected_classify": {
     "kind": "chitchat",
     "offer": null
    },
    "step_index": 0,
    "total_steps": 4,
    "finished": false,
    "concessions_used": 0,
    "persona": {
     "id": "li",
     "name_zh": "沉默寡言 Li",
     "name_en": "Man-of-Few-Words Li",
     "style_zh": "消息极短，惜字如金",
     "style_en": "Terse, minimal messages",
     "language": "zh",
     "avatar_color": "#78716C",
     "item_key": "gamecard"
    }
   },
   {
    "suggestion_id": "eeae806c900e4bb195cfe56f1ac81d5e",
    "conversation_id": "95a67311e14c4166aa78f7367d8b2031",
    "item": {
     "id": "c86c1b029a2c4b3f97aaed9e3ca3da5c",
     "title": "Switch 游戏卡带",
     "asking_price": "180.00",
     "floor_price": "153.00"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "140.00"
    },
    "decision": {
     "kind": "counter",
     "price": "171.00",
     "rule_id": "BARGAIN-COUNTER-T1",
     "citations": [
      "第 1 轮让步：按挂牌价 95% 还价（让步梯度第 1 档）"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "亲，这个价真出不了～171.00 已经是诚意价了，真心喜欢就带走吧！",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=140.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "counter 171.00 · BARGAIN-COUNTER-T1 · 已让步 0 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "140行不",
    "note_zh": "卡带底价 = 180 × 85% = 153.00；140 < 153 但过了 80% 线 → 梯度第 1 档：180 × 95% = 171.00",
    "note_en": "Card floor = 180 × 85% = 153.00; 140 < floor but above the 80% line → tier 1: 180 × 95% = 171.00",
    "expected": {
     "kind": "counter",
     "price": "171.00",
     "rule_id": "BARGAIN-COUNTER-T1",
     "used": 0
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "140.00"
    },
    "step_index": 1,
    "total_steps": 4,
    "finished": false,
    "concessions_used": 1,
    "persona": {
     "id": "li",
     "name_zh": "沉默寡言 Li",
     "name_en": "Man-of-Few-Words Li",
     "style_zh": "消息极短，惜字如金",
     "style_en": "Terse, minimal messages",
     "language": "zh",
     "avatar_color": "#78716C",
     "item_key": "gamecard"
    }
   },
   {
    "suggestion_id": "3094591076cb4331b49fc36cee4213f8",
    "conversation_id": "95a67311e14c4166aa78f7367d8b2031",
    "item": {
     "id": "c86c1b029a2c4b3f97aaed9e3ca3da5c",
     "title": "Switch 游戏卡带",
     "asking_price": "180.00",
     "floor_price": "153.00"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "150.00"
    },
    "decision": {
     "kind": "counter",
     "price": "165.60",
     "rule_id": "BARGAIN-COUNTER-T2",
     "citations": [
      "第 2 轮让步：按挂牌价 92% 还价（让步梯度第 2 档）"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "亲，这个价真出不了～165.60 已经是诚意价了，真心喜欢就带走吧！",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=150.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "counter 165.60 · BARGAIN-COUNTER-T2 · 已让步 1 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "150",
    "note_zh": "两个字也是一条完整事实：150 < 153 → 梯度第 2 档：180 × 92% = 165.60",
    "note_en": "Two characters still make a complete fact: 150 < 153 → tier 2: 180 × 92% = 165.60",
    "expected": {
     "kind": "counter",
     "price": "165.60",
     "rule_id": "BARGAIN-COUNTER-T2",
     "used": 1
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "150.00"
    },
    "step_index": 2,
    "total_steps": 4,
    "finished": false,
    "concessions_used": 2,
    "persona": {
     "id": "li",
     "name_zh": "沉默寡言 Li",
     "name_en": "Man-of-Few-Words Li",
     "style_zh": "消息极短，惜字如金",
     "style_en": "Terse, minimal messages",
     "language": "zh",
     "avatar_color": "#78716C",
     "item_key": "gamecard"
    }
   },
   {
    "suggestion_id": "d91396c2b7ca4ce7b1008e95830dc1b8",
    "conversation_id": "95a67311e14c4166aa78f7367d8b2031",
    "item": {
     "id": "c86c1b029a2c4b3f97aaed9e3ca3da5c",
     "title": "Switch 游戏卡带",
     "asking_price": "180.00",
     "floor_price": "153.00"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "155.00"
    },
    "decision": {
     "kind": "accept",
     "price": null,
     "rule_id": "BARGAIN-ACCEPT",
     "citations": [
      "买家出价已达到您设定的底价，按授权可以成交",
      "第 3 轮让步：按挂牌价 90% 还价（让步梯度第 3 档）"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "好嘞，就按您说的 155.00 出！我这就改价，您直接拍就行～",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=155.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "accept · BARGAIN-ACCEPT · 已让步 2 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "好吧那就155",
    "note_zh": "155 ≥ 底价 153.00 → 成交。全程卖家只打了四个字，剩下的都是店员的事",
    "note_en": "155 ≥ floor 153.00 → deal. The seller typed four characters in total; the clerk did the rest",
    "expected": {
     "kind": "accept",
     "rule_id": "BARGAIN-ACCEPT",
     "used": 2
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "155.00"
    },
    "step_index": 3,
    "total_steps": 4,
    "finished": true,
    "concessions_used": 2,
    "persona": {
     "id": "li",
     "name_zh": "沉默寡言 Li",
     "name_en": "Man-of-Few-Words Li",
     "style_zh": "消息极短，惜字如金",
     "style_en": "Terse, minimal messages",
     "language": "zh",
     "avatar_color": "#78716C",
     "item_key": "gamecard"
    }
   }
  ],
  "zhang": [
   {
    "suggestion_id": "796201197155485a8bbbb5d7bf38d575",
    "conversation_id": "0f89e0a6c31b46499ad51663f466109e",
    "item": {
     "id": "1187d198282949a1bac691b42e7d3fc1",
     "title": "小米手环 8",
     "asking_price": "129.00",
     "floor_price": "109.65"
    },
    "classification": {
     "kind": "aftersale",
     "language": "zh",
     "offer": null
    },
    "decision": null,
    "reply_text": "真不好意思给您添麻烦了！您别急，把订单号和问题照片发我，我马上处理。",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 aftersale/zh"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "非议价消息，引擎未介入"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "收到的手环是坏的，充不上电",
    "note_zh": "售后消息不议价、不进引擎；模板话术先稳住并索要订单号与照片。LLM 在线时这一步会更有人味儿，但决策路径完全一致",
    "note_en": "After-sales messages never reach the engine; the template calms the buyer and asks for order number + photos. A live LLM would sound warmer, but the decision path is identical",
    "expected": {
     "kind": "none"
    },
    "expected_classify": {
     "kind": "aftersale",
     "offer": null
    },
    "step_index": 0,
    "total_steps": 3,
    "finished": false,
    "concessions_used": 0,
    "persona": {
     "id": "zhang",
     "name_zh": "售后抱怨张姐",
     "name_en": "Upset Customer Zhang",
     "style_zh": "收货后来投诉，情绪逐步升级",
     "style_en": "Post-purchase complaints, escalating",
     "language": "zh",
     "avatar_color": "#D97706",
     "item_key": "band"
    }
   },
   {
    "suggestion_id": "9082716598a14b648b6d39435e3819a7",
    "conversation_id": "0f89e0a6c31b46499ad51663f466109e",
    "item": {
     "id": "1187d198282949a1bac691b42e7d3fc1",
     "title": "小米手环 8",
     "asking_price": "129.00",
     "floor_price": "109.65"
    },
    "classification": {
     "kind": "aftersale",
     "language": "zh",
     "offer": null
    },
    "decision": null,
    "reply_text": "真不好意思给您添麻烦了！您别急，把订单号和问题照片发我，我马上处理。",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 aftersale/zh"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "非议价消息，引擎未介入"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "我要退货，退款怎么弄？",
    "note_zh": "退货诉求：AI 只收集信息、不承诺退款——承诺超出授权的事会被护栏拦下",
    "note_en": "Return request: the AI collects facts but never promises refunds — unauthorized promises get blocked by the guardrail",
    "expected": {
     "kind": "none"
    },
    "expected_classify": {
     "kind": "aftersale",
     "offer": null
    },
    "step_index": 1,
    "total_steps": 3,
    "finished": false,
    "concessions_used": 0,
    "persona": {
     "id": "zhang",
     "name_zh": "售后抱怨张姐",
     "name_en": "Upset Customer Zhang",
     "style_zh": "收货后来投诉，情绪逐步升级",
     "style_en": "Post-purchase complaints, escalating",
     "language": "zh",
     "avatar_color": "#D97706",
     "item_key": "band"
    }
   },
   {
    "suggestion_id": "900cb0ad7c1e4b219ea37e87d061a46e",
    "conversation_id": "0f89e0a6c31b46499ad51663f466109e",
    "item": {
     "id": "1187d198282949a1bac691b42e7d3fc1",
     "title": "小米手环 8",
     "asking_price": "129.00",
     "floor_price": "109.65"
    },
    "classification": {
     "kind": "aftersale",
     "language": "zh",
     "offer": null
    },
    "decision": null,
    "reply_text": "真不好意思给您添麻烦了！您别急，把订单号和问题照片发我，我马上处理。",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 aftersale/zh"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "非议价消息，引擎未介入"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "我要投诉你们，赶紧给我退款",
    "note_zh": "情绪升级——真实工作台里店主可以一键「转人工」接管；AI 的职责是不火上浇油",
    "note_en": "Emotion escalates — in the real workbench the seller can take over with one click; the AI's job is to never pour oil on the fire",
    "expected": {
     "kind": "none"
    },
    "expected_classify": {
     "kind": "aftersale",
     "offer": null
    },
    "step_index": 2,
    "total_steps": 3,
    "finished": true,
    "concessions_used": 0,
    "persona": {
     "id": "zhang",
     "name_zh": "售后抱怨张姐",
     "name_en": "Upset Customer Zhang",
     "style_zh": "收货后来投诉，情绪逐步升级",
     "style_en": "Post-purchase complaints, escalating",
     "language": "zh",
     "avatar_color": "#D97706",
     "item_key": "band"
    }
   }
  ],
  "emma": [
   {
    "suggestion_id": "5980155930b641bbaa8adb5b60d5d1e0",
    "conversation_id": "246dbeecfdea4f638b4367153cf89a83",
    "item": {
     "id": "5d1ad72b49774ca6a8349ebf48353a8c",
     "title": "机械键盘 87 键 茶轴",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    "classification": {
     "kind": "chitchat",
     "language": "en",
     "offer": null
    },
    "decision": null,
    "reply_text": "Hi there! Happy to answer any questions.",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 chitchat/en"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "非议价消息，引擎未介入"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（en）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "Hi, is this still available?",
    "note_zh": "分类器识别 language=en——接下来所有回复自动用英文起草，店主不用会英语",
    "note_en": "The classifier detects language=en — every reply from here is drafted in English, so the seller doesn't have to speak it",
    "expected": {
     "kind": "none"
    },
    "expected_classify": {
     "kind": "chitchat",
     "offer": null
    },
    "step_index": 0,
    "total_steps": 3,
    "finished": false,
    "concessions_used": 0,
    "persona": {
     "id": "emma",
     "name_zh": "海外买家 Emma",
     "name_en": "Emma (overseas buyer)",
     "style_zh": "英文询价，礼貌直接",
     "style_en": "English-speaking, polite and direct",
     "language": "en",
     "avatar_color": "#1677FF",
     "item_key": "keyboard"
    }
   },
   {
    "suggestion_id": "106de52cee9344a0aa51e43b24ab1d3e",
    "conversation_id": "246dbeecfdea4f638b4367153cf89a83",
    "item": {
     "id": "5d1ad72b49774ca6a8349ebf48353a8c",
     "title": "机械键盘 87 键 茶轴",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    "classification": {
     "kind": "bargain",
     "language": "en",
     "offer": "300.00"
    },
    "decision": {
     "kind": "counter",
     "price": "379.05",
     "rule_id": "BARGAIN-COUNTER-T1",
     "citations": [
      "第 1 轮让步：按挂牌价 95% 还价（让步梯度第 1 档）"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "Sorry, I can't go that low. The best I can do is 379.05 — it's a really fair price!",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/en offer=300.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "counter 379.05 · BARGAIN-COUNTER-T1 · 已让步 0 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（en）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "Would you take 300 for it?",
    "note_zh": "英文买家、中文店主、同一套授权引擎：钱由程序算，语言只是话术的皮。这就是跨境场景的全部秘密",
    "note_en": "English buyer, Chinese seller, one authorization engine: money is computed by the program — language is just the wrapper. That's the whole trick for cross-border selling",
    "expected": {
     "kind": "counter",
     "price": "379.05",
     "rule_id": "BARGAIN-COUNTER-T1",
     "used": 0
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "300.00"
    },
    "step_index": 1,
    "total_steps": 3,
    "finished": false,
    "concessions_used": 1,
    "persona": {
     "id": "emma",
     "name_zh": "海外买家 Emma",
     "name_en": "Emma (overseas buyer)",
     "style_zh": "英文询价，礼貌直接",
     "style_en": "English-speaking, polite and direct",
     "language": "en",
     "avatar_color": "#1677FF",
     "item_key": "keyboard"
    }
   },
   {
    "suggestion_id": "4db5029698f2409181feb51bcaad7f00",
    "conversation_id": "246dbeecfdea4f638b4367153cf89a83",
    "item": {
     "id": "5d1ad72b49774ca6a8349ebf48353a8c",
     "title": "机械键盘 87 键 茶轴",
     "asking_price": "399.00",
     "floor_price": "339.15"
    },
    "classification": {
     "kind": "bargain",
     "language": "en",
     "offer": "340.00"
    },
    "decision": {
     "kind": "accept",
     "price": null,
     "rule_id": "BARGAIN-ACCEPT",
     "citations": [
      "买家出价已达到您设定的底价，按授权可以成交",
      "第 2 轮让步：按挂牌价 92% 还价（让步梯度第 2 档）"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "Deal at 340.00! I'll update the price — go ahead and place the order.",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/en offer=340.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "accept · BARGAIN-ACCEPT · 已让步 1 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（en）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "OK, would you take 340?",
    "note_zh": "340 ≥ 底价 339.15 → 英文成交话术。（MVP 边界：数字按人民币口径，汇率换算是 roadmap）",
    "note_en": "340 ≥ floor 339.15 → deal, in English. (MVP boundary: amounts are CNY-denominated; FX conversion is on the roadmap)",
    "expected": {
     "kind": "accept",
     "rule_id": "BARGAIN-ACCEPT",
     "used": 1
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "340.00"
    },
    "step_index": 2,
    "total_steps": 3,
    "finished": true,
    "concessions_used": 1,
    "persona": {
     "id": "emma",
     "name_zh": "海外买家 Emma",
     "name_en": "Emma (overseas buyer)",
     "style_zh": "英文询价，礼貌直接",
     "style_en": "English-speaking, polite and direct",
     "language": "en",
     "avatar_color": "#1677FF",
     "item_key": "keyboard"
    }
   }
  ],
  "chen": [
   {
    "suggestion_id": "3aea57f7cf9a4b29bc28d9846686b1f1",
    "conversation_id": "1e3afdbeb0fc4a85aa2e299d15ee25e6",
    "item": {
     "id": "1187d198282949a1bac691b42e7d3fc1",
     "title": "小米手环 8",
     "asking_price": "129.00",
     "floor_price": "109.65"
    },
    "classification": {
     "kind": "bargain",
     "language": "zh",
     "offer": "120.00"
    },
    "decision": {
     "kind": "accept",
     "price": null,
     "rule_id": "BARGAIN-ACCEPT",
     "citations": [
      "买家出价已达到您设定的底价，按授权可以成交",
      "第 1 轮让步：按挂牌价 95% 还价（让步梯度第 1 档）"
     ],
     "reasons": [],
     "requires_human_review": false
    },
    "reply_text": "好嘞，就按您说的 120.00 出！我这就改价，您直接拍就行～",
    "guardrail_hits": [],
    "trace": [
     {
      "step": "classify",
      "ok": true,
      "ms": 0,
      "note": "模板分类 bargain/zh offer=120.00"
     },
     {
      "step": "decide",
      "ok": true,
      "ms": 0,
      "note": "accept · BARGAIN-ACCEPT · 已让步 0 次"
     },
     {
      "step": "draft",
      "ok": true,
      "ms": 0,
      "note": "模板话术（zh）"
     },
     {
      "step": "guardrail",
      "ok": true,
      "ms": 0,
      "note": "0 命中"
     }
    ],
    "quota": {
     "used_today": 0,
     "free_limit": 10,
     "plan": "free"
    },
    "persona_message": "老板，120包邮的话我现在就拍",
    "note_zh": "120 ≥ 底价 109.65 → 直接成交，从收到消息到给出建议不到一秒。快，本身就是转化率",
    "note_en": "120 ≥ floor 109.65 → instant deal; suggestion ready in under a second. Speed itself is conversion",
    "expected": {
     "kind": "accept",
     "rule_id": "BARGAIN-ACCEPT",
     "used": 0
    },
    "expected_classify": {
     "kind": "bargain",
     "offer": "120.00"
    },
    "step_index": 0,
    "total_steps": 1,
    "finished": true,
    "concessions_used": 0,
    "persona": {
     "id": "chen",
     "name_zh": "爽快人小陈",
     "name_en": "Quick-Trigger Chen",
     "style_zh": "开口就是能成交的价",
     "style_en": "Opens with a deal-closing price",
     "language": "zh",
     "avatar_color": "#16A34A",
     "item_key": "band"
    }
   }
  ]
 }
};
