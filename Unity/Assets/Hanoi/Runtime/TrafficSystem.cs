using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// TRAFFIC T3: all traffic of an area in ONE MonoBehaviour (no per-vehicle Update): motorbikes follow the lanes of
/// the TrafficNet (Map/pipeline/traffic.py), pooled MotoRigs with a rider each.
///  - car following: IDM (intelligent driver model) on the vehicle ahead on the lane, on the next lane and past a
///    junction link; Hanoi style: every bike keeps its own lateral offset in the lane and only follows a vehicle
///    that overlaps it sideways, so two bikes can ride side by side;
///  - junctions without lights: a vehicle reserves its link when it must stop or go (stopping distance + margin);
///    a link whose conflicting links (cross / merge) are held by someone else is a stop line; waiting more than
///    waitLimit s forces the entry (no gridlock);
///  - speeds: 26-40 km/h (random factor) limited by the lane / link speed (curves);
///  - spawn at the lanes that enter at the map edge, despawn at the exits; every spawn re-rolls bike paint,
///    shirt and helmet from the pooled materials;
///  - each bike is placed from its two axle points on the lane (slopes of the flyover), leans / steers with the
///    curvature (MotoRig.LeanFor / SteerFor).
/// Play mode: Start populates, Update steps. Editor tools: Init / Populate / Simulate / Pose.
/// </summary>
public class TrafficSystem : MonoBehaviour
{
    [Serializable]
    public class Slot { public MotoRig moto; public Renderer[] rider; public CarRig car; public Renderer[] paint; }   // a bike + rider, or a car

    [Serializable]
    public class Stats
    {
        public int spawned, finished, deadEnds, flyEnters, forced, collisionFrames;
        public float minDist = 99f, speedTime, vehTime, maxWait;
        public List<string> overlaps = new List<string>();     // the first few vehicle pairs closer than 0.8 m (debug)
        public float AvgKmh => vehTime > 0f ? speedTime / vehTime * 3.6f : 0f;
    }

    public TrafficNet net = new TrafficNet();
    public List<Slot> slots = new List<Slot>();
    [Tooltip("Paint materials M_Moto_0..5; rider materials [shirt * helmets + helmet].")]
    public Material[] bikeMats, riderMats, carMats;
    public int helmets = 6;
    public float[] paintWeights, shirtWeights, helmetWeights, carWeights;
    [Range(0f, 1f)] public float carShare = 0.15f;
    public int targetCount = 40;
    public int seed = 7;
    public Vector2 spawnInterval = new Vector2(1f, 2.5f);
    public float waitLimit = 6f;
    [Tooltip("Count vehicles in contact (statistics only, O(N^2): off in play mode, on in the editor tests).")]
    public bool measure = true;

    // IDM
    const float A = 1.6f, B = 2.5f, T = 0.9f, S0 = 1.0f, BikeLen = 1.9f, CarLen = 4.6f;
    const float BikeMax = 40f / 3.6f, CarMax = 45f / 3.6f, LatGap = 1.0f, CarLatGap = 1.7f;
    const float JunctionZone = 15f;       // m before a lane's end where bikes stop passing each other
    const float ShortLane = 20f;          // m: a lane this short before a junction link is looked through
    const float Margin = 0.55f;           // lane edge kept free by the lateral offsets (half bike width + a little)

    class Veh
    {
        public Slot slot;
        public int lane = -1, next = -1, next2 = -1, prev = -1, hold = -1, hold2 = -1;   // links held: the one on / next, and a second one ahead
        public float s, v, acc, factor, latFrac, lat, wait, steer, lean, steerT, leanT, dist;
        public bool active, force, blocked, onFly, car;
        public float len = BikeLen;
    }

    static GameObject Go(Slot sl) => sl.car != null ? sl.car.gameObject : sl.moto.gameObject;
    static float Half(Veh a, Veh o) => 0.5f * (a.len + o.len);
    static float MaxSpeed(Veh a) => a.car ? CarMax : BikeMax;

