"""Road centrelines -> carriageway / sidewalk surfaces, hand-edited sidewalks, corner fillets, kerb lines."""
import math
import numpy as np
from collections import defaultdict

import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

from .config import KERB_W, SIDEWALK
from .osm import polygons_of, to_float, way_coords


# carriageway width (m) per highway class; None = not a road for us
ROAD_WIDTH = {
    'motorway': 22, 'trunk': 20, 'primary': 16, 'secondary': 12, 'tertiary': 9,
    'motorway_link': 7, 'trunk_link': 7, 'primary_link': 7, 'secondary_link': 7, 'tertiary_link': 6,
    'unclassified': 7, 'residential': 6, 'living_street': 5, 'pedestrian': 5, 'service': 3.5,
}
SERVICE_SKIP = {'parking_aisle', 'drive-through'}
KERB_R = 3.0              # m: kerb fillet radius at street corners
KERB_FILLET_MAX = 8.0     # m2: closing pieces bigger than this are narrow medians, not corners


def build_roads(ways, nodes, area, overrides, flags):
    roads = []
    for wid, (refs, tags) in ways.items():
        cls = tags.get('highway')
        if cls not in ROAD_WIDTH:
            continue
        if cls == 'service' and tags.get('service') in SERVICE_SKIP:
            continue
        if tags.get('area') == 'yes':
            continue
        coords = way_coords(refs, nodes)
        if len(coords) < 2:
            continue
        width = ROAD_WIDTH[cls]
        lanes = to_float(tags.get('lanes'))
        if lanes:
            width = max(lanes * 3.25, 3.0)
        w_tag = to_float(tags.get('width'))
        if w_tag and 2.0 <= w_tag <= 60.0:
            width = w_tag
        layer = int(to_float(tags.get('layer')) or 0)
        bridge = tags.get('bridge') not in (None, 'no')
        tunnel = tags.get('tunnel') not in (None, 'no')
        ow = tags.get('oneway')
        oneway = 1 if ow in ('yes', '1', 'true') or tags.get('junction') in ('roundabout', 'circular') else \
            -1 if ow == '-1' else 0        # +1 = along the way, -1 = against it, 0 = both ways (traffic lanes)
        roads.append(dict(id=wid, cls=cls, width=width, lanes=lanes, oneway=oneway, layer=layer, bridge=bridge,
                          tunnel=tunnel, refs=refs, line=LineString(coords), name=tags.get('name', '')))

    # overrides
    for props, g in overrides:
        op = props.get('op')
        if op == 'road':
            targets = [r for r in roads if str(r['id']) == str(props.get('osm_id'))] if props.get('osm_id') \
                else [r for r in roads if r['line'].distance(g) < 3.0 and r['line'].hausdorff_distance(g) < 15.0]
            for r in targets:
                if props.get('drop'):
                    r['drop'] = True
                if props.get('width'):
                    r['width'] = float(props['width'])
                if props.get('lanes'):
                    r['width'] = float(props['lanes']) * 3.25
        elif op == 'road_add' and isinstance(g, LineString):
            cls = props.get('class', 'residential')
            roads.append(dict(id=f"add{len(roads)}", cls=cls, width=float(props.get('width', ROAD_WIDTH.get(cls, 6))),
                              lanes=None, oneway=0, layer=0, bridge=False, tunnel=False, refs=[], line=g, name='override'))
    roads = [r for r in roads if not r.get('drop') and not r['tunnel']]

    # topology: degree of each endpoint node; snap dangling ends onto nearby roads
    degree = defaultdict(int)
    for r in roads:
        for ref in r['refs']:
            degree[ref] += 1
    tree = STRtree([r['line'] for r in roads])
    snapped = dropped = 0
    for i, r in enumerate(roads):
        if not r['refs']:
            continue
        coords = list(r['line'].coords)
        for end in (0, -1):
            if degree[r['refs'][end]] > 1:
                continue
            p = Point(coords[end])
            best, bd = None, 3.0
            for j in tree.query(p.buffer(3.0)):
                if j == i:
                    continue
                d = roads[j]['line'].distance(p)
                if 0.05 < d < bd:
                    best, bd = j, d
            if best is not None:
                q = roads[best]['line'].interpolate(roads[best]['line'].project(p))
                if end == 0:
                    coords.insert(0, (q.x, q.y))
                else:
                    coords.append((q.x, q.y))
                snapped += 1
        r['line'] = LineString(coords)
    # short dangling service stubs
    keep = []
    for r in roads:
        dead = r['refs'] and (degree[r['refs'][0]] <= 1 or degree[r['refs'][-1]] <= 1)
        if r['cls'] == 'service' and dead and r['line'].length < 8.0:
            dropped += 1
            continue
        r['line'] = r['line'].simplify(0.3)
        keep.append(r)
    roads = keep

    ground = [r for r in roads if r['layer'] <= 0 and not r['bridge']]
    elevated = [r for r in roads if r not in ground]
    surface = unary_union([r['line'].buffer(r['width'] / 2, cap_style='flat', join_style='round') for r in ground]
                          + [r['line'].buffer(r['width'] / 2, cap_style='round') for r in ground if r['cls'] != 'service']
                          ).intersection(area)
    # elevated roads: nothing may be built underneath either
    under = unary_union([r['line'].buffer(r['width'] / 2) for r in elevated]).intersection(area) if elevated else Polygon()
    walks = unary_union([r['line'].buffer(r['width'] / 2 + SIDEWALK.get(r['cls'], 0), cap_style='flat')
                         for r in ground if SIDEWALK.get(r['cls'], 0) > 0]).intersection(area)
    sidewalk = walks.difference(surface)
    surface = surface.union(under.difference(sidewalk))
    print(f"[roads] {len(roads)} roads ({len(elevated)} elevated), snapped {snapped} ends, dropped {dropped} stubs")
    return roads, surface, sidewalk


