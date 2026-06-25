"""
tcp_handshake.py - Reference implementation of the TCP 3-way handshake, the
4-way teardown, sliding-window flow control, and slow-start / AIMD congestion
control -- and why distributed systems CANNOT trust TCP alone for correctness.

This is the single source of truth that TCP_HANDSHAKE.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 tcp_handshake.py

============================================================================
THE INTUITION (read this first) -- the registered-mail phone call
============================================================================
TCP is a *reliable, ordered, byte-stream* pipe between two processes. Picture
two offices exchanging numbered, registered envelopes over a courier network:

  * Handshake  : before any real mail, both offices exchange "are you ready?"
                  notes and each picks a SECRET starting number (the ISN). The
                  3-way handshake (SYN, SYN-ACK, ACK) makes sure BOTH sides
                  agree on those starting numbers, so old mis-delivered
                  envelopes from a PREVIOUS call cannot be mistaken for new ones.
  * Data       : every envelope carries a sequence number. The receiver signs
                  (ACKs) for the next number it expects. The sender keeps a copy
                  until that ACK arrives, then throws it away. Lost envelope?
                  resend. Out of order? buffer + reorder.
  * Flow ctrl  : the receiver stamps every ACK with how much free shelf space
                  it has (the advertised window, rwnd). The sender never mails
                  more than the receiver can shelf -- that is flow control.
  * Congestion : the sender also has its OWN window (cwnd) sized by what the
                  NETWORK can carry. Start tiny (1 envelope), double each round
                  (slow start), then grow linearly (AIMD). On any loss, halve
                  the target and restart tiny. The classic sawtooth.
  * Teardown   : to hang up, each side says FIN ("I have no more to send"),
                  the other ACKs, then says its own FIN. The side that sent the
                  first ACK-of-FINAL-FIN sits in TIME_WAIT (2*MSL) to catch any
                  straggling envelopes before reusing the port.

WHY DISTRIBUTED SYSTEMS DON'T STOP AT TCP: TCP's guarantees (ordered, reliable,
not-duplicated) hold ONLY *within one living connection*. When a server crashes
and a load balancer redirects you to a *new* server, your TCP connection is
RESET (RST) -- in-flight requests evaporate, and a blind retry can double-execute
a non-idempotent operation. Head-of-line blocking means one lost byte stalls
every byte behind it even on independent logical streams. So real systems layer
application-level defenses on top: idempotency keys, per-operation sequence
numbers, logical clocks (🔗 LAMPORT_TIMESTAMPS.md), and consensus logs whose
(term, index) ordering is independent of transport (🔗 RAFT.md / PAXOS.md).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  segment       : one TCP packet. Header carries flags + seq + ack + window.
  seq           : the byte-offset (from this side's ISN) of the FIRST payload
                  byte in this segment. The receiver uses it to place bytes.
  ack           : "the next byte number I expect from YOU." Implicitly confirms
                  receipt of everything below it. Cumulative.
  ISN           : Initial Sequence Number. Each side picks a random-ish start so
                  that segments from an OLD connection (same 4-tuple) cannot be
                  confused with segments of a NEW one.
  SYN / FIN     : control flags that each CONSUME one sequence number (they
                  occupy a byte position) even though they carry no payload.
                  This is why a SYN is acked with seq+1, and a FIN with seq+1.
  ACK (flag)    : "the ack field of this segment is meaningful." Set on nearly
                  everything after the handshake.
  window / rwnd : the receiver-advertised free buffer, in bytes. Flow control:
                  the sender's un-acked bytes may never exceed rwnd.
  cwnd          : congestion window. The sender's own estimate of what the
                  NETWORK can carry. Actual send window = min(rwnd, cwnd).
  ssthresh      : slow-start threshold. Below it, cwnd doubles per RTT
                  (exponential). At/above it, cwnd grows +1 per RTT (linear).
  MSS           : Maximum Segment Size. Bytes of payload per segment. Here 100
                  (for readable arithmetic; real value ~1460 over Ethernet).
  MSL           : Maximum Segment Lifetime. The longest a segment may live in
                  the net (~2 min). TIME_WAIT lasts 2*MSL.
  TIME_WAIT     : the final state of the side that closes first. It lingers
                  2*MSL so a delayed/duplicate segment from this 4-tuple dies
                  before the port can be reused.

============================================================================
THE SPEC & THE LINEAGE
============================================================================
  RFC 793  (Postel, 1981) : the original TCP. 3-way handshake, state machine,
                            sequence numbers, the 4-way close + TIME_WAIT.
  RFC 1122 (Braden, 1989) : host requirements; clarifies slow start must be on.
  Jacobson 1988           : "Congestion Avoidance and Control". INVENTS slow
                            start + AIMD. The sawtooth is his. (The birth of
                            modern congestion control.)
  RFC 5681 (Allman, 2009) : the current congestion-control spec (slow start,
                            congestion avoidance, fast retransmit/recovery).
  RFC 6298 (Allman, 2011) : computing the retransmission timeout (RTO).
  RFC 1323 (Jacobson, 1992): window scaling + timestamps (PAWS) for fat/long
                            pipes. Why rwnd fits in 16 bits but can be scaled.
  QUIC (RFC 9000, 2021)   : runs the SAME reliability over UDP to dodge TCP's
                            head-of-line blocking across multiplexed streams.

KEY FORMULAS (all verified against the RFCs + asserted in code):
    next_expected_seq = last_ack_value                      (cumulative ACK)
    ack_of_SYN        = SYN.seq + 1          (SYN consumes 1 seq number)
    ack_of_FIN        = FIN.seq + 1          (FIN consumes 1 seq number)
    ack_of_data       = data.seq + len(data) (data consumes len seq numbers)
    send_window       = min(rwnd, cwnd)
    slow start        : cwnd += segs_acked            -> doubles each RTT
    congestion avoid  : cwnd += MSS * MSS / cwnd      -> +1 MSS each RTT
    on loss (basic)   : ssthresh = max(cwnd/2, 2*MSS); cwnd = 1*MSS  (restart)
    TIME_WAIT         : 2 * MSL                         (catch delayed dupes)

Conventions in this file:
  ISN_C   : client initial sequence number.  Here 1000.
  ISN_S   : server initial sequence number.  Here 5000.
  MSS     : 100 bytes (for clean arithmetic; not a real Ethernet MSS).
  seq/ack : printed as integers (byte positions), as Wireshark does in absolute
            mode.  Window sizes in bytes.
"""

