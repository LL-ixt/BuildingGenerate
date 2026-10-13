"""CART — xe gom rác đẩy tay 3 bánh (500 L), low-poly prop. Geometry only (bmesh); build_cart.py
drives it.

Refs: Ref/xe rac.jpg (green hopper bin, folded rim, side brackets, painted frame) and
Ref/xe-gom-rac-day-tay-500-lit-inox.webp (two big spoked wheels under the middle of the bin,
one small swivel wheel under the push handle, handle tubes down to the caster).

Conventions (Blender, metres): cart front (away from the handle) = -Y, handle = +Y, up = +Z,
origin = ground under the big-wheel axle. One material (M_HanoiMoto, the vehicle atlas): every
face points at a palette slot via hanoi_moto.Parts; slot PAINT is tinted per instance (green).

Every builder takes lod (0 / 1 / 2, see LODS). LOD0 is the working model in HanoiCart.blend (the
user cleaned it by hand on 2026-10-12: rim corner tabs and front hook removed -> CORNER_TABS / HOOK).
"""
import math

import bmesh
from mathutils import Matrix, Vector

from hanoi_moto import box, cylinder, lathe

# ---------------------------------------------------------------- dimensions
BIN = dict(
    y=0.12,                 # bin centre (Y): the axle sits a bit in front of the middle
    z0=0.36,                # bottom (outside)
    z1=1.06,                # top of the rim
    top=(0.48, 0.58),       # half-size (X, Y) of the mouth at the top of the wall
    bot=(0.33, 0.36),       # half-size (X, Y) of the bottom
    chamfer=0.04,           # bottom edge bevel
    t=0.02,                 # wall thickness
    lip=0.035,              # rim folded outwards
    skirt=0.03,             # rim drop
)
WHEEL_R = 0.33              # big wheels (66 cm), axle at z = WHEEL_R, y = 0
WHEEL_X = 0.46              # wheel centre plane (tucked under the rim like ref 1)
# swivel axis (x = 0, y), pivot height: right under the cross bar just behind the bin bottom
CASTER = dict(y=BIN['y'] + BIN['bot'][1] + 0.08, r=0.10, top=0.245, trail=0.035)
BRACE_X = 0.22              # half-length of that cross bar (lower frame tubes and handle tubes end on it)
HANDLE = dict(x=0.32, y=1.13, z=0.98)                    # grip bar ends
CORNER_TABS = False         # rim corner tabs (removed by hand in the LOD0 model)
HOOK = False                # hitch hook on the front rim (removed by hand in the LOD0 model)

# Level of detail. LOD0 = close-up (~2.2k tris), LOD1 ~ 15-40 m, LOD2 = far.
# tube / axle = cylinder sides; joint = sphere (u, v) or None; wheel: segs around, tyre = points of
# the tyre section, rim band, hub sides, axle nut, spokes; caster: segs, hub band sides, axle.
LODS = {
    0: dict(tube=8, axle=8, joint=(8, 4), grips=True, ribs=True, fork=True,
            wheel=dict(segs=24, tyre=6, rim=True, hub=8, nut=True, spokes=16),
            caster=dict(segs=16, hub=12, axle=True)),
    1: dict(tube=5, axle=5, joint=None, grips=True, ribs=True, fork=True,
            wheel=dict(segs=12, tyre=4, rim=False, hub=5, nut=False, spokes=8),
            caster=dict(segs=8, hub=8, axle=False)),
    2: dict(tube=3, axle=3, joint=None, grips=False, ribs=False, fork=False,
            wheel=dict(segs=10, tyre=3, rim=False, hub=4, nut=False, spokes=0),
            caster=dict(segs=6, hub=0, axle=False)),
}


def bin_half(z):
    """Half-size (X, Y) of the bin wall (outside) at height z, linear bottom -> top."""
    b = BIN
    k = (z - b['z0']) / (b['z1'] - b['z0'])
    return tuple(lo + (hi - lo) * k for lo, hi in zip(b['bot'], b['top']))


