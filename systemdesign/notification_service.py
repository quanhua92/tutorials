"""
notification_service.py - Reference simulation of a multi-channel Notification
Service (push / email / SMS / in-app): priority queue, per-user preference
aggregation, fan-out to channels, delivery-guarantee tracking (at-least-once
with retry + DLQ), deduplication via idempotency keys, and per-user rate
limiting.

This is the single source of truth that NOTIFICATION_SERVICE.md is built from.
Every fan-out count, delivery status, dedup decision, priority order, and scale
number in the guide is printed by this file. Deterministic (no randomness, no
wall-clock). Re-run and re-paste the output into the guide.

Run:
    python3 notification_service.py

========================================================================
THE INTUITION (read this first) - the smart mailroom problem
========================================================================
A notification service is a smart mailroom. An event ("Alice liked your photo")
arrives. The mailroom must decide:

  * WHO gets it     : the target user (and which users, for group events).
  * WHICH channels  : push, email, SMS, in-app - but the USER decides, via a
                      per-channel per-category preference matrix. You do not
                      spam someone's phone with a marketing email they opted
                      out of.
  * HOW URGENT      : a security alert (urgent) jumps the queue and BYPASSES
                      quiet hours + rate limits; a weekly digest (low) waits.
                      Priority is a SEPARATE axis from channel.
  * IS IT A DUPE    : the same "someone liked your photo" can fire 10 times in
                      a second. Dedup via an idempotency key (event+user+type)
                      within a TTL window collapses the burst to 1.
  * DID IT ARRIVE   : at-least-once. Each channel delivery is tracked
                      (pending -> sent -> delivered | failed), retried with
                      exponential backoff, and dead-lettered after N attempts.

The NON-OBVIOUS parts this file drills into:
  1. Fan-out MULTIPLIES work. One notification to a user with 3 channels on =
     3 delivery attempts. At scale (1B/day x 3 channels x 1.5 retry) that is
     4.5B channel attempts/day. (Sections A, G)
  2. Priority queue: urgent notifications must LEAP-FROG a backlog of normal
     ones. A FIFO queue makes an urgent security alert wait behind marketing
     digests. Priority is a per-message weight, consumed highest-first.
     (Section B)
  3. Preferences are a MATRIX (channel x category), not a single on/off.
     "Push for DMs, email for mentions, nothing for marketing" requires
     intersecting the notification's channels with the user's allowed matrix.
     Effective channel count = requested INTERSECT allowed. (Section C)
  4. At-least-once delivery means the RECEIVER must be idempotent: a retried
     push may be delivered twice, so the device dedups on notification_id.
     Retries use exponential backoff (1s, 2s). (Section D)
  5. Dedup is NOT retry. Retry re-sends a FAILED delivery. Dedup prevents the
     SAME logical event from entering the pipeline twice (the producer
     double-fires). Key = (notif_id, user, type), TTL'd in Redis.
     (Section E)
  6. Rate limiting is per-USER per-CHANNEL per-WINDOW. A user can receive 100
     emails/hour and still be fine on push. Urgent notifications BYPASS the
     limiter (you always get a security alert). (Section F)

========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
========================================================================
  event          : the original happening (like, comment, system alert) that
                   should produce a notification. Producer-side concept.
  notification   : the rendered message for ONE user, possibly multi-channel.
  channel        : a delivery transport: push (FCM/APNs), email (SES/SendGrid),
                   SMS (Twilio), in_app (stored in DB, polled).
  priority       : urgent / high / normal / low. Affects queue order + bypass.
  preference     : a user's per-channel per-category opt-in/out matrix.
  fan-out        : splitting one notification into N channel deliveries.
  idempotency key: (notif_id, user, type) hash - dedupes duplicate events.
  delivery       : one attempt series to send on one channel for one user.
  status         : pending -> sent -> delivered | failed. Tracked per delivery.
  retry          : re-sending a delivery that failed, with exponential backoff.
  rate limit     : max N notifications/channel/window/user.
  DLQ            : dead-letter queue - deliveries that exhausted retries.
========================================================================
"""

from collections import defaultdict


# --------------------------------------------------------------------------
# Core model. Pure data classes, deterministic.
# --------------------------------------------------------------------------
CHANNELS = ["push", "email", "sms", "in_app"]

# Priority weights. Higher = processed first. Urgent bypasses rate limit.
PRIORITY = {"urgent": 4, "high": 3, "normal": 2, "low": 1}

