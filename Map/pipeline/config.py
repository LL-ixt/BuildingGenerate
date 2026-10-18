"""Shared settings of the OSM pipeline: paths, road / sidewalk tables, street cross-section, lots."""
import math, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the Map folder
OVERRIDES = os.path.join(HERE, "overrides.geojson")
CHUNK = 200.0

SIDEWALK = {  # sidewalk width each side
    'motorway': 0, 'trunk': 4, 'primary': 4, 'secondary': 3.5, 'tertiary': 3, 'unclassified': 2,
    'residential': 1.5, 'living_street': 0, 'pedestrian': 0, 'service': 0,
}
OPEN_TAGS = {
    'leisure': {'park', 'garden', 'pitch', 'playground', 'stadium', 'recreation_ground', 'swimming_pool'},
    'landuse': {'grass', 'cemetery', 'recreation_ground', 'religious', 'village_green', 'meadow'},
    'amenity': {'parking'},
}
WATER_TAGS = {'natural': {'water'}, 'landuse': {'reservoir', 'basin'}, 'waterway': {'riverbank'}}
RAIL_CLEAR = 4.0          # m each side of an elevated line: never built on

# street cross-section, exported as city.json "street" so Unity builds the same shape
ROAD_Y = 0.02             # m: carriageway above the block ground
KERB_H = 0.20             # m: sidewalk top above the carriageway
KERB_LIP = 0.045          # m: vertical lip of the kerb on the road side
KERB_ANGLE = 30.0         # deg: sloped kerb face (Ref/sideway.png)
KERB_W = round((KERB_H - KERB_LIP) / math.tan(math.radians(KERB_ANGLE)), 3)   # ~0.27 m
KERB_STONE = 1.0          # m: kerb stone length (texture joints)
KERB_BULGE = 0.01         # m: the sloped face is slightly convex
KERB_VIEWS = [(-641, 294), (-381, -69)]   # report_kerb_<i>.png centres: a tertiary junction, Nguyen Trai x metro
# (across, up) from the top of the sidewalk side to the road; across 0 = road edge, negative = sidewalk side
KERB_PROFILE = [(round(-KERB_W * (1 - t), 4),
                 round(KERB_H - (KERB_H - KERB_LIP) * t + KERB_BULGE * math.sin(math.pi * t), 4))
                for t in (0.0, 1 / 3, 2 / 3, 1.0)] + [(0.0, 0.0)]
