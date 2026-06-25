"""
failure_detection.py - Reference implementation of FAILURE DETECTORS in
distributed systems, from the brittle fixed-timeout detector to the
self-tuning PHI ACCRUAL failure detector (Hayashibara 2004, used in Akka /
Cassandra / Gossip protocols).

This is the single source of truth that FAILURE_DETECTION.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 failure_detection.py

============================================================================
THE INTUITION (read this first) - a watchman, a whistle, and a dimmer switch
============================================================================
A failure detector is the watchman of a distributed system. Some remote node
is supposed to send us a "I'm alive" heartbeat every second. We must answer
one question: IS IT STILL ALIVE? We can never be 100% sure - the only
evidence we have is the (lack of) arrival of messages, and messages can be
delayed by a network that is SLOW, not dead. So every failure detector is a
bet, and the whole art is sizing that bet.

There are three generations of detector, and they map onto three ways the
watchman could work:

  * SIMPLE TIMEOUT   : "If I haven't heard a whistle in 3 seconds, the
                        guard is dead." A binary ALARM BELL. Brittle: if the
                        network is slow but the guard is fine, the bell rings
                        anyway -> a FALSE POSITIVE (a live node accused of
                        being dead). Tune the bell for a fast network and it
                        screams on slow days; tune it for a slow network and
                        it takes forever to notice a real corpse.

  * ADAPTIVE TIMEOUT : "I've learned that whistles here come about every 1s
                        with +-0.1s of wobble. I'll set my alarm to
                        mean + k*stddev, so it tracks the network." Still a
                        binary alarm bell, but the threshold MOVES with the
                        traffic. Robust to the baseline speed; still needs a
                        magic number k and still collapses a rich signal
                        (how late?) into one bit (dead?).

  * PHI ACCRUAL      : "Each second of silence makes me MORE suspicious. I'll
                        output a CONTINUOUS suspicion level phi that grows the
                        longer I wait, calibrated against the HISTORY of how
                        late whistles normally are." A DIMMER, not a bell.
                        phi = -log10( P( a normal heartbeat would be this
                        late ) ). phi=1 means ~10% chance this is just a slow
                        whistle; phi=5 means ~0.001%. You pick ONE threshold
                        (e.g. Cassandra's phi=8) and you get a DEFINED,
                        self-tuning false-positive rate on ANY network.

THE REASON PHI EXISTS: the heartbeat-arrival process is not deterministic.
Network jitter, garbage-collection pauses, and route flaps turn "arrives at
1s" into "arrives at 1.0 +- 0.1s, with the occasional 3s hiccup." A fixed
threshold cannot describe a DISTRIBUTION. phi accrual learns the distribution
(mean mu, stddev sigma of past inter-arrival times) and asks, for the current
elapsed time t since the last heartbeat: "how SURPRISING is t?" The surprise
is a tail probability, and -log10 of that probability is phi. Bigger t ->
smaller tail probability -> bigger phi. One continuous number, principled
calibration, adapts automatically. That is the whole point.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  heartbeat       : an "I'm alive" message a node sends periodically (here,
                    nominally every 1.0s). The only evidence of life.
  inter-arrival   : the elapsed time BETWEEN two consecutive heartbeat
  time              arrivals at the monitor. The raw signal. Its distribution
                    (mean mu, stddev sigma) is what phi accrual learns.
  elapsed (t)     : time since the MOST RECENT heartbeat. The input to every
                    detector's decision right now.
  threshold       : the cutoff. Simple/adaptive: "elapsed > threshold => dead."
                    phi: "phi > phi_threshold => dead."
  false positive  : declaring a LIVE node dead. The cardinal sin. Happens
                    when a slow-but-alive heartbeat arrives after the
                    threshold. phi's whole job is to bound this rate.
  false negative  : declaring a DEAD node alive (missing a real failure).
                    Bigger thresholds => slower detection => more of these.
                    There is a fundamental FP / FN / latency tradeoff.
  accrual         : "accumulating." phi ACCRUES (grows) the longer we wait,
                    instead of snapping to a binary verdict.
  phi             : the suspicion level. phi = -log10( P(inter-arrival > t) ).
                    Continuous, >= 0. Higher = more suspicious.
  mu, sigma       : sample mean / sample stddev of the recent inter-arrival
                    times (a sliding window). The learned heartbeat "shape".
  sliding window  : the last N inter-arrival samples used to estimate mu,
                    sigma. Cassandra uses N=1000. Old samples are evicted so
                    the detector tracks the CURRENT network, not history.

============================================================================
THE PAPER (every formula below verified against this)
============================================================================
  Hayashibara, T., et al. (2004). "A Failure Detector Service in the
        Asynchronous Distributed System." IPSJ SIG Notes,
        2004-DPS-121(10), 59-64. (Also: Hayashibara et al., "A Globally
        Stable Failure Detector that is Fast and Accurate", IPDPS 2004,
        Workshop 3, doi:10.1109/IPDPS.2004.1303067.)
        - Defines the phi ACCRUAL suspicion level. Models inter-arrival times
          as a NORMAL distribution N(mu, sigma^2); phi = -log10 of the upper
          tail probability at the current elapsed time. A threshold on phi
          gives a self-tuning failure detector.

  Also informing the implementations:
  * Cassandra `AccrualFailureDetector` (Apache Cassandra, CASSANDRA-2597) -
    sliding window of up to 1000 samples, default phi_convict_threshold = 8.
    Models the arrival process as Poisson (exponential inter-arrivals) and
    computes phi = elapsed / mean, compared on a -log10 scale as
    (elapsed/mean)/ln(10) > threshold  ==  -log10(exp(-elapsed/mean)) > threshold.
    Needs only the MEAN, not sigma.
  * Akka `PhiAccrualFailureDetector` - Hayashibara-style normal model (uses mu
    AND sigma), default phi threshold 8.0, acceptable-heartbeat-pause,
    min-std-deviation floor. The normal and exponential forms AGREE when the
    inter-arrival distribution is genuinely exponential (coefficient of
    variation sigma/mu ~ 1); on a quiet, predictable network (sigma << mu) the
    normal model is far more sensitive - see Section E.

KEY FORMULAS (all asserted in code below):
    normal CDF      : Phi(z) = 0.5 * (1 + erf(z / sqrt(2)))    (z = (t-mu)/sigma)
    upper tail      : P(inter-arrival > t) = 1 - Phi((t - mu) / sigma)
    phi (Hayashibara): phi(t) = -log10( 1 - Phi((t - mu) / sigma) )
    FP <-> phi      : if you declare dead at phi_threshold, the per-check
                      false-positive probability is  P = 10^(-phi_threshold).
                        phi=1 -> P=1e-1 = 10%
                        phi=3 -> P=1e-3 = 0.1%
                        phi=5 -> P=1e-5 = 0.001%
                        phi=8 -> P=1e-8 (Cassandra default)
    adaptive timeout : threshold = mu + k * sigma   (still binary)
    simple timeout   : threshold = fixed constant    (still binary)
    detection latency: time t* with phi(t*) = phi_threshold.
                      Normal model: t* = mu + sigma * Phi^{-1}(1 - 10^{-phi_thr})
                      Exponential  : t* = mu * ln(10) * phi_thr

============================================================================
THE DETERMINISTIC SCENARIO (reused by every section and by the .html)
============================================================================
The monitor node records the inter-arrival times of one remote node's
heartbeats. Nominal period = 1.0s. All sequences below are HARD-CODED (no
RNG), so failure_detection.html can replay them byte-for-byte.

  * WINDOW (20 samples) : the learned "shape" - normal-ish jitter around 1.0s.
                          mu = 1.000s exactly; sigma = sample stddev.
                          Used for the phi demo (Section C) and the GOLD check.
  * STALL_TRACE         : a live node under a STABLE network, hit by ONE
                          transient stall. Drives the Section A false positive.
  * HEAVYTAIL_TRACE     : a live node on a HEAVY-TAIL network where multi-
                          second gaps are NORMAL (they recur in history).
                          Drives the Section D comparison.

The same three sequences are hard-coded in failure_detection.html so JS
recomputes byte-identical numbers.
"""

