"""RIDER R1 — MakeHuman (MPFB) man in polo shirt + trousers + helmet (no pose, no reduction yet).

    blender -b --python Blender/scripts/build_rider.py -- --build      (NOT --factory-startup: MPFB is an extension)

Scene of Blender/HanoiRider.blend (R1):
  RIDER_SRC   Human (MPFB basemesh, macros hanoi_rider.MACROS, height TARGET_HEIGHT), Human.Polo_t-shirt,
              Human.m_trousers_01 (fitted mhclo clothes; the body under them masked by their delete groups),
              Helmet (the Sketchfab helmet joined into one mesh, scaled / placed on the head; its shell texture
              cleaned of every lettering -> Blender/rider/T_HelmetClean.png)
  Coordinates: x = right, -y = forward (like the bikes), feet on z = 0.
Report Blender/rider/rider_r1.json, sheet Blender/previews/rider_r1_sheet.png.
"""
import importlib
import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_rider
importlib.reload(hanoi_rider)
from hanoi_rider import (HELMET, HELMET_CLEARANCE, HELMET_PEAK_MATERIAL, HELMET_SHELL_MATERIAL, HELMET_SHELL_T,
                         HELMET_HAND, HELMET_SCALE, HELMET_TEX, HELMET_UP_FIX,
                         LETTERING_DIST, MACROS, POLO, SKIN_SRGB, TARGET_HEIGHT, TROUSERS)
from hanoi_rider import (ANKLE_FROM_FOOT, CULL_CONE_DEG, CULL_RAYS, ELBOW_POLE, FINGER_CURL_DEG, FOOT_DIR,
                         HELMET_PRE_TRIS, HIP_ABOVE_SEAT, KNEE_POLE, LEAN_DEG, MOTO_FBX, MOTO_ID, POLO_INFLATE, RIG, SHOES,
                         SHOES_TEX, WRIST_FROM_GRIP)
from hanoi_rider import (ATLAS_RES, BAKE_CAGE, BAKE_MARGIN, HELMET_COLOURS, HELMET_GREY, HULL_PARTS, LOD1_TRIS,
                         MIN_ISLAND, NAME, PART_TRIS, ROUGHNESS, SHIRT_COLOURS, SHIRT_GREY)
from mathutils.bvhtree import BVHTree

BLEND =os.path.join(ROOT, "Blender", "HanoiRider.blend")
RIDER_DIR = os.path.join(ROOT, "Blender", "rider")
PREVIEW_DIR = os.path.join(ROOT, "Blender", "previews")


def mpfb():
    """The MPFB services (Blender extension, loaded with the user preferences)."""
    import addon_utils
    mod = next((m for m in addon_utils.modules() if m.__name__.endswith(".mpfb")), None)
    if mod is None:
        raise RuntimeError("MPFB extension not found: run Blender without --factory-startup")
    addon_utils.enable(mod.__name__, default_set=True)
    base = mod.__name__
    hs = importlib.import_module(base + ".services.humanservice").HumanService
    ts = importlib.import_module(base + ".services.targetservice").TargetService
    props = importlib.import_module(base + ".entities.objectproperties").HumanObjectProperties
    return hs, ts, props


