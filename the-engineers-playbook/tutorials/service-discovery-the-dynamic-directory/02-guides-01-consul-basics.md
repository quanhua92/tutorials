# Consul Basics: Your First Service Discovery Experience

## Prerequisites

- Docker installed on your machine
- Basic understanding of HTTP and JSON
- Familiarity with command-line tools
- Optional: `jq` for JSON parsing

## What is Consul?

Consul is HashiCorp's service discovery and configuration tool. It provides:
- **Service registration and discovery**
- **Health checking**
- **Key-value storage**
- **Multi-datacenter support**

```mermaid
graph TD
    subgraph "Consul Architecture"
        subgraph "Core Components"
            SD[Service Discovery]
            HC[Health Checking]
            KV[Key-Value Store]
            MDC[Multi-Datacenter]
        end
        
        subgraph "Consul Agent"
            CA[Consul Agent]
            API[HTTP API]
            DNS[DNS Interface]
            UI[Web UI]
        end
        
        subgraph "Client Integration"
            S1[Service A]
            S2[Service B]
            S3[Service C]
            APP[Application]
        end
        
        CA --> SD
        CA --> HC
        CA --> KV
        CA --> MDC
        
        CA --> API
        CA --> DNS
        CA --> UI
        
        S1 --> API
        S2 --> API
        S3 --> API
        APP --> API
        APP --> DNS
        
        style CA fill:#e1f5fe
        style API fill:#e8f5e8
        style DNS fill:#e8f5e8
        style UI fill:#e8f5e8
    end
```

Think of Consul as a **digital receptionist** for your services—it knows where everyone is and can direct traffic accordingly.

### The Digital Receptionist Analogy

```mermaid
graph TD
    subgraph "Traditional Office"
        R[Receptionist]
        D[Directory Book]
        V[Visitor]
        E1[Employee A - Room 101]
        E2[Employee B - Room 102]
        E3[Employee C - Room 103]
        
        V --> R
        R --> D
        R --> E1
        R --> E2
        R --> E3
        
        style R fill:#fff3e0
    end
    
    subgraph "Consul Service Discovery"
        C[Consul Agent]
        SR[Service Registry]
        CL[Client Application]
        S1[Service A - 192.168.1.45:8080]
        S2[Service B - 192.168.1.46:8080]
        S3[Service C - 192.168.1.47:8080]
        
        CL --> C
        C --> SR
        C --> S1
        C --> S2
        C --> S3
        
        style C fill:#e8f5e8
    end
```

## Setting Up Consul

### 1. Start Consul in Development Mode

```mermaid
sequenceDiagram
    participant D as Developer
    participant Docker as Docker
    participant C as Consul Container
    participant B as Browser
    
    Note over D,C: Consul Setup Process
    
    D->>Docker: docker run consul:latest
    Docker->>C: Start Consul agent
    C->>C: Initialize in dev mode
    C->>C: Start HTTP API (8500)
    C->>C: Start DNS service (8600)
    C->>C: Start Web UI
    
    D->>C: curl http://localhost:8500/v1/status/leader
    C->>D: Return leader info
    
    D->>B: Open http://localhost:8500
    B->>C: Request Web UI
    C->>B: Serve Web UI
```

```bash
# Pull and run Consul in development mode
docker run -d --name consul-dev \
  -p 8500:8500 \
  -p 8600:8600/udp \
  consul:latest agent -dev -client=0.0.0.0

# Verify it's running
curl http://localhost:8500/v1/status/leader
```

**Consul Development Mode Setup**:

```mermaid
graph TD
    subgraph "Consul Container"
        subgraph "Network Ports"
            P1[8500 - HTTP API]
            P2[8600 - DNS]
        end
        
        subgraph "Core Services"
            API[HTTP API Server]
            DNS[DNS Server]
            UI[Web UI]
            Agent[Consul Agent]
        end
        
        subgraph "Storage"
            Mem[In-Memory Storage<br/>(Dev Mode Only)]
        end
        
        Agent --> API
        Agent --> DNS
        Agent --> UI
        Agent --> Mem
        
        API --> P1
        DNS --> P2
        
        style Agent fill:#e1f5fe
        style Mem fill:#fff3e0
    end
    
    subgraph "Your Machine"
        Browser[Browser<br/>http://localhost:8500]
        CLI[Command Line<br/>curl/API calls]
        Apps[Your Applications]
    end
    
    Browser --> P1
    CLI --> P1
    Apps --> P1
    Apps --> P2
```

