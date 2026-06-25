//! tokio_channels.rs — Phase 7 bundle (async member).
//!
//! GOAL (one line): show, by printing every value, how tokio's four async
//! channel flavors (mpsc, oneshot, broadcast, watch) synchronize values across
//! async tasks — with `.await` on `send`/`recv`, bounded backpressure, and
//! one-shot / fan-out / latest-value semantics each.
//!
//! This is the GROUND TRUTH for TOKIO_CHANNELS.md. Every number, table, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Lineage: the sync sibling `std::sync::mpsc` (MPSC_CHANNELS) blocks the THREAD
//! on `send`/`recv`. These tokio channels are the ASYNC analogs: `.await` yields
//! the TASK back to the runtime instead of parking an OS thread, so one thread
//! can drive thousands of channels.
//!
//! DETERMINISM: receive order from multiple async producers is nondeterministic,
//! so Section C collects values, SORTS them, and prints from main after the
//! senders finish. No value is printed in receive-scheduling order.
//!
//! Run:
//!     just run tokio_channels   (== cargo run --bin tokio_channels)

use tokio::sync::{broadcast, mpsc, oneshot, watch};

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

// ── Section A: mpsc bounded — the basic async send/recv handshake ────────────

async fn section_a() {
    banner("A — mpsc bounded: async send().await / recv().await handshake");
    // mpsc::channel(n) -> a BOUNDED multi-producer, single-consumer queue.
    // n = max messages buffered before send().await yields (backpressure).
    let (tx, mut rx) = mpsc::channel::<i32>(8);
    println!("  let (tx, rx) = mpsc::channel::<i32>(8);   // bounded(8), MPSC");

    // send().await takes the value BY VALUE (it MOVES in — see MPSC_CHANNELS
    // Section B) and returns Result<(), SendError<T>>. `.await` because on a
    // bounded channel send may YIELD until a slot is free.
    tx.send(42).await.expect("send 42");
    println!("  tx.send(42).await;   // 42 MOVED into the channel");

    // recv().await returns Option<T>: Some(v) for a value, None when ALL senders
    // have been dropped (channel closed). `.await` yields the task until a value
    // arrives or the channel hangs up.
    let got = rx.recv().await;
    println!("  rx.recv().await -> {:?}", got);

    check(
        "tx.send(42).await then rx.recv().await yields Some(42)",
        got == Some(42),
    );

    // Closing: drop the only Sender -> recv().await returns None (not a panic).
    drop(tx);
    let after_close = rx.recv().await;
    println!("  after drop(tx): rx.recv().await -> {:?}", after_close);
    check(
        "recv returns None once all Senders are dropped (channel closed)",
        after_close.is_none(),
    );
}

// ── Section B: bounded backpressure — send().await PARKS when the buffer is full

async fn section_b() {
    banner("B — bounded(1) backpressure: a full channel parks send().await");
    // capacity 1: at most ONE message may be buffered at a time.
    let (tx, mut rx) = mpsc::channel::<i32>(1);
    println!("  let (tx, rx) = mpsc::channel::<i32>(1);   // ONE slot");

    // First send fills the only slot and completes immediately.
    tx.send(1).await.expect("send 1");
    println!("  tx.send(1).await;   // slot now FULL (capacity reached)");

    // DETERMINISTIC WITNESS that send().await would park: try_send never blocks.
    // It reports the would-block state as Err(TrySendError::Full(v)), handing the
    // value back. (We cannot print "I am parked" from a future without making the
    // output nondeterministic; Full(2) IS the proof a send would block here.)
    match tx.try_send(2) {
        Err(mpsc::error::TrySendError::Full(2)) => {
            println!(
                "  tx.try_send(2) -> Err(TrySendError::Full(2))   (= send(2).await would PARK)"
            );
            check(
                "bounded(1) is full -> try_send returns Full(2) (backpressure)",
                true,
            );
        }
        other => {
            check(
                "bounded(1) is full -> try_send returns Full(2) (backpressure)",
                matches!(other, Err(mpsc::error::TrySendError::Full(_))),
            );
        }
    }

    // Show the parked send actually RESUMING once a recv frees the slot.
    // Spawn a sender that calls send(2).await: it parks (slot full), then is
    // woken when rx.recv() takes 1 out and frees the slot.
    let tx2 = tx.clone();
    let sender = tokio::spawn(async move {
        tx2.send(2).await.expect("send 2"); // parks, then resumes after a recv
    });
    let first = rx.recv().await; // drains 1 -> frees the slot -> parked send(2) wakes
    let second = rx.recv().await; // drains the 2 the parked sender pushed
    sender.await.expect("sender task");
    drop(tx); // close the channel
    println!("  spawned tx.send(2).await PARKED, then resumed after rx.recv() freed a slot;");
    println!("    rx.recv() -> {:?}, then {:?}", first, second);

    check(
        "backpressure: the parked send(2) delivered AFTER a recv freed the slot",
        first == Some(1) && second == Some(2),
    );
}

