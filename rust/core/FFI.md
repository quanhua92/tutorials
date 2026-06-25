# FFI — Calling C from Rust and Rust from C, Across the ABI Boundary

> **One-line goal:** a **Foreign Function Interface (FFI)** is the bridge across
> the C ABI — you call **foreign** C functions through an `unsafe extern "C"`
> block, hand Rust data to C with `CString`/`*const c_char`, pass Rust callbacks
> as `extern "C" fn` pointers, and **export** Rust functions back to C with
> `#[unsafe(no_mangle)] pub extern "C"` over a `#[repr(C)]` data contract.
>
> **Run:** `just run ffi` (== `cargo run --bin ffi`)
> **Member:** `core` (stdlib-only — no `[dependencies]`; libc/libm are linked
> automatically by every Rust target).
> **Prerequisites:** 🔗 [DROP_UNSAFE](./DROP_UNSAFE.md) — `unsafe` is the
> foundation: every foreign call lives inside an `unsafe` block because the
> compiler cannot prove the C side's contract. 🔗 [STRINGS_STR](./STRINGS_STR.md)
> — `CString`/`CStr` are the NUL-terminated C-string analogues of `String`/`&str`.
> **Ground truth:** [`ffi.rs`](./ffi.rs); captured stdout:
> [`ffi_output.txt`](./ffi_output.txt).

---

## Why this exists (lineage)

[DROP_UNSAFE](./DROP_UNSAFE.md) showed that `unsafe` unlocks the five operations
the borrow checker cannot prove. **FFI is *the* production reason that escape
hatch exists.** Rust's safety is a *compile-time, single-language* guarantee:
the moment bytes cross into C (or C into Rust), the borrow checker is blind —
it cannot see the C source, cannot verify the C signature, cannot track the C
calling convention. So the boundary is drawn at the **ABI**: both sides agree
on *how arguments are passed* (the C calling convention, `"C"`), *what the types
are* (`c_int`, `c_char`, …), and *who owns what* (a hand-written contract).

Rust's bet is that this boundary is **narrow and explicit**. You pay `unsafe`
only at the seam; everything on the Rust side of the seam stays fully checked.
The Rust Book frames it precisely: an `extern` block is *"a way for a
programming language to define functions and enable a different (foreign)
programming language to call those functions"* and *"functions declared within
`extern` blocks are generally unsafe to call from Rust code, so `extern` blocks
must also be marked `unsafe` … because other languages don't enforce Rust's
rules and guarantees, and Rust can't check them"* ([Book ch20.1][book-unsafe]).

```mermaid
graph TD
    RSIDE["Rust (safe, borrow-checked)"]
    CSIDE["C (libc / your .so / .dylib)"]
    RSIDE -->|"unsafe extern \"C\" { fn abs(..) }<br/>call inside unsafe {}"| CallC["call C's abs/strlen<br/>(libc linked by default)"]
    CSIDE -->|"CString.as_ptr()<br/>*const c_char (NUL-terminated)"| CallC
    CSIDE -->|"C symbol rust_add<br/>(#[unsafe(no_mangle)])"| Export["Rust fn callable from C<br/>crate-type = cdylib/staticlib"]
    Export --> CHeader["cbindgen generates the .h<br/>int32_t rust_add(int32_t, int32_t);"]
    RSIDE -->|"extern \"C\" fn double<br/>(a function pointer)"| Cb["callback handed to C<br/>int (*)(int)"]
    Both["#[repr(C)] struct<br/>field order + padding = C ABI<br/>(default Rust repr is UNSPECIFIED)"]:::core
    CallC --> Both
    Export --> Both
    style RSIDE fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style CallC fill:#fef9e7,stroke:#f1c40f,stroke-width:3px
    style Export fill:#eaf2f8,stroke:#2980b9,stroke-width:2px
    style Both fill:#fdedec,stroke:#c0392b,stroke-width:2px
    classDef core fill:#eafaf1,stroke:#27ae60,stroke-width:3px;
```

