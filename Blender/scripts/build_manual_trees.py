"""Plan TM: leaf cards ("particles"), textures and LODs for the hand-made trees of
Blender/ManualSculptedTree.blend (bezier curves = trunk + branches, sphere meshes = sculpted canopy lobes).

Step A, in the open Blender (MCP):
    exec(open(r"D:/Project III/BuildingGenerate/Blender/scripts/build_manual_trees.py", encoding="utf-8").read(),
         {"__name__": "__main__"})
  Per tree a collection TR_<Species>_0 (laid out at x = LAYOUT_X, one tree every SPACING m along y):
    TR_X_0_Work             root empty of the editable step-A objects (foot of the trunk)
    TR_X_0_Trunk_LOD0       swept tube mesh from the curve (bark UV: u around, v = length / 2 m)
    TR_X_0_Leaves_LOD0      voxel union of the sculpted lobes carrying two LIVE modifiers:
                              HN_LeafScatter (geometry nodes "particles": Density, Spacing, Card Size,
                              Size Random, Inset, Inset Share, Depth Scale, Seed) and
                              NormalTransfer (Data Transfer, custom normals from the shell)
    TR_X_0_NormalShell      hidden: the union smoothed hard + inflated (soft "spherical" normals)
  Vertex colour 'Col' on the leaves: R random per card, G depth in the crown (1 = outside), B height.
  Then a copy of the file is rendered in the background next to a 4-floor tube house:
    Blender/previews/trees_manual_A_sun.png
Step B, in the open Blender (MCP), after the user tuned the HN_LeafScatter sliders:
    exec(open(...).read(), {"__name__": "__main__", "STEP": "B"})
  Bakes the live leaves (+ two re-evaluations with fewer, larger cards for LOD1), builds trunks per LOD
  and the LOD2 blob (NormalShell decimated, vertex-coloured), merges trunk + foliage into ONE mesh per
  LOD (2 materials, custom normals kept), under the export root TR_X_0 (at x = LAYOUT_X + 16; LOD1/2
  shown 14 / 28 m further on, snapped back on export):
    TR_X_0 -> TR_X_0_LOD0 / _LOD1 / _LOD2
  Exports Export/Trees/FBX/TR_X_0.fbx + Export/Trees/trees.json, saves the .blend, renders
  Blender/previews/trees_manual_B_<Species>_sun.png and re-imports the FBX to check them.
Background helpers (called by the steps):
    blender -b <copy.blend> --python build_manual_trees.py -- --preview A|B
    blender -b --factory-startup --python build_manual_trees.py -- --verify

The user's curves and lobes are never edited; they are only moved into the collection 'Source'.
Scale: every tree is scaled about its foot so that trunk + crown reach TARGET_H.
"""
import os, sys, math, json, importlib, subprocess, tempfile
import bpy, bmesh
import numpy as np
from mathutils import Vector, Matrix

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_common, hanoi_tree
importlib.reload(hanoi_common)
importlib.reload(hanoi_tree)
from hanoi_common import collection, clear_collection, empty
from hanoi_tree import bezier_samples, tube_mesh, bake

BLEND = os.path.join(ROOT, "Blender", "ManualSculptedTree.blend")
TEX = os.path.join(ROOT, "Export", "Textures", "Trees")
PREVIEW_DIR = os.path.join(ROOT, "Blender", "previews")
BLENDER_EXE = r"D:\Blender Foundation\Blender 5.2\blender.exe"
PREVIEW_COPY = os.path.join(tempfile.gettempdir(), "hanoi_manual_trees_preview.blend")

# curve object of the user's file -> species (left to right in the user's view: sau, xa cu, bang, hoa sua)
TREES = [('tree', 'Sau'), ('tree.001', 'XaCu'), ('tree.002', 'Bang'), ('tree.004', 'HoaSua')]
LOBE_COLLECTION = 'Collection'                   # where the user's sculpted lobes live
TARGET_H = {'Sau': 14.0, 'XaCu': 15.0, 'Bang': 12.0, 'HoaSua': 13.0}   # m, foot to crown top
TRUNK_R = {'Sau': 1.0, 'XaCu': 1.0, 'Bang': 1.6, 'HoaSua': 1.3}        # extra radius factor after scaling
LAYOUT_X, SPACING = 30.0, 22.0
# lower-left UV corner of each species cell in T_Foliage.png (2x2; see build_tree_textures.CELL_POS)
CELL_UV = {'Sau': (0.0, 0.5), 'XaCu': (0.5, 0.5), 'Bang': (0.0, 0.0), 'HoaSua': (0.5, 0.0)}

VOXEL = 0.16                 # m: union remesh of the lobes (keeps the sculpted lumps)
CANOPY_TRIS = 8000           # scatter surface after decimation
TRI_BUDGET = (6000, 2000, 400)
CARD_TRIS = 4                # 2 crossed quads
CARD_SIZE = 1.15             # m, LOD0 card edge
TRUNK_SIDES = (8, 5, 4)      # LOD0 sides by branch level


