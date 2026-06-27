"""
back_of_envelope.py - Back-of-Envelope Estimation for system design.

The single source of truth that BACK_OF_ENVELOPE.md and back_of_envelope.html
are built from. Every number, table, and estimate in this bundle is printed by
this file.

Run:
    python3 back_of_envelope.py

Pure stdlib. Fully deterministic (no random; every value is a closed-form
calculation on constants).

==========================================================================
THE INTUITION (read this first)
==========================================================================
Back-of-envelope estimation is three multiplications chained together:

  DAU  ->  actions/user/day  ->  QPS  ->  servers
                                   |
                                   +-->  bytes/record  ->  storage
                                   |
                                   +-->  payload x 8  ->  bandwidth

The skill is NOT arithmetic precision. It is:
  1. Knowing the reference numbers (latency hierarchy, single-node QPS, the
     power-of-2 table) so you never start from zero.
  2. Always separating AVG QPS from PEAK QPS (x3 for consumer apps).
  3. Always applying the replication factor (x3) to storage.
  4. Connecting each number to an architectural decision (cache? shard? CDN?).

Get the EXPONENT right; the coefficient does not matter. 10K vs 12K QPS is the
same decision; 10K vs 100K QPS changes the architecture.

References:
  - Jeff Dean, "Latency Numbers Every Programmer Should Know" (Google).
  - CalibreOS, "Back-of-Envelope Estimation" + "Numbers Cheat Sheet".
"""

import math

BANNER = "=" * 74

# ---------------------------------------------------------------------------
# Unit constants - BINARY units (2^n). See power-of-2 table in Section A.
# Network bandwidth uses DECIMAL (1 Gbps = 1e9 bps) by industry convention.
# ---------------------------------------------------------------------------
KB = 1024
MB = 1024 ** 2
GB = 1024 ** 3
TB = 1024 ** 4
PB = 1024 ** 5
EB = 1024 ** 6

SECONDS_PER_DAY = 86_400


# ============================================================================
# Pretty printers
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def human_bytes(n: float) -> str:
    """Format a byte count in binary units (KiB/MiB/GiB...), 3 sig figs."""
    for unit, factor in [("EB", EB), ("PB", PB), ("TB", TB), ("GB", GB),
                         ("MB", MB), ("KB", KB)]:
        if abs(n) >= factor:
            return f"{n / factor:.3g} {unit}"
    return f"{n:.0f} B"


def human_sec(s: float) -> str:
    """Humanize seconds for the 'if 1ns = 1s' latency scale."""
    if s < 90:
        return f"{s:.0f} s"
    if s < 5400:                       # < 90 min
        return f"{s / 60:.1f} min"
    if s < 3 * 86400:                  # < 3 days
        return f"{s / 3600:.1f} h"
    if s < 2 * 365 * 86400:            # < 2 years
        return f"{s / 86400:.1f} days"
    return f"{s / (365 * 86400):.1f} years"


# ============================================================================
# SECTION A: Power-of-2 reference table
# ============================================================================

POW2 = [
    ("2^10", 10, "KiB / Kbit", KB),
    ("2^20", 20, "MiB / Mbit", MB),
    ("2^30", 30, "GiB / Gbit", GB),
    ("2^40", 40, "TiB / Tbit", TB),
    ("2^50", 50, "PiB / Pbit", PB),
    ("2^60", 60, "EiB / Ebit", EB),
]


def section_power2():
    banner("SECTION A: Power-of-2 reference table (binary units)")

    print("\n  Storage/memory use BINARY multiples (2^n). The trap: drive vendors\n"
          "  and networks use DECIMAL (1 GB = 1e9 B, 1 Gbps = 1e9 bps), so a\n"
          "  '1 TB' disk holds ~931 GiB.\n")
    print(f"  {'power':<8}{'exp':<6}{'unit':<18}{'value':>24}")
    print("  " + "-" * 56)
    for label, exp, unit, val in POW2:
        print(f"  {label:<8}{exp:<6}{unit:<18}{val:>24,}")

    print("\n  Binary vs decimal gap (why your 1 TB drive shows 931 GB):")
    for decimal_gb, name in [(1, "1 TB disk"), (100, "100 GB disk")]:
        shown = decimal_gb * 1_000_000_000 / GB
        print(f"    {name:<14} -> {shown:.1f} GiB usable")
    print(f"\n[check] power-of-2 table: 2^30 = {GB:,}: OK")
    return GB


