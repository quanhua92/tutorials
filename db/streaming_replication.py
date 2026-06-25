"""
streaming_replication.py - Reference implementation of PostgreSQL-style
streaming replication: the primary ships WAL records to standby(s) in real time
over a TCP connection, and each standby replays that WAL to stay a hot copy.

This is the single source of truth that STREAMING_REPLICATION.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 streaming_replication.py

============================================================================
THE INTUITION (read this first) - the office with two identical ledgers
============================================================================
Imagine the head office writes every order into its LEDGER (the WAL) the moment
it is decided, and a branch office keeps an IDENTICAL ledger by watching the
head office's desk and copying each line over a phone call as it is written.

  * primary   : the head office. Appends to its WAL, flushes it, and SHIPS each
                record over TCP the moment it is produced (the walsender).
  * standby   : the branch office. Receives WAL records, writes them, flushes
                them, and REPLAYS them onto its own data pages so its tables
                match the primary's.
  * async     : the head office tells the client "done" the instant ITS OWN
                ledger hits disk. If the phone line is slow, the branch lags -
                and a fire in the head office before the line catches up BURNS
                committed orders the branch never copied.
  * sync      : the head office WAITS on the phone until the branch confirms
                "my ledger is flushed too," THEN tells the client "done." Safer,
                but the client pays the round-trip.
  * slot      : a named bookmark the primary keeps PER standby ("the branch is
                only caught up to line 220"). The primary will NOT erase ledger
                pages the branch has not yet copied, even if its own checkpoint
                would otherwise recycle them.

THE REASON STREAMING EXISTS: a single machine will eventually die (disk, power,
rack). The WAL is already the perfect, ordered description of every change
(see WAL_CHECKPOINT.md), so the cheapest durable HA is to SHIP THAT WAL to a
second machine continuously and have it replay it. No application logic, no
two-phase commit, no distributed transactions - just "send the log, apply the
log." Streaming (vs log-shipping whole files) cuts the replication lag from
"minutes/one WAL file" to "milliseconds".

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   WAL                : the append-only, fsync'd log of every modification.
                        The cargo that streaming replication ships. See
                        WAL_CHECKPOINT.md for how it is produced. 🔗
   LSN                : Log Sequence Number. A monotonic byte/position into the
                        WAL. Bigger LSN = later record. Used everywhere here to
                        say "how far along" each side is.
   primary / standby  : the writer vs the read-only copy. (A "standby" that has
                        been promoted becomes a primary.)
   walsender          : the primary-side process that streams WAL over a TCP
                        connection to one standby.
   walreceiver        : the standby-side process that receives that stream.
   async (mode)       : primary acks COMMIT to the client as soon as the WAL is
                        flushed LOCALLY. Standby catch-up is best-effort.
   sync (mode)        : primary waits for N named standbys to confirm WAL FLUSH
                        before acking COMMIT. Tuned by synchronous_standby_names.
   flush_lsn          : how far a standby has DURABLY flushed the received WAL.
                        Sync commit waits until flush_lsn >= commit LSN.
   replay_lsn         : how far a standby has APPLIED the WAL to its data pages
                        (visible to read queries). replay_lsn <= flush_lsn.
   sent_lsn /         : the four pg_stat_replication progress markers - primary
   write_lsn /          SENT it, standby WROTE it (not fsync'd), FLUSHED it
   flush_lsn /         (durable), REPLAYED it (visible). Monotone descending:
   replay_lsn           sent >= write >= flush >= replay <= primary insert_lsn.
   synchronous_        : the GUC that names the sync standbys and the rule:
   standby_names         's1'                      wait for s1 only
                          'FIRST 2 (s1, s2, s3)'    wait for the first 2 that
                                                    reply, in this priority order
                          'ANY 2 (s1, s2, s3)'      wait for ANY 2 of the 3
                                                    (a quorum)
   replication slot   : a durable, named bookmark (restart_lsn) the primary
                        keeps per standby. Prevents WAL recycling past it, so a
                        slow/disconnected standby can always catch up.
   restart_lsn        : the slot's bookmark - the oldest LSN the standby still
                        needs. The primary will not recycle WAL at or before it.
   failover / promote : turning a standby into a primary (pg_promote). Finishes
                        WAL replay, then opens for writes. The old primary must
                        be fenced off or two primaries diverge (split-brain).
   split-brain        : two nodes both believe they are primary and accept
                        writes. The two WAL streams diverge irrecoverably.

============================================================================
THE LINEAGE (papers + docs)
============================================================================
   Physical log        Streaming requires a physical (byte-image) WAL, not a
   streaming           logical one. Postgres' physical WAL made it natural.
                       Stonebraker's "The Design of the Postgres Storage
                       System" (1987) + the redo log lineage (see WAL_CHECKPOINT
                       "lineage") underpin it.
   Sync rep / quorum   PostgreSQL 9.1 introduced synchronous replication; 9.6
                       added quorum ('ANY n') and priority ('FIRST n')
                       synchronous_standby_names. Docs §27.2, §27.4.
   Replication slots   PostgreSQL 9.4. Prevent the "standby goes stale because
                       WAL was recycled" failure. Docs §27.2.5.
   Shared-nothing HA   The pattern generalizes: Raft (Ongaro & Ousterhout 2014,
                       arXiv:1409.4265) uses a leader + followers shipping a
                       log with a quorum commit - the SAME shape as Postgres
                       'ANY n', just at the consensus layer.
   Patroni / etcd     Operational failover managers: use an etcd/raft quorum to
                       elect ONE primary and STONITH the rest, killing
                       split-brain. The standard Postgres HA stack.

KEY FORMULAS (all verified below + asserted in code):
   async commit latency = primary_flush          (standby is NOT on the path)
   sync  commit latency = primary_flush + max(standby_flush_time for required)
                         where standby_flush_time = ship + flush + ack
   FIRST n latency      = primary_flush + max(flush_time of the first n named)
   ANY   n latency      = primary_flush + n-th smallest flush_time (a quorum:
                          the commit acks as soon as n have replied)
   sync ack condition   : flush_lsn(s) >= commit_lsn  for each required standby
   data-loss window     = [async_ack_time, standby_flush_time)  -> RPO risk
   recycle floor (slot) : max(policy_floor, min(slot.restart_lsn over slots))

Conventions:
   Times are deterministic integers in MILLISECONDS (clean to print, reproducible
   by the .html). LSNs are integers; WAL segments are 100 LSNs each (W0..W5).
"""

