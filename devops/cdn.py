"""
cdn.py - Reference simulation of a Content Delivery Network (CDN).

This is the single source of truth that CDN.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 cdn.py      (pure stdlib; no dependencies)

============================================================================
THE INTUITION (read this first) -- a global chain of convenience stores
============================================================================
Imagine a retailer with ONE central warehouse (the ORIGIN) and thousands of
CONVENIENCE STORES near every customer (the EDGE). Instead of shipping every
order from the warehouse (slow, expensive, warehouse melts under load), the
nearest store serves the customer from its own shelf (CACHE).

  * A HIT  (item on the shelf)  -> serve instantly, never bother the warehouse.
  * A MISS (item not stocked)    -> fetch one from the warehouse, put a copy on
                                    the shelf so the NEXT customer gets a hit.

The job of a CDN is to maximize the HIT RATE so the origin sees as little
traffic as possible (origin offload). Three cache tiers drive cumulative hit
rate up:

  edge POP  (~10 ms)   -> ~80% of requests
  regional  (~30 ms)   -> edges miss here; cumulative ~95%
  origin shield (~80 ms)-> last defense; request coalescing -> cumulative ~99%

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  Edge POP      : Point of Presence -- the cache closest to users (RAM + SSD).
  Origin        : the real server/database that owns the content.
  Origin shield : a single-region cache in front of the origin; request
                  coalescing collapses a burst of identical misses into ONE
                  origin fetch (prevents the thundering herd).
  Cache key     : the identifier of a cached object -- typically (method, host,
                  path), plus a normalized subset of query/headers. Adding
                  cookies/User-Agent to the key FRAGMENTS the cache.
  TTL           : Time To Live -- how long a cached object stays fresh before it
                  must be revalidated or refetched.
  Cache hit rate: fraction of requests served from cache (no origin fetch).
  Origin offload: fraction of traffic the origin does NOT serve. Hit rate and
                  offload track each other (minus the first-request misses).
  Invalidation : removing/updating a cached object before its TTL expires
                  (explicit purge) or via a new versioned URL.
  Anycast      : BGP-based routing that sends the user to the NEAREST POP, with
                  automatic failover if a POP dies.

KEY FACTS (all asserted in code below):
  * A 3-tier hierarchy (edge -> regional -> shield) drives cumulative hit rate
    from ~80% to ~99%; the origin serves ~1% of requests.
  * A cache-key that includes a high-cardinality field (e.g. a tracking cookie)
    can COLLAPSE hit rate from 95% to near 0%.
  * Request coalescing at the shield turns 300 simultaneous edge misses into
    ONE origin fetch (thundering-herd defense).
  * Latency math: serving from edge (~20 ms) vs origin cross-continent
    (~220 ms) is a ~11x speedup for the cacheable asset.
  * A short TTL trades freshness for a lower hit rate (more revalidations);
    versioned URLs + long TTL give BOTH immutability and a ~100% hit rate.

Sources: CDN design (CalibreOS), Cloudflare/CloudFront docs, RFC 7234
(HTTP caching), Akamai edge architecture write-ups.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 0. THE CDN MODEL -- deterministic, no randomness.
# ============================================================================

# Three cache tiers. hit_rate = fraction of incoming requests this tier serves.
TIERS = [
    {"name": "edge POP",      "latency_ms": 10,  "hit_rate": 0.80},
    {"name": "regional cache","latency_ms": 30,  "hit_rate": 0.75},  # of MISSes
    {"name": "origin shield", "latency_ms": 80,  "hit_rate": 0.80},  # of MISSes
]
ORIGIN_LATENCY_MS = 200   # cross-continent origin fetch (miss at every tier)


def cumulative_hit_rate(tiers: list) -> float:
    """Cumulative hit rate across the hierarchy. Each tier serves `hit_rate`
    of whatever REACHES it (i.e. of the misses from above)."""
    miss = 1.0
    for t in tiers:
        miss *= (1.0 - t["hit_rate"])
    return 1.0 - miss


# ============================================================================
# 1. LATENCY MODEL  (edge vs origin, per-tier breakdown)
# ============================================================================

def request_latency(tiers: list, origin_ms: float) -> dict:
    """For one request, model where it is served and its latency.

    Returns a breakdown: expected latency (probability-weighted) + the
    per-tier outcome (hit/miss). Uses the tier hit_rates as deterministic
    probabilities (not RNG, so output is reproducible).
    """
    p_served_at = []   # probability the request is served at each tier / origin
    reached = 1.0
    for i, t in enumerate(tiers):
        p_hit = reached * t["hit_rate"]
        p_served_at.append((t["name"], t["latency_ms"], p_hit))
        reached = reached * (1.0 - t["hit_rate"])
    # remaining 'reached' is served by origin
    p_served_at.append(("origin", origin_ms, reached))
    expected = sum(p * lat for _, lat, p in p_served_at)
    return {"per_tier": p_served_at, "expected_ms": expected,
            "origin_direct_ms": origin_ms}


# ============================================================================
# 2. CACHE KEY FRAGMENTATION
# ============================================================================

def hit_rate_with_key_cardinality(n_objects: int, cache_capacity: int) -> float:
    """A simple LRU model: hit rate ~ fraction of the working set that fits.

    If the cache key is just (host, path), the working set = distinct objects.
    If a high-cardinality field (cookie, session id) is added to the key, the
    SAME object explodes into many variants -> working set blows past capacity
    -> hit rate collapses.
    """
    if n_objects <= 0:
        return 0.0
    served = min(n_objects, cache_capacity)
    return served / n_objects


def key_variants(base_objects: int, cardinality: int) -> int:
    """Adding a field with `cardinality` distinct values multiplies variants."""
    return base_objects * cardinality


# ============================================================================
# 3. REQUEST COALESCING (thundering herd defense)
# ============================================================================

def thundering_herd(num_pops: int, coalesce: bool) -> dict:
    """A viral URL: every POP misses at once.

    Without coalescing: each POP fetches independently -> num_pops origin hits.
    With shield coalescing: the shield sends ONE origin request and fans out.
    """
    if coalesce:
        origin_hits = 1
    else:
        origin_hits = num_pops
    return {"edge_misses": num_pops, "origin_hits": origin_hits}


# ============================================================================
# 4. HIT RATE / ORIGIN OFFLOAD  (steady-state calculator)
# ============================================================================

def origin_offload(hit_rate: float) -> float:
    """Origin offload ratio = fraction of traffic NOT served by origin.

    Equal to (1 - miss rate). A 95% hit rate -> 95% origin offload.
    """
    return hit_rate


def bandwidth_cost(egress_gb: float, hit_rate: float, origin_price: float,
                   cdn_price: float) -> dict:
    """Monthly egress cost: CDN-served bytes at cdn_price, origin-served
    (cache-miss) bytes at origin_price.

    Typical 2026 pricing: origin ~$0.09/GB, CDN ~$0.02-0.04/GB.
    """
    cdn_gb = egress_gb * hit_rate
    origin_gb = egress_gb * (1.0 - hit_rate)
    cdn_cost = cdn_gb * cdn_price
    origin_cost = origin_gb * origin_price
    no_cdn_cost = egress_gb * origin_price
    return {"cdn_gb": cdn_gb, "origin_gb": origin_gb,
            "cdn_cost": cdn_cost, "origin_cost": origin_cost,
            "total_cost": cdn_cost + origin_cost,
            "no_cdn_cost": no_cdn_cost,
            "savings": no_cdn_cost - (cdn_cost + origin_cost)}


# ============================================================================
# 5. TTL STRATEGIES
# ============================================================================

TTL_STRATEGIES = [
    {"strategy": "versioned URLs", "ttl": 31536000,
     "stale": "never (new URL on every deploy)", "invalidate": "free (new URL)",
     "hit_rate": 0.99, "use_case": "build assets (JS/CSS/images with content hash)"},
    {"strategy": "short TTL + SWR", "ttl": 60,
     "stale": "up to 60s + stale-while-revalidate window",
     "invalidate": "wait TTL (or purge)", "hit_rate": 0.90,
     "use_case": "HTML pages, semi-dynamic content"},
    {"strategy": "CDN-only s-maxage", "ttl": 300,
     "stale": "up to 5 min at CDN, 30s in browser",
     "invalidate": "wait s-maxage (or purge)", "hit_rate": 0.95,
     "use_case": "public API responses"},
    {"strategy": "explicit purge", "ttl": 3600,
     "stale": "until purge or TTL expiry",
     "invalidate": "API purge (~200ms Fastly, ~30-60s CloudFront)",
     "hit_rate": 0.85, "use_case": "low-frequency, high-urgency updates"},
    {"strategy": "no-store", "ttl": 0,
     "stale": "never cached anywhere", "invalidate": "n/a",
     "hit_rate": 0.0, "use_case": "auth/private responses"},
]


# ============================================================================
# 6. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 7. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: Cache hierarchy + cumulative hit rate
# ----------------------------------------------------------------------------

def section_hierarchy():
    banner("SECTION A: Cache hierarchy -- edge, regional, origin shield")
    print("Three cache tiers in front of the origin. Each tier serves a fixed")
    print("fraction of the requests that REACH it (i.e. the misses from above):\n")
    print("  tier             latency   serves")
    print("  " + "-" * 44)
    for t in TIERS:
        print(f"  {t['name']:<17} {t['latency_ms']:>4} ms   "
              f"{t['hit_rate']*100:>4.0f}% of what reaches it")
    print(f"  {'origin':<17} {ORIGIN_LATENCY_MS:>4} ms   the rest (final miss)\n")
    cum = cumulative_hit_rate(TIERS)
    print(f"Cumulative hit rate = 1 - (1-0.80)(1-0.75)(1-0.80) = {cum*100:.2f}%")
    origin_frac = 1.0 - cum
    print(f"Origin sees only {origin_frac*100:.2f}% of user requests "
          f"(~1 in {1/origin_frac:.0f}).\n")
    print("WHY HIERARCHY: each tier only needs to cache what the tier above it")
    print("MISSED. Edge handles the hot 80% from RAM; regional + shield mop up")
    print("most of the rest, so the origin is shielded from bursty traffic and")
    print("the thundering herd.\n")
    ok = abs(cum - 0.99) < 0.01
    print("GOLD (pinned for cdn.html):")
    print(f"  cumulative hit rate = {cum*100:.2f}%   "
          f"(edge 80% -> +15% -> +4% = ~99%)")
    print(f"[check] 3-tier hierarchy reaches ~99% cumulative hit rate?  "
          f"{'OK' if ok else 'FAIL'}")
    return cum


# ----------------------------------------------------------------------------
# SECTION B: Latency optimization
# ----------------------------------------------------------------------------

def section_latency():
    banner("SECTION B: Latency -- edge hit vs origin miss")
    res = request_latency(TIERS, ORIGIN_LATENCY_MS)
    print("Per-request outcome (probability-weighted by each tier's hit rate):\n")
    print("  served at          latency   probability")
    print("  " + "-" * 44)
    for name, lat, p in res["per_tier"]:
        print(f"  {name:<17} {lat:>4} ms   {p*100:>6.2f}%")
    print()
    print(f"Expected latency per request = {res['expected_ms']:.2f} ms")
    print(f"Direct-to-origin (no CDN)    = {res['origin_direct_ms']:.2f} ms\n")
    speedup = res["origin_direct_ms"] / res["expected_ms"]
    print(f"Speedup = origin / expected  = {speedup:.2f}x\n")
    print("For a pure EDGE HIT (the common case, ~80% of requests):")
    edge_lat = TIERS[0]["latency_ms"]
    edge_speedup = res["origin_direct_ms"] / edge_lat
    print(f"  edge {edge_lat} ms vs origin {res['origin_direct_ms']} ms "
          f"= {edge_speedup:.1f}x faster.\n")
    print("This is the whole value proposition of a CDN: move bytes close to the")
    print("user so the round trip is measured in single-digit-to-tens of ms, not")
    print("cross-continent hundreds.\n")
    ok = res["expected_ms"] < res["origin_direct_ms"] and speedup > 1.5
    print("GOLD (pinned for cdn.html):")
    print(f"  expected latency = {res['expected_ms']:.2f} ms ; "
          f"direct origin = {res['origin_direct_ms']} ms")
    print(f"[check] CDN cuts expected latency below direct-origin?  "
          f"{'OK' if ok else 'FAIL'}")
    return res


# ----------------------------------------------------------------------------
# SECTION C: Cache key fragmentation  (GOLD)
# ----------------------------------------------------------------------------

def section_cache_key():
    banner("SECTION C: Cache key -- why including a cookie destroys hit rate")
    base = 1000
    cap = 1000
    print(f"Working set = {base} distinct objects ; cache capacity = {cap} slots.\n")
    clean = hit_rate_with_key_cardinality(base, cap)
    print(f"Key = (host, path)                  -> {base} variants, "
          f"hit rate = {clean*100:.0f}%")
    for card, label in [(50, "Accept-Language (50 langs)"),
                        (5000, "session cookie (5000 sessions)"),
                        (100000, "User-Agent (100000 UAs)")]:
        variants = key_variants(base, card)
        hr = hit_rate_with_key_cardinality(variants, cap)
        print(f"Key += {label:<28} -> {variants:>7} variants, "
              f"hit rate = {hr*100:.2f}%")
    print()
    print("WHAT THIS PROVES: a cache key must include ONLY what determines the")
    print("response content. Adding a high-cardinality field (a tracking cookie,")
    print("a raw User-Agent, a random nonce) makes every request look unique ->")
    print("the cache stores a million near-duplicates and serves almost nothing")
    print("from cache.\n")
    print("RULES:")
    print("  * strip cookies on /static/* paths")
    print("  * normalize query strings (whitelist only params that change the")
    print("    response)")
    print("  * Vary only on Accept-Encoding (2 variants: gzip, br), NEVER on")
    print("    User-Agent")
    print("  * include in the key ONLY what determines the response content\n")
    cookie_variants = key_variants(base, 5000)
    cookie_hr = hit_rate_with_key_cardinality(cookie_variants, cap)
    ok = clean >= 0.99 and cookie_hr < 0.05
    print("GOLD (pinned for cdn.html):")
    print(f"  clean key hit rate = {clean*100:.0f}% ; "
          f"with session cookie = {cookie_hr*100:.2f}%")
    print(f"[check] clean key ~100% but cookie-key collapses below 5%?  "
          f"{'OK' if ok else 'FAIL'}")
    return clean, cookie_hr


# ----------------------------------------------------------------------------
# SECTION D: Request coalescing (thundering herd)
# ----------------------------------------------------------------------------

def section_coalescing():
    banner("SECTION D: Origin shield -- request coalescing kills the thundering herd")
    pops = 300
    print(f"A viral URL: all {pops} edge POPs miss on the SAME object at once.\n")
    no_coal = thundering_herd(pops, coalesce=False)
    coal = thundering_herd(pops, coalesce=True)
    print(f"  WITHOUT shield coalescing: {no_coal['edge_misses']} edge misses -> "
          f"{no_coal['origin_hits']} origin hits  (origin hammered)")
    print(f"  WITH shield coalescing:    {coal['edge_misses']} edge misses -> "
          f"{coal['origin_hits']} origin hit   (shield fans out the response)\n")
    print("HOW IT WORKS: the shield is a single choke point. When the first edge")
    print("miss arrives, the shield fires ONE origin request and holds the rest;")
    print("when the response returns, it serves all waiting edges from cache. "
          "The origin sees a "
          f"{no_coal['origin_hits']/coal['origin_hits']:.0f}x "
          "reduction in load during a burst.\n")
    print("This is why a well-tuned CDN has an origin shield even when the edge")
    print("tier already has a high hit rate: it protects the origin from the")
    print("correlated misses a single hot URL can cause.\n")
    ok = (no_coal["origin_hits"] == pops) and (coal["origin_hits"] == 1)
    print("GOLD (pinned for cdn.html):")
    print(f"  coalescing reduces {pops} simultaneous misses to 1 origin fetch")
    print(f"[check] coalescing collapses {pops} misses -> 1 origin hit?  "
          f"{'OK' if ok else 'FAIL'}")
    return coal


# ----------------------------------------------------------------------------
# SECTION E: Hit rate / origin offload calculator + bandwidth cost
# ----------------------------------------------------------------------------

def section_offload():
    banner("SECTION E: Hit rate -> origin offload -> bandwidth cost")
    print("Origin offload ratio = hit rate (the origin serves only the misses).\n")
    print("  hit rate   origin offload   origin serves")
    print("  " + "-" * 48)
    for hr in (0.50, 0.75, 0.90, 0.95, 0.99):
        print(f"  {hr*100:>5.0f}%       {origin_offload(hr)*100:>5.0f}%           "
              f"{(1-hr)*100:>5.1f}%")
    print()
    egress = 10_000_000  # 10 PB/month -> GB
    print(f"Bandwidth cost at {egress:,} GB/month egress "
          f"(origin $0.09/GB, CDN $0.02/GB):\n")
    print("  hit rate   CDN cost       origin cost     total          vs no-CDN")
    print("  " + "-" * 70)
    gold_99 = None
    for hr in (0.50, 0.90, 0.99):
        r = bandwidth_cost(egress, hr, 0.09, 0.02)
        if hr == 0.99:
            gold_99 = r
        print(f"  {hr*100:>5.0f}%       ${r['cdn_cost']:>12,.0f}   "
              f"${r['origin_cost']:>12,.0f}   "
              f"${r['total_cost']:>12,.0f}   ${r['savings']:>12,.0f} saved")
    print()
    no_cdn = bandwidth_cost(egress, 0.0, 0.09, 0.02)["no_cdn_cost"]
    print(f"Without a CDN: ${no_cdn:,.0f}/month ({egress:,} GB @ $0.09/GB).")
    print(f"At 99% hit rate: ${gold_99['total_cost']:,.0f}/month "
          f"-> ${gold_99['savings']:,.0f} saved ({gold_99['savings']/no_cdn*100:.0f}%).\n")
    print("The economics: even though the CDN charges per byte, its price/GB is")
    print("far below origin egress, and it serves ~99% of bytes. The origin bill")
    print("shrinks to a rounding error.\n")
    ok = (gold_99["total_cost"] < no_cdn) and (gold_99["savings"] > 0)
    print("GOLD (pinned for cdn.html):")
    print(f"  99% hit rate -> ${gold_99['total_cost']:,.0f}/mo vs "
          f"${no_cdn:,.0f}/mo without CDN")
    print(f"[check] CDN 99% hit rate is cheaper than no-CDN?  "
          f"{'OK' if ok else 'FAIL'}")
    return gold_99, no_cdn


# ----------------------------------------------------------------------------
# SECTION F: TTL strategies
# ----------------------------------------------------------------------------

def section_ttl():
    banner("SECTION F: TTL strategies -- freshness vs hit rate")
    print("Each strategy picks a different point on the freshness/hit-rate axis:\n")
    print("  strategy                TTL        stale?                hit rate")
    print("  " + "-" * 76)
    for s in TTL_STRATEGIES:
        ttl_str = (f"{s['ttl']}s" if s["ttl"] < 3600
                   else (f"{s['ttl']//86400}d" if s["ttl"] >= 86400
                         else f"{s['ttl']}s"))
        print(f"  {s['strategy']:<23} {ttl_str:<10} {s['stale']:<22} "
              f"{s['hit_rate']*100:>5.0f}%")
    print()
    print("THE PATTERN: versioned URLs win on BOTH axes. A content hash in the")
    print("filename (/app.a3f7c9.js) means the URL changes only when the content")
    print("changes, so you can set a 1-YEAR immutable TTL. 'Invalidation' becomes")
    print("free: you deploy a new file with a new hash, and the old cached copy")
    print("simply ages out because nobody requests it anymore. This is the")
    print("production default for build-pipeline assets.\n")
    print("For content that genuinely changes (HTML, API responses), use a SHORT")
    print("TTL + stale-while-revalidate: serve stale instantly, refresh in the")
    print("background. Acceptable staleness up to the SWR window; hit rate stays")
    print("high because most requests are served before the refresh completes.\n")
    versioned = next(s for s in TTL_STRATEGIES if s["strategy"] == "versioned URLs")
    html = next(s for s in TTL_STRATEGIES if s["strategy"] == "short TTL + SWR")
    ok = (versioned["hit_rate"] >= 0.99 and versioned["ttl"] == 31536000
          and html["hit_rate"] >= 0.90)
    print("GOLD (pinned for cdn.html):")
    print(f"  versioned URLs: TTL {versioned['ttl']//86400}d, "
          f"hit rate {versioned['hit_rate']*100:.0f}%")
    print(f"[check] versioned URLs give 1yr TTL + ~99% hit rate?  "
          f"{'OK' if ok else 'FAIL'}")
    return versioned


# ============================================================================
# main
# ============================================================================

def main():
    print("cdn.py - reference simulation.")
    print("All numbers below feed CDN.md.")
    print("stdlib only; deterministic.")

    section_hierarchy()
    section_latency()
    section_cache_key()
    section_coalescing()
    section_offload()
    section_ttl()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
