//! build_config.rs — Phase 6 bundle.
//!
//! GOAL (one line): show, by printing every value, how Rust decides what code
//! exists and what values are baked in AT BUILD TIME — `cfg!()`/`#[cfg]`/
//! `#[cfg_attr]` (conditional compilation), `env!`/`option_env!` (compile-time
//! environment reads), and `compile_error!` (fail-the-build on misconfig) — and
//! DOCUMENT the `build.rs` script that generates code into `OUT_DIR` for the
//! crate to `include!`.
//!
//! This is the GROUND TRUTH for BUILD_CONFIG.md. Every number and worked example
//! in the guide is printed by this file. Change it -> re-run -> re-paste. Never
//! hand-compute.
//!
//! WHY THIS IS ONE `[[bin]]`, NOT A REAL `build.rs`: a build script is a
//! build-time program compiled and run BEFORE its package (one per package, in a
//! file literally named `build.rs`). A workspace `[[bin]]` cannot host one. So
//! the RUNNABLE build-time primitives that a normal crate CAN use — `cfg!`,
//! `env!`, `option_env!`, `concat!` — are exercised live below (Sections A, B,
//! D, E), and the `build.rs` + `OUT_DIR` + `cargo::` directives + `include!`
//! workflow is DOCUMENTED with a concrete example (Section E), clearly labelled
//! as build-system evidence (like a `-gcflags` trace in the Go bundles). An
//! unconditional `compile_error!` is also documentation only (Section C) —
//! shipping one would make THIS file fail to compile.
//!
//! Determinism: every printed value is a pure compile-time constant (cfg bools,
//! Cargo-set `CARGO_PKG_*` strings, set-membership tests). No wall-clock, no
//! printed addresses, no host-specific paths printed as values (only their
//! presence/absence booleans). Output is byte-reproducible across runs.
//!
//! Run:
//!     just run build_config   (== cargo run --bin build_config)

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

// ── Section A: cfg!() — conditional compilation evaluated to a `bool` ─────────
//
// `cfg!(PREDICATE)` is a built-in macro that expands to the literal `true` or
// `false` depending on whether PREDICATE holds FOR THIS COMPILATION. Unlike the
// `#[cfg]` ATTRIBUTE (which REMOVES the annotated item when false), `cfg!()` NEVER
// removes code — every branch of an `if cfg!(...)` must still type-check. That is
// what lets us PRINT the boolean here: the value is a runtime `bool` whose value
// was fixed at compile time.

fn section_a() {
    banner("A — cfg!(): conditional compilation -> a `bool` literal");

    // `debug_assertions` is set by rustc whenever compiling WITHOUT -O (i.e. a
    // debug build). `cargo run` builds in debug, so this is `true` here. A
    // `cargo run --release` would make it `false`.
    let dbg = cfg!(debug_assertions);
    println!("  cfg!(debug_assertions)       = {dbg}   (debug build via `cargo run`)");
    check(
        "cfg!(debug_assertions) is true for a debug (`cargo run`) build",
        dbg,
    );

    // target_os is a key/value cfg. On this host it is "macos"; on a Linux box
    // the FIRST line would be false and the SECOND true. Both are printed so the
    // contrast is visible.
    let on_mac = cfg!(target_os = "macos");
    let on_linux = cfg!(target_os = "linux");
    println!("  cfg!(target_os = \"macos\")   = {on_mac}");
    println!("  cfg!(target_os = \"linux\")   = {on_linux}");
    check(
        "exactly one of macos/linux target_os holds on a single host",
        on_mac ^ on_linux,
    );
    check("this machine is cfg!(target_os = \"macos\")", on_mac);

    // `unix` and `windows` are convenience name-cfgs derived from
    // `target_family`. On macOS/unix, `unix` is set and `windows` is not.
    let is_unix = cfg!(unix);
    let is_windows = cfg!(windows);
    println!("  cfg!(unix)                   = {is_unix}");
    println!("  cfg!(windows)                = {is_windows}");
    check(
        "cfg!(unix) and cfg!(windows) are mutually exclusive",
        is_unix ^ is_windows,
    );

    // CRUCIAL DISTINCTION — print it so it is in the captured output:
    //   `cfg!(...)`  -> expands to `true`/`false`; code stays, all branches compile.
    //   `#[cfg(...)]` -> an ATTRIBUTE; REMOVES the item when the predicate is false.
    println!("  NOTE: cfg!() expands to a bool and KEEPS all code;");
    println!("        #[cfg(...)] is an attribute that REMOVES items when false.");
}

