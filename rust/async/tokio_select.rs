//! tokio_select.rs — Phase 7 bundle.
//!
//! GOAL (one line): show, by printing every value, that `tokio::select!` awaits
//! many futures on ONE task, returns when the FIRST becomes ready, DROPS
//! (cancels) the rest, and how `biased` ordering, the `else` branch,
//! cancellation, and the `loop { select! }` event-loop idiom behave — all in
//! DETERMINISTIC scenarios whose checks never assume which ready branch wins.
//!
//! This is the GROUND TRUTH for TOKIO_SELECT.md. Every value below is computed
//! by this file. Change it -> re-run -> re-paste. Never hand-compute.
//!
//! Run:
//!     just run tokio_select   (== cargo run --bin tokio_select)

use std::collections::BTreeSet;
use std::future::{pending, ready};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use tokio::sync::{mpsc, oneshot};

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

/// A guard whose `Drop` flips a shared flag — proving the LOSING branch of a
/// `select!` was dropped (cancelled) while suspended at an `.await`. `Arc` (not
/// `Cell`) because the future carrying it must be `Send` on the multi-thread
/// runtime; `AtomicBool` gives `&`-free mutation across threads. See Section E.
struct CancelGuard {
    cancelled: Arc<AtomicBool>,
}

impl Drop for CancelGuard {
    fn drop(&mut self) {
        self.cancelled.store(true, Ordering::SeqCst);
        println!("    (CancelGuard::drop fired — losing branch was CANCELLED)");
    }
}

// ── Section A: first-ready — when ONLY one branch is ready, select picks it ──

async fn section_a() {
    banner("A — first ready wins: only ONE branch ready -> deterministic pick");
    // `ready("A")` completes immediately; `pending()` NEVER completes. Because
    // exactly one branch can ever be ready, select! deterministically resolves
    // it. We MAY assert which one wins here (allowed: only one is ready).
    let winner = tokio::select! {
        v = ready("A") => v,
        _ = pending::<&str>() => "B",
    };
    println!(
        "  select!(ready(\"A\"), pending::<&str>()) -> winner = {:?}",
        winner
    );
    check(
        "with only A ready, select picks A every time",
        winner == "A",
    );
}

// ── Section B: BOTH ready — pick is pseudo-RANDOM; assert a SET, never which ─

async fn section_b() {
    banner("B — BOTH ready: pick is pseudo-RANDOM -> assert a SET, never which");
    // When BOTH branches are ready at once, tokio::select! pseudo-randomly picks
    // one to poll first (fairness against starvation). NEVER assert which one —
    // assert the SET of winners over many trials contains BOTH. The exact split
    // varies per run, so we deliberately do NOT print counts (they would break
    // byte-reproducibility of _output.txt); only the sorted set is printed.
    let mut winners: BTreeSet<&str> = BTreeSet::new();
    for _ in 0..1000 {
        let w = tokio::select! {
            v = ready("A") => v,
            v = ready("B") => v,
        };
        winners.insert(w);
    }
    let sorted: Vec<&str> = winners.iter().copied().collect();
    println!(
        "  over 1000 trials with both branches ready, the set of winners = {:?}",
        sorted
    );
    check(
        "both A and B appeared as winners (set len == 2)",
        winners.len() == 2,
    );
    check("A was a winner at least once", winners.contains("A"));
    check("B was a winner at least once", winners.contains("B"));
}

// ── Section C: biased — branches polled TOP-DOWN, FIRST ready always wins ───

async fn section_c() {
    banner("C — biased: branches polled TOP-DOWN -> FIRST ready always wins");
    // `biased;` overrides the random fairness: branches are checked in the
    // order written, top to bottom. With both ready, the FIRST listed ALWAYS
    // wins. This is deterministic, so we may assert the winner directly.
    // (Contrast B: WITHOUT `biased`, both would appear over 1000 trials.)
    let mut all_first = true;
    for _ in 0..1000 {
        let w = tokio::select! {
            biased;
            v = ready("first") => v,
            v = ready("second") => v,
        };
        all_first &= w == "first";
    }
    println!("  biased; select!(ready(\"first\"), ready(\"second\")) x1000");
    println!("  -> \"first\" won every time: {}", all_first);
    check(
        "biased: first-listed ready branch always wins (top-down order)",
        all_first,
    );
}

// ── Section D: else branch — runs when ALL branches are DISABLED ────────────

