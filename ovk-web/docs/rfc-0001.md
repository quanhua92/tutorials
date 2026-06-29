# RFC 0001 — Product & Architecture

| | |
|---|---|
| **Status** | Draft — awaiting decisions on open questions in §19 |
| **Author** | OpenVideoKit team |
| **Date** | 2026-06-28 |
| **Supersedes** | The prior `0001-cross-platform-desktop-studio.md` (Tauri + Go) **and** the current local-only FastAPI web app (`src/openvideokit/`) |
| **Discussion** | `docs/rfc/` |

---

## 1. Summary

OpenVideoKit becomes a **scene-based, HTML-slide video editor** — a
PowerPoint / Canva / Google Vids class tool — delivered as a **Python local
application** (browser-served) with an optional **Python cloud control plane**.

The core idea is a strict, two-level separation of concerns:

> **JSON is data. HTML is animation.**

Every unit in a project — the project root and each slide — is a folder with
two files: `index.html` (the animation/visual) and `index.json` (the data).
The slide `index.html` files are bare `<template>` sub-compositions; the root
`index.html` is the HyperFrames host that sequences them. **The editable
source files *are* HyperFrames' files** — export is arrange + stamp data +
render, with zero format translation.

An **app-owned preview engine** renders slides live in the browser behind a
`SlideRenderer` interface. HyperFrames is the initial renderer implementation
for both preview and export; it is replaceable by our own renderer later
without touching the editor. **Preview and export share one engine, so "it
looked different when I exported" is structurally impossible.**

AI is a staged two-tier assistant (see
[RFC 0002 — AI Subsystem](./0002-ai-subsystem.md)): a small model fills the
data layer over curated templates (the cheap default path); a coding model
optionally authors slide HTML for polish.

The cloud control plane and billing are **additive, not required for v1**
(local-first). This RFC supersedes the prior Tauri/Rust + Go design entirely;
the stack is **Python end-to-end**.

---

## 2. Motivation

The current app is a generated HTML form that stamps values into templates and
renders via HyperFrames. It works for prototyping but cannot support:

- **A real editing surface** — there is no timeline, no visual stage, no
  properties panel. The only affordance is a generated form.
- **AI's actual advantage** — the form model boxes AI out of its strength:
  authoring rich HTML/CSS/GSAP animations. AI becomes a slot-filler, not a
  creative collaborator.
- **Decoupled preview/render** — HyperFrames is both the live preview *and*
  the final renderer. You cannot iterate on a preview without coupling to
  HF's composition lifecycle, and preview/render fidelity is only as good as
  HF's internal consistency.

The editor model resolves all three:

- A native-class editor (timeline + stage + properties + per-slide HTML
  editor + asset library + AI dock).
- Slides-as-HTML keeps the canvas open so AI can author animations directly.
- A `SlideRenderer` interface decouples the editor from the engine; preview
  and export go through the same interface.

### 2.1 Why Python, not Tauri/Rust (decision record)

The host language's job here is **glue**: spawn Chromium/FFmpeg/Ollama, stream
OpenRouter responses, serve a web UI, manage files, talk to the cloud. The
performance-critical work (rendering, frame capture, encoding, GPU) happens in
Chromium/FFmpeg regardless of host language — Rust's strengths are wasted on
orchestration.

- The existing code (`config.py`, `templating.py`, `voiceover.py`,
  `captions.py`, `rendering.py`, the FastAPI `app.py`) is **reused, not
  ported**. The prior RFC's largest open risk (porting voiceover/captions to
  Rust) vanishes.
- AI glue (asyncio streaming, JSON/schema handling, prompt management) is
  ergonomic in Python and painful in Rust.
- The reference products — Google Vids, Canva, Figma — are **web apps**.
  Browser-served is the reference class, not a downgrade.
- One language across client and server (shared Pydantic types), no
  Rust/Go/Python split.

The only thing Python costs today is the "double-click native installer" UX —
and the reference products don't have that either. A native shell
(pywebview / Electron / Tauri-with-Python-sidecar) can wrap the same Python
core later with zero logic rewrite (see §14).

---

## 3. Goals & Non-Goals

### Goals

1. A **scene-based editor** (timeline + stage + properties + per-slide HTML
   editor + asset library + AI dock) delivered as a local Python web app.
2. The **JSON = data / HTML = animation** document model, symmetric at project
   and slide level.
