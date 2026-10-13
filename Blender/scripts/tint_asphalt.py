"""Recolour a grey aggregate-pavement texture to the Hanoi look of Ref/asphalt.jpg (sunlit part):
pale warm beige binder, small blue-grey stones.

    python Blender/scripts/tint_asphalt.py [src.png] [--binder d7cab8] [--stone 5f6668]

The grey source keeps its own detail; only its brightness is remapped through a colour ramp
(luminance -> colour) with a separate blue-green paint for the stones.
Writes Textures/src/gemini/asphalt.png (picked up by build_ground_textures.py) and keeps the
untouched source next to it as asphalt_gray_src.png.
"""
import argparse, os, shutil
import numpy as np
from PIL import Image

ROOT = r"D:\Project III\BuildingGenerate"
DEFAULT_SRC = r"C:\Users\Admin\Downloads\Seamless Gray Aggregate Pavement Texture.png"
OUT_DIR = os.path.join(ROOT, "Textures", "src", "gemini")


def rgb(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def smooth(x, lo, hi):
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def recolour(lum, binder, stone, binder_l, stone_l):
    """Binder: luminance ramp around `binder`. Stones: separate soft mask, painted blue-green
    (dark core -> `stone` tint) so they keep the saturated colour of the reference instead of
    fading to grey when blended with the pale binder."""
    xs = np.array([binder_l - 40, binder_l - 18, binder_l, binder_l + 16, binder_l + 70], np.float32)
    cols = np.stack([binder * 0.80, binder * 0.90, binder, binder * 1.04 + 6, np.array([238, 232, 220], np.float32)])
    cols = np.clip(cols, 0, 255)
    bcol = np.stack([np.interp(lum, xs, cols[:, c]) for c in range(3)], axis=2)
    mask = 1.0 - smooth(lum, stone_l + 10, binder_l - 4)          # 1 = stone, 0 = binder
    t = smooth(lum, stone_l - 38, stone_l + 36)[..., None]        # darkest -> brightest stone
    scol = stone * (0.55 + 0.75 * t)
    return bcol * (1 - mask[..., None]) + scol * mask[..., None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src', nargs='?', default=DEFAULT_SRC)
    ap.add_argument('--binder', default='d7cab8')
    ap.add_argument('--stone', default='4c6876', help='mid tint of the stones (blue-green slate)')
    a = ap.parse_args()

    im = Image.open(a.src).convert('RGB')
    lum = np.asarray(im, np.float32).mean(2)
    binder_l = float(np.median(lum))
    stone_l = float(np.percentile(lum, 8))
    out = recolour(lum, rgb(a.binder), rgb(a.stone), binder_l, stone_l)
    os.makedirs(OUT_DIR, exist_ok=True)
    keep = os.path.join(OUT_DIR, 'asphalt_gray_src.png')
    if not os.path.exists(keep):
        shutil.copy(a.src, keep)
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), 'RGB').save(os.path.join(OUT_DIR, 'asphalt.png'))
    print(f"[tint] binder L {binder_l:.0f} -> #{a.binder}, stone L {stone_l:.0f} -> #{a.stone} -> asphalt.png")


if __name__ == '__main__':
    main()
