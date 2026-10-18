"""Street props: alley signs, power poles, garbage carts."""
import math, random, zlib
from collections import defaultdict

from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .config import KERB_W, SIDEWALK
from .osm import Tiled


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
