"""PROPS P1 — power pole + "NGÕ" alley sign (hanoi_props.py) in Blender/HanoiProps.blend.

Atlas first (plain Python):  python Blender/scripts/build_props_texture.py
Then, without touching the open Blender:
    blender -b --python Blender/scripts/build_props.py -- --build          (new file -> HanoiProps.blend)
    blender -b Blender/HanoiProps.blend --python Blender/scripts/build_props.py -- --build [--force]
    blender -b Blender/HanoiProps.blend --python Blender/scripts/build_props.py -- --preview
    python Blender/scripts/props_sheet.py                                   (-> previews/props_p1_sheet.png)
P2 (LODs + FBX, LOD0 = the working objects as they are, LOD1 from hanoi_props.LODS):
    blender -b Blender/HanoiProps.blend --python Blender/scripts/build_props.py -- --export
    -> Export/Props/FBX/SM_PowerPole.fbx, SM_SignNgo.fbx (root > <name>_LOD0/_LOD1),
       Export/Props/Textures/T_StreetProps*.png, entries in Export/Props/props.json

Scene: collection PROPS with PROP_PowerPole and PROP_SignNgo (LOD0, origin = ground at the pole
axis, street side = -Y), side by side. --build refuses to overwrite a mesh edited by hand.
Material M_HanoiProps: Blender/props/T_StreetProps.png (albedo), T_StreetPropsData.png
(R roughness, G metallic), T_StreetProps_N.png (OpenGL normal).
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
import hanoi_props
for m in (hanoi_common, hanoi_props):
    importlib.reload(m)
from hanoi_common import collection, clear_collection, save_kit
from hanoi_props import LODS, power_pole, sign_ngo, tris

BLEND = os.path.join(ROOT, "Blender", "HanoiProps.blend")
PROPS_DIR = os.path.join(ROOT, "Blender", "props")
PREVIEW_DIR = os.path.join(ROOT, "Blender", "previews", "props_p1")
ITEMS = {   # object -> (builder, location in the working scene)
    'PROP_PowerPole': (power_pole, (0, 0, 0)),
    'PROP_SignNgo':   (sign_ngo, (1.6, 0, 0)),
}
EXPORT_NAMES = {'PROP_PowerPole': 'SM_PowerPole', 'PROP_SignNgo': 'SM_SignNgo'}
EXPORT_DIR = os.path.join(ROOT, "Export", "Props")


def check_open_file():
    cur = bpy.data.filepath
    if cur and os.path.normcase(os.path.abspath(cur)) != os.path.normcase(os.path.abspath(BLEND)):
        raise RuntimeError(f"Blender has '{cur}' open; open {BLEND} (or a new file) first. Nothing changed.")


def props_material():
    mat = bpy.data.materials.get('M_HanoiProps') or bpy.data.materials.new('M_HanoiProps')
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    out = N('ShaderNodeOutputMaterial'); out.location = (500, 0)
    bsdf = N('ShaderNodeBsdfPrincipled'); bsdf.location = (200, 0)
    texs = {}
    for i, (key, fname, data) in enumerate((('alb', 'T_StreetProps.png', False),
                                            ('dat', 'T_StreetPropsData.png', True),
                                            ('nrm', 'T_StreetProps_N.png', True))):
        img = bpy.data.images.get(fname) or bpy.data.images.load(os.path.join(PROPS_DIR, fname))
        img.reload()
        img.colorspace_settings.name = 'Non-Color' if data else 'sRGB'
        t = N('ShaderNodeTexImage'); t.image = img; t.location = (-600, 300 - 300 * i)
        texs[key] = t
    L(texs['alb'].outputs['Color'], bsdf.inputs['Base Color'])
    sep = N('ShaderNodeSeparateColor'); sep.location = (-300, 0)
    L(texs['dat'].outputs['Color'], sep.inputs['Color'])
    L(sep.outputs['Red'], bsdf.inputs['Roughness'])
    L(sep.outputs['Green'], bsdf.inputs['Metallic'])
    nm = N('ShaderNodeNormalMap'); nm.location = (-300, -300)
    L(texs['nrm'].outputs['Color'], nm.inputs['Color'])
    L(nm.outputs['Normal'], bsdf.inputs['Normal'])
    L(bsdf.outputs[0], out.inputs['Surface'])
    mat.diffuse_color = (0.6, 0.6, 0.58, 1)
    return mat


def to_mesh(name, bm, mat, sharp_deg=40):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    me.shade_smooth()
    me.set_sharp_from_angle(angle=math.radians(sharp_deg))
    return me


def build(force=False):
    check_open_file()
    for ob in list(bpy.data.objects):          # the factory cube sits on the origin
        if ob.name == 'Cube' and ob.type == 'MESH' and len(ob.data.vertices) == 8:
            bpy.data.objects.remove(ob, do_unlink=True)
    mat = props_material()
    if not force:
        for name, (fn, _) in ITEMS.items():
            ob = bpy.data.objects.get(name)
            if ob is None:
                continue
            me = to_mesh('_check', fn(0), mat)
            same = (len(me.vertices), tris(me)) == (len(ob.data.vertices), tris(ob.data))
            bpy.data.meshes.remove(me)
            if not same:
                raise RuntimeError(f"{name} was edited by hand; re-run with --force to overwrite it.")
    col = collection('PROPS')
    clear_collection(col)
    report = {}
    for name, (fn, loc) in ITEMS.items():
        me = to_mesh(name, fn(0), mat)
        ob = bpy.data.objects.new(name, me)
        col.objects.link(ob)
        ob.location = loc
        bpy.context.view_layer.update()
        zs = [(ob.matrix_world @ v.co).z for v in me.vertices]
        dims = ob.dimensions
        report[name] = dict(tris=tris(me), size=[round(dims.x, 3), round(dims.y, 3), round(dims.z, 3)],
                            z=[round(min(zs), 3), round(max(zs), 3)])
    return report


# ---------------------------------------------------------------- P2: LODs + FBX
def export_lods():
    import shutil
    check_open_file()
    mat = props_material()
    col = collection('PROPS_EXPORT')
    clear_collection(col)
    for ob in list(col.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    fbx_dir = os.path.join(EXPORT_DIR, 'FBX')
    tex_dir = os.path.join(EXPORT_DIR, 'Textures')
    os.makedirs(fbx_dir, exist_ok=True)
    os.makedirs(tex_dir, exist_ok=True)
    for f in ('T_StreetProps.png', 'T_StreetPropsData.png', 'T_StreetProps_N.png'):
        shutil.copy2(os.path.join(PROPS_DIR, f), os.path.join(tex_dir, f))
    reports = []
    for i, (obname, (fn, _)) in enumerate(ITEMS.items()):
        work = bpy.data.objects.get(obname)
        if work is None:
            raise RuntimeError(f"working object {obname} is missing in {BLEND}")
        name = EXPORT_NAMES[obname]
        root = bpy.data.objects.new(name, None)
        col.objects.link(root)
        root.location = (4 + 2 * i, 0, 0)
        rep = {'name': name, 'tris': {}}
        for lod in LODS:
            if lod == 0:                            # the working mesh as edited, in prop space
                me = work.data.copy()
                me.transform(work.matrix_world.to_3x3().to_4x4())
            else:
                me = to_mesh(f'{name}_LOD{lod}', fn(lod), mat)
            me.name = f'{name}_LOD{lod}'
            ob = bpy.data.objects.new(me.name, me)
            col.objects.link(ob)
            ob.parent = root
            ob.location = (0, lod * 1.0, 0)         # side by side in the .blend only
            rep['tris'][f'LOD{lod}'] = tris(me)
            if lod == 0:
                lo = [min((v.co[k]) for v in me.vertices) for k in range(3)]
                hi = [max((v.co[k]) for v in me.vertices) for k in range(3)]
        bpy.context.view_layer.update()
        hanoi_common.export_fbx(os.path.join(fbx_dir, f'{name}.fbx'), [root], zero_roots=True)
        rep.update({
            'units': 'metres, Unity axes (x right, y up, z forward = street side); origin = ground at '
                     'the pole axis',
            'size': [round(hi[0] - lo[0], 3), round(hi[2] - lo[2], 3), round(hi[1] - lo[1], 3)],
            'material': 'M_HanoiProps: Export/Props/Textures/T_StreetProps.png (albedo), '
                        'T_StreetPropsData.png (R roughness, G metallic), T_StreetProps_N.png (OpenGL normal)',
        })
        reports.append(rep)
    manifest = os.path.join(EXPORT_DIR, 'props.json')
    data = json.load(open(manifest, encoding='utf-8')) if os.path.exists(manifest) else {'props': []}
    names = {r['name'] for r in reports}
    data['props'] = [p for p in data.get('props', []) if p.get('name') not in names] + reports
    with open(manifest, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    return reports


# ---------------------------------------------------------------- preview (background)
def look(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def new_cam(name, loc, target, lens=50, ortho=None):
    cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    if ortho:
        cam.data.type = 'ORTHO'; cam.data.ortho_scale = ortho
    else:
        cam.data.lens = lens
    cam.data.clip_start = 0.05
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
        if ob.type in ('CAMERA', 'LIGHT'):
            bpy.data.objects.remove(ob, do_unlink=True)
    try:
        sc.render.engine = 'BLENDER_EEVEE'
    except TypeError:
        sc.render.engine = 'BLENDER_EEVEE_NEXT'
    sc.view_settings.view_transform = 'Standard'
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    sc.collection.objects.link(sun)
    preview_modules.apply_env('sun', sun)
    # pavement: a light slab like the Hanoi sidewalk, the road beyond it
    for size, loc, colr in (((12, 6, 0.1), (0.8, 2.0, -0.05), (0.16, 0.15, 0.135)),
                            ((40, 20, 0.1), (0.8, -11.5, -0.25), (0.05, 0.05, 0.05))):
        bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
        g = bpy.context.active_object
        g.scale = size
        gm = bpy.data.materials.new('M_Ground'); gm.use_nodes = True
        next(n for n in gm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Base Color'].default_value = colr + (1,)
        g.data.materials.append(gm)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    out = PREVIEW_DIR
    sx = ITEMS['PROP_SignNgo'][1][0]
    render(os.path.join(out, 'pole_full.png'), new_cam('CamPF', (-3.2, -6.5, 1.6), (0.4, 0, 4.2), 30), (800, 1200))
    render(os.path.join(out, 'pole_base.png'), new_cam('CamPB', (-1.1, -1.9, 1.5), (0, -0.05, 1.5), 35), (900, 1100))
    render(os.path.join(out, 'pole_box.png'), new_cam('CamBX', (0.9, -1.6, 3.9), (0, -0.25, 3.6), 40), (900, 900))
    render(os.path.join(out, 'sign_full.png'), new_cam('CamSF', (sx - 1.8, -4.2, 1.7), (sx + 0.2, 0, 1.6), 35), (800, 1100))
    render(os.path.join(out, 'sign_plate.png'), new_cam('CamSP', (sx + 0.15, -1.6, 2.45), (sx + 0.35, 0, 2.6), 40), (1100, 800))
    render(os.path.join(out, 'sign_back.png'), new_cam('CamSB', (sx + 0.9, 1.6, 2.3), (sx + 0.35, 0, 2.6), 40), (1100, 800))
    render(os.path.join(out, 'street.png'), new_cam('CamST', (-4.5, -11, 1.7), (0.8, 0, 2.6), 30), (1600, 1000))


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--preview" in argv:
        render_preview()
    elif "--export" in argv:
        print('[export]', json.dumps(export_lods()))
        save_kit(BLEND)
    else:
        print('[props]', json.dumps(build(force="--force" in argv)))
        save_kit(BLEND)
