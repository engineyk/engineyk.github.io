---
layout:     post
title:      Unreal Multi Thread Lock
subtitle:   UE multi thread rendering architecture and pipeline
date:       2023-4-9
author:     kang
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - Multi-Thread-Rendering
---

<center> Unreal Multi-Thread Lock </center>


```        
1. Overview                 |
                            |   Lock Selection Guide
                            |   → 锁机制和封锁协议
                            |       → 三级封锁
                            |       → 两段锁协议
                            |       → 封锁协议
                            |   → 并发控制
                            |       → 原子性
                            |       → 一致性
                            |       → 隔离性
                            |       → 持久性
                            |       → 互相依赖/循环依赖
                            |   → 线程安全
                            |       → 数据竞争（Race Condition）
                            |       → 死锁（Deadlock）
                            |       → 线程饥饿（Thread Starvation）
                            |   → 线程同步问题
                            |       → 生产者 - 消费者问题
                            |       → 线程间通信
                            |   → 线程资源管理
                            |       → 线程数量控制
                            |       → 资源释放
2. Lock                     |
                            |   → 锁
                            |       → Mutex Lock            互斥锁 FCriticalSection
                            |       → Read-Write Lock       读写锁
                            |       →   Read Lock           读锁
                            |       →   Write Lock          写锁
                            |       → 条件锁
                            |       → 自旋锁
                            |       → 递归锁
                            |       → condition_variable    条件变量
                            |       → atomic                原子操作
                            |           → TAtomic
                            |           → std::atomic
                            |       → MemoryBarrier 内存屏障
                            |   → STD
                            |       → std::future   获取线程值
                            |       → Mutex
3. Dead Lock                |
                            |   → 死锁的四个条件
                            |       → 互斥
                            |       → 保持
                            |       → 不能剥夺
                            |       → 互斥
                            |   → 如何解决？
4. QA                       |
                            |   → 读写锁与互斥锁的区别与关系
```


# Overview

## 锁机制和封锁协议

### 1. 三级封锁

- 一级封锁协议	
  - 事务T在修改数据R之前必须先对其加X锁，直到事务结束才释放。一级封锁协议可以防止丢失修改，并保证事务T是可恢复的。
    即更新数据前先加写锁
- 二级封锁协议	
  - 即在一级封锁协议的基础上，读数据先加读锁，读完立即释放读锁
    可防止丢失修改，还可防止读“脏”数据
    二级封锁协议是指，在一级封锁协议基础上增加事务T在读数据R之前必须先对其加S锁，读完后即可释放S锁。二级封锁协议除防止丢失修改，还可以进一步防止读“脏”数据。
- 三级封锁协议 	
  - 即在一级封锁协议的基础上. 读数据先加读锁，等事务结束再释放读锁（与二级封锁协议释放时间点不同）
    可防止丢失修改、读“脏”数据与数据不可重复读
    三级封锁协议是指，在一级封锁协议基础上增加事务T在读数据R之前必须先对其加S锁，直到事务结束才释放。三级封锁协议除防止了丢失修改和读“脏”数据外，还可以进一步防止不可重复读。

### 2. 两段锁协议

可串行化，有可能发生死锁
- 两段锁协议：
  - 是指所有的事务必须分两个阶段对数据项加锁和解锁。即事务分两个阶段，
  - 第一个阶段是获得封锁。事务可以获得任何数据项上的任何类型的锁，但是不能释放；
  - 第二阶段是释放封锁，事务可以释放任何数据项上的任何类型的锁，但不能申请。

### 3. 封锁协议
- X锁：排它锁 也称为写锁
- S锁：共享锁 也称为读锁
  
## 并发控制

### 1. 原子性
- 整个事务中的所有操作，要么全部完成，要么全部不完成，不可能停滞在中间某个环节。
- 事务在执行过程中发生错误，会被回滚（Rollback）到事务开始前的状态，就像这个事务从来没有执行过一样。
### 2. 一致性
- 在事务开始之前和事务结束以后，数据库的完整性约束没有被破坏。
### 3. 隔离性
- 隔离状态执行事务，使它们好像是系统在给定时间内执行的唯一操作。
- 如果有两个事务，运行在相同的时间内，执行相同的功能，事务的隔离性将确保每一事务在系统中认为只有该事务在使用系统。
- 这种属性有时称为串行化，为了防止事务操作间的混淆，必须串行化或序列化请求，使得在同一时间仅有一个请求用于同一数据。
### 4. 持久性
- 在事务完成以后，该事务所对数据库所作的更改便持久的保存在数据库之中，并不会被回滚。
### 5. 并发处理
- 提高操作的效率

### 并发控制存在的问题
- 丢失更新
- 不可重复读
- 读“脏”数据（临时值）

