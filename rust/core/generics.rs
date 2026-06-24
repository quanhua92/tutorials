//! generics.rs — Phase 2 bundle (Types, Traits & Generics).
//!
//! GOAL (one line): show, by printing every value, that a GENERIC item
//! (`fn first<T>`, `struct Stack<T>`, `enum Opt<T>`) is a COMPILE-TIME
//! TEMPLATE parameterized by one or more type parameters, that the compiler
//! MONOMORPHIZES it (stamps out one concrete copy per type used -> static
//! dispatch, zero runtime cost, at the price of code-size growth), that the
//! turbofish `::<>` disambiguates type inference, and that CONST GENERICS
//! (`<const N: usize>`) parameterize by a compile-time VALUE (e.g. array size).
//!
//! This is the GROUND TRUTH for GENERICS.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Run:
//!     just run generics   (== cargo run --bin generics)

use std::any::type_name;

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

// ── Section A: a generic FUNCTION — one definition, usable for any T ─────────
// `fn first<T>(slice: &[T]) -> &T` works for ANY T: it only borrows element 0,
// so it needs NO trait bound on T (unlike the Book's `largest<T>`, which needs
// `PartialOrd` to compare). The `<T>` AFTER the fn name DECLARES the type param;
// the same name is then usable in the parameter and return types.
//
// The diagnostic print of `type_name::<T>()` is the MONOMORPHIZATION
// FINGERPRINT used in Section C: the SAME source text prints a DIFFERENT type
// name per concrete instantiation, proving each call site compiled its own copy.
fn first<T>(slice: &[T]) -> &T {
    println!("    [first::<{}> called]", type_name::<T>());
    &slice[0]
}

// ── Section B: a generic STRUCT + its generic impl ──────────────────────────
// `Stack<T>` is parameterized by the element type T. Its ONE field is a
// `Vec<T>`, so the whole struct is generic. `impl<T> Stack<T>` declares T again
// after `impl` so the methods apply to EVERY `Stack<T>` (Section F contrasts
// this with a concrete `impl Stack<u8>`).
struct Stack<T> {
    items: Vec<T>,
}

impl<T> Stack<T> {
    fn new() -> Self {
        Stack { items: Vec::new() }
    }

    /// Takes `item` BY VALUE (ownership moves in) — that is why a Stack<String>
    /// can own its Strings. The param type T lets the same method store any T.
    fn push(&mut self, item: T) {
        self.items.push(item);
    }

    /// Returns `Option<T>`: `Some` with ownership of the top, or `None` if empty.
    fn pop(&mut self) -> Option<T> {
        self.items.pop()
    }

    fn len(&self) -> usize {
        self.items.len()
    }
}

// A generic ENUM is identical in shape: `<T>` after the name, T usable in the
// variants' payloads. (Option<T>/Result<T,E> in the stdlib are exactly this.)
#[derive(Debug, PartialEq)]
enum Opt<T> {
    Some(T),
    None,
}

// ── Section D helpers: turbofish resolves type-inference ambiguity ──────────
// `parse` and `collect` are generic over their RETURN type, so the compiler
// often cannot pick the concrete type from context. The turbofish `::<>`
// spells it out at the CALL SITE.

/// Parses a string into an i32 via turbofish on `parse`. Without `::<i32>` the
/// compiler emits "type annotations needed" — it cannot know what to parse into.
fn parse_i32(s: &str) -> i32 {
    s.parse::<i32>().unwrap_or(0)
}

/// Collects an iterator of numbers into a `Vec<i32>` via turbofish on `collect`.
/// `collect::<Vec<_>>` fixes the container and lets inference fill the element.
fn collect_doubled(xs: &[i32]) -> Vec<i32> {
    xs.iter().map(|x| x * 2).collect::<Vec<i32>>()
}

// ── Section E: CONST GENERICS — parameterize by a compile-time VALUE ────────
// `<const N: usize>` is a CONST parameter: a value known at compile time, not a
// type. It lets `Arr<T, N>` wrap a fixed-size `[T; N]` and abstract over the
// length. Stabilized in Rust 1.51 (RFC 2000). The bound `T: Copy + Default` is
// required here only so `[T::default(); N]` can initialize the array.
struct Arr<T, const N: usize> {
    buf: [T; N],
}

impl<T: Copy + Default, const N: usize> Arr<T, N> {
    /// Builds an `Arr` full of `T::default()`. N is known at compile time, so
    /// `[T::default(); N]` is a fixed-size stack array — no heap.
    fn full_default() -> Self {
        Arr {
            buf: [T::default(); N],
        }
    }

    /// `N` is a compile-time constant, so `.len()` returns it directly — no
    /// stored length field, no runtime tracking.
    const fn len(&self) -> usize {
        N
    }

    fn as_slice(&self) -> &[T] {
        &self.buf
    }
}