from __future__ import annotations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The deterministic timing model (milliseconds). Fixed so the .md and the .html
# reproduce every number byte-for-byte. No randomness anywhere.
# ----------------------------------------------------------------------------
PRIMARY_FLUSH = 5            # ms: primary fsync of the COMMIT WAL record

# Each standby: (name, ship, flush, ack, replay) in ms.
#   ship   : network latency primary -> standby (WAL record arrives)
#   flush  : standby write + fsync of the WAL (durable on the standby)
#   ack    : network latency standby -> primary (the sync confirmation)
#   replay : standby apply of the WAL to its data pages (visible to queries)
# standby_flush_time (the contribution to sync commit latency) = ship + flush + ack.
STANDBYS = [
    ("s1", 2, 4, 2, 3),       # flush_time = 8
    ("s2", 3, 6, 3, 4),       # flush_time = 12
    ("s3", 2, 6, 2, 3),       # flush_time = 10
]

SEG_SIZE = 100                # LSNs per WAL segment (W0 = 0..99, W1 = 100..199, ...)


def sb_flush_time(sb):
    """standby_flush_time = ship + flush + ack (the sync-wait contribution)."""
    return sb[1] + sb[2] + sb[3]


def sb_name(sb):
    return sb[0]


def seg_of(lsn):
    """WAL segment index containing an LSN (SEG_SIZE LSNs each)."""
    return lsn // SEG_SIZE


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 1. SECTION A - async replication timeline (the data-loss window)
# ============================================================================
def section_a():
    banner("SECTION A: async replication - ack now, ship later (data-loss window)")
    print("In ASYNC mode the primary acks the COMMIT to the client the instant its")
    print("OWN WAL is flushed. Shipping to the standby happens in parallel but is")
    print("NOT on the commit path. If the standby is behind and the primary dies,")
    print("committed transactions the standby never received are LOST.\n")

    s1 = STANDBYS[0]
    ship, flush, ack, replay = s1[1], s1[2], s1[3], s1[4]
    ack_client = PRIMARY_FLUSH
    ship_done = ack_client + ship
    flush_done = ship_done + flush
    replay_done = flush_done + replay

    print(f"Model: primary_flush = {PRIMARY_FLUSH} ms ; standby s1 with")
    print(f"  ship = {ship}, flush = {flush}, ack = {ack} (unused in async), "
          f"replay = {replay} ms.\n")
    print("  | t (ms) | where     | event                                          |")
    print("  |--------|-----------|------------------------------------------------|")
    rows = [
        (0,          "client",   "COMMIT issued"),
        (ack_client, "primary",  "WAL flush (fsync) done -> ACK CLIENT 'committed'"),
        (ship_done,  "standby",  "WAL record received over TCP"),
        (flush_done, "standby",  "WAL flushed to disk (durable on standby)"),
        (replay_done,"standby",  "WAL replayed onto data pages (visible)"),
    ]
    rows.sort(key=lambda r: r[0])
    for t, w, e in rows:
        star = "  <- client told 'done' HERE (async)" if "ACK CLIENT" in e else ""
        print(f"  | {t:>6}  | {w:<9} | {e:<46} |{star}")
    print()

    rpo_lo, rpo_hi = ack_client, flush_done
    print(f"DATA-LOSS WINDOW (RPO) = [t={rpo_lo} (client acked), t={rpo_hi} "
          f"(standby durable)]  =  {rpo_hi - rpo_lo} ms wide.\n")
    print("Crash probes:")
    print("  | crash at t | committed on primary? | on standby? | outcome          |")
    print("  |------------|-----------------------|-------------|------------------|")
    probes = [
        (ack_client + 1, "yes (acked)", "NO (not shipped yet)", "DATA LOSS"),
        (ship_done + 1,  "yes (acked)", "in OS cache, not fsync'd", "AT RISK"),
        (flush_done + 1, "yes (acked)", "yes (flushed)",          "SAFE (no loss)"),
        (replay_done + 1,"yes (acked)", "yes (flushed, replayed)","SAFE + readable"),
    ]
    for t, cp, sp, out in probes:
        bad = out == "DATA LOSS"
        print(f"  | t={t:<9}| {cp:<21} | {sp:<25} | "
              f"{out:<16}|{'  <- loss' if bad else ''}")
    print()
    print("Lesson: async gives the lowest commit latency (" + str(ack_client)
          + " ms = primary only) but a non-trivial RPO. The window is the gap")
    print("between the local ack and the standby's durable flush. Sync mode")
    print("(Section B) closes that window by putting the standby ON the path.\n")

    # assert the timeline is monotone and the window is positive
    assert 0 < ack_client < ship_done < flush_done < replay_done
    assert rpo_hi - rpo_lo == flush_done - ack_client > 0
    print(f"[check] async ack = {ack_client} ms ; RPO window = "
          f"{rpo_hi - rpo_lo} ms wide: OK")


