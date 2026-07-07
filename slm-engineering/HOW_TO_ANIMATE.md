# HOW_TO_ANIMATE — Building Self-Contained Concept Animations (SLM Engineering)

> A recipe for turning a `.md` concept + a `.py` reference into a single,
> interactive, **self-contained `.html` file** (embedded CSS + JS, zero deps,
> opens by double-click) that makes the idea *click*.
>
> The full worked recipe lives in the sibling section:
> [`../llm/HOW_TO_ANIMATE.md`](../llm/HOW_TO_ANIMATE.md). Read it once; this file
> adds only the **`slm-engineering/`-specific conventions** and the exact header
> template to copy.

---

## 0. The hard rules (unchanged from `../llm/`)

1. **One file, zero deps.** No npm, no CDN, no `fetch`. Everything inline:
   `<style>…</style>` and `<script>…</script>`. Works offline by double-click.
2. **The `.py` is ground truth.** Numbers shown must either (a) be copied verbatim
   from the `.py` output, or (b) be recomputed in JS with the *identical* formula
   and spot-checked against the `.py`. Never invent numbers.
3. **Mirror the `.md` sections.** Each animation panel maps to a `.md` section.
4. **No build step.** Plain ES5-ish JS. Avoid modules/imports so it runs from `file://`.

---

## 1. Section accent color

`slm-engineering/` uses **teal `#1abc9c`** as its accent (distinct from `../llm/`'s
green `#27ae60`). Use it for: sliders (`accent-color`), the active/selected thing,
the `.val` numbers, and the `[check: OK]` badge.

```css
:root{
  --bg:#0d1117; --panel:#161b22; --ink:#e6edf3; --muted:#8b949e;
  --grid:#21262d; --accent:#1abc9c;   /* teal — the section identity */
  --green:#27ae60; --red:#c0392b; --orange:#e67e22; --blue:#2980b9;
}
```

Keep the rest of the palette identical to `../llm/` so the two sections read as
siblings (red = watch-out, orange = selected, blue = long-range, muted = axes).

---

## 2. The header template (copy this VERBATIM, swap only the names)

This is the exact structure every `slm-engineering/*.html` must use — it mirrors
[`../llm/rope.html`](../llm/rope.html). **`.md`/`.py` badge links are FULL GitHub
URLs; sibling `.html` links are RELATIVE; the back-button is `../index.html`.**

```html
<!-- 1. back to the repo-root tutorials dashboard -->
<a href="../index.html" style="display:inline-block;color:#8b949e;font-size:.8rem;
   text-decoration:none;border:1px solid #30363d;background:#161b22;border-radius:6px;
   padding:3px 11px;margin:0 0 .9rem">← all tutorials</a>

<h1>SCALING LAWS
  <!-- 2. badges: .md (teal/green) + .py (orange), FULL GitHub URLs -->
  <a class="badge md" title="Full guide"
     href="https://github.com/quanhua92/tutorials/blob/main/slm-engineering/SCALING_LAWS.md">📖 SCALING_LAWS.md</a>
  <a class="badge py" title="Ground-truth source code"
     href="https://github.com/quanhua92/tutorials/blob/main/slm-engineering/scaling_laws.py">📄 scaling_laws.py</a>
</h1>
<!-- 3. guide-callout div (right after the header) -->
<div class="guide-callout">📖 <a
   href="https://github.com/quanhua92/tutorials/blob/main/slm-engineering/SCALING_LAWS.md">Read the full guide</a>
   — architecture diagrams, decision tables, killer gotchas, cheat sheet.
   This page is the interactive companion.</div>

<!-- 4. one-line subtitle with a RELATIVE sibling link -->
<div class="sub"><b>One-liner here.</b> Every number is recomputed in JS from the
   <i>identical</i> formula in <code>scaling_laws.py</code>.
   &nbsp;|&nbsp; <a href="./vocab_rationalization.html">compare with vocab rationalization →</a></div>
```

### The badge + callout CSS (add once per file, right after the `:root`)

```css
a{color:#58a6ff}
.badge{display:inline-block;border-radius:5px;padding:2px 9px;font-size:.72rem;
  font-weight:600;margin-left:.6rem;text-decoration:none;border:1px solid}
.badge.md{background:#0f2e29;color:var(--accent);border-color:var(--accent)}
.badge.py{background:#3a2a14;color:var(--orange);border-color:var(--orange)}
.guide-callout{margin:10px 0 0;padding:10px 14px;border-radius:8px;
  background:rgba(26,188,156,.06);border:1px solid rgba(26,188,156,.2);
  font-size:.82rem;color:var(--muted);line-height:1.5}
.guide-callout a{color:var(--accent);font-weight:600;text-decoration:none}
.guide-callout a:hover{text-decoration:underline}
```

> The `.badge.md` uses the teal accent (section identity); `.badge.py` uses orange
> universally. The `.guide-callout` uses teal at low alpha.

---

## 3. Tables must be overflow-wrapped

Any `<table>` (including JS-populated ones) goes inside a scroll wrapper or the
page overflows on narrow screens:

```html
<div style="overflow-x:auto;min-width:0">
  <table class="heat">…</table>
</div>
```

The `min-width:0` is critical — without it flex children won't shrink and the
scroll never engages.

---

## 4. The gold-check badge (mandatory footer)

Recompute one concrete value the `.py` prints, compare, show a badge:

```html
<span class="badge" id="check">check: …</span>
```
```js
const ok = (Math.abs(jsValue - PY_GOLD_VALUE) < 1e-4);
document.getElementById('check').textContent =
  ok ? 'check: OK — JS matches scaling_laws.py Section C'
     : 'check: FAIL — mismatch!';
document.getElementById('check').style.color = ok ? 'var(--accent)' : 'var(--red)';
```

---

## 5. Verification (mandatory before reporting)

1. **Syntax:** extract the `<script>`, `node --check` it (must pass).
2. **Runtime:** run the DOM-mock smoke test (see
   [`SUBAGENTS_RESEARCH_GUIDE.md`](./SUBAGENTS_RESEARCH_GUIDE.md) §5) —
   `node --check` is syntax-only and misses runtime crashes.
3. **Gold:** the `[check: OK]` badge is teal, not red.
4. **Header:** badges are full GitHub URLs, sibling link is relative, back-button
   is `../index.html`.

Study [`../llm/rope.html`](../llm/rope.html) (rotating-vectors / canvas pattern)
and [`../llm/zero.html`](../llm/zero.html) (bar-chart / memory pattern) for the
two canonical visual archetypes.