    public Stats stats = new Stats();
    System.Random rng;
    readonly List<Veh> vehs = new List<Veh>();
    int[] holders;
    List<Veh>[] byLane;
    List<int> sources = new List<int>();
    float spawnTimer, time;

    public int ActiveCount { get { int n = 0; foreach (var a in vehs) if (a.active) n++; return n; } }
    public int ActiveCars { get { int n = 0; foreach (var a in vehs) if (a.active && a.car) n++; return n; } }

    // ------------------------------------------------------------------ setup
    public void Init()
    {
        rng = new System.Random(seed);
        vehs.Clear();
        foreach (var sl in slots)
        {
            if (sl.moto == null && sl.car == null) continue;
            vehs.Add(new Veh { slot = sl, car = sl.car != null, len = sl.car != null ? CarLen : BikeLen });
            Go(sl).SetActive(false);
        }
        holders = new int[net.lanes.Count];
        byLane = new List<Veh>[net.lanes.Count];
        for (int i = 0; i < byLane.Length; i++) byLane[i] = new List<Veh>();
        sources.Clear();
        for (int i = 0; i < net.lanes.Count; i++) if (net.lanes[i].src && !net.lanes[i].link) sources.Add(i);
        stats = new Stats();
        spawnTimer = 0f;
        time = 0f;
    }

    /// Initial traffic: `count` bikes at random spots of the lanes (not on links), at least 8 m apart.
    public void Populate(int count, float minGap = 8f)
    {
        var cum = new List<float>();
        float tot = 0f;
        foreach (var l in net.lanes) { tot += l.link ? 0f : l.Length; cum.Add(tot); }
        int placed = 0;
        for (int tries = 0; tries < count * 60 && placed < count; tries++)
        {
            float u = (float)rng.NextDouble() * tot;
            int lane = cum.FindIndex(c => c >= u);
            if (lane < 0 || net.lanes[lane].link) continue;
            float s = (float)rng.NextDouble() * net.lanes[lane].Length;
            if (Occupied(lane, s, minGap)) continue;
            if (TrySpawn(lane, s, 0.7f)) placed++;
        }
        Pose();
    }

    bool Occupied(int lane, float s, float dist)
    {
        foreach (var a in vehs) if (a.active && a.lane == lane && Mathf.Abs(a.s - s) < dist) return true;
        return false;
    }

    static int Pick(float[] w, double u)
    {
        if (w == null || w.Length == 0) return 0;
        double acc = 0;
        for (int i = 0; i < w.Length; i++) if (u < (acc += w[i])) return i;
        return w.Length - 1;
    }

    bool TrySpawn(int lane, float s, float vFrac)
    {
        // cars only on lanes wide enough; when the car pool is used up a bike takes the place
        bool wantCar = rng.NextDouble() < carShare && net.lanes[lane].width >= 3.0f;
        Veh a = vehs.Find(x => !x.active && x.car == wantCar) ?? vehs.Find(x => !x.active && !x.car);
        if (a == null) return false;
        a.active = true;
        a.lane = lane; a.s = s; a.prev = -1; a.hold = a.hold2 = -1; a.next2 = -1;
        a.next = Choose(lane);
        a.factor = a.car ? Mathf.Lerp(0.75f, 1f, (float)rng.NextDouble()) : Mathf.Lerp(0.65f, 1f, (float)rng.NextDouble());
        a.latFrac = a.car ? 0f : (float)(rng.NextDouble() * 2 - 1);      // cars keep the lane centre
        a.lat = a.latFrac * LatMax(lane);
        a.v = vFrac * Mathf.Max(2.5f, Mathf.Min(net.lanes[lane].speed, MaxSpeed(a)) * a.factor);
        a.acc = a.wait = a.steer = a.lean = a.steerT = a.leanT = a.dist = 0f;
        a.force = a.blocked = false;
        a.onFly = net.lanes[lane].fly;
        if (a.car)
        {
            // random look: car paint
            if (carMats != null && carMats.Length > 0 && a.slot.paint != null)
            {
                var m = carMats[Mathf.Min(Pick(carWeights, rng.NextDouble()), carMats.Length - 1)];
                foreach (var r in a.slot.paint) if (r) r.sharedMaterial = m;
            }
        }
        else
        {
            // random look: bike paint, shirt, helmet
            if (bikeMats != null && bikeMats.Length > 0) a.slot.moto.SetPaint(bikeMats[Mathf.Min(Pick(paintWeights, rng.NextDouble()), bikeMats.Length - 1)]);
            if (riderMats != null && riderMats.Length > 0 && a.slot.rider != null)
            {
                int idx = Pick(shirtWeights, rng.NextDouble()) * helmets + Pick(helmetWeights, rng.NextDouble());
                var m = riderMats[Mathf.Min(idx, riderMats.Length - 1)];
                foreach (var r in a.slot.rider) if (r) r.sharedMaterial = m;
            }
        }
        Go(a.slot).SetActive(true);
        stats.spawned++;
        return true;
    }