3. An **app-owned preview** behind a `SlideRenderer` interface, decoupled from
   the export engine.
4. HyperFrames as the initial renderer (preview + export), **replaceable**
   later by our own renderer; visual determinism.
5. **Incremental migration** from the current codebase — extend, don't rewrite.
6. A **Python cloud control plane** (FastAPI) for auth, projects, assets, and
   billing — additive, deferred past v1.

### Non-Goals (this RFC)

- Mobile / tablet client.
- Server-side render farm (renders stay local for v1).
- Full multi-track NLE (Premiere/Resolve class). Scene-based only.
- Byte-identical determinism (visual determinism suffices — see §11).
- A native signed installer in v1 (deferred — §14).
- Cloud-required operation or cloud-required AI. v1 is local-first; AI is
  local/BYO-key.
- An LLM in the *render* hot path. The renderer (HF or ours) remains
  deterministic; AI only produces the data and the slide HTML that the
  renderer consumes.

---

## 4. Product Concept & Hybrid Compute Split

A **scene-based, AI-assisted HTML-slide video editor**.

| Layer | Runs where | Why |
|---|---|---|
| Editor UI, preview, export, AI inference | **Local Python app** (browser-served) | Latency-sensitive; keeps AI + API keys on-device; reuses existing code |
| Auth, project metadata, S3 vault, asset search, credits | **Cloud Python (FastAPI)** — *deferred past v1* | Central source of truth; shareable across devices |
| Per-slide rendering (preview + export) | **`SlideRenderer` interface** — HF now, ours later | Proven POC; replaceable behind an interface |

Cloud is **additive**. v1 (P0) ships as a local app with no cloud dependency.

---

## 5. Core Document Model (the heart)

> **JSON is data. HTML is animation.** — at *both* granularities.

### 5.1 Symmetric unit structure

Every unit — the project root and each slide — is a folder with two files:

```
project/                     ← root unit
├── index.html               ← HF root composition (HOST)
├── index.json               ← root DATA
├── slides/
│   ├── slide-0/             ← slide unit
│   │   ├── index.html       ← bare <template> sub-composition
│   │   └── index.json       ← slide DATA
│   └── slide-1/
│       ├── index.html
│       └── index.json
└── assets/                  ← images, audio, fonts (content-addressed by SHA-256)
```

| Unit | `index.html` (animation) | `index.json` (data) |
|---|---|---|
| **Root** | HF root **host**: slide host-divs (`data-composition-src`), transitions **between** slides (`<!-- SCENE_TRANSITIONS -->`), audio playback, caption overlay | canvas, theme, audio refs, slide ordering, `transition_default` |
| **Slide** | bare `<template>` sub-composition: `data-composition-id="__SLIDE_ID__"`, CSS, GSAP **within-slide** timeline, `__FIELD__` placeholders | fields (values), asset refs (SHAs), voiceover text + voice, measured duration |

### 5.2 Root `index.json` (minimal, project-wide)

```jsonc
{
  "version": 1,
  "canvas": { "width": 1920, "height": 1080, "fps": 30 },
  "theme":  { "caption_style": "highlight", "colors": {}, "fonts": {} },
  "audio":  {
    "music":     { "asset": "sha256:...", "volume": 0.08, "loop": true },
    "voiceover": { "asset": "voiceover.mp3", "auto_generated": true }
  },
  "transition_default": { "type": "crossfade", "duration": 0.4 },
  "slides": ["slide-0", "slide-1", "slide-2"]
}
```

### 5.3 Slide `index.json` (per-slide data only)

```jsonc
{
  "id": "slide-0",
  "duration": 5.0,                              // measured (from voiceover timings)
  "transition": { "type": "push", "duration": 0.5 },  // optional override of transition_default
  "fields":  { "title": "Eco Bottle", "body": "..." }, // injected via __FIELD__
  "assets":  { "img": "sha256:..." },
  "voiceover": { "text": "Narration...", "voice": "vi-VN-HoaiMyNeural" }
}
```

### 5.4 Slide `index.html` (bare `<template>` composition)

Matches the layout file format mandated by
[`AGENTS.md`](../../AGENTS.md):

