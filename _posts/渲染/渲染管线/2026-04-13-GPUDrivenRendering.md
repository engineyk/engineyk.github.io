---
layout:     post
title:      GPU Driven Rendering
subtitle:   Indirect Draw、GPU Culling、Meshlet、Visibility Buffer、Virtual Geometry
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

## 一、概述：为什么需要 GPU Driven Rendering

### 1.1 传统渲染管线的瓶颈

```
Traditional CPU-Driven Pipeline:

  CPU                                    GPU
  ┌──────────────────┐                  ┌──────────────────┐
  │ For each object: │                  │                  │
  │   Frustum Cull   │  Draw Call ×N    │  Vertex Shader   │
  │   Occlusion Test │ ──────────────▶ │  Rasterizer      │
  │   LOD Select     │  State Change ×N │  Fragment Shader │
  │   Set Material   │                  │                  │
  │   Set Transform  │                  │                  │
  │   DrawIndexed()  │                  │                  │
  └──────────────────┘                  └──────────────────┘

Bottlenecks:
1. CPU bound: per-object culling, sorting, state management
2. Draw call overhead: each DrawIndexed() has driver overhead
3. CPU-GPU sync: CPU must wait for GPU query results (occlusion)
4. Scalability: O(N) CPU work per frame, N = object count
5. Latency: CPU decisions are 1-2 frames behind GPU state
```

### 1.2 GPU Driven 的核心思想

```
GPU-Driven Pipeline:

  CPU                                    GPU
  ┌──────────────────┐                  ┌──────────────────────────────┐
  │ Upload scene     │  Once per frame  │  Compute: Frustum Cull       │
  │ data to GPU      │ ──────────────▶ │  Compute: Occlusion Cull     │
  │ buffers          │                  │  Compute: LOD Select         │
  │                  │  1 Draw Call     │  Compute: Build Draw Args    │
  │ ExecuteIndirect()│ ──────────────▶ │  IndirectDraw: Render All    │
  │                  │                  │                              │
  └──────────────────┘                  └──────────────────────────────┘

Key Principles:
1. Move decision-making from CPU to GPU (Compute Shaders)
2. Use Indirect Draw to let GPU decide what/how to draw
3. Minimize CPU-GPU round trips
4. Process all objects in parallel on GPU
5. Scale with GPU compute power, not CPU single-thread
```

### 1.3 GPU Driven 技术演进

```
Timeline:

2015  Wihlidal (Frostbite)  - GPU-Driven Rendering Pipelines (SIGGRAPH)
      ├─ Indirect Draw + GPU Culling
      └─ Multi-Draw Indirect

2016  Ubisoft (AC Unity)    - Cluster-based rendering
      └─ Triangle cluster culling

2018  Wihlidal (Frostbite)  - Optimizing the Graphics Pipeline with Compute
      └─ Two-phase occlusion culling

2020  Epic (UE5 Nanite)     - Virtual Geometry
      ├─ Meshlet + DAG LOD
      ├─ Software rasterizer
      └─ Visibility Buffer

2021  Traverso (UE5)        - Nanite deep dive
      └─ Cluster hierarchy, BVH culling

2023  Mesh Shaders          - Hardware meshlet pipeline
      └─ Amplification + Mesh Shader (DX12/Vulkan)
```

---

## 二、Indirect Draw (间接绘制)

### 2.1 Direct Draw vs Indirect Draw

```
Direct Draw:
  CPU fills draw parameters → GPU executes

  CPU: DrawIndexedInstanced(indexCount, instanceCount, startIndex, baseVertex, startInstance)
       ↓ ↓ ↓ ↓ ↓
  GPU: executes with these exact parameters

Indirect Draw:
  GPU buffer holds draw parameters → GPU reads and executes

  CPU: ExecuteIndirect(commandSignature, maxCommands, argBuffer, countBuffer)
       ↓
  GPU: reads draw args from argBuffer, reads count from countBuffer
       executes variable number of draw calls

  ┌─────────────────────────────────────────────────────┐
  │  Indirect Argument Buffer (GPU Buffer)              │
  │                                                     │
  │  Draw 0: { indexCount, instanceCount, startIndex,   │
  │            baseVertex, startInstance }              │
  │  Draw 1: { indexCount, instanceCount, startIndex,   │
  │            baseVertex, startInstance }              │
  │  Draw 2: { ... }                                    │
  │  ...                                                │
  │  Draw N: { ... }                                    │
  └─────────────────────────────────────────────────────┘

  ┌──────────────────┐
  │  Count Buffer    │
  │  actualDrawCount │  ← GPU Compute writes this
  └──────────────────┘
```

### 2.2 API 对比

| API        | 函数                                    | 特点                                |
| ---------- | --------------------------------------- | ----------------------------------- |
| **DX11**   | `DrawIndexedInstancedIndirect`          | 单次 Indirect Draw                  |
| **DX12**   | `ExecuteIndirect`                       | 支持多种命令（Draw + State Change） |
| **Vulkan** | `vkCmdDrawIndexedIndirect`              | Multi-Draw Indirect                 |
| **Vulkan** | `vkCmdDrawIndexedIndirectCount`         | Count 也来自 GPU Buffer             |
| **Metal**  | `drawIndexedPrimitives:indirectBuffer:` | Indirect Draw                       |
| **OpenGL** | `glMultiDrawElementsIndirect`           | Multi-Draw Indirect                 |

