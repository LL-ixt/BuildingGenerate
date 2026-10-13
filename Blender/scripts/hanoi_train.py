"""TRAIN — Hanoi metro car (Ref/train.webp, Line 3 Alstom Metropolis), low poly, all detail in the
livery atlas (build_train_texture.py -> Blender/train/T_Train.png + atlas.json).

    end car   20 m: raked + rounded nose (front surface filled by concentric loops), bumper, coupler
    mid car   19 m: flat gangway ends
    both      body = one section swept along the car (2.86 m wide, roof 3.8 m above the rail top),
              bellows at the gangway ends, 2 bogies (frame + 4 wheels on gauge 1.435), underframe
              equipment, 2 roof AC units
Geometry only (bmesh); build_train.py drives it.

Conventions (Blender, metres): origin = rail top under the car centre, up = +Z, the car runs towards
-Y (= Unity +Z after the FBX axis swap); s = -y = metres forward. Body UVs: sides -> SIDE_END /
SIDE_MID (u along the car rear -> front, v = height), front -> FRONT (planar x / z), the rest ->
flat palette cells. One material, M_Train. lod: 0 close-up, 1 mid (6-sided wheels, fewer nose loops,
no coupler / bellows), 2 far (body + roof units only, flat nose).
"""
import json
import math

import bmesh
from mathutils import Vector

ATLAS = json.load(open(r"D:\Project III\BuildingGenerate\Blender\train\atlas.json", encoding='utf-8'))
R = ATLAS['regions']
CAR = ATLAS['car']
Z_SIDE = ATLAS['z_side']
A_FRONT, Z_FRONT = ATLAS['a_front'], ATLAS['z_front']

# right half of the body section (x >= 0), bottom -> top, z above the rail top
SEC_HALF = [(0.0, 0.80), (1.25, 0.80), (1.38, 0.92), (1.42, 1.15), (1.43, 1.70), (1.41, 2.40),
            (1.36, 3.05), (1.28, 3.40), (1.12, 3.62), (0.85, 3.74), (0.45, 3.79), (0.0, 3.80)]
NOSE = dict(len=1.6, rake=0.85, rake_z=(1.55, 3.75), tuck=0.12, corner=0.62, corner_p=2.6, bulge=0.06)
BUMPER = dict(z=(0.30, 0.80), half_w=1.30, depth=0.55)
BOGIE = dict(inset=3.6, half_w=1.05, half_l=1.3, z=(0.50, 0.78), axle=1.05)
WHEEL = dict(r=0.42, w=0.14, x=1.435 / 2)
GANGWAY_GAP = 0.6           # between two car ends (bellows 0.3 m each)
LODS = {0: dict(loops=5, wheel_sides=12, coupler=True, bellows=True, bogies=True),
        1: dict(loops=2, wheel_sides=6, coupler=False, bellows=False, bogies=True),
        2: dict(loops=0, wheel_sides=0, coupler=False, bellows=False, bogies=False)}


def section():
    """Closed loop, counter-clockwise seen from the front (-Y looking +Y... order irrelevant: faces are
    oriented by hint points)."""
    right = SEC_HALF
    left = [(-x, z) for x, z in reversed(SEC_HALF[1:-1])]
    return right + left[:]


SEC = section()


def ruv(region, u, v):
    u0, v0, u1, v1 = R[region]
    return (u0 + (u1 - u0) * u, v0 + (v1 - v0) * v)


def cell(name):
    u0, v0, u1, v1 = R[name]
    return ((u0 + u1) / 2, (v0 + v1) / 2)


def front_uv(x, z):
    return ruv('FRONT', (x - A_FRONT[0]) / (A_FRONT[1] - A_FRONT[0]), (z - Z_FRONT[0]) / (Z_FRONT[1] - Z_FRONT[0]))


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def setback(x, z):
    """How far the nose surface lies behind the front tip at (x, z)."""
    rake = NOSE['rake'] * smoothstep(*NOSE['rake_z'], z) ** 1.3
    tuck = NOSE['tuck'] * smoothstep(1.2, 0.8, z)
    corner = NOSE['corner'] * (min(abs(x), 1.43) / 1.43) ** NOSE['corner_p']
    return rake + tuck + corner


