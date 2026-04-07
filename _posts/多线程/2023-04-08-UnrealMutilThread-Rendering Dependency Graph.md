---
layout:     post
title:      Unreal Multi-Thread Rendering Dependency Graph
subtitle:   UE multi-thread rendering architecture and pipeline
date:       2023-4-8
author:     kang
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - Rendering
---


<center> Unreal Multi-Thread Rendering Dependency Graph 渲染依赖性图表</center>

# <center> Overview</center>

```        
1. Overview                 |
                            |   Pipeline
                            |   What && How && Why
                            |
2. RDGEngine                |
                            |   → 2.1 Builder ： 心脏和发动机，大管家，负责收集渲染Pass和参数，编译Pass、数据，处理资源依赖，裁剪和优化各类数据，还有提供执行接口
                            |       → RDGBuilder Pattern: 构建参数 AddPass
                            |   → 2.2 Pass System
                            |       → Pass Types
                            |       → Pass Declaration 单个Pass
                            |       → Connecting Pass 多个Pass连接
                            |       → Pass Execution
                            |       → Pass Merging
                            |   → 2.3 Resouces Management
                            |       → Transient Resource Pool
                            |       → Resource Lifetime Tracking
                            |       → Memory Aliasing
                            |       → External vs Transient Resources
                            |   → 2.4 Dependency Resolution
                            |       → Implicit Dependencies
                            |       → Dependency Graph Construction Algorith
                            |       → Topological Sort for Execution Order
                            |       → Dead Pass Culling
                            |   → 2.5 Execution & Scheduling
                            |       → Barrier Generation
                            |       → Barrier Batching
                            |       → Async Compute Scheduling
                            |       → Parallel Command Recording
                            |   → 2.6 Directed Acyclic Graph (DAG)
                            |   → 2.7 Compiile
4. Implementation           |
                            |   → Traditional Immediate Mode Rendering
                            |   → RDG Approach
                            |   → Feature Comparison
                            |   → Unreal Engine 5 (RDG)
5.                 |
```

# 一. Overview

## Pipeline

```
┌──────────────────────────────────────────────────────────┐
│                    Application Layer                     │
│         (Game Logic, Scene Management, Culling)          │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  RDG Builder / Setup Phase              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │ Pass A   │  │ Pass B   │  │ Pass C   │  ...          │
│  │ (Shadow) │  │ (GBuffer)│  │ (Light)  │               │
│  └──────────┘  └──────────┘  └──────────┘               │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  Compile Phase                          │
│  ┌────────────────┐  ┌────────────────┐                 │
│  │ Dependency     │  │ Resource       │                 │
│  │ Resolution     │  │ Lifetime Calc  │                 │
│  └────────────────┘  └────────────────┘                 │
│  ┌────────────────┐  ┌────────────────┐                 │
│  │ Dead Pass      │  │ Barrier        │                 │
│  │ Culling        │  │ Generation     │                 │
│  └────────────────┘  └────────────────┘                 │
│  ┌────────────────┐                                     │
│  │ Memory Aliasing│                                     │
│  │ & Allocation   │                                     │
│  └────────────────┘                                     │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  Execute Phase                          │
│  ┌────────────────┐  ┌────────────────┐                 │
│  │ Command Buffer │  │ GPU Resource   │                 │
│  │ Recording      │  │ Instantiation  │                 │
│  └────────────────┘  └────────────────┘                 │
│  ┌────────────────┐                                     │
│  │ Queue Submit   │                                     │
│  └────────────────┘                                     │
└─────────────────────────────────────────────────────────┘
```


## Summary
Rendering Dependency Graph，渲染依赖性图表

- 基于有向无环图(Directed Acyclic Graph，DAG)的调度系统，用于执行渲染管线的整帧优化
- 利用现代的图形API（DirectX 12、Vulkan和Metal 2），实现自动异步计算调度以及更高效的内存管理和屏障管理来提升性能
- 传统的图形API（DirectX 11、OpenGL）要求驱动器调用复杂的启发法，以确定何时以及如何在GPU上执行关键的调度操作
- 清空缓存，管理和再使用内存，执行布局转换等等
- 接口存在即时模式特性，因此需要复杂的记录和状态跟踪才能处理各种极端情况。这些情况最终会对性能产生负面影响，并阻碍并行
- 现代的图形API（DirectX 12、Vulkan和Metal 2）与传统图形API不同，将低级GPU管理的负担转移到应用程序。
- 这使得应用程序可以利用渲染管线的高级情境来驱动调度，从而提高性能并且简化渲染堆栈。
- RDG的理念不在GPU上立即执行Pass，而是先收集所有需要渲染的Pass，然后按照依赖的顺序对图表进行编译和执行，期间会执行各类裁剪和优化。
- 依赖性图表数据结构的整帧认知与现代图形API的能力相结合，使RDG能够在后台执行复杂的调度任务：
  - 执行异步计算通道的自动调度和隔离
  - 在帧的不相交间隔期间，使资源之间的别名内存保持活跃状态
  - 尽早启动屏障和布局转换，避免管线延迟
