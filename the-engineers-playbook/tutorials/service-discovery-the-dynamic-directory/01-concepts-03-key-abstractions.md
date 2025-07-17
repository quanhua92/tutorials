# Key Abstractions: The Building Blocks of Service Discovery

## The Company Directory Analogy

Before diving into technical abstractions, let's expand our company directory metaphor:

```mermaid
graph TD
    subgraph "Company Directory System"
        subgraph "Directory Database"
            DD[Directory Database]
        end
        
        subgraph "Employees"
            E1[John - Sales - Ext 123]
            E2[Jane - Marketing - Ext 456]
            E3[Bob - Engineering - Ext 789]
        end
        
        subgraph "Directory Services"
            R[Receptionist]
            IT[IT Help Desk]
            HR[HR Department]
        end
        
        E1 --> DD
        E2 --> DD
        E3 --> DD
        
        DD --> R
        DD --> IT
        DD --> HR
    end
    
    subgraph "Service Discovery System"
        subgraph "Service Registry"
            SR[Service Registry]
        end
        
        subgraph "Services"
            S1[User Service - 192.168.1.45:8080]
            S2[Order Service - 192.168.1.46:8080]
            S3[Payment Service - 192.168.1.47:8080]
        end
        
        subgraph "Discovery Clients"
            C1[Web App Client]
            C2[Mobile API Client]
            C3[Admin Dashboard]
        end
        
        S1 --> SR
        S2 --> SR
        S3 --> SR
        
        SR --> C1
        SR --> C2
        SR --> C3
    end
```

**Mapping the Concepts**:

| Company Directory | Service Discovery |
|---|---|
| **Employee** (Name, dept, ext, office) | **Service** (Name, address, port, metadata) |
| **Directory Database** (Central employee list) | **Service Registry** (Central service database) |
| **Receptionist** (Helps visitors find people) | **Discovery Client** (Helps apps find services) |
| **Phone Extension** (How to reach someone) | **Service Endpoint** (How to connect to service) |
| **Department** (Organizational grouping) | **Service Tags** (Logical grouping) |
| **Employee Status** (Available, in meeting, etc.) | **Health Status** (Healthy, unhealthy, etc.) |

## Core Abstraction 1: The Service Registry

### What It Is
The **Service Registry** is the central nervous system of service discovery. It's a distributed database that maintains the current state of all services in your system.

### Mental Model: The Living Phonebook

```mermaid
graph TD
    subgraph "Traditional Phonebook"
        PB[📞 Static Phonebook]
        PB --> E1[John: 555-1234]
        PB --> E2[Jane: 555-5678]
        PB --> E3[Bob: 555-9012]
        
        style PB fill:#ffebee
        style E1 fill:#ffebee
        style E2 fill:#ffebee
        style E3 fill:#ffebee
    end
    
    subgraph "Living Service Registry"
        SR[🔄 Dynamic Service Registry]
        
        subgraph "Auto-Discovery"
            AD1[Service Starts → Auto-Register]
            AD2[Service Stops → Auto-Remove]
            AD3[Service Fails → Mark Unhealthy]
        end
        
        subgraph "Rich Queries"
            Q1[Find by Name]
            Q2[Find by Tags]
            Q3[Find by Health Status]
            Q4[Find by Region]
        end
        
        SR --> AD1
        SR --> AD2
        SR --> AD3
        
        SR --> Q1
        SR --> Q2
        SR --> Q3
        SR --> Q4
        
        style SR fill:#e8f5e8
        style AD1 fill:#e8f5e8
        style AD2 fill:#e8f5e8
        style AD3 fill:#e8f5e8
    end
```

Think of it as a **living phonebook** that:
- Automatically adds new entries when services start
- Removes entries when services stop or become unhealthy
- Provides rich search capabilities beyond simple name lookup
- Updates in real-time without manual intervention
- Includes health status and rich metadata

### Key Properties

**1. Service Identity**
```json
{
  "id": "user-service-01",
  "name": "user-service",
  "address": "192.168.1.45",
  "port": 8080,
  "tags": ["production", "v2.1.0"],
  "metadata": {
    "version": "2.1.0",
    "region": "us-east-1",
    "capabilities": ["read", "write"]
  }
}
```

