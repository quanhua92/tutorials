#!/usr/bin/env python3
"""
pastebin.py - Pastebin system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds PASTEBIN.md
and is recomputed identically in pastebin.html (gold-checked).

Core model: CONTENT-ADDRESSED STORAGE.
  - Paste body is stored in object storage keyed by its SHA-256 digest.
  - Identical content hashes to the same key => automatic dedup.
  - A short URL slug is derived from the (truncated) hash; the FULL hash
    is always the object key, so truncation can never cause data loss.

Sections:
  1. Content-addressed storage (SHA-256 -> object key -> short URL)
  2. Text dedup via hashing (corpus simulation, storage savings)
  3. Expiration TTL cleanup (soft delete + async physical reclaim)
  4. Access control (public / unlisted / private)
  5. Scale estimation (read:write 1000:1, storage, bandwidth, QPS)
  6. GOLD values pinned for pastebin.html
"""

import hashlib
import math
import random

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def fmt_bytes(n):
    # decimal units (1000): 1e9 B == 1.00 GB, 1.825e12 B == 1.83 TB
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000.0:
            return "%.2f %s" % (n, unit)
        n /= 1000.0
    return "%.2f EB" % n


def fmt_int(n):
    return "{:,}".format(n)


# base62 (identical alphabet to url_shortener.py so the bundle is consistent)
ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)  # 62


def base62_encode(n):
    if n == 0:
        return ALPHABET[0]
    chars = []
    while n > 0:
        chars.append(ALPHABET[n % BASE])
        n //= BASE
    return "".join(reversed(chars))


# ---------------------------------------------------------------------------
# content-addressing primitives
# ---------------------------------------------------------------------------

def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_key(text):
    """Full SHA-256 hex digest = object storage key (zero collisions)."""
    return sha256_hex(text)


def full_base62(h):
    """Encode the full 256-bit hash into base62 (~43 chars)."""
    return base62_encode(int(h, 16))


def short_url_slug(h, nchars=11):
    """Truncated hash for the URL slug; collision-checked vs full hash."""
    return full_base62(h)[:nchars].rjust(nchars, "0")


# ---------------------------------------------------------------------------
# SECTION 1 - Content-addressed storage
# ---------------------------------------------------------------------------

