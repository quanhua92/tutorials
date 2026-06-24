//! vec_collections.rs — Phase 1 bundle #7 (Vec<T> + &[T]).
//!
//! GOAL (one line): show, by printing every value, that a `Vec<T>` owns a
//! growable heap buffer described by the triple `{ptr, len, capacity}`, that
//! `push` grows it with amortized-O(1) doubling reallocs, and that a slice
//! `&[T]` is merely a *borrowed fat-pointer view* of contiguous `T`s that a
//! `&Vec` deref-coerces into for free.
//!
//! This is the GROUND TRUTH for VEC_COLLECTIONS.md. Every number, table, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Two things CANNOT live here because they would not compile or would abort:
//!   - the out-of-bounds panic itself is caught with `catch_unwind` so the run
//!     continues (and the exact panic payload is asserted);
//!   - the alias trap (holding `&v[0]` across `v.push`) is a COMPILE error
//!     (E0502); it is documented in VEC_COLLECTIONS.md with the exact message.
//!
//! Run:
//!     just run vec_collections   (== cargo run --bin vec_collections)

use std::panic::AssertUnwindSafe;

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

/// Takes a `&[i32]` slice — a borrowed view. A `&Vec<i32>` argument deref-coerces
/// to this type at the call site (see Section D), so this signature is strictly
/// more general than `&Vec<i32>` and is the idiomatic choice.
fn sum_slice(s: &[i32]) -> i32 {
    s.iter().sum()
}

// ── Section A: create — Vec::new (no alloc) vs with_capacity (pre-alloc) ─────

fn section_a() {
    banner("A — create: Vec::new (no alloc) vs with_capacity (pre-alloc)");
    // Vec::new() builds the {ptr,len,cap} handle but allocates NO heap memory:
    // capacity is 0. The first push triggers the very first allocation.
    let empty: Vec<i32> = Vec::new();
    println!("  let empty: Vec<i32> = Vec::new();");
    println!(
        "    empty.len = {}, empty.capacity = {}  (no allocation yet)",
        empty.len(),
        empty.capacity()
    );
    check(
        "Vec::new() allocates nothing until the first push: len == 0 AND capacity == 0",
        empty.is_empty() && empty.capacity() == 0,
    );

    // with_capacity(n) pre-allocates room for AT LEAST n elements (the allocator
    // may hand back more). Length stays 0; only capacity is >= n.
    let pre: Vec<i32> = Vec::with_capacity(3);
    println!("  let pre = Vec::with_capacity(3);");
    println!(
        "    pre.len = {}, pre.capacity = {}  (capacity >= requested)",
        pre.len(),
        pre.capacity()
    );
    check(
        "with_capacity(3): length is 0 but capacity >= 3",
        pre.is_empty() && pre.capacity() >= 3,
    );

    // Pushing FEWER than `capacity` elements triggers no reallocation at all.
    let mut filled = Vec::with_capacity(3);
    let cap_before = filled.capacity();
    filled.push(1);
    filled.push(2);
    filled.push(3);
    println!(
        "  push 1, 2, 3 into with_capacity(3): len = {}, capacity = {}",
        filled.len(),
        filled.capacity()
    );
    check(
        "3 pushes fit within the pre-allocated capacity: capacity UNCHANGED (no realloc)",
        filled.len() == 3 && filled.capacity() == cap_before,
    );
}

// ── Section B: push — amortized O(1) via capacity doubling on realloc ───────

fn section_b() {
    banner("B — push: amortized O(1) via capacity doubling on realloc");
    // Start from an empty Vec and push one element at a time, recording the
    // capacity after each push. When len == capacity, the next push reallocates:
    // a bigger buffer is allocated, the elements are MOVED over, and capacity
    // grows (the current strategy doubles it). Because each realloc is O(n) but
    // happens only every O(n) pushes, push is amortized O(1).
    let mut v: Vec<i32> = Vec::new();
    let mut caps: Vec<usize> = Vec::new();
    println!("  let mut v: Vec<i32> = Vec::new();  (len = 0, capacity = 0)");
    for i in 1..=5 {
        v.push(i);
        caps.push(v.capacity());
    }
    println!("  push 1..=5, recording capacity after each push:");
    println!("    capacities = {:?}", caps);
    println!(
        "    final: v.len = {}, v.capacity = {}",
        v.len(),
        v.capacity()
    );
    check(
        "capacity is always >= length (the load-bearing invariant)",
        v.capacity() >= v.len(),
    );
    check(
        "push grew the vec: after 5 pushes capacity >= 5",
        v.capacity() >= 5,
    );
    check(
        "pushing never panicked: v == [1, 2, 3, 4, 5]",
        v == [1, 2, 3, 4, 5],
    );
    // NOTE: the exact sequence above (e.g. [4,4,4,4,8]) is the CURRENT growth
    // strategy; std does not guarantee a particular factor, only amortized O(1).
}

