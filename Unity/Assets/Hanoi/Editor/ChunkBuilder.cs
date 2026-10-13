using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

/// <summary>
/// M4: one far-view mesh (HLOD) per chunk, saved as an asset and shown in the main scene.
///  - Every building with a LODGroup contributes its LAST LOD (tube LOD2 box + roof, tower LOD1),
///    baked to world space. UV2 = (house world position, 2) so the shader derives the same paint /
///    dirt seed as for the separate house (HanoiSeeds in HanoiCommon.hlsl).
///  - The chunk's ground meshes (road, sidewalk, green, water) are merged as extra submeshes.
/// Run after CityPlacer (which rebuilds the main scene). Menu "Hanoi/City/Build HLOD" or batch:
/// -executeMethod ChunkBuilder.RunBatch
/// </summary>
public static class ChunkBuilder
{
    const string CityDir = "Assets/Hanoi/City";
    const string HlodDir = CityDir + "/HLOD";
    const string MainScene = CityDir + "/City_Main.unity";
    const string MatDir = "Assets/Hanoi/Materials";

    // submesh order = material order on the HLOD renderer
    static readonly string[] Layers = { "Kit", "Road", "Sidewalk", "Kerb", "Green", "Water", "Foliage" };
    static readonly string[] LayerMats = { "M_HanoiKit", "M_Asphalt", "M_Sidewalk", "M_Kerb", "M_Green", "M_Water", "M_FoliageBlob" };
    const int FoliageLayer = 6;

    /// Crown-only HLOD mesh of a tree prefab (HanoiTrees, ~80 tris) with its node matrix inside the model.
    static (Mesh mesh, Matrix4x4 node) TreeHlod(string id, Dictionary<string, (Mesh, Matrix4x4)> cache)
    {
        if (cache.TryGetValue(id, out var hit)) return hit;
        var mesh = HanoiTrees.LoadHlodMesh(id);
        var node = Matrix4x4.identity;
        var model = AssetDatabase.LoadAssetAtPath<GameObject>($"Assets/Hanoi/Trees/HLOD/{id}_HLOD.fbx");
        var mf = model != null ? model.GetComponentInChildren<MeshFilter>() : null;
        if (mf != null) node = model.transform.worldToLocalMatrix * mf.transform.localToWorldMatrix;
        return cache[id] = (mesh, node);
    }

    /// Prefab id (TR_Sau_0 ...) of a placed tree: from its prefab link, else from the name.
    static string TreeId(GameObject go)
    {
        var src = PrefabUtility.GetCorrespondingObjectFromSource(go);
        string n = src != null ? src.name : go.name;
        var parts = n.Split('_');
        return parts.Length >= 3 ? $"{parts[0]}_{parts[1]}_{parts[2].Split(' ')[0]}" : n;
    }

    class Builder
    {
        public readonly List<Vector3> pos = new List<Vector3>();
        public readonly List<Vector3> nrm = new List<Vector3>();
        public readonly List<Vector2> uv = new List<Vector2>();
        public readonly List<Vector2> uv1 = new List<Vector2>();
        public readonly List<Vector4> uv2 = new List<Vector4>();
        public readonly List<Color32> col = new List<Color32>();
        public readonly List<int>[] tris = Layers.Select(_ => new List<int>()).ToArray();

