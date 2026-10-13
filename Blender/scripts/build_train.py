"""TRAIN T1 — Hanoi metro cars (hanoi_train.py) in Blender/HanoiTrain.blend + preview.

Atlas first (plain Python):  python Blender/scripts/build_train_texture.py
Then, without touching the open Blender:
    blender -b --python Blender/scripts/build_train.py -- --build            (new file -> HanoiTrain.blend)
    blender -b Blender/HanoiTrain.blend --python Blender/scripts/build_train.py -- --build
    blender -b Blender/HanoiTrain.blend --python Blender/scripts/build_train.py -- --preview
    python Blender/scripts/train_sheet.py                                     (-> previews/train_t1_sheet.png)
T2 (LODs + FBX):
    blender -b Blender/HanoiTrain.blend --python Blender/scripts/build_train.py -- --export
    -> Export/Metro/FBX/SM_Train_End.fbx, SM_Train_Mid.fbx (root > <name>_LOD0/1/2, hanoi_train.LODS),
       Export/Metro/Train/T_Train.png + T_TrainData.png, Export/Metro/train.json (car lengths, gap,
       bogie centres for the Unity runner)

Scene: collection TRAIN_KIT = TRAIN_End, TRAIN_Mid (LOD0, origin = rail top under the car centre,
front = -Y) side by side at x 40 (studio); collection TRAIN_TEST = a 4-car train (End, Mid, Mid,
End turned round) on a straight 160 m viaduct piece built with hanoi_metro (track B, x = +2).
Material M_Train: Blender/train/T_Train.png (albedo) + T_TrainData.png (R roughness, G metallic).
"""
import importlib
import json
import math
import os
import sys

import bpy
from mathutils import Vector

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_common
import hanoi_train as ht
for _m in (hanoi_common, ht):
    importlib.reload(_m)
from hanoi_common import collection, clear_collection, save_kit

BLEND = os.path.join(ROOT, "Blender", "HanoiTrain.blend")
TRAIN_DIR = os.path.join(ROOT, "Blender", "train")
PREVIEW_DIR = os.path.join(ROOT, "Blender", "previews", "train_t1")
STUDIO_X = 40.0
TRACK_X = 2.0
CONSIST_Y0 = 30.0           # centre of the leading end car on the test viaduct


def check_open_file():
    cur = bpy.data.filepath
    if cur and os.path.normcase(os.path.abspath(cur)) != os.path.normcase(os.path.abspath(BLEND)):
        raise RuntimeError(f"Blender has '{cur}' open; open {BLEND} (or a new file) first. Nothing changed.")


def train_material():
    mat = bpy.data.materials.get('M_Train') or bpy.data.materials.new('M_Train')
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    out = N('ShaderNodeOutputMaterial'); out.location = (500, 0)
    bsdf = N('ShaderNodeBsdfPrincipled'); bsdf.location = (200, 0)
    texs = {}
    for i, (key, fname, data) in enumerate((('alb', 'T_Train.png', False), ('dat', 'T_TrainData.png', True))):
        img = bpy.data.images.get(fname) or bpy.data.images.load(os.path.join(TRAIN_DIR, fname))
        img.reload()
        img.colorspace_settings.name = 'Non-Color' if data else 'sRGB'
        t = N('ShaderNodeTexImage'); t.image = img; t.location = (-600, 300 - 300 * i)
        texs[key] = t
    L(texs['alb'].outputs['Color'], bsdf.inputs['Base Color'])
    sep = N('ShaderNodeSeparateColor'); sep.location = (-300, 0)
    L(texs['dat'].outputs['Color'], sep.inputs['Color'])
    L(sep.outputs['Red'], bsdf.inputs['Roughness'])
    L(sep.outputs['Green'], bsdf.inputs['Metallic'])
    L(bsdf.outputs[0], out.inputs['Surface'])
    mat.diffuse_color = (0.5, 0.6, 0.1, 1)
    return mat


def to_mesh(name, bm, mats, sharp_deg=35):
    old = bpy.data.meshes.get(name)
    if old is not None:
        old.name = name + '_old'
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    me.shade_smooth()
    me.set_sharp_from_angle(angle=math.radians(sharp_deg))
    return me


def link(name, me, col, loc=(0, 0, 0), rot_z=0.0):
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (0, 0, rot_z)
    return ob