> **The one mental model for FFI.** The compiler guarantees safety **up to the
> ABI** and **not one byte past it.** Every signature in an `unsafe extern`
> block is an unverified promise *you* write; every `#[repr(C)]` struct is a
> layout *you* pin; every exported `#[unsafe(no_mangle)]` name is a global
> symbol *you* keep unique. `unsafe` is how you sign each of those promises.

---

## The edition-2024 syntax (read this first)

This crate is **edition 2024**, and FFI syntax changed in two load-bearing
ways. The code below uses the new forms throughout; the bare pre-2024 forms are
now a **hard error**:

| Pre-2024 (now wrong) | Edition 2024 (required) | Why |
|---|---|---|
| `extern "C" { fn f(..); }` | `unsafe extern "C" { fn f(..); }` | the block makes *unverified* claims ([unsafe-extern][ed-unsafe-extern]) |
| `#[no_mangle] pub extern "C" fn g()` | `#[unsafe(no_mangle)] pub extern "C" fn g()` | an unmangled name is a global symbol — a duplicate is UB ([unsafe-attributes][ed-unsafe-attr]) |

---

## Section A — Calling a C function: `extern abs`, wrapped in `unsafe`

The minimal FFI: declare C's `abs` (from `<stdlib.h>`) in an `unsafe extern "C"`
block, then call it inside `unsafe {}`.

```rust
use std::os::raw::c_int;

unsafe extern "C" {
    fn abs(input: c_int) -> c_int;   // C's `int abs(int)`
}

fn main() {
    let result = unsafe { abs(-7) };  // 7
}
```

> **From ffi.rs Section A:**
> ```
> ======================================================================
> SECTION A — call a C function: extern abs, wrapped in unsafe
> ======================================================================
>   unsafe extern "C" { fn abs(input: c_int) -> c_int; }
>   (libc is linked by default on every Rust target -> no #[link])
>   unsafe { abs(-7) } -> 7
> [check] foreign C abs(-7) == 7 (libc, deterministic): OK
> ```

**What.** `unsafe { abs(-7) }` returns `7` — the C library's absolute-value
function, called from Rust. No `#[link(...)]` attribute is needed.

**Why (internals).**
- **The C ABI.** `"C"` selects the platform's C calling convention — *how*
  arguments are passed in registers/stack, who cleans up, etc. The Rust
  Reference lists the full set (`"stdcall"`, `"system"`, `"C-unwind"`, …); the
  Nomicon notes *"most foreign code exposes a C ABI, and Rust uses the
  platform's C calling convention by default"* ([Nomicon — FFI][nomicon-ffi]).
- **Why `unsafe`?** Rust cannot read `<stdlib.h>`; it only has *your* signature.
  If you lied (wrong arg count, wrong type, wrong ABI), the call is Undefined
  Behavior. The Book: *"the Rust compiler cannot check if the declaration is
  correct, so specifying it correctly is part of keeping the binding correct at
  runtime"* ([Book ch20.1][book-unsafe]). The `unsafe` block is the promise
  that *you* checked.
- **Why no `#[link]`?** The Nomicon is explicit: *"Rust links against `libc`
  and `libm` by default"* ([Nomicon — FFI][nomicon-ffi]). On macOS `abs` and
  `strlen` live in `libSystem`; on Linux in `libc`/`libm`. You only need
  `#[link(name = "...")]` for libraries that are *not* the C runtime (e.g.
  snappy, readline, a framework).
- **`safe fn` opt-in.** Because `abs` has no memory-safety considerations, the
  Book shows you may write `safe fn abs(..)` inside the block to call it
  *without* `unsafe` ([Book ch20.1][book-unsafe]) — but that removes a useful
  speed bump, so this bundle keeps the call `unsafe`.

---

## Section B — Handing a Rust string to C: `CString` → `*const c_char`

C strings are **NUL-terminated byte arrays**; Rust strings (`String`/`&str`)
are **length-prefixed and may contain interior `\0`**. `CString` is the bridge:
it owns a heap buffer guaranteed to have **no interior NUL** and a **trailing
`\0`**, and `.as_ptr()` lends it to C as `*const c_char`.

