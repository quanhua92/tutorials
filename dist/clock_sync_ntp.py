"""
clock_sync_ntp.py - Reference implementation of PHYSICAL clock synchronization:
Cristian's algorithm (client/server, RTT/2 offset), the Berkeley algorithm
(master averages, tells slaves how to adjust), NTP (hierarchical strata +
Marzullo's intersection algorithm for outlier rejection), quartz-crystal clock
drift, and why you can NEVER fully trust a wall clock (leap seconds, NTP step
adjustments that can jump BACKWARD, VM migration, and Google's smear).

This is the single source of truth that CLOCK_SYNC_NTP.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 clock_sync_ntp.py

=========================================================================
THE INTUITION (read this first) - why clocks lie, and what we do about it
=========================================================================
Every quartz crystal in every machine oscillates at a slightly different
frequency. Two "perfectly synchronized" clocks will DRIFT apart at roughly
1 part per million (rho ~ 1e-6), so after just 12 days they can disagree by
~1 second. There is no global "now"; each machine only has its own private
clock, and that private clock is always wrong by some unknown amount.

We CANNOT make clocks perfect. Instead we MEASURE how wrong they are and
CORRECT them. The four classical answers, in order of how much they assume:

  * Cristian (1989): assume ONE trustworthy server. Client asks "what time
                      is it?", server answers. Half the round-trip is your
                      error bound. Simple, but the server is a single point.
  * Berkeley  (1989): NO machine is trusted. A master polls everyone, AVERAGES
                      their clocks, and tells each machine how to nudge itself.
                      Good for a LAN where nobody is the "truth".
  * NTP       (1991): build a GLOBAL hierarchy (strata). Stratum 0 = atomic
                      clocks/GPS, stratum 1 = directly wired to them, stratum 2
                      = from stratum 1, and so on. Each layer adds a little error.
  * Marzullo  (1984): given many servers each returning (offset, +/- error),
                      find the BIGGEST clique of overlapping intervals and
                      treat the rest as liars/outliers. This is how NTP rejects
                      a broken timeserver without ever trusting any single one.

But even with all of this, wall clocks are STILL unsafe: a leap second makes
23:59:60 happen, NTP can STEP a clock backward, and a VM live-migration freezes
the guest clock for seconds. Timestamps are approximations, never facts.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  clock skew     : the FIXED difference between two clocks at one instant.
  clock drift    : the RATE at which that difference GROWS over time (rho).
  offset  (theta): how much to ADD to my clock to match the reference.
                   theta = reference_time - my_time. Positive => I am behind.
  RTT            : round-trip time = T2 - T0 (request sent -> reply received).
  T0, T1, T2     : client sends at T0; server stamps its time T1; client
                   receives at T2. (T1 rides inside the reply payload.)
  accuracy bound : |true offset - estimated offset| <= (T2 - T0)/2 = RTT/2.
                   Cristian's guarantee. Provable from symmetry assumptions.
  stratum        : distance (in hops) from a reference clock. 0 = the atomic
                   clock itself; 16 = "unsynchronized".
  rho            : drift rate of a quartz crystal ~ 1e-6 (1 ppm). After time t
                   a single clock can be off by rho*t; two clocks by up to 2*rho*t.

=========================================================================
THE PAPERS (all formulas below verified against these)
=========================================================================
  Cristian  (1989) "Probabilistic clock synchronization", Distributed Computing.
  Gusella & Zatti (1989) "The accuracy of the clock synchronization achieved by
                   TEMPO in Berkeley UNIX 4.3BSD", IEEE Trans. SE.  -> Berkeley.
  Mills    (1991) "Internet time synchronization: the network time protocol"
                   IEEE Trans. Comms.   (NTP; later RFC 5905).
  Marzullo  (1984) "Maintaining the time in a distributed system", Stanford.
                   -> the interval-intersection algorithm NTP uses internally.

KEY FORMULAS (all asserted in code below):
    Cristian offset :  theta = T1 - (T0 + T2)/2
    Cristian bound  :  |true_offset - theta| <= (T2 - T0)/2          ( = RTT/2 )
    Drift bound     :  |clock_a(t) - clock_b(t)| <= 2 * rho * t
    rho (quartz)    :  ~1e-6   ->  rho * 86400 = 0.0864 s/day/clock
    Berkeley adjust :  adj_i = average(all_clocks) - clock_i
    Marzullo        :  pick the offset contained in the MOST (offset+/-error)
                       intervals; reject the rest as outliers.
    Google smear    :  1 leap-second spread over 24h = 1/86400 s/s ~ 11.57 ppm.
"""

