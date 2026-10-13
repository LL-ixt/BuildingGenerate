using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

/// <summary>
/// M1: import the Blender variant library (Export/Library/library.json + FBX) as prefabs with
/// LODGroups, and build a gallery scene to review it.
/// Menu "Hanoi/Library/..." or batch: -executeMethod HanoiLibrary.RunBatch
/// </summary>
public static class HanoiLibrary
{
    const string LibRoot = "Assets/Hanoi/Library";
    const string ModelsDir = LibRoot + "/Models";
    const string PrefabDir = LibRoot + "/Prefabs";
    const string GalleryScene = LibRoot + "/LibraryGallery.unity";

    static string ExportLibDir => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Export/Library"));

    // towers are huge but cheap: swap massing LODs late, cull only very far away
    static readonly float[] TowerLodHeights = { 0.05f, 0.002f };

    [Serializable] class Manifest { public int version; public Variant[] variants; }
    [Serializable] public class Variant
    {
        public string id, type, archetype, file;
        public int floors, lods;
        public float frontage, depth, height;
        // tube houses (library.json v2)
        public string exposed, top, roof_color, ground;
        public float[] depth_scale;
    }

    static Manifest LoadManifest() =>
        JsonUtility.FromJson<Manifest>(File.ReadAllText(Path.Combine(ExportLibDir, "library.json")));

