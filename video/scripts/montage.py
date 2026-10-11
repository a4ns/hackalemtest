import sys, glob, os
from PIL import Image, ImageDraw
d, out, cols, w = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
files = sorted(glob.glob(os.path.join(d, "t*.png")))
ims = [Image.open(f).convert("RGB") for f in files]
h = int(w * 9 / 16)
rows = (len(ims) + cols - 1) // cols
sheet = Image.new("RGB", (cols * w, rows * h), (0, 0, 0))
for i, (f, im) in enumerate(zip(files, ims)):
    im = im.resize((w, h), Image.LANCZOS)
    dr = ImageDraw.Draw(im); dr.text((8, 6), os.path.basename(f)[1:-4], fill=(255, 220, 0))
    sheet.paste(im, ((i % cols) * w, (i // cols) * h))
sheet.save(out)
print(out, sheet.size)
