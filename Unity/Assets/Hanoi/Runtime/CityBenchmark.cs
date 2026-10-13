using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Unity.Profiling;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// M5/M6: automatic fly-through benchmark of the streamed city. Only active when the player runs with
/// -hanoiBench (see Tools/run_bench.ps1 and Editor/CityBenchmarkBuild.cs, which writes the path to
/// StreamingAssets/bench_path.json from a real street of Map/out/city.json).
///
/// Waits until the chunks around the start are loaded, flies the path segments (street, rise, drone,
/// high), records every frame (frame / CPU / GPU time, SetPass, draw calls, batches, triangles, memory,
/// loaded chunks), writes bench_[tag].csv + bench_[tag].txt (per-segment avg / p95 / p99 / max / hitches)
/// and a screenshot per segment, then quits.
///
/// Command line: -benchTag name  -grd 0|1  -occlusion 0|1  -shadow metres  -loadRadius metres  -benchOut dir
/// </summary>
public class CityBenchmark : MonoBehaviour
{
    [Serializable] class PathFile { public string road; public Segment[] segments; }
    [Serializable] class Segment { public string name; public float speed; public Vector3[] points; public float lookAhead; public float pitch; }

    struct Sample
    {
        public int seg; public bool skip;            // skip: screenshot / first frames of a segment (not in the stats)
        public float t, frameMs, cpuMs, gpuMs;
        public long setPass, draws, batches, tris, sysMem;
        public int loaded, pending;
    }

    string tag = "run", outDir;
    PathFile path;
    readonly List<Sample> samples = new List<Sample>();
    ProfilerRecorder setPassRec, drawRec, batchRec, trisRec, memRec;
    readonly FrameTiming[] timings = new FrameTiming[1];

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Bootstrap()
    {
        if (!Environment.GetCommandLineArgs().Contains("-hanoiBench")) return;
        var cam = Camera.main;
        if (cam == null || cam.GetComponent<CityBenchmark>() != null) return;
        cam.gameObject.AddComponent<CityBenchmark>();
    }

    static string Arg(string name, string fallback)
    {
        var a = Environment.GetCommandLineArgs();
        int i = Array.IndexOf(a, name);
        return i >= 0 && i + 1 < a.Length ? a[i + 1] : fallback;
    }