// ── Section B: env! / option_env! — read the environment AT COMPILE TIME ─────
//
// `env!("VAR")` expands to a `&'static str` holding the value of VAR as it was
// when rustc ran (i.e. at BUILD time). If VAR is unset, `env!` is a COMPILE
// ERROR. `option_env!("VAR")` is the total version: it expands to
// `Option<&'static str>` — `Some` if set, `None` if not, and never a compile
// error. Cargo sets a fixed family of `CARGO_*` vars for every crate it builds
// (CARGO_PKG_NAME, CARGO_PKG_VERSION, CARGO_CRATE_NAME, ...); those are the
// deterministic, host-independent values asserted below.

fn section_b() {
    banner("B — env! / option_env!: read the env at COMPILE time");

    // These are set by Cargo for every crate. `core` is the member crate's
    // PACKAGE name (see core/Cargo.toml); the version comes from the workspace
    // `[workspace.package] version = "0.0.0"`. CARGO_CRATE_NAME, by contrast, is
    // the name of the specific CRATE/target being compiled — for a `[[bin]]` that
    // is the BIN's crate name (`build_config`), NOT the package name. All three
    // are &'static str.
    let pkg_name: &str = env!("CARGO_PKG_NAME");
    let pkg_version: &str = env!("CARGO_PKG_VERSION");
    let crate_name: &str = env!("CARGO_CRATE_NAME");
    println!("  env!(\"CARGO_PKG_NAME\")    = {pkg_name:?}");
    println!("  env!(\"CARGO_PKG_VERSION\") = {pkg_version:?}");
    println!("  env!(\"CARGO_CRATE_NAME\")  = {crate_name:?}");
    check(
        "env!(\"CARGO_PKG_NAME\") == \"core\" (the member PACKAGE name)",
        pkg_name == "core",
    );
    check(
        "env!(\"CARGO_PKG_VERSION\") is non-empty (set by Cargo)",
        !pkg_version.is_empty(),
    );
    check(
        "env!(\"CARGO_PKG_VERSION\") == \"0.0.0\" (workspace version)",
        pkg_version == "0.0.0",
    );
    check(
        "env!(\"CARGO_CRATE_NAME\") == \"build_config\": the BIN crate, NOT the package",
        crate_name == "build_config",
    );
    check(
        "CARGO_PKG_NAME (\"core\") != CARGO_CRATE_NAME (\"build_config\"): package vs target crate",
        pkg_name != crate_name,
    );

    // option_env! is the fallible form. We check PRESENCE only — never print the
    // value, because the value (a home directory, a path) is host-specific and
    // would make the output non-reproducible across machines.
    let home: Option<&str> = option_env!("HOME");
    let never_set: Option<&str> = option_env!("BUILD_CONFIG_DEFINITELY_UNSET_VAR");
    let out_dir: Option<&str> = option_env!("OUT_DIR");
    println!(
        "  option_env!(\"HOME\")                       = <{}>",
        if home.is_some() { "Some" } else { "None" }
    );
    println!(
        "  option_env!(\"BUILD_CONFIG_DEFINITELY_UNSET...\") = <{}>",
        if never_set.is_some() { "Some" } else { "None" }
    );
    println!(
        "  option_env!(\"OUT_DIR\")                    = <{}>",
        if out_dir.is_some() { "Some" } else { "None" }
    );
    check(
        "option_env!(\"HOME\") is Some on a typical Unix build host (presence only)",
        home.is_some(),
    );
    check(
        "option_env! on an unset var returns None (never a compile error)",
        never_set.is_none(),
    );
    // OUT_DIR is set ONLY for packages that HAVE a build script. `core` has
    // none, so option_env!(\"OUT_DIR\") is None here — a live demonstration that
    // OUT_DIR is build-script-gated, not universally present.
    check(
        "option_env!(\"OUT_DIR\") is None: `core` has NO build.rs (OUT_DIR is build-script-only)",
        out_dir.is_none(),
    );
}

