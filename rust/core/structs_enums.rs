//! structs_enums.rs — Phase 2 bundle (Types, Traits & Generics).
//!
//! GOAL (one line): show, by printing every value, that a Rust **struct**
//! groups named/positional fields into one type, that an **enum** is a *tagged
//! union* (one discriminant tag + a per-variant payload), and that the stdlib
//! `Option<T>` / `Result<T,E>` enums are Rust's null- and error-handling.
//!
//! This is the GROUND TRUTH for STRUCTS_ENUMS.md. Every number, table, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Run:
//!     just run structs_enums   (== cargo run --bin structs_enums)

use std::f64::consts::PI;
use std::mem::discriminant;

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

// ── Shared types ────────────────────────────────────────────────────────────

/// A NAMED-FIELD struct: each field has a name. The most common struct form.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Point {
    x: i32,
    y: i32,
}

impl Point {
    /// Associated function (no `self`) — a constructor, used like `Vec::new`.
    /// Field init shorthand: `x` stands for `x: x`.
    fn new(x: i32, y: i32) -> Self {
        Point { x, y }
    }

    /// Method borrowing `self` immutably (`&self`): read access, no ownership
    /// taken, caller keeps the value.
    fn manhattan(&self) -> i32 {
        self.x.abs() + self.y.abs()
    }

    /// Method borrowing `self` mutably (`&mut self`): mutates in place.
    fn translate(&mut self, dx: i32, dy: i32) {
        self.x += dx;
        self.y += dy;
    }
}

/// A TUPLE struct: fields are positional (`.0`, `.1`, ...). A distinct new
/// type — `Color(255,0,0)` and a plain `(255,0,0)` tuple are NOT the same type.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Color(i32, i32, i32);

/// A UNIT struct: no fields. Zero bytes; useful as a marker / trait target.
#[derive(Debug)]
struct Marker;

/// An enum is a TAGGED UNION: one discriminant tag selects which single variant
/// is active; the payload shape varies per variant. `match` is exhaustive.
#[derive(Debug, Clone, PartialEq)]
enum Shape {
    /// unit-like variant: no data.
    Point,
    /// tuple variant: positional payload (`f64` radius).
    Circle(f64),
    /// struct variant: named-field payload.
    Rect { w: f64, h: f64 },
}

impl Shape {
    /// `match` is exhaustive: the compiler forces an arm for every variant.
    /// `&self` -> the match borrows; the caller keeps ownership of the shape.
    fn area(&self) -> f64 {
        match self {
            Shape::Point => 0.0,
            Shape::Circle(r) => PI * r * r,
            Shape::Rect { w, h } => w * h,
        }
    }

    /// `_` / `..` discard the payload when only the tag matters.
    fn label(&self) -> &'static str {
        match self {
            Shape::Point => "point",
            Shape::Circle(_) => "circle",
            Shape::Rect { .. } => "rect",
        }
    }
}

// ── Section A: named struct + impl (methods, associated fns, update syntax) ─

fn section_a() {
    banner("A — named struct + impl: &self, &mut self, associated fn, update");
    let p = Point::new(3, 4); // associated fn (constructor); shorthand inside
    println!(
        "  Point::new(3, 4)        -> Point {{ x: {}, y: {} }}",
        p.x, p.y
    );
    println!("  p.manhattan() = |{}|+|{}| = {}", p.x, p.y, p.manhattan());
    check("Point{x:3,y:4}.manhattan() == 7", p.manhattan() == 7);

    // &mut self mutates in place.
    let mut q = Point::new(1, 1);
    q.translate(2, 5);
    println!(
        "  q.translate(2, 5)       -> Point {{ x: {}, y: {} }}",
        q.x, q.y
    );
    check(
        "&mut self mutates in place: (1,1)+(2,5) == (3,6)",
        q == Point::new(3, 6),
    );

    // Struct update syntax: `..p` fills the remaining fields from `p`.
    // Point is Copy -> the copied fields are duplicated, so `p` stays usable.
    let r = Point { y: 100, ..p };
    println!(
        "  Point {{ y: 100, ..p }} -> Point {{ x: {}, y: {} }}",
        r.x, r.y
    );
    check(
        "update syntax copies x: Point{y:100,..P{3,4}} == (3,100)",
        r == Point::new(3, 100),
    );
    check(
        "source p still usable after `..p` (Point is Copy)",
        p == Point::new(3, 4),
    );
}

// ── Section B: tuple struct (positional) + unit struct (no fields) ──────────

