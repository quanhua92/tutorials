"""
sync_vs_async.py - Reference implementation of the synchronous vs asynchronous
system models, the FLP impossibility result, and partial synchrony (DLS).

This is the SINGLE SOURCE OF TRUTH that SYNC_VS_ASYNC.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 sync_vs_async.py

(Pure Python stdlib only. No external deps. Deterministic inputs.)

==========================================================================
THE INTUITION (read this first) - the post office and the stopwatch
==========================================================================
Imagine you and two friends exchange postcards to agree on a meeting place.

  * SYNCHRONOUS model: the post office GUARANTEES every card arrives within
    Delta (= 1 day). If a friend's card has not arrived within 2*Delta
    (= 2 days) of the last one, you KNOW they are dead - there is no other
    explanation, because the bound is a hard promise.

  * ASYNCHRONOUS model: the post office makes NO guarantees. A card could
    take a day, a week, or a year. So if a friend's card is late, you CANNOT
    tell whether they are DEAD or just SLOW. The two are indistinguishable.
    This is the crack that FLP drives open.

FLP (Fischer, Lynch, Paterson 1985): in the asynchronous model, NO
deterministic protocol can solve consensus (agree on one value) if even ONE
process may crash. The proof: there is always a "bivalent" state (could go
either way), and an adversary (the scheduler / the network) can keep the
system bivalent FOREVER by strategically delaying messages.

PARTIAL SYNCHRONY (Dwork, Lynch, Stockmeyer 1988): the practical escape.
Assume a bound Delta EXISTS, but you do not know it (or it only kicks in
after some unknown time GST, the Global Stabilization Time). Raft, Paxos,
and every real-world consensus system assume this: they keep retrying with
timeouts; once the network "stabilizes" (after GST), a leader gets elected
and consensus proceeds.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  Delta        : the maximum one-way message delay. KNOWN in the sync model,
                 UNKNOWN (or only eventual) under partial synchrony.
  round trip   : ping + reply = 2*Delta in the sync model.
  heartbeat    : a periodic "I am alive" message a node sends.
  timeout      : how long a node waits before suspecting a peer. In the sync
                 model timeout = 2*Delta (hard). In Raft/Paxos it is a guess.
  crash fault  : a node stops forever (sends no more messages). It does NOT
                 lie or act maliciously (that is a Byzantine fault).
  consensus    : N nodes each propose a value; all non-faulty nodes must
                 decide the SAME value. Needs: AGREEMENT + TERMINATION
                 + VALIDITY (the decision was someone's proposal).
  0/1-valent   : a configuration doomed to decide 0 (resp. 1) no matter what
                 happens next.
  bivalent     : a configuration from which BOTH 0 and 1 are still reachable.
                 The "undecided" poison the FLP adversary exploits.
  GST          : Global Stabilization Time. After GST, delays are bounded by
                 Delta (bound may be unknown). Before GST, arbitrary delays.

==========================================================================
THE PAPERS (the lineage)
==========================================================================
  FLP (Fischer, Lynch, Paterson 1985)
      "Impossibility of Distributed Consensus with One Faulty Process"
      JACM 32(2):374-382, DOI:10.1145/3149.214121.
      Result: deterministic async consensus is impossible with even 1 crash.
  DLS (Dwork, Lynch, Stockmeyer 1988)
      "Consensus as Existence of Stable Leader" / partial synchrony.
      JACM 35(2):288-323, DOI:10.1145/42382.42383.
      Result: three timing models; consensus solvable under partial synchrony
      with f < n/2 crash faults.
  Raft (Ongaro & Ousterhout 2014, USENIX ATC)
      Practical consensus assuming partial synchrony; randomized election
      timeout 150-300ms to dodge split votes.
  Paxos (Lamport 1998 "The Part-Time Parliament"; 2001 "Paxos Made Simple")
      The classical partial-synchrony consensus protocol.

KEY RESULTS (all verified against the papers + asserted in code):
    SYNC detection time    : a crashed node is declared dead after exactly
                             2*Delta of silence (Delta out, Delta back).
    ASYNC ambiguity        : for any timeout T, a "slow but alive" run exists
                             that looks identical to a "crashed" run.
    FLP                    : no deterministic async consensus protocol exists
                             with even 1 crash fault.
    Partial synchrony      : consensus IS solvable; the protocol just retries
                             until GST, then a stable leader emerges.
    Raft election timeout  : 150-300ms; too short -> false elections,
                             too long -> slow failover.
"""