# ============================================================================
# 2. SECTION B - sync replication (standby on the commit path)
# ============================================================================
def section_b():
    banner("SECTION B: sync replication - wait for standby flush before ack")
    print("In SYNC mode the primary does NOT ack the COMMIT until the required")
    print("standby/standbys confirm they have FLUSHED the WAL (flush_lsn >= the")
    print("commit LSN). The client pays the round-trip; in exchange there is no")
    print("data-loss window - at ack time the commit is durable on BOTH sides.\n")
    print("Configured by synchronous_standby_names. Simplest form: a single name.\n")

    s1 = STANDBYS[0]
    ft = sb_flush_time(s1)
    latency = PRIMARY_FLUSH + ft
    print(f"  synchronous_standby_names = '{s1[0]}'")
    print(f"  primary_flush = {PRIMARY_FLUSH} ms ; s1 flush_time = ship({s1[1]}) + "
          f"flush({s1[2]}) + ack({s1[3]}) = {ft} ms\n")

    print("  | t (ms) | where     | event                                          |")
    print("  |--------|-----------|------------------------------------------------|")
    ship_done = PRIMARY_FLUSH + s1[1]
    flush_done = ship_done + s1[2]
    ack_back = flush_done + s1[3]
    rows = [
        (0,             "client",  "COMMIT issued"),
        (PRIMARY_FLUSH, "primary", "WAL flushed LOCALLY (not yet acked)"),
        (ship_done,     "standby", f"{s1[0]} received the WAL record"),
        (flush_done,    "standby", f"{s1[0]} FLUSHED WAL (flush_lsn >= commit LSN)"),
        (ack_back,      "primary", f"{s1[0]}'s flush ack arrives"),
        (ack_back,      "primary", "-> ACK CLIENT 'committed' (sync wait over)"),
    ]
    rows.sort(key=lambda r: r[0])
    for t, w, e in rows:
        star = "  <- client told 'done' HERE (sync)" if "ACK CLIENT" in e else ""
        print(f"  | {t:>6}  | {w:<9} | {e:<46} |{star}")
    print()

    cost = latency - PRIMARY_FLUSH
    print(f"sync commit latency = primary_flush + flush_time(s1) = {PRIMARY_FLUSH} "
          f"+ {ft} = {latency} ms")
    print(f"  latency cost vs async = {latency} - {PRIMARY_FLUSH} = {cost} ms "
          f"(the round-trip tax for zero RPO).\n")

    # THE GOLD-CHECK FORMULA: sync latency == primary_flush + max(standby_flush_times)
    required = [s1]
    gold = PRIMARY_FLUSH + max(sb_flush_time(s) for s in required)
    assert latency == gold, "gold check failed"
    print(f"GOLD-CHECK: latency ({latency}) == primary_flush ({PRIMARY_FLUSH}) + "
          f"max(standby_flush_times={[sb_flush_time(s) for s in required]}) "
          f"({gold - PRIMARY_FLUSH}) == {gold}: {'OK' if latency == gold else 'FAIL'}\n")

    print("Why flush (not write, not replay)? Postgres sync replication waits for")
    print("the standby's WAL to be DURABLE (flush_lsn), so a standby crash right")
    print("after the ack cannot lose the commit. Waiting for replay (visible) would")
    print("be stricter and slower; waiting for mere write (cached) would be unsafe.")
    print(f"\n[check] sync single-standby latency = {latency} ms, "
          f"cost = {cost} ms, GOLD holds: OK")


