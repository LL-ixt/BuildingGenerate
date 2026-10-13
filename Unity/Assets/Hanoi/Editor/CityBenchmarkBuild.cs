using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// M5/M6: render settings for the streamed city (GPU Resident Drawer) + the Windows Development player
/// used by the fly-through benchmark (Runtime/CityBenchmark.cs, path from Tools/make_bench_path.py,
/// runs via Tools/run_bench.ps1).
/// Menu "Hanoi/Bench/..." or batch: -executeMethod CityBenchmarkBuild.RunBatch
/// </summary>
public static class CityBenchmarkBuild
{
    static string BuildExe => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Builds/Bench/HanoiBench.exe"));

    /// GPU Resident Drawer mode on every URP asset used by a quality level (PC + Mobile), BRG variants kept
    /// in builds. Default OFF: with it on, every URP/Lit ground material renders as a dark mirror in the
    /// player (fine in the Editor; not static batching) - see PROJECT_NOTES (M6). The Hanoi shaders work with it.
    [MenuItem("Hanoi/Bench/Configure Rendering (GPU Resident Drawer OFF)")]
    public static void ConfigureRendering() => ConfigureRendering(GPUResidentDrawerMode.Disabled);

    [MenuItem("Hanoi/Bench/Configure Rendering (GPU Resident Drawer ON, ground broken in builds)")]
    public static void ConfigureRenderingGrd() => ConfigureRendering(GPUResidentDrawerMode.InstancedDrawing);

    public static void ConfigureRendering(GPUResidentDrawerMode mode)
    {
        var assets = Enumerable.Range(0, QualitySettings.count)
            .Select(i => QualitySettings.GetRenderPipelineAssetAt(i) as UniversalRenderPipelineAsset)
            .Append(GraphicsSettings.defaultRenderPipeline as UniversalRenderPipelineAsset)
            .Where(a => a != null).Distinct();
        foreach (var a in assets)
        {
            a.gpuResidentDrawerMode = mode;
            EditorUtility.SetDirty(a);
            Debug.Log($"[Bench] {a.name}: GPU Resident Drawer {a.gpuResidentDrawerMode}, occlusion {a.gpuResidentDrawerEnableOcclusionCullingInCameras}, " +
                      $"SRP Batcher {a.useSRPBatcher}, shadow {a.shadowDistance} m");
        }
        var gs = new SerializedObject(GraphicsSettings.GetGraphicsSettings());
        var brg = gs.FindProperty("m_BrgStripping");
        if (brg != null && brg.intValue != 1)
        {
            brg.intValue = 1;                                  // BatchRendererGroupStrippingMode.KeepAll
            gs.ApplyModifiedPropertiesWithoutUndo();
        }
        Debug.Log($"[Bench] BRG variant stripping = {(brg != null ? brg.intValue.ToString() : "?")} (1 = keep all)");
        PlayerSettings.enableFrameTimingStats = true;

        // Depth priming: the depth (+ normals, SSAO needs them anyway) prepass fills the depth buffer first,
        // the forward pass then shades each pixel once (ZTest Equal) - big win for the overlapping,
        // alpha-clipped leaf cards. Every Hanoi shader clips identically in DepthOnly / DepthNormals.
        foreach (var path in AssetDatabase.FindAssets("t:UniversalRendererData", new[] { "Assets/Settings" }).Select(AssetDatabase.GUIDToAssetPath))
        {
            var rd = AssetDatabase.LoadAssetAtPath<UniversalRendererData>(path);
            if (rd == null || !rd.name.StartsWith("PC_")) continue;
            rd.depthPrimingMode = DepthPrimingMode.Forced;
            EditorUtility.SetDirty(rd);
            Debug.Log($"[Bench] {rd.name}: depth priming {rd.depthPrimingMode}, rendering mode {rd.renderingMode}");
        }

        // Static batching merges the static ground / kerb / HLOD meshes at build time; the GPU Resident
        // Drawer then draws those merged meshes with a wrong cbuffer (ground turned into a black mirror in
        // the player, fine in the Editor where nothing is batched). GRD + SRP Batcher do not need it.
        var set = typeof(PlayerSettings).GetMethod("SetStaticBatchingForPlatform",
            System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic);
        var get = typeof(PlayerSettings).GetMethod("GetStaticBatchingForPlatform",
            System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic);
        if (set != null)
        {
            set.Invoke(null, new object[] { BuildTarget.StandaloneWindows64, false });
            Debug.Log($"[Bench] static batching (Windows) = {get?.Invoke(null, new object[] { BuildTarget.StandaloneWindows64 })}");
        }
        else
            Debug.LogError("[Bench] PlayerSettings.SetStaticBatchingForPlatform not found: turn Static Batching off by hand");
        AssetDatabase.SaveAssets();
    }

