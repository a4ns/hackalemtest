#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ готового микса: метрики по окнам, проверки стыков/клиппинга и спектрограмма PNG (PIL + numpy).

  python3 audio/analyze_audio.py [путь.wav] [путь.png]

По умолчанию:  assets/audio/hackalem-intro-mix.wav  ->  docs/assets/sound_spectrogram.png
"""
from __future__ import annotations

import json
import math
import os
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WAV = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "assets", "audio", "hackalem-intro-mix.wav")
PNG = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "docs", "assets", "sound_spectrogram.png")
with open(os.path.join(ROOT, "config", "cues.json"), "r", encoding="utf-8") as _f:
    T = json.load(_f)["T"]


def read_wav24(path):
    with wave.open(path, "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    assert sw == 3 and ch == 2
    b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
    v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
    v = np.where(v & 0x800000, v - 0x1000000, v).astype(np.float64) / 8388608.0
    return v.reshape(-1, 2).T.copy(), sr, n


def dbfs(x, floor=-120.0):
    return 20.0 * math.log10(max(x, 10 ** (floor / 20.0)))


def rms_db(x):
    return dbfs(float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0)


def corr(a, b):
    sa, sb = a.std(), b.std()
    if sa < 1e-9 or sb < 1e-9:
        return float("nan")
    return float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))


def momentary_table(x, sr):
    sys.path.insert(0, HERE)
    import build_audio as B
    kw = B.k_weight(x)
    e = (kw ** 2).sum(axis=0)
    cs = np.concatenate([[0.0], np.cumsum(e)])
    blk = int(0.4 * sr)
    print("\n== Momentary LUFS (окно 400 мс, шаг 0.5 с; центр окна) ==")
    row = []
    for k in range(0, 30):
        c = int((k * 0.5) * sr)
        a, b = max(0, c - blk // 2), min(x.shape[1], c + blk // 2)
        z = (cs[b] - cs[a]) / max(b - a, 1)
        row.append((k * 0.5, -0.691 + 10 * math.log10(max(z, 1e-12))))
    for i in range(0, len(row), 6):
        print("  " + "  ".join(f"{t:4.1f}s:{v:6.1f}" for t, v in row[i:i + 6]))
    print(f"  Integrated (внутренний): {B.integrated_lufs(x):.2f} LUFS, true-peak(4x) {20 * math.log10(B.true_peak_lin(x)):.2f} dBTP")


def metrics(x, sr):
    n = x.shape[1]
    mono = x.mean(axis=0)
    mid, side = (x[0] + x[1]) / 2, (x[0] - x[1]) / 2
    print("\n== RMS / пик / ширина по секундным окнам ==")
    print(" окно, с      RMS dBFS   пик dBFS   S/M dB   corr(L,R)")
    for s in range(15):
        a, b = s * sr, (s + 1) * sr
        seg = x[:, a:b]
        sm = rms_db(side[a:b]) - rms_db(mid[a:b]) if rms_db(mid[a:b]) > -100 else float("nan")
        print(f" {s:2d}.0-{s+1:2d}.0    {rms_db(seg):8.1f}   {dbfs(np.abs(seg).max()):8.1f}   {sm:7.1f}   {corr(x[0, a:b], x[1, a:b]):7.2f}")
    print("\n== Ключевые окна ==")
    wins = [("0.00-0.35 акцент №1", 0.0, 0.35), ("2.4-3.2 арпеджио+райзер", 2.4, 3.2), ("3.2-3.4 акцент №2", 3.2, 3.4),
            ("8.0-9.2 билд", 8.0, 9.2), ("9.20-9.50 отсчёт", 9.2, 9.5), ("9.50-9.60 вдох", 9.5, 9.6),
            ("9.60-9.80 ГЛАВНЫЙ УДАР", 9.6, 9.8), ("9.6-10.6 климакс", 9.6, 10.6), ("10.6-11.7 затухание/печать", 10.6, 11.7),
            ("12.7-13.9 точки/pad", 12.7, 13.9), ("14.0-15.0 финал", 14.0, 15.0)]
    for name, a, b in wins:
        seg = x[:, int(a * sr):int(b * sr)]
        mid_, side_ = (seg[0] + seg[1]) / 2, (seg[0] - seg[1]) / 2
        print(f" {name:28s} RMS {rms_db(seg):7.1f} dBFS   пик {dbfs(np.abs(seg).max()):7.1f}   S/M {rms_db(side_) - rms_db(mid_):6.1f} dB   corr {corr(seg[0], seg[1]):5.2f}")
    # 20 мс окна вокруг 9.2..9.6 для проверки "вырезания"
    print("\n== 9.2-9.6, окна по 20 мс (RMS dBFS) ==")
    row = []
    for k in range(20):
        a = int((9.2 + 0.02 * k) * sr)
        row.append(f"{rms_db(x[:, a:a + int(0.02 * sr)]):6.1f}")
    print(" ".join(row))
    print("\n== Проверки целостности ==")
    for nm, a, b in (("первые 10 мс", 0, int(0.01 * sr)), ("последние 10 мс", n - int(0.01 * sr), n)):
        seg = x[:, a:b]
        print(f" {nm}: макс|x| = {np.abs(seg).max():.3e} ({dbfs(np.abs(seg).max()):.1f} dBFS), x[edge] L/R = "
              f"{seg[0, 0 if a == 0 else -1]:+.2e}/{seg[1, 0 if a == 0 else -1]:+.2e}")
    d = np.abs(np.diff(x, axis=1)).max(axis=0)
    i = int(d.argmax())
    print(f" макс скачок между соседними семплами: {d.max():.4f} FS на t={i / sr:.4f} с")
    print(f" семплов >= 0.98 FS: {(np.abs(x) >= 0.98).sum()},  >= 0.89 FS (-1 dBFS): {(np.abs(x) >= 0.891).sum()}")
    print(f" DC (среднее): L {x[0].mean():+.2e}  R {x[1].mean():+.2e}")
    # локальные "щелчки": резкие скачки на фоне тихой окрестности
    hp = np.diff(mono, n=2)
    blk = 480
    worst = (0.0, 0)
    for s in range(blk, n - blk, blk):
        loc = np.abs(hp[s - blk:s]).mean() + 1e-6
        jump = np.abs(hp[s:s + blk]).max()
        if jump / loc > worst[0] and jump > 0.02:
            worst = (jump / loc, s)
    print(f" макс. отношение 2-й разности к фону (кандидат на щелчок): {worst[0]:.1f} на t={worst[1] / sr:.3f} с")


# --------------------------------------------------------------------------- #
# Спектрограмма
# --------------------------------------------------------------------------- #
def inferno_lut():
    stops = [(0.00, (0, 0, 4)), (0.15, (31, 12, 72)), (0.30, (85, 15, 109)), (0.45, (136, 34, 106)), (0.60, (186, 54, 85)),
             (0.75, (227, 89, 51)), (0.88, (249, 140, 10)), (0.96, (245, 219, 76)), (1.00, (252, 255, 164))]
    lut = np.zeros((256, 3), dtype=np.uint8)
    xs = np.array([s[0] for s in stops])
    for c in range(3):
        lut[:, c] = np.interp(np.linspace(0, 1, 256), xs, [s[1][c] for s in stops])
    return lut


FONT_CANDIDATES = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                   "/usr/share/fonts/truetype/freefont/FreeSans.ttf"]
HAS_CYR = False


def font(sz):
    global HAS_CYR
    for pth in FONT_CANDIDATES:
        if os.path.exists(pth):
            HAS_CYR = True
            return ImageFont.truetype(pth, sz)
    HAS_CYR = False
    try:
        return ImageFont.load_default(size=sz)
    except TypeError:
        return ImageFont.load_default()


def L(ru, en):
    return ru if HAS_CYR else en


def stft_mag(mono, sr, nfft=4096, hop=256):
    win = np.hanning(nfft)
    n_fr = 1 + (len(mono) - nfft) // hop
    pad = nfft // 2
    xm = np.concatenate([np.zeros(pad), mono, np.zeros(pad)])
    n_fr = 1 + (len(xm) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(n_fr)[:, None]
    spec = np.abs(np.fft.rfft(xm[idx] * win[None, :], axis=1))
    return spec / (nfft / 4.0), hop


def render_png(x, sr, path):
    mono = x.mean(axis=0)
    spec, hop = stft_mag(mono, sr)
    freqs = np.fft.rfftfreq(4096, 1.0 / sr)
    W, H_SP, H_RMS, H_COR = 1800, 640, 150, 90
    ML, MR, MT, MB = 70, 24, 54, 40
    total_h = MT + H_SP + 14 + H_RMS + 14 + H_COR + MB
    PW = W - ML - MR
    img = Image.new("RGB", (W, total_h), (8, 12, 22))
    d = ImageDraw.Draw(img)
    f_s, f_m, f_b = font(13), font(15), font(20)
    d.text((ML, 14), L("HackAlem AI intro — спектрограмма (моно-сумма, лог. частота) / RMS / корреляция L-R", "HackAlem AI intro - spectrogram (mono sum, log freq) / RMS / L-R correlation"), font=f_b, fill=(234, 246, 255))

    # --- спектрограмма
    fmin, fmax = 30.0, 20000.0
    ys = np.exp(np.linspace(math.log(fmax), math.log(fmin), H_SP))
    bin_f = ys / (sr / 4096.0)
    b0 = np.clip(np.floor(bin_f).astype(int), 0, spec.shape[1] - 2)
    fr = bin_f - b0
    cols = np.clip((np.arange(PW) / PW * (len(mono) / sr) * sr / hop).astype(int), 0, spec.shape[0] - 1)
    S = spec[cols][:, :]  # (PW, bins)
    img_db = np.empty((H_SP, PW))
    mag = S[:, b0] * (1 - fr)[None, :] + S[:, b0 + 1] * fr[None, :]   # (PW, H_SP)
    img_db = 20 * np.log10(np.maximum(mag.T, 1e-9))
    lo, hi = -105.0, -18.0
    norm = np.clip((img_db - lo) / (hi - lo), 0, 1)
    rgb = inferno_lut()[(norm * 255).astype(np.uint8)]
    img.paste(Image.fromarray(rgb, "RGB"), (ML, MT))
    d.rectangle([ML, MT, ML + PW, MT + H_SP], outline=(80, 96, 120))

    def xpix(t):
        return ML + t / (len(mono) / sr) * PW

    for fq, lab in ((50, "50"), (100, "100"), (200, "200"), (500, "500"), (1000, "1k"), (2000, "2k"), (5000, "5k"), (10000, "10k"), (20000, "20k")):
        y = MT + H_SP * (math.log(fmax / fq) / math.log(fmax / fmin))
        d.line([ML - 5, y, ML, y], fill=(150, 165, 190))
        d.text((ML - 8, y - 7), lab, font=f_s, fill=(170, 185, 210), anchor="ra")
        d.line([ML, y, ML + PW, y], fill=(255, 255, 255, 30) if False else (40, 52, 74))
    # маркеры
    marks = [(0.0, L("0.00 акцент", "0.00 accent")), (T["n2"], "0.40"), (T["n8"], L("3.20 акцент 2", "3.20 accent 2")),
             (T["syncPulses"][0], L("4.0 ритм", "4.0 groove")), (T["scan"][0], L("7.2 райзер", "7.2 riser")),
             (T["countdown"][0], L("9.2 вырез", "9.2 cut")), (T["hit"], L("9.60 УДАР", "9.60 HIT")),
             (T["lock"][0], "10.5"), (T["print"][0], L("10.95 печать", "10.95 print")), (T["dotAccents"][0], L("12.7 точки", "12.7 dots")),
             (T["lastTick"], "14.0")]
    for t, lab in marks:
        xp = xpix(t)
        col = (255, 255, 255) if abs(t - T["hit"]) < 1e-6 else (120, 200, 255)
        d.line([xp, MT, xp, MT + H_SP + 14 + H_RMS + 14 + H_COR], fill=col + (0,) if False else col, width=1)
    for i, (t, lab) in enumerate(marks):
        d.text((xpix(t) + 3, MT + 3 + 14 * (i % 3)), lab, font=f_s, fill=(255, 255, 255))
    for s in range(16):
        xp = xpix(s)
        d.line([xp, MT + H_SP, xp, MT + H_SP + 5], fill=(170, 185, 210))
        d.text((xp, total_h - MB + 6), f"{s}", font=f_s, fill=(170, 185, 210), anchor="ma")
    d.text((ML + PW / 2, total_h - 18), L("время, с", "time, s"), font=f_s, fill=(170, 185, 210), anchor="ma")

    # --- RMS (окна 50 мс) в дБ
    y0 = MT + H_SP + 14
    d.rectangle([ML, y0, ML + PW, y0 + H_RMS], outline=(80, 96, 120), fill=(12, 18, 32))
    win = int(0.05 * sr)
    nwin = len(mono) // win
    seg = x[:, : nwin * win].reshape(2, nwin, win)
    r = 10 * np.log10(np.maximum((seg ** 2).mean(axis=(0, 2)), 1e-12))
    pk = 20 * np.log10(np.maximum(np.abs(seg).max(axis=(0, 2)), 1e-9))
    for lvl in (-60, -40, -20, 0):
        y = y0 + H_RMS * (0 - lvl) / 60.0
        d.line([ML, y, ML + PW, y], fill=(40, 52, 74))
        d.text((ML - 8, y - 7), f"{lvl}", font=f_s, fill=(170, 185, 210), anchor="ra")
    pts_r, pts_p = [], []
    for i in range(nwin):
        xp = ML + (i + 0.5) * win / (len(mono)) * PW
        pts_r.append((xp, y0 + H_RMS * (0 - max(r[i], -60)) / 60.0))
        pts_p.append((xp, y0 + H_RMS * (0 - max(pk[i], -60)) / 60.0))
    d.line(pts_p, fill=(90, 120, 170), width=1)
    d.line(pts_r, fill=(255, 178, 63), width=2)
    d.text((ML + 6, y0 + 4), L("RMS (окно 50 мс, оранж.) и пик (синий), dBFS", "RMS (50 ms window, orange) and peak (blue), dBFS"), font=f_s, fill=(220, 230, 245))

    # --- корреляция L/R (окна 100 мс)
    y1 = y0 + H_RMS + 14
    d.rectangle([ML, y1, ML + PW, y1 + H_COR], outline=(80, 96, 120), fill=(12, 18, 32))
    cw = int(0.1 * sr)
    nc = len(mono) // cw
    pts_c = []
    for i in range(nc):
        a = x[0, i * cw:(i + 1) * cw]
        b = x[1, i * cw:(i + 1) * cw]
        c = corr(a, b)
        if math.isnan(c) or max(np.abs(a).max(), np.abs(b).max()) < 10 ** (-70 / 20):
            continue
        pts_c.append((ML + (i + 0.5) * cw / len(mono) * PW, y1 + H_COR * (1 - (c + 1) / 2)))
    for lvl, lab in ((1, "+1"), (0, "0"), (-1, "-1")):
        y = y1 + H_COR * (1 - (lvl + 1) / 2)
        d.line([ML, y, ML + PW, y], fill=(40, 52, 74))
        d.text((ML - 8, y - 7), lab, font=f_s, fill=(170, 185, 210), anchor="ra")
    if len(pts_c) > 1:
        d.line(pts_c, fill=(0, 200, 255), width=2)
    d.text((ML + 6, y1 + 4), L("корреляция L/R (+1 = моно, 0 = широко)", "L/R correlation (+1 = mono, 0 = wide)"), font=f_s, fill=(220, 230, 245))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, optimize=True)
    print(f"\nспектрограмма: {path}  ({img.size[0]}x{img.size[1]})")


def main():
    x, sr, n = read_wav24(WAV)
    print(f"{WAV}\n  sr={sr}  samples={n}  длительность={n / sr:.6f} с  канал-пиков: L {dbfs(np.abs(x[0]).max()):.2f} / R {dbfs(np.abs(x[1]).max()):.2f} dBFS")
    metrics(x, sr)
    momentary_table(x, sr)
    render_png(x, sr, PNG)


if __name__ == "__main__":
    main()