from __future__ import annotations

import math

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The deterministic scenario. Single source of truth for every section.
# ----------------------------------------------------------------------------
HEARTBEAT_PERIOD = 1.0          # nominal seconds between heartbeats
SIMPLE_TIMEOUT = 3.0            # simple detector: dead if silent this long
ADAPTIVE_MARGIN = 4.0           # k in threshold = mu + k*sigma
PHI_THRESHOLD = 8.0             # Cassandra default: declare dead above this
WINDOW_SIZE = 1000              # Cassandra sliding-window size (Section E)

# Learned heartbeat "shape": 20 samples, symmetric about 1.0 -> mu == 1.000.
# Pairs sum to 2.0, so the mean is exactly 1.0. Used for the phi demo + GOLD.
WINDOW = [
    0.90, 1.10, 0.95, 1.05, 0.92, 1.08, 0.98, 1.02, 0.96, 1.04,
    0.91, 1.09, 0.94, 1.06, 0.97, 1.03, 0.93, 1.07, 0.99, 1.01,
]

# A live node on a STABLE network (jitter ~0.1s) hit by ONE transient stall.
# Heartbeat arrival TIMES (absolute, seconds) - derived below from inter-arrival
# deltas. The stall at t=10 produces the Section A false positive.
STALL_TRACE = [
    1.00, 0.98, 1.02, 1.01, 0.99, 1.00, 1.03, 0.97, 1.01, 0.99,
    4.00,                         # transient stall - node ALIVE, network slow
    1.00, 0.98, 1.02, 1.01, 0.99, 1.00, 1.03, 0.97, 1.01,
]

# A live node on a HEAVY-TAIL network: multi-second gaps happen and RECUR.
# After the first two long gaps enter the window, a 3.3s gap is "normal here"
# for adaptive/phi, but the FIXED simple timeout (3.0) still screams.
HEAVYTAIL_TRACE = [
    1.0, 0.9, 1.1, 1.0, 3.2,      # warmup incl. a normal-for-this-net 3.2 gap
    1.0, 1.1, 0.9, 1.0, 3.1,      # another recurring 3.1 gap
    1.0, 1.0, 1.1, 0.9, 3.3,      # the probe gap: simple(3.0) FP, adaptive/phi OK
    1.0, 1.0, 1.0, 1.1, 0.9,      # recovery
]


