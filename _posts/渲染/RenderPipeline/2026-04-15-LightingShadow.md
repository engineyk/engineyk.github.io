---
layout:     post
title:      LightingShadow
subtitle:   LightingShadow
date:       2026-04-15
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - GPU
    - 渲染
---

# Lighting & Shadow Rendering


---

## 1. Overview

```
Light & Shadow Pipeline:

┌─────────────────────────────────────────────────────────┐
│                    Light Sources                        │
│  Directional │ Point │ Spot │ Area │ Emissive │ IBL     │
└──────┬──────────┬───────┬──────┬───────┬────────┬───────┘
       │          │       │      │       │        │
       ▼          ▼       ▼      ▼       ▼        ▼
┌─────────────────────────────────────────────────────────┐
│                  Direct Lighting                        │
│  BRDF (Diffuse + Specular) → Shadow → Attenuation       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│               Indirect Lighting (GI)                    │
│  Lightmap │ Light Probe │ Reflection Probe │ SSGI │ RT  │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                Shadow Techniques                        │
│  ShadowMap │ CSM │ VSM │ PCSS │ SDF │ RayTrace          │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Post-Processing Effects                    │
│  AO (SSAO/GTAO/HBAO) │ Bloom │ Volumetric │ LensFlare   │
└─────────────────────────────────────────────────────────┘
```

### 1.1 Core Challenges

| Challenge         | Description                              | Key Metric         |
| ----------------- | ---------------------------------------- | ------------------ |
| Physical Accuracy | Energy conservation, Fresnel, microfacet | BRDF correctness   |
| Shadow Quality    | Aliasing, peter-panning, light leaking   | Resolution vs cost |
| GI Approximation  | Indirect bounce, color bleeding, AO      | Visual fidelity    |
| Performance       | Per-light cost, shadow pass count        | ms per frame       |
| Mobile Bandwidth  | TBR tile memory, texture fetch           | bytes per pixel    |

---

## 2. Lighting Models

### 2.1 Rendering Equation

```
Lo(p, ωo) = Le(p, ωo) + ∫Ω fr(p, ωi, ωo) · Li(p, ωi) · (n · ωi) dωi

Where:
  Lo = outgoing radiance          出射辐射度
  Le = emitted radiance           自发光辐射度
  fr = BRDF                       双向反射分布函数
  Li = incoming radiance          入射辐射度
  n · ωi = cos(θ)                 Lambert余弦项
  Ω = hemisphere                  半球积分域
```

### 2.2 BRDF Decomposition

```
fr(p, ωi, ωo) = kd · f_diffuse + ks · f_specular

┌────────────────────────────────────────────────────┐
│              Cook-Torrance BRDF                    │
│                                                    │
│                  D(h) · F(v,h) · G(l,v,h)          │
│  f_specular = ─────────────────────────────        │
│                    4 · (n·l) · (n·v)               │
│                                                    │
│  D = Normal Distribution Function (NDF)            │
│  F = Fresnel Term                                  │
│  G = Geometry / Visibility Term                    │
│                                                    │
│  f_diffuse = Lambert / Disney Diffuse / Oren-Nayar │
└────────────────────────────────────────────────────┘
```

### 2.3 NDF (Normal Distribution Function)

法线分布函数 — 描述微表面法线朝向半程向量 h 的概率分布

```hlsl
// GGX / Trowbridge-Reitz (industry standard)
// 长尾高光，视觉效果最好，UE/Unity 默认选择
float D_GGX(float NdotH, float roughness)
{
    float a  = roughness * roughness;          // remap to perceptual roughness
    float a2 = a * a;
    float d  = (NdotH * NdotH) * (a2 - 1.0) + 1.0;
    return a2 / (PI * d * d);
}

// Beckmann (older, used in some offline renderers)
float D_Beckmann(float NdotH, float roughness)
{
    float a2 = roughness * roughness;
    float r  = 1.0 / (a2 * pow(NdotH, 4.0));
    float e  = exp(-(1.0 - NdotH * NdotH) / (a2 * NdotH * NdotH));
    return r * e;
}

// Blinn-Phong (legacy, not physically based)
float D_BlinnPhong(float NdotH, float shininess)
{
    return (shininess + 2.0) / (2.0 * PI) * pow(NdotH, shininess);
}
```

**对比：**

| NDF         | 高光形状   | 能量守恒 | 性能 | 使用场景 |
| ----------- | ---------- | -------- | ---- | -------- |
| GGX         | 长尾，自然 | ✅        | 中   | PBR 标准 |
| Beckmann    | 短尾，锐利 | ✅        | 中   | 离线渲染 |
| Blinn-Phong | 无物理意义 | ❌        | 快   | Legacy   |

### 2.4 Fresnel Term

菲涅尔项 — 描述不同观察角度下反射率的变化

```hlsl
// Schlick Approximation (standard in real-time)
// F0 = reflectance at normal incidence (0°)
// 非金属 F0 ≈ 0.04, 金属 F0 = albedo
float3 F_Schlick(float VdotH, float3 F0)
{
    return F0 + (1.0 - F0) * pow(1.0 - VdotH, 5.0);
}

// Schlick with roughness (for IBL / environment specular)
float3 F_SchlickRoughness(float NdotV, float3 F0, float roughness)
{
    float3 maxReflect = max(float3(1.0 - roughness), F0);
    return F0 + (maxReflect - F0) * pow(1.0 - NdotV, 5.0);
}

// Exact Fresnel (for reference / offline)
// Uses full Fresnel equations with complex IOR
// Rarely used in real-time
```

**关键理解：**

```
观察角度 vs 反射率：

反射率
  1.0 ┤                                    ╱
      │                                  ╱
      │                               ╱
      │                           ╱
  F0  ┤─────────────────────╱
      │
  0.0 ┤
      └──────────────────────────────────
      0°(正对)                    90°(掠射)
                  观察角度

掠射角（Grazing Angle）时所有材质反射率趋近 1.0
这就是为什么水面远处看起来像镜子，近处能看到水底
```

### 2.5 Geometry / Visibility Term

几何遮蔽项 — 描述微表面自遮挡（Shadowing & Masking）

```hlsl
// Smith GGX (separable form)
float G_SmithGGX(float NdotV, float NdotL, float roughness)
{
    float r = roughness + 1.0;
    float k = (r * r) / 8.0;  // direct lighting remapping
    // For IBL: k = roughness^2 / 2

    float ggx1 = NdotV / (NdotV * (1.0 - k) + k);  // G1(v)
    float ggx2 = NdotL / (NdotL * (1.0 - k) + k);  // G1(l)
    return ggx1 * ggx2;
}

// Smith-GGX Correlated (more accurate, used in Filament/UE5)
// Accounts for correlation between masking and shadowing
float V_SmithGGXCorrelated(float NdotV, float NdotL, float roughness)
{
    float a2 = roughness * roughness;
    float GGXV = NdotL * sqrt(NdotV * NdotV * (1.0 - a2) + a2);
    float GGXL = NdotV * sqrt(NdotL * NdotL * (1.0 - a2) + a2);
    return 0.5 / (GGXV + GGXL);
    // Note: this is V = G / (4 * NdotV * NdotL), denominator already included
}

// Mobile approximation (Filament)
float V_SmithGGXCorrelatedFast(float NdotV, float NdotL, float roughness)
{
    float a = roughness;
    float GGXV = NdotL * (NdotV * (1.0 - a) + a);
    float GGXL = NdotV * (NdotL * (1.0 - a) + a);
    return 0.5 / (GGXV + GGXL);
}
```

### 2.6 Diffuse Models

```hlsl
// Lambert (simplest, most common)
float3 Fd_Lambert(float3 albedo)
{
    return albedo / PI;
}

// Disney Diffuse (Burley 2012)
// Adds roughness-dependent retro-reflection at grazing angles
float3 Fd_Burley(float NdotV, float NdotL, float LdotH, float roughness, float3 albedo)
{
    float f90 = 0.5 + 2.0 * roughness * LdotH * LdotH;
    float lightScatter = 1.0 + (f90 - 1.0) * pow(1.0 - NdotL, 5.0);
    float viewScatter  = 1.0 + (f90 - 1.0) * pow(1.0 - NdotV, 5.0);
    return albedo / PI * lightScatter * viewScatter;
}
```

### 2.7 Complete PBR Shader

