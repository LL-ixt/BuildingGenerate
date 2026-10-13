"""Step 1 prototype: build the Hanoi kit + one tube house (LOD0/1/2) and export FBX for Unity.

Run inside Blender:
    exec(open(r"D:/Project III/BuildingGenerate/Blender/scripts/hanoi_house.py").read())
"""
import os, sys, json, math, importlib
import bpy
from mathutils import Matrix, Vector

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_trim, hanoi_kit, hanoi_common
importlib.reload(hanoi_trim); importlib.reload(hanoi_kit); importlib.reload(hanoi_common)
from hanoi_kit import MB, MODULES, GH, FH, HW, DEPTH, TUM
from hanoi_common import (FBX_DIR, collection, clear_collection, mesh_object, empty,
                          materials, save_kit, export_fbx)
BLEND_PATH = os.path.join(ROOT, "Blender", "HanoiKit_Prototype.blend")

# House A recipe: (module, (x, y, z), rot_z_deg). Precursor of the Unity BuildingRecipe asset.
Z = [0.0] + [GH + FH * i for i in range(5)]          # floor base heights
HOUSE_A = [
    ('Body_GF', (0, 0, Z[0]), 0), ('GF_Shop', (0, 0, Z[0]), 0),
    ('Body_UF', (0, 0, Z[1]), 0), ('UF_Balcony', (0, 0, Z[1]), 0),
    ('Body_UF', (0, 0, Z[2]), 0), ('UF_Cage', (0, 0, Z[2]), 0),
    ('Body_UF', (0, 0, Z[3]), 0), ('UF_Shutter', (0, 0, Z[3]), 0),
    ('Body_UF', (0, 0, Z[4]), 0), ('UF_Balcony', (0, 0, Z[4]), 0),
    ('RF_Terrace', (0, 0, Z[5]), 0), ('RF_TileRoof', (0, 0, Z[5]), 0),
    ('PR_WaterTank', (1.4, 9.0, Z[5]), 90),
    ('PR_AC', (1.0, 0, Z[3] + 0.15), 0), ('PR_AC', (-1.0, 0, Z[3] + 0.15), 0),
]
ROOF_Z = Z[5]
PLINTH = 0.3         # m: concrete foot below z = 0, hides the step between the 20 cm sidewalk and the lot ground


def add_plinth(mb, depth):
    """Foot of the house: 4 walls from -PLINTH to 0 (no top / bottom). Houses stand at sidewalk height in Unity."""
    mb.box(-HW, HW, 0.0, depth, -PLINTH, 0.0, 'CONCRETE', skip={'+Z', '-Z'}, uv='world')


# ---------------------------------------------------------------- house assembly
def without_crown(mb):
    """Copy of a front module without the crown cornice at the top of the floor (z 3.1..3.3):
    under a sloped roof the eave overhang passes through it."""
    out = MB()
    out.polys = [p for p in mb.polys
                 if not (p[2] == 'CORNICE' and all(3.05 <= v.z <= 3.35 for v in p[0]))]
    return out


def assemble(recipe, lod, depth=DEPTH):
    mb = MB()
    cache = {}
    sloped = [loc[2] for name, loc, rot in recipe if name.startswith('ROOF_')]
    roof_z = sloped[0] if sloped else None
    for name, loc, rot in recipe:
        crownless = (roof_z is not None and name.startswith('UF_') and abs(loc[2] + FH - roof_z) < 1e-3)
        key = (name, crownless)
        if key not in cache:
            cache[key] = hanoi_kit.build_module(name, lod, depth)
            if crownless:
                cache[key] = without_crown(cache[key])
        m = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(math.radians(rot), 4, 'Z')
        mb.extend(cache[key], m)
    add_plinth(mb, depth)
    return mb


