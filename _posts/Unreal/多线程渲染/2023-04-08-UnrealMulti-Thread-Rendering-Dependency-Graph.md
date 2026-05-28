---
layout:     post
title:      Unreal Multi Thread Renderer RDG
subtitle:   Rendering Dependency Graph
date:       2023-4-8
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - Multi-Thread-Rendering
---


<center> Rendering Dependency Graph 渲染依赖性图表</center>

# <center> Overview</center>

```
1. Overview                 |
                            |   Pipeline
                            |   What && How && Why
                            |
2. RDGEngine                |
                            |   → 2.1 Builder：心脏和发动机，大管家
                            |       负责收集渲染Pass和参数，编译Pass、数据
                            |       处理资源依赖，裁剪和优化各类数据，提供执行接口
                            |       → RDGBuilder Pattern: 构建参数 AddPass
                            |   → 2.2 Pass System
                            |       → Pass Types
                            |       → Pass Declaration 单个Pass
                            |       → Connecting Pass 多个Pass连接
                            |       → Pass Execution
                            |       → Pass Merging
                            |   → 2.3 Resources Management
                            |       → Transient Resource Pool
                            |       → Resource Lifetime Tracking
                            |       → Memory Aliasing
                            |       → External vs Transient Resources
                            |   → 2.4 Dependency Resolution
                            |       → Implicit Dependencies
                            |       → Dependency Graph Construction Algorithm
                            |       → Topological Sort for Execution Order
                            |       → Dead Pass Culling
                            |   → 2.5 Execution & Scheduling
                            |       → Barrier Generation
                            |       → Barrier Batching
                            |       → Async Compute Scheduling
                            |       → Parallel Command Recording
                            |   → 2.6 Directed Acyclic Graph (DAG)
                            |   → 2.7 Compile
3. Implementation           |
                            |   → Traditional Immediate Mode Rendering
                            |   → RDG Approach
                            |   → Feature Comparison
```

# 一. Overview

## Pipeline

```
┌──────────────────────────────────────────────────┐
│                    Application Layer             │
│         (Game Logic, Scene Management, Culling)  │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│                  RDG Builder / Setup Phase      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Pass A   │  │ Pass B   │  │ Pass C   │  ...  │
│  │ (Shadow) │  │ (GBuffer)│  │ (Light)  │       │
│  └──────────┘  └──────────┘  └──────────┘       │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│                  Compile Phase                  │
│  ┌────────────────┐  ┌────────────────┐         │
│  │ Dependency     │  │ Resource       │         │
│  │ Resolution     │  │ Lifetime Calc  │         │
│  └────────────────┘  └────────────────┘         │
│  ┌────────────────┐  ┌────────────────┐         │
│  │ Dead Pass      │  │ Barrier        │         │
│  │ Culling        │  │ Generation     │         │
│  └────────────────┘  └────────────────┘         │
│  ┌────────────────┐                             │
│  │ Memory Aliasing│                             │
│  │ & Allocation   │                             │
│  └────────────────┘                             │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│                  Execute Phase                  │
│  ┌────────────────┐  ┌────────────────┐         │
│  │ Command Buffer │  │ GPU Resource   │         │
│  │ Recording      │  │ Instantiation  │         │
│  └────────────────┘  └────────────────┘         │
│  ┌────────────────┐                             │
│  │ Queue Submit   │                             │
│  └────────────────┘                             │
└─────────────────────────────────────────────────┘
```


## Summary

Rendering Dependency Graph，渲染依赖性图表

- 基于有向无环图（Directed Acyclic Graph，DAG）的调度系统，用于执行渲染管线的整帧优化
- 利用现代图形 API（DirectX 12、Vulkan 和 Metal 2），实现自动异步计算调度以及更高效的内存管理和屏障管理来提升性能
- 传统图形 API（DirectX 11、OpenGL）要求驱动器调用复杂的启发法，以确定何时以及如何在 GPU 上执行关键的调度操作
  - 清空缓存、管理和再使用内存、执行布局转换等
  - 接口存在即时模式特性，因此需要复杂的记录和状态跟踪才能处理各种极端情况，最终会对性能产生负面影响并阻碍并行
- 现代图形 API（DirectX 12、Vulkan 和 Metal 2）将低级 GPU 管理的负担转移到应用程序，使应用程序可以利用渲染管线的高级情境来驱动调度，从而提高性能并简化渲染堆栈
- **RDG 的理念**：不在 GPU 上立即执行 Pass，而是先收集所有需要渲染的 Pass，然后按照依赖的顺序对图表进行编译和执行，期间会执行各类裁剪和优化
- 依赖性图表数据结构的整帧认知与现代图形 API 的能力相结合，使 RDG 能够在后台执行复杂的调度任务：
  - 执行异步计算通道的自动调度和隔离
  - 在帧的不相交间隔期间，使资源之间的别名内存保持活跃状态
  - 尽早启动屏障和布局转换，避免管线延迟
- RDG 并非 UE 独创的概念和技术，早在 2017 年的 GDC 中，寒霜就已经实现并应用了 Frame Graph（帧图）的技术
  - Frame Graph 旨在将引擎的各类渲染功能（Feature）和上层渲染逻辑（Renderer）与下层资源（Shader、RenderContext、图形 API 等）隔离开来
  - FrameGraph 是高层级的 Render Pass 和资源的代表，包含了一帧中所用到的所有信息
- UE 的 RDG 正是基于 Frame Graph 之上定制和实现而成的
- RDG 已经被大量普及，包含场景渲染、后处理、光追等等模块都使用了 RDG 代替原本直接调用 RHI 命令的方式


## What is a Rendering Dependency Graph? 什么是渲染依赖图？

A **Rendering Dependency Graph (RDG)**, also known as a **Frame Graph** or **Render Graph**, is a high-level abstraction layer for organizing and executing rendering operations in a modern graphics pipeline. It models the entire frame's rendering workload as a **Directed Acyclic Graph (DAG)**, where:
A **Rendering Dependency Graph (RDG)**，也称为 **Frame Graph** 或 **Render Graph**，是一种用于组织和执行现代图形管线中渲染操作的高层抽象层。它将整帧的渲染工作负载建模为一个**有向无环图（DAG）**：

