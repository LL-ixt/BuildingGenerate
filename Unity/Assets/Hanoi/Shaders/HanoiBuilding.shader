// Shared opaque shader for every Hanoi kit building (one material for the whole city).
//  - Base colour from mesh vertex colour (RGB) x optional trim sheet _BaseMap.
//  - Vertex alpha = paint mask: those surfaces get a per-house colour picked from the palette
//    by a hash of the object position (no per-instance data -> SRP Batcher / GPU Resident Drawer).
//  - Procedural world-space dirt (streaks, blotches, ground grime), amount varies per house.
//  - Until the trim texture exists, railings / louvres / roller shutters / far windows are
//    drawn procedurally from their trim-sheet UV regions (_Procedural = 1).
//  - Tower / big-building walls (UV0 in a GRID_* region) get procedural windows sized in world
//    metres from FacadeUV (HanoiForward.hlsl), whatever the building's stretch.
Shader "Hanoi/Building"
{
    Properties
    {
        [MainTexture] _BaseMap ("Trim Albedo (optional)", 2D) = "white" {}
        [MainColor] _BaseColor ("Base Color", Color) = (1, 1, 1, 1)
        _Smoothness ("Smoothness", Range(0, 1)) = 0.15

        [Header(Per house paint palette)]
        _PaintCount ("Palette Size", Range(1, 6)) = 6
        _PaintJitter ("Brightness Jitter", Range(0, 0.5)) = 0.15
        _Paint0 ("Paint 0", Color) = (0.93, 0.78, 0.42, 1)
        _Paint1 ("Paint 1", Color) = (0.92, 0.72, 0.66, 1)
        _Paint2 ("Paint 2", Color) = (0.64, 0.80, 0.76, 1)
        _Paint3 ("Paint 3", Color) = (0.68, 0.70, 0.60, 1)
        _Paint4 ("Paint 4", Color) = (0.94, 0.92, 0.85, 1)
        _Paint5 ("Paint 5", Color) = (0.86, 0.60, 0.38, 1)

        [Header(Dirt)]
        _DirtMin ("Dirt Min", Range(0, 1)) = 0.25
        _DirtMax ("Dirt Max", Range(0, 1)) = 0.85
        _DirtyShare ("Share Of Dirty Houses", Range(0, 1)) = 0.15

        [Header(Procedural trim stand in)]
        [Toggle] _Procedural ("Procedural Details", Float) = 1
        _RailRect ("Rail UV Rect", Vector) = (0.00146, 0.00146, 0.24854, 0.24854)
        _GlassRect ("Window UV Rect", Vector) = (0.75146, 0.62646, 0.99854, 0.87354)
        _ShutterRect ("Shutter UV Rect", Vector) = (0.50146, 0.62646, 0.74854, 0.87354)
        _RollerRect ("Roller UV Rect", Vector) = (0.00146, 0.25146, 0.24854, 0.49854)
        _InteriorRect ("Open Shop Interior UV Rect", Vector) = (0.25146, 0.50146, 0.37354, 0.62354)
        _InteriorGlow ("Interior Glow", Range(0, 2)) = 0.6
        _RailBalRect ("Balcony Rail Image Rect", Vector) = (0.00146, 0.15587, 0.24854, 0.24854)
        _RailCageRect ("Cage Rail Image Rect", Vector) = (0.00146, 0.00146, 0.24854, 0.15587)
        _RailTexMode ("Rail Image Bits (1 balcony, 2 cage)", Float) = 0
        _NightLights ("Lit Windows Fraction", Range(0, 1)) = 0
        [HDR] _LightColor ("Room Light Color", Color) = (1.0, 0.8, 0.55, 1)
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" "UniversalMaterialType" = "Lit" "Queue" = "AlphaTest" }
        LOD 300

        HLSLINCLUDE
        #include "HanoiCommon.hlsl"

        half3 HanoiPaint(float s)
        {
            float n = max(_PaintCount, 1.0);
            int i = (int)min(floor(s * n), n - 1.0);
            half3 c = _Paint0.rgb;
            c = i == 1 ? _Paint1.rgb : c;
            c = i == 2 ? _Paint2.rgb : c;
            c = i == 3 ? _Paint3.rgb : c;
            c = i == 4 ? _Paint4.rgb : c;
            c = i == 5 ? _Paint5.rgb : c;
            return c * (1.0 + (HanoiHash11(s * 91.7) - 0.5) * _PaintJitter);
        }

        half HanoiDirt(float3 posWS, float3 posOS, half3 nWS, float seed)
        {
            float2 p = abs(nWS.x) > abs(nWS.z) ? posWS.zy : posWS.xy;
            float streak = HanoiNoise(float2(p.x * 3.0 + seed * 91.0, p.y * 0.35));
            streak *= HanoiNoise(float2(p.x * 1.1 - seed * 13.0, p.y * 0.12 + 5.0)) * 1.6;
            float blot = HanoiNoise(p * 0.45 + seed * 37.0) * 0.6 + HanoiNoise(p * 1.7) * 0.4;
            float ground = saturate(1.0 - posOS.y / 1.2);
            float up = saturate(nWS.y);
            float d = saturate(streak - 0.25) * 0.9 + saturate(blot - 0.45) * 1.4 + ground * 0.5 + up * blot * 0.6;
            return saturate(d);
        }
        ENDHLSL

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }
            Cull Back
            ZWrite On

            HLSLPROGRAM
            #pragma target 2.0
            #pragma vertex HanoiVertex
            #pragma fragment HanoiFragment

            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE _MAIN_LIGHT_SHADOWS_SCREEN
            #pragma multi_compile _ _ADDITIONAL_LIGHTS
            #pragma multi_compile _ EVALUATE_SH_MIXED EVALUATE_SH_VERTEX
            #pragma multi_compile_fragment _ _ADDITIONAL_LIGHT_SHADOWS
            #pragma multi_compile_fragment _ _REFLECTION_PROBE_BLENDING
            #pragma multi_compile_fragment _ _REFLECTION_PROBE_BOX_PROJECTION
            #pragma multi_compile_fragment _ _SHADOWS_SOFT _SHADOWS_SOFT_LOW _SHADOWS_SOFT_MEDIUM _SHADOWS_SOFT_HIGH
            #pragma multi_compile_fragment _ _SCREEN_SPACE_OCCLUSION
            #pragma multi_compile_fragment _ _LIGHT_COOKIES
            #pragma multi_compile _ _LIGHT_LAYERS
            #pragma multi_compile _ _CLUSTER_LIGHT_LOOP
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/RenderingLayers.hlsl"

            #pragma multi_compile _ SHADOWS_SHADOWMASK
            #pragma multi_compile _ LOD_FADE_CROSSFADE
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Fog.hlsl"
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/ProbeVolumeVariants.hlsl"

            #pragma multi_compile_instancing
            #pragma instancing_options renderinglayer
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DOTS.hlsl"

            #include "HanoiForward.hlsl"

            // ---- tower facade grid. Styles mirror hanoi_trim.GRID_STYLES (UV0 x in 7/8..1, y < 1/8):
            // 0 RES_LOGGIA, 1 STRIPE, 2 PUNCHED, 3 CURTAIN; cell = (bay width, floor height) in metres.
            static const float2 HanoiGridCell[4] = { float2(3.6, 3.2), float2(2.0, 3.4), float2(3.3, 3.0), float2(1.5, 3.8) };

            // coverage of [a, b] by a pixel of width w centred on x (cell units); fades to the mean far away
            float HanoiBox(float x, float a, float b, float w)
            {
                w = max(w, 1e-4);
                float c = saturate((min(x + 0.5 * w, b) - max(x - 0.5 * w, a)) / w);
                return lerp(c, b - a, saturate(w * 2.0 - 0.5));
            }
            float HanoiRectCov(float2 st, float4 r, float2 w) { return HanoiBox(st.x, r.x, r.z, w.x) * HanoiBox(st.y, r.y, r.w, w.y); }

            // Whole bays / floors fitted into the wall, so windows are never cut at corners or the roof.
            // Returns the glass coverage (for smoothness, dirt, night lights).
            half HanoiFacadeGrid(float2 uv, float2 c, float2 fw, float seed, inout half3 albedo)
            {
                int style = (int)clamp(floor((uv.x - 0.875) * 32.0), 0.0, 3.0);
                float2 st = frac(c), id = floor(c);
                float r = HanoiHash13(float3(id, seed * 97.0 + style * 13.0));
                half3 wall = albedo;
                // glass: dark, some cells with light curtains behind
                half3 glass = lerp(half3(0.025, 0.03, 0.038), half3(0.11, 0.10, 0.085), r * r);
                half3 col = wall;
                half g = 0;
                if (style == 2)
                {   // old housing block: punched windows with frame + sill, AC units, floor band
                    col = lerp(col, wall * 0.86, HanoiRectCov(st, float4(0.0, 0.0, 1.0, 0.04), fw));
                    col = lerp(col, wall * 1.1, HanoiRectCov(st, float4(0.23, 0.27, 0.77, 0.32), fw));
                    col = lerp(col, half3(0.78, 0.79, 0.78), HanoiRectCov(st, float4(0.27, 0.32, 0.73, 0.80), fw));
                    g = HanoiRectCov(st, float4(0.305, 0.355, 0.695, 0.765), fw);
                    col = lerp(col, glass, g);
                    col = lerp(col, half3(0.72, 0.73, 0.72), HanoiRectCov(st, float4(0.485, 0.355, 0.515, 0.765), fw));
                    if (frac(r * 7.31) < 0.22)      // air conditioner next to the window
                        col = lerp(col, half3(0.82, 0.83, 0.82), HanoiRectCov(st, float4(0.76, 0.36, 0.93, 0.52), fw));
                }
                else if (style == 0)
                {   // residential tower: recessed loggias behind a parapet
                    col = lerp(col, wall * 0.42, HanoiRectCov(st, float4(0.07, 0.36, 0.93, 0.86), fw));
                    g = HanoiRectCov(st, float4(0.16, 0.38, 0.84, 0.84), fw);
                    col = lerp(col, glass, g);
                    col = lerp(col, wall * 1.06, HanoiRectCov(st, float4(0.07, 0.33, 0.93, 0.36), fw));
                }
                else if (style == 1)
                {   // vertical light stripes between dark glass, thin spandrels
                    g = HanoiRectCov(st, float4(0.34, 0.13, 1.0, 1.0), fw);
                    col = lerp(col, glass * 0.8, g);
                    col = lerp(col, wall * 0.62, HanoiRectCov(st, float4(0.34, 0.0, 1.0, 0.13), fw));
                }
                else
                {   // glass curtain wall tinted by the vertex colour, mullions + opaque spandrels
                    half3 cg = albedo * 0.32 + glass * 0.4;
                    g = HanoiRectCov(st, float4(0.04, 0.2, 0.96, 0.98), fw);
                    col = lerp(albedo * 0.55, cg, g);
                    col = lerp(col, albedo * 0.22, HanoiRectCov(st, float4(0.04, 0.02, 0.96, 0.18), fw));
                }
                albedo = col;
                return g;
            }

            void HanoiSurface(HanoiVaryings input, half3 viewDirWS, inout SurfaceData s)
            {
                float2 uv = input.uv;
                half3 albedo = s.albedo * SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, TRANSFORM_TEX(uv, _BaseMap)).rgb * _BaseColor.rgb;
                half paint = input.color.a;
                albedo = lerp(albedo, albedo * HanoiPaint(input.seed.x), paint);

                // derivatives outside branches
                float2 stS = HanoiRectST(uv, _ShutterRect); float2 fwS = fwidth(stS);
                float2 stG = HanoiRectST(uv, _GlassRect);
                float2 stR = HanoiRectST(uv, _RollerRect);  float2 fwR = fwidth(stR);
                int gStyle = (int)clamp(floor((uv.x - 0.875) * 32.0), 0.0, 3.0);
                float2 gHalf = max(input.facade.zw, 1e-3);
                float2 gN = max(1.0, round(2.0 * gHalf / HanoiGridCell[gStyle]));
                float2 gC = (input.facade.xy + gHalf) / (2.0 * gHalf) * gN;
                float2 gFw = fwidth(gC);

                half glassCov = 0;
                if (uv.x > 0.874 && uv.y < 0.126 && input.facade.z > 0.25)
                {
                    glassCov = HanoiFacadeGrid(uv, gC, gFw, input.seed.x, albedo);
                    s.smoothness = lerp(s.smoothness, 0.9, glassCov);
                    float lit = HanoiHash13(float3(floor(gC), input.seed.x * 53.0));
                    s.emission += lit < _NightLights ? _LightColor.rgb * 0.6 * glassCov : 0;
                    paint = 0;
                }

                if (_Procedural > 0.5)
                {
                    if (HanoiInRect(uv, _ShutterRect))
                    {
                        bool frame = stS.x < 0.07 || stS.x > 0.93 || stS.y < 0.06 || stS.y > 0.94 ||
                                     abs(stS.x - 0.5) < 0.03 || abs(stS.y - 0.5) < 0.025;
                        float f = frac(stS.y * 18.0);
                        float shade = f < 0.14 ? 0.3 : 0.7 + 0.45 * f;
                        shade = lerp(shade, 0.78, saturate(fwS.y * 27.0));
                        albedo *= frame ? 1.0 : shade;
                    }
                    else if (HanoiInRect(uv, _GlassRect))
                    {
                        bool frame = stG.x < 0.08 || stG.x > 0.92 || stG.y < 0.07 || stG.y > 0.93 ||
                                     abs(stG.x - 0.5) < 0.025 || abs(stG.y - 0.69) < 0.02;
                        if (!frame)
                        {
                            float room = HanoiHash13(float3(floor(input.positionOS.x / 2.0), floor(input.positionOS.y / 3.3), input.seed.x * 131.0));
                            albedo = lerp(half3(0.02, 0.025, 0.03), half3(0.09, 0.075, 0.06), room);
                            s.smoothness = 0.9;
                            s.emission = HanoiHash11(room * 71.3) < _NightLights ? _LightColor.rgb * 0.6 : 0;
                            paint = 0;
                        }
                    }
                    else if (HanoiInRect(uv, _RollerRect))
                    {
                        float f = frac(stR.y * 30.0);
                        float shade = f < 0.08 ? 0.35 : 0.65 + 0.35 * sin(PI * f);
                        albedo *= lerp(shade, 0.75, saturate(fwR.y * 45.0));
                        s.metallic = 0.4;
                        s.smoothness = 0.35;
                    }
                }

                // open ground floor: the recess reads as a bright lit room, not a dark hole
                if (HanoiInRect(uv, _InteriorRect))
                {
                    s.emission += albedo * _InteriorGlow;
                    paint = 0;
                }

                // most houses are clean: only the top _DirtyShare of the per-house seed gets the full dirt
                half dirtyHouse = smoothstep(1.0 - _DirtyShare - 0.12, 1.0 - _DirtyShare + 0.04, input.seed.y);
                half dirtAmt = lerp(_DirtMin, _DirtMax, dirtyHouse);
                half d = HanoiDirt(input.positionWS, input.positionOS, input.normalWS, input.seed.x) * dirtAmt * lerp(0.5, 1.0, paint) * (1.0 - 0.7 * glassCov);
                s.albedo = lerp(albedo, albedo * half3(0.50, 0.47, 0.40), d);
                s.smoothness *= 1.0 - 0.5 * d;
            }
            ENDHLSL
        }

        Pass
        {
            Name "ShadowCaster"
            Tags { "LightMode" = "ShadowCaster" }
            ZWrite On
            ZTest LEqual
            ColorMask 0
            Cull Back

            HLSLPROGRAM
            #pragma target 2.0
            #pragma vertex HanoiShadowVertex
            #pragma fragment HanoiShadowFragment
            #pragma multi_compile_instancing
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DOTS.hlsl"
            #pragma multi_compile _ LOD_FADE_CROSSFADE
            #pragma multi_compile_vertex _ _CASTING_PUNCTUAL_LIGHT_SHADOW
            #define HANOI_SHADOW_PASS
            #include "HanoiPasses.hlsl"
            ENDHLSL
        }

        Pass
        {
            Name "DepthOnly"
            Tags { "LightMode" = "DepthOnly" }
            ZWrite On
            ColorMask R
            Cull Back

            HLSLPROGRAM
            #pragma target 2.0
            #pragma vertex HanoiDepthVertex
            #pragma fragment HanoiDepthOnlyFragment
            #pragma multi_compile _ LOD_FADE_CROSSFADE
            #pragma multi_compile_instancing
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DOTS.hlsl"
            #include "HanoiPasses.hlsl"
            ENDHLSL
        }

        Pass
        {
            Name "DepthNormals"
            Tags { "LightMode" = "DepthNormals" }
            ZWrite On
            Cull Back

            HLSLPROGRAM
            #pragma target 2.0
            #pragma vertex HanoiDepthVertex
            #pragma fragment HanoiDepthNormalsFragment
            #pragma multi_compile _ LOD_FADE_CROSSFADE
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/RenderingLayers.hlsl"
            #pragma multi_compile_instancing
            #include_with_pragmas "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DOTS.hlsl"
            #include "HanoiPasses.hlsl"
            ENDHLSL
        }
    }
    FallBack "Hidden/Universal Render Pipeline/FallbackError"
}