def build_lod2(roof_z=ROOF_Z):
    """Massing box for far view (roof_z = top of the last floor). UVs laid out in slot 0 of a future 2048 facade atlas
    (512x1024 px per house) so a facade bake can drop straight in later."""
    mb = MB()
    A, SX, SY = 2048.0, 0, 1024          # atlas size, slot origin px

    def rect(x, y, w, h):
        return ((SX + x) / A, (SY + y) / A, (SX + x + w) / A, (SY + y + h) / A)

    def q(pts, n, r, region):
        pts = [Vector(p) for p in pts]
        if hanoi_kit._newell(pts).dot(Vector(n)) < 0:
            pts = [pts[1], pts[0], pts[3], pts[2]]
        u0, v0, u1, v1 = r
        mb.polys.append((pts, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)], region, 0))

    def tri(pts, n, r, region):
        pts = [Vector(p) for p in pts]
        if hanoi_kit._newell(pts).dot(Vector(n)) < 0:
            pts = pts[::-1]
        u0, v0, u1, v1 = r
        xs = [p.x for p in pts]; zs = [p.z for p in pts]
        uvs = [(u0 + (p.x - min(xs)) / (max(xs) - min(xs)) * (u1 - u0),
                v0 + (p.z - min(zs)) / (max(zs) - min(zs)) * (v1 - v0)) for p in pts]
        mb.polys.append((pts, uvs, region, 0))

    top = roof_z + 1.1                       # parapet height folded into the box
    x0, x1, y0, y1 = -HW, HW, 0.0, DEPTH
    q([(x0, y0, 0), (x1, y0, 0), (x1, y0, top), (x0, y0, top)], (0, -1, 0), rect(0, 0, 232, 1020), 'PLASTER')
    q([(x0, y0, top), (x1, y0, top), (x1, y1, top), (x0, y1, top)], (0, 0, 1), rect(236, 0, 114, 342), 'CONCRETE')
    q([(x0, y1, 0), (x0, y0, 0), (x0, y0, top), (x0, y1, top)], (-1, 0, 0), rect(236, 346, 168, 250), 'PLASTER')
    q([(x1, y1, 0), (x0, y1, 0), (x0, y1, top), (x1, y1, top)], (0, 1, 0), rect(408, 346, 56, 250), 'PLASTER')
    q([(x1, y0, 0), (x1, y1, 0), (x1, y1, top), (x1, y0, top)], (1, 0, 0), rect(236, 600, 168, 250), 'PLASTER')
    # tum
    tx0, tx1, ty0, ty1 = TUM['x0'], TUM['x1'], TUM['y0'], TUM['y1']
    tz0, tz1 = top, roof_z + TUM['h'] + 0.15
    q([(tx0, ty0, tz0), (tx1, ty0, tz0), (tx1, ty0, tz1), (tx0, ty0, tz1)], (0, -1, 0), rect(408, 600, 80, 48), 'PLASTER')
    q([(tx1, ty1, tz0), (tx0, ty1, tz0), (tx0, ty1, tz1), (tx1, ty1, tz1)], (0, 1, 0), rect(408, 652, 40, 24), 'PLASTER')
    q([(tx0, ty1, tz0), (tx0, ty0, tz0), (tx0, ty0, tz1), (tx0, ty1, tz1)], (-1, 0, 0), rect(236, 854, 98, 24), 'PLASTER')
    q([(tx1, ty0, tz0), (tx1, ty1, tz0), (tx1, ty1, tz1), (tx1, ty0, tz1)], (1, 0, 0), rect(340, 854, 98, 24), 'PLASTER')
    # gable roof
    rx0, rx1, ry0, ry1 = tx0 - 0.15, tx1 + 0.15, ty0 - 0.3, ty1
    xr, rh = (rx0 + rx1) / 2, 1.1
    q([(rx0, ry1, tz1), (rx0, ry0, tz1), (xr, ry0, tz1 + rh), (xr, ry1, tz1 + rh)], (-rh, 0, xr - rx0), rect(236, 882, 211, 51), 'TILE')
    q([(rx1, ry0, tz1), (rx1, ry1, tz1), (xr, ry1, tz1 + rh), (xr, ry0, tz1 + rh)], (rh, 0, rx1 - xr), rect(236, 937, 211, 51), 'TILE')
    tri([(rx0, ry0, tz1), (rx1, ry0, tz1), (xr, ry0, tz1 + rh)], (0, -1, 0), rect(236, 992, 88, 29), 'PLASTER')
    tri([(rx1, ry1, tz1), (rx0, ry1, tz1), (xr, ry1, tz1 + rh)], (0, 1, 0), rect(330, 992, 88, 29), 'PLASTER')
    return mb


