//! strings_str.rs — Phase 1 bundle.
//!
//! GOAL (one line): show, by printing every value, that `String` is the OWNED,
//! growable, heap-allocated text (a `{ptr, len, capacity}` handle over a UTF-8
//! buffer) while `&str` is a BORROWED, read-only view (`{ptr, len}` fat pointer)
//! — and that Rust strings are ALWAYS valid UTF-8, so `len()` counts BYTES, not
//! characters, and indexing `s[i]` is a compile error.
//!
//! This is the GROUND TRUTH for STRINGS_STR.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! One ownership rule here is a COMPILE ERROR: indexing a `String`/`str` with a
//! single integer (`s[0]`) does not build. It cannot live in this runnable file,
//! so the exact `error[E0277]` is documented in STRINGS_STR.md.
//!
//! Run:
//!     just run strings_str   (== cargo run --bin strings_str)

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

// A string literal has the `'static` lifetime: it is baked into the read-only
// program binary, so it lives for the whole program and needs no owner binding.
// This signature (no input lifetimes) is only legal because the literal is
// `'static` — the proof a literal IS `&'static str`.
fn static_literal() -> &'static str {
    "burned into the read-only binary"
}

// ── Section A: String — owned, growable, heap-allocated text ────────────────

fn section_a() {
    banner("A — String: owned, growable, heap-allocated text");
    let s = String::from("hello");
    println!("  let s = String::from(\"hello\");");
    println!("    s            = {:?}", s);
    println!(
        "    s.len()      = {}   (BYTES currently in the buffer)",
        s.len()
    );
    println!(
        "    s.capacity() = {}   (buffer size; always >= len)",
        s.capacity()
    );
    println!(
        "    handle size  = size_of::<String>() = {} bytes  ({{ptr, len, capacity}})",
        std::mem::size_of::<String>()
    );

    // A String is MUTABLE and GROWS: push_str appends a &str, push appends a char.
    let mut g = String::from("rust");
    g.push_str("acean");
    g.push('!');
    println!("  growable: push_str(\"acean\"); push('!') -> {:?}", g);

    // The handle size is CONSTANT regardless of heap content, exactly like Vec.
    let big = String::from("0123456789").repeat(1000); // 10_000 bytes on heap
    println!(
        "  big = ...repeat(1000) -> {} bytes of heap text; handle still {} bytes",
        big.len(),
        std::mem::size_of::<String>()
    );

    check(
        "String handle = ptr(8)+len(8)+cap(8) = 24 bytes on a 64-bit target",
        std::mem::size_of::<String>() == 24,
    );
    check("len() counts BYTES: \"hello\".len() == 5", s.len() == 5);
    check(
        "capacity >= len is always true (the documented invariant)",
        s.capacity() >= s.len(),
    );
    check(
        "String is growable: \"rust\" + \"acean\" + '!' == \"rustacean!\"",
        g == "rustacean!",
    );
    check(
        "handle size is constant: a 10000-byte String still has a 24-byte handle",
        big.len() == 10000 && std::mem::size_of::<String>() == 24,
    );
}

// ── Section B: &str — a BORROWED, read-only view ({ptr, len} fat pointer) ────

fn section_b() {
    banner("B — &str: a BORROWED, read-only view ({ptr, len} fat pointer)");
    // A literal is a `&'static str`: a borrow of text baked into the binary.
    let lit = "literal";
    println!(
        "  let lit = \"literal\";   // type_name::<&str>() = {}",
        std::any::type_name::<&str>()
    );
    println!("                       // (type_name erases lifetimes; the literal IS &'static str)");

    // A &str can BORROW a String's heap text WITHOUT owning it.
    let owned = String::from("owned heap text");
    let view: &str = owned.as_str();
    println!("  let view: &str = String::from(\"owned heap text\").as_str();");
    println!("    view = {:?}, view.len() = {}", view, view.len());

    // A &str can also be a sub-window (slice) of another &str, at char boundaries.
    let slice = &lit[0..3];
    println!(
        "  let slice = &lit[0..3];   -> {:?}   (a sub-&str window)",
        slice
    );

    println!(
        "  &str handle = size_of::<&str>() = {} bytes  ({{ptr, len}}; ptr 8 + len 8)",
        std::mem::size_of::<&str>()
    );
    check(
        "&str fat pointer = ptr(8)+len(8) = 16 bytes on a 64-bit target",
        std::mem::size_of::<&str>() == 16,
    );
    check(
        "a &str can borrow a String's contents without owning them",
        view == "owned heap text",
    );
    check(
        "a &'static str literal can be returned from a fn with no input borrows",
        static_literal() == "burned into the read-only binary",
    );
}

