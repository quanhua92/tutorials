//! deployment.rs — Phase 8 bundle.
//!
//! GOAL (one line): show, by printing every value, how Rust learns about its
//! build target AT COMPILE TIME (`cfg!(target_*)` predicates, `env!()` Cargo
//! constants, deterministic `size_of` layout facts) — and DOCUMENT the
//! deployment artifact pipeline those compile-time decisions feed: cross-
//! compiling to a musl static binary, packing it into a multi-stage scratch
//! Docker image, and shrinking it with the release profile.
//!
//! This is the GROUND TRUTH for DEPLOYMENT.md. Every runnable value below is
//! computed by this file. The Dockerfile, the `cargo build --target` /
//! `rustup target add` / `cross` workflow, and the `[profile.release]` table
//! are BUILD-SYSTEM EVIDENCE documented as code blocks (NOT `.go` callouts) —
//! the parts a normal crate CANNOT run live (a real cross-compile / Docker
//! build happens OUTSIDE `cargo run`). Change a runnable value -> re-run ->
//! re-paste. Never hand-compute.
//!
//! WHY THIS IS ONE `[[bin]]`: cross-compilation (`cargo build --target ...`),
//! Docker image builds (`docker build`), and the release profile are EXTERNAL
//! build/deploy steps. The COMPILE-TIME PRIMITIVES a normal crate CAN observe
//! — `cfg!(target_*)`, `env!`/`option_env!`, `size_of` — are exercised live
//! below (Sections A–D); the artifact pipeline is DOCUMENTED (Sections E–F)
//! with the exact commands, clearly labelled as build-system evidence.
//!
//! Determinism: every runnable value is a pure compile-time constant (cfg
//! bools, Cargo-set `CARGO_PKG_*` strings, `size_of` layout sizes). No
//! wall-clock, no printed addresses, no host-specific paths printed as values.
//! Output is byte-reproducible across runs on the same host.
//!
//! Run:
//!     just run deployment   (== cargo run --bin deployment)

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

// Known cfg value sets (from the Rust Reference conditional-compilation list).
// Used for PORTABLE set-membership checks: the current target MUST be a member.

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

const KNOWN_TARGET_ARCH: &[&str] = &[
    "x86",
    "x86_64",
    "arm",
    "aarch64",
    "riscv32",
    "riscv64",
    "powerpc",
    "powerpc64",
    "mips",
    "s390x",
    "wasm32",
    "wasm64",
];

const KNOWN_TARGET_ENV: &[&str] = &[
    "",     // macos/bsd set no ABI env
    "gnu",  // linux glibc
    "musl", // linux musl (static)
    "msvc", // windows
    "sgx", "uclibc", "newlib",
];

// ── Section A: cross-compile target flags via cfg!(target_*) — RUN + DOCUMENT ─
//
// `cfg!(target_os = "..")`, `cfg!(target_arch = "..")`, `cfg!(target_env =
// "..")`, `cfg!(target_endian = "..")`, `cfg!(target_pointer_width = "..")`
// read the BUILD TARGET at compile time. This is exactly what `cargo build
// --target x86_64-unknown-linux-musl` flips: each predicate re-evaluates for
// the requested triple. We resolve the four core dimensions to strings (one
// true arm per host) and assert PORTABLE set membership.