- RDG并非UE独创的概念和技术，早在2017年的GDC中，寒霜就已经实现并应用了Frame Graph（帧图）的技术。
- Frame Graph旨在将引擎的各类渲染功能（Feature）和上层渲染逻辑（Renderer）和下层资源（Shader、RenderContext、图形API等）隔离开来
- FrameGraph是高层级的Render Pass和资源的代表，包含了一帧中所用到的所有信息
- UE的RDG正是基于Frame Graph之上定制和实现而成的
- RDG已经被大量普及，包含场景渲染、后处理、光追等等模块都使用了RDG代替原本直接调用RHI命令的方式

## What is a Rendering Dependency Graph?

A **Rendering Dependency Graph (RDG)**, also known as a **Frame Graph** or **Render Graph**, is a high-level abstraction layer for organizing and executing rendering operations in a modern graphics pipeline. It models the entire frame's rendering workload as a **Directed Acyclic Graph (DAG)**, where:

- **Nodes** represent rendering passes (compute, raster, copy, etc.)
- **Edges** represent resource dependencies between passes

The framework automatically handles:
- Resource allocation and deallocation (transient resources)
- Execution ordering based on dependencies
- Synchronization barriers (pipeline barriers, layout transitions)
- Dead code elimination (culling unused passes)
- Resource aliasing and memory optimization

## Why Use a Rendering Dependency Graph? 为什么使用RDG？

| Problem (Traditional)               | Solution (RDG)                           |
| ----------------------------------- | ---------------------------------------- |
| Manual resource lifetime management | Automatic transient resource allocation  |
| Hardcoded render pass ordering      | Automatic dependency-driven scheduling   |
| Manual barrier/transition insertion | Automatic synchronization                |
| Difficult to add/remove features    | Modular pass-based architecture          |
| Wasted GPU memory                   | Resource aliasing & memory pooling       |
| Hard to parallelize CPU work        | Graph enables parallel command recording |

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



## Three-Phase Pipeline

The RDG operates in three distinct phases per frame:

### 1. Setup (Declaration)
- Passes declare their resource inputs/outputs  声明资源
- Resources are created as **virtual handles**  虚拟句柄
- No GPU work is performed                      GPU运行
- Runs on CPU, can be parallelized              并行处理

### 2. Compile (Analysis)
- Build dependency graph from declared inputs/outputs
- Calculate resource lifetimes
- Cull unreferenced passes
- Determine execution order (topological sort)
- Generate synchronization barriers
- Perform memory aliasing analysis

