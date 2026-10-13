"""PROPS texture atlas (2048 x 2048) for the street props: power pole + "NGÕ" alley sign.
Plain Python 3.12 (numpy, PIL):
    python Blender/scripts/build_props_texture.py

Sources (CC0, ambientCG, Textures/src/cc0/props/<id>/): Concrete035 (weathered concrete pole),
PaintedMetal012 (chipped white paint: its paint / chip mask drives every painted surface),
Metal021 (rusty steel: sign pipe and what shows through the chips). Everything is aged on purpose:
grime at the foot, rain streaks, rust drips under the box, torn paper scraps on the pole.

Layout (pixels, top-left origin; atlas.json stores UV boxes u0, v0, u1, v1 with v up):
    POLE      x 0-512,     y 0-2048     power pole, u = around (u 0.75 faces -Y), v = height 0..8.5 m
                                         red/white bands on the bottom 1.5 m
    SIGNPOLE  x 512-640,   y 0-2048     sign pipe, u = around, v = height 0..3.0 m, red/white bands
    BOX       x 640-1152,  y 0-512      pale yellow box front (0.42 x 0.56 m), sides reuse it
    METAL     x 1152-1280, y 0-128      galvanised steel (straps, brackets, plate edges)
    SIGN      x 1024-2048, y 1024-1536  blue alley plate, white frame, "NGÕ"
Outputs Blender/props/T_StreetProps.png (sRGB albedo), T_StreetPropsData.png (R roughness,
G metallic), T_StreetProps_N.png (OpenGL normal) and atlas.json (read by hanoi_props.py).
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = r"D:\Project III\BuildingGenerate"
SRC = os.path.join(ROOT, "Textures", "src", "cc0", "props")
OUT = os.path.join(ROOT, "Blender", "props")
N = 2048
FONT = r"C:\Windows\Fonts\ARIALNB.TTF"

POLE_H = 8.5              # m, height covered by the POLE strip
SIGNPOLE_H = 3.0
POLE_CIRC = 2 * np.pi * 0.17      # base circumference (the strip wraps once around)
SIGNPOLE_CIRC = 2 * np.pi * 0.032
BANDS_POLE = 0.3          # m per band, 5 bands from the ground: red white red white red
BANDS_SIGN = 0.4          # m per band, whole sign pipe, red at the ground
BOX_Z = (3.32, 3.88)      # box bottom / top on the pole (hanoi_props uses the same numbers)

REGIONS_PX = {
    'POLE':     (0, 0, 512, 2048),
    'SIGNPOLE': (512, 0, 640, 2048),
    'BOX':      (640, 0, 1152, 512),
    'METAL':    (1152, 0, 1280, 128),
    'SIGN':     (1024, 1024, 2048, 1536),
}
RED = np.array([150, 38, 32]) / 255
WHITE = np.array([214, 208, 196]) / 255
PALE_YELLOW = np.array([220, 204, 142]) / 255
SIGN_BLUE = np.array([24, 78, 176]) / 255

rng = np.random.default_rng(7)


# ---------------------------------------------------------------- helpers
def src(asset, kind):
    return os.path.join(SRC, asset, f"{asset}_1K-JPG_{kind}.jpg")


def load(path, w, h):
    """Seamless source resized to one tile of w x h px (stays seamless)."""
    return np.asarray(Image.open(path).convert('RGB').resize((w, h), Image.BICUBIC)) / 255.0


def tile_to(img, w, h):
    reps = (int(np.ceil(h / img.shape[0])), int(np.ceil(w / img.shape[1])), 1)
    return np.tile(img, reps)[:h, :w]


def blur(a, r):
    im = Image.fromarray(np.uint8(np.clip(a, 0, 1) * 255))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r))) / 255.0


def noise(h, w, r, stretch=1, wrap=True):
    """Smooth noise 0..1 (h x w); stretch > 1 elongates it vertically (rain streaks); wrap = periodic
    in x (around the pole)."""
    hh = max(4, int(h / stretch))
    base = rng.random((hh, w))
    if wrap:
        base = np.tile(base, (1, 3))
    a = blur(base, r)
    if wrap:
        a = a[:, w:2 * w]
    a = np.asarray(Image.fromarray(np.uint8(a * 255)).resize((w, h), Image.BICUBIC)) / 255.0
    a = (a - a.min()) / max(a.max() - a.min(), 1e-6)
    return a


def lum(img):
    return img @ np.array([0.299, 0.587, 0.114])


def chip_mask(paint_src, coverage):
    """1 = paint, 0 = chipped, from PaintedMetal012 (bright, unsaturated = paint). coverage = chipped
    fraction wanted."""
    l = lum(paint_src)
    sat = paint_src.max(-1) - paint_src.min(-1)
    score = l - 1.5 * sat
    thr = np.quantile(score, coverage)
    return np.clip((score - thr) / 0.04 + 0.5, 0, 1)


def paint_shade(paint_src):
    """Brightness variation of the painted parts (around 1.0)."""
    l = lum(paint_src)
    return 0.85 + 0.3 * (l - l.mean()) / max(l.std() * 3, 1e-6) + 0.15


def heights(h, total):
    """z (m) of each row of a strip h px high covering 0..total (row 0 = top)."""
    return (h - 1 - np.arange(h) + 0.5) / h * total


def normal_blend(n, k):
    """Scale a normal map's tangent part by k (0 = flat)."""
    v = n * 2 - 1
    v[..., :2] *= k[..., None] if np.ndim(k) else k
    v /= np.linalg.norm(v, axis=-1, keepdims=True)
    return v * 0.5 + 0.5


