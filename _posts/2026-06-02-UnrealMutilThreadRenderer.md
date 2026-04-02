---
layout:     post
title:      Unreal Multi-Thread Renderer
subtitle:   UE multi-thread rendering architecture and pipeline
date:       2026-4-2
author:     kang
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - Rendering
---

<!-- [toc] -->

<center> Unreal Multi-Thread Renderer </center>

# <center>Multi-Thread Renderer Overview</center>

```
1. Three Threads    |
                    |   → Game Thread (GT)
                    |   → Render Thread (RT)
                    |   → RHI Thread
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

# 一. Three Threads

## 1. Summary

### 1.1 线程种类

| Three Threads              | Abbreviation | 职责                                                     | Responsibility                                                         | 入口                                               |
| -------------------------- | ------------ | -------------------------------------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------- |
| **Game Thread** 主线程     | GT           | 游戏逻辑、蓝图、物理、动画等高层逻辑处理                 | Gameplay logic, Actor tick, animation, physics, scene proxy creation   | `UGameEngine::Tick()`                              |
| **Render Thread** 渲染线程 | RT           | 渲染命令生成，渲染资源管理，准备提交给 RHI 的任务        | Visibility culling, draw command generation, render pass orchestration | `FRenderingThread::Run()` `ENQUEUE_RENDER_COMMAND` |
| **RHI Thread** RHI线程     | RHIT         | 渲染硬件接口层，与底层图形 API 交互（DX12/Vulkan/Metal等 | Translate RHI commands to platform API (D3D12/Vulkan/Metal)            | `FRHICommandList`                                  |
| **GPU Thread** GPU线程     | GPUT         | 图形硬件实际执行渲染指令                                 |                                                                        |                                                    |

- **主线程入口**：
- **渲染线程入口**：
- **渲染命令队列**： 宏
- **RHI接口**：
- 
### 1.2 Thread Frame 

```
┌──────────────┐    ┌───────────────┐    ┌──────────────┐    ┌───────────┐
│  Game Thread │───>│ Render Thread │───>│  RHI Thread  │───>│   GPU     │
│   (Frame N)  │    │  (Frame N-1)  │    │  (Frame N-2) │    │(Frame N-3)│
└──────────────┘    └───────────────┘    └──────────────┘    └───────────┘
```

### 1.3 Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                     Game Thread                         │
│  UPrimitiveComponent → FPrimitiveSceneProxy (create)    │ 1. 创建组件 PrimitiveSceneProxy
│  Transform/Material updates → ENQUEUE_RENDER_COMMAND    │ 2. ENQUEUE_RENDER_COMMAND 数据发送到渲染线程 
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

### 1.6 Data Flow

1. **划分粒度**
   - 线性划分：ParallelFor
   - 递归划分：快速排序,将连续数据按照某种规则划分成若干份，每一份又可继续划分成更细粒度，直到某种规则停止划分
2. **竞争条件**
   - 原子操作、临界区、读写锁、内核对象、信号量、互斥体、栅栏、屏障、事件
3. **并行**
   - 数据并行：MMX指令、SIMD技术、Compute着色器等
   - 任务并行：文件加载、音频处理、网络接收、物理模拟

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

# 七. Thread Primitives

## 7.1 FRunnable & FRunnableThread

> UE's basic thread abstraction. Wrap work in `FRunnable`, launch with `FRunnableThread`.

```cpp
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
```

## 7.2 FAsyncTask & FAutoDeleteAsyncTask

> Higher-level async work, runs on thread pool. No manual thread management.

```cpp
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

// Option 1: Manual lifecycle
FAsyncTask<FMyAsyncWork>* Task = new FAsyncTask<FMyAsyncWork>();
Task->StartBackgroundTask();       // run on thread pool
// Task->StartSynchronousTask();   // or run on calling thread
Task->EnsureCompletion();          // block until done
delete Task;

// Option 2: Auto-delete (fire and forget)
(new FAutoDeleteAsyncTask<FMyAsyncWork>())->StartBackgroundTask();
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

# 八. Locking & Synchronization

## 8.1 Lock Types Overview