```hlsl
half4 PBR_DirectLighting(Surface surface, Light light)
{
    float3 N = surface.normal;
    float3 V = surface.viewDir;
    float3 L = light.direction;
    float3 H = normalize(V + L);

    float NdotL = saturate(dot(N, L));
    float NdotV = max(dot(N, V), 1e-4);  // avoid division by zero
    float NdotH = saturate(dot(N, H));
    float VdotH = saturate(dot(V, H));

    // Specular BRDF
    float  D = D_GGX(NdotH, surface.roughness);
    float3 F = F_Schlick(VdotH, surface.F0);
    float  G = V_SmithGGXCorrelated(NdotV, NdotL, surface.roughness);
    // Note: using V term (G already divided by denominator)
    float3 specular = D * F * G;

    // Diffuse BRDF
    float3 kd = (1.0 - F) * (1.0 - surface.metallic);
    float3 diffuse = kd * Fd_Lambert(surface.albedo);

    // Final
    return half4((diffuse + specular) * light.color * light.attenuation * NdotL, 1.0);
}
```

**能量守恒关键点：**

```
入射能量 = 反射能量 + 折射能量 + 吸收能量

金属 (metallic = 1):
  F0 = albedo (高反射)
  kd = 0 (无漫反射，所有能量走镜面反射)
  折射光被自由电子完全吸收

非金属 (metallic = 0):
  F0 ≈ 0.04 (低反射)
  kd = 1 - F (大部分能量走漫反射)
  折射光经次表面散射后重新射出 = diffuse

能量守恒: kd + ks ≤ 1
  kd = (1 - F) * (1 - metallic)
  ks = F
```

---

## 3. Light Types & Attenuation

### 3.1 Light Source Classification

```
┌──────────────────────────────────────────────────────┐
│                   Light Sources                      │
├──────────────┬───────────────────────────────────────┤
│ Analytical   │ Directional, Point, Spot, Area        │
│ (解析光源)    │ 有明确数学公式描述                      │
├──────────────┼───────────────────────────────────────┤
│ Image-Based  │ Cubemap, SH, Reflection Probe         │
│ (基于图像)    │ 预计算环境光照                         │
├──────────────┼───────────────────────────────────────┤
│ Emissive     │ Emissive surfaces, Light cards        │
│ (自发光)      │ 不直接照亮其他物体(除非用GI)            │
└──────────────┴───────────────────────────────────────┘
```

### 3.2 Attenuation Functions

```hlsl
// === Directional Light ===
// No attenuation (infinite distance)
float Atten_Directional() { return 1.0; }

// === Point Light ===
// Inverse square law (physically correct)
float Atten_Point_Physical(float distance, float range)
{
    float d2 = distance * distance;
    // Windowing function to avoid hard cutoff at range boundary
    float factor = saturate(1.0 - pow(distance / range, 4.0));
    return (factor * factor) / max(d2, 0.01 * 0.01);
}

// UE4 implementation
float Atten_Point_UE4(float distance, float invRadius)
{
    float d2 = distance * distance;
    float falloff = 1.0 / (d2 + 1.0);
    float t = saturate(1.0 - pow(distance * invRadius, 4.0));
    return falloff * t * t;
}

// Unity URP implementation
float Atten_Point_URP(float distanceSqr, half4 distanceAndSpotAttenuation)
{
    float lightAtten = rcp(max(distanceSqr, 0.00001));
    float factor = distanceSqr * distanceAndSpotAttenuation.x;  // x = 1/range^2
    float smoothFactor = saturate(1.0 - factor * factor);
    return lightAtten * smoothFactor * smoothFactor;
}

// === Spot Light ===
float Atten_Spot(float3 lightDir, float3 spotDir,
                 float innerCos, float outerCos)
{
    float cosAngle = dot(-lightDir, spotDir);
    float spotAtten = saturate((cosAngle - outerCos) / (innerCos - outerCos));
    return spotAtten * spotAtten;  // smooth falloff
}

// === Area Light (Approximate) ===
// Most Representative Point (MRP) technique
// Used in UE4 for sphere/tube lights
// Modifies L vector to point toward closest point on light shape
```

### 3.3 Light Culling Strategies

```
┌─────────────────────────────────────────────────────────┐
│              Light Culling Methods                      │
├─────────────────┬───────────────────────────────────────┤
│ Per-Object      │ CPU: each object gets light list      │
│ (URP Forward)   │ Max 8 lights per object               │
│                 │ Simple, low overhead                  │
├─────────────────┼───────────────────────────────────────┤
│ Tiled           │ Screen divided into tiles (16x16)     │
│ (Forward+)      │ Each tile: frustum-sphere test        │
│                 │ Compute shader builds light list      │
│                 │ Good for many small lights            │
├─────────────────┼───────────────────────────────────────┤
│ Clustered       │ 3D grid (tiles + depth slices)        │
│ (UE4/HDRP)      │ Better depth distribution             │
│                 │ Handles depth discontinuities         │
│                 │ More memory, better quality           │
└─────────────────┴───────────────────────────────────────┘

Tiled vs Clustered:

  Tiled (2D):                    Clustered (3D):
  ┌──┬──┬──┬──┐                  ┌──┬──┬──┬──┐  ← far slice
  │  │  │  │  │                  ├──┼──┼──┼──┤
  ├──┼──┼──┼──┤                  ├──┼──┼──┼──┤  ← mid slices
  │  │  │  │  │                  ├──┼──┼──┼──┤
  ├──┼──┼──┼──┤                  ├──┼──┼──┼──┤
  │  │  │  │  │                  └──┴──┴──┴──┘  ← near slice
  └──┴──┴──┴──┘
  All depth → 1 list             Each depth slice → own list
  Problem: depth discontinuity   Better: lights only affect
  → too many lights per tile     relevant depth range
```

---

## 4. Shadow Mapping

### 4.1 Basic Shadow Map Pipeline

```
Shadow Map Generation:

  Pass 1: Shadow Caster Pass (from light's view)
  ┌─────────────────────────────────────────┐
  │ 1. Set camera to light position/dir     │
  │ 2. Render scene depth to shadow map     │
  │ 3. Store depth in texture               │
  └──────────────────┬──────────────────────┘
                     │
                     ▼
  Pass 2: Shadow Receiver Pass (from camera's view)
  ┌─────────────────────────────────────────┐
  │ 1. Transform fragment to light space    │
  │ 2. Sample shadow map at light-space XY  │
  │ 3. Compare fragment depth vs map depth  │
  │ 4. fragment.z > shadowMap.z → in shadow │
  └─────────────────────────────────────────┘
```

```hlsl
// Basic shadow sampling
float SampleShadow(float4 shadowCoord)
{
    // Transform to shadow map UV space
    float3 projCoord = shadowCoord.xyz / shadowCoord.w;
    projCoord = projCoord * 0.5 + 0.5;  // [-1,1] → [0,1]

    // Sample shadow map depth
    float closestDepth = tex2D(_ShadowMap, projCoord.xy).r;
    float currentDepth = projCoord.z;

    // Depth comparison with bias
    float bias = 0.005;
    float shadow = currentDepth - bias > closestDepth ? 0.0 : 1.0;
    return shadow;
}
```

### 4.2 Shadow Artifacts & Solutions

```
┌─────────────────────────────────────────────────────────┐
│                Shadow Artifacts                         │
├──────────────┬──────────────────────────────────────────┤
│ Shadow Acne  │ Self-shadowing due to depth precision    │
│ (阴影粉刺)    │ Fix: depth bias / slope-scale bias       │
├──────────────┼──────────────────────────────────────────┤
│ Peter-Panning│ Object appears floating (too much bias)  │
│ (彼得潘)      │ Fix: reduce bias / normal offset bias    │
├──────────────┼──────────────────────────────────────────┤
│ Aliasing     │ Jagged shadow edges (low resolution)     │
│ (锯齿)       │ Fix: PCF / CSM / higher resolution       │
├──────────────┼──────────────────────────────────────────┤
│ Light Leaking│ Shadow bleeds through thin geometry      │
│ (漏光)       │ Fix: normal offset / two-sided shadow    │
├──────────────┼──────────────────────────────────────────┤
│ Swimming     │ Shadow edges shimmer when camera moves   │
│ (游泳/闪烁)   │ Fix: stable CSM / texel snapping         │
└──────────────┴──────────────────────────────────────────┘
```

```hlsl
// Slope-scale bias (hardware supported)
// Adjusts bias based on surface angle to light
float bias = max(maxBias * (1.0 - NdotL), minBias);

// Normal offset bias (push along surface normal)
// Most effective against light leaking
float3 normalBias = surface.normal * normalBiasScale * texelSize;
float3 biasedPos = worldPos + normalBias;

// Combined approach (UE4/Unity)
float3 shadowPos = worldPos
    + surface.normal * normalBias    // push along normal
    + lightDir * depthBias;          // push toward light
```