# ---------------------------------------------------------------- source
def source():
    """[(species, curve, [lobes])]; lobes assigned to the curve whose foot is nearest in XY.
    Moves the user's objects into collection 'Source' (no edit of their data)."""
    curves = [(bpy.data.objects[c], sp) for c, sp in TREES]
    lobes = [o for o in bpy.data.objects if o.type == 'MESH' and any(
        c.name == LOBE_COLLECTION or c.name == 'Source' for c in o.users_collection) and not o.name.startswith('TR_')]
    src = collection('Source')
    lc = bpy.data.collections.get(LOBE_COLLECTION)
    if lc is not None and lc.name not in src.children:
        for parent in [bpy.context.scene.collection] + list(bpy.data.collections):
            if lc.name in parent.children:
                parent.children.unlink(lc)
        src.children.link(lc)
    for cu, _ in curves:
        if src not in cu.users_collection:
            for c in list(cu.users_collection):
                c.objects.unlink(cu)
            src.objects.link(cu)
    out = []
    for cu, sp in curves:
        foot = cu.matrix_world.translation
        mine = [o for o in lobes if min(curves, key=lambda c: (c[0].matrix_world.translation.xy -
                                                              o.matrix_world.translation.xy).length)[0] is cu]
        out.append((sp, cu, mine))
    return out


def tree_frame(sp, cu, lobes):
    """Matrix world -> tree space (foot at origin, scaled to TARGET_H) and the scale."""
    mw = cu.matrix_world
    foot = mw @ max(cu.data.splines, key=lambda s: s.bezier_points[0].radius).bezier_points[0].co
    top = max(max((mw @ p.co).z for s in cu.data.splines for p in s.bezier_points),
              max((o.matrix_world @ Vector(c)).z for o in lobes for c in o.bound_box))
    s = TARGET_H[sp] / (top - foot.z)
    return Matrix.Scale(s, 4) @ Matrix.Translation(-foot), s


def branches_of(cu, M, s, sp):
    """Curve splines -> hanoi_tree branch dicts (pts, rs, level) in tree space."""
    mw = cu.matrix_world
    k = s * TRUNK_R[sp] * max(cu.data.bevel_depth, 1e-6) * mw.to_scale().x
    rmax = max(spl.bezier_points[0].radius for spl in cu.data.splines)
    out = []
    for spl in cu.data.splines:
        r0 = spl.bezier_points[0].radius
        level = 0 if r0 > 0.55 * rmax else 1 if r0 > 0.2 * rmax else 2
        pts, rs = bezier_samples(spl, (3, 2, 1)[level])
        out.append(dict(pts=[M @ (mw @ p) for p in pts], rs=[r * k for r in rs], level=level))
    return out


def lobe_union(name, lobes, M, col):
    """Sculpted lobes (world) -> tree space -> voxel union -> light smooth -> decimate."""
    verts, faces = [], []
    for o in lobes:
        T = M @ o.matrix_world
        base = len(verts)
        verts += [T @ v.co for v in o.data.vertices]
        faces += [[base + i for i in p.vertices] for p in o.data.polygons]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    m = ob.modifiers.new("Remesh", 'REMESH')
    m.mode = 'VOXEL'; m.voxel_size = VOXEL; m.adaptivity = 0.0
    m = ob.modifiers.new("Smooth", 'SMOOTH'); m.factor = 0.5; m.iterations = 2
    bake(ob)
    m = ob.modifiers.new("Decimate", 'DECIMATE')
    m.ratio = min(1.0, CANOPY_TRIS / max(1, len(ob.data.polygons) * 2))
    bake(ob)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def normal_shell(name, canopy, col):
    """Canopy smoothed hard and inflated by 5% of the crown radius: source of the soft leaf normals."""
    ob = bpy.data.objects.new(name, canopy.data.copy())
    col.objects.link(ob)
    co = np.array([v.co for v in ob.data.vertices])
    crown_r = float(np.ptp(co[:, :2], 0).mean() / 2)
    m = ob.modifiers.new("Smooth", 'SMOOTH'); m.factor = 1.0; m.iterations = 25
    m = ob.modifiers.new("Inflate", 'DISPLACE'); m.mid_level = 0.0; m.strength = 0.05 * crown_r
    bake(ob)
    for p in ob.data.polygons:
        p.use_smooth = True
    ob.hide_render = True
    ob.hide_set(True)
    return ob, crown_r


# ---------------------------------------------------------------- leaf cards
def card_object(sp, col, mat):
    """Unit leaf card: a quad tangent to the crown (local XY) + one along the normal (local XZ),
    UVs inside the species cell of the atlas. Scaled per instance by the scatter node group.
    Carries M_Foliage itself: realized instances keep the card's material, not the crown's."""
    name = f"HN_LeafCard_{sp}"
    ob = bpy.data.objects.get(name)
    if ob is not None:
        bpy.data.objects.remove(ob, do_unlink=True)
    u0, v0 = CELL_UV[sp]
    h = 0.5
    quads = [[(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)],
             [(-h, 0, -h), (h, 0, -h), (h, 0, h), (-h, 0, h)]]
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    for q in quads:
        f = bm.faces.new([bm.verts.new(p) for p in q])
        f.smooth = True
        for loop, (a, b) in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
            loop[uv].uv = (u0 + 0.5 * a, v0 + 0.5 * b)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    ob.hide_render = True
    ob.hide_set(True)
    return ob


def _in(node, name, typ=None):
    return next(s for s in node.inputs if s.name == name and s.enabled and (typ is None or s.type == typ))


def _out(node, name, typ=None):
    return next(s for s in node.outputs if s.name == name and s.enabled and (typ is None or s.type == typ))