    float LatMax(int lane) => Mathf.Max(0f, net.lanes[lane].width / 2f - Margin) * (net.lanes[lane].link ? 0.4f : 1f);   // tight inside junctions

    /// Next lane of `lane` for a vehicle: random, straight ahead is preferred.
    int Choose(int lane)
    {
        var nx = net.lanes[lane].next;
        if (nx == null || nx.Length == 0) return -1;
        float tot = 0f;
        foreach (var n in nx) tot += Weight(n);
        float u = (float)rng.NextDouble() * tot;
        foreach (var n in nx) { if ((u -= Weight(n)) <= 0f) return n; }
        return nx[nx.Length - 1];
    }

    float Weight(int lane) => Mathf.Abs(net.lanes[lane].turn) < 35f ? 4f : 1f;

    // ------------------------------------------------------------------ simulation
    void Start()
    {
        if (!Application.isPlaying) return;
        measure = false;
        Init();
        Populate(Mathf.RoundToInt(targetCount * 0.8f));
    }

    void Update()
    {
        if (!Application.isPlaying || vehs.Count == 0) return;
        Step(Mathf.Min(Time.deltaTime, 0.05f));
        Pose();
    }

    /// Runs the traffic for `seconds` in `dt` steps (tools / tests); call Pose() afterwards.
    public void Simulate(float seconds, float dt = 0.05f)
    {
        for (float t = 0f; t < seconds; t += dt) Step(dt);
        Pose();
    }

    public void Step(float dt)
    {
        time += dt;
        // spawn at the map edge
        spawnTimer -= dt;
        if (spawnTimer <= 0f && ActiveCount < targetCount && sources.Count > 0)
        {
            int lane = sources[rng.Next(sources.Count)];
            if (!Occupied(lane, 6f, 14f) && TrySpawn(lane, 0f, 0.9f))
                spawnTimer = Mathf.Lerp(spawnInterval.x, spawnInterval.y, (float)rng.NextDouble());
            else
                spawnTimer = 0.3f;
        }
        foreach (var l in byLane) l.Clear();
        foreach (var a in vehs) if (a.active) byLane[a.lane].Add(a);
        foreach (var a in vehs) if (a.active) a.acc = Accel(a);
        foreach (var a in vehs) if (a.active) Move(a, dt);
        if (measure) Measure(dt);
    }

