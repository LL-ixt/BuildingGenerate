using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Debug = UnityEngine.Debug;

/// <summary>
/// TRAFFIC T3: the Chùa Bộc test area's traffic. Reads city.json "traffic" (Map/pipeline/traffic.py) into a
/// TrafficNet, pools motorbikes with riders (SM_Moto_SH_Rig + HanoiRiders.Ride) and saves
/// Assets/Hanoi/FlyoverTest/Traffic.unity (one TrafficSystem; open it next to the city + flyover scenes and press
/// Play). Menu "Hanoi/Flyover Test/Traffic/..." or batch: -executeMethod TrafficBuilder.RunBatch
/// (build, simulate 120 s from the editor, log the numbers, shots ft_t3_*).
/// </summary>
public static class TrafficBuilder
{
    public const string ScenePath = "Assets/Hanoi/FlyoverTest/Traffic.unity";
    const int PoolSize = 48;      // bikes
    const int PoolCars = 14;      // cars (~15 % of the traffic)

    [Serializable] class CityJ { public StreetJ street; public TrafficJ traffic; }
    [Serializable] class StreetJ { public float road_y; }
    [Serializable] class TrafficJ { public LaneJ[] lanes; public int[] conflicts; }
    [Serializable] class LaneJ { public int id; public string kind; public float width, speed; public int[] next; public bool src, sink; public float[] pts; }

    // ------------------------------------------------------------------ build
    [MenuItem("Hanoi/Flyover Test/Traffic/Build Traffic Scene")]
    public static void Build() => CityTarget.With(CityTarget.FlyoverTest, BuildInTarget);

    static TrafficNet LoadNet()
    {
        var c = JsonUtility.FromJson<CityJ>(File.ReadAllText(CityTarget.CityJson));
        float roadY = c.street != null ? c.street.road_y : 0.02f;
        var net = new TrafficNet();
        var T = c.traffic;
        for (int i = 0; i < T.lanes.Length; i++)
        {
            var j = T.lanes[i];
            if (j.id != i) throw new Exception($"traffic lane ids must equal their index ({j.id} at {i})");
            var pts = new Vector3[j.pts.Length / 3];
            for (int k = 0; k < pts.Length; k++)                      // map x, y, z -> Unity x, z, y (+ road height)
                pts[k] = new Vector3(j.pts[3 * k], roadY + j.pts[3 * k + 2], j.pts[3 * k + 1]);
            var l = new TrafficLane
            {
                pts = pts, next = j.next ?? new int[0], width = j.width, speed = j.speed / 3.6f,
                src = j.src, sink = j.sink, link = j.kind == "link", fly = j.pts.Where((v, k) => k % 3 == 2).Max() > 0.05f,
            };
            TrafficNet.Measure(l);
            net.lanes.Add(l);
        }
        var conf = new System.Collections.Generic.List<int>[net.lanes.Count];
        for (int i = 0; i < conf.Length; i++) conf[i] = new System.Collections.Generic.List<int>();
        for (int i = 0; i + 1 < T.conflicts.Length; i += 2)
        {
            conf[T.conflicts[i]].Add(T.conflicts[i + 1]);
            conf[T.conflicts[i + 1]].Add(T.conflicts[i]);
        }
        for (int i = 0; i < conf.Length; i++) net.lanes[i].conflicts = conf[i].ToArray();
        return net;
    }

