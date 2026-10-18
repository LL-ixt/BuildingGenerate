"""Big buildings from OSM footprints, tube-house lots infilled along block frontages, layout checks."""
import math, random

import shapely
from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .osm import area_features, polygons_of, to_float


BIG_AREA = 250.0         # m2: footprints at least this big are kept as "big buildings"
BIG_LEVELS = 6            # ... or this many floors
LOT_DEPTH = 12.0          # matches the tube-house library depth
LOT_MIN, LOT_MAX = 3.5, 5.0
FLOOR_H = 3.2


def min_rect(poly):
    """Oriented rectangle -> (centre, long-axis unit vector, length, width, polygon)."""
    r = poly.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e0 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e1 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    l0, l1 = math.hypot(*e0), math.hypot(*e1)
    axis, L, Wd = (e0, l0, l1) if l0 >= l1 else (e1, l1, l0)
    n = math.hypot(*axis) or 1.0
    return (r.centroid.x, r.centroid.y), (axis[0] / n, axis[1] / n), L, Wd, r


def build_big(ways, rels, nodes, area, blocked_t, overrides, flags):
    raw = area_features(ways, rels, nodes, lambda t: 'building' in t and t.get('building') != 'no')
    deletes = [g for p, g in overrides if p.get('op') == 'delete']
    cands = []
    for bid, poly, tags in raw:
        levels = to_float(tags.get('building:levels'))
        h = to_float(tags.get('height'))
        if levels is None and h:
            levels = round(h / FLOOR_H)
        if poly.area < BIG_AREA and (levels or 0) < BIG_LEVELS:
            continue
        if not poly.intersects(area) or any(poly.intersects(d) for d in deletes):
            continue
        cands.append(dict(id=bid, poly=poly.simplify(0.5), levels=levels, area=poly.area, src='osm',
                          name=tags.get('name', '')))
    for props, g in overrides:
        if props.get('op') == 'building':
            for p in polygons_of(g):
                cands = [c for c in cands if not c['poly'].intersects(p)]
                cands.append(dict(id=f"ovr{len(cands)}", poly=p, levels=to_float(props.get('levels')),
                                  area=p.area, src='override', name=props.get('name', '')))

    # priority: overrides > taller > has levels > bigger
    cands.sort(key=lambda c: (c['src'] != 'override', -(c['levels'] or 0), c['levels'] is None, -c['area']))
    placed, taken = [], []

    def taken_near(g):
        bx0, by0, bx1, by1 = g.bounds
        near = [t for t in taken if t.bounds[0] <= bx1 and t.bounds[2] >= bx0 and t.bounds[1] <= by1 and t.bounds[3] >= by0]
        return unary_union(near) if near else Polygon()

    for c in cands:
        poly = c['poly'].intersection(area).difference(blocked_t.near(c['poly']))
        if taken:
            poly = poly.difference(taken_near(poly))
        parts = polygons_of(poly)
        if not parts:
            flags.append(dict(kind='building_dropped', id=c['id'], xy=list(c['poly'].centroid.coords[0]),
                              msg='nha lon bi duong/nha khac de hoan toan'))
            continue
        part = max(parts, key=lambda p: p.area)
        kept = part.area / c['area']
        if kept < 0.5:
            flags.append(dict(kind='building_dropped', id=c['id'], xy=list(c['poly'].centroid.coords[0]),
                              msg=f'chi con {kept:.0%} dien tich sau khi tru duong/chong lan'))
            continue
        (cx, cy), axis, L, Wd, rect = min_rect(part)
        # the rectangle itself must not hit roads or earlier buildings
        clash = blocked_t.area_in(rect) + taken_near(rect).intersection(rect).area
        if clash > 0.08 * rect.area:
            rect = rect.buffer(-1.0, join_style='mitre')
            (cx, cy), axis, L, Wd, rect = min_rect(rect) if not rect.is_empty else ((cx, cy), axis, L, Wd, rect)
        clash = blocked_t.area_in(rect) + taken_near(rect).intersection(rect).area
        if rect.is_empty or clash > 0.08 * rect.area:
            flags.append(dict(kind='building_dropped', id=c['id'], xy=[cx, cy],
                              msg=f'hinh chu nhat bao lan duong/nha khac {clash:.0f} m2 (sua tay trong overrides)'))
            continue
        if kept < 0.7:
            flags.append(dict(kind='building_cut', id=c['id'], xy=[cx, cy], msg=f'bi cat con {kept:.0%}'))
        if c['levels'] is None and c['area'] > 1500:
            flags.append(dict(kind='no_levels', id=c['id'], xy=[cx, cy],
                              msg=f'nha {c["area"]:.0f} m2 khong co so tang (dat building:levels trong overrides)'))
        taken.append(rect)
        placed.append(dict(id=c['id'], src=c['src'], name=c['name'], levels=c['levels'],
                           area=round(c['area'], 1), cx=round(cx, 2), cy=round(cy, 2),
                           axis=[round(axis[0], 4), round(axis[1], 4)], length=round(L, 2), width=round(Wd, 2),
                           rect=rect, poly=part))
    print(f"[buildings] {len(raw)} OSM footprints -> {len(cands)} big candidates -> {len(placed)} placed")
    return placed, (unary_union(taken) if taken else Polygon())


