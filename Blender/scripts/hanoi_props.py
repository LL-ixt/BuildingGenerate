"""PROPS — street props with real UVs into the props atlas (build_props_texture.py):
    power pole  concrete pole (red / white bands at the foot, baked in the texture) + pale yellow box
    sign_ngo    red / white striped pipe + blue "NGÕ" plate
Geometry only (bmesh); build_props.py drives it.

Conventions (Blender, metres): origin = ground at the pole axis, up = +Z; the box / the plate face
the street at -Y (Unity +Z after the FBX axis swap). One material, M_HanoiProps.
Every builder takes lod: 0 = close-up, 1 = mid / far (fewer sides, no straps / clamps).
"""
import json
import math

import bmesh
from mathutils import Vector

ATLAS_JSON = r"D:\Project III\BuildingGenerate\Blender\props\atlas.json"
ATLAS = json.load(open(ATLAS_JSON, encoding='utf-8'))
REGIONS = ATLAS['regions']

POLE = dict(h=ATLAS['pole_h'], r0=0.17, r1=0.10)            # base / top radius (spun concrete, slight taper)
BOX = dict(w=0.42, d=0.20, z=tuple(ATLAS['box_z']), gap=0.035, cap=0.02)
SIGN = dict(h=ATLAS['signpole_h'], r=0.032, plate=(0.62, 0.31, 0.012), z_top=2.76, gap=0.015)
LODS = {
    0: dict(pole_segs=16, pipe_segs=12, straps=True),
    1: dict(pole_segs=8, pipe_segs=6, straps=False),
}


def ruv(region, u, v):
    """(u, v) 0..1 inside an atlas region -> atlas UV."""
    u0, v0, u1, v1 = REGIONS[region]
    return (u0 + (u1 - u0) * u, v0 + (v1 - v0) * v)


class Mesh:
    """Faces with per-corner UVs, turned into one bmesh."""

    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new('UVMap')

    def face(self, pts, uvs):
        vs = [self.bm.verts.new(p) for p in pts]
        f = self.bm.faces.new(vs)
        for l, uv in zip(f.loops, uvs):
            l[self.uv].uv = uv
        return f

    def quad_grid(self, rings, uvs):
        """rings[i][k] points, uvs[i][k]: quads between consecutive rings (shared verts)."""
        vs = [[self.bm.verts.new(p) for p in ring] for ring in rings]
        for i in range(len(rings) - 1):
            for k in range(len(rings[i]) - 1):
                f = self.bm.faces.new((vs[i][k], vs[i][k + 1], vs[i + 1][k + 1], vs[i + 1][k]))
                for l, (ii, kk) in zip(f.loops, ((i, k), (i, k + 1), (i + 1, k + 1), (i + 1, k))):
                    l[self.uv].uv = uvs[ii][kk]

    def finish(self):
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-6)   # closes the tube seams
        return self.bm                      # faces are built counter-clockwise from outside


# ---------------------------------------------------------------- pieces
def tube(m, z0, z1, r0, r1, segs, region, v0, v1, centre=(0, 0), u_turns=1.0):
    """Side of a (tapered) cylinder along Z, seam at +X; u = around (0.75 faces -Y)."""
    cx, cy = centre
    rings, uvs = [], []
    for z, r, v in ((z0, r0, v0), (z1, r1, v1)):
        ring, uv = [], []
        for k in range(segs + 1):
            a = 2 * math.pi * k / segs
            ring.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
            uv.append(ruv(region, u_turns * k / segs, v))
        rings.append(ring); uvs.append(uv)
    m.quad_grid(rings, uvs)


def cap(m, z, r, segs, region, uv_centre, uv_r, centre=(0, 0), dome=0.0):
    """Top disc (fan, optional dome height) mapped onto a small circle of the region."""
    cx, cy = centre
    tip = (cx, cy, z + dome)
    for k in range(segs):
        a0, a1 = 2 * math.pi * k / segs, 2 * math.pi * (k + 1) / segs
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0), z)
        p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1), z)
        uc = ruv(region, *uv_centre)
        u0 = ruv(region, uv_centre[0] + uv_r * math.cos(a0), uv_centre[1] + uv_r * math.sin(a0))
        u1 = ruv(region, uv_centre[0] + uv_r * math.cos(a1), uv_centre[1] + uv_r * math.sin(a1))
        m.face((p0, p1, tip), (u0, u1, uc))