def tris_of(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def evaluated_verts(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    co = np.array([ob.matrix_world @ v.co for v in me.vertices])
    ev.to_mesh_clear()
    return co


def body_height(human):
    co = evaluated_verts(human)
    return float(co[:, 2].max() - co[:, 2].min())


# ------------------------------------------------------------------ human
def make_human():
    hs, ts, props = mpfb()
    macros = dict(MACROS)
    lo, hi = 0.0, 1.0
    human = None
    for it in range(7):                                  # bisection on the height macro
        macros['height'] = (lo + hi) / 2
        if human is not None:
            for k in ('height',):
                props.set_value(k, macros[k], entity_reference=human)
            ts.reapply_macro_details(human)
        else:
            human = hs.create_human(macro_detail_dict=macros)
        h = body_height(human)
        print(f"[rider] height macro {macros['height']:.3f} -> {h:.3f} m")
        if h > TARGET_HEIGHT:
            hi = macros['height']
        else:
            lo = macros['height']
    # feet back on the ground after the last change
    co = evaluated_verts(human)
    human.location.z -= co[:, 2].min()
    bpy.context.view_layer.update()
    human.name = "Human"
    return hs, human, macros['height']


def skin(human):
    """One flat skin material on the body (MPFB's default skin needs the system asset pack)."""
    m = bpy.data.materials.get("M_RiderSkin") or bpy.data.materials.new("M_RiderSkin")
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in SKIN_SRGB]
    b.inputs['Base Color'].default_value = (*lin, 1)
    b.inputs['Roughness'].default_value = 0.6
    m.diffuse_color = (*lin, 1)
    human.data.materials.clear()
    human.data.materials.append(m)


def dress(hs, human):
    """Polo, trousers, sneakers, rigged to the armature (they follow the pose); body under them masked."""
    out = []
    for f in (POLO, TROUSERS, SHOES):
        out.append(hs.add_mhclo_asset(f, human, asset_type="Clothes", subdiv_levels=0))
    return out


def bw_shoes(shoes):
    """Sneakers black / white: light low-saturation parts (sole, rims, laces) white, everything else black,
    a little of the original shading kept in both."""
    img = bpy.data.images.load(SHOES_TEX)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    rgb = px[..., :3]
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    white = (lum > 0.35) & (sat < 0.25)
    v = np.where(white, np.clip(0.78 + (lum - 0.6) * 0.4, 0.65, 0.92), np.clip(0.035 + (lum - 0.15) * 0.06, 0.015, 0.07))
    px[..., :3] = v[..., None]
    out = bpy.data.images.new("T_ShoesBW", w, h, alpha=True)
    out.pixels.foreach_set(px.ravel())
    out.filepath_raw = os.path.join(RIDER_DIR, "T_ShoesBW.png")
    out.file_format = 'PNG'
    out.save()
    bpy.data.images.remove(img)
    for m in shoes.data.materials:
        if m and m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == 'TEX_IMAGE' and n.image and 'normal' not in n.image.name.lower():
                    n.image = out
    print(f"[rider] shoes black / white: {white.mean() * 100:.0f} % white texels")


# ------------------------------------------------------------------ helmet
def clean_helmet_texture():
    """The shell colour = the most common texel colour; every texel far from it (lettering, logos) gets it."""
    img = bpy.data.images.load(HELMET_TEX)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    rgb = px[..., :3]
    q = np.round(rgb[::8, ::8].reshape(-1, 3) * 32) / 32
    vals, counts = np.unique(q, axis=0, return_counts=True)
    shell = vals[counts.argmax()]
    shell = rgb[np.linalg.norm(rgb - shell, axis=-1) < 0.06].mean(0)    # refine on the real texels
    d = np.linalg.norm(rgb - shell, axis=-1)
    bad = d > LETTERING_DIST
    rgb[bad] = shell
    px[..., :3] = rgb
    out = bpy.data.images.new("T_HelmetClean", w, h, alpha=True)
    out.pixels.foreach_set(px.ravel())
    out.filepath_raw = os.path.join(RIDER_DIR, "T_HelmetClean.png")
    out.file_format = 'PNG'
    out.save()
    bpy.data.images.remove(img)
    print(f"[rider] helmet texture: shell colour {np.round(shell, 3).tolist()}, {bad.mean() * 100:.1f} % texels repainted")
    return out


def load_helmet(human):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=HELMET)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == 'MESH']
    for o in meshes:
        o.data = o.data.copy()
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    for o in new:
        if o.type != 'MESH':
            bpy.data.objects.remove(o)
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.join()
    hel = bpy.context.view_layer.objects.active
    hel.name = hel.data.name = "Helmet"
    # upright, then the peak forward (-y)
    hel.data.transform(Matrix.Rotation(math.radians(HELMET_UP_FIX), 4, 'X'))

    def centroid(name):
        idx = {i for i, m in enumerate(hel.data.materials) if m and m.name == name}
        pts = [p.center for p in hel.data.polygons if p.material_index in idx]
        return sum(pts, Vector()) / max(len(pts), 1)

    d = centroid(HELMET_PEAK_MATERIAL) - centroid(HELMET_SHELL_MATERIAL)
    yaw = math.atan2(d.x, -d.y)                         # angle of the peak direction from -y
    hel.data.transform(Matrix.Rotation(-yaw, 4, 'Z'))
    # fit: shell width = head width + 2 x clearance; top of the shell above the head top; centred on the skull
    shell = {i for i, m in enumerate(hel.data.materials) if m and m.name == HELMET_SHELL_MATERIAL}
    co = np.array([hel.data.vertices[v].co[:] for p in hel.data.polygons if p.material_index in shell
                   for v in p.vertices[:1]])
    lo, hi = co.min(0), co.max(0)
    head = evaluated_verts(human)
    top = head[:, 2].max()
    skull = head[head[:, 2] > top - 0.20]
    s_lo, s_hi = skull.min(0), skull.max(0)
    head_w = s_hi[0] - s_lo[0]
    scale = (head_w + 2 * (HELMET_CLEARANCE + HELMET_SHELL_T)) / (hi[0] - lo[0]) * HELMET_SCALE
    c = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[2]))   # centre of the shell top
    target = Vector(((s_lo[0] + s_hi[0]) / 2, (s_lo[1] + s_hi[1]) / 2, top + HELMET_CLEARANCE + HELMET_SHELL_T))
    hel.data.transform(Matrix.Translation(target) @ Matrix.Scale(scale, 4) @ Matrix.Translation(-c))
    # pivot = centre of the shell (scale / rotate the helmet by hand around itself)
    sh = np.array([hel.data.vertices[v].co[:] for p in hel.data.polygons if p.material_index in shell
                   for v in p.vertices[:1]])
    pivot = Vector(((sh.min(0) + sh.max(0)) / 2).tolist())
    hel.data.transform(Matrix.Translation(-pivot))
    hel.location = pivot
    if HELMET_HAND:                                     # the user's fit, kept on rebuilds
        hel.location = Vector(HELMET_HAND['location'])
        hel.scale = (HELMET_HAND['scale'],) * 3
    clean = clean_helmet_texture()
    for m in hel.data.materials:
        if m and m.name.startswith(HELMET_SHELL_MATERIAL) and m.name.split('.')[0] == HELMET_SHELL_MATERIAL \
                and m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == 'TEX_IMAGE':
                    n.image = clean
    print(f"[rider] helmet: {tris_of(hel)} tris, peak yaw {math.degrees(yaw):.1f} deg, scale {scale:.5f}, head width {head_w:.3f} m")
    return hel, dict(scale=scale, yaw_deg=round(math.degrees(yaw), 2), head_width=float(head_w), head_top=float(top))


