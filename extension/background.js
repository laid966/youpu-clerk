// 有谱掌柜扩展 · Service Worker
//
// 职责：设置存取、API 代理（fetch 走服务端 CORS，不申请 host_permissions）、
// 右键菜单「问有谱掌柜」。
//
// 合规姿势（产品决定，不是技术妥协）：
// - 只做"建议"：扩展永远由店主亲手选中文字触发、亲手复制/点发送后才生效；
//   源码里不存在免手发送的能力（tests/test_clerk_extension.py 盯着这条红线）。
// - 不碰密码、不碰 cookie、不逆向平台私有接口——只调我们自己工作台的公开 API。

const DEFAULTS = {
  apiBase: "http://127.0.0.1:8100",
  token: "",
  activeItem: "",
};

async function getSettings() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  const settings = Object.assign({}, DEFAULTS, stored);
  if (!settings.token) {
    settings.token = "ext" + Date.now().toString(16) + Math.random().toString(16).slice(2, 10);
    await chrome.storage.local.set({ token: settings.token });
  }
  return settings;
}

async function apiFetch(path, options, settings) {
  const cfg = settings || (await getSettings());
  const headers = Object.assign(
    { "Content-Type": "application/json", "X-Clerk-User": cfg.token },
    (options && options.headers) || {}
  );
  const res = await fetch(cfg.apiBase.replace(/\/$/, "") + path, Object.assign({}, options, { headers }));
  let data = {};
  try { data = await res.json(); } catch (e) { data = {}; }
  if (!res.ok) {
    const error = data.error || {};
    return { error: error.code || "HTTP_" + res.status, message: error.message || res.statusText, status: res.status, pricing: error.pricing };
  }
  return data;
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "ask-youpu",
    title: "问有谱掌柜：这句怎么回",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "ask-youpu" || !info.selectionText) return;
  const result = await handleSuggest(info.selectionText.trim());
  chrome.tabs.sendMessage(tab.id, { type: "youpu-result", result, text: info.selectionText.trim() }).catch(() => {
    // 页面没有 content script（如 chrome:// 页）——静默忽略
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    try {
      if (message.type === "suggest") {
        sendResponse(await handleSuggest(message.text));
      } else if (message.type === "adopt") {
        sendResponse(await apiFetch("/api/inquiries/" + message.suggestionId + "/adopt", {
          method: "POST",
          body: JSON.stringify({ action: message.action, final_text: message.finalText || null }),
        }));
      } else if (message.type === "settings") {
        sendResponse(await getSettings());
      } else if (message.type === "saveSettings") {
        await chrome.storage.local.set(message.values);
        sendResponse({ ok: true });
      } else if (message.type === "items") {
        sendResponse(await apiFetch("/api/items"));
      } else if (message.type === "entitlements") {
        sendResponse(await apiFetch("/api/entitlements/me"));
      } else if (message.type === "health") {
        sendResponse(await apiFetch("/api/health"));
      } else {
        sendResponse({ error: "UNKNOWN_MESSAGE" });
      }
    } catch (networkError) {
      sendResponse({ error: "NETWORK", message: String(networkError && networkError.message || networkError) });
    }
  })();
  return true; // 异步 sendResponse
});

async function handleSuggest(text) {
  const settings = await getSettings();
  if (!text) return { error: "EMPTY_TEXT" };
  if (!settings.activeItem) return { error: "NO_ITEM" };
  return apiFetch("/api/inquiry", {
    method: "POST",
    body: JSON.stringify({ item_id: settings.activeItem, message: text, source: "extension" }),
  }, settings);
}
