// 支付宝开放平台凭证只读提取（作者本机登录态，经 CDP）。
// 只读：抓 APPID / 支付宝公钥 / PID 三个展示值；不点击签约、不发起任何写操作。
// 用法：node tools/alipay-extract.mjs   （前置：隔离 Edge 实例已在 9223 监听）

const BASE = "http://127.0.0.1:9223";

async function tabs() {
  const r = await fetch(BASE + "/json/list");
  return r.json();
}

let id = 0;
function rpc(ws, method, params = {}) {
  return new Promise((resolve, reject) => {
    const my = ++id;
    const onMsg = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id === my) {
        ws.removeEventListener("message", onMsg);
        msg.error ? reject(new Error(method + ": " + JSON.stringify(msg.error))) : resolve(msg.result);
      }
    };
    ws.addEventListener("message", onMsg);
    ws.send(JSON.stringify({ id: my, method, params }));
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function evalJs(ws, expression) {
  const r = await rpc(ws, "Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails.exception || r.exceptionDetails));
  return r.result.value;
}

async function goto(ws, url) {
  await rpc(ws, "Page.enable");
  await rpc(ws, "Page.navigate", { url });
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    try {
      if ((await evalJs(ws, "document.readyState")) === "complete") break;
    } catch {}
  }
  await sleep(3000); // SPA 渲染余量
}

async function main() {
  const list = await tabs();
  const page = list.find((t) => t.type === "page") || list[0];
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });

  const out = {};

  await goto(ws, "https://open.alipay.com/develop/manage");
  let text = await evalJs(ws, "document.body.innerText");
  const digits = [...new Set(text.match(/\b20\d{14}\b/g) || [])];
  out.pid = digits.find((d) => d.startsWith("2088")) || null;
  out.appIdCandidates = digits.filter((d) => !d.startsWith("2088"));
  out.appLinks = await evalJs(
    ws,
    "JSON.stringify([...document.querySelectorAll('a[href]')].map(a=>a.href).filter(h=>/appId|appDetail/i.test(h)).slice(0,5))"
  );

  // 进应用详情 → 开发设置
  let detailUrl = null;
  try {
    const links = JSON.parse(out.appLinks);
    if (links.length) detailUrl = links[0];
  } catch {}
  if (!detailUrl && out.appIdCandidates.length) {
    detailUrl = "https://open.alipay.com/develop/manage/app/detail?appId=" + out.appIdCandidates[0];
  }
  if (detailUrl) {
    await goto(ws, detailUrl);
    text = await evalJs(ws, "document.body.innerText");
    const more = [...new Set(text.match(/\b20\d{14}\b/g) || [])];
    if (!out.pid) out.pid = more.find((d) => d.startsWith("2088")) || null;
    if (!out.appIdCandidates.length) out.appIdCandidates = more.filter((d) => !d.startsWith("2088"));

    await evalJs(
      ws,
      "(()=>{const el=[...document.querySelectorAll('*')].reverse().find(e=>e.children.length===0&&e.textContent.trim()==='开发设置');if(el){el.click();return 'clicked'}return 'notfound'})()"
    );
    await sleep(2500);
    text = await evalJs(ws, "document.body.innerText");
    out.alipayPublicKey =
      (text.match(/MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA[A-Za-z0-9+/=]+/) || [null])[0];
    if (!out.alipayPublicKey) {
      // 可能需要点"查看"展开
      await evalJs(
        ws,
        "(()=>{const els=[...document.querySelectorAll('button,span,a')].filter(e=>e.children.length===0&&e.textContent.trim()==='查看');els.forEach(e=>e.click());return els.length})()"
      );
      await sleep(2000);
      text = await evalJs(ws, "document.body.innerText");
      out.alipayPublicKey =
        (text.match(/MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA[A-Za-z0-9+/=]+/) || [null])[0];
    }
    out.devSettingsSnippet = text.split("\n").filter((l) => /公钥|加签|RSA/.test(l)).slice(0, 12);
  }

  if (!out.pid) {
    await goto(ws, "https://open.alipay.com/develop/manage");
    text = await evalJs(ws, "document.body.innerText");
    out.pid = ((text.match(/\b2088\d{12}\b/g) || [])[0]) || null;
  }

  console.log(JSON.stringify(out, null, 2));
  ws.close();
}

main().catch((e) => {
  console.error("EXTRACT FAIL:", e.message);
  process.exit(1);
});