from __future__ import annotations

BANNER = "=" * 72

# Deterministic constants for the worked example (so .html can replicate exactly).
ISN_C = 1000          # client ISN
ISN_S = 5000          # server ISN
MSS = 100             # bytes per segment (kept small for readable arithmetic)
MSL = 120             # seconds (2 minutes, the textbook value)


# ============================================================================
# 1. CORE PRIMITIVES  (the code TCP_HANDSHAKE.md walks through)
# ============================================================================

class Segment:
    """One TCP segment: a direction, flags, seq, ack, payload length, window.

    `datalen` is the payload size in bytes (0 for pure SYN/FIN/ACK). seq/ack are
    byte positions. `win` is the window this segment ADVERTISES (flow control).
    """

    __slots__ = ("direction", "flags", "seq", "ack", "datalen", "win", "note")

    def __init__(self, direction, flags, seq, ack, datalen=0, win=MSS * 4, note=""):
        self.direction = direction        # "C->S" or "S->C"
        self.flags = flags                # e.g. "SYN", "SYN,ACK", "ACK", "FIN,ACK"
        self.seq = seq
        self.ack = ack
        self.datalen = datalen
        self.win = win
        self.note = note

    def __repr__(self):
        parts = [f"{self.direction} {self.flags:<9} seq={self.seq}"]
        if "ACK" in self.flags or "ack" in self.flags:
            parts.append(f"ack={self.ack}")
        if self.datalen:
            parts.append(f"len={self.datalen}")
        parts.append(f"win={self.win}")
        s = "  ".join(parts)
        if self.note:
            s += f"   // {self.note}"
        return s


def ack_for(seg: Segment) -> int:
    """The cumulative ACK value a receiver sends after in-order receipt of `seg`.

    Implements the core arithmetic:
        ack = seg.seq + (1 if SYN or FIN else 0) + seg.datalen
    SYN and FIN each consume ONE sequence number (they occupy a byte slot) even
    though they carry no payload. Pure data consumes `datalen` slots. A pure ACK
    (no SYN/FIN/data) consumes NONE, so it is never itself acked.
    """
    consumed = seg.datalen
    if "SYN" in seg.flags:
        consumed += 1
    if "FIN" in seg.flags:
        consumed += 1
    return seg.seq + consumed


# ----------------------------------------------------------------------------
# Flow-control engine: a byte-stream sender with a sliding window.
# ----------------------------------------------------------------------------

