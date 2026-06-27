# Design a Pastebin

> **Companion code:** [`pastebin.py`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/pastebin.py).
> **Live demo:** [`pastebin.html`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/pastebin.html) — open in a browser.

---

## 0. TL;DR — the one idea

> **The analogy:** a pastebin is an **immutable, write-once object store**
> (`short_slug → paste body`) where the body itself is **addressed by its SHA-256
> digest**, so reposts dedup for free, reads are served a **thousand times more than
> writes** and are pushed as far toward the CDN edge as possible.

The whole system reduces to two operations — **create a paste** (write, rare:
hash the body, store the object once, mint a short slug, return a URL) and **read a
paste** (read, constant: resolve the slug, serve the cached/immutable body). Every
other concern (content-addressing vs IDs, dedup, TTL cleanup, public/unlisted/private
access control) hangs off those two ops.

```mermaid
graph LR
    U(["user"]) -->|POST /api/pastes| GW["API Gateway<br/>(rate limit, auth, abuse scan)"]
    U -->|GET /{slug}| CDN["CDN<br/>(immutable, 24h+ TTL)"]
    CDN -.miss.-> GW
    GW -->|write| PS["Paste Service"]
    GW -->|read| PS
    PS -->|"SHA-256(body) = object key"| OBJ[("Object Storage<br/>S3, content-addressed")]
    PS -->|metadata| DB[("Metadata DB<br/>Postgres")]
    PS -->|warm hot tier| RC[("Redis<br/>recent pastes")]
    PS -.expires_at.-> TTL["Cleanup Pipeline<br/>(soft 404 + async reclaim)"]
    style CDN fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style PS fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style OBJ fill:#eaf2f8,stroke:#2980b9
    style TTL fill:#fef9e7,stroke:#f1c40f
```

---

## 1. Requirements

### Functional
- **Create** a paste from arbitrary text, get back a short URL (`pastebin.com/Xy3Kp9`).
- **View** a paste via its short URL; expired pastes return **404**.
- Per-paste **expiration** (10 min / 1 hour / 1 day / 1 week / 1 month / never).
- Per-paste **access tier**: public, unlisted, or private (auth-required).
- **Dedup**: identical content returns the same object (and same URL).
- **Abuse detection**: flag malware / phishing / credential dumps.

### Non-Functional
- **Read latency**: p99 < 50 ms (CDN-served).
- **Write latency**: p99 < 100 ms.
- **Read-heavy**: ≈ **1000 : 1** read:write ratio.
- **Availability** 99.9%; **durability** 11 nines (object-storage backed).
- **Immutability**: paste bodies are write-once, so they cache aggressively everywhere.

---

## 2. Scale Estimation

> From `pastebin.py` **Section 5** (100K pastes/day, 100M reads/day, 10 KB avg):

| Metric | Value |
|---|---|
| New pastes / day | 100,000 |
| Reads / day | 100,000,000 |
| **Read : write ratio** | **1000 : 1** |
| Avg write QPS (create) | 1.16 /s |
| Avg read QPS (view) | 1,157.4 /s |
| Peak read QPS (10× viral) | 11,574 /s |
| Avg paste size | 10.00 KB |
| **Raw storage / day** | **1.00 GB** |
| Raw storage / 5 years | 1.82 TB |
| Read egress bandwidth (payload) | 11.57 MB/s |

> From `pastebin.py` **Section 5** — CDN effect (95% hit on public/unlisted reads):

| Cache metric | Value |
|---|---|
| Reads served from CDN | 1,100 /s |
| Reads still hitting backend | 58 /s |

> From `pastebin.py` **Section 2** — content-addressed dedup (100K creates: 80% fresh + 20% reposts):

| Dedup metric | Value |
|---|---|
| Unique bodies stored / day | 82,563 |
| Duplicate events / day | 17,437 (**17.44% dedup**) |
| Storage after dedup / day | 825.63 MB (saved 174.37 MB) |
| Storage after dedup / 5 yr | 1.51 TB (saved 318.23 GB) |

> From `pastebin.py` **Section 1** — short-slug keyspace (collision lives on the URL only):

| Slug length | Keyspace | First slug clash (~) |
|---|---|---|
| 8 chars | 218,340,105,584,896 (2.18e14) | 18,519,391 pastes |
| 11 chars | 52,036,560,683,837,093,888 (5.20e19) | 9,040,953,400 pastes |

---

## 3. Architecture