## 线程安全
### 1. 数据竞争（Race Condition）
多个线程同时访问和修改共享数据，导致数据结果不可预测。
**互斥锁（Mutex）**
 使用互斥锁保护共享数据的访问。例如，在C++中可以使用std::mutex。
**原子操作（Atomic Operations）**
 对于简单的变量操作，使用原子操作确保操作的不可分割性。例如，Java中的AtomicInteger
**线程局部存储（Thread - Local Storage, TLS**
为每个线程提供数据副本，避免共享数据竞争

volatile保证可见性但不保证原子性

### 2. 死锁（Deadlock）
多个线程互相等待对方持有的资源，导致无法继续执行。
**避免嵌套锁**
尽量避免在一个线程中嵌套获取多个锁。如果必须嵌套，确保锁的获取**顺序一致**。 
**使用超时机制**
在尝试获取锁时设置超时时间，超时后释放已持有的锁并重新尝试。
**死锁检测和恢复**
实现死锁检测机制，检测到死锁后牺牲某些线程来打破死锁。
**通过工具检测死锁**
jstack

死锁，四个必要条件，以及如何避免，比如顺序加锁，超时机制

### 3. 线程饥饿（Thread Starvation）
某些线程因资源竞争而长时间无法获得足够的资源来执行。
**合理设置线程优先级
避免过多高优先级线程，确保线程优先级分配合理。
**使用公平锁**
在某些情况下，使用公平锁确保线程按请求顺序获得锁。
**资源分配策略**
设计合理的资源分配策略，确保每个线程都能获得足够的资源。 


## 线程同步问题

### 生产者 - 消费者问题
生产者线程生成数据放入缓冲区，消费者线程从缓冲区获取数据处理。如果速度不匹配，可能导致缓冲区溢出或消费者等待。 |
**信号量（Semaphore）**
使用信号量控制缓冲区访问。生产者释放信号量，消费者等待信号量。
**条件变量（Condition Variable）**
结合互斥锁使用条件变量实现生产者和消费者同步。

### 线程间通信

线程之间需要传递消息或共享数据，但缺乏正确同步机制可能导致数据不一致或线程阻塞。
**队列（Queue）**
使用线程安全的队列来传递消息。例如，在Python中可以使用queue.Queue，在Java中可以使用BlockingQueue。
**管道（Pipe）**
在某些语言中，可以使用管道来实现线程间的通信。例如，在C语言中可以使用pipe函数。
**共享内存**
如果线程之间需要共享大量数据，可以使用共享内存。但需要注意线程安全问题，可以通过互斥锁等机制来保护共享内存的访问。

## 线程资源管理

### 线程数量控制
线程之间需要传递消息或共享数据，但缺乏正确同步机制可能导致数据不一致或线程阻线程数量过多会导致线程切换开销增大，甚至可能耗尽系统资源（如内存、文件句柄等）。
- **线程池**：避免频繁创建/销毁线程
  - 合理配置核心线程数、最大线程数、队列容量
  - 根据任务类型选择线程池类型（`FixedThreadPool`/`CachedThreadPool`等）
- 及时释放资源（数据库连接、文件句柄等）
- 使用 `ThreadLocal` 时注意内存泄漏

**线程池（Thread Pool）**
使用线程池来管理线程的数量。线程池会预先创建一定数量的线程，并在任务到达时分配给线程执行。当线程完成任务后，会返回线程池等待下一个任务。例如，在Java中可以使用ExecutorService来实现线程池。
**动态线程创建和销毁**
根据系统的负载动态调整线程的数量。当系统负载较高时，可以增加线程数量；当系统负载较低时，可以减少线程数量。

### 资源释放 
线程在执行过程中可能会占用系统资源（如文件句柄、网络连接等），如果线程结束时没有正确释放这些资源，可能会导致资源泄漏。
**使用RAII（Resource Acquisition Is Initialization）模式**
在C++中，可以通过RAII模式来管理资源的生命周期。例如，使用智能指针（如std::unique_ptr）来管理动态分配的内存。
**在异常处理中释放资源**
确保在异常情况下也能正确释放资源。例如，在Java中可以使用try - finally块来释放资源。
**线程终止时清理资源**
在线程结束时，确保释放所有占用的资源。例如，在Python中可以在线程的__del__方法中释放资源。



## Lock Selection Guide

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


## Locking & Synchronization

# Lock Types 