fn section_a() {
    banner("A — Cross-compile target flags via cfg!(target_*) — RUN + DOCUMENT");

    let this_os = if cfg!(target_os = "windows") {
        "windows"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "ios") {
        "ios"
    } else if cfg!(target_os = "linux") {
        "linux"
    } else if cfg!(target_os = "android") {
        "android"
    } else if cfg!(target_os = "freebsd") {
        "freebsd"
    } else {
        "other"
    };

    let this_arch = if cfg!(target_arch = "x86_64") {
        "x86_64"
    } else if cfg!(target_arch = "aarch64") {
        "aarch64"
    } else if cfg!(target_arch = "x86") {
        "x86"
    } else if cfg!(target_arch = "arm") {
        "arm"
    } else if cfg!(target_arch = "wasm32") {
        "wasm32"
    } else {
        "other"
    };

    let this_env = if cfg!(target_env = "") {
        ""
    } else if cfg!(target_env = "gnu") {
        "gnu"
    } else if cfg!(target_env = "musl") {
        "musl"
    } else if cfg!(target_env = "msvc") {
        "msvc"
    } else {
        "other"
    };

    let this_endian = if cfg!(target_endian = "little") {
        "little"
    } else {
        "big"
    };

    println!("  cfg!(target_os)    = {this_os:?}");
    println!("  cfg!(target_arch)  = {this_arch:?}");
    println!("  cfg!(target_env)   = {this_env:?}   (musl is the static-link env)");
    println!("  cfg!(target_endian)= {this_endian:?}");
    println!(
        "  cfg!(target_pointer_width = \"64\") = {}",
        cfg!(target_pointer_width = "64")
    );

    check(
        "current target_os is in the Reference's enumerated set",
        KNOWN_TARGET_OS.contains(&this_os),
    );
    check(
        "current target_arch is non-empty and in the known arch set",
        !this_arch.is_empty() && KNOWN_TARGET_ARCH.contains(&this_arch),
    );
    check(
        "current target_env is in the known env set",
        KNOWN_TARGET_ENV.contains(&this_env),
    );
    check(
        "current target_endian is in {little, big}",
        this_endian == "little" || this_endian == "big",
    );
    check(
        "exactly one of cfg!(unix) / cfg!(windows) holds",
        cfg!(unix) ^ cfg!(windows),
    );

    // DOCUMENT (build-system evidence). Cross-compilation is a first-class Cargo
    // feature — no toolchain dance is needed for std; rustup fetches the target's
    // precompiled std on demand.
    println!();
    println!("  // Cross-compile to a STATIC musl Linux binary (no glibc dependency):");
    println!("  //   rustup target add x86_64-unknown-linux-musl     # fetch target std");
    println!("  //   cargo build --release --target x86_64-unknown-linux-musl");
    println!("  // Output -> target/x86_64-unknown-linux-musl/release/<bin>");
    println!();
    println!("  // Pin a default target per-project in .cargo/config.toml:");
    println!("  //   [build]");
    println!("  //   target = \"x86_64-unknown-linux-musl\"");
    println!();
    println!(
        "  // cfg!(target_env = \"musl\") on THIS host = {} (true only when building FOR musl)",
        cfg!(target_env = "musl")
    );
}

// ── Section B: release vs debug — RUN cfg!(debug_assertions) + DOCUMENT ──────
//
// `cargo run` / `cargo build` use the `dev` profile (debug_assertions = ON).
// `cargo build --release` uses the `release` profile (debug_assertions = OFF).
// The most deployment-relevant consequence: integer-overflow behavior of the
// bare operators flips between profiles (dev: PANIC; release: WRAP). The
// explicit checked_*/wrapping_*/saturating_* methods are mode-INDEPENDENT.

fn section_b() {
    banner("B — Release vs Debug profile — RUN cfg!(debug_assertions) + DOCUMENT");

    let dbg = cfg!(debug_assertions);
    println!("  cfg!(debug_assertions) = {dbg}   (dev profile; --release -> false)");
    check(
        "cfg!(debug_assertions) is true for a dev (`cargo run`) build",
        dbg,
    );

    // Mode-INDEPENDENT overflow handling — identical in dev and release:
    let max = 255u8;
    let checked = max.checked_add(1); // None on overflow
    let wrapping = max.wrapping_add(1); // wraps to 0
    let saturating = max.saturating_add(1); // saturates at MAX
    println!(
        "  255u8.checked_add(1)    = {checked:?}    (None -> caller decides; mode-independent)"
    );
    println!("  255u8.wrapping_add(1)   = {wrapping}      (wraps to 0; mode-independent)");
    println!("  255u8.saturating_add(1) = {saturating}    (saturates; mode-independent)");
    check(
        "checked_add on u8::MAX is None regardless of profile",
        checked.is_none(),
    );
    check(
        "wrapping_add on u8::MAX wraps to 0 regardless of profile",
        wrapping == 0,
    );
    check(
        "saturating_add on u8::MAX stays at 255 regardless of profile",
        saturating == 255,
    );

    // DOCUMENT (build-system evidence). The bare operators are the ONLY overflow
    // behavior that flips between profiles.
    println!();
    println!("  // Bare arithmetic overflow behavior (the mode-dependent part):");
    println!("  //   let x: u8 = 255u8 + 1;");
    println!("  //   - dev    (cfg!(debug_assertions)==true ): PANIC at runtime");
    println!("  //   - release(cfg!(debug_assertions)==false): WRAPS silently to 0");
    println!();
    println!("  // Build the optimized artifact (--release flips debug_assertions OFF):");
    println!("  //   cargo build --release   # -> target/release/<bin>");
    println!();
    println!("  // Default dev profile (cargo run/build/check) — Cargo Book:");
    println!("  //   opt-level=0 debug=true strip=\"none\" debug-assertions=true");
    println!("  //   overflow-checks=true lto=false panic=\"unwind\" codegen-units=256");
    println!();
    println!("  // Default release profile (--release / cargo install) — Cargo Book:");
    println!("  //   opt-level=3 debug=false strip=\"none\" debug-assertions=false");
    println!("  //   overflow-checks=false lto=false panic=\"unwind\" codegen-units=16");
}

