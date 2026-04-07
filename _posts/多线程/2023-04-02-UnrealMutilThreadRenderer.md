---
layout:     post
title:      Unreal Multi-Thread Renderer
subtitle:   UE multi-thread rendering architecture and pipeline
date:       2023-4-2
author:     kang
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - Multi-Thread-Rendering
---

<center> Unreal Multi-Thread Renderer </center>

# <center> Overview</center>

```
1. Threads          |
                    |   Three Threads
                    |       → Game Thread (GT)
                    |           → ENQUEUE_RENDER_COMMAND
                    |       → Render Thread (RT)
                    |       → RHI Thread
                    |   Thread Data Flow
                    |
2. Frame Pipeline   |
                    |   → Frame N: GT prepares scene
                    |   → Frame N-1: RT generates commands
                    |   → Frame N-2: RHI submits to GPU
                    |
3. Synchronization  |
                    |   → FRenderCommandFence
                    |   → FFrameEndSync
                    |   → TaskGraph
                    |
4. Key Mechanisms   |
                    |   → ENQUEUE_RENDER_COMMAND
                    |   → FRenderCommandFence
                    |   → Parallel Command List
                    |   → RHI Command List
```

---

# 一. Threads

## 1. Summary

### 1.1 线程种类

| Three Threads     | 缩写 | 入口                                               | Responsibility                                                                                         |
| ----------------- | ---- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **Game Thread**   | GT   | `UGameEngine::Tick()`                              | GameplayLogic, Layout、ActorTick, Animation, Physics, SceneProxyCreation                               |
| **Render Thread** | RT   | `FRenderingThread::Run()` `ENQUEUE_RENDER_COMMAND` | Visibility culling, DrawCommandGeneration, 渲染资源管理，RenderPassOrchestration 准备提交给 RHI 的任务 |
| **RHI Thread**    | RHIT | `FRHICommandList`                                  | Translate RHI commands to platform API (D3D12/Vulkan/Metal)                                            |
| **GPU Thread**    | GPUT |                                                    | 图形硬件实际执行渲染指令                                                                               |


| Concept                  | Description                                        |
| ------------------------ | -------------------------------------------------- |
| GT                       | Game Thread — gameplay, logic, physics             |
| RT                       | Render Thread — culling, draw command gen          |
| RHIT                     | RHI Thread — native API translation                |
| `ENQUEUE_RENDER_COMMAND` | GT→RT communication macro                          |
| `FPrimitiveSceneProxy`   | RT-safe mirror of UPrimitiveComponent              |
| `FRHICommandList`        | Abstract GPU command buffer                        |
| `FRenderCommandFence`    | GT↔RT synchronization primitive                    |
| `FlushRenderingCommands` | Full GT→RT sync (expensive)                        |
| TaskGraph                | UE's parallel task framework                       |
| Frame Pipelining         | GT/RT/RHIT work on different frames simultaneously |

### 1.2 Thread Frame 

```
┌──────────────┐    ┌───────────────┐    ┌──────────────┐    ┌──────────────┐
│  Game Thread │───>│ Render Thread │───>│  RHI Thread  │───>│     GPU      │
│   (Frame N)  │    │  (Frame N-1)  │    │  (Frame N-2) │    │  (Frame N-3) │
└──────────────┘    └───────────────┘    └──────────────┘    └──────────────┘
```

### 1.3 Thread Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                     Game Thread                         │
│  UPrimitiveComponent → FPrimitiveSceneProxy (create)    │ 1. 创建组件 PrimitiveSceneProxy
│  Transform/Material updates → ENQUEUE_RENDER_COMMAND    │ 2. ENQUEUE_RENDER_COMMAND 发送数据到渲染线程 
└──────────────────────┬──────────────────────────────────┘
                       │ Command Queue
                       ▼
┌─────────────────────────────────────────────────────────┐
│                    Render Thread                        │
│  FScene → Visibility Culling → MeshDrawCommands         │
│  → FRHICommandList generation                           │
└──────────────────────┬──────────────────────────────────┘
                       │ RHI Command Queue
                       ▼
