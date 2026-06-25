//! modules.rs — Phase 5 bundle.
//!
//! GOAL (one line): show, by printing every value, how Rust's MODULE system
//! controls NAMESPACES and VISIBILITY — all resolved statically at compile
//! time, with zero runtime cost.
//!
//! This is the GROUND TRUTH for MODULES.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Several module rules are COMPILE ERRORS (e.g. calling a private fn from
//! outside its module). Those cannot live in a runnable file — this binary
//! would not build. They are documented in MODULES.md with the exact compiler
//! message (E0603 / E0624 / E0432).
//!
//! This file is a SINGLE `[[bin]]`. Cross-file modules (`mod foo;` -> foo.rs)
//! cannot be demonstrated in one runnable file, so the MODULE system is shown
//! here via INLINE `mod foo { ... }` blocks (which are real modules, identical
//! in semantics). The cross-file FILE-TREE form is documented in Section F and
//! MODULES.md with a concrete directory tree.
//!
//! Run:
//!     just run modules   (== cargo run --bin modules)

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

// ── The module tree used by Sections A–F (all INLINE mods; real modules) ─────

// Section A: the simplest module — private by default, `pub` exposes an item.
mod inner {
    fn private_greet() -> &'static str {
        "(inner secret)"
    }
    pub fn public_greet() -> &'static str {
        "hello from inner::public"
    }
    // A descendant (the same module) CAN touch the private fn: privacy only
    // restricts access from OUTSIDE the module, not from within it.
    pub fn leak_via_sibling() -> &'static str {
        private_greet()
    }
}

// Section B: the four-way visibility ladder — pub / pub(crate) / pub(super) /
// pub(in path) — plus a wholly-private fn. `vis` is nested inside `outer` so
// that `pub(super)` (parent = `outer`) is meaningfully different from
// `pub(crate)` (the whole crate).
mod outer {
    pub mod vis {
        pub fn pub_anywhere() -> u32 {
            1
        }
        pub(crate) fn pub_crate() -> u32 {
            2
        }
        pub(super) fn pub_parent() -> u32 {
            3
        }
        pub(in crate::outer) fn pub_scope() -> u32 {
            4
        }
        fn private_fn() -> u32 {
            5
        }
        // From WITHIN `vis`, every one of the five is callable — a module can
        // always see its own items regardless of visibility annotation.
        pub fn call_all_from_inside() -> [u32; 5] {
            [
                pub_anywhere(),
                pub_crate(),
                pub_parent(),
                pub_scope(),
                private_fn(),
            ]
        }
    }

    // `outer` is the PARENT of `vis`, so it can reach `pub(super)` and
    // `pub(in crate::outer)` items — but the crate root cannot.
    pub fn call_from_parent() -> [u32; 4] {
        [
            vis::pub_anywhere(),
            vis::pub_crate(),
            vis::pub_parent(),
            vis::pub_scope(),
        ]
    }
}

// Section C: a module whose items we will `use`-import in several forms.
mod warehouse {
    pub fn ship() -> &'static str {
        "shipped"
    }
    pub fn stock() -> &'static str {
        "stocked"
    }
    pub fn audit() -> &'static str {
        "audited"
    }
    pub struct Parcel {
        pub id: u32,
    }
}

// Section D: a two-level module tree for demonstrating `self` / `super` /
// `crate::` path keywords. `crate_root_helper` lives at the CRATE ROOT so that
// `crate::crate_root_helper()` is an absolute path.
fn crate_root_helper() -> &'static str {
    "crate_root_helper"
}

mod network {
    pub fn net_fn() -> &'static str {
        "network::net_fn"
    }

    pub mod server {
        fn handler() -> &'static str {
            "server::handler"
        }
        // self:: = the CURRENT module (server).
        pub fn via_self() -> &'static str {
            self::handler()
        }
        // super:: = the PARENT module (network).
        pub fn via_super() -> &'static str {
            super::net_fn()
        }
        // super::super:: = two levels up (the crate root).
        pub fn via_super_super() -> &'static str {
            super::super::crate_root_helper()
        }
        // crate:: = ABSOLUTE path from the crate root.
        pub fn via_crate() -> &'static str {
            crate::crate_root_helper()
        }
    }
}

// Section E: the re-export / facade pattern. `base` and `other` are private
// modules; `pub use` lifts selected items up to the crate root's namespace.
mod base {
    pub fn x() -> &'static str {
        "base::x"
    }
}
mod other {
    pub fn z() -> &'static str {
        "other::z"
    }
}
pub use base::x;
pub use other::z as facade_z;

// Section F: nested inline mods still form a real dotted module path, which
// `module_path!()` reports. This ties the inline form to the file-tree form.
mod demo_path {
    pub mod nested {
        pub fn where_am_i() -> &'static str {
            module_path!()
        }
    }
}

// ── Section A: inline `mod` — items PRIVATE by default; `pub` exposes ───────