// ── Section C: env!() Cargo constants + CARGO_CFG_* build-script-only ────────
//
// `env!(\"VAR\")` expands to a &'static str holding VAR's value AT COMPILE time
// (compile error if unset); `option_env!` is the total form (Option, never a
// compile error). Cargo sets a fixed family of `CARGO_PKG_*`/`CARGO_CRATE_NAME`
// vars for EVERY crate — those are crate-accessible and deterministic. The
// `CARGO_CFG_<cfg>` vars, by contrast, are set ONLY for build scripts; a normal
// crate reads cfg via the `cfg!()` macro (Section A), not via env!.

fn section_c() {
    banner("C — env!() Cargo constants + CARGO_CFG_* are build-script-only — RUN + DOCUMENT");

    let pkg_name: &str = env!("CARGO_PKG_NAME");
    let pkg_version: &str = env!("CARGO_PKG_VERSION");
    let crate_name: &str = env!("CARGO_CRATE_NAME");
    println!("  env!(\"CARGO_PKG_NAME\")    = {pkg_name:?}    (member PACKAGE name)");
    println!("  env!(\"CARGO_PKG_VERSION\") = {pkg_version:?}    (workspace version)");
    println!("  env!(\"CARGO_CRATE_NAME\")  = {crate_name:?}    (this BIN crate, not package)");
    check("env!(\"CARGO_PKG_NAME\") == \"core\"", pkg_name == "core");
    check(
        "env!(\"CARGO_PKG_VERSION\") == \"0.0.0\" (workspace version)",
        pkg_version == "0.0.0",
    );
    check(
        "env!(\"CARGO_CRATE_NAME\") == \"deployment\" (the BIN crate)",
        crate_name == "deployment",
    );
    check(
        "CARGO_PKG_NAME != CARGO_CRATE_NAME (package vs bin crate)",
        pkg_name != crate_name,
    );

    // HONEST DEMONSTRATION: CARGO_CFG_* are build-script-only. option_env! shows
    // the absence (None) without a compile error — proving a normal crate cannot
    // read cfg this way and must use the cfg!() macro instead.
    let cfg_os_env: Option<&str> = option_env!("CARGO_CFG_TARGET_OS");
    let cfg_arch_env: Option<&str> = option_env!("CARGO_CFG_TARGET_ARCH");
    println!(
        "  option_env!(\"CARGO_CFG_TARGET_OS\")   = <{}>   (Some only in build.rs)",
        if cfg_os_env.is_some() { "Some" } else { "None" }
    );
    println!(
        "  option_env!(\"CARGO_CFG_TARGET_ARCH\") = <{}>",
        if cfg_arch_env.is_some() {
            "Some"
        } else {
            "None"
        }
    );
    check(
        "CARGO_CFG_TARGET_OS is None here: CARGO_CFG_* are BUILD-SCRIPT-ONLY",
        cfg_os_env.is_none(),
    );
    check(
        "CARGO_CFG_TARGET_ARCH is None here (same reason)",
        cfg_arch_env.is_none(),
    );

    // DOCUMENT (build-system evidence). The build-script side that DOES see them.
    println!();
    println!("  // In a build.rs, Cargo sets CARGO_CFG_<cfg> for every cfg key:");
    println!("  //   fn main() {{");
    println!("  //     let os = env!(\"CARGO_CFG_TARGET_OS\");   // \"linux\", \"macos\", ...");
    println!("  //     if os == \"linux\" {{ println!(\"cargo::rustc-cfg=linux_only\"); }}");
    println!("  //   }}");
    println!("  // The crate then gates code on the installed cfg:  #[cfg(linux_only)]");
    println!();
    println!("  // Crates read the SAME fact via cfg!(target_os = \"linux\") (Section A)");
    println!("  // at compile time WITHOUT a build script.");
}

