#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HackAlem AI — intro v2: sound (numpy synthesis + Spotify pedalboard effects; optional CC0 samples).

    python3 audio/build_audio.py          →  assets/audio/hackalem-intro-mix.wav  (48 kHz, stereo, 24-bit, 720000 samples)

Everything is derived from config/cues.json + config/events.json (the same choreography the picture uses):
cubes landing → glass ticks, word completes → chord stabs, fly-through → risers, the hit → a layered impact
and the D-minor→D-major resolution, title letters → soft sparkles. No Math.random: every voice has a named seed.

Design goals after the v1 review (bass-heavy, thin, toy-like): weight in 150 Hz–4 kHz instead of sub, real reverb
(Freeverb via pedalboard), detuned saw/FM-bell timbres instead of 8-bit blips, a mid-range hook on frame 0,
a build→hit contrast of ≥7 LU, and a master chain that keeps the true peak under the AAC limit.
"""
from __future__ import annotations

import hashlib, json, math, os, re, subprocess, sys, tempfile, time

import numpy as np
from pedalboard import (Compressor, Gain, HighpassFilter, HighShelfFilter, LowpassFilter, LowShelfFilter, Pedalboard,
                        PeakFilter, Reverb)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dsp  # noqa: E402
from dsp import (SR, N, S, db, rng, note, tvec, ease, curve, pan_mono, svf, svf_st, fm_bell, saw_pluck, glass_ping,  # noqa: E402
                 supersaw, pad_note, kick_drum, sub_tone, noise_sweep, env_exp, limiter, soft_clip, integrated_lufs,
                 true_peak_lin, write_wav24, aac_probe, oversample4)

ROOT = os.path.dirname(HERE)
CUES = json.load(open(os.path.join(ROOT, "config", "cues.json"), encoding="utf-8"))
EV = json.load(open(os.path.join(ROOT, "config", "events.json"), encoding="utf-8"))
SAMPLES_DIR = os.path.join(HERE, "samples")
OUT_WAV = os.path.join(ROOT, "assets", "audio", "hackalem-intro-mix.wav")
MANIFEST = os.path.join(HERE, "events_manifest.json")

T = CUES["T"]
HIT = float(T["hit"])
INHALE = T["inhale"]
BPM = float(CUES["meta"]["bpm"])
BEAT = 60.0 / BPM
S16 = BEAT / 4.0
DUR = float(CUES["meta"]["duration"])
TARGET_LUFS = -14.5
PRE_DB = -5.5          # everything before the hit sits this much lower (build→hit contrast), except the frame-0 hook and the risers
TRUE_PEAK_CEIL_DB = -1.4
AAC_TP_LIMIT_DB = -1.75


def pre_db(t):
    """Everything before the hit sits lower, and steps up with each word (idea → team → agent → mark): the sense of development comes from level too."""
    if t < float(T["team"]["t0"]):
        return PRE_DB - 2.0
    if t < float(T["agent"]["t0"]):
        return PRE_DB - 0.5
    if t < float(T["mark"]["t0"]):
        return PRE_DB + 0.8
    return PRE_DB + 2.0


# ---------------------------------------------------------------------------------------------- mixing bus
class Bus:
    def __init__(self):
        self.dry = np.zeros((2, N))
        self.room = np.zeros((2, N))
        self.hall = np.zeros((2, N))
        self.keep = np.zeros((2, N))   # not ducked in the inhale (risers, reverse swell)
        self.log = []

    def put(self, sig, t, gain=0.0, pan=0.0, room=0.0, hall=0.0, label="", tail_ms=6.0, keep=False, fade_in_ms=0.0):
        sig = np.asarray(sig, dtype=np.float64)
        if sig.ndim == 1:
            sig = pan_mono(sig, pan)
        else:
            # stereo input: balance only
            th = (np.clip(pan, -1, 1) + 1.0) * np.pi / 4.0
            sig = sig * np.array([[math.cos(th) * math.sqrt(2)], [math.sin(th) * math.sqrt(2)]])
        i0 = S(t)
        if i0 >= N:
            return
        n = min(sig.shape[1], N - i0)
        if 0.5 < t < HIT - 0.01 and not keep:
            gain += pre_db(t)
        x = sig[:, :n] * float(db(gain))
        kf = min(n, int(fade_in_ms * 1e-3 * SR))
        if kf > 1:
            x[:, :kf] *= np.linspace(0, 1, kf)[None, :]
        k = min(n, int(tail_ms * 1e-3 * SR))
        if k > 1 and i0 + n < N:
            x[:, -k:] *= np.linspace(1, 0, k)[None, :]
        (self.keep if keep else self.dry)[:, i0:i0 + n] += x
        if room:
            self.room[:, i0:i0 + n] += x * room
        if hall:
            self.hall[:, i0:i0 + n] += x * hall
        self.log.append({"t": round(float(t), 4), "sample": i0, "label": label, "gain_db": round(float(gain), 2)})


def verb(x, room_size, damping, width=1.0, predelay=0.0):
    if predelay:
        k = int(predelay * SR)
        x = np.pad(x, ((0, 0), (k, 0)))[:, :N]
    b = Pedalboard([Reverb(room_size=room_size, damping=damping, wet_level=1.0, dry_level=0.0, width=width)])
    return b(x.astype(np.float32), SR).astype(np.float64)


# ---------------------------------------------------------------------------------------------- musical map
T_TEAM, T_AGENT, T_MARK = float(T["team"]["t0"]), float(T["agent"]["t0"]), float(T["mark"]["t0"])
CHORDS = [  # (from, to, tones) — D minor world; the hit resolves to D major; boundaries follow the picture's word changes
    (0.0, T_TEAM, ["D", "F", "A", "C", "E"]),        # Dm9      idea
    (T_TEAM, T_AGENT, ["Bb", "D", "F", "A"]),        # Bbmaj7   team
    (T_AGENT, T_MARK, ["G", "Bb", "D", "F", "A"]),   # Gm9      agent
    (T_MARK, HIT, ["A", "C#", "E", "G", "B"]),       # A9       the dominant: everything leans on the hit
    (HIT, 99.0, ["D", "F#", "A", "C#", "E"]),        # Dmaj9    resolution
]
ROOTS = {0: "D2", 1: "Bb1", 2: "G1", 3: "A1", 4: "D2"}


def seg_at(t):
    for i, (a, b, tones) in enumerate(CHORDS):
        if a <= t < b:
            return i, tones
    return len(CHORDS) - 1, CHORDS[-1][2]


def ladder(tones, octs):
    names = [f"{n}{o}" for o in octs for n in tones]
    return sorted(names, key=note)


def load_sample(name):
    p = os.path.join(SAMPLES_DIR, name)
    if not os.path.exists(p):
        return None
    import soundfile as sf
    x, sr = sf.read(p, always_2d=True)
    if sr != SR:
        import scipy.signal as ss
        x = ss.resample_poly(x, SR, sr, axis=0)
    return x.T.copy()


_SMP = {}
USE_SAMPLES = os.environ.get("HK_NO_SAMPLES") != "1"


def smp(name, pitch_to=None, max_ratio=1.5):
    """Kenney CC0 sample (48 kHz); optionally re-pitched by resampling so tonal dings sit in D."""
    key = (name, pitch_to)
    if key in _SMP:
        return _SMP[key]
    x = load_sample(name + ".wav")
    if x is None or not USE_SAMPLES:
        _SMP[key] = None
        return None
    x = x.mean(axis=0)
    if pitch_to:
        n = min(len(x), int(0.25 * SR))
        spec = np.abs(np.fft.rfft(x[:n] * np.hanning(n), 1 << 16))
        fpk = np.argmax(spec[40:]) + 40
        f0 = fpk * SR / (1 << 16)
        ratio = float(np.clip(note(pitch_to) / f0, 1 / max_ratio, max_ratio))
        import scipy.signal as ss
        x = ss.resample(x, int(len(x) / ratio))
    _SMP[key] = x
    return x


def addv(a, b, k=1.0):
    n = max(len(a), len(b))
    out = np.zeros(n)
    out[:len(a)] += a
    out[:len(b)] += k * b
    return out


def tick_voice(f, name, bright=1.0):
    """A glassy 'tile lands' tick: short inharmonic ping + a soft click."""
    y = glass_ping(f, 0.5, tau=0.16 * (0.8 + 0.4 * bright), name=name)
    n = len(y)
    t = tvec(n)
    ck = svf(rng(name + "c").standard_normal(n), 4200.0, 1.1, "bp") * np.exp(-t / 0.0035) * 0.35
    return y + ck


def wood_tock(f0, name):
    """Soft low-mid 'thud' that makes a landing feel physical without piling up sub."""
    n = int(0.16 * SR)
    t = tvec(n)
    fr = f0 * (0.65 + 0.35 * np.exp(-t / 0.02))
    y = np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-t / 0.035)
    y += 0.25 * svf(rng(name).standard_normal(n), 900.0, 0.8, "bp") * np.exp(-t / 0.008)
    return y * np.minimum(1.0, t / 0.0008)


# ---------------------------------------------------------------------------------------------- score
def score(bus: Bus):
    r = np.random.default_rng(7)

    # ---- 0. frame-0 hook: bell + soft body thump, mid-range (it must survive a phone speaker) ----
    hook = fm_bell(note("D5"), 1.8, ratio=2.0, index=2.2, tau_i=0.28, tau_a=0.9, click=0.2, name="hook1")
    hook = addv(hook, fm_bell(note("A5"), 1.6, ratio=2.0, index=1.6, tau_i=0.2, tau_a=0.7, click=0.0, name="hook2"), 0.55)
    hook = addv(hook, glass_ping(note("D6"), 1.6, tau=0.7, name="hook3"), 0.30)
    bus.put(hook, 0.0, gain=-19.0, pan=0.0, room=0.5, hall=0.6, label="hook:bell", tail_ms=40, fade_in_ms=4)
    d = smp("ui_ding_k_confirmation_001", pitch_to="D5")
    if d is not None:
        bus.put(d, 0.0, gain=-22.0, room=0.3, hall=0.5, label="hook:ding(kenney CC0)", fade_in_ms=4)
    br = noise_sweep(1.2, 700.0, 6500.0, q=0.9, name="hookswell", mode="bp", wide=True, ampfn=lambda u: np.clip(u, 0, 1) ** 1.6 * np.minimum(1.0, (1.0 - np.clip(u, 0, 1)) * 5.0))
    bus.put(br, 0.15, gain=-23.0, hall=0.4, label="hook:swell", tail_ms=40)
    body = kick_drum(dur=0.38, f0=210.0, f1=96.0, tau_p=0.03, tau_a=0.12, click=0.5, drive=1.7, name="hookk")
    bus.put(body, 0.0, gain=-18.0, room=0.15, label="hook:body", fade_in_ms=3)
    air = noise_sweep(0.55, 900.0, 7000.0, q=0.9, name="hookair", mode="bp", wide=True, ampfn=lambda u: np.sin(np.pi * np.minimum(u * 1.0, 1.0)) ** 2)
    bus.put(air, 0.0, gain=-27.0, hall=0.5, label="hook:air", tail_ms=30, fade_in_ms=4)

    # ---- 1. pads: chord per segment, slowly opening filter; the bed never goes silent before the hit ----
    pad_levels = [-23.0, -21.5, -20.0, -18.5]
    for si, (a, b, tones) in enumerate(CHORDS[:4]):
        dur = (b - a) + 1.4
        mix = np.zeros((2, int(dur * SR)))
        for k, nm in enumerate(ladder(tones, (3, 4))):
            mix += pad_note(note(nm), dur, f"pad{si}{k}", voices=3, spread=0.9, detune_c=7.0, harmonics=(1.0, 0.55, 0.3, 0.18, 0.1))
        fc = curve([(0, 700.0 + 500 * si), (dur, 2600.0 + 900 * si)], log=True, n=mix.shape[1])
        mix = np.stack([svf(mix[0], fc, 0.8, "lp"), svf(mix[1], fc, 0.8, "lp")])
        env = curve([(0, 0.0), (0.6, 1.0), (dur - 1.4, 1.0), (dur, 0.0)], n=mix.shape[1])
        bus.put(mix * env / math.sqrt(len(tones)), a, gain=pad_levels[si], room=0.25, hall=0.5, label=f"pad:{si}", tail_ms=2)

    # ---- 2. soft pulse: body kick on the beat from bar 2, firmer in the build; bass note per chord ----
    t = 1.6
    while t < HIT - 0.45:
        lvl = -18.0 if t < T_AGENT else (-13.0 if t < T_MARK else -10.0)
        k = kick_drum(dur=0.3, f0=190.0, f1=84.0, tau_p=0.026, tau_a=0.1, click=0.35, drive=1.6, name=f"k{t:.2f}")
        bus.put(k, t, gain=lvl, room=0.12, label="kick")
        t += BEAT
    for si, (a, b, tones) in enumerate(CHORDS[:4]):
        if a < 1.6:
            continue
        b_ = sub_tone(0.55, note(ROOTS[si]) * 2, None, harm=0.55, drive=2.0)
        t0 = a
        while t0 < min(b, HIT - 0.4):
            bus.put(b_ * np.exp(-tvec(len(b_)) / 0.30), t0, gain=(-15.0 if t0 < T_AGENT else -11.0), label="bass", tail_ms=10)
            t0 += BEAT * 2

    # ---- 3. arpeggio (detuned saw plucks): 8ths in act I, 16ths after; the filter opens as the story grows ----
    pat = [0, 2, 1, 3, 2, 4, 3, 2]
    t = 0.4
    idx = 0
    while t < HIT - 0.55:
        si, tones = seg_at(t)
        lad = ladder(tones, (4, 5))
        step = 0.2 if t < T_MARK else S16
        nm = lad[pat[idx % 8] % len(lad)] if si != 3 else lad[(pat[idx % 8] + 1) % len(lad)]
        prog = min(1.0, t / (HIT - 0.55))
        fc0 = 1500.0 + 6500.0 * prog
        y = saw_pluck(note(nm), 0.5, fc0=fc0, fc1=480.0 + 500 * prog, tau_f=0.10, tau_a=0.22, detune=9.0, q=1.0)
        lvl = -35.0 + 12.0 * prog + (3.0 if (idx % 4 == 0) else 0.0)
        bus.put(y, t, gain=lvl, pan=0.5 * math.sin(idx * 0.9), room=0.3, hall=0.25, label=f"arp:{nm}")
        t += step
        idx += 1

    # ---- 4. landings: a glass tick (pitched from the current chord, rising across the word) + a soft tock ----
    for ev in EV["landings"]:
        t, cnt, stg = ev["t"], ev["count"], ev["stage"]
        st = EV["stages"][stg]
        prog = (t - (st["t0"] + st["dur"])) / max(0.05, st["t1"] - st["t0"] - st["dur"])
        prog = float(np.clip(prog, 0.0, 1.0))
        si, tones = seg_at(t - 0.05)
        lad = ladder(tones, (5, 6))
        wob = {"idea": 0.0, "team": 0.10 * math.sin(t * 21.0), "agent": 0.14 * math.sin(t * 13.0 + 1.0), "mark": 0.0}[stg]
        nm = lad[int(np.clip(round((prog + wob) * (len(lad) - 1)), 0, len(lad) - 1))]
        t = t + float(np.random.default_rng(int(t * 1000)).uniform(-0.012, 0.012))   # humanise: the ladders are not on a rigid 100 ms grid
        vel = min(1.0, math.sqrt(cnt / 16.0))
        pan = -0.7 + 1.4 * prog if stg != "mark" else 0.0
        bus.put(tick_voice(note(nm), f"tk{stg}{t:.1f}", bright=0.7 + 0.5 * prog), t, gain=-23.0 + 8.0 * vel + 3 * prog + {'idea': -3.0, 'team': 0.0, 'agent': 2.0, 'mark': 4.0}[stg], pan=pan, room=0.35, hall=0.3, label=f"land:{stg}:{nm}")
        bus.put(wood_tock(note(lad[0]) * 0.5, f"tock{t:.2f}"), t, gain=-22.0 + 7.0 * vel, pan=pan * 0.4, room=0.2, label="tock")
        c_ = smp("ui_click_k_select_001" if int(t * 10) % 2 else "ui_click_k_tick_004")
        if c_ is not None:
            bus.put(c_, t, gain=-27.0 + 7.0 * vel, pan=pan, room=0.25, label="land:click(kenney CC0)")

    # ---- 5. word completes: chord stab + bell accent (quiet → bigger) ----
    for tt, lvl, oct_ in ((1.5, -19.0, 4), (3.7, -16.5, 4), (5.9, -14.0, 4)):
        si, tones = seg_at(tt - 0.05)
        for k, nm in enumerate(ladder(tones, (oct_, oct_ + 1))[:6]):
            y = saw_pluck(note(nm), 1.0, fc0=7000.0, fc1=900.0, tau_f=0.2, tau_a=0.5, detune=10.0, q=0.8)
            bus.put(y, tt, gain=lvl - 3.0, pan=-0.6 + 0.24 * k, room=0.3, hall=0.55, label=f"stab:{nm}")
        bus.put(fm_bell(note(ladder(tones, (6,))[2]), 1.4, ratio=3.0, index=2.0, tau_a=0.7, name=f"acc{tt}"), tt, gain=lvl - 3.0, hall=0.6, label="stab:bell")

    # ---- 6. flights: whoosh / riser under each departure; the last one is the build ----
    for (a, b, hi, lv) in ((T_TEAM, T_TEAM + 0.9, 5200.0, -17.0), (T_AGENT, T_AGENT + 0.7, 6500.0, -15.0)):
        w = noise_sweep(b - a, 300.0, hi, q=1.0, name=f"wh{a}", mode="bp", wide=True, ampfn=lambda u: np.sin(np.pi * np.clip(u, 0, 1) ** 0.8) ** 1.5)
        bus.put(w, a, gain=lv, hall=0.4, label="whoosh")
    rise = noise_sweep(HIT - T_MARK - 0.05, 250.0, 11000.0, q=0.9, name="rise", mode="bp", wide=True, ampfn=lambda u: np.clip(u, 0, 1) ** 2.2)
    bus.put(rise, T_MARK, gain=-24.0, hall=0.35, label="riser:noise", tail_ms=40, keep=True)
    n_r = int((HIT - T_MARK - 0.05) * SR)
    fr = curve([(0, 180.0), (n_r / SR, 1500.0)], log=True, n=n_r)
    ph = np.cumsum(fr) / SR
    saw = 2 * (ph - np.floor(ph + 0.5))
    saw = svf(saw, curve([(0, 500.0), (n_r / SR, 5200.0)], log=True, n=n_r), 1.1, "lp")
    saw *= curve([(0, 0.0), (n_r / SR, 1.0)], n=n_r) ** 2
    bus.put(saw, T_MARK, gain=-30.0, pan=0.0, room=0.2, hall=0.3, label="riser:saw", tail_ms=30, keep=True)
    # snare-ish 16th roll
    t_r0 = T_MARK + 0.2
    t = t_r0
    k = 0
    while t < INHALE[0]:
        n = int(0.09 * SR)
        s_ = svf(rng(f"roll{k}").standard_normal(n), 2800.0, 0.9, "hp") * np.exp(-tvec(n) / 0.02)
        bus.put(s_, t, gain=-31.0 + 9.0 * (t - t_r0) / max(0.2, INHALE[0] - t_r0), pan=0.2 * (k % 2 * 2 - 1), room=0.2, label="roll")
        t += S16
        k += 1

    # ---- 7. inhale: reverse swell of the hit's crash, then a 60 ms hole right before the hit ----
    crash = svf(rng("crash").standard_normal(int(2.2 * SR)), 2500.0, 0.8, "hp")
    crash *= np.exp(-tvec(len(crash)) / 0.7)
    rev = crash[::-1].copy()
    rev = rev[-int(1.3 * SR):]
    bus.put(np.stack([rev, rev[::-1]]), HIT - 0.05 - len(rev) / SR, gain=-21.0, hall=0.3, label="reverse swell", tail_ms=2, keep=True)

    # ---- 8. THE HIT (8.4): body + crack + metal + crash + chord bloom + sub (the sub is a guest, not the host) ----
    thump = kick_drum(dur=0.7, f0=230.0, f1=72.0, tau_p=0.045, tau_a=0.24, click=0.6, drive=2.4, name="hitk")
    bus.put(thump, HIT, gain=-3.0, room=0.2, hall=0.2, label="hit:thump")
    boom = sub_tone(2.2, 74.0, 38.0, tau_f=0.35, harm=0.5, drive=1.6) * np.exp(-tvec(int(2.2 * SR)) / 0.7)
    bus.put(boom * np.minimum(1.0, tvec(len(boom)) / 0.004), HIT, gain=-10.0, label="hit:sub", tail_ms=60)
    nb = int(0.5 * SR)
    mid_burst = svf(rng("hitmid").standard_normal(nb), 380.0, 0.9, "bp") * np.exp(-tvec(nb) / 0.12)
    bus.put(mid_burst * np.minimum(1.0, tvec(len(mid_burst)) / 0.003), HIT + 0.01, gain=-5.0, room=0.25, hall=0.3, label="hit:midburst")
    crack = svf(rng("hitcrack").standard_normal(nb), 1800.0, 0.7, "hp") * np.exp(-tvec(nb) / 0.05) * np.minimum(1.0, tvec(nb) / 0.002)
    bus.put(crack, HIT, gain=-9.0, pan=0.0, room=0.3, hall=0.3, label="hit:crack")
    metal = fm_bell(note("D4"), 3.4, ratio=2.76, index=4.5, tau_i=0.4, tau_a=1.1, click=0.1, name="hitmetal")
    metal = addv(metal, fm_bell(note("A4"), 3.0, ratio=3.9, index=3.0, tau_i=0.3, tau_a=0.9, click=0.0, name="hitmetal2"), 0.5)
    bus.put(metal, HIT + 0.05, gain=-12.0, hall=0.7, label="hit:metal", tail_ms=60)
    shimmer = svf(rng("hitcrash").standard_normal(int(3.2 * SR)), 3200.0, 0.7, "hp") * np.exp(-tvec(int(3.2 * SR)) / 0.9)
    bus.put(np.stack([shimmer, np.roll(shimmer, 31)]), HIT + 0.10, gain=-19.0, hall=0.6, label="hit:crash", tail_ms=80)
    crunch = smp("imp_boom_k_explosionCrunch_002")
    if crunch is not None:
        bus.put(crunch, HIT - 0.05, gain=-13.0, room=0.2, hall=0.35, label="hit:crunch(kenney CC0)", tail_ms=40)
    for nm_, g_, pn in (("imp_glass_k_impactGlass_medium_003", -9.0, -0.25), ("imp_metal_k_scifi_impactMetal_004", -10.0, 0.25)):
        x_ = smp(nm_)
        if x_ is not None:
            bus.put(x_, HIT + 0.04, gain=g_, pan=pn, room=0.25, hall=0.5, label=f"hit:{nm_}(kenney CC0)")
    rs = noise_sweep(0.6, 700.0, 9000.0, q=1.0, name="ringsweep", mode="bp", wide=True, ampfn=lambda u: np.sin(np.pi * np.clip(u, 0, 1) ** 0.7) ** 1.5)
    bus.put(rs, HIT + 0.04, gain=-14.0, hall=0.5, label="hit:ring sweep", tail_ms=40)
    # D major chord bloom (stack of detuned saw voices through a bright filter that closes slowly)
    dd = 5.2
    ch = np.zeros((2, int(dd * SR)))
    for k, nm in enumerate(["D3", "A3", "D4", "F#4", "A4", "C#5", "E5", "A5", "D6"]):
        ch += supersaw([note(nm)], dd, f"bloom{k}", voices=5, detune_c=14.0, spread=0.9) * (1.0 if k < 6 else 0.7)
    fc = curve([(0, 9000.0), (1.2, 4200.0), (dd, 1800.0)], log=True, n=ch.shape[1])
    ch = np.stack([svf(ch[0], fc, 0.7, "lp"), svf(ch[1], fc, 0.7, "lp")])
    ch *= np.exp(-tvec(ch.shape[1]) / 2.4)[None, :] * np.minimum(1.0, tvec(ch.shape[1]) / 0.008)[None, :]
    bus.put(ch / 3.2, HIT + 0.07, gain=-6.0, fade_in_ms=8, room=0.15, hall=0.6, label="hit:chord", tail_ms=100)
    for k, nm in enumerate(["D5", "A5", "D6", "F#6"]):
        bus.put(fm_bell(note(nm), 3.0, ratio=2.0, index=1.6, tau_i=0.25, tau_a=1.4, click=0.12, name=f"hitbell{k}"), HIT + 0.09 + 0.012 * k, gain=-17.0 + k, pan=-0.3 + 0.2 * k, hall=0.7, label=f"hit:bell:{nm}")

    # ---- 9. sparkle cascade over the carved figure, descending D-major pentatonic ----
    pent = ["D7", "B6", "A6", "F#6", "E6", "D6", "B5", "A5", "F#5", "E5", "D5"]
    t = HIT + 0.18
    for k in range(18):
        nm = pent[min(k // 2 + (k % 2), len(pent) - 1)]
        bus.put(tick_voice(note(nm), f"spark{k}", bright=1.2), t, gain=-18.0 - 0.6 * k, pan=math.sin(k * 1.7) * 0.45, room=0.3, hall=0.6, label=f"spark:{nm}")
        t += S16 if k < 10 else 2 * S16

    # ---- 10. lockup: pad bed, letter sparkles, tagline shimmer, final bell sting ----
    dd = 14.0 - HIT
    bed = np.zeros((2, int(dd * SR)))
    for k, nm in enumerate(["D3", "A3", "D4", "F#4", "A4", "E5"]):
        bed += pad_note(note(nm), dd, f"bed{k}", voices=3, spread=0.9, detune_c=6.0, harmonics=(1.0, 0.5, 0.28, 0.14, 0.07))
    fc = curve([(0, 3200.0), (dd, 2600.0)], log=True, n=bed.shape[1])
    bed = np.stack([svf(bed[0], fc, 0.8, "lp"), svf(bed[1], fc, 0.8, "lp")])
    bed *= curve([(0, 0.0), (0.5, 1.0), (dd - 2.2, 0.8), (dd, 0.0)], n=bed.shape[1])
    bus.put(bed / 2.4, HIT, gain=-14.0, room=0.2, hall=0.55, label="lock:bed", tail_ms=2, fade_in_ms=30)
    lad = ["D5", "F#5", "A5", "B5", "D6", "E6", "F#6", "A6", "B6", "D7"]
    for k, tt in enumerate(EV["letters"]):
        bus.put(tick_voice(note(lad[min(k, len(lad) - 1)]), f"let{k}", bright=1.0), tt, gain=-23.0 + 0.4 * k, pan=-0.5 + 0.11 * k, room=0.3, hall=0.45, label=f"letter:{k}")
        g_ = smp("ui_ding_k_glass_001", pitch_to=lad[min(k, len(lad) - 1)])
        if g_ is not None:
            bus.put(g_, tt, gain=-27.0 + 0.3 * k, pan=-0.5 + 0.11 * k, room=0.25, hall=0.45, label=f"letter:glass{k}(kenney CC0)")
    tg0 = EV["tagline"][0]
    sh = noise_sweep(0.9, 2500.0, 9000.0, q=1.4, name="tagsh", mode="bp", wide=True, ampfn=lambda u: np.sin(np.pi * np.clip(u, 0, 1)) ** 2)
    bus.put(sh, tg0, gain=-30.0, hall=0.5, label="tagline:shimmer")
    for k, (tt, nms, lv) in enumerate(((12.5, ["D6", "A6", "F#6"], -23.0), (13.4, ["E6", "B6", "D7"], -28.0))):
        for j, nm in enumerate(nms):
            bus.put(fm_bell(note(nm), 2.6, ratio=2.0, index=1.4, tau_i=0.3, tau_a=1.3, click=0.1, name=f"sting{k}{j}"), tt + 0.03 * j, gain=lv - j, pan=-0.12 + 0.12 * j, hall=0.75, label=f"sting:{nm}")
    # the gliding mark: soft air sweep
    sw = noise_sweep(1.0, 500.0, 6000.0, q=1.0, name="glide", mode="bp", wide=True, ampfn=lambda u: np.sin(np.pi * np.clip(u, 0, 1)) ** 2)
    bus.put(sw, T["lockMove"][0], gain=-15.0, hall=0.45, label="glide")
    # tonic payoff when the title is complete, plus a bell on the rule draw
    tp = T["title"][1] - 0.25
    ton = sub_tone(3.2, note("D3"), None, harm=0.5, drive=1.8) * np.exp(-tvec(int(3.2 * SR)) / 1.1)
    bus.put(ton, tp, gain=-18.0, room=0.1, hall=0.3, label="lock:tonic D3", tail_ms=60)
    bus.put(fm_bell(note("D5"), 2.4, ratio=2.0, index=1.4, tau_i=0.3, tau_a=1.2, click=0.1, name="rulebell"), T["rule"][0], gain=-19.0, pan=0.1, hall=0.7, label="rule:bell D5")


# ---------------------------------------------------------------------------------------------- master
def mono_bass(x, fc=200.0):
    m = 0.5 * (x[0] + x[1])
    sd = svf(0.5 * (x[0] - x[1]), fc, 0.7071, "hp")
    return np.stack([m + sd, m - sd])


def master_chain(x):
    x = mono_bass(x)
    b = Pedalboard([
        HighpassFilter(30.0),
        LowShelfFilter(cutoff_frequency_hz=140.0, gain_db=3.0),
        PeakFilter(cutoff_frequency_hz=1200.0, gain_db=-2.8, q=0.6),
        PeakFilter(cutoff_frequency_hz=3000.0, gain_db=0.5, q=0.7),
        HighShelfFilter(cutoff_frequency_hz=9000.0, gain_db=1.5),
        Compressor(threshold_db=-19.0, ratio=2.0, attack_ms=25.0, release_ms=220.0),
    ])
    return b(x.astype(np.float32), SR).astype(np.float64)


def master(mix, gain_db, ceiling_db):
    y = mix * float(db(gain_db))
    y = soft_clip(y, 0.75)
    y, g = limiter(y, float(db(ceiling_db)))
    fade = curve([(0.0, 0.0), (0.002, 1.0), (14.45, 1.0), (14.96, 0.0), (15.0, 0.0)])
    return y * fade[None, :], g


def main():
    t0 = time.time()
    bus = Bus()
    score(bus)
    print(f"[score] {len(bus.log)} events {time.time() - t0:.1f}s")
    # the inhale: everything except the risers/reverse swell sinks, with a short hole right before the hit
    duck = np.ones(N)
    tt_ = tvec(N)
    seg = (tt_ >= INHALE[0]) & (tt_ < HIT)
    u = np.clip((tt_ - INHALE[0]) / (HIT - 0.1 - INHALE[0]), 0, 1)
    duck[seg] = db(-28.0 * ease(u))[seg]
    hole = (tt_ >= HIT - 0.07) & (tt_ < HIT)
    duck[hole] = float(db(-40.0))
    for a_ in (bus.dry, bus.room, bus.hall):
        a_ *= duck[None, :]
    kd = np.ones(N)
    pre = (tt_ >= HIT - 0.35) & (tt_ < HIT - 0.07)
    kd[pre] = float(db(-14.0))
    kd[hole] = float(db(-34.0))
    bus.keep *= kd[None, :]
    room = verb(bus.room, 0.32, 0.55, 0.9, predelay=0.006)
    hall = verb(bus.hall, 0.88, 0.42, 0.6, predelay=0.024)
    # the vacuum must be a vacuum: the reverb tails of the build are ducked as well (they come back after the hit)
    room *= duck[None, :]
    hall *= duck[None, :]
    mix = bus.dry + 0.9 * room + 1.0 * hall + bus.keep
    mix = svf_st(mix, 24.0, 0.7071, "hp")
    mix = master_chain(mix)
    print(f"[mix] {time.time() - t0:.1f}s")
    g, ceil = 0.0, TRUE_PEAK_CEIL_DB
    for outer in range(6):
        for it in range(8):
            y, gr = master(mix, g, ceil)
            l = integrated_lufs(y)
            if abs(l - TARGET_LUFS) < 0.03:
                break
            g += (TARGET_LUFS - l) * 0.9
        y, gr = master(mix, g, ceil)
        tp_aac, l_aac = aac_probe(y)
        print(f"[aac] ceiling={ceil:+.2f}: after AAC192 true-peak={tp_aac:+.2f} dBTP  LUFS={l_aac:.2f}  (gain {g:+.2f} dB, loudest limiter GR {20 * np.log10(gr.min()):.1f} dB)")
        if tp_aac <= AAC_TP_LIMIT_DB:
            break
        ceil -= (tp_aac - AAC_TP_LIMIT_DB) + 0.05
    q = write_wav24(OUT_WAV, y)
    sha = hashlib.sha256(open(OUT_WAV, "rb").read()).hexdigest()
    print(f"[out] {OUT_WAV} samples={q.shape[1]} sha256={sha[:16]}  LUFS={integrated_lufs(y):.2f}  TP={20 * np.log10(true_peak_lin(y)):.2f} dBTP")
    json.dump({"sr": SR, "samples": N, "master_gain_db": round(g, 3), "limiter_ceiling_db": round(ceil, 3), "after_aac192_true_peak_db": tp_aac,
               "after_aac192_lufs": l_aac, "sha256_wav": sha, "events": sorted(bus.log, key=lambda e: (e["sample"], e["label"]))},
              open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[done] {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