        /// upOnly: keep only the upward-facing triangles (sidewalk top; its skirt walls are too small to see from afar)
        public void Add(Mesh m, int subMesh, Matrix4x4 toWorld, Vector4 seedPos, int layer, Color32 defaultColor, bool upOnly = false)
        {
            if (upOnly)
            {
                var nn = m.normals; var ii = m.GetTriangles(subMesh);
                var keep = new List<int>();
                for (int i = 0; i < ii.Length; i += 3)
                    if (nn[ii[i]].y > 0.5f && nn[ii[i + 1]].y > 0.5f && nn[ii[i + 2]].y > 0.5f) keep.AddRange(new[] { ii[i], ii[i + 1], ii[i + 2] });
                if (keep.Count == 0) return;
                // compact: only referenced vertices
                var map = new Dictionary<int, int>(); var vs = new List<Vector3>(); var ns = new List<Vector3>(); var us = new List<Vector2>();
                var src = m.vertices; var uvs = m.uv;
                foreach (int k in keep) if (!map.ContainsKey(k)) { map[k] = vs.Count; vs.Add(src[k]); ns.Add(nn[k]); us.Add(uvs.Length > 0 ? uvs[k] : Vector2.zero); }
                var small = new Mesh();
                small.indexFormat = IndexFormat.UInt32;
                small.SetVertices(vs); small.SetNormals(ns); small.SetUVs(0, us);
                small.SetTriangles(keep.Select(k => map[k]).ToList(), 0);
                Add(small, 0, toWorld, seedPos, layer, defaultColor, false);
                Object.DestroyImmediate(small);
                return;
            }
            var v = m.vertices; var n = m.normals; var t = m.uv; var c = m.colors32;
            var f = m.uv2;                                                    // towers: FacadeUV (object metres from the wall centre)
            var nm = toWorld.inverse.transpose;                               // non-uniform scale safe
            float kv = toWorld.MultiplyVector(Vector3.up).magnitude;
            int b = pos.Count;
            for (int i = 0; i < v.Length; i++)
            {
                pos.Add(toWorld.MultiplyPoint3x4(v[i]));
                nrm.Add(n.Length > 0 ? nm.MultiplyVector(n[i]).normalized : Vector3.up);
                uv.Add(t.Length > 0 ? t[i] : Vector2.zero);
                if (f.Length > 0 && n.Length > 0)
                {   // baked to world metres like the shader does per object (HanoiForward.hlsl), the HLOD renderer is unscaled
                    var e = new Vector3(n[i].z, 0f, -n[i].x);
                    float ku = e.magnitude > 1e-3f ? toWorld.MultiplyVector(e.normalized).magnitude : 1f;
                    uv1.Add(new Vector2(f[i].x * ku, f[i].y * kv));
                }
                else uv1.Add(Vector2.zero);
                uv2.Add(seedPos);
                col.Add(c.Length > 0 ? c[i] : defaultColor);
            }
            // mirrored transforms flip the winding
            bool flip = toWorld.determinant < 0;
            var idx = m.GetTriangles(subMesh);
            var dst = tris[layer];
            for (int i = 0; i < idx.Length; i += 3)
            {
                dst.Add(b + idx[i]);
                dst.Add(b + (flip ? idx[i + 2] : idx[i + 1]));
                dst.Add(b + (flip ? idx[i + 1] : idx[i + 2]));
            }
        }

        public Mesh Build(string name, out bool[] used)
        {
            var m = new Mesh { name = name, indexFormat = IndexFormat.UInt32 };
            m.SetVertices(pos); m.SetNormals(nrm); m.SetUVs(0, uv); m.SetUVs(1, uv1); m.SetUVs(2, uv2); m.SetColors(col);
            var u = tris.Select(t => t.Count > 0).ToArray();
            used = u;
            var live = Enumerable.Range(0, Layers.Length).Where(i => u[i]).ToArray();
            m.subMeshCount = live.Length;
            for (int s = 0; s < live.Length; s++) m.SetTriangles(tris[live[s]], s, false);
            m.RecalculateBounds();
            m.RecalculateTangents();
            m.UploadMeshData(false);
            return m;
        }
    }

    static int LayerOf(string goName)
    {
        for (int i = 1; i < Layers.Length; i++)
            if (goName.EndsWith("_" + Layers[i])) return i;
        return -1;
    }