def block(m, lo, hi, faces):
    """Axis-aligned box lo..hi; faces = {'-Y': (region, (u0, v0, u1, v1)), ...} for the six sides
    (key 'all' = default). Each face maps its rectangle with u to the viewer's right, v up."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    sides = {   # corners counter-clockwise seen from outside: bottom-left, bottom-right, top-right, top-left
        '-Y': ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)),
        '+Y': ((x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)),
        '+X': ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)),
        '-X': ((x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)),
        '+Z': ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)),
        '-Z': ((x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)),
    }
    for key, pts in sides.items():
        spec = faces.get(key, faces.get('all'))
        if spec is None:
            continue
        region, (u0, v0, u1, v1) = spec
        m.face(pts, [ruv(region, u, v) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))])


def pole_r(z):
    return POLE['r0'] + (POLE['r1'] - POLE['r0']) * z / POLE['h']


# ---------------------------------------------------------------- props
def power_pole(lod=0):
    """Concrete pole + pale yellow box on the street side (-Y), strapped to the pole."""
    L = LODS[lod]
    m = Mesh()
    H, n = POLE['h'], L['pole_segs']
    # u offset: the texture's u 0.75 (rust drip under the box) must face -Y -> seam at +X works
    tube(m, 0.0, H, POLE['r0'], POLE['r1'], n, 'POLE', 0.0, 1.0)
    cap(m, H, POLE['r1'], n, 'POLE', (0.5, 0.985), 0.012)
    zb, zt = BOX['z']
    yb = -(pole_r((zb + zt) / 2) + BOX['gap'])          # box back
    yf = yb - BOX['d']
    w2 = BOX['w'] / 2
    plain = ('BOX', (0.08, 0.30, 0.30, 0.62))            # a clean painted patch for the small sides
    block(m, (-w2, yf, zb), (w2, yb, zt), {'-Y': ('BOX', (0, 0, 1, 1)), 'all': plain})
    c = BOX['cap']                                       # rain cap, overhanging the front and sides
    block(m, (-w2 - c, yf - c * 1.5, zt), (w2 + c, yb, zt + c), {'all': plain})
    if L['straps']:
        for z in (zb + 0.10, zt - 0.10):
            r = pole_r(z) + 0.004
            tube(m, z - 0.015, z + 0.015, r, r, n, 'METAL', 0.1, 0.9)
            block(m, (-0.025, yb + 0.002, z - 0.015), (0.025, -pole_r(z) + 0.01, z + 0.015),
                  {'all': ('METAL', (0.1, 0.1, 0.9, 0.9))})
    return m.finish()


def sign_ngo(lod=0):
    """Striped pipe with the plate on its +X side, text facing -Y (and readable from +Y)."""
    L = LODS[lod]
    m = Mesh()
    H, r, n = SIGN['h'], SIGN['r'], L['pipe_segs']
    tube(m, 0.0, H, r, r, n, 'SIGNPOLE', 0.0, 1.0)
    cap(m, H, r, n, 'SIGNPOLE', (0.5, 0.995), 0.004, dome=0.012)
    pw, ph, pt = SIGN['plate']
    x0 = r + SIGN['gap']
    z1 = SIGN['z_top']
    z0 = z1 - ph
    edge = ('METAL', (0.2, 0.2, 0.8, 0.8))
    block(m, (x0, -pt / 2, z0), (x0 + pw, pt / 2, z1),
          {'-Y': ('SIGN', (0, 0, 1, 1)), '+Y': ('SIGN', (0, 0, 1, 1)), 'all': edge})
    if L['straps']:
        for z in (z0 + 0.06, z1 - 0.06):
            tube(m, z - 0.015, z + 0.015, r + 0.004, r + 0.004, n, 'METAL', 0.1, 0.9)
            block(m, (r, -0.012, z - 0.015), (x0 + 0.02, 0.012, z + 0.015), {'all': edge})
    return m.finish()


def tris(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)