from __future__ import annotations

BANNER = "=" * 72

# Quartz-crystal drift rate. The textbook value is ~1e-6 (1 part per million).
# Verified: rho * (12 days in seconds) = 1e-6 * 1036800 = 1.0368 s ~ "1 s / 12 d".
RHO = 1e-6


# ============================================================================
# 1. REFERENCE IMPLEMENTATIONS  (this is the code CLOCK_SYNC_NTP.md walks through)
# ============================================================================

def cristian(T0: float, T1: float, T2: float) -> tuple[float, float]:
    """Cristian's algorithm (1989).

    Client sends a request at client-time T0. The server stamps the reply with
    its OWN clock value T1 (the only piece of "truth" that crosses the wire).
    Client receives the reply at client-time T2.

        estimated offset  theta = T1 - (T0 + T2)/2
        accuracy bound    = (T2 - T0)/2 = RTT/2

    theta is how much to ADD to the client clock to match the server: positive
    => client is behind the server. The true offset is guaranteed to lie within
    [theta - RTT/2, theta + RTT/2] under the symmetric-network assumption.
    """
    theta = T1 - (T0 + T2) / 2.0
    accuracy = (T2 - T0) / 2.0
    return theta, accuracy


def berkeley_adjustments(clocks: list[float]) -> list[float]:
    """Berkeley algorithm (Gusella & Zatti 1989).

    `clocks[0]` is the master; the rest are slaves. The master AVERAGES all the
    clocks (including its own, the classic convention), then tells each machine
    the adjustment it must apply:

        average = mean(clocks)
        adj_i   = average - clock_i      (positive => speed up, negative => slow)

    Everyone converges to `average`. No machine is trusted as the "truth"; the
    group agree to disagree toward the middle. (Faulty/outlier slaves must be
    filtered first or the average gets poisoned - see Marzullo in section_c.)
    """
    average = sum(clocks) / len(clocks)
    return [average - c for c in clocks]


def marzullo(offsets: list[float], errors: list[float]) -> tuple[list[int], tuple[float, float]]:
    """Marzullo's interval-intersection algorithm (1984).

    Each server i claims the true offset is `offsets[i]` within +/- `errors[i]`,
    i.e. it offers the interval [offsets[i]-errors[i], offsets[i]+errors[i]].
    Marzullo returns the set of servers whose intervals ALL overlap (the largest
    such clique) and the region of agreement. Servers outside that clique are
    treated as faulty/outliers and rejected.

    Implementation: a sweep over interval endpoints. At a START we gain a clock,
    at an END we lose one. The widest-attended region is the max-overlap span;
    the clocks present there are the trusted clique.
    """
    events = []
    for i, (off, err) in enumerate(zip(offsets, errors)):
        lo, hi = off - err, off + err
        events.append((lo, +1, i))   # +1: a clock's interval begins
        events.append((hi, -1, i))   # -1: a clock's interval ends
    # Sort by coordinate; at a tie, process STARTS (+1) before ENDS (-1) so that
    # two intervals that merely touch at a point are still counted as overlapping.
    events.sort(key=lambda e: (e[0], -e[1]))

    active = set()
    best_count = -1
    best_start = best_end = None
    best_set: set[int] = set()
    prev_coord = None
    for coord, delta, i in events:
        # If a region has been open with the current `active` set, its span is
        # [prev_coord, coord]. Record it if it beats the running best.
        if prev_coord is not None and active:
            if len(active) > best_count:
                best_count = len(active)
                best_start, best_end = prev_coord, coord
                best_set = set(active)
        if delta == +1:
            active.add(i)
        else:
            active.discard(i)
        prev_coord = coord
    return sorted(best_set), (best_start, best_end)


