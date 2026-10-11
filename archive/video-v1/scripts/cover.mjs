// Renders the full-resolution cover PNG (1920x1080) straight from the engine.
//   node scripts/cover.mjs [out.png]
import fs from "node:fs";
import { openEngine } from "./_harness.mjs";
const out = process.argv[2] || "renders/hackalem-intro-cover.png";
const { page, close } = await openEngine();
const data = await page.evaluate(() => { window.HK.renderCover(); return document.getElementById("stage").toDataURL("image/png"); });
fs.mkdirSync(out.includes("/") ? out.slice(0, out.lastIndexOf("/")) : ".", { recursive: true });
fs.writeFileSync(out, Buffer.from(data.split(",")[1], "base64"));
console.log("cover ->", out);
await close();
