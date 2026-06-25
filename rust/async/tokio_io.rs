//! tokio_io.rs — Phase 7 bundle (async member).
//!
//! GOAL (one line): show, by printing every value, how `tokio::io` turns the
//! blocking `Read`/`Write` model into polled `AsyncRead`/`AsyncWrite`, driven
//! entirely `.await` — and how `duplex`, `copy`, `BufReader`, EOF, and the
//! `tokio_util::io` stream bridges behave on a deterministic in-memory pipe.
//!
//! This is the GROUND TRUTH for TOKIO_IO.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! All I/O here is IN-MEMORY (`tokio::io::duplex`, `std::io::Cursor`): no
//! network, no files, fully deterministic — so `_output.txt` is byte-stable.
//!
//! Run:
//!     just run tokio_io   (== cargo run --bin tokio_io)

use std::io;

use bytes::Bytes;
use futures::StreamExt;
use futures::stream;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader, copy, duplex};
use tokio_util::io::{ReaderStream, StreamReader};

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

// ── Section A: AsyncWrite/AsyncRead over an in-memory duplex pipe ───────────

async fn section_a() {
    banner("A — AsyncWrite/AsyncRead over an in-memory duplex pipe");
    // `tokio::io::duplex(n)` returns a PAIR of connected, in-memory byte
    // streams: bytes written on one side become readable on the other, exactly
    // like a socket pair. `n` is the per-side buffer cap before a write parks.
    // This is the test-friendly substitute for a real TCP connection: no DNS,
    // no network, fully deterministic. Both halves implement AsyncRead +
    // AsyncWrite, so the SAME Ext methods (.write_all, .read, ...) apply.
    let (mut tx, mut rx) = duplex(64);
    println!("  let (mut tx, mut rx) = tokio::io::duplex(64);");

    // write_all: AsyncWriteExt -> writes the WHOLE slice, looping internally
    // across `poll_write` until every byte is accepted. (See pitfalls: it does
    // NOT flush by itself.)
    tx.write_all(b"hello").await.expect("write_all");
    println!("  tx.write_all(b\"hello\").await;   // 5 bytes flow into the pipe");

    // read: AsyncReadExt -> pulls SOME bytes into `buf`, returning how many.
    // Ok(0) means EOF. In-memory duplex with a 64-byte buffer returns all 5
    // bytes written so far in a single read.
    let mut buf = [0u8; 16];
    let n = rx.read(&mut buf).await.expect("read");
    println!(
        "  rx.read(&mut buf).await -> {} bytes: {:?}  ({:?})",
        n,
        &buf[..n],
        std::str::from_utf8(&buf[..n]).unwrap(),
    );

    check(
        "bytes written on `tx` emerge unchanged on `rx` through the duplex",
        &buf[..n] == b"hello",
    );
    check("a single .read() drained the whole 5-byte payload", n == 5);

    // flush is an explicit AsyncWriteExt call: it pushes any internal buffer
    // down to the destination. write_all does NOT guarantee a flush.
    tx.write_all(b"!").await.expect("write_all");
    tx.flush().await.expect("flush");
    let mut rest = [0u8; 4];
    let m = rx.read(&mut rest).await.expect("read");
    check(
        "after flush, the extra byte written is readable on the other side",
        &rest[..m] == b"!",
    );
}

// ── Section B: copy — stream a reader into a writer, returns total copied ────