def leaf_scatter_group():
    """HN_LeafScatter: Poisson points on the crown -> optional inset -> card instances aligned to the
    surface normal with a random spin -> realized; vertex colour 'Col' (R random, G depth, B height)."""
    ng = bpy.data.node_groups.get("HN_LeafScatter")
    if ng is not None:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new("HN_LeafScatter", 'GeometryNodeTree')
    io = ng.interface
    io.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    specs = [("Card", 'NodeSocketObject', None), ("Shell", 'NodeSocketObject', None),
             ("Density", 'NodeSocketFloat', 4.0), ("Spacing", 'NodeSocketFloat', 0.35),
             ("Card Size", 'NodeSocketFloat', CARD_SIZE), ("Size Random", 'NodeSocketFloat', 0.2),
             ("Tilt", 'NodeSocketFloat', 0.35), ("Inset", 'NodeSocketFloat', 0.6),
             ("Inset Share", 'NodeSocketFloat', 0.15), ("Depth Scale", 'NodeSocketFloat', 1.2),
             ("Seed", 'NodeSocketInt', 0)]
    for nm, typ, dv in specs:
        s = io.new_socket(nm, in_out='INPUT', socket_type=typ)
        if dv is not None:
            s.default_value = dv
    io.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    N, L = ng.nodes, ng.links
    gi = N.new('NodeGroupInput'); go = N.new('NodeGroupOutput')

    def op(operation, a, b):
        n = N.new('ShaderNodeMath'); n.operation = operation
        for sock, v in zip(n.inputs, (a, b)):
            if isinstance(v, (int, float)):
                sock.default_value = v
            else:
                L.new(v, sock)
        return n.outputs[0]

    def rnd(kind, lo, hi, seed_off):
        """Random Value output; for BOOLEAN, `lo` is the probability socket."""
        n = N.new('FunctionNodeRandomValue'); n.data_type = kind
        if kind == 'BOOLEAN':
            L.new(lo, _in(n, 'Probability'))
        else:
            t = 'VECTOR' if kind == 'FLOAT_VECTOR' else 'VALUE'
            _in(n, 'Min', t).default_value = lo
            _in(n, 'Max', t).default_value = hi
        L.new(op('ADD', gi.outputs['Seed'], seed_off), _in(n, 'Seed'))
        return _out(n, 'Value')

    dist = N.new('GeometryNodeDistributePointsOnFaces'); dist.distribute_method = 'POISSON'
    L.new(gi.outputs['Geometry'], _in(dist, 'Mesh'))
    L.new(gi.outputs['Spacing'], _in(dist, 'Distance Min'))
    L.new(gi.outputs['Density'], _in(dist, 'Density Max'))
    L.new(gi.outputs['Seed'], _in(dist, 'Seed'))

    # inset: a share of the cards sink into the crown along -normal (fills it, gives depth)
    inset = N.new('GeometryNodeSetPosition')
    L.new(_out(dist, 'Points'), _in(inset, 'Geometry'))
    L.new(rnd('BOOLEAN', gi.outputs['Inset Share'], None, 11), _in(inset, 'Selection'))
    k = N.new('ShaderNodeVectorMath'); k.operation = 'SCALE'
    L.new(_out(dist, 'Normal'), k.inputs[0])
    L.new(op('MULTIPLY', gi.outputs['Inset'], -1.0), _in(k, 'Scale'))
    L.new(k.outputs['Vector'], _in(inset, 'Offset'))

    # vertex colour on the points (instances + realize carry it to the card vertices)
    shell = N.new('GeometryNodeObjectInfo'); shell.transform_space = 'RELATIVE'
    L.new(gi.outputs['Shell'], _in(shell, 'Object'))
    prox = N.new('GeometryNodeProximity'); prox.target_element = 'FACES'
    L.new(_out(shell, 'Geometry'), _in(prox, 'Geometry'))
    clamp = N.new('ShaderNodeClamp')                   # G: 1 at the shell, 0 at Depth Scale inside
    L.new(op('SUBTRACT', 1.0, op('DIVIDE', _out(prox, 'Distance'), gi.outputs['Depth Scale'])), clamp.inputs['Value'])
    pos = N.new('GeometryNodeInputPosition')
    sep = N.new('ShaderNodeSeparateXYZ'); L.new(pos.outputs[0], sep.inputs[0])
    stat = N.new('GeometryNodeAttributeStatistic')
    L.new(gi.outputs['Geometry'], _in(stat, 'Geometry'))
    L.new(sep.outputs['Z'], _in(stat, 'Attribute'))
    hmap = N.new('ShaderNodeMapRange')
    L.new(sep.outputs['Z'], _in(hmap, 'Value'))
    L.new(_out(stat, 'Min'), _in(hmap, 'From Min'))
    L.new(_out(stat, 'Max'), _in(hmap, 'From Max'))
    comb = N.new('FunctionNodeCombineColor')
    L.new(rnd('FLOAT', 0.0, 1.0, 7), comb.inputs['Red'])
    L.new(clamp.outputs[0], comb.inputs['Green'])
    L.new(_out(hmap, 'Result'), comb.inputs['Blue'])
    store = N.new('GeometryNodeStoreNamedAttribute'); store.data_type = 'FLOAT_COLOR'; store.domain = 'POINT'
    L.new(_out(inset, 'Geometry'), _in(store, 'Geometry'))
    _in(store, 'Name').default_value = "Col"
    L.new(comb.outputs['Color'], _in(store, 'Value'))

    # cards: aligned to the normal, random spin around it + a little tilt, random size
    e2r = N.new('FunctionNodeEulerToRotation')
    tilt = rnd('FLOAT_VECTOR', (-1, -1, 0), (1, 1, 6.2832), 3)
    tv = N.new('ShaderNodeVectorMath'); tv.operation = 'MULTIPLY'
    L.new(tilt, tv.inputs[0])
    cxyz = N.new('ShaderNodeCombineXYZ')
    L.new(gi.outputs['Tilt'], cxyz.inputs['X']); L.new(gi.outputs['Tilt'], cxyz.inputs['Y'])
    cxyz.inputs['Z'].default_value = 1.0
    L.new(cxyz.outputs[0], tv.inputs[1])
    L.new(tv.outputs['Vector'], e2r.inputs['Euler'])
    rot = N.new('FunctionNodeRotateRotation')
    try:
        rot.rotation_space = 'LOCAL'
    except (AttributeError, TypeError):
        pass
    L.new(_out(dist, 'Rotation'), _in(rot, 'Rotation'))
    L.new(e2r.outputs['Rotation'], _in(rot, 'Rotate By'))
    size = op('MULTIPLY', gi.outputs['Card Size'],
              op('ADD', 1.0, op('MULTIPLY', gi.outputs['Size Random'], rnd('FLOAT', -1.0, 1.0, 5))))
    card = N.new('GeometryNodeObjectInfo'); card.transform_space = 'ORIGINAL'
    L.new(gi.outputs['Card'], _in(card, 'Object'))
    inst = N.new('GeometryNodeInstanceOnPoints')
    L.new(_out(store, 'Geometry'), _in(inst, 'Points'))
    L.new(_out(card, 'Geometry'), _in(inst, 'Instance'))
    L.new(_out(rot, 'Rotation'), _in(inst, 'Rotation'))
    L.new(size, _in(inst, 'Scale'))
    real = N.new('GeometryNodeRealizeInstances')
    L.new(_out(inst, 'Instances'), _in(real, 'Geometry'))
    L.new(_out(real, 'Geometry'), go.inputs[0])
    return ng


