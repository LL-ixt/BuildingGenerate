"""MOTO X1 — trace the side photo of the Honda SH (Ref/xemay.png) into part outlines.

Plain Python 3.12 (numpy, contourpy, shapely, matplotlib), not Blender:
    python Blender/scripts/moto_trace.py

How it works: the photo has a clean alpha channel -> silhouette S. Green paint pixels,
smoothed -> paint mask P. Each part = (hand-placed region box in pixels) ∩ S, then ∩ P
(painted parts) or − P − wheel discs (black parts), minus what earlier parts already took
(PARTS order = priority, so parts never overlap). So outer edges come from the photo,
only the internal cuts between parts are hand-placed (PARTS below — edit them here).
Wheels are fitted circles (least squares on the free tyre edge), not traced.

Output, profile plane (u = forward from the wheelbase midpoint, z = up from the ground, metres):
    Blender/moto/sh_profile.json      parts, wheels, anchor points, scale
    Blender/previews/moto_trace.png   outlines over the photo for checking
"""
import json
import os
from functools import reduce

import contourpy
import matplotlib
matplotlib.use('Agg')
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union

ROOT = r"D:\Project III\BuildingGenerate"
SRC = os.path.join(ROOT, "Ref", "xemay.png")
OUT_JSON = os.path.join(ROOT, "Blender", "moto", "sh_profile.json")
OUT_PNG = os.path.join(ROOT, "Blender", "previews", "moto_trace.png")

WHEELBASE_M = 1.353          # Honda SH 150i/160i spec -> image scale
SIMPLIFY_PX = 3.5            # outline simplification (~8 mm)
MIN_AREA_PX = 250            # drop specks (decals, gaps)

# Part regions, image pixels (x right = forward, y down). mode: paint = ∩P, black = −P −wheels,
# all = whole silhouette. width/offset = default extrusion (m) for X2; offset > 0 = rider's left.
PARTS = {
    'SEAT':         dict(mode='black', slot='SEAT', width=0.30, offset=0.0,
                         region=[(195, 262), (560, 262), (560, 445), (520, 445), (470, 410),
                                 (420, 375), (330, 335), (250, 322), (195, 310)]),
    'RACK':         dict(mode='all', slot='PLASTIC', width=0.24, offset=0.0,
                         region=[(85, 258), (200, 258), (200, 290), (85, 282)]),
    'TAIL_LIGHT':   dict(mode='black_only', slot='RED', width=0.20, offset=0.0,
                         region=[(108, 284), (200, 290), (200, 320), (130, 314)]),
    'BODY_REAR':    dict(mode='paint', slot='PAINT', width=0.36, offset=0.0,
                         region=[(100, 260), (595, 260), (595, 610), (100, 610)]),
    'BODY_FRONT':   dict(mode='paint', slot='PAINT', width=0.42, offset=0.0,
                         region=[(595, 258), (800, 258), (800, 368), (728, 368), (728, 450),
                                 (800, 450), (800, 610), (595, 610)]),
    'HEADLIGHT':    dict(mode='black_only', slot='LIGHT', width=0.30, offset=0.0,
                         region=[(735, 318), (800, 318), (800, 372), (735, 372)]),
    'FRONT_FENDER': dict(mode='paint', slot='PAINT', width=0.14, offset=0.0, steer=True,
                         region=[(728, 368), (895, 368), (895, 450), (728, 450)]),
    'HANDLE_COVER': dict(mode='all', slot='PAINT', width=0.30, offset=0.0, steer=True,
                         region=[(560, 182), (705, 182), (705, 262), (560, 262)]),
    'NECK':         dict(mode='black', slot='PLASTIC', width=0.14, offset=0.0,
                         region=[(600, 250), (705, 250), (705, 335), (600, 335)]),
    'LEG_INNER':    dict(mode='black', slot='PLASTIC', width=0.34, offset=0.0,
                         region=[(598, 300), (665, 300), (665, 505), (598, 505)]),
    'FLOOR':        dict(mode='black', slot='PLASTIC', width=0.30, offset=0.0,
                         region=[(470, 445), (700, 445), (700, 600), (470, 600)]),
    'UNDER_REAR':   dict(mode='black', slot='PLASTIC', width=0.26, offset=0.0,
                         region=[(150, 325), (480, 325), (480, 418), (240, 418), (240, 370),
                                 (170, 370), (170, 418), (150, 418)]),
    'MUDGUARD':     dict(mode='black', slot='PLASTIC', width=0.16, offset=0.0,
                         region=[(45, 335), (150, 335), (150, 505), (45, 505)]),
    'POWERTRAIN':   dict(mode='black', slot='PLASTIC', width=0.26, offset=-0.02,
                         region=[(300, 418), (480, 418), (480, 600), (300, 600)]),
    'EXHAUST':      dict(mode='all', slot='METAL', width=0.13, offset=-0.17,
                         region=[(146, 446), (172, 430), (312, 522), (316, 562), (282, 562),
                                 (146, 474)]),
}
STEER_PARTS = [k for k, v in PARTS.items() if v.get('steer')]

