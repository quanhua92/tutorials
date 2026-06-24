//! pattern_matching.rs — Phase 2 bundle.
//!
//! GOAL (one line): show, by printing every value, that a Rust *pattern* both
//! TESTS a value's shape (is it this variant? this length?) and DESTRUCTURES it
//! (binding the pieces it matched), that `match` is EXHAUSTIVE (every value must
//! be covered or the program will not compile — E0004), and that `if let` /
//! `while let` / `let else` are the single-pattern control-flow shapes built on
//! the same machinery — with the refutability rule deciding where each is legal.
//!
//! This is the GROUND TRUTH for PATTERN_MATCHING.md. Every number, table, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Several rules are COMPILE ERRORS (a non-exhaustive `match` -> E0004; a
//! refutable pattern such as `Some(x)` in a bare `let` -> E0005). Those cannot
//! live in a runnable file — this binary would not build. They are documented in
//! PATTERN_MATCHING.md with the exact compiler message.
//!
//! Run:
//!     just run pattern_matching   (== cargo run --bin pattern_matching)

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

// ── Data types used across the sections ─────────────────────────────────────

#[derive(Debug, Clone, Copy)]
struct Point {
    x: i32,
    y: i32,
}

#[derive(Debug, Clone, Copy)]
struct Color(i32, i32, i32); // a TUPLE struct: fields are positional

// A non-Copy struct: has a heap-owning `String` field, so the partial-move /
// `ref` example in Section A is meaningful (you genuinely move one field and
// borrow another instead of copying).
struct Person {
    name: String,
    age: u8,
}

// An enum with every variant shape: unit (Dot), tuple (Circle/Square), and
// struct-like (Rect). `area` must name ALL of them or it will not compile.
#[derive(Debug, Clone, Copy)]
enum Shape {
    Circle(i32),             // radius
    Rect { w: i32, h: i32 }, // named fields
    Square(i32),             // side
    Dot,                     // unit variant: no payload
}

// ── Section A: destructuring tuples and structs (pull fields apart) ─────────

fn section_a() {
    banner("A — destructuring tuples and structs (pull fields apart)");
    let pair: (i32, i32) = (3, 4);
    let (a, b) = pair;
    println!("  let (a, b) = (3, 4);   -> a = {a}, b = {b}");
    check(
        "tuple destructure: (a,b)=(3,4) -> a==3 && b==4",
        a == 3 && b == 4,
    );

    // Patterns nest arbitrarily: a tuple of (tuple, struct).
    let nested = ((1, 2), Point { x: 3, y: 4 });
    let ((p, q), Point { x, y }) = nested;
    println!(
        "  let ((p,q), Point{{x,y}}) = ((1,2), Point{{x:3,y:4}});  -> p={p}, q={q}, x={x}, y={y}"
    );
    check(
        "nested destructure binds every leaf: p==1, q==2, x==3, y==4",
        p == 1 && q == 2 && x == 3 && y == 4,
    );

    // Struct shorthand: `Point { x, y }` means `Point { x: x, y: y }`.
    let pt = Point { x: 3, y: 4 };
    let Point { x, y } = pt;
    println!("  let Point {{ x, y }} = Point{{x:3,y:4}};  -> x = {x}, y = {y}");
    check(
        "struct shorthand `Point{x,y}` binds x==3, y==4",
        x == 3 && y == 4,
    );

    // `..` ignores the rest: bind only the fields you care about.
    let pt2 = Point { x: 7, y: 9 };
    let Point { x: only_x, .. } = pt2;
    println!(
        "  let Point {{ x: only_x, .. }} = Point{{x:7,y:9}};  -> only_x = {only_x} (y ignored)"
    );
    check("`..` ignores remaining fields: only_x == 7", only_x == 7);

    // Tuple struct: destructure by position.
    let Color(r, g, b) = Color(16, 32, 48);
    println!("  let Color(r, g, b) = Color(16, 32, 48);  -> r={r}, g={g}, b={b}");
    check(
        "tuple-struct destructure by position: r==16, g==32, b==48",
        r == 16 && g == 32 && b == 48,
    );

    // `ref` inside a struct pattern: borrow one field while MOVING another.
    // `Person` is non-Copy (it owns a String), so this is a real partial move:
    // `name` is moved out (the String's owner is now `name`); `age` is borrowed
    // by reference through `ref age`. `person` is left partially moved.
    let person = Person {
        name: String::from("ada"),
        age: 36,
    };
    let Person { name, ref age } = person;
    println!("  let Person {{ name, ref age }} = Person{{name:\"ada\",age:36}};");
    println!("    name (moved out)  = \"{name}\"");
    println!("    *age (borrowed)   = {age}");
    check(
        "`ref` borrows a field while another is moved: name==\"ada\", *age==36",
        name == "ada" && *age == 36,
    );
}

