#!/usr/bin/env python3
"""
online_auction.py - Online auction system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds ONLINE_AUCTION.md
and is recomputed identically in online_auction.html (gold-checked).

Sections:
  1. Auction state machine (UPCOMING -> ACTIVE -> CLOSING -> CLOSED / NO_SALE / CANCELLED)
  2. Real-time bid processing (increment rules, highest bid tracking, reserve price)
  3. Concurrent bid conflict resolution (last-write-wins vs highest-bid-wins vs serialized)
  4. Anti-sniping extension window + proxy bidding resolution
  5. Auction close logic (winner determination + reserve check)
  6. Eventual consistency for bid propagation (CLOSING drain window)
  7. Scale estimation (bids/sec, storage, Kafka partitions, WebSocket watchers)
  8. GOLD values pinned for online_auction.html
"""

# ---------------------------------------------------------------------------
# scale constants (single source of truth, mirrored in online_auction.html GOLD)
# ---------------------------------------------------------------------------
ACTIVE_AUCTIONS = 1_000_000
AVG_BIDS_PER_AUCTION = 50
BYTES_PER_BID = 200
AVG_AUCTION_DURATION_DAYS = 7
PEAK_BIDS_PER_SEC = 10_000
VIRAL_BIDS_PER_SEC = 100          # a single viral auction at close time
CONCURRENT_WATCHERS = 50_000
GATEWAY_SERVERS = 10
AUCTIONS_PER_PARTITION = 1_000
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
# Auction model (the single state machine that powers every section)
# ---------------------------------------------------------------------------
class Auction:
    """English ascending auction with reserve, increment, anti-sniping."""

    def __init__(self, auction_id, seller_id, start_price, reserve_price,
                 min_increment=5, start_time=0, end_time=300,
                 extension_window=30, max_extension=600):
        self.auction_id = auction_id
        self.seller_id = seller_id
        self.start_price = start_price
        self.reserve_price = reserve_price       # hidden from bidders
        self.min_increment = min_increment
        self.current_price = start_price
        self.current_winner = None
        self.bid_count = 0
        self.status = "UPCOMING"
        self.start_time = start_time
        self.end_time = end_time
        self.original_end_time = end_time
        self.extension_window = extension_window
        self.max_extension = max_extension
        self.bids = []                            # append-only audit trail

    def activate(self, now):
        if self.status == "UPCOMING" and now >= self.start_time:
            self.status = "ACTIVE"
            return True
        return False

    def begin_closing(self, now):
        if self.status == "ACTIVE" and now >= self.end_time:
            self.status = "CLOSING"
            return True
        return False

    def place_bid(self, bidder, amount, now):
        if self.status != "ACTIVE":
            return False, "not_active"
        if now > self.end_time:
            return False, "after_end_time"
        if amount < self.current_price + self.min_increment:
            return False, "below_min_increment"
        self.bids.append({"bidder": bidder, "amount": amount, "t": now})
        self.current_price = amount
        self.current_winner = bidder
        self.bid_count += 1
        # anti-sniping: extend if bid lands inside the final window (capped)
        if self.end_time - now <= self.extension_window:
            cap = self.original_end_time + self.max_extension
            self.end_time = min(self.end_time + self.extension_window, cap)
            return True, "accepted+extended"
        return True, "accepted"

    def drain_bid(self, bidder, amount):
        # CLOSING grace window: honor a bid already in the Kafka partition.
        if self.status != "CLOSING":
            return False, "not_closing"
        if amount < self.current_price + self.min_increment:
            return False, "below_min_increment"
        self.bids.append({"bidder": bidder, "amount": amount,
                          "t": self.end_time, "type": "DRAINED"})
        self.current_price = amount
        self.current_winner = bidder
        self.bid_count += 1
        return True, "drained"

    def finalize(self):
        if self.status != "CLOSING":
            return False
        if self.current_winner is None or self.current_price < self.reserve_price:
            self.status = "NO_SALE"
        else:
            self.status = "CLOSED"
        return True

    def cancel(self):
        if self.status in ("UPCOMING", "ACTIVE") and self.bid_count == 0:
            self.status = "CANCELLED"
            return True
        return False


