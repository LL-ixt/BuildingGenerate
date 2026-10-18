using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// RIDER R4: the male rider of the Honda SH (Blender/scripts/build_rider.py -- --r3 -> Export/Vehicles: FBX, baked
/// albedo + data map, vehicles.json "SM_Rider_M") as Unity prefabs and a gallery. Body MakeHuman (CC0), polo CC0,
/// trousers / sneakers / helmet CC-BY (vehicles.json "credits", PROJECT_NOTES).
/// Menu "Hanoi/Riders/..." or batch: -executeMethod HanoiRiders.RunBatch
/// Prefabs (Assets/Hanoi/Vehicles/Prefabs):
///   SM_Rider_M             the rider; origin = the bike origin (ground, wheelbase midpoint): child of an
///                          SM_Moto_SH_* prefab with no offset. Own LODGroup, culled with the bike.
///                          Ride(bike, shirt, helmet) places one and sets the material of that colour pair.
///   SM_Moto_SH_Rig_Ridden  the riding bike rig (HanoiMotos) with a rider on it, for traffic later.
/// Materials M_Rider_S{s}_H{h} (Hanoi/Vehicle, _PaintMaskMode 2): shirt + helmet shell baked grey, data A = shirt
/// mask (_PaintColor), data B = helmet mask (_PaintColor2). One material per pair: no per-instance data.
/// </summary>
public static class HanoiRiders
{
    const string Root = "Assets/Hanoi/Vehicles";
    const string ModelsDir = Root + "/Models";
    const string PrefabDir = Root + "/Prefabs";
    const string TexDir = Root + "/Textures";
    const string GalleryScene = Root + "/RiderGallery.unity";
    public const string RiderId = "SM_Rider_M";
    const string RiddenRigId = "SM_Moto_SH_Rig_Ridden";

    // shirt colours (sRGB, = hanoi_rider.SHIRT_COLOURS) and how common they are
    internal static readonly Color[] Shirts =
    {
        new Color(0.88f, 0.88f, 0.86f), new Color(0.55f, 0.68f, 0.82f), new Color(0.12f, 0.17f, 0.32f),
        new Color(0.45f, 0.46f, 0.47f), new Color(0.16f, 0.30f, 0.20f), new Color(0.42f, 0.10f, 0.12f),
    };
    static readonly string[] ShirtNames = { "white", "light blue", "navy", "grey", "dark green", "maroon" };
    internal static readonly float[] ShirtWeights = { 0.26f, 0.14f, 0.20f, 0.18f, 0.10f, 0.12f };

    // helmet shell colours (sRGB, = hanoi_rider.HELMET_COLOURS) and how common they are
    internal static readonly Color[] Helmets =
    {
        new Color(0.90f, 0.90f, 0.88f), new Color(0.06f, 0.06f, 0.07f), new Color(0.62f, 0.08f, 0.09f),
        new Color(0.10f, 0.25f, 0.60f), new Color(0.55f, 0.56f, 0.58f), new Color(0.85f, 0.70f, 0.10f),
    };
    static readonly string[] HelmetNames = { "white", "black", "red", "blue", "silver", "yellow" };
    internal static readonly float[] HelmetWeights = { 0.24f, 0.24f, 0.14f, 0.14f, 0.16f, 0.08f };

    // LOD switch distances (m, 60 deg FOV): LOD1 from ~15 m, culled past ~90 m like the bike (HanoiMotos.MotoLodHeights)
    static readonly float[] LodDistances = { 15f, 90f };

    static string ExportDir => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Export/Vehicles"));
    static string MaterialName(int s, int h) => $"M_Rider_S{s}_H{h}";

    static int Pick(float[] weights, double u)
    {
        double acc = 0;
        for (int i = 0; i < weights.Length; i++)
            if (u < (acc += weights[i])) return i;
        return weights.Length - 1;
    }

    internal static int PickShirt(double u) => Pick(ShirtWeights, u);
    internal static int PickHelmet(double u) => Pick(HelmetWeights, u);

