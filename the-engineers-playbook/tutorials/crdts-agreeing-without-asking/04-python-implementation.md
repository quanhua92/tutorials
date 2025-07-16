# Complete CRDT Implementation in Python

## Overview

This implementation provides a production-ready foundation for building CRDT-based distributed systems. We'll implement multiple CRDT types with proper abstractions, network simulation, and comprehensive testing.

## Prerequisites

- Python 3.7 or higher
- Basic understanding of CRDT concepts
- Familiarity with distributed systems

## Core CRDT Framework

### Base CRDT Interface

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, TypeVar, Generic
import json
import time
import uuid
from dataclasses import dataclass, field
from collections import defaultdict

T = TypeVar('T')

class CRDT(ABC, Generic[T]):
    """
    Abstract base class for all CRDT implementations.
    
    Defines the core interface that all CRDTs must implement to ensure
    mathematical properties are maintained.
    """
    
    def __init__(self, node_id: str):
        """
        Initialize CRDT with node identifier.
        
        Args:
            node_id: Unique identifier for this node
        """
        self.node_id = node_id
        self.created_at = time.time()
    
    @abstractmethod
    def merge(self, other: 'CRDT') -> 'CRDT':
        """
        Merge this CRDT with another CRDT of the same type.
        
        Must satisfy:
        - Commutativity: merge(a, b) = merge(b, a)
        - Associativity: merge(merge(a, b), c) = merge(a, merge(b, c))
        - Idempotence: merge(a, a) = a
        
        Args:
            other: Another CRDT to merge with
            
        Returns:
            New CRDT with merged state
        """
        pass
    
    @abstractmethod
    def value(self) -> T:
        """
        Get the current logical value of this CRDT.
        
        Returns:
            The logical value represented by this CRDT
        """
        pass
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize CRDT to dictionary for network transmission.
        
        Returns:
            Dictionary representation of CRDT state
        """
        pass
    
    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CRDT':
        """
        Deserialize CRDT from dictionary.
        
        Args:
            data: Dictionary representation of CRDT state
            
        Returns:
            Reconstructed CRDT instance
        """
        pass
    
    def clone(self) -> 'CRDT':
        """Create a deep copy of this CRDT."""
        return self.from_dict(self.to_dict())

@dataclass
class VectorClock:
    """
    Vector clock implementation for tracking causality.
    
    Essential for many CRDT implementations to determine the relative
    ordering of events across different nodes.
    """
    
    clocks: Dict[str, int] = field(default_factory=dict)
    
    def increment(self, node_id: str) -> 'VectorClock':
        """Increment the clock for a specific node."""
        result = VectorClock(self.clocks.copy())
        result.clocks[node_id] = result.clocks.get(node_id, 0) + 1
        return result
    
    def merge(self, other: 'VectorClock') -> 'VectorClock':
        """Merge with another vector clock by taking element-wise maximum."""
        result = VectorClock()
        all_nodes = set(self.clocks.keys()) | set(other.clocks.keys())
        
        for node in all_nodes:
            my_clock = self.clocks.get(node, 0)
            other_clock = other.clocks.get(node, 0)
            result.clocks[node] = max(my_clock, other_clock)
        
        return result
    
    def compare(self, other: 'VectorClock') -> str:
        """
        Compare this vector clock with another.
        
        Returns:
            'before': This clock happens before other
            'after': This clock happens after other
            'concurrent': Clocks are concurrent (neither before nor after)
            'equal': Clocks are identical
        """
        if self.clocks == other.clocks:
            return 'equal'
        
        self_before_other = all(
            self.clocks.get(node, 0) <= other.clocks.get(node, 0)
            for node in set(self.clocks.keys()) | set(other.clocks.keys())
        )
        
        other_before_self = all(
            other.clocks.get(node, 0) <= self.clocks.get(node, 0)
            for node in set(self.clocks.keys()) | set(other.clocks.keys())
        )
        
        if self_before_other and not other_before_self:
            return 'before'
        elif other_before_self and not self_before_other:
            return 'after'
        else:
            return 'concurrent'
```

## G-Counter: Grow-Only Counter

```python
class GCounter(CRDT[int]):
    """
    Grow-only Counter CRDT.
    
    Supports increment operations only. The value is the sum of all
    per-node counters. Merge operation takes element-wise maximum.
    """
    
    def __init__(self, node_id: str):
        super().__init__(node_id)
        self.counters: Dict[str, int] = defaultdict(int)
    
    def increment(self, amount: int = 1) -> 'GCounter':
        """
        Increment this node's counter.
        
        Args:
            amount: Amount to increment (must be positive)
            
        Returns:
            Self for method chaining
        """
        if amount <= 0:
            raise ValueError("GCounter only supports positive increments")
        
        self.counters[self.node_id] += amount
        return self
    
    def merge(self, other: 'GCounter') -> 'GCounter':
        """Merge by taking element-wise maximum of counters."""
        result = GCounter(self.node_id)
        all_nodes = set(self.counters.keys()) | set(other.counters.keys())
        
        for node in all_nodes:
            my_count = self.counters.get(node, 0)
            other_count = other.counters.get(node, 0)
            result.counters[node] = max(my_count, other_count)
        
        return result
    
    def value(self) -> int:
        """Get current counter value (sum of all node counters)."""
        return sum(self.counters.values())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'GCounter',
            'node_id': self.node_id,
            'counters': dict(self.counters),
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GCounter':
        counter = cls(data['node_id'])
        counter.counters = defaultdict(int, data['counters'])
        counter.created_at = data['created_at']
        return counter
    
    def __str__(self) -> str:
        return f"GCounter(node={self.node_id}, value={self.value()}, counters={dict(self.counters)})"
```

## PN-Counter: Increment/Decrement Counter

```python
class PNCounter(CRDT[int]):
    """
    Positive-Negative Counter CRDT.
    
    Supports both increment and decrement operations using two G-Counters.
    Value is the difference between positive and negative totals.
    """
    
    def __init__(self, node_id: str):
        super().__init__(node_id)
        self.positive = GCounter(node_id)
        self.negative = GCounter(node_id)
    
    def increment(self, amount: int = 1) -> 'PNCounter':
        """Increment the counter."""
        if amount <= 0:
            raise ValueError("Increment amount must be positive")
        
        self.positive.increment(amount)
        return self
    
    def decrement(self, amount: int = 1) -> 'PNCounter':
        """Decrement the counter."""
        if amount <= 0:
            raise ValueError("Decrement amount must be positive")
        
        self.negative.increment(amount)
        return self
    
    def merge(self, other: 'PNCounter') -> 'PNCounter':
        """Merge by merging underlying G-Counters."""
        result = PNCounter(self.node_id)
        result.positive = self.positive.merge(other.positive)
        result.negative = self.negative.merge(other.negative)
        return result
    
    def value(self) -> int:
        """Get current counter value."""
        return self.positive.value() - self.negative.value()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'PNCounter',
            'node_id': self.node_id,
            'positive': self.positive.to_dict(),
            'negative': self.negative.to_dict(),
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PNCounter':
        counter = cls(data['node_id'])
        counter.positive = GCounter.from_dict(data['positive'])
        counter.negative = GCounter.from_dict(data['negative'])
        counter.created_at = data['created_at']
        return counter
    
    def __str__(self) -> str:
        return f"PNCounter(node={self.node_id}, value={self.value()}, +{self.positive.value()}, -{self.negative.value()})"
```

## G-Set: Grow-Only Set

```python
class GSet(CRDT[set]):
    """
    Grow-only Set CRDT.
    
    Supports add operations only. Elements can never be removed.
    Merge operation is set union.
    """
    
    def __init__(self, node_id: str):
        super().__init__(node_id)
        self.elements: set = set()
    
    def add(self, element: Any) -> 'GSet':
        """
        Add an element to the set.
        
        Args:
            element: Element to add (must be hashable)
            
        Returns:
            Self for method chaining
        """
        if not isinstance(element, (str, int, float, tuple, frozenset)):
            raise ValueError("Element must be hashable")
        
        self.elements.add(element)
        return self
    
    def contains(self, element: Any) -> bool:
        """Check if element is in the set."""
        return element in self.elements
    
    def merge(self, other: 'GSet') -> 'GSet':
        """Merge by taking set union."""
        result = GSet(self.node_id)
        result.elements = self.elements | other.elements
        return result
    
    def value(self) -> set:
        """Get current set value."""
        return self.elements.copy()
    
    def size(self) -> int:
        """Get number of elements in set."""
        return len(self.elements)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'GSet',
            'node_id': self.node_id,
            'elements': list(self.elements),
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GSet':
        gset = cls(data['node_id'])
        gset.elements = set(data['elements'])
        gset.created_at = data['created_at']
        return gset
    
    def __str__(self) -> str:
        return f"GSet(node={self.node_id}, size={self.size()}, elements={sorted(list(self.elements))})"
```

## OR-Set: Observed-Remove Set

```python
@dataclass
class ElementTag:
    """Unique tag for OR-Set elements to track add/remove operations."""
    element: Any
    node_id: str
    timestamp: float
    unique_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    def __hash__(self):
        return hash((self.element, self.node_id, self.timestamp, self.unique_id))

class ORSet(CRDT[set]):
    """
    Observed-Remove Set CRDT.
    
    Supports both add and remove operations. Uses unique tags to track
    element additions, allowing removes to be properly handled.
    """
    
    def __init__(self, node_id: str):
        super().__init__(node_id)
        self.added_tags: set[ElementTag] = set()
        self.removed_tags: set[ElementTag] = set()
    
    def add(self, element: Any) -> 'ORSet':
        """
        Add an element with a unique tag.
        
        Args:
            element: Element to add
            
        Returns:
            Self for method chaining
        """
        tag = ElementTag(
            element=element,
            node_id=self.node_id,
            timestamp=time.time()
        )
        self.added_tags.add(tag)
        return self
    
    def remove(self, element: Any) -> 'ORSet':
        """
        Remove an element by marking all its current tags as removed.
        
        Args:
            element: Element to remove
            
        Returns:
            Self for method chaining
        """
        # Find all current tags for this element
        current_tags = {
            tag for tag in self.added_tags 
            if tag.element == element and tag not in self.removed_tags
        }
        
        # Mark all current tags as removed
        self.removed_tags.update(current_tags)
        return self
    
    def contains(self, element: Any) -> bool:
        """Check if element is currently in the set."""
        return any(
            tag.element == element and tag not in self.removed_tags
            for tag in self.added_tags
        )
    
    def merge(self, other: 'ORSet') -> 'ORSet':
        """Merge by taking union of added and removed tags."""
        result = ORSet(self.node_id)
        result.added_tags = self.added_tags | other.added_tags
        result.removed_tags = self.removed_tags | other.removed_tags
        return result
    
    def value(self) -> set:
        """Get current set value (elements present minus removed)."""
        return {
            tag.element for tag in self.added_tags
            if tag not in self.removed_tags
        }
    
    def size(self) -> int:
        """Get number of elements currently in set."""
        return len(self.value())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'ORSet',
            'node_id': self.node_id,
            'added_tags': [
                {
                    'element': tag.element,
                    'node_id': tag.node_id,
                    'timestamp': tag.timestamp,
                    'unique_id': tag.unique_id
                }
                for tag in self.added_tags
            ],
            'removed_tags': [
                {
                    'element': tag.element,
                    'node_id': tag.node_id,
                    'timestamp': tag.timestamp,
                    'unique_id': tag.unique_id
                }
                for tag in self.removed_tags
            ],
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ORSet':
        orset = cls(data['node_id'])
        
        orset.added_tags = {
            ElementTag(
                element=tag_data['element'],
                node_id=tag_data['node_id'],
                timestamp=tag_data['timestamp'],
                unique_id=tag_data['unique_id']
            )
            for tag_data in data['added_tags']
        }
        
        orset.removed_tags = {
            ElementTag(
                element=tag_data['element'],
                node_id=tag_data['node_id'],
                timestamp=tag_data['timestamp'],
                unique_id=tag_data['unique_id']
            )
            for tag_data in data['removed_tags']
        }
        
        orset.created_at = data['created_at']
        return orset
    
    def __str__(self) -> str:
        elements = sorted(list(self.value()))
        return f"ORSet(node={self.node_id}, size={self.size()}, elements={elements})"
```

## LWW-Register: Last-Writer-Wins Register

```python
@dataclass
class RegisterValue:
    """Value with timestamp for LWW-Register."""
    value: Any
    timestamp: float
    node_id: str
    
    def __lt__(self, other: 'RegisterValue') -> bool:
        """Compare register values for last-writer-wins semantics."""
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp
        # Break ties using node_id for deterministic behavior
        return self.node_id < other.node_id

class LWWRegister(CRDT[Any]):
    """
    Last-Writer-Wins Register CRDT.
    
    Stores a single value with timestamp. Merge operation selects
    the value with the latest timestamp (or deterministic tie-breaking).
    """
    
    def __init__(self, node_id: str, initial_value: Any = None):
        super().__init__(node_id)
        self.register_value = RegisterValue(
            value=initial_value,
            timestamp=time.time(),
            node_id=node_id
        )
    
    def set(self, value: Any) -> 'LWWRegister':
        """
        Set the register value with current timestamp.
        
        Args:
            value: New value to set
            
        Returns:
            Self for method chaining
        """
        self.register_value = RegisterValue(
            value=value,
            timestamp=time.time(),
            node_id=self.node_id
        )
        return self
    
    def merge(self, other: 'LWWRegister') -> 'LWWRegister':
        """Merge by selecting value with latest timestamp."""
        result = LWWRegister(self.node_id)
        
        if other.register_value > self.register_value:
            result.register_value = other.register_value
        else:
            result.register_value = self.register_value
        
        return result
    
    def value(self) -> Any:
        """Get current register value."""
        return self.register_value.value
    
    def timestamp(self) -> float:
        """Get timestamp of current value."""
        return self.register_value.timestamp
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'type': 'LWWRegister',
            'node_id': self.node_id,
            'value': self.register_value.value,
            'timestamp': self.register_value.timestamp,
            'value_node_id': self.register_value.node_id,
            'created_at': self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LWWRegister':
        register = cls(data['node_id'])
        register.register_value = RegisterValue(
            value=data['value'],
            timestamp=data['timestamp'],
            node_id=data['value_node_id']
        )
        register.created_at = data['created_at']
        return register
    
    def __str__(self) -> str:
        return f"LWWRegister(node={self.node_id}, value={self.value()}, timestamp={self.timestamp():.3f})"
```

## Network Simulation and Message Passing

```python
import random
import threading
import queue
from typing import List, Callable, Optional
from dataclasses import dataclass
from enum import Enum

class MessageType(Enum):
    """Types of messages in the CRDT network."""
    STATE_SYNC = "state_sync"
    OPERATION = "operation"
    HEARTBEAT = "heartbeat"

@dataclass
class NetworkMessage:
    """Network message for CRDT synchronization."""
    message_id: str
    message_type: MessageType
    from_node: str
    to_node: str
    payload: Dict[str, Any]
    timestamp: float
    ttl: int = 10  # Time to live (hops)

class NetworkSimulator:
    """
    Simulates realistic network conditions for CRDT testing.
    
    Features:
    - Message delays and reordering
    - Network partitions
    - Message loss
    - Bandwidth limitations
    """
    
    def __init__(self, 
                 latency_range: tuple = (10, 100),  # ms
                 loss_rate: float = 0.05,
                 partition_probability: float = 0.01):
        """
        Initialize network simulator.
        
        Args:
            latency_range: Min and max latency in milliseconds
            loss_rate: Probability of message loss (0.0 to 1.0)
            partition_probability: Probability of network partition
        """
        self.latency_range = latency_range
        self.loss_rate = loss_rate
        self.partition_probability = partition_probability
        self.partitioned_nodes: set = set()
        self.message_queue = queue.PriorityQueue()
        self.running = False
        self.message_handlers: Dict[str, Callable] = {}
    
    def register_node(self, node_id: str, message_handler: Callable):
        """Register a node's message handler."""
        self.message_handlers[node_id] = message_handler
    
    def send_message(self, message: NetworkMessage) -> bool:
        """
        Send a message through the network simulation.
        
        Args:
            message: Message to send
            
        Returns:
            True if message was accepted, False if dropped
        """
        # Check for network partition
        if (message.from_node in self.partitioned_nodes or 
            message.to_node in self.partitioned_nodes):
            return False
        
        # Check for message loss
        if random.random() < self.loss_rate:
            return False
        
        # Add random latency
        latency_ms = random.randint(*self.latency_range)
        delivery_time = time.time() + (latency_ms / 1000)
        
        # Add to message queue with delivery time as priority
        self.message_queue.put((delivery_time, message))
        return True
    
    def create_partition(self, nodes: List[str]):
        """Create a network partition isolating the specified nodes."""
        self.partitioned_nodes.update(nodes)
    
    def heal_partition(self):
        """Heal all network partitions."""
        self.partitioned_nodes.clear()
    
    def start(self):
        """Start the network message delivery simulation."""
        self.running = True
        threading.Thread(target=self._message_delivery_loop, daemon=True).start()
    
    def stop(self):
        """Stop the network simulation."""
        self.running = False
    
    def _message_delivery_loop(self):
        """Background thread for delivering messages."""
        while self.running:
            try:
                # Wait for messages with timeout
                delivery_time, message = self.message_queue.get(timeout=0.1)
                
                # Check if it's time to deliver
                if time.time() >= delivery_time:
                    # Deliver message to target node
                    if message.to_node in self.message_handlers:
                        self.message_handlers[message.to_node](message)
                else:
                    # Put message back if not ready
                    self.message_queue.put((delivery_time, message))
                    time.sleep(0.01)
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error in message delivery: {e}")
```

## Distributed CRDT Node

```python
class CRDTNode:
    """
    A distributed node that manages multiple CRDTs and handles networking.
    
    This represents a complete node in a distributed CRDT system,
    managing state synchronization and providing a clean API.
    """
    
    def __init__(self, node_id: str, network: NetworkSimulator):
        """
        Initialize CRDT node.
        
        Args:
            node_id: Unique identifier for this node
            network: Network simulator for message passing
        """
        self.node_id = node_id
        self.network = network
        self.crdts: Dict[str, CRDT] = {}
        self.peers: set = set()
        self.sync_interval = 5.0  # seconds
        self.last_sync = time.time()
        
        # Register with network
        self.network.register_node(node_id, self.handle_message)
        
        # Start periodic sync
        self._start_periodic_sync()
    
    def create_crdt(self, crdt_id: str, crdt_type: str, **kwargs) -> CRDT:
        """
        Create a new CRDT on this node.
        
        Args:
            crdt_id: Unique identifier for the CRDT
            crdt_type: Type of CRDT to create
            **kwargs: Additional arguments for CRDT constructor
            
        Returns:
            Created CRDT instance
        """
        crdt_classes = {
            'GCounter': GCounter,
            'PNCounter': PNCounter,
            'GSet': GSet,
            'ORSet': ORSet,
            'LWWRegister': LWWRegister
        }
        
        if crdt_type not in crdt_classes:
            raise ValueError(f"Unknown CRDT type: {crdt_type}")
        
        crdt = crdt_classes[crdt_type](self.node_id, **kwargs)
        self.crdts[crdt_id] = crdt
        return crdt
    
    def get_crdt(self, crdt_id: str) -> Optional[CRDT]:
        """Get a CRDT by ID."""
        return self.crdts.get(crdt_id)
    
    def add_peer(self, peer_node_id: str):
        """Add a peer node for synchronization."""
        self.peers.add(peer_node_id)
    
    def remove_peer(self, peer_node_id: str):
        """Remove a peer node."""
        self.peers.discard(peer_node_id)
    
    def sync_with_peers(self):
        """Manually trigger synchronization with all peers."""
        for peer in self.peers:
            self.sync_with_peer(peer)
    
    def sync_with_peer(self, peer_node_id: str):
        """Synchronize all CRDTs with a specific peer."""
        for crdt_id, crdt in self.crdts.items():
            message = NetworkMessage(
                message_id=str(uuid.uuid4()),
                message_type=MessageType.STATE_SYNC,
                from_node=self.node_id,
                to_node=peer_node_id,
                payload={
                    'crdt_id': crdt_id,
                    'crdt_state': crdt.to_dict()
                },
                timestamp=time.time()
            )
            self.network.send_message(message)
    
    def handle_message(self, message: NetworkMessage):
        """Handle incoming network messages."""
        if message.message_type == MessageType.STATE_SYNC:
            self._handle_state_sync(message)
        elif message.message_type == MessageType.HEARTBEAT:
            self._handle_heartbeat(message)
    
    def _handle_state_sync(self, message: NetworkMessage):
        """Handle CRDT state synchronization message."""
        crdt_id = message.payload['crdt_id']
        remote_state = message.payload['crdt_state']
        
        if crdt_id not in self.crdts:
            # Create CRDT if it doesn't exist
            crdt_type = remote_state['type']
            self.create_crdt(crdt_id, crdt_type)
        
        # Merge remote state
        local_crdt = self.crdts[crdt_id]
        remote_crdt = self._deserialize_crdt(remote_state)
        
        if remote_crdt:
            merged_crdt = local_crdt.merge(remote_crdt)
            self.crdts[crdt_id] = merged_crdt
    
    def _deserialize_crdt(self, state: Dict[str, Any]) -> Optional[CRDT]:
        """Deserialize CRDT from state dictionary."""
        crdt_type = state.get('type')
        
        crdt_classes = {
            'GCounter': GCounter,
            'PNCounter': PNCounter,
            'GSet': GSet,
            'ORSet': ORSet,
            'LWWRegister': LWWRegister
        }
        
        if crdt_type in crdt_classes:
            return crdt_classes[crdt_type].from_dict(state)
        
        return None
    
    def _handle_heartbeat(self, message: NetworkMessage):
        """Handle heartbeat message."""
        # Send heartbeat response
        response = NetworkMessage(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.HEARTBEAT,
            from_node=self.node_id,
            to_node=message.from_node,
            payload={'response': True},
            timestamp=time.time()
        )
        self.network.send_message(response)
    
    def _start_periodic_sync(self):
        """Start periodic synchronization with peers."""
        def sync_loop():
            while True:
                time.sleep(self.sync_interval)
                if time.time() - self.last_sync >= self.sync_interval:
                    self.sync_with_peers()
                    self.last_sync = time.time()
        
        threading.Thread(target=sync_loop, daemon=True).start()
    
    def status(self) -> Dict[str, Any]:
        """Get comprehensive status of this node."""
        return {
            'node_id': self.node_id,
            'peers': list(self.peers),
            'crdts': {
                crdt_id: {
                    'type': crdt.__class__.__name__,
                    'value': crdt.value(),
                    'state': crdt.to_dict()
                }
                for crdt_id, crdt in self.crdts.items()
            },
            'last_sync': self.last_sync
        }
    
    def __str__(self) -> str:
        crdt_summary = {crdt_id: crdt.value() for crdt_id, crdt in self.crdts.items()}
        return f"CRDTNode(id={self.node_id}, peers={len(self.peers)}, crdts={crdt_summary})"
