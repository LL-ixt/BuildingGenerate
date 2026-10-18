using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.SceneManagement;

/// <summary>
/// Lives in the city main scene: the list of chunk scenes written by CityPlacer (M3), with their
/// world bounds and the merged far-view mesh (HLOD) made by ChunkBuilder (M4).
///
/// A chunk's HLOD is shown only while its chunk scene is NOT loaded; the moment the scene is loaded
/// (by hand in the Editor, or later by the M5 streamer) the HLOD is hidden so the real houses
/// (LODGroups, LOD0 close up) are not covered by the box version.
/// </summary>
[ExecuteAlways]
public class CityChunks : MonoBehaviour
{
    [Serializable]
    public struct Chunk
    {
        public int ix, iy;
        public string scenePath;
        public Rect boundsXZ;        // world x / z
        public int buildings;
        public MeshRenderer hlod;    // merged far-view mesh in the main scene (ChunkBuilder, M4)
        public int hlodTris;
    }

    public float chunkSize = 200f;
    public List<Chunk> chunks = new List<Chunk>();
    [Tooltip("Load the elevated metro scene next to this city in play mode (main map only, not test areas).")]
    public bool loadMetro = true;

    string[] sceneNames;

    /// True when the chunk's scene is loaded (its houses exist).
    public bool IsLoaded(int i)
    {
        if (sceneNames == null || sceneNames.Length != chunks.Count)
        {
            sceneNames = new string[chunks.Count];
            for (int k = 0; k < chunks.Count; k++) sceneNames[k] = Path.GetFileNameWithoutExtension(chunks[k].scenePath);
        }
        var sc = SceneManager.GetSceneByName(sceneNames[i]);
        return sc.IsValid() && sc.isLoaded;
    }

    void Update() => SyncHlod();

    /// HLOD on = chunk scene not loaded.
    public void SyncHlod()
    {
        for (int i = 0; i < chunks.Count; i++)
        {
            var h = chunks[i].hlod;
            if (h == null) continue;
            bool want = !IsLoaded(i);
            if (h.enabled != want) h.enabled = want;
        }
    }
}