    // ------------------------------------------------------------------ assets
    static Texture2D ImportTex(string file, bool albedo)
    {
        Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, TexDir));
        string dst = $"{TexDir}/{file}";
        File.Copy(Path.Combine(ExportDir, "Textures", file), Path.Combine(HanoiSetup.ProjectDir, dst), true);
        AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        var imp = (TextureImporter)AssetImporter.GetAtPath(dst);
        imp.textureType = TextureImporterType.Default;
        imp.sRGBTexture = albedo;
        // data: B = helmet mask, A = shirt mask, kept as is
        imp.alphaSource = albedo ? TextureImporterAlphaSource.None : TextureImporterAlphaSource.FromInput;
        imp.alphaIsTransparency = false;
        imp.mipmapEnabled = true;
        imp.maxTextureSize = 512;
        imp.anisoLevel = 4;
        imp.wrapMode = TextureWrapMode.Clamp;
        imp.filterMode = FilterMode.Trilinear;
        var ps = imp.GetDefaultPlatformTextureSettings();
        ps.textureCompression = TextureImporterCompression.CompressedHQ;
        imp.SetPlatformTextureSettings(ps);
        imp.SaveAndReimport();
        return AssetDatabase.LoadAssetAtPath<Texture2D>(dst);
    }

    /// One material per (shirt, helmet) pair: [s, h].
    internal static Material[,] RiderMaterials()
    {
        var albedo = ImportTex("T_RiderM.png", true);
        var data = ImportTex("T_RiderMData.png", false);
        // single-colour materials of the first R4 (M_Rider_0..5)
        foreach (var g in AssetDatabase.FindAssets("M_Rider_ t:Material"))
        {
            var p = AssetDatabase.GUIDToAssetPath(g);
            if (Regex.IsMatch(Path.GetFileNameWithoutExtension(p), @"^M_Rider_\d$")) AssetDatabase.DeleteAsset(p);
        }
        var mats = new Material[Shirts.Length, Helmets.Length];
        for (int s = 0; s < Shirts.Length; s++)
            for (int h = 0; h < Helmets.Length; h++)
            {
                var mat = HanoiSetup.MaterialAsset(MaterialName(s, h), "Hanoi/Vehicle");
                mat.SetTexture("_BaseMap", albedo);
                mat.SetTexture("_DataMap", data);
                mat.SetTexture("_BumpMap", null);              // flat (far view, no normal map baked)
                mat.SetFloat("_Cutoff", 0f);
                mat.SetFloat("_PaintMaskMode", 2f);
                mat.SetVector("_PaintRect", new Vector4(-1f, -1f, -1f, -1f));
                mat.SetColor("_PaintColor", Shirts[s]);
                mat.SetColor("_PaintColor2", Helmets[h]);
                EditorUtility.SetDirty(mat);
                mats[s, h] = mat;
            }
        AssetDatabase.SaveAssets();
        return mats;
    }

    /// LOD heights from the switch distances and the group's size (screen height = size / (2 d tan 30 deg)).
    static void SetLodDistances(LODGroup lg)
    {
        var lods = lg.GetLODs();
        float k = 2f * Mathf.Tan(30f * Mathf.Deg2Rad);
        for (int i = 0; i < lods.Length; i++)
            lods[i].screenRelativeTransitionHeight = lg.size / (k * LodDistances[i]);
        lg.SetLODs(lods);
    }

    [MenuItem("Hanoi/Riders/Import Riders")]
    public static void ImportRiders()
    {
        foreach (var d in new[] { ModelsDir, PrefabDir, TexDir })
            Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, d));
        var mats = RiderMaterials();

        string dst = $"{ModelsDir}/{RiderId}.fbx";
        File.Copy(Path.Combine(ExportDir, "FBX", RiderId + ".fbx"), Path.Combine(HanoiSetup.ProjectDir, dst), true);
        AssetDatabase.ImportAsset(dst, ImportAssetOptions.ForceSynchronousImport | ImportAssetOptions.ForceUpdate);
        var imp = (ModelImporter)AssetImporter.GetAtPath(dst);
        imp.importNormals = ModelImporterNormals.Import;              // Blender's smooth-by-angle
        imp.importTangents = ModelImporterTangents.None;
        imp.importAnimation = false; imp.importCameras = false; imp.importLights = false;
        imp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
        imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_RiderM"), mats[0, 0]);
        imp.SaveAndReimport();
        var model = AssetDatabase.LoadAssetAtPath<GameObject>(dst);

        // single-colour prefabs of the first R4 (SM_Rider_M_C0..5)
        foreach (var f in Directory.GetFiles(Path.Combine(HanoiSetup.ProjectDir, PrefabDir), $"{RiderId}_C?.prefab"))
            AssetDatabase.DeleteAsset($"{PrefabDir}/{Path.GetFileName(f)}");
        var go = (GameObject)PrefabUtility.InstantiatePrefab(model);
        go.name = RiderId;
        SetLodDistances(HanoiSetup.SetupLods(go, new[] { 0.1f, 0.02f }));
        foreach (var r in go.GetComponentsInChildren<Renderer>())
        {
            r.sharedMaterial = mats[0, 0];
            r.shadowCastingMode = r.name.EndsWith("_LOD1") ? ShadowCastingMode.Off : ShadowCastingMode.On;
        }
        Report(go);
        PrefabUtility.SaveAsPrefabAsset(go, $"{PrefabDir}/{RiderId}.prefab");
        Object.DestroyImmediate(go);
        Debug.Log($"[Riders] {mats.Length} materials: shirts {string.Join(", ", ShirtNames.Select((n, k) => $"S{k} {n}"))}; " +
                  $"helmets {string.Join(", ", HelmetNames.Select((n, k) => $"H{k} {n}"))}");

        // riding rig + rider (nested prefabs: the bike keeps its own LODGroup, the rider his)
        var rigSrc = HanoiMotos.LoadPrefab("SM_Moto_SH_Rig");
        if (rigSrc == null)
        {
            Debug.LogWarning("[Riders] SM_Moto_SH_Rig missing: run HanoiMotos.ImportMotos first");
            return;
        }
        var rig = (GameObject)PrefabUtility.InstantiatePrefab(rigSrc);
        rig.name = RiddenRigId;
        Ride(rig.transform, 0, 1);
        PrefabUtility.SaveAsPrefabAsset(rig, $"{PrefabDir}/{RiddenRigId}.prefab");
        Object.DestroyImmediate(rig);
        AssetDatabase.SaveAssets();
    }

    static void Report(GameObject go)
    {
        var lg = go.GetComponent<LODGroup>();
        var lods = lg.GetLODs();
        var tris = string.Join(", ", lods.Select((l, i) =>
            $"LOD{i} {l.renderers.Sum(r => r.GetComponent<MeshFilter>().sharedMesh.triangles.Length / 3)} tris " +
            $"(h {l.screenRelativeTransitionHeight:F3})"));
        var b = go.GetComponentsInChildren<MeshRenderer>().First(r => r.name.EndsWith("_LOD0")).bounds;
        Debug.Log($"[Riders] {go.name}: {tris}, size {lg.size:F2} m, bounds min {b.min:F3} max {b.max:F3}");
    }

    public static GameObject LoadPrefab(string id) => AssetDatabase.LoadAssetAtPath<GameObject>($"{PrefabDir}/{id}.prefab");

    public static Material LoadMaterial(int shirt, int helmet) =>
        AssetDatabase.FindAssets($"{MaterialName(shirt, helmet)} t:Material")
            .Select(g => AssetDatabase.LoadAssetAtPath<Material>(AssetDatabase.GUIDToAssetPath(g)))
            .FirstOrDefault(m => m != null && m.name == MaterialName(shirt, helmet));

    /// Rider with that shirt / helmet colour on the bike `bike` (child, no offset: both share the bike origin;
    /// on a riding rig under its Lean pivot, so he leans with the bike).
    public static GameObject Ride(Transform bike, int shirt, int helmet)
    {
        var rig = bike.GetComponent<MotoRig>();                  // Unity null: no ?. on components
        var parent = rig != null && rig.lean != null ? rig.lean : bike;
        var r = (GameObject)PrefabUtility.InstantiatePrefab(LoadPrefab(RiderId), parent);
        r.transform.localPosition = Vector3.zero;
        r.transform.localRotation = Quaternion.identity;
        r.transform.localScale = Vector3.one;
        var mat = LoadMaterial(shirt, helmet);
        foreach (var rend in r.GetComponentsInChildren<Renderer>())
            rend.sharedMaterial = mat;
        return r;
    }

    /// Rider with random colours (seeded rng: re-placing gives the same riders).
    public static GameObject RideRandom(Transform bike, System.Random rng) =>
        Ride(bike, PickShirt(rng.NextDouble()), PickHelmet(rng.NextDouble()));

    // ------------------------------------------------------------------ gallery
    [MenuItem("Hanoi/Riders/Build Rider Gallery")]
    public static void BuildGallery()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        HanoiLighting.Apply();
        var cam = Camera.main;
        cam.farClipPlane = 2000f; cam.nearClipPlane = 0.05f; cam.fieldOfView = 60f;
        var asphalt = HanoiSetup.LitMaterial("M_Asphalt", new Color(0.18f, 0.18f, 0.19f), 0.2f);
        HanoiSetup.Box("Ground", new Vector3(0, -0.05f, 0), new Vector3(1000, 0.1f, 1000), asphalt);
        var root = new GameObject("RiderGallery").transform;
        // a row along X: bike colour k, shirt k, helmet k, then an empty bike for comparison
        for (int k = 0; k < Shirts.Length; k++)
        {
            var b = (GameObject)PrefabUtility.InstantiatePrefab(HanoiMotos.LoadParked(k), root);
            b.transform.SetPositionAndRotation(new Vector3((k - 2.5f) * 1.5f, 0f, 0f), Quaternion.identity);
            Ride(b.transform, k, k);
        }
        var empty = (GameObject)PrefabUtility.InstantiatePrefab(HanoiMotos.LoadParked(1), root);
        empty.transform.SetPositionAndRotation(new Vector3(3.5f * 1.5f, 0f, 0f), Quaternion.identity);
        // a loose group in traffic: random bikes / shirts / helmets, a little yaw
        var rng = new System.Random(11);
        for (int i = 0; i < 12; i++)
        {
            var b = (GameObject)PrefabUtility.InstantiatePrefab(HanoiMotos.LoadParked(HanoiMotos.PickPaint(rng.NextDouble())), root);
            b.name = $"Traffic_{i:00}";
            var p = new Vector3(12f + (i % 4) * 1.3f + (float)rng.NextDouble() * 0.5f, 0f, (i / 4) * 2.4f + (float)rng.NextDouble() * 0.8f);
            b.transform.SetPositionAndRotation(p, Quaternion.Euler(0f, (float)(rng.NextDouble() * 10 - 5), 0f));
            RideRandom(b.transform, rng);
        }
        // LOD comparison + the ridden rig, away from the row
        var lodRoot = new GameObject("LodCompare").transform;
        for (int k = 0; k < 2; k++)
        {
            var b = (GameObject)PrefabUtility.InstantiatePrefab(HanoiMotos.LoadParked(2), lodRoot);
            b.name = $"Moto_forceLOD{k}";
            b.transform.SetPositionAndRotation(new Vector3(200f + k * 2.6f, 0f, 200f), Quaternion.Euler(0, 90f, 0));
            Ride(b.transform, 2, 0).name = $"Rider_forceLOD{k}";
        }
        var rig = (GameObject)PrefabUtility.InstantiatePrefab(LoadPrefab(RiddenRigId), lodRoot);
        rig.transform.SetPositionAndRotation(new Vector3(200f + 5.6f, 0f, 200f), Quaternion.Euler(0, 90f, 0));
        // TRAFFIC T2: riding rigs leaning / steering (nose +z): upright, right turn, left turn, parking steer
        var leanRoot = new GameObject("LeanTest").transform;
        var poses = new[] { (0f, 0f), (6f, 25f), (-6f, -25f), (12f, 0f) };
        for (int k = 0; k < poses.Length; k++)
        {
            var b = (GameObject)PrefabUtility.InstantiatePrefab(HanoiMotos.LoadPrefab("SM_Moto_SH_Rig"), leanRoot);
            b.name = $"Lean_{k}";
            b.transform.SetPositionAndRotation(new Vector3(300f + k * 2.2f, 0f, 200f), Quaternion.identity);
            var mr = b.GetComponent<MotoRig>();
            mr.SetPaint(HanoiMotos.LoadMaterial(k + 1));
            RideRandom(b.transform, rng);
            mr.Drive(0f, poses[k].Item1, poses[k].Item2);
        }
        CheckWheelSpin();
        EditorSceneManager.SaveScene(scene, GalleryScene);
        Debug.Log($"[Riders] gallery -> {GalleryScene}");
        CaptureShots();
    }

    [MenuItem("Hanoi/Riders/Capture Rider Shots")]
    public static void CaptureShots()
    {
        if (EditorSceneManager.GetActiveScene().path != GalleryScene)
            EditorSceneManager.OpenScene(GalleryScene);
        EditorSettings.asyncShaderCompilation = false;
        var cam = Camera.main;
        HanoiSetup.Shot(cam, "rider_r4_1_front10", new Vector3(-2f, 1.6f, 10f), new Vector3(0f, 0.9f, 0f));
        HanoiSetup.Shot(cam, "rider_r4_2_close", new Vector3(-5.6f, 1.5f, 2.4f), new Vector3(-3.75f, 1.0f, 0f));
        HanoiSetup.Shot(cam, "rider_r4_3_side", new Vector3(-9f, 1.3f, 0.6f), new Vector3(-3.75f, 0.9f, 0f));
        HanoiSetup.Shot(cam, "rider_r4_4_far30", new Vector3(8f, 1.7f, 32f), new Vector3(8f, 0.8f, 2f));
        HanoiSetup.Shot(cam, "rider_r4_5_drone", new Vector3(4f, 18f, 22f), new Vector3(8f, 0f, 2f));
        HanoiSetup.Shot(cam, "rider_r4_7_traffic", new Vector3(10f, 1.8f, 12f), new Vector3(14f, 0.9f, 2.5f));
        var groups = Object.FindObjectsByType<LODGroup>(FindObjectsSortMode.None).Where(g => g.name.Contains("_forceLOD")).ToArray();
        foreach (var g in groups) g.ForceLOD(int.Parse(g.name.Substring(g.name.Length - 1)));
        HanoiSetup.Shot(cam, "rider_r4_6_lods_rig", new Vector3(202.8f, 1.5f, 194f), new Vector3(202.8f, 0.9f, 200f));
        foreach (var g in groups) g.ForceLOD(-1);
        // T2: lean / steer (Lean_0 upright, 1 right 25 deg, 2 left 25 deg, 3 parking steer 12 deg)
        HanoiSetup.Shot(cam, "traffic_t2_1_front", new Vector3(303.3f, 1.3f, 207f), new Vector3(303.3f, 0.8f, 200f));
        HanoiSetup.Shot(cam, "traffic_t2_2_rear", new Vector3(303.3f, 1.6f, 193.5f), new Vector3(303.3f, 0.8f, 200f));
        HanoiSetup.Shot(cam, "traffic_t2_3_hands", new Vector3(306.6f, 2.6f, 201.2f), new Vector3(306.6f, 0.9f, 200.2f));
        Debug.Log($"[Riders] shots in {HanoiSetup.ShotsDir}");
    }

    /// Rolling forward (+z) must move the top of each wheel forward; leaning right must move the head to +x.
    static void CheckWheelSpin()
    {
        var go = (GameObject)PrefabUtility.InstantiatePrefab(HanoiMotos.LoadPrefab("SM_Moto_SH_Rig"));
        var mr = go.GetComponent<MotoRig>();
        Ride(go.transform, 0, 0);
        Vector3 TopF() => mr.wheelF.TransformPoint(Vector3.up * mr.wheelRadiusF);
        Vector3 TopR() => mr.wheelR.TransformPoint(Vector3.up * mr.wheelRadiusR);
        var head0 = go.GetComponentsInChildren<Renderer>().First(r => r.name.Contains("Rider")).bounds.max;
        var f0 = TopF(); var r0 = TopR();
        mr.Drive(0.05f, 0f, 0f);
        var f1 = TopF(); var r1 = TopR();
        mr.Drive(0f, 0f, 20f);
        var head1 = go.GetComponentsInChildren<Renderer>().First(r => r.name.Contains("Rider")).bounds.max;
        mr.Drive(0f, 10f, 0f);
        var nose = mr.wheelF.position + mr.wheelF.forward;          // wheel forward after steering right
        Debug.Log($"[Riders] T2 check: wheel tops move forward F {f1.z - f0.z:+0.000;-0.000} R {r1.z - r0.z:+0.000;-0.000} m " +
                  $"(both > 0 ok); lean right 20 deg moves the rider's top x {head1.x - head0.x:+0.00;-0.00} m (> 0 ok); " +
                  $"steer right 10 deg turns the front wheel to x {nose.x - mr.wheelF.position.x:+0.00;-0.00} (> 0 ok)");
        Object.DestroyImmediate(go);
    }

    public static void RunBatch()
    {
        ImportRiders();
        BuildGallery();
    }
}
