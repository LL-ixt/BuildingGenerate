"""CART — the 3-wheel hand garbage cart (hanoi_cart.py): C1 working model, C2 LODs + FBX.

Without touching the open Blender (preferred):
    blender -b --python Blender/scripts/build_cart.py -- --build      (new file -> Blender/HanoiCart.blend)
    blender -b Blender/HanoiCart.blend --python Blender/scripts/build_cart.py -- --build [--force]
    blender -b Blender/HanoiCart.blend --python Blender/scripts/build_cart.py -- --preview
    python Blender/scripts/cart_sheet.py                               (-> previews/cart_c1_sheet.png)
C2 (LODs + FBX, from the hand-edited working model; does not touch it):
    blender -b Blender/HanoiCart.blend --python Blender/scripts/build_cart.py -- --export
    blender -b --factory-startup --python Blender/scripts/build_cart.py -- --verify
    blender -b Blender/HanoiCart.blend --python Blender/scripts/build_cart.py -- --preview-lods
    python Blender/scripts/cart_sheet.py c2                            (-> previews/cart_c2_sheet.png)

Working model (collection CART; origin = ground under the big-wheel axle, front = -Y, handle = +Y):
    CART_Body          bin + frame + handle (one mesh)
    CART_WheelL / R    origin = axle (spin around X)
    CART_Caster        swivel fork, origin = swivel pivot (turn around Z)
      CART_CasterWheel origin = small-wheel axle (child of the fork)
The user edits these by hand; --build refuses to overwrite a mesh that no longer matches the
script (use --force), --export copies them as LOD0 and generates LOD1/LOD2 from hanoi_cart.LODS.

Export (collection CART_EXPORT, beside the working model):
    SM_Cart_Rac      > SM_Cart_Rac_LOD0/1/2 (one merged mesh per LOD, parked prop)
    SM_Cart_Rac_Rig  > Cart_{Body,WheelL,WheelR,Caster,CasterWheel}_LODn (origins on their pivots,
                       flat hierarchy), HAND_L / HAND_R
    -> Export/Props/FBX/SM_Cart_Rac(.fbx|_Rig.fbx) + Export/Props/props.json
All meshes use M_HanoiMoto (vehicle atlas); slot PAINT tinted by the object prop paint_color.
"""
import importlib
import json
import os
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_common
import hanoi_moto
import hanoi_cart
import build_moto
for m in (hanoi_common, hanoi_moto, hanoi_cart, build_moto):
    importlib.reload(m)
from hanoi_common import collection, clear_collection, empty, save_kit
from hanoi_moto import Parts, tris
from hanoi_cart import (CASTER, HANDLE, LODS, WHEEL_R, WHEEL_X, body, caster_fork, caster_wheel,
                        spoke_wheel)
from build_moto import export_selection, moto_material, new_cam, render, srgb_to_lin, to_unity

BLEND = os.path.join(ROOT, "Blender", "HanoiCart.blend")
PREVIEW_ROOT = os.path.join(ROOT, "Blender", "previews")
EXPORT_DIR = os.path.join(ROOT, "Export", "Props")
FBX_OUT = os.path.join(EXPORT_DIR, "FBX")
CART_GREEN = (88, 190, 52)          # sRGB, Ref/xe rac.jpg
STATIC_X, RIG_X = 2.0, 6.5          # where the export roots sit in the .blend (snapped to 0 on export)

# group -> (working object, pieces(lod), pivot in the working model)
GROUPS = {
    'Body':        ('CART_Body', body),
    'WheelL':      ('CART_WheelL', spoke_wheel),
    'WheelR':      ('CART_WheelR', spoke_wheel),
    'Caster':      ('CART_Caster', caster_fork),
    'CasterWheel': ('CART_CasterWheel', caster_wheel),
}


def green_linear():
    return tuple(srgb_to_lin(c) for c in CART_GREEN) + (1.0,)


def check_open_file():
    cur = bpy.data.filepath
    if cur and os.path.normcase(os.path.abspath(cur)) != os.path.normcase(os.path.abspath(BLEND)):
        raise RuntimeError(f"Blender has '{cur}' open; open {BLEND} (or a new file) first. Nothing changed.")


def parts_mesh(name, pieces, mat):
    p = Parts()
    for bm_, slot in pieces:
        p.add(bm_, slot)
    me = p.to_mesh(name, mat)
    if 'slot' in me.attributes:
        me.attributes.remove(me.attributes['slot'])
    return me


