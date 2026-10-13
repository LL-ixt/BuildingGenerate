"""METRO — elevated viaduct kit (Ref/cot.jpg, Ref/cot_shape.png, Ref/overallview.jpeg, Ref/metro1.jpg):
    pier      chamfered rectangular column + funnel cap (flares out, folds back in just below the top,
              as in cot_shape.png) + bearings + red / white striped planter kerb at the foot
    deck      cross-section profiles swept along the line (Unity MetroBuilder; build_metro.py sweeps
              them in Blender only for the preview): box girder, parapets, noise barrier, rail
              plinths, rails, yellow cable troughs; posts every POST_STEP m
Geometry only (bmesh); build_metro.py drives it.

Conventions (Blender, metres): ground = z 0, the line runs along +Y, +X = right of travel.
Pier parts all have their origin on the ground at the pier axis (export_fbx snaps children to the
root); the column is built for the default height and stretched in Unity when the ground or the
rail level differs. Profiles are (x across, z up) relative to DECK_TOP, counter-clockwise.
Flat colours by material slot (MATS) until the texture step (V3).
"""
import math
import random

import bmesh
from mathutils import Vector

# ---------------------------------------------------------------- dimensions
RAIL_TOP = 12.0                 # m above the road
RAIL_H = 0.176                  # UIC60-ish rail height
PLINTH_H = 0.22                 # concrete rail plinth (ballastless track)
DECK_TOP = RAIL_TOP - RAIL_H - PLINTH_H      # 11.604: top of the girder slab
GIRDER_D = 2.0
GIRDER_BOTTOM = DECK_TOP - GIRDER_D           # 9.604
BEARING_H = 0.15
CAP_TOP = GIRDER_BOTTOM - BEARING_H           # 9.454
TRACK_SPACING = 4.0             # between track centres
GAUGE = 1.435
SPAN = 30.0                     # target pier spacing (Unity may slide 24..40)
POST_STEP = 2.0                 # barrier posts

COL = dict(w=2.6, d=2.0, ch=0.30)                       # across (X), along (Y), corner chamfer
CAP = dict(h=1.9, wide=(7.6, 2.8), wide_dz=0.45,        # widest ring 0.45 below the cap top
           top=(6.0, 2.5), ch_wide=0.40, ch_top=0.32)
CAP_BOTTOM = CAP_TOP - CAP['h']                          # 7.554 = column top
BEARING = dict(size=(0.7, 0.55), x=1.6, y=0.55)          # 4 pads: x +-1.6, y +-0.55 (one girder end each side)
FOOT = dict(w=4.0, d=3.4, t=0.22, h=0.30, soil=0.20, stripe=0.5)

# material slots (Unity remaps by name)
MATS = ['M_MetroConcrete', 'M_MetroBarrier', 'M_MetroSteel', 'M_MetroYellow',
        'M_MetroKerbRed', 'M_MetroKerbWhite', 'M_MetroSoil', 'M_MetroConcreteDark',
        'M_MetroGirder', 'M_MetroPier', 'M_MetroKerbStripe']