def _mod_socket(mod, item):
    """Blender 5.x: modifier inputs live in mod.properties.inputs.<identifier>.value (4.x: mod[identifier])."""
    props = getattr(mod, 'properties', None)
    return getattr(props.inputs, item.identifier) if props is not None else None


def set_inputs(mod, **kw):
    """Set geometry-nodes modifier inputs by their interface names."""
    for item in mod.node_group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name in kw:
            s = _mod_socket(mod, item)
            if s is not None:
                s.value = kw[item.name]
            else:
                mod[item.identifier] = kw[item.name]
    mod.id_data.update_tag()                        # setting .value does not re-evaluate by itself


def get_input(mod, name):
    for item in mod.node_group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name:
            s = _mod_socket(mod, item)
            return s.value if s is not None else mod[item.identifier]


# ---------------------------------------------------------------- materials (Blender preview only)
def image(name):
    path = os.path.join(TEX, name)
    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.load(path)
    else:
        img.filepath = path
        img.reload()
    return img


def foliage_material():
    m = bpy.data.materials.get('M_Foliage') or bpy.data.materials.new('M_Foliage')
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = image('T_Foliage.png')
    vc = nt.nodes.new('ShaderNodeVertexColor'); vc.layer_name = 'Col'
    sep = nt.nodes.new('ShaderNodeSeparateColor')
    nt.links.new(vc.outputs['Color'], sep.inputs['Color'])
    # hue jitter per card (R) + darker inside the crown (G: 1 outside -> 0.55 deep inside)
    hue = nt.nodes.new('ShaderNodeHueSaturation')
    hm = nt.nodes.new('ShaderNodeMapRange'); hm.inputs['To Min'].default_value = 0.47; hm.inputs['To Max'].default_value = 0.53
    nt.links.new(sep.outputs['Red'], hm.inputs['Value'])
    nt.links.new(hm.outputs['Result'], hue.inputs['Hue'])
    nt.links.new(tex.outputs['Color'], hue.inputs['Color'])
    ao = nt.nodes.new('ShaderNodeMapRange'); ao.inputs['To Min'].default_value = 0.55
    nt.links.new(sep.outputs['Green'], ao.inputs['Value'])
    mul = nt.nodes.new('ShaderNodeMix'); mul.data_type = 'RGBA'; mul.blend_type = 'MULTIPLY'
    mul.inputs['Factor'].default_value = 1.0
    nt.links.new(hue.outputs['Color'], mul.inputs['A'])
    nt.links.new(ao.outputs['Result'], mul.inputs['B'])
    nt.links.new(mul.outputs['Result'], bsdf.inputs['Base Color'])
    clip = nt.nodes.new('ShaderNodeMath'); clip.operation = 'GREATER_THAN'; clip.inputs[1].default_value = 0.5
    nt.links.new(tex.outputs['Alpha'], clip.inputs[0])
    nt.links.new(clip.outputs[0], bsdf.inputs['Alpha'])
    bsdf.inputs['Roughness'].default_value = 0.75
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    m.use_backface_culling = False
    try:
        m.surface_render_method = 'DITHERED'
    except (AttributeError, TypeError):
        pass
    m.diffuse_color = (0.15, 0.3, 0.06, 1)
    return m


