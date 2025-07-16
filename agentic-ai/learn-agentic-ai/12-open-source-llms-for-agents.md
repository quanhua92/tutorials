# Open Source LLMs for Agentic AI: Self-Hosted Intelligence at Scale

**Based on:** [09_open_source_llms](https://github.com/panaversity/learn-agentic-ai/tree/bd868a5030d29df4d816c9d6322899655424b49a/09_open_source_llms)

## The Core Concept: Why This Example Exists

### The Problem: Commercial API Dependencies Limit Agent Autonomy

While commercial LLM APIs (OpenAI, Anthropic, Google) provide powerful capabilities, they create significant limitations for agentic AI systems:

- **Cost Barriers**: API costs can become prohibitive at scale ($0.01-$0.06 per 1K tokens)
- **Vendor Lock-in**: Dependence on external providers for core intelligence
- **Data Privacy Concerns**: Sensitive data sent to third-party services
- **Rate Limiting**: API throttling constrains agent autonomy and responsiveness
- **Latency Issues**: Network round-trips introduce delays in agent reasoning
- **Compliance Challenges**: Regulatory requirements may prohibit external API usage
- **Availability Dependencies**: System reliability depends on external service uptime

The fundamental challenge is achieving **true agent autonomy** while maintaining cost-effectiveness, data privacy, and performance at scale.

### The Solution: Self-Hosted Open Source LLM Infrastructure

**Open source LLMs** provide a path to truly autonomous agentic systems by enabling:

- **Cost Control**: Fixed infrastructure costs instead of per-token pricing
- **Data Sovereignty**: Complete control over data processing and storage
- **Customization Freedom**: Fine-tuning models for specific agent domains
- **Unlimited Scaling**: No API rate limits or usage restrictions
- **Latency Optimization**: Local processing eliminates network delays
- **Compliance Assurance**: Meeting regulatory requirements through local deployment

The key insight: **Self-hosted open source LLMs transform agents from API-dependent systems into truly autonomous intelligent entities with complete control over their reasoning infrastructure.**

---

## Practical Walkthrough: Code Breakdown

### Foundation Layer: Local Model Deployment with Ollama

Ollama provides the most accessible entry point for running open source LLMs locally with minimal setup complexity.

#### Ollama-Based Agent Infrastructure

**Local LLM Agent Setup:**
```python
import asyncio
import aiohttp
import json
from typing import Dict, List, Any, AsyncGenerator
from agents import Agent
import requests

class OllamaLLMClient:
    """Client for interacting with Ollama-hosted models"""
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.session = None
        self.available_models = []
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        await self.refresh_models()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def refresh_models(self):
        """Get list of available models"""
        try:
            async with self.session.get(f"{self.base_url}/api/tags") as response:
                if response.status == 200:
                    data = await response.json()
                    self.available_models = [model["name"] for model in data.get("models", [])]
                    print(f"📚 Available models: {', '.join(self.available_models)}")
                else:
                    print(f"❌ Failed to fetch models: {response.status}")
        except Exception as e:
            print(f"Error fetching models: {e}")
    
    async def pull_model(self, model_name: str) -> bool:
        """Pull a model if not already available"""
        if model_name in self.available_models:
            return True
            
        try:
            print(f"📥 Pulling model {model_name}...")
            async with self.session.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name}
            ) as response:
                if response.status == 200:
                    # Stream the download progress
                    async for line in response.content:
                        try:
                            progress = json.loads(line)
                            if progress.get("status"):
                                print(f"  {progress['status']}")
                        except json.JSONDecodeError:
                            continue
                    
                    await self.refresh_models()
                    return model_name in self.available_models
                else:
                    print(f"❌ Failed to pull model: {response.status}")
                    return False
        except Exception as e:
            print(f"Error pulling model: {e}")
            return False
    
    async def chat(
        self, 
        model: str, 
        messages: List[Dict[str, str]],
        stream: bool = False,
        options: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Send chat request to Ollama"""
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": options or {}
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}/api/chat",
                json=payload
            ) as response:
                
                if response.status == 200:
                    if stream:
                        return await self._handle_streaming_response(response)
                    else:
                        return await response.json()
                else:
                    error_text = await response.text()
                    raise Exception(f"Ollama API error {response.status}: {error_text}")
                    
        except Exception as e:
            print(f"Error in chat request: {e}")
            raise
    
    async def _handle_streaming_response(self, response) -> AsyncGenerator[Dict[str, Any], None]:
        """Handle streaming chat responses"""
        async for line in response.content:
            if line:
                try:
                    chunk = json.loads(line)
                    yield chunk
                except json.JSONDecodeError:
                    continue

class OpenSourceAgent:
    """Agent powered by open source LLMs via Ollama"""
    
    def __init__(
        self, 
        name: str,
        instructions: str,
        model: str = "llama3.1:8b",
        ollama_url: str = "http://localhost:11434"
    ):
        self.name = name
        self.instructions = instructions
        self.model = model
        self.ollama_client = OllamaLLMClient(ollama_url)
        self.conversation_history = []
        self.tools = []
        
    async def add_tool(self, tool_definition: Dict[str, Any]):
        """Add a tool that the agent can use"""
        self.tools.append(tool_definition)
        print(f"🔧 Added tool: {tool_definition['name']}")
    
    async def process_message(self, message: str, context: Dict[str, Any] = None) -> str:
        """Process a message using the open source model"""
        
        async with self.ollama_client as client:
            # Ensure model is available
            if not await client.pull_model(self.model):
                raise Exception(f"Failed to load model: {self.model}")
            
            # Build conversation context
            messages = self._build_conversation_context(message, context)
            
            # Get response from model
            response = await client.chat(
                model=self.model,
                messages=messages,
                options={
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "top_k": 40,
                    "repeat_penalty": 1.1
                }
            )
            
            assistant_message = response["message"]["content"]
            
            # Update conversation history
            self.conversation_history.append({"role": "user", "content": message})
            self.conversation_history.append({"role": "assistant", "content": assistant_message})
            
            # Limit conversation history
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-20:]
            
            return assistant_message
    
    def _build_conversation_context(self, message: str, context: Dict[str, Any] = None) -> List[Dict[str, str]]:
        """Build conversation context for the model"""
        
        messages = []
        
        # System prompt with instructions
        system_prompt = f"""You are {self.name}, an AI agent with the following capabilities:

{self.instructions}

You have access to the following tools:
{self._format_tools_for_prompt()}

Current context:
{json.dumps(context) if context else 'No additional context'}

Respond helpfully and use tools when appropriate. Be concise but thorough.
"""
        
        messages.append({"role": "system", "content": system_prompt})
        
        # Add recent conversation history
        messages.extend(self.conversation_history[-10:])  # Last 10 exchanges
        
        # Add current message
        messages.append({"role": "user", "content": message})
        
        return messages
    
    def _format_tools_for_prompt(self) -> str:
        """Format available tools for the system prompt"""
        if not self.tools:
            return "No tools available"
        
        tool_descriptions = []
        for tool in self.tools:
            tool_descriptions.append(f"- {tool['name']}: {tool['description']}")
        
        return "\n".join(tool_descriptions)
    
    async def stream_response(self, message: str, context: Dict[str, Any] = None) -> AsyncGenerator[str, None]:
        """Stream response from the model"""
        
        async with self.ollama_client as client:
            if not await client.pull_model(self.model):
                raise Exception(f"Failed to load model: {self.model}")
            
            messages = self._build_conversation_context(message, context)
            
            full_response = ""
            
            async for chunk in client.chat(
                model=self.model,
                messages=messages,
                stream=True,
                options={"temperature": 0.7}
            ):
                if chunk.get("message", {}).get("content"):
                    content = chunk["message"]["content"]
                    full_response += content
                    yield content
                
                if chunk.get("done", False):
                    # Update conversation history when complete
                    self.conversation_history.append({"role": "user", "content": message})
                    self.conversation_history.append({"role": "assistant", "content": full_response})

# Docker deployment configuration
OLLAMA_DOCKER_COMPOSE = """
version: '3.8'
services:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    environment:
      - OLLAMA_HOST=0.0.0.0
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]

  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    ports:
      - "3000:8080"
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
    volumes:
      - open_webui_data:/app/backend/data
    depends_on:
      - ollama
    restart: unless-stopped

volumes:
  ollama_data:
  open_webui_data:
"""

# Usage example
async def demo_open_source_agent():
    """Demonstrate open source agent capabilities"""
    
    # Create research agent
    research_agent = OpenSourceAgent(
        name="Open Source Research Assistant",
        instructions="""
        You are a research assistant that helps with:
        - Web search and information gathering
        - Data analysis and interpretation
        - Document summarization
        - Technical explanations
        
        Always provide accurate, helpful responses and cite sources when possible.
        """,
        model="llama3.1:8b"
    )
    
    # Add tools
    await research_agent.add_tool({
        "name": "web_search",
        "description": "Search the web for current information"
    })
    
    # Process queries
    response = await research_agent.process_message(
        "What are the latest developments in open source large language models?"
    )
    
    print(f"Agent Response: {response}")
```

### Cloud Infrastructure Layer: Kubernetes-Based Model Serving

For production deployments, Kubernetes provides scalable, resilient infrastructure for serving open source models.

#### Kubernetes Model Serving Architecture

**Production Model Deployment:**
```yaml
# ollama-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama-server
  namespace: llm-serving
  labels:
    app: ollama-server
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: ollama-server
  template:
    metadata:
      labels:
        app: ollama-server
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
    spec:
      nodeSelector:
        gpu-type: "nvidia-t4"  # Schedule on GPU nodes
      containers:
      - name: ollama
        image: ollama/ollama:latest
        ports:
        - containerPort: 11434
          name: http
        env:
        - name: OLLAMA_HOST
          value: "0.0.0.0:11434"
        - name: OLLAMA_MODELS
          value: "/models"
        - name: OLLAMA_KEEP_ALIVE
          value: "10m"
        resources:
          requests:
            memory: "8Gi"
            cpu: "2"
            nvidia.com/gpu: 1
          limits:
            memory: "16Gi"
            cpu: "4"
            nvidia.com/gpu: 1
        volumeMounts:
        - name: model-storage
          mountPath: /models
        - name: ollama-data
          mountPath: /root/.ollama
        livenessProbe:
          httpGet:
            path: /api/version
            port: 11434
          initialDelaySeconds: 60
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /api/version
            port: 11434
          initialDelaySeconds: 30
          periodSeconds: 10
      # Sidecar for model management
      - name: model-manager
        image: your-registry/model-manager:latest
        env:
        - name: OLLAMA_URL
          value: "http://localhost:11434"
        - name: MODELS_TO_LOAD
          value: "llama3.1:8b,mistral:7b,phi3:mini"
        volumeMounts:
        - name: model-storage
          mountPath: /models
        command: ["/bin/sh"]
        args:
        - -c
        - |
          echo "Loading models..."
          for model in $(echo $MODELS_TO_LOAD | tr ',' ' '); do
            echo "Pulling $model"
            curl -X POST $OLLAMA_URL/api/pull -d "{\"name\":\"$model\"}"
          done
          echo "Models loaded, starting health check loop"
          while true; do
            sleep 300
            curl -f $OLLAMA_URL/api/version || exit 1
          done
      volumes:
      - name: model-storage
        persistentVolumeClaim:
          claimName: ollama-models-pvc
      - name: ollama-data
        emptyDir: {}

---
apiVersion: v1
kind: Service
metadata:
  name: ollama-service
  namespace: llm-serving
  labels:
    app: ollama-server
spec:
  selector:
    app: ollama-server
  ports:
  - port: 80
    targetPort: 11434
    name: http
  type: ClusterIP

---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ollama-models-pvc
  namespace: llm-serving
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 100Gi
  storageClassName: fast-ssd

---
# HPA for scaling based on GPU utilization
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ollama-hpa
  namespace: llm-serving
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ollama-server
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: nvidia.com/gpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: ollama_active_requests
      target:
        type: AverageValue
        averageValue: "5"
```

### Cost Optimization Layer: Efficient Resource Management

Open source LLMs require careful resource management to achieve cost benefits over commercial APIs.

#### Cost-Effective Deployment Strategies

**Multi-Tier Cost Optimization:**
```python
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

class CostOptimizedLLMService:
    """Cost-optimized LLM service with multiple deployment tiers"""
    
    def __init__(self):
        self.local_endpoint = "http://localhost:11434"
        self.cloud_endpoint = "http://ollama-service.llm-serving.svc.cluster.local"
        self.fallback_api = "openai"  # Commercial API as fallback
        
        # Cost tracking
        self.monthly_budget = 1000.0  # USD
        self.current_spend = 0.0
        self.request_count = 0
        
        # Performance tracking
        self.response_times = {}
        self.error_rates = {}
        
    async def get_completion(
        self,
        prompt: str,
        model: str = "llama3.1:8b",
        max_tokens: int = 2000,
        priority: str = "normal"
    ) -> Dict[str, Any]:
        """Get completion with cost optimization"""
        
        start_time = datetime.now()
        
        try:
            # Strategy 1: Try local model first (lowest cost)
            if await self._is_local_available():
                response = await self._get_local_completion(prompt, model, max_tokens)
                cost = self._calculate_local_cost(len(prompt + response.get("content", "")))
                
                await self._update_metrics("local", start_time, True, cost)
                return {
                    "content": response.get("content"),
                    "source": "local",
                    "cost": cost,
                    "tokens": len(prompt + response.get("content", ""))
                }
            
            # Strategy 2: Try cloud-hosted model (medium cost)
            if await self._is_cloud_available():
                response = await self._get_cloud_completion(prompt, model, max_tokens)
                cost = self._calculate_cloud_cost(len(prompt + response.get("content", "")))
                
                await self._update_metrics("cloud", start_time, True, cost)
                return {
                    "content": response.get("content"),
                    "source": "cloud",
                    "cost": cost,
                    "tokens": len(prompt + response.get("content", ""))
                }
            
            # Strategy 3: Fallback to commercial API (highest cost, highest reliability)
            if priority == "high" or self.current_spend < self.monthly_budget * 0.8:
                response = await self._get_commercial_completion(prompt, model, max_tokens)
                cost = self._calculate_commercial_cost(response.get("usage", {}).get("total_tokens", 0))
                
                await self._update_metrics("commercial", start_time, True, cost)
                return {
                    "content": response.get("content"),
                    "source": "commercial",
                    "cost": cost,
                    "tokens": response.get("usage", {}).get("total_tokens", 0)
                }
            
            raise Exception("All LLM services unavailable and budget limit reached")
            
        except Exception as e:
            await self._update_metrics("error", start_time, False, 0)
            raise
    
    async def _is_local_available(self) -> bool:
        """Check if local Ollama instance is available"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.local_endpoint}/api/version",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status == 200
        except:
            return False
    
    async def _is_cloud_available(self) -> bool:
        """Check if cloud-hosted service is available"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.cloud_endpoint}/api/version",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    return response.status == 200
        except:
            return False
    
    async def _get_local_completion(self, prompt: str, model: str, max_tokens: int) -> Dict[str, Any]:
        """Get completion from local Ollama instance"""
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.7
                }
            }
            
            async with session.post(
                f"{self.local_endpoint}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                
                if response.status == 200:
                    result = await response.json()
                    return {
                        "content": result["message"]["content"],
                        "model": model,
                        "source": "local"
                    }
                else:
                    raise Exception(f"Local model error: {response.status}")
    
    def _calculate_local_cost(self, total_tokens: int) -> float:
        """Calculate cost for local processing"""
        # Assume $0.50/hour for local GPU, ~100 tokens/second
        cost_per_token = 0.50 / 3600 / 100  # Rough estimate
        return total_tokens * cost_per_token
    
    def _calculate_cloud_cost(self, total_tokens: int) -> float:
        """Calculate cost for cloud-hosted processing"""
        # Assume $0.80/hour for cloud GPU, ~100 tokens/second
        cost_per_token = 0.80 / 3600 / 100
        return total_tokens * cost_per_token
    
    def _calculate_commercial_cost(self, total_tokens: int) -> float:
        """Calculate cost for commercial API"""
        # OpenAI GPT-4 pricing: ~$0.03/1K tokens
        return (total_tokens / 1000) * 0.03
    
    async def _update_metrics(self, source: str, start_time: datetime, success: bool, cost: float):
        """Update performance and cost metrics"""
        end_time = datetime.now()
        response_time = (end_time - start_time).total_seconds()
        
        # Update response times
        if source not in self.response_times:
            self.response_times[source] = []
        self.response_times[source].append(response_time)
        
        # Update error rates
        if source not in self.error_rates:
            self.error_rates[source] = {"total": 0, "errors": 0}
        self.error_rates[source]["total"] += 1
        if not success:
            self.error_rates[source]["errors"] += 1
        
        # Update costs
        self.current_spend += cost
        self.request_count += 1
        
        # Log metrics
        print(f"📊 {source.upper()}: {response_time:.2f}s, ${cost:.4f}, Success: {success}")
    
    async def get_cost_report(self) -> Dict[str, Any]:
        """Generate cost and performance report"""
        return {
            "total_spend": self.current_spend,
            "total_requests": self.request_count,
            "average_cost_per_request": self.current_spend / max(self.request_count, 1),
            "budget_utilization": (self.current_spend / self.monthly_budget) * 100,
            "response_times": {
                source: {
                    "average": sum(times) / len(times),
                    "min": min(times),
                    "max": max(times)
                }
                for source, times in self.response_times.items()
                if times
            },
            "error_rates": {
                source: (data["errors"] / data["total"]) * 100
                for source, data in self.error_rates.items()
                if data["total"] > 0
            }
        }

class OpenSourceAgentBuilder:
    """Builder for creating agents with open source LLMs"""
    
    def __init__(self, llm_service: CostOptimizedLLMService):
        self.llm_service = llm_service
        
    async def create_research_agent(self, specialization: str = "general") -> 'OpenSourceAgent':
        """Create a research agent optimized for specific domains"""
        
        # Select optimal model based on specialization
        model_mapping = {
            "general": "llama3.1:8b",
            "code": "codellama:13b",
            "math": "mathstral:7b",
            "science": "llama3.1:70b",  # Larger model for complex reasoning
            "creative": "mistral:7b"
        }
        
        model = model_mapping.get(specialization, "llama3.1:8b")
        
        instructions = f"""
        You are a specialized research agent focusing on {specialization}.
        Your capabilities include:
        - Information gathering and analysis
        - Critical thinking and reasoning
        - Synthesis of complex information
        - Tool integration for enhanced functionality
        
        Always provide accurate, well-reasoned responses based on your training
        and available tools. Be transparent about your limitations.
        """
        
        agent = OpenSourceAgent(
            name=f"{specialization.title()} Research Agent",
            instructions=instructions,
            model=model
        )
        
        # Add domain-specific tools
        if specialization == "code":
            await agent.add_tool({
                "name": "code_analysis",
                "description": "Analyze code for bugs, performance, and best practices"
            })
        elif specialization == "math":
            await agent.add_tool({
                "name": "calculation",
                "description": "Perform complex mathematical calculations"
            })
        
        return agent
    
    async def create_multi_agent_system(self, domain: str) -> Dict[str, 'OpenSourceAgent']:
        """Create a coordinated multi-agent system for a specific domain"""
        
        agents = {}
        
        if domain == "research":
            agents["gatherer"] = await self.create_research_agent("general")
            agents["analyzer"] = await self.create_research_agent("science") 
            agents["synthesizer"] = await self.create_research_agent("creative")
            
        elif domain == "software_development":
            agents["architect"] = await self.create_research_agent("code")
            agents["developer"] = await self.create_research_agent("code")
            agents["tester"] = await self.create_research_agent("code")
            agents["reviewer"] = await self.create_research_agent("general")
            
        return agents

# Infrastructure automation
class LLMInfrastructureManager:
    """Manage LLM infrastructure deployment and scaling"""
    
    def __init__(self, k8s_namespace: str = "llm-serving"):
        self.namespace = k8s_namespace
        self.models_cache = {}
        
    async def deploy_model_service(
        self, 
        model_name: str,
        replicas: int = 2,
        gpu_type: str = "nvidia-t4"
    ) -> bool:
        """Deploy a specific model as a scalable service"""
        
        # Generate Kubernetes manifests
        deployment_manifest = self._generate_deployment_manifest(
            model_name, replicas, gpu_type
        )
        
        service_manifest = self._generate_service_manifest(model_name)
        
        hpa_manifest = self._generate_hpa_manifest(model_name)
        
        # Apply manifests (simplified - in practice use kubernetes client)
        success = await self._apply_kubernetes_manifests([
            deployment_manifest,
            service_manifest, 
            hpa_manifest
        ])
        
        if success:
            print(f"✅ Deployed {model_name} service with {replicas} replicas")
            return True
        else:
            print(f"❌ Failed to deploy {model_name} service")
            return False
    
    def _generate_deployment_manifest(
        self, 
        model_name: str, 
        replicas: int,
        gpu_type: str
    ) -> Dict[str, Any]:
        """Generate Kubernetes deployment manifest"""
        
        safe_name = model_name.replace(":", "-").replace(".", "-")
        
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": f"ollama-{safe_name}",
                "namespace": self.namespace,
                "labels": {
                    "app": f"ollama-{safe_name}",
                    "model": model_name
                }
            },
            "spec": {
                "replicas": replicas,
                "selector": {
                    "matchLabels": {
                        "app": f"ollama-{safe_name}"
                    }
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": f"ollama-{safe_name}"
                        }
                    },
                    "spec": {
                        "nodeSelector": {
                            "gpu-type": gpu_type
                        },
                        "containers": [
                            {
                                "name": "ollama",
                                "image": "ollama/ollama:latest",
                                "ports": [{"containerPort": 11434}],
                                "env": [
                                    {"name": "OLLAMA_HOST", "value": "0.0.0.0:11434"},
                                    {"name": "OLLAMA_KEEP_ALIVE", "value": "10m"}
                                ],
                                "resources": {
                                    "requests": {
                                        "memory": "8Gi",
                                        "cpu": "2",
                                        "nvidia.com/gpu": 1
                                    },
                                    "limits": {
                                        "memory": "16Gi", 
                                        "cpu": "4",
                                        "nvidia.com/gpu": 1
                                    }
                                },
                                "readinessProbe": {
                                    "httpGet": {
                                        "path": "/api/version",
                                        "port": 11434
                                    },
                                    "initialDelaySeconds": 30,
                                    "periodSeconds": 10
                                }
                            }
                        ],
                        "initContainers": [
                            {
                                "name": "model-loader",
                                "image": "curlimages/curl:latest",
                                "command": ["/bin/sh"],
                                "args": [
                                    "-c",
                                    f"until curl -f http://localhost:11434/api/version; do sleep 5; done; curl -X POST http://localhost:11434/api/pull -d '{{\"name\":\"{model_name}\"}}'"
                                ]
                            }
                        ]
                    }
                }
            }
        }
```

### Performance Optimization Layer: Model Quantization and Efficiency

Optimizing open source models for production requires advanced quantization and serving techniques.

#### Advanced Model Optimization

**Quantization and Serving Optimization:**
```python
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from typing import Optional
import time

class OptimizedModelServer:
    """Optimized model server with quantization and caching"""
    
    def __init__(
        self,
        model_name: str,
        quantization_config: Optional[Dict[str, Any]] = None,
        device: str = "auto"
    ):
        self.model_name = model_name
        self.device = device
        self.model = None
        self.tokenizer = None
        self.quantization_config = quantization_config or self._default_quantization_config()
        
        # Caching
        self.response_cache = {}
        self.cache_max_size = 1000
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Performance tracking
        self.request_count = 0
        self.total_inference_time = 0.0
        
    def _default_quantization_config(self) -> Dict[str, Any]:
        """Default quantization configuration for memory efficiency"""
        return {
            "load_in_4bit": True,
            "bnb_4bit_use_double_quant": True,
            "bnb_4bit_quant_type": "nf4",
            "bnb_4bit_compute_dtype": torch.bfloat16
        }
    
    async def initialize(self):
        """Initialize the model with optimizations"""
        print(f"🚀 Initializing optimized model: {self.model_name}")
        
        # Configure quantization
        quantization_config = BitsAndBytesConfig(**self.quantization_config)
        
        # Load tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            trust_remote_code=True
        )
        
        # Load model with quantization
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            quantization_config=quantization_config,
            device_map=self.device,
            trust_remote_code=True,
            torch_dtype=torch.bfloat16
        )
        
        # Enable compilation for faster inference (PyTorch 2.0+)
        if hasattr(torch, 'compile'):
            self.model = torch.compile(self.model, mode="reduce-overhead")
        
        print(f"✅ Model initialized. Memory usage: {self._get_memory_usage():.2f} GB")
    
    async def generate(
        self,
        prompt: str,
        max_new_tokens: int = 512,
        temperature: float = 0.7,
        do_sample: bool = True,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Generate response with optimizations"""
        
        # Check cache first
        if use_cache:
            cache_key = hash(f"{prompt}_{max_new_tokens}_{temperature}")
            if cache_key in self.response_cache:
                self.cache_hits += 1
                return {
                    "response": self.response_cache[cache_key],
                    "cached": True,
                    "generation_time": 0.0
                }
        
        start_time = time.time()
        
        # Tokenize input
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        
        # Generate with optimizations
        with torch.no_grad():
            with torch.cuda.amp.autocast():  # Mixed precision for speed
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    do_sample=do_sample,
                    pad_token_id=self.tokenizer.eos_token_id,
                    use_cache=True,  # Enable KV cache
                    repetition_penalty=1.1
                )
        
        # Decode response
        generated_tokens = outputs[0][inputs['input_ids'].shape[1]:]
        response = self.tokenizer.decode(generated_tokens, skip_special_tokens=True)
        
        generation_time = time.time() - start_time
        
        # Update metrics
        self.request_count += 1
        self.total_inference_time += generation_time
        
        # Cache response
        if use_cache and len(self.response_cache) < self.cache_max_size:
            cache_key = hash(f"{prompt}_{max_new_tokens}_{temperature}")
            self.response_cache[cache_key] = response
            self.cache_misses += 1
        
        return {
            "response": response,
            "cached": False,
            "generation_time": generation_time,
            "tokens_per_second": len(generated_tokens) / generation_time
        }
    
    def _get_memory_usage(self) -> float:
        """Get current GPU memory usage in GB"""
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() / (1024**3)
        return 0.0
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        avg_inference_time = self.total_inference_time / max(self.request_count, 1)
        cache_hit_rate = self.cache_hits / max(self.cache_hits + self.cache_misses, 1)
        
        return {
            "total_requests": self.request_count,
            "average_inference_time": avg_inference_time,
            "cache_hit_rate": cache_hit_rate * 100,
            "memory_usage_gb": self._get_memory_usage(),
            "requests_per_second": 1.0 / avg_inference_time if avg_inference_time > 0 else 0
        }

# Model selection and benchmarking
class ModelBenchmark:
    """Benchmark different models for agent use cases"""
    
    AGENT_OPTIMIZED_MODELS = {
        "small": {
            "name": "microsoft/Phi-3-mini-4k-instruct",
            "parameters": "3.8B",
            "memory_gb": 4,
            "use_cases": ["simple reasoning", "tool calling", "chat"]
        },
        "medium": {
            "name": "meta-llama/Llama-3.1-8B-Instruct", 
            "parameters": "8B",
            "memory_gb": 8,
            "use_cases": ["complex reasoning", "research", "analysis"]
        },
        "large": {
            "name": "meta-llama/Llama-3.1-70B-Instruct",
            "parameters": "70B", 
            "memory_gb": 140,
            "use_cases": ["expert reasoning", "scientific analysis", "code generation"]
        },
        "code": {
            "name": "codellama/CodeLlama-13b-Instruct-hf",
            "parameters": "13B",
            "memory_gb": 26,
            "use_cases": ["code generation", "debugging", "architecture"]
        }
    }
    
    @classmethod
    async def benchmark_models(cls, test_prompts: List[str]) -> Dict[str, Dict[str, Any]]:
        """Benchmark multiple models on test prompts"""
        
        results = {}
        
        for size, model_info in cls.AGENT_OPTIMIZED_MODELS.items():
            print(f"🧪 Benchmarking {size} model: {model_info['name']}")
            
            try:
                server = OptimizedModelServer(model_info["name"])
                await server.initialize()
                
                # Run benchmark
                benchmark_results = []
                for prompt in test_prompts:
                    result = await server.generate(prompt, max_new_tokens=256)
                    benchmark_results.append(result)
                
                # Calculate averages
                avg_time = sum(r["generation_time"] for r in benchmark_results) / len(benchmark_results)
                avg_tokens_per_sec = sum(r["tokens_per_second"] for r in benchmark_results) / len(benchmark_results)
                
                results[size] = {
                    "model_info": model_info,
                    "average_generation_time": avg_time,
                    "average_tokens_per_second": avg_tokens_per_sec,
                    "memory_usage_gb": server.get_performance_stats()["memory_usage_gb"]
                }
                
            except Exception as e:
                results[size] = {
                    "model_info": model_info,
                    "error": str(e)
                }
        
        return results

# Usage examples
async def deploy_production_llm_infrastructure():
    """Deploy production-ready open source LLM infrastructure"""
    
    # Initialize cost-optimized service
    llm_service = CostOptimizedLLMService()
    
    # Create agent builder
    agent_builder = OpenSourceAgentBuilder(llm_service)
    
    # Deploy specialized agents
    research_agents = await agent_builder.create_multi_agent_system("research")
    
    # Deploy infrastructure
    infra_manager = LLMInfrastructureManager()
    
    # Deploy multiple model services
    await infra_manager.deploy_model_service("llama3.1:8b", replicas=3)
    await infra_manager.deploy_model_service("mistral:7b", replicas=2) 
    await infra_manager.deploy_model_service("codellama:13b", replicas=1)
    
    print("🎉 Production LLM infrastructure deployed successfully")
    
    return llm_service, research_agents
```

---

## Mental Model: Thinking Infrastructure vs API

### Build the Mental Model: Owning vs Renting Intelligence

Think of the choice between open source LLMs and commercial APIs like **owning vs renting a car**:

**Commercial APIs (Renting)**:
- **Low upfront cost**: Pay per use
- **No maintenance**: Provider handles updates
- **Limited control**: Can't modify or customize
- **Usage restrictions**: Rate limits and terms of service

**Open Source LLMs (Owning)**:
- **High upfront cost**: Infrastructure investment
- **Full maintenance**: You manage updates and operations
- **Complete control**: Customize and fine-tune as needed
- **Unlimited usage**: No restrictions on how you use the models

### Why It's Designed This Way: Balancing Control, Cost, and Capability

The choice depends on your specific requirements:

1. **Scale**: High-volume applications benefit from self-hosting
2. **Privacy**: Sensitive data requires local processing
3. **Customization**: Domain-specific needs require fine-tuning
4. **Cost**: Large-scale operations can be cheaper with self-hosting
5. **Reliability**: Critical applications need infrastructure control

### Further Exploration: Building Hybrid LLM Strategies

**Immediate Practice:**
1. Deploy Ollama locally and experiment with different models
2. Set up Kubernetes-based model serving for production
3. Implement cost optimization with fallback strategies
4. Benchmark models for your specific agent use cases

**Design Challenge:**
Create a "hybrid intelligence system" that:
- Uses local models for routine tasks
- Falls back to commercial APIs for complex reasoning
- Optimizes costs based on request patterns
- Maintains data privacy through intelligent routing

**Advanced Exploration:**
- How would you implement model fine-tuning for specific agent domains?
- What patterns support A/B testing between different models?
- How could you create a model marketplace for specialized capabilities?
- What techniques enable real-time model swapping without downtime?

---

*Open source LLMs provide the foundation for truly autonomous agentic AI systems by eliminating dependencies on external APIs while enabling complete control over intelligence infrastructure. Understanding these deployment patterns, optimization techniques, and cost management strategies is essential for building scalable, cost-effective, and privacy-preserving agent systems.*