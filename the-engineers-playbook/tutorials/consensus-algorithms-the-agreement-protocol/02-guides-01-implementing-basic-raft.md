# Implementing Basic Raft: Democracy in Action

## What We're Building

We'll implement a simplified version of Raft leader election—the process by which a group of nodes agrees on who should be the leader. This is the foundation of the Raft consensus algorithm.

**Goal**: Build a system where 5 nodes can reliably elect a leader, even when some nodes fail.

## The Raft Leader Election Protocol

### States
Every node can be in one of three states:
- **Follower**: Default state, follows the leader
- **Candidate**: Competing to become leader
- **Leader**: Coordinates the cluster

### The Election Process

```mermaid
flowchart TD
    A[Follower] --> B[Timeout, become Candidate]
    B --> C[Request votes from all nodes]
    C --> D{Majority votes?}
    D -->|Yes| E[Become Leader]
    D -->|No| F[Return to Follower]
    E --> G[Send heartbeats]
    F --> A
    G --> H[Heartbeat timeout?]
    H -->|Yes| A
    H -->|No| G
    
    style A fill:#e3f2fd
    style E fill:#e8f5e8
    style F fill:#ffcdd2
    style G fill:#fff3e0
```

## Detailed Message Flow

```mermaid
sequenceDiagram
    participant A as Node A (Candidate)
    participant B as Node B (Follower)
    participant C as Node C (Follower)
    participant D as Node D (Follower)
    participant E as Node E (Follower)
    
    Note over A,E: Election timeout triggers
    A->>A: Increment term, vote for self
    
    par Vote requests
        A->>B: VoteRequest(term=1, candidateId=A)
        A->>C: VoteRequest(term=1, candidateId=A)
        A->>D: VoteRequest(term=1, candidateId=A)
        A->>E: VoteRequest(term=1, candidateId=A)
    end
    
    par Vote responses
        B->>A: VoteResponse(term=1, granted=true)
        C->>A: VoteResponse(term=1, granted=true)
        D->>A: VoteResponse(term=1, granted=false)
        E->>A: VoteResponse(term=1, granted=true)
    end
    
    Note over A: Received 4/5 votes (including self)
    A->>A: Become leader
    
    par Heartbeats
        A->>B: Heartbeat(term=1, leaderId=A)
        A->>C: Heartbeat(term=1, leaderId=A)
        A->>D: Heartbeat(term=1, leaderId=A)
        A->>E: Heartbeat(term=1, leaderId=A)
    end
```

## Core Data Structures

```go
type Node struct {
    ID          string
    State       NodeState
    CurrentTerm int
    VotedFor    string
    Peers       []string
    
    // Timers
    ElectionTimeout  time.Duration
    HeartbeatTimeout time.Duration
    LastHeartbeat    time.Time
}

type NodeState int
const (
    Follower NodeState = iota
    Candidate
    Leader
)

type VoteRequest struct {
    Term        int
    CandidateID string
}

type VoteResponse struct {
    Term        int
    VoteGranted bool
}
```

## Step-by-Step Implementation

### Step 1: Initialize the Node

```go
func NewNode(id string, peers []string) *Node {
    return &Node{
        ID:               id,
        State:            Follower,
        CurrentTerm:      0,
        VotedFor:         "",
        Peers:            peers,
        ElectionTimeout:  randomTimeout(150, 300), // 150-300ms
        HeartbeatTimeout: 50 * time.Millisecond,
        LastHeartbeat:    time.Now(),
    }
}

func randomTimeout(min, max int) time.Duration {
    return time.Duration(rand.Intn(max-min)+min) * time.Millisecond
}
```

**Why random timeouts?** If all nodes had the same timeout, they'd all start elections simultaneously, creating chaos. Random timeouts ensure elections happen one at a time.

### Step 2: Handle Election Timeout

```go
func (n *Node) checkElectionTimeout() {
    if n.State == Leader {
        return // Leaders don't participate in elections
    }
    
    if time.Since(n.LastHeartbeat) > n.ElectionTimeout {
        n.startElection()
    }
}

func (n *Node) startElection() {
    n.State = Candidate
    n.CurrentTerm++
    n.VotedFor = n.ID
    n.LastHeartbeat = time.Now()
    
    fmt.Printf("Node %s starting election for term %d\n", n.ID, n.CurrentTerm)
    
    // Vote for ourselves
    votes := 1
    
    // Request votes from all peers
    for _, peer := range n.Peers {
        if peer != n.ID {
            if n.requestVote(peer) {
                votes++
            }
        }
    }
    
    // Check if we won
    majority := len(n.Peers)/2 + 1
    if votes >= majority {
        n.becomeLeader()
    } else {
        n.becomeFollower()
    }
}
```

