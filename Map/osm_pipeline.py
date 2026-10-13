"""M2: OpenStreetMap -> clean city layout (Map/city.json) + error report.

OSM is only a *hint*: building shapes come from the variant library, roads are rebuilt from
centrelines + a width table, tube houses are infilled along block frontages. Dirty OSM data can
therefore only shift lots, never break geometry.

    python Map/osm_pipeline.py [Map/raw/thanhxuan.osm]

Outputs (Map/out/):
  city.json           layout for Unity (metres, x = east, y = north, origin = centre of the bounds)
  report.png          map of the result; red = needs a human decision
  report.json         the same flags as a list
  *.geojson           cleaned layers in WGS84, to view/fix in QGIS

Manual fixes: Map/overrides.geojson (WGS84, edit in QGIS). Feature property "op":
  road         LineString near an OSM road, or {"osm_id": id}: {"width": m} or {"lanes": n}; "drop": true removes it
  road_add     LineString: new road, {"width": m, "class": "residential"}
  no_build     Polygon: nothing is placed inside (parks, yards, stations...)
  building     Polygon: big building replacing OSM ones it overlaps, {"levels": n}
  delete       Polygon: removes OSM big buildings intersecting it
  sidewalk     Polygon, {"mode": "add"}: becomes sidewalk (taken from road or block, nothing is built on it);
               {"mode": "cut"}: sidewalk inside becomes road surface. Kerbs follow the edited shape.
  tree         Point: adds a tree ({"species": "Sau" | "XaCu" | "Bang" | "HoaSua", "scale": 1.0} optional);
               Polygon: removes every generated tree inside (see out/trees.geojson).
Overrides are applied after the automatic steps, so re-downloading OSM keeps them.
"""
import json, math, os, random, sys, zlib, xml.etree.ElementTree as ET
import numpy as np
from collections import defaultdict

import shapely
import shapely.prepared
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import linemerge, nearest_points, polygonize, unary_union
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
OVERRIDES = os.path.join(HERE, "overrides.geojson")
CHUNK = 200.0

# carriageway width (m) per highway class; None = not a road for us
ROAD_WIDTH = {
    'motorway': 22, 'trunk': 20, 'primary': 16, 'secondary': 12, 'tertiary': 9,
    'motorway_link': 7, 'trunk_link': 7, 'primary_link': 7, 'secondary_link': 7, 'tertiary_link': 6,
    'unclassified': 7, 'residential': 6, 'living_street': 5, 'pedestrian': 5, 'service': 3.5,
}
SIDEWALK = {  # sidewalk width each side
    'motorway': 0, 'trunk': 4, 'primary': 4, 'secondary': 3.5, 'tertiary': 3, 'unclassified': 2,
    'residential': 1.5, 'living_street': 0, 'pedestrian': 0, 'service': 0,
}
SERVICE_SKIP = {'parking_aisle', 'drive-through'}
OPEN_TAGS = {
    'leisure': {'park', 'garden', 'pitch', 'playground', 'stadium', 'recreation_ground', 'swimming_pool'},
    'landuse': {'grass', 'cemetery', 'recreation_ground', 'religious', 'village_green', 'meadow'},
    'amenity': {'parking'},
}
WATER_TAGS = {'natural': {'water'}, 'landuse': {'reservoir', 'basin'}, 'waterway': {'riverbank'}}

RAIL_TYPES = {'subway', 'light_rail'}
MEDIAN_W = 5.0            # m: pier + planter-frame zone under an elevated metro (still asphalt for now)
RAIL_CLEAR = 4.0          # m each side of an elevated line: never built on
CORRIDOR_MAX = 36.0       # m: furthest parallel carriageway swallowed into the metro corridor
CORRIDOR_CLUSTER = 12.0   # m: parallel roads this far past the nearest one still count (service lanes in the median)
CORRIDOR_CLS = {'motorway', 'trunk', 'primary', 'secondary'}
CROSS_CLS = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary',
             'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'}

# street cross-section, exported as city.json "street" so Unity builds the same shape
ROAD_Y = 0.02             # m: carriageway above the block ground
KERB_H = 0.20             # m: sidewalk top above the carriageway
KERB_LIP = 0.045          # m: vertical lip of the kerb on the road side
KERB_ANGLE = 30.0         # deg: sloped kerb face (Ref/sideway.png)
KERB_W = round((KERB_H - KERB_LIP) / math.tan(math.radians(KERB_ANGLE)), 3)   # ~0.27 m
KERB_STONE = 1.0          # m: kerb stone length (texture joints)
KERB_BULGE = 0.01         # m: the sloped face is slightly convex
KERB_R = 3.0              # m: kerb fillet radius at street corners
KERB_VIEWS = [(-641, 294), (-381, -69)]   # report_kerb_<i>.png centres: a tertiary junction, Nguyen Trai x metro
KERB_FILLET_MAX = 8.0     # m2: closing pieces bigger than this are narrow medians, not corners
# (across, up) from the top of the sidewalk side to the road; across 0 = road edge, negative = sidewalk side
KERB_PROFILE = [(round(-KERB_W * (1 - t), 4),
                 round(KERB_H - (KERB_H - KERB_LIP) * t + KERB_BULGE * math.sin(math.pi * t), 4))
                for t in (0.0, 1 / 3, 2 / 3, 1.0)] + [(0.0, 0.0)]

BIG_AREA = 250.0         # m2: footprints at least this big are kept as "big buildings"
BIG_LEVELS = 6            # ... or this many floors
LOT_DEPTH = 12.0          # matches the tube-house library depth
LOT_MIN, LOT_MAX = 3.5, 5.0
FLOOR_H = 3.2


# ---------------------------------------------------------------- parsing / projection
class Proj:
    def __init__(self, minlat, minlon, maxlat, maxlon):
        self.lat0, self.lon0 = (minlat + maxlat) / 2, (minlon + maxlon) / 2
        self.kx = 111320.0 * math.cos(math.radians(self.lat0))
        self.ky = 110540.0

    def fwd(self, lat, lon):
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)

    def inv(self, x, y):
        return (self.lon0 + x / self.kx, self.lat0 + y / self.ky)   # GeoJSON order lon, lat


def parse_osm(path):
    tree = ET.parse(path)
    root = tree.getroot()
    b = root.find('bounds')
    proj = Proj(*(float(b.get(k)) for k in ('minlat', 'minlon', 'maxlat', 'maxlon')))
    nodes = {}
    for n in root.iter('node'):
        nodes[n.get('id')] = proj.fwd(float(n.get('lat')), float(n.get('lon')))
    ways = {}
    for w in root.iter('way'):
        refs = [nd.get('ref') for nd in w.iter('nd')]
        tags = {t.get('k'): t.get('v') for t in w.iter('tag')}
        ways[w.get('id')] = (refs, tags)
    rels = []
    for r in root.iter('relation'):
        tags = {t.get('k'): t.get('v') for t in r.iter('tag')}
        members = [(m.get('type'), m.get('ref'), m.get('role')) for m in r.iter('member')]
        rels.append((r.get('id'), members, tags))
    x0, y0 = proj.fwd(float(b.get('minlat')), float(b.get('minlon')))
    x1, y1 = proj.fwd(float(b.get('maxlat')), float(b.get('maxlon')))
    return proj, box(x0, y0, x1, y1), nodes, ways, rels


