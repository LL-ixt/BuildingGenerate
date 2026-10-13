"""TRAIN preview sheet: Ref/train.webp + the renders of build_train.py --preview.

Plain Python 3.12:  python Blender/scripts/train_sheet.py [tag]      (tag default t1)
Reads Blender/previews/train_<tag>/*.png, writes Blender/previews/train_<tag>_sheet.png.
"""
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = r"D:\Project III\BuildingGenerate"
TAG = sys.argv[1] if len(sys.argv) > 1 else 't1'
SRC = os.path.join(ROOT, "Blender", "previews", f"train_{TAG}")
OUT = os.path.join(ROOT, "Blender", "previews", f"train_{TAG}_sheet.png")
PANELS = [("Ref/train.webp", "ref tàu (tuyến 3)"), ("front34.png", "trên cầu, góc giống ref"),
          ("studio_34.png", "đầu tàu 3/4"), ("Ref/overallview.jpeg", "ref tổng quan"),
          ("drone.png", "đoàn 4 toa trên cầu"), ("studio_front.png", "mặt trước (ortho)"),
          ("studio_end_side.png", "toa đầu 20 m"), ("studio_mid_side.png", "toa giữa 19 m"),
          ("studio_under.png", "giá chuyển hướng + bánh")]


def main():
    panels = []
    for name, title in PANELS:
        p = os.path.join(ROOT, name) if name.startswith("Ref/") else os.path.join(SRC, name)
        if os.path.exists(p):
            panels.append((title, np.asarray(Image.open(p).convert('RGB'))))
    cols = 3
    nrow = (len(panels) + cols - 1) // cols
    fig = plt.figure(figsize=(cols * 6.0, nrow * 4.2), dpi=110)
    for i, (title, im) in enumerate(panels):
        ax = fig.add_subplot(nrow, cols, i + 1)
        ax.imshow(im)
        ax.set_title(title, fontsize=10); ax.axis('off')
    fig.tight_layout()
    fig.savefig(OUT)
    print('sheet', OUT)


if __name__ == '__main__':
    main()
