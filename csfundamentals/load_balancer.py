"""Load Balancer — ground-truth implementations of core LB algorithms.

Five algorithms covering the spectrum from stateless to stateful routing:

  1. Round Robin           — zero-state sequential assignment
  2. Weighted Round Robin  — nginx smooth weighted RR (interleaved, not bursty)
  3. Least Connections     — routes to fewest active connections (slow-fail aware)
  4. IP Hash               — hash(client_ip) mod N (sticky sessions)
  5. Consistent Hashing    — ring with 300 virtual nodes (minimal key remap)

Plus a health-check simulation showing traffic rerouting around an unhealthy
backend and resuming when it recovers.

Every number printed below is produced by running this file; nothing is
hand-computed.  Capture with:

    python3 load_balancer.py > load_balancer_output.txt 2>/dev/null
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict


# ---------------------------------------------------------------------------
# FNV-1a 32-bit hash — deterministic across Python and JavaScript.
# Used by IP-hash and consistent-hashing so the HTML gold-check reproduces
# identical numbers to this Python source.
# ---------------------------------------------------------------------------

def fnv1a_32(s: str) -> int:
    """Raw FNV-1a 32-bit hash (no finalization)."""
    h = 2166136261
    for byte in s.encode("utf-8"):
        h ^= byte
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def hash32(s: str) -> int:
    """FNV-1a + Murmur3 fmix32 finalization.

    The raw FNV-1a hash has poor avalanche when inputs share a prefix
    (e.g. ``b0#0``, ``b0#1``, ...) which causes consistent-hash ring
    positions to cluster.  The fmix32 finalizer spreads bits uniformly,
    giving balanced ring distributions with 150 virtual nodes.

    Fully deterministic across Python and JavaScript — the HTML gold-check
    reproduces identical values.
    """
    h = fnv1a_32(s)
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


# ---------------------------------------------------------------------------
# Algorithm 1 — Round Robin
# ---------------------------------------------------------------------------

class RoundRobinLB:
    """Stateless cyclic assignment: request i goes to backends[i mod N]."""

    def __init__(self, backends: list[str]):
        self.backends = backends
        self._idx = 0

    def pick(self) -> str:
        backend = self.backends[self._idx % len(self.backends)]
        self._idx += 1
        return backend


def section_round_robin() -> None:
    print("=" * 72)
    print("=== Round Robin — sequential assignment, zero state")
    print("=" * 72)
    backends = ["b0", "b1", "b2"]
    lb = RoundRobinLB(backends)
    print(f"  backends = {backends}")
    print()
    print("  request  ->  backend")
    print("  -------      -------")
    for i in range(1, 7):
        print(f"  {i:>7}  ->  {lb.pick()}")

    lb2 = RoundRobinLB(backends)
    n = 1000
    counts = [0] * len(backends)
    for _ in range(n):
        counts[backends.index(lb2.pick())] += 1

    print()
    print(f"  distribution over {n} requests:")
    print(f"  {'backend':>8}  {'count':>5}  {'pct':>6}")
    print(f"  {'-------':>8}  {'-----':>5}  {'---':>6}")
    for i, b in enumerate(backends):
        print(f"  {b:>8}  {counts[i]:>5}  {counts[i] / n * 100:>5.1f}%")
    spread = max(counts) - min(counts)
    print()
    print(f"  max - min = {spread}   [check] {'OK' if spread <= 1 else 'FAIL'}"
          f"   (+/-1 perfectly even)")
    assert spread <= 1


# ---------------------------------------------------------------------------
# Algorithm 2 — Smooth Weighted Round Robin (nginx algorithm)
# ---------------------------------------------------------------------------

class SmoothWeightedLB:
    """Nginx's smooth weighted round robin.

    Each step: add weights to current_weight, pick the max, subtract total.
    High-weight backends are interleaved across the cycle rather than
    clustered at the start (naive WRR would burst all a's first).
    """

    def __init__(self, backends: list[str], weights: list[int]):
        assert len(backends) == len(weights)
        self.backends = backends
        self.weights = weights
        self.current = [0] * len(backends)
        self._total = sum(weights)

    def pick(self) -> str:
        for i in range(len(self.backends)):
            self.current[i] += self.weights[i]
        best = self.current.index(max(self.current))
        self.current[best] -= self._total
        return self.backends[best]


def section_weighted_round_robin() -> None:
    print()
    print("=" * 72)
    print("=== Weighted Round Robin — nginx smooth weighted (interleaved)")
    print("=" * 72)
    backends = ["a", "b", "c"]
    weights = [5, 1, 1]
    total = sum(weights)
    print(f"  backends = {backends}   weights = {weights}   total = {total}")
    print()

    lb = SmoothWeightedLB(backends, weights)
    print("  step  cw_before      cw_after_add    pick  cw_after_sub")
    print("  ----  ---------      ------------    ----  ------------")
    for step in range(1, total + 1):
        before = list(lb.current)
        picked = lb.pick()
        after_add = [before[i] + weights[i] for i in range(len(backends))]
        after_sub = list(lb.current)
        print(f"  {step:>4}  {str(before):>14}  {str(after_add):>14}"
              f"    {picked:>2}  {str(after_sub):>14}")

    print()
    naive = []
    for b, w in zip(backends, weights):
        naive.extend([b] * w)
    lb2 = SmoothWeightedLB(backends, weights)
    smooth = [lb2.pick() for _ in range(total)]
    print(f"  naive  WRR (1 cycle): {' '.join(naive)}")
    print(f"  smooth WRR (1 cycle): {' '.join(smooth)}")
    print("  smooth WRR spreads the high-weight backend across the cycle")

    lb3 = SmoothWeightedLB(backends, weights)
    n = 1000
    counts = [0] * len(backends)
    for _ in range(n):
        counts[backends.index(lb3.pick())] += 1

    print()
    print(f"  distribution over {n} requests:")
    print(f"  {'backend':>8}  {'count':>5}  {'pct':>6}  {'weight':>6}  {'w_ratio':>7}")
    print(f"  {'-------':>8}  {'-----':>5}  {'---':>6}  {'------':>6}  {'-------':>7}")
    for i, b in enumerate(backends):
        print(f"  {b:>8}  {counts[i]:>5}  {counts[i] / n * 100:>5.1f}%"
              f"  {weights[i]:>6}  {weights[i] / total * 100:>6.1f}%")
    ok = counts == [714, 143, 143]
    print()
    print(f"  counts = {counts}   expected = [714, 143, 143]"
          f"   [check] {'OK' if ok else 'FAIL'}")
    assert ok


# ---------------------------------------------------------------------------
# Algorithm 3 — Least Connections
# ---------------------------------------------------------------------------

def simulate_least_connections(
    n_requests: int, durations: list[int], backends: list[str]
) -> tuple[list[int], list[int], list[tuple[int, list[int], str]]]:
    """Deterministic least-connections simulation.

    Each backend has a fixed *duration* (simulation steps a connection stays
    active before completing).  Fast backends drain quickly -> low active
    count -> attract more new requests.  Slow backends pile up -> high active
    count -> receive fewer requests.
    """
    n = len(durations)
    active = [0] * n
    counts = [0] * n
    schedule: dict[int, list[int]] = defaultdict(list)
    trace: list[tuple[int, list[int], str]] = []
    for t in range(n_requests):
        for bi in schedule.pop(t, []):
            active[bi] -= 1
        target = min(range(n), key=lambda i: (active[i], i))
        active[target] += 1
        counts[target] += 1
        schedule[t + durations[target]].append(target)
        if t < 12:
            trace.append((t, list(active), backends[target]))
    return counts, active, trace


def section_least_connections() -> None:
    print()
    print("=" * 72)
    print("=== Least Connections — routes to fewest active connections")
    print("=" * 72)
    backends = ["fast", "medium", "slow"]
    durations = [2, 5, 20]
    n = 1000
    print(f"  backends  = {backends}")
    print(f"  durations = {durations}  (steps per active connection)")
    print(f"  requests  = {n}")
    print()

    counts, active, trace = simulate_least_connections(n, durations, backends)

    print("  step  active_conns   pick")
    print("  ----  -------------  ------")
    for t, act, picked in trace:
        print(f"  {t:>4}  {str(act):>13}  {picked:>6}")
    print(f"  ... ({n - len(trace)} more steps)")

    print()
    print(f"  distribution over {n} requests:")
    print(f"  {'backend':>8}  {'count':>5}  {'pct':>6}  {'duration':>8}  {'active_end':>10}")
    print(f"  {'-------':>8}  {'-----':>5}  {'---':>6}  {'--------':>8}  {'----------':>10}")
    for i, b in enumerate(backends):
        print(f"  {b:>8}  {counts[i]:>5}  {counts[i] / n * 100:>5.1f}%"
              f"  {durations[i]:>8}  {active[i]:>10}")

    ok = counts[0] > counts[1] > counts[2]
    print()
    print(f"  fast({counts[0]}) > medium({counts[1]}) > slow({counts[2]})"
          f"   [check] {'OK' if ok else 'FAIL'}")
    assert ok, f"least-conn ordering broken: {counts}"


# ---------------------------------------------------------------------------
# Algorithm 4 — IP Hash
# ---------------------------------------------------------------------------

def ip_hash(ip: str, n_backends: int) -> int:
    return hash32(ip) % n_backends


def section_ip_hash() -> None:
    print()
    print("=" * 72)
    print("=== IP Hash — hash(client_ip) mod N (sticky sessions)")
    print("=" * 72)
    backends = ["b0", "b1", "b2"]
    n_be = len(backends)
    print(f"  backends = {backends}   hash = FNV-1a+fmix32   route = hash mod {n_be}")
    print()

    sample_ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3",
                  "192.168.1.50", "172.16.0.99"]
    print("  sample IP            hash       ->  backend")
    print("  ----------          ----------      -------")
    for ip in sample_ips:
        h = hash32(ip)
        print(f"  {ip:>16}  {h:>10}  ->  {backends[h % n_be]}")

    print()
    test_ip = "10.0.0.42"
    h = hash32(test_ip)
    print(f"  stickiness: {test_ip} maps to {backends[h % n_be]} every time"
          f" (hash={h})")

    ips = [f"10.0.{i // 256}.{i % 256}" for i in range(1000)]
    n = len(ips)
    counts = [0] * n_be
    for ip in ips:
        counts[ip_hash(ip, n_be)] += 1

    print()
    print(f"  distribution over {n} unique IPs:")
    print(f"  {'backend':>8}  {'count':>5}  {'pct':>6}")
    print(f"  {'-------':>8}  {'-----':>5}  {'---':>6}")
    for i, b in enumerate(backends):
        print(f"  {b:>8}  {counts[i]:>5}  {counts[i] / n * 100:>5.1f}%")
    spread = max(counts) - min(counts)
    print()
    print(f"  max - min = {spread}   [check] {'OK' if spread < 80 else 'FAIL'}"
          f"   (roughly uniform)")
    assert spread < 80


# ---------------------------------------------------------------------------
# Algorithm 5 — Consistent Hashing
# ---------------------------------------------------------------------------

class ConsistentHashRing:
    """Consistent hash ring with configurable virtual nodes (replicas).

    Each physical node is hashed to *replicas* positions on a 32-bit ring.
    A key maps to the first node clockwise from its hash position.
    Adding/removing a node remaps only ~1/N of all keys (vs ~N/(N+1) for
    naive modulo hashing).
    """

    def __init__(self, replicas: int = 300):
        self.replicas = replicas
        self.ring: dict[int, str] = {}
        self._sorted: list[int] = []

    def _position(self, label: str) -> int:
        return hash32(label)

    def add_node(self, node: str) -> None:
        for i in range(self.replicas):
            pos = self._position(f"{node}#{i}")
            self.ring[pos] = node
        self._sorted = sorted(self.ring)

    def remove_node(self, node: str) -> None:
        for i in range(self.replicas):
            pos = self._position(f"{node}#{i}")
            self.ring.pop(pos, None)
        self._sorted = sorted(self.ring)

    def get_node(self, key: str) -> str | None:
        if not self.ring:
            return None
        pos = self._position(key)
        idx = bisect.bisect(self._sorted, pos)
        if idx == len(self._sorted):
            idx = 0
        return self.ring[self._sorted[idx]]


def section_consistent_hashing() -> None:
    print()
    print("=" * 72)
    print("=== Consistent Hashing — ring with virtual nodes")
    print("=" * 72)
    nodes = ["b0", "b1", "b2"]
    replicas = 300
    ring = ConsistentHashRing(replicas=replicas)
    for node in nodes:
        ring.add_node(node)
    print(f"  nodes = {nodes}   replicas_per_node = {replicas}"
          f"   ring_positions = {len(nodes) * replicas}")
    print()

    keys = [f"user-{i:04d}" for i in range(1000)]
    n = len(keys)

    assignment = {k: ring.get_node(k) for k in keys}
    counts = {node: sum(1 for v in assignment.values() if v == node) for node in nodes}

    print(f"  distribution over {n} keys:")
    print(f"  {'node':>6}  {'count':>5}  {'pct':>6}")
    print(f"  {'----':>6}  {'-----':>5}  {'---':>6}")
    for node in nodes:
        print(f"  {node:>6}  {counts[node]:>5}  {counts[node] / n * 100:>5.1f}%")

    mean = n / len(nodes)
    variance = sum((counts[node] - mean) ** 2 for node in nodes) / len(nodes)
    std = math.sqrt(variance)
    print()
    print(f"  ideal per node = {mean:.1f}   std_dev = {std:.1f}"
          f"   [check] {'OK' if std < 40 else 'FAIL'} (balanced)")
    assert std < 60

    print()
    print("  --- remap analysis: add node b3 ---")
    old = dict(assignment)
    ring.add_node("b3")
    new = {k: ring.get_node(k) for k in keys}
    moved = sum(1 for k in keys if old[k] != new[k])
    print(f"  keys remapped: {moved} / {n}  ({moved / n * 100:.1f}%)")
    print(f"  ideal (1/(N+1)): {n / (len(nodes) + 1):.0f}  ({100 / (len(nodes) + 1):.1f}%)")
    ok_ch = 200 <= moved <= 400
    print(f"  [check] {'OK' if ok_ch else 'FAIL'} (consistent hash remaps ~1/4 of keys)")
    assert ok_ch

    print()
    print("  --- comparison: naive modulo hashing, add 4th node ---")
    mod_before = {k: hash32(k) % 3 for k in keys}
    mod_after = {k: hash32(k) % 4 for k in keys}
    mod_moved = sum(1 for k in keys if mod_before[k] != mod_after[k])
    print(f"  modulo hash remapped: {mod_moved} / {n}  ({mod_moved / n * 100:.1f}%)")
    print(f"  consistent  remapped: {moved} / {n}  ({moved / n * 100:.1f}%)")
    print(f"  consistent hashing remaps {mod_moved / moved:.1f}x fewer keys"
          f" than modulo hashing")


# ---------------------------------------------------------------------------
# Health Check Simulation
# ---------------------------------------------------------------------------

class HealthCheckedLB:
    """Round-robin LB that skips unhealthy backends.

    The rotation index still advances through unhealthy nodes so that when
    one recovers it rejoins the natural cycle without manual re-indexing.
    """

    def __init__(self, backends: list[str]):
        self.backends = backends
        self.healthy = [True] * len(backends)
        self._idx = 0

    def set_health(self, idx: int, healthy: bool) -> None:
        self.healthy[idx] = healthy

    def pick(self) -> tuple[int | None, str | None]:
        for _ in range(len(self.backends)):
            idx = self._idx % len(self.backends)
            self._idx += 1
            if self.healthy[idx]:
                return idx, self.backends[idx]
        return None, None


def section_health_check() -> None:
    print()
    print("=" * 72)
    print("=== Health Check Simulation — traffic rerouting around failures")
    print("=" * 72)
    backends = ["b0", "b1", "b2"]
    lb = HealthCheckedLB(backends)
    print(f"  backends = {backends}")
    print()

    req_counter = [0]

    def run_phase(label: str, n: int) -> list[int]:
        print(f"  Phase: {label}")
        print(f"  {'req':>4}  ->  backend   healthy")
        print(f"  {'---':>4}      -------   -------")
        counts = [0] * len(backends)
        for _ in range(n):
            req_counter[0] += 1
            idx, backend = lb.pick()
            if idx is not None:
                counts[idx] += 1
            h = "YES" if lb.healthy[idx] else "NO" if idx is not None else "ALL DOWN"
            print(f"  {req_counter[0]:>4}  ->  {backend or '---':>6}"
                  f"    {h}")
        print("  distribution: " + "  ".join(
            f"{b}={counts[i]}" for i, b in enumerate(backends)))
        print()
        return counts

    p1 = run_phase("all healthy, 6 requests via round-robin", 6)
    assert p1 == [2, 2, 2]
    print(f"  [check] OK   (even distribution: {p1})")
    print()

    lb.set_health(1, False)
    print("  ** b1 marked UNHEALTHY **")
    print()
    p2 = run_phase("b1 unhealthy, 6 requests (should skip b1)", 6)
    assert p2 == [3, 0, 3]
    print(f"  [check] OK   (b1 received 0 traffic: {p2})")
    print()

    lb.set_health(1, True)
    print("  ** b1 recovered (HEALTHY) **")
    print()
    p3 = run_phase("b1 recovered, 6 requests (back in rotation)", 6)
    assert p3 == [2, 2, 2]
    print(f"  [check] OK   (b1 back in rotation: {p3})")


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    section_round_robin()
    section_weighted_round_robin()
    section_least_connections()
    section_ip_hash()
    section_consistent_hashing()
    section_health_check()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
