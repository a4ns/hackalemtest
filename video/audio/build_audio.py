#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HackAlem AI - вступительный ролик 15 с: процедурный саундтрек (только numpy).

Запуск:  python3 audio/build_audio.py        (или `npm run audio`)
Выход:   assets/audio/hackalem-intro-mix.wav  (48 кГц, стерео, 24 бит, ровно 720 000 семплов)
         audio/events_manifest.json            (карта событий: время -> номер семпла)

Принципы
  * Все времена берутся из config/cues.json (ключ T, meta.bpm, meta.fps). Производные
    (шестнадцатая, такт, кадр, шаги арпеджио, "плаки" и т. д.) считаются от них же.
  * Никаких внешних сэмплов: осцилляторы, шум, фильтры (TPT-SVF), bitcrush/downsample,
    FM, суперпила (polyBLEP), реверберация через синтезированный импульсный отклик,
    эхо, сайдчейн (детектор огибающей по бочке), lookahead true-peak лимитер.
  * Детерминизм: каждое событие использует собственный seed (crc32 имени ^ SEED),
    вся математика - float64 numpy + чистый Python; результат побитово повторяется
    при том же numpy.
  * Концепция "звук растёт в разрешении": акт I - 2-4 бит и узкая полоса,
    акт II - 8 бит + ритм, акт III - полный бас/райзер, отсчёт - потеря разрешения,
    9.600 - первое полноразрядное широкое стерео, финал - чистый pad + пиксельные тики.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
import wave
import zlib

import numpy as np

# --------------------------------------------------------------------------- #
# Конфигурация и время
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CUES_PATH = os.path.join(ROOT, "config", "cues.json")
OUT_WAV = os.path.join(ROOT, "assets", "audio", "hackalem-intro-mix.wav")
MANIFEST = os.path.join(HERE, "events_manifest.json")

SR = 48000
SEED = 0x48414B4C  # "HAKL"
TARGET_LUFS = -14.0
TRUE_PEAK_CEIL_DB = -1.35   # потолок лимитера (детекция по 4x oversampling); цель <= -1.0 dBTP
# Поправка внутреннего измерителя к ffmpeg ebur128 (подбирается по проверке ffmpeg, см. 04_sound.md)
LUFS_CAL_DB = 0.0
AAC_TP_LIMIT_DB = -1.05     # HyperFrames кодирует AAC 192k и сам занижает звук, если true peak ПОСЛЕ AAC > -1 dBTP; подбираем потолок так, чтобы не занижал
PRE_TRIM = 0.0              # доп. подрезка пред-слоя перед сведением (дБ); 0 - не используется

with open(CUES_PATH, "r", encoding="utf-8") as _f:
    CUES = json.load(_f)
T = CUES["T"]
META = CUES["meta"]
FPS = float(META["fps"])
BPM = float(META["bpm"])
DURATION = float(META["duration"])
N = int(round(DURATION * SR))
assert N == 720000, "длительность должна давать ровно 720000 семплов"

BEAT = 60.0 / BPM          # 0.4 с
S16 = BEAT / 4.0           # 0.1 с (шестнадцатая = 3 кадра)
BAR = 4.0 * BEAT           # 1.6 с
FRAME = 1.0 / FPS

HIT = T["hit"]             # 9.600
CD = T["countdown"]        # 9.2 9.3 9.4 9.5
CUT_T = CD[0]              # музыка вырезается с 9.2

# Свет из выреза знака (указание режиссёра; в cues.json отдельных ключей нет): яркий до HIT+0.50 (10.10),
# уходит к lock[0]-0.32 (10.58); от 10.58 до начала сжатия lock[0] (10.90) знак тёмный и спокойный.
# Pad / саб / хвост удара затихают вслед за светом.
LIGHT_BRIGHT = HIT + 0.50
LIGHT_OUT = T["lock"][0] - 0.32


def S(t: float) -> int:
    """Секунды -> индекс семпла (с округлением к ближайшему)."""
    return int(round(t * SR))


EVENTS: list[dict] = []


# --------------------------------------------------------------------------- #
# Утилиты
# --------------------------------------------------------------------------- #
def db(x):
    return 10.0 ** (np.asarray(x, dtype=np.float64) / 20.0)


def rng(name: str) -> np.random.Generator:
    return np.random.default_rng((zlib.crc32(name.encode("utf-8")) ^ SEED) & 0xFFFFFFFF)


_NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


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


D1 = note("D1")


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


# --------------------------------------------------------------------------- #
# Осцилляторы, огибающие
# --------------------------------------------------------------------------- #
def phase_of(f: np.ndarray) -> np.ndarray:
    """Фаза (в циклах) для мгновенной частоты f[n]; старт с 0."""
    return (np.cumsum(f) - f) / SR


def full(f, n):
    return np.broadcast_to(np.asarray(f, dtype=np.float64), (n,)).copy()


def osc_sine(ph):
    return np.sin(2.0 * np.pi * ph)


def osc_tri(ph):
    return 4.0 * np.abs(((ph + 0.25) % 1.0) - 0.5) - 1.0


def osc_square_naive(ph, duty=0.5):
    return np.where((ph % 1.0) < duty, 1.0, -1.0)


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


# --------------------------------------------------------------------------- #
# Фильтры и эффекты
# --------------------------------------------------------------------------- #
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


def echo_pingpong(sig2: np.ndarray, delay: float, fb: float, taps: int, lp_hz=None) -> np.ndarray:
    """Эхо с перекрёстной подачей (L/R попеременно). sig2: (2, n) -> (2, n)."""
    n = sig2.shape[1]
    m = 0.5 * (sig2[0] + sig2[1])
    out = np.zeros((2, n))
    d = int(round(delay * SR))
    for k in range(1, taps + 1):
        s = k * d
        if s >= n:
            break
        tap = np.zeros(n)
        tap[s:] = m[: n - s] * (fb ** k)
        out[1 if k % 2 == 1 else 0] += tap
    if lp_hz:
        out = svf_st(out, lp_hz, 0.7071, "lp")
    return out


def echo_mono_to_stereo_tail(sig: np.ndarray, delay: float, fb: float, taps: int, extra: float = 0.0):
    """Эхо для короткого события: возвращает (2, n + taps*delay)."""
    d = int(round(delay * SR))
    n = len(sig) + taps * d + int(extra * SR)
    out = np.zeros((2, n))
    out[0, : len(sig)] += sig
    out[1, : len(sig)] += sig
    for k in range(1, taps + 1):
        ch = 1 if k % 2 == 1 else 0
        out[ch, k * d: k * d + len(sig)] += sig * (fb ** k)
    return out


# --------------------------------------------------------------------------- #
# Реверберация: синтезированный импульсный отклик + FFT-свёртка
# --------------------------------------------------------------------------- #
def make_ir(name, length, t60_lo, t60_hi, corr, predelay, er_taps=0, er_span=0.06):
    n = int(length * SR)
    r = rng("ir:" + name)
    nL = r.standard_normal(n)
    nR = corr * nL + math.sqrt(max(0.0, 1.0 - corr ** 2)) * r.standard_normal(n)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    centers = [90.0 * 2 ** i for i in range(8)]
    t = np.arange(n) / SR
    ws = [np.exp(-0.5 * (np.log2(np.maximum(freqs, 1.0) / fc) / 0.75) ** 2) for fc in centers]
    wsum = np.sum(ws, axis=0) + 1e-12
    irs = []
    for noise in (nL, nR):
        F = np.fft.rfft(noise)
        out = np.zeros(n)
        for i, w in enumerate(ws):
            t60 = t60_lo * (t60_hi / t60_lo) ** (i / (len(centers) - 1))
            band = np.fft.irfft(F * (w / wsum), n)
            out += band * np.exp(-6.9078 * t / t60)
        out *= np.minimum(1.0, t / 0.012)
        irs.append(out)
    ir = np.stack(irs)
    if er_taps:
        for c in range(2):
            pos = r.uniform(0.003, er_span, er_taps)
            sgn = r.choice([-1.0, 1.0], er_taps)
            for p, s in zip(pos, sgn):
                ir[c, int(p * SR)] += s * 0.6 * np.exp(-p / 0.03) * ir[c].std() * 8.0
    pd = int(predelay * SR)
    if pd:
        ir = np.concatenate([np.zeros((2, pd)), ir], axis=1)
    ir /= np.sqrt((ir ** 2).sum(axis=1, keepdims=True))
    return ir


