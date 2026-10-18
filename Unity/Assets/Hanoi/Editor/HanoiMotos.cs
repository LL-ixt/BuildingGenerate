using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// MOTO X4: motorbikes from Blender (Blender/scripts/build_moto.py -> Export/Vehicles: FBX, atlas,
/// vehicles.json) as prefabs with LODGroups, a gallery street, and the parked bikes of the city
/// (Map/osm_pipeline.place_motos -> city.json chunk.moto, placed by CityPlacer.PlaceMotos).
/// Menu "Hanoi/Motos/..." or batch: -executeMethod HanoiMotos.RunBatch / RunCityBatch
/// Prefabs:
///   SM_Moto_SH_C0..C5  parked bike, one prefab per paint colour (merged mesh per LOD); the city
///                      picks one at random per bike (seeded, so re-placing gives the same colours).
///   SM_Moto_SH_Rig     riding bike: Body_LODn, Steer pivot (Steer_LODn + WheelF pivot) and WheelR
///                      pivot; steer about vehicles.json rig.steer_axis, wheels about their local X.
/// Materials M_Moto_0..5 (Hanoi/Vehicle): same atlas + data map, alpha clip (wheel spokes), one paint
/// colour each (no per-instance data: SRP Batcher / GPU Resident Drawer friendly).
/// </summary>
public static class HanoiMotos
{
    const string MotoRoot = "Assets/Hanoi/Vehicles";
    const string ModelsDir = MotoRoot + "/Models";
    const string PrefabDir = MotoRoot + "/Prefabs";
    const string TexDir = MotoRoot + "/Textures";
    const string GalleryScene = MotoRoot + "/MotoGallery.unity";
    public const string ParkedId = "SM_Moto_SH";
    const string RigId = "SM_Moto_SH_Rig";

    // paint colours (sRGB) and how common they are in Hanoi traffic
    internal static readonly Color[] Paints =
    {
        new Color(0.91f, 0.91f, 0.89f), new Color(0.09f, 0.09f, 0.10f), new Color(0.59f, 0.08f, 0.09f),
        new Color(0.47f, 0.48f, 0.49f), new Color(0.25f, 0.36f, 0.27f), new Color(0.11f, 0.21f, 0.43f),
    };
    static readonly string[] PaintNames = { "white", "black", "red", "grey", "green", "navy" };
    internal static readonly float[] PaintWeights = { 0.27f, 0.25f, 0.14f, 0.18f, 0.08f, 0.08f };

    /// Random colour index from PaintWeights, u in [0, 1).
    internal static int PickPaint(double u)
    {
        double acc = 0;
        for (int i = 0; i < PaintWeights.Length; i++)
            if (u < (acc += PaintWeights[i])) return i;
        return PaintWeights.Length - 1;
    }

    static string ColourId(int k) => $"{ParkedId}_C{k}";

    static string ExportDir => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Export/Vehicles"));

    // LODGroup size = 2.0 m (bike length), 60 deg FOV: LOD1 from ~15 m, LOD2 from ~35 m, culled past ~90 m
    internal static readonly float[] MotoLodHeights = { 0.11f, 0.05f, 0.018f };

