---
layout:     post
title:      Unreal Multi-Thread Lock
subtitle:   UE multi-thread rendering architecture and pipeline
date:       2023-4-7
author:     kang
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - Rendering
---

<center> Unreal Multi-Thread Lock </center>


# Lock Selection Guide

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


# Locking & Synchronization

## Lock Types Overview

| Lock Type          | Header                  | Recursive | Read/Write | Spin | Use Case                          |
| ------------------ | ----------------------- | --------- | ---------- | ---- | --------------------------------- |
| `FCriticalSection` | `HAL/CriticalSection.h` | Yes       | No         | No   | General purpose mutex             |
| `FSpinLock`        | `HAL/SpinLock.h`        | No        | No         | Yes  | Very short critical sections      |
| `FRWLock`          | `HAL/RWLock.h`          | No        | Yes        | No   | Read-heavy shared data            |
| `FScopeLock`       | `Misc/ScopeLock.h`      | —         | —          | —    | RAII wrapper for FCriticalSection |
| `FReadScopeLock`   | `Misc/ScopeLock.h`      | —         | Read       | —    | RAII read lock for FRWLock        |
| `FWriteScopeLock`  | `Misc/ScopeLock.h`      | —         | Write      | —    | RAII write lock for FRWLock       |

## FCriticalSection (Mutex)

> Platform-abstracted mutex. Recursive (same thread can lock multiple times).

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

## FRWLock (Read-Write Lock) 读写锁

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

## FSpinLock 旋转锁

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

## Atomic Operations (Lock-Free) 原子锁

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

### std::atomic原子性
- 并不是关键字，而是STL的模板类
- STL的模板类，可以支持指定类型的原子操作
- 使用原子的类型意味着该类型的实例的读写操作都是原子性的，无法被其它线程切割，从而达到线程安全和同步的目标。
- atomic的实现机制与临界区类似，但效率上比临界区更快
- 可能有些读者会好奇，为什么对于基本类型的操作也需要原子操作。比如：
- 编译成汇编指令后，会有多条指令，这就会在多线程中引起线程上下文切换，引起不可预知的行为。
```c++
int cnt = 0;
auto f = [&]{cnt++;};
std::thread t1{f}, t2{f}, t3{f};
```
为了**避免**这种情况，就需要加入atomic类型：
```c++
std::atomic<int> cnt{0};    // 给cnt加入原子操作。
auto f = [&]{cnt++;};
std::thread t1{f}, t2{f}, t3{f};
```

**compare_exchange_weak**

- 可以很方便地实现线程安全的非阻塞式的数据结构
- weak模式不会卡调用线程，将原子对象的值和预期值（expected）对比，
  - 如果相同，就替换成目标值（desired），并返回true
  - 如果不同，就加载原子对象的值到预期值（expected），并返回false。



## FEvent (Condition Signal)

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

### condition_variable 条件变量

std::condition_variable和std::condition_variable_any都是条件变量，都是C++标准库的实现，它们都需要与互斥量配合使用。
std::condition_variable_any更加通用，会在性能上产生更多的开销。故而，应当首先考虑使用std::condition_variable。
利用条件变量的接口，结合互斥量的使用，可以很方便地执行线程间的等待、通知等操作。示例：
```c++
// main() signals data ready for processing
// Worker thread is processing data
// Worker thread signals data processing completed
// Back in main(), data = Example data after processing
 
std::mutex m;
std::condition_variable cv;    // 声明条件变量
std::string data;
bool ready = false;
bool processed = false;
 
void worker_thread()
{
    // 等待直到主线程改变ready为true.
    std::unique_lock<std::mutex> lk(m);
    cv.wait(lk, []{return ready;});
 
    // 获得了互斥量的锁
    std::cout << "Worker thread is processing data\n";
    data += " after processing";
 
    // 发送数据给主线程
    processed = true;
    std::cout << "Worker thread signals data processing completed\n";
 
    // 手动解锁, 以便主线程获得锁.
    lk.unlock();
    cv.notify_one();
}
 
int main()
{
    std::thread worker(worker_thread);
 
    data = "Example data";
    // send data to the worker thread
    {
        std::lock_guard<std::mutex> lk(m);
        ready = true;
        std::cout << "main() signals data ready for processing\n";
    }
    cv.notify_one();
 
    // wait for the worker
    {
        std::unique_lock<std::mutex> lk(m);
        cv.wait(lk, []{return processed;});
    }
    std::cout << "Back in main(), data = " << data << '\n';
 
    worker.join();
}

```

```c++
//使用std::condition_variable等待数据
std::condition_variable data_cond;
std::mutex mut;
std::queue<data_chunk> data_queue;

void data_preparation_thread()
{
    while(more_data_to_prepare())
    {
        data_chunk const data=prepare_data();
        std::lock_guard<std::mutex> lk(mut);
        data_queue.push(data);
        data_cond.notify_one();//条件锁通知
    }
}
void data_processing_thread()
{
    while(true)
    {
        //这里使用unique_lock是为了后面方便解锁
        std::unique_lock<std::mutex> lk(mut);   
        //收到通知
        data_cond.wait(lk, {[]return !data_queue.empty();});
        data_chunk data = data_queue.front();
        data_queue.pop();
        lk.unlock();
        process(data);
        if(is_last_chunk(data))
            break;
    }
}
```


## Lock-Free Data Structures

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

## Synchronization in Rendering Context

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

## Common Pitfalls

### Deadlock 死锁

```cpp
// BAD: Lock ordering violation → deadlock
// Thread A: Lock(A) → Lock(B)
// Thread B: Lock(B) → Lock(A)

// GOOD: Always lock in consistent order
// Thread A: Lock(A) → Lock(B)
// Thread B: Lock(A) → Lock(B)
```

### GT/RT Race Condition 竞态条件

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

