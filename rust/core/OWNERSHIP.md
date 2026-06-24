# OWNERSHIP — One Owner, Moves, and Deterministic Drop

> **One-line goal:** every value has **exactly one owner**; assigning / passing /
> returning a non-`Copy` value **moves** that ownership (the source becomes
> unusable); when the owner goes out of scope the value is **dropped**
> (`Drop::drop` runs once, deterministically).
>
> **Run:** `just run ownership` (== `cargo run --bin ownership`)
> **Member:** `core` (stdlib-only — no `[dependencies]`).
> **Prerequisites:** none — this is **Phase 1 / the STYLE ANCHOR**. Read this first.
> **Ground truth:** [`ownership.rs`](./ownership.rs); captured stdout:
> [`ownership_output.txt`](./ownership_output.txt).

---

## Why this exists (lineage)

Most languages manage memory one of two ways, and Rust rejects both:

| Model | Who frees? | Cost / problem |
|---|---|---|
| **Garbage collection** (Java, Go, Python, JS) | A runtime **tracer** periodically finds unreachable memory | Non-deterministic pauses; you can't say *when* a finalizer runs; runtime overhead. |
| **Manual `malloc`/`free`** (C, C++) | **You**, by hand | Forget → leak; free twice → corruption; free early → use-after-free. The classic security bugs. |
| **Ownership** (Rust) | **The compiler** inserts the free at compile time; the runtime does *nothing* | Zero-cost, deterministic, memory-safe with **no GC**. |

Rust's bet: memory safety **and** speed, by making "who owns this, and for how
long" a **compile-time** property enforced by the **borrow checker**. There is no
tracing collector, no reference count inserted for you, no pause. The price is
that you must think about ownership on every binding — which is exactly what this
bundle makes mechanical.

```mermaid
graph TD
    Owner["Each value has ONE owner binding"]
    Owner -->|"let s2 = s1;<br/>pass by value<br/>return"| Move["MOVE for non-Copy types<br/>(String, Vec, Box, ...)"]
    Owner -->|"let y = x;"| Copy["COPY for Copy types<br/>(i32, &T, bool, ...)"]
    Move --> Poisoned["source s1 is POISONED<br/>using it = compile error E0382"]
    Copy --> BothValid["both x and y valid<br/>(cheap bitwise copy)"]
    Owner -->|"} end of scope"| Drop["Drop::drop runs ONCE<br/>(deterministic, RAII)"]
    Move --> Shallow["shallow: only the handle copies<br/>{ptr,len,cap} = O(1)"]
    Poisoned -->|.clone() alternative| Clone["deep copy: both usable"]
    style Owner fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style Move fill:#fef9e7,stroke:#f1c40f,stroke-width:2px
    style Drop fill:#eaf2f8,stroke:#2980b9,stroke-width:2px
    style Poisoned fill:#fdedec,stroke:#c0392b,stroke-width:2px
```

---

## The three rules (memorize these)

The Rust Book states them verbatim ([ch4.1][book-ownership]):

1. Each value in Rust has an **owner**.
2. There can only be **one owner at a time**.
3. When the owner goes **out of scope**, the value will be **dropped**.

Everything in this guide is a consequence of those three lines.

---

## Section A — A move on assign invalidates the source

```rust
let s1 = String::from("hello");
let s2 = s1;          // OWNERSHIP MOVES into s2; s1 is now unusable
```

> **From ownership.rs Section A:**
> ```
> ======================================================================
> SECTION A — move on assign: the source is INVALIDATED
> ======================================================================
>   let s1 = String::from("hello");   s1.len=5, s1.cap=5
>   let s2 = s1;   // ownership MOVES -> s1 is now unusable
>                   s2 = "hello", s2.len=5, s2.cap=5
> [check] moved String's new owner has the SAME len as the original: OK
> [check] moved String's new owner has the SAME cap as the original: OK
>   let c1 = String::from("rust");  let c2 = c1.clone();
>     c1 = "rust", c2 = "rust"  (both usable)
> [check] .clone() deep-copies: source AND clone stay usable and equal: OK
> ```