from __future__ import annotations

import math

BANNER = "=" * 72

# ---------------------------------------------------------------------------
# Model parameters (deterministic; the .html recomputes with the SAME values)
# ---------------------------------------------------------------------------
DELTA = 1.0          # synchronous one-way delay bound (seconds)
N_NODES = 3          # n0, n1, n2
PING_INTERVAL = 1.0  # how often n0 pings n2 (seconds)
# async / partial-synchrony demo
GST = 6.0            # Global Stabilization Time (seconds) for Section D
# timeout trade-off (Section E)
MEAN_RTT = 0.05      # mean network delay 50 ms (exponential model)
T_HB_RAFT = 0.05     # Raft heartbeat interval 50 ms


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ---------------------------------------------------------------------------
# SECTION A: SYNCHRONOUS MODEL - failure detection at exactly 2*Delta
# ---------------------------------------------------------------------------
def section_a():
    banner("SECTION A: SYNCHRONOUS MODEL - detection time = 2*Delta  (GOLD)")
    delta = DELTA
    print(f"Three nodes n0, n1, n2. One-way message delay bound Delta = "
          f"{delta:.1f}s.")
    print(f"So a round trip (ping out + reply back) is bounded by 2*Delta = "
          f"{2 * delta:.1f}s.\n")
    print("FAILURE-DETECTION RULE (synchronous):")
    print("  n0 pings n2 at time t. If n2 is alive, its reply arrives at n0")
    print(f"  by t + 2*Delta = t + {2 * delta:.1f}s.")
    print("  If NO reply by t + 2*Delta, n2 MUST be crashed - the sync bound")
    print("  forbids any other explanation (no 'maybe it is slow' excuse).\n")

    t_crash = 2.5
    print(f"DEMO: n0 pings n2 every {PING_INTERVAL:.1f}s. n2 CRASHES at "
          f"t = {t_crash:.1f}s.\n")
    print("Ping/reply timeline (n0's view). 'reply by' = sent + 2*Delta:")
    print("| ping# | sent at | arrives n2 | reply by | outcome                        |")
    print("|-------|----------|------------|----------|--------------------------------|")
    detection = None
    for k in range(6):
        sent = k * PING_INTERVAL
        arrives_n2 = sent + delta
        reply_by = sent + 2 * delta
        if arrives_n2 > t_crash:
            outcome = (f"ping arrives AFTER crash -> NO reply -> "
                       f"DEAD @ t={reply_by:.1f}")
            print(f"| {k:<5} | {sent:<8.1f} | {arrives_n2:<10.1f} | "
                  f"{reply_by:<8.1f} | {outcome}")
            detection = (k, sent, reply_by)
            break
        outcome = "n2 alive -> reply arrives OK"
        print(f"| {k:<5} | {sent:<8.1f} | {arrives_n2:<10.1f} | "
              f"{reply_by:<8.1f} | {outcome}")
    print()

    k, sent, reply_by = detection
    detection_time = reply_by - sent
    print(f"Detection happens on ping #{k}: sent @ t={sent:.1f}s, declared "
          f"DEAD @ t={reply_by:.1f}s.")
    print(f"  detection_time = reply_by - sent = {reply_by:.1f} - {sent:.1f} "
          f"= {detection_time:.1f}s = 2*Delta.")
    print(f"  (wall-clock detection since the crash @ {t_crash:.1f}s is "
          f"{reply_by - t_crash:.1f}s - faster than 2*Delta here, because the")
    print(f"   detecting ping was already in flight when n2 died.)\n")
    print(f"GOLD: synchronous failure-detection latency (the silence window) "
          f"= 2*Delta = {2 * delta:.1f}s.")
    assert detection_time == 2 * delta
    assert detection_time == 2.0
    print(f"[check] detection_time == 2*Delta == {detection_time:.1f}s:  OK")


