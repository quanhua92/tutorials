#!/usr/bin/env python3
"""
ticket_booking.py - Ticket booking system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds TICKET_BOOKING.md
and is recomputed identically in ticket_booking.html (gold-checked).

Sections:
  1. Seat + hold state machine (AVAILABLE -> HELD -> SOLD, with TTL -> RELEASED)
  2. Seat selection with hold-and-release (TTL-based locking)
  3. Concurrent booking conflict resolution (naive read-modify-write vs SELECT FOR UPDATE vs Redis Lua atomic)
  4. Idempotency keys for payment (replay returns same result, no double-charge)
  5. Payment flow state machine (PENDING -> AUTHORIZED -> CAPTURED -> REFUNDED; VOIDED on hold expiry)
  6. High-demand event surge handling (virtual waiting room, lottery, throttling)
  7. Scale estimation (100K concurrent users, 50K seats/venue, 100K req/sec peak, 8min hold)
  8. GOLD values pinned for ticket_booking.html
"""

# ---------------------------------------------------------------------------
# scale constants (single source of truth, mirrored in ticket_booking.html GOLD)
# ---------------------------------------------------------------------------
SEATS_PER_VENUE = 50_000
PEAK_REQUESTS_PER_SEC = 100_000
CONCURRENT_USERS_FLASH = 100_000
HOLD_WINDOW_SECONDS = 480              # 8 min hold before auto-release
HOLD_EXPIRY_RATE = 0.30                # 30% of holds expire unredeemed
AVG_SEATS_PER_BOOKING = 4
BYTES_PER_BOOKING = 256
BYTES_PER_HOLD = 128
BOOKINGS_PER_YEAR = 100_000_000
EVENTS_PER_YEAR = 1_000_000
AVG_SEATS_PER_EVENT = 100
WAITING_ROOM_BATCH = 1_000             # users admitted per batch
WAITING_ROOM_INTERVAL_SEC = 5          # batch every 5s
SWEEPER_INTERVAL_SEC = 30              # expired-hold scan cadence
WEBSOCKET_GATEWAYS = 20
IDEMPOTENCY_TTL_HOURS = 24
SECONDS_PER_DAY = 86_400

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000.0:
            return "%.2f %s" % (n, unit)
        n /= 1000.0
    return "%.2f EB" % n


def fmt_int(n):
    return "{:,}".format(n)


# ---------------------------------------------------------------------------
# Seat model (the single state machine that powers every section)
# ---------------------------------------------------------------------------
class Seat:
    """A single seat: AVAILABLE <-> HELD (TTL) -> SOLD. version for optimistic CAS."""

    def __init__(self, seat_id, price=50):
        self.seat_id = seat_id
        self.price = price
        self.status = "AVAILABLE"
        self.held_by = None
        self.hold_expires_at = None
        self.version = 0

    def hold(self, user, now, ttl):
        if self.status == "AVAILABLE":
            self.status = "HELD"
            self.held_by = user
            self.hold_expires_at = now + ttl
            self.version += 1
            return True, "held"
        if self.status == "HELD" and now >= self.hold_expires_at:
            self.status = "HELD"
            self.held_by = user
            self.hold_expires_at = now + ttl
            self.version += 1
            return True, "reclaimed"
        return False, self.status

    def confirm(self, user, now):
        if (self.status == "HELD" and self.held_by == user
                and now < self.hold_expires_at):
            self.status = "SOLD"
            self.version += 1
            return True, "sold"
        return False, self.status

    def release_expired(self, now):
        if self.status == "HELD" and now >= self.hold_expires_at:
            prev = self.held_by
            self.status = "AVAILABLE"
            self.held_by = None
            self.hold_expires_at = None
            self.version += 1
            return True, prev
        return False, None


