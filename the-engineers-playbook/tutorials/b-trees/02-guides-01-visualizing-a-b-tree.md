# Visualizing a B-Tree: Building Understanding Through Practice

## Introduction: Learning Through Construction

The best way to understand B-Trees is to build one step by step, watching how the structure evolves as we insert keys. This guide will walk you through constructing a B-Tree from scratch, showing how nodes split, the tree grows, and balance is maintained.

We'll use a B-Tree of order 5 (maximum 4 keys per node) for clarity, but the principles apply to any order.

## Starting Simple: The Empty Tree

### Initial State

Let's start with an empty B-Tree of order 5:

```
Empty B-Tree (order 5):
- Maximum keys per node: 4
- Minimum keys per node: 2 (except root)
- Maximum children per node: 5
- Minimum children per node: 3 (except root)

Tree structure:
(empty)
```

### B-Tree Properties to Remember

As we build our tree, we'll maintain these invariants:
1. All leaf nodes are at the same level
2. Keys within nodes are sorted
3. For internal nodes: if key K is in position i, then:
   - All keys in child[i] are < K
   - All keys in child[i+1] are ≥ K

## First Insertions: Building the Root

### Insert 10

```
Insert: 10

Tree after insertion:
┌─────┐
│ 10  │ (root, leaf)
└─────┘

Explanation:
- Tree was empty, so 10 becomes the root
- Root is also a leaf (no children)
- Node has 1 key (within limits: 1-4 keys allowed)
```

### Insert 20

```
Insert: 20

Tree after insertion:
┌─────────┐
│ 10, 20  │ (root, leaf)
└─────────┘

Explanation:
- 20 > 10, so it goes to the right
- Node now has 2 keys (within limits)
- Still a single leaf node
```

### Insert 30

```
Insert: 30

Tree after insertion:
┌─────────────┐
│ 10, 20, 30  │ (root, leaf)
└─────────────┘

Explanation:
- 30 > 20, so it goes to the right
- Node now has 3 keys (within limits)
- Still a single leaf node
```

### Insert 40

```
Insert: 40

Tree after insertion:
┌─────────────────┐
│ 10, 20, 30, 40  │ (root, leaf)
└─────────────────┘

Explanation:
- 40 > 30, so it goes to the right
- Node now has 4 keys (at maximum capacity)
- Still a single leaf node
- Next insertion will cause a split!
```

## First Split: Creating the Tree Structure

### Insert 50 (Triggers Split)

```
Insert: 50

Before split:
┌─────────────────┐
│ 10, 20, 30, 40  │ (full node)
└─────────────────┘

Split process:
1. Node is full (4 keys), need to split
2. Choose middle key: 30 (position 2 in 0-indexed array)
3. Create two new nodes:
   - Left: keys < 30
   - Right: keys ≥ 30
4. Promote middle key to parent (create new root)

After split:
         ┌─────┐
         │ 30  │ (root, internal)
         └─────┘
        /       \
┌─────────┐   ┌─────────────┐
│ 10, 20  │   │ 40, 50     │ (leaves)
└─────────┘   └─────────────┘

Explanation:
- Tree height increased from 1 to 2
- Root is now an internal node with 1 key
- Two leaf nodes, each with 2 keys
- All leaves are at the same level
```

## Growing the Tree: More Insertions

### Insert 60

```
Insert: 60

Search process:
1. Start at root: key 30
2. 60 > 30, go right
3. Arrive at leaf [40, 50]
4. Insert 60 in sorted order

Tree after insertion:
         ┌─────┐
         │ 30  │
         └─────┘
        /       \
┌─────────┐   ┌─────────────┐
│ 10, 20  │   │ 40, 50, 60  │
└─────────┘   └─────────────┘

Explanation:
- Right leaf now has 3 keys (within limits)
- No split needed
- Tree structure unchanged
```

### Insert 70

```
Insert: 70

Tree after insertion:
         ┌─────┐
         │ 30  │
         └─────┘
        /       \
┌─────────┐   ┌─────────────────┐
│ 10, 20  │   │ 40, 50, 60, 70  │
└─────────┘   └─────────────────┘

Explanation:
- Right leaf now has 4 keys (at maximum capacity)
- No split needed yet
- Next insertion to right side will cause split
```

