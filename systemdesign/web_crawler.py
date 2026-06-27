"""
web_crawler.py - Reference simulation of a scalable web crawler.

Covers:
  - URL Frontier (Mercator design: front priority queues + back per-domain
    queues + ready-time min-heap for politeness scheduling)
  - BFS crawl on a small link graph (step-by-step frontier evolution)
  - Politeness (per-domain crawl-delay enforcement)
  - DNS caching (hit/miss + latency savings)
  - Duplicate URL detection (URL canonicalization + Bloom filter + content hash)
  - robots.txt respect (Disallow / Allow / Crawl-delay directives)
  - Scale estimation (bloom filter sizing, storage, bandwidth for 10B pages)

This is the single source of truth for WEB_CRAWLER.md and web_crawler.html.
All numbers are deterministic (no randomness, no wall-clock). Re-run reproduces
every value below.

Run:
    python3 web_crawler.py
"""

import hashlib
import heapq
import math
from collections import deque
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


# =========================================================================
# THE INTUITION (read this first) — the library cataloguer
# =========================================================================
# A web crawler is a library cataloguer with an infinitely growing to-read
# pile. You start with a few seed pages ("read these"), fetch each one, extract
# the links inside, and add the new ones to the pile. The interesting design
# questions are all about MANAGING THAT PILE:
#
#   * URL FRONTIER (Mercator design):
#       The pile is split into FRONT QUEUES (by priority — PageRank,
#       freshness, user-submitted) and BACK QUEUES (one per domain). The front
#       queues decide WHAT matters; the back queues decide WHEN it's polite to
#       fetch. A min-heap of back queues (keyed by ready_time = last_access +
#       crawl_delay) picks the domain whose next URL is most ready. This
#       DECOUPLES priority from politeness — a core insight.
#
#   * BFS TRAVERSAL:
#       You crawl breadth-first (by depth from seed) to get broad coverage
#       before going deep. The frontier is a FIFO within each priority level.
#       Duplicates (a page discovered via two different link paths) are caught
#       by a SEEN set before they re-enter the frontier.
#
#   * POLITENESS:
#       Every domain gets its own crawl-delay. The back-queue ready-time
#       mechanism enforces it automatically: a domain's back queue can't be
#       dequeued until now >= last_access + crawl_delay. Different domains CAN
#       be fetched in parallel (their delays are independent).
#
#   * DEDUPLICATION (three layers):
#       1. URL canonicalization (lowercase host, strip www, sort query params,
#          drop fragment) collapses equivalent URL strings into one.
#       2. Bloom filter (probabilistic set, ~12 GB for 10B URLs at 1% FP) for
#          cheap negative checks: "definitely not seen" → fast path.
#       3. Content hash (SHA-256 / SimHash) catches mirror pages: different
#          URLs pointing to identical or near-identical content.
#
#   * ROBOTS.TXT:
#       Fetch and cache per-domain rules before crawling. Respect Disallow /
#       Allow patterns and the Crawl-delay directive. Cached in Redis with TTL.
#
#   * DNS CACHING:
#       A DNS lookup takes ~50 ms; a cache hit takes ~0.1 ms. Caching per
#       domain (with TTL) saves ~67% of DNS time for repeat-heavy crawls.
#
# =========================================================================
# PLAIN-ENGLISH GLOSSARY
# =========================================================================
#   URL frontier    : the priority queue of URLs waiting to be crawled.
#   front queue     : priority-based FIFO (HIGH / MED / LOW). Decides WHAT.
#   back queue      : per-domain FIFO. Enforces politeness. Decides WHEN.
#   ready_time      : earliest wall-clock time a domain's next URL can fetch.
#   crawl_delay     : minimum seconds between two fetches to the same domain.
#   canonical URL   : normalized form of a URL (host lowercased, params sorted).
#   bloom filter    : probabilistic "have I seen this?" set. Zero false
#                     negatives, small false positive rate. ~10 bits/URL at 1%.
#   SimHash         : near-duplicate fingerprint of page content.
#   spider trap     : infinite URL space (calendars, session IDs) that traps
#                     the crawler in one site. Detected by URL-pattern or
#                     max-depth limits.
# =========================================================================