fn section_a() {
    banner("A — inline `mod`: items PRIVATE by default; `pub` exposes");
    println!("  mod inner {{");
    println!(
        "      fn private_greet() -> \"(inner secret)\"   // private: only inner + descendants"
    );
    println!("      pub fn public_greet() -> \"hello from inner::public\"");
    println!("      pub fn leak_via_sibling() -> private_greet()   // descendant reaches private");
    println!("  }}");
    let g = inner::public_greet();
    println!("  inner::public_greet() -> {:?}", g);
    let leaked = inner::leak_via_sibling();
    println!(
        "  inner::leak_via_sibling() -> {:?}  (sibling inside inner calls the private fn)",
        leaked
    );
    check(
        "inner::public_greet() callable from the crate root (parent of inner)",
        g == "hello from inner::public",
    );
    check(
        "a sibling inside `inner` CAN call the private fn (privacy = outside-only)",
        leaked == "(inner secret)",
    );
}

// ── Section B: pub / pub(crate) / pub(super) / pub(in path) / private ────────

fn section_b() {
    banner("B — visibility ladder: pub / pub(crate) / pub(super) / pub(in path) / private");
    println!("  mod outer {{ pub mod vis {{");
    println!("      pub          fn pub_anywhere() -> 1;   // visible everywhere reachable");
    println!("      pub(crate)   fn pub_crate()   -> 2;   // visible in this whole crate");
    println!("      pub(super)   fn pub_parent()  -> 3;   // visible to `outer` (the parent)");
    println!("      pub(in crate::outer) fn pub_scope() -> 4;  // visible in the `outer` subtree");
    println!("                     fn private_fn()  -> 5;   // visible only inside `vis`");
    println!("  }} }}");
    println!();

    // From the CRATE ROOT: pub and pub(crate) are reachable.
    let p1 = outer::vis::pub_anywhere();
    let p2 = outer::vis::pub_crate();
    println!("  crate-root calls outer::vis::pub_anywhere() -> {}", p1);
    println!(
        "  crate-root calls outer::vis::pub_crate()   -> {}  (crate root is in the crate)",
        p2
    );

    // From WITHIN `vis`: all five are callable.
    let inside = outer::vis::call_all_from_inside();
    println!(
        "  vis::call_all_from_inside() -> {:?}  (a module sees ALL its own items)",
        inside
    );

    // From `outer` (the PARENT of `vis`): pub, pub(crate), pub(super), pub(in outer).
    let parent = outer::call_from_parent();
    println!(
        "  outer::call_from_parent()   -> {:?}  (parent reaches pub(super) + pub(in outer))",
        parent
    );

    check(
        "pub: outer::vis::pub_anywhere() == 1 from the crate root",
        p1 == 1,
    );
    check(
        "pub(crate): outer::vis::pub_crate() == 2 from the crate root",
        p2 == 2,
    );
    check(
        "from inside `vis`, all 5 items are callable: [1,2,3,4,5]",
        inside == [1, 2, 3, 4, 5],
    );
    check(
        "from `outer` (parent), pub+pub(crate)+pub(super)+pub(in outer) reachable: [1,2,3,4]",
        parent == [1, 2, 3, 4],
    );
}

// ── Section C: `use` — single, grouped, alias (idiom: module for fns, full for types) ─

fn section_c() {
    banner("C — `use`: single / grouped / alias  (idiom: module for fns, full path for types)");
    // Idiom for FUNCTIONS: bring the parent MODULE in, then call fn() via it.
    // (We bring the fns directly here to also show the direct form.)
    use warehouse::Parcel as Box;
    use warehouse::ship; // single import
    use warehouse::{audit, stock}; // grouped import (one shared prefix) // `as` alias -> local name `Box`

    println!("  use warehouse::ship;                  // single");
    println!("  use warehouse::{{audit, stock}};         // grouped (shared prefix)");
    println!("  use warehouse::Parcel as Box;         // alias -> local name `Box`");
    let s = ship();
    let st = stock();
    let au = audit();
    let parcel = Box { id: 1 }; // `Box` is now `warehouse::Parcel`
    println!(
        "  ship()={:?}, stock()={:?}, audit()={:?}, Parcel{{id:{}}} via `Box`",
        s, st, au, parcel.id
    );
    check(
        "use warehouse::ship; brings ship() into scope",
        s == "shipped",
    );
    check(
        "use warehouse::{audit, stock}; groups imports (both callable)",
        st == "stocked" && au == "audited",
    );
    check(
        "use warehouse::Parcel as Box; aliases the struct (Box.id == 1)",
        parcel.id == 1,
    );
}

// ── Section D: path keywords — self / super / crate:: (absolute vs relative) ─

