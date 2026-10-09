"""Automated QC of the exported MP4 (the real file, not the source).
Usage: python3 scripts/qc.py renders/hackalem-intro.mp4 [renders/hackalem-intro-silent.mp4]
Checks: streams/duration, loudness + true peak + clipping of the muxed audio, first/last samples,
black/frozen frames, A/V sync of the main hit (white flash frame vs audio transient), silent-file video identity.
"""
import json, re, subprocess, sys
import numpy as np

src = sys.argv[1]
silent = sys.argv[2] if len(sys.argv) > 2 else None
FPS = 30
HIT = 9.6


def run(args):
    return subprocess.run(args, capture_output=True, text=True)


def ffprobe(path):
    r = run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path])
    return json.loads(r.stdout)


print("== streams ==")
info = ffprobe(src)
for s in info["streams"]:
    if s["codec_type"] == "video":
        print(f"video: {s['codec_name']} {s['profile']} {s['width']}x{s['height']} {s['pix_fmt']} {s['r_frame_rate']} "
              f"frames={s.get('nb_frames')} dur={s.get('duration')} {s.get('color_space')}/{s.get('color_transfer')} "
              f"br={int(s.get('bit_rate', 0)) / 1e6:.1f} Mbit/s")
    else:
        print(f"audio: {s['codec_name']} {s['sample_rate']} Hz {s['channels']}ch dur={s.get('duration')} br={int(s.get('bit_rate', 0)) / 1e3:.0f} kbit/s")
print("container duration:", info["format"]["duration"], "size MB:", round(int(info["format"]["size"]) / 1e6, 2))

print("\n== loudness (muxed audio) ==")
r = run(["ffmpeg", "-v", "info", "-i", src, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"])
tail = r.stderr[r.stderr.rfind("Summary:"):]
for k in ("I:", "LRA:", "Peak:"):
    m = re.search(rf"^\s*{re.escape(k)}\s+(-?[\d.]+)", tail, re.M)
    print(k, m.group(1) if m else "n/a")

raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-f", "f32le", "-ac", "2", "-ar", "48000", "-"], capture_output=True).stdout
a = np.frombuffer(raw, np.float32).reshape(-1, 2)
print(f"samples: {len(a)} ({len(a) / 48000:.3f} s)  sample peak: {20 * np.log10(np.abs(a).max() + 1e-12):.2f} dBFS  clipped(>=0.999): {(np.abs(a) >= 0.999).sum()}")
print("first 10 ms peak:", round(float(np.abs(a[:480]).max()), 4), " last 10 ms peak:", round(float(np.abs(a[-480:]).max()), 6))
mono = a.mean(axis=1)
# the impact is a sub-bass boom (D1 glide); the reverse swell before it has no energy below 150 Hz
spec = np.fft.rfft(mono)
freqs = np.fft.rfftfreq(len(mono), 1 / 48000)
spec[freqs > 150] = 0
sub = np.abs(np.fft.irfft(spec, len(mono)))
w0, w1 = int((HIT - 0.15) * 48000), int((HIT + 0.4) * 48000)
thr = 0.35 * sub[w0:w1].max()
onset = (np.argmax(sub[w0:w1] > thr) + w0) / 48000
print(f"main impact onset (sub-bass <150 Hz, 35% of window peak): {onset:.4f} s (expected {HIT})")
import os
WAV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "audio", "hackalem-intro-mix.wav")
if os.path.exists(WAV):
    ref = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", WAV, "-f", "f32le", "-ac", "2", "-ar", "48000", "-"], capture_output=True).stdout, np.float32).reshape(-1, 2)
    sl = slice(int(8.0 * 48000), int(11.0 * 48000))
    x, y = ref[sl, 0], a[sl, 0]
    lag = int(np.argmax(np.correlate(y - y.mean(), x - x.mean(), "full")) - (len(x) - 1))
    gain = 20 * np.log10(np.sqrt((y ** 2).mean()) / np.sqrt((x ** 2).mean()))
    print(f"muxed audio vs source WAV: lag {lag} samples ({lag / 48:.2f} ms), gain {gain:+.2f} dB (renderer's AAC true-peak correction)")
secs = [20 * np.log10(np.sqrt((a[int(i * 48000):int((i + 1) * 48000)] ** 2).mean()) + 1e-9) for i in range(15)]
print("RMS dBFS per second:", " ".join(f"{v:5.1f}" for v in secs))

print("\n== picture ==")
w, h = 320, 180
p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
lum, diffs, prev = [], [], None
while True:
    b = p.stdout.read(w * h)
    if len(b) < w * h:
        break
    f = np.frombuffer(b, np.uint8).astype(np.float32)
    lum.append(f.mean())
    if prev is not None:
        diffs.append(np.abs(f - prev).mean())
    prev = f
lum = np.array(lum)
print("frames decoded:", len(lum))
print("black frames (mean luma<6):", np.where(lum < 6)[0].tolist())
flash = int(np.argmax(lum))
print(f"brightest frame: {flash} (t={flash / FPS:.3f} s, luma {lum[flash]:.0f}); expected {int(HIT * FPS)}")
d = np.array(diffs)
runs, st = [], None
for k in range(len(d)):
    if d[k] < 0.02 and st is None:
        st = k
    if (d[k] >= 0.02 or k == len(d) - 1) and st is not None:
        if k - st >= 6:
            runs.append((round((st + 1) / FPS, 2), round(k / FPS, 2)))
        st = None
print("frozen runs (>=6 frames):", runs)
print(f"A/V sync of the hit: video flash frame {flash / FPS:.4f} s vs audio onset {onset:.4f} s -> delta {(onset - flash / FPS) * 1000:.1f} ms")

if silent:
    print("\n== silent file ==")
    si = ffprobe(silent)
    print("streams:", [s["codec_type"] for s in si["streams"]])
    hv = lambda path: subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"], capture_output=True, text=True).stdout.strip()
    print("video stream md5 final :", hv(src))
    print("video stream md5 silent:", hv(silent))
