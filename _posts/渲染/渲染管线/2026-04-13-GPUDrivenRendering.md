---
layout:     post
title:      GPU Driven Rendering
subtitle:   Indirect Draw、GPU Culling、Cluster/Meshlet、Hi-Z、Two-Phase OC、Nanite 架构
date:       2026-04-13
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - 渲染
    - 优化
---

# GPU Driven Rendering

---

## 一、核心思想

```
Traditional Rendering:                GPU Driven Rendering:

  CPU                  GPU              CPU              GPU
  ┌──────────┐                          ┌──────────┐
  │ Traverse │                          │ Upload   │
  │ Scene    │                          │ Scene    │
  │ Graph    │                          │ Data     │
  ├──────────┤                          │ (once)   │
  │ Frustum  │                          └────┬─────┘
  │ Cull     │                               │
  ├──────────┤                               ▼
  │ Occlusion│                          ┌──────────┐
  │ Cull     │                          │ GPU      │
  ├──────────┤                          │ Culling  │
  │ Sort     │                          ├──────────┤
  ├──────────┤                          │ GPU      │
  │ Set State│                          │ Compact  │
  │ Per Draw │                          ├──────────┤
  ├──────────┤         ┌──────────┐     │ Indirect │
  │ DrawCall │────────▶│ Vertex   │     │ Draw     │────▶ Rendering
  │ DrawCall │────────▶│ Fragment │     └──────────┘
  │ DrawCall │────────▶│ ...      │
  │ ...×1000 │         └──────────┘     1 Indirect DrawCall
  └──────────┘                          renders thousands of objects

Key Insight:
  Move per-object work (cull, sort, draw setup) from CPU → GPU
  CPU submits O(1) commands instead of O(N)
```

### 为什么需要 GPU Driven？

| 问题               | 传统管线                  | GPU Driven                      |
| ------------------ | ------------------------- | ------------------------------- |
| **Draw Call 瓶颈** | CPU 逐个提交，驱动开销大  | 1 次 Indirect Draw 渲染数千物体 |
| **CPU-GPU 同步**   | CPU 等 GPU 查询结果做剔除 | GPU 自行剔除，无需回读          |
| **场景规模**       | 数千物体就吃力            | 百万级三角形场景                |
| **Culling 精度**   | 物体级别                  | 三角形/Cluster 级别             |
| **CPU 占用**       | 大量时间在渲染提交        | CPU 解放给 Gameplay/Physics     |

---

## 二、基础设施

### 2.1 Indirect Draw

```
Traditional Draw:
  CPU fills command buffer with per-draw parameters:
  Draw(vertexCount=36, instanceCount=1, firstVertex=0, ...)
  Draw(vertexCount=24, instanceCount=1, firstVertex=36, ...)
  Draw(vertexCount=60, instanceCount=1, firstVertex=60, ...)
  ... × N draw calls

Indirect Draw:
  GPU reads draw parameters from a GPU buffer:

  ┌───────────────────────────────────────────────────┐
  │              Indirect Argument Buffer             │
  │  (GPU Buffer, written by Compute Shader)          │
  ├─────────────┬─────────────┬─────────────┬─────────┤
  │ Draw Args 0 │ Draw Args 1 │ Draw Args 2 │  ...    │
  │ vertexCount │ vertexCount │ vertexCount │         │
  │ instCount   │ instCount   │ instCount   │         │
  │ firstVert   │ firstVert   │ firstVert   │         │
  │ firstInst   │ firstInst   │ firstInst   │         │
  └─────────────┴─────────────┴─────────────┴─────────┘

  CPU: DrawIndirect(argBuffer, drawCount)     ← 1 API call
  or:  DrawIndexedIndirect(argBuffer, count)
  or:  MultiDrawIndirect(argBuffer, count)    ← best: 1 call, N draws
```

#### API 对比

| API        | 函数                                     | 说明                          |
| ---------- | ---------------------------------------- | ----------------------------- |
| **Vulkan** | `vkCmdDrawIndexedIndirect`               | 支持 Multi-Draw               |
| **Vulkan** | `vkCmdDrawIndexedIndirectCount`          | Draw count 也在 GPU buffer 中 |
| **D3D12**  | `ExecuteIndirect`                        | 最灵活，可切换 root constants |
| **D3D11**  | `DrawIndexedInstancedIndirect`           | 单次 Indirect                 |
| **Metal**  | `drawIndexedPrimitives(indirectBuffer:)` | ICB (Indirect Command Buffer) |
| **OpenGL** | `glMultiDrawElementsIndirect`            | Multi-Draw                    |

```hlsl
// Indirect Draw Arguments structure (D3D12 / Vulkan)
struct DrawIndexedIndirectArgs
{
    uint indexCountPerInstance;
    uint instanceCount;
    uint startIndexLocation;
    int  baseVertexLocation;
    uint startInstanceLocation;
};

// Compute shader fills indirect args
[numthreads(64, 1, 1)]
void CSBuildIndirectArgs(uint3 id : SV_DispatchThreadID)
{
    uint meshIndex = id.x;
    if (meshIndex >= totalMeshCount) return;
    
    MeshInfo mesh = meshInfoBuffer[meshIndex];
    
    // After culling, only visible meshes get valid args
    if (IsVisible(meshIndex))
    {
        uint drawIndex;
        InterlockedAdd(drawCountBuffer[0], 1, drawIndex);
        
        indirectArgsBuffer[drawIndex].indexCountPerInstance = mesh.indexCount;
        indirectArgsBuffer[drawIndex].instanceCount = 1;
        indirectArgsBuffer[drawIndex].startIndexLocation = mesh.indexOffset;
        indirectArgsBuffer[drawIndex].baseVertexLocation = mesh.vertexOffset;
        indirectArgsBuffer[drawIndex].startInstanceLocation = drawIndex;
    }
}
```

### 2.2 GPU Scene Buffer

