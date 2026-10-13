"""MOTO texture atlas (1024 x 1024) for M_HanoiMoto — plain Python 3.12 (numpy, matplotlib):
    python Blender/scripts/build_moto_atlas.py

Layout (UV, origin bottom-left):
    v 0.875-1      8 slot cells (palette, 128 px each): PAINT PLASTIC SEAT METAL TIRE LIGHT RED RIM
    u 0-0.5, v 0.375-0.875   wheel side, from the front wheel of Ref/xemay.png. The fork and the
                   brake caliper hide parts of it, so one clean 72 deg sector (the rim has 5 twin
                   spokes) is resampled around the full circle, red removed (black/grey only).
                   ALPHA = 0 between the spokes
                   (the photo's own alpha): the rim disc is alpha-clipped, you see through it.
                   Override: if Ref/wheel_src.png exists (square, transparent background, wheel
                   seen exactly from the side, tyre touching the image edges) it is used instead.
    u 0-0.125, v 0-0.375     shock spring (helix of red coils; u = around, v = along)
    u 0.125-0.25, v 0-0.375  tyre tread (one tile per wheel segment; v = around)
Outputs Blender/moto/T_MotoAtlas.png (sRGB albedo + alpha clip mask), T_MotoAtlasData.png (R roughness, G metallic,
B emission) and atlas.json (regions + wheel scale) read by hanoi_moto.py.
"""
import json
import os

import matplotlib.image as mpimg
import numpy as np

ROOT = r"D:\Project III\BuildingGenerate"
SRC = os.path.join(ROOT, "Ref", "xemay.png")
WHEEL_SRC = os.path.join(ROOT, "Ref", "wheel_src.png")     # optional clean wheel (e.g. from Gemini)
OUT = os.path.join(ROOT, "Blender", "moto")
PROFILE = os.path.join(OUT, "sh_profile.json")
N = 1024

SLOTS = ['PAINT', 'PLASTIC', 'SEAT', 'METAL', 'TIRE', 'LIGHT', 'RED', 'RIM']
PALETTE = {   # sRGB albedo, (roughness, metallic, emission)
    'PAINT':   ((235, 235, 235), (0.30, 0.50, 0.0)),      # metallic paint, tinted per bike
    'PLASTIC': ((30, 30, 32),    (0.60, 0.0, 0.0)),
    'SEAT':    ((24, 22, 22),    (0.85, 0.0, 0.0)),
    'METAL':   ((196, 198, 202), (0.25, 1.0, 0.0)),
    'TIRE':    ((20, 20, 20),    (0.90, 0.0, 0.0)),
    'LIGHT':   ((235, 238, 240), (0.05, 0.0, 0.3)),
    'RED':     ((175, 22, 20),   (0.40, 0.0, 0.0)),
    'RIM':     ((38, 38, 40),    (0.40, 0.6, 0.0)),
}
REGIONS = {   # u0, v0, u1, v1
    'palette': (0.0, 0.875, 1.0, 1.0),
    'wheel':   (0.0, 0.375, 0.5, 0.875),
    'spring':  (0.0, 0.0, 0.125, 0.375),
    'tread':   (0.125, 0.0, 0.25, 0.375),
}
SECTOR0, SECTOR = 250.0, 72.0     # clean sector of the front wheel photo (deg, maths angle)
PAD = 4.0                         # px of background around the tyre in the wheel tile
HUB_PX = (804.0, 540.0)           # axle in the photo: perspective puts it off the tyre centre
RIM_FRAC = 0.80                   # rim edge (red stripe) / tyre radius; tyre = angle-averaged
BEHIND = np.array([0.035, 0.035, 0.04])   # colour under the clipped (transparent) texels


def px_rect(region):
    u0, v0, u1, v1 = REGIONS[region]
    return int(round((1 - v1) * N)), int(round((1 - v0) * N)), int(round(u0 * N)), int(round(u1 * N))