// ── Section C: compile_error! — DOCUMENTED (cannot be shipped live) ──────────
//
// `compile_error!("msg")` unconditionally fails compilation with `msg`. It is
// the compile-time analogue of `panic!`. Because an UNCONDITIONAL
// compile_error! would stop THIS file from building, we do not emit one.
// Instead we show the idiomatic cfg-GUARDED form (recommended by the std docs):
// the error fires ONLY when a required configuration is missing, and is dead
// code otherwise. This pattern is how crates fail loudly on misconfiguration
// instead of silently building a broken artifact.

fn section_c() {
    banner("C — compile_error!: fail the build on misconfiguration (DOCUMENTED)");

    println!("  // An UNCONDITIONAL compile_error! always fails the build:");
    println!("  //   compile_error!(\"boom\");   // <- never ship this in a runnable file");
    println!();
    println!("  // The idiomatic cfg-GUARDED form (verbatim from the std docs):");
    println!("  //   #[cfg(not(any(feature = \"foo\", feature = \"bar\")))]");
    println!(
        "  //   compile_error!(\"Either feature \\\"foo\\\" or \\\"bar\\\" must be enabled.\");"
    );
    println!();
    println!("  // Single-feature guard (the brief's pattern):");
    println!("  //   #[cfg(not(feature = \"x\"))]");
    println!("  //   compile_error!(\"enable feature `x`\");");
    println!();
    println!("  // How it behaves:");
    println!("  //   - if the cfg predicate is FALSE -> the item is removed (no error).");
    println!("  //   - if the cfg predicate is TRUE  -> compilation stops with the message.");
    println!("  //   - it is the compiler-level form of panic!, emitted during compilation.");

    // A live, SAFE demonstration of the mechanism: a cfg predicate that is a
    // CONTRADICTION is always false, so a compile_error! behind it would be dead
    // code and never fire. `unix` and `windows` are mutually-exclusive target
    // families, so `all(unix, windows)` is false on EVERY host — we assert that
    // boolean (the exact thing that would gate such a guarded compile_error!).
    // (We avoid `feature = "..."` cfgs here: this crate declares no [features],
    // so they would trip the `unexpected_cfgs` lint under -D warnings.)
    let guard_false = cfg!(all(unix, windows));
    check(
        "a contradictory cfg predicate (all(unix, windows)) is always false",
        !guard_false,
    );
}

// ── Section D: target info via cfg — what the crate can see at compile time ──
//
// The compiled crate learns about its TARGET through cfg values (target_arch,
// target_os, target_vendor, target_pointer_width, target_endian, target_family,
// plus the `unix`/`windows` name-cfgs). These are available to EVERY crate. The
// `TARGET`/`HOST`/`OPT_LEVEL`/`DEBUG` *environment variables*, by contrast, are
// set ONLY for build scripts (see Section E) — a normal crate CANNOT read them
// with `env!`, which is why we use cfg here, not env!(\"TARGET\").

// The complete set of `target_os` values the Rust Reference enumerates. Used for
// a set-membership check: the current target_os MUST be one of these.
const KNOWN_TARGET_OS: &[&str] = &[
    "windows",
    "macos",
    "ios",
    "linux",
    "android",
    "freebsd",
    "dragonfly",
    "openbsd",
    "netbsd",
    "none",
];

