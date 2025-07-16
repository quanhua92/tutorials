# Agent Discovery and Orchestration: Building Dynamic Multi-Agent Ecosystems

**Based on:** [09_agent_discovery](https://github.com/panaversity/learn-agentic-ai/tree/bd868a5030d29df4d816c9d6322899655424b49a/09_agent_discovery)

## The Core Concept: Why This Example Exists

### The Problem: Static Agent Systems Can't Adapt to Dynamic Needs

Traditional multi-agent systems rely on **static, pre-configured connections** between agents, creating several limitations:

- **Rigid Architecture**: Agents can only communicate with pre-defined partners
- **Single Points of Failure**: When one agent fails, the entire workflow breaks
- **Poor Resource Utilization**: Can't dynamically balance load across available agents
- **Limited Scalability**: Adding new agents requires reconfiguring the entire system
- **No Capability Evolution**: Agents can't discover new capabilities or services as they become available
- **Manual Orchestration**: Requires human intervention to route tasks to appropriate agents

The fundamental challenge is creating **dynamic, self-organizing agent networks** that can discover capabilities, adapt to failures, and optimize performance without central coordination.

### The Solution: Agent Discovery and Dynamic Orchestration

**Agent discovery and orchestration** enables the creation of **autonomous agent ecosystems** where:

- **Agents discover each other dynamically** using standardized protocols
- **Capabilities are matched automatically** based on task requirements
- **Load balancing occurs naturally** across available agent instances
- **Failures are handled gracefully** with automatic failover
- **New agents integrate seamlessly** without system reconfiguration
- **Performance optimizes continuously** through reputation and metrics

The key insight: **Just as the internet enables dynamic discovery and communication between any connected device, agent ecosystems need discovery protocols that enable autonomous agents to find, evaluate, and collaborate with each other.**

---

## Practical Walkthrough: Code Breakdown

### Foundation Layer: Agent Cards and Discovery Protocol

The foundation of agent discovery is the **Agent Card** system, which provides a standardized way for agents to advertise their capabilities.

#### Agent Card Implementation

**Standardized Agent Advertisement:**
```python
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, HttpUrl
from datetime import datetime
import json
import aiohttp
import asyncio

class AgentCapability(BaseModel):
    """Definition of an agent capability"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    confidence_score: float = 0.0
    cost_estimate: Optional[float] = None
    average_response_time: Optional[float] = None

class AgentCard(BaseModel):
    """Standardized agent advertisement following A2A protocol"""
    agent_id: str
    name: str
    description: str
    version: str
    endpoint: HttpUrl
    capabilities: List[AgentCapability]
    supported_protocols: List[str] = ["json-rpc-2.0", "rest", "sse"]
    authentication: Dict[str, Any] = {"type": "oauth2"}
    health_check_endpoint: str = "/health"
    metrics_endpoint: str = "/metrics"
    max_concurrent_tasks: int = 10
    current_load: int = 0
    reputation_score: float = 0.0
    last_seen: datetime
    tags: List[str] = []
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class AgentRegistry:
    """Centralized registry for agent discovery and management"""
    
    def __init__(self):
        self.agents: Dict[str, AgentCard] = {}
        self.capability_index: Dict[str, List[str]] = {}
        self.health_check_interval = 60  # seconds
        self.cleanup_interval = 300  # 5 minutes
        
    async def register_agent(self, agent_card: AgentCard) -> bool:
        """Register an agent with the registry"""
        try:
            # Validate agent card
            if await self._validate_agent_card(agent_card):
                self.agents[agent_card.agent_id] = agent_card
                await self._update_capability_index(agent_card)
                
                print(f"✅ Registered agent: {agent_card.name} ({agent_card.agent_id})")
                return True
            else:
                print(f"❌ Failed to validate agent card for {agent_card.agent_id}")
                return False
                
        except Exception as e:
            print(f"Error registering agent {agent_card.agent_id}: {e}")
            return False
    
    async def discover_agents(
        self, 
        capability: str = None,
        tags: List[str] = None,
        max_load: int = None,
        min_reputation: float = None
    ) -> List[AgentCard]:
        """Discover agents based on criteria"""
        
        candidates = list(self.agents.values())
        
        # Filter by capability
        if capability:
            candidates = [
                agent for agent in candidates
                if any(cap.name == capability for cap in agent.capabilities)
            ]
        
        # Filter by tags
        if tags:
            candidates = [
                agent for agent in candidates
                if any(tag in agent.tags for tag in tags)
            ]
        
        # Filter by load
        if max_load is not None:
            candidates = [
                agent for agent in candidates
                if agent.current_load <= max_load
            ]
        
        # Filter by reputation
        if min_reputation is not None:
            candidates = [
                agent for agent in candidates
                if agent.reputation_score >= min_reputation
            ]
        
        # Sort by suitability (reputation, load, response time)
        candidates.sort(
            key=lambda a: (
                -a.reputation_score,  # Higher reputation first
                a.current_load,       # Lower load first
                a.capabilities[0].average_response_time or 999  # Faster first
            )
        )
        
        return candidates
    
    async def _validate_agent_card(self, agent_card: AgentCard) -> bool:
        """Validate agent card by checking health endpoint"""
        try:
            async with aiohttp.ClientSession() as session:
                health_url = f"{agent_card.endpoint.rstrip('/')}{agent_card.health_check_endpoint}"
                async with session.get(health_url, timeout=10) as response:
                    return response.status == 200
        except Exception:
            return False
    
    async def _update_capability_index(self, agent_card: AgentCard):
        """Update the capability index for fast lookups"""
        for capability in agent_card.capabilities:
            capability_name = capability.name
            if capability_name not in self.capability_index:
                self.capability_index[capability_name] = []
            
            if agent_card.agent_id not in self.capability_index[capability_name]:
                self.capability_index[capability_name].append(agent_card.agent_id)
    
    async def start_health_monitoring(self):
        """Start periodic health checking of registered agents"""
        while True:
            await asyncio.sleep(self.health_check_interval)
            await self._check_agent_health()
    
    async def _check_agent_health(self):
        """Check health of all registered agents"""
        unhealthy_agents = []
        
        for agent_id, agent_card in self.agents.items():
            if not await self._validate_agent_card(agent_card):
                unhealthy_agents.append(agent_id)
                print(f"⚠️ Agent {agent_id} failed health check")
        
        # Remove unhealthy agents
        for agent_id in unhealthy_agents:
            await self.unregister_agent(agent_id)
    
    async def unregister_agent(self, agent_id: str):
        """Remove agent from registry"""
        if agent_id in self.agents:
            agent_card = self.agents[agent_id]
            
            # Remove from capability index
            for capability in agent_card.capabilities:
                if capability.name in self.capability_index:
                    if agent_id in self.capability_index[capability.name]:
                        self.capability_index[capability.name].remove(agent_id)
            
            # Remove from main registry
            del self.agents[agent_id]
            print(f"🗑️ Unregistered agent: {agent_id}")

class A2ACardResolver:
    """Official A2A Card Resolver for automatic agent discovery"""
    
    def __init__(self, registry: AgentRegistry):
        self.registry = registry
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes
    
    async def resolve_agent_card(self, agent_endpoint: str) -> Optional[AgentCard]:
        """Resolve agent card from well-known endpoint"""
        try:
            well_known_url = f"{agent_endpoint.rstrip('/')}/.well-known/agent.json"
            
            # Check cache first
            if well_known_url in self.cache:
                cached_entry = self.cache[well_known_url]
                if (datetime.now() - cached_entry["timestamp"]).seconds < self.cache_ttl:
                    return cached_entry["agent_card"]
            
            # Fetch agent card
            async with aiohttp.ClientSession() as session:
                async with session.get(well_known_url, timeout=10) as response:
                    if response.status == 200:
                        card_data = await response.json()
                        agent_card = AgentCard(**card_data)
                        
                        # Cache the result
                        self.cache[well_known_url] = {
                            "agent_card": agent_card,
                            "timestamp": datetime.now()
                        }
                        
                        return agent_card
            
            return None
            
        except Exception as e:
            print(f"Error resolving agent card from {agent_endpoint}: {e}")
            return None
    
    async def discover_and_register(self, agent_endpoints: List[str]):
        """Discover agents from endpoints and register them"""
        for endpoint in agent_endpoints:
            agent_card = await self.resolve_agent_card(endpoint)
            if agent_card:
                await self.registry.register_agent(agent_card)
```

### Communication Layer: Agent-to-Agent Protocol (A2A)

The A2A protocol enables standardized communication between discovered agents.

#### A2A Communication Implementation

**Standardized Agent Communication:**
```python
import uuid
from enum import Enum

class TaskStatus(Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"

class A2AMessage(BaseModel):
    """Standardized A2A message format"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.now)

class A2AResponse(BaseModel):
    """Standardized A2A response format"""
    id: str
    jsonrpc: str = "2.0"
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

class TaskRequest(BaseModel):
    """Task request to another agent"""
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capability: str
    parameters: Dict[str, Any]
    priority: int = 1
    timeout: Optional[int] = None
    callback_url: Optional[str] = None

class TaskResponse(BaseModel):
    """Task response from agent"""
    task_id: str
    status: TaskStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: Optional[float] = None
    estimated_completion: Optional[datetime] = None

class A2AClient:
    """Client for communicating with other agents via A2A protocol"""
    
    def __init__(self, agent_registry: AgentRegistry, source_agent_id: str):
        self.registry = agent_registry
        self.source_agent_id = source_agent_id
        self.active_tasks: Dict[str, TaskRequest] = {}
        
    async def delegate_task(
        self, 
        capability: str, 
        parameters: Dict[str, Any],
        selection_criteria: Dict[str, Any] = None
    ) -> TaskResponse:
        """Delegate a task to the most suitable agent"""
        
        # Discover suitable agents
        suitable_agents = await self.registry.discover_agents(
            capability=capability,
            max_load=selection_criteria.get("max_load", 8),
            min_reputation=selection_criteria.get("min_reputation", 0.5)
        )
        
        if not suitable_agents:
            return TaskResponse(
                task_id=str(uuid.uuid4()),
                status=TaskStatus.FAILED,
                error=f"No agents found with capability: {capability}"
            )
        
        # Select the best agent (first in sorted list)
        target_agent = suitable_agents[0]
        
        # Create task request
        task_request = TaskRequest(
            capability=capability,
            parameters=parameters,
            timeout=selection_criteria.get("timeout", 300)
        )
        
        # Send task to agent
        response = await self._send_task_request(target_agent, task_request)
        
        # Track active task
        self.active_tasks[task_request.task_id] = task_request
        
        return response
    
    async def _send_task_request(
        self, 
        target_agent: AgentCard, 
        task_request: TaskRequest
    ) -> TaskResponse:
        """Send task request to specific agent"""
        
        try:
            # Create A2A message
            message = A2AMessage(
                method="execute_task",
                params={
                    "task_request": task_request.dict(),
                    "source_agent": self.source_agent_id
                }
            )
            
            # Send request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{target_agent.endpoint}/a2a/execute",
                    json=message.dict(),
                    headers={"Content-Type": "application/json"},
                    timeout=task_request.timeout or 300
                ) as response:
                    
                    if response.status == 200:
                        response_data = await response.json()
                        a2a_response = A2AResponse(**response_data)
                        
                        if a2a_response.result:
                            return TaskResponse(**a2a_response.result)
                        else:
                            return TaskResponse(
                                task_id=task_request.task_id,
                                status=TaskStatus.FAILED,
                                error=str(a2a_response.error)
                            )
                    else:
                        return TaskResponse(
                            task_id=task_request.task_id,
                            status=TaskStatus.FAILED,
                            error=f"HTTP {response.status}: {await response.text()}"
                        )
                        
        except asyncio.TimeoutError:
            return TaskResponse(
                task_id=task_request.task_id,
                status=TaskStatus.FAILED,
                error="Task request timed out"
            )
        except Exception as e:
            return TaskResponse(
                task_id=task_request.task_id,
                status=TaskStatus.FAILED,
                error=str(e)
            )
    
    async def get_task_status(self, task_id: str) -> Optional[TaskResponse]:
        """Get status of a delegated task"""
        if task_id in self.active_tasks:
            task_request = self.active_tasks[task_id]
            
            # Find the agent handling this task
            # (In practice, you'd track which agent is handling each task)
            suitable_agents = await self.registry.discover_agents(
                capability=task_request.capability
            )
            
            if suitable_agents:
                target_agent = suitable_agents[0]
                
                # Query task status
                message = A2AMessage(
                    method="get_task_status",
                    params={"task_id": task_id}
                )
                
                # Send status request
                # Implementation similar to _send_task_request
                pass
        
        return None

class MultiAgentOrchestrator:
    """Orchestrator for coordinating multiple agents dynamically"""
    
    def __init__(self, registry: AgentRegistry, agent_id: str):
        self.registry = registry
        self.agent_id = agent_id
        self.a2a_client = A2AClient(registry, agent_id)
        
    async def coordinate_research_workflow(self, topic: str) -> Dict[str, Any]:
        """Coordinate a research workflow across multiple agents"""
        
        workflow_results = {}
        
        try:
            # Phase 1: Information Gathering (parallel)
            gathering_tasks = await asyncio.gather(
                self.a2a_client.delegate_task(
                    "web_search",
                    {"query": topic, "max_results": 20}
                ),
                self.a2a_client.delegate_task(
                    "academic_search", 
                    {"topic": topic, "max_papers": 10}
                ),
                self.a2a_client.delegate_task(
                    "news_search",
                    {"keywords": topic, "timeframe": "30d"}
                ),
                return_exceptions=True
            )
            
            # Collect successful results
            web_results = gathering_tasks[0] if not isinstance(gathering_tasks[0], Exception) else None
            academic_results = gathering_tasks[1] if not isinstance(gathering_tasks[1], Exception) else None
            news_results = gathering_tasks[2] if not isinstance(gathering_tasks[2], Exception) else None
            
            workflow_results["gathering"] = {
                "web": web_results.result if web_results and web_results.status == TaskStatus.COMPLETED else None,
                "academic": academic_results.result if academic_results and academic_results.status == TaskStatus.COMPLETED else None,
                "news": news_results.result if news_results and news_results.status == TaskStatus.COMPLETED else None
            }
            
            # Phase 2: Analysis (sequential, depends on gathering)
            if any(workflow_results["gathering"].values()):
                analysis_response = await self.a2a_client.delegate_task(
                    "data_analysis",
                    {
                        "data": workflow_results["gathering"],
                        "analysis_type": "comprehensive",
                        "focus": ["trends", "insights", "recommendations"]
                    }
                )
                
                workflow_results["analysis"] = analysis_response.result if analysis_response.status == TaskStatus.COMPLETED else None
            
            # Phase 3: Synthesis (depends on analysis)
            if workflow_results.get("analysis"):
                synthesis_response = await self.a2a_client.delegate_task(
                    "content_synthesis",
                    {
                        "analysis_results": workflow_results["analysis"],
                        "format": "executive_summary",
                        "length": "detailed"
                    }
                )
                
                workflow_results["synthesis"] = synthesis_response.result if synthesis_response.status == TaskStatus.COMPLETED else None
            
            # Phase 4: Quality Review (parallel with synthesis)
            if workflow_results.get("synthesis"):
                review_response = await self.a2a_client.delegate_task(
                    "quality_review",
                    {
                        "content": workflow_results["synthesis"],
                        "criteria": ["accuracy", "completeness", "clarity"]
                    }
                )
                
                workflow_results["review"] = review_response.result if review_response.status == TaskStatus.COMPLETED else None
            
            return {
                "status": "completed",
                "topic": topic,
                "workflow_results": workflow_results,
                "agents_used": await self._get_agents_used(),
                "total_time": "calculated_time_here"
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "partial_results": workflow_results
            }
    
    async def _get_agents_used(self) -> List[str]:
        """Get list of agents that participated in the workflow"""
        # In practice, track agents used during delegation
        return ["research-agent-1", "analysis-agent-2", "synthesis-agent-3"]
```

### Load Balancing and Failover: Intelligent Agent Selection

Dynamic agent ecosystems require sophisticated load balancing and failover mechanisms.

#### Intelligent Agent Selection

**Load-Aware Agent Selection:**
```python
class AgentLoadBalancer:
    """Intelligent load balancing and failover for agent selection"""
    
    def __init__(self, registry: AgentRegistry):
        self.registry = registry
        self.agent_metrics: Dict[str, Dict] = {}
        self.selection_strategy = "weighted_round_robin"
        
    async def select_agent(
        self, 
        capability: str,
        selection_criteria: Dict[str, Any] = None
    ) -> Optional[AgentCard]:
        """Select the best agent for a capability using intelligent algorithms"""
        
        # Get candidate agents
        candidates = await self.registry.discover_agents(
            capability=capability,
            max_load=selection_criteria.get("max_load"),
            min_reputation=selection_criteria.get("min_reputation")
        )
        
        if not candidates:
            return None
        
        # Apply selection strategy
        if self.selection_strategy == "weighted_round_robin":
            return await self._weighted_round_robin_selection(candidates)
        elif self.selection_strategy == "least_connections":
            return await self._least_connections_selection(candidates)
        elif self.selection_strategy == "response_time":
            return await self._response_time_selection(candidates)
        elif self.selection_strategy == "adaptive":
            return await self._adaptive_selection(candidates, capability)
        else:
            return candidates[0]  # Default to first available
    
    async def _weighted_round_robin_selection(self, candidates: List[AgentCard]) -> AgentCard:
        """Select agent using weighted round-robin based on capacity"""
        
        # Calculate weights based on available capacity
        weights = []
        for agent in candidates:
            available_capacity = agent.max_concurrent_tasks - agent.current_load
            weight = max(1, available_capacity)  # Minimum weight of 1
            weights.append(weight)
        
        # Weighted random selection
        import random
        selected = random.choices(candidates, weights=weights, k=1)[0]
        return selected
    
    async def _least_connections_selection(self, candidates: List[AgentCard]) -> AgentCard:
        """Select agent with least current load"""
        return min(candidates, key=lambda a: a.current_load)
    
    async def _response_time_selection(self, candidates: List[AgentCard]) -> AgentCard:
        """Select agent with best response time"""
        # Filter agents with response time data
        candidates_with_metrics = [
            agent for agent in candidates 
            if agent.capabilities and agent.capabilities[0].average_response_time is not None
        ]
        
        if candidates_with_metrics:
            return min(
                candidates_with_metrics, 
                key=lambda a: a.capabilities[0].average_response_time
            )
        else:
            return candidates[0]
    
    async def _adaptive_selection(self, candidates: List[AgentCard], capability: str) -> AgentCard:
        """Adaptive selection based on historical performance"""
        
        # Calculate composite scores
        scored_candidates = []
        
        for agent in candidates:
            metrics = self.agent_metrics.get(agent.agent_id, {})
            capability_metrics = metrics.get(capability, {})
            
            # Composite score factors
            reputation_score = agent.reputation_score
            load_score = 1.0 - (agent.current_load / agent.max_concurrent_tasks)
            response_time_score = 1.0 / (capability_metrics.get("avg_response_time", 1.0) + 1.0)
            success_rate = capability_metrics.get("success_rate", 0.5)
            
            # Weighted composite score
            composite_score = (
                reputation_score * 0.3 +
                load_score * 0.25 +
                response_time_score * 0.25 +
                success_rate * 0.2
            )
            
            scored_candidates.append((agent, composite_score))
        
        # Select agent with highest composite score
        best_agent = max(scored_candidates, key=lambda x: x[1])[0]
        return best_agent
    
    async def update_agent_metrics(
        self, 
        agent_id: str, 
        capability: str, 
        response_time: float,
        success: bool
    ):
        """Update agent performance metrics"""
        
        if agent_id not in self.agent_metrics:
            self.agent_metrics[agent_id] = {}
        
        if capability not in self.agent_metrics[agent_id]:
            self.agent_metrics[agent_id][capability] = {
                "total_requests": 0,
                "successful_requests": 0,
                "total_response_time": 0.0,
                "avg_response_time": 0.0,
                "success_rate": 0.0
            }
        
        metrics = self.agent_metrics[agent_id][capability]
        
        # Update counters
        metrics["total_requests"] += 1
        if success:
            metrics["successful_requests"] += 1
        metrics["total_response_time"] += response_time
        
        # Recalculate averages
        metrics["avg_response_time"] = metrics["total_response_time"] / metrics["total_requests"]
        metrics["success_rate"] = metrics["successful_requests"] / metrics["total_requests"]

class FailoverManager:
    """Manages failover scenarios in agent communication"""
    
    def __init__(self, load_balancer: AgentLoadBalancer):
        self.load_balancer = load_balancer
        self.retry_attempts = 3
        self.retry_delay = 1.0  # seconds
        
    async def execute_with_failover(
        self,
        capability: str,
        parameters: Dict[str, Any],
        selection_criteria: Dict[str, Any] = None
    ) -> TaskResponse:
        """Execute task with automatic failover"""
        
        last_error = None
        
        for attempt in range(self.retry_attempts):
            try:
                # Select agent
                agent = await self.load_balancer.select_agent(capability, selection_criteria)
                
                if not agent:
                    return TaskResponse(
                        task_id=str(uuid.uuid4()),
                        status=TaskStatus.FAILED,
                        error="No suitable agents available"
                    )
                
                # Execute task
                a2a_client = A2AClient(self.load_balancer.registry, "orchestrator")
                response = await a2a_client._send_task_request(
                    agent,
                    TaskRequest(capability=capability, parameters=parameters)
                )
                
                # If successful, update metrics and return
                if response.status == TaskStatus.COMPLETED:
                    await self.load_balancer.update_agent_metrics(
                        agent.agent_id, capability, 1.0, True  # Simplified metrics
                    )
                    return response
                else:
                    # Task failed, mark agent and try next
                    await self.load_balancer.update_agent_metrics(
                        agent.agent_id, capability, 1.0, False
                    )
                    last_error = response.error
                    
            except Exception as e:
                last_error = str(e)
                
            # Wait before retry
            if attempt < self.retry_attempts - 1:
                await asyncio.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
        
        # All attempts failed
        return TaskResponse(
            task_id=str(uuid.uuid4()),
            status=TaskStatus.FAILED,
            error=f"All failover attempts exhausted. Last error: {last_error}"
        )
```

### Event-Driven Orchestration: Reactive Agent Networks

Advanced agent ecosystems use event-driven patterns for loose coupling and scalability.

#### Event-Driven Agent Coordination

**Reactive Agent Network Implementation:**
```python
from typing import Callable
import asyncio
from asyncio import Queue

class AgentEvent(BaseModel):
    """Event for agent communication"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    source_agent: str
    target_agents: List[str] = []  # Empty means broadcast
    payload: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)
    correlation_id: Optional[str] = None

class EventBus:
    """Event bus for agent-to-agent communication"""
    
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.event_queue: Queue = Queue()
        self.processing = False
        
    async def subscribe(self, event_type: str, handler: Callable):
        """Subscribe to specific event types"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        
        self.subscribers[event_type].append(handler)
        print(f"📡 Subscribed to event type: {event_type}")
    
    async def publish(self, event: AgentEvent):
        """Publish event to the bus"""
        await self.event_queue.put(event)
        
        if not self.processing:
            asyncio.create_task(self._process_events())
    
    async def _process_events(self):
        """Process events from the queue"""
        self.processing = True
        
        try:
            while not self.event_queue.empty():
                event = await self.event_queue.get()
                await self._dispatch_event(event)
                
        finally:
            self.processing = False
    
    async def _dispatch_event(self, event: AgentEvent):
        """Dispatch event to appropriate handlers"""
        handlers = self.subscribers.get(event.event_type, [])
        
        if handlers:
            # Execute all handlers concurrently
            await asyncio.gather(
                *[handler(event) for handler in handlers],
                return_exceptions=True
            )
            
            print(f"📨 Dispatched event {event.event_type} to {len(handlers)} handlers")

class ReactiveAgent:
    """Agent that participates in event-driven orchestration"""
    
    def __init__(self, agent_id: str, capabilities: List[str], event_bus: EventBus):
        self.agent_id = agent_id
        self.capabilities = capabilities
        self.event_bus = event_bus
        self.task_queue: Queue = Queue()
        self.processing_tasks = False
        
    async def start(self):
        """Start the reactive agent"""
        # Subscribe to relevant events
        await self.event_bus.subscribe("task_available", self._handle_task_available)
        await self.event_bus.subscribe("agent_request", self._handle_agent_request)
        await self.event_bus.subscribe("capability_query", self._handle_capability_query)
        
        # Start task processing
        asyncio.create_task(self._process_task_queue())
        
        print(f"🤖 Reactive agent {self.agent_id} started")
    
    async def _handle_task_available(self, event: AgentEvent):
        """Handle task availability events"""
        task_info = event.payload
        required_capability = task_info.get("capability")
        
        # Check if we can handle this task
        if required_capability in self.capabilities:
            # Express interest in the task
            interest_event = AgentEvent(
                event_type="task_interest",
                source_agent=self.agent_id,
                target_agents=[event.source_agent],
                payload={
                    "task_id": task_info["task_id"],
                    "agent_id": self.agent_id,
                    "confidence": self._calculate_confidence(required_capability),
                    "estimated_time": self._estimate_completion_time(task_info)
                },
                correlation_id=event.correlation_id
            )
            
            await self.event_bus.publish(interest_event)
    
    async def _handle_agent_request(self, event: AgentEvent):
        """Handle direct agent requests"""
        if self.agent_id in event.target_agents or not event.target_agents:
            request_info = event.payload
            
            if request_info.get("type") == "execute_task":
                # Add task to queue
                await self.task_queue.put({
                    "task_id": request_info["task_id"],
                    "capability": request_info["capability"],
                    "parameters": request_info["parameters"],
                    "source_agent": event.source_agent,
                    "correlation_id": event.correlation_id
                })
    
    async def _handle_capability_query(self, event: AgentEvent):
        """Handle capability discovery queries"""
        query = event.payload.get("query")
        
        # Check if our capabilities match the query
        matching_capabilities = [
            cap for cap in self.capabilities 
            if query.lower() in cap.lower()
        ]
        
        if matching_capabilities:
            # Respond with our capabilities
            response_event = AgentEvent(
                event_type="capability_response",
                source_agent=self.agent_id,
                target_agents=[event.source_agent],
                payload={
                    "agent_id": self.agent_id,
                    "matching_capabilities": matching_capabilities,
                    "current_load": self.task_queue.qsize(),
                    "availability": "available" if self.task_queue.qsize() < 5 else "busy"
                },
                correlation_id=event.correlation_id
            )
            
            await self.event_bus.publish(response_event)
    
    async def _process_task_queue(self):
        """Process tasks from the queue"""
        self.processing_tasks = True
        
        while True:
            try:
                # Get task from queue (blocks until available)
                task = await self.task_queue.get()
                
                # Process the task
                result = await self._execute_task(task)
                
                # Publish completion event
                completion_event = AgentEvent(
                    event_type="task_completed",
                    source_agent=self.agent_id,
                    target_agents=[task["source_agent"]],
                    payload={
                        "task_id": task["task_id"],
                        "result": result,
                        "processing_time": "calculated_time",
                        "agent_id": self.agent_id
                    },
                    correlation_id=task["correlation_id"]
                )
                
                await self.event_bus.publish(completion_event)
                
            except Exception as e:
                print(f"Error processing task: {e}")
            
            await asyncio.sleep(0.1)  # Small delay to prevent busy waiting
    
    def _calculate_confidence(self, capability: str) -> float:
        """Calculate confidence score for handling a capability"""
        # Simplified confidence calculation
        if capability in self.capabilities:
            return 0.9
        return 0.0
    
    def _estimate_completion_time(self, task_info: Dict[str, Any]) -> int:
        """Estimate task completion time in seconds"""
        # Simplified estimation
        complexity = task_info.get("complexity", "medium")
        base_times = {"simple": 30, "medium": 120, "complex": 300}
        return base_times.get(complexity, 120)
    
    async def _execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific task"""
        # Simulate task execution
        await asyncio.sleep(2)  # Simulate processing time
        
        return {
            "status": "completed",
            "output": f"Task {task['task_id']} completed by {self.agent_id}",
            "capability_used": task["capability"]
        }

# Usage example: Setting up a reactive agent network
async def setup_reactive_agent_network():
    """Set up a network of reactive agents"""
    
    # Create event bus
    event_bus = EventBus()
    
    # Create specialized agents
    agents = [
        ReactiveAgent("research-agent-1", ["web_search", "academic_research"], event_bus),
        ReactiveAgent("analysis-agent-1", ["data_analysis", "statistical_analysis"], event_bus),
        ReactiveAgent("synthesis-agent-1", ["content_synthesis", "report_generation"], event_bus),
        ReactiveAgent("review-agent-1", ["quality_review", "fact_checking"], event_bus)
    ]
    
    # Start all agents
    for agent in agents:
        await agent.start()
    
    # Simulate a complex task that requires coordination
    complex_task_event = AgentEvent(
        event_type="task_available",
        source_agent="orchestrator",
        payload={
            "task_id": "research_project_001",
            "capability": "web_search",
            "complexity": "medium",
            "description": "Research latest trends in AI agent development"
        }
    )
    
    # Publish the task
    await event_bus.publish(complex_task_event)
    
    return event_bus, agents
```

---

## Mental Model: Thinking in Agent Networks

### Build the Mental Model: The Internet of Intelligent Agents

Think of agent discovery like **how devices connect to the internet**:

**Traditional Networks**: Fixed phone systems
- **Static connections**: Predefined phone numbers
- **Manual routing**: Operator assistance required
- **Single points of failure**: Central switchboard

**Agent Networks**: Modern internet
- **Dynamic discovery**: DNS and service discovery
- **Automatic routing**: Packets find optimal paths
- **Distributed resilience**: Multiple paths and failover

### Why It's Designed This Way: Enabling Agent Autonomy

Agent discovery patterns enable true autonomy by allowing agents to:

1. **Find collaborators independently** without human configuration
2. **Adapt to changing conditions** by discovering new capabilities
3. **Optimize performance** through intelligent selection algorithms
4. **Maintain resilience** with automatic failover and redundancy

### Further Exploration: Building Agent Marketplaces

**Immediate Practice:**
1. Implement agent cards and registry-based discovery
2. Create A2A communication between discovered agents
3. Build load balancing with health monitoring
4. Add event-driven coordination patterns

**Design Challenge:**
Create an "agent marketplace" where:
- Agents advertise specialized capabilities
- Tasks are auctioned to the best-suited agents
- Reputation systems track performance
- Dynamic pricing based on demand and quality

**Advanced Exploration:**
- How would you implement agent reputation and trust systems?
- What patterns support cross-organizational agent collaboration?
- How could agents negotiate service level agreements autonomously?
- What governance mechanisms prevent malicious agent behavior?

---

*Agent discovery and orchestration patterns form the foundation of autonomous agent ecosystems, enabling intelligent systems to find, evaluate, and collaborate with each other without central coordination. These patterns are essential for building scalable, resilient, and truly autonomous multi-agent systems that can adapt and evolve as new capabilities emerge.*