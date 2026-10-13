"""Step H1: high-rise generator — massing (LOD1 / LOD2) with facade-grid UVs.

Each facade wall is one quad per footprint edge; its second UV layer 'FacadeUV' holds metres from
the quad's centre (u along the edge, v up), so |FacadeUV| at the corners = half the wall size. The
Unity shader rescales it to world metres (towers are stretched / squashed at placement) and fits
whole bays / floors into the wall, so the procedural windows always keep a real size.
UV0 points into a GRID_* trim region that selects the cell style (see hanoi_trim.py).

Run inside Blender:
    exec(open(r"D:/Project III/BuildingGenerate/Blender/scripts/hanoi_tower.py", encoding="utf-8").read())
"""
import os, sys, math, importlib
import bpy
from mathutils import Vector

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_trim, hanoi_kit, hanoi_common
importlib.reload(hanoi_trim); importlib.reload(hanoi_kit); importlib.reload(hanoi_common)
from hanoi_kit import MB, MODULES
from hanoi_common import collection, clear_collection, mesh_object, empty, materials, save_kit

BLEND_PATH = os.path.join(ROOT, "Blender", "HanoiKit_Prototype.blend")
WHITE_TINT = (1.0, 1.0, 1.0, 1.0)


# ---------------------------------------------------------------- footprints
def footprint(w, d, corner=None, slot=None):
    """CCW outline centred on the origin, long side along X, 'front' = -Y.
    corner: None | ('chamfer', c) | ('notch', nx, ny);  slot: None | (width, depth) light-well
    cut into the middle of both long sides. Shape is point-symmetric (front half + 180° copy)."""
    hw, hd = w / 2, d / 2
    if corner is None:
        left = [(-hw, -hd)]
    elif corner[0] == 'chamfer':
        c = corner[1]
        left = [(-hw, -hd + c), (-hw + c, -hd)]
    else:
        nx, ny = corner[1], corner[2]
        left = [(-hw, -hd + ny), (-hw + nx, -hd + ny), (-hw + nx, -hd)]
    half = list(left)
    if slot:
        sw, sd = slot
        half += [(-sw / 2, -hd), (-sw / 2, -hd + sd), (sw / 2, -hd + sd), (sw / 2, -hd)]
    half += [(-x, y) for x, y in reversed(left)]
    return half + [(-x, -y) for x, y in half]


def scaled(fp, sx, sy=None):
    sy = sx if sy is None else sy
    return [(x * sx, y * sy) for x, y in fp]


def edges(fp):
    for i in range(len(fp)):
        a, b = Vector((*fp[i], 0)), Vector((*fp[(i + 1) % len(fp)], 0))
        t = b - a
        L = t.length
        if L < 1e-4:
            continue
        t /= L
        yield a, b, L, t, Vector((t.y, -t.x, 0))       # outward normal of a CCW outline


# ---------------------------------------------------------------- building blocks
def grid_walls(mb, fp, z0, floors, fh, bay, style, color, min_grid=1.5):
    """One quad per edge, FacadeUV = metres from the quad centre. Edges too short for a bay become solid.
    (bay / fh only size the wall here; the shader picks its own per-style cell size.)"""
    z1 = z0 + floors * fh
    for a, b, L, t, n in edges(fp):
        pts = [(a.x, a.y, z0), (b.x, b.y, z0), (b.x, b.y, z1), (a.x, a.y, z1)]
        if L < min_grid:
            start = len(mb.polys)
            mb.quad(pts, 'CONCRETE', n=tuple(n), uv='world')
            mb.set_color(color, start)
            continue
        hl, hh = L / 2, (z1 - z0) / 2
        mb.grid_quad(pts, style, [(-hl, -hh), (hl, -hh), (hl, hh), (-hl, hh)], color)
    return z1


def solid_walls(mb, fp, z0, z1, color, double=False, region='CONCRETE'):
    start = len(mb.polys)
    for a, b, L, t, n in edges(fp):
        mb.quad([(a.x, a.y, z0), (b.x, b.y, z0), (b.x, b.y, z1), (a.x, a.y, z1)], region,
                n=tuple(n), uv='world', double=double)
    mb.set_color(color, start)


def cap(mb, fp, z, color, region='CONCRETE'):
    start = len(mb.polys)
    mb.poly([(x, y, z) for x, y in fp], region, n=(0, 0, 1), phys=(40, 40))
    mb.set_color(color, start)


def block(mb, x0, x1, y0, y1, z0, z1, color, skip=('-Z',)):
    start = len(mb.polys)
    mb.box(x0, x1, y0, y1, z0, z1, 'CONCRETE', skip=set(skip), uv='world')
    mb.set_color(color, start)