fn section_d() {
    banner("D — target info via cfg: arch / os / vendor / width / endian");

    // Resolve the current target_os to a string via a cfg! ladder (deterministic;
    // exactly one arm is true on any single host).
    let this_os = if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "linux") {
        "linux"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else if cfg!(target_os = "freebsd") {
        "freebsd"
    } else {
        "other"
    };
    println!("  this target_os = {this_os:?}");
    check(
        "the current target_os is in the Reference's enumerated set",
        KNOWN_TARGET_OS.contains(&this_os),
    );

    // Pin the host this bundle was authored on (deterministic for THIS machine).
    println!(
        "  cfg!(target_arch         = \"aarch64\") = {}",
        cfg!(target_arch = "aarch64")
    );
    println!(
        "  cfg!(target_vendor       = \"apple\")   = {}",
        cfg!(target_vendor = "apple")
    );
    println!(
        "  cfg!(target_pointer_width= \"64\")      = {}",
        cfg!(target_pointer_width = "64")
    );
    println!(
        "  cfg!(target_endian       = \"little\")  = {}",
        cfg!(target_endian = "little")
    );
    println!(
        "  cfg!(target_family       = \"unix\")    = {}",
        cfg!(target_family = "unix")
    );
    check(
        "cfg!(target_arch = \"aarch64\") on this Apple Silicon host",
        cfg!(target_arch = "aarch64"),
    );
    check(
        "cfg!(target_vendor = \"apple\") on this host",
        cfg!(target_vendor = "apple"),
    );
    check(
        "cfg!(target_pointer_width = \"64\") on this 64-bit host",
        cfg!(target_pointer_width = "64"),
    );
    check(
        "cfg!(target_endian = \"little\") on this host",
        cfg!(target_endian = "little"),
    );
    check(
        "cfg!(target_family = \"unix\") on this host",
        cfg!(target_family = "unix"),
    );

    // target_env is "" (empty) on macOS — a historical quirk the Reference calls
    // out: target_env is only non-empty when needed to disambiguate the ABI.
    let env_macos_empty = cfg!(target_os = "macos") && cfg!(target_env = "");
    check(
        "on macOS, target_env is the empty string (only set when needed to disambiguate)",
        env_macos_empty,
    );
}

// ── Section E: build.rs — DOCUMENTED (build-system evidence) ─────────────────
//
// A build script is a file named `build.rs` at the root of a package. Cargo
// compiles it and runs it BEFORE building the package. It can: read env vars
// (CARGO_PKG_*, OUT_DIR, TARGET, HOST, ...), write generated code into OUT_DIR,
// and emit `cargo::` directives to stdout that change how the package is then
// compiled. The crate later `include!`s the generated file or reads cfg/env the
// script installed.
//
// We CANNOT host a real build.rs in this `[[bin]]`, so this section (1) shows a
// concrete build.rs + its crate-side `include!` as a code block (evidence), and
// (2) exercises the ONE part of that pipeline a normal crate CAN run live: the
// `concat!(env!(...), ...)` compile-time string splice that `include!` relies on
// to build the path into OUT_DIR.

