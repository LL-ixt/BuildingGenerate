"""CART preview sheet: the two refs + the renders of build_cart.py --preview in one image.

Plain Python 3.12:  python Blender/scripts/cart_sheet.py [tag]      (tag default c1)
Reads Blender/previews/cart_<tag>/*.png, writes Blender/previews/cart_<tag>_sheet.png.
"""
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = r"D:\Project III\BuildingGenerate"
TAG = sys.argv[1] if len(sys.argv) > 1 else 'c1'
SRC = os.path.join(ROOT, "Blender", "previews", f"cart_{TAG}")
OUT = os.path.join(ROOT, "Blender", "previews", f"cart_{TAG}_sheet.png")
REFS = (("Ref/xe rac.jpg", "ref 1 (thùng)"), ("Ref/xe-gom-rac-day-tay-500-lit-inox.webp", "ref 2 (khung, 3 bánh)"))


def load(name):
    p = os.path.join(SRC, name)
    if not os.path.exists(p):
        return None
    im = mpimg.imread(p)
    if im.shape[-1] == 4:                         # transparent renders on white
        a = im[..., 3:4]
        im = im[..., :3] * a + (1 - a)
    return im[..., :3]


def lod_panels():
    """C2: one row per LOD: close 3/4, then what 1080p / 60 deg shows at 8, 20, 50 m (enlarged)."""
    panels = []
    for k in range(3):
        for name, title, zoom in (('q34', '3/4', 1), ('far8', '8 m', 2), ('far20', '20 m', 4),
                                  ('far50', '50 m', 8)):
            im = load(f'lod{k}_{name}.png')
            if im is not None:
                if zoom > 1:
                    title += f': {im.shape[1]}x{im.shape[0]} px (x{zoom})'
                    im = np.repeat(np.repeat(im, zoom, 0), zoom, 1)
                panels.append((f'LOD{k} {title}', im))
    return panels, 4


def main():
    if TAG != 'c1':
        panels, cols = lod_panels()
        return save(panels, cols)
    panels = [(t, np.asarray(Image.open(os.path.join(ROOT, p)).convert('RGB')) / 255.0) for p, t in REFS]
    for name, title in (('ref1_view.png', 'góc nhìn như ref 1'), ('side.png', 'ngang (ortho), như ref 2'),
                        ('q34_rear.png', '3/4 phía tay đẩy'), ('q34_front.png', '3/4 phía trước'),
                        ('back.png', 'từ phía tay đẩy (ortho)'), ('top.png', 'từ trên')):
        im = load(name)
        if im is not None:
            panels.append((title, im))
    far = load('far20.png')
    if far is not None:
        panels.append((f'20 m, 1080p 60°: {far.shape[1]}x{far.shape[0]} px (phóng x4)',
                       np.repeat(np.repeat(far, 4, 0), 4, 1)))
    save(panels, 3)


def save(panels, cols):
    nrow = (len(panels) + cols - 1) // cols
    fig = plt.figure(figsize=(cols * 5.5, nrow * 4.6), dpi=110)
    for i, (title, im) in enumerate(panels):
        ax = fig.add_subplot(nrow, cols, i + 1)
        ax.imshow(np.clip(im, 0, 1), interpolation='nearest')
        ax.set_title(title, fontsize=10); ax.axis('off')
    fig.tight_layout()
    fig.savefig(OUT)
    print('sheet', OUT)


if __name__ == '__main__':
    main()