fn section_d() {
    banner("D — path keywords: self:: / super:: / crate::  (relative vs absolute)");
    println!("  fn crate_root_helper() -> \"crate_root_helper\"   // lives at the CRATE ROOT");
    println!("  mod network {{ pub fn net_fn(){{...}}");
    println!("      pub mod server {{ fn handler(){{...}}");
    println!("          pub fn via_self()       -> self::handler();");
    println!("          pub fn via_super()      -> super::net_fn();");
    println!("          pub fn via_super_super()-> super::super::crate_root_helper();");
    println!("          pub fn via_crate()      -> crate::crate_root_helper();");
    println!("  }} }}");
    let s = network::server::via_self();
    let sup = network::server::via_super();
    let sup2 = network::server::via_super_super();
    let cr = network::server::via_crate();
    println!(
        "  network::server::via_self()        -> {:?}  (self = current module)",
        s
    );
    println!(
        "  network::server::via_super()       -> {:?}  (super = parent = network)",
        sup
    );
    println!(
        "  network::server::via_super_super() -> {:?}  (super::super = crate root)",
        sup2
    );
    println!(
        "  network::server::via_crate()       -> {:?}  (crate:: = absolute from root)",
        cr
    );
    check(
        "self::handler() reaches a sibling in the SAME module",
        s == "server::handler",
    );
    check(
        "super::net_fn() reaches an item in the PARENT module",
        sup == "network::net_fn",
    );
    check(
        "crate::crate_root_helper() is an ABSOLUTE path to the crate root",
        cr == "crate_root_helper",
    );
    check(
        "super::super:: reaches TWO levels up (also the crate root)",
        sup2 == "crate_root_helper",
    );
}

// ── Section E: `pub use` re-export — the facade pattern ──────────────────────

fn section_e() {
    banner("E — `pub use` re-export: bring an item up AND make it public (facade)");
    println!("  mod base  {{ pub fn x() -> \"base::x\" }}    // private module");
    println!("  mod other {{ pub fn z() -> \"other::z\" }}    // private module");
    println!("  pub use base::x;                 // re-export: x() now public FROM HERE");
    println!("  pub use other::z as facade_z;    // re-export + alias under a clean name");
    // x() and facade_z() are callable with NO `base::` / `other::` prefix because
    // `pub use` lifted them into this scope at the crate root.
    let rx = x();
    let rz = facade_z();
    println!(
        "  x()         -> {:?}  (called directly; no base:: prefix)",
        rx
    );
    println!("  facade_z()  -> {:?}  (re-exported with an alias)", rz);
    check(
        "pub use base::x; -> x() callable at the re-export site",
        rx == "base::x",
    );
    check(
        "pub use other::z as facade_z; -> callable under the alias",
        rz == "other::z",
    );
}

// ── Section F: the FILE-TREE mod system (multi-file crates; documented) ──────

fn section_f() {
    banner("F — file-tree mod system + module_path!() (ties inline to multi-file form)");

    // RUNNABLE proof that nested inline mods form a real dotted module path —
    // the SAME path a multi-file crate would produce for src/demo_path/nested.rs.
    let p = demo_path::nested::where_am_i();
    println!("  module_path!() inside `demo_path::nested` -> {:?}", p);
    check(
        "module_path!() ends with \"demo_path::nested\" (nested mods form a path)",
        p.ends_with("demo_path::nested"),
    );

    println!();
    println!("  In a MULTI-FILE crate, `mod foo;` (NO body) loads foo's items from a FILE:");
    println!();
    println!("    src/");
    println!("    +- main.rs            // crate root:  `mod network;`");
    println!("    +- network.rs         // edition 2018+ PREFERRED form  (== network/mod.rs)");
    println!("    |   +-- declares `pub mod server;`");
    println!("    +- network/");
    println!("        +- server.rs      // item lives at crate::network::server::*");
    println!();
    println!("    // src/main.rs  (crate root):");
    println!("    mod network;              // -> loads network.rs  (OR network/mod.rs)");
    println!();
    println!("    // src/network.rs:");
    println!("    pub mod server;           // -> loads network/server.rs");
    println!("    pub fn connect() {{}}        // crate::network::connect");
    println!();
    println!("    // src/network/server.rs:");
    println!("    pub fn listen() {{}}        // crate::network::server::listen");
    println!();
    println!("  Rust Reference rules (items/modules -> Module source filenames):");
    println!("    - `mod foo;` loads from foo.rs  OR  foo/mod.rs  -- NOT both (hard error).");
    println!("    - rustc >= 1.30 (edition 2018+): prefer foo.rs over foo/mod.rs.");
    println!("    - `#[path = \"alt.rs\"] mod foo;` overrides the filename.");
    println!("    - E0432: unresolved import / module file not found on disk.");
    println!("    - The INLINE `mod foo {{ .. }}` used in Sections A-E and the");
    println!("      file-tree `mod foo;` form build the SAME module tree.");
}

fn main() {
    println!("modules.rs — Phase 5 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
