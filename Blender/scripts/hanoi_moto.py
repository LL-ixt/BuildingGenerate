"""MOTO — low-poly scooter (Honda SH) built from the traced side profile (moto_trace.py).

Geometry only (bmesh), no scene logic; build_moto.py drives it.

Conventions (Blender, metres): bike front = -Y (Unity +Z after the FBX axis swap), up = +Z,
origin = ground, midway between the two tyre contact points. Profile coords from the json:
u = forward, z = up  ->  Y = -u, Z = z.  Rider's right = -X (the photo shows the right side).

One material, M_HanoiMoto, on a 1024 atlas (build_moto_atlas.py): most faces point at one of the
8 slot cells of the palette strip (slot PAINT is tinted per instance); wheels and springs carry
real UVs into the wheel / spring / tread tiles.
"""
import json
import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

ATLAS_JSON = os.path.join(r"D:\Project III\BuildingGenerate", "Blender", "moto", "atlas.json")
ATLAS = json.load(open(ATLAS_JSON, encoding='utf-8'))     # written by build_moto_atlas.py
SLOTS = ATLAS['slots']
REGIONS = ATLAS['regions']

# common Hanoi scooter colours (sRGB); index picked by a position hash in Unity
PAINT_COLOURS = [(64, 92, 70), (232, 232, 228), (22, 22, 24), (150, 20, 24),
                 (120, 122, 124), (110, 84, 60), (28, 54, 110), (200, 196, 182)]

# shell recipe per traced part: width taper along the part's length (t: 0 = rear, 1 = front)
# and height (s: 0 = bottom, 1 = top), bevel = (edge round radius m, rings of vertices in it),
# pillow = (unused, height m): extra smooth dome towards the middle of big panels.
PART_STYLE = {
    'SEAT':         dict(bevel=(0.045, 2), t=[(0, 0.62), (0.45, 1.0), (1, 0.82)], s=[(0, 0.9), (1, 1.0)],
                         pillow=(0.10, 0.012)),
    'RACK':         dict(bevel=(0.008, 1), t=[(0, 0.75), (1, 1.0)]),
    'TAIL_LIGHT':   dict(bevel=(0.015, 1), t=[(0, 0.55), (1, 1.0)]),
    'BODY_REAR':    dict(bevel=(0.04, 2), t=[(0, 0.5), (0.35, 0.95), (0.75, 1.0), (1, 0.9)],
                         s=[(0, 0.82), (0.6, 1.0), (1, 0.92)], pillow=(0.12, 0.015)),
    'BODY_FRONT':   dict(bevel=(0.05, 2), s=[(0, 0.82), (0.45, 1.0), (1, 0.85)],
                         pillow=(0.12, 0.02), carve=dict(nose=0.08, d0=0.06, d1=0.12, dz=0.06)),
    'HEADLIGHT':    dict(bevel=(0.02, 1)),
    'FRONT_FENDER': dict(width=0.16, bevel=(0.045, 2)),
    'HANDLE_COVER': dict(width=0.46, bevel=(0.04, 2), t=[(0, 1.0), (0.5, 0.95), (1, 0.6)],
                         s=[(0, 0.55), (0.6, 1.0), (1, 0.9)],
                         pillow=(0.06, 0.01)),
    'NECK':         dict(bevel=(0.015, 1)),
    'LEG_INNER':    dict(bevel=(0.015, 1), s=[(0, 0.8), (1, 1.0)]),
    'FLOOR':        dict(bevel=(0.015, 1), t=[(0, 0.9), (1, 1.0)]),
    'UNDER_REAR':   dict(bevel=(0.02, 1), t=[(0, 0.7), (1, 1.0)]),
    'MUDGUARD':     dict(bevel=(0.015, 1), t=[(0, 0.7), (1, 1.0)]),
    'POWERTRAIN':   dict(bevel=(0.03, 1), pillow=(0.08, 0.01)),
    'EXHAUST':      dict(bevel=(0.045, 2), t=[(0, 0.8), (1, 1.0)]),
    'CVT_CASE':     dict(bevel=(0.025, 1)),
}

# Top view (Ref/xemay4.jpg, scooters 1 and 4 seen from above): half-width of the front end
# relative to its widest point, from the grips (t = 0) to the nose tip (t = 1). Applied to
# TOP_VIEW_PARTS by scaling each cross-section to fit (bevels keep their roundness).
TOP_VIEW = [(0, 1.0), (0.3, 1.0), (0.5, 0.92), (0.6, 0.73), (0.7, 0.55), (0.8, 0.43),
            (0.9, 0.32), (1.0, 0.24)]
