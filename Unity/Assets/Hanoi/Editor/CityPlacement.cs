using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// CityPlacer bookkeeping between runs: which lot keys each chunk received last time, and the
/// lots whose building the user deleted by hand (tombstones, never placed again).
/// </summary>
public class CityPlacement : ScriptableObject
{
    [Serializable]
    public class ChunkKeys
    {
        public string chunk;
        public List<string> keys = new List<string>();
    }

    public List<ChunkKeys> placed = new List<ChunkKeys>();
    public List<string> tombstones = new List<string>();

    public ChunkKeys For(string chunk)
    {
        var c = placed.Find(p => p.chunk == chunk);
        if (c == null) { c = new ChunkKeys { chunk = chunk }; placed.Add(c); }
        return c;
    }
}