def conv_stereo(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    if not np.any(x):
        return np.zeros_like(x)
    M = ir.shape[1]
    nfft = 1 << int(math.ceil(math.log2(x.shape[1] + M)))
    out = np.empty_like(x)
    for c in range(2):
        out[c] = np.fft.irfft(np.fft.rfft(x[c], nfft) * np.fft.rfft(ir[c], nfft), nfft)[: x.shape[1]]
    return out


# --------------------------------------------------------------------------- #
# Инструменты (возвращают numpy-массивы, не размещают)
# --------------------------------------------------------------------------- #
def sub_tone(dur, f0, f1=None, tau_f=0.3, harm=0.3, drive=1.4):
    """Синус-саб (с опциональным скольжением f0 -> f1) + 2-я гармоника + мягкая сатурация."""
    n = int(dur * SR)
    t = tvec(n)
    f = full(f0, n) if f1 is None else f1 * (f0 / f1) ** np.exp(-t / tau_f)
    ph = phase_of(f)
    y = np.sin(2 * np.pi * ph) + harm * np.sin(4 * np.pi * ph + 0.6)
    return np.tanh(drive * y) / np.tanh(drive)


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


def crackle(dur=0.2, name="crackle"):
    """Сухой электрический треск: 2 бита, частота дискретизации 4 кГц."""
    n = int(dur * SR)
    r = rng(name)
    t = tvec(n)
    nz = crush(r.standard_normal(n) / 2.2, bits=2, rate=4000)
    blk = 96
    nb = n // blk + 1
    p = np.interp(np.arange(nb) * blk / SR, [0.0, dur], [0.95, 0.2])
    gate = np.repeat((r.random(nb) < p).astype(np.float64), blk)[:n]
    env = np.exp(-t / 0.045) * np.minimum(1.0, t / 0.0005)
    return svf(nz * gate * env, 300.0, 0.7071, "hp")


def square_sweep(dur, f0, f1, bits=2, rate=8000, duty=0.5, pw=2.0):
    """Растущий 2-бит прямоугольник f0 -> f1 (экспоненциально), амплитуда растёт как u**pw."""
    n = int(dur * SR)
    u = np.linspace(0.0, 1.0, n)
    f = f0 * (f1 / f0) ** u
    y = osc_square_naive(phase_of(f), duty)
    y = crush(y, bits, rate)
    return y * (u ** pw)


def lofi_tick(f, dur, bits, rate, tau=0.04, wave_="tri"):
    n = int(dur * SR)
    ph = phase_of(full(f, n))
    y = osc_tri(ph) if wave_ == "tri" else osc_sine(ph)
    y = crush(y, bits, rate)
    return y * env_exp(n, a=0.0008, tau=tau)


def chord_stab(names, dur, bits, rate, tau=0.09, duty=0.5):
    n = int(dur * SR)
    y = np.zeros(n)
    for nm in names:
        y += osc_square_naive(phase_of(full(note(nm), n)), duty)
    y /= len(names)
    y = crush(y, bits, rate)
    return y * env_exp(n, a=0.001, tau=tau)


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


def hat(dur=0.05, tau=0.012, name="hat", bits=8, rate=24000, bright=1.0):
    n = int(dur * SR)
    t = tvec(n)
    metal = np.zeros(n)
    for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0):
        metal += osc_square_naive(phase_of(full(f * 2.0, n)))
    metal /= 6.0
    y = 0.6 * metal + 0.5 * rng(name).standard_normal(n)
    y = crush(y, bits, rate, "tread")
    y = svf(y, 7000.0 * bright, 0.9, "hp")
    return y * env_exp(n, a=0.0005, tau=tau)


def clap(dur=0.26, name="clap", fc=1700.0, q=1.1, bursts=3, spacing=0.011, tail_tau=0.075, bits=None, rate=None):
    n = int(dur * SR)
    t = tvec(n)
    y = svf(rng(name).standard_normal(n), fc, q, "bp")
    env = np.zeros(n)
    for k in range(bursts):
        tk = k * spacing
        env += np.clip((t - tk) / 0.0008, 0.0, 1.0) * np.exp(-np.maximum(t - tk, 0) / 0.004)
    tb = bursts * spacing
    env += np.clip((t - tb) / 0.0008, 0.0, 1.0) * np.exp(-np.maximum(t - tb, 0) / tail_tau)
    env = np.minimum(env, 1.0)
    y = svf(y, 8000.0, 0.7071, "lp") * env
    if bits or rate:
        y = crush(y, bits, rate, "tread")
    return y


def snare(dur=0.22, name="snare", tone=190.0, bits=None, rate=None, noise_tau=0.07):
    n = int(dur * SR)
    t = tvec(n)
    nz = svf(svf(rng(name).standard_normal(n), 1100.0, 0.8, "hp"), 7000.0, 0.7071, "lp")
    nz = nz * env_exp(n, a=0.0009, tau=noise_tau)
    f = tone * (1.0 + 0.6 * np.exp(-t / 0.02))
    tn = osc_tri(phase_of(f)) * env_exp(n, a=0.0009, tau=0.055)
    y = 0.8 * nz + 0.55 * tn
    if bits or rate:
        y = crush(y, bits, rate, "tread")
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


def metal_click(f, dur=0.12, name="mc"):
    n = int(dur * SR)
    t = tvec(n)
    r = rng(name)
    y = np.zeros(n)
    for ratio, a_ in ((1.0, 1.0), (1.504, 0.7), (2.1, 0.55), (3.7, 0.4), (5.23, 0.3)):
        y += a_ * np.sin(2 * np.pi * (f * ratio * t + r.random()))
    y *= np.exp(-t / 0.022)
    y += 0.4 * svf(r.standard_normal(n), 6500.0, 0.7071, "lp") * np.exp(-t / 0.0022)
    return y * np.minimum(1.0, t / 0.0005) * 0.35


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


def crash(dur=2.6, name="crash", tau=0.9):
    n = int(dur * SR)
    t = tvec(n)
    chans = []
    for c in range(2):
        r = rng(f"{name}:{c}")
        m = np.zeros(n)
        for ratio in (1.0, 1.34, 1.78, 2.37, 3.1, 4.2, 5.6, 7.4, 9.9, 13.1):
            ff = 330.0 * ratio * (1.0 + 0.01 * (r.random() - 0.5))
            m += osc_square_naive(phase_of(full(ff, n)) + r.random())
        m /= 10.0
        y = 0.55 * m + 0.7 * r.standard_normal(n)
        y = svf(svf(y, 3500.0, 0.8, "hp"), 12000.0, 0.7071, "lp")
        chans.append(y)
    y = np.stack(chans) * env_exp(n, a=0.002, tau=tau)[None, :]
    return y


def reverse_snare_swell(dur, name="rs"):
    s = snare(dur=dur, name=name, noise_tau=dur * 0.35)
    s = s[::-1].copy()
    return s * (np.linspace(0.0, 1.0, len(s)) ** 0.7)


# --------------------------------------------------------------------------- #
# Слои и размещение событий
# --------------------------------------------------------------------------- #
class Layer:
    def __init__(self):
        self.dry = np.zeros((2, N))
        self.send = np.zeros((2, N))


LAYER_NAMES = ("kick", "perc", "bed", "fx", "cd", "hit", "pad", "post")
LAYERS: dict = {}
TRIG = None              # триггер сайдчейна (огибающая бочек), создаётся в reset_state()


def reset_state():
    global LAYERS, TRIG
    LAYERS = {k: Layer() for k in LAYER_NAMES}
    TRIG = np.zeros(N)
    EVENTS.clear()


