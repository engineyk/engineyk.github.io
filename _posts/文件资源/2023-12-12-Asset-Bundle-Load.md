---
layout:     post
title:      Unity Bundle 加载
subtitle:   Bundle的加载
date:       2023-12-12
author:     engineyk
header-img: img/post-bg-ocenwar.jpg
catalog: true
tags:
    - 资产管理
---


# Unity AssetBundle加载

---

## 目录

- [1. 概述](#1-概述)
- [2. AssetBundle 文件结构](#2-assetbundle-文件结构)
- [3. 为什么 LoadFromStream 需要多次 IO](#3-为什么-loadfromstream-需要多次-io)
- [4. FileStream 可以用同一个吗](#4-filestream-可以用同一个吗)
- [5. Stream 的生命周期要求](#5-stream-的生命周期要求)
- [6. 多个 AssetBundle 共享 FileStream 的问题](#6-多个-assetbundle-共享-filestream-的问题)
- [7. 加密流场景下的 IO 分析](#7-加密流场景下的-io-分析)
- [8. 最佳实践与代码示例](#8-最佳实践与代码示例)
- [9. 性能优化建议](#9-性能优化建议)
- [10. 常见问题 FAQ](#10-常见问题-faq)
- [11. 总结](#11-总结)

---

## 1. 概述

`AssetBundle.LoadFromStream` 是 Unity 提供的从 `System.IO.Stream` 加载 AssetBundle 的 API。与 `LoadFromFile` 和 `LoadFromMemory` 不同，它允许开发者自定义数据源（加密流、压缩流、网络流等）。

```csharp
// API Signature
public static AssetBundle LoadFromStream(
    Stream stream,
    uint crc = 0,
    uint managedReadBufferSize = 4096
);

public static AssetBundleCreateRequest LoadFromStreamAsync(
    Stream stream,
    uint crc = 0,
    uint managedReadBufferSize = 4096
);
```

**核心特点**：
- Stream 必须支持 `Read`、`Seek`（即 `CanRead == true` && `CanSeek == true`）
- Stream 在 AssetBundle 整个生命周期内必须保持打开
- Unity 会在加载过程中对 Stream 进行**多次、非连续的 IO 操作**

---

## 2. AssetBundle 文件结构

AssetBundle 并非简单的连续二进制块，而是一个**分层结构**的文件格式：

```
┌─────────────────────────────────────────────┐
│                  Header                     │  ← 第 1 次 IO: 读取头部
│  - Signature ("UnityFS")                    │
│  - Format Version                           │
│  - Unity Version                            │
│  - Generator Version                        │
│  - File Size                                │
│  - Compressed Block Size                    │
│  - Uncompressed Block Size                  │
│  - Flags                                    │
├─────────────────────────────────────────────┤
│              Block Info                     │  ← 第 2 次 IO: 读取块信息
│  - Block Count                              │
│  - Per-Block: compressed size,              │
│    uncompressed size, flags                 │
├─────────────────────────────────────────────┤
│           Directory Info                    │  ← 第 3 次 IO: 读取资源目录
│  - Entry Count                              │
│  - Per-Entry: offset, size, flags, name     │
├─────────────────────────────────────────────┤
│                                             │
│            Data Blocks                      │  ← 第 4~N 次 IO: 按需读取资源
│  - Block 0: [compressed data]               │
│  - Block 1: [compressed data]               │
│  - Block 2: [compressed data]               │
│  - ...                                      │
│                                             │
└─────────────────────────────────────────────┘
```

---

## 3. 为什么 LoadFromStream 需要多次 IO

### 3.1 分阶段读取

Unity 不会一次性将整个 AssetBundle 读入内存，而是分阶段按需读取：

```
时间线 ──────────────────────────────────────────────────────►

[Seek(0)]     [Seek(headerEnd)]    [Seek(dirEnd)]     [Seek(block_N_offset)]
    │               │                    │                    │
    ▼               ▼                    ▼                    ▼
 ┌──────┐      ┌──────────┐        ┌───────────┐       ┌──────────┐
 │Header│      │Block Info│        │ Directory │       │Data Block│
 │ Read │      │  Read    │        │   Read    │       │  Read    │
 └──────┘      └──────────┘        └───────────┘       └──────────┘
   IO #1          IO #2               IO #3             IO #4~N
```

| 阶段        | 操作                             | 目的                                          |
| ----------- | -------------------------------- | --------------------------------------------- |
| **阶段 1**  | `Seek(0)` + `Read`               | 读取 Header，获取文件基本信息和后续数据偏移量 |
| **阶段 2**  | `Seek(blockInfoOffset)` + `Read` | 读取 Block Info，了解数据块的压缩方式和大小   |
| **阶段 3**  | `Seek(directoryOffset)` + `Read` | 读取 Directory，建立资源名称到数据块的映射    |
| **阶段 4+** | `Seek(dataOffset)` + `Read`      | 按需加载具体资源的数据块                      |

### 3.2 为什么不一次性读完

```
一次性读取 (LoadFromMemory):
  ✅ 简单
  ❌ 内存占用 = 整个 AB 文件大小
  ❌ 加载延迟 = 读取整个文件的时间

按需读取 (LoadFromStream):
  ✅ 内存占用低（只加载需要的部分）
  ✅ 首次加载快（只需读 Header + 目录）
  ✅ 支持流式加载
  ❌ 需要 Stream 保持打开
  ❌ 需要 Stream 支持 Seek
```

### 3.3 具体 IO 调用追踪

通过自定义 Stream 包装器，可以观察到 Unity 的实际 IO 行为：

```csharp
public class DebugStream : Stream
{
    private Stream _inner;
    private int _readCount = 0;
    private int _seekCount = 0;

    public DebugStream(Stream inner) => _inner = inner;

    public override int Read(byte[] buffer, int offset, int count)
    {
        _readCount++;
        Debug.Log($"[IO #{_readCount}] Read({count} bytes) at position {_inner.Position}");
        return _inner.Read(buffer, offset, count);
    }

    public override long Seek(long offset, SeekOrigin origin)
    {
        _seekCount++;
        Debug.Log($"[Seek #{_seekCount}] Seek({offset}, {origin})");
        return _inner.Seek(offset, origin);
    }

    // ... delegate other members to _inner
    public override bool CanRead => _inner.CanRead;
    public override bool CanSeek => _inner.CanSeek;
    public override bool CanWrite => _inner.CanWrite;
    public override long Length => _inner.Length;
    public override long Position
    {
        get => _inner.Position;
        set => _inner.Position = value;
    }
    public override void Flush() => _inner.Flush();
    public override void SetLength(long value) => _inner.SetLength(value);
    public override void Write(byte[] buffer, int offset, int count)
        => _inner.Write(buffer, offset, count);
}
```

**典型输出**：
```
[Seek #1] Seek(0, Begin)
[IO #1]   Read(4096 bytes) at position 0          // Header
[Seek #2] Seek(62, Begin)
[IO #2]   Read(4096 bytes) at position 62         // Block Info
[Seek #3] Seek(178, Begin)
[IO #3]   Read(4096 bytes) at position 178        // Directory
[Seek #4] Seek(1024, Begin)
[IO #4]   Read(4096 bytes) at position 1024       // Data Block 0
[Seek #5] Seek(5120, Begin)
[IO #5]   Read(4096 bytes) at position 5120       // Data Block 1
...
```

---

## 4. FileStream 可以用同一个吗

### 4.1 同一个 AB 文件：可以，但没必要

对于**同一个 AssetBundle 文件**，`LoadFromStream` 本身就只需要一个 FileStream：

```csharp
// ✅ 正确：一个 FileStream 对应一个 AssetBundle
FileStream fs = new FileStream("bundle.ab", FileMode.Open, FileAccess.Read);
AssetBundle ab = AssetBundle.LoadFromStream(fs);
// fs 必须保持打开，直到 ab.Unload() 之后才能关闭
```

### 4.2 多个 AB 文件共享一个 FileStream：❌ 不可以

```csharp
// ❌ 错误：多个 AB 不能共享同一个 FileStream
FileStream fs = new FileStream("bundle_a.ab", FileMode.Open, FileAccess.Read);
AssetBundle ab1 = AssetBundle.LoadFromStream(fs);

// fs 的 Position 已被 ab1 改变，且 ab1 随时可能再次 Seek/Read
// 此时无法用同一个 fs 去加载另一个文件
```

### 4.3 合并包场景：一个文件多个 AB

如果你将多个 AssetBundle 合并到一个大文件中，理论上可以用**同一个物理文件**，但需要为每个 AB 创建**独立的 Stream 视图**：

```csharp
// Scenario: Multiple ABs packed into one file
// [AB_A: offset=0, size=10000] [AB_B: offset=10000, size=20000]

// ❌ Wrong: sharing one FileStream
FileStream fs = new FileStream("combined.pak", FileMode.Open);
var ab1 = AssetBundle.LoadFromStream(fs);  // ab1 takes control of fs
var ab2 = AssetBundle.LoadFromStream(fs);  // CONFLICT! ab1 still using fs

// ✅ Correct: separate FileStream per AB
FileStream fs1 = new FileStream("combined.pak", FileMode.Open, FileAccess.Read, FileShare.Read);
FileStream fs2 = new FileStream("combined.pak", FileMode.Open, FileAccess.Read, FileShare.Read);
var ab1 = AssetBundle.LoadFromStream(new OffsetStream(fs1, 0, 10000));
var ab2 = AssetBundle.LoadFromStream(new OffsetStream(fs2, 10000, 20000));
```

### 4.4 为什么不能共享：Position 冲突

```bash
FileStream 内部状态:
┌───────────────────────────┐
│  Position (读写指针位置)   │  ← 全局唯一，所有操作共享
│  Length                   │
│  Handle (OS文件句柄)       │
└───────────────────────────┘

AB_A 读取:  Seek(100) → Read(...)  → Position = 4196
AB_B 读取:  Seek(0)   → Read(...)  → Position = 4096
AB_A 再读:  Seek(4196)→ 但 Position 已被 AB_B 改为 4096 !!!

结果: 数据错乱 → 加载失败或崩溃
```

### 4.5 结论表

| 场景                    | 能否共享 FileStream | 原因                        |
| ----------------------- | :-----------------: | --------------------------- |
| 同一个 AB 的多次 Load   |          ❌          | 同一个 AB 不能重复加载      |
| 不同 AB 文件            |          ❌          | Position 冲突，数据错乱     |
| 合并包中的不同 AB       |     ❌ 直接共享      | 需要独立的 Stream 实例      |
| 合并包 + OffsetStream   | ✅ 独立 Stream 包装  | 每个 AB 有独立的 Position   |
| 同一文件多个 FileStream |          ✅          | FileShare.Read 允许多个句柄 |

---

## 5. Stream 的生命周期要求

### 5.1 生命周期规则

```
Stream 创建 ──► LoadFromStream() ──► 使用 AB 资源 ──► AB.Unload() ──► Stream.Close()
     │                                                      │              │
     │◄──────────── Stream 必须保持打开 ──────────────────────►│              │
     │                                                                      │
     │◄──────────── 关闭 Stream 必须在 Unload 之后 ────────────────────────►│
```

### 5.2 正确的生命周期管理

```csharp
public class AssetBundleHandle : IDisposable
{
    private FileStream _stream;
    private AssetBundle _bundle;
    private bool _disposed = false;

    public AssetBundle Bundle => _bundle;

    public static AssetBundleHandle Load(string path)
    {
        var handle = new AssetBundleHandle();
        handle._stream = new FileStream(
            path, FileMode.Open, FileAccess.Read, FileShare.Read
        );
        handle._bundle = AssetBundle.LoadFromStream(handle._stream);
        return handle;
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;

        // Order matters: Unload first, then close stream
        if (_bundle != null)
        {
            _bundle.Unload(true);
            _bundle = null;
        }

        if (_stream != null)
        {
            _stream.Close();
            _stream.Dispose();
            _stream = null;
        }
    }
}

// Usage
using (var handle = AssetBundleHandle.Load("path/to/bundle.ab"))
{
    var prefab = handle.Bundle.LoadAsset<GameObject>("MyPrefab");
    Instantiate(prefab);
} // auto Unload + Close
```

### 5.3 常见错误

```csharp
// ❌ Error 1: Closing stream too early
FileStream fs = new FileStream("bundle.ab", FileMode.Open);
AssetBundle ab = AssetBundle.LoadFromStream(fs);
fs.Close();  // WRONG! AB still needs the stream
ab.LoadAsset<GameObject>("Prefab");  // CRASH or corrupted data

// ❌ Error 2: Using 'using' block incorrectly
AssetBundle ab;
using (FileStream fs = new FileStream("bundle.ab", FileMode.Open))
{
    ab = AssetBundle.LoadFromStream(fs);
}  // fs closed here, but ab still needs it!
ab.LoadAsset<GameObject>("Prefab");  // CRASH

// ❌ Error 3: Forgetting to close stream after unload
FileStream fs = new FileStream("bundle.ab", FileMode.Open);
AssetBundle ab = AssetBundle.LoadFromStream(fs);
ab.Unload(true);
// fs is never closed → file handle leak!
```

---

## 6. 多个 AssetBundle 共享 FileStream 的问题

### 6.1 问题根源：Stream 不是线程安全的

```csharp
// FileStream is NOT thread-safe
// Even in single-threaded context, Position is shared state

public class FileStream
{
    private long _position;  // ← shared mutable state

    public override int Read(byte[] buffer, int offset, int count)
    {
        // reads from _position
        // advances _position by bytes read
    }

    public override long Seek(long offset, SeekOrigin origin)
    {
        // modifies _position
    }
}
```

### 6.2 解决方案：OffsetStream（子流）

当多个 AB 打包在同一个文件中时，使用 OffsetStream 为每个 AB 提供独立的视图：

```csharp
/// <summary>
/// Provides an independent seekable view over a portion of a file.
/// Each instance maintains its own Position, safe for concurrent AB loading.
/// </summary>
public class OffsetStream : Stream
{
    private readonly string _filePath;
    private readonly FileStream _stream;
    private readonly long _offset;
    private readonly long _length;
    private long _position;

    public OffsetStream(string filePath, long offset, long length)
    {
        _filePath = filePath;
        _offset = offset;
        _length = length;
        _position = 0;

        // Each OffsetStream owns its own FileStream handle
        _stream = new FileStream(
            filePath, FileMode.Open, FileAccess.Read, FileShare.Read
        );
    }

    public override bool CanRead => true;
    public override bool CanSeek => true;
    public override bool CanWrite => false;
    public override long Length => _length;

    public override long Position
    {
        get => _position;
        set
        {
            if (value < 0 || value > _length)
                throw new ArgumentOutOfRangeException();
            _position = value;
        }
    }

    public override int Read(byte[] buffer, int offset, int count)
    {
        long remaining = _length - _position;
        if (remaining <= 0) return 0;
        if (count > remaining) count = (int)remaining;

        _stream.Seek(_offset + _position, SeekOrigin.Begin);
        int bytesRead = _stream.Read(buffer, offset, count);
        _position += bytesRead;
        return bytesRead;
    }

    public override long Seek(long offset, SeekOrigin origin)
    {
        long newPos = origin switch
        {
            SeekOrigin.Begin   => offset,
            SeekOrigin.Current => _position + offset,
            SeekOrigin.End     => _length + offset,
            _ => throw new ArgumentException()
        };

        if (newPos < 0 || newPos > _length)
            throw new ArgumentOutOfRangeException();

        _position = newPos;
        return _position;
    }

    public override void Flush() { }
    public override void SetLength(long value)
        => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count)
        => throw new NotSupportedException();

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _stream?.Dispose();
        }
        base.Dispose(disposing);
    }
}
```

### 6.3 合并包加载示例

```csharp
/// <summary>
/// Pack file format:
/// [4 bytes: entry count]
/// [entries: name(256 bytes) + offset(8 bytes) + size(8 bytes)] * N
/// [AB data blocks...]
/// </summary>
public class PackFileLoader : IDisposable
{
    private Dictionary<string, (long offset, long size)> _entries;
    private List<OffsetStream> _streams = new List<OffsetStream>();
    private Dictionary<string, AssetBundle> _bundles = new Dictionary<string, AssetBundle>();
    private string _packPath;

    public void LoadPackFile(string packPath)
    {
        _packPath = packPath;
        _entries = new Dictionary<string, (long, long)>();

        using var reader = new BinaryReader(
            new FileStream(packPath, FileMode.Open, FileAccess.Read)
        );

        int count = reader.ReadInt32();
        for (int i = 0; i < count; i++)
        {
            byte[] nameBytes = reader.ReadBytes(256);
            string name = System.Text.Encoding.UTF8.GetString(nameBytes).TrimEnd('\0');
            long offset = reader.ReadInt64();
            long size = reader.ReadInt64();
            _entries[name] = (offset, size);
        }
    }

    public AssetBundle LoadBundle(string bundleName)
    {
        if (_bundles.TryGetValue(bundleName, out var existing))
            return existing;

        if (!_entries.TryGetValue(bundleName, out var entry))
            throw new FileNotFoundException($"Bundle '{bundleName}' not found in pack");

        // Each AB gets its own independent stream
        var stream = new OffsetStream(_packPath, entry.offset, entry.size);
        _streams.Add(stream);

        var bundle = AssetBundle.LoadFromStream(stream);
        _bundles[bundleName] = bundle;
        return bundle;
    }

    public void Dispose()
    {
        foreach (var kvp in _bundles)
            kvp.Value?.Unload(true);
        _bundles.Clear();

        foreach (var stream in _streams)
            stream?.Dispose();
        _streams.Clear();
    }
}
```

---

## 7. 加密流场景下的 IO 分析

### 7.1 为什么加密场景更需要理解多次 IO

加密流是 `LoadFromStream` 最常见的使用场景。由于 Unity 会多次 Seek + Read，加密/解密逻辑必须正确处理随机访问：

```
常见加密方式与 Seek 兼容性:

┌─────────────────┬──────────┬────────────────────────────┐
│   加密方式       │ 支持Seek │ 说明                        │
├─────────────────┼──────────┼────────────────────────────┤
│ XOR             │ ✅       │ 逐字节异或，天然支持随机访问 │
│ AES-ECB         │ ✅       │ 块独立加密，可随机访问块     │
│ AES-CBC         │ ⚠️       │ 需要从块边界开始解密        │
│ AES-CTR         │ ✅       │ 计数器模式，天然支持随机访问 │
│ ChaCha20        │ ✅       │ 流密码，支持任意位置解密     │
│ 仅头部加密       │ ✅       │ 只加密前 N 字节，简单高效    │
└─────────────────┴──────────┴────────────────────────────┘
```

### 7.2 XOR 加密流示例

```csharp
public class XorEncryptStream : Stream
{
    private readonly Stream _baseStream;
    private readonly byte[] _key;

    public XorEncryptStream(Stream baseStream, byte[] key)
    {
        _baseStream = baseStream;
        _key = key;
    }

    public override int Read(byte[] buffer, int offset, int count)
    {
        long posBeforeRead = _baseStream.Position;
        int bytesRead = _baseStream.Read(buffer, offset, count);

        // XOR decryption: position-based key rotation
        for (int i = 0; i < bytesRead; i++)
        {
            long absolutePos = posBeforeRead + i;
            buffer[offset + i] ^= _key[absolutePos % _key.Length];
        }

        return bytesRead;
    }

    public override long Seek(long offset, SeekOrigin origin)
        => _baseStream.Seek(offset, origin);

    // Delegate properties
    public override bool CanRead => true;
    public override bool CanSeek => _baseStream.CanSeek;
    public override bool CanWrite => false;
    public override long Length => _baseStream.Length;
    public override long Position
    {
        get => _baseStream.Position;
        set => _baseStream.Position = value;
    }
    public override void Flush() => _baseStream.Flush();
    public override void SetLength(long value)
        => throw new NotSupportedException();
    public override void Write(byte[] buffer, int offset, int count)
        => throw new NotSupportedException();

    protected override void Dispose(bool disposing)
    {
        if (disposing) _baseStream?.Dispose();
        base.Dispose(disposing);
    }
}

// Usage
var key = System.Text.Encoding.UTF8.GetBytes("MySecretKey12345");
var fileStream = new FileStream("encrypted.ab", FileMode.Open, FileAccess.Read);
var decryptStream = new XorEncryptStream(fileStream, key);
var bundle = AssetBundle.LoadFromStream(decryptStream);
```

---

## 8. 最佳实践与代码示例

### 8.1 完整的生产级 AssetBundle 管理器

```csharp
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

public class StreamBundleManager : MonoBehaviour, IDisposable
{
    private static StreamBundleManager _instance;
    public static StreamBundleManager Instance => _instance;

    // Track all loaded bundles and their streams
    private readonly Dictionary<string, BundleEntry> _loadedBundles
        = new Dictionary<string, BundleEntry>();

    private class BundleEntry
    {
        public Stream Stream;
        public AssetBundle Bundle;
        public int RefCount;
    }

    private void Awake()
    {
        _instance = this;
        DontDestroyOnLoad(gameObject);
    }

    /// <summary>
    /// Load an AssetBundle from file with optional encryption.
    /// Each call creates an independent FileStream.
    /// </summary>
    public AssetBundle LoadBundle(string bundlePath, byte[] encryptionKey = null)
    {
        // Return cached bundle if already loaded
        if (_loadedBundles.TryGetValue(bundlePath, out var entry))
        {
            entry.RefCount++;
            return entry.Bundle;
        }

        // Create independent FileStream for this bundle
        Stream stream = new FileStream(
            bundlePath,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            bufferSize: 4096  // match Unity's default managedReadBufferSize
        );

        // Wrap with decryption if key provided
        if (encryptionKey != null && encryptionKey.Length > 0)
        {
            stream = new XorEncryptStream(stream, encryptionKey);
        }

        // Load AssetBundle from stream
        AssetBundle bundle = AssetBundle.LoadFromStream(stream);

        if (bundle == null)
        {
            stream.Dispose();
            Debug.LogError($"Failed to load AssetBundle: {bundlePath}");
            return null;
        }

        _loadedBundles[bundlePath] = new BundleEntry
        {
            Stream = stream,
            Bundle = bundle,
            RefCount = 1
        };

        return bundle;
    }

    /// <summary>
    /// Unload a bundle. Stream is closed when ref count reaches 0.
    /// </summary>
    public void UnloadBundle(string bundlePath, bool unloadAllLoadedObjects = false)
    {
        if (!_loadedBundles.TryGetValue(bundlePath, out var entry))
            return;

        entry.RefCount--;

        if (entry.RefCount <= 0)
        {
            // Order: Unload bundle first, then close stream
            entry.Bundle.Unload(unloadAllLoadedObjects);
            entry.Stream.Dispose();
            _loadedBundles.Remove(bundlePath);
        }
    }

    public void Dispose()
    {
        foreach (var kvp in _loadedBundles)
        {
            kvp.Value.Bundle?.Unload(true);
            kvp.Value.Stream?.Dispose();
        }
        _loadedBundles.Clear();
    }

    private void OnDestroy() => Dispose();
}
```

### 8.2 使用示例

```csharp
public class GameLoader : MonoBehaviour
{
    private void Start()
    {
        // Simple load
        var bundle = StreamBundleManager.Instance.LoadBundle(
            Application.streamingAssetsPath + "/characters.ab"
        );

        // Load with encryption
        byte[] key = System.Text.Encoding.UTF8.GetBytes("GameSecret2026!!");
        var encBundle = StreamBundleManager.Instance.LoadBundle(
            Application.streamingAssetsPath + "/levels.ab",
            key
        );

        // Use assets
        var prefab = bundle.LoadAsset<GameObject>("Hero");
        Instantiate(prefab);
    }

    private void OnDestroy()
    {
        StreamBundleManager.Instance.UnloadBundle(
            Application.streamingAssetsPath + "/characters.ab", true
        );
    }
}
```

---

## 9. 性能优化建议

### 9.1 Buffer Size 调优

```csharp
// managedReadBufferSize parameter affects IO granularity
// Default: 4096 bytes

// Small bundles (< 1MB): use default
AssetBundle.LoadFromStream(stream, 0, 4096);

// Large bundles (> 10MB): increase buffer for fewer IO calls
AssetBundle.LoadFromStream(stream, 0, 65536);

// Very large bundles (> 100MB): even larger buffer
AssetBundle.LoadFromStream(stream, 0, 131072);
```

| Bundle Size | Recommended Buffer | IO Count Reduction |
| ----------- | ------------------ | ------------------ |
| < 1 MB      | 4096 (default)     | baseline           |
| 1-10 MB     | 16384              | ~60% fewer reads   |
| 10-100 MB   | 65536              | ~80% fewer reads   |
| > 100 MB    | 131072             | ~90% fewer reads   |

### 9.2 LoadFromStream vs LoadFromFile vs LoadFromMemory

性能对比 (相对值, 越低越好):

| Mode           | 加载速度 | 内存占用 | 灵活性 | 适用场景           |
| -------------- | -------- | -------- | ------ | ------------------ |
| LoadFromFile   | ★☆☆☆☆    | ★☆☆☆☆    | ★★★★★  | 无加密，本地文件   |
| LoadFromStream | ★★★☆☆    | ★★☆☆☆    | ★★☆☆☆  | 加密，合并包       |
| LoadFromMemory | ★★★★★    | ★★★★★    | ★☆☆☆☆  | 小文件，已在内存中 |

```

 ★ 越多表示开销越大

 推荐优先级:
 1. LoadFromFile     — 无加密需求时首选
 2. LoadFromStream   — 需要加密或自定义数据源时使用
 3. LoadFromMemory   — 尽量避免（双倍内存占用）
```

### 9.3 异步加载

```csharp
public async void LoadBundleAsync(string path)
{
    var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
    var request = AssetBundle.LoadFromStreamAsync(stream);

    // Wait for completion without blocking main thread
    while (!request.isDone)
    {
        // Progress: request.progress (0.0 ~ 1.0)
        await System.Threading.Tasks.Task.Yield();
    }

    AssetBundle bundle = request.assetBundle;
    if (bundle != null)
    {
        Debug.Log($"Bundle loaded: {bundle.name}");
    }
}
```

---

## 10. 常见问题 FAQ

### Q1: LoadFromStream 报错 "Stream does not support seeking"

**原因**：传入的 Stream 的 `CanSeek` 返回 `false`。  
**解决**：确保 Stream 支持随机访问。如果是网络流或 GZipStream，需要先读入 MemoryStream：

```csharp
// Convert non-seekable stream to seekable
var memStream = new MemoryStream();
nonSeekableStream.CopyTo(memStream);
memStream.Position = 0;
var bundle = AssetBundle.LoadFromStream(memStream);
```

### Q2: 加载后资源损坏或崩溃

**常见原因**：
1. Stream 被提前关闭
2. 加密流的 Seek 实现有 bug
3. 多个 AB 共享了同一个 Stream 实例
4. OffsetStream 的偏移量计算错误

### Q3: 为什么 LoadFromFile 不需要保持文件打开？

`LoadFromFile` 由 Unity 原生层直接管理文件句柄，使用内存映射文件（mmap）技术，不经过 C# 的 Stream 层。Unity 内部自行管理文件的打开和关闭。

### Q4: LoadFromStream 是否线程安全？

`LoadFromStream` 本身必须在主线程调用。但 Unity 内部可能在工作线程中对 Stream 进行 Read/Seek 操作（尤其是异步加载时），因此：
- 不要在其他线程操作同一个 Stream
- 不要在 AB 加载期间修改 Stream 的 Position

### Q5: 移动平台上的注意事项

```
Android:
  - StreamingAssets 在 APK 内，不能直接用 FileStream
  - 需要先用 UnityWebRequest 或 Java API 提取到可写目录
  - 或使用 splitApplication + OBB 文件

iOS:
  - StreamingAssets 可直接用 FileStream 访问
  - 注意 App Thinning 可能影响文件路径

WebGL:
  - 不支持 FileStream
  - 不支持 LoadFromStream
  - 只能用 LoadFromMemory 或 UnityWebRequestAssetBundle
```

---

## 11. 总结

### 核心要点

```
┌─────────────────────────────────────────────────────────────────┐
│                    关键结论                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. LoadFromStream 需要多次 IO 是因为 AB 文件是分层结构，        │
│     Unity 按需读取 Header → BlockInfo → Directory → Data        │
│                                                                 │
│  2. 每个 AssetBundle 必须有自己独立的 Stream 实例                │
│     不能多个 AB 共享同一个 FileStream（Position 冲突）           │
│                                                                 │
│  3. 同一个物理文件可以打开多个 FileStream（FileShare.Read）      │
│     但每个 AB 需要独立的 Stream 视图                             │
│                                                                 │
│  4. Stream 必须在 AB 整个生命周期内保持打开                      │
│     关闭顺序: AB.Unload() → Stream.Close()                     │
│                                                                 │
│  5. 加密流必须正确实现 Seek，推荐使用 XOR 或 AES-CTR            │
│                                                                 │
│  6. 无加密需求时优先使用 LoadFromFile（性能最优）                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 方案选择流程图

```
需要加载 AssetBundle?
    │
    ├── 无加密/无自定义需求 ──► LoadFromFile (最优)
    │
    ├── 需要加密 ──► LoadFromStream + 加密 Stream
    │       │
    │       ├── 简单加密 ──► XOR Stream
    │       └── 高安全性 ──► AES-CTR Stream
    │
    ├── 合并包 ──► LoadFromStream + OffsetStream
    │       │
    │       └── 每个 AB 独立的 OffsetStream 实例
    │
    └── 数据已在内存中 ──► LoadFromMemory (避免使用)
```

---

> **参考资料**：
> - [Unity Documentation - AssetBundle.LoadFromStream](https://docs.unity3d.com/ScriptReference/AssetBundle.LoadFromStream.html)
> - [Unity Documentation - AssetBundle Fundamentals](https://learn.unity.com/tutorial/assets-resources-and-assetbundles)
> - Unity Source Reference: `Runtime/VirtualFileSystem/ArchiveStorageReader.cpp`