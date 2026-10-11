// Pure choreography: for every cube i and time t → position, orientation, scale, glow.
// No Math.random / Date: everything is a function of (cues, t), so any frame renders identically.
import { layoutWord, layoutMark } from "./glyphs.js";

export function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
export const ease = {
  inOut3: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  inOut4: (p) => (p < 0.5 ? 8 * p * p * p * p : 1 - Math.pow(-2 * p + 2, 4) / 2),
  out3: (p) => 1 - Math.pow(1 - p, 3),
  out5: (p) => 1 - Math.pow(1 - p, 5),
  in2: (p) => p * p,
  smooth: (p) => p * p * (3 - 2 * p),
};

// ---- tiny quaternion helpers (x,y,z,w) ----
const qAxis = (ax, ay, az, ang, o) => {
  const s = Math.sin(ang / 2); o[0] = ax * s; o[1] = ay * s; o[2] = az * s; o[3] = Math.cos(ang / 2); return o;
};
const qSlerp = (a, b, t, o) => {
  let cos = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
  let bx = b[0], by = b[1], bz = b[2], bw = b[3];
  if (cos < 0) { cos = -cos; bx = -bx; by = -by; bz = -bz; bw = -bw; }
  let k0, k1;
  if (cos > 0.9995) { k0 = 1 - t; k1 = t; }
  else { const th = Math.acos(cos), s = Math.sin(th); k0 = Math.sin((1 - t) * th) / s; k1 = Math.sin(t * th) / s; }
  o[0] = k0 * a[0] + k1 * bx; o[1] = k0 * a[1] + k1 * by; o[2] = k0 * a[2] + k1 * bz; o[3] = k0 * a[3] + k1 * bw;
  const n = Math.hypot(o[0], o[1], o[2], o[3]); o[0] /= n; o[1] /= n; o[2] /= n; o[3] /= n; return o;
};
const qMul = (a, b, o) => {
  const ax = a[0], ay = a[1], az = a[2], aw = a[3], bx = b[0], by = b[1], bz = b[2], bw = b[3];
  o[0] = aw * bx + ax * bw + ay * bz - az * by; o[1] = aw * by - ax * bz + ay * bw + az * bx;
  o[2] = aw * bz + ax * by - ay * bx + az * bw; o[3] = aw * bw - ax * bx - ay * by - az * bz; return o;
};
const QI = [0, 0, 0, 1];
const heroA = [0, 0, 0, 1], heroB = [0, 0, 0, 1], heroC = [0, 0, 0, 1];

