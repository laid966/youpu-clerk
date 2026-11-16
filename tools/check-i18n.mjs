// i18n 漂移检查器：双语产品的"静默失效"防线。
//
// 查两类事故（都是本项目最恨的"配置看着生效、实际永远缺失"家族）：
//   1. zh / en 字典键集合不一致（某语言漏键 → 用户看到裸 key 或另一种语言）
//   2. app.js 里字面量 t("a.b.c") 用了字典里不存在的键（拼写错 → 界面露 key）
// 动态拼接的键（t("suggest." + kind)）靠第 1 类检查兜底：家族键在两字典里必须齐。
//
// 用法：node tools/check-i18n.mjs   （退出码非 0 = 有漂移，可进 CI）

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import en from "../clerk/web/i18n/en.js";
import zh from "../clerk/web/i18n/zh.js";

const root = fileURLToPath(new URL("..", import.meta.url));
const src = readFileSync(root + "clerk/web/app.js", "utf8");

function flatten(obj, prefix = "") {
  return Object.entries(obj).flatMap(([key, value]) =>
    value && typeof value === "object"
      ? flatten(value, prefix + key + ".")
      : [prefix + key]
  );
}

const zhKeys = new Set(flatten(zh));
const enKeys = new Set(flatten(en));

let bad = 0;
for (const key of zhKeys) {
  if (!enKeys.has(key)) { console.log("en 缺键:", key); bad += 1; }
}
for (const key of enKeys) {
  if (!zhKeys.has(key)) { console.log("zh 缺键:", key); bad += 1; }
}

const literal = new Set();
const re = /\bt\("([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)"/g;
let match;
while ((match = re.exec(src)) !== null) literal.add(match[1]);
for (const key of literal) {
  if (!zhKeys.has(key)) { console.log("app.js 用了 zh 没有的键:", key); bad += 1; }
  if (!enKeys.has(key)) { console.log("app.js 用了 en 没有的键:", key); bad += 1; }
}

if (bad === 0) {
  console.log(`i18n OK：zh=${zhKeys.size} 键，en=${enKeys.size} 键，app.js 字面量引用 ${literal.size} 个，全部命中`);
} else {
  console.log(`i18n 漂移：${bad} 处`);
}
process.exit(bad === 0 ? 0 : 1);
