"""Elevated metro lines and the corridor / pier median under them."""
import math
import numpy as np
from collections import defaultdict

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, nearest_points, unary_union
from shapely.strtree import STRtree

from .osm import area_features, polygons_of, tangent, to_float, way_coords


RAIL_TYPES = {'subway', 'light_rail'}
MEDIAN_W = 5.0            # m: pier + planter-frame zone under an elevated metro (still asphalt for now)
CORRIDOR_MAX = 36.0       # m: furthest parallel carriageway swallowed into the metro corridor
CORRIDOR_CLUSTER = 12.0   # m: parallel roads this far past the nearest one still count (service lanes in the median)
CORRIDOR_CLS = {'motorway', 'trunk', 'primary', 'secondary'}
CROSS_CLS = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary',
             'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'}


def build_rails(ways, nodes, area):
    """Elevated metro lines -> (rails, platforms). Each rail = one line (both tracks) with its
    centreline, so the median / piers can follow the middle of the viaduct."""
    tracks = defaultdict(list)
    for wid, (refs, tags) in ways.items():
        if tags.get('railway') in RAIL_TYPES and (tags.get('bridge') not in (None, 'no')
                                                  or (to_float(tags.get('layer')) or 0) > 0):
            coords = way_coords(refs, nodes)
            if len(coords) > 1:
                tracks[tags.get('ref') or tags.get('name', '')].append(
                    (LineString(coords), int(to_float(tags.get('layer')) or 0), tags.get('name', '')))
    rails = []
    for ref, parts in tracks.items():
        merged = linemerge(unary_union([p[0] for p in parts]))
        lines = sorted(getattr(merged, 'geoms', [merged]), key=lambda l: -l.length)
        a, others = lines[0], unary_union(lines[1:]) if len(lines) > 1 else None
        pts = []
        for s in np.arange(0.0, a.length, 4.0).tolist() + [a.length]:
            p = a.interpolate(s)
            if others is not None and others.distance(p) < 10.0:       # midpoint between the two tracks
                q = others.interpolate(others.project(p)) if others.geom_type == 'LineString' \
                    else nearest_points(others, p)[0]
                p = Point((p.x + q.x) / 2, (p.y + q.y) / 2)
            pts.append((p.x, p.y))
        centre = LineString(pts).simplify(0.3).intersection(area.buffer(50))
        if centre.is_empty:
            continue
        centre = linemerge(centre) if centre.geom_type == 'MultiLineString' else centre
        rails.append(dict(ref=ref, name=parts[0][2], layer=max(p[1] for p in parts), tracks=len(lines),
                          centre=centre, track_lines=[l.intersection(area.buffer(50)) for l in lines]))
    platforms = [p for _, p, t in area_features(ways, [], nodes, lambda t: t.get('railway') == 'platform')
                 if p.intersects(area)]
    print(f"[rails] {len(rails)} elevated lines ({sum(r['centre'].length for r in rails):.0f} m in the map), "
          f"{len(platforms)} platforms")
    return rails, platforms


def metro_corridor(rails, roads, surface):
    """Ground between the two carriageways of a dual road that carries a metro viaduct in its middle
    (OSM draws two one-way roads ~40 m apart -> the gap became a block of tube houses).
    Returns (corridor, median): the corridor becomes road surface; the median marks the pier zone."""
    major = [r for r in roads if r['cls'] in CORRIDOR_CLS and r['layer'] <= 0 and not r['bridge']]
    tree = STRtree([r['line'] for r in major])
    quads, medians = [], []
    for rail in rails:
        for line in getattr(rail['centre'], 'geoms', [rail['centre']]):
            ss = np.arange(0.0, line.length, 4.0).tolist() + [line.length]
            sides = []                                     # per sample: (point, normal, dist left, dist right)
            for s in ss:
                p = line.interpolate(s)
                tx, ty = tangent(line, s)
                nx, ny = -ty, tx
                d = []
                for sgn in (1, -1):
                    ray = LineString([(p.x, p.y), (p.x + sgn * nx * CORRIDOR_MAX, p.y + sgn * ny * CORRIDOR_MAX)])
                    hits = []
                    for j in tree.query(ray):
                        rl = major[j]['line']
                        hit = ray.intersection(rl)
                        for h in getattr(hit, 'geoms', [hit]):
                            if h.is_empty or h.geom_type != 'Point':
                                continue
                            ux, uy = tangent(rl, rl.project(h))
                            if abs(ux * tx + uy * ty) > math.cos(math.radians(20)):   # parallel carriageway
                                hits.append(math.hypot(h.x - p.x, h.y - p.y))
                    # the carriageway (plus service lanes just past it), never a separate street further out
                    d.append(max([h for h in hits if h <= min(hits) + CORRIDOR_CLUSTER], default=0.0))
                sides.append([p, (nx, ny), d[0], d[1]])
            # fill short misses (a parallel road broken at a junction) from the neighbours, then median-filter
            for k in (2, 3):
                arr = np.array([s[k] for s in sides])
                for i in range(len(arr)):
                    if arr[i] == 0.0:
                        lo, hi = arr[max(0, i - 3):i], arr[i + 1:i + 4]
                        if (lo > 0).any() and (hi > 0).any():
                            arr[i] = max(lo.max(), hi.max())
                arr = np.array([np.median(arr[max(0, i - 2):i + 3]) for i in range(len(arr))])
                for s, v in zip(sides, arr):
                    s[k] = float(v)
            for a, b in zip(sides, sides[1:]):
                pa, (nax, nay), la, ra = a
                pb, (nbx, nby), lb, rb = b
                q = Polygon([(pa.x + nax * la, pa.y + nay * la), (pb.x + nbx * lb, pb.y + nby * lb),
                             (pb.x - nbx * rb, pb.y - nby * rb), (pa.x - nax * ra, pa.y - nay * ra)])
                if q.is_valid and q.area > 0.5:
                    quads.append(q)
            medians.append(line.buffer(MEDIAN_W / 2, cap_style='flat'))
    # closing fills notches left where the rays missed a carriageway at a junction
    corridor = unary_union(quads).buffer(8.0).buffer(-8.0) if quads else Polygon()
    median = unary_union(medians).intersection(surface.union(corridor)) if medians else Polygon()
    # junctions: cut the median where a main road crosses the line
    cuts = []
    for r in roads:
        if r['cls'] not in CROSS_CLS or r['layer'] > 0 or r['bridge'] or not r['line'].intersects(median):
            continue
        for rail in rails:
            for line in getattr(rail['centre'], 'geoms', [rail['centre']]):
                hit = r['line'].intersection(line)
                for h in getattr(hit, 'geoms', [hit]):
                    if h.is_empty or h.geom_type != 'Point':
                        continue
                    ux, uy = tangent(r['line'], r['line'].project(h))
                    tx, ty = tangent(line, line.project(h))
                    if abs(ux * tx + uy * ty) < math.cos(math.radians(30)):
                        cuts.append(r['line'].buffer(r['width'] / 2 + 3.0, cap_style='flat'))
                        break
    if cuts:
        median = median.difference(unary_union(cuts))
    median = unary_union([p for p in polygons_of(median) if p.area / MEDIAN_W >= 6.0] or [Polygon()])
    median = median.simplify(0.2)
    print(f"[metro] corridor {corridor.area:.0f} m2, median {median.area / MEDIAN_W:.0f} m long, "
          f"{len(cuts)} junction cuts")
    return corridor, median
