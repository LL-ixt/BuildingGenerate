"""Per-chunk export: triangulated ground layers, kerb lines, trees / bikes / props."""
import math
from collections import defaultdict

import shapely
from shapely.geometry import Point, box
from shapely.strtree import STRtree

from .config import CHUNK
from .osm import polygons_of



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