    static void BuildInTarget()
    {
        var net = LoadNet();
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var root = new GameObject("Traffic");
        var sys = root.AddComponent<TrafficSystem>();
        sys.net = net;
        sys.bikeMats = Enumerable.Range(0, HanoiMotos.Paints.Length).Select(HanoiMotos.LoadMaterial).ToArray();
        sys.helmets = HanoiRiders.Helmets.Length;
        sys.riderMats = Enumerable.Range(0, HanoiRiders.Shirts.Length)
            .SelectMany(s => Enumerable.Range(0, HanoiRiders.Helmets.Length).Select(h => HanoiRiders.LoadMaterial(s, h))).ToArray();
        sys.paintWeights = HanoiMotos.PaintWeights;
        sys.shirtWeights = HanoiRiders.ShirtWeights;
        sys.helmetWeights = HanoiRiders.HelmetWeights;
        var rigPrefab = HanoiMotos.LoadPrefab("SM_Moto_SH_Rig");
        if (rigPrefab == null || HanoiRiders.LoadPrefab(HanoiRiders.RiderId) == null)
            throw new Exception("moto rig / rider prefabs missing: run HanoiMotos.ImportMotos and HanoiRiders.ImportRiders first");
        var pool = new GameObject("Pool").transform;
        pool.SetParent(root.transform, false);
        for (int i = 0; i < PoolSize; i++)
        {
            var b = (GameObject)PrefabUtility.InstantiatePrefab(rigPrefab, pool);
            b.name = $"Bike_{i:00}";
            var rider = HanoiRiders.Ride(b.transform, 0, 0);
            sys.slots.Add(new TrafficSystem.Slot
            {
                moto = b.GetComponent<MotoRig>(),
                rider = rider.GetComponentsInChildren<Renderer>(),
            });
            b.SetActive(false);
        }
        // cars (T4): LUX A2 rig with a pooled paint material per colour
        var carPrefab = HanoiCars.LoadPrefab("SM_Car_LuxA2_Rig");
        if (carPrefab == null) throw new Exception("car rig prefab missing: run HanoiCars.ImportCars first");
        sys.carMats = Enumerable.Range(0, HanoiCars.Paints.Length)
            .Select(k => HanoiCars.LoadParked(k).GetComponentInChildren<Renderer>().sharedMaterial).ToArray();
        sys.carWeights = HanoiCars.PaintWeights;
        for (int i = 0; i < PoolCars; i++)
        {
            var c = (GameObject)PrefabUtility.InstantiatePrefab(carPrefab, pool);
            c.name = $"Car_{i:00}";
            sys.slots.Add(new TrafficSystem.Slot { car = c.GetComponent<CarRig>(), paint = c.GetComponentsInChildren<Renderer>() });
            c.SetActive(false);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.Combine(HanoiSetup.ProjectDir, ScenePath)));
        EditorSceneManager.SaveScene(scene, ScenePath);
        int links = net.lanes.Count(l => l.link), fly = net.lanes.Count(l => l.fly && !l.link);
        Debug.Log($"[Traffic] scene {ScenePath}: {net.lanes.Count} lanes ({links} links, {fly} on the flyover), " +
                  $"{PoolSize} pooled bikes + {PoolCars} cars");
    }

    // ------------------------------------------------------------------ open
    [MenuItem("Hanoi/Flyover Test/Traffic/Open City + Flyover + Traffic")]
    public static void Open() => CityTarget.With(CityTarget.FlyoverTest, OpenInTarget);

    static void OpenInTarget()
    {
        CityPlacer.OpenAll();
        if (File.Exists(Path.Combine(HanoiSetup.ProjectDir, FlyoverBuilder.ScenePath)))
            EditorSceneManager.OpenScene(FlyoverBuilder.ScenePath, OpenSceneMode.Additive);
        EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Additive);
    }

    // ------------------------------------------------------------------ test + shots
    [MenuItem("Hanoi/Flyover Test/Traffic/Run Test + Shots")]
    public static void RunTest() => CityTarget.With(CityTarget.FlyoverTest, TestInTarget);

    static void TestInTarget()
    {
        OpenInTarget();
        EditorSettings.asyncShaderCompilation = false;
        var sys = UnityEngine.Object.FindFirstObjectByType<TrafficSystem>();
        sys.Init();
        sys.Populate(32);
        const float dt = 0.05f;
        var sw = new Stopwatch();
        for (int t = 1; t <= 120; t++)
        {
            sw.Start();
            for (float x = 0f; x < 1f; x += dt) sys.Step(dt);
            sw.Stop();
            if (t % 30 == 0) Debug.Log($"[Traffic] T3 t = {t} s: {sys.Summary()}");
        }
        sys.Pose();
        foreach (var o in sys.stats.overlaps) Debug.Log("[Traffic] overlap " + o);
        Debug.Log($"[Traffic] T3 cost of the model: {sw.Elapsed.TotalMilliseconds / (120f / dt):F3} ms per 50 ms step " +
                  $"({sys.ActiveCount} bikes)");

        var (flys, roadY) = FlyoverBuilder.Load();
        var f = flys[0];
        var path = new FlyoverBuilder.Path3(f, roadY);
        Vector3 G(float s) { var q = path.Pos(s); q.y = 0.2f; return q; }
        var mid = G((f.clear_from + f.clear_to) / 2f);
        var inward = new Vector3(-mid.x, 0f, -mid.z).normalized;
        var cam = Camera.main;
        // eye level on the road: a ground lane point 30-45 m from the junction, looking at it
        Vector3 eye = mid + inward * 38f;
        float bestD = float.MaxValue;
        foreach (var l in sys.net.lanes)
        {
            if (l.link || l.fly) continue;
            foreach (var q in l.pts)
            {
                float d = Vector3.Distance(new Vector3(q.x, 0f, q.z), new Vector3(mid.x, 0f, mid.z));
                if (d > 30f && d < 45f && Mathf.Abs(d - 38f) < bestD) { bestD = Mathf.Abs(d - 38f); eye = q; }
            }
        }
        HanoiSetup.Shot(cam, "ft_t3_1_junction_eye", eye + Vector3.up * 1.7f, mid + Vector3.up * 1.2f);
        HanoiSetup.Shot(cam, "ft_t3_2_drone", mid + inward * 55f + Vector3.up * 32f, mid);
        HanoiSetup.ShotSized(cam, "ft_t3_3_top", mid + Vector3.up * 220f, mid, 1600, 1600);
        float sd = f.clear_from - 30f;
        var right = new Vector3(path.Dir(sd).z, 0f, -path.Dir(sd).x);
        HanoiSetup.Shot(cam, "ft_t3_4_deck", path.Pos(sd) + Vector3.up * 1.5f + right * 1.5f, path.Pos(sd + 60f) + Vector3.up * 1f);
        if (sys.FindVehicle(true, out var p, out var fwd) || sys.FindVehicle(false, out p, out fwd))
            HanoiSetup.Shot(cam, "ft_t3_5_chase", p - fwd * 7f + Vector3.up * 3f, p + Vector3.up * 1f);
        if (sys.FindVehicleNear(mid, out p, out fwd))
            HanoiSetup.Shot(cam, "ft_t3_6_near_junction", p - fwd * 9f + Vector3.up * 2.4f + new Vector3(fwd.z, 0f, -fwd.x) * 2.5f, p + Vector3.up * 1f);
        if (sys.FindCar(mid, out p, out fwd))
        {
            var side = new Vector3(fwd.z, 0f, -fwd.x);
            HanoiSetup.Shot(cam, "ft_t4_1_car_chase", p - fwd * 10f + Vector3.up * 3f + side * 2f, p + Vector3.up * 1f);
            HanoiSetup.Shot(cam, "ft_t4_2_car_side", p + side * 8f + fwd * 4f + Vector3.up * 1.6f, p + Vector3.up * 0.8f);
        }
        if (sys.FindVehicleNear(mid + inward * 60f, out p, out fwd))
            HanoiSetup.Shot(cam, "ft_t3_7_front", p + fwd * 12f + Vector3.up * 1.6f, p + Vector3.up * 1f);
        Debug.Log($"[Traffic] shots in {HanoiSetup.ShotsDir}");
    }

    // ------------------------------------------------------------------ stress test (rush hour, step 1: measure)
    /// Rush-hour load: N vehicles (85 % bikes) packed on the lanes. Per N: cost of the traffic model per step and
    /// contacts / waits over 60 s, plus drone / eye shots for 300 and 600. Nothing is saved.
    [MenuItem("Hanoi/Flyover Test/Traffic/Stress Test (rush hour)")]
    public static void RunStress() => CityTarget.With(CityTarget.FlyoverTest, StressInTarget);

    static void GrowPool(TrafficSystem sys, int bikes, int cars)
    {
        var pool = sys.transform.Find("Pool");
        var bikePrefab = HanoiMotos.LoadPrefab("SM_Moto_SH_Rig");
        var carPrefab = HanoiCars.LoadPrefab("SM_Car_LuxA2_Rig");
        int haveBikes = sys.slots.Count(s => s.moto != null), haveCars = sys.slots.Count(s => s.car != null);
        for (int i = haveBikes; i < bikes; i++)
        {
            var b = (GameObject)PrefabUtility.InstantiatePrefab(bikePrefab, pool);
            var rider = HanoiRiders.Ride(b.transform, 0, 0);
            sys.slots.Add(new TrafficSystem.Slot { moto = b.GetComponent<MotoRig>(), rider = rider.GetComponentsInChildren<Renderer>() });
            b.SetActive(false);
        }
        for (int i = haveCars; i < cars; i++)
        {
            var c = (GameObject)PrefabUtility.InstantiatePrefab(carPrefab, pool);
            sys.slots.Add(new TrafficSystem.Slot { car = c.GetComponent<CarRig>(), paint = c.GetComponentsInChildren<Renderer>() });
            c.SetActive(false);
        }
    }

    static void StressInTarget()
    {
        OpenInTarget();
        EditorSettings.asyncShaderCompilation = false;
        var sys = UnityEngine.Object.FindFirstObjectByType<TrafficSystem>();
        var (flys, roadY) = FlyoverBuilder.Load();
        var path = new FlyoverBuilder.Path3(flys[0], roadY);
        var mid = path.Pos((flys[0].clear_from + flys[0].clear_to) / 2f); mid.y = 0.2f;
        var inward = new Vector3(-mid.x, 0f, -mid.z).normalized;
        var cam = Camera.main;
        var views = new[]
        {
            ("drone", mid + inward * 55f + Vector3.up * 32f, mid),
            ("eye", mid + inward * 38f + Vector3.up * 1.7f, mid + Vector3.up * 1.2f),
        };
        foreach (int n in new[] { 50, 150, 300, 600 })
        {
            GrowPool(sys, Mathf.RoundToInt(n * 0.85f) + 4, Mathf.RoundToInt(n * 0.15f) + 2);
            sys.targetCount = n;
            sys.spawnInterval = new Vector2(0.05f, 0.1f);
            sys.seed = 11;
            sys.measure = false;
            sys.Init();
            sys.Populate(n, 4.5f);
            int placed = sys.ActiveCount;
            sys.Simulate(30f);                                      // settle
            var sw = Stopwatch.StartNew();
            for (int i = 0; i < 200; i++) sys.Step(0.05f);
            double stepMs = sw.Elapsed.TotalMilliseconds / 200;
            sw.Restart();
            for (int i = 0; i < 20; i++) sys.Pose();
            double poseMs = sw.Elapsed.TotalMilliseconds / 20;
            sys.measure = true;
            sys.stats = new TrafficSystem.Stats();
            sys.Simulate(60f);
            Debug.Log($"[Stress] N {n} (placed {placed}): model {stepMs:F2} ms per 50 ms step, pose {poseMs:F2} ms; 60 s: {sys.Summary()}");
            sys.measure = false;
            sys.Pose();
            // drawing is measured in play mode (TrafficPerf): Camera.Render from an editor command breaks URP's passes
            if (n == 300 || n == 600) HanoiSetup.Shot(cam, $"ft_t5_stress_{n}_drone", views[0].Item2, views[0].Item3);
            if (n == 300 || n == 600) HanoiSetup.Shot(cam, $"ft_t5_stress_{n}_eye", views[1].Item2, views[1].Item3);
        }
    }

    /// Drawing cost in play mode: the pool is grown for 600 vehicles, a TrafficPerf (Runtime) is added, play starts and
    /// TrafficPerf logs "[Perf]" lines for 0 / 50 / 150 / 300 / 600 vehicles from a drone and an eye-level view.
    [MenuItem("Hanoi/Flyover Test/Traffic/Perf in Play (rush hour)")]
    public static void RunPerf() => CityTarget.With(CityTarget.FlyoverTest, () =>
    {
        OpenInTarget();
        var sys = UnityEngine.Object.FindFirstObjectByType<TrafficSystem>();
        GrowPool(sys, 600, 110);
        var (flys, roadY) = FlyoverBuilder.Load();
        var path = new FlyoverBuilder.Path3(flys[0], roadY);
        var mid = path.Pos((flys[0].clear_from + flys[0].clear_to) / 2f); mid.y = 0.2f;
        var inward = new Vector3(-mid.x, 0f, -mid.z).normalized;
        var perf = sys.GetComponent<TrafficPerf>() ?? sys.gameObject.AddComponent<TrafficPerf>();
        perf.views = new[]
        {
            new TrafficPerf.View { name = "drone", pos = mid + inward * 55f + Vector3.up * 32f, target = mid },
            new TrafficPerf.View { name = "eye", pos = mid + inward * 38f + Vector3.up * 1.7f, target = mid + Vector3.up * 1.2f },
        };
        sys.seed = 11;
        EditorApplication.isPlaying = true;
    });

    /// 120 s of traffic for several seeds (collisions, forced entries, waits): checks the rules are not luck.
    public static void RunSeeds() => CityTarget.With(CityTarget.FlyoverTest, () =>
    {
        EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
        var sys = UnityEngine.Object.FindFirstObjectByType<TrafficSystem>();
        foreach (int seed in new[] { 1, 2, 3, 4, 5, 6 })
        {
            sys.seed = seed;
            sys.Init();
            sys.Populate(32);
            sys.Simulate(120f);
            Debug.Log($"[Traffic] seed {seed}: {sys.Summary()}");
            foreach (var o in sys.stats.overlaps.Take(6)) Debug.Log($"[Traffic] seed {seed} overlap " + o);
        }
    });

    public static void RunBatch()
    {
        Build();
        RunTest();
    }
}