def put(layer, sig, t, g=0.0, pan=0.0, rev=None, fi=24, fo=96, label=None, trig=False):
    """Разместить событие ровно с семпла S(t). g - dB, rev - dB отправки на ревербератор слоя."""
    L = LAYERS[layer] if isinstance(layer, str) else layer
    sig = np.asarray(sig, dtype=np.float64)
    st = pan_mono(sig, pan) if sig.ndim == 1 else sig.copy()
    st = st * float(db(g))
    fade_edges(st, fi, fo)
    i0 = S(t)
    if i0 >= N:
        return
    i1 = min(N, i0 + st.shape[1])
    seg = st[:, : i1 - i0]
    L.dry[:, i0:i1] += seg
    if rev is not None:
        L.send[:, i0:i1] += seg * float(db(rev))
    if trig:
        TRIG[i0:i1] += np.abs(seg).max(axis=0)
    if label:
        EVENTS.append({"label": label, "t": round(float(t), 6), "sample": i0, "layer": layer if isinstance(layer, str) else "?",
                       "gain_db": round(float(g), 2)})


# --------------------------------------------------------------------------- #
# Аранжировка
# --------------------------------------------------------------------------- #
PENTA_HI = ["D5", "E5", "F#5", "A5", "B5", "D6", "E6", "F#6", "A6", "B6", "D7"]   # D-мажорная пентатоника
MINOR_HI = ["D5", "F5", "G5", "A5", "C6", "D6", "F6", "A6"]                      # D-минорная пентатоника


def chord_tones(kind):
    """Ноты арпеджио (Гц) для аккорда, 5 тонов: r, 3, 5, r+8ve, 3+8ve."""
    if kind == "Dm":
        return [note(x) for x in ("D4", "F4", "A4", "D5", "F5")]
    if kind == "F":
        return [note(x) for x in ("F4", "A4", "C5", "F5", "A5")]
    if kind == "C":
        return [note(x) for x in ("C4", "E4", "G4", "C5", "E5")]
    raise ValueError(kind)


ARP_PATTERN = [0, 1, 2, 3, 4, 3, 2, 1]   # вверх-вниз, повторяется дважды на такт


def score_act1_2_pre():
    """Акт I (0 - 3.2) и вход акта II."""
    # ---- 0.000 Акцент №1: саб D1 0.35 c + 2-бит треск 4 кГц 0.2 c; старт на семпле 0, микрофейд 2 мс
    sub = sub_tone(0.35, D1, harm=0.35, drive=1.5) * env_exp(int(0.35 * SR), a=0.002, tau=0.13)
    put("kick", sub, 0.0, g=-6.0, fi=96, fo=480, label="accent1 sub D1")
    put("perc", crackle(0.2, "accent1-crackle"), 0.0, g=-12.0, fi=96, fo=240, label="accent1 crackle 2bit/4kHz")

    # ---- 0.00-0.40 растущий 2-бит прямоугольник 200->900 Гц (с воздухом перед ударом 0.4)
    t_end = T["ideaOpen"] - 0.012
    sw = square_sweep(t_end - 0.05, 200.0, 900.0, bits=2, rate=8000, pw=2.2)
    put("fx", sw, 0.05, g=-20.0, fi=96, fo=288, label="crack sweep 200->900 2bit")

    # ---- 0.40 удар + аккорд-стаб D/A 4 бит
    t = T["ideaOpen"]
    put("kick", kick_drum(0.3, 140, 55, 0.025, 0.09, bits=4, rate=12000, name="k-0.4", lp=2500), t,
        g=-6.0, trig=True, label="kick 0.4 lofi 4bit")
    put("bed", chord_stab(["D3", "A3", "D4", "A4"], 0.3, 4, 12000, tau=0.085), t, g=-13.0, rev=-14.0,
        label="stab D/A 4bit")

    # ---- 0.6 0.8 1.0 1.2: 4 тика-ступени (высота и разрядность/частота растут)
    steps = T["ideaRes"][1:]
    pitches = ["D4", "F4", "A4", "D5"]
    bits = [2, 3, 4, 6]
    rates = [4000, 8000, 12000, 24000]
    for i, (ts, _res) in enumerate(steps):
        put("bed", lofi_tick(note(pitches[i]), 0.09, bits[i], rates[i], tau=0.04, wave_="tri"), ts,
            g=-12.0 + 1.0 * i, rev=-14.0, pan=-0.25 + 0.17 * i, label=f"res-tick {pitches[i]} {bits[i]}bit/{rates[i]//1000}k")
    # на 1.20 чистый колокольчик D5 в полном разрешении
    put("bed", fm_bell(note("D5"), 1.0, ratio=3.5, index=2.4, tau_i=0.09, tau_a=0.28, name="bell1.2"), steps[-1][0],
        g=-13.0, rev=-8.0, label="clean bell D5 1.2")

    # ---- 1.2-2.0 (до 2.4) саб-педаль D1 тихо
    t0 = steps[-1][0]
    dur = T["ideaClose"][1] - t0
    pedal = sub_tone(dur, D1, harm=0.2, drive=1.2) * curve([(0, 0), (0.25, 1), (dur - 0.35, 1), (dur, 0)], n=int(dur * SR))
    put("kick", pedal, t0, g=-22.0, fi=480, fo=960, label="sub pedal D1")

    # редкие псевдослучайные пиксельные блипы (seed), панорама случайная, очень тихо
    r = rng("pixel-blips")
    nb = 9
    tb = np.sort(r.uniform(t0 + 0.07, T["ideaClose"][0] - 0.05, nb))
    for i, tt in enumerate(tb):
        f = note(PENTA_HI[int(r.integers(0, 7))])
        put("bed", lofi_tick(f, 0.035, 4, 12000, tau=0.014, wave_="tri"), float(tt),
            g=-26.0 + 3.0 * float(r.random()), pan=float(r.uniform(-0.8, 0.8)), rev=-12.0, label=f"pixel blip {i}")

    # ---- 1.6 и 2.0 призрачный бочонок
    for i, tg in enumerate(T["pulses1"]):
        put("kick", kick_drum(0.22, 90, 48, 0.03, 0.07, click=0.0, drive=1.3, name=f"ghost{i}", lp=140), tg,
            g=-17.0, rev=-10.0, label="ghost kick")

    # ---- 2.0-2.4 закрывающийся фронт: шум L->R + три пинга рождения искр
    c0, c1 = T["ideaClose"]
    sweep = noise_sweep(c1 - c0, 500.0, 5200.0, q=1.4, name="close-sweep", mode="bp",
                        ampfn=lambda u: np.sin(np.pi * np.clip(u, 0, 1)) ** 1.2)
    put("fx", pan_curve(sweep, -0.9, 0.9), c0, g=-17.0, rev=-14.0, label="closing noise L->R")
    for i, nm in enumerate(("A5", "C6", "E6")):
        tt = c0 + (i + 1) * S16
        put("bed", glass_ping(note(nm), 0.35, tau=0.12, name=f"birth{i}") * 0.6 + 0.4 * lofi_tick(note(nm), 0.35, 6, 24000, tau=0.06),
            tt, g=-15.0, pan=(-0.5, 0.0, 0.5)[i], rev=-9.0, label=f"spark birth {nm}")

    # ---- 2.4-3.2: 8 ступеней арпеджио D F A C D F A C (6 бит), панорама поочерёдно, фильтр растёт
    h0, h1 = T["sparkHop"]
    step = (h1 - h0) / 8.0
    seq = ["D4", "F4", "A4", "C5", "D5", "F5", "A5", "C6"]
    n_arp = int((h1 - h0) * SR)
    hop = np.zeros((2, n_arp))
    for i, nm in enumerate(seq):
        f = note(nm)
        nn = int(0.085 * SR)
        y = osc_square_naive(phase_of(full(f, nn)), 0.25)
        y = crush(y, 6, 16000) * env_exp(nn, a=0.0008, tau=0.035)
        y = fade_edges(y, 24, 96)
        st = pan_mono(y, -0.55 if i % 2 == 0 else 0.55) * float(db(-4.0 + 0.9 * i))
        k0 = int(round(i * step * SR))
        hop[:, k0:k0 + nn] += st[:, : n_arp - k0]
    fc = curve([(0, 1200.0), (h1 - h0, 9000.0)], n=n_arp, log=True)
    hop = svf_st(hop, fc, 1.1, "lp")
    put("bed", hop, h0, g=-12.5, rev=-12.0, fi=24, fo=240, label="spark hop arp x8 6bit")

    # райзер к 3.20 (оставляем 30 мс воздуха перед акцентом)
    rd = (h1 - h0) - 0.03
    rz = riser(rd, "riser-2.4", fc0=300.0, fc1=9500.0, f0=note("D3"), f1=note("D4"), noise_mix=0.6, pw=2.0)
    put("fx", rz, h0, g=-11.0, rev=-14.0, fo=480, label="riser 2.4->3.2")