MAT_COLOURS = {   # linear base colour, roughness, metallic (Blender preview + Unity V2 stand-ins)
    'M_MetroConcrete':     ((0.42, 0.41, 0.38), 0.85, 0.0),
    'M_MetroConcreteDark': ((0.25, 0.25, 0.24), 0.9, 0.0),
    'M_MetroBarrier':      ((0.70, 0.73, 0.75), 0.45, 0.0),
    'M_MetroSteel':        ((0.35, 0.34, 0.32), 0.35, 0.9),
    'M_MetroYellow':       ((0.75, 0.52, 0.06), 0.6, 0.0),
    'M_MetroKerbRed':      ((0.55, 0.05, 0.04), 0.7, 0.0),
    'M_MetroKerbWhite':    ((0.75, 0.75, 0.72), 0.7, 0.0),
    'M_MetroSoil':         ((0.06, 0.09, 0.03), 0.95, 0.0),
    'M_MetroGirder':       ((0.42, 0.41, 0.38), 0.85, 0.0),
    'M_MetroPier':         ((0.42, 0.41, 0.38), 0.85, 0.0),
    'M_MetroKerbStripe':   ((0.55, 0.30, 0.28), 0.75, 0.0),
}
# V3 textures (build_metro_texture.py -> Export/Textures/Metro): albedo, OpenGL normal, base tint (linear)
TEX_DIR = r"D:\Project III\BuildingGenerate\Export\Textures\Metro"
MAT_TEX = {
    'M_MetroConcrete':     ('T_MetroConcrete.png', 'T_MetroConcrete_N.png', (1.0, 1.0, 1.0)),   # 4 m tiles
    'M_MetroConcreteDark': ('T_MetroConcrete.png', 'T_MetroConcrete_N.png', (0.55, 0.55, 0.55)),
    'M_MetroGirder':       ('T_MetroGirder.png', 'T_MetroGirder_N.png', (1.0, 1.0, 1.0)),       # u 8 m along, v around the profile
    'M_MetroPier':         ('T_MetroPier.png', 'T_MetroPier_N.png', (1.0, 1.0, 1.0)),           # u around, v = z / CAP_TOP
    'M_MetroBarrier':      ('T_MetroBarrier.png', 'T_MetroBarrier_N.png', (1.0, 1.0, 1.0)),     # one 2 m panel between posts
    'M_MetroKerbStripe':   ('T_MetroKerbStripe.png', '', (1.0, 1.0, 1.0)),                      # red / white, 1 m period
}
GIRDER_U_LEN = 8.0          # m of girder per texture repeat
MI = {m: i for i, m in enumerate(MATS)}


# ---------------------------------------------------------------- deck profiles
def _mirror(pts):
    """Mirror x -> -x and keep counter-clockwise order."""
    return [(-x, z) for x, z in reversed(pts)]


def _box(x0, z0, x1, z1):
    return [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]


def _rail(xc):
    """Simplified flat-bottom rail, base on the plinth top (z = PLINTH_H)."""
    z0, h = PLINTH_H, RAIL_H
    f, w, hd = 0.075, 0.009, 0.036          # half foot, half web, half head
    return [(xc - f, z0), (xc + f, z0), (xc + f, z0 + 0.012), (xc + w, z0 + 0.03),
            (xc + w, z0 + h - 0.05), (xc + hd, z0 + h - 0.04), (xc + hd, z0 + h),
            (xc - hd, z0 + h), (xc - hd, z0 + h - 0.04), (xc - w, z0 + h - 0.05),
            (xc - w, z0 + 0.03), (xc - f, z0 + 0.012)]


HALF_W = 4.7          # deck half width
PARAPET = dict(t=0.30, h=0.55)                 # concrete upstand at the edge
BARRIER = dict(t=0.06, h=2.0, inset=0.10)      # panel plane 0.10 m inside the parapet outer face
GIRDER = [(HALF_W, -0.55), (HALF_W, 0.0), (-HALF_W, 0.0), (-HALF_W, -0.55),    # 0.55 m vertical fascia
          (-3.2, -0.75), (-2.35, -GIRDER_D), (2.35, -GIRDER_D), (3.2, -0.75)]


