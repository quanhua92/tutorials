# Color-Mix & Opacity Modifiers (Tailwind CSS 4)

> **Companion demo:** [`color_mix_opacity.html`](./color_mix_opacity.html) — open in a browser.
> The page is the **rendered ground truth**: it applies `bg-cyan-500/40` and
> asserts via `getComputedStyle()` that the resolved alpha is ≈ 0.4.

---

## 0. TL;DR — the one idea

Tailwind v4 replaces v3's `rgba()` opacity hack with native CSS `color-mix()`.
The `/40` suffix on any color utility compiles to
`color-mix(in oklch, var(--color-*) 40%, transparent)` — a **perceptually
correct** fade over a **theme-swappable CSS variable**.

```mermaid
flowchart LR
  U["bg-cyan-500/40<br/>(utility in markup)"]
  T["@theme<br/>--color-cyan-500:<br/>oklch(0.715 0.143 215.221)"]
  M["color-mix(<br/>in oklch,<br/>var(--color-cyan-500) 40%,<br/>transparent)"]
  R["browser resolves<br/>→ rgb(...) / 0.4<br/>or oklch(... / 0.4)"]
  U -->|CDN / build compiles| M
  T -.->|var() substituted| M
  M -->|computed style| R

  style U fill:#eafaf1,stroke:#27ae60,stroke-width:2px
  style T fill:#fef9e7,stroke:#f1c40f
  style M fill:#eaf2f8,stroke:#2980b9,stroke-width:2px
  style R fill:#f4ecf7,stroke:#8e44ad
```

The pipeline: **utility** → (reads the `@theme` color variable) → **`color-mix()`
CSS** → browser resolves to a concrete color with the requested alpha. Swap the
variable (dark mode, brand swap) and every `/40` follows automatically — no
recompile, no rgba duplication.

---

## 1. How it works

Each Tailwind color token lives in `@theme` as an OKLCH value:

```css
@theme {
  --color-cyan-500: oklch(0.715 0.143 215.221);
}
```

When you write `bg-cyan-500/40`, Tailwind v4 emits:

```css
.bg-cyan-500\/40 {
  background-color: color-mix(in oklch, var(--color-cyan-500) 40%, transparent);
}
```

`color-mix(in oklch, A p%, B)` means: "in OKLCH color space, mix `p%` of `A`
with `(100−p)%` of `B`". With `B = transparent` (alpha 0), you get exactly the
opacity-modifier behaviour — but expressed as a **color blend** rather than a
raw alpha channel hack. This generalises:

| Want… | Write… | Mix partner |
|---|---|---|
| 40% opacity | `bg-cyan-500/40` | `transparent` |
| a mid-color between two theme colors | `color-mix(in oklch, var(--color-cyan-500), var(--color-blue-500) 50%)` | another color |
| a softer hover tint | `color-mix(in oklch, var(--color-brand), white 15%)` | `white` |

The `in oklch` part is the key — see [oklch_colors](./oklch_colors.html) for why
OKLCH produces perceptually even fades.

---

## 2. Opacity modifier syntax

The `/opacity` suffix attaches to **any** color utility — not just backgrounds.

| Pattern | Compiles to |
|---|---|
| `bg-cyan-500/40` | `color-mix(in oklch, var(--color-cyan-500) 40%, transparent)` |
| `text-red-500/70` | same shape, on `color` |
| `border-green-500/30` | same shape, on `border-color` |
| `ring-cyan-500/50` | same shape, on `--tw-ring-color` |
| `divide-slate-500/20` | same shape, on `border-color` of dividers |
| `from-blue-500/30` | same shape, on gradient stop color |
| `placeholder-slate-400/50` | same shape, on `::placeholder` |
| `accent-cyan-500/60` | same shape, on `accent-color` |

### Named steps (the default scale)

Tailwind ships `/0 /5 /10 /20 /25 /30 /40 /50 /60 /70 /75 /80 /90 /95 /100` as
named opacity steps. These are the "blessed" values — use them when you can.

### Arbitrary opacity — `/[0.33]` and `/[33%]`

When a named step doesn't fit, escape the scale with the arbitrary-value form:

```html
<!-- decimal form (0–1) -->
<div class="bg-cyan-500/[0.33]">33% opacity</div>

<!-- percentage form -->
<div class="bg-cyan-500/[33%]">also 33% opacity</div>
```

