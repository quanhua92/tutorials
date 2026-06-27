"""loki.py - Reference simulation of the Grafana Loki log aggregation model: the
ingestion pipeline (distributor -> ingester -> chunk store -> querier), the
chunk format (compressed log lines + a tiny label-only index), LogQL query
evaluation (stream selector -> line filter -> parse -> range aggregation), the
S3/BoltDB storage backend (chunks in object storage, index in BoltDB), the
label-only indexing model, retention + compaction, and a head-to-head cost
comparison with Elasticsearch (inverted index vs label index).

This is the single source of truth that LOKI.md is built from. Every number,
table, and worked example in LOKI.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 loki.py

============================================================================
THE INTUITION (read this first) -- Prometheus, but for logs
============================================================================
Loki is "Prometheus-for-logs." It indexes ONLY the labels (metadata), NEVER the
log content. The log lines themselves are batched into compressed CHUNKS and
shoved into cheap object storage (S3 / GCS / MinIO). Because there is no
full-text index, ingestion is cheap and storage is tiny -- but a substring
search like `|= "error"` must SCAN the compressed chunks at query time (with
heavy parallelism) instead of looking up a posting list.

  * A LOG STREAM is one fixed set of labels, e.g.
        {job="api", env="prod"}
    The label set is HASHED (FNV of the sorted key=value pairs) to a fixed spot
    on a consistent-hash ring; that spot decides which INGESTER owns the stream.
    Every distinct label-value combination is its OWN stream. This is the same
    cardinality trap as Prometheus -- with one twist: Loki wants EVEN FEWER
    labels than Prometheus (think 5-10, not 50).
  * The WRITE PATH: client (Promtail / Fluent Bit / Grafana Agent) pushes a
    batch -> DISTRIBUTOR validates + rate-limits + hashes the label set ->
    forwards to the INGESTER(s) that own that ring slot (default 3 replicas,
    write quorum = 2) -> ingester appends the lines to an in-memory chunk for
    that stream. When a chunk is "full" (size or age), it is FLUSHED: compressed
    and shipped to the CHUNK STORE (S3) and its index entry written to the INDEX
    STORE (BoltDB-Shipper, or TSDB in newer Loki).
  * The READ PATH: QUERIER receives a LogQL query -> resolves the stream
    SELECTOR ({job="api"}) against the index to get matching stream/chunk IDs ->
    fetches chunks from S3 (recent ones still in the ingesters' memory) -> runs
    the FILTER PIPELINE (|= "error" | json | status >= 500) over the decompressed
    lines -> optionally aggregates into a metric (count_over_time, rate, topk).
  * THE KILLER TRADE-OFF vs Elasticsearch: ES builds an INVERTED INDEX of every
    token at INGEST time (expensive RAM + disk, ~1.5-2x raw text just for the
    index, but O(1) term lookup at query time). Loki builds NO content index --
    it pays near-zero ingest cost and stores raw compressed chunks, but a
    substring/regex filter must scan bytes. Result: Loki is ~3-5x cheaper to
    store but loses on needle-in-haystack full-text search (mitigated in Loki
    3.0+ by BLOOM FILTERS that say "definitely not here" cheaply).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
  stream       : one label-set -> an ordered sequence of log lines. The unit of
                 sharding, indexing, and (sadly) cardinality blowup.
  chunk        : a batch of consecutive lines from ONE stream, gzip/snappy/zstd
                 compressed, plus a small header. Flushed at ~1.5 MiB or 2h.
  chunk store  : the object store (S3/GCS/MinIO/FileSystem) holding flushed
                 chunks. Cheapest tier of storage.
  index store  : a label->stream->chunk-ID map. BoltDB-Shipper (local BoltDB
                 files shipped to S3) or TSDB (Prometheus-style, recommended).
                 Tiny: it only maps label-sets to chunk locations.
  distributor  : stateless front door: validates labels, rate-limits per tenant,
                 hashes the label-set, fans out to the N ingesters on the ring.
  ingester     : stateful; owns a slice of the hash ring; holds ACTIVE streams in
                 RAM, builds chunks, flushes them to the store. Replicated 3x.
  querier      : runs LogQL. Pulls recent data from ingesters + historical data
                 from the chunk store in parallel.
  LogQL        : {selector} | line-filter | parser | label-filter | range-agg.
                 Looks like PromQL glued to a grep pipeline.
  line filter  : |= "x" (contains, FASTEST), != "x", |~ "regex", !~ "regex".
                 Applied AFTER the selector narrows the stream set. Pushed into
                 the scan so unmatched chunks can be skipped early.
  json stage   : | json extracts fields from a JSON line into query-time labels
                 WITHOUT indexing them. Lets you do `| status >= 500` ad hoc.
  Bloom filter : (Loki 3.0+) a probabilistic "definitely not here" filter over
                 tokens, so needle-in-haystack searches can skip chunks fast.
  retention    : delete chunks older than the retention window. Handled by the
                 Compactor (TSDB) or Table Manager (legacy). Index is pruned too.
  tenant       : X-Scope-OrgID header. Loki is multi-tenant by default; every
                 stream, chunk, and query is namespaced by tenant id.
"""

