# Design a URL Shortener

> **Companion code:** [`url_shortener.py`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/url_shortener.py).
> **Live demo:** [`url_shortener.html`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/url_shortener.html) — open in a browser.

---

## 0. TL;DR — the one idea

> **The analogy:** a URL shortener is a **giant hash map** (`short_key → long_url`)
> that is *read a thousand times more than it is written*, fronted by a cache, with a
> side-channel pipeline that records every click without slowing the redirect down.

The whole system reduces to two fast operations — **mint a key** (write, rare) and
**resolve a key** (read, constant). Everything else (key generation strategy, cache,
analytics, 301 vs 302) is a tradeoff hanging off those two ops.

```mermaid
graph LR
    C(["client"]) -->|POST /shorten| GW["API Gateway<br/>(rate limit, auth)"]
    C -->|GET /{key}| GW
    GW -->|write| SS["Shortening Service"]
    GW -->|read| RS["Redirect Service"]
    SS --> ID["ID Generator<br/>(Snowflake / counter)"]
    SS -->|write-through| DB[("Key→URL DB<br/>sharded MySQL / Cassandra")]
    SS -->|populate| RC[("Redis Cache<br/>short_key → long_url")]
    RS -->|1. lookup| RC
    RC -.miss.-> DB
    RS -->|2. 302 + long_url| C
    RS -.3. async click event.-> KF["Kafka"]
    KF --> SP["Stream Processor"]
    SP --> AN[("Analytics DB<br/>time-series")]
    style GW fill:#eaf2f8,stroke:#2980b9
    style RC fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style RS fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style KF fill:#fef9e7,stroke:#f1c40f
```

---

## 1. Requirements

### Functional
- **Shorten** a long URL to a unique, compact alias (6–7 chars).
- **Redirect** a short key back to the original long URL.
- Support optional **custom aliases** (`bit.ly/my-brand`).
- Track **click analytics** (timestamp, referrer, country, device).
- Support **expiration** and **deletion** of short URLs.

### Non-Functional
- **High availability** on the redirect path (links are shared broadly; downtime breaks the internet).
- **Low latency**: redirect `< 50 ms p99`, shortening `< 200 ms`.
- **Read-heavy**: optimise for redirects (≈10:1 read:write).
- **Horizontally scalable** to absorb viral link spikes (10× peak).
- **Durability**: a shortened URL must keep resolving forever (or until explicit expiry).

---

## 2. Scale Estimation

> From `url_shortener.py` **Section 4** (100M new URLs/day, 1B redirects/day, 500 B/record):

| Metric | Value |
|---|---|
| New URLs / day | 100,000,000 |
| Redirects / day | 1,000,000,000 |
| **Read : write ratio** | **10 : 1** |
| Avg write QPS (shorten) | 1,157.4 /s |
| Avg read QPS (redirect) | 11,574.1 /s |
| Peak read QPS (10× viral) | 115,741 /s |
| New URLs / year | 36,500,000,000 (36.5 B) |
| **Storage / year** | **18.25 TB** |
| Storage / 5 years | 91.25 TB |
| Write bandwidth (payload) | 578.70 KB/s |
| Read bandwidth (payload) | 5.79 MB/s |

> From `url_shortener.py` **Section 4** — cache effect (Redis @ 92% hit rate):

| Cache metric | Value |
|---|---|
| Redirects served from cache | 10,648.1 /s |
| Redirects still hitting DB (misses) | 925.9 /s |

> From `url_shortener.py` **Section 1** — key-length capacity:

| Key length | Keyspace | Years of growth (vs 36.5 B/yr) |
|---|---|---|
| 6 chars | 56,800,235,584 (56.8 B) | **1.6 years** |
| 7 chars | 3,521,614,606,208 (3.52 T) | **96.5 years** |

---

## 3. Architecture

