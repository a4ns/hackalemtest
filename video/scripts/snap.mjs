// Dev harness: render given times straight from the engine (no HyperFrames), save PNGs.
// node scripts/snap.mjs <outDir> t1 t2 ...   (needs a static server on :8123: npx http-server . -p 8123)
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";
import fs from "node:fs";
const [outDir, ...ts] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args: ["--no-sandbox", "--force-color-profile=srgb"] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
p.on("console", (m) => console.log("[page]", m.text()));
p.on("pageerror", (e) => console.log("[pageerror]", e.message));
await p.addInitScript(() => { window.__timelines = {}; });
await p.goto("http://localhost:8123/index.html");
await p.waitForFunction(() => window.HK && window.HK.ready === true, null, { timeout: 30000 });
for (const t of ts) {
  const t0 = Date.now();
  const data = await p.evaluate((t) => { window.HK.render(t); return document.getElementById("stage").toDataURL("image/png"); }, Number(t));
  fs.writeFileSync(`${outDir}/t${Number(t).toFixed(3).padStart(7, "0")}.png`, Buffer.from(data.split(",")[1], "base64"));
  console.log("t=" + t, (Date.now() - t0) + "ms");
}
await b.close();
