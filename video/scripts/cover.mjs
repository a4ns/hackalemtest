// Renders the full-resolution cover PNG straight from the engine.  node scripts/cover.mjs <out.png>
// (needs a static server on :8123: npx http-server . -p 8123)
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";
import fs from "node:fs";
const out = process.argv[2] || "renders/hackalem-intro-cover.png";
const b = await chromium.launch({ executablePath: process.env.CHROME || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args: ["--no-sandbox", "--force-color-profile=srgb"] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
await p.addInitScript(() => { window.__timelines = {}; });
await p.goto("http://localhost:8123/index.html");
await p.waitForFunction(() => window.HK && window.HK.ready === true, null, { timeout: 30000 });
const data = await p.evaluate(() => { window.HK.renderCover(); return document.getElementById("stage").toDataURL("image/png"); });
fs.writeFileSync(out, Buffer.from(data.split(",")[1], "base64"));
console.log("cover ->", out);
await b.close();
