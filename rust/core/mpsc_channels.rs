//! mpsc_channels.rs — Phase 4 bundle.
//!
//! GOAL (one line): show, by printing every value, how Rust's `std::sync::mpsc`
//! channels transfer OWNERSHIP of messages between threads — "share memory by
//! communicating" — across one receiver and (cloned) multiple senders, both
//! unbounded (`channel`) and bounded (`sync_channel`).
//!
//! This is the GROUND TRUTH for MPSC_CHANNELS.md. Every number, table, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! One rule here is a COMPILE ERROR (using a value after `send` moves it). That
//! cannot live in a runnable file — it is documented in MPSC_CHANNELS.md with
//! the exact compiler message (E0382).
//!
//! DETERMINISM: the interleaving of sends from multiple producers is
//! NONDETERMINISTIC. Section D collects every received value into a Vec, SORTS
//! it, and only then prints — never in scheduling order. No thread prints
//! directly. See HOW_TO_RESEARCH.md §4.2 rule 3.
//!
//! Run:
//!     just run mpsc_channels   (== cargo run --bin mpsc_channels)

use std::sync::mpsc::{RecvError, TrySendError, channel, sync_channel};
use std::thread;

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

// ── Section A: the basic handshake — send moves, recv blocks ────────────────

fn section_a() {
    banner("A — basic send/recv: send MOVES the value, recv blocks");
    // channel() -> (Sender, Receiver): an ASYNCHRONOUS, unbounded channel.
    // "All sends will be asynchronous (they never block). The channel
    // conceptually has an infinite buffer." — std::sync::mpsc docs.
    let (tx, rx) = channel();
    println!("  let (tx, rx) = channel();   // async, UNBOUNDED, send never blocks");

    // tx.send(v) takes v BY VALUE -> v is MOVED into the channel (see Section B).
    // It takes &self, so the same Sender can send again. On an async channel it
    // returns immediately; the value sits in the buffer.
    tx.send(42).unwrap();
    println!("  tx.send(42);   // 42 moved into the channel; tx still usable");

    // rx.recv() BLOCKS the current thread until a value arrives, then returns
    // Result<T, RecvError>. It returns Err ONLY when every Sender has dropped.
    let got = rx.recv();
    println!("  rx.recv() -> {:?}", got);

    check("tx.send(42) then rx.recv() yields Ok(42)", got == Ok(42));
}

// ── Section B: send MOVES the value — ownership crosses the channel ─────────

fn section_b() {
    banner("B — send MOVES: ownership crosses the channel (E0382 if reused)");
    let (tx, rx) = channel();
    let msg = String::from("hello");
    println!("  let msg = String::from(\"hello\");  (msg owns the heap buffer)");

    // tx.send(msg) MOVES msg: String is not Copy, so the heap buffer's ownership
    // travels from this stack frame into the channel. Using `msg` after this
    // line is a COMPILE ERROR (E0382) — see MPSC_CHANNELS.md for the message:
    //   error[E0382]: borrow of moved value: `msg`
    tx.send(msg).unwrap();
    println!("  tx.send(msg);   // msg MOVED into the channel; the binding is poisoned");
    // println!("{msg}");   // E0382 — would not compile

    // The receiver picks up FULL OWNERSHIP of the String — it may mutate it,
    // drop it, or hand it on. No deep copy of the heap bytes was made.
    let received = rx.recv().unwrap();
    println!(
        "  rx.recv() -> {:?}  (receiver now OWNS the String; len {})",
        received,
        received.len()
    );

    check(
        "ownership transferred through the channel: receiver owns the String",
        received == "hello",
    );
}

// ── Section C: rx.iter() drains the channel until all Senders drop ──────────

fn section_c() {
    banner("C — rx.iter(): drain the channel until every Sender drops");
    let (tx, rx) = channel();
    println!("  let (tx, rx) = channel();");

    // Single producer, FIFO: the order sent == the order received.
    tx.send(1).unwrap();
    tx.send(2).unwrap();
    tx.send(3).unwrap();
    println!("  tx.send(1); tx.send(2); tx.send(3);");

    // CRITICAL: drop the Sender so the channel CLOSES. Without this drop,
    // rx.iter() would block forever waiting for more (tx is still alive).
    drop(tx);
    println!("  drop(tx);   // closes the channel -> rx.iter() will terminate");

    // rx.iter() yields each buffered message (blocking for the next) and returns
    // None once every Sender has hung up, so the iteration ends naturally.
    let collected: Vec<i32> = rx.iter().collect();
    println!("  collected via rx.iter() -> {:?}", collected);

    check(
        "rx.iter() yields [1, 2, 3] in FIFO order from one producer",
        collected == vec![1, 2, 3],
    );
}

// ── Section D: multiple producers — clone tx; collect; SORT (determinism) ───

