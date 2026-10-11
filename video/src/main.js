import * as THREE from "three";
import cues from "../config/cues.js";
import { buildPlan, ease } from "./schedule.js";
import { createWorld, W, H } from "./world.js";

const T = cues.T;
const plan = buildPlan(cues);
const canvas = document.getElementById("stage");
const world = createWorld(canvas, plan, cues);
const { camera, cubesMesh, aGlow, aTint, voids, shafts } = world;

const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
const lerp = (a, b, p) => a + (b - a) * p;

// ---------------- camera path ----------------
// keys: t, distance, yaw (orbit, rad), height, target x/y, fov, ease into this key
const CAM = [
  { t: 0.0, d: 7.4, yaw: 0.20, h: 0.35, tx: 0.9, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 0.15, d: 8.0, yaw: 0.18, h: 0.30, tx: 0.7, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 1.5, d: 35.0, yaw: 0.10, h: 1.2, tx: 0, ty: 0.0, fov: 28, e: "out3" },
  { t: 2.7, d: 33.0, yaw: -0.14, h: 0.6, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },     // slow orbit during the ИДЕЯ hold: parallax against the debris
  { t: 4.05, d: 54.0, yaw: 0.10, h: 1.4, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 5.1, d: 53.0, yaw: -0.10, h: 1.2, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 6.2, d: 63.0, yaw: 0.10, h: 1.0, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 7.2, d: 62.0, yaw: -0.06, h: 0.8, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 8.6, d: 56.0, yaw: 0.0, h: 0.4, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 8.88, d: 52.0, yaw: 0.03, h: 0.2, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 9.02, d: 43.0, yaw: -0.04, h: 0.4, tx: 0, ty: 0.0, fov: 28, e: "out3" },
  { t: 9.5, d: 46.0, yaw: 0.08, h: 0.8, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 10.4, d: 58.0, yaw: 0.0, h: 0.0, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },
  { t: 15.0, d: 58.0, yaw: 0.0, h: 0.0, tx: 0, ty: 0.0, fov: 28, e: "inOut3" },
];
function camAt(t, out, noSway = false) {
  let k = 0;
  while (k < CAM.length - 2 && t >= CAM[k + 1].t) k++;
  const a = CAM[k], b = CAM[k + 1];
  const p = clamp01((t - a.t) / (b.t - a.t));
  const e = ease[b.e](p);
  const d = lerp(a.d, b.d, e), yaw = lerp(a.yaw, b.yaw, e), h = lerp(a.h, b.h, e), tx = lerp(a.tx, b.tx, e), ty = lerp(a.ty, b.ty, e);
  out.pos.set(tx + d * Math.sin(yaw), ty + h * (d / 30), d * Math.cos(yaw));
  out.target.set(tx, ty, 0);
  out.fov = lerp(a.fov, b.fov, e);
  // slow breathing so nothing is ever perfectly still
  const sw = noSway ? 0 : Math.min(1, t / 0.4) * (t > 12.5 ? Math.max(0, 1 - (t - 12.5) / 2.0) * 0.6 + 0.4 : 1);
  out.pos.x += Math.sin(t * 0.9) * 0.012 * d * sw; out.pos.y += Math.sin(t * 0.7 + 1.0) * 0.008 * d * sw;
  return out;
}
const camState = { pos: new THREE.Vector3(), target: new THREE.Vector3(), fov: 28 };

// ---------------- scene state at time tt ----------------
const st = { q: [0, 0, 0, 1], x: 0, y: 0, z: 0, s: 1, sz: 1, glow: 0, white: 0, tint: [0, 0.6, 1], stage: -1 };
const M = new THREE.Matrix4(), P = new THREE.Vector3(), Q = new THREE.Quaternion(), S = new THREE.Vector3();
const wallS = { x: 0, y: 0, s: 1, flat: 0 };
const HIT = T.hit;
const TW = (window.HK_TWEAK = { beamK: 1, glowK: 1 }); // live knobs for look-dev only (defaults are the shipped values)