def riser(dur, name, fc0=200.0, fc1=8000.0, f0=147.0, f1=588.0, noise_mix=0.55, q=1.3, pw=2.0, gate_rate=None):
    n = int(dur * SR)
    u = np.linspace(0.0, 1.0, n)
    fc = fc0 * (fc1 / fc0) ** (u ** 1.3)
    f = f0 * (f1 / f0) ** u
    saw = osc_saw(phase_of(f), f)
    nz = rng(name).standard_normal(n) * 0.5
    src = (1.0 - noise_mix) * saw + noise_mix * nz
    y = svf(src, fc, q, "lp")
    amp = u ** pw
    if gate_rate is not None:
        rate = gate_rate[0] * (gate_rate[1] / gate_rate[0]) ** u
        ph = np.cumsum(rate) / SR
        g = 0.55 + 0.45 * (0.5 + 0.5 * np.sin(2 * np.pi * ph))
        amp = amp * g
    return y * amp


def bass_note(f_root, dur, name):
    """Саб-синус (D1/F1) + пила октавой выше через ФНЧ - слышно и на маленьких динамиках."""
    n = int(dur * SR)
    t = tvec(n)
    sub = sub_tone(dur, f_root, harm=0.25, drive=1.3)
    ff = f_root * 2.0
    saw = osc_saw(phase_of(full(ff, n)), ff)
    fc = 160.0 + 900.0 * np.exp(-t / 0.05)
    saw = svf(saw, fc, 1.0, "lp")
    y = 0.62 * sub + 0.5 * saw
    return y * env_exp(n, a=0.003, tau=dur * 0.7)


