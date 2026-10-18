"""Traffic lanes (Plan TRAFFIC T1): directed lane centrelines + junction links from the OSM roads.

Right-hand traffic. Topology from the OSM node ids (`refs`) only: a flyover crossing a street without a shared
node is not a junction. Heights only from the flyover profile already computed in flyover.py (deck top above the
road), everything else z = 0. Output for city.json "traffic":
  lanes[]   id, kind 'lane' | 'link' (junction connector), pts flat [x, y, z, ...] (z above the road surface),
            width (m), speed (km/h), next[] (lane ids a vehicle may continue on), src / sink (enters / leaves the
            map at its edge), road (OSM way id), node (junction node id of a link)
  conflicts flat [a, b, ...]: pairs of links of one junction that cross or merge (only one at a time)
"""
import math
from collections import defaultdict, deque

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import substring
from shapely.strtree import STRtree

from .osm import polygons_of

# drivable classes: speed (km/h), default lanes of a one-way road, default lanes per direction of a two-way road
TRAFFIC_CLASSES = {
    'trunk': (60, 2, 2), 'primary': (50, 2, 2), 'secondary': (45, 2, 1), 'tertiary': (40, 1, 1),
    'trunk_link': (40, 1, 1), 'primary_link': (35, 1, 1), 'secondary_link': (35, 1, 1), 'tertiary_link': (30, 1, 1),
    'unclassified': (35, 1, 1), 'residential': (30, 1, 1),
}                          # service (alleys, yards) has no traffic
FLY_SPEED = 50             # km/h on a flyover
LANE_MIN_W = 2.75          # m: fewer lanes than tagged when the carriageway is too narrow for them
LANE_STEP = 2.0            # m: lane sampling
JUNCTION_PAD = 1.0         # m: lanes stop this far past the widest half carriageway meeting at a junction
THROUGH_TRIM = 3.0         # m: trim where just two pieces continue each other (width / lane changes)
THROUGH_DEG = 30.0         # deg: "continue each other"
STRAIGHT_DEG, UTURN_DEG = 35.0, 150.0
LINK_LAT_ACC = 2.0         # m/s2: comfortable side acceleration in junction curves
LINK_MIN_SPEED = 12.0      # km/h
CONFLICT_DIST = 1.5        # m: links of different lanes closer than this (or crossing) are exclusive
BORDER_TOL = 3.0           # m: a dead end this close to the map edge is where the road leaves the map


