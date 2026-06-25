//! fs_paths.rs — Phase 5 bundle.
//!
//! GOAL (one line): show, by writing and reading files in a temp dir, how Rust's
//! `std::fs` (`read`/`write`/`File`), `std::path` (`Path`/`PathBuf`), `read_dir`,
//! `canonicalize`, and `env::temp_dir` work together for cross-platform FS I/O.
//!
//! This is the GROUND TRUTH for FS_PATHS.md. Every value below is computed by
//! this file; the .md guide pastes it verbatim. Never hand-compute.
//!
//! DETERMINISM: all writes go to `env::temp_dir()` + a FIXED filename; the temp
//! dir's absolute prefix varies per OS/session (and on macOS `/tmp` is a symlink
//! to `/private/tmp`), so this file NEVER prints an absolute path as a value —
//! it asserts only structural facts (file names, content, sizes, booleans) that
//! are reproducible anywhere. `read_dir` entries are collected and SORTED before
//! printing (iteration order is not guaranteed). Each section best-effort removes
//! its own scratch files before and after, so re-runs are clean.
//!
//! Run:
//!     just run fs_paths   (== cargo run --bin fs_paths)

use std::env;
use std::ffi::OsStr;
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

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

/// Best-effort scratch removal; ignores "not found" (stale cleanup) and errors.
fn rm_file(path: &Path) {
    let _ = fs::remove_file(path);
}
fn rm_dir(path: &Path) {
    let _ = fs::remove_dir_all(path);
}

/// The fixed scratch names under `env::temp_dir()` (absolute prefix elided in
/// all output because it varies per OS/session and may be a symlink).
fn probe_file() -> PathBuf {
    env::temp_dir().join("rs_fs_probe.txt")
}
fn probe_dir() -> PathBuf {
    env::temp_dir().join("rs_fs_probe_dir")
}

// ── Section A: write + read round-trip (fs::write / read / read_to_string) ───

fn section_a() -> std::io::Result<()> {
    banner("A — write then read: fs::write / read / read_to_string");
    rm_file(&probe_file());
    let path = probe_file();

    // fs::write(path, bytes): creates the file if missing, REPLACES it if present.
    // Signature: pub fn write<P: AsRef<Path>, C: AsRef<[u8]>>(path: P, contents: C)
    let payload = "hello";
    fs::write(&path, payload)?;
    println!("  fs::write(temp/\"rs_fs_probe.txt\", \"hello\");  // created/replaced");

    // fs::read_to_string: whole file decoded as UTF-8 into a String. Errors if the
    // bytes are not valid UTF-8.
    let text = fs::read_to_string(&path)?;
    println!("  fs::read_to_string -> {:?}  (len {})", text, text.len());

    // fs::read: whole file as Vec<u8> (raw bytes — no UTF-8 requirement). This is
    // the function to reach for when the file may be binary or non-UTF-8.
    let bytes = fs::read(&path)?;
    println!(
        "  fs::read          -> len {}, bytes = {:?}",
        bytes.len(),
        bytes
    );

    check(
        "write \"hello\" then read_to_string returns \"hello\"",
        text == "hello",
    );
    check(
        "fs::read byte length matches the 5-byte payload",
        bytes.len() == 5,
    );
    check("first byte of \"hello\" is b'h' (104)", bytes[0] == b'h');

    rm_file(&path);
    Ok(())
}

// ── Section B: Path (borrowed) vs PathBuf (owned) — the str/String analog ─────

fn section_b() -> std::io::Result<()> {
    banner("B — Path (borrowed, unsized) vs PathBuf (owned, growable)");
    // `Path` is `?Sized` (always behind &/Box), exactly like `str`. `PathBuf`
    // owns its bytes and is growable, like `String`. Both are thin wrappers over
    // OsStr/OsString, so they carry the LOCAL platform's path syntax.
    let joined: PathBuf = PathBuf::from("a").join("b.txt");
    println!(
        "  PathBuf::from(\"a\").join(\"b.txt\") -> {}",
        joined.display()
    );
    println!(
        "  std::path::MAIN_SEPARATOR         = {:?}",
        std::path::MAIN_SEPARATOR
    );

    // Pure path queries — NO filesystem access, fully deterministic on any OS.
    let p = Path::new("x.txt");
    println!(
        "  Path::new(\"x.txt\").file_name()   -> {:?}",
        p.file_name()
    );
    println!(
        "  Path::new(\"x.txt\").file_stem()   -> {:?}",
        p.file_stem()
    );
    println!(
        "  Path::new(\"x.txt\").extension()   -> {:?}",
        p.extension()
    );

    let parent = Path::new("a/b.txt").parent();
    println!("  Path::new(\"a/b.txt\").parent()    -> {:?}", parent);

    check(
        "join builds the cross-platform path \"a/b.txt\"",
        joined.as_path() == Path::new("a/b.txt"),
    );
    check(
        "file_stem(\"x.txt\") == \"x\"",
        p.file_stem() == Some(OsStr::new("x")),
    );
    check(
        "extension(\"x.txt\") == \"txt\"",
        p.extension() == Some(OsStr::new("txt")),
    );
    check(
        "parent(\"a/b.txt\") == \"a\"",
        parent == Some(Path::new("a")),
    );
    Ok(())
}

// ── Section C: File::open / File::create — a Read/Write handle (drops = close)