```rust
use std::ffi::CString;
use std::os::raw::c_char;

unsafe extern "C" {
    fn strlen(s: *const c_char) -> usize;   // C's `size_t strlen(const char*)`
}

let cs = CString::new("hello").unwrap();   // "hello\0", owned by cs
let ptr = cs.as_ptr();                      // *const c_char (a borrow of cs!)
let n = unsafe { strlen(ptr) };             // 5 — strlen stops at the first \0
```

> **From ffi.rs Section B:**
> ```
> ======================================================================
> SECTION B — CString -> *const c_char -> C strlen
> ======================================================================
>   let cs = CString::new("hello").unwrap();   // owned, NUL-terminated
>   cs.as_ptr() -> *const c_char;  unsafe { strlen(ptr) } -> 5
> [check] C strlen("hello") == 5 (excludes the NUL terminator): OK
> [check] CString outlives the pointer it handed out: OK
> ```

**What.** `strlen` returns `5` for `"hello"` — it counts bytes **up to, but not
including**, the `\0`. The second check confirms the `CString` is still alive
(`to_bytes().len() == 5`) after the call.

**Why (internals).**
- **`CString` is to `CStr` as `String` is to `&str`.** `CString` is the
  *owned, growable* form (it allocates the NUL-terminated buffer); `CStr` is the
  *borrowed* view. The docs: *"A type representing an owned, C-compatible,
  nul-terminated string with no nul bytes in the middle"* ([std::ffi::CString][std-cstring]).
  🔗 [STRINGS_STR](./STRINGS_STR.md) for the owned/borrowed split in general.
- **`as_ptr()` is a *borrow*, not a move.** The pointer aliases bytes the
  `CString` still owns; the `CString` **must outlive** every use of the pointer.
  This is exactly why the code binds `cs` to a local *first*, then takes its
  pointer — the classic footgun is `CString::new(x).unwrap().as_ptr()`, where
  the temporary is dropped at the `;` and the pointer dangles instantly. The
  std docs devote a whole **WARNING** block to this: it is *immediate Undefined
  Behavior* ([std::ffi::CString — as_ptr][std-cstring]).
- **`CString::new` returns `Result`.** It *fails* on an interior NUL byte
  (`NulError`), because a `\0` in the middle would truncate the string from C's
  perspective. That check is the whole point of the type.
- **`as_ptr` is read-only.** If C writes through the pointer, that's UB. To hand
  C a *mutable* buffer you'd manage ownership yourself (`into_raw`/`from_raw`).

---

## Section C — The C type aliases: `c_int`, `c_char`, … are platform-sized

Never put `i32` directly in an `extern` signature for a C `int`. Use the
**alias** `std::os::raw::c_int` (`= core::ffi::c_int`), which tracks whatever
the C compiler calls `int` on the target.

```rust
use std::os::raw::{c_char, c_int};
use std::mem::size_of;

size_of::<c_int>()   // 4 on virtually all targets (== i32)
size_of::<c_char>()  // 1 (signed i8 here; unsigned u8 on ARM)
size_of::<usize>()   // 8 (== C's size_t on a 64-bit target)
```

> **From ffi.rs Section C:**
> ```
> ======================================================================
> SECTION C — C type aliases: c_int/c_char are platform-sized
> ======================================================================
>   use std::os::raw::{c_int, c_char};   // std::ffi has them too
>   size_of::<c_int>()  = 4
>   size_of::<c_char>() = 1
>   size_of::<usize>()  = 8  (C's size_t on a 64-bit target)
> [check] c_int == i32 on this platform (4 bytes) — true on virtually all targets: OK
> [check] c_char == i8 here (signed char; macOS/Linux/x86) — platform-dependent: OK
> [check] usize == C's size_t (8 bytes on a 64-bit target): OK
> ```

**What.** On this target (macOS, 64-bit), `c_int` is 4 bytes (`i32`), `c_char`
is 1 byte (signed `i8`), and `usize` is 8 bytes (`size_t`). Three checks pin
those sizes.

**Why (internals).**
- **The aliases exist *because* the C types vary.** `c_int` is *"equivalent to
  C's `signed int` (`int`) type"* but its *bit width* follows the platform's C
  ABI ([std::os::raw][std-raw]). `c_char` is the sharpest example: it is `i8`
  on x86/macOS/Linux (signed `char`) but `u8` on ARM (unsigned `char`). Writing
  `i8` literally in a signature would be *wrong* on ARM.