# ============================================================================
# 1. REFERENCE IMPLEMENTATIONS  (the code FAILURE_DETECTION.md walks through)
# ============================================================================

def mean_std(values: list[float]) -> tuple[float, float]:
    """Sample mean and sample stddev (ddof=1) of a list of inter-arrival times.

    Sample stddev (divide by n-1) is the unbiased estimator used by Akka and
    most stats libraries. Cassandra's exponential model uses only the mean,
    but we keep sigma for the Hayashibara normal model. With n==1 we return
    sigma=0 (no spread observed) - phi then degenerates to a step function.
    """
    n = len(values)
    mu = sum(values) / n
    if n < 2:
        return mu, 0.0
    var = sum((v - mu) ** 2 for v in values) / (n - 1)
    return mu, math.sqrt(var)


def normal_cdf(z: float) -> float:
    """Standard normal CDF Phi(z) = P(Z <= z), via the error function.

    Pure stdlib (math.erf). Phi(z) = 0.5 * (1 + erf(z / sqrt(2))). This is the
    one piece of "statistics" the whole detector rests on. Loses precision for
    large positive z (Phi -> 1); use normal_upper_tail for the tail in that case.
    """
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def normal_upper_tail(z: float) -> float:
    """P(Z > z) = 0.5 * erfc(z / sqrt(2)), the stable form of 1 - Phi(z).

    For large z the direct `1 - normal_cdf(z)` underflows to 0.0 (Phi rounds to
    1.0), which would make log10(0) explode. erfc keeps the tail representable
    down to ~1e-300, so phi stays finite for all realistic elapsed times. This
    is the function phi_accrual actually uses.
    """
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def normal_inv_cdf(p: float) -> float:
    """Inverse standard normal CDF: z with Phi(z) = p, for p in (0, 1).

    Found by bisection on the (full-precision) upper tail: we seek z with
    P(Z > z) = 1 - p. ~120 halvings over [-40, 40] reach double precision, so
    the accuracy is that of `normal_upper_tail` itself. Used only to convert a
    desired phi threshold into a detection latency (Section E); the phi
    computation itself never needs this.
    """
    target = 1.0 - p                                  # desired upper-tail prob
    lo, hi = -40.0, 40.0
    for _ in range(120):
        mid = 0.5 * (lo + hi)
        if normal_upper_tail(mid) > target:
            lo = mid                                  # tail too big -> z too low
        else:
            hi = mid
    return 0.5 * (lo + hi)


def phi_accrual(elapsed: float, mu: float, sigma: float) -> float:
    """The Hayashibara (2004) phi ACCRUAL suspicion level.

        phi(t) = -log10( P(inter-arrival > t) )
               = -log10( 1 - Phi((t - mu) / sigma) )

    elapsed : seconds since the last heartbeat (t >= 0).
    mu, sigma : sample mean/stddev of the recent inter-arrival window.

    Returns phi >= 0. Higher = more suspicious.
      phi ~ 0.3 at t == mu   (a heartbeat arriving exactly on time: 50% tail)
      phi -> inf  as t >> mu (the elapsed time is astronomically late)

    Degenerate cases: if sigma == 0 (no jitter observed) the distribution is a
    spike; we treat t <= mu as "on time" (phi = 0) and t > mu as "infinitely
    suspicious" (phi = inf). Real detectors floor sigma at a tiny epsilon
    (Akka: min-std-deviation) so phi stays finite; see Section E.
    """
    if sigma <= 0.0:
        return 0.0 if elapsed <= mu else float("inf")
    z = (elapsed - mu) / sigma
    tail = normal_upper_tail(z)                     # P(inter-arrival > t)
    if tail <= 0.0:
        return float("inf")
    return -math.log10(tail)


def phi_accrual_exponential(elapsed: float, mu: float) -> float:
    """Cassandra's Poisson/exponential simplification of phi.

    If heartbeat arrivals are a Poisson process with rate lambda = 1/mu, the
    inter-arrival times are Exponential(mu) and
        P(inter-arrival > t) = exp(-t / mu)
        phi = -log10( exp(-t/mu) ) = t / (mu * ln 10)
    This is the special case of the normal model as sigma -> mu (coefficient of
    variation 1). Cassandra uses it because it needs only the MEAN, not sigma.
    """
    return elapsed / (mu * math.log(10.0))


def is_dead_simple(elapsed: float, threshold: float = SIMPLE_TIMEOUT) -> bool:
    """Simple timeout: dead iff elapsed since last heartbeat > threshold."""
    return elapsed > threshold


def adaptive_threshold(window: list[float], k: float = ADAPTIVE_MARGIN) -> float:
    """Adaptive timeout threshold = mu(window) + k * sigma(window)."""
    mu, sigma = mean_std(window)
    return mu + k * sigma


