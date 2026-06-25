//! io.rs — Phase 5 bundle.
//!
//! GOAL (one line): show, by printing every value, how `std::io` reads bytes
//! (`Read`), writes bytes (`Write`), buffers line reads (`BufRead`), streams
//! reader→writer (`io::copy`), and models failures (`io::Result`/`io::Error`) —
//! all in-memory via `Cursor`/`Vec<u8>`/`&[u8]`, with NO files and NO network.
//!
//! This is the GROUND TRUTH for IO.md. Every number and worked example in the
//! guide is printed by this file. Change it -> re-run -> re-paste. Never
//! hand-compute.
//!
//! Determinism: every reader/writer here is in-memory (`Cursor`, `Vec<u8>`,
//! `&[u8]`), so the output is byte-reproducible across runs — no ASLR, no
//! thread interleaving, no random seed.
//!
//! Run:
//!     just run io   (== cargo run --bin io)

use std::io::{self, BufRead, BufReader, Cursor, Read, Write};

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

// ── Section A: Read — pull bytes into a caller-owned buffer; Ok(0) = EOF ─────

fn section_a() {
    banner("A — Read: pull bytes into a caller buffer; Ok(0) is EOF");
    // `Cursor` wraps an in-memory byte buffer and implements Read (also
    // BufRead, Seek, and — over Vec — Write). Its position starts at 0.
    let mut reader = Cursor::new(b"hi");
    println!("  Cursor::new(b\"hi\");  position = {}", reader.position());

    // read() fills the CALLER's buffer up to its length and returns the count.
    // It MAY return fewer than buf.len() (a "short read"); Ok(0) signals EOF
    // and is NOT an error.
    let mut buf = [0u8; 2];
    let n = reader
        .read(&mut buf)
        .expect("in-memory read never errors here");
    println!("  reader.read(&mut [0u8;2]) -> n = {n}, buf = {buf:?}");
    check("read fills the 2-byte buffer with b\"hi\"", buf == *b"hi");

    // A second read is now at EOF -> Ok(0).
    let n_eof = reader
        .read(&mut buf)
        .expect("in-memory read never errors here");
    println!("  reader.read(&mut buf) again -> n = {n_eof}  (0 == end of stream)");
    check("read returns Ok(0) at EOF, not an Err", n_eof == 0);

    // `&[u8]` ITSELF implements Read: each read ADVANCES the slice reference to
    // the unread remainder — a borrowed cursor over borrowed bytes. This is why
    // `&[u8]` plugs into any `impl Read` API for free.
    let mut bytes: &[u8] = b"hello";
    let mut two = [0u8; 2];
    let m = bytes.read(&mut two).expect("read from &[u8] never errors");
    println!("  let mut bytes: &[u8] = b\"hello\";  read {m} -> {two:?}; bytes left = {bytes:?}");
    check(
        "&[u8] Read advances the slice to the unread remainder",
        m == 2 && bytes == b"llo",
    );
}

// ── Section B: Write — drain a caller buffer into a sink; flush pushes it ────

fn section_b() {
    banner("B — Write: drain a buffer into a sink; Vec<u8> is a Writer");
    // `Vec<u8>` implements Write by APPENDING (it grows as needed). `write`
    // returns how many bytes it accepted (may be a partial write).
    let mut out: Vec<u8> = Vec::new();
    let n = out.write(b"data").expect("Vec write never errors");
    println!("  out.write(b\"data\") -> wrote {n} byte(s); out = {out:?}");
    check("write() returns the count of bytes accepted", n == 4);

    // `write_all` loops `write` until the WHOLE buffer is consumed (or a real
    // error surfaces) — the convenience method you reach for in practice.
    out.write_all(b"-more").expect("Vec write_all never errors");
    println!("  out.write_all(b\"-more\"); out = {out:?}");
    check(
        "Vec<u8> Writer appends bytes via write_all",
        out == b"data-more",
    );

    // flush() is a no-op for Vec (it has no internal staging buffer); it only
    // matters for BufWriter / real sinks. The trait still requires it.
    out.flush().expect("Vec flush never errors");
    check(
        "flush on Vec is a no-op; contents unchanged",
        out == b"data-more",
    );
}

// ── Section C: io::copy — stream ALL bytes reader→writer, return total ───────

fn section_c() {
    banner("C — io::copy: stream reader -> writer; returns total bytes (u64)");
    let mut reader = Cursor::new(b"hello");
    let mut writer: Vec<u8> = Vec::new();
    // copy() loops read()/write() until EOF, transparently retrying on
    // ErrorKind::Interrupted, and returns the total copied as u64.
    let copied = io::copy(&mut reader, &mut writer).expect("in-memory copy never errors");
    println!("  io::copy(Cursor(b\"hello\"), &mut Vec) -> copied = {copied}");
    println!("  writer == {writer:?}");
    check("io::copy returns the total bytes streamed", copied == 5);
    check(
        "io::copy reproduces the source bytes in the writer",
        writer == b"hello",
    );
}

// ── Section D: BufRead — buffered reading; .lines() -> Iterator<Result<String>>