TOP_VIEW_HALF = 0.21          # m, widest half-width (handlebar 0.70 m = 90 px -> 7.8 mm/px)
TOP_VIEW_PARTS = {'BODY_FRONT', 'HEADLIGHT', 'FRONT_FENDER', 'NECK', 'LEG_INNER'}
# (the handlebar cover is wider than the shield: wings ~0.48 m in Ref/xemayfront.png)


def top_view_limit(u0, u1):
    """u -> max half-width of the front end; u0 = grips, u1 = nose tip (profile u)."""
    return lambda u: TOP_VIEW_HALF * interp(TOP_VIEW, (u - u0) / (u1 - u0))


def front_carve(polys, z_cut, nose, d0, d1, dz):
    """Front view (Ref/xemayfront.png): below the headlight (z < z_cut) the front shield is
    hollowed on both sides, leaving a central nose of half-width `nose` for the first d0 m behind
    the shield's front edge, opening back to full width over d1 m; blends in over dz in height.
    Returns (u, z) -> half-width limit."""
    def front_edge(z):
        best = -1e9
        for poly in polys:
            for (ua, za), (ub, zb) in zip(poly, poly[1:] + poly[:1]):
                if (za > z) != (zb > z):
                    best = max(best, ua + (z - za) * (ub - ua) / (zb - za))
        return best

    def limit(u, z):
        below = 1.0 - _smooth((z - (z_cut - dz)) / dz)
        if below <= 0:
            return 1e9
        e = front_edge(z) - u
        lim = nose + (TOP_VIEW_HALF - nose) * _smooth((e - d0) / d1)
        return lim + (1 - below) * (2 * TOP_VIEW_HALF - lim)    # above the cut: no limit

    def in_recess(u, z):
        """Walls of the hollow (shown black like the inner shield in the photo)."""
        e = front_edge(z) - u
        return z < z_cut - dz * 0.3 and d0 * 0.5 < e < d0 + d1
    limit.in_recess = in_recess
    return limit


WHEEL = {   # tyre section height / width (m)
    'front': dict(section=0.075, width=0.10),
    'rear':  dict(section=0.085, width=0.12),
}
WHEEL_SEGS = 20


def slot_uv(slot):
    u0, v0, u1, v1 = REGIONS['palette']
    return (u0 + (u1 - u0) * (SLOTS.index(slot) + 0.5) / len(SLOTS), (v0 + v1) / 2)


def region_uv(region, u, v):
    """(u, v) in 0..1 inside an atlas tile -> atlas UV."""
    u0, v0, u1, v1 = REGIONS[region]
    return (u0 + (u1 - u0) * u, v0 + (v1 - v0) * v)


def to_xyz(u, z, x=0.0):
    return Vector((x, -u, z))


def interp(table, t):
    if not table:
        return 1.0
    if t <= table[0][0]:
        return table[0][1]
    for (t0, f0), (t1, f1) in zip(table, table[1:]):
        if t <= t1:                                    # smoothstep: no creases at the keys
            x = (t - t0) / max(t1 - t0, 1e-9)
            return f0 + (f1 - f0) * x * x * (3 - 2 * x)
    return table[-1][1]


# ---------------------------------------------------------------- mesh accumulation
class Parts:
    """Collects bmesh pieces with a slot each; to_mesh() joins them into one object mesh."""

    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new('UVMap')

    def add(self, bm_piece, slot, matrix=None):
        if matrix is not None:
            bm_piece.transform(matrix)
        me = bpy.data.meshes.new('_tmp')
        bm_piece.to_mesh(me)
        bm_piece.free()
        n0 = len(self.bm.faces)
        override = [p.value for p in me.attributes['slot'].data] if 'slot' in me.attributes else None
        own_uv = len(me.uv_layers) > 0                 # textured piece: keep its UVs
        self.bm.from_mesh(me)
        bpy.data.meshes.remove(me)
        self.bm.faces.ensure_lookup_table()
        uv = slot_uv(slot)
        for k, f in enumerate(self.bm.faces[n0:]):
            if own_uv:
                continue
            fuv = slot_uv(SLOTS[override[k]]) if override and override[k] >= 0 else uv
            for l in f.loops:
                l[self.uv].uv = fuv

    def to_mesh(self, name, mat, sharp_deg=55):
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        me.materials.append(mat)
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(sharp_deg))
        return me