| Lock Type          | --     | Header                  | Recursive | Read/Write | Spin | Use Case                          |
| ------------------ | ------ | ----------------------- | --------- | ---------- | ---- | --------------------------------- |
| `FCriticalSection` | 互斥锁 | `HAL/CriticalSection.h` | Yes       | No         | No   | General purpose mutex             |
| `FSpinLock`        | 自旋锁 | `HAL/SpinLock.h`        | No        | No         | Yes  | Very short critical sections      |
| `FRWLock`          | 读写锁 | `HAL/RWLock.h`          | No        | Yes        | No   | Read-heavy shared data            |
| `FScopeLock`       |        | `Misc/ScopeLock.h`      | —         | —          | —    | RAII wrapper for FCriticalSection |
| `FReadScopeLock`   | 读锁   | `Misc/ScopeLock.h`      | —         | Read       | —    | RAII read lock for FRWLock        |
| `FWriteScopeLock`  | 写锁   | `Misc/ScopeLock.h`      | —         | Write      | —    | RAII write lock for FRWLock       |

## Mutex FCriticalSection (互斥锁)

> Platform-abstracted mutex. Recursive (same thread can lock multiple times).
> std::mutex即互斥量，它会在作用范围内进入临界区（Critical section），使得该代码片段同时只能由一个线程访问，当其它线程尝试执行该片段时，会被阻塞。
> std::mutex常与std::lock_guard，示例代码：

```c++
// 输出
// http://bar => fake content
// http://foo => fake content
 
std::map<std::string, std::string> g_pages;
std::mutex g_pages_mutex;    // 声明互斥量
 
void save_page(const std::string &url)
{
    // simulate a long page fetch
    std::this_thread::sleep_for(std::chrono::seconds(2));
    std::string result = "fake content";
     
    // 配合std::lock_guard使用, 可以及时进入和释放互斥量.
    std::lock_guard<std::mutex> guard(g_pages_mutex);
    g_pages[url] = result;
}
 
int main() 
{
    std::thread t1(save_page, "http://foo");
    std::thread t2(save_page, "http://bar");
    t1.join();
    t2.join();
 
    // safe to access g_pages without lock now, as the threads are joined
    for (const auto &pair : g_pages) {
        std::cout << pair.first << " => " << pair.second << '\n';
    }
}
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
> c++11本身是没有读写锁的，目前c函数，或者c++自己实现一个读写锁读锁
> 写锁
> 脏写数据 读数据后，修改数据时数据被覆盖

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
> 从“自旋锁”的名字也可以看出来，如果一个线程想要获取一个被使用的自旋锁，那么它会一致占用CPU请求这个自旋锁使得CPU不能去做其他的事情，直到获取这个锁为止，这就是“自旋”的含义。

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

## 递归锁

> 互斥锁的基础上多次加锁解锁
> 递归锁（Recursive Lock）也称为可重入互斥锁（reentrant mutex），
  >> 是互斥锁的一种，同一线程对其多次加锁不会产生死锁。
  >> 递归锁会使用引用计数机制，以便可以从同一线程多次加锁、解锁，当加锁、解锁次数相等时，锁才可以被其他线程获取。


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

### condition_variable 条件变量 条件锁

- 条件锁就是所谓的条件变量，某一个线程因为某个条件为满足时可以使用条件变量使改程序处于阻塞状态。
  - 一旦条件满足以“信号量”的方式唤醒一个因为该条件而被阻塞的线程。
  - 最为常见就是在线程池中，起初没有任务时任务队列为空，此时线程池中的线程因为“任务队列为空”这个条件处于阻塞状态。
  - 一旦有任务进来，就会以信号量的方式唤醒一个线程来处理这个任务。

#### 1. 条件锁通知

1. wait()
   1. 阻塞当前线程，等待条件成立。                                                                                                                                                                                |
2. wait_for()   
   1. 阻塞当前线程的过程中，该函数会自动调用 unlock() 函数解锁互斥锁，从而令其他线程使用公共资源。当条件成立或者超过了指定的等待时间（比如 3 秒），该函数会自动调用 lock() 函数对互斥锁加锁，同时令线程继续执行。 |
3. wait_until() 
   1. 和 wait_for() 功能类似，不同之处在于，wait_until() 函数可以设定一个具体时间点（例如 2021年4月8日 的某个具体时间），当条件成立或者等待时间超过了指定的时间点，函数会自动对互斥锁加锁，同时线程继续执行。     |
4. notify_one() 
   1. 向其中一个正在等待的线程发送“条件成立”的信号。                                                                                                                                                              |
5. notify_all() 
   1. 向所有等待的线程发送“条件成立”的信号。                                                                                                                                                                      |


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


## MemoryBarrier 内存屏障

### 内存屏障MemoryBarrier为什么会产生乱序？

#### 1. 多个线程同时lock

```c++
// thread A
void thread_A() {
    lock(&mtx);
    unlock(&mtx);
}
// thread B
void thread_B() {
    lock(&mtx);    
    unlock(&mtx);
}
```

thread A和thread B同时尝试去hold这个mutex，
得不到锁而发起一次syscall，
把自己的进程从running list挂到blocked list ：意味着：一次特权级切换（由此带来的cache miss、tlb miss），kernel code path开销，原本的cpu时间片也被夺走

通信？
通过一个ready来做通信，set ready后其他线程才可见
ready: 称为data的visible point

编译器优化与乱序?


#### 2. 编译器优化
编译器把自己优化成一个寄存器。也即编译器codegen时，对ready的读写优化后生成的全是对一个寄存器的访问，这样其他人再怎么改你也看不到，因为压根没有访存。
volatile qualifier来强制编译器对ready的访问生成访存代码
volatile bool ready = false

#### 3. 乱序

```c++
Initially (data, ready) = (0, false)