# ---------------------------------------------------------------- regions
def pole():
    x0, y0, x1, y1 = REGIONS_PX['POLE']
    w, h = x1 - x0, y1 - y0
    tile_h = max(64, int(round(POLE_CIRC / (POLE_H / h))))      # one texture tile = one turn: square texels
    conc = tile_to(load(src('Concrete035', 'Color'), w, tile_h), w, h)
    nrm = tile_to(load(src('Concrete035', 'NormalGL'), w, tile_h), w, h)
    pnt = tile_to(load(src('PaintedMetal012', 'Color'), w, tile_h), w, h)
    z = heights(h, POLE_H)[:, None]
    u = (np.arange(w)[None, :] + 0.5) / w

    # concrete, a bit warmer and lighter than the photo, large patches
    alb = conc * np.array([1.04, 1.02, 0.97]) * 1.05
    alb *= (0.9 + 0.2 * noise(h, w, 30))[..., None]
    # paint bands with hand-painted wobbly edges and chips showing the concrete
    edge = (noise(1, w, 12)[0] - 0.5) * 0.03
    band = np.floor((z - edge[None, :]) / BANDS_POLE)
    painted = (z - edge[None, :] < 5 * BANDS_POLE) & (band >= 0)
    col = np.where((band % 2 == 0)[..., None], RED, WHITE)
    chips = chip_mask(pnt, 0.18) * painted
    pcol = col * np.clip(paint_shade(pnt), 0.7, 1.15)[..., None]
    alb = alb * (1 - chips[..., None]) + pcol * chips[..., None]
    # grime: dark foot + splashes, rain streaks, rust drips under the box (front, u ~ 0.75)
    foot = np.exp(-z / 0.45) * (0.6 + 0.4 * noise(h, w, 3))
    streak = noise(h, w, 2.5, stretch=24)
    rain = np.clip((streak - 0.55) * 2.0, 0, 1) * 0.22
    du = np.minimum(np.abs(u - 0.75), 1 - np.abs(u - 0.75))
    drip = (np.exp(-(du / 0.06) ** 2) * (z < BOX_Z[0]) * np.clip(1 - (BOX_Z[0] - z) / 1.6, 0, 1)
            * np.clip((noise(h, w, 1.5, stretch=30) - 0.35) * 2, 0, 1))
    rust = np.array([0.42, 0.24, 0.12])
    alb = alb * (1 - 0.55 * foot[..., None]) * (1 - rain[..., None])
    alb = alb * (1 - 0.3 * foot[..., None]) + np.array([0.33, 0.28, 0.22]) * 0.3 * foot[..., None]
    alb = alb * (1 - 0.55 * drip[..., None]) + rust * 0.55 * drip[..., None]
    top = np.clip((z - (POLE_H - 0.8)) / 0.8, 0, 1) * 0.25          # soot near the top
    alb *= (1 - top)[..., None]
    rough = 0.92 - 0.2 * chips
    nk = 1.0 - 0.6 * chips
    alb, rough, nk = paper_scraps(alb, rough, nk, z, u)
    return alb, rough, np.zeros_like(rough), normal_blend(nrm, nk)