    IEnumerator Start()
    {
        foreach (var fly in GetComponents<FlyCamera>()) Destroy(fly);
        QualitySettings.vSyncCount = 0;
        Application.targetFrameRate = -1;

        tag = Arg("-benchTag", "run");
        outDir = Arg("-benchOut", Application.persistentDataPath);
        Directory.CreateDirectory(outDir);
        var asset = GraphicsSettings.currentRenderPipeline as UniversalRenderPipelineAsset;
        if (asset != null)
        {
            string grd = Arg("-grd", "");                // default: keep the asset's setting
            if (grd != "")
                asset.gpuResidentDrawerMode = grd == "1" ? GPUResidentDrawerMode.InstancedDrawing : GPUResidentDrawerMode.Disabled;
            asset.gpuResidentDrawerEnableOcclusionCullingInCameras = Arg("-occlusion", "0") == "1";
            string prime = Arg("-depthPrime", "");       // default: keep the renderer's setting
            if (prime != "" && asset.scriptableRenderer is UniversalRenderer ur)
                ur.depthPrimingMode = prime == "1" ? DepthPrimingMode.Forced : DepthPrimingMode.Disabled;
            asset.shadowDistance = float.Parse(Arg("-shadow", asset.shadowDistance.ToString(System.Globalization.CultureInfo.InvariantCulture)),
                                               System.Globalization.CultureInfo.InvariantCulture);
        }
        var streamer = FindAnyObjectByType<ChunkStreamer>();
        if (streamer != null)
        {
            float r = float.Parse(Arg("-loadRadius", streamer.loadRadius.ToString(System.Globalization.CultureInfo.InvariantCulture)),
                                  System.Globalization.CultureInfo.InvariantCulture);
            streamer.unloadRadius = r + (streamer.unloadRadius - streamer.loadRadius);
            streamer.loadRadius = r;
        }

        path = JsonUtility.FromJson<PathFile>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath, "bench_path.json")));
        setPassRec = ProfilerRecorder.StartNew(ProfilerCategory.Render, "SetPass Calls Count");
        drawRec = ProfilerRecorder.StartNew(ProfilerCategory.Render, "Draw Calls Count");
        batchRec = ProfilerRecorder.StartNew(ProfilerCategory.Render, "Batches Count");
        trisRec = ProfilerRecorder.StartNew(ProfilerCategory.Render, "Triangles Count");
        memRec = ProfilerRecorder.StartNew(ProfilerCategory.Memory, "System Used Memory");

        // start pose, then let the streamer fill the start area (and shaders warm up)
        Place(path.segments[0], 0f);
        float t0 = Time.realtimeSinceStartup;
        yield return new WaitForSecondsRealtime(1f);
        while (streamer != null && !streamer.Settled && Time.realtimeSinceStartup - t0 < 60f)
            yield return null;
        float settle = Time.realtimeSinceStartup - t0;
        yield return new WaitForSecondsRealtime(2f);

        for (int s = 0; s < path.segments.Length; s++)
        {
            var seg = path.segments[s];
            float len = Length(seg.points), dist = 0f, shotAt = len * 0.5f;
            bool shot = false;
            int frame = 0, skipUntil = 3;              // the first frames after a jump / a screenshot are not representative
            while (dist <= len)
            {
                Place(seg, dist);
                yield return null;
                Record(s, dist / Mathf.Max(seg.speed, 0.01f), streamer, frame < skipUntil);
                if (!shot && dist >= shotAt)
                {
                    ScreenCapture.CaptureScreenshot(Path.Combine(outDir, $"bench_{tag}_{s}_{seg.name}.png"));
                    shot = true;
                    skipUntil = frame + 4;
                }
                dist += seg.speed * Time.unscaledDeltaTime;
                frame++;
            }
        }
        Write(asset, settle);
        yield return null;
        Application.Quit();
    }

    void Record(int seg, float t, ChunkStreamer streamer, bool skip)
    {
        FrameTimingManager.CaptureFrameTimings();
        float cpu = 0, gpu = 0;
        if (FrameTimingManager.GetLatestTimings(1, timings) > 0)
        {
            cpu = (float)timings[0].cpuMainThreadFrameTime;
            gpu = (float)timings[0].gpuFrameTime;
            if (gpu < 0f || gpu > 1000f) gpu = float.NaN;    // the GPU timer sometimes returns garbage
        }
        samples.Add(new Sample
        {
            seg = seg, skip = skip, t = t, frameMs = Time.unscaledDeltaTime * 1000f, cpuMs = cpu, gpuMs = gpu,
            setPass = setPassRec.LastValue, draws = drawRec.LastValue, batches = batchRec.LastValue,
            tris = trisRec.LastValue, sysMem = memRec.LastValue,
            loaded = streamer != null ? streamer.LoadedCount : 0, pending = streamer != null ? streamer.PendingCount : 0,
        });
    }

    // ---------------------------------------------------------------- path
    static float Length(Vector3[] pts)
    {
        float l = 0f;
        for (int i = 1; i < pts.Length; i++) l += Vector3.Distance(pts[i - 1], pts[i]);
        return l;
    }

    static Vector3 At(Vector3[] pts, float d)
    {
        for (int i = 1; i < pts.Length; i++)
        {
            float l = Vector3.Distance(pts[i - 1], pts[i]);
            if (d <= l || i == pts.Length - 1)
                return Vector3.Lerp(pts[i - 1], pts[i], l > 1e-4f ? Mathf.Clamp01(d / l) : 1f);
            d -= l;
        }
        return pts[pts.Length - 1];
    }

    void Place(Segment seg, float d)
    {
        var p = At(seg.points, d);
        var ahead = At(seg.points, d + Mathf.Max(seg.lookAhead, 1f));
        var dir = ahead - p; dir.y = 0f;
        if (dir.sqrMagnitude < 1e-4f) dir = transform.forward;
        var rot = Quaternion.LookRotation(dir.normalized) * Quaternion.Euler(seg.pitch, 0f, 0f);
        transform.SetPositionAndRotation(p, rot);
    }

    // ---------------------------------------------------------------- report
    static float Pct(List<float> v, float q) { if (v.Count == 0) return 0; v.Sort(); return v[Mathf.Clamp((int)(q * (v.Count - 1)), 0, v.Count - 1)]; }

    void Write(UniversalRenderPipelineAsset asset, float settle)
    {
        var inv = System.Globalization.CultureInfo.InvariantCulture;
        var csv = new StringBuilder("segment,skip,t,frame_ms,cpu_ms,gpu_ms,setpass,draws,batches,tris,sys_mem_mb,chunks_loaded,chunks_pending\n");
        foreach (var s in samples)
            csv.AppendLine(string.Format(inv, "{0},{1},{2:F3},{3:F2},{4:F2},{5:F2},{6},{7},{8},{9},{10},{11},{12}",
                path.segments[s.seg].name, s.skip ? 1 : 0, s.t, s.frameMs, s.cpuMs, s.gpuMs, s.setPass, s.draws, s.batches, s.tris,
                s.sysMem / (1024 * 1024), s.loaded, s.pending));
        File.WriteAllText(Path.Combine(outDir, $"bench_{tag}.csv"), csv.ToString());

        var sb = new StringBuilder();
        sb.AppendLine($"tag {tag}  GPU {SystemInfo.graphicsDeviceName} ({SystemInfo.graphicsDeviceType})  CPU {SystemInfo.processorType}");
        sb.AppendLine($"resolution {Screen.width}x{Screen.height}  GRD {asset?.gpuResidentDrawerMode}  occlusion {asset?.gpuResidentDrawerEnableOcclusionCullingInCameras}  " +
                      $"depth priming {(asset?.scriptableRenderer as UniversalRenderer)?.depthPrimingMode}  " +
                      $"shadow {asset?.shadowDistance} m  road '{path.road}'  start area loaded in {settle:F1} s");
        sb.AppendLine("(tris: the BRG draws of the GPU Resident Drawer are not counted by the Triangles counter)");
        sb.AppendLine("segment   frames  fps_avg  frame_avg  p95    p99    max    >33ms  cpu_avg gpu_avg  setpass_avg/max  draws_avg/max   tris_avg/max(M)  mem_max(MB)  chunks_max");
        for (int g = 0; g < path.segments.Length; g++)
        {
            var seg = samples.Where(s => s.seg == g && !s.skip).ToList();
            if (seg.Count == 0) continue;
            var f = seg.Select(s => s.frameMs).ToList();
            float avg = f.Average();
            var gpu = seg.Where(s => !float.IsNaN(s.gpuMs)).Select(s => s.gpuMs).DefaultIfEmpty(0f);
            sb.AppendLine(string.Format(inv,
                "{0,-9} {1,6}  {2,7:F1}  {3,9:F2}  {4,5:F1}  {5,5:F1}  {6,5:F1}  {7,5}  {8,7:F2} {9,7:F2}  {10,6:F0}/{11,-6}  {12,6:F0}/{13,-6}  {14,6:F2}/{15,-6:F2}  {16,10}  {17,6}",
                path.segments[g].name, seg.Count, 1000f / avg, avg, Pct(new List<float>(f), 0.95f), Pct(new List<float>(f), 0.99f), f.Max(),
                f.Count(x => x > 33.3f), seg.Average(s => s.cpuMs), gpu.Average(),
                seg.Average(s => s.setPass), seg.Max(s => s.setPass), seg.Average(s => s.draws), seg.Max(s => s.draws),
                seg.Average(s => s.tris) / 1e6, seg.Max(s => s.tris) / 1e6, seg.Max(s => s.sysMem) / (1024 * 1024), seg.Max(s => s.loaded)));
        }
        File.WriteAllText(Path.Combine(outDir, $"bench_{tag}.txt"), sb.ToString());
        Debug.Log("[Bench]\n" + sb);
    }

    void OnDestroy()
    {
        setPassRec.Dispose(); drawRec.Dispose(); batchRec.Dispose(); trisRec.Dispose(); memRec.Dispose();
    }
}
