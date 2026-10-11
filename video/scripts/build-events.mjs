// Choreography → sound cues: when cubes land (per 0.1 s bin), when letters pop, hit etc. Audio reads config/events.json.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import cues from "../config/cues.js";
import { landingEvents } from "../src/schedule.js";
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const land = landingEvents(cues);
const T = cues.T;
const titleChars = [...cues.text.titleA, ...cues.text.titleB].length;
const out = {
  landings: land,
  stages: Object.fromEntries(["idea", "team", "agent", "mark"].map((k) => [k, { t0: T[k].t0, t1: T[k].t1, dur: T[k].dur }])),
  hit: T.hit, inhale: T.inhale, lockMove: T.lockMove,
  letters: Array.from({ length: titleChars }, (_, i) => +(T.title[0] + i * 0.045 + 0.12).toFixed(3)),
  tagline: T.tagline, rule: T.rule,
};
fs.writeFileSync(path.join(root, "config/events.json"), JSON.stringify(out, null, 1));
console.log("events.json:", land.length, "landing bins,", out.letters.length, "letters");