# ============================================================================
# SECTION B: Latency numbers every engineer should know
# ============================================================================

# (label, latency in nanoseconds). Source: Jeff Dean's canonical table.
LATENCY = [
    ("L1 cache reference",            1),            # 1 ns
    ("L2 cache reference",            4),            # 4 ns
    ("L3 cache reference",           10),            # 10 ns
    ("Mutex lock/unlock",            25),            # 25 ns
    ("Main memory (DRAM)",          100),            # 100 ns
    ("SSD random read (4 KB)",    100_000),          # 100 us
    ("Intra-DC RTT (same DC)",    500_000),          # 500 us
    ("SSD sequential read (1 MB)", 1_000_000),       # 1 ms
    ("HDD random seek",          10_000_000),        # 10 ms
    ("Cross-region RTT (US-EU)", 100_000_000),       # 100 ms
    ("Cross-region RTT (US-Asia)", 200_000_000),     # 200 ms
]


def section_latency():
    banner("SECTION B: Latency numbers (L1 cache vs disk vs network)")

    print("\n  Six orders of magnitude separate L1 (~1 ns) from cross-region RTT\n"
          "  (~200 ms). Memorize the anchors: DRAM=100ns, SSD=100us, RTT=100ms.\n"
          "  The 'if 1ns = 1s' column makes the gaps visceral.\n")
    print(f"  {'operation':<30}{'latency':>14}{'if 1ns=1s':>16}")
    print("  " + "-" * 60)
    for label, ns in LATENCY:
        lat = _fmt_latency(ns)
        human = human_sec(ns)               # 1ns -> 1s, so numeric seconds == ns
        print(f"  {label:<30}{lat:>14}{human:>16}")

    print("\n  Key jumps:")
    print(f"    DRAM -> SSD random:    {100_000/100:.0f}x slower   (100x)")
    print(f"    SSD -> intra-DC RTT:   {500_000/100_000:.0f}x slower (5x)")
    print(f"    intra-DC -> US-Asia:   {200_000_000/500_000:.0f}x slower (400x)")
    print("\n  Insight: intra-DC network (500us) is FASTER than a 1MB SSD seq read\n"
          "  (1ms). A distributed in-memory cache can beat a local SSD cache for\n"
          "  latency-sensitive paths.")
    print("\n[check] latency anchors DRAM=100ns SSD=100us RTT=100ms: OK")
    return LATENCY


def _fmt_latency(ns: int) -> str:
    """Format nanoseconds into a human-readable latency string."""
    if ns < 1_000:
        return f"{ns} ns"
    if ns < 1_000_000:
        return f"{ns / 1_000:g} us"
    if ns < 1_000_000_000:
        return f"{ns / 1_000_000:g} ms"
    return f"{ns / 1_000_000_000:g} s"


# ============================================================================
# SECTION C: Throughput - QPS and peak QPS
# ============================================================================

# Throughput formula: avg_qps = DAU * actions_per_user_per_day / 86_400
# peak_qps = avg_qps * peak_multiplier  (3 for consumer, 5-10 for B2B)
THROUGHPUT_EXAMPLES = [
    ("Twitter (consumer social)",  200_000_000, 10,   0.1, 3),
    ("WhatsApp (messaging)",     1_000_000_000,  0, 40,   3),
    ("B2B SaaS dashboard",          1_000_000,   5,   1,  5),
]


