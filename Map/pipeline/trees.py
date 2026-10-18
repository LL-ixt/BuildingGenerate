"""Street trees along the kerbs and loose trees in the green areas."""
import json, math, os, random, zlib
from collections import defaultdict

import shapely
import shapely.prepared
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .config import HERE
from .osm import Tiled, polygons_of


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