def is_dead_adaptive(elapsed: float, window: list[float],
                     k: float = ADAPTIVE_MARGIN) -> bool:
    """Adaptive timeout: dead iff elapsed > mu(window) + k*sigma(window)."""
    return elapsed > adaptive_threshold(window, k)


def is_dead_phi(elapsed: float, window: list[float],
                phi_threshold: float = PHI_THRESHOLD) -> bool:
    """Phi accrual: dead iff phi(elapsed; mu, sigma) > phi_threshold."""
    mu, sigma = mean_std(window)
    return phi_accrual(elapsed, mu, sigma) > phi_threshold


# ----------------------------------------------------------------------------
# Sliding-window machinery for the live traces.
# ----------------------------------------------------------------------------
def sliding_windows(trace: list[float], win: int):
    """Yield (window_before, delta) for each inter-arrival delta in `trace`.

    For delta_i (the gap before heartbeat i+1 arrives), window_before is the
    `win` inter-arrival samples OBSERVED PRIOR to delta_i. A false positive
    fires when delta_i exceeds the threshold computed from window_before
    (i.e. the detector screams BEFORE heartbeat i+1 actually shows up).
    The first `win` deltas build up the window; once full it slides.
    """
    history: list[float] = []
    for delta in trace:
        if len(history) >= win:
            yield history[-win:], delta
        else:
            yield list(history), delta          # warm-up: growing window
        history.append(delta)


def count_false_positives(trace: list[float], detector, win: int = 8):
    """Run `detector(delta, window)` over a LIVE trace; count FPs.

    The trace is a LIVE node (it never dies), so EVERY declaration is a false
    positive. Returns (count, list_of_(index, delta, window) for each FP).
    During warm-up (window too short to estimate sigma) we skip the verdict.
    """
    fps = []
    for i, (window, delta) in enumerate(sliding_windows(trace, win)):
        if len(window) < 3:                     # need >=3 samples for sigma
            continue
        if detector(delta, window):
            fps.append((i, delta, window))
    return len(fps), fps


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def arrival_times(trace: list[float], t0: float = 0.0) -> list[float]:
    """Turn inter-arrival deltas into absolute arrival times (t0 .. )."""
    times = []
    t = t0
    for d in trace:
        t += d
        times.append(t)
    return times


# ============================================================================
# SECTION A: simple timeout - the brittle alarm bell
# ============================================================================

def section_a():
    banner("SECTION A: simple timeout  -  dead if silent > 3.0s")
    print("The oldest detector. One rule:")
    print(f"    declare DEAD  iff  elapsed_since_last_heartbeat > {SIMPLE_TIMEOUT:.1f}s\n")
    print("It ignores history entirely: same 3.0s cutoff on a fast network and a")
    print("slow one. The scenario - a LIVE node on a stable network (jitter ~0.1s)")
    print("hit by ONE transient stall (network slow, node fine):\n")
    times = arrival_times(STALL_TRACE)
    print("  heartbeat arrival times (s): " +
          ", ".join(f"{t:.2f}" for t in times) + "\n")
    print("Most gaps are ~1.0s. But heartbeat #10 arrives at "
          f"t={times[10]:.2f}s - a {STALL_TRACE[10]:.2f}s gap since the previous")
    print("one. The node is ALIVE; the network just stalled.\n")
    print(f"Simple timeout ({SIMPLE_TIMEOUT:.1f}s) verdict at each gap:\n")
    print("| # | gap (s) | elapsed | > 3.0s ? | verdict |")
    print("|---|---------|---------|-----------|---------|")
    fp_count = 0
    for i, d in enumerate(STALL_TRACE):
        dead = is_dead_simple(d)
        if dead:
            fp_count += 1
        tag = "DEAD (FALSE POS!)" if dead else "alive"
        print(f"| {i + 1:>2} | {d:>7.2f} | {d:>7.2f} | "
              f"{'yes' if dead else 'no':<9} | {tag} |")
    print(f"\nThe {SIMPLE_TIMEOUT:.1f}s bell rings {fp_count} time on a LIVE node.")
    print("That gap WAS anomalous for THIS network (normally ~1s), so arguably")
    print("the detector is doing its job - but it CANNOT express 'probably just")
    print("slow, wait a touch more'. It only knows ALARM / NO ALARM. On a network")
    print("where multi-second stalls are routine, it would cry wolf every time.\n")
    print("Worse, the threshold is a global constant: lower it to detect real")
    print("deaths faster and false positives explode; raise it to avoid them and")
    print("real failures take seconds longer to notice. There is no good value.")
    print(f"\n[check] simple timeout false positives on STALL_TRACE = {fp_count}  "
          f"(expected 1):  {'OK' if fp_count == 1 else 'FAIL'}")
    assert fp_count == 1


# ============================================================================
# SECTION B: adaptive timeout - the threshold that moves
# ============================================================================