# ------------------------------------------------------------------ preview
def sheet(tag, objs, views, res=(700, 1000)):
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sh = sc.display.shading
    sh.light, sh.color_type, sh.show_cavity = 'STUDIO', 'TEXTURE', True
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = False
    keep = set(objs)
    for o in sc.objects:
        if o.type == 'MESH':
            o.hide_render = o not in keep
    cam = bpy.data.objects.get("PrevCam") or bpy.data.objects.new("PrevCam", bpy.data.cameras.new("PrevCam"))
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    sc.camera = cam
    tiles = []
    for loc, target, ortho in views:
        cam.data.type = 'ORTHO'
        cam.data.ortho_scale = ortho
        cam.location = loc
        cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
        path = os.path.join(PREVIEW_DIR, "_rider_tmp.png")
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(path)
        tiles.append(np.array(img.pixels[:]).reshape(res[1], res[0], 4))
        bpy.data.images.remove(img)
        os.remove(path)
    for o in sc.objects:
        o.hide_render = False
    row = np.concatenate(tiles, 1)
    out = bpy.data.images.new(tag, row.shape[1], row.shape[0])
    out.pixels = row.ravel()
    out.filepath_raw = os.path.join(PREVIEW_DIR, f"{tag}_sheet.png")
    out.file_format = 'PNG'
    out.save()
    print(f"[rider] preview {out.filepath_raw}")


# ------------------------------------------------------------------ R2 pose
def moto_anchors():
    v = next(x for x in json.load(open(os.path.join(ROOT, "Export", "Vehicles", "vehicles.json"), encoding="utf-8"))
             ['vehicles'] if x['name'] == MOTO_ID)
    return {k: Vector((-p[0], -p[2], p[1])) for k, p in v['anchors'].items()}      # Unity -> Blender


def attach_helmet(hel, rig):
    bpy.context.view_layer.update()
    mw = hel.matrix_world.copy()
    hel.parent, hel.parent_type, hel.parent_bone = rig, 'BONE', 'head'
    bpy.context.view_layer.update()
    hel.matrix_world = mw


def surface_z(tree, x, y, z_from):
    """Top of the bike mesh under (x, y), looking down from z_from."""
    hit = tree.ray_cast(Vector((x, y, z_from)), Vector((0, 0, -1)), 3.0)
    return None if hit[0] is None else hit[0].z


def mesh_anchors(moto):
    """The traced anchors put on the real mesh: SEAT_ANCHOR / FOOT_L/R keep their x, y but take the height of the
    seat top / floorboard below them (the traced SEAT_ANCHOR sits ~9 cm under the modelled seat)."""
    A = moto_anchors()
    dg = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(moto, dg)
    fixed = dict(A)
    s = A['SEAT_ANCHOR']
    zs = [surface_z(tree, x, s.y + dy, 1.5) for x in (-0.06, 0.0, 0.06) for dy in (-0.04, 0.0, 0.04)]
    zs = [z for z in zs if z is not None and z > 0.5]
    fixed['SEAT_ANCHOR'] = Vector((s.x, s.y, float(np.median(zs))))
    for S in ('L', 'R'):
        f = A[f'FOOT_{S}']
        z = surface_z(tree, f.x, f.y, f.z + 0.3)
        if z is not None:
            fixed[f'FOOT_{S}'] = Vector((f.x, f.y, z))
    diff = {k: round(fixed[k].z - A[k].z, 3) for k in ('SEAT_ANCHOR', 'FOOT_L', 'FOOT_R')}
    print(f"[rider] anchors on the mesh: height corrections {diff}")
    return fixed, diff