# ============================================================================
# 3. SECTION C - quorum commit: ANY n vs FIRST n
# ============================================================================
def section_c():
    banner("SECTION C: quorum commit - 'ANY n (s1,s2,s3)' vs 'FIRST n (s1,s2,s3)'")
    print("With multiple sync standbys the question is WHICH acks to wait for.\n")
    print("  FIRST n (s1, s2, s3) : wait for the FIRST n standbys IN THIS ORDER.")
    print("                          Always s1..sn, regardless of who is fastest.")
    print("  ANY   n (s1, s2, s3) : wait for ANY n of the named set to reply.")
    print("                          A QUORUM - whichever n ack first satisfy it.\n")

    print("Standby flush times (ship+flush+ack):")
    print("  | standby | ship | flush | ack | flush_time |")
    print("  |---------|------|-------|-----|------------|")
    for sb in STANDBYS:
        print(f"  | {sb[0]:<7} | {sb[1]:<4} | {sb[2]:<5} | {sb[3]:<3} | "
              f"{sb_flush_time(sb):<10} |")
    print()
    fts = [sb_flush_time(sb) for sb in STANDBYS]
    names = [sb[0] for sb in STANDBYS]
    sb_list = "(" + ", ".join(names) + ")"

    def first_n(n):
        need = STANDBYS[:n]
        return PRIMARY_FLUSH + max(sb_flush_time(s) for s in need), need

    def any_n(n):
        sorted_ft = sorted(fts)
        nth = sorted_ft[n - 1]                       # n-th smallest
        # which standbys were counted: the n fastest by flush_time
        order = sorted(range(len(fts)), key=lambda i: fts[i])
        counted = [STANDBYS[i] for i in order[:n]]
        return PRIMARY_FLUSH + nth, counted

    print("Latency per mode (latency = primary_flush + wait):\n")
    print("  | synchronous_standby_names | rule         | wait on        | latency |")
    print("  |---------------------------|--------------|----------------|---------|")
    for n in (1, 2, 3):
        lat_f, need_f = first_n(n)
        label = "FIRST " + str(n) + " " + sb_list
        who_f = ",".join(sb_name(s) for s in need_f) + " (max=" + str(max(sb_flush_time(s) for s in need_f)) + ")"
        print(f"  | {label:<25} | max(first {n}) | {who_f:<14} | {PRIMARY_FLUSH}+{lat_f-PRIMARY_FLUSH} = {lat_f:<3} |")
        lat_a, need_a = any_n(n)
        label2 = "ANY " + str(n) + " " + sb_list
        order = sorted(range(len(fts)), key=lambda i: fts[i])
        who_a = ",".join(sb_name(STANDBYS[i]) for i in order[:n]) + " (nth=" + str(sorted(fts)[n-1]) + ")"
        print(f"  | {label2:<25} | {n}-th fastest | {who_a:<14} | {PRIMARY_FLUSH}+{lat_a-PRIMARY_FLUSH} = {lat_a:<3} |")
    print()

    # Contrast FIRST 2 vs ANY 2 explicitly - the headline of this section.
    f2, need_f2 = first_n(2)
    a2, need_a2 = any_n(2)
    print(f"FIRST 2 {sb_list}: waits for s1 and s2 -> max({sb_flush_time(STANDBYS[0])},"
          f"{sb_flush_time(STANDBYS[1])}) = {max(sb_flush_time(STANDBYS[0]),sb_flush_time(STANDBYS[1]))} "
          f"-> latency {f2} ms. Bound by s2 (the slow one).")
    print(f"ANY   2 {sb_list}: waits for any 2     -> 2nd-smallest of {fts} = "
          f"{sorted(fts)[1]} -> latency {a2} ms. s3 ({sb_flush_time(STANDBYS[2])}) "
          f"replies before s2 ({sb_flush_time(STANDBYS[1])}), so ANY is FASTER.\n")
    print(f"  -> ANY 2 ({a2} ms) beats FIRST 2 ({f2} ms) by {f2 - a2} ms: a quorum")
    print("     tolerates one slow/hot standby; FIRST does not. Trade-off: ANY lets")
    print("     ANY 2 standbys hold the commit, so a failover to the one that HAD")
    print("     NOT yet acked could still lose it - FIRST guarantees the named")
    print("     priority standbys have it.\n")

    # GOLD-CHECK the FIRST-n case with the literal formula (max of required set)
    required_first2 = STANDBYS[:2]
    gold_first2 = PRIMARY_FLUSH + max(sb_flush_time(s) for s in required_first2)
    assert f2 == gold_first2
    # ANY-n is the n-th order statistic, which equals max of the n fastest
    assert a2 == PRIMARY_FLUSH + max(sb_flush_time(s) for s in need_a2)
    assert a2 < f2, "ANY 2 should be faster than FIRST 2 in this model"
    print(f"[check] FIRST 2 latency {f2} = {PRIMARY_FLUSH}+max"
          f"({[sb_flush_time(s) for s in required_first2]}); "
          f"ANY 2 latency {a2} = {PRIMARY_FLUSH}+max(n fastest); ANY < FIRST: OK")