```mermaid
graph TD
    LB["Load Balancer / CDN"] --> AGW["API Gateway<br/>rate-limit + auth + abuse scan"]
    AGW -->|POST /api/pastes| SH["Paste Service<br/>(create)"]
    AGW -->|GET /{slug}| RD["Paste Service<br/>(read)"]
    SH -->|"1. SHA-256(body) = content_key"| HZ["Hash + slug mint"]
    HZ -->|2. write-once if new| OBJ[("Object Storage S3<br/>keyed by SHA-256")]
    HZ -->|3. metadata row| DB[("Metadata DB<br/>Postgres")]
    SH -->|warm| CA[("Redis hot tier<br/>recent 7 days")]
    RD -->|1 read cache| CA
    CA -.miss.-> DB
    RD -->|2 fetch body| OBJ
    DB -.tracks expires_at.-> CL["Cleanup Pipeline<br/>(nightly async reclaim)"]
    CL -.deletes last-ref.-> OBJ
    AGW -.inline scan.-> AB["Abuse Detection<br/>(YARA + entropy)"]
    RD -->|3 serve immutable body| LB
    style CA fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style RD fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    style OBJ fill:#eaf2f8,stroke:#2980b9
    style CL fill:#fef9e7,stroke:#f1c40f
```

### Key Components

| Component | Technology | Why |
|---|---|---|
| API Gateway | Kong / Envoy | Rate-limit abuse-prone `POST`, TLS, inline abuse scan (YARA + regex, ~50 ms). |
| Paste Service | stateless Go/Java pods | Hash body, mint slug, write object + metadata + cache. Horizontally scalable. |
| Object Storage | **S3, content-addressed** | Object key = full SHA-256. 11-nines durability; immutable → trivially cacheable. |
| Metadata DB | Postgres | `slug → content_key, tier, expires_at, owner`. Read replicas absorb cache misses. |
| Redis hot tier | Redis cluster | Recent (≤7-day) pastes behind the CDN; sub-ms reads. |
| CDN | CloudFront / Cloudflare | Paste bodies are immutable, so 24h+ TTL is safe; 95% edge hit rate. |
| Cleanup Pipeline | async batch job | Soft-delete (404 on read) + nightly physical reclaim after 24h grace. |
| Abuse Detection | YARA + ML classifier | Inline blocks known patterns; async ML flags phishing/entropy for review. |

---

## 4. Key Design Decisions

### 4.1 Content-addressed storage vs ID-based

> From `pastebin.py` **Section 1** (SHA-256 → key → slug) and **Section 2** (dedup):

| Decision | Option A | Option B | Winner | Why |
|---|---|---|---|---|
| **Object addressing** | **Content-addressed** (key = SHA-256) | ID-based (random base62 → arbitrary body) | **Content-addressed** | Identical content → identical key → **free dedup** (17.4% storage saved); immutability is structural, not policy; write-once is self-evident. Cost: reclaim becomes refcounted. |

- **Object key = full 256-bit SHA-256** (64 hex). Zero collision risk; true dedup.
- **URL slug = truncated hash** (11 base62 chars, keyspace 5.2e19) — collision-checked against the full hash. A slug clash appends a salt and rehashes the slug; the object is **never** overwritten.
- Worked example (from the simulation): `print('hello world')` → key `939338e3…f3c117` → slug `yZFeDe0w8YK`. The same text pasted twice returns the same key and URL.

### 4.2 Storage backend: object storage (S3) vs database BLOB

| Decision | Option A | Option B | Winner | Why |
|---|---|---|---|---|
| **Body storage** | **Object storage (S3)** | DB BLOB / TEXT column | **Object storage** | 10 KB–1 MB bodies are too big for the hot DB row; S3 gives 11-nines durability at ~$0.023/GB, content-addressed keys map 1:1 to object keys, and immutable objects cache perfectly on the CDN. The DB only holds metadata. |

### 4.3 Expiration (TTL) strategy

> From `pastebin.py` **Section 3** (two-phase deletion):

| Decision | Option A | Option B | Winner | Why |
|---|---|---|---|---|
| **TTL enforcement** | Read-path check (`expires_at → 404`) | Eager background sweep only | **Read-path soft delete + async hard reclaim** | Checking `expires_at` on read makes a paste vanish instantly with zero storage work; the nightly job then physically deletes the object after a 24h grace window (also catches never-read expired pastes). |

- **Soft delete** (read path): if `expires_at < now`, return 404 — instant, no I/O.
- **Hard reclaim** (async nightly): delete objects whose **last** referencing metadata row is past the grace window; S3 lifecycle policies handle cold-tier cleanup natively.
- **Never-expire** pastes accumulate at ~10,000/day → **3.65 M/year → 36.50 GB/year** — manageable; eventually tier to cheapest storage.

### 4.4 Access control (public / unlisted / private)

> From `pastebin.py` **Section 4**:

| Decision | Tier | CDN cache? | Notes |
|---|---|---|---|
| **public** (60%) | anyone, indexed | yes (24h+) | Full edge caching. |
| **unlisted** (30%) | anyone with URL, not indexed | yes | The slug is the secret — **unguessable** slugs are mandatory. |
| **private** (10%) | owner only (token) | **NO** | Bypass CDN, hit service, optional at-rest encryption. ~2% of reads but always backend. |

---

## 5. Data Model

### `pastes` (metadata — sharded by `slug`)

