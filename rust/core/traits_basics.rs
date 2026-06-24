//! traits_basics.rs — Phase 2 bundle.
//!
//! GOAL (one line): show, by printing every value, how a Rust trait defines a
//! CONTRACT of behavior, how types IMPLEMENT it (with optional DEFAULT methods),
//! how `impl Trait` in argument/return position gives STATIC dispatch via
//! monomorphization (zero runtime cost), how supertraits compose contracts, and
//! how the orphan rule limits who may implement what for whom.
//!
//! This is the GROUND TRUTH for TRAITS_BASICS.md. Every value below is computed
//! by this file; the .md guide pastes it verbatim. Never hand-compute.
//!
//! Some trait rules are COMPILE ERRORS (the orphan rule: `impl Display for
//! Vec<T>` is E0117) and so cannot live in a runnable file — this binary would
//! not build. They are documented in Section F (commented) and in
//! TRAITS_BASICS.md with the exact compiler message.
//!
//! Run:
//!     just run traits_basics   (== cargo run --bin traits_basics)

use std::fmt;

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

// ── The contract used across Sections A–D ───────────────────────────────────
// A trait groups method SIGNATURES a type must provide, plus optional default
// bodies. `greet` has NO body -> every implementor MUST define it (required).
// `farewell` HAS a body -> a DEFAULT method an implementor may override or use
// as-is (demonstrated in Section B).
trait Greet {
    fn greet(&self) -> String; // required: no body, ends in `;`
    fn farewell(&self) -> String {
        // default: has a body
        String::from("(waves goodbye)")
    }
}

struct Dog {
    name: &'static str,
}

struct Cat {
    name: &'static str,
}

// impl Greet for Dog: Dog provides `greet`, and ACCEPTS the default `farewell`.
impl Greet for Dog {
    fn greet(&self) -> String {
        format!("Woof! (says {})", self.name)
    }
}

// impl Greet for Cat: Cat provides `greet`, and OVERRIDES the default `farewell`.
impl Greet for Cat {
    fn greet(&self) -> String {
        format!("Meow! (says {})", self.name)
    }
    fn farewell(&self) -> String {
        format!("{} stalks off", self.name)
    }
}

// ── Section C: `impl Trait` as a PARAMETER type (static dispatch) ───────────
// `g: &impl Greet` accepts any type that implements Greet. The compiler
// MONOMORPHIZES: it generates one specialized copy of `who` per concrete type
// passed (one for Dog, one for Cat), so the call is a direct, zero-cost static
// dispatch — no vtable, no runtime indirection.
fn who(g: &impl Greet) -> String {
    g.greet()
}

// ── Section D: `impl Trait` as a RETURN type ────────────────────────────────
// Returns SOME type implementing Greet without naming the concrete type. The
// concrete type here is Dog; callers see only the trait. This is also
// monomorphized / static dispatch. Constraint: only ONE concrete type may be
// returned per function (returning Dog OR Cat would fail to compile — see .md).
fn make_greeter() -> impl Greet {
    Dog { name: "Bot" }
}

// ── Section E: supertraits + multiple bounds ────────────────────────────────
// `Named` is a SUPERTRAIT; `Announce: Named` is a SUBTRAIT. Any type impl'ing
// Announce MUST also impl Named, and inside Announce we may call `self.name()`.
// (This is the Reference's `trait Circle: Shape` pattern, applied to Greet.)
trait Named {
    fn name(&self) -> &str;
}

trait Announce: Named {
    // default method that CALLS a supertrait method:
    fn announce(&self) -> String {
        format!(">> {} <<", self.name())
    }
}

struct Robot {
    id: &'static str,
}

impl fmt::Display for Robot {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Robot#{}", self.id)
    }
}

impl Named for Robot {
    fn name(&self) -> &str {
        self.id
    }
}

impl Announce for Robot {} // uses the default announce(); Named satisfied above

// A subtrait bound grants the supertrait's methods too: `a.name()` is legal here
// only because Announce: Named.
fn announce_for(a: &impl Announce) -> String {
    format!("{} says: {}", a.name(), a.announce())
}

// Multiple bounds with `+`: x must impl BOTH Named AND Display. (This is the
// Book's `&(impl Summary + Display)` shorthand; the long form is `<T: Named +
// fmt::Display>`.) Works on Robot because Robot impls both.
fn tag(x: &(impl Named + fmt::Display)) -> String {
    format!("[{}] {}", x.name(), x) // name() from Named, {} from Display
}

// ── Section F: the orphan rule — the two ALLOWED directions ────────────────
// You may impl a trait for a type only if you OWN at least one of them. The
// stdlib trait `Display` and the stdlib type `Vec` are FOREIGN to this crate.
// Direction 1 (allowed): FOREIGN trait on a LOCAL type.
struct Version {
    major: u32,
    minor: u32,
}

impl fmt::Display for Version {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}.{}", self.major, self.minor)
    }
}

// Direction 2 (allowed): LOCAL trait on a FOREIGN type.
trait SumExt {
    fn total(&self) -> i32;
}

impl SumExt for Vec<i32> {
    fn total(&self) -> i32 {
        self.iter().sum()
    }
}
//
// Direction 3 (FORBIDDEN -> error[E0117]): FOREIGN trait on a FOREIGN type.
//   impl fmt::Display for Vec<i32> { ... }   // both foreign -> E0117
// The compiler rejects it: "only traits defined in the current crate can be
// implemented for types defined outside of the crate". See TRAITS_BASICS.md.

// ── Section A: define a trait, implement it for types ───────────────────────