- **The full set** (in `std::os::raw` / `core::ffi`): `c_int`, `c_uint`,
  `c_long`, `c_ulong`, `c_longlong`, `c_ulonglong`, `c_short`, `c_ushort`,
  `c_char`, `c_schar`, `c_uchar`, `c_float`, `c_double`, `c_void` — one alias
  per C primitive ([std::os::raw][std-raw]).
- **`usize` ↔ `size_t`.** C's `size_t` (the return of `strlen`, the arg of
  `malloc`) maps to Rust `usize` by definition. `c_void` maps `void *` (only
  valid behind a pointer).

---

## Section D — A Rust callback: `extern "C" fn` handed to C

Some C APIs take a **function pointer** (a callback). A Rust function marked
`extern "C" fn` has the C calling convention, so its *address* can be passed to
C as an `int (*)(int)`.

```rust
extern "C" fn double(x: i32) -> i32 { x * 2 }

fn apply(cb: extern "C" fn(i32) -> i32, x: i32) -> i32 { cb(x) }

let out = apply(double, 5);   // 10
```

> **From ffi.rs Section D:**
> ```
> ======================================================================
> SECTION D — Rust fn pointer with the C ABI (a callback for C)
> ======================================================================
>   extern "C" fn double(x: i32) -> i32 { x * 2 }
>   fn apply(cb: extern "C" fn(i32) -> i32, x: i32) -> i32 { cb(x) }
>   apply(double, 5) -> 10
> [check] C-ABI fn pointer applied: double(5) == 10: OK
>   // C would receive `double` as `int (*)(int)`; calling it is SAFE
>   // (only FOREIGN-fn calls and raw-pointer derefs are unsafe)
> ```

**What.** `apply(double, 5)` returns `10`. Note: **no `unsafe` anywhere.**

**Why (internals).**
- **Defining an `extern "C" fn` is SAFE; only calling a *foreign* one is
  unsafe.** `double` is a normal Rust function that merely *happens* to use the
  C calling convention — its body is fully type-checked by Rust, so calling it
  (directly or through a function-pointer value) needs no `unsafe`. The Nomicon:
  *"the callback function is marked as `extern` with the correct calling
  convention to make it callable from C code"* ([Nomicon — Callbacks][nomicon-ffi]).
- **The asymmetry to remember.** The *items* declared inside an
  `unsafe extern "C" { }` block are unsafe to call (Rust didn't compile them).
  The *values* of type `extern "C" fn(...)` that *Rust itself defined* are safe
  to call. This is why Section A needs `unsafe {}` but Section D does not.
- **Nullable callbacks via `Option`.** A C API that accepts `NULL` for "no
  callback" maps to `Option<extern "C" fn(...) -> ...>`: `None` is the null
  pointer, via the guaranteed *nullable-pointer optimization*
  ([Nomicon — nullable pointer optimization][nomicon-ffi]). No `transmute` needed.

---

## Section E — Exporting a Rust function to C: `#[unsafe(no_mangle)]`

To let **C call Rust**, do the reverse: give the function the C ABI (`extern
"C"`), make it `pub`, and stop the compiler from mangling its name so the
linker symbol is predictable.

```rust
#[unsafe(no_mangle)]
pub extern "C" fn rust_add(a: c_int, b: c_int) -> c_int { a + b }
```

> **From ffi.rs Section E:**
> ```
> ======================================================================
> SECTION E — export a Rust fn to C: #[unsafe(no_mangle)] pub extern "C"
> ======================================================================
>   #[unsafe(no_mangle)] pub extern "C" fn rust_add(a, b) -> a + b
>   rust_add(2, 3) -> 5   (symbol `rust_add`, callable from C)
> [check] exported rust_add(2, 3) == 5 (also callable directly in Rust): OK
>   // cbindgen (github.com/mozilla/cbindgen) auto-generates the C
>   // header:  int32_t rust_add(int32_t a, int32_t b);
> ```

**What.** `rust_add(2, 3)` returns `5`. From Rust's side it is an ordinary
function; from the linker's side there is now a global symbol literally named
`rust_add`, which C can declare and call.

**Why (internals).**
- **`extern "C"`** fixes the calling convention so C can call *into* us
  correctly — the mirror image of Section A. *"The `extern "C"` makes this
  function adhere to the C calling convention"* ([Nomicon — Calling Rust from
  C][nomicon-ffi]).