```
All scene data lives on GPU:

┌─────────────────────────────────────────────────────────┐
│                    GPU Scene Buffers                    │
├──────────────────┬──────────────────────────────────────┤
│ Instance Buffer  │ [Transform, AABB, MaterialID, ...]   │
│                  │ Per-instance data for all objects    │
├──────────────────┼──────────────────────────────────────┤
│ Mesh Data Buffer │ [Vertex, Index, MeshInfo, ...]       │
│                  │ All meshes in one big buffer         │
├──────────────────┼──────────────────────────────────────┤
│ Material Buffer  │ [Albedo, Roughness, TexIndices, ...] │
│                  │ Bindless material parameters         │
├──────────────────┼──────────────────────────────────────┤
│ Texture Array /  │ All textures accessible via index    │
│ Bindless Textures│ No per-draw texture binding          │
├──────────────────┼──────────────────────────────────────┤
│ Visibility Buffer│ Culling results (bitfield or list)   │
├──────────────────┼──────────────────────────────────────┤
│ Indirect Args    │ Draw parameters (filled by compute)  │
└──────────────────┴──────────────────────────────────────┘

Vertex Shader reads instance data via SV_InstanceID:
  float4x4 world = instanceBuffer[instanceID].transform;
  uint matID = instanceBuffer[instanceID].materialID;

Pixel Shader reads material via materialID:
  float4 albedo = textureArray.Sample(sampler, uv, matID);
```

### 2.3 Bindless Resources

```
Traditional Binding:              Bindless:

  Slot 0: Texture A                All textures in descriptor heap
  Slot 1: Texture B                Shader accesses by index:
  Slot 2: Texture C                  tex = textures[materialID];
  ... must rebind per draw

D3D12: Descriptor Heap + Root Descriptor Table
Vulkan: Descriptor Indexing (VK_EXT_descriptor_indexing)
Metal:  Argument Buffers
OpenGL: GL_ARB_bindless_texture

Benefits:
- No per-draw binding changes
- All materials accessible in one draw
- Enables true GPU-driven pipeline
```

```hlsl
// HLSL Bindless example (SM 6.6 / D3D12)
struct MaterialData
{
    uint albedoTexIndex;
    uint normalTexIndex;
    uint roughnessTexIndex;
    float4 baseColor;
};

StructuredBuffer<MaterialData> materials : register(t0);
Texture2D textures[] : register(t1);  // unbounded array
SamplerState linearSampler : register(s0);

float4 PSMain(VSOutput input) : SV_Target
{
    uint matID = instanceBuffer[input.instanceID].materialID;
    MaterialData mat = materials[matID];
    
    float4 albedo = textures[mat.albedoTexIndex].Sample(linearSampler, input.uv);
    float3 normal = textures[mat.normalTexIndex].Sample(linearSampler, input.uv).xyz;
    
    return albedo * mat.baseColor;
}
```

---

## 三、GPU Culling

### 3.1 Culling 层级

```
┌─────────────────────────────────────────────────────┐
│                  Culling Pipeline                   │
│                                                     │
│  ┌───────────────┐                                  │
│  │ Frustum Cull  │  Reject objects outside view     │
│  │  (per-object) │  ~50-70% rejected                │
│  └──────┬────────┘                                  │
│         ▼                                           │
│  ┌───────────────┐                                  │
│  │ Hi-Z Occlusion│  Reject objects behind others    │
│  │  Cull         │  ~20-40% additional rejected     │
│  │  (per-object) │                                  │
│  └──────┬────────┘                                  │
│         ▼                                           │
│  ┌───────────────┐                                  │
│  │ Cluster/      │  Reject invisible clusters       │
│  │ Meshlet Cull  │  Fine-grained culling            │
│  │  (per-cluster)│                                  │
│  └──────┬────────┘                                  │
│         ▼                                           │
│  ┌───────────────┐                                  │
│  │ Triangle Cull │  Backface, degenerate, subpixel  │
│  │  (per-tri)    │  In mesh shader or compute       │
│  └──────┬────────┘                                  │
│         ▼                                           │
│  ┌──────────────┐                                   │
│  │ Rasterize    │  Only truly visible geometry      │
│  └──────────────┘                                   │
└─────────────────────────────────────────────────────┘
```

### 3.2 GPU Frustum Culling

```hlsl
// Frustum culling in compute shader
// Test AABB against 6 frustum planes

bool FrustumCullAABB(float3 center, float3 extents, float4 planes[6])
{
    [unroll]
    for (int i = 0; i < 6; i++)
    {
        float3 normal = planes[i].xyz;
        float dist = planes[i].w;
        
        // Compute the projection interval radius of AABB onto plane normal
        float r = dot(extents, abs(normal));
        
        // Compute distance of AABB center from plane
        float s = dot(normal, center) + dist;
        
        // If AABB is entirely behind the plane, it's outside the frustum
        if (s + r < 0.0)
            return false;  // culled
    }
    return true;  // visible
}

[numthreads(64, 1, 1)]
void CSFrustumCull(uint3 id : SV_DispatchThreadID)
{
    uint instanceID = id.x;
    if (instanceID >= instanceCount) return;
    
    InstanceData inst = instanceBuffer[instanceID];
    
    // Transform AABB to world space
    float3 worldCenter = mul(inst.transform, float4(inst.aabbCenter, 1.0)).xyz;
    float3 worldExtents = abs(mul((float3x3)inst.transform, inst.aabbExtents));
    
    if (FrustumCullAABB(worldCenter, worldExtents, frustumPlanes))
    {
        // Mark as visible
        uint index;
        InterlockedAdd(visibleCount[0], 1, index);
        visibleInstances[index] = instanceID;
    }
}
```

### 3.3 Hi-Z Occlusion Culling

```
Hi-Z (Hierarchical-Z) Buffer:

  Full resolution depth → Mip chain (max depth per 2×2 block)

  Mip 0 (1920×1080):  per-pixel depth
  Mip 1 (960×540):    max of each 2×2 block
  Mip 2 (480×270):    max of each 2×2 block of Mip 1
  Mip 3 (240×135):    ...
  ...

  ┌────────────────────────────────┐
  │ Mip 0: Full depth buffer       │
  │ ████████████████████████████   │
  ├────────────────┐               │
  │ Mip 1: 1/2     │               │
  │ ████████████   │               │
  ├────────┐       │               │
  │ Mip 2  │       │               │
  │ ██████ │       │               │
  ├────┐   │       │               │
  │Mip3│   │       │               │
  ├────┘   │       │               │
  │        └───────┘               │
  │                                │
  └────────────────────────────────┘

Occlusion Test:
  1. Project object's AABB to screen space
  2. Compute screen-space bounding rect
  3. Select appropriate mip level based on rect size
  4. Sample Hi-Z at that mip level
  5. If object's nearest depth > Hi-Z depth → occluded
```

