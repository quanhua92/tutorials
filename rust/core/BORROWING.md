# BORROWING — References (`&T` / `&mut T`) and the Alias-XOR-Mutability Rule

> **Goal (one line):** a reference is a *permission to read (`&T`) or mutate
> (`&mut T`) a value without taking ownership of it* — enforced by the borrow
> checker at compile time so that **aliased mutation is impossible**.

**Run:** `just run borrowing` (== `cargo run --bin borrowing`)
**Prerequisites:** [OWNERSHIP](#) (a value has exactly one owner; passing it by
value *moves* it and invalidates the source). Borrowing is the cure for "I want
to use it, not own it."
**Member:** `core` (stdlib-only).

---

## Lineage — why borrowing exists

🔗 [OWNERSHIP](#) is heavy: if `calculate_length(s: String)` takes the `String`
by value, ownership *moves* into the function and `s` is dead when it returns —
so the book's first attempt returns `(String, usize)` to hand ownership *back*.
That is absurd for a function that only wants to *look* at the data.

**Borrowing** is the lighter tool: create a **reference** with `&` that refers to
the owner's data **without owning it**. Because the reference doesn't own the
data, dropping the reference does **nothing** to the data — the owner keeps it.
The price is one rule — **you may have many readers *or* one writer, never both**
— which is exactly the rule that prevents data races, and the compiler proves it
holds *before your program ever runs*.

```mermaid
graph TD
    OWN["x : i32 = 42<br/>(THE OWNER<br/>holds the value)"]
    OWN -- "& (shared, read-only)" --> A1["r1 : &i32"]
    OWN -- "& (many allowed)" --> A2["r2 : &i32"]
    OWN -- "& (many allowed)" --> A3["r3 : &i32"]
    OWN -.->|&mut (EXCLUSIVE<br/>only ONE, no others)| M["rm : &mut i32"]
    style OWN fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style M fill:#fadbd8,stroke:#c0392b,stroke-width:2px
```

The solid arrows (many `&`) and the dashed arrow (one `&mut`) are **mutually
exclusive at any instant** — that is the entire borrow checker in one diagram.

---

## The aliasing-XOR-mutability rule (the core invariant)

> **At any instant, for any one piece of data, you may have:**
> **either** any number of **shared** references `&T`,
> **or** exactly **one** **mutable** reference `&mut T` —
> **never both, never two mutables.**

This is often shortened to *"aliasing XOR mutability"*: you get *aliasing*
(many names for the same data) **or** *mutation*, but not both at once. The
borrow checker enforces it statically — there is no runtime check, no lock; if
your code violates it, **it does not compile**. That is why Rust is said to give
"data-race freedom by construction": the three ingredients of a data race —

1. two or more pointers access the same data at the same time,
2. at least one is writing,
3. there is no synchronization,

— can never all be true in safe Rust, because rule (2)+(1) without sync is
exactly what `&mut`'s exclusivity forbids.

### Shared `&T` vs mutable `&mut T` — side by side

| Aspect | Shared reference `&T` | Mutable reference `&mut T` |
|---|---|---|
| Permission | **read** the data | **read + mutate** the data |
| How many at once | **any number** | **exactly one** |
| Other refs allowed? | yes (more `&T`) | **none** (no `&T`, no other `&mut`) |
| `Copy`? | **yes** (copying = copying the pointer) | **no** (it is the sole access path) |
| Default? | references are immutable by default, like bindings | requires `&mut` and a `mut` owner |

---

## Section A — Shared references: many readers, all read-only

A shared reference `&T` lets you read a value you don't own. Any number of them
may exist simultaneously, and dereferencing each yields the **same** value. We
never print pointer *addresses* (ASLR makes them non-reproducible); we assert the
*structural* fact — all three deref to `42`.

> From `borrowing.rs` Section A:
> ```
> value x = 42
> deref r1 = 42 | deref r2 = 42 | deref r3 = 42
> implicit deref (Display): r1 = 42 | r2 = 42 | r3 = 42
> [check] three &i32 to the same value all deref to 42: OK
> [check] shared refs are Copy (r1 still readable again): OK
> [check] x still owned & unchanged after borrowing (borrow != move): OK
> ```

Note the implicit deref: `println!("{r1}")` works because `&T: Display` whenever
`T: Display` — the compiler auto-derefs for you. `*r1` is the explicit form.

---

## Section B — Exclusive reference: one writer, mutation reflects on the owner

A mutable reference `&mut T` is the **only** permitted access path while it
lives, so writing through it (`*r = 99`) mutates the owner's data directly. The
reference still **does not own** the value — it merely holds the permission to
mutate — so when it goes out of scope the owner `x` carries the change.

> From `borrowing.rs` Section B:
> ```
> before: x = 10
> inside block, after *r = 99: *r = 99
> after:  x = 99  (mutation reflected on the owner)
> [check] &mut mutation reflects on the original (x 10 -> 99): OK
> ```

---

## Section C — Borrowing does **not** move

This is the whole point versus OWNERSHIP. After `let r = &s;`, the owner `s` is
still fully usable — borrowing is a *look, don't take* operation. (A move
`let r = s;` would have killed `s`; see 🔗 [MOVE_SEMANTICS](#).)

> From `borrowing.rs` Section C:
> ```
> borrow r reads: "hi"
> owner s still works after the borrow: "hi"
> [check] s is still usable after `let r = &s;`: OK
> ```

---

## Section D — Non-Lexical Lifetimes (NLL): a borrow ends at its *last use*

A reference's scope is **not** "from its declaration to the closing brace" — it
ends at its **last use**. So once `r1`/`r2` are last read in the `println!`, they
are *dead*, and a fresh `&mut s` afterwards is legal even though all three names
are textually in the same block. Before NLL landed in Rust 2018, this *was* a
compile error; the compiler now tracks actual use.

```mermaid
sequenceDiagram
    participant Code
    Note over Code: let mut s = "nll";
    Code->>s: let r1 = &s;   (immutable borrow #1 starts)
    Code->>s: let r2 = &s;   (immutable borrow #2 starts)
    Code->>s: println r1, r2;  ◄── LAST USE: r1, r2 now DEAD
    Note over Code: NLL ends the immutable borrows here.
    Code->>s: let r3 = &mut s;  (legal: no overlap with the dead & borrows)
    Code->>s: r3.push_str(...); (mutate)
```

> From `borrowing.rs` Section D:
> ```
> shared reads: "nll" + "nll"
> mutated via &mut: "nll works"
> [check] NLL: &mut after last & use compiles and runs: OK
> ```

---

## Section E — Borrowing a slice `&[T]`: read a whole sequence without owning

The idiomatic "lend me the data" signature is a slice reference: `fn
sum_slice(nums: &[i32])`. The caller passes `&data` (an array coerces to a slice
reference), the function reads every element, and `data` is **never moved or
copied**. This is how nearly every stdlib collection reader is written.

> From `borrowing.rs` Section E:
> ```
> data = [4, 8, 15, 23]
> sum_slice(&data) = 50  (data not moved)
> [check] sum_slice([4, 8, 15, 23]) == 50: OK
> [check] data still owned after passing &data to a fn: OK
> ```

---

## Section F — Mutable reborrow: `&mut *r`

From an existing `&mut T` you can mint another `&mut T` to the same data with
`&mut *r` (a **reborrow**). While the reborrow lives, the original `r` is
*unavailable*; when it ends, `r` is usable again — so the XOR-mutability
invariant still holds (still exactly one writer). Passing `r` to a `&mut`-
parameter function **implicitly** reborrows, which is why the caller keeps
ownership and `x` reflects the change.

> From `borrowing.rs` Section F:
> ```
> after add_one(&mut x): x = 8
> [check] reborrow &mut *r mutated through a fn (x 7 -> 8): OK
> ```

---

## The "why" — mechanism beneath the syntax

**What is a reference, physically?** A reference is a pointer: the address of the
borrowed data, with a thin "shared vs mutable" tag in the *type*. At runtime a
`&i32` and a `*const i32` are the same machine word; the safety lives entirely in
the type system and the borrow checker, so references are **zero-cost** — no
runtime counters, no locks, no reference counting.

**Why is `&T` `Copy` but `&mut T` not?** Copying a `&T` is shallow — it just
duplicates the pointer, and since nobody can mutate through a `&T`, two copies
can't race. A `&mut T` is *the* sole access path; if it were `Copy` you'd have
two mutable paths and the invariant would break, so it is move-only.

**Who enforces the rule?** The **borrow checker**, a compile-time pass that
tracks, for every place, the set of outstanding shared and mutable borrows and
rejects any state with overlap. It uses **lifetimes** (🔗 [LIFETIMES](#)) as its
"time axis": a borrow is valid for a region of the program, and NLL shrinks that
region to actual use. The checker proves two things up front: (1) no aliasing +
mutation overlap, and (2) **references never dangle** — no reference may outlive
the data it points to (the owner must outlive all its borrowers). A dangling
reference is therefore a *compile error*, not a runtime crash.

**The two forbidden states are compile errors** (not runtime panics). On this
toolchain (`rustc 1.96.0`, edition 2024) the exact messages are:

Two `&mut` to the same place at once (error **`E0499`**):
```text
error[E0499]: cannot borrow `s` as mutable more than once at a time
 --> main.rs:4:14
  |
3 |     let r1 = &mut s;
  |              ------ first mutable borrow occurs here
4 |     let r2 = &mut s;
  |              ^^^^^^ second mutable borrow occurs here
5 |     println!("{r1}, {r2}");
  |                -- first borrow later used here
```

A `&mut` while a `&` is alive (error **`E0502`**):
```text
error[E0502]: cannot borrow `s` as mutable because it is also borrowed as immutable
 --> main.rs:5:14
  |
3 |     let r1 = &s;
  |              -- immutable borrow occurs here
4 |     let r2 = &s;
5 |     let r3 = &mut s;
  |              ^^^^^^ mutable borrow occurs here
6 |     println!("{r1}, {r2}, {r3}");
  |                -- immutable borrow later used here
```

A related one — trying to mutate **through** a shared `&` — is error **`E0596`**:
`cannot borrow \`*some_string\` as mutable, as it is behind a \`&\` reference`.
These three are the borrow checker's entire rejection vocabulary for this
chapter; learn to read them and most "fighting the borrow checker" moments
resolve themselves.

---

## 🔗 Cross-references

- 🔗 **[OWNERSHIP](#)** — you cannot understand a borrow until you see that a
  reference is *permission to use without owning*, and ownership is what the
  borrower never takes. Borrowing is the answer to "ownership moves are too
  expensive just to read."
- 🔗 **[MOVE_SEMANTICS](#)** — the contrast case: a move invalidates the source;
  a borrow does not. `let r = &x` vs `let r = x`.
- 🔗 **[LIFETIMES](#)** — *how long* a borrow is valid. The borrow checker's time
  axis; without named lifetimes you cannot return a reference or store one in a
  struct.
- 🔗 **[INTERIOR_MUTABILITY](#)** — what to reach for when the type system's
  "`&` + mutation is impossible" rule is genuinely too strict: `Cell`/`RefCell`
  (single-threaded) and `Mutex`/`RwLock` (multi-threaded) move the aliasing check
  to runtime so you *can* mutate through what looks like a shared handle.

---

## Pitfalls (the expert payoff)

| Trap | Symptom / error | Fix |
|---|---|---|
| Two `&mut` to one place | `E0499 cannot borrow ... as mutable more than once at a time` | Drop/re-scope the first before making the second; or collect results and mutate sequentially. |
| `&` alive while making `&mut` | `E0502 cannot borrow ... as mutable because it is also borrowed as immutable` | Move the last use of the `&` *before* the `&mut` (NLL ends the borrow at last use). |
| Mutate through `&` | `E0596 cannot borrow \`*x\` as mutable, as it is behind a \`&\` reference` | Take `&mut` from the start, or use interior mutability. |
| Forgetting `mut` on the owner | `cannot borrow \`s\` as mutable, as it is not declared as mutable` | Declare `let mut s = ...`. |
| Return a `&` to a local | `E0106 missing lifetime specifier` / "no value for it to be borrowed from" (dangling) | Return an *owned* value, or tie the reference's lifetime to an input (🔗 LIFETIMES). |
| Holding a `&mut` too long blocks reuse | borrow errors far from the cause | Bind the `&mut` in the tightest scope possible; reborrow (`&mut *r`) instead of re-borrowing the owner. |
| Expecting `&mut` to be `Copy` | move errors when "reusing" a `&mut` | It is move-only; reborrow explicitly with `&mut *r` when you need to pass it onward and keep using it. |
| Thinking NLL = no rules | surprised when a later use revives a borrow | A borrow extends to its *last* use, not its last *obvious* use — a later reference (e.g. in a closure) keeps it alive. |
| Needing `&` + mutation legitimately | borrow checker fights a shared-cache / callback pattern | That is exactly interior mutability (`RefCell`/`Mutex`); see 🔗 INTERIOR_MUTABILITY. |

---

## Cheat sheet

```rust
// Shared reference: read-only, MANY allowed, Copy.
let r1: &i32 = &x;
let r2: &i32 = &x;            // fine — many &

// Mutable reference: read+write, EXACTLY ONE, not Copy.
let m: &mut i32 = &mut x;     // needs `let mut x`
*m = 99;                      // mutate THROUGH it

// Borrowing != move: owner stays usable.
let s = String::from("hi");
let r = &s;
println!("{s}");              // s still owned

// Lend a sequence without owning it.
fn sum(slice: &[i32]) -> i32 { slice.iter().sum() }

// Reborrow an existing &mut.
let r: &mut T = &mut x;
work(&mut *r);                // reborrows; r usable again after `work`

// RULE: at any instant — many &T  XOR  one &mut T.  Never both.
// Refs never dangle.  All of the above is proven at COMPILE time.
```

---

## Sources

- The Rust Programming Language, Ch 4.2 "References and Borrowing" (the rules of
  references; mutable-reference restriction; data races; NLL; dangling
  references):
  https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html
- The Rust Reference, "Pointer types → References (`&` and `&mut`)" — shared
  references prevent direct mutation and any number may exist; a mutable
  reference is the sole access path and is not `Copy`; `&mut *` reborrow:
  https://doc.rust-lang.org/reference/types/pointer.html#references--and-mut
- Error codes `E0499`, `E0502`, `E0596`, `E0106` — reproduced verbatim from
  `rustc 1.96.0` (edition 2024); explain text at
  https://doc.rust-lang.org/error_codes/error-index.html