Both compile to `color-mix(in oklch, var(--color-cyan-500) 33%, transparent)`.
The decimal form is more common in the wild; the percentage form is useful when
copying values from design tools that emit `%`.

### CSS-variable-driven opacity

You can also drive opacity from a variable (advanced — rarely needed):

```html
<div class="bg-cyan-500/[var(--brand-opacity)]"></div>
```

---

## 3. color-mix() for blending two colors

`color-mix()` is a general CSS primitive — it's not limited to the
opacity-modifier pattern. Anywhere you'd hand-mix two colors (gradient stops,
generated shades, hover tints), prefer `color-mix()`:

```css
@utility brand-tint {
  /* 80% brand + 20% white = a softer hover background */
  background-color: color-mix(in oklch, var(--color-brand), white 20%);
}

@utility brand-deep {
  /* 80% brand + 20% black = a pressed/active state */
  background-color: color-mix(in oklch, var(--color-brand), black 20%);
}
```

For gradient interpolation, `in oklch` (or `in oklab`, `in srgb`, `in oklch
longer hue`) controls how colors interpolate across the stop range — see
[gradients_v4](./gradients_v4.html).

```css
.bg-brand-gradient {
  background: linear-gradient(
    in oklch,
    var(--color-cyan-500),
    color-mix(in oklch, var(--color-cyan-500), var(--color-blue-500) 50%),
    var(--color-blue-500)
  );
}
```

---

## 4. v3 `rgba()` vs v4 `color-mix()` — the migration

| Aspect | v3 `rgba()` | v4 `color-mix()` |
|---|---|---|
| Compiled output | `rgba(34, 211, 238, 0.4)` | `color-mix(in oklch, var(--color-cyan-500) 40%, transparent)` |
| Color space | sRGB (gamma-encoded) | OKLCH (perceptually uniform) |
| Theme-swap friendly | ❌ opacity baked into a literal — must regenerate per theme | ✅ reads `var(--color-*)` — swap the var, every `/40` follows |
| Fade appearance | sRGB fade — mid-tones desaturate toward gray | OKLCH fade — perceptually linear, stays vivid |
| Works on | bg/text/border via separate code paths | **every** color utility — one implementation |
| Browser floor | every browser ever | Chrome 111+, Safari 16.2+, Firefox 113+ (all 2023+) |
| Source of truth | the rgba literal in compiled CSS | the `@theme` variable (single source) |

### Why this is a real win, not cosmetics

1. **Theme swapping.** With v3, switching `--color-cyan-500` did nothing for
   `/40` utilities — they had the rgba baked in. With v4, every opacity variant
   reads the live variable. Dark mode, multi-brand, route-scoped themes ([multi_theme](./multi_theme.html)) all "just work".
2. **Perceptual correctness.** sRGB `rgba` fading desaturates mid-tones (a red
   at 50% opacity over white looks pinkish-gray, not "half as red"). OKLCH
   `color-mix` keeps the hue and chroma perceptually constant.
3. **Implementation unification.** v3 had three code paths (bg, text, border)
   each emitting its own rgba. v4 has one: emit `color-mix()` on whichever
   property the utility targets. Less code, fewer bugs.

---

## 5. Browser support

`color-mix()` shipped in:

- **Chrome / Edge / Brave / Opera:** 111+ (March 2023)
- **Safari / iOS Safari:** 16.2+ (December 2022)
- **Firefox:** 113+ (May 2023)
- **Samsung Internet:** 21+

Global usage is **~96%+** as of 2026 — safe to ship without a fallback for any
modern audience. The one holdout category is legacy enterprise IE/Edge-legacy,
which v4 doesn't target anyway.

`getComputedStyle()` returns the **resolved** value (e.g.
`oklch(0.715 0.143 215.221 / 0.4)` or `rgba(34, 211, 238, 0.4)` depending on
browser) — not the `color-mix()` source expression. The companion demo's
gold-check parses whichever form the browser returns.