```hlsl
// Hi-Z Mip Chain Generation (Compute Shader)
// Each mip takes max of 2×2 block from previous mip

Texture2D<float> inputDepth : register(t0);
RWTexture2D<float> outputMip : register(u0);

[numthreads(8, 8, 1)]
void CSBuildHiZ(uint3 id : SV_DispatchThreadID)
{
    uint2 srcCoord = id.xy * 2;
    
    float d0 = inputDepth[srcCoord + uint2(0, 0)];
    float d1 = inputDepth[srcCoord + uint2(1, 0)];
    float d2 = inputDepth[srcCoord + uint2(0, 1)];
    float d3 = inputDepth[srcCoord + uint2(1, 1)];
    
    // For reversed-Z: use min (closest depth is largest value)
    // For standard-Z: use max (farthest depth)
    #if REVERSED_Z
        float maxDepth = min(min(d0, d1), min(d2, d3));
    #else
        float maxDepth = max(max(d0, d1), max(d2, d3));
    #endif
    
    outputMip[id.xy] = maxDepth;
}

// Hi-Z Occlusion Test
bool HiZOcclusionTest(float3 aabbMin, float3 aabbMax, 
                       float4x4 viewProj, Texture2D<float> hiZBuffer)
{
    // 1. Project 8 corners of AABB to clip space
    float2 screenMin = float2(1, 1);
    float2 screenMax = float2(-1, -1);
    float nearestDepth = 1.0;  // farthest in [0,1]
    
    [unroll]
    for (int i = 0; i < 8; i++)
    {
        float3 corner = float3(
            (i & 1) ? aabbMax.x : aabbMin.x,
            (i & 2) ? aabbMax.y : aabbMin.y,
            (i & 4) ? aabbMax.z : aabbMin.z
        );
        
        float4 clip = mul(viewProj, float4(corner, 1.0));
        float3 ndc = clip.xyz / clip.w;
        
        screenMin = min(screenMin, ndc.xy);
        screenMax = max(screenMax, ndc.xy);
        nearestDepth = min(nearestDepth, ndc.z);  // reversed-Z: min = nearest
    }
    
    // 2. Convert NDC to UV [0,1]
    float2 uvMin = screenMin * 0.5 + 0.5;
    float2 uvMax = screenMax * 0.5 + 0.5;
    
    // 3. Select mip level based on screen-space size
    float2 screenSize = (uvMax - uvMin) * float2(screenWidth, screenHeight);
    float mipLevel = ceil(log2(max(screenSize.x, screenSize.y)));
    mipLevel = clamp(mipLevel, 0, maxMipLevel);
    
    // 4. Sample Hi-Z at selected mip
    float hiZDepth = hiZBuffer.SampleLevel(pointSampler, (uvMin + uvMax) * 0.5, mipLevel);
    
    // 5. Compare (reversed-Z: nearest = larger value)
    #if REVERSED_Z
        return nearestDepth > hiZDepth;  // visible if nearer than Hi-Z
    #else
        return nearestDepth < hiZDepth;  // visible if nearer than Hi-Z
    #endif
}
```

### 3.4 Two-Phase Occlusion Culling

```
Problem: Hi-Z needs last frame's depth, but camera moved!
  → Some objects incorrectly culled (disocclusion artifacts)

Solution: Two-Phase Occlusion Culling

┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Phase 1: "Safe" pass                                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 1. Reproject last frame's Hi-Z to current frame     │    │
│  │ 2. Frustum cull ALL objects                         │    │
│  │ 3. Hi-Z test against reprojected depth              │    │
│  │ 4. Render objects that were visible LAST frame      │    │
│  │    AND pass Hi-Z test this frame                    │    │
│  │ 5. Build NEW Hi-Z from Phase 1 depth                │    │
│  └─────────────────────────────────────────────────────┘    │
│                          │                                  │
│                          ▼                                  │
│  Phase 2: "Catch-up" pass                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 1. Test objects that were CULLED in Phase 1         │    │
│  │    against the NEW Hi-Z from Phase 1                │    │
│  │ 2. Render newly visible objects (disoccluded)       │    │
│  │ 3. Update Hi-Z (optional, for next frame)           │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  Result: No popping artifacts, correct occlusion            │
└─────────────────────────────────────────────────────────────┘

Timeline:
  Frame N-1: Render → Depth → Hi-Z(N-1)
  Frame N:
    Phase 1: Cull with Hi-Z(N-1) → Render visible → Hi-Z(N) partial
    Phase 2: Cull rejected with Hi-Z(N) partial → Render newly visible
```

```
Pseudo-code:

// Phase 1
ComputeShader: FrustumCull(allObjects)
ComputeShader: HiZCull(frustumVisible, lastFrameHiZ) → phase1Visible, phase1Rejected
Draw: Render(phase1Visible)
ComputeShader: BuildHiZ(currentDepth) → currentHiZ

// Phase 2  
ComputeShader: HiZCull(phase1Rejected, currentHiZ) → phase2Visible
Draw: Render(phase2Visible)
// Optionally update Hi-Z again
```

---

## 四、Cluster / Meshlet Rendering

### 4.1 概念

```
Traditional: Entire mesh as one draw unit
  → Coarse culling (object-level only)
  → Waste rendering hidden parts of large meshes

Cluster/Meshlet: Split mesh into small chunks (~64-128 triangles)
  → Fine-grained culling per cluster
  → Only render visible clusters

Mesh Splitting:
  ┌─────────────────────────────────────┐
  │          Original Mesh              │
  │    ┌─────┬─────┬─────┬─────┐        │
  │    │ C0  │ C1  │ C2  │ C3  │        │
  │    ├─────┼─────┼─────┼─────┤        │
  │    │ C4  │ C5  │ C6  │ C7  │        │
  │    ├─────┼─────┼─────┼─────┤        │
  │    │ C8  │ C9  │ C10 │ C11 │        │
  │    └─────┴─────┴─────┴─────┘        │
  └─────────────────────────────────────┘

  Each cluster Ci:
  - 64-128 triangles
  - Has its own bounding sphere/cone
  - Can be independently culled
  - Optimal for mesh shader workgroups

Meshlet Structure:
  struct Meshlet {
      uint vertexOffset;     // into shared vertex buffer
      uint vertexCount;      // typically ≤ 64
      uint triangleOffset;   // into shared index buffer
      uint triangleCount;    // typically ≤ 128
      float3 center;         // bounding sphere center
      float radius;          // bounding sphere radius
      float3 coneAxis;       // normal cone axis
      float coneCutoff;      // normal cone cutoff (backface culling)
  };
```

### 4.2 Meshlet 生成

