"""MOTO X2 — build the Honda SH LOD0 in Blender from Blender/moto/sh_profile.json (moto_trace.py).

In the open Blender (MCP, port 9876):
    python Blender/scripts/bl.py Blender/scripts/build_moto.py
or without touching the open Blender:
    blender -b Blender/HanoiMoto.blend --python Blender/scripts/build_moto.py -- --build
or in Blender's text editor:
    exec(open(r"D:/Project III/BuildingGenerate/Blender/scripts/build_moto.py", encoding="utf-8").read(),
         {"__name__": "__main__"})

Scene (saved as Blender/HanoiMoto.blend):
  MOTO_REF    the photo as an image empty on the bike's right side (view from -X: Ctrl+Numpad3)
  MOTO_TRACE  one poly curve per traced part (TR_<PART>_<i>), drawn on that photo.
              Hand edits: move the curve points, set the curve's custom property hand_edited = True,
              re-run -> the builder reads the edited points instead of the json.
  MOTO_EXPORT (X3, -- --export) SM_Moto_SH > SM_Moto_SH_LOD0/1/2 (parked, merged) and
              SM_Moto_SH_Rig > Body_LODn, Steer > (Steer_LODn, WheelF > WheelF_LODn), WheelR > ...
              -> Export/Vehicles/FBX/SM_Moto_SH(.fbx|_Rig.fbx) + Export/Vehicles/vehicles.json
  MOTO_SH     root empty MOTO_SH (origin = ground, wheelbase midpoint) with
                SH_Body    every fixed part (one mesh)
                SH_Steer   front fender, handlebar cover, grips, mirrors, fork; origin = steering pivot
                SH_WheelF  / SH_WheelR   origin = axle
                anchors    SEAT_ANCHOR, HAND_L/R, FOOT_L/R (future riders / VAT)
Then a copy is rendered in the background (blender -b ... -- --preview) and composed by
moto_sheet.py into Blender/previews/moto_x2_sheet.png.
"""
import importlib
import json
import math
import os
import subprocess
import sys
import tempfile

import bpy
from mathutils import Matrix, Vector

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_common
import hanoi_moto
importlib.reload(hanoi_common)
importlib.reload(hanoi_moto)
from hanoi_common import collection, clear_collection, empty, save_kit
from hanoi_moto import (PAINT_COLOURS, PART_STYLE, REGIONS, SLOTS, TOP_VIEW_PARTS, WHEEL, Parts, box,
                        capsule, cylinder, ellipsoid, extrude_profile, front_carve, simplify_poly,
                        to_xyz, top_view_limit, tris, wheel)

MOTO_DIR = os.path.join(ROOT, "Blender", "moto")
PROFILE = os.path.join(MOTO_DIR, "sh_profile.json")
REF_IMG = os.path.join(ROOT, "Ref", "xemay.png")
BLEND = os.path.join(ROOT, "Blender", "HanoiMoto.blend")
PREVIEW_DIR = os.path.join(ROOT, "Blender", "previews")
BLENDER_EXE = r"D:\Blender Foundation\Blender 5.2\blender.exe"
PYTHON_EXE = "python"
PREVIEW_COPY = os.path.join(tempfile.gettempdir(), "hanoi_moto_preview.blend")
REF_X = -0.9            # photo plane (right side of the bike), trace curves just in front of it
TRACE_X = -0.85
SH_GREEN = 0            # PAINT_COLOURS index used for the SH itself


def srgb_to_lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def paint_linear(i):
    return tuple(srgb_to_lin(c) for c in PAINT_COLOURS[i]) + (1.0,)


# ---------------------------------------------------------------- material
def atlas_images():
    """T_MotoAtlas (albedo, sRGB) + T_MotoAtlasData (roughness / metallic / emission), from
    build_moto_atlas.py."""
    out = []
    for name, data in (('T_MotoAtlas', False), ('T_MotoAtlasData', True)):
        path = os.path.join(MOTO_DIR, f"{name}.png")
        img = bpy.data.images.get(f"{name}.png") or bpy.data.images.load(path)
        img.reload()
        img.colorspace_settings.name = 'Non-Color' if data else 'sRGB'
        out.append(img)
    return out


