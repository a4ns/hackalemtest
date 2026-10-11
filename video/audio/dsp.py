# DSP primitives for the v2 score (numpy; ported from the v1 synth, deterministic).
from __future__ import annotations
import math, os, wave, zlib
import numpy as np

SR = 48000
SEED = 0x48414B4C
DURATION = 15.0
N = int(round(DURATION * SR))
_NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
D1 = None
EVENTS: list = []

def S(t: float) -> int:
    """Секунды -> индекс семпла (с округлением к ближайшему)."""
    return int(round(t * SR))



def db(x):
    return 10.0 ** (np.asarray(x, dtype=np.float64) / 20.0)



def rng(name: str) -> np.random.Generator:
    return np.random.default_rng((zlib.crc32(name.encode("utf-8")) ^ SEED) & 0xFFFFFFFF)



def note(name: str) -> float:
    """'D4' / 'F#3' / 'Bb2' -> Гц."""
    i = 1
    acc = 0
    if name[1] in "#b":
        acc = 1 if name[1] == "#" else -1
        i = 2
    octv = int(name[i:])
    m = 12 * (octv + 1) + _NOTE[name[0]] + acc
    return 440.0 * 2.0 ** ((m - 69) / 12.0)



def tvec(n: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / SR



def ease(u):
    u = np.clip(u, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)



def curve(points, t0: float = 0.0, n: int = N, log: bool = False, ease_on: bool = True):
    """Кусочная автоматизация с косинусным сглаживанием.
    points: [(t, value), ...] (t возрастает; равные t разводить на 1e-6)."""
    ts = np.array([p[0] for p in points], dtype=np.float64)
    vs = np.array([p[1] for p in points], dtype=np.float64)
    if log:
        vs = np.log(vs)
    tt = t0 + np.arange(n, dtype=np.float64) / SR
    u = np.interp(tt, ts, np.arange(len(ts), dtype=np.float64))
    seg = np.clip(np.floor(u).astype(int), 0, len(ts) - 2)
    f = u - seg
    if ease_on:
        f = 0.5 - 0.5 * np.cos(np.pi * f)
    v = vs[seg] + (vs[seg + 1] - vs[seg]) * f
    return np.exp(v) if log else v



def fade_edges(x: np.ndarray, fi: int, fo: int) -> np.ndarray:
    n = x.shape[-1]
    if fi > 0:
        k = min(fi, n)
        x[..., :k] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
    if fo > 0:
        k = min(fo, n)
        x[..., n - k:] *= 0.5 + 0.5 * np.cos(np.pi * (np.arange(k) + 1) / k)
    return x



def pan_mono(x: np.ndarray, p: float) -> np.ndarray:
    th = (np.clip(p, -1.0, 1.0) + 1.0) * np.pi / 4.0
    return np.stack([x * math.cos(th), x * math.sin(th)])



def pan_curve(x: np.ndarray, p0: float, p1: float) -> np.ndarray:
    n = len(x)
    p = p0 + (p1 - p0) * ease(np.linspace(0.0, 1.0, n))
    th = (p + 1.0) * np.pi / 4.0
    return np.stack([x * np.cos(th), x * np.sin(th)])



def phase_of(f: np.ndarray) -> np.ndarray:
    """Фаза (в циклах) для мгновенной частоты f[n]; старт с 0."""
    return (np.cumsum(f) - f) / SR



def full(f, n):
    return np.broadcast_to(np.asarray(f, dtype=np.float64), (n,)).copy()



def osc_sine(ph):
    return np.sin(2.0 * np.pi * ph)



def osc_tri(ph):
    return 4.0 * np.abs(((ph + 0.25) % 1.0) - 0.5) - 1.0



def _polyblep(t, dt):
    out = np.zeros_like(t)
    m = t < dt
    x = t[m] / dt[m]
    out[m] = x + x - x * x - 1.0
    m2 = t > 1.0 - dt
    x = (t[m2] - 1.0) / dt[m2]
    out[m2] = x * x + x + x + 1.0
    return out



def osc_saw(ph, f):
    t = ph % 1.0
    dt = np.clip(np.asarray(f, dtype=np.float64) / SR, 1e-6, 0.45)
    dt = np.broadcast_to(dt, t.shape)
    return 2.0 * t - 1.0 - _polyblep(t, dt)



def env_exp(n, a=0.001, tau=0.1, hold=0.0):
    t = tvec(n)
    e = np.minimum(1.0, t / a) if a > 0 else np.ones(n)
    return e * np.exp(-np.maximum(t - a - hold, 0.0) / tau)



def svf(x, fc, q=0.7071, mode="lp"):
    """TPT state-variable filter (Simper). fc, q - скаляр или массив по семплам."""
    x = np.asarray(x, dtype=np.float64)
    n = x.shape[0]
    fc = np.broadcast_to(np.asarray(fc, dtype=np.float64), (n,))
    q = np.broadcast_to(np.asarray(q, dtype=np.float64), (n,))
    g = np.tan(np.pi * np.clip(fc, 5.0, 0.45 * SR) / SR)
    k = 1.0 / q
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    xl = x.tolist()
    a1l = a1.tolist()
    a2l = a2.tolist()
    a3l = a3.tolist()
    v1o = [0.0] * n
    v2o = [0.0] * n
    s1 = 0.0
    s2 = 0.0
    for i in range(n):
        v3 = xl[i] - s2
        v1 = a1l[i] * s1 + a2l[i] * v3
        v2 = s2 + a2l[i] * s1 + a3l[i] * v3
        s1 = 2.0 * v1 - s1
        s2 = 2.0 * v2 - s2
        v1o[i] = v1
        v2o[i] = v2
    v1a = np.array(v1o)
    v2a = np.array(v2o)
    if mode == "lp":
        return v2a
    if mode == "bp":
        return v1a * k
    if mode == "hp":
        return x - k * v1a - v2a
    if mode == "notch":
        return x - k * v1a
    raise ValueError(mode)



def svf_st(x2, fc, q=0.7071, mode="lp"):
    return np.stack([svf(x2[0], fc, q, mode), svf(x2[1], fc, q, mode)])



def crush(x, bits=None, rate=None, mode="rise"):
    """Bitcrush + sample-and-hold downsample."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if rate is not None and rate < SR:
        k = np.floor(np.arange(n) * (rate / SR))
        idx = np.minimum(np.floor(k * (SR / rate) + 1e-6).astype(np.int64), n - 1)
        x = x[idx]
    if bits is not None:
        H = 2.0 ** (bits - 1)
        if mode == "rise":
            x = (np.floor(np.clip(x, -0.9999, 0.9999) * H) + 0.5) / H
        else:
            Lq = max(H - 1.0, 1.0)
            x = np.round(np.clip(x, -1.0, 1.0) * Lq) / Lq
    return x



def noise_sweep(dur, f0, f1, q=1.3, name="sw", mode="bp", wide=False, ampfn=None):
    """Шум через ФНЧ/ПФ с экспоненциальным свипом центра f0 -> f1."""
    n = int(dur * SR)
    u = np.linspace(0.0, 1.0, n)
    fc = f0 * (f1 / f0) ** u
    r = rng(name)
    if wide:
        a = svf(r.standard_normal(n), fc, q, mode)
        b = svf(r.standard_normal(n), fc, q, mode)
        y = np.stack([a, b])
    else:
        y = svf(r.standard_normal(n), fc, q, mode)
    if ampfn is not None:
        y = y * ampfn(u)
    return y



def fm_bell(f, dur, ratio=3.5, index=3.0, tau_i=0.15, tau_a=0.5, click=0.15, name="bell", partial2=0.25):
    n = int(dur * SR)
    t = tvec(n)
    idx = index * np.exp(-t / tau_i)
    y = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * ratio * t))
    y += partial2 * np.sin(2 * np.pi * f * 2.0 * t + 0.5 * idx * np.sin(2 * np.pi * f * 1.41 * t)) * np.exp(-t / (tau_a * 0.4))
    y *= env_exp(n, a=0.0008, tau=tau_a)
    if click:
        ck = np.diff(rng(name).standard_normal(n), prepend=0.0) * np.exp(-t / 0.0015)
        y += click * ck
    return y



def saw_pluck(f, dur, fc0=5500.0, fc1=500.0, tau_f=0.12, tau_a=0.35, detune=7.0, q=0.9):
    n = int(dur * SR)
    t = tvec(n)
    y = np.zeros(n)
    for c in (-detune, detune):
        ff = f * 2 ** (c / 1200.0)
        y += osc_saw(phase_of(full(ff, n)), ff)
    y += 0.8 * osc_tri(phase_of(full(f * 0.5, n)))
    fc = fc1 + (fc0 - fc1) * np.exp(-t / tau_f)
    y = svf(y, fc, q, "lp")
    return y * env_exp(n, a=0.002, tau=tau_a) * 0.5



def glass_ping(f, dur, tau=0.45, name="glass"):
    n = int(dur * SR)
    t = tvec(n)
    y = np.zeros(n)
    for r_, a_, ta in ((1.0, 1.0, 1.0), (2.76, 0.45, 0.55), (5.40, 0.28, 0.32), (8.93, 0.14, 0.2)):
        if f * r_ < 18000:
            y += a_ * np.sin(2 * np.pi * f * r_ * t) * np.exp(-t / (tau * ta))
    y *= np.minimum(1.0, t / 0.0008)
    return y



def supersaw(freqs, dur, name, voices=5, detune_c=13.0, spread=0.9, vib_c=3.5):
    """Суперпила (polyBLEP), стерео-раскладка голосов, медленный дрейф."""
    n = int(dur * SR)
    t = tvec(n)
    r = rng(name)
    out = np.zeros((2, n))
    for fi_, f in enumerate(freqs):
        for v in range(voices):
            pos = (v - (voices - 1) / 2.0) / ((voices - 1) / 2.0)
            cents = pos * detune_c
            lfo = vib_c * np.sin(2 * np.pi * (0.2 + 0.25 * r.random()) * t + 6.2832 * r.random())
            ff = f * 2.0 ** ((cents + lfo) / 1200.0)
            y = osc_saw(phase_of(ff) + r.random(), ff)
            p = np.clip(pos * spread + (r.random() - 0.5) * 0.15, -1, 1)
            th = (p + 1.0) * np.pi / 4.0
            out[0] += y * math.cos(th)
            out[1] += y * math.sin(th)
    return out / math.sqrt(len(freqs) * voices)



def pad_note(f, dur, name, voices=3, spread=0.85, detune_c=6.0, harmonics=(1.0, 0.5, 0.24, 0.12, 0.06)):
    n = int(dur * SR)
    t = tvec(n)
    r = rng(name)
    out = np.zeros((2, n))
    for v in range(voices):
        pos = (v - (voices - 1) / 2.0) / max((voices - 1) / 2.0, 1.0)
        ff = f * 2.0 ** ((pos * detune_c) / 1200.0)
        y = np.zeros(n)
        for h, a_ in enumerate(harmonics, start=1):
            if ff * h < 16000:
                y += a_ * np.sin(2 * np.pi * (ff * h * t + r.random()))
        y *= 1.0 + 0.12 * np.sin(2 * np.pi * (0.25 + 0.3 * r.random()) * t + 6.2832 * r.random())
        p = pos * spread
        th = (p + 1.0) * np.pi / 4.0
        out[0] += y * math.cos(th)
        out[1] += y * math.sin(th)
    return out / math.sqrt(voices)



def kick_drum(dur=0.36, f0=165.0, f1=55.0, tau_p=0.028, tau_a=0.13, click=0.35, drive=2.0,
              name="kick", bits=None, rate=None, lp=None):
    n = int(dur * SR)
    t = tvec(n)
    f = f1 + (f0 - f1) * np.exp(-t / tau_p)
    amp = np.minimum(1.0, t / 0.001) * np.exp(-t / tau_a)
    body = np.sin(2 * np.pi * phase_of(f)) * amp
    body = np.tanh(drive * body) / np.tanh(drive)
    nc = min(n, int(0.012 * SR))
    ck = np.zeros(n)
    if click:
        ck[:nc] = svf(rng(name).standard_normal(nc), 3500.0, 0.8, "bp") * 0.55
        ck *= np.minimum(1.0, t / 0.0006) * np.exp(-t / 0.0025)
    y = body + click * ck
    if bits or rate:
        y = crush(y, bits, rate, "tread")
    if lp:
        y = svf(y, lp, 0.7071, "lp")
    return y



def sub_tone(dur, f0, f1=None, tau_f=0.3, harm=0.3, drive=1.4):
    """Синус-саб (с опциональным скольжением f0 -> f1) + 2-я гармоника + мягкая сатурация."""
    n = int(dur * SR)
    t = tvec(n)
    f = full(f0, n) if f1 is None else f1 * (f0 / f1) ** np.exp(-t / tau_f)
    ph = phase_of(f)
    y = np.sin(2 * np.pi * ph) + harm * np.sin(4 * np.pi * ph + 0.6)
    return np.tanh(drive * y) / np.tanh(drive)



def oversample4(x: np.ndarray) -> np.ndarray:
    n = x.shape[-1]
    X = np.fft.rfft(x, axis=-1)
    Y = np.zeros(X.shape[:-1] + (2 * n + 1,), dtype=np.complex128)
    Y[..., : X.shape[-1]] = X
    return np.fft.irfft(Y, 4 * n, axis=-1) * 4.0



def true_peak_lin(x2: np.ndarray) -> float:
    return float(np.abs(oversample4(x2)).max())



def soft_clip(y, knee):
    a = np.abs(y)
    over = a > knee
    out = y.copy()
    out[over] = np.sign(y[over]) * (knee + (1.0 - knee) * np.tanh((a[over] - knee) / (1.0 - knee)))
    return out



def limiter(x2, ceiling_lin, look=144, release=0.09):
    """Lookahead-лимитер по оценке true-peak (4x). Усиление сглажено окном 2*look+1."""
    n = x2.shape[1]
    os_ = np.abs(oversample4(x2)).reshape(2, n, 4).max(axis=(0, 2))
    need = np.minimum(1.0, ceiling_lin / np.maximum(os_, 1e-12))
    pad = np.pad(need, (look, look), constant_values=1.0)
    win = np.lib.stride_tricks.sliding_window_view(pad, 2 * look + 1)
    gmin = win.min(axis=1)
    k = np.ones(2 * look + 1) / (2 * look + 1)
    g_att = np.convolve(np.pad(gmin, (look, look), mode="edge"), k, mode="valid")
    # релиз: ограничиваем скорость восстановления усиления
    rel = 1.0 - math.exp(-1.0 / (release * SR))
    g = np.empty(n)
    prev = 1.0
    ga = g_att.tolist()
    for i in range(n):
        tgt = ga[i]
        v = prev + (1.0 - prev) * rel
        if tgt < v:
            v = tgt
        g[i] = v
        prev = v
    return x2 * g[None, :], g



def k_weight(x2):
    nfft = 1 << int(math.ceil(math.log2(x2.shape[1] + SR)))
    w = 2 * np.pi * np.fft.rfftfreq(nfft)
    z1 = np.exp(-1j * w)
    z2 = z1 * z1
    b1 = (1.53512485958697, -2.69169618940638, 1.19839281085285)
    a1 = (1.0, -1.69065929318241, 0.73248077421585)
    b2 = (1.0, -2.0, 1.0)
    a2 = (1.0, -1.99004745483398, 0.99007225036621)
    H = ((b1[0] + b1[1] * z1 + b1[2] * z2) / (a1[0] + a1[1] * z1 + a1[2] * z2)) * \
        ((b2[0] + b2[1] * z1 + b2[2] * z2) / (a2[0] + a2[1] * z1 + a2[2] * z2))
    return np.stack([np.fft.irfft(np.fft.rfft(c, nfft) * H, nfft)[: x2.shape[1]] for c in x2])



def integrated_lufs(x2):
    kw = k_weight(x2)
    e = (kw ** 2).sum(axis=0)
    cs = np.concatenate([[0.0], np.cumsum(e)])
    blk, step = 19200, 4800
    starts = np.arange(0, x2.shape[1] - blk + 1, step)
    z = (cs[starts + blk] - cs[starts]) / blk
    lk = -0.691 + 10.0 * np.log10(np.maximum(z, 1e-20))
    m = lk > -70.0
    if not m.any():
        return -70.0
    rel = -0.691 + 10.0 * np.log10(z[m].mean()) - 10.0
    m2 = lk > max(rel, -70.0)
    return float(-0.691 + 10.0 * np.log10(z[m2].mean()))



def write_wav24(path, x2):
    q = np.clip(np.round(x2 * 8388607.0), -8388608, 8388607).astype(np.int32)
    inter = np.ascontiguousarray(q.T).reshape(-1)
    raw = inter.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(raw)
    return q



def aac_probe(y):
    """Кодирует микс как рендер (AAC 192k, 48 кГц), декодирует и меряет ffmpeg ebur128: (true peak dBTP, integrated LUFS)."""
    import subprocess, tempfile, re
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "m.wav"); m4a = os.path.join(d, "m.m4a")
        write_wav24(wav, y)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", m4a], check=True)
        r = subprocess.run(["ffmpeg", "-v", "info", "-i", m4a, "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    tp = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail).group(1))
    li = float(re.search(r"I:\s+(-?[\d.]+) LUFS", tail).group(1))
    return tp, li