// ── Section B: enum match with payload (exhaustive; every variant named) ────

/// Area of a `Shape`. This `match` names ALL four variants — no `_` catch-all.
/// If a variant were added to `Shape` later, this function would fail to
/// compile (E0004) until the new variant is handled. PI IS APPROXIMATED AS 3 so
/// every area is an exact integer (no float-equality pitfalls).
fn area(shape: Shape) -> i32 {
    match shape {
        Shape::Circle(r) => 3 * r * r,
        Shape::Rect { w, h } => w * h,
        Shape::Square(s) => s * s,
        Shape::Dot => 0,
    }
}

fn section_b() {
    banner("B — enum match with payload: exhaustive, every variant named");
    let circle_area = area(Shape::Circle(2)); // 3 * 2 * 2 = 12
    let rect_area = area(Shape::Rect { w: 2, h: 3 }); // 2 * 3 = 6
    let square_area = area(Shape::Square(4)); // 4 * 4 = 16
    let dot_area = area(Shape::Dot); // unit variant, no payload -> 0
    println!("  area(Shape::Circle(2))        = {circle_area}  (pi ~= 3)");
    println!("  area(Shape::Rect{{w:2,h:3}})  = {rect_area}");
    println!("  area(Shape::Square(4))        = {square_area}");
    println!("  area(Shape::Dot)              = {dot_area}  (unit variant)");
    check(
        "match Shape::Circle(r) payload binds r: Circle(2) area == 12",
        circle_area == 12,
    );
    check(
        "match Shape::Rect{w,h} struct payload binds fields: Rect{2,3} area == 6",
        rect_area == 6,
    );
    check(
        "match Shape::Square(s) payload binds s: Square(4) area == 16",
        square_area == 16,
    );
    check(
        "match Shape::Dot (unit variant, no payload): area == 0",
        dot_area == 0,
    );
}

// ── Section C: slice patterns: `[first, rest @ ..]`, `[first, .., last]` ────

fn section_c() {
    banner("C — slice patterns: [first, rest @ ..], [first, .., last]");
    // A FIXED-SIZE array `[i32; 3]`: an exact-length pattern is exhaustive by
    // itself (no `_` needed) — the length is known statically.
    let arr: [i32; 3] = [1, 2, 3];
    let [a0, a1, a2] = arr;
    println!("  let [a0, a1, a2] = [1, 2, 3];  -> a0={a0}, a1={a1}, a2={a2}");
    check(
        "array of known length 3 destructure positionally: 1, 2, 3",
        a0 == 1 && a1 == 2 && a2 == 3,
    );

    // A DYNAMIC-LENGTH slice `&[i32]`: the length is unknown at compile time, so
    // the match must cover every possible length (a `_`/`[..]` catch-all is
    // required). `..` is the REST pattern; `rest @ ..` BINDS the rest as a subslice.
    let slice: &[i32] = &[10, 20, 30];
    let (first, mid_len, last) = match slice {
        [first, rest @ .., last] => (*first, rest.len(), *last), // >= 2 elements
        [single] => (*single, 0, *single),                       // exactly 1
        [] => (0, 0, 0),                                         // empty
    };
    println!(
        "  match &[10,20,30] {{ [first, rest @ .., last] => .. }}  -> first={first}, rest.len={mid_len}, last={last}"
    );
    check(
        "slice [first, rest@.., last]: first==10, last==30, middle rest.len()==1",
        first == 10 && last == 30 && mid_len == 1,
    );
    check("the whole slice has length 3", slice.len() == 3);

    // head + tail: `[head, tail @ ..]` matches any non-empty slice.
    let (head, tail_len) = match slice {
        [head, tail @ ..] => (*head, tail.len()),
        [] => (0, 0),
    };
    println!(
        "  match &[10,20,30] {{ [head, tail @ ..] => .. }}  -> head={head}, tail.len={tail_len}"
    );
    check(
        "slice [head, tail@..]: head==10, tail.len()==2",
        head == 10 && tail_len == 2,
    );
}