```

## Complete Example: Distributed Shopping Cart

```python
def demonstrate_distributed_shopping_cart():
    """
    Demonstrate a realistic distributed shopping cart using multiple CRDT types.
    """
    print("Distributed Shopping Cart with CRDTs")
    print("=" * 60)
    
    # Create network simulator
    network = NetworkSimulator(
        latency_range=(20, 80),
        loss_rate=0.1,
        partition_probability=0.02
    )
    network.start()
    
    # Create three nodes (mobile, web, backend)
    mobile_node = CRDTNode("mobile", network)
    web_node = CRDTNode("web", network)
    backend_node = CRDTNode("backend", network)
    
    # Set up peer connections
    nodes = [mobile_node, web_node, backend_node]
    for node in nodes:
        for other in nodes:
            if node != other:
                node.add_peer(other.node_id)
    
    # Create shopping cart CRDTs
    for node in nodes:
        # Items in cart (OR-Set for add/remove items)
        node.create_crdt("cart_items", "ORSet")
        
        # Item quantities (PN-Counter for each item)
        node.create_crdt("laptop_quantity", "PNCounter")
        node.create_crdt("mouse_quantity", "PNCounter")
        node.create_crdt("keyboard_quantity", "PNCounter")
        
        # Last viewed item (LWW-Register)
        node.create_crdt("last_viewed", "LWWRegister", initial_value=None)
        
        # Total items counter (G-Counter for analytics)
        node.create_crdt("total_items_added", "GCounter")
    
    print("\\n📱 Mobile user adds items...")
    
    # Mobile user adds items
    mobile_cart = mobile_node.get_crdt("cart_items")
    mobile_cart.add("laptop").add("mouse")
    
    mobile_laptop_qty = mobile_node.get_crdt("laptop_quantity")
    mobile_laptop_qty.increment(1)
    
    mobile_mouse_qty = mobile_node.get_crdt("mouse_quantity")
    mobile_mouse_qty.increment(1)
    
    mobile_total = mobile_node.get_crdt("total_items_added")
    mobile_total.increment(2)
    
    mobile_last_viewed = mobile_node.get_crdt("last_viewed")
    mobile_last_viewed.set("laptop")
    
    print(f"  Mobile cart: {mobile_cart.value()}")
    print(f"  Laptop qty: {mobile_laptop_qty.value()}")
    print(f"  Last viewed: {mobile_last_viewed.value()}")
    
    print("\\n💻 Web user modifies cart...")
    
    # Web user adds keyboard and increases laptop quantity
    web_cart = web_node.get_crdt("cart_items")
    web_cart.add("keyboard")
    
    web_laptop_qty = web_node.get_crdt("laptop_quantity")
    web_laptop_qty.increment(1)  # Now 2 laptops
    
    web_keyboard_qty = web_node.get_crdt("keyboard_quantity")
    web_keyboard_qty.increment(1)
    
    web_total = web_node.get_crdt("total_items_added")
    web_total.increment(2)
    
    web_last_viewed = web_node.get_crdt("last_viewed")
    web_last_viewed.set("keyboard")
    
    print(f"  Web cart: {web_cart.value()}")
    print(f"  Laptop qty: {web_laptop_qty.value()}")
    print(f"  Last viewed: {web_last_viewed.value()}")
    
    print("\\n🔄 Synchronizing...")
    
    # Force synchronization
    time.sleep(1)  # Let network messages propagate
    for node in nodes:
        node.sync_with_peers()
    
    time.sleep(2)  # Wait for convergence
    
    print("\\n📊 Final state after synchronization:")
    
    for node in nodes:
        cart_items = node.get_crdt("cart_items")
        laptop_qty = node.get_crdt("laptop_quantity")
        mouse_qty = node.get_crdt("mouse_quantity")
        keyboard_qty = node.get_crdt("keyboard_quantity")
        last_viewed = node.get_crdt("last_viewed")
        total_added = node.get_crdt("total_items_added")
        
        print(f"\\n  {node.node_id.upper()} NODE:")
        print(f"    Cart items: {sorted(list(cart_items.value()))}")
        print(f"    Quantities: laptop={laptop_qty.value()}, mouse={mouse_qty.value()}, keyboard={keyboard_qty.value()}")
        print(f"    Last viewed: {last_viewed.value()}")
        print(f"    Total items added (analytics): {total_added.value()}")
    
    # Test network partition
    print("\\n🚫 Simulating network partition...")
    network.create_partition(["mobile"])
    
    # Mobile user removes mouse while partitioned
    mobile_cart.remove("mouse")
    mobile_mouse_qty.decrement(1)
    
    print(f"  Mobile (partitioned) removes mouse: {mobile_cart.value()}")
    
    # Web user adds more items
    web_laptop_qty.increment(1)  # 3 laptops now
    print(f"  Web adds another laptop: {web_laptop_qty.value()}")
    
    time.sleep(1)
    
    print("\\n🔄 Healing partition...")
    network.heal_partition()
    
    # Force sync after partition heal
    time.sleep(1)
    for node in nodes:
        node.sync_with_peers()
    
    time.sleep(2)
    
    print("\\n📊 Final converged state:")
    
    for node in nodes:
        cart_items = node.get_crdt("cart_items")
        laptop_qty = node.get_crdt("laptop_quantity")
        mouse_qty = node.get_crdt("mouse_quantity")
        
        print(f"  {node.node_id}: cart={sorted(list(cart_items.value()))}, laptop_qty={laptop_qty.value()}, mouse_qty={mouse_qty.value()}")
    
    # Verify convergence
    cart_values = [list(node.get_crdt("cart_items").value()) for node in nodes]
    laptop_values = [node.get_crdt("laptop_quantity").value() for node in nodes]
    
    if all(sorted(cv) == sorted(cart_values[0]) for cv in cart_values) and \
       all(lv == laptop_values[0] for lv in laptop_values):
        print("\\n✅ SUCCESS: All nodes converged to consistent state!")
    else:
        print("\\n❌ FAILURE: Nodes did not converge properly")
    
    network.stop()