# Points read off the photo (pixels) for procedural pieces built in X2.
POINTS = {
    'mirror_R_head': (602, 145), 'mirror_L_head': (624, 122),   # far mirror shows higher
    'mirror_root': (622, 192), 'grip': (590, 222),
    'fork_top': (742, 365), 'shock_top': (221, 377), 'shock_bottom': (186, 462),
    'tail_end': (110, 292), 'plate': (62, 470),
    'seat_top': (440, 300),                     # rider sits around here
    'foot': (560, 515),                         # floorboard, front of the seat
}


def box_blur(m, r):
    """Mean filter (2r+1)^2 via an integral image (no scipy here)."""
    p = np.pad(m.astype(np.float64), r + 1, mode='edge')
    c = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return (s / (k * k))[:m.shape[0], :m.shape[1]]


def close(mask, r):
    return box_blur(box_blur(mask, r) > 0.25, r) > 0.75


def mask_polygons(mask):
    """Binary mask -> shapely geometry (even-odd rule handles holes)."""
    z = box_blur(mask, 1)
    lines = contourpy.contour_generator(z=z).lines(0.5)
    polys = [Polygon(l).buffer(0) for l in lines if len(l) >= 4]
    polys = [p for p in polys if p.area > 4]
    return reduce(lambda a, b: a.symmetric_difference(b), polys, Polygon())


def fit_circle(pts):
    p = np.asarray(pts, float)
    A = np.c_[2 * p[:, 0], 2 * p[:, 1], np.ones(len(p))]
    cx, cy, c = np.linalg.lstsq(A, (p ** 2).sum(1), rcond=None)[0]
    r = np.sqrt(c + cx * cx + cy * cy)
    res = np.abs(np.hypot(p[:, 0] - cx, p[:, 1] - cy) - r)
    return float(cx), float(cy), float(r), float(res.max())


def pieces(geom):
    if geom.is_empty:
        return []
    gs = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    out = []
    for g in sorted(gs, key=lambda g: -g.area):
        if not isinstance(g, Polygon) or g.area < MIN_AREA_PX:
            continue
        g = Polygon(g.exterior)                     # holes (decals) filled
        if any(o.contains(g.representative_point()) for o in out):
            continue                                # island inside a filled hole
        out.append(g.simplify(SIMPLIFY_PX, preserve_topology=True))
    return out