def fin(mb, a, t, n, width, depth, z0, z1, color):
    """Vertical fin standing on the facade at point a (edge tangent t, outward normal n)."""
    w2 = t * (width / 2)
    p = [a - w2, a + w2, a + w2 + n * depth, a - w2 + n * depth]   # base outline
    centre = sum(p, Vector()) / 4
    start = len(mb.polys)
    for i in range(1, 4):           # i == 0 lies on the wall: never visible
        q0, q1 = p[i], p[(i + 1) % 4]
        out = (q0 + q1) / 2 - centre
        mb.quad([(q0.x, q0.y, z0), (q1.x, q1.y, z0), (q1.x, q1.y, z1), (q0.x, q0.y, z1)], 'CONCRETE',
                n=tuple(out), uv='world')
    mb.poly([(q.x, q.y, z1) for q in p], 'CONCRETE', n=(0, 0, 1))
    mb.set_color(color, start)


# ---------------------------------------------------------------- crowns
def crown(mb, r, fp, z, lod):
    kind, col = r['crown'], r.get('crown_color', r['color'])
    roof = (0.55, 0.55, 0.53)
    if kind == 'frame':                          # T1: parapet + technical block + pergola frame
        solid_walls(mb, fp, z, z + 1.3, col, double=lod == 1)
        core = scaled(footprint(*r['core']), 1.0)
        solid_walls(mb, core, z, z + 6.5, col)
        cap(mb, core, z + 6.5, roof)
        if lod == 1:
            cx, cy = r['core'][0] / 2 + 2.0, r['core'][1] / 2 + 1.5
            for sx in (-1, 1):
                for sy in (-1, 1):
                    block(mb, sx * cx - 0.5, sx * cx + 0.5, sy * cy - 0.5, sy * cy + 0.5, z, z + 10.5, col)
            for sy in (-1, 1):
                block(mb, -cx - 0.5, cx + 0.5, sy * cy - 0.5, sy * cy + 0.5, z + 9.5, z + 10.5, col, skip=())
            for sx in (-1, 1):
                block(mb, sx * cx - 0.5, sx * cx + 0.5, -cy + 0.5, cy - 0.5, z + 9.5, z + 10.5, col, skip=())
    elif kind == 'band':                         # T2: tall solid band above the roof + plant boxes
        solid_walls(mb, fp, z, z + 4.5, col, double=lod == 1)
        if lod == 1:
            block(mb, -8, 2, -5, 6, z, z + 3.5, roof)
            block(mb, 5, 11, -3, 4, z, z + 2.5, roof)
    elif kind == 'tanks':                        # T3: low parapet, stair/lift head, water tanks
        solid_walls(mb, fp, z, z + 1.0, col, double=lod == 1)
        block(mb, -6, 2, -3, 3, z, z + 3.2, col)
        if lod == 1:
            tank = MODULES['PR_WaterTank'](1)
            from mathutils import Matrix
            for i, x in enumerate((6, 9, 12, -12, -15)):
                mb.extend(tank, Matrix.Translation((x, 2.0 if i % 2 else -2.0, z)))
    elif kind == 'mast':                         # T4: crown band + antenna mast
        solid_walls(mb, fp, z, z + 3.0, col, double=lod == 1)
        block(mb, -4, 4, -4, 4, z, z + 5.0, roof)
        if lod == 1:
            block(mb, -0.4, 0.4, -0.4, 0.4, z + 5.0, z + 28.0, (0.75, 0.75, 0.75))


# ---------------------------------------------------------------- tower
def build_tower(r, lod):
    """lod 1: massing + fins + crown details; lod 2: massing + crown block only."""
    mb = MB()
    fp = r['fp']
    z = 0.0
    p = r.get('podium')
    solid_walls(mb, p.get('fp', fp) if p else fp, -1.5, 0.0, (0.55, 0.55, 0.53))     # foot below the sidewalk-level ground (deep: Unity stretches towers vertically, down to x0.2)
    if p:
        pfp = p.get('fp', fp)
        z = grid_walls(mb, pfp, 0.0, p['floors'], p['fh'], p.get('bay', r['bay']), p['style'], p['color'])
        if pfp is not fp:
            cap(mb, pfp, z, (0.55, 0.55, 0.53))
    body0 = z
    z = grid_walls(mb, fp, z, r['floors'], r['fh'], r['bay'], r['style'], r['color'])
    cap(mb, fp, z, (0.55, 0.55, 0.53))
    if lod == 1 and r.get('fins'):
        every, width, depth = r['fins']
        for a, b, L, t, n in edges(fp):
            if L < 8:
                continue
            nb = max(1, round(L / r['bay']))
            for k in range(0, nb + 1, every):
                fin(mb, a + t * (L * k / nb), t, n, width, depth, body0, z + 4.5, r.get('crown_color', r['color']))
    crown(mb, r, fp, z, lod)
    return mb


