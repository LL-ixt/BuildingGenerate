using System.Collections;
using System.Collections.Generic;
using Unity.Profiling;
using UnityEngine;

/// <summary>
/// TRAFFIC rush-hour step 1: drawing cost of the traffic, measured in PLAY mode (Editor/TrafficBuilder adds this to the
/// Traffic object and starts play: "Hanoi/Flyover Test/Traffic/Perf in Play"). For each vehicle count and each view:
/// frame time of real frames (average / 95th percentile / worst), CPU and GPU frame time of FrameTimingManager (0 when
/// the platform does not report them), and the renderer counters (draw calls, batches, set-pass calls, triangles,
/// shadow casters). Logs "[Perf] ..." lines, then leaves play mode.
/// </summary>
public class TrafficPerf : MonoBehaviour
{
    [System.Serializable] public class View { public string name; public Vector3 pos, target; }

    public int[] counts = { 0, 50, 150, 300, 600 };
    public View[] views;
    public float warmSeconds = 3f, measureSeconds = 6f;

    IEnumerator Start()
    {
        var sys = GetComponent<TrafficSystem>();
        var cam = Camera.main;
        var flyCam = cam != null ? cam.GetComponent<FlyCamera>() : null;
        if (flyCam != null) flyCam.enabled = false;
        yield return null;
        var draw = ProfilerRecorder.StartNew(ProfilerCategory.Render, "Draw Calls Count");
        var batches = ProfilerRecorder.StartNew(ProfilerCategory.Render, "Batches Count");
        var setPass = ProfilerRecorder.StartNew(ProfilerCategory.Render, "SetPass Calls Count");
        var tris = ProfilerRecorder.StartNew(ProfilerCategory.Render, "Triangles Count");
        var shadow = ProfilerRecorder.StartNew(ProfilerCategory.Render, "Shadow Casters Count");
        var timings = new FrameTiming[1];
        Debug.Log($"[Perf] screen {Screen.width}x{Screen.height}, {SystemInfo.graphicsDeviceName}, {SystemInfo.graphicsDeviceType}");
        foreach (int n in counts)
        {
            sys.measure = false;
            sys.targetCount = n;
            sys.spawnInterval = new Vector2(0.05f, 0.1f);
            sys.Init();
            if (n > 0) sys.Populate(n, 4.5f);
            foreach (var v in views)
            {
                cam.transform.SetPositionAndRotation(v.pos, Quaternion.LookRotation(v.target - v.pos, Vector3.up));
                float t0 = Time.realtimeSinceStartup;
                while (Time.realtimeSinceStartup - t0 < warmSeconds) yield return null;
                var ft = new List<float>();
                double cpu = 0, gpu = 0, dc = 0, bt = 0, sp = 0, tr = 0, sh = 0;
                int frames = 0, gpuFrames = 0;
                t0 = Time.realtimeSinceStartup;
                while (Time.realtimeSinceStartup - t0 < measureSeconds)
                {
                    yield return null;
                    ft.Add(Time.unscaledDeltaTime * 1000f);
                    FrameTimingManager.CaptureFrameTimings();
                    if (FrameTimingManager.GetLatestTimings(1, timings) > 0)
                    {
                        cpu += timings[0].cpuFrameTime;
                        if (timings[0].gpuFrameTime > 0) { gpu += timings[0].gpuFrameTime; gpuFrames++; }
                    }
                    dc += draw.LastValue; bt += batches.LastValue; sp += setPass.LastValue; tr += tris.LastValue; sh += shadow.LastValue;
                    frames++;
                }
                ft.Sort();
                float avg = 0f; foreach (var f in ft) avg += f; avg /= Mathf.Max(1, ft.Count);
                Debug.Log($"[Perf] N {n} ({sys.ActiveCount} active, {sys.ActiveCars} cars) view {v.name}: frame avg {avg:F1} ms " +
                          $"(p95 {ft[Mathf.Min(ft.Count - 1, (int)(ft.Count * 0.95f))]:F1}, worst {ft[ft.Count - 1]:F1}, {frames} frames), " +
                          $"FrameTiming cpu {cpu / Mathf.Max(1, frames):F1} ms gpu {(gpuFrames > 0 ? gpu / gpuFrames : 0):F1} ms; " +
                          $"draw calls {dc / frames:F0}, batches {bt / frames:F0}, set-pass {sp / frames:F0}, " +
                          $"tris {tr / frames / 1000:F0}k, shadow casters {sh / frames:F0}");
            }
        }
        draw.Dispose(); batches.Dispose(); setPass.Dispose(); tris.Dispose(); shadow.Dispose();
        Debug.Log("[Perf] done");
#if UNITY_EDITOR
        UnityEditor.EditorApplication.isPlaying = false;
#endif
    }
}
