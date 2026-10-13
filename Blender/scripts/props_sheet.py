"""PROPS preview sheet: the refs + the renders of build_props.py --preview in one image.

Plain Python 3.12:  python Blender/scripts/props_sheet.py [tag]      (tag default p1)
Reads Blender/previews/props_<tag>/*.png, writes Blender/previews/props_<tag>_sheet.png.
"""
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = r"D:\Project III\BuildingGenerate"
TAG = sys.argv[1] if len(sys.argv) > 1 else 'p1'
SRC = os.path.join(ROOT, "Blender", "previews", f"props_{TAG}")
OUT = os.path.join(ROOT, "Blender", "previews", f"props_{TAG}_sheet.png")
PANELS = [("Ref/cotdien1.webp", "ref cột điện"), ("Ref/bienbaongo.webp", "ref biển ngõ"),
          ("street.png", "vỉa hè, mắt người 11 m"), ("pole_full.png", "cột điện 8.5 m"),
          ("pole_base.png", "chân cột: sọc sơn bong, giấy dán"), ("pole_box.png", "hộp vàng nhạt + đai"),
          ("sign_full.png", "biển ngõ 3 m"), ("sign_plate.png", "mặt trước"), ("sign_back.png", "mặt sau")]


def main():
    panels = []
    for name, title in PANELS:
        p = os.path.join(ROOT, name) if name.startswith("Ref/") else os.path.join(SRC, name)
        if os.path.exists(p):
            panels.append((title, np.asarray(Image.open(p).convert('RGB'))))
    cols = 3
    nrow = (len(panels) + cols - 1) // cols
    fig = plt.figure(figsize=(cols * 5.5, nrow * 4.8), dpi=110)
    for i, (title, im) in enumerate(panels):
        ax = fig.add_subplot(nrow, cols, i + 1)
        ax.imshow(im)
        ax.set_title(title, fontsize=10); ax.axis('off')
    fig.tight_layout()
    fig.savefig(OUT)
    print('sheet', OUT)


if __name__ == '__main__':
    main()
