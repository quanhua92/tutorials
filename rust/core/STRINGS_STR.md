# STRINGS_STR — `String` (owned) vs `&str` (borrowed), and Why UTF-8 Changes Everything

> **One-line goal:** `String` is the **owned, growable, heap-allocated** text (a
> `{ptr, len, capacity}` handle over a UTF-8 buffer); `&str` is a **borrowed,
> read-only view** (`{ptr, len}` fat pointer) into a `String`, a slice, or a
> `'static` literal. Rust strings are **always valid UTF-8**, so `len()` counts
> **bytes** (not characters), and indexing `s[i]` is a **compile error**.
>
> **Run:** `just run strings_str` (== `cargo run --bin strings_str`)
> **Member:** `core` (stdlib-only — no `[dependencies]`).
> **Prerequisites:** 🔗 [OWNERSHIP](./OWNERSHIP.md) — `String` owns its heap
> buffer; a move transfers that ownership. Read that first.
> **Ground truth:** [`strings_str.rs`](./strings_str.rs); captured stdout:
> [`strings_str_output.txt`](./strings_str_output.txt).

---

## Why this exists (lineage)

A newcomer to Rust asks: *"If there is a `String`, why is every literal a
`&str`, and why can't I write `s[0]`?"* The answer is that Rust has **two** string
types by design, split along the **ownership** fault line introduced in
[OWNERSHIP](./OWNERSHIP.md):

| Type | Owner? | Where the bytes live | Growable? | Cost to pass |
|---|---|---|---|---|
| **`String`** | **yes** — it owns a heap buffer | heap (`Vec<u8>` of UTF-8) | **yes** (`push`, `push_str`, `+`) | move (or `&String`) |
| **`&str`** | **no** — a *borrow* | anywhere (heap, *or the read-only binary* for a literal) | no (read-only) | a cheap fat-pointer copy |

`String` is to `&str` exactly what `Vec<T>` is to `&[T]`: the owned, growable
container versus a borrowed window over contiguous elements. The Book defines it
precisely: "`String`... is a growable, mutable, owned, UTF-8 encoded string type"
while the primitive `str` "is usually seen in its borrowed form, `&str`"
([Book ch8.2][book-strings]).

```mermaid
graph TD
    Lit["\"hello\" literal<br/>baked into the read-only binary"]
    Lit -->|type &'static str| Str["&str = {ptr, len}<br/>a BORROWED view (fat pointer)"]
    Owned["String = {ptr, len, capacity}<br/>owns a heap buffer"]
    Owned -->|"push / push_str / +"| Grow["buffer GROWS on the heap"]
    Owned -.->|"as_str() or &s<br/>(Deref coercion)"| Str
    Str -->|"reads a String's heap bytes<br/>WITHOUT owning them"| Owned
    Str -->|"or reads the binary's bytes"| Lit
    Both["BOTH are ALWAYS valid UTF-8"]:::core
    Str --> Both
    Owned --> Both
    Both --> NoIndex["indexing s[i] is a COMPILE ERROR (E0277)<br/>len() counts BYTES, not chars"]
    classDef core fill:#eafaf1,stroke:#27ae60,stroke-width:3px;
    style Owned fill:#eaf2f8,stroke:#2980b9,stroke-width:2px
    style Str fill:#fef9e7,stroke:#f1c40f,stroke-width:2px
    style NoIndex fill:#fdedec,stroke:#c0392b,stroke-width:2px
```

Everything in this guide is a consequence of one fact — **a Rust string is a
sequence of UTF-8 bytes, and UTF-8 is variable-width** — plus the ownership rule
that a borrow may never own.

---

## Section A — `String`: owned, growable, heap-allocated text

```rust
let s = String::from("hello");   // s owns a heap buffer of 5 UTF-8 bytes
```