def paper_scraps(alb, rough, nk, z, u):
    """Torn, faded flyers glued on the pole at hand height (the 'khoan cắt bê tông' kind), text
    only suggested by grey bars."""
    h, w = rough.shape
    zs = z[:, 0]
    for _ in range(7):
        zc = rng.uniform(1.75, 3.0)
        uc = rng.uniform(0.18, 0.82)
        hz, wu = rng.uniform(0.18, 0.40), rng.uniform(0.12, 0.26)
        rows = np.where(np.abs(zs - zc) < hz / 2)[0]
        cols = np.where(np.abs(u[0] - uc) < wu / 2)[0]
        if len(rows) < 4 or len(cols) < 4:
            continue
        sub = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
        sh = (len(rows), len(cols))
        tear = noise(*sh, 2, wrap=False)
        yy, xx = np.meshgrid(np.linspace(-1, 1, sh[0]), np.linspace(-1, 1, sh[1]), indexing='ij')
        shape = np.clip((1 - np.maximum(np.abs(yy), np.abs(xx))) * 4 + (tear - 0.5) * 3, 0, 1)
        shape *= rng.uniform(0.5, 0.9) * (tear > rng.uniform(0.15, 0.45))        # mostly torn off
        paper = np.array([0.86, 0.83, 0.72]) * rng.uniform(0.75, 1.0)
        if rng.random() < 0.3:
            paper = np.array([0.80, 0.74, 0.52])                                   # yellowed
        layer = np.ones(sh + (3,)) * paper
        lines = (np.sin(yy * rng.integers(3, 7) * np.pi) > 0.7) & (np.abs(xx) < 0.7)
        lines &= noise(*sh, 1.5, wrap=False) > 0.45
        layer[lines] *= 0.6
        layer *= (0.85 + 0.15 * tear)[..., None]
        a = shape[..., None]
        alb[sub] = alb[sub] * (1 - a) + layer * a
        rough[sub] = rough[sub] * (1 - shape) + 0.97 * shape
        nk[sub] = nk[sub] * (1 - shape) + 0.15 * shape
    return alb, rough, nk


def signpole():
    x0, y0, x1, y1 = REGIONS_PX['SIGNPOLE']
    w, h = x1 - x0, y1 - y0
    tile_h = max(32, int(round(SIGNPOLE_CIRC / (SIGNPOLE_H / h))))
    steel = tile_to(load(src('Metal021', 'Color'), w, tile_h), w, h)
    nrm = tile_to(load(src('PaintedMetal012', 'NormalGL'), w, tile_h), w, h)
    pnt = tile_to(load(src('PaintedMetal012', 'Color'), w, tile_h), w, h)
    z = heights(h, SIGNPOLE_H)[:, None]
    band = np.floor(z / BANDS_SIGN)
    col = np.where((band % 2 == 0)[..., None], RED, WHITE)
    col = np.where((z > SIGNPOLE_H - 0.05)[..., None], WHITE, col)
    chips = chip_mask(pnt, 0.10)
    alb = steel * (1 - chips[..., None]) + col * np.clip(paint_shade(pnt), 0.75, 1.1)[..., None] * chips[..., None]
    foot = np.exp(-z / 0.2) * (0.5 + 0.5 * noise(h, w, 2))
    rain = np.clip((noise(h, w, 1.5, stretch=20) - 0.6) * 2, 0, 1) * 0.18
    alb = alb * (1 - 0.5 * foot[..., None]) * (1 - rain[..., None])
    rough = 0.55 + 0.3 * (1 - chips)
    metal = 0.6 * (1 - chips)
    return alb, rough, metal, normal_blend(nrm, 0.5 + 0.5 * (1 - chips))