class Mesh:
    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new('UVMap')

    def face(self, pts, uvs, hint):
        """Polygon whose normal points away from `hint` (a point inside the part)."""
        pts = [Vector(p) for p in pts]
        n = Vector((0, 0, 0))
        for i in range(len(pts)):                        # Newell normal
            a, b = pts[i], pts[(i + 1) % len(pts)]
            n += Vector(((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y)))
        c = sum(pts, Vector()) / len(pts)
        if n.dot(c - Vector(hint)) < 0:
            pts, uvs = pts[::-1], uvs[::-1]
        f = self.bm.faces.new([self.bm.verts.new(p) for p in pts])
        for l, uv in zip(f.loops, uvs):
            l[self.uv].uv = uv
        return f

    def finish(self):
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-5)
        return self.bm


def box(m, lo, hi, uv, skip=()):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    c = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    sides = {
        '-Y': ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)),
        '+Y': ((x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)),
        '+X': ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)),
        '-X': ((x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)),
        '+Z': ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)),
        '-Z': ((x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)),
    }
    for k, pts in sides.items():
        if k not in skip:
            m.face(pts, [uv] * 4, c)


# ---------------------------------------------------------------- body
def side_uv(region, length, s, z):
    return ruv(region, (s + length / 2) / length, (z - Z_SIDE[0]) / (Z_SIDE[1] - Z_SIDE[0]))


def edge_kind(z0, z1):
    if min(z0, z1) >= Z_SIDE[1] - 1e-4:
        return 'ROOF'
    if max(z0, z1) <= Z_SIDE[0] + 1e-4:
        return 'UNDER'
    return 'SIDE'


def body_strip(m, region, length, ring_a, ring_b, hint_z=2.2):
    """Quads between two rings of SEC points: ring_* = [(x, s, z)] (s forward)."""
    n = len(SEC)
    for k in range(n):
        k1 = (k + 1) % n
        pa, pb, qa, qb = ring_a[k], ring_a[k1], ring_b[k], ring_b[k1]
        kind = edge_kind(pa[2], pb[2])
        if kind == 'SIDE':
            uvs = [side_uv(region, length, p[1], p[2]) for p in (pa, pb, qb, qa)]
        else:
            uvs = [cell(kind)] * 4
        ys = (pa[1] + qa[1]) / 2
        m.face([(p[0], -p[1], p[2]) for p in (pa, pb, qb, qa)], uvs, (0, -ys, hint_z))


def flat_end(m, s, sign, lod):
    """Gangway end (flat, dark) + bellows when lod 0. sign = +1 front end, -1 rear end."""
    pts = [(x, -s, z) for x, z in SEC]
    m.face(pts, [cell('GANGWAY')] * len(pts), (0, -(s - sign), 2.2))
    if LODS[lod]['bellows']:
        g = GANGWAY_GAP / 2 - 0.01
        s0, s1 = sorted((s, s + sign * g))
        box(m, (-0.78, -s1, 1.05), (0.78, -s0, 3.35), cell('RUBBER'))


def nose(m, s_tip, lod, length):
    """Side walls from the body to the nose surface, nose surface (concentric loops), bumper, coupler."""
    s_ns = s_tip - NOSE['len']
    K = LODS[lod]['loops']
    ring_a = [(x, s_ns, z) for x, z in SEC]
    if K == 0:                       # far LOD: flat slanted front
        ring_b = [(x, s_tip - setback(0, z) - 0.3, z) for x, z in SEC]
        body_strip(m, 'SIDE_END', length, ring_a, ring_b)
        m.face([(p[0], -p[1], p[2]) for p in ring_b], [front_uv(p[0], p[2]) for p in ring_b], (0, -(s_ns - 1), 2.2))
        return
    ring_b = [(x, s_tip - setback(x, z), z) for x, z in SEC]
    body_strip(m, 'SIDE_END', length, ring_a, ring_b)
    centre = (0.0, 2.3)
    loops = [ring_b]
    for k in range(1, K + 1):
        f = 1 - k / K
        loop = []
        for x, z in SEC:
            lx, lz = centre[0] + (x - centre[0]) * f, centre[1] + (z - centre[1]) * f
            loop.append((lx, s_tip - setback(lx, lz) + NOSE['bulge'] * (k / K) ** 0.7, lz))
        loops.append(loop)
    hint = (0, -(s_ns - 1.0), 2.2)
    n = len(SEC)
    for a, b in zip(loops, loops[1:]):
        for k in range(n):
            k1 = (k + 1) % n
            quad = (a[k], a[k1], b[k1], b[k])
            if math.dist(b[k], b[k1]) < 1e-6:                      # last loop collapsed to the centre
                quad = (a[k], a[k1], b[k])
            m.face([(p[0], -p[1], p[2]) for p in quad], [front_uv(p[0], p[2]) for p in quad], hint)
    # bumper under the nose: rounded plan, front faces in FRONT, sides lime
    z0, z1 = BUMPER['z']
    hw = BUMPER['half_w']
    xs = [hw * (i / 6 * 2 - 1) for i in range(7)]
    front_pts = [(x, s_tip - setback(x, z1) - 0.02) for x in xs]
    s_back = s_ns
    outline = [(hw, s_back)] + front_pts[::-1] + [(-hw, s_back)]      # counter-clockwise-ish plan
    hb = (0, -(s_back + 0.3), (z0 + z1) / 2)
    for (xa, sa), (xb, sb) in zip(outline, outline[1:]):
        quad = [(xa, -sa, z0), (xb, -sb, z0), (xb, -sb, z1), (xa, -sa, z1)]
        on_front = sa > s_back + 1e-3 and sb > s_back + 1e-3
        uvs = [front_uv(p[0], p[2]) for p in quad] if on_front else [cell('LIME')] * 4
        m.face(quad, uvs, hb)
    m.face([(x, -s, z0) for x, s in outline], [cell('UNDER')] * len(outline), (0, -(s_back + 0.3), z1))
    if LODS[lod]['coupler']:
        sf = s_tip - setback(0, 0.5)
        box(m, (-0.12, -(sf + 0.28), 0.42), (0.12, -(sf - 0.05), 0.62), cell('COUPLER'))