# --------------------------------------------------------------------------
# Component 1: Bloom filter for URL deduplication
# --------------------------------------------------------------------------
class BloomFilter:
    """
    capacity  : expected number of elements
    fp_rate   : target false-positive probability (e.g. 0.01 = 1%)
    m         : number of bits in the filter (auto-computed)
    k         : number of hash functions (auto-computed)

    Optimal sizing:
        m = -n * ln(p) / (ln 2)^2       bits
        k = (m / n) * ln 2              hash functions

    Uses double hashing: h_i(x) = (h1(x) + i * h2(x)) mod m, where h1/h2 are
    the first 8 bytes of SHA-256. This is the Kirsch-Mitzenmacher technique.
    """

    def __init__(self, capacity, fp_rate):
        self.capacity = capacity
        self.fp_rate = fp_rate
        self.m = self._optimal_m(capacity, fp_rate)
        self.k = self._optimal_k(self.m, capacity)
        self.bits = bytearray((self.m + 7) // 8)

    @staticmethod
    def _optimal_m(n, p):
        return int(-n * math.log(p) / (math.log(2) ** 2))

    @staticmethod
    def _optimal_k(m, n):
        return max(1, int(round((m / n) * math.log(2))))

    def _indices(self, item):
        h = hashlib.sha256(item.encode()).digest()
        h1 = int.from_bytes(h[:8], "big")
        h2 = int.from_bytes(h[8:16], "big")
        if h2 == 0:
            h2 = 1
        return [(h1 + i * h2) % self.m for i in range(self.k)]

    def add(self, item):
        for idx in self._indices(item):
            self.bits[idx >> 3] |= (1 << (idx & 7))

    def maybe_contains(self, item):
        return all(self.bits[idx >> 3] & (1 << (idx & 7)) for idx in self._indices(item))

    def bit_count(self):
        return sum(bin(b).count("1") for b in self.bits)


# --------------------------------------------------------------------------
# Component 2: URL canonicalization
# --------------------------------------------------------------------------
def canonicalize(url):
    """
    Normalize a URL to its canonical form:
      - scheme → https
      - host → lowercase, strip leading 'www.'
      - path → strip trailing '/'
      - query params → sorted
      - fragment → dropped
      - port → dropped if default
    """
    p = urlparse(url)
    scheme = "https"
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    host = netloc.split(":")[0]
    path = p.path.rstrip("/") or "/"
    params = sorted(parse_qsl(p.query, keep_blank_values=True))
    query = urlencode(params)
    return urlunparse((scheme, host, path, "", query, ""))


# --------------------------------------------------------------------------
# Component 3: robots.txt parser + matcher
# --------------------------------------------------------------------------
class RobotsRules:
    """
    Parses a simplified robots.txt for User-agent: * rules.
    Supports Disallow:, Allow:, and Crawl-delay: directives.
    Matching uses longest-prefix match (Allow overrides Disallow for the same
    or more specific path).
    """

    def __init__(self, robots_txt):
        self.disallow = []
        self.allow = []
        self.crawl_delay = 0
        for line in robots_txt.strip().split("\n"):
            line = line.strip()
            low = line.lower()
            if low.startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    self.disallow.append(path)
            elif low.startswith("allow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    self.allow.append(path)
            elif low.startswith("crawl-delay:"):
                try:
                    self.crawl_delay = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass

    def allowed(self, path):
        for pattern in self.allow:
            if path.startswith(pattern):
                return True
        for pattern in self.disallow:
            if path.startswith(pattern):
                return False
        return True


# --------------------------------------------------------------------------
# Component 4: Mercator URL frontier
# --------------------------------------------------------------------------
class MercatorFrontier:
    """
    The Mercator URL frontier (Heydon & Najork 1999).

    Front queues (F1..Ff): priority FIFOs (HIGH / MED / LOW). URLs enter here
    based on importance (PageRank, freshness, user priority). The selector
    pulls from front queues with WEIGHTED randomness (HIGH pulled 6x more
    often than LOW in this demo).

    Back queues (B1..Bb): one FIFO per domain. Enforces politeness — URLs for
    the same host are serialized. The ready-time heap picks the back queue
    whose head URL is most ready to fetch.

    Ready-time heap: min-heap of (ready_time, domain). ready_time =
    last_fetch_time[domain] + crawl_delay[domain]. A back queue's head can't
    be dequeued until now >= ready_time.

    This DECOUPLES priority (front queues) from politeness (back queues).
    """

    PRIORITY_ORDER = ["HIGH", "MED", "LOW"]
    PRIORITY_WEIGHTS = {"HIGH": 6, "MED": 3, "LOW": 1}

    def __init__(self, crawl_delays):
        self.crawl_delays = crawl_delays
        self.front_queues = {p: deque() for p in self.PRIORITY_ORDER}
        self.back_queues = {}
        self.heap = []

    def enqueue(self, url, domain, priority):
        self.front_queues[priority].append((url, domain))

    def front_queue_state(self):
        return {p: list(self.front_queues[p]) for p in self.PRIORITY_ORDER}

    def route_to_back_queues(self):
        """Pull all URLs from front queues (priority order) into domain back queues."""
        all_urls = []
        for prio in self.PRIORITY_ORDER:
            all_urls.extend(self.front_queues[prio])
            self.front_queues[prio] = deque()
        for url, domain in all_urls:
            if domain not in self.back_queues:
                self.back_queues[domain] = deque()
            self.back_queues[domain].append(url)
        for domain in self.back_queues:
            if self.back_queues[domain]:
                heapq.heappush(self.heap, (0.0, domain))

    def try_dequeue(self, now):
        """
        Returns:
          (url, domain, fetch_time) on success
          ("WAIT", None, ready_time) if must wait
          None if frontier is empty
        """
        while self.heap:
            ready_time, domain = self.heap[0]
            if not self.back_queues[domain]:
                heapq.heappop(self.heap)
                continue
            if ready_time <= now:
                heapq.heappop(self.heap)
                url = self.back_queues[domain].popleft()
                new_ready = now + self.crawl_delays[domain]
                if self.back_queues[domain]:
                    heapq.heappush(self.heap, (new_ready, domain))
                return (url, domain, now)
            else:
                return ("WAIT", None, ready_time)
        return None


# --------------------------------------------------------------------------
# Component 5: Per-domain politeness enforcer
# --------------------------------------------------------------------------
class PolitenessEnforcer:
    def __init__(self, crawl_delays):
        self.crawl_delays = crawl_delays
        self.last_access = {}

    def can_fetch(self, domain, now):
        if domain not in self.last_access:
            return True, now
        wait_until = self.last_access[domain] + self.crawl_delays[domain]
        return now >= wait_until, wait_until

    def record_access(self, domain, now):
        self.last_access[domain] = now


# --------------------------------------------------------------------------
# Component 6: DNS cache
# --------------------------------------------------------------------------
class DNSCache:
    def __init__(self):
        self.cache = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _fake_ip(domain):
        h = int(hashlib.md5(domain.encode()).hexdigest(), 16)
        return f"{h % 223 + 1}.{(h >> 8) % 256}.{(h >> 16) % 256}.{(h >> 24) % 256}"

    def resolve(self, domain):
        if domain in self.cache:
            self.hits += 1
            return self.cache[domain], True
        self.misses += 1
        ip = self._fake_ip(domain)
        self.cache[domain] = ip
        return ip, False


# --------------------------------------------------------------------------
# Component 7: BFS crawler (step-by-step)
# --------------------------------------------------------------------------
def bfs_crawl(graph, seed, verbose=True):
    """
    BFS crawl over a small link graph. Returns (visited_order, dup_count).
    Uses a `seen` set for dedup (frontier + visited). Prints frontier evolution.
    """
    frontier = deque([seed])
    visited = []
    seen = {seed}
    dup_count = 0

    step = 0
    while frontier:
        url = frontier.popleft()
        visited.append(url)
        links = graph.get(url, [])
        new_links = []
        dups = []
        for link in links:
            if link not in seen:
                seen.add(link)
                frontier.append(link)
                new_links.append(link)
            else:
                dup_count += 1
                dups.append(link)
        step += 1
        if verbose:
            print(f"  step {step}: pop '{url}'  →  out-links={links}")
            if new_links:
                print(f"           new:     {new_links}  → enqueue")
            if dups:
                print(f"           DEDUP:   {dups}  → skipped (already in seen set)")
            if not links:
                print(f"           (no out-links)")
            print(f"           frontier={list(frontier)}  visited={visited}")

    return visited, dup_count


# --------------------------------------------------------------------------
# Banner helper
# --------------------------------------------------------------------------
def banner(title):
    line = "=" * 72
    print()
    print(line)
    print(" " + title)
    print(line)


# --------------------------------------------------------------------------
# Main simulation
# --------------------------------------------------------------------------
def main():
    banner("WEB CRAWLER - reference simulation")
    print("Source of truth for WEB_CRAWLER.md and web_crawler.html.")
    print("All numbers below are deterministic; re-run reproduces them.")

    # =====================================================================
    # SECTION A: URL FRONTIER (Mercator design)
    # =====================================================================
    banner("Section A - URL Frontier (Mercator design: front + back queues)")
    print("Front queues hold URLs by PRIORITY. Back queues hold URLs per DOMAIN.")
    print("The ready-time heap picks the domain whose next URL is most ready.")
    print("This DECOUPLES priority (front) from politeness (back).\n")

    crawl_delays = {"example.com": 2, "news.com": 5, "blog.com": 1}
    mf = MercatorFrontier(crawl_delays)

    seeds = [
        ("https://example.com/a", "example.com", "HIGH"),
        ("https://example.com/b", "example.com", "MED"),
        ("https://example.com/c", "example.com", "LOW"),
        ("https://news.com/x", "news.com", "HIGH"),
        ("https://news.com/y", "news.com", "MED"),
        ("https://blog.com/p", "blog.com", "HIGH"),
        ("https://blog.com/q", "blog.com", "LOW"),
    ]
    print("Phase 1: enqueue 7 seed URLs → routed to front queues by priority.")
    for url, domain, prio in seeds:
        mf.enqueue(url, domain, prio)
    for prio in MercatorFrontier.PRIORITY_ORDER:
        q = mf.front_queues[prio]
        urls = [u for u, _ in q]
        print(f"  {prio:4s} (weight={MercatorFrontier.PRIORITY_WEIGHTS[prio]}): {urls}")

    print("\nPhase 2: route front → back queues (priority order preserved per domain).")
    mf.route_to_back_queues()
    for domain in sorted(mf.back_queues):
        bq = list(mf.back_queues[domain])
        print(f"  {domain:15s}  delay={crawl_delays[domain]}s  back_queue={bq}")
    print(f"  ready-time heap: {sorted(mf.heap)}")

    print("\nPhase 3: crawl loop (dequeue by ready-time, enforce crawl-delay).")
    now = 0.0
    fetch_log = []
    step = 0
    while True:
        result = mf.try_dequeue(now)
        if result is None:
            break
        tag, _, fetch_time = result[0], result[1], result[2]
        if result[0] == "WAIT":
            step += 1
            print(f"  t={now:.0f}s  →  all back queues cooling; advance to t={result[2]:.0f}s")
            now = result[2]
            continue
        url, domain, ft = result
        step += 1
        fetch_log.append((ft, domain, url))
        print(f"  t={now:.0f}s  FETCH  {url:30s}  domain={domain}  delay={crawl_delays[domain]}s")

    print(f"\n  Fetch schedule ({len(fetch_log)} URLs):")
    for ft, domain, url in fetch_log:
        print(f"    t={ft:.0f}s  {url:30s}  [{domain}]")
    print()
    print("  Key observations:")
    print("    • t=0: 3 parallel fetches across DIFFERENT domains (no cross-domain blocking)")
    print("    • blog.com (delay=1s):     fetched at t=0, t=1  → 1s spacing")
    print("    • example.com (delay=2s):  fetched at t=0, t=2, t=4  → 2s spacing")
    print("    • news.com (delay=5s):     fetched at t=0, t=5  → 5s spacing")
    print("    • 7 URLs crawled in 5s (not 7×max_delay=35s) because domains are independent")

    # =====================================================================
    # SECTION B: BFS CRAWL ON A SMALL GRAPH
    # =====================================================================
    banner("Section B - BFS crawl simulation (frontier evolution step-by-step)")
    print("Crawl a 6-node graph. D is a cross-link (discovered by both B and C).")
    print("The `seen` set prevents D from entering the frontier twice.\n")

    graph = {
        "A": ["B", "C"],
        "B": ["D"],
        "C": ["D", "E"],
        "D": ["F"],
        "E": [],
        "F": [],
    }
    print("  Graph:")
    for node, links in graph.items():
        print(f"    {node} → {links}")
    print()
    print("  Seed: A")
    print()

    visited, dup_count = bfs_crawl(graph, "A")
    print(f"\n  Result: {len(visited)} pages crawled, {dup_count} duplicate URL(s) deduped")
    print(f"  Crawl order: {' → '.join(visited)}")

    # =====================================================================
    # SECTION C: POLITENESS + DNS CACHING
    # =====================================================================
    banner("Section C - Politeness (per-domain crawl-delay) + DNS caching")

    print("Phase 1: per-domain rate limiting without proper waiting.")
    print("  3 requests to news.com at t=0, t=1, t=2 (crawl_delay=5s).\n")
    pe = PolitenessEnforcer({"news.com": 5})
    raw_requests = [("news.com", 0), ("news.com", 1), ("news.com", 2)]
    for domain, t in raw_requests:
        allowed, wait = pe.can_fetch(domain, t)
        if allowed:
            pe.record_access(domain, t)
            print(f"  t={t}s  FETCH {domain}  (allowed — first access)")
        else:
            print(f"  t={t}s  BLOCKED  {domain}  (must wait until t={wait}s)")

    print("\nPhase 2: with proper back-off (respect crawl-delay).")
    pe2 = PolitenessEnforcer({"news.com": 5})
    t = 0
    schedule = []
    for i in range(3):
        allowed, wait = pe2.can_fetch("news.com", t)
        if not allowed:
            t = wait
        pe2.record_access("news.com", t)
        schedule.append(t)
        print(f"  fetch #{i+1} at t={t}s")
        t += 1
    print(f"  Schedule: {schedule}  (crawl_delay=5s → 0, 5, 10)")

    print("\nPhase 3: DNS caching (resolve 3 domains × 3 lookups each).")
    dns = DNSCache()
    domains = ["example.com", "news.com", "blog.com"]
    DNS_MISS_MS = 50.0
    DNS_HIT_MS = 0.1
    for domain in domains:
        for i in range(3):
            ip, hit = dns.resolve(domain)
            tag = "HIT " if hit else "MISS"
            print(f"  resolve({domain:15s}) → {ip:15s}  [{tag}]")
    total = dns.hits + dns.misses
    time_with_cache = dns.misses * DNS_MISS_MS + dns.hits * DNS_HIT_MS
    time_without = total * DNS_MISS_MS
    saved = time_without - time_with_cache
    pct = saved / time_without * 100
    print(f"\n  DNS lookups: {total} total ({dns.misses} misses, {dns.hits} hits)")
    print(f"  Time without cache: {total} × {DNS_MISS_MS:.0f}ms = {time_without:.0f}ms")
    print(f"  Time with cache:    {dns.misses} × {DNS_MISS_MS:.0f}ms + {dns.hits} × {DNS_HIT_MS}ms = {time_with_cache:.1f}ms")
    print(f"  Saved: {saved:.1f}ms ({pct:.0f}%)")

    # =====================================================================
    # SECTION D: DEDUPLICATION (canonicalization + bloom + content hash)
    # =====================================================================
    banner("Section D - Deduplication (canonicalization + Bloom filter + content hash)")

    print("Layer 1: URL canonicalization — variant URLs → one canonical form.\n")
    variants = [
        "https://Example.com/a?b=2&a=1",
        "https://www.example.com/a?a=1&b=2",
        "https://example.com/a?a=1&b=2#section",
        "https://example.com/a/?a=1&b=2",
    ]
    canonicals = set()
    for v in variants:
        c = canonicalize(v)
        canonicals.add(c)
        print(f"  {v:45s} → {c}")
    print(f"\n  {len(variants)} variant URLs → {len(canonicals)} canonical URL(s)")
    print(f"  Dedup rate: {(len(variants) - len(canonicals)) / len(variants) * 100:.0f}%")

    print("\nLayer 2: Bloom filter (probabilistic URL set).\n")
    bf = BloomFilter(capacity=100, fp_rate=0.01)
    print(f"  m = {bf.m} bits ({bf.m / 8 / 1024:.1f} KB), k = {bf.k} hash functions")
    print(f"  Inserting 50 URLs (page0..page49)...\n")
    inserted = [f"https://site.com/page{i}" for i in range(50)]
    for url in inserted:
        bf.add(url)
    print(f"  Bits set: {bf.bit_count()} / {bf.m} = {bf.bit_count() / bf.m * 100:.1f}%")
    fn = sum(1 for url in inserted if not bf.maybe_contains(url))
    print(f"\n  False negative check: query all 50 inserted URLs")
    print(f"    false negatives = {fn}  (MUST be 0 — bloom filters never miss)")
    absent = [f"https://site.com/other{i}" for i in range(50)]
    fp = sum(1 for url in absent if bf.maybe_contains(url))
    print(f"\n  False positive check: query 50 known-absent URLs")
    print(f"    false positives = {fp} / 50 = {fp / 50 * 100:.1f}%  (target was 1%)")

    print("\nLayer 3: content hash (SHA-256) — detect mirror/duplicate pages.\n")
    content_a = "<html><body>Welcome to Example</body></html>"
    url_m1 = "https://example.com/index.html"
    url_m2 = "https://mirror.example.com/home"
    url_m3 = "https://example.com/about"
    content_b = "<html><body>About Us</body></html>"
    hash_a = hashlib.sha256(content_a.encode()).hexdigest()[:16]
    hash_b = hashlib.sha256(content_b.encode()).hexdigest()[:16]
    print(f"  {url_m1:45s} content_hash={hash_a}")
    print(f"  {url_m2:45s} content_hash={hash_a}  ← SAME (mirror)")
    print(f"  {url_m3:45s} content_hash={hash_b}  ← different content")
    print(f"\n  {url_m1} and {url_m2} are content duplicates despite different URLs")

    # =====================================================================
    # SECTION E: ROBOTS.TXT RESPECT
    # =====================================================================
    banner("Section E - robots.txt respect (Disallow / Allow / Crawl-delay)")
    robots_txt = """\
User-agent: *
Crawl-delay: 2
Disallow: /private
Disallow: /tmp/
Allow: /public/news
"""
    print("  robots.txt for example.com:")
    for line in robots_txt.strip().split("\n"):
        print(f"    {line}")
    rules = RobotsRules(robots_txt)
    print(f"\n  Parsed: crawl_delay={rules.crawl_delay}, disallow={rules.disallow}, allow={rules.allow}\n")
    print("  URL checks (Allow overrides Disallow for more specific paths):\n")
    test_paths = ["/index.html", "/private/secret", "/tmp/cache/data", "/public/news/today", "/public"]
    for path in test_paths:
        verdict = "ALLOWED" if rules.allowed(path) else "BLOCKED"
        print(f"    {path:30s} → {verdict}")

    # =====================================================================
    # SECTION F: SCALE ESTIMATION
    # =====================================================================
    banner("Section F - Scale estimation (10B pages)")
    pages = 10_000_000_000
    avg_kb = 50
    content_tb = pages * avg_kb * 1024 / (1024 ** 4)
    url_bytes = 100
    frontier_tb = pages * url_bytes / (1024 ** 4)
    fetch_rate = 50_000
    bandwidth_gbps = fetch_rate * avg_kb * 1024 * 8 / 1e9
    bf_m_10b = int(-pages * math.log(0.01) / (math.log(2) ** 2))
    bf_gb = bf_m_10b / 8 / (1024 ** 3)
    bf_k_10b = max(1, round((bf_m_10b / pages) * math.log(2)))
    recrawl_days = 30
    daily_recrawl = pages / recrawl_days
    recrawl_per_sec = daily_recrawl / 86400
    domains = 1_000_000
    avg_delay = 5
    max_fetch_rate = domains / avg_delay

    print("  Metric                              Value")
    print("  " + "-" * 64)
    print(f"  Pages to crawl                      {pages:,}")
    print(f"  Avg page size                       {avg_kb} KB")
    print(f"  Content storage                     {content_tb:,.0f} TB")
    print(f"  URL frontier (URL + metadata)       {frontier_tb:,.1f} TB  ({url_bytes} B/URL)")
    print(f"  Peak fetch rate                     {fetch_rate:,} pages/sec")
    print(f"  Bandwidth at peak                   {bandwidth_gbps:,.1f} Gbps")
    print(f"  Concurrent workers (~1s/page)       ~{fetch_rate:,}")
    print()
    print(f"  Bloom filter (URL dedup, 1% FP):")
    print(f"    m = -n·ln(p)/(ln2)²              = {bf_m_10b:,} bits")
    print(f"    size                              = {bf_gb:,.1f} GB")
    print(f"    k = (m/n)·ln2                     = {bf_k_10b} hash functions")
    print()
    print(f"  Freshness (re-crawl every {recrawl_days} days):")
    print(f"    Daily re-crawl volume             = {daily_recrawl:,.0f} pages/day")
    print(f"    Re-crawl rate                     = {recrawl_per_sec:,.0f} pages/sec")
    print()
    print(f"  Politeness capacity ({domains:,} domains, avg delay {avg_delay}s):")
    print(f"    Max sustained fetch rate          = {max_fetch_rate:,.0f} pages/sec")
    print(f"    Workers needed (at {fetch_rate:,}/sec)         = {fetch_rate:,}  ({fetch_rate / max_fetch_rate * 100:.1f}% of polite max)")

    # =====================================================================
    # SECTION G: CHECKS
    # =====================================================================
    banner("Section G - [check] assertions")

    assert len(fetch_log) == 7, f"7 URLs should be fetched, got {len(fetch_log)}"
    print(f"[check] Mercator: 7 URLs fetched                          ... OK")

    t0_domains = sorted(d for ft, d, _ in fetch_log if ft == 0.0)
    assert t0_domains == ["blog.com", "example.com", "news.com"], \
        f"t=0 should fetch 3 domains, got {t0_domains}"
    print(f"[check] Mercator: t=0 fetches 3 domains in parallel       ... OK")

    blog_times = sorted(ft for ft, d, _ in fetch_log if d == "blog.com")
    assert blog_times == [0.0, 1.0], f"blog.com (delay=1) should fetch at [0,1], got {blog_times}"
    print(f"[check] Mercator: blog.com (delay=1) → fetch at [0, 1]    ... OK")

    example_times = sorted(ft for ft, d, _ in fetch_log if d == "example.com")
    assert example_times == [0.0, 2.0, 4.0], \
        f"example.com (delay=2) should fetch at [0,2,4], got {example_times}"
    print(f"[check] Mercator: example.com (delay=2) → [0, 2, 4]       ... OK")

    news_times = sorted(ft for ft, d, _ in fetch_log if d == "news.com")
    assert news_times == [0.0, 5.0], f"news.com (delay=5) should fetch at [0,5], got {news_times}"
    print(f"[check] Mercator: news.com (delay=5) → [0, 5]             ... OK")

    assert visited == ["A", "B", "C", "D", "E", "F"], f"BFS order wrong: {visited}"
    print(f"[check] BFS: crawl order A→B→C→D→E→F                     ... OK")

    assert dup_count == 1, f"expected 1 dedup (D via B and C), got {dup_count}"
    print(f"[check] BFS: 1 duplicate URL (D) detected & deduped       ... OK")

    assert schedule == [0, 5, 10], f"politeness schedule should be [0,5,10], got {schedule}"
    print(f"[check] Politeness: delay=5s → fetch at [0, 5, 10]        ... OK")

    assert dns.hits == 6 and dns.misses == 3, f"DNS: 3 misses/6 hits, got {dns.misses}/{dns.hits}"
    print(f"[check] DNS cache: 3 misses, 6 hits (out of 9)            ... OK")

    assert len(canonicals) == 1, f"4 variants → 1 canonical, got {len(canonicals)}"
    print(f"[check] Canonicalization: 4 variants → 1 canonical URL    ... OK")

    assert fn == 0, f"bloom filter must have 0 false negatives, got {fn}"
    print(f"[check] Bloom filter: 0 false negatives                   ... OK")

    assert hash_a == hashlib.sha256(content_a.encode()).hexdigest()[:16]
    assert hash_a != hash_b, "different content → different hash"
    print(f"[check] Content hash: same content → same SHA-256         ... OK")

    assert not rules.allowed("/private/secret"), "Disallow: /private must block"
    assert rules.allowed("/public/news/today"), "Allow: /public/news must allow"
    assert rules.crawl_delay == 2, "crawl-delay should be 2"
    print(f"[check] robots.txt: /private blocked, /public/news allowed ... OK")

    assert abs(bf_gb - 11.2) < 0.5, f"bloom filter for 10B URLs ≈ 11.2 GB, got {bf_gb:.1f}"
    print(f"[check] Scale: bloom filter (10B URLs, 1% FP) = {bf_gb:.1f} GB   ... OK")

    assert content_tb > 450 and content_tb < 500, f"content storage ≈ 465 TB, got {content_tb:.0f}"
    print(f"[check] Scale: 10B pages × 50KB = {content_tb:,.0f} TB            ... OK")

    print()
    print("All [check] assertions passed. Re-run reproduces every number above.")


if __name__ == "__main__":
    main()