# ---------------------------------------------------------------- C1: working model
def build(force=False):
    check_open_file()
    for ob in list(bpy.data.objects):          # the factory cube sits on the origin
        if ob.name == 'Cube' and ob.type == 'MESH' and len(ob.data.vertices) == 8:
            bpy.data.objects.remove(ob, do_unlink=True)
    mat = moto_material()
    if not force:                              # never wipe hand edits silently
        for g, (obname, fn) in GROUPS.items():
            ob = bpy.data.objects.get(obname)
            if ob is None:
                continue
            me = parts_mesh('_check', fn(0), mat)
            same = (len(me.vertices), tris(me)) == (len(ob.data.vertices), tris(ob.data))
            bpy.data.meshes.remove(me)
            if not same:
                raise RuntimeError(f"{obname} was edited by hand (differs from the script); "
                                   f"re-run with --force to overwrite it. Nothing changed.")
    col = collection('CART')
    clear_collection(col)
    report = {}
    root = empty('CART_Rac', col)
    root.empty_display_size = 0.4

    def make(name, pieces, loc, parent=root):
        me = parts_mesh(name, pieces, mat)
        ob = bpy.data.objects.new(name, me)
        col.objects.link(ob)
        ob.parent = parent
        ob.location = Vector(loc)
        ob['paint_color'] = green_linear()
        report[name] = tris(me)
        return ob

    make('CART_Body', body(0), (0, 0, 0))
    for name, sx in (('CART_WheelL', 1), ('CART_WheelR', -1)):
        make(name, spoke_wheel(0), (sx * WHEEL_X, 0, WHEEL_R))
    fork = make('CART_Caster', caster_fork(0), (0, CASTER['y'], CASTER['top']))
    make('CART_CasterWheel', caster_wheel(0), (0, CASTER['trail'], CASTER['r'] - CASTER['top']), parent=fork)
    for name, p in anchors().items():
        a = empty(name, col, p)
        a.empty_display_size = 0.06
        a.parent = root
    bpy.context.view_layer.update()
    report['total'] = sum(report.values())
    lo, hi = _bounds([o for o in col.objects if o.type == 'MESH'])
    report['size_xyz'] = [round(v, 3) for v in hi - lo]
    report['wheel_bottoms'] = {o.name: round(min((o.matrix_world @ v.co).z for v in o.data.vertices), 4)
                               for o in col.objects if 'Wheel' in o.name}
    return report


def anchors():
    return {name: Vector((sx * (HANDLE['x'] - 0.09), HANDLE['y'], HANDLE['z']))
            for name, sx in (('HAND_L', 1), ('HAND_R', -1))}


def _bounds(obs):
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    for ob in obs:
        for v in ob.data.vertices:
            p = ob.matrix_world @ v.co
            lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
    return lo, hi


# ---------------------------------------------------------------- C2: LODs + FBX
def group_meshes(lod, mat):
    """{group: (mesh in pivot space, pivot world position)}. LOD0 = copies of the hand-edited
    working objects; LOD1/2 = hanoi_cart pieces, oriented like the working objects."""
    out = {}
    for g, (obname, fn) in GROUPS.items():
        ob = bpy.data.objects.get(obname)
        if ob is None:
            raise RuntimeError(f"working object {obname} is missing in {BLEND}")
        mw = ob.matrix_world
        rot = mw.to_3x3().to_4x4()                 # rotation / scale of the working object
        if lod == 0:
            me = ob.data.copy()
            me.name = f'Cart_{g}_LOD0'
        else:
            me = parts_mesh(f'Cart_{g}_LOD{lod}', fn(lod), mat)
            if g == 'Body':                         # pieces are built in cart space
                me.transform(mw.inverted())
        me.transform(rot)
        out[g] = (me, mw.translation.copy())
    return out


