//! trait_objects.rs — Phase 2 bundle.
//!
//! GOAL (one line): show, by printing every value, that `dyn Trait` is a
//! dynamically-dispatched *trait object* — a FAT pointer (data + vtable) that can
//! hold ANY concrete type implementing the trait, resolved at runtime via the
//! vtable — the dynamic counterpart to the STATIC `impl Trait` of TRAITS_BASICS.
//!
//! This is the GROUND TRUTH for TRAIT_OBJECTS.md. Every value below is computed
//! by this file. Change it -> re-run -> re-paste. Never hand-compute.
//!
//! Some trait-object rules are COMPILE ERRORS (using a non-dyn-compatible trait
//! as `dyn`, error E0038). Those cannot live in a runnable file — this binary
//! would not build. They are documented in TRAIT_OBJECTS.md with the exact
//! compiler message.
//!
//! Run:
//!     just run trait_objects   (== cargo run --bin trait_objects)

const BANNER_WIDTH: usize = 70;

fn banner(title: &str) {
    let bar = "=".repeat(BANNER_WIDTH);
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

// ── The shared, fully dyn-compatible trait used throughout ────────────────────
//
// Object-safe: one method, takes `&self`, no generic type params, does not
// return `Self`. Every method is dispatchable through a vtable entry.

trait Greet {
    fn greet(&self) -> String;
}

#[derive(Clone, Copy)]
struct Dog;
#[derive(Clone, Copy)]
struct Cat;

impl Greet for Dog {
    fn greet(&self) -> String {
        String::from("Woof!")
    }
}

impl Greet for Cat {
    fn greet(&self) -> String {
        String::from("Meow!")
    }
}

// ── Section A: Box<dyn Trait> — ONE owned slot, ANY concrete type ────────────

fn section_a() {
    banner("A — Box<dyn Greet>: ONE owned slot, ANY concrete type (type erasure)");
    // A `Box<dyn Greet>` is an OWNED trait object on the heap. The concrete type
    // is ERASED: the slot only promises "something that greets". Which `greet`
    // impl runs is decided at runtime via the vtable.
    let mut b: Box<dyn Greet> = Box::new(Dog);
    println!("  let b: Box<dyn Greet> = Box::new(Dog);");
    println!(
        "    b.greet() = {:?}   <- Dog's impl, chosen at RUNTIME via vtable",
        b.greet()
    );
    check(
        "Box<dyn Greet> dispatches to Dog::greet at runtime",
        b.greet() == "Woof!",
    );

    // Reassigning the slot drops the OLD value (Dog) and stores Cat — the very
    // same ownership rule as OWNERSHIP.rs Section D. Same `Box<dyn Greet>` type,
    // a DIFFERENT concrete payload behind it.
    b = Box::new(Cat);
    println!("  b = Box::new(Cat);    // old Dog dropped; SAME type `Box<dyn Greet>`");
    println!("    b.greet() = {:?}   <- Cat's impl now", b.greet());
    check(
        "after reassign, the trait object dispatches to Cat::greet",
        b.greet() == "Meow!",
    );
}

// ── Section B: &dyn Trait — a BORROWED trait object (no move) ─────────────────

/// Takes a BORROWED trait object: `&dyn Greet`. No ownership moves; the caller
/// keeps its value. The same `loud` works for a reference to ANY greeter.
fn loud(g: &dyn Greet) -> String {
    format!("{}!!", g.greet().to_uppercase())
}

fn section_b() {
    banner("B — &dyn Greet: a borrowed trait object (no ownership moves)");
    let dog = Dog;
    let cat = Cat;
    // The SAME `loud` works for both Dog and Cat — late binding at runtime.
    println!("  loud(&Dog) = {:?}", loud(&dog));
    println!("  loud(&Cat) = {:?}", loud(&cat));
    check("&dyn Greet works for Dog", loud(&dog) == "WOOF!!!");
    check("&dyn Greet works for Cat", loud(&cat) == "MEOW!!!");
    // The callers still own their values — borrowing a trait object never moves.
    check(
        "borrowing a trait object does NOT move the owner's value",
        dog.greet() == "Woof!",
    );
}

// ── Section C: the FAT pointer = (data ptr) + (vtable ptr) = 2 words ──────────

fn section_c() {
    banner("C — the FAT pointer: (data ptr) + (vtable ptr) = 2 words");
    // A reference to a concrete SIZED type is a THIN pointer: exactly 1 word.
    let thin = std::mem::size_of::<&Dog>();
    // A reference to `dyn Greet` is a FAT pointer: 2 words = (data, vtable). The
    // Reference guarantees pointers to DSTs (like trait objects) carry the extra
    // vtable word; it does NOT guarantee the FIELD ORDER (see pitfalls).
    let fat = std::mem::size_of::<&dyn Greet>();
    let word = std::mem::size_of::<usize>();
    println!(
        "  size_of::<&Dog>()       = {} bytes = 1 word   (thin pointer: just the address)",
        thin
    );
    println!(
        "  size_of::<&dyn Greet>() = {} bytes = 2 words  (fat pointer: data + vtable)",
        fat
    );
    check(
        "&Dog is a thin pointer: size == 1 * size_of::<usize>()",
        thin == word,
    );
    check(
        "&dyn Greet is a fat pointer: size == 2 * size_of::<usize>() (data + vtable)",
        fat == 2 * word,
    );
    // `Box<dyn Greet>` is ALSO 2 words: a Box just owns the fat pointer verbatim
    // (plus the heap allocation it points at), it does not grow it.
    let box_dyn = std::mem::size_of::<Box<dyn Greet>>();
    println!(
        "  size_of::<Box<dyn Greet>>() = {} bytes = 2 words  (holds the fat pointer)",
        box_dyn
    );
    check(
        "Box<dyn Greet> == 2 words too (it stores the fat pointer)",
        box_dyn == 2 * word,
    );
}

// ── Section D: heterogeneous Vec<Box<dyn Trait>> — the headline use case ──────

fn section_d() {
    banner("D — heterogeneous Vec<Box<dyn Greet>>: TWO types in ONE collection");
    // The whole point: a single Vec holding DIFFERENT concrete types that share
    // the trait. A generic `Vec<T>` CANNOT do this — one T per Vec, all-equal.
    // (See the E0038-adjacent compile note in TRAIT_OBJECTS.md Section D.)
    let zoo: Vec<Box<dyn Greet>> = vec![Box::new(Dog), Box::new(Cat)];
    println!("  let zoo: Vec<Box<dyn Greet>> = vec![Box::new(Dog), Box::new(Cat)];");
    for (i, a) in zoo.iter().enumerate() {
        println!(
            "    zoo[{i}].greet() = {:?}   (concrete type erased)",
            a.greet()
        );
    }
    check("heterogeneous Vec holds exactly 2 elements", zoo.len() == 2);
    check("zoo[0] greets as Dog (Woof!)", zoo[0].greet() == "Woof!");
    check("zoo[1] greets as Cat (Meow!)", zoo[1].greet() == "Meow!");
    check(
        "every element is greetable regardless of its (erased) concrete type",
        zoo.iter().all(|a| !a.greet().is_empty()),
    );
}

// ── Section E: object safety (dyn compatibility) — what CANNOT be `dyn` ───────
//
// Two dyn-INCOMPATIBLE traits. DEFINING them compiles fine; what fails (E0038) is
// trying to use them as `dyn` (e.g. `Box<dyn Transformer>`). Here we use them
// only via STATIC dispatch on concrete types.

/// dyn-INCOMPATIBLE #1: a method with a generic type parameter `T`. The vtable
/// would need one entry per concrete `T` ever fed to it — unbounded, impossible
/// to build. Attempting `Box<dyn Transformer>` is error E0038.
trait Transformer {
    fn apply<T: std::fmt::Display>(&self, x: T) -> String;
}

impl Transformer for u64 {
    fn apply<T: std::fmt::Display>(&self, x: T) -> String {
        format!("applied to {x} with seed {self}")
    }
}

/// dyn-INCOMPATIBLE #2: a method that returns `Self`. At a `dyn` call site the
/// concrete type is unknown, so the return size/type cannot be determined.
/// Attempting `Box<dyn Duplicator>` is error E0038.
#[derive(PartialEq, Eq)]
struct Mark(u32);

trait Duplicator {
    fn duplicate(&self) -> Self;
}

impl Duplicator for Mark {
    fn duplicate(&self) -> Self {
        Mark(self.0)
    }
}

fn section_e() {
    banner("E — object safety (dyn compatibility): what CANNOT be `dyn`");
    // #1: generic method. Usable statically (concrete `T` known at the call
    // site) but REFUSES to become a trait object.
    let seed = 42u64;
    let r1 = seed.apply(7u8);
    println!("  Transformer: seed.apply::<u8>(7) = {:?}", r1);
    check(
        "a trait with a generic method still works via STATIC dispatch",
        r1 == "applied to 7 with seed 42",
    );

    // #2: returns Self. Fine statically (concrete type known at compile time),
    // but `dyn` is impossible.
    let m = Mark(5);
    let r2 = m.duplicate();
    println!("  Duplicator: Mark(5).duplicate() = Mark({})", r2.0);
    check(
        "returning Self works statically, just not as a trait object",
        r2 == Mark(5),
    );

    // Both traits REFUSE `dyn`. The verbatim E0038 compiler messages for
    // `Box<dyn Transformer>` and `Box<dyn Duplicator>` are in TRAIT_OBJECTS.md
    // Section E — they cannot live in this runnable file (it would not build).
}

// ── Section F: STATIC (generics) vs DYNAMIC (dyn) — same result, different codegen ─

/// STATIC dispatch: a GENERIC function. The compiler monomorphizes a SEPARATE
/// copy per concrete type used (`greet_all::<Dog>`, `greet_all::<Cat>`, ...) —
/// each call is a direct, inlinable call. This is the TRAITS_BASICS / GENERICS
/// path. It requires a HOMOGENEOUS collection (all elements the same type T).
fn greet_all<T: Greet>(items: &[T]) -> Vec<String> {
    items.iter().map(|x| x.greet()).collect()
}

/// DYNAMIC dispatch: ONE function, taking trait objects. No monomorphization;
/// every `.greet()` is an indirect call loaded from the vtable (not inlinable).
/// It accepts a HETEROGENEOUS collection (any mix of greeters behind `Box<dyn>`).
fn greet_all_dyn(items: &[Box<dyn Greet>]) -> Vec<String> {
    items.iter().map(|x| x.greet()).collect()
}

fn section_f() {
    banner("F — static (generics) vs dynamic (dyn): same result, different codegen");
    // STATIC: homogeneous &[Dog]. The compiler stamps out `greet_all::<Dog>`.
    let dogs = [Dog, Dog];
    let s = greet_all(&dogs);
    println!("  static   greet_all(&[Dog, Dog])   = {:?}", s);

    // DYNAMIC: heterogeneous &[Box<dyn Greet>] holding Dog AND Cat in one slice.
    let zoo: Vec<Box<dyn Greet>> = vec![Box::new(Dog), Box::new(Cat)];
    let d = greet_all_dyn(&zoo);
    println!("  dynamic  greet_all_dyn(&zoo)      = {:?}", d);

    check(
        "static dispatch gives identical results for the homogeneous Dog case",
        s == vec![String::from("Woof!"), String::from("Woof!")],
    );
    check(
        "dynamic dispatch handles the HETEROGENEOUS case (Dog+Cat) that static generics cannot",
        d == vec![String::from("Woof!"), String::from("Meow!")],
    );
    // The OBSERVABLE behavior matches; the difference is purely in codegen:
    //   static  -> N specialized copies, direct calls, inlinable (zero-cost).
    //   dynamic -> 1 copy, indirect vtable calls, not inlinable (small runtime cost).
    // See TRAIT_OBJECTS.md Section F for the monomorphization-vs-vtable diagram.
}

fn main() {
    println!("trait_objects.rs — Phase 2 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