function setScene(tt) {
  for (let i = 0; i < plan.cubes.length; i++) {
    plan.state(plan.cubes[i], tt, st);
    const fill = st.stage === 3 ? 0.985 : st.stage >= 0 ? 0.94 : 1; // gaps: words slightly open, the mark nearly closed
    const hide = tt > T.lockMove[1] + 0.1 ? 0 : 1; // the flat cubes are replaced by the original vector mark
    P.set(st.x, st.y, st.z); Q.set(st.q[0], st.q[1], st.q[2], st.q[3]);
    const s = st.s * fill * hide;
    S.set(s, s, s * st.sz);
    M.compose(P, Q, S); cubesMesh.setMatrixAt(i, M);
    aGlow.setXY(i, st.glow, st.white);
    aTint.setXYZ(i, st.tint[0], st.tint[1], st.tint[2]);
  }
  cubesMesh.instanceMatrix.needsUpdate = true; aGlow.needsUpdate = true; aTint.needsUpdate = true;

  // shafts follow the wall transform
  plan.wall(tt, wallS);
  for (let k = 0; k < voids.length; k++) {
    P.set(voids[k].x * wallS.s + wallS.x, voids[k].y * wallS.s + wallS.y, -0.55);
    Q.identity(); S.set(wallS.s, wallS.s, 18 * wallS.s); M.compose(P, Q, S); shafts.setMatrixAt(k, M);
    P.z = -0.6; S.set(wallS.s, wallS.s, 1); M.compose(P, Q, S); world.back.setMatrixAt(k, M);
  }
  shafts.instanceMatrix.needsUpdate = true; world.back.instanceMatrix.needsUpdate = true;

  // intensities
  const th = tt - HIT;
  const hitPulse = th >= 0 ? Math.exp(-th * 2.2) : 0;
  const hitSharp = th >= 0 ? Math.exp(-th * 9) : 0;
  const lockFade = 1 - ease.smooth(clamp01((tt - 9.6) / 1.0));
  const build = ease.smooth(clamp01((tt - T.mark.t0) / (T.inhale[0] - T.mark.t0)));
  const inhale = tt >= T.inhale[0] && tt < HIT ? ease.smooth(clamp01((tt - T.inhale[0]) / (HIT - T.inhale[0]))) : 0;
  const figFade = 1 - ease.smooth(clamp01((tt - HIT - 0.4) / 0.7));       // the light through the figure is gone before the glide: the carved figure ends dark, as in the logo
  const seep = tt >= HIT - 0.12 && tt < HIT ? 0.25 * ease.smooth(clamp01((tt - (HIT - 0.12)) / 0.12)) : 0;   // light starts leaking 3 frames before the hit
  world.shaftU.uI.value = th >= 0 ? 0.7 * Math.exp(-th * 3.2) * (1 - ease.smooth(clamp01((th - 0.35) / 0.35))) : 0;   // additive boxes overlap ~20× at oblique angles: keep it low or they clip to white dashes
  world.backU.uI.value = th >= 0 ? (1.35 * Math.exp(-th * 4.2) + 0.5 * Math.exp(-th * 1.6)) * figFade : (0.10 * build * (1 - inhale) + seep);
  shafts.visible = world.shaftU.uI.value > 0.001; world.back.visible = world.backU.uI.value > 0.001; // never drawn while off: at the opening the camera sits inside their volume
  world.hazeU.uGlow.value = (0.20 + 0.14 * build * (1 - inhale) + 0.10 * hitPulse) * (1 + (tt > 11 ? 0.06 * Math.sin(tt * 1.7) : 0));
  world.hazeU.uPulse.value = 0.1 * hitPulse;
  world.beamU.uI.value = TW.beamK * (0.9 + 0.35 * build * (1 - inhale) + 0.8 * hitPulse);
  world.hazeU.uBeam.value = TW.beamK * (1 + 1.0 * hitPulse);
  world.beamU.uTime.value = tt; world.dustU.uTime.value = tt;
  world.dustU.uI.value = 0.9 + 0.8 * hitPulse;
  world.bloom.strength = 0.5 + 0.1 * build;
  world.fxU.uFlash.value = th >= 0 && th < 0.2 ? 0.05 * Math.exp(-th * 22) : 0;
  world.fxU.uZoom.value = th >= 0 ? 0.03 * Math.exp(-th * 12) : 0;
  world.fxU.uCA.value = 0.0012 + (th >= 0 ? 0.004 * Math.exp(-th * 10) : 0);
  world.rim.intensity = 260 + 300 * hitPulse + 140 * build;
  // shockwave ring through the wall plane
  world.ring.visible = th >= 0 && th < 1.0;
  if (world.ring.visible) { const R = 2 + th * 62; world.ring.scale.set(R, R, 1); world.ring.position.set(wallS.x, wallS.y, 1.2); world.ringU.uA.value = 1.0 * Math.exp(-th * 4.0); }

  { // the lit cubes light up their surroundings (the dark debris around the word picks up blue edges)
    let lit = 0; for (let i = 0; i < plan.cubes.length; i++) if (aGlow.getX(i) > 0.7) lit++;
    world.glowLight.intensity = TW.glowK * (25 + 0.9 * lit + 150 * hitSharp) * (tt > HIT ? 1 - ease.smooth(clamp01((tt - HIT - 0.4) / 0.5)) : 1);
  }
  camAt(tt, camState);
  if (th >= 0 && th < 0.3) { const k = Math.exp(-th * 16); camState.pos.x += 0.22 * k * Math.sin(th * 120); camState.pos.y += 0.18 * k * Math.cos(th * 105); }
  camera.position.copy(camState.pos); camera.fov = camState.fov; camera.updateProjectionMatrix();
  camera.lookAt(camState.target);
  camera.updateMatrixWorld();
}

