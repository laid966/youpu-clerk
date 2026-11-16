// 扩展弹窗：配置工作台地址、选择当前商品、查看额度、同账户打开工作台。
// 弹窗文案量少，直接双语内联（不走网页端的字典体系，扩展保持零依赖）。

const IS_ZH = (navigator.language || "").toLowerCase().startsWith("zh");
const T = {
  saved: ["已保存", "Saved"],
  savedReload: ["已保存——去任意网页选中买家消息即可", "Saved — select any buyer message on any page"],
  loadFail: ["连不上工作台后端", "Cannot reach the workbench backend"],
  noItems: ["工作台里还没有商品档案，先去工作台创建", "No item profiles yet — create one in the workbench first"],
  quota: (used, limit) => `今日建议 ${used}/${limit}`,
  quotaEn: (used, limit) => `Suggestions today ${used}/${limit}`,
  pickItem: ["选择商品…", "Pick an item…"],
};
const t = (key) => (Array.isArray(T[key]) ? T[key][IS_ZH ? 0 : 1] : T[key]);

const apiBaseInput = document.getElementById("apiBase");
const itemSelect = document.getElementById("activeItem");
const statusEl = document.getElementById("status");
const quotaEl = document.getElementById("quota");

function setStatus(text, kind) {
  statusEl.textContent = text || "";
  statusEl.className = "status" + (kind ? " " + kind : "");
}

async function loadSettings() {
  const settings = await chrome.runtime.sendMessage({ type: "settings" });
  apiBaseInput.value = settings.apiBase;
  await loadItems(settings);
  loadEntitlements();
}

async function loadItems(settings) {
  const response = await chrome.runtime.sendMessage({ type: "items" });
  itemSelect.innerHTML = "";
  if (!response || response.error || !response.items) {
    itemSelect.appendChild(option("", t("loadFail")));
    setStatus(response && response.error === "NETWORK" ? t("loadFail") : "", "bad");
    return;
  }
  if (!response.items.length) {
    itemSelect.appendChild(option("", t("noItems")));
    return;
  }
  itemSelect.appendChild(option("", t("pickItem")));
  for (const item of response.items) {
    itemSelect.appendChild(option(item.id, `${item.title} · ¥${item.asking_price}`));
  }
  const active = (settings && settings.activeItem) || "";
  if (active && response.items.some((item) => item.id === active)) itemSelect.value = active;
}

function option(value, label) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = label;
  return node;
}

async function loadEntitlements() {
  const response = await chrome.runtime.sendMessage({ type: "entitlements" });
  if (response && response.quota) {
    quotaEl.textContent = IS_ZH
      ? T.quota(response.quota.used_today, response.quota.free_limit)
      : T.quotaEn(response.quota.used_today, response.quota.free_limit);
  } else {
    quotaEl.textContent = "";
  }
}

document.getElementById("save").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({
    type: "saveSettings",
    values: { apiBase: apiBaseInput.value.trim() || "http://127.0.0.1:8100", activeItem: itemSelect.value },
  });
  setStatus(itemSelect.value ? t("savedReload") : t("saved"), "ok");
  loadEntitlements();
});

document.getElementById("openWb").addEventListener("click", async () => {
  const settings = await chrome.runtime.sendMessage({ type: "settings" });
  const base = (apiBaseInput.value.trim() || settings.apiBase).replace(/\/$/, "");
  // 带上扩展的 token：网页端与扩展共用同一账户（商品/台账/额度不分裂）
  chrome.tabs.create({ url: base + "/?token=" + encodeURIComponent(settings.token) });
});

document.getElementById("reload").addEventListener("click", async () => {
  setStatus("");
  const settings = await chrome.runtime.sendMessage({ type: "settings" });
  await loadItems(settings);
  loadEntitlements();
});

// 页面诊断（G1）：在闲鱼网页版等目标页面上收集聊天 DOM 的候选结构。
// 只读、不碰消息内容；产物是给开发者判断"自动监听层"可行性的依据。
document.getElementById("diagnose").addEventListener("click", async () => {
  const out = document.getElementById("diagOut");
  const copyBtn = document.getElementById("diagCopy");
  out.style.display = "block";
  out.value = IS_ZH ? "采集中…" : "collecting…";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const info = await chrome.tabs.sendMessage(tab.id, { type: "youpu-diagnose" });
    out.value = JSON.stringify(info, null, 1);
    copyBtn.style.display = "inline-block";
  } catch (error) {
    out.value = (IS_ZH ? "采集失败：当前页面没有注入内容脚本（chrome:// 页或扩展商店页不行）。请先打开闲鱼网页版的聊天页面再点诊断。错误：" : "Diagnose failed: content script not injected on this page. Open the Xianyu web chat page first. Error: ") + error;
  }
});

document.getElementById("diagCopy").addEventListener("click", async () => {
  await navigator.clipboard.writeText(document.getElementById("diagOut").value);
  setStatus(IS_ZH ? "已复制——粘贴给开发者即可" : "Copied — paste it to the developer", "ok");
});

loadSettings();