async fn section_b() {
    banner("B — tokio::io::copy streams reader -> writer, returns total bytes");
    // `tokio::io::copy(&mut reader, &mut writer)` is the async twin of
    // std::io::copy. It allocates an 8 KB scratch buffer, loops read->write
    // until the reader hits EOF, and returns the TOTAL number of bytes moved.
    // Constraints: both bounds must be `Unpin` (you can hold a &mut to them).
    let (mut tx, mut rx) = duplex(64);
    tx.write_all(b"world").await.expect("write_all");
    println!("  tx.write_all(b\"world\").await;   // 5 bytes seeded into the pipe");

    // Drop `tx` so `rx` sees EOF after draining (see Section E for EOF depth).
    // Without EOF, copy would wait forever for more data.
    drop(tx);
    println!("  drop(tx);   // signal EOF so `copy` knows when to stop");

    let mut sink = Vec::new(); // Vec<u8> implements AsyncWrite
    let copied = copy(&mut rx, &mut sink).await.expect("copy");
    println!(
        "  copy(&mut rx, &mut sink).await -> copied = {} bytes",
        copied
    );
    println!("  sink = {:?}", String::from_utf8_lossy(&sink));

    check(
        "copy reports the exact byte count it moved (5)",
        copied == 5,
    );
    check(
        "copy's destination contains the streamed bytes",
        sink == b"world",
    );
}

// ── Section C: read_to_end — drain a reader fully into a Vec<u8> ─────────────

async fn section_c() {
    banner("C — read_to_end drains an AsyncRead fully into a Vec<u8>");
    // `AsyncReadExt::read_to_end(&mut buf)` repeatedly calls `read()` and
    // APPENDS to `buf` until `read()` returns Ok(0) (EOF). Returns the count of
    // newly-read bytes. A `Cursor<Vec<u8>>` is an in-memory AsyncRead whose
    // length is fixed -> the whole content is read, then EOF.
    let payload = b"the quick brown fox";
    let mut reader = std::io::Cursor::new(payload.to_vec());
    println!(
        "  let reader = Cursor::new({:?});   // {} bytes, then EOF",
        String::from_utf8_lossy(payload),
        payload.len()
    );

    let mut buf = Vec::new();
    let read = reader.read_to_end(&mut buf).await.expect("read_to_end");
    println!("  read_to_end(&mut buf).await -> read = {} bytes", read);
    println!("  buf = {:?}", String::from_utf8_lossy(&buf));

    check(
        "read_to_end returns the full payload length",
        read == payload.len(),
    );
    check(
        "read_to_end captured the exact bytes of the source",
        buf == payload,
    );
}

// ── Section D: BufReader + lines — async line splitting ──────────────────────

async fn section_d() {
    banner("D — BufReader + lines(): async newline-splitting over AsyncRead");
    // `BufReader::new(r)` wraps an AsyncRead with an 8 KB read-ahead buffer so
    // that many small reads share one big underlying read. `AsyncBufReadExt::
    // lines()` turns the buffered reader into a `Lines` struct (which impls the
    // Stream trait). Its inherent `next_line().await` returns the next line as
    // io::Result<Option<String>> — None at EOF.
    let (mut tx, rx) = duplex(64);
    let text = "alpha\nbeta\ngamma";
    tx.write_all(text.as_bytes()).await.expect("write_all");
    drop(tx); // EOF so the final (newline-less) line still gets emitted
    println!("  tx.write_all(b\"alpha\\nbeta\\ngamma\"); drop(tx);");

    // tokio::io::Lines exposes an inherent `next_line()` async method returning
    // io::Result<Option<String>> — no Stream trait needed (see pitfalls).
    let mut lines = BufReader::new(rx).lines();
    let first = lines
        .next_line()
        .await
        .expect("next_line io")
        .expect("no first line");
    let second = lines
        .next_line()
        .await
        .expect("next_line io")
        .expect("no second line");
    println!("  lines().next().await (1st) = {:?}", first);
    println!("  lines().next().await (2nd) = {:?}", second);

    check(
        "first line is split at the first newline -> \"alpha\"",
        first == "alpha",
    );
    check(
        "second line is split at the second newline -> \"beta\"",
        second == "beta",
    );
}

// ── Section E: EOF — dropping the writer terminates the reader ───────────────