### Step 3: Handle Vote Requests

```go
func (n *Node) handleVoteRequest(req VoteRequest) VoteResponse {
    response := VoteResponse{
        Term:        n.CurrentTerm,
        VoteGranted: false,
    }
    
    // If candidate's term is older, reject
    if req.Term < n.CurrentTerm {
        return response
    }
    
    // If candidate's term is newer, update our term
    if req.Term > n.CurrentTerm {
        n.CurrentTerm = req.Term
        n.VotedFor = ""
        n.becomeFollower()
    }
    
    // Grant vote if we haven't voted or voted for this candidate
    if n.VotedFor == "" || n.VotedFor == req.CandidateID {
        n.VotedFor = req.CandidateID
        n.LastHeartbeat = time.Now()
        response.VoteGranted = true
        response.Term = n.CurrentTerm
        
        fmt.Printf("Node %s granted vote to %s for term %d\n", 
                   n.ID, req.CandidateID, n.CurrentTerm)
    }
    
    return response
}
```

### Step 4: State Transitions

```go
func (n *Node) becomeLeader() {
    n.State = Leader
    fmt.Printf("Node %s became leader for term %d\n", n.ID, n.CurrentTerm)
    
    // Start sending heartbeats
    go n.sendHeartbeats()
}

func (n *Node) becomeFollower() {
    n.State = Follower
    n.ElectionTimeout = randomTimeout(150, 300)
    n.LastHeartbeat = time.Now()
}

func (n *Node) sendHeartbeats() {
    for n.State == Leader {
        for _, peer := range n.Peers {
            if peer != n.ID {
                n.sendHeartbeat(peer)
            }
        }
        time.Sleep(n.HeartbeatTimeout)
    }
}
```

### Step 5: Handle Heartbeats

```go
type HeartbeatRequest struct {
    Term     int
    LeaderID string
}

func (n *Node) handleHeartbeat(req HeartbeatRequest) {
    // If heartbeat is from older term, ignore
    if req.Term < n.CurrentTerm {
        return
    }
    
    // If heartbeat is from newer term, update and become follower
    if req.Term > n.CurrentTerm {
        n.CurrentTerm = req.Term
        n.VotedFor = ""
    }
    
    // Valid heartbeat - reset election timeout
    n.becomeFollower()
    fmt.Printf("Node %s received heartbeat from leader %s (term %d)\n", 
               n.ID, req.LeaderID, req.Term)
}
```

## Running the Election

```go
func main() {
    // Create a 5-node cluster
    nodeIDs := []string{"A", "B", "C", "D", "E"}
    nodes := make([]*Node, len(nodeIDs))
    
    for i, id := range nodeIDs {
        nodes[i] = NewNode(id, nodeIDs)
    }
    
    // Start all nodes
    for _, node := range nodes {
        go node.run()
    }
    
    // Let them run for 5 seconds
    time.Sleep(5 * time.Second)
    
    // Check who's the leader
    for _, node := range nodes {
        if node.State == Leader {
            fmt.Printf("Final leader: %s (term %d)\n", node.ID, node.CurrentTerm)
        }
    }
}

func (n *Node) run() {
    ticker := time.NewTicker(10 * time.Millisecond)
    defer ticker.Stop()
    
    for {
        select {
        case <-ticker.C:
            n.checkElectionTimeout()
        }
    }
}
```

## Key Insights from This Implementation

### 1. **Split Vote Prevention**
Random timeouts ensure that elections happen sequentially, not simultaneously. This prevents split votes where multiple candidates compete.

### 2. **Term Monotonicity**
Terms only increase, never decrease. This ensures that old messages from crashed leaders don't cause confusion.

### 3. **Majority Rule**
A candidate needs votes from a majority of nodes (including itself) to become leader. This ensures at most one leader per term.

### 4. **Heartbeat Suppression**
Regular heartbeats from the leader prevent followers from starting unnecessary elections.

