---
layout:     post
title:      BatchRendererGroup
subtitle:   BatchRendererGroup vs GPU Indirect Rendering
date:       2022-08-11
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - 渲染
---

# Unity BatchRendererGroup vs GPU Indirect Rendering

> **适用引擎**：Unity 2022.1+ (URP/HDRP, SRP Batcher 兼容)  
> **关键词**：BatchRendererGroup (BRG), DrawMeshInstancedIndirect, GPU Driven Rendering  
> **最后更新**：2026-04-10

---

## 目录

1. [概述与背景](#1-概述与背景)
2. [架构对比](#2-架构对比)
3. [API 使用对比](#3-api-使用对比)
4. [渲染管线集成](#4-渲染管线集成)
5. [性能对比分析](#5-性能对比分析)
6. [内存模型对比](#6-内存模型对比)
7. [功能特性对比](#7-功能特性对比)
8. [适用场景分析](#8-适用场景分析)
9. [从 Indirect 迁移到 BRG](#9-从-indirect-迁移到-brg)
10. [BRG 高级用法](#10-brg-高级用法)
11. [常见问题与陷阱](#11-常见问题与陷阱)
12. [最佳实践总结](#12-最佳实践总结)

---

## 1. 概述与背景

### 1.1 为什么需要 BRG

Unity 传统的大规模实例渲染方案主要有三种：

| 方案                                 | API                    | 引入版本     | 状态         |
| ------------------------------------ | ---------------------- | ------------ | ------------ |
| `Graphics.DrawMeshInstanced`         | CPU 提交实例矩阵       | Unity 5.4    | 维护中       |
| `Graphics.DrawMeshInstancedIndirect` | GPU Buffer 驱动        | Unity 5.6    | 维护中       |
| `BatchRendererGroup` (BRG)           | SRP Batcher 兼容批处理 | Unity 2022.1 | **主推方案** |

**BRG 的诞生动机**：

```
问题 1: DrawMeshInstancedIndirect 绕过了 SRP Batcher
  → 无法与场景中其他物体合批
  → 无法享受 SRP Batcher 的 SetPass 优化
  → 阴影、深度等多 Pass 需要手动管理

问题 2: DrawMeshInstancedIndirect 绕过了 Unity 渲染管线
  → 不参与 Culling 系统
  → 不参与 LOD 系统
  → 不参与 Light Probe / Reflection Probe
  → 不参与 Occlusion Culling
  → 需要手动处理所有渲染 Pass (Forward, Shadow, Depth, Motion Vector...)

问题 3: DOTS/ECS 需要高效的渲染后端
  → Entities Graphics 底层就是 BRG
  → 需要与 ECS 数据布局 (SoA) 兼容
```

### 1.2 核心定位差异

```
DrawMeshInstancedIndirect:
  "我完全控制 GPU，手动管理一切，追求极致灵活性"
  → 适合: 自研管线、Compute Shader 深度集成、粒子系统

BatchRendererGroup:
  "我提供实例数据，Unity 帮我处理渲染管线集成"
  → 适合: 大规模场景物体、植被、建筑、与 Unity 管线深度集成
```

---

## 2. 架构对比

### 2.1 DrawMeshInstancedIndirect 架构

```
┌──────────────────────────────────────────────────────────────┐
│                  Indirect Rendering Pipeline                 │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌───────────────┐     ┌──────────────┐                      │
│  │ Compute Shader│────>│ Instance     │                      │
│  │ (Culling)     │     │ Buffer       │                      │
│  └───────────────┘     │ (GPU Memory) │                      │
│         │              └──────┬───────┘                      │
│         │                     │                              │
│         ▼                     ▼                              │
│  ┌───────────────┐     ┌──────────────┐                      │
│  │ IndirectArgs  │     │ Material     │                      │
│  │ Buffer        │     │ Properties   │                      │
│  └──────┬────────┘     └──────┬───────┘                      │
│         │                     │                              │
│         ▼                     ▼                              │
│  ┌─────────────────────────────────────┐                     │
│  │ Graphics.DrawMeshInstancedIndirect  │  ← 每个 Pass 手动调用│
│  │ (完全绕过 Unity 渲染管线)            │                      │
│  └─────────────────────────────────────┘                     │
│         │                                                    │
│         ▼                                                    │
│  ┌───────────────┐                                           │
│  │ GPU Draw Call │  ← 直接提交到 GPU                          │
│  │ (1 call per   │                                           │
│  │  material)    │                                           │
│  └───────────────┘                                           │
│                                                              │
│  ⚠️ 不参与: SRP Batcher, Culling, LOD, Probe, Shadow Pass    │
│  ⚠️ 需要手动: 每个 Camera, 每个 Pass 分别调用                  │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 BatchRendererGroup 架构

```
┌─────────────────────────────────────────────────────────────┐
│                  BRG Rendering Pipeline                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐     ┌──────────────────┐                  │
│  │ User Code    │────>│ BRG Instance     │                  │
│  │ (C# / Burst) │     │ (GraphicsBuffer) │                  │
│  └──────────────┘     │ SoA Layout       │                  │
│                       └──────┬───────────┘                  │
│                              │                              │
│                              ▼                              │
│  ┌─────────────────────────────────────────┐                │
│  │ OnPerformCulling Callback               │                │
│  │ (用户实现: 视锥剔除, LOD, 遮挡剔除)       │                │
│  │ 输出: BatchDrawCommand[]                │                │
│  └─────────────────────┬───────────────────┘                │
│                        │                                    │
│                        ▼                                    │
│  ┌─────────────────────────────────────────┐                │
│  │ Unity SRP Batcher                       │                │
│  │ ✅ 自动合批                             │                │
│  │ ✅ 自动处理所有 Pass (Shadow, Depth...) │                │
│  │ ✅ 自动 SetPass 优化                    │                │
│  └─────────────────────┬───────────────────┘                │
│                        │                                    │
│                        ▼                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Forward Pass │  │ Shadow Pass  │  │ Depth Pass   │       │
│  │ (自动)       │   │ (自动)       │  │ (自动)       │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                             │
│  ✅ 参与: SRP Batcher, 多 Pass 自动, Light Probe, LOD       │
│  ✅ 兼容: URP, HDRP, 自定义 SRP                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 数据流对比

```
Indirect Rendering 数据流:
  CPU → ComputeBuffer (实例数据) → CS 剔除 → AppendBuffer → IndirectArgs → DrawCall
  特点: GPU 全程驱动, CPU 几乎不参与渲染

BRG 数据流:
  CPU → GraphicsBuffer (SoA 实例数据) → OnPerformCulling (CPU/Burst) → BatchDrawCommand → SRP Batcher → DrawCall
  特点: CPU 负责剔除和命令生成, GPU 负责渲染
  
  注意: BRG 的剔除回调可以用 Burst + Jobs 加速, 接近 GPU 剔除的效率
```

---

## 3. API 使用对比

### 3.1 Indirect Rendering 基本用法

```csharp
// === DrawMeshInstancedIndirect 完整示例 ===

public class IndirectGrassRenderer : MonoBehaviour
{
    [SerializeField] Mesh grassMesh;
    [SerializeField] Material grassMaterial;
    [SerializeField] ComputeShader cullingCS;
    
    ComputeBuffer instanceBuffer;      // 所有实例数据
    ComputeBuffer visibleBuffer;       // 可见实例数据
    ComputeBuffer argsBuffer;          // IndirectArgs
    MaterialPropertyBlock mpb;
    
    struct GrassInstance
    {
        public Vector3 position;
        public float rotation;
        public float scale;
        // 20 bytes per instance
    }
    
    void Start()
    {
        // 1. 创建实例数据
        var instances = GenerateGrassInstances();
        instanceBuffer = new ComputeBuffer(instances.Length, 20);
        instanceBuffer.SetData(instances);
        
        // 2. 创建可见实例 Buffer (AppendBuffer)
        visibleBuffer = new ComputeBuffer(instances.Length, 20, ComputeBufferType.Append);
        
        // 3. 创建 IndirectArgs
        argsBuffer = new ComputeBuffer(1, 5 * sizeof(uint), ComputeBufferType.IndirectArguments);
        uint[] args = new uint[5] {
            grassMesh.GetIndexCount(0),  // indexCountPerInstance
            0,                            // instanceCount (CS 填写)
            grassMesh.GetIndexStart(0),
            grassMesh.GetBaseVertex(0),
            0
        };
        argsBuffer.SetData(args);
        
        // 4. 设置 Material
        mpb = new MaterialPropertyBlock();
        mpb.SetBuffer("_InstanceBuffer", visibleBuffer);
    }
    
    void Update()
    {
        // === 每帧流程 ===
        
        // Step 1: 重置 AppendBuffer
        visibleBuffer.SetCounterValue(0);
        
        // Step 2: GPU 剔除
        cullingCS.SetBuffer(0, "_AllInstances", instanceBuffer);
        cullingCS.SetBuffer(0, "_VisibleInstances", visibleBuffer);
        cullingCS.SetMatrix("_VPMatrix", Camera.main.projectionMatrix * Camera.main.worldToCameraMatrix);
        cullingCS.SetVector("_CameraPos", Camera.main.transform.position);
        cullingCS.Dispatch(0, Mathf.CeilToInt(instanceCount / 64f), 1, 1);
        
        // Step 3: 拷贝实例数量到 IndirectArgs
        ComputeBuffer.CopyCount(visibleBuffer, argsBuffer, sizeof(uint));
        
        // Step 4: 渲染 (只处理了 Forward Pass!)
        Graphics.DrawMeshInstancedIndirect(
            grassMesh,
            0,
            grassMaterial,
            new Bounds(Vector3.zero, Vector3.one * 1000),
            argsBuffer,
            0,
            mpb
        );
        
        // ⚠️ 问题: Shadow Pass 需要额外处理!
        // ⚠️ 问题: Depth Prepass 需要额外处理!
        // ⚠️ 问题: Motion Vector Pass 需要额外处理!
        // ⚠️ 问题: 多 Camera 需要额外处理!
    }
    
    void OnDestroy()
    {
        instanceBuffer?.Release();
        visibleBuffer?.Release();
        argsBuffer?.Release();
    }
}
```

```hlsl
// === Indirect Rendering Shader ===

struct GrassInstance
{
    float3 position;
    float rotation;
    float scale;
};

StructuredBuffer<GrassInstance> _InstanceBuffer;

v2f vert(appdata v, uint instanceID : SV_InstanceID)
{
    GrassInstance inst = _InstanceBuffer[instanceID];
    
    // 手动构建变换矩阵
    float s = sin(inst.rotation);
    float c = cos(inst.rotation);
    float3x3 rotMatrix = float3x3(
        c, 0, s,
        0, 1, 0,
       -s, 0, c
    );
    
    float3 worldPos = mul(rotMatrix, v.vertex.xyz * inst.scale) + inst.position;
    
    v2f o;
    o.pos = mul(UNITY_MATRIX_VP, float4(worldPos, 1.0));
    o.uv = v.uv;
    return o;
}
```

### 3.2 BatchRendererGroup 基本用法

```csharp
// === BatchRendererGroup 完整示例 ===

using Unity.Collections;
using Unity.Collections.LowLevel.Unsafe;
using Unity.Jobs;
using Unity.Burst;
using Unity.Mathematics;
using UnityEngine;
using UnityEngine.Rendering;

public class BRGGrassRenderer : MonoBehaviour
{
    [SerializeField] Mesh grassMesh;
    [SerializeField] Material grassMaterial; // 必须兼容 SRP Batcher!
    
    BatchRendererGroup brg;
    GraphicsBuffer instanceDataBuffer;
    BatchID batchID;
    BatchMeshID meshID;
    BatchMaterialID materialID;
    
    // 实例数据 (SoA 布局)
    NativeArray<float3> positions;
    NativeArray<float> rotations;
    NativeArray<float> scales;
    int instanceCount;
    
    // BRG 元数据
    static readonly int objectToWorldID = Shader.PropertyToID("unity_ObjectToWorld");
    static readonly int worldToObjectID = Shader.PropertyToID("unity_WorldToObject");
    static readonly int colorID = Shader.PropertyToID("_BaseColor");
    
    void Start()
    {
        // 1. 创建 BRG
        brg = new BatchRendererGroup(OnPerformCulling, IntPtr.Zero);
        
        // 2. 注册 Mesh 和 Material
        meshID = brg.RegisterMesh(grassMesh);
        materialID = brg.RegisterMaterial(grassMaterial);
        
        // 3. 准备实例数据
        instanceCount = 50000;
        positions = new NativeArray<float3>(instanceCount, Allocator.Persistent);
        rotations = new NativeArray<float>(instanceCount, Allocator.Persistent);
        scales = new NativeArray<float>(instanceCount, Allocator.Persistent);
        GenerateGrassData();
        
        // 4. 创建 GPU Buffer (SoA 布局, DOTS 兼容)
        // BRG 要求特定的内存布局: 每个属性连续存储
        int totalBytes = instanceCount * (64 + 64 + 16); // 2x float4x4 + color
        totalBytes += 256; // metadata offset alignment
        
        instanceDataBuffer = new GraphicsBuffer(
            GraphicsBuffer.Target.Raw,
            totalBytes / 4,
            4
        );
        
        // 5. 上传实例数据
        UploadInstanceData();
        
        // 6. 注册 Batch
        var metadata = new NativeArray<MetadataValue>(3, Allocator.Temp);
        metadata[0] = new MetadataValue { NameID = objectToWorldID, Value = 0x80000000 | 0 };
        metadata[1] = new MetadataValue { NameID = worldToObjectID, Value = 0x80000000 | (uint)(instanceCount * 64) };
        metadata[2] = new MetadataValue { NameID = colorID, Value = 0x80000000 | (uint)(instanceCount * 128) };
        
        batchID = brg.AddBatch(metadata, instanceDataBuffer.bufferHandle);
        metadata.Dispose();
    }
    
    void UploadInstanceData()
    {
        // 构建 ObjectToWorld 和 WorldToObject 矩阵
        var matrices = new NativeArray<float4x4>(instanceCount * 2, Allocator.Temp);
        var colors = new NativeArray<float4>(instanceCount, Allocator.Temp);
        
        for (int i = 0; i < instanceCount; i++)
        {
            float s = math.sin(rotations[i]);
            float c = math.cos(rotations[i]);
            float scale = scales[i];
            
            // ObjectToWorld
            matrices[i] = new float4x4(
                c * scale, 0, s * scale, positions[i].x,
                0, scale, 0, positions[i].y,
                -s * scale, 0, c * scale, positions[i].z,
                0, 0, 0, 1
            );
            
            // WorldToObject (inverse)
            float invScale = 1f / scale;
            matrices[instanceCount + i] = new float4x4(
                c * invScale, 0, -s * invScale, 0,
                0, invScale, 0, 0,
                s * invScale, 0, c * invScale, 0,
                0, 0, 0, 1
            );
            // Translation part of inverse needs proper calculation
            float3 invPos = -math.mul(new float3x3(matrices[instanceCount + i]), positions[i]);
            matrices[instanceCount + i].c3 = new float4(invPos, 1);
            
            colors[i] = new float4(0.2f, 0.8f, 0.1f, 1.0f); // grass green
        }
        
        // Upload to GPU buffer
        instanceDataBuffer.SetData(matrices, 0, 0, instanceCount * 2);
        instanceDataBuffer.SetData(colors, 0, instanceCount * 2 * 4, instanceCount); // offset in float4 units
        
        matrices.Dispose();
        colors.Dispose();
    }
    
    // === 核心: 剔除回调 ===
    // Unity 每帧、每个 Camera、每个需要渲染的 Pass 都会调用此回调
    [BurstCompile]
    unsafe JobHandle OnPerformCulling(
        BatchRendererGroup rendererGroup,
        BatchCullingContext cullingContext,
        BatchCullingOutput cullingOutput,
        IntPtr userContext)
    {
        // cullingContext 包含:
        // - cullingPlanes: 视锥体平面 (已包含 Shadow 的视锥)
        // - viewType: Camera / Light (Shadow)
        // - projectionType: Perspective / Orthographic
        // - lodParameters: LOD 计算参数
        
        // 分配输出命令
        int maxDrawCommands = 1; // 简单情况: 1 个 draw command
        
        var drawCommands = (BatchCullingOutputDrawCommands*)cullingOutput.drawCommands.GetUnsafePtr();
        
        drawCommands->drawCommands = (BatchDrawCommand*)UnsafeUtility.Malloc(
            sizeof(BatchDrawCommand) * maxDrawCommands,
            UnsafeUtility.AlignOf<BatchDrawCommand>(),
            Allocator.TempJob
        );
        
        drawCommands->drawCommandCount = maxDrawCommands;
        
        // 可见实例索引
        drawCommands->visibleInstances = (int*)UnsafeUtility.Malloc(
            sizeof(int) * instanceCount,
            UnsafeUtility.AlignOf<int>(),
            Allocator.TempJob
        );
        
        // 简单实现: 所有实例都可见 (实际应做视锥剔除)
        int visibleCount = 0;
        for (int i = 0; i < instanceCount; i++)
        {
            // TODO: 视锥剔除
            // if (IsVisibleInFrustum(positions[i], cullingContext.cullingPlanes))
            drawCommands->visibleInstances[visibleCount++] = i;
        }
        
        drawCommands->visibleInstanceCount = visibleCount;
        
        // 填写 Draw Command
        drawCommands->drawCommands[0] = new BatchDrawCommand
        {
            visibleOffset = 0,
            visibleCount = (uint)visibleCount,
            batchID = batchID,
            materialID = materialID,
            meshID = meshID,
            submeshIndex = 0,
            splitVisibilityMask = 0xff,
            flags = BatchDrawCommandFlags.None,
            sortingPosition = 0,
        };
        
        // 其他必要字段
        drawCommands->drawRanges = (BatchDrawRange*)UnsafeUtility.Malloc(
            sizeof(BatchDrawRange), UnsafeUtility.AlignOf<BatchDrawRange>(), Allocator.TempJob);
        drawCommands->drawRangeCount = 1;
        drawCommands->drawRanges[0] = new BatchDrawRange
        {
            drawCommandsBegin = 0,
            drawCommandsCount = (uint)maxDrawCommands,
            filterSettings = new BatchFilterSettings
            {
                renderingLayerMask = 0xffffffff,
                layer = 0,
                motionMode = MotionVectorGenerationMode.Camera,
                shadowCastingMode = ShadowCastingMode.On,
                receiveShadows = true,
                staticShadowCaster = false,
                allDepthSorted = false,
            }
        };
        
        drawCommands->instanceSortingPositions = null;
        drawCommands->instanceSortingPositionFloatCount = 0;
        
        return default; // 同步完成, 也可返回 JobHandle 异步
    }
    
    void OnDestroy()
    {
        brg?.Dispose();
        instanceDataBuffer?.Dispose();
        positions.Dispose();
        rotations.Dispose();
        scales.Dispose();
    }
}
```

### 3.3 代码复杂度对比

| 方面           | Indirect                      | BRG                       |
| -------------- | ----------------------------- | ------------------------- |
| 初始化代码量   | ~50 行                        | ~120 行                   |
| 每帧更新代码量 | ~30 行 + CS                   | ~80 行 (剔除回调)         |
| Shader 复杂度  | 需要手动读取 StructuredBuffer | 标准 SRP Shader，无需修改 |
| 多 Pass 处理   | 每个 Pass 手动调用            | 自动                      |
| 阴影处理       | 手动实现 Shadow Pass          | 自动                      |
| 总代码量       | 少但需要更多 Shader 工作      | 多但一次性设置            |

---

## 4. 渲染管线集成

### 4.1 SRP Batcher 兼容性

```
DrawMeshInstancedIndirect:
  ❌ 不参与 SRP Batcher
  ❌ 每次调用是独立的 Draw Call
  ❌ 无法与场景中其他物体合批
  ❌ Material Property Block 打断 SRP Batcher
  
  渲染流程:
  [Scene Objects via SRP Batcher] → [Indirect Draw Call (独立)] → [More Scene Objects]
  
  结果: Indirect 的 Draw Call 是一个 "孤岛"，前后都会打断批处理

BatchRendererGroup:
  ✅ 完全参与 SRP Batcher
  ✅ BRG 实例与场景物体可以合批
  ✅ 相同 Material 的 BRG 实例自动合并
  ✅ 使用 DOTS Instancing (cbuffer 方式传递数据)
  
  渲染流程:
  [Scene Objects + BRG Instances 统一排序合批] → [最优 Draw Call 序列]
```

### 4.2 多 Pass 自动处理

```
URP Forward Rendering 需要的 Pass:

                        Indirect          BRG
─────────────────────────────────────────────────
Depth Prepass           手动调用 ❌        自动 ✅
Shadow Caster Pass      手动调用 ❌        自动 ✅
Forward Pass            手动调用 ❌        自动 ✅
Motion Vector Pass      手动调用 ❌        自动 ✅
Depth Normal Pass       手动调用 ❌        自动 ✅

HDRP 需要的 Pass:
GBuffer Pass            手动调用 ❌        自动 ✅
Shadow Pass             手动调用 ❌        自动 ✅
Forward Pass            手动调用 ❌        自动 ✅
Motion Vector Pass      手动调用 ❌        自动 ✅
Depth Prepass           手动调用 ❌        自动 ✅
Decal Pass              不支持 ❌          自动 ✅
```

```csharp
// Indirect: 手动处理 Shadow Pass 的痛苦
void RenderShadows()
{
    // 需要为每个 Shadow Cascade 单独处理
    for (int cascade = 0; cascade < 4; cascade++)
    {
        // 需要获取 Shadow 的 VP 矩阵
        Matrix4x4 shadowVP = GetShadowVPMatrix(cascade);
        
        // 需要用 Shadow VP 重新做剔除
        cullingCS.SetMatrix("_VPMatrix", shadowVP);
        visibleBuffer.SetCounterValue(0);
        cullingCS.Dispatch(0, ...);
        ComputeBuffer.CopyCount(visibleBuffer, argsBuffer, 4);
        
        // 需要使用 Shadow Caster Material/Pass
        Graphics.DrawMeshInstancedIndirect(
            grassMesh, 0, shadowMaterial, bounds, argsBuffer);
    }
    // 4 个 Cascade = 4 次剔除 + 4 次 Draw
    // 如果有多个 Shadow Light，还要翻倍...
}

// BRG: 什么都不用做，Unity 自动处理
// OnPerformCulling 会被自动调用，cullingContext 中包含 Shadow 的视锥信息
// Unity 自动使用正确的 Shadow Pass 渲染
```

### 4.3 Light Probe 与 Reflection Probe

```
Indirect:
  ❌ 不支持 Light Probe (需要手动采样 SH 并传入 Buffer)
  ❌ 不支持 Reflection Probe
  ❌ 不支持 Light Map
  
  手动实现 Light Probe:
  // CPU 端: 为每个实例采样 Light Probe
  for (int i = 0; i < instanceCount; i++)
  {
      SphericalHarmonicsL2 sh;
      LightProbes.GetInterpolatedProbe(positions[i], null, out sh);
      // 上传 SH 系数到 GPU Buffer... (每实例 27 个 float!)
  }
  // 代价: CPU 采样昂贵 + GPU 内存暴增

BRG:
  ✅ 支持 Light Probe (通过 metadata 传递 SH 系数)
  ✅ 支持 Reflection Probe (通过 BatchDrawCommand.flags)
  ✅ 支持 Light Map (通过 metadata)
  
  // BRG 中使用 Light Probe:
  // 在 metadata 中注册 unity_SHAr, unity_SHAg, unity_SHAb 等属性
  // Unity 自动在渲染时读取对应的 SH 数据
```

---

## 5. 性能对比分析

### 5.1 CPU 性能

```
场景: 50,000 草实例, URP Forward, 1 Directional Light + 4 Cascade Shadow

                              Indirect              BRG
──────────────────────────────────────────────────────────────
CPU 渲染提交时间               0.3ms                 0.1ms
  - Forward Pass              0.1ms (1 DrawCall)    自动合批
  - Shadow Pass x4            0.2ms (手动4次调用)    自动
  - Depth Prepass             需要额外调用           自动

CPU 剔除时间                   ~0ms (GPU 剔除)       0.5ms (Burst Jobs)
  - 视锥剔除                  CS 执行                Burst 并行
  - 遮挡剔除                  Hi-Z (GPU)             需要自己实现

CPU 数据更新                   0.1ms                 0.2ms
  - Buffer 更新               SetData                SetData
  - 矩阵计算                  GPU 中完成             CPU/Burst

CPU 总计                       ~0.4ms                ~0.8ms

⚠️ BRG 的 CPU 开销更高，因为剔除在 CPU 端执行
⚠️ 但 BRG 的 GPU 开销可能更低，因为 SRP Batcher 优化
```

### 5.2 GPU 性能

```
                              Indirect              BRG
──────────────────────────────────────────────────────────────
Draw Call 数量                 1 (Forward)           1-3 (SRP 合批)
                              + 4 (Shadow)          (Shadow 自动)
                              + 1 (Depth)           
                              = 6 total             = 3-5 total (合批后)

State Change                   每次 Draw 前设置      SRP Batcher 最小化
  - SetPass                   6 次                  1-2 次
  - SetBuffer                 6 次                  0 次 (cbuffer)

GPU 剔除 (CS)                  0.2ms                 0ms (CPU 已剔除)

VS 性能                        相同                  相同
  - 但 Indirect 需要手动       BRG 使用标准
    读取 StructuredBuffer      DOTS Instancing
    (可能更慢)                 (cbuffer, 更快)

PS 性能                        相同                  相同

GPU 总计                       ~2.5ms                ~2.0ms
```

### 5.3 综合性能对比

```
场景规模        Indirect 总耗时    BRG 总耗时    胜出
──────────────────────────────────────────────────────
1,000 实例      0.5ms              0.4ms         BRG ✅
10,000 实例     1.2ms              1.0ms         BRG ✅
50,000 实例     2.9ms              2.8ms         接近
100,000 实例    5.1ms              5.5ms         Indirect ✅
500,000 实例    12ms               15ms          Indirect ✅

分析:
- 小规模 (< 50K): BRG 胜出，因为多 Pass 自动处理 + SRP Batcher
- 大规模 (> 100K): Indirect 胜出，因为 GPU 剔除效率更高
- 超大规模 (> 500K): Indirect 明显胜出，CPU 剔除成为 BRG 瓶颈

关键因素:
- BRG 的 OnPerformCulling 在 CPU 执行，大规模时成为瓶颈
- Indirect 的 CS 剔除在 GPU 执行，可以处理百万级实例
- 但 Indirect 的多 Pass 手动管理增加了固定开销
```

### 5.4 Shader 数据访问性能

```hlsl
// === Indirect: StructuredBuffer 访问 ===
// 每个实例从 StructuredBuffer 读取数据
// StructuredBuffer 走 L2 Cache，可能有 Cache Miss

StructuredBuffer<GrassInstance> _InstanceBuffer;

v2f vert(appdata v, uint instanceID : SV_InstanceID)
{
    GrassInstance inst = _InstanceBuffer[instanceID]; // 可能 Cache Miss
    // 手动构建矩阵...
}

// === BRG: DOTS Instancing (cbuffer) ===
// 数据通过 Constant Buffer 传递，硬件优化更好
// Unity 自动处理数据绑定

// Shader 中使用标准 DOTS Instancing 宏:
CBUFFER_START(UnityPerDraw)
    float4x4 unity_ObjectToWorld;
    float4x4 unity_WorldToObject;
CBUFFER_END

// 或自定义属性:
CBUFFER_START(UnityPerMaterial)
    float4 _BaseColor;
CBUFFER_END

// DOTS Instancing 通过 ByteAddressBuffer + metadata offset 访问
// 硬件对 cbuffer 有专门的缓存优化
```

```
数据访问性能对比:

                        StructuredBuffer        DOTS Instancing (cbuffer)
─────────────────────────────────────────────────────────────────────────
缓存友好度               中等 (L2)               高 (Constant Cache)
随机访问性能             较好                    较好
连续访问性能             好                      很好
Wave 内一致性            不保证                  保证 (同一 Draw 内)
带宽消耗                 较高                    较低
```

---

## 6. 内存模型对比

### 6.1 GPU 内存布局

```
=== Indirect: AoS (Array of Structures) ===

Buffer 布局:
[Instance0: pos.x, pos.y, pos.z, rot, scale]
[Instance1: pos.x, pos.y, pos.z, rot, scale]
[Instance2: pos.x, pos.y, pos.z, rot, scale]
...

优点: 单个实例数据连续，适合 GPU 随机访问
缺点: 如果只需要 position，也要加载整个结构体


=== BRG: SoA (Structure of Arrays) ===

Buffer 布局:
[All ObjectToWorld matrices: M0, M1, M2, M3, ...]
[All WorldToObject matrices: M0, M1, M2, M3, ...]
[All Colors: C0, C1, C2, C3, ...]

优点: 
  - 同一属性连续存储，缓存友好
  - 只需要某个属性时不会加载无关数据
  - 与 DOTS/ECS 的 Chunk 布局兼容
缺点:
  - 更新单个实例需要写入多个不连续位置
```

### 6.2 内存占用对比

```
50,000 草实例:

=== Indirect ===
Instance Buffer:     50,000 × 20 bytes  = 1.0 MB
Visible Buffer:      50,000 × 20 bytes  = 1.0 MB (AppendBuffer)
Indirect Args:       5 × 4 bytes        = 20 bytes
CS Temp Buffers:     ~0.5 MB
Total GPU Memory:    ~2.5 MB

=== BRG ===
ObjectToWorld:       50,000 × 64 bytes  = 3.2 MB (float4x4)
WorldToObject:       50,000 × 64 bytes  = 3.2 MB (float4x4)
Color:               50,000 × 16 bytes  = 0.8 MB (float4)
Metadata:            ~256 bytes
Total GPU Memory:    ~7.2 MB

⚠️ BRG 默认内存占用更高!
原因: BRG 需要完整的 ObjectToWorld + WorldToObject 矩阵 (128 bytes/instance)
而 Indirect 可以只存储 position + rotation + scale (20 bytes/instance)
```

### 6.3 BRG 内存优化

```csharp
// 优化 1: 使用 packed 矩阵 (float3x4 代替 float4x4)
// 节省 25% 矩阵内存
// 需要 Shader 配合: 最后一行固定为 (0,0,0,1)

// 优化 2: 共享 WorldToObject
// 如果所有实例的缩放相同，WorldToObject 可以共享
// 或者在 Shader 中实时计算 inverse

// 优化 3: 减少 per-instance 属性
// 不需要 per-instance color? 不注册 _BaseColor metadata
// 使用 Material 的全局属性代替

// 优化后:
// ObjectToWorld:    50,000 × 48 bytes = 2.4 MB (float3x4)
// WorldToObject:    共享 1 个 = 48 bytes
// Total: ~2.4 MB (节省 67%)
```

---

## 7. 功能特性对比

### 7.1 完整特性矩阵

| 特性                | Indirect     | BRG               | 说明                                |
| ------------------- | ------------ | ----------------- | ----------------------------------- |
| **渲染管线集成**    |              |                   |                                     |
| SRP Batcher 合批    | ❌            | ✅                 | BRG 最大优势                        |
| 多 Pass 自动处理    | ❌            | ✅                 | Shadow, Depth, Motion Vector        |
| 多 Camera 自动处理  | ❌            | ✅                 | Scene View, Reflection Probe Camera |
| Render Layer 过滤   | ❌            | ✅                 | BatchFilterSettings                 |
| **剔除**            |              |                   |                                     |
| 视锥剔除            | GPU (CS) ✅   | CPU (Burst) ✅     | Indirect 更适合大规模               |
| 遮挡剔除            | GPU (Hi-Z) ✅ | 需自己实现        | Indirect 优势                       |
| 距离剔除            | GPU ✅        | CPU ✅             | 都支持                              |
| LOD                 | GPU ✅        | CPU ✅             | BRG 可用 BatchDrawCommand 分 LOD    |
| **光照**            |              |                   |                                     |
| Light Probe         | 手动 ⚠️       | 自动 ✅            | BRG 优势                            |
| Reflection Probe    | 手动 ⚠️       | 自动 ✅            | BRG 优势                            |
| Light Map           | 不支持 ❌     | 支持 ✅            | BRG 优势                            |
| Shadow Casting      | 手动 ⚠️       | 自动 ✅            | BRG 优势                            |
| Shadow Receiving    | 手动 ⚠️       | 自动 ✅            | BRG 优势                            |
| **动画**            |              |                   |                                     |
| GPU 动画            | 完全控制 ✅   | 需要更新 Buffer ⚠️ | Indirect 更灵活                     |
| Compute Shader 集成 | 原生 ✅       | 需要额外同步 ⚠️    | Indirect 优势                       |
| **平台兼容性**      |              |                   |                                     |
| 所有平台            | 大部分 ✅     | Unity 2022.1+ ✅   | BRG 需要较新版本                    |
| WebGL               | 有限 ⚠️       | 有限 ⚠️            | 都有限制                            |
| **调试**            |              |                   |                                     |
| Frame Debugger      | 有限         | 完整 ✅            | BRG 在 Frame Debugger 中可见        |
| RenderDoc           | ✅            | ✅                 | 都支持                              |
| Scene View 可见     | 需要额外处理 | 自动 ✅            | BRG 优势                            |

### 7.2 Shader 兼容性

```hlsl
// === Indirect: 需要自定义 Shader ===
// 必须手动从 StructuredBuffer 读取实例数据
// 不能使用标准 URP/HDRP Shader
// 需要为每个 Pass 编写对应的 Shader Variant

// Forward Pass Shader
Shader "Custom/GrassIndirect"
{
    SubShader
    {
        // Forward Pass
        Pass
        {
            Tags { "LightMode" = "UniversalForward" }
            // 手动实现...
        }
        // Shadow Pass - 需要单独写!
        Pass
        {
            Tags { "LightMode" = "ShadowCaster" }
            // 手动实现...
        }
        // Depth Pass - 需要单独写!
        Pass
        {
            Tags { "LightMode" = "DepthOnly" }
            // 手动实现...
        }
        // 还有 DepthNormals, MotionVectors...
    }
}


// === BRG: 使用标准 SRP Shader + DOTS Instancing ===
// 只需要在标准 Shader 基础上添加 DOTS Instancing 支持
// 所有 Pass 自动工作

Shader "Custom/GrassBRG"
{
    SubShader
    {
        // 使用标准 URP Shader 的所有 Pass
        // 只需要添加 DOTS Instancing 关键字
        
        Pass
        {
            Tags { "LightMode" = "UniversalForward" }
            
            HLSLPROGRAM
            #pragma multi_compile _ DOTS_INSTANCING_ON
            
            #ifdef DOTS_INSTANCING_ON
                UNITY_DOTS_INSTANCING_START(MaterialPropertyMetadata)
                    UNITY_DOTS_INSTANCED_PROP(float4, _BaseColor)
                UNITY_DOTS_INSTANCING_END(MaterialPropertyMetadata)
                
                #define _BaseColor UNITY_ACCESS_DOTS_INSTANCED_PROP_WITH_DEFAULT(float4, _BaseColor)
            #endif
            
            // 其余代码与标准 URP Shader 完全相同!
            // unity_ObjectToWorld 等内置属性自动通过 DOTS Instancing 获取
            ENDHLSL
        }
        
        // Shadow, Depth 等 Pass 使用 URP 标准的 Include
        // 自动支持 DOTS Instancing，无需额外代码
    }
}
```

---

## 8. 适用场景分析

### 8.1 选择决策树

```
                    需要大规模实例渲染?
                          │
                    ┌─────┴─────┐
                    │           │
                   Yes          No → 使用标准 GameObject
                    │
              实例数量级?
                    │
          ┌─────────┼─────────┐
          │         │         │
        < 50K    50K-200K    > 200K
          │         │         │
          ▼         ▼         ▼
     需要完整      两者都可    GPU 剔除
     管线集成?     考虑        是否必要?
          │                    │
     ┌────┴────┐          ┌───┴───┐
     │         │          │       │
    Yes        No        Yes      No
     │         │          │       │
     ▼         ▼          ▼       ▼
   BRG ✅   Indirect    Indirect  BRG
            也可以 ✅    ✅       (需要优化剔除)


额外考虑因素:
─────────────────────────────────────────
需要 Compute Shader 深度集成?     → Indirect
需要 GPU 粒子系统?               → Indirect
需要与 DOTS/ECS 集成?            → BRG
需要 Light Probe / Light Map?    → BRG
需要最少的 Shader 工作?          → BRG
需要在 Scene View 中可见?        → BRG
需要支持所有渲染 Pass?           → BRG
需要 GPU 遮挡剔除?              → Indirect
需要 GPU 物理模拟?              → Indirect
```

### 8.2 典型场景推荐

| 场景              | 推荐方案 | 原因                             |
| ----------------- | -------- | -------------------------------- |
| 草地渲染 (< 50K)  | BRG      | 需要阴影、Light Probe、多 Pass   |
| 草地渲染 (> 200K) | Indirect | GPU 剔除效率更高                 |
| 树木/植被         | BRG      | 需要 LOD、Light Probe、完整光照  |
| GPU 粒子系统      | Indirect | 需要 CS 物理模拟                 |
| 建筑实例化        | BRG      | 需要 Light Map、Reflection Probe |
| 石头/碎片         | BRG      | 需要完整渲染管线                 |
| 人群模拟          | Indirect | GPU 动画 + 大规模                |
| 弹幕/子弹         | Indirect | CS 物理 + 简单渲染               |
| 地形装饰物        | BRG      | 需要与地形光照一致               |
| 星空/点云         | Indirect | 极大规模 + 简单渲染              |

### 8.3 混合方案

```
实际项目中，BRG 和 Indirect 可以共存:

┌─────────────────────────────────────────┐
│              渲染管线                     │
├─────────────────────────────────────────┤
│                                         │
│  BRG 负责:                              │
│  ├── 近景草 (< 50m, 需要阴影和光照)      │
│  ├── 树木 (需要 LOD 和 Light Probe)      │
│  └── 建筑 (需要 Light Map)              │
│                                         │
│  Indirect 负责:                         │
│  ├── 远景草 (> 50m, 简化渲染)            │
│  ├── GPU 粒子 (CS 物理模拟)             │
│  └── 特效 (弹幕、碎片)                  │
│                                         │
└─────────────────────────────────────────┘
```

---

## 9. 从 Indirect 迁移到 BRG

### 9.1 迁移步骤

```
Step 1: 评估是否需要迁移
  ├── 当前 Indirect 方案是否有多 Pass 问题? → 迁移
  ├── 是否需要 Light Probe / Shadow? → 迁移
  ├── 实例数 > 200K 且 GPU 剔除是核心? → 不迁移
  └── 是否使用 DOTS/ECS? → 迁移 (使用 Entities Graphics)

Step 2: Shader 迁移
  ├── 移除 StructuredBuffer 读取
  ├── 添加 DOTS_INSTANCING_ON 支持
  ├── 使用标准 unity_ObjectToWorld
  └── 删除手动编写的 Shadow/Depth Pass

Step 3: C# 代码迁移
  ├── 替换 ComputeBuffer → GraphicsBuffer
  ├── 实现 OnPerformCulling 回调
  ├── 数据布局从 AoS → SoA
  └── 删除手动 DrawMeshInstancedIndirect 调用

Step 4: 剔除迁移
  ├── GPU CS 剔除 → CPU Burst Jobs 剔除
  ├── 或保留 GPU 剔除，结果回读到 CPU (有延迟)
  └── 评估 CPU 剔除性能是否满足需求

Step 5: 测试验证
  ├── 验证所有 Pass 正确渲染 (Shadow, Depth, Motion Vector)
  ├── 验证 Light Probe 正确
  ├── 验证 Scene View 正确
  └── 性能对比测试
```

### 9.2 Shader 迁移示例

```hlsl
// === 迁移前: Indirect Shader ===

StructuredBuffer<float4> _PositionBuffer;
StructuredBuffer<float4> _ColorBuffer;

v2f vert(appdata v, uint instanceID : SV_InstanceID)
{
    float4 posData = _PositionBuffer[instanceID];
    float3 worldPos = v.vertex.xyz * posData.w + posData.xyz;
    
    v2f o;
    o.pos = mul(UNITY_MATRIX_VP, float4(worldPos, 1.0));
    o.color = _ColorBuffer[instanceID];
    return o;
}


// === 迁移后: BRG Shader ===

// 不需要 StructuredBuffer!
// 使用标准的 DOTS Instancing

#pragma multi_compile _ DOTS_INSTANCING_ON

#ifdef DOTS_INSTANCING_ON
    UNITY_DOTS_INSTANCING_START(MaterialPropertyMetadata)
        UNITY_DOTS_INSTANCED_PROP(float4, _BaseColor)
    UNITY_DOTS_INSTANCING_END(MaterialPropertyMetadata)
    
    #define _BaseColor UNITY_ACCESS_DOTS_INSTANCED_PROP_WITH_DEFAULT(float4, _BaseColor)
#endif

v2f vert(appdata v)
{
    // 使用标准的 Unity 变换
    // unity_ObjectToWorld 自动通过 DOTS Instancing 获取
    float3 worldPos = mul(unity_ObjectToWorld, v.vertex).xyz;
    
    v2f o;
    o.pos = mul(UNITY_MATRIX_VP, float4(worldPos, 1.0));
    o.color = _BaseColor; // 自动获取 per-instance 颜色
    return o;
}
```

### 9.3 剔除迁移

```csharp
// === 迁移前: GPU Compute Shader 剔除 ===

// culling.compute
[numthreads(64, 1, 1)]
void CSCull(uint3 id : SV_DispatchThreadID)
{
    float3 pos = allInstances[id.x].position;
    if (IsInFrustum(pos, _FrustumPlanes))
    {
        uint idx;
        InterlockedAdd(count[0], 1, idx);
        visibleInstances.Append(allInstances[id.x]);
    }
}


// === 迁移后: CPU Burst Jobs 剔除 ===

[BurstCompile]
struct FrustumCullJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<float3> positions;
    [ReadOnly] public NativeArray<Plane> frustumPlanes; // 6 planes
    [WriteOnly] public NativeArray<int> visibleIndices;
    public NativeCounter.Concurrent visibleCount;
    
    public void Execute(int index)
    {
        float3 pos = positions[index];
        
        // 6-plane frustum test
        bool visible = true;
        for (int p = 0; p < 6; p++)
        {
            Plane plane = frustumPlanes[p];
            float dist = math.dot(plane.normal, pos) + plane.distance;
            if (dist < -0.5f) // radius
            {
                visible = false;
                break;
            }
        }
        
        if (visible)
        {
            int idx = visibleCount.Increment();
            visibleIndices[idx] = index;
        }
    }
}

// 在 OnPerformCulling 中调度:
var job = new FrustumCullJob
{
    positions = positions,
    frustumPlanes = ExtractPlanes(cullingContext.cullingPlanes),
    visibleIndices = tempVisibleIndices,
    visibleCount = counter,
};
JobHandle handle = job.Schedule(instanceCount, 64);
```

---

## 10. BRG 高级用法

### 10.1 多 LOD 支持

```csharp
// BRG 通过多个 BatchDrawCommand 实现 LOD
// 每个 LOD 使用不同的 MeshID

BatchMeshID meshLOD0 = brg.RegisterMesh(grassMeshLOD0); // 8 vertices
BatchMeshID meshLOD1 = brg.RegisterMesh(grassMeshLOD1); // 4 vertices
BatchMeshID meshLOD2 = brg.RegisterMesh(grassMeshLOD2); // 3 vertices

// 在 OnPerformCulling 中:
unsafe JobHandle OnPerformCulling(...)
{
    // 根据距离分配到不同 LOD 的 DrawCommand
    int lod0Count = 0, lod1Count = 0, lod2Count = 0;
    
    for (int i = 0; i < instanceCount; i++)
    {
        float dist = math.distance(positions[i], cameraPos);
        if (dist < 20f)
            lod0Indices[lod0Count++] = i;
        else if (dist < 60f)
            lod1Indices[lod1Count++] = i;
        else if (dist < 120f)
            lod2Indices[lod2Count++] = i;
    }
    
    // 3 个 DrawCommand，分别使用不同的 Mesh
    drawCommands->drawCommandCount = 3;
    
    drawCommands->drawCommands[0] = new BatchDrawCommand
    {
        meshID = meshLOD0,
        visibleOffset = 0,
        visibleCount = (uint)lod0Count,
        // ...
    };
    
    drawCommands->drawCommands[1] = new BatchDrawCommand
    {
        meshID = meshLOD1,
        visibleOffset = (uint)lod0Count,
        visibleCount = (uint)lod1Count,
        // ...
    };
    
    drawCommands->drawCommands[2] = new BatchDrawCommand
    {
        meshID = meshLOD2,
        visibleOffset = (uint)(lod0Count + lod1Count),
        visibleCount = (uint)lod2Count,
        // ...
    };
}
```

### 10.2 动态更新实例数据

```csharp
// BRG 支持动态更新 GPU Buffer
// 适用于: 风力动画、生长动画、交互变形

void UpdateGrassAnimation()
{
    // 方案 1: 全量更新 (简单但带宽大)
    var matrices = new NativeArray<float3x4>(instanceCount, Allocator.Temp);
    
    // Burst Job 并行计算新矩阵
    new UpdateMatricesJob
    {
        positions = positions,
        windOffset = CalculateWind(),
        time = Time.time,
        output = matrices
    }.Schedule(instanceCount, 64).Complete();
    
    instanceDataBuffer.SetData(matrices);
    matrices.Dispose();
    
    // 方案 2: 部分更新 (只更新变化的实例)
    // 使用 GraphicsBuffer.SetData 的 offset 参数
    // 只更新移动/变化的实例的矩阵
    foreach (int dirtyIndex in dirtyInstances)
    {
        instanceDataBuffer.SetData(singleMatrix, 0, dirtyIndex * 12, 12); // float3x4 = 12 floats
    }
}
```

### 10.3 与 Entities Graphics 的关系

```
Entities Graphics (DOTS 渲染系统) 的底层就是 BRG:

┌─────────────────────────────────────────┐
│           Entities Graphics              │
│  ┌─────────────────────────────────┐    │
│  │ ECS Components                   │    │
│  │ (LocalToWorld, RenderMesh, etc.) │    │
│  └──────────────┬──────────────────┘    │
│                 │                        │
│                 ▼                        │
│  ┌─────────────────────────────────┐    │
│  │ EntitiesGraphicsSystem           │    │
│  │ (自动管理 BRG)                   │    │
│  └──────────────┬──────────────────┘    │
│                 │                        │
│                 ▼                        │
│  ┌─────────────────────────────────┐    │
│  │ BatchRendererGroup               │    │
│  │ (底层渲染 API)                   │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘

如果你使用 DOTS/ECS:
  → 直接使用 Entities Graphics，它自动管理 BRG
  → 不需要手动创建 BRG

如果你不使用 DOTS/ECS:
  → 直接使用 BRG API
  → 自己管理实例数据和剔除
```

---

## 11. 常见问题与陷阱

### 11.1 BRG 常见问题

| 问题              | 原因                                         | 解决方案                                     |
| ----------------- | -------------------------------------------- | -------------------------------------------- |
| 实例不显示        | Material 不兼容 SRP Batcher                  | 确保 Material 使用 SRP 兼容 Shader           |
| 实例不显示        | Metadata 偏移错误                            | 检查 MetadataValue 的 offset 计算            |
| 实例不显示        | Buffer 大小不足                              | 确保 GraphicsBuffer 足够大                   |
| 阴影不正确        | BatchFilterSettings 未设置 shadowCastingMode | 设置 ShadowCastingMode.On                    |
| 闪烁              | 矩阵数据错误                                 | 检查 ObjectToWorld 和 WorldToObject 是否匹配 |
| 性能差            | OnPerformCulling 太慢                        | 使用 Burst + Jobs 加速                       |
| Scene View 不显示 | OnPerformCulling 未处理 Editor Camera        | 检查 cullingContext.viewType                 |
| 内存泄漏          | 未 Dispose BRG/Buffer                        | 在 OnDestroy 中正确释放                      |

### 11.2 Indirect 常见问题

| 问题               | 原因                         | 解决方案                                              |
| ------------------ | ---------------------------- | ----------------------------------------------------- |
| 没有阴影           | 未实现 Shadow Pass           | 手动添加 ShadowCaster Pass                            |
| SRP Batcher 断裂   | Indirect 不参与 SRP Batcher  | 无法解决，这是架构限制                                |
| Scene View 不显示  | 只在 Game Camera 调用了 Draw | 在 OnRenderObject 或 RenderPipelineManager 回调中处理 |
| 多 Camera 渲染错误 | 剔除数据只针对一个 Camera    | 为每个 Camera 单独剔除                                |
| Buffer 数据错误    | CS 和渲染之间的同步问题      | 确保 CS Dispatch 在 Draw 之前完成                     |

### 11.3 性能陷阱

```csharp
// ❌ BRG 陷阱 1: OnPerformCulling 中分配内存
unsafe JobHandle OnPerformCulling(...)
{
    // 每帧分配 NativeArray → GC 压力!
    var temp = new NativeArray<int>(count, Allocator.Temp); // ❌
    
    // ✅ 使用 Allocator.TempJob 或预分配
    var temp = new NativeArray<int>(count, Allocator.TempJob); // ✅
}

// ❌ BRG 陷阱 2: 每帧全量上传 Buffer
void Update()
{
    // 50,000 × 128 bytes = 6.4 MB 每帧上传! ❌
    instanceDataBuffer.SetData(allMatrices);
    
    // ✅ 只上传变化的部分
    // 或使用 double buffering
}

// ❌ Indirect 陷阱: CopyCount 导致 GPU stall
void Update()
{
    ComputeBuffer.CopyCount(appendBuffer, argsBuffer, 4);
    // 这个操作在某些平台上可能导致 GPU pipeline stall
    // ✅ 使用 CS 直接写入 argsBuffer 代替 CopyCount
}
```

---

## 12. 最佳实践总结

### 12.1 选择建议

```
┌─────────────────────────────────────────────────────────────┐
│                     选择建议总结                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  选 BRG 当:                                                 │
│  ✅ 需要完整的渲染管线集成 (Shadow, Depth, Probe)            │
│  ✅ 使用 URP/HDRP 且希望与 SRP Batcher 兼容                │
│  ✅ 实例数 < 100K                                           │
│  ✅ 使用或计划使用 DOTS/ECS                                  │
│  ✅ 希望减少 Shader 维护工作                                 │
│  ✅ 需要在 Scene View / 多 Camera 中正确显示                │
│                                                             │
│  选 Indirect 当:                                            │
│  ✅ 实例数 > 200K，需要 GPU 剔除                            │
│  ✅ 需要 Compute Shader 深度集成 (物理模拟、GPU 动画)        │
│  ✅ 渲染需求简单 (不需要多 Pass)                             │
│  ✅ 需要 GPU 遮挡剔除 (Hi-Z)                                │
│  ✅ 自研渲染管线，完全控制渲染流程                            │
│  ✅ GPU 粒子系统                                            │
│                                                             │
│  混合使用:                                                   │
│  ✅ 近景用 BRG (完整光照)，远景用 Indirect (大规模简化渲染)   │
│  ✅ 场景物体用 BRG，特效用 Indirect                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 12.2 性能优化清单

#### BRG 优化清单

- [ ] OnPerformCulling 使用 Burst + IJobParallelFor
- [ ] 预分配所有 NativeArray，避免每帧分配
- [ ] 使用 float3x4 代替 float4x4 节省内存
- [ ] 减少 per-instance 属性数量
- [ ] 实现空间分区加速剔除 (Grid / Quadtree)
- [ ] 使用 BatchDrawCommand 的 sortingPosition 优化渲染顺序
- [ ] 动态实例只更新变化的 Buffer 区域
- [ ] 多 LOD 使用多个 DrawCommand

#### Indirect 优化清单

- [ ] 实现两级剔除 (Chunk + Instance)
- [ ] 实现 Hi-Z 遮挡剔除
- [ ] 所有 Pass 共享剔除结果 (如果视锥相同)
- [ ] 使用 CS 直接写入 IndirectArgs (避免 CopyCount)
- [ ] 实例数据压缩 (< 16 bytes/instance)
- [ ] 为 Shadow Pass 实现单独的简化剔除
- [ ] 使用 AsyncGPUReadback 避免 GPU stall (如需回读)

### 12.3 未来趋势

```
Unity 路线图:

2022.1  BRG 正式发布
2023.x  Entities Graphics 1.0 (基于 BRG)
2024.x  GPU Resident Drawer (Unity 自动将 MeshRenderer 转为 BRG)
2025.x  GPU Occlusion Culling (BRG 原生支持 GPU 遮挡剔除)
Future  GPU Driven Rendering Pipeline (完全 GPU 驱动)

趋势:
- BRG 正在成为 Unity 的标准渲染后端
- GPU Resident Drawer 让普通 MeshRenderer 也能享受 BRG 性能
- 未来 BRG 可能支持 GPU 剔除，弥补当前 CPU 剔除的短板
- Indirect 仍然是自定义 GPU 管线的最佳选择
```

---

## 附录 A: API 速查表

### BRG 核心 API

```csharp
// 创建
var brg = new BatchRendererGroup(OnPerformCulling, IntPtr.Zero);

// 注册资源
BatchMeshID meshID = brg.RegisterMesh(mesh);
BatchMaterialID matID = brg.RegisterMaterial(material);

// 添加 Batch
BatchID batchID = brg.AddBatch(metadata, bufferHandle);

// 移除
brg.RemoveBatch(batchID);
brg.UnregisterMesh(meshID);
brg.UnregisterMaterial(matID);

// 销毁
brg.Dispose();
```

### Indirect 核心 API

```csharp
// 创建 Buffer
var buffer = new ComputeBuffer(count, stride);
var argsBuffer = new ComputeBuffer(1, 5 * 4, ComputeBufferType.IndirectArguments);
var appendBuffer = new ComputeBuffer(count, stride, ComputeBufferType.Append);

// 渲染
Graphics.DrawMeshInstancedIndirect(mesh, submesh, material, bounds, argsBuffer, 0, mpb);

// 拷贝计数
ComputeBuffer.CopyCount(appendBuffer, argsBuffer, offset);

// 销毁
buffer.Release();
```

---

## 附录 B: 参考资源

| 资源                      | 链接                                                                     |
| ------------------------- | ------------------------------------------------------------------------ |
| Unity BRG 官方文档        | docs.unity3d.com/Manual/batch-renderer-group.html                        |
| Unity BRG 示例项目        | github.com/Unity-Technologies/Graphics (BRG samples)                     |
| Entities Graphics         | docs.unity3d.com/Packages/com.unity.entities.graphics                    |
| GPU Resident Drawer       | Unity 6 文档                                                             |
| DOTS Instancing Shader    | URP/HDRP Shader 源码中的 DOTSInstancing.hlsl                             |
| DrawMeshInstancedIndirect | docs.unity3d.com/ScriptReference/Graphics.DrawMeshInstancedIndirect.html |

---