```hlsl
// DX12 Indirect Argument Structure
struct DrawIndexedArguments {
    uint IndexCountPerInstance;
    uint InstanceCount;
    uint StartIndexLocation;
    int  BaseVertexLocation;
    uint StartInstanceLocation;
};

// Compute Shader: fill indirect args
[numthreads(64, 1, 1)]
void CSBuildDrawArgs(uint3 id : SV_DispatchThreadID) {
    uint objectIndex = id.x;
    if (objectIndex >= totalObjects) return;
    
    ObjectData obj = objectBuffer[objectIndex];
    
    // Only add visible objects
    if (IsVisible(obj)) {
        uint drawIndex;
        InterlockedAdd(drawCountBuffer[0], 1, drawIndex);
        
        DrawIndexedArguments args;
        args.IndexCountPerInstance = obj.indexCount;
        args.InstanceCount = 1;
        args.StartIndexLocation = obj.startIndex;
        args.BaseVertexLocation = obj.baseVertex;
        args.StartInstanceLocation = objectIndex;  // pass object ID
        
        drawArgsBuffer[drawIndex] = args;
    }
}
```

### 2.3 Bindless Resources (无绑定资源)

```
Traditional Binding Model:
  CPU: SetTexture(slot0, texA)    ← per-material state change
       SetTexture(slot1, texB)
       SetBuffer(slot2, bufC)
       Draw()

Bindless Model:
  All resources in descriptor heap / bindless array
  Shader indexes into them using object ID

  ┌──────────────────────────────────────────┐
  │  Descriptor Heap / Bindless Array        │
  │  [0] Texture A                           │
  │  [1] Texture B                           │
  │  [2] Texture C                           │
  │  ...                                     │
  │  [N] Texture N                           │
  └──────────────────────────────────────────┘

  ┌──────────────────────────────────────────┐
  │  Material Buffer                         │
  │  [0] { albedoIdx=3, normalIdx=7, ... }   │
  │  [1] { albedoIdx=1, normalIdx=5, ... }   │
  │  ...                                     │
  └──────────────────────────────────────────┘

  Vertex Shader:
    uint objectID = SV_StartInstanceLocation;  // from indirect args
    MaterialData mat = materialBuffer[objectID];
    Texture2D albedo = textures[mat.albedoIdx];  // bindless access
```

```hlsl
// HLSL Bindless (SM 6.6 / DX12)
// ResourceDescriptorHeap[] - global descriptor heap
Texture2D GetTexture(uint index) {
    return ResourceDescriptorHeap[index];
}

float4 PSMain(VSOutput input) : SV_Target {
    uint objectID = input.objectID;
    MaterialData mat = materialBuffer[objectID];
    
    Texture2D albedoTex = GetTexture(mat.albedoTextureIndex);
    Texture2D normalTex = GetTexture(mat.normalTextureIndex);
    
    float4 albedo = albedoTex.Sample(linearSampler, input.uv);
    float3 normal = normalTex.Sample(linearSampler, input.uv).xyz;
    
    // ... shading
}

// Vulkan Bindless (descriptor indexing)
layout(set = 0, binding = 0) uniform sampler2D textures[];  // unbounded array

void main() {
    uint matIdx = objectBuffer[gl_InstanceIndex].materialIndex;
    MaterialData mat = materialBuffer[matIdx];
    vec4 albedo = texture(textures[mat.albedoIdx], uv);
}
```

---

## 三、GPU Culling (GPU 剔除)

### 3.1 剔除层级

```
Culling Hierarchy (coarse → fine):

┌─────────────────────────────────────────────────────────────┐
│  Level 0: Instance Culling (per-object)                     │
│  ├─ Frustum Culling                                         │
│  ├─ Occlusion Culling (Hi-Z)                                │
│  └─ Distance / Size Culling                                 │
├─────────────────────────────────────────────────────────────┤
│  Level 1: Cluster/Meshlet Culling (per-cluster)             │
│  ├─ Frustum Culling                                         │
│  ├─ Occlusion Culling                                       │
│  ├─ Backface Cluster Culling                                │
│  └─ Screen-size Culling                                     │
├─────────────────────────────────────────────────────────────┤
│  Level 2: Triangle Culling (per-triangle)                   │
│  ├─ Backface Culling                                        │
│  ├─ Degenerate Triangle Culling                             │
│  ├─ Small Triangle Culling (sub-pixel)                      │
│  └─ Frustum Micro-Culling                                   │
└─────────────────────────────────────────────────────────────┘

Typical rejection rates:
  Frustum Cull:     ~50-70% objects rejected
  Occlusion Cull:   ~30-60% of remaining rejected
  Cluster Cull:     ~20-40% clusters rejected
  Triangle Cull:    ~20-50% triangles rejected
  Total:            ~90-99% triangles never rasterized
```

### 3.2 GPU Frustum Culling

```hlsl
// Frustum culling in compute shader
// Test AABB against 6 frustum planes

struct FrustumPlane {
    float3 normal;
    float  distance;
};

bool FrustumCullAABB(float3 aabbMin, float3 aabbMax, FrustumPlane planes[6]) {
    [unroll]
    for (int i = 0; i < 6; i++) {
        // Find the corner most aligned with the plane normal (positive vertex)
        float3 positiveVertex = float3(
            planes[i].normal.x >= 0 ? aabbMax.x : aabbMin.x,
            planes[i].normal.y >= 0 ? aabbMax.y : aabbMin.y,
            planes[i].normal.z >= 0 ? aabbMax.z : aabbMin.z
        );
        
        if (dot(planes[i].normal, positiveVertex) + planes[i].distance < 0) {
            return false;  // outside this plane → culled
        }
    }
    return true;  // inside all planes → visible
}

// Sphere-based frustum culling (faster, less precise)
bool FrustumCullSphere(float3 center, float radius, FrustumPlane planes[6]) {
    [unroll]
    for (int i = 0; i < 6; i++) {
        if (dot(planes[i].normal, center) + planes[i].distance < -radius) {
            return false;
        }
    }
    return true;
}
```