- **`#[unsafe(no_mangle)]`** turns off name mangling. Rust normally encodes
  types/generics into the symbol (`_ZN3foo...`); for C to find the symbol by a
  plain name, mangling must be off. The Book: *"Mangling is when a compiler
  changes the name … for a Rust function to be nameable by other languages, we
  must disable the Rust compiler's name mangling"* ([Book ch20.1][book-unsafe]).
- **Why *unsafe*?** An unmangled name lives in the **global** symbol namespace.
  Two `#[no_mangle] fn malloc` across crates is a linker collision (or silent
  UB). The edition-2024 `unsafe(...)` makes you *assert* the name is unique:
  *"there might be name collisions across libraries without the built-in
  mangling, so it is our responsibility to make sure the name we choose is safe
  to export"* ([Book ch20.1][book-unsafe]; [edition guide][ed-unsafe-attr]).
  This is exactly why this bundle names it `rust_add`, not the risky bare `add`.
- **To build a callable library**, set `crate-type = ["cdylib"]` (a shared
  `.so`/`.dylib`/`.dll`) or `["staticlib"]` (a `.a`) in `Cargo.toml`'s `[lib]`,
  then link from C (`gcc main.c -lrust_add -L...`) — see the Nomicon's worked
  flow ([Nomicon — C side][nomicon-ffi]).
- **Generating the header by hand is error-prone — use `cbindgen`.** It scans
  your `#[repr(C)]`/`#[unsafe(no_mangle)] pub extern "C"` items and emits the
  matching `.h` automatically ([cbindgen on GitHub][cbindgen]).

---

## Section F — `#[repr(C)]`: a stable, C-compatible struct layout

A `struct` that crosses the FFI boundary **must** have the C layout. The default
Rust representation is **unspecified** — the compiler may reorder fields for
compactness. `#[repr(C)]` pins field order and applies the platform's C padding
rules, so bytes line up with what C expects.

```rust
#[repr(C)]
struct Mixed { flag: u8, value: u32 }   // flag@0, value@4, size 8

std::mem::offset_of!(Mixed, flag)   // 0
std::mem::offset_of!(Mixed, value)  // 4  (3 bytes padding after `flag`)
std::mem::size_of::<Mixed>()        // 8
```

> **From ffi.rs Section F:**
> ```
> ======================================================================
> SECTION F — #[repr(C)]: a stable, C-compatible struct layout
> ======================================================================
>   #[repr(C)] struct Mixed { flag: u8, value: u32 }
>   offset_of!(Mixed, flag)  = 0
>   offset_of!(Mixed, value) = 4  (3 bytes padding after flag)
>   size_of::<Mixed>()       = 8
> [check] repr(C): fields in DECLARATION order (flag@0, value@4): OK
> [check] repr(C) size = 1 + 3 padding + 4 = 8 bytes (C alignment rules): OK
>   // WITHOUT #[repr(C)] the default Rust repr is UNSPECIFIED:
>   // it may reorder/repack fields -> NOT a safe FFI contract.
> ```

**What.** With `#[repr(C)]`, `flag` sits at offset `0`, `value` at offset `4`
(3 bytes of padding inserted so `value` is 4-byte aligned), total size `8`.

**Why (internals).**
- **Fields in declaration order.** `repr(C)` forbids reordering: `flag` first,
  then `value`, matching the C `struct { u8 flag; u32 value; }` exactly. The
  Nomicon: *"Rust guarantees that the layout of a `struct` is compatible with
  the platform's representation in C only if the `#[repr(C)]` attribute is
  applied to it"* ([Nomicon — Interoperability][nomicon-ffi]).
- **C padding/alignment rules apply.** A `u32` needs 4-byte alignment, so after
  a `u8` field the compiler inserts 3 padding bytes. `size_of` and `offset_of!`
  expose this deterministic layout — `offset_of!` is stable since Rust 1.77.
