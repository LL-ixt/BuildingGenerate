"""RIDER — male motorbike rider from MakeHuman (MPFB) for far views. Settings shared by build_rider.py.

Assets (downloaded into Blender/rider/assets, see the credits):
  polo/      Male Polo Shirt (MakeHuman community, CC0, author Namuhekam)
  trousers/  M Trousers 01 (MakeHuman community node/746, CC-BY)
  helmet/    "Mu bao hiem samsung" (Sketchfab, CC-BY-4.0, 3dpro.com.vn) - its texture is cleaned of all lettering
"""
import os

ROOT = r"D:\Project III\BuildingGenerate"
ASSETS = os.path.join(ROOT, "Blender", "rider", "assets")
POLO = os.path.join(ASSETS, "polo", "Polo_t-shirt.mhclo")
TROUSERS = os.path.join(ASSETS, "trousers", "m_trousers_01.mhclo")
HELMET = os.path.join(ASSETS, "helmet", "scene.gltf")
HELMET_TEX = os.path.join(ASSETS, "helmet", "textures", "image_baseColor.png")

CREDITS = {
    'polo': 'Male Polo Shirt by Namuhekam, MakeHuman community, CC0',
    'trousers': 'M Trousers 01, MakeHuman community (http://www.makehumancommunity.org/node/746), CC-BY',
    'helmet': 'This work is based on "Mu bao hiem samsung" (https://sketchfab.com/3d-models/'
              'mu-bao-hiem-samsung-89f64ad1071b48939603b8c0fd790b4e) by 3dpro.com.vn (https://sketchfab.com/hai3dpro) '
              'licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)',
    'body': 'MakeHuman / MPFB base mesh (CC0 output)',
}

# MakeHuman macros (0..1): adult Vietnamese man, average build
MACROS = dict(gender=1.0, age=0.6, muscle=0.5, weight=0.5, proportions=0.5, cupsize=0.5, firmness=0.5,
              race=dict(asian=1.0, caucasian=0.0, african=0.0))
TARGET_HEIGHT = 1.68       # m, found by bisection on the 'height' macro
SKIN_SRGB = (0.72, 0.55, 0.43)   # flat skin colour (no MakeHuman skin textures installed; far view only)

# helmet: the source model lies on its side (its up axis is -y after the glTF import) -> HELMET_UP_FIX (deg about x);
# the peak (black visor, material image.007) then decides the yaw so that it faces -y = forward.
HELMET_SHELL_MATERIAL = 'image'
HELMET_PEAK_MATERIAL = 'image.007'
HELMET_UP_FIX = -90.0
HELMET_CLEARANCE = 0.015   # m between the skull and the inside of the shell (sides and top)
HELMET_SCALE = 1.0         # extra factor on the fitted size (hand tuning)
# user's hand fit in Blender (2026-10-20: smaller, not over the eyes): object scale + pivot (shell centre) location,
# applied after the automatic fit; None = automatic only
HELMET_HAND = dict(scale=0.8316, location=(-0.0023, -0.0405, 1.6472))
HELMET_SHELL_T = 0.012     # m: shell thickness (outside top = head top + clearance + this)
LETTERING_DIST = 0.12      # texel colour distance from the shell colour above which a texel is lettering

# shoes: ELVS zombie killer sneakers (MakeHuman community, CC-BY), recoloured black / white
SHOES = os.path.join(ASSETS, "shoes", "elvs_zombiekiller_sneakers1.mhclo")
SHOES_TEX = os.path.join(ASSETS, "shoes", "sneakerstexture1.png")
CREDITS['shoes'] = 'ELVS Zombie Killer Sneakers, MakeHuman community (makehumancommunity.org/clothes/elvs_zombie_killer_sneakers.html), CC-BY'