**2. Service Lifecycle**
```mermaid
graph TD
    A[Service Starts] --> B[Register with Registry]
    B --> C[Send Regular Heartbeats]
    C --> D{Health Check Passes?}
    D -->|Yes| C
    D -->|No| E[Mark as Unhealthy]
    E --> F[Remove from Active Pool]
    F --> G[Attempt Recovery]
    G --> H{Service Recovers?}
    H -->|Yes| C
    H -->|No| I[Deregister Service]
```

**3. Query Interface**
```
// Find all instances of a service
GET /v1/health/service/user-service

// Find healthy instances in a specific datacenter
GET /v1/health/service/user-service?dc=us-east-1&passing=true

// Find services with specific tags
GET /v1/health/service/user-service?tag=production&tag=v2.1.0
```

## Core Abstraction 2: Health Checks

### What They Are
**Health Checks** are the mechanism by which the registry determines whether a service is capable of handling requests.

### Mental Model
Think of health checks as a **security guard making rounds**:
- Visits each service at regular intervals
- Asks: "Are you operational and ready to serve?"
- Takes action if no satisfactory response

### Types of Health Checks

```mermaid
graph TD
    subgraph "Health Check Types"
        subgraph "HTTP Health Checks"
            H1[Registry] --> H2[GET /health]
            H2 --> H3[Service Response]
            H3 --> H4{Status Code?}
            H4 -->|200-299| H5[✅ Healthy]
            H4 -->|400-599| H6[❌ Unhealthy]
            H4 -->|Timeout| H7[❌ Unhealthy]
        end
        
        subgraph "TCP Health Checks"
            T1[Registry] --> T2[TCP Connect]
            T2 --> T3{Connection?}
            T3 -->|Success| T4[✅ Healthy]
            T3 -->|Failure| T5[❌ Unhealthy]
        end
        
        subgraph "Script Health Checks"
            S1[Registry] --> S2[Execute Script]
            S2 --> S3{Exit Code?}
            S3 -->|0| S4[✅ Healthy]
            S3 -->|Non-zero| S5[❌ Unhealthy]
        end
    end
    
    style H5 fill:#e8f5e8
    style T4 fill:#e8f5e8
    style S4 fill:#e8f5e8
    style H6 fill:#ffebee
    style H7 fill:#ffebee
    style T5 fill:#ffebee
    style S5 fill:#ffebee
```

**1. HTTP Health Checks**
```http
GET /health → 200 OK
{
  "status": "healthy",
  "checks": {
    "database": "ok",
    "cache": "ok",
    "disk_space": "ok"
  }
}
```

**2. TCP Health Checks**
```
Connect to service:port → Connection successful = healthy
```

**3. Script-Based Health Checks**
```bash
#!/bin/bash
# Custom health check script
if curl -f http://localhost:8080/health > /dev/null 2>&1; then
    exit 0  # Healthy
else
    exit 1  # Unhealthy
fi
```

### Health Check Lifecycle

```mermaid
sequenceDiagram
    participant S as Service
    participant R as Registry
    participant H as Health Checker
    participant C as Client
    
    Note over S,R: Service Registration
    S->>R: Register service
    R->>H: Start health monitoring
    
    loop Health Check Cycle
        Note over H,S: Regular Health Checks
        H->>S: Health check request
        S->>H: Health response
        
        alt Health Check Passes
            H->>R: Service is healthy
            R->>R: Keep in active pool
        else Health Check Fails
            H->>R: Service is unhealthy
            R->>R: Increment failure count
            
            alt Max Failures Reached
                R->>R: Remove from active pool
                R->>C: Stop routing traffic
                Note over R: Service marked as unhealthy
            else Still Within Failure Threshold
                R->>R: Keep monitoring
            end
        end
    end
    
    Note over S,R: Service Recovery
    S->>H: Health check passes
    H->>R: Service recovered
    R->>R: Add back to active pool
```

**Detailed Health Check State Machine**:

```mermaid
stateDiagram-v2
    [*] --> Registered
    Registered --> Healthy : First health check passes
    Registered --> Warning : First health check fails
    
    Healthy --> Healthy : Health check passes
    Healthy --> Warning : Health check fails
    
    Warning --> Healthy : Health check passes
    Warning --> Warning : Health check fails (< max failures)
    Warning --> Critical : Health check fails (>= max failures)
    
    Critical --> Warning : Health check passes
    Critical --> Critical : Health check fails
    Critical --> Deregistered : Service shuts down
    
    Deregistered --> [*]
```

## Core Abstraction 3: Service Metadata

### What It Is
**Service Metadata** provides rich, contextual information about services beyond just their network location.