### 3.3 Hi-Z Occlusion Culling (两阶段)

```
Hi-Z (Hierarchical Z-Buffer) Occlusion Culling:

Phase 1: Build Hi-Z pyramid from previous frame's depth

  Full Res Depth    Mip 1 (1/2)    Mip 2 (1/4)    Mip 3 (1/8)
  ┌────────────┐    ┌───────┐       ┌───────┐        ┌──┐
  │            │    │       │       │       │        │  │
  │  1920×1080 │ →  │960×540│  →    │480×270│  →     │  │
  │            │    │       │       │       │        └──┘
  │            │    └───────┘       └───────┘
  └────────────┘
  Each mip stores MAX depth of 2×2 parent texels

Phase 2: Test objects against Hi-Z

  For each object AABB:
  1. Project AABB to screen space → get screen rect
  2. Choose mip level where rect ≈ 1-2 texels
  3. Sample Hi-Z at that mip
  4. If object's min depth > Hi-Z max depth → OCCLUDED

Two-Phase Occlusion Culling (Frostbite approach):

  Frame N-1 depth ──▶ Build Hi-Z
                          │
  Phase 1: ───────────────┤
  Test ALL objects against last frame's Hi-Z
  Draw VISIBLE objects → produce current frame depth
                          │
  Current depth ──▶ Rebuild Hi-Z
                          │
  Phase 2: ───────────────┤
  Test REJECTED objects against current frame's Hi-Z
  Draw newly visible objects (false negatives from Phase 1)

  → Handles disocclusion (objects revealed by camera movement)
  → No 1-frame lag artifacts
```

```hlsl
// Hi-Z Pyramid Generation (Compute Shader)
Texture2D<float> inputDepth;
RWTexture2D<float> outputMip;

[numthreads(8, 8, 1)]
void CSBuildHiZ(uint3 id : SV_DispatchThreadID) {
    uint2 srcCoord = id.xy * 2;
    
    float d0 = inputDepth[srcCoord + uint2(0, 0)];
    float d1 = inputDepth[srcCoord + uint2(1, 0)];
    float d2 = inputDepth[srcCoord + uint2(0, 1)];
    float d3 = inputDepth[srcCoord + uint2(1, 1)];
    
    // Reversed-Z: use MIN for "farthest" depth
    // Standard-Z: use MAX for "farthest" depth
    float maxDepth = max(max(d0, d1), max(d2, d3));
    
    outputMip[id.xy] = maxDepth;
}

// Hi-Z Occlusion Test
bool HiZOcclusionTest(float3 aabbMin, float3 aabbMax, 
                       float4x4 viewProj, Texture2D<float> hiZBuffer) {
    // 1. Project AABB 8 corners to screen space
    float2 screenMin = float2(1, 1);
    float2 screenMax = float2(0, 0);
    float closestDepth = 1.0;  // reversed-Z: 1 = near
    
    float3 corners[8] = {
        float3(aabbMin.x, aabbMin.y, aabbMin.z),
        float3(aabbMax.x, aabbMin.y, aabbMin.z),
        float3(aabbMin.x, aabbMax.y, aabbMin.z),
        float3(aabbMax.x, aabbMax.y, aabbMin.z),
        float3(aabbMin.x, aabbMin.y, aabbMax.z),
        float3(aabbMax.x, aabbMin.y, aabbMax.z),
        float3(aabbMin.x, aabbMax.y, aabbMax.z),
        float3(aabbMax.x, aabbMax.y, aabbMax.z)
    };
    
    [unroll]
    for (int i = 0; i < 8; i++) {
        float4 clip = mul(viewProj, float4(corners[i], 1.0));
        float3 ndc = clip.xyz / clip.w;
        float2 uv = ndc.xy * 0.5 + 0.5;
        uv.y = 1.0 - uv.y;
        
        screenMin = min(screenMin, uv);
        screenMax = max(screenMax, uv);
        closestDepth = min(closestDepth, ndc.z);  // reversed-Z
    }
    
    // 2. Choose mip level
    float2 screenSize = (screenMax - screenMin) * float2(screenWidth, screenHeight);
    float mipLevel = ceil(log2(max(screenSize.x, screenSize.y)));
    mipLevel = clamp(mipLevel, 0, maxMipLevel);
    
    // 3. Sample Hi-Z
    float hiZDepth = hiZBuffer.SampleLevel(pointSampler, 
                     (screenMin + screenMax) * 0.5, mipLevel);
    
    // 4. Reversed-Z: object closer depth > hiZ depth means occluded
    // (In reversed-Z, closer = larger value)
    return closestDepth > hiZDepth;  // true = visible
}
```

### 3.4 Backface Cluster Culling

```
For a cluster of triangles, precompute a "cone" of normals:

  Cone apex = average normal direction
  Cone half-angle = max angle deviation from average

  If the entire cone faces away from the camera → cull entire cluster

        Camera
          │
          ▼
    ╲  ╲  │  ╱  ╱
     ╲  ╲ │ ╱  ╱
      ╲  ╲│╱  ╱
       ╲  │  ╱
        ╲ │ ╱     ← Normal cone
         ╲│╱
     ┌─────────┐
     │ Cluster │  ← All normals face away → CULL
     └─────────┘
```

```hlsl
// Cluster backface culling
struct ClusterConeData {
    float3 coneApex;      // cone apex position (in object space)
    float3 coneAxis;      // average normal direction
    float  coneCutoff;    // cos(half-angle + 90°)
};

bool IsClusterBackface(ClusterConeData cone, float3 cameraPos, float4x4 worldMatrix) {
    float3 worldApex = mul(worldMatrix, float4(cone.coneApex, 1.0)).xyz;
    float3 worldAxis = normalize(mul((float3x3)worldMatrix, cone.coneAxis));
    
    float3 viewDir = normalize(worldApex - cameraPos);
    
    // If dot(viewDir, coneAxis) > coneCutoff, all triangles face away
    return dot(viewDir, worldAxis) > cone.coneCutoff;
}
```