def deck_profiles():
    """name -> dict(mat, lods (max LOD that still has it), closed, pts). Mirrored pieces get _L/_R."""
    P = {}

    def add(name, mat, lods, pts, mirror=False, closed=True):
        if mirror:
            P[name + '_R'] = dict(mat=mat, lods=lods, closed=closed, pts=pts)
            P[name + '_L'] = dict(mat=mat, lods=lods, closed=closed, pts=_mirror(pts))
        else:
            P[name] = dict(mat=mat, lods=lods, closed=closed, pts=pts)

    add('girder', 'M_MetroGirder', 2, GIRDER)
    pt, ph = PARAPET['t'], PARAPET['h']
    add('parapet', 'M_MetroConcrete', 1, _box(HALF_W - pt, 0.0, HALF_W, ph), mirror=True)
    bx = HALF_W - BARRIER['inset'] - BARRIER['t']
    add('barrier', 'M_MetroBarrier', 1, _box(bx, ph, bx + BARRIER['t'], ph + BARRIER['h']), mirror=True)
    add('barrier_cap', 'M_MetroSteel', 0, _box(bx - 0.03, ph + BARRIER['h'], bx + BARRIER['t'] + 0.03,
                                                ph + BARRIER['h'] + 0.06), mirror=True)
    for tx, tag in ((-TRACK_SPACING / 2, 'A'), (TRACK_SPACING / 2, 'B')):
        for side in (-1, 1):
            xc = tx + side * GAUGE / 2
            add(f'plinth_{tag}{"LR"[side > 0]}', 'M_MetroConcreteDark', 1,
                _box(xc - 0.30, 0.0, xc + 0.30, PLINTH_H))
            add(f'rail_{tag}{"LR"[side > 0]}', 'M_MetroSteel', 0, _rail(xc))
    # yellow cable trough covers: centre walkway + one beside each outer track
    add('trough_C', 'M_MetroYellow', 0, _box(-0.30, 0.0, 0.30, 0.28))
    add('trough', 'M_MetroYellow', 0, _box(3.25, 0.0, 3.80, 0.28), mirror=True)
    # LOD2: girder + barriers as one U (no rails); parapet + barrier merged into a solid wall
    top = ph + BARRIER['h']
    P['lod2_shell'] = dict(mat='M_MetroConcrete', lods=(2, 2), closed=True, pts=[
        (HALF_W, -0.55), (HALF_W, top), (bx, top), (bx, 0.0), (-bx, 0.0), (-bx, top), (-HALF_W, top),
        (-HALF_W, -0.55), (-3.2, -0.75), (-2.35, -GIRDER_D), (2.35, -GIRDER_D), (3.2, -0.75)])
    P['girder']['lods'] = (0, 1)
    # UV modes (Unity MetroBuilder + sweep() below): 'perimeter' u = s / 4, v = profile arc / 4 (tiled
    # concrete); 'fraction' u = s / u_len, v = profile arc / whole perimeter (profile atlas: the girder
    # texture knows where the fascia is); 'height' u = (s - u_off) / u_len, v = (y - ymin) / (ymax - ymin)
    P['girder']['uv'] = dict(mode='fraction', u_len=GIRDER_U_LEN, u_off=0.0)
    for side in 'LR':                            # panels end at the posts (s = 1, 3, 5 ...)
        P['barrier_' + side]['uv'] = dict(mode='height', u_len=POST_STEP, u_off=POST_STEP / 2)
    for k, v in P.items():                       # normalise lods to (min, max)
        if isinstance(v['lods'], int):
            v['lods'] = (0, v['lods'])
        v.setdefault('uv', dict(mode='perimeter', u_len=4.0, u_off=0.0))
    return P


POST = dict(w=0.16, d=0.12)        # H post behind the barrier panel (inside face), parapet top -> barrier top


# ---------------------------------------------------------------- mesh builder
class Mesh:
    def __init__(self):
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new('UVMap')
        self.has_uv = self.bm.faces.layers.int.new('has_uv')     # 1 = explicit UVs, box projection skips it

    def face(self, pts, mat, uvs=None):
        vs = [self.bm.verts.new(p) for p in pts]
        f = self.bm.faces.new(vs)
        f.material_index = MI[mat]
        if uvs:
            for l, uv in zip(f.loops, uvs):
                l[self.uv].uv = uv
            f[self.has_uv] = 1
        return f

    def finish(self, box_uv=True):
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-5)
        if box_uv:
            auto_uv(self.bm, self.uv, skip=self.has_uv)
        self.bm.faces.layers.int.remove(self.has_uv)
        return self.bm


