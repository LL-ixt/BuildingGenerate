using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// Step 2 tooling: import the Blender kit, wire it to the Hanoi shaders, build a street test scene
/// and capture test shots. Menu "Hanoi/..." or batch: -executeMethod HanoiSetup.RunBatch
/// </summary>
public static class HanoiSetup
{
    const string Root = "Assets/Hanoi";
    const string ModelsDir = Root + "/Models";
    const string MatDir = Root + "/Materials";
    const string ScenePath = Root + "/Scenes/StreetTest.unity";

    internal static string ProjectDir => Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
    static string ExportFbxDir => Path.GetFullPath(Path.Combine(ProjectDir, "../Export/FBX"));
    internal static string ShotsDir => Path.GetFullPath(Path.Combine(ProjectDir, "../Unity_logs/shots"));

    // ------------------------------------------------------------------ import
    [MenuItem("Hanoi/1. Import Kit + Materials")]
    public static void ImportAll()
    {
        foreach (var d in new[] { ModelsDir, MatDir, Root + "/Scenes" })
            Directory.CreateDirectory(Path.Combine(ProjectDir, d));

        foreach (var src in Directory.GetFiles(ExportFbxDir, "*.fbx"))
            File.Copy(src, Path.Combine(ProjectDir, ModelsDir, Path.GetFileName(src)), true);
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

        var kit = MaterialAsset("M_HanoiKit", "Hanoi/Building");
        var glass = MaterialAsset("M_HanoiGlass", "Hanoi/Window");

        foreach (var path in AssetDatabase.FindAssets("t:Model", new[] { ModelsDir }).Select(AssetDatabase.GUIDToAssetPath))
            ConfigureModel(path, kit, glass);

        foreach (var name in new[] { "Hanoi/Building", "Hanoi/Window" })
        {
            var sh = Shader.Find(name);
            if (sh == null) { Debug.LogError($"[Hanoi] shader not found: {name}"); continue; }
            var msgs = ShaderUtil.GetShaderMessages(sh);
            Debug.Log($"[Hanoi] shader {name}: hasError={ShaderUtil.ShaderHasError(sh)} messages={msgs.Length}");
            foreach (var m in msgs)
                Debug.Log($"[Hanoi]   {m.severity} {m.file}:{m.line} {m.message}");
        }
    }

    /// Import settings shared by every Blender FBX: Blender normals, Mikk tangents, both kit materials remapped.
    internal static void ConfigureModel(string path, Material kit, Material glass)
    {
        var imp = (ModelImporter)AssetImporter.GetAtPath(path);
        imp.importNormals = ModelImporterNormals.Import;
        imp.importTangents = ModelImporterTangents.CalculateMikk;
        imp.importAnimation = false;
        imp.importCameras = false;
        imp.importLights = false;
        imp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_HanoiKit"), kit);
        imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_HanoiGlass"), glass);
        imp.SaveAndReimport();
    }

    internal static Material MaterialAsset(string name, string shaderName)
    {
        string path = $"{MatDir}/{name}.mat";
        var shader = Shader.Find(shaderName);
        var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (mat == null)
        {
            mat = new Material(shader) { name = name };
            AssetDatabase.CreateAsset(mat, path);
        }
        else if (mat.shader != shader)
        {
            mat.shader = shader;
        }
        EditorUtility.SetDirty(mat);
        AssetDatabase.SaveAssets();
        return mat;
    }

    /// URP/Lit material; texture = source file in Export/Textures (copied + imported), tiling in repeats per UV unit.
    internal static Material LitMaterial(string name, Color c, float smooth, string exportTexture = null, Vector2? tiling = null)
    {
        string path = $"{MatDir}/{name}.mat";
        var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (mat == null)
        {
            mat = new Material(Shader.Find("Universal Render Pipeline/Lit"));
            AssetDatabase.CreateAsset(mat, path);
        }
        // a material that already carries a texture keeps its (white) tint when another scene asks for it
        // by name without a texture (gallery / street test), otherwise the texture would be darkened
        if (exportTexture != null || mat.GetTexture("_BaseMap") == null)
            mat.SetColor("_BaseColor", c);
        mat.SetFloat("_Smoothness", smooth);
        if (exportTexture != null)
        {
            var tex = ImportTexture(exportTexture, alphaCoverage: false);
            mat.SetTexture("_BaseMap", tex);
            mat.SetColor("_BaseColor", Color.white);
            mat.mainTextureScale = tiling ?? Vector2.one;
        }
        EditorUtility.SetDirty(mat);
        return mat;
    }