def drift_bound(t_seconds: float, rho: float = RHO) -> float:
    """Worst-case divergence between two clocks after `t_seconds`.

    Each clock can drift up to +/-rho*t from real time, so in the worst case
    they drift in OPPOSITE directions: divergence <= 2*rho*t. (For a single
    clock vs true time the bound is rho*t.)
    """
    return 2.0 * rho * t_seconds


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_dur(s: float) -> str:
    """Human-readable duration from seconds."""
    if s < 1e-3:
        return f"{s * 1e6:.2f} us"
    if s < 1.0:
        return f"{s * 1e3:.2f} ms"
    if s < 60:
        return f"{s:.3f} s"
    if s < 3600:
        return f"{s / 60:.2f} min"
    if s < 86400:
        return f"{s / 3600:.2f} h"
    if s < 2.628e6:
        return f"{s / 86400:.2f} days"
    return f"{s / 3.156e7:.2f} years"


# ============================================================================
# SECTION A: Cristian's algorithm
# ============================================================================

def section_a():
    banner("SECTION A: Cristian's algorithm  (client/server, RTT/2 offset)")
    print("Setup: client asks a trusted server 'what time is it?'.")
    print("  T0 : client sends the request   (read on the CLIENT clock)")
    print("  T1 : server stamps the reply    (read on the SERVER clock)")
    print("  T2 : client receives the reply  (read on the CLIENT clock)")
    print("  RTT = T2 - T0  (measured entirely by the client).\n")
    print("Formulas:")
    print("  offset  theta    = T1 - (T0 + T2)/2     (ADD to client to match server)")
    print("  accuracy bound   = (T2 - T0)/2 = RTT/2  (|true - theta| <= this)\n")

    # ----- Worked example built from GROUND TRUTH so we can verify the math -----
    # Let real time be t. Client clock C(t) = t. Server clock S(t) = t + 12.
    # So the TRUE offset (server - client) = 12.0.
    true_offset = 12.0
    print(f"Ground truth for the demo: client clock == real time; server is "
          f"{true_offset:+.1f} s ahead. TRUE offset = {true_offset:.1f}.\n")

    # Case 1: SYMMETRIC network. d_out == d_in. Cristian recovers the truth EXACTLY.
    d_out, d_in = 4.0, 4.0
    T0 = 0.0
    T2 = T0 + d_out + d_in                      # client receives
    T1 = T0 + d_out + true_offset               # server stamps its own clock
    theta1, acc1 = cristian(T0, T1, T2)
    print(f"Case 1 (SYMMETRIC network, d_out={d_out}, d_in={d_in}):")
    print(f"  T0={T0}, T1={T1}, T2={T2}, RTT={T2 - T0}")
    print(f"  theta = T1 - (T0+T2)/2 = {T1} - {(T0 + T2) / 2} = {theta1:.4f}")
    print(f"  accuracy bound = RTT/2 = {acc1:.4f}")
    print(f"  error = |true - theta| = {abs(true_offset - theta1):.6f}  "
          f"(ZERO -> symmetric delay cancels out exactly)\n")

    # Case 2: ASYMMETRIC network. The estimate is biased by (d_in - d_out)/2,
    # but the true offset is still guaranteed inside [theta - RTT/2, theta + RTT/2].
    d_out, d_in = 3.0, 5.0
    T0 = 0.0
    T2 = T0 + d_out + d_in
    T1 = T0 + d_out + true_offset
    theta2, acc2 = cristian(T0, T1, T2)
    err2 = abs(true_offset - theta2)
    bias = (d_in - d_out) / 2.0
    print(f"Case 2 (ASYMMETRIC network, d_out={d_out}, d_in={d_in}):")
    print(f"  T0={T0}, T1={T1}, T2={T2}, RTT={T2 - T0}")
    print(f"  theta = T1 - (T0+T2)/2 = {T1} - {(T0 + T2) / 2} = {theta2:.4f}")
    print(f"  accuracy bound = RTT/2 = {acc2:.4f}")
    print(f"  error = |true - theta| = {err2:.4f}   "
          f"== (d_in - d_out)/2 = {bias:.4f}  (the asymmetry bias)")
    lo, hi = theta2 - acc2, theta2 + acc2
    print(f"  true offset {true_offset} in [theta-RTT/2, theta+RTT/2] = "
          f"[{lo:.4f}, {hi:.4f}]?  {lo <= true_offset <= hi}")
    print("\nThe punchline: Cristian's error is at most RTT/2. A 200 ms ping")
    print("=> you only ever know the time to +/- 100 ms. Want milliseconds of")
    print("accuracy? You need a sub-2-millisecond round trip, i.e. a LAN.\n")

    # GOLD values (pinned for clock_sync_ntp.html). The .html must reproduce these.
    print(f"GOLD (pinned for clock_sync_ntp.html) - Case 2 scenario:")
    print(f"  T0=0, d_out=3, d_in=5, server_ahead=12 -> T1=15, T2=8")
    print(f"  theta  = {theta2}     (must be exactly 11.0)")
    print(f"  accuracy = {acc2}   (must be exactly 4.0)")
    print(f"  true_offset = {true_offset} , error = {err2}  (== (d_in-d_out)/2)")
    assert theta2 == 11.0, "Cristian gold offset must be 11.0"
    assert acc2 == 4.0, "Cristian gold accuracy must be 4.0"
    assert err2 == 1.0, "Cristian gold error must be 1.0"
    assert lo <= true_offset <= hi, "accuracy bound must hold"
    print("[check] Cristian GOLD: theta=11.0, accuracy=4.0, bound holds:  OK")