def score_act2_3_pre():
    """3.2 - 9.2: акт II (8-бит + ритм) и акт III (бас, райзер, ускорение)."""
    t32 = T["n8"]
    # ---- 3.20 Акцент №2: бочка + саб-бум + шумовой всплеск
    put("kick", kick_drum(0.42, 190, 55, 0.028, 0.15, click=0.4, drive=2.2, name="k-3.2"), t32, g=-1.5, trig=True,
        label="ACCENT2 kick")
    put("kick", sub_tone(0.7, 70.0, D1, tau_f=0.18, harm=0.3) * env_exp(int(0.7 * SR), a=0.003, tau=0.22), t32, g=-4.0,
        fo=960, label="ACCENT2 sub boom")
    nb = noise_sweep(0.5, 9000.0, 900.0, q=0.8, name="burst-3.2", mode="lp",
                     ampfn=lambda u: np.exp(-u * 5.0))
    put("perc", nb, t32, g=-9.0, rev=-10.0, label="ACCENT2 noise burst")

    # ---- сетка: kicks 4-on-the-floor 4.0 ... 8.8
    kick_times = []
    k = T["syncPulses"][0]
    while k < CUT_T - 1e-9:
        kick_times.append(round(k, 6))
        k += BEAT
    # на 9.0 вместо бочки идёт ролл - убираем бочки, которые попадают в последний бит перед отсчётом
    kick_times = [x for x in kick_times if x <= T["buildPulses"][2] + 1e-9]
    for i, tk in enumerate(kick_times):
        big = abs(tk - T["syncPulses"][0]) < 1e-6
        put("kick", kick_drum(0.34, 175, 55, 0.026, 0.12, click=0.32, drive=2.0, name=f"k-{tk}"), tk,
            g=-2.0 if not big else -1.5, trig=True, label="kick 4-on-floor" if i else "kick 4.0 (+clap)")

    # ---- бас D1/F1 (С2 на подъёме): на офф-битах
    chords = [(t32, "Dm", "D"), (T["syncPulses"][2], "F", "F"), (t32 + 2 * BAR, "Dm", "D"),
              (T["scan"][0], "F", "F"), (T["scan"][1], "Dm", "D"), (T["buildPulses"][2], "C", "C")]
    root_hz = {"D": D1, "F": note("F1"), "C": note("C2")}
    chord_t = [c[0] for c in chords]
    # бас: с 4.0
    def chord_at(tt):
        idx = max(i for i, c in enumerate(chord_t) if c <= tt + 1e-9)
        return chords[idx]
    for tk in kick_times:
        tb = tk + BEAT / 2.0
        if tb >= CUT_T - 0.05:
            continue
        _, kind, root = chord_at(tb)
        put("bed", bass_note(root_hz[root], BEAT / 2.0 - 0.02, f"bass{tb}"), tb, g=-6.0, label="bass offbeat")

    # ---- хлопки: 4.0 (с хлопком), затем 2-я и 4-я доли с 5.2; билд 8.0 8.4 8.8 9.0 9.1 ниже
    put("perc", clap(0.28, "clap-4.0", bits=8, rate=24000), T["syncPulses"][0], g=-7.0, rev=-14.0, label="clap 4.0")
    bars = T["syncPulses"][2]
    back = []
    tt = bars + BEAT
    while tt < T["buildPulses"][0] - 1e-9:
        back.append(round(tt, 6))
        tt += BEAT * 2
    for i, tb in enumerate(back):
        put("perc", clap(0.22, f"clap-{tb}", bits=8, rate=24000, tail_tau=0.06), tb, g=-10.0, rev=-14.0, label="clap backbeat")

    # ---- 8-бит арпа 16-ми с 3.2 до 9.2
    arp = np.zeros(N)
    t_cur = t32
    idx = 0
    while t_cur < CUT_T - 1e-9:
        _, kind, _ = chord_at(t_cur)
        tones = chord_tones(kind)
        f = tones[ARP_PATTERN[idx % len(ARP_PATTERN)]]
        # акты: октава выше для акцентов на начале такта в акте III
        nn = int(0.085 * SR)
        y = osc_square_naive(phase_of(full(f, nn)), 0.25)
        y = crush(y, 8, 24000) * env_exp(nn, a=0.0008, tau=0.04)
        y = fade_edges(y, 24, 120)
        i0 = S(t_cur)
        arp[i0:i0 + nn] += y[: N - i0]
        # шаг сетки считаем от S16, но позицию берём от S(t) без накопления ошибки
        idx += 1
        t_cur = t32 + idx * S16
    # открывающийся ФНЧ: акт II тусклее, акт III ярче
    fc = curve([(0.0, 1800.0), (t32, 1800.0), (T["syncPulses"][2], 3200.0), (T["scan"][0], 5500.0), (CUT_T, 9500.0)],
               log=True)
    s0 = S(t32)
    s1 = S(CUT_T)
    arp_f = np.zeros(N)
    arp_f[s0:s1] = svf(arp[s0:s1], fc[s0:s1], 1.0, "lp")
    arp_amp = curve([(0.0, 0.45), (t32, 0.45), (T["syncPulses"][2], 0.6), (T["agentLetters"][0][0], 0.8), (T["scan"][0], 0.9), (CUT_T, 1.0)])
    arp_f *= arp_amp
    arp_st = np.stack([arp_f, arp_f])
    arp_ec = echo_pingpong(arp_st, 3 * S16, 0.42, 3, lp_hz=4500.0)
    LAYERS["bed"].dry += (arp_st * float(db(-17.0)) + arp_ec * float(db(-20.0)))
    LAYERS["bed"].send += (arp_st * float(db(-17.0 - 16.0)))
    EVENTS.append({"label": "arp 8bit/24k 16th x%d" % idx, "t": t32, "sample": S(t32), "layer": "bed", "gain_db": -17.0})

    # ---- 3.2-4.0 три "скан"-слоя: L растущий, центр падающий, R падающий
    dur = T["teamCut"][1] - T["teamCut"][0]
    for nm, f0, f1, pn, lvl in (("scanL", 500.0, 2200.0, -0.9, -22.0), ("scanC", 2400.0, 600.0, 0.0, -23.0),
                                ("scanR", 3200.0, 850.0, 0.9, -22.0)):
        n = int((dur - 0.03) * SR)
        u = np.linspace(0.0, 1.0, n)
        f = f0 * (f1 / f0) ** u
        y = osc_tri(phase_of(f))
        y = crush(y, 8, 16000)
        flutter = 0.7 + 0.3 * osc_square_naive(np.cumsum(np.full(n, 20.0)) / SR, 0.5)
        flutter = svf(flutter, 400.0, 0.7, "lp")
        y = y * flutter * ease(u * 6.0) * (1.0 - 0.0 * u)
        put("fx", y, t32 + 0.02, g=lvl, pan=pn, rev=-16.0, fo=480, label=f"scan layer {nm}")

    # ---- хэты: 16-ми 3.2 - 9.0, кроме ускоряющегося участка 5.6-7.1
    letters = T["agentLetters"]
    acc_a, acc_b = letters[0][0], letters[-1][1]
    vel = [0.5, 0.28, 0.95, 0.32]
    t_cur = t32
    j = 0
    while t_cur < T["buildPulses"][3] - 1e-9:
        if not (acc_a - 1e-9 <= t_cur < acc_b + 0.1 + 1e-9):
            v = vel[j % 4]
            open_ = (j % 4 == 2)
            h = hat(0.11 if open_ else 0.04, tau=0.045 if open_ else 0.011, name=f"hat{j}", bright=1.0 if open_ else 1.1)
            put("perc", h, t_cur, g=-21.0 + 20 * math.log10(v), pan=0.25 if open_ else -0.1, rev=-18.0, label="hat 16th")
        j += 1
        t_cur = t32 + j * S16
    # ускоряющийся хэт 5.6-7.1: по 4 удара на букву
    for li, (a, b) in enumerate(letters):
        for q_ in range(4):
            tt = a + (b - a) * q_ / 4.0
            v = 0.45 + 0.5 * (li * 4 + q_) / (len(letters) * 4 - 1)
            put("perc", hat(0.035, tau=0.01, name=f"acc-hat{li}-{q_}"), tt, g=-21.0 + 20 * math.log10(v), pan=0.2 * ((-1) ** q_),
                rev=-18.0, label="hat accel")

    # ---- 4.8-5.2: реверс-снейр + 4 ступенчатых тика вниз
    c0, c1 = T["teamClose"]
    put("perc", reverse_snare_swell(c1 - c0, "revsnare"), c0, g=-10.0, rev=-12.0, label="reverse snare 4.8->5.2")
    for k_, nm in enumerate(("A5", "F5", "D5", "A4")):
        put("bed", lofi_tick(note(nm), 0.06, 8 - k_, 24000 - 4000 * k_, tau=0.03), c0 + k_ * S16, g=-13.0,
            pan=0.35 * ((-1) ** k_), rev=-12.0, label=f"descending tick {nm}")

    # ---- 5.2-5.6: три плака (D4 F4 A4) к 5.60 + аккорд на 5.60
    d0, d1 = T["dock"]
    for k_, nm in enumerate(("D4", "F4", "A4")):
        put("bed", saw_pluck(note(nm), 0.4, fc0=4500.0, fc1=700.0, tau_f=0.07, tau_a=0.16),
            d0 + (k_ + 1) * S16, g=-12.0, pan=-0.3 + 0.3 * k_, rev=-12.0, label=f"dock pluck {nm}")
    chord = np.zeros(int(0.5 * SR))
    for nm in ("D3", "F3", "A3", "D4", "F4", "A4"):
        ff = note(nm)
        chord += saw_pluck(ff, 0.5, fc0=4000.0, fc1=900.0, tau_f=0.12, tau_a=0.28) / 2.4
    put("bed", chord, d1, g=-11.0, rev=-10.0, label="dock chord Dm @5.6")

    # ---- 5.6-7.1: колокольчики на завершении букв D4 F4 A4 C5 D5
    for i, (a, b) in enumerate(letters):
        nm = ("D4", "F4", "A4", "C5", "D5")[i]
        put("bed", fm_bell(note(nm), 0.7, ratio=3.5, index=2.0, tau_i=0.1, tau_a=0.22, name=f"letter-bell{i}"), b,
            g=-12.0 + 0.8 * i, pan=-0.3 + 0.15 * i, rev=-9.0, label=f"letter bell {nm} @{b}")

    # ---- 7.2-8.0: райзер (пила+шум 200->8000), 8 ступенчатых ярких кликов с повышением высоты
    s0_, s1_ = T["scan"]
    rz = riser(s1_ - s0_, "riser-7.2", fc0=200.0, fc1=8000.0, f0=note("D2"), f1=note("D3"), noise_mix=0.5, pw=1.5)
    put("fx", rz, s0_, g=-16.0, rev=-15.0, fo=240, label="riser 7.2->8.0 (200->8k)")
    sstep = (s1_ - s0_) / 8.0
    for i, nm in enumerate(("D5", "F5", "A5", "C6", "D6", "F6", "A6", "C7")):
        ff = note(nm)
        nn = int(0.06 * SR)
        t = tvec(nn)
        y = osc_square_naive(phase_of(full(ff, nn)), 0.25) * 0.6 + 0.6 * np.sin(2 * np.pi * ff * 2 * t)
        y = crush(y, 8, 24000) * env_exp(nn, a=0.0005, tau=0.016)
        put("bed", y, s0_ + i * sstep, g=-16.0 + 0.6 * i, pan=0.4 * ((-1) ** i), rev=-14.0, label=f"scan click {nm}")

    # ---- 8.0 .. 9.2: ускоряющийся клэп/снейр + ролл, большой райзер до пика на 9.20
    bp = T["buildPulses"]
    for i, tb in enumerate(bp):
        put("perc", clap(0.2, f"build-clap{i}", bursts=4, spacing=0.008, tail_tau=0.05) * 0.8 + 0.5 * snare(0.2, f"build-snr{i}"),
            tb, g=-8.0 + 0.7 * i, rev=-12.0, label=f"build clap/snare {tb}")
    # ролл 16-ми 9.00-9.20 (шаг 1/2 шестнадцатой, нарастающий)
    roll_t = bp[3]
    kk = 0
    while roll_t < CUT_T - 0.01:
        if all(abs(roll_t - b) > 1e-6 for b in bp):
            v = 0.5 + 0.5 * (roll_t - bp[3]) / (CUT_T - bp[3])
            put("perc", snare(0.09, f"roll{kk}", noise_tau=0.025), roll_t, g=-14.0 + 20 * math.log10(v), pan=0.2 * ((-1) ** kk),
                label="roll 32nd")
        roll_t += S16 / 2.0
        kk += 1
    big = riser(CUT_T - bp[0], "riser-big", fc0=500.0, fc1=14000.0, f0=note("D2"), f1=note("D4"), noise_mix=0.55, q=1.5, pw=1.8,
                gate_rate=(4.0, 34.0))
    put("fx", big, bp[0], g=-14.0, rev=-16.0, fo=24, label="big riser 8.0->9.2 peak@9.2")
    # sub-pedal на подъёме: D1 -> нарастает
    dpe = CUT_T - T["scan"][1]
    subr = sub_tone(dpe, D1, harm=0.3) * (ease(np.linspace(0, 1, int(dpe * SR))) ** 1.2)
    put("kick", subr, T["scan"][1], g=-17.0, fo=24, label="sub swell 8.0->9.2")