┌─────────────────────────────────────────────────────────┐
│                     RHI Thread                          │
│  FRHICommandList → D3D12/Vulkan/Metal native calls      │
│  → GPU submission                                       │
└─────────────────────────────────────────────────────────┘
```

### 1.4 **线程对应关系**

| Game Thread         | 描述                                             | Renderer Thread      | 描述                                                        |
| ------------------- | ------------------------------------------------ | -------------------- | ----------------------------------------------------------- |
| UWorld              | 一组可以相互交互的Actor和组件的集合              | FScene               | UWorld在渲染模块的代表                                      |
| FSceneView          | FScene内的单个视图 FScene允许有多个view          | FViewInfo            | view在渲染器的内部代表                                      |
| ULocalPlayer        | 每个ULocalPlayer拥有一个FSceneViewState实例      | FSceneViewState      | 有关view的渲染器私有信息                                    |
| ULightComponent     | 光源组件 所有光源类型的父类                      | FLightSceneProxy     | 渲染线程代表 <br> 镜像了ULightComponent在渲染线程的状态     |
|                     |                                                  | FLightSceneInfo      | 渲染器内部状态 光源组件在渲染线程的映射关系                 |
| UPrimitiveComponent | 图元组件，可渲染物体父类 CPU层裁剪的最小粒度单位 | FPrimitiveSceneProxy | 渲染线程代表 <br> 镜像了UPrimitiveComponent在渲染线程的状态 |
|                     |                                                  | FPrimitiveSceneInfo  | 渲染器内部状态                                              |
| UMaterialInterface  | 游戏线程代表                                     | FMaterialRenderProxy | 渲染线程代表 <br> 镜像了UMaterialInterface在渲染线程的状态  |

#### 1.4.1 FPrimitiveSceneProxy

> Bridge between GT (`UPrimitiveComponent`) and RT (`FScene`)

| GT (Game Thread)         | RT (Render Thread)              |
| ------------------------ | ------------------------------- |
| `UStaticMeshComponent`   | `FStaticMeshSceneProxy`         |
| `USkeletalMeshComponent` | `FSkeletalMeshSceneProxy`       |
| `ULandscapeComponent`    | `FLandscapeComponentSceneProxy` |

```cpp
// Lifecycle
// 1. GT creates proxy
FPrimitiveSceneProxy* Proxy = Component->CreateSceneProxy();

// 2. GT enqueues "add to scene" command
ENQUEUE_RENDER_COMMAND(AddPrimitive)(
    [Scene, Proxy](FRHICommandListImmediate& RHICmdList)
    {
        Scene->AddPrimitive(Proxy);
    }
);

// 3. RT owns proxy lifetime after this point
// 4. GT enqueues "remove" when component is destroyed
```

### 1.5 **线程对应关系**

| 从               | 到                    |                                               |
| ---------------- | --------------------- | --------------------------------------------- |
| FSceneRenderer   | FMeshElementCollector | 一一对应,每个FSceneRenderer拥有一个收集器     |
| FMeshBatch       | FMeshDrawCommand      | FBasePassMeshProcessor::BuildMeshDrawCommands |
| FMeshDrawCommand | FMeshPassProcessor    | 每个Pass都对应了一个FMeshPassProcess          |
| FMeshDrawCommand | RHICommandList        |                                               |

### 1.6 划分粒度

1. **划分粒度**
   - 线性划分：ParallelFor
   - 递归划分：快速排序,将连续数据按照某种规则划分成若干份，每一份又可继续划分成更细粒度，直到某种规则停止划分
2. **竞争条件**
   - 原子操作、临界区、读写锁、内核对象、信号量、互斥体、栅栏、屏障、事件
3. **并行**
   - 数据并行：MMX指令、SIMD技术、Compute着色器等
   - 任务并行：文件加载、音频处理、网络接收、物理模拟

### 1.7 多线程并行

**数据并行**
- 不同的线程携带不同的数据执行相同的逻辑
- 数据并行的应用是MMX指令、SIMD技术、Compute着色器等

**任务并行**
- 游戏引擎经常将文件加载、音频处理、网络接收乃至物理模拟都放到单独的线程，以便它们可以并行地执行不同的任务
- 任务并行是不同的线程执行不同的逻辑，数据可以相同，也可以不同

### 1.8 划分粒度
**线性划分**
并行化的std::for_each和UE里的ParallelFor

```c++
inline void ParallelFor(int32 Num, TFunctionRef<void(int32)> Body, bool bForceSingleThread, bool bPumpRenderingThread=false);
基于TaskGraph机制实现的
ParallelFor(AddPrimitiveBatches.Num(), // 数量
        [&](int32 Index) //回调函数, Index返回索引
        {
            if (!AddPrimitiveBatches[Index]->IsPendingKill())
            {
                Scene->AddPrimitive(AddPrimitiveBatches[Index]);
            }
        },
        !FApp::ShouldUseThreadingForPerformance() // 是否多线程处理
    );