---

## 四、Meshlet (网格小片)

### 4.1 概念

```
Traditional Mesh:
  One big index buffer + vertex buffer per mesh
  GPU processes entire mesh even if partially visible

Meshlet Decomposition:
  Split mesh into small clusters of ~64-128 triangles
  Each meshlet is independently cullable and renderable

  Original Mesh (10K triangles)
  ┌──────────────────────────────────────┐
  │  ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲  │
  │  ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲  │
  │  ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲  │
  └──────────────────────────────────────┘
                    ↓ decompose
  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
  │ M0   │ │ M1   │ │ M2   │ │ M3   │ │ M4   │
  │ 64▲  │ │ 64▲  │ │ 64▲  │ │ 64▲  │ │ 64▲  │
  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘
  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ...
  │ M5   │ │ M6   │ │ M7   │ │ M8   │
  │ 64▲  │ │ 64▲  │ │ 64▲  │ │ 64▲  │
  └──────┘ └──────┘ └──────┘ └──────┘

  ~156 meshlets for 10K triangles
  Each meshlet has its own bounding sphere + normal cone
```

### 4.2 Meshlet 数据结构

```hlsl
// Meshlet data structure
struct Meshlet {
    uint vertexOffset;     // offset into meshlet vertex buffer
    uint triangleOffset;   // offset into meshlet triangle buffer
    uint vertexCount;      // number of unique vertices (max 64 or 128)
    uint triangleCount;    // number of triangles (max 64 or 128)
};

// Meshlet bounds for culling
struct MeshletBounds {
    float3 center;         // bounding sphere center
    float  radius;         // bounding sphere radius
    float3 coneApex;       // normal cone apex
    float3 coneAxis;       // normal cone axis
    float  coneCutoff;     // normal cone cutoff (cos angle)
};

// Memory layout:
//
// Vertex Buffer:     [shared vertices for all meshlets]
// Meshlet Vertices:  [v0, v1, v2, ... | v0, v1, v2, ... | ...]
//                     ← meshlet 0 →   ← meshlet 1 →
// Meshlet Triangles: [0,1,2, 0,2,3, ... | 0,1,2, 1,2,3, ... | ...]
//                     ← meshlet 0 →      ← meshlet 1 →
//                    (local indices into meshlet's vertex list)
```

### 4.3 Meshlet 生成算法

```
Meshlet Generation (meshoptimizer approach):

1. Start with a seed triangle
2. Grow the meshlet by adding adjacent triangles
3. Constraints:
   - Max vertices per meshlet: 64 (or 128)
   - Max triangles per meshlet: 124 (or 256)
   - Maximize spatial locality (minimize bounding sphere)
4. When meshlet is full, start a new one
5. Compute bounding sphere and normal cone for each meshlet

Tools:
- meshoptimizer (open source): meshopt_buildMeshlets()
- DirectXMesh: ComputeMeshlets()
- Custom offline tool
```

```cpp
// Using meshoptimizer library
#include <meshoptimizer.h>

void BuildMeshlets(const std::vector<uint32_t>& indices,
                   const std::vector<Vertex>& vertices) {
    const size_t maxVertices = 64;
    const size_t maxTriangles = 124;
    
    size_t maxMeshlets = meshopt_buildMeshletsBound(
        indices.size(), maxVertices, maxTriangles);
    
    std::vector<meshopt_Meshlet> meshlets(maxMeshlets);
    std::vector<unsigned int> meshletVertices(maxMeshlets * maxVertices);
    std::vector<unsigned char> meshletTriangles(maxMeshlets * maxTriangles * 3);
    
    size_t meshletCount = meshopt_buildMeshlets(
        meshlets.data(), meshletVertices.data(), meshletTriangles.data(),
        indices.data(), indices.size(),
        &vertices[0].position.x, vertices.size(), sizeof(Vertex),
        maxVertices, maxTriangles, 0.0f /* cone weight */);
    
    // Compute bounds for each meshlet
    for (size_t i = 0; i < meshletCount; i++) {
        meshopt_Bounds bounds = meshopt_computeMeshletBounds(
            &meshletVertices[meshlets[i].vertex_offset],
            &meshletTriangles[meshlets[i].triangle_offset],
            meshlets[i].triangle_count,
            &vertices[0].position.x, vertices.size(), sizeof(Vertex));
        
        // bounds.center, bounds.radius
        // bounds.cone_apex, bounds.cone_axis, bounds.cone_cutoff
    }
}
```

### 4.4 Mesh Shader Pipeline (DX12 Ultimate / Vulkan)

```
Traditional Pipeline:
  Input Assembler → Vertex Shader → Hull → Tessellator → Domain → Geometry → Rasterizer

Mesh Shader Pipeline:
  Amplification Shader → Mesh Shader → Rasterizer

  ┌──────────────────────┐     ┌───────────────────────┐     ┌────────────┐
  │ Amplification Shader │ ──▶│    Mesh Shader         │ ──▶│ Rasterizer │
  │ (Task Shader in VK)  │     │                       │     │            │
  │                      │     │ Outputs:              │     │            │
  │ Per-meshlet:         │     │ - vertices (max 256)  │     │            │
  │ - Frustum cull       │     │ - primitives (max 256)│     │            │
  │ - Backface cull      │     │ - per-vertex attribs  │     │            │
  │ - LOD select         │     │ - per-prim attribs    │     │            │
  │                      │     │                       │     │            │
  │ Output:              │     │ Reads meshlet data    │     │            │
  │ - meshlet count      │     │ from buffers          │     │            │
  │ - meshlet indices    │     │                       │     │            │
  └──────────────────────┘     └───────────────────────┘     └────────────┘

  Amplification Shader: 1 thread group per instance/LOD group
    → Decides HOW MANY mesh shader groups to launch
    → Passes per-meshlet payload

  Mesh Shader: 1 thread group per meshlet
    → Reads vertices and indices from buffers
    → Outputs primitives directly (no Input Assembler)
    → Can do per-triangle culling
```

