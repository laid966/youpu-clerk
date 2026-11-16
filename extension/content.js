// 有谱掌柜扩展 · Content Script
//
// 交互模型（划词建议，平台无关）：
//   选中买家消息 → 出现「谱」浮动按钮 → 点击 → 浮动面板给出建议
//   → 店主点「复制回复」→ 亲手粘贴发送 → 点「已发送」写台账
//
// 为什么用划词而不是逆向页面 DOM：
// 1. 不依赖任何平台的 DOM 结构——闲鱼改版不影响，甚至淘宝/微信网页版都能用；
// 2. 不碰平台私有接口，合规姿态最干净（我们只是店主自己的剪贴板助手）；
// 3. G1（闲鱼网页 IM 结构验证）通过后，可再加"自动监听"增强层，划词永远是兜底。
//
// 红线：本文件不存在任何代替店主发送消息的能力（有测试盯着）。

const IS_ZH = (navigator.language || "").toLowerCase().startsWith("zh");
const L = IS_ZH
  ? {
      ask: "谱 · 问掌柜",
      loading: "程序算钱中…",
      copy: "复制回复",
      copied: "已复制——去亲手发给买家吧",
      markSent: "已发送（记台账）",
      marked: "已记账 ✓",
      discard: "不用",
      openWb: "工作台",
      needItem: "请先点扩展图标，选择商品档案",
      networkError: "连不上工作台后端（先在电脑上启动 uvicorn clerk.server:app --port 8100）",
      quota: "今日免费额度已用完，去工作台升级",
      error: "出错了",
      basis: "依据",
      human: "转人工",
      kinds: { counter: "还价", accept: "可成交", firm: "守价", human: "转人工", none: "常规回复" },
    }
  : {
      ask: "YouPu · Ask",
      loading: "Computing…",
      copy: "Copy reply",
      copied: "Copied — now send it yourself",
      markSent: "Mark sent (ledger)",
      marked: "Logged ✓",
      discard: "Dismiss",
      openWb: "Workbench",
      needItem: "Click the extension icon and pick an item profile first",
      networkError: "Cannot reach the workbench backend (start uvicorn clerk.server:app --port 8100)",
      quota: "Daily free quota used up — upgrade in the workbench",
      error: "Error",
      basis: "Basis",
      human: "Human",
      kinds: { counter: "Counter", accept: "Accept", firm: "Hold", human: "Human", none: "Reply" },
    };

const ACCENT = "#1677FF";

// ---- 浮动按钮（划词出现） ----

let bubbleHost = null;

function removeBubble() {
  if (bubbleHost) {
    bubbleHost.remove();
    bubbleHost = null;
  }
}

document.addEventListener("mouseup", (event) => {
  setTimeout(() => {
    const selection = window.getSelection();
    const text = selection ? selection.toString().trim() : "";
    if (!text || text.length < 2 || text.length > 500) {
      removeBubble();
      return;
    }
    if (bubbleHost && bubbleHost.contains(event.target)) return;
    showBubble(event, text);
  }, 10);
});

document.addEventListener("mousedown", (event) => {
  if (bubbleHost && !bubbleHost.contains(event.target)) removeBubble();
});

function showBubble(event, text) {
  removeBubble();
  const range = window.getSelection().getRangeAt(0);
  const rect = range.getBoundingClientRect();
  bubbleHost = document.createElement("div");
  bubbleHost.setAttribute("style",
    "position:absolute;z-index:2147483646;left:" + (rect.right + window.scrollX - 40) + "px;top:" +
    (rect.bottom + window.scrollY + 6) + "px");
  const shadow = bubbleHost.attachShadow({ mode: "closed" });
  shadow.innerHTML =
    '<button style="all:unset;cursor:pointer;background:' + ACCENT + ";color:#fff;font:12px/1 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;" +
    'padding:7px 12px;border-radius:999px;box-shadow:0 4px 14px rgba(22,119,255,.4)">' +
    L.ask + "</button>";
  shadow.querySelector("button").addEventListener("click", () => {
    removeBubble();
    askClerk(text);
  });
  document.documentElement.appendChild(bubbleHost);
}

// ---- 建议面板 ----

let panelHost = null;

async function askClerk(text) {
  openPanel('<div style="padding:20px;color:#78716C;font-size:13px">' + L.loading + "</div>");
  const result = await chrome.runtime.sendMessage({ type: "suggest", text });
  if (!result || result.error) {
    const message =
      result && result.error === "NO_ITEM" ? L.needItem :
      result && result.error === "QUOTA_EXCEEDED" ? L.quota :
      result && result.error === "NETWORK" ? L.networkError :
      (result && result.message) || L.error;
    openPanel('<div style="padding:20px;color:#DC2626;font-size:13px;max-width:280px">' + esc(message) + "</div>");
    return;
  }
  renderSuggestion(result);
}