```html
<template>
  <div data-composition-id="__SLIDE_ID__" data-width="1920" data-height="1080">
    <div class="content">
      <h1>__TITLE__</h1>
      <p>__BODY__</p>
    </div>
    <style>
      [data-composition-id="__SLIDE_ID__"] { background: #0a0a14; }
      [data-composition-id="__SLIDE_ID__"] .content { text-align: center; padding-top: 38vh; }
    </style>
    <script>
      var tl = gsap.timeline({ paused: true });
      tl.from('[data-composition-id="__SLIDE_ID__"] .content > *',
              { opacity: 0, y: 40, duration: 0.4, stagger: 0.1 });
      window.__timelines['__SLIDE_ID__'] = tl;
    </script>
  </div>
</template>
```

### 5.5 Why this model (decision records)

**Why slides-as-HTML, not a JSON scene graph holding the visuals.**
A JSON scene graph flattens AI's expressiveness into a fixed vocabulary the
renderer/compiler understands. Slides-as-HTML keeps the canvas open: AI can
author any HTML/CSS/GSAP it's capable of. The JSON carries only the data the
editor UI binds to.

**Why bare `<template>` compositions.**
This is HyperFrames' native sub-composition format and the format
[`AGENTS.md`](../../AGENTS.md) already mandates. HF's runtime extracts
`<template>` content and mounts it; an `<html>` wrapper causes HF to render
the sub-comp blank (verified in HF v0.7.3). Using it as the source format
means **zero translation at export** (§10).

**Why `index.html` + `index.json` per unit (symmetric naming).**
Every unit is a folder with the same two filenames. The convention
disambiguates by folder (`slide-0/index.html` vs root `index.html`), matches
filesystem-site conventions (Next.js et al.), and makes "a unit is a folder"
trivial to reason about, duplicate, reorder, and delete.

**Why JSON holds only data (not the timeline structure).**
Animation timing, motion, layering, and transitions live in the HTML where AI
authors them. The editor's "timeline" panel is a *view* over `(slide order +
measured durations)` — not a rich structure it persists. This keeps the data
layer small, stable, and ideal for small-model AI edits (RFC 0002).

**Why `html_override` is a fork, not in-place.** *(Future, when Tier-2 AI
customizes a slide's HTML.)* A Tier-2 customization copies the template's
slide folder and edits the copy. The slide's data still re-injects via
`__FIELD__`. This preserves template lineage and keeps the shared template
reusable across slides and projects.

### 5.6 Data binding (how `fields` reach the HTML)

Stamping — `__FIELD__` string replacement — remains the data-injection
mechanism, because HF's `getVariables()` returns `{}` in sub-compositions
([`AGENTS.md`](../../AGENTS.md)). The editor:

- Stamps on structural change (slide add/remove/reorder, layout swap).
- Live-binds text **fields** for responsive editing (textarea → immediate
  preview update via a light DOM patch, no full re-stamp).
- Fully re-stamps at export.

Each field id uppercases to its placeholder: field `title` → `__TITLE__`.

---

## 6. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  LOCAL PYTHON APP  (FastAPI + uvicorn, browser-served)        │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  EDITOR UI (browser)                                   │  │
│  │   Timeline · Stage · Properties/data · HTML editor ·   │  │
│  │   Asset library · AI dock                              │  │
│  └────────────────────────────────────────────────────────┘  │
│      │  read/write project files           │ render           │
│      ▼                                     ▼                  │
│  ┌─────────────────────┐         ┌────────────────────────┐  │
│  │  Project workspace  │         │  PREVIEW ENGINE        │  │
│  │  (index.html/json + │         │  app-owned; drives      │  │
│  │   slides/ + assets/)│         │  SlideRenderer from     │  │
│  └─────────────────────┘         │  playhead; audio sync   │  │
│          │                       └────────────────────────┘  │
│          │                                                 │
│          │  AI (RFC 0002): Tier-1 edits index.json;         │
│          │             Tier-2 edits slide index.html        │
│          │                                                 │
│          │  Export ▼                                       │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  EXPORT: assemble + stamp → HF workspace →             │ │
│  │  npx hyperframes render → MP4 (visual determinism)     │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
│  REUSED: templating · voiceover · captions · rendering       │
└──────────────────────────────────────────────────────────────┘
               │ HTTPS (project/asset sync)        [P1, deferred]
               ▼
┌──────────────────────────────────────────────────────────────┐
│  CLOUD PYTHON CONTROL PLANE (FastAPI)        [deferred past v1]│
│   auth · projects · S3 + presign · asset search · credits    │
│   ** NO inference — all AI is local / BYO-key **             │
└──────────────────────────────────────────────────────────────┘
```