    [MenuItem("Hanoi/City/Build HLOD")]
    public static void Run()
    {
        var t0 = System.DateTime.Now;
        Directory.CreateDirectory(Path.Combine(HanoiSetup.ProjectDir, HlodDir));
        EditorSceneManager.OpenScene(MainScene, OpenSceneMode.Single);
        var chunks = Object.FindFirstObjectByType<CityChunks>().chunks.ToList();

        var results = new Dictionary<string, (string meshPath, bool[] used, int tris, int houses)>();
        long totalTris = 0; int totalHouses = 0, trees = 0, missingTrees = 0;
        foreach (var c in chunks)
        {
            var scene = EditorSceneManager.OpenScene(c.scenePath, OpenSceneMode.Single);
            // opening a scene unloads unreferenced assets: resolve the tree meshes again per chunk
            var treeCache = new Dictionary<string, (Mesh, Matrix4x4)>();
            var b = new Builder();
            int houses = 0;
            foreach (var root in scene.GetRootGameObjects())
            {
                if (root.name == "Buildings")
                {
                    foreach (var lg in root.GetComponentsInChildren<LODGroup>())
                    {
                        var lods = lg.GetLODs();
                        if (lods.Length == 0) continue;
                        var seedPos = (Vector4)lg.transform.position; seedPos.w = 2f;     // HLOD flag, see HanoiSeeds()
                        foreach (var r in lods[lods.Length - 1].renderers)
                        {
                            var mf = r != null ? r.GetComponent<MeshFilter>() : null;
                            if (mf == null || mf.sharedMesh == null) continue;
                            // the kit material only (far LODs never use glass)
                            for (int s = 0; s < mf.sharedMesh.subMeshCount; s++)
                                if (r.sharedMaterials.Length <= s || r.sharedMaterials[s] == null ||
                                    r.sharedMaterials[s].name == "M_HanoiKit")
                                    b.Add(mf.sharedMesh, s, r.transform.localToWorldMatrix, seedPos, 0, new Color32(255, 255, 255, 0));
                        }
                        houses++;
                    }
                }
                else if (root.name == "Trees" || root.name == "TreesManual")
                {
                    foreach (var lg in root.GetComponentsInChildren<LODGroup>())
                    {
                        var (crown, node) = TreeHlod(TreeId(lg.gameObject), treeCache);
                        if (crown == null) { missingTrees++; continue; }
                        b.Add(crown, 0, lg.transform.localToWorldMatrix * node, Vector4.zero, FoliageLayer, new Color32(80, 120, 40, 255));
                        trees++;
                    }
                }
                else if (root.name == "Ground")
                {
                    foreach (var mf in root.GetComponentsInChildren<MeshFilter>())
                    {
                        int layer = LayerOf(mf.gameObject.name);
                        if (layer < 0 || mf.sharedMesh == null) continue;
                        if (Layers[layer] == "Kerb") continue;                 // 27 cm wide: invisible from afar, ~0.4 M triangles
                        b.Add(mf.sharedMesh, 0, mf.transform.localToWorldMatrix, Vector4.zero, layer, new Color32(255, 255, 255, 0),
                              upOnly: Layers[layer] == "Sidewalk");
                    }
                }
            }
            string name = Path.GetFileNameWithoutExtension(c.scenePath) + "_HLOD";
            string meshPath = $"{HlodDir}/{name}.asset";
            var mesh = b.Build(name, out var used);
            AssetDatabase.DeleteAsset(meshPath);
            AssetDatabase.CreateAsset(mesh, meshPath);
            int tris = b.tris.Sum(t => t.Count) / 3;
            results[c.scenePath] = (meshPath, used, tris, houses);
            totalTris += tris; totalHouses += houses;
        }
        AssetDatabase.SaveAssets();

        // main scene: one renderer per chunk under "HLOD"
        var main = EditorSceneManager.OpenScene(MainScene, OpenSceneMode.Single);
        var reg = Object.FindFirstObjectByType<CityChunks>();
        var old = main.GetRootGameObjects().FirstOrDefault(g => g.name == "HLOD");
        if (old != null) Object.DestroyImmediate(old);
        var hRoot = new GameObject("HLOD").transform;
        var mats = LayerMats.Select(n => AssetDatabase.LoadAssetAtPath<Material>($"{MatDir}/{n}.mat")).ToArray();
        for (int i = 0; i < reg.chunks.Count; i++)
        {
            var c = reg.chunks[i];
            if (!results.TryGetValue(c.scenePath, out var res)) continue;
            var go = new GameObject(Path.GetFileName(res.meshPath).Replace(".asset", ""));
            go.transform.SetParent(hRoot, false);
            go.AddComponent<MeshFilter>().sharedMesh = AssetDatabase.LoadAssetAtPath<Mesh>(res.meshPath);
            var mr = go.AddComponent<MeshRenderer>();
            mr.sharedMaterials = Enumerable.Range(0, Layers.Length).Where(k => res.used[k]).Select(k => mats[k]).ToArray();
            mr.shadowCastingMode = ShadowCastingMode.On;
            GameObjectUtility.SetStaticEditorFlags(go, StaticEditorFlags.BatchingStatic);
            c.hlod = mr; c.hlodTris = res.tris;
            reg.chunks[i] = c;
        }
        EditorUtility.SetDirty(reg);
        EditorSceneManager.SaveScene(main);
        Debug.Log($"[HLOD] {trees} trees merged as crown blobs ({missingTrees} without an HLOD mesh)");
        Debug.Log($"[HLOD] {results.Count} chunks, {totalHouses} buildings merged, {totalTris:N0} triangles in total " +
                  $"(max {results.Values.Max(r => r.tris):N0} / chunk), {(System.DateTime.Now - t0).TotalSeconds:F0} s");
    }