def pose(rig, A):
    """Seat the rider: hips over SEAT_ANCHOR, two-bone IK (computed here) for legs and arms, torso lean, head back
    level, fingers curled. Pose-bone matrices are in armature space (the rig sits at the origin)."""
    for o in bpy.context.selected_objects:
        o.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='POSE')
    inv = rig.matrix_world.inverted()
    pb = rig.pose.bones
    upd = bpy.context.view_layer.update

    def rotate(n, R):
        b = pb[n]
        h = b.head.copy()
        b.matrix = Matrix.Translation(h) @ R.to_4x4() @ Matrix.Translation(-h) @ b.matrix
        upd()

    def aim(n, target):
        b = pb[n]
        d0 = (b.tail - b.head).normalized()
        d1 = (target - b.head).normalized()
        rotate(n, d0.rotation_difference(d1).to_matrix())

    def two_bone(upper, lower, target, pole):
        S = pb[upper].head.copy()
        l1 = (pb[upper].tail - pb[upper].head).length
        l2 = (pb[lower].tail - pb[lower].head).length
        d = target - S
        L = min(max(d.length, 1e-3), l1 + l2 - 1e-4)
        dn = d.normalized()
        pv = pole - S
        pv = (pv - dn * pv.dot(dn)).normalized()
        a = (l1 * l1 - l2 * l2 + L * L) / (2 * L)
        K = S + dn * a + pv * math.sqrt(max(l1 * l1 - a * a, 0.0))
        aim(upper, K)
        aim(lower, S + dn * L)
        return d.length - (l1 + l2)                        # > 0: target out of reach by this much

    def wrist_target(S, sx):
        return A[f'HAND_{S}'] + Vector((-WRIST_FROM_GRIP[0] * sx, WRIST_FROM_GRIP[1], WRIST_FROM_GRIP[2]))

    # hips
    hips = (pb['thigh_l'].head + pb['thigh_r'].head) / 2
    target = inv @ (A['SEAT_ANCHOR'] + Vector(HIP_ABOVE_SEAT))
    M = pb['pelvis'].matrix.copy()
    M.translation += target - hips
    pb['pelvis'].matrix = M
    upd()
    # torso lean forward (top towards -y), head level again
    lean = math.radians(LEAN_DEG)
    rotate('spine_01', Matrix.Rotation(lean, 3, 'X'))
    rotate('neck_01', Matrix.Rotation(-lean * 0.6, 3, 'X'))
    rotate('head', Matrix.Rotation(-lean * 0.4, 3, 'X'))
    reach = {}
    for side, sx in (('l', 1.0), ('r', -1.0)):
        S = 'L' if side == 'l' else 'R'
        # legs: ankle over the floorboard, knees forward / slightly out
        ankle = inv @ (A[f'FOOT_{S}'] + Vector(ANKLE_FROM_FOOT))
        hip = pb[f'thigh_{side}'].head.copy()
        pole = (hip + ankle) / 2 + Vector((KNEE_POLE[0] * sx, KNEE_POLE[1], KNEE_POLE[2]))
        reach[f'leg_{side}'] = two_bone(f'thigh_{side}', f'calf_{side}', ankle, pole)
        f = pb[f'foot_{side}']
        aim(f'foot_{side}', f.head + Vector(FOOT_DIR).normalized() * (f.tail - f.head).length)
        # arms: wrist just behind / inside the grip, elbows out, down and back
        wrist = inv @ wrist_target(S, sx)
        sh = pb[f'upperarm_{side}'].head.copy()
        pole = (sh + wrist) / 2 + Vector((ELBOW_POLE[0] * sx, ELBOW_POLE[1], ELBOW_POLE[2]))
        reach[f'arm_{side}'] = two_bone(f'upperarm_{side}', f'lowerarm_{side}', wrist, pole)
        # fingers round the grip
        for fn in ('index', 'middle', 'ring', 'pinky'):
            for k in ('01', '02', '03'):
                b = pb[f'{fn}_{k}_{side}']
                b.rotation_mode = 'XYZ'
                b.rotation_euler[0] = math.radians(FINGER_CURL_DEG)
        upd()
    bpy.ops.object.mode_set(mode='OBJECT')
    # how close the joints ended up to their targets
    err = {}
    for side, S, sx in (('l', 'L', 1.0), ('r', 'R', -1.0)):
        err[f'ankle_{side}'] = round(((rig.matrix_world @ pb[f'foot_{side}'].head) - (A[f'FOOT_{S}'] + Vector(ANKLE_FROM_FOOT))).length, 4)
        err[f'wrist_{side}'] = round(((rig.matrix_world @ pb[f'hand_{side}'].head) - wrist_target(S, sx)).length, 4)
    hips = rig.matrix_world @ ((pb['thigh_l'].head + pb['thigh_r'].head) / 2)
    err['hips'] = round((hips - (A['SEAT_ANCHOR'] + Vector(HIP_ABOVE_SEAT))).length, 4)
    print(f"[rider] pose: reach (m, >0 = short) {dict((k, round(v, 3)) for k, v in reach.items())}, joint errors {err}")
    return dict(reach={k: round(v, 4) for k, v in reach.items()}, joint_error=err)


def freeze(objs, coll):
    """Posed, masked, shape-keyed objects -> plain static meshes (world space) in coll."""
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for o in objs:
        ev = o.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
        me.transform(o.matrix_world)
        name = o.name.split('.')[-1] if '.' in o.name else o.name
        ob = bpy.data.objects.new("Rider_" + name, me)
        coll.objects.link(ob)
        out.append(ob)
    return out


def reduce(ob, target):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    for _ in range(4):
        n = tris_of(ob)
        if n <= target * 1.05:
            break
        dm = ob.modifiers.new("decimate", 'DECIMATE')
        dm.decimate_type, dm.ratio = 'COLLAPSE', target / n
        bpy.ops.object.modifier_apply(modifier=dm.name)