def score_countdown():
    """9.20 - 9.60: музыка вырезана; падающие тона теряют разрешение; пинг; обратный свелл."""
    freqs = [note("A5"), note("A4"), note("A3"), note("A2")]
    bits = [8, 6, 4, 3]
    rates = [32000, 16000, 8000, 4000]
    lps = [11000.0, 5200.0, 2400.0, 900.0]
    durs = [0.085, 0.085, 0.085, 0.05]
    for i, tc in enumerate(CD):
        n = int(durs[i] * SR)
        u = np.linspace(0.0, 1.0, n)
        f = freqs[i] * 0.5 ** (u * 0.9)           # быстрое падение вниз
        y = 0.7 * osc_tri(phase_of(f)) + 0.35 * osc_square_naive(phase_of(f), 0.5)
        y = crush(y, bits[i], rates[i])
        y = svf(y, lps[i], 1.0, "lp") * env_exp(n, a=0.0006, tau=durs[i] * 0.8)
        put("cd", y, tc, g=-2.5 - 0.5 * i, rev=-20.0, fi=24, fo=120, label=f"countdown tone {i} {note_name(freqs[i])} {bits[i]}bit")
    # 9.5-9.6: почти тишина - один высокий пинг + обратный свелл
    tp = CD[-1] + 0.05
    put("cd", glass_ping(note("A6"), 0.14, tau=0.06, name="cd-ping") * 0.5, tp, g=-12.0, rev=-14.0, label="high ping A6")
    t_end = HIT - 0.012           # 12 мс воздуха перед ударом
    t0 = CD[-1] + 0.005
    n = int((t_end - t0) * SR)
    u = np.linspace(0.0, 1.0, n)
    sw = svf(rng("cd-swell").standard_normal(n), 300.0 * (9000.0 / 300.0) ** (u ** 1.5), 1.0, "bp")
    tone = np.zeros(n)
    t = tvec(n)
    for nm in ("A3", "E4", "A4"):
        tone += np.sin(2 * np.pi * note(nm) * t)
    y = (0.9 * sw + 0.12 * tone) * (u ** 1.8)
    st = pan_curve(y, -0.15, 0.15)
    put("cd", st, t0, g=-4.0, fi=48, fo=576, label="reverse swell (inhale) ->9.6")


def note_name(f):
    return {880.0: "A5", 440.0: "A4", 220.0: "A3", 110.0: "A2"}.get(round(f, 1), f"{f:.1f}Hz")