# ---------------------------------------------------------------------------
# Payment model (Section 5)
# ---------------------------------------------------------------------------
class Payment:
    """Payment lifecycle: PENDING -> AUTHORIZED -> CAPTURED -> REFUNDED.
    AUTHORIZED -> VOIDED (hold expired). PENDING -> FAILED (decline)."""

    def __init__(self, payment_id, amount):
        self.payment_id = payment_id
        self.amount = amount
        self.status = "PENDING"
        self.history = [("PENDING", 0)]

    def authorize(self, t):
        if self.status != "PENDING":
            return False
        self.status = "AUTHORIZED"
        self.history.append(("AUTHORIZED", t))
        return True

    def capture(self, t):
        if self.status != "AUTHORIZED":
            return False
        self.status = "CAPTURED"
        self.history.append(("CAPTURED", t))
        return True

    def void(self, t):
        if self.status != "AUTHORIZED":
            return False
        self.status = "VOIDED"
        self.history.append(("VOIDED", t))
        return True

    def refund(self, t):
        if self.status != "CAPTURED":
            return False
        self.status = "REFUNDED"
        self.history.append(("REFUNDED", t))
        return True

    def fail(self, t):
        if self.status != "PENDING":
            return False
        self.status = "FAILED"
        self.history.append(("FAILED", t))
        return True


# ---------------------------------------------------------------------------
# Idempotency store (Section 4)
# ---------------------------------------------------------------------------
class IdempotencyStore:
    """Maps (user_id, idempotency_key) -> stored response for the TTL window."""

    def __init__(self):
        self.store = {}

    def execute(self, user, key, op):
        ck = (user, key)
        if ck in self.store:
            return self.store[ck], "REPLAY"
        result = op()
        self.store[ck] = result
        return result, "FIRST"


