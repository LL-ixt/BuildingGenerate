"""CAR — VinFast LUX A2.0 low-poly from the Sketchfab model (CC-BY-4.0, see CREDIT).

Pure data + helpers shared by build_car.py: which source material is which slot, the wheel layout.
"""

SRC_GLTF = r"C:\Users\Admin\Downloads\vinfast_lux_a2.0\scene.gltf"
CREDIT = ('This work is based on "VinFast LUX A2.0" (https://sketchfab.com/3d-models/'
          'vinfast-lux-a20-9089d4d7f1ea4de5a4cf924ed6e01410) by Dave Love SketchFab '
          '(https://sketchfab.com/Tyler_Dave) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)')

# real car, only to check the import scale (not forced): length, width, height, wheelbase (m)
REAL_DIMS = (4.973, 1.900, 1.464, 2.933)

# source material name (without the .00N suffix) -> slot; None = interior, deleted
SLOT_OF = {
    'EXT_Body': 'paint', 'metallic_PRIMARY': 'paint',
    'ext_glass': 'glass', 'mirror': 'trim',
    'light_glass': 'light', 'chrome_light': 'light', 'rearlight': 'light', 'rearlight_nm': 'light',
    'svitit': 'light', 'platelights': 'light', 'pidsvitknomera': 'light',
    'chrome_trim': 'chrome', 'chrome_metal': 'chrome', 'chrome_exh': 'chrome', 'chrome_door': 'chrome',
    'metal_ext': 'trim',                       # 410k tris of chassis / engine / suspension, dark metal from outside
    'black': 'trim', 'blackunder': 'trim', 'plastic_ext': 'trim', 'base_black': 'trim', 'blackplastic': 'trim',
    'Metal_ch': 'trim', 'plastic_ie': 'trim',  # plastic_ie = rear plate frame
    'plate': 'plate',
    'EXT_TYRE': 'tyre', 'rim_ao': 'rim', 'lug': 'rim', 'wheelbadge': 'rim',
    'DISC_BRAKE': 'brake', 'caliper': 'brake',
}
# decided from where the faces are (build_car.py --inspect, 2026-10-19): all inside the cabin / under the bonnet
# -> interior: chrome_metaltrim, black_vent, common_black053, bw00a (cabin), bw033b2, carbon (engine bay),
# PLASTIC_WHEEL (the steering wheel!), black.003 (roof light housing)
INTERIOR_EXACT = {'black.003'}
AMBIGUOUS = set()
WHEEL_SLOTS = {'tyre', 'rim', 'brake'}
BODY_SLOTS = ['paint', 'glass', 'light', 'chrome', 'trim', 'plate']


# ---- C2 LOD0 (build_car.py -- --lod0)
SLOTS = ['paint', 'glass', 'light', 'chrome', 'trim', 'plate', 'tyre', 'rim']     # face attribute 'slot' = index
VOXEL = 0.025              # m: remesh of the exterior into one closed shell
BODY_TRIS = 2600           # decimate target of the body shell (LOD0)
SMOOTH_ANGLE = 35.0        # deg: shade smooth, sharper edges stay hard
BAKE_RES = 1024            # px: body texture (slot map in C2; albedo / normal in C3)
BAKE_MARGIN = 8            # px of bleed around the UV islands
WHEEL_SIDES = 16           # LOD0 wheel: tyre revolved with this many segments
RIM_INSET = 0.03           # m: rim disc set back from the tyre's outer sidewall
SEAT_BOXES = [             # dark seat backs behind the tinted glass: (centre x, y, z), size (x, y, z)
    ((0.0, -0.05, 0.85), (1.30, 0.12, 0.55)),       # front row
    ((0.0, 0.85, 0.85), (1.35, 0.12, 0.50)),        # rear bench
]


# ---- C3 textures, LODs, export (build_car.py -- --c3)
TEX_RES = 1024
BODY_UV = 0.8              # body UV islands packed into [0, 0.8]^2; the right / top strip holds the wheel tiles
RIM_RECT = (0.8, 0.8, 1.0, 1.0)      # rim face (rendered from the source wheel), u0 v0 u1 v1
TYRE_RECT = (0.8, 0.6, 1.0, 0.8)     # flat tyre rubber
TYRE_SRGB = (0.055, 0.055, 0.06)
GLASS_SRGB = (0.035, 0.042, 0.05)    # tinted glass albedo (the cabin is gone)
PAINT_GREY = 0.8                     # paint baked neutral; the shader multiplies by _PaintColor
LENS_FRONT_SRGB = (0.78, 0.80, 0.82) # clear lamp lenses bake dark: stand-in colours by position
LENS_REAR_SRGB = (0.50, 0.04, 0.05)
CAGE = 0.08                          # m: bake cage (the decimated shell sinks up to a few cm into the source)
# per slot: roughness, metallic, lamp emission, paint mask -> _DataMap RGBA
SLOT_DATA = {'paint': (0.30, 0.0, 0.0, 1.0), 'glass': (0.05, 0.0, 0.0, 0.0), 'light': (0.15, 0.0, 0.8, 0.0),
             'chrome': (0.15, 1.0, 0.0, 0.0), 'trim': (0.70, 0.0, 0.0, 0.0), 'plate': (0.55, 0.0, 0.0, 0.0)}
RIM_DATA = (0.35, 0.8, 0.0, 0.0)
TYRE_DATA = (0.90, 0.0, 0.0, 0.0)
# LODs: body triangle budget, wheel sides, tyre profile points
LODS = [dict(body=None, sides=16, profile=8), dict(body=700, sides=10, profile=6), dict(body=250, sides=6, profile=4)]
NAME = 'SM_Car_LuxA2'
PAINT_COLOURS = [            # sRGB, Hanoi street mix: white, black, silver, red, dark blue, grey
    (0.92, 0.92, 0.90), (0.05, 0.05, 0.06), (0.62, 0.64, 0.66), (0.62, 0.06, 0.07), (0.08, 0.14, 0.32),
    (0.36, 0.37, 0.39)]


def base_name(mat_name):
    """'EXT_Body.001' -> 'EXT_Body'."""
    n = mat_name
    while len(n) > 4 and n[-4] == '.' and n[-3:].isdigit():
        n = n[:-4]
    return n


def slot_of(mat_name):
    """Slot of a source material; None = interior (everything not listed and not ambiguous)."""
    if mat_name in INTERIOR_EXACT:
        return None
    b = base_name(mat_name)
    if b in SLOT_OF:
        return SLOT_OF[b]
    if b in AMBIGUOUS:
        return 'ambiguous'
    return None