### Mental Model: The Enhanced Business Card

```mermaid
graph TD
    subgraph "Traditional Business Card"
        BC[📇 Basic Business Card]
        BC --> N[Name: John Smith]
        BC --> T[Title: Software Engineer]
        BC --> P[Phone: 555-1234]
        BC --> E[Email: john@company.com]
        
        style BC fill:#ffebee
    end
    
    subgraph "Service Metadata: Enhanced Profile"
        SM[🏷️ Service Metadata]
        
        subgraph "Identity"
            I1[Name: user-service]
            I2[Version: v2.1.0]
            I3[Environment: production]
        end
        
        subgraph "Capabilities"
            C1[Operations: read, write, delete]
            C2[Protocols: HTTP, gRPC]
            C3[Data Formats: JSON, Protobuf]
        end
        
        subgraph "Operational Info"
            O1[Region: us-east-1]
            O2[Instance Type: m5.large]
            O3[Load Balancer Weight: 100]
        end
        
        subgraph "Custom Attributes"
            A1[Team: user-experience]
            A2[Cost Center: engineering]
            A3[Maintenance Window: sunday-2am]
        end
        
        SM --> I1
        SM --> I2
        SM --> I3
        SM --> C1
        SM --> C2
        SM --> C3
        SM --> O1
        SM --> O2
        SM --> O3
        SM --> A1
        SM --> A2
        SM --> A3
        
        style SM fill:#e8f5e8
    end
```

Think of metadata as an **employee's enhanced business card** that includes:
- Basic info (name, contact, version)
- Capabilities (skills, protocols, operations)
- Preferences (region, load balancer weight)
- Status (health, availability, maintenance windows)
- Custom attributes (team, cost center, etc.)

### Categories of Metadata

**1. Identity Metadata**
```json
{
  "service_name": "user-service",
  "service_id": "user-service-01",
  "version": "2.1.0",
  "environment": "production"
}
```

**2. Capability Metadata**
```json
{
  "supported_operations": ["read", "write", "delete"],
  "api_version": "v2",
  "protocols": ["http", "grpc"],
  "data_formats": ["json", "protobuf"]
}
```

**3. Operational Metadata**
```json
{
  "region": "us-east-1",
  "datacenter": "us-east-1a",
  "instance_type": "m5.large",
  "load_balancer_weight": 100
}
```

**4. Custom Metadata**
```json
{
  "team": "user-experience",
  "cost_center": "engineering",
  "maintenance_window": "sunday-2am-utc"
}
```

### Using Metadata for Smart Routing

```mermaid
graph TD
    subgraph "Smart Routing Scenarios"
        subgraph "Version-Based Routing (Canary Deployment)"
            VR[Client Request]
            VR --> VD{Version Decision}
            VD -->|10%| V2[v2.1.0 Instance]
            VD -->|90%| V1[v2.0.0 Instance]
            
            style V2 fill:#fff3e0
            style V1 fill:#e8f5e8
        end
        
        subgraph "Geographic Routing"
            GR[Client Request]
            GR --> GD{Region Check}
            GD -->|Same Region| G1[Local Instance<br/>us-east-1]
            GD -->|Different Region| G2[Remote Instance<br/>us-west-2]
            
            style G1 fill:#e8f5e8
            style G2 fill:#fff3e0
        end
        
        subgraph "Capability-Based Routing"
            CR[Client Request]
            CR --> CD{Required Capability}
            CD -->|Read Only| C1[Read-Only Instance]
            CD -->|Write Required| C2[Read-Write Instance]
            
            style C1 fill:#e3f2fd
            style C2 fill:#fff3e0
        end
        
        subgraph "Load-Based Routing"
            LR[Client Request]
            LR --> LD{Load Balancer Weight}
            LD -->|Weight: 100| L1[High-Performance Instance]
            LD -->|Weight: 50| L2[Standard Instance]
            LD -->|Weight: 25| L3[Low-Performance Instance]
            
            style L1 fill:#e8f5e8
            style L2 fill:#fff3e0
            style L3 fill:#ffebee
        end
    end
```

**Version-Based Routing (Canary Deployment)**:
```sql
-- Route 10% of traffic to v2.1.0, 90% to v2.0.0
SELECT * FROM services 
WHERE name = 'user-service' 
AND version = '2.1.0' 
AND random() < 0.1

UNION ALL

SELECT * FROM services 
WHERE name = 'user-service' 
AND version = '2.0.0' 
AND random() >= 0.1
```