def consist_positions():
    """[(kind, y centre, turned)] for End, Mid, Mid, End(turned), leading car front towards -Y."""
    e, m, g = ht.CAR['end_len'], ht.CAR['mid_len'], ht.GANGWAY_GAP
    y = CONSIST_Y0
    out = [('end', y, False)]
    y += e / 2 + g + m / 2; out.append(('mid', y, False))
    y += m + g; out.append(('mid', y, False))
    y += m / 2 + g + e / 2; out.append(('end', y, True))
    return out


def build():
    check_open_file()
    for ob in list(bpy.data.objects):
        if ob.name == 'Cube' and ob.type == 'MESH' and len(ob.data.vertices) == 8:
            bpy.data.objects.remove(ob, do_unlink=True)
    mat = train_material()
    kit = collection('TRAIN_KIT')
    test = collection('TRAIN_TEST')
    clear_collection(kit)
    clear_collection(test)
    report = {}
    meshes = {}
    for i, kind in enumerate(('end', 'mid')):
        me = to_mesh(f'TRAIN_{kind.capitalize()}', ht.car(kind, 0), [mat])
        meshes[kind] = me
        link(me.name, me, kit, loc=(STUDIO_X + 6 * i, 0, 0))
        dims = [max(v.co[k] for v in me.vertices) - min(v.co[k] for v in me.vertices) for k in range(3)]
        report[me.name] = dict(tris=ht.tris(me), size=[round(d, 2) for d in dims])

    # test viaduct: straight 160 m from the metro kit + piers every 30 m
    import build_metro
    importlib.reload(build_metro)
    hm = build_metro.hm
    mmats = build_metro.materials()
    frames = hm.path_frames([('line', 160.0)], step=4.0)
    me = build_metro.to_mesh('TestDeck', hm.deck(0, frames), mmats)
    link('TestDeck', me, test, loc=(0, -10, 0))
    pier = {p: build_metro.to_mesh(f'TestPier_{p}', fn(0), mmats) for p, fn in hm.PIER_PARTS.items()}
    for k in range(6):
        for p, pm in pier.items():
            link(f'TestPier{k}_{p}', pm, test, loc=(0, -10 + 30 * k, 0))
    for i, (kind, y, turned) in enumerate(consist_positions()):
        link(f'TestCar{i}', meshes[kind], test, loc=(TRACK_X, y, hm.RAIL_TOP), rot_z=math.pi if turned else 0.0)
    return report


# ---------------------------------------------------------------- T2: LODs + FBX
EXPORT_DIR = os.path.join(ROOT, "Export", "Metro")


def bogie_centres(kind):
    """Bogie centres (s, + = towards the cab / car front) as hanoi_train.car places them."""
    L = ht.CAR['end_len'] if kind == 'end' else ht.CAR['mid_len']
    front = L / 2 - ht.BOGIE['inset'] - (0.4 if kind == 'end' else 0.0)
    return [round(front, 3), round(-L / 2 + ht.BOGIE['inset'], 3)]