```mermaid
graph TD
    LB["Load Balancer / CDN"] --> AGW["API Gateway<br/>rate-limit + auth"]
    AGW -->|POST /shorten| SH["Shortening Service"]
    AGW -->|GET /{key}| RD["Redirect Service"]
    SH --> IG["ID Generator<br/>Snowflake 64-bit"]
    SH --> WDB[("Key→URL DB<br/>sharded by short_key")]
    SH -->|write-through| CA[("Redis cluster")]
    RD -->|1 read| CA
    CA -.cache miss.-> RDB[("DB read replica")]
    RD -->|2 emit click| KP["Kafka queue"]
    KP --> ST["Stream processor<br/>(aggregate + dedup)"]
    ST --> TS[("Analytics DB<br/>time-series, sharded by day)"]
    RD -->|3 302 + Location| LB
    style CA fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style RD fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style KP fill:#fef9e7,stroke:#f1c40f
```

### Key Components

| Component | Technology | Why |
|---|---|---|
| API Gateway | Kong / Envoy | Rate-limit the `POST /shorten` abuse path; auth; TLS termination. |
| Shortening Service | stateless Go/Java pods | Mint key, write DB + cache, return. Horizontally scalable. |
| Redirect Service | stateless, latency-critical | Cache-first lookup; must stay `< 50 ms p99`. The hot path. |
| ID Generator | Snowflake (Twitter) | Distributed, k-sorted, ~4M ids/sec/machine, no SPOF. |
| Key→URL DB | sharded MySQL / Cassandra | Shard by `short_key` hash for uniform load; 18.25 TB/yr. |
| Redis Cache | Redis cluster | Cuts DB read load by 92% (10,648/s → 926/s at DB). |
| Analytics Pipeline | Kafka → Flink → ClickHouse | Async; never blocks the redirect. Time-series by day. |

---

## 4. Key Design Decisions

### 4.1 Key generation strategy

> From `url_shortener.py` **Section 2** (sample keys) and **Section 3** (collision math):

| Decision | Option A | Option B | Option C | Winner | Why |
|---|---|---|---|---|---|
| **Key generation** | Auto-increment + base62 | Snowflake 64-bit + base62 | MD5 truncate + check | **Snowflake** | No SPOF, k-sorted, ~4M ids/sec/machine; counter is a bottleneck, hash needs collision retries. |

Sample keys from the simulation:

| Strategy | Sample (6–10 chars) | Notes |
|---|---|---|
| Auto-increment (ids 1,000,001+) | `4c93, 4c94, 4c95 …` | Shortest (≤6 chars), ordered, guessable. |
| Snowflake (machine 23) | `BQKudzksBG … BK` (10 chars) | Longer key, but fully distributed. |
| MD5 truncated | `BGgbti, ozffQX, vPIm0L` | Stateless; collides at ~298k URLs (see below). |

### 4.2 Collision risk for hash-based keys (Section 3)

> 6-char base62 keyspace M = **56,800,235,584**. Birthday-paradox first collision at **n ≈ 298,700 URLs**; the simulation's actual first collision was at **URL #364,496** (key `22wqCV`).

| n URLs | P(at least 1 collision) |
|---|---|
| 1,000 | 0.00001 |
| 10,000 | 0.00088 |
| 100,000 | 0.08426 |
| 286,000 | 0.51326 |
| 1,000,000 | 0.99985 |

**Fix:** bump to 7 chars (keyspace ×62 → 3.52 T), or check DB and rehash with a salt on collision.

### 4.3 Cache strategy for redirects

| Decision | Option A | Option B | Option C | Winner | Why |
|---|---|---|---|---|---|
| **Cache** | No cache, read DB | Write-through on shorten | Lazy load on first read | **Write-through** | Shorten is rare & tolerated (200ms budget); pre-populates cache so even a new URL's first redirect is a hit. |

### 4.4 Redirect: 301 vs 302

| Decision | Option A | Option B | Winner | Why |
|---|---|---|---|---|
| **Redirect code** | 301 Permanent | 302 Temporary | **302** | Every click hits our server → full analytics (referrer, geo, device). 301 is browser-cached and silently kills click tracking. Worth the extra server load (mitigated by Redis). |

### 4.5 Analytics is async (Section 5)

> The redirect path fires a **non-blocking click event to Kafka**; geo-lookup, dedup and aggregation happen downstream. Simulated Zipf traffic: **top 1% of keys carry 39.3% of clicks**, top 10% carry 69.4% — cache the hot keys aggressively.