**Geographic Routing**:
```sql
-- Prefer services in the same region, fallback to others
SELECT * FROM services 
WHERE name = 'user-service' 
AND region = 'us-east-1' 
ORDER BY latency ASC
LIMIT 1

-- If no local services, use remote
UNION ALL

SELECT * FROM services 
WHERE name = 'user-service' 
AND region != 'us-east-1'
ORDER BY latency ASC
LIMIT 1
```

**Capability-Based Routing**:
```sql
-- Route based on required capabilities
SELECT * FROM services 
WHERE name = 'user-service' 
AND capabilities LIKE '%write%'
AND health_status = 'healthy'
ORDER BY load_balancer_weight DESC
```

## Core Abstraction 4: The Service Discovery Client

### What It Is
The **Discovery Client** is the interface between your application and the service registry. It abstracts away the complexity of service lookup and provides a simple API.

### Mental Model: The Smart Phone Contacts App

```mermaid
graph TD
    subgraph "Traditional Phone Book"
        PB[📞 Phone Book]
        PB --> M[Manual Lookup]
        M --> S[Static Information]
        S --> O[Outdated Data]
        
        style PB fill:#ffebee
        style O fill:#ffebee
    end
    
    subgraph "Smart Contacts App (Discovery Client)"
        SC[📱 Smart Contacts]
        
        subgraph "Core Features"
            AS[Auto-Sync with Directory]
            C[Intelligent Caching]
            SF[Search & Filtering]
            AU[Automatic Updates]
        end
        
        subgraph "Advanced Features"
            F[Favorites/Preferences]
            H[Call History]
            AI[Smart Suggestions]
            O[Offline Mode]
        end
        
        SC --> AS
        SC --> C
        SC --> SF
        SC --> AU
        SC --> F
        SC --> H
        SC --> AI
        SC --> O
        
        style SC fill:#e8f5e8
    end
    
    subgraph "Service Discovery Mapping"
        SD[Discovery Client]
        
        subgraph "Core Capabilities"
            RS[Registry Synchronization]
            SC[Service Caching]
            SQ[Service Queries]
            RT[Real-time Updates]
        end
        
        subgraph "Advanced Capabilities"
            LB[Load Balancing]
            CB[Circuit Breaking]
            R[Retry Logic]
            FM[Failover Management]
        end
        
        SD --> RS
        SD --> SC
        SD --> SQ
        SD --> RT
        SD --> LB
        SD --> CB
        SD --> R
        SD --> FM
        
        style SD fill:#e1f5fe
    end
```

Think of it as a **smart phone contacts app** that:
- Automatically syncs with the company directory
- Caches frequently used contacts
- Provides search and filtering capabilities
- Handles directory updates seamlessly
- Provides offline functionality
- Learns from usage patterns

### Client Responsibilities

```mermaid
sequenceDiagram
    participant A as Application
    participant C as Discovery Client
    participant Cache as Client Cache
    participant R as Service Registry
    participant S as Service Instance
    
    Note over A,S: Service Discovery Flow
    
    A->>C: Request "user-service"
    C->>Cache: Check cache
    
    alt Cache Hit (Fresh)
        Cache->>C: Return cached services
        C->>C: Apply load balancing
        C->>A: Return selected instance
    else Cache Miss or Stale
        C->>R: Query registry
        R->>C: Return service list
        C->>Cache: Update cache
        C->>C: Apply load balancing
        C->>A: Return selected instance
    end
    
    A->>S: Make request to service
    S->>A: Response
    
    Note over C,Cache: Background refresh
    loop Periodic Refresh
        C->>R: Refresh service list
        R->>C: Updated services
        C->>Cache: Update cache
    end
```

**1. Service Lookup with Caching**
```go
client := discovery.NewClient()
services, err := client.Discover("user-service", discovery.HealthyOnly())
if err != nil {
    return err
}

// Pick a service instance (load balancing logic)
instance := services[rand.Intn(len(services))]
```

**2. Multi-Level Caching Strategy**
```mermaid
graph TD
    subgraph "Client Cache Hierarchy"
        L1[L1: In-Memory Cache<br/>Fast access, short TTL]
        L2[L2: Local File Cache<br/>Persistent, medium TTL]
        L3[L3: Static Fallback<br/>Last resort config]
        
        A[Application Request] --> L1
        L1 -->|Cache Miss| L2
        L2 -->|Cache Miss| R[Registry Query]
        R -->|Registry Down| L3
        
        R --> L2
        L2 --> L1
        L1 --> A
        
        style L1 fill:#e8f5e8
        style L2 fill:#fff3e0
        style L3 fill:#ffebee
    end
```