// ── Section D: `@` bindings (capture a value a subpattern matched) ──────────

fn section_d() {
    banner("D — `@` bindings: capture a value that a subpattern matched");
    // `b @ 1..=5` tests the value against the range AND binds it to `b`. The
    // bound value is the MATCHED VALUE (3), not the range.
    let n = 3_i32;
    let label = match n {
        b @ 1..=5 => format!("small: {b}"),
        b @ 6..=9 => format!("mid: {b}"),
        b => format!("big: {b}"),
    };
    println!("  n = {n};  match {{ b @ 1..=5, b @ 6..=9, b }}  -> \"{label}\"");
    check(
        "`@ 1..=5` binds the matched value: n==3 matches, bound b==3",
        n == 3 && label == "small: 3",
    );

    // `p @ Point { x: 1..=5, .. }`: bind the WHOLE struct while testing one
    // field against a range. `@` takes the whole struct pattern as its
    // subpattern, so `p` is bound to the matched `Point`.
    let pt = Point { x: 4, y: 50 };
    let px = pt.x;
    let classified = match pt {
        p @ Point { x: 1..=5, .. } => format!("near (x={}, y={})", p.x, p.y),
        Point { x, .. } => format!("far x={x}"),
    };
    println!("  match Point{{x:4,y:50}} {{ p @ Point{{x:1..=5,..}} => .. }}  -> \"{classified}\"");
    check(
        "`@` binds whole Point while a field range test passes: x==4 caught by 1..=5",
        px == 4 && classified.starts_with("near"),
    );

    // Reference pattern `&n`: match THROUGH a reference and bind the dereffed
    // value. `&n` is IRREFUTABLE (any `&i32` matches), so it is legal in a `let`.
    let r: &i32 = &7;
    let &n = r;
    println!("  let &n = &7;  -> n = {n}  (the `&` pattern dereferences for you)");
    check(
        "reference pattern `&n` binds the dereffed value: n == 7",
        n == 7,
    );
}

// ── Section E: match guards `pattern if cond` (a runtime clause) ────────────

fn classify(n: i32) -> &'static str {
    match n {
        x if x % 2 == 0 => "even",
        _ => "odd", // `_` is STILL REQUIRED: a guard can fail, so the arm above
                    // is not guaranteed to match -> exhaustiveness is not satisfied by it.
    }
}

fn section_e() {
    banner("E — match guards: `pattern if cond` (a runtime clause)");
    let (e, o) = (classify(4), classify(9));
    println!("  classify(4) = \"{e}\"   classify(9) = \"{o}\"");
    check(
        "guard `x if x%2==0` matches: classify(4) == \"even\"",
        e == "even",
    );
    check(
        "guarded arm can fail -> `_` still required: classify(9) == \"odd\"",
        o == "odd",
    );

    // A guard can inspect MULTIPLE bound fields at once.
    let pt = Point { x: 5, y: 5 };
    let kind = match pt {
        Point { x, y } if x == y => "diagonal",
        _ => "off-diagonal",
    };
    println!(
        "  match Point{{x:5,y:5}} {{ Point{{x,y}} if x==y => \"diagonal\", _ => .. }}  -> \"{kind}\""
    );
    check(
        "guard on two bound struct fields: Point{x:5,y:5} -> \"diagonal\"",
        kind == "diagonal",
    );
}

// ── Section F: if let / while let / let else (single-pattern control flow) ───