This starts Consul with:
- **Web UI**: http://localhost:8500
- **HTTP API**: Port 8500
- **DNS**: Port 8600

### 2. Explore the Web UI

```mermaid
graph TD
    subgraph "Consul Web UI Components"
        subgraph "Navigation"
            N1[Services]
            N2[Nodes]
            N3[Key/Value]
            N4[Intentions]
            N5[Access Control]
        end
        
        subgraph "Services View"
            S1[Service List]
            S2[Service Details]
            S3[Health Checks]
            S4[Service Instances]
        end
        
        subgraph "Nodes View"
            ND1[Node List]
            ND2[Node Details]
            ND3[Node Health]
            ND4[Node Services]
        end
        
        subgraph "Key/Value View"
            KV1[Key Browser]
            KV2[Value Editor]
            KV3[Folder Structure]
        end
        
        N1 --> S1
        N1 --> S2
        N1 --> S3
        N1 --> S4
        
        N2 --> ND1
        N2 --> ND2
        N2 --> ND3
        N2 --> ND4
        
        N3 --> KV1
        N3 --> KV2
        N3 --> KV3
        
        style N1 fill:#e8f5e8
        style N2 fill:#e8f5e8
        style N3 fill:#e8f5e8
        style N4 fill:#e8f5e8
    end
```