// ── Section C: multi-producer — clone tx per task; collect and SORT ──────────

async fn section_c() {
    banner("C — multi-producer: clone tx per task; collect and SORT (determinism)");
    let (tx, mut rx) = mpsc::channel::<i32>(8);
    let values = [10, 20, 30];

    // Sender is Clone: tx.clone() hands each spawned task an independent producer
    // feeding the SAME single receiver. (Receiver is NOT Clone — single consumer.)
    let mut handles = Vec::new();
    for v in values {
        let tx = tx.clone();
        handles.push(tokio::spawn(async move {
            tx.send(v).await.expect("send value");
        }));
    }
    drop(tx); // drop the original so the channel closes once all clones finish
    println!(
        "  spawned {} tasks, each cloned tx and sent one of {:?};",
        values.len(),
        values
    );

    // wait for all senders to finish (so the channel then has no live Senders)
    for h in handles {
        h.await.expect("sender task");
    }

    // Reception order across producers is NONDETERMINISTIC (the runtime schedules
    // tasks). Collect into a Vec, SORT, then print from main. NEVER print inside
    // the spawned tasks. (HOW_TO_RESEARCH.md §4.2 rule 3.)
    let mut got: Vec<i32> = Vec::new();
    while let Some(v) = rx.recv().await {
        got.push(v);
    }
    got.sort_unstable();
    println!("  collected (sorted) -> {:?}", got);

    check(
        "3 cloned senders delivered exactly {10, 20, 30} as a set",
        got == vec![10, 20, 30],
    );
}

// ── Section D: oneshot — ONE value, ONE sender -> ONE receiver (a promise) ────

async fn section_d() {
    banner("D — oneshot: a complete-once promise (one sender -> one receiver)");
    // oneshot::channel() -> (Sender, Receiver). No capacity arg: it is always 1.
    // Neither handle is Clone. The Sender is consumed by `send` (it takes self by
    // value), so it can be used exactly once — sending twice is a compile error.
    let (tx, rx) = oneshot::channel::<&'static str>();
    println!("  let (tx, rx) = oneshot::channel::<&str>();   // capacity is always 1");

    // oneshot::Sender::send is NOT async — it completes immediately. It is usable
    // from sync code (or a Drop impl). Returns Err(v) only if the Receiver was
    // dropped first (the caller then keeps the value).
    tx.send("done").expect("oneshot send");
    println!("  tx.send(\"done\");   // NOT async; completes immediately");

    // Receiver is a Future: rx.await yields Result<T, RecvError>. Err means the
    // Sender was dropped WITHOUT sending.
    let got = rx.await;
    println!("  rx.await -> {:?}", got);

    check(
        "oneshot: send once + recv once yields the single value",
        got == Ok("done"),
    );

    // The "dropped without sending" branch: drop the Sender -> rx.await is Err.
    let (tx2, rx2) = oneshot::channel::<u32>();
    drop(tx2);
    let missed = rx2.await;
    println!("  drop(tx2) without sending; rx2.await -> {:?}", missed);
    check(
        "oneshot: a dropped Sender makes rx.await return Err (RecvError)",
        missed.is_err(),
    );
}