| Lock Type          | Header                  | Recursive | Read/Write | Spin | Use Case                          |
| ------------------ | ----------------------- | --------- | ---------- | ---- | --------------------------------- |
| `FCriticalSection` | `HAL/CriticalSection.h` | Yes       | No         | No   | General purpose mutex             |
| `FSpinLock`        | `HAL/SpinLock.h`        | No        | No         | Yes  | Very short critical sections      |
| `FRWLock`          | `HAL/RWLock.h`          | No        | Yes        | No   | Read-heavy shared data            |
| `FScopeLock`       | `Misc/ScopeLock.h`      | —         | —          | —    | RAII wrapper for FCriticalSection |
| `FReadScopeLock`   | `Misc/ScopeLock.h`      | —         | Read       | —    | RAII read lock for FRWLock        |
| `FWriteScopeLock`  | `Misc/ScopeLock.h`      | —         | Write      | —    | RAII write lock for FRWLock       |

## 8.2 FCriticalSection (Mutex)

> Platform-abstracted mutex. Recursive (same thread can lock multiple times).

```cpp
class FThreadSafeCounter
{
    FCriticalSection Mutex;
    int32 Count = 0;

public:
    void Increment()
    {
        // RAII lock — automatically unlocks when scope exits
        FScopeLock Lock(&Mutex);
        Count++;
    }

    int32 GetCount()
    {
        FScopeLock Lock(&Mutex);
        return Count;
    }
};
```

```cpp
// Manual lock/unlock (avoid — prefer FScopeLock)
Mutex.Lock();
// ... critical section ...
Mutex.Unlock();

// TryLock (non-blocking)
if (Mutex.TryLock())
{
    // ... got the lock ...
    Mutex.Unlock();
}
```

## 8.3 FRWLock (Read-Write Lock)

> Multiple readers OR single writer. Ideal for read-heavy data.

```cpp
class FSharedConfig
{
    FRWLock Lock;
    TMap<FString, FString> Data;

public:
    // Multiple threads can read simultaneously
    FString Get(const FString& Key)
    {
        FReadScopeLock ReadLock(Lock);
        if (const FString* Val = Data.Find(Key))
            return *Val;
        return TEXT("");
    }

    // Only one thread can write, blocks all readers
    void Set(const FString& Key, const FString& Value)
    {
        FWriteScopeLock WriteLock(Lock);
        Data.Add(Key, Value);
    }
};
```

## 8.4 FSpinLock

> Busy-wait lock. No OS context switch. Only for **very short** critical sections (< 1μs).

```cpp
FSpinLock SpinLock;

void QuickUpdate()
{
    SpinLock.Lock();
    // Very fast operation (few instructions)
    CachedValue = NewValue;
    SpinLock.Unlock();
}
```

> ⚠️ **Warning**: SpinLock wastes CPU cycles while waiting. Never hold across allocations, I/O, or any potentially slow operation.

## 8.5 Atomic Operations (Lock-Free)

> No lock needed. Hardware-level atomic instructions. Best performance for simple counters/flags.

```cpp
// FThreadSafeCounter — built-in atomic counter
FThreadSafeCounter Counter;
Counter.Increment();           // atomic ++
Counter.Decrement();           // atomic --
int32 Val = Counter.GetValue(); // atomic read

// FThreadSafeBool — atomic boolean
FThreadSafeBool bRunning = true;
bRunning = false;  // atomic write
if (bRunning) {}   // atomic read

// TAtomic<T> (UE4) / std::atomic<T>
TAtomic<int32> AtomicInt(0);
AtomicInt.Store(42);
int32 Val = AtomicInt.Load();

// FPlatformAtomics — low-level primitives
FPlatformAtomics::InterlockedIncrement(&SharedInt);
FPlatformAtomics::InterlockedDecrement(&SharedInt);
FPlatformAtomics::InterlockedExchange(&SharedInt, NewValue);
FPlatformAtomics::InterlockedCompareExchange(&SharedInt, NewValue, ExpectedValue);
```

| Function                     | Description                                                |
| ---------------------------- | ---------------------------------------------------------- |
| `InterlockedIncrement`       | Atomic `++`                                                |
| `InterlockedDecrement`       | Atomic `--`                                                |
| `InterlockedExchange`        | Atomic swap, returns old value                             |
| `InterlockedCompareExchange` | CAS (Compare-And-Swap), foundation of lock-free algorithms |
| `InterlockedAdd`             | Atomic `+=`                                                |

## 8.6 FEvent (Condition Signal)

> OS event for thread signaling. Thread sleeps until signaled (no busy-wait).