def bark_material():
    m = bpy.data.materials.get('M_Bark') or bpy.data.materials.new('M_Bark')
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    tex = nt.nodes.new('ShaderNodeTexImage'); tex.image = image('T_Bark.png')
    nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.9
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    m.diffuse_color = (0.2, 0.16, 0.12, 1)
    return m


# ---------------------------------------------------------------- step A
def tris(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


def evaluated_tris(ob):
    bpy.context.view_layer.update()                 # modifier inputs changed: re-evaluate first
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    n = tris(me)
    ev.to_mesh_clear()
    return n


def build_a():
    bark, leaf = bark_material(), foliage_material()
    ng = leaf_scatter_group()
    cards = collection('TR_Cards')
    cards.hide_render = True
    report = []
    for i, (sp, cu, lobes) in enumerate(source()):
        name = f"TR_{sp}_0"
        col = collection(name)
        clear_collection(col)
        M, s = tree_frame(sp, cu, lobes)
        root = empty(f"{name}_Work", col, loc=(LAYOUT_X, i * SPACING, 0))
        root.empty_display_size = 2.0

        br = branches_of(cu, M, s, sp)
        trunk = bpy.data.objects.new(f"{name}_Trunk_LOD0", tube_mesh(f"{name}_Trunk_LOD0", br, sides=TRUNK_SIDES, flare=1.25))
        col.objects.link(trunk)
        trunk.data.materials.append(bark)

        canopy = lobe_union(f"{name}_Leaves_LOD0", lobes, M, col)
        shell, crown_r = normal_shell(f"{name}_NormalShell", canopy, col)
        area = sum(p.area for p in canopy.data.polygons)
        n_cards = int((TRI_BUDGET[0] - tris(trunk.data)) / CARD_TRIS * 0.95)
        density = n_cards / area
        spacing = 0.62 / math.sqrt(density)          # Poisson radius ~ the mean spacing at that density
        card = card_object(sp, cards, leaf)

        canopy.data.materials.append(leaf)
        mod = canopy.modifiers.new("HN_LeafScatter", 'NODES')
        mod.node_group = ng
        set_inputs(mod, Card=card, Shell=shell, Density=density * 3.0, Spacing=spacing,
                   **{"Card Size": CARD_SIZE * (s / 2.5) ** 0.3, "Depth Scale": 0.25 * crown_r,
                      "Inset": 0.12 * crown_r, "Seed": i * 101})
        dt = canopy.modifiers.new("NormalTransfer", 'DATA_TRANSFER')
        dt.object = shell
        dt.use_loop_data = True
        dt.data_types_loops = {'CUSTOM_NORMAL'}
        dt.loop_mapping = 'POLYINTERP_NEAREST'
        for ob in (trunk, canopy, shell):
            ob.parent = root
        # Poisson count is only roughly density * area: correct the spacing until within the budget
        for _ in range(4):
            lt = evaluated_tris(canopy)
            want = TRI_BUDGET[0] - tris(trunk.data)
            if 0.93 * want <= lt <= want:
                break
            spacing *= math.sqrt(lt / (0.97 * want))
            set_inputs(mod, Spacing=spacing)
        lt = evaluated_tris(canopy)
        report.append(dict(id=name, species=sp, scale=round(s, 2), height=TARGET_H[sp], crown_r=round(crown_r, 2),
                           trunk_tris=tris(trunk.data), leaf_tris=lt, cards=lt // CARD_TRIS,
                           lod0_tris=tris(trunk.data) + lt, crown_area=round(area, 1)))
        print(f"[trees] {name}: x{s:.2f}, crown r {crown_r:.1f} m, trunk {tris(trunk.data)} + leaves {lt} "
              f"({lt // CARD_TRIS} cards) = {tris(trunk.data) + lt} tris")
    return report


# ---------------------------------------------------------------- step B
EXPORT_DIR = os.path.join(ROOT, "Export", "Trees")
EXPORT_DX = 16.0                 # export root sits this far from the work root (+x)
LOD_DX = 14.0                    # LOD1 / LOD2 shown this far apart in the .blend (snapped on export)
LOD1_CARD = 1.5                  # LOD1 card size vs LOD0
TRUNK_LOD = [dict(sides=TRUNK_SIDES, max_level=2, min_r=0.018),
             dict(sides=(6, 4), max_level=1, min_r=0.03),
             dict(sides=(4,), max_level=0, min_r=0.05)]
TRUNK_STEP = (1, 1, 3)           # keep every n-th sample along the branches per LOD
BLOB_PUFF = 0.4                  # LOD2 crown pushed out by this x card size (cards stick out of the crown)
HLOD_TRIS = 80                   # crown-only mesh merged into the Unity chunk HLOD (thousands of trees)


def evaluated_mesh(ob, name):
    """Mesh of `ob` with its modifiers (live ones stay on the object)."""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    return bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)