```
Meshlet Generation Algorithm (meshoptimizer):

1. Start with a seed triangle
2. Greedily add adjacent triangles that:
   a. Share vertices with current meshlet (maximize vertex reuse)
   b. Don't exceed vertex limit (64) or triangle limit (128)
3. When meshlet is full, start a new one
4. Compute bounding sphere and normal cone for each meshlet

Vertex Reuse:
  Good meshlet:  64 vertices, 128 triangles → 2.0 tri/vert ratio
  Ideal:         ~1.8-2.0 triangles per vertex
  Poor:          < 1.5 triangles per vertex

Normal Cone:
  - Cone that bounds all triangle normals in the meshlet
  - If cone doesn't face camera → entire meshlet is backfacing
  - Enables cluster-level backface culling

  cone_axis = average of all triangle normals (normalized)
  cone_cutoff = max angle between cone_axis and any triangle normal
  
  Backface test:
    if (dot(cone_axis, view_dir) > cone_cutoff)
        → all triangles face away → cull entire meshlet
```

```cpp
// Using meshoptimizer library
#include <meshoptimizer.h>

const size_t maxVertices = 64;
const size_t maxTriangles = 128;
const float coneWeight = 0.5f;

size_t maxMeshlets = meshopt_buildMeshletsBound(
    indexCount, maxVertices, maxTriangles);

std::vector<meshopt_Meshlet> meshlets(maxMeshlets);
std::vector<unsigned int> meshletVertices(maxMeshlets * maxVertices);
std::vector<unsigned char> meshletTriangles(maxMeshlets * maxTriangles * 3);

size_t meshletCount = meshopt_buildMeshlets(
    meshlets.data(), meshletVertices.data(), meshletTriangles.data(),
    indices, indexCount, vertices, vertexCount, sizeof(Vertex),
    maxVertices, maxTriangles, coneWeight);

// Compute bounds for each meshlet
for (size_t i = 0; i < meshletCount; i++) {
    meshopt_Bounds bounds = meshopt_computeMeshletBounds(
        &meshletVertices[meshlets[i].vertex_offset],
        &meshletTriangles[meshlets[i].triangle_offset],
        meshlets[i].triangle_count,
        vertices, vertexCount, sizeof(Vertex));
    
    // bounds.center, bounds.radius → bounding sphere
    // bounds.cone_axis, bounds.cone_cutoff → normal cone
}
```

### 4.3 Mesh Shader Pipeline

```
Traditional Pipeline:          Mesh Shader Pipeline:

  Input Assembler                 Task Shader (optional)
       │                              │
  Vertex Shader                  Mesh Shader
       │                              │
  Hull Shader (opt)              Rasterizer
       │                              │
  Domain Shader (opt)            Pixel Shader
       │
  Geometry Shader (opt)
       │
  Rasterizer
       │
  Pixel Shader

Task Shader (Amplification Shader in D3D12):
  - Runs per-meshlet workgroup
  - Decides which meshlets to emit
  - Cluster-level culling here
  - Outputs: meshlet indices to process

Mesh Shader:
  - Runs per-meshlet workgroup (32/64 threads)
  - Reads vertices and indices from buffers
  - Outputs: primitives and vertices directly
  - No Input Assembler needed
  - Can do per-triangle culling
```

```hlsl
// Mesh Shader example (HLSL SM 6.5+)

struct MeshletInfo
{
    uint vertexOffset;
    uint vertexCount;
    uint triangleOffset;
    uint triangleCount;
    float3 center;
    float radius;
    float3 coneAxis;
    float coneCutoff;
};

// Task Shader: cluster-level culling
[numthreads(32, 1, 1)]
void TaskMain(uint gtid : SV_GroupThreadID, uint gid : SV_GroupID)
{
    uint meshletIndex = gid * 32 + gtid;
    bool visible = false;
    
    if (meshletIndex < meshletCount)
    {
        MeshletInfo meshlet = meshletBuffer[meshletIndex];
        
        // Frustum cull
        visible = FrustumCullSphere(meshlet.center, meshlet.radius);
        
        // Normal cone cull (backface)
        if (visible)
        {
            float3 viewDir = normalize(meshlet.center - cameraPos);
            visible = dot(meshlet.coneAxis, viewDir) <= meshlet.coneCutoff;
        }
        
        // Hi-Z occlusion cull
        if (visible)
        {
            visible = HiZTestSphere(meshlet.center, meshlet.radius);
        }
    }
    
    // Compact visible meshlets
    uint visibleCount = WavePrefixCountBits(WaveActiveBallot(visible));
    // Dispatch mesh shader for visible meshlets
    DispatchMesh(visibleCount, 1, 1, payload);
}

// Mesh Shader: output vertices and triangles
[numthreads(128, 1, 1)]
[outputtopology("triangle")]
void MeshMain(
    uint gtid : SV_GroupThreadID,
    uint gid : SV_GroupID,
    out vertices VertexOutput verts[64],
    out indices uint3 tris[128])
{
    uint meshletIndex = payload.meshletIndices[gid];
    MeshletInfo meshlet = meshletBuffer[meshletIndex];
    
    SetMeshOutputCounts(meshlet.vertexCount, meshlet.triangleCount);
    
    // Output vertices
    if (gtid < meshlet.vertexCount)
    {
        uint vertexIndex = meshletVertices[meshlet.vertexOffset + gtid];
        Vertex v = vertexBuffer[vertexIndex];
        verts[gtid].position = mul(viewProj, mul(world, float4(v.pos, 1.0)));
        verts[gtid].normal = mul((float3x3)world, v.normal);
        verts[gtid].uv = v.uv;
    }
    
    // Output triangles
    if (gtid < meshlet.triangleCount)
    {
        uint offset = meshlet.triangleOffset + gtid * 3;
        tris[gtid] = uint3(
            meshletTriangles[offset],
            meshletTriangles[offset + 1],
            meshletTriangles[offset + 2]
        );
    }
}
```

---

## 五、Visibility Buffer (V-Buffer)

### 5.1 概念

