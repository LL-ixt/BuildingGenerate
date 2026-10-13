"""METRO V3 textures. Plain Python 3.12 (numpy, PIL):
    python Blender/scripts/build_metro_texture.py

Needs Export/Metro/metro.json (build_metro.py --build writes it: the girder profile drives the
girder atlas). Sources (CC0, ambientCG, Textures/src/cc0/props/<id>/): Concrete032 (smooth cast
concrete: fine grain + normal) only; large blotches are procedural noise (no 2 m repeat). Writes Export/Textures/Metro/:

    T_MetroConcrete(_N).png   1024^2, 4 x 4 m tile: generic cast concrete (parapets, plinths with a
                              dark tint, LOD2 shell, sweep caps). UV = metres / 4.
    T_MetroGirder(_N).png     1024 x 2048 "profile atlas": u = 8 m along the line, v = arc length
                              around the girder profile / perimeter (MetroBuilder uv mode 'fraction'),
                              so the fascia rows carry the rain streaks running down from the parapet,
                              the drip edge is dirty, the underside slightly mottled.
    T_MetroPier(_N).png       1024^2: u = around the pier (fraction of the ring), v = z / cap top.
                              Streaks under the cap, a damp shadow right below it, formwork lift
                              lines, splash grime at the foot; streaks on the cap slope.
    T_MetroBarrier(_N).png    1024^2 = one 2 x 2 m noise-barrier panel between two posts: white panel,
                              4 sub-panels on aluminium rails, fine vertical ribs, dust at the bottom.
Image rows: row 0 = v 1 (top of the texture in Unity / Blender).
"""
import json
import os

import numpy as np
from PIL import Image

ROOT = r"D:\Project III\BuildingGenerate"
SRC = os.path.join(ROOT, "Textures", "src", "cc0", "props")
OUT = os.path.join(ROOT, "Export", "Textures", "Metro")
SPEC = os.path.join(ROOT, "Export", "Metro", "metro.json")
SRC_M = 2.0                  # physical size of one ambientCG concrete tile (m)
CONCRETE_SRGB = np.array([0.585, 0.575, 0.545])     # mean albedo (the kerb lesson: ~0.55 sRGB, not brighter)
GIRDER_U_LEN = 8.0
rng = np.random.default_rng(11)


# ---------------------------------------------------------------- helpers
def load(asset, kind):
    p = os.path.join(SRC, asset, f"{asset}_1K-JPG_{kind}.jpg")
    return np.asarray(Image.open(p).convert('RGB'), dtype=np.float32) / 255.0


def tiled(img, phys_w, phys_h, px_w, px_h):
    """Repeat a tileable source (SRC_M metres square) over phys_w x phys_h metres in px_w x px_h pixels.
    The repeat count is rounded to an integer on each axis, so the result tiles seamlessly itself."""
    rx, ry = max(1, round(phys_w / SRC_M)), max(1, round(phys_h / SRC_M))
    tw, th = max(1, round(px_w / rx)), max(1, round(px_h / ry))
    t = np.asarray(Image.fromarray((img * 255).astype(np.uint8)).resize((tw, th), Image.LANCZOS),
                   dtype=np.float32) / 255.0
    big = np.tile(t, (ry, rx, 1))
    return np.asarray(Image.fromarray((big * 255).astype(np.uint8)).resize((px_w, px_h), Image.BILINEAR),
                      dtype=np.float32) / 255.0


def wrap_blur(a, r):
    """Gaussian blur (sigma r px) that wraps around both edges (FFT: keeps tiling)."""
    if a.ndim == 3:
        return np.stack([wrap_blur(a[..., c], r) for c in range(a.shape[2])], -1)
    h, w = a.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    g = np.exp(-2 * (np.pi * r) ** 2 * (fx ** 2 + fy ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * g)).astype(np.float32)


def norm(a):
    return (a - a.mean()) / (a.std() + 1e-6)


def lum(rgb):
    return rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)


