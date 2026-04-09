---
layout: post
title: "自定义地形系统"
subtitle: "流程 · 生命周期 · 优化 · 兼容性适配"
date: 2026-04-09
author: "engineyk"
header-img: "img/post-bg-unity.jpg"
tags:
  - Unity
  - Terrain
  - 渲染
  - 优化
---

# 自定义地形系统 深度解析

## 目录

1. [系统概述](#1-系统概述)
2. [目录结构](#2-目录结构)
3. [核心流程](#3-核心流程)
4. [生命周期](#4-生命周期)
5. [核心优势](#5-核心优势)
6. [优化技术详解](#6-优化技术详解)
7. [兼容性与低端机适配](#7-兼容性与低端机适配)
8. [与 Unity 内置 Terrain 对比](#8-与-unity-内置-terrain-对比)
9. [核心概念速查](#9-核心概念速查)

---

## 1. 系统概述

该地形系统是基于自定义渲染管线（SRP/URP）实现的高性能地形渲染方案，脱离 Unity 内置 `Terrain` 组件，完全自主控制地形的 **分块（Chunk）**、**LOD**、**剔除（Culling）**、**混合（Blending）** 和 **渲染（Rendering）** 流程。

核心目标：
- 支持超大地图（公里级）的实时渲染
- 精细控制 DrawCall 数量与 GPU 带宽
- 在中低端移动设备上保持稳定帧率
- 与自定义 SRP 管线深度集成

---

## 2. 目录结构

```
Runtime/Component/Terrain/
├── TerrainSystem.cs          # 系统主入口，管理全局状态与帧循环
├── TerrainRenderer.cs        # 渲染器，负责提交 DrawCall
├── TerrainChunk.cs           # 地形块数据结构与网格管理
├── TerrainLOD.cs             # LOD 级别计算与切换
├── TerrainCulling.cs         # 视锥剔除 / 遮挡剔除
├── TerrainHeightmap.cs       # 高度图采样与法线生成
├── TerrainSplatmap.cs        # 地表纹理混合（Splat Map）
├── TerrainGrass.cs           # 地形草地集成
├── TerrainWater.cs           # 水面集成（可选）
├── Shaders/
│   ├── Terrain.shader        # 地形主 Shader
│   ├── TerrainLit.hlsl       # 光照计算
│   ├── TerrainSplat.hlsl     # 纹理混合
│   └── TerrainHeightmap.hlsl # 高度图采样
└── Resources/
    ├── TerrainDefaultMat.mat # 默认材质
    └── TerrainConfig.asset   # 全局配置
```

---

## 3. 核心流程

### 3.1 整体帧循环

```
每帧 Update
    │
    ├─► [1] 相机位置更新
    │       └─ 计算相机所在 Chunk 坐标
    │
    ├─► [2] LOD 计算
    │       └─ 根据相机距离为每个 Chunk 分配 LOD 级别
    │
    ├─► [3] 视锥剔除（Culling）
    │       ├─ CPU 粗剔除：AABB vs Frustum
    │       └─ GPU 精剔除：Hi-Z / Occlusion Query（可选）
    │
    ├─► [4] Chunk 动态加载/卸载
    │       ├─ 进入视野 → 加载 Mesh + 纹理
    │       └─ 离开视野 → 放回对象池
    │
    ├─► [5] LOD 过渡处理
    │       └─ 相邻 Chunk LOD 差异 → 接缝修复（Skirt / Morphing）
    │
    └─► [6] 提交渲染
            ├─ 合并同 LOD 级别的 Chunk → GPU Instancing
            ├─ 设置 Heightmap / Splatmap 纹理
            └─ DrawMeshInstanced / DrawMeshInstancedIndirect
```

### 3.2 地形初始化流程

```
TerrainSystem.Initialize()
    │
    ├─► 读取 TerrainConfig（地图尺寸、Chunk 大小、LOD 层数）
    ├─► 生成 Chunk 网格（按 LOD 级别预生成不同精度 Mesh）
    ├─► 上传 Heightmap 到 GPU（RenderTexture / Texture2D）
    ├─► 生成 Splatmap（地表纹理权重图）
    ├─► 初始化对象池（ChunkPool）
    └─► 注册到 SRP RenderPipeline 回调
```

### 3.3 Chunk 网格生成

```csharp
// Each LOD level generates a grid mesh with different vertex density
// LOD0: 64x64 vertices (highest detail)
// LOD1: 32x32 vertices
// LOD2: 16x16 vertices
// LOD3:  8x8  vertices (lowest detail)

public Mesh GenerateChunkMesh(int lodLevel)
{
    int gridSize = chunkVertexCount >> lodLevel; // Bit shift = divide by 2^lod
    float cellSize = chunkWorldSize / gridSize;

    var vertices  = new Vector3[gridSize * gridSize];
    var uvs       = new Vector2[gridSize * gridSize];
    var triangles = new int[(gridSize - 1) * (gridSize - 1) * 6];

    for (int z = 0; z < gridSize; z++)
    for (int x = 0; x < gridSize; x++)
    {
        int idx = z * gridSize + x;
        // Y will be displaced by heightmap in vertex shader
        vertices[idx] = new Vector3(x * cellSize, 0, z * cellSize);
        uvs[idx]      = new Vector2((float)x / (gridSize - 1),
                                    (float)z / (gridSize - 1));
    }
    // ... fill triangles ...
    return BuildMesh(vertices, uvs, triangles);
}
```

---

## 4. 生命周期

### 4.1 系统生命周期

```
┌─────────────────────────────────────────────────────┐
│                  TerrainSystem                       │
│                                                     │
│  Awake()                                            │
│    └─ 读取配置，分配内存，初始化 ChunkPool           │
│                                                     │
│  Start()                                            │
│    └─ 生成所有 LOD Mesh，上传 Heightmap/Splatmap     │
│       注册 SRP BeginCameraRendering 回调             │
│                                                     │
│  Update() ──────────────────────────────────────►  │
│    ├─ 更新相机位置                                   │
│    ├─ 触发 LOD 重新计算（脏标记驱动）                │
│    └─ 触发 Chunk 加载/卸载                           │
│                                                     │
│  OnBeginCameraRendering()                           │
│    ├─ 执行视锥剔除                                   │
│    ├─ 构建渲染批次                                   │
│    └─ 提交 DrawCall                                 │
│                                                     │
│  OnDestroy()                                        │
│    └─ 释放 ComputeBuffer / RenderTexture / Mesh     │
└─────────────────────────────────────────────────────┘
```

### 4.2 Chunk 生命周期

```
[未激活] ──Spawn()──► [激活/加载中]
                           │
                      加载 Mesh + 纹理
                           │
                           ▼
                      [存活/渲染中] ◄──────────────────┐
                           │                           │
                    每帧更新 LOD 级别                   │
                    参与视锥剔除                        │
                    提交渲染批次                        │
                           │                           │
                    离开视野或超出距离                  │
                           │                           │
                           ▼                           │
                      [回收中] ──────────────────────► [对象池]
                                  Recycle()            │
                                                       │
                                              进入视野时重新 Spawn
```

### 4.3 LOD 状态机

```
相机距离 d

d < LOD0_Range  →  LOD 0（最高精度，64x64）
d < LOD1_Range  →  LOD 1（32x32）
d < LOD2_Range  →  LOD 2（16x16）
d < LOD3_Range  →  LOD 3（8x8）
d >= LOD3_Range →  Culled（不渲染）

过渡区间（Transition Zone）：
  相邻 LOD 之间有 10% 重叠区间
  使用 Alpha Blend 或 Vertex Morphing 平滑过渡
```

---

## 5. 核心优势

### 5.1 对比 Unity 内置 Terrain

| 特性 | Unity 内置 Terrain | 自定义地形系统 |
|------|-------------------|---------------|
| DrawCall 控制 | 自动，难以优化 | 完全自主，GPU Instancing |
| LOD 策略 | 固定，不可定制 | 完全可定制 |
| 移动端性能 | 较差 | 针对性优化 |
| 与 SRP 集成 | 有限 | 深度集成 |
| 地图尺寸上限 | ~4km² | 理论无上限 |
| 内存管理 | 自动（不可控） | 手动对象池 |
| Shader 定制 | 受限 | 完全自定义 |
| 草地集成 | 独立系统 | 统一管理 |

### 5.2 性能优势

- **DrawCall 减少 60~80%**：同 LOD 级别的 Chunk 合并为一次 `DrawMeshInstancedIndirect`
- **带宽节省**：LOD 远处 Chunk 使用低精度 Mesh，减少顶点数据传输
- **CPU 开销极低**：视锥剔除使用 Burst Job，主线程几乎零开销
- **内存可控**：对象池复用 Chunk，避免 GC 压力

---

## 6. 优化技术详解

### 6.1 Chunk 分块策略

将地形划分为均匀的正方形 Chunk（通常 64m × 64m），每个 Chunk 独立管理 LOD 和剔除：

```
地图 2048m × 2048m，Chunk 64m × 64m
→ 共 32 × 32 = 1024 个 Chunk
→ 相机视野内通常只有 ~100 个 Chunk 可见
→ 每帧实际渲染 Chunk 数量大幅减少
```

### 6.2 GPU Instancing 批次合并

```csharp
// Group visible chunks by LOD level
var lodGroups = new Dictionary<int, List<Matrix4x4>>();

foreach (var chunk in visibleChunks)
{
    int lod = chunk.CurrentLOD;
    if (!lodGroups.ContainsKey(lod))
        lodGroups[lod] = new List<Matrix4x4>();
    lodGroups[lod].Add(chunk.LocalToWorldMatrix);
}

// Submit one DrawCall per LOD level
foreach (var (lod, matrices) in lodGroups)
{
    Graphics.DrawMeshInstanced(
        lodMeshes[lod],
        0,
        terrainMaterial,
        matrices.ToArray(),
        matrices.Count,
        materialPropertyBlock);
}
// Result: 4 LOD levels = max 4 DrawCalls for entire terrain
```

### 6.3 Heightmap GPU 采样

高度图存储在 GPU 纹理中，顶点着色器直接采样，避免 CPU 端逐顶点计算：

```hlsl
// Terrain.shader - Vertex Stage
sampler2D _HeightMap;
float     _HeightScale;
float     _ChunkOffset;  // Per-instance chunk world offset

VertexOutput TerrainVert(VertexInput v)
{
    VertexOutput o;

    // Sample heightmap in vertex shader (no CPU involvement)
    float2 heightUV = v.uv * _ChunkUVScale + _ChunkUVOffset;
    float  height   = tex2Dlod(_HeightMap, float4(heightUV, 0, 0)).r;

    float3 worldPos = v.positionOS;
    worldPos.y = height * _HeightScale; // Displace vertex vertically

    o.positionCS = TransformObjectToHClip(worldPos);
    o.uv         = v.uv;
    return o;
}
```

### 6.4 Splatmap 纹理混合

使用 RGBA 四通道 Splatmap 控制最多 4 层地表纹理的混合权重：

```hlsl
// TerrainSplat.hlsl
sampler2D _SplatMap;    // RGBA: weight for 4 terrain layers
sampler2D _Layer0Tex;   // Grass
sampler2D _Layer1Tex;   // Rock
sampler2D _Layer2Tex;   // Sand
sampler2D _Layer3Tex;   // Snow

float4 SampleTerrainAlbedo(float2 uv)
{
    float4 splat   = tex2D(_SplatMap, uv);
    float4 layer0  = tex2D(_Layer0Tex, uv * _Layer0Tiling);
    float4 layer1  = tex2D(_Layer1Tex, uv * _Layer1Tiling);
    float4 layer2  = tex2D(_Layer2Tex, uv * _Layer2Tiling);
    float4 layer3  = tex2D(_Layer3Tex, uv * _Layer3Tiling);

    // Weighted blend
    return layer0 * splat.r
         + layer1 * splat.g
         + layer2 * splat.b
         + layer3 * splat.a;
}
```

### 6.5 视锥剔除（Burst Job）

```csharp
[BurstCompile]
public struct TerrainCullingJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<AABB>   ChunkBounds;
    [ReadOnly] public NativeArray<Plane>  FrustumPlanes; // 6 planes
    [WriteOnly] public NativeArray<bool>  Visibility;

    public void Execute(int index)
    {
        AABB bounds = ChunkBounds[index];
        bool visible = true;

        for (int p = 0; p < 6; p++)
        {
            Plane plane = FrustumPlanes[p];
            // Find the positive vertex of AABB relative to plane normal
            float3 positiveVertex = new float3(
                plane.normal.x >= 0 ? bounds.Max.x : bounds.Min.x,
                plane.normal.y >= 0 ? bounds.Max.y : bounds.Min.y,
                plane.normal.z >= 0 ? bounds.Max.z : bounds.Min.z);

            if (math.dot(plane.normal, positiveVertex) + plane.distance < 0)
            {
                visible = false;
                break;
            }
        }
        Visibility[index] = visible;
    }
}
```

### 6.6 LOD 接缝修复（Skirt）

相邻 Chunk LOD 级别不同时，低精度 Chunk 边缘会出现裂缝。通过在 Chunk 边缘添加 **Skirt（裙边）** 顶点向下延伸来遮挡裂缝：

```
高精度 Chunk (LOD0)    低精度 Chunk (LOD1)
▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲    ▲    ▲    ▲    ▲
                  ↕ 裂缝
解决方案：在 LOD1 边缘添加向下的 Skirt 顶点
▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲    ▲    ▲    ▲    ▲
                      ▼    ▼    ▼    ▼  ← Skirt
```

### 6.7 法线贴图生成

法线从 Heightmap 实时计算，避免存储额外的法线纹理：

```hlsl
// Calculate normal from heightmap gradient
float3 CalculateTerrainNormal(sampler2D heightMap, float2 uv, float texelSize)
{
    float hL = tex2D(heightMap, uv + float2(-texelSize, 0)).r;
    float hR = tex2D(heightMap, uv + float2( texelSize, 0)).r;
    float hD = tex2D(heightMap, uv + float2(0, -texelSize)).r;
    float hU = tex2D(heightMap, uv + float2(0,  texelSize)).r;

    float3 normal = normalize(float3(hL - hR, 2.0 * texelSize, hD - hU));
    return normal;
}
```

---

## 7. 兼容性与低端机适配

### 7.1 硬件兼容性要求

| 功能 | 最低要求 | 用途 |
|------|---------|------|
| **Shader Model** | 3.0 | 基础地形渲染 |
| **GPU Instancing** | OpenGL ES 3.0 / Metal | Chunk 批次合并 |
| **Compute Shader** | OpenGL ES 3.1 / Metal | GPU 剔除（可选） |
| **RenderTexture** | OpenGL ES 2.0+ | Heightmap 存储 |
| **Texture2DArray** | OpenGL ES 3.0 | 多层纹理（可选） |

### 7.2 平台支持矩阵

| 平台 | GPU Instancing | Compute Shader | 推荐方案 |
|------|---------------|---------------|----------|
| PC (DX11+) | ✅ | ✅ | 全功能 |
| iOS (Metal) | ✅ | ✅ A9+ | 全功能 |
| Android (GLES 3.1+) | ✅ | ✅ | 全功能 |
| Android (GLES 3.0) | ✅ | ❌ | CPU 剔除 |
| Android (GLES 2.0) | ❌ | ❌ | 降级方案 |
| WebGL 2.0 | ✅ | ❌ | CPU 剔除 |

### 7.3 运行时能力检测

```csharp
public static class TerrainCompatibility
{
    public enum QualityTier { High, Medium, Low, Minimal }

    public static QualityTier Detect()
    {
        bool hasInstancing      = SystemInfo.supportsInstancing;
        bool hasComputeShader   = SystemInfo.supportsComputeShaders;
        int  shaderLevel        = SystemInfo.graphicsShaderLevel;
        int  maxTextureSize     = SystemInfo.maxTextureSize;

        if (hasInstancing && hasComputeShader && shaderLevel >= 45)
            return QualityTier.High;

        if (hasInstancing && shaderLevel >= 30)
            return QualityTier.Medium;

        if (shaderLevel >= 25)
            return QualityTier.Low;

        return QualityTier.Minimal;
    }
}
```

### 7.4 分级质量配置

```csharp
[Serializable]
public class TerrainQualityConfig
{
    public int   MaxVisibleChunks;   // Max chunks rendered per frame
    public int   MaxLODLevels;       // Number of LOD levels
    public int   ChunkGridSize;      // Vertex count per chunk side
    public float LOD0Range;          // Distance for highest LOD
    public bool  UseGPUCulling;      // GPU Hi-Z culling
    public bool  UseGPUInstancing;   // DrawMeshInstancedIndirect
    public int   SplatLayerCount;    // Number of terrain texture layers
    public bool  EnableNormalMap;    // Per-pixel normal mapping
    public bool  EnableGrass;        // Grass rendering
}

public static TerrainQualityConfig GetConfig(TerrainCompatibility.QualityTier tier)
{
    return tier switch
    {
        QualityTier.High => new TerrainQualityConfig
        {
            MaxVisibleChunks = 256,
            MaxLODLevels     = 4,
            ChunkGridSize    = 64,
            LOD0Range        = 100f,
            UseGPUCulling    = true,
            UseGPUInstancing = true,
            SplatLayerCount  = 4,
            EnableNormalMap  = true,
            EnableGrass      = true,
        },
        QualityTier.Medium => new TerrainQualityConfig
        {
            MaxVisibleChunks = 128,
            MaxLODLevels     = 3,
            ChunkGridSize    = 32,
            LOD0Range        = 60f,
            UseGPUCulling    = false,  // CPU culling instead
            UseGPUInstancing = true,
            SplatLayerCount  = 3,
            EnableNormalMap  = true,
            EnableGrass      = true,
        },
        QualityTier.Low => new TerrainQualityConfig
        {
            MaxVisibleChunks = 64,
            MaxLODLevels     = 2,
            ChunkGridSize    = 16,
            LOD0Range        = 40f,
            UseGPUCulling    = false,
            UseGPUInstancing = false,  // DrawMeshInstanced (1023 limit)
            SplatLayerCount  = 2,
            EnableNormalMap  = false,  // Vertex normal only
            EnableGrass      = false,
        },
        _ => new TerrainQualityConfig   // Minimal
        {
            MaxVisibleChunks = 32,
            MaxLODLevels     = 1,
            ChunkGridSize    = 8,
            LOD0Range        = 30f,
            UseGPUCulling    = false,
            UseGPUInstancing = false,
            SplatLayerCount  = 1,
            EnableNormalMap  = false,
            EnableGrass      = false,
        },
    };
}
```

### 7.5 GPU Instancing 不支持时的降级方案

当设备不支持 GPU Instancing（GLES 2.0 等）时，退回到逐 Chunk 单独 DrawCall：

```csharp
public void RenderChunks(List<TerrainChunk> visibleChunks)
{
    if (SystemInfo.supportsInstancing)
    {
        // High-end: batch by LOD level, one DrawCall per LOD
        RenderWithInstancing(visibleChunks);
    }
    else
    {
        // Low-end: one DrawCall per chunk (more DrawCalls, but compatible)
        RenderWithoutInstancing(visibleChunks);
    }
}

private void RenderWithoutInstancing(List<TerrainChunk> chunks)
{
    foreach (var chunk in chunks)
    {
        // Set per-chunk properties manually
        _mpb.SetVector("_ChunkOffset", chunk.WorldOffset);
        _mpb.SetVector("_ChunkUVOffset", chunk.HeightmapUVOffset);
        _mpb.SetFloat("_ChunkUVScale", chunk.HeightmapUVScale);

        Graphics.DrawMesh(
            _lodMeshes[chunk.CurrentLOD],
            chunk.WorldMatrix,
            _terrainMaterial,
            0,
            null,
            0,
            _mpb);
    }
}
```

### 7.6 Heightmap 精度降级

低端机使用低精度 Heightmap 减少内存和带宽：

```csharp
public Texture2D CreateHeightmap(float[,] heights, QualityTier tier)
{
    // High-end: 16-bit precision (R16 format)
    // Low-end:  8-bit precision (R8 format, less memory)
    TextureFormat format = tier >= QualityTier.Medium
        ? TextureFormat.R16
        : TextureFormat.R8;

    // High-end: full resolution 2048x2048
    // Low-end:  half resolution 1024x1024
    int resolution = tier >= QualityTier.Medium ? 2048 : 1024;

    var tex = new Texture2D(resolution, resolution, format, false);
    // ... fill data ...
    tex.Apply();
    return tex;
}
```

### 7.7 Splatmap 层数降级

```csharp
// High-end: 4 layers (RGBA splatmap)
// Medium:   3 layers (RGB splatmap, A unused)
// Low-end:  2 layers (RG splatmap)
// Minimal:  1 layer  (no blending, single texture)

public string GetTerrainShaderVariant(int splatLayerCount)
{
    return splatLayerCount switch
    {
        4 => "Terrain/Lit_4Layer",
        3 => "Terrain/Lit_3Layer",
        2 => "Terrain/Lit_2Layer",
        _ => "Terrain/Lit_1Layer",
    };
}
```

### 7.8 低端机优化策略汇总

| 优化手段 | 高端机 | 中端机 | 低端机 | 极低端 |
|---------|--------|--------|--------|--------|
| GPU Instancing | ✅ Indirect | ✅ Instanced | ❌ DrawMesh | ❌ DrawMesh |
| 视锥剔除 | GPU Hi-Z | CPU Burst | CPU 单线程 | CPU 简化 |
| LOD 级别数 | 4 | 3 | 2 | 1 |
| Chunk 网格精度 | 64×64 | 32×32 | 16×16 | 8×8 |
| Heightmap 精度 | R16 2048² | R16 2048² | R8 1024² | R8 512² |
| Splatmap 层数 | 4 | 3 | 2 | 1 |
| 法线贴图 | ✅ | ✅ | ❌ | ❌ |
| 草地渲染 | ✅ | ✅ | ❌ | ❌ |
| 最大可见 Chunk | 256 | 128 | 64 | 32 |

---

## 8. 与 Unity 内置 Terrain 对比

### 8.1 性能对比

| 指标 | Unity 内置 Terrain | 自定义地形系统 |
|------|-------------------|---------------|
| DrawCall（1km²地图） | ~20~50 | ~4（按LOD分组）|
| 顶点数（全视野） | 固定高精度 | 按距离动态调整 |
| CPU 剔除开销 | 较高 | Burst Job，极低 |
| 内存占用 | 较高（不可控） | 可精确控制 |
| 移动端帧率 | 30~45 FPS | 55~60 FPS |

### 8.2 功能对比

| 功能 | Unity 内置 Terrain | 自定义地形系统 |
|------|-------------------|---------------|
| 地图尺寸 | 建议 ≤ 4km² | 理论无上限 |
| LOD 定制 | 有限 | 完全自定义 |
| Shader 定制 | 受限 | 完全自由 |
| 与 SRP 集成 | 部分支持 | 深度集成 |
| 草地系统 | 独立，性能差 | 统一管理 |
| 运行时编辑 | 支持 | 需自行实现 |
| 物理碰撞 | 内置 | 需自行实现 |

---

## 9. 核心概念速查

| 概念 | 说明 |
|------|------|
| **Chunk** | 地形的基本渲染单元，固定尺寸的正方形网格 |
| **LOD** | Level of Detail，根据距离降低网格精度 |
| **Heightmap** | 存储地形高度信息的灰度纹理 |
| **Splatmap** | 存储地表纹理混合权重的 RGBA 纹理 |
| **Skirt** | 防止 LOD 接缝的裙边顶点 |
| **GPU Instancing** | 一次 DrawCall 渲染多个相同 Mesh 的实例 |
| **Hi-Z Culling** | 利用深度层级图进行 GPU 端遮挡剔除 |
| **Burst Job** | Unity 的高性能 C# 编译器，用于并行 CPU 计算 |
| **DrawMeshInstancedIndirect** | GPU 驱动的间接绘制，DrawCall 参数由 GPU Buffer 提供 |
| **Vertex Morphing** | LOD 切换时顶点平滑过渡，避免突变 |
