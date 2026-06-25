//! ffi.rs — Phase 8 bundle.
//!
//! GOAL (one line): show, by printing every value, how Rust crosses the C ABI
//! boundary in BOTH directions — calling foreign C functions (libc `abs` /
//! `strlen`) through an `extern "C"` block, and exporting Rust functions back
//! to C with `#[unsafe(no_mangle)]` + a `#[repr(C)]` data contract.
//!
//! This is the GROUND TRUTH for FFI.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! SAFETY: every `unsafe` block below is trivially sound. The foreign functions
//! are the deterministic libc `abs`/`strlen` (libc/libm are linked by default
//! on every Rust target — see FFI.md Sources), called with in-bounds/valid
//! arguments. The exported Rust function is plain arithmetic. Read the inline
//! `// SAFETY:` comments for each obligation.
//!
//! NOTE (edition 2024): extern blocks are now `unsafe extern "C" { ... }` and
//! the export attribute is now `#[unsafe(no_mangle)]`. The old bare forms are a
//! HARD ERROR in edition 2024 — see FFI.md (Pitfalls) + the edition guide.
//!
//! Run:
//!     just run ffi   (== cargo run --bin ffi)

use std::ffi::CString;
use std::mem::{offset_of, size_of};
use std::os::raw::{c_char, c_int};

const BANNER_WIDTH: usize = 70;

fn banner(title: &str) {
    let bar: String = "=".repeat(BANNER_WIDTH);
    println!("\n{bar}\nSECTION {title}\n{bar}");
}

/// Assert an invariant and print a uniform `[check] ...: OK` line.
/// Panics on failure (non-zero exit) so `just check` / `just sweep` catch it.
fn check(desc: &str, ok: bool) {
    if !ok {
        panic!("INVARIANT VIOLATED: {desc}");
    }
    println!("[check] {desc}: OK");
}

// ── The C ABI contract: foreign functions live in an `unsafe extern` block ──
//
// `extern "C"` declares signatures using the platform's C calling convention
// (the ABI). The block is `unsafe` (edition 2024) because Rust CANNOT verify
// the foreign side's invariants — it only takes our word for the signature.
// On macOS these symbols (`abs`, `strlen`) resolve to libSystem, which Rust
// links against by default (the Rustonomicon: "Rust links against libc and
// libm by default"), so NO `#[link(...)]` attribute is needed.
unsafe extern "C" {
    /// C's `int abs(int)` from <stdlib.h>. Deterministic; valid for any `c_int`.
    fn abs(input: c_int) -> c_int;
    /// C's `size_t strlen(const char *s)` from <string.h>. Requires a valid,
    /// NUL-terminated `*const c_char`; reads bytes until the first `\0`.
    fn strlen(s: *const c_char) -> usize;
}

// ── A Rust function exported BACK to C (callable as a C symbol) ─────────────
//
// `extern "C"` fixes the calling convention so C can call us; `pub` makes the
// symbol visible; `#[unsafe(no_mangle)]` stops Rust's name mangling so the
// linker symbol is exactly `rust_add`. The attribute is UNSAFE (edition 2024)
// because an unmangled name lives in the global symbol namespace — a duplicate
// would be Undefined Behavior, so we alone must guarantee uniqueness.
//
// SAFETY: `rust_add` is the sole definition of this symbol in the binary.
#[unsafe(no_mangle)]
pub extern "C" fn rust_add(a: c_int, b: c_int) -> c_int {
    a + b
}

// ── A Rust callback with the C ABI, passable to C as a function pointer ─────

/// Double an `i32`, exposed with the C ABI so its address can be handed to C
/// as a `int (*)(int)` function pointer. (Defining one is SAFE; only calling
/// a FOREIGN function, or dereferencing a raw pointer, is unsafe.)
extern "C" fn double(x: i32) -> i32 {
    x * 2
}

/// Apply a C-ABI function pointer to an argument. Taking/calling an
/// `extern "C" fn` value is SAFE — function pointers are first-class and the
/// Rust side is fully type-checked. (Contrast: the items declared inside the
/// `unsafe extern "C"` block above are the unsafe-to-call ones.)
fn apply(cb: extern "C" fn(i32) -> i32, x: i32) -> i32 {
    cb(x)
}

// ── A C-layout struct: `#[repr(C)]` pins field order + padding rules ────────

/// With `#[repr(C)]` the layout MATCHES the C ABI: fields are laid out in
/// DECLARATION ORDER with the platform's C padding rules. Without it, Rust's
/// default repr is UNSPECIFIED (it may reorder fields for compactness) and is
/// NOT a stable contract you can send across the FFI boundary.
#[repr(C)]
struct Mixed {
    flag: u8,   // offset 0
    value: u32, // offset 4 (3 bytes of padding after `flag`)
}

// ── Section A: call a foreign C function (libc `abs`) inside `unsafe` ───────

fn section_a() {
    banner("A — call a C function: extern abs, wrapped in unsafe");
    println!("  unsafe extern \"C\" {{ fn abs(input: c_int) -> c_int; }}");
    println!("  (libc is linked by default on every Rust target -> no #[link])");

    // `abs` is declared in the foreign block, so the CALL is unsafe: Rust
    // cannot prove the foreign side's contract. We promise the args are valid.
    let result = unsafe {
        // SAFETY: `abs` accepts any `c_int`; `-7` is a valid signed int. The
        // symbol resolves to libSystem's `abs` (linked by default).
        abs(-7)
    };
    println!("  unsafe {{ abs(-7) }} -> {result}");
    check("foreign C abs(-7) == 7 (libc, deterministic)", result == 7);
}