**What.** `let s2 = s1;` does **not** copy the heap bytes of `"hello"`. It copies
the small on-stack **handle** `{ptr, len, cap}` and then marks `s1` as moved.
The two checks confirm `s2` ends up with the **same `len` and `cap`** the
original had — i.e. it now points at the very same heap buffer `s1` built.

**Why (internals).** A `String` is a 3-word handle on the stack (pointer +
length + capacity, **24 bytes** on a 64-bit target — proven in Section E) that
points at a heap buffer. If assignment *also* copied the heap, you'd get **two**
owners of one buffer; when both later dropped they'd **double-free** it — a
classic memory-safety bug ([Book Fig. 4-2][book-ownership]). Rust prevents that
not by copying the heap (expensive, O(n)) but by **invalidating the source**:
after the move there is still exactly one owner, so there is exactly one free.
The compiler enforces this statically — using `s1` after the move is a
**compile error**, never a runtime crash.

**The compile error (cannot live in the runnable `.rs` — it would not build):**

```console
error[E0382]: borrow of moved value: `s1`
 --> src/main.rs:5:16
  |
2 |     let s1 = String::from("hello");
  |         -- move occurs because `s1` has type `String`,
  |            which does not implement the `Copy` trait
3 |     let s2 = s1;
  |              -- value moved here
4 |
5 |     println!("{s1}, world!");
  |                ^^ value borrowed here after move
  |
  = note: this error originates in the macro `format_args_nl` ...
help: consider cloning the value if the performance cost is acceptable
  |
3 |     let s2 = s1.clone();
  |                ++++++++
```

> **`error[E0382]`** is *the* borrow-checker signature you will meet constantly.
> Note the message tells you the **reason** (`does not implement the Copy trait`)
> and the **fix** (`.clone()`). Reading these messages is the skill.

**The escape hatch — `.clone()`** (third check). When you genuinely need two
independent copies, `.clone()` performs the **deep** copy the compiler refuses
to do automatically: the heap buffer is duplicated, so `c1` and `c2` are both
usable. The Book calls this a "visual indicator that something different is going
on" — `.clone()` may be expensive, which is precisely why it is never implicit.
🔗 See [COPY_CLONE](./COPY_CLONE.md) for which types are `Copy` (cheap, implicit)
versus `Clone` (explicit, possibly deep).

---

## Section B — Moving into a function; borrowing to avoid the move

Passing a value **by value** to a function is mechanically identical to `let s2
= s1;` — it is a move. The caller's binding is dead afterwards.

```rust
fn takes_string(s: String) -> usize { s.len() }   // s MOVED in; dropped at `}`

let s = String::from("hello");
let n = takes_string(s);   // s moved into the fn; unusable here
```

> **From ownership.rs Section B:**
> ```
> ======================================================================
> SECTION B — move into a function; borrow to use without owning
> ======================================================================
>     [inside takes_string] received "hello" (len 5)
>   takes_string(s) -> 5  (s moved away; unusable in caller)
> [check] value moved into fn is dropped there; its length returns via the return value: OK
>     [inside takes_string] received "world" (len 5)
>   takes_string(s2.clone()) -> 5  (caller keeps s2 = "world")
> [check] clone first: caller keeps a usable, equal copy after the call: OK
>   len_of(&s3) -> 4  (s3 still owned by caller: "rust")
> [check] borrowing (&) does NOT move; caller retains ownership and value: OK
> ```

**What.** Three ways to hand a `String` to a function, each with a different
ownership consequence (first check: by-value move; second check: clone-first;
third check: borrow):

| Call | Ownership | Caller's `s` afterwards | Cost |
|---|---|---|---|
| `takes_string(s)` | **moves** in | **unusable** (compile error to touch) | O(1) move |
| `takes_string(s.clone())` | moves a **clone** in | still usable | O(n) deep copy |
| `len_of(&s)` | **no** move — borrows | still usable, still owns | O(1), no copy |