---

## 7. Editor Surfaces

All surfaces operate on the same workspace files; switching is lossless.

| Surface | Binds to | Job |
|---|---|---|
| **Timeline** (bottom) | root `index.json` (slide order) + each slide `duration` | reorder slides, see per-slide durations, audio lane |
| **Stage / Canvas** (center) | active slide | live preview via `SlideRenderer`; play/scrub |
| **Properties / data** (right) | slide `index.json` | edit `fields`, asset refs, voiceover text, transition override |
| **HTML editor** (per slide) | slide `index.html` | edit within-slide animation; the **AI Tier-2 surface**; power users |
| **Root HTML editor** | root `index.html` | edit between-slides transitions, sequencing, audio, captions |
| **Asset library** (left) | [RFC 0003](./0003-asset-intelligence.md) search | browse/drop assets → SHA ref lands in `index.json` |
| **AI dock** | project files | generate/refine (RFC 0002) |

Undo/redo falls out naturally as file/JSON mutations, not HTML diffs.

---

## 8. App-Owned Preview Engine

The preview is **app-owned** — the editor drives it; HyperFrames is not in
the editing loop as a black box.

- Renders the active slide's `index.html` (the bare `<template>`) in the
  browser via the `SlideRenderer` interface.
- Drives GSAP timelines from the playhead time.
- Syncs audio via the external-`<audio>` pattern documented in
  [`AGENTS.md`](../../AGENTS.md) ("Preview audio").
- **Real-time, not frame-accurate.** That is the point of decoupling: the
  preview is responsive for editing; the export is rigorous (§10).

The preview engine sits behind the `SlideRenderer` interface (§9), so the
engine is pluggable without touching the editor.

---

## 9. The `SlideRenderer` Interface & the HF → Own-Renderer Path

### 9.1 The interface

```
interface SlideRenderer:
    load(slide_html, fields, assets)   # mount a slide composition
    render_at(timecode) -> frame       # render at time t (preview or capture)
    duration() -> seconds
```

Preview and export **both** go through this interface.

### 9.2 Implementation 1 (POC, now): HyperFrames

- **Preview:** instantiate HF's `<hyperframes-player>` per active slide;
  drive it to the playhead.
- **Export:** assemble slides + data into one HF composition; call
  `npx hyperframes render` once (§10). Proven, reuses today's render path.

### 9.3 Implementation 2 (future): our own renderer

Headless-Chromium frame capture + FFmpeg encode/mux, targeting **visual
determinism** (§11). Swaps in behind the same interface; the editor and
export pipeline are unchanged.

### 9.4 Why this kills fidelity drift (decision record)

Preview and export share **one interface → one engine at every stage**. POC:
both use HF → consistent. Later: both swap to our renderer together → still
consistent. "It looked different when I exported" is **structurally
impossible**, because preview and render are never two different engines. This
is the single biggest risk of a decoupled-preview architecture, eliminated by
construction.

### 9.5 Why "make HF smaller"

HF's role contracts from "the whole composition engine" to "render this one
slide at time *t*." Its surface becomes small, well-defined, and replaceable.
Timeline orchestration, the document model, and the editor are all **ours**;
HF is a pluggable rendering primitive.

---

## 10. Export Pipeline

Export is **assembly + stamp + render** — no format translation, because the
source files are already HF's files.

1. Assemble: write the workspace into HF's expected layout —
   `index.html` (root host) + `compositions/slide-N.html` (each slide's
   `index.html` copied verbatim) + `assets/`.
2. Stamp: replace `__SLIDE_ID__` and every `__FIELD__` in each composition
   from the corresponding slide `index.json`.
3. Voiceover: run the existing edge-tts + ffprobe + ffmpeg concat + timings
   pipeline (reused from `voiceover.py`), driven by per-slide
   `voiceover.text`. Update `data-start` / `data-duration` and the root `DUR`
   to the measured voiceover length.
4. Captions: run the existing `captions.build_captions()` pipeline (reused)
   to emit the caption layer + GSAP word-highlight timeline into the root
   `index.html` markers.
5. Render: `npx hyperframes render <workspace> --output scene.mp4`.
6. Stream progress: parse HF stdout → emit progress events → UI progress bar.