```
Traditional Deferred:              Visibility Buffer:

  G-Buffer:                         V-Buffer:
  ┌──────────┐                      ┌───────────┐
  │ Albedo   │ RGBA8  (32 bpp)      │TriangleID │ R32UI (32 bpp)
  ├──────────┤                      │+InstanceID│ or R32G32UI
  │ Normal   │ RG16F  (32 bpp)      └───────────┘
  ├──────────┤                        Total: 4-8 bytes/pixel
  │ Roughness│ R8     (8 bpp)       
  │ Metallic │                       vs G-Buffer: 12-20+ bytes/pixel
  ├──────────┤
  │ Depth    │ D32F   (32 bpp)
  └──────────┘
  Total: ~16-20+ bytes/pixel

V-Buffer stores WHAT triangle is visible at each pixel.
Material evaluation happens in a full-screen compute pass.

V-Buffer pixel format:
  Bits [31:24]: DrawCall/Instance ID (8 bits → 256 instances)
  Bits [23:0]:  Triangle ID (24 bits → 16M triangles)
  
  Or use 64-bit: uint2 → more instances + triangles
```

### 5.2 Pipeline

```
Visibility Buffer Pipeline:

  ┌──────────────────────────────────────────────────┐
  │ 1. GPU Culling (Compute)                         │
  │    Frustum + Hi-Z + Cluster cull                 │
  └──────────────────┬───────────────────────────────┘
                     ▼
  ┌──────────────────────────────────────────────────┐
  │ 2. Visibility Pass (Rasterize)                   │
  │    Render all visible meshlets                   │
  │    Output: TriangleID + InstanceID per pixel     │
  │    Minimal vertex shader, trivial pixel shader   │
  │    (just write IDs, no material evaluation)      │
  └──────────────────┬───────────────────────────────┘
                     ▼
  ┌──────────────────────────────────────────────────┐
  │ 3. Material Classification (Compute)             │
  │    Group pixels by material type                 │
  │    Build per-material pixel lists                │
  │    (for efficient wave occupancy)                │
  └──────────────────┬───────────────────────────────┘
                     ▼
  ┌──────────────────────────────────────────────────┐
  │ 4. Deferred Material Evaluation (Compute)        │
  │    For each pixel:                               │
  │    a. Read TriangleID + InstanceID from V-Buffer │
  │    b. Fetch triangle vertices                    │
  │    c. Compute barycentrics from screen position  │
  │    d. Interpolate attributes (UV, normal, etc.)  │
  │    e. Sample textures, evaluate material         │
  │    f. Compute lighting                           │
  │    g. Write final color                          │
  └──────────────────────────────────────────────────┘

Advantages:
  ✅ Minimal bandwidth in rasterization pass
  ✅ Decouples geometry from shading
  ✅ Perfect for GPU-driven (no material sorting needed)
  ✅ Handles complex materials without G-Buffer bloat
  ✅ Enables variable rate shading naturally

Disadvantages:
  ❌ Requires barycentric computation in compute
  ❌ Texture sampling with computed UVs (no HW derivatives)
  ❌ Need to handle MSAA differently
  ❌ More complex pipeline setup
```

```hlsl
// Visibility Buffer - Rasterization Pass
struct VSOutput
{
    float4 position : SV_Position;
    nointerpolation uint triangleID : TRIANGLE_ID;
    nointerpolation uint instanceID : INSTANCE_ID;
};

VSOutput VSMain(uint vertexID : SV_VertexID, uint instanceID : SV_InstanceID)
{
    VSOutput output;
    // Minimal vertex shader - just transform position
    float3 pos = vertexBuffer[vertexID].position;
    float4x4 world = instanceBuffer[instanceID].transform;
    output.position = mul(viewProj, mul(world, float4(pos, 1.0)));
    output.triangleID = vertexID / 3;  // or from meshlet
    output.instanceID = instanceID;
    return output;
}

uint2 PSMain(VSOutput input) : SV_Target
{
    // Just write IDs - no material evaluation!
    return uint2(input.instanceID, input.triangleID);
}

// Material Evaluation Pass (Compute)
[numthreads(8, 8, 1)]
void CSMaterialEval(uint3 id : SV_DispatchThreadID)
{
    uint2 pixel = id.xy;
    uint2 vbufData = visibilityBuffer[pixel];
    uint instanceID = vbufData.x;
    uint triangleID = vbufData.y;
    
    if (instanceID == 0xFFFFFFFF) return;  // sky/empty
    
    // Fetch triangle vertices
    InstanceData inst = instanceBuffer[instanceID];
    uint indexBase = inst.indexOffset + triangleID * 3;
    uint i0 = indexBuffer[indexBase + 0];
    uint i1 = indexBuffer[indexBase + 1];
    uint i2 = indexBuffer[indexBase + 2];
    
    Vertex v0 = vertexBuffer[inst.vertexOffset + i0];
    Vertex v1 = vertexBuffer[inst.vertexOffset + i1];
    Vertex v2 = vertexBuffer[inst.vertexOffset + i2];
    
    // Compute barycentrics from screen position
    float2 screenPos = (float2(pixel) + 0.5) / float2(screenWidth, screenHeight);
    float3 bary = ComputeBarycentrics(v0.pos, v1.pos, v2.pos, screenPos, inst.transform, viewProj);
    
    // Interpolate attributes
    float2 uv = bary.x * v0.uv + bary.y * v1.uv + bary.z * v2.uv;
    float3 normal = normalize(bary.x * v0.normal + bary.y * v1.normal + bary.z * v2.normal);
    
    // Evaluate material
    MaterialData mat = materialBuffer[inst.materialID];
    float4 albedo = textures[mat.albedoIndex].SampleLevel(linearSampler, uv, ComputeLOD(uv, pixel));
    
    // Lighting
    float3 color = EvaluateLighting(albedo.rgb, normal, worldPos, ...);
    
    outputColor[pixel] = float4(color, 1.0);
}
```

---

## 六、Nanite 架构分析 (UE5)

### 6.1 整体架构