**Why (internals).** The borrow checker models every value's ownership as a
**linear resource**: it must have exactly one owner at all times, so giving it
away (by value) must extinguish the giver. The only way to *use* a value without
taking it is a **reference** `&T` — a *permission to read/use without owning*.
`len_of(&s3)` returns `4` and `s3` is still `"rust"` in the caller: the borrow
ended at the statement boundary and ownership never left. This is the doorway to
the entire borrowing system.

> **Signature idiom:** `len_of` takes `&str`, not `&String`. Clippy's
> `ptr_arg` lint (`-D warnings`) flags `&String`/`&Vec` parameters because `&str`
>/`&[T]` are more general and free (deref-coercion turns `&String` into `&str`
> at the call site for free). Every later bundle follows this.

**The compile error (using `s` after moving it into the function) is again
`E0382`**, identical in shape to Section A:

```console
error[E0382]: borrow of moved value: `s`
  |
  |     let s = String::from("hello");
  |         - move occurs because `s` has type `String`, ...
  |     takes_string(s);
  |                  - value moved here
  |     println!("{s}");   // cannot use `s` here
  |                ^ value borrowed here after move
```

🔗 [BORROWING](./BORROWING.md) — references (`&`/`&mut`) are *permissions to use
without owning*; you cannot understand a move until you see what a borrow avoids.

---

## Section C — Drop at scope end: RAII, deterministic, exactly once

