---
layout:     post
title:      Unreal Multi-Thread Rendering Dependency Graph
subtitle:   UE multi-thread rendering architecture and pipeline
date:       2023-4-8
author:     kang
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - multi thread rendering
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

### 6. AddPass

FRDGBuilder::AddPass是向RDG系统增加一个包含Pass参数和Lambda的Pass
AddPass会根据传入的参数构建一个RDG Pass的实例，然后设置该Pass的纹理和缓冲区数据，接着用内部设置Pass的依赖Pass等句柄，如果是立即模式，会重定向纹理和缓冲区的Merge状态成Pass状态，并且直接执行

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
RDG Pass和渲染Pass并非一一对应关系，有可能多个合并成一个渲染Pass，详见后面章节。RDG Pass最复杂莫过于多线程处理、资源状态转换以及依赖处理，不过本节先不涉及

[RDG Pass](<../../code/RDG/RDG Pass.md>)

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


### 5. Builder Execute

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

### 6. Execute Pass

- **3个步骤：**
  1. prologue
  2. pass主体
  3. epilogue
- 执行期间
   1. 先编译所有Pass，然后依次执行Pass的前序、主体和后续，相当于将命令队列的BeginRenderPass、执行渲染代码、EndRenderPass分散在它们之间。
   2. Pass执行主体实际很简单，就是调用该Pass的Lambda实例，传入使用的命令队列实例

```c++
// 1. prologue
void FRDGBuilder::ExecutePassPrologue(FRHIComputeCommandList& RHICmdListPass, FRDGPass* Pass)
{
    // 提交前序开始屏障.
    if (Pass->PrologueBarriersToBegin)
    {
        Pass->PrologueBarriersToBegin->Submit(RHICmdListPass);
    }

    // 提交前序结束屏障.
    if (Pass->PrologueBarriersToEnd)
    {
        Pass->PrologueBarriersToEnd->Submit(RHICmdListPass);
    }

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
    {
        Pass->EpilogueBarriersToBeginForGraphics->Submit(RHICmdListPass);
    }

    // 提交用于异步计算的尾声屏障.
    if (Pass->EpilogueBarriersToBeginForAsyncCompute)
    {
        Pass->EpilogueBarriersToBeginForAsyncCompute->Submit(RHICmdListPass);
    }
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

    // 1.执行prologue
    ExecutePassPrologue(RHICmdListPass, Pass);

    // 2.执行pass主体
    Pass->Execute(RHICmdListPass);

    // 3.执行epilogue
    ExecutePassEpilogue(RHICmdListPass, Pass);

#if RDG_GPU_SCOPES
    if (bUsePassEventScope)
    {
        GPUScopeStacks.EndExecutePass(Pass);
    }
#endif

    // 异步计算完成, 则立即派发.
    if (Pass->bAsyncComputeEnd)
    {
        FRHIAsyncComputeCommandListImmediate::ImmediateDispatch(RHICmdListAsyncCompute);
    }

    // 如果是调试模式且非异步计算，则提交命令并刷新到GPU, 然后等待GPU处理完成.
    if (GRDGDebugFlushGPU && !GRDGAsyncCompute)
    {
        RHICmdList.SubmitCommandsAndFlushGPU();
        RHICmdList.BlockUntilGPUIdle();
    }
}
```


### 7. Execute Clear

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

[Compile](../../code/RDG/Compile.cpp)


# 三. Implementation
### 1. Traditional Immediate Mode Rendering

```cpp
// Traditional: Manual, error-prone, hard to maintain
void RenderFrame_Traditional() {
    // Must manually track resource states
    shadowMap->TransitionTo(DEPTH_WRITE);
    RenderShadows();
    
    shadowMap->TransitionTo(SHADER_READ);  // Easy to forget!
    gbuffer->TransitionTo(RENDER_TARGET);
    RenderGBuffer();
    
    gbuffer->TransitionTo(SHADER_READ);
    sceneColor->TransitionTo(RENDER_TARGET);
    RenderLighting();
    
    // Must manually manage resource lifetimes
    // Must manually handle async compute sync
    // Cannot easily reorder or cull passes
}
```

### 2. RDG Approach

```cpp
// RDG: Declarative, automatic, maintainable
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

---