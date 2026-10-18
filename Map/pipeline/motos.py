"""Parked motorbikes in front of the tube houses."""
import math, random, zlib
from collections import defaultdict

from shapely.geometry import Point
from shapely.ops import unary_union

from .osm import Tiled


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