    [MenuItem("Hanoi/Library/Import Library")]
    public static void ImportLibrary()
    {
        var manifest = LoadManifest();
        foreach (var d in new[] { ModelsDir, PrefabDir })
            Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, d));

        // mirror the exported FBX set (stale variants are removed)
        var wanted = manifest.variants.Select(v => v.id + ".fbx").ToHashSet();
        foreach (var f in Directory.GetFiles(Path.Combine(HanoiSetup.ProjectDir, ModelsDir), "*.fbx"))
            if (!wanted.Contains(Path.GetFileName(f)))
                AssetDatabase.DeleteAsset($"{ModelsDir}/{Path.GetFileName(f)}");
        var wantedPrefabs = manifest.variants.Select(v => v.id + ".prefab").ToHashSet();
        foreach (var f in Directory.GetFiles(Path.Combine(HanoiSetup.ProjectDir, PrefabDir), "*.prefab"))
            if (!wantedPrefabs.Contains(Path.GetFileName(f)))
                AssetDatabase.DeleteAsset($"{PrefabDir}/{Path.GetFileName(f)}");
        foreach (var v in manifest.variants)
            File.Copy(Path.Combine(ExportLibDir, v.file), Path.Combine(HanoiSetup.ProjectDir, ModelsDir, v.id + ".fbx"), true);
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

        var kit = HanoiSetup.MaterialAsset("M_HanoiKit", "Hanoi/Building");
        var glass = HanoiSetup.MaterialAsset("M_HanoiGlass", "Hanoi/Window");
        HanoiSetup.ConfigureKitTexture(kit);

        AssetDatabase.StartAssetEditing();
        try
        {
            foreach (var v in manifest.variants)
                HanoiSetup.ConfigureModel($"{ModelsDir}/{v.id}.fbx", kit, glass);
        }
        finally { AssetDatabase.StopAssetEditing(); }

        int made = 0;
        foreach (var v in manifest.variants)
        {
            var model = AssetDatabase.LoadAssetAtPath<GameObject>($"{ModelsDir}/{v.id}.fbx");
            if (model == null) { Debug.LogError($"[Hanoi] missing model {v.id}"); continue; }
            var go = (GameObject)PrefabUtility.InstantiatePrefab(model);
            var lg = HanoiSetup.SetupLods(go, v.type == "tower" ? TowerLodHeights : HanoiSetup.TubeLodHeights);
            var info = go.GetComponent<BuildingVariant>();
            if (info == null) info = go.AddComponent<BuildingVariant>();
            info.variantId = v.id; info.type = v.type; info.archetype = v.archetype;
            info.floors = v.floors; info.frontage = v.frontage; info.depth = v.depth; info.height = v.height;
            info.exposed = v.exposed ?? ""; info.top = v.top ?? ""; info.roofColor = v.roof_color ?? "";
            info.ground = v.ground ?? "";
            info.depthScale = v.depth_scale != null && v.depth_scale.Length == 2
                ? new Vector2(v.depth_scale[0], v.depth_scale[1]) : Vector2.one;
            int lodCount = lg.lodCount;
            PrefabUtility.SaveAsPrefabAsset(go, $"{PrefabDir}/{v.id}.prefab");
            UnityEngine.Object.DestroyImmediate(go);
            if (lodCount != v.lods)
                Debug.LogWarning($"[Hanoi] {v.id}: LODGroup has {lodCount} levels, manifest says {v.lods}");
            made++;
        }
        AssetDatabase.SaveAssets();
        Debug.Log($"[Hanoi] library: {made}/{manifest.variants.Length} prefabs in {PrefabDir}");
    }

    public static GameObject LoadPrefab(string id) => AssetDatabase.LoadAssetAtPath<GameObject>($"{PrefabDir}/{id}.prefab");

    // ------------------------------------------------------------------ gallery
    [MenuItem("Hanoi/Library/Build Gallery Scene")]
    public static void BuildGallery()
    {
        var manifest = LoadManifest();
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        HanoiLighting.Apply();
        Camera.main.farClipPlane = 4000f;

        var ground = HanoiSetup.LitMaterial("M_Asphalt", new Color(0.18f, 0.18f, 0.19f), 0.2f);
        HanoiSetup.Box("Ground", new Vector3(0, -0.05f, 0), new Vector3(2000, 0.1f, 2000), ground);

        // tube houses: pairs of terraces (24 per row) facing streets along X, streets 60 m apart
        // (facade = model +Z); depth buckets in manifest order -> one street per bucket
        const int perRow = 24;
        var tubes = manifest.variants.Where(v => v.type == "tube").ToArray();
        var root = new GameObject("Gallery").transform;
        for (int i = 0; i < tubes.Length; i++)
        {
            int row = i / perRow, k = i % perRow;
            var p = (GameObject)PrefabUtility.InstantiatePrefab(LoadPrefab(tubes[i].id), root);
            bool south = row % 2 == 0;
            float z = (south ? -6f : 6f) - (row / 2) * 60f;
            p.transform.SetPositionAndRotation(new Vector3((k - (perRow - 1) / 2f) * 4f, 0, z),
                Quaternion.Euler(0, south ? 0f : 180f, 0));
        }
        // towers in a row behind
        var towers = manifest.variants.Where(v => v.type == "tower").ToArray();
        for (int j = 0; j < towers.Length; j++)
        {
            var p = (GameObject)PrefabUtility.InstantiatePrefab(LoadPrefab(towers[j].id), root);
            p.transform.SetPositionAndRotation(new Vector3((j - (towers.Length - 1) / 2f) * 70f, 0, 140f),
                Quaternion.Euler(0, 180f, 0));
        }
        EditorSceneManager.SaveScene(scene, GalleryScene);

        EditorSettings.asyncShaderCompilation = false;
        var cam = Camera.main;
        HanoiSetup.Shot(cam, "lib_1_street", new Vector3(-36f, 1.7f, 0f), new Vector3(10f, 8f, 0f));
        HanoiSetup.Shot(cam, "lib_2_street_high", new Vector3(-40f, 22f, -1f), new Vector3(8f, 6f, 0f));
        HanoiSetup.Shot(cam, "lib_3_overview", new Vector3(-60f, 120f, -260f), new Vector3(0f, 40f, 80f));
        Debug.Log($"[Hanoi] gallery: {tubes.Length} tube houses, {towers.Length} towers -> {GalleryScene}");
    }

    // ------------------------------------------------------------------ B4: tube street test
    const string TubeStreetScene = LibRoot + "/TubeStreetTest.unity";

    /// Two facing rows of terraces along a street (X axis), cut into blocks by side streets so the
    /// block ends are corners. Lots get random depths; TubeHousePicker chooses variant + depth scale
    /// and opens side windows on corners and where a house is taller than its neighbour.
    [MenuItem("Hanoi/Library/Build Tube Street Test")]
    public static void BuildTubeStreet()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        HanoiLighting.Apply();
        var cam = Camera.main;
        cam.farClipPlane = 4000f; cam.nearClipPlane = 0.1f; cam.fieldOfView = 60f;

        var library = AssetDatabase.FindAssets("t:Prefab", new[] { PrefabDir })
            .Select(g => AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(g)))
            .Select(go => go.GetComponent<BuildingVariant>())
            .Where(v => v != null && v.type == "tube").ToList();

        const float lotW = 4f, road = 4f, walk = 2.5f, sideStreet = 8f;
        int[] blocks = { 9, 12, 7 };                 // houses per block, west to east
        float rowLen = blocks.Sum() * lotW + (blocks.Length - 1) * sideStreet;
        var asphalt = HanoiSetup.LitMaterial("M_Asphalt", new Color(0.18f, 0.18f, 0.19f), 0.2f);
        var paving = HanoiSetup.LitMaterial("M_Sidewalk", new Color(0.50f, 0.48f, 0.45f), 0.15f);
        HanoiSetup.Box("Ground", new Vector3(0, -0.05f, 0), new Vector3(2000, 0.1f, 2000), asphalt);

        var root = new GameObject("TubeStreet").transform;
        var rng = new System.Random(4);
        int placed = 0, exposedCount = 0;
        for (int row = 0; row < 2; row++)
        {
            // south row faces +Z (north), north row faces -Z; viewer's right = house local -X
            float zEdge = (road + walk) * (row == 0 ? -1 : 1);
            var rot = Quaternion.Euler(0, row == 0 ? 0f : 180f, 0);
            Vector3 right = rot * Vector3.left;
            float x0 = -rowLen / 2f;
            float cursor = 0f;                       // distance along `right` from the row start
            Vector3 start = new Vector3(row == 0 ? -x0 : x0, 0.15f, zEdge);   // viewer's left end
            for (int b = 0; b < blocks.Length; b++)
            {
                var lots = Enumerable.Range(0, blocks[b])
                    .Select(_ => new TubeHousePicker.Lot { depth = 8f + (float)rng.NextDouble() * 10f }).ToList();
                var picks = TubeHousePicker.PickRow(library, lots, true, true, 100 * row + b);
                for (int i = 0; i < picks.Length; i++)
                {
                    var c = picks[i];
                    if (c.variant == null) continue;
                    var go = (GameObject)PrefabUtility.InstantiatePrefab(c.variant.gameObject, root);
                    go.name = $"{c.variant.variantId}_r{row}b{b}_{i:00}";
                    Vector3 pos = start + right * (cursor + (i + 0.5f) * lotW);
                    go.transform.SetPositionAndRotation(pos, rot);
                    go.transform.localScale = new Vector3(1f, 1f, c.depthScale);
                    placed++;
                    if (c.exposedLeft || c.exposedRight) exposedCount++;
                }
                cursor += blocks[b] * lotW + sideStreet;
            }
            // sidewalk strip along the row
            HanoiSetup.Box($"Sidewalk_{row}", new Vector3(0, 0.07f, zEdge - (row == 0 ? -walk / 2 : walk / 2)),
                new Vector3(rowLen + 20, 0.15f, walk), paving);
        }
        EditorSceneManager.SaveScene(scene, TubeStreetScene);

        EditorSettings.asyncShaderCompilation = false;
        float cx = blocks[0] * lotW + sideStreet / 2f - rowLen / 2f;   // north row: first side street (x)
        HanoiSetup.Shot(cam, "b4_1_street", new Vector3(-rowLen / 2f + 6f, 1.7f, 1.5f), new Vector3(0f, 6f, -4f));
        HanoiSetup.Shot(cam, "b4_2_corner", new Vector3(cx + 9f, 1.8f, 1.0f), new Vector3(cx - 3f, 8f, 13f));
        HanoiSetup.Shot(cam, "b4_2b_corner_other", new Vector3(cx - 9f, 1.8f, 1.0f), new Vector3(cx + 3f, 8f, 13f));
        HanoiSetup.Shot(cam, "b4_3_drone", new Vector3(-rowLen / 2f - 15f, 32f, -4f), new Vector3(-10f, 2f, 0f));
        HanoiSetup.Shot(cam, "b4_4_shop_close", new Vector3(-rowLen / 2f + 20f, 1.6f, 0.5f), new Vector3(-rowLen / 2f + 24f, 2.0f, -7f));
        HanoiSetup.Shot(cam, "b4_5_far_lod", new Vector3(-250f, 180f, 260f), new Vector3(0f, 0f, 0f));
        Debug.Log($"[Hanoi] tube street: {placed} houses ({exposedCount} with exposed side walls) -> {TubeStreetScene}");
    }

    public static void RunBatch()
    {
        ImportLibrary();
        BuildGallery();
        BuildTubeStreet();
    }

    public static void RunTubeStreet() => BuildTubeStreet();
}