# ---------------------------------------------------------------- helpers
def beam(p0, p1, w, h, up=(0, 0, 1)):
    """Rectangular bar between two points: w across (perpendicular to up), h along up."""
    p0, p1 = Vector(p0), Vector(p1)
    d = (p1 - p0)
    ax = d.normalized()
    side = ax.cross(Vector(up))
    if side.length < 1e-6:
        side = ax.cross(Vector((0, 1, 0)))
    side.normalize()
    nup = side.cross(ax).normalized()
    m = Matrix((side, nup, ax)).transposed().to_4x4()
    m.translation = (p0 + p1) / 2
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(w, h, d.length), verts=bm.verts)
    bm.transform(m)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    return bm


def tube_path(points, r, segs=8):
    """Bent tube: one cylinder per segment, each stretched by r so the joints close."""
    out = []
    pts = [Vector(p) for p in points]
    for a, b in zip(pts, pts[1:]):
        d = (b - a).normalized() * r * 0.8
        out.append(cylinder(a - d if a is not pts[0] else a, b + d if b is not pts[-1] else b, r, segs=segs))
    return out


def ellipsoid_joint(c, r, u=8, v=4):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=r)
    bmesh.ops.translate(bm, vec=Vector(c), verts=bm.verts)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    return bm


def fit_ground(bm, R):
    """Scale a wheel piece radially (around its X axle) so its lowest vertex sits at -R: coarse
    polygons have a flat at the bottom and would float above the ground."""
    low = -min(v.co.z for v in bm.verts)
    if abs(low - R) > 1e-6:
        bmesh.ops.scale(bm, vec=(1, R / low, R / low), verts=bm.verts)
    return bm


