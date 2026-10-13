"""B3: rule-based tube-house recipes, following tube_house_recipe.md.

A house = ground floor (GF) + 1..4 upper floors (UF) + top (flat terrace or a roof), built on a
lot of a given depth. Each floor = front module + back wall + left / right side walls; side
walls get windows only on the exposed sides (corner lot / taller than the neighbour).

Pure Python (no bpy): recipes are lists of (module, (x, y, z), rot_z_deg) for hanoi_house.assemble.
"""
import random
from hanoi_kit import GH, FH, tum_rect

# lot depth buckets baked into the library; placement may scale a house along its depth
DEPTHS = (9.0, 12.0, 16.0)
DEPTH_SCALE = (0.85, 1.15)

# weights (higher = more frequent)
FLOORS_W = {2: 2, 3: 4, 4: 4, 5: 3}                 # floors incl. the ground floor, top not counted
GF_W = {'GF_FoldGate': 3, 'GF_Open': 3, 'GF_WoodDoor': 2, 'GF_Shop': 1.5, 'GF_Roller': 1.5}
UF_W = {'UF_Window': 3, 'UF_BalconySolid': 3, 'UF_Balcony': 3, 'UF_Shutter': 1, 'UF_Cage': 1}
TOP_W = {'RF_Terrace': 4, 'ROOF_Shed': 2, 'ROOF_Gable': 2.5, 'ROOF_Hip': 1.5}
ROOF_COLOR_W = {'Red': 3, 'Blue': 2}
SIDE_N_W = {0: 1, 1: 2, 2: 2}                       # windows per floor on an exposed wall
SIDE_ALIGN_W = {'': 2, 'F': 1, 'B': 1}              # centre / towards the street / towards the back

REPEAT_P = 0.55          # an upper floor copies the floor below (houses are built floor by floor)
TOP_BALCONY_P = 0.5      # the last upper floor favours a balcony
SIDE_GF_BLANK_P = 0.6    # exposed walls are often blank on the ground floor
SIDE_SAME_ALIGN_P = 0.8  # windows stack in columns
AC_P = 0.35              # air-conditioner per free slot beside a window
TANK_P = 0.8             # water tank on a flat terrace


def pick(rng, weights):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def side_column(rng, floors):
    """Window code per floor (GF first) for one exposed wall, e.g. ['0', '1F', '2F']."""
    align = pick(rng, SIDE_ALIGN_W)
    out = []
    for f in range(floors):
        n = 0 if (f == 0 and rng.random() < SIDE_GF_BLANK_P) else pick(rng, SIDE_N_W)
        a = align if rng.random() < SIDE_SAME_ALIGN_P else pick(rng, SIDE_ALIGN_W)
        out.append(f"{n}{a}" if n else "0")
    if all(c == "0" for c in out):          # an exposed wall is never completely blank
        out[-1] = f"{rng.choice((1, 2))}{align}"
    return out


def tube_recipe(seed, depth=12.0, exposed=''):
    """exposed: '', 'L', 'R' or 'LR' -- which side walls may have windows.
    Returns (recipe, meta)."""
    rng = random.Random(seed)
    floors = pick(rng, FLOORS_W)
    n_up = floors - 1
    z = [0.0] + [GH + FH * i for i in range(n_up + 1)]
    roof_z = z[floors]

    side = {s: (side_column(rng, floors) if s in exposed else ['0'] * floors) for s in 'LR'}
    gf = pick(rng, GF_W)
    ufs = []
    for i in range(n_up):
        if ufs and rng.random() < REPEAT_P:
            m = ufs[-1]
        elif i == n_up - 1 and n_up > 1 and rng.random() < TOP_BALCONY_P:
            m = rng.choice(('UF_Balcony', 'UF_BalconySolid'))
        else:
            m = pick(rng, UF_W)
        ufs.append(m)

    top = pick(rng, TOP_W)
    color = pick(rng, ROOF_COLOR_W) if top != 'RF_Terrace' else None
    top_module = top if color is None else f"{top}_{color}"

    recipe = []
    for f in range(floors):
        k, front = ('GF', gf) if f == 0 else ('UF', ufs[f - 1])
        p = (0, 0, z[f])
        recipe += [(f'Back_{k}', p, 0), (f"SideL_{k}_{side['L'][f]}", p, 0),
                   (f"SideR_{k}_{side['R'][f]}", p, 0), (front, p, 0)]
        # props: AC units beside / under windows
        slots = {'UF_Window': (-1.45, 1.45), 'UF_Shutter': (-1.0, 1.0)}.get(front, ())
        for x in slots:
            if rng.random() < AC_P:
                recipe.append(('PR_AC', (x, 0, z[f] + 0.15), 0))
    recipe.append((top_module, (0, 0, roof_z), 0))
    if top == 'RF_Terrace' and rng.random() < TANK_P:
        t = tum_rect(depth)
        recipe.append(('PR_WaterTank', (1.4, round(rng.uniform(t['y0'] + 1.0, depth - 1.2), 2), roof_z), 90))

    meta = dict(floors=floors, gf=gf, upper=ufs, top=top, top_module=top_module, roof_color=color, side=side,
                exposed=exposed, depth=depth, roof_z=round(roof_z, 3))
    return recipe, meta


def signature(meta):
    """Shape identity (props ignored) used to keep library variants unique."""
    return (meta['depth'], meta['gf'], tuple(meta['upper']), meta['top'], meta['roof_color'],
            tuple(meta['side']['L']), tuple(meta['side']['R']))


# library plan: per depth bucket, how many houses of each exposure
PLAN = {'': 12, 'L': 5, 'R': 5, 'LR': 2}


def library_plan(seed0=2000):
    """Yields (vid, seed, recipe, meta) for every library house, all shapes unique."""
    seen = set()
    seed = seed0
    for depth in DEPTHS:
        i = 0
        for exposed, count in PLAN.items():
            made = 0
            while made < count:
                recipe, meta = tube_recipe(seed, depth, exposed)
                seed += 1
                sig = signature(meta)
                if sig in seen:
                    continue
                seen.add(sig)
                made += 1
                tag = exposed or 'C'
                yield f"TH_D{int(depth):02d}_{tag}_{i:02d}", seed - 1, recipe, meta
                i += 1