### 4.3 PCF (Percentage Closer Filtering) 百分比渐进过滤

- PCF 即 投影导致的锯齿
- 优化CSM边缘锯齿 多次采样点的周围来判断该点阴影位置的权重，最后进行阴影系数的改变
- PCF能解决shadow map的锯齿块和硬边问题，产生柔和软阴影。
- 核心思想是从深度贴图中多次采样，每一次采样的纹理坐标都稍有不同（比如采样像素周围一圈范围）。
- 每个独立的样本可能在也可能不再阴影中。
- 所有的次生结果接着结合在一起，最终通过样本的总数目将深度结果平均化。

```hlsl
// Basic PCF - sample multiple shadow map texels and average
float PCF_Basic(float3 shadowCoord, float2 texelSize, int kernelSize)
{
    float shadow = 0.0;
    int halfKernel = kernelSize / 2;

    for (int x = -halfKernel; x <= halfKernel; x++)
    {
        for (int y = -halfKernel; y <= halfKernel; y++)
        {
            float2 offset = float2(x, y) * texelSize;
            float depth = tex2D(_ShadowMap, shadowCoord.xy + offset).r;
            shadow += shadowCoord.z - bias > depth ? 0.0 : 1.0;
        }
    }
    return shadow / (kernelSize * kernelSize);
}

// Optimized PCF using hardware bilinear (4 taps → 16 samples)
// Leverages GPU's built-in 2x2 bilinear filtering
float PCF_Bilinear4Tap(float3 shadowCoord, float2 texelSize)
{
    // 4 bilinear samples = 16 point samples
    float2 offset = float2(0.5, 0.5) * texelSize;
    float s0 = SampleShadowMap_Bilinear(shadowCoord.xy + float2(-offset.x, -offset.y));
    float s1 = SampleShadowMap_Bilinear(shadowCoord.xy + float2( offset.x, -offset.y));
    float s2 = SampleShadowMap_Bilinear(shadowCoord.xy + float2(-offset.x,  offset.y));
    float s3 = SampleShadowMap_Bilinear(shadowCoord.xy + float2( offset.x,  offset.y));
    return (s0 + s1 + s2 + s3) * 0.25;
}

// Poisson Disk PCF (better quality, irregular sampling)
static const float2 poissonDisk[16] = {
    float2(-0.94201624, -0.39906216), float2(0.94558609, -0.76890725),
    float2(-0.09418410, -0.92938870), float2(0.34495938,  0.29387760),
    // ... more samples
};

float PCF_PoissonDisk(float3 shadowCoord, float2 texelSize, float radius)
{
    float shadow = 0.0;
    for (int i = 0; i < 16; i++)
    {
        float2 offset = poissonDisk[i] * radius * texelSize;
        float depth = tex2D(_ShadowMap, shadowCoord.xy + offset).r;
        shadow += shadowCoord.z - bias > depth ? 0.0 : 1.0;
    }
    return shadow / 16.0;
}
```

### 4.4 CSM (Cascaded Shadow Maps)

级联阴影贴图 — 解决方向光大范围阴影的精度问题

```
CSM Principle:

  Camera Frustum split into cascades:

  Near ◄──────────────────────────────────────► Far
  ┌────────┬──────────────┬────────────────────────┐
  │Cascade0│  Cascade 1   │      Cascade 2         │
  │ 2048²  │   2048²      │       2048²            │
  │ 0-10m  │  10-30m      │      30-100m           │
  │ High   │  Medium      │       Low              │
  │ Detail │  Detail      │      Detail            │
  └────────┴──────────────┴────────────────────────┘

  Each cascade: own shadow map with same resolution
  Near objects get more texels per unit area

  Split Scheme:
  ┌──────────────────────────────────────────────┐
  │ Practical Split = lerp(Uniform, Log, lambda) │
  │                                              │
  │ Uniform   : Ci = Cn + (Cf-Cn) * i/N          │
  │ Log       : Ci = Cn * (Cf/Cn)^(i/N)          │
  │ Practical : Ci = λ*Log + (1-λ)*Uniform       │
  │                                              │
  │ λ = 0.5 is common starting point             │
  └──────────────────────────────────────────────┘
```

```hlsl
// CSM cascade selection
int SelectCascade(float viewDepth, float4 cascadeSplits)
{
    // cascadeSplits.xyzw = split distances in view space
    int cascade = 3;
    if (viewDepth < cascadeSplits.x) cascade = 0;
    else if (viewDepth < cascadeSplits.y) cascade = 1;
    else if (viewDepth < cascadeSplits.z) cascade = 2;
    return cascade;
}

// Cascade blending (avoid hard transition)
float CascadeBlend(float viewDepth, float splitDist, float blendRange)
{
    return saturate((splitDist - viewDepth) / blendRange);
}

// Stable CSM (prevent shadow swimming)
// Snap shadow map to texel grid
float3 StabilizeCascade(float3 shadowOrigin, float texelSize)
{
    shadowOrigin.xy = floor(shadowOrigin.xy / texelSize) * texelSize;
    return shadowOrigin;
}
```

**CSM 性能开销：**

| Cascade Count | Shadow Pass | Memory (2048²) | Typical Use |
| ------------- | ----------- | -------------- | ----------- |
| 2             | 2x scene    | 32 MB          | Mobile      |
| 3             | 3x scene    | 48 MB          | Console     |
| 4             | 4x scene    | 64 MB          | PC High     |

### 4.5 VSM (Variance Shadow Maps)

- 方差阴影贴图 — 支持硬件过滤的软阴影
  - 在使用PCF时一般不能提前对Shadow Map进行模糊处理，因为这会导致PCF计算不准，而Variance Shadow Maps则没有这样的限制。
  - VSM存储的Shadow Map不仅包括**深度**，还有**深度的平方**，这时可以对Shadow Map做过滤，
  - 然后利用切比雪夫不等式计算出大于当前深度的概率上限，也就是阴影区的概率

```
VSM vs Standard Shadow Map:

  Standard SM   :               VSM         :
  Store         : depth         Store       : depth + depth²
  Filter        : ❌ (wrong)    Filter      : ✅ (correct blur)
  Compare       : binary        Compare     : Chebyshev inequality
  Soft shadow   : PCF           Soft shadow : native blur

  VSM Advantage: can use hardware bilinear/mipmap/Gaussian blur
  VSM Problem: light bleeding (漏光) in overlapping occluders
```

```hlsl
// VSM: store moments
float2 VSM_StoreMoments(float depth)
{
    return float2(depth, depth * depth);  // (E[x], E[x²])
}

// VSM: compute shadow using Chebyshev inequality
float VSM_Shadow(float2 moments, float fragDepth)
{
    float E_x  = moments.x;   // mean depth
    float E_x2 = moments.y;   // mean depth squared
    float variance = E_x2 - E_x * E_x;  // σ² = E[x²] - E[x]²
    variance = max(variance, 0.00001);   // prevent division by zero

    float d = fragDepth - E_x;
    // Chebyshev: P(x >= t) <= σ² / (σ² + d²)
    float pMax = variance / (variance + d * d);

    // Light bleeding fix
    pMax = smoothstep(0.2, 1.0, pMax);  // reduce light bleeding

    return fragDepth <= E_x ? 1.0 : pMax;
}
```

### 4.6 PCSS (Percentage Closer Soft Shadows)

PCSS为了实现更真实的软阴影，达到离遮挡物距离近的时候硬，远的时候软的效果。

1. 算每个区块深度（shadow map上，只算被遮挡点的平均深度）
2. 通过深度估算需要采样范围多大（curDepth - AvgDepth） / AvgDepth
3. PCF在shadow map上采样，范围由第二步确定


```
PCSS Principle:
  Real shadows have variable penumbra width:
  - Close to occluder → sharp shadow
  - Far from occluder → soft shadow

  ┌─ Light ─┐
  │ ████████ │  (area light source)
  └────┬─────┘
       │
    ┌──┴──┐
    │Block│     ← Occluder (blocker)
    └──┬──┘
       │
  ─────┼─────  ← Receiver surface
    ▓▓▓█▓▓▓   ← Penumbra (半影) + Umbra (本影)

  Penumbra width = lightSize * (dReceiver - dBlocker) / dBlocker
```