def rect_ring(bm, hx, hy, z, y0=0.0):
    return [bm.verts.new((sx * hx, y0 + sy * hy, z)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def bridge(bm, ra, rb):
    for k in range(4):
        j = (k + 1) % 4
        bm.faces.new((ra[k], ra[j], rb[j], rb[k]))


# ---------------------------------------------------------------- bin
def bin_shell(lod=0):
    """Hopper bin, one closed shell: outer bottom -> chamfer -> sloped wall -> rim skirt -> lip ->
    inner wall -> inner bottom. Sharp sheet-metal edges (every edge split). Same at every LOD
    (56 tris)."""
    b = BIN
    c, t, y0 = b['chamfer'], b['t'], b['y']
    bm = bmesh.new()
    zs = b['z1'] - b['skirt']                      # bottom of the rim skirt
    hx0, hy0 = bin_half(b['z0'] + c)
    hxs, hys = bin_half(zs)
    hx1, hy1 = b['top']
    rings = [
        rect_ring(bm, hx0 - c, hy0 - c, b['z0'], y0),
        rect_ring(bm, hx0, hy0, b['z0'] + c, y0),
        rect_ring(bm, hxs, hys, zs, y0),                                   # wall top, under the skirt
        rect_ring(bm, hxs + b['lip'], hys + b['lip'], zs, y0),             # skirt lower edge
        rect_ring(bm, hx1 + b['lip'], hy1 + b['lip'], b['z1'], y0),        # lip outer edge
        rect_ring(bm, hx1 - t, hy1 - t, b['z1'], y0),                      # lip inner edge
    ]
    hxi, hyi = bin_half(b['z0'] + c + t)
    rings.append(rect_ring(bm, hxi - t, hyi - t, b['z0'] + c + t, y0))     # inner wall bottom
    rings.append(rect_ring(bm, hxi - c - t * 0.6, hyi - c - t * 0.6, b['z0'] + t, y0))
    bm.faces.new(rings[0][::-1])
    for ra, rb in zip(rings, rings[1:]):
        bridge(bm, ra, rb)
    bm.faces.new(rings[-1])
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.split_edges(bm, edges=bm.edges[:])    # sheet metal: every fold is a hard edge
    return bm


def bin_details(lod=0):
    """Rim corner tabs, side brackets (rim -> axle), axle, front hook. -> [(bmesh, slot)]"""
    L = LODS[lod]
    b = BIN
    out = []
    hx1, hy1 = b['top']
    lip = b['lip']
    zr = b['z1'] - b['skirt'] / 2
    for sx in (-1, 1) if CORNER_TABS else ():       # folded corner tabs (ref 1)
        for sy in (-1, 1):
            out.append((box((sx * (hx1 + lip + 0.012), b['y'] + sy * (hy1 + lip + 0.012), zr),
                            (0.03, 0.03, b['skirt'] + 0.006)), 'PAINT'))
    for sx in (-1, 1):
        # flat bracket: down the sloped side wall from the rim, then straight down to the axle
        z_knee = 0.70
        hxk, _ = bin_half(z_knee)
        top = Vector((sx * (bin_half(b['z1'] - b['skirt'])[0] + 0.008), 0, b['z1'] - b['skirt']))
        knee = Vector((sx * (hxk + 0.008), 0, z_knee))
        foot = Vector((sx * (hxk + 0.008), 0, WHEEL_R - 0.03))
        out.append((beam(top, knee, 0.05, 0.012, up=(sx, 0, 0)), 'PAINT'))
        out.append((beam(knee + Vector((0, 0, 0.01)), foot, 0.05, 0.012, up=(sx, 0, 0)), 'PAINT'))
        # second, thinner rib on the handle side of the wall (ref 1 vertical channel)
        if not L['ribs']:
            continue
        yr = b['y'] + 0.32
        out.append((beam((sx * (bin_half(b['z1'] - b['skirt'])[0] + 0.006), yr, b['z1'] - b['skirt']),
                         (sx * (bin_half(b['z0'] + b['chamfer'])[0] + 0.006), yr, b['z0'] + b['chamfer']),
                         0.03, 0.008, up=(sx, 0, 0)), 'PAINT'))
    # axle across under the bin
    out.append((cylinder((-WHEEL_X + 0.03, 0, WHEEL_R), (WHEEL_X - 0.03, 0, WHEEL_R), 0.016,
                         segs=L['axle']), 'PAINT'))
    # hook on the front rim (to hitch carts in a train)
    yf = b['y'] - hy1 - lip
    for p0, p1 in (((0, yf, b['z1'] - 0.01), (0, yf - 0.06, b['z1'] - 0.01)),
                   ((0, yf - 0.06, b['z1'] - 0.01), (0, yf - 0.06, b['z1'] + 0.04))) if HOOK else ():
        out.append((cylinder(p0, p1, 0.008, segs=6), 'METAL'))
    return out


# ---------------------------------------------------------------- frame
def frame(lod=0):
    """Lower frame axle -> cross bar, caster plate under the cross bar, handle tubes from the grip
    corners down to the cross bar ends, grip bar. -> [(bmesh, slot)]"""
    L = LODS[lod]
    n = L['tube']
    out = []
    cy, top = CASTER['y'], CASTER['top']
    hx, hy, hz = HANDLE['x'], HANDLE['y'], HANDLE['z']
    plate_z = top + 0.006
    zb = plate_z + 0.006 + 0.016                   # cross bar resting on the caster plate
    out.append((box((0, cy, plate_z), (0.16, 0.11, 0.012)), 'PAINT'))
    out.append((cylinder((-BRACE_X, cy, zb), (BRACE_X, cy, zb), 0.016, segs=n), 'PAINT'))
    zw = BIN['z1'] - 0.08                          # where the handle tubes leave the back wall
    wall_y = BIN['y'] + bin_half(zw)[1]
    for sx in (-1, 1):
        end = (sx * BRACE_X, cy, zb)
        # lower frame: from the axle bracket, under the bin bottom, to the cross bar
        out += [(bm, 'PAINT') for bm in tube_path([(sx * 0.36, 0.0, WHEEL_R), end], 0.014, n)]
        # handle: off the back wall, back to the grip corner, then down to the cross bar end
        out += [(bm, 'PAINT') for bm in tube_path(
            [(sx * hx, wall_y - 0.01, zw), (sx * hx, hy, hz)], 0.016, n)]
        out += [(bm, 'PAINT') for bm in tube_path([(sx * hx, hy, hz), end], 0.016, n)]
        if L['joint']:
            out.append((ellipsoid_joint((sx * hx, hy, hz), 0.022, *L['joint']), 'PAINT'))
            out.append((ellipsoid_joint(end, 0.02, *L['joint']), 'PAINT'))
    # grip bar across the handle ends, with black rubber grips at both ends
    out.append((cylinder((-hx, hy, hz), (hx, hy, hz), 0.017, segs=n), 'PAINT'))
    for sx in (-1, 1) if L['grips'] else ():
        out.append((cylinder((sx * (hx - 0.03), hy, hz), (sx * (hx - 0.16), hy, hz), 0.021, segs=n), 'TIRE'))
    return out


def body(lod=0):
    return [(bin_shell(lod), 'PAINT')] + bin_details(lod) + frame(lod)


# ---------------------------------------------------------------- wheels
def spoke_wheel(lod=0, R=WHEEL_R):
    """Big wheel around its own axle (origin, axis X): round-section tyre, thin steel rim, hub,
    spokes laced from the two hub flanges to the rim centre line. -> [(bmesh, slot)]"""
    W = LODS[lod]['wheel']
    segs = W['segs']
    out = []
    sr = 0.022                                      # tyre section radius
    rc = R - sr
    nt = W['tyre']
    a0 = 0.0 if nt == 6 else math.pi / nt           # low LODs: flat side inwards / outwards
    tyre = [(rc + sr * math.cos(a), sr * 0.9 * math.sin(a))
            for a in (a0 + 2 * math.pi * k / nt for k in range(nt))]
    out.append((fit_ground(lathe(tyre, segs, closed=True), R), 'TIRE'))
    r_in = rc - sr * 0.9                            # rim: a thin band inside the tyre
    if W['rim']:
        rim = [(r_in - 0.014, -0.011), (r_in + 0.002, -0.013), (r_in + 0.002, 0.013), (r_in - 0.014, 0.011)]
        out.append((lathe(rim, segs, closed=True), 'RIM'))
    out.append((cylinder((-0.045, 0, 0), (0.045, 0, 0), 0.028, segs=W['hub']), 'METAL'))   # hub
    if W['nut']:
        out.append((cylinder((-0.06, 0, 0), (0.06, 0, 0), 0.010, segs=6), 'METAL'))       # axle nut ends
    r_s = r_in - 0.012 if W['rim'] else r_in + 0.004
    spokes = W['spokes']
    for k in range(spokes):
        a = 2 * math.pi * k / spokes
        side = 1 if k % 2 else -1
        a_hub = a + side * 0.35                     # tangential lacing
        p0 = Vector((side * 0.035, 0.026 * math.cos(a_hub), 0.026 * math.sin(a_hub)))
        p1 = Vector((side * 0.004, r_s * math.cos(a), r_s * math.sin(a)))
        out.append((cylinder(p0, p1, 0.0035, segs=3, caps=False), 'RIM'))
    return out


def caster_wheel(lod=0, r=CASTER['r']):
    """Small solid wheel around its axle (origin, axis X). -> [(bmesh, slot)]"""
    C = LODS[lod]['caster']
    if C['hub']:
        prof = [(0.055, -0.020), (r - 0.012, -0.024), (r, -0.012), (r, 0.012), (r - 0.012, 0.024),
                (0.055, 0.020)]
        out = [(fit_ground(lathe(prof, C['segs']), r), 'TIRE'),
               (lathe([(0.012, -0.022), (0.056, -0.020), (0.056, 0.020), (0.012, 0.022)], C['hub']), 'RIM')]
    else:                                           # far: one closed tyre, no hub
        out = [(fit_ground(lathe([(0.03, -0.022), (r, -0.02), (r, 0.02), (0.03, 0.022)], C['segs'],
                                 closed=True), r), 'TIRE')]
    if C['axle']:
        out.append((cylinder((-0.032, 0, 0), (0.032, 0, 0), 0.008, segs=6), 'METAL'))
    return out


def caster_fork(lod=0):
    """Swivel fork, origin = pivot (top of the swivel bearing). The wheel axle sits at
    (0, trail, r - top) below it. -> [(bmesh, slot)]"""
    r, top, trail = CASTER['r'], CASTER['top'], CASTER['trail']
    az = r - top
    if not LODS[lod]['fork']:                       # far: one block from the plate to the axle
        return [(beam((0, trail * 0.3, 0), (0, trail, az), 0.07, 0.02), 'METAL')]
    out = [(cylinder((0, 0, -0.025), (0, 0, 0.0), 0.03, segs=8), 'METAL'),         # bearing
           (box((0, trail * 0.5, -0.03), (0.075, 0.05 + trail, 0.008)), 'METAL')]   # fork crown
    for sx in (-1, 1):
        out.append((beam((sx * 0.033, trail * 0.4, -0.03), (sx * 0.033, trail, az), 0.03, 0.006,
                         up=(sx, 0, 0)), 'METAL'))
    return out