def tris(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


# ---------------------------------------------------------------- traced parts
def signed_area(poly):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))


def _seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return (a + ab * t - p).length


def _outline_dist(p, pts):
    return min(_seg_dist(p, pts[i - 1], pts[i]) for i in range(len(pts)))


def _inside(p, pts):
    c = False
    for i in range(len(pts)):
        a, b = pts[i - 1], pts[i]
        if (a.y > p.y) != (b.y > p.y) and p.x < a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y):
            c = not c
    return c


def _smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def extrude_profile(poly, width, offset=0.0, bevel=(0.02, 1), t=None, s=None, pillow=None, top=None,
                    grid=0.055, carve=None):
    """Profile polygon [(u, z)] -> closed rounded shell of `width` (X).

    The side faces are a constrained Delaunay triangulation of the outline plus inner points
    (rings along the outline + a grid). Each vertex is pushed out by its true distance d to the
    outline: x = h_edge + r*sin(d/r * pi/2) (round edge of radius r = bevel[0], bevel[1] rings)
    + pillow: a membrane under pressure (graph Poisson solve, 0 on the outline) scaled so its
    top is the pillow height -> one smooth dome, no ridges. Always a valid surface, even in thin or
    concave spots (no inset/bevel overlaps). Then the width tapers by the t / s tables and the
    top-view limit (top = u -> max half-width). Returns a triangulated bmesh."""
    from mathutils.geometry import delaunay_2d_cdt
    if signed_area(poly) < 0:
        poly = poly[::-1]
    h = width / 2
    r, rings = bevel
    ph = pillow[1] if pillow else 0.0
    r = max(0.002, min(r, h * 0.8)) if rings > 0 else 1e-4    # rings 0: flat slab (far LOD)
    h_edge = max(0.002, h - r - ph)
    pts = [Vector(p) for p in poly]
    n = len(pts)

    extra = []

    def try_add(q, need, spacing):
        if _inside(q, pts) and _outline_dist(q, pts) >= need and                 all((q - e).length >= spacing for e in extra):
            extra.append(q)

    for k in range(1, rings + 1):                      # rings along the inward vertex normals
        d = r * (k / rings) * 0.95
        for i in range(n):
            e0, e1 = pts[i] - pts[i - 1], pts[(i + 1) % n] - pts[i]
            nin = Vector((-e0.y, e0.x)).normalized() + Vector((-e1.y, e1.x)).normalized()
            if nin.length < 1e-6:
                continue
            try_add(pts[i] + nin.normalized() * d, 0.7 * d, 0.5 * d)
    us = [p.x for p in pts]
    zs = [p.y for p in pts]
    u0, u1, z0, z1 = min(us), max(us), min(zs), max(zs)
    gu = u0 + grid / 2 if grid else u1
    while gu < u1:                                     # interior grid
        gz = z0 + grid / 2
        while gz < z1:
            try_add(Vector((gu, gz)), max(r, 0.5 * grid), 0.6 * grid)
            gz += grid
        gu += grid

    coords, _, faces, orig, _, _ = delaunay_2d_cdt(
        pts + extra, [(i, (i + 1) % n) for i in range(n)], [list(range(n))], 1, 1e-6)
    in_to_out = {}
    for o, ins in enumerate(orig):
        for i in ins:
            in_to_out[i] = o

    def xof(o):
        if any(i < n for i in orig[o]):
            return h_edge
        d = _outline_dist(Vector(coords[o]), pts)
        return h_edge + r * math.sin(min(d / r, 1.0) * math.pi / 2)

    xs = [xof(o) for o in range(len(coords))]
    if ph > 0:                                         # pillow membrane
        nb = [set() for _ in coords]
        for f in faces:
            for a in f:
                nb[a].update(b for b in f if b != a)
        fixed = [any(i < n for i in orig[o]) for o in range(len(coords))]
        P = [0.0] * len(coords)
        for _ in range(200):
            P = [0.0 if fixed[o] or not nb[o] else sum(P[j] for j in nb[o]) / len(nb[o]) + 1.0
                 for o in range(len(coords))]
        top_p = max(P) or 1.0
        xs = [x + ph * (p / top_p) for x, p in zip(xs, P)]
    nb = [set() for _ in coords]                       # relax the distance-field ridges
    for f in faces:
        for a in f:
            nb[a].update(b for b in f if b != a)
    edge = [any(i < n for i in orig[o]) for o in range(len(coords))]
    for _ in range(4):
        xs = [x if edge[o] or not nb[o] else 0.5 * x + 0.5 * sum(xs[j] for j in nb[o]) / len(nb[o])
              for o, x in enumerate(xs)]
    bm = bmesh.new()
    side_v = {}
    for side in (-1, 1):
        side_v[side] = [bm.verts.new(to_xyz(c[0], c[1], side * x)) for c, x in zip(coords, xs)]
    for f in faces:
        for side in (-1, 1):
            vs = [side_v[side][o] for o in f]
            try:
                bm.faces.new(vs if side > 0 else vs[::-1])
            except ValueError:
                pass
    for i in range(n):                                 # band around the outline
        a, b = in_to_out[i], in_to_out[(i + 1) % n]
        if a != b:
            try:
                bm.faces.new((side_v[-1][a], side_v[1][a], side_v[1][b], side_v[-1][b]))
            except ValueError:
                pass
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    for v in bm.verts:
        tt = (-v.co.y - u0) / max(u1 - u0, 1e-6)
        ss = (v.co.z - z0) / max(z1 - z0, 1e-6)
        f = interp(t, tt) * interp(s, ss)
        if top is not None:
            f *= min(1.0, top(-v.co.y) / h)
        if carve is not None:                          # (u, z) -> half-width limit
            f *= min(1.0, carve(-v.co.y, v.co.z) / h)
        v.co.x = offset + v.co.x * f
    if carve is not None:                              # per-face slot: hollow walls -> PLASTIC
        lay = bm.faces.layers.int.new('slot')
        for fc in bm.faces:
            vs = fc.verts
            hollow = sum(carve.in_recess(-v.co.y, v.co.z) for v in vs) >= 2 and                 min(abs(v.co.x - offset) for v in vs) > 0.03
            fc[lay] = SLOTS.index('PLASTIC') if hollow else -1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def simplify_poly(poly, tol):
    """Ramer-Douglas-Peucker on a closed polygon [(u, z)] (keeps >= 4 points)."""
    if tol <= 0 or len(poly) <= 4:
        return poly
    pts = [Vector(p) for p in poly]
    i0 = 0
    i1 = max(range(len(pts)), key=lambda i: (pts[i] - pts[i0]).length)

    def rdp(a, b):                                      # indices along the ring a -> b
        idx = [(a + k) % len(pts) for k in range((b - a) % len(pts) + 1)]
        if len(idx) < 3:
            return [idx[0]]
        far = max(idx[1:-1], key=lambda i: _seg_dist(pts[i], pts[idx[0]], pts[idx[-1]]))
        if _seg_dist(pts[far], pts[idx[0]], pts[idx[-1]]) <= tol:
            return [idx[0]]
        return rdp(idx[0], far) + rdp(far, idx[-1])
    keep = rdp(i0, i1) + rdp(i1, i0)
    if len(keep) < 4:                                   # too coarse for a small part: retry finer
        return simplify_poly(poly, tol * 0.5) if tol > 0.004 else poly
    return [poly[i] for i in keep]