// ── Section D: size_of — deterministic data-layout facts baked into the binary
//
// These sizes are FIXED by the target ABI (pointer width) and the Rust layout
// rules; they are compile-time constants. They are the exact bytes that end up
// in the compiled binary's data paths, which is why they matter for deployment
// (they do NOT change between debug/release — layout is stable).

fn section_d() {
    banner("D — size_of: deterministic data-layout facts baked into the binary — RUN");

    let usize_bytes = std::mem::size_of::<usize>();
    let ptr_bytes = std::mem::size_of::<*const u8>();
    let str_bytes = std::mem::size_of::<&str>();
    let vec_u8_bytes = std::mem::size_of::<Vec<u8>>();
    let opt_box_bytes = std::mem::size_of::<Option<Box<u8>>>();
    println!("  size_of::<usize>()           = {usize_bytes}  (target_pointer_width / 8)");
    println!("  size_of::<*const u8>()       = {ptr_bytes}  (a raw pointer)");
    println!("  size_of::<&str>()            = {str_bytes}  (ptr + len = 2 * usize)");
    println!("  size_of::<Vec<u8>>()         = {vec_u8_bytes}  (ptr + len + cap = 3 * usize)");
    println!(
        "  size_of::<Option<Box<u8>>>() = {opt_box_bytes}  (niche-optimized: == a bare Box<u8>)"
    );
    check(
        "size_of::<usize>() == 8 on a 64-bit target",
        usize_bytes == 8,
    );
    check(
        "size_of::<*const u8>() == size_of::<usize>() (pointer width)",
        ptr_bytes == usize_bytes,
    );
    check(
        "size_of::<&str>() == 2 * usize (ptr+len = 16 bytes)",
        str_bytes == 2 * usize_bytes,
    );
    check(
        "size_of::<Vec<u8>>() == 3 * usize (ptr+len+cap = 24 bytes)",
        vec_u8_bytes == 3 * usize_bytes,
    );
    check(
        "Option<Box<u8>> is niche-optimized to 1 usize (no tag byte for None)",
        opt_box_bytes == usize_bytes,
    );
    check(
        "cfg!(target_pointer_width = \"64\") implies usize == 8 bytes",
        cfg!(target_pointer_width = "64") && usize_bytes == 8,
    );
}

// ── Section E: musl static binary + multi-stage scratch Dockerfile (DOCUMENTED)
//
// Build-system evidence (a real cross-compile / docker build runs OUTSIDE cargo
// run). musl statically links libc -> a binary with ZERO shared-library deps ->
// deployable in a `FROM scratch` image. Multi-stage: stage 1 (builder) compiles
// with the full toolchain; stage 2 (runtime) copies ONLY the static binary.