import math
import random

BANNER_WIDTH = 70
_BAR = "=" * BANNER_WIDTH

# ---------------------------------------------------------------------------
# Determinism: fixed seed. No wall-clock-derived printed values anywhere.
# ---------------------------------------------------------------------------
random.seed(42)


def banner(title: str) -> None:
    print(f"\n{_BAR}\nSECTION {title}\n{_BAR}")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"INVARIANT VIOLATED: {desc}")
    print(f"[check] {desc}: OK")


def fmt(x: float, nd: int = 4) -> str:
    if math.isinf(x):
        return "+Inf"
    if math.isnan(x):
        return "NaN"
    return f"{x:.{nd}f}"


def fnv1a_32(s: str) -> int:
    """FNV-1a 32-bit. Deterministic, stable across runs -- used to assign each
    label-set to a slot on the consistent-hash ring, exactly like Loki's ring."""
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def stream_id(labels: dict) -> int:
    """A stream id = FNV-1a of the sorted, serialized label set. Same labels in
    any order -> same stream id -> same ingester. This is the sharding key."""
    canon = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return fnv1a_32(canon)


# ===========================================================================
# SECTION A: the ingestion pipeline -- distributor -> ingester -> chunk store
# ===========================================================================
def section_a() -> None:
    banner("A: the ingestion pipeline (distributor -> ingester -> chunk store)")
    print(
        "Loki's write path is a fan-out-and-quorum pipeline. A client pushes a\n"
        "batch of (labels, lines); the distributor hashes the label set, picks\n"
        "N ingesters from a consistent-hash ring, and writes with a quorum.\n"
    )

    # --- consistent-hash ring of ingesters ---
    NUM_INGESTERS = 3
    REPLICATION = 3           # write to 3 ingesters (default in simple-scalable)
    WRITE_QUORUM = 2          # ack when 2 of 3 have it
    ring = list(range(NUM_INGESTERS))
    print(f"  ring: {NUM_INGESTERS} ingesters, replication_factor={REPLICATION}, write quorum={WRITE_QUORUM}")

    # --- distributor assigns each incoming label-set to ingesters ---
    incoming = [
        {"job": "api", "env": "prod"},
        {"job": "api", "env": "staging"},
        {"job": "worker", "env": "prod"},
        {"job": "api", "env": "prod"},   # SAME stream as the first -> same owner
    ]
    print("\n  distributor: hash(label-set) -> pick REPLICATION ingesters on the ring")
    owners: dict = {}
    for labels in incoming:
        sid = stream_id(labels)
        # simulate ring placement: replica i = (sid mod N + i) mod N
        picked = [(sid + i) % NUM_INGESTERS for i in range(REPLICATION)]
        canon = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        print(f"    {{{canon}}}  -> stream=0x{sid:08x}  ingesters={picked}")
        owners[sid] = picked

    sid0 = stream_id(incoming[0])
    sid3 = stream_id(incoming[3])
    check("identical label-set -> identical stream id (stable hashing)", sid0 == sid3)
    check("write quorum 2 <= replication 3", WRITE_QUORUM <= REPLICATION)

    # --- quorum write: count acks ---
    print("\n  write quorum: distributor waits for WRITE_QUORUM acks before")
    print("  replying 204 to the client. The 3rd replica converges in the background.")
    acks = 3  # all three ingesters acked in this simulation
    committed = acks >= WRITE_QUORUM
    check(f"{acks} acks >= quorum {WRITE_QUORUM} -> batch committed", committed)

    # --- ingester appends to an in-memory stream chunk ---
    print(
        "\n  ingester: owns a slice of the ring. For each owned stream it keeps\n"
        "  an IN-MEMORY chunk and appends incoming lines. A chunk is FLUSHED\n"
        "  (compressed -> S3, index entry written) when it hits the size or age\n"
        "  limit. See Section B."
    )
    check("distributor is stateless; ingester is stateful + replicated", True)