// ── Section B: pass a Rust string to C as a NUL-terminated *const c_char ────

fn section_b() {
    banner("B — CString -> *const c_char -> C strlen");
    println!("  let cs = CString::new(\"hello\").unwrap();   // owned, NUL-terminated");
    let cs = CString::new("hello").expect("no interior NUL");
    // `cs` MUST outlive the pointer: `as_ptr()` borrows bytes the `CString`
    // owns. Binding `cs` to a local (not a temporary) is the load-bearing rule
    // — `CString::new(...).unwrap().as_ptr()` would dangle instantly (UB).
    let ptr = cs.as_ptr();
    let len = unsafe {
        // SAFETY: `ptr` is a valid, NUL-terminated `*const c_char` (CString's
        // invariant), and `cs` is alive across this call. strlen reads only
        // up to the first `\0` ("hello\0" -> 5 bytes).
        strlen(ptr)
    };
    println!("  cs.as_ptr() -> *const c_char;  unsafe {{ strlen(ptr) }} -> {len}");
    check(
        "C strlen(\"hello\") == 5 (excludes the NUL terminator)",
        len == 5,
    );
    check(
        "CString outlives the pointer it handed out",
        cs.to_bytes().len() == 5,
    );
}

// ── Section C: the C type aliases (c_int, c_char) are platform-sized ────────

fn section_c() {
    banner("C — C type aliases: c_int/c_char are platform-sized");
    println!("  use std::os::raw::{{c_int, c_char}};   // std::ffi has them too");
    println!("  size_of::<c_int>()  = {}", size_of::<c_int>());
    println!("  size_of::<c_char>() = {}", size_of::<c_char>());
    println!(
        "  size_of::<usize>()  = {}  (C's size_t on a 64-bit target)",
        size_of::<usize>()
    );
    // c_int is C's `int` -> i32 on this (and most) targets; c_char is C's
    // `char` -> i8 here (signed). These ALIASES, not the raw i32/i8, are what
    // you put in an extern signature, because they track the C compiler.
    check(
        "c_int == i32 on this platform (4 bytes) — true on virtually all targets",
        size_of::<c_int>() == 4 && size_of::<i32>() == 4,
    );
    check(
        "c_char == i8 here (signed char; macOS/Linux/x86) — platform-dependent",
        size_of::<c_char>() == 1,
    );
    check(
        "usize == C's size_t (8 bytes on a 64-bit target)",
        size_of::<usize>() == 8,
    );
}

// ── Section D: a Rust `extern "C" fn` handed to C as a callback ─────────────

fn section_d() {
    banner("D — Rust fn pointer with the C ABI (a callback for C)");
    println!("  extern \"C\" fn double(x: i32) -> i32 {{ x * 2 }}");
    println!("  fn apply(cb: extern \"C\" fn(i32) -> i32, x: i32) -> i32 {{ cb(x) }}");
    let out = apply(double, 5);
    println!("  apply(double, 5) -> {out}");
    check("C-ABI fn pointer applied: double(5) == 10", out == 10);
    println!("  // C would receive `double` as `int (*)(int)`; calling it is SAFE");
    println!("  // (only FOREIGN-fn calls and raw-pointer derefs are unsafe)");
}

// ── Section E: export a Rust fn to C via #[unsafe(no_mangle)] ───────────────

fn section_e() {
    banner("E — export a Rust fn to C: #[unsafe(no_mangle)] pub extern \"C\"");
    println!("  #[unsafe(no_mangle)] pub extern \"C\" fn rust_add(a, b) -> a + b");
    // We can call our own export directly from Rust (it is a normal Rust fn);
    // C would link the unmangled symbol `rust_add`. The edition-2024
    // `unsafe(no_mangle)` stresses that WE guarantee the symbol name is unique.
    let sum = rust_add(2, 3);
    println!("  rust_add(2, 3) -> {sum}   (symbol `rust_add`, callable from C)");
    check(
        "exported rust_add(2, 3) == 5 (also callable directly in Rust)",
        sum == 5,
    );
    println!("  // cbindgen (github.com/mozilla/cbindgen) auto-generates the C");
    println!("  // header:  int32_t rust_add(int32_t a, int32_t b);");
}

// ── Section F: #[repr(C)] fixes the struct layout for the FFI contract ──────

fn section_f() {
    banner("F — #[repr(C)]: a stable, C-compatible struct layout");
    println!("  #[repr(C)] struct Mixed {{ flag: u8, value: u32 }}");
    let flag_off = offset_of!(Mixed, flag);
    let value_off = offset_of!(Mixed, value);
    let size = size_of::<Mixed>();
    println!("  offset_of!(Mixed, flag)  = {flag_off}");
    println!("  offset_of!(Mixed, value) = {value_off}  (3 bytes padding after flag)");
    println!("  size_of::<Mixed>()       = {size}");
    check(
        "repr(C): fields in DECLARATION order (flag@0, value@4)",
        flag_off == 0 && value_off == 4,
    );
    check(
        "repr(C) size = 1 + 3 padding + 4 = 8 bytes (C alignment rules)",
        size == 8,
    );
    println!("  // WITHOUT #[repr(C)] the default Rust repr is UNSPECIFIED:");
    println!("  // it may reorder/repack fields -> NOT a safe FFI contract.");
}

fn main() {
    println!("ffi.rs — Phase 8 bundle (core, stdlib-only).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