> **From strings_str.rs Section A:**
> ```
> ======================================================================
> SECTION A — String: owned, growable, heap-allocated text
> ======================================================================
>   let s = String::from("hello");
>     s            = "hello"
>     s.len()      = 5   (BYTES currently in the buffer)
>     s.capacity() = 5   (buffer size; always >= len)
>     handle size  = size_of::<String>() = 24 bytes  ({ptr, len, capacity})
>   growable: push_str("acean"); push('!') -> "rustacean!"
>   big = ...repeat(1000) -> 10000 bytes of heap text; handle still 24 bytes
> [check] String handle = ptr(8)+len(8)+cap(8) = 24 bytes on a 64-bit target: OK
> [check] len() counts BYTES: "hello".len() == 5: OK
> [check] capacity >= len is always true (the documented invariant): OK
> [check] String is growable: "rust" + "acean" + '!' == "rustacean!": OK
> [check] handle size is constant: a 10000-byte String still has a 24-byte handle: OK
> ```

**What.** A `String` is a 3-word **handle on the stack** — `{ ptr, len,
capacity }` = **24 bytes** on a 64-bit target — pointing at a **heap** buffer of
UTF-8 bytes. The first check proves the handle size with `size_of::<String>()`;
the last check proves the handle size is **constant** even for a 10 000-byte
string.

**Why (internals).**
- **It is literally a `Vec<u8>` with a UTF-8 invariant.** The Book: "`String` is
  actually implemented as a wrapper around a vector of bytes with some extra
  guarantees, restrictions, and capabilities" ([Book ch8.2][book-strings]).
  The std docs agree: "A `String` is made up of three components: a pointer to
  some bytes, a length, and a capacity... This buffer is always stored on the
  heap" ([`std::string::String` — Representation][std-string]).
- **`len()` is the byte count, not the character count.** The second check pins
  `"hello".len() == 5` — but only because each of those letters is one byte in
  UTF-8. Section C shows this assumption collapses the moment an accent or emoji
  appears.
- **`capacity >= len` is an invariant.** "the length will always be less than or
  equal to the capacity" ([`std::string::String` — Representation][std-string]).
  `capacity()` is the buffer size (room to grow without reallocating); `len()` is
  how many bytes are actually used.
- **Growable + mutable, unlike a literal.** `push_str` appends a `&str`; `push`
  appends a single `char`. The `+` operator and `format!` also build strings
  (Section E). None of this is possible on a `&str` literal, which lives in the
  read-only binary.
- **Non-`Copy`.** Because the handle *owns* the heap buffer, copying a `String`
  would create two owners of one buffer (a double-free). So `String` is `Clone`
  but not `Copy` — assigning or passing it **moves** it (see [OWNERSHIP](./OWNERSHIP.md)).
  That is precisely why the *owned* type must be distinguished from the *borrowed*
  one.

🔗 [OWNERSHIP](./OWNERSHIP.md) — `String` is the canonical owned type; a move
copies the 24-byte handle and poisons the source. 🔗 [VEC_COLLECTIONS](./VEC_COLLECTIONS.md)
— `String` is a `Vec<u8>` that enforces UTF-8; the two share `push`/`capacity`/
`with_capacity`.

---

## Section B — `&str`: a borrowed, read-only view (`{ptr, len}` fat pointer)

```rust
let lit   = "literal";                 // &'static str — baked into the binary
let view: &str = some_string.as_str(); // a &str borrowed from a String
let slice = &lit[0..3];                // a sub-&str window
```

> **From strings_str.rs Section B:**
> ```
> ======================================================================
> SECTION B — &str: a BORROWED, read-only view ({ptr, len} fat pointer)
> ======================================================================
>   let lit = "literal";   // type_name::<&str>() = &str
>                        // (type_name erases lifetimes; the literal IS &'static str)
>   let view: &str = String::from("owned heap text").as_str();
>     view = "owned heap text", view.len() = 15
>   let slice = &lit[0..3];   -> "lit"   (a sub-&str window)
>   &str handle = size_of::<&str>() = 16 bytes  ({ptr, len}; ptr 8 + len 8)
> [check] &str fat pointer = ptr(8)+len(8) = 16 bytes on a 64-bit target: OK
> [check] a &str can borrow a String's contents without owning them: OK
> [check] a &'static str literal can be returned from a fn with no input borrows: OK
> ```

**What.** A `&str` is a **2-word fat pointer** — `{ ptr, len }` = **16 bytes**
(proven by the first check) — that refers to UTF-8 bytes owned by someone else:
either a `String`'s heap buffer, a sub-window of another `&str`, or the bytes of a
literal burned into the binary.