def cull_hidden(objs):
    """Delete every face that cannot be seen from outside: CULL_RAYS rays from the face (normal + a cone around it)
    are all blocked by the rider itself (body under the clothes, scalp under the helmet, feet in the shoes,
    helmet liner...)."""
    verts, polys, off = [], [], 0
    for o in objs:
        verts += [v.co.copy() for v in o.data.vertices]
        polys += [[off + i for i in p.vertices] for p in o.data.polygons]
        off += len(o.data.vertices)
    tree = BVHTree.FromPolygons(verts, polys)
    rng = np.random.default_rng(3)
    cone = [Vector((0, 0, 1))]                              # fixed directions in the face frame (z = normal)
    for k in range(1, CULL_RAYS):
        a = 2 * math.pi * k / (CULL_RAYS - 1)
        t = math.radians(CULL_CONE_DEG) * (0.5 + 0.5 * rng.random())
        cone.append(Vector((math.sin(t) * math.cos(a), math.sin(t) * math.sin(a), math.cos(t))))
    report = {}
    for o in objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        hidden = []
        for f in bm.faces:
            n = f.normal
            if n.length < 0.5:
                continue
            R = n.to_track_quat('Z', 'Y').to_matrix()
            c = f.calc_center_median() + n * 0.003
            if all(tree.ray_cast(c, R @ d, 5.0)[0] is not None for d in cone):
                hidden.append(f)
        before = len(bm.faces)
        bmesh.ops.delete(bm, geom=hidden, context='FACES')
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bm.to_mesh(o.data)
        bm.free()
        report[o.name] = dict(faces_before=before, hidden=len(hidden), tris_after=tris_of(o))
    print(f"[rider] culled hidden faces: {report}")
    return report


def import_moto(coll):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=MOTO_FBX)
    new = [o for o in bpy.data.objects if o not in before]
    keep = [o for o in new if o.type == 'MESH' and o.name.endswith('_LOD0')]
    for o in keep:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
        o.name = "Moto_SH_ref"
    for o in new:
        if o not in keep:
            bpy.data.objects.remove(o)
    return keep


def penetration(rider, moto):
    """Rider vertices inside the bike (behind its surface along its normal) and how deep."""
    dg = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(moto, dg)
    out = {}
    for o in rider:
        inside, depth, where = 0, 0.0, None
        for v in o.data.vertices:
            hit = tree.find_nearest(v.co, 0.1)
            if hit[0] is not None and (v.co - hit[0]).dot(hit[1]) < 0:
                inside += 1
                if hit[3] > depth:
                    depth, where = hit[3], [round(c, 3) for c in v.co]
        if inside:
            out[o.name] = dict(verts_inside=inside, max_depth=round(depth, 4), deepest_at=where)
    return out


POSE_JSON = os.path.join(RIDER_DIR, "rider_pose.json")
RIG_NAME = "RiderRig"


def save_pose(rig):
    """The rig's pose (local matrix_basis of every bone) -> rider_pose.json, so rebuilds keep a hand-made pose."""
    data = {b.name: [list(r) for r in b.matrix_basis] for b in rig.pose.bones}
    with open(POSE_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"[rider] pose saved: {POSE_JSON} ({len(data)} bones)")


def load_pose(rig):
    data = json.load(open(POSE_JSON, encoding="utf-8"))
    for b in rig.pose.bones:
        if b.name in data:
            b.matrix_basis = Matrix(data[b.name])
    bpy.context.view_layer.update()
    print(f"[rider] pose loaded from {POSE_JSON}")
    return dict(source=os.path.basename(POSE_JSON))


