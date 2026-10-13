"""Kit sheet: lay out modules (each on its body) in a row, LOD0 bottom / LOD1 top, label them,
render a PNG and save a preview .blend.

Background:
    blender -b --factory-startup --python preview_modules.py -- [Module ...]
No module list -> the front modules of the tube-house recipe; '--houses' -> sample houses (B2).
"""
import os, sys, math, importlib
import bpy
from mathutils import Matrix, Vector

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_trim, hanoi_kit, hanoi_common
importlib.reload(hanoi_trim); importlib.reload(hanoi_kit); importlib.reload(hanoi_common)
from hanoi_kit import MB, MODULES, GH, FH
from hanoi_common import collection, clear_collection, mesh_object, empty, materials, save_kit

OUT_DIR = os.path.join(ROOT, "Blender", "previews")
BLEND_PATH = os.path.join(ROOT, "Blender", "HanoiModules_Preview.blend")
DEFAULT = ['GF_WoodDoor', 'GF_FoldGate', 'GF_Open', 'GF_Shop', 'GF_Roller',
           'UF_Window', 'UF_BalconySolid', 'UF_Balcony', 'UF_Shutter', 'UF_Cage']
SPACING = 5.5
ROW_GAP = 2.0


def with_body(name, lod):
    mb = MB()
    body = 'Body_GF' if name.startswith('GF_') else 'Body_UF' if name.startswith('UF_') else None
    if body:
        mb.extend(MODULES[body](lod), Matrix.Identity(4))
    mb.extend(MODULES[name](lod), Matrix.Identity(4))
    return mb


def label(text, loc, col, size=0.35):
    cu = bpy.data.curves.new(f"LBL_{text}", 'FONT')
    cu.body = text; cu.size = size; cu.align_x = 'CENTER'
    ob = bpy.data.objects.new(f"LBL_{text}", cu)
    ob.location = loc; ob.rotation_euler = (math.radians(90), 0, 0)
    col.objects.link(ob)
    m = bpy.data.materials.get('M_Label')
    if m is None:
        m = bpy.data.materials.new('M_Label'); m.use_nodes = True
        next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Base Color'].default_value = (0.01, 0.01, 0.01, 1)
        m.diffuse_color = (0.02, 0.02, 0.02, 1)
    cu.materials.append(m)
    return ob