Sources: [caniuse: css-color-mix](https://caniuse.com/css-color-mix),
[MDN: color-mix()](https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/color-mix).

---

## 6. Killer Gotchas

| Trap | Symptom | Fix |
|---|---|---|
| **`getComputedStyle` returns a resolved color, not `color-mix(...)`** | You assert the string contains `color-mix` — it never does | Parse the alpha from the resolved form (`rgba(...,a)`, `rgb(... / a)`, or `oklch(... / a)`) instead |
| **Alpha tolerance** | `bg-cyan-500/40` resolves to `0.398` not `0.4` (OKLCH rounding) | Assert with tolerance: `Math.abs(alpha - 0.4) < 0.06` |
| **`/0` and `/100` are special** | `bg-x/0` and `bg-x/100` may serialize differently (some browsers drop the alpha channel when it's 1) | Don't pin a gold-check on `/100`; use `/40` or another mid value |
| **Old browser = silent no-op** | In Safari 16.1 or older, `color-mix()` is invalid → property ignored → element appears with no background | v4's browser floor is the same as `color-mix()`'s; if you must support older, use `@supports (color: color-mix(in oklch, red, blue))` gates |
| **Custom color not registered as a variable** | `bg-mybrand-500/40` compiles but renders nothing | You must declare `--color-mybrand-500` in `@theme` — the `/40` modifier reads `var(--color-mybrand-500)`, and an undefined var means no color |
| **`in oklch` vs `in srgb` fade look different** | Same `/40` looks more vivid than your v3 rgba did | That's correct — OKLCH preserves chroma; sRGB desaturates. Don't "fix" it by switching interpolation space |
| **Blending with `white`/`black` ≠ opacity** | `color-mix(in oklch, red, white 60%)` is pink, not 40%-opaque red | For opacity use `transparent` as the second color, not `white` |
| **Gradient interpolation ≠ opacity interpolation** | `bg-linear-to-r from-cyan-500/40 to-blue-500/40` interpolates both color *and* alpha | If you want a flat-alpha gradient, set the alpha on the container, not on the stops |

---

### Cheat sheet

```html
<!-- Named opacity steps (/0 /5 /10 /20 /25 /30 /40 /50 /60 /70 /75 /80 /90 /95 /100) -->
<div class="bg-cyan-500/40 text-slate-100/80 border-cyan-500/30"></div>

<!-- Arbitrary opacity -->
<div class="bg-cyan-500/[0.33]"></div>   <!-- decimal 0–1 -->
<div class="bg-cyan-500/[33%]"></div>    <!-- percentage -->

<!-- Works on every color utility -->
<div class="ring-cyan-500/50 divide-slate-500/20 from-blue-500/30"></div>

<!-- Blending two theme colors (in @utility or <style type="text/tailwindcss">) -->
@utility brand-mid {
  background-color: color-mix(in oklch, var(--color-cyan-500), var(--color-blue-500) 50%);
}
```

```css
/* What v4 emits for bg-cyan-500/40 */
.bg-cyan-500\/40 {
  background-color: color-mix(in oklch, var(--color-cyan-500) 40%, transparent);
}
```

---

## 🔗 Cross-references

- **[oklch_colors](./oklch_colors.html)** — the OKLCH color space that makes
  `color-mix(in oklch, …)` perceptually correct. Read this first if the "why
  OKLCH not sRGB" question isn't clear.
- **[theme_inline](./theme_inline.html)** — `@theme inline` and cross-variable
  references: how `--color-cyan-500` itself can derive from another token, and
  why opacity modifiers still work through the indirection.
- **[gradients_v4](./gradients_v4.html)** — `bg-linear-*` / `bg-radial-*` /
  `bg-conic-*` and the `in oklch` / `in oklab` interpolation keywords that share
  the same color-mix machinery as opacity modifiers.
- **[multi_theme](./multi_theme.html)** — scoped themes and brand-per-route
  switching: the payoff of v4's variable-driven opacity (swap the var, every
  `/40` follows).
- **[arbitrary_values](./arbitrary_values.html)** — the `/[0.33]` and `/[33%]`
  arbitrary-opacity syntax is a special case of v4's arbitrary-value system.

---

## Sources

1. **Tailwind CSS v4 — Colors / Using opacity modifiers.**
   <https://tailwindcss.com/docs/colors> — official docs on the `/opacity`
   suffix and its compilation to `color-mix()`.
2. **MDN — `color-mix()`.**
   <https://developer.mozilla.org/en-US/docs/Web/CSS/color_value/color-mix> —
   the CSS primitive v4 builds on; syntax, interpolation color spaces, examples.
3. **Can I use — CSS `color-mix()` function.**
   <https://caniuse.com/css-color-mix> — browser support matrix (Chrome 111+,
   Safari 16.2+, Firefox 113+, ~96%+ global as of 2026).
4. **Tailwind CSS v4 upgrade guide.**
   <https://tailwindcss.com/docs/upgrade-guide> — notes the v3→v4 opacity
   migration (rgba → color-mix over OKLCH).
