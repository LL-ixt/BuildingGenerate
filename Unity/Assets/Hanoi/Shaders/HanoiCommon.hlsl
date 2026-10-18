#ifndef HANOI_COMMON_INCLUDED
#define HANOI_COMMON_INCLUDED

// Shared by Hanoi/Building, Hanoi/Window and Hanoi/Vehicle (define HANOI_VEHICLE before including).
// Per-house variation (paint colour, dirt) is derived from a hash of the object position, so it
// needs no per-instance data: works with the SRP Batcher and the GPU Resident Drawer.

#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
#include "Packages/com.unity.render-pipelines.core/ShaderLibrary/Color.hlsl"

CBUFFER_START(UnityPerMaterial)
    float4 _BaseMap_ST;
    half4  _BaseColor;
    half4  _Paint0, _Paint1, _Paint2, _Paint3, _Paint4, _Paint5;
    half   _PaintCount;
    half   _PaintJitter;
    half   _DirtMin, _DirtMax, _DirtyShare;
    half   _Smoothness;
    half   _Procedural;
    // trim-sheet regions (u0, v0, u1, v1), mirror of Blender/scripts/hanoi_trim.py
    float4 _RailRect, _GlassRect, _ShutterRect, _RollerRect, _InteriorRect;
    // trim sheet railing images (sub-rects of _RailRect) and which of them exist: bit 0 = balcony, bit 1 = cage
    float4 _RailBalRect, _RailCageRect;
    half   _RailTexMode;
    half   _InteriorGlow;
    // Hanoi/Window
    half4  _WallColorA, _WallColorB, _FloorColor, _CeilingColor, _LightColor;
    half   _RoomDepth, _InteriorBrightness, _NightLights, _CurtainChance;
    // Hanoi/Vehicle: paint colour of this material (one material per colour), the atlas cell it
    // replaces, alpha-clip threshold, lamp glow
    half4  _PaintColor;
    float4 _PaintRect;
    half   _Cutoff, _EmissionGain;
    // Hanoi/Vehicle (cars): paint where _DataMap.a says so (baked mask) instead of _PaintRect; normal map
    half   _PaintMaskMode, _BumpScale;
    // Hanoi/Vehicle (riders, _PaintMaskMode 2): second paint where _DataMap.b says so (helmet), no emission
    half4  _PaintColor2;
CBUFFER_END

TEXTURE2D(_BaseMap); SAMPLER(sampler_BaseMap);
TEXTURE2D(_DataMap); SAMPLER(sampler_DataMap);      // Hanoi/Vehicle: R roughness, G metallic, B emission, A paint mask (cars)
TEXTURE2D(_BumpMap); SAMPLER(sampler_BumpMap);      // Hanoi/Vehicle: tangent-space normal map (cars; flat for the bikes)

// ------------------------------------------------------------------ hashing / noise
float HanoiHash11(float p) { p = frac(p * 0.1031); p *= p + 33.33; p *= p + p; return frac(p); }
float HanoiHash12(float2 p) { float3 p3 = frac(p.xyx * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return frac((p3.x + p3.y) * p3.z); }
float HanoiHash13(float3 p3) { p3 = frac(p3 * 0.1031); p3 += dot(p3, p3.zyx + 31.32); return frac((p3.x + p3.y) * p3.z); }

float HanoiNoise(float2 p)
{
    float2 i = floor(p), f = frac(p);
    float2 u = f * f * (3.0 - 2.0 * f);
    float a = HanoiHash12(i), b = HanoiHash12(i + float2(1, 0));
    float c = HanoiHash12(i + float2(0, 1)), d = HanoiHash12(i + float2(1, 1));
    return lerp(lerp(a, b, u.x), lerp(c, d, u.x), u.y);
}

// Two stable random numbers per house, from the house's world position.
float2 HanoiSeedsFromPosition(float3 o)
{
    o = floor(o * 4.0 + 0.5);
    return float2(HanoiHash13(o + 0.37), HanoiHash13(o + 17.31));
}

float2 HanoiObjectSeeds() { return HanoiSeedsFromPosition(GetObjectToWorldMatrix()._m03_m13_m23); }

// Combined HLOD meshes (M4) store each house's world position in UV2.xyz with UV2.w = 2, so a
// merged house gets exactly the colour / dirt it has as a separate object. (Not w = 1: a mesh
// without UV2 reads the default (0, 0, 0, 1).)
float2 HanoiSeeds(float4 uv2)
{
    return uv2.w > 1.5 ? HanoiSeedsFromPosition(uv2.xyz) : HanoiObjectSeeds();
}

// ------------------------------------------------------------------ trim regions
bool HanoiInRect(float2 uv, float4 r) { return uv.x >= r.x && uv.y >= r.y && uv.x <= r.z && uv.y <= r.w; }
float2 HanoiRectST(float2 uv, float4 r) { return (uv - r.xy) / (r.zw - r.xy); }

// anti-aliased coverage of a line at c with half width w (fw = pixel footprint)
float HanoiLine(float x, float c, float w, float fw)
{
    w = max(w, fw * 0.35);
    return 1.0 - smoothstep(w, w + fw, abs(x - c));
}

// Procedural wrought-iron railing (stand-in for the RAIL region of the trim sheet).
float HanoiRailCoverage(float2 uv)
{
    float2 st = HanoiRectST(uv, _RailRect);
    float2 fw = fwidth(st);
    float c = max(HanoiLine(st.y, 0.025, 0.025, fw.y), HanoiLine(st.y, 0.975, 0.025, fw.y));
    c = max(c, HanoiLine(st.y, 0.14, 0.012, fw.y));
    c = max(c, HanoiLine(st.y, 0.38, 0.008, fw.y));
    c = max(c, HanoiLine(st.y, 0.62, 0.008, fw.y));
    float fx = frac(st.x * 10.0);
    c = max(c, HanoiLine(fx, 0.5, 0.07, fw.x * 10.0));
    float cx = floor(st.x * 10.0 + 0.5) / 10.0;
    float d = length(float2(st.x - cx, st.y - 0.5));
    float band = step(0.38, st.y) * step(st.y, 0.62);
    c = max(c, band * HanoiLine(d, 0.045, 0.007, fw.x));
    return saturate(c);
}

// Alpha clip shared by every pass.
#ifdef HANOI_VEHICLE
void HanoiClip(float2 uv)
{
    clip(SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv).a - _Cutoff);   // see-through wheel spokes
}
#else
void HanoiClip(float2 uv)
{
    float cov = HanoiRailCoverage(uv);   // evaluated outside the branch (uses derivatives)
    // railing image alpha, sampled outside the branches too
    float texA = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv).a;
    int mode = (int)(_RailTexMode + 0.5);
    bool texBal = (mode & 1) != 0 && HanoiInRect(uv, _RailBalRect);
    bool texCage = (mode & 2) != 0 && HanoiInRect(uv, _RailCageRect);
    if (texBal || texCage)
        clip(texA - 0.5);
    else if (_Procedural > 0.5 && HanoiInRect(uv, _RailRect))
        clip(cov - 0.5);
}
#endif

#endif
