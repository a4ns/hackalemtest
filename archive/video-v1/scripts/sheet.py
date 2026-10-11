# contact sheet: python3 scripts/sheet.py out.png cols thumbW file1 file2 ...
import sys
from PIL import Image, ImageDraw
out, cols, tw = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
fs = sys.argv[4:]
th = tw * 9 // 16
rows = (len(fs) + cols - 1) // cols
sheet = Image.new("RGB", (tw * cols, th * rows))
d = ImageDraw.Draw(sheet)
for i, f in enumerate(fs):
    im = Image.open(f).convert("RGB").resize((tw, th), Image.LANCZOS)
    sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    d.text(((i % cols) * tw + 8, (i // cols) * th + th - 18), f.split("/")[-1][1:-4], fill=(255, 255, 255))
sheet.save(out)