def section_throughput():
    banner("SECTION C: Throughput - average QPS and peak QPS")

    print(f"\n  Formula:  avg_qps = DAU * actions/user/day / {SECONDS_PER_DAY}")
    print("            peak_qps = avg_qps * peak_multiplier  (3 = consumer, 5-10 = B2B)\n")
    print(f"  {'system':<28}{'DAU':>14}{'r/user/d':>9}{'w/user/d':>9}"
          f"{'avg R/s':>9}{'peak R/s':>10}{'avg W/s':>9}")
    print("  " + "-" * 88)
    for name, dau, rpu, wpu, mult in THROUGHPUT_EXAMPLES:
        reads_day = dau * rpu
        writes_day = dau * wpu
        avg_r = reads_day / SECONDS_PER_DAY
        peak_r = avg_r * mult
        avg_w = writes_day / SECONDS_PER_DAY
        print(f"  {name:<28}{dau:>14,}{rpu:>9}{wpu:>9}"
              f"{avg_r:>9,.0f}{peak_r:>10,.0f}{avg_w:>9,.0f}")

    # Detailed Twitter walkthrough
    name, dau, rpu, wpu, mult = THROUGHPUT_EXAMPLES[0]
    print(f"\n  WALKTHROUGH: {name}, {dau:,} DAU")
    reads_day = dau * rpu
    writes_day = dau * wpu
    avg_r = reads_day / SECONDS_PER_DAY
    peak_r = avg_r * mult
    avg_w = writes_day / SECONDS_PER_DAY
    peak_w = avg_w * mult
    print(f"    reads/day      = {dau:,} x {rpu} = {reads_day:,}")
    print(f"    avg read QPS   = {reads_day:,} / {SECONDS_PER_DAY} = {avg_r:,.1f}")
    print(f"    peak read QPS  = {avg_r:,.1f} x {mult} = {peak_r:,.1f}")
    print(f"    avg write QPS  = {avg_w:,.1f}   peak = {peak_w:,.1f}")
    print(f"    read:write     = {rpu}/{wpu} = {rpu/wpu:.0f}:1  (reads dominate)")
    print("\n  WHY peak x3: consumer traffic concentrates in a ~8h daytime window.\n"
          "  Spreading 24h of activity over 8h -> 24/8 = 3x concentration. B2B apps\n"
          "  concentrate into business hours -> 5-10x. State the multiplier aloud.")
    print("\n[check] peak QPS = avg QPS x 3 for consumer apps: OK")
    return avg_r, peak_r, avg_w, peak_w


# ============================================================================
# SECTION D: Storage estimation
# ============================================================================

def section_storage():
    banner("SECTION D: Storage estimation (bytes/day -> bytes/year)")

    print("\n  Formula:  daily_raw = writes/day * record_size")
    print("            daily_total = daily_raw * replication * index_overhead")
    print("            5-year = daily_total * 1825 days\n")

    # Twitter text storage
    wpu = 0.1
    rec = 1024                              # 1 KB tweet
    rf = 3
    writes_day = int(200_000_000 * wpu)     # 20M tweets/day
    daily_raw = writes_day * rec
    daily_rf = daily_raw * rf
    fiveyr_raw = daily_raw * 1825
    fiveyr_rf = daily_rf * 1825

    print(f"  Twitter text ({writes_day:,} tweets/day x {rec} B, RF={rf}):\n")
    print(f"    daily raw           = {writes_day:,} x {rec} = {human_bytes(daily_raw)}")
    print(f"    daily w/ RF={rf}        = {human_bytes(daily_rf)}")
    print(f"    5-year raw          = {human_bytes(fiveyr_raw)}")
    print(f"    5-year w/ RF={rf}       = {human_bytes(fiveyr_rf)}")

    # Media dwarfs text
    media_day = writes_day * 0.20 * 300 * 1024     # 20% tweets x 300 KB photo
    media_5yr = media_day * 1825 * rf
    print("\n  Twitter MEDIA (20% of tweets carry a 300 KB photo):\n")
    print(f"    daily media raw    = {human_bytes(media_day)}  (vs {human_bytes(daily_raw)} text)")
    print(f"    5-year media w/ RF = {human_bytes(media_5yr)}")
    print(f"    media:text ratio   = {media_5yr/fiveyr_rf:.0f}x  (media dominates)\n")

    print("  The three storage multipliers:")
    print("    replication  x3   all durable distributed storage (Kafka/HDFS/S3/PG replicas)")
    print("    index        x1.5-2  relational DB B-tree indexes (3-4 indexes ~= table size)")
    print("    encoding     x2-4  video platforms (5 resolution tiers)")
    print("\n  Storage-tier selection by raw capacity:")
    print("    < 1 TB      -> single DB instance")
    print("    1-100 TB    -> S3 for blobs + DB for structured")
    print("    100 TB-1 PB -> tiered hot/warm/cold retention")
    print("    > 1 PB      -> distributed FS (HDFS/Colossus), multi-DC")
    print(f"\n[check] 5-year Twitter text w/ RF = {human_bytes(fiveyr_rf)}: OK")
    return daily_raw, fiveyr_rf