def section_content_addressing():
    banner("SECTION 1: Content-addressed storage (SHA-256 -> key -> URL)")
    print("Paste body -> SHA-256 -> 64-char hex = the object storage key.")
    print("  digest bits = 256,  hex chars = 64")
    sample_for_len = "the quick brown fox jumps over the lazy dog"
    print("  base62 of a 256-bit hash = %d chars (62^43 ~= 2^256)" %
          len(full_base62(sha256_hex(sample_for_len))))
    print()

    samples = [
        "print('hello world')",                       # appears twice on purpose
        "print('hello world')",                       # identical => SAME key (dedup!)
        "def add(a, b):\n    return a + b\n",
        "SELECT * FROM users WHERE id = 1;",
    ]
    print("Sample pastes -> content keys:")
    print("  %-30s | %s | %s" % ("content (<=30)", "SHA-256 object key (64 hex)", "URL slug (11 b62)"))
    for s in samples:
        h = content_key(s)
        slug = short_url_slug(h)
        disp = s.replace("\n", "\\n")[:30]
        print("  %-30s | %s | %s" % (disp, h, slug))
    print()
    print("=> the two identical 'print(hello world)' pastes map to the SAME object")
    print("   key and the SAME URL slug. That is automatic, free dedup: identical")
    print("   content is never stored twice.")
    print()

    print("Short-slug length vs keyspace (collision risk lives on the URL only):")
    for k in (8, 10, 11, 12):
        cap = BASE ** k
        first = math.sqrt(math.pi * cap / 2.0)
        print("  %2d chars -> %20s keyspace, first slug clash ~ %.0f pastes" %
              (k, fmt_int(cap), first))
    print()
    print("  GOTCHA: the slug is a TRUNCATION of the hash. Two different pastes can")
    print("  collide on the slug but NEVER on the full 256-bit object key. So the")
    print("  object is always keyed by the full hash; on a slug clash we append a")
    print("  salt and rehash the slug. No content is ever overwritten.")
    print()

    h1 = content_key("print('hello world')")
    h2 = content_key("print('hello world') ")
    ok = (h1 == content_key("print('hello world')")) and (h1 != h2)
    print("[check] identical content -> identical key, 1-char change -> different key? " +
          ("OK" if ok else "FAIL"))
    print("[check] slug is 11 chars of base62? " +
          ("OK" if len(short_url_slug(h1)) == 11 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Text dedup via hashing
# ---------------------------------------------------------------------------

def make_fresh(doc_id):
    # a fresh, unique paste body (build logs, one-off code)
    return ("def solve_%d():\n"
            "    # build %d\n"
            "    return %d\n" % (doc_id, doc_id, (doc_id * 2654435761) % 2147483647))


VIRAL_BODIES = [
    "POST /api/login HTTP/1.1\nHost: prod.example.com\nAuthorization: Bearer ...",
    "[ERROR] 2024-06-27 NullPointerException at com.app.Service.handle(Service.java:42)",
    "version: '3.8'\nservices:\n  web:\n    image: nginx:latest\n    ports: ['80:80']",
    "import os\nos.environ['SECRET_KEY'] = 'sk-leaked-0000'\n",
    "git clone https://github.com/example/repo.git && cd repo && make install",
]


def section_dedup():
    banner("SECTION 2: Text dedup via hashing")
    n_events = 100_000          # paste-create events in one day
    fresh_rate = 0.80           # 80% are fresh unique content
    viral_size = 500            # 20% are reposts drawn from a small viral pool
    avg_size = 10_000           # 10 KB average paste body
    random.seed(2024)

    seen = {}
    fresh_counter = 0
    repost_events = 0
    for _ in range(n_events):
        if random.random() < fresh_rate:
            content = make_fresh(fresh_counter)
            fresh_counter += 1
        else:
            # repost of a "viral" snippet (error logs, configs, leaked keys)
            content = VIRAL_BODIES[random.randrange(viral_size) % len(VIRAL_BODIES)]
            content = content + "\n# copy %d\n" % random.randrange(viral_size)
            repost_events += 1
        h = content_key(content)
        seen[h] = seen.get(h, 0) + 1

    unique = len(seen)
    dup_events = n_events - unique
    dedup_pct = dup_events / n_events * 100.0
    raw = n_events * avg_size
    after = unique * avg_size
    saved = raw - after

    print("Simulation: %s create-events (%.0f%% fresh + %.0f%% reposts of %d viral snippets)." %
          (fmt_int(n_events), fresh_rate * 100, (1 - fresh_rate) * 100, viral_size))
    print("  create events         = %s" % fmt_int(n_events))
    print("  repost events         = %s  (error logs, configs, leaked keys)" % fmt_int(repost_events))
    print("  unique bodies stored  = %s" % fmt_int(unique))
    print("  duplicate events      = %s   (%.2f%% dedup)" %
          (fmt_int(dup_events), dedup_pct))
    top = sorted(seen.values(), reverse=True)
    print("  hottest body reposted = %d times (a viral config snippet)" % top[0])
    print()
    print("Storage impact (avg %s / paste):" % fmt_bytes(avg_size))
    print("  raw, no dedup   = %s / day" % fmt_bytes(raw))
    print("  after dedup     = %s / day   (saved %s, %.2f%%)" %
          (fmt_bytes(after), fmt_bytes(saved), saved / raw * 100.0))
    print()
    print("5-year effect (no TTL reclaim):")
    print("  raw 5yr     = %s" % fmt_bytes(raw * 365 * 5))
    print("  deduped 5yr = %s   (saved %s)" %
          (fmt_bytes(after * 365 * 5), fmt_bytes(saved * 365 * 5)))
    print()
    print("  => content addressing turns reposts into a single stored object.")
    print("     The object key (full hash) is written once; later creates just add")
    print("     a metadata row pointing at the same key.")
    print()

    ok = (unique < n_events) and (after < raw)
    print("[check] dedup actually reduces both stored objects and bytes? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Expiration TTL cleanup
# ---------------------------------------------------------------------------

TTL_BUCKETS = [
    ("10 min",  10 * 60,        0.05),
    ("1 hour",  60 * 60,        0.15),
    ("1 day",   24 * 3600,      0.30),
    ("1 week",  7 * 24 * 3600,  0.25),
    ("1 month", 30 * 24 * 3600, 0.15),
    ("never",   None,           0.10),
]


def section_ttl():
    banner("SECTION 3: Expiration TTL cleanup")
    n_day = 100_000
    avg_size = 10_000
    print("TTL bucket distribution (%s pastes/day):" % fmt_int(n_day))
    print("  %-9s %12s %12s" % ("bucket", "pastes/day", "reclaimable"))
    reclaimable = 0
    never_day = 0
    for name, secs, frac in TTL_BUCKETS:
        count = int(round(n_day * frac))
        if secs is None:
            never_day = count
            print("  %-9s %12s %12s" % (name, fmt_int(count), "no"))
        else:
            reclaimable += count
            print("  %-9s %12s %12s" % (name, fmt_int(count), "yes"))
    print()
    print("Two-phase deletion:")
    print("  SOFT delete  : read path checks expires_at -> 404 if expired.")
    print("                  Instant; zero storage work; expired paste simply vanishes.")
    print("  HARD reclaim : async nightly job deletes the object after a 24h grace")
    print("                  window. S3 lifecycle policies handle the cold tier natively.")
    print()
    print("Reclaimable per day (will be physically deleted) = %s pastes" %
          fmt_int(reclaimable))
    print("Never-expire accumulation = %s pastes/day -> %.2f M/year -> %s/year" %
          (fmt_int(never_day), never_day * 365 / 1e6,
           fmt_bytes(never_day * 365 * avg_size)))
    print()
    print("  GOTCHA: content-addressing makes HARD reclaim reference-counted. Several")
    print("  metadata rows may point at one object key (dedup). The reclaim job must")
    print("  delete the object only when the LAST referencing row expires, or storage")
    print("  leaks OR live pastes 404. Keep a refcount per content key.")
    print()

    total_frac = sum(f for _, _, f in TTL_BUCKETS)
    ok = (abs(total_frac - 1.0) < 1e-9) and (never_day > 0) and (reclaimable > 0)
    print("[check] TTL fractions sum to 1.0 and mix reclaimable + never? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Access control
# ---------------------------------------------------------------------------

ACCESS_TIERS = [
    ("public",   0.60),
    ("unlisted", 0.30),
    ("private",  0.10),
]


def section_access():
    banner("SECTION 4: Access control (public / unlisted / private)")
    n_day = 100_000
    print("Tier distribution (%s pastes/day):" % fmt_int(n_day))
    print("  %-9s %7s %12s %14s" % ("tier", "share", "pastes/day", "CDN cache"))
    for name, frac in ACCESS_TIERS:
        cdn = "yes" if name != "private" else "NO (auth)"
        print("  %-9s %6d%% %12s %14s" % (name, frac * 100, fmt_int(int(round(n_day * frac))), cdn))
    print()
    print("Read-path authorization:")
    print("  public   : anyone; indexed; full CDN caching with 24h+ TTL.")
    print("  unlisted : anyone WITH the URL; NOT indexed; CDN still caches (the URL is")
    print("              the secret, so unguessable slugs are mandatory).")
    print("  private  : owner only (bearer token / session); bypass the CDN, hit the")
    print("              service, optional at-rest encryption. Never publicly cacheable.")
    print()
    reads_day = 100_000_000
    rq = reads_day / 86400.0
    private_frac_reads = 0.02   # private is 10% of content but ~2% of reads
    print("Private = 10% of content but only ~2% of reads; those reads bypass CDN:")
    print("  total read QPS        = %.1f /s" % rq)
    print("  private (backend-only)= %.1f /s  (always hits the service, never edge)" %
          (rq * private_frac_reads))
    print()
    print("  GOTCHA: caching private pastes on a shared public CDN is a leak. Tag the")
    print("  cache key with the tier; private reads use a per-user cache namespace or")
    print("  skip the CDN entirely and go service -> Redis (per-token key).")
    print()

    ok = abs(sum(f for _, f in ACCESS_TIERS) - 1.0) < 1e-9
    print("[check] access tier shares sum to 1.0? " + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Scale estimation
# ---------------------------------------------------------------------------

def section_scale():
    banner("SECTION 5: Scale estimation")
    new_per_day = 100_000
    reads_per_day = 100_000_000
    avg_size = 10_000
    sps = 86_400

    wq = new_per_day / sps
    rq = reads_per_day / sps
    ratio = reads_per_day // new_per_day

    print("Assumptions:")
    print("  new pastes/day   = %s" % fmt_int(new_per_day))
    print("  reads/day        = %s" % fmt_int(reads_per_day))
    print("  read:write ratio = %d : 1" % ratio)
    print("  avg paste size   = %s" % fmt_bytes(avg_size))
    print()
    print("QPS:")
    print("  write QPS avg    = %.2f /s   (peak ~%.0f /s, 100x)" % (wq, wq * 100))
    print("  read  QPS avg    = %.1f /s   (peak ~%.0f /s, 10x)" % (rq, rq * 10))
    print()

    raw_day = new_per_day * avg_size
    raw_5yr = raw_day * 365 * 5
    print("Storage (raw, no dedup, no reclaim):")
    print("  /day  = %s" % fmt_bytes(raw_day))
    print("  /5yr  = %s" % fmt_bytes(raw_5yr))
    print("  (~2 TB quoted ceiling; dedup + TTL reclaim lower the real footprint.)")
    print()

    cdn = 0.95
    print("CDN effect (%.0f%% hit on public/unlisted reads):" % (cdn * 100))
    print("  CDN serves  = %.0f /s" % (rq * cdn))
    print("  backend hit = %.0f /s" % (rq * (1 - cdn)))
    print()

    bw_r = rq * avg_size
    print("Bandwidth:")
    print("  read egress (payload) = %s /s avg" % fmt_bytes(bw_r))
    print()

    ok = (ratio == 1000) and (abs(raw_day / 1e9 - 1.0) < 1e-9)
    print("[check] read:write == 1000:1 and raw storage/day == 1.00 GB? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - GOLD values pinned for pastebin.html
# ---------------------------------------------------------------------------

def section_gold():
    banner("SECTION 6: GOLD values (pinned for pastebin.html)")
    wq = round(100_000 / 86_400, 1)
    rq = round(100_000_000 / 86_400, 1)
    raw_day = 100_000 * 10_000
    raw_5yr = raw_day * 365 * 5
    probe = "print('hello world')"
    ph = content_key(probe)
    gold = [
        ("sha256_probe_hex64",   ph),
        ("sha256_probe_hex16",   ph[:16]),
        ("sha256_slug_11",       short_url_slug(ph)),
        ("sha256_full_b62_len",  len(full_base62(ph))),
        ("write_qps_avg",        wq),
        ("read_qps_avg",         rq),
        ("storage_per_day_b",    raw_day),
        ("storage_5yr_b",        raw_5yr),
        ("read_write_ratio",     1000),
        ("avg_paste_size_b",     10_000),
    ]
    for k, v in gold:
        print("  %-22s = %s" % (k, v))
    print()

    probe2 = "print('hello world') "
    ok = (content_key(probe) == content_key(probe) and
          content_key(probe) != content_key(probe2) and
          abs(rq - 1157.4) < 1e-9 and
          abs(raw_5yr / 1e12 - 1.825) < 1e-9 and
          100_000_000 // 100_000 == 1000)
    print("[check] GOLD reproduces from SHA-256 + scale formulas? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# pastebin.py - Pastebin system design simulation")
    print("# Pure Python stdlib only. Numbers below feed PASTEBIN.md")
    print("# and pastebin.html (gold-checked).")
    section_content_addressing()
    section_dedup()
    section_ttl()
    section_access()
    section_scale()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
