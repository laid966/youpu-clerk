// 有谱掌柜 · 工作台 SPA
// 零构建：原生 ES modules。视图 = 字符串模板 + 事件委托（data-act）。
// 设计基调见 docs/31；API 形状见 docs/32；mock 数据是真实后端的抓取（clerk/capture_mock.py）。

import { api, IS_MOCK } from "./api.js";
import ZH from "./i18n/zh.js";
import EN from "./i18n/en.js";

const DICTS = { zh: ZH, en: EN };

function initialLang() {
  const saved = localStorage.getItem("clerk.lang");
  if (saved === "zh" || saved === "en") return saved;
  return (navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";
}

const state = {
  lang: initialLang(),
  demo: null, // { boot, pid, conv, steps, busy }
  wb: null,   // { items, conversations, activeConv, thread, pending, editing, chosenItem, report, ledger, showNew, personaNames }
  renderSeq: 0,
};

const view = document.getElementById("view");
const modalRoot = document.getElementById("modalRoot");
const toastRoot = document.getElementById("toastRoot");

// ---------------------------------------------------------------------------
// 基础工具
// ---------------------------------------------------------------------------

function t(key, vars) {
  const lookup = (dict) => key.split(".").reduce((o, k) => (o == null ? undefined : o[k]), dict);
  let value = lookup(DICTS[state.lang]);
  if (value === undefined) value = lookup(ZH);
  if (value === undefined) return key;
  if (vars) for (const [k, v] of Object.entries(vars)) value = value.replaceAll("{" + k + "}", v);
  return value;
}

const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtMoney(amountStr) {
  if (amountStr == null) return "";
  return state.lang === "en" ? "CNY " + amountStr : "¥" + amountStr;
}

const CHECK_SVG =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#16A34A" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';

// ---------------------------------------------------------------------------
// Toast 与 Modal
// ---------------------------------------------------------------------------

function toast(message, kind) {
  const node = document.createElement("div");
  node.className = "toast" + (kind ? " " + kind : "");
  node.textContent = message;
  toastRoot.appendChild(node);
  setTimeout(() => node.remove(), 3600);
}

function toastErr(error) {
  if (error && error.status === 402) {
    openPricingModal();
    return;
  }
  const code = error && error.code;
  const message =
    code && DICTS[state.lang].errors[code]
      ? t("errors." + code)
      : (error && error.message) || t("errors.generic");
  toast(message, "bad");
}

function openModal(innerHtml) {
  modalRoot.hidden = false;
  modalRoot.innerHTML =
    '<div class="modal-overlay" data-act="modal-close">' +
    '<div class="modal" data-stop="1">' +
    '<button class="modal-close" data-act="modal-close" aria-label="close">✕</button>' +
    innerHtml +
    "</div></div>";
}

function closeModal() {
  modalRoot.hidden = true;
  modalRoot.innerHTML = "";
}

// ---------------------------------------------------------------------------
// 共享组件（建议卡是产品的脸，演示与工作台共用同一个渲染器）
// ---------------------------------------------------------------------------

function traceHtml(trace) {
  if (!trace || !trace.length) return "";
  const chips = trace
    .map((step) => '<span class="trace-chip ' + (step.ok ? "ok" : "bad") + '"><b>' +
      t("suggest." + step.step) + "</b> " + step.ms + "ms</span>")
    .join(" ");
  const notes = trace
    .map((step) => "<li><b>" + t("suggest." + step.step) + "</b> · " + step.ms + "ms — " + esc(step.note) + "</li>")
    .join("");
  return '<details class="sg-trace"><summary>' + t("suggest.trace") + " · " + chips + "</summary><ol>" + notes + "</ol></details>";
}

function matchChip(step) {
  const expected = step.expected;
  if (!expected) return "";
  const actual = step.decision;
  let ok;
  if (expected.kind === "none") ok = actual === null;
  else if (!actual) ok = false;
  else {
    ok = actual.kind === expected.kind;
    if (ok && expected.kind === "counter") ok = actual.price === expected.price;
    if (ok && expected.rule_id) ok = actual.rule_id === expected.rule_id;
  }
  return ok
    ? '<span class="chip ok">✓ ' + t("demo.matchOk") + "</span>"
    : '<span class="chip bad">✗ ' + t("demo.matchBad") + "</span>";
}

function adoptedChip(adopted) {
  if (!adopted) return "";
  const key = { sent: "adoptedSent", edited: "adoptedEdited", discarded: "adoptedDiscarded", escalated: "adoptedEscalated" }[adopted];
  return key ? '<span class="chip muted">' + t("suggest." + key) + "</span>" : "";
}

// suggestion: 契约 §3 的 Suggestion 形状（或 demo/step 的扩展形状）
// opts: { match, adopted, adoptBar, editing, readonlyNote }
function suggestionCard(suggestion, opts) {
  opts = opts || {};
  const decision = suggestion.decision;
  const kind = decision ? decision.kind : "none";
  const price = decision && decision.price ? '<span class="price">' + fmtMoney(decision.price) + "</span>" : "";
  const langChip = suggestion.classification
    ? '<span class="chip muted">' + t("suggest.replyLang") + ": " + suggestion.classification.language.toUpperCase() + "</span>"
    : "";
  const cites =
    decision && decision.citations && decision.citations.length
      ? '<div class="cites">' + decision.citations.map((c) => '<span class="cite-chip">' + esc(c) + "</span>").join("") + "</div>"
      : "";
  const reasons =
    decision && decision.reasons && decision.reasons.length
      ? '<div class="reasons">' + decision.reasons.map((r) => '<span class="reason-chip">⚠ ' + esc(r) + "</span>").join("") + "</div>"
      : "";
  const guardChips =
    suggestion.guardrail_hits && suggestion.guardrail_hits.length
      ? '<div class="cites">' + suggestion.guardrail_hits.map((h) => '<span class="chip bad">拦截 ' + esc(h.rule) + "</span>").join("") + "</div>"
      : "";

  let replyBody = '<div class="sg-reply">' + esc(suggestion.reply_text) + "</div>";
  if (opts.editing) {
    replyBody =
      '<div class="sg-reply"><textarea id="editText">' + esc(opts.editing.text) + "</textarea>" +
      '<div class="adopt-bar">' +
      '<button class="btn small primary" data-act="edit-confirm">' + t("suggest.editConfirm") + "</button>" +
      '<button class="btn small" data-act="edit-cancel">' + t("suggest.editCancel") + "</button></div></div>";
  }

  let adoptBar = "";
  if (opts.adoptBar && !opts.editing) {
    adoptBar =
      '<div class="adopt-bar">' +
      '<button class="btn small primary" data-act="adopt" data-a="sent">' + t("suggest.adoptSent") + "</button>" +
      '<button class="btn small" data-act="adopt" data-a="edited">' + t("suggest.adoptEdited") + "</button>" +
      '<button class="btn small" data-act="adopt" data-a="discarded">' + t("suggest.adoptDiscard") + "</button>" +
      '<button class="btn small warn" data-act="adopt" data-a="escalated">' + t("suggest.adoptEscalate") + "</button>" +
      "</div>";
  }
  const readonly = opts.readonlyNote ? '<div class="adopt-bar"><span class="hint">' + t("suggest.mockReadonly") + "</span></div>" : "";

  return (
    '<div class="suggestion">' +
    '<div class="sg-head"><span class="badge b-' + kind + '">' + t("suggest." + kind) + "</span>" + price +
    (opts.match !== undefined ? matchChip(suggestion) : "") + langChip + adoptedChip(opts.adopted) + "</div>" +
    replyBody + cites + reasons + guardChips + traceHtml(suggestion.trace) + adoptBar + readonly +
    "</div>"
  );
}

function buyerBubble(text, alias) {
  return '<div class="msg buyer"><div class="who">' + esc(alias || t("demo.buyerSays")) + '</div><div class="bubble">' + esc(text) + "</div></div>";
}
function sellerBubble(text) {
  return '<div class="msg seller"><div class="bubble">' + esc(text) + "</div></div>";
}

// ---------------------------------------------------------------------------
// 路由与页面骨架
// ---------------------------------------------------------------------------

function currentRoute() {
  return (location.hash.replace(/^#\/?/, "").split("?")[0]) || "";
}

function renderChrome(route) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    a.textContent = t("nav." + a.dataset.nav);
    a.classList.toggle("active", a.dataset.nav === route);
  });
  document.querySelectorAll("#langSwitch button").forEach((b) =>
    b.classList.toggle("active", b.dataset.lang === state.lang));
  document.getElementById("footerText").textContent = t("footer.disclaimer");
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
}