```
Nanite = GPU Driven Rendering + Cluster LOD + Visibility Buffer

┌─────────────────────────────────────────────────────────────┐
│                    Nanite Pipeline                          │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 1. Instance Culling (Compute)                         │  │
│  │    - Frustum cull all instances                       │  │
│  │    - Hi-Z occlusion cull (from last frame)            │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         ▼                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 2. Persistent Cull (Compute)                          │  │
│  │    - BVH traversal per instance                       │  │
│  │    - Select LOD level per cluster (screen-space error)│  │
│  │    - Frustum + Hi-Z cull per cluster                  │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         ▼                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 3. Rasterization                                      │  │
│  │    - HW raster: large triangles (normal rasterizer)   │  │
│  │    - SW raster: small triangles (compute shader)      │  │
│  │    - Output: Visibility Buffer (64-bit per pixel)     │  │
│  └──────────────────────┬────────────────────────────────┘  │
│                         ▼                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ 4. Material Classification + Evaluation               │  │
│  │    - Group pixels by material                         │  │
│  │    - Evaluate materials in compute                    │  │
│  │    - Output to G-Buffer for deferred lighting         │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  Two-Phase Occlusion Culling across frames                  │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 Cluster LOD (DAG)

```
Traditional LOD:                    Nanite Cluster LOD:

  LOD 0: ████████ (full detail)       Cluster DAG (Directed Acyclic Graph):
  LOD 1: ████ (half)                  
  LOD 2: ██ (quarter)                        ┌──┐
  LOD 3: █ (lowest)                          │C0│ LOD 0 (coarsest)
                                             └┬─┘
  Problem: Entire mesh switches LOD        ╱     ╲
  → Visible popping                    ┌──┐      ┌──┐
                                       │C1│      │C2│ LOD 1
                                       └┬─┘      └┬─┘
                                      ╱  ╲      ╱   ╲
                                    ┌──┐ ┌──┐ ┌──┐ ┌──┐
                                    │C3│ │C4│ │C5│ │C6│ LOD 2 (finest)
                                    └──┘ └──┘ └──┘ └──┘

  Each cluster can be at a DIFFERENT LOD level!
  → Smooth, per-cluster LOD transitions
  → No popping (error-driven selection)

LOD Selection:
  For each cluster, compute screen-space error:
    error = worldSpaceError × screenHeight / (2 × distance × tan(fov/2))
  
  If error < threshold (e.g., 1 pixel):
    → Use this LOD level
  Else:
    → Traverse to finer children

Cluster Group Constraint:
  - Parent cluster group must cover same area as children
  - Boundary edges between groups must match exactly
  - Enables seamless LOD transitions without cracks
```

### 6.3 Software Rasterizer

```
Why software rasterize small triangles?

Hardware Rasterizer:
  - Processes triangles in 2×2 pixel quads
  - For a 1-pixel triangle: 4 pixels processed, 3 wasted (75% waste)
  - For sub-pixel triangles: even worse
  - Fixed-function overhead per triangle

Software Rasterizer (Compute Shader):
  - Process exactly the pixels covered
  - No quad overshading
  - Efficient for tiny triangles (< ~32 pixels)
  - Write directly to visibility buffer via atomics

Nanite's approach:
  ┌─────────────────────────────────────────┐
  │ Classify clusters by triangle size:      │
  │                                         │
  │ Large triangles (> ~32 pixels)           │
  │   → Hardware rasterizer                  │
  │   → Better for large triangles           │
  │                                         │
  │ Small triangles (< ~32 pixels)           │
  │   → Software rasterizer (compute)        │
  │   → No quad overshading waste            │
  │   → Atomic writes to visibility buffer   │
  └─────────────────────────────────────────┘

SW Raster pseudo-code:
  1. Transform triangle vertices to screen space
  2. Compute bounding box in pixels
  3. For each pixel in bounding box:
     a. Compute barycentric coordinates
     b. If inside triangle AND depth test passes:
        InterlockedMin(visBuffer[pixel], packDepthAndTriID)
```

### 6.4 Nanite 数据流总结

```
Offline (Build):
  Original Mesh
      │
      ▼
  Meshlet Generation (meshoptimizer-like)
      │
      ▼
  Cluster LOD DAG Construction
  (simplify clusters, build parent groups)
      │
      ▼
  BVH Construction (per-instance)
      │
      ▼
  Packed GPU Buffers
  (vertices, indices, meshlets, BVH nodes, LOD data)

Runtime (Per Frame):
  GPU Scene Buffer (all instances)
      │
      ▼
  Instance Cull (Compute) ─── Frustum + Hi-Z(last frame)
      │
      ▼
  Persistent Cull (Compute) ─── BVH traverse + LOD select + Cluster cull
      │
      ├── HW Raster Queue (large triangles)
      └── SW Raster Queue (small triangles)
              │
              ▼
      Visibility Buffer (TriID + InstanceID + Depth)
              │
              ▼
      Material Classification (Compute)
              │
              ▼
      Material Evaluation (Compute) → G-Buffer
              │
              ▼
      Deferred Lighting (as usual)
```

---

## 七、Virtual Texture (VT) / Streaming Virtual Texturing

```
Problem: Huge unique textures for large worlds
  → Can't fit all in VRAM
  → Traditional mipmaps waste memory on invisible areas

Virtual Texture:
  ┌─────────────────────────────────────────────────┐
  │ Virtual Address Space (huge, e.g., 128K × 128K)  │
  │ ┌─────┬─────┬─────┬─────┬─────┬─────┐          │
  │ │ P0  │ P1  │ P2  │ P3  │ P4  │ ... │ Pages    │
  │ └──┬──┴──┬──┴──┬──┴─────┴─────┴─────┘          │
  │    │     │     │                                 │
  │    ▼     ▼     ▼                                 │
  │ ┌──────────────────┐                             │
  │ │  Page Table       │  Virtual → Physical mapping │
  │ │  (GPU texture)    │                             │
  │ └────────┬─────────┘                             │
  │          ▼                                       │
  │ ┌──────────────────┐                             │
  │ │  Physical Cache   │  Fixed-size atlas texture   │
  │ │  (e.g., 8K×8K)   │  Only resident pages         │
  │ │  ┌────┬────┬────┐│                             │
  │ │  │ P0 │ P2 │ P7 ││                             │
  │ │  ├────┼────┼────┤│                             │
  │ │  │ P1 │ P5 │ P9 ││                             │
  │ │  └────┴────┴────┘│                             │
  │ └──────────────────┘                             │
  └─────────────────────────────────────────────────┘

Runtime Flow:
  1. Shader samples virtual texture
  2. Page table lookup → physical page location
  3. If page not resident → fallback to lower mip
  4. Feedback buffer records which pages were requested
  5. CPU/async reads feedback, streams in needed pages
  6. Update page table when new pages arrive

Benefits:
  ✅ Constant VRAM usage regardless of world size
  ✅ Only visible pages at needed mip levels loaded
  ✅ Unique texturing for entire world (no tiling)
  ✅ Combines well with GPU-driven rendering