// ── Section F: a CONCRETE impl — methods only for ONE instantiation ─────────
// `impl Stack<u8>` (NO `<T>` after impl) adds methods that exist ONLY on
// `Stack<u8>`, not on `Stack<i32>` or any other instantiation. This is how you
// give a specific generic instantiation extra behavior (the Book's
// `impl Point<f32>` pattern, Listing 10-10).
impl Stack<u8> {
    /// Sums every byte — only meaningful for `Stack<u8>`.
    fn byte_sum(&self) -> u8 {
        self.items
            .iter()
            .copied()
            .fold(0u8, |a, b| a.wrapping_add(b))
    }
}

// ── Section A: a generic fn works for ANY T ────────────────────────────────

fn section_a() {
    banner("A — a generic fn: fn first<T>(slice: &[T]) -> &T works for any T");
    let nums = [10, 20, 30];
    let words = ["alpha", "bravo", "charlie"];
    println!("  fn first<T>(slice: &[T]) -> &T {{ &slice[0] }}");
    println!("  let nums  = [10, 20, 30];");
    println!("  let words = [\"alpha\", \"bravo\", \"charlie\"];");
    let first_num = first(&nums);
    let first_word = first(&words);
    println!("    first(&nums)  -> {}   (T inferred as i32)", first_num);
    println!(
        "    first(&words) -> {:?}  (T inferred as &str)",
        first_word
    );
    check(
        "first(&[10,20,30]) == 10 (instantiated for i32)",
        *first_num == 10,
    );
    check(
        "first([\"alpha\",\"bravo\",\"charlie\"]) == \"alpha\" (instantiated for &str)",
        *first_word == "alpha",
    );
}

// ── Section B: a generic struct + generic impl ──────────────────────────────

fn section_b() {
    banner("B — a generic struct: Stack<T> used with i32 AND String");
    // Stack<i32>: T = i32. push takes an i32 by value.
    let mut s = Stack::<i32>::new();
    s.push(1);
    s.push(2);
    println!("  let mut s = Stack::<i32>::new();  s.push(1);  s.push(2);");
    let popped = s.pop();
    println!(
        "    s.pop() -> {:?}   (LIFO: last pushed comes out first)",
        popped
    );
    println!("    s.len() -> {}", s.len());
    check(
        "Stack::<i32> push 1,2 then pop == Some(2)",
        popped == Some(2),
    );
    check("after pop, Stack len == 1", s.len() == 1);

    // Stack<String>: T = String. The SAME `push`/`pop` source now owns Strings.
    let mut names = Stack::new();
    names.push(String::from("ada"));
    names.push(String::from("grace"));
    println!("  let mut names = Stack::new();  push \"ada\";  push \"grace\";");
    let top = names.pop();
    println!("    names.pop() -> {:?}", top);
    check(
        "Stack<String> reuses the same push/pop source (T = String)",
        top.as_deref() == Some("grace"),
    );

    // A generic ENUM behaves the same way: Opt<T> carries a T in its Some arm.
    let some = Opt::Some(7i32);
    let none: Opt<i32> = Opt::None;
    println!("  Opt::Some(7) -> {:?}   Opt::None  -> {:?}", some, none,);
    check(
        "generic enum Opt<i32>::Some(7) == Some(7)",
        some == Opt::Some(7),
    );
    check(
        "generic enum Opt<i32>::None is the None variant",
        none == Opt::None,
    );
}

// ── Section C: monomorphization — one source, many compiled copies ──────────

fn section_c() {
    banner("C — monomorphization: first::<u8> and first::<u32> are TWO fns");
    // The SAME `fn first<T>` source is called with two DIFFERENT concrete types.
    // The diagnostic print inside `first` emits a DISTINCT type name per call —
    // that is the observable fingerprint of monomorphization: the compiler
    // generated `first_u8` and `first_u32` as two separate compiled functions,
    // so they each printed their own type. No boxing, no runtime type info —
    // the type is baked in at compile time.
    let bytes = [5u8, 6, 7];
    let words = [5u32, 6, 7];
    println!("  first(&[5u8,6,7])  and  first(&[5u32,6,7])  (same source):");
    let b = first(&bytes);
    let w = first(&words);
    println!("    -> first::<u8>  returned {}", b);
    println!("    -> first::<u32> returned {}", w);
    check(
        "first::<u8> and first::<u32> print DISTINCT type names (mono evidence)",
        type_name::<u8>() != type_name::<u32>(),
    );
    check("first::<u8> returns the u8 5", *b == 5);
    check("first::<u32> returns the u32 5", *w == 5);
}

// ── Section D: turbofish — disambiguating type inference ────────────────────