def auto_uv(bm, uv, scale=0.25, skip=None):
    """Box projection, 4 m per UV unit (tiled concrete in V3)."""
    for f in bm.faces:
        if skip is not None and f[skip]:
            continue
        n = f.normal if f.normal.length > 0 else Vector((0, 0, 1))
        ax = max(range(3), key=lambda i: abs(n[i]))
        for l in f.loops:
            c = l.vert.co
            if ax == 2:
                l[uv].uv = (c.x * scale, c.y * scale)
            elif ax == 0:
                l[uv].uv = (c.y * scale * (1 if n.x > 0 else -1), c.z * scale)
            else:
                l[uv].uv = (c.x * scale * (-1 if n.y > 0 else 1), c.z * scale)


def chamfer_rect(w, d, c, z):
    """8 corners of a w x d rectangle with 45 deg chamfers c, counter-clockwise seen from +Z."""
    x, y = w / 2, d / 2
    return [(x, -y + c, z), (x, y - c, z), (x - c, y, z), (-x + c, y, z),
            (-x, y - c, z), (-x, -y + c, z), (-x + c, -y, z), (x - c, -y, z)]


def ring_u(ring):
    """Arc-length fraction around a closed ring: n + 1 values, 0 .. 1 (the seam gets 0 and 1)."""
    per = [0.0]
    for k in range(len(ring)):
        a, b = ring[k], ring[(k + 1) % len(ring)]
        per.append(per[-1] + math.dist(a, b))
    return [p / per[-1] for p in per]


def loft(m, rings, mat, v_of_z=None):
    """Quads between consecutive rings (same point count, closed loops), normals outward.
    v_of_z: explicit UVs u = fraction around the ring, v = v_of_z(z) (else box projection)."""
    for a, b in zip(rings, rings[1:]):
        n = len(a)
        ua, ub = ring_u(a), ring_u(b)
        for k in range(n):
            k1 = (k + 1) % n
            uvs = None
            if v_of_z:
                va, vb = v_of_z(a[k][2]), v_of_z(b[k][2])
                uvs = [(ua[k], va), (ua[k + 1], va), (ub[k + 1], vb), (ub[k], vb)]
            m.face((a[k], a[k1], b[k1], b[k]), mat, uvs)


def box(m, lo, hi, mat, skip=()):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
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
            m.face(pts, mat)


# ---------------------------------------------------------------- pier parts
def pier_v(z):
    """Pier texture v: 0 at the ground, 1 at the cap top (the column stretches with the texture in Unity)."""
    return z / CAP_TOP


def column(lod=0, top=CAP_BOTTOM):
    """Chamfered prism from just below the ground to the cap bottom (no caps: hidden)."""
    m = Mesh()
    loft(m, [chamfer_rect(COL['w'], COL['d'], COL['ch'], z) for z in (-0.05, top)], 'M_MetroPier', pier_v)
    return m.finish()


def cap(lod=0):
    """Funnel cap: column section -> widest ring (0.45 below the top) -> top; bearings on LOD0."""
    m = Mesh()
    z0, z2 = CAP_BOTTOM, CAP_TOP
    z1 = z2 - CAP['wide_dz']
    rings = [chamfer_rect(COL['w'], COL['d'], COL['ch'], z0),
             chamfer_rect(*CAP['wide'], CAP['ch_wide'], z1),
             chamfer_rect(*CAP['top'], CAP['ch_top'], z2)]
    loft(m, rings, 'M_MetroPier', pier_v)
    top = rings[2]                                           # top (counter-clockwise from +Z): plain strip at v ~1
    m.face(top, 'M_MetroPier', [(0.5 + p[0] / (4 * CAP['top'][0]), 0.985 + p[1] * 0.002) for p in top])
    if lod == 0:
        bw, bd = BEARING['size']
        for sx in (-1, 1):
            for sy in (-1, 1):
                cx, cy = sx * BEARING['x'], sy * BEARING['y']
                box(m, (cx - bw / 2, cy - bd / 2, z2), (cx + bw / 2, cy + bd / 2, z2 + BEARING_H),
                    'M_MetroConcreteDark', skip=('-Z',))
    return m.finish()


