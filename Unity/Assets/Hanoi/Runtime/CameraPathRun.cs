using UnityEngine;

/// <summary>
/// Slow fly-through for reviewing the city: moves this camera from `start` to `finish`
/// (two empty GameObjects you place in the scene) at a constant speed.
///
/// Use: add this component to the camera (or any object), drag the two objects into Start / Finish,
/// press Play. The camera takes its rotation from the two objects too: it blends from Start's
/// rotation to Finish's rotation along the way, or looks along the path when "Look Along Path" is on.
/// Needs the chunk streamer in the scene to show real houses (it is added automatically in play mode).
/// </summary>
public class CameraPathRun : MonoBehaviour
{
    public Transform start;
    public Transform finish;

    [Tooltip("Metres per second. 6 = walking pace, 15 = slow drive, 40+ = drone.")]
    public float speed = 8f;
    [Tooltip("Seconds to wait at the start before moving.")]
    public float startDelay = 1f;
    [Tooltip("Ease in / out at both ends.")]
    public bool smooth = true;
    [Tooltip("Face the direction of travel instead of blending the two objects' rotations.")]
    public bool lookAlongPath = false;
    public enum EndAction { Stop, Loop, PingPong }
    public EndAction atEnd = EndAction.Stop;
    public bool playOnStart = true;

    float t;             // 0..1 progress along the path
    float wait;
    int dir = 1;
    bool running;

    void Start()
    {
        if (start != null) Apply(0f);
        wait = startDelay;
        running = playOnStart;
    }

    public void Play() { running = true; }
    public void Restart() { t = 0f; dir = 1; wait = startDelay; running = true; Apply(0f); }

    void Update()
    {
        if (!running || start == null || finish == null) return;
        if (wait > 0f) { wait -= Time.deltaTime; return; }

        float length = Vector3.Distance(start.position, finish.position);
        if (length < 0.01f) return;
        t += dir * (speed / length) * Time.deltaTime;

        if (t >= 1f || t <= 0f)
        {
            t = Mathf.Clamp01(t);
            switch (atEnd)
            {
                case EndAction.Stop: running = false; break;
                case EndAction.Loop: t = 0f; wait = startDelay; break;
                case EndAction.PingPong: dir = -dir; wait = startDelay; break;
            }
        }
        Apply(t);
    }

    void Apply(float u)
    {
        if (start == null || finish == null) return;
        float k = smooth ? Mathf.SmoothStep(0f, 1f, u) : u;
        transform.position = Vector3.Lerp(start.position, finish.position, k);
        if (lookAlongPath)
        {
            var d = finish.position - start.position;
            if (d.sqrMagnitude > 1e-6f) transform.rotation = Quaternion.LookRotation(d.normalized);
        }
        else
        {
            transform.rotation = Quaternion.Slerp(start.rotation, finish.rotation, k);
        }
    }

    void OnDrawGizmos()
    {
        if (start == null || finish == null) return;
        Gizmos.color = Color.green; Gizmos.DrawSphere(start.position, 1.2f);
        Gizmos.color = Color.red; Gizmos.DrawSphere(finish.position, 1.2f);
        Gizmos.color = Color.yellow; Gizmos.DrawLine(start.position, finish.position);
        Gizmos.color = Color.cyan;
        Gizmos.DrawRay(start.position, start.forward * 6f);
        Gizmos.DrawRay(finish.position, finish.forward * 6f);
    }
}