- **节点（Nodes）**：represent rendering passes (compute, raster, copy, etc.) 代表渲染 Pass（Compute、Raster、Copy 等）
- **边（Edges）**：represent resource dependencies between passes 代表 Pass 之间的资源依赖关系


The framework automatically handles: 框架自动处理以下内容：
- Resource allocation and deallocation (transient resources)  资源分配与释放（瞬态资源）
- Execution ordering based on dependencies 基于依赖关系的执行顺序
- Synchronization barriers (pipeline barriers, layout transitions) 同步屏障（Pipeline Barriers、Layout Transitions）
- Dead code elimination (culling unused passes) 无效代码消除（裁剪未使用的 Pass）
- Resource aliasing and memory optimization 资源别名与内存优化

## Why Use a Rendering Dependency Graph? 为什么使用RDG？

| Problem (Traditional)               | 传统方式的问题              | Solution (RDG)                           | RDG 的解决方案           |
| ----------------------------------- | --------------------------- | ---------------------------------------- | ------------------------ |
| Manual resource lifetime management | 手动管理资源生命周期        | Automatic transient resource allocation  | 自动瞬态资源分配         |
| Hardcoded render pass ordering      | 硬编码渲染 Pass 顺序        | Automatic dependency-driven scheduling   | 基于依赖关系的自动调度   |
| Manual barrier/transition insertion | 手动插入 Barrier/Transition | Automatic synchronization                | 自动同步                 |
| Difficult to add/remove features    | 难以添加/删除渲染特性       | Modular pass-based architecture          | 模块化的 Pass 架构       |
| Wasted GPU memory                   | GPU 内存浪费                | Resource aliasing & memory pooling       | 资源别名与内存池化       |
| Hard to parallelize CPU work        | CPU 工作难以并行化          | Graph enables parallel command recording | 图结构驱动的并行命令录制 |

--- 


## Debugger

| 控制台变量                    | 描述                                                                                                                 |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| r.RDG.AsyncCompute            | 控制异步计算策略：0-禁用；1-为异步计算Pass启用标记（默认）；2-开启所有使用compute命令列表的计算通道。                |
| r.RDG.Breakpoint              | 当满足某些条件时，断点到调试器的断点位置。0-禁用，1~4-不同的特殊调试模式。                                           |
| r.RDG.ClobberResources        | 在分配时间用指定的清理颜色清除所有渲染目标和纹理/缓冲UAV。用于调试。                                                 |
| r.RDG.CullPasses              | RDG是否开启裁剪无用的Pass。0-禁用，1-开启（默认）。                                                                  |
| r.RDG.Debug                   | 允许输出在连接和执行过程中发现的效率低下的警告。                                                                     |
| r.RDG.Debug.FlushGPU          | 开启每次Pass执行后刷新指令到GPU。当设置(r.RDG.AsyncCompute=0)时禁用异步计算。                                        |
| r.RDG.Debug.GraphFilter       | 将某些调试事件过滤到特定的图中。                                                                                     |
| r.RDG.Debug.PassFilter        | 将某些调试事件过滤到特定的Pass。                                                                                     |
| r.RDG.Debug.ResourceFilter    | 将某些调试事件过滤到特定的资源。                                                                                     |
| r.RDG.DumpGraph               | 将多个可视化日志转储到磁盘。0-禁用，1-显示生产者、消费者Pass依赖，2-显示资源状态和转换，3-显示图形、异步计算的重叠。 |
| r.RDG.ExtendResourceLifetimes | RDG将把资源生命周期扩展到图的全部长度。会增加内存的占用。                                                            |
| r.RDG.ImmediateMode           | 在创建Pass时执行Pass。当在Pass的Lambda中崩溃时，连接代码的调用堆栈非常有用。                                         |
| r.RDG.MergeRenderPasses       | 图形将合并相同的、连续的渲染通道到一个单一的渲染通道。0-禁用，1-开启（默认）。                                       |
| r.RDG.OverlapUAVs             | RDG将在需要时重叠UAV的工作。如果禁用，UAV屏障总是插入。                                                              |
| r.RDG.TransitionLog           | 输出资源转换到控制台。                                                                                               |
| r.RDG.VerboseCSVStats         | 控制RDG的CSV分析统计的详细程度。0-为图形执行生成一个CSV配置文件，1-为图形执行的每个阶段生成一个CSV文件。             |



## Three-Phase Pipeline 三阶段管线

The RDG operates in three distinct phases per frame:

### 1. Setup (Declaration)
- Passes declare their resource inputs/outputs          声明资源
- Resources are created as **virtual handles**          虚拟句柄
- No GPU work is performed                              不执行任何 GPU 工作
- Runs on CPU, can be parallelized                      在 CPU 上，并行处理

### 2. Compile (Analysis)
- Build dependency graph from declared inputs/outputs   根据声明的输入/输出构建依赖图
- Calculate resource lifetimes                          计算资源生命周期
- Cull unreferenced passes                              裁剪未被引用的 Pass（Dead Pass Culling）
- Determine execution order (topological sort)          确定执行顺序（拓扑排序）
- Generate synchronization barriers                     生成同步屏障（Barrier）
- Perform memory aliasing analysis                      执行内存别名分析（Memory Aliasing）

### 3. Execute (Recording & Submission)
- Allocate actual GPU resources                         分配实际 GPU 资源
- Record command buffers                                录制命令缓冲区（Command Buffer）
- Insert barriers and transitions                       插入屏障和状态转换
- Submit to GPU queues                                  提交到 GPU 队列

# 二. RDGEngine

## 2.1 Builder

### 1. Builder Pattern
**The graph is constructed using a builder pattern:**

```c++
// ----创建FRDGBuilder的局部对象----
FRDGBuilder GraphBuilder(RHICmdList, RDG_EVENT_NAME("GraphBuilder_RenderMyStuff"));
// ----增加Pass----
GraphBuilder.AddPass(...);
GraphBuilder.AddPass(...);
// ----增加资源提取----
GraphBuilder.QueueTextureExtraction(...);
// ---- 执行FRDGBuilder ----
GraphBuilder.Execute();
```

