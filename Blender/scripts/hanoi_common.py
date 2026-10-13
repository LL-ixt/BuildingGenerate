"""Shared Blender helpers for the Hanoi kit scripts (houses and towers):
collections, objects, the two shared materials, FBX export for Unity."""
import os
import bpy

ROOT = r"D:\Project III\BuildingGenerate"
FBX_DIR = os.path.join(ROOT, "Export", "FBX")
PREVIEW_TINT = (0.84, 0.55, 0.14, 1.0)   # linear "vàng Pháp", Blender preview only


def collection(name, parent=None):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col


def clear_collection(col):
    for ob in list(col.all_objects):
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.meshes.remove(data)


def mesh_object(name, mb, col, mats, parent=None, loc=(0, 0, 0), tint=PREVIEW_TINT):
    me = mb.to_mesh(name, mats)
    ob = bpy.data.objects.new(name, me)
    ob['paint_color'] = tint
    col.objects.link(ob)
    ob.parent = parent
    ob.location = loc
    return ob


def empty(name, col, loc=(0, 0, 0)):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = 'PLAIN_AXES'
    ob.empty_display_size = 0.5
    ob.location = loc
    col.objects.link(ob)
    return ob


def materials():
    """M_HanoiKit / M_HanoiGlass. The node graphs are Blender previews only; Unity remaps
    both names to Hanoi/Building and Hanoi/Window."""
    kit = bpy.data.materials.get('M_HanoiKit') or bpy.data.materials.new('M_HanoiKit')
    kit.use_nodes = True
    nt = kit.node_tree; nt.nodes.clear()
    L = nt.links.new
    out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location = (500, 0)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (200, 0)
    vc = nt.nodes.new('ShaderNodeVertexColor'); vc.layer_name = 'Col'; vc.location = (-900, 0)
    # tint preview: base * paint_color where vertex alpha (paint mask) = 1
    tint = nt.nodes.new('ShaderNodeAttribute'); tint.location = (-900, -200)
    tint.attribute_type = 'OBJECT'; tint.attribute_name = 'paint_color'
    mul = nt.nodes.new('ShaderNodeMix'); mul.data_type = 'RGBA'; mul.blend_type = 'MULTIPLY'
    mul.location = (-600, 0)
    L(vc.outputs['Alpha'], mul.inputs['Factor'])
    L(vc.outputs['Color'], mul.inputs[6])
    L(tint.outputs['Color'], mul.inputs[7])

    # facade-grid preview (towers): a dark window in the middle of every ~3.3 x 3 m FacadeUV cell
    # (FacadeUV = metres from the wall centre; the Unity shader fits exact bays / floors instead).
    # Faces without a grid have FacadeUV = (0, 0) -> frac = 0 -> no window.
    fuv = nt.nodes.new('ShaderNodeUVMap'); fuv.uv_map = 'FacadeUV'; fuv.location = (-1400, -400)
    cell = nt.nodes.new('ShaderNodeVectorMath'); cell.operation = 'MULTIPLY'; cell.location = (-1200, -400)
    cell.inputs[1].default_value = (1 / 3.3, 1 / 3.0, 1.0)
    L(fuv.outputs['UV'], cell.inputs[0])
    sep = nt.nodes.new('ShaderNodeSeparateXYZ'); sep.location = (-1000, -400)
    L(cell.outputs['Vector'], sep.inputs[0])

    def band(src, lo, hi, y):
        fr = nt.nodes.new('ShaderNodeMath'); fr.operation = 'FRACT'; fr.location = (-800, y)
        L(src, fr.inputs[0])
        a = nt.nodes.new('ShaderNodeMath'); a.operation = 'GREATER_THAN'; a.inputs[1].default_value = lo
        b = nt.nodes.new('ShaderNodeMath'); b.operation = 'LESS_THAN'; b.inputs[1].default_value = hi
        a.location = (-600, y); b.location = (-600, y - 120)
        L(fr.outputs[0], a.inputs[0]); L(fr.outputs[0], b.inputs[0])
        m = nt.nodes.new('ShaderNodeMath'); m.operation = 'MULTIPLY'; m.location = (-400, y)
        L(a.outputs[0], m.inputs[0]); L(b.outputs[0], m.inputs[1])
        return m.outputs[0]

    wx = band(sep.outputs['X'], 0.15, 0.85, -400)
    wy = band(sep.outputs['Y'], 0.22, 0.86, -700)
    win = nt.nodes.new('ShaderNodeMath'); win.operation = 'MULTIPLY'; win.location = (-200, -500)
    L(wx, win.inputs[0]); L(wy, win.inputs[1])
    glassmix = nt.nodes.new('ShaderNodeMix'); glassmix.data_type = 'RGBA'; glassmix.location = (-200, 0)
    glassmix.inputs[7].default_value = (0.03, 0.045, 0.06, 1)
    L(win.outputs[0], glassmix.inputs['Factor'])
    # trim-sheet texture (Export/Textures/T_HanoiTrim.png): albedo = texture x (paint-tinted) vertex colour
    tex_path = os.path.join(ROOT, "Export", "Textures", "T_HanoiTrim.png")
    if os.path.exists(tex_path):
        img = bpy.data.images.get('T_HanoiTrim.png') or bpy.data.images.load(tex_path)
        img.colorspace_settings.name = 'sRGB'
        tx = nt.nodes.new('ShaderNodeTexImage'); tx.image = img; tx.location = (-900, -650)
        tx.interpolation = 'Linear'
        uvn = nt.nodes.new('ShaderNodeUVMap'); uvn.uv_map = 'UVMap'; uvn.location = (-1150, -650)
        L(uvn.outputs['UV'], tx.inputs['Vector'])
        tmul = nt.nodes.new('ShaderNodeMix'); tmul.data_type = 'RGBA'; tmul.blend_type = 'MULTIPLY'
        tmul.location = (-400, 150); tmul.inputs['Factor'].default_value = 1.0
        L(mul.outputs[2], tmul.inputs[6])
        L(tx.outputs['Color'], tmul.inputs[7])
        L(tmul.outputs[2], glassmix.inputs[6])
        L(tx.outputs['Alpha'], bsdf.inputs['Alpha'])               # railings: keyed alpha in the atlas
        try:
            kit.surface_render_method = 'DITHERED'
        except (AttributeError, TypeError):
            pass
    else:
        L(mul.outputs[2], glassmix.inputs[6])
    L(glassmix.outputs[2], bsdf.inputs['Base Color'])
    rough = nt.nodes.new('ShaderNodeMapRange'); rough.location = (0, -400)
    rough.inputs['To Min'].default_value = 0.8; rough.inputs['To Max'].default_value = 0.08
    L(win.outputs[0], rough.inputs['Value'])
    L(rough.outputs[0], bsdf.inputs['Roughness'])
    L(bsdf.outputs[0], out.inputs['Surface'])

    glass = bpy.data.materials.get('M_HanoiGlass') or bpy.data.materials.new('M_HanoiGlass')
    glass.use_nodes = True
    g = next(n for n in glass.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    g.inputs['Base Color'].default_value = (0.02, 0.03, 0.04, 1)
    g.inputs['Roughness'].default_value = 0.05
    glass.diffuse_color = (0.05, 0.07, 0.09, 1)
    kit.diffuse_color = (0.9, 0.8, 0.5, 1)
    return kit, glass


def export_fbx(path, roots, zero_roots=False):
    """Export roots + children with children temporarily snapped to their parent (LOD groups).
    zero_roots: also move the roots to the origin for the export (one asset per file)."""
    saved = {}
    bpy.ops.object.select_all(action='DESELECT')
    for r in roots:
        if zero_roots:
            saved[r.name] = tuple(r.location)
            r.location = (0, 0, 0)
        r.select_set(True)
        for c in r.children:
            saved[c.name] = tuple(c.location)
            c.location = (0, 0, 0)
            c.select_set(True)
    try:
        bpy.ops.export_scene.fbx(
            filepath=path, use_selection=True, object_types={'EMPTY', 'MESH'},
            apply_scale_options='FBX_SCALE_ALL', axis_forward='-Z', axis_up='Y',
            bake_space_transform=True, mesh_smooth_type='FACE', use_mesh_modifiers=True,
            add_leaf_bones=False, bake_anim=False, path_mode='AUTO', colors_type='SRGB')
    finally:
        for r in roots:
            if zero_roots:
                r.location = saved[r.name]
            for c in r.children:
                c.location = saved[c.name]
    return path


def save_kit(path):
    """Save the kit .blend, but never hijack another open file (e.g. a reference pack):
    only saves when the session is untitled or already is the kit file."""
    current = bpy.data.filepath
    if current and os.path.normcase(os.path.abspath(current)) != os.path.normcase(os.path.abspath(path)):
        print(f"[hanoi] NOT saving: Blender has '{current}' open, expected '{path}'. "
              f"Open the kit file (or a new file) and re-run.")
        return False
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return True