def main():
    img = mpimg.imread(SRC)
    alpha, rgb = img[..., 3], img[..., :3]
    solid = alpha > 0.9
    S = close(alpha > 0.5, 1)
    mx = rgb.max(-1)
    green = S & (rgb[..., 1] > rgb[..., 0] + 0.03) & (rgb[..., 1] > rgb[..., 2]) & (mx >= 0.22)
    P = close(green, 4)

    # wheels: rightmost (front) / leftmost (rear) silhouette pixel per row on the free tyre arc
    fpts = [(600 + np.nonzero(solid[y, 600:])[0].max(), y) for y in range(470, 625)]
    rpts = [(np.nonzero(solid[y, :400])[0].min(), y) for y in range(505, 630)]
    fx, fy, fr, fe = fit_circle(fpts)
    rx, ry, rr, re = fit_circle(rpts)
    ground_px = (fy + fr + ry + rr) / 2
    s = WHEELBASE_M / np.hypot(fx - rx, fy - ry)          # metres per pixel
    mid_x = (fx + rx) / 2

    def to_m(x, y):
        return [round((x - mid_x) * s, 4), round((ground_px - y) * s, 4)]

    S_poly, P_poly = mask_polygons(S), mask_polygons(P)
    wheels_px = unary_union([Point(fx, fy).buffer(fr + 2), Point(rx, ry).buffer(rr + 2)])

    parts_out, drawn, claimed = {}, {}, Polygon()
    for name, d in PARTS.items():
        reg = Polygon(d['region'])
        g = reg.intersection(S_poly)
        if d['mode'] == 'paint':
            g = g.intersection(P_poly)
        elif d['mode'] == 'black':
            g = g.difference(P_poly).difference(wheels_px)
        elif d['mode'] == 'black_only':
            g = g.difference(P_poly)
        g = g.difference(claimed)
        ps = pieces(g)
        claimed = unary_union([claimed, g] + ps)      # incl. filled decal holes
        drawn[name] = ps
        parts_out[name] = {
            'slot': d['slot'], 'width': d['width'], 'offset': d['offset'],
            'steer': bool(d.get('steer')),
            'polys': [[to_m(x, y) for x, y in list(p.exterior.coords)[:-1]] for p in ps],
        }

    # silhouette not covered by any part (wheels and mirrors are built procedurally)
    mirrors_px = Polygon([(580, 90), (645, 90), (645, 200), (580, 200)])
    left = S_poly.difference(unary_union([claimed, wheels_px, mirrors_px]))
    leftovers = [g for g in pieces(left) if g.area > 400]
    sx0, sy0, sx1, sy1 = S_poly.bounds
    data = {
        'source': 'Ref/xemay.png', 'model': 'Honda SH 150i (side, right side of the bike)',
        'plane': 'u = forward from wheelbase midpoint (m), z = up from ground (m)',
        'metres_per_px': round(float(s), 6),
        'px_origin': [round(mid_x, 2), round(ground_px, 2)],
        'wheels': {
            'front': {'centre': to_m(fx, fy), 'radius': round(fr * s, 4), 'fit_err_px': round(fe, 2)},
            'rear': {'centre': to_m(rx, ry), 'radius': round(rr * s, 4), 'fit_err_px': round(re, 2)},
        },
        'points': {k: to_m(*v) for k, v in POINTS.items()},
        'bounds': {'u': [to_m(sx0, 0)[0], to_m(sx1, 0)[0]], 'z_top': to_m(0, sy0)[1]},
        'steer_parts': STEER_PARTS,
        'parts': parts_out,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)

    # ---- check image: photo faded, coloured part outlines, wheels, ground, origin
    h, w = alpha.shape
    fig = plt.figure(figsize=(w / 80, h / 80), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    bg = np.ones((h, w, 3)) * (1 - alpha[..., None]) + rgb * alpha[..., None]
    ax.imshow(0.45 + 0.55 * bg)
    cmap = plt.get_cmap('tab20')
    for i, (name, ps) in enumerate(drawn.items()):
        c = cmap(i % 20)
        for p in ps:
            xs, ys = p.exterior.xy
            ax.fill(xs, ys, color=c, alpha=0.35, lw=0)
            ax.plot(xs, ys, color=c, lw=1.4)
            ax.plot(xs, ys, '.', color=c, ms=2.5)
        if ps:
            cx, cy = ps[0].representative_point().coords[0]
            ax.text(cx, cy, f"{name}\n{len(ps[0].exterior.coords) - 1}v", fontsize=6.5,
                    ha='center', va='center', color='k',
                    bbox=dict(fc='w', alpha=0.7, lw=0, pad=0.5))
    for g in leftovers:
        xs, ys = g.exterior.xy
        ax.fill(xs, ys, fill=False, hatch='////', color='r', lw=0.8)
    for (cx, cy, r) in [(fx, fy, fr), (rx, ry, rr)]:
        ax.add_patch(plt.Circle((cx, cy), r, fill=False, color='r', lw=1.2, ls='--'))
        ax.plot(cx, cy, 'r+', ms=10)
    for k, (px, py) in POINTS.items():
        ax.plot(px, py, 'mx', ms=6)
        ax.text(px + 4, py - 3, k, fontsize=6, color='m')
    ax.axhline(ground_px, color='r', lw=0.8)
    ax.plot(mid_x, ground_px, 'ko', ms=5)
    ax.text(10, 20, f"{s * 1000:.2f} mm/px   wheelbase {WHEELBASE_M} m   "
            f"length {(sx1 - sx0) * s:.2f} m   height {(ground_px - sy0) * s:.2f} m   "
            f"wheel Ø F {2 * fr * s:.3f} / R {2 * rr * s:.3f} m", fontsize=8)
    ax.set_xlim(0, w); ax.set_ylim(h, 0); ax.axis('off')
    os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)
    fig.savefig(OUT_PNG)

    print(f"scale {s * 1000:.3f} mm/px  ground y={ground_px:.1f}px  mid x={mid_x:.1f}px")
    print(f"front wheel c=({fx:.1f},{fy:.1f}) r={fr:.1f}px err<={fe:.2f}  "
          f"rear c=({rx:.1f},{ry:.1f}) r={rr:.1f}px err<={re:.2f}")
    print(f"length {(sx1 - sx0) * s:.3f} m, height {(ground_px - sy0) * s:.3f} m")
    for name, p in parts_out.items():
        print(f"  {name:13s} pieces={len(p['polys'])} verts={[len(q) for q in p['polys']]}")
    print('uncovered silhouette (px^2, bbox):',
          [(int(g.area), [int(v) for v in g.bounds]) for g in leftovers])
    print('wrote', OUT_JSON, OUT_PNG)


if __name__ == '__main__':
    main()