if __name__ == "__main__":
    demonstrate_distributed_shopping_cart()
```

## Testing Framework

```python
import unittest
from typing import List

class CRDTTestFramework(unittest.TestCase):
    """
    Comprehensive test framework for CRDT implementations.
    
    Tests mathematical properties and distributed behavior.
    """
    
    def test_g_counter_properties(self):
        """Test G-Counter CRDT properties."""
        counter1 = GCounter("node1")
        counter2 = GCounter("node2")
        counter3 = GCounter("node3")
        
        # Test basic operations
        counter1.increment(5)
        counter2.increment(3)
        counter3.increment(7)
        
        # Test commutativity: merge(a, b) = merge(b, a)
        merge_ab = counter1.merge(counter2)
        merge_ba = counter2.merge(counter1)
        self.assertEqual(merge_ab.value(), merge_ba.value())
        
        # Test associativity: merge(merge(a, b), c) = merge(a, merge(b, c))
        left_assoc = counter1.merge(counter2).merge(counter3)
        right_assoc = counter1.merge(counter2.merge(counter3))
        self.assertEqual(left_assoc.value(), right_assoc.value())
        
        # Test idempotence: merge(a, a) = a
        self_merge = counter1.merge(counter1)
        self.assertEqual(counter1.value(), self_merge.value())
        
        # Test monotonicity: value only increases
        original_value = counter1.value()
        counter1.increment(1)
        self.assertGreater(counter1.value(), original_value)
    
    def test_or_set_semantics(self):
        """Test OR-Set add/remove semantics."""
        set1 = ORSet("node1")
        set2 = ORSet("node2")
        
        # Both nodes add the same element
        set1.add("apple")
        set2.add("apple")
        
        # Node1 removes apple
        set1.remove("apple")
        
        # Merge sets
        merged = set1.merge(set2)
        
        # Apple should still be present (concurrent add wins over remove)
        self.assertTrue(merged.contains("apple"))
        
        # Test remove after merge
        merged.remove("apple")
        self.assertFalse(merged.contains("apple"))
    
    def test_network_partition_convergence(self):
        """Test that CRDTs converge after network partitions."""
        network = NetworkSimulator(loss_rate=0.0)  # No message loss for deterministic testing
        network.start()
        
        try:
            # Create two nodes
            node1 = CRDTNode("node1", network)
            node2 = CRDTNode("node2", network)
            
            node1.add_peer("node2")
            node2.add_peer("node1")
            
            # Create counters
            counter1 = node1.create_crdt("test_counter", "PNCounter")
            counter2 = node2.create_crdt("test_counter", "PNCounter")
            
            # Partition network
            network.create_partition(["node1"])
            
            # Make changes during partition
            counter1.increment(5)
            counter2.increment(3)
            
            # Verify different values during partition
            self.assertNotEqual(counter1.value(), counter2.value())
            
            # Heal partition
            network.heal_partition()
            
            # Force synchronization
            node1.sync_with_peers()
            node2.sync_with_peers()
            
            # Wait for convergence
            time.sleep(1)
            
            # Verify convergence
            final_counter1 = node1.get_crdt("test_counter")
            final_counter2 = node2.get_crdt("test_counter")
            self.assertEqual(final_counter1.value(), final_counter2.value())
            self.assertEqual(final_counter1.value(), 8)  # 5 + 3
            
        finally:
            network.stop()

def run_tests():
    """Run the complete test suite."""
    unittest.main(verbosity=2)

if __name__ == "__main__":
    # Run demonstration
    demonstrate_distributed_shopping_cart()
    
    print("\\n" + "="*60)
    print("Running test suite...")
    print("="*60)
    
    # Run tests
    run_tests()
```

## Running the Code

Save all the code in a file called `crdt_implementation.py` and run:

```bash
python crdt_implementation.py
```

This implementation provides:

1. **Complete CRDT Types**: G-Counter, PN-Counter, G-Set, OR-Set, LWW-Register
2. **Network Simulation**: Realistic network conditions with latency, loss, and partitions
3. **Distributed Nodes**: Full node implementation with automatic synchronization
4. **Comprehensive Testing**: Test framework validating CRDT properties
5. **Real-World Example**: Distributed shopping cart demonstration

The code demonstrates how CRDTs enable building robust distributed systems that remain available and eventually consistent without requiring complex coordination protocols.