**Why (internals).**
- **A `&str` is a slice.** The Book (Figure 4-7): a string slice "would be a slice
  that contains a pointer to the byte at index 6 of `s` with a length value of 5"
  ([Book ch4.3][book-slices]). It stores a start pointer **and a length** — no
  capacity, because it does not own memory it could grow into.
- **A literal IS a `&str` into the binary.** "The type of `s` here is `&str`: It's
  a slice pointing to that specific point of the binary. This is also why string
  literals are immutable; `&str` is an immutable reference" ([Book ch4.3][book-slices]).
  Its lifetime is `'static` — the literal is baked into the program binary at
  compile time, so it is valid for the entire run. The third check demonstrates
  this: `fn static_literal() -> &'static str` returns a literal with **no input
  borrows**, which is only legal because the literal outlives everything.
- **`type_name` erases lifetimes.** `type_name::<&str>()` prints `&str`, and
  `type_name::<&'static str>()` prints *the same* `&str` — the function does not
  render lifetimes. So the `'static`-ness of a literal is a *lifetime* fact, not
  something `type_name` can show; that is why the check proves it via a function
  signature instead.
- **Borrowing, never owning.** `view` reads a `String`'s bytes through `as_str()`
  but the `String` retains ownership (the second check). This is the doorway to
  [BORROWING](./BORROWING.md): a `&str` is a permission to read without owning.

> **Signature idiom: take `&str`, not `&String`.** Clippy's `ptr_arg` lint flags
> `&String` parameters because `&str` is strictly more general: a single `&str`
> parameter accepts a `&String`, a `&str` slice, **and** a literal, all via deref
> coercion ([Book ch4.3 — "String Slices as Parameters"][book-slices]). Every
> later bundle follows this.

🔗 [LIFETIMES](./LIFETIMES.md) — the `'static` lifetime is the borrow checker's
"lives for the whole program" label, and a literal's `'static` is its most common
appearance.

---

## Section C — UTF-8: `len()` is BYTES; `.chars()` is Unicode scalar values

```rust
let word = "résumé";   // len() == 8 bytes, but 6 scalar values
let wave = "👋";        // len() == 4 bytes, but 1 scalar value
```

> **From strings_str.rs Section C:**
> ```
> ======================================================================
> SECTION C — UTF-8: len() is BYTES; .chars() is Unicode scalar values
> ======================================================================
>   let word = "résumé";
>     word.len()           = 8   (BYTES; each 'é' is 2 bytes)
>     word.chars().count() = 6   (Unicode scalar values)
>   let wave = "👋";
>     wave.len()           = 4   (BYTES; the emoji is 4 bytes)
>     wave.chars().count() = 1   (one scalar value)
>     wave.bytes() = [240, 159, 145, 139]   (4 bytes that decode to ONE scalar value)
> [check] "résumé": len() == 8 bytes, chars().count() == 6: OK
> [check] "👋": len() == 4 bytes, chars().count() == 1: OK
> [check] .bytes() yields exactly len() bytes (both count raw UTF-8 bytes): OK
> ```

**What.** `"résumé"` has `len() == 8` but `chars().count() == 6`; `"👋"` has
`len() == 4` but `chars().count() == 1`. The collected `wave.bytes()` —
`[240, 159, 145, 139]` — is the raw proof: **four bytes decode into a single
scalar value**.

**Why (internals).**
- **UTF-8 is variable-width.** ASCII takes 1 byte; accented Latin (`é`, U+00E9)
  takes 2; many symbols/CJK take 3; emoji above U+FFFF (like `👋`, U+1F44B) take
  4. Because `String`/`str` are defined as "a sequence of UTF-8 bytes", `len()`
  reports bytes — it would be **O(n)** to count characters, and indexing would
  have to pay that cost (see Section F).
- **Three valid ways to view a string.** The Book distinguishes: **bytes** (the
  raw `u8`s), **Unicode scalar values** (Rust's `char`), and **grapheme clusters**
  (what a human calls a "letter"). `len()`/`bytes()` give the first; `chars()`
  gives the second; **grapheme clusters are NOT in the standard library**
  ([Book ch8.2 — "Bytes, Scalar Values, and Grapheme Clusters"][book-strings]).
- **`char` is a 4-byte scalar value, not a byte.** This is why a `Vec<char>` of
  the same text is *larger* than the UTF-8 string for ASCII (20 bytes for 5 ASCII
  chars vs 5 bytes as a `&str`). UTF-8's whole point is to be compact for ASCII
  while still encoding all of Unicode.

> **The `é` in "résumé" is 2 bytes (0xC3 0xA9),** so two of them add 2 extra
> bytes over the 6 visible letters → `len() == 8`. Internalize this: *visible
> length and `len()` diverge as soon as non-ASCII appears.*

🔗 [FORMATTING](./FORMATTING.md) — `Display`/`Debug` render strings; `{:?}` quotes
them, which is why every string in the output above appears in quotes.

---

## Section D — conversions: `&str` → `String`, and `String` → `&str`

```rust
// &str -> String  (three equivalent spellings, each a NEW owned heap copy)
let a = "hi".to_string();      // ToString  (any Display type)
let b = String::from("hi");    // From<&str> for String
let c = "hi".to_owned();       // ToOwned   (borrowed -> owned counterpart)