```hlsl
// PCSS: 3-step algorithm
float PCSS(float3 shadowCoord, float2 texelSize, float lightSize)
{
    // Step 1: Blocker search (find average blocker depth)
    float avgBlockerDepth = 0.0;
    int blockerCount = 0;
    float searchRadius = lightSize * shadowCoord.z / shadowCoord.z;  // simplified

    for (int i = 0; i < BLOCKER_SEARCH_SAMPLES; i++)
    {
        float2 offset = poissonDisk[i] * searchRadius * texelSize;
        float depth = tex2D(_ShadowMap, shadowCoord.xy + offset).r;
        if (depth < shadowCoord.z - bias)
        {
            avgBlockerDepth += depth;
            blockerCount++;
        }
    }

    if (blockerCount == 0) return 1.0;  // no blocker, fully lit
    avgBlockerDepth /= blockerCount;

    // Step 2: Penumbra estimation
    float penumbraWidth = lightSize * (shadowCoord.z - avgBlockerDepth) / avgBlockerDepth;

    // Step 3: PCF with variable kernel size
    float shadow = 0.0;
    for (int i = 0; i < PCF_SAMPLES; i++)
    {
        float2 offset = poissonDisk[i] * penumbraWidth * texelSize;
        float depth = tex2D(_ShadowMap, shadowCoord.xy + offset).r;
        shadow += shadowCoord.z - bias > depth ? 0.0 : 1.0;
    }
    return shadow / PCF_SAMPLES;
}
```

### 4.7 Shadow Technique Comparison

| Technique   | Quality | Performance | Soft Shadow | Artifacts           |
| ----------- | ------- | ----------- | ----------- | ------------------- |
| Hard Shadow | ★☆☆     | ★★★         | ❌           | Aliasing            |
| PCF 3x3     | ★★☆     | ★★★         | Fixed width | Banding             |
| PCF Poisson | ★★★     | ★★☆         | Fixed width | Noise               |
| CSM         | ★★★     | ★★☆         | + PCF       | Cascade seams       |
| VSM         | ★★★     | ★★★         | ✅ Native    | Light bleeding      |
| PCSS        | ★★★★    | ★★☆         | ✅ Variable  | Noise               |
| SDF Shadow  | ★★★★    | ★★☆         | ✅ Variable  | SDF generation cost |
| Ray Traced  | ★★★★★   | ★☆☆         | ✅ Perfect   | Hardware required   |

---

## 5. Global Illumination

### 5.1 GI Overview

```
┌──────────────────────────────────────────────────────────┐
│              Global Illumination Methods                 │
├──────────────┬───────────────────────────────────────────┤
│              │  Baked (Offline)    │  Real-time          │
├──────────────┼─────────────────────┼─────────────────────┤
│ Diffuse GI   │ Lightmap            │ SSGI                │
│              │ Light Probe (SH)    │ DDGI                │
│              │ Irradiance Volume   │ Lumen (UE5)         │
│              │                     │ Voxel GI            │
├──────────────┼─────────────────────┼─────────────────────┤
│ Specular GI  │ Reflection Probe    │ SSR                 │
│              │ Planar Reflection   │ RT Reflection       │
│              │                     │ Lumen Reflection    │
├──────────────┼─────────────────────┼─────────────────────┤
│ AO           │ Baked AO map        │ SSAO / GTAO / HBAO  │
│              │ Bent Normal         │ RT AO               │
└──────────────┴─────────────────────┴─────────────────────┘
```

### 5.2 Lightmap

光照贴图 — 将间接光照预计算烘焙到纹理中

```
Lightmap Pipeline:

  1. UV Unwrap (Lightmap UV - UV2)
     ┌──────────────────────┐
     │ Each mesh face gets  │
     │ unique UV space in   │
     │ lightmap atlas       │
     └──────────┬───────────┘
                │
  2. Path Tracing / Radiosity
     ┌──────────────────────┐
     │ Trace rays from each │
     │ lightmap texel       │
     │ Accumulate bounced   │
     │ light (GI)           │
     └──────────┬───────────┘
                │
  3. Store in Texture
     ┌──────────────────────┐
     │ Directional Lightmap │
     │ = Color + Direction  │
     │ or SH Lightmap       │
     │ = SH coefficients    │
     └──────────────────────┘

Lightmap Types:
  Non-Directional: RGB color only (cheapest)
  Directional:     RGB + dominant direction (better specular)
  SH:              L0/L1 SH coefficients (best quality)
```

```hlsl
// Sample lightmap in shader
half3 SampleLightmap(float2 lightmapUV)
{
    // Unity: lightmap stored in RGBM encoding
    half4 encodedLight = SAMPLE_TEXTURE2D(unity_Lightmap, samplerunity_Lightmap, lightmapUV);
    // Decode RGBM: rgb * a * 5.0 (Unity's range)
    half3 lightmap = DecodeLightmap(encodedLight);
    return lightmap;
}

// Directional lightmap
half3 SampleDirectionalLightmap(float2 lightmapUV, half3 normalWS)
{
    half4 direction = SAMPLE_TEXTURE2D(unity_LightmapInd, samplerunity_Lightmap, lightmapUV);
    half3 color = SampleLightmap(lightmapUV);

    // Half-Lambert style directional factor
    half halfLambert = dot(normalWS, direction.xyz - 0.5) + 0.5;
    return color * halfLambert / max(1e-4, direction.w);
}
```

**Lightmap 优缺点：**

| Pros                       | Cons                            |
| -------------------------- | ------------------------------- |
| Zero runtime cost for GI   | Static only, no dynamic objects |
| High quality (path traced) | Large memory (texture atlas)    |
| Infinite bounces           | Long bake time                  |
| No noise                   | UV seams possible               |

### 5.3 Light Probes (Spherical Harmonics)

球谐光照探针 — 为动态物体提供间接光照

```
Spherical Harmonics (SH):

  Represent lighting environment as frequency bands:

  L0 (1 coeff):   Ambient / average color
  ┌───┐
  │ ● │  DC term, constant in all directions
  └───┘

  L1 (3 coeffs):  Directional gradient
  ┌───┬───┬───┐
  │ ↕ │ ↔ │ ↗ │  Linear terms (x, y, z)
  └───┴───┴───┘

  L2 (5 coeffs):  Quadratic detail
  ┌───┬───┬───┬───┬───┐
  │   │   │   │   │   │  Higher frequency
  └───┴───┴───┴───┴───┘

  Total L2 SH: 9 coefficients per color channel = 27 floats
  Sufficient for low-frequency diffuse lighting

  Memory per probe: 27 floats × 4 bytes = 108 bytes
  vs Cubemap: 6 × 64 × 64 × 4 = 98,304 bytes
  Compression ratio: ~1000:1
```

```hlsl
// Evaluate SH lighting (L2, 9 coefficients)
half3 SampleSH(half3 normalWS)
{
    // Unity packs SH into 7 float4 values
    // unity_SHAr, unity_SHAg, unity_SHAb (L0L1)
    // unity_SHBr, unity_SHBg, unity_SHBb (L2)
    // unity_SHC (L2)

    half4 n = half4(normalWS, 1.0);

    // L0 + L1
    half3 res;
    res.r = dot(unity_SHAr, n);
    res.g = dot(unity_SHAg, n);
    res.b = dot(unity_SHAb, n);

    // L2
    half4 vB = n.xyzz * n.yzzx;
    res.r += dot(unity_SHBr, vB);
    res.g += dot(unity_SHBg, vB);
    res.b += dot(unity_SHBb, vB);

    float vC = n.x * n.x - n.y * n.y;
    res += unity_SHC.rgb * vC;

    return max(half3(0, 0, 0), res);
}
```

### 5.4 Reflection Probes

反射探针 — 为镜面反射提供环境信息

```
Reflection Probe Pipeline:

  Capture:
  ┌─────────────────────────────────┐
  │ Render 6 faces of cubemap       │
  │ at probe position               │
  └──────────────┬──────────────────┘
                 │
  Pre-filter (Split-Sum Approximation):
  ┌─────────────────────────────────┐
  │ Mip 0: roughness = 0 (mirror)   │
  │ Mip 1: roughness = 0.25         │
  │ Mip 2: roughness = 0.5          │
  │ Mip 3: roughness = 0.75         │
  │ Mip 4: roughness = 1.0 (diffuse)│
  └──────────────┬──────────────────┘
                 │
  Runtime Sampling:
  ┌─────────────────────────────────┐
  │ reflectDir = reflect(-V, N)     │
  │ mipLevel = roughness * maxMip   │
  │ color = cubemap.SampleLevel(    │
  │           reflectDir, mipLevel) │
  └─────────────────────────────────┘
```

