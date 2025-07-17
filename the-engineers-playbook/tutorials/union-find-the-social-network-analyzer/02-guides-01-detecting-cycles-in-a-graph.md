# Detecting Cycles in a Graph: A Union-Find Approach

One of the most elegant applications of Union-Find is cycle detection in undirected graphs. This guide demonstrates how to use Union-Find to determine if adding an edge would create a cycle—a fundamental operation in algorithms like Kruskal's Minimum Spanning Tree.

## The Cycle Detection Problem

**Problem**: Given an undirected graph and a new edge, determine if adding this edge would create a cycle.

**Traditional Approach**: Use DFS or BFS to search for a path between the edge's endpoints
- Time complexity: O(V + E) per edge check
- Space complexity: O(V) for visited tracking

**Union-Find Approach**: Check if both endpoints are already connected
- Time complexity: O(α(V)) per edge check (nearly constant)
- Space complexity: O(V) for the Union-Find structure

## The Key Insight

**Cycle Formation Rule**: Adding an edge (u, v) creates a cycle if and only if u and v are already connected through some path in the existing graph.

**Union-Find Translation**: Two nodes are connected if they have the same representative. Therefore:
- If `find(u) == find(v)`: Adding edge (u, v) creates a cycle
- If `find(u) != find(v)`: Adding edge (u, v) is safe

## Algorithm Walkthrough

### Step-by-Step Process

```mermaid
graph LR
    subgraph "Step 1: Initialize"
        A1[1] 
        B1[2]
        C1[3]
        D1[4]
    end
    
    subgraph "Step 2: Add Edge (1,2)"
        A2[1] --- B2[2]
        C2[3]
        D2[4]
    end
    
    subgraph "Step 3: Add Edge (2,3)"
        A3[1] --- B3[2] --- C3[3]
        D3[4]
    end
    
    subgraph "Step 4: Check Edge (1,3)"
        A4[1] --- B4[2] --- C4[3]
        A4 -.-> C4
        D4[4]
        style A4 fill:#ff9999
        style C4 fill:#ff9999
    end
```

1. **Initialize**: Each node is its own component
2. **Process edges safely**: Add edges that don't create cycles
3. **Detect cycle**: Reject edges between already-connected nodes

### Detailed Example

Let's trace through a concrete example:

**Graph Setup**:
- Nodes: {1, 2, 3, 4, 5}
- Edges to process: [(1,2), (2,3), (3,4), (1,3), (4,5), (2,5)]

```mermaid
graph TD
    subgraph "Union-Find State Evolution"
        subgraph "Initial State"
            S1[Component 1: {1}]
            S2[Component 2: {2}]
            S3[Component 3: {3}]
            S4[Component 4: {4}]
            S5[Component 5: {5}]
        end
        
        subgraph "After Edge (1,2)"
            T1[Component 1: {1,2}]
            T3[Component 2: {3}]
            T4[Component 3: {4}]
            T5[Component 4: {5}]
        end
        
        subgraph "After Edge (2,3)"
            U1[Component 1: {1,2,3}]
            U4[Component 2: {4}]
            U5[Component 3: {5}]
        end
        
        subgraph "Edge (1,3) - CYCLE!"
            V1[Component 1: {1,2,3}]
            V4[Component 2: {4}]
            V5[Component 3: {5}]
            CYCLE[❌ 1 and 3 already connected!]
            
            style CYCLE fill:#ffebee
        end
    end
```

**Processing Each Edge**:

```python
# Initialize Union-Find
uf = UnionFind(5)  # Nodes 1-5
edges = [(1,2), (2,3), (3,4), (1,3), (4,5), (2,5)]

for u, v in edges:
    if uf.find(u) == uf.find(v):
        print(f"CYCLE DETECTED: Adding edge ({u},{v}) would create a cycle")
    else:
        print(f"SAFE: Adding edge ({u},{v})")
        uf.union(u, v)
```

**Execution Trace**:

```
Edge (1,2): find(1)=1, find(2)=2 → Different → SAFE, union(1,2)
Components: {1,2}, {3}, {4}, {5}

Edge (2,3): find(2)=1, find(3)=3 → Different → SAFE, union(2,3)  
Components: {1,2,3}, {4}, {5}

Edge (3,4): find(3)=1, find(4)=4 → Different → SAFE, union(3,4)
Components: {1,2,3,4}, {5}

Edge (1,3): find(1)=1, find(3)=1 → Same → CYCLE DETECTED!
Components: {1,2,3,4}, {5} (unchanged)

Edge (4,5): find(4)=1, find(5)=5 → Different → SAFE, union(4,5)
Components: {1,2,3,4,5}

Edge (2,5): find(2)=1, find(5)=1 → Same → CYCLE DETECTED!
Components: {1,2,3,4,5} (unchanged)
```

## Complete Implementation

### Basic Cycle Detection