    float Accel(Veh a)
    {
        var ln = net.lanes[a.lane];
        float v0 = Mathf.Max(2.5f, Mathf.Min(ln.speed, MaxSpeed(a)) * a.factor);
        float dEnd = ln.Length - a.s;
        float ratio = 0f;
        TrafficLane nl = a.next >= 0 ? net.lanes[a.next] : null;
        int beyond = nl != null && nl.link && nl.next.Length > 0 ? nl.next[0] : -1;   // lane after a junction link
        bool atSplit = nl != null && nl.link && !ln.link;             // the links of this lane share its end
        // only the lanes that matter are looked at (per-lane lists, rebuilt every step): the own lane, the next lane,
        // the lane past a junction link and the sibling links of this lane
        var same = byLane[a.lane];
        for (int i = 0; i < same.Count; i++)
        {
            var o = same[i];
            if (o == a || o.s <= a.s) continue;
            // no passing side by side near the end of a lane: the paths of the junction ahead split / merge there
            if (dEnd >= JunctionZone && Mathf.Abs(o.lat - a.lat) >= (a.car || o.car ? CarLatGap : LatGap)) continue;
            Lead(ref ratio, a.v, o.s - a.s - Half(a, o), o.v);
        }
        if (a.next >= 0)
        {
            var ahead = byLane[a.next];
            for (int i = 0; i < ahead.Count; i++)
            {
                var o = ahead[i];
                if (Mathf.Abs(o.lat - a.lat) >= (a.car || o.car ? CarLatGap : LatGap)) continue;
                Lead(ref ratio, a.v, dEnd + o.s - Half(a, o), o.v);
            }
            if (atSplit)
            {
                // another link out of the same lane: it starts where this one starts, so whoever is on it is ahead
                foreach (int sib in ln.next)
                {
                    if (sib == a.next) continue;
                    var other = byLane[sib];
                    for (int i = 0; i < other.Count; i++) Lead(ref ratio, a.v, dEnd + other[i].s - Half(a, other[i]), other[i].v);
                }
            }
        }
        if (beyond >= 0)
        {
            var past = byLane[beyond];
            for (int i = 0; i < past.Count; i++)
            {
                var o = past[i];
                if (Mathf.Abs(o.lat - a.lat) >= (a.car || o.car ? CarLatGap : LatGap)) continue;
                Lead(ref ratio, a.v, dEnd + nl.Length + o.s - Half(a, o), o.v);
            }
        }
        a.blocked = false;
        if (nl != null)
        {
            float vn = Mathf.Min(nl.speed, MaxSpeed(a)) * a.factor;    // slow down for the curve / lane ahead
            if (vn < a.v) Lead(ref ratio, a.v, dEnd - 0.5f * a.len, vn);
            // the junction ahead: its link is the next lane, or the one after a short lane between two junctions
            int tgt = -1;
            float dStop = dEnd;
            if (nl.link) tgt = a.next;
            else if (nl.Length < ShortLane && nl.next.Length > 0)
            {
                if (a.next2 < 0) a.next2 = Choose(a.next);
                if (a.next2 >= 0 && net.lanes[a.next2].link) { tgt = a.next2; dStop = dEnd + nl.Length; }
            }
            if (tgt >= 0 && a.hold != tgt && a.hold2 != tgt && dStop < a.v * a.v / (2f * B) + 3f)
            {
                if (a.force || CanEnter(tgt)) { Reserve(a, tgt); if (a.force) stats.forced++; }
                else { a.blocked = true; Lead(ref ratio, a.v, dStop - 0.5f * a.len - 0.1f, 0f); }
            }
        }
        float free = 1f - Mathf.Pow(a.v / v0, 4f);
        return Mathf.Clamp(A * (free - ratio * ratio), -7f, A);
    }

    static void Lead(ref float ratio, float v, float gap, float vl)
    {
        gap = Mathf.Max(gap, 0.1f);
        float star = S0 + Mathf.Max(0f, v * T + v * (v - vl) / (2f * Mathf.Sqrt(A * B)));
        ratio = Mathf.Max(ratio, star / gap);
    }

    void Reserve(Veh a, int link)
    {
        holders[link]++;
        if (a.hold < 0) a.hold = link; else a.hold2 = link;
    }

    bool CanEnter(int link)
    {
        foreach (int c in net.lanes[link].conflicts) if (holders[c] > 0) return false;
        return true;
    }