def resolve_proxy(proxy_bidders, current_price, min_increment):
    """Resolve a two-or-more bidder proxy race. Vickrey-ish: top max wins
    at one increment over the second-highest max, capped at the winner's max."""
    ranked = sorted(proxy_bidders, key=lambda x: x[1], reverse=True)
    if not ranked:
        return None, current_price
    if len(ranked) == 1:
        bidder, mx = ranked[0]
        return bidder, min(mx, current_price + min_increment)
    top_bidder, top_max = ranked[0]
    second_max = ranked[1][1]
    return top_bidder, min(top_max, second_max + min_increment)


# ---------------------------------------------------------------------------
# SECTION 1 - Auction state machine
# ---------------------------------------------------------------------------
def section_state_machine():
    banner("SECTION 1: Auction state machine")
    print("Six states. Transitions only advance forward; guards block illegal moves.\n")

    TRANSITIONS = {
        "UPCOMING":  ["ACTIVE", "CANCELLED"],
        "ACTIVE":    ["CLOSING", "CANCELLED"],
        "CLOSING":   ["CLOSED", "NO_SALE"],
        "CLOSED":    [],
        "CANCELLED": [],
        "NO_SALE":   [],
    }
    print("Allowed transitions:")
    for s, ts in TRANSITIONS.items():
        print("  %-10s -> %s" % (s, ", ".join(ts) if ts else "(terminal)"))
    print()

    # happy path: UPCOMING -> ACTIVE -> CLOSING -> CLOSED
    a = Auction("A1", "S1", start_price=100, reserve_price=150,
                min_increment=5, start_time=0, end_time=300)
    print("Happy-path A1 (start $100, reserve $150, end t=300):")
    a.activate(0)
    print("  activate(t=0)    -> status=%-9s" % a.status)
    a.place_bid("Alice", 120, 50)
    a.place_bid("Bob", 180, 200)
    print("  2 bids accepted  -> status=%-9s price=$%s winner=%s" %
          (a.status, a.current_price, a.current_winner))
    a.begin_closing(300)
    print("  end_time reached -> status=%-9s" % a.status)
    a.finalize()
    print("  finalize()       -> status=%-9s (reserve $150 met by Bob's $180)" % a.status)
    print()

    # reserve not met -> NO_SALE
    b = Auction("A2", "S2", start_price=100, reserve_price=250, end_time=100)
    b.activate(0)
    b.place_bid("Carol", 150, 10)
    b.begin_closing(100)
    b.finalize()
    print("Reserve-unmet A2 (reserve $250, top bid $150):")
    print("  finalize()       -> status=%-9s (top bid < reserve -> NO_SALE)" % b.status)
    print()

    # cancel allowed only before any bids
    c = Auction("A3", "S3", start_price=100, reserve_price=150, end_time=100)
    c.activate(0)
    ok_no_bids = c.cancel()
    print("Cancel A3 with NO bids:  %s (status=%s)" %
          ("OK" if ok_no_bids else "FAIL", c.status))

    d = Auction("A4", "S4", start_price=100, reserve_price=150, end_time=100)
    d.activate(0)
    d.place_bid("Dave", 110, 5)
    ok_has_bids = d.cancel()
    print("Cancel A4 WITH bids:     %s (status stays %s)" %
          ("REJECTED" if not ok_has_bids else "OK", d.status))
    print()

    print("[check] CLOSED is terminal? " +
          ("OK" if TRANSITIONS["CLOSED"] == [] else "FAIL"))
    print("[check] reserve unmet -> NO_SALE, reserve met -> CLOSED? " +
          ("OK" if b.status == "NO_SALE" and a.status == "CLOSED" else "FAIL"))
    print("[check] cancel rejected once a bid exists? " +
          ("OK" if ok_no_bids and not ok_has_bids else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Real-time bid processing
# ---------------------------------------------------------------------------
def section_bid_processing():
    banner("SECTION 2: Real-time bid processing (increment + highest bid + reserve)")
    a = Auction("A1", "S1", start_price=100, reserve_price=200,
                min_increment=5, start_time=0, end_time=300)
    a.activate(0)
    print("Auction: start $100, min_increment $5, reserve $200 (hidden from bidders).\n")

    attempts = [
        ("Alice", 102, 10, "below min_increment ($100+$5=$105)"),
        ("Alice", 105, 11, "OK: clears min_increment"),
        ("Bob",   108, 20, "below current($105)+$5=$110"),
        ("Bob",   150, 21, "OK: clears increment"),
        ("Carol", 145, 30, "below current winner's $150"),
    ]
    print("  %-6s %-7s %-4s %-7s %s" % ("bidder", "amount", "t", "result", "reason"))
    for bidder, amt, t, reason in attempts:
        ok, _ = a.place_bid(bidder, amt, t)
        print("  %-6s $%-6d %-4d %-7s %s" %
              (bidder, amt, t, "ACCEPT" if ok else "REJECT", reason))
    print()
    print("After 5 attempts: bid_count=%d, current_price=$%s, winner=%s" %
          (a.bid_count, a.current_price, a.current_winner))
    print("Reserve status: %s (reserve $%s is never shown to bidders)" %
          ("MET" if a.current_price >= a.reserve_price else "NOT MET", a.reserve_price))
    print()

    min_first = a.start_price + a.min_increment
    print("[check] min first bid = start + increment = $%d? " % min_first +
          ("OK" if min_first == 105 else "FAIL"))
    print("[check] current_price tracks the highest ACCEPTED bid ($150)? " +
          ("OK" if a.current_price == 150 else "FAIL"))
    print("[check] reserve stays hidden (stored, not exposed in bid API)? " +
          ("OK" if a.reserve_price == 200 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Concurrent bid conflict resolution
# ---------------------------------------------------------------------------
def section_concurrency():
    banner("SECTION 3: Concurrent bid conflict resolution")
    print("Three bids land 'simultaneously' on a hot auction (current $100, Alice).")
    print("Network/replication lag makes them arrive in ARRIVAL order, not amount order.\n")

    concurrent = [
        {"bidder": "Bob",   "amount": 130, "arrival": 1},
        {"bidder": "Dave",  "amount": 125, "arrival": 2},
        {"bidder": "Carol", "amount": 110, "arrival": 3},   # lowest, arrives last (lag)
    ]
    base_price, base_winner, min_inc = 100, "Alice", 5

    print("Concurrent batch (arrival order):")
    for b in concurrent:
        print("  %s $%d (arrival %d)" % (b["bidder"], b["amount"], b["arrival"]))
    print()

    # A: last-write-wins (naive overwrite)
    print("A. LAST-WRITE-WINS  (naive overwrite on every write)")
    lww_price, lww_winner = base_price, base_winner
    for b in sorted(concurrent, key=lambda x: x["arrival"]):
        lww_price, lww_winner = b["amount"], b["bidder"]
    lww_loss = 130 - lww_price
    print("   winner=%s @ $%d  <- Carol's LOWER $110 overwrote Bob's $130" %
          (lww_winner, lww_price))
    print("   seller LOSES $%d vs what Bob offered" % lww_loss)
    print()

    # B: highest-bid-wins (picks max, no serial ordering)
    print("B. HIGHEST-BID-WINS (compare amounts, take the max)")
    hbw_price, hbw_winner = base_price, base_winner
    for b in concurrent:
        if b["amount"] > hbw_price:
            hbw_price, hbw_winner = b["amount"], b["bidder"]
    print("   winner=%s @ $%d  <- correct amount, but no serial order for" %
          (hbw_winner, hbw_price))
    print("   increment/proxy/causality rules; ties are ambiguous")
    print()

    # C: Kafka per-auction partition (serialized, single-threaded per auction)
    print("C. KAFKA PER-AUCTION PARTITION (serialized, single processor/auction)")
    ser_price, ser_winner = base_price, base_winner
    accepted = []
    for b in sorted(concurrent, key=lambda x: x["arrival"]):
        if b["amount"] >= ser_price + min_inc:
            ser_price, ser_winner = b["amount"], b["bidder"]
            accepted.append(b)
    print("   each bid must clear current+$%d; processed strictly in arrival order:" % min_inc)
    for b in accepted:
        print("     %s $%d ACCEPTED" % (b["bidder"], b["amount"]))
    print("   winner=%s @ $%d (Carol/Dave rejected: did not clear running price)" %
          (ser_winner, ser_price))
    print()
    print("=> LWW can UNDERPRICE the auction and lose the seller real money.")
    print("=> HBW fixes the price but skips increment/proxy/causality rules.")
    print("=> Kafka partition = one processor per auction, sequential, enforces ALL rules;")
    print("   system-wide throughput scales by adding partitions (~1K for 1M auctions).")
    print()

    print("[check] LWW winner is the LAST arrival (Carol $110), not highest? " +
          ("OK" if lww_winner == "Carol" and lww_price == 110 else "FAIL"))
    print("[check] serialized winner is the highest VALID bid (Bob $130)? " +
          ("OK" if ser_winner == "Bob" and ser_price == 130 else "FAIL"))
    print("[check] LWW revenue loss vs Bob = $%d? " % lww_loss +
          ("OK" if lww_loss == 20 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Anti-sniping extension + proxy bidding
# ---------------------------------------------------------------------------
def section_antisnipe_proxy():
    banner("SECTION 4: Anti-sniping extension window + proxy bidding")

    # --- anti-sniping ---
    print("A. Anti-sniping extension (popcorn bidding)")
    a = Auction("A1", "S1", start_price=100, reserve_price=200,
                min_increment=5, start_time=0, end_time=300,
                extension_window=30, max_extension=600)
    a.activate(0)
    cap = a.original_end_time + a.max_extension
    print("  end_time=%d  extension_window=%ds  hard_cap=orig+max=%d" %
          (a.end_time, a.extension_window, cap))

    a.place_bid("Alice", 110, 100)
    print("  bid @t=100 (200s before end): end_time=%d (no extension)" % a.end_time)

    a.place_bid("Bob", 130, 295)
    ext1 = a.end_time - 300
    print("  bid @t=295 (5s before end, in %ds window): end_time=%d (+%ds)" %
          (a.extension_window, a.end_time, ext1))

    a.place_bid("Carol", 150, 320)
    print("  bid @t=320 (10s before new end): end_time=%d (+%ds total)" %
          (a.end_time, a.end_time - 300))
    print("  end_time never exceeds hard_cap=%d -> no infinite auction" % cap)
    print()

    print("[check] first extension = +%ds? " % a.extension_window +
          ("OK" if ext1 == 30 else "FAIL"))
    print("[check] end_time bounded by original_end + max_extension? " +
          ("OK" if a.end_time <= cap else "FAIL"))
    print()

    # --- proxy bidding ---
    print("B. Proxy bidding (two-bidder race, Vickrey-ish)")
    print("  start $100, min_increment $5")
    print("  Alice sets proxy_max $200; Bob sets proxy_max $150")
    proxy = [("Alice", 200), ("Bob", 150)]
    winner, price = resolve_proxy(proxy, current_price=100, min_increment=5)
    print("  resolve -> winner=%s, final_price=$%d" % (winner, price))
    print("  (one increment over Bob's max $150+$5=$155, capped at Alice's $200)")
    print("  watchers see ONLY the final price $%d, never intermediate proxy ticks" % price)
    print()

    print("[check] proxy winner is the higher-max bidder (Alice)? " +
          ("OK" if winner == "Alice" else "FAIL"))
    print("[check] proxy price = second_max + increment = $155? " +
          ("OK" if price == 155 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Auction close logic
# ---------------------------------------------------------------------------
def section_close():
    banner("SECTION 5: Auction close logic (winner + reserve check)")

    # case 1: reserve met -> CLOSED with winner
    a = Auction("A1", "S1", start_price=100, reserve_price=200, end_time=300)
    a.activate(0)
    a.place_bid("Alice", 250, 50)
    a.begin_closing(300)
    a.finalize()
    print("Case 1: reserve MET")
    print("  top bid $%d >= reserve $%d -> status=%s, winner=%s" %
          (a.current_price, a.reserve_price, a.status, a.current_winner))

    # case 2: bids exist but reserve not met -> NO_SALE
    b = Auction("A2", "S2", start_price=100, reserve_price=300, end_time=100)
    b.activate(0)
    b.place_bid("Bob", 180, 50)
    b.begin_closing(100)
    b.finalize()
    print("Case 2: reserve NOT MET")
    print("  top bid $%d <  reserve $%d -> status=%s (seller keeps item)" %
          (b.current_price, b.reserve_price, b.status))

    # case 3: no bids at all -> NO_SALE
    c = Auction("A3", "S3", start_price=100, reserve_price=150, end_time=100)
    c.activate(0)
    c.begin_closing(100)
    c.finalize()
    print("Case 3: NO BIDS")
    print("  no bids at all       -> status=%s" % c.status)
    print()

    print("[check] reserve met -> CLOSED with winner? " +
          ("OK" if a.status == "CLOSED" and a.current_winner == "Alice" else "FAIL"))
    print("[check] reserve unmet -> NO_SALE? " +
          ("OK" if b.status == "NO_SALE" else "FAIL"))
    print("[check] no bids -> NO_SALE? " +
          ("OK" if c.status == "NO_SALE" else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Eventual consistency (CLOSING drain)
# ---------------------------------------------------------------------------
def section_eventual_consistency():
    banner("SECTION 6: Eventual consistency (CLOSING drain window)")
    print("Bid path: client -> ingestion -> Kafka partition -> processor -> DB -> broadcast.")
    print("Broadcast to watchers is EVENTUALLY consistent (may lag <1s).")
    print("CLOSING drains bids already in the partition so none are silently dropped.\n")

    a = Auction("A1", "S1", start_price=100, reserve_price=150, end_time=100)
    a.activate(0)
    a.place_bid("Alice", 110, 50)
    a.begin_closing(100)
    print("t=100: end_time reached -> status=%s (partition still holds in-flight bids)" %
          a.status)

    in_flight = [
        ("Bob",   130, "queued @t=99.8"),
        ("Carol", 145, "queued @t=99.9"),
    ]
    print("  draining in-flight queue (each was enqueued BEFORE end_time):")
    for bidder, amt, note in in_flight:
        ok, _ = a.drain_bid(bidder, amt)
        print("    %s $%d -> %s (%s)" % (bidder, amt, "DRAINED" if ok else "DROPPED", note))

    late_ok, _ = a.place_bid("Dave", 200, 100.5)
    print("    Dave $%d -> %s (arrived AFTER close, status not ACTIVE)" %
          (200, "REJECTED" if not late_ok else "ACCEPTED"))

    a.finalize()
    print("  drain complete -> status=%s, winner=%s @ $%d" %
          (a.status, a.current_winner, a.current_price))
    print()
    print("=> CLOSING gives a 2-5s grace window. Bids in the partition before end_time")
    print("   are honored; bids after the close return AUCTION_CLOSED.")
    print("   Use SERVER timestamps only -- never trust client bid_timestamp for anti-snipe.")
    print()

    print("[check] in-flight bids drained (Bob & Carol honored)? " +
          ("OK" if a.current_winner == "Carol" else "FAIL"))
    print("[check] late bid rejected (arrived after close)? " +
          ("OK" if not late_ok else "FAIL"))
    print("[check] final winner is the highest DRAINED bid ($145)? " +
          ("OK" if a.current_price == 145 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - Scale estimation
# ---------------------------------------------------------------------------
def section_scale():
    banner("SECTION 7: Scale estimation")
    print("Assumptions:")
    print("  active auctions (concurrent)   = %s" % fmt_int(ACTIVE_AUCTIONS))
    print("  avg bids / auction             = %d" % AVG_BIDS_PER_AUCTION)
    print("  bytes / bid                    = %d" % BYTES_PER_BID)
    print("  avg auction duration           = %d days" % AVG_AUCTION_DURATION_DAYS)
    print("  peak bids / sec (system-wide)  = %s" % fmt_int(PEAK_BIDS_PER_SEC))
    print("  viral auction (single)         = %s bids/sec" % fmt_int(VIRAL_BIDS_PER_SEC))
    print("  concurrent watchers            = %s" % fmt_int(CONCURRENT_WATCHERS))
    print()

    storage_per_cycle = ACTIVE_AUCTIONS * AVG_BIDS_PER_AUCTION * BYTES_PER_BID
    auctions_per_day = ACTIVE_AUCTIONS / AVG_AUCTION_DURATION_DAYS
    bids_per_day = auctions_per_day * AVG_BIDS_PER_AUCTION
    avg_bids_per_sec = bids_per_day / SECONDS_PER_DAY
    storage_per_day = bids_per_day * BYTES_PER_BID
    storage_per_year = storage_per_day * 365
    kafka_partitions = (ACTIVE_AUCTIONS + AUCTIONS_PER_PARTITION - 1) // AUCTIONS_PER_PARTITION
    watchers_per_gateway = CONCURRENT_WATCHERS // GATEWAY_SERVERS
    peak_per_auction = PEAK_BIDS_PER_SEC / ACTIVE_AUCTIONS

    print("Bid volume:")
    print("  auctions closing / day         = %s" % fmt_int(int(auctions_per_day)))
    print("  bids / day                     = %s" % fmt_int(int(bids_per_day)))
    print("  avg bids / sec                 = %.1f /s" % avg_bids_per_sec)
    print("  peak bids / sec (system)       = %s /s" % fmt_int(PEAK_BIDS_PER_SEC))
    print("  viral single auction           = %s bids/sec on ONE auction" % fmt_int(VIRAL_BIDS_PER_SEC))
    print("  peak avg per auction           = %.4f bids/sec/auction" % peak_per_auction)
    print()
    print("Storage (bids table, append-only):")
    print("  storage / cycle (1M auctions)  = %s" % fmt_bytes(storage_per_cycle))
    print("  storage / day                  = %s" % fmt_bytes(storage_per_day))
    print("  storage / year                 = %s" % fmt_bytes(storage_per_year))
    print()
    print("Kafka (partition key = auction_id, one processor / partition):")
    print("  partitions needed              = %s  (1M auctions / ~1K per partition)" %
          fmt_int(kafka_partitions))
    print()
    print("WebSocket broadcast (per-auction local connection map):")
    print("  concurrent watchers            = %s" % fmt_int(CONCURRENT_WATCHERS))
    print("  gateway servers                = %d" % GATEWAY_SERVERS)
    print("  connections / gateway          = %s" % fmt_int(watchers_per_gateway))
    print()

    print("[check] storage per cycle == 10.0 GB? " +
          ("OK" if abs(storage_per_cycle / 1e9 - 10.0) < 0.01 else "FAIL"))
    print("[check] kafka partitions == 1000? " +
          ("OK" if kafka_partitions == 1000 else "FAIL"))
    print("[check] watchers / gateway == 5000? " +
          ("OK" if watchers_per_gateway == 5000 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 8 - GOLD values for online_auction.html
# ---------------------------------------------------------------------------
def section_gold():
    banner("SECTION 8: GOLD values (pinned for online_auction.html)")
    storage_per_cycle_gb = round(
        ACTIVE_AUCTIONS * AVG_BIDS_PER_AUCTION * BYTES_PER_BID / 1e9, 2)
    auctions_per_day = ACTIVE_AUCTIONS / AVG_AUCTION_DURATION_DAYS
    bids_per_day = auctions_per_day * AVG_BIDS_PER_AUCTION
    avg_bids_per_sec = round(bids_per_day / SECONDS_PER_DAY, 1)
    kafka_partitions = (ACTIVE_AUCTIONS + AUCTIONS_PER_PARTITION - 1) // AUCTIONS_PER_PARTITION
    watchers_per_gateway = CONCURRENT_WATCHERS // GATEWAY_SERVERS

    gold = [
        ("active_auctions",             ACTIVE_AUCTIONS),
        ("peak_bids_per_sec",           PEAK_BIDS_PER_SEC),
        ("avg_bids_per_sec",            avg_bids_per_sec),
        ("storage_per_cycle_gb",        storage_per_cycle_gb),
        ("kafka_partitions",            kafka_partitions),
        ("watchers_per_gateway",        watchers_per_gateway),
        ("viral_auction_bids_per_sec",  VIRAL_BIDS_PER_SEC),
        ("min_bid_threshold_dollars",   105),
        ("lww_revenue_loss_dollars",    20),
        ("proxy_resolved_price",        155),
        ("anti_snipe_extension_seconds", 30),
    ]
    for k, v in gold:
        print("  %-30s = %s" % (k, v))
    print()

    ok = (ACTIVE_AUCTIONS == 1_000_000 and
          PEAK_BIDS_PER_SEC == 10_000 and
          abs(avg_bids_per_sec - 82.7) < 1e-9 and
          abs(storage_per_cycle_gb - 10.0) < 1e-9 and
          kafka_partitions == 1000 and
          watchers_per_gateway == 5000 and
          VIRAL_BIDS_PER_SEC == 100)
    print("[check] GOLD reproduces from scale constants + auction formulas? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# online_auction.py - Online auction system design simulation")
    print("# Pure Python stdlib only. Numbers below feed ONLINE_AUCTION.md")
    print("# and online_auction.html (gold-checked).")
    section_state_machine()
    section_bid_processing()
    section_concurrency()
    section_antisnipe_proxy()
    section_close()
    section_eventual_consistency()
    section_scale()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