```hlsl
// IBL Specular (Split-Sum Approximation)
half3 IBL_Specular(half3 N, half3 V, half roughness, half3 F0)
{
    half3 R = reflect(-V, N);
    half NdotV = saturate(dot(N, V));

    // Part 1: Pre-filtered environment map
    half mip = roughness * UNITY_SPECCUBE_LOD_STEPS;
    half3 prefilteredColor = SAMPLE_TEXTURECUBE_LOD(
        unity_SpecCube0, samplerunity_SpecCube0, R, mip).rgb;
    prefilteredColor = DecodeHDR(prefilteredColor);

    // Part 2: BRDF integration LUT
    half2 envBRDF = SAMPLE_TEXTURE2D(
        _BRDFLut, sampler_BRDFLut, half2(NdotV, roughness)).rg;

    // Combine
    return prefilteredColor * (F0 * envBRDF.x + envBRDF.y);
}
```

### 5.5 Screen Space Global Illumination (SSGI)

```
SSGI Pipeline:

  1. Ray March in screen space
     ┌──────────────────────────────────┐
     │ For each pixel:                  │
     │   Generate rays in hemisphere    │
     │   March along ray in depth buffer│
     │   If hit: read color buffer      │
     │   Accumulate indirect light      │
     └──────────────┬───────────────────┘
                    │
  2. Temporal Accumulation
     ┌──────────────────────────────────┐
     │ Blend current frame with history │
     │ Reduces noise, improves quality  │
     │ Requires motion vectors          │
     └──────────────┬───────────────────┘
                    │
  3. Spatial Denoise
     ┌──────────────────────────────────┐
     │ Edge-aware bilateral filter      │
     │ Preserves sharp edges            │
     │ Removes remaining noise          │
     └─────────────────────────────────┘

  Limitations:
  - Only captures what's on screen (no off-screen bounces)
  - Fails at screen edges
  - Depth-only → misses thin objects
  - Performance cost: 1-3ms
```

### 5.6 Lumen (UE5)

```
Lumen Architecture:

  ┌─────────────────────────────────────────────────┐
  │                Surface Cache                     │
  │  Mesh Cards → capture surface attributes         │
  │  (albedo, normal, emissive) from 6 directions    │
  │  Stored in atlas, updated incrementally           │
  └──────────────────────┬──────────────────────────┘
                         │
  ┌──────────────────────▼──────────────────────────┐
  │              Radiance Cache                      │
  │  World-space probes on adaptive grid             │
  │  Each probe: SH coefficients                     │
  │  Updated via screen traces + surface cache       │
  └──────────────────────┬──────────────────────────┘
                         │
  ┌──────────────────────▼──────────────────────────┐
  │           Screen Space Tracing                   │
  │  Primary: screen space ray march                 │
  │  Fallback: trace against surface cache           │
  │  Final fallback: distance field tracing          │
  └──────────────────────┬──────────────────────────┘
                         │
  ┌──────────────────────▼──────────────────────────┐
  │           Temporal & Spatial Filter              │
  │  Denoise, accumulate, upscale                    │
  └─────────────────────────────────────────────────┘

  Lumen Modes:
  ┌──────────────┬──────────────────────────────────┐
  │ Software     │ SDF tracing + Surface Cache       │
  │              │ Works on all hardware              │
  │              │ Lower quality, ~2-4ms              │
  ├──────────────┼──────────────────────────────────┤
  │ Hardware RT  │ Uses RT cores for final gather     │
  │              │ Higher quality, requires RTX/RDNA2 │
  │              │ ~3-6ms                             │
  └──────────────┴──────────────────────────────────┘
```

---

## 6. Ambient Occlusion

### 6.1 AO Techniques Overview

```
┌─────────────────────────────────────────────────────────┐
│              Ambient Occlusion Methods                    │
├──────────────┬──────────────────────────────────────────┤
│ Baked AO     │ Offline ray traced, stored in texture     │
│              │ Highest quality, static only               │
├──────────────┼──────────────────────────────────────────┤
│ SSAO         │ Screen-space, sample depth buffer         │
│ (Crytek 2007)│ Random hemisphere samples                 │
│              │ Noisy, needs blur                          │
├──────────────┼──────────────────────────────────────────┤
│ HBAO+        │ Horizon-based, physically motivated       │
│ (NVIDIA)     │ Better quality than SSAO                   │
│              │ Traces horizon angle per direction         │
├──────────────┼──────────────────────────────────────────┤
│ GTAO         │ Ground Truth AO (Jimenez 2016)            │
│              │ Integrates visibility over hemisphere      │
│              │ Best quality/performance ratio             │
│              │ Used in UE4/UE5                            │
├──────────────┼──────────────────────────────────────────┤
│ RTAO         │ Ray traced, hardware accelerated           │
│              │ True geometry AO, no screen-space limits   │
└──────────────┴──────────────────────────────────────────┘
```

### 6.2 SSAO Implementation

```hlsl
// SSAO (simplified Crytek-style)
float SSAO(float2 uv, float3 posVS, float3 normalVS)
{
    float occlusion = 0.0;
    float radius = _AORadius;

    for (int i = 0; i < SAMPLE_COUNT; i++)
    {
        // Random point in hemisphere oriented along normal
        float3 sampleDir = TangentToViewSpace(hemisphereKernel[i], normalVS);
        float3 samplePos = posVS + sampleDir * radius;

        // Project sample to screen space
        float4 offset = mul(_ProjectionMatrix, float4(samplePos, 1.0));
        offset.xy = offset.xy / offset.w * 0.5 + 0.5;

        // Sample depth buffer at projected position
        float sampleDepth = LinearEyeDepth(tex2D(_DepthTexture, offset.xy).r);

        // Range check: only occlude if sample is close enough
        float rangeCheck = smoothstep(0.0, 1.0, radius / abs(posVS.z - sampleDepth));

        // If sample is behind geometry → occluded
        occlusion += (sampleDepth >= samplePos.z + bias ? 1.0 : 0.0) * rangeCheck;
    }

    return 1.0 - (occlusion / SAMPLE_COUNT) * _AOIntensity;
}
```

### 6.3 GTAO (Ground Truth Ambient Occlusion)

```
GTAO Principle:

  For each pixel, trace horizon angles in multiple directions:

  Side view of one slice direction:

       ╱ horizon angle θ
      ╱
     ╱
    P────────────→ trace direction
    │
    │ surface normal
    │

  Visibility = integral of visible hemisphere
  AO = 1 - Visibility

  Steps:
  1. For each direction (4-8 slices):
     a. March along direction in screen space
     b. Sample depth buffer at each step
     c. Compute horizon angle (max elevation angle of occluder)
  2. Integrate visible arc between horizon angles
  3. Average across all directions
  4. Apply cosine-weighted integration

  Advantage over SSAO:
  - Physically based integration (not random sampling)
  - Less noise, fewer samples needed
  - Better contact shadows
```

```hlsl
// GTAO (simplified)
float GTAO(float2 uv, float3 posVS, float3 normalVS)
{
    float ao = 0.0;
    int directionCount = 4;  // number of slice directions
    int stepCount = 4;       // steps per direction

    for (int dir = 0; dir < directionCount; dir++)
    {
        float angle = (float(dir) + noise) / float(directionCount) * PI;
        float2 direction = float2(cos(angle), sin(angle));

        // Find horizon angles in both directions (+/-)
        float horizonCos1 = -1.0;  // negative direction
        float horizonCos2 = -1.0;  // positive direction

        for (int step = 1; step <= stepCount; step++)
        {
            float2 offset = direction * float(step) * _StepSize;

            // Positive direction
            float3 samplePos = GetViewPos(uv + offset);
            float3 diff = samplePos - posVS;
            float cosAngle = dot(normalize(diff), normalVS);
            horizonCos2 = max(horizonCos2, cosAngle);

            // Negative direction
            samplePos = GetViewPos(uv - offset);
            diff = samplePos - posVS;
            cosAngle = dot(normalize(diff), normalVS);
            horizonCos1 = max(horizonCos1, cosAngle);
        }

        // Integrate visible arc
        float theta1 = acos(horizonCos1);
        float theta2 = acos(horizonCos2);
        ao += IntegrateArc(theta1, theta2, normalVS, direction);
    }

    return ao / float(directionCount);
}
```

---

## 7. Volumetric Lighting

### 7.1 God Rays / Light Shafts

体积光 — 模拟光线在介质中的散射