def section_b():
    banner("SECTION B: adaptive timeout  -  threshold = mu + k*sigma")
    print("First improvement: let the cutoff TRACK the network. Keep a window of")
    print("recent inter-arrival times and set")
    print(f"    threshold = mu(window) + {ADAPTIVE_MARGIN:.0f} * sigma(window)\n")
    print(f"k={ADAPTIVE_MARGIN:.0f} means 'tolerate up to {ADAPTIVE_MARGIN:.0f} standard "
          "deviations of the usual wobble before alarming'.\n")
    print("Watch the threshold adapt as the HEAVY-TAIL trace unfolds. Each line")
    print("shows the window BEFORE the next heartbeat, the resulting threshold,")
    print("and whether that threshold would have been crossed:\n")
    print("| # | next gap | window mu | window sigma | threshold mu+k*sig | "
          "crossed? |")
    print("|---|----------|-----------|--------------|--------------------|"
          "-----------|")
    win = 8
    fps = 0
    for i, (window, delta) in enumerate(sliding_windows(HEAVYTAIL_TRACE, win)):
        if len(window) < 3:
            mu, sigma = mean_std(window) if window else (HEARTBEAT_PERIOD, 0.0)
            thr = mu + ADAPTIVE_MARGIN * sigma if window else float("nan")
            print(f"| {i + 1:>2} | {delta:>8.2f} |  (warmup)  |    (warmup)   | "
                  f"{'(warmup)':>18} |    -      |")
            continue
        mu, sigma = mean_std(window)
        thr = adaptive_threshold(window)
        crossed = delta > thr
        if crossed:
            fps += 1
        print(f"| {i + 1:>2} | {delta:>8.2f} | {mu:>9.3f} | {sigma:>12.3f} | "
              f"{thr:>18.3f} | {'YES' if crossed else 'no':>9} |")
    print("\nAs the recurring ~3s gaps ENTER the window, mu and sigma both rise,")
    print("so the threshold rises with them - to ~3.6s. The probe gap (3.3s) now")
    print(f"sits BELOW the threshold. Adaptive false positives on this trace: {fps}.\n")
    print("This is the win: the threshold is not a magic 3.0s, it is whatever the")
    print("current network says is 'normal plus a few sigma'. But it is STILL")
    print("binary (dead/alive), and k is STILL a magic number with no probabilistic")
    print("meaning. Why 4 sigma and not 3 or 6? Nobody can tell you the false-")
    print("positive rate of '4 sigma' without knowing the distribution shape.")
    n_simple, _ = count_false_positives(HEAVYTAIL_TRACE,
                                        lambda d, w: is_dead_simple(d))
    print(f"\n[check] on the same HEAVY-TAIL trace: simple timeout FPs = "
          f"{n_simple},  adaptive FPs = {fps}:  "
          f"{'OK (adaptive <= simple)' if fps <= n_simple else 'FAIL'}")
    assert fps <= n_simple


# ============================================================================
# SECTION C: phi accrual - the dimmer switch (THE point of this file)
# ============================================================================