def merged(name, groups):
    import bmesh
    bm = bmesh.new()
    for me, pivot in groups.values():
        tmp = me.copy()
        tmp.transform(Matrix.Translation(pivot))
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def export_lods():
    check_open_file()
    mat = moto_material()
    col = collection('CART_EXPORT')
    clear_collection(col)
    for ob in list(col.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    paint = green_linear()
    static = empty('SM_Cart_Rac', col, (STATIC_X, 0, 0))
    rig = empty('SM_Cart_Rac_Rig', col, (RIG_X, 0, 0))
    report = {'name': 'SM_Cart_Rac', 'tris': {}, 'rig_tris': {}}
    pivots = {}
    for lod in LODS:
        groups = group_meshes(lod, mat)
        me = merged(f'SM_Cart_Rac_LOD{lod}', groups)
        me.materials.clear()
        me.materials.append(mat)
        ob = bpy.data.objects.new(me.name, me)
        col.objects.link(ob)
        ob.parent = static
        ob.location = (lod * 1.3, 0, 0)            # side by side in the .blend only
        ob['paint_color'] = paint
        report['tris'][f'LOD{lod}'] = tris(me)
        # flat rig: every mesh a direct child of the root, origin on its pivot (Unity re-parents
        # CasterWheel under Caster)
        n = 0
        for g, (gm, pivot) in groups.items():
            o = bpy.data.objects.new(gm.name, gm)
            col.objects.link(o)
            o.parent = rig
            o.location = pivot
            o['paint_color'] = paint
            n += tris(gm)
        report['rig_tris'][f'LOD{lod}'] = n
        if lod == 0:
            pivots = {g: p for g, (_, p) in groups.items()}
    for name, p in anchors().items():
        a = empty(name, col)
        a.empty_display_size = 0.06
        a.parent = rig
        a.location = p
    bpy.context.view_layer.update()

    os.makedirs(FBX_OUT, exist_ok=True)
    hanoi_common.export_fbx(os.path.join(FBX_OUT, 'SM_Cart_Rac.fbx'), [static], zero_roots=True)
    export_selection(os.path.join(FBX_OUT, 'SM_Cart_Rac_Rig.fbx'), [rig])

    lo, hi = _bounds([bpy.data.objects[g] for g, _ in GROUPS.values()])
    report.update({
        'units': 'metres, Unity axes (x right, y up, z forward = cart front); origin = ground under '
                 'the big-wheel axle',
        'size': [round(hi.x - lo.x, 3), round(hi.z - lo.z, 3), round(hi.y - lo.y, 3)],
        'material': 'M_HanoiMoto (vehicle atlas Export/Vehicles/Textures/T_MotoAtlas.png + '
                    'T_MotoAtlasData.png, palette cells only); paint tint where UV is in the PAINT cell',
        'paint_colour_srgb': list(CART_GREEN),
        'rig': {
            'wheel_l': {'pivot': to_unity(pivots['WheelL']), 'radius': WHEEL_R, 'spin_axis': [1, 0, 0]},
            'wheel_r': {'pivot': to_unity(pivots['WheelR']), 'radius': WHEEL_R, 'spin_axis': [1, 0, 0]},
            'caster': {'pivot': to_unity(pivots['Caster']), 'swivel_axis': [0, 1, 0]},
            'caster_wheel': {'pivot': to_unity(pivots['CasterWheel']), 'radius': CASTER['r'],
                             'spin_axis': [1, 0, 0]},
            'hierarchy': 'FBX is flat: SM_Cart_Rac_Rig > Cart_Body_LODn, Cart_WheelL_LODn, Cart_WheelR_LODn, '
                         'Cart_Caster_LODn, Cart_CasterWheel_LODn (origins on their pivots), HAND_L/R. '
                         'In Unity: CasterWheel goes under the Caster pivot; Caster swivels about Y, '
                         'wheels spin about local X.',
        },
        'anchors': {k: to_unity(v) for k, v in anchors().items()},
    })
    manifest = os.path.join(EXPORT_DIR, 'props.json')
    data = {'props': []}
    if os.path.exists(manifest):
        data = json.load(open(manifest, encoding='utf-8'))
    data['props'] = [p for p in data.get('props', []) if p.get('name') != report['name']] + [report]
    with open(manifest, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    return report


def verify_fbx():
    """Re-import both FBX files in an empty scene and print names / positions / tris."""
    for f in ('SM_Cart_Rac.fbx', 'SM_Cart_Rac_Rig.fbx'):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=os.path.join(FBX_OUT, f))
        new = [o for o in bpy.data.objects if o not in before]
        for o in sorted(new, key=lambda o: o.name):
            info = f"{o.type} parent={o.parent.name if o.parent else '-'} " \
                   f"world={tuple(round(v, 3) for v in o.matrix_world.translation)}"
            if o.type == 'MESH':
                zs = [(o.matrix_world @ v.co).z for v in o.data.vertices]
                info += f" tris={tris(o.data)} z=[{min(zs):.3f},{max(zs):.3f}] uv={[u.name for u in o.data.uv_layers]}"
            print(f"[verify] {f}: {o.name} {info}")
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)