// ── Section C: UTF-8 — len() is BYTES; .chars() is Unicode scalar values ─────

fn section_c() {
    banner("C — UTF-8: len() is BYTES; .chars() is Unicode scalar values");
    let word = "résumé"; // two accented 'é' (U+00E9), each 2 bytes in UTF-8
    println!("  let word = \"résumé\";");
    println!(
        "    word.len()           = {}   (BYTES; each 'é' is 2 bytes)",
        word.len()
    );
    println!(
        "    word.chars().count() = {}   (Unicode scalar values)",
        word.chars().count()
    );

    let wave = "👋"; // U+1F44B, a 4-byte UTF-8 sequence
    println!("  let wave = \"👋\";");
    println!(
        "    wave.len()           = {}   (BYTES; the emoji is 4 bytes)",
        wave.len()
    );
    println!(
        "    wave.chars().count() = {}   (one scalar value)",
        wave.chars().count()
    );

    // Proof of the multi-byte encoding: the RAW UTF-8 byte values themselves.
    // (Collected at runtime — these exact bytes are the ground truth, never
    // hand-computed. This is the Book's ch8.2 demonstration of `bytes()`.)
    let wave_bytes: Vec<u8> = wave.bytes().collect();
    println!(
        "    wave.bytes() = {:?}   (4 bytes that decode to ONE scalar value)",
        wave_bytes
    );

    check(
        "\"résumé\": len() == 8 bytes, chars().count() == 6",
        word.len() == 8 && word.chars().count() == 6,
    );
    check(
        "\"👋\": len() == 4 bytes, chars().count() == 1",
        wave.len() == 4 && wave.chars().count() == 1,
    );
    check(
        ".bytes() yields exactly len() bytes (both count raw UTF-8 bytes)",
        wave_bytes.len() == wave.len(),
    );
}

// ── Section D: conversions — &str -> String, and String -> &str ─────────────

fn section_d() {
    banner("D — conversions: &str -> String, and String -> &str");
    let lit = "hello";

    // &str -> String: three equivalent spellings, each producing a new owned heap copy.
    let a = lit.to_string(); // ToString trait (works on anything Display)
    let b = String::from(lit); // From<&str> for String
    let c = lit.to_owned(); // ToOwned trait (borrowed -> owned counterpart)
    println!("  from &str \"{}\" -> String via three ways:", lit);
    println!("    \"hello\".to_string()   = {:?}   (ToString trait)", a);
    println!("    String::from(\"hello\") = {:?}   (From trait)", b);
    println!("    \"hello\".to_owned()    = {:?}   (ToOwned trait)", c);

    // String -> &str: as_str() is explicit; `&owned` coerces via Deref<Target=str>.
    let owned = String::from("hi");
    let v1: &str = owned.as_str();
    let v2: &str = &owned; // deref coercion: &String -> &str, for free
    println!(
        "  String -> &str:  owned.as_str() == {:?};  &owned (deref) == {:?}",
        v1, v2
    );

    check(
        "to_string / String::from / to_owned all yield the same String",
        a == b && b == c && a == "hello",
    );
    check(
        "String::from(\"hi\").as_str() == \"hi\" (round-trip equality)",
        owned.as_str() == "hi",
    );
    check(
        "deref coercion: &String coerces to &str for free (same value)",
        v1 == "hi" && v2 == "hi",
    );
}

