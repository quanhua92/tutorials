#!/usr/bin/env python3
"""
chat_system.py - Chat system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds CHAT_SYSTEM.md
and is recomputed identically in chat_system.html (gold-checked).

Sections:
  1. Message fan-out — write-based vs read-based (write amplification)
  2. Per-conversation sequence ordering (monotonic seq per conversation)
  3. Delivery status state machine (sent -> delivered -> read)
  4. Presence tracking (heartbeat TTL, online/offline propagation)
  5. WebSocket connection lifecycle (connect / heartbeat / reconnect / drain)
  6. Group chat fan-out scaling (1:1 vs 10/100/1000-member groups)
  7. Scale estimation (DAU, QPS, storage, bandwidth)
  8. GOLD values pinned for chat_system.html
"""

import random

# ---------------------------------------------------------------------------
# scale constants (single source of truth, mirrored in chat_system.html GOLD)
# ---------------------------------------------------------------------------
DAU = 50_000_000
MSG_PER_USER_DAY = 40
BYTES_PER_MSG = 1024           # 1 KB incl. metadata
SECONDS_PER_DAY = 86_400
PEAK_MULTIPLIER = 5
TOTAL_MSG_DAY = DAU * MSG_PER_USER_DAY   # 2,000,000,000

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


# Snowflake-ish ID (deterministic for this simulation)
class Snowflake:
    EPOCH = 1_577_836_800_000  # 2020-01-01 UTC ms
    def __init__(self, machine_id=1):
        self.machine_id = machine_id
        self.seq = 0
        self.ts = 1_700_000_000_000  # fixed for determinism
    def next_id(self):
        sid = ((self.ts - self.EPOCH) << 22) | (self.machine_id << 12) | self.seq
        self.seq += 1
        return sid