def sidewalk_overrides(surface, sidewalk, overrides, area):
    n = 0
    for props, g in overrides:
        if props.get('op') != 'sidewalk' or g.geom_type not in ('Polygon', 'MultiPolygon'):
            continue
        g = g.intersection(area)
        if props.get('mode', 'add') == 'cut':
            surface = surface.union(g.intersection(sidewalk))
            sidewalk = sidewalk.difference(g)
        else:
            sidewalk = sidewalk.union(g)
            surface = surface.difference(g)
        n += 1
    if n:
        print(f"[sidewalk] {n} overrides applied")
    return surface, sidewalk


def fillet_corners(surface, sidewalk):
    """Round the kerb at street corners: concave corners of the road surface (closing with radius
    KERB_R) are filled where they eat into the sidewalk. Big pieces are narrow medians -> kept."""
    closed = surface.buffer(KERB_R, quad_segs=6).buffer(-KERB_R, quad_segs=6)
    gaps = closed.difference(surface).intersection(sidewalk)
    keep, big = [], 0
    for p in polygons_of(gaps):
        if p.area < 0.05 or p.buffer(-0.05).is_empty:      # slivers along straight edges
            continue
        if p.area > KERB_FILLET_MAX:
            big += 1
            continue
        keep.append(p)
    fill = unary_union(keep) if keep else Polygon()
    surface, sidewalk = surface.union(fill), sidewalk.difference(fill)
    # slivers thinner than 2 kerb widths (left by flat road caps / fillets) become road: no stray kerbs
    opened = sidewalk.buffer(-KERB_W, quad_segs=2).buffer(KERB_W, quad_segs=2).intersection(sidewalk)
    opened = unary_union([p for p in polygons_of(opened) if p.area >= 1.0] or [Polygon()])
    thin = sidewalk.difference(opened)
    print(f"[kerb] {len(keep)} corner fillets (R {KERB_R} m), {big} large pieces left as sidewalk, "
          f"{thin.area:.0f} m2 of slivers -> road")
    return surface.union(thin), opened


def kerb_lines(surface, sidewalk):
    """Sidewalk outline split into kerbs (against the road, oriented with the road on the right)
    and skirts (against block ground / green / water: a plain vertical side)."""
    near_road = surface.buffer(0.05)
    shapely.prepare(surface)
    bnd = sidewalk.boundary
    kerb = linemerge(bnd.intersection(near_road))
    skirt = bnd.difference(near_road)
    kerbs = []
    for l in getattr(kerb, 'geoms', [kerb]):
        if l.geom_type != 'LineString' or l.length < 0.3:
            continue
        l = l.simplify(0.02)
        c = list(l.coords)
        # vote over a few segments: probe 10 cm right of the line must hit the road
        votes = 0
        for i in np.linspace(0, len(c) - 2, min(len(c) - 1, 5)).astype(int).tolist():
            (ax, ay), (bx, by) = c[i], c[i + 1]
            d = math.hypot(bx - ax, by - ay) or 1.0
            mx, my = (ax + bx) / 2 + (by - ay) / d * 0.1, (ay + by) / 2 - (bx - ax) / d * 0.1
            votes += 1 if surface.contains(Point(mx, my)) else -1
        kerbs.append(LineString(c[::-1]) if votes < 0 else l)
    skirts = []
    for l in getattr(skirt, 'geoms', [skirt]):
        if l.geom_type != 'LineString' or l.length < 0.05:
            continue
        c = list(l.coords)                       # oriented with the sidewalk on the LEFT (wall faces right / outwards)
        votes = 0
        for i in np.linspace(0, len(c) - 2, min(len(c) - 1, 5)).astype(int).tolist():
            (ax, ay), (bx, by) = c[i], c[i + 1]
            d = math.hypot(bx - ax, by - ay) or 1.0
            mx, my = (ax + bx) / 2 - (by - ay) / d * 0.1, (ay + by) / 2 + (bx - ax) / d * 0.1
            votes += 1 if sidewalk.contains(Point(mx, my)) else -1
        skirts.append(LineString(c[::-1]) if votes < 0 else l)
    walk_top = sidewalk.difference(unary_union([k.buffer(KERB_W, cap_style='flat', join_style='mitre', mitre_limit=2.0)
                                                for k in kerbs])) if kerbs else sidewalk
    print(f"[kerb] {len(kerbs)} kerb lines {sum(k.length for k in kerbs) / 1000:.1f} km, "
          f"{len(skirts)} skirts {sum(s.length for s in skirts) / 1000:.1f} km")
    return kerbs, skirts, walk_top