// String -> &str  (free; no copy)
let v = owned.as_str();        // explicit
let v: &str = &owned;          // deref coercion: &String -> &str
```

> **From strings_str.rs Section D:**
> ```
> ======================================================================
> SECTION D — conversions: &str -> String, and String -> &str
> ======================================================================
>   from &str "hello" -> String via three ways:
>     "hello".to_string()   = "hello"   (ToString trait)
>     String::from("hello") = "hello"   (From trait)
>     "hello".to_owned()    = "hello"   (ToOwned trait)
>   String -> &str:  owned.as_str() == "hi";  &owned (deref) == "hi"
> [check] to_string / String::from / to_owned all yield the same String: OK
> [check] String::from("hi").as_str() == "hi" (round-trip equality): OK
> [check] deref coercion: &String coerces to &str for free (same value): OK
> ```

**What.** The first check proves `to_string`, `String::from`, and `to_owned`
produce the **same** owned `String` from a `&str`. The next two prove the reverse
direction — `as_str()` and `&owned` — both yield the borrowed `&str` for free.

**Why (internals).**
- **`&str` → `String` allocates.** All three spellings copy the bytes into a fresh
  heap buffer (an owned value must own its memory). The Book: "`String::from` and
  `to_string` do the same thing, so which one you choose is a matter of style and
  readability" ([Book ch8.2][book-strings]). `to_owned` is the trait-general form
  (`&str`→`String`, `&[T]`→`Vec<T>`); `to_string` works on anything `Display`.
- **`String` → `&str` is free, via `Deref`.** `String` implements
  `Deref<Target = str>`, so it *inherits every `str` method* and a `&String`
  *coerces* to `&str` at any coercion site. The std docs: "you can pass a `String`
  to a function which takes a `&str` by using an ampersand (`&`)" and "this
  conversion is very inexpensive" ([`std::string::String` — Deref][std-string]).
- **Asymmetry is the point.** Going *up* to `String` costs a heap allocation
  (you're materializing an owner); going *down* to `&str` costs nothing (you're
  just dropping the capacity word and borrowing). This is why idiomatic APIs take
  `&str` and return `String` only when they must produce new owned text.

🔗 [COPY_CLONE](./COPY_CLONE.md) — `to_owned`/`clone` are the explicit, possibly
deep, copy operations; `String` is `Clone` but **not** `Copy` (it owns the heap).

---

## Section E — building: `with_capacity` avoids realloc; `format!` concatenates

```rust
let mut pre = String::with_capacity(25);   // one allocation, no realloc in the loop
let cat = format!("{}-{}-{}", s1, s2, s3); // borrows all inputs; never moves them
```

> **From strings_str.rs Section E:**
> ```
> ======================================================================
> SECTION E — building: with_capacity avoids realloc; format! concatenates
> ======================================================================
>   naive String::new() + 5x push_str("hello") capacity trace: [0, 8, 16, 16, 32, 32]
>   String::with_capacity(25): cap stays 25 across 5x push_str("hello")
>     result = "hellohellohellohellohello"
>   format!("{}-{}-{}", s1, s2, s3) = "tic-tac-toe"
>     (s1, s2, s3 still usable after: "tic", "tac", "toe")
> [check] with_capacity(25) holds "hello"x5 (25 bytes) with no realloc: OK
> [check] format! concatenation: "tic"-"tac"-"toe" == "tic-tac-toe": OK
> [check] format! borrows its arguments: all inputs stay usable: OK
> ```

**What.** The capacity trace `[0, 8, 16, 16, 32, 32]` shows a naive `String::new()`
reallocating **four times** as it grows; `String::with_capacity(25)` then holds
all 25 bytes with **zero** reallocations (capacity stays `25`). `format!`
concatenates three `String`s into `"tic-tac-toe"` while leaving all three inputs
usable (it borrowed them).

**Why (internals).**
- **Growth doubles (amortized O(1) `push`).** The `0 → 8 → 16 → 32` trace is the
  *exact* sequence printed in the std docs for this example ([`std::string::String`
  — Representation][std-string]). Each realloc copies the existing bytes to a
  bigger buffer; doubling keeps the amortized cost of one `push` constant.
- **`with_capacity` is the perf knob.** If you know the final size, pre-allocate.
  The std docs: "This is useful when you may be appending a bunch of data to the
  `String`, reducing the number of reallocations it needs to do"
  ([`with_capacity`][std-string]).
- **`format!` borrows; `+` consumes.** The `+` operator has signature
  `fn add(self, s: &str) -> String` — it **moves** the left operand (`s1 + &s2`
  kills `s1`) but borrows the right ([Book ch8.2][book-strings]). `format!` is the
  readable alternative for ≥2 strings, and crucially **borrows every input** (the
  third check), which is why `s1`/`s2`/`s3` survive. This is `format!`'s main
  advantage over chaining `+`.

> **Don't reflexively build strings with `+`.** `format!` is clearer for several
> pieces and never surprises you with a moved operand. Reach for `push_str` in a
> loop, and `with_capacity` when the size is known.

---

## Section F — indexing `s[0]` is FORBIDDEN; use `.chars().nth()` / byte slices

```rust
let s = String::from("hi");
// s[0]            // <-- DOES NOT COMPILE  (E0277)
let c = s.chars().next();        // Some('h')  -- the first scalar value
let h: &str = &s[0..1];          // "h"        -- a byte-range slice (must hit a char boundary)
```

> **From strings_str.rs Section F:**
> ```
> ======================================================================
> SECTION F — indexing s[0] is FORBIDDEN; use .chars().nth() / byte slices
> ======================================================================
>   let s = String::from("hi");
>   // s[0]   <-- DOES NOT COMPILE (E0277; see STRINGS_STR.md)
>   s.chars().next() = Some('h')   (== .chars().nth(0); clippy prefers .next())
>   "rust".chars().nth(2) = Some('s')   (general form; O(i) walk from the front)
>   &s[0..1] = "h"   (byte-range slice; byte 1 is a char boundary here)
>   "👋".chars().next() = Some('👋')   (bytes 0..4 are one 4-byte char)
> [check] chars().next() of "hi" == Some('h'): OK
> [check] chars().nth(2) of "rust" == Some('s'): OK
> [check] byte-range slice &s[0..1] == "h" (byte 1 is a char boundary): OK
> ```

**What.** `s[0]` is rejected by the compiler; `.chars().next()` returns
`Some('h')`; `&s[0..1]` yields the slice `"h"` because byte `1` is a valid char
boundary for ASCII `"hi"`.

**The compile error (cannot live in the runnable `.rs` — it would not build):**

```console
error[E0277]: the type `str` cannot be indexed by `{integer}`
   --> src/main.rs:3:16
    |
  3 |     let _h = s[0];
    |                ^ string indices are ranges of `usize`
    |
    = help: the trait `SliceIndex<str>` is not implemented for `{integer}`
    = note: you can use `.chars().nth()` or `.bytes().nth()`
            for more information, see chapter 8 in The Book: <https://doc.rust-lang.org/book/ch08-02-strings.html#indexing-into-strings>
    = note: required for `String` to implement `Index<{integer}>`