fn section_e() {
    banner("E — Musl static binary + multi-stage scratch Dockerfile (DOCUMENTED)");

    println!("  // ── Why musl: a FULLY STATIC binary with NO glibc dependency ──");
    println!("  //   A gnu (glibc) binary dynamically links libc.so.6, so one built on");
    println!("  //   Ubuntu 24.04 may fail on older distros (\"GLIBC_2.xx not found\").");
    println!("  //   Linking musl (a small libc-standard C library) yields a STATIC");
    println!("  //   binary with zero shared-library deps -> runs in `FROM scratch`.");
    println!();
    println!("  // Build for musl, then PROVE it is fully static:");
    println!("  //   rustup target add x86_64-unknown-linux-musl");
    println!("  //   cargo build --release --target x86_64-unknown-linux-musl");
    println!("  //   file target/x86_64-unknown-linux-musl/release/deployment");
    println!("  //     # -> \"... statically linked\"");
    println!("  //   ldd  target/x86_64-unknown-linux-musl/release/deployment");
    println!("  //     # -> \"not a dynamic executable\"");
    println!();
    println!("  // ── Multi-stage Dockerfile: builder compiles, final stage runs ──");
    println!("  //   # ---- stage 1: builder (full Rust toolchain lives here) ----");
    println!("  //   FROM rust:1-bookworm AS builder");
    println!("  //   RUN apt-get update && apt-get install -y musl-tools");
    println!("  //   RUN rustup target add x86_64-unknown-linux-musl");
    println!("  //   WORKDIR /app");
    println!("  //   COPY Cargo.toml Cargo.lock .");
    println!(
        "  //   RUN mkdir src && cargo build --release --target x86_64-unknown-linux-musl  # cache deps"
    );
    println!("  //   COPY . .");
    println!("  //   RUN cargo build --release --target x86_64-unknown-linux-musl");
    println!("  //");
    println!("  //   # ---- stage 2: runtime (ONLY the static binary + TLS CAs) ----");
    println!("  //   FROM scratch");
    println!("  //   COPY --from=builder \\");
    println!("  //     /app/target/x86_64-unknown-linux-musl/release/deployment /deployment");
    println!("  //   COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/");
    println!("  //   ENTRYPOINT [\"/deployment\"]");
    println!();
    println!("  //   docker build -t deployment:latest .");
    println!("  //   docker images deployment   # ~ a few MB, not GB (no OS in stage 2)");
    println!();
    println!("  // Distroless alternative to scratch (adds CA certs + /etc/passwd, no shell):");
    println!("  //   FROM gcr.io/distroless/cc-debian12");
    println!("  //   COPY --from=builder /app/target/.../release/deployment /deployment");
    println!();
    println!("  // ── `cross` (cross-rs): Dockerized toolchain for tricky targets ──");
    println!("  //   cargo install cross --git https://github.com/cross-rs/cross");
    println!("  //   cross build --release --target aarch64-unknown-linux-musl");
    println!("  //   cross build --release --target x86_64-pc-windows-gnu");
    println!("  // `cross` wraps cargo with a per-target Docker image bundling the right");
    println!("  // C toolchain + linker, so you never install arm64/mingw locally.");
}

// ── Section F: [profile.release] for minimal binary size (DOCUMENTED) ────────
//
// The default release profile is tuned for SPEED (opt-level=3), not SIZE. The
// Cargo Book `[profile.release]` table lets you trade link time + unwinding for
// a much smaller binary. Verified against the Cargo Book Profiles chapter.

fn section_f() {
    banner("F — [profile.release] for minimal binary size (DOCUMENTED)");

    println!("  // Shrink the release binary in Cargo.toml (Cargo Book — Profiles):");
    println!("  //   [profile.release]");
    println!("  //   opt-level = \"z\"     # optimize for SIZE ('s' also shrinks; 3 = speed)");
    println!("  //   lto = true          # 'fat' LTO across the whole dep graph (or \"thin\")");
    println!("  //   codegen-units = 1   # one unit -> best optimization, slower link");
    println!("  //   strip = \"symbols\"   # strip=true is equivalent; removes symbol tables");
    println!("  //   panic = \"abort\"     # drop the unwind tables -> smaller binary");
    println!();
    println!("  //   cargo build --release    # applies [profile.release] automatically");
    println!();
    println!("  // Each knob (Cargo Book + min-sized-rust):");
    println!("  //   opt-level=\"z\"   -> optimize for binary size ('s'=size, 3=speed)");
    println!("  //   lto=true        -> whole-program LLVM optimization across all crates");
    println!("  //   codegen-units=1 -> one codegen unit lets LLVM see the whole crate");
    println!("  //   strip=\"symbols\" -> remove the symbol table + debuginfo from the binary");
    println!("  //   panic=\"abort\"   -> no unwinding machinery (smaller binary)");
    println!();
    println!("  // CAVEAT: panic=\"abort\" is IGNORED by tests/benches/build scripts/proc-");
    println!("  // macros — the test harness requires unwinding, so a release TEST build");
    println!("  // forces deps back to \"unwind\".");
    println!();
    println!("  // Custom profile inheriting release + the size knobs:");
    println!("  //   [profile.min]");
    println!("  //   inherits = \"release\"");
    println!("  //   opt-level = \"z\"");
    println!("  //   lto = true");
    println!("  //   strip = true");
    println!("  //   panic = \"abort\"");
    println!("  //   cargo build --profile min   # -> target/min/<bin>");
    println!();
    println!("  // Order of magnitude: a default --release binary can be ~5-15 MB; the full");
    println!("  // size profile + musl + strip often lands it under ~1-2 MB. (Exact numbers");
    println!("  // are binary-specific; this is documentation, not a runnable check.)");
}

fn main() {
    println!("deployment.rs — Phase 8 bundle.");
    println!("Every runnable value below is a compile-time constant baked in by rustc/Cargo.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