def export():
    import shutil
    check_open_file()
    mat = train_material()
    col = collection('TRAIN_EXPORT')
    clear_collection(col)
    for ob in list(col.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    fbx_dir = os.path.join(EXPORT_DIR, 'FBX')
    tex_dir = os.path.join(EXPORT_DIR, 'Train')
    os.makedirs(fbx_dir, exist_ok=True)
    os.makedirs(tex_dir, exist_ok=True)
    for f in ('T_Train.png', 'T_TrainData.png'):
        shutil.copy2(os.path.join(TRAIN_DIR, f), os.path.join(tex_dir, f))
    cars = []
    for i, kind in enumerate(('end', 'mid')):
        name = f'SM_Train_{kind.capitalize()}'
        root = bpy.data.objects.new(name, None)
        col.objects.link(root)
        root.location = (STUDIO_X + 20 + 8 * i, 0, 0)
        tris = {}
        for lod in ht.LODS:
            me = to_mesh(f'{name}_LOD{lod}', ht.car(kind, lod), [mat])
            ob = bpy.data.objects.new(me.name, me)
            col.objects.link(ob)
            ob.parent = root
            ob.location = (0, 0, 4.5 * lod)                 # stacked in the .blend only
            tris[f'LOD{lod}'] = ht.tris(me)
        bpy.context.view_layer.update()
        hanoi_common.export_fbx(os.path.join(fbx_dir, f'{name}.fbx'), [root], zero_roots=True)
        L = ht.CAR['end_len'] if kind == 'end' else ht.CAR['mid_len']
        cars.append(dict(name=name, kind=kind, length=L, tris=tris, bogies=bogie_centres(kind),
                         # s of the outermost point: the end car's nose tip / bumper, else the bellows
                         front=round(L / 2, 3), rear=round(-L / 2, 3)))
    data = dict(units='metres, Unity axes: origin = rail top under the car centre, car front = +Z',
                gap=ht.GANGWAY_GAP, consist=['end', 'mid', 'mid', 'end_turned'], cars=cars,
                material='M_Train: Hanoi/Vehicle, Export/Metro/Train/T_Train.png (albedo) + '
                         'T_TrainData.png (R roughness, G metallic)')
    with open(os.path.join(EXPORT_DIR, 'train.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    return data


# ---------------------------------------------------------------- preview (background)
def look(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def new_cam(name, loc, target, lens=35, ortho=None):
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    if ortho:
        cam.data.type = 'ORTHO'; cam.data.ortho_scale = ortho
    else:
        cam.data.lens = lens
    cam.data.clip_start = 0.1
    cam.data.clip_end = 2000
    look(cam, target)
    bpy.context.view_layer.update()
    return cam


def render(path, cam, res):
    sc = bpy.context.scene
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print('[preview]', os.path.basename(path))


def render_preview():
    import preview_modules
    importlib.reload(preview_modules)
    sc = bpy.context.scene
    for ob in list(bpy.data.objects):
        if ob.type in ('CAMERA', 'LIGHT') or ob.name.startswith('PrevGround'):
            bpy.data.objects.remove(ob, do_unlink=True)
    try:
        sc.render.engine = 'BLENDER_EEVEE'
    except TypeError:
        sc.render.engine = 'BLENDER_EEVEE_NEXT'
    sc.view_settings.view_transform = 'Standard'
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    sc.collection.objects.link(sun)
    preview_modules.apply_env('sun', sun)
    gm = bpy.data.materials.get('M_PrevGround') or bpy.data.materials.new('M_PrevGround')
    gm.use_nodes = True
    next(n for n in gm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Base Color'].default_value = (0.06, 0.06, 0.06, 1)
    me = bpy.data.meshes.new('PrevGround')
    me.from_pydata([(-80, -80, -0.01), (120, -80, -0.01), (120, 200, -0.01), (-80, 200, -0.01)], [], [(0, 1, 2, 3)])
    me.materials.append(gm)
    g = bpy.data.objects.new('PrevGround', me)
    sc.collection.objects.link(g)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    o = PREVIEW_DIR
    y0, rt = CONSIST_Y0, 12.0
    tip = y0 - ht.CAR['end_len'] / 2
    # like Ref/train.webp: standing beside the track at the front, slightly low
    render(os.path.join(o, 'front34.png'), new_cam('CamF34', (TRACK_X + 1.75, tip - 9.0, rt + 1.2), (TRACK_X, tip + 4, rt + 2.0), 28), (1500, 1000))
    render(os.path.join(o, 'drone.png'), new_cam('CamDrone', (-26, tip - 35, rt + 20), (TRACK_X, y0 + 25, rt + 1), 30), (1600, 1000))
    render(os.path.join(o, 'deck_side.png'), new_cam('CamDS', (-2.6, y0 + 8, rt + 1.7), (TRACK_X, y0 + 30, rt + 2.0), 24), (1500, 1000))
    S = STUDIO_X
    render(os.path.join(o, 'studio_front.png'), new_cam('CamSF', (S, -14, 2.2), (S, 0, 2.0), ortho=4.6), (900, 1000))
    render(os.path.join(o, 'studio_end_side.png'), new_cam('CamSE', (S - 30, 0, 2.2), (S, 0, 2.2), ortho=22), (1800, 520))
    render(os.path.join(o, 'studio_mid_side.png'), new_cam('CamSM', (S + 6 + 30, 0, 2.2), (S + 6, 0, 2.2), ortho=22), (1800, 520))
    render(os.path.join(o, 'studio_34.png'), new_cam('CamS34', (S - 7, -17, 3.2), (S, -6, 1.8), 35), (1400, 1000))
    render(os.path.join(o, 'studio_under.png'), new_cam('CamSU', (S + 4.5, 3, 0.6), (S, 6.5, 0.45), 30), (1400, 900))


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--preview" in argv:
        render_preview()
    elif "--export" in argv:
        print('[export]', json.dumps(export()))
        save_kit(BLEND)
    else:
        print('[train]', json.dumps(build()))
        save_kit(BLEND)