When an owner reaches the end of its scope (the closing `}`), Rust runs its
**drop glue** automatically. This is **RAII** ("Resource Acquisition Is
Initialization", borrowed from C++): the lifetime of the value *is* the lifetime
of the resource, and cleanup is tied to the braces, not to a manual call.

> **From ownership.rs Section C:**
> ```
> ======================================================================
> SECTION C — drop at scope end: RAII, deterministic, exactly once
> ======================================================================
>   created alpha, then bravo  (drops so far: 0)
> [check] no Drop runs while the owners are still in scope: OK
>     (drop fires: bravo)
>     (drop fires: alpha)
>   after block closed: total drops = 2
> [check] both sentinels dropped exactly once, at scope end: OK
> ```

**What.** A `Sentinel` struct implements `Drop` to bump a shared `Cell<u32>`
counter (and print) when it is destroyed. Two sentinels are created inside a
block; the first check shows zero drops while both are alive; the second check
shows the count is exactly `2` after the block closes.

**Why (internals).**
- **Deterministic & exactly once.** Unlike a GC finalizer (which may never run,
  or run at an unknown time), Rust's drop is **guaranteed to run exactly once**
  at a known place: the `}`. That is why `MutexGuard`, file handles, and
  `Box`'s heap free can all be `Drop` impls — no leak is possible if the owner
  is reachable.
- **Drop order is reverse declaration order.** The output shows `bravo` dropping
  *before* `alpha`, even though `alpha` was declared first. The Rust Reference
  fixes this: local variables drop in **reverse order of declaration**
  ([Reference — Destructors][ref-destructors]). This makes later values (which
  may borrow earlier ones) drop before the things they borrow — a soundness
  requirement.
- **`Drop` cannot be `Copy`.** A type that implements `Drop` is forbidden from
  being `Copy` (compile error E0184 if you try). The Book: "Rust won't let us
  annotate a type with the `Copy` trait if the type, or any of its parts, has
  implemented the `Drop` trait." ([Book ch4.1][book-ownership]) — because
  copying a resource that needs custom cleanup would call `drop` twice. The
  `Sentinel` here is therefore a move-only type.

> **Interior mutability note.** The counter is a `Cell<u32>` shared by *two*
  sentinels through `&Cell`. `Cell` provides mutation through a **shared**
  reference (`set`/`get`), so `drop(&mut self)` can increment a counter that
  lives outside the sentinel without any `Mutex`/`RefCell` borrow tracking. This
  is the simplest interior-mutability primitive. 🔗 [BOX_RC_ARC](./BOX_RC_ARC.md)
  and an interior-mutability bundle cover `RefCell`/`Mutex` for the non-`Copy`
  cases.

---

## Section D — `std::mem::drop` forces an EARLY drop; reassignment drops the old value

Sometimes you cannot wait for the `}` — e.g. releasing a `MutexGuard` mid-scope,
or closing a file before reopening it. `std::mem::drop` does that.

```rust
pub fn drop<T>(_x: T) {}   // the ENTIRE stdlib definition — it is not magic
```

> **From ownership.rs Section D:**
> ```
> ======================================================================
> SECTION D — std::mem::drop forces an EARLY drop; reassign drops the old value
> ======================================================================
>   created xray  (drops: 0)
>     (drop fires: xray)
>   after std::mem::drop(_x): drops = 1  (dropped NOW, before block end)
> [check] std::mem::drop drops the value immediately, not at scope end: OK
> [check] no double-drop: an early-dropped value is not dropped again at scope end: OK
>   created 'first'  (drops: 0)
>     (drop fires: first)
>   after `s = Sentinel{second}`: drops = 1  (current owner = 'second')
> [check] reassigning a binding drops the old value immediately: OK
>     (drop fires: second)
> [check] 'second' then drops at scope end (total 2): OK
> ```

**What.** Four checks pin the timing:
1. `std::mem::drop(_x)` runs `Drop` **immediately** at the call site (count `1`
   before the block ends).
2. There is **no double-drop** — the early-dropped value is *not* dropped again
   at the `}`. (Rust's soundness guarantee: drop runs once.)
3. **Reassigning** a binding (`s = Sentinel{second}`) drops the **old** value
   **immediately**, not at scope end (`'first'` drops on that line).
4. The **new** value (`'second'`) then drops normally at the `}` (total `2`).

**Why (internals).**
- `std::mem::drop(x)` is **literally** `fn drop<T>(_x: T) {}` ([std docs][std-drop]).
  It works purely through the ownership model: `_x` takes the value **by value**
  (a move), and because `_x` is never used, it is dropped at the end of the
  function body — i.e. right there at the call. There is no special runtime
  support; it is ownership all the way down.
- The `_` (underscore) binding name inside the function is what marks "intentionally
  unused" so the compiler does not warn. **Do not confuse this with `let _ =
  expr;` at the use site** — see the pitfalls table: `let _ = ...` drops
  *immediately*, whereas `let _x = ...` lives to end of scope.
- **Reassignment = drop-then-overwrite** ([Book "Scope and Assignment"][book-ownership]).
  When you write `s = new_value`, Rust first runs the drop glue of the *current*
  value of `s`, then writes the new value into the binding. That is why
  `'first'` is gone before `'second'` even exists, with no double-free.
- For `Copy` types, `std::mem::drop` is a **no-op**: a copy is moved in and
  dropped; the original persists unchanged (see the [std::mem::drop docs][std-drop]
  example). 🔗 [COPY_CLONE](./COPY_CLONE.md).

---

## Section E — A move is a SHALLOW bitwise copy of the handle (O(1))

A frequent confusion is "isn't a move just a copy?" No — a move copies only the
**handle** (the fixed-size stack representation), never the heap payload.

> **From ownership.rs Section E:**
> ```
> ======================================================================
> SECTION E — a move is a SHALLOW bitwise copy of the handle (O(1))
> ======================================================================
>   let s1 = String::from("hello, rust");
>     handle size = size_of_val(&s1) = 24 bytes
>     s1.len = 11, s1.cap = 11
>   let s2 = s1;  // handle copied bitwise; heap NOT copied; s1 poisoned
>     s2.len = 11, s2.cap = 11
> [check] String handle = ptr(8)+len(8)+cap(8) = 24 bytes on a 64-bit target: OK
> [check] shallow move preserves len across the move: OK
> [check] shallow move preserves cap across the move: OK
>   big = ...repeat(1000) -> 10000 bytes of heap text; handle still 24 bytes
> [check] handle size is constant: a 10000-byte String still has a 24-byte handle: OK
> [check] moving `big` is O(1): only the 24-byte handle copies, never the 10000 heap bytes: OK
> ```

**What.** `size_of_val(&s1)` reports the handle is **24 bytes**; after the move
`s2` has the **same `len` and `cap`**; and crucially a **10 000-byte** `String`
(`big`) still has a **24-byte** handle. The move is therefore **O(1)** — it
copies 24 bytes regardless of how much text lives on the heap.

**Why (internals).**
- `String` = `{ ptr: *const u8 (8), len: usize (8), capacity: usize (8) }` =
  24 bytes on a 64-bit target. `size_of_val(&s1)` returns this **structural**
  size — it is deterministic and has nothing to do with the actual address
  (which varies per run due to ASLR, so this file deliberately never prints one;
  see the DETERMINISM rule in `HOW_TO_RESEARCH.md` §4.2).
- A move is a **`memcpy` of those 24 bytes** — the pointer now lives in two
  handles for an instant, but the compiler statically invalidates the old one
  (poisons it), so at runtime only `s2` is usable. The heap buffer is **not**
  touched. The Hacker News summary of the LLVM lowering: "Rust will bitwise copy
  the containing type... if you move a `String`, it will copy the `String`
  struct" ([HN discussion][hn-move]). The HashRust writeup agrees: a move is "the
  combination of [a] shallow copy of the value and a static check by the
  compiler that the old value cannot be used anymore" ([HashRust][hashrust]).
- **Handle size is constant ⇒ move cost is constant.** That is the whole point
  of the `big` check: moving a 10 KB string costs the same 24-byte copy as
  moving `"hi"`. This is why the Book says "any automatic copying can be assumed
  to be inexpensive in terms of runtime performance" ([Book ch4.1][book-ownership])
  — Rust never inserts a hidden deep copy.

> **Why not just call it a shallow copy?** Because a shallow copy would leave
> **two** live owners (a double-free waiting to happen). A move is a shallow
> copy **plus** source invalidation. The invalidation is the load-bearing part;
> it is what makes the shallow copy safe. The Book: "because Rust also
> invalidates the first variable, instead of being called a shallow copy, it's
> known as a *move*" ([Book ch4.1][book-ownership]).

🔗 [MOVE_SEMANTICS](./MOVE_SEMANTICS.md) — partial moves (`s.field` out of a
struct) and moving out of fields. 🔗 [DROP_UNSAFE](./DROP_UNSAFE.md) — the `Drop`
trait in depth, drop glue, and `ManuallyDrop`/`MaybeUninit`.

---

## Pitfalls (the expert payoff)

| Trap | Symptom | Fix / why |
|---|---|---|
| **Using a value after a move** | `error[E0382]: borrow of moved value: \`x\`` | The source is poisoned. If you need both, `.clone()` first, or pass `&x` to borrow. |
| **`let _ = guard;`** vs **`let _x = guard;`** | A `MutexGuard`/sentinel seems to release instantly (or never) | `let _ = expr;` drops **immediately**; `let _x = ...` (named, even with `_`) lives to the `}`. Bind it to a name to keep it alive. |
| **Expecting a deep copy** | Two bindings "share" data but editing one changes... nothing, because the source is dead | Rust never deep-copies implicitly. `clone()` is the only deep copy, and it's explicit. |
| **Forgetting drop runs in reverse order** | A field is dropped before the thing that still needs it | Locals drop in **reverse declaration order**. Declare dependents *after* their dependencies. |
| **`fn f(s: &String)`** | clippy `ptr_arg` fails under `-D warnings` | Take `&str` (or `&[T]`); deref-coercion makes `&String` → `&str` free at the call site. |
| **Thinking `Copy` types move** | "Why is my `i32` still usable after `let y = x;`?" | `Copy` types are **copied**, not moved — both bindings stay valid. `Drop` types can't be `Copy`. |
| **Calling `.clone()` reflexively** | needless clones, perf hit; clippy `redundant_clone` | Clone only when you need two owners. Often a `&` borrow is what you wanted. |
| **Double-free intuition from C** | "Won't two owners both free?" | There is never two owners — the move poisons the source, so `drop` runs exactly once. No runtime check needed. |
| **`mut` reassignment drops silently** | Old value gone before you expect | `s = new_value` runs the **old** value's `Drop` right there. If the old value is a guard, it's released at reassignment, not at `}`. |
| **`drop(x)` on a `Copy` type does nothing** | "I dropped my `i32` but it's still there" | `std::mem::drop` moves a *copy* in and drops that; the original `Copy` value is untouched (clippy `dropping_copy_types` even warns). |

---

## Cheat sheet

```rust
// RULE 1: one owner at a time.
// RULE 2: assigning/passing/returning a non-Copy value MOVES it (source dies).
// RULE 3: at the owner's `}`, Drop::drop runs once (deterministic, RAII).

let s1 = String::from("hi");   // s1 owns the heap buffer
let s2 = s1;                   // MOVE: s2 owns it now; s1 is POISONED
// s1.len();                   // E0382 borrow of moved value — won't compile
let c2 = s1.clone();           // (hypothetically) deep copy -> both valid

take(s2);                      // moves into the fn; caller's s2 dead after
take(&s2);                     // BORROW: no move, caller keeps s2  -> BORROWING
drop(s2);                      // std::mem::drop -> early drop, RIGHT NOW
// std::mem::drop is literally:  pub fn drop<T>(_x: T) {}

// A move = bitwise copy of the 24-byte {ptr,len,cap} HANDLE only -> O(1).
//   size_of_val(&s) == 24   (never print the address; it's non-deterministic)
// Drop order at `}` = REVERSE declaration order. Drop can't be Copy.
```