def way_coords(refs, nodes):
    return [nodes[r] for r in refs if r in nodes]


def tag_match(tags, table):
    return any(tags.get(k) in vs for k, vs in table.items())


def polygons_of(geom):
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [g for g in getattr(geom, 'geoms', []) if isinstance(g, Polygon)]


class Tiled:
    """A huge geometry (the whole street network is one polygon) cut into grid tiles with an
    STRtree, so per-building / per-lot queries only touch the few tiles nearby."""

    def __init__(self, geom, origin, cell=100.0):
        self.tiles = []
        if geom is not None and not geom.is_empty:
            x0, y0 = origin
            gx0, gy0, gx1, gy1 = geom.bounds
            i0, j0 = math.floor((gx0 - x0) / cell), math.floor((gy0 - y0) / cell)
            i1, j1 = math.ceil((gx1 - x0) / cell), math.ceil((gy1 - y0) / cell)
            cells = [box(x0 + i * cell, y0 + j * cell, x0 + (i + 1) * cell, y0 + (j + 1) * cell)
                     for j in range(j0, j1) for i in range(i0, i1)]
            pieces = shapely.intersection(geom, cells)
            self.tiles = [p for p in pieces if not p.is_empty]
        self.tree = STRtree(self.tiles)
        for t in self.tiles:
            shapely.prepare(t)

    def _idx(self, g):
        return self.tree.query(g) if self.tiles else []

    def near(self, g):
        idx = self._idx(g)
        return unary_union([self.tiles[i] for i in idx]) if len(idx) else Polygon()

    def area_in(self, g):
        return sum(self.tiles[i].intersection(g).area for i in self._idx(g))

    def covers_point(self, pt):
        return any(self.tiles[i].covers(pt) for i in self._idx(pt))


def clean_poly(coords):
    if len(coords) < 4:
        return None
    try:
        g = shapely.make_valid(Polygon(coords))
    except Exception:
        return None
    polys = polygons_of(g)
    if not polys:
        return None
    return max(polys, key=lambda p: p.area)


def area_features(ways, rels, nodes, pred):
    """Closed ways + multipolygon relations whose tags satisfy pred -> [(id, polygon, tags)]."""
    out = []
    for wid, (refs, tags) in ways.items():
        if len(refs) > 3 and refs[0] == refs[-1] and pred(tags):
            p = clean_poly(way_coords(refs, nodes))
            if p is not None:
                out.append((f"w{wid}", p, tags))
    for rid, members, tags in rels:
        if tags.get('type') != 'multipolygon' or not pred(tags):
            continue
        lines = [LineString(way_coords(ways[ref][0], nodes)) for t, ref, role in members
                 if t == 'way' and role in ('outer', '') and ref in ways and len(ways[ref][0]) > 1]
        lines = [l for l in lines if len(l.coords) > 1]
        for p in polygonize(linemerge(lines) if lines else []):
            p = shapely.make_valid(p)
            for q in polygons_of(p):
                out.append((f"r{rid}", q, tags))
    return out