## Testing Failure Scenarios

### Simulate Leader Failure
```go
// Kill the leader after 2 seconds
time.Sleep(2 * time.Second)
for _, node := range nodes {
    if node.State == Leader {
        node.State = Follower // Simulate crash
        fmt.Printf("Leader %s crashed!\n", node.ID)
        break
    }
}
```

### Simulate Network Partition
```go
// Isolate node A from others
nodeA.Peers = []string{"A"} // Only sees itself
```

## Advanced Scenarios

### Network Partition Recovery

```mermaid
sequenceDiagram
    participant A as Node A
    participant B as Node B
    participant C as Node C
    participant D as Node D
    participant E as Node E
    
    Note over A,C: Partition: {A,B} vs {C,D,E}
    
    rect rgb(255, 200, 200)
        Note over A,B: Minority partition
        A->>B: Heartbeat fails
        B->>A: No response
        Note over A,B: Cannot elect leader (no majority)
    end
    
    rect rgb(200, 255, 200)
        Note over C,E: Majority partition
        C->>C: Election timeout
        C->>D: VoteRequest
        C->>E: VoteRequest
        D->>C: VoteResponse(granted=true)
        E->>C: VoteResponse(granted=true)
        Note over C: Becomes leader with 3/5 nodes
    end
    
    Note over A,E: Network heals
    C->>A: Heartbeat(term=2)
    C->>B: Heartbeat(term=2)
    A->>A: Accept C as leader
    B->>B: Accept C as leader
```

### Performance Characteristics

```mermaid
graph TD
    subgraph "Time Complexity"
        A1["Election: O(n) messages"]
        A2["Heartbeat: O(n) messages"]
        A3["Failure detection: O(timeout)"]
    end
    
    subgraph "Space Complexity"
        B1["Per node: O(1) state"]
        B2["Network: O(n²) connections"]
        B3["Messages: O(n) buffer"]
    end
    
    subgraph "Fault Tolerance"
        C1["Crash failures: ⌊n/2⌋"]
        C2["Network partitions: Minority side unavailable"]
        C3["Recovery: Automatic when majority reforms"]
    end
    
    style A1 fill:#e3f2fd
    style B1 fill:#e8f5e8
    style C1 fill:#fff3e0
```

## What We've Accomplished

This basic implementation demonstrates:
- ✅ **Leader election** with majority voting
- ✅ **Failure detection** via heartbeat timeouts
- ✅ **Term-based ordering** to prevent confusion
- ✅ **Split vote prevention** via random timeouts

## System Behavior Analysis

### Normal Operation Timeline

```mermaid
gantt
    title Raft Leader Election Timeline
    dateFormat X
    axisFormat %Ls
    
    section Node A
    Follower    :a1, 0, 150
    Candidate   :a2, 150, 200
    Leader      :a3, 200, 1000
    
    section Node B
    Follower    :b1, 0, 1000
    
    section Node C
    Follower    :c1, 0, 1000
    
    section Node D
    Follower    :d1, 0, 1000
    
    section Node E
    Follower    :e1, 0, 1000
```

### Split Vote Scenario

```mermaid
sequenceDiagram
    participant A as Node A
    participant B as Node B
    participant C as Node C
    participant D as Node D
    participant E as Node E
    
    Note over A,E: Both A and B timeout simultaneously
    
    par Competing elections
        A->>A: Start election (term=1)
        B->>B: Start election (term=1)
    end
    
    par Vote requests
        A->>C: VoteRequest(term=1)
        A->>D: VoteRequest(term=1)
        B->>C: VoteRequest(term=1)
        B->>E: VoteRequest(term=1)
    end
    
    Note over C: Receives both requests, votes for first
    C->>A: VoteResponse(granted=true)
    C->>B: VoteResponse(granted=false)
    
    Note over A,B: Neither gets majority
    A->>A: Election timeout, retry
    B->>B: Election timeout, retry
    
    Note over A,E: Random timeouts prevent infinite loops
```

## Next Steps

This is just leader election. A full Raft implementation would also include:
- **Log replication**: Distributing commands to followers
- **Safety guarantees**: Ensuring committed entries are never lost
- **Membership changes**: Adding/removing nodes safely
- **Log compaction**: Cleaning up old entries

But you now understand the democratic foundation that makes it all possible!