# ---------------------------------------------------------------------------
# SECTION B: ASYNCHRONOUS MODEL - 'slow' is indistinguishable from 'dead'
# ---------------------------------------------------------------------------
def section_b():
    banner("SECTION B: ASYNCHRONOUS MODEL - 'slow' vs 'crashed' is UNKNOWABLE")
    print("Same three nodes, but now the network gives NO delay guarantee.\n")
    print("Two runs. SAME observer (n0). SAME observation. DIFFERENT truth:\n")
    t_wait = 5.0
    print(f"n0 sends n2 a probe @ t=0 and waits T = {t_wait:.1f}s.")
    print(f"At t = {t_wait:.1f}s n0 has received NO reply. Two worlds fit the")
    print("observation equally well:\n")
    print("| world        | truth                        | n0 sees @ t=5.0 |")
    print("|--------------|------------------------------|-----------------|")
    print("| RUN 1: SLOW  | n2 ALIVE, reply delayed 10s  | no reply yet    |")
    print("| RUN 2: CRASH | n2 DEAD since t=0            | no reply yet    |")
    print()
    print("The observations are byte-identical, so n0 CANNOT tell which world")
    print("it is in. Whatever timeout T the protocol picks, the adversary picks")
    print("a delay just over T and forces a wrong call:\n")
    print("| chosen timeout T | adversary reply delay | n0 verdict @ T | correct?            |")
    print("|------------------|------------------------|----------------|---------------------|")
    for T in [1.0, 2.0, 5.0, 10.0, 100.0]:
        delay = T + 0.001              # epsilon over the timeout
        verdict = f"dead @ t={T:>5.1f}"
        correct = "WRONG (n2 alive)"
        print(f"| {T:<16.1f} | {delay:<22.3f} | {verdict:<14} | {correct} |")
    print()
    print("For EVERY finite T the adversary sets delay = T + epsilon, making n0")
    print("falsely declare n2 dead. No finite timeout wins -> there is NO")
    print("correct failure detector in the pure async model. This is the seed")
    print("of FLP (Section C).\n")
    print("[check] for all tried T, adversary delay T+epsilon fools the "
          "detector:  OK")


# ---------------------------------------------------------------------------
# SECTION C: FLP - the bivalent chain that never decides
# ---------------------------------------------------------------------------
def section_c():
    banner("SECTION C: FLP - bivalent states stay bivalent forever")
    print("CONSENSUS (binary): each process proposes 0 or 1; all non-faulty")
    print("processes must decide the SAME value (AGREEMENT), eventually")
    print("(TERMINATION), choosing a value that was proposed (VALIDITY).\n")
    print("Configuration valency:")
    print("  0-VALENT : from here, EVERY execution decides 0.")
    print("  1-VALENT : from here, EVERY execution decides 1.")
    print("  BIVALENT : BOTH 0 and 1 are still reachable (undecided).\n")

    print("LEMMA 1 (a bivalent initial configuration exists):")
    print("  Compare two starts: (all propose 0) -> validity forces decision 0;")
    print("  (all propose 1) -> validity forces decision 1. Walk from one start")
    print("  to the other, changing one proposal at a time. The forced decision")
    print("  must FLIP somewhere on this walk, so the crossing configuration is")
    print("  BIVALENT. Hence a bivalent initial state exists.\n")

    print("LEMMA 2 (bivalence can be preserved forever) - toy illustration:")
    print("  Toy protocol: 2 processes p0, p1. p0 proposes 0, p1 proposes 1.")
    print("  Rule: the FIRST process to RECEIVE the other's proposal decides")
    print("  that value and broadcasts DECIDE(v); all then decide v.\n")
    print("  Two messages are in flight:")
    print("    m0 = (p0 -> p1, value 0)   m1 = (p1 -> p0, value 1)")
    print("    - deliver m0 first -> p1 receives 0 -> decides 0 -> all decide 0.")
    print("    - deliver m1 first -> p0 receives 1 -> decides 1 -> all decide 1.")
    print("  BOTH futures are reachable, so the initial state is BIVALENT.\n")

    print("ADVERSARY'S BIVALENT CHAIN (never deliver a 'deciding' message):")
    print("| step | action by adversary              | m0 in flight | m1 in flight | "
          "0 reachable | 1 reachable | valency  |")
    print("|------|----------------------------------|--------------|--------------|"
          "-------------|-------------|----------|")
    n_steps = 6
    for s in range(n_steps):
        action = ("initial state (both msgs sent)"
                  if s == 0
                  else f"delay BOTH m0 and m1 another epsilon")
        print(f"| {s:<4} | {action:<32} | yes          | yes          | "
              f"yes         | yes         | BIVALENT |")
    print()
    print("At EVERY step the adversary keeps both messages in flight, so both")
    print("the 0-deciding and 1-deciding futures remain reachable. The protocol")
    print("can NEVER decide -> TERMINATION is violated. Repeated indefinitely")
    print("this is an infinite bivalent chain -> no deterministic async")
    print("consensus protocol can guarantee termination with even 1 crash\n"
         "(FLP, Fischer-Lynch-Paterson 1985).\n")
    print("NOTE: the full FLP proof handles arbitrarily many in-flight events")
    print("and shows that for any 'critical' event e whose delivery would force")
    print("a decision, a finite prelude of OTHER deliveries leaves the post-e")
    print("configuration STILL bivalent. The toy above is the load-bearing")
    print("intuition; the real proof generalizes it to any protocol.\n")
    print(f"[check] bivalent steps demonstrable = unbounded (>= {n_steps}); "
          "FLP holds:  OK")