def footing(lod=0):
    """Planter kerb around the column (red / white stripes every FOOT['stripe'] m) + soil."""
    m = Mesh()
    W, D, t, h = FOOT['w'] / 2, FOOT['d'] / 2, FOOT['t'], FOOT['h']
    # outer rectangle walked counter-clockwise; each side = run of stripe segments
    corners = [(W, -D), (W, D), (-W, D), (-W, -D)]
    k = 0
    for i in range(4):
        (ax, ay), (bx, by) = corners[i], corners[(i + 1) % 4]
        L = math.hypot(bx - ax, by - ay)
        dx, dy = (bx - ax) / L, (by - ay) / L
        nx, ny = dy, -dx                                     # outward normal of a CCW loop
        n = max(1, round(L / FOOT['stripe'])) if lod == 0 else 1
        for s in range(n):
            t0, t1 = L * s / n, L * (s + 1) / n
            p0 = (ax + dx * t0, ay + dy * t0)
            p1 = (ax + dx * t1, ay + dy * t1)
            # inner points pulled in by t along the normal and trimmed at the corners
            i0 = (p0[0] - nx * t + (dx * t if s == 0 else 0), p0[1] - ny * t + (dy * t if s == 0 else 0))
            i1 = (p1[0] - nx * t - (dx * t if s == n - 1 else 0), p1[1] - ny * t - (dy * t if s == n - 1 else 0))
            mat = 'M_MetroKerbRed' if (k % 2 == 0 and lod == 0) else 'M_MetroKerbWhite'
            k += 1
            m.face(((*p0, 0.0), (*p1, 0.0), (*p1, h), (*p0, h)), mat)               # outer face
            m.face(((*p0, h), (*p1, h), (*i1, h), (*i0, h)), mat)                   # top
            if lod == 0:
                m.face(((*i0, h), (*i1, h), (*i1, FOOT['soil']), (*i0, FOOT['soil'])), mat)   # inner lip
    # soil: ring between the kerb and the column; side i of the kerb faces column points 2i, 2i+1,
    # the column chamfer 2i+1 -> 2i+2 fills the corner triangle
    zs = FOOT['soil']
    inner = [(W - t, -D + t, zs), (W - t, D - t, zs), (-W + t, D - t, zs), (-W + t, -D + t, zs)]
    colr = chamfer_rect(COL['w'], COL['d'], COL['ch'], zs)
    for i in range(4):
        o0, o1 = inner[i], inner[(i + 1) % 4]
        c0, c1, c2 = colr[2 * i], colr[2 * i + 1], colr[(2 * i + 2) % 8]
        m.face((o0, o1, c1, c0), 'M_MetroSoil')
        m.face((o1, c2, c1), 'M_MetroSoil')
    return m.finish()


PIER_PARTS = {'Column': column, 'Cap': cap, 'Footing': footing}
PIER_LODS = (0, 1)


