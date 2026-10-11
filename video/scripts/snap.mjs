// Render single frames straight from the engine (software WebGL, same flags as the HyperFrames capture) → PNG.
// usage: node scripts/snap.mjs outdir t1 t2 ...   (env SAMPLES=1 to force no sub-frame blur)
import fs from "node:fs";
import path from "node:path";
import { openEngine } from "./_harness.mjs";
const [out, ...times] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const { page, close } = await openEngine();
for (const t of times.map(Number)) {
  const t0 = Date.now();
  await page.evaluate(({ t, s }) => window.HK.renderAt(t, s ? { samples: s } : {}), { t, s: Number(process.env.SAMPLES) || 0 });
  const f = path.join(out, `t${t.toFixed(3).padStart(7, "0")}.png`);
  await page.screenshot({ path: f });
  console.log(f, Date.now() - t0, "ms");
}
await close();