    void Move(Veh a, float dt)
    {
        a.v = Mathf.Max(0f, a.v + a.acc * dt);
        float ds = a.v * dt;
        a.s += ds;
        a.dist += ds;
        if (a.blocked && a.v < 0.5f)
        {
            a.wait += dt;
            stats.maxWait = Mathf.Max(stats.maxWait, a.wait);
            if (a.wait > waitLimit && !a.force)
            {
                a.force = true;
                if (stats.overlaps.Count < 14)
                    stats.overlaps.Add($"t {time:F1}s FORCED lane {a.lane} s {a.s:F1}/{net.lanes[a.lane].Length:F1} next {a.next} next2 {a.next2} hold {a.hold}/{a.hold2} " +
                                       $"conflicts held: {string.Join(",", System.Array.FindAll(net.lanes[a.next >= 0 && net.lanes[a.next].link ? a.next : a.next2 >= 0 ? a.next2 : 0].conflicts, c => holders[c] > 0))}");
            }
        }
        else if (!a.blocked) a.wait = 0f;
        var ln = net.lanes[a.lane];
        while (a.s > ln.Length)
        {
            a.s -= ln.Length;
            if (a.hold == a.lane) { holders[a.lane]--; a.hold = a.hold2; a.hold2 = -1; a.force = false; a.wait = 0f; }
            if (a.next < 0)
            {
                if (!ln.sink) stats.deadEnds++;
                Despawn(a);
                return;
            }
            a.prev = a.lane;
            a.lane = a.next;
            ln = net.lanes[a.lane];
            a.next = a.next2 >= 0 ? a.next2 : Choose(a.lane);
            a.next2 = -1;
            if (ln.link && a.hold != a.lane)                                      // could not stop in time
            {
                holders[a.lane]++;
                if (a.hold < 0) a.hold = a.lane; else { a.hold2 = a.hold; a.hold = a.lane; }
            }
            if (ln.fly && !a.onFly) stats.flyEnters++;
            a.onFly = ln.fly;
        }
        a.lat = Mathf.MoveTowards(a.lat, a.latFrac * LatMax(a.lane), 0.6f * dt);
        float k = net.Curvature(a.lane, a.s);
        a.steerT = a.car ? Mathf.Clamp(Mathf.Atan(a.slot.car.wheelbase * k) * Mathf.Rad2Deg, -30f, 30f) : a.slot.moto.SteerFor(k);
        a.leanT = a.car ? 0f : MotoRig.LeanFor(a.v, k);
        a.steer = Mathf.MoveTowards(a.steer, a.steerT, 90f * dt);
        a.lean = Mathf.MoveTowards(a.lean, a.leanT, 40f * dt);
    }

    void Despawn(Veh a)
    {
        if (a.hold >= 0) { holders[a.hold]--; a.hold = -1; }
        if (a.hold2 >= 0) { holders[a.hold2]--; a.hold2 = -1; }
        a.active = false;
        Go(a.slot).SetActive(false);
        stats.finished++;
    }

    void Measure(float dt)
    {
        for (int i = 0; i < vehs.Count; i++)
        {
            var a = vehs[i];
            if (!a.active) continue;
            stats.speedTime += a.v * dt;
            stats.vehTime += dt;
            var pa = net.Pos(a.lane, a.s, a.lat);
            for (int j = i + 1; j < vehs.Count; j++)
            {
                var b = vehs[j];
                if (!b.active) continue;
                var pb = net.Pos(b.lane, b.s, b.lat);
                if (Mathf.Abs(pa.y - pb.y) > 2f) continue;                 // flyover over the street
                float d = Mathf.Sqrt((pa.x - pb.x) * (pa.x - pb.x) + (pa.z - pb.z) * (pa.z - pb.z));
                if (d < stats.minDist) stats.minDist = d;
                if (d < (a.car ? 0.9f : 0.35f) + (b.car ? 0.9f : 0.35f))      // body half widths
                {
                    stats.collisionFrames++;
                    if (stats.overlaps.Count < 14)
                        stats.overlaps.Add($"t {time:F1}s d {d:F2}: A lane {a.lane}{(net.lanes[a.lane].link ? " link" : "")} s {a.s:F1}/{net.lanes[a.lane].Length:F1} v {a.v:F1} " +
                                           $"hold {a.hold} blk {a.blocked} frc {a.force} next {a.next} lat {a.lat:F1} | B lane {b.lane}{(net.lanes[b.lane].link ? " link" : "")} " +
                                           $"s {b.s:F1}/{net.lanes[b.lane].Length:F1} v {b.v:F1} hold {b.hold} blk {b.blocked} frc {b.force} next {b.next} lat {b.lat:F1}");
                }
            }
        }
    }