```
Volumetric Lighting Methods:

┌──────────────────┬─────────────────────────────────────┐
│ Radial Blur      │ Post-process, blur from light source │
│ (Screen Space)   │ Cheap, fake, only for directional    │
├──────────────────┼─────────────────────────────────────┤
│ Ray Marching     │ March rays through volume             │
│ (Per-Pixel)      │ Accurate, expensive                   │
├──────────────────┼─────────────────────────────────────┤
│ Froxel           │ 3D frustum-aligned voxel grid         │
│ (UE4/HDRP)      │ Best quality/performance               │
│                  │ Temporal reprojection                  │
└──────────────────┴─────────────────────────────────────┘
```

```hlsl
// Simple ray marching volumetric light
float3 VolumetricLight(float3 worldPos, float3 cameraPos, Light light)
{
    float3 rayDir = worldPos - cameraPos;
    float rayLength = length(rayDir);
    rayDir /= rayLength;

    int stepCount = 32;
    float stepSize = rayLength / float(stepCount);
    float3 accumScattering = 0;

    // Dithered start position (reduce banding)
    float dither = InterleavedGradientNoise(screenUV * _ScreenSize.xy);
    float3 currentPos = cameraPos + rayDir * stepSize * dither;

    for (int i = 0; i < stepCount; i++)
    {
        // Shadow test at current position
        float shadow = SampleShadowMap(currentPos);

        // Phase function (Henyey-Greenstein)
        float cosAngle = dot(rayDir, light.direction);
        float phase = HenyeyGreenstein(cosAngle, _Anisotropy);

        // Accumulate in-scattered light
        float density = SampleDensity(currentPos);  // fog/dust density
        accumScattering += shadow * phase * density * light.color * stepSize;

        // Beer's law extinction
        // transmittance *= exp(-density * stepSize * _ExtinctionCoeff);

        currentPos += rayDir * stepSize;
    }

    return accumScattering * _ScatteringCoeff;
}

// Henyey-Greenstein phase function
// g > 0: forward scattering (sun shafts)
// g < 0: back scattering
// g = 0: isotropic (uniform)
float HenyeyGreenstein(float cosAngle, float g)
{
    float g2 = g * g;
    return (1.0 - g2) / (4.0 * PI * pow(1.0 + g2 - 2.0 * g * cosAngle, 1.5));
}
```

### 7.2 Froxel-Based Volumetric Fog

```
Froxel (Frustum + Voxel):

  Camera frustum divided into 3D grid:

  Near ◄─────────────────────────────► Far
  ┌──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┐
  │  │  │  │  │  │  │  │  │  │  │  │  ← depth slices
  ├──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──┤    (exponential distribution)
  │  │  │  │  │  │  │  │  │  │  │  │
  ├──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼──┤
  │  │  │  │  │  │  │  │  │  │  │  │
  └──┴──┴──┴──┴──┴──┴──┴──┴──┴──┴──┘

  Typical: 160 × 90 × 64 = ~1M froxels

  Pipeline:
  1. Inject: write density + scattering into 3D texture
  2. Light: for each froxel, compute in-scattering from all lights
  3. Integrate: front-to-back accumulation (Beer-Lambert)
  4. Apply: sample integrated volume during scene compositing

  Temporal: jitter slice offset each frame, blend with history
  → 4 frames of jitter = 4x effective sample count
```

---

## 8. Screen Space Reflections (SSR)

### 8.1 SSR Pipeline

```
SSR Steps:

  1. Generate reflection ray
     R = reflect(-V, N)

  2. Ray march in screen space
     ┌──────────────────────────────────┐
     │ Start from pixel position         │
     │ Step along R projected to screen  │
     │ At each step: compare ray depth   │
     │   with depth buffer               │
     │ If ray goes behind geometry → hit │
     └──────────────────────────────────┘

  3. Read color at hit point
     color = ColorBuffer[hitUV]

  4. Fade edges
     - Fade at screen borders (no data)
     - Fade by roughness (noisy at high roughness)
     - Fade by ray length (distant reflections less reliable)
```

```hlsl
// Hierarchical ray marching (Hi-Z SSR)
float4 SSR_HiZ(float3 posVS, float3 reflectDirVS)
{
    // Project ray to screen space
    float3 rayOrigin = posVS;
    float3 rayEnd = posVS + reflectDirVS * _MaxDistance;

    float2 startUV = ViewToScreen(rayOrigin);
    float2 endUV = ViewToScreen(rayEnd);

    // Hi-Z traversal: start at highest mip, step down on hit
    int mipLevel = _MaxMipLevel;
    float2 currentUV = startUV;
    float currentDepth = rayOrigin.z;

    for (int i = 0; i < MAX_STEPS; i++)
    {
        // Sample depth at current mip level
        float sceneDepth = SampleHiZDepth(currentUV, mipLevel);

        if (currentDepth > sceneDepth)  // ray behind geometry
        {
            if (mipLevel == 0)
            {
                // Found intersection at finest level
                float3 hitColor = tex2D(_ColorBuffer, currentUV).rgb;
                float confidence = ComputeConfidence(currentUV, roughness);
                return float4(hitColor, confidence);
            }
            // Step back and go to finer mip
            currentUV -= stepUV;
            currentDepth -= stepDepth;
            mipLevel--;
        }
        else
        {
            // Advance ray at current mip level
            float stepScale = exp2(mipLevel);
            currentUV += stepUV * stepScale;
            currentDepth += stepDepth * stepScale;
        }
    }

    return float4(0, 0, 0, 0);  // no hit, fallback to probe
}
```

---

## 9. Mobile Lighting Optimization

### 9.1 Mobile Lighting Constraints

```
┌─────────────────────────────────────────────────────────┐
│           Mobile Lighting Budget                         │
├──────────────────┬──────────────────────────────────────┤
│ Total frame      │ 16.6ms (60fps) / 33.3ms (30fps)     │
│ Lighting budget  │ 2-4ms                                │
│ Shadow budget    │ 1-2ms                                │
│ Max lights       │ 1 directional + 4-8 additional       │
│ Shadow cascades  │ 2 (mobile) / 4 (high-end mobile)     │
│ Shadow resolution│ 1024-2048                             │
│ GI method        │ Lightmap + SH probes                  │
│ AO               │ Baked only (or very cheap SSAO)       │
│ Reflections      │ Reflection probe only (no SSR)        │
└──────────────────┴──────────────────────────────────────┘
```

### 9.2 Mobile BRDF Simplifications

```hlsl
// Mobile-optimized PBR (URP Mobile path)
half3 MobileBRDF(half3 albedo, half metallic, half roughness,
                 half3 N, half3 L, half3 V, half3 lightColor)
{
    half3 H = normalize(V + L);
    half NdotL = saturate(dot(N, L));
    half NdotH = saturate(dot(N, H));
    half NdotV = saturate(dot(N, V));

    // Simplified specular: GGX approximation
    // Minimalist Cook-Torrance (Filament mobile)
    half a2 = roughness * roughness;
    half d = NdotH * NdotH * (a2 - 1.0) + 1.0;
    half specularTerm = a2 / (d * d * max(0.1, NdotL * NdotV) * (roughness * 4.0 + 2.0));
    // Note: no PI division, no separate D/F/G
    // All approximated into single expression

    // Fresnel: simplified Schlick
    half3 F0 = lerp(half3(0.04, 0.04, 0.04), albedo, metallic);

    // Combine
    half3 diffuse = albedo * (1.0 - metallic);
    half3 color = (diffuse + specularTerm * F0) * lightColor * NdotL;

    return color;
}
```

### 9.3 Mobile Shadow Optimization

```
Mobile Shadow Strategies:

  1. Reduce shadow caster count
     - Only main character + important objects cast shadows
     - Use LOD to simplify shadow meshes

  2. Lower shadow map resolution
     - 1024² for mobile (vs 2048-4096 on PC)
     - 2 cascades max (vs 4 on PC)

  3. Simpler filtering
     - 1-tap or 4-tap PCF (vs 16+ on PC)
     - Hardware shadow comparison (free on most GPUs)

  4. Shadow distance
     - 30-50m max (vs 100+ on PC)
     - Fade out shadows at distance

  5. Blob shadows for distant/unimportant objects
     - Simple projected circle/ellipse
     - Zero shadow map cost

  6. Screen-space contact shadows
     - Short-range ray march in depth buffer
     - Adds detail near contact points
     - 4-8 steps, very cheap
```

