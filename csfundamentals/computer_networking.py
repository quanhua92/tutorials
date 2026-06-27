"""Computer Networking — ground-truth simulations of core network protocols.

Four simulations covering the transport, naming, and application layers:

  1. TCP 3-way handshake  — SYN / SYN-ACK / ACK state machine (+ 4-way teardown)
  2. TCP congestion control — slow start -> congestion avoidance -> fast recovery
     (Reno), with cwnd evolution per RTT and injected loss events
  3. DNS resolution         — recursive query chain (stub -> root -> TLD -> auth)
  4. HTTP/1.1 vs HTTP/2 vs HTTP/3 — setup RTT, multiplexing, header compression

Every number printed below is produced by running this file; nothing is
hand-computed.  The HTML companion recomputes the gold values in JavaScript
and compares.  Capture with:

    python3 computer_networking.py > computer_networking_output.txt 2>/dev/null
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Section 1 — TCP 3-way handshake (and 4-way teardown)
# ---------------------------------------------------------------------------

# TCP finite-state machine (connection-establishment half).
# Each endpoint tracks its current state, next sequence number, and the
# sequence number it expects to receive next.

TCP_STATES = {
    "CLOSED", "LISTEN", "SYN_SENT", "SYN_RCVD",
    "ESTABLISHED", "FIN_WAIT_1", "FIN_WAIT_2",
    "CLOSE_WAIT", "LAST_ACK", "TIME_WAIT", "CLOSED2",
}


class TCPEndpoint:
    """One side of a TCP connection."""

    def __init__(self, name: str, isn: int):
        self.name = name
        self.state = "CLOSED"
        self.snd_nxt = isn          # next sequence number to send
        self.rcv_nxt = 0            # next sequence number expected to receive

    def send(self, flags: str, payload: int = 0) -> tuple[str, int, int]:
        """Emit a segment. Returns (flags, seq, ack). Consumes payload bytes."""
        seq = self.snd_nxt
        ack = self.rcv_nxt
        # SYN and FIN each consume one sequence number; data consumes len.
        if "S" in flags or "F" in flags:
            self.snd_nxt += 1
        self.snd_nxt += payload
        return (flags, seq, ack)

    def __repr__(self) -> str:
        return (f"{self.name}[{self.state}] snd_nxt={self.snd_nxt}"
                f" rcv_nxt={self.rcv_nxt}")


def handshake_trace(
    client_isn: int, server_isn: int
) -> tuple[list[tuple[str, str, str, int, int]], TCPEndpoint, TCPEndpoint]:
    """Run a full 3-way handshake. Returns the message log + endpoints."""
    client = TCPEndpoint("client", client_isn)
    server = TCPEndpoint("server", server_isn)
    log: list[tuple[str, str, str, int, int]] = []  # (direction, flags, desc, seq, ack)

    # --- Server starts listening ---
    server.state = "LISTEN"

    # --- Message 1: client -> server, SYN ---
    client.state = "SYN_SENT"
    flags, seq, ack = client.send("S")          # SYN consumes 1 seq
    client.rcv_nxt = 0
    log.append(("client -> server", "SYN",
                "synchronize, client_isn", seq, ack))

    # Server receives SYN -> SYN_RCVD, records expected seq, echoes ISN+1
    server.rcv_nxt = seq + 1
    server.state = "SYN_RCVD"

    # --- Message 2: server -> client, SYN-ACK ---
    flags, seq, ack = server.send("S")          # server's SYN (server_isn)
    s_syn_seq = seq
    log.append(("server -> client", "SYN-ACK",
                "synchronize + acknowledge", seq, ack))  # ack = client_isn+1

    # Client receives SYN-ACK -> ESTABLISHED
    client.rcv_nxt = s_syn_seq + 1
    client.state = "ESTABLISHED"

    # --- Message 3: client -> server, ACK ---
    flags, seq, ack = client.send("")           # pure ACK consumes no seq
    log.append(("client -> server", "ACK",
                "finalize handshake", seq, ack))            # ack = server_isn+1

    # Server receives ACK -> ESTABLISHED
    server.state = "ESTABLISHED"
    return log, client, server


def teardown_trace(
    client: TCPEndpoint, server: TCPEndpoint
) -> list[tuple[str, str, str, int, int]]:
    """Run a 4-way FIN teardown from an ESTABLISHED state. Returns log."""
    log: list[tuple[str, str, str, int, int]] = []

    # --- Message 1: client -> server, FIN (active close) ---
    client.state = "FIN_WAIT_1"
    flags, seq, ack = client.send("F")          # FIN consumes 1 seq
    c_fin_seq = seq
    log.append(("client -> server", "FIN",
                "active close (no more data)", seq, ack))
    server.rcv_nxt = c_fin_seq + 1

    # --- Message 2: server -> client, ACK ---
    server.state = "CLOSE_WAIT"
    flags, seq, ack = server.send("")
    log.append(("server -> client", "ACK",
                "acknowledge client FIN", seq, ack))
    client.state = "FIN_WAIT_2"

    # --- Message 3: server -> client, FIN (passive close) ---
    server.state = "LAST_ACK"
    flags, seq, ack = server.send("F")
    s_fin_seq = seq
    log.append(("server -> client", "FIN",
                "passive close", seq, ack))
    client.rcv_nxt = s_fin_seq + 1

    # --- Message 4: client -> server, ACK ---
    client.state = "TIME_WAIT"
    flags, seq, ack = client.send("")
    log.append(("client -> server", "ACK",
                "final ack, then 2*MSL wait", seq, ack))
    server.state = "CLOSED"
    client.state = "CLOSED"  # after TIME_WAIT
    return log


def section_tcp_handshake() -> None:
    print("=" * 72)
    print("=== TCP 3-Way Handshake — SYN / SYN-ACK / ACK")
    print("=" * 72)
    client_isn = 1000
    server_isn = 5000
    log, client, server = handshake_trace(client_isn, server_isn)
    print(f"  client_isn = {client_isn}   server_isn = {server_isn}")
    print()
    print("  #   direction            flags     seq    ack   note")
    print("  --  -------------------  --------  ----   ----  ----------------------")
    for i, (direc, flags, note, seq, ack) in enumerate(log, 1):
        print(f"  {i}   {direc:<19}  {flags:<8}  {seq:<5}  "
              f"{ack:<4} {note}")
    print()
    print(f"  client final: {client}")
    print(f"  server final: {server}")
    print()
    ok = (
        client.state == "ESTABLISHED"
        and server.state == "ESTABLISHED"
        and client.snd_nxt == client_isn + 1     # ISN + SYN
        and server.snd_nxt == server_isn + 1
        and client.rcv_nxt == server_isn + 1     # expects server's next byte
        and server.rcv_nxt == client_isn + 1
    )
    print(f"  both endpoints ESTABLISHED, seq numbers advanced"
          f"   [check] {'OK' if ok else 'FAIL'}")
    assert ok

    print()
    print("  --- 4-way teardown (FIN / ACK / FIN / ACK) ---")
    tlog = teardown_trace(client, server)
    print()
    print("  #   direction            flags     note")
    print("  --  -------------------  --------  ----------------------")
    for i, (direc, flags, note, seq, ack) in enumerate(tlog, 1):
        print(f"  {i}   {direc:<19}  {flags:<8}  {note}")
    print()
    print(f"  client final: {client}")
    print(f"  server final: {server}")
    print(f"  4 messages exchanged, connection gracefully closed"
          f"   [check] {'OK' if len(tlog) == 4 else 'FAIL'}")
    assert len(tlog) == 4


# ---------------------------------------------------------------------------
# Section 2 — TCP congestion control (Reno)
# ---------------------------------------------------------------------------

# Per-RTT discrete model of TCP Reno congestion control.  The congestion
# window (cwnd, in MSS segments) determines how much unacknowledged data the
# sender may have in flight per round-trip time.
#
#   SLOW START          : cwnd doubles every RTT (exponential) while
#                         cwnd < ssthresh.
#   CONGESTION AVOIDANCE: cwnd grows by 1 MSS per RTT (linear / AIMD).
#   FAST RECOVERY       : on 3 duplicate ACKs, halve cwnd -> ssthresh,
#                         set cwnd = ssthresh, resume CA (no timeout).
#   TIMEOUT             : ssthresh = cwnd/2, cwnd = 1, restart slow start.

SLOW_START = "slow_start"
CONGESTION_AVOIDANCE = "congestion_avoidance"


def simulate_congestion_control(
    n_rtts: int,
    initial_ssthresh: int,
    losses: dict[int, str],
) -> list[tuple[int, str, int, int, str]]:
    """Run a deterministic Reno simulation.

    ``losses`` maps RTT number -> event type ("dup_ack" or "timeout").  At the
    start of a loss RTT, the recorded cwnd is the pre-loss value; the loss is
    then applied to set up the NEXT round.
    Returns a list of (rtt, state, cwnd, ssthresh, event).
    """
    cwnd = 1
    ssthresh = initial_ssthresh
    state = SLOW_START
    trace: list[tuple[int, str, int, int, str]] = []
    for rtt in range(1, n_rtts + 1):
        event = "-"
        # Record state at the START of this RTT (the window in flight now).
        if rtt in losses:
            event = losses[rtt]
            trace.append((rtt, state, cwnd, ssthresh, event))
            # Apply the loss -> changes cwnd/ssthresh for the NEXT round.
            if event == "dup_ack":                 # fast retransmit / recovery
                ssthresh = max(cwnd // 2, 2)
                cwnd = ssthresh
                state = CONGESTION_AVOIDANCE
            else:                                  # timeout
                ssthresh = max(cwnd // 2, 2)
                cwnd = 1
                state = SLOW_START
        else:
            trace.append((rtt, state, cwnd, ssthresh, event))
            # Grow the window for the next RTT.
            if state == SLOW_START:
                cwnd *= 2
                if cwnd >= ssthresh:
                    state = CONGESTION_AVOIDANCE
            else:                                  # congestion avoidance
                cwnd += 1
    return trace


def section_congestion_control() -> None:
    print()
    print("=" * 72)
    print("=== TCP Congestion Control — Reno (slow start / avoidance / fast recovery)")
    print("=" * 72)
    initial_ssthresh = 16
    losses = {9: "dup_ack", 16: "timeout"}
    n_rtts = 24
    trace = simulate_congestion_control(n_rtts, initial_ssthresh, losses)
    print(f"  initial ssthresh = {initial_ssthresh} MSS   "
          f"losses @ RTT {{9: dup_ack, 16: timeout}}")
    print()
    print("  RTT  state                cwnd  ssthresh  event")
    print("  ---  -------------------  ----  --------  ---------")
    cwnd_seq = []
    for rtt, state, cwnd, ssthresh, event in trace:
        cwnd_seq.append(cwnd)
        ev = "" if event == "-" else " <== " + event
        print(f"  {rtt:>3}  {state:<19}  {cwnd:>4}  {ssthresh:>8}  "
              f"{event}{ev if False else ''}")
        if event != "-":
            print(f"       ^^^ {event}: ssthresh <- {ssthresh}, "
                  f"cwnd <- {cwnd}")

    peak = max(cwnd_seq)
    n_slow = sum(1 for _, s, _, _, _ in trace if s == SLOW_START)
    n_avoid = sum(1 for _, s, _, _, _ in trace if s == CONGESTION_AVOIDANCE)
    print()
    print(f"  peak cwnd       = {peak} MSS")
    print(f"  rounds in slow start / congestion avoidance = "
          f"{n_slow} / {n_avoid}")
    print("  cwnd sequence (start of each RTT):")
    print(f"  {cwnd_seq}")

    # Three classic AIMD properties to verify:
    #   (a) slow start is exponential (1->2->4->8->16),
    #   (b) after a dup-ACK loss cwnd halves (20 -> 10),
    #   (c) after a timeout cwnd resets to 1.
    ss_prefix = [t[2] for t in trace[:4]]           # first 4 rounds
    ok_exp = ss_prefix == [1, 2, 4, 8]
    ok_halve = trace[9][2] == 10 and trace[8][2] == 20   # RTT10 cwnd=10 after RTT9 loss
    ok_reset = trace[16][2] == 1                      # RTT17 cwnd=1 after RTT16 timeout
    ok = ok_exp and ok_halve and ok_reset
    print()
    print(f"  slow start exponential [1,2,4,8]: {ok_exp}")
    print(f"  dup-ACK halves cwnd (20 -> 10): {ok_halve}")
    print(f"  timeout resets cwnd to 1: {ok_reset}")
    print(f"  [check] {'OK' if ok else 'FAIL'}   (Reno AIMD verified)")
    assert ok


# ---------------------------------------------------------------------------
# Section 3 — DNS resolution (recursive query chain)
# ---------------------------------------------------------------------------

# A DNS resolution for "www.example.com" walks the hierarchical name space.
# The stub resolver's query to the recursive resolver is RECURSIVE (the
# resolver does all the work and returns the final answer).  The recursive
# resolver's own queries to root / TLD / authoritative servers are ITERATIVE:
# it follows referrals one hop at a time.

def resolve_dns(
    domain: str,
    browser_cache: dict[str, tuple[str, int]],
    os_cache: dict[str, tuple[str, int]],
    zone_db: dict[str, str],
) -> tuple[list[tuple[str, str, str, str]], str, list[str]]:
    """Simulate a full recursive DNS resolution.

    Returns (trace, resolved_ip, cache_path).
    ``zone_db`` maps a server label -> referral or answer string.
    """
    trace: list[tuple[str, str, str, str]] = []   # (querier, server, type, result)

    # Step 1: browser cache
    if domain in browser_cache:
        ip, _ttl = browser_cache[domain]
        trace.append(("browser", "browser_cache", "A (hit)",
                      f"{ip} (cached)"))
        return trace, ip, ["browser_cache"]

    # Step 2: OS cache
    if domain in os_cache:
        ip, _ttl = os_cache[domain]
        trace.append(("stub", "os_cache", "A (hit)", f"{ip} (cached)"))
        return trace, ip, ["os_cache"]

    cache_path = ["browser_cache:MISS", "os_cache:MISS"]

    # Step 3: stub -> recursive resolver (RECURSIVE query)
    trace.append(("stub_resolver", "recursive_resolver",
                  "A (recursive)", "please resolve fully"))
    cache_path.append("recursive_resolver")

    # The recursive resolver now walks the hierarchy ITERATIVELY.
    # Root -> TLD -> Authoritative
    for hop in ("root_server", "tld_server", "authoritative_server"):
        qtype = "A" if hop == "authoritative_server" else "NS (referral)"
        result = zone_db[hop]
        trace.append(("recursive_resolver", hop, qtype, result))
        cache_path.append(hop)

    # Final answer
    ip = zone_db["answer"]
    trace.append(("recursive_resolver", "stub_resolver",
                  "A (answer)", f"{ip} TTL=3600"))
    return trace, ip, cache_path


def section_dns_resolution() -> None:
    print()
    print("=" * 72)
    print("=== DNS Resolution — recursive query chain (stub -> root -> TLD -> auth)")
    print("=" * 72)
    domain = "www.example.com"
    browser_cache: dict[str, tuple[str, int]] = {}
    os_cache: dict[str, tuple[str, int]] = {}
    zone_db = {
        "root_server": "referral -> com. TLD servers",
        "tld_server": "referral -> example.com. authoritative servers",
        "authoritative_server": "referral -> ns.example.com",
        "answer": "93.184.216.34",
    }
    print(f"  resolving: {domain}")
    print("  browser cache: empty   OS cache: empty")
    print()

    trace, ip, path = resolve_dns(domain, browser_cache, os_cache, zone_db)
    print("  #   querier               server                 query            result")
    print("  --  -------------------   -------------------    --------------   -----------------------------")
    for i, (querier, server, qtype, result) in enumerate(trace, 1):
        print(f"  {i}   {querier:<21}  {server:<21}  "
              f"{qtype:<14}  {result}")
    print()
    print(f"  resolved IP = {ip}   TTL = 3600s")
    print(f"  resolution hops = {len(path)}")
    print(f"  path: {' -> '.join(path)}")

    # First lookup must be a full miss (no cache); second lookup must hit.
    # Path: browser_cache:MISS, os_cache:MISS, recursive_resolver,
    #       root_server, tld_server, authoritative_server  => 6 hops.
    ok_first = ip == "93.184.216.34" and len(path) == 6

    # Cache it and resolve again -> browser cache hit.
    browser_cache[domain] = (ip, 3600)
    trace2, ip2, path2 = resolve_dns(domain, browser_cache, os_cache, zone_db)
    ok_second = ip2 == ip and len(path2) == 1 and path2[0] == "browser_cache"
    print()
    print("  --- second lookup (answer now cached) ---")
    print(f"  resolved IP = {ip2}   hops = {len(path2)}"
          f"   path = {path2}")
    print()
    print(f"  first  lookup: full miss, {len(path)} hops -> {ip}")
    print(f"  second lookup: cache hit, {len(path2)} hop  -> {ip2}")
    print(f"  [check] {'OK' if ok_first and ok_second else 'FAIL'}"
          f"   (caching eliminates the recursive walk)")
    assert ok_first and ok_second


# ---------------------------------------------------------------------------
# Section 4 — HTTP/1.1 vs HTTP/2 vs HTTP/3
# ---------------------------------------------------------------------------

# Comparison of setup cost (RTT) and fetch cost for a typical page: one HTML
# document plus N sub-resources (images, scripts, stylesheets), each requiring
# one round-trip to fetch after the connection is established.

def http_fetch_total(
    n_resources: int,
    max_conns: int,
    multiplex: bool,
    setup_rtt: int,
) -> tuple[int, int]:
    """Return (setup_rtt, fetch_rtt) for fetching ``n_resources``."""
    if multiplex:
        fetch_rtt = 1                     # all streams in parallel
    else:
        # Head-of-line blocking per connection: each conn fetches sequentially.
        fetch_rtt = math.ceil(n_resources / max_conns)
    return setup_rtt, fetch_rtt


def header_compression(
    header_lines: list[tuple[str, str, int]],
    static_table: dict[str, str],
) -> tuple[int, int, int]:
    """Return (raw, hpack, qpack) byte sizes for a header block.

    ``header_lines`` is a list of (name, value, raw_bytes).  A line whose
    value matches a static-table entry is replaced by a 1-2 byte index;
    the rest are Huffman-coded literals (~60% of raw).
    """
    raw = sum(b for _, _, b in header_lines)
    hpack = 0
    qpack = 0
    for name, value, raw_bytes in header_lines:
        if value == static_table.get(name):
            hpack += 2                       # indexed field line
            qpack += 2
        else:
            lit = max(raw_bytes * 6 // 10, 8)   # Huffman literal
            hpack += lit
            qpack += lit
    return raw, hpack, qpack


def section_http_comparison() -> None:
    print()
    print("=" * 72)
    print("=== HTTP/1.1 vs HTTP/2 vs HTTP/3 — multiplexing, header compression")
    print("=" * 72)
    n_resources = 12

    versions = [
        # name, setup_rtt, max_conns, multiplex, transport
        ("HTTP/1.1", 3, 6, False, "TCP + TLS 1.2"),
        ("HTTP/2",   2, 1, True,  "TCP + TLS 1.3"),
        ("HTTP/3",   1, 1, True,  "QUIC (UDP) + TLS 1.3"),
    ]

    print(f"  fetch: 1 HTML + {n_resources} resources (each 1 RTT to fetch)")
    print()
    print(f"  {'version':<9} {'transport':<22} {'setup':>5} {'fetch':>5}"
          f" {'total':>5}  notes")
    print(f"  {'-------':<9} {'---------':<22} {'-----':>5} {'-----':>5}"
          f" {'-----':>5}  -----")
    totals = {}
    for name, setup, conns, mux, transport in versions:
        s_rtt, f_rtt = http_fetch_total(n_resources, conns, mux, setup)
        total = s_rtt + f_rtt
        totals[name] = total
        note = "multiplexed" if mux else f"{conns} conns, HOL blocking"
        print(f"  {name:<9} {transport:<22} {s_rtt:>5} {f_rtt:>5}"
              f" {total:>5}  {note}")

    ok_speed = (totals["HTTP/1.1"] > totals["HTTP/2"] > totals["HTTP/3"])
    print()
    print(f"  totals: HTTP/1.1={totals['HTTP/1.1']} RTT,"
          f" HTTP/2={totals['HTTP/2']} RTT, HTTP/3={totals['HTTP/3']} RTT")
    print(f"  each version strictly faster than the previous: {ok_speed}")
    print(f"  [check] {'OK' if ok_speed else 'FAIL'}"
          f"   (HTTP/1.1 {totals['HTTP/1.1']} > HTTP/2 {totals['HTTP/2']}"
          f" > HTTP/3 {totals['HTTP/3']})")
    assert ok_speed

    # --- Header compression (HPACK for H2, QPACK for H3) ---
    print()
    print("  --- header compression (HPACK / QPACK) ---")
    static_table = {
        ":method": "GET",
        ":path": "/",
        ":scheme": "https",
        "host": "www.example.com",
        "user-agent": "Mozilla/5.0",
        "accept": "*/*",
        "accept-encoding": "gzip",
    }
    # (name, value, raw_bytes)  -- first 7 match the static table
    header_lines = [
        (":method", "GET", 38),
        (":path", "/", 26),
        (":scheme", "https", 39),
        ("host", "www.example.com", 72),
        ("user-agent", "Mozilla/5.0", 90),
        ("accept", "*/*", 36),
        ("accept-encoding", "gzip", 66),
        ("x-request-id", "abc123def456", 84),   # custom, not indexed
        ("authorization", "Bearer eyJ...", 96),  # custom, not indexed
    ]
    raw_header, hpack, qpack = header_compression(header_lines, static_table)
    hpack_ratio = hpack / raw_header * 100
    qpack_ratio = qpack / raw_header * 100
    print(f"  raw header size (HTTP/1.1) = {raw_header} bytes")
    print(f"  HTTP/2  HPACK              = {hpack} bytes  ({hpack_ratio:.1f}% of raw)")
    print(f"  HTTP/3  QPACK              = {qpack} bytes  ({qpack_ratio:.1f}% of raw)")
    ok_hpack = hpack < raw_header and qpack <= raw_header
    print(f"  [check] {'OK' if ok_hpack else 'FAIL'}"
          f"   (compression shrinks headers)")
    assert ok_hpack

    # --- Feature comparison matrix ---
    print()
    print("  --- feature comparison ---")
    print(f"  {'feature':<24} {'HTTP/1.1':<14} {'HTTP/2':<14} {'HTTP/3':<14}")
    print(f"  {'------':<24} {'-------':<14} {'------':<14} {'------':<14}")
    rows = [
        ("transport",            "TCP",          "TCP",          "QUIC (UDP)"),
        ("multiplexing",         "no",           "yes",          "yes"),
        ("head-of-line block",   "per-conn",     "TCP-level",    "none"),
        ("header format",        "text",         "binary+HPACK", "binary+QPACK"),
        ("server push",          "no",           "yes",          "no (removed)"),
        ("mandatory TLS",        "no",           "no (in prac.)", "yes (TLS 1.3)"),
        ("0-RTT resume",         "no",           "no",           "yes"),
    ]
    for feat, a, b, c in rows:
        print(f"  {feat:<24} {a:<14} {b:<14} {c:<14}")


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    section_tcp_handshake()
    section_congestion_control()
    section_dns_resolution()
    section_http_comparison()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