MAX_RETRIES = 3          # at-least-once: up to 3 total attempts per delivery
BACKOFF_BASE = 2         # exponential backoff: 2^(n-1) s before retry n -> 1s, 2s


def backoff_delay(attempt_number):
    """Delay (seconds) BEFORE retry attempt N. Attempt 1 has no delay."""
    if attempt_number <= 1:
        return 0
    return BACKOFF_BASE ** (attempt_number - 2)


class Notification:
    """One logical notification for one user, requesting a set of channels."""
    def __init__(self, notif_id, user_id, ntype, priority, channels):
        self.notif_id = notif_id
        self.user_id = user_id
        self.ntype = ntype          # category: dm, mention, security, marketing...
        self.priority = priority
        self.channels = channels    # requested channels

    @property
    def idempotency_key(self):
        return (self.notif_id, self.user_id, self.ntype)

    def __repr__(self):
        return (f"Notification({self.notif_id}, user={self.user_id}, "
                f"type={self.ntype}, pri={self.priority}, "
                f"channels={self.channels})")


class Delivery:
    """One channel delivery for one notification. Retried up to MAX_RETRIES.

    fail_attempts : the first N attempts fail (transient), then it succeeds.
                    Models a flaky provider recovering. 0 = succeeds first try.
    hard_fail     : always fails -> exhausted retries -> DLQ.
    """
    def __init__(self, notif_id, user_id, channel, ntype,
                 fail_attempts=0, hard_fail=False):
        self.notif_id = notif_id
        self.user_id = user_id
        self.channel = channel
        self.ntype = ntype
        self.fail_attempts = fail_attempts
        self.hard_fail = hard_fail
        self.attempts = 0
        self.status = "pending"     # pending -> sent -> delivered | failed

    def deliver(self):
        """At-least-once delivery loop with exponential backoff retry.
        Returns final status: 'delivered' or 'failed'."""
        for n in range(1, MAX_RETRIES + 1):
            self.attempts = n
            self.status = "sent"    # handed to the provider
            if self.hard_fail:
                continue            # provider rejects, never confirms
            if n <= self.fail_attempts:
                continue            # transient failure on first N attempts
            self.status = "delivered"
            return "delivered"
        self.status = "failed"      # exhausted retries -> dead-letter
        return "failed"


# --------------------------------------------------------------------------
# User preference matrix. user -> {channel: set(allowed types) | "ALL"}.
# "ALL" = every category allowed on this channel. empty set = channel off.
# --------------------------------------------------------------------------
PREFERENCES = {
    "U1": {"push": "ALL", "email": "ALL",   "sms": set(),       "in_app": "ALL"},
    "U2": {"push": "ALL", "email": set(),   "sms": {"security"}, "in_app": "ALL"},
    "U3": {"push": "ALL", "email": {"mention", "system"}, "sms": set(), "in_app": "ALL"},
    "U4": {"push": "ALL", "email": "ALL",   "sms": "ALL",       "in_app": "ALL"},
}


def allowed_channel(user_id, channel, ntype):
    """Is this (user, channel, category) allowed by preferences?"""
    prefs = PREFERENCES.get(user_id, {})
    allowed = prefs.get(channel, set())
    if allowed == "ALL":
        return True
    return ntype in allowed


def effective_channels(notif):
    """Intersect requested channels with the user's preference matrix."""
    return [c for c in notif.channels if allowed_channel(notif.user_id, c, notif.ntype)]


# --------------------------------------------------------------------------
# Rate limits. Per-user per-channel per-hour. Urgent bypasses.
# --------------------------------------------------------------------------
RATE_LIMITS = {  # max notifications per channel per hour per user
    "push": 50,
    "email": 20,
    "sms": 5,
    "in_app": 100,
}


def banner(title):
    line = "=" * 72
    print()
    print(line)
    print(" " + title)
    print(line)


# --------------------------------------------------------------------------
# The scenario. 7 events arrive in this order; trace follows them through
# the whole pipeline (dedup -> priority -> preference -> fan-out -> delivery).
# --------------------------------------------------------------------------
SCENARIO_EVENTS = [
    Notification("n1", "U1", "dm",        "normal", ["push", "email"]),
    Notification("n2", "U2", "security",  "urgent", ["push", "sms"]),
    Notification("n3", "U1", "mention",   "high",   ["push", "email"]),
    Notification("n1", "U1", "dm",        "normal", ["push", "email"]),   # DUPE of E1
    Notification("n4", "U3", "marketing", "low",    ["email"]),
    Notification("n5", "U4", "system",    "normal", ["email", "sms"]),
    Notification("n6", "U1", "comment",   "normal", ["push"]),
]