// ── Section E: broadcast — MULTI-receiver; each receiver gets a COPY ─────────

async fn section_e() {
    banner("E — broadcast: multi-consumer; each receiver gets a COPY");
    // broadcast::channel(n) -> (Sender, Receiver). The Sender is Clone; extra
    // Receivers come from tx.subscribe(). Requires T: Clone (each rx gets a copy).
    // n = max messages retained for slow receivers before the oldest is dropped.
    let (tx, mut rx1) = broadcast::channel::<i32>(16);
    let mut rx2 = tx.subscribe();
    println!("  let (tx, rx1) = broadcast::channel::<i32>(16);  let mut rx2 = tx.subscribe();");

    // send returns the NUMBER of active receivers that will receive this value.
    let reached = tx.send(10).expect("broadcast 10");
    println!(
        "  tx.send(10) -> Ok({})   (returned receiver count)",
        reached
    );
    tx.send(20).expect("broadcast 20");

    // Each receiver independently reads its OWN copy of every sent value.
    let a1 = rx1.recv().await.expect("rx1 a");
    let a2 = rx1.recv().await.expect("rx1 b");
    let b1 = rx2.recv().await.expect("rx2 a");
    let b2 = rx2.recv().await.expect("rx2 b");
    println!(
        "  rx1.recv() x2 -> [{}, {}]   rx2.recv() x2 -> [{}, {}]",
        a1, a2, b1, b2
    );

    check(
        "broadcast: rx1 received the full sequence [10, 20]",
        a1 == 10 && a2 == 20,
    );
    check(
        "broadcast: rx2 received a COPY of the SAME sequence [10, 20]",
        b1 == 10 && b2 == 20,
    );
    check(
        "broadcast::send returned the number of receivers (2)",
        reached == 2,
    );
}

// ── Section F: watch — a single value that changes; receivers see the LATEST ─

async fn section_f() {
    banner("F — watch: one latest value; receivers see only the most recent");
    // watch::channel(init) -> (Sender, Receiver). Created with an INITIAL value.
    // It only ever retains the LAST value sent — no history is kept.
    let (tx, mut rx) = watch::channel(0);
    println!("  let (tx, rx) = watch::channel(0);   // initial value 0 (considered SEEN)");

    // Send several updates in a row BEFORE awaiting. watch coalesces: only the
    // most recent (3) survives. Intermediate values 1 and 2 are never observable.
    tx.send(1).expect("watch 1");
    tx.send(2).expect("watch 2");
    tx.send(3).expect("watch 3");
    println!("  tx.send(1); tx.send(2); tx.send(3);   // only 3 (the latest) is retained");

    // changed().await resolves once an UNSEEN value exists, then marks it seen.
    // (The initial value is seen at creation, so changed() would not fire until a
    // subsequent send — which is exactly what happened above.)
    rx.changed().await.expect("watch changed");
    let latest = *rx.borrow();
    println!("  rx.changed().await; *rx.borrow() -> {}", latest);

    check(
        "watch: receiver sees only the LATEST value (3); 1 and 2 were coalesced away",
        latest == 3,
    );

    // borrow() reads the current value without an .await; borrow_and_update()
    // also marks it seen. has_changed() is the sync, non-marking probe.
    tx.send(7).expect("watch 7");
    let saw = rx.has_changed().expect("has_changed");
    println!(
        "  tx.send(7); rx.has_changed() -> {}   (sync probe; does NOT mark seen)",
        saw
    );
    check(
        "watch: has_changed() is true after a send the receiver has not marked seen",
        saw,
    );
}

#[tokio::main]
async fn main() {
    println!("tokio_channels.rs — Phase 7 bundle (async member).");
    println!("Every value below is computed by this file.\n");
    section_a().await;
    section_b().await;
    section_c().await;
    section_d().await;
    section_e().await;
    section_f().await;
    banner("DONE — all sections printed");
}