def score_climax():
    """9.600 и далее: полноразрядное широкое стерео, Dmaj9, pad, тики, финал."""
    # ---- ГЛАВНЫЙ УДАР
    # саб-бум D1: скольжение 80 -> 36 Гц за ~1.2 с
    dur = 2.0
    n = int(dur * SR)
    boom = sub_tone(dur, 80.0, D1, tau_f=0.33, harm=0.35, drive=1.6)
    t = tvec(n)
    boom *= np.minimum(1.0, t / 0.003) * np.exp(-np.maximum(t - 0.1, 0) / 0.75)
    # скольжение 80->36 Гц задано на 1.2 с; амплитуда уходит к LIGHT_OUT вслед за светом знака
    boom *= curve([(0.0, 1.0), (LIGHT_BRIGHT - HIT, 1.0), (LIGHT_OUT - HIT, 0.0), (dur, 0.0)], n=n)
    put("hit", boom, HIT, g=-4.5, fo=480, label="HIT sub boom 80->36Hz (fades with light)")
    # большая бочка
    put("hit", kick_drum(0.6, 210, 52, 0.032, 0.2, click=0.5, drive=2.4, name="k-big"), HIT, g=-3.0, trig=True,
        label="HIT big kick")
    # широкий шум (стерео, декоррелированный)
    wn = noise_sweep(1.8, 8500.0, 1800.0, q=0.7, name="hit-noise", mode="lp", wide=True,
                     ampfn=lambda u: np.exp(-u * 3.4))
    put("hit", wn, HIT, g=-9.5, rev=-8.0, fi=96, label="HIT wide noise")
    # тарелка-крэш
    put("hit", crash(2.8, "hit-crash", tau=0.95), HIT, g=-15.5, rev=-8.0, fi=96, label="HIT crash")
    # аккорд Dmaj9 (суперпила) D2 A2 E3 F#3 A3 C#4 E4
    chord_hz = [note(x) for x in ("D2", "A2", "E3", "F#3", "A3", "C#4", "E4")]
    cd = LIGHT_OUT - HIT + 0.02
    ss = supersaw(chord_hz, cd, "dmaj9-super", voices=5, detune_c=14.0)
    ss *= curve([(0, 1.0), (0.12, 1.0), (LIGHT_BRIGHT - HIT, 0.62), (LIGHT_OUT - HIT, 0.0), (cd, 0.0)], n=int(cd * SR), ease_on=True)[None, :]
    put("pad", ss, HIT, g=-6.0, rev=-5.0, fo=960, label="HIT Dmaj9 supersaw")

    # ---- 9.600-10.100: 8 металлических кликов с ростом высоты (по аккорду), расширяющаяся база
    fr = T["waveFrames"] * FRAME
    clicks = ["D5", "F#5", "A5", "C#6", "E6", "F#6", "A6", "C#7"]
    for k, nm in enumerate(clicks):
        tt = HIT + k * fr
        width = 0.12 + 0.82 * k / 7.0
        pn = width * (1 if k % 2 == 0 else -1)
        put("post", metal_click(note(nm), 0.12, f"mclick{k}"), tt, g=-17.0 + 0.4 * k, pan=pn, rev=-9.0, label=f"metal click {nm}")

    # ---- знак сияет (до LIGHT_OUT): тихие искры
    r = rng("sparks-10.1")
    sp0 = HIT + 0.52
    sp_step = (LIGHT_OUT - 0.04 - sp0) / 6.0
    for i in range(6):
        tt = sp0 + sp_step * i + float(r.uniform(0, 0.03))
        nm = ["A6", "F#6", "D7", "E6", "B6", "F#6"][i]
        put("post", glass_ping(note(nm), 0.5, tau=0.18, name=f"spark{i}"), tt, g=-27.0 + float(r.uniform(-2, 2)),
            pan=float(r.uniform(-0.85, 0.85)), rev=-4.0, label=f"spark {nm}")

    # ---- pad: Dmaj9 (чистый) с 9.6, затем Gmaj9 с 11.2 (hit+BAR), D с 12.7; ФНЧ-огибающая ниже
    ch1 = [note(x) for x in ("D3", "A3", "E4", "F#4", "A4", "C#5")]           # Dmaj9
    ch2 = [note(x) for x in ("G2", "D3", "F#3", "B3", "D4", "A4")]            # Gmaj9 (без 5-й)
    ch3 = [note(x) for x in ("D3", "A3", "D4", "F#4", "A4", "E5")]            # Dadd9/maj
    t_a = HIT
    t_b = T["lock"][0]               # сжатие знака: Gmaj9 входит со стартом сжатия
    t_c = T["dotAccents"][0]         # «точка»: финальный чистый D

    def pad_chord(freqs, t0, dur, att, rel, label, g, pts=None):
        n = int(dur * SR)
        acc = np.zeros((2, n))
        for i, f in enumerate(freqs):
            acc += pad_note(f, dur, f"{label}-{i}") / math.sqrt(len(freqs))
        env = curve(pts if pts else [(0, 0), (att, 1), (dur - rel, 1), (dur, 0)], n=n)
        acc = acc * env[None, :]
        held = env > 0.5
        rms = math.sqrt(float(np.mean(acc[:, held] ** 2)))
        acc *= 0.1 / rms                       # опорный уровень -20 dBFS RMS на удержании, g - относительно него
        put("pad", acc, t0, g=g, rev=-7.0, fi=24, fo=240, label=label)

    d1 = (t_b + 0.4) - t_a
    pad_chord(ch1, t_a, d1, 0, 0, "pad Dmaj9", -3.0,
              pts=[(0, 0), (0.18, 1), (LIGHT_BRIGHT - t_a, 1), (LIGHT_OUT - t_a, 0.22), (t_b - t_a, 0.22), (d1, 0)])
    pad_chord(ch2, t_b, (t_c + 0.35) - t_b, 0.5, 0.6, "pad Gmaj9", -2.0)
    pad_chord(ch3, t_c - 0.08, DURATION - (t_c - 0.08), 0.45, DURATION - T["lastTick"] - 0.02, "pad D final", -2.0)

    # ---- мягкий свуш L->R на сжатии знака (lock)
    l0, l1 = T["lock"]
    sw = noise_sweep(l1 - l0, 2800.0, 600.0, q=1.2, name="lock-swish", mode="bp", wide=False,
                     ampfn=lambda u: np.sin(np.pi * np.clip(u, 0, 1)) ** 1.5)
    put("post", pan_curve(sw, -0.95, 0.95), l0, g=-17.0, rev=-5.0, fo=480, label="soft swish L->R")

    # ---- 10.95-11.70 каскад гранулярных тиков (~400/с), панорама L->R, D-мажорная пентатоника
    p0, p1 = T["print"]
    r = rng("print-cascade")
    ntick = int(round((p1 - p0) * 400.0))
    for i in range(ntick):
        u = i / max(ntick - 1, 1)
        tt = p0 + (p1 - p0) * u
        nm = PENTA_HI[int(r.integers(0, len(PENTA_HI)))]
        f = note(nm)
        gl = int(0.0045 * SR)
        tg = tvec(gl)
        y = osc_tri(phase_of(full(f, gl))) * (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(gl) / gl))
        y = crush(y, 8, 24000)
        lvl = -33.0 + 5.0 * math.sin(math.pi * u) + float(r.uniform(-1.5, 1.5))
        put("post", y, tt, g=lvl, pan=-0.9 + 1.8 * u + float(r.uniform(-0.05, 0.05)), rev=-3.0, fi=0, fo=0)
    EVENTS.append({"label": "print cascade grains x%d (~400/s) L->R" % ntick, "t": p0, "sample": S(p0), "layer": "post", "gain_db": -33.0})
    put("post", fm_bell(note("D6"), 1.4, ratio=3.5, index=1.6, tau_i=0.12, tau_a=0.5, name="bellD6"), p1, g=-15.0, pan=0.1,
        rev=-4.0, label="bell D6 @print end")

    # ---- 11.8-12.1 тонкий восходящий свип в 3 ступени
    r0, r1 = T["rule"]
    st = (r1 - r0) / 3.0
    prev = note("D5")
    for i, nm in enumerate(("F#5", "A5", "D6")):
        ff = note(nm)
        n = int(st * SR)
        u = np.linspace(0, 1, n)
        f = np.where(u < 0.3, prev * (ff / prev) ** ease(u / 0.3), ff)
        y = crush(osc_tri(phase_of(f)), 8, 24000) * (0.6 + 0.4 * u) * np.minimum(1.0, 1.0 - np.maximum(u - 0.75, 0) / 0.25)
        put("post", y, r0 + i * st, g=-26.0 + 1.5 * i, pan=-0.2 + 0.2 * i, rev=-6.0, fo=96, label=f"rule sweep step {nm}")
        prev = ff

    # ---- 11.9-12.7 "клавиши": один тик на кадр
    g0, g1 = T["tagline"]
    nk = int(round((g1 - g0) / FRAME))
    r = rng("keys")
    for k in range(nk):
        tt = g0 + k * FRAME
        ff = note(["A6", "D7", "F#6", "B6", "E7", "A6"][int(r.integers(0, 6))])
        n = int(0.011 * SR)
        y = osc_square_naive(phase_of(full(ff, n)), 0.25)
        y = crush(y, 6, 24000) * env_exp(n, a=0.0003, tau=0.0028)
        y2 = np.diff(r.standard_normal(n), prepend=0.0) * env_exp(n, a=0.0002, tau=0.0012) * 0.5
        put("post", y * 0.7 + y2, tt, g=-35.0 + (3.0 if k % 5 == 0 else 0.0), pan=float(r.uniform(-0.6, 0.6)), rev=-6.0, fo=48,
            label="key tick" if k == 0 else None)

    # ---- 12.7 13.1 13.5: «точка» вордмарка
    da = T["dotAccents"]
    pk = saw_pluck(note("D5"), 0.9, fc0=5200.0, fc1=700.0, tau_f=0.11, tau_a=0.28)
    pk = echo_mono_to_stereo_tail(pk, 0.3, 0.38, 2)
    put("post", pk, da[0], g=-15.0, rev=-5.0, label="dot1 D5 warm pluck")
    bl = fm_bell(note("A5"), 1.2, ratio=3.5, index=1.8, tau_i=0.14, tau_a=0.42, name="dot-bell")
    bl = echo_mono_to_stereo_tail(bl, 0.3, 0.36, 2)
    put("post", bl, da[1], g=-17.0, rev=-5.0, label="dot2 A5 bell")
    gl = glass_ping(note("F#6"), 1.3, tau=0.5, name="dot-glass")
    gl = echo_mono_to_stereo_tail(gl, 0.3, 0.36, 2)
    put("post", gl, da[2], g=-19.0, rev=-4.0, label="dot3 F#6 glass")

    # ---- 14.00 мягкий низкий пульс (саб D1, 50 мс) + воздушный свелл
    tl = T["lastTick"]
    n = int(0.05 * SR)
    pulse = sub_tone(0.05, D1, harm=0.25, drive=1.1) * np.sin(np.pi * np.linspace(0, 1, n)) ** 1.5
    put("post", pulse, tl, g=-9.0, fi=48, fo=240, label="last tick sub pulse D1 50ms")
    dsw = 0.9
    r = rng("air-14")
    # свелл набирается ДО последнего тика и уходит после
    pre = 0.2
    nn = int((pre + dsw) * SR)
    amp_full = np.concatenate([ease(np.linspace(0, 1, int(pre * SR))) ** 2, np.exp(-np.arange(int(dsw * SR)) / SR / 0.3)])
    air_full = np.stack([svf(r.standard_normal(nn), 5200.0, 0.9, "bp"), svf(r.standard_normal(nn), 5200.0, 0.9, "bp")])
    put("post", air_full * amp_full[None, :], tl - pre, g=-25.0, rev=-3.0, fo=960, label="air swell around 14.0")


def score_all():
    reset_state()
    score_act1_2_pre()
    score_act2_3_pre()
    score_countdown()
    score_climax()


# --------------------------------------------------------------------------- #
# Микс
# --------------------------------------------------------------------------- #
def follower(x, atk, rel):
    aa = math.exp(-1.0 / (atk * SR))
    ar = math.exp(-1.0 / (rel * SR))
    y = 0.0
    out = [0.0] * len(x)
    for i, v in enumerate(x.tolist()):
        if v > y:
            y = v + aa * (y - v)
        else:
            y = v + ar * (y - v)
        out[i] = y
    return np.array(out)


def sidechain_gain(trig, depth_db, atk=0.0015, rel=0.16, ref=0.5):
    env = follower(trig, atk, rel)
    amount = 1.0 - float(db(-depth_db))
    return 1.0 - amount * np.clip(env / ref, 0.0, 1.0)


def lofi_bandwidth(x2):
    """Полоса растёт ступенями вместе с разрешением картинки (пока звучит 'лоуфай')."""
    res_t = [t for t, _ in T["ideaRes"]]               # 0.4 0.6 0.8 1.0 1.2
    freqs = [3200.0, 4500.0, 6500.0, 9500.0, 14000.0]   # ступени полосы в такт ступеням разрешения
    pts = [(0.0, 3200.0)]
    for t0, f0 in zip(res_t, freqs):
        pts += [(t0, f0), (t0 + 0.04, f0)]
    a3 = T["agentLetters"][0][0]
    pts += [(T["n8"], 14000.0), (T["n8"] + 0.04, 17000.0), (a3, 17000.0), (a3 + 0.04, 21000.0), (CUT_T + 0.01, 21000.0)]
    clean = []
    for t_, f_ in pts:                                   # t строго возрастает
        if clean and t_ <= clean[-1][0]:
            t_ = clean[-1][0] + 1e-5
        clean.append((t_, f_))
    fc = curve(clean, log=True, ease_on=True)
    s1 = S(CUT_T + 0.02)
    out = x2.copy()
    out[:, :s1] = svf_st(x2[:, :s1], fc[:s1], 0.7071, "lp")
    return out


