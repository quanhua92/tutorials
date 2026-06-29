# TODO — ovk-web curriculum build plan

Phases × bundles. Each bundle maps to an RFC 0001 section. Mark `[x]` when the
sweep passes (run + lint + output.txt byte-stable + reference.txt ≥2 URLs +
mermaid OK + html runtime OK + gold-check green).

## Phase 0 — Bootstrap + style anchor

- [x] Scaffold project (pnpm/vite/tsx/eslint/mermaid-cli), Justfile, docs
- [x] `unit_model` — RFC §5.1 (STYLE ANCHOR — defines house style)

## Phase 1 — Document Model (RFC §5)  [Batch B1] ✓

- [x] `root_index_json` — §5.2 root schema (canvas/theme/audio/slides)
- [x] `slide_index_json` — §5.3 slide schema (fields/assets/voiceover/duration)
- [x] `data_binding` — §5.6 `__FIELD__` stamping
- [x] `bare_template` — §5.4/§5.5 bare `<template>` sub-composition format

## Phase 2 — Editor Surfaces (RFC §7)  [Batch B2] ✓

- [x] `timeline_panel` — §7 timeline = view over (slide order + durations)
- [x] `stage_canvas` — §7 stage rendering the active slide
- [x] `properties_panel` — §7 live-bind text fields → slide index.json
- [x] `html_editor_surface` — §7 per-slide HTML editor + lint gate

## Phase 3 — Preview & Render Engine (RFC §8, §9)  [Batch B3] ✓

- [x] `slide_renderer_interface` — §9.1 interface; §9.2 HF impl; §9.3 swap path
- [x] `preview_engine` — §8 drive GSAP from playhead (real-time, not frame-accurate)
- [x] `audio_sync` — §8 + AGENTS.md external-`<audio>` pattern
- [x] `captions_karaoke` — AGENTS.md caption rules (GSAP direct color tweens)

## Phase 4 — Assets / Export / Determinism (RFC §10, §11, §13)  [Batch B4] ✓

- [x] `asset_library` — §5.1 SHA-256 content addressing
- [x] `export_pipeline` — §10 assemble + stamp + voiceover + captions → render
- [x] `visual_determinism` — §11 visual determinism + perceptual hashing
- [~] (spare) `transitions` — §5 root between-slide transitions — DEFERRED (out of committed 15+anchor scope)