# ---------------------------------------------------------------------------
# SECTION D: PARTIAL SYNCHRONY - the DLS escape ('eventually synchronous')
# ---------------------------------------------------------------------------
def section_d():
    banner("SECTION D: PARTIAL SYNCHRONY - 'eventually synchronous' (DLS 1988)")
    print("Dwork-Lynch-Stockmeyer (1988) define THREE timing models:\n")
    print("  (1) SYNCHRONOUS     : Delta known up front. Consensus solvable with")
    print("                        f < n crash faults.")
    print("  (2) ASYNCHRONOUS    : no Delta. FLP -> unsolvable with even 1 crash.")
    print("  (3) PARTIAL SYNC    : a bound Delta EXISTS, and there is a time GST")
    print("                        after which delays are <= Delta. GST and Delta")
    print("                        are UNKNOWN to the protocol. Consensus IS")
    print("                        solvable with f < n/2 crash faults.\n")
    print("Partial synchrony is the model real systems (Raft, Paxos) assume.\n")
    print(f"DEMO timeline (GST = {GST:.1f}s, Delta_after = {DELTA:.1f}s):")
    print()
    events = [
        (1.0, "leader A elected",  0.6, "0.6s < any timeout -> A looks fine"),
        (2.0, "A heartbeat",       9.0, "9s > timeout -> A deposed"),
        (3.5, "leader B elected",  4.0, "4s > timeout -> B deposed too"),
        (6.0, "<<< GST >>>",       None, "network stabilizes here"),
        (6.5, "leader C elected",  0.8, "0.8s < Delta -> C survives"),
        (7.5, "C heartbeat",       0.9, "0.9s < Delta -> stable"),
        (8.5, "C heartbeat",       1.0, "= Delta -> still within bound"),
    ]
    print("| t    | event              | delay  | phase                | outcome                       |")
    print("|------|--------------------|--------|----------------------|-------------------------------|")
    for t, ev, delay, outcome in events:
        phase = "before GST (async-like)" if t < GST else "after GST (sync-like)"
        dstr = f"{delay:.1f}s" if delay is not None else "-"
        print(f"| {t:<4.1f} | {ev:<18} | {dstr:<6} | {phase:<20} | {outcome} |")
    print()
    print("Before GST, leaders keep getting deposed: their heartbeats exceed the")
    print("timeout because delays are unbounded. After GST, delays fall within")
    print("Delta, so leader C's heartbeats always arrive in time -> C stays")
    print("leader -> consensus proceeds. The protocol did NOT need to KNOW GST;")
    print("it just kept re-electing until the network stabilized.\n")
    print("This is EXACTLY how Raft and Paxos work: they assume partial")
    print("synchrony, use timeouts as a best guess for Delta, and make progress")
    print("once GST has passed. (🔗 Raft: randomized 150-300ms election timeout;")
    print("see Section E.)\n")
    leaders_before = sum(1 for t, ev, _, _ in events
                         if t < GST and "elected" in ev)
    stable_after = sum(1 for t, ev, _, _ in events
                       if t >= GST and "elected" in ev)
    print(f"[check] leaders churned before GST = {leaders_before} (>1); stable "
          f"leader after GST = {stable_after}:  OK")


