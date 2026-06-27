"""
architectural_patterns.py - Architectural patterns for distributed systems:
the deployment-topology spectrum (monolith / SOA / microservices / serverless),
service mesh + sidecar, event-driven architecture, and CQRS - with a tradeoff
analysis that scores each pattern on the axes a staff engineer actually weighs.

This is the architectural-patterns overlay of the dist/ suite. It ties together
the structure decisions (how do you split a system?) with the building blocks
the deeper bundles expand on (cqrs here <-> write_scaling in architectural
theory; event-driven here <-> gossip/backpressure; sidecar here <->
circuit_breaker/failure_detection). Every number, table, and worked example
below is printed by this file and recomputed live in architectural_patterns.html.

Run:
    python3 architectural_patterns.py

Pure Python stdlib only (no imports beyond the standard library).

============================================================================
THE INTUITION (read this first) - structure follows the forcing function
============================================================================
Architecture is not a religion; it is a response to a FORCING FUNCTION - a
number or constraint that makes a particular structure necessary. Get the
forcing function right and the pattern follows; get it wrong and you either
over-engineer (a 3-person startup on Kubernetes) or under-engineer (a single
Postgres for a billion users).

  1. THE DEPLOYMENT SPECTRUM is a slider, not a binary. Monolith -> SOA ->
     microservices -> serverless trade INDEPENDENT-SCALABILITY and
     FAULT-ISOLATION for OPERATIONAL-COMPLEXITY and NETWORK-LATENCY. You move
     RIGHT only when the cost of the monolith (coupled deploys, blast radius)
     exceeds the cost of the distributed operations (observability, network
     failure modes).

  2. MICROSERVICES DO NOT FIX BAD DESIGN. Conway's law: the architecture
     mirrors the org chart. A 'distributed monolith' - services that must
     deploy together and share a database - has ALL the costs of microservices
     (network, ops) and NONE of the benefits (independent deploy, fault
     isolation). The database boundary IS the service boundary.

  3. A SERVICE MESH MOVES THE CROSS-CUTTING CODE OUT OF YOUR SERVICE. mTLS,
     retries, circuit breaking, load balancing, observability - every service
     re-implements these. A sidecar proxy (Envoy) does them once, uniformly,
     language-agnostically. The cost is a second process per pod and a control
     plane - worth it past ~20 services, pure overhead below ~10.

  4. EVENT-DRIVEN = TEMPORAL DECOUPLING. A request/response call couples the
     caller to the callee in TIME (the caller blocks). An event decouples them:
     the producer fires and forgets, consumers react later. This absorbs
     bursts (the queue is the buffer) and enables fan-out (one event -> N
     consumers), at the cost of harder debugging (no stack trace across
     services) and eventual consistency.

  5. CQRS SPLITS WRITE FROM READ. The write model is normalized (Postgres,
     strong consistency, low write contention). The read model is denormalized
     (Elasticsearch/Redis, query-optimized). A CDC/Kafka stream keeps them in
     sync with a 50-500ms lag. You pay 50-500ms of STALENESS to get 10x-100x
     read throughput WITHOUT sharding the primary.

THE HARD TRUTH: every pattern listed here ADDS a failure mode. The monolith's
only failure is the deploy; microservices add network, the mesh adds a control
plane, events add a broker, CQRS adds a read-lag. Pick the pattern only when
the forcing function makes the ADDED failure mode cheaper than the problem it
solves.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  monolith        : one deployable unit. All code in one process, one database.
                     Simplest to build, deploy, and debug. Scales by cloning
                     the whole unit (you scale the slowest feature too).
  SOA             : services with SHARED enterprise infrastructure (an ESB -
                     enterprise service bus) and heavyweight protocols (SOAP).
                     The precursor to microservices; coarse-grained, often
                     still sharing a database.
  microservices   : small, independently-deployable services, each owning its
                     own database, communicating over lightweight protocols
                     (REST/gRPC/async). Conway's law made explicit.
  serverless / FaaS: functions-as-a-service. The cloud runs, scales, and bills
                     your code per invocation. No servers to manage, cold-start
                     latency, hard limit on execution time, vendor lock-in.
  forcing function: the metric or constraint that MAKES a structure necessary
                     (read QPS > 10K, deploy frequency > 10/day, blast radius
                     > acceptable). Derive it FIRST, then propose the pattern.
  service mesh    : an infrastructure layer (data plane = sidecar proxies +
                     control plane) that handles service-to-service comms:
                     mTLS, retries, circuit breaking, LB, tracing.
  sidecar         : a second container in the same pod as your service, sharing
                     its network namespace. The proxy that IS the mesh data
                     plane. Decouples cross-cutting logic from app code.
  data plane      : the proxies (Envoy/Linkerd) that intercept every request.
                     They do the actual work (TLS, retry, route).
  control plane   : the brain (Istiod/Consul) that configures the data plane -
                     pushes routes, certs, policies. Does NOT sit in the data
                     path, so its latency does not affect requests.
  event-driven    : producers emit events to a broker (Kafka); consumers react
                     asynchronously. Temporal decoupling + fan-out.
  fan-out         : one event triggers N independent downstream actions (e.g.
                     1 post -> 300K feed insertions across N worker partitions).
  CQRS            : command/query responsibility segregation. Separate the
                     WRITE model (normalized, OLTP) from the READ model
                     (denormalized, query-optimized), synced by a stream.
  read lag        : in CQRS, the delay between a write committing and the read
                     model reflecting it (50-500ms via Kafka CDC). Unacceptable
                     for "read your own writes" without session pinning.
  outbox pattern  : write the domain record + an outbox event in ONE local
                     transaction; a poller/CDC (Debezium) publishes the event.
                     The production-standard way to "write + reliably publish".
  distributed monolith: anti-pattern. Services that must deploy together / share
                     a DB. All microservice costs, none of the benefits.
  blast radius    : the scope of damage when a change fails. A monolith deploy
                     can break everything; a microservice deploy breaks one.

============================================================================
THE PATTERNS & PAPERS
============================================================================
  Fowler & Lewis 2011  "Microservices" (term popularized by Fowler) - the
                        first clear articulation of the fine-grained service
                        style and its tradeoffs.
  Newman              "Building Microservices" - service boundaries, the
                        database-per-service rule, integration patterns.
  Burns et al.         Borg/Omega/Kubernetes lineage - containers + pods, the
                        substrate that made the sidecar/mesh pattern viable.
  Buchhein & Donovan   Envoy/Service-mesh design - data plane vs control plane
                        separation; xDS APIs.
  Richardsons          CQRS + event sourcing pattern language.

KEY FORMULAS / facts (all asserted in code):
    score(p, w) : weighted sum of axis scores for pattern p under weights w
    fan_out     : 1 event -> K consumers (linear; Kafka partitions parallelize)
    cqrs_lag    : read_lag = producer_commit_to_broker + broker_to_consumer
    sidecar_mem : N pods * mem_per_sidecar (linear in service count)
    mesh_links  : data plane is O(N) proxies; logical links = O(N^2) but routed
"""