fn section_d() {
    banner("D — BufRead: .lines() yields io::Result<String>, strips newlines");
    // BufReader wraps a Read with an internal buffer (default 8 KiB) so line
    // reads don't cost one syscall (or one read()) per byte. Cursor already
    // implements BufRead, but BufReader is the adapter you wrap a File with.
    let buffered = BufReader::new(Cursor::new(b"a\nb\nc"));
    // lines() yields io::Result<String>, each WITHOUT the trailing newline
    // byte (0xA) or CRLF. collect::<io::Result<Vec<_>>>() short-circuits on
    // the first line that errors (e.g. invalid UTF-8).
    let lines: Vec<String> = buffered
        .lines()
        .collect::<io::Result<Vec<_>>>()
        .expect("in-memory lines never error");
    println!("  BufReader over b\"a\\nb\\nc\" -> lines = {lines:?}");
    check(
        "lines() splits the stream into N newline-free strings",
        lines.len() == 3,
    );
    check("lines() strips the trailing newline byte", lines[1] == "b");
}

// ── Section E: read_to_string / read_exact — whole-stream vs fixed-size reads ─

fn section_e() {
    banner("E — read_to_string (whole stream -> String) / read_exact (fill buf)");
    // read_to_string: reads to EOF into a String; ERRORS if the bytes are not
    // valid UTF-8. Use it when the source is text and fits in memory.
    let mut reader = Cursor::new(b"hello");
    let mut s = String::new();
    let n = reader
        .read_to_string(&mut s)
        .expect("valid UTF-8 in-memory read_to_string");
    println!("  read_to_string -> {n} byte(s); s = {s:?}");
    check(
        "read_to_string consumes the whole stream into a String",
        s == "hello" && n == 5,
    );

    // read_exact: fills the buffer COMPLETELY or returns ErrorKind::UnexpectedEof.
    // The fixed-size read you use for binary headers / framed protocols.
    let mut r2 = Cursor::new(b"WXYZ");
    let mut fixed = [0u8; 4];
    r2.read_exact(&mut fixed).expect("enough bytes in-memory");
    println!("  read_exact(&mut [0u8;4]) <- Cursor(b\"WXYZ\") -> buf = {fixed:?}");
    check(
        "read_exact fills the fixed buffer byte-for-byte",
        fixed == *b"WXYZ",
    );
}

// ── Section F: io::Result + ? — propagate io::Error; construct via Error::new ─

/// Read exactly 2 bytes, using `?` to propagate any `io::Error` to the caller.
/// Demonstrates: `io::Result<T>` is `Result<T, io::Error>`; `?` on a read that
/// returns `Err(e)` short-circuits and returns `Err(e)` from THIS function.
fn read_two<R: Read>(reader: &mut R) -> io::Result<[u8; 2]> {
    let mut buf = [0u8; 2];
    reader.read_exact(&mut buf)?; // <- ? : on Err, propagate io::Error now
    Ok(buf)
}

fn section_f() {
    banner("F — io::Result + ?: propagate io::Error; Error::new / kind() / Display");
    // Happy path: enough bytes -> read_exact succeeds -> Ok(...) bubbles up.
    let mut full = Cursor::new(b"hi");
    let pair = read_two(&mut full).expect("enough bytes -> read_exact succeeds");
    println!("  read_two(Cursor(b\"hi\")) -> Ok({pair:?})");
    check(
        "? propagates the success value on a full read",
        pair == [b'h', b'i'],
    );

    // Error path: EOF before 2 bytes -> read_exact returns UnexpectedEof, which
    // `?` propagates straight out of read_two. unwrap_err() asserts the Err.
    let mut empty = Cursor::new(b"");
    let err = read_two(&mut empty).unwrap_err();
    println!(
        "  read_two(Cursor(b\"\")) -> Err: kind = {:?}, display = \"{err}\"",
        err.kind()
    );
    check(
        "? propagates io::Error out of the function on a short read",
        err.kind() == io::ErrorKind::UnexpectedEof,
    );

    // Constructing custom (non-OS) errors three ways:
    //   - Error::new(kind, payload): kind + arbitrary message (heap-allocates).
    //     (ErrorKind::Other is special: clippy's `io_other_error` reroutes it
    //      to `Error::other` — use any OTHER kind to keep Error::new explicit.)
    //   - Error::from(ErrorKind): kind only, no allocation.
    //   - Error::other(msg): shortcut for Error::new(ErrorKind::Other, msg).
    let custom = io::Error::new(io::ErrorKind::InvalidInput, "boom");
    let from_kind: io::Error = io::ErrorKind::NotFound.into();
    let shortcut = io::Error::other("oops");
    println!(
        "  Error::new(InvalidInput, \"boom\").kind() = {:?}   |   Error::from(NotFound) = \"{from_kind}\"   |   Error::other(\"oops\").kind() = {:?}",
        custom.kind(),
        shortcut.kind(),
    );
    check(
        "Error::new carries the assigned ErrorKind",
        custom.kind() == io::ErrorKind::InvalidInput,
    );
    check(
        "Error: From<ErrorKind> maps NotFound to its Display string",
        format!("{from_kind}") == "entity not found",
    );
    check(
        "Error::other is Error::new(ErrorKind::Other, msg)",
        shortcut.kind() == io::ErrorKind::Other,
    );
}

fn main() {
    println!("io.rs — Phase 5 bundle.");
    println!("Every value below is computed by this file (in-memory I/O via Cursor/Vec).\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