fn section_b() {
    banner("B — tuple struct (.0/.1 access) + unit struct (0 bytes)");
    let red = Color(255, 0, 0);
    println!("  let red = Color(255, 0, 0);");
    println!(
        "    red.0 = {}, red.1 = {}, red.2 = {}",
        red.0, red.1, red.2
    );
    check(
        "tuple struct fields are positional: red.0 == 255",
        red.0 == 255,
    );

    // Destructuring a tuple struct requires naming the type.
    let Color(r, g, b) = red;
    println!("  let Color(r, g, b) = red; -> ({}, {}, {})", r, g, b);
    check(
        "tuple struct destructures by position: (r,g,b)==(255,0,0)",
        (r, g, b) == (255, 0, 0),
    );

    // Unit struct: instantiated by its name, no parens/braces.
    let _m = Marker;
    let _ = _m; // keep `_m` "used" for clarity
    println!("  let _m = Marker;   // unit struct: no data");
    check(
        "unit struct Marker occupies 0 bytes",
        std::mem::size_of::<Marker>() == 0,
    );
}

// ── Section C: enum = tagged union; exhaustive match ────────────────────────

fn section_c() {
    banner("C — enum = tagged union (tag + payload); exhaustive match");
    let shapes = [
        Shape::Point,
        Shape::Circle(2.0),
        Shape::Rect { w: 3.0, h: 4.0 },
    ];
    for s in &shapes {
        println!("  {:?}: label={}, area={:.3}", s, s.label(), s.area());
    }

    check("Shape::Point.area() == 0.0", Shape::Point.area() == 0.0);
    check(
        "Shape::Circle(2.0).area() == pi*r^2 == 12.566...",
        Shape::Circle(2.0).area() == PI * 2.0 * 2.0,
    );
    check(
        "Shape::Rect{w:3,h:4}.area() == 12.0",
        Shape::Rect { w: 3.0, h: 4.0 }.area() == 12.0,
    );

    // The discriminant (tag) is SEPARATE from the payload: two circles with
    // different radii share the SAME tag. std::mem::discriminant exposes it.
    println!(
        "  size_of::<Shape>() = {} bytes  (max payload + tag + padding)",
        std::mem::size_of::<Shape>()
    );
    check(
        "same variant -> equal discriminant (tag independent of payload)",
        discriminant(&Shape::Circle(1.0)) == discriminant(&Shape::Circle(9.0)),
    );
    check(
        "different variant -> unequal discriminant",
        discriminant(&Shape::Circle(1.0)) != discriminant(&Shape::Point),
    );
}

// ── Section D: Option<T> — Some/None, match, if let, ? ──────────────────────

/// First even number in `xs`, or `None`. `Option<T>` is Rust's replacement for
/// `null` (Tony Hoare's "billion-dollar mistake") — the type system forces you
/// to handle the absent case. Iterator `.find()` returns `Option<&T>` directly,
/// and `.copied()` lifts it to `Option<T>`.
fn find_even(xs: &[i32]) -> Option<i32> {
    xs.iter().find(|&&x| x % 2 == 0).copied()
}

/// `?` on `Option`: returns early with `None` if the operand is `None`, else
/// unwraps the `Some`. Propagates absence upward without an explicit match.
fn first_even_doubled(xs: &[i32]) -> Option<i32> {
    let e = find_even(xs)?;
    Some(e * 2)
}

fn section_d() {
    banner("D — Option<T>: Some/None, match, if let, and ?");
    let with_even = [1, 2, 3];
    let without = [1, 3, 5];
    println!("  find_even([1,2,3]) = {:?}", find_even(&with_even));
    println!("  find_even([1,3,5]) = {:?}", find_even(&without));

    check(
        "find_even([1,2,3]) == Some(2)",
        find_even(&with_even) == Some(2),
    );
    check("find_even([1,3,5]) is None", find_even(&without).is_none());

    // match forces BOTH arms -> no null dereference is possible.
    match find_even(&with_even) {
        Some(n) => println!("  match Some: first even = {}", n),
        None => println!("  match None: no even"),
    }

    // if let: sugar for a single-arm match.
    if let Some(n) = find_even(&without) {
        println!("  if let Some: found {}", n);
    } else {
        println!("  if let None  -> else branch");
    }

    // ? propagates None automatically through the call chain.
    println!(
        "  first_even_doubled([1,2,3]) = {:?}",
        first_even_doubled(&with_even)
    );
    println!(
        "  first_even_doubled([1,3,5]) = {:?}",
        first_even_doubled(&without)
    );
    check(
        "? propagates None: doubled([1,2,3]) == Some(4)",
        first_even_doubled(&with_even) == Some(4),
    );
    check(
        "? propagates None: doubled([1,3,5]) == None",
        first_even_doubled(&without).is_none(),
    );
}

