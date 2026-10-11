// Three.js world: glossy cube field, brand beam, haze, dust, light shafts through the carved mark, post chain.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { TexturePass } from "three/addons/postprocessing/TexturePass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { mulberry32 } from "./schedule.js";

export const W = 1920, H = 1080;

export function createWorld(canvas, plan, cues) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.autoClear = true;
  renderer.setClearColor(0x03060d, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(28, W / H, 0.5, 400);

  // ---------- environment (what the glossy cubes reflect): dark studio with a few soft boxes ----------
  const envScene = new THREE.Scene();
  {
    const bg = new THREE.Mesh(new THREE.SphereGeometry(50, 32, 16), new THREE.MeshBasicMaterial({ color: 0x02050b, side: THREE.BackSide }));
    envScene.add(bg);
    const box = (w, h, color, k, pos, look) => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(k), side: THREE.DoubleSide }));
      m.position.set(...pos); m.lookAt(...look); envScene.add(m); return m;
    };
    box(30, 10, 0xdff1ff, 2.2, [-18, 22, 16], [0, 0, 0]);      // key strip, cool white, upper left
    box(12, 36, 0x2f9dff, 1.2, [30, 4, 8], [0, 0, 0]);          // blue blade, right
    box(40, 3, 0x00c8ff, 3, [0, -4, -24], [0, 0, 0]);        // cyan rim low behind
    box(14, 14, 0x0a3d80, 1.2, [-30, -8, 6], [0, 0, 0]);     // dim blue fill, left
    box(24, 6, 0xffffff, 0.9, [4, 30, -6], [0, 0, 0]);         // top spec
  }
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(envScene, 0.06).texture;
  scene.environmentIntensity = 0.55;

  // ---------- cubes ----------
  const N = plan.N;
  const geo = new RoundedBoxGeometry(1, 1, 1, 5, 0.085);
  const aGlow = new THREE.InstancedBufferAttribute(new Float32Array(N * 2), 2);
  const aTint = new THREE.InstancedBufferAttribute(new Float32Array(N * 3), 3);
  aGlow.setUsage(THREE.DynamicDrawUsage); aTint.setUsage(THREE.DynamicDrawUsage);
  geo.setAttribute("aGlow", aGlow); geo.setAttribute("aTint", aTint);
  const mat = new THREE.MeshPhysicalMaterial({
    color: 0x07101f, metalness: 0.62, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.18, envMapIntensity: 0.8,
  });
  mat.onBeforeCompile = (sh) => {
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nattribute vec2 aGlow;\nattribute vec3 aTint;\nvarying vec2 vGlow;\nvarying vec3 vTint;\nvarying vec3 vLocal;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvGlow = aGlow; vTint = aTint; vLocal = position;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\nvarying vec2 vGlow;\nvarying vec3 vTint;\nvarying vec3 vLocal;")
      .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
        {
          float fres = pow(1.0 - clamp(dot(normalize(normal), normalize(vViewPosition)), 0.0, 1.0), 2.2);
          vec3 al = abs(vLocal);
          float m = max(max(al.x, al.y), al.z);
          float rim = smoothstep(0.30, 0.5, m);
          // in-plane distance from the face centre: light pools in the middle of each glass tile
          float inpl = al.x >= al.y && al.x >= al.z ? max(al.y, al.z) : (al.y >= al.z ? max(al.x, al.z) : max(al.x, al.y));
          float pool = 1.0 - smoothstep(0.0, 0.46, inpl);
          vec3 emitCol = mix(vTint, vec3(1.0), clamp(vGlow.y, 0.0, 1.0));
          totalEmissiveRadiance = emitCol * vGlow.x * (0.09 + 0.14 * pool + 0.65 * rim + 0.85 * fres) * (0.78 + 0.22 * clamp(normal.y * 0.7 + 0.5, 0.0, 1.0));
        }`)
      .replace("#include <opaque_fragment>", "outgoingLight = clamp(outgoingLight, vec3(0.0), vec3(10.0)); // half-float safe: an Inf here would smear black through the bloom\n#include <opaque_fragment>");
  };
  const cubesMesh = new THREE.InstancedMesh(geo, mat, N);
  cubesMesh.frustumCulled = false;
  cubesMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  scene.add(cubesMesh);

  // lights: crisp key from upper left, cool fill, blue rim behind
  const key = new THREE.DirectionalLight(0xcfe9ff, 0.5); key.position.set(-14, 20, 30); scene.add(key);
  const rim = new THREE.PointLight(0x009af0, 900, 140, 1.6); rim.position.set(0, 4, -26); scene.add(rim);
  scene.add(new THREE.HemisphereLight(0x1a3a66, 0x02050b, 0.35));
  const glowLight = new THREE.PointLight(0x2a9cff, 0, 90, 1.5); glowLight.position.set(0, 0, 11); scene.add(glowLight);

  // ---------- haze backdrop ----------
  const hazeU = { uBeam: { value: 1 }, uGlow: { value: 0.5 }, uCenter: { value: new THREE.Vector2(0.5, 0.58) }, uPulse: { value: 0 } };
  const haze = new THREE.Mesh(new THREE.PlaneGeometry(520, 292), new THREE.ShaderMaterial({
    uniforms: hazeU, depthWrite: false, depthTest: false, transparent: false,
    vertexShader: "varying vec2 vUv; void main(){ vUv=uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader: `varying vec2 vUv; uniform float uGlow; uniform vec2 uCenter; uniform float uPulse; uniform float uBeam;
      void main(){
        vec2 d = (vUv - uCenter) * vec2(1.35, 1.0);
        float r = length(d);
        vec3 base = vec3(0.0016, 0.0038, 0.0095);
        vec3 deep = vec3(0.0006, 0.0014, 0.0038);
        vec3 glow = vec3(0.003, 0.024, 0.075);
        float g = exp(-r*r*5.5) * uGlow + exp(-r*r*1.6) * uGlow * 0.22;
        vec3 c = mix(deep, base, smoothstep(1.1, 0.0, r)) + glow * g;
        // brand light column from the top of the frame (the hero beam of the site), widening toward the stage
        float yy = vUv.y;
        float cw = mix(0.035, 0.30, pow(1.0 - yy, 0.9)) * 1.0;
        float cx = (vUv.x - 0.5) / cw; float colm = exp(-cx * cx) * smoothstep(0.12, 0.95, yy) * (0.35 + 0.65 * yy);
        c += vec3(0.003, 0.026, 0.080) * colm * uBeam + vec3(0.006, 0.022, 0.05) * colm * colm * uBeam;
        c += vec3(0.01,0.12,0.30) * exp(-r*r*18.0) * uPulse;
        gl_FragColor = vec4(c, 1.0);
      }`,
  }));
  haze.position.set(0, 0, -150); haze.renderOrder = -10; scene.add(haze);

  // ---------- brand beam: volumetric shaft from the top of the hero ----------
  const beamU = { uTime: { value: 0 }, uI: { value: 1 }, uColor: { value: new THREE.Color(0x3aa6ff) }, uCore: { value: new THREE.Color(0xbfe6ff) } };
  const beamMat = new THREE.ShaderMaterial({
    uniforms: beamU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    vertexShader: `varying vec3 vN; varying vec3 vV; varying vec3 vP;
      void main(){ vec4 wp = modelMatrix*vec4(position,1.0); vP = position; vN = normalize(mat3(modelMatrix)*normal); vV = normalize(cameraPosition - wp.xyz);
        gl_Position = projectionMatrix*viewMatrix*wp; }`,
    fragmentShader: `varying vec3 vN; varying vec3 vV; varying vec3 vP; uniform float uTime; uniform float uI; uniform vec3 uColor; uniform vec3 uCore;
      float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }
      float vnoise(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
        return mix(mix(hash(i),hash(i+vec2(1,0)),f.x), mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x), f.y); }
      void main(){
        float facing = clamp(abs(dot(normalize(vN), normalize(vV))), 0.0, 1.0);
        float body = pow(facing, 1.6);
        float h = (vP.y + 31.0) / 62.0;                // 0 bottom … 1 top
        float vert = smoothstep(0.0, 0.5, h) * (0.35 + 0.65*h);
        float ang = atan(vP.x, vP.z);
        float streak = 0.72 + 0.28 * vnoise(vec2(ang*7.0 + uTime*0.05, vP.y*0.05 - uTime*0.12));
        float a = body * vert * streak * uI * 0.07;
        vec3 col = mix(uColor, uCore, pow(facing, 5.0));
        gl_FragColor = vec4(col * a, a);
      }`,
  });
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(3.5, 26, 62, 72, 1, true), beamMat);
  beam.position.set(0, 12, -16); beam.renderOrder = 5; scene.add(beam);

  // ---------- dust motes caught in the light ----------
  const DN = 900;
  const dpos = new Float32Array(DN * 3), dmeta = new Float32Array(DN * 3);
  {
    const r = mulberry32(777);
    for (let i = 0; i < DN; i++) {
      dpos[i * 3] = (r() * 2 - 1) * 46; dpos[i * 3 + 1] = (r() * 2 - 1) * 28; dpos[i * 3 + 2] = -50 + r() * 66;
      dmeta[i * 3] = r(); dmeta[i * 3 + 1] = r(); dmeta[i * 3 + 2] = r();
    }
  }
  const dg = new THREE.BufferGeometry();
  dg.setAttribute("position", new THREE.BufferAttribute(dpos, 3)); dg.setAttribute("aMeta", new THREE.BufferAttribute(dmeta, 3));
  const dustU = { uTime: { value: 0 }, uI: { value: 1 }, uScale: { value: H / (2 * Math.tan((28 * Math.PI) / 360)) } };
  const dust = new THREE.Points(dg, new THREE.ShaderMaterial({
    uniforms: dustU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `attribute vec3 aMeta; uniform float uTime; uniform float uScale; varying float vA;
      void main(){
        vec3 p = position;
        p.y += mod(uTime*(0.25+aMeta.x*0.5) + aMeta.y*60.0, 60.0) - 30.0;
        p.x += sin(uTime*0.3 + aMeta.z*40.0) * 1.2;
        p.z += cos(uTime*0.22 + aMeta.y*30.0) * 1.2;
        vec4 mv = modelViewMatrix * vec4(p,1.0);
        float s = 0.10 + aMeta.z*0.22;
        gl_PointSize = clamp(s * uScale / -mv.z, 1.0, 8.0);
        float beamD = abs(p.x) / (3.2 + (p.y + 56.0) * 0.26);
        vA = (0.08 + 0.45*exp(-beamD*beamD*1.4)) * (0.35 + 0.65*step(0.35, aMeta.x));
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `uniform float uI; varying float vA;
      void main(){ vec2 c = gl_PointCoord - 0.5; float d = length(c); float a = smoothstep(0.5, 0.0, d); gl_FragColor = vec4(vec3(0.45,0.8,1.0) * a * a * vA * uI * 0.9, a*vA); }`,
  }));
  dust.renderOrder = 6; scene.add(dust);

  // ---------- light through the carved mark: backlight + shafts from every void cell ----------
  const voids = [];
  plan.mark.cells; // lit cells; voids are the complement within 16×16
  {
    const lit = new Set(plan.mark.cells.map((c) => c.row * 16 + c.col));
    for (let r = 0; r < 16; r++) for (let c = 0; c < 16; c++) if (!lit.has(r * 16 + c)) voids.push({ x: c - 7.5, y: 7.5 - r });
  }
  const shaftU = { uI: { value: 0 }, uLen: { value: 46 } };
  const shaftGeo = new THREE.BoxGeometry(1, 1, 1);
  shaftGeo.translate(0, 0, 0.5); // z from 0 → 1, scaled to length
  const shaftMat = new THREE.ShaderMaterial({
    uniforms: shaftU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `varying float vZ; varying vec3 vN; varying vec3 vV;
      void main(){ vec4 wp = modelMatrix * instanceMatrix * vec4(position,1.0); vZ = position.z; vN = normalize(mat3(modelMatrix*instanceMatrix) * normal); vV = normalize(cameraPosition - wp.xyz); gl_Position = projectionMatrix * viewMatrix * wp; }`,
    fragmentShader: `uniform float uI; varying float vZ; varying vec3 vN; varying vec3 vV;
      void main(){
        float f = clamp(abs(dot(normalize(vN), normalize(vV))), 0.0, 1.0);
        float side = 0.25 + 0.75 * clamp(1.0 - f, 0.0, 1.0);       // edges of the shaft glow more when seen from the side
        float a = uI * exp(-vZ * 6.0) * (0.45 + 0.4 * side);
        vec3 col = mix(vec3(0.0, 0.45, 1.0), vec3(0.55, 0.93, 1.0), exp(-vZ*8.0));
        gl_FragColor = vec4(col * a * 0.55, a);
      }`,
  });
  const shafts = new THREE.InstancedMesh(shaftGeo, shaftMat, voids.length);
  shafts.frustumCulled = false; shafts.renderOrder = 7; scene.add(shafts);
  // backlight lives only in the void cells (no leak through the seams between blue cubes)
  const backU = { uI: { value: 0 } };
  const back = new THREE.InstancedMesh(new THREE.PlaneGeometry(1.02, 1.02), new THREE.ShaderMaterial({
    uniforms: backU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: "varying float vR; void main(){ vR = length(instanceMatrix[3].xy) / 7.0; gl_Position = projectionMatrix*modelViewMatrix*instanceMatrix*vec4(position,1.0); }",
    fragmentShader: "varying float vR; uniform float uI; void main(){ float a = uI * (1.0 - 0.35 * clamp(vR, 0.0, 1.0)); gl_FragColor = vec4(mix(vec3(0.55,0.93,1.0), vec3(0.0,0.5,1.0), clamp(vR, 0.0, 1.0)) * a, a); }",
  }), voids.length);
  back.frustumCulled = false; back.renderOrder = 3; scene.add(back);

  // ---------- shockwave ring ----------
  const ringU = { uA: { value: 0 } };
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.94, 1.0, 160, 1), new THREE.ShaderMaterial({
    uniforms: ringU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    vertexShader: "void main(){ gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader: "uniform float uA; void main(){ gl_FragColor = vec4(vec3(0.05,0.72,1.0) * uA * 2.4, uA); }",
  }));
  ring.visible = false; ring.renderOrder = 8; scene.add(ring);

  // ---------- post chain ----------
  const rtScene = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, samples: 4, depthBuffer: true });
  const rtFast = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, samples: 0, depthBuffer: true });
  const rtAccum = new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType, depthBuffer: false });
  const accumScene = new THREE.Scene();
  const accumCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const accumMat = new THREE.ShaderMaterial({
    uniforms: { tMap: { value: rtScene.texture }, uW: { value: 1 } }, transparent: true, depthTest: false, depthWrite: false, blending: THREE.CustomBlending,
    blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor, blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneFactor,
    vertexShader: "varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.0,1.0); }",
    fragmentShader: "varying vec2 vUv; uniform sampler2D tMap; uniform float uW; void main(){ vec3 c = clamp(texture2D(tMap, vUv).rgb, 0.0, 60.0); if (!(c.r == c.r && c.g == c.g && c.b == c.b)) c = vec3(0.0); gl_FragColor = vec4(c * uW, 1.0); }",
  });
  accumScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), accumMat));

  const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(W, H, { type: THREE.HalfFloatType }));
  composer.setPixelRatio(1); composer.setSize(W, H);
  const texPass = new TexturePass(rtAccum.texture);
  composer.addPass(texPass);
  const bloom = new UnrealBloomPass(new THREE.Vector2(W / 2, H / 2), 0.4, 0.5, 1.0);
  composer.addPass(bloom);
  const fxU = { uCA: { value: 0 }, uFlash: { value: 0 }, uZoom: { value: 0 }, uVig: { value: 0.7 }, uCenter: { value: new THREE.Vector2(0.5, 0.5) } };
  const fx = new ShaderPass({
    uniforms: { tDiffuse: { value: null }, ...fxU },
    vertexShader: "varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader: `varying vec2 vUv; uniform sampler2D tDiffuse; uniform float uCA; uniform float uFlash; uniform float uZoom; uniform float uVig; uniform vec2 uCenter;
      void main(){
        vec2 d = vUv - uCenter;
        vec3 c = vec3(0.0);
        if (uZoom > 0.0005) {
          for (int i = 0; i < 10; i++) { float k = float(i) / 9.0; vec2 uv = uCenter + d * (1.0 - uZoom * k); c += texture2D(tDiffuse, uv).rgb; }
          c /= 10.0;
        } else {
          vec2 o = d * uCA;
          c = vec3(texture2D(tDiffuse, vUv + o).r, texture2D(tDiffuse, vUv).g, texture2D(tDiffuse, vUv - o).b);
        }
        float vig = 1.0 - uVig * smoothstep(0.35, 1.05, length(d * vec2(1.25, 1.0)));
        c *= vig;
        c += vec3(0.65, 0.88, 1.0) * uFlash;
        gl_FragColor = vec4(c, 1.0);
      }`,
  });
  composer.addPass(fx);
  composer.addPass(new OutputPass());
  const grainU = { uSeed: { value: 0 }, uAmt: { value: 1.5 } };
  const grain = new ShaderPass({
    uniforms: { tDiffuse: { value: null }, ...grainU },
    vertexShader: "varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader: `varying vec2 vUv; uniform sampler2D tDiffuse; uniform float uSeed; uniform float uAmt;
      float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
      void main(){
        vec3 c = texture2D(tDiffuse, vUv).rgb;
        float n = h(vUv * vec2(1920.0, 1080.0) + uSeed) + h(vUv * vec2(1920.0, 1080.0) * 1.7 + uSeed * 1.3) - 1.0; // triangular dither
        float lum = dot(c, vec3(0.299, 0.587, 0.114));
        c += n * (1.6 / 255.0) * uAmt * (1.0 - 0.5 * lum);
        gl_FragColor = vec4(c, 1.0);
      }`,
  });
  composer.addPass(grain);

  return { renderer, scene, camera, cubesMesh, aGlow, aTint, voids, shafts, shaftU, backU, back, hazeU, glowLight, ring, ringU, beamU, dustU, fxU, grainU, bloom, composer, texPass, rtScene, rtFast, rtAccum, accumScene, accumCam, accumMat, rim, key, beam };
}
