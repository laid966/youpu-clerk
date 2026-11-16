// G1 页面诊断采集器：连调试端口，对闲鱼聊天页只采**结构信息**。
//
// 隐私红线：不采任何消息文本、不采输入框内容、不采 cookie/凭据。
// 产物只有：选择器命中数、DOM 形状树（tag+class+子节点数）、发送框候选、iframe 地址。
// 这些足以回答"自动监听层能不能做、选择器怎么写"，且不含对话内容。
//
// 用法：node tools/g1-diagnose.mjs [port=9222]
// 前置：诊断浏览器窗口（--remote-debugging-port=9222 拉起的那个）里已登录闲鱼并打开一个聊天。

const port = process.argv[2] || "9222";

const EXPR = `(() => {
  const sels = ["[class*='message']", "[class*='chat']", "[class*='im-']", "[class*='msg']",
                "[class*='session']", "[class*='conversation']", "iframe", "textarea", "[contenteditable='true']"];
  const candidates = {};
  for (const s of sels) { try { candidates[s] = document.querySelectorAll(s).length; } catch (e) { candidates[s] = -1; } }
  const clsOf = (el) => String(el && el.className ? (el.className.baseVal !== undefined ? el.className.baseVal : el.className) : "").slice(0, 100);
  const shape = (el, depth) => (!el || depth > 2) ? null : ({
    tag: el.tagName, cls: clsOf(el),
    kids: Array.from(el.children).slice(0, 6).map((c) => shape(c, depth + 1))
  });
  const first = document.querySelector("[class*='message'], [class*='chat'], [class*='msg']");
  const send = document.querySelector("textarea, [contenteditable='true']");
  return JSON.stringify({
    url: location.href,
    title: document.title,
    candidates,
    sampleTree: shape(first, 0),
    sendBox: send ? { tag: send.tagName, cls: clsOf(send), placeholder: String(send.getAttribute("placeholder") || "").slice(0, 60) } : null,
    iframeUrls: Array.from(document.querySelectorAll("iframe")).slice(0, 5).map((f) => String(f.src || "").slice(0, 120))
  });
})()`;

async function main() {
  const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const pages = list.filter((t) => t.type === "page");
  const page = pages.find((t) => /goofish\.com/.test(t.url));
  if (!page) {
    console.error("没找到闲鱼页面。当前打开的页面：");
    for (const p of pages) console.error("  -", p.url);
    console.error("请在诊断浏览器窗口里登录闲鱼并打开任意一个聊天，然后重跑本脚本。");
    process.exit(2);
  }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const timer = setTimeout(() => { console.error("CDP 10 秒无响应"); process.exit(3); }, 10000);

  ws.addEventListener("open", () => {
    ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: EXPR, returnByValue: true } }));
  });
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id !== 1) return;
    clearTimeout(timer);
    ws.close();
    if (msg.result && msg.result.exceptionDetails) {
      console.error("页面内执行异常：", JSON.stringify(msg.result.exceptionDetails).slice(0, 500));
      process.exit(4);
    }
    const value = msg.result && msg.result.result && msg.result.result.value;
    console.log(typeof value === "string" ? value : JSON.stringify(value));
    process.exit(0);
  });
  ws.addEventListener("error", (e) => { clearTimeout(timer); console.error("WebSocket 错误", e && e.message); process.exit(5); });
}

main().catch((err) => { console.error(err && err.message ? err.message : err); process.exit(1); });