fn section_c() -> std::io::Result<()> {
    banner("C — File::open / File::create: a Read+Write handle, closed on DROP");
    rm_file(&probe_file());
    let path = probe_file();

    // File::create opens for WRITE (create + truncate). It yields a Write handle.
    // The OS file descriptor is closed when `f` is DROPPED — RAII, no close() call.
    {
        let mut f = File::create(&path)?;
        f.write_all(b"file-content")?;
        println!("  File::create(path); f.write_all(b\"file-content\");");
    } // <- `f` drops HERE: the fd closes before the next block reads.

    // File::open opens for READ (read-only). It yields a Read handle.
    let mut f = File::open(&path)?;
    let mut buf = String::new();
    f.read_to_string(&mut buf)?;
    println!(
        "  File::open(path); read_to_string -> {:?}  (len {})",
        buf,
        buf.len()
    );

    check(
        "File::create + write_all, then File::open + read_to_string round-trips",
        buf == "file-content",
    );
    check("File::write_all wrote 12 bytes", buf.len() == 12);

    rm_file(&path);
    Ok(())
}

// ── Section D: read_dir → entries (order NOT guaranteed → SORT) ──────────────

fn section_d() -> std::io::Result<()> {
    banner("D — read_dir: an iterator of entries (order NOT guaranteed -> SORT)");
    let dir = probe_dir();
    rm_dir(&dir);
    fs::create_dir(&dir)?;

    // Drop three files with KNOWN names into the fresh dir, deliberately in an
    // unsorted creation order.
    let names = ["03.txt", "01.txt", "02.txt"];
    for n in names {
        fs::write(dir.join(n), n)?;
    }
    println!("  created 3 files in a fresh temp dir: {:?}", names);

    // read_dir yields io::Result<DirEntry>; collect into Vec, then SORT for
    // reproducible output. The canonical collect pattern (read_dir docs) is
    // collect::<Result<Vec<_>, _>>()?, which short-circuits on the first error.
    let mut entries: Vec<String> = fs::read_dir(&dir)?
        .map(|res| res.map(|e| e.file_name().to_string_lossy().into_owned()))
        .collect::<std::io::Result<Vec<_>>>()?;
    entries.sort(); // DETERMINISM: read_dir order is unspecified per-call/OS.
    println!("  read_dir entries (SORTED): {:?}", entries);

    let expected: Vec<String> = ["01.txt", "02.txt", "03.txt"]
        .iter()
        .map(|s| s.to_string())
        .collect();
    check(
        "sorted read_dir names == [\"01.txt\", \"02.txt\", \"03.txt\"]",
        entries == expected,
    );
    check("read_dir yielded exactly 3 entries", entries.len() == 3);

    rm_dir(&dir);
    Ok(())
}

// ── Section E: exists / is_file / is_dir (swallow errors: TOCTOU trap) ───────

fn section_e() -> std::io::Result<()> {
    banner("E — exists() / is_file() / is_dir() (swallow errors: TOCTOU trap)");
    // Re-create one file + one dir to probe.
    rm_file(&probe_file());
    rm_dir(&probe_dir());
    let file = probe_file();
    let dir = probe_dir();
    fs::write(&file, "probe")?;
    fs::create_dir(&dir)?;

    println!(
        "  the temp FILE: exists={}, is_file={}, is_dir={}",
        file.exists(),
        file.is_file(),
        file.is_dir()
    );
    println!(
        "  the temp DIR : exists={}, is_file={}, is_dir={}",
        dir.exists(),
        dir.is_file(),
        dir.is_dir()
    );

    check(
        "written file: exists() && is_file() && !is_dir()",
        file.exists() && file.is_file() && !file.is_dir(),
    );
    check(
        "temp dir: exists() && is_dir() && !is_file()",
        dir.exists() && dir.is_dir() && !dir.is_file(),
    );

    // try_exists (1.63) is the non-swallowing variant: it returns io::Result<bool>,
    // surfacing permission/IO errors instead of hiding them behind `false`.
    let te = file.try_exists()?;
    println!("  file.try_exists() -> Ok({})", te);
    check("try_exists() returns Ok(true) for the written file", te);

    rm_file(&file);
    rm_dir(&dir);
    Ok(())
}

// ── Section F: canonicalize — absolute, normalized, symlinks resolved ────────

fn section_f() -> std::io::Result<()> {
    banner("F — fs::canonicalize: absolute form, symlinks resolved");
    rm_file(&probe_file());
    let path = probe_file();
    fs::write(&path, "canon")?;

    // temp_dir() may itself be a symlink (e.g. macOS /tmp -> /private/tmp);
    // canonicalize resolves EVERY component and yields a real absolute path.
    // The absolute prefix varies per machine, so we never print it — only the
    // structural facts that hold anywhere.
    let canon = fs::canonicalize(&path)?;
    println!(
        "  canonicalize succeeded; is_absolute = {}",
        canon.is_absolute()
    );
    println!("  (absolute prefix elided — it varies per OS/session)");
    println!(
        "  canon.file_name()               = {:?}",
        canon.file_name()
    );
    println!(
        "  canon == canonicalize(path) again -> {}",
        canon == fs::canonicalize(&path)?
    );

    check("canonicalize yields an absolute path", canon.is_absolute());
    check(
        "canonicalize ends with the file's name (\"rs_fs_probe.txt\")",
        canon.file_name() == Some(OsStr::new("rs_fs_probe.txt")),
    );

    rm_file(&path);
    Ok(())
}

fn main() -> std::io::Result<()> {
    println!("fs_paths.rs — Phase 5 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a()?;
    section_b()?;
    section_c()?;
    section_d()?;
    section_e()?;
    section_f()?;
    banner("DONE — all sections printed");
    Ok(())
}
