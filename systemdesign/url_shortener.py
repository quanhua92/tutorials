#!/usr/bin/env python3
"""
url_shortener.py - URL Shortener system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds URL_SHORTENER.md
and is recomputed identically in url_shortener.html (gold-checked).

Sections:
  1. Base62 encoding / decoding (the core of short-key generation)
  2. Key generation strategies (auto-increment, Snowflake, MD5-hash)
  3. Collision detection (birthday paradox for hash-based keys)
  4. Scale estimation (storage, QPS, bandwidth)
  5. Redirect analytics pipeline (async click event fan-out, hot keys)
  6. GOLD values pinned for url_shortener.html
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
    # decimal units (1000), so 18.25e12 B == 18.25 TB (matches GOLD check)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000.0:
            return "%.2f %s" % (n, unit)
        n /= 1000.0
    return "%.2f EB" % n


def fmt_int(n):
    return "{:,}".format(n)


# ---------------------------------------------------------------------------
# SECTION 1 - Base62 encoding
# ---------------------------------------------------------------------------

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)  # 62
INDEX_OF = {c: i for i, c in enumerate(ALPHABET)}


def base62_encode(n):
    if n == 0:
        return ALPHABET[0]
    chars = []
    while n > 0:
        chars.append(ALPHABET[n % BASE])
        n //= BASE
    return "".join(reversed(chars))


def base62_decode(s):
    n = 0
    for ch in s:
        n = n * BASE + INDEX_OF[ch]
    return n


def section_base62():
    banner("SECTION 1: Base62 encoding / decoding")
    print("Alphabet (%d chars): %s" % (BASE, ALPHABET))
    print("  0-9 = values 0-9,  a-z = 10-35,  A-Z = 36-61")
    print()

    print("Short-key capacity by length:")
    for k in (5, 6, 7, 8):
        cap = BASE ** k
        print("  %d chars -> %20s keys  (%.2f B)" % (k, fmt_int(cap), cap / 1e9))
    print()

    examples = [0, 1, 61, 62, 63, 12345, 100000000, 68999]
    print("Round-trip worked examples (id <-> base62):")
    for n in examples:
        enc = base62_encode(n)
        dec = base62_decode(enc)
        ok = "OK" if dec == n else "FAIL"
        print("  %15d -> %-10s -> %15d   [%s]" % (n, enc, dec, ok))
    print()

    yearly_new = 36_500_000_000  # 100M/day * 365
    key6 = BASE ** 6
    key7 = BASE ** 7
    print("Headline capacity vs 36.5B new URLs/year:")
    print("  6-char keys %s hold %.1f years of growth" % (fmt_int(key6), key6 / yearly_new))
    print("  7-char keys %s hold %.1f years of growth" % (fmt_int(key7), key7 / yearly_new))
    print()
    print("[check] base62_encode(12345) == '3d7'? " +
          ("OK" if base62_encode(12345) == "3d7" else "FAIL"))
    print("[check] base62_decode('3d7') == 12345? " +
          ("OK" if base62_decode("3d7") == 12345 else "FAIL"))
    print("[check] round-trip holds for all examples? " +
          ("OK" if all(base62_decode(base62_encode(n)) == n for n in examples) else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Key generation strategies
# ---------------------------------------------------------------------------

def section_keygen():
    banner("SECTION 2: Key generation strategies")
    print("Three ways to mint a unique short key per long URL.\n")

    # A. auto-increment
    print("A. Auto-increment counter + base62 encode")
    counter = 1_000_000
    samples_a = []
    for _ in range(5):
        counter += 1
        samples_a.append(base62_encode(counter))
    print("   ids 1,000,001..1,000,005 -> keys %s" % samples_a)
    print("   + ordered, zero collisions, shortest key (6 chars)")
    print("   - single point of coordination (DB sequence), guessable URL count")
    print()

    # B. Snowflake
    print("B. Snowflake distributed ID (Twitter 64-bit) + base62")
    EPOCH = 1_577_836_800_000  # 2020-01-01 UTC ms
    machine_id = 23
    ts_base = 1_700_000_000_000
    samples_b = []
    for seq in range(5):
        sid = ((ts_base - EPOCH) << 22) | (machine_id << 12) | seq
        samples_b.append(base62_encode(sid))
    print("   layout: 1 sign | 41 ts-ms | 10 machine | 12 seq")
    print("   machine_id=%d, 5 consecutive seq -> keys (note length):" % machine_id)
    for seq, key in enumerate(samples_b):
        print("     seq=%d -> %-11s (%d chars)" % (seq, key, len(key)))
    print("   + no SPOF, k-sorted, ~4M ids/sec/machine (12 bits/ms)")
    print("   - keys longer (~9 chars), clock-drift / NTP handling needed")
    print()

    # C. hash-based
    print("C. MD5(long_url) truncated to 6 base62 chars + collision check")
    urls = [
        "https://www.example.com/very/long/path?utm=xyz",
        "https://news.ycombinator.com/item?id=99999",
        "https://github.com/quanhua92/tutorials",
    ]
    samples_c = []
    for url in urls:
        h = hashlib.md5(url.encode()).hexdigest()
        prefix = int(h[:12], 16)  # 48 bits
        key = base62_encode(prefix).rjust(6, "0")[-6:]
        samples_c.append(key)
    for url, key in zip(urls, samples_c):
        print("   %-48s -> %s" % (url[:48], key))
    print("   + no coordination, deterministic, stateless")
    print("   - collisions INEVITABLE (see Section 3), must check + rehash")
    print()

    all_keys = samples_a + samples_b + samples_c
    print("[check] every strategy yields a non-empty base62 key? " +
          ("OK" if all(len(k) >= 1 for k in all_keys) else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Collision detection
# ---------------------------------------------------------------------------

def section_collisions():
    banner("SECTION 3: Collision detection (hash-based keys)")
    keyspace = BASE ** 6  # 56.8B for a 6-char key
    print("6-char base62 keyspace M = %s" % fmt_int(keyspace))
    print()

    print("Birthday-paradox collision probability P(n keys):")
    for n in (1_000, 10_000, 100_000, 286_000, 1_000_000):
        p = 1 - math.exp(-(n * n) / (2 * keyspace))
        print("  n = %10d   P(collision) = %.5f" % (n, p))
    threshold = math.sqrt(math.pi * keyspace / 2)
    print("  expected FIRST collision at n ~ %.0f URLs" % threshold)
    print()

    print("Actual simulation: truncate MD5(url) to 6 base62 chars, 500k URLs:")
    random.seed(123)
    seen = {}
    collisions = 0
    first_n = None
    N = 500_000
    for i in range(N):
        fake = "https://site.example/path/%d/q=%d" % (i, i * 7919)
        h = hashlib.md5(fake.encode()).hexdigest()
        prefix = int(h[:12], 16)
        key = base62_encode(prefix).rjust(6, "0")[-6:]
        if key in seen:
            collisions += 1
            if first_n is None:
                first_n = i
                print("  FIRST collision at URL #%d: key '%s'" % (i, key))
        else:
            seen[key] = i
    print("  generated %s keys -> %s collisions (%.3f%%)" %
          (fmt_int(N), fmt_int(collisions), collisions / N * 100))
    print()
    print("  => 6-char hash keys COLLIDE at scale. Two fixes:")
    print("     (1) bump to 7 chars (keyspace x62), OR")
    print("     (2) check DB; on collision append a salt and rehash.")
    print()
    print("[check] collisions actually occur for 6-char hash keys? " +
          ("OK" if collisions > 0 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Scale estimation
# ---------------------------------------------------------------------------

def section_scale():
    banner("SECTION 4: Scale estimation")
    new_per_day = 100_000_000
    reads_per_day = 1_000_000_000
    bytes_per_record = 500
    seconds_per_day = 86_400

    print("Assumptions:")
    print("  new URLs / day        = %s" % fmt_int(new_per_day))
    print("  redirects / day       = %s" % fmt_int(reads_per_day))
    print("  read : write ratio    = %d : 1" % (reads_per_day // new_per_day))
    print("  bytes / URL record    = %d  (long_url + metadata)" % bytes_per_record)
    print()

    wq = new_per_day / seconds_per_day
    rq = reads_per_day / seconds_per_day
    print("Average QPS:")
    print("  writes (shorten)  = %8.1f /s" % wq)
    print("  reads  (redirect) = %8.1f /s" % rq)
    print()
    print("Peak QPS (10x avg, viral spike):")
    print("  writes peak = %10.0f /s" % (wq * 10))
    print("  reads  peak = %10.0f /s" % (rq * 10))
    print()

    new_per_year = new_per_day * 365
    stor_year = new_per_year * bytes_per_record
    print("Annual growth:")
    print("  new URLs / year   = %s  (%.1f B)" % (fmt_int(new_per_year), new_per_year / 1e9))
    print("  storage / year    = %s" % fmt_bytes(stor_year))
    print("  storage / 5 years = %s" % fmt_bytes(stor_year * 5))
    print()

    wbw = wq * bytes_per_record
    rbw = rq * bytes_per_record
    print("Bandwidth (avg, payload only):")
    print("  write bandwidth = %s/s" % fmt_bytes(wbw))
    print("  read  bandwidth = %s/s" % fmt_bytes(rbw))
    print()

    cache_hit_rate = 0.92
    db_read_qps = rq * (1 - cache_hit_rate)
    print("Cache effect (Redis, 92% hit rate on redirects):")
    print("  cache serves  = %.1f /s" % (rq * cache_hit_rate))
    print("  DB still hit   = %.1f /s  (the misses)" % db_read_qps)
    print()
    print("[check] read:write == 10:1? " +
          ("OK" if reads_per_day // new_per_day == 10 else "FAIL"))
    print("[check] storage/year == 18.25 TB? " +
          ("OK" if abs(stor_year / 1e12 - 18.25) < 0.001 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Redirect analytics pipeline
# ---------------------------------------------------------------------------

def section_analytics():
    banner("SECTION 5: Redirect analytics pipeline")
    print("Flow on every GET /{key}:")
    print("  client -> redirect service -> 302 + long URL (synchronous, <50ms)")
    print("                 |")
    print("                 +-> fire async click event -> Kafka (non-blocking)")
    print("                        Kafka -> stream processor -> analytics DB")
    print()
    print("Why async?  A redirect must stay <50ms p99. Geo-lookup, dedup and")
    print("aggregation are slow and loss-tolerable; never block the redirect path.")
    print()

    random.seed(7)
    n_keys = 1000
    weights = [1.0 / (k + 1) for k in range(n_keys)]  # Zipf / power-law
    keys = ["key%04d" % k for k in range(n_keys)]
    countries = ["US", "VN", "DE", "BR", "IN", "JP"]

    n_clicks = 100_000
    sampled = random.choices(keys, weights=weights, k=n_clicks)
    country_samples = random.choices(countries, k=n_clicks)

    counts = {}
    for k in sampled:
        counts[k] = counts.get(k, 0) + 1
    by_country = {}
    for c in country_samples:
        by_country[c] = by_country.get(c, 0) + 1

    sorted_counts = sorted(counts.values(), reverse=True)
    top1 = sum(sorted_counts[:n_keys // 100])
    top10 = sum(sorted_counts[:n_keys // 10])
    print("Simulated %s clicks across %d keys (Zipf / power-law traffic):" %
          (fmt_int(n_clicks), n_keys))
    print("  top  1%% of keys (%d keys) carry %.1f%% of clicks" %
          (n_keys // 100, top1 / n_clicks * 100))
    print("  top 10%% of keys (%d keys) carry %.1f%% of clicks" %
          (n_keys // 10, top10 / n_clicks * 100))
    print("  => cache hot keys aggressively; cold keys may hit DB unpenalised.")
    print()

    print("  Clicks by country (uniform for demo):")
    for c in sorted(by_country, key=lambda x: -by_country[x]):
        pct = by_country[c] / n_clicks * 100
        bar = "#" * int(pct * 2)
        print("    %s: %7s (%4.1f%%) %s" % (c, fmt_int(by_country[c]), pct, bar))
    print()
    print("[check] all clicks attributed to a country? " +
          ("OK" if sum(by_country.values()) == n_clicks else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - GOLD values for url_shortener.html
# ---------------------------------------------------------------------------

def section_gold():
    banner("SECTION 6: GOLD values (pinned for url_shortener.html)")
    wq = round(100_000_000 / 86_400, 1)
    rq = round(1_000_000_000 / 86_400, 1)
    stor_tb = 36_500_000_000 * 500 / 1e12
    gold = [
        ("base62_encode_0", base62_encode(0)),
        ("base62_encode_61", base62_encode(61)),
        ("base62_encode_62", base62_encode(62)),
        ("base62_encode_12345", base62_encode(12345)),
        ("base62_encode_100m", base62_encode(100_000_000)),
        ("base62_decode_3d7", base62_decode("3d7")),
        ("base62_decode_6LAze", base62_decode("6LAze")),
        ("key6_capacity", BASE ** 6),
        ("key7_capacity", BASE ** 7),
        ("write_qps_avg", wq),
        ("read_qps_avg", rq),
        ("storage_per_year_tb", stor_tb),
        ("read_write_ratio", 10),
    ]
    for k, v in gold:
        print("  %-24s = %s" % (k, v))
    print()
    ok = (base62_decode(base62_encode(12345)) == 12345 and
          base62_encode(100_000_000) == "6LAze" and
          abs(stor_tb - 18.25) < 1e-9)
    print("[check] GOLD reproduces from base62 + scale formulas? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# url_shortener.py - URL Shortener system design simulation")
    print("# Pure Python stdlib only. Numbers below feed URL_SHORTENER.md")
    print("# and url_shortener.html (gold-checked).")
    section_base62()
    section_keygen()
    section_collisions()
    section_scale()
    section_analytics()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