fn section_a() {
    banner("A — define a trait, implement it for types");
    let dog = Dog { name: "Rex" };
    let cat = Cat { name: "Mia" };
    println!("  trait Greet {{ fn greet(&self) -> String; }}");
    println!("  impl Greet for Dog   /   impl Greet for Cat");
    println!("    dog.greet() = {:?}", dog.greet());
    println!("    cat.greet() = {:?}", cat.greet());
    check(
        "Dog implements Greet: greet() == \"Woof! (says Rex)\"",
        dog.greet() == "Woof! (says Rex)",
    );
    check(
        "Cat implements Greet: greet() == \"Meow! (says Mia)\"",
        cat.greet() == "Meow! (says Mia)",
    );
}

// ── Section B: default methods — override or accept as-is ───────────────────

fn section_b() {
    banner("B — default method: one type overrides, one uses the default");
    let dog = Dog { name: "Rex" };
    let cat = Cat { name: "Mia" };
    println!("  trait Greet {{");
    println!("      fn greet(&self) -> String;                 // required");
    println!("      fn farewell(&self) -> String {{             // DEFAULT body");
    println!("          String::from(\"(waves goodbye)\")");
    println!("      }}");
    println!("  }}");
    println!(
        "    dog.farewell() = {:?}   (Dog: empty impl, uses DEFAULT)",
        dog.farewell()
    );
    println!(
        "    cat.farewell() = {:?}   (Cat: OVERRIDES farewell)",
        cat.farewell()
    );
    check(
        "Dog uses the DEFAULT farewell (no override in its impl)",
        dog.farewell() == "(waves goodbye)",
    );
    check(
        "Cat OVERRIDES the default farewell with its own body",
        cat.farewell() == "Mia stalks off",
    );
    check(
        "override vs default produce DISTINCT outputs",
        dog.farewell() != cat.farewell(),
    );
}

// ── Section C: `impl Trait` parameter — static dispatch via monomorphization ─

fn section_c() {
    banner("C — impl Trait param: fn who(g: &impl Greet), static dispatch");
    let dog = Dog { name: "Rex" };
    let cat = Cat { name: "Mia" };
    println!("  fn who(g: &impl Greet) -> String {{ g.greet() }}");
    println!("    who(&dog) = {:?}", who(&dog));
    println!("    who(&cat) = {:?}", who(&cat));
    println!("  (compiler emits ONE copy of `who` per concrete type -> zero-cost)");
    check(
        "who(&Dog) dispatches statically to Dog::greet",
        who(&dog) == "Woof! (says Rex)",
    );
    check(
        "who(&Cat) dispatches statically to Cat::greet",
        who(&cat) == "Meow! (says Mia)",
    );
}

// ── Section D: `impl Trait` return — a concrete type hidden behind the trait ─

fn section_d() {
    banner("D — impl Trait return: a concrete type hidden behind the trait");
    let g = make_greeter();
    println!("  fn make_greeter() -> impl Greet {{ Dog {{ name: \"Bot\" }} }}");
    println!("    make_greeter().greet() = {:?}", g.greet());
    println!("  (caller sees only `impl Greet`; the concrete Dog is hidden)");
    check(
        "a value returned as `impl Greet` is greetable (concrete type = Dog)",
        g.greet() == "Woof! (says Bot)",
    );
}

// ── Section E: supertrait + multiple bounds ─────────────────────────────────

fn section_e() {
    banner("E — supertrait (trait Announce: Named) + multiple bounds (+)");
    let robot = Robot { id: "R2" };
    println!("  trait Named {{ fn name(&self) -> &str; }}");
    println!("  trait Announce: Named {{ fn announce(&self) -> String {{ ... }} }}");
    println!("    robot.name()    = {:?}", robot.name());
    println!("    robot.announce()= {:?}", robot.announce());
    println!("    announce_for(&robot) = {:?}", announce_for(&robot));
    println!("  fn tag(x: &(impl Named + fmt::Display)) -> String  // multiple bounds");
    println!("    tag(&robot)     = {:?}", tag(&robot));
    check(
        "subtrait's default method calls the SUPERTRAIT method (self.name())",
        robot.announce() == ">> R2 <<",
    );
    check(
        "a subtrait bound grants the supertrait's methods (a.name() legal)",
        announce_for(&robot) == "R2 says: >> R2 <<",
    );
    check(
        "multiple bounds `Named + Display` let one fn use both behaviors",
        tag(&robot) == "[R2] Robot#R2",
    );
}

// ── Section F: the orphan rule (the two ALLOWED directions) ─────────────────

fn section_f() {
    banner("F — orphan rule: own the trait OR the type (else E0117)");
    let v = Version { major: 1, minor: 2 };
    let nums = vec![1, 2, 3, 4];
    println!("  Direction 1 (allowed): FOREIGN trait on a LOCAL type");
    println!(
        "    impl fmt::Display for Version  ->  format!(\"{{}}\", v) = {:?}",
        format!("{}", v)
    );
    println!("  Direction 2 (allowed): LOCAL trait on a FOREIGN type");
    println!(
        "    impl SumExt for Vec<i32>       ->  nums.total() = {}",
        nums.total()
    );
    println!("  Direction 3 (FORBIDDEN -> E0117):");
    println!("    // impl fmt::Display for Vec<i32> {{ .. }}   // both foreign");
    check(
        "Direction 1 OK: impl Display (foreign) for Version (local)",
        format!("{}", v) == "1.2",
    );
    check(
        "Direction 2 OK: impl SumExt (local) for Vec<i32> (foreign)",
        nums.total() == 10,
    );
}

fn main() {
    println!("traits_basics.rs — Phase 2 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