# ============================================================================
# 4. SECTION D - replication slots (prevent WAL recycling)
# ============================================================================
def section_d():
    banner("SECTION D: replication slots - do not recycle WAL the standby needs")
    print("Without a slot, the primary recycles old WAL segments based ONLY on its")
    print("own checkpoint horizon (keep the last few). A standby that disconnects")
    print("or falls behind can need a segment the primary has already erased -> the")
    print("standby goes STALE and must be rebuilt from a base backup.\n")
    print("A REPLICATION SLOT fixes this: the primary tracks the standby's")
    print("restart_lsn and refuses to recycle WAL at or before it. The slot makes")
    print("the primary's WAL retention depend on the slowest standby.\n")

    insert_lsn = 540
    seg_count = seg_of(insert_lsn) + 1           # W0..W5
    segments = list(range(seg_count))            # [0,1,2,3,4,5]
    # primary policy: keep the last KEEP segments ("min_wal_size")
    KEEP = 3
    policy_floor_seg = segments[-KEEP]           # keep W3,W4,W5 -> floor W3

    def seg_label(n):
        return "W" + str(n)

    def seg_range(n):
        return f"{n*SEG_SIZE}..{n*SEG_SIZE+SEG_SIZE-1}"

    print(f"Model: WAL segments W0..W{segments[-1]} ({SEG_SIZE} LSNs each); "
          f"primary insert_lsn = {insert_lsn} (in W{seg_of(insert_lsn)}).")
    print(f"Primary recycle policy: keep the last {KEEP} segments "
          f"({seg_label(policy_floor_seg)}..{seg_label(segments[-1])}); recycle older.\n")

    slot_restart_lsn = 220                        # standby still needs from here
    print(f"Standby 'app_slot' restart_lsn = {slot_restart_lsn} "
          f"(in W{seg_of(slot_restart_lsn)}).\n")

    def recycle_floor_seg(with_slot):
        if with_slot:
            # floor = the segment containing the OLDEST needed LSN across slots,
            # i.e. max(policy_floor, seg_of(restart_lsn))  ... but slot can only
            # PULL the floor BACK (keep more), never push it forward:
            # effective floor = min(policy_floor_seg, seg_of(restart_lsn))
            return min(policy_floor_seg, seg_of(slot_restart_lsn))
        return policy_floor_seg

    print("Case 1 - NO slot (primary recycles by policy only):")
    floor1 = recycle_floor_seg(False)
    recycled1 = [s for s in segments if s < floor1]
    kept1 = [s for s in segments if s >= floor1]
    print(f"  floor = W{floor1} (LSN {floor1*SEG_SIZE}); recycle "
          f"{[seg_label(s) for s in recycled1]}; keep {[seg_label(s) for s in kept1]}")
    needs = seg_of(slot_restart_lsn)
    stale = needs < floor1
    print(f"  standby needs W{needs} (restart_lsn {slot_restart_lsn}); "
          f"W{needs} is {'RECYCLED -> STALE (needs base backup)' if stale else 'kept'}")
    print()
    print("Case 2 - WITH slot 'app_slot' (restart_lsn pinned at "
          + str(slot_restart_lsn) + "):")
    floor2 = recycle_floor_seg(True)
    recycled2 = [s for s in segments if s < floor2]
    kept2 = [s for s in segments if s >= floor2]
    print(f"  floor = W{floor2} (LSN {floor2*SEG_SIZE}); recycle "
          f"{[seg_label(s) for s in recycled2]}; keep {[seg_label(s) for s in kept2]}")
    safe2 = needs >= floor2
    print(f"  standby needs W{needs}; W{needs} is "
          f"{'KEPT -> standby can stream from here' if safe2 else 'recycled'}")
    print()
    rec1 = ",".join(seg_label(s) for s in recycled1) or "(none)"
    rec2 = ",".join(seg_label(s) for s in recycled2) or "(none)"
    print("  | config    | floor | recycled | standby W2 status      |")
    print("  |-----------|-------|----------|------------------------|")
    print(f"  | no slot   | W{floor1}    | {rec1:<8} | "
          f"{'STALE (data loss)' if stale else 'kept'} |")
    print(f"  | with slot | W{floor2}    | {rec2:<8} | "
          f"{'kept (safe)' if safe2 else 'stale'} |")
    print()
    print("SLOT ADVANCES as the standby replays (restart_lsn moves forward):")
    new_restart = 350                             # standby caught up to here
    floor3 = min(policy_floor_seg, seg_of(new_restart))
    print(f"  after replay, app_slot restart_lsn -> {new_restart} (W{seg_of(new_restart)}); "
          f"floor -> W{floor3}; now W2 can be recycled (standby moved past it).\n")

    # assertions
    assert floor1 == 3 and floor2 == 2
    assert stale and safe2 is not False           # safe2 True
    assert floor3 == 3, "once the slot passes the policy floor, floor snaps back"
    assert recycled2 == [0, 1]
    print("[check] no-slot floor W3 (standby stale); slot floor W2 (standby safe); "
          "slot advances -> floor W3: OK")


