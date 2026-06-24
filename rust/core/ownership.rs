//! ownership.rs — Phase 1 bundle #1 (STYLE ANCHOR).
//!
//! GOAL (one line): show, by printing every value, that each Rust value has
//! exactly ONE owner, that assigning/passing/returning a non-Copy value MOVES
//! that ownership (invalidating the source), and that the owner dropping at end
//! of scope runs `Drop` deterministically, exactly once.
//!
//! This is the GROUND TRUTH for OWNERSHIP.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Several ownership rules are COMPILE ERRORS (e.g. using a value after it was
//! moved). Those cannot live in a runnable file — this binary would not build.
//! They are documented in OWNERSHIP.md with the exact compiler message.
//!
//! Run:
//!     just run ownership   (== cargo run --bin ownership)

use std::cell::Cell;

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

/// A tiny RAII sentinel: it prints and bumps a shared counter when dropped, so
/// the *timing and count* of drops become observable. It holds a shared `&Cell`
/// (interior mutability through a shared reference) so two sentinels can share
/// one counter without `mut`. It implements `Drop`, so it is NOT `Copy`.
struct Sentinel<'a> {
    name: &'static str,
    drops: &'a Cell<u32>,
}

impl Drop for Sentinel<'_> {
    fn drop(&mut self) {
        self.drops.set(self.drops.get() + 1);
        println!("    (drop fires: {})", self.name);
    }
}

// ── Section A: move on assign — the source binding is invalidated ───────────

fn section_a() {
    banner("A — move on assign: the source is INVALIDATED");
    let s1 = String::from("hello");
    let len_before = s1.len();
    let cap_before = s1.capacity();
    println!(
        "  let s1 = String::from(\"hello\");   s1.len={}, s1.cap={}",
        len_before, cap_before
    );

    // `let s2 = s1;` MOVES ownership of the heap buffer from s1 to s2. The
    // {ptr,len,cap} handle is copied bitwise; the heap bytes are NOT. From here
    // on s1 is poisoned — referencing it is a compile error (see OWNERSHIP.md).
    let s2 = s1;
    println!("  let s2 = s1;   // ownership MOVES -> s1 is now unusable");
    println!(
        "                  s2 = {:?}, s2.len={}, s2.cap={}",
        s2,
        s2.len(),
        s2.capacity()
    );

    check(
        "moved String's new owner has the SAME len as the original",
        s2.len() == len_before,
    );
    check(
        "moved String's new owner has the SAME cap as the original",
        s2.capacity() == cap_before,
    );

    // `.clone()` is the explicit DEEP copy: the heap buffer is duplicated, so
    // BOTH bindings stay valid and independently usable.
    let c1 = String::from("rust");
    let c2 = c1.clone();
    println!("  let c1 = String::from(\"rust\");  let c2 = c1.clone();");
    println!("    c1 = {:?}, c2 = {:?}  (both usable)", c1, c2);
    check(
        ".clone() deep-copies: source AND clone stay usable and equal",
        c1 == "rust" && c2 == "rust",
    );
}

// ── Section B: move into a function; borrow to use without owning ───────────

/// Takes a `String` BY VALUE — ownership moves in, and the value is dropped at
/// the end of this function (the caller may not use its binding afterwards).
fn takes_string(s: String) -> usize {
    println!(
        "    [inside takes_string] received {:?} (len {})",
        s,
        s.len()
    );
    s.len()
}

/// Takes a `&str` (borrow) — NO ownership moves, so the caller keeps its value.
/// (`&str` over `&String` is the idiomatic signature; see OWNERSHIP.md.)
fn len_of(s: &str) -> usize {
    s.len()
}

fn section_b() {
    banner("B — move into a function; borrow to use without owning");
    // Passing by value = a move, identical in mechanics to `let s2 = s1`.
    let s = String::from("hello");
    let n = takes_string(s);
    println!(
        "  takes_string(s) -> {}  (s moved away; unusable in caller)",
        n
    );
    check(
        "value moved into fn is dropped there; its length returns via the return value",
        n == 5,
    );

    // Option 1 to keep using it: clone before the move.
    let s2 = String::from("world");
    let n2 = takes_string(s2.clone());
    println!(
        "  takes_string(s2.clone()) -> {}  (caller keeps s2 = {:?})",
        n2, s2
    );
    check(
        "clone first: caller keeps a usable, equal copy after the call",
        s2 == "world" && n2 == 5,
    );

    // Option 2 (cheaper, no copy): pass a reference. -> see BORROWING bundle.
    let s3 = String::from("rust");
    let n3 = len_of(&s3);
    println!(
        "  len_of(&s3) -> {}  (s3 still owned by caller: {:?})",
        n3, s3
    );
    check(
        "borrowing (&) does NOT move; caller retains ownership and value",
        s3 == "rust" && n3 == 4,
    );
}