```

---

## 八、完整 GPU Driven Pipeline 总结

```
┌─────────────────────────────────────────────────────────────────┐
│                  Modern GPU Driven Pipeline                      │
│                                                                 │
│  CPU (minimal work):                                            │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ • Upload new/changed instance data                       │    │
│  │ • Submit compute dispatches + indirect draws             │    │
│  │ • Handle streaming (VT pages, mesh LOD data)             │    │
│  │ • ~O(1) API calls per frame                              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  GPU (all the heavy lifting):                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. Instance Culling          (Compute)                   │    │
│  │    Frustum + Hi-Z(prev frame)                            │    │
│  │                                                         │    │
│  │ 2. Cluster/Meshlet Culling   (Compute / Task Shader)     │    │
│  │    BVH traverse + LOD select + Frustum + Hi-Z + Cone     │    │
│  │                                                         │    │
│  │ 3. Draw Compaction           (Compute)                   │    │
│  │    Build indirect args + instance remap                  │    │
│  │                                                         │    │
│  │ 4. Rasterization             (HW + SW)                   │    │
│  │    → Visibility Buffer                                   │    │
│  │                                                         │    │
│  │ 5. Hi-Z Rebuild              (Compute)                   │    │
│  │    For Phase 2 + next frame                              │    │
│  │                                                         │    │
│  │ 6. Phase 2 Cull + Render     (Compute + Raster)          │    │
│  │    Catch disoccluded objects                             │    │
│  │                                                         │    │
│  │ 7. Material Eval             (Compute)                   │    │
│  │    V-Buffer → G-Buffer                                   │    │
│  │                                                         │    │
│  │ 8. Lighting                  (Compute / Full-screen)     │    │
│  │    Deferred / Tiled / Clustered                          │    │
│  │                                                         │    │
│  │ 9. Post Processing           (Compute)                   │    │
│  │    TAA, Bloom, Tone mapping, etc.                        │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 九、带宽分析

### 9.1 V-Buffer vs G-Buffer 带宽对比 (1080p)

```
G-Buffer (typical):
  Albedo:     RGBA8     = 4 bytes/pixel
  Normal:     RG16F     = 4 bytes/pixel
  Roughness:  R8        = 1 byte/pixel
  Metallic:   R8        = 1 byte/pixel
  Depth:      D32F      = 4 bytes/pixel
  Motion:     RG16F     = 4 bytes/pixel
  ─────────────────────────────────────
  Total:                  18 bytes/pixel
  1080p: 1920×1080 × 18 = 37.3 MB per frame (write)

Visibility Buffer:
  V-Buffer:   R32G32UI  = 8 bytes/pixel  (TriID + InstanceID)
  Depth:      D32F      = 4 bytes/pixel
  ─────────────────────────────────────
  Total:                  12 bytes/pixel
  1080p: 1920×1080 × 12 = 24.9 MB per frame (write)

  But V-Buffer raster pass is simpler:
  - No texture sampling during rasterization
  - No material evaluation during rasterization
  - Much less ALU and texture bandwidth

  Material eval pass reads V-Buffer (24.9 MB) + writes G-Buffer (37.3 MB)
  But only for visible pixels (no overdraw!)
```

### 9.2 Culling 效率

```
Typical culling rejection rates:

  ┌──────────────────┬──────────────┬──────────────────┐
  │ Culling Stage    │ Rejection %  │ Remaining        │
  ├──────────────────┼──────────────┼──────────────────┤
  │ Total instances  │              │ 100,000          │
  │ Frustum cull     │ ~60%         │ 40,000           │
  │ Hi-Z occlusion   │ ~50%         │ 20,000           │
  │ Cluster cull     │ ~60%         │ 8,000 clusters   │
  │ Backface cone    │ ~30%         │ 5,600 clusters   │
  │ Small tri cull   │ ~20%         │ ~4,500 clusters  │
  └──────────────────┴──────────────┴──────────────────┘

  From 100K instances → ~4.5K clusters actually rasterized
  = 95.5% geometry rejected before rasterization!
```

---

## 十、移动端 GPU Driven

### 10.1 移动端限制

```
Mobile GPU constraints:
  ❌ No Mesh Shaders (yet, coming in newer GPUs)
  ❌ Limited compute shader performance
  ❌ Tile-based rendering conflicts with compute-heavy pipeline
  ❌ No 64-bit atomics (needed for SW rasterizer)
  ❌ Limited buffer sizes
  ❌ Bandwidth is precious (shared memory bus)

What works on mobile:
  ✅ Indirect Draw (GLES 3.1+ / Vulkan / Metal)
  ✅ GPU Frustum Culling (compute)
  ✅ Simple Hi-Z Occlusion Culling
  ✅ Instance merging / batching
  ✅ Bindless textures (Vulkan descriptor indexing)
```

### 10.2 移动端 GPU Driven 简化方案

```
Mobile GPU Driven Pipeline:

  1. CPU: Upload instance data (transforms, AABBs)
  2. Compute: Frustum cull → visible list
  3. Compute: Hi-Z cull (optional, from prev frame)
  4. Compute: Build indirect args + sort by material
  5. Render: MultiDrawIndirect with instance buffer
     - Use instancing, not per-draw state changes
     - Bindless textures or texture arrays
  6. Tile-based deferred shading (TBDR friendly)

  Key optimizations:
  - Merge small meshes into larger batches
  - Use texture arrays instead of bindless (wider support)
  - Keep compute passes lightweight
  - Respect tile memory (subpass for G-Buffer → lighting)
```

---

## 十一、面试高频题

### 11.1 概念题

| #   | 问题                              | 核心答案                                                                     |
| --- | --------------------------------- | ---------------------------------------------------------------------------- |
| 1   | GPU Driven Rendering 的核心思想？ | 将场景遍历、剔除、Draw Call 生成从 CPU 移到 GPU，CPU 只提交 O(1) 次命令      |
| 2   | Indirect Draw 是什么？            | GPU 从 Buffer 读取 Draw 参数，而非 CPU 逐个指定。支持 GPU 自主决定画什么     |
| 3   | 为什么需要 Bindless？             | 传统绑定模型每次 Draw 需切换资源，GPU Driven 需要一次 Draw 访问所有材质/纹理 |
| 4   | Hi-Z Occlusion Culling 原理？     | 深度 Mip Chain，将物体投影到屏幕，选合适 Mip 级别比较深度，判断是否被遮挡    |
| 5   | Two-Phase OC 解决什么问题？       | 上帧深度在当前帧可能不准确（相机移动），Phase 2 用当前帧部分深度补救         |
| 6   | Cluster/Meshlet 是什么？          | 将 Mesh 切分为 64-128 三角形的小块，每块独立剔除，实现细粒度可见性判断       |
| 7   | Visibility Buffer vs G-Buffer？   | V-Buffer 只存三角形 ID，带宽小无 overdraw 浪费；材质在 Compute 中延迟求值    |
| 8   | Nanite 的 LOD 策略？              | Cluster DAG，每个 Cluster 独立选 LOD（基于屏幕空间误差），无整体切换         |
| 9   | 为什么 Nanite 需要软光栅？        | 小三角形在 HW 光栅器中有 2×2 quad 浪费，软光栅用 Compute 精确处理            |
| 10  | GPU Driven 在移动端的挑战？       | 无 Mesh Shader、Compute 性能有限、TBDR 架构冲突、带宽敏感                    |