---

## Sources

Every claim above was web-verified in at least two authoritative places.

- **The Rust Programming Language, ch4.1 "What is Ownership?"** — the 3 rules, the
  `String` move figure, `E0382`, `clone`, `Copy`, scope/drop, RAII, "Scope and
  Assignment" (reassignment drops immediately):
  https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html
- **`std::mem::drop` docs** — the literal definition `pub fn drop<T>(_x: T) {}`,
  "it is not magic", the `Copy`-no-op behavior, `RefCell` borrow-release example:
  https://doc.rust-lang.org/std/mem/fn.drop.html
- **The Rust Reference — Destructors / drop order** — reverse-order-of-declaration
  drop, drop glue, drop runs once:
  https://doc.rust-lang.org/reference/destructors.html
- **The Rust Book ch15.3 "The `Drop` Trait Runs Code on Cleanup"** — RAII,
  custom `Drop`, why you cannot call `Drop::drop` directly (use `std::mem::drop`):
  https://doc.rust-lang.org/book/ch15-03-drop.html
- **HashRust — "Moves, copies and clones in Rust"** — a move is "a shallow copy
  of the value and a static check by the compiler that the old value cannot be
  used anymore" (independent corroboration of the Book's model):
  https://hashrust.com/blog/moves-copies-and-clones-in-rust/
- **Hacker News discussion of move lowering** — "Rust will bitwise copy the
  containing type... if you move a `String`, it will copy the `String` struct"
  (LLVM-level confirmation that a move is a shallow bitwise handle copy):
  https://news.ycombinator.com/item?id=23363986
- **Effective Rust, Item 11 "Implement the Drop trait for RAII patterns"** —
  RAII discipline, when/why to write a custom `Drop`:
  https://effective-rust.com/raii.html
