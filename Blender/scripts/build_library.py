"""M1/B3: build the building-variant library and export one FBX per variant + a JSON manifest.

The library is the only source of building shapes for the city: the map pipeline only picks a
variant + position per lot, it never builds unique meshes.

Batch (preferred, does not touch the open Blender session):
    blender -b --python "D:/Project III/BuildingGenerate/Blender/scripts/build_library.py"
"""
import os, sys, json, math, random, importlib, datetime
import bpy

ROOT = r"D:\Project III\BuildingGenerate"
SCRIPTS = os.path.join(ROOT, "Blender", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import hanoi_trim, hanoi_kit, hanoi_common, hanoi_house, hanoi_tower, tube_generator
for m in (hanoi_trim, hanoi_kit, hanoi_common, hanoi_house, hanoi_tower, tube_generator):
    importlib.reload(m)
from hanoi_kit import W
from hanoi_common import collection, clear_collection, mesh_object, empty, materials, export_fbx, save_kit
from hanoi_house import assemble, build_lod2_house
from tube_generator import library_plan, DEPTH_SCALE
from hanoi_tower import TOWERS, build_tower, scaled

LIB_DIR = os.path.join(ROOT, "Export", "Library")
FBX_DIR = os.path.join(LIB_DIR, "FBX")
MANIFEST = os.path.join(LIB_DIR, "library.json")
LIB_BLEND = os.path.join(ROOT, "Blender", "HanoiLibrary.blend")

WHITE = (1.0, 1.0, 1.0, 1.0)

# (archetype, floors, footprint scale along the long side)
TOWER_VARIANTS = (
    ('T1_RoyalCity', 24, 1.0), ('T1_RoyalCity', 30, 1.0), ('T1_RoyalCity', 36, 1.0),
    ('T1_RoyalCity', 30, 0.75),
    ('T2_Stripe', 40, 1.0), ('T2_Stripe', 50, 1.0),
    ('T3_OldHousing', 15, 1.0), ('T3_OldHousing', 21, 1.0), ('T3_OldHousing', 18, 0.7),
    ('T4_Office', 20, 1.0), ('T4_Office', 30, 1.0),
)


# ---------------------------------------------------------------- build
def bbox(ob):
    xs = [v[0] for v in ob.bound_box]; ys = [v[1] for v in ob.bound_box]; zs = [v[2] for v in ob.bound_box]
    return [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3)], [round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)]


def main():
    for n in ('Cube',):
        ob = bpy.data.objects.get(n)
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)
    kit, glass = materials()
    col = collection('LIBRARY'); clear_collection(col)
    os.makedirs(FBX_DIR, exist_ok=True)
    for f in os.listdir(FBX_DIR):
        if f.lower().endswith('.fbx'):
            os.remove(os.path.join(FBX_DIR, f))

    variants = []

    # tube houses (tube_generator rules): LOD0 / LOD1 from modules, LOD2 massing + roof
    rows = {}
    for vid, seed, recipe, meta in library_plan():
        depth = meta['depth']
        col_i = rows.setdefault(depth, 0); rows[depth] += 1
        root = empty(vid, col, loc=(col_i * 6.0, {9.0: 0.0, 12.0: 20.0, 16.0: 45.0}[depth], 0))
        lods = [assemble(recipe, 0, depth), assemble(recipe, 1, depth),
                build_lod2_house(meta['roof_z'], depth, meta['top_module'])]
        tris, obs = [], []
        for lod, mb in enumerate(lods):
            obs.append(mesh_object(f"{vid}_LOD{lod}", mb, col, [kit, glass] if lod < 2 else [kit],
                                   parent=root, loc=(0, 0, 0) if lod == 0 else (0, 0, -200.0 * lod)))
            tris.append(mb.tri_count())
        lo, hi = bbox(obs[0])
        export_fbx(os.path.join(FBX_DIR, vid + '.fbx'), [root], zero_roots=True)
        variants.append(dict(
            id=vid, type='tube', file=f"FBX/{vid}.fbx", seed=seed, floors=meta['floors'],
            frontage=W, depth=depth, depth_scale=list(DEPTH_SCALE), height=round(hi[2], 2),
            roof_z=meta['roof_z'], top=meta['top'], roof_color=meta['roof_color'],
            exposed=meta['exposed'], side_windows=meta['side'], ground=meta['gf'], upper=meta['upper'],
            bounds_min=lo, bounds_max=hi, lods=len(lods), tris=tris,
            recipe=[dict(module=m, pos=list(p), rotZ=r) for m, p, r in recipe]))

    # towers: massing only (LOD0 = generator LOD1, LOD1 = generator LOD2)
    for j, (arch, floors, sx) in enumerate(TOWER_VARIANTS):
        vid = f"TW_{arch.split('_')[0]}_{floors}F" + ("" if sx == 1.0 else f"_S{int(sx * 100)}")
        r = dict(TOWERS[arch], floors=floors)
        if sx != 1.0:
            r['fp'] = scaled(r['fp'], sx, 1.0)
        root = empty(vid, col, loc=(80.0 + (j % 6) * 70.0, (j // 6) * 70.0, 0))
        tris, obs = [], []
        for lod, glod in enumerate((1, 2)):
            mb = build_tower(r, glod)
            obs.append(mesh_object(f"{vid}_LOD{lod}", mb, col, [kit], parent=root,
                                   loc=(0, 0, 0) if lod == 0 else (0, 0, -300.0), tint=WHITE))
            tris.append(mb.tri_count())
        lo, hi = bbox(obs[0])
        export_fbx(os.path.join(FBX_DIR, vid + '.fbx'), [root], zero_roots=True)
        variants.append(dict(
            id=vid, type='tower', archetype=arch, file=f"FBX/{vid}.fbx", floors=floors,
            footprint=[[round(x, 3), round(y, 3)] for x, y in r['fp']],
            frontage=round(hi[0] - lo[0], 2), depth=round(hi[1] - lo[1], 2), height=round(hi[2], 2),
            bounds_min=lo, bounds_max=hi, lods=2, tris=tris))

    manifest = dict(
        version=2,
        generated=datetime.datetime.now().isoformat(timespec='seconds'),
        coords="Blender metres: X = frontage axis, -Y = facade/front, +Y = depth, Z = up; origin = facade centre at ground",
        tube_notes="depth = baked lot depth bucket; placement may scale along depth within depth_scale. "
                   "exposed = side walls that carry windows ('L'/'R' seen from the street): use for corner lots "
                   "or houses taller than the neighbour; '' = party walls only.",
        materials=['M_HanoiKit', 'M_HanoiGlass'],
        variants=variants)
    with open(MANIFEST, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    save_kit(LIB_BLEND)
    return variants


if __name__ == "__main__":
    V = main()
    tubes = [v for v in V if v['type'] == 'tube']
    towers = [v for v in V if v['type'] == 'tower']
    print(f"[library] {len(tubes)} tube houses, {len(towers)} towers -> {MANIFEST}")
    for v in V:
        print(f"  {v['id']:22s} floors={v['floors']:3d} h={v['height']:7.2f} tris={v['tris']}"
              + (f" {v['ground']:12s} {v['top']}{'_' + v['roof_color'] if v.get('roof_color') else ''}" if v['type'] == 'tube' else ""))