    /// URP/Lit ground material: base map (repeats per UV unit), optional normal map and a large-scale grey
    /// detail albedo (neutral 0.5 = no change, x2 multiply) that breaks the repetition of a small base tile.
    internal static Material GroundMaterial(string name, float smooth, string baseTex, Vector2 tiling,
                                            string normalTex = null, float normalScale = 1f,
                                            string macroTex = null, Vector2? macroTiling = null)
    {
        var mat = LitMaterial(name, Color.white, smooth, baseTex, tiling);
        if (normalTex != null)
        {
            mat.SetTexture("_BumpMap", ImportTexture(normalTex, false, normalMap: true));
            mat.SetTextureScale("_BumpMap", tiling);
            mat.SetFloat("_BumpScale", normalScale);
            mat.EnableKeyword("_NORMALMAP");
        }
        if (macroTex != null)
        {
            mat.SetTexture("_DetailAlbedoMap", ImportTexture(macroTex, false));
            mat.SetTextureScale("_DetailAlbedoMap", macroTiling ?? Vector2.one);
            mat.SetFloat("_DetailAlbedoMapScale", 1f);
            mat.EnableKeyword("_DETAIL_MULX2");
        }
        EditorUtility.SetDirty(mat);
        return mat;
    }

    // ------------------------------------------------------------------ textures
    internal static string ExportTexDir => Path.GetFullPath(Path.Combine(ProjectDir, "../Export/Textures"));
    const string TexDir = Root + "/Textures";