### Insert 80 (Triggers Second Split)

```
Insert: 80

Before split:
Right leaf is full: [40, 50, 60, 70]
Need to insert 80

Split process:
1. Leaf [40, 50, 60, 70] is full
2. Choose middle key: 60 (position 2)
3. Create two new leaf nodes:
   - Left: [40, 50]
   - Right: [70, 80]
4. Promote 60 to parent (root)

After split:
         ┌─────────┐
         │ 30, 60  │ (root, internal)
         └─────────┘
        /    |    \
┌─────────┐ ┌─────────┐ ┌─────────┐
│ 10, 20  │ │ 40, 50  │ │ 70, 80  │ (leaves)
└─────────┘ └─────────┘ └─────────┘

Explanation:
- Root now has 2 keys: 30, 60
- Tree has 3 leaf nodes
- All leaves still at same level
- Tree height remains 2
```

## Complex Insertion: Multiple Levels

### Insert 15

```
Insert: 15

Search process:
1. Start at root: keys [30, 60]
2. 15 < 30, go left
3. Arrive at leaf [10, 20]
4. Insert 15 in sorted order

Tree after insertion:
         ┌─────────┐
         │ 30, 60  │
         └─────────┘
        /    |    \
┌─────────────┐ ┌─────────┐ ┌─────────┐
│ 10, 15, 20  │ │ 40, 50  │ │ 70, 80  │
└─────────────┘ └─────────┘ └─────────┘

Explanation:
- Left leaf now has 3 keys
- No split needed
- Tree structure unchanged
```

### Insert 25

```
Insert: 25

Tree after insertion:
         ┌─────────┐
         │ 30, 60  │
         └─────────┘
        /    |    \
┌─────────────────┐ ┌─────────┐ ┌─────────┐
│ 10, 15, 20, 25  │ │ 40, 50  │ │ 70, 80  │
└─────────────────┘ └─────────┘ └─────────┘

Explanation:
- Left leaf now has 4 keys (at maximum)
- No split needed yet
- Next insertion to left side will cause split
```

### Insert 12 (Triggers Third Split)

```
Insert: 12

Before split:
Left leaf is full: [10, 15, 20, 25]
Need to insert 12

Split process:
1. Leaf [10, 15, 20, 25] is full
2. Choose middle key: 15 (position 2)
3. Create two new leaf nodes:
   - Left: [10, 12]
   - Right: [20, 25]
4. Promote 15 to parent (root)

After split:
         ┌─────────────┐
         │ 15, 30, 60  │ (root, internal)
         └─────────────┘
        /    |    |    \
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ 10, 12  │ │ 20, 25  │ │ 40, 50  │ │ 70, 80  │
└─────────┘ └─────────┘ └─────────┘ └─────────┘

Explanation:
- Root now has 3 keys: 15, 30, 60
- Tree has 4 leaf nodes
- All leaves still at same level
- Tree height remains 2
```

## Root Split: Increasing Tree Height

### Insert 35

```
Insert: 35

Search process:
1. Start at root: keys [15, 30, 60]
2. 35 > 30 and 35 < 60, go to middle-right child
3. Arrive at leaf [40, 50]
4. Insert 35 in sorted order

Tree after insertion:
         ┌─────────────┐
         │ 15, 30, 60  │
         └─────────────┘
        /    |    |    \
┌─────────┐ ┌─────────┐ ┌─────────────┐ ┌─────────┐
│ 10, 12  │ │ 20, 25  │ │ 35, 40, 50  │ │ 70, 80  │
└─────────┘ └─────────┘ └─────────────┘ └─────────┘

Explanation:
- Middle-right leaf now has 3 keys
- No split needed
- Tree structure unchanged
```

### Insert 45

```
Insert: 45

Tree after insertion:
         ┌─────────────┐
         │ 15, 30, 60  │
         └─────────────┘
        /    |    |    \
┌─────────┐ ┌─────────┐ ┌─────────────────┐ ┌─────────┐
│ 10, 12  │ │ 20, 25  │ │ 35, 40, 45, 50  │ │ 70, 80  │
└─────────┘ └─────────┘ └─────────────────┘ └─────────┘

Explanation:
- Middle-right leaf now has 4 keys (at maximum)
- No split needed yet
- Root also has 3 keys
```

