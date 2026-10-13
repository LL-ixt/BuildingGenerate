"""T1: Hanoi street trees - branch skeleton + canopy blocking (the "sculpt" step done by script).

Background (keeps hand edits, see below):
    blender -b --python Blender/scripts/hanoi_tree.py   (no --factory-startup: needs the Sapling extension)
Writes Blender/HanoiTrees.blend (one collection per tree) and Blender/previews/trees_t1*.png.

Trees: TR_<Species>_<seed>, origin = centre of the trunk base, Z up, metres.
  Sau     (sấu)      straight trunk, dense round crown, branches rising
  XaCu    (xà cừ)    thick trunk, 3-4 heavy limbs spreading into an umbrella crown
  Bang    (bàng)     low clear trunk, 3-4 tiers of horizontal branches, flat layered discs
  HoaSua  (hoa sữa)  leader with whorls of branches, upright egg-shaped crown

Branching = Sapling Tree Gen (Weber-Penn) with per-species parameters (SAPLING); tubes rebuilt here.
Canopy = ellipsoid "lobes" on clusters of the branch tips -> voxel remesh (merge) -> squash the underside ->
noise displacement along the normals -> smooth -> decimate. Each lobe also says which tier it
belongs to (bàng discs stay separate).

Hand edits: sculpt TR_x_Canopy in HanoiTrees.blend, set its custom property hand_edited = True,
save, re-run: that canopy is kept as is, everything else is rebuilt from the seed.
The skeleton + lobes are stored as JSON on the root empty (custom property 'tree') for T3.
"""
import os, sys, math, json, random, importlib, zlib
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix, noise

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_common
importlib.reload(hanoi_common)
from hanoi_common import collection, empty, save_kit

TREE_BLEND = os.path.join(ROOT, "Blender", "HanoiTrees.blend")
SPECIES_ORDER = ['Sau', 'XaCu', 'Bang', 'HoaSua']
SEEDS = (0, 1, 2)
VOXEL = 0.22               # m: canopy remesh resolution
CANOPY_TRIS = 6000         # canopy after decimation (leaf scatter source / normal shell / LOD2 base)
SPACING = 15.0             # m between trees in the .blend


# ---------------------------------------------------------------- skeleton data
class Tree:
    def __init__(self, species, seed):
        self.species, self.seed = species, seed
        self.rng = random.Random(zlib.crc32(f"{species}/{seed}".encode()))   # hash() is salted per process
        self.branches = []     # dict(pts=[Vector], rs=[radius], level)  (level 0 = trunk)
        self.lobes = []        # dict(c=Vector, r=Vector, tier=int)
        self.flat = 0.65       # underside squash (1 = none)
        self.height = 0.0

    def u(self, a, b):
        return self.rng.uniform(a, b)

    def to_json(self):
        return json.dumps(dict(
            species=self.species, seed=self.seed, height=round(self.height, 2), flat=self.flat,
            branches=[dict(pts=[[round(v, 3) for v in p] for p in b['pts']], rs=[round(r, 4) for r in b['rs']],
                           level=b['level']) for b in self.branches],
            lobes=[dict(c=[round(v, 3) for v in l['c']], r=[round(v, 3) for v in l['r']], tier=l['tier'])
                   for l in self.lobes]))


# ---------------------------------------------------------------- Sapling Tree Gen (branching)
# The skeleton comes from the Sapling Tree Gen extension (Weber-Penn model): run Blender WITHOUT
# --factory-startup so the user's extensions load. Only its curve (points + radii) is used; the
# tube mesh and the canopy are built here. Parameters start from the add-on's quaking_aspen preset.
SAPLING_PRESET = os.path.join(os.environ.get('APPDATA', ''), "Blender Foundation", "Blender", "5.2", "extensions",
                              "blender_org", "sapling_tree_gen", "presets", "quaking_aspen.py")