```python
class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n
    
    def find(self, x):
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # Path compression
        return self.parent[x]
    
    def union(self, x, y):
        root_x, root_y = self.find(x), self.find(y)
        if root_x == root_y:
            return False  # Already connected - would create cycle
        
        # Union by rank
        if self.rank[root_x] < self.rank[root_y]:
            self.parent[root_x] = root_y
        elif self.rank[root_x] > self.rank[root_y]:
            self.parent[root_y] = root_x
        else:
            self.parent[root_y] = root_x
            self.rank[root_x] += 1
        return True

def has_cycle(edges, num_nodes):
    """
    Detect if the given edges form a cycle in an undirected graph.
    
    Args:
        edges: List of (u, v) tuples representing edges
        num_nodes: Total number of nodes in the graph
    
    Returns:
        True if any cycle is detected, False otherwise
    """
    uf = UnionFind(num_nodes)
    
    for u, v in edges:
        if not uf.union(u, v):
            return True  # Cycle detected
    
    return False

# Example usage
edges = [(0, 1), (1, 2), (2, 3), (0, 2)]  # This forms a cycle
print(has_cycle(edges, 4))  # Output: True

edges_safe = [(0, 1), (1, 2), (2, 3)]  # This is a tree (no cycle)
print(has_cycle(edges_safe, 4))  # Output: False
```

### Interactive Cycle Detection

```python
def detect_cycles_incrementally(edges, num_nodes):
    """
    Process edges one by one and report cycles as they're detected.
    """
    uf = UnionFind(num_nodes)
    safe_edges = []
    cycle_edges = []
    
    for u, v in edges:
        if uf.find(u) == uf.find(v):
            cycle_edges.append((u, v))
            print(f"⚠️  Edge ({u},{v}) would create a cycle - REJECTED")
        else:
            uf.union(u, v)
            safe_edges.append((u, v))
            print(f"✅ Edge ({u},{v}) added safely")
    
    return safe_edges, cycle_edges

# Demo with a more complex graph
edges = [(0,1), (1,2), (2,3), (3,4), (4,1), (2,5), (5,3), (0,4)]
safe, cycles = detect_cycles_incrementally(edges, 6)

print(f"\nSafe edges: {safe}")
print(f"Cycle-causing edges: {cycles}")
```

## Real-World Applications

### Minimum Spanning Tree (Kruskal's Algorithm)

Cycle detection is the core of Kruskal's MST algorithm:

```python
def kruskal_mst(edges, num_nodes):
    """
    Find Minimum Spanning Tree using Kruskal's algorithm.
    Cycle detection ensures we don't add redundant edges.
    """
    # Sort edges by weight
    edges.sort(key=lambda x: x[2])  # (u, v, weight)
    
    uf = UnionFind(num_nodes)
    mst_edges = []
    total_weight = 0
    
    for u, v, weight in edges:
        if uf.find(u) != uf.find(v):  # No cycle
            uf.union(u, v)
            mst_edges.append((u, v, weight))
            total_weight += weight
            
            if len(mst_edges) == num_nodes - 1:
                break  # MST complete
    
    return mst_edges, total_weight

# Example: Finding MST of a weighted graph
edges = [
    (0, 1, 4), (0, 2, 2), (1, 2, 1), 
    (1, 3, 5), (2, 3, 8), (2, 4, 10),
    (3, 4, 2)
]

mst, weight = kruskal_mst(edges, 5)
print(f"MST edges: {mst}")
print(f"Total weight: {weight}")
```

### Network Reliability Analysis

```python
def find_critical_edges(edges, num_nodes):
    """
    Find edges whose removal would disconnect the graph.
    """
    critical_edges = []
    
    for i, target_edge in enumerate(edges):
        # Try building graph without this edge
        other_edges = edges[:i] + edges[i+1:]
        
        if not is_connected(other_edges, num_nodes):
            critical_edges.append(target_edge)
    
    return critical_edges

def is_connected(edges, num_nodes):
    """Check if graph is connected using Union-Find."""
    uf = UnionFind(num_nodes)
    
    for u, v in edges:
        uf.union(u, v)
    
    # All nodes should have the same representative
    root = uf.find(0)
    return all(uf.find(i) == root for i in range(num_nodes))
```

## Performance Analysis

### Time Complexity Comparison

| Algorithm | Single Query | All Edges |
|-----------|--------------|-----------|
| DFS/BFS   | O(V + E)     | O(E × (V + E)) |
| Union-Find| O(α(V))      | O(E × α(V)) |

### Space Complexity

| Algorithm | Space Usage |
|-----------|-------------|
| DFS/BFS   | O(V) per query |
| Union-Find| O(V) total |

### Practical Performance

For a graph with 10,000 nodes and 50,000 edges:
- **DFS approach**: ~500ms per edge check
- **Union-Find approach**: ~0.001ms per edge check

## When to Use Union-Find for Cycle Detection

**Ideal Scenarios**:
✅ Processing many edges incrementally  
✅ Need to detect cycles during graph construction  
✅ Building minimum spanning trees  
✅ Network reliability analysis  

**Consider Alternatives When**:
❌ Need to find the actual cycle path  
❌ Working with directed graphs (Union-Find is for undirected)  
❌ Need to detect specific types of cycles (e.g., odd-length cycles)  
❌ Graph structure changes frequently with edge removals  

## Key Takeaways

1. **Elegance**: Union-Find reduces cycle detection to a simple connectivity check
2. **Efficiency**: Near-constant time per operation makes it ideal for incremental processing
3. **Simplicity**: Algorithm is straightforward to implement and debug
4. **Versatility**: Forms the foundation for many graph algorithms (MST, connected components)

The Union-Find approach to cycle detection demonstrates the power of choosing the right data structure—transforming an expensive graph traversal problem into an efficient set membership question.