```

**递归划分**
递归划分法是将连续数据按照某种规则划分成若干份，每一份又可继续划分成更细粒度，直到某种规则停止划分。常用于快速排序。

**递归划分法**
将一个大框架内的逻辑划分成若干个子任务，它们之间通常保持独立，也可以有一定依赖，每个任务派发到一个线程执行，这就意味着真正意义上的线程独立，每个线程只需要关注自己所要做的事情即可。
https://www.gdcvault.com/play/1012321/Task-based-Multithreading-How-to

### SIMD
SIMD（Single Instruction, Multiple Data）是一种数据并行的计算方式，可以一次性处理多个数据元素。为了最大化SIMD的效率，常见做法是将同类数据**紧密连续地排列（pack）**在内存中，使其对齐到SIMD指令要求的边界（如16字节、32字节等）。

**虚函数的额外内存开销**

一旦类包含虚函数（即有虚表指针vptr），每个对象实例中都会多出一个vptr字段（通常为4~8字节）。这会导致：

- **数据不再紧密连续**，对象内部多了vptr指针，破坏了内存对齐
- **不同子类对象大小不一**，难以用SIMD对齐“打包”处理
```cpp
struct Base {
    virtual void foo();
    float x, y, z, w;
};
Base arr[1024]; // 每个对象多了vptr，内存布局中间插入指针，影响SIMD加载
```


## 2. Game Thread (GT) 游戏线程

> UPrimitiveComponent → FPrimitiveSceneProxy (create) 

- 主线程、游戏线程和TaskGraph系统的ENamedThreads::GameThread
- 线程修改的是 UPrimitiveComponent
- Execute `UWorld::Tick()`, all Actor/Component Tick
- Update transforms, animation, physics simulation
- Create/Update/Destroy **FPrimitiveSceneProxy** (render thread representation of UPrimitiveComponent)
- Enqueue render commands via `ENQUEUE_RENDER_COMMAND` 

1. **创建组件PrimitiveSceneProxy**
```c++
void FScene::AddPrimitive(UPrimitiveComponent* Primitive)
{
    // 创建图元的场景代理
    FPrimitiveSceneProxy* PrimitiveSceneProxy = Primitive->CreateSceneProxy();
    Primitive->SceneProxy = PrimitiveSceneProxy;

    ENQUEUE_RENDER_COMMAND(AddPrimitiveCommand)(
    [Params = MoveTemp(Params), Scene, PrimitiveSceneInfo, PreviousTransform = MoveTemp(PreviousTransform)](FRHICommandListImmediate& RHICmdList)
    {
        FPrimitiveSceneProxy* SceneProxy = Params.PrimitiveSceneProxy;
        (......)
        SceneProxy->CreateRenderThreadResources();
        // 在渲染线程中将SceneInfo加入到场景中.
        Scene->AddPrimitiveSceneInfo_RenderThread(PrimitiveSceneInfo, PreviousTransform);
    });
}
```

2. **数据发送到渲染线程**
```c++
void FScene::UpdateLightTransform(ULightComponent* Light)
{
    if(Light->SceneProxy)
    {
        // 组装组件的数据到结构体（注意这里不能将Component的地址传到渲染线程，而是将所有要更新的数据拷贝一份）
        FUpdateLightTransformParameters Parameters;
        Parameters.LightToWorld = Light->GetComponentTransform().ToMatrixNoScale();
        Parameters.Position = Light->GetLightPosition();
        FScene* Scene = this;
        FLightSceneInfo* LightSceneInfo = Light->SceneProxy->GetLightSceneInfo();
        // 将数据发送到渲染线程执行.
        ENQUEUE_RENDER_COMMAND(UpdateLightTransform)(
            [Scene, LightSceneInfo, Parameters](FRHICommandListImmediate& RHICmdList)
            {
                FScopeCycleCounter Context(LightSceneInfo->Proxy->GetStatId());
                // 在渲染线程执行数据更新.
                Scene->UpdateLightTransform_RenderThread(LightSceneInfo, Parameters);
            });
    }
}
```

3. **ENQUEUE_RENDER_COMMAND** 渲染命令队列
```c++
// 渲染命令队列
// 游戏线程发送数据到渲染线程
// GT sends data to RT
ENQUEUE_RENDER_COMMAND(UpdateTransform)(
    [Proxy, NewTransform](FRHICommandListImmediate& RHICmdList)
    {
        Proxy->SetTransform(NewTransform);
    }
);
```

## 3. Render Thread (RT) 渲染线程

> 一条专门用于生成渲染指令和渲染逻辑的独立线程
> RenderingThread.h声明了全部对外的接口
> 多线程处理在DX11驱动程序：渲染线程（生产者）、驱动程序线程（消费者）

1. **输入**
- Process render commands from GT's command queue
2. **处理**
- 抽象的图形API调用
- **Visibility & Culling**: Frustum culling, occlusion culling
- **Draw Policy Matching**: Sort and batch draw calls
3. **输出**
- Generate **FRHICommandList** (platform-independent GPU commands) 生成渲染指令和渲染逻辑的独立线程
- Manage render targets, passes (BasePass, LightingPass, PostProcess)

### 3.1 ENQUEUE_RENDER_COMMAND

> 向渲染线程入队渲染指令, Type指明了渲染操作的名字
> GT → RT communication. Enqueues a lambda to be executed on the Render Thread.

```c++
ENQUEUE_RENDER_COMMAND(FAddLightCommand)(
[Scene, LightSceneInfo](FRHICommandListImmediate& RHICmdList)
{
    CSV_SCOPED_TIMING_STAT_EXCLUSIVE(Scene_AddLight);
    FScopeCycleCounter Context(LightSceneInfo->Proxy->GetStatId());
    Scene->AddLightSceneInfo_RenderThread(LightSceneInfo);
});
```

```cpp
// Macro definition (simplified)
#define ENQUEUE_RENDER_COMMAND(CommandName) \
    struct CommandName##_Command { \
        static void Execute(FRHICommandListImmediate& RHICmdList, ...); \
    };