# ---------------------------------------------------------------- previews (background)
def preview_scene():
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


def add_ground():
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
    g = bpy.context.active_object
    for c in list(g.users_collection):
        c.objects.unlink(g)
    bpy.context.scene.collection.objects.link(g)
    gm = bpy.data.materials.new('M_Ground'); gm.use_nodes = True
    next(n for n in gm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Base Color'].default_value = (0.32, 0.32, 0.31, 1)
    g.data.materials.append(gm)


def render_preview():
    preview_scene()
    out = os.path.join(PREVIEW_ROOT, 'cart_c1')
    os.makedirs(out, exist_ok=True)
    if 'CART_EXPORT' in bpy.data.collections:
        bpy.data.collections['CART_EXPORT'].hide_render = True
    tgt = (0, 0.2, 0.6)
    # orthographic: side (from +X, like the refs) and back, transparent
    render(os.path.join(out, 'side.png'), new_cam('CamSide', (8, 0.25, 0.6), (0, 0.25, 0.6), ortho=2.0),
           (1000, 760), transparent=True)
    render(os.path.join(out, 'back.png'), new_cam('CamBack', (0, 8, 0.6), (0, 0, 0.6), ortho=1.6),
           (800, 760), transparent=True)
    render(os.path.join(out, 'top.png'), new_cam('CamTop', (0, 0.25, 6), (0, 0.25, 0), ortho=2.0),
           (700, 1000))
    add_ground()
    render(os.path.join(out, 'q34_front.png'), new_cam('CamQF', (2.6, -2.6, 1.7), tgt, 40), (1400, 1050))
    render(os.path.join(out, 'q34_rear.png'), new_cam('CamQR', (-2.4, 3.1, 1.8), tgt, 40), (1400, 1050))
    render(os.path.join(out, 'ref1_view.png'), new_cam('CamR1', (-1.9, -2.3, 1.75), (0, 0.15, 0.55), 40),
           (1200, 980))
    corners = [o.matrix_world @ Vector(c) for o in bpy.data.collections['CART'].objects
               if o.type == 'MESH' for c in o.bound_box]
    d = Vector((0.6, -0.8, 0)).normalized() * 20
    render(os.path.join(out, 'far20.png'), new_cam('CamFar20', (d.x, d.y, 1.7), tgt, 31.2), (1920, 1080),
           crop_to=corners)


def render_lods():
    """Each LOD alone at the origin: close 3/4, and what a 1080p / 60° camera sees at 8, 20, 50 m."""
    preview_scene()
    for c in bpy.data.collections:
        c.hide_render = c.name != 'CART_EXPORT'
    add_ground()
    rig = bpy.data.objects['SM_Cart_Rac_Rig']
    for o in [rig] + list(rig.children_recursive):
        o.hide_render = True
    bpy.data.objects['SM_Cart_Rac'].location = (0, 0, 0)
    lods = [bpy.data.objects[f'SM_Cart_Rac_LOD{k}'] for k in LODS]
    out = os.path.join(PREVIEW_ROOT, 'cart_c2')
    os.makedirs(out, exist_ok=True)
    tgt = (0, 0.2, 0.6)
    for k, ob in enumerate(lods):
        for o in lods:
            o.hide_render = o is not ob
            o.location = (0, 0, 0)
        bpy.context.view_layer.update()
        render(os.path.join(out, f'lod{k}_q34.png'), new_cam(f'CamQ{k}', (-2.4, 3.1, 1.8), tgt, 40), (900, 700))
        corners = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        for dist in (8, 20, 50):
            d = Vector((0.6, -0.8, 0)).normalized() * dist
            render(os.path.join(out, f'lod{k}_far{dist}.png'),
                   new_cam(f'CamF{k}{dist}', (d.x, d.y, 1.7), tgt, 31.2), (1920, 1080), crop_to=corners)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--preview" in argv:
        render_preview()
    elif "--export" in argv:
        print('[export]', json.dumps(export_lods()))
        save_kit(BLEND)
    elif "--verify" in argv:
        verify_fbx()
    elif "--preview-lods" in argv:
        render_lods()
    else:
        print('[cart]', json.dumps(build(force="--force" in argv)))
        save_kit(BLEND)