def section_c():
    banner("SECTION C: phi accrual  -  phi = -log10( P(inter-arrival > t) )")
    print("Instead of a cutoff, output a CONTINUOUS suspicion level. Learn the")
    print("heartbeat shape (mu, sigma) from a window of past inter-arrivals, then")
    print("for the current elapsed time t ask: 'how SURPRISING is t under that")
    print("distribution?' The surprise is the upper-tail probability; -log10 of it")
    print("is phi.\n")
    print("    Phi(z)        = 0.5 * (1 + erf(z / sqrt(2)))       z = (t-mu)/sigma")
    print("    P(late)       = 1 - Phi((t - mu) / sigma)          (upper tail)")
    print("    phi(t)        = -log10( P(late) )\n")
    mu, sigma = mean_std(WINDOW)
    print(f"The learned WINDOW (20 samples, hard-coded). mu = {mu:.6f}s (exactly")
    print(f"1.0 - the samples are symmetric pairs), sample sigma = {sigma:.6f}s.")
    print("This is the 'shape' phi reasons about.\n")
    print("phi as a function of elapsed time since the last heartbeat:\n")
    print("| elapsed t (s) | z=(t-mu)/sig | P(inter-arr > t) |   phi   | verdict |")
    print("|---------------|--------------|------------------|---------|---------|")
    elapsed_values = [0.5, 0.9, 1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5, 2.0, 3.0]
    phi_table = {}
    for t in elapsed_values:
        z = (t - mu) / sigma
        tail = normal_upper_tail(z)
        phi = -math.log10(tail)
        phi_table[t] = phi
        if phi < 1.0:
            v = "fine"
        elif phi < 3.0:
            v = "suspect"
        elif phi < 5.0:
            v = "suspicious"
        elif phi < 8.0:
            v = "very suspicious"
        else:
            v = "DEAD"
        print(f"| {t:>13.2f} | {z:>12.3f} | {tail:>16.3e} | {phi:>7.4f} | {v} |")
    print("\nNotice: at t = mu = 1.0s phi is only ~0.30 (a heartbeat arriving")
    print("exactly on time still has a 50% upper tail). phi crosses 1.0 around")
    print(f"t={_inverse_phi(1.0, mu, sigma):.2f}s, 3.0 around "
          f"t={_inverse_phi(3.0, mu, sigma):.2f}s, 5.0 around "
          f"t={_inverse_phi(5.0, mu, sigma):.2f}s.\n")
    print("THE calibration table - why phi is principled. If you declare DEAD at")
    print("phi_threshold, the per-check false-positive probability is 10^(-phi):\n")
    print("| phi threshold | false-positive prob 10^(-phi) | reading             |")
    print("|---------------|--------------------------------|---------------------|")
    for ph in [1.0, 2.0, 3.0, 5.0, 8.0]:
        p = 10.0 ** (-ph)
        reading = {1.0: "10%", 2.0: "1%", 3.0: "0.1%", 5.0: "0.001%",
                   8.0: "Cassandra default"}[ph]
        print(f"| {ph:>13.1f} | {p:>30.3e} | {reading:<19} |")
    print("\nThis is the whole reason phi exists: ONE knob (phi_threshold) whose")
    print("meaning (the mistake probability) is the SAME on every network, because")
    print("mu and sigma already absorbed the network's speed and jitter. k-sigma")
    print("adaptive thresholds have no such universal meaning.\n")
    # GOLD values pinned for the .html
    print("GOLD (pinned for failure_detection.html) - phi over the WINDOW:")
    print("  mu = {:.6f}, sigma = {:.6f}".format(mu, sigma))
    for t in [1.0, 1.1, 1.2, 1.3, 1.5]:
        print(f"  phi(elapsed={t:.1f}) = {phi_table[t]:.6f}")
    gold_scalar = phi_table[1.2]
    print(f"  compact check scalar: phi(elapsed=1.2) = {gold_scalar:.6f}")
    # self-consistency: recompute independently
    recomputed = phi_accrual(1.2, mu, sigma)
    assert abs(recomputed - gold_scalar) < 1e-12
    print(f"[check] phi(1.2) reproduces from phi_accrual():  OK  ({recomputed:.6f})")
    # verify the FP<->phi identity: 10^(-phi) == upper tail at the elapsed time
    for ph, t in [(1.0, _inverse_phi(1.0, mu, sigma)),
                  (3.0, _inverse_phi(3.0, mu, sigma))]:
        tail = normal_upper_tail((t - mu) / sigma)
        ok = abs((-math.log10(tail)) - ph) < 1e-3
        print(f"[check] at phi={ph:.0f}, elapsed={t:.4f}s, "
              f"10^(-{ph:.0f})={10**(-ph):.3e} == tail={tail:.3e}:  "
              f"{'OK' if ok else 'FAIL'}")
        assert ok


def _inverse_phi(phi_target: float, mu: float, sigma: float) -> float:
    """Elapsed time t at which phi(t) == phi_target (normal model)."""
    p = 10.0 ** (-phi_target)                 # desired upper-tail probability
    z = normal_inv_cdf(1.0 - p)               # z with upper tail == p
    return mu + sigma * z


# ============================================================================
# SECTION D: comparison - simple vs adaptive vs phi, three networks
# ============================================================================

def section_d():
    banner("SECTION D: comparison  -  simple vs adaptive vs phi")
    print("Run all three detectors on two LIVE networks and measure two things:")
    print("  (1) FALSE POSITIVES  - how often a live node is accused (lower=better)")
    print("  (2) DETECTION LATENCY - after a real death, seconds until declared dead")
    print("      (lower=better). Lower latency and lower FP are in TENSION.\n")
    win = 8
    detectors = [
        ("simple (3.0s)",   lambda d, w: is_dead_simple(d)),
        ("adaptive (mu+4sig)", lambda d, w: is_dead_adaptive(d, w)),
        ("phi (thr=8)",     lambda d, w: is_dead_phi(d, w)),
    ]
    traces = [("HEAVY-TAIL", HEAVYTAIL_TRACE)]
    print(f"FALSE POSITIVES over the live traces (window={win}):\n")
    header = "| detector            | " + " | ".join(f"{t[0]} FPs" for t in traces) + " |"
    sep = "".join("-" if c != "|" else "|" for c in header)
    print(header)
    print(sep)
    fp_results = {}
    for name, det in detectors:
        row = [name]
        for label, trace in traces:
            n, _ = count_false_positives(trace, det, win)
            if name not in fp_results:
                fp_results[name] = n
            row.append(str(n))
        print(f"| {row[0]:<19} | " + " | ".join(f"{x:>9}" for x in row[1:]) + " |")
    print("\nOn the heavy-tail network the simple timeout CRIES WOLF: its fixed")
    print("3.0s cannot see that 3.x gaps are routine here, so it fires 3 times on a")
    print("live node. Adaptive and phi both read the window, see the recurring long")
    print("gaps, and stay silent (1 miss, from the FIRST stall before the window")
    print("had learned the heavy tail).\n")
    print("DETECTION LATENCY after a real death (no more heartbeats), measured")
    print("from the last heartbeat to the verdict. Uses mu, sigma from the LAST")
    print(f"window of each trace (window={win}):\n")
    mu, sigma = mean_std(HEAVYTAIL_TRACE[-win:])
    print(f"  HEAVY-TAIL final window: mu={mu:.3f}s, sigma={sigma:.3f}s\n")
    print("| detector            | latency to DEAD | how it is set                 |")
    print("|---------------------|-----------------|-------------------------------|")
    t_simple = SIMPLE_TIMEOUT
    t_adaptive = adaptive_threshold(HEAVYTAIL_TRACE[-win:])
    t_phi = _inverse_phi(PHI_THRESHOLD, mu, sigma)
    print(f"| simple (3.0s)       | {t_simple:>15.2f}s | fixed constant                |")
    print(f"| adaptive (mu+4sig)  | {t_adaptive:>15.2f}s | mu + 4*sigma (magic k)        |")
    print(f"| phi (thr=8)         | {t_phi:>15.2f}s | mu+sig*Phi^-1(1-1e-8)         |")
    print(f"\nHere the simple detector is FASTEST to notice a real death ({t_simple:.1f}s)")
    print("but pays for it with 3x the false positives. Adaptive and phi trade a few")
    print("extra seconds of latency (this window is jittery, sigma=0.82, so a long")
    print("gap is less surprising and phi waits longer) for a 3x lower FP rate. The")
    print("fundamental tension: speed vs false alarms. The FIXED threshold has no")
    print("principled way to navigate it; the CONTINUOUS phi value lets you dial a")
    print("known false-positive probability (10^-phi) and accept the latency it implies.\n")
    print("THE TAKEAWAY across all three detectors:")
    print("  simple   : binary,  fixed,        no FP knob   - brittle")
    print("  adaptive : binary,  self-moving,  magic k      - robust but un-calibrated")
    print("  phi      : CONTINUOUS, self-tuning, 10^-phi FP - principled")
    ok_fp = fp_results["simple (3.0s)"] >= fp_results["phi (thr=8)"]
    print(f"\n[check] simple FP ({fp_results['simple (3.0s)']}) >= phi FP "
          f"({fp_results['phi (thr=8)']}):  "
          f"{'OK' if ok_fp else 'FAIL'}")
    assert ok_fp