// frames that contain fast motion get sub-frame samples (180° shutter)
const FAST = [[2.65, 4.15], [5.05, 6.35], [7.15, 8.55], [8.88, 9.5]];
function samplesFor(tt) { if (tt > 0.1 && tt < 1.55) return 16; for (const [a, b] of FAST) if (tt > a && tt < b) return 10; return 1; }
const SHUTTER = 0.4 / 30;   // 144° shutter

const px1 = new Uint8Array(4);
function renderAt(t, opts = {}) {
  const K = opts.samples || samplesFor(t);
  const r = world.renderer;
  r.setRenderTarget(world.rtAccum); r.setClearColor(0x000000, 1); r.clear(true, false, false);
  world.accumMat.uniforms.uW.value = 1 / K;
  const rt = K > 1 ? world.rtFast : world.rtScene; world.accumMat.uniforms.tMap.value = rt.texture;
  for (let k = 0; k < K; k++) {
    const tt = K === 1 ? t : t + ((k + 0.5) / K - 0.5) * SHUTTER;
    setScene(Math.max(0, tt));
    r.setRenderTarget(rt); r.setClearColor(0x03060d, 1); r.clear(true, true, true);
    r.render(world.scene, camera);
    r.setRenderTarget(world.rtAccum); r.autoClear = false;
    r.render(world.accumScene, world.accumCam);
    r.autoClear = true;
  }
  r.setRenderTarget(null);
  world.grainU.uSeed.value = (Math.round(t * 30) % 997) * 1.371;
  world.composer.render();
  overlay(t);
  const gl = r.getContext(); gl.finish(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px1); // forces the GPU queue to drain before the capture
}

// ---------------- DOM overlay (brand bug, title, tagline, final vector mark) ----------------
const $ = (id) => document.getElementById(id);
const bug = $("bug"), title = $("title"), tag = $("tagline"), rule = $("rule"), markFinal = $("markFinal");
const titleLetters = [...title.querySelectorAll(".ch")];
const tagLetters = [...tag.querySelectorAll(".tc")];

function layoutOverlay() {
  // final wall rectangle from the real camera, so the vector mark sits exactly on the flat cubes
  const t = 14.0; camAt(t, camState, true); camera.position.copy(camState.pos); camera.lookAt(camState.target); camera.updateMatrixWorld(); camera.updateProjectionMatrix();
  const L = cues.lockup, half = 8 * L.wallS;
  const proj = (x, y) => { const v = new THREE.Vector3(L.wallX + x, L.wallY + y, 0).project(camera); return [(v.x * 0.5 + 0.5) * W, (-v.y * 0.5 + 0.5) * H]; };
  const [x0, y0] = proj(-half, half), [x1, y1] = proj(half, -half);
  // lockup grid: rule and tagline are exactly as wide as the title's ink, so the three right edges line up
  // (box→ink corrections measured on a still: title ink = box − 25 px, tagline ink = box-fit + 15 px)
  const tw = title.getBoundingClientRect().width;
  tag.style.fontSize = "49px";
  const gw = tag.getBoundingClientRect().width - 0.06 * 49;
  const fs0 = 49 * tw / gw;
  tag.style.fontSize = (fs0 * (tw - 25) / (tw + 15) * 0.9974).toFixed(2) + "px";
  rule.style.width = (tw - 25).toFixed(1) + "px";
    const box = { left: x0 + "px", top: y0 + "px", width: x1 - x0 + "px", height: y1 - y0 + "px" };
  Object.assign(markFinal.style, box); Object.assign($("sheenWrap").style, box);
  window.HK.markRect = { x0, y0, x1, y1 };
}