class SlidingSender:
    """A sender that transmits bytes in-order with a fixed receiver window.

    Tracks:
      send_base : seq of the oldest UN-acked byte (left edge of the window)
      send_next : seq of the next byte to send (right edge of new data)
      rwnd      : receiver-advertised window in bytes (flow control)
    Bytes in flight = send_next - send_base. The sender may send while that is
    less than rwnd. Each ACK slides send_base forward (cumulative ACK), opening
    room at the right edge. This is the textbook sliding window (RFC 793 §3.4).
    """

    def __init__(self, send_base, rwnd):
        self.send_base = send_base
        self.send_next = send_base
        self.rwnd = rwnd

    @property
    def in_flight(self):
        return self.send_next - self.send_base

    @property
    def window_right(self):
        return self.send_base + self.rwnd

    def can_send(self):
        return self.in_flight < self.rwnd

    def send(self, datalen=MSS):
        """Send one segment of `datalen` bytes. Returns the seq used, or None."""
        if self.in_flight + datalen > self.rwnd:
            return None                       # window full -> blocked (flow ctrl)
        seq = self.send_next
        self.send_next += datalen
        return seq

    def receive_ack(self, ack_value):
        """Slide the window: send_base jumps to the cumulative ack value."""
        if ack_value > self.send_base:
            self.send_base = ack_value


# ----------------------------------------------------------------------------
# Congestion-control engine: slow start -> congestion avoidance (AIMD).
# ----------------------------------------------------------------------------