// ── Section C: drop at scope end — RAII, deterministic, exactly once ────────

fn section_c() {
    banner("C — drop at scope end: RAII, deterministic, exactly once");
    let drops = Cell::new(0u32);
    {
        // Named bindings (even with a leading `_`) live until the closing `}`.
        let _a = Sentinel {
            name: "alpha",
            drops: &drops,
        };
        let _b = Sentinel {
            name: "bravo",
            drops: &drops,
        };
        println!(
            "  created alpha, then bravo  (drops so far: {})",
            drops.get()
        );
        check(
            "no Drop runs while the owners are still in scope",
            drops.get() == 0,
        );
    } // <- `}` fires drop glue: bravo FIRST, then alpha (reverse declaration order)
    println!("  after block closed: total drops = {}", drops.get());
    check(
        "both sentinels dropped exactly once, at scope end",
        drops.get() == 2,
    );
}

// ── Section D: std::mem::drop forces an EARLY drop; reassign drops old value ─

fn section_d() {
    banner("D — std::mem::drop forces an EARLY drop; reassign drops the old value");

    // std::mem::drop(x) simply moves x into `fn drop<T>(_x: T){}`; _x then drops
    // at the function's end — i.e. immediately, at the call site.
    let drops = Cell::new(0u32);
    {
        let _x = Sentinel {
            name: "xray",
            drops: &drops,
        };
        println!("  created xray  (drops: {})", drops.get());
        std::mem::drop(_x);
        println!(
            "  after std::mem::drop(_x): drops = {}  (dropped NOW, before block end)",
            drops.get()
        );
        check(
            "std::mem::drop drops the value immediately, not at scope end",
            drops.get() == 1,
        );
    }
    check(
        "no double-drop: an early-dropped value is not dropped again at scope end",
        drops.get() == 1,
    );

    // Assigning a NEW value to an existing binding drops the OLD value at once.
    let drops2 = Cell::new(0u32);
    {
        let mut s = Sentinel {
            name: "first",
            drops: &drops2,
        };
        println!("  created '{}'  (drops: {})", s.name, drops2.get());
        s = Sentinel {
            name: "second",
            drops: &drops2,
        }; // 'first' drops HERE
        println!(
            "  after `s = Sentinel{{second}}`: drops = {}  (current owner = '{}')",
            drops2.get(),
            s.name
        );
        check(
            "reassigning a binding drops the old value immediately",
            drops2.get() == 1,
        );
    } // 'second' drops now
    check(
        "'second' then drops at scope end (total 2)",
        drops2.get() == 2,
    );
}

// ── Section E: a move is a SHALLOW bitwise copy of the handle (O(1)) ─────────

fn section_e() {
    banner("E — a move is a SHALLOW bitwise copy of the handle (O(1))");
    let s1 = String::from("hello, rust");
    let handle_bytes = std::mem::size_of_val(&s1);
    let len1 = s1.len();
    let cap1 = s1.capacity();
    println!("  let s1 = String::from(\"hello, rust\");");
    println!(
        "    handle size = size_of_val(&s1) = {} bytes",
        handle_bytes
    );
    println!("    s1.len = {}, s1.cap = {}", len1, cap1);

    // Bitwise copy of the {ptr,len,cap} handle ONLY; the heap bytes are shared
    // (then s1 is poisoned so there is still exactly one owner). O(1).
    let s2 = s1;
    println!("  let s2 = s1;  // handle copied bitwise; heap NOT copied; s1 poisoned");
    println!("    s2.len = {}, s2.cap = {}", s2.len(), s2.capacity());

    check(
        "String handle = ptr(8)+len(8)+cap(8) = 24 bytes on a 64-bit target",
        handle_bytes == 24,
    );
    check(
        "shallow move preserves len across the move",
        len1 == s2.len(),
    );
    check(
        "shallow move preserves cap across the move",
        cap1 == s2.capacity(),
    );

    // The handle size is CONSTANT regardless of heap size — that is why a move
    // is O(1): it copies a fixed 24-byte handle, never the heap payload.
    let big = String::from("0123456789").repeat(1000); // 10_000 bytes on heap
    let big_handle = std::mem::size_of_val(&big);
    println!(
        "  big = ...repeat(1000) -> {} bytes of heap text; handle still {} bytes",
        big.len(),
        big_handle
    );
    check(
        "handle size is constant: a 10000-byte String still has a 24-byte handle",
        big_handle == 24 && big.len() == 10000,
    );
    check(
        "moving `big` is O(1): only the 24-byte handle copies, never the 10000 heap bytes",
        std::mem::size_of_val(&big) == 24,
    );
}

fn main() {
    println!("ownership.rs — Phase 1 bundle #1 (style anchor).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    banner("DONE — all sections printed");
}