def capsule(c0, r0, c1, r1, n=10):
    """Convex hull of two circles in the profile plane (u, z) -> polygon."""
    pts = []
    for (cu, cz), r in ((c0, r0), (c1, r1)):
        for k in range(n * 2):
            a = 2 * math.pi * k / (n * 2)
            pts.append((cu + r * math.cos(a), cz + r * math.sin(a)))
    pts = sorted(set(pts))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


# ---------------------------------------------------------------- procedural pieces
def cylinder(p0, p1, r, segs=8, caps=True, r1=None, uv_region=None):
    """Tube between two points (world vectors); r1 = end radius (cone).
    uv_region: atlas tile wrapped around the side (u = around, v = p0 -> p1)."""
    p0, p1 = Vector(p0), Vector(p1)
    bm = bmesh.new()
    axis = p1 - p0
    q = axis.to_track_quat('Z', 'Y')
    m = Matrix.Translation(p0) @ q.to_matrix().to_4x4()
    r1 = r if r1 is None else r1
    ring0, ring1 = [], []
    for k in range(segs):
        a = 2 * math.pi * k / segs
        ring0.append(bm.verts.new(m @ Vector((r * math.cos(a), r * math.sin(a), 0))))
        ring1.append(bm.verts.new(m @ Vector((r1 * math.cos(a), r1 * math.sin(a), axis.length))))
    uvl = bm.loops.layers.uv.new('UVMap') if uv_region else None
    for k in range(segs):
        j = (k + 1) % segs
        f = bm.faces.new((ring0[k], ring0[j], ring1[j], ring1[k]))
        if uvl:
            for l, (uu, vv) in zip(f.loops, ((k, 0), (k + 1, 0), (k + 1, 1), (k, 1))):
                l[uvl].uv = region_uv(uv_region, uu / segs, vv)
    if caps and not uv_region:
        bm.faces.new(ring0[::-1])
        bm.faces.new(ring1)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def ellipsoid(centre, size, segs=8, rings=5):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=0.5)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(centre), verts=bm.verts)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    return bm