fn section_d() {
    banner("D — turbofish ::<> disambiguates when type inference cannot");
    // `parse` is generic over its OUTPUT: "42" could parse to i32, u64, f64...
    // Without an annotation the compiler cannot choose, so we write `::<i32>`.
    println!("  \"42\".parse::<i32>()  -> {}", parse_i32("42"));
    check("\"42\".parse::<i32>() == 42", parse_i32("42") == 42);
    check(
        "\"x\".parse::<i32>() falls back to 0 (unwrap_or)",
        parse_i32("x") == 0,
    );

    // `collect` is generic over its OUTPUT collection: an iterator of i32 could
    // become a Vec, HashSet, String... `collect::<Vec<i32>>()` pins it down.
    let doubled = collect_doubled(&[1, 2, 3]);
    println!(
        "  [1,2,3].iter().map(|x| x*2).collect::<Vec<i32>>() -> {:?}",
        doubled
    );
    check(
        "collect::<Vec<i32>>() on doubled [1,2,3] == [2,4,6]",
        doubled == [2, 4, 6],
    );

    // Turbofish with inference: `collect::<Vec<_>>()` fixes the container and
    // lets the compiler infer the ELEMENT type (_) from the iterator.
    let tup: Vec<i32> = ["10", "20", "30"]
        .iter()
        .map(|s| s.parse::<i32>().unwrap_or(0))
        .collect::<Vec<_>>();
    println!(
        "  parse each of [\"10\",\"20\",\"30\"], collect::<Vec<_>>() -> {:?}",
        tup
    );
    check(
        "collect::<Vec<_>> infers the element type -> [10,20,30]",
        tup == [10, 20, 30],
    );
}

// ── Section E: const generics — parameterize by a compile-time VALUE ────────

fn section_e() {
    banner("E — const generics: Arr<T, const N: usize> is parameterized by N");
    // `Arr::<u8, 4>`: T = u8 AND N = 4 (a compile-time value, not a type).
    // The inner buffer is a genuine `[u8; 4]` — fixed size, on the stack, no
    // heap allocation. `full_default()` fills it with `u8::default()` == 0.
    let arr = Arr::<u8, 4>::full_default();
    println!("  let arr = Arr::<u8, 4>::full_default();");
    println!("    arr.as_slice() -> {:?}", arr.as_slice());
    println!(
        "    arr.len()      -> {}  (== the const param N)",
        arr.len()
    );
    check(
        "Arr::<u8, 4> buffer is a 4-element zero-filled array",
        arr.as_slice() == [0u8, 0, 0, 0],
    );
    check(
        "Arr::<u8, 4>.len() == 4 (the const param N is baked in)",
        arr.len() == 4,
    );

    // A DIFFERENT N is a DIFFERENT TYPE: Arr<_, 4> and Arr<_, 8> do not mix.
    // N is part of the type, known at compile time, so `.len()` is a const fn.
    let bigger = Arr::<u8, 8>::full_default();
    println!("  let bigger = Arr::<u8, 8>::full_default();");
    println!(
        "    bigger.len() -> {}  (distinct type from Arr<_, 4>)",
        bigger.len()
    );
    check(
        "Arr::<u8, 8>.len() == 8 — different N means a different type",
        bigger.len() == 8,
    );

    // size_of::<Arr<u8,4>>() is the size of [u8;4] == 4; N changes the size.
    let sz4 = std::mem::size_of::<Arr<u8, 4>>();
    let sz8 = std::mem::size_of::<Arr<u8, 8>>();
    println!(
        "  size_of::<Arr<u8,4>>() = {},  size_of::<Arr<u8,8>>() = {}",
        sz4, sz8
    );
    check(
        "N changes layout: size_of::<Arr<u8,4>>() == 4 and <...,8> == 8",
        sz4 == 4 && sz8 == 8,
    );
}

// ── Section F: generic impl vs CONCRETE impl ────────────────────────────────

fn section_f() {
    banner("F — generic impl<T> vs concrete impl (methods only on Stack<u8>)");
    // `impl<T> Stack<T>` (Section B's new/push/pop/len) applies to EVERY
    // instantiation. `impl Stack<u8>` adds `byte_sum` ONLY to Stack<u8>.
    let mut bytes = Stack::<u8>::new();
    bytes.push(10);
    bytes.push(20);
    bytes.push(5);
    println!("  let mut bytes = Stack::<u8>::new();  push 10, 20, 5;");
    println!(
        "    bytes.byte_sum() -> {}   (method from the CONCRETE impl)",
        bytes.byte_sum()
    );
    check(
        "concrete impl Stack<u8>::byte_sum sums the bytes (10+20+5 == 35)",
        bytes.byte_sum() == 35,
    );

    // The generic impl<T>'s methods still work on Stack<u8> too — both impls
    // compose: a type can have one generic impl AND extra concrete impls.
    let popped = bytes.pop();
    println!("    bytes.pop() -> {:?}   (generic impl<T> method)", popped);
    check(
        "Stack<u8> still has the GENERIC impl's pop() (== Some(5))",
        popped == Some(5),
    );

    // Contrast: Stack<i32> has pop (generic impl) but NOT byte_sum (concrete
    // impl only). If we uncommented `ints.byte_sum()` it would fail to compile
    // with "no method named `byte_sum` found for `Stack<i32>`". Documented in
    // GENERICS.md.
    let mut ints = Stack::<i32>::new();
    ints.push(100);
    ints.push(200);
    let ints_popped = ints.pop();
    println!("  let mut ints = Stack::<i32>::new();  push 100, 200;");
    println!(
        "    ints.pop() -> {:?}   (ints.byte_sum() would NOT compile)",
        ints_popped
    );
    check(
        "generic impl methods apply to Stack<i32> too (pop -> Some(200))",
        ints_popped == Some(200),
    );
}

fn main() {
    println!("generics.rs — Phase 2 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