def moto_material():
    """M_HanoiMoto (Blender preview; Unity maps it to Hanoi/Vehicle with the same atlas)."""
    mat = bpy.data.materials.get('M_HanoiMoto') or bpy.data.materials.new('M_HanoiMoto')
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    alb_img, dat_img = atlas_images()
    out = N('ShaderNodeOutputMaterial'); out.location = (600, 0)
    bsdf = N('ShaderNodeBsdfPrincipled'); bsdf.location = (300, 0)
    uv = N('ShaderNodeUVMap'); uv.uv_map = 'UVMap'; uv.location = (-1100, 0)
    texs = []
    for i, img in enumerate((alb_img, dat_img)):
        t = N('ShaderNodeTexImage'); t.image = img; t.interpolation = 'Linear'
        t.location = (-800, -300 * i)
        L(uv.outputs['UV'], t.inputs['Vector'])
        texs.append(t)
    sep = N('ShaderNodeSeparateXYZ'); sep.location = (-800, 300)
    L(uv.outputs['UV'], sep.inputs[0])
    # paint mask = the PAINT cell of the palette strip
    pu0, pv0, pu1, _ = REGIONS['palette']
    in_u = N('ShaderNodeMath'); in_u.operation = 'LESS_THAN'; in_u.location = (-650, 380)
    in_u.inputs[1].default_value = pu0 + (pu1 - pu0) / len(SLOTS)
    L(sep.outputs['X'], in_u.inputs[0])
    in_v = N('ShaderNodeMath'); in_v.operation = 'GREATER_THAN'; in_v.location = (-650, 220)
    in_v.inputs[1].default_value = pv0
    L(sep.outputs['Y'], in_v.inputs[0])
    is_paint = N('ShaderNodeMath'); is_paint.operation = 'MULTIPLY'; is_paint.location = (-500, 300)
    L(in_u.outputs[0], is_paint.inputs[0]); L(in_v.outputs[0], is_paint.inputs[1])
    attr = N('ShaderNodeAttribute'); attr.attribute_type = 'OBJECT'; attr.attribute_name = 'paint_color'
    attr.location = (-550, 150)
    mix = N('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.location = (-250, 150)
    L(is_paint.outputs[0], mix.inputs['Factor'])
    L(texs[0].outputs['Color'], mix.inputs[6])
    L(attr.outputs['Color'], mix.inputs[7])
    L(mix.outputs[2], bsdf.inputs['Base Color'])
    sc = N('ShaderNodeSeparateColor'); sc.location = (-450, -300)
    L(texs[1].outputs['Color'], sc.inputs['Color'])
    L(sc.outputs['Red'], bsdf.inputs['Roughness'])
    L(sc.outputs['Green'], bsdf.inputs['Metallic'])
    L(texs[0].outputs['Color'], bsdf.inputs['Emission Color'])
    L(sc.outputs['Blue'], bsdf.inputs['Emission Strength'])
    # alpha clip (wheel tile: transparent between the spokes)
    clip = N('ShaderNodeMath'); clip.operation = 'GREATER_THAN'; clip.location = (0, -500)
    clip.inputs[1].default_value = 0.5
    L(texs[0].outputs['Alpha'], clip.inputs[0])
    L(clip.outputs[0], bsdf.inputs['Alpha'])
    try:
        mat.surface_render_method = 'DITHERED'
    except (AttributeError, TypeError):
        pass
    L(bsdf.outputs[0], out.inputs['Surface'])
    mat.diffuse_color = (0.3, 0.4, 0.32, 1)
    return mat


# ---------------------------------------------------------------- reference photo + trace curves
def px_to_uz(prof, x, y):
    s = prof['metres_per_px']
    ox, oy = prof['px_origin']
    return ((x - ox) * s, (oy - y) * s)


def ref_photo(prof, col):
    ob = bpy.data.objects.get('REF_xemay')
    if ob is None:
        ob = bpy.data.objects.new('REF_xemay', None)
        col.objects.link(ob)
    img = bpy.data.images.get('xemay.png') or bpy.data.images.load(REF_IMG)
    ob.empty_display_type = 'IMAGE'
    ob.data = img
    w, h = img.size
    s = prof['metres_per_px']
    ob.empty_display_size = max(w, h) * s
    ob.use_empty_image_alpha = True
    ob.color[3] = 0.6
    uc, zc = px_to_uz(prof, w / 2, h / 2)
    # image x -> bike forward (-Y), image y -> up (+Z), facing -X
    rot = Matrix(((0, 0, -1), (-1, 0, 0), (0, 1, 0)))
    ob.matrix_world = Matrix.Translation((REF_X, -uc, zc)) @ rot.to_4x4()
    ob.hide_select = True
    return ob


def trace_polys(prof, col):
    """{part: [poly (u, z)]}: from hand-edited curves when flagged, else from the json
    (and the curves are (re)drawn from it)."""
    out = {}
    for part, d in prof['parts'].items():
        polys = []
        for i, poly in enumerate(d['polys']):
            name = f"TR_{part}_{i}"
            ob = bpy.data.objects.get(name)
            if ob is not None and ob.get('hand_edited'):
                sp = ob.data.splines[0]
                mw = ob.matrix_world
                polys.append([(-(mw @ p.co.xyz).y, (mw @ p.co.xyz).z) for p in sp.points])
                continue
            if ob is not None:
                cu = ob.data
                bpy.data.objects.remove(ob, do_unlink=True)
                bpy.data.curves.remove(cu)
            cu = bpy.data.curves.new(name, 'CURVE')
            cu.dimensions = '3D'
            sp = cu.splines.new('POLY')
            sp.points.add(len(poly) - 1)
            for p, (u, z) in zip(sp.points, poly):
                p.co = (TRACE_X, -u, z, 1)
            sp.use_cyclic_u = True
            ob = bpy.data.objects.new(name, cu)
            ob['hand_edited'] = False
            col.objects.link(ob)
            polys.append(poly)
        out[part] = polys
    return out


# ---------------------------------------------------------------- build
# Level of detail recipes. LOD0 = close-up / action scenes, LOD1 ~ 15-40 m, LOD2 = far.
LODS = {
    0: dict(simplify=0.0,   rings=None, grid=0.055, pillow=True,  wheel_segs=20, simple_wheel=False,
            cyl=8, details=True,  carve=True),
    1: dict(simplify=0.03,  rings=1,    grid=None,  pillow=False, wheel_segs=10, simple_wheel=False,
            cyl=5, details=False, carve=True),
    2: dict(simplify=0.08,  rings=0,    grid=None,  pillow=False, wheel_segs=6,  simple_wheel=True,
            cyl=4, details=False, carve=False),
}
LOD2_SKIP = {'NECK', 'RACK', 'UNDER_REAR'}


def assemble(prof, polys, lod=0):
    """All pieces of one LOD. Returns ({group: (Parts, pivot)}, steering axis, tris per part).
    Body / Steer are in world coords, the wheels in their own axle space."""
    L = LODS[lod]
    P = prof['points']
    cf, cr = prof['wheels']['front']['centre'], prof['wheels']['rear']['centre']
    cyl = L['cyl']
    body, steer = Parts(), Parts()
    report_parts = {}
    steer_parts = set(prof['steer_parts'])
    nose = max(u for part in TOP_VIEW_PARTS for poly in polys[part] for u, _ in poly)
    top = top_view_limit(P['grip'][0], nose)
    z_cut = min(z for poly in polys['HEADLIGHT'] for _, z in poly)
    for part, plist in polys.items():
        if lod == 2 and part in LOD2_SKIP:
            continue
        d = prof['parts'][part]
        st = PART_STYLE.get(part, {})
        dst = steer if part in steer_parts else body
        carve = None
        if 'carve' in st and L['carve']:     # hollow the shield below the headlight (front view)
            carve = front_carve(plist, z_cut, **st['carve'])
        r, rings = st.get('bevel', (0.02, 1))
        rings = rings if L['rings'] is None else min(rings, L['rings'])
        for poly in plist:
            bm_ = extrude_profile(simplify_poly(poly, L['simplify']), st.get('width', d['width']),
                                  d['offset'], (r, rings), st.get('t'), st.get('s'),
                                  st.get('pillow') if L['pillow'] else None,
                                  top if part in TOP_VIEW_PARTS else None, grid=L['grid'], carve=carve)
            report_parts[part] = report_parts.get(part, 0) + len(bm_.faces)
            dst.add(bm_, d['slot'])

    # CVT case on the left (the photo only shows the right side): axle -> engine
    if lod < 2:
        cvt = capsule((cr[0], cr[1]), 0.07, (cr[0] + 0.47, cr[1] + 0.04), 0.115, n=10 if lod == 0 else 5)
        st = PART_STYLE['CVT_CASE']
        body.add(extrude_profile(cvt, 0.09, 0.125, st['bevel'] if lod == 0 else (st['bevel'][0], 1),
                                 grid=L['grid']), 'PLASTIC')
    # rear axle + twin rear shocks, each tied to the frame (top pin) and to the axle (lower arm)
    axle_r = to_xyz(*cr)
    if lod < 2:
        body.add(cylinder(axle_r + Vector((-0.14, 0, 0)), axle_r + Vector((0.14, 0, 0)), 0.014,
                          segs=cyl, caps=lod == 0), 'METAL')
    for side in (-1, 1):
        x = side * 0.11
        top_p, bot = to_xyz(*P['shock_top'], x), to_xyz(*P['shock_bottom'], x)
        top_p = top_p + (top_p - bot).normalized() * 0.03          # reach into the body
        if lod < 2:
            body.add(cylinder(top_p + Vector((side * 0.025, 0, 0)), top_p - Vector((side * 0.10, 0, 0)),
                              0.018, segs=cyl, caps=lod == 0), 'PLASTIC')   # top pin into the frame
            body.add(cylinder(bot, axle_r + Vector((x, 0, 0)), 0.022, segs=cyl, caps=lod == 0),
                     'PLASTIC')                                             # lower arm to the axle
        if lod == 0:
            body.add(cylinder(bot, top_p, 0.011, segs=max(4, cyl - 2)), 'METAL')
        a, b = (0.15, 0.85) if lod < 2 else (0.0, 1.0)
        body.add(cylinder(bot.lerp(top_p, a), bot.lerp(top_p, b), 0.027, segs=cyl,
                          uv_region='spring'), 'RED')
    # number plate (VN 19 x 14 cm), facing back
    pu, pz = px_to_uz(prof, 78, 418)
    body.add(box(to_xyz(pu - 0.01, pz), (0.19, 0.008, 0.14)), 'METAL')

    # steering: fork along axle -> fork_top, grips, mirrors
    axle = to_xyz(*cf)
    ftop = to_xyz(*P['fork_top'])
    axis = (ftop - axle).normalized()
    gu, gz = P['grip']
    hu = (P['mirror_R_head'][0] + P['mirror_L_head'][0]) / 2
    hz = (P['mirror_R_head'][1] + P['mirror_L_head'][1]) / 2
    for side in (-1, 1):
        off = Vector((side * 0.085, 0, 0))
        mid = axle.lerp(ftop, 0.55)
        caps = lod == 0
        if lod == 2:                                   # one tube per fork leg
            steer.add(cylinder(axle + off, ftop + off, 0.022, segs=cyl, caps=False), 'PLASTIC')
        else:
            steer.add(cylinder(axle + off, mid + off, 0.025, segs=cyl, caps=caps), 'PLASTIC')
            steer.add(cylinder(mid + off, ftop + off + axis * 0.08, 0.019, segs=cyl, caps=caps), 'METAL')
        # bar starts inside the handlebar cover so it never floats beside it
        steer.add(cylinder(to_xyz(gu, gz, side * 0.06), to_xyz(gu - 0.01, gz - 0.005, side * 0.335),
                           0.018, segs=cyl, caps=lod < 2), 'PLASTIC')
        if L['details']:
            steer.add(cylinder(to_xyz(gu - 0.01, gz - 0.005, side * 0.335),
                               to_xyz(gu - 0.01, gz - 0.005, side * 0.35), 0.02, segs=cyl), 'METAL')
        root = to_xyz(P['mirror_root'][0], P['mirror_root'][1] - 0.03, side * 0.11)   # inside the cover
        head = to_xyz(hu, hz - 0.03, side * 0.29)
        # mirror head: horizontal oval (Ref/xemayfront.png), stalk meets its inner lower edge
        steer.add(cylinder(root, head + Vector((-side * 0.045, 0, -0.025)), 0.008,
                           segs=max(4, cyl - 2), caps=False), 'PLASTIC')
        if lod == 2:
            steer.add(box(head, (0.13, 0.03, 0.075)), 'PLASTIC')
        else:
            steer.add(ellipsoid(head, (0.135, 0.035, 0.08), segs=8 if lod == 0 else 6,
                                rings=5 if lod == 0 else 3), 'PLASTIC')

    groups = {'Body': (body, Vector()), 'Steer': (steer, ftop)}
    for key, name, c in (('front', 'WheelF', cf), ('rear', 'WheelR', cr)):
        w = WHEEL[key]
        wp = Parts()
        for bm_, slot in wheel(prof['wheels'][key]['radius'], w['section'], w['width'],
                               segs=L['wheel_segs'], simple=L['simple_wheel']):
            wp.add(bm_, slot)
        groups[name] = (wp, to_xyz(*c))
    return groups, axis, report_parts


def anchors(prof):
    P = prof['points']
    return {name: to_xyz(u, z, x) for name, (u, z), x in (
        ('SEAT_ANCHOR', P['seat_top'], 0.0), ('HAND_L', P['grip'], 0.32), ('HAND_R', P['grip'], -0.32),
        ('FOOT_L', P['foot'], 0.12), ('FOOT_R', P['foot'], -0.12))}


def group_mesh(name, parts, pivot, group, mat, local=True):
    """Mesh of one group: local=True -> pivot-relative (rig), else world space (merging)."""
    if group.startswith('Wheel'):
        if not local:
            parts.bm.transform(Matrix.Translation(pivot))
    elif local:
        parts.bm.transform(Matrix.Translation(-pivot))
    return parts.to_mesh(name, mat)


def merged_mesh(name, groups, mat):
    """One mesh for a parked bike: every group in world space, joined."""
    import bmesh
    bm = bmesh.new()
    for g, (parts, pivot) in groups.items():
        me = group_mesh('_tmp', parts, pivot, g, mat, local=False)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    if 'slot' in me.attributes:
        me.attributes.remove(me.attributes['slot'])
    return me


def check_open_file():
    cur = bpy.data.filepath
    if cur and os.path.normcase(os.path.abspath(cur)) != os.path.normcase(os.path.abspath(BLEND)):
        raise RuntimeError(f"Blender has '{cur}' open; open {BLEND} (or a new file) first. Nothing changed.")


def build():
    """LOD0 working model in MOTO_SH (separate Body / Steer / wheels + anchors)."""
    check_open_file()
    prof = json.load(open(PROFILE, encoding='utf-8'))
    for ob in list(bpy.data.objects):          # the factory cube sits on the origin
        if ob.name == 'Cube' and ob.type == 'MESH' and len(ob.data.vertices) == 8:
            bpy.data.objects.remove(ob, do_unlink=True)
    ref_col = collection('MOTO_REF')
    trace_col = collection('MOTO_TRACE')
    sh_col = collection('MOTO_SH')
    clear_collection(sh_col)
    ref_photo(prof, ref_col)
    polys = trace_polys(prof, trace_col)
    mat = moto_material()
    groups, axis, report_parts = assemble(prof, polys, 0)

    report = {}
    root = empty('MOTO_SH', sh_col)
    root.empty_display_size = 0.3
    for g, (parts, pivot) in groups.items():
        name = 'SH_' + g
        me = group_mesh(name, parts, pivot, g, mat)
        ob = bpy.data.objects.new(name, me)
        sh_col.objects.link(ob)
        ob.parent = root
        ob.location = pivot
        ob['paint_color'] = paint_linear(SH_GREEN)
        report[name] = tris(me)
    bpy.data.objects['SH_Steer']['steer_axis'] = tuple(round(v, 4) for v in axis)
    for name, p in anchors(prof).items():
        a = empty('SH_' + name, sh_col, p)
        a.empty_display_size = 0.06
        a.parent = root
    report['total'] = sum(v for k, v in report.items())
    report['parts'] = report_parts
    bpy.context.view_layer.update()
    report['size_xyz'] = [round(v, 3) for v in _dims(sh_col)]
    return report


def _dims(col):
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    for ob in col.objects:
        if ob.type != 'MESH':
            continue
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
    return hi - lo


# ---------------------------------------------------------------- preview (background copy)
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
    if abs(cam.location.x - target[0]) < 1e-6 and abs(cam.location.y - target[1]) < 0.2:
        cam.rotation_euler = (0, 0, 0)             # straight down, bike front (-Y) at the bottom
    bpy.context.view_layer.update()
    return cam


def render(path, cam, res, transparent=False, crop_to=None):
    sc = bpy.context.scene
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = transparent
    sc.render.use_border = sc.render.use_crop_to_border = False
    if crop_to is not None:
        from bpy_extras.object_utils import world_to_camera_view
        pts = [world_to_camera_view(sc, cam, p) for p in crop_to]
        m = 0.01
        sc.render.border_min_x = max(0, min(p.x for p in pts) - m)
        sc.render.border_max_x = min(1, max(p.x for p in pts) + m)
        sc.render.border_min_y = max(0, min(p.y for p in pts) - m)
        sc.render.border_max_y = min(1, max(p.y for p in pts) + m)
        sc.render.use_border = sc.render.use_crop_to_border = True
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print('[preview]', os.path.basename(path))


def render_preview():
    import preview_modules
    importlib.reload(preview_modules)
    prof = json.load(open(PROFILE, encoding='utf-8'))
    sc = bpy.context.scene
    for c in ('MOTO_REF', 'MOTO_TRACE', 'MOTO_EXPORT'):
        if c in bpy.data.collections:
            bpy.data.collections[c].hide_render = True
    for ob in list(bpy.data.objects):
        if ob.type in ('CAMERA', 'LIGHT'):
            bpy.data.objects.remove(ob, do_unlink=True)
    sc.render.engine = 'BLENDER_EEVEE'
    sc.view_settings.view_transform = 'Standard'
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    sc.collection.objects.link(sun)
    preview_modules.apply_env('sun', sun)
    out = os.path.join(PREVIEW_DIR, 'moto_x2')
    os.makedirs(out, exist_ok=True)
    root = bpy.data.objects['MOTO_SH']
    sh_obs = [o for o in root.children if o.type == 'MESH']

    # 1) side, orthographic, pixel-aligned with the photo (transparent, no ground)
    w, h = 971, 767
    s = prof['metres_per_px']
    uc, zc = px_to_uz(prof, w / 2, h / 2)
    cam = new_cam('CamSide', (-10, -uc, zc), (0, -uc, zc), ortho=w * s)
    render(os.path.join(out, 'side.png'), cam, (w, h), transparent=True)

    # ground for the rest
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
    g = bpy.context.active_object
    gm = bpy.data.materials.new('M_Ground'); gm.use_nodes = True
    next(n for n in gm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Base Color'].default_value = (0.32, 0.32, 0.31, 1)
    g.data.materials.append(gm)

    # 2) close 3/4 views
    tgt = (0, 0, 0.55)
    render(os.path.join(out, 'q34_front.png'), new_cam('CamQF', (-2.4, -3.0, 1.35), tgt, 45), (1400, 1050))
    render(os.path.join(out, 'q34_rear.png'), new_cam('CamQR', (2.5, 2.7, 1.45), tgt, 45), (1400, 1050))
    render(os.path.join(out, 'front.png'), new_cam('CamF', (0, -4.5, 0.9), (0, 0, 0.62), 50), (900, 1050))
    render(os.path.join(out, 'close_front.png'), new_cam('CamCF', (-1.25, -1.0, 1.0), (0, -0.45, 0.7), 35),
           (1200, 1200))
    render(os.path.join(out, 'close_rear.png'), new_cam('CamCR', (-1.3, 0.6, 1.05), (0, 0.25, 0.6), 35),
           (1200, 1200))
    render(os.path.join(out, 'front_ortho.png'), new_cam('CamFO', (0, -8, 0.64), (0, 0, 0.64), ortho=1.42),
           (520, 740), transparent=True)
    render(os.path.join(out, 'top.png'), new_cam('CamTop', (0, -0.05, 6), (0, -0.05, 0), ortho=2.3),
           (600, 1050))

    # 3) far: what a 1920x1080 / 60° camera at eye height sees, cropped around the bike
    corners = [o.matrix_world @ Vector(c) for o in sh_obs for c in o.bound_box]
    for dist in (20, 50):
        d = Vector((-0.6, -0.8, 0)).normalized() * dist
        cam = new_cam(f'CamFar{dist}', (d.x, d.y, 1.7), tgt, 31.2)
        render(os.path.join(out, f'far{dist}.png'), cam, (1920, 1080), crop_to=corners)

    # 4) a row of 10 parked bikes in different colours along a kerb
    import random
    rnd = random.Random(3)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0.6, 0.1))
    walk = bpy.context.active_object
    walk.scale = (14, 4.2, 0.2)
    wm = bpy.data.materials.new('M_Walk'); wm.use_nodes = True
    next(n for n in wm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Base Color'].default_value = (0.5, 0.47, 0.42, 1)
    walk.data.materials.append(wm)
    for i in range(10):
        holder = bpy.data.objects.new(f'Row{i}', None)
        sc.collection.objects.link(holder)
        holder.location = (-3.6 + i * 0.8, 0, 0.2)
        holder.rotation_euler = (0, 0, math.radians(180 + rnd.uniform(-10, 10)))
        for o in sh_obs:
            c = o.copy()
            sc.collection.objects.link(c)
            c.parent = holder
            c.matrix_parent_inverse = Matrix()
            c.location = o.location
            c['paint_color'] = paint_linear(i % len(PAINT_COLOURS))
    render(os.path.join(out, 'row.png'), new_cam('CamRow', (-3.5, -6.5, 2.4), (0, 0.2, 0.5), 35),
           (1800, 900))


def preview_in_background():
    bpy.ops.wm.save_as_mainfile(filepath=PREVIEW_COPY, copy=True)
    cmd = [BLENDER_EXE, "-b", PREVIEW_COPY, "--python", os.path.join(SCRIPTS, "build_moto.py"),
           "--", "--preview"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    print("\n".join(l for l in r.stdout.splitlines()
                    if l.startswith(("[preview]", "Error", "Traceback"))) or r.stdout[-2000:])
    if r.returncode != 0:
        print(r.stderr[-2000:])
    r = subprocess.run([PYTHON_EXE, os.path.join(SCRIPTS, "moto_sheet.py")], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-1500:], r.stderr[-1500:])


# ---------------------------------------------------------------- X3: LODs + FBX export
EXPORT_DIR = os.path.join(ROOT, "Export", "Vehicles")
FBX_OUT = os.path.join(EXPORT_DIR, "FBX")
STATIC_X, RIG_X = 2.0, 5.0          # where the export roots sit in the .blend (snapped to 0 on export)


def to_unity(v):
    """Blender (x, y, z) -> Unity after FBX (-Z forward, Y up) import: (-x, z, -y)."""
    return [round(-v[0], 4), round(v[2], 4), round(-v[1], 4)]


def export_selection(path, roots):
    """FBX of roots + all descendants, roots moved to the origin for the export."""
    saved = {r.name: tuple(r.location) for r in roots}
    bpy.ops.object.select_all(action='DESELECT')
    for r in roots:
        r.location = (0, 0, 0)
        for o in [r] + list(r.children_recursive):
            o.hide_set(False)
            o.select_set(True)
    bpy.context.view_layer.update()
    try:
        bpy.ops.export_scene.fbx(
            filepath=path, use_selection=True, object_types={'EMPTY', 'MESH'},
            apply_scale_options='FBX_SCALE_ALL', axis_forward='-Z', axis_up='Y',
            bake_space_transform=True, mesh_smooth_type='FACE', use_mesh_modifiers=True,
            add_leaf_bones=False, bake_anim=False, path_mode='AUTO', colors_type='SRGB')
    finally:
        for r in roots:
            r.location = saved[r.name]
    return path


def export_lods():
    """MOTO_EXPORT: SM_Moto_SH (parked, one merged mesh per LOD) and SM_Moto_SH_Rig (body,
    steering, wheels separate, for riding), exported to Export/Vehicles/FBX + vehicles.json."""
    check_open_file()
    prof = json.load(open(PROFILE, encoding='utf-8'))
    polys = trace_polys(prof, collection('MOTO_TRACE'))
    mat = moto_material()
    col = collection('MOTO_EXPORT')
    clear_collection(col)
    for ob in list(col.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    paint = paint_linear(SH_GREEN)

    static = empty('SM_Moto_SH', col, (STATIC_X, 0, 0))
    rig = empty('SM_Moto_SH_Rig', col, (RIG_X, 0, 0))
    report = {'name': 'SM_Moto_SH', 'tris': {}, 'rig_tris': {}}
    pivots = {}
    for lod in LODS:
        groups, axis, _ = assemble(prof, polys, lod)
        me = merged_mesh(f'SM_Moto_SH_LOD{lod}', groups, mat)
        ob = bpy.data.objects.new(me.name, me)
        col.objects.link(ob)
        ob.parent = static
        ob.location = (lod * 1.0, 0, 0)           # side by side in the .blend only
        ob['paint_color'] = paint
        report['tris'][f'LOD{lod}'] = tris(me)

        groups, axis, _ = assemble(prof, polys, lod)
        if lod == 0:
            pivots = {g: p.copy() for g, (_, p) in groups.items()}
            for name, p in anchors(prof).items():
                a = empty(name, col)
                a.empty_display_size = 0.06
                a.parent = rig
                a.location = p
        # flat rig (one level: nested empties break the FBX axis bake): every mesh is a direct
        # child of the root with its origin on its pivot; Unity re-parents WheelF under Steer.
        n = 0
        for g, (parts, pivot) in groups.items():
            gm = group_mesh(f'{g}_LOD{lod}', parts, pivot, g, mat)
            if 'slot' in gm.attributes:
                gm.attributes.remove(gm.attributes['slot'])
            o = bpy.data.objects.new(gm.name, gm)
            col.objects.link(o)
            o.parent = rig
            o.location = pivot
            o['paint_color'] = paint
            n += tris(gm)
        report['rig_tris'][f'LOD{lod}'] = n
    bpy.context.view_layer.update()

    os.makedirs(FBX_OUT, exist_ok=True)
    import shutil                                       # atlas textures travel with the FBX
    tex_out = os.path.join(EXPORT_DIR, 'Textures')
    os.makedirs(tex_out, exist_ok=True)
    for name in ('T_MotoAtlas.png', 'T_MotoAtlasData.png'):
        shutil.copy2(os.path.join(MOTO_DIR, name), os.path.join(tex_out, name))
    hanoi_common.export_fbx(os.path.join(FBX_OUT, 'SM_Moto_SH.fbx'), [static], zero_roots=True)
    export_selection(os.path.join(FBX_OUT, 'SM_Moto_SH_Rig.fbx'), [rig])

    wf, wr = prof['wheels']['front'], prof['wheels']['rear']
    lo, hi = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    lod0 = bpy.data.objects['SM_Moto_SH_LOD0']
    for c in lod0.bound_box:
        p = Vector(c) + Vector((0, 0, 0))
        lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
    report.update({
        'units': 'metres, Unity axes (x right, y up, z forward); origin = ground, wheelbase midpoint',
        'size': to_unity(hi - lo) and [round(hi.x - lo.x, 3), round(hi.z - lo.z, 3), round(hi.y - lo.y, 3)],
        'material': 'M_HanoiMoto: atlas Blender/moto/T_MotoAtlas.png + T_MotoAtlasData.png; '
                    'paint tint where UV is in the PAINT cell (u < 0.125, v > 0.875); '
                    'alpha clip 0.5 (atlas alpha: see-through between the wheel spokes)',
        'paint_colours_srgb': PAINT_COLOURS,
        'rig': {
            'steer_pivot': to_unity(pivots['Steer']),
            'steer_axis': to_unity(axis),
            'wheel_front': {'pivot': to_unity(pivots['WheelF']), 'radius': wf['radius'],
                            'spin_axis': [1, 0, 0]},
            'wheel_rear': {'pivot': to_unity(pivots['WheelR']), 'radius': wr['radius'],
                           'spin_axis': [1, 0, 0]},
            'hierarchy': 'FBX is flat: SM_Moto_SH_Rig > Body_LODn, Steer_LODn, WheelF_LODn, WheelR_LODn '
                         '(origins on their pivots), anchors. In Unity: Steer pivot holds Steer_LODn + '
                         'WheelF pivot (WheelF_LODn); rotate Steer about steer_axis, wheels about local X.',
        },
        'anchors': {k: to_unity(v) for k, v in anchors(prof).items()},
    })
    with open(os.path.join(EXPORT_DIR, 'vehicles.json'), 'w', encoding='utf-8') as f:
        json.dump({'vehicles': [report]}, f, indent=1)
    return report


def verify_fbx():
    """Re-import both FBX files in an empty scene and print names / positions / tris."""
    for f in ('SM_Moto_SH.fbx', 'SM_Moto_SH_Rig.fbx'):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=os.path.join(FBX_OUT, f))
        new = [o for o in bpy.data.objects if o not in before]
        for o in sorted(new, key=lambda o: o.name):
            info = f"{o.type} parent={o.parent.name if o.parent else '-'} " \
                   f"world={tuple(round(v, 3) for v in o.matrix_world.translation)}"
            if o.type == 'MESH':
                info += f" tris={tris(o.data)} uv={[u.name for u in o.data.uv_layers]}"
            print(f"[verify] {f}: {o.name} {info}")
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)


