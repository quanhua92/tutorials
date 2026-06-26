# Dockerfile — Layers, Build Cache & Multi-Stage, Visually

> **Companion code:** [`dockerfile.py`](./dockerfile.py). **Every number in this
> guide is printed by `uv run python dockerfile.py`** — change the code, re-run,
> re-paste. Nothing here is hand-computed.
>
> **Sibling guides:** [`OVERLAYFS.md`](./OVERLAYFS.md) (how the layers this guide
> *builds* get *stored* and copy-on-write'd at runtime) and
> [`NAMESPACES.md`](./NAMESPACES.md). Cross-references are marked 🔗 throughout.
>
> **Live animation:** [`dockerfile.html`](./dockerfile.html) — open in a browser.

---

## 0. TL;DR — the assembly line with a photographer

### Read this first — the recipe on the conveyor belt

A Dockerfile is a **recipe** executed on an **assembly line**. Each instruction
(`FROM`, `RUN`, `COPY`, …) is one **workstation** along the line. After every
workstation, a **photographer snaps a photo** of the whole conveyor belt and
files it — that photo is a **layer** (a frozen filesystem snapshot).

```mermaid
graph LR
    F["FROM<br/>base image"] --> R["RUN<br/>shell cmd"]
    R --> C["COPY<br/>files in"]
    C --> M["CMD<br/>default process"]
    style F fill:#0d2438,stroke:#2980b9
    style R fill:#0d2438,stroke:#2980b9
    style C fill:#0d2438,stroke:#2980b9
    style M fill:#2a2233,stroke:#8e7cc3
```

- The finished **image** is just the **stack of photos**, bottom (base OS) to
  top (your last instruction). To run a container, OverlayFS lays them down as
  read-only lowers and adds one writable sheet on top 🔗 ([OVERLAYFS.md](./OVERLAYFS.md)).
- Next time you run the **same** line, the photographer checks each workstation
  in order: *"is everything up to here — the parent photo AND this workstation's
  inputs — identical to last time?"* If yes, **skip the work, reuse the filed
  photo**: a cache **HIT**. The first workstation where an input changed has no
  matching photo: a cache **MISS**. From a miss onward, **every** following
  workstation is also a miss — the photos downstream no longer line up. That
  cascade is cache invalidation.

The cardinal rule falls straight out of the cascade: put things that **change
often** (your app source) **late** in the recipe, and things that change
**rarely** (system deps, package installs) **early**. Then an app edit reuses
every cached photo up to the `COPY` and re-photographs only from there.

> **One-line definition:** a *Dockerfile* is an ordered list of instructions;
> each `FROM`/`RUN`/`COPY` **commits a layer**, each layer's cache key hashes in
> its **parent + inputs**, so **one change invalidates that line and everything
> after it**. `CMD`/`ENV` edit the image *config*, not the layer stack.

### Glossary (every term used below)

| Term | Plain meaning |
|---|---|
| **instruction** | one line of the recipe. Kinds: `FROM` (base), `RUN` (shell → fs layer), `COPY`/`ADD` (context files → fs layer), metadata (`CMD`,`ENV`,`EXPOSE`,`ENTRYPOINT`) → image **config**, *not* a layer |
| **layer** | the frozen snapshot one instruction produces; content-addressed: `key = sha256(parent_key + kind + inputs)` |
| **cache key** | the digest the photographer compares. For `RUN` it's the command string; for `COPY` it's the command **plus the checksum of the source files** — so editing a copied file busts the cache though the line text is identical |
| **cache HIT / MISS** | HIT = identical parent + inputs seen before, reuse it. MISS = no match, re-execute & re-photograph. **One MISS cascades** to every later instruction |
| **build context** | the directory the client TARs up and sends the daemon at `docker build`, *before* any instruction runs. `.dockerignore` trims it |
| **`.dockerignore`** | exclude patterns; matched files never enter the context (and never bust `COPY`-cache for nothing) |
| **multi-stage** | several `FROM` blocks in one file. Build fat in an early stage, `COPY --from=` only the artifact into a **minimal final stage**. The final image is the **last** stage — the compiler never ships |
| **base image** | the `FROM` you start from. `ubuntu` (full) vs `*-slim` vs `alpine` vs `distroless` vs `scratch` is the biggest lever on final size + attack surface |

---

## 1. Each instruction commits a layer (`.py` Section A)

The canonical 4-instruction Dockerfile. Each row is one workstation; the layer id
is the photographer's photo at that point:

| # | instruction | layer id | adds | cache (cold) |
|---|---|---|---|---|
| 0 | `FROM ubuntu:22.04` | `30970ed4af28` | 68.7 MiB | COLD |
| 1 | `RUN apt-get update && apt-get install -y python3` | `9d0c75233047` | 45.8 MiB | COLD |
| 2 | `COPY app/ /app/` | `ee747f76da3a` | 8.1 MiB | COLD |
| 3 | `CMD ["python3", "/app/main.py"]` | `ca94af79b8ef` | — config — | COLD |

**4 instructions → 3 filesystem layers + 1 config (`CMD`).** Final image =
**122.5 MiB** (the sum of the 3 fs layers). `CMD` writes *no* layer — it only
sets the default process in the image config JSON (~0 bytes).

The key chain is what makes the cascade inevitable — each key depends on the one
above it:

```
key(0) = sha256( ROOT            + FROM + ubuntu:22.04                    ) = 30970ed4af28
key(1) = sha256( 30970ed4af28    + RUN  + apt-get ... python3             ) = 9d0c75233047
key(2) = sha256( 9d0c75233047    + COPY + app@sha256:a1b2c3               ) = ee747f76da3a
key(3) = sha256( ee747f76da3a    + CMD  + ["python3","/app/main.py"]      ) = ca94af79b8ef
```

> 🔗 These layers are the read-only `lowerdir`s an OverlayFS mount stacks — see
> [`OVERLAYFS.md`](./OVERLAYFS.md) §1.

---

## 2. The build cache — one MISS cascades; order by change rate (`.py` Section B)

### Scenario 1 — you edit a file in `app/` and rebuild

The `COPY` line **text** is identical, but its `content_tag` (the checksum of
`app/`) changed, so the cache key for line 2 differs → **MISS**, and `CMD`
after it cascades:

| # | instruction | layer id | cache |
|---|---|---|---|
| 0 | `FROM ubuntu:22.04` | `30970ed4af28` | **HIT** (reused) |
| 1 | `RUN apt-get … python3` | `9d0c75233047` | **HIT** (reused) |
| 2 | `COPY app/ /app/` | `1d39409f5818` | **MISS** (re-run) |
| 3 | `CMD ["python3", "/app/main.py"]` | `75422f83e547` | **MISS** (re-run) |

**Cache vector = `[HIT, HIT, MISS, MISS]`** → **2 of 4** instructions re-run (the
`COPY` + the `CMD` config). The two *expensive* layers (ubuntu, apt) are reused
— zero `apt-get`, zero download.

### Scenario 2 — the cardinal rule: order by change frequency

Two Dockerfiles that do the **same** thing, ordered differently. You edit
`app/main.py` and rebuild. Watch which layers re-run:

**BAD order** (`COPY app/` *before* `pip install`):

| # | instruction | cache |
|---|---|---|
| 0 | `FROM python:3.10-slim` | HIT |
| 1 | `COPY app/ /app/` | **MISS** |
| 2 | `RUN pip install -r /app/requirements.txt` | **MISS** |
| 3 | `CMD …` | **MISS** |

→ re-runs **3**, *including the slow `pip install` (60 MB)*, on **every** edit.

**GOOD order** (deps first, app last):

| # | instruction | cache |
|---|---|---|
| 0 | `FROM python:3.10-slim` | HIT |
| 1 | `COPY requirements.txt /tmp/` | HIT |
| 2 | `RUN pip install -r /tmp/requirements.txt` | HIT |
| 3 | `COPY app/ /app/` | **MISS** |
| 4 | `CMD …` | **MISS** |

→ re-runs **only 2** (the `COPY` + `CMD`). `pip install` is **cached**.

> Same outcome, radically different rebuild cost. **Rule: least-changing inputs
> first** (base OS, system deps, package lists), **most-changing last** (your
> source). Then a code tweak reuses everything above.

---

## 3. Multi-stage — build fat, ship thin (`.py` Section C)

One Dockerfile, two `FROM` blocks. Stage 1 (**builder**) has the compiler + source
and produces a binary. Stage 2 (**runtime**) is a minimal image that copies *only*
that binary. The final image is the **last stage** — the compiler never ships.

**Stage 1 — builder (golang + source + build):**

| # | instruction | adds |
|---|---|---|
| 0 | `FROM golang:1.21 AS builder` | 747.7 MiB |
| 1 | `COPY . /src` | 3.8 MiB |
| 2 | `RUN go build -o /out/server` | 11.4 MiB |

**Builder total = 762.9 MiB (800 MB).**

**Stage 2 — runtime (alpine + just the binary):**

| # | instruction | adds |
|---|---|---|
| 0 | `FROM alpine:3.19` | 7.6 MiB |
| 1 | `COPY --from=builder /out/server /server` | 11.4 MiB |
| 2 | `CMD ["/server"]` | — config — |

**Runtime total = 19.1 MiB (20 MB) — this is what ships.**

**Savings = 762.9 MiB / 19.1 MiB = 40.0× smaller.** The 762.9 MiB builder — its
compiler, source, build caches, and the 200+ MB Go toolchain — never reach the
registry. The same trick works in any language: compile in the full SDK image,
then `COPY --from=builder` the single artifact into `alpine`/`distroless`/`scratch`.

---

## 4. `.dockerignore` — what you send the daemon matters (`.py` Section D)

`docker build` TARs up the build-context directory and ships it to the daemon
**before** any instruction runs. Everything in it is sent — even files no `COPY`
ever references — so a fat context means a **slow start** *and* spurious
`COPY`-cache invalidation (editing `node_modules` busts `COPY .`).

| path | size | sent without `.dockerignore`? |
|---|---|---|
| `app/` | 7.6 MiB | yes |
| `package.json` | 293.0 KiB | yes |
| `requirements.txt` | 1.2 KiB | yes |
| `node_modules/` | 200.3 MiB | **NO (excluded)** |
| `.git/` | 45.8 MiB | **NO (excluded)** |
| `dist/` | 14.3 MiB | **NO (excluded)** |
| `npm-debug.log` | 1.9 MiB | **NO (excluded)** |
| `.env` | 1.4 KiB | **NO (excluded)** |

**Full context = 270.2 MiB → trimmed = 7.9 MiB (34.1× smaller)**, and the `.env`
secret stays local. `.dockerignore` used:

```
.env
.git/
dist/
node_modules/
npm-debug.log
```

---

## 5. Base image — the biggest single lever on size + security (`.py` Section E)

The `FROM` line dominates final image size. Pick the smallest base that still
runs your app. **Smaller = faster pull, less RAM, fewer CVEs, and no
shell/package-manager for an attacker to use.**

| base image | size | shell? | pkg mgr | best for |
|---|---|---|---|---|
| `ubuntu:22.04` | 72.1 MiB | yes | apt | general; full userspace |
| `python:3.10` | 350.0 MiB | yes | apt+pip | DEV (has build tools) |
| `python:3.10-slim` | 45.0 MiB | yes | apt(min) | PROD python (glibc) |
| `python:3.10-alpine` | 16.0 MiB | yes | apk | tiny; watch musl ABI gaps |
| `gcr.io/distroless/python3-deb12` | 28.0 MiB | **NO** | **NONE** | PROD secure (no shell) |
| `scratch` | 0 B | **NO** | **NONE** | static binary ONLY |

**`distroless`** is the prod sweet spot for interpreted runtimes: it ships the
interpreter + your app and **nothing else** — no shell, no package manager, no
`curl` for an attacker. Pair it with multi-stage (§3): **build** in
`python:3.10`, **run** in `distroless`.

---

## 6. The gold check (`.py` Section F)

Re-derive the canonical numbers `dockerfile.html` must reproduce from the
identical model:

| gold value | value |
|---|---|
| `instruction_count` | 4 |
| `fs_layer_count` | **3** (FROM+RUN+COPY; `CMD` is config) |
| `cache_vector_app_edit` | **`[HIT, HIT, MISS, MISS]`** |
| `rerun_instructions` | **2** |
| `multistage_builder_bytes` | 800,000,000 |
| `multistage_final_bytes` | **20,000,000** |
| `multistage_ratio` | **40.0** |
| `context_full_bytes` | 266,000,000 |
| `context_trimmed_bytes` | 8,000,000 |

The invariants this encodes:

- `fs_layer_count == 3` — only `FROM`/`RUN`/`COPY` commit layers; `CMD` edits config.
- Editing the `COPY` (the common app-source case) yields `[HIT, HIT, MISS, MISS]`
  — the expensive base + deps layers are reused, only `COPY` + `CMD` re-run.
- A multi-stage final image is the **last stage only** (20 MB), while the 800 MB
  builder is discarded (40.0× smaller).

All are asserted in code and re-derived in the live page
([`dockerfile.html`](./dockerfile.html) → green `check: OK`).

---

## Sources

- Dockerfile reference — <https://docs.docker.com/engine/reference/builder/>.
- Build cache — <https://docs.docker.com/build/cache/> (parent-keyed, cascade-on-miss).
- Multi-stage builds (Docker 17.05) — <https://docs.docker.com/build/building/multi-stage/>.
- BuildKit (default frontend since Docker 23.0) — <https://docs.docker.com/build/buildkit/>.
- `.dockerignore` — <https://docs.docker.com/build/building/context/#dockerignore-file>.
- Distroless — <https://github.com/GoogleContainerTools/distroless>.
- OCI Image Format spec — <https://github.com/opencontainers/image-spec>.
- Sibling guides: [`OVERLAYFS.md`](./OVERLAYFS.md) (runtime storage of these
  layers), [`NAMESPACES.md`](./NAMESPACES.md).