SAPLING = {
    # dense round crown, rising branches
    'Sau': dict(scale=11.0, scaleV=0.5, shape='1', baseSize=0.32, ratio=0.034, ratioPower=1.3,
                branches=(0, 22, 9, 0), length=(1.0, 0.46, 0.42, 0.3), lengthV=(0, 0.06, 0.1, 0),
                downAngle=(90, 62, 45, 45), downAngleV=(0, -20, 15, 10), rotateV=(15, 15, 30, 0),
                curve=(0, -15, -10, 0), curveV=(15, 40, 60, 0), attractUp=(0, 0.5, 0.6, 0.5), rootFlare=1.25),
    # thick trunk forking into heavy limbs, wide umbrella
    'XaCu': dict(scale=12.5, scaleV=0.5, shape='2', baseSize=0.40, ratio=0.032, ratioPower=1.25,
                 baseSplits=2, splitHeight=0.38, splitAngle=(22, 0, 0, 0), splitAngleV=(6, 0, 0, 0),
                 branches=(0, 16, 9, 0), length=(1.0, 0.55, 0.4, 0.3), lengthV=(0, 0.08, 0.1, 0),
                 downAngle=(90, 52, 40, 45), downAngleV=(0, -20, 10, 10), rotateV=(15, 20, 30, 0),
                 curve=(0, -8, -10, 0), curveV=(10, 30, 50, 0), attractUp=(0, 0.25, 0.4, 0.5), rootFlare=1.35),
    # whorls of near-horizontal branches (tiers)
    'Bang': dict(scale=9.5, scaleV=0.4, shape='4', baseSize=0.25, ratio=0.028, ratioPower=1.2, nrings=4,
                 branches=(0, 24, 8, 0), length=(1.0, 0.6, 0.36, 0.3), lengthV=(0, 0.05, 0.08, 0),
                 downAngle=(90, 86, 40, 45), downAngleV=(0, 4, 10, 10), rotateV=(15, 10, 30, 0),
                 curve=(0, 6, -10, 0), curveV=(0, 12, 30, 0), attractUp=(0, 0.0, 0.3, 0.5), rootFlare=1.2),
    # leader with whorls rising into an upright egg
    'HoaSua': dict(scale=11.5, scaleV=0.5, shape='7', baseSize=0.30, ratio=0.032, ratioPower=1.2, nrings=3,
                   branches=(0, 18, 8, 0), length=(1.0, 0.42, 0.4, 0.3), lengthV=(0, 0.05, 0.08, 0),
                   downAngle=(90, 50, 40, 45), downAngleV=(0, -10, 10, 10), rotateV=(15, 10, 30, 0),
                   curve=(0, -10, -10, 0), curveV=(10, 30, 40, 0), attractUp=(0, 0.6, 0.6, 0.5), rootFlare=1.2),
}
# canopy lobes from the branch tips: clusters, lobe radius bounds, vertical squash, underside squash, core lobe
CROWN = {
    'Sau':    dict(k=12, rmin=1.6, rmax=2.6, squash=0.95, flat=0.55, core=0.25, zweight=1.0),
    'XaCu':   dict(k=14, rmin=1.9, rmax=3.0, squash=0.70, flat=0.55, core=0.45, zweight=1.0),
    'Bang':   dict(k=20, rmin=1.2, rmax=1.9, squash=0.40, flat=0.6, core=0.0, zweight=4.0),
    'HoaSua': dict(k=11, rmin=1.5, rmax=2.3, squash=1.0, flat=0.6, core=0.3, zweight=1.0),
}


def sapling_params(species, seed):
    import ast
    txt = open(SAPLING_PRESET, encoding='utf-8').read()
    p = ast.literal_eval(txt[txt.index('{'):])
    p.update(levels=3, showLeaves=False, do_update=True, bevel=True, prune=False, curveRes=(8, 5, 3, 1),
             handleType='0', baseSplits=0, nrings=0, splitAngle=(0, 0, 0, 0), splitAngleV=(0, 0, 0, 0),
             segSplits=(0, 0, 0, 0), taper=(1, 1, 1, 1), resU=4, bevelRes=1, useArm=False, armAnim=False,
             seed=zlib.crc32(f"sapling/{species}/{seed}".encode()) % 10000)
    p.update(SAPLING[species])
    return p


def bezier_samples(sp, per_seg=3):
    """Points + radii along a Sapling bezier spline (per_seg samples per segment)."""
    bp = sp.bezier_points
    pts, rs = [bp[0].co.copy()], [bp[0].radius]
    for a, b in zip(bp, bp[1:]):
        for k in range(1, per_seg + 1):
            t = k / per_seg
            p = (a.co * (1 - t) ** 3 + a.handle_right * 3 * (1 - t) ** 2 * t +
                 b.handle_left * 3 * (1 - t) * t ** 2 + b.co * t ** 3)
            pts.append(p); rs.append(a.radius * (1 - t) + b.radius * t)
    return pts, rs