def ACT_TRIM_DB():
    """Кривая динамики по актам (дБ): акт II тише, акт III растёт, билд - максимум перед вырезом."""
    return curve([(0.0, 0.0), (T["n8"] + 0.3, 0.0), (T["syncPulses"][0], -3.5), (T["syncPulses"][2], -3.5),
                  (T["agentLetters"][0][0], -2.0), (T["scan"][0], -1.0), (T["buildPulses"][0], 0.0), (CUT_T, 1.0)])


def mix_all(irs):
    IR_ROOM, IR_HALL = irs
    pre = {}
    for k in ("kick", "perc", "bed", "fx"):
        L = LAYERS[k]
        pre[k] = L.dry + conv_stereo(L.send, IR_ROOM)
    duck = sidechain_gain(TRIG, depth_db=9.0)
    pre["bed"] = pre["bed"] * duck[None, :]
    # воздух (30 мс) перед акцентом №2 на 3.20 для постели и fx; ровный фейд, без щелчка
    gap = curve([(0, 1), (T["n8"] - 0.034, 1), (T["n8"] - 0.029, 0.0), (T["n8"] - 1e-4, 0.0), (T["n8"] + 0.002, 1.0)])
    pre["bed"] = pre["bed"] * gap[None, :]
    pre["fx"] = pre["fx"] * gap[None, :]
    pre_sum = pre["kick"] + pre["perc"] + pre["bed"] + pre["fx"]
    pre_sum = pre_sum * np.power(10.0, ACT_TRIM_DB() / 20.0)[None, :]
    pre_sum = lofi_bandwidth(pre_sum)
    cut = curve([(0, 1), (CUT_T, 1), (CUT_T + 0.003, 0)])
    pre_sum = pre_sum * cut[None, :]
    LAYERS_OUT = {"pre": pre_sum}

    cdL = LAYERS["cd"]
    cd_sum = cdL.dry + conv_stereo(cdL.send, IR_ROOM)
    cd_sum = cd_sum * curve([(0, 1), (HIT - 0.0135, 1), (HIT - 0.0095, 0), (HIT, 0)])[None, :]

    hit = LAYERS["hit"].dry + conv_stereo(LAYERS["hit"].send, IR_HALL)
    padL = LAYERS["pad"]
    pad = padL.dry + conv_stereo(padL.send, IR_HALL)
    duck_pad = sidechain_gain(TRIG * (np.arange(N) >= S(HIT)), depth_db=5.0, rel=0.35)
    pad = pad * duck_pad[None, :]
    fc = curve([(0, 14000.0), (HIT, 14000.0), (LIGHT_BRIGHT, 9000.0), (LIGHT_OUT, 600.0), (T["lock"][0], 600.0),
                (T["lock"][0] + 0.5, 2500.0), (T["print"][1], 4500.0), (T["rule"][1] + 0.3, 9000.0), (T["lastTick"], 9000.0)],
               log=True)
    s0 = S(HIT) - 2
    pad_f = pad.copy()
    pad_f[:, s0:] = svf_st(pad[:, s0:], fc[s0:], 0.7071, "lp")
    # свет уходит -> хвост удара и pad затихают вслед (гладкие кривые в дБ)
    hit = hit * np.power(10.0, curve([(0, 0.0), (LIGHT_BRIGHT, 0.0), (LIGHT_OUT, -24.0)]) / 20.0)[None, :]
    pad_f = pad_f * np.power(10.0, curve([(0, 0.0), (LIGHT_BRIGHT, 0.0), (LIGHT_OUT, -9.0), (T["lock"][0], -9.0),
                                          (T["lock"][0] + 0.7, 0.0)]) / 20.0)[None, :]
    post = LAYERS["post"].dry + conv_stereo(LAYERS["post"].send, IR_HALL)
    return pre_sum, cd_sum, hit, pad_f, post


# --------------------------------------------------------------------------- #
# Мастеринг: HP, мягкий клиппер, lookahead true-peak лимитер, фейд
# --------------------------------------------------------------------------- #
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


def master(mix, gain_db, ceiling_db=TRUE_PEAK_CEIL_DB, knee=0.72):
    y = mix * float(db(gain_db))
    y = soft_clip(y, knee)
    y, g = limiter(y, float(db(ceiling_db)))
    fade = curve([(0.0, 0.0), (0.002, 1.0), (T["staticFrom"] - 0.25, 1.0), (DURATION - 0.04, 0.0), (DURATION, 0.0)])
    return y * fade[None, :], g


# --------------------------------------------------------------------------- #
# Измерение громкости (BS.1770-4, интегральная, гейтинг) - для подбора гейна
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# WAV
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
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


def main():
    t_start = time.time()
    score_all()
    print(f"[score] {len(EVENTS)} подписанных событий, {time.time()-t_start:.1f} c")

    IR_ROOM = make_ir("room", 0.9, 0.55, 0.18, corr=0.88, predelay=0.004, er_taps=6, er_span=0.03)
    IR_HALL = make_ir("hall", 5.0, 4.4, 1.7, corr=0.0, predelay=0.024, er_taps=10, er_span=0.07)
    pre_sum, cd_sum, hit, pad, post = mix_all((IR_ROOM, IR_HALL))
    print(f"[mix] {time.time()-t_start:.1f} c")
    mix = pre_sum * float(db(PRE_TRIM)) + cd_sum + hit + pad + post
    # HP 22 Гц: убрать DC/субзвук
    mix = svf_st(mix, 22.0, 0.7071, "hp")

    # подбор мастер-гейна под -14 LUFS integrated, потолка лимитера - под true peak после AAC
    g = 0.0
    ceil = TRUE_PEAK_CEIL_DB
    for outer in range(6):
        for it in range(8):
            y, gr = master(mix, g, ceil)
            l = integrated_lufs(y) + LUFS_CAL_DB
            print(f"[gain] ceil={ceil:+.2f} it={it} gain={g:+.2f} dB  LUFS={l:.2f}  maxGR={20*np.log10(gr.min()):.2f} dB")
            if abs(l - TARGET_LUFS) < 0.03:
                break
            g += (TARGET_LUFS - l) * 0.9
        y, gr = master(mix, g, ceil)
        tp_aac, l_aac = aac_probe(y)
        print(f"[aac] ceiling={ceil:+.2f} dBTP -> after AAC 192k: true-peak={tp_aac:+.2f} dBTP, integrated={l_aac:.2f} LUFS")
        if tp_aac <= AAC_TP_LIMIT_DB:
            break
        ceil -= (tp_aac - AAC_TP_LIMIT_DB) + 0.05
    grdb = 20 * np.log10(np.maximum(gr, 1e-6))
    print("[limiter] макс. gain reduction по секундам (dB): " +
          " ".join(f"{grdb[i*SR:(i+1)*SR].min():.1f}" for i in range(15)))
    q = write_wav24(OUT_WAV, y)
    with open(OUT_WAV, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    print(f"[out] {OUT_WAV}  samples={q.shape[1]}  gain={g:+.2f} dB  sha256={sha[:16]}")
    print(f"[meter] integrated={integrated_lufs(y):.2f} LUFS  true-peak(4x)={20*np.log10(true_peak_lin(y)):.2f} dBTP  "
          f"sample-peak={20*np.log10(np.abs(y).max()):.2f} dBFS")
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({"sr": SR, "samples": N, "master_gain_db": round(g, 3), "limiter_ceiling_db": round(ceil, 3),
                   "after_aac192_true_peak_db": tp_aac, "after_aac192_lufs": l_aac, "sha256_wav": sha,
                   "events": sorted(EVENTS, key=lambda e: (e["sample"], e["label"]))}, f, ensure_ascii=False, indent=1)
    print(f"[done] {time.time()-t_start:.1f} c")


if __name__ == "__main__":
    main()