### 3. Execute (Recording & Submission)
- Allocate actual GPU resources
- Record command buffers
- Insert barriers and transitions
- Submit to GPU queues

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
    // Create a new transient texture
    RDGTextureRef CreateTexture(const FRDGTextureDesc& desc, const char* name);
    // Create a new transient buffer
    RDGBufferRef CreateBuffer(const FRDGBufferDesc& desc, const char* name);
    // Import an external resource
    RDGTextureRef RegisterExternalTexture(FRHITexture* texture, const char* name);
    // Add a render pass
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
    Raster        = 1 << 0,   // Uses render targets, draw calls
    Compute       = 1 << 1,   // Uses compute dispatch
    AsyncCompute  = 1 << 2,   // Runs on async compute queue
    Copy          = 1 << 3,   // Transfer operations
    NeverCull     = 1 << 4,   // Cannot be culled (e.g., readback)
    SkipBarriers  = 1 << 5,   // Manual barrier management
};
```

- **Raster Pass**: Traditional draw calls with render targets
- **Compute Pass**: Dispatch compute shaders
- **Copy/Transfer Pass**: Resource copies, uploads, readbacks
- **Async Compute Pass**: Runs on async compute queue

A **Pass** is the fundamental unit of work:

```cpp
struct RenderPass {
    std::string name;
    PassType type;              // Raster, Compute, Copy, AsyncCompute
    std::vector<ResourceRef> inputs;
    std::vector<ResourceRef> outputs;
    ExecuteCallback execute;    // Lambda containing actual GPU commands
};
```

### 2. Connecting Passes

Passes are connected implicitly through shared resource references:

```cpp
void SetupFrame(RDGBuilder& builder) {
    // Pass 1: GBuffer
    auto [albedo, normal, depth] = AddGBufferPass(builder, view);
    
    // Pass 2: SSAO (reads depth, writes SSAO texture)
    auto ssaoTexture = AddSSAOPass(builder, depth);
    
    // Pass 3: Lighting (reads GBuffer + SSAO)
    auto sceneColor = AddLightingPass(builder, albedo, normal, depth, ssaoTexture);
    
    // Pass 4: Post Processing
    auto finalColor = AddPostProcessPass(builder, sceneColor);
    
    // Pass 5: Present
    AddPresentPass(builder, finalColor, swapChainTarget);
}
```

```c++
// 增加RDG Pass.
GraphBuilder.AddPass(
    RDG_EVENT_NAME("MyRDGPass"),
    PassParameters,
    ERDGPassFlags::Raster,
    // Pass的Lambda
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

### 3. Pass Declaration Example

```cpp
void AddGBufferPass(RDGBuilder& builder, const ViewInfo& view) {
    // Declare outputs
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
    
    // Declare pass parameters
    auto* params = builder.AllocParameters<FGBufferPassParams>();
    params->albedoTarget = builder.CreateRTV(albedoRT);
    params->normalTarget = builder.CreateRTV(normalRT);
    params->depthTarget  = builder.CreateDSV(depthRT);
    
    // Add the pass
    builder.AddPass(
        "GBufferPass",
        params,
        ERDGPassFlags::Raster,
        [view](const FGBufferPassParams& params, FRHICommandList& cmdList) {
            // Actual rendering commands
            cmdList.SetRenderTargets(params.albedoTarget, params.normalTarget, params.depthTarget);
            for (const auto& mesh : view.visibleMeshes) {
                cmdList.DrawIndexed(mesh);
            }
        }
    );
}
```


### 4. Pass Execution Lambda

The execution lambda captures the actual GPU work:

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
        
        // Dispatch
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
    SHADER_PARAMETER_RDG_TEXTURE(Texture2D, GBufferA)        // SRV input
    SHADER_PARAMETER_RDG_TEXTURE(Texture2D, GBufferB)        // SRV input
    SHADER_PARAMETER_RDG_TEXTURE(Texture2D, SceneDepth)      // SRV input
    SHADER_PARAMETER_RDG_TEXTURE(Texture2D, SSAOTexture)     // SRV input
    SHADER_PARAMETER_RDG_TEXTURE_UAV(RWTexture2D, SceneColor) // UAV output
    SHADER_PARAMETER_STRUCT_REF(FViewUniformShaderParameters, View)
    RENDER_TARGET_BINDING_SLOTS()                             // RTV slots
END_SHADER_PARAMETER_STRUCT()
```


---

## 2.3 Resouces Management 资源管理

Resources in RDG are **virtual handles** until execution:

```cpp
struct RDGResource {
    std::string name;
    ResourceDesc desc;          // Texture/Buffer description
    bool isExternal;            // Imported or transient
    bool isTransient;           // Managed by the graph
    ResourceLifetime lifetime;  // First use → last use
};
```

Resource categories:
- **Transient Resources**: Created and destroyed within a single frame
- **External/Imported Resources**: Persist across frames (e.g., swap chain, history buffers)
- **Extracted Resources**: Transient resources promoted to persist beyond the frame
Resources are accessed through typed views:

| View Type                     | Description                       |
| ----------------------------- | --------------------------------- |
| `SRV` (Shader Resource View)  | Read-only texture/buffer access   |
| `UAV` (Unordered Access View) | Read-write access in compute      |
| `RTV` (Render Target View)    | Write as color attachment         |
| `DSV` (Depth Stencil View)    | Write as depth/stencil attachment |
| `CBV` (Constant Buffer View)  | Uniform/constant buffer access    |

### 1. Transient Resource Pool

Transient resources are allocated from a pool and reused across frames:

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

### 4. External vs Transient Resources

```cpp
// External: imported from outside the graph, persists across frames
RDGTextureRef backBuffer = builder.RegisterExternalTexture(
    swapChain->GetCurrentBackBuffer(), "BackBuffer"
);

// Transient: created and destroyed within the frame
RDGTextureRef tempBlur = builder.CreateTexture(
    FRDGTextureDesc::Create2D(w, h, PF_R16G16B16A16_FLOAT),
    "TempBlurTarget"
);

// Extracted: transient promoted to external for next frame use
RDGTextureRef historyBuffer = builder.CreateTexture(desc, "HistoryBuffer");
builder.QueueExtraction(historyBuffer, &savedHistoryBuffer);
```

---

## 2.4 Dependency Resolution

### 1. Implicit Dependencies

Dependencies are inferred from resource usage:

```
Pass A writes ResourceX → Pass B reads ResourceX
∴ Pass B depends on Pass A (B must execute after A)
```

### 2. Dependency Graph Construction Algorithm

```python
def build_dependency_graph(passes):
    graph = DirectedGraph()
    resource_writers = {}  # resource -> last writer pass
    
    for pass_node in passes:
        graph.add_node(pass_node)
        
        # For each input resource, add edge from writer to this pass
        for resource in pass_node.inputs:
            if resource in resource_writers:
                writer = resource_writers[resource]
                graph.add_edge(writer, pass_node)  # writer -> reader
        
        # Track this pass as the writer for its outputs
        for resource in pass_node.outputs:
            resource_writers[resource] = pass_node
    
    return graph
```

### 3. Topological Sort for Execution Order

```python
def topological_sort(graph):
    in_degree = {node: 0 for node in graph.nodes}
    for u, v in graph.edges:
        in_degree[v] += 1
    
    queue = [node for node in graph.nodes if in_degree[node] == 0]
    execution_order = []
    
    while queue:
        node = queue.pop(0)  # Can use priority for optimization
        execution_order.append(node)
        
        for neighbor in graph.successors(node):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    assert len(execution_order) == len(graph.nodes), "Cycle detected!"
    return execution_order
```

### 4. Dead Pass Culling

Passes whose outputs are never consumed can be removed:

```python
def cull_unused_passes(graph, required_outputs):
    # Start from required outputs (e.g., present pass)
    visited = set()
    stack = [pass for pass in graph.nodes if pass.has_side_effects 
             or any(out in required_outputs for out in pass.outputs)]
    
    # Backward traversal: mark all passes that contribute to required outputs
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        
        # Add all predecessors (passes that produce our inputs)
        for predecessor in graph.predecessors(current):
            stack.append(predecessor)
    
    # Remove unvisited passes
    culled = [p for p in graph.nodes if p not in visited]
    for pass_node in culled:
        graph.remove_node(pass_node)
    
    return culled
```

---



## 2.5 Execution & Scheduling

收集Pass（AddPass）、编译渲染图之后，便可以**执行渲染图**了，由FRDGBuilder::Execute承担
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
        Compile();

        {
            SCOPE_CYCLE_COUNTER(STAT_RDG_CollectResourcesTime);

            // 收集Pass资源.
            for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
            {
                if (!PassesToCull[PassHandle])
                {
                    CollectPassResources(PassHandle);
                }
            }

            // 结束纹理提取.
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

    // 遍历所有纹理, 每个纹理增加尾声转换.
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

### 1. Barrier Generation 生成

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

### 2. Barrier Batching 合批

Barriers are batched for efficiency:

```
Before batching:
  Barrier(ResA: SRV → UAV)
  Dispatch()
  Barrier(ResB: RTV → SRV)
  Barrier(ResC: RTV → SRV)
  DrawCall()

After batching:
  Barrier(ResA: SRV → UAV)
  Dispatch()
  BatchedBarrier(ResB: RTV → SRV, ResC: RTV → SRV)  // Single API call
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
- FRDGBuilder的编译逻辑非常复杂，执行了很多处理和优化
- RDG编译期间的逻辑非常复杂
- 步骤繁多
  - 先后经历构建生产者和消费者的依赖关系
  - 确定Pass的裁剪等各类标记
  - 调整资源的生命周期，裁剪Pass
  - 处理Pass的资源转换和屏障
  - 处理异步计算Pass的依赖和引用关系
  - 查找并建立分叉和合并Pass节点
  - 合并所有具体相同渲染目标的光栅化Pass等步骤

```c++
void FRDGBuilder::Compile()
{
    uint32 RasterPassCount = 0;
    uint32 AsyncComputePassCount = 0;

    // Pass标记位.
    FRDGPassBitArray PassesOnAsyncCompute(false, Passes.Num());
    FRDGPassBitArray PassesOnRaster(false, Passes.Num());
    FRDGPassBitArray PassesWithUntrackedOutputs(false, Passes.Num());
    FRDGPassBitArray PassesToNeverCull(false, Passes.Num());

    const FRDGPassHandle ProloguePassHandle = GetProloguePassHandle();
    const FRDGPassHandle EpiloguePassHandle = GetEpiloguePassHandle();

    const auto IsCrossPipeline = [&](FRDGPassHandle A, FRDGPassHandle B)
    {
        return PassesOnAsyncCompute[A] != PassesOnAsyncCompute[B];
    };

    const auto IsSortedBefore = [&](FRDGPassHandle A, FRDGPassHandle B)
    {
        return A < B;
    };

    const auto IsSortedAfter = [&](FRDGPassHandle A, FRDGPassHandle B)
    {
        return A > B;
    };

    // 在图中构建生产者/消费者依赖关系，并构建打包的元数据位数组，以便在搜索符合特定条件的Pass时获得更好的缓存一致性.
    // 搜索根也被用来进行筛选. 携带了不跟踪的RHI输出(e.g. SHADER_PARAMETER_{BUFFER, TEXTURE}_UAV)的Pass不能被裁剪, 也不能写入外部资源的任何Pass.
    // 资源提取将生命周期延长到尾声(epilogue)Pass，尾声Pass总是图的根。前言和尾声是辅助Pass，因此永远不会被淘汰。
    {
        SCOPED_NAMED_EVENT(FRDGBuilder_Compile_Culling_Dependencies, FColor::Emerald);

        // 增加裁剪依赖.
        const auto AddCullingDependency = [&](FRDGPassHandle& ProducerHandle, FRDGPassHandle PassHandle, ERHIAccess Access)
        {
            if (Access != ERHIAccess::Unknown)
            {
                if (ProducerHandle.IsValid())
                {
                    // 增加Pass依赖.
                    AddPassDependency(ProducerHandle, PassHandle);
                }

                // 如果可写, 则存储新的生产者.
                if (IsWritableAccess(Access))
                {
                    ProducerHandle = PassHandle;
                }
            }
        };

        // 遍历所有Pass, 处理每个Pass的纹理和缓冲区状态等.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            FRDGPass* Pass = Passes[PassHandle];

            bool bUntrackedOutputs = Pass->GetParameters().HasExternalOutputs();

            // 处理Pass的所有纹理状态.
            for (auto& TexturePair : Pass->TextureStates)
            {
                FRDGTextureRef Texture = TexturePair.Key;
                auto& LastProducers = Texture->LastProducers;
                auto& PassState = TexturePair.Value.State;

                const bool bWholePassState = IsWholeResource(PassState);
                const bool bWholeProducers = IsWholeResource(LastProducers);

                // 生产者数组需要至少和pass状态数组一样大.
                if (bWholeProducers && !bWholePassState)
                {
                    InitAsSubresources(LastProducers, Texture->Layout);
                }

                // 增加裁剪依赖.
                for (uint32 Index = 0, Count = LastProducers.Num(); Index < Count; ++Index)
                {
                    AddCullingDependency(LastProducers[Index], PassHandle, PassState[bWholePassState ? 0 : Index].Access);
                }

                bUntrackedOutputs |= Texture->bExternal;
            }

            // 处理Pass的所有缓冲区状态.
            for (auto& BufferPair : Pass->BufferStates)
            {
                FRDGBufferRef Buffer = BufferPair.Key;
                AddCullingDependency(Buffer->LastProducer, PassHandle, BufferPair.Value.State.Access);
                bUntrackedOutputs |= Buffer->bExternal;
            }

            // 处理Pass的其它标记和数据.
            const ERDGPassFlags PassFlags = Pass->GetFlags();
            const bool bAsyncCompute = EnumHasAnyFlags(PassFlags, ERDGPassFlags::AsyncCompute);
            const bool bRaster = EnumHasAnyFlags(PassFlags, ERDGPassFlags::Raster);
            const bool bNeverCull = EnumHasAnyFlags(PassFlags, ERDGPassFlags::NeverCull);

            PassesOnRaster[PassHandle] = bRaster;
            PassesOnAsyncCompute[PassHandle] = bAsyncCompute;
            PassesToNeverCull[PassHandle] = bNeverCull;
            PassesWithUntrackedOutputs[PassHandle] = bUntrackedOutputs;
            AsyncComputePassCount += bAsyncCompute ? 1 : 0;
            RasterPassCount += bRaster ? 1 : 0;
        }

        // prologue/epilogue设置为不追踪, 它们分别负责外部资源的导入/导出.
        PassesWithUntrackedOutputs[ProloguePassHandle] = true;
        PassesWithUntrackedOutputs[EpiloguePassHandle] = true;

        // 处理提取纹理的裁剪依赖.
        for (const auto& Query : ExtractedTextures)
        {
            FRDGTextureRef Texture = Query.Key;
            for (FRDGPassHandle& ProducerHandle : Texture->LastProducers)
            {
                AddCullingDependency(ProducerHandle, EpiloguePassHandle, Texture->AccessFinal);
            }
            Texture->ReferenceCount++;
        }

        // 处理提取缓冲区的裁剪依赖.
        for (const auto& Query : ExtractedBuffers)
        {
            FRDGBufferRef Buffer = Query.Key;
            AddCullingDependency(Buffer->LastProducer, EpiloguePassHandle, Buffer->AccessFinal);
            Buffer->ReferenceCount++;
        }
    }

    // -------- 处理Pass裁剪 --------
    
    if (GRDGCullPasses)
    {
        TArray<FRDGPassHandle, TInlineAllocator<32, SceneRenderingAllocator>> PassStack;
        // 所有Pass初始化为剔除.
        PassesToCull.Init(true, Passes.Num());

        // 收集Pass的根列表, 符合条件的是那些不追踪的输出或标记为永不剔除的Pass.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            if (PassesWithUntrackedOutputs[PassHandle] || PassesToNeverCull[PassHandle])
            {
                PassStack.Add(PassHandle);
            }
        }

        // 非递归循环的栈遍历, 采用深度优先搜索方式, 标记每个根可达的Pass节点为不裁剪.
        while (PassStack.Num())
        {
            const FRDGPassHandle PassHandle = PassStack.Pop();

            if (PassesToCull[PassHandle])
            {
                PassesToCull[PassHandle] = false;
                PassStack.Append(Passes[PassHandle]->Producers);

            #if STATS
                --GRDGStatPassCullCount;
            #endif
            }
        }
    }
    else // 不启用Pass裁剪, 所有Pass初始化为不裁剪.
    {
        PassesToCull.Init(false, Passes.Num());
    }
    
    // -------- 处理Pass屏障 --------

    // 遍历经过筛选的图，并为每个子资源编译屏障, 某些过渡是多余的, 例如read-to-read。
    // RDG采用了保守的启发式，选择不合并不一定意味着就要执行转换. 
    // 它们是两个不同的步骤。合并状态跟踪第一次和最后一次的Pass间隔. Pass的引用也会累积到每个资源上. 
    // 必须在剔除后发生，因为剔除后的Pass不能提供引用.

    {
        SCOPED_NAMED_EVENT(FRDGBuilder_Compile_Barriers, FColor::Emerald);

        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            // 跳过被裁剪或无参数的Pass.
            if (PassesToCull[PassHandle] || PassesWithEmptyParameters[PassHandle])
            {
                continue;
            }

            // 合并子资源状态.
            const auto MergeSubresourceStates = [&](ERDGParentResourceType ResourceType, FRDGSubresourceState*& PassMergeState, FRDGSubresourceState*& ResourceMergeState, const FRDGSubresourceState& PassState)
            {
                // 跳过未知状态的资源合并.
                if (PassState.Access == ERHIAccess::Unknown)
                {
                    return;
                }

                if (!ResourceMergeState || !FRDGSubresourceState::IsMergeAllowed(ResourceType, *ResourceMergeState, PassState))
                {
                    // 跨管线、不可合并的状态改变需要一个新的pass依赖项来进行防护.
                    if (ResourceMergeState && ResourceMergeState->Pipeline != PassState.Pipeline)
                    {
                        AddPassDependency(ResourceMergeState->LastPass, PassHandle);
                    }

                    // 分配一个新的挂起的合并状态，并将其分配给pass状态.
                    ResourceMergeState = AllocSubresource(PassState);
                    ResourceMergeState->SetPass(PassHandle);
                }
                else
                {
                    // 合并Pass状态进合并后的状态.
                    ResourceMergeState->Access |= PassState.Access;
                    ResourceMergeState->LastPass = PassHandle;
                }

                PassMergeState = ResourceMergeState;
            };

            const bool bAsyncComputePass = PassesOnAsyncCompute[PassHandle];

            // 获取当前处理的Pass实例.
            FRDGPass* Pass = Passes[PassHandle];

            // 处理当前Pass的纹理状态.
            for (auto& TexturePair : Pass->TextureStates)
            {
                FRDGTextureRef Texture = TexturePair.Key;
                auto& PassState = TexturePair.Value;

                // 增加引用数量.
                Texture->ReferenceCount += PassState.ReferenceCount;
                Texture->bUsedByAsyncComputePass |= bAsyncComputePass;

                const bool bWholePassState = IsWholeResource(PassState.State);
                const bool bWholeMergeState = IsWholeResource(Texture->MergeState);

                // 为简单起见，合并/Pass状态维度应该匹配.
                if (bWholeMergeState && !bWholePassState)
                {
                    InitAsSubresources(Texture->MergeState, Texture->Layout);
                }
                else if (!bWholeMergeState && bWholePassState)
                {
                    InitAsWholeResource(Texture->MergeState);
                }

                const uint32 SubresourceCount = PassState.State.Num();
                PassState.MergeState.SetNum(SubresourceCount);

                // 合并子资源状态.
                for (uint32 Index = 0; Index < SubresourceCount; ++Index)
                {
                    MergeSubresourceStates(ERDGParentResourceType::Texture, PassState.MergeState[Index], Texture->MergeState[Index], PassState.State[Index]);
                }
            }

            // 处理当前Pass的缓冲区状态.
            for (auto& BufferPair : Pass->BufferStates)
            {
                FRDGBufferRef Buffer = BufferPair.Key;
                auto& PassState = BufferPair.Value;

                Buffer->ReferenceCount += PassState.ReferenceCount;
                Buffer->bUsedByAsyncComputePass |= bAsyncComputePass;

                MergeSubresourceStates(ERDGParentResourceType::Buffer, PassState.MergeState, Buffer->MergeState, PassState.State);
            }
        }
    }

    // 处理异步计算Pass.
    if (AsyncComputePassCount > 0)
    {
        SCOPED_NAMED_EVENT(FRDGBuilder_Compile_AsyncCompute, FColor::Emerald);

        FRDGPassBitArray PassesWithCrossPipelineProducer(false, Passes.Num());
        FRDGPassBitArray PassesWithCrossPipelineConsumer(false, Passes.Num());

        // 遍历正在执行的活动Pass，以便为每个Pass找到最新的跨管道生产者和最早的跨管道消费者, 以便后续构建异步计算重叠区域时缩小搜索空间.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            if (PassesToCull[PassHandle] || PassesWithEmptyParameters[PassHandle])
            {
                continue;
            }

            FRDGPass* Pass = Passes[PassHandle];

            // 遍历生产者, 处理生产者和消费者的引用关系.
            for (FRDGPassHandle ProducerHandle : Pass->GetProducers())
            {
                const FRDGPassHandle ConsumerHandle = PassHandle;

                if (!IsCrossPipeline(ProducerHandle, ConsumerHandle))
                {
                    continue;
                }

                FRDGPass* Consumer = Pass;
                FRDGPass* Producer = Passes[ProducerHandle];

                // 为生产者查找另一个管道上最早的消费者.
                if (Producer->CrossPipelineConsumer.IsNull() || IsSortedBefore(ConsumerHandle, Producer->CrossPipelineConsumer))
                {
                    Producer->CrossPipelineConsumer = PassHandle;
                    PassesWithCrossPipelineConsumer[ProducerHandle] = true;
                }

                // 为消费者查找另一个管道上的最新生产者.
                if (Consumer->CrossPipelineProducer.IsNull() || IsSortedAfter(ProducerHandle, Consumer->CrossPipelineProducer))
                {
                    Consumer->CrossPipelineProducer = ProducerHandle;
                    PassesWithCrossPipelineProducer[ConsumerHandle] = true;
                }
            }
        }

        // 为异步计算建立fork / join重叠区域, 用于栅栏及资源分配/回收. 在fork/join完成之前，异步计算Pass不能分配/释放它们的资源引用，因为两个管道是并行运行的。因此，异步计算的所有资源生命周期都被扩展到整个异步区域。

        const auto IsCrossPipelineProducer = [&](FRDGPassHandle A)
        {
            return PassesWithCrossPipelineConsumer[A];
        };

        const auto IsCrossPipelineConsumer = [&](FRDGPassHandle A)
        {
            return PassesWithCrossPipelineProducer[A];
        };

        // 查找跨管道生产者.
        const auto FindCrossPipelineProducer = [&](FRDGPassHandle PassHandle)
        {
            FRDGPassHandle LatestProducerHandle = ProloguePassHandle;
            FRDGPassHandle ConsumerHandle = PassHandle;

            // 期望在其它管道上找到最新的生产者，以便建立一个分叉点. 因为可以用N个生产者通道消耗N个资源，所以只关心最后一个.
            while (ConsumerHandle != Passes.Begin())
            {
                if (!PassesToCull[ConsumerHandle] && !IsCrossPipeline(ConsumerHandle, PassHandle) && IsCrossPipelineConsumer(ConsumerHandle))
                {
                    const FRDGPass* Consumer = Passes[ConsumerHandle];

                    if (IsSortedAfter(Consumer->CrossPipelineProducer, LatestProducerHandle))
                    {
                        LatestProducerHandle = Consumer->CrossPipelineProducer;
                    }
                }
                --ConsumerHandle;
            }

            return LatestProducerHandle;
        };

        // 查找跨管道消费者.
        const auto FindCrossPipelineConsumer = [&](FRDGPassHandle PassHandle)
        {
            check(PassHandle != EpiloguePassHandle);

            FRDGPassHandle EarliestConsumerHandle = EpiloguePassHandle;
            FRDGPassHandle ProducerHandle = PassHandle;

            // 期望找到另一个管道上最早的使用者，因为这在管道之间建立了连接点。因为可以在另一个管道上为N个消费者生产，所以只关心第一个执行的消费者. 
            while (ProducerHandle != Passes.End())
            {
                if (!PassesToCull[ProducerHandle] && !IsCrossPipeline(ProducerHandle, PassHandle) && IsCrossPipelineProducer(ProducerHandle))
                {
                    const FRDGPass* Producer = Passes[ProducerHandle];

                    if (IsSortedBefore(Producer->CrossPipelineConsumer, EarliestConsumerHandle))
                    {
                        EarliestConsumerHandle = Producer->CrossPipelineConsumer;
                    }
                }
                ++ProducerHandle;
            }

            return EarliestConsumerHandle;
        };

        // 将图形Pass插入到异步计算Pass的分叉中.
        const auto InsertGraphicsToAsyncComputeFork = [&](FRDGPass* GraphicsPass, FRDGPass* AsyncComputePass)
        {
            FRDGBarrierBatchBegin& EpilogueBarriersToBeginForAsyncCompute = GraphicsPass->GetEpilogueBarriersToBeginForAsyncCompute(Allocator);

            GraphicsPass->bGraphicsFork = 1;
            EpilogueBarriersToBeginForAsyncCompute.SetUseCrossPipelineFence();

            AsyncComputePass->bAsyncComputeBegin = 1;
            AsyncComputePass->GetPrologueBarriersToEnd(Allocator).AddDependency(&EpilogueBarriersToBeginForAsyncCompute);
        };

        // 将异步计算Pass插入到图形Pass的合并中.
        const auto InsertAsyncToGraphicsComputeJoin = [&](FRDGPass* AsyncComputePass, FRDGPass* GraphicsPass)
        {
            FRDGBarrierBatchBegin& EpilogueBarriersToBeginForGraphics = AsyncComputePass->GetEpilogueBarriersToBeginForGraphics(Allocator);

            AsyncComputePass->bAsyncComputeEnd = 1;
            EpilogueBarriersToBeginForGraphics.SetUseCrossPipelineFence();

            GraphicsPass->bGraphicsJoin = 1;
            GraphicsPass->GetPrologueBarriersToEnd(Allocator).AddDependency(&EpilogueBarriersToBeginForGraphics);
        };

        FRDGPass* PrevGraphicsForkPass = nullptr;
        FRDGPass* PrevGraphicsJoinPass = nullptr;
        FRDGPass* PrevAsyncComputePass = nullptr;

        // 遍历所有Pass, 扩展资源的生命周期, 处理图形Pass和异步计算Pass的交叉和合并节点.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            if (!PassesOnAsyncCompute[PassHandle] || PassesToCull[PassHandle])
            {
                continue;
            }

            FRDGPass* AsyncComputePass = Passes[PassHandle];

            // 找到分叉Pass和合并Pass.
            const FRDGPassHandle GraphicsForkPassHandle = FindCrossPipelineProducer(PassHandle);
            const FRDGPassHandle GraphicsJoinPassHandle = FindCrossPipelineConsumer(PassHandle);

            AsyncComputePass->GraphicsForkPass = GraphicsForkPassHandle;
            AsyncComputePass->GraphicsJoinPass = GraphicsJoinPassHandle;

            FRDGPass* GraphicsForkPass = Passes[GraphicsForkPassHandle];
            FRDGPass* GraphicsJoinPass = Passes[GraphicsJoinPassHandle];

            // 将异步计算中使用的资源的生命周期延长到fork/join图形Pass。
            GraphicsForkPass->ResourcesToBegin.Add(AsyncComputePass);
            GraphicsJoinPass->ResourcesToEnd.Add(AsyncComputePass);

            // 将图形分叉Pass插入到异步计算分叉Pass.
            if (PrevGraphicsForkPass != GraphicsForkPass)
            {
                InsertGraphicsToAsyncComputeFork(GraphicsForkPass, AsyncComputePass);
            }

            // 将异步计算合并Pass插入到图形合并Pass.
            if (PrevGraphicsJoinPass != GraphicsJoinPass && PrevAsyncComputePass)
            {
                InsertAsyncToGraphicsComputeJoin(PrevAsyncComputePass, PrevGraphicsJoinPass);
            }

            PrevAsyncComputePass = AsyncComputePass;
            PrevGraphicsForkPass = GraphicsForkPass;
            PrevGraphicsJoinPass = GraphicsJoinPass;
        }

        // 图中的最后一个异步计算Pass需要手动连接回epilogue pass.
        if (PrevAsyncComputePass)
        {
            InsertAsyncToGraphicsComputeJoin(PrevAsyncComputePass, EpiloguePass);
            PrevAsyncComputePass->bAsyncComputeEndExecute = 1;
        }
    }

    // 遍历所有图形管道Pass, 并且合并所有具有相同RT的光栅化Pass到同一个RHI渲染Pass中.
    if (GRDGMergeRenderPasses && RasterPassCount > 0)
    {
        SCOPED_NAMED_EVENT(FRDGBuilder_Compile_RenderPassMerge, FColor::Emerald);

        TArray<FRDGPassHandle, SceneRenderingAllocator> PassesToMerge;
        FRDGPass* PrevPass = nullptr;
        const FRenderTargetBindingSlots* PrevRenderTargets = nullptr;

        const auto CommitMerge = [&]
        {
            if (PassesToMerge.Num())
            {
                const FRDGPassHandle FirstPassHandle = PassesToMerge[0];
                const FRDGPassHandle LastPassHandle = PassesToMerge.Last();
                
                // 给定一个Pass的间隔合并成一个单一的渲染Pass: [B, X, X, X, X, E], 开始Pass(B)和结束Pass(E)会分别调用BeginRenderPass/EndRenderPass.
                // 另外，begin将处理整个合并间隔的所有序言屏障，end将处理所有尾声屏障, 这可以避免渲染通道内的资源转换，并更有效地批量处理资源转换.
                // 假设已经在遍历期间完成了过滤来自合并集的Pass之间的依赖关系. 
                
                // (B)是合并序列里的首个Pass.
                {
                    FRDGPass* Pass = Passes[FirstPassHandle];
                    Pass->bSkipRenderPassEnd = 1;
                    Pass->EpilogueBarrierPass = LastPassHandle;
                }

                // (X)是中间Pass.
                for (int32 PassIndex = 1, PassCount = PassesToMerge.Num() - 1; PassIndex < PassCount; ++PassIndex)
                {
                    const FRDGPassHandle PassHandle = PassesToMerge[PassIndex];
                    FRDGPass* Pass = Passes[PassHandle];
                    Pass->bSkipRenderPassBegin = 1;
                    Pass->bSkipRenderPassEnd = 1;
                    Pass->PrologueBarrierPass = FirstPassHandle;
                    Pass->EpilogueBarrierPass = LastPassHandle;
                }

                // (E)是合并序列里的最后Pass.
                {
                    FRDGPass* Pass = Passes[LastPassHandle];
                    Pass->bSkipRenderPassBegin = 1;
                    Pass->PrologueBarrierPass = FirstPassHandle;
                }

            #if STATS
                GRDGStatRenderPassMergeCount += PassesToMerge.Num();
            #endif
            }
            PassesToMerge.Reset();
            PrevPass = nullptr;
            PrevRenderTargets = nullptr;
        };

        // 遍历所有光栅Pass, 合并所有相同RT的Pass到同一个渲染Pass中.
        for (FRDGPassHandle PassHandle = Passes.Begin(); PassHandle != Passes.End(); ++PassHandle)
        {
            // 跳过已被裁剪的Pass.
            if (PassesToCull[PassHandle])
            {
                continue;
            }

            // 是光栅Pass才处理.
            if (PassesOnRaster[PassHandle])
            {
                FRDGPass* NextPass = Passes[PassHandle];

                // 用户控制渲染Pass的Pass不能与其他Pass合并，光栅UAV的Pass由于潜在的相互依赖也不能合并.
                if (EnumHasAnyFlags(NextPass->GetFlags(), ERDGPassFlags::SkipRenderPass) || NextPass->bUAVAccess)
                {
                    CommitMerge();
                    continue;
                }

                // 图形分叉Pass不能和之前的光栅Pass合并.
                if (NextPass->bGraphicsFork)
                {
                    CommitMerge();
                }

                const FRenderTargetBindingSlots& RenderTargets = NextPass->GetParameters().GetRenderTargets();

                if (PrevPass)
                {
                    // 对比RT, 以判定是否可以合并.
                    if (PrevRenderTargets->CanMergeBefore(RenderTargets)
                    #if WITH_MGPU
                        && PrevPass->GPUMask == NextPass->GPUMask
                    #endif
                        )
                    {
                        // 如果可以, 添加Pass到PassesToMerge列表.
                        if (!PassesToMerge.Num())
                        {
                            PassesToMerge.Add(PrevPass->GetHandle());
                        }
                        PassesToMerge.Add(PassHandle);
                    }
                    else
                    {
                        CommitMerge();
                    }
                }

                PrevPass = NextPass;
                PrevRenderTargets = &RenderTargets;
            }
            else if (!PassesOnAsyncCompute[PassHandle])
            {
                // 图形管道上的非光栅Pass将使RT合并无效.
                CommitMerge();
            }
        }

        CommitMerge();
    }
}
```