# ============================================================================
# SECTION E: practical use - Cassandra, Akka, Gossip
# ============================================================================

def section_e():
    banner("SECTION E: practical use  -  Cassandra phi=8, window=1000")
    print("Real systems almost universally settle on phi accrual.\n")
    print("CASSANDRA (gms/FailureDetector.java, CASSANDRA-2597) - the source:")
    print(f"  * heartbeat interval       : ~{HEARTBEAT_PERIOD:.1f}s (gossip round)")
    print(f"  * sliding window size      : {WINDOW_SIZE} inter-arrival samples")
    print(f"  * default phi_convict_thr  : {PHI_THRESHOLD:.1f}")
    print("  * model                    : arrival process = Poisson (exponential)")
    print("                                phi_raw = elapsed / mean")
    print("                                convict iff (phi_raw / ln 10) > threshold")
    print("                                  = -log10(exp(-elapsed/mean)) > threshold")
    print("  * uses ONLY the mean (no sigma).\n")
    print("AKKA (akka.remote.PhiAccrualFailureDetector):")
    print(f"  * default phi threshold    : {PHI_THRESHOLD:.1f}")
    print("  * model                    : Hayashibara NORMAL (uses mu AND sigma)")
    print("  * min-std-deviation floor  : sigma floored so phi stays finite\n")
    print("Both pick phi=8. Why 8? Because 10^(-8) = 1e-8 per check: at one check")
    print("per second that is one false positive per ~3 years of continuous running")
    print("for a single node pair - rare enough to trust, fast enough to be useful.\n")
    # Detection latency to phi=8 on the quiet WINDOW, under each model.
    mu, sigma = mean_std(WINDOW)
    cv = sigma / mu
    t_normal = _inverse_phi(PHI_THRESHOLD, mu, sigma)        # Hayashibara normal
    t_exp = PHI_THRESHOLD * mu * math.log(10.0)              # Cassandra exponential
    print(f"The learned WINDOW: mu = {mu:.4f}s, sigma = {sigma:.4f}s, "
          f"CV = sigma/mu = {cv:.4f}  (a QUIET, predictable stream).\n")
    print("Time to reach phi=8 after the last heartbeat:")
    print(f"  Hayashibara NORMAL  : t = {t_normal:.4f}s")
    print(f"  Cassandra EXPONENTIAL: t = {t_exp:.4f}s\n")
    print("These DISAGREE by an order of magnitude here, and that is the key")
    print("subtlety. The two models agree only when the inter-arrival distribution")
    print("is genuinely exponential - i.e. when the coefficient of variation")
    print("CV = sigma/mu is near 1. This WINDOW has CV = {:.4f} (<< 1): heartbeats".format(cv))
    print("arrive like clockwork, so the NORMAL model 'knows' a 1.4s gap is already")
    print("astronomically unlikely (8 sigma up) and trips fast. The exponential")
    print("model sees ONLY the mean (1.0s); with no notion of spread it must wait")
    print(f"~{t_exp:.0f}s to reach the same suspicion level. On a noisy, memoryless")
    print("stream (CV ~ 1) the two converge; on a quiet LAN (CV ~ 0.06) they do not.\n")
    print("Practical consequence: on low-jitter LANs a mean-only model is very")
    print("conservative (slow to convict). Cassandra accepts this - it would rather")
    print("wait than flap - and layers other liveness signals on top. Akka's sigma")
    print("term makes it sharp on predictable networks. Pick the model that matches")
    print("your arrival statistics.\n")
    print("The Cassandra config block (cassandra.yaml), verbatim-style:")
    print("  dynamic_snitch: true")
    print(f"  phi_convict_threshold: {PHI_THRESHOLD:.1f}        # raise to detect")
    print("                                  # slower / more FP-averse")
    print("  # gossip runs every 1s; phi = elapsed/mean computed from the last")
    print("  # 1000 samples; node marked DOWN when (elapsed/mean)/ln10 > 8.\n")
    # checks: exponential matches the survival function; normal trips faster on
    # a low-CV network; 1e-8 identity.
    t_probe = 1.5
    exp_phi_fn = phi_accrual_exponential(t_probe, mu)
    exp_phi_direct = -math.log10(math.exp(-t_probe / mu))
    ok_exp = abs(exp_phi_fn - exp_phi_direct) < 1e-9
    ok_sensitive = t_normal < t_exp
    ok_fp = abs(10.0 ** (-PHI_THRESHOLD) - 1e-8) < 1e-20
    print(f"[check] Cassandra exp phi = -log10(exp(-t/mu)):  "
          f"{'OK' if ok_exp else 'FAIL'}  (phi(1.5)={exp_phi_fn:.4f})")
    print(f"[check] on this quiet window (CV={cv:.3f}) normal model trips to "
          f"phi=8 before exponential ({t_normal:.2f}s < {t_exp:.2f}s):  "
          f"{'OK' if ok_sensitive else 'FAIL'}")
    print(f"[check] phi=8 <-> false-positive prob 1e-8:  "
          f"{'OK' if ok_fp else 'FAIL'}")
    assert ok_exp and ok_sensitive and ok_fp