// ── Section E: Result<T,E> — Ok/Err, match, ? ───────────────────────────────

/// Parse `s` to `i32`, returning `Result<i32, &str>`. `Result<T,E>` is Rust's
/// error-handling enum: `Ok(T)` on success, `Err(E)` on failure. The compiler
/// forces you to deal with the error path.
fn parse_i32(s: &str) -> Result<i32, &'static str> {
    s.parse::<i32>().map_err(|_| "not a valid i32")
}

/// `?` on `Result`: returns early with `Err` on the first failing field, else
/// unwraps the `Ok`. Requires the enclosing fn to return a `Result`.
fn sum_parsed(fields: &[&str]) -> Result<i32, &'static str> {
    let mut total = 0;
    for f in fields {
        total += parse_i32(f)?;
    }
    Ok(total)
}

fn section_e() {
    banner("E — Result<T,E>: Ok/Err, match, and ? propagation");
    let good = parse_i32("42");
    let bad = parse_i32("x");
    println!("  parse_i32(\"42\") = {:?}", good);
    println!("  parse_i32(\"x\")  = {:?}", bad);

    check("parse \"42\" -> Ok(42)", good == Ok(42));
    check("parse \"x\"  -> Err", bad.is_err());

    // match on Result handles both paths explicitly.
    match good {
        Ok(n) => println!("  match Ok(\"42\")  -> {}", n),
        Err(e) => println!("  match Err      -> {}", e),
    }
    match bad {
        Ok(n) => println!("  match Ok       -> {}", n),
        Err(e) => println!("  match Err(\"x\") -> {}", e),
    }

    // ? propagates Err on the first bad input.
    let total = sum_parsed(&["10", "20", "30"]);
    let partial = sum_parsed(&["10", "oops", "30"]);
    println!("  sum_parsed([\"10\",\"20\",\"30\"]) = {:?}", total);
    println!("  sum_parsed([\"10\",\"oops\",\"30\"]) = {:?}", partial);
    check(
        "? propagates Err: sum of clean inputs == Ok(60)",
        total == Ok(60),
    );
    check(
        "? propagates Err: sum with a bad input is Err",
        partial.is_err(),
    );
}

// ── Section F: #[derive(...)] — Debug, PartialEq, Clone, Copy ───────────────

/// Owned data (`String`) -> legitimately derives `Clone` but NOT `Copy`
/// (`String` is not `Copy`). Demonstrates derive only emits what the fields
/// allow.
#[derive(Debug, Clone, PartialEq)]
struct Person {
    name: String,
    age: u32,
}

/// All-`Copy` fields (`f64`) -> legitimately derives `Copy` + `Clone`.
/// Assignment COPIES (both bindings stay valid) instead of moving.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Vec2 {
    x: f64,
    y: f64,
}

impl Vec2 {
    fn new(x: f64, y: f64) -> Self {
        Self { x, y }
    }
}

fn section_f() {
    banner("F — #[derive(...)]: Debug, PartialEq, Clone, Copy");
    let p = Person {
        name: String::from("ada"),
        age: 36,
    };

    // Debug ({:?}): derived for free; format!/println! can print the struct.
    let dbg = format!("{:?}", p);
    println!("  let p = Person {{ name: \"ada\", age: 36 }};");
    println!("  format!(\"{{:?}}\", p) = {}", dbg);
    check(
        "#[derive(Debug)] -> debug string contains the type name \"Person\"",
        dbg.contains("Person"),
    );

    // PartialEq: derived -> `==` compares fields structurally.
    let q = Person {
        name: String::from("ada"),
        age: 36,
    };
    check(
        "#[derive(PartialEq)] -> field-wise equal structs compare ==",
        p == q,
    );

    // Clone: for non-Copy types, .clone() is the real (needed) deep copy. `p`
    // is used again below, so moving is impossible -> the clone is required.
    let r = p.clone();
    println!("  let r = p.clone();   -> {:?}", r);
    check(
        "#[derive(Clone)] -> clone yields an equal, independent value",
        r == p,
    );

    // Vec2 is Copy: assignment copies (source stays usable), no move/poison.
    let a = Vec2::new(1.0, 2.0);
    let b = a;
    println!("  let a = Vec2::new(1.0,2.0); let b = a;  (Copy)");
    println!("    a = {:?}, b = {:?}  (both usable)", a, b);
    check(
        "#[derive(Copy)] (all-Copy fields) -> source stays usable after assign",
        a == b,
    );
}

fn main() {
    println!("structs_enums.rs — Phase 2 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