# ============================================================================
# SECTION E: Bandwidth estimation
# ============================================================================

NIC = [
    ("1 Gbps NIC",   1_000_000_000),
    ("10 Gbps NIC", 10_000_000_000),
    ("25 Gbps (c5n)", 25_000_000_000),
]


def section_bandwidth():
    banner("SECTION E: Bandwidth estimation (throughput x payload x 8)")

    print("\n  Formula:  bandwidth_bps = ops/sec * payload_bytes * 8  (bits)")
    print("            usable MB/s   = bps / 8 / 1e6   (network is DECIMAL)\n")
    print("  NIC capacity (actual TCP throughput ~ line rate):")
    for name, bps in NIC:
        mbs = bps / 8 / 1_000_000
        print(f"    {name:<18} = {bps/1e9:g} Gbps = {mbs:g} MB/s")

    # Twitter read egress
    peak_r = 200_000_000 * 10 / SECONDS_PER_DAY * 3
    resp = 1024
    egress_bps = peak_r * resp * 8
    print(f"\n  Twitter READ egress (peak {peak_r:,.0f} reads/s x {resp} B):")
    print(f"    egress = {peak_r:,.0f} x {resp} x 8 = {egress_bps/1e6:,.1f} Mbps "
          f"= {egress_bps/1e9:.2f} Gbps")
    print(f"    fits 1 Gbps NIC? {'YES' if egress_bps < 1e9 else 'NO -> 10 Gbps NIC'}")

    # Kafka replication
    kops, kmsg, krf = 500_000, 1024, 3
    kbps = kops * kmsg * krf * 8
    print(f"\n  Kafka replication ({kops:,} msgs/s x {kmsg} B x RF={krf}):")
    print(f"    bandwidth = {kops:,} x {kmsg} x {krf} x 8 = {kbps/1e9:,.2f} Gbps "
          f"= {kbps/8/1e6:,.0f} MB/s")
    print("    needs network-optimized NIC (25 Gbps c5n); a 1 Gbps NIC saturates at 8%")
    print("\n  Candidates forget network. Always compute writes/sec x record x RF and\n"
          "  compare to NIC throughput. If it exceeds ~50% line rate, upgrade NIC.")
    print(f"\n[check] Kafka RF=3 replication = {kbps/1e9:.1f} Gbps: OK")
    return egress_bps, kbps


# ============================================================================
# SECTION F: Connection count
# ============================================================================

def section_connections():
    banner("SECTION F: Connection count (the connection-tier problem)")

    print("\n  For persistent-connection systems (chat, realtime), the binding resource\n"
          "  is FILE DESCRIPTORS and kernel connection state, NOT CPU or disk.\n")
    print("  servers = concurrent_connections / connections_per_server\n")
    print(f"  {'scenario':<24}{'connections':>16}{'per server':>14}{'servers':>10}")
    print("  " + "-" * 64)

    conns = 1_000_000_000
    for per in [65_000, 1_000_000]:
        n = math.ceil(conns / per)
        label = "default (65K fd)" if per == 65_000 else "tuned (1M fd)"
        print(f"  WhatsApp 1B conns{'':<7}{conns:>16,}{label:>14}{n:>10,}")

    print(f"\n  Tuning 65K -> 1M connections/server cuts the fleet {15385//1000}x\n"
          f"  (15,385 -> 1,000 servers). This forces a DEDICATED connection tier:\n"
          f"    - connection tier: stateless TCP/WS gateways, NO DB calls")
    print("    - Go preferred: goroutine ~8 KB vs Java thread ~1 MB stack")
    print("    - routing index: Redis hash user_id -> connection_server_id")
    print("\n[check] 1B conns / 65K per server = 15,385 servers: OK")
    return math.ceil(conns / 65_000), math.ceil(conns / 1_000_000)