def wheel(m, x, s, sides):
    r, w = WHEEL['r'], WHEEL['w']
    c = (x, -s, r)
    rings = []
    for side in (-1, 1):
        rings.append([(x + side * w / 2, -s + r * math.cos(2 * math.pi * i / sides),
                       r + r * math.sin(2 * math.pi * i / sides)) for i in range(sides)])
    uv = cell('WHEEL')
    for i in range(sides):
        i1 = (i + 1) % sides
        m.face([rings[0][i], rings[0][i1], rings[1][i1], rings[1][i]], [uv] * 4, c)
    for ring in rings:
        m.face(ring, [uv] * sides, c)


def underframe(m, length, lod, s_front_bogie, s_rear_bogie):
    L = LODS[lod]
    if L['bogies']:
        for sb in (s_rear_bogie, s_front_bogie):
            hl, hw = BOGIE['half_l'], BOGIE['half_w']
            box(m, (-hw, -(sb + hl), BOGIE['z'][0]), (hw, -(sb - hl), BOGIE['z'][1]), cell('BOGIE'), skip=('+Z',))
            for ds in (-BOGIE['axle'], BOGIE['axle']):
                for sx in (-1, 1):
                    wheel(m, sx * WHEEL['x'], sb + ds, L['wheel_sides'])
    s0 = s_rear_bogie + BOGIE['half_l'] + 0.4
    s1 = s_front_bogie - BOGIE['half_l'] - 0.4
    box(m, (-1.08, -s1, 0.45), (1.08, -s0, 0.80), cell('UNDER'), skip=('+Z',))


def roof_units(m, length):
    for sc in (-length / 4, length / 4):
        box(m, (-0.85, -(sc + 1.4), 3.78), (0.85, -(sc - 1.4), 4.06), cell('AC'), skip=('-Z',))


def car(kind='end', lod=0):
    """kind 'end' (cab at the front, -Y) or 'mid'. Returns a bmesh."""
    m = Mesh()
    length = CAR['end_len'] if kind == 'end' else CAR['mid_len']
    region = 'SIDE_END' if kind == 'end' else 'SIDE_MID'
    s_rear, s_tip = -length / 2, length / 2
    s_body_front = s_tip - NOSE['len'] if kind == 'end' else s_tip
    ring_r = [(x, s_rear, z) for x, z in SEC]
    ring_f = [(x, s_body_front, z) for x, z in SEC]
    body_strip(m, region, length, ring_r, ring_f)
    flat_end(m, s_rear, -1, lod)
    if kind == 'end':
        nose(m, s_tip, lod, length)
    else:
        flat_end(m, s_tip, 1, lod)
    inset = BOGIE['inset']
    underframe(m, length, lod, s_tip - inset - (0.4 if kind == 'end' else 0.0), s_rear + inset)
    roof_units(m, length)
    return m.finish()


def tris(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)