```hlsl
// Mobile-optimized shadow sampling (1 hardware PCF tap)
half MobileShadow(float4 shadowCoord)
{
    // Use hardware shadow comparison (SamplerComparisonState)
    // Returns filtered result from 2x2 texels for free
    return SAMPLE_TEXTURE2D_SHADOW(
        _MainLightShadowmapTexture,
        sampler_MainLightShadowmapTexture,
        shadowCoord.xyz);
}

// Contact shadow (screen-space, very short range)
half ContactShadow(float2 uv, float3 posVS, float3 lightDirVS)
{
    float3 rayDir = lightDirVS;
    float stepSize = _ContactShadowLength / 4.0;
    float3 currentPos = posVS;

    for (int i = 0; i < 4; i++)  // only 4 steps!
    {
        currentPos += rayDir * stepSize;
        float2 sampleUV = ViewToScreen(currentPos);
        float sceneDepth = SampleDepth(sampleUV);

        if (currentPos.z > sceneDepth + 0.01)
            return 0.0;  // in shadow
    }
    return 1.0;  // lit
}
```

### 9.4 TBR-Friendly Lighting

```
TBR Optimization for Lighting:

  ✅ Do:
  - Use FrameBuffer Fetch for deferred-like lighting on mobile
  - Keep render targets in tile memory (Memoryless)
  - Minimize Load/Store actions
  - Use single-pass lighting (avoid multiple full-screen passes)

  ❌ Don't:
  - Multiple full-screen post-process passes for lighting
  - Read back shadow map in same render pass
  - Use too many render targets (bandwidth)

  Mobile Deferred (Tile-Based):
  ┌─────────────────────────────────────────┐
  │ Subpass 0: Write GBuffer to tile memory │
  │ Subpass 1: Read GBuffer via FB Fetch    │
  │            Compute lighting             │
  │            Write final color            │
  │ Store: only final color to DRAM         │
  │ GBuffer: Memoryless (never hits DRAM)   │
  └─────────────────────────────────────────┘
  Bandwidth: same as forward rendering!
```

---

## 10. Engine Implementation Reference

### 10.1 Unity URP Lighting

```
URP Lighting Pipeline:

  Forward:
  ┌─────────────────────────────────────────┐
  │ 1. Main Light (directional) + shadow    │
  │ 2. Additional Lights (per-object list)  │
  │    Max 8 per object                     │
  │ 3. GI: Lightmap / SH Probes             │
  │ 4. Reflection: Probe + Planar           │
  │ 5. AO: Baked / SSAO (optional)          │
  └─────────────────────────────────────────┘

  Forward+:
  ┌─────────────────────────────────────────┐
  │ 1. Depth PrePass                        │
  │ 2. Light Culling (tiled, compute)       │
  │ 3. Forward rendering with light list    │
  │    No per-object light limit            │
  └─────────────────────────────────────────┘

```

### 10.2 UE4/UE5 Lighting

```
UE Lighting Architecture:

  Deferred Pipeline:
  ┌─────────────────────────────────────────┐
  │ 1. Base Pass → GBuffer                  │
  │ 2. Shadow Depth Pass (per light)        │
  │ 3. Lighting Pass                        │
  │    a. Directional light (full-screen)   │
  │    b. Point/Spot (stencil-masked)       │
  │    c. Tiled deferred (many lights)      │
  │ 4. Reflection Environment               │
  │ 5. Translucency                         │
  │ 6. Post-Process (AO, Bloom, etc.)       │
  └─────────────────────────────────────────┘

  UE5 Additions:
  - Lumen GI (replaces lightmaps for dynamic GI)
  - Virtual Shadow Maps (replaces CSM)
  - Nanite (affects shadow rendering)

  Virtual Shadow Maps (VSM):
  ┌─────────────────────────────────────────┐
  │ Single 16K×16K virtual shadow map       │
  │ Clipmap for directional light           │
  │ Pages allocated on demand               │
  │ Nanite rasterizes shadow geometry       │
  │ Per-page caching (only re-render dirty) │
  │ Result: high-res shadows everywhere     │
  └─────────────────────────────────────────┘
```

---

## 11. Advanced Topics

### 11.1 SDF Shadows (Signed Distance Field)

```
SDF Shadow Principle:

  Pre-compute: for each point in 3D space, store distance to nearest surface
  Runtime: ray march through SDF, use distance to estimate shadow softness

  ┌─────────────────────────────────────────┐
  │ float shadow = 1.0;                     │
  │ float t = 0.01;                         │
  │ for (int i = 0; i < 32; i++) {          │
  │     float d = SampleSDF(pos + dir * t); │
  │     shadow = min(shadow,                │
  │                  k * d / t);            │
  │     t += d;                             │
  │     if (d < 0.001) break;               │
  │ }                                       │
  │ // k controls penumbra softness         │
  └─────────────────────────────────────────┘

  Advantages:
  - Naturally soft shadows (variable penumbra)
  - No shadow map needed
  - Works for any light type

  Disadvantages:
  - SDF generation cost (offline or GPU compute)
  - Memory for 3D SDF texture
  - Limited to static geometry (or needs update)
  - Lower precision than shadow maps

  UE4 Distance Field Shadows:
  - Per-mesh SDF stored in volume texture
  - Composited at runtime via ray marching
  - Used for: area shadows, AO, sky occlusion
```

### 11.2 Ray Traced Shadows

```
RT Shadow Pipeline:

  1. For each pixel:
     - Cast ray toward light source
     - If ray hits geometry before light → shadow
     - For area lights: cast multiple rays → soft shadow

  2. Denoise:
     - 1 spp (sample per pixel) is very noisy
     - Temporal accumulation + spatial filter
     - NVIDIA RTXDI for many lights

  Performance:
  ┌──────────────┬──────────┬──────────┐
  │ Resolution   │ 1 spp    │ 4 spp    │
  ├──────────────┼──────────┼──────────┤
  │ 1080p        │ ~1ms     │ ~3ms     │
  │ 1440p        │ ~1.5ms   │ ~5ms     │
  │ 4K           │ ~3ms     │ ~10ms    │
  └──────────────┴──────────┴──────────┘
  (RTX 3080, typical scene complexity)
```

### 11.3 Subsurface Scattering (SSS)

次表面散射 — 模拟光线穿透半透明材质（皮肤、蜡烛、树叶等）

```
SSS Methods:

  Pre-Integrated SSS (Mobile-friendly):
  ┌─────────────────────────────────────────┐
  │ Pre-compute LUT: NdotL × curvature      │
  │ → wrap lighting + color shift           │
  │ Very cheap, single texture lookup       │
  └─────────────────────────────────────────┘

  Screen-Space SSS (Separable SSS):
  ┌─────────────────────────────────────────┐
  │ 1. Render skin to separate RT           │
  │ 2. Blur in screen space (Gaussian)      │
  │    - Different blur per RGB channel     │
  │    - Red blurs most (penetrates deepest)│
  │ 3. Composite back                       │
  └─────────────────────────────────────────┘

  Transmission (back-lighting):
  ┌─────────────────────────────────────────┐
  │ Light passing through thin objects      │
  │ (ears, leaves, thin cloth)              │
  │ Approximate: wrap NdotL + thickness map │
  │ float transmission = saturate(          │
  │   dot(-N, L) * thickness * scale);      │
  └─────────────────────────────────────────┘
```

```hlsl
// Pre-integrated skin SSS
half3 PreIntegratedSSS(half NdotL, half curvature, sampler2D sssLUT)
{
    // LUT: x = NdotL * 0.5 + 0.5, y = curvature
    half2 lutUV = half2(NdotL * 0.5 + 0.5, curvature);
    return tex2D(sssLUT, lutUV).rgb;
}

// Transmission approximation
half3 Transmission(half3 N, half3 L, half3 V, half thickness,
                   half3 translucencyColor)
{
    half3 H = normalize(L + N * _Distortion);
    half VdotH = saturate(dot(V, -H));
    half transmission = pow(VdotH, _Power) * _Scale;
    transmission *= (1.0 - thickness);  // thickness map: 0=thin, 1=thick
    return translucencyColor * transmission;
}
```

---

## 12. Performance Analysis

### 12.1 Lighting Cost Breakdown

