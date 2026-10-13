"""MOTO preview sheet: compose the renders of build_moto.py --preview into one image.

Plain Python 3.12:  python Blender/scripts/moto_sheet.py [tag]      (tag default x2)
Reads Blender/previews/moto_<tag>/*.png, writes Blender/previews/moto_<tag>_sheet.png.
The side render is pixel-aligned with Ref/xemay.png, so it is overlaid on the photo.
"""
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np

ROOT = r"D:\Project III\BuildingGenerate"
TAG = sys.argv[1] if len(sys.argv) > 1 else 'x2'
SRC = os.path.join(ROOT, "Blender", "previews", f"moto_{TAG}")
OUT = os.path.join(ROOT, "Blender", "previews", f"moto_{TAG}_sheet.png")
REF = os.path.join(ROOT, "Ref", "xemay.png")


def load(name):
    p = os.path.join(SRC, name)
    return mpimg.imread(p) if os.path.exists(p) else None


def on_white(rgba):
    a = rgba[..., 3:4]
    return rgba[..., :3] * a + (1 - a)


def main():
    ref = mpimg.imread(REF)
    side = load('side.png')
    panels = []
    panels.append(('ảnh gốc', on_white(ref)))
    if side is not None:
        panels.append(('render ngang (ortho)', on_white(side)))
        # outline compare: photo silhouette red, render silhouette cyan, overlap grey
        a_ref, a_r = ref[..., 3] > 0.5, side[..., 3] > 0.5
        cmp_ = np.ones(a_ref.shape + (3,))
        cmp_[a_ref & ~a_r] = (0.9, 0.2, 0.2)
        cmp_[a_r & ~a_ref] = (0.1, 0.7, 0.9)
        cmp_[a_r & a_ref] = (0.75, 0.75, 0.75)
        iou = (a_ref & a_r).sum() / max((a_ref | a_r).sum(), 1)
        panels.append((f'đỏ = chỉ ảnh, xanh = chỉ render (IoU {iou:.2f})', cmp_))
        blend = 0.5 * on_white(ref) + 0.5 * on_white(side)
        panels.append(('chồng 50/50', blend))
    top_ref = os.path.join(ROOT, "Ref", "xemay4.jpg")
    if os.path.exists(top_ref) and load('top.png') is not None:
        panels.append(('ảnh từ trên (xemay4, xe 1)', mpimg.imread(top_ref)[60:247, 30:140] / 255.0))
    for name, title in (('top.png', 'render từ trên'), ('q34_front.png', '3/4 trước-phải'),
                        ('q34_rear.png', '3/4 sau-trái'), ('front.png', 'chính diện')):
        im = load(name)
        if im is not None:
            panels.append((title, im[..., :3]))
    for dist in (20, 50):
        im = load(f'far{dist}.png')
        if im is not None:
            k = 8 if dist == 50 else 4
            big = np.repeat(np.repeat(im[..., :3], k, 0), k, 1)
            panels.append((f'{dist} m, 1080p 60°: {im.shape[1]}x{im.shape[0]} px (phóng x{k})', big))
    row = load('row.png')

    cols = 4
    nrow = (len(panels) + cols - 1) // cols + (1 if row is not None else 0)
    fig = plt.figure(figsize=(cols * 5, nrow * 4.2), dpi=110)
    for i, (title, im) in enumerate(panels):
        ax = fig.add_subplot(nrow, cols, i + 1)
        ax.imshow(np.clip(im, 0, 1), interpolation='nearest')
        ax.set_title(title, fontsize=9); ax.axis('off')
    if row is not None:
        ax = fig.add_subplot(nrow, 1, nrow)
        ax.imshow(row[..., :3]); ax.set_title('10 xe đỗ, đổi màu theo slot PAINT', fontsize=9)
        ax.axis('off')
    fig.tight_layout()
    fig.savefig(OUT)
    print('sheet', OUT)


if __name__ == '__main__':
    main()