let renderToken = 0;
async function render() {
  const seq = ++renderToken;
  const route = currentRoute();
  renderChrome(route);
  if (route === "demo") return renderDemo(seq);
  if (route === "app") return renderWorkbench(seq);
  if (route === "pricing") return renderPricing(seq);
  return renderLanding(seq);
}

function stale(seq) {
  return seq !== renderToken;
}

function renderErrorBox(error) {
  const message = error && error.code && DICTS[state.lang].errors[error.code]
    ? t("errors." + error.code)
    : (error && error.message) || t("errors.generic");
  view.innerHTML =
    '<div class="error-box"><h2>⚠</h2><p>' + esc(message) + "</p>" +
    '<button class="btn" data-act="retry">' + t("common.retry") + "</button></div>";
}

// ---------------------------------------------------------------------------
// 落地页
// ---------------------------------------------------------------------------

function renderLanding(seq) {
  const heroCard =
    '<div class="suggestion" style="align-self:stretch;width:100%">' +
    '<div class="sg-head"><span class="badge b-counter">' + t("mock.badge") + '</span><span class="price">' + fmtMoney("379.05") + "</span>" +
    '<span class="chip ok">✓ ' + t("demo.matchOk") + "</span></div>" +
    '<div class="sg-reply">' + esc(t("mock.reply")) + "</div>" +
    '<div class="cites"><span class="cite-chip">' + esc(t("mock.cite")) + "</span></div>" +
    '<div class="sg-trace"><summary style="list-style:none;color:var(--text-muted)">' + esc(t("mock.trace")) + "</summary></div>" +
    "</div>";

  view.innerHTML =
    '<section class="hero container">' +
      "<div>" +
        '<span class="hero-badge">' + esc(t("hero.badge")) + "</span>" +
        '<h1 style="white-space:pre-line">' + esc(t("hero.title")) + "</h1>" +
        '<p class="sub">' + esc(t("hero.sub")) + "</p>" +
        '<div class="ctas">' +
          '<a class="btn primary big" href="#/demo">' + esc(t("hero.ctaDemo")) + "</a>" +
          '<a class="btn big" href="#/app">' + esc(t("hero.ctaApp")) + "</a>" +
        "</div>" +
        '<div class="trust">' + esc(t("hero.trust")) + "</div>" +
      "</div>" +
      "<div>" + buyerBubble(t("mock.buyer")) + heroCard + "</div>" +
    "</section>" +

    '<section class="section container">' +
      '<h2 class="section-title">' + esc(t("principle.title")) + "</h2>" +
      '<p class="section-sub">' + esc(t("principle.sub")) + "</p>" +
      flowRow(1, t("principle.s1t"), t("principle.s1d"), t("principle.s1who"), "") +
      flowRow(2, t("principle.s2t"), t("principle.s2d"), t("principle.s2who"), "program") +
      flowRow(3, t("principle.s3t"), t("principle.s3d"), t("principle.s3who"), "human") +
    "</section>" +

    '<section class="section container">' +
      '<h2 class="section-title">' + esc(t("promise.title")) + "</h2>" +
      promiseRow(t("promise.p1t"), t("promise.p1d")) +
      promiseRow(t("promise.p2t"), t("promise.p2d")) +
      promiseRow(t("promise.p3t"), t("promise.p3d")) +
    "</section>" +

    '<section class="section container" style="text-align:center;padding-bottom:72px">' +
      '<h2 class="section-title">' + esc(t("cta.title")) + "</h2>" +
      '<p class="section-sub">' + esc(t("cta.sub")) + "</p>" +
      '<a class="btn primary big" href="#/demo">' + esc(t("cta.btn")) + " →</a>" +
    "</section>";

  if (stale(seq)) return;
}

