//! iterators.rs — Phase 3 bundle #2 (Memory & Smart Pointers).
//!
//! GOAL (one line): show, by printing every value, that a Rust iterator is a
//! LAZY sequence driven by ONE required method (`fn next(&mut self) -> Option
//! <Self::Item>`), that adapter chains like `.map(..).filter(..)` do NO work
//! until a CONSUMING op (`collect`/`sum`/`for`/`fold`) pulls values through
//! them, that fusion + monomorphization compile the whole chain into ONE tight
//! loop (zero-cost), that there are three ownership flavors (`into_iter` ->
//! `T`, `iter` -> `&T`, `iter_mut` -> `&mut T`), and that implementing
//! `Iterator::next` on your own type gives you every adapter for free.
//!
//! This is the GROUND TRUTH for ITERATORS.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! The "lazy chain compiles to one loop" claim is a COMPILE-TIME / release-mode
//! guarantee (verified by Book ch13.4 + godbolt asm inspection) — it is NOT
//! observable from debug stdout, so it is documented in ITERATORS.md rather
//! than asserted here. What this file DOES prove at runtime: laziness (an
//! unconsumed chain runs zero closures) and fusion's SEMANTIC equivalence (the
//! chain produces exactly the values a hand loop would).
//!
//! Run:
//!     just run iterators   (== cargo run --bin iterators)

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

// ── Section A: the Iterator trait — one required method, `next` ─────────────
// The whole Iterator trait has ONE required method: `fn next(&mut self) ->
// Option<Self::Item>`. The other ~70 methods (map, filter, collect, sum, fold,
// ...) are PROVIDED: each is implemented in terms of `next`. That is why you
// implement only `next` and get the entire adapter library for free.

fn section_a() {
    banner("A — the Iterator trait: one required method, `next`");
    println!("  pub trait Iterator {{");
    println!("      type Item;");
    println!("      fn next(&mut self) -> Option<Self::Item>;");
    println!("      // ~70 provided methods (map, filter, collect, sum, fold, ...)");
    println!("  }}");
    println!("  // Implement ONLY next(); every adapter is derived from it.");

    let a = [1, 2, 3];
    let mut it = a.iter(); // std::slice::Iter — impl Iterator<Item = &i32>
    println!("  let a = [1, 2, 3];  let mut it = a.iter();   // Item = &i32");
    // Call next() by hand: Some, Some, Some, then None (and None again — slice
    // iterators are fused). This manual `next()` driving is exactly what
    // `for x in it` desugars into (via IntoIterator — see Section D).
    let seq = [it.next(), it.next(), it.next(), it.next(), it.next()];
    println!("  it.next() x5 -> {:?}", seq);
    check(
        "next() yields Some(&1), Some(&2), Some(&3), then None (fused: stays None)",
        seq == [Some(&1), Some(&2), Some(&3), None, None],
    );
}

// ── Section B: LAZY adapters — wrap the source, run NOTHING until consumed ──
// `map`/`filter`/`take`/`skip`/`enumerate`/`zip` are ITERATOR ADAPTERS: each
// takes the iterator BY VALUE, wraps it in a new iterator struct (Map, Filter,
// Take, ...), and returns that wrapper. The closures inside are NOT called yet
// — the chain is just a DESCRIPTION of a computation. The Book (ch13.2):
// "iterators are lazy, and we need to consume the iterator here."

fn section_b() {
    banner("B — LAZY adapters: wrap the source; NOTHING runs until consumed");
    // `calls` proves laziness: `inspect` would bump it if the chain were
    // running, but we have only BUILT the chain so far — not consumed it.
    let calls = Cell::new(0u32);
    let chain = [1, 2, 3, 4, 5, 6]
        .iter()
        .inspect(|_| calls.set(calls.get() + 1))
        .map(|&x| x * 2)
        .filter(|&x| x > 4);
    println!("  [1..6].iter().inspect(..).map(|x| x*2).filter(|x| x>4)  // built, NOT consumed");
    println!(
        "  inspect-calls so far = {}  (the chain did ZERO work)",
        calls.get()
    );
    check(
        "lazy: an unconsumed chain runs no closures (inspect saw 0 items)",
        calls.get() == 0,
    );

    // `skip` and `take` are lazy too — they just re-wrap the upstream iterator.
    let skipped: Vec<i32> = (1..=10).skip(7).take(2).collect();
    println!(
        "  (1..=10).skip(7).take(2).collect() = {:?}  (skip+take are lazy adapters)",
        skipped
    );
    check("skip(7).take(2) on 1..=10 -> [8,9]", skipped == [8, 9]);

    // NOW consume `chain`: the closures run, fused into ONE pass over the source.
    let out: Vec<i32> = chain.collect();
    println!("  chain.collect::<Vec<_>>() = {:?}  (now it ran)", out);
    // [1,2,3,4,5,6] -> *2 -> [2,4,6,8,10,12] -> >4 -> [6,8,10,12]
    check(
        "after collect: map(x*2).filter(>4) produced [6,8,10,12]",
        out == [6, 8, 10, 12],
    );
    check(
        "fusion (semantic): inspect saw all 6 source items in a SINGLE pass",
        calls.get() == 6,
    );
}