```cpp
// Create event
FEvent* Event = FPlatformProcess::GetSynchEventFromPool();

// Worker thread — wait for signal
void WorkerRun()
{
    while (!bStopping)
    {
        Event->Wait();  // sleep until triggered (or timeout)
        // Process work
    }
}

// Producer thread — signal worker
void EnqueueWork()
{
    WorkQueue.Enqueue(NewWork);
    Event->Trigger();  // wake up worker
}

// Cleanup
FPlatformProcess::ReturnSynchEventToPool(Event);
```

## 8.7 Lock-Free Data Structures

> UE provides lock-free containers for high-performance multi-thread communication.

```cpp
// Single-Producer, Single-Consumer queue (no lock needed)
TQueue<FMyData, EQueueMode::Spsc> SpscQueue;

// Producer thread
SpscQueue.Enqueue(Data);

// Consumer thread
FMyData Item;
while (SpscQueue.Dequeue(Item))
{
    Process(Item);
}

// Multi-Producer, Single-Consumer queue
TQueue<FMyData, EQueueMode::Mpsc> MpscQueue;

// Lock-free linked list
TLockFreePointerListFIFO<FMyData, 0> LockFreeList;
LockFreeList.Push(new FMyData());
FMyData* Item = LockFreeList.Pop();
```

| Container                  | Producers | Consumers | Lock-Free     |
| -------------------------- | --------- | --------- | ------------- |
| `TQueue<T, Spsc>`          | 1         | 1         | Yes           |
| `TQueue<T, Mpsc>`          | N         | 1         | Yes           |
| `TLockFreePointerListFIFO` | N         | N         | Yes           |
| `TCircularQueue`           | 1         | 1         | Yes (bounded) |

## 8.8 Synchronization in Rendering Context

```
┌─────────────────────────────────────────────────────────────┐
│                  GT ↔ RT Synchronization                    │
│                                                             │
│  ENQUEUE_RENDER_COMMAND    Lock-free command queue (Mpsc)   │
│  FRenderCommandFence       FEvent-based fence               │
│  FlushRenderingCommands    Full barrier (blocks GT)         │
│  FPrimitiveSceneProxy      Ownership transfer (no lock)     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  RT ↔ RHI Synchronization                   │
│                                                             │
│  FRHICommandList           Lock-free command buffer         │
│  FRHISubmitCommandsHint    Flush hint to RHI thread         │
│  GPU Fence                 CPU↔GPU sync (FRHIGPUFence)      │
└─────────────────────────────────────────────────────────────┘
```

## 8.9 Common Pitfalls

### Deadlock

```cpp
// BAD: Lock ordering violation → deadlock
// Thread A: Lock(A) → Lock(B)
// Thread B: Lock(B) → Lock(A)

// GOOD: Always lock in consistent order
// Thread A: Lock(A) → Lock(B)
// Thread B: Lock(A) → Lock(B)
```

### GT/RT Race Condition

```cpp
// BAD: Capturing raw pointer — component may be destroyed before RT executes
UStaticMeshComponent* Comp = GetComponent();
ENQUEUE_RENDER_COMMAND(Bad)(
    [Comp](FRHICommandListImmediate& RHICmdList)
    {
        Comp->DoSomething();  // CRASH: Comp may be GC'd
    }
);

// GOOD: Copy data or use SceneProxy
FTransform CopiedTransform = Comp->GetComponentTransform();
ENQUEUE_RENDER_COMMAND(Good)(
    [CopiedTransform](FRHICommandListImmediate& RHICmdList)
    {
        UseTransform(CopiedTransform);  // Safe: value copy
    }
);
```

### Over-Locking

```cpp
// BAD: Lock held during slow operation
{
    FScopeLock Lock(&Mutex);
    LoadTextureFromDisk();  // I/O blocks all other threads!
    ProcessData();
}

// GOOD: Minimize lock scope
FRawData LocalData;
{
    FScopeLock Lock(&Mutex);
    LocalData = SharedData;  // Quick copy under lock
}
ProcessData(LocalData);      // Slow work outside lock
```

### Lock Selection Guide

```
Need sync?  ──No──>  No lock needed
    │
   Yes
    │
 Simple counter/flag?  ──Yes──>  FThreadSafeCounter / FThreadSafeBool / Atomics
    │
   No
    │
 Read-heavy?  ──Yes──>  FRWLock
    │
   No
    │
 Very short critical section (<1μs)?  ──Yes──>  FSpinLock
    │
   No
    │
 General purpose  ──>  FCriticalSection + FScopeLock
    │
 Producer-Consumer?  ──Yes──>  TQueue (Spsc/Mpsc) lock-free
```

---

# Quick Reference

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
