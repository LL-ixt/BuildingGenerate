"""Pick street views that show a "NGÕ" sign, a power pole, parked bikes and trees together (for the
props screenshots in Unity, HanoiProps.CityShots). Plain Python:
    python Map/find_props_shot.py  -> out/props_shot.json
The camera stands on the centreline of the street the props line (eye height, no building in the
way), ~18 m back along it, looking at the group. city.json metres (x east, y north) = Unity (x, z)."""
import json
import math
import os

from shapely.geometry import LineString, Point

HERE = os.path.dirname(os.path.abspath(__file__))
city = json.load(open(os.path.join(HERE, 'out', 'city.json'), encoding='utf-8'))
pts = {'sign': [], 'pole': [], 'cart': [], 'moto': [], 'tree': []}
for c in city['chunks']:
    p = c.get('prop', [])
    for i in range(0, len(p), 4):
        pts[('sign', 'pole', 'cart')[int(p[i + 2])]].append((p[i], p[i + 1]))
    m = c.get('moto', [])
    pts['moto'] += [(m[i], m[i + 1]) for i in range(0, len(m), 3)]
    t = c.get('tree', [])
    pts['tree'] += [(t[i], t[i + 1]) for i in range(0, len(t), 6) if t[i + 5] == 0]
mains = [r for r in city['roads'] if r['cls'] in ('primary', 'secondary', 'tertiary', 'trunk', 'residential')]
lines = [LineString(r['line']) for r in mains]

BACK, ALONG, SIDE = 16.0, 35.0, 14.0      # camera distance; group extent along / across the street


def group(line, s0):
    """Objects within ALONG ahead of s0 along the line and SIDE across it -> {kind: [(ds, side)]}."""
    out = {}
    for kind, lst in pts.items():
        for x, y in lst:
            if abs(x - line.interpolate(s0).x) > 60 or abs(y - line.interpolate(s0).y) > 60:
                continue
            s = line.project(Point(x, y))
            d = line.interpolate(s).distance(Point(x, y))
            if d < SIDE and 0 <= s - s0 <= ALONG:
                out.setdefault(kind, []).append((x, y))
    return out


cands = []
for sx, sy in pts['sign']:
    best = min(range(len(lines)), key=lambda i: lines[i].distance(Point(sx, sy)))
    line = lines[best]
    if line.distance(Point(sx, sy)) > 15 or line.length < 60:
        continue
    s_sign = line.project(Point(sx, sy))
    for direction in (1, -1):                         # look along the line or against it
        ln = line if direction == 1 else LineString(list(line.coords)[::-1])
        s = ln.project(Point(sx, sy))
        s0 = s - 8.0                                  # the group starts a little before the sign
        if s0 - BACK < 0:
            continue
        g = group(ln, s0)
        if not g.get('pole') or not g.get('moto') or not g.get('tree'):
            continue
        score = (min(len(g['moto']), 6) + min(len(g['tree']), 5) + 2 * min(len(g.get('pole', [])), 2)
                 + min(len(g.get('sign', [])), 3) + 4 * min(len(g.get('cart', [])), 1))
        cam = ln.interpolate(s0 - BACK)
        allp = [q for k in g for q in g[k] if k != 'tree']
        tx = sum(q[0] for q in allp) / len(allp)
        ty = sum(q[1] for q in allp) / len(allp)
        cands.append((score, (cam.x, cam.y), (tx, ty), {k: len(v) for k, v in g.items()}, (round(sx), round(sy))))

cands.sort(key=lambda c: -c[0])
shots, used = [], []
for score, cam, tgt, counts, sign in cands:
    if any(math.hypot(tgt[0] - u[0], tgt[1] - u[1]) < 150 for u in used):
        continue                                       # two different places
    used.append(tgt)
    k = len(used)
    dx, dy = tgt[0] - cam[0], tgt[1] - cam[1]
    n = math.hypot(dx, dy)
    ux, uy = dx / n, dy / n
    shots.append(dict(name=f'props_s{k}_street', camera=[round(cam[0], 2), 1.7, round(cam[1], 2)],
                      target=[round(tgt[0], 2), 1.5, round(tgt[1], 2)], counts=counts, score=score))
    shots.append(dict(name=f'props_s{k}_high', camera=[round(cam[0] - ux * 6, 2), 9.0, round(cam[1] - uy * 6, 2)],
                      target=[round(tgt[0], 2), 0.5, round(tgt[1], 2)], counts=counts, score=score))
    if len(used) == 2:
        break
json.dump({'shots': shots}, open(os.path.join(HERE, 'out', 'props_shot.json'), 'w'), indent=1)
for s in shots:
    print(s)


# ---- close view: the pole with a bike cluster and a sign nearest to it, camera on the road ~10 m away
poles = []
for c in city['chunks']:
    p = c.get('prop', [])
    poles += [(p[i], p[i + 1], p[i + 3]) for i in range(0, len(p), 4) if int(p[i + 2]) == 1]


def nearest(kind, x, y):
    return min(pts[kind], key=lambda q: math.hypot(q[0] - x, q[1] - y))


best = None
for px, py, yaw in poles:
    m, s = nearest('moto', px, py), nearest('sign', px, py)
    dm, ds = math.hypot(m[0] - px, m[1] - py), math.hypot(s[0] - px, s[1] - py)
    trees = sum(math.hypot(t[0] - px, t[1] - py) < 15 for t in pts['tree'])
    cost = max(dm, ds) - 1.5 * min(trees, 3)
    if best is None or cost < best[0]:
        best = (cost, (px, py, yaw), m, s, dm, ds, trees)
cost, (px, py, yaw), m, s, dm, ds, trees = best
rx, ry = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))     # pole box -> road
gx, gy = (px + m[0] + s[0]) / 3, (py + m[1] + s[1]) / 3
for sgn in (1, -1):                                                   # stand on the side that frames all three
    tx, ty = -ry * sgn, rx * sgn
    cx, cy = gx + rx * 6.0 - tx * 13.0, gy + ry * 6.0 - ty * 13.0
    vx, vy = gx - cx, gy - cy
    ang = [abs(math.degrees(math.atan2(vx * (q[1] - cy) - vy * (q[0] - cx), vx * (q[0] - cx) + vy * (q[1] - cy))))
           for q in ((px, py), m, s)]
    if max(ang) < 32:
        break
close = dict(name='props_s0_close', camera=[round(cx, 2), 1.7, round(cy, 2)], target=[round(gx, 2), 1.4, round(gy, 2)],
             counts=dict(moto_dist=round(dm, 1), sign_dist=round(ds, 1), trees=trees), score=-round(cost, 1))
data = json.load(open(os.path.join(HERE, 'out', 'props_shot.json')))
data['shots'] = [close] + data['shots']
json.dump(data, open(os.path.join(HERE, 'out', 'props_shot.json'), 'w'), indent=1)
print(close, 'angles', [round(a) for a in ang])