fn section_f() {
    banner("F — if let / while let / let else (single-pattern control flow)");
    // LET-CHAINS (`if let P = e && let Q = f`): combine several `let` patterns
    // with `&&`. This peels an Option<Option<T>> in ONE conditional instead of a
    // nesting tower of `if let`s (the classic pre-let-chain shape). Stable since
    // Rust 1.88; clippy's `collapsible_if` actively suggests it.
    let nested: Option<Option<i32>> = Some(Some(7));
    let mut found: Option<i32> = None;
    if let Some(inner) = nested
        && let Some(v) = inner
    {
        found = Some(v);
    }
    println!("  let-chain on Option<Option<i32>> = Some(Some(7))  -> found = {found:?}");
    check(
        "let-chain `if let .. && let Some(v) = inner` peels Option<Option<7>> -> Some(7)",
        found == Some(7),
    );

    // `let else`: destructure-or-diverge. The bindings survive into the rest of
    // the block only on the match path; the `else` block MUST diverge (return /
    // break / panic / never return).
    let maybe: Option<i32> = Some(42);
    let Some(x) = maybe else {
        // Unreachable for `Some(42)`, but the compiler demands a diverging block.
        return;
    };
    println!("  let Some(x) = Some(42) else {{ return }};  -> x = {x}");
    check("`let else` binds x on the success path: x == 42", x == 42);

    // `while let` draining a Vec<Option<T>>. `pop()` is LIFO and deterministic,
    // so the collected order is byte-reproducible across runs.
    let mut stack: Vec<Option<i32>> = vec![Some(10), None, Some(20), Some(30), None];
    let mut somes: Vec<i32> = Vec::new();
    let mut nones: i32 = 0;
    while let Some(item) = stack.pop() {
        if let Some(v) = item {
            somes.push(v);
        } else {
            nones += 1;
        }
    }
    println!(
        "  drained Vec<Option<i32>> via while let + if let  -> somes = {somes:?}, nones = {nones}"
    );
    check(
        "`while let` drains the Vec in LIFO order: somes == [30, 20, 10]",
        somes == vec![30, 20, 10],
    );
    check(
        "`while let` counted the Nones on the way: nones == 2",
        nones == 2,
    );
    check(
        "`while let` stops when pop() returns None: stack now empty",
        stack.is_empty(),
    );
}

// ── Section G: refutability (refutable patterns CANNOT go in a bare `let`) ──

fn section_g() {
    banner("G — refutability: refutable patterns cannot go in a bare `let`");
    // `let Some(x) = opt;` is a COMPILE ERROR (E0005): `Some(x)` is REFUTABLE
    // (it fails on `None`), but a `let` binding accepts only IRREFUTABLE
    // patterns. That error cannot live in this runnable binary (it would not
    // build); it is shown verbatim in PATTERN_MATCHING.md. The two fixes:
    let opt: Option<i32> = Some(5);

    // Fix 1: `if let` — handle the match (and the miss, if you care).
    if let Some(x) = opt {
        println!("  if let Some(x) = Some(5)  -> x = {x}");
        check(
            "fix #1 `if let` carries the refutable pattern: x == 5",
            x == 5,
        );
    }

    // Fix 2: `let else` — destructure, or diverge on the miss.
    let Some(y) = opt else {
        return;
    };
    println!("  let Some(y) = Some(5) else {{ return }};  -> y = {y}");
    check(
        "fix #2 `let else` carries the refutable pattern: y == 5",
        y == 5,
    );

    // Irrefutable patterns are fine in a bare `let`: tuples, structs, `_`, a
    // plain name. They are guaranteed to match EVERY value of the type.
    let (a, b) = (1, 2);
    let Point { x, y } = Point { x: 3, y: 4 };
    println!("  irrefutable `let` patterns: (a,b) = ({a},{b});  Point{{x,y}} = ({x},{y})");
    check(
        "irrefutable patterns bind in plain `let`: a==1, b==2, x==3, y==4",
        a == 1 && b == 2 && x == 3 && y == 4,
    );
}

fn main() {
    println!("pattern_matching.rs — Phase 2 bundle.");
    println!("Every value below is computed by this file.");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    section_g();
    banner("DONE — all sections printed");
}