```
Typical Lighting Cost (1080p, mid-range GPU):

┌──────────────────────────┬──────────┬──────────┐
│ Component                │ PC (ms)  │ Mobile   │
├──────────────────────────┼──────────┼──────────┤
│ Shadow Map Render (CSM)  │ 0.5-2.0  │ 0.5-1.5  │
│ Shadow Sampling          │ 0.2-0.5  │ 0.1-0.3  │
│ Direct Lighting          │ 0.3-1.0  │ 0.2-0.5  │
│ GI (Lightmap/SH)         │ 0.1-0.3  │ 0.1-0.2  │
│ Reflection Probe         │ 0.1-0.3  │ 0.1-0.2  │
│ SSR                      │ 0.5-2.0  │ N/A      │
│ SSAO/GTAO                │ 0.3-1.0  │ N/A      │
│ Volumetric Fog           │ 0.5-1.5  │ N/A      │
├──────────────────────────┼──────────┼──────────┤
│ Total                    │ 2.5-8.6  │ 1.0-2.7  │
└──────────────────────────┴──────────┴──────────┘
```

### 12.2 Optimization Checklist

```
Shadow Optimization:
□ Minimize shadow caster count (culling, LOD)
□ Use appropriate shadow map resolution
□ Limit cascade count on mobile (2 max)
□ Enable shadow caching for static lights
□ Use contact shadows instead of high-res shadow maps
□ Fade shadows at distance

Lighting Optimization:
□ Limit additional light count per object
□ Use light culling (Forward+ / Clustered)
□ Bake static lighting (lightmaps)
□ Use SH probes for dynamic objects
□ Simplify BRDF on mobile
□ Reduce specular on distant objects

GI Optimization:
□ Use lightmaps for static geometry
□ Limit reflection probe count and resolution
□ Use box projection for indoor probes
□ Disable SSR on mobile
□ Use SSAO at half resolution

Bandwidth Optimization (Mobile):
□ Minimize render target count
□ Use Memoryless for intermediate targets
□ Avoid unnecessary Load/Store actions
□ Single-pass lighting where possible
□ Compress shadow maps (16-bit depth)
```

---

## 13. Interview Questions

### Q1: Explain the Cook-Torrance BRDF and each term's role

**Answer:**

Cook-Torrance BRDF: `f = D * F * G / (4 * NdotV * NdotL)`

- **D (NDF)**: Normal Distribution Function, describes probability of microfacet normals aligning with half-vector. GGX is standard — produces long-tail highlights. Controls specular shape.
- **F (Fresnel)**: Schlick approximation. Reflectance increases at grazing angles. F0 = base reflectivity (0.04 for dielectrics, albedo for metals). Drives edge highlighting.
- **G (Geometry)**: Smith-GGX. Models self-shadowing/masking of microfacets. Darkens specular at grazing angles. Prevents energy gain.
- **Denominator**: Normalization factor ensuring energy conservation.

Energy conservation: `kd = (1-F)(1-metallic)`, ensures reflected + refracted ≤ incident energy.

### Q2: Why does MSAA not work well with deferred rendering?

**Answer:**

Deferred rendering writes material properties to GBuffer (multiple render targets), then performs lighting in a full-screen pass. MSAA operates at rasterization stage — it generates multiple samples per pixel for geometry edges.

Problem: The lighting pass is a full-screen quad — it has no geometry edges, so MSAA provides zero benefit for the most expensive pass. Meanwhile, the GBuffer must store N× more data (one per sample), multiplying bandwidth and memory.

Solutions:
- Use MSAA only for GBuffer, resolve before lighting (loses edge quality)
- Use temporal AA instead (TAA) — standard approach
- Use Forward+ rendering if MSAA is required

### Q3: Explain CSM and how to reduce shadow swimming

**Answer:**

CSM splits camera frustum into cascades, each with its own shadow map. Near cascades get higher texel density.

Shadow swimming occurs because shadow map texels don't align with world-space positions as camera moves. Fix: **texel snapping** — round shadow map origin to texel grid:

```
shadowOrigin.xy = floor(shadowOrigin.xy / texelSize) * texelSize;
```

Also: use stable cascade bounds (sphere-based instead of tight frustum fit), and avoid cascade split distance changes.

### Q4: Compare shadow techniques for mobile games

**Answer:**

| Technique                 | Quality | Cost         | Best For           |
| ------------------------- | ------- | ------------ | ------------------ |
| Shadow Map + 1-tap PCF    | Low     | Very cheap   | Background objects |
| CSM 2-cascade + 4-tap PCF | Medium  | Cheap        | Main scene         |
| Blob shadow (projected)   | Low     | Near zero    | Distant characters |
| Contact shadow (4-step)   | Detail  | Very cheap   | Close-up detail    |
| Baked shadow (lightmap)   | High    | Zero runtime | Static environment |

Recommended mobile setup: CSM 2-cascade for main character + important objects, blob shadows for NPCs, baked shadows for environment, contact shadows for close-up detail.

### Q5: What is the Split-Sum approximation for IBL?

**Answer:**

The rendering equation for environment lighting requires integrating BRDF × incoming radiance over hemisphere — too expensive for real-time.

Split-Sum splits this into two pre-computable parts:

1. **Pre-filtered Environment Map**: Convolve cubemap with GGX NDF at different roughness levels, store in mip chain. Sample with `roughness → mipLevel`.

2. **BRDF Integration LUT**: 2D texture indexed by (NdotV, roughness). Stores pre-integrated `scale` and `bias` for Fresnel: `F0 * scale + bias`.

Runtime: `specular = prefilteredColor * (F0 * brdfLUT.x + brdfLUT.y)`

This reduces hemisphere integration to two texture lookups.

### Q6: How does GTAO improve over SSAO?

**Answer:**

SSAO: Random hemisphere sampling → noisy, needs many samples + blur, not physically based.

GTAO: Traces horizon angles in screen space along multiple directions. For each direction, finds maximum elevation angle of occluders. Integrates visible arc analytically using cosine-weighted formula.

Advantages:
- Physically motivated (approximates ground truth)
- Less noise with fewer samples (4 directions × 4 steps vs 32+ random samples)
- Better contact shadows
- Multi-bounce approximation possible
- ~0.5ms at 1080p (comparable to SSAO but better quality)

### Q7: Explain volumetric lighting with Froxel approach

**Answer:**

Froxel = Frustum-aligned Voxel. Divide camera frustum into 3D grid (e.g., 160×90×64). Depth slices use exponential distribution (more detail near camera).

Pipeline:
1. **Inject**: Write fog density and scattering coefficients into 3D texture
2. **Light**: For each froxel, compute in-scattered light from all lights (with shadow)
3. **Integrate**: Front-to-back accumulation using Beer-Lambert law
4. **Apply**: During scene compositing, sample integrated volume at pixel depth

Temporal jittering: offset slice position each frame, blend with history → 4× effective samples.

Advantage over per-pixel ray marching: computation is in low-res 3D space, shared across pixels in same froxel.

### Q8: Forward vs Deferred lighting — when to choose which?

**Answer:**

| Aspect           | Forward             | Deferred               |
| ---------------- | ------------------- | ---------------------- |
| Many lights      | O(objects × lights) | O(pixels × lights)     |
| MSAA             | ✅ Native            | ❌ Expensive            |
| Transparency     | ✅ Natural           | ❌ Separate pass        |
| Bandwidth        | Low (1 RT)          | High (GBuffer)         |
| Material variety | ✅ Unlimited         | Limited by GBuffer     |
| Mobile           | ✅ Preferred         | Possible with FB Fetch |

Choose Forward: mobile, MSAA needed, few lights, transparency-heavy.
Choose Deferred: PC/console, many dynamic lights, complex scenes.
Forward+: Best of both — forward rendering with tiled light culling.

---

## 14. Practice Checklist

```
光影渲染开发检查清单：

基础光照:
□ PBR BRDF implemented correctly (D, F, G terms)
□ Energy conservation verified (kd + ks ≤ 1)
□ Metallic/roughness workflow consistent
□ Linear color space (not gamma)
□ HDR rendering pipeline

阴影系统:
□ Shadow bias tuned (no acne, no peter-panning)
□ CSM cascade splits optimized for scene
□ Shadow swimming fixed (texel snapping)
□ Shadow fade at distance
□ Mobile: 2 cascades max, 1-4 tap PCF

全局光照:
□ Lightmap UV2 properly unwrapped
□ Light probes placed at key positions
□ Reflection probes cover reflective areas
□ Probe blending smooth (no hard transitions)
□ Dynamic objects receive GI via probes

性能优化:
□ Light culling enabled (Forward+ or Clustered)
□ Shadow caster count minimized
□ AO at appropriate resolution
□ Volumetric effects budgeted
□ Mobile bandwidth measured and optimized

质量验证:
□ No light leaking through walls
□ No shadow acne or peter-panning
□ Smooth cascade transitions
□ Correct specular on metals vs dielectrics
□ GI color bleeding looks natural
□ AO not too dark in corners
```