For more information about this error, try `rustc --explain E0277`.
```

*(Captured verbatim from `rustc` 1.96.0 for `let s = String::from("hi"); let _h = s[0];`.
Note the error names `str` — that is where `SliceIndex` is checked — with a note
that this is what blocks `String`'s `Index` impl.)*

**Why (internals).** The Book gives **three** reasons indexing is forbidden
([Book ch8.2 — "Indexing into Strings"][book-strings]):
1. **Ambiguity of the return type.** Should `s[0]` be a `u8` byte, a `char`, a
   grapheme cluster, or a `&str`? For `"hi"`, byte `0` is `104` — not `'h'` —
   which is "likely not what a user would want."
2. **A byte index can split a character.** `👋` is 4 bytes; index `0..1` would
   land *inside* the scalar value, producing invalid UTF-8. Rust refuses to return
   malformed data, so it forbids the operation entirely.
3. **Indexing must be O(1).** Counting to the *i*-th character requires walking
   from the front (UTF-8 is variable-width), which is O(n). Rust won't offer an
   "indexing" operation that secretly isn't constant time.

**The three legal alternatives:**
- **`.chars().nth(i)` / `.chars().next()`** — the *i*-th Unicode scalar value,
  but it is **O(i)** (a front walk), and clippy's `iter_nth_zero` lint steers you
  to `.next()` for index `0` ([`clippy::iter_nth_zero`][clippy-iter-nth-zero]).
- **`&s[a..b]`** — a byte-range slice returning a `&str`, **constant time**, but
  it **panics at runtime** if `a`/`b` are not char boundaries: `byte index 1 is
  not a char boundary; it is inside 'З'` ([Book ch8.2][book-strings]). Use
  `s.get(a..b)` for a non-panicking `Option<&str>`.
- **`.bytes()`** — iterate raw `u8`s when you genuinely want bytes (Section C).

> **Slicing a multi-byte char panics, it does not compile-fail.** `&"👋"[0..1]`
> compiles fine but aborts at runtime — the boundary check is dynamic. This is the
> one place Rust string handling trades a compile guarantee for a runtime panic.

---

## Pitfalls (the expert payoff)

| Trap | Symptom | Fix / why |
|---|---|---|
| **Indexing `s[i]`** | `error[E0277]: the type \`str\` cannot be indexed by \`{integer}\`` | Indexing is forbidden. Use `s.chars().nth(i)` (O(i)) or a byte-range slice `&s[a..b]`. |
| **`len()` ≠ character count** | `"résumé".len()` is `8`, not `6` | `len()` counts **bytes**. For characters use `.chars().count()`; for graphemes use the `unicode-segmentation` crate (not in std). |
| **Slicing mid-char panics** | `thread 'main' panicked at 'byte index N is not a char boundary'` | Byte-range slices must land on char boundaries. Use `.get(a..b)` for an `Option<&str>` instead of panicking `[a..b]`. |
| **`to_string()` "for free"?** | Hidden allocation in a hot loop | `&str → String` always allocates a heap buffer. If you only need to *read*, pass `&str`; only call `to_string`/`to_owned` when you need an owner. |
| **Confusing `String` and `&str` ownership** | A `String` moves where a `&str` was expected, or vice-versa | `String` owns; `&str` borrows. Take `&str` in signatures (deref coercion makes `&String` work for free); return `String` only when you produce new owned text. |
| **`fn f(s: &String)`** | clippy `ptr_arg` fails under `-D warnings` | Take `&str`; it accepts `&String`, `&str` slices, and literals via deref coercion. |
| **`s1 + s2` (two `String`s)** | `error[E0277]` / surprised that `s1` is moved | `+` is `add(self, s: &str)` — it **moves** the left side. Write `s1 + &s2`, or prefer `format!` which borrows all inputs. |
| **`&'static str` not visible via `type_name`** | `type_name::<&'static str>()` prints just `&str` | `type_name` erases lifetimes. Prove `'static` with a `fn() -> &'static str` signature, not `type_name`. |
| **Expecting `s[i]` to be O(1)** | Naively calling `.chars().nth(i)` in a loop → O(n²) | `.chars().nth(i)` walks from the front. Iterate with `for c in s.chars()` or collect once. |
| **Grapheme clusters from std** | "How do I get the Nth visible letter?" | Not in std. `chars()` gives scalar values, not graphemes (`"👨‍👩‍👧"` is several scalars, one cluster). Use `unicode-segmentation`. |
| **Treating a literal like a growable buffer** | `push_str` on a `&str` won't compile | A literal is `&'static str` — immutable, in the read-only binary. You need an owned `String` to mutate. |

---

## Cheat sheet

```rust
// OWNERSHIP is the dividing line:
//   String  = OWNED, growable, heap buffer of UTF-8 bytes   {ptr, len, capacity} = 24 B
//   &str    = BORROWED, read-only view                      {ptr, len}           = 16 B