// Usage: GT enqueues work for RT
ENQUEUE_RENDER_COMMAND(MyCommand)(
    [CapturedData](FRHICommandListImmediate& RHICmdList)
    {
        // This runs on Render Thread
        DoSomethingOnRT(CapturedData);
    }
);
```

**Important rules:**
- Captured data must be **thread-safe** (copy or shared_ptr)
- Never capture raw pointers to GT objects that may be destroyed
- Use `FPrimitiveSceneProxy` as RT-safe representation

### 3.2 **多线程** ProcessThreadUntilRequestReturn

```cpp
/** The rendering thread main loop */
void RenderingThreadMain( FEvent* TaskGraphBoundSyncEvent )
{
    ENamedThreads::Type RenderThread = ENamedThreads::Type(ENamedThreads::ActualRenderingThread);
    ENamedThreads::SetRenderThread(RenderThread);
    FTaskGraphInterface::Get().AttachToThread(RenderThread);

    virtual void FTaskGraphInterface::Get().ProcessThreadUntilRequestReturn(RenderThread) final override {
        void Thread(CurrentThread).ProcessTasksUntilQuit(QueueIndex){
            void ProcessTasksNamedThread() {
                while (!Queue(QueueIndex).QuitForReturn) {
                    FBaseGraphTask* Task = Queue(QueueIndex).StallQueue.Pop(0, bStallQueueAllowStall);
                    void Task->Execute(NewTasks, ENamedThreads::Type(ThreadId | (QueueIndex << ENamedThreads::QueueIndexShift))) {
                        void ExecuteTask(NewTasks, CurrentThread){
                            void Task.DoTask(CurrentThread, Subsequents){

                            }
                        }
                    }
                }
            }
        }
    }

    ENamedThreads::SetRenderThread(ENamedThreads::GameThread);
}
```

### 3.3 **非多线程**ProcessThreadUntilIdle
```c++
// 未开启单独的渲染线程，会在游戏线程执行渲染指令
void FlushRenderingCommands(bool bFlushDeferredDeletes)
{
    if (!GIsThreadedRendering
        && !FTaskGraphInterface::Get().IsThreadProcessingTasks(ENamedThreads::GameThread)
        && !FTaskGraphInterface::Get().IsThreadProcessingTasks(ENamedThreads::GameThread_Local))
    {
        FTaskGraphInterface::Get().ProcessThreadUntilIdle(ENamedThreads::GameThread);
        FTaskGraphInterface::Get().ProcessThreadUntilIdle(ENamedThreads::GameThread_Local);
    }
}
```

## 4. RHI Thread

- Translates `FRHICommandList` to native API calls
  - RHI线程作为后端（backtend）会执行和转换渲染线程的Command List成为指定图形API的调用（称为Graphical Command），并提交到GPU执行
  - 转换渲染指令到指定图形API，创建、上传渲染资源到GPU
- D3D12: `ID3D12CommandList`, Vulkan: `VkCommandBuffer`
- Handles GPU resource creation, state management
- Can be disabled (`r.RHICmdBypass=1`), merging into RT
- StartRenderingThread：创建RHIThread
- RHICommandList: 向RHI线程入队

```c++
// RHI thread translates abstract commands
void FD3D12CommandContext::RHIDrawIndexedPrimitive(...)
{
    // Translate to D3D12
    CommandList->DrawIndexedInstanced(IndexCount, InstanceCount, ...);
}
```

### 4.1 FRHICommandList

- 渲染线程如向RHI线程入队任务
- 所有的RHI指令都是预先声明并实现好的，目前存在的RHI渲染指令类型达到近百种

**1. 渲染指令类型**

```c++
FRHICOMMAND_MACRO(FRHICommandUpdateGeometryCacheBuffer)
FRHICOMMAND_MACRO(FRHICommandCopyTexture)
FRHICOMMAND_MACRO(FRHISubmitFrameToEncoder)
FRHICOMMAND_MACRO(FRHICommandBeginRenderPass)
FRHICOMMAND_MACRO(FRHICommandBeginScene)
```

**2. FRHICOMMAND_MACRO**

```c++
// Engine\Source\Runtime\RHI\Public\RHICommandList.h