```cpp
class RDGBuilder {
public:
    // Create a new transient texture   // 创建瞬态纹理（虚拟句柄，编译阶段才分配实际内存）
    RDGTextureRef CreateTexture(const FRDGTextureDesc& desc, const char* name);
    // Create a new transient buffer    // 创建瞬态缓冲区
    RDGBufferRef CreateBuffer(const FRDGBufferDesc& desc, const char* name);
    // Import an external resource      // 导入外部资源（跨帧持久资源，如 SwapChain、历史帧缓冲）
    RDGTextureRef RegisterExternalTexture(FRHITexture* texture, const char* name);
    // Add a render pass                // 添加渲染 Pass
    template<typename ParameterStruct>
    void AddPass(
        const char* name,
        const ParameterStruct* parameters,
        ERDGPassFlags flags,
        std::function<void(const ParameterStruct&, FRHICommandList&)> executeLambda
    );
};
```

---

## 2.2 Pass System

### 1. Pass Types

```cpp
enum class ERDGPassFlags : uint32_t {
    None          = 0,
    Raster        = 1 << 0,   // Uses render targets, draw calls   // 光栅化 Pass，使用渲染目标和 DrawCall      
    Compute       = 1 << 1,   // Uses compute dispatch             // 计算 Pass，使用 Compute Dispatch
    AsyncCompute  = 1 << 2,   // Runs on async compute queue       // 异步计算 Pass，运行在独立的 Async Compute 队列  
    Copy          = 1 << 3,   // Transfer operations               // 传输操作（资源拷贝、上传、回读）  
    NeverCull     = 1 << 4,   // Cannot be culled (e.g., readback) // 不可被裁剪（如 Readback Pass）
    SkipBarriers  = 1 << 5,   // Manual barrier management         // 手动管理 Barrier  
};
```

- **Raster Pass**: Traditional draw calls with render targets       // 传统光栅化 DrawCall，带渲染目标
- **Compute Pass**: Dispatch compute shaders                        // Dispatch 计算着色器
- **Copy/Transfer Pass**: Resource copies, uploads, readbacks       // 资源拷贝、上传、回读
- **Async Compute Pass**: Runs on async compute queue               // 运行在异步计算队列上

A **Pass** is the fundamental unit of work: Pass 是工作的基本单元

```cpp
struct RenderPass {
    std::string name;
    PassType type;                      // Raster, Compute, Copy, AsyncCompute
    std::vector<ResourceRef> inputs;    // 输入资源（SRV）
    std::vector<ResourceRef> outputs;   // 输出资源（RTV/UAV）
    ExecuteCallback execute;            // Lambda containing actual GPU commands
};
```

### 2. Connecting Passes

Passes are connected implicitly through shared resource references: Pass 通过共享资源引用隐式连接，无需手动声明依赖关系：

```cpp
void SetupFrame(RDGBuilder& builder) {
    // Pass 1: GBuffer 写入 albedo/normal/depth
    auto [albedo, normal, depth] = AddGBufferPass(builder, view);
    
    // Pass 2: SSAO (reads depth, writes SSAO texture)
    // → 自动建立 GBuffer → SSAO 的依赖
    auto ssaoTexture = AddSSAOPass(builder, depth);
    
    // Pass 3: Lighting (reads GBuffer + SSAO)
    // → 自动建立 GBuffer/SSAO → Lighting 的依赖
    auto sceneColor = AddLightingPass(builder, albedo, normal, depth, ssaoTexture);
    
    // Pass 4: Post Processing
    auto finalColor = AddPostProcessPass(builder, sceneColor);
    
    // Pass 5: Present
    AddPresentPass(builder, finalColor, swapChainTarget);
}
```

```c++
// 增加 RDG Pass 示例
GraphBuilder.AddPass(
    RDG_EVENT_NAME("MyRDGPass"),
    PassParameters,
    ERDGPassFlags::Raster,
    // Pass的Lambda
    // Pass 的执行 Lambda（编译阶段不执行，Execute 阶段才调用）
    [PixelShader, PassParameters, PipelineState] (FRHICommandListImmediate& RHICmdList)
    {
        // 设置视口.
        RHICmdList.SetViewport(0, 0, 0.0f, 1024, 768, 1.0f);

        // 设置PSO.
        SetScreenPassPipelineState(RHICmdList, PipelineState);

        // 设置着色器参数.
        SetShaderParameters(RHICmdList, PixelShader, PixelShader.GetPixelShader(), *PassParameters);

        // 绘制矩形区域.
        DrawRectangle(RHICmdList, 0, 0, 1024, 768, 0, 0, 1.0f, 1.0f, FIntPoint(1024, 768), FIntPoint(1024, 768), PipelineState.VertexShader, EDRF_Default);
    });
```

### 3. Pass Declaration Example 声明示例

```cpp
void AddGBufferPass(RDGBuilder& builder, const ViewInfo& view) {
    // Declare outputs
    // 声明输出资源（此时只创建虚拟句柄，不分配 GPU 内存）
    RDGTextureRef albedoRT = builder.CreateTexture(
        FRDGTextureDesc::Create2D(width, height, PF_R8G8B8A8_UNORM),
        "GBuffer_Albedo"
    );
    
    RDGTextureRef normalRT = builder.CreateTexture(
        FRDGTextureDesc::Create2D(width, height, PF_R16G16B16A16_FLOAT),
        "GBuffer_Normal"
    );
    
    RDGTextureRef depthRT = builder.CreateTexture(
        FRDGTextureDesc::Create2D(width, height, PF_D32_FLOAT),
        "GBuffer_Depth"
    );
    
    // Declare pass parameters（绑定资源视图）
    auto* params = builder.AllocParameters<FGBufferPassParams>();
    params->albedoTarget = builder.CreateRTV(albedoRT);  // 颜色附件
    params->normalTarget = builder.CreateRTV(normalRT);  // 法线附件
    params->depthTarget  = builder.CreateDSV(depthRT);   // 深度附件
    
    // Add the pass
    builder.AddPass(
        "GBufferPass",
        params,
        ERDGPassFlags::Raster,
        [view](const FGBufferPassParams& params, FRHICommandList& cmdList) {
            // Actual rendering commands（Execute 阶段执行）
            cmdList.SetRenderTargets(params.albedoTarget, params.normalTarget, params.depthTarget);
            for (const auto& mesh : view.visibleMeshes) {
                cmdList.DrawIndexed(mesh);
            }
        }
    );
}
```