- **Default repr is NOT a contract.** Without `repr(C)`, Rust may reorder
  fields (e.g. put `value` first to drop the padding) or repack; the layout can
  even change between compiler versions. Sending a default-repr struct across
  the FFI boundary is therefore **Undefined Behavior** waiting to happen.
  - `#[repr(C, packed)]` removes the padding (dangerous: unaligned access).
  - **Opaque types** (C hands you a pointer you must not inspect) are modelled
    with a `#[repr(C)]` struct of `()` + `PhantomData<(*mut u8, PhantomPinned)>`
    so it can't be constructed, nor be `Send`/`Sync` ([Nomicon — opaque][nomicon-ffi]).
- **Don't use an empty enum for opaque.** An empty enum is *uninhabited*; taking
  a reference to one is UB. Use the struct-with-`PhantomData` pattern instead.

---

## Pitfalls (the expert payoff)

| Trap | Symptom | Fix / why |
|---|---|---|
| **`CString::new(x).unwrap().as_ptr()`** | dangling pointer → instant UB, often a crash/garbage much later | Bind the `CString` to a local *first*: `let cs = CString::new(x)?; let p = cs.as_ptr();` Keep `cs` alive across every use of `p`. ([CString as_ptr WARNING][std-cstring]) |
| **Interior NUL in a `CString`** | `CString::new` returns `Err(NulError)` (C would see a truncated string) | Expected — that check is the type's purpose. Sanitize input or use `from_vec_unchecked` only inside `unsafe` with a proven guarantee. |
| **C writes through `as_ptr()`** | silent heap corruption / UB | `as_ptr` is **read-only**. For a mutable buffer use `into_raw`/`from_raw` (and reclaim with `from_raw`, never C `free`). |
| **`#[no_mangle]` / `#[export_name]` bare in edition 2024** | hard error `unsafe_attr_outside_unsafe` | Write `#[unsafe(no_mangle)]`. The edition guide makes it mandatory because duplicate global symbols are UB ([edition guide][ed-unsafe-attr]). |
| **Bare `extern "C" { }` in edition 2024** | hard error: extern block must be `unsafe` | Write `unsafe extern "C" { }`. Items inside are implicitly unsafe to call ([unsafe-extern][ed-unsafe-extern]). |
| **Using `i32` for C's `int`** | works on x86, **miscompiles on ARM** where `c_int` differs | Always use the aliases `c_int`/`c_char`/`size_t`=usize in `extern` signatures ([std::os::raw][std-raw]). |
| **Sending a default-repr struct across FFI** | field reorder/repack → C reads garbage offsets | Add `#[repr(C)]`. Only `repr(C)` is a layout the compiler guarantees ([Nomicon — Interoperability][nomicon-ffi]). |
| **A `panic` unwinding across the C boundary** | UB (a foreign exception entering Rust) or forced abort | Use `"C-unwind"`/`extern "C-unwind"` if you expect panics to cross, or `catch_unwind` to stop them at the seam ([Nomicon — FFI unwinding][nomicon-ffi]). |
| **Forgetting `crate-type = ["cdylib"]`** | C can't link your Rust functions; symbol missing | Exports need a library crate type. A plain `[[bin]]` (like this bundle) defines the symbol but isn't a linkable library. |
| **Reading the `extern` signature wrong** | wrong arg count/type/ABI → UB, often a subtle crash | The signature is *your unverified claim*. Mirror the C header exactly; prefer `cbindgen` both ways to stay honest. |
| **Calling a foreign fn outside `unsafe {}`** | `E0133: call to unsafe function is unsafe` | Every item in an `unsafe extern` block is unsafe to call — wrap the call, or mark the item `safe` only after proving it. |

---

## Cheat sheet