def concrete(phys_w, phys_h, px_w, px_h):
    """(albedo 0..1 sRGB, normal xyz -1..1): fine grain of Concrete032 + procedural large blotches,
    recoloured to CONCRETE_SRGB."""
    c32 = tiled(load('Concrete032', 'Color'), phys_w, phys_h, px_w, px_h)
    l32 = lum(c32)
    fine = l32 - wrap_blur(l32, 2.0)                    # grain only: the source's 2 m blotches would repeat
    # large-scale variation = procedural noise over the whole texture (no 2 m repeat)
    big = sum(w * norm(wrap_blur(rng.random((px_h, px_w)).astype(np.float32), r))
              for r, w in ((6, 0.25), (22, 0.45), (70, 0.6)))
    shade = 1.0 + 1.4 * fine + 0.035 * big
    alb = CONCRETE_SRGB[None, None, :] * shade[..., None]
    n32 = tiled(load('Concrete032', 'NormalGL'), phys_w, phys_h, px_w, px_h) * 2 - 1
    n = n32 * np.array([0.6, 0.6, 1.0], dtype=np.float32)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return np.clip(alb, 0, 1), n


def normal_from_height(h, strength, wrap=True):
    """Height (rows down = -v) -> OpenGL tangent-space normal (green = +v)."""
    if wrap:
        du = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) / 2
        dr = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) / 2
    else:
        du = np.gradient(h, axis=1); dr = np.gradient(h, axis=0)
    dv = -dr
    n = np.stack([-du * strength, -dv * strength, np.ones_like(h)], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def combine_normals(a, b):
    """Whiteout blend of two tangent-space normals."""
    n = np.stack([a[..., 0] + b[..., 0], a[..., 1] + b[..., 1], a[..., 2] * b[..., 2]], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def streaks(h, w, n, length, width, strength, start_jitter=0, rng=rng, wrap_x=True):
    """Dark rain streaks running DOWN the canvas (row 0 = where the water comes from).
    length / width / strength: (lo, hi) ranges in pixels / pixels / darkening 0..1. Returns 0..1."""
    m = np.zeros((h, w), np.float32)
    rows = np.arange(h, dtype=np.float32)[:, None]
    for _ in range(n):
        x0 = rng.uniform(0, w)
        y0 = rng.uniform(0, start_jitter) if start_jitter else 0.0
        L = rng.uniform(*length)
        sw = rng.uniform(*width)
        st = rng.uniform(*strength)
        x_lo, x_hi = int(x0 - 4 * sw - 3), int(x0 + 4 * sw + 4)
        xs = np.arange(x_lo, x_hi, dtype=np.float32)[None, :]
        t = np.clip((rows - y0) / L, 0, None)
        wob = np.sin(rows / rng.uniform(6, 14) + rng.uniform(0, 6)) * sw * 0.35       # slight meander
        lat = np.exp(-((xs - x0 - wob) ** 2) / (2 * (sw * (1 + 0.6 * t)) ** 2))    # widens downward
        along = np.where(rows >= y0, np.clip(1 - t, 0, 1) ** 1.6, 0.0)
        val = st * along * lat
        cols = np.arange(x_lo, x_hi) % w if wrap_x else np.clip(np.arange(x_lo, x_hi), 0, w - 1)
        m[:, cols] = np.maximum(m[:, cols], val)
    noise = wrap_blur(rng.random((h, w)).astype(np.float32), 1.2)
    return np.clip(m * (0.75 + 0.5 * noise), 0, 1)


def save(name, alb=None, nrm=None):
    os.makedirs(OUT, exist_ok=True)
    if alb is not None:
        Image.fromarray((np.clip(alb, 0, 1) * 255 + 0.5).astype(np.uint8)).save(os.path.join(OUT, name + '.png'))
    if nrm is not None:
        Image.fromarray(((nrm * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8)).save(os.path.join(OUT, name + '_N.png'))
    print('[metro tex]', name, '' if alb is None else f'mean albedo {alb.mean(axis=(0, 1)).round(3)}')


# ---------------------------------------------------------------- textures
def build_concrete():
    alb, n = concrete(4.0, 4.0, 1024, 1024)
    save('T_MetroConcrete', alb, n)


def girder_segments(spec):
    """Girder profile -> [(v0, v1, kind, down_is_row_plus)] with v = arc fraction; kind fascia / top / under."""
    p = next(x for x in spec['profiles'] if x['name'] == 'girder')['pts']
    pts = list(zip(p[0::2], p[1::2]))
    n = len(pts)
    lens = [np.hypot(pts[(k + 1) % n][0] - pts[k][0], pts[(k + 1) % n][1] - pts[k][1]) for k in range(n)]
    total = sum(lens)
    segs, acc = [], 0.0
    for k in range(n):
        (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % n]
        nx, ny = (y1 - y0), -(x1 - x0)                  # outward normal of a CCW edge
        L = lens[k]
        kind = 'fascia' if abs(nx) > 0.9 * L else ('top' if ny > 0.9 * L else 'under')
        # image rows grow as v falls; along the edge v grows: down (y falling) = rows+ when y rises with v
        segs.append((acc / total, (acc + L) / total, kind, y1 > y0, L))
        acc += L
    return segs, total


def build_girder(spec):
    W, H = 1024, 2048
    segs, total = girder_segments(spec)
    alb, n = concrete(GIRDER_U_LEN, total, W, H)
    shade = np.ones((H, W), np.float32)
    for v0, v1, kind, down_plus, L in segs:
        r0, r1 = int(round((1 - v1) * H)), int(round((1 - v0) * H))     # rows of this face
        h = r1 - r0
        if h < 2:
            continue
        ppm = h / L
        if kind == 'fascia':
            # streaks from the parapet foot (top edge) down the 0.55 m fascia, dirty drip edge at the bottom
            m = streaks(h, W, 70, (0.25 * h, 1.3 * h), (1.0, 3.5), (0.10, 0.42), start_jitter=2)
            edge = np.exp(-(np.arange(h)[::-1, None] / (0.04 * ppm)) ** 2).astype(np.float32)
            dirt = 1 - 0.55 * m - 0.18 * edge
            top_band = np.exp(-(np.arange(h)[:, None] / (0.05 * ppm)) ** 2) * 0.10     # damp line under the parapet
            dirt -= top_band.astype(np.float32)
            if not down_plus:
                dirt = dirt[::-1]
            shade[r0:r1] *= dirt
        elif kind == 'under':
            mott = wrap_blur(rng.random((h, W)).astype(np.float32), 18)
            mott = (mott - mott.mean()) / (mott.std() + 1e-6)
            shade[r0:r1] *= (0.93 + 0.03 * mott)
        else:   # deck top: dusty, mostly hidden under the plinths / troughs
            shade[r0:r1] *= 0.9
    save('T_MetroGirder', alb * shade[..., None], n)


def build_pier(spec):
    W = H = 1024
    cap_top = spec['cap_top']
    v_of = lambda z: z / cap_top
    row = lambda z: int(round((1 - v_of(z)) * H))
    col_perim = 2 * (2.6 + 2.0) - 8 * 0.3 + 4 * np.hypot(0.3, 0.3)
    alb, n = concrete(col_perim, cap_top, W, H)
    shade = np.ones((H, W), np.float32)
    rcb = row(spec['cap_bottom'])                       # column top
    rw = row(cap_top - 0.45)                            # widest cap ring
    rows = np.arange(H, dtype=np.float32)[:, None]
    ppm = H / cap_top
    # damp shadow right under the cap + streaks running down the column
    damp = np.where(rows >= rcb, np.exp(-((rows - rcb) / (0.35 * ppm)) ** 2), 0)
    m = streaks(H - rcb, W, 45, (0.4 * ppm, 3.6 * ppm), (1.5, 5.0), (0.08, 0.30), start_jitter=3)
    shade[rcb:] *= 1 - 0.5 * m
    shade *= (1 - 0.10 * damp).astype(np.float32)
    # streaks on the cap slope (widest ring -> column)
    mc = streaks(rcb - rw, W, 40, (0.3 * (rcb - rw), 1.0 * (rcb - rw)), (1.0, 3.0), (0.08, 0.25))
    shade[rw:rcb] *= 1 - 0.5 * mc
    # formwork lift lines on the column (every 2.4 m) and splash grime at the foot
    hgt = np.zeros((H, W), np.float32)
    for z in np.arange(2.4, spec['cap_bottom'] - 0.3, 2.4):
        r = row(z)
        shade[r - 1:r + 2] *= 0.93
        hgt[r - 1:r + 2] -= 1.0
    foot = np.clip(1 - (cap_top * (1 - rows / H)) / 0.7, 0, 1) ** 1.5           # bottom 0.7 m
    fnoise = wrap_blur(rng.random((H, W)).astype(np.float32), 2.5)
    shade *= (1 - foot * (0.18 + 0.25 * fnoise)).astype(np.float32)
    nrm = combine_normals(n, normal_from_height(wrap_blur(hgt, 0.8), 1.5))
    save('T_MetroPier', alb * shade[..., None], nrm)


def build_barrier():
    W = H = 1024                                        # 2 m x 2 m
    ppm = W / 2.0
    u = (np.arange(W, dtype=np.float32) + 0.5) / ppm    # m across the panel
    yv = (H - np.arange(H, dtype=np.float32) - 0.5) / ppm   # m up from the barrier foot
    U, Y = np.meshgrid(u, yv)
    base = np.array([0.84, 0.86, 0.86], np.float32)
    rail = np.array([0.60, 0.61, 0.62], np.float32)
    hgt = np.zeros((H, W), np.float32)
    col = np.broadcast_to(base, (H, W, 3)).copy()
    # fine vertical ribs every 5 cm (shading + height)
    rib = 0.5 + 0.5 * np.cos(2 * np.pi * U / 0.05)
    col *= (0.965 + 0.035 * rib)[..., None]
    hgt += 0.4 * rib
    # aluminium frame: rails at 0, 0.5, 1.0, 1.5, 2.0 m (6 cm), side frames 4 cm (behind the posts)
    is_rail = np.zeros((H, W), bool)
    for z in (0.0, 0.5, 1.0, 1.5, 2.0):
        is_rail |= np.abs(Y - z) < 0.03
    is_rail |= (U < 0.04) | (U > 1.96)
    col[is_rail] = rail
    hgt[is_rail] = 2.0
    # dust: road spray at the bottom, streaks below each rail, a little overall noise
    dust = np.clip(1 - Y / 0.6, 0, 1) ** 1.3 * 0.22
    sm = np.zeros((H, W), np.float32)
    for z in (2.0, 1.5, 1.0, 0.5):
        r0 = int(round((2.0 - z) * ppm)) + 16
        hh = int(0.45 * ppm)
        sm[r0:r0 + hh] = np.maximum(sm[r0:r0 + hh], streaks(min(hh, H - r0), W, 25, (0.3 * hh, hh), (1.0, 3.0), (0.05, 0.16))[:H - r0])
    noise = wrap_blur(rng.random((H, W)).astype(np.float32), 30)
    noise = (noise - noise.mean()) / (noise.std() + 1e-6)
    shade = (1 - dust - 0.6 * sm + 0.02 * noise)[..., None]
    nrm = normal_from_height(wrap_blur(hgt, 1.0), 2.0)
    save('T_MetroBarrier', col * shade, nrm)


def build_kerb_stripe():
    """Planter kerb (P1): 1 m period = 0.5 m red + 0.5 m white paint on concrete, u along the line,
    v = up the kerb profile (0 = road). Worn paint on the edges, road grime at the foot."""
    W, H = 512, 128
    alb, _ = concrete(1.0, 0.3, W, H)
    u = (np.arange(W) + 0.5) / W
    red = np.array([150, 38, 32], np.float32) / 255
    white = np.array([214, 208, 196], np.float32) / 255
    paint = np.where((u < 0.5)[None, :, None], red, white)
    grain = alb / CONCRETE_SRGB[None, None, :]
    wear = wrap_blur(rng.random((H, W)).astype(np.float32), 3)
    wear = np.clip((wear - np.percentile(wear, 88)) * 25, 0, 1)          # ~12 % chipped to concrete
    col = paint * grain * (1 - wear[..., None]) + alb * wear[..., None]
    v = 1 - (np.arange(H) + 0.5) / H                                       # row 0 = v 1 (kerb top)
    grime = np.clip(1 - v / 0.35, 0, 1)[:, None] ** 1.5 * 0.35
    col *= (1 - grime)[..., None]
    save('T_MetroKerbStripe', col)


if __name__ == '__main__':
    spec = json.load(open(SPEC, encoding='utf-8'))
    build_concrete()
    build_girder(spec)
    build_pier(spec)
    build_barrier()
    build_kerb_stripe()