    /// Copies Export/Textures/<rel> into Assets/Hanoi/Textures and applies the shared import settings.
    internal static Texture2D ImportTexture(string rel, bool alphaCoverage, bool normalMap = false)
    {
        string dst = $"{TexDir}/{Path.GetFileName(rel)}";
        Directory.CreateDirectory(Path.Combine(ProjectDir, TexDir));
        string src = Path.Combine(ExportTexDir, rel);
        string full = Path.Combine(ProjectDir, dst);
        if (!File.Exists(full) || File.GetLastWriteTimeUtc(src) > File.GetLastWriteTimeUtc(full))
        {
            File.Copy(src, full, true);
            AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport);
        }
        var imp = (TextureImporter)AssetImporter.GetAtPath(dst);
        var wantType = normalMap ? TextureImporterType.NormalMap : TextureImporterType.Default;
        bool dirty = imp.textureType != wantType || (!normalMap && imp.sRGBTexture != true) || imp.maxTextureSize != 2048 ||
                     imp.anisoLevel != 8 || imp.mipmapEnabled != true || imp.alphaIsTransparency != alphaCoverage ||
                     imp.mipMapsPreserveCoverage != alphaCoverage;
        if (dirty)
        {
            imp.textureType = wantType;
            if (!normalMap) imp.sRGBTexture = true;
            imp.maxTextureSize = 2048;
            imp.anisoLevel = 8;
            imp.mipmapEnabled = true;
            imp.wrapMode = TextureWrapMode.Repeat;
            imp.filterMode = FilterMode.Trilinear;
            imp.alphaIsTransparency = alphaCoverage;        // dilates colour under alpha 0 (no dark halos)
            imp.mipMapsPreserveCoverage = alphaCoverage;    // railings keep their bars at distance
            imp.alphaTestReferenceValue = 0.5f;
            var ps = imp.GetDefaultPlatformTextureSettings();
            ps.textureCompression = TextureImporterCompression.CompressedHQ;
            imp.SetPlatformTextureSettings(ps);
            imp.SaveAndReimport();
        }
        return AssetDatabase.LoadAssetAtPath<Texture2D>(dst);
    }

    static readonly Vector4 NoRect = new Vector4(-2f, -2f, -1f, -1f);     // matches no UV: procedural stand-in off

    /// Trim sheet on M_HanoiKit; the procedural stand-ins switch off for every region that now has an image.
    internal static void ConfigureKitTexture(Material kit)
    {
        string jsonPath = Path.Combine(ExportTexDir, "textured_regions.json");
        if (!File.Exists(jsonPath)) return;
        var regions = File.ReadAllText(jsonPath).Trim('[', ']', ' ', '\n', '\r').Split(',')
            .Select(s => s.Trim().Trim('"')).Where(s => s.Length > 0).ToHashSet();
        var tex = ImportTexture("T_HanoiTrim.png", alphaCoverage: true);
        kit.SetTexture("_BaseMap", tex);
        kit.SetVector("_ShutterRect", regions.Contains("SHUTTER") ? NoRect : new Vector4(0.50146f, 0.62646f, 0.74854f, 0.87354f));
        kit.SetVector("_GlassRect", regions.Contains("GLASSWIN") ? NoRect : new Vector4(0.75146f, 0.62646f, 0.99854f, 0.87354f));
        kit.SetVector("_RollerRect", regions.Contains("ROLLER") ? NoRect : new Vector4(0.00146f, 0.25146f, 0.24854f, 0.49854f));
        kit.SetFloat("_DirtMin", 0.03f); kit.SetFloat("_DirtMax", 0.85f); kit.SetFloat("_DirtyShare", 0.15f);   // few dirty walls
        kit.SetFloat("_RailTexMode", (regions.Contains("RAIL_BAL") ? 1 : 0) + (regions.Contains("RAIL_CAGE") ? 2 : 0));
        EditorUtility.SetDirty(kit);
        Debug.Log($"[Hanoi] trim texture on M_HanoiKit: {regions.Count} textured regions, rail mode {kit.GetFloat("_RailTexMode")}");
    }

    // ------------------------------------------------------------------ scene
    [MenuItem("Hanoi/2. Build Street Test Scene")]
    public static void BuildScene()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        HanoiLighting.Apply();

        var cam = Camera.main;
        cam.farClipPlane = 3000f;
        cam.nearClipPlane = 0.1f;
        cam.fieldOfView = 60f;

        // street: road along X, sidewalks, two facing rows of houses
        const int perRow = 12;
        const float width = 4f, road = 4f, walk = 2.5f;
        float edge = road + walk;
        var asphalt = LitMaterial("M_Asphalt", new Color(0.18f, 0.18f, 0.19f), 0.2f);
        var paving = LitMaterial("M_Sidewalk", new Color(0.50f, 0.48f, 0.45f), 0.15f);
        Box("Road", new Vector3(0, -0.05f, 0), new Vector3(400, 0.1f, 400), asphalt);
        Box("Sidewalk_S", new Vector3(0, 0.07f, -(road + walk / 2)), new Vector3(perRow * width + 20, 0.15f, walk), paving);
        Box("Sidewalk_N", new Vector3(0, 0.07f, road + walk / 2), new Vector3(perRow * width + 20, 0.15f, walk), paving);

        var model = AssetDatabase.LoadAssetAtPath<GameObject>($"{ModelsDir}/SM_HouseA.fbx");
        Vector3 facade = FacadeDirection(model);
        Debug.Log($"[Hanoi] SM_HouseA facade direction (model space) = {facade}");

        var street = new GameObject("Street").transform;
        for (int row = 0; row < 2; row++)
        {
            float z = row == 0 ? -edge : edge;
            Vector3 face = row == 0 ? Vector3.forward : Vector3.back;
            var rot = Quaternion.Euler(0, Vector3.SignedAngle(facade, face, Vector3.up), 0);
            for (int i = 0; i < perRow; i++)
            {
                var go = (GameObject)PrefabUtility.InstantiatePrefab(model, street);
                go.name = $"HouseA_{row}_{i:00}";
                go.transform.SetPositionAndRotation(new Vector3((i - perRow / 2f + 0.5f) * width, 0.15f, z), rot);
                SetupLods(go);
            }
        }

        EditorSceneManager.SaveScene(scene, ScenePath);
        Debug.Log($"[Hanoi] scene saved: {ScenePath}");
    }

    internal static void Box(string name, Vector3 pos, Vector3 size, Material mat)
    {
        var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
        go.name = name;
        go.transform.position = pos;
        go.transform.localScale = size;
        go.GetComponent<Renderer>().sharedMaterial = mat;
        Object.DestroyImmediate(go.GetComponent<Collider>());
    }

    /// Facade = the side of the 12 m deep body that sits near the pivot (balconies stick out ~1 m).
    static Vector3 FacadeDirection(GameObject model)
    {
        var tmp = Object.Instantiate(model);
        tmp.transform.SetPositionAndRotation(Vector3.zero, Quaternion.identity);
        var lod0 = tmp.GetComponentsInChildren<Renderer>().First(r => r.name.EndsWith("_LOD0"));
        var b = lod0.bounds;
        Object.DestroyImmediate(tmp);
        bool depthIsX = b.size.x > b.size.z;
        float min = depthIsX ? b.min.x : b.min.z, max = depthIsX ? b.max.x : b.max.z;
        float sign = Mathf.Abs(min) < Mathf.Abs(max) ? -1f : 1f;
        return depthIsX ? new Vector3(sign, 0, 0) : new Vector3(0, 0, sign);
    }

    // ~20 m tall house, 60 deg FOV: LOD1 from ~60 m, LOD2 from ~220 m, culled past ~2 km
    internal static readonly float[] TubeLodHeights = { 0.28f, 0.08f, 0.008f };

    static void SetupLods(GameObject house) => SetupLods(house, TubeLodHeights);

    /// LODGroup on `go` from its child renderers named *_LOD0, *_LOD1, ... with cross-fade.
    internal static LODGroup SetupLods(GameObject go, float[] heights)
    {
        var lg = go.GetComponentInChildren<LODGroup>();
        if (lg == null)
            lg = go.AddComponent<LODGroup>();
        var renderers = go.GetComponentsInChildren<Renderer>();
        int count = Enumerable.Range(0, 8).Count(i => renderers.Any(r => r.name.EndsWith($"_LOD{i}")));
        var lods = new LOD[count];
        for (int i = 0; i < count; i++)
            lods[i] = new LOD(heights[i], renderers.Where(r => r.name.EndsWith($"_LOD{i}")).ToArray());
        lg.SetLODs(lods);
        lg.fadeMode = LODFadeMode.CrossFade;
        lg.animateCrossFading = true;
        lg.RecalculateBounds();
        return lg;
    }

    // ------------------------------------------------------------------ shots
    [MenuItem("Hanoi/3. Capture Test Shots")]
    public static void CaptureShots()
    {
        if (EditorSceneManager.GetActiveScene().path != ScenePath)
            EditorSceneManager.OpenScene(ScenePath);
        EditorSettings.asyncShaderCompilation = false;
        Directory.CreateDirectory(ShotsDir);

        var cam = Camera.main;
        var sun = Object.FindFirstObjectByType<Light>();
        var kit = AssetDatabase.LoadAssetAtPath<Material>($"{MatDir}/M_HanoiKit.mat");
        var glass = AssetDatabase.LoadAssetAtPath<Material>($"{MatDir}/M_HanoiGlass.mat");

        Shot(cam, "1_street", new Vector3(-20f, 1.7f, -1.5f), new Vector3(8f, 7f, 1.0f));
        Shot(cam, "2_windows_close", new Vector3(-1.0f, 11.0f, 0.5f), new Vector3(3.0f, 10.5f, 6.5f));
        Shot(cam, "2b_window_front", new Vector3(3.2f, 12.6f, 3.2f), new Vector3(1.6f, 12.0f, 6.5f));
        Shot(cam, "3_drone_50m", new Vector3(-35f, 50f, -45f), new Vector3(0f, 5f, 0f));
        Shot(cam, "4_far_300m", new Vector3(-260f, 300f, -320f), new Vector3(0f, 0f, 0f));

        // night: dim sun / ambient, light up some rooms
        float sunI = sun.intensity, ambI = RenderSettings.ambientIntensity;
        sun.intensity = 0.03f;
        RenderSettings.ambientIntensity = 0.1f;
        kit.SetFloat("_NightLights", 0.45f); glass.SetFloat("_NightLights", 0.45f);
        Shot(cam, "5_street_night", new Vector3(-20f, 1.7f, -1.5f), new Vector3(8f, 7f, 1.0f));
        kit.SetFloat("_NightLights", 0f); glass.SetFloat("_NightLights", 0f);
        sun.intensity = sunI;
        RenderSettings.ambientIntensity = ambI;

        Debug.Log($"[Hanoi] shots written to {ShotsDir}");
    }

    /// Saves what the camera already rendered into `rt` (after a Render) as a png.
    internal static void ShotWith(Camera cam, string name, RenderTexture rt)
    {
        cam.targetTexture = rt;
        cam.Render();
        var prev = RenderTexture.active;
        RenderTexture.active = rt;
        var tex = new Texture2D(rt.width, rt.height, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0);
        tex.Apply();
        Directory.CreateDirectory(ShotsDir);
        File.WriteAllBytes(Path.Combine(ShotsDir, name + ".png"), tex.EncodeToPNG());
        RenderTexture.active = prev;
        Object.DestroyImmediate(tex);
    }

    internal static void Shot(Camera cam, string name, Vector3 pos, Vector3 target) => ShotSized(cam, name, pos, target, 1600, 900);

    /// Top-down views: look straight down with north (+Z) up the picture.
    internal static void ShotSized(Camera cam, string name, Vector3 pos, Vector3 target, int w, int h)
    {
        var up = Mathf.Abs(Vector3.Dot((target - pos).normalized, Vector3.up)) > 0.99f ? Vector3.forward : Vector3.up;
        cam.transform.SetPositionAndRotation(pos, Quaternion.LookRotation(target - pos, up));
        var rt = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB) { antiAliasing = 4 };
        var prev = cam.targetTexture;
        cam.targetTexture = rt;
        cam.Render();
        cam.Render();   // second frame: shadows / LOD state settled
        RenderTexture.active = rt;
        var tex = new Texture2D(w, h, TextureFormat.RGB24, false);
        tex.ReadPixels(new Rect(0, 0, w, h), 0, 0);
        tex.Apply();
        File.WriteAllBytes(Path.Combine(ShotsDir, name + ".png"), tex.EncodeToPNG());
        RenderTexture.active = null;
        cam.targetTexture = prev;
        Object.DestroyImmediate(tex);
        rt.Release();
        Object.DestroyImmediate(rt);
    }

    // ------------------------------------------------------------------ batch entry
    public static void RunBatch()
    {
        ImportAll();
        BuildScene();
        CaptureShots();
    }

    public static void RunShots() => CaptureShots();
}