def render_scene(png, center, width, height, yaw=-8, pitch=12):
    """Ground, sun, sky and an orthographic camera aimed at center; renders OUT_DIR/png."""
    bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 20, -0.01))
    g = bpy.context.active_object; g.name = 'Ground'
    gm = bpy.data.materials.new('M_Ground'); gm.use_nodes = True
    next(n for n in gm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Base Color'].default_value = (0.35, 0.35, 0.34, 1)
    g.data.materials.append(gm)
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    bpy.context.scene.collection.objects.link(sun)

    yaw, pitch = math.radians(yaw), math.radians(pitch)
    cam = bpy.data.objects.new('Cam', bpy.data.cameras.new('Cam'))
    bpy.context.scene.collection.objects.link(cam)
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = width
    cam.data.clip_end = 1000
    fwd = Vector((math.sin(-yaw) * math.cos(pitch), math.cos(-yaw) * math.cos(pitch), -math.sin(pitch)))
    cam.location = Vector(center) - fwd * 150
    cam.rotation_euler = (math.pi / 2 - pitch, 0, yaw)
    sc = bpy.context.scene
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = 2400, int(2400 * height / width)
    try:
        sc.render.engine = 'BLENDER_EEVEE'
    except TypeError as e:
        print("[preview] engine:", e)
    sc.view_settings.view_transform = 'Standard'
    os.makedirs(OUT_DIR, exist_ok=True)
    stem, ext = os.path.splitext(png)
    for env in ENVS:
        apply_env(env, sun)
        sc.render.filepath = os.path.join(OUT_DIR, png if env == 'flat' else f"{stem}_{env}{ext}")
        bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------- lighting
# 'flat'     old flat sky + one sun (fast sanity check)
# 'sun'      real HDRI (clear sky, midday) + a sun lamp placed at the HDRI's brightest spot
# 'overcast' real HDRI (overcast sky), no sun
ENVS = ['sun', 'overcast']
HDRI = {'sun': 'sun_2k.hdr', 'overcast': 'overcast_2k.hdr'}
HDRI_DIR = os.path.join(ROOT, "Textures", "src", "hdri")
SUN_STRENGTH = 2.5          # W/m2 lamp on top of the HDRI; the HDRI's own sun disc is small and clipped


def brightest_dir(img):
    """World-space direction (Blender equirect convention) of the brightest pixel of an HDRI."""
    import numpy as np
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    lum = px.reshape(h, w, 4)[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    # smooth over a few pixels so a single hot pixel cannot win
    k = 9
    pad = np.pad(lum, ((k // 2, k // 2), (k // 2, k // 2)), mode='edge')
    acc = sum(pad[i:i + h, j:j + w] for i in range(k) for j in range(k))
    y, x = np.unravel_index(int(np.argmax(acc)), acc.shape)        # y = 0 is the bottom row
    u, v = (x + 0.5) / w, (y + 0.5) / h
    phi, theta = (u - 0.5) * 2 * math.pi, (v - 0.5) * math.pi
    return Vector((-math.cos(phi) * math.cos(theta), math.sin(phi) * math.cos(theta), math.sin(theta)))


def apply_env(env, sun):
    sc = bpy.context.scene
    world = sc.world or bpy.data.worlds.new('World')
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld')
    bg = nt.nodes.new('ShaderNodeBackground')
    nt.links.new(bg.outputs['Background'], out.inputs['Surface'])
    if env == 'flat':
        bg.inputs['Color'].default_value = (0.75, 0.8, 0.88, 1); bg.inputs['Strength'].default_value = 0.8
        sun.data.energy = 3.0
        sun.rotation_euler = (math.radians(55), 0, math.radians(-30))
        return
    path = os.path.join(HDRI_DIR, HDRI[env])
    img = bpy.data.images.get(HDRI[env]) or bpy.data.images.load(path)
    env_tex = nt.nodes.new('ShaderNodeTexEnvironment'); env_tex.image = img
    nt.links.new(env_tex.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 1.0
    if env == 'sun':
        d = brightest_dir(img)
        sun.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()      # lamp's +Z points at the sun
        sun.data.energy = SUN_STRENGTH
        sun.data.angle = math.radians(1.5)
        print(f"[preview] sun direction from HDRI: elevation {math.degrees(math.asin(d.z)):.0f} deg, "
              f"azimuth {math.degrees(math.atan2(d.y, d.x)):.0f} deg")
    else:
        sun.data.energy = 0.0


def main(names):
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    kit_mat, glass_mat = materials()
    mats = [kit_mat, glass_mat]
    col = collection('KIT_Sheet'); clear_collection(col)

    report = {}
    top_h = max(GH, FH) + 1.3
    for i, name in enumerate(names):
        x = (i - (len(names) - 1) / 2) * SPACING
        root = empty(name, col, loc=(x, 0, 0))
        tris = []
        for lod in (0, 1):
            mb = with_body(name, lod)
            mesh_object(f"{name}_LOD{lod}", mb, col, mats, parent=root, loc=(0, 0, lod * (top_h + ROW_GAP)))
            tris.append(mb.tri_count())
        report[name] = tris
        label(name, (x, -1.6, top_h + 0.55), col)
        label(f"{tris[0]} / {tris[1]} tris", (x, -1.6, top_h + 0.1), col, size=0.25)
    lx = (-(len(names) - 1) / 2 - 0.7) * SPACING
    label("LOD0", (lx, -1.6, 1.6), col, 0.5)
    label("LOD1", (lx, -1.6, 1.6 + top_h + ROW_GAP), col, 0.5)

    width, height = len(names) * SPACING + 6, 2 * top_h + ROW_GAP + 4
    render_scene('kit_sheet.png', (0, 0, (2 * top_h + ROW_GAP) / 2), width, height, yaw=-8)
    save_kit(BLEND_PATH)
    return report


# ---------------------------------------------------------------- B2: whole houses
# (label, ground floor, upper floors, right-side windows per floor (GF first), top, depth)
HOUSES = [
    ('SIDE 0 / san thuong / 12 m', 'GF_FoldGate', ['UF_Window', 'UF_BalconySolid'], [0, 0, 0], 'RF_Terrace', 12.0),
    ('SIDE 1F / mai lech do / 12 m', 'GF_WoodDoor', ['UF_Balcony', 'UF_Window'], ['0', '1F', '1F'], 'ROOF_Shed_Red', 12.0),
    ('SIDE 2 giua / hai doc xanh / 12 m', 'GF_Open', ['UF_BalconySolid', 'UF_Window'], ['2', '2', '2'], 'ROOF_Gable_Blue', 12.0),
    ('SIDE 1B-2B / bon doc do / 9 m', 'GF_FoldGate', ['UF_Window', 'UF_Cage'], ['1B', '2B', '2B'], 'ROOF_Hip_Red', 9.0),
    ('SIDE 1 tron / hai doc do / 16 m', 'GF_Shop', ['UF_Balcony', 'UF_Shutter', 'UF_Window'], ['0', '1F', '1', '1B'], 'ROOF_Gable_Red', 16.0),
    ('SIDE 2F / bon doc xanh / 16 m', 'GF_Roller', ['UF_BalconySolid', 'UF_BalconySolid'], ['2F', '2F', '2F'], 'ROOF_Hip_Blue', 16.0),
]
HOUSE_SPACING = 15.0
YAW = 32


def house_recipe(gf, ufs, side_r, top):
    """Recipe items (module, pos, rot); left walls blank, right walls with side_r windows."""
    z = [0.0] + [GH + FH * i for i in range(len(ufs))]
    items = [('Back_GF', (0, 0, 0), 0), ('SideL_GF_0', (0, 0, 0), 0), (f'SideR_GF_{side_r[0]}', (0, 0, 0), 0),
             (gf, (0, 0, 0), 0)]
    for i, uf in enumerate(ufs):
        zz = z[i + 1]
        items += [('Back_UF', (0, 0, zz), 0), ('SideL_UF_0', (0, 0, zz), 0),
                  (f'SideR_UF_{side_r[i + 1]}', (0, 0, zz), 0), (uf, (0, 0, zz), 0)]
    items.append((top, (0, 0, GH + FH * len(ufs)), 0))
    return items


def main_houses():
    import hanoi_house
    importlib.reload(hanoi_house)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    kit_mat, glass_mat = materials()
    mats = [kit_mat, glass_mat]
    col = collection('HOUSE_Sheet'); clear_collection(col)
    report = {}
    for i, (name, gf, ufs, side_r, top, depth) in enumerate(HOUSES):
        # lined up along the camera's screen-right axis so the row reads straight
        t = (i - (len(HOUSES) - 1) / 2) * HOUSE_SPACING
        x, y = t * math.cos(math.radians(YAW)), t * math.sin(math.radians(YAW))
        recipe = house_recipe(gf, ufs, side_r, top)
        root = empty(f"H{i}", col, loc=(x, y, 0))
        tris = []
        for lod in (0, 1):
            mb = hanoi_house.assemble(recipe, lod, depth)
            ob = mesh_object(f"H{i}_LOD{lod}", mb, col, mats, parent=root)
            ob.hide_render = lod > 0
            tris.append(mb.tri_count())
        report[name] = tris
        label(name, (x, y - 3.0, 0.45), col, 0.4)
        label(f"{tris[0]} / {tris[1]} tris", (x, y - 3.0, 0.05), col, 0.3)
    width = len(HOUSES) * HOUSE_SPACING + 4
    render_scene('houses_b2.png', (0, 6, 7.0), width, 26, yaw=YAW, pitch=20)
    save_kit(os.path.join(ROOT, "Blender", "HanoiHouses_Preview.blend"))
    return report


# ---------------------------------------------------------------- B3: a street of library houses
def main_street(n=16, seed=7):
    """A row of abutting houses from the B3 library plan: exposed-left house at the left end,
    exposed-right at the right end, party-wall houses between, random depth scale."""
    import random, hanoi_house, tube_generator
    importlib.reload(hanoi_house); importlib.reload(tube_generator)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    kit_mat, glass_mat = materials()
    mats = [kit_mat, glass_mat]
    col = collection('STREET'); clear_collection(col)
    lib = list(tube_generator.library_plan())
    rng = random.Random(seed)
    pick = lambda tag: rng.choice([h for h in lib if h[3]['exposed'] == tag])
    row = [pick('L')] + [pick('') for _ in range(n - 2)] + [pick('R')]
    lo_s, hi_s = tube_generator.DEPTH_SCALE
    for i, (vid, _, recipe, meta) in enumerate(row):
        x = (i - (n - 1) / 2) * 4.0
        mb = hanoi_house.assemble(recipe, 0, meta['depth'])
        ob = mesh_object(f"{vid}_{i}", mb, col, mats, loc=(x, 0, 0),
                         tint=(*hanoi_common.PREVIEW_TINT[:3], 1) if i % 3 else (0.55, 0.62, 0.70, 1))
        ob.scale.y = rng.uniform(lo_s, hi_s)
        print(f"[street] {i:2d} {vid:16s} depth {meta['depth'] * ob.scale.y:5.1f} m")
    width = n * 4.0 + 10
    render_scene('street_b3.png', (0, 4, 8.0), width, width * 0.45, yaw=28, pitch=18)
    # aerial: roofs
    sc = bpy.context.scene
    cam = sc.camera
    yaw, pitch = math.radians(28), math.radians(50)
    fwd = Vector((math.sin(-yaw) * math.cos(pitch), math.cos(-yaw) * math.cos(pitch), -math.sin(pitch)))
    cam.location = Vector((0, 6, 6)) - fwd * 150
    cam.rotation_euler = (math.pi / 2 - pitch, 0, yaw)
    sc.render.filepath = os.path.join(OUT_DIR, 'street_b3_aerial.png')
    bpy.ops.render.render(write_still=True)
    save_kit(os.path.join(ROOT, "Blender", "HanoiStreet_Preview.blend"))
    return {}


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    if '--flat' in argv:                       # old flat-sky check
        ENVS[:] = ['flat']; argv.remove('--flat')
    REPORT = (main_houses() if argv == ['--houses'] else main_street() if argv == ['--street']
              else main(argv or DEFAULT))
    for k, v in REPORT.items():
        print(f"[preview] {k:16s} tris LOD0/LOD1: {v}")