def merged_mesh(name, parts, mats):
    """parts: [(mesh, material index, colour)] -> ONE mesh: 'UVMap', corner BYTE_COLOR 'Col' (raw bytes =
    data: R random / G depth / B height for leaves; the colour for the blob), custom normals = each
    part's corner normals (keeps the transferred leaf normals). colour: used when the part has no 'Col';
    a callable gets the corner positions (n,3) and returns (n,4)."""
    cos, lvs, lss, uvs, nrs, cols, mis = [], [], [], [], [], [], []
    vb = lb = 0
    for me, mi, colour in parts:
        nv, nl, npl = len(me.vertices), len(me.loops), len(me.polygons)
        co = np.empty(nv * 3, np.float32); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
        lv = np.empty(nl, np.int32); me.loops.foreach_get('vertex_index', lv)
        ls = np.empty(npl, np.int32); me.polygons.foreach_get('loop_start', ls)
        uv = np.zeros(nl * 2, np.float32)
        if me.uv_layers:
            me.uv_layers[0].data.foreach_get('uv', uv)
        nr = np.empty(nl * 3, np.float32); me.corner_normals.foreach_get('vector', nr)
        at = me.attributes.get('Col')
        if at is not None:
            c = np.empty(len(at.data) * 4, np.float32); at.data.foreach_get('color', c); c = c.reshape(-1, 4)
            c = c[lv] if at.domain == 'POINT' else c
        elif callable(colour):
            c = colour(co[lv])
        else:
            c = np.tile(np.array(colour, np.float32), (nl, 1))
        cos.append(co); lvs.append(lv + vb); lss.append(ls + lb); uvs.append(uv); nrs.append(nr.reshape(-1, 3))
        cols.append(c); mis.append(np.full(npl, mi, np.int32))
        vb += nv; lb += nl
    co, lv, ls = np.concatenate(cos), np.concatenate(lvs), np.concatenate(lss)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(co)); me.vertices.foreach_set('co', co.ravel())
    me.loops.add(len(lv)); me.loops.foreach_set('vertex_index', lv)
    me.polygons.add(len(ls)); me.polygons.foreach_set('loop_start', ls)
    me.polygons.foreach_set('material_index', np.concatenate(mis))
    me.update(calc_edges=True)
    me.polygons.foreach_set('use_smooth', np.ones(len(ls), bool))
    me.uv_layers.new(name='UVMap').data.foreach_set('uv', np.concatenate(uvs))
    ca = me.color_attributes.new('Col', 'BYTE_COLOR', 'CORNER')
    ca.data.foreach_set('color_srgb', np.clip(np.concatenate(cols), 0, 1).ravel())
    me.normals_split_custom_set(np.concatenate(nrs))
    for m in mats:
        me.materials.append(m)
    me.update()
    return me


def blob_material():
    m = bpy.data.materials.get('M_FoliageBlob') or bpy.data.materials.new('M_FoliageBlob')
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    vc = nt.nodes.new('ShaderNodeVertexColor'); vc.layer_name = 'Col'
    nt.links.new(vc.outputs['Color'], bsdf.inputs['Base Color'])
    bsdf.inputs['Roughness'].default_value = 0.85
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    m.diffuse_color = (0.12, 0.25, 0.05, 1)
    return m


def blob_mesh(shell, name, target, puff):
    """LOD2 crown: the NormalShell pushed out by `puff` m (to the LOD0 silhouette) and decimated to
    at most `target` triangles (smooth normals of the shell)."""
    tmp = bpy.data.objects.new("__blob", shell.data)
    bpy.context.scene.collection.objects.link(tmp)
    m = tmp.modifiers.new("Puff", 'DISPLACE'); m.mid_level = 0.0; m.strength = puff
    m = tmp.modifiers.new("Decimate", 'DECIMATE')
    ratio = target / max(1, tris(shell.data))
    for _ in range(6):
        m.ratio = min(1.0, ratio)
        me = evaluated_mesh(tmp, name)
        if tris(me) <= target:
            break
        ratio *= 0.97 * target / tris(me)
        bpy.data.meshes.remove(me)
    bpy.data.objects.remove(tmp, do_unlink=True)
    return me


def thinned(branches, step):
    """Every `step`-th sample along each branch (the last one always kept)."""
    if step <= 1:
        return branches
    out = []
    for b in branches:
        idx = list(range(0, len(b['pts']) - 1, step)) + [len(b['pts']) - 1]
        out.append(dict(b, pts=[b['pts'][j] for j in idx], rs=[b['rs'][j] for j in idx]))
    return out


def blob_colour(sp, z_top):
    """Species leaf colour (sRGB, from T_Foliage_blob.json), a bit darker towards the crown base."""
    rgb = np.array(json.load(open(os.path.join(TEX, "T_Foliage_blob.json")))['blob'][sp]['srgb'], np.float32)

    def f(p):
        h = np.clip((p[:, 2] - p[:, 2].min()) / max(1e-6, z_top - p[:, 2].min()), 0, 1)
        c = rgb[None, :] * (0.8 + 0.2 * h[:, None])            # true average; Unity matches the crown via _BlobGain
        return np.concatenate([c, np.ones((len(p), 1), np.float32)], 1)
    return f