### 4. Pass Execution Lambda

The execution lambda captures the actual GPU work: 执行 Lambda 封装了实际的 GPU 工作：

```cpp
builder.AddPass(
    RDG_EVENT_NAME("DeferredLighting"),
    passParameters,
    ERDGPassFlags::Compute,
    [this, viewInfo, lightData](FRHIComputeCommandList& cmdList) {
        // Set compute shader
        cmdList.SetComputeShader(deferredLightingCS);
        
        // Bind parameters (auto-bound from parameter struct)
        SetShaderParameters(cmdList, deferredLightingCS, *passParameters);
        
        // Dispatch（每个线程组处理 8×8 像素）
        uint32_t groupsX = DivideAndRoundUp(viewInfo.width, 8);
        uint32_t groupsY = DivideAndRoundUp(viewInfo.height, 8);
        cmdList.Dispatch(groupsX, groupsY, 1);
    }
);
```


### 5. Parameter Struct Pattern (UE5 Style)

Unreal Engine 5 uses a macro-based parameter declaration:

```cpp
BEGIN_SHADER_PARAMETER_STRUCT(FDeferredLightingParams, )
    SHADER_PARAMETER_RDG_TEXTURE(Texture2D, GBufferA)           // SRV input
    SHADER_PARAMETER_RDG_TEXTURE(Texture2D, GBufferB)           // SRV input
    SHADER_PARAMETER_RDG_TEXTURE(Texture2D, SceneDepth)         // SRV input
    SHADER_PARAMETER_RDG_TEXTURE(Texture2D, SSAOTexture)        // SRV input
    SHADER_PARAMETER_RDG_TEXTURE_UAV(RWTexture2D, SceneColor)   // UAV output
    SHADER_PARAMETER_STRUCT_REF(FViewUniformShaderParameters, View)
    RENDER_TARGET_BINDING_SLOTS()                               // RTV slots
END_SHADER_PARAMETER_STRUCT()
```

### 6. AddPass 源码分析

FRDGBuilder::AddPass是向RDG系统增加一个包含Pass参数和Lambda的Pass

**流程：**
1. 根据传入参数构建 RDG Pass 实例
2. 设置该 Pass 的纹理和缓冲区数据
3. 建立 Pass 的依赖句柄
4. 若为立即模式（`GRDGImmediateMode`），直接执行该 Pass

```c++
// Engine\Source\Runtime\RenderCore\Public\RenderGraphBuilder.inl

template <typename ParameterStructType, typename ExecuteLambdaType>
FRDGPassRef FRDGBuilder::AddPass(FRDGEventName&& Name, const ParameterStructType* ParameterStruct, ERDGPassFlags Flags, ExecuteLambdaType&& ExecuteLambda)
{
    using LambdaPassType = TRDGLambdaPass<ParameterStructType, ExecuteLambdaType>;

    (......)

    // 分配RDG Pass实例.
    FRDGPass* Pass = Allocator.AllocObject<LambdaPassType>(
        MoveTemp(Name),
        ParameterStruct,
        OverridePassFlags(Name.GetTCHAR(), Flags, LambdaPassType::kSupportsAsyncCompute),
        MoveTemp(ExecuteLambda));

    // 加入Pass列表.
    Passes.Insert(Pass);
    // 设置Pass.
    SetupPass(Pass);
    
    return Pass;
}
```

### RDG Pass
RDG Pass模块涉及了屏障、资源转换、RDGPass等概念：

- RDG Pass 和渲染 Pass 并非一一对应关系，有可能多个 RDG Pass 合并成一个渲染 Pass（详见后面章节）
- RDG Pass 最复杂的部分在于多线程处理、资源状态转换以及依赖处理

[RDG Pass](<../../code/RDG/RDG Pass.md>)

---


## 2.3 Resouces Management 资源管理

Resources in RDG are **virtual handles** until execution:

```cpp
struct RDGResource {
    std::string name;
    ResourceDesc desc;          // Texture/Buffer description   // 纹理/缓冲区描述
    bool isExternal;            // Imported or transient        // 是否为导入的外部资源
    bool isTransient;           // Managed by the graph         // 是否由图管理（瞬态资源）
    ResourceLifetime lifetime;  // First use → last use         // 首次使用 → 最后使用
};
```

Resource categories:
- **Transient Resources**: Created and destroyed within a single frame // 单帧内创建和销毁
- **External/Imported Resources**: Persist across frames (e.g., swap chain, history buffers)
- **Extracted Resources**: Transient resources promoted to persist beyond the frame // 瞬态资源被提升为跨帧持久资源
Resources are accessed through typed views:

| View Type                     | Description                       |
| ----------------------------- | --------------------------------- |
| `SRV` (Shader Resource View)  | Read-only texture/buffer access   |
| `UAV` (Unordered Access View) | Read-write access in compute      |
| `RTV` (Render Target View)    | Write as color attachment         |
| `DSV` (Depth Stencil View)    | Write as depth/stencil attachment |
| `CBV` (Constant Buffer View)  | Uniform/constant buffer access    |

### 1. Transient Resource Pool 瞬态资源池

Transient resources are allocated from a pool and reused across frames: 瞬态资源从资源池中分配，并在帧间复用：

```cpp
class TransientResourcePool {
public:
    // Allocate a texture matching the description
    GPUTexture* Allocate(const TextureDesc& desc);
    
    // Return a texture to the pool
    void Release(GPUTexture* texture);
    
    // Called at frame end to manage pool size
    void Tick();
    
private:
    // Pool organized by resource description
    std::unordered_map<TextureDesc, std::vector<GPUTexture*>> pool;
    
    // Track unused resources for eviction
    std::unordered_map<GPUTexture*, uint32_t> unusedFrameCount;
    static constexpr uint32_t MAX_UNUSED_FRAMES = 30;
};
```

