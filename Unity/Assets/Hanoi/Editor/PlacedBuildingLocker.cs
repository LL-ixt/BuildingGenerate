using UnityEditor;
using UnityEngine;

/// <summary>
/// Any manual change to a placed building (move / rotate / scale / edit its components) locks it,
/// so the next CityPlacer run keeps it as is.
/// </summary>
[InitializeOnLoad]
static class PlacedBuildingLocker
{
    static PlacedBuildingLocker()
    {
        Undo.postprocessModifications += OnModifications;
    }

    static UndoPropertyModification[] OnModifications(UndoPropertyModification[] mods)
    {
        foreach (var m in mods)
        {
            var target = m.currentValue?.target;
            GameObject go = target is Component c ? c.gameObject : target as GameObject;
            if (go == null) continue;
            var pb = go.GetComponentInParent<PlacedBuilding>();
            if (pb == null || pb.locked) continue;
            if (target == pb && m.currentValue.propertyPath == "locked") continue;   // user unlocking
            Undo.RecordObject(pb, "Lock placed building");
            pb.locked = true;
            EditorUtility.SetDirty(pb);
        }
        return mods;
    }
}