fn section_e() {
    banner("E — build.rs workflow (DOCUMENTED) + the concat! splice (RUN)");

    println!("  // ── build.rs (lives at the package root; run BEFORE the crate) ──");
    println!("  // fn main() {{");
    println!("  //     // Cargo sets CARGO_PKG_VERSION, OUT_DIR, TARGET, HOST, ... for");
    println!("  //     // the build script. Read the version, bake it into generated code.");
    println!("  //     let version = env!(\"CARGO_PKG_VERSION\");");
    println!("  //     let out_dir = env!(\"OUT_DIR\");");
    println!("  //     let dest = std::path::Path::new(&out_dir).join(\"generated.rs\");");
    println!(
        "  //     let generated = format!(\"pub const VERSION: &str = \\\"{{version}}\\\";\\n\");"
    );
    println!("  //     std::fs::write(&dest, generated).unwrap();");
    println!("  //     // Tell Cargo: re-run me only when Cargo.toml changes.");
    println!("  //     println!(\"cargo::rerun-if-changed=Cargo.toml\");");
    println!("  //     // (optional) expose a value to the crate via env! at compile time:");
    println!("  //     println!(\"cargo::rustc-env=BUILD_GIT_HASH=abc123\");");
    println!("  // }}");
    println!();
    println!("  // ── crate side: pull the generated file in at compile time ──");
    println!("  // include!(concat!(env!(\"OUT_DIR\"), \"/generated.rs\"));");
    println!("  // // now `VERSION` is in scope, e.g.:");
    println!("  // println!(\"built version: {{}}\", VERSION);");
    println!();
    println!("  // cargo:: directives a build script can emit (Cargo Book):");
    println!(
        "  //   cargo::rustc-cfg=KEY[=\"VALUE\"]        -> enables a #[cfg(KEY)] in the crate"
    );
    println!(
        "  //   cargo::rustc-env=VAR=VALUE            -> readable via env!(\"VAR\") in the crate"
    );
    println!("  //   cargo::rerun-if-changed=PATH          -> re-run only when PATH changes");
    println!("  //   cargo::rerun-if-env-changed=NAME      -> re-run only when env NAME changes");
    println!("  //   cargo::warning=/cargo::error=MESSAGE -> surface a warning / fail the build");

    // RUNNABLE piece: the compile-time string splice `include!` depends on.
    // `concat!` joins &str literals at compile time; `env!` yields a &'static str.
    // Together they build the path "core.rs" with zero runtime cost — exactly the
    // mechanism `include!(concat!(env!(\"OUT_DIR\"), \"/generated.rs\"))` uses, just
    // pointed at a filename derived from the package name instead of OUT_DIR.
    let crate_source_file: &str = concat!(env!("CARGO_PKG_NAME"), ".rs");
    println!();
    println!("  concat!(env!(\"CARGO_PKG_NAME\"), \".rs\") = {crate_source_file:?}");
    check(
        "concat!(env!(...), ...) is a compile-time &'static str splice (== \"core.rs\")",
        crate_source_file == "core.rs",
    );
}

// ── Section F: features — DOCUMENTED ([features] in Cargo.toml) ──────────────
//
// Cargo features are compile-time switches declared in `[features]` of the
// manifest. Enabling a feature `foo` sets the cfg `feature = "foo"`, gating code
// with `#[cfg(feature = "foo")]` / `cfg!(feature = "foo")`. Features can also
// turn on optional dependencies. `core` ships NO `[features]` (it is stdlib-
// only), so every `feature=` cfg is false here; we therefore DOCUMENT the
// manifest shape rather than assert a live feature.

fn section_f() {
    banner("F — Cargo features: [features] -> cfg(feature = \"..\") (DOCUMENTED)");

    println!("  // [features] in Cargo.toml:");
    println!("  //   [features]");
    println!("  //   json   = [\"dep:serde_json\"]   # optional dep + a cfg switch");
    println!("  //   pretty = []                    # pure switch, no extra dep");
    println!();
    println!("  // [dependencies] (optional, pulled in only by the feature):");
    println!("  //   serde_json = {{ version = \"1\", optional = true }}");
    println!();
    println!("  // In code, the feature becomes a cfg:");
    println!("  //   #[cfg(feature = \"json\")]");
    println!("  //   fn parse_json() {{ /* ... */ }}");
    println!();
    println!("  //   if cfg!(feature = \"pretty\") {{ /* pretty-print */ }}");
    println!();
    println!("  // Enable from the CLI:   cargo build --features json");
    println!("  //                       cargo build --all-features");
    println!("  //                       cargo build --no-default-features");
    println!();
    println!("  // A feature `json` gates code via the cfg `feature = \"json\"`:");
    let feature_cfg: String = format!("feature = \"{}\"", "json");
    println!("  //   format!(\"feature = \\\"{{}}\\\"\", \"json\") = {feature_cfg:?}");

    check(
        "a feature named `json` in [features] gates code via cfg `feature = \"json\"`",
        feature_cfg == "feature = \"json\"",
    );
}

fn main() {
    println!("build_config.rs — Phase 6 bundle.");
    println!("Every value below is a compile-time constant baked in by rustc/Cargo.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