### 2. Resource Lifetime Tracking

```
Frame Timeline:
  Pass1    Pass2    Pass3    Pass4    Pass5    Pass6
   │        │        │        │        │        │
   ├─ ResA ─┤        │        │        │        │
   │        ├─ ResB ─┼─ ResB ─┤        │        │
   │        │        ├─ ResC ─┼─ ResC ─┤        │
   │        │        │        ├─ ResD ─┼─ ResD ─┤
   │        │        │        │        │        │
```

Resource lifetimes are computed as:
- **First Use**: The earliest pass that reads or writes the resource
- **Last Use**: The latest pass that reads or writes the resource
- **Allocation Point**: Just before first use
- **Deallocation Point**: Just after last use

### 3. Memory Aliasing

Non-overlapping resources can share the same physical memory:

```
Physical Memory Block:
┌──────────────────────────────────────────────────┐
│  ResA (Pass1-2)  │         ResC (Pass3-5)        │
│──────────────────│───────────────────────────────│
│       ResB (Pass2-4)       │  ResD (Pass5-6)     │
└──────────────────────────────────────────────────┘

Aliasing: ResA and ResC share memory (non-overlapping lifetimes)
          ResB and ResD share memory (non-overlapping lifetimes)
```

Aliasing algorithm:
1. Sort resources by size (descending)
2. For each resource, find a memory slot where no lifetime overlap exists
3. Use placed/aliased resource APIs (D3D12 Placed Resources, Vulkan Memory Aliasing)

### 4. External vs Transient Resources 外部资源 vs 瞬态资源

```cpp
// External: imported from outside the graph, persists across frames 从图外部导入，跨帧持久
RDGTextureRef backBuffer = builder.RegisterExternalTexture(
    swapChain->GetCurrentBackBuffer(), "BackBuffer"
);

// Transient: created and destroyed within the frame 在帧内创建和销毁
RDGTextureRef tempBlur = builder.CreateTexture(
    FRDGTextureDesc::Create2D(w, h, PF_R16G16B16A16_FLOAT),
    "TempBlurTarget"
);

// Extracted: transient promoted to external for next frame use 瞬态资源提升为外部资源，供下一帧使用（如 TAA 历史帧）
RDGTextureRef historyBuffer = builder.CreateTexture(desc, "HistoryBuffer");
builder.QueueExtraction(historyBuffer, &savedHistoryBuffer);
```

---

## 2.4 Dependency Resolution

### 1. Implicit Dependencies 隐式依赖

Dependencies are inferred from resource usage:

```
Pass A writes ResourceX → Pass B reads ResourceX
∴ Pass B depends on Pass A (B must execute after A)
```

### 2. Dependency Graph Construction Algorithm 依赖图构建算法

```python
def build_dependency_graph(passes):
    graph = DirectedGraph()
    resource_writers = {}  # resource -> last writer pass
    
    for pass_node in passes:
        graph.add_node(pass_node)
        
        # For each input resource, add edge from writer to this pass
	# 对每个输入资源，从写入者到当前 Pass 添加有向边
        for resource in pass_node.inputs:
            if resource in resource_writers:
                writer = resource_writers[resource]
                graph.add_edge(writer, pass_node)  # writer -> reader
        
        # Track this pass as the writer for its outputs
	# 记录当前 Pass 为其输出资源的写入者
        for resource in pass_node.outputs:
            resource_writers[resource] = pass_node
    
    return graph
```

### 3. Topological Sort for Execution Order 拓扑排序

```python
def topological_sort(graph):
    in_degree = {node: 0 for node in graph.nodes}
    for u, v in graph.edges:
        in_degree[v] += 1
    
    # 入度为 0 的节点（无依赖）作为起始节点
    queue = [node for node in graph.nodes if in_degree[node] == 0]
    execution_order = []
    
    while queue:
        node = queue.pop(0)  # Can use priority for optimization
        execution_order.append(node)
        
        for neighbor in graph.successors(node):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    assert len(execution_order) == len(graph.nodes), "Cycle detected! 检测到环形依赖！"
    return execution_order
```

### 4. Dead Pass Culling

Passes whose outputs are never consumed can be removed:
输出从未被消费的 Pass 可以被移除，减少不必要的 GPU 工作：

```python
def cull_unused_passes(graph, required_outputs):
    # Start from required outputs (e.g., present pass)
    # 从必要输出（如 Present Pass）开始反向遍历
    visited = set()
    stack = [pass for pass in graph.nodes if pass.has_side_effects 
             or any(out in required_outputs for out in pass.outputs)]
    
    # Backward traversal: mark all passes that contribute to required outputs
    # 反向遍历：标记所有对必要输出有贡献的 Pass
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        
        # Add all predecessors (passes that produce our inputs)
	# 添加所有前驱（产生当前 Pass 输入的 Pass）
        for predecessor in graph.predecessors(current):
            stack.append(predecessor)
    
    # Remove unvisited passes
    # 移除未被访问的 Pass（无效 Pass）
    culled = [p for p in graph.nodes if p not in visited]
    for pass_node in culled:
        graph.remove_node(pass_node)
    
    return culled
```

---



## 2.5 Execution & Scheduling 执行与调度

### 1. Barrier Generation 屏障生成

Automatic barrier insertion between passes:

```cpp
struct ResourceBarrier {
    GPUResource* resource;
    ResourceState before;   // e.g., RENDER_TARGET
    ResourceState after;    // e.g., SHADER_RESOURCE
    uint32_t subresource;   // Mip/slice level
};

void GenerateBarriers(const ExecutionOrder& order) {
    std::unordered_map<RDGResource*, ResourceState> currentStates;
    
    for (auto& pass : order) {
        std::vector<ResourceBarrier> barriers;
        
        for (auto& [resource, requiredState] : pass.resourceAccesses) {
            ResourceState currentState = currentStates[resource];
            
            if (currentState != requiredState) {
                barriers.push_back({
                    resource->GetGPUResource(),
                    currentState,
                    requiredState
                });
                currentStates[resource] = requiredState;
            }
        }
        
        if (!barriers.empty()) {
            pass.preBarriers = std::move(barriers);
        }
    }
}
```