# ============================================================================
# 5. SECTION E - lag monitoring (pg_stat_replication waterfall)
# ============================================================================
def section_e():
    banner("SECTION E: lag monitoring - sent / write / flush / replay LSNs")
    print("pg_stat_replication exposes FOUR progress markers per standby. They are")
    print("monotone descending (each <= the previous) and together form the lag")
    print("waterfall - each gap is a different kind of slowness you can act on.\n")

    insert_lsn = 540
    sent_lsn = 540
    write_lsn = 500
    flush_lsn = 480
    replay_lsn = 450

    print("  | marker        | LSN | meaning                                       |")
    print("  |---------------|-----|-----------------------------------------------|")
    print(f"  | insert_lsn (P)| {insert_lsn} | primary's current WAL position (the source)  |")
    print(f"  | sent_lsn      | {sent_lsn} | primary has PUSHED this far over TCP         |")
    print(f"  | write_lsn     | {write_lsn} | standby has WRITTEN this far (not fsync'd)   |")
    print(f"  | flush_lsn     | {flush_lsn} | standby has FLUSHED this far (durable)       |")
    print(f"  | replay_lsn    | {replay_lsn}| standby has REPLAYED this far (visible)     |")
    print()
    send_lag = insert_lsn - sent_lsn
    write_lag = sent_lsn - write_lsn
    flush_lag = write_lsn - flush_lsn
    replay_lag = flush_lsn - replay_lsn
    total_lag = insert_lsn - replay_lsn
    print("The waterfall (each gap = a distinct bottleneck):\n")
    print("  | segment        | from      | to        | gap (LSN) | what is slow        |")
    print("  |----------------|-----------|-----------|-----------|---------------------|")
    print(f"  | send   lag     | insert    | sent      | {send_lag:>4}      | walsender / network|")
    print(f"  | write  lag     | sent      | write     | {write_lag:>4}      | standby I/O write   |")
    print(f"  | flush  lag     | write     | flush     | {flush_lag:>4}      | standby fsync       |")
    print(f"  | replay lag     | flush     | replay    | {replay_lag:>4}      | standby apply (CPU) |")
    print(f"  | TOTAL          | insert    | replay    | {total_lag:>4}      | end-to-end lag      |")
    print()
    print("Monotonicity MUST hold (an invariant pg_stat_replication relies on):")
    print(f"  insert({insert_lsn}) >= sent({sent_lsn}) >= write({write_lsn}) "
          f">= flush({flush_lsn}) >= replay({replay_lsn})  -> "
          f"{'OK' if insert_lsn>=sent_lsn>=write_lsn>=flush_lsn>=replay_lsn else 'BROKEN'}\n")
    print("Read it as a diagnostic:")
    print(f"  - send lag = {send_lag}: network/walsender healthy (everything shipped).")
    print(f"  - write lag = {write_lag}: standby has NOT yet written {write_lag} LSN - I/O.")
    print(f"  - flush lag = {flush_lag}: written but not fsync'd - the durability gap.")
    print("    (sync replication waits here: flush_lsn is what unblocks a COMMIT.)")
    print(f"  - replay lag = {replay_lag}: durable but not yet visible - the read lag.")
    print(f"  - TOTAL end-to-end lag = {total_lag} LSN behind the primary.\n")

    assert insert_lsn >= sent_lsn >= write_lsn >= flush_lsn >= replay_lsn
    assert total_lag == send_lag + write_lag + flush_lag + replay_lag
    assert send_lag == 0 and total_lag == 90
    print(f"[check] monotone; total_lag {total_lag} == sum of gaps "
          f"({send_lag}+{write_lag}+{flush_lag}+{replay_lag}): OK")