# ---- R2 pose on the Honda SH (anchors of Export/Vehicles/vehicles.json, Unity -> Blender (-x, -z, y))
MOTO_ID = 'SM_Moto_SH'
MOTO_FBX = os.path.join(ROOT, "Export", "Vehicles", "FBX", "SM_Moto_SH.fbx")
RIG = 'game_engine'
HIP_ABOVE_SEAT = (0.0, -0.05, 0.10)  # hip joints (thigh heads) above the seat top found under SEAT_ANCHOR
ANKLE_FROM_FOOT = (0.0, 0.03, 0.085) # ankle above the floorboard top found under FOOT_L/R, a bit back
WRIST_FROM_GRIP = (0.02, 0.07, 0.0)  # wrist relative to HAND_L/R; x is towards the bike's centre line
LEAN_DEG = 18.0                      # torso forward lean (spine_01); neck + head turn it back to look ahead
KNEE_POLE = (0.06, -0.6, 0.35)       # pole point offsets from the hip-ankle midpoint (x outward); knees together (ref)
ELBOW_POLE = (0.15, 0.30, -0.45)     # from the shoulder-wrist midpoint (x outward): elbows a bit out, down, back
FINGER_CURL_DEG = 55.0               # around the grip
FOOT_DIR = (0.0, -1.0, -0.25)        # ankle -> ball direction (flat on the floorboard)

# after posing: helmet pre-reduced (it is a 940k-tri scan), then every face hidden inside the clothes / helmet goes
HELMET_PRE_TRIS = 15000
CULL_RAYS = 10                       # rays per face (normal + a fixed cone); all blocked = hidden face
CULL_CONE_DEG = 70.0
POLO_INFLATE = 0.006                 # m: the polo pushed out along its normals so the trousers' waistband stays under it

# ---- R3 reduction, bake, LODs, export (build_rider.py -- --r3)
NAME = 'SM_Rider_M'
# LOD0 triangle budget per frozen part (symmetric collapse decimate), LOD1 = the joined LOD0 decimated to LOD1_TRIS
PART_TRIS = {'Human': 650, 'Polo': 300, 'trousers': 220, 'sneakers': 120, 'Helmet': 210}
LOD1_TRIS = 500
# clean-up before the decimate (a collapse cannot remove loose pieces: the scanned helmet has ~1100 of them, the
# sneakers ~550: laces, eyelets, sole layers)
MIN_ISLAND = {'Helmet': 0.01}   # loose pieces under this fraction of the part's area are dropped
# parts replaced by convex hulls (colours still baked from the originals): 'side' = one per foot (x < 0 / x > 0),
# 'island' = one per kept loose piece (helmet shell, peak, ...: the scan is open / non-manifold and does not collapse)
HULL_PARTS = {'sneakers': 'side', 'Helmet': 'island'}
ATLAS_RES = 512
BAKE_CAGE = 0.02          # m (fingers, ears: thin parts)
BAKE_MARGIN = 4
SHIRT_GREY = 0.8          # sRGB grey the shirt is baked at; Hanoi/Vehicle multiplies by _PaintColor / 0.604
ROUGHNESS = {'Human': 0.65, 'Polo': 0.85, 'trousers': 0.9, 'sneakers': 0.6, 'Helmet': 0.3}
SHIRT_COLOURS = [          # sRGB, common shirt colours: white, light blue, navy, grey, dark green, maroon
    (0.88, 0.88, 0.86), (0.55, 0.68, 0.82), (0.12, 0.17, 0.32), (0.45, 0.46, 0.47), (0.16, 0.30, 0.20),
    (0.42, 0.10, 0.12)]
# helmet shell (material HELMET_SHELL_MATERIAL) baked grey too, its mask in data B -> Hanoi/Vehicle _PaintColor2
HELMET_GREY = 0.8
HELMET_COLOURS = [         # sRGB: white, black, red, blue, silver, yellow
    (0.90, 0.90, 0.88), (0.06, 0.06, 0.07), (0.62, 0.08, 0.09), (0.10, 0.25, 0.60), (0.55, 0.56, 0.58),
    (0.85, 0.70, 0.10)]
