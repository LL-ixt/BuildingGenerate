"""METRO V1 — viaduct kit (hanoi_metro.py) in Blender/HanoiMetro.blend + preview + export.

Without touching the open Blender:
    blender -b --python Blender/scripts/build_metro.py -- --build                 (new file -> HanoiMetro.blend)
    blender -b Blender/HanoiMetro.blend --python Blender/scripts/build_metro.py -- --build
    blender -b Blender/HanoiMetro.blend --python Blender/scripts/build_metro.py -- --preview
    python Blender/scripts/metro_sheet.py                                         (-> previews/metro_v1_sheet.png)
    blender -b Blender/HanoiMetro.blend --python Blender/scripts/build_metro.py -- --export
    -> Export/Metro/FBX/SM_MetroPier.fbx (root > SM_MetroPier_{Column,Cap,Footing}_LOD{0,1}, all with
       their origin on the ground at the pier axis), Export/Metro/metro.json (dimensions + deck
       profiles per LOD for the Unity sweep).

Scene: collection METRO_KIT (pier parts, LOD0 + LOD1 side by side at x -20 / -30) and METRO_TEST
(3 straight spans + a 220 m-radius curve: deck swept along the path, piers every SPAN, ground,
a few massing boxes for scale). Flat colours (MAT_COLOURS) until the texture step.
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
import hanoi_metro as hm
for _m in (hanoi_common, hm):
    importlib.reload(_m)
from hanoi_common import collection, clear_collection, save_kit

BLEND = os.path.join(ROOT, "Blender", "HanoiMetro.blend")
PREVIEW_DIR = os.path.join(ROOT, "Blender", "previews", "metro_v1")
EXPORT_DIR = os.path.join(ROOT, "Export", "Metro")
TEST_PATH = [('line', 3 * hm.SPAN), ('arc', 220.0, 15.6, 1), ('line', 30.0)]


def check_open_file():
    cur = bpy.data.filepath
    if cur and os.path.normcase(os.path.abspath(cur)) != os.path.normcase(os.path.abspath(BLEND)):
        raise RuntimeError(f"Blender has '{cur}' open; open {BLEND} (or a new file) first. Nothing changed.")


def materials():
    """Flat colours (MAT_COLOURS); materials of MAT_TEX also get their texture + normal map once
    build_metro_texture.py has written them (preview only: Unity builds its own materials)."""
    out = []
    for name in hm.MATS:
        col, rough, metal = hm.MAT_COLOURS[name]
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        mat.use_nodes = True
        nt = mat.node_tree
        for nd in [n for n in nt.nodes if n.type in ('TEX_IMAGE', 'NORMAL_MAP', 'MIX')]:
            nt.nodes.remove(nd)
        b = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
        b.inputs['Base Color'].default_value = (*col, 1)
        b.inputs['Roughness'].default_value = rough
        b.inputs['Metallic'].default_value = metal
        mat.diffuse_color = (*col, 1)
        tex = hm.MAT_TEX.get(name)
        if tex and os.path.exists(os.path.join(hm.TEX_DIR, tex[0])):
            alb, nrm, tint = tex
            ti = nt.nodes.new('ShaderNodeTexImage')
            ti.image = bpy.data.images.load(os.path.join(hm.TEX_DIR, alb), check_existing=True)
            ti.image.reload()
            mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'
            mix.inputs['Factor'].default_value = 1.0
            mix.inputs[7].default_value = (*tint, 1)
            nt.links.new(ti.outputs['Color'], mix.inputs[6])
            nt.links.new(mix.outputs[2], b.inputs['Base Color'])
            if nrm and os.path.exists(os.path.join(hm.TEX_DIR, nrm)):
                tn = nt.nodes.new('ShaderNodeTexImage')
                tn.image = bpy.data.images.load(os.path.join(hm.TEX_DIR, nrm), check_existing=True)
                tn.image.reload()
                tn.image.colorspace_settings.name = 'Non-Color'
                nm = nt.nodes.new('ShaderNodeNormalMap')
                nt.links.new(tn.outputs['Color'], nm.inputs['Color'])
                nt.links.new(nm.outputs['Normal'], b.inputs['Normal'])
        out.append(mat)
    return out


def foliage_materials():
    """Preview stand-ins for the tree materials (Unity remaps M_Foliage / M_FoliageBlob by name)."""
    leaf = bpy.data.materials.get('M_Foliage') or bpy.data.materials.new('M_Foliage')
    leaf.use_nodes = True
    nt = leaf.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    ti = nt.nodes.new('ShaderNodeTexImage')
    ti.image = bpy.data.images.load(os.path.join(ROOT, 'Export', 'Textures', 'Trees', 'T_Foliage.png'), check_existing=True)
    nt.links.new(ti.outputs['Color'], b.inputs['Base Color'])
    nt.links.new(ti.outputs['Alpha'], b.inputs['Alpha'])
    nt.links.new(b.outputs[0], out.inputs['Surface'])
    b.inputs['Roughness'].default_value = 0.7
    try:
        leaf.surface_render_method = 'DITHERED'
    except (AttributeError, TypeError):
        pass
    blob = bpy.data.materials.get('M_FoliageBlob') or bpy.data.materials.new('M_FoliageBlob')
    blob.use_nodes = True
    nt = blob.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    vc = nt.nodes.new('ShaderNodeVertexColor'); vc.layer_name = 'Col'
    nt.links.new(vc.outputs['Color'], b.inputs['Base Color'])
    nt.links.new(b.outputs[0], out.inputs['Surface'])
    b.inputs['Roughness'].default_value = 0.8
    return leaf, blob


def shrub_mesh(name, data, mat):
    """hanoi_metro.shrub() lists -> mesh with UVMap, corner BYTE_COLOR 'Col' (raw bytes), custom normals."""
    verts, faces, uvs, cols, nrms = data
    old = bpy.data.meshes.get(name)
    if old is not None:
        old.name = name + '_old'
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    uvl = me.uv_layers.new(name='UVMap')
    ca = me.color_attributes.new('Col', 'BYTE_COLOR', 'CORNER')
    for i in range(len(me.loops)):          # loops follow the face corner order of from_pydata
        uvl.data[i].uv = uvs[i]
        ca.data[i].color_srgb = cols[i]
    me.polygons.foreach_set('use_smooth', [True] * len(me.polygons))
    me.normals_split_custom_set(nrms)
    me.materials.append(mat)
    me.update()
    return me


def to_mesh(name, bm, mats, sharp_deg=30):
    me = bpy.data.meshes.get(name)
    if me is not None:
        me.name = name + '_old'
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    me.shade_smooth()
    me.set_sharp_from_angle(angle=math.radians(sharp_deg))
    return me


def link(name, me, col, loc=(0, 0, 0), rot_z=0.0, parent=None):
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (0, 0, rot_z)
    ob.parent = parent
    return ob


def flat_mat(name, colr, rough=0.9):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    b.inputs['Base Color'].default_value = (*colr, 1)
    b.inputs['Roughness'].default_value = rough
    m.diffuse_color = (*colr, 1)
    return m


def plane(name, col, x0, y0, x1, y1, z, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata([(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)], [], [(0, 1, 2, 3)])
    me.materials.append(mat)
    return link(name, me, col)


def write_manifest(extra=None):
    os.makedirs(EXPORT_DIR, exist_ok=True)
    profs = hm.deck_profiles()
    data = {
        'units': 'metres. Profiles: (x across, +x = right of travel; y up) relative to deck_top, '
                 'counter-clockwise, closed. Pier parts: origin on the ground at the pier axis, '
                 'Unity axes (x across, y up, z along the line).',
        'rail_top': hm.RAIL_TOP, 'deck_top': round(hm.DECK_TOP, 4), 'girder_bottom': round(hm.GIRDER_BOTTOM, 4),
        'cap_top': round(hm.CAP_TOP, 4), 'cap_bottom': round(hm.CAP_BOTTOM, 4),
        'column_default_top': round(hm.CAP_BOTTOM, 4),
        'track_spacing': hm.TRACK_SPACING, 'gauge': hm.GAUGE, 'span': hm.SPAN,
        'span_range': [24.0, 40.0], 'half_width': hm.HALF_W,
        'post': dict(step=hm.POST_STEP, w=hm.POST['w'], d=hm.POST['d'],
                     x=round(hm.HALF_W - hm.BARRIER['inset'] - hm.BARRIER['t'] - hm.POST['d'] / 2, 4),
                     y0=hm.PARAPET['h'], y1=hm.PARAPET['h'] + hm.BARRIER['h'], mat='M_MetroSteel', lods=[0, 0]),
        'footing': dict(w=hm.FOOT['w'], d=hm.FOOT['d']),
        # lists + flat coordinates: Unity's JsonUtility reads neither dicts nor nested arrays
        # tex / normal: files in Export/Textures/Metro (empty = flat colour); tint multiplies the texture
        'materials': [dict(name=k, color=list(v[0]), roughness=v[1], metallic=v[2],
                           tex=hm.MAT_TEX.get(k, ('', '', None))[0], normal=hm.MAT_TEX.get(k, ('', '', None))[1],
                           tint=list(hm.MAT_TEX[k][2]) if k in hm.MAT_TEX else [1.0, 1.0, 1.0])
                      for k, v in hm.MAT_COLOURS.items()],
        'profiles': [dict(name=k, mat=v['mat'], lods=list(v['lods']), closed=v['closed'], uv=v['uv'],
                          pts=[round(c, 4) for x, z in v['pts'] for c in (x, z)])
                     for k, v in profs.items()],
        # P1: planter profiles are relative to the GROUND (y up from the road), swept between the piers
        'planter': dict(w=hm.PLANTER['w'], t=hm.PLANTER['t'], h=hm.PLANTER['h'], soil=hm.PLANTER['soil'],
                        profiles=[dict(name=k, mat=v['mat'], lods=list(v['lods']), closed=v['closed'], uv=v['uv'],
                                       pts=[round(c, 4) for x, z in v['pts'] for c in (x, z)])
                                  for k, v in hm.planter_profiles().items()]),
        'shrub': dict(variants=hm.SHRUB['variants'], step=hm.SHRUB['step'], row=hm.SHRUB['row'],
                      scale=list(hm.SHRUB['scale']), fbx='SM_MetroShrub.fbx',
                      meshes='SM_MetroShrub_<variant>_LOD<lod>, LOD0 M_Foliage cards, LOD1 M_FoliageBlob'),
    }
    path = os.path.join(EXPORT_DIR, 'metro.json')
    if extra is None and os.path.exists(path):              # keep the export report from --export
        old = json.load(open(path, encoding='utf-8'))
        for key in ('pier', 'shrub_export'):
            if key in old:
                data[key] = old[key]
    if extra:
        data.update(extra)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1)
    return path


# ---------------------------------------------------------------- build
def build():
    check_open_file()
    for ob in list(bpy.data.objects):          # the factory cube sits on the origin
        if ob.name == 'Cube' and ob.type == 'MESH' and len(ob.data.vertices) == 8:
            bpy.data.objects.remove(ob, do_unlink=True)
    mats = materials()
    kit = collection('METRO_KIT')
    test = collection('METRO_TEST')
    clear_collection(kit)
    clear_collection(test)
    report = {'pier': {}, 'deck': {}}

    pier_meshes = {}
    for lod in hm.PIER_LODS:
        root = bpy.data.objects.new(f'Pier_LOD{lod}', None)
        kit.objects.link(root)
        root.location = (-20 - 10 * lod, 0, 0)
        for part, fn in hm.PIER_PARTS.items():
            me = to_mesh(f'SM_MetroPier_{part}_LOD{lod}', fn(lod), mats)
            link(f'Kit_{part}_LOD{lod}', me, kit, parent=root)     # SM_* names are kept for the export
            pier_meshes[(part, lod)] = me
            report['pier'][me.name] = hm.tris(me)

    frames = hm.path_frames(TEST_PATH, step=2.0)
    for lod in (0, 1, 2):
        me = to_mesh(f'Deck_LOD{lod}', hm.deck(lod, frames), mats)
        ob = link(me.name, me, test)
        ob.hide_render = lod != 0
        ob.hide_set(lod != 0)
        report['deck'][f'LOD{lod}_per_30m'] = round(hm.tris(me) / (frames[-1][0] / hm.SPAN))

    # piers every SPAN along the path (LOD0 meshes, linked data)
    s_next = 0.0
    k = 0
    for s, p, t in frames:
        if s + 1e-6 >= s_next:
            yaw = math.atan2(t.y, t.x) - math.pi / 2
            for part in hm.PIER_PARTS:
                link(f'TestPier{k}_{part}', pier_meshes[(part, 0)], test, loc=(p.x, p.y, 0), rot_z=yaw)
            k += 1
            s_next += hm.SPAN

    # P1: shrub kit (variants x LODs at x -40) + planters between the test piers with shrubs
    leaf, blob = foliage_materials()
    shrubs = {}
    for v in range(hm.SHRUB['variants']):
        for lod in (0, 1):
            me = shrub_mesh(f'SM_MetroShrub_{v}_LOD{lod}', hm.shrub(lod, 100 + v), leaf if lod == 0 else blob)
            shrubs[(v, lod)] = me
            link(f'KitShrub_{v}_LOD{lod}', me, kit, loc=(-40 - 2.0 * v, 3.0 * lod, 0))
    report['shrub'] = {f'LOD{l}': hm.tris(shrubs[(0, l)]) for l in (0, 1)}
    import random
    rnd = random.Random(3)
    pprof = hm.planter_profiles()
    half_d = hm.FOOT['d'] / 2
    for k in range(int(frames[-1][0] // hm.SPAN)):
        a, b = k * hm.SPAN + half_d, (k + 1) * hm.SPAN - half_d
        sub = [f for f in frames if a - 1e-6 <= f[0] <= b + 1e-6]
        if len(sub) < 2:
            continue
        m = hm.Mesh()
        for name, prof in pprof.items():
            if name != 'planter_end':
                hm.sweep(m, sub, prof, 0.0)
        me = to_mesh(f'TestPlanter{k}', m.finish(box_uv=False), mats)
        link(me.name, me, test)
        s = a + 0.45
        while s < b - 0.45:
            f = min(sub, key=lambda fr: abs(fr[0] - s))
            r = f[2].cross(Vector((0, 0, 1))).normalized()
            for side in (-1, 1):
                ss = s + (0.45 if side > 0 else 0.0)
                pos = f[1] + f[2] * (ss - f[0]) + r * side * (hm.SHRUB['row'] + rnd.uniform(-0.15, 0.15))
                ob = link(f'TestShrub{k}_{len(test.objects)}', shrubs[(rnd.randrange(hm.SHRUB['variants']), 0)], test,
                          loc=(pos.x, pos.y, hm.PLANTER['soil']), rot_z=rnd.uniform(0, 6.283))
                sc = rnd.uniform(*hm.SHRUB['scale'])
                ob.scale = (sc, sc, sc)
            s += hm.SHRUB['step'] * rnd.uniform(0.85, 1.15)

    # ground: asphalt both ways + a 5 m median strip, massing boxes for scale
    asphalt = flat_mat('M_PrevAsphalt', (0.055, 0.055, 0.055))
    median = flat_mat('M_PrevMedian', (0.07, 0.07, 0.065))
    plane('PrevGround', test, -120, -80, 160, 260, 0.0, asphalt)
    me = to_mesh('PrevMedian', _strip(frames, 2.5, 0.02), [median])
    link('PrevMedian', me, test)
    box_mat = flat_mat('M_PrevBuilding', (0.45, 0.42, 0.38))
    import random
    rnd = random.Random(7)
    for side in (-1, 1):
        y = -60.0
        while y < 220:
            w, d, h = rnd.uniform(4, 6), 12.0, rnd.choice((10, 13, 16, 20, 26))
            x = side * (32 + d / 2)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y + w / 2, h / 2))
            b = bpy.context.active_object
            b.scale = (d, w, h)
            b.name = 'PrevBox'
            b.data.materials.append(box_mat)
            for c in b.users_collection:
                c.objects.unlink(b)
            test.objects.link(b)
            y += w + 0.05
    write_manifest()
    return report


def _strip(frames, half, z):
    import bmesh
    bm = bmesh.new()
    up = Vector((0, 0, 1))
    prev = None
    for s, p, t in frames:
        r = t.cross(up).normalized()
        a = bm.verts.new(p - r * half + up * z)
        b = bm.verts.new(p + r * half + up * z)
        if prev:
            bm.faces.new((prev[0], prev[1], b, a))
        prev = (a, b)
    return bm


# ---------------------------------------------------------------- export
def export():
    check_open_file()
    mats = materials()
    col = collection('METRO_EXPORT')
    clear_collection(col)
    for ob in list(col.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    fbx_dir = os.path.join(EXPORT_DIR, 'FBX')
    os.makedirs(fbx_dir, exist_ok=True)
    root = bpy.data.objects.new('SM_MetroPier', None)
    col.objects.link(root)
    root.location = (-60, 0, 0)
    rep = {'name': 'SM_MetroPier', 'tris': {}, 'parts': list(hm.PIER_PARTS)}
    for lod in hm.PIER_LODS:
        for part, fn in hm.PIER_PARTS.items():
            src = bpy.data.objects.get(f'Kit_{part}_LOD{lod}')
            me = src.data.copy() if src is not None else to_mesh(f'_tmp', fn(lod), mats)
            me.name = f'SM_MetroPier_{part}_LOD{lod}_X'
            ob = bpy.data.objects.new(f'SM_MetroPier_{part}_LOD{lod}', me)
            col.objects.link(ob)
            ob.parent = root
            rep['tris'][ob.name] = hm.tris(me)
    bpy.context.view_layer.update()
    # export_fbx snaps children to the root -> part origins (ground, pier axis) stay as built
    hanoi_common.export_fbx(os.path.join(fbx_dir, 'SM_MetroPier.fbx'), [root], zero_roots=True)
    # P1 shrubs: SM_MetroShrub.fbx = root > SM_MetroShrub_<v>_LOD<l> (meshes looked up by name in Unity)
    leaf, blob = foliage_materials()
    sroot = bpy.data.objects.new('SM_MetroShrub', None)
    col.objects.link(sroot)
    sroot.location = (-70, 0, 0)
    srep = {'name': 'SM_MetroShrub', 'tris': {}}
    for v in range(hm.SHRUB['variants']):
        for lod in (0, 1):
            me = shrub_mesh(f'SM_MetroShrub_{v}_LOD{lod}_X', hm.shrub(lod, 100 + v), leaf if lod == 0 else blob)
            ob = bpy.data.objects.new(f'SM_MetroShrub_{v}_LOD{lod}', me)
            col.objects.link(ob)
            ob.parent = sroot
            srep['tris'][ob.name] = hm.tris(me)
    bpy.context.view_layer.update()
    hanoi_common.export_fbx(os.path.join(fbx_dir, 'SM_MetroShrub.fbx'), [sroot], zero_roots=True)
    path = write_manifest({'pier': rep, 'shrub_export': srep})
    return rep, path


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
        if ob.type in ('CAMERA', 'LIGHT'):
            bpy.data.objects.remove(ob, do_unlink=True)
    try:
        sc.render.engine = 'BLENDER_EEVEE'
    except TypeError:
        sc.render.engine = 'BLENDER_EEVEE_NEXT'
    sc.view_settings.view_transform = 'Standard'
    try:
        sc.eevee.use_shadows = True
    except AttributeError:
        pass
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    sc.collection.objects.link(sun)
    preview_modules.apply_env('sun', sun)
    kit = bpy.data.collections.get('METRO_KIT')
    if kit:
        for ob in kit.all_objects:
            ob.hide_render = True
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    o = PREVIEW_DIR
    render(os.path.join(o, 'drone.png'), new_cam('CamDrone', (-24, -28, 30), (6, 95, 9), 28), (1600, 1000))
    render(os.path.join(o, 'under.png'), new_cam('CamUnder', (-8.5, 52, 1.6), (0, 60, 8.2), 22), (900, 1200))
    render(os.path.join(o, 'side.png'), new_cam('CamSide', (-16, -12, 7.5), (0, 80, 9.5), 32), (1100, 1400))
    render(os.path.join(o, 'deck.png'), new_cam('CamDeck', (2.2, 22, 14.2), (0, 70, 12.2), 26), (1500, 1000))
    sec = new_cam('CamSec', (0, -40, 7.0), (0, 0, 7.0), ortho=15.5)
    sec.data.clip_end = 41.5                    # only the line's first metre: the curve stays out
    render(os.path.join(o, 'section.png'), sec, (1000, 1100))
    render(os.path.join(o, 'curve.png'), new_cam('CamCurve', (60, 40, 45), (40, 140, 6), 30), (1500, 1000))


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--preview" in argv:
        render_preview()
    elif "--export" in argv:
        rep, path = export()
        print('[export]', json.dumps(rep), path)
        save_kit(BLEND)
    else:
        print('[metro]', json.dumps(build()))
        save_kit(BLEND)