def freeze_and_check(report):
    """RIDER_RIG (posed, rigged) -> RIDER_POSED static meshes (hidden in the viewport): helmet pre-reduced, polo
    pushed out, hidden faces culled; penetration into the bike, report, preview, the pose saved to rider_pose.json."""
    rig = bpy.data.objects[RIG_NAME]
    src = [o for o in bpy.data.collections["RIDER_RIG"].objects if o.type == 'MESH']
    old = bpy.data.collections.get("RIDER_POSED")
    if old:
        for o in list(old.objects):
            bpy.data.objects.remove(o)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new("RIDER_POSED")
    bpy.context.scene.collection.children.link(coll)
    order = sorted(src, key=lambda o: ('Helmet' in o.name, o.name))
    rider = freeze(order, coll)
    for m in [m for m in bpy.data.meshes if m.users == 0]:
        bpy.data.meshes.remove(m)
    helmet = next(o for o in rider if o.name.endswith("Helmet"))
    reduce(helmet, HELMET_PRE_TRIS)
    polo = next(o for o in rider if 'Polo' in o.name)
    for v in polo.data.vertices:                        # keep the trousers' waistband under the shirt
        v.co += v.normal * POLO_INFLATE
    culled = cull_hidden(rider)
    moto = [o for o in bpy.data.collections["MOTO_REF"].objects if o.type == 'MESH']
    pen = penetration(rider, moto[0]) if moto else None
    report.update(culled=culled, penetration=pen, tris={o.name: tris_of(o) for o in rider})
    report['tris']['total'] = sum(report['tris'].values())
    with open(os.path.join(RIDER_DIR, "rider_r2.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(f"[rider] tris {report['tris']}; penetration {pen}")
    save_pose(rig)
    coll.hide_viewport = True                           # the user works on RIDER_RIG; RIDER_POSED renders
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    c = (0, 0, 0.8)
    sheet("rider_r2", rider + moto, [((7, 0, 0.8), c, 2.3), ((-4, -5, 2.2), c, 2.3), ((4, 5, 2.4), c, 2.3),
                                       ((0, -7, 0.9), c, 2.3)], res=(800, 800))


def build(auto_pose=False):
    """R1 + R2. The rig stays (collection RIDER_RIG) so the pose can be edited by hand in Pose Mode, then
    `-- --freeze` rebuilds RIDER_POSED from it. A saved rider_pose.json is re-used unless auto_pose."""
    bpy.ops.wm.read_homefile(use_empty=True)
    os.makedirs(RIDER_DIR, exist_ok=True)
    hs, human, hmacro = make_human()
    height = body_height(human)
    skin(human)
    rig = hs.add_builtin_rig(human, RIG)
    rig.name = RIG_NAME
    clothes = dress(hs, human)
    bw_shoes(clothes[2])
    hel, fit = load_helmet(human)
    attach_helmet(hel, rig)
    ref = bpy.data.collections.new("MOTO_REF")
    bpy.context.scene.collection.children.link(ref)
    moto = import_moto(ref)
    anchors, anchor_fix = mesh_anchors(moto[0])
    if os.path.exists(POSE_JSON) and not auto_pose:
        posing = load_pose(rig)
    else:
        posing = pose(rig, anchors)
    posing['anchor_height_fix'] = anchor_fix
    coll = bpy.data.collections.new("RIDER_RIG")
    bpy.context.scene.collection.children.link(coll)
    for o in [human, rig, hel] + clothes:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    report = dict(height=round(height, 3), height_macro=round(hmacro, 4), helmet=fit, pose=posing,
                  credits=hanoi_rider.CREDITS)
    freeze_and_check(report)


def freeze_only():
    """After a hand edit of the pose in HanoiRider.blend: rebuild RIDER_POSED from RIDER_RIG."""
    path = os.path.join(RIDER_DIR, "rider_r2.json")
    report = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    report['pose'] = dict(source='hand edit in HanoiRider.blend')
    freeze_and_check(report)


# ------------------------------------------------------------------ R3: reduce, bake, LODs, export
EXPORT_DIR = os.path.join(ROOT, "Export", "Vehicles")


def part_key(name):
    return next(k for k in PART_TRIS if k in name)


def face_islands(bm):
    """Connected face sets (by shared edges)."""
    seen, out = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        seen.add(f)
        stack, comp = [f], []
        while stack:
            g = stack.pop()
            comp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in seen:
                        seen.add(h)
                        stack.append(h)
        out.append(comp)
    return out


def drop_small_islands(me, frac):
    """Delete the loose pieces whose area is under `frac` of the mesh's area."""
    bm = bmesh.new()
    bm.from_mesh(me)
    islands = [(sum(x.calc_area() for x in comp), comp) for comp in face_islands(bm)]
    total = sum(a for a, _ in islands)
    gone = [f for a, comp in islands if a < frac * total for f in comp]
    bmesh.ops.delete(bm, geom=gone, context='FACES')
    bm.to_mesh(me)
    bm.free()
    return len(islands) - sum(1 for a, _ in islands if a < frac * total)


def convex_hulls(me, mode):
    """The mesh replaced by closed, decimatable convex hulls: one per side (mode 'side', x < 0 / x > 0: the shoes)
    or one per loose piece (mode 'island')."""
    src = bmesh.new()
    src.from_mesh(me)
    if mode == 'side':
        groups = [[v.co.copy() for v in src.verts if v.co.x * s > 0] for s in (-1, 1)]
    else:
        groups = [[v.co.copy() for v in {v for f in comp for v in f.verts}] for comp in face_islands(src)]
    src.free()
    bm = bmesh.new()
    for pts in groups:
        if len(pts) < 4:
            continue
        vs = [bm.verts.new(c) for c in pts]
        res = bmesh.ops.convex_hull(bm, input=vs)
        gone = {v for v in res['geom_interior'] + res['geom_unused'] if isinstance(v, bmesh.types.BMVert)}
        bmesh.ops.delete(bm, geom=list(gone), context='VERTS')
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()


def r3():
    """RIDER_POSED (frozen pose, hidden faces culled) -> SM_Rider_M LOD0 (~1.5k, per-part symmetric decimate) and
    LOD1 (~500), one 512 atlas baked from the posed sources: T_RiderM (albedo, shirt neutral grey), T_RiderMData
    (R rough, G metal, B 0, A shirt mask -> Hanoi/Vehicle _PaintMaskMode). FBX + vehicles.json entry."""
    import hanoi_common
    srcs = [o for o in bpy.data.collections["RIDER_POSED"].objects if o.type == 'MESH']
    old = bpy.data.collections.get("RIDER_EXPORT")
    if old:
        for o in list(old.objects):
            bpy.data.objects.remove(o)
        bpy.data.collections.remove(old)
    coll = bpy.data.collections.new("RIDER_EXPORT")
    bpy.context.scene.collection.children.link(coll)
    bpy.data.collections["RIDER_POSED"].hide_viewport = False
    # 1) LOD0: every part decimated on its own, then joined; slot attribute = part (for masks)
    keys = list(PART_TRIS)
    parts = []
    for o in srcs:
        k = part_key(o.name)
        me = o.data.copy()
        me.materials.clear()
        c = bpy.data.objects.new("tmp_" + k, me)
        coll.objects.link(c)
        for x in bpy.context.selected_objects:
            x.select_set(False)
        c.select_set(True)
        bpy.context.view_layer.objects.active = c
        bpy.ops.object.mode_set(mode='EDIT')               # weld split seams so the collapse can work
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.0005)
        bpy.ops.object.mode_set(mode='OBJECT')
        if k in MIN_ISLAND:
            print(f"[rider] {k}: {drop_small_islands(c.data, MIN_ISLAND[k])} pieces kept")
        if k in HULL_PARTS:
            convex_hulls(c.data, HULL_PARTS[k])
        for _ in range(8):
            n = tris_of(c)
            if n <= PART_TRIS[k] * 1.05:
                break
            dm = c.modifiers.new("d", 'DECIMATE')
            dm.decimate_type, dm.ratio = 'COLLAPSE', max(PART_TRIS[k] / n, 0.05)
            bpy.ops.object.modifier_apply(modifier=dm.name)
        print(f"[rider] {k}: {tris_of(c)} tris")
        a = c.data.attributes.new('part', 'INT', 'FACE')
        a.data.foreach_set('value', [keys.index(k)] * len(c.data.polygons))
        parts.append(c)
    for x in bpy.context.selected_objects:
        x.select_set(False)
    for c in parts:
        c.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    lod0 = bpy.context.view_layer.objects.active
    lod0.name = lod0.data.name = f"{NAME}_LOD0"
    for uv in list(lod0.data.uv_layers):
        lod0.data.uv_layers.remove(uv)
    lod0.data.uv_layers.new(name="UVMap")
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(45))
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.01, area_weight=1.0)
    bpy.ops.object.mode_set(mode='OBJECT')

    # 2) bakes from the posed sources (selected to active): albedo (diffuse colour) and the shirt mask (emission)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device, sc.cycles.samples = 'CPU', 4
    tgt = bpy.data.materials.new("M_RiderBake")
    tgt.use_nodes = True
    tex = tgt.node_tree.nodes.new('ShaderNodeTexImage')
    tgt.node_tree.nodes.active = tex
    lod0.data.materials.append(tgt)

    def new_img(name, data=False):
        if name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[name])
        im = bpy.data.images.new(name, ATLAS_RES, ATLAS_RES, alpha=True)
        if data:
            im.colorspace_settings.name = 'Non-Color'
        return im

    def bake(img, **kw):
        tex.image = img
        for x in bpy.context.selected_objects:
            x.select_set(False)
        for o in srcs:
            o.select_set(True)
        lod0.select_set(True)
        bpy.context.view_layer.objects.active = lod0
        bpy.ops.object.bake(use_selected_to_active=True, cage_extrusion=BAKE_CAGE, max_ray_distance=3 * BAKE_CAGE,
                            margin=BAKE_MARGIN, **kw)

    alb = new_img("T_RiderM")
    bake(alb, type='DIFFUSE', pass_filter={'COLOR'})
    keep = {o.name: [s.material for s in o.material_slots] for o in srcs}

    def bake_values(name, value_of):
        """Every source material slot emits a flat value (value_of(part key, material name)) -> baked into a data
        image (R channel)."""
        em = {}
        for o in srcs:
            for s in o.material_slots:
                v = float(value_of(part_key(o.name), s.material.name if s.material else ""))
                if v not in em:
                    m = bpy.data.materials.new(f"E_{name}_{v}")
                    m.use_nodes = True
                    nt = m.node_tree
                    for n in list(nt.nodes):
                        nt.nodes.remove(n)
                    e = nt.nodes.new('ShaderNodeEmission')
                    e.inputs['Color'].default_value = (v, v, v, 1)
                    nt.links.new(e.outputs[0], nt.nodes.new('ShaderNodeOutputMaterial').inputs['Surface'])
                    em[v] = m
                s.material = em[v]
        img = new_img(name, data=True)
        bake(img, type='EMIT')
        for o in srcs:
            for s, m in zip(o.material_slots, keep[o.name]):
                s.material = m
        return np.array(img.pixels[:], dtype=np.float32).reshape(ATLAS_RES, ATLAS_RES, 4)[..., 0]

    M = bake_values("T_RiderMask", lambda k, m: k == 'Polo')
    H = bake_values("T_RiderHelmetMask", lambda k, m: k == 'Helmet' and m == hanoi_rider.HELMET_SHELL_MATERIAL)
    rough = bake_values("T_RiderRough", lambda k, m: ROUGHNESS[k])
    # 3) textures: shirt + helmet shell neutral grey (keep their shading), data map (R rough, B helmet, A shirt mask)
    A = np.array(alb.pixels[:], dtype=np.float32).reshape(ATLAS_RES, ATLAS_RES, 4)
    lum = A[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    for mask, target in ((M, SHIRT_GREY), (H, HELMET_GREY)):
        # the byte image holds sRGB values: the median goes to the grey as stored (0.8 = 0.604 linear in Unity)
        sel = mask > 0.5
        scale = target / max(float(np.median(lum[sel])) if sel.any() else target, 1e-4)
        grey = np.clip(lum * scale, 0, 1)
        A[..., :3] = np.where(sel[..., None], grey[..., None], A[..., :3])
    shirt = M > 0.5
    A[..., 3] = 1.0
    alb.pixels.foreach_set(A.ravel())
    D = np.zeros_like(A)
    D[..., 0] = rough
    D[..., 2] = H
    D[..., 3] = M
    data = new_img("T_RiderMData", data=True)
    data.pixels.foreach_set(D.ravel())
    for im, fn in ((alb, "T_RiderM.png"), (data, "T_RiderMData.png")):
        im.filepath_raw = os.path.join(RIDER_DIR, fn)
        im.file_format = 'PNG'
        im.save()
    # 4) material for the FBX (Unity remaps it to Hanoi/Vehicle)
    mat = bpy.data.materials.get("M_RiderM") or bpy.data.materials.new("M_RiderM")
    mat.use_nodes = True
    bs = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    for n in [n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE']:   # from an earlier run
        mat.node_tree.nodes.remove(n)
    ti = mat.node_tree.nodes.new('ShaderNodeTexImage')
    ti.image = alb
    mat.node_tree.nodes.active = ti                     # the workbench preview shows the active image node
    mat.node_tree.links.new(ti.outputs['Color'], bs.inputs['Base Color'])
    lod0.data.materials.clear()
    lod0.data.materials.append(mat)
    # 5) LOD1: every part of LOD0 decimated on its own to its share of LOD1_TRIS (a collapse of the joined mesh
    # pulled spikes out of the sleeves), UVs kept, then joined
    share = LOD1_TRIS / sum(PART_TRIS.values())
    pieces = []
    for i, k in enumerate(keys):
        me1 = lod0.data.copy()
        bm = bmesh.new()
        bm.from_mesh(me1)
        lay = bm.faces.layers.int['part']
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f[lay] != i], context='FACES')
        bm.to_mesh(me1)
        bm.free()
        p = bpy.data.objects.new(f"tmp1_{k}", me1)
        coll.objects.link(p)
        for x in bpy.context.selected_objects:
            x.select_set(False)
        p.select_set(True)
        bpy.context.view_layer.objects.active = p
        for _ in range(5):
            n = tris_of(p)
            if n <= PART_TRIS[k] * share * 1.05:
                break
            dm = p.modifiers.new("d", 'DECIMATE')
            dm.decimate_type, dm.ratio = 'COLLAPSE', max(PART_TRIS[k] * share / n, 0.05)
            bpy.ops.object.modifier_apply(modifier=dm.name)
        print(f"[rider] LOD1 {k}: {tris_of(p)} tris")
        pieces.append(p)
    for x in bpy.context.selected_objects:
        x.select_set(False)
    for p in pieces:
        p.select_set(True)
    bpy.context.view_layer.objects.active = pieces[0]
    bpy.ops.object.join()
    lod1 = bpy.context.view_layer.objects.active
    lod1.name = lod1.data.name = f"{NAME}_LOD1"
    for o in (lod0, lod1):
        if 'part' in o.data.attributes:
            o.data.attributes.remove(o.data.attributes['part'])
    root = bpy.data.objects.new(NAME, None)
    coll.objects.link(root)
    for o in (lod0, lod1):
        o.parent = root
    bpy.data.collections["RIDER_POSED"].hide_viewport = True
    # 6) export + report
    os.makedirs(os.path.join(EXPORT_DIR, "FBX"), exist_ok=True)
    os.makedirs(os.path.join(EXPORT_DIR, "Textures"), exist_ok=True)
    import shutil
    for fn in ("T_RiderM.png", "T_RiderMData.png"):
        shutil.copy2(os.path.join(RIDER_DIR, fn), os.path.join(EXPORT_DIR, "Textures", fn))
    hanoi_common.export_fbx(os.path.join(EXPORT_DIR, "FBX", f"{NAME}.fbx"), [root], zero_roots=True)
    lo = min(v.co.z for v in lod0.data.vertices)
    rep = dict(name=NAME, tris={'LOD0': tris_of(lod0), 'LOD1': tris_of(lod1)},
               units='metres, Unity axes; origin = the SM_Moto_SH origin (ground, wheelbase midpoint): make it a child '
                     'of the bike with no offset',
               lowest_point=round(lo, 4),
               material='Hanoi/Vehicle, _PaintMaskMode 2: _BaseMap T_RiderM.png (shirt + helmet shell baked grey 0.8), '
                        '_DataMap T_RiderMData.png (R rough, G metal, B helmet mask -> _PaintColor2, A shirt mask -> '
                        '_PaintColor)',
               shirt_colours_srgb=SHIRT_COLOURS, helmet_colours_srgb=HELMET_COLOURS, rides=MOTO_ID,
               credits=hanoi_rider.CREDITS)
    hanoi_common.write_vehicle(EXPORT_DIR, rep)
    with open(os.path.join(RIDER_DIR, "rider_r3.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    print(f"[rider] R3 {rep['tris']}, shirt texels {shirt.mean() * 100:.1f} %, lowest z {lo:.3f}")
    bpy.ops.wm.save_as_mainfile(filepath=BLEND, compress=True)
    moto = [o for o in bpy.data.collections["MOTO_REF"].objects if o.type == 'MESH']
    lod1.location.x = 1.6
    c = (0.8, 0, 0.8)
    sheet("rider_r3", [lod0, lod1] + moto, [((0.8, -7, 1.6), c, 3.4), ((7.8, 0, 0.9), c, 3.4), ((-4, 6, 2.0), c, 3.4)],
          res=(900, 700))
    lod1.location.x = 0.0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--r3" in argv:                          # blender -b Blender/HanoiRider.blend --python build_rider.py -- --r3
        r3()
    if "--build" in argv:                       # blender -b --python build_rider.py -- --build [--auto-pose]
        build(auto_pose="--auto-pose" in argv)
    elif "--freeze" in argv:                    # blender -b Blender/HanoiRider.blend --python build_rider.py -- --freeze
        freeze_only()