Open http://localhost:8500 in your browser. You'll see:
- **Services**: Currently empty (we'll add services here)
- **Nodes**: Your local Consul agent
- **Key/Value**: Configuration storage
- **Intentions**: Service-to-service permissions

## Registering Your First Service

### The Service Registration Flow

```mermaid
sequenceDiagram
    participant S as Service
    participant C as Consul Agent
    participant R as Registry
    participant H as Health Checker
    participant UI as Web UI
    
    Note over S,UI: Service Registration Process
    
    S->>S: Start service on port 8080
    S->>C: Register service via HTTP API
    C->>R: Store service information
    C->>H: Start health monitoring
    
    loop Health Monitoring
        H->>S: GET /health
        S->>H: 200 OK (healthy)
        H->>R: Update service status
    end
    
    Note over UI: Service now visible in Web UI
    
    UI->>R: Query services
    R->>UI: Return service list
```

### 1. Create a Simple Web Service

Let's create a basic web service that we'll register with Consul:

```mermaid
graph TD
    subgraph "Our Demo Service"
        subgraph "HTTP Endpoints"
            E1[GET / - Main page]
            E2[GET /health - Health check]
        end
        
        subgraph "Service Features"
            F1[Simple HTTP server]
            F2[Health check endpoint]
            F3[JSON responses]
            F4[Python implementation]
        end
        
        subgraph "Consul Integration"
            I1[Service registration]
            I2[Health check configuration]
            I3[Metadata provision]
        end
        
        E1 --> F1
        E2 --> F2
        F2 --> F3
        F1 --> F4
        
        F1 --> I1
        F2 --> I2
        F4 --> I3
        
        style E2 fill:#e8f5e8
        style I2 fill:#e8f5e8
    end
```

```bash
# Create a simple HTTP server
mkdir consul-demo && cd consul-demo

# Create a simple Python web server
cat > web_service.py << 'EOF'
#!/usr/bin/env python3
import http.server
import socketserver
import json
import threading
import time

class HealthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            health_data = {
                'status': 'healthy',
                'service': 'web-service',
                'timestamp': time.time()
            }
            self.wfile.write(json.dumps(health_data).encode())
        elif self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h1>Hello from Web Service!</h1>')
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    PORT = 8080
    with socketserver.TCPServer(("", PORT), HealthHandler) as httpd:
        print(f"Server running on port {PORT}")
        httpd.serve_forever()
EOF

# Make it executable
chmod +x web_service.py

# Run the service in the background
python3 web_service.py &
SERVICE_PID=$!

# Test the service
curl http://localhost:8080/health
```

### 2. Register the Service with Consul

```mermaid
sequenceDiagram
    participant D as Developer
    participant C as Consul API
    participant R as Registry
    participant H as Health Checker
    participant S as Service
    
    Note over D,S: Service Registration
    
    D->>C: POST /v1/agent/service/register
    Note over D: {
      "ID": "web-service-1",
      "Name": "web-service",
      "Address": "localhost",
      "Port": 8080,
      "Tags": ["web", "python", "v1.0"],
      "Check": {
        "HTTP": "http://localhost:8080/health",
        "Interval": "10s"
      }
    }
    
    C->>R: Store service registration
    C->>H: Configure health check
    C->>D: 200 OK - Registration successful
    
    Note over H,S: Health Check Setup
    
    H->>S: GET /health (every 10s)
    S->>H: 200 OK + health status
    H->>R: Update service health
```

Now let's register our web service with Consul:

```bash
# Register the service
curl -X PUT http://localhost:8500/v1/agent/service/register \
  -H "Content-Type: application/json" \
  -d '{
    "ID": "web-service-1",
    "Name": "web-service",
    "Address": "localhost",
    "Port": 8080,
    "Tags": ["web", "python", "v1.0"],
    "Meta": {
      "version": "1.0.0",
      "environment": "development"
    },
    "Check": {
      "HTTP": "http://localhost:8080/health",
      "Interval": "10s",
      "Timeout": "3s"
    }
  }'
```

**Service Registration Breakdown**:

```mermaid
graph TD
    subgraph "Service Registration JSON"
        subgraph "Identity"
            ID[ID: web-service-1]
            Name[Name: web-service]
            Addr[Address: localhost]
            Port[Port: 8080]
        end
        
        subgraph "Classification"
            Tags[Tags: web, python, v1.0]
            Meta[Meta: version, environment]
        end
        
        subgraph "Health Check"
            HTTP[HTTP: /health endpoint]
            Interval[Interval: 10s]
            Timeout[Timeout: 3s]
        end
        
        subgraph "Result"
            Reg[Service Registered]
            Mon[Health Monitoring Started]
            Disc[Service Discoverable]
        end
        
        ID --> Reg
        Name --> Reg
        Addr --> Reg
        Port --> Reg
        
        Tags --> Disc
        Meta --> Disc
        
        HTTP --> Mon
        Interval --> Mon
        Timeout --> Mon
        
        Reg --> Disc
        Mon --> Disc
        
        style HTTP fill:#e8f5e8
        style Mon fill:#e8f5e8
        style Disc fill:#e1f5fe
    end
```

### 3. Verify the Registration

```bash
# List all services
curl http://localhost:8500/v1/agent/services | jq

# Get specific service details
curl http://localhost:8500/v1/health/service/web-service | jq

# Check the web UI
echo "Visit http://localhost:8500 to see your service!"
```

## Understanding Health Checks

### Health Check Architecture

```mermaid
graph TD
    subgraph "Consul Health Check System"
        subgraph "Health Check Types"
            HTTP[HTTP Check]
            TCP[TCP Check]
            Script[Script Check]
            TTL[TTL Check]
        end
        
        subgraph "Health Check Engine"
            Scheduler[Check Scheduler]
            Executor[Check Executor]
            ResultProcessor[Result Processor]
        end
        
        subgraph "Service Status"
            Passing[Passing ✅]
            Warning[Warning ⚠️]
            Critical[Critical ❌]
        end
        
        subgraph "Actions"
            Include[Include in Discovery]
            Exclude[Exclude from Discovery]
            Alert[Generate Alerts]
        end
        
        HTTP --> Scheduler
        TCP --> Scheduler
        Script --> Scheduler
        TTL --> Scheduler
        
        Scheduler --> Executor
        Executor --> ResultProcessor
        
        ResultProcessor --> Passing
        ResultProcessor --> Warning
        ResultProcessor --> Critical
        
        Passing --> Include
        Warning --> Include
        Critical --> Exclude
        Critical --> Alert
        
        style HTTP fill:#e8f5e8
        style Passing fill:#e8f5e8
        style Include fill:#e8f5e8
        style Critical fill:#ffebee
        style Exclude fill:#ffebee
    end
```

### 1. Health Check Types

Consul supports several health check types:

```mermaid
graph TD
    subgraph "Health Check Types Comparison"
        subgraph "HTTP Health Check"
            H1[Consul Agent] --> H2[HTTP GET /health]
            H2 --> H3[Service Response]
            H3 --> H4{Status Code}
            H4 -->|200-299| H5[✅ Healthy]
            H4 -->|400-599| H6[❌ Unhealthy]
            H4 -->|Timeout| H7[❌ Unhealthy]
            
            HN["Best for: Web services, REST APIs"]
        end
        
        subgraph "TCP Health Check"
            T1[Consul Agent] --> T2[TCP Connect :8080]
            T2 --> T3{Connection}
            T3 -->|Success| T4[✅ Healthy]
            T3 -->|Failure| T5[❌ Unhealthy]
            
            TN["Best for: Databases, low-level services"]
        end
        
        subgraph "Script Health Check"
            S1[Consul Agent] --> S2[Execute Script]
            S2 --> S3{Exit Code}
            S3 -->|0| S4[✅ Healthy]
            S3 -->|Non-zero| S5[❌ Unhealthy]
            
            SN["Best for: Custom logic, complex checks"]
        end
        
        subgraph "TTL Health Check"
            TT1[Service] --> TT2[Update TTL]
            TT2 --> TT3{TTL Expired?}
            TT3 -->|No| TT4[✅ Healthy]
            TT3 -->|Yes| TT5[❌ Unhealthy]
            
            TTN["Best for: Self-reporting services"]
        end
    end
```

```bash
# HTTP health check (what we used)
curl -X PUT http://localhost:8500/v1/agent/check/register \
  -H "Content-Type: application/json" \
  -d '{
    "ID": "web-service-http",
    "Name": "Web Service HTTP Check",
    "ServiceID": "web-service-1",
    "HTTP": "http://localhost:8080/health",
    "Interval": "10s",
    "Timeout": "3s"
  }'

# TCP health check
curl -X PUT http://localhost:8500/v1/agent/check/register \
  -H "Content-Type: application/json" \
  -d '{
    "ID": "web-service-tcp",
    "Name": "Web Service TCP Check",
    "ServiceID": "web-service-1",
    "TCP": "localhost:8080",
    "Interval": "10s",
    "Timeout": "3s"
  }'
```

### 2. Health Check States

```bash
# Check current health status
curl http://localhost:8500/v1/health/checks/web-service | jq

# Manually pass/fail a check
curl -X PUT http://localhost:8500/v1/agent/check/pass/web-service-http
curl -X PUT http://localhost:8500/v1/agent/check/fail/web-service-http
```

## Service Discovery in Action

### The Discovery Process

```mermaid
sequenceDiagram
    participant C as Client
    participant CA as Consul API
    participant R as Registry
    participant S1 as Service Instance 1
    participant S2 as Service Instance 2
    participant S3 as Service Instance 3
    
    Note over C,S3: Service Discovery Flow
    
    C->>CA: GET /v1/health/service/web-service
    CA->>R: Query service instances
    R->>CA: Return all instances
    
    Note over CA: Filter by health status
    CA->>CA: Check health status
    CA->>C: Return healthy instances
    
    Note over C: Client selects instance
    C->>C: Apply load balancing
    C->>S2: Make request to selected instance
    S2->>C: Response
    
    Note over C,S3: Discovery with filters
    
    C->>CA: GET /v1/health/service/web-service?tag=production
    CA->>R: Query with tag filter
    R->>CA: Return filtered instances
    CA->>C: Return matching instances
```

### 1. Discovering Services

```mermaid
graph TD
    subgraph "Service Discovery Query Types"
        subgraph "Basic Discovery"
            Q1["GET /v1/health/service/web-service"]
            Q1 --> R1["All registered instances"]
        end
        
        subgraph "Health-Filtered Discovery"
            Q2["GET /v1/health/service/web-service?passing=true"]
            Q2 --> R2["Only healthy instances"]
        end
        
        subgraph "Tag-Filtered Discovery"
            Q3["GET /v1/health/service/web-service?tag=production"]
            Q3 --> R3["Instances with 'production' tag"]
        end
        
        subgraph "Multi-Filter Discovery"
            Q4["GET /v1/health/service/web-service?tag=web&passing=true"]
            Q4 --> R4["Healthy instances with 'web' tag"]
        end
        
        subgraph "Datacenter Discovery"
            Q5["GET /v1/health/service/web-service?dc=us-east-1"]
            Q5 --> R5["Instances in specific datacenter"]
        end
        
        style Q2 fill:#e8f5e8
        style R2 fill:#e8f5e8
        style Q4 fill:#e1f5fe
        style R4 fill:#e1f5fe
    end
```

```bash
# Find all instances of web-service
curl http://localhost:8500/v1/health/service/web-service | jq

# Find only healthy instances
curl http://localhost:8500/v1/health/service/web-service?passing=true | jq

# Find services with specific tags
curl http://localhost:8500/v1/health/service/web-service?tag=web | jq

# Combine filters
curl "http://localhost:8500/v1/health/service/web-service?tag=production&passing=true" | jq
```

### 2. Create a Discovery Client

Let's create a simple client that discovers and connects to services:

```bash
cat > discovery_client.py << 'EOF'
#!/usr/bin/env python3
import requests
import json
import random
import time

class ConsulDiscoveryClient:
    def __init__(self, consul_host='localhost', consul_port=8500):
        self.consul_url = f"http://{consul_host}:{consul_port}"
    
    def discover_service(self, service_name, healthy_only=True):
        """Discover instances of a service"""
        url = f"{self.consul_url}/v1/health/service/{service_name}"
        if healthy_only:
            url += "?passing=true"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            services = response.json()
            
            return [{
                'id': service['Service']['ID'],
                'address': service['Service']['Address'],
                'port': service['Service']['Port'],
                'tags': service['Service']['Tags'],
                'healthy': all(check['Status'] == 'passing' 
                             for check in service['Checks'])
            } for service in services]
        except requests.exceptions.RequestException as e:
            print(f"Error discovering service: {e}")
            return []
    
    def get_service_instance(self, service_name):
        """Get a single service instance using round-robin"""
        instances = self.discover_service(service_name)
        if not instances:
            return None
        
        # Simple random selection (in real systems, use proper load balancing)
        return random.choice(instances)
    
    def make_request(self, service_name, path="/"):
        """Make a request to a service instance"""
        instance = self.get_service_instance(service_name)
        if not instance:
            return None
        
        url = f"http://{instance['address']}:{instance['port']}{path}"
        try:
            response = requests.get(url)
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"Error making request to {url}: {e}")
            return None

# Example usage
if __name__ == '__main__':
    client = ConsulDiscoveryClient()
    
    # Discover web-service instances
    print("Discovering web-service instances...")
    instances = client.discover_service('web-service')
    print(f"Found {len(instances)} instances:")
    for instance in instances:
        print(f"  - {instance['id']}: {instance['address']}:{instance['port']}")
    
    # Make requests to the service
    print("\nMaking requests to the service...")
    for i in range(5):
        response = client.make_request('web-service', '/')
        if response:
            print(f"Request {i+1}: {response[:50]}...")
        time.sleep(1)
EOF

# Make it executable
chmod +x discovery_client.py

# Run the discovery client
python3 discovery_client.py
```

## Scaling with Multiple Instances

### Load Balancing and High Availability

```mermaid
graph TD
    subgraph "Single Instance (Before)"
        C1[Client] --> S1[web-service-1<br/>:8080]
        
        N1["❌ Single point of failure<br/>❌ No load distribution<br/>❌ Limited capacity"]
    end
    
    subgraph "Multiple Instances (After)"
        C2[Client] --> LB[Load Balancer Logic]
        LB --> S2[web-service-1<br/>:8080]
        LB --> S3[web-service-2<br/>:8081]
        LB --> S4[web-service-3<br/>:8082]
        
        N2["✅ High availability<br/>✅ Load distribution<br/>✅ Increased capacity"]
    end
    
    style S1 fill:#ffebee
    style S2 fill:#e8f5e8
    style S3 fill:#e8f5e8
    style S4 fill:#e8f5e8
    style LB fill:#e1f5fe
```

### 1. Register Multiple Service Instances

```mermaid
sequenceDiagram
    participant D as Developer
    participant S1 as Service Instance 1
    participant S2 as Service Instance 2
    participant S3 as Service Instance 3
    participant C as Consul
    
    Note over D,C: Scaling Up Services
    
    D->>S1: Start service on port 8080
    S1->>C: Register as web-service-1
    
    D->>S2: Start service on port 8081
    S2->>C: Register as web-service-2
    
    D->>S3: Start service on port 8082
    S3->>C: Register as web-service-3
    
    Note over C: All instances now discoverable
    
    C->>C: Health check all instances
    C->>S1: GET /health
    C->>S2: GET /health
    C->>S3: GET /health
    
    S1->>C: 200 OK
    S2->>C: 200 OK
    S3->>C: 200 OK
    
    Note over C: All instances healthy and available
```

```bash
# Start additional service instances
python3 web_service.py &
SERVICE_PID_2=$!

# Register second instance (on different port)
curl -X PUT http://localhost:8500/v1/agent/service/register \
  -H "Content-Type: application/json" \
  -d '{
    "ID": "web-service-2",
    "Name": "web-service",
    "Address": "localhost",
    "Port": 8081,
    "Tags": ["web", "python", "v1.0"],
    "Meta": {
      "version": "1.0.0",
      "environment": "development"
    },
    "Check": {
      "HTTP": "http://localhost:8081/health",
      "Interval": "10s",
      "Timeout": "3s"
    }
  }'
```

### 2. Test Load Distribution

```bash
# Run the discovery client again
python3 discovery_client.py

# You should see requests distributed across both instances
```

## Service Metadata and Tagging

### 1. Advanced Service Registration

```bash
# Register a service with rich metadata
curl -X PUT http://localhost:8500/v1/agent/service/register \
  -H "Content-Type: application/json" \
  -d '{
    "ID": "user-service-1",
    "Name": "user-service",
    "Address": "localhost",
    "Port": 9090,
    "Tags": ["api", "user", "v2.0", "production"],
    "Meta": {
      "version": "2.0.0",
      "environment": "production",
      "team": "user-experience",
      "capabilities": "read,write,delete",
      "protocol": "http"
    },
    "Check": {
      "HTTP": "http://localhost:9090/health",
      "Interval": "10s",
      "Timeout": "3s"
    }
  }'
```

### 2. Query by Metadata

```bash
# Find services by tag
curl "http://localhost:8500/v1/health/service/user-service?tag=production" | jq

# Find services with specific metadata (using catalog endpoint)
curl "http://localhost:8500/v1/catalog/service/user-service" | jq '.[] | select(.ServiceMeta.environment == "production")'
```

## DNS Interface

Consul provides a DNS interface for service discovery:

```mermaid
graph TD
    subgraph "Consul DNS Interface"
        subgraph "DNS Queries"
            Q1["A Record Query<br/>web-service.service.consul"]
            Q2["SRV Record Query<br/>web-service.service.consul"]
        end
        
        subgraph "Consul DNS Server"
            DNS[DNS Server :8600]
            Resolver[DNS Resolver]
            Registry[Service Registry]
        end
        
        subgraph "DNS Responses"
            A1["A Record Response<br/>192.168.1.45"]
            SRV1["SRV Record Response<br/>Priority: 1, Port: 8080"]
        end
        
        Q1 --> DNS
        Q2 --> DNS
        DNS --> Resolver
        Resolver --> Registry
        Registry --> Resolver
        Resolver --> A1
        Resolver --> SRV1
        
        style DNS fill:#e8f5e8
        style Registry fill:#e1f5fe
    end
```

```bash
# Query services via DNS
dig @127.0.0.1 -p 8600 web-service.service.consul

# Query for SRV records (includes port information)
dig @127.0.0.1 -p 8600 web-service.service.consul SRV

# Query for healthy instances only
dig @127.0.0.1 -p 8600 web-service.service.consul

# Query specific datacenter
dig @127.0.0.1 -p 8600 web-service.service.dc1.consul
```

### DNS Query Types

```mermaid
graph TD
    subgraph "DNS Query Types in Consul"
        subgraph "A Record Queries"
            A1["web-service.service.consul"]
            A2["Returns IP addresses"]
            A3["Round-robin by default"]
            A1 --> A2
            A2 --> A3
        end
        
        subgraph "SRV Record Queries"
            S1["web-service.service.consul SRV"]
            S2["Returns IP + Port + Priority"]
            S3["Full service information"]
            S1 --> S2
            S2 --> S3
        end
        
        subgraph "Tag-based Queries"
            T1["production.web-service.service.consul"]
            T2["Returns instances with tag"]
            T3["Filtered by tag"]
            T1 --> T2
            T2 --> T3
        end
        
        style A1 fill:#e8f5e8
        style S1 fill:#e8f5e8
        style T1 fill:#e8f5e8
    end
```

## Best Practices Demonstrated

### Service Lifecycle Best Practices

```mermaid
graph TD
    subgraph "Service Lifecycle Best Practices"
        subgraph "Startup Phase"
            S1[Initialize Service]
            S2[Setup Health Check]
            S3[Register with Consul]
            S4[Start Accepting Traffic]
            
            S1 --> S2
            S2 --> S3
            S3 --> S4
        end
        
        subgraph "Running Phase"
            R1[Process Requests]
            R2[Update Health Status]
            R3[Handle Health Checks]
            R4[Monitor Performance]
            
            R1 --> R2
            R2 --> R3
            R3 --> R4
            R4 --> R1
        end
        
        subgraph "Shutdown Phase"
            SH1[Stop Accepting New Requests]
            SH2[Complete Existing Requests]
            SH3[Deregister from Consul]
            SH4[Cleanup Resources]
            
            SH1 --> SH2
            SH2 --> SH3
            SH3 --> SH4
        end
        
        S4 --> R1
        R1 --> SH1
        
        style S3 fill:#e8f5e8
        style R2 fill:#e8f5e8
        style SH3 fill:#e8f5e8
    end
```

### 1. Graceful Shutdown

```bash
cat > graceful_service.py << 'EOF'
#!/usr/bin/env python3
import signal
import sys
import requests
import time
from web_service import HealthHandler
import socketserver

class GracefulService:
    def __init__(self, service_id, port):
        self.service_id = service_id
        self.port = port
        self.consul_url = "http://localhost:8500"
        self.running = True
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)
    
    def register(self):
        """Register service with Consul"""
        registration = {
            "ID": self.service_id,
            "Name": "graceful-service",
            "Address": "localhost",
            "Port": self.port,
            "Tags": ["graceful", "demo"],
            "Check": {
                "HTTP": f"http://localhost:{self.port}/health",
                "Interval": "10s",
                "Timeout": "3s"
            }
        }
        
        try:
            response = requests.put(
                f"{self.consul_url}/v1/agent/service/register",
                json=registration
            )
            response.raise_for_status()
            print(f"Service {self.service_id} registered successfully")
        except requests.exceptions.RequestException as e:
            print(f"Failed to register service: {e}")
    
    def deregister(self):
        """Deregister service from Consul"""
        try:
            response = requests.put(
                f"{self.consul_url}/v1/agent/service/deregister/{self.service_id}"
            )
            response.raise_for_status()
            print(f"Service {self.service_id} deregistered successfully")
        except requests.exceptions.RequestException as e:
            print(f"Failed to deregister service: {e}")
    
    def shutdown(self, signum, frame):
        """Graceful shutdown handler"""
        print(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        self.deregister()
        sys.exit(0)
    
    def run(self):
        """Run the service"""
        self.register()
        
        # Start HTTP server
        with socketserver.TCPServer(("", self.port), HealthHandler) as httpd:
            print(f"Service running on port {self.port}")
            while self.running:
                httpd.handle_request()

if __name__ == '__main__':
    service = GracefulService("graceful-service-1", 8082)
    service.run()
EOF

# Run the graceful service
python3 graceful_service.py
# Press Ctrl+C to see graceful shutdown
```

## Cleanup

```mermaid
sequenceDiagram
    participant D as Developer
    participant S1 as Service 1
    participant S2 as Service 2
    participant C as Consul
    participant Docker as Docker
    
    Note over D,Docker: Cleanup Process
    
    D->>S1: Send SIGTERM
    S1->>C: Deregister service
    S1->>S1: Shutdown gracefully
    
    D->>S2: Send SIGTERM
    S2->>C: Deregister service
    S2->>S2: Shutdown gracefully
    
    D->>C: Manual deregistration (if needed)
    C->>C: Remove services from registry
    
    D->>Docker: Stop consul container
    Docker->>C: Stop Consul agent
    
    D->>D: Clean up demo files
    
    Note over D: Clean environment restored
```

```bash
# Stop all services
kill $SERVICE_PID $SERVICE_PID_2 2>/dev/null || true

# Deregister services (if not done gracefully)
curl -X PUT http://localhost:8500/v1/agent/service/deregister/web-service-1
curl -X PUT http://localhost:8500/v1/agent/service/deregister/web-service-2

# Stop Consul
docker stop consul-dev
docker rm consul-dev

# Clean up files
rm -f web_service.py discovery_client.py graceful_service.py
```

## Key Takeaways

```mermaid
mindmap
  root((Consul Basics<br/>Key Takeaways))
    Service Registration
      HTTP API simplicity
      Rich metadata support
      Automatic health checks
      Tag-based organization
    Service Discovery
      Multiple query options
      Health-based filtering
      DNS interface
      Real-time updates
    Health Management
      Multiple check types
      Automatic failure detection
      Service isolation
      Recovery handling
    Operational Patterns
      Graceful shutdown
      Multiple instances
      Load balancing
      Best practices
```

**Core Concepts Demonstrated**:

1. **Service registration** is straightforward with Consul's HTTP API
2. **Health checks** automatically manage service availability
3. **Service discovery** enables dynamic service location
4. **Metadata and tags** provide rich service information
5. **Graceful shutdown** ensures clean service deregistration
6. **Scaling** through multiple instances is seamless
7. **DNS interface** provides alternative discovery method

**What You've Learned**:

```mermaid
graph TD
    subgraph "Practical Skills Gained"
        subgraph "Consul Operations"
            O1[Start Consul in dev mode]
            O2[Use Consul Web UI]
            O3[Register services via API]
            O4[Query services programmatically]
        end
        
        subgraph "Service Development"
            D1[Create health check endpoints]
            D2[Implement graceful shutdown]
            D3[Handle service metadata]
            D4[Build discovery clients]
        end
        
        subgraph "System Design"
            S1[Understand service lifecycle]
            S2[Design for high availability]
            S3[Implement load balancing]
            S4[Plan for failure scenarios]
        end
        
        style O1 fill:#e8f5e8
        style D1 fill:#e8f5e8
        style S1 fill:#e8f5e8
    end
```

This hands-on experience demonstrates the core concepts of service discovery in action. Next, we'll explore the architectural patterns and trade-offs in client-side vs. server-side discovery.