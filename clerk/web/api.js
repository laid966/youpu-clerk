// API 层：真实模式走 fetch + X-Clerk-User 头；?mock=1 时用 clerk.capture_mock
// 从真实后端抓取的响应数据回放（mock.js 头部注释说明了生成方式）。
// 原则：mock 与真实 API 返回**完全同形**——视图层不知道也不该知道自己在哪种模式。

import mock from "./mock.js";

export const IS_MOCK = new URLSearchParams(location.search).has("mock");

function makeToken() {
  // ?token= 用于跨端身份打通：Chrome 扩展的「打开工作台」按钮带着扩展自己的 token
  // 过来，网页端就沿用同一个身份（商品档案、台账、额度全在一个账户下）。
  const fromUrl = new URLSearchParams(location.search).get("token");
  let token = fromUrl || localStorage.getItem("clerk.user");
  if (!token) {
    token = crypto.randomUUID
      ? crypto.randomUUID().replaceAll("-", "")
      : "u" + Date.now().toString(16) + Math.random().toString(16).slice(2);
  }
  localStorage.setItem("clerk.user", token);
  return token;
}
export const USER_TOKEN = makeToken();

async function call(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json", "X-Clerk-User": USER_TOKEN },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (networkError) {
    const err = new Error("NETWORK");
    err.code = "NETWORK";
    err.status = 0;
    throw err;
  }
  let data = {};
  try {
    data = await res.json();
  } catch (emptyBody) {
    data = {};
  }
  if (!res.ok) {
    const err = new Error((data.error && data.error.message) || res.statusText);
    err.code = (data.error && data.error.code) || "HTTP_" + res.status;
    err.status = res.status;
    err.pricing = data.error && data.error.pricing;
    throw err;
  }
  return data;
}

// ---- mock 回放状态（内存级：刷新页面从头播，与真后端"进度在服务端"不同，够用）----
const mockProgress = {};

function mockItems() {
  return mock.bootstrap.shop.items.map((item) => ({
    id: item.key,
    title: item.title,
    title_en: item.title_en,
    asking_price: item.asking_price,
    floor_price: item.floor_price,
    platform: "demo",
    status: "active",
  }));
}

function mockConversations() {
  return Object.keys(mock.scripts).map((personaId) => {
    const persona = mock.bootstrap.personas.find((p) => p.id === personaId) || {};
    const steps = mock.scripts[personaId];
    return {
      id: "mock-" + personaId,
      item_id: persona.item_key,
      buyer_alias: personaId,
      language: persona.language || "zh",
      status: "open",
      created_at: "",
      updated_at: "",
      _mockSteps: steps,
    };
  });
}

function mockLedger() {
  const entries = [];
  for (const personaId of Object.keys(mock.scripts)) {
    for (const step of mock.scripts[personaId]) {
      entries.push({
        id: step.suggestion_id,
        conversation_id: "mock-" + personaId,
        kind: step.decision ? step.decision.kind : "none",
        price: step.decision ? step.decision.price : null,
        rule_id: step.decision ? step.decision.rule_id : null,
        citations: step.decision ? step.decision.citations : [],
        reply_text: step.reply_text,
        adopted: "sent",
        requires_human_review: step.decision ? step.decision.requires_human_review : false,
        created_at: "",
      });
    }
  }
  return entries;
}

function mockReport() {
  const entries = mockLedger();
  const kinds = entries.map((entry) => entry.kind);
  const count = (k) => kinds.filter((x) => x === k).length;
  return {
    day: "",
    inquiries: entries.length,
    bargain_related: entries.length - count("none"),
    counters: count("counter"),
    accepts: count("accept"),
    firms: count("firm"),
    humans: count("human"),
    concessions_adopted: count("counter"),
    adopted: entries.length,
    adopt_rate: 1,
  };
}

export const api = {
  health: () => (IS_MOCK ? Promise.resolve(mock.health) : call("GET", "/api/health")),
  demoBootstrap: () => (IS_MOCK ? Promise.resolve(mock.bootstrap) : call("GET", "/api/demo/bootstrap")),

  demoStep(personaId, conversationId) {
    if (!IS_MOCK) {
      return call("POST", "/api/demo/step", {
        persona_id: personaId,
        conversation_id: conversationId || null,
      });
    }
    const script = mock.scripts[personaId];
    if (!script) {
      return Promise.reject(Object.assign(new Error("no script"), { code: "DEMO_ERROR", status: 400 }));
    }
    if (!conversationId) mockProgress[personaId] = 0; // 新开局
    const index = mockProgress[personaId] || 0;
    if (index >= script.length) {
      return Promise.reject(Object.assign(new Error("finished"), { code: "DEMO_ERROR", status: 400 }));
    }
    mockProgress[personaId] = index + 1;
    return Promise.resolve(
      Object.assign({}, script[index], { conversation_id: "mock-" + personaId })
    );
  },

  payProducts: () => (IS_MOCK ? Promise.resolve(mock.payProducts) : call("GET", "/api/pay/products")),
  payOrder: (productCode) => call("POST", "/api/pay/order", { product_code: productCode }),
  payNotifyDev: (outTradeNo, amount) =>
    call("POST", "/api/pay/notify-dev", { out_trade_no: outTradeNo, amount }),
  payQuery: (outTradeNo) => call("POST", "/api/pay/query", { out_trade_no: outTradeNo }),
  entitlements: () =>
    IS_MOCK
      ? Promise.resolve({ plan: "free", active: false, expires_at: null, quota: { used_today: 0, free_limit: 10 } })
      : call("GET", "/api/entitlements/me"),
  items: () => (IS_MOCK ? Promise.resolve({ items: mockItems() }) : call("GET", "/api/items")),
  createItem: (payload) => call("POST", "/api/items", payload),
  updateItem: (itemId, payload) => call("PATCH", "/api/items/" + itemId, payload),
  inquiry: (payload) => call("POST", "/api/inquiry", payload),
  adopt: (suggestionId, action, finalText) =>
    call("POST", "/api/inquiries/" + suggestionId + "/adopt", {
      action,
      final_text: finalText || null,
    }),
  conversations: () =>
    IS_MOCK ? Promise.resolve({ conversations: mockConversations() }) : call("GET", "/api/conversations"),
  conversation: (conversationId) => call("GET", "/api/conversations/" + conversationId),
  ledger: (day) =>
    IS_MOCK
      ? Promise.resolve({ day: day || "", entries: mockLedger() })
      : call("GET", "/api/ledger" + (day ? "?day=" + encodeURIComponent(day) : "")),
  reportDaily: () => (IS_MOCK ? Promise.resolve(mockReport()) : call("GET", "/api/report/daily")),
};