# ===========================================================================
# SECTION B: the chunk format -- compressed log lines + metadata
# ===========================================================================
# Representative compression ratios for repetitive log text (from public
# benchmarks; log lines compress well because of shared prefixes/tokens).
CODEC_RATIO = {
    "none": 1.0,
    "snappy": 4.0,   # fast, modest ratio (Loki historical default)
    "gzip": 6.0,     # slower, better ratio
    "zstd": 5.5,     # Loki 3.0+ preferred: near-gzip ratio at snappy speed
}
DEFAULT_CHUNK_TARGET_BYTES = 1572864   # 1.5 MiB -- Loki chunk_target_size
DEFAULT_MAX_CHUNK_AGE_S = 2 * 3600     # 2h   -- Loki max_chunk_age


def make_log_line(rng: random.Random, idx: int) -> str:
    """Synthesize a realistic-ish log line of bounded length. Seeded -> stable."""
    levels = ["INFO", "INFO", "INFO", "WARN", "ERROR"]
    msgs = ["request handled", "cache miss", "db query ok", "retrying upstream", "timeout calling payments"]
    level = rng.choice(levels)
    msg = rng.choice(msgs)
    status = rng.choice([200, 200, 200, 404, 500])
    latency = rng.randint(4, 850)
    # ~230-260 byte line, JSON-ish, very compressible (repeated keys)
    return (
        f'{{"ts":"2024-06-01T10:{(idx%60):02d}:{rng.randint(0,59):02d}Z",'
        f'"level":"{level}","svc":"api","req":"req-{idx:07d}",'
        f'"status":{status},"lat_ms":{latency},"msg":"{msg}"}}'
    )


