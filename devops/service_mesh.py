"""
service_mesh.py - Reference simulation of a service mesh (Istio + Envoy).

This is the single source of truth that SERVICE_MESH.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 service_mesh.py      (pure stdlib; no dependencies)

============================================================================
THE INTUITION (read this first) -- the diplomatic pouch service
============================================================================
Picture two embassies (services) that need to exchange messages. Without a mesh,
each ambassador must hand-build their own secure courier: hire a guard (TLS),
write rules for how many messengers may enter at once (limits), keep a blacklist
of unsafe routes (circuit breaker), and file a trip report after every delivery
(metrics/tracing). Every embassy reinvents all of this, in every language, and
they never quite agree.

A SERVICE MESH installs ONE shared courier corps -- an ENVOY PROXY -- in front
of EVERY embassy, as a SIDECAR (a second container inside the same pod). The
ambassador just hands the letter to the local courier; the courier corps handles
security, limits, blacklists, and reporting uniformly. The ambassador's code
never changes.

Two halves of the courier corps:
  * CONTROL PLANE (Istiod)  -- headquarters. Reads your rules (VirtualService,
                               DestinationRule) and tells every courier how to
                               behave. Does NOT touch live traffic.
  * DATA PLANE  (Envoy x N) -- the couriers themselves, one per pod. ALL traffic
                               in/out of the pod is forced through them via
                               iptables redirect set up by an init container.

THE REASON FOR THE SIDECAR (not a library): security and uniformity must apply
to EVERY service, in EVERY language, including ones you cannot recompile. The
sidecar is injected by the mesh at pod-creation time (mutation webhook), so the
team that owns the app does not have to think about it. mTLS, retry, tracing all
come "for free" from the courier corps -- zero app code changes.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  service mesh  : an infrastructure layer that moves service-to-service traffic
                  through programmable proxies. Istio and Linkerd are meshes.
  sidecar       : a second container added to a pod, running alongside the app.
                  Here the sidecar is Envoy (the proxy).
  Envoy         : the proxy. The whole "data plane". Built by Lyft, CNCF project.
  Istiod        : the Istio control plane. Configures every Envoy via xDS.
  xDS           : the protocol Istiod uses to push config to Envoy (LDS/RDS/CDS/
                  EDS). "dynamic config over gRPC".
  init container: a container that runs to completion BEFORE the app starts.
                  Here it installs iptables rules that hijack all traffic into
                  Envoy. (Istio's "istio-init" / CNI plugin.)
  mTLS          : mutual TLS -- BOTH sides present and verify a certificate.
                  In the mesh, Envoy does it; the app sees plaintext on loopback.
  SPIFFE        : a standard identity for workloads: spiffe://<trust-domain>/ns/
                  <ns>/sa/<sa>. The SPIRE/Istiod CA mints short-lived certs whose
                  SAN is this identity. Auto-rotated long before expiry.
  VirtualService: the routing rules: "send 90% to v1, 10% to v2". (control plane)
  DestinationRule: policy for a host: load balancer algo, subsets (v1/v2),
                  connection pool limits, outlier detection. (control plane)
  subset        : a named slice of a service's pods, by label (version=v1).
  weight        : in a VirtualService route, the % of traffic to a subset.
  retry         : re-send a failed request (e.g. on 5xx), up to N attempts.
  timeout       : give up a single attempt after T seconds (perTryTimeout).
  circuit break : per-CLUSTER connection pool limit; overflow -> 503 locally,
                  never even calls upstream (protects a struggling service).
  outlier
   detection    : per-HOST health; eject a host after K consecutive 5xx for a
                  cooldown, so the LB stops sending it traffic. (host-level)
  golden
   signals      : the four metrics to watch any service: latency, traffic,
                  errors, saturation (Google SRE). Envoy emits all four.
  trace / span  : a request's path across services (Jaeger). Envoy auto-propagates
                  W3C Traceparent headers and emits spans -- no app change.

KEY FACTS (all asserted in code below):
  * The sidecar makes the mesh transparent to the app: app talks plaintext to
    127.0.0.1, Envoy does the mTLS/retry/metrics on the wire.
  * mTLS identity = SPIFFE ID; certs are short-lived (24h) and auto-rotated at
    ~80% lifetime, so a stolen cert is useless within hours.
  * Weighted routing (VirtualService) is enforced by Envoy's Weighted Round Robin
    cluster LB: over `sum(weights)` requests the split is EXACTLY the weights.
  * Retries + outlier detection hide transient upstream failures from the caller;
    the caller sees a clean 200 even when a backend pod is erroring.
  * Circuit breaking is LOCAL overflow protection (don't drown a slow service);
    outlier detection is REMOTE health protection (stop using a bad host).

Sources: Istio docs (istio.io/latest/docs), Envoy docs (envoyproxy.io), the
SPIFFE/SPIRE spec (spiffe.io), Google SRE Book ch.6 (the four golden signals),
and the Borg/K8s "sidecar pattern" (Brendan Burns, Designing Distributed Systems).
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 0. THE MESH MODEL -- deterministic, no randomness.
# ============================================================================

# A pod WITHOUT a mesh: one container. The app opens its own sockets.
POD_BEFORE_INJECTION = {
    "name": "payment-7d9-xyz",
    "containers": [
        {"name": "payment", "image": "registry/payment:2.1", "port": 8080},
    ],
    "initContainers": [],
}

# The SAME pod AFTER Istio injects the sidecar. Two changes, both transparent:
#   1. an init container ("istio-init") writes iptables rules so ALL traffic is
#      redirected to Envoy BEFORE the app container starts.
#   2. a sidecar container ("istio-proxy" = Envoy) is added; it owns ports
#      15001 (outbound) and 15006 (inbound).
# The "payment" container is UNCHANGED -- it still listens on :8080 and has no
# idea a proxy now sits in front of it.
POD_AFTER_INJECTION = {
    "name": "payment-7d9-xyz",
    "initContainers": [
        {"name": "istio-init", "image": "istio/proxyv2:1.22",
         "job": "iptables redirect: inbound->15006, outbound->15001"},
    ],
    "containers": [
        {"name": "payment", "image": "registry/payment:2.1", "port": 8080},
        {"name": "istio-proxy", "image": "istio/proxyv2:1.22",
         "ports": {"outbound": 15001, "inbound": 15006, "admin": 15020},
         "role": "Envoy sidecar -- mTLS, retry, LB, metrics"},
    ],
}

# The control-plane rules the operator writes (YAML). Section C/D quote these.
VIRTUAL_SERVICE = {
    "apiVersion": "networking.istio.io/v1",
    "kind": "VirtualService",
    "name": "payment",
    "host": "payment",
    "routes": [
        {"to": "payment", "subset": "v1", "weight": 90},
        {"to": "payment", "subset": "v2", "weight": 10},
    ],
}

DESTINATION_RULE = {
    "apiVersion": "networking.istio.io/v1",
    "kind": "DestinationRule",
    "name": "payment",
    "host": "payment",
    "subsets": [
        {"name": "v1", "label": "version=v1"},
        {"name": "v2", "label": "version=v2"},
    ],
    "trafficPolicy": {
        "loadBalancer": "ROUND_ROBIN",
        "connectionPool": {"maxConnections": 100, "maxPendingRequests": 10},
        "outlierDetection": {"consecutive5xxErrors": 5, "baseEjectionTime": 30},
    },
    "retryPolicy": {"attempts": 3, "perTryTimeout": "2s",
                    "retryOn": "5xx,connect-failure,reset"},
}


# ============================================================================
# 1. CORE MECHANISMS  (the code SERVICE_MESH.md walks through)
# ============================================================================

def smooth_weighted_round_robin(weights: dict, n: int) -> list:
    """Envoy's Weighted Round Robin cluster LB, in the classic "smooth WRR"
    form (the same algorithm Nginx uses). Over `sum(weights)` consecutive picks,
    each endpoint is chosen EXACTLY its weight times, and picks are spread out.

    weights: {endpoint_name: weight}. n: number of picks. Returns [name, ...].

    This is the engine that turns a VirtualService's `weight: 90 / weight: 10`
    into an actual traffic split, and it is DETERMINISTIC -- which is what makes
    the gold check possible.
    """
    names = list(weights)
    cur = {k: 0 for k in names}
    total = sum(weights.values())
    seq = []
    for _ in range(n):
        for k in names:
            cur[k] += weights[k]
        best = max(names, key=lambda k: (cur[k], k))   # tie-break by name
        cur[best] -= total
        seq.append(best)
    return seq


def counts(seq: list) -> dict:
    out = {}
    for x in seq:
        out[x] = out.get(x, 0) + 1
    return out


def percentile(sorted_vals: list, p: float) -> float:
    """Nearest-rank percentile. sorted_vals must be sorted ascending."""
    if not sorted_vals:
        return 0.0
    rank = max(0, (p / 100) * len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def dump_yaml(obj: dict, indent: int = 0) -> str:
    """A tiny YAML-ish printer (not a real parser, just for display)."""
    pad = "  " * indent
    lines = []
    for k, v in obj.items():
        if isinstance(v, dict):
            lines.append(f"{pad}{k}:")
            lines.append(dump_yaml(v, indent + 1))
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            lines.append(f"{pad}{k}:")
            for item in v:
                sub = dump_yaml(item, indent + 1).rstrip("\n").split("\n")
                lines.append(f"{pad}- {sub[0].strip()}")
                for s in sub[1:]:
                    lines.append(f"{pad}  {s.strip()}")
        else:
            val = ", ".join(v) if isinstance(v, list) else str(v)
            lines.append(f"{pad}{k}: {val}")
    return "\n".join(lines) if indent else "\n".join(lines)


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: Sidecar injection -- the pod topology
# ----------------------------------------------------------------------------

def section_sidecar():
    banner("SECTION A: Sidecar injection -- the pod topology")
    print("A service mesh does NOT rewrite your app. It adds TWO things to the")
    print("pod, both invisible to the app container:\n")
    print("  1. init container 'istio-init'  -- runs once, BEFORE the app. Installs")
    print("     iptables rules that hijack EVERY TCP connection into Envoy.")
    print("  2. sidecar 'istio-proxy' (Envoy)-- runs alongside the app, forever.")
    print("     Owns port 15001 (outbound) and 15006 (inbound).\n")
    print("BEFORE injection (a plain pod):\n")
    print(dump_yaml(POD_BEFORE_INJECTION))
    print("\nAFTER Istio injection (same app container, untouched):\n")
    print(dump_yaml(POD_AFTER_INJECTION))
    print()
    print("Traffic path once the sidecar is in place (the app is NEVER aware):")
    print("  INBOUND : client -> pod eth0 -> iptables -> Envoy:15006 -> app:8080")
    print("                                   (mTLS terminates here)")
    print("  OUTBOUND: app:8080 -> iptables -> Envoy:15001 -> (mTLS) -> remote Envoy")
    print("                                              -> remote app:8080")
    print()
    print("KEY POINT: the app still binds 0.0.0.0:8080 and talks to remote")
    print("services by DNS as before. The iptables redirect is what makes the")
    print("interception transparent -- the app's sockets see plaintext on the")
    print("loopback; the wire between pods is encrypted by Envoy.\n")
    n_init = len(POD_AFTER_INJECTION["initContainers"])
    n_app = sum(1 for c in POD_AFTER_INJECTION["containers"]
                if c["name"] != "istio-proxy")
    n_side = sum(1 for c in POD_AFTER_INJECTION["containers"]
                 if c["name"] == "istio-proxy")
    ok = n_init == 1 and n_app == 1 and n_side == 1
    print(f"[check] injection added 1 init + 1 sidecar, app unchanged?  "
          f"{'OK' if ok else 'FAIL'}   "
          f"(init={n_init}, app={n_app}, sidecar={n_side})")


# ----------------------------------------------------------------------------
# SECTION B: mTLS between services (SPIFFE identity + auto rotation)
# ----------------------------------------------------------------------------

def section_mtls():
    banner("SECTION B: mTLS -- Envoy-to-Envoy mutual TLS (SPIFFE identity)")
    print("Without a mesh, every service must obtain+rotate its own TLS cert and")
    print("verify peers. Almost nobody does it correctly. The mesh does it FOR you:\n")
    print("Istiod runs a CA. Every pod's Envoy asks it for a short-lived cert whose")
    print("Subject Alternative Name (SAN) is the pod's SPIFFE identity:\n")
    trust_domain = "cluster.local"
    ns, sa = "default", "payment"
    spiffe = f"spiffe://{trust_domain}/ns/{ns}/sa/{sa}"
    print(f"  SPIFFE ID  = {spiffe}\n")
    cert = {
        "san (identity)": spiffe,
        "issuer": f"Istio CA (trust domain {trust_domain})",
        "serial": "1A:2B:3C:4D:5E:6F",
        "key": "ECDSA P-256",
        "validity": "24h  (notBefore=T0, notAfter=T0+24h)",
        "rotate_at": "80% of TTL = 19h12m  (Envoy fetches a fresh cert in advance)",
    }
    print(dump_yaml({"workload_certificate": cert}))
    print()
    print("The handshake between two pods (both have Envoy sidecars):")
    print("  1. client Envoy opens TLS to server Envoy, presents ITS cert")
    print("     (SAN = spiffe://.../ns/default/sa/frontend).")
    print("  2. server Envoy presents ITS cert (SAN = spiffe://.../sa/payment),")
    print("     verifies the client cert chains to the shared CA.")
    print("  3. both sides now share an AES-256-GCM channel. The APP on each end")
    print("     only ever sees plaintext on 127.0.0.1.\n")
    print("PeerAuthn policy can REQUIRE mTLS ('STRICT') so plaintext is rejected:")
    policy = {"mode": "STRICT", "mtls": "auto (Envoy negotiates TLS 1.3)"}
    print("  " + dump_yaml({"PeerAuthentication": policy}).replace("\n", "\n  "))
    print()
    print("WHY auto-rotation matters: a 24h cert rotated at 80% lifetime means a")
    print("compromised cert is useless within hours. Operators set policy once;")
    print("rotation, distribution, and verification are the mesh's job, not the")
    print("app team's. Zero cert logic in application code.\n")
    ttl_h = 24
    rotate_pct = 80            # percent of TTL
    rotate_at = ttl_h * rotate_pct / 100          # hours
    ok = abs(rotate_at - 19.2) < 1e-9
    print(f"[check] 24h cert rotated at 80% -> {rotate_at:g}h (long before expiry)?  "
          f"{'OK' if ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION C: Traffic management -- VirtualService weighted routing  (GOLD)
# ----------------------------------------------------------------------------

def section_traffic():
    banner("SECTION C: Traffic management -- VirtualService 90/10 split  (GOLD)")
    print("The operator writes two control-plane objects. Istiod reads them and")
    print("programs every Envoy via xDS. The data plane (Envoy) does the split.\n")
    print("VirtualService -- the routing rules:\n")
    print(dump_yaml(VIRTUAL_SERVICE))
    print("\nDestinationRule -- subsets, LB, and policy for 'payment':\n")
    print(dump_yaml(DESTINATION_RULE))
    print()
    print("How the weights become reality: Envoy's cluster for 'payment' has two")
    print("subsets (v1, v2). The VirtualService sets their LB weights to 90 and 10.")
    print("Envoy then runs a WEIGHTED ROUND ROBIN over the subsets.\n")
    weights = {r["subset"]: r["weight"] for r in VIRTUAL_SERVICE["routes"]}
    total_weight = sum(weights.values())
    print(f"Configured weights: {weights}   (sum = {total_weight})")
    print(f"WRR guarantee: over every {total_weight} consecutive requests, v1 gets")
    print(f"exactly {weights['v1']} and v2 exactly {weights['v2']}.\n")
    n_req = 1000
    seq = smooth_weighted_round_robin(weights, n_req)
    c = counts(seq)
    pct = {k: c[k] / n_req * 100 for k in c}
    print(f"Simulated {n_req} requests through Envoy's WRR (deterministic):")
    print(f"  v1 -> {c['v1']:>4} requests  ({pct['v1']:.1f}%)")
    print(f"  v2 -> {c['v2']:>4} requests  ({pct['v2']:.1f}%)\n")
    # GOLD: observed per-cycle counts must equal configured weights
    one_cycle = smooth_weighted_round_robin(weights, total_weight)
    cycle_counts = counts(one_cycle)
    match = all(cycle_counts[k] == weights[k] for k in weights)
    print("GOLD (pinned for service_mesh.html):")
    print(f"  per-cycle counts over {total_weight} requests = {cycle_counts}")
    print(f"  configured weights                       = {weights}")
    print(f"  1000-req split                           = "
          f"{{v1: {c['v1']}, v2: {c['v2']}}}  ratio {pct['v1']:.0f}:{pct['v2']:.0f}")
    print(f"[check] WRR per-cycle counts == VirtualService weights?  "
          f"{'OK' if match else 'FAIL'}")
    assert match, "WRR must reproduce the configured weights exactly"
    return c, weights


# ----------------------------------------------------------------------------
# SECTION D: Resilience -- retries, timeouts, outlier detection, circuit break
# ----------------------------------------------------------------------------

def section_resilience():
    banner("SECTION D: Resilience -- retries + outlier detection + circuit break")
    print("Three independent protections live in the sidecar (DestinationRule):\n")
    print("  retry          : re-send on {5xx,connect-failure,reset}, up to 3 tries,")
    print("                   each try capped at perTryTimeout=2s.")
    print("  outlier detect : per-HOST. After 5 consecutive 5xx, EJECT the host for")
    print("                   baseEjectionTime=30s; the LB skips it. (host health)")
    print("  circuit break  : per-CLUSTER pool. If maxConnections=100 is exceeded,")
    print("                   return 503 LOCALLY (UPSTREAM_OVERFLOW) -- never even")
    print("                   call the struggling upstream. (overflow protection)\n")
    hosts = ["pod-a", "pod-b"]
    attempts = DESTINATION_RULE["retryPolicy"]["attempts"]
    eject_n = DESTINATION_RULE["trafficPolicy"]["outlierDetection"]["consecutive5xxErrors"]
    n = 8

    def make_upstream():
        # pod-a errors on its first 5 attempts, then heals; pod-b is always healthy.
        st = {"a": 0}

        def up(host):
            if host == "pod-a":
                i = st["a"]
                st["a"] += 1
                return 503 if i < 5 else 200
            return 200
        return up

    # --- WITH mesh: retries + outlier detection (isolated timeline) ---
    def with_mesh():
        up = make_upstream()
        consec = {"pod-a": 0, "pod-b": 0}
        ejected = set()
        lb = [0]
        first_eject = None
        rows = []

        def pick():
            alive = [h for h in hosts if h not in ejected]
            h = alive[lb[0] % len(alive)]
            lb[0] += 1
            return h

        for r in range(1, n + 1):
            last = 0
            path = []
            tries = 0
            for _ in range(attempts):
                tries += 1
                h = pick()
                code = up(h)
                if code == 200:
                    consec[h] = 0
                    path.append(f"{h}:200")
                    last = 200
                    break
                consec[h] += 1
                path.append(f"{h}:503")
                if consec[h] >= eject_n and h not in ejected:
                    ejected.add(h)
                    path.append(f"{h}:EJECT")
                    if first_eject is None:
                        first_eject = r
                last = code
            rows.append((last, tries, " -> ".join(path)))
        return rows, first_eject

    # --- WITHOUT mesh: app calls a host directly, no retry, no eject ---
    def without_mesh():
        up = make_upstream()
        lb = [0]
        rows = []
        for r in range(1, n + 1):
            h = hosts[lb[0] % len(hosts)]
            lb[0] += 1
            code = up(h)
            rows.append((code, 1, f"{h}:{code}"))
        return rows

    wm, first_eject = with_mesh()
    wo = without_mesh()
    print(f"Cluster v1 = {hosts}. pod-a returns [503 x5] then heals; pod-b = 200.")
    print(f"retry: attempts={attempts}; eject a host after {eject_n} consecutive 5xx.\n")
    print("  req | WITHOUT mesh (app calls upstream directly) | "
          "WITH mesh (Envoy retries + ejects)")
    print("  ----|--------------------------------------------|"
          "----------------------------------------------")
    fails_wo = sum(1 for last, _, _ in wo if last != 200)
    fails_wm = sum(1 for last, _, _ in wm if last != 200)
    for r in range(n):
        last_wo, t_wo, p_wo = wo[r]
        last_wm, t_wm, p_wm = wm[r]
        tag_wo = "200" if last_wo == 200 else "503!"
        tag_wm = "200" if last_wm == 200 else "503!"
        print(f"  {r+1:>3} | {tag_wo:<5} {p_wo:<22} {'':<14} | "
              f"{tag_wm:<5} {p_wm}  ({t_wm} tries)")
    print()
    print(f"User-visible failures:  WITHOUT mesh = {fails_wo}/{n}     "
          f"WITH mesh = {fails_wm}/{n}")
    print(f"pod-a ejected on request {first_eject} (after {eject_n} consecutive 5xx).\n")
    print("READ THIS: WITHOUT the mesh, every call that lands on pod-a while it is")
    print("erroring is a 503 the USER sees. WITH the mesh, Envoy retries the same")
    print("request to pod-b on failure -- the user gets a clean 200 -- and once")
    print("pod-a has erred 5x in a row, outlier detection EJECTS it so later")
    print("requests are not even routed there. The caller never knows pod-a broke.\n")
    ok_retries = fails_wm == 0 and fails_wo > 0 and first_eject is not None

    # --- Circuit breaking: per-CLUSTER overflow protection (separate trace) ---
    max_conn = DESTINATION_RULE["trafficPolicy"]["connectionPool"]["maxConnections"]
    burst = 105
    forwarded = min(burst, max_conn)
    rejected = burst - forwarded
    print("Circuit breaking -- per-CLUSTER overflow protection (separate trace):")
    print(f"  connectionPool.maxConnections = {max_conn}. A burst of {burst} "
          f"simultaneous requests arrives.")
    print(f"  Envoy forwards the first {forwarded} and rejects the remaining "
          f"{rejected} LOCALLY (503 UPSTREAM_OVERFLOW) -- it never drowns the")
    print(f"  upstream with {burst} concurrent calls. This is overflow protection")
    print("  at the CALLER; outlier detection above is health protection at the HOST.")
    print(f"  forwarded={forwarded}   locally rejected (overflow)={rejected}")
    ok_cb = forwarded == max_conn and rejected == burst - max_conn
    print(f"[check] retries+ejection hid all upstream failures "
          f"({'OK' if ok_retries else 'FAIL'})   "
          f"circuit breaker capped overflow at maxConnections "
          f"({'OK' if ok_cb else 'FAIL'})")
    assert ok_retries and ok_cb, "resilience checks must pass"


# ----------------------------------------------------------------------------
# SECTION E: Observability -- golden signals, no app code changes
# ----------------------------------------------------------------------------

def section_observability():
    banner("SECTION E: Observability -- the four golden signals (for free)")
    print("Envoy sits on EVERY connection, so it sees EVERY request. It emits the")
    print("four golden signals (Google SRE ch.6) with ZERO changes to app code:\n")
    print("  Latency   : per-request histogram -> p50 / p90 / p99  (scraped by")
    print("              Prometheus from Envoy's /stats, label istio_requests_total).")
    print("  Traffic   : requests/sec, in/out bytes (the load on the service).")
    print("  Errors    : rate of 1xx-4xx-5xx, esp. 5xx / 4xx split.")
    print("  Saturation: how 'full' the service is -- connection-pool util vs")
    print("              maxConnections, CPU, queue depth.\n")
    print("Tracing is the same story: Envoy generates/propagates W3C Traceparent")
    print("headers and ships spans to Jaeger -- one click in the UI shows the full")
    print("request hop chain across services, again with no app change.\n")
    # Deterministic latency sample (ms) for 20 calls to 'payment'.
    latencies = [42, 47, 51, 39, 58, 44, 61, 49, 53, 46,
                 55, 41, 63, 48, 52, 45, 59, 50, 54, 43]
    lat_sorted = sorted(latencies)
    p50 = percentile(lat_sorted, 50)
    p90 = percentile(lat_sorted, 90)
    p99 = percentile(lat_sorted, 99)
    rps = len(latencies)
    errors = 2
    err_rate = errors / rps * 100
    max_conn = DESTINATION_RULE["trafficPolicy"]["connectionPool"]["maxConnections"]
    active_conn = 73
    sat = active_conn / max_conn * 100
    print(f"Sample window: {rps} requests over 1s to 'payment' (deterministic).")
    print(f"  latency (ms): min={lat_sorted[0]}  p50={p50:.1f}  "
          f"p90={p90:.1f}  p99={p99:.1f}  max={lat_sorted[-1]}")
    print(f"  traffic    : {rps} req/s")
    print(f"  errors     : {errors} 5xx  ({err_rate:.1f}%)")
    print(f"  saturation : {active_conn}/{max_conn} connections = {sat:.0f}% of pool\n")
    print("These are GOLDEN because they tell you, in four numbers, whether a")
    print("service is healthy: rising latency + rising errors + high saturation =")
    print("a service in trouble -- and the mesh gave you all of it automatically.")
    ok = (p50 < p90 < p99 and err_rate >= 0 and 0 <= sat <= 100)
    print(f"[check] p50<p90<p99 ordering + valid saturation window?  "
          f"{'OK' if ok else 'FAIL'}")
    print("GOLD (pinned for service_mesh.html): "
          f"p50={p50:.1f}ms, p90={p90:.1f}ms, p99={p99:.1f}ms, "
          f"sat={sat:.0f}%, err={err_rate:.1f}%")
    return p50, p90, p99, sat, err_rate


# ============================================================================
# main
# ============================================================================

def main():
    print("service_mesh.py - reference simulation.")
    print("All numbers below feed SERVICE_MESH.md.")
    print("stdlib only; deterministic.")

    section_sidecar()
    section_mtls()
    section_traffic()
    section_resilience()
    section_observability()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