function flowRow(num, title, desc, who, whoClass) {
  return (
    '<div class="flow-row"><div class="flow-num">' + num + "</div>" +
    "<div><h3>" + esc(title) + "</h3><p>" + esc(desc) + "</p></div>" +
    '<span class="who-chip ' + whoClass + '">' + esc(who) + "</span></div>"
  );
}

function promiseRow(title, desc) {
  return '<div class="promise-row">' + CHECK_SVG + "<div><h3>" + esc(title) + "</h3><p>" + esc(desc) + "</p></div></div>";
}

// ---------------------------------------------------------------------------
// 演示页
// ---------------------------------------------------------------------------

async function renderDemo(seq) {
  view.innerHTML = '<div class="loading">' + t("common.loading") + "</div>";
  try {
    if (!state.demo || !state.demo.boot) {
      const boot = await api.demoBootstrap();
      state.demo = Object.assign({}, state.demo, { boot });
    }
  } catch (error) {
    if (stale(seq)) return;
    return renderErrorBox(error);
  }
  if (stale(seq)) return;
  if (!state.demo.pid) renderPersonaGrid();
  else renderPlayer();
}

function renderPersonaGrid() {
  const boot = state.demo.boot;
  const itemByKey = {};
  boot.shop.items.forEach((item) => { itemByKey[item.key] = item; });

  const cards = boot.personas.map((persona) => {
    const item = itemByKey[persona.item_key] || {};
    const name = state.lang === "en" ? persona.name_en : persona.name_zh;
    const style = state.lang === "en" ? persona.style_en : persona.style_zh;
    const initial = (persona.language === "en" ? persona.name_en : persona.name_zh).slice(0, 1);
    return (
      '<button class="persona-card" data-act="pick" data-pid="' + persona.id + '">' +
      '<div class="persona-head"><span class="avatar-dot" style="background:' + persona.avatar_color + '">' + esc(initial) + "</span>" +
      "<h3>" + esc(name) + "</h3></div>" +
      '<p class="style">' + esc(style) + "</p>" +
      '<div class="persona-meta"><span class="chip muted">' + persona.language.toUpperCase() + "</span>" +
      "<span>" + persona.steps.length + " " + t("demo.stepsUnit") + "</span>" +
      "<span>· " + esc(state.lang === "en" ? item.title_en || item.title : item.title) + "</span></div>" +
      "</button>"
    );
  }).join("");

  view.innerHTML =
    '<div class="container"><h1 class="section-title">' + esc(t("demo.title")) + "</h1>" +
    '<p class="section-sub">' + esc(t("demo.sub")) + (IS_MOCK ? " · mock" : "") + "</p>" +
    '<div class="persona-grid">' + cards + "</div></div>";
}

function renderPlayer() {
  const demo = state.demo;
  const boot = demo.boot;
  const persona = boot.personas.find((p) => p.id === demo.pid);
  const item = boot.shop.items.find((i) => i.key === persona.item_key);
  const steps = demo.steps;
  const last = steps[steps.length - 1];
  const finished = last && last.finished;
  const total = last ? last.total_steps : persona.steps.length;
  const personaName = state.lang === "en" ? persona.name_en : persona.name_zh;

  const thread = steps.map((step) => {
    const note = state.lang === "en" ? step.note_en : step.note_zh;
    return (
      buyerBubble(step.persona_message, personaName) +
      suggestionCard(step, { match: true }) +
      (note ? '<div class="narration"><b>' + t("demo.narration") + "</b> · " + esc(note) + "</div>" : "")
    );
  }).join("");

  const controls = finished
    ? '<div class="player-controls"><button class="btn primary big" data-act="demo-report">' + t("demo.viewReport") + "</button>" +
      '<button class="btn" data-act="demo-restart">' + t("demo.restart") + "</button>" +
      '<span class="step-count">' + t("demo.finished") + "</span></div>"
    : '<div class="player-controls"><button class="btn primary big" data-act="demo-next"' + (demo.busy ? " disabled" : "") + ">" +
      t("demo.next") + (demo.busy ? "…" : " →") + "</button>" +
      '<button class="btn" data-act="demo-restart">' + t("demo.restart") + "</button>" +
      '<span class="step-count">' + t("demo.stepOf", { i: steps.length, n: total }) + "</span></div>";

  view.innerHTML =
    '<div class="container">' +
      '<div class="player-head">' +
        "<div><a href=\"#/demo\" data-act=\"demo-back\" style=\"color:var(--text-muted);font-size:13px\">← " + t("demo.back") + "</a>" +
        "<h1 class=\"section-title\" style=\"margin-top:6px\">" + esc(personaName) +
        ' <span class="chip muted">' + persona.language.toUpperCase() + "</span></h1></div>" +
      "</div>" +
      '<div class="player-grid">' +
        '<div><div class="thread">' + (thread || '<div class="empty">' + t("demo.sub") + "</div>") + "</div>" + controls + "</div>" +
        '<div class="side-card"><h4>' + t("demo.sellerView") + "</h4>" +
          '<div style="font-weight:600;margin-bottom:8px">' + esc(state.lang === "en" ? item.title_en || item.title : item.title) + "</div>" +
          '<div class="kv"><span>' + t("demo.asking") + '</span><span class="v">' + fmtMoney(item.asking_price) + "</span></div>" +
          '<div class="kv"><span>' + t("demo.floor") + '</span><span class="v">' + fmtMoney(item.floor_price) + "</span></div>" +
          '<p class="hint" style="margin-top:10px">' + esc(state.lang === "en" ? persona.style_en : persona.style_zh) + "</p>" +
        "</div>" +
      "</div>" +
    "</div>";
}