```hlsl
// DX12 Mesh Shader Example

// Amplification Shader (per-instance culling)
struct AmplificationPayload {
    uint meshletIndices[32];  // which meshlets to render
};

[numthreads(32, 1, 1)]
void ASMain(uint gtid : SV_GroupThreadID, uint gid : SV_GroupID) {
    uint instanceID = gid;
    uint meshletID = gtid;
    
    InstanceData instance = instanceBuffer[instanceID];
    MeshletBounds bounds = meshletBoundsBuffer[instance.meshletOffset + meshletID];
    
    // Transform bounds to world space and cull
    bool visible = true;
    visible = visible && FrustumCullSphere(bounds.center, bounds.radius, frustumPlanes);
    visible = visible && !IsClusterBackface(bounds, cameraPos);
    visible = visible && HiZOcclusionTest(bounds);
    
    // Compact visible meshlets
    AmplificationPayload payload;
    uint visibleCount = WavePrefixCountBits(WaveActiveBallot(visible));
    if (visible) {
        uint index = WavePrefixCountBits(WaveActiveBallot(visible));
        payload.meshletIndices[index] = meshletID;
    }
    
    // Dispatch mesh shader groups for visible meshlets only
    DispatchMesh(visibleCount, 1, 1, payload);
}

// Mesh Shader (per-meshlet rendering)
[outputtopology("triangle")]
[numthreads(128, 1, 1)]
void MSMain(
    uint gtid : SV_GroupThreadID,
    uint gid : SV_GroupID,
    in payload AmplificationPayload payload,
    out vertices VertexOutput verts[64],
    out indices uint3 tris[124]
) {
    uint meshletIndex = payload.meshletIndices[gid];
    Meshlet meshlet = meshletBuffer[meshletIndex];
    
    SetMeshOutputCounts(meshlet.vertexCount, meshlet.triangleCount);
    
    // Output vertices
    if (gtid < meshlet.vertexCount) {
        uint vertexIndex = meshletVertices[meshlet.vertexOffset + gtid];
        Vertex v = vertexBuffer[vertexIndex];
        
        verts[gtid].position = mul(mvpMatrix, float4(v.position, 1.0));
        verts[gtid].normal = v.normal;
        verts[gtid].uv = v.uv;
    }
    
    // Output triangles
    if (gtid < meshlet.triangleCount) {
        uint offset = meshlet.triangleOffset + gtid * 3;
        tris[gtid] = uint3(
            meshletTriangles[offset + 0],
            meshletTriangles[offset + 1],
            meshletTriangles[offset + 2]
        );
    }
}
```

---

## 五、Visibility Buffer (可见性缓冲)

### 5.1 G-Buffer vs Visibility Buffer

```
Traditional Deferred (G-Buffer):

  Geometry Pass → G-Buffer (multiple RT) → Lighting Pass

  G-Buffer contents per pixel:
  ┌──────────┬──────────┬──────────┬──────────┐
  │ Albedo   │ Normal   │ Roughness│ Depth    │
  │ RGBA8    │ RG16F    │ R8       │ D32F     │
  │ 32 bpp   │ 32 bpp   │ 8 bpp    │ 32 bpp   │
  └──────────┴──────────┴──────────┴──────────┘
  Total: ~104 bpp = 13 bytes/pixel
  1080p: 13 × 1920 × 1080 = ~27 MB bandwidth per pass

Visibility Buffer:

  Geometry Pass → Vis Buffer (1 RT) → Material Pass

  Vis Buffer contents per pixel:
  ┌─────────────────────────────┐
  │ TriangleID | InstanceID     │
  │ uint32 or uint64            │
  │ 4-8 bytes/pixel             │
  └─────────────────────────────┘
  + Depth buffer
  Total: ~8 bpp = 4-8 bytes/pixel
  1080p: 8 × 1920 × 1080 = ~16 MB bandwidth

  Material Pass: full-screen quad
  - Read TriangleID + InstanceID
  - Fetch vertex data, compute barycentrics
  - Reconstruct all attributes (position, normal, UV, etc.)
  - Evaluate material, output to lighting buffer
```

### 5.2 为什么 Visibility Buffer 更好

| 特性            | G-Buffer                   | Visibility Buffer     |
| --------------- | -------------------------- | --------------------- |
| 带宽            | 高（多 RT 写入）           | 低（仅 ID + Depth）   |
| Overdraw 代价   | 高（写多个 RT）            | 低（仅写 ID）         |
| 材质解耦        | 几何 Pass 需知道材质       | 几何 Pass 与材质无关  |
| 小三角形        | Quad Overdraw 严重         | 可用软光栅优化        |
| 材质数量        | 需要 Uber Shader 或多 Pass | 材质 Pass 统一处理    |
| MSAA            | 每个 RT 都需 MSAA          | 仅 Vis Buffer 需 MSAA |
| 适合 GPU Driven | 一般                       | 非常适合              |

### 5.3 Visibility Buffer 实现