| Column | Type | Notes |
|---|---|---|
| `slug` | VARCHAR(11) | **PK**, truncated hash, base62. URL slug; collision-checked. |
| `content_key` | CHAR(64) | Full **SHA-256** = object storage key. The dedup pivot. |
| `title` | VARCHAR | Optional. |
| `owner_id` | BIGINT | Nullable (anonymous creates). |
| `tier` | ENUM | `public` / `unlisted` / `private`. |
| `expires_at` | TIMESTAMP | NULL = never. Soft-delete check on read. |
| `storage_tier` | ENUM | `hot` / `warm` / `cold` / `archive`. |
| `created_at` | TIMESTAMP | Creation time. |
| `taken_down` | BOOLEAN | Abuse takedown → 410 Gone. |

### `content_objects` (refcount for dedup reclaim)

| Column | Type | Notes |
|---|---|---|
| `content_key` | CHAR(64) | **PK**, full SHA-256. |
| `size_bytes` | BIGINT | Body size. |
| `refcount` | INT | Number of `pastes` rows pointing here. Object is deleted only when `refcount → 0`. |

---

## 6. API Endpoints

| Method | Path | Body / Response | Notes |
|---|---|---|---|
| `POST` | `/api/pastes` | req `{content, ttl, tier, title?}` → `{slug, url, content_key}` | rate-limited; inline abuse scan; dedup returns existing slug for identical content. |
| `GET` | `/{slug}` | → paste body + metadata | CDN-first (public/unlisted); auth check for private; 404 if expired. |
| `DELETE` | `/api/pastes/{slug}` | → 204 | owner only (auth); decrements refcount, invalidates cache. |
| `POST` | `/api/pastes/{slug}/report` | → `{status:"queued"}` | queues abuse review; takedown sets `taken_down` → 410. |

---

## 7. Caching & cleanup deep dive

- **Four read layers** (immutable bodies cache aggressively): (1) **CDN edge** 24h+
  TTL, 95% hit; (2) **Redis hot tier** (≤7-day window) behind CDN misses; (3) **DB
  read replicas** for metadata; (4) **object storage** cold read only on a true miss.
- **Dedup reclaim is reference-counted** (`content_objects.refcount`). Several metadata
  rows may point at one object key; the reclaim job deletes the object **only when the
  last row expires**, or storage leaks *or* live pastes 404.
- **Cache stampede on a viral paste** — coalesce concurrent misses (single-flight);
  the immutable CDN is the primary defense, so even a viral paste is mostly edge-served.
- **Cold-tier latency spike** — monitor per-tier read rates; alert when cold reads
  (S3 fetch) exceed threshold, which means the hot tier is undersized.

---

### Killer Gotchas

- **Truncating the hash for the URL risks FALSE dedup.** Two different pastes can share
  an 11-char slug but **never** the full 256-bit object key. Always key the object by
  the full hash; on a slug clash, salt + rehash the slug. Never overwrite a body.
- **Dedup makes reclaim reference-counted.** Deleting an object when *any* referencing
  paste expires will 404 a still-live paste; never deleting will leak storage. Keep a
  `refcount` per `content_key` and delete only at zero.
- **Caching private pastes on a shared public CDN is a leak.** Tag cache keys with the
  tier; private reads use a per-user namespace or skip the CDN and go service → Redis
  (per-token key).
- **Unlisted ≠ private.** Unlisted relies on the slug being unguessable; a predictable
  slug generator (auto-increment, sequential base62) turns "unlisted" into "public".
  Use a high-entropy, hash-derived slug.
- **Blocking abuse scan on the create path** blows the 100 ms write budget. Inline
  scan only known patterns (~50 ms); defer ML/entropy classification to an async queue.
- **"Never expire" pastes fill storage forever.** ~10K/day → 36.5 GB/year; apply
  lifecycle policies even to "never-expire" (e.g., archive if unread for 3 years).

---

### Reproduce

```bash
python3 pastebin.py          # prints all sections + [check] OK
```

> From `pastebin.py` **Section 6 — GOLD CHECK** (values pinned for `pastebin.html`):

```
sha256_probe_hex64     = 939338e3b6ab652043d93dff9c1e8eaa69a0a969a4a0de50870a6cbad7f3c117
sha256_probe_hex16     = 939338e3b6ab6520
sha256_slug_11         = yZFeDe0w8YK
sha256_full_b62_len    = 43
write_qps_avg          = 1.2
read_qps_avg           = 1157.4
storage_per_day_b      = 1000000000
storage_5yr_b          = 1825000000000
read_write_ratio       = 1000
avg_paste_size_b       = 10000
```

`[check] GOLD reproduces from SHA-256 + scale formulas? OK` — the gold badge `check: OK`
at the bottom of [`pastebin.html`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/pastebin.html)
recomputes **SHA-256 in pure JavaScript** and the scale formulas, and confirms they match
the `.py` exactly (probe hash, 11-char slug, QPS, storage, ratio).