def bilinear(img, x, y):
    h, w = img.shape[:2]
    x = np.clip(x, 0, w - 1.001); y = np.clip(y, 0, h - 1.001)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    a, b = img[y0, x0], img[y0, x0 + 1]
    c, d = img[y0 + 1, x0], img[y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def main():
    prof = json.load(open(PROFILE, encoding='utf-8'))
    s = prof['metres_per_px']
    ox, oy = prof['px_origin']
    fu, fz = prof['wheels']['front']['centre']
    cx, cy = ox + fu / s, oy - fz / s
    r = prof['wheels']['front']['radius'] / s
    photo = mpimg.imread(SRC)
    rgb = photo[..., :3] * photo[..., 3:4] + BEHIND * (1 - photo[..., 3:4])

    alb = np.zeros((N, N, 3)); dat = np.zeros((N, N, 3)); alpha = np.ones((N, N))
    dat[..., 0] = 0.8
    rgba = np.concatenate([rgb, photo[..., 3:4]], -1)

    # palette strip
    r0, r1, c0, c1 = px_rect('palette')
    for i, sl in enumerate(SLOTS):
        col, data = PALETTE[sl]
        a, b = c0 + i * (c1 - c0) // 8, c0 + (i + 1) * (c1 - c0) // 8
        alb[r0:r1, a:b] = np.array(col) / 255.0
        dat[r0:r1, a:b] = data

    # wheel tile: polar resample of the clean sector
    r0, r1, c0, c1 = px_rect('wheel')
    size = r1 - r0
    rc = r + PAD
    jj, ii = np.meshgrid(np.arange(size) + 0.5, np.arange(size) + 0.5)
    dx = (jj / size * 2 - 1) * rc
    dy = (1 - ii / size * 2) * rc
    rho = np.hypot(dx, dy)
    th = np.degrees(np.arctan2(dy, dx)) % 360
    th2 = SECTOR0 + (th - SECTOR0) % SECTOR
    # soften the sector seam: blend with the neighbouring copy over 4 deg
    th3 = th2 - SECTOR
    w = smooth(SECTOR - 4, SECTOR, (th - SECTOR0) % SECTOR)[..., None]
    # sampling centre slides from the axle (hub) to the tyre centre (rim edge and beyond)
    k = np.clip(rho / (RIM_FRAC * r), 0, 1)
    ccx = HUB_PX[0] + (cx - HUB_PX[0]) * k
    ccy = HUB_PX[1] + (cy - HUB_PX[1]) * k
    sx = ccx + rho * np.cos(np.radians(th2)); sy = ccy - rho * np.sin(np.radians(th2))
    sx3 = ccx + rho * np.cos(np.radians(th3)); sy3 = ccy - rho * np.sin(np.radians(th3))
    c4 = bilinear(rgba, sx, sy) * (1 - w) + bilinear(rgba, sx3, sy3) * w
    c, a = c4[..., :3], c4[..., 3]
    # tyre ring: average over the sector angles per radius -> no lighting seams
    rb = np.linspace(RIM_FRAC * r, r, 24)
    prof = []
    for rr_ in rb:
        t = np.radians(np.linspace(SECTOR0 + 2, SECTOR0 + SECTOR - 2, 40))
        prof.append(bilinear(rgb, cx + rr_ * np.cos(t), cy - rr_ * np.sin(t)).mean(0))
    prof = np.array(prof)
    ring = np.stack([np.interp(rho, rb, prof[:, ch]) for ch in range(3)], -1)
    tw = smooth(RIM_FRAC * r + 1, RIM_FRAC * r + 3, rho)[..., None]
    c = c * (1 - tw) + ring * tw
    rubber = np.array([0.075, 0.075, 0.08])
    c = np.where((rho > r - 0.5)[..., None], rubber, c)
    a = np.where(rho > RIM_FRAC * r - 1, 1.0, a)          # tyre always solid
    if os.path.exists(WHEEL_SRC):                         # clean wheel image overrides the photo
        src = mpimg.imread(WHEEL_SRC)
        if src.dtype != np.float32 and src.max() > 1:
            src = src / 255.0
        if src.shape[2] == 3:
            src = np.concatenate([src, np.ones(src.shape[:2] + (1,))], -1)
        ys, xs = np.nonzero(src[..., 3] > 0.5)
        scx, scy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
        sr = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2
        k2 = sr / r                                       # photo px -> source px
        c4 = bilinear(src, scx + dx * k2, scy - dy * k2)
        c = c4[..., :3] * c4[..., 3:4] + BEHIND * (1 - c4[..., 3:4])
        a = np.where(rho > r - 0.5, 1.0, c4[..., 3])
        c = np.where((rho > r - 0.5)[..., None], rubber, c)
        print('wheel tile from', WHEEL_SRC)
    # no red on the wheel (user): red pinstripe / caliper tint -> rim black, then grey only
    red = smooth(0.03, 0.12, c[..., 0] - np.maximum(c[..., 1], c[..., 2]))[..., None]
    c = c * (1 - red) + np.array([0.06, 0.06, 0.065]) * red
    c = np.repeat(c.mean(-1, keepdims=True), 3, -1)
    alb[r0:r1, c0:c1] = c
    alpha[r0:r1, c0:c1] = (a > 0.5).astype(float)
    lum = c.mean(-1); sat = c.max(-1) - c.min(-1)
    metal = smooth(0.30, 0.55, lum) * (1 - smooth(0.1, 0.3, sat))
    tyre = rho > r * 0.80
    dat[r0:r1, c0:c1, 0] = np.where(tyre, 0.9, 0.45 - 0.2 * metal)
    dat[r0:r1, c0:c1, 1] = np.where(tyre, 0.0, 0.25 + 0.65 * metal)
    dat[r0:r1, c0:c1, 2] = 0

    # spring: red helix coils
    r0, r1, c0, c1 = px_rect('spring')
    h, w_ = r1 - r0, c1 - c0
    vv, uu = np.meshgrid((np.arange(h)[::-1] + 0.5) / h, (np.arange(w_) + 0.5) / w_, indexing='ij')
    coils = 9
    ph = (vv * coils + uu) % 1.0
    wire = np.exp(-((ph - 0.5) / 0.22) ** 2)                 # round wire cross-section
    shade = 0.55 + 0.45 * np.cos((uu - 0.5) * np.pi * 2) ** 2
    red = np.array([0.78, 0.07, 0.06]); gap = np.array([0.05, 0.02, 0.02])
    alb[r0:r1, c0:c1] = (gap + (red * (0.5 + 0.5 * shade[..., None]) - gap) * wire[..., None])
    dat[r0:r1, c0:c1, 0] = 0.35 + 0.4 * (1 - wire)
    dat[r0:r1, c0:c1, 1] = 0.1

    # tread: chevron grooves, periodic in v (around the tyre)
    r0, r1, c0, c1 = px_rect('tread')
    h, w_ = r1 - r0, c1 - c0
    vv, uu = np.meshgrid((np.arange(h)[::-1] + 0.5) / h, (np.arange(w_) + 0.5) / w_, indexing='ij')
    chev = (vv * 3 + np.abs(uu - 0.5) * 1.2) % 1.0
    groove = (np.abs(chev - 0.5) < 0.06) & (np.abs(uu - 0.5) < 0.42)
    base = 0.08 + 0.02 * np.cos(uu * np.pi * 2)
    t = np.where(groove, 0.03, base)
    alb[r0:r1, c0:c1] = t[..., None] * np.array([1, 1, 1.05])
    dat[r0:r1, c0:c1, 0] = 0.92
    dat[r0:r1, c0:c1, 1] = 0.0

    os.makedirs(OUT, exist_ok=True)
    mpimg.imsave(os.path.join(OUT, 'T_MotoAtlas.png'),
                 np.concatenate([np.clip(alb, 0, 1), alpha[..., None]], -1))
    mpimg.imsave(os.path.join(OUT, 'T_MotoAtlasData.png'), np.clip(dat, 0, 1))
    json.dump({'size': N, 'slots': SLOTS, 'palette': {k: v[1] for k, v in PALETTE.items()},
               'regions': REGIONS, 'wheel_radius_frac': r / rc},
              open(os.path.join(OUT, 'atlas.json'), 'w'), indent=1)
    print('atlas written; wheel tile radius frac', round(r / rc, 4))


if __name__ == '__main__':
    main()