def box(centre, size):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(centre), verts=bm.verts)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    return bm


def lathe(profile, segs, closed=False):
    """Revolve [(r, x)] around the X axis (wheel axle). Returns bmesh."""
    bm = bmesh.new()
    rings = []
    for k in range(segs):
        a = 2 * math.pi * k / segs
        ca, sa = math.cos(a), math.sin(a)
        rings.append([bm.verts.new((x, r * ca, r * sa)) for r, x in profile])
    n = len(profile)
    for k in range(segs):
        j = (k + 1) % segs
        for i in range(n if closed else n - 1):
            i2 = (i + 1) % n
            bm.faces.new((rings[k][i], rings[k][i2], rings[j][i2], rings[j][i]))
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def wheel(radius, section, width, segs=WHEEL_SEGS, simple=False):
    """Wheel around its own axle (origin, axis X): lathed tyre + a two-sided rim disc in the
    middle plane. Sidewalls and disc are planar-mapped onto the wheel tile (5 twin spokes, brake
    disc, red stripe; alpha 0 between the spokes -> clipped), the tread onto the tread tile.
    Returns [(bmesh, slot)]."""
    R, s, w = radius, section, width
    rin = R - s
    rt = R / ATLAS['wheel_radius_frac']               # tile half-size in metres

    def photo(y, z):
        return region_uv('wheel', 0.5 + 0.5 * (-y) / rt, 0.5 + 0.5 * z / rt)

    prof = [(rin + 0.005, -0.40 * w), (R - 0.5 * s, -0.50 * w), (R, -0.3 * w),
            (R, 0.3 * w), (R - 0.5 * s, 0.50 * w), (rin + 0.005, 0.40 * w)]
    if simple:                                          # far LOD: square tyre section
        prof = [(rin + 0.005, -0.42 * w), (R, -0.42 * w), (R, 0.42 * w), (rin + 0.005, 0.42 * w)]
    tread = (len(prof) - 1) // 2
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new('UVMap')
    rings = []
    for k in range(segs + 1):
        a = 2 * math.pi * k / segs
        rings.append([(x, r * math.cos(a), r * math.sin(a)) for r, x in prof])
    verts = [[bm.verts.new(p) for p in ring] for ring in rings[:-1]]
    for k in range(segs):
        j = (k + 1) % segs
        for i in range(len(prof) - 1):
            f = bm.faces.new((verts[k][i], verts[k][i + 1], verts[j][i + 1], verts[j][i]))
            corners = ((k, i), (k, i + 1), (k + 1, i + 1), (k + 1, i))
            for l, (kk, ii) in zip(f.loops, corners):
                if i == tread:                          # tread band
                    l[uvl].uv = region_uv('tread', ii - tread, kk - k)
                else:
                    _, y, z = rings[kk][ii]
                    l[uvl].uv = photo(y, z)
    rd = rin + 0.012
    for side in (-1, 1):                                # one rim disc in the middle plane, both faces
        x = side * 0.002                                # (alpha-clipped: see-through between spokes)
        ring = [bm.verts.new((x, rd * math.cos(2 * math.pi * k / segs), rd * math.sin(2 * math.pi * k / segs)))
                for k in range(segs)]
        f = bm.faces.new(ring if side > 0 else ring[::-1])
        for l in f.loops:
            l[uvl].uv = photo(l.vert.co.y, l.vert.co.z)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return [(bm, 'TIRE')]
