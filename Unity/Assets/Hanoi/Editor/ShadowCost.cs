using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using Debug = UnityEngine.Debug;

/// <summary>
/// Measures what real-time shadows cost on the placed city. Mimics the planned streaming set-up:
/// chunks within LoadRadius of the camera are loaded as separate houses (their HLOD hidden), the rest
/// stays HLOD. For three camera heights it times 1080p frames with different shadow distances and writes
/// shots. Batch: -executeMethod ShadowCost.RunBatch
/// </summary>
public static class ShadowCost
{
    const float LoadRadius = 350f;
    const int W = 1920, H = 1080, Frames = 12;

    static readonly (string name, Vector3 pos, Vector3 target)[] Views =
    {
        ("street", new Vector3(808f, 1.7f, -2f), new Vector3(840f, 7f, 22f)),
        ("drone80", new Vector3(760f, 80f, -60f), new Vector3(830f, 5f, 15f)),
        ("high250", new Vector3(560f, 250f, -330f), new Vector3(830f, 0f, 20f)),
    };

    static readonly float[] Distances = { 0f, 50f, 150f, 300f };

    public static void RunBatch()
    {
        EditorSettings.asyncShaderCompilation = false;
        var main = EditorSceneManager.OpenScene("Assets/Hanoi/City/City_Main.unity", OpenSceneMode.Single);
        var reg = Object.FindFirstObjectByType<CityChunks>();
        var cam = Camera.main;
        var asset = (UniversalRenderPipelineAsset)GraphicsSettings.currentRenderPipeline;
        var sb = new StringBuilder();
        sb.AppendLine($"[Shadow] pipeline asset {asset.name}, cascades {asset.shadowCascadeCount}, start distance {asset.shadowDistance}");

        var sun = Object.FindFirstObjectByType<Light>();
        sb.AppendLine($"[Shadow] sun shadows {sun.shadows}");

        var rt = new RenderTexture(W, H, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 1 };
        var tex = new Texture2D(1, 1, TextureFormat.RGBA32, false);
        float baseDistance = asset.shadowDistance;
        int baseCascades = asset.shadowCascadeCount;

        foreach (var v in Views)
        {
            // streaming-like set: near chunks as houses, far chunks as HLOD
            int loaded = 0, caster = 0;
            foreach (var c in reg.chunks)
            {
                var b = c.boundsXZ;
                float dx = Mathf.Max(b.xMin - v.pos.x, 0f, v.pos.x - b.xMax), dz = Mathf.Max(b.yMin - v.pos.z, 0f, v.pos.z - b.yMax);
                bool near = Mathf.Sqrt(dx * dx + dz * dz) < LoadRadius;
                var scene = UnityEngine.SceneManagement.SceneManager.GetSceneByPath(c.scenePath);
                if (near && !scene.isLoaded) { scene = EditorSceneManager.OpenScene(c.scenePath, OpenSceneMode.Additive); }
                if (!near && scene.isLoaded) EditorSceneManager.CloseScene(scene, true);
                if (c.hlod != null) c.hlod.enabled = !near;
                if (near) { loaded++; caster += scene.GetRootGameObjects().Sum(g => g.GetComponentsInChildren<LODGroup>().Length); }
            }
            sb.AppendLine($"[Shadow] view {v.name}: {loaded} chunks loaded as houses (~{caster} buildings), others HLOD");
            cam.transform.SetPositionAndRotation(v.pos, Quaternion.LookRotation(v.target - v.pos));
            cam.targetTexture = rt;

            foreach (float d in Distances)
            {
                asset.shadowDistance = Mathf.Max(d, 0.1f);
                sun.shadows = d <= 0f ? LightShadows.None : LightShadows.Soft;
                for (int i = 0; i < 3; i++) cam.Render();                         // warm-up
                RenderTexture.active = rt; tex.ReadPixels(new Rect(0, 0, 1, 1), 0, 0); RenderTexture.active = null;
                var sw = Stopwatch.StartNew();
                for (int i = 0; i < Frames; i++) cam.Render();
                RenderTexture.active = rt; tex.ReadPixels(new Rect(0, 0, 1, 1), 0, 0); RenderTexture.active = null;   // GPU sync
                sw.Stop();
                sb.AppendLine($"[Shadow]   {v.name,-8} shadow distance {(d <= 0 ? "OFF" : d + " m"),-7} -> {sw.Elapsed.TotalMilliseconds / Frames,6:F1} ms / frame");
                HanoiSetup.ShotWith(cam, $"sh_{v.name}_{(d <= 0 ? "off" : ((int)d).ToString())}", rt);
            }
            cam.targetTexture = null;
        }
        asset.shadowDistance = baseDistance;
        sun.shadows = LightShadows.Soft;
        Debug.Log(sb.ToString());
        File.WriteAllText(Path.Combine(HanoiSetup.ShotsDir, "..", "shadow_cost.txt"), sb.ToString());
    }
}