```hlsl
// Pass 1: Geometry Pass - Write Visibility Buffer
struct VSOutput {
    float4 position : SV_Position;
    nointerpolation uint triangleID : TRIANGLE_ID;
    nointerpolation uint instanceID : INSTANCE_ID;
};

VSOutput VSMain(uint vertexID : SV_VertexID, uint instanceID : SV_InstanceID) {
    VSOutput output;
    // ... transform vertex
    output.triangleID = vertexID / 3;  // or from meshlet
    output.instanceID = instanceID;
    return output;
}

uint PSVisBuffer(VSOutput input) : SV_Target {
    // Pack triangle ID and instance ID into single uint
    return (input.instanceID << 16) | (input.triangleID & 0xFFFF);
}

// Pass 2: Material Pass - Full screen, reconstruct attributes
float4 PSMaterial(float4 pos : SV_Position) : SV_Target {
    uint2 pixelCoord = uint2(pos.xy);
    uint visData = visibilityBuffer[pixelCoord];
    float depth = depthBuffer[pixelCoord];
    
    if (visData == 0xFFFFFFFF) discard;  // no geometry
    
    uint instanceID = visData >> 16;
    uint triangleID = visData & 0xFFFF;
    
    // Fetch triangle vertices
    InstanceData instance = instanceBuffer[instanceID];
    uint3 indices = FetchTriangleIndices(instance, triangleID);
    
    float3 v0 = FetchPosition(instance, indices.x);
    float3 v1 = FetchPosition(instance, indices.y);
    float3 v2 = FetchPosition(instance, indices.z);
    
    // Compute barycentrics from screen position and depth
    float3 bary = ComputeBarycentrics(pos.xy, depth, v0, v1, v2, viewProjMatrix);
    
    // Interpolate all attributes using barycentrics
    float2 uv = BaryInterpolate(FetchUV(instance, indices), bary);
    float3 normal = BaryInterpolate(FetchNormal(instance, indices), bary);
    
    // Evaluate material
    MaterialData mat = materialBuffer[instance.materialID];
    float4 albedo = GetTexture(mat.albedoIdx).Sample(linearSampler, uv);
    
    // ... lighting calculation
    return finalColor;
}

// Barycentric computation from screen-space
float3 ComputeBarycentrics(float2 pixelPos, float depth,
                            float3 v0, float3 v1, float3 v2,
                            float4x4 viewProj) {
    // Project vertices to screen space
    float4 p0 = mul(viewProj, float4(v0, 1.0));
    float4 p1 = mul(viewProj, float4(v1, 1.0));
    float4 p2 = mul(viewProj, float4(v2, 1.0));
    
    float2 s0 = p0.xy / p0.w;
    float2 s1 = p1.xy / p1.w;
    float2 s2 = p2.xy / p2.w;
    
    // Convert pixel position to NDC
    float2 ndc = pixelPos / float2(screenWidth, screenHeight) * 2.0 - 1.0;
    ndc.y = -ndc.y;
    
    // Compute barycentrics using cross products
    float2 e0 = s1 - s0;
    float2 e1 = s2 - s0;
    float2 e2 = ndc - s0;
    
    float d00 = dot(e0, e0);
    float d01 = dot(e0, e1);
    float d11 = dot(e1, e1);
    float d20 = dot(e2, e0);
    float d21 = dot(e2, e1);
    
    float denom = d00 * d11 - d01 * d01;
    float v = (d11 * d20 - d01 * d21) / denom;
    float w = (d00 * d21 - d01 * d20) / denom;
    float u = 1.0 - v - w;
    
    // Perspective-correct interpolation
    float3 bary = float3(u / p0.w, v / p1.w, w / p2.w);
    bary /= (bary.x + bary.y + bary.z);
    
    return bary;
}
```

---

## 六、Virtual Geometry (Nanite 架构)

### 6.1 Nanite 核心架构

```
Nanite Pipeline Overview:

  Offline (Asset Import)                    Runtime (Per Frame)
  ┌───────────────────────┐                 ┌───────────────────────────────┐
  │ 1. Meshlet Generation │                 │ 1. Instance Culling (GPU)     │
  │ 2. LOD Cluster DAG    │                 │    - Frustum + Occlusion      │
  │ 3. BVH Construction   │                 │                               │
  │ 4. Streaming Pages    │                 │ 2. Persistent Cull (BVH)      │
  │                       │                 │    - Hierarchical traversal   │
  │                       │                 │    - LOD selection per cluster│
  │                       │                 │                               │
  │                       │                 │ 3. Rasterization              │
  │                       │                 │    - HW raster (large tris)   │
  │                       │                 │    - SW raster (small tris)   │
  │                       │                 │                               │
  │                       │                 │ 4. Visibility Buffer          │
  │                       │                 │    - Deferred material eval   │
  └───────────────────────┘                 └───────────────────────────────┘
```

### 6.2 Cluster LOD DAG (有向无环图)

```
Traditional LOD:
  LOD 0 (full detail)    → 100K triangles
  LOD 1 (medium)         → 25K triangles
  LOD 2 (low)            → 6K triangles
  LOD 3 (very low)       → 1.5K triangles

  Problem: Entire mesh switches LOD → visible pop

Nanite Cluster LOD DAG:
  Each cluster can independently choose its LOD level
  Parent cluster = simplified version of its children

  Level 0 (finest):   [C0] [C1] [C2] [C3] [C4] [C5] [C6] [C7]
                        ╲  ╱     ╲  ╱     ╲  ╱     ╲  ╱
  Level 1:              [C8]     [C9]     [C10]    [C11]
                          ╲      ╱           ╲      ╱
  Level 2:                [C12]               [C13]
                             ╲               ╱
  Level 3 (coarsest):         [C14]

  Key insight: 
  - A parent cluster is a simplified mesh of its children's combined geometry
  - At runtime, for each group, choose EITHER parent OR all children
  - Decision based on screen-space error threshold
  - Different parts of same mesh can be at different LOD levels
  - NO visible popping (error-bounded simplification)

  LOD Selection Rule:
  if (parentError_screenSpace < threshold)
      render parent (coarser)
  else
      render children (finer)

  Screen-space error = worldSpaceError / distanceToCamera × screenHeight / FOV
```

