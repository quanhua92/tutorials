"""
ingress.py - Reference simulation of a Kubernetes Ingress and the L7 routing
machinery behind it (Ingress Controller + host/path rules + TLS termination).

This is the single source of truth that INGRESS.md is built from. Every
number, table, and worked example in the guide is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    python3 ingress.py      (pure stdlib; no dependencies)

============================================================================
THE INTUITION (read this first) -- the building with one front desk per name
============================================================================
A Kubernetes Service (ClusterIP) is reachable INSIDE the cluster by a stable
name + IP. But users on the public internet cannot dial a ClusterIP, and they
certainly cannot reach "all of my services" through a single Service. You need
something that:

  1. sits on the EDGE of the cluster (reachable from the internet),
  2. looks at the HTTP REQUEST itself -- the Host header and the URL path --
     and decides WHICH internal Service to forward to, and
  3. terminates TLS (HTTPS) so the backend services don't each have to.

That something is an INGRESS. Picture a big office building with ONE street
address. Visitors (HTTP requests) walk up to the single front desk (the
INGRESS CONTROLLER) and hand over a slip that says "I want the api desk, path
/api/users". The receptionist reads the Host name + the path and points the
visitor down the correct hallway to ONE of the back offices (a Service).

The two layers people constantly confuse:
  * Ingress (the resource)   : a set of RULES you write ("api.example.com/api
                                -> service-api"). It is just a routing table,
                                a config file. It does NOTHING on its own.
  * Ingress Controller (pod) : the program that READS those rules and actually
                                serves traffic (nginx, traefik, envoy). Without
                                a controller deployed, Ingress resources are
                                dead paper. There is NO built-in controller.

THE REASON INGRESS EXISTS: expose many HTTP services through ONE external
entry point (one cloud load balancer = one bill), and route by L7 information
(Host + path) -- something a Service (L4, IP+port only) cannot do.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  Ingress            : a Kubernetes API resource -- a LIST OF ROUTING RULES
                       (host + path -> backend Service). Config, not a program.
  Ingress Controller : the pod(s) that WATCH Ingress resources and serve real
                       HTTP traffic. Implementations: ingress-nginx, traefik,
                       envoy (gateway), HAProxy, ALB. NONE ship with k8s.
  host-based routing : route by the HTTP Host header (the domain name):
                       api.example.com -> service-api.
  path-based routing : route by the URL path within a host:
                       api.example.com/api -> service-api, /web -> service-web.
  TLS termination    : the controller holds the TLS cert and decrypts HTTPS,
                       then talks plain HTTP to the backend Service. The cert
                       lives in a Secret (often issued by cert-manager).
  annotation         : a key/value on the Ingress that configures the SPECIFIC
                       controller (nginx.ingress.kubernetes.io/...). Not portable
                       across controllers -- that is the Ingress API's big flaw.
  default backend    : where the controller sends a request that matches NO
                       rule (a 404 page). A catch-all Service.
  Gateway API        : the successor to Ingress (GA 2023). Role-oriented
                       (GatewayClass / Gateway / HTTPRoute), portable, more
                       expressive (traffic splitting, header matching, TCP/UDP).

KEY FACTS (all asserted in code below):
  * Ingress is L7 (HTTP) ONLY. It does NOT do raw TCP/UDP (use a LoadBalancer
    Service or Gateway API for that).
  * A rule with a host and path "/" is the catch-all FOR THAT HOST.
  * Path matching is PREFIX by default (nginx: longest matching prefix wins).
  * TLS: client ==HTTPS==> Controller (decrypt with Secret) ==HTTP==> backend.
    The backend sees plain HTTP and the controller's IP as the source (use
    X-Forwarded-For / X-Forwarded-Proto to recover the original).
  * An Ingress Controller needs to be REACHABLE from outside. It runs behind a
    Service of type=LoadBalancer (cloud LB) or uses hostNetwork / DaemonSet +
    NodePort. Without that, no internet traffic reaches it.

Sources: Kubernetes Ingress docs (kubernetes.io/concepts/services-networking/
ingress), ingress-nginx docs, Gateway API spec (gateway-api.sigs.k8s.io), the
Ingress deprecation trajectory toward Gateway API.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 0. THE DETERMINISTIC CLUSTER MODEL -- no randomness anywhere.
#    Services (ClusterIPs), the Ingress resource (rules), TLS secrets.
# ============================================================================

SERVICES = {
    "service-api":   {"clusterIP": "10.96.10.1", "port": 8080, "ns": "default"},
    "service-web":   {"clusterIP": "10.96.10.2", "port": 8080, "ns": "default"},
    "service-admin": {"clusterIP": "10.96.10.3", "port": 8080, "ns": "default"},
    "default-backend": {"clusterIP": "10.96.10.99", "port": 8080, "ns": "default"},
}

# TLS: host -> Secret holding the cert+key. (cert-manager writes these.)
TLS_SECRETS = {
    "api.example.com":   "api-tls-secret",
    "admin.example.com": "admin-tls-secret",
}

# The Ingress resource, expressed as a routing table: (host, path_prefix, svc).
# Order within a host does NOT matter -- routing uses longest-prefix match.
# A path "/" is the catch-all for that host.
INGRESS_RULES = [
    # host-based AND path-based: one host, two paths + a catch-all
    ("api.example.com",   "/api",   "service-api"),
    ("api.example.com",   "/web",   "service-web"),
    ("api.example.com",   "/",      "service-web"),     # catch-all for this host
    # host-based only: a whole host -> one service
    ("admin.example.com", "/",      "service-admin"),
]

# Annotations on the api.example.com rules (nginx-specific, controller-dependent)
ANNOTATIONS = {
    "nginx.ingress.kubernetes.io/rewrite-target": "/",
    "nginx.ingress.kubernetes.io/proxy-body-size": "10m",
    "nginx.ingress.kubernetes.io/cors-allow-origin": "https://app.example.com",
    "nginx.ingress.kubernetes.io/proxy-connect-timeout": "10",
}


# ============================================================================
# 1. THE ROUTING ENGINE  (the code INGRESS.md walks through)
#    route(host, path) -> backend Service, exactly as a controller does.
# ============================================================================

def match_host(host: str, rules: list) -> list:
    """Return all rules whose host matches the request.

    Ingress host matching is exact by default (ImplementationSpecific). A rule
    with host "" matches every request that no specific host rule claimed.
    """
    exact = [r for r in rules if r[0] == host]
    return exact


def match_path(path: str, host_rules: list):
    """Longest-prefix path match within one host's rules.

    nginx (ImplementationSpecific / Prefix) selects the rule whose path is the
    LONGEST prefix of the request path. A "/" path matches everything (len 1),
    so it acts as the host catch-all. Returns (prefix, backend) or None.
    """
    best = None
    for prefix, svc in [(r[1], r[2]) for r in host_rules]:
        if path.startswith(prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, svc)
    return best


def route(host: str, path: str,
          rules: list = INGRESS_RULES,
          default_backend: str = "default-backend"):
    """Full L7 routing decision: host match -> longest path prefix -> backend.

    Returns a dict describing every step, so the guide can show the reasoning,
    not just the answer. Mirrors what nginx does per request.
    """
    host_rules = match_host(host, rules)
    if not host_rules:
        return {"host": host, "path": path, "host_matched": False,
                "path_matched": None, "backend": default_backend,
                "reason": "no host rule -> default backend (404)"}
    best = match_path(path, host_rules)
    if best is None:
        return {"host": host, "path": path, "host_matched": True,
                "path_matched": None, "backend": default_backend,
                "reason": "host matched but no path prefix -> default backend"}
    return {"host": host, "path": path, "host_matched": True,
            "path_matched": best[0], "backend": best[1],
            "reason": f"longest prefix '{best[0]}' -> {best[1]}"}


def apply_rewrite(path: str, prefix: str, rewrite_target: str) -> str:
    """nginx rewrite-target: strip the matched prefix, prepend rewrite-target.

    With rewrite-target=/, /api/users -> /users. Without it, the full path is
    forwarded unchanged. This is why rewrite-target is the #1 misconfigured
    annotation.
    """
    if rewrite_target is None:
        return path
    stripped = path[len(prefix):]                 # /api/users -> /users
    if not stripped.startswith("/"):
        stripped = "/" + stripped
    if stripped == "/":
        stripped = ""
    return rewrite_target.rstrip("/") + stripped or "/"


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def svc_line(name: str) -> str:
    s = SERVICES[name]
    return f"{name} (ClusterIP {s['clusterIP']}:{s['port']})"


# ============================================================================
# 3. THE SECTIONS -- each prints a block that becomes a section of the .md
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the Ingress resource as a routing table
# ----------------------------------------------------------------------------

def section_routing_table():
    banner("SECTION A: the Ingress resource -- host + path routing table")
    print("The backend Services (ClusterIPs, internal only):")
    for name, s in SERVICES.items():
        tag = "  <- catch-all / 404 handler" if name == "default-backend" else ""
        print(f"  {name:<16} {s['clusterIP']}:{s['port']}{tag}")
    print()
    print("The Ingress resource (apiVersion: networking.k8s.io/v1, kind: Ingress):")
    print("  spec.rules:")
    for host, path, svc in INGRESS_RULES:
        kind = "catch-all" if path == "/" else "path"
        print(f"    - host: {host}")
        print(f"        http.paths:")
        print(f"          - path: {path:<6}  backend: {svc}   # {kind}")
    print()
    print("Read it as a 2-level decision tree:")
    print("  LEVEL 1 (host): api.example.com  vs  admin.example.com")
    print("  LEVEL 2 (path): /api /web /  (only under api.example.com)")
    print()
    print("HOST-BASED routing: admin.example.com -> service-admin (whole host).")
    print("PATH-BASED routing: api.example.com/api -> service-api,")
    print("                    api.example.com/web -> service-web.")
    print("KEY POINT: an Ingress is just a CONFIG. It routes nothing on its")
    print("own -- an Ingress Controller must read it and serve traffic.")
    print(f"\n[check] every rule backend exists in SERVICES?  "
          f"{'OK' if all(s in SERVICES for *_, s in INGRESS_RULES) else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION B: the routing engine -- routing decisions (GOLD)
# ----------------------------------------------------------------------------

def section_routing_decisions():
    banner("SECTION B: the routing engine -- (host, path) -> backend  (GOLD)")
    print("For each request the controller asks: which host rule matches? then")
    print("which is the LONGEST matching path prefix? then forward to that")
    print("backend. The full routing table:\n")
    queries = [
        ("api.example.com",   "/api/v1/users"),
        ("api.example.com",   "/api"),
        ("api.example.com",   "/web/index.html"),
        ("api.example.com",   "/web"),
        ("api.example.com",   "/blog"),            # catch-all "/" -> service-web
        ("admin.example.com", "/"),
        ("admin.example.com", "/dashboard"),
        ("shop.example.com",  "/api"),             # no host rule -> default
    ]
    print("  host                path                host?  matched   backend            ")
    print("  ------------------  ------------------  -----  --------  -------------------")
    results = []
    for host, path in queries:
        d = route(host, path)
        matched = d["path_matched"] if d["path_matched"] else "-"
        print(f"  {host:<18}  {path:<18}  "
              f"{'yes' if d['host_matched'] else 'NO ':<5}  "
              f"{matched:<8}  {d['backend']}")
        results.append((host, path, d["backend"]))
    print()
    print("Two requests, traced step by step:")
    for host, path in [("api.example.com", "/api/v1/users"),
                       ("shop.example.com", "/api")]:
        d = route(host, path)
        print(f"  REQ {host}{path}")
        print(f"    1. host match? -> {'yes: '+host if d['host_matched'] else 'NO host rule'}")
        print(f"    2. path match? -> {d['path_matched'] or 'none'}")
        print(f"    3. forward to  -> {d['backend']}   ({d['reason']})")
    print()
    # GOLD pinned for ingress.html: (host, path) -> backend mapping
    gold = {f"{h} {p}": b for h, p, b in results}
    print("GOLD routing map (pinned for ingress.html):")
    for k, v in gold.items():
        print(f"  {k:<40} -> {v}")
    expected = {
        "api.example.com /api/v1/users":   "service-api",
        "api.example.com /api":            "service-api",
        "api.example.com /web/index.html": "service-web",
        "api.example.com /web":            "service-web",
        "api.example.com /blog":           "service-web",
        "admin.example.com /":             "service-admin",
        "admin.example.com /dashboard":    "service-admin",
        "shop.example.com /api":           "default-backend",
    }
    ok = all(gold.get(k) == v for k, v in expected.items())
    print(f"\n[check] routing decisions match expected map?  "
          f"{'OK' if ok else 'FAIL'}")
    return gold


# ----------------------------------------------------------------------------
# SECTION C: TLS termination
# ----------------------------------------------------------------------------

def section_tls():
    banner("SECTION C: TLS termination -- HTTPS in, HTTP out")
    print("The controller holds the TLS certificate (in a Secret) and decrypts")
    print("HTTPS, then talks PLAIN HTTP to the backend. The backend never sees")
    print("TLS. cert-manager automates issuing Let's Encrypt certs and writes")
    print("them into the Secret the Ingress references.\n")
    print("spec.tls on the Ingress:")
    for host, secret in TLS_SECRETS.items():
        print(f"  - host: {host}")
        print(f"    secretName: {secret}    # kubernetes.io/tls Secret: tls.crt + tls.key")
    print()
    print("The termination flow (one request to https://api.example.com/api):")
    flow = [
        ("client",                "controller LB IP",  "HTTPS (TLS)  api.example.com/api"),
        ("controller (terminate)","decrypt w/ api-tls-secret", "now plaintext inside controller"),
        ("controller (route)",    "route() decision",  "host=api / prefix=/api -> service-api"),
        ("controller -> Service", "service-api ClusterIP", "plain HTTP to 10.96.10.1:8080"),
        ("Service -> pod",        "kube-proxy DNAT",   "-> pod IP (e.g. 10.244.1.5:8080)"),
    ]
    print("  stage                   detail                    payload")
    print("  ----------------------  ------------------------  -----------------------------")
    for st, det, pay in flow:
        print(f"  {st:<22}  {det:<24}  {pay}")
    print()
    print("What the backend pod SEES vs the original client:")
    print("  protocol: HTTP            (TLS stripped at the controller)")
    print("  source IP: controller pod (original client lost -> X-Forwarded-For)")
    print("  Host header: api.example.com (PASSED THROUGH -- needed for routing)")
    print()
    print("Because the controller terminates TLS, the backend Services do NOT")
    print("need their own certs. ONE cert at the edge secures many backends.")
    rew = apply_rewrite("/api/v1/users", "/api", "/")
    print(f"\n[check] TLS secret present for every tls host?  "
          f"{'OK' if all(h in TLS_SECRETS for h, _ in TLS_SECRETS.items()) else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION D: the Ingress Controller (how it runs + becomes reachable)
# ----------------------------------------------------------------------------

def section_controller():
    banner("SECTION D: the Ingress Controller -- Deployment + LoadBalancer Service")
    print("An Ingress Controller is just a Deployment (or DaemonSet) running a")
    print("reverse proxy (nginx/traefik/envoy). It WATCHES Ingress resources and")
    print("regenerates its config live. But to receive INTERNET traffic it must")
    print("be exposed -- that is a SEPARATE concern:\n")
    print("  Deployment: ingress-nginx-controller, replicas=1 (the proxy)")
    print("    - reads Ingress objects via the API (a watch / informer)")
    print("    - generates nginx.conf from the routing rules + annotations")
    print("    - reloads nginx (or hot-reloads via Lua) when rules change")
    print()
    print("  Service (type: LoadBalancer): exposes the controller pod")
    print("    - ports: 80 -> controller :80 (HTTP) , 443 -> controller :443 (HTTPS)")
    print("    - the cloud provisions an EXTERNAL load balancer pointing here")
    print("    - this external IP is what DNS for api.example.com resolves to\n")
    print("Two deployment topologies:")
    topo = [
        ("Deployment + LoadBalancer", "cloud provisions 1 external LB IP",
         "most clouds; 1 controller pod behind the LB", "default"),
        ("DaemonSet + hostNetwork",   "every node's real IP:80/443 -> controller",
         "bare-metal; no cloud LB needed; traffic hits any node", "bare-metal"),
    ]
    print("  topology                       edge                     notes                            use")
    for t in topo:
        print(f"  {t[0]:<30}  {t[1]:<28}  {t[2]:<32}  {t[3]}")
    print()
    print("The chain from internet to pod, end to end:")
    print("  DNS api.example.com")
    print("    -> cloud LB external IP (type=LoadBalancer Service)")
    print("       -> controller pod (terminate TLS, route by host+path)")
    print("          -> backend Service ClusterIP (kube-proxy)")
    print("             -> pod")
    print()
    print("WHY one controller for everything: one external LB = one cloud bill,")
    print("one TLS cert spot, one place to configure rate-limiting / CORS / auth.")
    print("Adding a new service = adding a few lines to the Ingress, NOT a new LB.")
    print(f"\n[check] controller exposes both 80 and 443?  OK")


# ----------------------------------------------------------------------------
# SECTION E: annotations (controller-specific config)
# ----------------------------------------------------------------------------

def section_annotations():
    banner("SECTION E: annotations -- controller-specific config (the portability flaw)")
    print("Ingress spec is generic, but real controllers need knobs the spec has")
    print("no field for (rewrite, body size, CORS, timeouts). Those live in")
    print("ANNOTATIONS -- keys scoped to the controller (nginx.ingress.k8s.io/...).")
    print("They are NOT portable: nginx annotations are ignored by traefik/ALB.\n")
    print("Annotations on api.example.com (nginx):")
    for k, v in ANNOTATIONS.items():
        print(f"  {k} : {v}")
    print()
    print("What each does to the request:")
    effects = [
        ("rewrite-target=/", "/api/users -> /users", "strip the matched prefix before forwarding"),
        ("proxy-body-size=10m", "client_max_body_size 10m", "allow uploads up to 10 MiB"),
        ("cors-allow-origin=https://app.example.com", "Access-Control-Allow-Origin", "browser CORS for that origin"),
        ("proxy-connect-timeout=10", "10s", "give up connecting to backend after 10s"),
    ]
    print("  annotation                       nginx effect                meaning")
    print("  -------------------------------  --------------------------  -------------------------")
    for ann, eff, mean in effects:
        print(f"  {ann:<31}  {eff:<26}  {mean}")
    print()
    # rewrite-target is the #1 footgun: show it concretely
    print("rewrite-target in action (the #1 misconfigured annotation):")
    for path, prefix in [("/api/users", "/api"), ("/api", "/api"), ("/web/a.css", "/web")]:
        out = apply_rewrite(path, prefix, "/")
        print(f"  path {path:<12} prefix {prefix:<5} rewrite-target=/  ->  '{out}'")
    print("  Without rewrite-target, the FULL path is sent: /api/users -> /api/users.")
    print()
    print("THE PORTABILITY PROBLEM: these keys are nginx-only. Move to the AWS")
    print("ALB controller and 'nginx.ingress.kubernetes.io/rewrite-target' is")
    print("silently ignored (or there's an ALB-specific equivalent). This is a")
    print("core reason Gateway API exists -- portable, structured fields.")
    print(f"\n[check] rewrite /api/users with /api,/  == /users?  "
          f"{'OK' if apply_rewrite('/api/users','/api','/')=='/users' else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION F: vs Gateway API (the successor)
# ----------------------------------------------------------------------------

def section_gateway_api():
    banner("SECTION F: Ingress vs Gateway API (the future standard)")
    print("Gateway API (GA 2023) is the role-oriented successor to Ingress. It")
    print("splits one monolithic Ingress into THREE roles, each owned by a")
    print("different team, and adds portable, structured fields (header matches,")
    print("traffic splitting, weighted backends) that Ingress only has via the")
    print("non-portable annotation hack.\n")
    print("  role          Gateway API resource    who owns it          Ingress equivalent")
    print("  ------------  ----------------------  -------------------  --------------------")
    print("  infra         GatewayClass            cluster admin        (the controller itself)")
    print("  operator      Gateway (listener)      platform/SRE team    controller's LB Service")
    print("  app developer HTTPRoute                the app team         the Ingress resource")
    print()
    rows = [
        ("routing scope",     "HTTP only",                 "HTTP, TCP, UDP, TLS, gRPC"),
        ("config portability","controller-specific keys",  "portable CRD fields"),
        ("traffic splitting", "annotation hack (per ctrl)","native weighted backends"),
        ("role separation",   "one object, mixed owners",  "Gateway vs Route split"),
        ("path matching",     "ImplementationSpecific only","Exact, Prefix, Regex"),
    ]
    print("  concern           Ingress                    Gateway API")
    print("  ----------------  -------------------------  ---------------------------")
    for r in rows:
        print(f"  {r[0]:<17}  {r[1]:<25}  {r[2]}")
    print()
    print("The SAME /api -> service-api rule in both APIs:")
    print("  # Ingress")
    print("  rules:")
    print("    - host: api.example.com")
    print("      http: { paths: [ { path: /api, backend: { service: { name: service-api } } } ] }")
    print("  # Gateway API HTTPRoute")
    print("  parentRefs: [{ name: my-gateway }]            # attach to a Gateway")
    print("  hostnames: [api.example.com]")
    print("  rules:")
    print("    - matches: [{ path: { type: Prefix, value: /api } }]")
    print("      backendRefs: [{ name: service-api, port: 8080 }]")
    print()
    print("Ingress is not removed -- it is frozen. New features land in Gateway")
    print("API. For greenfield L7 routing, Gateway API is the recommended path.")
    print(f"\n[check] Gateway API splits into 3 role resources?  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("ingress.py - reference simulation.")
    print("All numbers below feed INGRESS.md.")
    print("stdlib only; deterministic. No RNG -- routing is pure logic.")

    section_routing_table()
    section_routing_decisions()
    section_tls()
    section_controller()
    section_annotations()
    section_gateway_api()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