// ── Section C: indexing — v[i] PANICS out-of-bounds; v.get(i) -> Option ──────

fn section_c() {
    banner("C — indexing: v[i] PANICS out-of-bounds; v.get(i) returns Option");
    let v: Vec<i32> = vec![10, 20, 30];
    println!("  let v = vec![10, 20, 30];  (len = {})", v.len());

    // Indexing v[i] uses the Index trait. In bounds it yields the element...
    println!("    v[1] = {}", v[1]);
    check(
        "in-bounds indexing returns the element: v[1] == 20",
        v[1] == 20,
    );

    // ...but it is BOUNDS-CHECKED at runtime: an out-of-range index PANICS in
    // both debug and release builds. The safe alternative is .get(i), which
    // returns Option<&T> (None instead of a panic).
    match v.get(1) {
        Some(x) => check("v.get(1) yields Some(20)", *x == 20),
        None => check("v.get(1) yields Some(20)", false),
    }
    check(
        "v.get(5) yields None on an out-of-bounds index",
        v.get(5).is_none(),
    );

    // v[5] would abort the program. We catch the unwind so the run continues,
    // then assert the EXACT panic payload string produced by the Index impl.
    // The default panic hook would still print a scary traceback to stderr, so
    // we silence it for just this deliberate panic and restore it right after.
    let saved_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    let result = std::panic::catch_unwind(AssertUnwindSafe(|| v[5]));
    std::panic::set_hook(saved_hook);
    match result {
        Ok(_) => check("v[5] panics (the vec has len 3)", false),
        Err(payload) => {
            let msg = payload
                .downcast_ref::<String>()
                .map(String::as_str)
                .or_else(|| payload.downcast_ref::<&'static str>().copied())
                .unwrap_or("<non-string panic payload>");
            println!("    v[5] -> CAUGHT panic: \"{msg}\"");
            check(
                "out-of-bounds panic prints the canonical slice message",
                msg == "index out of bounds: the len is 3 but the index is 5",
            );
        }
    }
}

// ── Section D: slices &[T] — a borrowed view; &Vec derefs to &[T] ────────────

fn section_d() {
    banner("D — slices &[T]: a borrowed view; &Vec derefs to &[T] for free");
    let v = vec![10, 20, 30];
    println!("  let v = vec![10, 20, 30];");

    // Passing &v where &[i32] is expected: deref coercion turns &Vec<T> into
    // &[T] automatically (Vec implements Deref<Target = [T]>).
    let total = sum_slice(&v);
    println!("  sum_slice(&v) -> {total}   (passed &Vec, coerced to &[i32])");
    check(
        "a &Vec argument deref-coerces to &[T] and sums to 60",
        total == 60,
    );

    // The same coercion happens at a binding with an explicit slice type.
    let s: &[i32] = &v;
    println!("  let s: &[i32] = &v;   // same coercion at the binding");
    check(
        "&[i32] = &v binds a slice reference spanning the whole vec",
        s == &v[..],
    );

    // Sub-slicing borrows a contiguous window. Range a..b is half-open: [a, b).
    let mid: &[i32] = &v[1..3];
    println!("  let mid = &v[1..3];   // mid = {:?}", mid);
    check("sub-slice &v[1..3] == [20, 30]", mid == [20, 30]);

    // A slice reference is a FAT pointer {data_ptr, len} (two words); a plain
    // reference &T is THIN (one word). That is why &[T] carries its own length.
    let fat = std::mem::size_of::<&[i32]>();
    let thin = std::mem::size_of::<&i32>();
    println!("  size_of::<&[i32]>() = {fat} bytes (fat pointer: data_ptr + len)");
    println!("  size_of::<&i32>()  = {thin} bytes (thin pointer: data_ptr only)");
    check(
        "slice reference &[T] is a fat pointer: 16 bytes = ptr(8) + len(8)",
        fat == 16,
    );
    check("plain reference &T is a thin pointer: 8 bytes", thin == 8);
}

// ── Section E: mutation methods — push/pop/insert/remove/extend/retain/clear ─

fn section_e() {
    banner("E — mutation methods: push/pop/insert/remove/extend/retain/clear");
    let mut v: Vec<i32> = Vec::new();
    v.push(20);
    v.push(30);
    v.insert(0, 10); // O(n): shifts elements right to make room
    println!("  push 20, 30; insert(0, 10) -> {:?}", v);
    check(
        "insert(0, 10) prepends (O(n) shift): v == [10, 20, 30]",
        v == [10, 20, 30],
    );

    v.extend([40, 50]);
    println!("  extend([40, 50]) -> {:?}", v);
    check(
        "extend appends a sequence: v == [10, 20, 30, 40, 50]",
        v == [10, 20, 30, 40, 50],
    );

    let popped = v.pop();
    println!("  v.pop() -> {:?}; v now {:?}", popped, v);
    check(
        "pop removes and returns the LAST element: Some(50)",
        popped == Some(50),
    );

    let removed = v.remove(0); // O(n): shifts the tail left to fill the gap
    println!("  v.remove(0) -> {removed}; v now {:?}", v);
    check(
        "remove(0) takes index 0 and shifts left (O(n)): removed = 10, v == [20, 30, 40]",
        removed == 10 && v == [20, 30, 40],
    );

    v.retain(|&x| x >= 30);
    println!("  v.retain(|x| x >= 30) -> {:?}", v);
    check(
        "retain keeps only matching elements: v == [30, 40]",
        v == [30, 40],
    );

    v.clear();
    println!("  v.clear() -> len = {}, v = {:?}", v.len(), v);
    check("clear empties the vec (length 0): v == []", v.is_empty());
}

// ── Section F: iteration — by reference (&v / .iter) vs by value (into_iter) ──

fn section_f() {
    banner("F — iteration: by reference (&v / .iter) vs by value (into_iter)");
    let v = vec![10, 20, 30];

    // 1. `for x in &v` BORROWS: it yields &i32 and leaves v owned and usable.
    let mut borrowed_sum = 0;
    for x in &v {
        borrowed_sum += x;
    }
    println!(
        "  for x in &v {{ sum }} -> {borrowed_sum}; v still owned: {:?}",
        v
    );
    check(
        "for x in &v borrows (yields &i32): sum == 60 AND v stays usable",
        borrowed_sum == 60 && v.len() == 3,
    );

    // 2. .iter() is the explicit borrow flavor (also yields &i32).
    let doubled: Vec<i32> = v.iter().map(|&x| x * 2).collect();
    println!("  v.iter().map(|x| x * 2).collect() -> {:?}", doubled);
    check(
        ".iter() borrows and yields &i32: doubled == [20, 40, 60]",
        doubled == [20, 40, 60],
    );

    // 3. into_iter() CONSUMES v: ownership of each element moves out, so v is
    //    dead afterwards (this is `for x in v` desugared).
    let consumed_sum: i32 = v.into_iter().sum();
    println!("  v.into_iter().sum() -> {consumed_sum}  (v consumed; unusable hereafter)");
    check(
        "into_iter consumes the Vec by value: sum == 60",
        consumed_sum == 60,
    );
}

// ── Section G: the alias trap — &v[i] held across v.push() is E0502 ──────────

fn section_g() {
    banner("G — the alias trap: &v[i] held across v.push() is E0502 (compile error)");
    // This DOES NOT COMPILE, so it can only appear as documentation:
    //
    //     let mut v = vec![10, 20, 30];
    //     let first = &v[0];     // <- immutable borrow of `v` starts
    //     v.push(40);            // ERROR E0502: mutable borrow while immutable is live
    //     println!("{first}");   // <- immutable borrow used here
    //
    // WHY the borrow checker rejects it: `push` may REALLOCATE (move the whole
    // buffer to a new address) when len == capacity, which would dangle `first`.
    // The full verbatim diagnostic is in VEC_COLLECTIONS.md (Section G).
    //
    // FIX: because i32 is Copy, read the value OUT first. The borrow ends at the
    // read, so there is no outstanding borrow when push runs.
    let mut v = vec![10, 20, 30];
    let first = v[0]; // Copy: borrowed, read, borrow ends immediately
    v.push(40); // safe now: no outstanding borrow of v
    println!("  copy-out fix: first = {first}, after push v = {:?}", v);
    check(
        "copying the Copy element out before push lets push run: v.len == 4",
        v.len() == 4 && first == 10,
    );
}

fn main() {
    println!("vec_collections.rs — Phase 1 bundle #7 (Vec<T> + &[T]).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    section_g();
    banner("DONE — all sections printed");
}
