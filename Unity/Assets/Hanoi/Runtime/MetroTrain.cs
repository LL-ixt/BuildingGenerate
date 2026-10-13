using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// One metro train (TRAIN T2) running along a MetroLine: the head (front tip) moves by arc length on a
/// track `trackOffset` m right of the line direction; every car is placed from its two bogie points on
/// that track, so the cars follow curves (and slopes) like real bogies. Cars outside the line (past
/// either end) are hidden; a train that ran off one end comes back in from the other (the line ends
/// at the map edge). Station zones of the MetroLine: the train brakes to stop with its middle on the
/// zone centre and waits `dwell` s.
/// [ExecuteAlways]: outside play mode the train sits at `startS` (editing, screenshots).
/// Spawned by Editor/MetroTrains.cs from the Export/Metro/train.json consist.
/// </summary>
[ExecuteAlways]
public class MetroTrain : MonoBehaviour
{
    [Serializable]
    public class Car
    {
        public Transform t;
        public float offset;          // front tip of the train -> car centre (m along the track)
        public float bogieA, bogieB;  // bogie centres from the car centre in the TRAVEL direction (A ahead)
        public bool turned;           // car model faces backwards (the last end car)
    }

    public MetroLine line;
    public List<Car> cars = new List<Car>();
    public float length = 80f;                 // whole train, tip to tail
    [Tooltip("+ = right of the line direction (direction +1 runs on the right-hand track).")]
    public float trackOffset = 2f;
    [Tooltip("+1 = towards increasing arc length, -1 = back.")]
    public int direction = 1;
    [Tooltip("Head (front tip) arc length outside play mode / at play start.")]
    public float startS = 300f;
    public float maxSpeed = 15f, accel = 0.9f, decel = 1.1f, dwell = 20f;

    float head, speed, dwellLeft;
    bool started;

    public float Head => head;

    void OnEnable()
    {
        head = startS;
        started = false;
        Pose();
    }

    void OnValidate()
    {
        if (!Application.isPlaying) { head = startS; Pose(); }
    }

    void Update()
    {
        if (line == null) return;
        if (!Application.isPlaying) { head = startS; Pose(); return; }
        if (!started) { head = startS; started = true; }
        Step(Time.deltaTime);
        Pose();
    }

    /// Put the head at `s` and place the cars (screenshots, tools).
    public void PlaceAt(float s)
    {
        head = s;
        Pose();
    }

    /// Runs the train for `seconds` in `dt` steps (tests / tools; works outside play mode until the next
    /// Editor Update puts it back on startS).
    public void Simulate(float seconds, float dt = 0.05f)
    {
        for (float t = 0f; t < seconds; t += dt) Step(dt);
        Pose();
    }

    public float Speed => speed;

    void Step(float dt)
    {
        var path = line.Path;
        float L = path.Length;
        if (dwellLeft > 0f) { dwellLeft -= dt; return; }
        float vmax = maxSpeed;
        float stop = NextStop(L);
        if (!float.IsNaN(stop))
        {
            float d = (stop - head) * direction;
            if (d < 0.3f) { head = stop; speed = 0f; dwellLeft = dwell; return; }
            vmax = Mathf.Min(vmax, Mathf.Sqrt(2f * decel * d));
        }
        speed = Mathf.MoveTowards(speed, vmax, (speed < vmax ? accel : decel) * dt);
        head += direction * speed * dt;
        // off one end -> back in from the other (hidden while outside the line)
        if (direction > 0 && head - length > L + 20f) head = -20f;
        if (direction < 0 && head + length < -20f) head = L + 20f;
    }

    /// Head position that stops the train with its middle on the next station-zone centre ahead.
    float NextStop(float L)
    {
        float best = float.NaN;
        foreach (var z in line.stationZones)
        {
            float c = (z.s0 + z.s1) / 2f;
            float s = c + direction * length / 2f;
            if (s < 0f || s > L) continue;
            float ahead = (s - head) * direction;
            if (ahead > 0.3f && (float.IsNaN(best) || ahead < (best - head) * direction)) best = s;
        }
        return best;
    }

    void Pose()
    {
        if (line == null || cars == null) return;
        var path = line.Path;
        if (path == null) return;
        float L = path.Length;
        foreach (var c in cars)
        {
            if (c.t == null) continue;
            float sc = head - direction * c.offset;
            bool on = sc > -2f && sc < L + 2f;
            if (c.t.gameObject.activeSelf != on) c.t.gameObject.SetActive(on);
            if (!on) continue;
            Vector3 pa = path.Track(sc + direction * c.bogieA, trackOffset);
            Vector3 pb = path.Track(sc + direction * c.bogieB, trackOffset);
            Vector3 fwd = pa - pb;
            if (fwd.sqrMagnitude < 1e-6f) continue;
            Vector3 centre = pb + fwd * ((0f - c.bogieB) / (c.bogieA - c.bogieB));
            fwd.Normalize();
            c.t.SetPositionAndRotation(centre, Quaternion.LookRotation(c.turned ? -fwd : fwd, Vector3.up));
        }
    }
}
