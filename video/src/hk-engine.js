/* HackAlem AI — intro. Canvas renderer: drawFrame(t) is a pure function of time.
 * Idea ("Resolution"): one lattice, everything changes in 3-frame steps (1/16 note @150 BPM).
 * All timings come from config/cues.js (generated from config/cues.json).
 */
(function () {
  "use strict";

  const CUES = window.HK_CUES;
  const T = CUES.T;
  const PAL = CUES.palette;
  const TXT = CUES.text;
  const GRID = window.HK_MARK_GRID; // 16 rows of 16 (1 = brand-blue cell)
  const FPS = CUES.meta.fps;
  const W = 1920, H = 1080, CX = 960, CY = 540;
  const STEP = 0.1; // 3 frames @30fps = a 16th note @150 BPM
  const EPS = 1e-6;

  // ───────────────────────── helpers ─────────────────────────
  const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
  const lerp = (a, b, t) => a + (b - a) * t;
  const inv = (a, b, x) => clamp((x - a) / (b - a));
  const smooth = (a, b, x) => { const t = inv(a, b, x); return t * t * (3 - 2 * t); };
  const eOutExpo = (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
  const eOutCubic = (t) => 1 - Math.pow(1 - t, 3);
  const eInOutCubic = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const eInOutSine = (t) => -(Math.cos(Math.PI * t) - 1) / 2;
  const quant = (t, q = STEP) => Math.floor(t / q + EPS) * q;
  const frameOf = (t) => Math.floor(t * FPS + EPS);
  const hash = (a, b = 0, c = 0) => {
    let h = (Math.imul(a | 0, 374761393) + Math.imul(b | 0, 668265263) + Math.imul(c | 0, 1274126177)) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  };
  const hex = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
  const rgba = (c, a = 1) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
  const mix = (a, b, t) => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
  const C = {};
  Object.keys(PAL).forEach((k) => (C[k] = hex(PAL[k])));
  const WHITE = [255, 255, 255];

  // decaying pulse train (sum of exponentials after each beat in `list`)
  const pulse = (t, list, decay = 0.12) => {
    let p = 0;
    for (let i = 0; i < list.length; i++) {
      const d = t - list[i];
      if (d >= 0 && d < decay * 6) p += Math.exp(-d / decay);
    }
    return Math.min(1.4, p);
  };

  // ───────────────────────── canvases ─────────────────────────
  const mk = (w = W, h = H) => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };
  const stage = document.getElementById("stage");
  const out = stage.getContext("2d");
  const wallC = mk(), wallX = wallC.getContext("2d");
  const maskC = mk(), maskX = maskC.getContext("2d");
  const sceneC = mk(), sceneX = sceneC.getContext("2d");
  const frameC = mk(), frameX = frameC.getContext("2d");
  const accC = mk(), accX = accC.getContext("2d");
  const haloC = mk(480, 270), haloX = haloC.getContext("2d");
  const bloomA = mk(480, 270), bloomAx = bloomA.getContext("2d");
  const bloomB = mk(120, 68), bloomBx = bloomB.getContext("2d");

  // ───────────────────────── assets / init ─────────────────────────
  const WORDS = {}; // key -> {crisp, pix:{res:canvas}, l, r, top, bottom, mid, letters:[{x0,x1,cx}], font}
  let logoImg = null, logoC = null, wmCov = null;

  // Lockup geometry (original logo.svg 3777×570, scaled by K)
  const K = 0.38;
  const LOGO_W = 3777 * K, LOGO_H = 570 * K;
  const LOGO_X = (W - LOGO_W) / 2;
  const LOGO_Y = 362;
  const MARK_PX = 570 * K;
  const MARK_CX = LOGO_X + 285 * K, MARK_CY = LOGO_Y + 285 * K;
  const S_LOCK = MARK_PX / 960;
  const WM_U = 60, WM_X0 = 711, WM_BASE = 482.5; // wordmark pixel unit (stroke) and origin in svg units
  const DOT = { x: 3240.5, y: 423.124, s: 60 };

  const FONT_DISPLAY = '800 100px "Manrope"';
  const MONO = '"JetBrains Mono"';

  function prepWord(key, text, targetW, trackEm, dy) {
    const x = document.createElement("canvas"); x.width = W; x.height = H;
    const g = x.getContext("2d");
    g.font = FONT_DISPLAY;
    g.letterSpacing = trackEm * 100 + "px";
    const w100 = g.measureText(text).width - trackEm * 100;
    const size = (targetW / w100) * 100;
    const sp = trackEm * size;
    g.font = `800 ${size}px "Manrope"`;
    g.letterSpacing = sp + "px";
    g.textBaseline = "alphabetic";
    g.textAlign = "left";
    const total = g.measureText(text).width - sp;
    const l = (W - total) / 2;
    const capH = g.measureText("Н").actualBoundingBoxAscent;
    const base = CY + capH / 2 + (dy || 0);
    g.fillStyle = "#fff";
    g.fillText(text, l, base);
    const letters = [];
    for (let i = 0; i < text.length; i++) {
      const a = g.measureText(text.slice(0, i)).width;
      const b = g.measureText(text.slice(0, i + 1)).width - sp;
      letters.push({ x0: l + a, x1: l + b, cx: l + (a + b) / 2 });
    }
    // boundaries midway between letters
    for (let i = 0; i < letters.length; i++) {
      letters[i].b0 = i === 0 ? l - 12 : (letters[i - 1].x1 + letters[i].x0) / 2;
      letters[i].b1 = i === letters.length - 1 ? l + total + 12 : (letters[i].x1 + letters[i + 1].x0) / 2;
    }
    const wd = { key, text, crisp: x, pix: {}, l, r: l + total, top: base - capH, bottom: base, mid: base - capH / 2, capH, size, letters };
    WORDS[key] = wd;
    return wd;
  }

  // pixelated (mosaic) copy of a word, binary-thresholded, cached per block size
  function pixWord(wd, res) {
    if (res <= 1) return wd.crisp;
    if (wd.pix[res]) return wd.pix[res];
    const sw = Math.ceil(W / res), sh = Math.ceil(H / res);
    const s = mk(sw, sh), sx = s.getContext("2d");
    sx.imageSmoothingEnabled = true; sx.imageSmoothingQuality = "high";
    sx.drawImage(wd.crisp, 0, 0, sw, sh);
    const id = sx.getImageData(0, 0, sw, sh);
    for (let i = 3; i < id.data.length; i += 4) { const on = id.data[i] > 112; id.data[i - 3] = id.data[i - 2] = id.data[i - 1] = 255; id.data[i] = on ? 255 : 0; }
    sx.putImageData(id, 0, 0);
    const o = mk(), ox = o.getContext("2d");
    ox.imageSmoothingEnabled = false;
    ox.drawImage(s, 0, 0, sw, sh, 0, 0, sw * res, sh * res);
    wd.pix[res] = o;
    return o;
  }

  async function init() {
    await Promise.all([
      document.fonts.load('800 100px "Manrope"', "ИДЕЯКОМАНДАГЕНТ"),
      document.fonts.load('800 100px "Manrope"', "HackAlem AI"),
      document.fonts.load('700 24px "JetBrains Mono"', "AGENTIC-AI ХАКАТОН · АСТАНА"),
      document.fonts.load('600 24px "JetBrains Mono"', "ПИКСЕЛЕЙAGENTIC-AI ХАКАТОН · АСТАНА0123456789×"),
      document.fonts.load('800 24px "JetBrains Mono"', "0123456789"),
    ]);
    prepWord("idea", TXT.idea, 1560, -0.025, 0);
    prepWord("team", TXT.team, 1500, -0.025, 0);
    prepWord("agent", TXT.agent, 1560, -0.025, 0);
    [120, 60, 30, 15].forEach((r) => { pixWord(WORDS.idea, r); });
    pixWord(WORDS.team, 30);

    // original logo -> raster at lockup size (vector kept as file; only rasterised here)
    logoImg = new Image();
    logoImg.src = "assets/brand/hackalem-logo.svg";
    await logoImg.decode();
    logoC = mk(Math.ceil(LOGO_W) + 2, Math.ceil(LOGO_H) + 2);
    const lx = logoC.getContext("2d");
    lx.imageSmoothingQuality = "high";
    lx.drawImage(logoImg, 0, 0, LOGO_W, LOGO_H);
    // per-cell coverage of the wordmark print lattice
    const id = lx.getImageData(0, 0, logoC.width, logoC.height);
    const cu = WM_U * K;
    wmCov = [];
    const cols = Math.ceil((3777 - WM_X0) / WM_U) + 1, rows = 7;
    for (let c = 0; c < cols; c++) {
      wmCov[c] = [];
      for (let r = 0; r < rows; r++) {
        const x0 = Math.floor((WM_X0 + c * WM_U) * K), x1 = Math.ceil((WM_X0 + (c + 1) * WM_U) * K);
        const y1 = Math.ceil((WM_BASE - r * WM_U) * K), y0 = Math.floor((WM_BASE - (r + 1) * WM_U) * K);
        let on = false;
        for (let y = Math.max(0, y0); y < Math.min(logoC.height, y1) && !on; y++)
          for (let x = Math.max(0, x0); x < Math.min(logoC.width, x1); x++)
            if (id.data[(y * logoC.width + x) * 4 + 3] > 24) { on = true; break; }
        wmCov[c][r] = on;
      }
    }
    void cu;
  }

  // ───────────────────────── camera ─────────────────────────
  let COVER = false;
  function camera(t) {
    if (COVER) return { S: 0.74, ox: 560, oy: 540 };
    let S, ox = CX, oy = CY;
    if (t < T.hit) {
      S = t < T.n8 ? 4.0 : t < T.dock[1] ? 4.2 : 4.4;
    } else {
      const u = inv(T.hit, T.hit + T.whip, t);
      S = 4.4 * Math.pow(1 / 4.4, eOutCubic(u));
      const l = eInOutCubic(inv(T.lock[0], T.lock[1], t));
      if (l > 0) {
        S = Math.exp(lerp(Math.log(S), Math.log(S_LOCK), l));
        ox = lerp(CX, MARK_CX, l); oy = lerp(CY, MARK_CY, l);
      }
    }
    return { S, ox, oy };
  }

  const HITS = [
    [0.0, 18], [0.4, 12], [0.8, 12], [1.2, 16], [3.2, 22], [4.0, 10], [4.4, 10], [4.8, 12],
    [5.6, 8], [7.2, 8], [8.0, 8], [8.4, 9], [8.8, 11], [9.0, 11], [9.1, 12], [9.6, 38],
  ];
  function shakePunch(t) {
    let amp = 0, pun = 0;
    for (let i = 0; i < HITS.length; i++) {
      const d = t - HITS[i][0];
      if (d >= 0 && d < 0.5) { const e = Math.exp(-d / 0.09); amp += HITS[i][1] * e; pun += (HITS[i][1] / 38) * 0.035 * e; }
    }
    const f = frameOf(t);
    const dx = (hash(f, 11) - 0.5) * 2 * amp, dy = (hash(f, 23) - 0.5) * 2 * amp;
    return { dx, dy, k: 1 + pun };
  }

  // ───────────────────────── plate (the light behind the wall) ─────────────────────────
  const PL = {
    warm: [[255, 243, 214], C.amber, C.orange],
    ice: [[255, 255, 255], [250, 253, 255], [236, 247, 255]],
    dark: [[6, 11, 22], [6, 11, 22], [6, 11, 22]],
    burst: [[255, 255, 255], [159, 234, 255], C.cyan],
    drain: [[40, 170, 230], [0, 100, 170], [6, 30, 62]],
  };
  const PLATE_KEYS = [
    [0.0, "warm", 1.0], [2.0, "warm", 1.0], [2.4, "warm", 0.45], [2.8, "ice", 0.55], [3.2, "ice", 1.0],
    [5.19, "ice", 1.0], [5.2, "dark", 0.0], [9.55, "dark", 0.0],
    [T.hit, "burst", 1.0], [T.hit + 0.5, "burst", 1.0], [T.hit + 0.68, "drain", 0.85], [T.hit + 0.98, "dark", 0.0],
    [T.lastTick - 0.034, "dark", 0.0], [T.lastTick, "burst", 0.85], [T.lastTick + 0.07, "burst", 0.7], [T.lastTick + 0.17, "drain", 0.8], [T.lastTick + 0.4, "dark", 0.0],
  ];
  function plateState(t) {
    let a = PLATE_KEYS[0], b = PLATE_KEYS[PLATE_KEYS.length - 1];
    if (t <= a[0]) b = a;
    else if (t >= b[0]) a = b;
    else for (let i = 0; i < PLATE_KEYS.length - 1; i++) if (t >= PLATE_KEYS[i][0] && t < PLATE_KEYS[i + 1][0]) { a = PLATE_KEYS[i]; b = PLATE_KEYS[i + 1]; break; }
    const u = a === b ? 0 : (t - a[0]) / (b[0] - a[0]);
    const ca = PL[a[1]], cb = PL[b[1]];
    const core = mix(ca[0], cb[0], u), midc = mix(ca[1], cb[1], u), edge = mix(ca[2], cb[2], u);
    const warm = (a[1] === "warm" ? 1 - u : 0) + (b[1] === "warm" ? u : 0);
    return { core, mid: midc, edge, i: lerp(a[2], b[2], u), warm: a[1] === b[1] ? (a[1] === "warm" ? 1 : 0) : clamp(warm) };
  }

  function drawPlate(X, t, cam) {
    const ps = plateState(t);
    const half = 480 * cam.S;
    X.save();
    X.beginPath();
    X.rect(cam.ox - half, cam.oy - half, half * 2, half * 2);
    X.clip();
    X.fillStyle = PAL.void;
    X.fillRect(0, 0, W, H);
    if (ps.i > 0.002) {
      const R = Math.max(560, Math.min(1500, 640 * cam.S));
      X.globalAlpha = clamp(ps.i);
      if (ps.warm > 0.01) {
        const lg = X.createLinearGradient(0, CY - 380, 0, CY + 380);
        lg.addColorStop(0, "#FFF3CC"); lg.addColorStop(1, "#FF9A3A");
        X.fillStyle = lg; X.fillRect(0, 0, W, H);
      }
      const g = X.createRadialGradient(cam.ox, cam.oy, 0, cam.ox, cam.oy, R);
      g.addColorStop(0, rgba(ps.core, 1)); g.addColorStop(0.32, rgba(ps.mid, 1 - ps.warm * 0.85)); g.addColorStop(1, rgba(ps.edge, 1 - ps.warm * 0.9));
      X.fillStyle = g;
      X.fillRect(0, 0, W, H);
      X.globalAlpha = 1;
    }
    X.restore();
  }

  // ───────────────────────── wall (quadtree of cells) ─────────────────────────
  const LV = [1, 2, 4, 8, 16];
  const SPLIT_D = 0.12;
  const MERGE_D = 0.09;

  function splitAt(lv, i) {
    if (lv === 0) return T.n2;
    if (lv === 1) return T.n4;
    if (lv === 2) return T.n8;
    const cx = -480 + (i + 0.5) * 120; // world x of an n=8 cell centre
    const k = clamp(Math.ceil((cx + 240) / 60 - EPS), 0, 8);
    return T.scan[0] + k * STEP;
  }
  const mergeAt = (lv) => T.countdown[3 - lv];

  function actColor(t) {
    if (t < 2.6) return [255, 214, 140];
    if (t < 5.4) return [200, 240, 255];
    return C.cyan;
  }

  function tileTone(lv, i, j, t) {
    const rnd = hash(lv * 31 + i, j, 7);
    let m = 1 + (rnd - 0.5) * 0.07;
    // lone cells shimmer out of phase; at the sync they lock to one pulse
    const amp = 0.075 * smooth(1.1, 1.5, t) * (1 - smooth(2.2, 2.4, t)) + 0.075 * smooth(3.2, 3.4, t) * (1 - smooth(T.syncPulses[0] - 0.1, T.syncPulses[0], t));
    m += amp * Math.sin(2 * Math.PI * (2.2 + rnd * 1.6) * t + rnd * 6.28);
    const sync = pulse(t, T.syncPulses, 0.13) * 0.20 * smooth(T.syncPulses[0] - 0.02, T.syncPulses[0], t);
    const p1 = pulse(t, T.pulses1, 0.12) * 0.07;
    const pb = pulse(t, T.buildPulses, 0.1) * 0.16;
    return m + sync + p1 + pb;
  }

  function wallColor(t, tone) {
    // Act I: pure brand blue. Act II: dimmer so the white cut reads. Act III: dimmest so the void cut reads.
    const dim = 0.15 * smooth(0.34, 0.46, t) + 0.25 * smooth(T.ideaClose[0], T.ideaClose[1], t) + 0.25 * smooth(T.dock[0], T.dock[1], t);
    const dimK = t >= 9.4 ? dim * (1 - smooth(9.4, 9.6, t)) : dim;
    const base = mix(C.wall, C.wallDim, clamp(dimK));
    const hi = clamp(tone - 1, 0, 0.6);
    const lo = clamp(1 - tone, 0, 0.3);
    let c = mix(base, C.wallHigh, hi * 1.4);
    c = mix(c, C.wallDark, lo * 1.2);
    return c;
  }

  function gapPx(S) { return lerp(0, 4.5, smooth(1.1, 3.5, S)); }

  function paintTile(X, sx, sy, ss, col, S, extraGap) {
    const g = gapPx(S) + (extraGap || 0);
    const ov = g < 0.5 ? 0.45 : 0; // hide anti-aliasing hairlines between neighbouring cells
    const x = sx + g / 2 - ov, y = sy + g / 2 - ov, s = ss - g + 2 * ov;
    if (s <= 0) return;
    X.fillStyle = rgba(col);
    X.fillRect(x, y, s, s);
    if (S > 2.0 && s > 40) {
      const gr = X.createLinearGradient(0, y, 0, y + s);
      gr.addColorStop(0, "rgba(255,255,255,0.10)"); gr.addColorStop(0.5, "rgba(255,255,255,0)"); gr.addColorStop(1, "rgba(0,12,32,0.16)");
      X.fillStyle = gr; X.fillRect(x, y, s, s);
      X.fillStyle = "rgba(255,255,255,0.20)"; X.fillRect(x, y, s, 3);
      X.fillStyle = "rgba(255,255,255,0.10)"; X.fillRect(x, y, 2, s);
    }
  }

  function crossFlash(X, sx, sy, ss, u, col, S) {
    // two light lines grow from the centre of a splitting cell — the "cut" that makes 4 cells
    const e = eOutExpo(clamp(u * 1.6));
    const a = (1 - clamp(u)) ;
    if (a <= 0.01) return;
    const len = ss * e, w = Math.max(3, 9 * a) * Math.min(1, S / 3);
    const cx = sx + ss / 2, cy = sy + ss / 2;
    X.save();
    X.globalCompositeOperation = "lighter";
    X.fillStyle = rgba(col, 0.9 * a);
    X.fillRect(cx - len / 2, cy - w / 2, len, w);
    X.fillRect(cx - w / 2, cy - len / 2, w, len);
    X.restore();
  }

  function drawTree(X, t, cam) {
    const S = cam.S;
    const flashCol = actColor(t);
    function cell(lv, i, j) {
      const n = LV[lv], size = 960 / n;
      const sx = cam.ox + (-480 + i * size) * S, sy = cam.oy + (-480 + j * size) * S, ss = size * S;
      if (sx > W || sy > H || sx + ss < 0 || sy + ss < 0) return;
      if (lv < 4) {
        const st = splitAt(lv, i), mt = mergeAt(lv);
        const splitOn = t >= st && t < mt;
        const merging = t >= mt && t < mt + MERGE_D;
        if (splitOn || merging) {
          const u = splitOn ? (t - st) / SPLIT_D : 0;
          for (let dj = 0; dj < 2; dj++) for (let di = 0; di < 2; di++) cell(lv + 1, i * 2 + di, j * 2 + dj);
          if (splitOn && u < 1) crossFlash(X, sx, sy, ss, u, flashCol, S);
          if (merging) crossFlash(X, sx, sy, ss, 1 - (t - mt) / MERGE_D, flashCol, S);
          return;
        }
      }
      // leaf
      const tone = tileTone(lv, i, j, t);
      const col = wallColor(t, tone);
      paintTile(X, sx, sy, ss, col, S, 0);
    }
    cell(0, 0, 0);
  }

  // leaf count for the HUD
  function pixelCount(t) {
    if (t >= T.hit) {
      const k = Math.floor((t - T.hit) / (T.waveFrames / FPS) + EPS);
      return Math.min(256, Math.pow(2 * (k + 1), 2));
    }
    if (t >= T.countdown[3]) return 1;
    if (t >= T.countdown[2]) return 4;
    if (t >= T.countdown[1]) return 16;
    if (t >= T.countdown[0]) return 64;
    if (t >= T.scan[0]) {
      let n = 0;
      for (let i = 0; i < 8; i++) n += (t >= splitAt(3, i) ? 4 : 1) * 8;
      return n;
    }
    if (t >= T.n8) return 64;
    if (t >= T.n4) return 16;
    if (t >= T.n2) return 4;
    return 1;
  }

  // ───────────────────────── words → masks ─────────────────────────
  function lookupRes(t) {
    let r = T.ideaRes[0][1];
    for (let i = 0; i < T.ideaRes.length; i++) if (t >= T.ideaRes[i][0] - EPS) r = T.ideaRes[i][1];
    return r;
  }

  function clipRect(X, x0, y0, x1, y1, img) {
    if (x1 <= x0 || y1 <= y0) return;
    X.save();
    X.beginPath(); X.rect(x0, y0, x1 - x0, y1 - y0); X.clip();
    X.drawImage(img, 0, 0);
    X.restore();
  }

  function teamSegs() {
    const w = WORDS.team, L = w.letters;
    return [
      { x0: w.l - 12, x1: L[2].b0, a: 0, b: 1 },
      { x0: L[2].b0, x1: L[5].b0, a: 2, b: 4 },
      { x0: L[5].b0, x1: w.r + 12, a: 5, b: 6 },
    ];
  }
  const teamP = (t, ease) => ease(inv(T.teamCut[0], T.teamCut[1], quant(t) + STEP));

  function maskIdea(t, fx) {
    const X = maskX, w = WORDS.idea;
    // crack: a vertical slit of light, grows from the centre
    const crackT = T.ideaOpen + 0.3;
    if (t < crackT) {
      const h = H * (0.34 + 0.66 * eOutExpo(inv(0, T.crackFull, t)));
      const jit = (hash(frameOf(t), 5) - 0.5) * 6;
      const wd = lerp(5, 18, inv(0, T.ideaOpen, t));
      X.fillStyle = "#fff";
      X.fillRect(CX - wd / 2 + jit, CY - h / 2, wd, h);
    }
    if (t >= T.ideaOpen) {
      const r = (W / 2 + 40) * eOutExpo(inv(T.ideaOpen, T.ideaOpen + 0.35, t));
      let left = CX - r;
      const c0 = T.ideaClose[0], c1 = T.ideaClose[1];
      let front = 0;
      if (t >= c0) { front = lerp(w.l - 30, w.r + 30, inv(c0, c1, quant(t, 1 / FPS * 2) + 2 / FPS)); left = Math.max(left, front); fx.push({ type: "vbar", x: front, y0: w.top - 40, y1: w.bottom + 40, col: [255, 226, 170] }); }
      const res = lookupRes(t);
      clipRect(X, left, 0, CX + r, H, pixWord(w, res));
    }
  }

  function maskTeam(t, fx) {
    const X = maskX, w = WORDS.team, segs = teamSegs();
    const cut0 = T.teamCut[0], cut1 = T.teamCut[1];
    const lag = 90;
    if (t >= cut0 && t < T.teamClose[0]) {
      const p1 = teamP(t, eOutCubic), p2 = teamP(t, (u) => u), p3 = teamP(t, eInOutCubic);
      const s1 = segs[0], s2 = segs[1], s3 = segs[2];
      const h1 = lerp(s1.x0, s1.x1, p1), h3 = lerp(s3.x1, s3.x0, p3), h2 = lerp(w.top - 8, w.bottom + 8, p2);
      const crisp = w.crisp, pix = pixWord(w, 30);
      const l1 = p1 >= 0.999 ? 0 : lag, l2 = p2 >= 0.999 ? 0 : lag, l3 = p3 >= 0.999 ? 0 : lag; // a finished cut is crisp
      // КО: left → right
      clipRect(X, s1.x0, 0, h1 - l1, H, crisp); clipRect(X, Math.max(s1.x0, h1 - l1), 0, h1, H, pix);
      // МАН: top → bottom
      clipRect(X, s2.x0, 0, s2.x1, h2 - l2, crisp); clipRect(X, s2.x0, Math.max(0, h2 - l2), s2.x1, h2, pix);
      // ДА: right → left
      clipRect(X, h3 + l3, 0, s3.x1, H, crisp); clipRect(X, h3, 0, Math.min(s3.x1, h3 + l3), H, pix);
      const done = (v) => v >= 0.999;
      fx.push({ type: "vbar", x: h1, y0: w.top - 30, y1: w.bottom + 30, col: [255, 160, 90], off: done(p1) });
      fx.push({ type: "hbar", y: h2, x0: s2.x0, x1: s2.x1, col: [255, 255, 255], off: done(p2) });
      fx.push({ type: "vbar", x: h3, y0: w.top - 30, y1: w.bottom + 30, col: [90, 220, 255], off: done(p3) });
    } else if (t >= T.teamClose[0] && t < T.teamClose[1]) {
      const a = (w.r - w.l) / 2 * inv(T.teamClose[0], T.teamClose[1], quant(t) + STEP);
      clipRect(X, w.l + a, 0, w.r - a, H, w.crisp);
    } else if (t >= T.teamCut[1] && t < T.teamClose[0]) {
      X.drawImage(w.crisp, 0, 0);
    }
  }

  function maskAgent(t, fx) {
    const X = maskX, w = WORDS.agent, L = T.agentLetters;
    if (t < L[0][0] || t >= T.countdown[3]) return;
    for (let i = 0; i < w.letters.length; i++) {
      const lt = w.letters[i], a = L[i][0], b = L[i][1];
      if (t < a) continue;
      const p = clamp(inv(a, b, quant(t) + STEP));
      clipRect(X, lt.b0, w.top - 6, lt.b1, w.top - 6 + (w.capH + 12) * p, w.crisp);
      if (t < b && t >= a) fx.push({ type: "hbar", y: lerp(w.top - 6, w.bottom + 6, p), x0: lt.b0, x1: lt.b1, col: [255, 255, 255] });
    }
  }

  function drawMask(t, fx) {
    maskX.setTransform(1, 0, 0, 1, 0, 0);
    maskX.clearRect(0, 0, W, H);
    maskX.imageSmoothingEnabled = false;
    if (t < T.ideaClose[1]) maskIdea(t, fx);
    if (t >= T.teamCut[0] && t < T.teamClose[1]) maskTeam(t, fx);
    if (t >= T.agentLetters[0][0] && t < T.countdown[3]) maskAgent(t, fx);
  }

  function rimColor(t) {
    if (t < 2.6) return C.amber;
    if (t < 5.4) return C.cyan;
    return C.cyan;
  }

  // soft halo hugging the cutouts (computed at 1/4 res)
  function drawHalo(X, t) {
    haloX.setTransform(1, 0, 0, 1, 0, 0);
    haloX.globalCompositeOperation = "source-over";
    haloX.clearRect(0, 0, 480, 270);
    haloX.filter = "blur(5px)";
    haloX.drawImage(maskC, 0, 0, 480, 270);
    haloX.filter = "none";
    haloX.globalCompositeOperation = "destination-out";
    haloX.drawImage(maskC, 0, 0, 480, 270);
    haloX.globalCompositeOperation = "source-in";
    haloX.fillStyle = rgba(rimColor(t));
    haloX.fillRect(0, 0, 480, 270);
    haloX.globalCompositeOperation = "source-over";
    X.save();
    X.globalCompositeOperation = "lighter";
    X.globalAlpha = 0.6 + 0.4 * Math.min(1, pulse(t, T.syncPulses, 0.12) + pulse(t, T.buildPulses, 0.1) * 0.8);
    X.imageSmoothingEnabled = true;
    X.drawImage(haloC, 0, 0, W, H);
    X.restore();
  }

  // ───────────────────────── sparks & fx ─────────────────────────
  function spark(X, x, y, size, col, alpha, glow) {
    if (alpha <= 0.01) return;
    const R = size * 3.4 * (glow || 1);
    X.save();
    X.globalCompositeOperation = "lighter";
    const g = X.createRadialGradient(x, y, 0, x, y, R);
    g.addColorStop(0, rgba(col, 0.55 * alpha)); g.addColorStop(1, rgba(col, 0));
    X.fillStyle = g; X.fillRect(x - R, y - R, R * 2, R * 2);
    X.restore();
    X.save();
    X.globalAlpha = clamp(alpha);
    X.fillStyle = rgba(col);
    X.fillRect(x - size / 2 - 4, y - size / 2 - 4, size + 8, size + 8);
    X.fillStyle = "#fff";
    const c = size * 0.62;
    X.fillRect(x - c / 2, y - c / 2, c, c);
    X.restore();
  }

  function hop(t, t0, t1, p0, p1, arc) {
    const q = clamp(quant(t), t0, t1 - STEP);
    const u = eInOutCubic(inv(t0, t1, q + STEP));
    return { x: lerp(p0.x, p1.x, u), y: lerp(p0.y, p1.y, u) - arc * Math.sin(Math.PI * u) };
  }

  const DOCK = [0, 1, 2].map((k) => ({ x: CX + (k - 1) * 136, y: 972 }));
  const SPARK_COL = [[255, 150, 60], [255, 255, 255], [60, 215, 255]];
  const SP = 72; // size of the three team sparks, px

  function dockSquare(X, x, y, size, col, hot) {
    X.save();
    X.fillStyle = rgba(C.hudInk); X.fillRect(x - size / 2 - 8, y - size / 2 - 8, size + 16, size + 16);
    X.fillStyle = rgba(col); X.fillRect(x - size / 2, y - size / 2, size, size);
    X.fillStyle = "#fff"; const c = size * (0.28 + 0.36 * hot); X.fillRect(x - c / 2, y - c / 2, c, c);
    if (hot > 0.15) {
      X.globalCompositeOperation = "lighter";
      const R = size * 2.4, g = X.createRadialGradient(x, y, 0, x, y, R);
      g.addColorStop(0, rgba(col, 0.4 * hot)); g.addColorStop(1, rgba(col, 0));
      X.fillStyle = g; X.fillRect(x - R, y - R, R * 2, R * 2);
    }
    X.restore();
  }

  function echoes(X, t, hp, col, size) {
    for (let e = 1; e <= 4; e++) {
      const te = t - e * STEP;
      if (te < hp.t0) break;
      const pe = hop(te, hp.t0, hp.t1, hp.from, hp.to, hp.arc);
      X.globalAlpha = 0.55 / e; X.fillStyle = rgba(col); X.fillRect(pe.x - size / 2, pe.y - size / 2, size, size); X.globalAlpha = 1;
    }
  }

  function sparkSet(X, t, fx) {
    const wI = WORDS.idea, wT = WORDS.team, wA = WORDS.agent;
    const segs = teamSegs();
    // frame 0: the idea spark and the amber light leaking out of the crack
    if (t < 0.9) {
      const a = 0.32 * (1 - inv(0.35, 0.9, t));
      const h = H * (0.34 + 0.66 * eOutExpo(inv(0, T.crackFull, t)));
      const g = X.createLinearGradient(CX - 150, 0, CX + 150, 0);
      g.addColorStop(0, "rgba(255,170,70,0)"); g.addColorStop(0.5, `rgba(255,196,110,${a})`); g.addColorStop(1, "rgba(255,170,70,0)");
      X.save(); X.globalCompositeOperation = "lighter"; X.fillStyle = g; X.fillRect(CX - 150, CY - h / 2, 300, h); X.restore();
    }
    if (t < T.ideaOpen + 0.2) {
      const pul = 1 + 0.9 * Math.sin(inv(0, 0.2, t) * Math.PI) * (t < 0.2 ? 1 : 0);
      const s0 = (t < 0.4 ? lerp(96, 44, inv(0, 0.4, t)) : 44 * (1 - inv(0.4, 0.6, t))) * pul;
      spark(X, CX, CY, s0, SPARK_COL[0], 1 - inv(0.5, 0.6, t), 1.4);
    }
    // three sparks: born at the closing front of ИДЕЯ, hop to the cutters' start points
    const cl0 = T.ideaClose[0], cl1 = T.ideaClose[1];
    const born = [0, 1, 2].map((k) => cl0 + (cl1 - cl0) * (0.25 + 0.25 * k));
    const bx = [0.25, 0.5, 0.75].map((f) => lerp(wI.l, wI.r, f));
    const cB = (segs[1].x0 + segs[1].x1) / 2;
    const starts = [{ x: segs[0].x0, y: wT.mid }, { x: cB, y: wT.top - 8 }, { x: segs[2].x1, y: wT.mid }];
    const fin = [{ x: segs[0].x1, y: wT.mid }, { x: cB, y: wT.bottom + 8 }, { x: segs[2].x0, y: wT.mid }];
    const rest = [{ x: segs[0].x1, y: wT.top - 90 }, { x: cB, y: wT.bottom + 96 }, { x: segs[2].x0, y: wT.top - 90 }]; // off the glyphs
    const arcs = [-190, 0, 190];
    const docks = DOCK;
    const cut1 = T.teamCut[1];
    for (let k = 0; k < 3; k++) {
      const col = SPARK_COL[k];
      let p = null, hp = null, size = SP, a = 1;
      const mkhop = (t0, t1, from, to, arc) => { hp = { t0, t1, from, to, arc }; return hop(t, t0, t1, from, to, arc); };
      if (t >= born[k] && t < T.sparkHop[0]) p = { x: bx[k], y: wI.mid };
      else if (t >= T.sparkHop[0] && t < T.teamCut[0]) p = mkhop(T.sparkHop[0], T.sparkHop[1], { x: bx[k], y: wI.mid }, starts[k], arcs[k]);
      else if (t >= T.teamCut[0] && t < cut1) {
        const p1 = teamP(t, eOutCubic), p2 = teamP(t, (u) => u), p3 = teamP(t, eInOutCubic);
        if (k === 0) p = { x: lerp(segs[0].x0, segs[0].x1, p1), y: wT.mid };
        if (k === 1) p = { x: starts[1].x, y: lerp(wT.top - 8, wT.bottom + 8, p2) };
        if (k === 2) p = { x: lerp(segs[2].x1, segs[2].x0, p3), y: wT.mid };
      } else if (t >= cut1 && t < cut1 + 0.4) p = mkhop(cut1, cut1 + 0.4, fin[k], rest[k], arcs[k] * 0.3);
      else if (t >= cut1 + 0.4 && t < T.dock[0]) p = rest[k];
      else if (t >= T.dock[0] && t < T.dock[1]) p = mkhop(T.dock[0], T.dock[1], rest[k], docks[k], arcs[k] * 0.5);
      else if (t >= T.dock[1] && t < T.gather[0]) {
        // docked: the team stays below the word and pulses with the work
        const lp = letterPulse(t, k);
        dockSquare(X, docks[k].x, docks[k].y, 84, SPARK_COL[k], Math.min(1, pulse(t, T.buildPulses, 0.12) + lp + pulse(t, T.syncPulses, 0.1)));
      } else if (t >= T.gather[0] && t < T.gather[1]) { size = 84; p = mkhop(T.gather[0], T.gather[1], docks[k], { x: CX, y: CY }, (k - 1) * 110); }
      if (p) {
        if (hp) echoes(X, t, hp, col, size);
        spark(X, p.x, p.y, size, col, a, 1);
      }
    }
    // agent spark: the writer. During the build it waits under the word and is fed by the team.
    const wl = T.agentLetters, last = wl[wl.length - 1][1];
    const hub = { x: CX, y: wA.bottom + 108 };
    if (t >= T.dock[1] - 0.1 && t < T.gather[1]) {
      let p = null, size = 64;
      if (t < wl[0][0]) p = { x: CX, y: CY };
      else if (t < last) {
        let i = 0; for (let n = 0; n < wl.length; n++) if (t >= wl[n][0]) i = n;
        const pp = clamp(inv(wl[i][0], wl[i][1], quant(t) + STEP));
        p = { x: wA.letters[i].cx, y: lerp(wA.top - 6, wA.bottom + 6, pp) };
      } else if (t < T.scan[0]) p = { x: wA.letters[wA.letters.length - 1].cx, y: wA.bottom + 6 };
      else if (t < T.scan[1] + STEP) {
        const k = Math.min(8, Math.floor((t - T.scan[0]) / STEP + EPS));
        p = { x: scanX(k, camera(t)), y: CY };
      } else if (t < T.gather[0]) p = hop(t, T.scan[1] + STEP, T.scan[1] + 3 * STEP, { x: scanX(8, camera(T.scan[0])), y: CY }, hub, 0);
      else p = hop(t, T.gather[0], T.gather[1], hub, { x: CX, y: CY }, 0);
      const charge = t > T.scan[1] ? 1 + 0.6 * pulse(t, T.buildPulses, 0.1) : 1;
      if (p) spark(X, p.x, p.y, size * charge, [255, 255, 255], 1, 1.3);
    }
    // team → agent: every build pulse sends three packets from the docked team to the agent
    for (let m = 0; m < T.buildPulses.length; m++) {
      const pt = T.buildPulses[m];
      if (t >= pt - 0.3 && t < pt) {
        for (let k = 0; k < 3; k++) {
          const hp = { t0: pt - 0.3, t1: pt, from: docks[k], to: hub, arc: (k - 1) * 46 };
          const pp = hop(t, hp.t0, hp.t1, hp.from, hp.to, hp.arc);
          echoes(X, t, hp, SPARK_COL[k], 34);
          X.fillStyle = rgba(SPARK_COL[k]); X.fillRect(pp.x - 24, pp.y - 24, 48, 48);
          X.fillStyle = "#fff"; X.fillRect(pp.x - 12, pp.y - 12, 24, 24);
        }
      }
    }
    // the centre spark just before the hit (mirror of frame 0)
    if (t >= T.gather[1] && t < T.hit) {
      const g = inv(T.gather[1], T.hit, t);
      spark(X, CX, CY, lerp(60, 84, g), [255, 255, 255], 1, 1.8);
    }
    // heads of the three cutters are drawn as bars (see fx)
    fx.forEach((f) => {
      if (f.off) return;
      X.save();
      X.globalCompositeOperation = "lighter";
      const c = f.col;
      if (f.type === "vbar") {
        X.fillStyle = rgba(c, 0.18); X.fillRect(f.x - 26, f.y0, 52, f.y1 - f.y0);
        X.fillStyle = rgba(c, 0.6); X.fillRect(f.x - 7, f.y0, 14, f.y1 - f.y0);
        X.fillStyle = rgba(WHITE, 0.95); X.fillRect(f.x - 2, f.y0, 4, f.y1 - f.y0);
      } else {
        X.fillStyle = rgba(c, 0.18); X.fillRect(f.x0, f.y - 26, f.x1 - f.x0, 52);
        X.fillStyle = rgba(c, 0.6); X.fillRect(f.x0, f.y - 7, f.x1 - f.x0, 14);
        X.fillStyle = rgba(WHITE, 0.95); X.fillRect(f.x0, f.y - 2, f.x1 - f.x0, 4);
      }
      X.restore();
    });
  }

  function letterPulse(t, k) {
    // each letter of АГЕНТ is "launched" by one of the three docked team sparks
    let p = 0;
    for (let i = 0; i < T.agentLetters.length; i++) {
      if (i % 3 !== k) continue;
      const d = t - T.agentLetters[i][1];
      if (d >= 0 && d < 0.5) p += Math.exp(-d / 0.1);
    }
    return p;
  }

  function scanX(k, cam) { return cam.ox + (-240 + 60 * k) * cam.S; }

  function drawScanBar(X, t, cam) {
    if (t < T.scan[0] || t >= T.scan[1] + STEP) return;
    const k = Math.min(8, Math.floor((t - T.scan[0]) / STEP + EPS));
    const x = scanX(k, cam);
    X.save();
    X.globalCompositeOperation = "lighter";
    X.fillStyle = rgba(C.cyan, 0.16); X.fillRect(x - 70, 0, 140, H);
    X.fillStyle = rgba(C.cyan, 0.55); X.fillRect(x - 9, 0, 18, H);
    X.fillStyle = rgba(WHITE, 0.95); X.fillRect(x - 2.5, 0, 5, H);
    X.restore();
  }

  // ───────────────────────── the hit: square wave of resolution ─────────────────────────
  function drawWave(X, t, cam) {
    const S = cam.S;
    const fr = T.waveFrames / FPS;
    const k = Math.floor((t - T.hit) / fr + EPS);
    const wv = Math.min(480, 60 * (k + 1)); // world half-width of the front
    const half = wv * S;
    // slab outside the front (even-odd hole)
    if (wv < 480) {
      X.save();
      X.beginPath();
      X.rect(0, 0, W, H);
      X.rect(cam.ox - half, cam.oy - half, half * 2, half * 2);
      X.clip("evenodd");
      const sz = 960 * S;
      paintTile(X, cam.ox - sz / 2, cam.oy - sz / 2, sz, wallColor(t, 1.0 + 0.0), S, 0);
      X.restore();
    }
    // mosaic inside
    const cell = 60 * S;
    for (let j = 0; j < 16; j++) for (let i = 0; i < 16; i++) {
      const cxw = -480 + (i + 0.5) * 60, cyw = -480 + (j + 0.5) * 60;
      if (Math.abs(cxw) > wv || Math.abs(cyw) > wv) continue;
      const sx = cam.ox + (-480 + i * 60) * S, sy = cam.oy + (-480 + j * 60) * S;
      if (GRID[j][i]) paintTile(X, sx, sy, cell, C.wall, S, 0);
    }
    return { wv, k };
  }

  function drawWaveFx(X, t, cam, info) {
    const S = cam.S, wv = info.wv, half = wv * S;
    const age = t - T.hit;
    X.save();
    X.globalCompositeOperation = "lighter";
    // freshly revealed void cells flash white → settle into the glow
    const fr = T.waveFrames / FPS;
    for (let j = 0; j < 16; j++) for (let i = 0; i < 16; i++) {
      if (GRID[j][i]) continue;
      const ring = Math.max(Math.abs(i - 7.5), Math.abs(j - 7.5)) - 0.5;
      const rt = T.hit + ring * fr;
      const a = t - rt;
      if (a < 0 || a > 0.4) continue;
      const f = Math.exp(-a / 0.09);
      X.fillStyle = rgba(WHITE, 0.85 * f);
      const sx = cam.ox + (-480 + i * 60) * S, sy = cam.oy + (-480 + j * 60) * S;
      X.fillRect(sx, sy, 60 * S, 60 * S);
    }
    // front outline: lives while the front travels, fades right after it closes the square
    const doneT = T.hit + 7 * fr;
    const oa = wv < 480 ? 1 : 1 - inv(doneT, doneT + 0.05, t);
    if (oa > 0.01) {
      const th = Math.max(5, 12 * Math.min(1, S / 2));
      X.fillStyle = rgba(WHITE, 0.95 * oa);
      const x0 = cam.ox - half, y0 = cam.oy - half, x1 = cam.ox + half, y1 = cam.oy + half;
      X.fillRect(x0 - th / 2, y0 - th / 2, half * 2 + th, th);
      X.fillRect(x0 - th / 2, y1 - th / 2, half * 2 + th, th);
      X.fillRect(x0 - th / 2, y0, th, half * 2);
      X.fillRect(x1 - th / 2, y0, th, half * 2);
      X.strokeStyle = rgba(C.cyan, 0.25 * oa); X.lineWidth = th * 2.2;
      X.strokeRect(x0, y0, half * 2, half * 2);
    }
    // light shaft out of the figure (the site's own hero light, brief)
    const sh = age > 0.05 ? Math.exp(-(age - 0.05) / 0.12) : 0;
    if (sh > 0.01) {
      const g = X.createLinearGradient(cam.ox - 90, 0, cam.ox + 90, 0);
      g.addColorStop(0, "rgba(0,200,255,0)"); g.addColorStop(0.5, `rgba(190,240,255,${0.30 * sh})`); g.addColorStop(1, "rgba(0,200,255,0)");
      X.fillStyle = g; X.fillRect(cam.ox - 90, 0, 180, H);
    }
    X.restore();
    // light bleeding out of the lit void onto the neighbouring blue cells
    const ps = plateState(t);
    if (ps.i > 0.02) {
      haloX.setTransform(1, 0, 0, 1, 0, 0);
      haloX.globalCompositeOperation = "source-over";
      haloX.clearRect(0, 0, 480, 270);
      haloX.fillStyle = "#fff";
      for (let j = 0; j < 16; j++) for (let i = 0; i < 16; i++) {
        if (GRID[j][i]) continue;
        const ring = Math.max(Math.abs(i - 7.5), Math.abs(j - 7.5)) - 0.5;
        if (t < T.hit + ring * fr) continue;
        haloX.fillRect((cam.ox + (-480 + i * 60) * S) / 4, (cam.oy + (-480 + j * 60) * S) / 4, 15 * S, 15 * S);
      }
      haloX.filter = "blur(4px)";
      haloX.globalCompositeOperation = "copy";
      haloX.drawImage(haloC, 0, 0);
      haloX.filter = "none";
      haloX.globalCompositeOperation = "source-in";
      haloX.fillStyle = rgba(mix(C.cyan, WHITE, 0.45));
      haloX.fillRect(0, 0, 480, 270);
      haloX.globalCompositeOperation = "source-over";
      X.save();
      X.globalCompositeOperation = "lighter";
      X.globalAlpha = 0.5 * ps.i;
      X.imageSmoothingEnabled = true;
      X.drawImage(haloC, 0, 0, W, H);
      X.restore();
    }
    X.restore();
  }

  // ───────────────────────── lockup: wordmark print, rule, tagline ─────────────────────────
  function drawLockup(X, t, cam) {
    if (t < T.print[0]) return;
    const cu = WM_U * K;
    const cols = wmCov.length;
    const P0 = T.print[0], P1 = T.print[1];
    const span = P1 - P0 - 0.18;
    let frontCol = -1;
    X.save();
    for (let c = 0; c < cols; c++) {
      for (let r = 0; r < 7; r++) {
        if (!wmCov[c][r]) continue;
        const tc = P0 + span * (c / (cols - 1)) + hash(c, r, 3) * 0.1;
        const a = inv(tc, tc + 0.18, t);
        if (a <= 0) continue;
        const sxu = WM_X0 + c * WM_U, syu = WM_BASE - (r + 1) * WM_U;
        const x0 = Math.floor(sxu * K), y0 = Math.floor(syu * K), x1 = Math.ceil((sxu + WM_U) * K), y1 = Math.ceil((syu + WM_U) * K);
        X.globalAlpha = eOutCubic(a);
        X.drawImage(logoC, x0, y0, x1 - x0, y1 - y0, LOGO_X + x0, LOGO_Y + y0, x1 - x0, y1 - y0);
        if (a < 1) {
          X.globalAlpha = (1 - a) * 0.95;
          X.globalCompositeOperation = "lighter";
          X.fillStyle = a < 0.5 ? rgba(C.ice) : rgba(C.cyan);
          X.fillRect(LOGO_X + x0 - 3, LOGO_Y + y0 - 3, x1 - x0 + 6, y1 - y0 + 6);
          X.globalCompositeOperation = "source-over";
          frontCol = Math.max(frontCol, c);
        }
      }
    }
    X.globalAlpha = 1;
    if (frontCol >= 0 && t < P1) {
      const fx = LOGO_X + (WM_X0 + (frontCol + 1) * WM_U) * K;
      X.globalCompositeOperation = "lighter";
      X.fillStyle = rgba(C.cyan, 0.2); X.fillRect(fx - 28, LOGO_Y + 30, 56, LOGO_H - 60);
      X.fillStyle = rgba(WHITE, 0.9); X.fillRect(fx - 2, LOGO_Y + 30, 4, LOGO_H - 60);
    }
    X.restore();

    // original mark from the svg replaces the canvas mark once the lock is done (identical geometry)
    if (t >= T.lock[1]) {
      const a = smooth(T.lock[1], T.lock[1] + 0.12, t);
      X.save(); X.globalAlpha = a;
      X.drawImage(logoC, 0, 0, Math.ceil(570 * K), logoC.height, LOGO_X, LOGO_Y, Math.ceil(570 * K), logoC.height);
      X.restore();
    }
  }

  function drawFinal(X, t) {
    // rule
    if (t >= T.rule[0]) {
      const p = inv(T.rule[0], T.rule[1], quant(t, 1 / FPS * 2) + 2 / FPS);
      const w = LOGO_W * p;
      X.fillStyle = rgba(C.wall, 0.9);
      X.fillRect(LOGO_X, 634, w, 4);
    }
    // tagline typed one char per frame
    if (t >= T.tagline[0]) {
      const s = TXT.tagline;
      const n = Math.min(s.length, Math.floor((t - T.tagline[0]) * FPS + EPS) + 1);
      X.save();
      X.font = `700 34px ${MONO}`;
      X.letterSpacing = "7px";
      X.textBaseline = "alphabetic";
      X.fillStyle = rgba(C.sky, 0.92);
      X.fillText(s.slice(0, n), LOGO_X, 710);
      if (n < s.length) { const wd = X.measureText(s.slice(0, n)).width; X.fillStyle = rgba(C.ice); X.fillRect(LOGO_X + wd + 2, 682, 18, 30); }
      X.restore();
    }
    // the dot of "hackalem.ai": the first pixel comes back as idea · team · agent
    const da = T.dotAccents;
    for (let i = 0; i < da.length; i++) {
      const d = t - da[i];
      if (d < 0 || d > 0.42) continue;
      const col = SPARK_COL[i];
      const dx = LOGO_X + DOT.x * K, dy = LOGO_Y + DOT.y * K, ds = DOT.s * K;
      const e = Math.exp(-d / 0.16);
      X.save();
      X.fillStyle = rgba(C.void); X.fillRect(dx - 2, dy - 2, ds + 4, ds + 4);
      X.globalCompositeOperation = "lighter";
      const R = ds * (3 + 4 * e);
      const g = X.createRadialGradient(dx + ds / 2, dy + ds / 2, 0, dx + ds / 2, dy + ds / 2, R);
      g.addColorStop(0, rgba(col, 0.6 * e)); g.addColorStop(1, rgba(col, 0));
      X.fillStyle = g; X.fillRect(dx + ds / 2 - R, dy + ds / 2 - R, R * 2, R * 2);
      X.globalCompositeOperation = "source-over";
      X.fillStyle = rgba(mix(col, WHITE, 0.25)); const s2 = ds * (1 + 0.5 * e);
      X.fillRect(dx + ds / 2 - s2 / 2, dy + ds / 2 - s2 / 2, s2, s2);
      X.restore();
    }
  }

  // ───────────────────────── HUD ─────────────────────────
  function drawHUD(X, t) {
    if (t >= T.hit + 0.84) return;
    const a = 1 - smooth(T.hit + 0.62, T.hit + 0.82, t);
    const n = pixelCount(t);
    const chg = [T.n2, T.n4, T.n8, ...T.countdown, T.hit];
    let flash = 0;
    chg.forEach((c) => { if (t >= c && t < c + 0.1) flash = 1; });
    X.save();
    X.globalAlpha = a;
    X.fillStyle = t >= T.hit ? rgba(C.ice) : rgba(flash ? C.ice : C.hudInk);
    X.textBaseline = "alphabetic";
    X.font = `700 31px ${MONO}`; X.letterSpacing = "7px";
    X.fillText(TXT.hudLabel, 72, 106);
    X.font = `800 104px ${MONO}`; X.letterSpacing = "-3px";
    X.fillText(String(n), 72, 208);
    X.fillRect(72, 124, 64, 5);
    X.restore();
  }

  // ───────────────────────── post ─────────────────────────
  let noiseC = null;
  function noiseTile() {
    if (noiseC) return noiseC;
    noiseC = mk(256, 256);
    const g = noiseC.getContext("2d"), id = g.createImageData(256, 256);
    for (let i = 0; i < 256 * 256; i++) { const v = (hash(i, 99) * 255) | 0; id.data[i * 4] = id.data[i * 4 + 1] = id.data[i * 4 + 2] = v; id.data[i * 4 + 3] = 255; }
    g.putImageData(id, 0, 0);
    return noiseC;
  }

  function bloom(X, k) {
    bloomAx.setTransform(1, 0, 0, 1, 0, 0);
    bloomAx.filter = "brightness(0.5) contrast(5) blur(2px)";
    bloomAx.imageSmoothingQuality = "high";
    bloomAx.clearRect(0, 0, 480, 270);
    bloomAx.drawImage(frameC, 0, 0, 480, 270);
    bloomAx.filter = "none";
    bloomBx.filter = "blur(2px)";
    bloomBx.clearRect(0, 0, 120, 68);
    bloomBx.drawImage(bloomA, 0, 0, 120, 68);
    bloomBx.filter = "none";
    X.save();
    X.globalCompositeOperation = "lighter";
    X.imageSmoothingEnabled = true;
    X.globalAlpha = 0.34 * k; X.drawImage(bloomA, 0, 0, W, H);
    X.globalAlpha = 0.30 * k; X.drawImage(bloomB, 0, 0, W, H);
    X.restore();
  }

  function post(X, t) {
    // vignette
    const g = X.createRadialGradient(CX, CY, 600, CX, CY, 1320);
    g.addColorStop(0, "rgba(3,6,13,0)"); g.addColorStop(1, "rgba(3,6,13,0.40)");
    X.fillStyle = g; X.fillRect(0, 0, W, H);
    // grain (deterministic per frame)
    const f = frameOf(t);
    X.save();
    X.globalAlpha = 0.045;
    X.globalCompositeOperation = "overlay";
    const nt = noiseTile();
    const ox = -((hash(f, 1) * 256) | 0), oy = -((hash(f, 2) * 256) | 0);
    for (let y = oy; y < H; y += 256) for (let x = ox; x < W; x += 256) X.drawImage(nt, x, y);
    X.restore();
  }

  // ───────────────────────── frame assembly ─────────────────────────
  function drawScene(X, t) {
    const cam = camera(t);
    X.setTransform(1, 0, 0, 1, 0, 0);
    X.globalCompositeOperation = "source-over";
    X.globalAlpha = 1;
    X.fillStyle = PAL.void;
    X.fillRect(0, 0, W, H);
    drawPlate(X, t, cam);
    wallX.setTransform(1, 0, 0, 1, 0, 0);
    wallX.globalCompositeOperation = "source-over";
    wallX.clearRect(0, 0, W, H);
    const fx = [];
    let waveInfo = null;
    if (t < T.hit) drawTree(wallX, t, cam); else waveInfo = drawWave(wallX, t, cam);
    if (t < T.hit) {
      drawMask(t, fx);
      wallX.globalCompositeOperation = "destination-out";
      wallX.drawImage(maskC, 0, 0);
      wallX.globalCompositeOperation = "source-over";
    }
    X.drawImage(wallC, 0, 0);
    if (t < T.hit) {
      drawHalo(X, t);
      drawScanBar(X, t, cam);
      sparkSet(X, t, fx);
    } else {
      drawWaveFx(X, t, cam, waveInfo);
    }
    drawLockup(X, t, cam);
    drawFinal(X, t);
  }

  function renderSample(t) {
    drawScene(sceneX, t);
    const sp = shakePunch(t);
    frameX.setTransform(1, 0, 0, 1, 0, 0);
    frameX.globalAlpha = 1;
    frameX.globalCompositeOperation = "source-over";
    frameX.fillStyle = t < T.hit + 0.1 ? rgba(wallColor(t, 1.0)) : PAL.void; // shake must never expose a dark edge
    frameX.fillRect(0, 0, W, H);
    frameX.setTransform(sp.k, 0, 0, sp.k, CX + sp.dx - CX * sp.k, CY + sp.dy - CY * sp.k);
    frameX.drawImage(sceneC, 0, 0);
    frameX.setTransform(1, 0, 0, 1, 0, 0);
    const bk = t >= T.hit && t < T.lock[1] ? 1.25 : 1.0;
    bloom(frameX, bk);
  }

  // motion blur only on the whip-out (sub-frame accumulation, deterministic)
  function blurSamples(t) {
    const a = t - T.hit;
    if (a < -EPS || a > 0.34) return 1;
    return a < 0.2 ? 9 : 5;
  }

  function render(t) {
    t = clamp(t, 0, CUES.meta.duration - 1 / FPS / 2);
    const n = blurSamples(t);
    out.setTransform(1, 0, 0, 1, 0, 0);
    out.globalAlpha = 1;
    out.globalCompositeOperation = "source-over";
    if (n <= 1) {
      renderSample(t);
      out.drawImage(frameC, 0, 0);
    } else {
      const shutter = 0.25 / FPS; // 180° shutter, only on the whip-out
      accX.setTransform(1, 0, 0, 1, 0, 0);
      for (let i = 0; i < n; i++) {
        const ts = Math.max(T.hit, t + (i / (n - 1) - 0.5) * shutter * 2);
        renderSample(ts);
        accX.globalAlpha = 1 / (i + 1);
        accX.globalCompositeOperation = "source-over";
        accX.drawImage(frameC, 0, 0);
      }
      accX.globalAlpha = 1;
      out.drawImage(accC, 0, 0);
    }
    // HUD + flash + post on the final image
    drawHUD(out, t);
    if (t >= 1 / FPS - EPS && t < 0.3) { out.fillStyle = rgba([255, 236, 200], 0.5 * Math.exp(-(t - 1 / FPS) / 0.06)); out.fillRect(0, 0, W, H); }
    const fl = t >= T.hit && t < T.hit + 1 / FPS - EPS ? 1 : t >= T.hit + 1 / FPS - EPS && t < T.hit + 2 / FPS - EPS ? 0.28 : 0;
    if (fl > 0) { out.fillStyle = rgba(C.ice, fl); out.fillRect(0, 0, W, H); }
    post(out, t);
  }

  // Cover: the lit mark + title, for a still / thumbnail. window.HK.renderCover()
  function renderCover() {
    COVER = true;
    const t = 10.1;
    renderSample(t);
    out.setTransform(1, 0, 0, 1, 0, 0);
    out.globalAlpha = 1;
    out.drawImage(frameC, 0, 0);
    COVER = false;
    out.save();
    out.textBaseline = "alphabetic";
    out.fillStyle = rgba(C.ice);
    out.font = '800 176px "Manrope"';
    out.letterSpacing = "-5px";
    out.fillText("HackAlem", 960, 560);
    out.fillStyle = rgba(C.cyan);
    out.fillText("AI", 960, 724);
    out.fillStyle = rgba(C.sky, 0.95);
    out.font = `700 30px ${MONO}`;
    out.letterSpacing = "7px";
    out.fillText(TXT.tagline, 966, 818);
    out.fillStyle = rgba(C.wall, 0.95);
    out.fillRect(962, 770, 150, 5);
    out.restore();
    post(out, t);
  }

  // ───────────────────────── boot ─────────────────────────
  const loaded = init().then(() => { window.HK.ready = true; render(0); });
  window.HK = { render, renderCover, loaded, ready: false, W, H, T };
  window.__hf = window.__hf || {};
  window.__hf.buildReady = window.__hf.buildReady || {};
  window.__hf.buildReady["hackalem-intro"] = loaded;
  window.addEventListener("hf-seek", (e) => { const t = e.detail.time; if (window.HK.ready) render(t); else loaded.then(() => render(t)); });
})();