async fn section_e() {
    banner("E — EOF: dropping the writer lets the reader finish (no hang)");
    // An AsyncRead signals EOF by returning Ok(0). For a duplex, dropping the
    // writer half is what produces that EOF on the reader half AFTER it drains
    // the buffered bytes. `read_to_end` loops until Ok(0); if the writer were
    // never dropped, `read_to_end` would park forever -> a deadlock. Here we
    // prove the drop makes it terminate with the accumulated payload.
    let (mut tx, mut rx) = duplex(64);
    tx.write_all(b"final").await.expect("write_all");
    println!("  tx.write_all(b\"final\").await;   // 5 bytes buffered for rx");

    // `tx` is dropped at the end of this block — but we drop it FIRST so the
    // subsequent read_to_end observes EOF after the 5 buffered bytes.
    drop(tx);
    println!("  drop(tx);   // writer gone -> rx will hit Ok(0) after draining");

    let mut out = Vec::new();
    let n = rx.read_to_end(&mut out).await.expect("read_to_end"); // would hang w/o EOF
    println!(
        "  rx.read_to_end(&mut out).await -> {} bytes: {:?}",
        n,
        String::from_utf8_lossy(&out)
    );

    check(
        "after the writer drops, read_to_end returns (does NOT hang)",
        n == 5,
    );
    check(
        "EOF drains exactly the bytes written before the drop",
        out == b"final",
    );
}

// ── Section F: ReaderStream / StreamReader — bridge AsyncRead <-> Stream ─────

async fn section_f() {
    banner("F — ReaderStream / StreamReader: bridge AsyncRead <-> byte Stream");
    // `tokio_util::io` (enabled via the `io` feature) provides the two halves
    // of the stream<->I/O bridge used by hyper/reqwest for chunked bodies:
    //   * ReaderStream: AsyncRead -> Stream<Item = io::Result<Bytes>>
    //   * StreamReader: Stream<Item = io::Result<Bytes>> -> AsyncRead
    // (The Sink->AsyncWrite half is `SinkWriter`; there is no type named
    //  "StreamWriter" in tokio_util — see TOKIO_IO.md pitfalls.)

    // --- Direction 1: AsyncRead -> Stream of byte chunks -------------------
    let data = b"stream-me!".to_vec();
    let cursor = std::io::Cursor::new(data.clone());
    let mut reader_stream = ReaderStream::new(cursor);
    println!(
        "  ReaderStream::new(Cursor({:?}))",
        String::from_utf8_lossy(&data)
    );

    let mut chunks: Vec<Bytes> = Vec::new();
    while let Some(chunk) = reader_stream.next().await {
        chunks.push(chunk.expect("chunk"));
    }
    let mut rejoined = Vec::new();
    for chunk in &chunks {
        rejoined.extend_from_slice(chunk);
    }
    println!(
        "  -> {} chunk(s); rejoined = {:?}",
        chunks.len(),
        String::from_utf8_lossy(&rejoined)
    );
    check(
        "ReaderStream re-emits the whole reader content when chunks are rejoined",
        rejoined == data,
    );

    // --- Direction 2: Stream of byte chunks -> AsyncRead -------------------
    let byte_stream = stream::iter([
        Ok::<Bytes, io::Error>(Bytes::from_static(b"chunk-1")),
        Ok::<Bytes, io::Error>(Bytes::from_static(b"-chunk-2")),
    ]);
    let mut reader = StreamReader::new(byte_stream);
    println!("  StreamReader::new(stream of [b\"chunk-1\", b\"-chunk-2\"])");

    let mut out = Vec::new();
    let n = reader.read_to_end(&mut out).await.expect("read_to_end");
    println!(
        "  reader.read_to_end(&mut out).await -> {} bytes: {:?}",
        n,
        String::from_utf8_lossy(&out)
    );
    check(
        "StreamReader concatenates the chunks back into one byte stream",
        out == b"chunk-1-chunk-2",
    );
}

#[tokio::main]
async fn main() {
    println!("tokio_io.rs — Phase 7 bundle (async member).");
    println!("Every value below is computed by this file.\n");
    section_a().await;
    section_b().await;
    section_c().await;
    section_d().await;
    section_e().await;
    section_f().await;
    banner("DONE — all sections printed");
}