    // ------------------------------------------------------------------ assets
    static Texture2D ImportTex(string file, bool albedo)
    {
        Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, TexDir));
        string dst = $"{TexDir}/{file}";
        File.Copy(Path.Combine(ExportDir, "Textures", file), Path.Combine(HanoiSetup.ProjectDir, dst), true);
        AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        var imp = (TextureImporter)AssetImporter.GetAtPath(dst);
        imp.textureType = TextureImporterType.Default;
        imp.sRGBTexture = albedo;                          // data map = linear rough / metal / emission
        imp.alphaSource = albedo ? TextureImporterAlphaSource.FromInput : TextureImporterAlphaSource.None;
        imp.alphaIsTransparency = albedo;                  // dilate colour under the clipped texels
        imp.mipMapsPreserveCoverage = albedo;              // spokes keep their coverage at distance
        imp.alphaTestReferenceValue = 0.5f;
        imp.mipmapEnabled = true;
        imp.maxTextureSize = 1024;
        imp.anisoLevel = 8;
        imp.wrapMode = TextureWrapMode.Clamp;
        imp.filterMode = FilterMode.Trilinear;
        var ps = imp.GetDefaultPlatformTextureSettings();
        ps.textureCompression = TextureImporterCompression.CompressedHQ;
        imp.SetPlatformTextureSettings(ps);
        imp.SaveAndReimport();
        return AssetDatabase.LoadAssetAtPath<Texture2D>(dst);
    }

    internal static Material[] MotoMaterials()
    {
        var atlas = ImportTex("T_MotoAtlas.png", true);
        var data = ImportTex("T_MotoAtlasData.png", false);
        var mats = new Material[Paints.Length];
        for (int k = 0; k < Paints.Length; k++)
        {
            var mat = HanoiSetup.MaterialAsset($"M_Moto_{k}", "Hanoi/Vehicle");
            mat.SetTexture("_BaseMap", atlas);
            mat.SetTexture("_DataMap", data);
            mat.SetFloat("_Cutoff", 0.5f);
            mat.SetVector("_PaintRect", new Vector4(0f, 0.875f, 0.125f, 1f));   // build_moto_atlas.REGIONS palette cell 0
            mat.SetColor("_PaintColor", Paints[k]);
            EditorUtility.SetDirty(mat);
            mats[k] = mat;
        }
        AssetDatabase.SaveAssets();
        return mats;
    }

    [MenuItem("Hanoi/Motos/Import Motos")]
    public static void ImportMotos()
    {
        foreach (var d in new[] { ModelsDir, PrefabDir, TexDir })
            Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, d));
        var mats = MotoMaterials();
        var mat = mats[4];                                     // SH green: the FBX default / the rig
        var sh = Shader.Find("Hanoi/Vehicle");
        Debug.Log($"[Motos] shader Hanoi/Vehicle: found={sh != null} hasError={(sh != null && ShaderUtil.ShaderHasError(sh))}");
        if (sh != null)
            foreach (var m in ShaderUtil.GetShaderMessages(sh))
                Debug.Log($"[Motos]   {m.severity} {m.file}:{m.line} {m.message}");

        foreach (var id in new[] { ParkedId, RigId })
        {
            File.Copy(Path.Combine(ExportDir, "FBX", id + ".fbx"), Path.Combine(HanoiSetup.ProjectDir, ModelsDir, id + ".fbx"), true);
            AssetDatabase.ImportAsset($"{ModelsDir}/{id}.fbx", ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
            var imp = (ModelImporter)AssetImporter.GetAtPath($"{ModelsDir}/{id}.fbx");
            imp.importNormals = ModelImporterNormals.Import;       // Blender's smooth groups / sharp edges
            imp.importTangents = ModelImporterTangents.None;
            imp.importAnimation = false; imp.importCameras = false; imp.importLights = false;
            imp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
            imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_HanoiMoto"), mat);
            imp.SaveAndReimport();
        }

        // parked: merged mesh per LOD, one prefab per paint colour
        foreach (var f in Directory.GetFiles(Path.Combine(HanoiSetup.ProjectDir, PrefabDir), $"{ParkedId}.prefab"))
            AssetDatabase.DeleteAsset($"{PrefabDir}/{Path.GetFileName(f)}");        // old single-material prefab
        var model = AssetDatabase.LoadAssetAtPath<GameObject>($"{ModelsDir}/{ParkedId}.fbx");
        GameObject go;
        for (int k = 0; k < mats.Length; k++)
        {
            go = (GameObject)PrefabUtility.InstantiatePrefab(model);
            go.name = ColourId(k);
            HanoiSetup.SetupLods(go, MotoLodHeights);
            foreach (var r in go.GetComponentsInChildren<Renderer>())
            {
                r.sharedMaterial = mats[k];
                r.shadowCastingMode = r.name.EndsWith("_LOD2") ? ShadowCastingMode.Off : ShadowCastingMode.On;
            }
            if (k == 0) Report(go);
            PrefabUtility.SaveAsPrefabAsset(go, $"{PrefabDir}/{ColourId(k)}.prefab");
            Object.DestroyImmediate(go);
        }
        Debug.Log($"[Motos] colour prefabs: {string.Join(", ", PaintNames.Select((n, k) => $"C{k} {n}"))}");

        // rig: the FBX is flat (Blender's FBX axis bake breaks nested empties) -> rebuild the pivots here
        model = AssetDatabase.LoadAssetAtPath<GameObject>($"{ModelsDir}/{RigId}.fbx");
        go = (GameObject)PrefabUtility.InstantiatePrefab(model);
        PrefabUtility.UnpackPrefabInstance(go, PrefabUnpackMode.Completely, InteractionMode.AutomatedAction);
        Transform Pivot(string part, Transform parent)
        {
            var src = go.transform.Find(part + "_LOD0");
            var p = new GameObject(part).transform;
            p.SetParent(parent, false);
            p.position = src.position;
            foreach (var t in go.GetComponentsInChildren<Transform>().Where(t => t.name.StartsWith(part + "_LOD")).ToArray())
                t.SetParent(p, true);
            return p;
        }
        // Lean pivot on the ground under the wheelbase midpoint (= the root origin): the whole bike rolls about
        // the tyre contact line
        var lean = new GameObject("Lean").transform;
        lean.SetParent(go.transform, false);
        var steer = Pivot("Steer", lean);
        var wheelF = Pivot("WheelF", steer);
        var wheelR = Pivot("WheelR", lean);
        foreach (var t in go.transform.Cast<Transform>().Where(t => t != lean).ToArray())
            if (t.name.StartsWith("Body_LOD")) t.SetParent(lean, true);
        var rig = go.AddComponent<MotoRig>();
        rig.lean = lean; rig.steer = steer; rig.wheelF = wheelF; rig.wheelR = wheelR;
        var vj = LoadRig();
        if (vj != null)
        {
            rig.wheelRadiusF = vj.wheel_front.radius;
            rig.wheelRadiusR = vj.wheel_rear.radius;
            if (vj.steer_axis != null && vj.steer_axis.Length == 3)
                rig.steerAxis = new Vector3(vj.steer_axis[0], vj.steer_axis[1], vj.steer_axis[2]);
        }
        rig.wheelbase = Vector3.Distance(wheelF.position, wheelR.position);
        rig.paintRenderers = go.GetComponentsInChildren<Renderer>();
        HanoiSetup.SetupLods(go, MotoLodHeights);
        Report(go);
        Debug.Log($"[Motos] MotoRig: wheel radius F {rig.wheelRadiusF:F3} / R {rig.wheelRadiusR:F3}, wheelbase {rig.wheelbase:F3}, " +
                  $"steer axis {rig.steerAxis:F3}");
        PrefabUtility.SaveAsPrefabAsset(go, $"{PrefabDir}/{RigId}.prefab");
        Object.DestroyImmediate(go);
        AssetDatabase.SaveAssets();
    }

    [System.Serializable] class VehiclesJ { public VehicleJ[] vehicles; }
    [System.Serializable] class VehicleJ { public string name; public RigJ rig; }
    [System.Serializable] internal class RigJ { public float[] steer_axis; public WheelJ wheel_front, wheel_rear; }
    [System.Serializable] internal class WheelJ { public float radius; }

    /// vehicles.json rig block of the SH (Unity axes).
    static RigJ LoadRig()
    {
        var path = Path.Combine(ExportDir, "vehicles.json");
        if (!File.Exists(path)) return null;
        var v = JsonUtility.FromJson<VehiclesJ>(File.ReadAllText(path));
        return v?.vehicles?.FirstOrDefault(x => x.name == ParkedId)?.rig;
    }

    /// Paint material k (M_Moto_0..5) for a riding bike (MotoRig.SetPaint).
    public static Material LoadMaterial(int k) =>
        AssetDatabase.LoadAssetAtPath<Material>(AssetDatabase.GetAssetPath(LoadParked(k).GetComponentInChildren<Renderer>().sharedMaterial));

    static void Report(GameObject go)
    {
        var lg = go.GetComponent<LODGroup>();
        var tris = string.Join(", ", lg.GetLODs().Select((l, i) =>
            $"LOD{i} {l.renderers.Sum(r => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3)}"));
        Debug.Log($"[Motos] {go.name}: {lg.lodCount} LODs ({tris}), size {lg.size:F2} m, " +
                  $"materials {string.Join("/", go.GetComponentsInChildren<Renderer>().SelectMany(r => r.sharedMaterials).Select(m => m ? m.name : "null").Distinct())}");
    }

    public static GameObject LoadPrefab(string id) => AssetDatabase.LoadAssetAtPath<GameObject>($"{PrefabDir}/{id}.prefab");

    /// Parked bike prefab of colour k (0..5).
    public static GameObject LoadParked(int k) => LoadPrefab(ColourId(k));

    // ------------------------------------------------------------------ gallery
    [MenuItem("Hanoi/Motos/Build Moto Gallery")]
    public static void BuildGallery()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        HanoiLighting.Apply();
        var cam = Camera.main;
        cam.farClipPlane = 2000f; cam.nearClipPlane = 0.05f; cam.fieldOfView = 60f;
        var asphalt = HanoiSetup.LitMaterial("M_Asphalt", new Color(0.18f, 0.18f, 0.19f), 0.2f);
        var paving = HanoiSetup.LitMaterial("M_Sidewalk", new Color(0.50f, 0.48f, 0.45f), 0.15f);
        HanoiSetup.Box("Ground", new Vector3(0, -0.05f, 0), new Vector3(1000, 0.1f, 1000), asphalt);

        // street along X like the tree gallery: tube houses facing +Z on a 4 m sidewalk, bikes in front
        const float road = 4f, walk = 4f, lotW = 4f, walkY = 0.15f;
        const int houses = 16;
        float zHouse = -(road + walk);
        float rowLen = houses * lotW;
        var root = new GameObject("MotoGallery").transform;
        HanoiSetup.Box("Sidewalk", new Vector3(0, walkY / 2, -(road + walk / 2)), new Vector3(rowLen + 20, walkY, walk), paving);
        var tubes = AssetDatabase.FindAssets("t:Prefab", new[] { "Assets/Hanoi/Library/Prefabs" })
            .Select(g => AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(g)))
            .Select(g => g.GetComponent<BuildingVariant>())
            .Where(v => v != null && v.type == "tube" && string.IsNullOrEmpty(v.exposed) && v.depth <= 12.5f).ToList();
        var rng = new System.Random(5);
        for (int i = 0; i < houses && tubes.Count > 0; i++)
        {
            var h = (GameObject)PrefabUtility.InstantiatePrefab(tubes[rng.Next(tubes.Count)].gameObject, root);
            h.transform.SetPositionAndRotation(new Vector3(-rowLen / 2f + (i + 0.5f) * lotW, walkY, zHouse), Quaternion.identity);
        }
        // the same rule as the city: some fronts get 1-4 bikes against the facade, nose in or out
        var colours = Enumerable.Range(0, Paints.Length).Select(LoadParked).ToArray();
        int n = 0;
        for (int i = 0; i < houses; i++)
        {
            if (i % 3 == 1) continue;                                  // empty fronts
            int count = 1 + rng.Next(4);
            bool noseIn = rng.NextDouble() < 0.7;
            for (int k = 0; k < count; k++)
            {
                float x = -rowLen / 2f + (i + 0.5f) * lotW + (k - (count - 1) / 2f) * 0.8f;
                var b = (GameObject)PrefabUtility.InstantiatePrefab(colours[PickPaint(rng.NextDouble())], root);
                b.name = $"Moto_{n++:00}";
                float yaw = (noseIn ? 180f : 0f) + (float)(rng.NextDouble() * 14 - 7);
                b.transform.SetPositionAndRotation(new Vector3(x, walkY, zHouse + 0.35f + 1.0f), Quaternion.Euler(0, yaw, 0));
            }
        }
        // LOD comparison, away from the street
        var lodRoot = new GameObject("LodCompare").transform;
        for (int k = 0; k < 3; k++)
        {
            var b = (GameObject)PrefabUtility.InstantiatePrefab(colours[4], lodRoot);
            b.name = $"Moto_forceLOD{k}";
            b.transform.SetPositionAndRotation(new Vector3(200f + k * 2.6f, 0f, 200f), Quaternion.Euler(0, 90f, 0));
        }
        var rig = (GameObject)PrefabUtility.InstantiatePrefab(LoadPrefab(RigId), lodRoot);
        rig.transform.SetPositionAndRotation(new Vector3(200f + 8.2f, 0f, 200f), Quaternion.Euler(0, 90f, 0));
        rig.GetComponent<MotoRig>().Drive(0.5f, -12f, 0f);                // steered + rolled, to show the pivots
        EditorSceneManager.SaveScene(scene, GalleryScene);
        Debug.Log($"[Motos] gallery: {n} parked bikes in front of {houses} tube houses -> {GalleryScene}");
        CaptureShots();
    }

    [MenuItem("Hanoi/Motos/Capture Moto Shots")]
    public static void CaptureShots()
    {
        if (EditorSceneManager.GetActiveScene().path != GalleryScene)
            EditorSceneManager.OpenScene(GalleryScene);
        EditorSettings.asyncShaderCompilation = false;
        var cam = Camera.main;
        float z = -(4f + 4f) + 1.35f;
        HanoiSetup.Shot(cam, "x4_1_street_eye", new Vector3(-30f, 1.6f, -1.0f), new Vector3(-12f, 1.0f, z));
        HanoiSetup.Shot(cam, "x4_2_close", new Vector3(-21f, 1.4f, -2.2f), new Vector3(-24f, 0.6f, z));
        HanoiSetup.Shot(cam, "x4_3_far20", new Vector3(-20f, 1.7f, 14f), new Vector3(-10f, 1.0f, z));
        HanoiSetup.Shot(cam, "x4_4_drone", new Vector3(-20f, 25f, 22f), new Vector3(0f, 0f, z));
        var groups = Object.FindObjectsByType<LODGroup>(FindObjectsSortMode.None).Where(g => g.name.Contains("_forceLOD")).ToArray();
        foreach (var g in groups) g.ForceLOD(int.Parse(g.name.Substring(g.name.Length - 1)));
        HanoiSetup.Shot(cam, "x4_5_lods", new Vector3(204f, 1.3f, 194.5f), new Vector3(204f, 0.6f, 200f));
        foreach (var g in groups) g.ForceLOD(-1);
        Debug.Log($"[Motos] shots in {HanoiSetup.ShotsDir}");
    }

    public static void RunBatch()
    {
        ImportMotos();
        BuildGallery();
    }

    // ------------------------------------------------------------------ city
    [MenuItem("Hanoi/Motos/City Moto Shots")]
    public static void CityShots()
    {
        EditorSettings.asyncShaderCompilation = false;
        EditorSceneManager.OpenScene("Assets/Hanoi/City/City_Main.unity", OpenSceneMode.Single);
        var reg = Object.FindFirstObjectByType<CityChunks>();
        var cam = Camera.main;
        // densest stretch of parked bikes (Map/out/report_motos_dense.png): map (x, y) -> Unity (x, z)
        var c = new Vector3(-404.9f, 0f, -151.1f);
        HanoiTrees.LoadAround(reg, c, 300f);
        var along = new Vector3(0.80f, 0f, 0.60f);                   // street direction there (~37 deg)
        var side = new Vector3(-along.z, 0f, along.x);               // towards the road
        HanoiSetup.Shot(cam, "x4_c1_street", c - along * 22f + side * 5f + Vector3.up * 1.6f, c + along * 6f + Vector3.up * 0.8f);
        HanoiSetup.Shot(cam, "x4_c2_walk", c - along * 10f + side * 2.6f + Vector3.up * 1.6f, c + along * 4f + Vector3.up * 0.7f);
        HanoiSetup.Shot(cam, "x4_c3_drone", c + side * 30f + Vector3.up * 35f, c);
        Debug.Log($"[Motos] city shots in {HanoiSetup.ShotsDir}");
    }

    /// Whole chain after a change of the bikes or of their layout (Map/osm_pipeline.py):
    /// import bikes, place the city (houses + trees + bikes), rebuild HLOD, shots.
    public static void RunCityBatch()
    {
        CityBenchmarkBuild.ConfigureRendering();
        HanoiTrees.ImportTrees();
        ImportMotos();
        CityPlacer.Run();
        ChunkBuilder.Run();
        BuildGallery();
        CityShots();
    }
}