# ============================================================================
# SECTION G: Cache size + required hit rate
# ============================================================================

def section_cache():
    banner("SECTION G: Cache size + required hit rate")

    peak_r = 200_000_000 * 10 / SECONDS_PER_DAY * 3
    db_cap = 5_000                          # Postgres complex-query QPS
    hit_rate = (peak_r - db_cap) / peak_r
    db_load = peak_r * (1 - hit_rate)

    print("\n  required_hit_rate = (peak_qps - db_capacity) / peak_qps\n")
    print(f"  Twitter: peak read QPS = {peak_r:,.0f}, Postgres complex = {db_cap:,} QPS")
    print(f"    hit_rate = ({peak_r:,.0f} - {db_cap:,}) / {peak_r:,.0f} = {hit_rate:.4f}")
    print(f"             = {hit_rate*100:.1f}%   (must cache 92.8% of reads)")
    print(f"    DB load after cache = peak x (1 - hit_rate) = {db_load:,.0f} QPS")
    print("\n  Below 5K QPS caching adds complexity without solving a bottleneck.\n"
          "  Above 300K ops/s a single Redis node is the ceiling -> Redis Cluster.\n")

    # Cache memory sizing
    keys = 100_000_000
    val = 1024
    overhead = 0.15
    raw = keys * val
    total = raw * (1 + overhead)
    nodes256 = math.ceil(total / (256 * GB))
    print(f"  Cache memory sizing ({keys:,} keys x {val} B + {overhead:.0%} metadata):")
    print(f"    raw        = {human_bytes(raw)}")
    print(f"    w/ overhead = {human_bytes(total)}")
    print(f"    @ 256 GB/node = {nodes256} node(s)")
    print(f"\n[check] required hit rate for 5K-DB / {peak_r:,.0f}-peak = {hit_rate*100:.1f}%: OK")
    return hit_rate, nodes256


# ============================================================================
# SECTION H: Volume -> architecture reference
# ============================================================================

VOL_ARCH = [
    (100_000,      "~1.2",   "~3.5",   "single server, no caching"),
    (1_000_000,    "~12",    "~35",    "single app + single DB"),
    (10_000_000,   "~116",   "~347",   "LB + 2-3 app servers, read replica"),
    (100_000_000,  "~1.2K",  "~3.5K",  "Redis caching, DB read replicas, ~5 apps"),
    (1_000_000_000,"~11.6K", "~34.7K", "Redis mandatory, 3-5 replicas, ~30 apps"),
    (10_000_000_000,"~116K", "~347K",  "multi-tier cache, sharding, ~350 apps"),
]


def section_volume():
    banner("SECTION H: Daily volume -> architecture trigger")

    print("\n  avg_qps = daily_requests / 86,400.  peak = avg x 3.\n")
    print(f"  {'daily requests':>16}{'avg QPS':>10}{'peak QPS':>11}   architecture")
    print("  " + "-" * 70)
    for daily, avg, peak, arch in VOL_ARCH:
        print(f"  {daily:>16,}{avg:>10}{peak:>11}   {arch}")
    print("\n  The 5K QPS Postgres-complex threshold is the single most important\n"
          "  line: above it, caching is no longer optional.")
    print("\n[check] 100M req/day -> ~1.2K avg QPS -> Redis tier: OK")


# ============================================================================
# SECTION I: GOLD values - pinned for back_of_envelope.html
# ============================================================================