def build_b():
    bark, leaf, blob = bark_material(), foliage_material(), blob_material()
    os.makedirs(os.path.join(EXPORT_DIR, "FBX"), exist_ok=True)
    report = []
    for i, (sp, cu, lobes) in enumerate(source()):
        name = f"TR_{sp}_0"
        col = bpy.data.collections[name]
        old = bpy.data.objects.get(name)                 # step-A root from before the _Work rename
        if old is not None and any(c.name.endswith('_Leaves_LOD0') for c in old.children):
            old.name = f"{name}_Work"
        work = bpy.data.objects[f"{name}_Work"]
        leaves = bpy.data.objects[f"{name}_Leaves_LOD0"]
        shell = bpy.data.objects[f"{name}_NormalShell"]
        for ob in [o for o in col.objects if o.name.startswith(f"{name}_LOD") or o.name == name]:
            me = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me)
        root = empty(name, col, loc=(work.location.x + EXPORT_DX, work.location.y, 0))
        root.empty_display_size = 2.0

        M, s = tree_frame(sp, cu, lobes)
        br = branches_of(cu, M, s, sp)
        trunks = [tube_mesh(f"__trunk{k}", thinned(br, TRUNK_STEP[k]), flare=1.25, **TRUNK_LOD[k]) for k in range(3)]

        # LOD0 = the leaves exactly as the user left the sliders; LOD1 = fewer, larger cards, same look
        mod = leaves.modifiers["HN_LeafScatter"]
        keep = {k: get_input(mod, k) for k in ("Spacing", "Card Size")}
        foliage = [evaluated_mesh(leaves, "__leaves0")]
        set_inputs(mod, **{"Card Size": keep["Card Size"] * LOD1_CARD})
        spacing = keep["Spacing"] * LOD1_CARD
        want = TRI_BUDGET[1] - tris(trunks[1])
        for _ in range(5):
            set_inputs(mod, Spacing=spacing)
            lt = evaluated_tris(leaves)
            if 0.9 * want <= lt <= want:
                break
            spacing *= math.sqrt(lt / (0.95 * want))
        foliage.append(evaluated_mesh(leaves, "__leaves1"))
        set_inputs(mod, **keep)                          # the live modifier keeps the user's LOD0 values
        z_top = max(v.co.z for v in shell.data.vertices)
        foliage.append(blob_mesh(shell, "__blob2", TRI_BUDGET[2] - tris(trunks[2]), BLOB_PUFF * keep["Card Size"]))

        tri_counts = []
        for k in range(3):
            fol_mat = blob if k == 2 else leaf
            colour = blob_colour(sp, z_top) if k == 2 else (0.5, 1.0, 0.5, 1.0)
            me = merged_mesh(f"{name}_LOD{k}", [(trunks[k], 0, (0.5, 1.0, 0.0, 1.0)), (foliage[k], 1, colour)],
                             [bark, fol_mat])
            ob = bpy.data.objects.new(f"{name}_LOD{k}", me)
            col.objects.link(ob)
            ob.parent = root
            ob.location = (k * LOD_DX, 0, 0)
            tri_counts.append(tris(me))
        for me in trunks + foliage:
            bpy.data.meshes.remove(me)

        fbx = os.path.join(EXPORT_DIR, "FBX", f"{name}.fbx")
        hanoi_common.export_fbx(fbx, [root], zero_roots=True)

        # chunk HLOD (Unity ChunkBuilder): crown only, ~HLOD_TRIS, same blob colours; no trunk (invisible from afar)
        old = bpy.data.objects.get(f"{name}_HLOD")
        if old is not None:
            me = old.data
            bpy.data.objects.remove(old, do_unlink=True)
            bpy.data.meshes.remove(me)
        hb = blob_mesh(shell, "__hlod", HLOD_TRIS, BLOB_PUFF * keep["Card Size"] * 1.1)
        hme = merged_mesh(f"{name}_HLOD", [(hb, 0, blob_colour(sp, z_top))], [blob])
        bpy.data.meshes.remove(hb)
        hob = bpy.data.objects.new(f"{name}_HLOD", hme)
        col.objects.link(hob)
        hob.location = (root.location.x + 3 * LOD_DX, root.location.y, 0)
        os.makedirs(os.path.join(EXPORT_DIR, "FBX", "HLOD"), exist_ok=True)
        hanoi_common.export_fbx(os.path.join(EXPORT_DIR, "FBX", "HLOD", f"{name}_HLOD.fbx"), [hob], zero_roots=True)
        tri_counts.append(tris(hme))
        crown_r = float(np.ptp(np.array([v.co for v in shell.data.vertices])[:, :2], 0).mean() / 2)
        report.append(dict(id=name, species=sp, fbx=f"FBX/{name}.fbx", hlod=f"FBX/HLOD/{name}_HLOD.fbx",
                           height=TARGET_H[sp], scale=round(s, 3),
                           crown_r=round(crown_r, 2), tris=tri_counts[:3], hlod_tris=tri_counts[3], budget=list(TRI_BUDGET),
                           leaf_spacing=round(keep["Spacing"], 4), card_size=round(keep["Card Size"], 3)))
        flag = "" if all(t <= b for t, b in zip(tri_counts, TRI_BUDGET + (HLOD_TRIS,))) else "  OVER BUDGET"
        print(f"[trees] {name}: LOD0/1/2 + HLOD tris {tri_counts} (budget {list(TRI_BUDGET)} + {HLOD_TRIS}){flag} -> {fbx}")
    json.dump(dict(source="Blender/ManualSculptedTree.blend", trees=report),
              open(os.path.join(EXPORT_DIR, "trees.json"), "w"), indent=1)
    hanoi_common.save_kit(BLEND)
    return report