function renderSuggestion(s) {
  const d = s.decision;
  const kind = d ? d.kind : "none";
  const colors = { counter: ACCENT, accept: "#16A34A", firm: "#D97706", human: "#DC2626", none: "#78716C" };
  const color = colors[kind] || ACCENT;
  const price = d && d.price ? '<span style="font:600 20px/1 ui-monospace,Consolas,monospace;color:' + color + '">' + (IS_ZH ? "¥" : "CNY ") + d.price + "</span>" : "";
  const cites = d && d.citations && d.citations.length
    ? '<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px">' +
      d.citations.map((c) => '<span style="font-size:11px;color:#78716C;border:1px solid #E7E5E4;border-radius:999px;padding:2px 8px">' + esc(c) + "</span>").join("") + "</div>"
    : "";
  openPanel(
    '<div style="width:320px;font:13px/1.6 -apple-system,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;color:#1C1917">' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">' +
        '<span style="font-size:11.5px;font-weight:600;padding:2px 9px;border-radius:999px;background:' + color + '1A;color:' + color + '">' + L.kinds[kind] + "</span>" +
        price +
        '<button id="yp-close" style="all:unset;margin-left:auto;cursor:pointer;color:#A8A29E;font-size:15px;padding:0 4px">✕</button>' +
      "</div>" +
      '<div style="background:#FAFAF9;border:1px dashed #D6D3D1;border-radius:6px;padding:8px 10px;white-space:pre-wrap;word-break:break-word">' + esc(s.reply_text) + "</div>" +
      cites +
      '<div style="display:flex;gap:6px;margin-top:10px;flex-wrap:wrap">' +
        '<button id="yp-copy" style="flex:1;cursor:pointer;background:' + ACCENT + ";color:#fff;border:0;border-radius:6px;padding:7px 10px;font-size:12.5px\">" + L.copy + "</button>" +
        '<button id="yp-sent" style="cursor:pointer;background:#fff;color:#1C1917;border:1px solid #D6D3D1;border-radius:6px;padding:7px 10px;font-size:12.5px">' + L.markSent + "</button>" +
        '<button id="yp-discard" style="cursor:pointer;background:#fff;color:#78716C;border:1px solid #E7E5E4;border-radius:6px;padding:7px 10px;font-size:12.5px">' + L.discard + "</button>" +
      "</div>" +
      '<div id="yp-status" style="margin-top:8px;font-size:11.5px;color:#16A34A;min-height:16px"></div>' +
    "</div>",
    () => {
      bind("yp-copy", async () => {
        await navigator.clipboard.writeText(s.reply_text);
        setStatus(L.copied);
      });
      bind("yp-sent", async () => {
        const r = await chrome.runtime.sendMessage({ type: "adopt", suggestionId: s.suggestion_id, action: "sent" });
        setStatus(r && r.ok ? L.marked : L.error + ": " + ((r && r.message) || (r && r.error) || "?"));
      });
      bind("yp-discard", async () => {
        await chrome.runtime.sendMessage({ type: "adopt", suggestionId: s.suggestion_id, action: "discarded" });
        closePanel();
      });
      bind("yp-close", closePanel);
      function bind(id, handler) {
        const node = panelShadow.getElementById(id);
        if (node) node.addEventListener("click", handler);
      }
      function setStatus(text) {
        const node = panelShadow.getElementById("yp-status");
        if (node) node.textContent = text;
      }
    }
  );
}

let panelShadow = null;

function openPanel(innerHtml, afterBind) {
  closePanel();
  panelHost = document.createElement("div");
  panelHost.setAttribute("style",
    "position:fixed;z-index:2147483647;right:20px;bottom:20px;background:#fff;border:1px solid #E7E5E4;" +
    "border-radius:12px;box-shadow:0 12px 32px rgba(28,25,23,.18);padding:14px");
  panelShadow = panelHost.attachShadow({ mode: "open" });
  panelShadow.innerHTML = innerHtml;
  document.documentElement.appendChild(panelHost);
  if (afterBind) afterBind();
}

function closePanel() {
  if (panelHost) {
    panelHost.remove();
    panelHost = null;
    panelShadow = null;
  }
}

// 右键菜单触发的结果也走同一个面板
chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === "youpu-result") {
    if (message.result && !message.result.error) renderSuggestion(message.result);
    else openPanel('<div style="padding:16px;color:#DC2626;font-size:13px;max-width:260px">' +
      esc((message.result && (message.result.message || message.result.error)) || L.error) + "</div>");
  }
});

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