async fn section_d() {
    banner("D — else branch: runs when ALL branches are DISABLED");
    // A branch is DISABLED when (a) its `if` precondition is false, OR (b) its
    // pattern does NOT match the value the future resolved to. When ALL
    // branches are disabled, `else =>` runs. KEY EXPERT POINT: `else` does NOT
    // mean "no future is ready right now". If a branch is merely Pending (not
    // ready), select AWAITS it and `else` does NOT fire. `else` is about
    // disabled branches, not about readiness. (See pitfalls.)
    let (tx, rx) = oneshot::channel::<u32>();
    drop(tx); // close the channel WITHOUT sending -> rx resolves to Err
    let outcome = tokio::select! {
        // rx resolves to Err(RecvError); Ok(v) does NOT match -> branch disabled
        Ok(v) = rx => v,
        // all branches disabled -> else runs
        else => 999_u32,
    };
    println!("  oneshot closed without send: rx resolves to Err; Ok(v) never matches");
    println!("  -> select! else branch produced = {}", outcome);
    check(
        "else runs when every branch's pattern fails to match (closed channel)",
        outcome == 999,
    );
}

// ── Section E: cancellation — the LOSING branch is dropped mid-await ────────

async fn section_e() {
    banner("E — cancellation: the LOSING branch is dropped mid-await");
    // The winner is `ready("winner")` (immediately ready). The loser holds a
    // `CancelGuard` and suspends forever at `pending().await`. select! resolves
    // the winner, then DROPS the loser — running its `Drop`. That is how async
    // cancellation propagates: dropping a future mid-`.await` runs its drop glue.
    let cancelled = Arc::new(AtomicBool::new(false));
    let guard = CancelGuard {
        cancelled: cancelled.clone(),
    };
    let winner = tokio::select! {
        v = ready("winner") => v,
        _ = async move {
            let _g = guard; // guard lives across the await below
            pending::<()>().await; // never ready -> suspended HERE when dropped
        } => "loser",
    };
    println!("  winner = {:?}", winner);
    println!(
        "  cancelled flag after select = {}",
        cancelled.load(Ordering::SeqCst)
    );
    check(
        "the winning (ready) branch won deterministically",
        winner == "winner",
    );
    check(
        "the losing branch's guard was dropped -> cancellation propagated",
        cancelled.load(Ordering::SeqCst),
    );
}

// ── Section F: event loop — loop { select! { ... else => break } } ──────────

async fn section_f() {
    banner("F — event loop: loop { select! { ... else => break } }");
    // The canonical idiom: a loop whose body is a select! over event sources,
    // exiting via `else` when all sources are exhausted/closed. Deterministic
    // (NO real timers): we fill a channel, close it, and the loop drains it
    // then hits `else`. We also show the `if` precondition that disables a
    // branch once a resumed future has completed (prevents re-polling a finished
    // future, which would panic "resumed after completion").

    // F1: drain a channel via loop + select + else.
    let (tx, mut rx) = mpsc::channel::<u32>(8);
    for v in [1_u32, 2, 3] {
        tx.try_send(v).unwrap();
    }
    drop(tx); // close -> after the 3 values, recv() returns None
    let mut received: Vec<u32> = Vec::new();
    loop {
        tokio::select! {
            Some(v) = rx.recv() => received.push(v),
            // recv() -> None does NOT match Some(v) -> branch disabled -> else
            else => break,
        }
    }
    received.sort();
    println!("  loop drained the channel -> received = {:?}", received);
    check(
        "loop+select drains a channel then exits via else",
        received == vec![1, 2, 3],
    );

    // F2: event loop with an `if` precondition guarding a RESUMED future, so a
    // COMPLETED future is never re-polled. The FINAL state is deterministic even
    // though the per-iteration winner (work vs channel) is pseudo-random when
    // both are ready: the work runs exactly once, the channel drains fully.
    let (tx2, mut rx2) = mpsc::channel::<u32>(8);
    for v in [10_u32, 20, 30] {
        tx2.try_send(v).unwrap();
    }
    drop(tx2); // close
    let work = async { 42_u32 };
    tokio::pin!(work);
    let mut work_done = false;
    let mut from_work: Option<u32> = None;
    let mut from_chan: Vec<u32> = Vec::new();
    loop {
        tokio::select! {
            // disabled once work has completed: re-polling a finished future
            // across loop iterations would panic "resumed after completion".
            v = &mut work, if !work_done => {
                work_done = true;
                from_work = Some(v);
            }
            Some(v) = rx2.recv() => from_chan.push(v),
            else => break,
        }
    }
    from_chan.sort();
    println!(
        "  event loop: from_work = {:?}, from_chan = {:?}",
        from_work, from_chan
    );
    check(
        "event loop runs the resumed future exactly once",
        work_done && from_work == Some(42),
    );
    check(
        "event loop drains the rest of the channel (sorted)",
        from_chan == vec![10, 20, 30],
    );
}

#[tokio::main]
async fn main() {
    println!("tokio_select.rs — Phase 7 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a().await;
    section_b().await;
    section_c().await;
    section_d().await;
    section_e().await;
    section_f().await;
    banner("DONE — all sections printed");
}
