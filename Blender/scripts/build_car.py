"""CAR C1 — VinFast LUX A2.0: import the Sketchfab glTF, drop the interior, group by slot, split the wheels.

    blender -b --factory-startup --python Blender/scripts/build_car.py -- --inspect   # per-material report only
    blender -b --factory-startup --python Blender/scripts/build_car.py -- --clean     # -> Blender/HanoiCar.blend

Scene of HanoiCar.blend (C1):
  CAR_CLEAN   CAR_<slot> one mesh per body slot (paint, glass, light, chrome, trim, plate), car coordinates:
              x = right, -y = nose, z = up, ground z = 0, origin = wheelbase midpoint;
              CAR_Wheel{FL,FR,RL,RR} (tyre + rim + brake), origin = axle centre.
Report: Blender/car/car_c1.json, preview Blender/previews/car_c1_sheet.png.
Source model: hanoi_car.CREDIT (CC-BY-4.0).
"""
import importlib
import json
import math
import os
from collections import defaultdict
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_car
importlib.reload(hanoi_car)
from hanoi_car import (BODY_UV, GLASS_SRGB, LODS, NAME, PAINT_COLOURS, PAINT_GREY, RIM_DATA, RIM_RECT,
                       SLOT_DATA, TEX_RES, TYRE_DATA, TYRE_RECT, TYRE_SRGB, CAGE, LENS_FRONT_SRGB, LENS_REAR_SRGB,
                       AMBIGUOUS, BODY_SLOTS, BAKE_MARGIN, BAKE_RES, BODY_TRIS, REAL_DIMS, RIM_INSET, SEAT_BOXES, SLOTS,
                       SMOOTH_ANGLE, SRC_GLTF, VOXEL, WHEEL_SIDES, WHEEL_SLOTS, base_name, slot_of)
from mathutils.bvhtree import BVHTree

BLEND = os.path.join(ROOT, "Blender", "HanoiCar.blend")
CAR_DIR = os.path.join(ROOT, "Blender", "car")
PREVIEW_DIR = os.path.join(ROOT, "Blender", "previews")


# ------------------------------------------------------------------ import
def import_source():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRC_GLTF)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    # bake every transform into the mesh (glTF nodes carry scale / rotation)
    for o in meshes:
        o.data = o.data.copy()
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    for o in [o for o in bpy.context.scene.objects if o.type != 'MESH']:
        bpy.data.objects.remove(o)
    return meshes


def faces_by_material(meshes):
    """material name -> list of (centroid, area, tri count) arrays over all meshes."""
    out = {}
    for o in meshes:
        me = o.data
        n = len(me.polygons)
        if n == 0:
            continue
        mi = np.zeros(n, dtype=np.int32); me.polygons.foreach_get('material_index', mi)
        cen = np.zeros(n * 3); me.polygons.foreach_get('center', cen); cen = cen.reshape(-1, 3)
        area = np.zeros(n); me.polygons.foreach_get('area', area)
        tot = np.zeros(n, dtype=np.int32); me.polygons.foreach_get('loop_total', tot)
        for k, slot in enumerate(o.material_slots):
            m = mi == k
            if not m.any():
                continue
            name = slot.material.name if slot.material else '(none)'
            d = out.setdefault(name, [[], [], []])
            d[0].append(cen[m]); d[1].append(area[m]); d[2].append(tot[m] - 2)
    return {k: (np.concatenate(v[0]), np.concatenate(v[1]), int(np.concatenate(v[2]).sum())) for k, v in out.items()}


def car_frame(fm):
    """Long axis, nose direction and ground from the exterior materials -> (R, t) mapping source -> car coords."""
    body = np.concatenate([c for n, (c, a, t) in fm.items() if slot_of(n) == 'paint'])
    lo, hi = body.min(0), body.max(0)
    ext = hi - lo
    up = 2                                                       # glTF importer gives Z up
    long_ax = 0 if ext[0] > ext[1] else 1
    side_ax = 1 - long_ax
    # the rear lights sit at the back
    rear = np.concatenate([c for n, (c, a, t) in fm.items() if base_name(n) in ('rearlight', 'rearlight_nm')])
    mid = (lo + hi) / 2
    rear_sign = 1.0 if rear[:, long_ax].mean() > mid[long_ax] else -1.0
    # car coords: y = towards the rear (so -y = nose), x = right when looking from behind the car forward
    R = np.zeros((3, 3))
    R[1, long_ax] = rear_sign
    R[2, up] = 1.0
    R[0] = np.cross(R[1], R[2])                                  # right-handed
    tyres = np.concatenate([c for n, (c, a, t) in fm.items() if slot_of(n) == 'tyre'])
    tz = tyres @ R.T
    centre = np.array([(tz[:, 0].min() + tz[:, 0].max()) / 2, (tz[:, 1].min() + tz[:, 1].max()) / 2, tz[:, 2].min()])
    return R, centre


# ------------------------------------------------------------------ inspect
def inspect():
    meshes = import_source()
    fm = faces_by_material(meshes)
    R, c = car_frame(fm)
    allc = np.concatenate([v[0] for v in fm.values()]) @ R.T - c
    print(f"[car] source {sum(v[2] for v in fm.values())} tris, {len(fm)} materials, "
          f"car box x {allc[:, 0].min():.2f}..{allc[:, 0].max():.2f} y {allc[:, 1].min():.2f}..{allc[:, 1].max():.2f} "
          f"z {allc[:, 2].min():.2f}..{allc[:, 2].max():.2f}")
    rows = []
    for n, (cen, area, tris) in fm.items():
        p = cen @ R.T - c
        rows.append((slot_of(n) or 'INTERIOR', n, tris, p.mean(0), p.min(0), p.max(0), area.sum()))
    for s, n, tris, m, lo, hi, a in sorted(rows, key=lambda r: (r[0], -r[2])):
        print(f"  {s:9s} {n:32s} {tris:7d} tris  area {a:6.2f} m2  centre ({m[0]:5.2f},{m[1]:5.2f},{m[2]:5.2f})  "
              f"x {lo[0]:5.2f}..{hi[0]:5.2f} y {lo[1]:5.2f}..{hi[1]:5.2f} z {lo[2]:5.2f}..{hi[2]:5.2f}")