def box():
    x0, y0, x1, y1 = REGIONS_PX['BOX']
    w, h = x1 - x0, y1 - y0
    pnt = load(src('PaintedMetal012', 'Color'), w, h)
    steel = load(src('Metal021', 'Color'), w, h)
    nrm = load(src('PaintedMetal012', 'NormalGL'), w, h)
    chips = chip_mask(pnt, 0.07)
    alb = steel * (1 - chips[..., None]) + PALE_YELLOW * np.clip(paint_shade(pnt), 0.8, 1.1)[..., None] * chips[..., None]
    yy = np.linspace(0, 1, h)[:, None]                 # 0 = top of the box
    rain = np.clip((noise(h, w, 2, stretch=16, wrap=False) - 0.5) * 2, 0, 1) * (0.15 + 0.2 * yy)
    alb *= (1 - rain[..., None]) * (1 - 0.18 * yy[..., None] ** 2)
    im = Image.fromarray(np.uint8(np.clip(alb, 0, 1) * 255))
    d = ImageDraw.Draw(im)
    m = 22
    d.rectangle((m, m, w - m, h - m), outline=(78, 70, 48), width=3)          # door seam
    d.rectangle((w - m - 34, h // 2 - 26, w - m - 16, h // 2 + 26), fill=(60, 58, 52))   # lock
    d.ellipse((w - m - 30, h // 2 - 6, w - m - 20, h // 2 + 4), fill=(140, 138, 128))
    for yh in (90, h - 90):                                                    # hinges (left)
        d.rectangle((m - 10, yh - 18, m + 4, yh + 18), fill=(84, 80, 70))
    cx, cy, s = w // 2, 96, 46                                                 # faded danger sticker
    d.polygon([(cx, cy - s), (cx - s, cy + s * 0.75), (cx + s, cy + s * 0.75)], fill=(208, 170, 40),
              outline=(30, 28, 26))
    d.polygon([(cx + 6, cy - 22), (cx - 12, cy + 8), (cx, cy + 8), (cx - 8, cy + 30), (cx + 14, cy - 2),
               (cx + 2, cy - 2), (cx + 10, cy - 22)], fill=(30, 28, 26))
    alb = np.asarray(im) / 255.0
    rough = 0.6 + 0.3 * (1 - chips)
    return alb, rough, 0.3 * (1 - chips), normal_blend(nrm, 0.6)


def metal():
    x0, y0, x1, y1 = REGIONS_PX['METAL']
    w, h = x1 - x0, y1 - y0
    steel = load(src('Metal021', 'Color'), w, h)
    alb = 0.6 * steel + 0.4 * np.array([0.55, 0.56, 0.55])
    return alb, np.full((h, w), 0.55), np.full((h, w), 0.8), np.full((h, w, 3), [0.5, 0.5, 1.0])


def sign():
    x0, y0, x1, y1 = REGIONS_PX['SIGN']
    w, h = x1 - x0, y1 - y0
    im = Image.new('RGB', (w, h), tuple(int(c * 255) for c in SIGN_BLUE))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((22, 22, w - 22, h - 22), radius=34, outline=(242, 244, 246), width=11)
    font = ImageFont.truetype(FONT, 300)
    text = "NGÕ"
    bb = d.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((w - tw) / 2 - bb[0], (h - th) / 2 - bb[1] + 8), text, font=font, fill=(244, 246, 248))
    alb = np.asarray(im) / 255.0
    # ageing: sun fade, dust towards the bottom, rain streaks, a few scratches and chips
    pnt = load(src('PaintedMetal012', 'Color'), w, w)[:h]
    alb = alb * 0.9 + np.array([0.62, 0.64, 0.66]) * 0.1
    yy = np.linspace(0, 1, h)[:, None]
    dust = (0.35 + 0.65 * yy) * noise(h, w, 18, wrap=False)
    alb = alb * (1 - 0.18 * dust[..., None]) + np.array([0.55, 0.5, 0.42]) * 0.12 * dust[..., None]
    rain = np.clip((noise(h, w, 2, stretch=18, wrap=False) - 0.55) * 2, 0, 1) * 0.15
    alb *= (1 - rain[..., None])
    chips = 1 - chip_mask(pnt, 0.025)
    alb = alb * (1 - chips[..., None]) + np.array([0.62, 0.62, 0.6]) * chips[..., None]
    sc = Image.new('L', (w, h), 0)
    ds = ImageDraw.Draw(sc)
    for _ in range(14):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        a, L = rng.uniform(-0.5, 0.5), rng.uniform(20, 90)
        ds.line((x, y, x + L * np.cos(a), y + L * np.sin(a)), fill=int(rng.uniform(60, 140)), width=1)
    s = np.asarray(sc)[..., None] / 255.0
    alb = alb * (1 - s) + 0.8 * s
    rough = 0.45 + 0.4 * chips + 0.2 * dust
    return alb, rough, np.zeros((h, w)), np.full((h, w, 3), [0.5, 0.5, 1.0])


# ---------------------------------------------------------------- main
def main():
    alb = np.zeros((N, N, 3)); alb[:] = 0.5
    dat = np.zeros((N, N, 3)); dat[..., 0] = 0.8
    nrm = np.zeros((N, N, 3)); nrm[:] = (0.5, 0.5, 1.0)
    for name, fn in (('POLE', pole), ('SIGNPOLE', signpole), ('BOX', box), ('METAL', metal), ('SIGN', sign)):
        x0, y0, x1, y1 = REGIONS_PX[name]
        a, r, m, n = fn()
        alb[y0:y1, x0:x1] = a
        dat[y0:y1, x0:x1, 0] = r
        dat[y0:y1, x0:x1, 1] = m
        nrm[y0:y1, x0:x1] = n
        print('region', name, a.shape[1], 'x', a.shape[0])
    os.makedirs(OUT, exist_ok=True)
    for arr, fname in ((alb, 'T_StreetProps.png'), (dat, 'T_StreetPropsData.png'), (nrm, 'T_StreetProps_N.png')):
        Image.fromarray(np.uint8(np.clip(arr, 0, 1) * 255 + 0.5)).save(os.path.join(OUT, fname))
    regions = {k: (x0 / N, 1 - y1 / N, x1 / N, 1 - y0 / N) for k, (x0, y0, x1, y1) in REGIONS_PX.items()}
    json.dump({'size': N, 'regions': regions, 'pole_h': POLE_H, 'signpole_h': SIGNPOLE_H, 'box_z': BOX_Z,
               'sources': ['ambientCG Concrete035', 'ambientCG PaintedMetal012', 'ambientCG Metal021 (CC0)']},
              open(os.path.join(OUT, 'atlas.json'), 'w'), indent=1)
    print('atlas written ->', OUT)


if __name__ == '__main__':
    main()