function overlay(t) {
  // frame 0 is already branded: bug + corner label
  const [cf0, cf1] = T.cornerFade;
  const fadeBug = 1 - ease.smooth(clamp01((t - cf0) / (cf1 - cf0)));
  bug.style.opacity = (0.95 * fadeBug).toFixed(3);
  // title: letter-by-letter rise out of a soft blur
  const [a, b] = T.title;
  titleLetters.forEach((el, i) => {
    const p = ease.out5(clamp01((t - a - i * 0.045) / 0.55));
    el.style.opacity = p.toFixed(3);
    el.style.transform = `translateY(${((1 - p) * 0.42).toFixed(3)}em)`;
    el.style.filter = p < 1 ? `blur(${((1 - p) * 14).toFixed(2)}px)` : "none";
  });
  const [ta, tb] = T.tagline;
  tagLetters.forEach((el, i) => {
    const p = ease.out3(clamp01((t - ta - i * 0.018) / 0.35));
    el.style.opacity = p.toFixed(3);
  });
  const [ra, rb] = T.rule;
  rule.style.transform = `scaleX(${ease.inOut3(clamp01((t - ra) / (rb - ra))).toFixed(4)})`;
  rule.style.opacity = t >= ra ? "1" : "0";
  // vector mark crossfade over the flat cubes
  const fa = T.lockMove[1] - 0.22, fb = T.lockMove[1] + 0.04;
  markFinal.style.opacity = ease.smooth(clamp01((t - fa) / (fb - fa))).toFixed(3);
  // two soft diagonal sheens across the vector mark (only on its tiles, via the mark's own alpha as a mask)
  const sheen = (t0) => clamp01((t - t0) / 0.9);
  const sw1 = sheen(T.sweep), sw2 = sheen(T.sweep2);
  const wrap = $("sheenWrap");
  const sv = (sw) => (sw > 0 && sw < 1 ? Math.sin(sw * Math.PI) : 0);
  wrap.style.opacity = Math.min(1, 0.95 * Math.max(sv(sw1), sv(sw2))).toFixed(3);
  const swp = sw1 > 0 && sw1 < 1 ? sw1 : sw2;
  $("sheen").style.transform = `translateX(${lerp(-70, 190, ease.inOut3(swp)).toFixed(1)}%) skewX(-12deg)`;
  // the hold is never a still: a very slow push-in on the whole lockup (mark, sheen and type share one transform)
  const hold = clamp01((t - 11.0) / 4.0), k = 1 + 0.014 * ease.smooth(hold);
  const tf = `translate(${(Math.sin(t * 0.5) * 2.5).toFixed(2)}px, ${(Math.cos(t * 0.4) * 1.8).toFixed(2)}px) scale(${k.toFixed(5)})`;
  [markFinal, wrap, $("lock")].forEach((el) => { el.style.transformOrigin = (960 - (parseFloat(el.style.left) || (el.id === "lock" ? 640 : 0))) + "px " + (540 - (parseFloat(el.style.top) || 0)) + "px"; el.style.transform = tf; });
}

window.HK = { ready: false, renderAt, W, H, plan, camAt, setScene, world, THREE };
window.addEventListener("hf-seek", (e) => renderAt(e.detail.time));

const fontsReady = document.fonts ? Promise.all([
  document.fonts.load("800 100px Manrope", "HackAlem AI"), document.fonts.load("800 100px Manrope", "ИДЕЯ"),
  document.fonts.load("500 40px 'JetBrains Mono'", "AGENTIC-AI ХАКАТОН · АСТАНА"), document.fonts.load("800 36px Manrope", "HackAlem AI"), document.fonts.ready,
]) : Promise.resolve();
window.__hf = window.__hf || {}; window.__hf.buildReady = window.__hf.buildReady || {};
window.__hf.buildReady["hackalem-v2"] = (async () => {
  await fontsReady;
  await Promise.all([$("bugMark").decode?.(), markFinal.decode?.()].filter(Boolean));
  layoutOverlay();
  renderAt(window.__hfThreeTime || 0);
  window.HK.ready = true;
})();