// ── Section C: CONSUMING adapters — collect/sum/product/count/fold/any/all ──
// Consuming adapters take the iterator BY VALUE and DRIVE `next()` to
// completion (or until they short-circuit). After one, the iterator is gone.
// These are the ops that actually do the work the lazy chain described.

fn section_c() {
    banner("C — CONSUMING adapters: sum/product/count/fold/any/all drive the chain");

    // sum: owns the iterator, drives next() to None, returns the total.
    let s: i32 = (1..=5).sum();
    println!("  (1..=5).sum::<i32>() = {}", s);
    check("sum consumes the range: 1+2+3+4+5 = 15", s == 15);

    // product: like sum, but multiplies.
    let p: i32 = (1..=4).product();
    println!("  (1..=4).product::<i32>() = {}", p);
    check("product consumes: 1*2*3*4 = 24", p == 24);

    // count: drives to None and counts the Some(_) it saw.
    let c = [10, 20, 30].iter().count();
    println!("  [10,20,30].iter().count() = {}", c);
    check("count consumes: 3 elements", c == 3);

    // fold: left reduce with a seed; the MOST GENERAL consuming adapter
    // (sum == fold(0, |a,x| a+x); product == fold(1, |a,x| a*x)). To show its
    // real power, compute TWO aggregates in a single pass — something no single
    // built-in adapter can do. The seed is a tuple; the closure threads it.
    let (sum, max): (i32, i32) = (1..=5).fold((0, i32::MIN), |(s, m), x| (s + x, m.max(x)));
    println!(
        "  (1..=5).fold((0, MIN), |(s,m),x| (s+x, m.max(x))) -> sum={}, max={}",
        sum, max
    );
    check(
        "fold threads a tuple seed: one pass yields sum=15 AND max=5",
        sum == 15 && max == 5,
    );

    // any/all: BOOLEAN consumers that SHORT-CIRCUIT (stop at first deciding el).
    let has_even = [1, 3, 5, 6].iter().any(|&x| x % 2 == 0);
    let all_pos = [1, 2, 3].iter().all(|&x| x > 0);
    println!(
        "  [1,3,5,6].any(|x| x%2==0) = {}  (short-circuits at 6)",
        has_even
    );
    println!("  [1,2,3].all(|x| x>0)     = {}", all_pos);
    check("any drives until first true (found 6 -> true)", has_even);
    check("all drives until first false (none here -> true)", all_pos);

    // collect: the universal consumer — any FromIterator (Vec, HashMap, String,
    // HashSet, ...). Type is inferred from the binding (often via turbofish).
    let doubled: Vec<i32> = [1, 2, 3].iter().map(|&x| x * 2).collect();
    println!(
        "  [1,2,3].iter().map(|x| x*2).collect::<Vec<_>>() = {:?}",
        doubled
    );
    check("collect into Vec: [2,4,6]", doubled == [2, 4, 6]);
}

// ── Section D: the three forms — into_iter (T), iter (&T), iter_mut (&mut T) ─
// Every collection offers three iteration modes differing only in OWNERSHIP.
// `for x in v` desugars to `for x in IntoIterator::into_iter(v)` — so `for`
// over an owned Vec CONSUMES it; over `&v` it borrows; over `&mut v` it borrows
// mutably. (For a `Vec<T>`, `into_iter` yields `T`, `iter` yields `&T`,
// `iter_mut` yields `&mut T`.)

fn section_d() {
    banner("D — into_iter (T) vs iter (&T) vs iter_mut (&mut T)");
    // (1) into_iter: consumes the collection, yields OWNED items.
    let owned: Vec<i32> = vec![1, 2, 3].into_iter().collect();
    // (the Vec is now moved away; using it here would be E0382)
    println!(
        "  vec![1,2,3].into_iter().collect::<Vec<i32>>() = {:?}",
        owned
    );
    check(
        "into_iter yields OWNED T (the Vec is consumed)",
        owned == [1, 2, 3],
    );

    // (2) iter: borrows immutably, yields &T; caller keeps the collection.
    let nums = vec![1, 2, 3];
    let refs: Vec<&i32> = nums.iter().collect();
    println!("  vec![1,2,3].iter().collect::<Vec<&i32>>() = {:?}", refs);
    println!("  (nums still owned by caller: {:?})", nums);
    check(
        "iter yields &T; caller retains ownership (nums still usable)",
        nums == [1, 2, 3] && refs == [&1, &2, &3],
    );

    // (3) iter_mut: borrows mutably, yields &mut T; mutate IN PLACE.
    let mut to_double = vec![1, 2, 3];
    for n in to_double.iter_mut() {
        *n *= 2;
    }
    println!("  for n in v.iter_mut() {{ *n *= 2; }} -> {:?}", to_double);
    check(
        "iter_mut yields &mut T; doubles each element to [2,4,6]",
        to_double == [2, 4, 6],
    );

    // `for x in v` uses IntoIterator — for an owned array/Vec that is
    // `into_iter` (items by value). The loop takes ownership and makes the
    // iterator `mut` behind the scenes (you never write `mut` on a `for`).
    let mut total = 0i32;
    for x in [1, 2, 3] {
        total += x;
    }
    println!(
        "  for x in [1,2,3] {{ total += x; }} -> {}  (desugars to .into_iter())",
        total
    );
    check(
        "`for x in v` desugars to IntoIterator::into_iter (total = 6)",
        total == 6,
    );
}