async function demoNext() {
  const demo = state.demo;
  if (!demo || demo.busy) return;
  demo.busy = true;
  renderPlayer();
  try {
    const body = await api.demoStep(demo.pid, demo.conv);
    demo.conv = body.conversation_id;
    demo.steps.push(body);
  } catch (error) {
    toastErr(error);
  }
  demo.busy = false;
  renderPlayer();
  const thread = document.querySelector(".thread");
  if (thread) thread.lastElementChild && thread.lastElementChild.scrollIntoView({ behavior: "smooth", block: "end" });
}

// ---------------------------------------------------------------------------
// 工作台
// ---------------------------------------------------------------------------

async function renderWorkbench(seq) {
  view.innerHTML = '<div class="loading">' + t("common.loading") + "</div>";
  try {
    if (!state.wb) {
      const [itemsRes, convsRes, report, ledgerRes] = await Promise.all([
        api.items(), api.conversations(), api.reportDaily(), api.ledger(),
      ]);
      state.wb = {
        items: itemsRes.items,
        conversations: convsRes.conversations,
        activeConv: null,
        thread: null,
        pending: null,
        editing: null,
        chosenItem: itemsRes.items.length ? itemsRes.items[0].id : "",
        report,
        ledger: ledgerRes.entries,
        showNew: false,
        personaNames: {},
      };
      if (IS_MOCK) {
        const boot = await api.demoBootstrap();
        boot.personas.forEach((p) => { state.wb.personaNames[p.id] = state.lang === "en" ? p.name_en : p.name_zh; });
      }
    }
  } catch (error) {
    if (stale(seq)) return;
    return renderErrorBox(error);
  }
  if (stale(seq)) return;
  drawWorkbench();
}

async function reloadWb() {
  const wb = state.wb;
  const [itemsRes, convsRes, report, ledgerRes] = await Promise.all([
    api.items(), api.conversations(), api.reportDaily(), api.ledger(),
  ]);
  wb.items = itemsRes.items;
  wb.conversations = convsRes.conversations;
  wb.report = report;
  wb.ledger = ledgerRes.entries;
  if (wb.activeConv && !IS_MOCK) {
    try { wb.thread = await api.conversation(wb.activeConv); } catch (e) { wb.thread = null; }
  }
}

function drawWorkbench() {
  const wb = state.wb;
  const queue = wb.conversations.map((conv) => {
    const item = wb.items.find((i) => i.id === conv.item_id);
    const alias = IS_MOCK ? (wb.personaNames[conv.buyer_alias] || conv.buyer_alias) : conv.buyer_alias;
    return (
      '<div class="conv-item' + (wb.activeConv === conv.id ? " active" : "") + '" data-act="wb-conv" data-id="' + conv.id + '">' +
      '<div class="t1"><span class="status-dot ' + (conv.status === "escalated" ? "human" : "open") + '"></span>' + esc(alias) + "</div>" +
      '<div class="t2">' + esc(item ? item.title : conv.item_id) + "</div></div>"
    );
  }).join("");

  view.innerHTML =
    (IS_MOCK ? '<div class="mock-banner">' + esc(t("wb.mockBanner")) + "</div>" : "") +
    '<div class="wb-grid">' +
      '<div class="pane"><div class="pane-head"><span>' + t("wb.queue") + "</span>" +
        (IS_MOCK ? "" : '<button class="btn small" data-act="wb-newchat">' + t("wb.newChat") + "</button>") + "</div>" +
        '<div class="pane-body">' + (queue || '<div class="empty">' + t("wb.emptyQueue") + "</div>") + "</div></div>" +

      '<div class="pane"><div class="pane-head"><span>' + t("wb.title") + "</span></div>" +
        '<div class="pane-body" id="wbCenter">' + wbCenter() + "</div></div>" +

      '<div style="display:flex;flex-direction:column;gap:16px">' +
        itemCard() + todayCard() + ledgerCard() +
      "</div>" +
    "</div>";
}

function wbCenter() {
  const wb = state.wb;
  if (IS_MOCK) return mockThread();
  if (wb.activeConv && wb.thread) return realThread() + pasteBar();
  return newChatForm() + pasteBar();
}

function newChatForm() {
  const wb = state.wb;
  const options = wb.items.map((item) =>
    '<option value="' + item.id + '"' + (item.id === wb.chosenItem ? " selected" : "") + ">" + esc(item.title) + " · " + fmtMoney(item.asking_price) + "</option>"
  ).join("");
  return (
    '<div class="item-select"><span>' + t("wb.chooseItem") + "</span>" +
    (options ? '<select id="itemSelect">' + options + "</select>" : '<span class="hint">' + t("wb.noItems") + "</span>") +
    "</div>"
  );
}

function pasteBar() {
  return (
    '<div class="paste-bar"><textarea id="pasteInput" placeholder="' + esc(t("wb.pastePlaceholder")) + '"></textarea>' +
    '<button class="btn primary" data-act="wb-suggest" style="align-self:flex-end">' + t("wb.getSuggest") + "</button></div>" +
    (state.wb.pending ? '<div class="thread" style="margin-top:16px">' + pendingCard() + "</div>" : "")
  );
}

function pendingCard() {
  const wb = state.wb;
  return suggestionCard(wb.pending, {
    adoptBar: true,
    editing: wb.editing,
  });
}