def build_lod2_house(roof_z, depth, top):
    """Far-view massing for generated houses: one quad per wall up to the roof line, then the
    roof module at LOD1 without its undersides, or a flat terrace + tum box."""
    mb = MB()
    flat = top == 'RF_Terrace'
    h = roof_z + (1.1 if flat else 0.0)          # flat terrace: parapet folded into the box
    q = lambda pts, n, reg='PLASTER': mb.quad(pts, reg, n=n, uv='world')
    f = -PLINTH                                   # walls reach down to the plinth bottom (no extra triangles)
    q([(-HW, 0, f), (HW, 0, f), (HW, 0, h), (-HW, 0, h)], (0, -1, 0))
    q([(HW, depth, f), (-HW, depth, f), (-HW, depth, h), (HW, depth, h)], (0, 1, 0))
    q([(-HW, depth, f), (-HW, 0, f), (-HW, 0, h), (-HW, depth, h)], (-1, 0, 0))
    q([(HW, 0, f), (HW, depth, f), (HW, depth, h), (HW, 0, h)], (1, 0, 0))
    if flat:
        q([(-HW, 0, h), (HW, 0, h), (HW, depth, h), (-HW, depth, h)], (0, 0, 1), 'ROOFTOP')
        t = hanoi_kit.tum_rect(depth)
        top_z = roof_z + t['h'] + 0.15
        mb.box(t['x0'], t['x1'], t['y0'], t['y1'], h, top_z, 'PLASTER', skip={'-Z'}, uv='world',
               regions={'+Z': 'CONCRETE'})
    else:
        roof = hanoi_kit.build_module(top, 1, depth)
        roof.polys = [p for p in roof.polys if hanoi_kit._newell(p[0]).normalized().z > -0.1]
        mb.extend(roof, Matrix.Translation((0, 0, roof_z)))
    return mb


# ---------------------------------------------------------------- main
def main():
    scene = bpy.context.scene
    for n in ('Cube', 'Light'):
        ob = bpy.data.objects.get(n)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)

    kit_mat, glass_mat = materials()
    mats = [kit_mat, glass_mat]
    col_kit = collection('KIT_Modules'); clear_collection(col_kit)
    col_house = collection('HOUSE_A'); clear_collection(col_house)

    report = {}
    # kit: one empty per module, LOD0 child in front row, LOD1 child in back row
    kit_roots = []
    for i, name in enumerate(MODULES):
        root = empty(name, col_kit, loc=(-34 + i * 6.5, -30, 0))
        kit_roots.append(root)
        tris = []
        for lod, off in ((0, (0, 0, 0)), (1, (0, -18, 0))):
            mb = MODULES[name](lod)
            mesh_object(f"{name}_LOD{lod}", mb, col_kit, mats, parent=root, loc=off)
            tris.append(mb.tri_count())
        report[name] = tris

    # house A
    root = empty('SM_HouseA', col_house)
    lods = [assemble(HOUSE_A, 0), assemble(HOUSE_A, 1), build_lod2()]
    house_tris = []
    for lod, mb in enumerate(lods):
        mesh_object(f"SM_HouseA_LOD{lod}", mb, col_house, mats if lod < 2 else [kit_mat],
                    parent=root, loc=(lod * 7.0, 0, 0))
        house_tris.append(mb.tri_count())
    report['SM_HouseA'] = house_tris

    # light
    sun = bpy.data.objects.get('Sun')
    if sun is None:
        sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
        scene.collection.objects.link(sun)
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(-35))

    os.makedirs(FBX_DIR, exist_ok=True)
    export_fbx(os.path.join(FBX_DIR, 'SM_HouseA.fbx'), [root])
    export_fbx(os.path.join(FBX_DIR, 'Kit_HanoiTube.fbx'), kit_roots)
    with open(os.path.join(ROOT, 'Export', 'HouseA_recipe.json'), 'w', encoding='utf-8') as f:
        json.dump([{'module': n, 'pos': list(p), 'rotZ': r} for n, p, r in HOUSE_A], f, indent=1)
    save_kit(BLEND_PATH)
    return report


if __name__ == "__main__":
    REPORT = main()
    for k, v in REPORT.items():
        print(f"{k:14s} tris per LOD: {v}")
