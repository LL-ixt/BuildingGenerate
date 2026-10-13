"""M5/M6: benchmark fly-through path for CityBenchmark (Unity), from a real street of Map/out/city.json.

    python Tools/make_bench_path.py [road name]

Writes Unity/Assets/StreamingAssets/bench_path.json. Unity coords: x = east, z = north (city.json x, y).
Segments (name, speed m/s, look-ahead m, pitch deg down):
    street   along the road centre at eye height (1.7 m above the road)
    rise     back along the road, climbing to 50 m
    low80    80 m drone flight across the map (crosses many chunk borders: streaming at speed)
    drone300 300 m flight diagonal over the whole map
    high     1.5 km overview
"""
import os, sys, json, math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CITY = os.path.join(ROOT, "Map", "out", "city.json")
OUT = os.path.join(ROOT, "Unity", "Assets", "StreamingAssets", "bench_path.json")
ROAD = sys.argv[1] if len(sys.argv) > 1 else "Phố Thượng Đình"


def length(line):
    return sum(math.dist(line[i], line[i + 1]) for i in range(len(line) - 1))


def main():
    d = json.load(open(CITY, encoding="utf-8"))
    x0, y0, x1, y1 = d['bounds']
    road_y = d['street']['road_y']
    roads = [r for r in d['roads'] if r['name'] == ROAD and not r['bridge'] and r['layer'] == 0]
    if not roads:
        raise SystemExit(f"road '{ROAD}' not found")
    road = max(roads, key=lambda r: length(r['line']))
    line = [p for p in road['line'] if x0 + 50 < p[0] < x1 - 50 and y0 + 50 < p[1] < y1 - 50]
    eye = road_y + 1.7
    street = [[p[0], eye, p[1]] for p in line]

    # rise: from the street end, back along the last 250 m of the road, up to 50 m
    back = list(reversed(line))
    acc, rise = 0.0, []
    for i, p in enumerate(back):
        if i:
            acc += math.dist(back[i - 1], p)
        rise.append([p[0], eye + (50 - eye) * min(1.0, acc / 250.0), p[1]])
        if acc > 250:
            break

    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    low80 = [[rise[-1][0], 80.0, rise[-1][2]], [cx - 0.35 * (x1 - x0), 80.0, cy + 0.3 * (y1 - y0)]]
    drone = [[x0 + 150, 300.0, y0 + 150], [x1 - 150, 300.0, y1 - 150]]
    high = [[cx - 600, 1500.0, y0 - 600], [cx + 600, 1500.0, y0 - 600]]

    path = dict(road=ROAD, segments=[
        dict(name="street", speed=12.0, lookAhead=20.0, pitch=2.0, points=street),
        dict(name="rise", speed=10.0, lookAhead=20.0, pitch=12.0, points=rise),
        dict(name="low80", speed=25.0, lookAhead=60.0, pitch=22.0, points=low80),
        dict(name="drone300", speed=45.0, lookAhead=100.0, pitch=30.0, points=drone),
        dict(name="high", speed=60.0, lookAhead=100.0, pitch=45.0, points=high),
    ])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # JsonUtility reads Vector3 as {"x":..,"y":..,"z":..}
    for s in path['segments']:
        s['points'] = [dict(x=round(p[0], 2), y=round(p[1], 2), z=round(p[2], 2)) for p in s['points']]
        n = len(s['points'])
        L = sum(math.dist((a['x'], a['y'], a['z']), (b['x'], b['y'], b['z'])) for a, b in zip(s['points'], s['points'][1:]))
        print(f"[bench] {s['name']:9s} {n:3d} points, {L:7.0f} m, {L / s['speed']:5.1f} s")
    json.dump(path, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[bench] wrote", OUT)


if __name__ == "__main__":
    main()