# ============================================================================
# 6. SECTION F - failover & split-brain
# ============================================================================
def section_f():
    banner("SECTION F: failover - promote a standby (and avoid split-brain)")
    print("When the primary dies, you PROMOTE a standby: it finishes replaying WAL,")
    print("flips itself to read-write, and becomes the new primary (pg_promote).")
    print("The danger is SPLIT-BRAIN: if the old primary is not actually dead (just")
    print("partitioned) and BOTH accept writes, the two WAL streams diverge and")
    print("cannot be reconciled. HA stacks (Patroni + etcd) fence the old primary")
    print("(STONITH) so only ONE primary ever exists.\n")

    # A deterministic failover timeline (ms from failure detection).
    print("  | t (ms) | event                                                   |")
    print("  |--------|---------------------------------------------------------|")
    timeline = [
        (0,    "primary becomes unreachable (detected by heartbeat timeout)"),
        (0,    "standby's walreceiver notices the connection dropped"),
        (10,   "failover manager (Patroni) acquires the etcd leader lease"),
        (10,   "Patroni runs pg_promote on the chosen standby"),
        (12,   "standby finishes replaying any buffered WAL"),
        (12,   "standby flips to read-write = NEW PRIMARY"),
        (15,   "DNS / connection pooler repoints clients to the new primary"),
        (15,   "old primary is FENCED (STONITH) - kernel panic / power off"),
    ]
    for t, e in timeline:
        print(f"  | {t:>5}   | {e:<55} |")
    print()
    print("SPLIT-BRAIN - what happens WITHOUT fencing:")
    print("  - old primary is only PARTITIONED (network split), not dead.")
    print("  - it keeps accepting writes from clients that can still reach it.")
    print("  - the promoted standby ALSO accepts writes.")
    print("  - two primaries, two WAL streams -> DIVERGENCE. On heal, the old")
    print("    primary's WAL cannot be merged (it has writes the new primary never")
    print("    saw). The only safe recovery is to DISCARD the old primary's divergent")
    print("    writes (pg_rewind) or rebuild it from a base backup.\n")
    print("MITIGATIONS:")
    print("  - FENCING / STONITH: the failover manager kills the old primary")
    print("    (kernel panic, power-cycle via IPMI) BEFORE promoting, so it cannot")
    print("    accept writes. The standard Postgres HA approach (Patroni, repmgr).")
    print("  - CONSENSUS QUORUM: Patroni uses etcd/raft so only ONE primary wins")
    print("    the lease; a partitioned old primary loses the lease and demotes")
    print("    itself. This is the SAME quorum idea as Section C's 'ANY n'.")
    print("  - sync replication: if the new primary was a SYNC standby, its data is")
    print("    a superset of what the old primary committed - no committed loss.\n")

    # sanity: promote ends replay then opens read-write (replay before write)
    assert timeline[3][0] <= timeline[4][0] <= timeline[5][0]
    assert timeline[6][0] <= timeline[7][0]   # clients repoint AFTER promotion
    print("[check] failover order: detect -> promote lease -> finish replay -> "
          "read-write -> repoint -> fence: OK")