### 6.3 Software Rasterizer

```
Why software rasterization?

Hardware rasterizer processes in 2×2 pixel quads:
  ┌───┬───┐
  │ P │ P │  ← 2×2 quad
  ├───┼───┤     If triangle covers only 1 pixel,
  │   │   │     3 pixels are wasted (75% waste)
  └───┴───┘

For small triangles (< 2×2 pixels), quad overdraw is massive:
  - 1-pixel triangle: 75% wasted
  - Sub-pixel triangle: 100% wasted
  - Nanite scenes can have millions of tiny triangles

Nanite's approach:
  ┌─────────────────────────────────────────┐
  │  Classify triangles by screen size       │
  │                                         │
  │  Large triangles (> ~32 pixels)          │
  │  → Hardware rasterizer (efficient)       │
  │                                         │
  │  Small triangles (< ~32 pixels)          │
  │  → Software rasterizer (compute shader)  │
  │     - No quad overdraw                   │
  │     - Atomic writes to visibility buffer │
  │     - Custom depth test                  │
  └─────────────────────────────────────────┘

Software Rasterizer (simplified):
  1. Transform triangle vertices to screen space
  2. Compute bounding box in pixels
  3. For each pixel in bounding box:
     a. Edge function test (is pixel inside triangle?)
     b. Depth test (compare with current depth)
     c. Atomic write to visibility buffer
        InterlockedMin(visBuffer[pixel], packDepthAndID(depth, triID))
```

```hlsl
// Simplified software rasterizer (compute shader)
[numthreads(64, 1, 1)]
void CSSoftwareRasterize(uint3 id : SV_DispatchThreadID) {
    uint clusterIndex = id.x / 124;  // 124 triangles per cluster
    uint triIndex = id.x % 124;
    
    // Fetch and transform triangle
    float4 v0clip, v1clip, v2clip;
    TransformTriangle(clusterIndex, triIndex, v0clip, v1clip, v2clip);
    
    // Perspective divide
    float2 s0 = v0clip.xy / v0clip.w;
    float2 s1 = v1clip.xy / v1clip.w;
    float2 s2 = v2clip.xy / v2clip.w;
    
    // Convert to pixel coordinates
    float2 p0 = (s0 * 0.5 + 0.5) * float2(screenWidth, screenHeight);
    float2 p1 = (s1 * 0.5 + 0.5) * float2(screenWidth, screenHeight);
    float2 p2 = (s2 * 0.5 + 0.5) * float2(screenWidth, screenHeight);
    
    // Bounding box
    int2 bbMin = max(int2(0, 0), int2(floor(min(min(p0, p1), p2))));
    int2 bbMax = min(int2(screenWidth-1, screenHeight-1), int2(ceil(max(max(p0, p1), p2))));
    
    // Rasterize
    for (int y = bbMin.y; y <= bbMax.y; y++) {
        for (int x = bbMin.x; x <= bbMax.x; x++) {
            float2 pixel = float2(x, y) + 0.5;
            
            // Edge functions
            float w0 = EdgeFunction(p1, p2, pixel);
            float w1 = EdgeFunction(p2, p0, pixel);
            float w2 = EdgeFunction(p0, p1, pixel);
            
            if (w0 >= 0 && w1 >= 0 && w2 >= 0) {
                // Compute depth
                float area = EdgeFunction(p0, p1, p2);
                float3 bary = float3(w0, w1, w2) / area;
                float depth = bary.x * v0clip.z/v0clip.w 
                            + bary.y * v1clip.z/v1clip.w 
                            + bary.z * v2clip.z/v2clip.w;
                
                // Pack depth + ID and atomic write
                uint packed = PackVisibility(depth, clusterIndex, triIndex);
                uint pixelIndex = y * screenWidth + x;
                InterlockedMax(visibilityBuffer[pixelIndex], packed);  // reversed-Z
            }
        }
    }
}

float EdgeFunction(float2 a, float2 b, float2 c) {
    return (c.x - a.x) * (b.y - a.y) - (c.y - a.y) * (b.x - a.x);
}
```

### 6.4 Streaming (虚拟几何体流式加载)

```
Nanite Streaming:

  Disk/Memory                            GPU Memory (VRAM)
  ┌──────────────────┐                 ┌──────────────────┐
  │  Page Pool       │                 │  GPU Page Pool   │
  │  ┌──────┐        │   Stream In     │  ┌──────┐        │
  │  │Page 0│────────┼───────────────▶│  │Page 0│        │
  │  ├──────┤        │                │   ├──────┤        │
  │  │Page 1│        │                │   │Page 3│        │
  │  ├──────┤        │   Stream Out   │   ├──────┤        │
  │  │Page 2│◀───────┼────────────────│  │Page 5│        │
  │  ├──────┤        │                │   ├──────┤        │
  │  │Page 3│        │                │   │ ...  │        │
  │  │ ...  │        │                │   └──────┘        │
  └──────────────────┘                └──────────────────┘

  Each page contains:
  - Multiple clusters (meshlets)
  - Vertex data + index data
  - Hierarchy metadata

  Streaming priority based on:
  - Screen-space error (higher error → higher priority)
  - Distance to camera
  - Visibility (is it in frustum?)

  Fixed GPU memory budget (e.g., 256 MB for geometry)
  LRU eviction of unused pages
```