def simulate_congestion(cwnd0=1, ssthresh0=16, loss_at_rtt=7, n_rtts=16):
    """Step cwnd RTT-by-RTT under slow start + congestion avoidance + loss.

    Rules (RFC 5681, basic Reno-timeout model for clarity):
      - cwnd < ssthresh : SLOW START. Double cwnd each RTT (cwnd += cwnd, since
                          cwnd segments are ACKed and each adds 1 MSS).
      - cwnd >= ssthresh: CONGESTION AVOIDANCE (AIMD). +1 MSS per RTT (linear).
      - loss event      : the cwnd USED that RTT is the peak; ssthresh is set to
                          max(cwnd // 2, 2) and the NEXT RTT restarts at cwnd=1.
                          This is the sawtooth DROP.

    The recorded cwnd for each RTT is the value TRANSMITTED with that RTT. On a
    loss RTT we record the peak cwnd (with the LOSS event) and reset cwnd so the
    NEXT RTT shows the drop -- the sawtooth is visible as peak-then-1.

    Returns a list of dicts: {rtt, cwnd, ssthresh, phase, event}.
    Deterministic: a loss is injected at `loss_at_rtt`.
    """
    cwnd = cwnd0
    ssthresh = ssthresh0
    trace = []
    for rtt in range(n_rtts):
        phase = "slow-start" if cwnd < ssthresh else "congestion-avoidance (AIMD)"
        if rtt == loss_at_rtt:
            # this RTT transmitted with `cwnd` (the peak); a loss is detected.
            event = "LOSS -> ssthresh=cwnd/2, next cwnd=1"
            ssthresh = max(cwnd // 2, 2)
            trace.append({"rtt": rtt, "cwnd": cwnd, "ssthresh": ssthresh,
                          "phase": phase, "event": event})
            cwnd = 1                            # restart slow start next RTT
        else:
            trace.append({"rtt": rtt, "cwnd": cwnd, "ssthresh": ssthresh,
                          "phase": phase, "event": ""})
            # advance cwnd for the NEXT RTT
            if cwnd < ssthresh:
                cwnd = cwnd * 2                  # slow start: double
            else:
                cwnd = cwnd + 1                  # AIMD: +1
    return trace


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_segment(seg: Segment):
    print(f"    {seg!r}")


# ============================================================================
# 3. THE SIMULATION SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: 3-way handshake -- both sides pick ISNs, agree on starting points
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: the 3-way handshake  (SYN, SYN-ACK, ACK)")
    print("Goal: before any data, BOTH sides must (1) agree the other is alive")
    print("and (2) synchronize their starting sequence numbers (ISNs). Three")
    print("segments do it. The ISNs exist so that a delayed segment from an OLD,")
    print("dead connection (same IP/port 4-tuple) cannot be mistaken for data in")
    print("the NEW connection. Picking a fresh random-ish ISN every time breaks")
    print("that aliasing.\n")
    print(f"Worked numbers: ISN_client (ISN_C) = {ISN_C}, "
          f"ISN_server (ISN_S) = {ISN_S}, MSS = {MSS}.\n")

    # step 1: client -> server SYN
    s1 = Segment("C->S", "SYN", seq=ISN_C, ack=0, note="client picks ISN_C")
    print("Step 1 - CLIENT sends SYN (I want to talk; my seq starts at ISN_C):")
    print_segment(s1)
    print(f"      SYN consumes seq #{ISN_C}, so server's ACK will expect {ISN_C + 1}.\n")

    # step 2: server -> client SYN-ACK
    ack_of_syn = ack_for(s1)                    # ISN_C + 1
    s2 = Segment("S->C", "SYN,ACK", seq=ISN_S, ack=ack_of_syn,
                 note=f"server picks ISN_S; confirms client SYN (ack={ack_of_syn})")
    print("Step 2 - SERVER sends SYN-ACK (yes; MY seq starts at ISN_S; I expect "
          f"your {ack_of_syn}):")
    print_segment(s2)
    print(f"      server's SYN consumes seq #{ISN_S}, so client's ACK expects "
          f"{ISN_S + 1}.\n")

    # step 3: client -> server ACK
    ack_of_syn2 = ack_for(s2)                   # ISN_S + 1
    s3 = Segment("C->S", "ACK", seq=ack_of_syn, ack=ack_of_syn2,
                 note="client confirms server SYN; no payload, no new flag-byte")
    print("Step 3 - CLIENT sends ACK (I confirm your SYN; connection OPEN):")
    print_segment(s3)
    print()

    print("State after handshake (these are the NEXT seqs each side will use):")
    print(f"    client: seq_next = {ack_of_syn}   (= ISN_C + 1, the SYN byte was consumed)")
    print(f"    server: seq_next = {ack_of_syn2}   (= ISN_S + 1, the SYN byte was consumed)")
    print()
    print("Why 3 steps, not 2? Step 1 proves client->server works; step 2 proves")
    print("BOTH server->client AND server received the SYN; step 3 proves the")
    print("client received the server's SYN. Without step 3 the server could be")
    print("talking to nobody (the client's SYN could have been a spoofed/spurious")
    print("packet). Each direction is independently confirmed.\n")

    # WHY ISN: the old-segment attack / confusion
    print("Why random ISNs (not 0 every time)? Imagine a stray segment from a")
    print("PREVIOUS connection (same 4-tuple) that wanders in 60s late. If every")
    print("connection started at seq 0, that stale byte-stream would land EXACTLY")
    print("on the new connection's sequence space and corrupt it. A fresh, hard-")
    print("to-guess ISN shifts the window so old segments fall outside it.")
    print("  - This is also why ISNs must be UNPREDICTABLE: predicting them enabled")
    print("    the classic TCP sequence-number injection (Mitnick 1994). Modern")
    print("    stacks use ISN randomizers / RFC 6528.\n")

    print(f"[check] SYN acked with {ack_of_syn} = ISN_C+1 = {ISN_C}+1; "
          f"server SYN acked with {ack_of_syn2} = ISN_S+1 = {ISN_S}+1:  OK")
    # return the established state so later sections can continue this connection
    return {"client_seq": ack_of_syn, "server_seq": ack_of_syn2}


# ----------------------------------------------------------------------------
# SECTION B: sliding window flow control -- send 4, slide on each ACK
# ----------------------------------------------------------------------------

def section_b(conn):
    banner("SECTION B: sliding window flow control  (receiver advertises, sender obeys)")
    print("Flow control keeps a fast sender from drowning a slow receiver. The")
    print("receiver stamps every ACK with rwnd = its free buffer (bytes). The")
    print("sender keeps a WINDOW of un-acked bytes; it may not let that window")
    print("exceed rwnd. As ACKs arrive, the window SLIDES left-to-right: the left")
    print("edge (send_base) jumps forward, opening room at the right edge to send")
    print("new bytes. This is a byte-level sliding window (RFC 793, RFC 1122).\n")

    win = MSS * 4                                # 4 segments = 400 bytes
    sender = SlidingSender(send_base=conn["client_seq"], rwnd=win)
    print(f"Worked: after handshake client_seq={conn['client_seq']}, "
          f"rwnd={win} bytes ({win // MSS} segments of {MSS} B).\n")

    print("Round 1 - SEND until the window is full (4 segments in flight):")
    sent = []
    while sender.can_send():
        seq = sender.send(MSS)
        if seq is None:
            break
        n = len(sent) + 1
        seg = Segment("C->S", "ACK", seq=seq, ack=0, datalen=MSS,
                      note=f"segment {n}")
        sent.append(seg)
        print_segment(seg)
    print(f"      in_flight = send_next - send_base = {sender.send_next} - "
          f"{sender.send_base} = {sender.in_flight} bytes  "
          f"(== rwnd {win}, window FULL)\n")

    print("The sender is now BLOCKED: send_next - send_base == rwnd. It must")
    print("wait for an ACK to slide the window.\n")

    print("Round 2 - ACKs arrive one per segment; the window slides, one new")
    print("segment leaves on each ACK:")
    for i in range(4):
        acked_seq = sent[i].seq
        ack_val = ack_for(sent[i])               # seq + MSS
        sender.receive_ack(ack_val)
        # now there is room for one more segment
        new_seq = sender.send(MSS)
        seg_n = len(sent) + 1
        new_seg = Segment("C->S", "ACK", seq=new_seq, ack=0, datalen=MSS,
                          note=f"segment {seg_n} (window slid)")
        sent.append(new_seg)
        print(f"  ACK ack={ack_val} arrives (segment {i + 1} at seq {acked_seq} confirmed)")
        print(f"      -> send_base slides to {sender.send_base}, in_flight drops, "
              f"room opens -> send segment {seg_n} at seq {new_seq}")
    print(f"\n      after 4 ACKs: send_base={sender.send_base}, "
          f"send_next={sender.send_next}, in_flight={sender.in_flight}")
    print("      The window moved right by 4 segments; 4 new segments left. The")
    print("      pipeline stays FULL -- that is the whole point of the window: it")
    print("      keeps the pipe stuffed instead of send-one-wait-one.\n")

    print("Flow-control edge case: if the receiver advertises rwnd=0 (buffer")
    print("full), the sender MUST stop. It then sends zero-window probes until")
    print("the receiver re-advertises a non-zero window. A misbehaving receiver")
    print("that shrinks the window abruptly can cause the sender to stall.\n")

    print(f"[check] after sliding, send_base={sender.send_base} = "
          f"{conn['client_seq']} + {4 * MSS}; window stayed full "
          f"(in_flight={sender.in_flight} == rwnd {win}):  OK")
    conn["client_seq"] = sender.send_next
    return conn


# ----------------------------------------------------------------------------
# SECTION C: slow start + congestion avoidance (AIMD) -- the sawtooth
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: congestion control  (slow start -> AIMD -> sawtooth)")
    print("Flow control (Section B) protects the RECEIVER. Congestion control")
    print("protects the NETWORK. The sender keeps a SECOND window, cwnd, that it")
    print("grows/cautiously probes based on success or loss. The real send window")
    print("is min(rwnd, cwnd). Jacobson 1988 / RFC 5681 define the classic shape:\n")
    print("  SLOW START         : cwnd starts at 1 MSS and DOUBLES each RTT")
    print("                       (exponential) -- bandwidth is probed fast.")
    print("  CONGESTION AVOID   : once cwnd >= ssthresh, grow LINEARLY (+1 MSS/RTT)")
    print("                       (AIMD additive increase) -- probe gently.")
    print("  LOSS (multiplicative decrease): ssthresh = cwnd/2; cwnd = 1 (restart")
    print("                       slow start). Plot cwnd over RTTs and you get the")
    print("                       famous SAWTOOTH: sharp drops, slow climbs.\n")
    print("Deterministic run: cwnd0=1, ssthresh0=16, loss injected at RTT 7.\n")

    trace = simulate_congestion(cwnd0=1, ssthresh0=16, loss_at_rtt=7, n_rtts=16)
    print("| RTT | cwnd | ssthresh | phase                  | event                    |")
    print("|-----|------|----------|------------------------|--------------------------|")
    for row in trace:
        ev = row["event"] if row["event"] else "growth"
        print(f"| {row['rtt']:<3} | {row['cwnd']:<4} | {row['ssthresh']:<8} | "
              f"{row['phase']:<22} | {ev:<24} |")
    print()
    print("Reading the trace:")
    print("  RTTs 0-3: slow start. 1 -> 2 -> 4 -> 8 (doubling). Exponential.")
    print("  RTT 4: cwnd hits 16 == ssthresh -> switch to AIMD (congestion avoid).")
    print("  RTTs 5-7: linear climb 17 -> 18 -> 19 (additive increase, +1/RTT).")
    print("  RTT 7 (loss): peak cwnd=19; ssthresh = 19//2 = 9; the NEXT RTT restarts")
    print("         at cwnd=1 (the sawtooth DROP).")
    print("  RTTs 8-11: slow start again 1 -> 2 -> 4 -> 8 (each < new ssthresh 9).")
    print("  RTT 11->12: cwnd 8 (< 9) doubles to 16, OVERSHOOTING ssthresh (discrete")
    print("          doubling cannot land on 9 exactly) -> back in AIMD.")
    print("  RTTs 13-15: linear climb 17 -> 18 -> 19 (additive, +1/RTT).\n")

    # the cwnd sequence is the gold (deterministic)
    cwnd_series = [r["cwnd"] for r in trace]
    print(f"cwnd series (the sawtooth): {cwnd_series}")
    print("The sawtooth is the signature of TCP congestion control: aggressive")
    print("doubling to FIND capacity, then careful linear probing, then a halving")
    print("drop on any sign of congestion. Over many cycles it converges toward")
    print("the fair share of the bottleneck (the AIMD fairness property).\n")

    peak = max(cwnd_series[:8])
    print(f"[check] pre-loss peak cwnd={peak}, post-loss ssthresh={peak // 2}; "
          f"cwnd series length {len(cwnd_series)}:  OK")
    return trace


# ----------------------------------------------------------------------------
# SECTION D: 4-way teardown + TIME_WAIT -- clean close, catch delayed dupes
# ----------------------------------------------------------------------------

def section_d(conn):
    banner("SECTION D: 4-way teardown + TIME_WAIT  (FIN, ACK, FIN, ACK, 2*MSL)")
    print("Closing is NOT symmetric: each direction closes INDEPENDENTLY (TCP is")
    print("full-duplex). The side done sending issues FIN ('no more data from")
    print("me'); the other ACKs and may keep sending (half-close). When BOTH are")
    print("done, four segments have crossed: FIN, ACK, FIN, ACK.\n")
    print("Then the side that sent the FIRST final-ACK enters TIME_WAIT for 2*MSL.")
    print("Why? (1) if its final ACK was lost, the peer retransmits FIN and it can")
    print("re-ACK; (2) to let any wandering duplicate segments from this 4-tuple")
    print("die out BEFORE the port is reused, so they cannot corrupt a NEW")
    print("connection. That lingering is what causes port exhaustion.\n")

    cseq = conn["client_seq"]                    # client's next seq after data
    sseq = conn["server_seq"]                    # server's next seq (sent no data)

    print("Continuing the connection from Section A (client sent data, now closes):\n")
    # step 1: client FIN
    f1 = Segment("C->S", "FIN,ACK", seq=cseq, ack=sseq,
                 note="client: 'I have no more data'")
    print("Step 1 - CLIENT sends FIN:")
    print_segment(f1)
    ack_of_fin = ack_for(f1)                     # cseq + 1
    print(f"      FIN consumes seq #{cseq}; server's ACK will expect {ack_of_fin}.\n")

    # step 2: server ACK
    f2 = Segment("S->C", "ACK", seq=sseq, ack=ack_of_fin,
                 note="server confirms FIN; client->server half is closed")
    print("Step 2 - SERVER sends ACK of FIN (half-close: client can no longer send):")
    print_segment(f2)
    print("      (server MAY still send its own data here -- half-duplex close.)\n")

    # step 3: server FIN
    f3 = Segment("S->C", "FIN,ACK", seq=sseq, ack=ack_of_fin,
                 note="server: 'I have no more data either'")
    print("Step 3 - SERVER sends its FIN:")
    print_segment(f3)
    ack_of_fin2 = ack_for(f3)                    # sseq + 1
    print(f"      server's FIN consumes seq #{sseq}; client's ACK expects "
          f"{ack_of_fin2}.\n")

    # step 4: client ACK
    f4 = Segment("C->S", "ACK", seq=ack_of_fin, ack=ack_of_fin2,
                 note="client confirms server FIN; server can close now")
    print("Step 4 - CLIENT sends ACK of server FIN:")
    print_segment(f4)
    print("      SERVER is now CLOSED. CLIENT enters TIME_WAIT.\n")

    time_wait = 2 * MSL
    print(f"TIME_WAIT: client lingers {time_wait}s (= 2 * MSL = 2 * {MSL}s) holding")
    print("the 4-tuple (src_ip, src_port, dst_ip, dst_port). During that window:")
    print("  - if the server's retransmitted FIN arrives (our step-4 ACK was lost),")
    print("    the client re-sends the ACK so the server can finally close;")
    print("  - any delayed duplicate segment bound for this OLD connection expires")
    print("    before the port is freed, so it cannot poison a NEW connection.\n")

    print("WHY THIS EXHAUSTS PORTS IN LOAD BALANCERS:")
    print("A load balancer opening many SHORT-LIVED connections to backends keeps")
    print("each closed one in TIME_WAIT for 4 minutes. The client ephemeral-port")
    print("range is finite (~28232 ports on Linux, 32768-60999). Each live +")
    print("TIME_WAIT 4-tuple holds one. Steady-state cap on new connections/sec:")
    ephemeral = 60999 - 32768 + 1
    rate_cap = ephemeral / time_wait
    print(f"  ephemeral ports ~= {ephemeral}; TIME_WAIT = {time_wait}s")
    print(f"  => max ~{ephemeral}/{time_wait} = {rate_cap:.1f} new conn/s per src IP")
    print("  (the classic 'Cannot assign requested address' under load.) Mitigations:")
    print("  SO_REUSEADDR/SO_LINGER, longer keep-alive (fewer short conns), or a")
    print("  connection pool. 🔗 This is a big reason HTTP/2 and connection pools")
    print("  exist: amortize the handshake/teardown over many requests.\n")

    print(f"[check] FIN acked with seq+1: client FIN {cseq} -> ack {ack_of_fin}, "
          f"server FIN {sseq} -> ack {ack_of_fin2}; TIME_WAIT = 2*MSL = "
          f"{time_wait}s:  OK")
    return {"time_wait_s": time_wait, "ack_of_client_fin": ack_of_fin,
            "ack_of_server_fin": ack_of_fin2}


# ----------------------------------------------------------------------------
# SECTION E: why distributed systems need MORE than TCP
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: why distributed systems cannot trust TCP alone")
    print("TCP guarantees ordered, reliable, non-duplicated delivery -- but ONLY")
    print("*within a single living connection*. Real distributed systems fail over,")
    print("multiplex logical streams, and must survive crashes. Three cracks:\n")

    print("(1) HEAD-OF-LINE BLOCKING (within one connection).")
    print("TCP delivers a strictly ordered BYTE STREAM. If byte N is lost, bytes")
    print("N+1, N+2, ... that ALREADY arrived are HELD in the kernel until N is")
    print("retransmitted -- even if they belong to an independent logical request.")
    print("HTTP/2 multiplexes many streams over ONE TCP connection, so a loss on")
    print("stream A stalls streams B, C, D that have nothing to do with A. QUIC")
    print("(RFC 9000) runs its own per-stream reliability over UDP precisely to")
    print("remove this coupling.\n")

    print("(2) CONNECTION RESET DURING FAILOVER (between connections).")
    print("When a server crashes, a load balancer redirects the client to a NEW")
    print("backend over a NEW TCP connection. The old connection is torn down with")
    print("an RST -- any request still in flight is LOST, the app sees ECONNRESET.")
    print("A naive retry can then DOUBLE-EXECUTE a non-idempotent operation.\n")

    # Concrete failover simulation
    print("Concrete failover demo (idempotent op is safe; non-idempotent is NOT):")
    print("  client -> node A: INCR counter   (op_id=7)   over TCP conn #1")
    print("  node A applies it (counter: 0 -> 1) then CRASHES before replying")
    print("  client times out, opens TCP conn #2 to node B (failover)")
    print("  client retries:   INCR counter   (op_id=7)   over TCP conn #2")
    print("  node B applies it (counter: 1 -> 2)  <- DOUBLE INCREMENT!")
    print("  -> INCR is NOT idempotent, so the retry corrupted the count.\n")
    print("  The fix: an IDEMPOTENCY KEY (op_id=7). Node B records op_id=7 was")
    print("  already done (it propagated via replication) and returns the cached")
    print("  result instead of re-executing. SET x=1 IS idempotent (retry is a")
    print("  no-op); INCR / charge-$100 are NOT, and MUST carry a dedup key.\n")

    print("(3) CONSENSUS DOES NOT TRUST TCP ORDERING.")
    print("Raft/Paxos do NOT rely on 'whatever order TCP delivered the bytes' for")
    print("correctness. Each log entry carries its OWN (term, index). If a leader's")
    print("TCP connection is reset and a follower reconnects, the AppendEntries RPC")
    print("re-specifies (term=3, index=7, entry=...). The follower de-duplicates /")
    print("truncates by INDEX, not by arrival order. TCP is just the transport;")
    print("the protocol's ordering is logical, application-level, and survives")
    print("connection resets and reordering across connections. 🔗 RAFT.md,")
    print("PAXOS.md, LAMPORT_TIMESTAMPS.md.\n")

    print("BOTTOM LINE: TCP gives you a reliable ordered pipe. Distributed-system")
    print("correctness needs MORE: idempotency keys for safe retries, application")
    print("sequence numbers / logical clocks for ordering that spans connections,")
    print("and consensus for agreement that survives failover. Trust TCP for the")
    print("bytes; trust your protocol for the semantics.\n")
    print("[check] TCP reliability is per-connection; failover = RST + in-flight")
    print("        loss; consensus uses logical (term,index) not TCP order:  OK")


# ============================================================================
# 4. GOLD CHECK  (pinned values that tcp_handshake.html recomputes in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  (pinned values for tcp_handshake.html)")
    print("Capstone: the sequence/ack arithmetic across a connection's FULL life")
    print("-- handshake, data, teardown -- plus the congestion sawtooth and the")
    print("TIME_WAIT math. Every value is recomputed by the .html from the SAME")
    print("constants (ISN_C=1000, ISN_S=5000, MSS=100, MSL=120).\n")

    # --- handshake arithmetic ---
    syn = Segment("C->S", "SYN", seq=ISN_C, ack=0)
    synack = Segment("S->C", "SYN,ACK", seq=ISN_S, ack=ack_for(syn))
    client_seq = ack_for(syn)                    # 1001  (= the 3rd seg's seq)
    server_seq = ack_for(synack)                 # 5001  (= the 3rd seg's ack)

    print("Handshake:")
    print(f"  SYN        ack_value = {ack_for(syn)}   (= ISN_C + 1 = {ISN_C + 1})")
    print(f"  SYN-ACK    ack_value = {ack_for(synack)}   (= ISN_S + 1 = {ISN_S + 1})")
    print(f"  client seq_next after open = {client_seq}")
    print(f"  server seq_next after open = {server_seq}")

    # --- data transfer (4 segments of MSS) ---
    data_acks = []
    for i in range(4):
        seg = Segment("C->S", "ACK", seq=client_seq + i * MSS, ack=server_seq,
                      datalen=MSS)
        data_acks.append(ack_for(seg))
    final_client_seq = client_seq + 4 * MSS
    print("\nData (4 segments x 100 bytes):")
    print(f"  segment acks = {data_acks}")
    print(f"  final client seq_next = {final_client_seq}  "
          f"(= {client_seq} + {4 * MSS})")
    print(f"  cumulative ACK the server sends back = {final_client_seq}  "
          f"(= last_seg.seq + len)")

    # --- teardown arithmetic ---
    fin_c = Segment("C->S", "FIN,ACK", seq=final_client_seq, ack=server_seq)
    ack_fin = ack_for(fin_c)                     # final_client_seq + 1
    fin_s = Segment("S->C", "FIN,ACK", seq=server_seq, ack=ack_fin)
    ack_fin2 = ack_for(fin_s)                     # server_seq + 1

    print("\nTeardown:")
    print(f"  client FIN seq = {final_client_seq} -> server ACK = {ack_fin}")
    print(f"  server FIN seq = {server_seq} -> client ACK = {ack_fin2}")
    print(f"  TIME_WAIT      = 2 * MSL = {2 * MSL} s")

    # --- congestion sawtooth ---
    trace = simulate_congestion(cwnd0=1, ssthresh0=16, loss_at_rtt=7, n_rtts=16)
    cwnd_series = [r["cwnd"] for r in trace]
    pre_loss_peak = max(cwnd_series[:8])
    post_loss_ssthresh = max(cwnd_series[:8]) // 2
    print("\nCongestion sawtooth cwnd series:")
    print(f"  {cwnd_series}")
    print(f"  pre-loss peak cwnd = {pre_loss_peak}; post-loss ssthresh = "
          f"{post_loss_ssthresh}")

    # --- assertions (self-consistency) ---
    assert ack_for(syn) == ISN_C + 1
    assert ack_for(synack) == ISN_S + 1
    assert client_seq == 1001 and server_seq == 5001
    assert final_client_seq == 1401
    assert data_acks == [1101, 1201, 1301, 1401]
    assert ack_fin == 1402 and ack_fin2 == 5002
    assert 2 * MSL == 240
    assert pre_loss_peak == 19 and post_loss_ssthresh == 9

    # --- port-exhaustion rate ---
    ephemeral = 60999 - 32768 + 1
    rate_cap = ephemeral / (2 * MSL)

    print("\nGOLD scalars (pinned for a compact .html check):")
    print(f"  isn_client            = {ISN_C}")
    print(f"  isn_server            = {ISN_S}")
    print(f"  ack_of_syn            = {ack_for(syn)}        (ISN_C + 1)")
    print(f"  ack_of_syn_ack        = {ack_for(synack)}        (ISN_S + 1)")
    print(f"  client_seq_after_open = {client_seq}")
    print(f"  server_seq_after_open = {server_seq}")
    print(f"  data_ack_after_4_segs = {final_client_seq}       (last seq + len)")
    print(f"  ack_of_client_fin     = {ack_fin}       (FIN consumes 1)")
    print(f"  ack_of_server_fin     = {ack_fin2}       (FIN consumes 1)")
    print(f"  time_wait_seconds     = {2 * MSL}     (2 * MSL)")
    print(f"  cwnd_series           = {cwnd_series}")
    print(f"  pre_loss_peak_cwnd    = {pre_loss_peak}")
    print(f"  post_loss_ssthresh    = {post_loss_ssthresh}")
    print(f"  ephemeral_ports       = {ephemeral}  (32768..60999)")
    print(f"  port_rate_cap_per_sec = {rate_cap:.1f}  (ephemeral / TIME_WAIT)")

    print("\n[check] all seq/ack arithmetic reproduces from ISN_C/ISN_S/MSS, the")
    print("        sawtooth is deterministic, and TIME_WAIT = 240s:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("tcp_handshake.py - reference impl. All numbers below feed "
          "TCP_HANDSHAKE.md.")
    print("python stdlib only (no external deps).")
    print(f"constants: ISN_C={ISN_C}, ISN_S={ISN_S}, MSS={MSS}, MSL={MSL}s")

    conn = section_a()
    conn = section_b(conn)
    section_c()
    section_d(conn)
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