### Insert 55 (Triggers Root Split)

```
Insert: 55

Before split:
1. Middle-right leaf [35, 40, 45, 50] is full
2. Need to insert 55
3. This will cause leaf split
4. Root [15, 30, 60] also has 3 keys
5. Promoting middle key will make root full (4 keys)

Step 1 - Leaf split:
Middle-right leaf [35, 40, 45, 50] splits:
- Left: [35, 40]
- Right: [50, 55]
- Promote: 45

Step 2 - Root would become:
[15, 30, 45, 60] (4 keys - at maximum)

Since root is at maximum capacity, it must split too!

Root split:
1. Root [15, 30, 45, 60] is full
2. Choose middle key: 45 (position 2)
3. Create two new internal nodes:
   - Left: [15, 30]
   - Right: [60]
4. Promote 45 to new root

Final tree after both splits:
              ┌─────┐
              │ 45  │ (new root, internal)
              └─────┘
             /       \
    ┌─────────┐     ┌─────┐
    │ 15, 30  │     │ 60  │ (internal nodes)
    └─────────┘     └─────┘
   /    |    \      /     \
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ 10, 12  │ │ 20, 25  │ │ 35, 40  │ │ 50, 55  │ │ 70, 80  │
└─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘

Explanation:
- Tree height increased from 2 to 3
- New root has 1 key: 45
- Two internal nodes at level 2
- Five leaf nodes at level 3
- All leaves still at same level
```

## Visualization Summary

Let's trace through the complete evolution:

### Evolution Timeline

```
Step 1: Insert 10
┌─────┐
│ 10  │
└─────┘

Step 2: Insert 20
┌─────────┐
│ 10, 20  │
└─────────┘

Step 3: Insert 30
┌─────────────┐
│ 10, 20, 30  │
└─────────────┘

Step 4: Insert 40
┌─────────────────┐
│ 10, 20, 30, 40  │
└─────────────────┘

Step 5: Insert 50 (first split)
         ┌─────┐
         │ 30  │
         └─────┘
        /       \
┌─────────┐   ┌─────────┐
│ 10, 20  │   │ 40, 50  │
└─────────┘   └─────────┘

Step 6-7: Insert 60, 70
         ┌─────┐
         │ 30  │
         └─────┘
        /       \
┌─────────┐   ┌─────────────────┐
│ 10, 20  │   │ 40, 50, 60, 70  │
└─────────┘   └─────────────────┘

Step 8: Insert 80 (second split)
         ┌─────────┐
         │ 30, 60  │
         └─────────┘
        /    |    \
┌─────────┐ ┌─────────┐ ┌─────────┐
│ 10, 20  │ │ 40, 50  │ │ 70, 80  │
└─────────┘ └─────────┘ └─────────┘

Step 9-11: Insert 15, 25, 12 (third split)
         ┌─────────────┐
         │ 15, 30, 60  │
         └─────────────┘
        /    |    |    \
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ 10, 12  │ │ 20, 25  │ │ 40, 50  │ │ 70, 80  │
└─────────┘ └─────────┘ └─────────┘ └─────────┘

Step 12-13: Insert 35, 45
         ┌─────────────┐
         │ 15, 30, 60  │
         └─────────────┘
        /    |    |    \
┌─────────┐ ┌─────────┐ ┌─────────────────┐ ┌─────────┐
│ 10, 12  │ │ 20, 25  │ │ 35, 40, 45, 50  │ │ 70, 80  │
└─────────┘ └─────────┘ └─────────────────┘ └─────────┘

Step 14: Insert 55 (root split - height increases)
              ┌─────┐
              │ 45  │
              └─────┘
             /       \
    ┌─────────┐     ┌─────┐
    │ 15, 30  │     │ 60  │
    └─────────┘     └─────┘
   /    |    \      /     \
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ 10, 12  │ │ 20, 25  │ │ 35, 40  │ │ 50, 55  │ │ 70, 80  │
└─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

## Key Observations

### Split Patterns

1. **When to split**: When a node exceeds its maximum capacity
2. **How to split**: 
   - Choose middle key
   - Create two new nodes
   - Promote middle key to parent
3. **Propagation**: Splits can cascade up the tree
4. **Balance**: All leaves remain at the same level

### Search Efficiency

```
Tree height vs number of keys (order 5):
- Height 1: 1-4 keys
- Height 2: 5-24 keys  
- Height 3: 25-124 keys
- Height 4: 125-624 keys

