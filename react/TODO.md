# TODO — React Deep Dive (36 bundles)

> Companion to `../frontend/` — where `frontend/react/` (4 bundles) teaches
> basics, this section goes deep: hooks, patterns, concurrent React,
> performance, animations, TanStack Router.

## Phase 1 — Hooks Mastery (6)

- [x] 01 `use_reducer` ⭐ **STYLE ANCHOR** — useReducer: dispatch table, state machines
- [x] 02 `use_ref_dom` — useRef: mutable refs, DOM access, timers
- [x] 03 `use_memo_callback` — useMemo & useCallback: memoization, referential equality
- [x] 04 `use_context` — Context API: Provider/Consumer, context splits
- [x] 05 `custom_hooks` — Custom hooks: useDebounce, useLocalStorage, useFetch
- [x] 06 `use_layout_effect` — useLayoutEffect vs useEffect: paint timing

## Phase 2 — Component Patterns (6)

- [x] 07 `compound_components` — Compound pattern: implicit state via context
- [x] 08 `render_props` — Render props & function-as-child
- [x] 09 `headless_ui` — Headless UI: state reducer + prop getters
- [x] 10 `controlled_uncontrolled` — Controlled vs uncontrolled, key-based reset
- [x] 11 `error_boundaries` — Error boundaries: catching render errors
- [x] 12 `forward_ref` — forwardRef + useImperativeHandle

## Phase 3 — Concurrent React & React 19 (5)

- [x] 13 `suspense_patterns` — Suspense: declarative loading, throw-promise
- [x] 14 `use_transition` — useTransition: urgent vs non-urgent updates
- [x] 15 `use_deferred_value` — useDeferredValue: deferring expensive renders
- [x] 16 `use_external_store` — useSyncExternalStore: external subscriptions
- [x] 17 `react19_actions` — useActionState, useFormStatus, useOptimistic

## Phase 4 — Performance (4)

- [x] 18 `react_memo` — React.memo: preventing re-renders
- [x] 19 `re_render_profiling` — Profiling: flamegraph, commit reasons
- [x] 20 `virtual_lists` — Virtualized rendering: windowing
- [x] 21 `lazy_suspense` — Code splitting: React.lazy, dynamic import

## Phase 5 — Animations (5)

- [x] 22 `css_animations` — CSS transitions in React: FLIP technique
- [x] 23 `view_transitions` — View Transitions API: crossfade, shared elements
- [x] 24 `framer_motion_core` — Framer Motion: motion components, gestures
- [x] 25 `spring_physics` — Spring physics: damping, stiffness, natural motion
- [x] 26 `animation_orchestration` — Variants, stagger, AnimatePresence exits

## Phase 6 — TanStack Router Deep Dive (10)

- [x] 27 `router_fundamentals` — Route tree, history, matching — the mental model
- [x] 28 `router_route_tree` — Compilation, linearization, matching algorithm
- [x] 29 `router_type_inference` — How definitions propagate types
- [x] 30 `router_search_validation` — Zod/Valibot schemas, defaults
- [x] 31 `router_loader_lifecycle` — beforeLoad → loader → component, caching
- [x] 32 `router_navigation_preload` — Intent-based preloading, dedup, prefetch
- [x] 33 `router_nested_context` — Nested routes, Outlet, context flow
- [ ] 34 `router_code_splitting` — createLazy, route-level splitting, Suspense
- [ ] 35 `router_advanced_patterns` — Auth routes, navigation blocking, masking
- [ ] 36 `router_devtools` — DevTools: route tree viz, inspector, profiling

## Cross-link Map

```
frontend/react/ (basics)                react/ (deep dive)
───────────────────────────             ──────────────────────────
react_via_cdn           ─────────────→  (all bundles use this CDN pattern)
react_state_hooks       ──┬─────────→   use_reducer, use_ref_dom, react19_actions
                         └─────────→   use_transition, use_deferred_value
react_components_props  ─────────────→  use_context, compound_components
react_effects_lists     ──┬─────────→   use_layout_effect, suspense_patterns
                         └─────────→   error_boundaries

frontend/tanstack-start/ (concepts)    react/ Phase 6 (deep dive)
───────────────────────────────────    ──────────────────────────
router_type_safety      ─────────────→  router_type_inference
file_based_routing      ─────────────→  router_route_tree
path_search_params      ─────────────→  router_search_validation
loaders_data            ─────────────→  router_loader_lifecycle
navigation_links        ─────────────→  router_navigation_preload
nested_outlet_context   ─────────────→  router_nested_context
```