function realThread() {
  const wb = state.wb;
  const thread = wb.thread;
  const decisionByMessage = {};
  (thread.decisions || []).forEach((d) => { decisionByMessage[d.message_id] = d; });
  return '<div class="thread">' + (thread.messages || []).map((message) => {
    if (message.direction === "seller") return sellerBubble(message.body);
    const decision = decisionByMessage[message.id];
    let html = buyerBubble(message.body, thread.conversation.buyer_alias);
    if (decision) {
      html += suggestionCard(
        {
          decision: decision.kind === "none" ? null : {
            kind: decision.kind, price: decision.price, rule_id: decision.rule_id,
            citations: decision.citations, reasons: decision.reasons,
            requires_human_review: decision.requires_human_review,
          },
          reply_text: decision.reply_text,
          guardrail_hits: decision.guardrail || [],
          classification: decision.classification,
          trace: [],
        },
        { adopted: decision.adopted }
      );
    }
    return html;
  }).join("") + "</div>";
}

function mockThread() {
  const wb = state.wb;
  const conv = wb.conversations.find((c) => c.id === wb.activeConv);
  if (!conv || !conv._mockSteps) {
    return '<div class="empty">' + t("wb.openThread") + "</div>";
  }
  const personaName = wb.personaNames[conv.buyer_alias] || conv.buyer_alias;
  return '<div class="thread">' + conv._mockSteps.map((step) =>
    buyerBubble(step.persona_message, personaName) + suggestionCard(step, { match: true, readonlyNote: true })
  ).join("") + "</div>";
}

function itemCard() {
  const wb = state.wb;
  const activeItem = activeItemOf();
  const body = activeItem
    ? '<div style="font-weight:600;margin-bottom:6px">' + esc(activeItem.title) + "</div>" +
      '<div class="kv"><span>' + t("demo.asking") + '</span><span class="v">' + fmtMoney(activeItem.asking_price) + "</span></div>" +
      (IS_MOCK
        ? '<div class="kv"><span>' + t("wb.floor") + '</span><span class="v">' + fmtMoney(activeItem.floor_price) + "</span></div>"
        : floorSlider(activeItem))
    : '<div class="empty">' + t("wb.noItems") + "</div>";

  const newForm = wb.showNew
    ? '<div class="form-grid">' +
      '<input id="newTitle" placeholder="' + esc(t("wb.itemTitlePh")) + '"/>' +
      '<input id="newAsking" placeholder="' + esc(t("wb.askingPh")) + '" inputmode="decimal"/>' +
      '<input id="newFloor" placeholder="' + esc(t("wb.floorAuto")) + '" inputmode="decimal"/>' +
      '<button class="btn primary small" data-act="wb-create">' + t("wb.create") + "</button></div>"
    : "";

  return '<div class="pane"><div class="pane-head"><span>' + t("wb.items") + "</span>" +
    (IS_MOCK ? "" : '<button class="btn small" data-act="wb-new">' + t("wb.newItem") + "</button>") + "</div>" +
    '<div class="pane-body">' + body + newForm + "</div></div>";
}

function activeItemOf() {
  const wb = state.wb;
  if (wb.activeConv) {
    const conv = wb.conversations.find((c) => c.id === wb.activeConv);
    if (conv) return wb.items.find((i) => i.id === conv.item_id) || null;
  }
  return wb.items.find((i) => i.id === wb.chosenItem) || wb.items[0] || null;
}

function floorSlider(item) {
  const asking = parseFloat(item.asking_price);
  const floor = parseFloat(item.floor_price);
  const pct = Math.round((floor / asking) * 100);
  return (
    '<div class="slider-row"><div class="slider-label"><span>' + t("wb.floor") + '</span><span class="v" id="floorLabel">' + fmtMoney(item.floor_price) + " · " + pct + "%</span></div>" +
    '<input type="range" id="floorSlider" min="50" max="100" step="1" value="' + pct + '" data-asking="' + item.asking_price + '" data-item="' + item.id + '"/>' +
    '<div class="hint">' + t("wb.floorHint") + "</div></div>"
  );
}

function todayCard() {
  const report = state.wb.report || {};
  return '<div class="pane"><div class="pane-head"><span>' + t("wb.today") + "</span>" +
    '<button class="btn small" data-act="wb-report">' + t("report.title") + "</button></div>" +
    '<div class="pane-body"><div class="stat-grid">' +
    stat(report.inquiries, t("wb.statInquiries")) +
    stat(report.counters, t("wb.statCounters")) +
    stat(report.accepts, t("wb.statAccepts")) +
    stat(report.humans, t("wb.statHumans")) +
    "</div></div></div>";
}

function stat(n, label) {
  return '<div class="stat"><div class="n">' + (n == null ? 0 : n) + '</div><div class="l">' + esc(label) + "</div></div>";
}

function ledgerCard() {
  const entries = (state.wb.ledger || []).slice(-8).reverse();
  const rows = entries.map((entry) =>
    "<tr><td>" + (entry.kind === "none" ? "—" : '<span class="badge b-' + entry.kind + '">' + t("suggest." + entry.kind) + "</span>") + "</td>" +
    '<td class="num">' + (entry.price ? fmtMoney(entry.price) : "—") + "</td>" +
    '<td><span class="hint">' + esc(entry.rule_id || "") + "</span></td></tr>"
  ).join("");
  return '<div class="pane"><div class="pane-head"><span>' + t("wb.ledger") + "</span></div>" +
    '<div class="pane-body">' +
    (rows ? '<table class="ledger-table"><thead><tr><th></th><th style="text-align:right"></th><th></th></tr></thead><tbody>' + rows + "</tbody></table>"
          : '<div class="empty">' + t("wb.ledgerEmpty") + "</div>") +
    "</div></div>";
}

// ---- 工作台交互 ----