# Failure schedule for deliveries (deterministic). Keyed by (notif_id, channel).
# Demonstrates: first-try success, transient-then-success (retry), hard fail (DLQ).
FAILURE_SCHEDULE = {
    ("n3", "email"): {"fail_attempts": 1},   # attempt 1 fails, attempt 2 delivers
    ("n5", "sms"):   {"hard_fail": True},    # all 3 attempts fail -> DLQ
}


def build_deliveries(notif):
    """Fan out a notification to one Delivery per effective channel."""
    out = []
    for ch in effective_channels(notif):
        fs = FAILURE_SCHEDULE.get((notif.notif_id, ch), {})
        out.append(Delivery(notif.notif_id, notif.user_id, ch, notif.ntype,
                            fail_attempts=fs.get("fail_attempts", 0),
                            hard_fail=fs.get("hard_fail", False)))
    return out


def main():
    banner("NOTIFICATION SERVICE - reference simulation "
           "(priority + fan-out + dedup + retry + rate limit)")
    print("Source of truth for NOTIFICATION_SERVICE.md and notification_service.html.")
    print("All numbers below are deterministic; re-run reproduces them.")

    # Pipeline stage 1 (runs first in reality): dedup. Details shown in Section E.
    seen_keys = set()
    deduped = []
    unique = []
    for n in SCENARIO_EVENTS:
        if n.idempotency_key in seen_keys:
            deduped.append(n)
        else:
            seen_keys.add(n.idempotency_key)
            unique.append(n)

    # ---------------------------------------------------------------------
    # SECTION A: MULTI-CHANNEL FAN-OUT
    # ---------------------------------------------------------------------
    banner("Section A - Multi-channel fan-out (1 event -> N channels)")
    print("One notification requests multiple channels. The service fans it out")
    print("into one Delivery per (effective) channel. Fan-out FACTOR = avg")
    print("channels per notification; it MULTIPLIES the delivery workload.\n")
    examples = [SCENARIO_EVENTS[0], SCENARIO_EVENTS[1], SCENARIO_EVENTS[5]]
    for n in examples:
        eff = effective_channels(n)
        print(f"  {n.notif_id} user={n.user_id} type={n.ntype:9s} "
              f"requested={n.channels}")
        print(f"      -> effective (after prefs) = {eff}   "
              f"fan-out = {len(eff)} deliveries")
    print()
    print("  >>> Fan-out is a multiplier. At 3 channels/notification the")
    print("      downstream push/email/SMS dispatchers see 3x the notification")
    print("      volume. This dominates the throughput budget (Section G).")

    # ---------------------------------------------------------------------
    # SECTION B: PRIORITY QUEUE
    # ---------------------------------------------------------------------
    banner("Section B - Priority queue (urgent leap-frogs the backlog)")
    print("Events arrive in arrival order but are CONSUMED highest-priority")
    print(f"first. Weights: " + ", ".join(f"{k}={v}" for k, v in PRIORITY.items()) + "\n")
    print("  arrival order (raw, includes the duplicate):")
    for i, n in enumerate(SCENARIO_EVENTS, 1):
        print(f"    #{i} {n.notif_id} priority={n.priority}({PRIORITY[n.priority]}) "
              f"type={n.ntype}")
    print()
    # dedup runs FIRST (Section E), then priority sort over the survivors.
    # stable sort by priority desc preserves arrival order within a tier.
    pq = sorted(unique, key=lambda n: -PRIORITY[n.priority])
    print(f"  after dedup ({len(SCENARIO_EVENTS)} -> {len(unique)} unique), "
          f"processing order (priority desc, stable):")
    for i, n in enumerate(pq, 1):
        tag = "   <-- URGENT: jumps to front" if (i == 1 and n.priority == "urgent") else ""
        print(f"    #{i} {n.notif_id} priority={n.priority}({PRIORITY[n.priority]}) "
              f"type={n.ntype}{tag}")
    print()
    print("  >>> n2 (urgent security alert, arrived 2nd) is processed FIRST.")
    print("      A FIFO queue would bury it behind n1 (normal). Priority is a")
    print("      per-message weight, not FIFO. Urgent also BYPASSES rate limits")
    print("      and quiet hours (Section F).")

    # ---------------------------------------------------------------------
    # SECTION C: USER PREFERENCE AGGREGATION
    # ---------------------------------------------------------------------
    banner("Section C - User preference aggregation (channel x category matrix)")
    print("Preferences are a MATRIX, not a single on/off. Each user sets, per")
    print("channel, which CATEGORIES are allowed. A notification's channels are")
    print("intersected with the allowed matrix -> effective channels.\n")
    print("  preference matrix:")
    for u, prefs in PREFERENCES.items():
        parts = []
        for ch in CHANNELS:
            a = prefs[ch]
            parts.append(f"{ch}=" + ("ALL" if a == "ALL" else
                                     ("{" + ",".join(sorted(a)) + "}" if a else "off")))
        print(f"    {u}: " + "  ".join(parts))
    print()
    print("  filtering the unique notifications:")
    for n in unique:
        eff = effective_channels(n)
        dropped = [c for c in n.channels if c not in eff]
        note = ""
        if not eff:
            note = "  >>> SUPPRESSED (0 effective channels)"
        elif dropped:
            note = f"  dropped={dropped}"
        print(f"    {n.notif_id} user={n.user_id} {n.ntype:9s} "
              f"requested={n.channels} -> effective={eff}{note}")
    print()
    print("  >>> n4 (marketing email to U3) is SUPPRESSED entirely: U3 allows")
    print("      email only for {mention,system}, not marketing. A single")
    print("      boolean 'email on/off' could not express this - the matrix can.")

    # ---------------------------------------------------------------------
    # SECTION D: DELIVERY GUARANTEE TRACKING (at-least-once + retry + DLQ)
    # ---------------------------------------------------------------------
    banner("Section D - Delivery tracking (at-least-once, retry, DLQ)")
    print(f"At-least-once: each delivery retries up to MAX_RETRIES={MAX_RETRIES}.")
    retry_delays = [backoff_delay(i) for i in range(2, MAX_RETRIES + 1)]
    print(f"Backoff before retries = {retry_delays} s "
          f"({BACKOFF_BASE}^(n-1) for retry n).\n")

    # Build deliveries from the priority-ordered, deduped, preference-filtered
    # pipeline and run each delivery's retry loop exactly once.
    deliveries = []
    for n in pq:
        deliveries.extend(build_deliveries(n))
    for d in deliveries:
        d.deliver()

    print("  per-delivery outcome:")
    print("    notif user channel  type      attempts  status   backoff(s)")
    print("    " + "-" * 64)
    total_attempts = 0
    delivered = 0
    failed = 0
    for d in deliveries:
        delays = [backoff_delay(n) for n in range(2, d.attempts + 1)]
        delay_str = ",".join(str(x) for x in delays) if delays else "-"
        total_attempts += d.attempts
        if d.status == "delivered":
            delivered += 1
        else:
            failed += 1
        print(f"    {d.notif_id}   {d.user_id}   {d.channel:6s}  {d.ntype:9s}"
              f"  {d.attempts}/{MAX_RETRIES}        {d.status:9s} {delay_str}")
    print()
    success_rate = (delivered / len(deliveries)) * 100 if deliveries else 0
    avg_attempts = total_attempts / len(deliveries) if deliveries else 0
    print(f"  deliveries: {len(deliveries)}   delivered: {delivered}   "
          f"failed (DLQ): {failed}")
    print(f"  total channel attempts: {total_attempts}   "
          f"success rate: {success_rate:.1f}%   "
          f"avg attempts/delivery: {avg_attempts:.2f}")
    print()
    print("  >>> n3 email: attempt 1 fails (transient), retries after 1s,")
    print("      delivers on attempt 2. The receiver MUST be idempotent because")
    print("      a retried push can arrive twice (dedup on notif_id client-side).")
    print(f"  >>> n5 sms: all {MAX_RETRIES} attempts fail -> DEAD-LETTERED. DLQ")
    print("      entries are alerted on for manual investigation. (A retried")
    print("      delivery that 'succeeds' after the user already got it is the")
    print("      classic at-least-once duplicate - hence client dedup.)")

    # ---------------------------------------------------------------------
    # SECTION E: DEDUPLICATION (idempotency key + TTL)
    # ---------------------------------------------------------------------
    banner("Section E - Deduplication (idempotency key, TTL window)")
    print("The producer can double-fire the SAME event (retry, at-least-once on")
    print("the producer side too). Dedup collapses it: key = (notif_id, user,")
    print("type), stored in a Redis SET with a short TTL (e.g. 1h). A repeat key")
    print("within the window is dropped BEFORE priority/fan-out.\n")
    print(f"  events received : {len(SCENARIO_EVENTS)}")
    print(f"  deduped (dropped): {len(deduped)}")
    for n in deduped:
        print(f"      dropped {n.notif_id} key={(n.notif_id, n.user_id, n.ntype)} "
              f"(duplicate within TTL window)")
    print(f"  unique (kept)   : {len(unique)}")
    for n in unique:
        print(f"      kept    {n.notif_id} key={(n.notif_id, n.user_id, n.ntype)}")
    print()
    print("  >>> Dedup != retry. Retry re-sends a FAILED delivery (Section D).")
    print("      Dedup prevents the SAME logical event from entering the pipeline")
    print("      twice. Without it, a producer retry would deliver n1 twice.")

    # ---------------------------------------------------------------------
    # SECTION F: PER-USER RATE LIMITING
    # ---------------------------------------------------------------------
    banner("Section F - Per-user rate limiting (urgent bypasses)")
    print("Each (user, channel) has a max notifications/hour. A burst beyond the")
    print("limit is throttled (deferred or dropped). URGENT notifications bypass")
    print("the limiter - you always get a security alert.\n")
    limit = RATE_LIMITS["push"]
    burst = 60
    urgent_after = 1
    delivered_count = 0
    throttled_count = 0
    for i in range(burst):
        if delivered_count < limit:
            delivered_count += 1
        else:
            throttled_count += 1
    # urgent bypass
    bypassed = urgent_after
    delivered_count += bypassed
    print(f"  U1 push: limit={limit}/hour, burst={burst} normal pushes + "
          f"{urgent_after} urgent")
    print(f"    normal delivered (within limit): {limit}")
    print(f"    throttled (over limit)         : {throttled_count}")
    print(f"    urgent bypassed limiter        : {bypassed}")
    print(f"    total delivered to U1 push     : {delivered_count}")
    print()
    print("  >>> Without the urgent bypass, a flooded user would MISS security")
    print("      alerts. Priority and rate-limiting interact: urgent both jumps")
    print("      the queue (Section B) AND ignores the throttle (here).")

    # ---------------------------------------------------------------------
    # SECTION G: SCALE ESTIMATION
    # ---------------------------------------------------------------------
    banner("Section G - Scale estimation (hyperscale multi-channel)")
    users = 500_000_000
    dau = 100_000_000
    notif_per_day = 1_000_000_000
    avg_channels = 3
    retry_mult = 1.5
    peak_notif_per_sec = 100_000
    bytes_per_log = 500
    bytes_per_pref = 1024
    days_per_year = 365
    print(f"  users (total)            : {users:,}")
    print(f"  DAU                      : {dau:,}")
    print(f"  notifications/day        : {notif_per_day:,}")
    print(f"  avg channels/notif       : {avg_channels} (fan-out factor)")
    print(f"  retry multiplier         : {retry_mult}x (at-least-once)")
    print(f"  peak notifications/sec   : {peak_notif_per_sec:,}")
    print()
    delivery_attempts_day = notif_per_day * avg_channels
    total_attempts_day = int(delivery_attempts_day * retry_mult)
    avg_notif_per_sec = notif_per_day / 86400
    peak_attempts_per_sec = peak_notif_per_sec * avg_channels * retry_mult
    print(f"  delivery attempts/day    : {delivery_attempts_day:,}")
    print(f"  total channel attempts/day (x{retry_mult}): {total_attempts_day:,}")
    print(f"  notifications/sec (avg)  : {avg_notif_per_sec:,.0f}")
    print(f"  attempts/sec (peak)      : {peak_attempts_per_sec:,.0f}")
    print()
    log_storage_tb = notif_per_day * bytes_per_log * days_per_year / (1000**4)
    pref_storage_gb = users * bytes_per_pref / (1000**3)
    print(f"  notification log/year    : ~{log_storage_tb:,.0f} TB "
          f"({bytes_per_log}B/log)")
    print(f"  preferences (all users)  : ~{pref_storage_gb:,.0f} GB "
          f"({bytes_per_pref}B/user, in SQL/Redis)")
    dedup_keys_peak = peak_notif_per_sec * 3600
    dedup_mem_gb = dedup_keys_peak * 40 / (1000**3)
    print(f"  dedup keys (1h TTL peak) : ~{dedup_keys_peak/1e6:,.0f}M keys "
          f"-> ~{dedup_mem_gb:,.1f} GB Redis")

    # ---------------------------------------------------------------------
    # SECTION H: [check] ASSERTIONS
    # ---------------------------------------------------------------------
    banner("Section H - [check] assertions")

    # Check 1: priority order matches expected.
    expected_order = ["n2", "n3", "n1", "n5", "n6", "n4"]
    got_order = [n.notif_id for n in pq]
    assert got_order == expected_order, \
        f"priority order mismatch: got {got_order}, expected {expected_order}"
    print(f"[check] priority: order = {','.join(got_order)} ... OK")

    # Check 2: dedup - 7 events, 1 deduped, 6 unique.
    assert len(SCENARIO_EVENTS) == 7
    assert len(deduped) == 1
    assert len(unique) == 6
    print(f"[check] dedup: 7 events -> {len(deduped)} deduped -> "
          f"{len(unique)} unique ... OK")

    # Check 3: preference suppression - n4 marketing email to U3 = 0 channels.
    n4 = SCENARIO_EVENTS[4]
    assert n4.notif_id == "n4" and n4.ntype == "marketing"
    assert effective_channels(n4) == [], "n4 must be suppressed to 0 channels"
    print(f"[check] preference: n4 marketing email to U3 suppressed "
          f"(0 effective channels) ... OK")

    # Check 4: fan-out deliveries count = 9 (after dedup + pref filter).
    assert len(deliveries) == 9, f"expected 9 deliveries, got {len(deliveries)}"
    print(f"[check] fan-out: {len(deliveries)} deliveries after dedup + pref ... OK")

    # Check 5: delivered = 8, failed (DLQ) = 1.
    assert delivered == 8, f"expected 8 delivered, got {delivered}"
    assert failed == 1, f"expected 1 failed, got {failed}"
    print(f"[check] delivery: {delivered} delivered, {failed} failed (DLQ) ... OK")

    # Check 6: total channel attempts = 12 (7 first-try + 2 n3email + 3 n5sms).
    assert total_attempts == 12, f"expected 12 attempts, got {total_attempts}"
    print(f"[check] retry: total attempts = {total_attempts} "
          f"(avg {avg_attempts:.2f}/delivery) ... OK")

    # Check 7: success rate = 88.9%.
    assert abs(success_rate - 88.9) < 0.05, f"success rate {success_rate}"
    print(f"[check] success: rate = {success_rate:.1f}% ... OK")

    # Check 8: n3 email retried exactly once (2 attempts) then delivered.
    n3email = next(d for d in deliveries
                   if d.notif_id == "n3" and d.channel == "email")
    assert n3email.attempts == 2 and n3email.status == "delivered"
    print(f"[check] retry: n3 email = {n3email.attempts} attempts -> delivered ... OK")

    # Check 9: n5 sms hard-failed to DLQ after MAX_RETRIES.
    n5sms = next(d for d in deliveries
                 if d.notif_id == "n5" and d.channel == "sms")
    assert n5sms.attempts == MAX_RETRIES and n5sms.status == "failed"
    print(f"[check] DLQ: n5 sms = {n5sms.attempts} attempts -> failed (DLQ) ... OK")

    # Check 10: backoff sequence is exponential [1, 2] (retries before attempts 2,3).
    backoffs = [backoff_delay(i) for i in range(2, MAX_RETRIES + 1)]
    assert backoffs == [1, 2], f"backoff {backoffs}"
    print(f"[check] backoff: retry delays = {backoffs} (2^(n-1)) ... OK")

    # Check 11: urgent bypasses rate limit.
    assert bypassed == 1 and delivered_count == limit + bypassed
    print(f"[check] rate-limit: urgent bypassed, U1 push delivered = "
          f"{delivered_count} ({limit}+{bypassed}) ... OK")

    # Check 12: scale math.
    assert total_attempts_day == 4_500_000_000
    assert abs(peak_attempts_per_sec - 450000) < 1
    print(f"[check] scale: attempts/day = {total_attempts_day:,}, "
          f"peak attempts/sec = {peak_attempts_per_sec:,.0f} ... OK")

    print()
    print("All [check] assertions passed. Re-run reproduces every number above.")


if __name__ == "__main__":
    main()