fn section_d() {
    banner("D — multiple producers: clone tx per thread; collect and SORT");
    let (tx, rx) = channel();
    println!("  let (tx, rx) = channel();");

    // Sender is Clone: each clone is another producer feeding the SAME single
    // receiver. The Book calls this "multiple producer, single consumer".
    let values = [10, 20, 30];
    let mut handles = Vec::new();
    for v in values {
        let tx = tx.clone(); // one clone per thread
        handles.push(thread::spawn(move || {
            tx.send(v).unwrap(); // v moved into the closure, then into the channel
        }));
    }
    println!(
        "  spawned {} threads, each cloned tx and sent one of {:?}",
        handles.len(),
        values
    );

    // Drop the ORIGINAL sender so that once all clones drop (threads finish),
    // the channel closes and rx.iter() terminates.
    drop(tx);

    // Join every producer so all sends complete before we collect.
    for h in handles {
        h.join().unwrap();
    }

    // DETERMINISM: the interleaving of sends from multiple threads is
    // NONDETERMINISTIC, so we NEVER print in receive order. Collect, SORT,
    // then print -> byte-identical output on every run.
    let mut collected: Vec<i32> = rx.iter().collect();
    collected.sort_unstable();
    println!("  collected (sorted) -> {:?}", collected);

    check(
        "3 cloned senders delivered exactly {10, 20, 30} (as a set)",
        collected == vec![10, 20, 30],
    );
}

// ── Section E: bounded sync_channel — backpressure (send BLOCKS when full) ───

fn section_e() {
    banner("E — bounded sync_channel: send BLOCKS when the buffer is full");
    // sync_channel(bound): a SYNCHRONOUS, bounded channel. `bound` is the fixed
    // buffer size. "When the internal buffer becomes full, future sends will
    // block waiting for the buffer to open up." — std::sync::mpsc docs.
    let (tx, rx) = sync_channel(1);
    println!("  let (tx, rx) = sync_channel(1);   // bounded buffer of size 1");

    // First send fills the single slot and returns immediately.
    tx.send(1).unwrap();
    println!("  tx.send(1).unwrap();   (slot now FULL)");

    // A second send would BLOCK here. We observe that full state deterministically
    // with try_send (it NEVER blocks): it returns Err(Full(v)) when there is no
    // room, handing the value back to us.
    let r2 = tx.try_send(2);
    println!(
        "  tx.try_send(2) -> {:?}   (Full == backpressure: send would block)",
        r2
    );
    check(
        "bounded(1) channel is full after 1 send -> try_send returns Full(2)",
        matches!(r2, Err(TrySendError::Full(2))),
    );

    // Drain one slot -> a slot opens -> the previously-rejected value fits.
    let drained = rx.recv();
    println!("  rx.recv() -> {:?}   (freed the slot)", drained);

    tx.send(2).unwrap(); // now there is room
    let second = rx.recv();
    println!("  tx.send(2); rx.recv() -> {:?}", second);
    check(
        "after draining, the bounded channel accepts the queued value",
        drained == Ok(1) && second == Ok(2),
    );

    // RENDEZVOUS: sync_channel(0) has zero buffer. "A buffer size of 0 is valid,
    // in which case this becomes rendezvous channel where each send will not
    // return until a recv is paired with it." — std::sync::mpsc docs.
    let (tx0, rx0) = sync_channel(0);
    println!("  let (tx0, rx0) = sync_channel(0);   // rendezvous: 0-buffer");
    let handle = thread::spawn(move || {
        tx0.send(7).unwrap(); // blocks until main's rx0.recv() takes it
    });
    let handed = rx0.recv();
    handle.join().unwrap();
    println!("  spawned send(7) handed off -> rx0.recv() = {:?}", handed);
    check(
        "sync_channel(0) rendezvous: recv returns the handed-off value",
        handed == Ok(7),
    );
}

// ── Section F: channel close — drop all Senders -> recv returns Err ──────────

fn section_f() {
    banner("F — channel close: drop ALL Senders -> recv returns Err");
    let (tx, rx) = channel::<i32>();
    println!("  let (tx, rx) = channel::<i32>();");

    // Dropping every Sender closes the channel. recv then wakes and returns
    // Err(RecvError) — "no more values can ever arrive." (Values sent BEFORE the
    // drop are still delivered: channels buffer.) "all senders (including the
    // original) need to be dropped for the receiver to stop blocking." — Sender.
    drop(tx);
    println!("  drop(tx);   // no Senders remain -> channel is CLOSED");

    let after = rx.recv();
    println!("  rx.recv() -> {:?}", after);
    check(
        "recv returns Err(RecvError) once all Senders are dropped",
        after == Err(RecvError),
    );

    // rx.iter() likewise ends at once: it returns None on a closed channel, so
    // the loop body never runs and the collected Vec is empty.
    let drained: Vec<i32> = rx.iter().collect();
    println!("  rx.iter().collect::<Vec<_>>() -> {:?}", drained);
    check(
        "rx.iter() over a closed channel yields nothing",
        drained.is_empty(),
    );
}

// ── Section G: send error — drop the Receiver -> send returns Err ────────────

fn section_g() {
    banner("G — send error: drop the Receiver -> send returns Err(SendError)");
    let (tx, rx) = channel();
    println!("  let (tx, rx) = channel();");

    // The symmetric disconnect: dropping the RECEIVER makes further sends
    // pointless. send returns Err(SendError(v)), handing the value BACK to the
    // sender. This is how a producer detects that the consumer has gone away.
    drop(rx);
    println!("  drop(rx);   // consumer gone");

    let bounced = tx.send(99);
    let returned = match &bounced {
        Err(e) => Some(e.0), // SendError(pub T) -> the bounced-back value
        _ => None,
    };
    println!(
        "  tx.send(99) -> {:?}   (value bounced back to the sender)",
        bounced
    );
    check(
        "send returns the value (99) when the Receiver was dropped",
        returned == Some(99),
    );
}

fn main() {
    println!("mpsc_channels.rs — Phase 4 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    section_g();
    banner("DONE — all sections printed");
}
