using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// T4: street trees from Blender (Export/Trees/trees.json + FBX, built by Blender/scripts/build_manual_trees.py)
/// as prefabs with LODGroups + a gallery street to review them.
/// Menu "Hanoi/Trees/..." or batch: -executeMethod HanoiTrees.RunBatch
/// Materials: M_Bark (URP Lit, T_Bark), M_Foliage (Hanoi/Foliage, leaf atlas, alpha clip),
/// M_FoliageBlob (Hanoi/Foliage with _VertexAlbedo: LOD2 crown coloured by vertex colour).
/// </summary>
public static class HanoiTrees
{
    const string TreeRoot = "Assets/Hanoi/Trees";
    const string ModelsDir = TreeRoot + "/Models";
    const string PrefabDir = TreeRoot + "/Prefabs";
    const string GalleryScene = TreeRoot + "/TreeGallery.unity";

    static string ExportTreeDir => Path.GetFullPath(Path.Combine(HanoiSetup.ProjectDir, "../Export/Trees"));

    // ~15 m tree, 60 deg FOV: LOD1 from ~35 m, LOD2 from ~110 m, culled past ~1.5 km
    internal static readonly float[] TreeLodHeights = { 0.35f, 0.11f, 0.009f };

    [Serializable] class Manifest { public string source; public Tree[] trees; }
    const string HlodModelsDir = TreeRoot + "/HLOD";

    [Serializable] public class Tree
    {
        public string id, species, fbx, hlod;
        public float height, scale, crown_r;
        public int[] tris;
    }

    static Manifest LoadManifest() =>
        JsonUtility.FromJson<Manifest>(File.ReadAllText(Path.Combine(ExportTreeDir, "trees.json")));

    // ------------------------------------------------------------------ materials
    internal static Material Foliage()
    {
        var mat = HanoiSetup.MaterialAsset("M_Foliage", "Hanoi/Foliage");
        mat.SetTexture("_BaseMap", HanoiSetup.ImportTexture("Trees/T_Foliage.png", alphaCoverage: true));
        mat.SetFloat("_VertexAlbedo", 0f);
        mat.SetFloat("_Cutoff", 0.5f);
        mat.SetFloat("_AOMin", 0.62f);
        EditorUtility.SetDirty(mat);
        return mat;
    }

    internal static Material FoliageBlob()
    {
        var mat = HanoiSetup.MaterialAsset("M_FoliageBlob", "Hanoi/Foliage");
        mat.SetFloat("_VertexAlbedo", 1f);
        mat.SetFloat("_Translucency", 0.3f);
        mat.SetFloat("_BlobGain", 1.5f);
        EditorUtility.SetDirty(mat);
        return mat;
    }

    internal static Material Bark() =>
        HanoiSetup.LitMaterial("M_Bark", Color.white, 0.05f, "Trees/T_Bark.png", Vector2.one);