async function wbSuggest() {
  const wb = state.wb;
  const input = document.getElementById("pasteInput");
  const select = document.getElementById("itemSelect");
  const message = (input && input.value || "").trim();
  if (!message) return;
  const itemId = wb.activeConv
    ? (wb.conversations.find((c) => c.id === wb.activeConv) || {}).item_id
    : (select ? select.value : wb.chosenItem);
  if (!itemId) { toast(t("wb.noItems"), "bad"); return; }
  try {
    const result = await api.inquiry({
      item_id: itemId,
      message,
      conversation_id: wb.activeConv || null,
      source: "paste",
    });
    wb.pending = result;
    wb.activeConv = result.conversation_id;
    wb.editing = null;
    await reloadWb();
    wb.pending = result; // reloadWb 不碰 pending，但顺序上再钉一次
    drawWorkbench();
  } catch (error) {
    toastErr(error);
  }
}

async function wbAdopt(action) {
  const wb = state.wb;
  if (!wb.pending) return;
  if (action === "edited" && !wb.editing) {
    wb.editing = { text: wb.pending.reply_text };
    drawWorkbench();
    return;
  }
  try {
    await api.adopt(wb.pending.suggestion_id, action, wb.editing ? wb.editing.text : null);
    toast(t("wb.saved"), "ok");
    wb.pending = null;
    wb.editing = null;
    await reloadWb();
    drawWorkbench();
  } catch (error) {
    toastErr(error);
  }
}

async function wbCreateItem() {
  const title = (document.getElementById("newTitle") || {}).value || "";
  const asking = (document.getElementById("newAsking") || {}).value || "";
  const floor = ((document.getElementById("newFloor") || {}).value || "").trim();
  if (!title.trim() || !asking.trim()) { toast(t("wb.noItems"), "bad"); return; }
  try {
    const payload = { title: title.trim(), asking_price: asking.trim() };
    if (floor) payload.floor_price = floor;
    const created = await api.createItem(payload);
    state.wb.showNew = false;
    state.wb.chosenItem = created.item.id;
    await reloadWb();
    drawWorkbench();
    toast(t("wb.created"), "ok");
  } catch (error) {
    toastErr(error);
  }
}

async function wbOpenConversation(conversationId) {
  const wb = state.wb;
  wb.activeConv = conversationId;
  wb.pending = null;
  wb.editing = null;
  if (!IS_MOCK) {
    try { wb.thread = await api.conversation(conversationId); } catch (error) { toastErr(error); wb.thread = null; }
  }
  drawWorkbench();
}

async function wbSaveFloor(slider) {
  const asking = slider.dataset.asking;
  const itemId = slider.dataset.item;
  const floor = ((parseFloat(asking) * parseInt(slider.value, 10)) / 100).toFixed(2);
  try {
    await api.updateItem(itemId, { floor_price: floor });
    await reloadWb();
    drawWorkbench();
    toast(t("wb.saved") + " · " + fmtMoney(floor), "ok");
  } catch (error) {
    toastErr(error);
  }
}

// ---------------------------------------------------------------------------
// 定价
// ---------------------------------------------------------------------------

async function renderPricing(seq) {
  view.innerHTML = '<div class="loading">' + t("common.loading") + "</div>";
  let products;
  try {
    products = await api.payProducts();
  } catch (error) {
    if (stale(seq)) return;
    return renderErrorBox(error);
  }
  if (stale(seq)) return;
  view.innerHTML = '<div class="container">' + pricingBody(products) + "</div>";
}

function pricingBody(products) {
  const tiers = products.tiers || [];
  const early = tiers.find((tier) => tier.code === "pass30_early") || { price: "6.9" };
  const regular = tiers.find((tier) => tier.code === "pass30") || { price: "9.9" };
  const free = products.free || { daily_suggestions: 10, max_items: 1 };

  return (
    '<h1 class="section-title">' + esc(t("pricing.title")) + "</h1>" +
    '<p class="section-sub">' + esc(t("pricing.sub", { early: fmtMoney(early.price), price: fmtMoney(regular.price) })) + "</p>" +
    '<div class="pricing-grid">' +
      '<div class="plan"><h3>' + esc(t("pricing.freeName")) + '</h3><div class="amount">' + esc(t("pricing.freePrice")) + "</div>" +
        "<ul><li>" + esc(t("pricing.freeF1", { n: free.daily_suggestions })) + "</li>" +
        "<li>" + esc(t("pricing.freeF2")) + "</li>" +
        "<li>" + esc(t("pricing.freeF3")) + "</li></ul>" +
        '<a class="btn" href="#/app">' + esc(t("nav.app")) + "</a></div>" +
      '<div class="plan featured"><span class="early">' + fmtMoney(early.price) + " EARLY</span>" +
        "<h3>" + esc(t("pricing.paidName")) + '</h3><div class="amount">' + fmtMoney(early.price) +
        ' <small class="strike">' + fmtMoney(regular.price) + "</small></div>" +
        "<ul><li>" + esc(t("pricing.paidF1")) + "</li>" +
        "<li>" + esc(t("pricing.paidF2", { n: 50 })) + "</li>" +
        "<li>" + esc(t("pricing.paidF3")) + "</li>" +
        "<li>" + esc(t("pricing.paidF4")) + "</li></ul>" +
        '<button class="btn primary" data-act="buy" data-code="pass30_early">' + esc(t("pricing.buy")) + "</button></div>" +
    "</div>" +
    '<p class="hint" style="margin-top:16px">' + esc(t("pricing.quotaNote")) + "</p>"
  );
}

function openPricingModal() {
  api.payProducts()
    .then((products) => openModal(pricingBody(products)))
    .catch((error) => toastErr(error));
}

// ---------------------------------------------------------------------------
// 战报卡（16:9 可分享图；全部内联样式——SVG 序列化不会带样式表）
// ---------------------------------------------------------------------------

