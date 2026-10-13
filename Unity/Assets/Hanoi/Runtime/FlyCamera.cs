using UnityEngine;
using UnityEngine.InputSystem;

/// <summary>
/// Free-fly test camera (new Input System): hold right mouse to look, WASD move, Q/E down / up,
/// Shift = fast (x5), Ctrl = slow (x0.2), mouse wheel changes the base speed. Added to the main
/// camera automatically in play mode (see ChunkStreamer.Bootstrap).
/// </summary>
public class FlyCamera : MonoBehaviour
{
    public float speed = 40f;
    public float lookSpeed = 0.12f;
    float yaw, pitch;

    void Start()
    {
        var e = transform.eulerAngles;
        yaw = e.y; pitch = e.x > 180f ? e.x - 360f : e.x;
    }

    void Update()
    {
        var kb = Keyboard.current; var mouse = Mouse.current;
        if (kb == null || mouse == null) return;

        if (mouse.rightButton.isPressed)
        {
            var d = mouse.delta.ReadValue();
            yaw += d.x * lookSpeed;
            pitch = Mathf.Clamp(pitch - d.y * lookSpeed, -89f, 89f);
            transform.rotation = Quaternion.Euler(pitch, yaw, 0f);
        }

        float scroll = mouse.scroll.ReadValue().y;
        if (scroll != 0f) speed = Mathf.Clamp(speed * (scroll > 0 ? 1.2f : 1f / 1.2f), 2f, 600f);

        float s = speed * (kb.leftShiftKey.isPressed ? 5f : 1f) * (kb.leftCtrlKey.isPressed ? 0.2f : 1f);
        var move = Vector3.zero;
        if (kb.wKey.isPressed) move += transform.forward;
        if (kb.sKey.isPressed) move -= transform.forward;
        if (kb.dKey.isPressed) move += transform.right;
        if (kb.aKey.isPressed) move -= transform.right;
        if (kb.eKey.isPressed) move += Vector3.up;
        if (kb.qKey.isPressed) move -= Vector3.up;
        transform.position += move * s * Time.unscaledDeltaTime;
    }
}