    // ------------------------------------------------------------------ import
    [MenuItem("Hanoi/Trees/Import Trees")]
    public static void ImportTrees()
    {
        var manifest = LoadManifest();
        foreach (var d in new[] { ModelsDir, PrefabDir, HlodModelsDir })
            Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, d));
        // crown-only far meshes for the chunk HLOD (ChunkBuilder), not part of the prefabs
        foreach (var t in manifest.trees.Where(t => !string.IsNullOrEmpty(t.hlod)))
            File.Copy(Path.Combine(ExportTreeDir, t.hlod), Path.Combine(HanoiSetup.ProjectDir, HlodModelsDir, t.id + "_HLOD.fbx"), true);

        // mirror the exported set (stale trees are removed)
        var wanted = manifest.trees.Select(t => t.id).ToHashSet();
        foreach (var f in Directory.GetFiles(Path.Combine(HanoiSetup.ProjectDir, ModelsDir), "*.fbx"))
            if (!wanted.Contains(Path.GetFileNameWithoutExtension(f)))
                AssetDatabase.DeleteAsset($"{ModelsDir}/{Path.GetFileName(f)}");
        foreach (var f in Directory.GetFiles(Path.Combine(HanoiSetup.ProjectDir, PrefabDir), "*.prefab"))
            if (!wanted.Contains(Path.GetFileNameWithoutExtension(f)))
                AssetDatabase.DeleteAsset($"{PrefabDir}/{Path.GetFileName(f)}");
        foreach (var t in manifest.trees)
            File.Copy(Path.Combine(ExportTreeDir, t.fbx), Path.Combine(HanoiSetup.ProjectDir, ModelsDir, t.id + ".fbx"), true);
        AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

        var bark = Bark();
        var leaf = Foliage();
        var blob = FoliageBlob();
        var sh = Shader.Find("Hanoi/Foliage");
        Debug.Log($"[Trees] shader Hanoi/Foliage: hasError={ShaderUtil.ShaderHasError(sh)}");
        foreach (var m in ShaderUtil.GetShaderMessages(sh))
            Debug.Log($"[Trees]   {m.severity} {m.file}:{m.line} {m.message}");

        AssetDatabase.StartAssetEditing();
        try
        {
            foreach (var t in manifest.trees)
            {
                var imp = (ModelImporter)AssetImporter.GetAtPath($"{ModelsDir}/{t.id}.fbx");
                imp.importNormals = ModelImporterNormals.Import;          // keep the baked crown normals
                imp.importTangents = ModelImporterTangents.None;
                imp.importAnimation = false;
                imp.importCameras = false;
                imp.importLights = false;
                imp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
                imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_Bark"), bark);
                imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_Foliage"), leaf);
                imp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_FoliageBlob"), blob);
                imp.SaveAndReimport();
                var himp = AssetImporter.GetAtPath($"{HlodModelsDir}/{t.id}_HLOD.fbx") as ModelImporter;
                if (himp == null) continue;
                himp.importNormals = ModelImporterNormals.Import;
                himp.importTangents = ModelImporterTangents.None;
                himp.importAnimation = false; himp.importCameras = false; himp.importLights = false;
                himp.isReadable = true;                                      // ChunkBuilder reads it
                himp.materialImportMode = ModelImporterMaterialImportMode.ImportStandard;
                himp.AddRemap(new AssetImporter.SourceAssetIdentifier(typeof(Material), "M_FoliageBlob"), blob);
                himp.SaveAndReimport();
            }
        }
        finally { AssetDatabase.StopAssetEditing(); }

        int made = 0;
        foreach (var t in manifest.trees)
        {
            var model = AssetDatabase.LoadAssetAtPath<GameObject>($"{ModelsDir}/{t.id}.fbx");
            if (model == null) { Debug.LogError($"[Trees] missing model {t.id}"); continue; }
            var go = (GameObject)PrefabUtility.InstantiatePrefab(model);
            var lg = HanoiSetup.SetupLods(go, TreeLodHeights);
            AddShadowProxy(lg);
            int lodCount = lg.lodCount;
            var tris = go.GetComponentsInChildren<MeshFilter>().OrderBy(f => f.name)
                .Select(f => $"{f.name.Substring(f.name.LastIndexOf('_') + 1)} {f.sharedMesh.triangles.Length / 3}").ToArray();
            var mats = go.GetComponentsInChildren<Renderer>().SelectMany(r => r.sharedMaterials)
                .Select(m => m != null ? m.name : "null").Distinct().ToArray();
            PrefabUtility.SaveAsPrefabAsset(go, $"{PrefabDir}/{t.id}.prefab");
            UnityEngine.Object.DestroyImmediate(go);
            Debug.Log($"[Trees] {t.id}: {lodCount} LODs, {string.Join(", ", tris)}, materials {string.Join("/", mats)}");
            made++;
        }
        AssetDatabase.SaveAssets();
        Debug.Log($"[Trees] {made}/{manifest.trees.Length} prefabs in {PrefabDir}");
    }

    /// LOD0 (6k tris of alpha-clipped cards) no longer casts shadows; a hidden ShadowsOnly copy of the
    /// LOD1 mesh (2k tris, fewer bigger cards: nearly the same leaf shadow) does it instead, as part of
    /// LOD0 so it switches with it. LOD1 / LOD2 keep casting their own shadows.
    static void AddShadowProxy(LODGroup lg)
    {
        var lods = lg.GetLODs();
        if (lods.Length < 2) return;
        var lod1 = lods[1].renderers.OfType<MeshRenderer>().FirstOrDefault();
        var mf1 = lod1 != null ? lod1.GetComponent<MeshFilter>() : null;
        if (mf1 == null) return;
        foreach (var r in lods[0].renderers)
            if (r != null) r.shadowCastingMode = ShadowCastingMode.Off;
        var proxy = new GameObject(lod1.name.Replace("_LOD1", "_ShadowProxy"));
        proxy.transform.SetParent(lod1.transform.parent, false);
        proxy.transform.localPosition = lod1.transform.localPosition;
        proxy.transform.localRotation = lod1.transform.localRotation;
        proxy.transform.localScale = lod1.transform.localScale;
        proxy.AddComponent<MeshFilter>().sharedMesh = mf1.sharedMesh;
        var pr = proxy.AddComponent<MeshRenderer>();
        pr.sharedMaterials = lod1.sharedMaterials;
        pr.shadowCastingMode = ShadowCastingMode.ShadowsOnly;
        pr.receiveShadows = false;
        lods[0].renderers = lods[0].renderers.Append(pr).ToArray();
        lg.SetLODs(lods);
    }

    public static GameObject LoadPrefab(string id) => AssetDatabase.LoadAssetAtPath<GameObject>($"{PrefabDir}/{id}.prefab");

    /// Crown-only far mesh of a tree (TR_X_0) for the chunk HLOD, or null.
    public static Mesh LoadHlodMesh(string id) =>
        AssetDatabase.LoadAllAssetsAtPath($"{HlodModelsDir}/{id}_HLOD.fbx").OfType<Mesh>().FirstOrDefault();

    /// Species index in city.json (Map/osm_pipeline.py TREE_SPECIES) -> prefab id.
    internal static readonly string[] SpeciesIds = { "TR_Sau_0", "TR_XaCu_0", "TR_Bang_0", "TR_HoaSua_0" };

    // ------------------------------------------------------------------ gallery
    [MenuItem("Hanoi/Trees/Build Tree Gallery")]
    public static void BuildGallery()
    {
        var manifest = LoadManifest();
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        HanoiLighting.Apply();
        var cam = Camera.main;
        cam.farClipPlane = 4000f; cam.nearClipPlane = 0.1f; cam.fieldOfView = 60f;

        var asphalt = HanoiSetup.LitMaterial("M_Asphalt", new Color(0.18f, 0.18f, 0.19f), 0.2f);
        var paving = HanoiSetup.LitMaterial("M_Sidewalk", new Color(0.50f, 0.48f, 0.45f), 0.15f);
        HanoiSetup.Box("Ground", new Vector3(0, -0.05f, 0), new Vector3(2000, 0.1f, 2000), asphalt);

        // street along X: south row of tube houses facing +Z, 4 m sidewalk, trees 1 m from the kerb
        const float road = 4f, walk = 4f, lotW = 4f, treeStep = 10f;
        const int houses = 24;
        float zHouse = -(road + walk), zTree = -(road + 1.0f);
        float rowLen = houses * lotW;
        var root = new GameObject("TreeGallery").transform;
        HanoiSetup.Box("Sidewalk", new Vector3(0, 0.07f, -(road + walk / 2)), new Vector3(rowLen + 20, 0.15f, walk), paving);

        var tubes = AssetDatabase.FindAssets("t:Prefab", new[] { "Assets/Hanoi/Library/Prefabs" })
            .Select(g => AssetDatabase.LoadAssetAtPath<GameObject>(AssetDatabase.GUIDToAssetPath(g)))
            .Select(go => go.GetComponent<BuildingVariant>())
            .Where(v => v != null && v.type == "tube" && string.IsNullOrEmpty(v.exposed) && v.depth <= 12.5f)
            .ToList();
        var rng = new System.Random(11);
        for (int i = 0; i < houses && tubes.Count > 0; i++)
        {
            var v = tubes[rng.Next(tubes.Count)];
            var h = (GameObject)PrefabUtility.InstantiatePrefab(v.gameObject, root);
            h.transform.SetPositionAndRotation(new Vector3(-rowLen / 2f + (i + 0.5f) * lotW, 0.15f, zHouse), Quaternion.identity);
        }

        int nTrees = Mathf.FloorToInt(rowLen / treeStep);
        for (int i = 0; i < nTrees; i++)
        {
            var t = manifest.trees[i % manifest.trees.Length];
            var go = (GameObject)PrefabUtility.InstantiatePrefab(LoadPrefab(t.id), root);
            go.name = $"{t.id}_{i:00}";
            go.transform.SetPositionAndRotation(new Vector3(-rowLen / 2f + (i + 0.5f) * treeStep, 0.15f, zTree),
                Quaternion.Euler(0, (float)rng.NextDouble() * 360f, 0));
        }

        // LOD comparison rows away from the street: per species LOD0 / LOD1 / LOD2 forced
        var lodRoot = new GameObject("LodCompare").transform;
        for (int s = 0; s < manifest.trees.Length; s++)
            for (int k = 0; k < 3; k++)
            {
                var go = (GameObject)PrefabUtility.InstantiatePrefab(LoadPrefab(manifest.trees[s].id), lodRoot);
                go.name = $"{manifest.trees[s].id}_forceLOD{k}";
                go.transform.position = new Vector3(400f + (s % 2) * 60f + k * 17f, 0f, 200f + (s / 2) * 60f);
            }
        EditorSceneManager.SaveScene(scene, GalleryScene);
        Debug.Log($"[Trees] gallery: {nTrees} trees along {houses} tube houses -> {GalleryScene}");
        CaptureShots();
    }

    [MenuItem("Hanoi/Trees/Capture Tree Shots")]
    public static void CaptureShots()
    {
        if (EditorSceneManager.GetActiveScene().path != GalleryScene)
            EditorSceneManager.OpenScene(GalleryScene);
        EditorSettings.asyncShaderCompilation = false;
        var cam = Camera.main;
        float x0 = -48f;

        HanoiSetup.Shot(cam, "t4_1_eye", new Vector3(x0 + 2f, 1.7f, 1.0f), new Vector3(x0 + 26f, 6.5f, -5.5f));
        HanoiSetup.Shot(cam, "t4_2_under", new Vector3(x0 + 13.5f, 1.6f, -3.2f), new Vector3(x0 + 15.5f, 11f, -5.5f));

        // back-lit: camera on the far side of a tree from the sun, looking at it (towards the sun)
        var sun = UnityEngine.Object.FindObjectsByType<Light>(FindObjectsSortMode.None).First(l => l.type == LightType.Directional);
        Vector3 toSun = -sun.transform.forward; toSun.y = 0; toSun.Normalize();
        var tree = new Vector3(x0 + 25f, 8f, -5f);
        HanoiSetup.Shot(cam, "t4_3_backlit", tree - toSun * 22f + Vector3.up * -5.5f, tree + Vector3.up * 1.5f);
        HanoiSetup.Shot(cam, "t4_4_frontlit", tree + toSun * 22f + Vector3.up * -5.5f, tree + Vector3.up * 1.5f);

        // from the street side (north): the houses would hide the trees from the south
        HanoiSetup.Shot(cam, "t4_5_drone80", new Vector3(x0 - 25f, 80f, 70f), new Vector3(0f, 0f, -5f));
        HanoiSetup.Shot(cam, "t4_6_far300", new Vector3(-260f, 200f, 300f), new Vector3(0f, 0f, -5f));

        // forced LODs side by side (screen size would otherwise pick the same LOD for all three)
        var groups = UnityEngine.Object.FindObjectsByType<LODGroup>(FindObjectsSortMode.None)
            .Where(g => g.name.Contains("_forceLOD")).ToArray();
        foreach (var g in groups)
            g.ForceLOD(int.Parse(g.name.Substring(g.name.Length - 1)));
        HanoiSetup.Shot(cam, "t4_7_lods_a", new Vector3(447f, 8f, 140f), new Vector3(447f, 7f, 200f));
        HanoiSetup.Shot(cam, "t4_8_lods_b", new Vector3(447f, 8f, 200f), new Vector3(447f, 7f, 260f));
        foreach (var g in groups)
            g.ForceLOD(-1);
        Debug.Log($"[Trees] shots in {HanoiSetup.ShotsDir}");
    }

    public static void RunBatch()
    {
        ImportTrees();
        BuildGallery();
    }

    // ------------------------------------------------------------------ city (Plan TP P2)
    [Serializable] class BenchPath { public BenchSeg[] segments; }
    [Serializable] class BenchSeg { public string name; public Vector3[] points; }

    /// Chunks within `radius` of `pos` open as real scenes (HLOD hidden), all others closed (HLOD shown).
    internal static void LoadAround(CityChunks reg, Vector3 pos, float radius)
    {
        foreach (var c in reg.chunks)
        {
            var b = c.boundsXZ;
            float dx = Mathf.Max(b.xMin - pos.x, 0f, pos.x - b.xMax), dz = Mathf.Max(b.yMin - pos.z, 0f, pos.z - b.yMax);
            bool near = Mathf.Sqrt(dx * dx + dz * dz) < radius;
            var sc = UnityEngine.SceneManagement.SceneManager.GetSceneByPath(c.scenePath);
            if (near && !sc.isLoaded) EditorSceneManager.OpenScene(c.scenePath, OpenSceneMode.Additive);
            if (!near && sc.isLoaded) EditorSceneManager.CloseScene(sc, true);
        }
        reg.SyncHlod();
    }

    [MenuItem("Hanoi/Trees/City Tree Shots")]
    public static void CityTreeShots()
    {
        EditorSettings.asyncShaderCompilation = false;
        EditorSceneManager.OpenScene("Assets/Hanoi/City/City_Main.unity", OpenSceneMode.Single);
        var reg = UnityEngine.Object.FindFirstObjectByType<CityChunks>();
        var cam = Camera.main;
        var p = JsonUtility.FromJson<BenchPath>(File.ReadAllText(Path.Combine(Application.streamingAssetsPath, "bench_path.json")))
            .segments[0].points;                                 // Pho Thuong Dinh centreline, eye height
        Vector3 Up(Vector3 v, float y) => new Vector3(v.x, y, v.z);

        LoadAround(reg, p[0], 380f);
        HanoiSetup.Shot(cam, "tp_1_street", p[0], Up(p[2], 4f));
        int m = p.Length / 2;
        LoadAround(reg, p[m], 380f);
        HanoiSetup.Shot(cam, "tp_2_street_mid", p[m], Up(p[m + 2], 5f));
        HanoiSetup.Shot(cam, "tp_3_street_back", p[m + 1], Up(p[m - 2], 5f));
        var side = Vector3.Cross((p[m + 1] - p[m]).normalized, Vector3.up);
        HanoiSetup.Shot(cam, "tp_4_drone80", p[m] - (p[m + 2] - p[m]).normalized * 60f + side * 25f + Vector3.up * 80f, Up(p[m + 1], 0f));
        HanoiSetup.Shot(cam, "tp_5_high300", p[m] - (p[m + 2] - p[m]).normalized * 250f + Vector3.up * 300f, Up(p[m], 0f));
        LoadAround(reg, new Vector3(1e5f, 0, 1e5f), 1f);         // nothing loaded: HLOD everywhere
        HanoiSetup.Shot(cam, "tp_6_high300_hlod", p[m] - (p[m + 2] - p[m]).normalized * 250f + Vector3.up * 300f, Up(p[m], 0f));
        HanoiSetup.Shot(cam, "tp_7_far_hlod", new Vector3(-900f, 650f, -1500f), new Vector3(0f, 0f, 0f));
        Debug.Log($"[Trees] city shots in {HanoiSetup.ShotsDir}");
    }

    /// Whole chain after a change of the tree layout (Map/osm_pipeline.py) or of the trees:
    /// GRD off, import trees, place the city (houses + trees), rebuild HLOD, shots.
    public static void RunCityBatch()
    {
        CityBenchmarkBuild.ConfigureRendering();
        ImportTrees();
        CityPlacer.Run();
        ChunkBuilder.Run();
        CityTreeShots();
    }
}