# ============================================================================
# SECTION B: Berkeley algorithm
# ============================================================================

def section_b():
    banner("SECTION B: Berkeley algorithm  (master averages, tells slaves to adjust)")
    print("No machine is the 'truth'. A master polls every clock, AVERAGES them,")
    print("and tells each machine how to nudge itself so they all meet in the middle.\n")
    print("  average = mean(all clocks, master included)")
    print("  adj_i   = average - clock_i    (+ => speed up, - => slow down)\n")

    # Deterministic clocks: master at the epoch (0), three slaves all fast by
    # different amounts. Clean numbers so the averaging is obvious.
    labels = ["master", "slave A", "slave B", "slave C"]
    clocks = [0.0, 10.0, 20.0, 30.0]
    average = sum(clocks) / len(clocks)
    adjustments = berkeley_adjustments(clocks)

    print("| machine  | clock (s vs master) | average | adjustment = avg - clock |")
    print("|----------|---------------------|---------|--------------------------|")
    for lab, c, adj in zip(labels, clocks, adjustments):
        print(f"| {lab:<8} | {c:+19.1f} | {average:7.1f} | {adj:+24.1f} |")
    print(f"\naverage = (0 + 10 + 20 + 30) / 4 = {average:.1f} s")
    print("After applying the adjustments every clock reads "
          f"{average:.1f} s. They AGREE, even though none was right.\n")

    # The weakness: ONE liar poisons the mean.
    print("Weakness (why we need Marzullo next): one liar drags the average.")
    bad_clocks = [0.0, 10.0, 20.0, 300.0]      # slave C is 5 minutes fast
    bad_avg = sum(bad_clocks) / len(bad_clocks)
    print(f"  If slave C jumps to +300 s, average becomes {bad_avg:.1f} s and the")
    print(f"  master would obediently slow itself by {bad_avg:.1f} s to match garbage.")
    print("  Fix: reject outliers BEFORE averaging (Marzullo, section_c).")
    print(f"\n[check] clean-case adjustments sum to 0: "
          f"{abs(sum(adjustments)) < 1e-9}  (they must, by construction)")


# ============================================================================
# SECTION C: NTP strata + Marzullo's intersection algorithm
# ============================================================================