# ------------------------------------------------------------------ clean
WHEELS = {'FL': (-1, -1), 'FR': (1, -1), 'RL': (-1, 1), 'RR': (1, 1)}     # (x sign, y sign); -y = nose


def keep_faces(src, pred, name):
    """New object with the faces of src whose (material name, centre) satisfy pred; None if empty."""
    bm = bmesh.new()
    bm.from_mesh(src.data)
    names = [s.material.name if s.material else '' for s in src.material_slots]
    drop = [f for f in bm.faces if not pred(names[f.material_index] if f.material_index < len(names) else '',
                                            f.calc_center_median())]
    bmesh.ops.delete(bm, geom=drop, context='FACES')
    if not bm.faces:
        bm.free()
        return None
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for s in src.material_slots:
        me.materials.append(s.material)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def join(objs, name, coll):
    objs = [o for o in objs if o is not None]
    if not objs:
        return None
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = name
    # drop material slots nothing uses any more
    used = set(np.unique([p.material_index for p in ob.data.polygons]))
    for i in reversed(range(len(ob.material_slots))):
        if i not in used:
            ob.active_material_index = i
            bpy.ops.object.material_slot_remove()
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    coll.objects.link(ob)
    return ob


def tris_of(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def clean():
    meshes = import_source()
    fm = faces_by_material(meshes)
    R, c = car_frame(fm)
    # source -> car coordinates (rotation R, then the wheelbase midpoint on the ground to the origin)
    M = Matrix.Translation(Vector(-c)) @ Matrix([list(R[0]) + [0], list(R[1]) + [0], list(R[2]) + [0], [0, 0, 0, 1]])
    for o in meshes:
        o.data.transform(M)
        o.data.update()

    coll = bpy.data.collections.new("CAR_CLEAN")
    bpy.context.scene.collection.children.link(coll)
    report = dict(source_tris=sum(v[2] for v in fm.values()), slots={}, wheels={})
    for slot in BODY_SLOTS:
        parts = [keep_faces(o, lambda n, p, s=slot: slot_of(n) == s, f"tmp_{slot}") for o in meshes]
        ob = join(parts, f"CAR_{slot}", coll)
        if ob:
            report['slots'][slot] = tris_of(ob)
    # wheels: tyre + rim + brake faces by quarter of the car
    for w, (sx, sy) in WHEELS.items():
        parts = [keep_faces(o, lambda n, p, sx=sx, sy=sy: slot_of(n) in WHEEL_SLOTS and p.x * sx > 0 and p.y * sy > 0,
                            f"tmp_{w}") for o in meshes]
        ob = join(parts, f"CAR_Wheel{w}", coll)
        tyre_idx = {i for i, s in enumerate(ob.material_slots) if s.material and slot_of(s.material.name) == 'tyre'}
        vs = np.array([ob.data.vertices[v].co[:] for p in ob.data.polygons if p.material_index in tyre_idx
                       for v in p.vertices])
        lo, hi = vs.min(0), vs.max(0)
        axle = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2))
        ob.data.transform(Matrix.Translation(-axle))
        ob.location = axle
        report['wheels'][w] = dict(axle=[round(v, 4) for v in axle], radius=round((hi[2] - lo[2]) / 2, 4),
                                   width=round(hi[0] - lo[0], 4), tris=tris_of(ob))
    for o in meshes:
        bpy.data.objects.remove(o)
    for m in [m for m in bpy.data.meshes if m.users == 0]:
        bpy.data.meshes.remove(m)

    body = [o for o in coll.objects if not o.name.startswith('CAR_Wheel')]
    pts = np.concatenate([np.array([v.co[:] for v in o.data.vertices]) for o in body])
    lo, hi = pts.min(0), pts.max(0)
    paint = np.array([v.co[:] for v in coll.objects['CAR_paint'].data.vertices])
    wb = report['wheels']['RL']['axle'][1] - report['wheels']['FL']['axle'][1]
    track = report['wheels']['FR']['axle'][0] - report['wheels']['FL']['axle'][0]
    report['dims'] = dict(length=round(hi[1] - lo[1], 3), width_body=round(np.ptp(paint[:, 0]), 3),
                          width_mirrors=round(hi[0] - lo[0], 3), height=round(hi[2], 3),
                          wheelbase=round(wb, 3), track=round(track, 3), real=REAL_DIMS)
    report['kept_tris'] = sum(tris_of(o) for o in coll.objects)
    report['credit'] = hanoi_car.CREDIT
    os.makedirs(CAR_DIR, exist_ok=True)
    with open(os.path.join(CAR_DIR, "car_c1.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    print(f"[car] kept {report['kept_tris']} of {report['source_tris']} tris; slots {report['slots']}")
    print(f"[car] wheels {json.dumps(report['wheels'])}")
    print(f"[car] dims {report['dims']}")


# ------------------------------------------------------------------ preview
SLOT_COLOURS = {'paint': (0.75, 0.15, 0.12, 1), 'glass': (0.15, 0.35, 0.55, 1), 'light': (1.0, 0.85, 0.3, 1),
                'chrome': (0.85, 0.85, 0.9, 1), 'trim': (0.12, 0.12, 0.12, 1), 'plate': (0.95, 0.95, 0.95, 1),
                'Wheel': (0.35, 0.35, 0.38, 1)}
VIEWS = [((-4.5, -6.0, 2.2), 'front34'), ((-8.0, 0.0, 0.9), 'side'), ((4.5, 6.0, 2.4), 'rear34'),
         ((0.0, 0.0, 14.0), 'top')]


def render_views(colls, colour='OBJECT', mask=False, res=(900, 600)):
    """Render the 4 VIEWS with only `colls` visible -> list of (h, w, 4) float arrays (bottom-up rows).
    mask: transparent film, the alpha channel is the silhouette."""
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light = 'FLAT' if mask else 'STUDIO'
    sh.color_type = 'SINGLE' if mask else colour
    sh.show_cavity = not mask
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = mask
    for c in bpy.data.collections:
        c.hide_render = c.name not in colls
    cam = bpy.data.objects.get("PrevCam") or bpy.data.objects.new("PrevCam", bpy.data.cameras.new("PrevCam"))
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = 50
    tiles = []
    for loc, name in VIEWS:
        cam.location = loc
        d = Vector((0, 0, 0.7)) - Vector(loc)
        cam.rotation_euler = (0, 0, 0) if name == 'top' else d.to_track_quat('-Z', 'Y').to_euler()
        path = os.path.join(PREVIEW_DIR, f"_tmp_{name}.png")
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(path)
        tiles.append(np.array(img.pixels[:]).reshape(res[1], res[0], 4))
        bpy.data.images.remove(img)
        os.remove(path)
    return tiles


def save_sheet(tiles, tag):
    h, w = tiles[0].shape[:2]
    sheet = np.concatenate([np.concatenate(tiles[2:], 1), np.concatenate(tiles[:2], 1)], 0)   # pixels are bottom-up
    out = bpy.data.images.new(tag, 2 * w, 2 * h)
    out.pixels = sheet.ravel()
    out.filepath_raw = os.path.join(PREVIEW_DIR, f"{tag}_sheet.png")
    out.file_format = 'PNG'
    out.save()
    print(f"[car] preview {out.filepath_raw}")


def preview(tag, coll_name="CAR_CLEAN"):
    """4 views (front 3/4, side, rear 3/4, top), one colour per slot to check the grouping."""
    for o in bpy.data.collections[coll_name].objects:
        key = o.name.split('_')[-1]
        o.color = SLOT_COLOURS.get(key, SLOT_COLOURS['Wheel'] if 'Wheel' in o.name else (1, 0, 1, 1))
    save_sheet(render_views({coll_name}, 'OBJECT'), tag)


# ------------------------------------------------------------------ C2: LOD0
def slot_materials():
    """One flat material per slot (viewport colour = SLOT_COLOURS); the real atlas material comes in C3."""
    mats = []
    for s in SLOTS:
        m = bpy.data.materials.get(f"S_{s}") or bpy.data.materials.new(f"S_{s}")
        m.diffuse_color = SLOT_COLOURS.get(s, SLOT_COLOURS['Wheel'])
        mats.append(m)
    return mats


def slot_trees():
    """BVH of every CAR_<slot> source object (car coordinates)."""
    dg = bpy.context.evaluated_depsgraph_get()
    return {s: BVHTree.FromObject(bpy.data.objects[f"CAR_{s}"], dg) for s in BODY_SLOTS if f"CAR_{s}" in bpy.data.objects}


def nearest_slot(trees, p):
    best, bd = 'paint', 1e9
    for s, t in trees.items():
        hit = t.find_nearest(p)
        if hit[0] is not None and hit[3] < bd:
            best, bd = s, hit[3]
    return best


def assign_slots(ob, trees, samples=False):
    """Per-face slot from the nearest source surface (face centre; samples: + 3 points towards the corners,
    majority) -> material index + int face attribute 'slot'."""
    me = ob.data
    idx = {s: i for i, s in enumerate(SLOTS)}
    out = []
    for f in me.polygons:
        c = f.center
        pts = [c] + ([c.lerp(me.vertices[v].co, 0.6) for v in f.vertices[:3]] if samples else [])
        votes = defaultdict(int)
        for q in pts:
            votes[nearest_slot(trees, q)] += 1
        out.append(idx[max(votes, key=votes.get)])
    me.polygons.foreach_set('material_index', out)
    attr = me.attributes.get('slot') or me.attributes.new('slot', 'INT', 'FACE')
    attr.data.foreach_set('value', out)
    return out


def drop_inner_shells(ob):
    """After the remesh the empty cabin / engine bay become closed shells inside the body: delete every loose
    part that lies inside the biggest one (ray parity), and crumbs."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    parts, seen = [], set()
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, comp = [f], []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            comp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        parts.append(comp)
    areas = [sum(g.calc_area() for g in c) for c in parts]
    order = sorted(range(len(parts)), key=lambda i: -areas[i])
    outer = parts[order[0]]
    flat = []
    for g in outer:
        loop = [v.co.copy() for v in g.verts]
        for k in range(1, len(loop) - 1):
            flat += [loop[0], loop[k], loop[k + 1]]
    tree = BVHTree.FromPolygons(flat, [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(len(flat) // 3)])

    def inside(p):
        n, o = 0, p.copy()
        for _ in range(64):
            hit = tree.ray_cast(o, Vector((0.0, 0.0, 1.0)))
            if hit[0] is None:
                break
            n += 1
            o = hit[0] + Vector((0, 0, 1e-4))
        return n % 2 == 1

    drop, kept = [], 1
    for i in order[1:]:
        comp = parts[i]
        if areas[i] < 0.02 or inside(comp[len(comp) // 2].calc_center_median()):
            drop += comp
        else:
            kept += 1
    bmesh.ops.delete(bm, geom=list(set(drop)), context='FACES')
    bm.to_mesh(ob.data)
    bm.free()
    print(f"[car] shell: {len(parts)} loose parts, kept {kept}, dropped {len(parts) - kept}")


def body_shell(coll, trees):
    """Exterior slots -> voxel remesh -> inner shells out -> slot transfer -> symmetric decimate -> slots again."""
    srcs = [bpy.data.objects[f"CAR_{s}"] for s in BODY_SLOTS if f"CAR_{s}" in bpy.data.objects]
    me = bpy.data.meshes.new("CAR_Body_LOD0")
    bm = bmesh.new()
    for o in srcs:
        bm.from_mesh(o.data)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("CAR_Body_LOD0", me)
    coll.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    rm = ob.modifiers.new("remesh", 'REMESH')
    rm.mode, rm.voxel_size = 'VOXEL', VOXEL
    bpy.ops.object.modifier_apply(modifier=rm.name)
    print(f"[car] remesh {VOXEL} m: {tris_of(ob)} tris")
    drop_inner_shells(ob)
    # symmetric collapse down to the budget (one pass rarely lands on it)
    for _ in range(4):
        n = tris_of(ob)
        if n <= BODY_TRIS * 1.05:
            break
        dm = ob.modifiers.new("decimate", 'DECIMATE')
        dm.decimate_type, dm.ratio = 'COLLAPSE', BODY_TRIS / n
        dm.use_symmetry, dm.symmetry_axis = True, 'X'
        bpy.ops.object.modifier_apply(modifier=dm.name)
    smooth_by_angle(ob)
    for m in slot_materials():
        me.materials.append(m)
    assign_slots(ob, trees, samples=True)
    return ob


def smooth_by_angle(ob):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(SMOOTH_ANGLE))


def unwrap(ob):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(55), island_margin=0.004, area_weight=1.0)
    bpy.ops.object.mode_set(mode='OBJECT')


def bake_slot_map(body):
    """Slot colours of the detailed CAR_<slot> objects baked onto the LOD0 body (selected to active, emission):
    sharp window / light outlines whatever the triangulation. -> Blender/car/T_CarSlots.png"""
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 4
    img = bpy.data.images.get("T_CarSlots") or bpy.data.images.new("T_CarSlots", BAKE_RES, BAKE_RES)
    tgt = bpy.data.materials.get("M_CarBake") or bpy.data.materials.new("M_CarBake")
    tgt.use_nodes = True
    nt = tgt.node_tree
    tex = next((n for n in nt.nodes if n.type == 'TEX_IMAGE'), None) or nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    nt.nodes.active = tex
    saved = body.data.materials[:]
    body.data.materials.clear()
    body.data.materials.append(tgt)
    # emission material per slot on the sources (restored afterwards)
    srcs, keep = [], {}
    for s in BODY_SLOTS:
        o = bpy.data.objects.get(f"CAR_{s}")
        if o is None:
            continue
        e = bpy.data.materials.get(f"E_{s}") or bpy.data.materials.new(f"E_{s}")
        e.use_nodes = True
        en = e.node_tree
        for n in list(en.nodes):
            en.nodes.remove(n)
        em = en.nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = SLOT_COLOURS[s]
        out = en.nodes.new('ShaderNodeOutputMaterial')
        en.links.new(em.outputs[0], out.inputs['Surface'])
        keep[o.name] = [sl.material for sl in o.material_slots]
        for sl in o.material_slots:
            sl.material = e
        srcs.append(o)
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in srcs:
        o.hide_render = False
        o.select_set(True)
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.bake(type='EMIT', use_selected_to_active=True, cage_extrusion=0.04, max_ray_distance=0.12,
                        margin=BAKE_MARGIN)
    img.filepath_raw = os.path.join(CAR_DIR, "T_CarSlots.png")
    img.file_format = 'PNG'
    img.save()
    for o in srcs:
        for sl, m in zip(o.material_slots, keep[o.name]):
            sl.material = m
    # preview material: the baked map, lit
    pm = bpy.data.materials.get("M_CarSlotsPreview") or bpy.data.materials.new("M_CarSlotsPreview")
    pm.use_nodes = True
    pn = pm.node_tree
    bsdf = next(n for n in pn.nodes if n.type == 'BSDF_PRINCIPLED')
    ti = next((n for n in pn.nodes if n.type == 'TEX_IMAGE'), None) or pn.nodes.new('ShaderNodeTexImage')
    ti.image = img
    pn.links.new(ti.outputs['Color'], bsdf.inputs['Base Color'])
    body.data.materials.clear()
    body.data.materials.append(pm)
    print(f"[car] baked slot map {img.filepath_raw}")
    return saved


def seat_boxes(body):
    """Two dark boxes (seat backs) seen through the tinted glass, appended to the body mesh (slot trim)."""
    bm = bmesh.new()
    bm.from_mesh(body.data)
    trim = SLOTS.index('trim')
    attr = bm.faces.layers.int.get('slot')
    for c, size in SEAT_BOXES:
        r = bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=Vector(size), verts=r['verts'])
        bmesh.ops.translate(bm, vec=Vector(c), verts=r['verts'])
        for f in {f for v in r['verts'] for f in v.link_faces}:
            f.material_index = trim
            f[attr] = trim
    bm.to_mesh(body.data)
    bm.free()


def tyre_profile(n, hw, R, rim_r):
    """Tyre cross-section (x across, r) from the inner rim lip over the tread to the outer one; n = 8 / 6 / 4 points."""
    mid = rim_r + 0.35 * (R - rim_r)
    if n >= 8:
        return [(-hw * 0.92, rim_r), (-hw, mid), (-hw * 0.9, R - 0.012), (-hw * 0.55, R),
                (hw * 0.55, R), (hw * 0.9, R - 0.012), (hw, mid), (hw * 0.92, rim_r)]
    if n >= 6:
        return [(-hw * 0.92, rim_r), (-hw, mid), (-hw * 0.75, R), (hw * 0.75, R), (hw, mid), (hw * 0.92, rim_r)]
    return [(-hw * 0.92, rim_r), (-hw * 0.85, R), (hw * 0.85, R), (hw * 0.92, rim_r)]


def wheel_mesh(name, info, rim_r, coll, sides=WHEEL_SIDES, profile=8):
    """Procedural wheel around the axle (origin), axis = x, outer side = sign of the axle x: tyre profile revolved,
    a short barrel and one rim disc facing out. One segment boundary points straight down, so the tread touches
    z = axle - R exactly at every LOD. UVs: rim disc -> RIM_RECT (planar, as the rim render), barrel -> rim edge,
    tyre -> TYRE_RECT."""
    R, W = info['radius'], info['width']
    out = 1.0 if info['axle'][0] > 0 else -1.0
    prof = [(x * out, r) for x, r in tyre_profile(profile, W / 2, R, rim_r)]
    bm = bmesh.new()
    slot_l = bm.faces.layers.int.new('slot')
    uv_l = bm.loops.layers.uv.new('UVMap')
    tyre, rim = SLOTS.index('tyre'), SLOTS.index('rim')
    ang = [-math.pi / 2 + 2 * math.pi * k / sides for k in range(sides)]
    rings = [[bm.verts.new((x, r * math.cos(a), r * math.sin(a))) for x, r in prof] for a in ang]
    tu = ((TYRE_RECT[0] + TYRE_RECT[2]) / 2, (TYRE_RECT[1] + TYRE_RECT[3]) / 2)
    cu, cv = (RIM_RECT[0] + RIM_RECT[2]) / 2, (RIM_RECT[1] + RIM_RECT[3]) / 2
    k_uv = (RIM_RECT[2] - RIM_RECT[0]) / 2 / rim_r * 0.98

    def rim_uv(co):                                             # outer face seen from outside, as rendered
        return (cu + k_uv * (-co.y if out < 0 else co.y), cv + k_uv * co.z)

    for k in range(sides):
        a, b = rings[k], rings[(k + 1) % sides]
        for j in range(len(prof) - 1):
            f = bm.faces.new((a[j], a[j + 1], b[j + 1], b[j]))
            f.material_index, f[slot_l] = tyre, tyre
            for l in f.loops:
                l[uv_l].uv = tu
    xr = (W / 2 * 0.92 - RIM_INSET) * out
    disc = [bm.verts.new((xr, rim_r * math.cos(a), rim_r * math.sin(a))) for a in ang]
    f = bm.faces.new(disc)
    f.material_index, f[slot_l] = rim, rim
    for l in f.loops:
        l[uv_l].uv = rim_uv(l.vert.co)
    lip = [r_[-1] for r_ in rings]
    for k in range(sides):
        g = bm.faces.new((lip[k], lip[(k + 1) % sides], disc[(k + 1) % sides], disc[k]))
        g.material_index, g[slot_l] = rim, rim
        for l in g.loops:
            l[uv_l].uv = rim_uv(l.vert.co * 0.97)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in slot_materials():
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    ob.location = Vector(info['axle'])
    coll.objects.link(ob)
    return ob


def rim_radius():
    """Outer radius of the source rim (rim faces of CAR_WheelFL around its axle)."""
    ob = bpy.data.objects["CAR_WheelFL"]
    ri = {i for i, s in enumerate(ob.material_slots) if s.material and slot_of(s.material.name) == 'rim'}
    rs = [math.hypot(ob.data.vertices[v].co.y, ob.data.vertices[v].co.z)
          for p in ob.data.polygons if p.material_index in ri for v in p.vertices]
    return float(np.percentile(rs, 99))


def iou(colls_a, colls_b):
    """Silhouette overlap per view (rendered alpha masks)."""
    a = render_views(colls_a, mask=True, res=(450, 300))
    b = render_views(colls_b, mask=True, res=(450, 300))
    res = {}
    for (loc, name), x, y in zip(VIEWS, a, b):
        ma, mb = x[..., 3] > 0.5, y[..., 3] > 0.5
        res[name] = round(float((ma & mb).sum() / max((ma | mb).sum(), 1)), 3)
    return res


def lod0():
    report = json.load(open(os.path.join(CAR_DIR, "car_c1.json"), encoding="utf-8"))
    old = bpy.data.collections.get("CAR_LOD0")
    if old:
        for o in list(old.objects):
            bpy.data.objects.remove(o)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new("CAR_LOD0")
    bpy.context.scene.collection.children.link(coll)
    trees = slot_trees()
    body = body_shell(coll, trees)
    seat_boxes(body)
    unwrap(body)
    bake_slot_map(body)
    rr = rim_radius()
    wheels = [wheel_mesh(f"CAR_Wheel{w}_LOD0", info, rr, coll) for w, info in report['wheels'].items()]
    counts = dict(body=tris_of(body), wheels=[tris_of(w) for w in wheels])
    counts['total'] = counts['body'] + sum(counts['wheels'])
    slots = defaultdict(int)
    for v in body.data.attributes['slot'].data:
        slots[SLOTS[v.value]] += 1
    counts['body_faces_by_slot'] = dict(slots)
    counts['rim_radius'] = round(rr, 3)
    counts['iou'] = iou({"CAR_CLEAN"}, {"CAR_LOD0"})
    with open(os.path.join(CAR_DIR, "car_c2.json"), "w", encoding="utf-8") as f:
        json.dump(counts, f, indent=1)
    print(f"[car] LOD0 {counts}")
    for c in bpy.data.collections:
        c.hide_render = False
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    save_sheet(render_views({"CAR_LOD0"}, 'TEXTURE'), "car_c2")


# ------------------------------------------------------------------ C3: textures, LODs, export
EXPORT_DIR = os.path.join(ROOT, "Export", "Vehicles")
FBX_OUT = os.path.join(EXPORT_DIR, "FBX")


def srgb_lin(c):
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def new_image(name, colour=(0, 0, 0, 1), data=False):
    img = bpy.data.images.get(name)
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, TEX_RES, TEX_RES, alpha=True, float_buffer=False)
    img.generated_color = colour
    if data:
        img.colorspace_settings.name = 'Non-Color'
    return img


def pack_body_uvs(body):
    """Smart-project UVs scaled into [0, BODY_UV]^2 (the rest of the texture holds the wheel tiles)."""
    unwrap(body)
    uv = body.data.uv_layers.active.data
    co = np.zeros(len(uv) * 2)
    uv.foreach_get('uv', co)
    uv.foreach_set('uv', co * BODY_UV)


def temp_principled(name, rgb):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    b.inputs['Base Color'].default_value = (*srgb_lin(rgb), 1)
    return m


def lens_material():
    """Albedo stand-in for the clear lamp lenses (they bake dark): silver-white at the front, red at the back."""
    m = bpy.data.materials.get("B_lens") or bpy.data.materials.new("B_lens")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    gt = nt.nodes.new('ShaderNodeMath'); gt.operation = 'GREATER_THAN'; gt.inputs[1].default_value = 0.0
    mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'
    mix.inputs['A'].default_value = (*srgb_lin(LENS_FRONT_SRGB), 1)
    mix.inputs['B'].default_value = (*srgb_lin(LENS_REAR_SRGB), 1)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(geo.outputs['Position'], sep.inputs[0])
    nt.links.new(sep.outputs['Y'], gt.inputs[0])                   # +y = rear of the car
    nt.links.new(gt.outputs[0], mix.inputs['Factor'])
    nt.links.new(mix.outputs['Result'], bsdf.inputs['Base Color'])
    nt.links.new(bsdf.outputs[0], out.inputs['Surface'])
    return m


def bake_body(body):
    """Selected-to-active bakes from the CAR_<slot> sources onto the LOD0 body: slot map (emission), albedo
    (diffuse colour; paint neutral grey, glass tinted dark) and the tangent-space normal map."""
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 4
    tgt = bpy.data.materials.get("M_CarBake") or bpy.data.materials.new("M_CarBake")
    tgt.use_nodes = True
    nt = tgt.node_tree
    tex = next((n for n in nt.nodes if n.type == 'TEX_IMAGE'), None) or nt.nodes.new('ShaderNodeTexImage')
    nt.nodes.active = tex
    body.data.materials.clear()
    body.data.materials.append(tgt)
    srcs = [bpy.data.objects[f"CAR_{s}"] for s in BODY_SLOTS if f"CAR_{s}" in bpy.data.objects]
    keep = {o.name: [sl.material for sl in o.material_slots] for o in srcs}

    def set_mats(fn):
        for o in srcs:
            slot = o.name[4:]
            for sl, orig in zip(o.material_slots, keep[o.name]):
                sl.material = fn(slot, orig)

    def run(img, **kw):
        tex.image = img
        for o in bpy.context.selected_objects:
            o.select_set(False)
        for o in srcs:
            o.hide_render = False
            o.select_set(True)
        body.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.bake(use_selected_to_active=True, cage_extrusion=CAGE, max_ray_distance=2 * CAGE + 0.04,
                            margin=BAKE_MARGIN, **kw)

    imgs = {}
    # slot map: emission colour per slot
    emis = {}
    for s in BODY_SLOTS:
        e = bpy.data.materials.get(f"E_{s}") or bpy.data.materials.new(f"E_{s}")
        e.use_nodes = True
        en = e.node_tree
        for n in list(en.nodes):
            en.nodes.remove(n)
        em = en.nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = SLOT_COLOURS[s]
        en.links.new(em.outputs[0], en.nodes.new('ShaderNodeOutputMaterial').inputs['Surface'])
        emis[s] = e
    set_mats(lambda slot, orig: emis[slot])
    imgs['slots'] = new_image("T_CarSlots", data=True)
    run(imgs['slots'], type='EMIT')
    # albedo: originals, paint neutral, glass dark
    paint = temp_principled("B_paint", (PAINT_GREY,) * 3)
    glass = temp_principled("B_glass", GLASS_SRGB)
    lens = lens_material()
    set_mats(lambda slot, orig: paint if slot == 'paint' else glass if slot == 'glass'
             else lens if orig and base_name(orig.name) == 'light_glass' else orig)
    imgs['albedo'] = new_image("T_CarBody")
    run(imgs['albedo'], type='DIFFUSE', pass_filter={'COLOR'})
    # normal map (geometry only)
    set_mats(lambda slot, orig: orig)
    imgs['normal'] = new_image("T_CarBody_N", (0.5, 0.5, 1.0, 1.0), data=True)
    run(imgs['normal'], type='NORMAL', normal_space='TANGENT')
    return imgs


def px(img):
    return np.array(img.pixels[:], dtype=np.float32).reshape(TEX_RES, TEX_RES, 4)


def set_px(img, a):
    img.pixels.foreach_set(np.ascontiguousarray(a, dtype=np.float32).ravel())
    img.update()


def rect_px(rect):
    u0, v0, u1, v1 = rect
    return int(round(u0 * TEX_RES)), int(round(v0 * TEX_RES)), int(round(u1 * TEX_RES)), int(round(v1 * TEX_RES))


def render_rim(rim_r):
    """Source wheel FL seen straight from outside (orthographic, flat white world = soft AO look), square crop of
    the rim diameter -> float RGBA array of the RIM_RECT size."""
    sc = bpy.context.scene
    x0, y0, x1, y1 = rect_px(RIM_RECT)
    n = x1 - x0
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 32
    sc.render.resolution_x = sc.render.resolution_y = n
    sc.render.film_transparent = False
    world = sc.world or bpy.data.worlds.new("W")
    sc.world = world
    world.use_nodes = True
    bg = next(n_ for n_ in world.node_tree.nodes if n_.type == 'BACKGROUND')
    bg.inputs['Color'].default_value = (1, 1, 1, 1)
    bg.inputs['Strength'].default_value = 1.0
    for c in bpy.data.collections:
        c.hide_render = True
    w = bpy.data.objects["CAR_WheelFL"]
    tmp = bpy.data.collections.new("_RIM")
    sc.collection.children.link(tmp)
    tmp.objects.link(w)
    cam = bpy.data.objects.new("RimCam", bpy.data.cameras.new("RimCam"))
    sc.collection.objects.link(cam)
    cam.data.type, cam.data.ortho_scale = 'ORTHO', 2 * rim_r / 0.98
    cam.location = w.location + Vector((-1.5, 0, 0))
    cam.rotation_euler = Vector((1, 0, 0)).to_track_quat('-Z', 'Z').to_euler()
    sc.camera = cam
    path = os.path.join(CAR_DIR, "_rim.png")
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path)
    a = np.array(img.pixels[:], dtype=np.float32).reshape(n, n, 4)
    bpy.data.images.remove(img)
    os.remove(path)
    tmp.objects.unlink(w)
    bpy.data.collections.remove(tmp)
    bpy.data.objects.remove(cam)
    for c in bpy.data.collections:
        c.hide_render = False
    return a


def finish_textures(imgs, rim_r):
    """Wheel tiles into the albedo, the data map from the slot map (soft nearest-slot weights)."""
    alb, slots = px(imgs['albedo']), px(imgs['slots'])
    x0, y0, x1, y1 = rect_px(RIM_RECT)
    rim = render_rim(rim_r)
    n = rim.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]
    outside = np.hypot(xx - (n - 1) / 2, yy - (n - 1) / 2) > n / 2 * 0.98
    rim[outside, :3] = srgb_lin(TYRE_SRGB)                           # no white bleeding into the rim edge
    alb[y0:y1, x0:x1] = rim
    tx0, ty0, tx1, ty1 = rect_px(TYRE_RECT)
    alb[ty0:ty1, tx0:tx1, :3] = srgb_lin(TYRE_SRGB)
    alb[..., 3] = 1.0
    set_px(imgs['albedo'], alb)
    # data: weights by colour distance to each slot colour of the slot map
    cols = np.array([SLOT_COLOURS[s][:3] for s in BODY_SLOTS], dtype=np.float32)
    vals = np.array([SLOT_DATA[s] for s in BODY_SLOTS], dtype=np.float32)
    d2 = ((slots[..., None, :3] - cols[None, None]) ** 2).sum(-1)
    w = np.exp(-d2 / 0.01)
    w /= w.sum(-1, keepdims=True) + 1e-6
    data = w @ vals
    data[y0:y1, x0:x1] = RIM_DATA
    data[ty0:ty1, tx0:tx1] = TYRE_DATA
    imgs['data'] = new_image("T_CarBodyData", data=True)
    set_px(imgs['data'], data)
    for key, fname in (('albedo', 'T_CarBody.png'), ('data', 'T_CarBodyData.png'), ('normal', 'T_CarBody_N.png'),
                       ('slots', 'T_CarSlots.png')):
        im = imgs[key]
        im.filepath_raw = os.path.join(CAR_DIR, fname)
        im.file_format = 'PNG'
        im.save()
    print(f"[car] textures {', '.join(i.filepath_raw for i in imgs.values())}")


def car_material(imgs):
    """Blender-side material (preview + FBX): albedo, normal map. Unity builds Hanoi/Vehicle from the PNGs."""
    m = bpy.data.materials.get("M_CarLuxA2") or bpy.data.materials.new("M_CarLuxA2")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(bsdf.outputs[0], out.inputs['Surface'])
    ta = nt.nodes.new('ShaderNodeTexImage'); ta.image = imgs['albedo']
    nt.links.new(ta.outputs['Color'], bsdf.inputs['Base Color'])
    tn = nt.nodes.new('ShaderNodeTexImage'); tn.image = imgs['normal']
    nm = nt.nodes.new('ShaderNodeNormalMap')
    nt.links.new(tn.outputs['Color'], nm.inputs['Color'])
    nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    bsdf.inputs['Roughness'].default_value = 0.4
    nt.nodes.active = ta
    return m


def decimated_copy(src, name, target, coll):
    me = src.data.copy()
    me.name = name
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    for _ in range(4):
        n = tris_of(ob)
        if n <= target * 1.05:
            break
        dm = ob.modifiers.new("decimate", 'DECIMATE')
        dm.decimate_type, dm.ratio = 'COLLAPSE', target / n
        dm.use_symmetry, dm.symmetry_axis = True, 'X'
        bpy.ops.object.modifier_apply(modifier=dm.name)
    return ob


def c3():
    report = json.load(open(os.path.join(CAR_DIR, "car_c1.json"), encoding="utf-8"))
    rim_r = rim_radius()
    body0 = bpy.data.objects["CAR_Body_LOD0"]
    pack_body_uvs(body0)
    imgs = bake_body(body0)
    finish_textures(imgs, rim_r)
    mat = car_material(imgs)

    old = bpy.data.collections.get("CAR_EXPORT")
    if old:
        for o in list(old.objects):
            bpy.data.objects.remove(o)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new("CAR_EXPORT")
    bpy.context.scene.collection.children.link(coll)
    static = bpy.data.objects.new(NAME, None); coll.objects.link(static)
    rig = bpy.data.objects.new(f"{NAME}_Rig", None); coll.objects.link(rig)
    static.location, rig.location = (0, 0, 0), (3.0, 0, 0)
    out = dict(name=NAME, tris={}, rig_tris={}, contact={})
    for lod, cfg in enumerate(LODS):
        body = body0 if lod == 0 else decimated_copy(body0, f"CAR_Body_LOD{lod}", cfg['body'],
                                                      bpy.data.collections["CAR_LOD0"])
        body.data.materials.clear()
        body.data.materials.append(mat)
        wheels = {}
        for w, info in report['wheels'].items():
            o = wheel_mesh(f"tmp_{w}{lod}", info, rim_r, coll, cfg['sides'], cfg['profile'])
            o.data.materials.clear()
            o.data.materials.append(mat)
            wheels[w] = o
        # contact: lowest tyre point of every wheel on the ground
        lows = {w: round(o.location.z + min(v.co.z for v in o.data.vertices), 4) for w, o in wheels.items()}
        out['contact'][f'LOD{lod}'] = dict(tyres=lows, body_min=round(min(v.co.z for v in body.data.vertices), 3))
        # rig: flat children with origins on their pivots
        rb = bpy.data.objects.new(f"Body_LOD{lod}", body.data.copy()); coll.objects.link(rb); rb.parent = rig
        rig_n = tris_of(rb)
        for w, o in wheels.items():
            ro = bpy.data.objects.new(f"Wheel{w}_LOD{lod}", o.data.copy()); coll.objects.link(ro)
            ro.parent, ro.location = rig, o.location.copy()
            rig_n += tris_of(ro)
        out['rig_tris'][f'LOD{lod}'] = rig_n
        # static: one merged mesh per LOD
        bm = bmesh.new()
        bm.from_mesh(body.data)
        for o in wheels.values():
            m2 = o.data.copy()
            m2.transform(Matrix.Translation(o.location))
            bm.from_mesh(m2)
            bpy.data.meshes.remove(m2)
            bpy.data.objects.remove(o)
        me = bpy.data.meshes.new(f"{NAME}_LOD{lod}")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mat)
        for p in me.polygons:
            p.material_index = 0
        so = bpy.data.objects.new(me.name, me); coll.objects.link(so); so.parent = static
        out['tris'][f'LOD{lod}'] = tris_of(so)
        out['contact'][f'LOD{lod}']['merged_min_z'] = round(min(v.co.z for v in me.vertices), 4)
    for o in coll.objects:
        if o.type == 'MESH' and 'slot' in o.data.attributes:
            o.data.attributes.remove(o.data.attributes['slot'])
    bpy.context.view_layer.update()
    bad = [(k, w, z) for k, c in out['contact'].items() for w, z in c['tyres'].items() if abs(z) > 0.005]
    print(f"[car] contact {out['contact']} -> {'OK' if not bad else f'NOT ON THE GROUND: {bad}'}")

    # export
    import hanoi_common, shutil
    os.makedirs(FBX_OUT, exist_ok=True)
    tex_out = os.path.join(EXPORT_DIR, 'Textures')
    os.makedirs(tex_out, exist_ok=True)
    for f in ('T_CarBody.png', 'T_CarBodyData.png', 'T_CarBody_N.png'):
        shutil.copy2(os.path.join(CAR_DIR, f), os.path.join(tex_out, f))
    hanoi_common.export_fbx(os.path.join(FBX_OUT, f"{NAME}.fbx"), [static], zero_roots=True)
    saved = tuple(rig.location)
    rig.location = (0, 0, 0)
    bpy.ops.object.select_all(action='DESELECT')
    for o in [rig] + list(rig.children):
        o.select_set(True)
    bpy.ops.export_scene.fbx(
        filepath=os.path.join(FBX_OUT, f"{NAME}_Rig.fbx"), use_selection=True, object_types={'EMPTY', 'MESH'},
        apply_scale_options='FBX_SCALE_ALL', axis_forward='-Z', axis_up='Y', bake_space_transform=True,
        mesh_smooth_type='FACE', use_mesh_modifiers=True, add_leaf_bones=False, bake_anim=False, path_mode='AUTO')
    rig.location = saved

    def to_unity(v):
        return [round(-v[0], 4), round(v[2], 4), round(-v[1], 4)]

    d = report['dims']
    body_pts = np.array([v.co[:] for v in body0.data.vertices])
    lo, hi = body_pts.min(0), body_pts.max(0)
    out.update({
        'units': 'metres, Unity axes (x right, y up, z forward); origin = ground, wheelbase midpoint; '
                 'the tyres touch y = 0 (checked per LOD in contact)',
        'size': [round(hi[0] - lo[0], 3), round(hi[2] - lo[2], 3), round(hi[1] - lo[1], 3)],
        'collider_box': dict(center=to_unity(((lo + hi) / 2).tolist()) and
                             [0.0, round((lo[2] + hi[2]) / 2 + 0.05, 3), round(-(lo[1] + hi[1]) / 2, 3)],
                             size=[round(d['width_body'], 3), round(hi[2] - lo[2] - 0.1, 3), round(hi[1] - lo[1], 3)]),
        'material': 'Hanoi/Vehicle: _BaseMap T_CarBody.png (albedo, paint baked neutral grey), _DataMap '
                    'T_CarBodyData.png (R rough, G metal, B lamps, A paint mask -> albedo x _PaintColor), normal '
                    'T_CarBody_N.png (tangent space). Body UVs in [0, 0.8]^2, rim tile u,v 0.8-1, tyre u 0.8-1 v 0.6-0.8',
        'paint_colours_srgb': PAINT_COLOURS,
        'rig': {
            'wheels': {w: dict(pivot=to_unity(i['axle']), radius=i['radius'], width=i['width'], spin_axis=[1, 0, 0],
                               steer=w.startswith('F')) for w, i in report['wheels'].items()},
            'wheelbase': d['wheelbase'], 'track': d['track'],
            'hierarchy': f'FBX is flat: {NAME}_Rig > Body_LODn, Wheel{{FL,FR,RL,RR}}_LODn (origins on the axles). '
                         'Unity: Steer{FL,FR} pivots on the front axles hold the front wheels (rotate about Y); '
                         'every wheel spins about its local X.',
        },
        'credit': hanoi_car.CREDIT,
    })
    hanoi_common.write_vehicle(EXPORT_DIR, out)
    with open(os.path.join(CAR_DIR, "car_c3.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"[car] LOD tris {out['tris']}, rig {out['rig_tris']}")
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    lod_sheet(static)


def lod_sheet(static):
    """LOD0 / LOD1 / LOD2 side by side (textured, paint shown white) from front 3/4 and rear 3/4."""
    exp = bpy.data.collections["CAR_EXPORT"]
    kids = sorted(static.children, key=lambda o: o.name)
    for i, o in enumerate(kids):
        o.location = (i * 2.6 - 2.6, 0, 0)
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light, sh.color_type, sh.show_cavity = 'STUDIO', 'TEXTURE', False
    sc.render.resolution_x, sc.render.resolution_y = 1600, 700
    sc.render.film_transparent = False
    for c in bpy.data.collections:
        c.hide_render = c.name != "CAR_EXPORT"
    hidden = [o for o in exp.objects if o not in kids and o.type == 'MESH']
    for o in hidden:
        o.hide_render = True
    cam = bpy.data.objects.get("PrevCam") or bpy.data.objects.new("PrevCam", bpy.data.cameras.new("PrevCam"))
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type, cam.data.ortho_scale = 'ORTHO', 9.5
    tiles = []
    for loc in ((-7.0, -9.0, 4.0), (7.0, 9.0, 4.0)):
        cam.location = loc
        cam.rotation_euler = (Vector((0, 0, 0.5)) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
        path = os.path.join(PREVIEW_DIR, "_lods.png")
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(path)
        tiles.append(np.array(img.pixels[:]).reshape(700, 1600, 4))
        bpy.data.images.remove(img)
        os.remove(path)
    for i, o in enumerate(kids):
        o.location = (0, 0, 0)
    for o in hidden:
        o.hide_render = False
    for c in bpy.data.collections:
        c.hide_render = False
    sheet = np.concatenate([tiles[1], tiles[0]], 0)
    outi = bpy.data.images.new("car_c3", 1600, 1400)
    outi.pixels = sheet.ravel()
    outi.filepath_raw = os.path.join(PREVIEW_DIR, "car_c3_sheet.png")
    outi.file_format = 'PNG'
    outi.save()
    print(f"[car] preview {outi.filepath_raw}")


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--inspect" in argv:
        inspect()
    elif "--clean" in argv:
        clean()
        preview("car_c1")
    elif "--lod0" in argv:                      # blender -b Blender/HanoiCar.blend --python build_car.py -- --lod0
        lod0()
    elif "--c3" in argv:                        # blender -b Blender/HanoiCar.blend --python build_car.py -- --c3
        c3()