def to_float(v):
    try:
        return float(str(v).split(';')[0].replace(',', '.').replace('m', '').strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- overrides
def load_overrides(proj):
    if not os.path.exists(OVERRIDES):
        return []
    with open(OVERRIDES, encoding='utf-8') as f:
        fc = json.load(f)
    out = []
    for feat in fc.get('features', []):
        g = shape(feat['geometry'])
        g = shapely.transform(g, lambda c: np.array([proj.fwd(lat, lon) for lon, lat in c]))  # lon,lat -> x,y
        out.append((feat.get('properties', {}) or {}, g))
    return out


# ---------------------------------------------------------------- roads
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
        roads.append(dict(id=wid, cls=cls, width=width, lanes=lanes, layer=layer, bridge=bridge,
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
                              lanes=None, layer=0, bridge=False, tunnel=False, refs=[], line=g, name='override'))
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


# ---------------------------------------------------------------- elevated metro
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


def _tangent(line, s, h=1.5):
    p0, p1 = line.interpolate(max(s - h, 0.0)), line.interpolate(min(s + h, line.length))
    dx, dy = p1.x - p0.x, p1.y - p0.y
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


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
                tx, ty = _tangent(line, s)
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
                            ux, uy = _tangent(rl, rl.project(h))
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
                    ux, uy = _tangent(r['line'], r['line'].project(h))
                    tx, ty = _tangent(line, line.project(h))
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



# ---------------------------------------------------------------- big buildings
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


# ---------------------------------------------------------------- tube house lots
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


# ---------------------------------------------------------------- sidewalks + kerbs
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


# ---------------------------------------------------------------- street trees
TREE_SPECIES = ['Sau', 'XaCu', 'Bang', 'HoaSua']      # index = species id in city.json (TR_<name>_0 prefabs)
TREE_CROWN = {'Sau': 3.0, 'XaCu': 5.0, 'Bang': 4.6, 'HoaSua': 5.9}   # fallback; Export/Trees/trees.json wins
TREE_FROM_KERB = 0.9      # m: trunk behind the kerb line, on the sidewalk
TREE_STEP = 10.0          # m between street trees (+- TREE_JITTER)
TREE_JITTER = 1.5
TREE_GAP = 0.10           # share of empty pits
TREE_MIN_WALK = 2.5       # m: sidewalk at least this wide behind the kerb
TREE_CORNER = (5.0, 0.47) # disk radius, max share of road surface in it (straight kerb ~0.37, corner > 0.5)
TREE_OVERLAP = 2.0        # m: crown may reach this far past the facade line (balconies, pruned branches)
TREE_MIN_SCALE = 0.75
TREE_MAIN_SHARE = 0.8     # street trees of a street's main species
TREE_PARK_GAP = 9.0       # m: min distance between park trees
TREE_PARK_EDGE = 2.0      # m: park trees stay this far inside the green area


def tree_crowns():
    p = os.path.join(os.path.dirname(HERE), "Export", "Trees", "trees.json")
    crowns = dict(TREE_CROWN)
    if os.path.exists(p):
        for t in json.load(open(p, encoding='utf-8')).get('trees', []):
            crowns[t['species']] = t['crown_r'] + 0.5          # shell radius + the cards sticking out
    return [crowns[s] for s in TREE_SPECIES]


def place_trees(kerbs, roads, surface, sidewalk, open_, lots, big, origin, overrides, seed=11):
    """Street trees along the kerbs (sidewalk side) + loose trees in the green areas.
    Returns [dict(x, y, sp, yaw, scale, kind)] (kind 0 = street, 1 = park) and stats."""
    crowns = tree_crowns()
    surface_t, walk_t = Tiled(surface, origin), Tiled(sidewalk, origin)
    built = [l['rect'] for l in lots] + [b['rect'] for b in big]
    built_tree = STRtree(built)
    road_lines = [r['line'] for r in roads]
    road_tree = STRtree(road_lines)
    trees, stats = [], defaultdict(int)
    grid = defaultdict(list)                                   # 10 m hash of placed trunks

    def free(x, y, d):
        k = (int(x // 10), int(y // 10))
        return all(math.hypot(x - a, y - b) >= d for i in (-1, 0, 1) for j in (-1, 0, 1)
                   for a, b in grid[(k[0] + i, k[1] + j)])

    def add(x, y, sp, yaw, scale, kind):
        trees.append(dict(x=round(x, 2), y=round(y, 2), sp=sp, yaw=round(yaw, 1), scale=round(scale, 3), kind=kind))
        grid[(int(x // 10), int(y // 10))].append((x, y))

    def facade_dist(pt):
        i = built_tree.nearest(pt)
        return built[i].distance(pt) if i is not None else 99.0

    def fit(sp_order, room, rng):
        """First species whose crown fits the room (scaled down to TREE_MIN_SCALE at most)."""
        for sp in sp_order:
            s = min(rng.uniform(0.85, 1.15), room / crowns[sp])
            if s >= TREE_MIN_SCALE:
                return sp, s
        return None, 0.0

    # ---- along the kerbs (road on the right -> sidewalk on the left)
    for li, k in enumerate(kerbs):
        L = k.length
        if L < 8.0:
            stats['kerb_short'] += 1
            continue
        mid = k.interpolate(0.5, normalized=True)
        ri = road_tree.nearest(mid)
        name = roads[ri]['name'] or f"#{roads[ri]['id']}"
        rng = random.Random(zlib.crc32(f"{seed}/{li}".encode()))
        main = zlib.crc32(name.encode('utf-8')) % len(TREE_SPECIES)
        s = rng.uniform(2.0, TREE_STEP)
        while s < L - 2.0:
            a, b = k.interpolate(max(s - 0.5, 0)), k.interpolate(min(s + 0.5, L))
            dx, dy = b.x - a.x, b.y - a.y
            n = math.hypot(dx, dy) or 1.0
            lx, ly = -dy / n, dx / n                                # left normal = into the sidewalk
            p = k.interpolate(s)
            x, y = p.x + lx * TREE_FROM_KERB, p.y + ly * TREE_FROM_KERB
            s += TREE_STEP + rng.uniform(-TREE_JITTER, TREE_JITTER)
            pt = Point(x, y)
            if rng.random() < TREE_GAP:
                stats['gap'] += 1; continue
            if not walk_t.covers_point(Point(p.x + lx * TREE_MIN_WALK, p.y + ly * TREE_MIN_WALK)) or not walk_t.covers_point(pt):
                stats['narrow'] += 1; continue
            disk = pt.buffer(TREE_CORNER[0], quad_segs=4)
            if surface_t.area_in(disk) / disk.area > TREE_CORNER[1]:
                stats['corner'] += 1; continue
            fd = facade_dist(pt)
            if fd < 0.6:
                stats['in_lot'] += 1; continue
            if not free(x, y, 6.0):
                stats['crowded'] += 1; continue
            order = [main] if rng.random() < TREE_MAIN_SHARE else [rng.randrange(len(TREE_SPECIES))]
            order += sorted(range(len(TREE_SPECIES)), key=lambda i: crowns[i])     # fallback: smallest crown first
            sp, scale = fit(order, fd + TREE_OVERLAP, rng)
            if sp is None:
                stats['no_room'] += 1; continue
            stats['shrunk'] += scale < 0.85
            add(x, y, sp, rng.uniform(0, 360), scale, 0)

    # ---- green areas: Poisson darts
    rng = random.Random(seed)
    for gi, g in enumerate(polygons_of(open_)):
        inner = g.buffer(-TREE_PARK_EDGE)
        if inner.is_empty or inner.area < 30:
            continue
        prepared = shapely.prepared.prep(inner)
        gx0, gy0, gx1, gy1 = inner.bounds
        for _ in range(int(inner.area / 15) + 5):
            x, y = rng.uniform(gx0, gx1), rng.uniform(gy0, gy1)
            pt = Point(x, y)
            if not prepared.contains(pt) or not free(x, y, TREE_PARK_GAP):
                continue
            fd = facade_dist(pt)
            if fd < 1.0:
                continue
            sp, scale = fit(rng.sample(range(len(TREE_SPECIES)), len(TREE_SPECIES)), fd + TREE_OVERLAP + 1.0, rng)
            if sp is not None:
                add(x, y, sp, rng.uniform(0, 360), scale * rng.uniform(0.95, 1.1), 1)

    # ---- overrides: op "tree" -> Point adds a tree ({"species": "Bang"} optional), Polygon removes trees
    cuts = [g for p, g in overrides if p.get('op') == 'tree' and g.geom_type in ('Polygon', 'MultiPolygon')]
    if cuts:
        cut = unary_union(cuts)
        before = len(trees)
        trees = [t for t in trees if not cut.contains(Point(t['x'], t['y']))]
        stats['override_cut'] = before - len(trees)
    for p, g in overrides:
        if p.get('op') == 'tree' and g.geom_type == 'Point':
            sp = TREE_SPECIES.index(p['species']) if p.get('species') in TREE_SPECIES else rng.randrange(len(TREE_SPECIES))
            trees.append(dict(x=round(g.x, 2), y=round(g.y, 2), sp=sp, yaw=round(rng.uniform(0, 360), 1),
                              scale=float(p.get('scale', 1.0)), kind=2))
            stats['override_add'] += 1

    by_sp = defaultdict(int)
    for t in trees:
        by_sp[TREE_SPECIES[t['sp']]] += 1
    print(f"[trees] {sum(t['kind'] == 0 for t in trees)} street + {sum(t['kind'] == 1 for t in trees)} park "
          f"+ {sum(t['kind'] == 2 for t in trees)} hand-placed; species {dict(by_sp)}; skipped {dict(stats)}")
    return trees


# ---------------------------------------------------------------- parked motorbikes
# User: a moderate number, never the whole sidewalk -> only some shop fronts get a small cluster,
# parked across the sidewalk against the facade, and a clear walkway is always left in front.
MOTO_LOT_SHARE = 0.30     # share of tube-house fronts with bikes
MOTO_CLUSTER = [(1, 0.35), (2, 0.35), (3, 0.20), (4, 0.10)]   # bikes per front, weights
MOTO_PITCH = 0.80         # m between neighbouring bikes (SH: 0.71 m wide incl. mirrors)
MOTO_LEN, MOTO_W = 2.0, 0.72
MOTO_FROM_FACADE = 0.35   # m between the facade and the bike's end
MOTO_CLEAR = 1.2          # m of free walkway left between the bikes and the kerb / sidewalk end
MOTO_TREE_CLEAR = 0.8     # m from a tree trunk to the bike's footprint
MOTO_NOSE_IN = 0.7        # share parked nose towards the house
MOTO_YAW_JITTER = 7.0     # deg


def place_motos(lots, walk_top, surface, trees, origin, overrides, seed=23):
    """Parked bikes in front of tube houses. Returns [dict(x, y, yaw)] (yaw: Unity degrees,
    0 = bike front towards +y / north, clockwise seen from above)."""
    walk_t, surface_t = Tiled(walk_top, origin), Tiled(surface, origin)
    tgrid = defaultdict(list)
    for t in trees:
        tgrid[(int(t['x'] // 10), int(t['y'] // 10))].append((t['x'], t['y']))

    def near_tree(x, y, d):
        k = (int(x // 10), int(y // 10))
        return any(math.hypot(x - a, y - b) < d for i in (-1, 0, 1) for j in (-1, 0, 1)
                   for a, b in tgrid[(k[0] + i, k[1] + j)])

    motos, stats = [], defaultdict(int)
    sizes, weights = zip(*MOTO_CLUSTER)
    for li, l in enumerate(lots):
        rng = random.Random(zlib.crc32(f"{seed}/{li}".encode()))
        if rng.random() > MOTO_LOT_SHARE:
            continue
        nx, ny = l['front']
        tx, ty = -ny, nx                                      # along the facade
        n = min(rng.choices(sizes, weights)[0], int((l['width'] - 0.3) // MOTO_PITCH))
        if n < 1:
            stats['narrow_lot'] += 1; continue
        d_mid = MOTO_FROM_FACADE + MOTO_LEN / 2
        # the whole band (bikes + walkway) must be sidewalk, else skip this front (alleys, narrow walks)
        far = MOTO_FROM_FACADE + MOTO_LEN + MOTO_CLEAR
        if not all(walk_t.covers_point(Point(l['cx'] + nx * d + tx * o, l['cy'] + ny * d + ty * o))
                   for d in (MOTO_FROM_FACADE + 0.05, d_mid, MOTO_FROM_FACADE + MOTO_LEN, far)
                   for o in (-l['width'] / 2 + 0.3, 0.0, l['width'] / 2 - 0.3)):
            stats['no_walk'] += 1; continue
        cpt = Point(l['cx'] + nx * d_mid, l['cy'] + ny * d_mid)
        disk = cpt.buffer(5.0, quad_segs=4)
        if surface_t.area_in(disk) / disk.area > 0.47:       # street corner
            stats['corner'] += 1; continue
        shift = rng.uniform(-1, 1) * max(0.0, (l['width'] - 0.3 - n * MOTO_PITCH) / 2)
        nose_in = rng.random() < MOTO_NOSE_IN
        placed = 0
        for k in range(n):
            o = shift + (k - (n - 1) / 2) * MOTO_PITCH
            x, y = l['cx'] + nx * d_mid + tx * o, l['cy'] + ny * d_mid + ty * o
            if any(near_tree(x + nx * s, y + ny * s, MOTO_TREE_CLEAR + MOTO_W / 2)
                   for s in (-MOTO_LEN / 2, 0.0, MOTO_LEN / 2)):
                stats['tree'] += 1; continue
            fx, fy = (-nx, -ny) if nose_in else (nx, ny)
            yaw = math.degrees(math.atan2(fx, fy)) + rng.uniform(-MOTO_YAW_JITTER, MOTO_YAW_JITTER)
            motos.append(dict(x=round(x, 2), y=round(y, 2), yaw=round(yaw % 360, 1)))
            placed += 1
        stats['fronts'] += placed > 0

    # overrides: op "moto" -> Polygon removes bikes, Point adds one ({"yaw": deg} optional)
    cuts = [g for p, g in overrides if p.get('op') == 'moto' and g.geom_type in ('Polygon', 'MultiPolygon')]
    if cuts:
        cut = unary_union(cuts)
        before = len(motos)
        motos = [m for m in motos if not cut.contains(Point(m['x'], m['y']))]
        stats['override_cut'] = before - len(motos)
    for p, g in overrides:
        if p.get('op') == 'moto' and g.geom_type == 'Point':
            motos.append(dict(x=round(g.x, 2), y=round(g.y, 2), yaw=float(p.get('yaw', 0.0))))
            stats['override_add'] += 1
    print(f"[motos] {len(motos)} parked bikes in front of {stats['fronts']} houses "
          f"({len(lots)} lots); skipped {dict(stats)}")
    return motos


# ---------------------------------------------------------------- street props
# User (2026-10-13): "NGÕ" signs first, at sidewalk corners; power poles fewer; garbage carts rarer still.
PROP_KINDS = ['SignNgo', 'PowerPole', 'Cart']   # index = kind in city.json (HanoiProps prefabs)
ALLEY_CLS = {'service', 'residential', 'living_street', 'pedestrian', 'unclassified'}
ALLEY_MIN_LEN = 12.0      # m: shorter service ways are driveways
SIGN_SHARE = 0.85         # alley mouths with a sign
SIGN_FROM_EDGE = 0.45     # m: pole beside the alley edge, on the main street's sidewalk
SIGN_BEHIND_KERB = 0.45   # m: past the first sidewalk point seen from the junction
SIGN_CORNER_SHARE = 0.35  # plain street corners (kerb turning > SIGN_CORNER_DEG) with a sign too
SIGN_CORNER_DEG = 50.0
POLE_STEP = 55.0          # m between power poles along a kerb (+- POLE_JITTER)
POLE_JITTER = 8.0
POLE_KERB_SHARE = 0.55    # kerbs (street sides) that carry a pole line
POLE_FROM_KERB = 0.55     # m: pole axis behind the kerb line (kerb band 0.27 + radius 0.17 + gap)
POLE_MIN_WALK = 1.5
CART_MOUTH_SHARE = 0.12   # alley mouths used as a garbage collection point
CART_FROM_KERB = 1.0      # m: cart centre behind the kerb line, parallel to it
CART_MIN_WALK = 2.6
CART_KERB_EVERY = 700.0   # m of kerb per roadside cart (rare)
PROP_CLEAR = {'tree': 1.2, 'moto': 1.4, 'prop': 2.5}   # m from a prop to trunks / bikes / other props


def place_props(kerbs, roads, surface, walk_top, trees, motos, origin, overrides, seed=31):
    """Signs, power poles and garbage carts on the sidewalk. Returns [dict(x, y, kind, yaw)], yaw in
    Unity degrees (0 = the prefab's +Z towards north, clockwise from above). Prefab frames (FBX):
    sign = plate along local -X with the text facing +-Z; pole = box facing +Z; cart = front +Z."""
    walk_t, surface_t = Tiled(walk_top, origin), Tiled(surface, origin)
    grid = defaultdict(list)                                   # 10 m hash: (x, y, what)
    for t in trees:
        grid[(int(t['x'] // 10), int(t['y'] // 10))].append((t['x'], t['y'], 'tree'))
    for m in motos:
        grid[(int(m['x'] // 10), int(m['y'] // 10))].append((m['x'], m['y'], 'moto'))

    def free(x, y, extra=0.0):
        k = (int(x // 10), int(y // 10))
        return all(math.hypot(x - a, y - b) >= PROP_CLEAR[w] + extra
                   for i in (-1, 0, 1) for j in (-1, 0, 1) for a, b, w in grid[(k[0] + i, k[1] + j)])

    props, stats = [], defaultdict(int)

    def add(x, y, kind, yaw):
        props.append(dict(x=round(x, 2), y=round(y, 2), kind=kind, yaw=round(yaw % 360, 1)))
        grid[(int(x // 10), int(y // 10))].append((x, y, 'prop'))

    def yaw_of(vx, vy):                                        # prefab +Z along (vx, vy)
        return math.degrees(math.atan2(vx, vy))

    def on_walk(x, y, r):
        return all(walk_t.covers_point(Point(x + dx, y + dy)) for dx, dy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)))

    # ---- alley mouths: sign on the sidewalk corner beside the alley edge (and now and then a cart)
    main_roads = [r for r in roads if SIDEWALK.get(r['cls'], 0) >= 1.5 and r['cls'] not in ALLEY_CLS]
    main_tree = STRtree([r['line'] for r in main_roads])
    mouths = 0
    for ai, a in enumerate(roads):
        if a['cls'] not in ALLEY_CLS or a['line'].length < ALLEY_MIN_LEN:
            continue
        coords = list(a['line'].coords)
        for end in (0, 1):
            ex, ey = coords[0] if end == 0 else coords[-1]
            inner = a['line'].interpolate(3.0 if end == 0 else a['line'].length - 3.0)
            dx, dy = inner.x - ex, inner.y - ey
            n = math.hypot(dx, dy) or 1.0
            dx, dy = dx / n, dy / n                            # into the alley
            mi = main_tree.nearest(Point(ex, ey))
            if mi is None:
                continue
            m = main_roads[mi]
            if m['line'].distance(Point(ex, ey)) > m['width'] / 2 + 2.0:
                continue                                       # not a junction with a street that has a sidewalk
            mouths += 1
            rng = random.Random(zlib.crc32(f"{seed}/mouth/{ai}/{end}".encode()))
            sides = [1, -1] if rng.random() < 0.5 else [-1, 1]
            spots = {}
            for side in sides:                                 # first sidewalk point walking into the alley
                nx_, ny_ = -dy * side, dx * side
                off = a['width'] / 2
                for k in range(0, 100):
                    t = k * 0.25
                    x, y = ex + dx * t + nx_ * (off + SIGN_FROM_EDGE), ey + dy * t + ny_ * (off + SIGN_FROM_EDGE)
                    if walk_t.covers_point(Point(x, y)):
                        t += SIGN_BEHIND_KERB
                        spots[side] = (t, nx_, ny_, off)
                        break
            if not spots:
                stats['mouth_no_walk'] += 1
                continue
            placed_sign = None
            if rng.random() < SIGN_SHARE:
                # the kerb is filleted (R 3 m) at the mouth: step a little further in / away from the edge
                tries = [(dt, de) for dt in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0) for de in (0.0, 0.3, 0.7)]
                for side in sides:
                    if side not in spots or placed_sign is not None:
                        continue
                    t, nx_, ny_, off = spots[side]
                    for dt, de in tries:
                        e = off + SIGN_FROM_EDGE + de
                        x, y = ex + dx * (t + dt) + nx_ * e, ey + dy * (t + dt) + ny_ * e
                        if on_walk(x, y, 0.25) and free(x, y):
                            add(x, y, 0, yaw_of(dy, -dx))    # plate along the alley, pointing into it
                            placed_sign = side
                            stats['sign_mouth'] += 1
                            break
                if placed_sign is None:
                    stats['sign_blocked'] += 1
            if rng.random() < CART_MOUTH_SHARE:                # collection point: cart on the other corner
                done = False
                for side in sorted(spots, key=lambda s: s == placed_sign):
                    t, nx_, ny_, off = spots[side]
                    for dt in (0.6, 1.2, 2.0, 3.0):
                        x, y = ex + dx * (t + dt) + nx_ * (off + 1.4), ey + dy * (t + dt) + ny_ * (off + 1.4)
                        # parallel to the main street, i.e. across the alley direction
                        if on_walk(x, y, 0.9) and free(x, y, 0.5):
                            add(x, y, 2, yaw_of(nx_, ny_) + rng.uniform(-8, 8))
                            stats['cart_mouth'] += 1
                            done = True
                            break
                    if done:
                        break

    # ---- plain street corners (kerb turning sharply): a sign now and then
    for li, k in enumerate(kerbs):
        L = k.length
        if L < 6.0:
            continue
        rng = random.Random(zlib.crc32(f"{seed}/corner/{li}".encode()))

        def heading(s):
            a, b = k.interpolate(max(s - 1.5, 0)), k.interpolate(min(s + 1.5, L))
            return math.atan2(b.y - a.y, b.x - a.x)
        s, last = 3.0, -99.0
        while s < L - 3.0:
            turn = math.degrees((heading(s + 2.5) - heading(s - 2.5) + math.pi) % (2 * math.pi) - math.pi)
            if abs(turn) > SIGN_CORNER_DEG and s - last > 10.0:
                last = s
                if rng.random() < SIGN_CORNER_SHARE:
                    p = k.interpolate(s)
                    h = heading(s)
                    lx, ly = -math.sin(h), math.cos(h)          # left normal = into the sidewalk
                    x, y = p.x + lx * (KERB_W + 0.5), p.y + ly * (KERB_W + 0.5)
                    if on_walk(x, y, 0.25) and free(x, y):
                        ha = heading(s - 2.5)                  # plate along the incoming street
                        add(x, y, 0, yaw_of(math.sin(ha), -math.cos(ha)))
                        stats['sign_corner'] += 1
                s += 3.0
            s += 1.0

    # ---- power poles along some kerbs, box towards the road
    for li, k in enumerate(kerbs):
        L = k.length
        rng = random.Random(zlib.crc32(f"{seed}/pole/{li}".encode()))
        if L < 20.0 or rng.random() > POLE_KERB_SHARE:
            continue
        s = rng.uniform(5.0, POLE_STEP / 2)
        while s < L - 5.0:
            a, b = k.interpolate(max(s - 0.5, 0)), k.interpolate(min(s + 0.5, L))
            tx, ty = b.x - a.x, b.y - a.y
            n = math.hypot(tx, ty) or 1.0
            tx, ty = tx / n, ty / n
            lx, ly = -ty, tx
            p = k.interpolate(s)
            x, y = p.x + lx * POLE_FROM_KERB, p.y + ly * POLE_FROM_KERB
            s += POLE_STEP + rng.uniform(-POLE_JITTER, POLE_JITTER)
            pt = Point(x, y)
            if not walk_t.covers_point(Point(p.x + lx * POLE_MIN_WALK, p.y + ly * POLE_MIN_WALK)) or not on_walk(x, y, 0.2):
                stats['pole_narrow'] += 1; continue
            disk = pt.buffer(5.0, quad_segs=4)
            if surface_t.area_in(disk) / disk.area > 0.47:
                stats['pole_corner'] += 1; continue
            if not free(x, y):
                stats['pole_blocked'] += 1; continue
            add(x, y, 1, yaw_of(ty, -tx))                       # box faces the road (right of the kerb)
            stats['pole'] += 1

    # ---- a few carts left along the kerb (about one per CART_KERB_EVERY m of wide sidewalk)
    for li, k in enumerate(kerbs):
        L = k.length
        rng = random.Random(zlib.crc32(f"{seed}/cart/{li}".encode()))
        if L < 15.0 or rng.random() > L / CART_KERB_EVERY:
            continue
        for _ in range(6):
            s = rng.uniform(5.0, L - 5.0)
            a, b = k.interpolate(max(s - 0.5, 0)), k.interpolate(min(s + 0.5, L))
            tx, ty = b.x - a.x, b.y - a.y
            n = math.hypot(tx, ty) or 1.0
            tx, ty = tx / n, ty / n
            p = k.interpolate(s)
            x, y = p.x - ty * CART_FROM_KERB, p.y + tx * CART_FROM_KERB
            if (walk_t.covers_point(Point(p.x - ty * CART_MIN_WALK, p.y + tx * CART_MIN_WALK))
                    and on_walk(x, y, 0.9) and free(x, y, 0.5)):
                add(x, y, 2, yaw_of(tx, ty) + rng.choice((0, 180)) + rng.uniform(-6, 6))
                stats['cart_kerb'] += 1
                break

    # ---- overrides: op "prop" -> Point adds one ({"kind": "SignNgo|PowerPole|Cart", "yaw": deg}), Polygon cuts
    cuts = [g for p, g in overrides if p.get('op') == 'prop' and g.geom_type in ('Polygon', 'MultiPolygon')]
    if cuts:
        cut = unary_union(cuts)
        before = len(props)
        props = [p for p in props if not cut.contains(Point(p['x'], p['y']))]
        stats['override_cut'] = before - len(props)
    for p, g in overrides:
        if p.get('op') == 'prop' and g.geom_type == 'Point':
            kind = PROP_KINDS.index(p['kind']) if p.get('kind') in PROP_KINDS else 0
            props.append(dict(x=round(g.x, 2), y=round(g.y, 2), kind=kind, yaw=float(p.get('yaw', 0.0))))
            stats['override_add'] += 1
    count = {PROP_KINDS[i]: sum(p['kind'] == i for p in props) for i in range(len(PROP_KINDS))}
    print(f"[props] {count} ({mouths} alley mouths); {dict(stats)}")
    return props


def chunk_props(chunks, props, gx, gy, nx, ny):
    """chunk['prop'] = flat [x, y, kind, yaw, ...]."""
    per = defaultdict(list)
    for p in props:
        ix = min(max(int((p['x'] - gx) // CHUNK), 0), nx - 1)
        iy = min(max(int((p['y'] - gy) // CHUNK), 0), ny - 1)
        per[(ix, iy)].extend([p['x'], p['y'], p['kind'], p['yaw']])
    for c in chunks:
        c['prop'] = per.get((c['ix'], c['iy']), [])


def chunk_motos(chunks, motos, gx, gy, nx, ny):
    """chunk['moto'] = flat [x, y, yaw, ...]."""
    per = defaultdict(list)
    for m in motos:
        ix = min(max(int((m['x'] - gx) // CHUNK), 0), nx - 1)
        iy = min(max(int((m['y'] - gy) // CHUNK), 0), ny - 1)
        per[(ix, iy)].extend([m['x'], m['y'], m['yaw']])
    for c in chunks:
        c['moto'] = per.get((c['ix'], c['iy']), [])


def chunk_trees(chunks, trees, gx, gy, nx, ny):
    """chunk['tree'] = flat [x, y, species, yaw, scale, kind, ...] (JsonUtility-friendly)."""
    per = defaultdict(list)
    for t in trees:
        ix = min(max(int((t['x'] - gx) // CHUNK), 0), nx - 1)
        iy = min(max(int((t['y'] - gy) // CHUNK), 0), ny - 1)
        per[(ix, iy)].extend([t['x'], t['y'], t['sp'], t['yaw'], t['scale'], t['kind']])
    for c in chunks:
        c['tree'] = per.get((c['ix'], c['iy']), [])


def chunk_lines(lines, cb):
    """Lines clipped to a chunk box -> (flat coords, point counts, start distance along the full line)."""
    flat, counts, starts = [], [], []
    for l in lines:
        if not l.intersects(cb):
            continue
        part = l.intersection(cb)
        for p in getattr(part, 'geoms', [part]):
            if p.geom_type != 'LineString' or p.length < 0.05:
                continue
            c = list(p.coords)
            s0, s1 = l.project(Point(c[0])), l.project(Point(c[-1]))
            if s1 < s0 and not l.is_ring:                   # keep the kerb direction (road on the right)
                c, s0 = c[::-1], s1
            flat.extend(round(v, 3) for xy in c for v in xy)
            counts.append(len(c))
            starts.append(round(s0, 3))
    return flat, counts, starts


# ---------------------------------------------------------------- chunks
def triangles(geom):
    """Constrained Delaunay triangulation (holes respected) -> flat [x0,y0,x1,y1,x2,y2, ...]."""
    out = []
    for p in polygons_of(geom):
        if p.area < 0.05:
            continue
        tris = shapely.constrained_delaunay_triangles(p)
        for t in getattr(tris, 'geoms', [tris]):
            c = list(t.exterior.coords)[:3]
            out.extend(round(v, 2) for xy in c for v in xy)
    return out


def chunk_meshes(area, layers, lines=None):
    """layers: name -> Tiled polygons (triangulated); lines: name -> [LineString] (kerbs, skirts)
    exported as <name> flat coords, <name>_n point counts, <name>_s start distances."""
    x0, y0, x1, y1 = area.bounds
    nx, ny = math.ceil((x1 - x0) / CHUNK), math.ceil((y1 - y0) / CHUNK)
    trees = {k: (STRtree(v), v) for k, v in (lines or {}).items()}
    chunks = []
    for iy in range(ny):
        for ix in range(nx):
            cb = box(x0 + ix * CHUNK, y0 + iy * CHUNK, x0 + (ix + 1) * CHUNK, y0 + (iy + 1) * CHUNK)
            ch = dict(ix=ix, iy=iy, bounds=[round(v, 2) for v in cb.bounds])
            for name, t in layers.items():
                ch[name] = triangles(t.near(cb).intersection(cb))
            for name, (tree, ls) in trees.items():
                ch[name], ch[name + '_n'], ch[name + '_s'] = chunk_lines([ls[i] for i in tree.query(cb)], cb)
            chunks.append(ch)
    return chunks, (x0, y0, nx, ny)


# ---------------------------------------------------------------- checks + report
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


def save_geojson(name, feats, proj):
    def tr(g):
        return shapely.transform(g, lambda c: np.array([proj.inv(x, y) for x, y in c]))
    fc = dict(type='FeatureCollection', features=[
        dict(type='Feature', properties=props, geometry=mapping(tr(g))) for props, g in feats])
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as f:
        json.dump(fc, f)


def report_png(path, area, raw_buildings, surface, sidewalk, water, open_, lots, big, flags, zoom=None,
               median=None, rails=(), kerbs=(), skirts=(), trees=(), motos=()):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch
    from matplotlib.collections import PatchCollection

    def patches(geoms, **kw):
        """Polygons with holes (the street network is one polygon whose holes are the blocks)."""
        ps = []
        for g in geoms:
            for p in polygons_of(g):
                rings = [p.exterior] + list(p.interiors)
                verts, codes = [], []
                for r in rings:
                    c = list(r.coords)
                    verts += c
                    codes += [Path.MOVETO] + [Path.LINETO] * (len(c) - 2) + [Path.CLOSEPOLY]
                ps.append(PathPatch(Path(verts, codes)))
        return PatchCollection(ps, **kw)

    x0, y0, x1, y1 = zoom or area.bounds
    w = 22
    fig, ax = plt.subplots(figsize=(w, w * (y1 - y0) / (x1 - x0)), dpi=110)
    ax.set_facecolor('#f4f1ea')
    ax.add_collection(patches([water], facecolor='#9cc7e6', edgecolor='none'))
    ax.add_collection(patches([open_], facecolor='#bfdcae', edgecolor='none'))
    ax.add_collection(patches([sidewalk], facecolor='#d9d4cc', edgecolor='none'))
    ax.add_collection(patches([surface], facecolor='#6e6e6e', edgecolor='none'))
    if median is not None:
        ax.add_collection(patches([median], facecolor='#2f7d32', edgecolor='none'))
    ax.add_collection(patches(raw_buildings, facecolor='none', edgecolor='#999999', linewidth=0.3))
    ax.add_collection(patches([l['rect'] for l in lots], facecolor='#e8a65d', edgecolor='#8a5a2b', linewidth=0.2))
    ax.add_collection(patches([b['rect'] for b in big], facecolor='#5b7bb5', edgecolor='#1f3460', linewidth=0.4))
    for r in rails:
        for l in getattr(r['centre'], 'geoms', [r['centre']]):
            ax.plot(*l.xy, color='#1f4fd1', linewidth=1.2, linestyle='--')
    for ls, col in ((kerbs, '#d11f1f'), (skirts, '#1f6fd1')):
        for l in ls:
            ax.plot(*l.xy, color=col, linewidth=0.8)
    for f in flags:
        ax.add_patch(plt.Circle(f['xy'], 12, fill=False, color='red', linewidth=1.5))
    if trees:
        crowns = tree_crowns()
        cols = ['#2e7d32', '#1b5e20', '#9ccc65', '#00897b']          # Sau, XaCu, Bang, HoaSua
        from matplotlib.collections import PatchCollection as PC
        for sp in range(len(TREE_SPECIES)):
            ts = [t for t in trees if t['sp'] == sp]
            ax.add_collection(PC([plt.Circle((t['x'], t['y']), crowns[sp] * t['scale']) for t in ts],
                                 facecolor=cols[sp], edgecolor='black', linewidth=0.2, alpha=0.55))
            ax.plot([], [], 'o', color=cols[sp], label=f"{TREE_SPECIES[sp]} ({len(ts)})")
        ax.legend(loc='upper right', fontsize=14)
    if motos:                                          # parked bikes: 0.72 x 2.0 m boxes, nose = dot
        from matplotlib.collections import PatchCollection as PC
        boxes = []
        for m in motos:
            a = math.radians(m['yaw'])
            fx, fy = math.sin(a), math.cos(a)
            sx, sy = fy, -fx
            cx, cy = m['x'], m['y']
            boxes.append(plt.Polygon([(cx + fx * hl + sx * hw, cy + fy * hl + sy * hw)
                                      for hl, hw in ((1.0, 0.36), (1.0, -0.36), (-1.0, -0.36), (-1.0, 0.36))]))
            ax.plot(cx + fx * 0.8, cy + fy * 0.8, '.', color='black', markersize=1.5)
        ax.add_collection(PC(boxes, facecolor='#e0218a', edgecolor='black', linewidth=0.2))
        ax.plot([], [], 's', color='#e0218a', label=f"xe may ({len(motos)})")
        ax.legend(loc='upper right', fontsize=14)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect('equal')
    ax.set_title('xam = duong | be = via he | xanh la dam = vung tru metro | net xanh = metro | cam = lo nha ong | xanh duong = nha lon/thap | vien xam = OSM goc | do = can xem')
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ---------------------------------------------------------------- main
def main(osm_path):
    os.makedirs(OUT, exist_ok=True)
    proj, area, nodes, ways, rels = parse_osm(osm_path)
    print(f"[osm] {len(nodes)} nodes, {len(ways)} ways, {len(rels)} relations, area {area.area / 1e6:.2f} km2")
    overrides = load_overrides(proj)
    flags = []

    roads, surface, sidewalk = build_roads(ways, nodes, area, overrides, flags)
    rails, platforms = build_rails(ways, nodes, area)
    corridor, median = metro_corridor(rails, roads, surface)
    rail_clear = unary_union([r['centre'].buffer(RAIL_CLEAR) for r in rails]).intersection(area) if rails else Polygon()
    # under the viaduct: plain asphalt, no sidewalk; the median only marks where piers + planter frames go
    surface = surface.union(corridor).intersection(area)
    sidewalk = sidewalk.difference(corridor).difference(median)
    median = median.intersection(area)
    surface, sidewalk = sidewalk_overrides(surface, sidewalk, overrides, area)
    surface, sidewalk = fillet_corners(surface, sidewalk)
    kerbs, skirts, walk_top = kerb_lines(surface, sidewalk)
    street = surface.union(sidewalk)
    water = unary_union([p for _, p, _ in area_features(ways, rels, nodes, lambda t: tag_match(t, WATER_TAGS))]
                        or [Polygon()]).intersection(area)
    open_ = unary_union([p for _, p, _ in area_features(ways, rels, nodes, lambda t: tag_match(t, OPEN_TAGS))]
                        + [g for p, g in overrides if p.get('op') == 'no_build'] or [Polygon()]).intersection(area)
    open_ = open_.difference(street).difference(water)
    blocked = street.union(water).union(corridor).union(rail_clear)
    origin = area.bounds[:2]
    blocked_t = Tiled(blocked, origin)
    street_t = Tiled(street, origin)
    print("[tiles] street/blocked indexed")

    big, big_union = build_big(ways, rels, nodes, area, blocked_t, overrides, flags)
    blocks_geom = area.difference(blocked).difference(open_).difference(big_union.buffer(1.0))
    blocks = [p for p in polygons_of(blocks_geom) if p.area >= 30]
    print(f"[blocks] {len(blocks)} blocks")
    lots = infill_lots(blocks, street_t, flags)
    res = checks(lots, big, street_t, flags)
    trees = place_trees(kerbs, roads, surface, sidewalk, open_, lots, big, origin, overrides)
    motos = place_motos(lots, walk_top, surface, trees, origin, overrides)
    props = place_props(kerbs, roads, surface, walk_top, trees, motos, origin, overrides)

    # "sidewalk" = the flat top only (kerb band cut off); kerbs / skirts are swept in Unity
    chunks, (gx, gy, nx, ny) = chunk_meshes(area, {k: Tiled(g, origin, CHUNK) for k, g in
                                                   dict(road=surface, sidewalk=walk_top, water=water, green=open_).items()},
                                            lines=dict(kerb=kerbs, skirt=skirts))
    chunk_trees(chunks, trees, gx, gy, nx, ny)
    chunk_motos(chunks, motos, gx, gy, nx, ny)
    chunk_props(chunks, props, gx, gy, nx, ny)
    x0, y0, x1, y1 = area.bounds
    city = dict(
        version=1, source=os.path.basename(osm_path),
        origin=dict(lat=proj.lat0, lon=proj.lon0),
        coords="metres, x = east, y = north, origin = centre of the OSM bounds",
        bounds=[round(v, 2) for v in (x0, y0, x1, y1)],
        chunk=dict(size=CHUNK, x0=round(gx, 2), y0=round(gy, 2), nx=nx, ny=ny),
        # street cross-section: heights in metres above the block ground (road_y) / above the road (kerb_*);
        # profile = flat [across, up, ...], across 0 = road edge, negative = sidewalk side
        street=dict(road_y=ROAD_Y, kerb_h=KERB_H, kerb_lip=KERB_LIP, kerb_angle=KERB_ANGLE, kerb_w=KERB_W,
                    stone=KERB_STONE, profile=[v for xy in KERB_PROFILE for v in xy]),
        roads=[dict(id=r['id'], cls=r['cls'], width=r['width'], layer=r['layer'], bridge=r['bridge'],
                    name=r['name'], line=[[round(x, 2), round(y, 2)] for x, y in r['line'].coords]) for r in roads],
        buildings=[{k: v for k, v in b.items() if k not in ('rect', 'poly')} for b in big],
        lots=[{k: v for k, v in l.items() if k != 'rect'} for l in lots],
        # one entry per continuous piece of viaduct centreline, flat [x0, y0, x1, y1, ...] (JsonUtility-friendly)
        rails=[dict(ref=r['ref'], name=r['name'], layer=r['layer'], tracks=r['tracks'],
                    line=[round(v, 2) for xy in l.coords for v in xy])
               for r in rails for l in getattr(r['centre'], 'geoms', [r['centre']])],
        platforms=[dict(ring=[round(v, 2) for xy in p.exterior.coords for v in xy]) for p in platforms],
        # pier / planter-frame zone under the viaduct (cut at junctions), for the viaduct step
        medians=[dict(ring=[round(v, 2) for xy in p.exterior.coords for v in xy]) for p in polygons_of(median)],
        chunks=chunks,
        checks=res,
    )
    with open(os.path.join(OUT, 'city.json'), 'w', encoding='utf-8') as f:
        json.dump(city, f, separators=(',', ':'))
    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(checks=res, flags=flags), f, indent=1, ensure_ascii=False)

    raw_big_outlines = [p for _, p, t in area_features(ways, rels, nodes, lambda t: 'building' in t)]
    report_png(os.path.join(OUT, 'report.png'), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big, flags,
               median=median, rails=rails)
    cx, cy = area.centroid.x, area.centroid.y
    report_png(os.path.join(OUT, 'report_zoom.png'), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big,
               flags, zoom=(cx - 300, cy - 200, cx + 300, cy + 200), median=median, rails=rails)
    for i, (kx, ky) in enumerate(KERB_VIEWS):
        report_png(os.path.join(OUT, f'report_kerb_{i}.png'), area, raw_big_outlines, surface, sidewalk, water, open_,
                   lots, big, flags, zoom=(kx - 75, ky - 50, kx + 75, ky + 50), median=median, rails=rails,
                   kerbs=kerbs, skirts=skirts)
    report_png(os.path.join(OUT, 'report_metro.png'), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big,
               flags, zoom=(-1100, -700, -100, 100), median=median, rails=rails)
    report_png(os.path.join(OUT, 'report_metro_n.png'), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big,
               flags, zoom=(-300, 0, 500, 884), median=median, rails=rails)
    for name, zoom in (('report_trees.png', None), ('report_trees_0.png', (0, -250, 500, 100)),
                       ('report_trees_1.png', (-700, 150, -200, 500))):
        report_png(os.path.join(OUT, name), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big, [],
                   zoom=zoom, median=median, rails=rails, trees=trees)
    save_geojson('trees.geojson', [(dict(species=TREE_SPECIES[t['sp']], scale=t['scale'], kind=t['kind']),
                                    Point(t['x'], t['y'])) for t in trees], proj)

    for name, zoom in (('report_motos_0.png', (100, -150, 250, -50)), ('report_motos_1.png', (-500, 250, -350, 350))):
        report_png(os.path.join(OUT, name), area, raw_big_outlines, surface, sidewalk, water, open_, lots, big, [],
                   zoom=zoom, median=median, rails=rails, trees=trees, motos=motos)
    save_geojson('props.geojson', [(dict(kind=PROP_KINDS[p['kind']], yaw=p['yaw']), Point(p['x'], p['y']))
                                   for p in props], proj)
    save_geojson('motos.geojson', [(dict(yaw=m['yaw']), Point(m['x'], m['y'])) for m in motos], proj)
    save_geojson('roads.geojson', [(dict(id=r['id'], cls=r['cls'], width=r['width'], name=r['name']), r['line']) for r in roads], proj)
    save_geojson('road_surface.geojson', [(dict(kind='road'), surface), (dict(kind='sidewalk'), sidewalk),
                                          (dict(kind='median'), median)], proj)
    save_geojson('sidewalk.geojson', [(dict(kind='sidewalk_top'), walk_top)]
                 + [(dict(kind='kerb'), k) for k in kerbs] + [(dict(kind='skirt'), k) for k in skirts], proj)
    save_geojson('rail.geojson', [(dict(ref=r['ref'], name=r['name'], layer=r['layer']), r['centre']) for r in rails]
                 + [(dict(kind='platform'), p) for p in platforms], proj)
    save_geojson('buildings.geojson', [(dict(id=b['id'], levels=b['levels'], name=b['name']), b['rect']) for b in big], proj)
    save_geojson('lots.geojson', [(dict(block=l['block'], width=l['width']), l['rect']) for l in lots], proj)
    save_geojson('flags.geojson', [(dict(kind=f['kind'], id=f['id'], msg=f['msg']), Point(f['xy'])) for f in flags], proj)
    if not os.path.exists(OVERRIDES):
        with open(OVERRIDES, 'w', encoding='utf-8') as f:
            json.dump(dict(type='FeatureCollection', features=[]), f)

    kinds = defaultdict(int)
    for f in flags:
        kinds[f['kind']] += 1
    size = os.path.getsize(os.path.join(OUT, 'city.json')) / 1e6
    print(f"[out] city.json {size:.1f} MB, {len(chunks)} chunks, flags {dict(kinds)}")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'raw', 'thanhxuan.osm'))
