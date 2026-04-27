---
layout:     post
title:      GPU Particle System
subtitle:   基于 Compute Shader 的 GPU 粒子系统分析
date:       2026-04-09
author:     engineyk
header-img: img/post-bg-universe.jpg
catalog: true
tags:
  - 渲染
  - GPU
  - 粒子系统
  - Compute Shader
---

# GPU Particle System

## 目录
1. [系统概述](#1-系统概述)
2. [目录结构](#2-目录结构)
3. [核心流程](#3-核心流程)
4. [粒子生命周期](#4-粒子生命周期)
5. [与 CPU 粒子对比优势](#5-与-cpu-粒子对比优势)
6. [优化点详解](#6-优化点详解)
7. [渲染管线集成](#7-渲染管线集成)
8. [关键数据结构](#8-关键数据结构)
9. [使用方式](#9-使用方式)
10. [兼容性与低端机适配](#10-兼容性与低端机适配)

---

## 1. 系统概述

GPU Particle System 是基于 **Compute Shader** 驱动的高性能粒子系统，运行在自定义渲染管线（`com.universal.render-pipeline`）之上。

与传统 CPU 粒子系统不同，该系统将粒子的**模拟、更新、剔除、排序**全部交由 GPU 完成，CPU 仅负责参数提交和 DrawCall 触发，极大降低了 CPU 负担，支持同屏数十万级粒子的实时渲染。

```
┌─────────────────────────────────────────────────────┐
│                   CPU Side                          │
│  参数设置 → Emit 请求 → DispatchCompute → DrawCall  │
└────────────────────┬────────────────────────────────┘
                     │ GPU Buffer
┌────────────────────▼────────────────────────────────┐
│                   GPU Side                          │
│  Emit Kernel → Update Kernel → Sort → Render        │
└─────────────────────────────────────────────────────┘
```

---

## 2. 目录结构

```
GpuParticle/
├── GpuParticleSystem.cs          # 系统入口，管理整个粒子系统生命周期
├── GpuParticleEmitter.cs         # 发射器，控制粒子发射参数与形状
├── GpuParticleRenderer.cs        # 渲染器，负责提交 DrawCall
├── GpuParticleUpdater.cs         # 更新器，Dispatch Compute Shader
├── GpuParticleData.cs            # 粒子数据结构定义（位置/速度/生命等）
├── GpuParticleSorter.cs          # GPU 排序（半透明粒子深度排序）
├── GpuParticlePool.cs            # 粒子池，管理 Dead/Alive 列表
├── Shaders/
│   ├── GpuParticleEmit.compute   # 发射 Kernel
│   ├── GpuParticleUpdate.compute # 更新 Kernel（物理/生命衰减）
│   ├── GpuParticleSort.compute   # Bitonic/Radix Sort Kernel
│   └── GpuParticle.shader        # 渲染 Shader（顶点/片元）
└── Resources/
    └── GpuParticleDefault.mat    # 默认材质
```

---

## 3. 核心流程

### 3.1 整体帧循环

```
每帧 Update()
│
├── 1. [CPU] 收集发射请求
│         EmitRequest { position, velocity, count, ... }
│
├── 2. [GPU] Emit Kernel
│         从 DeadList 取出空闲粒子槽
│         初始化粒子数据（位置/速度/颜色/生命）
│         写入 ParticleBuffer
│
├── 3. [GPU] Update Kernel
│         遍历 AliveList
│         更新位置 = 位置 + 速度 * deltaTime
│         更新速度（重力/阻力/湍流）
│         生命值 -= deltaTime
│         死亡粒子 → 写回 DeadList
│         存活粒子 → 写入 AliveList_New
│
├── 4. [GPU] Sort Kernel（可选，半透明）
│         对 AliveList 按深度（dot(pos, cameraForward)）排序
│         使用 Bitonic Sort 或 Radix Sort
│
└── 5. [GPU] Render
          IndirectDrawCall（DrawMeshInstancedIndirect）
          顶点 Shader 从 ParticleBuffer 读取数据
          片元 Shader 处理颜色/透明度/软粒子
```

### 3.2 Compute Shader Dispatch 流程

```csharp
// 伪代码示意
void DispatchParticleUpdate()
{
    // Step1: Reset indirect args
    cs.SetBuffer(kernelReset, "_DeadList", deadListBuffer);
    cs.Dispatch(kernelReset, 1, 1, 1);

    // Step2: Emit new particles
    cs.SetBuffer(kernelEmit, "_ParticleBuffer", particleBuffer);
    cs.SetBuffer(kernelEmit, "_DeadList", deadListBuffer);
    cs.SetBuffer(kernelEmit, "_AliveList", aliveListBuffer);
    cs.Dispatch(kernelEmit, emitCount / 64 + 1, 1, 1);

    // Step3: Simulate
    cs.SetBuffer(kernelUpdate, "_ParticleBuffer", particleBuffer);
    cs.SetBuffer(kernelUpdate, "_AliveList", aliveListBuffer);
    cs.SetBuffer(kernelUpdate, "_AliveList_New", aliveListNewBuffer);
    cs.SetBuffer(kernelUpdate, "_DeadList", deadListBuffer);
    cs.SetFloat("_DeltaTime", Time.deltaTime);
    cs.DispatchIndirect(kernelUpdate, indirectArgsBuffer);

    // Step4: Swap alive lists
    SwapBuffer(ref aliveListBuffer, ref aliveListNewBuffer);
}
```

---

## 4. 粒子生命周期

```
┌──────────────────────────────────────────────────────────────┐
│                     粒子生命周期状态机                        │
│                                                              │
│   [空闲池 DeadList]                                          │
│         │                                                    │
│         │ Emit Kernel 分配                                   │
│         ▼                                                    │
│   [初始化 Init]                                              │
│    position = emitPos + randomOffset                         │
│    velocity = emitDir * speed + randomVelocity               │
│    lifetime = startLifetime                                  │
│    color    = startColor                                     │
│    size     = startSize                                      │
│         │                                                    │
│         │ 进入 AliveList                                     │
│         ▼                                                    │
│   [存活 Alive] ◄──────────────────────┐                     │
│    每帧 Update Kernel:                │                     │
│    · position += velocity * dt        │ lifetime > 0        │
│    · velocity += gravity * dt         │                     │
│    · velocity *= (1 - drag * dt)      │                     │
│    · color = lerp(startColor,endColor)│                     │
│    · size  = lerp(startSize, endSize) │                     │
│    · lifetime -= dt                   │                     │
│         │                             │                     │
│         │ lifetime <= 0               │                     │
│         ▼                             │                     │
│   [死亡 Dead]                         │                     │
│    写回 DeadList ──────────────────────┘                     │
│    等待下次 Emit 复用                                         │
└──────────────────────────────────────────────────────────────┘
```

### 4.1 生命周期参数

| 参数              | 说明                | 典型值         |
| ----------------- | ------------------- | -------------- |
| `startLifetime`   | 粒子初始生命时长    | 1.0 ~ 5.0s     |
| `startSpeed`      | 初始速度大小        | 0.5 ~ 10.0     |
| `startSize`       | 初始大小            | 0.01 ~ 1.0     |
| `startColor`      | 初始颜色（含Alpha） | RGBA           |
| `gravityModifier` | 重力系数            | 0.0 ~ 1.0      |
| `drag`            | 空气阻力            | 0.0 ~ 0.5      |
| `maxParticles`    | 最大粒子数上限      | 10000 ~ 500000 |

---

## 5. 与 CPU 粒子对比优势

### 5.1 性能对比

| 维度           | CPU 粒子（ParticleSystem） | GPU 粒子（本系统）  |
| -------------- | -------------------------- | ------------------- |
| **模拟位置**   | CPU 主线程                 | GPU Compute Shader  |
| **最大粒子数** | ~10,000（明显卡顿）        | ~500,000+           |
| **CPU 开销**   | 高（每粒子遍历）           | 极低（仅 Dispatch） |
| **DrawCall**   | 多（批次有限）             | 1次 IndirectDraw    |
| **内存带宽**   | CPU↔GPU 频繁传输           | 数据常驻 GPU        |
| **排序**       | CPU 排序（慢）             | GPU Bitonic Sort    |
| **碰撞**       | 简单 CPU 碰撞              | GPU 深度图碰撞      |

### 5.2 核心优势

1. **零 CPU 粒子遍历**  
   所有粒子模拟在 GPU 并行执行，CPU 仅提交一次 `DispatchCompute`

2. **IndirectDraw 零回读**  
   存活粒子数量由 GPU 自己维护在 `IndirectArgsBuffer` 中，CPU 无需回读粒子数量即可发起 DrawCall

3. **粒子池复用**  
   使用 `DeadList`（AppendBuffer）+ `AliveList`（ConsumeBuffer）实现 O(1) 粒子分配与回收，无内存碎片

4. **与自定义管线深度集成**  
   直接在 `RenderPass` 中注入，支持深度图软粒子、光照注入等高级效果

---

## 6. 优化点详解

### 6.1 粒子池（Dead/Alive List）

```hlsl
// Compute Shader 中的粒子池结构
AppendStructuredBuffer<uint> _DeadList;         // 空闲粒子索引池
ConsumeStructuredBuffer<uint> _AliveList;       // 当前存活粒子索引
AppendStructuredBuffer<uint> _AliveList_New;    // 下一帧存活列表

[numthreads(64, 1, 1)]
void UpdateKernel(uint3 id : SV_DispatchThreadID)
{
    uint index = _AliveList.Consume();          // O(1) 取出存活粒子
    Particle p = _ParticleBuffer[index];
    
    // 更新粒子
    p.position += p.velocity * _DeltaTime;
    p.lifetime -= _DeltaTime;
    
    if (p.lifetime > 0)
    {
        _AliveList_New.Append(index); // 继续存活
    }
    else
    {
        _DeadList.Append(index);      // 回收到死亡池
    }
    
    _ParticleBuffer[index] = p;
}
```

### 6.2 IndirectDraw（零 CPU 回读）

```csharp
// CPU 端只需设置最大值，实际数量由 GPU 填写
GraphicsBuffer indirectArgs = new GraphicsBuffer(
    GraphicsBuffer.Target.IndirectArguments, 5, sizeof(uint));

// GPU 在 Update Kernel 结束后自动写入存活粒子数
// CPU 直接调用，无需 AsyncGPUReadback
Graphics.DrawMeshInstancedIndirect(
    quadMesh, 0, material, bounds, indirectArgs);
```

### 6.3 GPU Bitonic Sort（半透明排序）

```
粒子数 N = 2^k（向上取整到2的幂次）

Bitonic Sort 复杂度：O(N · log²N) 在 GPU 上并行
CPU Sort 复杂度：O(N · logN) 但串行

当 N = 65536：
  CPU: ~1,000,000 次比较，串行 ≈ 5ms
  GPU: 并行执行，≈ 0.3ms（RTX 3060）
```

### 6.4 软粒子（Soft Particle）

```hlsl
// 片元 Shader 中采样深度图，避免粒子与场景硬边穿插
float sceneDepth = LinearEyeDepth(
    SAMPLE_TEXTURE2D(_CameraDepthTexture, sampler_CameraDepthTexture, uv).r,
    _ZBufferParams);
float particleDepth = -TransformWorldToView(worldPos).z;
float fade = saturate((sceneDepth - particleDepth) / _SoftParticleFadeDistance);
color.a *= fade;
```

### 6.5 视锥剔除（Frustum Culling）

```hlsl
// 在 Update Kernel 中进行视锥剔除
// 超出视锥的粒子不写入 AliveList_New（但不回收，保持模拟）
bool InFrustum(float3 pos)
{
    float4 clipPos = mul(_VPMatrix, float4(pos, 1.0));
    float3 ndc = clipPos.xyz / clipPos.w;
    return all(abs(ndc.xy) < 1.0 + _CullMargin) && ndc.z > 0;
}
```

### 6.6 数据布局优化（SoA vs AoS）

```hlsl
// AoS（Array of Structures）- 缓存不友好
struct Particle {
    float3 position;  // 12 bytes
    float3 velocity;  // 12 bytes
    float4 color;     // 16 bytes
    float  lifetime;  // 4  bytes
    float  size;      // 4  bytes
}; // 总计 48 bytes，Update时全部读取

// 优化：按访问频率拆分 Buffer
// 高频更新（每帧读写）
StructuredBuffer<float3> _Positions;
StructuredBuffer<float3> _Velocities;
StructuredBuffer<float>  _Lifetimes;
// 低频（仅渲染读取）
StructuredBuffer<float4> _Colors;
StructuredBuffer<float>  _Sizes;
```

---

## 7. 渲染管线集成

### 7.1 在自定义 RenderPass 中的位置

```
Custom Render Pipeline Frame
│
├── ShadowCasterPass
├── DepthPrePass
├── GBufferPass（延迟）
├── LightingPass
├── SkyboxPass
├── TransparentPass
│   └── ── GpuParticleRenderPass  ◄── 在透明物体阶段注入
│           · 绑定 ParticleBuffer
│           · 绑定深度图（软粒子）
│           · DrawMeshInstancedIndirect
└── PostProcessPass
```

### 7.2 深度图软粒子集成

```csharp
// 在 RenderPass.Execute 中
public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
{
    CommandBuffer cmd = CommandBufferPool.Get("GpuParticle");
    
    // 绑定深度图供软粒子使用
    cmd.SetGlobalTexture("_CameraDepthTexture", depthAttachment);
    
    // 提交 Compute 更新
    gpuParticleUpdater.Dispatch(cmd);
    
    // 提交渲染
    cmd.DrawMeshInstancedIndirect(quadMesh, 0, material, 0, indirectArgsBuffer);
    
    context.ExecuteCommandBuffer(cmd);
    CommandBufferPool.Release(cmd);
}
```

---

## 8. 关键数据结构

```hlsl
// 粒子核心数据（ParticleBuffer）
struct GpuParticle
{
    float3 position;      // 世界空间位置
    float3 velocity;      // 速度向量
    float4 color;         // 当前颜色（含Alpha）
    float  lifetime;      // 剩余生命时长
    float  maxLifetime;   // 初始生命时长（用于插值）
    float  size;          // 当前大小
    float  rotation;      // 旋转角度（Billboard）
    uint   flags;         // 状态标志位
};

// 发射请求（CPU → GPU）
struct EmitRequest
{
    float3 position;      // 发射位置
    float3 direction;     // 发射方向
    float  speed;         // 初始速度
    float  lifetime;      // 生命时长
    float4 color;         // 初始颜色
    float  size;          // 初始大小
    uint   count;         // 本次发射数量
};
```

---

## 9. 使用方式

### 9.1 基础使用

```csharp
// 挂载到 GameObject
var system = gameObject.AddComponent<GpuParticleSystem>();
system.maxParticles = 100000;
system.material = particleMaterial;

// 发射粒子
system.Emit(new EmitParams
{
    position  = transform.position,
    velocity  = Vector3.up * 5f,
    lifetime  = 2.0f,
    color     = Color.red,
    count     = 500
});
```

### 9.2 性能建议

| 场景       | 建议配置                           |
| ---------- | ---------------------------------- |
| 移动端     | maxParticles ≤ 50,000，关闭排序    |
| PC/主机    | maxParticles ≤ 500,000，开启软粒子 |
| 半透明特效 | 开启 Bitonic Sort，按深度排序      |
| 不透明粒子 | 关闭排序，开启深度写入             |
| 大量小粒子 | 使用 Point Mesh，减少顶点数        |

---

## 10. 兼容性与低端机适配

### 10.1 硬件兼容性要求

| 特性                    | 最低要求                       | 说明                 |
| ----------------------- | ------------------------------ | -------------------- |
| **Compute Shader**      | OpenGL ES 3.1 / Metal / Vulkan | GPU 粒子系统核心依赖 |
| **StructuredBuffer**    | Shader Model 5.0               | 粒子数据存储         |
| **IndirectDraw**        | OpenGL ES 3.1+ / DX11+         | 零回读 DrawCall      |
| **AppendConsumeBuffer** | DX11 / Vulkan / Metal          | 粒子池管理           |
| **AsyncGPUReadback**    | Unity 2018.2+                  | 粒子数量回读（可选） |

### 10.2 平台支持矩阵

| 平台               | Compute Shader | IndirectDraw | 推荐方案       |
| ------------------ | -------------- | ------------ | -------------- |
| PC (DX11/DX12)     | ✅ 完整支持     | ✅            | GPU 粒子全功能 |
| PC (Vulkan)        | ✅ 完整支持     | ✅            | GPU 粒子全功能 |
| iOS (Metal)        | ✅ A7 芯片以上  | ✅            | GPU 粒子全功能 |
| Android (Vulkan)   | ✅ Android 7.0+ | ✅            | GPU 粒子全功能 |
| Android (GLES 3.1) | ⚠️ 部分支持     | ⚠️ 需检测     | 降级方案       |
| Android (GLES 3.0) | ❌ 不支持       | ❌            | CPU 粒子回退   |
| WebGL 1.0/2.0      | ❌ 不支持       | ❌            | CPU 粒子回退   |
| 主机 (PS5/XSX)     | ✅ 完整支持     | ✅            | GPU 粒子全功能 |

### 10.2 StructuredBuffer 不支持时的处理方案

当设备不支持 `StructuredBuffer`（即 `SystemInfo.supportsComputeShaders` 为 `false`，或 Shader Model < 5.0）时，GPU 粒子系统的粒子数据存储方式需要整体替换。

#### 10.2.1 检测与降级入口

```csharp
public static bool SupportsStructuredBuffer()
{
    // StructuredBuffer requires Compute Shader support and SM5.0+
    if (!SystemInfo.supportsComputeShaders)
        return false;

    // Check graphics device type for known unsupported cases
    var deviceType = SystemInfo.graphicsDeviceType;
    if (deviceType == GraphicsDeviceType.OpenGLES2 ||
        deviceType == GraphicsDeviceType.OpenGLES3 && SystemInfo.graphicsShaderLevel < 45)
        return false;

    return true;
}
```

#### 10.2.2 替代方案：Texture2D 模拟 StructuredBuffer

当 StructuredBuffer 不可用时，可以将粒子数据编码进 `Texture2D`（RGBA Float 格式），通过 `tex2D` 采样替代 `StructuredBuffer` 读取。这是移动端最常见的兼容方案。

**数据布局设计**

每个粒子占用 4 个像素（4 行或 4 列），每个像素存储 RGBA 4 个 float：

```
Pixel 0: position(xyz) + lifetime(w)
Pixel 1: velocity(xyz) + age(w)
Pixel 2: color(rgba)
Pixel 3: size(x) + rotation(y) + custom(zw)
```

**CPU 端实现**

```csharp
public class GpuParticleTextureFallback : IDisposable
{
    private Texture2D _particleDataTex;
    private Color[]   _pixelBuffer;
    private int       _maxParticles;

    // Each particle uses 4 pixels (RGBA float each)
    private const int PIXELS_PER_PARTICLE = 4;

    public GpuParticleTextureFallback(int maxParticles)
    {
        _maxParticles = maxParticles;
        int texWidth  = 256; // 256 particles per row
        int texHeight = Mathf.CeilToInt((float)(maxParticles * PIXELS_PER_PARTICLE) / texWidth);

        _particleDataTex = new Texture2D(texWidth, texHeight,
            TextureFormat.RGBAFloat, false, true);
        _particleDataTex.filterMode = FilterMode.Point; // Must be Point, no interpolation
        _particleDataTex.wrapMode   = TextureWrapMode.Clamp;

        _pixelBuffer = new Color[texWidth * texHeight];
    }

    /// <summary>
    /// Write particle data into pixel buffer
    /// </summary>
    public void WriteParticle(int index, GpuParticleData data)
    {
        int basePixel = index * PIXELS_PER_PARTICLE;

        // Pixel 0: position + lifetime
        _pixelBuffer[basePixel + 0] = new Color(
            data.position.x, data.position.y, data.position.z, data.lifetime);

        // Pixel 1: velocity + age
        _pixelBuffer[basePixel + 1] = new Color(
            data.velocity.x, data.velocity.y, data.velocity.z, data.age);

        // Pixel 2: color
        _pixelBuffer[basePixel + 2] = new Color(
            data.color.r, data.color.g, data.color.b, data.color.a);

        // Pixel 3: size + rotation + custom
        _pixelBuffer[basePixel + 3] = new Color(
            data.size, data.rotation, data.customData.x, data.customData.y);
    }

    /// <summary>
    /// Upload pixel buffer to GPU texture
    /// </summary>
    public void Upload()
    {
        _particleDataTex.SetPixels(_pixelBuffer);
        _particleDataTex.Apply(false); // false = no mipmap update
    }

    public void BindToMaterial(Material mat)
    {
        mat.SetTexture("_ParticleDataTex", _particleDataTex);
        mat.SetInt("_ParticleTexWidth", _particleDataTex.width);
    }

    public void Dispose()
    {
        if (_particleDataTex != null)
            Object.Destroy(_particleDataTex);
    }
}
```

**Shader 端读取**

```hlsl
// Fallback: read particle data from Texture2D instead of StructuredBuffer
sampler2D _ParticleDataTex;
int       _ParticleTexWidth;

struct GpuParticleData
{
    float3 position;
    float  lifetime;
    float3 velocity;
    float  age;
    float4 color;
    float  size;
    float  rotation;
};

GpuParticleData SampleParticleData(int particleIndex)
{
    int basePixel = particleIndex * 4; // 4 pixels per particle

    // Calculate UV for each pixel
    float2 uv0 = float2((basePixel + 0) % _ParticleTexWidth,
                        (basePixel + 0) / _ParticleTexWidth);
    float2 uv1 = float2((basePixel + 1) % _ParticleTexWidth,
                        (basePixel + 1) / _ParticleTexWidth);
    float2 uv2 = float2((basePixel + 2) % _ParticleTexWidth,
                        (basePixel + 2) / _ParticleTexWidth);
    float2 uv3 = float2((basePixel + 3) % _ParticleTexWidth,
                        (basePixel + 3) / _ParticleTexWidth);

    // Normalize UV to [0,1]
    float2 texSize = float2(_ParticleTexWidth,
                            _ParticleTexWidth); // assume square for simplicity
    uv0 = (uv0 + 0.5) / texSize;
    uv1 = (uv1 + 0.5) / texSize;
    uv2 = (uv2 + 0.5) / texSize;
    uv3 = (uv3 + 0.5) / texSize;

    float4 p0 = tex2Dlod(_ParticleDataTex, float4(uv0, 0, 0));
    float4 p1 = tex2Dlod(_ParticleDataTex, float4(uv1, 0, 0));
    float4 p2 = tex2Dlod(_ParticleDataTex, float4(uv2, 0, 0));
    float4 p3 = tex2Dlod(_ParticleDataTex, float4(uv3, 0, 0));

    GpuParticleData data;
    data.position = p0.xyz;
    data.lifetime = p0.w;
    data.velocity = p1.xyz;
    data.age      = p1.w;
    data.color    = p2;
    data.size     = p3.x;
    data.rotation = p3.y;
    return data;
}
```

#### 10.2.3 替代方案：CPU 模拟 + DrawMeshInstanced

当设备既不支持 StructuredBuffer 也不支持 Compute Shader 时，退回到 CPU 全量模拟，使用 `DrawMeshInstanced` 批量渲染：

```csharp
public class GpuParticleCpuFallback : MonoBehaviour
{
    private struct CpuParticle
    {
        public Vector3 position;
        public Vector3 velocity;
        public float   age;
        public float   lifetime;
        public Color   color;
        public float   size;
    }

    private CpuParticle[] _particles;
    private Matrix4x4[]   _matrices;    // For DrawMeshInstanced
    private Vector4[]     _colors;      // MaterialPropertyBlock per instance
    private int           _aliveCount;
    private Mesh          _mesh;
    private Material      _material;
    private MaterialPropertyBlock _mpb;

    // DrawMeshInstanced max batch size is 1023
    private const int BATCH_SIZE = 1023;

    void Update()
    {
        SimulateParticles(Time.deltaTime);
        DrawParticles();
    }

    private void SimulateParticles(float dt)
    {
        int writeIdx = 0;
        for (int i = 0; i < _aliveCount; i++)
        {
            ref var p = ref _particles[i];
            p.age += dt;
            if (p.age >= p.lifetime) continue; // Dead, skip

            // Simple Euler integration
            p.velocity += Physics.gravity * dt;
            p.position += p.velocity * dt;

            _particles[writeIdx++] = p; // Compact alive list
        }
        _aliveCount = writeIdx;
    }

    private void DrawParticles()
    {
        if (_aliveCount == 0) return;

        int drawn = 0;
        while (drawn < _aliveCount)
        {
            int batchCount = Mathf.Min(BATCH_SIZE, _aliveCount - drawn);

            for (int i = 0; i < batchCount; i++)
            {
                ref var p = ref _particles[drawn + i];
                float t = p.age / p.lifetime;
                float scale = p.size * (1.0f - t); // Shrink over lifetime

                _matrices[i] = Matrix4x4.TRS(
                    p.position,
                    Quaternion.identity,
                    Vector3.one * scale);
                _colors[i] = p.color;
            }

            _mpb.SetVectorArray("_Color", _colors);
            Graphics.DrawMeshInstanced(_mesh, 0, _material,
                _matrices, batchCount, _mpb);

            drawn += batchCount;
        }
    }
}
```

#### 10.2.4 三种方案对比

| 方案 | 粒子上限 | CPU 开销 | GPU 开销 | 适用场景 |
|------|---------|---------|---------|----------|
| **StructuredBuffer（原方案）** | 50万+ | 极低 | 低 | 高端机全功能 |
| **Texture2D 模拟** | ~10万 | 中（SetPixels） | 低 | 中端机，支持GLES3.0 |
| **CPU 模拟 + DrawMeshInstanced** | ~1万 | 高 | 低 | 低端机兜底方案 |
| **Unity 内置 ParticleSystem** | ~5千 | 高 | 低 | 最终兜底 |

#### 10.2.5 统一接口封装

```csharp
public interface IGpuParticleBackend : IDisposable
{
    void Emit(Vector3 position, Vector3 velocity, float lifetime, Color color);
    void Update(float deltaTime);
    void Render(Camera camera);
    int  AliveCount { get; }
}

public static class GpuParticleBackendFactory
{
    public static IGpuParticleBackend Create(int maxParticles)
    {
        if (GpuParticleCompatibility.IsSupported())
        {
            Debug.Log("[GpuParticle] Using StructuredBuffer backend.");
            return new GpuParticleStructuredBufferBackend(maxParticles);
        }

        if (SystemInfo.graphicsShaderLevel >= 30) // GLES 3.0+
        {
            Debug.Log("[GpuParticle] Using Texture2D fallback backend.");
            return new GpuParticleTextureFallbackBackend(
                Mathf.Min(maxParticles, 10000));
        }

        Debug.Log("[GpuParticle] Using CPU fallback backend.");
        return new GpuParticleCpuFallbackBackend(
            Mathf.Min(maxParticles, 1000));
    }
}
```

### 10.3 运行时兼容性检测

```csharp
public class GpuParticleCompatibility
{
    /// <summary>
    /// Check if current device supports GPU particle system
    /// </summary>
    public static bool IsSupported()
    {
        // Check Compute Shader support
        if (!SystemInfo.supportsComputeShaders)
        {
            Debug.LogWarning("[GpuParticle] Compute Shader not supported, fallback to CPU particle.");
            return false;
        }

        // Check StructuredBuffer support
        if (!SystemInfo.supportsSetConstantBuffer)
        {
            Debug.LogWarning("[GpuParticle] StructuredBuffer not supported.");
            return false;
        }

        // Check IndirectDraw support
        if (!SystemInfo.supportsIndirectArgumentsBuffer)
        {
            Debug.LogWarning("[GpuParticle] IndirectDraw not supported, fallback to CPU count.");
            // 可降级为 CPU 回读粒子数量后 DrawMeshInstanced
        }

        // Check GPU memory (low-end device threshold: 1GB)
        if (SystemInfo.graphicsMemorySize < 1024)
        {
            Debug.LogWarning("[GpuParticle] Low GPU memory detected: " + SystemInfo.graphicsMemorySize + "MB");
            return false;
        }

        return true;
    }

    /// <summary>
    /// Get recommended quality level based on device capability
    /// </summary>
    public static GpuParticleQuality GetRecommendedQuality()
    {
        int gpuMemory = SystemInfo.graphicsMemorySize;
        int processorCount = SystemInfo.processorCount;
        string gpuName = SystemInfo.graphicsDeviceName.ToLower();

        // High-end: PC / flagship mobile (Snapdragon 8 Gen series, Apple A15+)
        if (gpuMemory >= 4096 || gpuName.Contains("rtx") || gpuName.Contains("rx 6"))
            return GpuParticleQuality.High;

        // Mid-range: Snapdragon 7 series, Apple A13, Mali-G77+
        if (gpuMemory >= 2048)
            return GpuParticleQuality.Medium;

        // Low-end: entry-level mobile
        return GpuParticleQuality.Low;
    }
}

public enum GpuParticleQuality
{
    High,    // 全功能，50万粒子，开启排序+软粒子
    Medium,  // 中等，10万粒子，开启软粒子，关闭排序
    Low,     // 低配，1万粒子，关闭所有高级特性
    Fallback // CPU 粒子回退
}
```

### 10.4 分级质量配置

```csharp
[System.Serializable]
public class GpuParticleQualitySettings
{
    public static readonly GpuParticleQualitySettings High = new GpuParticleQualitySettings
    {
        maxParticles        = 500000,
        enableSort          = true,
        enableSoftParticle  = true,
        enableFrustumCull   = true,
        simulationStepMode  = SimulationStep.PerFrame,
        textureResolution   = 512,
    };

    public static readonly GpuParticleQualitySettings Medium = new GpuParticleQualitySettings
    {
        maxParticles        = 100000,
        enableSort          = false,   // 关闭 GPU 排序，节省带宽
        enableSoftParticle  = true,
        enableFrustumCull   = true,
        simulationStepMode  = SimulationStep.PerFrame,
        textureResolution   = 256,
    };

    public static readonly GpuParticleQualitySettings Low = new GpuParticleQualitySettings
    {
        maxParticles        = 10000,
        enableSort          = false,
        enableSoftParticle  = false,   // 关闭软粒子，省去深度图采样
        enableFrustumCull   = true,
        simulationStepMode  = SimulationStep.EveryOtherFrame, // 隔帧更新
        textureResolution   = 128,
    };

    public int   maxParticles;
    public bool  enableSort;
    public bool  enableSoftParticle;
    public bool  enableFrustumCull;
    public SimulationStep simulationStepMode;
    public int   textureResolution;
}

public enum SimulationStep
{
    PerFrame,         // 每帧更新（默认）
    EveryOtherFrame,  // 隔帧更新（低端机省电）
    FixedTimeStep,    // 固定时间步长（稳定性优先）
}
```

### 10.5 低端机关键优化策略

#### 10.5.1 隔帧模拟（Temporal Simulation）

```csharp
private int _frameCounter = 0;

void Update()
{
    _frameCounter++;

    // Low-end: simulate every other frame, compensate with 2x deltaTime
    if (_qualitySettings.simulationStepMode == SimulationStep.EveryOtherFrame
        && _frameCounter % 2 != 0)
    {
        return; // Skip simulation this frame
    }

    float simulateDeltaTime = _qualitySettings.simulationStepMode
        == SimulationStep.EveryOtherFrame
        ? Time.deltaTime * 2.0f
        : Time.deltaTime;

    _computeShader.SetFloat("_DeltaTime", simulateDeltaTime);
    DispatchParticleUpdate();
}
```

#### 10.5.2 粒子数量动态缩减

```csharp
/// <summary>
/// Dynamically reduce particle count based on current frame rate
/// </summary>
public class GpuParticleAdaptiveScaler
{
    private const float TARGET_FPS     = 30.0f;
    private const float SCALE_UP_FPS   = 35.0f;
    private const float SCALE_DOWN_FPS = 25.0f;
    private const float SCALE_STEP     = 0.1f;
    private const float MIN_SCALE      = 0.1f;
    private const float MAX_SCALE      = 1.0f;

    private float _currentScale = 1.0f;
    private float _smoothFps    = 60.0f;

    public float Update(float deltaTime)
    {
        // Smooth FPS to avoid jitter
        _smoothFps = Mathf.Lerp(_smoothFps, 1.0f / deltaTime, 0.1f);

        if (_smoothFps < SCALE_DOWN_FPS)
        {
            // FPS too low, reduce particle count
            _currentScale = Mathf.Max(MIN_SCALE, _currentScale - SCALE_STEP * deltaTime);
        }
        else if (_smoothFps > SCALE_UP_FPS)
        {
            // FPS sufficient, gradually restore particle count
            _currentScale = Mathf.Min(MAX_SCALE, _currentScale + SCALE_STEP * 0.5f * deltaTime);
        }

        return _currentScale;
    }
}
```

#### 10.5.3 GPU 内存预算控制

```csharp
/// <summary>
/// Calculate GPU buffer memory usage and warn if exceeding budget
/// </summary>
public static long CalculateBufferMemory(int maxParticles)
{
    // GpuParticle struct: 48 bytes
    long particleBuffer = (long)maxParticles * 48;
    // AliveList x2 + DeadList: uint = 4 bytes each
    long indexBuffers   = (long)maxParticles * 4 * 3;
    // IndirectArgs: 5 * uint
    long indirectBuffer = 5 * 4;

    long totalBytes = particleBuffer + indexBuffers + indirectBuffer;
    return totalBytes;
}

// Low-end device memory budget reference
// maxParticles = 10000  → ~720 KB  ✅ Safe
// maxParticles = 100000 → ~7.2 MB  ✅ Safe
// maxParticles = 500000 → ~36  MB  ⚠️ High-end only
```

### 10.6 CPU 粒子回退方案

```csharp
public class GpuParticleSystem : MonoBehaviour
{
    private bool _useGpuParticle;
    private ParticleSystem _cpuFallback; // Unity built-in fallback

    void Awake()
    {
        _useGpuParticle = GpuParticleCompatibility.IsSupported();

        if (_useGpuParticle)
        {
            InitGpuParticle();
        }
        else
        {
            // Fallback to Unity built-in ParticleSystem
            _cpuFallback = gameObject.AddComponent<ParticleSystem>();
            ApplyCpuFallbackSettings(_cpuFallback);
            Debug.Log("[GpuParticle] Using CPU particle fallback.");
        }
    }

    public void Emit(EmitParams param)
    {
        if (_useGpuParticle)
        {
            EmitGpu(param);
        }
        else
        {
            // Map GPU emit params to CPU ParticleSystem
            var cpuParam = new ParticleSystem.EmitParams();
            cpuParam.position = param.position;
            cpuParam.velocity = param.velocity;
            _cpuFallback.Emit(cpuParam, Mathf.Min(param.count, 500)); // Limit count for CPU
        }
    }
}
```

### 10.7 Android 特殊适配

```csharp
void ApplyAndroidSpecificSettings()
{
    if (Application.platform != RuntimePlatform.Android) return;

    string gpuName = SystemInfo.graphicsDeviceName.ToLower();

    // Adreno GPU: good Compute Shader support
    if (gpuName.Contains("adreno"))
    {
        // Adreno 6xx+ supports full GPU particle
        // Adreno 5xx: reduce maxParticles
        if (gpuName.Contains("adreno 5"))
            _settings.maxParticles = Mathf.Min(_settings.maxParticles, 50000);
    }
    // Mali GPU: Compute Shader performance varies
    else if (gpuName.Contains("mali"))
    {
        // Mali-G77+ is fine, older Mali may have issues
        if (gpuName.Contains("mali-t") || gpuName.Contains("mali-4"))
        {
            // Very old Mali, force CPU fallback
            _useGpuParticle = false;
            return;
        }
        // Disable sort on Mali to avoid bandwidth issues
        _settings.enableSort = false;
    }
    // PowerVR: limited Compute Shader support
    else if (gpuName.Contains("powervr"))
    {
        _useGpuParticle = false; // Force CPU fallback
    }
}
```

### 10.8 低端机适配总结

```
设备检测流程
│
├── 不支持 Compute Shader？
│   └── → CPU 粒子回退（Unity ParticleSystem）
│
├── GPU 内存 < 1GB？
│   └── → CPU 粒子回退
│
├── 低端机（GPU 内存 1~2GB）
│   ├── maxParticles = 10,000
│   ├── 关闭 GPU Sort
│   ├── 关闭软粒子
│   ├── 隔帧模拟
│   └── 动态粒子数量缩减
│
├── 中端机（GPU 内存 2~4GB）
│   ├── maxParticles = 100,000
│   ├── 关闭 GPU Sort
│   ├── 开启软粒子
│   └── 每帧模拟
│
└── 高端机（GPU 内存 4GB+）
    ├── maxParticles = 500,000
    ├── 开启 GPU Sort
    ├── 开启软粒子
    └── 全功能
```

| 优化手段          | 低端机收益 | 实现复杂度 |
| ----------------- | ---------- | ---------- |
| 降低 maxParticles | ⭐⭐⭐⭐⭐      | 低         |
| 关闭 GPU Sort     | ⭐⭐⭐⭐       | 低         |
| 关闭软粒子        | ⭐⭐⭐        | 低         |
| 隔帧模拟          | ⭐⭐⭐        | 中         |
| 动态粒子缩减      | ⭐⭐⭐        | 中         |
| CPU 粒子回退      | ⭐⭐⭐⭐⭐      | 高         |
| SoA 数据布局      | ⭐⭐         | 高         |

---

## 参考资料

- [GPU Gems 3 - Chapter 28: Streaming Architectures and Technology Trends](https://developer.nvidia.com/gpugems/gpugems3)
- [Unity Compute Shader Documentation](https://docs.unity3d.com/Manual/class-ComputeShader.html)
- [GDC 2014 - GPU-Based Procedural Placement in Horizon Zero Dawn](https://www.gdcvault.com/)
- [Bitonic Sort on GPU - NVIDIA Developer Blog](https://developer.nvidia.com/blog)