---

## 5. Data Model

### `urls` (metadata — sharded by `short_key`)

| Column | Type | Notes |
|---|---|---|
| `short_key` | VARCHAR(10) | **PK**, base62-encoded Snowflake ID (7 chars). |
| `long_url` | TEXT | Original URL (avg ~500 B incl. metadata). |
| `user_id` | BIGINT | Creator (nullable for anonymous). |
| `created_at` | TIMESTAMP | Creation time. |
| `expires_at` | TIMESTAMP | Nullable TTL; null = permanent. |
| `custom_alias` | BOOL | True if user-supplied. |
| `click_count` | BIGINT | Async-updated counter (eventual). |

### `clicks` (analytics — time-series, sharded by day)

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT | PK. |
| `short_key` | VARCHAR(10) | FK → urls. |
| `ts` | TIMESTAMP | Click time (partition key). |
| `country` | CHAR(2) | Geo (IP lookup). |
| `device` | ENUM | mobile / desktop / tablet. |
| `referrer` | VARCHAR(64) | direct / twitter / email … |

---

## 6. API Endpoints

| Method | Path | Body / Response | Notes |
|---|---|---|---|
| `POST` | `/api/shorten` | req `{"long_url": "…"}` → `{"short_url": "x.ly/abc123", "key":"abc123"}` | rate-limited (abuse path). |
| `GET` | `/{short_key}` | → `302 Location: <long_url>` | cache-first; emits click event. |
| `GET` | `/api/shorten/{key}/stats` | → `{"clicks": 1234, "top_country":"US", …}` | reads analytics DB. |
| `DELETE` | `/api/shorten/{key}` | → `200 OK` | invalidates cache + tombstones row. |

---

## 7. Scale & sharding deep dive

- **Shard key:** hash `short_key` onto `[0, N)` shards — uniform load because base62
  keys are uniformly distributed (Snowflake-derived). Avoids hot-shard from sequential
  auto-increment counters.
- **Read replicas:** redirects read from DB replicas / cache only; writes hit the
  primary shard. 92% cache hit rate keeps DB read load at **925.9 /s** (Section 4).
- **Cache stampede:** for viral keys, coalesce concurrent misses (single-flight /
  request coalescing) and pin a small local LRU in the redirect pod.
- **Analytics sharding:** `clicks` partitioned by day (time-series access pattern);
  old days are read-only and roll up into hourly/daily aggregates.

---

### Killer Gotchas

- **301 silently kills analytics.** Browser caches the redirect; subsequent clicks
  never hit your server. Use **302** when click tracking matters.
- **6-char hash keys collide by ~298k URLs** (birthday paradox on 56.8B keyspace).
  Either go to 7 chars, or check-and-rehash — *always* handle collisions.
- **Auto-increment leaks your URL count** and is a single point of coordination;
  at scale prefer **Snowflake** (distributed, no SPOF).
- **Blocking analytics on the redirect path** blows the 50ms p99 budget. Click events
  must be **fire-and-forget to Kafka**, aggregated downstream.
- **Cache stampede on viral links** — without request coalescing, a cold cache miss
  for a hot key fans out into thousands of identical DB reads in one ms.
- **Short URLs are forever** (or until expiry) — the redirect path is a durability
  commitment; multi-AZ DB + replicas, never lose a mapping.

---

### Reproduce

```bash
python3 url_shortener.py          # prints all sections + [check] OK
```

> From `url_shortener.py` **Section 6 — GOLD CHECK** (values pinned for `url_shortener.html`):

```
base62_encode_12345      = 3d7
base62_encode_100m       = 6LAze
base62_decode_6LAze      = 100000000
key6_capacity            = 56800235584
key7_capacity            = 3521614606208
write_qps_avg            = 1157.4
read_qps_avg             = 11574.1
storage_per_year_tb      = 18.25
read_write_ratio         = 10
```

`[check] GOLD reproduces from base62 + scale formulas? OK` — the gold badge `check: OK`
at the bottom of [`url_shortener.html`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/url_shortener.html)
recomputes base62 + scale in JavaScript and confirms it matches the `.py` exactly.