// ── Section E: building — with_capacity avoids realloc; format! concatenates ─

fn section_e() {
    banner("E — building: with_capacity avoids realloc; format! concatenates");
    // Naive: String::new() starts at capacity 0, then reallocs as it grows.
    // (This 0,8,16,16,32,32 trace is the exact sequence in the std::string docs.)
    let mut grown = String::new();
    let mut caps = Vec::new();
    caps.push(grown.capacity());
    for _ in 0..5 {
        grown.push_str("hello");
        caps.push(grown.capacity());
    }
    println!(
        "  naive String::new() + 5x push_str(\"hello\") capacity trace: {:?}",
        caps
    );

    // Pre-allocated: one allocation up front, no realloc inside the loop.
    let mut pre = String::with_capacity(25);
    let pre_cap_before = pre.capacity();
    for _ in 0..5 {
        pre.push_str("hello");
    }
    println!(
        "  String::with_capacity(25): cap stays {} across 5x push_str(\"hello\")",
        pre.capacity()
    );
    println!("    result = {:?}", pre);

    // format! concatenates by BORROWING every input (it never moves them).
    let s1 = String::from("tic");
    let s2 = String::from("tac");
    let s3 = String::from("toe");
    let cat = format!("{}-{}-{}", s1, s2, s3);
    println!("  format!(\"{{}}-{{}}-{{}}\", s1, s2, s3) = {:?}", cat);
    println!(
        "    (s1, s2, s3 still usable after: {:?}, {:?}, {:?})",
        s1, s2, s3
    );

    check(
        "with_capacity(25) holds \"hello\"x5 (25 bytes) with no realloc",
        pre.len() == 25 && pre.capacity() == pre_cap_before,
    );
    check(
        "format! concatenation: \"tic\"-\"tac\"-\"toe\" == \"tic-tac-toe\"",
        cat == "tic-tac-toe",
    );
    check(
        "format! borrows its arguments: all inputs stay usable",
        s1 == "tic" && s2 == "tac" && s3 == "toe",
    );
}

// ── Section F: indexing s[0] is FORBIDDEN; use .chars().nth() / byte slices ──

fn section_f() {
    banner("F — indexing s[0] is FORBIDDEN; use .chars().nth() / byte slices");
    let s = String::from("hi");
    println!("  let s = String::from(\"hi\");");
    println!("  // s[0]   <-- DOES NOT COMPILE (E0277; see STRINGS_STR.md)");

    // The allowed access: iterate scalar values. .next() == .chars().nth(0).
    let first_char = s.chars().next();
    println!(
        "  s.chars().next() = {:?}   (== .chars().nth(0); clippy prefers .next())",
        first_char
    );

    // General indexed access: .chars().nth(i) walks from the front — O(i), NOT O(1).
    let word = String::from("rust");
    let third_char = word.chars().nth(2);
    println!(
        "  \"rust\".chars().nth(2) = {:?}   (general form; O(i) walk from the front)",
        third_char
    );

    // A byte-range slice is allowed, but the bounds MUST land on a char boundary.
    let first_byte_slice: &str = &s[0..1]; // byte 1 is a boundary for ASCII "hi"
    println!(
        "  &s[0..1] = {:?}   (byte-range slice; byte 1 is a char boundary here)",
        first_byte_slice
    );

    let wave = "👋";
    let wave_first = wave.chars().next();
    println!(
        "  \"👋\".chars().next() = {:?}   (bytes 0..4 are one 4-byte char)",
        wave_first
    );

    check(
        "chars().next() of \"hi\" == Some('h')",
        first_char == Some('h'),
    );
    check(
        "chars().nth(2) of \"rust\" == Some('s')",
        third_char == Some('s'),
    );
    check(
        "byte-range slice &s[0..1] == \"h\" (byte 1 is a char boundary)",
        first_byte_slice == "h",
    );
}

fn main() {
    println!("strings_str.rs — Phase 1 bundle (String vs &str, UTF-8).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