let s: String = String::from("hello");   // owns the heap buffer
let lit: &str = "hello";                 // &'static str, baked into the binary

// len() == BYTES, not characters (UTF-8 is variable-width):
//   "résumé".len() == 8   (6 letters)      "👋".len() == 4   (1 emoji)
"résumé".chars().count();                // 6  -- use .chars() for scalar values

// &str -> String  (allocates a new owner):
"hi".to_string();                        // ToString  (== String::from / .to_owned())
// String -> &str  (free, via Deref<Target=str>):
s.as_str();                              // explicit
let v: &str = &s;                        // deref coercion: &String -> &str

// Build efficiently:
let mut b = String::with_capacity(64);   // pre-allocate -> no realloc while growing
b.push_str("foo"); b.push('!');          // push_str(&str), push(char)
let cat = format!("{}-{}", a, b);        // borrows all inputs; never moves them
// let _ = s[0];                          // E0277 — indexing is FORBIDDEN
s.chars().next();                        // first scalar value (clippy prefers .next())
s.chars().nth(2);                        // i-th scalar value (O(i) front walk)
&s[0..4];                                // byte-range slice; PANICS if not a char boundary
s.get(0..4);                             // non-panicking: Option<&str>
```

---

## Sources

Every claim above was web-verified in at least two authoritative places; the
pinned byte counts and the `E0277` message were reproduced with the local
toolchain (`rustc` 1.96.0).

- **The Rust Programming Language, ch8.2 "Storing UTF-8 Encoded Text with Strings"**
  — `String` as a growable/owned/UTF-8 wrapper over `Vec<u8>`; `to_string`/
  `String::from`; `push_str`/`push`; the `+`/`add(self, s: &str)` signature &
  deref coercion; `format!`; the `E0277` indexing error and its three reasons;
  bytes vs scalar values vs grapheme clusters; slicing at char boundaries:
  https://doc.rust-lang.org/book/ch08-02-strings.html
- **The Rust Programming Language, ch4.3 "The Slice Type"** — `&str` as a
  `{ptr, len}` fat pointer; a literal is a `&str` into the read-only binary (hence
  immutable); "String Slices as Parameters" (take `&str`, not `&String`); slicing
  must hit UTF-8 char boundaries:
  https://doc.rust-lang.org/book/ch04-03-slices.html
- **`std::string::String` docs** — `String` owns a heap-allocated buffer; the
  `{ptr, len, capacity}` Representation; "always valid UTF-8"; `Deref<Target=str>`
  and the inexpensive `&String`→`&str` coercion; `with_capacity` and the
  `0,8,16,16,32,32` capacity-growth trace:
  https://doc.rust-lang.org/std/string/struct.String.html
- **`std::primitive.str` / `std::str` docs** — `str` as the core string slice;
  `len()`/`is_empty()`/`chars()`/`bytes()`/`char_indices()`; `is_char_boundary`:
  https://doc.rust-lang.org/std/primitive.str.html
- **The Rust Reference — Tokens: String literals** — a string literal's lexing and
  that its bytes are baked into the binary:
  https://doc.rust-lang.org/reference/tokens.html#string-literals
- **The Rust Reference — Literal expressions** — a string literal has type
  `&'static str` (the `'static` lifetime):
  https://doc.rust-lang.org/reference/expressions/literal-expr.html
- **Clippy lint `iter_nth_zero`** — why `.chars().next()` is preferred over
  `.chars().nth(0)` (the `.nth(0)` → `.next()` rewrite under `-D warnings`):
  https://rust-lang.github.io/rust-clippy/master/#iter_nth_zero