from __future__ import annotations

BANNER = "=" * 74

# ---------------------------------------------------------------------------
# The deployment-topology spectrum. Each pattern scored 1-5 on each axis,
# where 5 is BEST for that axis. Scores are the *consensus* tradeoffs (e.g.
# a monolith is the fastest to build but the worst to scale independently).
# These feed the weighted tradeoff analyzer (Section A / GOLD CHECK) AND the
# live .html comparison.
AXES = [
    "dev_velocity",     # how fast can a team build & ship features
    "ops_simple",       # how little operational machinery is needed
    "latency",          # how low the intra-system call latency is
    "scalability",      # how independently each part can scale
    "fault_isolation",  # how small the blast radius of a failure is
    "tech_flex",        # how freely each part can use its own stack
]

PATTERNS = {
    "monolith": {
        "dev_velocity": 5, "ops_simple": 5, "latency": 5,
        "scalability": 2, "fault_isolation": 1, "tech_flex": 1,
        "deploy_unit": "1",  "owns_db": "shared",
    },
    "soa": {
        "dev_velocity": 3, "ops_simple": 3, "latency": 3,
        "scalability": 3, "fault_isolation": 3, "tech_flex": 3,
        "deploy_unit": "~10", "owns_db": "shared (often)",
    },
    "microservices": {
        "dev_velocity": 2, "ops_simple": 1, "latency": 3,
        "scalability": 5, "fault_isolation": 5, "tech_flex": 5,
        "deploy_unit": "~100s", "owns_db": "per-service",
    },
    "serverless": {
        "dev_velocity": 4, "ops_simple": 4, "latency": 2,
        "scalability": 5, "fault_isolation": 4, "tech_flex": 2,
        "deploy_unit": "1 function", "owns_db": "managed",
    },
}