// RHI命令父类
struct FRHICommandBase
{
    FRHICommandBase* Next = nullptr; // 指向下一条RHI命令.
    // 执行RHI命令并销毁.
    virtual void ExecuteAndDestruct(FRHICommandListBase& CmdList, FRHICommandListDebugContext& DebugContext) = 0;
};

// RHI命令结构体
template<typename TCmd, typename NameType = FUnnamedRhiCommand>
struct FRHICommand : public FRHICommandBase
{
    (......)

    void ExecuteAndDestruct(FRHICommandListBase& CmdList, FRHICommandListDebugContext& Context) override final
    {
        (......)
        
        TCmd *ThisCmd = static_cast<TCmd*>(this);

        ThisCmd->Execute(CmdList);
        ThisCmd->~TCmd();
    }
};

// 向RHI线程发送RHI命令的宏.
#define FRHICOMMAND_MACRO(CommandName)                                \
struct PREPROCESSOR_JOIN(CommandName##String, __LINE__)                \
{                                                                    \
    static const TCHAR* TStr() { return TEXT(#CommandName); }        \
};                                                                    \
struct CommandName final : public FRHICommand<CommandName, PREPROCESSOR_JOIN(CommandName##String, __LINE__)>
```

---

# 二. Frame Pipeline (Pipelining)

## 2.1 Frame Overlap

> UE uses a **pipelined frame model** where GT, RT, and RHIT work on different frames simultaneously.

```
Time ──────────────────────────────────────────────────>

GT:   [Frame 3][Frame 4][Frame 5]
RT:        [Frame 2][Frame 3][Frame 4]
RHIT:           [Frame 1][Frame 2][Frame 3]
GPU:                 [Frame 0][Frame 1][Frame 2]
```

- **Latency**: ~3 frames from GT to screen (can be reduced)
- **Throughput**: All threads busy simultaneously → higher FPS
- `r.OneFrameThreadLag` controls GT-RT overlap (default=1)

## 2.2 Frame Sync Points

| Sync Point                                 | Description                                                        |
| ------------------------------------------ | ------------------------------------------------------------------ |
| `FFrameEndSync`                            | GT waits for RT to finish previous frame before starting new frame |
| `FRenderCommandFence`                      | GT can insert fence and wait for RT to reach it                    |
| `FlushRenderingCommands()`                 | GT blocks until RT finishes all queued commands                    |
| `FRHICommandListImmediate::ImmediateFlush` | RT flushes to RHI immediately                                      |

```cpp
// GT waits for RT to catch up
FRenderCommandFence Fence;
Fence.BeginFence();
Fence.Wait();  // blocks GT until RT processes all commands before fence

// Full flush (expensive, avoid in hot path)
FlushRenderingCommands();
```

---

# 三. Key Mechanisms

## 3.1 Parallel Command List Generation

> 合并命令
> UE4/5 can generate draw commands in parallel using TaskGraph workers.

```
Render Thread
    │
    ├── Worker 0: Generate BasePass commands (Batch 0-99)
    ├── Worker 1: Generate BasePass commands (Batch 100-199)
    ├── Worker 2: Generate ShadowPass commands
    └── Worker 3: Generate TranslucencyPass commands
    │
    ▼
  Merge into final FRHICommandList
```

```cpp
// Parallel for on render thread
ParallelFor(NumBatches,
    [&](int32 BatchIndex)
    {
        FRHICommandList* CmdList = new FRHICommandList(...);
        // Generate draw commands for this batch
        for (auto& MeshBatch : Batches[BatchIndex])
        {
            MeshBatch.Draw(CmdList);
        }
        ParallelCmdLists[BatchIndex] = CmdList;
    }
);

// Merge parallel command lists
RHICmdList.QueueParallelAsyncCommandListSubmit(ParallelCmdLists);
```

## 3.2 TaskGraph System

> UE's task-based parallelism framework, used extensively in rendering.

```cpp
// Define a task
class FMyRenderTask
{
public:
    static ENamedThreads::Type GetDesiredThread() { return ENamedThreads::AnyThread; }
    static ESubsequentsMode::Type GetSubsequentsMode() { return ESubsequentsMode::TrackSubsequents; }
    
    void DoTask(ENamedThreads::Type CurrentThread, const FGraphEventRef& MyCompletionGraphEvent)
    {
        // Do parallel work
    }
};

// Dispatch
FGraphEventRef Event = TGraphTask<FMyRenderTask>::CreateTask().ConstructAndDispatchWhenReady();
```

---

# 四. Render Thread Execution Flow

## 4.1 Per-Frame RT Flow

```
FDeferredShadingSceneRenderer::Render()
│
├── InitViews()                          // Visibility, culling, relevance
│   ├── FrustumCull()
│   ├── OcclusionCull()
│   └── ComputeViewVisibility()
│
├── RenderPrePass()                      // Depth PrePass (PreZ)
│   └── Early Z for opaque
│
├── RenderBasePass()                     // GBuffer fill (Deferred)
│   ├── Opaque geometry
│   └── Masked geometry
│
├── RenderLights()                       // Direct lighting
│   ├── Per-light shadow maps
│   └── Light accumulation
│
├── RenderIndirectLighting()             // GI, reflections
│   ├── Screen Space Reflections
│   ├── Reflection Captures
│   └── Indirect Lighting Cache
│
├── RenderTranslucency()                 // Translucent objects
│
├── RenderPostProcessing()               // Post effects
│   ├── Bloom
│   ├── Tone Mapping
│   ├── DOF
│   └── Anti-Aliasing (TAA/TSR)
│
└── Present()                            // Swap buffer
```

## 4.2 Deferred vs Forward

|                  | Deferred Shading              | Forward Shading    |
| ---------------- | ----------------------------- | ------------------ |
| **GBuffer**      | Yes (BasePass writes GBuffer) | No                 |
| **Light Count**  | Unlimited (screen-space)      | Limited per-object |
| **MSAA**         | Not supported                 | Supported          |
| **Translucency** | Separate pass                 | Same pass          |
| **Mobile**       | Not typical                   | Default on mobile  |
| **Thread Usage** | Heavy RT parallel             | Lighter RT         |

---

# 五. Common Console Variables

| CVar                                   | Default | Description                           |
| -------------------------------------- | ------- | ------------------------------------- |
| `r.RHICmdBypass`                       | 0       | 1 = disable RHI thread, merge into RT |
| `r.RHIThread.Enable`                   | 1       | Enable/disable dedicated RHI thread   |
| `r.OneFrameThreadLag`                  | 1       | Allow GT to run 1 frame ahead of RT   |
| `r.ParallelTranslucency`               | 1       | Parallel translucency rendering       |
| `r.MeshDrawCommands.ParallelPassSetup` | 1       | Parallel mesh draw command generation |
| `r.DoInitViewsLightingAfterPrepass`    | 0       | Overlap lighting setup with prepass   |
| `r.GTSyncType`                         | 1       | GT-RT sync mode (0=none, 1=fence)     |

```cpp
// Check thread in code
check(IsInGameThread());
check(IsInRenderingThread());
check(IsInRHIThread());
```

---

# 六. Performance Tips

## 6.1 Avoid Full Flush

```cpp
// BAD: blocks GT until RT finishes everything
FlushRenderingCommands();

// GOOD: use fence for targeted sync
FRenderCommandFence Fence;
Fence.BeginFence();
// ... do other GT work ...
Fence.Wait(); // only block when actually needed
```

## 6.2 Reduce GT-RT Contention

- Minimize `ENQUEUE_RENDER_COMMAND` frequency (batch updates)
- Use `FPrimitiveSceneProxy` double-buffering for transform updates
- Avoid accessing RT data from GT (use async readback)

## 6.3 Parallel Rendering

- Enable `r.MeshDrawCommands.ParallelPassSetup=1`
- Use instancing / ISM / HISM to reduce draw call count
- Nanite (UE5): GPU-driven rendering bypasses much of CPU-side draw call generation

---

# 七. Thread Primitives 线程原理

## 7.1 FRunnable & FRunnableThread

> UE's basic thread abstraction. Wrap work in `FRunnable`, launch with `FRunnableThread`.

```cpp

// Launch
FMyWorker* Worker = new FMyWorker();
FRunnableThread* Thread = FRunnableThread::Create(
    Worker,
    TEXT("MyWorkerThread"),
    0,                          // stack size (0 = default)
    TPri_Normal                 // priority
);

// Shutdown
Thread->Kill(true);  // true = wait for completion
delete Thread;
delete Worker;

class FMyWorker : public FRunnable
{
public:
    // Called when thread starts
    virtual bool Init() override { return true; }

    // Main thread body
    virtual uint32 Run() override
    {
        while (!bStopping)
        {
            // Do work
            FPlatformProcess::Sleep(0.01f);
        }
        return 0;
    }

    // Called when thread is requested to stop
    virtual void Stop() override { bStopping = true; }

    // Called after Run() exits
    virtual void Exit() override { /* cleanup */ }

private:
    FThreadSafeBool bStopping = false;
};

```

## 7.2 FAsyncTask & FAutoDeleteAsyncTask

> Higher-level async work, runs on thread pool. No manual thread management.

```cpp

// Option 1: Manual lifecycle
FAsyncTask<FMyAsyncWork>* Task = new FAsyncTask<FMyAsyncWork>();
Task->StartBackgroundTask();       // run on thread pool
// Task->StartSynchronousTask();   // or run on calling thread
Task->EnsureCompletion();          // block until done
delete Task;

// Option 2: Auto-delete (fire and forget)
(new FAutoDeleteAsyncTask<FMyAsyncWork>())->StartBackgroundTask();

class FMyAsyncWork : public FNonAbandonableTask
{
    friend class FAutoDeleteAsyncTask<FMyAsyncWork>;

    void DoWork()
    {
        // Heavy computation here
    }

    FORCEINLINE TStatId GetStatId() const
    {
        RETURN_QUICK_DECLARE_CYCLE_STAT(FMyAsyncWork, STATGROUP_ThreadPoolAsyncTasks);
    }
};

```

## 7.3 Async() Helper

> Simplest way to run a lambda asynchronously.

```cpp
// Fire on any thread pool worker
TFuture<int32> Future = Async(EAsyncExecution::ThreadPool, []()
{
    // Heavy work
    return 42;
});

// Get result (blocks if not ready)
int32 Result = Future.Get();

// Non-blocking check
if (Future.IsReady())
{
    int32 Result = Future.Get();
}
```

| EAsyncExecution | Description                           |
| --------------- | ------------------------------------- |
| `Thread`        | Dedicated new thread                  |
| `ThreadPool`    | UE's global thread pool               |
| `TaskGraph`     | TaskGraph system (named thread aware) |

## 7.4 Thread-Safe Delegates

```cpp
// Dispatch to Game Thread from any thread
AsyncTask(ENamedThreads::GameThread, []()
{
    // Safe to access UObjects here
    GEngine->AddOnScreenDebugMessage(-1, 5.f, FColor::Red, TEXT("From worker"));
});

// Dispatch to Render Thread
ENQUEUE_RENDER_COMMAND(MyCmd)(
    [](FRHICommandListImmediate& RHICmdList)
    {
        // Safe to access render resources here
    }
);
```

---