def section_c():
    banner("SECTION C: NTP strata + Marzullo's intersection algorithm")
    print("NTP builds a HIERARCHY. Stratum 0 = a reference clock (atomic/GPS);")
    print("stratum 1 is wired directly to stratum 0; stratum 2 syncs from stratum")
    print("1; and so on. Each hop ADDS error. Stratum 16 means 'unsynchronized'.\n")
    print("| stratum | what it is                          | typical error vs UTC |")
    print("|---------|-------------------------------------|----------------------|")
    rows = [
        (0, "reference clock (atomic / GPS / radio)", "< 1 us  (the truth)"),
        (1, "server directly attached to stratum 0", "~few ms"),
        (2, "syncs from one or more stratum-1",       "~10s of ms"),
        (3, "syncs from stratum-2",                   "~100 ms"),
        (4, "syncs from stratum-3",                   "~hundreds of ms"),
        (16, "unsynchronized / unreachable",          "no guarantee"),
    ]
    for s, what, err in rows:
        print(f"| {s:<7} | {what:<35} | {err:<20} |")
    print("\nError accumulates DOWN the tree: a stratum-3 clock is wrong by")
    print("everything stratum 1 and 2 were wrong by, plus its own RTT/2.\n")

    # ----- Marzullo: reject the liar before it poisons the average -----
    print("Marzullo's algorithm (1984): given several servers, each returning")
    print("(offset, +/- error), keep only the LARGEST clique of intervals that all")
    print("overlap; discard the rest as outliers. This is NTP's outlier filter.\n")
    # Four servers. Three agree tightly; D is a blatant liar.
    labels = ["server A", "server B", "server C", "server D (liar)"]
    offsets = [10.0, 11.0, 12.0, 25.0]
    errors = [2.0, 2.0, 2.0, 2.0]
    print("| server          | offset +/- error | interval [lo, hi] |")
    print("|-----------------|------------------|-------------------|")
    for lab, off, err in zip(labels, offsets, errors):
        print(f"| {lab:<15} | {off:5.1f} +/- {err:.1f}    | [{off - err:5.1f}, {off + err:5.1f}]      |")

    trusted, region = marzullo(offsets, errors)
    est = (region[0] + region[1]) / 2.0
    rejected = [i for i in range(len(offsets)) if i not in trusted]
    print(f"\nLargest overlapping clique = {{"
          f"{', '.join(labels[i].split()[1] for i in trusted)}}} = {len(trusted)} servers")
    print(f"  region of agreement = [{region[0]}, {region[1]}], "
          f"midpoint estimate = {est:.2f}")
    print(f"  rejected as outliers = {{"
          f"{', '.join(labels[i].split()[1] for i in rejected)}}}")
    print(f"\n[check] Marzullo picks the 3 agreeing servers and rejects the liar: "
          f"trusted={trusted}, region={region}:  "
          f"{'OK' if trusted == [0, 1, 2] and region == (10.0, 12.0) else 'FAIL'}")
    assert trusted == [0, 1, 2] and region == (10.0, 12.0)


# ============================================================================
# SECTION D: clock drift
# ============================================================================

def section_d():
    banner("SECTION D: clock drift  (rho ~ 1e-6, worst-case divergence = 2*rho*t)")
    print("A quartz crystal drifts at rate rho. The textbook value is ~1 ppm,")
    print("so a single clock can be off by rho*t and two clocks can differ by")
    print("up to 2*rho*t. Once you SYNC, the clock IMMEDIATELY starts drifting")
    print("again - synchronization is not a state, it is a recurring payment.\n")
    print(f"rho = {RHO:.0e}  (1 ppm). Sanity: rho * 12 days = "
          f"{RHO * 12 * 86400:.4f} s  (~ '1 second per 12 days' per clock)\n")
    def drift_str(x: float) -> str:
        return f"{fmt_dur(x)} ({x:.4g} s)"
    print("| elapsed       | rho * t   (1 clock vs truth) | 2*rho*t  (two clocks)   |")
    print("|---------------|------------------------------|-------------------------|")
    periods = [1.0, 60.0, 3600.0, 86400.0, 12 * 86400.0, 365.25 * 86400.0]
    for t in periods:
        one = RHO * t
        two = 2.0 * RHO * t
        print(f"| {fmt_dur(t):<13} | {drift_str(one):<28} | {drift_str(two):<23} |")
    print(f"\nSo even if you perfectly sync two machines, after ONE DAY they can")
    print(f"already differ by {drift_bound(86400.0):.4f} s, and after a year by "
          f"{drift_bound(365.25 * 86400.0):.2f} s.")
    print("Moral: you must RE-SYNC periodically (NTP polls every ~17 minutes by")
    print("default) just to hold the drift budget.\n")
    print("[check] 2*rho*t for t=1 day == 2 * 1e-6 * 86400 == 0.1728 s:  OK")
    assert abs(drift_bound(86400.0) - 0.1728) < 1e-9