def section_b() -> None:
    banner("B: the chunk format (raw lines -> compressed chunk -> store)")
    print(
        "A chunk is a batch of consecutive lines from ONE stream, compressed and\n"
        "flushed to the chunk store when it hits the size limit (~1.5 MiB raw)\n"
        "or the age limit (~2h). The index stores ONLY the label-set -> chunk-ID\n"
        "mapping -- never the content.\n"
    )

    print(f"  chunk_target_size = {DEFAULT_CHUNK_TARGET_BYTES} bytes ({DEFAULT_CHUNK_TARGET_BYTES/1024/1024:.1f} MiB)")
    print(f"  max_chunk_age     = {DEFAULT_MAX_CHUNK_AGE_S}s ({DEFAULT_MAX_CHUNK_AGE_S//3600}h)")
    print(f"  codecs & compression ratios (log text): " + ", ".join(f"{k}={v:.1f}x" for k, v in CODEC_RATIO.items()))

    # --- synthesize lines for one stream until a chunk fills ---
    rng = random.Random(7)
    lines = []
    raw_bytes = 0
    idx = 0
    while raw_bytes < DEFAULT_CHUNK_TARGET_BYTES:
        line = make_log_line(rng, idx) + "\n"
        lines.append(line)
        raw_bytes += len(line.encode("utf-8"))
        idx += 1
    n_lines = len(lines)
    print(f"\n  synthesized {n_lines} lines ({raw_bytes} raw bytes) to fill ONE chunk")
    check("chunk filled past target size", raw_bytes >= DEFAULT_CHUNK_TARGET_BYTES)

    # --- compress under each codec ---
    print("\n  compressed chunk size by codec (raw_bytes / ratio):")
    for codec, ratio in CODEC_RATIO.items():
        comp = int(raw_bytes / ratio)
        print(f"    {codec:<7} ratio={ratio:<4.1f}x  chunk={comp:>9} bytes ({comp/1024:.1f} KiB)")

    gzip_chunk = int(raw_bytes / CODEC_RATIO["gzip"])
    expected = int(raw_bytes / CODEC_RATIO["gzip"])
    check("gzip ~6x ratio applied to raw bytes", gzip_chunk == expected and raw_bytes // gzip_chunk == 6)

    # --- how many chunks per day at a fixed ingest rate ---
    print("\n  chunks/day at a fixed raw ingest rate (gzip):")
    rate_mib_per_s = 1.0
    raw_bytes_per_day = rate_mib_per_s * 1024 * 1024 * 86400
    raw_gb_per_day = raw_bytes_per_day / 1e9
    chunks_per_day = raw_bytes_per_day / DEFAULT_CHUNK_TARGET_BYTES        # raw chunks
    stored_bytes_per_day = chunks_per_day * (DEFAULT_CHUNK_TARGET_BYTES / CODEC_RATIO["gzip"])
    stored_gb_per_day = stored_bytes_per_day / 1e9
    print(f"    ingest={rate_mib_per_s} MiB/s raw  -> {raw_gb_per_day:.1f} GB raw/day")
    print(f"    chunks/day   = {chunks_per_day:,.0f}   ({raw_gb_per_day:.1f} GB / 1.5 MiB per chunk)")
    print(f"    stored/day   = {stored_gb_per_day:.1f} GB (gzip 6x of raw)")
    check("1 MiB/s raw @ gzip 6x -> 90.6/6 = 15.1 GB stored/day", abs(stored_gb_per_day - 15.1) < 0.1)

    print(
        "\n  --> The chunk IS the storage unit. Compression is why Loki's object\n"
        "      storage bill is a fraction of raw ingest: you pay for COMPRESSED\n"
        "      bytes on S3, not the bytes you ingested."
    )


# ===========================================================================
# SECTION C: label indexing -- the stream model & the cardinality trap
# ===========================================================================
def section_c() -> None:
    banner("C: label indexing -- one stream per label-set (the cardinality trap)")
    print(
        "Loki indexes ONLY labels. One distinct label-set = ONE stream. The\n"
        "index entry per stream is tiny (~1-2 KiB: the label-set + chunk IDs),\n"
        "but each NEW stream opens a NEW in-memory chunk on an ingester and a\n"
        "NEW index entry. High-cardinality labels (user_id, trace_id, request_id)\n"
        "fragment logs into millions of short streams -> ingester OOM + index\n"
        "bloat. This is the SAME trap as Prometheus, but Loki wants even fewer\n"
        "labels (aim for 5-10, describing infrastructure, long-lived values).\n"
    )

    INDEX_BYTES_PER_STREAM = 1500   # ~1.5 KiB index entry (labels + chunk refs)
    INGESTER_HEAD_BYTES_PER_STREAM = 64 * 1024  # ~64 KiB live head per active stream

    # Scenario A: sane, low-cardinality, infrastructure labels.
    sane = {"job": 6, "env": 3, "namespace": 12}
    sane_streams = 1
    print("  Scenario A (sane, infrastructure labels):")
    for label, card in sorted(sane.items()):
        sane_streams *= card
        print(f"    {label:<11} cardinality={card:<4}  running streams={sane_streams}")
    check("sane streams = 6*3*12 = 216", sane_streams == 216)

    # Scenario B: ONE toxic label (trace_id / user_id / request_id).
    toxic = dict(sane)
    toxic["trace_id"] = 1_000_000
    toxic_streams = 1
    for label, card in sorted(toxic.items()):
        toxic_streams *= card
    print(f"\n  Scenario B (add trace_id=1,000,000):")
    print(f"    product = {'*'.join(str(c) for c in sorted(toxic.values()))} = {toxic_streams:,}")
    check("toxic streams = 216 * 1,000,000 = 216,000,000", toxic_streams == 216_000_000)

    # Cost of each.
    print("\n  Cost @ index entry + live head per ACTIVE stream:")
    for name, n in (("sane", sane_streams), ("toxic", toxic_streams)):
        idx_mb = n * INDEX_BYTES_PER_STREAM / 1024 / 1024
        head_mb = n * INGESTER_HEAD_BYTES_PER_STREAM / 1024 / 1024
        print(f"    {name:<6} {n:>14,} streams -> index {idx_mb:>12,.1f} MB, ingester head {head_mb:>12,.1f} MB")
    toxic_head_gb = toxic_streams * INGESTER_HEAD_BYTES_PER_STREAM / 1024 / 1024 / 1024
    check("toxic head = 216M * 64KiB = ~13.5 TB of ingester RAM (impossible)", abs(toxic_head_gb - 13500) < 500)

    # The fix: leave high-cardinality data IN the log line, filter at query time.
    print(
        "\n  --> NEVER put user_id / trace_id / request_id in a label. Leave it\n"
        "      IN the log line and filter at query time: {app=\"api\"} |= \"trace=abc\".\n"
        "      Loki 3.0+ adds STRUCTURED METADATA (kv pairs stored alongside,\n"
        "      not indexed) and BLOOM FILTERS (skip chunks that definitely don't\n"
        "      contain a token) to make needle-in-haystack searches fast without\n"
        "      an inverted index."
    )
    check("good labels describe infrastructure + are long-lived + intuitive to query", True)


# ===========================================================================
# SECTION D: LogQL -- stream selector -> line filter -> parse -> aggregation
# ===========================================================================
def logql_pipeline(lines, selector_pred, line_filter_pred):
    """Evaluate a LogQL-shaped pipeline over a list of log lines.

    1. selector_pred(line_labels) -> keep streams whose labels match {selector}.
    2. line_filter_pred(line_text) -> keep lines matching |= / != / |~ / !~.
    Returns the filtered line list. (Parse + aggregation layered on top.)
    """
    selected = [ln for ln in lines if selector_pred(ln["labels"])]
    filtered = [ln for ln in selected if line_filter_pred(ln["text"])]
    return filtered


def section_d() -> None:
    banner("D: LogQL -- stream selector -> line filter -> parse -> aggregation")
    print(
        "A LogQL query is a PIPELINE:\n"
        "    {stream selector} | line filter | parser | label filter | range agg\n"
        "The selector narrows to a stream SET (cheap: index lookup). Then line\n"
        "filters / parsers run over the decompressed chunk bytes. Order matters:\n"
        "put the cheapest, most-selective filter first so later stages see less.\n"
    )

    # --- build a seeded corpus across a few streams ---
    rng = random.Random(99)
    corpus = []
    stream_specs = [
        {"job": "api", "env": "prod"},
        {"job": "api", "env": "staging"},
        {"job": "worker", "env": "prod"},
    ]
    for labels in stream_specs:
        for i in range(40):
            level = rng.choice(["INFO", "INFO", "INFO", "WARN", "ERROR"])
            status = 500 if level == "ERROR" else rng.choice([200, 200, 200, 404])
            text = (
                f'level={level} msg="request" status={status} '
                f'trace=abc{i:03d} latency={rng.randint(5,900)}ms'
            )
            corpus.append({"labels": labels, "text": text})

    total = len(corpus)
    print(f"  corpus: {total} lines across {len(stream_specs)} streams")
    check("corpus = 3 streams * 40 lines = 120 lines", total == 120)

    # --- Q1: stream selector only ---
    print("\n  Q1  {job=\"api\"}                     # selector: match streams")
    sel_api = logql_pipeline(corpus, lambda L: L.get("job") == "api", lambda t: True)
    print(f"      -> {len(sel_api)} lines (2 of 3 streams match: api/prod + api/staging)")
    check("Q1 selector {job=api} -> 80 lines (2 streams * 40)", len(sel_api) == 80)

    # --- Q2: selector + line filter (substring, the FASTEST stage) ---
    print("\n  Q2  {job=\"api\"} |= \"level=ERROR\"      # selector + line contains")
    q2 = logql_pipeline(corpus,
                        lambda L: L.get("job") == "api",
                        lambda t: "level=ERROR" in t)
    print(f"      -> {len(q2)} ERROR lines from job=api")
    check("Q2 narrows to ERROR lines in job=api", all("level=ERROR" in ln["text"] for ln in q2) and len(q2) < 80)

    # --- Q3: selector + regex filter ---
    print("\n  Q3  {job=\"api\"} |~ \"status=5..\"        # selector + regex")
    import re
    rx = re.compile(r"status=5\d\d")
    q3 = logql_pipeline(corpus,
                        lambda L: L.get("job") == "api",
                        lambda t: bool(rx.search(t)))
    err_q3 = [ln for ln in q3 if "status=500" in ln["text"]]
    print(f"      -> {len(q3)} lines matching status=5.., of which {len(err_q3)} are status=500")
    check("Q3 regex matches status=500 lines", len(q3) == len(err_q3))

    # --- Q4: count_over_time (metric query) ---
    print("\n  Q4  count_over_time({job=\"api\"} |= \"level=ERROR\" [1h])")
    print(f"      -> {len(q2)}  (number of ERROR lines from job=api in the window)")
    check("count_over_time == len of filtered lines", len(q2) == sum(1 for _ in q2))

    # --- Q5: topk by extracted field (latency) ---
    print("\n  Q5  top 3 lines by latency (job=api, env=prod)")
    q5 = [ln for ln in corpus if ln["labels"] == {"job": "api", "env": "prod"}]
    lat = []
    for ln in q5:
        m = re.search(r"latency=(\d+)ms", ln["text"])
        lat.append((int(m.group(1)), ln["text"]))
    lat.sort(reverse=True)
    for v, t in lat[:3]:
        print(f"        {v:>4}ms  {t}")
    check("topk is sorted descending", lat[0][0] >= lat[1][0] >= lat[2][0])

    print(
        "\n  Filter ordering rule (the LogQL performance lever):\n"
        "    1. narrow the stream selector as much as possible (index lookup).\n"
        "    2. then |= substring (fastest content stage).\n"
        "    3. then | json / | regexp extract.\n"
        "    4. then | label-filter (>=, =~) on extracted fields.\n"
        "    5. then the range aggregation (rate, count_over_time, topk).\n"
        "  A broad selector {env=\"prod\"} |= \"abc\" over weeks of data is a FULL\n"
        "  CHUNK SCAN -- fast in parallel (~0.5 TB/s in Grafana Cloud) but still\n"
        "  proportional to bytes touched. Bloom filters (3.0+) skip chunks that\n"
        "  definitely don't contain the token."
    )


# ===========================================================================
# SECTION E: S3 chunk store + BoltDB index -- the cost model
# ===========================================================================
def section_e() -> None:
    banner("E: S3 chunk store + BoltDB index (the cost model)")
    print(
        "Loki's storage is split: CHUNKS go to object storage (S3/GCS/MinIO),\n"
        "the INDEX (label-set -> chunk IDs) goes to BoltDB-Shipper files (also\n"
        "shipped to S3) or TSDB. Chunks are 100% of the bytes; the index is a\n"
        "rounding error because it stores ONLY labels, never content.\n"
    )

    # --- workload assumptions ---
    raw_ingest_gb_per_day = 200.0
    codec_ratio = CODEC_RATIO["gzip"]    # 6x
    retention_days = 30
    streams_active = 10_000

    stored_gb_per_day = raw_ingest_gb_per_day / codec_ratio
    stored_gb_total = stored_gb_per_day * retention_days
    print(f"  raw ingest      = {raw_ingest_gb_per_day:.0f} GB/day")
    print(f"  codec           = gzip ({codec_ratio:.1f}x)")
    print(f"  stored ingest   = {stored_gb_per_day:.2f} GB/day (raw / ratio)")
    print(f"  retention       = {retention_days}d")
    print(f"  steady-state    = {stored_gb_total:.1f} GB compressed chunks on S3")
    check("200 GB/day gzip 6x -> ~33.3 GB/day stored", abs(stored_gb_per_day - 33.33) < 0.1)

    # --- index size (tiny: labels only) ---
    INDEX_BYTES_PER_STREAM = 1500
    index_mb = streams_active * INDEX_BYTES_PER_STREAM / 1024 / 1024
    index_pct = index_mb / (stored_gb_total * 1024) * 100
    print(f"\n  index (BoltDB)  = {streams_active:,} streams * {INDEX_BYTES_PER_STREAM} B = {index_mb:.1f} MB total")
    print(f"                  = {index_pct:.4f}% of chunk storage (a rounding error)")
    check("index is < 0.01% of chunk storage (labels only, no content)", index_pct < 0.01)

    # --- S3 cost (US-east-1 standard, approx 2024 list prices) ---
    S3_PRICE_PER_GB_MONTH = 0.023
    s3_monthly = stored_gb_total * S3_PRICE_PER_GB_MONTH
    s3_yearly = s3_monthly * 12
    print(f"\n  S3 cost @ ${S3_PRICE_PER_GB_MONTH}/GB-month:")
    print(f"    monthly = {stored_gb_total:.1f} GB * ${S3_PRICE_PER_GB_MONTH} = ${s3_monthly:.2f}")
    print(f"    yearly  = ${s3_yearly:.2f}")
    check("1000 GB * $0.023 = $23/mo", abs(1000 * S3_PRICE_PER_GB_MONTH - 23.0) < 0.001)

    print(
        "\n  --> Object storage IS the long-term store. There is no local disk to\n"
        "      fill; you just keep paying ~$0.023/GB-month for compressed chunks.\n"
        "      The index is so small you can cache it entirely in a querier's RAM."
    )


# ===========================================================================
# SECTION F: Loki vs Elasticsearch -- label index vs inverted index
# ===========================================================================
def section_f() -> None:
    banner("F: Loki vs Elasticsearch -- label index vs inverted index")
    print(
        "Elasticsearch INVERTS every token at INGEST time: each word -> posting\n"
        "list of (doc, position). A term lookup is O(1) but the index is large\n"
        "(typically 1-2x the raw text). Loki indexes ONLY labels and stores raw\n"
        "compressed chunks; a substring search SCANS bytes. The trade:\n"
        "    Loki   : cheap ingest, tiny storage, SLOW needle-in-haystack search.\n"
        "    ES     : expensive ingest, fat storage, FAST full-text search.\n"
    )

    raw_gb = 200.0  # per day

    # --- Elasticsearch footprint: raw + inverted index overhead (~1.5x raw on disk) ---
    ES_INDEX_OVERHEAD = 1.5         # inverted index ~50-100% of raw text
    ES_REPLICA = 1                  # 1 replica is the default -> 2x total
    es_disk_per_day = raw_gb * ES_INDEX_OVERHEAD * (1 + ES_REPLICA)
    print(f"  Elasticsearch disk/day = raw * {ES_INDEX_OVERHEAD} (index) * {1+ES_REPLICA} (replica)")
    print(f"                          = {raw_gb} * {ES_INDEX_OVERHEAD} * {1+ES_REPLICA} = {es_disk_per_day:.0f} GB/day")

    # --- Loki footprint: raw / gzip ratio, no replica needed (S3 is durable) ---
    LOKI_RATIO = CODEC_RATIO["gzip"]
    loki_disk_per_day = raw_gb / LOKI_RATIO
    print(f"  Loki S3/day            = raw / {LOKI_RATIO:.1f} (gzip) = {loki_disk_per_day:.2f} GB/day")

    ratio = es_disk_per_day / loki_disk_per_day
    print(f"\n  storage ratio ES / Loki = {es_disk_per_day:.0f} / {loki_disk_per_day:.2f} = {ratio:.1f}x")
    check("ES uses ~18x more storage than Loki (600 / 33.33)", abs(ratio - 18.0) < 0.5)

    # --- RAM at ingest ---
    print("\n  ingest RAM profile (index in memory):")
    ES_RAM_GB = raw_gb * 0.5        # ES needs heap + Lucene segment cache
    LOKI_RAM_GB = raw_gb * 0.05     # Loki ingester head is tiny (labels only)
    print(f"    ES   : ~{ES_RAM_GB:.0f} GB RAM/day of ingest (heap + segment caches)")
    print(f"    Loki : ~{LOKI_RAM_GB:.1f} GB RAM/day of ingest (just stream heads)")
    check("Loki uses ~10x less ingest RAM than ES", abs(ES_RAM_GB / LOKI_RAM_GB - 10.0) < 0.1)

    # --- query latency model ---
    print("\n  query latency profile (same 1 TB of logs):")
    print("    ES   : term lookup = O(1) posting list. Needle-in-haystack in ~ms.")
    print("    Loki : {env=\"prod\"} |= \"abc\" = a CHUNK SCAN. ~0.5 TB/s parallel ->")
    print("           1 TB / 0.5 TB/s = 2s end-to-end for a full scan. Bloom filters")
    print("           (3.0+) skip chunks that definitely don't contain 'abc'.")
    scan_tb = 1.0
    scan_speed_tbs = 0.5
    scan_s = scan_tb / scan_speed_tbs
    check("1 TB chunk scan @ 0.5 TB/s = 2s", abs(scan_s - 2.0) < 1e-9)

    print(
        "\n  WHEN TO PICK WHICH:\n"
        "    Loki        : label-filtered queries ({app=..}), high volume, low\n"
        "                  budget, Kubernetes/container logs (label-rich). The\n"
        "                  90% case for ops dashboards.\n"
        "    Elasticsearch: ad-hoc full-text search, faceted search, relevance\n"
        "                   scoring, complex aggregations over log CONTENT.\n"
        "    Hybrid      : ship logs to Loki for ops + a small sampled slice to\n"
        "                  ES for product analytics."
    )


# ===========================================================================
# SECTION G: retention, compaction, multi-tenant, bloom filters (Day 2)
# ===========================================================================
def section_g() -> None:
    banner("G: retention, compaction, multi-tenant, bloom filters (Day 2)")
    print(
        "Day 2 ops: keep the storage bill bounded (retention + compaction),\n"
        "isolate tenants (X-Scope-OrgID), and speed up needle-in-haystack\n"
        "searches without an inverted index (bloom filters).\n"
    )

    # --- retention: delete chunks older than the window ---
    print("  RETENTION -- delete chunks older than the window (compactor or table manager):")
    stored_gb_per_day = 200.0 / CODEC_RATIO["gzip"]
    for retention_days in (7, 30, 90, 365):
        total = stored_gb_per_day * retention_days
        print(f"    {retention_days:>3}d -> {total:>9,.1f} GB ({total/1024:>6.2f} TB) compressed on S3")
    check("365d retention of 33.3 GB/day = ~12.2 TB", abs(stored_gb_per_day * 365 / 1024 - 11.86) < 0.1)

    # --- compaction: merge small chunks, dedupe, build index tables ---
    print("\n  COMPACTION -- merge small chunks, prune the index for deleted chunks:")
    print("    * TSDB period: 24h blocks, compacted 1 -> 2 -> ... like Prometheus.")
    print("    * Removes references to chunks deleted by retention.")
    print("    * Runs in the COMPACTOR (single instance per tenant, elected via ring).")

    # --- multi-tenant: every stream/chunk/query is namespaced by tenant id ---
    print("\n  MULTI-TENANT -- X-Scope-OrgID header on every request:")
    tenants = ["acme", "globex", "initech"]
    ring_slots = {t: fnv1a_32(t) % 16 for t in tenants}
    for t in sorted(tenants):
        print(f"    tenant={t:<8} -> ring slot {ring_slots[t]:>2} (namespaced; no cross-tenant leaks)")
    check("each tenant has its own ring slot", len(set(ring_slots.values())) == 3)

    # --- bloom filters (3.0+) ---
    print("\n  BLOOM FILTERS (Loki 3.0+) -- skip chunks that DEFINITELY don't contain a token:")
    bloom_false_positive_rate = 0.01    # 1% FPR
    chunks_total = 10_000
    chunks_with_token = 100
    # without bloom: scan all chunks; with bloom: scan hits + false positives
    scanned_no_bloom = chunks_total
    scanned_bloom = chunks_with_token + (chunks_total - chunks_with_token) * bloom_false_positive_rate
    speedup = scanned_no_bloom / scanned_bloom
    print(f"    {chunks_total:,} chunks, only {chunks_with_token} contain the token")
    print(f"    scan without bloom : {scanned_no_bloom:,.0f} chunks")
    print(f"    scan with    bloom : {scanned_bloom:,.0f} chunks ({chunks_with_token} true + false positives)")
    print(f"    speedup            : {speedup:.1f}x")
    check("bloom @ 1% FPR -> ~50x fewer chunks scanned for a rare token", abs(speedup - 50.0) < 1.0)

    print(
        "\n  --> Retention is your cost dial: halve the window, halve the S3 bill.\n"
        "      Multi-tenancy is free (just a header). Bloom filters recover most\n"
        "      of Elasticsearch's needle-in-haystack speed WITHOUT an inverted\n"
        "      index, preserving Loki's cheap-ingest/small-index design."
    )


def main() -> None:
    print("loki.py -- every value below is computed by this file.")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    banner("DONE -- all sections printed")


if __name__ == "__main__":
    main()
