"""Motion profile of a rendered MP4: mean abs frame difference per frame (480x270 luma), printed per 0.25 s.
Usage: python3 scripts/motion_profile.py renders/hackalem-intro.mp4"""
import subprocess, sys
import numpy as np
src = sys.argv[1]
w, h = 480, 270
p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
prev, diffs = None, []
while True:
    b = p.stdout.read(w * h)
    if len(b) < w * h: break
    f = np.frombuffer(b, np.uint8).astype(np.float32)
    if prev is not None: diffs.append(float(np.abs(f - prev).mean()))
    prev = f
d = np.array(diffs)
print(f"{len(d)+1} frames")
for i in range(0, len(d), 8):  # 8 frames ~ 0.267 s
    seg = d[i:i + 8]
    bar = "#" * int(min(60, seg.mean() * 4))
    print(f"{(i+1)/30:6.2f}s  mean {seg.mean():6.2f}  max {seg.max():6.2f}  {bar}")
still = np.where(d < 0.05)[0]
runs, start = [], None
for k in range(len(d)):
    if d[k] < 0.05 and start is None: start = k
    if (d[k] >= 0.05 or k == len(d) - 1) and start is not None:
        if k - start >= 6: runs.append((start + 1, k))
        start = None
print("near-static runs (>=6 frames, diff<0.05):", [(round(a/30,2), round(b/30,2)) for a, b in runs])