# ---------------------------------------------------------------- deck sweep (Blender preview)
def path_frames(path, step=2.0):
    """path = list of segments ('line', length) / ('arc', radius, angle_deg, +1 right / -1 left),
    starting at the origin heading +Y. Returns [(s, pos Vector, tangent Vector)] every <= step m."""
    out = []
    pos, heading, s = Vector((0, 0, 0)), math.pi / 2, 0.0
    for seg in path:
        if seg[0] == 'line':
            L = seg[1]
            n = max(1, math.ceil(L / step))
            t = Vector((math.cos(heading), math.sin(heading), 0))
            for k in range(1 if out else 0, n + 1):
                out.append((s + L * k / n, pos + t * (L * k / n), t.copy()))
            pos = pos + t * L
            s += L
        else:
            _, R, ang, side = seg
            A = math.radians(ang)
            L = R * A
            n = max(1, math.ceil(L / step))
            # centre of the arc: to the right (side +1) of the heading
            right = Vector((math.cos(heading - math.pi / 2), math.sin(heading - math.pi / 2), 0))
            c = pos + right * R * side
            a0 = math.atan2(pos.y - c.y, pos.x - c.x)
            for i in range(1, n + 1):
                a = a0 - side * A * i / n
                p = c + Vector((math.cos(a), math.sin(a), 0)) * R
                h = heading - side * A * i / n
                out.append((s + L * i / n, p, Vector((math.cos(h), math.sin(h), 0))))
            heading -= side * A
            pos = out[-1][1].copy()
            s += L
    return out