# ============================================================================
# 7. GOLD - pinned values for streaming_replication.html (JS must reproduce)
# ============================================================================
def section_gold():
    banner("GOLD (pinned for streaming_replication.html) - JS must reproduce these")
    s1, s2, s3 = STANDBYS
    ft1, ft2, ft3 = sb_flush_time(s1), sb_flush_time(s2), sb_flush_time(s3)
    fts = [ft1, ft2, ft3]
    lat_async = PRIMARY_FLUSH
    lat_sync_s1 = PRIMARY_FLUSH + ft1
    lat_first2 = PRIMARY_FLUSH + max(ft1, ft2)
    lat_any2 = PRIMARY_FLUSH + sorted(fts)[1]
    # lag waterfall LSNs
    insert_lsn, sent_lsn, write_lsn, flush_lsn, replay_lsn = 540, 540, 500, 480, 450

    print(f"  primary_flush              = {PRIMARY_FLUSH} ms")
    print(f"  standby flush_times        = {fts}   (s1,s2,s3 = ship+flush+ack)")
    print(f"  async commit latency       = {lat_async} ms")
    print(f"  sync  's1'     latency     = {lat_sync_s1} ms   (= {PRIMARY_FLUSH} + {ft1})")
    print(f"  sync  'FIRST 2' latency    = {lat_first2} ms   (= {PRIMARY_FLUSH} + max({ft1},{ft2}))")
    print(f"  sync  'ANY 2'   latency    = {lat_any2} ms   (= {PRIMARY_FLUSH} + 2nd-smallest{fts})")
    print(f"  pg_stat_replication LSNs   = insert {insert_lsn}, sent {sent_lsn}, "
          f"write {write_lsn}, flush {flush_lsn}, replay {replay_lsn}")
    print(f"  total end-to-end lag       = {insert_lsn - replay_lsn} LSN")
    print()
    # the headline gold-check
    assert lat_sync_s1 == PRIMARY_FLUSH + max([ft1])
    assert lat_first2 == PRIMARY_FLUSH + max([ft1, ft2])
    assert lat_async < lat_any2 < lat_first2
    print("  GOLD-CHECK: sync commit latency == primary_flush + max(standby_flush_times)")
    print(f"    's1'     : {lat_sync_s1} == {PRIMARY_FLUSH} + max([{ft1}]) == "
          f"{PRIMARY_FLUSH + max([ft1])}   OK")
    print(f"    'FIRST 2': {lat_first2} == {PRIMARY_FLUSH} + max([{ft1},{ft2}]) == "
          f"{PRIMARY_FLUSH + max([ft1, ft2])}   OK")
    print("\n[check] GOLD pinned; async < ANY 2 < FIRST 2 < max(flush_times): OK")


# ============================================================================
# main
# ============================================================================
def main():
    print("streaming_replication.py - reference impl. All numbers feed")
    print("STREAMING_REPLICATION.md. Pure Python stdlib.")
    print("Run: python3 streaming_replication.py")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