```rust
use std::ffi::CString;
use std::os::raw::{c_char, c_int};          // C type aliases (platform-sized)

// ── Rust → C: declare foreign fns in an UNSAFE extern block (edition 2024) ─
unsafe extern "C" {
    fn abs(input: c_int) -> c_int;           // libc, linked by default
    fn strlen(s: *const c_char) -> usize;    // needs a valid NUL-terminated ptr
}
let r = unsafe { abs(-7) };                  // 7  (call must be in unsafe{})

// ── Strings: CString owns "...\0"; as_ptr() BORROWS it (keep cs alive!) ────
let cs = CString::new("hello").unwrap();     // NOT: CString::new(x).unwrap().as_ptr()
let n = unsafe { strlen(cs.as_ptr()) };      // 5

// ── Callback: a Rust fn with the C ABI, safe to define & call ──────────────
extern "C" fn double(x: i32) -> i32 { x * 2 }
fn apply(cb: extern "C" fn(i32) -> i32, x: i32) -> i32 { cb(x) }
apply(double, 5);                            // 10, NO unsafe (Rust-defined)

// ── Rust ← C: export an unmangled C-ABI symbol (edition 2024: unsafe attr) ─
#[unsafe(no_mangle)]                         // assert the name is globally unique
pub extern "C" fn rust_add(a: c_int, b: c_int) -> c_int { a + b }
// build as crate-type = ["cdylib"]; cbindgen -> int32_t rust_add(int32_t, int32_t);

// ── Data contract: #[repr(C)] pins field order + C padding (default = UB) ──
#[repr(C)]
struct Mixed { flag: u8, value: u32 }        // flag@0, value@4 (3 pad), size 8
// offset_of!(Mixed, value) == 4   (stable since 1.77)
```

---

## Sources

Every claim above was web-verified in at least two authoritative places.

- **The Rust Programming Language, ch20.1 "Unsafe Rust"** — the `extern`
  function section: declaring C's `abs`, the `unsafe extern` block, marking an
  item `safe`, `#[unsafe(no_mangle)]` export and *why* it's unsafe, the ABI:
  https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html
- **The Rustonomicon — "Foreign Function Interface"** — calling foreign
  functions, *"Rust links against `libc` and `libm` by default"*, callbacks
  (Rust fn as C function pointer), the nullable-pointer optimization / `Option`
  callbacks, calling Rust from C (`extern "C"` + `#[no_mangle]` + `cdylib`),
  `#[repr(C)]` interoperability, opaque types, FFI unwinding (`"C-unwind"`):
  https://doc.rust-lang.org/nomicon/ffi.html
- **`std::os::raw` module docs** — the C type aliases (`c_int` = "equivalent
  to C's `signed int`", `c_char`, `c_void`, …) and the note to prefer
  `core::ffi`:
  https://doc.rust-lang.org/std/os/raw/index.html
- **`std::ffi::CString` docs** — owned NUL-terminated string, `CString`↔`CStr`
  is `String`↔`&str`, `as_ptr()` returns `*const c_char` and is **read-only**,
  the dangling-pointer-from-a-temporary WARNING, `into_raw`/`from_raw`:
  https://doc.rust-lang.org/std/ffi/struct.CString.html
- **The Rust Edition Guide — "Unsafe attributes" (Rust 2024)** — `no_mangle`,
  `export_name`, `link_section` must now be `#[unsafe(...)]`; a duplicate
  global symbol is UB; the `unsafe_attr_outside_unsafe` lint:
  https://doc.rust-lang.org/edition-guide/rust-2024/unsafe-attributes.html
- **The Rust Edition Guide — "Unsafe `extern` blocks" (Rust 2024)** — `extern`
  blocks must be `unsafe extern`; individual items may be marked `safe`:
  https://doc.rust-lang.org/edition-guide/rust-2024/unsafe-extern.html
- **RFC 3325 — "Unsafe attributes"** — the rationale that `no_mangle` etc. can
  cause UB without any `unsafe` block, motivating the `unsafe(...)` form:
  https://rust-lang.github.io/rfcs/3325-unsafe-attributes.html
- **The Rust Reference — Type layout / Representations** — `#[repr(C)]` layout
  guarantees vs. the unspecified default repr:
  https://doc.rust-lang.org/reference/type-layout.html
- **`cbindgen` (Mozilla)** — generates C/C++ headers from Rust
  `#[repr(C)]`/`#[unsafe(no_mangle)] pub extern "C"` items:
  https://github.com/mozilla/cbindgen