def profile_uv(prof):
    """f(s, k) -> (u, v) for profile point k at arc length s, by prof['uv'] mode (same rules as Unity)."""
    pts, uvm = prof['pts'], prof['uv']
    n = len(pts)
    per = [0.0]
    for k in range(n):
        a, b = pts[k], pts[(k + 1) % n]
        per.append(per[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    ys = [z for _, z in pts]
    y0, y1 = min(ys), max(ys)
    mode, ul, uo = uvm['mode'], uvm['u_len'], uvm['u_off']
    if mode == 'fraction':
        return lambda s, k: (s / ul, per[k] / per[-1])
    if mode == 'height':
        return lambda s, k: ((s - uo) / ul, (pts[k % n][1] - y0) / max(1e-6, y1 - y0))
    return lambda s, k: (s / 4.0, per[k] / 4.0)


def sweep(m, frames, prof, z_base, cap_ends=True):
    """Extrude a closed (x, z) profile along the frames; UVs by prof['uv'] (profile_uv)."""
    up = Vector((0, 0, 1))
    pts = prof['pts']
    uvf = profile_uv(prof)
    rings = []
    for s, p, t in frames:
        r = t.cross(up).normalized()
        rings.append([p + r * x + up * (z_base + z) for x, z in pts])
    n = len(pts)
    for i in range(len(rings) - 1):
        a, b = rings[i], rings[i + 1]
        s0, s1 = frames[i][0], frames[i + 1][0]
        for k in range(n if prof['closed'] else n - 1):
            k1 = (k + 1) % n
            # (A, D, C, B) = outward for a counter-clockwise profile (see the module docstring);
            # k + 1 (not k1) so the seam edge gets the full perimeter
            m.face((a[k], b[k], b[k1], a[k1]), prof['mat'],
                   [uvf(s0, k), uvf(s1, k), uvf(s1, k + 1), uvf(s0, k + 1)])
    if cap_ends and prof['closed']:
        for ring, t in ((rings[0], -frames[0][2]), (rings[-1], frames[-1][2])):
            f = m.face(ring, prof['mat'], [(x * 0.25, z * 0.25) for x, z in pts])
            f.normal_update()
            if f.normal.dot(t) < 0:
                f.normal_flip()


def posts(m, frames, z_base, step=POST_STEP):
    """H posts on the inside face of both barriers every `step` m (boxes)."""
    up = Vector((0, 0, 1))
    bx = HALF_W - BARRIER['inset'] - BARRIER['t']
    z0, z1 = z_base + PARAPET['h'], z_base + PARAPET['h'] + BARRIER['h']
    s_next = frames[0][0] + step / 2
    for s, p, t in frames:
        while s >= s_next:
            r = t.cross(up).normalized()
            for side in (-1, 1):
                c = p - t * (s - s_next) + r * side * (bx - POST['d'] / 2)
                _oriented_box(m, c, t, r, POST['w'], POST['d'], z0, z1, 'M_MetroSteel')
            s_next += step


def _oriented_box(m, c, t, r, w, d, z0, z1, mat):
    hw, hd = w / 2, d / 2
    q = [c - t * hw - r * hd, c + t * hw - r * hd, c + t * hw + r * hd, c - t * hw + r * hd]   # CCW from +Z?
    lo = [Vector((v.x, v.y, z0)) for v in q]
    hi = [Vector((v.x, v.y, z1)) for v in q]
    # orientation check: make the bottom ring counter-clockwise from +Z
    if (lo[1] - lo[0]).cross(lo[2] - lo[1]).z < 0:
        lo.reverse(); hi.reverse()
    for k in range(4):
        k1 = (k + 1) % 4
        m.face((lo[k], lo[k1], hi[k1], hi[k]), mat)
    m.face(hi, mat)


def deck(lod, frames, z_base=DECK_TOP):
    m = Mesh()
    for name, prof in deck_profiles().items():
        lo, hi = prof['lods']
        if lo <= lod <= hi:
            sweep(m, frames, prof, z_base)
    if lod == 0:
        posts(m, frames, z_base)
    return m.finish(box_uv=False)


def tris(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


# ---------------------------------------------------------------- P1: planters + shrubs
# Planter frames between the piers (Ref/cot.jpg, Ref/metro1.jpg): two striped kerbs + soil swept along
# the line at ground level by Unity MetroBuilder (same width as the pier footing, so they line up);
# shrubs = clumps of leaf cards on the tree leaf atlas (T_Foliage, XaCu cell), LOD1 = a lumpy blob.
PLANTER = dict(w=FOOT['w'], t=FOOT['t'], h=FOOT['h'], soil=FOOT['soil'] - 0.02, stripe=1.0)
SHRUB = dict(r=(0.60, 0.60, 0.42), z=0.40, cards=36, card=(0.40, 0.55), variants=3,
             cell=(0.505, 0.505, 0.995, 0.995),            # T_Foliage 2x2: XaCu = col 1, row 0 (top)
             blob_srgb=(0.2864, 0.4658, 0.1107),            # T_Foliage_blob.json XaCu
             step=0.9, row=0.85, scale=(0.8, 1.25))


def planter_profiles():
    """Ground-level profiles (x across, y up from the road), same dict format as deck_profiles()."""
    W, t, h, soil = PLANTER['w'] / 2, PLANTER['t'], PLANTER['h'], PLANTER['soil']
    stripe = dict(mode='height', u_len=PLANTER['stripe'], u_off=0.0)
    kerb = _box(W - t, 0.0, W, h)
    return {
        'planter_kerb_R': dict(mat='M_MetroKerbStripe', lods=(0, 1), closed=True, pts=kerb, uv=stripe),
        'planter_kerb_L': dict(mat='M_MetroKerbStripe', lods=(0, 1), closed=True, pts=_mirror(kerb), uv=stripe),
        'planter_soil': dict(mat='M_MetroSoil', lods=(0, 1), closed=True, pts=_box(-(W - t), 0.0, W - t, soil),
                             uv=dict(mode='perimeter', u_len=4.0, u_off=0.0)),
        # end wall at a run end that is not a pier footing (junction cut): swept over t metres
        'planter_end': dict(mat='M_MetroKerbStripe', lods=(0, 1), closed=True, pts=_box(-W, 0.0, W, h), uv=stripe),
    }


def shrub(lod, seed):
    """One shrub clump at the origin (ground z 0). Returns (verts, faces, corner uvs, corner colours
    (raw 'Col' bytes 0..1), corner normals). LOD0: leaf cards, Col R random per card / G depth (1 =
    outside) / B height, normals from a point below the centre (soft rounded shading). LOD1: lumpy
    ellipsoid, Col = blob albedo (sRGB), ellipsoid normals."""
    rnd = random.Random(seed)
    rx, ry, rz = [r * rnd.uniform(0.85, 1.15) for r in SHRUB['r']]
    c = Vector((rnd.uniform(-0.05, 0.05), rnd.uniform(-0.05, 0.05), SHRUB['z'] * rz / SHRUB['r'][2]))
    nc = c - Vector((0, 0, 0.35))
    verts, faces, uvs, cols, nrms = [], [], [], [], []
    top = c.z + rz
    if lod == 0:
        u0, v0, u1, v1 = SHRUB['cell']
        for _ in range(SHRUB['cards']):
            d = Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), abs(rnd.gauss(0, 1)) * 0.9 - 0.2))
            d = d.normalized() if d.length > 1e-4 else Vector((0, 0, 1))
            depth = rnd.uniform(0.55, 1.0)
            p = c + Vector((d.x * rx, d.y * ry, d.z * rz)) * depth
            p.z = max(p.z, 0.10)
            n = (d + Vector((rnd.uniform(-0.4, 0.4), rnd.uniform(-0.4, 0.4), rnd.uniform(-0.2, 0.4)))).normalized()
            a = n.cross(Vector((0, 0, 1)))
            a = a.normalized() if a.length > 1e-3 else Vector((1, 0, 0))
            b = n.cross(a)
            roll = rnd.uniform(0, 2 * math.pi)
            ta = a * math.cos(roll) + b * math.sin(roll)
            tb = n.cross(ta)
            w = SHRUB['card'][0] * rnd.uniform(0.8, 1.2)
            h = SHRUB['card'][1] * rnd.uniform(0.8, 1.2)
            corners = [p - ta * w / 2 - tb * h / 2, p + ta * w / 2 - tb * h / 2,
                       p + ta * w / 2 + tb * h / 2, p - ta * w / 2 + tb * h / 2]
            k = len(verts)
            verts += [tuple(q) for q in corners]
            faces.append((k, k + 1, k + 2, k + 3))
            uvs += [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            R = rnd.random()
            for q in corners:
                G = min(1.0, (q - c).length / max(rx, rz))
                B = min(1.0, max(0.0, q.z / top))
                cols.append((R, G, B, 1.0))
                nrms.append(tuple((q - nc).normalized()))
        return verts, faces, uvs, cols, nrms
    # LOD1 blob: flat bottom ring, 4 rings at rising elevations, top pole; radii jittered per vertex
    seg = 8
    all_rings = []
    bottom = []
    for i in range(seg):
        ph = 2 * math.pi * i / seg
        bottom.append(len(verts)); verts.append((c.x + 0.8 * rx * math.cos(ph), c.y + 0.8 * ry * math.sin(ph), 0.05))
    all_rings.append(bottom)
    for el in (-10, 20, 45, 68):
        e = math.radians(el)
        row = []
        for i in range(seg):
            ph = 2 * math.pi * (i + 0.5 * (el > 30)) / seg
            jit = rnd.uniform(0.9, 1.1)
            row.append(len(verts))
            verts.append((c.x + math.cos(e) * rx * math.cos(ph) * jit, c.y + math.cos(e) * ry * math.sin(ph) * jit,
                          max(0.05, c.z + math.sin(e) * rz * jit)))
        all_rings.append(row)
    topi = len(verts); verts.append((c.x, c.y, c.z + rz))
    for ra, rb in zip(all_rings, all_rings[1:]):
        for i in range(seg):
            i1 = (i + 1) % seg
            faces.append((ra[i], ra[i1], rb[i1], rb[i]))
    last = all_rings[-1]
    for i in range(seg):
        faces.append((last[i], last[(i + 1) % seg], topi))
    for f in faces:
        for vi in f:
            q = Vector(verts[vi])
            uvs.append((0.75, 0.75))
            cols.append((*SHRUB['blob_srgb'], 1.0))
            g = Vector(((q.x - c.x) / rx ** 2, (q.y - c.y) / ry ** 2, (q.z - c.z) / rz ** 2))
            nrms.append(tuple(g.normalized() if g.length > 1e-6 else Vector((0, 0, 1))))
    return verts, faces, uvs, cols, nrms
