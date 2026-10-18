"""OSM parsing, local projection, geometry helpers and the QGIS overrides file."""
import json, math, os, xml.etree.ElementTree as ET
import numpy as np

import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon, box, shape
from shapely.ops import linemerge, polygonize, unary_union
from shapely.strtree import STRtree

from .config import OVERRIDES



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


def tangent(line, s, h=1.5):
    p0, p1 = line.interpolate(max(s - h, 0.0)), line.interpolate(min(s + h, line.length))
    dx, dy = p1.x - p0.x, p1.y - p0.y
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n