### 2. Barrier Batching 屏障合批

Barriers are batched for efficiency:

```
Before batching:
  Barrier(ResA: SRV → UAV)
  Dispatch()
  Barrier(ResB: RTV → SRV)  ← 两次独立的 Barrier 调用
  Barrier(ResC: RTV → SRV)  ← 两次独立的 Barrier 调用
  DrawCall()

After batching:
  Barrier(ResA: SRV → UAV)
  Dispatch()
  BatchedBarrier(ResB: RTV → SRV, ResC: RTV → SRV)  // Single API call ← 单次 API 调用
  DrawCall()
```

### 3. Async Compute Scheduling

```
Graphics Queue:  [Shadow] ──→ [GBuffer] ──→ [Lighting] ──→ [PostProcess]
                                  │              ↑
                                  │    ┌─────────┘
                                  ▼    │
Async Compute:              [SSAO Compute] ──→ [SSAO Blur]
                            (fence signal)     (fence wait)
```

Async compute passes are scheduled on a separate queue with fence synchronization:

说明：SSAO 在 GBuffer 完成后立即在 Async Compute 队列上并行执行
      Lighting Pass 通过 Fence 等待 SSAO 完成后再读取结果

```cpp
void ScheduleAsyncCompute(ExecutionPlan& plan) {
    for (auto& pass : plan.passes) {
        if (pass.flags & ERDGPassFlags::AsyncCompute) {
            // Find the latest graphics dependency
            auto graphicsDep = FindLatestGraphicsDependency(pass);
            
            // Insert fence after graphics dependency
            plan.InsertFence(graphicsDep, FenceType::GraphicsToCompute);
            
            // Find the earliest graphics consumer
            auto graphicsConsumer = FindEarliestGraphicsConsumer(pass);

            // Insert wait before graphics consumer
            plan.InsertWait(graphicsConsumer, FenceType::ComputeToGraphics);
            
            // Move pass to async compute queue
            plan.MoveToAsyncQueue(pass);
        }
    }
}
```

### 4. Parallel Command Recording

The graph enables parallel command buffer recording:

```cpp
void ExecuteGraph(const ExecutionPlan& plan) {
    // Group passes into independent batches
    auto batches = plan.GetParallelBatches();
    
    std::vector<CommandBuffer*> commandBuffers;
    
    // Record each batch in parallel
    parallel_for(batches, [&](const PassBatch& batch) {
        CommandBuffer* cmd = AllocateSecondaryCommandBuffer();
        
        for (auto& pass : batch.passes) {
            InsertBarriers(cmd, pass.preBarriers);
            pass.Execute(cmd);
        }
        
        commandBuffers.push_back(cmd);
    });
    
    // Submit all command buffers
    primaryCommandBuffer->ExecuteSecondary(commandBuffers);
    queue->Submit(primaryCommandBuffer);
}
```


### 5. Builder Execute

收集 Pass（`AddPass`）、编译渲染图之后，由 `FRDGBuilder::Execute` 负责执行渲染图：

```c++
void FRDGBuilder::Execute()
{
    SCOPED_NAMED_EVENT(FRDGBuilder_Execute, FColor::Emerald);

    // 在编译之前，在图的末尾创建epilogue pass.
    EpiloguePass = Passes.Allocate<FRDGSentinelPass>(Allocator, RDG_EVENT_NAME("Graph Epilogue"));
    SetupEmptyPass(EpiloguePass);

    const FRDGPassHandle ProloguePassHandle = GetProloguePassHandle();
    const FRDGPassHandle EpiloguePassHandle = GetEpiloguePassHandle();
    FRDGPassHandle LastUntrackedPassHandle = ProloguePassHandle;

    // 非立即模式.
    if (!GRDGImmediateMode)
    {
        // 执行之前先编译, 具体见11.3.3章节.
        // 执行之前先编译（依赖分析、裁剪、屏障生成等）
        Compile();

        {
            SCOPE_CYCLE_COUNTER(STAT_RDG_CollectResourcesTime);

            // 收集 Pass 资源（分配实际 GPU 资源）
            for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
            {
                if (!PassesToCull[PassHandle])
                {
                    CollectPassResources(PassHandle);
                }
            }

            // 结束纹理提取（标记提取资源的生命周期终点）
            for (const auto& Query : ExtractedTextures)
            {
                EndResourceRHI(EpiloguePassHandle, Query.Key, 1);
            }

            // 结束缓冲区提取.
            for (const auto& Query : ExtractedBuffers)
            {
                EndResourceRHI(EpiloguePassHandle, Query.Key, 1);
            }
        }

        // 收集Pass的屏障.
        {
            SCOPE_CYCLE_COUNTER(STAT_RDG_CollectBarriersTime);

            for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
            {
                if (!PassesToCull[PassHandle])
                {
                    CollectPassBarriers(PassHandle, LastUntrackedPassHandle);
                }
            }
        }
    }

    // 遍历所有纹理，每个纹理增加尾声转换（Epilogue Transition）
    for (FRDGTextureHandle TextureHandle = Textures.Begin(); TextureHandle != Textures.End(); ++TextureHandle)
    {
        FRDGTextureRef Texture = Textures[TextureHandle];

        if (Texture->GetRHIUnchecked())
        {
            AddEpilogueTransition(Texture, LastUntrackedPassHandle);
            Texture->Finalize();
        }
    }

    // 遍历所有缓冲区, 每个缓冲区增加尾声转换.
    for (FRDGBufferHandle BufferHandle = Buffers.Begin(); BufferHandle != Buffers.End(); ++BufferHandle)
    {
        FRDGBufferRef Buffer = Buffers[BufferHandle];

        if (Buffer->GetRHIUnchecked())
        {
            AddEpilogueTransition(Buffer, LastUntrackedPassHandle);
            Buffer->Finalize();
        }
    }

    // 执行Pass.
    if (!GRDGImmediateMode)
    {
        QUICK_SCOPE_CYCLE_COUNTER(STAT_FRDGBuilder_Execute_Passes);

        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            // 执行非裁剪的Pass.
            if (!PassesToCull[PassHandle])
            {
                ExecutePass(Passes[PassHandle]);
            }
        }
    }
    else
    {
        ExecutePass(EpiloguePass);
    }

    RHICmdList.SetGlobalUniformBuffers({});

#if WITH_MGPU
    (......)
#endif

    // 执行纹理提取.
    for (const auto& Query : ExtractedTextures)
    {
        *Query.Value = Query.Key->PooledRenderTarget;
    }

    // 执行缓冲区提取.
    for (const auto& Query : ExtractedBuffers)
    {
        *Query.Value = Query.Key->PooledBuffer;
    }

    // 清理.
    Clear();
}
```