def kmeans(X, k, rng, iters=25):
    k = max(1, min(k, len(X)))
    C = X[rng.sample(range(len(X)), k)].copy()
    for _ in range(iters):
        lab = ((X[:, None] - C[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            if (lab == j).any():
                C[j] = X[lab == j].mean(0)
    lab = ((X[:, None] - C[None]) ** 2).sum(-1).argmin(1)
    return C, lab


def make_tree(species, seed, col):
    """Run Sapling, read its curve into t.branches, derive the canopy lobes from the branch tips.
    Returns (Tree, curve object) - the curve stays in the .blend (hidden) for reference."""
    t = Tree(species, seed)
    before = set(bpy.data.objects)
    bpy.ops.curve.tree_add(**sapling_params(species, seed))
    cu = next(o for o in bpy.data.objects if o not in before and o.type == 'CURVE')
    for c in list(cu.users_collection):
        c.objects.unlink(cu)
    col.objects.link(cu)
    rmax = max(sp.bezier_points[0].radius for sp in cu.data.splines)
    tips = []
    for sp in cu.data.splines:
        r0 = sp.bezier_points[0].radius
        level = 0 if r0 > 0.55 * rmax else 1 if r0 > 0.12 * rmax else 2
        pts, rs = bezier_samples(sp, 3 if level == 0 else 2)
        t.branches.append(dict(pts=pts, rs=rs, level=level))
        tips.append(list(pts[-1]))                          # leader tops too: no bare leader above the crown
    cfg = CROWN[species]
    t.flat = cfg['flat']
    X = np.array(tips, np.float32)
    W = np.array([1.0, 1.0, cfg['zweight']], np.float32)
    C, lab = kmeans(X * W, cfg['k'], t.rng)
    C /= W
    for j, c in enumerate(C):
        pts = X[lab == j]
        spread = float(np.sqrt(((pts[:, :2] - c[:2]) ** 2).sum(1).mean())) if len(pts) else 0.0
        rad = min(cfg['rmax'], max(cfg['rmin'], spread * 1.2 + 0.9))
        lobe(t, Vector(c.tolist()) + Vector((0, 0, 0.25)), rad, cfg['squash'])
    if cfg['core'] > 0:                                     # fill the inside of round crowns
        cx = Vector(X.mean(0).tolist())
        half = float(np.abs(X[:, :2] - X[:, :2].mean(0)).max())
        lobe(t, cx, max(1.5, half * cfg['core']), cfg['squash'])
    t.height = max(l['c'].z + l['r'].z for l in t.lobes)
    return t, cu


def lobe(t, c, rad, squash, tier=0):
    t.lobes.append(dict(c=c.copy(), r=Vector((rad * t.u(0.9, 1.1), rad * t.u(0.9, 1.1), rad * squash)), tier=tier))


# ---------------------------------------------------------------- meshes
def tube_mesh(name, branches, sides=(8, 5, 4), max_level=2, v_scale=2.0, flare=1.0, min_r=0.018):
    """Branches as swept tubes (rotation-minimising frames), radius per point, sides per level.
    UV: u around, v = length / v_scale (bark tiles every 2 m)."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    for b in branches:
        if b['level'] > max_level or b['rs'][0] < min_r:
            continue
        pts, rs = b['pts'], b['rs']
        n = len(pts)
        ns = sides[min(b['level'], len(sides) - 1)]
        T = [(pts[min(i + 1, n - 1)] - pts[max(i - 1, 0)]).normalized() for i in range(n)]
        ref = Vector((1, 0, 0)) if abs(T[0].z) > 0.9 else Vector((0, 0, 1))
        N = [T[0].cross(ref).normalized()]
        for i in range(1, n):                                       # parallel transport
            v = N[-1] - T[i] * N[-1].dot(T[i])
            N.append(v.normalized() if v.length > 1e-6 else N[-1])
        acc = [0.0]
        for i in range(1, n):
            acc.append(acc[-1] + (pts[i] - pts[i - 1]).length)
        rings = []
        for i in range(n):
            r = max(rs[i], min_r * 0.5)
            if b['level'] == 0 and acc[i] < 0.8 and flare > 1:      # extra root flare
                r *= 1 + (flare - 1) * (1 - acc[i] / 0.8) ** 2
            B = T[i].cross(N[i])
            rings.append([bm.verts.new(pts[i] + (N[i] * math.cos(a) + B * math.sin(a)) * r)
                          for a in (2 * math.pi * s / ns for s in range(ns))])
        for i in range(n - 1):
            for s in range(ns):
                s2 = (s + 1) % ns
                f = bm.faces.new((rings[i][s], rings[i][s2], rings[i + 1][s2], rings[i + 1][s]))
                f.smooth = True
                for loop, (uu, vv) in zip(f.loops, ((s, i), (s + 1, i), (s + 1, i + 1), (s, i + 1))):
                    loop[uv].uv = (uu / ns, acc[vv] / v_scale)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def bake(ob):
    """Mesh with every modifier of `ob` applied (no operators: works in background)."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    ob.modifiers.clear()
    old = ob.data
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return me


def canopy_mesh(t, name, col):
    """Lobes -> voxel remesh -> squash underside -> noise displacement -> smooth -> decimate."""
    bm = bmesh.new()
    for l in t.lobes:
        res = bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
        S = Matrix.Diagonal((l['r'].x, l['r'].y, l['r'].z, 1.0))
        bmesh.ops.transform(bm, matrix=Matrix.Translation(l['c']) @ S, verts=res['verts'])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    m = ob.modifiers.new("Remesh", 'REMESH')
    m.mode = 'VOXEL'; m.voxel_size = VOXEL; m.adaptivity = 0.0
    bake(ob)

    # squash the underside towards each lobe's centre + lumpy noise along the normals
    me = ob.data
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32); me.vertices.foreach_get('co', co); co = co.reshape(n, 3)
    nr = np.empty(n * 3, np.float32); me.vertices.foreach_get('normal', nr); nr = nr.reshape(n, 3)
    C = np.array([list(l['c']) for l in t.lobes], np.float32)
    Rr = np.array([list(l['r']) for l in t.lobes], np.float32)
    d = (((co[:, None, :] - C[None]) / Rr[None]) ** 2).sum(-1)          # ellipsoidal distance to every lobe
    near = d.argmin(1)
    cz = C[near, 2]
    low = co[:, 2] < cz
    co[low, 2] = cz[low] - (cz[low] - co[low, 2]) * t.flat
    off = Vector((t.seed * 17.3 + 3.1, t.seed * 5.7 + 11.9, len(t.species) * 2.3))
    amp = np.array([0.42 * noise.noise(Vector(p) / 1.5 + off) + 0.22 * noise.noise(Vector(p) / 0.7 + off * 1.7)
                    for p in co], np.float32)
    co += nr * amp[:, None]
    me.vertices.foreach_set('co', co.ravel())
    me.update()

    m = ob.modifiers.new("Smooth", 'SMOOTH'); m.factor = 0.6; m.iterations = 6
    m = ob.modifiers.new("Decimate", 'DECIMATE')
    m.ratio = min(1.0, CANOPY_TRIS / max(1, len(me.polygons) * 2))
    bake(ob)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def preview_material(name, rgb):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = (*rgb, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.85
    m.diffuse_color = (*rgb, 1.0)
    return m


# ---------------------------------------------------------------- build
def build_all():
    if os.path.exists(TREE_BLEND):
        bpy.ops.wm.open_mainfile(filepath=TREE_BLEND)
    for nm in ('Cube', 'Light', 'Camera'):                    # factory-startup leftovers
        ob = bpy.data.objects.get(nm)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)
    bark = preview_material('M_Bark', (0.16, 0.12, 0.09))
    leaf = preview_material('M_Foliage', (0.10, 0.26, 0.07))
    report = []
    for si, sp in enumerate(SPECIES_ORDER):
        for seed in SEEDS:
            name = f"TR_{sp}_{seed}"
            col = collection(name)
            kept = None
            old_canopy = bpy.data.objects.get(f"{name}_Canopy")
            if old_canopy is not None and old_canopy.get('hand_edited'):
                kept = old_canopy.data
                kept.use_fake_user = True
            for ob in list(col.objects):
                data = ob.data
                bpy.data.objects.remove(ob, do_unlink=True)
                if data is not None and data is not kept and data.users == 0 and isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
            root = empty(name, col, loc=(seed * SPACING, si * SPACING, 0))
            t, cu = make_tree(sp, seed, col)
            cu.name = f"{name}_Curve"
            cu.parent = root
            cu.hide_render = True
            cu.hide_viewport = True
            root['tree'] = t.to_json()
            br = bpy.data.objects.new(f"{name}_Branches", tube_mesh(f"{name}_Branches", t.branches))
            br.data.materials.append(bark)
            col.objects.link(br); br.parent = root
            if kept is not None:
                cn = bpy.data.objects.new(f"{name}_Canopy", kept)
                cn['hand_edited'] = True
                col.objects.link(cn)
                kept.use_fake_user = False
            else:
                cn = canopy_mesh(t, f"{name}_Canopy", col)
                cn['hand_edited'] = False
            if not cn.data.materials:
                cn.data.materials.append(leaf)
            cn.parent = root
            tris = (sum(len(p.vertices) - 2 for p in br.data.polygons), sum(len(p.vertices) - 2 for p in cn.data.polygons))
            dims = cn.dimensions
            report.append((name, t.height, round(max(dims.x, dims.y), 1), round(dims.z, 1), tris, kept is not None))
            print(f"[tree] {name:12s} h {t.height:5.1f} m  crown {max(dims.x, dims.y):4.1f} x {dims.z:4.1f} m  "
                  f"branches {tris[0]} tris  canopy {tris[1]} tris{'  (hand edited, kept)' if kept else ''}")
    save_kit(TREE_BLEND)
    return report


# ---------------------------------------------------------------- preview
def render_previews():
    """Copies of the trees in a row next to a 4-floor tube house, rendered with the HDRI of preview_modules."""
    import preview_modules, hanoi_house, tube_generator
    for m in (preview_modules, hanoi_house, tube_generator):
        importlib.reload(m)
    from hanoi_common import materials, mesh_object
    pcol = collection('PREVIEW')
    kit, glass = materials()
    plan = [h for h in tube_generator.library_plan() if h[3]['floors'] == 4 and h[3]['exposed'] == '']
    vid, _, recipe, meta = plan[0]

    def place(tree_names, png, spacing, yaw=0, pitch=10):
        for ob in list(pcol.objects) + [o for o in bpy.data.objects if o.name.split('.')[0] in ('Ground', 'Sun', 'Cam')]:
            bpy.data.objects.remove(ob, do_unlink=True)
        x = -spacing * (len(tree_names) - 1) / 2 - spacing * 0.9
        mesh_object("RefHouse", hanoi_house.assemble(recipe, 0, meta['depth']), pcol, [kit, glass], loc=(x, 4.0, 0))
        for i, nm in enumerate(tree_names):
            xi = -spacing * (len(tree_names) - 1) / 2 + i * spacing
            for part in ('Branches', 'Canopy'):
                src = bpy.data.objects[f"{nm}_{part}"]
                ob = bpy.data.objects.new(f"P_{nm}_{part}", src.data)
                pcol.objects.link(ob)
                ob.location = (xi, 0, 0)
            preview_modules.label(nm.replace('TR_', ''), (xi, -7.0, 0.05), pcol, 0.9)
        width = spacing * (len(tree_names) + 1.3)
        preview_modules.render_scene(png, (-spacing * 0.45, 0, 7.5), width, 20, yaw=yaw, pitch=pitch)

    # tree collections must not render in the preview (they are laid out on a grid)
    for sp in SPECIES_ORDER:
        for seed in SEEDS:
            bpy.data.collections[f"TR_{sp}_{seed}"].hide_render = True
    preview_modules.ENVS[:] = ['sun']
    place([f"TR_{sp}_0" for sp in SPECIES_ORDER], 'trees_t1.png', 14.0)
    place([f"TR_{sp}_{s}" for sp in SPECIES_ORDER for s in SEEDS], 'trees_t1_all.png', 13.0)


if __name__ == "__main__":
    REPORT = build_all()
    render_previews()
    print(f"[tree] {len(REPORT)} trees -> {TREE_BLEND}")
