---
layout:     post
title:      Dedicated Server
subtitle:   一个无渲染、无音频、无输入的纯逻辑服务端进程，基于 C/S 架构运行。
date:       2025-04-09
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - Unreal
---

# Dedicated Server


---

## 目录

1. [基本原理](#1-基本原理)
2. [启动流程](#2-启动流程)
3. [生命周期](#3-生命周期)
4. [网络同步机制](#4-网络同步机制)
5. [优化事项](#5-优化事项)
6. [性能瓶颈分析](#6-性能瓶颈分析)
7. [移动端/云原生部署建议](#7-移动端云原生部署建议)

---

## 1. 基本原理

### 1.1 架构概述

Unreal Dedicated Server 是一个**无渲染、无音频、无输入**的纯逻辑服务端进程，基于 C/S 架构运行。

```
┌────────────────────────────────────────────────────┐
│                  Dedicated Server                  │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ GameMode │  │ World    │  │ NetDriver        │  │
│  │          │  │ Tick     │  │ (UdpNetDriver)   │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │ Physics  │  │ AI/Nav   │  │ ReplicationGraph │  │
│  │ (No GPU) │  │ Mesh     │  │                  │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
└────────────────────────────────────────────────────┘
         │              │                │
    ┌────┴───┐    ┌─────┴──┐       ┌─────┴──┐
    │Client 1│    │Client 2│       │Client N│
    └────────┘    └────────┘       └────────┘
```

### 1.2 与 Listen Server 的区别

| 特性     | Dedicated Server   | Listen Server        |
| -------- | ------------------ | -------------------- |
| 渲染     | ❌ 无               | ✅ 有（Host 客户端）  |
| 公平性   | ✅ 高（无本地优势） | ❌ Host 有延迟优势    |
| 资源消耗 | 低（CPU/内存为主） | 高（需要完整客户端） |
| 适用场景 | 竞技/MMO/大规模    | 合作/小规模          |
| 部署方式 | 独立服务器         | 玩家主机             |

### 1.3 核心模块

```
Dedicated Server 核心模块
├── Engine Core
│   ├── UEngine (GEngine)
│   ├── UWorld
│   └── FEngineLoop
├── Network Layer
│   ├── UNetDriver
│   ├── UNetConnection
│   └── UChannel (ActorChannel / ControlChannel)
├── Replication System
│   ├── FRepLayout
│   ├── FObjectReplicator
│   └── UReplicationGraph (可选)
├── Game Framework
│   ├── AGameModeBase
│   ├── AGameStateBase
│   └── APlayerController
└── Physics & AI
    ├── FPhysScene (CPU Only)
    └── UNavigationSystemV1
```

---

## 2. 启动流程

### 2.1 进程启动命令

```bash
# 基本启动
./MyGame/Binaries/Linux/MyGameServer MyMap?listen -server -log

# 带端口和最大玩家数
./MyGameServer MyMap?listen?MaxPlayers=64 -server -port=7777 -log

# 无头模式（生产环境）
./MyGameServer MyMap -server -log -unattended -nographics
```

### 2.2 启动流程详解

```
进程启动
    │
    ▼
WinMain / main()
    │
    ▼
FEngineLoop::PreInit()
    ├── 解析命令行参数 (FCommandLine)
    ├── 初始化日志系统 (GLog)
    ├── 加载核心模块 (FModuleManager)
    ├── 初始化 TaskGraph (FTaskGraphInterface)
    └── 初始化内存分配器
    │
    ▼
FEngineLoop::Init()
    ├── 创建 GEngine (UGameEngine / UDedicatedServerEngine)
    ├── GEngine->Init()
    │   ├── 初始化渲染（Server 跳过 RHI 初始化）
    │   ├── 初始化物理引擎 (PhysX/Chaos)
    │   ├── 初始化网络驱动 (UNetDriver)
    │   └── 加载默认 GameInstance
    ├── 加载初始 Map
    │   ├── UEngine::LoadMap()
    │   ├── 创建 UWorld
    │   ├── 初始化 WorldSettings
    │   └── BeginPlay() 触发
    └── 开始监听端口 (NetDriver->InitListen)
    │
    ▼
FEngineLoop::Tick() [主循环]
    ├── 计算 DeltaTime
    ├── GEngine->Tick()
    │   ├── World->Tick()
    │   ├── 处理网络数据包
    │   └── 复制 Actor 状态
    └── 循环直到退出
    │
    ▼
FEngineLoop::Exit()
    ├── 通知所有客户端断开
    ├── 销毁 World
    └── 释放所有模块
```

### 2.3 关键初始化代码路径

```cpp
// Engine/Source/Runtime/Launch/Private/LaunchEngineLoop.cpp

// 1. 预初始化
int32 FEngineLoop::PreInit(const TCHAR* CmdLine)
{
    // 解析命令行
    FCommandLine::Set(CmdLine);
    
    // 判断是否为 Server
    // IS_DEDICATED_SERVER 宏在编译时确定
    // 运行时通过 FPlatformProperties::IsServerOnly() 判断
    
    // 初始化 TaskGraph
    FTaskGraphInterface::Startup(FPlatformMisc::NumberOfCores());
    
    return 0;
}

// 2. 网络监听初始化
bool UIpNetDriver::InitListen(FNetworkNotify* InNotify, FURL& LocalURL, bool bReuseAddressAndPort, FString& Error)
{
    // 创建 Socket
    Socket = FSocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->CreateSocket(NAME_DGram, TEXT("Unreal"));
    
    // 绑定端口
    Socket->Bind(BindAddr);
    
    // 开始监听 UDP 数据包
    Socket->Listen(0);
    
    return true;
}
```

### 2.4 Map 加载流程

```
UEngine::LoadMap()
    │
    ├── 清理旧 World（如果存在）
    ├── 创建新 UWorld
    ├── 加载 Level Package
    ├── 初始化 Physics Scene
    ├── 初始化 Navigation Mesh
    ├── SpawnServerActors()
    │   ├── 生成 GameMode
    │   ├── 生成 GameState
    │   └── 生成 WorldSettings Actors
    ├── UWorld::InitializeActorsForPlay()
    │   ├── 所有 Actor::PreInitializeComponents()
    │   ├── 所有 Actor::InitializeComponents()
    │   └── 所有 Actor::PostInitializeComponents()
    └── UWorld::BeginPlay()
        ├── 所有 Actor::BeginPlay()
        └── 开始接受客户端连接
```

---

## 3. 生命周期

### 3.1 Server 整体生命周期

```
[启动] → [初始化] → [等待连接] → [游戏运行] → [关闭]
   │        │          │            │         │
 PreInit  Init     AcceptConn   Tick Loop  Cleanup
```

### 3.2 客户端连接生命周期

```
Client 发起连接请求
    │
    ▼
UNetDriver::NotifyAcceptedConnection()
    │
    ▼
创建 UNetConnection
    │
    ▼
握手阶段 (Challenge/Response)
    ├── NMT_Hello
    ├── NMT_Challenge  
    └── NMT_Login
    │
    ▼
AGameModeBase::PreLogin()
    ├── 验证玩家身份
    └── 检查服务器容量
    │
    ▼
AGameModeBase::Login()
    ├── 创建 PlayerController
    ├── 创建 PlayerState
    └── 返回 APlayerController*
    │
    ▼
AGameModeBase::PostLogin()
    ├── 初始化 HUD（Server 跳过）
    ├── 触发 OnPostLogin 委托
    └── 开始为该客户端复制 Actor
    │
    ▼
AGameModeBase::HandleStartingNewPlayer()
    └── 调用 RestartPlayer() 生成 Pawn
    │
    ▼
[游戏中] 持续同步状态
    │
    ▼
客户端断开 / 超时
    │
    ▼
AGameModeBase::Logout()
    ├── 销毁 PlayerController
    ├── 清理 PlayerState（可配置保留时间）
    └── 触发 OnLogout 委托
```

### 3.3 Actor 在 Server 上的生命周期

```cpp
// Server 上 Actor 完整生命周期

SpawnActor()                                // 生成
    → PreInitializeComponents()             // 组件预初始化
    → InitializeComponents()                // 组件初始化
    → PostInitializeComponents()            // 组件后初始化
    → BeginPlay()                           // 开始游戏逻辑
    → Tick()                                // 每帧更新（Server Tick）
    → [属性变化] → ReplicateProperties()    // 触发复制
    → [RPC调用]  → ProcessRPC()             // 处理 RPC
    → EndPlay()                             // 结束
    → Destroyed()                           // 销毁
```

### 3.4 Server Tick 流程

```
UWorld::Tick(ELevelTick TickType, float DeltaSeconds)
    │
    ├── TickGroup: TG_PrePhysics
    │   ├── Actor Tick (PrePhysics)
    │   └── Component Tick
    │
    ├── Physics Simulation Step
    │   └── FPhysScene::TickPhysScene() [CPU Only on Server]
    │
    ├── TickGroup: TG_PostPhysics  
    │   └── Actor Tick (PostPhysics)
    │
    ├── TickGroup: TG_PostUpdateWork
    │   └── 最终状态更新
    │
    ├── AI Tick
    │   └── UAISystem::Tick()
    │
    └── Network Tick
        ├── UNetDriver::TickDispatch()   // 接收数据包
        ├── UNetDriver::TickFlush()      // 发送复制数据
        └── UNetDriver::PostTickDispatch()
```

### 3.5 World 生命周期状态机

```
EWorldType::None
    → EWorldType::Game (Server)
        → InitializeActorsForPlay
        → BeginPlay
        → [Running]
        → EndPlay
    → EWorldType::Inactive
```

---

## 4. 网络同步机制

### 4.1 网络架构

```
Server
  └── UNetDriver (UIpNetDriver)
        ├── UNetConnection [Client1]
        │     ├── UControlChannel    // 控制消息
        │     ├── UActorChannel[0]   // Actor 同步
        │     ├── UActorChannel[1]
        │     └── ...
        ├── UNetConnection [Client2]
        └── ...
```

### 4.2 属性复制（Property Replication）

```cpp
// 1. 声明需要复制的属性
class AMyActor : public AActor
{
    UPROPERTY(Replicated)
    int32 Health;
    
    UPROPERTY(ReplicatedUsing = OnRep_Score)
    float Score;
    
    // 注册复制属性
    virtual void GetLifetimeReplicatedProps(
        TArray<FLifetimeProperty>& OutLifetimeProps) const override
    {
        Super::GetLifetimeReplicatedProps(OutLifetimeProps);
        
        DOREPLIFETIME(AMyActor, Health);
        
        // 条件复制
        DOREPLIFETIME_CONDITION(AMyActor, Score, COND_OwnerOnly);
    }
};
```

#### 复制条件（Replication Conditions）

| 条件                  | 说明                                         |
| --------------------- | -------------------------------------------- |
| `COND_None`           | 无条件复制给所有客户端                       |
| `COND_OwnerOnly`      | 只复制给拥有者                               |
| `COND_SkipOwner`      | 跳过拥有者，复制给其他人                     |
| `COND_SimulatedOnly`  | 只复制给模拟代理                             |
| `COND_AutonomousOnly` | 只复制给自主代理                             |
| `COND_InitialOnly`    | 只在初始化时复制一次                         |
| `COND_ReplayOrOwner`  | 回放或拥有者                                 |
| `COND_Custom`         | 自定义条件（配合 SetCustomIsActiveOverride） |

### 4.3 RPC 机制

```cpp
// Server RPC：客户端调用，服务端执行
UFUNCTION(Server, Reliable, WithValidation)
void ServerDoAction(FVector Location);

bool AMyActor::ServerDoAction_Validate(FVector Location)
{
    // 反作弊验证
    return Location.Z >= 0.0f;
}

void AMyActor::ServerDoAction_Implementation(FVector Location)
{
    // 服务端执行逻辑
    SetActorLocation(Location);
}

// Client RPC：服务端调用，客户端执行
UFUNCTION(Client, Reliable)
void ClientReceiveMessage(const FString& Message);

// Multicast RPC：服务端调用，所有客户端执行
UFUNCTION(NetMulticast, Unreliable)
void MulticastPlayEffect(FVector Position);
```

#### RPC 可靠性对比

| 类型         | 说明                 | 适用场景               |
| ------------ | -------------------- | ---------------------- |
| `Reliable`   | 保证送达，有重传机制 | 重要游戏事件、状态变更 |
| `Unreliable` | 不保证送达，无重传   | 特效、音效、非关键更新 |

### 4.4 复制图（Replication Graph）

UE5 推荐使用 `UReplicationGraph` 替代默认复制系统，大幅提升大规模 Actor 同步性能。

```
默认复制系统（Legacy）
    每帧遍历所有 Actor → O(N×M) 复杂度
    N = Actor数量, M = 连接数

Replication Graph
    空间分区 + 分组管理 → O(K×M)
    K = 每个客户端可见的 Actor 数量（远小于 N）
```

```cpp
// 自定义 ReplicationGraph 节点
class UMyReplicationGraphNode_GridSpatialization2D 
    : public UReplicationGraphNode_GridSpatialization2D
{
    // 基于网格空间分区，只同步视野内的 Actor
    // 大型开放世界场景必备
};

// 注册到 ReplicationGraph
void UMyReplicationGraph::InitGlobalActorClassSettings()
{
    // 静态 Actor：只在初始化时同步一次
    ClassRepNodePolicies.Set(AStaticMeshActor::StaticClass(),
        EClassRepNodeMapping::NotRouted);
    
    // 动态 Actor：使用空间分区节点
    ClassRepNodePolicies.Set(ACharacter::StaticClass(),
        EClassRepNodeMapping::Spatialize_Dynamic);
}
```

### 4.5 网络优先级与带宽控制

```cpp
// Actor 网络优先级
class AMyActor : public AActor
{
    // 提高重要 Actor 的复制优先级
    virtual float GetNetPriority(
        const FVector& ViewPos, 
        const FVector& ViewDir,
        AActor* Viewer,
        AActor* ViewTarget,
        UActorChannel* InChannel,
        float Time, 
        bool bLowBandwidth) const override
    {
        // 距离越近优先级越高
        float Distance = FVector::Dist(ViewPos, GetActorLocation());
        return FMath::Clamp(10000.0f / Distance, 1.0f, 10.0f);
    }
};
```

### 4.6 网络同步流程（每帧）

```
UNetDriver::TickFlush()
    │
    ├── 遍历所有 UNetConnection
    │   │
    │   ├── 计算本帧可用带宽 (Saturate Check)
    │   │
    │   ├── 收集需要复制的 Actor 列表
    │   │   └── ReplicationGraph::GatherActorListsForConnection()
    │   │
    │   ├── 按优先级排序 Actor
    │   │
    │   ├── 遍历 Actor 列表
    │   │   ├── 获取/创建 UActorChannel
    │   │   ├── FObjectReplicator::ReplicateProperties()
    │   │   │   ├── 比较属性与上次发送的 Shadow State
    │   │   │   ├── 序列化变化的属性
    │   │   │   └── 写入发送缓冲区
    │   │   └── 检查带宽是否耗尽
    │   │
    │   └── FlushNet() 发送数据包
    │
    └── 统计网络性能数据
```

---

## 5. 优化事项

### 5.1 Tick 优化

```cpp
// 1. 降低不重要 Actor 的 Tick 频率
AMyActor::AMyActor()
{
    // 每 0.1 秒 Tick 一次（而非每帧）
    PrimaryActorTick.TickInterval = 0.1f;
    
    // 不需要 Tick 的 Actor 直接关闭
    PrimaryActorTick.bCanEverTick = false;
}

// 2. 使用 SetActorTickInterval 动态调整
void AMyActor::OnPlayerFarAway()
{
    // 玩家远离时降低 Tick 频率
    SetActorTickInterval(1.0f);
}

// 3. 使用 TickGroup 合理分组
PrimaryActorTick.TickGroup = TG_PostPhysics;
```

### 5.2 网络优化

```ini
# DefaultEngine.ini 网络配置
[/Script/Engine.GameNetworkManager]
# 每个连接每秒最大复制 Actor 数
MaxDynamicBandwidth=7000
MinDynamicBandwidth=4000

# 每帧每个连接的最大发送字节数
TotalNetBandwidth=32000

[/Script/OnlineSubsystemUtils.IpNetDriver]
# 最大数据包大小
MaxClientRate=15000
MaxInternetClientRate=10000

# 连接超时时间
ConnectionTimeout=80.0
InitialConnectTimeout=120.0
```

```cpp
// 减少不必要的属性复制
// 使用 Push Model 按需标记脏属性（UE5 推荐）
#include "Net/Core/PushModel/PushModel.h"

void AMyActor::SetHealth(int32 NewHealth)
{
    Health = NewHealth;
    // 只有调用此函数时才标记为需要复制
    MARK_PROPERTY_DIRTY_FROM_NAME(AMyActor, Health, this);
}
```

### 5.3 内存优化

```cpp
// 1. Server 不加载客户端专用资源
// 在 .uasset 中设置 Cook 规则，或使用条件加载
if (!IsRunningDedicatedServer())
{
    // 加载音效、特效等客户端资源
    LoadClientOnlyAssets();
}

// 2. 使用 UPROPERTY 标记避免不必要的序列化
UPROPERTY(SkipSerialization)
UTexture2D* ClientOnlyTexture; // Server 不需要

// 3. 合理使用对象池
class AMyProjectilePool : public AActor
{
    TArray<AMyProjectile*> Pool;
    
    AMyProjectile* GetFromPool()
    {
        for (auto* Proj : Pool)
        {
            if (!Proj->IsActive())
                return Proj;
        }
        return SpawnNewProjectile();
    }
};
```

### 5.4 物理优化

```cpp
// Server 上物理优化
// 1. 减少物理模拟精度（Server 不需要视觉精度）
UBodySetup* BodySetup = Mesh->GetBodySetup();
BodySetup->CollisionTraceFlag = CTF_UseSimpleAsComplex;

// 2. 对远离玩家的 Actor 禁用物理
void AMyActor::OnPlayerDistanceChanged(float Distance)
{
    if (Distance > 5000.0f)
    {
        GetRootComponent()->SetSimulatePhysics(false);
    }
}

// 3. 使用 Async Physics Tick（UE5）
// 在 Project Settings 中启用 Physics > Tick Physics Async
```

### 5.5 AI 优化

```cpp
// 1. 限制同时寻路的 AI 数量
UNavigationSystemV1* NavSys = UNavigationSystemV1::GetCurrent(GetWorld());
NavSys->SetMaxSimultaneousQueries(8);

// 2. 使用 EQS 缓存
UEnvQueryManager* EQSManager = UEnvQueryManager::GetCurrent(GetWorld());
// 配置 EQS 查询间隔，避免每帧查询

// 3. AI LOD：远处 AI 降低更新频率
void AMyAIController::SetAILOD(float DistanceToPlayer)
{
    if (DistanceToPlayer > 3000.0f)
    {
        GetBrainComponent()->PauseLogic(TEXT("Far from player"));
    }
    else
    {
        GetBrainComponent()->ResumeLogic(TEXT("Near player"));
    }
}
```

### 5.6 多线程优化

```cpp
// 使用 TaskGraph 并行处理游戏逻辑
FGraphEventRef Task = FFunctionGraphTask::CreateAndDispatchWhenReady(
    [this]()
    {
        // 并行计算 AI 决策
        ProcessAIDecisions();
    },
    TStatId(),
    nullptr,
    ENamedThreads::AnyBackgroundThreadNormalTask
);

// 等待任务完成
FTaskGraphInterface::Get().WaitUntilTaskCompletes(Task);

// 使用 ParallelFor 并行处理大量 Actor
ParallelFor(Actors.Num(), [&](int32 Index)
{
    Actors[Index]->UpdateLogic();
});
```

---

## 6. 性能瓶颈分析

### 6.1 常见瓶颈点

```
Dedicated Server 性能瓶颈
├── CPU 瓶颈（最常见）
│   ├── 过多 Actor Tick
│   ├── 物理模拟开销
│   ├── AI 寻路计算
│   ├── 网络序列化/反序列化
│   └── GC（垃圾回收）停顿
│
├── 内存瓶颈
│   ├── Actor/Object 数量过多
│   ├── 导航网格内存占用
│   └── 网络缓冲区
│
├── 网络带宽瓶颈
│   ├── 复制 Actor 数量过多
│   ├── 属性变化频率过高
│   └── 大型数据结构复制
│
└── I/O 瓶颈
    ├── 频繁的存档读写
    └── 日志写入
```

### 6.2 性能分析工具

```bash
# 1. 启动时开启统计
./MyGameServer MyMap -server -log -stats

# 2. 运行时控制台命令
stat net          # 网络统计
stat game         # 游戏逻辑统计
stat unit         # 帧时间统计
stat unitgraph    # 帧时间图表
stat memory       # 内存统计
stat physics      # 物理统计
stat ai           # AI 统计

# 3. 网络性能详情
net.RepGraph.PrintAllActorInfo 1
net.ListNetGUIDExports
```

```cpp
// 代码中添加性能标记
void AMyActor::Tick(float DeltaTime)
{
    SCOPE_CYCLE_COUNTER(STAT_MyActorTick);
    
    // ... 逻辑代码
}

// 自定义统计组
DECLARE_CYCLE_STAT(TEXT("MyActor Tick"), STAT_MyActorTick, STATGROUP_Game);
```

### 6.3 网络瓶颈诊断

```
诊断网络瓶颈步骤：

1. 检查 NetDriver 统计
   → stat net 查看 OutBytes/InBytes/Ping

2. 检查复制 Actor 数量
   → net.RepGraph.PrintAllActorInfo
   → 目标：每个连接每帧 < 100 个 Actor 更新

3. 检查带宽饱和
   → 查看 Saturated 标志
   → 调整 MaxClientRate

4. 检查 RPC 频率
   → 避免每帧调用 Reliable RPC
   → 合并多个小 RPC 为一个大 RPC

5. 使用 Network Profiler
   → 启动参数加 -networkprofiler
   → 使用 NetworkProfiler.exe 分析
```

### 6.4 GC 优化

```ini
# DefaultEngine.ini
[/Script/Engine.GarbageCollectionSettings]
# 增大 GC 触发阈值，减少 GC 频率
gc.MaxObjectsNotConsideredByGC=1000000
gc.SizeOfPermanentObjectPool=0

# 增量 GC（减少单次停顿时间）
gc.IncrementalGCTimePerFrame=0.002

# 多线程 GC（UE5）
gc.AllowParallelGC=1
```

### 6.5 典型性能指标参考

| 指标                | 良好     | 警告       | 危险      |
| ------------------- | -------- | ---------- | --------- |
| Server Frame Time   | < 33ms   | 33-50ms    | > 50ms    |
| 每连接复制 Actor/帧 | < 100    | 100-300    | > 300     |
| 网络带宽/连接       | < 50KB/s | 50-100KB/s | > 100KB/s |
| 内存占用            | < 4GB    | 4-8GB      | > 8GB     |
| GC 停顿时间         | < 5ms    | 5-20ms     | > 20ms    |
| 物理 Tick 时间      | < 5ms    | 5-15ms     | > 15ms    |

---

## 7. 移动端/云原生部署建议

### 7.1 容器化部署（Docker/K8s）

```dockerfile
# Dockerfile 示例
FROM ubuntu:22.04

# 安装依赖
RUN apt-get update && apt-get install -y \
    libssl-dev \
    libc++-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制 Server 二进制
COPY ./LinuxServer /app/server
RUN chmod +x /app/server/MyGameServer

# 暴露端口
EXPOSE 7777/udp
EXPOSE 8080/tcp

# 启动命令
CMD ["/app/server/MyGameServer", "MyMap", "-server", "-log", "-port=7777"]
```

```yaml
# Kubernetes Deployment 示例
apiVersion: apps/v1
kind: Deployment
metadata:
  name: game-server
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: game-server
        image: mygame-server:latest
        resources:
          requests:
            cpu: "2"
            memory: "4Gi"
          limits:
            cpu: "4"
            memory: "8Gi"
        ports:
        - containerPort: 7777
          protocol: UDP
```

### 7.2 弹性伸缩策略

```
服务器伸缩策略
├── 水平扩展（推荐）
│   ├── 每个 Match 独立 Server 进程
│   ├── 使用 GameLift / Agones 管理
│   └── 根据玩家队列自动扩缩容
│
├── 垂直扩展
│   ├── 单服务器支持更多玩家
│   └── 需要优化 ReplicationGraph
│
└── 区域部署
    ├── 多地域部署降低延迟
    └── 使用 Anycast 路由
```

### 7.3 移动端网络适配

```cpp
// 针对移动端弱网环境的优化

// 1. 降低发送频率
void UMyNetDriver::SetMobileNetworkMode()
{
    // 移动端降低更新频率
    NetServerMaxTickRate = 20; // 默认 30
    MaxClientRate = 8000;      // 默认 15000
}

// 2. 增加容错机制
// 在 DefaultEngine.ini 中
// ConnectionTimeout=120.0  // 移动端增大超时时间
// InitialConnectTimeout=180.0

// 3. 使用 Adaptive Network Rate
// 根据客户端网络质量动态调整复制频率
void AMyPlayerController::UpdateNetworkQuality(float PacketLoss, float RTT)
{
    if (PacketLoss > 0.05f || RTT > 200.0f)
    {
        // 降低更新频率
        NetUpdateFrequency = 10.0f;
    }
    else
    {
        NetUpdateFrequency = 30.0f;
    }
}
```

### 7.4 监控与告警

```cpp
// 自定义性能监控上报
class FServerMetricsReporter
{
public:
    void ReportMetrics()
    {
        FServerMetrics Metrics;
        Metrics.PlayerCount = GetWorld()->GetNumPlayerControllers();
        Metrics.FrameTime = FApp::GetDeltaTime() * 1000.0f;
        Metrics.MemoryUsageMB = FPlatformMemory::GetStats().UsedPhysical / 1024 / 1024;
        
        // 上报到监控系统（Prometheus/CloudWatch等）
        HttpReportMetrics(Metrics);
    }
};
```

---

## 附录：关键 CVar 配置参考

```ini
# DefaultEngine.ini 完整服务器优化配置

[/Script/Engine.Engine]
# Server Tick Rate
NetServerMaxTickRate=30
bSmoothFrameRate=false

[/Script/Engine.GameNetworkManager]
TotalNetBandwidth=32000
MaxDynamicBandwidth=7000
MinDynamicBandwidth=4000
ADJUSTED_NET_UPDATE_DIST=1024.0
MAX_NEAR_PLANE_DIST=1024.0

[/Script/OnlineSubsystemUtils.IpNetDriver]
MaxClientRate=15000
MaxInternetClientRate=10000
RelevancyUpdateTimeout=5.0
ConnectionTimeout=80.0
InitialConnectTimeout=120.0
KeepAliveTime=0.2

[/Script/Engine.GarbageCollectionSettings]
gc.MaxObjectsNotConsideredByGC=1000000
gc.IncrementalGCTimePerFrame=0.002
gc.AllowParallelGC=1

[ConsoleVariables]
# 禁用不必要的渲染功能
r.SetRes=0x0
foliage.DitheredLOD=0
# 启用 Push Model 复制
net.IsPushModelEnabled=1
# 启用 ReplicationGraph
net.RepGraph.Enable=1
```