### 6. Execute Pass

- 每个 Pass 的执行分为 **3 个步骤**：
  1. **Prologue（前序）**：提交前序屏障，调用 `BeginRenderPass`
  2. **Pass 主体**：调用该 Pass 的 Lambda，传入命令队列实例
  3. **Epilogue（后序）**：调用 `EndRenderPass`，提交后序屏障，处理资源 Acquire/Discard
- 执行期间
   1. 先编译所有Pass，然后依次执行Pass的前序、主体和后续，相当于将命令队列的BeginRenderPass、执行渲染代码、EndRenderPass分散在它们之间。
   2. Pass执行主体实际很简单，就是调用该Pass的Lambda实例，传入使用的命令队列实例

```c++
// 1. prologue
void FRDGBuilder::ExecutePassPrologue(FRHIComputeCommandList& RHICmdListPass, FRDGPass* Pass)
{
    // 提交前序开始屏障
    if (Pass->PrologueBarriersToBegin)
        Pass->PrologueBarriersToBegin->Submit(RHICmdListPass);
    // 提交前序结束屏障
    if (Pass->PrologueBarriersToEnd)
        Pass->PrologueBarriersToEnd->Submit(RHICmdListPass);

    // 初始化统一缓冲区（首次使用时）
    // 由于访问检查将允许在RDG资源上调用GetRHI，所以在第一次使用时将初始化统一缓冲区.
    Pass->GetParameters().EnumerateUniformBuffers([&](FRDGUniformBufferRef UniformBuffer)
    {
        BeginResourceRHI(UniformBuffer);
    });

    // 设置异步计算预算(Budget).
    if (Pass->GetPipeline() == ERHIPipeline::AsyncCompute)
    {
        RHICmdListPass.SetAsyncComputeBudget(Pass->AsyncComputeBudget);
    }

    const ERDGPassFlags PassFlags = Pass->GetFlags();

    if (EnumHasAnyFlags(PassFlags, ERDGPassFlags::Raster))
    {
        if (!EnumHasAnyFlags(PassFlags, ERDGPassFlags::SkipRenderPass) && !Pass->SkipRenderPassBegin())
        {
            // 调用命令队列的BeginRenderPass接口.
            static_cast<FRHICommandList&>(RHICmdListPass).BeginRenderPass(Pass->GetParameters().GetRenderPassInfo(), Pass->GetName());
        }
    }
}

// 2. pass主体
void FRDGPass::Execute(FRHIComputeCommandList& RHICmdList)
{
    QUICK_SCOPE_CYCLE_COUNTER(STAT_FRDGPass_Execute);
    // 设置统一缓冲区.
    RHICmdList.SetGlobalUniformBuffers(ParameterStruct.GetGlobalUniformBuffers());
    // 执行Pass的实现.
    ExecuteImpl(RHICmdList);
}

void TRDGLambdaPass::ExecuteImpl(FRHIComputeCommandList& RHICmdList) override
{
    // 执行Lambda.
    // 执行用户提供的 Lambda
    ExecuteLambda(static_cast<TRHICommandList&>(RHICmdList));
}

// 3. epilogue
void FRDGBuilder::ExecutePassEpilogue(FRHIComputeCommandList& RHICmdListPass, FRDGPass* Pass)
{
    QUICK_SCOPE_CYCLE_COUNTER(STAT_FRDGBuilder_ExecutePassEpilogue);

    const ERDGPassFlags PassFlags = Pass->GetFlags();

    // 调用命令队列的EndRenderPass.
    if (EnumHasAnyFlags(PassFlags, ERDGPassFlags::Raster) && !EnumHasAnyFlags(PassFlags, ERDGPassFlags::SkipRenderPass) && !Pass->SkipRenderPassEnd())
    {
        static_cast<FRHICommandList&>(RHICmdListPass).EndRenderPass();
    }

    // 放弃资源转换.
    // 放弃（Discard）瞬态资源（通知驱动不需要保留内容）
    for (FRHITexture* Texture : Pass->TexturesToDiscard)
    {
        RHIDiscardTransientResource(Texture);
    }

    // 获取(Acquire)转换资源.
    for (FRHITexture* Texture : Pass->TexturesToAcquire)
    {
        RHIAcquireTransientResource(Texture);
    }

    const FRDGParameterStruct PassParameters = Pass->GetParameters();

    // 提交用于图形管线的尾声屏障.
    if (Pass->EpilogueBarriersToBeginForGraphics)
        Pass->EpilogueBarriersToBeginForGraphics->Submit(RHICmdListPass);

    // 提交用于异步计算的尾声屏障.
    if (Pass->EpilogueBarriersToBeginForAsyncCompute)
        Pass->EpilogueBarriersToBeginForAsyncCompute->Submit(RHICmdListPass);
}
```