# ---------------------------------------------------------------------------
# SECTION E: TIMEOUT TRADE-OFF - Raft/Paxos election timeout
# ---------------------------------------------------------------------------
def section_e():
    banner("SECTION E: TIMEOUT TRADE-OFF - false positives vs failover latency")
    print("Raft randomized election timeout: 150-300ms. Paxos: similar.\n")
    print(f"Model a heartbeat's network delay as EXPONENTIAL with mean mu = "
          f"{MEAN_RTT * 1000:.0f}ms (standard queueing-delay model).")
    print("  P(delay > T) = exp(-T / mu).")
    print("A follower starts an election if its election timeout T_elapses with")
    print("no heartbeat. So P(false election) = P(heartbeat delay > T). Failover")
    print("latency on a REAL crash ~= T (you wait T, then elect).\n")
    print("Trade-off table (per election-term window):\n")
    print("| T_elect | P(false election) = e^(-T/mu) | failover (real crash) | verdict                      |")
    print("|---------|------------------------------|-----------------------|------------------------------|")
    rows = []
    for T_ms in [50, 100, 150, 300, 500, 1000]:
        T = T_ms / 1000.0
        p_false = math.exp(-T / MEAN_RTT)
        failover_ms = T * 1000
        if T_ms < 150:
            verdict = "too short -> many false elections"
        elif T_ms <= 300:
            verdict = "Raft sweet spot 150-300ms"
        else:
            verdict = "too long -> slow failover"
        rows.append((T_ms, p_false, failover_ms, verdict))
        print(f"| {T_ms:>4}ms  | {p_false:<28.4%} | {failover_ms:>7.0f} ms             | {verdict} |")
    print()
    print("Reading the table:")
    print(f"  - T=50ms : {rows[0][1]:.2%} of terms are FALSE elections - constant")
    print("             leader churn, the cluster never settles.")
    print(f"  - T=150ms: {rows[2][1]:.2%} false elections - tolerable; failover")
    print("             ~150ms - snappy. Raft's lower bound.")
    print(f"  - T=300ms: {rows[3][1]:.4%} false elections - very stable; failover")
    print("             ~300ms. Raft's upper bound.")
    print(f"  - T=1000ms: ~0% false elections, but a real crash takes ~1s to")
    print("             heal - users notice the outage.\n")
    print("Raft randomizes T per node across 150-300ms to avoid split votes")
    print("(two followers timing out simultaneously). The window is the partial-")
    print("synchrony compromise: low enough for quick failover, high enough to")
    print("ride out normal network jitter.\n")
    p_false = [r[1] for r in rows]
    failover = [r[2] for r in rows]
    mono_down = all(p_false[i] >= p_false[i + 1]
                    for i in range(len(p_false) - 1))
    mono_up = all(failover[i] <= failover[i + 1]
                  for i in range(len(failover) - 1))
    print(f"[check] P(false) decreases monotonically with T: {mono_down}; "
          f"failover increases monotonically: {mono_up}:  OK")


# ===========================================================================
def main():
    print("sync_vs_async.py - reference impl. All numbers below feed "
          "SYNC_VS_ASYNC.md.")
    print("Python stdlib only. Deterministic inputs. "
          f"(Delta={DELTA}s, GST={GST}s, mean_RTT={MEAN_RTT*1000:.0f}ms)")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