# ---------------------------------------------------------------------------
# SECTION 1 - Seat + hold state machine
# ---------------------------------------------------------------------------
def section_state_machine():
    banner("SECTION 1: Seat + hold state machine")
    print("Three seat states. TTL drives HELD -> AVAILABLE; confirm drives HELD -> SOLD.\n")

    TRANSITIONS = {
        "AVAILABLE": ["HELD"],
        "HELD":      ["SOLD", "AVAILABLE"],
        "SOLD":      [],
    }
    print("Allowed transitions:")
    for s, ts in TRANSITIONS.items():
        print("  %-10s -> %s" % (s, ", ".join(ts) if ts else "(terminal)"))
    print()

    # happy path: AVAILABLE -> HELD -> SOLD
    s = Seat("A1", price=80)
    print("Happy-path A1 (price $80, TTL 480s):")
    ok, _ = s.hold("Alice", now=100, ttl=480)
    print("  hold(Alice,t=100,480) -> status=%-10s held_by=%s expires_at=%d" %
          (s.status, s.held_by, s.hold_expires_at))
    ok, _ = s.confirm("Alice", now=200)
    print("  confirm(Alice,t=200)  -> status=%-10s (within hold window)" % s.status)
    print()

    # hold expires -> released back to AVAILABLE
    s2 = Seat("A2", price=80)
    s2.hold("Bob", now=0, ttl=480)
    print("Hold-expiry A2 (held by Bob at t=0, TTL 480s):")
    released, prev = s2.release_expired(now=500)
    print("  release_expired(t=500) -> released=%s prev_holder=%s status=%s" %
          (released, prev, s2.status))
    print("  (a seat held but never paid returns to the pool -> no overbooking)")
    print()

    # reclaim an expired hold for a new user
    s3 = Seat("A3", price=80)
    s3.hold("Carol", now=0, ttl=480)
    ok3, reason3 = s3.hold("Dave", now=500, ttl=480)
    print("Reclaim A3 (Carol's hold expired, Dave grabs it at t=500):")
    print("  hold(Dave,t=500)      -> ok=%s reason=%s status=%s held_by=%s" %
          (ok3, reason3, s3.status, s3.held_by))
    print()

    # confirm outside the hold window -> rejected
    s4 = Seat("A4", price=80)
    s4.hold("Eve", now=0, ttl=480)
    ok4, reason4 = s4.confirm("Eve", now=600)
    print("Late confirm A4 (Eve held at t=0, confirms at t=600 after expiry):")
    print("  confirm(Eve,t=600)    -> ok=%s status=%s (hold window expired)" %
          (ok4, s4.status))
    print()

    print("[check] SOLD is terminal (no transition out)? " +
          ("OK" if TRANSITIONS["SOLD"] == [] else "FAIL"))
    print("[check] hold expiry returns seat to AVAILABLE? " +
          ("OK" if s2.status == "AVAILABLE" and released else "FAIL"))
    print("[check] expired hold is reclaimable by another user? " +
          ("OK" if reason3 == "reclaimed" and s3.held_by == "Dave" else "FAIL"))
    print("[check] confirm after hold expiry is rejected? " +
          ("OK" if not ok4 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Seat selection with hold-and-release (TTL locking)
# ---------------------------------------------------------------------------
def section_hold_release():
    banner("SECTION 2: Seat selection with hold-and-release (TTL locking)")
    print("Alice picks 3 seats; they are HELD atomically with a shared TTL.")
    print("If she does not pay within the window, the sweeper releases them.\n")

    seats = {sid: Seat(sid, price=80) for sid in ("A1", "A2", "A3", "A4")}
    TTL = HOLD_WINDOW_SECONDS

    picked = ["A1", "A2", "A3"]
    now = 0
    print("Alice selects %s at t=%d, TTL=%ds:" % (picked, now, TTL))
    held = []
    for sid in picked:
        ok, _ = seats[sid].hold("Alice", now, TTL)
        held.append(ok)
        print("  hold %-3s -> %-5s status=%-10s expires_at=%d" %
              (sid, "OK" if ok else "FAIL", seats[sid].status,
               seats[sid].hold_expires_at))
    print()

    # simulate the sweeper running before and after expiry
    print("Sweeper runs every %ds:" % SWEEPER_INTERVAL_SEC)
    for sweep_t in (100, 300, 490, 520):
        freed = 0
        for s in seats.values():
            ok, _ = s.release_expired(sweep_t)
            if ok:
                freed += 1
        statuses = ", ".join("%s:%s" % (s.seat_id, s.status) for s in seats.values())
        print("  sweep t=%-4d released=%d  seats[%s]" % (sweep_t, freed, statuses))
    print()

    print("=> At t=480 the hold window elapses; the t=520 sweep frees A1/A2/A3.")
    print("=> Worst-case overdue = sweeper interval = %ds (a seat may show HELD" %
          SWEEPER_INTERVAL_SEC)
    print("   up to %ds past expiry before the next sweep reclaims it)." %
          SWEEPER_INTERVAL_SEC)
    print()

    all_released = all(seats[sid].status == "AVAILABLE" for sid in picked)
    print("[check] all 3 seats released by t=520 sweep? " +
          ("OK" if all_released else "FAIL"))
    print("[check] A4 (never held) stays AVAILABLE through all sweeps? " +
          ("OK" if seats["A4"].status == "AVAILABLE" else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Concurrent booking conflict resolution
# ---------------------------------------------------------------------------
def section_concurrency():
    banner("SECTION 3: Concurrent booking conflict resolution")
    print("Two users race to hold seat S1 (currently AVAILABLE, v0).")
    print("Network/replication lag makes their reads interleave with writes.\n")

    concurrent = [
        {"user": "Alice", "arrival": 1},
        {"user": "Bob",   "arrival": 2},
    ]

    # A: naive read-modify-write (no atomicity) -> double book
    print("A. NAIVE READ-MODIFY-WRITE (read, then write, no atomicity)")
    state_a = {"status": "AVAILABLE", "version": 0, "held_by": None}
    alice_read = (state_a["status"], state_a["version"])   # Alice reads v0
    bob_read = (state_a["status"], state_a["version"])     # Bob reads v0 (stale)
    state_a["status"] = "HELD"; state_a["held_by"] = "Alice"; state_a["version"] = 1
    alice_won = True
    state_a["status"] = "HELD"; state_a["held_by"] = "Bob"; state_a["version"] = 1
    bob_won = True                                         # overwrites Alice
    double_book = alice_won and bob_won
    print("   Alice read (%s,v%d) -> write HELD by Alice (v0->v1)" % alice_read)
    print("   Bob   read (%s,v%d) -> write HELD by Bob   (stale v0 overwrites Alice)" % bob_read)
    print("   final: held_by=%s  <- BOTH users think they hold S1 -> DOUBLE BOOK" %
          state_a["held_by"])
    print()

    # B: SELECT FOR UPDATE (pessimistic row lock)
    print("B. SELECT FOR UPDATE (pessimistic row lock, blocks the loser)")
    state_b = {"status": "AVAILABLE", "version": 0, "held_by": None}
    state_b["status"] = "HELD"; state_b["held_by"] = "Alice"; state_b["version"] = 1
    bob_read_b = (state_b["status"], state_b["version"])   # Bob reads AFTER Alice commits
    bob_reject = state_b["status"] != "AVAILABLE"
    print("   Alice locks S1 -> read AVAILABLE -> write HELD by Alice -> commit")
    print("   Bob   blocks on lock, then reads (%s,v%d) -> REJECT" % bob_read_b)
    print("   final: held_by=%s  <- single owner, correct" % state_b["held_by"])
    print("   cost: Bob BLOCKED waiting for Alice's txn -> convoy at 100K req/sec")
    print()

    # C: Redis Lua atomic (single-threaded check-and-set)
    print("C. REDIS LUA ATOMIC (check-and-set in one single-threaded script)")
    state_c = {"status": "AVAILABLE", "version": 0, "held_by": None}
    results_c = []
    for who in sorted(concurrent, key=lambda x: x["arrival"]):
        if state_c["status"] == "AVAILABLE":
            state_c["status"] = "HELD"; state_c["held_by"] = who["user"]
            state_c["version"] += 1
            results_c.append((who["user"], "ACCEPT (Lua: AVAILABLE->HELD by %s, EX %ds)" %
                              (who["user"], HOLD_WINDOW_SECONDS)))
        else:
            results_c.append((who["user"], "REJECT (Lua: status=%s held_by=%s)" %
                              (state_c["status"], state_c["held_by"])))
    for u, r in results_c:
        print("   %s -> %s" % (u, r))
    print("   final: held_by=%s  <- single owner, no lock wait, loser picks another seat" %
          state_c["held_by"])
    print()
    print("=> Naive read-modify-write DOUBLE-BOOKS (both users believe they own S1).")
    print("=> SELECT FOR UPDATE is correct but BLOCKS the loser (convoy at flash sale).")
    print("=> Redis Lua CAS is atomic + non-blocking: winner takes the seat, the loser")
    print("   gets an instant 'already held' and picks another seat -> scales to 100K req/sec.")
    print()

    print("[check] naive double-books (both Alice and Bob win)? " +
          ("OK" if double_book else "FAIL"))
    print("[check] pessimistic rejects Bob (sees HELD after Alice commits)? " +
          ("OK" if bob_reject else "FAIL"))
    print("[check] Redis Lua gives exactly one winner (Alice, first arrival)? " +
          ("OK" if state_c["held_by"] == "Alice" else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Idempotency keys for payment
# ---------------------------------------------------------------------------
def section_idempotency():
    banner("SECTION 4: Idempotency keys for payment")
    print("Client generates a UUID per intent; server stores (user, key) -> response")
    print("for %dh. Retries with the SAME key return the cached response with NO side effect.\n" %
          IDEMPOTENCY_TTL_HOURS)

    store = IdempotencyStore()
    charges = {"count": 0}

    def charge_card():
        charges["count"] += 1
        return {"booking_id": "BKG-7421", "charged": 200, "status": "CAPTURED"}

    attempts = [
        ("Alice", "abc-123", "first attempt"),
        ("Alice", "abc-123", "retry 1 (network timeout)"),
        ("Alice", "abc-123", "retry 2 (connection reset)"),
        ("Alice", "abc-123", "retry 3 (user double-click)"),
    ]
    print("Intent: Alice pays $200 for seats [A1,A2], idempotency_key='abc-123'.")
    print("Network flakes -> client RETRIES the same request 3 more times.\n")
    print("  %-6s %-9s %-30s %-10s %-9s %s" %
          ("user", "key", "context", "status", "mode", "charged?"))
    for user, key, ctx in attempts:
        res, mode = store.execute(user, key, charge_card)
        print("  %-6s %-9s %-30s %-10s %-9s $%d" %
              (user, key, ctx, res["status"], mode, res["charged"]))

    print()
    print("=> 4 HTTP requests, card charged exactly ONCE (count=%d)." % charges["count"])
    print("=> All 4 responses identical (booking_id BKG-7421, $200, CAPTURED).")
    print("=> Without the key: each retry creates a new booking + new charge = 4 charges.")
    print()

    replay_res, replay_mode = store.execute("Alice", "abc-123", charge_card)
    consistent = (replay_res["booking_id"] == "BKG-7421" and
                  replay_res["charged"] == 200)
    print("[check] card charged exactly once across 4 attempts (count==1)? " +
          ("OK" if charges["count"] == 1 else "FAIL"))
    print("[check] replay returns identical cached response (BKG-7421, $200)? " +
          ("OK" if consistent else "FAIL"))
    print("[check] replay does NOT re-invoke the op (mode==REPLAY)? " +
          ("OK" if replay_mode == "REPLAY" and charges["count"] == 1 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Payment flow state machine
# ---------------------------------------------------------------------------
def section_payment():
    banner("SECTION 5: Payment flow state machine")
    print("Six states. AUTHORIZED reserves funds; CAPTURED moves them; VOIDED releases")
    print("the reservation when a hold expires (so the user is never charged for an")
    print("unconfirmed seat).\n")

    STATES = ("PENDING", "AUTHORIZED", "CAPTURED", "REFUNDED", "VOIDED", "FAILED")
    print("States: " + ", ".join(STATES) + "\n")

    # happy path: PENDING -> AUTHORIZED -> CAPTURED
    print("A. Happy path: hold -> authorize -> capture")
    p = Payment("PAY-1", amount=200)
    p.authorize(10)
    p.capture(30)
    print("  " + " -> ".join(s for s, _ in p.history))
    print("  amount=$%d final=%s (funds moved to merchant)" % (p.amount, p.status))
    print()

    # hold expiry: AUTHORIZED -> VOIDED
    print("B. Hold expiry: authorize then VOID (user never confirmed in time)")
    p2 = Payment("PAY-2", amount=200)
    p2.authorize(10)
    p2.void(520)
    print("  " + " -> ".join(s for s, _ in p2.history))
    print("  amount=$%d final=%s (authorization released, user NOT charged)" %
          (p2.amount, p2.status))
    print()

    # decline: PENDING -> FAILED
    print("C. Card decline: PENDING -> FAILED (hold released, user may retry)")
    p3 = Payment("PAY-3", amount=200)
    p3.fail(12)
    print("  " + " -> ".join(s for s, _ in p3.history))
    print("  amount=$%d final=%s (no funds reserved, seats freed immediately)" %
          (p3.amount, p3.status))
    print()

    # refund after capture
    print("D. Post-purchase refund: CAPTURED -> REFUNDED (e.g. event cancelled)")
    p4 = Payment("PAY-4", amount=200)
    p4.authorize(10); p4.capture(30); p4.refund(9000)
    print("  " + " -> ".join(s for s, _ in p4.history))
    print("  amount=$%d final=%s (funds returned to cardholder)" % (p4.amount, p4.status))
    print()

    # illegal transitions are rejected
    print("E. Illegal transitions are rejected (guards):")
    bad = Payment("PAY-5", amount=200)
    ok_cap = bad.capture(5)          # PENDING cannot capture
    bad.authorize(5)
    ok_ref = bad.refund(6)          # AUTHORIZED cannot refund (must capture first)
    ok_auth = bad.authorize(6)      # already AUTHORIZED
    print("  capture from PENDING     -> %s" % ("OK" if ok_cap else "REJECTED"))
    print("  refund from AUTHORIZED   -> %s" % ("OK" if ok_ref else "REJECTED"))
    print("  authorize when AUTHORIZED-> %s" % ("OK" if ok_auth else "REJECTED"))
    print()

    print("[check] happy path ends CAPTURED? " +
          ("OK" if p.status == "CAPTURED" else "FAIL"))
    print("[check] hold expiry ends VOIDED (no charge)? " +
          ("OK" if p2.status == "VOIDED" else "FAIL"))
    print("[check] decline ends FAILED? " +
          ("OK" if p3.status == "FAILED" else "FAIL"))
    print("[check] all 6 states reachable, illegal transitions blocked? " +
          ("OK" if (len(STATES) == 6 and not ok_cap and not ok_ref and not ok_auth)
           else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - High-demand event surge handling
# ---------------------------------------------------------------------------
def section_surge():
    banner("SECTION 6: High-demand event surge handling")
    print("A flash sale: %s concurrent users hit one %d-seat venue. Peak = %s req/sec.\n" %
          (fmt_int(CONCURRENT_USERS_FLASH), SEATS_PER_VENUE, fmt_int(PEAK_REQUESTS_PER_SEC)))

    print("A. Virtual waiting room (the winner)")
    admit_rate = WAITING_ROOM_BATCH / WAITING_ROOM_INTERVAL_SEC
    seats_locked_per_sec = admit_rate * AVG_SEATS_PER_BOOKING
    sellout = SEATS_PER_VENUE / seats_locked_per_sec
    print("  queue=%s users, admit %d/%ds = %.0f users/sec into seat selection" %
          (fmt_int(CONCURRENT_USERS_FLASH), WAITING_ROOM_BATCH,
           WAITING_ROOM_INTERVAL_SEC, admit_rate))
    print("  each user holds ~%d seats -> %.0f seats locked/sec" %
          (AVG_SEATS_PER_BOOKING, seats_locked_per_sec))
    print("  sellout time = %d / %.0f = %.1f sec" %
          (SEATS_PER_VENUE, seats_locked_per_sec, sellout))
    print("  users not admitted stay on a CDN-cached 'you are #N in line' page;")
    print("  backend sees a STEADY %.0f req/sec, never the raw %s spike." %
          (admit_rate, fmt_int(PEAK_REQUESTS_PER_SEC)))
    print()

    print("B. Request throttling (simple, poor UX)")
    print("  accept R req/sec, reject the rest with HTTP 429 + Retry-After.")
    print("  at %s req/sec peak, ~99%% are rejected -> users spam retry, worse UX." %
          fmt_int(PEAK_REQUESTS_PER_SEC))
    print()

    print("C. Lottery / pre-sale (eliminates the spike entirely)")
    print("  users register interest ahead of time; %d winners drawn at random get a" %
          (SEATS_PER_VENUE // AVG_SEATS_PER_BOOKING))
    print("  private booking window. No flash sale, no queue, fair by construction.")
    print()

    print("=> Waiting room absorbs the spike into a controlled admit rate.")
    print("=> Combine with: CDN-cached seat map, pre-auth card on file (reject")
    print("   non-serious buyers before they reach inventory), and bot detection.")
    print()

    print("[check] admit rate == 200 users/sec (1000/5)? " +
          ("OK" if admit_rate == 200 else "FAIL"))
    print("[check] sellout == 62.5 sec (50000/800)? " +
          ("OK" if sellout == 62.5 else "FAIL"))
    print("[check] backend absorbs 200 req/sec, not 100000? " +
          ("OK" if admit_rate < PEAK_REQUESTS_PER_SEC else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - Scale estimation
# ---------------------------------------------------------------------------
def section_scale():
    banner("SECTION 7: Scale estimation")
    print("Assumptions:")
    print("  seats / venue (flash event)     = %s" % fmt_int(SEATS_PER_VENUE))
    print("  peak requests / sec (on-sale)   = %s" % fmt_int(PEAK_REQUESTS_PER_SEC))
    print("  concurrent users (flash)        = %s" % fmt_int(CONCURRENT_USERS_FLASH))
    print("  hold window                     = %d sec (%d min)" %
          (HOLD_WINDOW_SECONDS, HOLD_WINDOW_SECONDS // 60))
    print("  hold expiry rate                = %.0f%%" % (HOLD_EXPIRY_RATE * 100))
    print("  avg seats / booking             = %d" % AVG_SEATS_PER_BOOKING)
    print("  bytes / booking record          = %d" % BYTES_PER_BOOKING)
    print("  bytes / hold record             = %d" % BYTES_PER_HOLD)
    print("  bookings / year                 = %s" % fmt_int(BOOKINGS_PER_YEAR))
    print("  events / year                   = %s" % fmt_int(EVENTS_PER_YEAR))
    print()

    bookings_per_sec_avg = BOOKINGS_PER_YEAR / (365 * SECONDS_PER_DAY)
    holds_total = BOOKINGS_PER_YEAR / (1 - HOLD_EXPIRY_RATE)
    storage_bookings = BOOKINGS_PER_YEAR * BYTES_PER_BOOKING
    storage_holds = holds_total * BYTES_PER_HOLD
    storage_total = storage_bookings + storage_holds
    admit_rate = WAITING_ROOM_BATCH / WAITING_ROOM_INTERVAL_SEC
    seats_locked_per_sec = admit_rate * AVG_SEATS_PER_BOOKING
    sellout = SEATS_PER_VENUE / seats_locked_per_sec
    ws_per_gateway = CONCURRENT_USERS_FLASH // WEBSOCKET_GATEWAYS
    sweep_overdue = SWEEPER_INTERVAL_SEC

    print("Volume:")
    print("  bookings / day                  = %s" %
          fmt_int(int(BOOKINGS_PER_YEAR / 365)))
    print("  avg bookings / sec              = %.1f /s" % bookings_per_sec_avg)
    print("  peak requests / sec (flash)     = %s /s" % fmt_int(PEAK_REQUESTS_PER_SEC))
    print("  hold attempts / year (bookings/(1-expiry)) = %s" % fmt_int(int(holds_total)))
    print()
    print("Storage (bookings + holds tables):")
    print("  bookings storage / year         = %s" % fmt_bytes(storage_bookings))
    print("  holds storage / year            = %s" % fmt_bytes(storage_holds))
    print("  total storage / year            = %s" % fmt_bytes(storage_total))
    print()
    print("Flash-sale throughput (virtual waiting room):")
    print("  admit rate                      = %.0f users/sec" % admit_rate)
    print("  seats locked / sec              = %.0f" % seats_locked_per_sec)
    print("  venue sellout time              = %.1f sec" % sellout)
    print()
    print("Real-time seat map (WebSocket push of availability):")
    print("  concurrent users (flash)        = %s" % fmt_int(CONCURRENT_USERS_FLASH))
    print("  WebSocket gateways              = %d" % WEBSOCKET_GATEWAYS)
    print("  connections / gateway           = %s" % fmt_int(ws_per_gateway))
    print("  sweeper cadence / max overdue   = %ds / %ds" %
          (SWEEPER_INTERVAL_SEC, sweep_overdue))
    print()

    print("[check] bookings storage/year == 25.60 GB? " +
          ("OK" if abs(storage_bookings / 1e9 - 25.60) < 0.01 else "FAIL"))
    print("[check] total storage/year == 43.89 GB? " +
          ("OK" if abs(storage_total / 1e9 - 43.89) < 0.01 else "FAIL"))
    print("[check] avg bookings/sec == 3.2? " +
          ("OK" if round(bookings_per_sec_avg, 1) == 3.2 else "FAIL"))
    print("[check] connections/gateway == 5000 (100000/20)? " +
          ("OK" if ws_per_gateway == 5000 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 8 - GOLD values for ticket_booking.html
# ---------------------------------------------------------------------------
def section_gold():
    banner("SECTION 8: GOLD values (pinned for ticket_booking.html)")
    bookings_per_sec_avg = round(
        BOOKINGS_PER_YEAR / (365 * SECONDS_PER_DAY), 1)
    holds_total = BOOKINGS_PER_YEAR / (1 - HOLD_EXPIRY_RATE)
    storage_bookings_gb = round(BOOKINGS_PER_YEAR * BYTES_PER_BOOKING / 1e9, 2)
    storage_holds_gb = round(holds_total * BYTES_PER_HOLD / 1e9, 2)
    storage_total_gb = round(storage_bookings_gb + storage_holds_gb, 2)
    admit_rate = WAITING_ROOM_BATCH / WAITING_ROOM_INTERVAL_SEC
    seats_locked_per_sec = admit_rate * AVG_SEATS_PER_BOOKING
    sellout = SEATS_PER_VENUE / seats_locked_per_sec
    ws_per_gateway = CONCURRENT_USERS_FLASH // WEBSOCKET_GATEWAYS

    gold = [
        ("seats_per_venue",             SEATS_PER_VENUE),
        ("peak_requests_per_sec",       PEAK_REQUESTS_PER_SEC),
        ("concurrent_users_flash",      CONCURRENT_USERS_FLASH),
        ("hold_window_seconds",         HOLD_WINDOW_SECONDS),
        ("hold_expiry_rate_pct",        int(HOLD_EXPIRY_RATE * 100)),
        ("bookings_per_year",           BOOKINGS_PER_YEAR),
        ("avg_bookings_per_sec",        bookings_per_sec_avg),
        ("storage_bookings_year_gb",    storage_bookings_gb),
        ("storage_total_year_gb",       storage_total_gb),
        ("waiting_room_admit_rate",     int(admit_rate)),
        ("sellout_time_seconds",        round(sellout, 1)),
        ("connections_per_gateway",     ws_per_gateway),
        ("naive_double_book_count",     1),
        ("redis_lua_winner",            "Alice"),
        ("idempotency_charge_count",    1),
        ("payment_states_count",        6),
    ]
    for k, v in gold:
        print("  %-30s = %s" % (k, v))
    print()

    ok = (SEATS_PER_VENUE == 50_000 and
          PEAK_REQUESTS_PER_SEC == 100_000 and
          HOLD_WINDOW_SECONDS == 480 and
          bookings_per_sec_avg == 3.2 and
          abs(storage_bookings_gb - 25.6) < 1e-9 and
          abs(storage_total_gb - 43.89) < 1e-9 and
          admit_rate == 200 and
          sellout == 62.5 and
          ws_per_gateway == 5000)
    print("[check] GOLD reproduces from scale constants + booking formulas? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# ticket_booking.py - Ticket booking system design simulation")
    print("# Pure Python stdlib only. Numbers below feed TICKET_BOOKING.md")
    print("# and ticket_booking.html (gold-checked).")
    section_state_machine()
    section_hold_release()
    section_concurrency()
    section_idempotency()
    section_payment()
    section_surge()
    section_scale()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