    [MenuItem("Hanoi/Bench/Build Benchmark Player")]
    public static void BuildPlayer()
    {
        ConfigureRendering();
        var scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
        if (scenes.Length == 0 || !scenes[0].EndsWith("City_Main.unity"))
            throw new BuildFailedException("[Bench] Build Settings must start with City_Main (run CityPlacer first)");
        if (!File.Exists(Path.Combine(Application.streamingAssetsPath, "bench_path.json")))
            throw new BuildFailedException("[Bench] missing StreamingAssets/bench_path.json (python Tools/make_bench_path.py)");

        PlayerSettings.SetScriptingBackend(NamedBuildTarget.Standalone, ScriptingImplementation.Mono2x);
        PlayerSettings.fullScreenMode = FullScreenMode.Windowed;
        PlayerSettings.defaultScreenWidth = 1920;
        PlayerSettings.defaultScreenHeight = 1080;
        PlayerSettings.resizableWindow = false;
        PlayerSettings.runInBackground = true;
        PlayerSettings.usePlayerLog = true;

        Directory.CreateDirectory(Path.GetDirectoryName(BuildExe));
        var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
        {
            scenes = scenes,
            locationPathName = BuildExe,
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.Development,
        });
        var s = report.summary;
        Debug.Log($"[Bench] build {s.result}: {scenes.Length} scenes, {s.totalSize / (1024 * 1024)} MB, " +
                  $"{s.totalTime.TotalMinutes:F1} min, {s.totalErrors} errors, {s.totalWarnings} warnings -> {BuildExe}");
        if (s.result != BuildResult.Succeeded)
            throw new BuildFailedException($"[Bench] build {s.result}");
    }

    public static void RunBatch() => BuildPlayer();

    /// Debug: the same street view with the GPU Resident Drawer off / on (+ the ground swapped to a plain
    /// URP Lit material) to find which shader breaks under BRG. Batch: -executeMethod CityBenchmarkBuild.GrdProbe
    public static void GrdProbe()
    {
        try { GrdProbeInner(); }
        catch (System.Exception e) { Debug.LogError($"[Probe] FAILED: {e}"); EditorApplication.Exit(3); }
        Debug.Log("[Probe] done");
    }

    static void GrdProbeInner()
    {
        EditorSettings.asyncShaderCompilation = false;
        UnityEditor.SceneManagement.EditorSceneManager.OpenScene("Assets/Hanoi/City/City_Main.unity");
        var reg = Object.FindFirstObjectByType<CityChunks>();
        var pos = new Vector3(119.2f, 1.72f, -111.68f);
        var target = new Vector3(137.35f, 3f, -83.91f);
        foreach (var c in reg.chunks)
        {
            var b = c.boundsXZ;
            float dx = Mathf.Max(b.xMin - pos.x, 0f, pos.x - b.xMax), dz = Mathf.Max(b.yMin - pos.z, 0f, pos.z - b.yMax);
            if (Mathf.Sqrt(dx * dx + dz * dz) < 250f)
                UnityEditor.SceneManagement.EditorSceneManager.OpenScene(c.scenePath, UnityEditor.SceneManagement.OpenSceneMode.Additive);
        }
        reg.SyncHlod();
        var asset = (UniversalRenderPipelineAsset)GraphicsSettings.currentRenderPipeline;
        var cam = Camera.main;

        Debug.Log($"[Probe] scenes open, camera {(cam != null ? cam.name : "NULL")}, asset {asset.name}");
        void Shot(string name)
        {
            Debug.Log($"[Probe] shot {name}: GRD {asset.gpuResidentDrawerMode}");
            HanoiSetup.Shot(cam, name, pos, target);
            Debug.Log($"[Probe] shot {name} written");
        }
        asset.gpuResidentDrawerMode = GPUResidentDrawerMode.Disabled; Shot("grd_probe_off");
        asset.gpuResidentDrawerMode = GPUResidentDrawerMode.InstancedDrawing; Shot("grd_probe_on");

        // which renderers use which shaders (+ keywords) in the loaded chunks
        var rs = Object.FindObjectsByType<MeshRenderer>(FindObjectsSortMode.None);
        foreach (var g in rs.SelectMany(r => r.sharedMaterials.Where(m => m != null).Select(m => (r, m)))
                     .GroupBy(x => x.m))
            Debug.Log($"[Probe] {g.Key.name}: shader {g.Key.shader.name}, keywords [{string.Join(" ", g.Key.shaderKeywords)}], " +
                      $"{g.Count()} renderers, e.g. {g.First().r.name} (static {g.First().r.gameObject.isStatic})");

        // plain URP Lit on the ground: same colour, no textures / keywords
        var plain = new Material(Shader.Find("Universal Render Pipeline/Lit")) { name = "M_PlainProbe" };
        plain.SetColor("_BaseColor", new Color(0.4f, 0.4f, 0.4f));
        foreach (var r in rs)
            if (r.sharedMaterials.Any(m => m != null && m.shader.name == "Universal Render Pipeline/Lit"))
                r.sharedMaterials = r.sharedMaterials.Select(m => m != null && m.shader.name == "Universal Render Pipeline/Lit" ? plain : m).ToArray();
        Shot("grd_probe_on_plainlit");
        asset.gpuResidentDrawerMode = GPUResidentDrawerMode.InstancedDrawing;
    }
}
