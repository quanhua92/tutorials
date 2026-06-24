//! __STEM__.rs — bundle.
//!
//! GOAL (one line): TODO.
//!
//! This is the GROUND TRUTH for __STEM_UPPER__.md. Every value below is computed
//! by this file; the .md guide pastes it verbatim. Never hand-compute.
//!
//! Run:
//!     just run __STEM__

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

// TODO: fn section_a() ... each prints a banner + a readable block + checks.

fn main() {
    println!("__STEM__.rs — bundle.");
    println!("Every value below is computed by this file.");
    // section_a();
    banner("DONE — all sections printed");
}
