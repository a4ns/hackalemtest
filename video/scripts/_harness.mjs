// Shared dev-harness helpers: tiny static server + Playwright launcher (no extra dependencies beyond `playwright`).
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".png": "image/png", ".wav": "audio/wav", ".mjs": "text/javascript", ".css": "text/css" };

export function startServer() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const p = path.join(ROOT, decodeURIComponent(req.url.split("?")[0]));
      if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "content-type": MIME[path.extname(p)] || "application/octet-stream" });
      fs.createReadStream(p).pipe(res);
    });
    srv.listen(0, "127.0.0.1", () => resolve({ srv, url: `http://127.0.0.1:${srv.address().port}/index.html` }));
  });
}

async function loadPlaywright() {
  try { return await import("playwright"); } catch {}
  const g = execSync("npm root -g").toString().trim();
  return await import(pathToFileURL(path.join(g, "playwright/index.mjs")).href);
}

export async function openEngine() {
  const { chromium } = await loadPlaywright();
  let exe = process.env.CHROME;
  if (!exe) { try { exe = execSync("npx --yes hyperframes@0.8.143 browser path 2>/dev/null").toString().trim().split("\n").pop(); } catch {} }
  const browser = await chromium.launch({ executablePath: exe || undefined, args: ["--no-sandbox", "--force-color-profile=srgb", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--enable-webgl"] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on("pageerror", (e) => console.log("[pageerror]", e.message)); page.on("console", (m) => { if (["error","warning"].includes(m.type())) console.log("[console]", m.text().slice(0, 300)); });
  await page.addInitScript(() => { window.__timelines = {}; });
  const { srv, url } = await startServer();
  await page.goto(url);
  await page.waitForFunction(() => window.HK && window.HK.ready === true, null, { timeout: 60000 });
  return { page, close: async () => { await browser.close(); srv.close(); } };
}