# ============================================================================
# SECTION E: why clocks fail  (leap seconds, NTP steps, VM migration, smear)
# ============================================================================

def section_e():
    banner("SECTION E: why you can NEVER fully trust a wall clock")
    print("Even with Cristian + Berkeley + NTP + Marzullo, wall-clock timestamps")
    print("are unsafe to treat as monotonic facts. Four classic ways they bite:\n")

    print("(1) LEAP SECONDS. The IERS occasionally inserts a 61st second into a")
    print("    UTC minute: 23:59:59 -> 23:59:60 -> 00:00:00. A naive clock either")
    print("    repeats 23:59:59 (so two distinct instants share a timestamp) or")
    print("    smears it. POSIX pretends all days are 86400 s, so the leap second")
    print("    is literally undefined behavior at the OS layer.\n")

    print("(2) NTP STEP ADJUSTMENTS. If ntpd computes an offset larger than the")
    print("    'slew' threshold (~128 ms), it STEPS the clock - an instantaneous")
    print("    jump that can be BACKWARD. Code that does `end - start` on wall-")
    print("    clock readings can get a NEGATIVE duration.\n")
    # Demonstrate the negative-duration bug with a concrete step.
    t_start = 1000.0
    step = -0.5              # NTP wound the clock back half a second
    t_end = 1000.3 + step    # real work took 0.3 s, but clock jumped back
    print(f"    demo: real work took 0.3 s around a -0.5 s NTP step:")
    print(f"          duration = end - start = {t_end} - {t_start} = "
          f"{t_end - t_start:+.3f} s   (NEGATIVE!)\n")

    print("(3) VM MIGRATION. A live-migration pauses the guest for the memory-")
    print("    copy, then resumes. The guest wall clock JUMPS FORWARD by the")
    print("    pause (seconds to minutes) and the TSC may reset. Any timeout or")
    print("    lease based on wall time can fire spuriously.\n")

    print("(4) GOOGLE'S SMEAR (the fix for leap seconds). Instead of a 1 s jump,")
    print("    slow/speed the clock slightly over 24 h so the leap second slides")
    print("    through invisibly:")
    smear_seconds = 1.0
    smear_window = 24.0 * 3600.0
    rate = smear_seconds / smear_window
    print(f"      smear rate = 1 s / {smear_window:.0f} s = {rate:.6e} s/s "
          f"= {rate * 1e6:.2f} us/s = {rate * 1e6:.2f} ppm")
    print("    Over 24 h the clock is at most ~0.5 s off UTC, but it NEVER jumps.")
    print("    The price: during the window your clock disagrees with unsmeared")
    print("    servers by up to half a second.\n")
    print("TAKEAWAY: never use wall-clock time to measure durations or order")
    print("events. Use a MONOTONIC clock (CLOCK_MONOTONIC / performance.now())")
    print("for elapsed time, and logical clocks / HLC for event ordering.")
    print(f"\n[check] smear rate = {rate:.6e} s/s ~= 11.57 ppm:  OK")
    assert abs(rate - 1.1574074074e-5) < 1e-9


# ============================================================================
# main
# ============================================================================

def main():
    print("clock_sync_ntp.py - reference impl. All numbers below feed "
          "CLOCK_SYNC_NTP.md.")
    print("Pure Python stdlib. rho =", RHO)

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
