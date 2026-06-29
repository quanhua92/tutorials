# TODO — Tailwind CSS 4 Deep Dive (38 bundles)

> Companion to `../frontend/tailwind/` — where frontend/tailwind/ (4 bundles)
> teaches v4 onboarding, this section goes advanced.

## Phase 1 — Container Queries (4)

- [x] 01 `container_basics` ⭐ **STYLE ANCHOR** — @container, container-type, why container queries
- [x] 02 `container_named` — Named containers (@container/sidebar), scoped queries
- [x] 03 `container_variants` — @sm:, @md:, @lg: variants, range queries (@max-md:)
- [x] 04 `container_patterns` — Component-driven responsive design patterns

## Phase 2 — The Variant Ecosystem (7)

- [x] 05 `group_peer` — group-*, peer-*: parent/sibling state-based styling
- [x] 06 `has_variant` — has-*, group-has-*, peer-has-* (:has() selector)
- [x] 07 `child_variants` — first:, last:, even:, odd:, only:, empty:, nth-
- [x] 08 `form_state` — required:, valid:, invalid:, autofill:, read-only:
- [x] 09 `a11y_variants` — motion-safe:, motion-reduce:, forced-colors:, contrast-more:
- [x] 10 `directional_media` — rtl:, ltr:, print:, open: (details/dialog)
- [x] 11 `data_attribute` — data-* variants, [data-state=open] patterns

## Phase 3 — Arbitrary Values & Dynamic Utilities (4)

- [x] 12 `arbitrary_values` — [17rem], [color:var(--x)], bg-[url(...)]
- [x] 13 `arbitrary_variants` — [&:nth-child(3)]:, [@supports(...)]:, [data-state]:
- [x] 14 `functional_utility` — @utility with --value(integer), --modifier(n)
- [x] 15 `arbitrary_properties` — [--scroll-offset:7px], [mask-type:luminance]

## Phase 4 — Color & Theming Internals (6)

- [x] 16 `oklch_colors` — oklch() color space, perceptual uniformity
- [x] 17 `color_mix_opacity` — color-mix(), opacity modifiers (/40)
- [ ] 18 `theme_inline` — @theme inline, cross-variable references
- [ ] 19 `multi_theme` — Scoped themes, brand-per-route, data-theme switching
- [ ] 20 `gradients_v4` — bg-linear-*, bg-radial-*, bg-conic-*, interpolation
- [ ] 21 `property_directive` — @property for typed CSS custom properties

## Phase 5 — Modern CSS Layout (4)

- [ ] 22 `css_nesting` — Native CSS nesting in v4 (& selector), nesting in @utility
- [ ] 23 `subgrid_layout` — grid-template-columns: subgrid, inheriting tracks
- [ ] 24 `gap_spacing` — The spacing scale (--spacing), gap/padding/margin derivation
- [ ] 25 `aspect_ratio_object` — aspect-ratio, object-fit/position, sizing

## Phase 6 — Animations & Motion (7)

- [ ] 26 `keyframes_animate` — @keyframes + --animate-* namespace
- [ ] 27 `transitions_timing` — transition-*, duration-*, ease-*, delay-*
- [ ] 28 `transforms_3d` — rotate-*, scale-*, skew-*, translate-*, 3D, perspective
- [ ] 29 `starting_style` — @starting-style for enter/exit transitions
- [ ] 30 `filters_masks` — backdrop-blur-*, filter-*, mask-*, mix-blend-*
- [ ] 31 `scroll_driven` — animation-timeline: scroll(), view()
- [ ] 32 `view_transitions_tw` — View Transitions API + Tailwind patterns

## Phase 7 — Build, Directives & Production (6)

- [ ] 33 `source_detection` — @source, auto-detection, globs, monorepo
- [ ] 34 `plugins_ecosystem` — @plugin (typography/forms), @reference, @variant
- [ ] 35 `preflight_reset` — What Preflight resets, overrides, @layer base
- [ ] 36 `build_tooling` — CLI, @tailwindcss/vite, @tailwindcss/postcss, Lightning CSS
- [ ] 37 `v3_migration` — Breaking changes, upgrade tool, manual migration
- [ ] 38 `production_optimization` — Content detection, tree-shaking, pinned builds
