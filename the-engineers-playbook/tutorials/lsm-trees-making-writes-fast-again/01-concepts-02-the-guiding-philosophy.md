# The Guiding Philosophy: Sequential Writes and Immutable Data

## The Core Principle: Never Modify, Only Append

LSM Trees are built on a simple but powerful philosophy: **never modify data in place**. Instead, always write new data sequentially and clean up later.

This principle drives every design decision in LSM Trees:
- New writes go to memory first
- Memory structures flush to immutable files on disk  
- Background processes merge and organize these files
- Old data is eventually garbage collected

## The Three-Layer Architecture

```mermaid
flowchart TD
    subgraph "Layer 1: MemTable (Memory)"
        MT["🧠 MemTable<br/>• Fast writes<br/>• Sorted in memory<br/>• Volatile"]
    end
    
    subgraph "Layer 2: SSTables (Disk)"
        SST1["💾 SSTable-001<br/>• Immutable<br/>• Sorted<br/>• Persistent"]
        SST2["💾 SSTable-002<br/>• Immutable<br/>• Sorted<br/>• Persistent"]
        SST3["💾 SSTable-003<br/>• Immutable<br/>• Sorted<br/>• Persistent"]
    end
    
    subgraph "Layer 3: Compaction (Background)"
        COMP["🔄 Compaction<br/>• Merges SSTables<br/>• Reclaims space<br/>• Maintains performance"]
    end
    
    MT -->|"Flush when full"| SST1
    SST1 --> COMP
    SST2 --> COMP
    SST3 --> COMP
    COMP -->|"Creates new"| SST4["💾 SSTable-004<br/>Merged & Optimized"]
    
    style MT fill:#FFB6C1
    style SST1 fill:#87CEEB
    style SST2 fill:#87CEEB
    style SST3 fill:#87CEEB
    style SST4 fill:#90EE90
    style COMP fill:#FFD700
```

### Layer 1: MemTable (Write Buffer)
- **Purpose**: Accept all incoming writes at memory speed
- **Structure**: Usually a balanced tree (Red-Black, AVL) or skip list
- **Characteristics**: Mutable, sorted, lost on crash (unless replicated)

### Layer 2: SSTables (Sorted String Tables)
- **Purpose**: Immutable, sorted storage files on disk
- **Structure**: Sorted key-value pairs with optional indexes
- **Characteristics**: Immutable after creation, mergeable

### Layer 3: Compaction Process
- **Purpose**: Background reorganization and garbage collection
- **Operation**: Merges multiple SSTables into fewer, larger ones
- **Benefit**: Maintains read performance and reclaims space

## The Write Path: Fast and Sequential

```mermaid
sequenceDiagram
    participant Client
    participant MemTable
    participant WAL
    participant SSTable
    participant Background
    
    Client->>WAL: 1. Write to log (durability)
    Client->>MemTable: 2. Store in memory (fast)
    MemTable-->>Client: 3. Ack write (immediate)
    
    Note over MemTable: MemTable grows...
    
    MemTable->>SSTable: 4. Flush when full (sequential)
    Background->>SSTable: 5. Compact in background
    
    Note over Client,Background: Client never waits for disk I/O!
```

**The magic**: Every disk write is sequential, maximizing throughput.

## The Read Path: Multiple Sources

```mermaid
flowchart TD
    A[Read Request] --> B[Check MemTable]
    B --> C{Found?}
    C -->|Yes| D[Return Value]
    C -->|No| E[Check SSTable-N]
    E --> F{Found?}
    F -->|Yes| D
    F -->|No| G[Check SSTable-N-1]
    G --> H{Found?}
    H -->|Yes| D
    H -->|No| I[Check Older SSTables...]
    I --> J[Return Not Found]
    
    style B fill:#FFB6C1
    style E fill:#87CEEB
    style G fill:#87CEEB
    style D fill:#90EE90
    style J fill:#FFA07A
```

**Read principle**: Check newest data first, work backwards in time.
Reads may touch multiple files but writes never block.

## Immutability: The Secret Sauce

Making SSTables immutable provides several benefits:

### 1. Concurrent Access Without Locks
```
Reader: "I'll read SSTable-001.db"
Writer: "I'll write SSTable-002.db"  
Compactor: "I'll merge SSTable-003.db and SSTable-004.db into SSTable-005.db"
```
No coordination needed—each process works on different files.

### 2. Crash Safety
```
Power failure during compaction:
- Original SSTables remain intact
- Partially written file is discarded
- System recovers cleanly
```

### 3. Simple Backup and Replication
```
Backup: Copy all SSTable files (they never change)
Replication: Ship SSTable files to replicas
Verification: Checksums detect corruption
```

## Memory vs. Disk Trade-offs

LSM Trees make explicit trade-offs between memory and disk efficiency:

### Write-Optimized Design
- **Pro**: All writes are sequential (fast)
- **Pro**: Write latency is predictable
- **Con**: Reads may need to check multiple files

### Memory Usage
- **MemTable**: Uses RAM for write buffering
- **Block cache**: Caches frequently accessed SSTable blocks
- **Bloom filters**: Reduce unnecessary SSTable reads

## The Compaction Strategy

Different compaction strategies optimize for different use cases:

### Size-Tiered Compaction
```mermaid
flowchart TD
    subgraph "Level 0"
        A1[1MB] 
        A2[1MB]
        A3[1MB]
        A4[1MB]
    end
    
    subgraph "Level 1"
        B1[4MB]
        B2[4MB]
    end
    
    subgraph "Level 2"
        C1[16MB]
    end
    
    A1 --> B1
    A2 --> B1
    A3 --> B2
    A4 --> B2
    B1 --> C1
    B2 --> C1
    
    style A1 fill:#FFB6C1
    style A2 fill:#FFB6C1
    style A3 fill:#FFB6C1
    style A4 fill:#FFB6C1
    style B1 fill:#87CEEB
    style B2 fill:#87CEEB
    style C1 fill:#90EE90
```
Merge files of similar size. **Best for write-heavy workloads**.

### Leveled Compaction  
```mermaid
flowchart TD
    subgraph "Level 0 (Overlapping)"
        L0A["Keys: 1,5,9"]
        L0B["Keys: 3,7,11"]
    end
    
    subgraph "Level 1 (Non-overlapping)"
        L1A["Keys: 1-10"]
        L1B["Keys: 11-20"]
        L1C["Keys: 21-30"]
    end
    
    subgraph "Level 2 (Non-overlapping)"
        L2A["Keys: 1-100"]
        L2B["Keys: 101-200"]
    end
    
    L0A --> L1A
    L0B --> L1B
    L1A --> L2A
    L1B --> L2A
    L1C --> L2B
    
    style L0A fill:#FFB6C1
    style L0B fill:#FFB6C1
    style L1A fill:#87CEEB
    style L1B fill:#87CEEB
    style L1C fill:#87CEEB
    style L2A fill:#90EE90
    style L2B fill:#90EE90
```
Maintain sorted levels with no overlap. **Better for read-heavy workloads**.

## Handling Deletes: Tombstones

Since files are immutable, deletions use **tombstone** markers:

```
SSTable-001: key="user:123" value="Alice"
SSTable-002: key="user:123" value=TOMBSTONE
```

During reads, the tombstone "shadows" the original value. Compaction eventually removes both the tombstone and original value.

## Write Amplification by Design

LSM Trees intentionally accept write amplification to optimize write latency:

```mermaid
flowchart LR
    A["User writes 1KB"] --> B["MemTable: 1KB"]
    B --> C["Flush: 1KB to disk"]
    C --> D["Compaction 1: +2KB"]
    D --> E["Compaction 2: +1KB"]
    E --> F["Total: 5KB written"]
    
    style A fill:#FFB6C1
    style F fill:#FFA07A
    style C fill:#90EE90
    style D fill:#FFD700
    style E fill:#FFD700
```

**The amplification equation**: `Write Amplification = Total Bytes Written / User Bytes Written`

In this example: `5KB / 1KB = 5x amplification`

The trade-off: **lower write latency** in exchange for **higher background I/O**.

## Real-World Analogy: The Restaurant Kitchen

Think of LSM Trees like a busy restaurant kitchen:

### Traditional Database (B-Tree Kitchen)
- **Order comes in**: Chef immediately finds the right pan, cooks the dish completely
- **Problem**: Only one dish can be prepared at a time
- **Result**: Orders back up during rush hour

### LSM Tree Kitchen
- **Order comes in**: Prep cook adds ingredients to staging area (MemTable)
- **Staging full**: Dump everything onto cooking surfaces (SSTable flush)
- **Background**: Line cooks organize and combine dishes (compaction)
- **Result**: Orders processed continuously, organization happens in parallel

The key insight: **separate the fast path (accepting orders) from the slow path (organization)**.

## Memory and Durability

LSM Trees handle the classic memory vs. durability trade-off:

### Write-Ahead Log (WAL)
```mermaid
sequenceDiagram
    participant Client
    participant WAL
    participant MemTable
    participant Disk
    
    Client->>WAL: 1. Append entry (sequential, durable)
    WAL->>Disk: fsync() - force to disk
    Client->>MemTable: 2. Store in memory (fast)
    MemTable-->>Client: 3. Acknowledge write
    
    Note over Client,Disk: Write is now durable!
    
    rect rgb(255, 200, 200)
        Note over WAL,MemTable: System Crash! 💥
    end
    
    WAL->>MemTable: Recovery: Replay WAL
    Note over MemTable: MemTable reconstructed
```

**Crash recovery process**:
1. Replay WAL to reconstruct MemTable
2. Resume normal operation
3. Continue from where we left off

This provides both **speed** (memory writes) and **durability** (WAL on disk).

## The Philosophy in Action

LSM Trees embody a simple philosophy: **optimize for the common case**. 

```mermaid
pie title Modern Application I/O Patterns
    "Writes (High Volume)" : 70
    "Point Reads" : 20
    "Range Scans" : 10
```

In modern applications:
- **Writes**: High volume, require low latency (logs, metrics, events)
- **Reads**: Important but can tolerate slightly higher latency
- **Storage**: Sequential I/O is 100x faster than random I/O

```mermaid
flowchart LR
    subgraph "Traditional DB Design"
        A1["Optimize for reads"] --> B1["Random writes"]
        B1 --> C1["Poor write performance"]
    end
    
    subgraph "LSM Tree Design"
        A2["Optimize for writes"] --> B2["Sequential writes"]
        B2 --> C2["Excellent write performance"]
        C2 --> D2["Accept read complexity"]
    end
    
    style C1 fill:#FF6347
    style C2 fill:#90EE90
    style D2 fill:#FFD700
```

By designing for write-heavy workloads and accepting read complexity, LSM Trees enable applications that were impossible with traditional storage engines.

The next section examines the key abstractions that make this philosophy concrete.