**3. Load Balancing Strategies**
```go
// Round-robin load balancing
func (c *Client) pickInstance(services []Service) Service {
    c.mutex.Lock()
    defer c.mutex.Unlock()
    
    instance := services[c.roundRobinIndex % len(services)]
    c.roundRobinIndex++
    return instance
}

// Weighted random selection
func (c *Client) pickWeightedInstance(services []Service) Service {
    totalWeight := 0
    for _, service := range services {
        totalWeight += service.Weight
    }
    
    r := rand.Intn(totalWeight)
    for _, service := range services {
        r -= service.Weight
        if r <= 0 {
            return service
        }
    }
    return services[0] // fallback
}
```

## Advanced Abstractions

### Service Mesh Integration

**Service Mesh** abstracts service discovery into the network layer:

```mermaid
graph TD
    subgraph "Traditional Service Discovery"
        A1[Application] --> C1[Discovery Client]
        C1 --> R1[Service Registry]
        C1 --> S1[Target Service]
        
        style A1 fill:#ffebee
        style C1 fill:#ffebee
    end
    
    subgraph "Service Mesh Discovery"
        A2[Application] --> P1[Sidecar Proxy]
        P1 --> R2[Service Registry]
        P1 --> P2[Target Sidecar]
        P2 --> S2[Target Service]
        
        subgraph "Sidecar Capabilities"
            SC1[Service Discovery]
            SC2[Load Balancing]
            SC3[Circuit Breaking]
            SC4[Retry Logic]
            SC5[mTLS]
            SC6[Metrics]
        end
        
        P1 --> SC1
        P1 --> SC2
        P1 --> SC3
        P1 --> SC4
        P1 --> SC5
        P1 --> SC6
        
        style P1 fill:#e8f5e8
        style P2 fill:#e8f5e8
        style SC1 fill:#e1f5fe
        style SC2 fill:#e1f5fe
        style SC3 fill:#e1f5fe
        style SC4 fill:#e1f5fe
        style SC5 fill:#e1f5fe
        style SC6 fill:#e1f5fe
    end
```

### Event-Driven Discovery

**Event Stream** provides real-time updates:

```mermaid
sequenceDiagram
    participant S as Service
    participant R as Registry
    participant E as Event Stream
    participant C1 as Client A
    participant C2 as Client B
    participant C3 as Client C
    
    Note over S,R: Service Lifecycle Events
    
    S->>R: Register service
    R->>E: Publish "service_registered" event
    E->>C1: Notify client A
    E->>C2: Notify client B
    E->>C3: Notify client C
    
    S->>R: Update health status
    R->>E: Publish "service_health_changed" event
    E->>C1: Notify client A
    E->>C2: Notify client B
    E->>C3: Notify client C
    
    S->>R: Deregister service
    R->>E: Publish "service_deregistered" event
    E->>C1: Notify client A
    E->>C2: Notify client B
    E->>C3: Notify client C
```

```json
{
  "event": "service_registered",
  "service": {
    "id": "user-service-02",
    "name": "user-service",
    "address": "192.168.1.46",
    "port": 8080,
    "tags": ["production", "v2.1.0"],
    "metadata": {
      "region": "us-east-1",
      "version": "2.1.0"
    }
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Multi-Registry Federation

**Federated Registry** spans multiple environments:

```mermaid
graph TD
    subgraph "Multi-Environment Federation"
        subgraph "Production Environment"
            PR[Production Registry]
            PS1[Service A]
            PS2[Service B]
            PS3[Service C]
            
            PS1 --> PR
            PS2 --> PR
            PS3 --> PR
        end
        
        subgraph "Staging Environment"
            SR[Staging Registry]
            SS1[Service A]
            SS2[Service B]
            
            SS1 --> SR
            SS2 --> SR
        end
        
        subgraph "Development Environment"
            DR[Development Registry]
            DS1[Service A]
            
            DS1 --> DR
        end
        
        subgraph "Federation Layer"
            FL[Federation Controller]
            GSV[Global Service View]
            
            FL --> GSV
        end
        
        PR --> FL
        SR --> FL
        DR --> FL
        
        subgraph "Cross-Environment Queries"
            Q1[Find all Service A instances]
            Q2[Find staging Service B]
            Q3[Cross-environment routing]
        end
        
        GSV --> Q1
        GSV --> Q2
        GSV --> Q3
        
        style FL fill:#e1f5fe
        style GSV fill:#e8f5e8
    end