function aggregateSteps(steps) {
  let counters = 0, accepts = 0, humans = 0, firms = 0;
  for (const step of steps) {
    const kind = step.decision ? step.decision.kind : null;
    if (kind === "counter") counters += 1;
    else if (kind === "accept") accepts += 1;
    else if (kind === "human") humans += 1;
    else if (kind === "firm") firms += 1;
  }
  return { inquiries: steps.length, counters, accepts, humans, firms, concessions: counters };
}

function buildReportCard(data) {
  const card = document.createElement("div");
  card.id = "reportCard";
  card.setAttribute("style",
    "width:640px;height:360px;box-sizing:border-box;background:#FFFFFF;border-radius:16px;padding:34px 40px;" +
    'font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;color:#1C1917;' +
    "display:flex;flex-direction:column;justify-content:space-between");
  const big = "font-family:ui-monospace,Consolas,monospace;font-weight:700;font-variant-numeric:tabular-nums";
  card.innerHTML =
    '<div style="display:flex;align-items:center;gap:10px">' +
      '<span style="width:30px;height:30px;border-radius:8px;background:#1677FF;color:#fff;display:flex;align-items:center;justify-content:center;font-size:16px">谱</span>' +
      '<span style="font-weight:600;font-size:15px">' + (state.lang === "en" ? "YouPu Clerk" : "有谱掌柜") + "</span>" +
      '<span style="margin-left:auto;color:#A8A29E;font-size:12px">' + esc(data.day || new Date().toISOString().slice(0, 10)) + "</span>" +
    "</div>" +
    "<div>" +
      '<div style="font-size:30px;font-weight:700;letter-spacing:-.01em">' +
        '<span style="' + big + ';color:#1677FF;font-size:44px">' + data.concessions + "</span> " + esc(t("report.concessions")) +
        ' · <span style="color:#16A34A">' + esc(t("report.inAuth")) + "</span></div>" +
      '<div style="display:flex;gap:36px;margin-top:18px">' +
        reportStat(data.inquiries, t("report.inquiries"), big) +
        reportStat(data.accepts, t("report.accepts"), big) +
        reportStat(data.counters, t("report.counters"), big) +
        reportStat(data.audited == null ? data.inquiries : data.audited, t("report.audited"), big) +
      "</div>" +
    "</div>" +
    '<div style="color:#78716C;font-size:12.5px;border-top:1px solid #E7E5E4;padding-top:14px">' +
      esc(t("report.tagline")) + "</div>";
  return card;
}

function reportStat(n, label, big) {
  return '<div><div style="' + big + ';font-size:26px">' + (n == null ? 0 : n) + "</div>" +
    '<div style="color:#78716C;font-size:12px;margin-top:2px">' + esc(label) + "</div></div>";
}

function openReportModal(data) {
  openModal(
    "<h3 style=\"margin:0 0 16px\">" + esc(t("report.title")) + "</h3>" +
    '<div id="reportHost" style="display:flex;justify-content:center;overflow:auto"></div>' +
    '<div style="display:flex;gap:10px;justify-content:center;margin-top:16px">' +
    '<button class="btn primary" data-act="card-download">' + esc(t("report.download")) + "</button></div>" +
    '<p class="hint" style="text-align:center">' + esc(t("report.downloadHint")) + "</p>"
  );
  const host = document.getElementById("reportHost");
  if (host) host.appendChild(buildReportCard(data));
}

async function downloadReportCard() {
  const node = document.getElementById("reportCard");
  if (!node) return;
  try {
    const clone = node.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
    const xml = new XMLSerializer().serializeToString(clone);
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">' +
      '<foreignObject width="100%" height="100%">' + xml + "</foreignObject></svg>";
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
    const img = new Image();
    await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = reject; img.src = url; });
    const canvas = document.createElement("canvas");
    canvas.width = 1280; canvas.height = 720;
    const ctx = canvas.getContext("2d");
    ctx.scale(2, 2);
    ctx.drawImage(img, 0, 0);
    URL.revokeObjectURL(url);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "youpu-report-" + new Date().toISOString().slice(0, 10) + ".png";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast(t("report.downloaded"), "ok");
  } catch (error) {
    toast(t("report.downloadHint"), "bad");
  }
}

// ---------------------------------------------------------------------------
// 全局事件委托
// ---------------------------------------------------------------------------

document.addEventListener("click", async (event) => {
  const langButton = event.target.closest("#langSwitch button");
  if (langButton) {
    state.lang = langButton.dataset.lang;
    localStorage.setItem("clerk.lang", state.lang);
    state.demo = null; state.wb = null; // 语言切换后重拉数据（人设名等随语言变）
    render();
    return;
  }
  if (event.target.closest('[data-stop="1"]') && !event.target.closest("[data-act]")) return;

  const actor = event.target.closest("[data-act]");
  if (!actor) return;
  const act = actor.dataset.act;

  if (act === "modal-close") { closeModal(); return; }
  if (act === "retry") { render(); return; }

  if (act === "pick") {
    state.demo = Object.assign({}, state.demo, { pid: actor.dataset.pid, conv: null, steps: [], busy: false });
    renderPlayer();
    return;
  }
  if (act === "demo-back") {
    // 必须显式重渲染：已经在 #/demo 上，点同 hash 链接不会触发 hashchange
    state.demo.pid = null;
    renderPersonaGrid();
    return;
  }
  if (act === "demo-next") { demoNext(); return; }
  if (act === "demo-restart") {
    state.demo = Object.assign({}, state.demo, { conv: null, steps: [], busy: false });
    renderPlayer();
    return;
  }
  if (act === "demo-report") {
    openReportModal(Object.assign(aggregateSteps(state.demo.steps), { day: "" }));
    return;
  }
  if (act === "adopt") { wbAdopt(actor.dataset.a); return; }
  if (act === "edit-confirm") {
    const textarea = document.getElementById("editText");
    if (state.wb.editing && textarea) state.wb.editing.text = textarea.value;
    wbAdopt("edited");
    return;
  }
  if (act === "edit-cancel") { state.wb.editing = null; drawWorkbench(); return; }
  if (act === "wb-suggest") { wbSuggest(); return; }
  if (act === "wb-newchat") {
    state.wb.activeConv = null; state.wb.thread = null; state.wb.pending = null;
    drawWorkbench();
    return;
  }
  if (act === "wb-conv") { wbOpenConversation(actor.dataset.id); return; }
  if (act === "wb-new") { state.wb.showNew = !state.wb.showNew; drawWorkbench(); return; }
  if (act === "wb-create") { wbCreateItem(); return; }
  if (act === "wb-report") {
    const report = state.wb.report || {};
    openReportModal({
      day: report.day,
      inquiries: report.inquiries || 0,
      accepts: report.accepts || 0,
      counters: report.counters || 0,
      concessions: report.concessions_adopted || 0,
      audited: report.inquiries || 0,
    });
    return;
  }
  if (act === "buy") { buyFlow(actor.dataset.code || "pass30_early"); return; }
  if (act === "pay-sim") { paySimulate(actor.dataset.no, actor.dataset.amount); return; }
  if (act === "card-download") { downloadReportCard(); return; }
});