def facing_road(p0, p1, street_t, step=1.5):
    """True if the outside of block edge p0->p1 (CCW exterior => outside on the right) touches a street."""
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy)
    nx, ny = dy / L, -dx / L
    return street_t.covers_point(Point(mx + nx * step, my + ny * step)), (nx, ny)


def infill_lots(blocks, street_t, flags, seed=7):
    rng = random.Random(seed)
    lots = []
    for bi, blk in enumerate(blocks):
        if blk.area < 30:
            continue
        b = blk.simplify(1.0)
        if b.is_empty or not isinstance(b, Polygon):
            continue
        b = orient(b, sign=1.0)          # CCW exterior: the street side of an edge is on its right
        shapely.prepare(b)
        shapely.prepare(blk)
        taken = []
        coords = list(b.exterior.coords)
        frontage = 0.0
        for p0, p1 in zip(coords, coords[1:]):
            L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if L < LOT_MIN:
                continue
            ok, (nx, ny) = facing_road(p0, p1, street_t)
            if not ok:
                continue
            frontage += L
            tx, ty = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            # split the edge into lots of 3.5..5 m
            widths, rest = [], L
            while rest >= LOT_MIN:
                w = rng.uniform(LOT_MIN, LOT_MAX)
                if rest - w < LOT_MIN:
                    w = rest if rest <= LOT_MAX + 0.5 else rest / 2
                widths.append(w)
                rest -= w
            s = (L - sum(widths)) / 2
            sb = 0.3                                          # setback absorbs simplification error
            for w in widths:
                a = (p0[0] + tx * s - nx * sb, p0[1] + ty * s - ny * sb)
                c = (a[0] + tx * w, a[1] + ty * w)
                ix, iy = -nx * LOT_DEPTH, -ny * LOT_DEPTH          # inwards
                rect = Polygon([a, c, (c[0] + ix, c[1] + iy), (a[0] + ix, a[1] + iy)])
                s += w
                if not blk.contains(rect):                   # true block, prepared
                    if rect.area - rect.intersection(blk).area > 0.3:   # m2 sticking out of the block
                        continue
                rb = rect.bounds
                clash = sum(t.intersection(rect).area for t in taken
                            if t.bounds[0] < rb[2] and t.bounds[2] > rb[0] and t.bounds[1] < rb[3] and t.bounds[3] > rb[1])
                if clash > 0.05:                             # m2; lots may touch, never overlap
                    continue
                taken.append(rect)
                lots.append(dict(cx=round((a[0] + c[0]) / 2, 2), cy=round((a[1] + c[1]) / 2, 2),
                                 front=[round(nx, 4), round(ny, 4)], width=round(w, 2), depth=LOT_DEPTH,
                                 block=bi, rect=rect))
        if frontage == 0 and blk.area > 200:
            flags.append(dict(kind='block_no_frontage', id=f"b{bi}", xy=list(blk.representative_point().coords[0]),
                              msg=f'khoi {blk.area:.0f} m2 khong giap duong nao (ngo thieu trong OSM?)'))
    print(f"[lots] {len(lots)} tube-house lots in {len(blocks)} blocks")
    return lots


def checks(lots, big, street_t, flags):
    lot_polys = [l['rect'] for l in lots]
    tree = STRtree(lot_polys)
    overl = 0
    for i, p in enumerate(lot_polys):
        for j in tree.query(p):
            if j > i and p.intersection(lot_polys[j]).area > 0.5:
                overl += 1
    on_road = sum(1 for p in lot_polys if street_t.area_in(p) > 0.5)
    big_on_road = sum(1 for b in big if street_t.area_in(b['rect']) > 0.08 * b['rect'].area)
    big_tree = STRtree([b['rect'] for b in big]) if big else None
    lot_on_big = 0 if big_tree is None else sum(
        1 for p in lot_polys for j in big_tree.query(p) if p.intersection(big[j]['rect']).area > 0.5)
    res = dict(lot_overlaps=overl, lots_on_road=on_road, big_on_road=big_on_road, lots_on_big=lot_on_big)
    print(f"[check] {res}")
    return res