# Archetypes read off Ref/ref.jpg (Thượng Đình / Nguyễn Trãi)
TOWERS = {
    # white residential slabs, serrated plan, regular loggia grid, crown frame
    'T1_RoyalCity': dict(
        fp=footprint(44, 20, corner=('notch', 3.6, 2.4), slot=(7.2, 4.0)),
        floors=34, fh=3.2, bay=3.6, style='GRID_RES_LOGGIA', color=(0.93, 0.93, 0.91),
        podium=dict(floors=2, fh=4.5, style='GRID_CURTAIN', color=(0.80, 0.80, 0.78)),
        crown='frame', core=(18, 9)),
    # tallest tower: chamfered block, light vertical stripes between dark glass
    'T2_Stripe': dict(
        fp=footprint(40, 28, corner=('chamfer', 4.0)),
        floors=48, fh=3.4, bay=2.0, style='GRID_STRIPE', color=(0.80, 0.80, 0.78),
        crown='band', crown_color=(0.86, 0.86, 0.84), fins=(2, 0.6, 0.7)),
    # older resettlement housing: long slab, punched windows, blue podium
    'T3_OldHousing': dict(
        fp=footprint(52, 16, slot=(4.0, 2.0)),
        floors=21, fh=3.0, bay=3.3, style='GRID_PUNCHED', color=(0.86, 0.85, 0.81),
        podium=dict(floors=2, fh=4.2, style='GRID_CURTAIN', color=(0.22, 0.42, 0.72)),
        crown='tanks'),
    # distant office tower, blue glass curtain wall
    'T4_Office': dict(
        fp=footprint(30, 30, corner=('chamfer', 3.0)),
        floors=30, fh=3.8, bay=1.5, style='GRID_CURTAIN', color=(0.30, 0.43, 0.58),
        podium=dict(floors=2, fh=5.0, style='GRID_CURTAIN', color=(0.55, 0.57, 0.58)),
        crown='mast', crown_color=(0.70, 0.72, 0.74)),
}

# Layout of Ref/ref.jpg measured from the photo (26 mm phone lens, ~1440 px focal length at
# 2000 px width): each tower = (archetype, bearing deg (+ = right of view axis), distance m,
# rot_z deg, floors override). Camera at the origin, 22 m up, looking +Y.
REF_LAYOUT = [
    ('T3_OldHousing', -33, 165, 25, None),
    ('T1_RoyalCity', -25, 470, 10, 34), ('T1_RoyalCity', -19, 610, 5, 30),
    ('T1_RoyalCity', -11, 390, 0, 36), ('T1_RoyalCity', -4, 500, -5, 32),
    ('T2_Stripe', 8, 420, 0, 50), ('T1_RoyalCity', 14, 520, 0, 34),
    ('T4_Office', 20, 1100, 10, None), ('T1_RoyalCity', 24, 1150, 0, 28),
    ('T1_RoyalCity', 33, 900, 0, 26),
]


REF_ORIGIN = (1000.0, 0.0)      # away from the kit / house rows


def ref_position(bearing, dist):
    a = math.radians(bearing)
    return REF_ORIGIN[0] + dist * math.sin(a), REF_ORIGIN[1] + dist * math.cos(a)


def main():
    kit, glass = materials()
    mats = [kit, glass]
    col = collection('TOWERS'); clear_collection(col)
    lay = collection('REF_LAYOUT'); clear_collection(lay)

    report, meshes = {}, {}
    for i, (name, r) in enumerate(TOWERS.items()):
        root = empty(f"SM_Tower_{name}", col, loc=(-150 + i * 80, -150, 0))
        tris = []
        for lod in (1, 2):
            mb = build_tower(r, lod)
            ob = mesh_object(f"SM_Tower_{name}_LOD{lod}", mb, col, mats, parent=root,
                             loc=(0, 0 if lod == 1 else -60, 0), tint=WHITE_TINT)
            meshes[(name, lod)] = ob.data
            tris.append(mb.tri_count())
        report[name] = tris

    # reference composition (LOD1 meshes, height variants rebuilt on the fly)
    variants = {}
    for k, (name, bearing, dist, rot, floors) in enumerate(REF_LAYOUT):
        x, y = ref_position(bearing, dist)
        key = (name, floors)
        if key not in variants:
            if floors is None:
                variants[key] = meshes[(name, 1)]
            else:
                r = dict(TOWERS[name], floors=floors)
                variants[key] = build_tower(r, 1).to_mesh(f"REF_{name}_{floors}", mats)
        ob = bpy.data.objects.new(f"REF_{k:02d}_{name}", variants[key])
        ob['paint_color'] = WHITE_TINT
        ob.location = (x, y, 0)
        ob.rotation_euler = (0, 0, math.radians(rot))
        lay.objects.link(ob)

    cam = bpy.data.objects.get('RefCam')
    if cam is None:
        cam = bpy.data.objects.new('RefCam', bpy.data.cameras.new('RefCam'))
        bpy.context.scene.collection.objects.link(cam)
    cam.data.lens = 26.0
    cam.data.clip_end = 3000
    cam.location = (REF_ORIGIN[0], REF_ORIGIN[1], 22)
    cam.rotation_euler = (math.radians(87), 0, 0)
    bpy.context.scene.camera = cam
    bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y = 1600, 900

    save_kit(BLEND_PATH)
    return report


if __name__ == "__main__":
    REPORT = main()
    for k, v in REPORT.items():
        print(f"{k:14s} tris LOD1/LOD2: {v}")