---

## 七、完整 GPU Driven Pipeline 流程

```
┌──────────────────────────────────────────────────────────────────────┐
│                    GPU Driven Rendering Pipeline                     │
│                                                                      │
│  ┌──────────────┐                                                    │
│  │ CPU (minimal)│                                                    │
│  │              │                                                    │
│  │ • Upload new │    ┌───────────────────────────────────────────┐   │
│  │   instances  │    │              GPU (all work)               │   │
│  │ • Stream     │    │                                           │   │
│  │   requests   │    │  1. Instance Culling (Compute)            │   │
│  │ • 1 Indirect │    │     ├─ Frustum cull all instances         │   │
│  │   Draw call  │    │     ├─ Hi-Z occlusion cull (Phase 1)      │   │
│  │              │    │     └─ Output: visible instance list      │   │
│  └──────┬───────┘    │                                           │   │
│         │            │  2. Persistent Cull / BVH Traversal       │   │
│         │            │     ├─ For each visible instance:         │   │
│         │            │     │   traverse cluster hierarchy        │   │
│         │            │     ├─ LOD selection per cluster group    │   │
│         │            │     ├─ Cluster frustum cull               │   │
│         │            │     ├─ Cluster backface cull              │   │
│         │            │     ├─ Cluster occlusion cull             │   │
│         │            │     └─ Output: visible cluster list       │   │
│         │            │                                           │   │
│         │            │  3. Classify Clusters                     │   │
│         │            │     ├─ Large triangles → HW raster batch  │   │
│         │            │     └─ Small triangles → SW raster batch  │   │
│         │            │                                           │   │
│         │            │  4. Rasterization                         │   │
│         │            │     ├─ HW Raster: IndirectDraw            │   │
│         │            │     └─ SW Raster: Compute Dispatch        │   │
│         │            │     → Output: Visibility Buffer + Depth   │   │
│         │            │                                           │   │
│         │            │  5. Hi-Z Rebuild                          │   │
│         │            │     └─ Build from current depth           │   │
│         │            │                                           │   │
│         │            │  6. Phase 2 Occlusion Cull                │   │
│         │            │     ├─ Re-test Phase 1 rejected objects   │   │
│         │            │     └─ Render newly visible (false neg)   │   │
│         │            │                                           │   │
│         │            │  7. Material Pass (Compute/Fullscreen)    │   │
│         │            │     ├─ Read Vis Buffer (triID, instID)    │   │
│         │            │     ├─ Fetch vertices, compute bary       │   │
│         │            │     ├─ Interpolate attributes             │   │
│         │            │     ├─ Evaluate material (bindless tex)   │   │
│         │            │     └─ Output: GBuffer or direct lighting │   │
│         │            │                                           │   │
│         │            │  8. Lighting / Post-Processing            │   │
│         │            │     └─ Standard deferred/forward lighting │   │
│         │            └───────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 八、引擎实现对比

### 8.1 各引擎 GPU Driven 方案

| 特性                  | UE5 Nanite | Frostbite | Unity DOTS | 自研引擎 |
| --------------------- | ---------- | --------- | ---------- | -------- |
| **Indirect Draw**     | ✅          | ✅         | ✅          | ✅        |
| **GPU Culling**       | ✅ 多级     | ✅ 两阶段  | ✅ 基础     | 可选     |
| **Meshlet**           | ✅ Cluster  | ✅         | ❌          | 可选     |
| **Visibility Buffer** | ✅          | ✅         | ❌          | 可选     |
| **Software Raster**   | ✅          | ❌         | ❌          | 少见     |
| **Virtual Geometry**  | ✅ DAG LOD  | ❌         | ❌          | 少见     |
| **Mesh Shader**       | 部分       | 实验      | ❌          | 可选     |
| **Streaming**         | ✅          | ✅         | ❌          | 可选     |
| **Bindless**          | ✅          | ✅         | 部分       | 可选     |

### 8.2 Nanite 限制

```
Nanite Limitations (UE5):

❌ Skinned meshes (skeletal animation)
❌ Morph targets
❌ World Position Offset (vertex animation)
❌ Translucent materials
❌ Masked materials (alpha test) - partial support in 5.1+
❌ Tessellation
❌ Custom vertex factories
⚠️ Mobile platforms (not supported)
⚠️ VR (performance concerns with SW raster)

Best suited for:
✅ Static meshes (environment, props, buildings)
✅ Foliage (with limitations)
✅ Massive open worlds
✅ Film-quality assets (millions of triangles)
✅ Reducing artist LOD workload
```

### 8.3 Unity GPU Driven 实现路径

```
Unity GPU Driven Options:

1. BatchRendererGroup (BRG) + DOTS
   - SRP Batcher compatible
   - GPU instancing with custom culling
   - Used by Entities Graphics package

2. Custom Compute + IndirectDraw
   - ComputeBuffer for instance data
   - ComputeShader for GPU culling
   - Graphics.DrawMeshInstancedIndirect()
   - Graphics.RenderMeshIndirect() (newer API)

3. RenderMeshIndirect (Unity 2022+)
   - BatchRendererGroup API
   - Supports SRP (URP/HDRP)
   - GPU-driven compatible
```

```csharp
// Unity: Simple GPU Culling + Indirect Draw
public class GPUDrivenRenderer : MonoBehaviour {
    public Mesh mesh;
    public Material material;
    public ComputeShader cullShader;
    
    ComputeBuffer instanceBuffer;      // all instance transforms
    ComputeBuffer visibleBuffer;       // visible instance indices
    ComputeBuffer argsBuffer;          // indirect draw arguments
    ComputeBuffer counterBuffer;       // visible count
    
    void Start() {
        // Initialize buffers with instance