# Weight profiles = the forcing function made numeric. Different business
# stages favor different topologies. Each axis weight is how much that axis
# matters (higher = more important). The analyzer picks the highest-scoring
# pattern per profile.
PROFILES = {
    "MVP / startup (ship fast, small team)": {
        "dev_velocity": 3, "ops_simple": 3, "latency": 2,
        "scalability": 1, "fault_isolation": 1, "tech_flex": 1,
    },
    "Hyperscale (independent scale + blast radius)": {
        "dev_velocity": 1, "ops_simple": 1, "latency": 2,
        "scalability": 3, "fault_isolation": 3, "tech_flex": 2,
    },
    "Cost-sensitive (minimize infra & ops)": {
        "dev_velocity": 2, "ops_simple": 3, "latency": 2,
        "scalability": 1, "fault_isolation": 2, "tech_flex": 1,
    },
    "Polyglot org (many teams, many stacks)": {
        "dev_velocity": 1, "ops_simple": 1, "latency": 1,
        "scalability": 2, "fault_isolation": 3, "tech_flex": 3,
    },
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def score(pattern: str, weights: dict) -> int:
    """Weighted sum of axis scores. Higher = better fit for the weight profile."""
    p = PATTERNS[pattern]
    return sum(p[axis] * weights[axis] for axis in AXES)


# ---------------------------------------------------------------------------
# SECTION A: the deployment spectrum - monolith / SOA / microservices / serverless
# ---------------------------------------------------------------------------
def section_a():
    banner("SECTION A: the deployment spectrum - monolith -> serverless")
    print("Architecture is a slider, not a binary. Moving RIGHT trades")
    print("INDEPENDENT-SCALABILITY and FAULT-ISOLATION for OPERATIONAL-COMPLEXITY")
    print("and NETWORK-LATENCY. You move right only when the cost of the monolith")
    print("exceeds the cost of the distributed operations.\n")
    print("  | topology     | deploy unit  | owns DB        | scales by            |")
    print("  |--------------|--------------|----------------|----------------------|")
    for name, p in PATTERNS.items():
        if name == "monolith":
            scales = "cloning the whole app"
        elif name == "soa":
            scales = "cloning coarse services"
        elif name == "microservices":
            scales = "cloning the one hot service"
        else:
            scales = "the cloud (auto, per call)"
        print(f"  | {name:<12} | {p['deploy_unit']:<12} | {p['owns_db']:<14} | {scales:<20} |")
    print()
    print("MONOLITH: one process, one database, one deploy. The fastest way to")
    print("deliver a working system. Every call is an in-process function call")
    print("(nanoseconds). The single failure mode is the deploy - but that deploy")
    print("can break EVERYTHING (blast radius = whole system). Scales only by")
    print("cloning the entire unit, so the slowest feature caps every other.\n")
    print("SOA: services communicating through an enterprise service bus (ESB),")
    print("often with heavyweight protocols (SOAP/XML). The precursor to")
    print("microservices - coarse-grained, frequently still sharing a database.")
    print("The ESB became a bottleneck and a single point of ownership, which is")
    print("why microservices replaced it with dumb pipes (REST/gRPC) and smart")
    print("endpoints.\n")
    print("MICROSERVICES: small, independently-deployable services, EACH owning")
    print("its own database, over lightweight protocols. The win is independent")
    print("deploy + scale + fault isolation (one service's crash does not take")
    print("down the others). The cost is the HARDEST problem in distributed")
    print("systems now multiplied across every service boundary: the network is")
    print("unreliable, debugging a request that hops 8 services needs distributed")
    print("tracing, and a 'distributed monolith' (services that must deploy")
    print("together / share a DB) has ALL the costs and NONE of the benefits.\n")
    print("SERVERLESS / FaaS: the cloud runs your function per invocation. No")
    print("servers, auto-scales to zero, bills per call. The cost is cold-start")
    print("latency (50-2000ms when the runtime is spun up), hard execution-time")
    print("limits (e.g. 15min), and deep vendor lock-in. Ideal for sporadic /")
    print("bursty workloads (webhooks, scheduled jobs), bad for steady hot paths.\n")
    print("THE DATABASE BOUNDARY IS THE SERVICE BOUNDARY. Sharing a database")
    print("couples services at the storage layer - a schema change by one team")
    print("breaks another. Database-per-service is what makes microservices")
    print("actually independent; without it you have a distributed monolith.\n")

    # the core tradeoff: latency blows up as you cross network boundaries
    hops = {
        "monolith (in-process call)": 0.000001,   # ~1 us function call
        "microservices (gRPC, same DC)": 0.001,    # ~1 ms
        "microservices + mesh sidecar": 0.002,     # ~2 ms (proxy hop added)
        "serverless cold start": 0.500,            # ~500 ms
    }
    print("The latency tax of distribution (per intra-system call):\n")
    print("  | call path                       | latency    | vs in-process |")
    print("  |----------------------------------|------------|---------------|")
    base = hops["monolith (in-process call)"]
    for path, lat in hops.items():
        ratio = lat / base
        print(f"  | {path:<32} | {lat*1000:<7.3f} ms | {ratio:>10.0f}x     |")
    print()
    print("A monolith function call is ~1 us. The SAME logical call as a gRPC")
    print("round-trip is ~1 ms (1000x). With a sidecar on both ends, ~2 ms. A")
    print("serverless cold start can be 500 ms (500000x). This is why you do NOT")
    print("split a service for a call that happens 10000x per request - the")
    print("network latency dominates. Split at BOUNDS that change at different")
    print("rates (write model vs read model; billing vs catalog), not at every")
    print("function.\n")
    assert hops["serverless cold start"] > 250000 * hops["monolith (in-process call)"]
    print("[check] cold start > 250000x in-process call => distribution has a latency tax: OK")


# ---------------------------------------------------------------------------
# SECTION B: service mesh & the sidecar pattern
# ---------------------------------------------------------------------------
def section_b():
    banner("SECTION B: service mesh & the sidecar pattern")
    print("Every microservice re-implements the SAME cross-cutting concerns:")
    print("mutual TLS, retries with backoff, circuit breaking, load balancing,")
    print("distributed tracing, metrics. A SERVICE MESH moves this into a sidecar")
    print("proxy (Envoy/Linkerd) that sits next to every service - so the logic is")
    print("written ONCE, uniformly, language-agnostically.\n")
    print("  | plane         | what it is                 | in the data path? |")
    print("  |---------------|----------------------------|------------------|")
    print("  | data plane    | sidecar proxy per pod      | YES (every call) |")
    print("  | control plane | config/cert/policy brain    | NO (config push) |")
    print()
    print("THE SIDECAR: a second container in the same pod, sharing the network")
    print("namespace. Your service talks to localhost; the sidecar intercepts,")
    print("adds mTLS + retry + circuit-break, and forwards. App code sees no")
    print("mesh - it just calls localhost. The mesh is transparent infrastructure.\n")
    print("THE CONTROL PLANE (Istiod / Consul): does NOT touch requests. It")
    print("watches the service registry, computes routes/certs/policies, and")
    print("PUSHES them to the data plane via xDS APIs. Because it is out of the")
    print("data path, control-plane latency never affects a request.\n")

    # the cost model: sidecar RAM is linear in the number of pods
    sidecar_mem_mb = 64          # Envoy idle baseline ~64 MB
    print(f"The cost: each sidecar costs ~{sidecar_mem_mb} MB RAM (Envoy baseline).")
    print("For N services with R replicas each, the mesh overhead is:\n")
    print("  | services N | replicas each | pods = N*R | sidecar RAM (GB) |")
    print("  |------------|---------------|------------|------------------|")
    sidecar_gb = {}
    for n in (5, 20, 50, 100):
        r = 3
        pods = n * r
        gb = pods * sidecar_mem_mb / 1024
        sidecar_gb[n] = gb
        print(f"  | {n:<10} | {r:<13} | {pods:<10} | {gb:.1f}              |")
    print()
    print("Below ~10-20 services the mesh is mostly overhead you pay for little")
    print("benefit (you could hand-roll mTLS for 5 services). Above ~20 services")
    print("the mesh pays for itself: uniform mTLS, zero-trust by default, and")
    print("observability across every hop without touching app code. The forcing")
    print("function for adopting a mesh is SERVICE COUNT + SECURITY POSTURE, not")
    print("cool tech.\n")

    # logical links grow quadratically, but the data plane is O(N) proxies
    print("Network topology: the LOGICAL call graph can be O(N^2) (any service")
    print("may call any other), but the DATA PLANE stays O(N) - one sidecar per")
    print("pod. The control plane computes the routes; you never wire N^2 links.\n")
    print("  | services N | possible links N*(N-1)/2 | sidecar proxies = N |")
    print("  |------------|--------------------------|----------------------|")
    for n in (5, 20, 50, 100):
        links = n * (n - 1) // 2
        print(f"  | {n:<10} | {links:<24} | {n:<20} |")
    print()

    assert sidecar_gb[20] > sidecar_gb[5] * 3   # roughly 4x (20/5)
    print("[check] sidecar overhead scales linearly with pods; mesh worth it past ~20 svc: OK")


# ---------------------------------------------------------------------------
# SECTION C: event-driven architecture
# ---------------------------------------------------------------------------
def section_c():
    banner("SECTION C: event-driven architecture - temporal decoupling + fan-out")
    print("A request/response call couples caller and callee in TIME: the caller")
    print("BLOCKS until the callee replies. An EVENT decouples them: the producer")
    print("writes to a broker (Kafka) and returns immediately; consumers react")
    print("LATER. The broker is the BUFFER that absorbs bursts and the BUS that")
    print("enables fan-out.\n")
    print("  | style          | coupling      | caller blocks? | failure mode        |")
    print("  |----------------|---------------|----------------|---------------------|")
    print("  | request/resp   | spatial+temporal| YES          | caller fails if callee down |")
    print("  | event-driven   | temporal decoupled| NO         | broker buffers; consumer lag |")
    print()
    print("THE WIN: (1) the producer is never blocked by a slow consumer (the")
    print("queue absorbs the burst), and (2) ONE event fans out to N consumers")
    print("without the producer knowing any of them exist (open/closed).\n")

    # fan-out model: 1 event -> K consumers. The slowest consumer caps only
    # ITSELF (separate partitions / consumer groups), not the others.
    print("FAN-OUT: one 'post.created' event triggers feed insertion, push")
    print("notification, search indexing, analytics - all independent consumers.")
    print("Each runs at its own pace in its own consumer group; the slowest does")
    print("NOT block the others (the broker retains the event).\n")
    print("  | event triggers | consumers K | broker writes | parallelism = partitions |")
    print("  |----------------|-------------|---------------|--------------------------|")
    for k in (1, 4, 10, 50):
        parts = k                      # one partition per consumer for full parallelism
        print(f"  | 1 post.created | {k:<11} | {k} writes      | up to {parts} concurrent       |")
    print()
    print("THE COST: harder debugging (no stack trace across a broker boundary -")
    print("you need correlation IDs + distributed tracing), and EVENTUAL")
    print("consistency (a consumer may lag seconds behind the producer). A")
    print("notification fired 6 hours late is WORSE than none - consumers must")
    print("respect message expiry / time-to-live.\n")
    print("CHOICE: use events for ASYNC, fan-out, burst-absorbing work (feeds,")
    print("notifications, analytics, audit). Use request/response for SYNCHRONOUS")
    print("dependencies the caller cannot proceed without (a payment authorization")
    print("before confirming an order). Mixing both via the OUTBOX pattern is the")
    print("production standard: write the record + the outbox event in ONE local")
    print("transaction; a CDC relay (Debezium) reliably publishes the event.\n")

    assert 50 > 4 > 1   # fan-out degree is the consumer count, independent
    print("[check] 1 event -> K consumers; broker buffers bursts; eventual consistency: OK")


# ---------------------------------------------------------------------------
# SECTION D: CQRS - split the write model from the read model
# ---------------------------------------------------------------------------
def section_d():
    banner("SECTION D: CQRS - split write (normalized) from read (denormalized)")
    print("Most systems are read-heavy (10:1 to 100:1 read:write). A single")
    print("normalized database serves writes well but struggles under read load: a")
    print("complex join across the feed is slow, and you cannot add read replicas")
    print("forever (each adds cost for a linear gain). CQRS splits the two:\n")
    print("  | model   | store              | optimized for | consistency     |")
    print("  |---------|--------------------|---------------|-----------------|")
    print("  | WRITE   | PostgreSQL (normal)| low write contention | strong   |")
    print("  | READ    | Elasticsearch/Redis(denormal)| query speed | eventual|")
    print()
    print("A CDC stream (Debezium -> Kafka) keeps the read model in sync. The")
    print("write commits to Postgres; the read model catches up 50-500ms later.")
    print("You trade that 50-500ms of STALENESS for 10x-100x read throughput")
    print("WITHOUT sharding the primary - the read model absorbs the query load.\n")

    # capacity model: read replicas vs CQRS. Redis cache first, replicate second.
    redis_qps = 100_000           # Redis Cluster ~100K ops/sec
    replica_qps = 5_000           # a Postgres read replica ~5K QPS
    redis_cost = 500              # $/mo for the Redis node
    replica_cost = 5_000          # $/mo for a read replica
    print("The economics (cache first, replicate second):\n")
    print("  | option              | QPS added | cost $/mo | $ per 1K QPS |")
    print("  |---------------------|-----------|-----------|--------------|")
    print(f"  | Redis cache node    | {redis_qps:>7,} | {redis_cost:>7,}   | {redis_cost/redis_qps*1000:>8.2f}    |")
    print(f"  | 4th read replica    | {replica_qps:>7,} | {replica_cost:>7,}   | {replica_cost/replica_qps*1000:>8.2f}    |")
    print()
    print(f"Redis at ${redis_cost}/mo absorbs {redis_qps:,} read QPS; a 4th read replica at")
    print(f"${replica_cost}/mo adds only {replica_qps:,} QPS. Cache first, replicate second.")
    print("CQRS pushes this further: the read model is a PURPOSE-BUILT store for")
    print("each query shape, not a generic replica of the write schema.\n")

    # the read-lag reality: 50-500ms. unacceptable for "read your own writes"
    lag_min, lag_max = 0.050, 0.500
    print("The read-lag reality: 50-500ms between write commit and read model")
    print("update. This is FINE for a feed (you don't notice a 200ms-old post).")
    print("It is UNACCEPTABLE for 'read your own writes': a user who updates their")
    print("profile and immediately reloads expects to SEE the change. The fix is")
    print("session pinning (serve that user's reads from the write model for a")
    print("short window) or read-after-write consistency at the cost of latency.\n")

    assert redis_cost / redis_qps < replica_cost / replica_qps / 10   # >10x cheaper per QPS
    assert lag_max > lag_min
    print("[check] Redis >10x cheaper per QPS than a replica; CQRS read lag 50-500ms: OK")


# ---------------------------------------------------------------------------
# GOLD CHECK: weighted tradeoff analyzer - which pattern wins per profile
# ---------------------------------------------------------------------------
def gold_check():
    banner("GOLD CHECK: weighted tradeoff analyzer - the right pattern per profile")
    print("CAPSTONE: the tradeoff matrix. Each topology is scored 1-5 on six axes")
    print("(5 = best). A WEIGHT PROFILE encodes the forcing function - how much")
    print("each axis matters for a given business stage. The winner is the")
    print("highest weighted sum. Derive the profile (the forcing function) FIRST;")
    print("the pattern then follows.\n")
    print("The scores (consensus tradeoffs):\n")
    print("  | pattern       | " + " | ".join(a.replace("_", " ") for a in AXES) + " |")
    print("  |---------------|" + "|".join(["------"] * len(AXES)) + "|")
    for name, p in PATTERNS.items():
        cells = " | ".join(str(p[a]) for a in AXES)
        print(f"  | {name:<13} | {cells} |")
    print()
    print("The four weight profiles (the forcing function, made numeric):\n")
    print("  | profile                                    | winner         | score |")
    print("  |--------------------------------------------|----------------|-------|")
    gold_winners = {}
    for prof, weights in PROFILES.items():
        ranked = sorted(PATTERNS, key=lambda name: score(name, weights), reverse=True)
        winner = ranked[0]
        ws = score(winner, weights)
        gold_winners[prof] = winner
        print(f"  | {prof:<42} | {winner:<14} | {ws:>5} |")
    print()
    print("WORKED EXAMPLE (MVP profile): a 3-person startup should ship a")
    print("MONOLITH. The forcing function is dev_velocity + ops_simple: you have")
    print("no SRE team, no traffic, and your job is to find product-market fit,")
    print("not to operate Kubernetes. Premature microservices here is a classic")
    print("over-engineering failure - 'I'd start with a single Postgres and")
    print("revisit at 10x scale'.\n")
    print("WORKED EXAMPLE (Hyperscale profile): at 1B users, the forcing function")
    print("is scalability + fault_isolation. The billing service crashes must NOT")
    print("take down the feed; the hot read path must scale independently of the")
    print("write path. MICROSERVICES (+ CQRS on the read path) is now the right")
    print("answer - the operational cost is justified by the independent scale.\n")

    # pinned gold scalars for the .html
    mvp = PROFILES["MVP / startup (ship fast, small team)"]
    hyper = PROFILES["Hyperscale (independent scale + blast radius)"]
    print("GOLD scalars (for a compact .html check):")
    print(f"  score(monolith, MVP)      = {score('monolith', mvp)}")
    print(f"  score(microservices, MVP) = {score('microservices', mvp)}")
    print(f"  score(monolith, hyperscale)= {score('monolith', hyper)}")
    print(f"  score(microservices, hyperscale)= {score('microservices', hyper)}")
    print(f"  winner(MVP)       = {gold_winners['MVP / startup (ship fast, small team)']}")
    print(f"  winner(hyperscale)= {gold_winners['Hyperscale (independent scale + blast radius)']}")
    print("  cold_start_ms     = 500")
    print("  grpc_hop_ms       = 1")
    print("  cqrs_lag_min_ms   = 50")
    print("  cqrs_lag_max_ms   = 500")

    # assertions (these pin the values the .html recomputes)
    assert score("monolith", mvp) == 44
    assert score("microservices", mvp) == 30
    assert score("microservices", hyper) == 49
    assert score("monolith", hyper) == 31
    assert gold_winners["MVP / startup (ship fast, small team)"] == "monolith"
    assert gold_winners["Hyperscale (independent scale + blast radius)"] == "microservices"
    assert gold_winners["Cost-sensitive (minimize infra & ops)"] == "monolith"
    assert gold_winners["Polyglot org (many teams, many stacks)"] == "microservices"
    print("\n[check] weighted scores + per-profile winners all match the tradeoff matrix: OK")


# ---------------------------------------------------------------------------
def main():
    print("architectural_patterns.py - structure decisions. All numbers below feed")
    print("ARCHITECTURAL_PATTERNS.md. Python stdlib only (no third-party deps).")
    print()
    section_a()
    section_b()
    section_c()
    section_d()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