The assembler must emit output that obeys the **full
[`AGENTS.md`](../../AGENTS.md) contract** (bare `<template>`,
`position:absolute;inset:0;` host divs, caption rules — no
`transform`/`scale`/`font-size` on `.word--active`, GSAP direct color tweens,
`__PLACEHOLDER__` convention). [`AGENTS.md`](../../AGENTS.md) is the
**export-target spec**.

---

## 11. Determinism

**Visual determinism**, not byte-identical.

- Same input → visually equivalent output across re-renders. Minor byte
  differences (encoder/browser non-determinism) are allowed.
- FFmpeg with fixed params is near-byte-deterministic; the variable part is
  browser capture, which only matters once we ship our own renderer.
- Cache keying and "did this edit change the output" diffs use **perceptual
  hashing**, not byte hashing.

Byte-identical determinism is a non-goal. If it ever becomes required (e.g.,
for CI gate precision), it can be tightened later (pin Chromium, force CPU
rasterization, full asset preload) without rearchitecting.

---

## 12. Local Python App Stack

| Concern | Choice |
|---|---|
| Server | FastAPI + uvicorn — **extends current `app.py`** |
| Concurrency | `asyncio` for AI streaming + process spawning; thread-based wrapper for the existing TTS `asyncio.run()` pattern ([`AGENTS.md`](../../AGENTS.md) pitfall #2) |
| Templating | Jinja2 + `__FIELD__` stamping (reused) |
| Voiceover | `edge-tts` + ffprobe + ffmpeg (reused from `voiceover.py`) |
| Captions | word-level karaoke + GSAP (reused from `captions.py`) |
| Render subprocess | `npx hyperframes` (reused from `rendering.py`) |
| AI client | new — see [RFC 0002](./0002-ai-subsystem.md) |
| Workspace root | unchanged shape: `index.html` / `compositions/` / `assets/` / `.ovk/` |

Net-new modules: `editor` (UI), `preview` (engine), `renderer` (interface + HF
impl), `ai_client` (RFC 0002), `export` (assembler). Everything else is
extended, not rewritten.

---

## 13. Cloud Control Plane (deferred past v1; details in RFC 0003 / 0004)

Python FastAPI (was Go in the prior RFC). Responsibilities: OAuth2/JWT auth,
project metadata, S3 + presigned URLs, asset catalog + search
([RFC 0003](./0003-asset-intelligence.md)), credit ledger
([RFC 0004](./0004-credits-and-billing.md)).

The control plane stores the project document (`index.json` files + slide
HTML) as **opaque content** during sync. It never interprets, renders, or
runs inference on it. **No inference runs in the cloud** — all AI is local /
BYO-key (RFC 0002).

### 13.1 Endpoint sketch (P1)

```
POST /auth/oauth/{provider}/callback   → { access_jwt, refresh_jwt }
GET  /projects                         → list
POST /projects                         → { id, name }
GET  /projects/{id}/manifest           → project files + presigned asset URLs
POST /projects/{id}/assets/presign     → { upload_url }
```

---

## 14. Distribution & CI/CD

- **v1:** a local web app. Run command + open browser. No installer.
- **Native shell (deferred):** wrap the same Python core in
  pywebview / Electron / Tauri-with-Python-sidecar when distribution demands.
  **Zero core rewrite either way** — the shell is a packaging concern.
- **CI:** Python packaging; **no Rust cross-compile matrix** (a major
  simplification vs the prior Tauri RFC). Smoke test: boot the app, run a
  1-frame render, assert exit 0.

---

## 15. Migration Path (incremental, not a rewrite)

| Phase | Scope | Exit criterion |
|---|---|---|
| **P0 — Local editor + AI** | Editor UI, app-owned preview, `SlideRenderer` (HF), staged two-tier AI (RFC 0002). Fully local, no cloud. | A user produces a video via the editor + AI, building on today's codebase. |
| **P1 — Cloud + assets** | Python control plane (auth, projects, S3, sync), asset library (RFC 0003). | Cross-device project sync. |
| **P2 — Billing** | Credits + template/asset unlocks + cloud render (RFC 0004). | Template unlock live. |

### 15.1 Existing templates carry over ~1:1

The current `templates/<id>/` format *already is* this model, packaged
differently: each `layouts/*.html` is a bare-`<template>` slide HTML source
with `__PLACEHOLDER__` markers; `default_slides` + fields are the data.
Migration is re-packaging:

- Each `layouts/<layout>.html` → `slides/<id>/index.html` (rename markers
  `__PLACEHOLDER__` → `__FIELD__` if needed).
- `default_slides` → per-slide `index.json`.
- Template-level config → root `index.json`.

No heavy importer, no coexistence cruft.

---

## 16. Animation Framework (decision)

**GSAP + vanilla CSS** inside slide `index.html` and the root `index.html`,
matching today's templates and the HF runtime. Do **not** introduce Tailwind
or a motion library into composition files.

- HF drives GSAP timelines natively; the caption rules in
  [`AGENTS.md`](../../AGENTS.md) assume GSAP direct tweens.
- Tailwind is fine for the **app UI** (the editor shell) but forbidden inside
  composition HTML — deterministic, reviewable template files stay
  framework-light.
- This keeps AI Tier-2's edits legible: a coding model that writes vanilla
  CSS + GSAP produces diffs a human can review.

---

## 17. Request / Data Flow

1. **Launch** → Python app boots, serves the editor in the browser.
2. **Open project** → load workspace (`index.html`/`index.json` + `slides/` +
   `assets/`).
3. **Edit** → via Timeline / Properties / HTML editor / Asset library / AI
   dock. All mutate workspace files.
4. **Preview** → `<SlideRenderer>` plays the active slide; audio syncs.
5. **Export** → assemble + stamp + voiceover + captions →
   `npx hyperframes render` → MP4; progress streams to the UI.
6. **Publish (P1, deferred)** → MP4 uploaded to S3 via presigned PUT.

---

## 18. Risks & Tradeoffs

| Risk | Mitigation |
|---|---|
| Preview ↔ export fidelity drift | **Structurally eliminated** — preview and export share one `SlideRenderer` (§9.4) |
| Determinism engineering when we ship our own renderer | Visual determinism bar (§11) is achievable; HF stays as fallback behind the interface |
| Tier-2 AI writes broken/invalid slide HTML | AGENTS.md lint gate (`npx hyperframes lint`) before accepting an HTML edit (RFC 0002) |
| Preview performance at 1080p in-browser | Profile; if webview proves too slow, the renderer interface lets a native canvas/WebGL impl swap in later |
| `open localhost` UX vs native app | Accepted for v1; native shell is a deferred packaging step (§14) |
| HyperFrames stdout format changes break the progress parser | Pin HF version; integration-test the parser in CI |
| Python single-threaded GIL under heavy AI streaming | I/O-bound glue — `asyncio` + thread-pool is sufficient (per the team's Python GIL guidance); heavy compute is in Chromium/FFmpeg, not Python |

---

## 19. Open Questions

| # | Question | Owner |
|---|---|---|
| Q1 | Exact POC export-capture mechanism — confirmed as assemble + `npx hyperframes render` once (§10); revisit if per-slide headless capture is needed before the own-renderer lands. | client |
| Q2 | Native shell choice when distribution demands it — pywebview vs Electron vs Tauri-with-Python-sidecar? | client |
| Q3 | Share Pydantic types across the client/server boundary (P1)? | backend |
| Q4 | Python control-plane deployment target (P1) — containerized FastAPI on ECS/Fly? | infra |
| Q5 | When (if ever) do we commit to building the own renderer to replace HF — firm roadmap item or option? | client |
| Q6 | Should the root `index.html` (between-slides transitions) be user-editable in v1, or generated and locked initially? | product |

---

## 20. Out of Scope (v1)

- Mobile and tablet clients.
- Server-side render farm (renders stay local).
- Full multi-track NLE.
- Byte-identical determinism.
- Native signed installer.
- Real-time collaborative editing (multi-cursor).
- Cloud-required operation or cloud-required AI.

---

## 21. References

- Current architecture: [`docs/architecture.md`](../architecture.md)
- Template & layout contract: [`AGENTS.md`](../../AGENTS.md) (caption rules,
  bare `<template>` format, `__PLACEHOLDER__` convention, preview-audio
  pattern, voiceover `asyncio.run()` pitfall)
- [RFC 0002 — AI Subsystem](./0002-ai-subsystem.md)
- [RFC 0003 — Asset Intelligence](./0003-asset-intelligence.md)
- [RFC 0004 — Credits & Billing](./0004-credits-and-billing.md)
- HyperFrames CLI: https://hyperframes.heygen.com/packages/cli
- FastAPI: https://fastapi.tiangolo.com
- edge-tts: https://github.com/rany2/edge-tts
- Google Vids (reference product): https://workspace.google.com/intl/en_za/products/vids/