def render_lods():
    """Previews of the three LODs: close 3/4 each, and LOD1 at 20 m / LOD2 at 50 m."""
    import preview_modules
    importlib.reload(preview_modules)
    sc = bpy.context.scene
    for c in bpy.data.collections:
        c.hide_render = c.name != 'MOTO_EXPORT'
    for ob in list(bpy.data.objects):
        if ob.type in ('CAMERA', 'LIGHT'):
            bpy.data.objects.remove(ob, do_unlink=True)
    sc.render.engine = 'BLENDER_EEVEE'
    sc.view_settings.view_transform = 'Standard'
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    sc.collection.objects.link(sun)
    preview_modules.apply_env('sun', sun)
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, 0))
    g = bpy.context.active_object
    for c in list(g.users_collection):                 # keep the ground out of hidden collections
        c.objects.unlink(g)
    sc.collection.objects.link(g)
    gm = bpy.data.materials.new('M_Ground'); gm.use_nodes = True
    next(n for n in gm.node_tree.nodes if n.type == 'BSDF_PRINCIPLED').inputs['Base Color'].default_value = (0.32, 0.32, 0.31, 1)
    g.data.materials.append(gm)
    rig = bpy.data.objects['SM_Moto_SH_Rig']
    for o in [rig] + list(rig.children_recursive):
        o.hide_render = True
    static = bpy.data.objects['SM_Moto_SH']
    static.location = (0, 0, 0)
    lods = [bpy.data.objects[f'SM_Moto_SH_LOD{k}'] for k in range(3)]
    out = os.path.join(PREVIEW_DIR, 'moto_x3')
    os.makedirs(out, exist_ok=True)
    tgt = (0, 0, 0.55)
    for k, ob in enumerate(lods):
        for o in lods:
            o.hide_render = o is not ob
            o.location = (0, 0, 0)
        bpy.context.view_layer.update()
        render(os.path.join(out, f'lod{k}_q34.png'), new_cam(f'CamQ{k}', (-2.4, -3.0, 1.35), tgt, 45),
               (900, 700))
        corners = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        for dist in (8, 20, 50):
            d = Vector((-0.6, -0.8, 0)).normalized() * dist
            render(os.path.join(out, f'lod{k}_far{dist}.png'), new_cam(f'CamF{k}{dist}', (d.x, d.y, 1.7), tgt, 31.2),
                   (1920, 1080), crop_to=corners)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--preview" in argv:
        render_preview()
    elif "--build" in argv:                    # background: blender -b HanoiMoto.blend --python ... -- --build
        print('[moto]', json.dumps(build()))
        save_kit(BLEND)
    elif "--export" in argv:                   # X3: blender -b HanoiMoto.blend --python ... -- --export
        print('[moto]', json.dumps(build()))
        print('[export]', json.dumps(export_lods()))
        save_kit(BLEND)
    elif "--verify" in argv:                   # blender -b --factory-startup --python ... -- --verify
        verify_fbx()
    elif "--preview-lods" in argv:
        render_lods()
    else:
        REPORT = build()
        print('[moto]', json.dumps(REPORT))
        save_kit(BLEND)
        if not globals().get("NO_PREVIEW"):
            preview_in_background()