export function buildPlan(cues) {
  const rng = mulberry32(cues.seed);
  const mark = layoutMark(cues.markGrid);
  const N = mark.cells.length;
  const words = {
    idea: layoutWord(cues.text.idea),
    team: layoutWord(cues.text.team),
    agent: layoutWord(cues.text.agent),
  };
  const T = cues.T;

  // ---- constellation: dark glass debris floating behind the stage ----
  const cubes = [];
  for (let i = 0; i < N; i++) {
    const ang = rng() * Math.PI * 2;
    const ax = rng() - 0.5, ay = rng() - 0.5, az = rng() - 0.5, al = Math.hypot(ax, ay, az) || 1;
    cubes.push({
      i,
      cx: (rng() * 2 - 1) * 40, cy: (rng() * 2 - 1) * 22, cz: -(7 + rng() * 40),
      size: 0.55 + rng() * 1.5,
      tAxis: [ax / al, ay / al, az / al], tW: (rng() < 0.5 ? -1 : 1) * (0.12 + rng() * 0.35), tPhi: ang,
      dA: 0.4 + rng() * 0.9, dW: 0.25 + rng() * 0.4, dP: [rng() * 6.28, rng() * 6.28, rng() * 6.28],
      flipAxis: [[1, 0, 0], [0, 1, 0], [0, 0, 1]][(rng() * 3) | 0], flipSteps: (rng() < 0.5 ? -1 : 1) * (2 + ((rng() * 3) | 0)),
      arc: 5 + rng() * 8, side: (rng() * 2 - 1),
      legs: [], hero: false,
    });
  }
  const constPos = (c, t, o) => {
    o[0] = c.cx + c.dA * Math.sin(c.dW * t + c.dP[0]);
    o[1] = c.cy + c.dA * Math.sin(c.dW * 1.3 * t + c.dP[1]);
    o[2] = c.cz + c.dA * Math.sin(c.dW * 0.8 * t + c.dP[2]);
    return o;
  };
  const constQuat = (c, t, o) => qAxis(c.tAxis[0], c.tAxis[1], c.tAxis[2], c.tW * t + c.tPhi, o);

  // ---- assign cubes to slots, word by word ----
  const stages = [
    { name: "idea", cells: words.idea.cells, ...T.idea, order: "x", color: "sky" },
    { name: "team", cells: words.team.cells, ...T.team, order: "x", color: "blue" },
    { name: "agent", cells: words.agent.cells, ...T.agent, order: "x", color: "cyan" },
    { name: "mark", cells: mark.cells, ...T.mark, order: "outer", color: "blue" },
  ];
  const byXY = (a, b) => a.x - b.x || b.y - a.y;
  let active = []; // [{cube, cell}] sorted by x
  const pool = () => cubes.filter((c) => !active.some((a) => a.cube === c));

  stages.forEach((st, si) => {
    const slots = st.cells.slice().sort(byXY);
    const n = slots.length;
    const next = [];
    const retire = [];
    if (si === 0) {
      // hero cube: the slot nearest the centre of the word; it is already lit on frame 0
      let best = 0, bd = 1e9;
      slots.forEach((s, k) => { const d = Math.hypot(s.x - 0.5, s.y); if (d < bd) { bd = d; best = k; } });
      cubes[0].hero = true;
      const rest = cubes.slice(1);
      // random-ish but deterministic pool order
      const perm = rest.map((c) => [rng(), c]).sort((a, b) => a[0] - b[0]).map((p) => p[1]);
      const others = slots.filter((_, k) => k !== best);
      const chosen = perm.slice(0, others.length).sort((a, b) => a.cx - b.cx);
      next.push({ cube: cubes[0], cell: slots[best], fresh: false });
      others.forEach((cell, k) => next.push({ cube: chosen[k], cell, fresh: true }));
    } else {
      const A = active.slice().sort((a, b) => byXY(a.cell, b.cell));
      if (A.length >= n) {
        const used = new Set();
        slots.forEach((cell, k) => { const idx = Math.min(A.length - 1, Math.floor((k + 0.5) * A.length / n)); used.add(idx); next.push({ cube: A[idx].cube, cell, fresh: false }); });
        A.forEach((a, idx) => { if (!used.has(idx)) retire.push(a.cube); });
      } else {
        const m = n - A.length;
        const taken = new Set();
        const slotForA = [];
        A.forEach((a, k) => { const idx = Math.min(n - 1, Math.floor((k + 0.5) * n / A.length)); slotForA.push(idx); taken.add(idx); });
        const freeSlots = slots.map((s, k) => ({ s, k })).filter((o) => !taken.has(o.k));
        const pl = pool().map((c) => [rng(), c]).sort((a, b) => a[0] - b[0]).map((p) => p[1]).slice(0, m).sort((a, b) => a.cx - b.cx);
        A.forEach((a, k) => next.push({ cube: a.cube, cell: slots[slotForA[k]], fresh: false }));
        freeSlots.forEach((o, k) => next.push({ cube: pl[k], cell: o.s, fresh: true }));
      }
    }
    // departure order key → u ∈ [0,1]
    let keys;
    if (st.order === "outer") {
      keys = next.map((o) => -Math.hypot(o.cell.x, o.cell.y));
    } else keys = next.map((o) => o.cell.x + (rng() - 0.5) * 2.2);
    const sorted = keys.map((k, idx) => [k, idx]).sort((a, b) => a[0] - b[0]);
    const rank = new Array(next.length);
    sorted.forEach(([, idx], r) => { rank[idx] = r / Math.max(1, next.length - 1); });
    const window_ = Math.max(0, st.t1 - st.t0 - st.dur);
    next.forEach((o, k) => {
      const c = o.cube;
      const s = st.t0 + window_ * rank[k];
      const dur = st.dur * (0.9 + rng() * 0.25);
      const prev = c.legs.length ? c.legs[c.legs.length - 1].to : null;
      c.legs.push({ s: c.hero && si === 0 ? -10 : s, d: c.hero && si === 0 ? 0.01 : dur, from: prev || { kind: "const" }, to: { kind: "slot", cell: o.cell, stage: st.name, color: st.color, si }, fresh: o.fresh });
    });
    retire.forEach((c) => {
      const s = st.t0 + rng() * (st.t1 - st.t0) * 0.7;
      c.legs.push({ s, d: 1.3 + rng() * 0.5, from: c.legs[c.legs.length - 1].to, to: { kind: "const", si } });
    });
    active = next.map((o) => ({ cube: o.cube, cell: o.cell }));
  });

  const R = Math.hypot(8, 8);
  const colors = {
    sky: [0.0, 0.34, 1.0], blue: [0.0, 0.32, 0.87], cyan: [0.0, 0.46, 1.0], white: [1, 1, 1],
  };

  // wall (mark) transform over time: sits centred, then glides left and shrinks into the lockup
  const wall = (t, o) => {
    const [a, b] = T.lockMove;
    const p = ease.inOut4(clamp01((t - a) / (b - a)));
    o.x = cues.lockup.wallX * p; o.y = cues.lockup.wallY * p; o.s = 1 + (cues.lockup.wallS - 1) * p;
    o.flat = ease.smooth(clamp01((t - a - 0.15) / (b - a)));
    return o;
  };

  const tmpA = [0, 0, 0], tmpB = [0, 0, 0], tmpQ = [0, 0, 0, 1], tmpQ2 = [0, 0, 0, 1], W = { x: 0, y: 0, s: 1, flat: 0 };
  const slotPos = (to, t, o) => {
    wall(t, W);
    if (to.stage === "mark") { o[0] = to.cell.x * W.s + W.x; o[1] = to.cell.y * W.s + W.y; o[2] = 0; }
    else { o[0] = to.cell.x; o[1] = to.cell.y; o[2] = 0; }
    return o;
  };

  // cue times for the climax (hit) kick
  const HIT = T.hit;

  function state(c, t, out) {
    // find phase
    let leg = null, restTo = null, prevTo = null;
    for (let k = 0; k < c.legs.length; k++) {
      const L = c.legs[k];
      if (t < L.s) { restTo = L.from; break; }
      if (t < L.s + L.d) { leg = L; break; }
      prevTo = L.to;
      restTo = L.to;
    }
    if (!leg && restTo === null) restTo = prevTo || { kind: "const" };
    let x, y, z, sc = 1, glow = 0.03, white = 0, tint = colors.blue, stage = -1, tl = -1, r = 0;
    const q = out.q;
    if (leg) {
      const p = clamp01((t - leg.s) / leg.d), e = ease.inOut4(p);
      const A = leg.from, B = leg.to;
      // from
      if (A.kind === "const") constPos(c, leg.s, tmpA); else slotPos(A, leg.s, tmpA);
      if (B.kind === "const") constPos(c, leg.s + leg.d, tmpB); else slotPos(B, t, tmpB);
      const arc = Math.sin(Math.PI * p);
      x = tmpA[0] + (tmpB[0] - tmpA[0]) * e + c.side * c.arc * 0.55 * arc;
      y = tmpA[1] + (tmpB[1] - tmpA[1]) * e + (c.side * 0.6) * c.arc * 0.3 * arc;
      z = tmpA[2] + (tmpB[2] - tmpA[2]) * e + c.arc * 0.22 * arc;
      const sA = A.kind === "const" ? c.size : 1, sB = B.kind === "const" ? c.size : 1;
      sc = (sA + (sB - sA) * e) * (1 + 0.18 * arc);
      // orientation
      if (A.kind === "const") constQuat(c, leg.s, tmpQ); else { tmpQ[0] = 0; tmpQ[1] = 0; tmpQ[2] = 0; tmpQ[3] = 1; }
      if (B.kind === "const") { constQuat(c, leg.s + leg.d, tmpQ2); qSlerp(tmpQ, tmpQ2, e, q); }
      else if (A.kind === "const") qSlerp(tmpQ, QI, e, q);
      else qAxis(c.flipAxis[0], c.flipAxis[1], c.flipAxis[2], (Math.PI / 2) * c.flipSteps * e, q);
      const colB = B.kind === "slot" ? colors[B.color] : colors.blue;
      const colA = A.kind === "slot" ? colors[A.color] : colors.blue;
      tint = [colA[0] + (colB[0] - colA[0]) * e, colA[1] + (colB[1] - colA[1]) * e, colA[2] + (colB[2] - colA[2]) * e];
      const toLit = B.kind === "slot" ? 1 : 0, fromLit = A.kind === "slot" ? 1 : 0;
      glow = 0.1 + 0.5 * arc + (fromLit + (toLit - fromLit) * e) * 0.55;
      white = 0.0;
    } else if (restTo.kind === "const") {
      constPos(c, t, tmpA); x = tmpA[0]; y = tmpA[1]; z = tmpA[2]; sc = c.size; constQuat(c, t, q);
      glow = 0.03; tint = colors.blue;
    } else {
      slotPos(restTo, t, tmpA); x = tmpA[0]; y = tmpA[1]; z = 0; sc = 1; q[0] = 0; q[1] = 0; q[2] = 0; q[3] = 1;
      // landing time of this slot
      const L = c.legs.find((l) => l.to === restTo);
      tl = L.s + L.d;
      const tau = t - tl;
      const col = colors[restTo.color];
      tint = col; stage = restTo.si;
      const brea = 0.92 + 0.08 * Math.sin(6.2832 * 0.55 * t + (restTo.cell.col || 0) * 0.45);
      glow = 1.15 * brea;
      if (tau >= 0 && tau < 1.2) {
        const f = Math.exp(-tau * 8.5);
        glow += 1.1 * f; white = Math.min(1, 0.45 * f);
        z += 0.34 * Math.exp(-tau * 11) * Math.sin(tau * 26);
      }
      if (c.hero && t < 1.2) {
        // the idea starts as one tilted glass cube and squares up as the word forms around it
        qAxis(0, 1, 0, 0.72 + 0.35 * t, heroA); qAxis(1, 0, 0, 0.42 - 0.12 * t, heroB); qMul(heroB, heroA, heroC);
        const k = ease.inOut3(clamp01((t - 0.55) / 0.7));
        qSlerp(heroC, QI, k, q);
        glow = 1.15 + 0.25 * Math.sin(t * 7.0) * (1 - k); white = 0;
        tint = colors.cyan;
      }
    }
    // ---- mark: inhale / hit / settle ----
    if (!leg && restTo.kind === "slot" && restTo.stage === "mark") {
      wall(t, W);
      const rr = Math.hypot(restTo.cell.x, restTo.cell.y);
      const [i0, i1] = T.inhale;
      if (t >= i0 && t < HIT) { const p = ease.smooth(clamp01((t - i0) / (i1 - i0))); glow *= 1 - 0.5 * p; sc *= 1 - 0.05 * p; z -= 0.6 * p; }
      if (t >= HIT) {
        // the wall dims for the first instants so the light bursting through the carved figure is the brightest thing on screen,
        // then a ripple (delayed by distance from the centre) lifts every cube toward the camera and lights it
        const dip = 1 - 0.45 * Math.exp(-(t - HIT) * 9);
        glow *= dip;
        const tau = t - HIT - rr * 0.016;
        if (tau > 0) {
          const f = Math.exp(-tau * 4.0);
          glow += 0.35 * f * Math.min(1, tau * 12);
          z += 2.8 * Math.exp(-tau * 4.2) * Math.sin(tau * 10) * (1 - ease.smooth(clamp01((rr - 4.5) / 5.5)));   // the outer rim stays a straight square, the inside breathes
        }
        sc *= 1 + 0.05 * Math.exp(-(t - HIT) * 6);
        const flat = W.flat;
        out.sz = 1 - 0.88 * flat; sc *= 1 + 0.015 * flat; // gaps close, thickness drops → the flat brand mark
        glow = glow * (1 + 0.05 * flat);
      } else out.sz = 1;
    } else out.sz = 1;
    out.x = x; out.y = y; out.z = z; out.s = sc; out.glow = glow; out.white = white; out.tint = tint; out.stage = stage;
    return out;
  }

  return { cubes, N, words, mark, stages, state, wall, R, colors };
}

// landing events (for the sound track): [{stage, t, count}] on the sixteenth grid
export function landingEvents(cues) {
  const plan = buildPlan(cues);
  const bins = {};
  plan.cubes.forEach((c) => c.legs.forEach((l) => {
    if (l.to.kind !== "slot") return;
    const t = l.s + l.d;
    if (t < 0.05) return;
    const k = Math.round(t * 10) / 10; // 0.1 s grid
    const key = l.to.stage + ":" + k;
    bins[key] = bins[key] || { stage: l.to.stage, t: k, count: 0 };
    bins[key].count++;
  }));
  return Object.values(bins).sort((a, b) => a.t - b.t);
}