```c++
void FRDGBuilder::ExecutePass(FRDGPass* Pass)
{
    QUICK_SCOPE_CYCLE_COUNTER(STAT_FRDGBuilder_ExecutePass);
    SCOPED_GPU_MASK(RHICmdList, Pass->GPUMask);
    IF_RDG_CPU_SCOPES(CPUScopeStacks.BeginExecutePass(Pass));

    // 使用GPU范围.
#if RDG_GPU_SCOPES
    const bool bUsePassEventScope = Pass != EpiloguePass && Pass != ProloguePass;
    if (bUsePassEventScope)
    {
        GPUScopeStacks.BeginExecutePass(Pass);
    }
#endif

#if WITH_MGPU
    if (!bWaitedForTemporalEffect && NameForTemporalEffect != NAME_None)
    {
        RHICmdList.WaitForTemporalEffect(NameForTemporalEffect);
        bWaitedForTemporalEffect = true;
    }
#endif

    // 执行pass的顺序: 1.prologue -> 2.pass主体 -> 3.epilogue.
    // 整个过程使用指定管道上的命令列表执行.
    FRHIComputeCommandList& RHICmdListPass = (Pass->GetPipeline() == ERHIPipeline::AsyncCompute)
        ? static_cast<FRHIComputeCommandList&>(RHICmdListAsyncCompute)
        : RHICmdList;

    // 执行顺序：1. Prologue → 2. Pass 主体 → 3. Epilogue
    ExecutePassPrologue(RHICmdListPass, Pass);
    Pass->Execute(RHICmdListPass);
    ExecutePassEpilogue(RHICmdListPass, Pass);


#if RDG_GPU_SCOPES
    if (bUsePassEventScope)
    {
        GPUScopeStacks.EndExecutePass(Pass);
    }
#endif

    // 异步计算完成, 则立即派发
    if (Pass->bAsyncComputeEnd)
    {
        FRHIAsyncComputeCommandListImmediate::ImmediateDispatch(RHICmdListAsyncCompute);
    }

    // 如果是调试模式且非异步计算，则提交命令并刷新到GPU, 然后等待GPU处理完成.
    // 调试模式：每次 Pass 后提交并等待 GPU 完成（用于精确定位崩溃位置）
    if (GRDGDebugFlushGPU && !GRDGAsyncCompute)
    {
        RHICmdList.SubmitCommandsAndFlushGPU();
        RHICmdList.BlockUntilGPUIdle();
    }
}
```


### 7. Execute Clear 清理

```c++
void FRDGBuilder::Clear()
{
    // 清理外部资源.
    ExternalTextures.Empty();
    ExternalBuffers.Empty();
    // 清理提取资源.
    ExtractedTextures.Empty();
    ExtractedBuffers.Empty();
    // 清理主体数据.
    Passes.Clear();
    Views.Clear();
    Textures.Clear();
    Buffers.Clear();
    // 清理统一缓冲区和分配器.
    UniformBuffers.Clear();
    Allocator.ReleaseAll();
}
```

## 2.6 Directed Acyclic Graph (DAG)

The rendering dependency graph is fundamentally a DAG: RDG 是一个有向无环图

```
[Shadow Map Pass] ──→ [GBuffer Pass] ──→ [Lighting Pass] ──→ [Post Process] ──→ [UI Overlay]
        │                                       ↑                    ↑
        └───────────────────────────────────────┘                    │
[SSAO Pass] ─────────────────────────────────────────────────────────┘
```

- **No cycles allowed** — a pass cannot depend on its own output
- **Multiple roots** — the graph can have multiple entry points
- **Single or multiple sinks** — typically ends at the final present/swap chain


## 2.7 Compiile

`FRDGBuilder` 的编译逻辑非常复杂，执行了大量处理和优化。

**编译步骤（按顺序）：**

1. 构建生产者（Producer）和消费者（Consumer）的依赖关系
2. 确定 Pass 的裁剪等各类标记
3. 调整资源的生命周期，裁剪无效 Pass
4. 处理 Pass 的资源转换和屏障
5. 处理异步计算 Pass 的依赖和引用关系
6. 查找并建立分叉（Fork）和合并（Join）Pass 节点
7. 合并所有具有相同渲染目标的连续光栅化 Pass

[Compile 源码](../../code/RDG/Compile.cpp)


# 三. Implementation 实现对比

### 1. Traditional Immediate Mode Rendering 传统即时模式渲染

```cpp
// Traditional: Manual, error-prone, hard to maintain
void RenderFrame_Traditional() {
    // Must manually track resource states 必须手动追踪资源状态
    shadowMap->TransitionTo(DEPTH_WRITE);
    RenderShadows();
    
    shadowMap->TransitionTo(SHADER_READ);  // Easy to forget! 容易遗漏！
    gbuffer->TransitionTo(RENDER_TARGET);
    RenderGBuffer();
    
    gbuffer->TransitionTo(SHADER_READ);
    sceneColor->TransitionTo(RENDER_TARGET);
    RenderLighting();
    
    // Must manually manage resource lifetimes  必须手动管理资源生命周期
    // Must manually handle async compute sync  必须手动处理异步计算同步
    // Cannot easily reorder or cull passes     无法轻松重排或裁剪 Pass
}
```

### 2. RDG Approach

```cpp
// RDG: Declarative, automatic, maintainable 声明式，自动化，易于维护
void RenderFrame_RDG(RDGBuilder& builder) {
    auto shadowMap = AddShadowPass(builder, ...);
    auto [gbufferA, gbufferB, depth] = AddGBufferPass(builder, ...);
    auto sceneColor = AddLightingPass(builder, shadowMap, gbufferA, gbufferB, depth);
    // Barriers, lifetimes, ordering — all automatic!
}
```

### 3. Feature Comparison

| Feature               | Traditional         | RDG                   |
| --------------------- | ------------------- | --------------------- |
| Resource Barriers     | Manual              | Automatic             |
| Resource Lifetimes    | Manual              | Automatic             |
| Pass Ordering         | Hardcoded           | Dependency-driven     |
| Dead Code Elimination | None                | Automatic             |
| Memory Aliasing       | Manual              | Automatic             |
| Async Compute         | Complex manual sync | Declarative           |
| Debugging             | Difficult           | Graph visualization   |
| Feature Toggle        | Rewrite pipeline    | Remove pass           |
| CPU Parallelism       | Manual threading    | Graph-driven batching |
| Render Pass Merging   | Manual              | Automatic             |