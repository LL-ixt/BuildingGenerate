using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// M5: keeps the chunk scenes around the camera loaded (real houses, LOD0 close up) and everything
/// else as HLOD. A chunk loads when its rectangle comes within LoadRadius of the camera and unloads
/// beyond UnloadRadius (hysteresis, so crossing a border does not flap). CityChunks hides / shows
/// the HLOD of a chunk by itself as the scene appears / disappears.
///
/// Plays in the Editor (chunk scenes are loaded straight from their asset path) and in builds
/// (scenes must be in Build Settings: CityPlacer adds them). Does nothing outside play mode.
/// </summary>
[RequireComponent(typeof(CityChunks))]
public class ChunkStreamer : MonoBehaviour
{
    const string MetroScene = "Assets/Hanoi/Metro/Metro.unity";     // = MetroBuilder.ScenePath

    public Transform target;                  // default: Camera.main
    public float loadRadius = 380f;
    public float unloadRadius = 460f;
    public int maxLoadsPerTick = 2;           // spread the cost of instantiating ~250 houses per chunk
    public float tick = 0.2f;

    public int LoadedCount { get; private set; }
    public int PendingCount { get; private set; }
    public int WantedCount { get; private set; }

    CityChunks reg;
    readonly HashSet<int> loading = new HashSet<int>();
    readonly Dictionary<int, AsyncOperation> unloading = new Dictionary<int, AsyncOperation>();
    float nextTick;

    // Added to the city main scene automatically when entering play mode (no scene edit needed).
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Bootstrap()
    {
        var r = FindAnyObjectByType<CityChunks>();
        if (r == null) return;
        if (r.GetComponent<ChunkStreamer>() == null) r.gameObject.AddComponent<ChunkStreamer>();
        // the elevated metro has its own scene (MetroBuilder), always loaded next to the city
        if (r.loadMetro && !SceneManager.GetSceneByPath(MetroScene).isLoaded)
        {
#if UNITY_EDITOR
            if (File.Exists(MetroScene))
                UnityEditor.SceneManagement.EditorSceneManager.LoadSceneAsyncInPlayMode(
                    MetroScene, new LoadSceneParameters(LoadSceneMode.Additive));
#else
            if (Application.CanStreamedLevelBeLoaded(Path.GetFileNameWithoutExtension(MetroScene)))
                SceneManager.LoadSceneAsync(Path.GetFileNameWithoutExtension(MetroScene), LoadSceneMode.Additive);
#endif
        }
        var cam = Camera.main;
        // free-fly test camera, unless a camera path is driving the camera
        if (cam != null && cam.GetComponent<FlyCamera>() == null && FindAnyObjectByType<CameraPathRun>() == null)
            cam.gameObject.AddComponent<FlyCamera>();
    }

    void Awake() => reg = GetComponent<CityChunks>();

    void Update()
    {
        if (!Application.isPlaying || reg == null || Time.unscaledTime < nextTick) return;
        nextTick = Time.unscaledTime + tick;
        if (target == null && Camera.main != null) target = Camera.main.transform;
        if (target == null) return;

        Vector2 p = new Vector2(target.position.x, target.position.z);
        int loaded = 0;
        candidates.Clear();
        for (int i = 0; i < reg.chunks.Count; i++)
        {
            var c = reg.chunks[i];
            float dx = Mathf.Max(c.boundsXZ.xMin - p.x, 0f, p.x - c.boundsXZ.xMax);
            float dz = Mathf.Max(c.boundsXZ.yMin - p.y, 0f, p.y - c.boundsXZ.yMax);
            // 3D: from high up the houses are at their last LOD anyway, which is what the HLOD shows
            float dy = Mathf.Max(target.position.y - 30f, 0f);
            float d = Mathf.Sqrt(dx * dx + dz * dz + dy * dy);
            bool isLoaded = reg.IsLoaded(i);
            if (isLoaded) loaded++;

            if (loading.Contains(i))
            {
                if (isLoaded) loading.Remove(i);
                continue;
            }
            if (unloading.TryGetValue(i, out var op))
            {
                if (op == null || op.isDone) unloading.Remove(i);
                continue;
            }
            if (!isLoaded && d < loadRadius)
                candidates.Add((d, i));
            else if (isLoaded && d > unloadRadius)
            {
                var sc = SceneManager.GetSceneByName(Path.GetFileNameWithoutExtension(c.scenePath));
                unloading[i] = SceneManager.UnloadSceneAsync(sc);
            }
        }
        // nearest chunks first: the ones the camera is in / looking at must not wait behind far ones
        candidates.Sort((a, b) => a.d.CompareTo(b.d));
        for (int k = 0; k < candidates.Count && k < maxLoadsPerTick; k++)
        {
            Load(reg.chunks[candidates[k].i].scenePath);
            loading.Add(candidates[k].i);
        }
        LoadedCount = loaded;
        PendingCount = loading.Count;
        WantedCount = loaded + candidates.Count + loading.Count;
    }

    readonly List<(float d, int i)> candidates = new List<(float d, int i)>();

    /// True when every chunk within loadRadius is loaded (or nothing is in flight).
    public bool Settled => PendingCount == 0 && candidates.Count == 0;

    static void Load(string path)
    {
#if UNITY_EDITOR
        UnityEditor.SceneManagement.EditorSceneManager.LoadSceneAsyncInPlayMode(
            path, new LoadSceneParameters(LoadSceneMode.Additive));
#else
        SceneManager.LoadSceneAsync(Path.GetFileNameWithoutExtension(path), LoadSceneMode.Additive);
#endif
    }

    void OnGUI()
    {
        if (!Application.isPlaying) return;
        GUI.Label(new Rect(10, 10, 420, 24), $"chunks loaded {LoadedCount}/{reg.chunks.Count}  loading {PendingCount}");
    }
}