async function buyFlow(productCode) {
  try {
    const result = await api.payOrder(productCode);
    const payment = result.payment || {};
    const orderNo = result.order.out_trade_no;

    // 真实通道：打开支付宝收银台（推荐 POST 表单；GET 链接兜底），然后轮询确认
    if (payment.form_html) {
      const win = window.open("", "_blank");
      if (win) {
        win.document.write(payment.form_html);
        win.document.close();
      }
      closeModal();
      toast(t("pricing.payOpened"));
      rememberPendingOrder(orderNo);
      return;
    }
    if (payment.pay_url) {
      window.open(payment.pay_url, "_blank");
      closeModal();
      toast(t("pricing.payOpened"));
      rememberPendingOrder(orderNo);
      return;
    }

    // 未接入/dev：诚实展示通道状态；dev 环境给模拟支付按钮
    openModal(
      "<h3 style=\"margin:0 0 14px\">" + esc(t("pricing.orderCreated")) + "</h3>" +
      '<div class="kv"><span>' + esc(t("pricing.orderNo")) + '</span><span class="v" style="font-family:var(--font-num)">' + esc(orderNo) + "</span></div>" +
      '<div class="kv"><span>' + esc(t("pricing.amount")) + '</span><span class="v" style="font-family:var(--font-num)">' + fmtMoney(result.order.amount) + "</span></div>" +
      '<p class="hint" style="margin:12px 0">' + esc(payment.instructions || t("pricing.channelPending")) + "</p>" +
      (payment.dev
        ? '<button class="btn primary" data-act="pay-sim" data-no="' + esc(orderNo) + '" data-amount="' + esc(result.order.amount) + '">' + esc(t("pricing.simulate")) + "</button>"
        : "")
    );
  } catch (error) {
    toastErr(error);
  }
}

// ---- 支付结果轮询：同步跳转不可信，权益以 notify/query 为准（文档纪律）----

let payPollTimer = null;

function rememberPendingOrder(orderNo) {
  localStorage.setItem("clerk.pendingOrder", orderNo);
  startPayPolling(orderNo);
}

function startPayPolling(orderNo, attempts) {
  stopPayPolling();
  let tries = 0;
  const maxTries = attempts || 40; // 40 × 3s = 2 分钟，覆盖收银台停留时间
  payPollTimer = setInterval(async () => {
    tries += 1;
    try {
      const result = await api.payQuery(orderNo);
      if (result.order && result.order.status === "paid") {
        stopPayPolling();
        localStorage.removeItem("clerk.pendingOrder");
        toast(t("pricing.paidOk"), "ok");
        state.wb = null;
        render();
        return;
      }
    } catch (error) {
      // 网络抖动继续轮询；额度/权限类错误不值得轮下去
      if (error && error.status && error.status !== 400) {
        stopPayPolling();
        localStorage.removeItem("clerk.pendingOrder");
      }
    }
    if (tries >= maxTries) {
      stopPayPolling();
      localStorage.removeItem("clerk.pendingOrder");
    }
  }, 3000);
}

function stopPayPolling() {
  if (payPollTimer) {
    clearInterval(payPollTimer);
    payPollTimer = null;
  }
}

async function paySimulate(outTradeNo, amount) {
  try {
    await api.payNotifyDev(outTradeNo, amount);
    closeModal();
    toast(t("pricing.paidOk"), "ok");
    state.wb = null; // 权益变了：工作台状态整体重拉
    render();
  } catch (error) {
    toastErr(error);
  }
}

document.addEventListener("input", (event) => {
  if (event.target.id === "floorSlider") {
    const asking = parseFloat(event.target.dataset.asking);
    const floor = ((asking * parseInt(event.target.value, 10)) / 100).toFixed(2);
    const label = document.getElementById("floorLabel");
    if (label) label.textContent = fmtMoney(floor) + " · " + event.target.value + "%";
  }
  if (event.target.id === "editText" && state.wb && state.wb.editing) {
    state.wb.editing.text = event.target.value;
  }
});

document.addEventListener("change", (event) => {
  if (event.target.id === "floorSlider") { wbSaveFloor(event.target); return; }
  if (event.target.id === "itemSelect") { state.wb.chosenItem = event.target.value; }
});

window.addEventListener("hashchange", () => render());

// 从支付宝收银台回跳/刷新页面后，接着确认上一笔待支付订单
if (!IS_MOCK) {
  const pendingOrder = localStorage.getItem("clerk.pendingOrder");
  if (pendingOrder) startPayPolling(pendingOrder, 10);
}

render();