### 11.2 深度问答

**Q: Indirect Draw 的 DrawCount 也可以在 GPU 上吗？**

```
Yes! This is called "Indirect Count" or "MDI with count":

  Vulkan:  vkCmdDrawIndexedIndirectCount
  D3D12:   ExecuteIndirect with count buffer
  OpenGL:  GL_ARB_indirect_parameters → glMultiDrawElementsIndirectCount

  The GPU culling compute shader:
  1. Atomically increments a counter for each visible object
  2. Writes draw args to indirect buffer
  3. Counter value becomes the draw count

  CPU never knows how many objects are visible!
  → True GPU autonomy
```

**Q: 如何处理半透明物体？**

```
GPU Driven + Transparency is challenging:

  Option 1: Separate pass
    - Opaque: GPU Driven pipeline (V-Buffer)
    - Transparent: Traditional forward pass (sorted back-to-front)
    - Most engines do this (including UE5 Nanite)

  Option 2: OIT (Order-Independent Transparency)
    - Per-pixel linked lists
    - Weighted blended OIT
    - Moment-based OIT
    - Can be GPU-driven but expensive

  Option 3: Stochastic transparency
    - Random sampling + TAA resolve
    - Works with V-Buffer pipeline
    - Quality depends on sample count

  Nanite (UE5.x): Opaque only, transparent uses traditional path
  Nanite (UE5.4+): Experimental masked/translucent support
```

**Q: GPU Culling 的同步问题？**

```
Compute → Draw dependency:

  Compute Shader writes:
    - Indirect argument buffer
    - Visible instance list
    - Draw count buffer

  Draw reads:
    - Same buffers as indirect arguments

  Must insert barrier between compute and draw:

  Vulkan:
    vkCmdPipelineBarrier(
      srcStage = VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
      dstStage = VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT,
      srcAccess = VK_ACCESS_SHADER_WRITE_BIT,
      dstAccess = VK_ACCESS_INDIRECT_COMMAND_READ_BIT
    );

  D3D12:
    ResourceBarrier(UAV → INDIRECT_ARGUMENT)

  Metal:
    Compute command encoder → Render command encoder
    (implicit barrier between encoders)
```

**Q: Cluster LOD 如何避免接缝 (Crack)？**

```
Nanite's approach:

  1. Cluster Group: Adjacent clusters that share boundary edges
     form a "group" that must LOD-switch together

  2. Boundary Locking: Vertices on cluster boundaries are
     locked during simplification → edges match exactly

  3. DAG Structure:
     - Children clusters cover same area as parent
     - Boundary edges between groups are preserved
     - When switching LOD, entire group switches atomically

  4. Error Metric:
     - Each cluster stores its simplification error
     - Parent error ≥ max(children errors)
     - Monotonic error ensures consistent LOD selection

  Result: No cracks between clusters at different LOD levels
  (as long as cluster groups are respected)
```

**Q: ExecuteIndirect (D3D12) vs DrawIndirect (Vulkan) 区别？**

```
D3D12 ExecuteIndirect:
  - Most flexible: can change root constants, VBV, IBV, SRV per draw
  - Command Signature defines what can change
  - Can effectively change "material" per draw from GPU
  - Higher driver overhead per command

Vulkan DrawIndexedIndirectCount:
  - Only draw parameters change (vertex count, instance count, etc.)
  - Cannot change pipeline, descriptors, push constants per draw
  - Must use bindless + instance ID to vary materials
  - Lower overhead, simpler

Metal Indirect Command Buffer (ICB):
  - Can encode entire render commands on GPU
  - Set pipeline, buffers, draw calls
  - Most flexible on Apple platforms

Practical choice:
  - Most GPU-driven engines use Vulkan-style + bindless
  - Simpler, portable, sufficient for most cases
  - D3D12 ExecuteIndirect useful for complex material switching
```

### 11.3 性能数据参考

```
Nanite (UE5) typical performance:
  - Scene: ~1 billion triangles (source geometry)
  - After culling: ~20-50 million triangles rasterized
  - GPU time: ~2-4ms (RTX 3080, 1080p)
  - CPU time: ~0.5ms (just dispatch + streaming)

GPU Driven (custom engine) typical gains:
  - Draw calls: 10,000+ → 1-10 indirect draws
  - CPU render time: 8ms → 0.5ms
  - GPU time: similar or better (less overdraw)
  - Memory: +20-30% for GPU buffers, but less VRAM waste overall

Culling efficiency:
  - Frustum: 50-70% rejection
  - Hi-Z: 20-50% additional rejection
  - Cluster: 40-60% additional rejection
  - Total: 90-98% geometry rejected
```

---

## 十二、实现 Checklist

```
Minimal GPU Driven (适合入门):
  □ GPU Scene Buffer (all instances in StructuredBuffer)
  □ GPU Frustum Culling (compute shader)
  □ Indirect Draw (DrawIndexedIndirect)
  □ Instance ID → material lookup in shader
  □ Texture Array or Bindless textures

Intermediate:
  □ Hi-Z Occlusion Culling
  □ Two-Phase Occlusion Culling
  □ Multi-Draw Indirect
  □ Draw count on GPU (IndirectCount)
  □ Material sorting in compute

Advanced:
  □ Meshlet/Cluster rendering
  □ Mesh Shader pipeline
  □ Cluster-level culling (frustum + Hi-Z + cone)
  □ Visibility Buffer
  □ Software rasterizer for small triangles
  □ Cluster LOD (DAG)
  □ Virtual Texturing integration

Production:
  □ Streaming (mesh LOD data, VT pages)
  □ Dynamic objects (per-frame instance updates)
  □ Shadow map GPU culling
  □ Transparency handling
  □ Debug visualization (culling stats, LOD colors)
  □ Profiling integration
```