def _heading(a, b):
    v = np.array(b[:2], float) - np.array(a[:2], float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.array([1.0, 0.0])


def _signed_deg(h0, h1):
    """Angle from heading h0 to h1, + = left (counter-clockwise)."""
    return math.degrees(math.atan2(h0[0] * h1[1] - h0[1] * h1[0], h0[0] * h1[0] + h0[1] * h1[1]))


def build_lanes(roads, nodes, flyovers, area, flags):
    # 1) drivable ways split into pieces at every node shared with another drivable way
    drive = []
    for r in roads:
        if r['cls'] not in TRAFFIC_CLASSES or not r['refs']:
            continue
        refs = [x for x in r['refs'] if x in nodes]
        if len(refs) >= 2:
            drive.append((r, refs))
    count = defaultdict(int)
    for _, refs in drive:
        for x in refs:
            count[x] += 1
    pieces = []
    for r, refs in drive:
        cut = [0] + [i for i in range(1, len(refs) - 1) if count[refs[i]] >= 2] + [len(refs) - 1]
        for i0, i1 in zip(cut, cut[1:]):
            sub = refs[i0:i1 + 1]
            line = LineString([nodes[x] for x in sub])
            if line.length > 0.1:
                pieces.append(dict(road=r, a=sub[0], b=sub[-1], line=line))

    # 2) pieces of a flyover: the deck centre (flyover.py) gives the plan and the height
    def fly_of(p):
        r = p['road']
        if r['layer'] < 1 or not r['bridge']:
            return None
        return next((f for f in flyovers if f['_centre'].distance(p['line']) < 3.0
                     and f['_centre'].hausdorff_distance(p['line']) < 0.6 * f['_centre'].length + 5.0), None)

    for p in pieces:
        f = fly_of(p)
        p['fly'] = f
        if f is not None:
            c = f['_centre']
            s0, s1 = c.project(Point(p['line'].coords[0])), c.project(Point(p['line'].coords[-1]))
            seg = substring(c, min(s0, s1), max(s0, s1))
            p['line'] = LineString(list(seg.coords)[::-1]) if s0 > s1 else seg

    def height(p, xy):
        f = p['fly']
        if f is None:
            return 0.0
        return float(np.interp(f['_centre'].project(Point(xy)), f['_ss'], f['_zs']))

    # 3) junction trims
    ends = defaultdict(list)                       # node -> [(piece, at start?)]
    for p in pieces:
        ends[p['a']].append((p, True))
        ends[p['b']].append((p, False))
    trim = {}
    for n, lst in ends.items():
        if len(lst) == 1:
            t = 0.0
        elif len(lst) == 2:
            (p, sa), (q, sb) = lst
            hp = _heading(*(p['line'].coords[:2] if sa else p['line'].coords[-2:][::-1]))   # leaving the node
            hq = _heading(*(q['line'].coords[:2] if sb else q['line'].coords[-2:][::-1]))
            through = abs(abs(_signed_deg(hp, hq)) - 180.0) < THROUGH_DEG
            t = THROUGH_TRIM if through else max(p['road']['width'], q['road']['width']) / 2 + JUNCTION_PAD
        else:
            t = max(p['road']['width'] for p, _ in lst) / 2 + JUNCTION_PAD
        for p, sa in lst:
            trim[(id(p), sa)] = t
    border = area.boundary
    inner = area.buffer(-BORDER_TOL)

    def node_kind(n):
        if len(ends[n]) > 1:
            return 'junction'
        return 'dead' if inner.contains(Point(nodes[n])) else 'border'

    # 4) trimmed, clipped centrelines -> directed lanes
    lanes = []
    by_end = defaultdict(list)                     # (node, 'in' | 'out') -> [lane]
    n_dead = 0
    for p in pieces:
        r, L = p['road'], p['line'].length
        ta, tb = trim[(id(p), True)], trim[(id(p), False)]
        if ta + tb > L - 2.0:                      # short piece between two junctions: share what is left
            k = max(L - 2.0, 0.2 * L) / max(ta + tb, 1e-6)
            ta, tb = ta * k, tb * k
        core = substring(p['line'], ta, L - tb)
        if core.length < 0.5:
            continue
        start, end = Point(core.coords[0]), Point(core.coords[-1])
        for part in [g for g in getattr(core.intersection(area), 'geoms', [core.intersection(area)])
                     if g.geom_type == 'LineString' and g.length > 1.0]:
            # each end: the piece's node (junction / dead end / map edge) or a cut by the map edge
            ea = (p['a'], node_kind(p['a'])) if Point(part.coords[0]).distance(start) < 0.05 else (None, 'border')
            eb = (p['b'], node_kind(p['b'])) if Point(part.coords[-1]).distance(end) < 0.05 else (None, 'border')
            speed0, ow_def, tw_def = TRAFFIC_CLASSES[r['cls']]
            speed = FLY_SPEED if p['fly'] is not None else speed0
            dirs = [1] if r['oneway'] == 1 else [-1] if r['oneway'] == -1 else [1, -1]
            tagged = int(r['lanes']) if r['lanes'] else 0
            n = (tagged or ow_def) if len(dirs) == 1 else (max(1, tagged // 2) if tagged else tw_def)
            while n > 1 and r['width'] / (n * len(dirs)) < LANE_MIN_W:
                n -= 1
            lw = r['width'] / (n * len(dirs))
            for d in dirs:
                c = part if d > 0 else LineString(list(part.coords)[::-1])
                e_from, e_to = (ea, eb) if d > 0 else (eb, ea)
                for i in range(n):                  # i = 0: rightmost lane
                    off = r['width'] / 2 - (i + 0.5) * lw
                    g = c.offset_curve(-off, join_style='round') if abs(off) > 1e-3 else c
                    if g.geom_type != 'LineString' or g.length < 0.5:
                        continue
                    g = g.simplify(0.05).segmentize(LANE_STEP)
                    pts = [(x, y, height(p, (x, y))) for x, y in g.coords]
                    lane = dict(id=len(lanes), kind='lane', pts=pts, width=lw, speed=speed, next=[],
                                src=e_from[1] == 'border', sink=e_to[1] == 'border', road=str(r['id']), node='',
                                edge=(id(p), d, id(part)), idx=i, n=n, dead=e_to[1] == 'dead')
                    lanes.append(lane)
                    if e_from[1] == 'junction':
                        by_end[(e_from[0], 'out')].append(lane)
                    if e_to[1] == 'junction':
                        by_end[(e_to[0], 'in')].append(lane)

    # 5) junction links: every incoming lane group to every outgoing group of another piece (no U-turns)
    links_at = defaultdict(list)
    n_lanes = len(lanes)
    for node in {k[0] for k in by_end}:
        ins, outs = defaultdict(list), defaultdict(list)
        for l in by_end[(node, 'in')]:
            ins[l['edge']].append(l)
        for l in by_end[(node, 'out')]:
            outs[l['edge']].append(l)
        for ek, gi in ins.items():
            gi.sort(key=lambda l: l['idx'])
            moves = []
            for ok, go in outs.items():
                if ok[0] == ek[0]:                  # same piece: U-turn
                    continue
                go.sort(key=lambda l: l['idx'])
                h_in = _heading(gi[0]['pts'][-2], gi[0]['pts'][-1])
                h_out = _heading(go[0]['pts'][0], go[0]['pts'][1])
                ang = _signed_deg(h_in, h_out)
                if abs(ang) > UTURN_DEG:
                    continue
                if abs(ang) < STRAIGHT_DEG:
                    # every in lane keeps going, every out lane is fed (road widening / narrowing)
                    pairs = sorted({(i, min(i, len(go) - 1)) for i in range(len(gi))}
                                   | {(min(j, len(gi) - 1), j) for j in range(len(go))})
                    pairs = [(gi[i], go[j]) for i, j in pairs]
                elif ang < 0:
                    pairs = [(gi[0], go[0])]             # right turn: rightmost lanes
                else:
                    pairs = [(gi[-1], go[-1])]           # left turn: leftmost lanes
                moves.append((ang, go))
                for li, lo in pairs:
                    links_at[node].append(_link(lanes, li, lo, node, ang))
            # middle lanes with no straight move (T junction): the nearest turn, keeping their side
            for li in gi:
                if li['next'] or not moves:
                    continue
                ang, go = min(moves, key=lambda m: abs(m[0]))
                k = li['idx'] if ang < 0 else len(go) - len(gi) + li['idx']
                links_at[node].append(_link(lanes, li, go[min(max(k, 0), len(go) - 1)], node, ang))
    n_links = len(lanes) - n_lanes

    # 6) conflicts: links that cross, merge into the same lane or run closer than CONFLICT_DIST (the whole map, not
    # per junction: neighbouring junctions close together overlap)
    allv = [l for ls in links_at.values() for l in ls]
    geo = [LineString([q[:2] for q in l['pts']]) for l in allv]
    cut = [substring(g, 0.3, g.length - 0.3) if g.length > 1.0 else g for g in geo]
    tree = STRtree(cut)
    conflicts = []
    for i, a in enumerate(allv):
        for j in tree.query(cut[i].buffer(CONFLICT_DIST)):
            if j <= i:
                continue
            b = allv[j]
            if a['from'] == b['from']:
                continue                                 # same lane splitting: they never meet
            if a['next'][0] == b['next'][0] or cut[i].distance(cut[j]) < CONFLICT_DIST:
                conflicts += [a['id'], b['id']]

    # 7) checks: dead ends inside the map, lanes from which no exit can be reached
    for l in lanes:
        if l['kind'] == 'lane' and not l['next'] and not l['sink']:
            n_dead += 1
            flags.append(dict(kind='lane_dead_end', id=l['road'], xy=tuple(l['pts'][-1][:2]),
                              msg=f"lane {l['id']} ({'dead-end road' if l['dead'] else 'no turn allowed'}) ends inside the map"))
    prev = defaultdict(list)
    for l in lanes:
        for k in l['next']:
            prev[k].append(l['id'])
    reach = set(l['id'] for l in lanes if l['sink'])
    todo = deque(reach)
    while todo:
        k = todo.popleft()
        for q in prev[k]:
            if q not in reach:
                reach.add(q)
                todo.append(q)
    traps = [l for l in lanes if l['id'] not in reach]
    if traps:
        flags.append(dict(kind='lane_trap', id=len(traps), xy=tuple(traps[0]['pts'][0][:2]),
                          msg=f"{len(traps)} lanes cannot reach the map edge"))
    fly_lanes = [l for l in lanes if l['kind'] == 'lane' and max(q[2] for q in l['pts']) > 0.01]
    stats = dict(pieces=len(pieces), lanes=n_lanes, links=n_links, conflicts=len(conflicts) // 2,
                 src=sum(l['src'] for l in lanes), sink=sum(l['sink'] for l in lanes), dead=n_dead, traps=len(traps),
                 fly_lanes=len(fly_lanes), fly_top=round(max((q[2] for l in fly_lanes for q in l['pts']), default=0.0), 2),
                 km=round(sum(LineString([q[:2] for q in l['pts']]).length for l in lanes if l['kind'] == 'lane') / 1000, 2))
    print(f"[traffic] {stats['pieces']} road pieces -> {stats['lanes']} lanes ({stats['km']} km), {stats['links']} "
          f"junction links, {stats['conflicts']} conflict pairs, {stats['src']} sources / {stats['sink']} exits at the "
          f"map edge, {stats['dead']} dead ends, {stats['traps']} trapped lanes; flyover {stats['fly_lanes']} lanes "
          f"up to {stats['fly_top']} m")
    out = dict(lanes=[dict(id=l['id'], kind=l['kind'], width=round(l['width'], 2), speed=round(l['speed'], 1),
                           next=l['next'], src=l['src'], sink=l['sink'], road=l['road'], node=l['node'],
                           pts=[round(v, 3 if k % 3 == 2 else 2) for q in l['pts'] for k, v in enumerate(q)])
                      for l in lanes],
               conflicts=conflicts, stats=stats)
    out['_lanes'] = lanes
    return out


def _link(lanes, li, lo, node, ang):
    """Quadratic Bezier from the end of lane li to the start of lane lo (control = where their tangents meet)."""
    p0, p2 = np.array(li['pts'][-1], float), np.array(lo['pts'][0], float)
    h0 = _heading(li['pts'][-2], li['pts'][-1])
    h2 = _heading(lo['pts'][0], lo['pts'][1])
    chord = float(np.linalg.norm(p2[:2] - p0[:2]))
    p1 = (p0 + p2) / 2
    den = h0[0] * h2[1] - h0[1] * h2[0]
    if abs(den) > 0.05:                            # tangents not parallel: meet ahead of both ends?
        d = p2[:2] - p0[:2]
        t = (d[0] * h2[1] - d[1] * h2[0]) / den
        u = (d[0] * h0[1] - d[1] * h0[0]) / den
        if 0.2 < t < 2 * chord and 0.2 < u < 2 * chord:
            p1 = np.array([p0[0] + h0[0] * t, p0[1] + h0[1] * t, (p0[2] + p2[2]) / 2])
    m = max(4, int(math.ceil(chord / 1.0)))
    pts = [tuple((1 - s) ** 2 * p0 + 2 * (1 - s) * s * p1 + s * s * p2) for s in np.linspace(0, 1, m + 1)]
    th = math.radians(abs(ang))
    radius = chord / (2 * math.sin(th / 2)) if th > 0.1 else math.inf
    v = min(li['speed'], lo['speed'], math.sqrt(LINK_LAT_ACC * radius) * 3.6 if radius < math.inf else 1e9)
    link = dict(id=len(lanes), kind='link', pts=pts, width=min(li['width'], lo['width']), speed=max(v, LINK_MIN_SPEED),
                next=[lo['id']], src=False, sink=False, road='', node=str(node), edge=None, idx=0, n=1, dead=False,
                **{'from': li['id']})
    lanes.append(link)
    li['next'].append(link['id'])
    return link


def report_traffic(path, traffic, surface, zoom=None):
    """Lanes coloured by height (deck of the flyover), arrows = direction, links thin, sources / exits / dead ends."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import cm, colors
    lanes = traffic['_lanes']
    if zoom is None:
        xs = [q[0] for l in lanes for q in l['pts']]
        ys = [q[1] for l in lanes for q in l['pts']]
        zoom = (min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5)
    x0, y0, x1, y1 = zoom
    fig, ax = plt.subplots(figsize=(16, 16 * (y1 - y0) / (x1 - x0)), dpi=110)
    for p in polygons_of(surface):
        ax.fill(*p.exterior.xy, color='#d0d0d0', lw=0)
        for h in p.interiors:
            ax.fill(*h.xy, color='white', lw=0)
    zmax = max([q[2] for l in lanes for q in l['pts']] + [1.0])
    norm = colors.Normalize(0, zmax)
    cmap = matplotlib.colormaps['plasma']
    for l in lanes:
        xy = np.array([q[:2] for q in l['pts']])
        if l['kind'] == 'link':
            ax.plot(xy[:, 0], xy[:, 1], color='#606060', lw=0.5, alpha=0.7)
            continue
        z = np.array([q[2] for q in l['pts']])
        for i in range(len(xy) - 1):
            ax.plot(xy[i:i + 2, 0], xy[i:i + 2, 1], color=cmap(norm((z[i] + z[i + 1]) / 2)), lw=1.6)
        k = len(xy) // 2
        if len(xy) >= 2:
            a, b = xy[max(k - 1, 0)], xy[min(k + 1, len(xy) - 1)]
            ax.annotate('', xy=b, xytext=a, arrowprops=dict(arrowstyle='-|>', color='black', lw=0.8, mutation_scale=9))
        if l['src']:
            ax.plot(*xy[0], marker='^', color='#20a020', ms=6)
        if l['sink']:
            ax.plot(*xy[-1], marker='x', color='#d02020', ms=6)
        if not l['next'] and not l['sink']:
            ax.plot(*xy[-1], marker='o', color='magenta', ms=9)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect('equal')
    fig.colorbar(cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=0.6, label='z lan (m tren mat duong)')
    s = traffic['stats']
    ax.set_title(f"lan xe (di ben phai, mui ten = chieu chay, mau = cao do), xam manh = nhanh re o nut; "
                 f"tam giac xanh = xe vao tu bien, x do = ra bien, cham hong = lan cut. {s['lanes']} lan, "
                 f"{s['links']} nhanh, {s['conflicts']} cap xung dot", fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