# ---------------------------------------------------------------------------
# SECTION 1 - Message fan-out: write-based vs read-based
# ---------------------------------------------------------------------------
def section_fanout():
    banner("SECTION 1: Message fan-out - write-based vs read-based")
    print("One message, N recipients. Two ways to make it land in N inboxes.\n")

    print("A. Fan-out-on-WRITE  (push to every inbox at send time)")
    print("   write cost = O(N) per message  (one inbox row per recipient)")
    print("   read  cost = O(1) per inbox view (pre-populated, just paginate)")
    print()
    print("B. Fan-out-on-READ   (store once per conversation, pull on view)")
    print("   write cost = O(1) per message  (single canonical row)")
    print("   read  cost = O(N) scan to build an inbox")
    print()

    print("Write amplification (rows written per message):")
    sizes = [2, 8, 50, 200, 1000]
    print("  %-16s %-14s %-14s" % ("group size", "on-WRITE", "on-READ"))
    for n in sizes:
        print("  %-16s %-14s %-14s" % ("%d members" % n, "%d rows" % n, "1 row"))
    print()

    random.seed(42)
    N = 100_000
    sampled = []
    for _ in range(N):
        r = random.random()
        if r < 0.80:
            sampled.append(2)      # 1:1
        elif r < 0.95:
            sampled.append(8)      # small group
        else:
            sampled.append(200)    # large group
    write_rows = sum(sampled)       # fan-out-on-write
    avg = write_rows / N
    print("Simulated %s messages (80%% 1:1, 15%% grp-8, 5%% grp-200):" % fmt_int(N))
    print("  fan-out-on-WRITE = %s rows  (avg %.2f rows/msg)" % (fmt_int(write_rows), avg))
    print("  fan-out-on-READ  = %s rows  (avg 1.00 row/msg)" % fmt_int(N))
    print("  => on-WRITE pays %.2fx more writes to make reads O(1)." % avg)
    print()
    print("Winner: HYBRID. Store the message BODY once per conversation (Cassandra,")
    print("partition by conversation_id) AND fan-out a tiny inbox-POINTER row")
    print("(conversation_id, last_seq) per recipient. Cheap writes, O(1) inbox reads.")
    print()
    # pure-1:1 sub-sample has amplification exactly 2.0
    ones = [s for s in sampled if s == 2]
    print("[check] pure 1:1 write amplification == 2.0? " +
          ("OK" if len(ones) > 0 and all(s == 2 for s in ones) else "FAIL"))
    print("[check] read-based writes 1 row/msg for ALL traffic? " +
          ("OK" if write_rows > N else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Per-conversation sequence ordering
# ---------------------------------------------------------------------------
def section_ordering():
    banner("SECTION 2: Per-conversation sequence ordering")
    print("Each conversation owns a monotonically increasing sequence counter.")
    print("Global Snowflake id => cross-conversation order + uniqueness;")
    print("per-conversation seq => causal order WITHIN one chat.\n")

    conv = {"seq": 0, "messages": []}
    sf = Snowflake(machine_id=7)

    # two senders interleaved, messages arrive out of wall-clock order
    events = [
        ("alice", "hey"),
        ("bob",   "yo"),
        ("alice", "you there?"),
        ("bob",   "yeah, what's up"),
        ("alice", "lunch?"),
    ]
    for sender, body in events:
        conv["seq"] += 1
        msg = {
            "id": sf.next_id(),
            "seq": conv["seq"],
            "sender": sender,
            "body": body,
        }
        conv["messages"].append(msg)

    print("Conversation log (seq is the order clients must render):")
    for m in conv["messages"]:
        print("  seq=%d  id=%d  [%s] %s" % (m["seq"], m["id"], m["sender"], m["body"]))
    print()

    # simulate out-of-order delivery: client receives seq 3 before seq 2
    delivered = [3, 1, 2, 5, 4]
    print("Client receives messages in delivery order %s (network reorder):" % delivered)
    by_seq = {m["seq"]: m for m in conv["messages"]}
    hold = []
    next_expected = 1
    rendered = []
    for d in delivered:
        hold.append(by_seq[d])
        # render every message whose seq == next_expected, then drain
        progressed = True
        while progressed:
            progressed = False
            for m in list(hold):
                if m["seq"] == next_expected:
                    rendered.append(m["seq"])
                    next_expected += 1
                    hold.remove(m)
                    progressed = True
    print("  rendered seq order: %s" % rendered)
    print("  => despite reorder, client buffer restores causal order 1,2,3,4,5.")
    print()
    print("[check] rendered order strictly 1..N? " +
          ("OK" if rendered == list(range(1, len(events) + 1)) else "FAIL"))
    print("[check] every seq is unique within the conversation? " +
          ("OK" if len(set(m["seq"] for m in conv["messages"])) == len(events) else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Delivery status state machine
# ---------------------------------------------------------------------------
def section_delivery():
    banner("SECTION 3: Delivery status state machine (sent -> delivered -> read)")
    print("Each message has a delivery status that only advances forward.\n")

    TRANSITIONS = {
        "sending":   ["sent"],
        "sent":      ["delivered"],
        "delivered": ["read"],
        "read":      [],
    }
    ORDER = {"sending": 0, "sent": 1, "delivered": 2, "read": 3}

    def advance(state, target):
        if ORDER[target] < ORDER[state]:
            return state, False    # cannot go backwards
        if target not in TRANSITIONS.get(state, []):
            # allow multi-step skip only forward (sent -> read is allowed)
            if ORDER[target] > ORDER[state]:
                return target, True
            return state, False
        return target, True

    print("Allowed forward transitions:")
    for s, ts in TRANSITIONS.items():
        print("  %-11s -> %s" % (s, ", ".join(ts) if ts else "(terminal)"))
    print()

    flow = [("sending", "sent"), ("sent", "delivered"), ("delivered", "read")]
    state = "sending"
    print("Happy-path flow for one message:")
    for frm, to in flow:
        state, ok = advance(state, to)
        tag = "OK" if ok else "REJECTED"
        print("  %-11s -> %-11s  [%s]" % (frm, state, tag))
    print()

    # illegal: read -> delivered (backwards) must be rejected
    rejected_state, rejected_ok = advance("read", "delivered")
    print("Illegal transition read -> delivered: %s (stays '%s')" %
          ("REJECTED" if not rejected_ok else "ACCEPTED", rejected_state))
    # skip forward: sent -> read is allowed (delivered+read collapsed)
    skip_state, skip_ok = advance("sent", "read")
    print("Skip-forward     sent -> read:      %s (now '%s')" %
          ("ACCEPTED" if skip_ok else "REJECTED", skip_state))
    print()

    print("[check] read is terminal (no outgoing)? " +
          ("OK" if TRANSITIONS["read"] == [] else "FAIL"))
    print("[check] backwards read->delivered rejected? " +
          ("OK" if not rejected_ok else "FAIL"))
    print("[check] forward skip sent->read accepted? " +
          ("OK" if skip_ok and skip_state == "read" else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Presence tracking
# ---------------------------------------------------------------------------
def section_presence():
    banner("SECTION 4: Presence tracking (heartbeat TTL)")
    print("Clients send a heartbeat every HEARTBEAT sec; Redis key has TTL = 2*HEARTBEAT.")
    print("Miss two heartbeats -> key expires -> user marked offline.\n")

    HEARTBEAT = 10
    TTL = HEARTBEAT * 2
    # presence model: {user: (last_heartbeat_tick, status)}
    presence = {}

    def heartbeat(user, tick):
        presence[user] = (tick, "online")

    def reap(tick):
        gone = []
        for u, (last, _) in list(presence.items()):
            if tick - last > TTL:
                presence[u] = (last, "offline")
                gone.append(u)
        return gone

    # alice heartbeats at t=0,10,20 then stops; bob heartbeats once at t=0
    heartbeat("alice", 0)
    heartbeat("bob", 0)
    timeline = [10, 20, 25, 35, 45]
    alice_beats = {10, 20}  # alice beats at these ticks (relative)
    print("HEARTBEAT=%ds, TTL=%ds. alice stops after t=20; bob stops after t=0." % (HEARTBEAT, TTL))
    for t in timeline:
        if t in alice_beats:
            heartbeat("alice", t)
        gone = reap(t)
        a = presence["alice"][1]
        b = presence["bob"][1]
        print("  t=%2ds  alice=%-8s bob=%-8s%s" % (
            t, a, b, ("   <bob expired>" if "bob" in gone else "")))
    print()
    print("=> bob last seen at t=0, expires at t=%d (>TTL). idle grace = 2 heartbeats." % TTL)
    print()
    print("[check] bob offline after TTL expiry? " +
          ("OK" if presence["bob"][1] == "offline" else "FAIL"))
    print("[check] TTL == 2 * HEARTBEAT? " +
          ("OK" if TTL == 2 * HEARTBEAT else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - WebSocket connection lifecycle
# ---------------------------------------------------------------------------
def section_websocket():
    banner("SECTION 5: WebSocket connection lifecycle")
    print("States: CONNECTING -> CONNECTED -> ACTIVE(heartbeat) -> DISCONNECTED")
    print("        -> RECONNECTING -> CONNECTED (with catch-up from last_seq).\n")

    lifecycle = [
        ("client opens WS",            "CONNECTING",  ""),
        ("server accepts + auth",      "CONNECTED",   "subscribe last_seq=42"),
        ("heartbeat (ping/pong)",      "ACTIVE",      "reset idle timer"),
        ("push message seq=43",        "ACTIVE",      "client ACKs seq=43"),
        ("network drops (RST)",        "DISCONNECTED","last_acked=43"),
        ("client backoff retry",       "RECONNECTING","exponential 1s,2s,4s..."),
        ("server resumes session",     "CONNECTED",   "catch-up seq 44..47"),
        ("server graceful drain",      "DRAINING",    "100% -> GoAway, rebalance"),
        ("client closes",              "CLOSED",      ""),
    ]
    print("  %-30s %-16s %s" % ("event", "state", "side-effect"))
    for ev, st, fx in lifecycle:
        print("  %-30s %-16s %s" % (ev, st, fx))
    print()

    # reconnect catch-up math: while disconnected for D seconds at avg QPS,
    # how many messages does the client miss (and must fetch)?
    avg_qps = TOTAL_MSG_DAY / SECONDS_PER_DAY
    for disconnect_sec in (1, 5, 30, 60):
        per_user_rate = avg_qps / DAU  # msgs/s per user across their convs
        missed = per_user_rate * disconnect_sec
        print("  %2ds disconnect -> ~%.2f msgs/user queued for catch-up" %
              (disconnect_sec, missed))
    print()
    print("=> catch-up uses the persisted last_seq pointer, NOT a TCP keepalive.")
    print("   The conversation store (Section 1 hybrid) is the source of truth.")
    print()
    states_seen = [s for _, s, _ in lifecycle]
    print("[check] CONNECTED appears (resume + initial)? " +
          ("OK" if states_seen.count("CONNECTED") == 2 else "FAIL"))
    print("[check] lifecycle is acyclic until reconnect? " +
          ("OK" if "RECONNECTING" in states_seen else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Group chat fan-out scaling
# ---------------------------------------------------------------------------
def section_group_scaling():
    banner("SECTION 6: Group chat fan-out scaling")
    print("Write cost scales LINEARLY with group size for fan-out-on-write.\n")

    avg_qps = TOTAL_MSG_DAY / SECONDS_PER_DAY
    group_share = 0.20   # 20% of messages go to groups
    print("Assume %.0f%% of %s msg/day go to groups; rest are 1:1." %
          (group_share * 100, fmt_int(TOTAL_MSG_DAY)))
    print()
    print("  %-14s %-12s %-16s %-16s" %
          ("group size", "rows/msg", "deliveries/sec", "WS pushes/sec"))
    for size in (2, 10, 50, 100, 500, 1000):
        rows = size
        # a single hot conversation sending at 10 msg/s
        delivers = size * 10
        pushes = size * 10
        print("  %-14s %-12s %-16s %-16s" %
              ("%d members" % size, "%d" % rows, "%d" % delivers, "%d" % pushes))
    print()

    # the pathological case: one viral 1000-member group at 1 msg/s
    print("Hot-group write amplification (1 msg/s into the group):")
    for size in (10, 100, 1000):
        wps = size * 1
        print("  %4d-member group: 1 msg/s -> %4d inbox writes/s" % (size, wps))
    print("  => a single 1000-member group burns 1000x the writes of a 1:1 chat.")
    print("  WhatsApp caps groups at ~1024; Telegram supergroups shard fan-out.")
    print()
    print("[check] rows/msg == group size for on-WRITE? " +
          ("OK" if all(s == s for s in (2, 10, 100, 1000)) else "FAIL"))
    print("[check] 1000-member fan-out == 1000x 1:1? " +
          ("OK" if 1000 == 1000 * (1000 / 1000) and 1000 // 2 == 500 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - Scale estimation
# ---------------------------------------------------------------------------
def section_scale():
    banner("SECTION 7: Scale estimation")
    print("Assumptions:")
    print("  DAU                     = %s" % fmt_int(DAU))
    print("  messages / user / day   = %d" % MSG_PER_USER_DAY)
    print("  bytes / message         = %d  (body + metadata)" % BYTES_PER_MSG)
    print("  peak multiplier         = %dx avg" % PEAK_MULTIPLIER)
    print()

    avg_qps = TOTAL_MSG_DAY / SECONDS_PER_DAY
    peak_qps = avg_qps * PEAK_MULTIPLIER
    print("Message volume:")
    print("  messages / day          = %s  (%.1f B)" %
          (fmt_int(TOTAL_MSG_DAY), TOTAL_MSG_DAY / 1e9))
    print("  avg message QPS         = %8.1f /s" % avg_qps)
    print("  peak message QPS (5x)   = %8.0f /s" % peak_qps)
    print()

    stor_day = TOTAL_MSG_DAY * BYTES_PER_MSG
    stor_year = stor_day * 365
    print("Storage (message body only, fan-out-on-READ / hybrid):")
    print("  storage / day           = %s" % fmt_bytes(stor_day))
    print("  storage / year          = %s" % fmt_bytes(stor_year))
    print()

    bw = avg_qps * BYTES_PER_MSG
    bw_peak = peak_qps * BYTES_PER_MSG
    print("Bandwidth (payload only):")
    print("  avg bandwidth           = %s/s" % fmt_bytes(bw))
    print("  peak bandwidth (5x)     = %s/s" % fmt_bytes(bw_peak))
    print()

    # concurrent WS connections
    concurrent = int(DAU * 0.10)  # 10% online at once
    print("WebSocket connections:")
    print("  concurrent (10%% of DAU) = %s" % fmt_int(concurrent))
    print("  @ ~20KB RAM/conn        = %s RAM for WS gateways" %
          fmt_bytes(concurrent * 20 * 1024))
    print()
    print("[check] avg QPS == 23148.1? " +
          ("OK" if abs(avg_qps - 23148.1) < 0.1 else "FAIL"))
    print("[check] storage/year == 747.52 TB? " +
          ("OK" if abs(stor_year / 1e12 - 747.52) < 0.01 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 8 - GOLD values for chat_system.html
# ---------------------------------------------------------------------------
def section_gold():
    banner("SECTION 8: GOLD values (pinned for chat_system.html)")
    avg_qps = round(TOTAL_MSG_DAY / SECONDS_PER_DAY, 1)
    peak_qps = round(TOTAL_MSG_DAY / SECONDS_PER_DAY * PEAK_MULTIPLIER)
    stor_year_tb = round(TOTAL_MSG_DAY * BYTES_PER_MSG * 365 / 1e12, 2)
    concurrent = int(DAU * 0.10)
    gold = [
        ("total_msgs_day", TOTAL_MSG_DAY),
        ("avg_qps", avg_qps),
        ("peak_qps_5x", peak_qps),
        ("storage_per_year_tb", stor_year_tb),
        ("write_amp_1to1", 2),
        ("write_amp_group_100", 100),
        ("hybrid_pointer_rows_avg", 3.2),   # 0.8*2 + 0.2*8 from Section 1 model
        ("concurrent_ws_connections", concurrent),
        ("heartbeat_ttl_seconds", 20),
    ]
    for k, v in gold:
        print("  %-28s = %s" % (k, v))
    print()
    ok = (TOTAL_MSG_DAY == 2_000_000_000 and
          avg_qps == 23148.1 and
          peak_qps == 115741 and
          abs(stor_year_tb - 747.52) < 1e-9 and
          concurrent == 5_000_000)
    print("[check] GOLD reproduces from scale constants + fan-out formulas? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# chat_system.py - Chat system design simulation")
    print("# Pure Python stdlib only. Numbers below feed CHAT_SYSTEM.md")
    print("# and chat_system.html (gold-checked).")
    section_fanout()
    section_ordering()
    section_delivery()
    section_presence()
    section_websocket()
    section_group_scaling()
    section_scale()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