Timeline  -------Thread A--------  ----------Thread B-------
    |       Store ready = true        
    |                                          Load ready = true 
    |                                          Load data = 0
    |       Store data = 0x1234

    // prepare data
    data = 0x1234;
    compiler_barrier();
    ready = true;    

    // load
    ready_value = ready;
    compiler_barrier();
    data_value = data;

compiler_barrier：
```


### 为什么平时写的代码不考虑乱序也没关系？
在代码中考虑memory order从来都不是一件容易的事，尤其是当你开始优化性能，尝试往lockless方面靠的时候，你需要把你的代码放在不同cpu架构下反复测试才能基本断言它是没有bug的。
那平时写代码为什么我们从来没有考虑过乱序问题，程序也依然没有bug呢？我觉得可能有以下原因：
- 你写的单线程代码的乱序由编译器和CPU共同提供基本保证。
- 虽然编译器和CPU本身都存在乱序行为，但它们都会保证基本的数据依赖关系，那些不影响程序正确性的乱序因为没有其他线程观测，是不会产生影响的，这对单线程代码已经足矣。
- 你写的多线程代码中大多使用库中提供的同步原语。比如pthread的pthread_mutex，C++自带的std::mutex，这些同步原语在实现的封装过程中已经把涉及乱序、memory order的部分为你考虑好了，只要你按照它们要求的用法使用，临界区就不会受到各层次乱序的影响。
- 你写的lockless程序只是在某个strong memory order的处理器架构下能够正确运行，在weak memory order的处理器架构下仍然存在bug。
- 如果你的lockless程序只在x86这样strong order处理器架构上验证过，那么它来到诸如arm、risc-v这样weak order架构下可能会暴露许多你之前没意识到的bug。

### 为了解决内存访问的乱序问题以及CPU缓冲数据的不同步问题。

**编译期**
```c++
sum = a + b; 
__COMPILE_MEMORY_BARRIER__; 
sum = sum + c;
```

**运行时**
处理器#2： 可能是乱序执行，f = 1可能先于x = 42执行
```c++
x = 42;
f = 1;
```

处理器#1： 输出的值是0而非42
```c++
    while (f == 0);
    print(x);
```
加入内存屏障, 保证f的值能够读取到其它处理器的最新值, 才会执行print(x)
```c++
    while (f == 0);
    _RUNTIME_MEMORY_BARRIAR_; 
    print(x);
```

#### 1. LoadLoad
```c++
if (IsValid)           // 加载并检测IsValid
{
    LOADLOAD_FENCE();  // LoadLoad屏障防止两个加载之间的重新排序，在加载Value及后续读取操作要读取的数据被访问前，保证IsValid及之前要读取的数据被读取完毕。
    return Value;      // 加载Value
}
```
#### 2. StoreStore
```c++
Value = x;             // 写入Value
STORESTORE_FENCE();    // StoreStore屏障防止两个写入之间的重排序，在IsValid及后续写入操作执行前，保证Value的写入操作对其它处理器可见。
IsValid = 1;           // 写入IsValid
```
#### 3. LoadStore
```c++
if (IsValid)            // 加载并检测IsValid
{
    LOADSTORE_FENCE();  // LoadStore屏障防止加载和写入之间的重排序，在Value及后续写入操作被刷出前，保证IsValid要读取的数据被读取完毕。
    Value = x;          // 写入Value
}
```
#### 4. StoreLoad
```c++
Value = x;          // 写入Value
STORELOAD_FENCE();  // 在IsValid及后续所有读取操作执行前，保证Value的写入对所有处理器可见。
if (IsValid)        // 加载并检测IsValid
{
    return 1;
}
```

--- 
# Dead Lock 

```cpp
// BAD: Lock ordering violation → deadlock
// Thread A: Lock(A) → Lock(B)
// Thread B: Lock(B) → Lock(A)

// GOOD: Always lock in consistent order
// Thread A: Lock(A) → Lock(B)
// Thread B: Lock(A) → Lock(B)
```

## 死锁的四个条件
- 互斥：只能由一个线程独享资源
- 保持: 因请求资源而阻塞时，对已获得的资源保持不释放
- 不能剥夺: 其他 进程/线程 需要等待该资源被释放
- 互相依赖/循环依赖

## 如何解决？
打破死锁产生的条件
银行家算法

