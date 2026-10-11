// Dev harness: render given times straight from the engine (no HyperFrames capture), save PNGs.
//   node scripts/snap.mjs <outDir> t1 t2 ...
import fs from "node:fs";
import { openEngine } from "./_harness.mjs";
const [outDir, ...ts] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const { page, close } = await openEngine();
for (const t of ts) {
  const t0 = Date.now();
  const data = await page.evaluate((t) => { window.HK.render(t); return document.getElementById("stage").toDataURL("image/png"); }, Number(t));
  fs.writeFileSync(`${outDir}/t${Number(t).toFixed(3).padStart(7, "0")}.png`, Buffer.from(data.split(",")[1], "base64"));
  console.log("t=" + t, Date.now() - t0 + "ms");
}
await close();