Our final tree:
- Height: 3
- Keys: 14
- Disk reads needed: 3
```

### Space Utilization

```
Node utilization in our final tree:
- Root: 1/4 keys = 25%
- Internal nodes: 2/4 and 1/4 keys = 50% and 25%
- Leaf nodes: 2/4 keys each = 50%
- Overall: 14/20 = 70%

Guaranteed minimum: 50% (except root)
```

## Interactive Exercises

### Exercise 1: Continue the Tree

What happens if we insert 5 into our final tree?

```
Current tree:
              ┌─────┐
              │ 45  │
              └─────┘
             /       \
    ┌─────────┐     ┌─────┐
    │ 15, 30  │     │ 60  │
    └─────────┘     └─────┘
   /    |    \      /     \
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ 10, 12  │ │ 20, 25  │ │ 35, 40  │ │ 50, 55  │ │ 70, 80  │
└─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘

Insert 5:
1. 5 < 45, go left
2. 5 < 15, go left
3. Arrive at leaf [10, 12]
4. Insert 5: [5, 10, 12]
5. Node not full, no split needed
```

### Exercise 2: Range Query

How would you find all keys between 30 and 50?

```
Range query [30, 50]:
1. Find starting position for 30
2. Traverse leaf nodes left to right
3. Collect keys until we exceed 50

Path:
1. Start at root: 45
2. 30 < 45, go left
3. At node [15, 30]: 30 ≥ 30, go right
4. At leaf [35, 40]: start here
5. Collect: 35, 40
6. Move to next leaf: [50, 55]
7. Collect: 50
8. Stop (55 > 50)

Result: [35, 40, 50]
```

## Advanced Visualization Techniques

### Node Fill Visualization

```
Node capacity visualization:
Empty: [    ]
25%:   [■   ]
50%:   [■■  ]
75%:   [■■■ ]
Full:  [■■■■]

Our tree:
              [■   ]  Root: 25%
             /       \
    [■■  ]           [■   ]  Internal: 50%, 25%
   /    \           /     \
[■■  ] [■■  ] [■■  ] [■■  ] [■■  ]  Leaves: all 50%
```

### Access Pattern Visualization

```
Search for key 55:
Path: Root(45) → Right(60) → Left(50,55) → Found

Disk reads: 3
┌─────┐ Read 1: Root node
│ 45  │
└─────┘
    ↓
┌─────┐ Read 2: Internal node
│ 60  │
└─────┘
    ↓
┌─────────┐ Read 3: Leaf node
│ 50, 55  │
└─────────┘
```

## Practical Applications

### Database Index

```
Table: employees
Index on: salary (B-Tree)

Salaries: 30K, 35K, 40K, 45K, 50K, 55K, 60K, 70K, 80K

Query: SELECT * FROM employees WHERE salary = 55000
Process: B-Tree search → 3 disk reads → Found
```

### File System

```
Directory structure (B-Tree):
- Files sorted by name
- Fast lookups by filename
- Efficient directory listings
- Support for large directories
```

### Memory Management

```
Virtual memory page tables:
- Virtual addresses as keys
- Physical addresses as values
- Fast address translation
- Efficient memory allocation
```

## Summary

Through this step-by-step visualization, we've seen how:

1. **B-Trees start simple** and grow organically
2. **Splits maintain balance** by keeping all leaves at the same level
3. **Tree height grows slowly** due to high node capacity
4. **Search efficiency** comes from minimizing tree height
5. **Space utilization** is guaranteed to be at least 50%

The key insight is that B-Trees automatically balance themselves through the split process, ensuring that the tree remains short and wide, which minimizes disk I/O operations.

Understanding this visual process is crucial for grasping why B-Trees are so effective for disk-based storage systems. The next step is to dive deeper into the theoretical foundations and compare B-Trees with other tree structures to understand their unique advantages.