def verify():
    """Background, empty scene: re-import every exported FBX and print what Unity will get."""
    for f in sorted(os.listdir(os.path.join(EXPORT_DIR, "FBX"))):
        if not f.endswith(".fbx"):
            continue
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=os.path.join(EXPORT_DIR, "FBX", f))
        new = [o for o in bpy.data.objects if o not in before]
        for o in sorted(new, key=lambda o: o.name):
            if o.type == 'MESH':
                me = o.data
                print(f"[verify] {f}: {o.name} parent={o.parent.name if o.parent else None} "
                      f"loc={tuple(round(v, 2) for v in o.matrix_world.translation)} "
                      f"size={tuple(round(v, 2) for v in o.dimensions)} tris={tris(me)} "
                      f"mats={[m.name for m in me.materials]} custom_normals={me.has_custom_normals} "
                      f"colours={[a.name for a in me.color_attributes]} uv={[u.name for u in me.uv_layers]}")
            else:
                print(f"[verify] {f}: {o.name} ({o.type}) rot={tuple(round(math.degrees(v)) for v in o.rotation_euler)}")
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)


def verify_in_background():
    cmd = [BLENDER_EXE, "-b", "--factory-startup", "--python", os.path.join(SCRIPTS, "build_manual_trees.py"),
           "--", "--verify"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    print("\n".join(l for l in r.stdout.splitlines() if l.startswith(("[verify]", "Error", "Traceback"))) or r.stderr[-2000:])


# ---------------------------------------------------------------- preview (background copy)
def render_preview(tag):
    import preview_modules, hanoi_house, tube_generator
    for m in (preview_modules, hanoi_house, tube_generator):
        importlib.reload(m)
    from hanoi_common import materials, mesh_object
    for c in ('Source', 'TR_Cards'):
        if c in bpy.data.collections:
            bpy.data.collections[c].hide_render = True
    pcol = collection('PREVIEW')
    kit, glass = materials()
    plan = [h for h in tube_generator.library_plan() if h[3]['floors'] == 4 and h[3]['exposed'] == '']
    _, _, recipe, meta = plan[0]
    preview_modules.OUT_DIR = PREVIEW_DIR
    preview_modules.ENVS[:] = ['sun']

    def reset(house_x):
        for ob in list(pcol.objects) + [o for o in bpy.data.objects if o.name.split('.')[0] in ('Ground', 'Sun', 'Cam')]:
            bpy.data.objects.remove(ob, do_unlink=True)
        mesh_object("RefHouse", hanoi_house.assemble(recipe, 0, meta['depth']), pcol, [kit, glass], loc=(house_x, 4.0, 0))

    spacing = 16.0
    if tag == 'A':
        names = [f"TR_{sp}_0_Work" if f"TR_{sp}_0_Work" in bpy.data.objects else f"TR_{sp}_0" for _, sp in TREES]
        for i, nm in enumerate(names):
            bpy.data.objects[nm].location = (i * spacing - spacing * 1.5, 0, 0)
        reset(-spacing * 2.5)
        for i, (_, sp) in enumerate(TREES):
            preview_modules.label(sp, (i * spacing - spacing * 1.5, -9.0, 0.05), pcol, 1.0)
        preview_modules.render_scene("trees_manual_A.png", (-spacing * 0.5, 0, 7.5), spacing * 5.6, 22, yaw=0, pitch=8)
        return
    # B: one image per species, LOD0 / LOD1 / LOD2 side by side next to the house
    roots = {sp: bpy.data.objects[f"TR_{sp}_0"] for _, sp in TREES}
    report = {t['species']: t for t in json.load(open(os.path.join(EXPORT_DIR, "trees.json")))['trees']}
    for ob in bpy.context.scene.objects:
        if ob.type != 'EMPTY' and not (ob.parent is not None and ob.parent in roots.values()):
            ob.hide_render = True
    for _, sp in TREES:
        for other, r in roots.items():
            r.location = (0, 0, 0) if other == sp else (0, 1000, 0)
            for c in r.children:
                c.hide_render = other != sp
        reset(-spacing)
        for k in range(3):
            preview_modules.label(f"LOD{k}  {report[sp]['tris'][k]} tris", (k * LOD_DX - 4.0, -9.0, 0.05), pcol, 0.9)
        preview_modules.render_scene(f"trees_manual_B_{sp}.png", (LOD_DX * 0.75, 0, 7.5), LOD_DX * 4.6, 20,
                                     yaw=0, pitch=8)


def preview_in_background(tag):
    bpy.ops.wm.save_as_mainfile(filepath=PREVIEW_COPY, copy=True)
    cmd = [BLENDER_EXE, "-b", PREVIEW_COPY, "--python", os.path.join(SCRIPTS, "build_manual_trees.py"),
           "--", "--preview", tag]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    tail = "\n".join(l for l in r.stdout.splitlines() if l.startswith(("[preview]", "[trees]", "Saved", "Error", "Traceback")))
    print(tail or r.stdout[-2000:])
    if r.returncode != 0:
        print(r.stderr[-2000:])


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--preview" in argv:
        render_preview(argv[argv.index("--preview") + 1])
    elif "--verify" in argv:
        verify()
    elif globals().get("STEP") == "B":
        REPORT = build_b()
        if not globals().get("NO_PREVIEW"):
            preview_in_background('B')
        verify_in_background()
    else:
        REPORT = build_a()
        json.dump(REPORT, open(os.path.join(PREVIEW_DIR, "trees_manual_A.json"), "w"), indent=1)
        if not globals().get("NO_PREVIEW"):
            preview_in_background('A')