    // ------------------------------------------------------------------ pose
    Vector3 Sample(Veh a, float d)
    {
        float lat = a.lat;
        var l = net.lanes[a.lane];
        if (d > l.Length && a.next >= 0) return net.Pos(a.next, d - l.Length, lat);
        if (d < 0f && a.prev >= 0) return net.Pos(a.prev, net.lanes[a.prev].Length + d, lat);
        return net.Pos(a.lane, d, lat);
    }

    public void Pose()
    {
        foreach (var a in vehs)
        {
            if (!a.active) continue;
            float half = (a.car ? a.slot.car.wheelbase : a.slot.moto.wheelbase) * 0.5f;
            Vector3 f = Sample(a, a.s + half), r = Sample(a, a.s - half);
            var fwd = f - r;
            if (fwd.sqrMagnitude < 1e-6f) fwd = net.Dir(a.lane, a.s);
            var tr = a.car ? a.slot.car.transform : a.slot.moto.transform;
            tr.SetPositionAndRotation((f + r) * 0.5f, Quaternion.LookRotation(fwd, Vector3.up));
            if (a.car) a.slot.car.Drive(a.dist, a.steer);
            else a.slot.moto.Drive(a.dist, a.steer, a.lean);
            a.dist = 0f;
        }
    }

    // ------------------------------------------------------------------ tools
    /// Position / heading of an active bike (screenshots); onFlyover = only bikes on a flyover lane.
    public bool FindVehicle(bool onFlyover, out Vector3 pos, out Vector3 fwd)
    {
        foreach (var a in vehs)
        {
            if (!a.active || (onFlyover && !net.lanes[a.lane].fly) || a.lane < 0) continue;
            pos = net.Pos(a.lane, a.s, a.lat);
            fwd = net.Dir(a.lane, a.s);
            return true;
        }
        pos = fwd = Vector3.zero;
        return false;
    }

    /// An active car (screenshots), the one nearest to `near`.
    public bool FindCar(Vector3 near, out Vector3 pos, out Vector3 fwd)
    {
        float best = float.MaxValue;
        pos = fwd = Vector3.zero;
        foreach (var a in vehs)
        {
            if (!a.active || !a.car) continue;
            var p = net.Pos(a.lane, a.s, a.lat);
            float d = (p - near).sqrMagnitude;
            if (d >= best) continue;
            best = d; pos = p; fwd = net.Dir(a.lane, a.s);
        }
        return best < float.MaxValue;
    }

    /// The active bike nearest to `near` (screenshots).
    public bool FindVehicleNear(Vector3 near, out Vector3 pos, out Vector3 fwd)
    {
        float best = float.MaxValue;
        pos = fwd = Vector3.zero;
        foreach (var a in vehs)
        {
            if (!a.active) continue;
            var p = net.Pos(a.lane, a.s, a.lat);
            float d = (p - near).sqrMagnitude;
            if (d >= best) continue;
            best = d; pos = p; fwd = net.Dir(a.lane, a.s);
        }
        return best < float.MaxValue;
    }

    public int StuckCount(float seconds)
    {
        int n = 0;
        foreach (var a in vehs) if (a.active && a.wait > seconds) n++;
        return n;
    }

    public string Summary() =>
        $"active {ActiveCount} ({ActiveCars} cars), spawned {stats.spawned}, left the map {stats.finished}, avg speed {stats.AvgKmh:F1} km/h, " +
        $"min centre distance {stats.minDist:F2} m, frames under 0.8 m {stats.collisionFrames}, forced entries {stats.forced}, " +
        $"max wait {stats.maxWait:F1} s, stuck now {StuckCount(20f)}, flyover entries {stats.flyEnters}, dead ends {stats.deadEnds}";
}