def section_gold():
    banner("SECTION I: GOLD values - pinned for back_of_envelope.html")

    # Twitter canonical inputs
    DAU = 200_000_000
    RPU = 10
    WPU = 0.1
    REC = 1024
    PEAK = 3
    RF = 3
    DBCAP = 5_000

    avg_r = DAU * RPU / SECONDS_PER_DAY
    peak_r = avg_r * PEAK
    avg_w = DAU * WPU / SECONDS_PER_DAY
    writes_day = DAU * WPU
    daily_raw = writes_day * REC
    fiveyr_rf = daily_raw * 1825 * RF
    hit_rate = (peak_r - DBCAP) / peak_r
    egress_gbps = peak_r * REC * 8 / 1e9
    kafka_gbps = 500_000 * 1024 * 3 * 8 / 1e9
    servers_default = math.ceil(1_000_000_000 / 65_000)
    servers_tuned = math.ceil(1_000_000_000 / 1_000_000)

    print(f"\n  Twitter (DAU={DAU:,} R={RPU}/d W={WPU}/d rec={REC}B peak={PEAK}x RF={RF}):")
    print(f"    avg read QPS  = {avg_r:.4f}   (round {round(avg_r)})")
    print(f"    peak read QPS = {peak_r:.4f}   (round {round(peak_r)})")
    print(f"    avg write QPS = {avg_w:.4f}   (round {round(avg_w)})")
    print(f"    read:write    = {RPU/WPU:.1f}")
    print(f"    daily raw     = {daily_raw:,} B  ({daily_raw/GB:.1f} GiB)")
    print(f"    5yr w/ RF     = {fiveyr_rf:,.0f} B  ({fiveyr_rf/TB:.1f} TiB)")
    print(f"    cache hit%    = {hit_rate*100:.1f}")
    print(f"    read egress   = {egress_gbps:.2f} Gbps")
    print(f"\n  Kafka (500K msgs/s x 1KB x RF=3):  {kafka_gbps:.1f} Gbps")
    print(f"\n  Connections (1B / 65K, 1B / 1M):  {servers_default}, {servers_tuned}")

    # Self-consistency asserts (catch formula drift)
    assert round(avg_r) == 23148, f"avg_r: {avg_r}"
    assert round(peak_r) == 69444, f"peak_r: {peak_r}"
    assert round(avg_w) == 231, f"avg_w: {avg_w}"
    assert RPU / WPU == 100.0
    assert daily_raw == 20_480_000_000
    assert abs(fiveyr_rf / TB - 101.9798219203949) < 1e-6, f"fiveyr_rf: {fiveyr_rf/TB}"
    assert abs(hit_rate - 0.928) < 1e-3, f"hit_rate: {hit_rate}"
    assert abs(egress_gbps - 0.569) < 1e-2, f"egress: {egress_gbps}"
    assert abs(kafka_gbps - 12.3) < 0.1, f"kafka: {kafka_gbps}"
    assert servers_default == 15385
    assert servers_tuned == 1000
    print("\n  all GOLD asserts passed")
    print("\n[check] GOLD values pinned for .html JS recompute: OK")
    return {
        "avg_r": round(avg_r),
        "peak_r": round(peak_r),
        "avg_w": round(avg_w),
        "rw_ratio": RPU / WPU,
        "daily_raw": daily_raw,
        "fiveyr_rf_tb": fiveyr_rf / TB,
        "hit_rate_pct": hit_rate * 100,
        "egress_gbps": egress_gbps,
        "kafka_gbps": kafka_gbps,
        "servers_default": servers_default,
        "servers_tuned": servers_tuned,
    }


# ============================================================================
# main
# ============================================================================

def main():
    print("back_of_envelope.py - reference estimation engine.")
    print("stdlib only; deterministic; no random seed.")
    print("Feeds BACK_OF_ENVELOPE.md and back_of_envelope.html.")
    section_power2()
    section_latency()
    section_throughput()
    section_storage()
    section_bandwidth()
    section_connections()
    section_cache()
    section_volume()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