// ── Section E: zip pairs two iterators; enumerate tags each with its index ──

fn section_e() {
    banner("E — zip pairs two iters; enumerate tags each item with its index");
    // zip: yields (a, b) pairs; STOPS when either iterator returns None.
    let pairs: Vec<(i32, &str)> = [1, 2, 3].into_iter().zip(["a", "b"]).collect();
    println!(
        "  [1,2,3].into_iter().zip([\"a\",\"b\"]).collect() = {:?}",
        pairs
    );
    check(
        "zip stops at the SHORTER iterator (length 2): [(1,\"a\"),(2,\"b\")]",
        pairs == [(1, "a"), (2, "b")],
    );

    // enumerate: yields (usize, Item) — index paired with each item, from 0.
    let indexed: Vec<(usize, i32)> = (100..=102).enumerate().collect();
    println!(
        "  (100..=102).enumerate().collect::<Vec<_>>() = {:?}",
        indexed
    );
    check(
        "enumerate yields (index, item) pairs from 0: [(0,100),(1,101),(2,102)]",
        indexed == [(0, 100), (1, 101), (2, 102)],
    );

    // zip + enumerate compose (both are lazy); collect drives both at once.
    let squared_index: Vec<(usize, i32)> = (10..)
        .zip([5, 6, 7])
        .enumerate()
        .map(|(i, (a, b))| (i, a * b))
        .collect();
    println!(
        "  (10..).zip([5,6,7]).enumerate().map(|(i,(a,b))| (i,a*b)).collect() = {:?}",
        squared_index
    );
    check(
        "zip+enumerate+map fused: [(0,50),(1,66),(2,84)]",
        squared_index == [(0, 50), (1, 66), (2, 84)],
    );
}

// ── Section F: a custom iterator — impl Iterator once, get ALL adapters free ─
// To make your own type iterable, implement `Iterator` (define `Item` + `next`).
// Because every adapter is derived from `next`, your type instantly gains
// map/filter/collect/sum/zip/enumerate/fold/... — for free, and statically
// dispatched (monomorphized), so there is no v-table cost.

/// A simple counter: yields 0, 1, 2, ... up to (but not including) `limit`.
struct Counter {
    current: u32,
    limit: u32,
}

impl Counter {
    fn new(limit: u32) -> Self {
        Counter { current: 0, limit }
    }
}

impl Iterator for Counter {
    type Item = u32;

    fn next(&mut self) -> Option<Self::Item> {
        if self.current < self.limit {
            let v = self.current;
            self.current += 1;
            Some(v)
        } else {
            None
        }
    }
}

fn section_f() {
    banner("F — custom iterator: impl Iterator once, get ALL adapters free");
    // Drive next() by hand — Counter is a real Iterator.
    let mut c = Counter::new(3);
    let seq = [c.next(), c.next(), c.next(), c.next()];
    println!("  Counter::new(3): next() x4 -> {:?}", seq);
    check(
        "custom Counter yields Some(0),Some(1),Some(2),None",
        seq == [Some(0), Some(1), Some(2), None],
    );

    // map + collect — free, because Iterator provides them.
    let mapped: Vec<u32> = Counter::new(3).map(|x| x + 10).collect();
    println!(
        "  Counter::new(3).map(|x| x+10).collect::<Vec<_>>() = {:?}",
        mapped
    );
    check(
        "custom iterator gets map+collect free: [10,11,12]",
        mapped == [10, 11, 12],
    );

    // filter + sum — also free.
    let sum_evens: u32 = Counter::new(6).filter(|x| x % 2 == 0).sum();
    println!(
        "  Counter::new(6).filter(|x| x%2==0).sum() = {}  (0+2+4)",
        sum_evens
    );
    check(
        "custom iterator gets filter+sum free: 0+2+4 = 6",
        sum_evens == 6,
    );

    // zip two custom iterators — stops at the shorter.
    let zipped: Vec<(u32, u32)> = Counter::new(2).zip(Counter::new(3)).collect();
    println!(
        "  Counter::new(2).zip(Counter::new(3)).collect() = {:?}",
        zipped
    );
    check(
        "zip of two custom iters stops at the shorter (2): [(0,0),(1,1)]",
        zipped == [(0, 0), (1, 1)],
    );
}

fn main() {
    println!("iterators.rs — Phase 3 bundle #2 (Memory & Smart Pointers).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