    /// Same views twice: HLOD only, then the real chunk scenes with the HLOD hidden -> compare colours.
    public static void Shots()
    {
        EditorSettings.asyncShaderCompilation = false;
        EditorSceneManager.OpenScene(MainScene, OpenSceneMode.Single);
        var cam = Camera.main;
        var views = new (string name, Vector3 pos, Vector3 target)[]
        {
            ("mid_300m", new Vector3(500f, 140f, -260f), new Vector3(800f, 0f, 20f)),
            ("far_1500m", new Vector3(-1100f, 1100f, -1500f), Vector3.zero),
        };
        foreach (var v in views) HanoiSetup.Shot(cam, $"m4_{v.name}_hlod", v.pos, v.target);

        var reg = Object.FindFirstObjectByType<CityChunks>();
        foreach (var c in reg.chunks)
            EditorSceneManager.OpenScene(c.scenePath, OpenSceneMode.Additive);
        reg.SyncHlod();                      // HLOD of every loaded chunk off
        foreach (var v in views) HanoiSetup.Shot(cam, $"m4_{v.name}_houses", v.pos, v.target);
        Debug.Log("[HLOD] shots written");
    }

    /// Whole-map pictures of the main scene alone (HLOD of every chunk, i.e. what the far view will be):
    /// a top-down orthographic map and a few oblique views. Batch: -executeMethod ChunkBuilder.MapShots
    [MenuItem("Hanoi/City/Capture Map Overview")]
    public static void MapShots()
    {
        EditorSettings.asyncShaderCompilation = false;
        EditorSceneManager.OpenScene(MainScene, OpenSceneMode.Single);
        var cam = Camera.main;
        var reg = Object.FindFirstObjectByType<CityChunks>();
        float x0 = reg.chunks.Min(c => c.boundsXZ.xMin), x1 = reg.chunks.Max(c => c.boundsXZ.xMax);
        float z0 = reg.chunks.Min(c => c.boundsXZ.yMin), z1 = reg.chunks.Max(c => c.boundsXZ.yMax);
        var centre = new Vector3((x0 + x1) / 2f, 0f, (z0 + z1) / 2f);
        cam.farClipPlane = 6000f;
        // top-down, north up
        cam.orthographic = true;
        cam.orthographicSize = (z1 - z0) / 2f + 40f;
        HanoiSetup.ShotSized(cam, "map_topdown", centre + Vector3.up * 1500f, centre, 3200, (int)(3200 * (cam.orthographicSize * 2f) / (x1 - x0 + 80f)));
        cam.orthographic = false;
        cam.fieldOfView = 50f;
        HanoiSetup.Shot(cam, "map_oblique_south", centre + new Vector3(0f, 1000f, -1900f), centre + new Vector3(0f, 0f, 150f));
        HanoiSetup.Shot(cam, "map_oblique_west", centre + new Vector3(-2000f, 900f, -300f), centre);
        HanoiSetup.Shot(cam, "map_oblique_high", centre + new Vector3(700f, 700f, -1100f), centre + new Vector3(-150f, 0f, 100f));
        Debug.Log($"[Map] bounds x {x0:F0}..{x1:F0}, z {z0:F0}..{z1:F0} = {(x1 - x0) * (z1 - z0) / 1e6f:F1} km2 box, {reg.chunks.Count} chunks");
    }

    public static void RunBatch()
    {
        Run();
        Shots();
    }
}