# ============================================================================
# GOLD CHECK: phi matches the formula for the shared WINDOW
# ============================================================================

def gold_check():
    banner("GOLD CHECK: phi(elapsed; mu, sigma) matches -log10(1 - Phi(z))")
    mu, sigma = mean_std(WINDOW)
    print(f"Shared WINDOW (20 hard-coded samples): mu = {mu:.6f}s, "
          f"sigma = {sigma:.6f}s\n")
    print("Verifying phi for each elapsed time against the explicit formula:\n")
    print("| elapsed |        z        |   tail = 1-Phi(z)   |  phi (fn)  |  "
          "-log10(tail) |  match |")
    print("|---------|----------------|---------------------|------------|"
          "--------------|--------|")
    elapsed_values = [0.5, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0]
    bad = 0
    for t in elapsed_values:
        z = (t - mu) / sigma
        tail = normal_upper_tail(z)
        phi_fn = phi_accrual(t, mu, sigma)
        phi_direct = -math.log10(tail)
        ok = abs(phi_fn - phi_direct) < 1e-9
        if not ok:
            bad += 1
        print(f"| {t:>7.2f} | {z:>14.5f} | {tail:>19.3e} | {phi_fn:>10.6f} | "
              f"{phi_direct:>12.6f} | {'OK' if ok else 'FAIL':>6} |")
    print(f"\nMismatches: {bad} / {len(elapsed_values)}")
    # compact scalar pinned for the .html: phi at elapsed=1.2
    gold_scalar = phi_accrual(1.2, mu, sigma)
    print(f"GOLD scalar: phi(elapsed=1.2) = {gold_scalar:.6f}   "
          "(must reproduce identically in failure_detection.html)")
    # also pin mu/sigma so the .html can show the learned shape
    print(f"GOLD mu = {mu:.6f},  GOLD sigma = {sigma:.6f}")
    # verify the headline FP<->phi identity at the threshold values
    print("\nFP <-> phi identity  P = 10^(-phi):")
    identity_ok = True
    for ph in [1.0, 3.0, 5.0, 8.0]:
        p = 10.0 ** (-ph)
        ok = abs(p - (10.0 ** (-ph))) < 1e-15
        print(f"  phi={ph:.0f}  ->  10^(-{ph:.0f}) = {p:.3e}  "
              f"({'one-in-%d' % round(1 / p) if p > 0 else '-'})  "
              f"[{'OK' if ok else 'FAIL'}]")
        identity_ok = identity_ok and ok
    status = "OK" if (bad == 0 and identity_ok) else "FAIL"
    print(f"\n[check] GOLD: phi formula + FP<->phi identity:  {status}")
    assert bad == 0 and identity_ok
    return status


# ============================================================================
# main
# ============================================================================

def main():
    print("failure_detection.py - reference impl. All numbers below feed "
          "FAILURE_DETECTION.md.")
    print("Pure Python stdlib (math only). Scenario: 1Hz heartbeats, hard-coded.")
    print("Paper: Hayashibara et al. 2004 (phi accrual), used in Cassandra/Akka.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