```

## Putting It All Together: The Complete System

```mermaid
graph TD
    subgraph "Service Discovery Ecosystem"
        subgraph "Services Layer"
            S1[User Service]
            S2[Order Service]
            S3[Payment Service]
            S4[Notification Service]
        end
        
        subgraph "Registry Layer"
            R[Service Registry]
            
            subgraph "Registry Components"
                DB[Registry Database]
                API[Registry API]
                HC[Health Checker]
                ES[Event Stream]
            end
            
            R --> DB
            R --> API
            R --> HC
            R --> ES
        end
        
        subgraph "Discovery Layer"
            DC1[Discovery Client A]
            DC2[Discovery Client B]
            DC3[Discovery Client C]
            
            subgraph "Client Features"
                C[Caching]
                LB[Load Balancing]
                CB[Circuit Breaking]
                R[Retry Logic]
            end
            
            DC1 --> C
            DC1 --> LB
            DC1 --> CB
            DC1 --> R
        end
        
        subgraph "Application Layer"
            A1[Web Application]
            A2[Mobile API]
            A3[Admin Dashboard]
        end
        
        %% Connections
        S1 --> R
        S2 --> R
        S3 --> R
        S4 --> R
        
        R --> DC1
        R --> DC2
        R --> DC3
        
        DC1 --> A1
        DC2 --> A2
        DC3 --> A3
        
        %% Health checks
        HC --> S1
        HC --> S2
        HC --> S3
        HC --> S4
        
        %% Events
        ES --> DC1
        ES --> DC2
        ES --> DC3
    end
    
    style R fill:#e1f5fe
    style DC1 fill:#e8f5e8
    style DC2 fill:#e8f5e8
    style DC3 fill:#e8f5e8
```

**The Complete Service Discovery Flow**:

```mermaid
sequenceDiagram
    participant S as Service
    participant R as Registry
    participant H as Health Checker
    participant E as Event Stream
    participant C as Discovery Client
    participant A as Application
    
    Note over S,A: Complete Service Discovery Lifecycle
    
    %% Registration
    S->>R: 1. Register with metadata
    R->>E: Publish registration event
    E->>C: Notify clients
    R->>H: Start health monitoring
    
    %% Health Monitoring
    loop Health Checks
        H->>S: Health check
        S->>H: Health response
        H->>R: Update health status
    end
    
    %% Service Discovery
    A->>C: Request "user-service"
    C->>R: Query registry (if cache miss)
    R->>C: Return healthy instances
    C->>C: Apply load balancing
    C->>A: Return selected instance
    
    %% Service Communication
    A->>S: Make request
    S->>A: Response
    
    %% Service Failure
    S->>S: Service becomes unhealthy
    H->>S: Health check fails
    H->>R: Mark as unhealthy
    R->>E: Publish health change event
    E->>C: Notify clients
    C->>C: Remove from active pool
    
    %% Service Recovery
    S->>S: Service recovers
    H->>S: Health check passes
    H->>R: Mark as healthy
    R->>E: Publish health change event
    E->>C: Notify clients
    C->>C: Add back to active pool
```

**Key Integration Points**:

1. **Services register** with the registry, providing rich metadata
2. **Health checks** continuously verify service availability
3. **Clients query** the registry using metadata filters
4. **Load balancing** distributes requests across healthy instances
5. **Caching** improves performance and resilience
6. **Event streams** provide real-time updates
7. **Circuit breakers** prevent cascading failures

### Mental Model Summary

```mermaid
mindmap
  root((Service Discovery<br/>Abstractions))
    Service Registry
      Living phonebook
      Automatic updates
      Rich queries
      Health tracking
    Health Checks
      Security guard rounds
      Continuous monitoring
      Multiple check types
      Failure thresholds
    Service Metadata
      Enhanced business card
      Identity + capabilities
      Operational info
      Smart routing
    Discovery Client
      Smart contacts app
      Caching + sync
      Load balancing
      Circuit breaking
    Advanced Features
      Service mesh
      Event streams
      Multi-registry
      Cross-environment
```

The next section will provide practical, hands-on experience with these abstractions using Consul, a popular service discovery system.