"""Real-Time Protocols — ground-truth simulations of WebSocket, SSE,
long polling, and gRPC streaming.

Five simulations covering the real-time-communication stack. Pure Python
stdlib; no network, no sockets, no external libraries.

  1. WebSocket — full-duplex after an HTTP Upgrade + 101 Switching
     Protocols; 2-14 byte frame header; ping/pong heartbeat; close
     handshake. The only browser-native BIDIRECTIONAL option.
  2. SSE (Server-Sent Events) — single persistent HTTP connection, server
     pushes text frames (`id:`/`event:`/`data:`); built-in auto-reconnect
     via EventSource + Last-Event-ID. Server-to-client ONLY.
  3. Long polling — request -> hold -> response; client GETs, server holds
     until data or a ~30s timeout, then the client immediately re-GETs.
     Stateless and proxy-friendly, but a full HTTP handshake PER message.
  4. gRPC streaming — bidirectional streams over HTTP/2; Protocol Buffers
     with a 5-byte length prefix per message. The microservice-to-
     microservice standard (not browser-native without grpc-web).
  5. Comparison — latency, per-message overhead, session overhead,
     scalability, and a decision tree. One bad burst replayed under all
     four protocols.

Notes
-----
- A fixed traffic model (event rate, payload size, RTT, reconnect gap) is
  used so the output is byte-for-byte reproducible and the HTML gold-check
  recomputes identical values. Real networks vary; these are
  representative numbers from the source material.
- Per-message overhead values come from the protocol specs:
  * WebSocket frame header: FIN/RSV/opcode (1B) + length (1B) + 4B mask
    key for client->server (masked) = 6B typical (range 2-14B).
  * SSE: "id: N\\nevent: t\\ndata: ...\\n\\n" framing ~= 50B per event.
  * Long polling: a full HTTP request+response header set ~= 800B per
    message (the handshake repeats every cycle; there is no persistent
    connection).
  * gRPC: 1B compressed-flag + 4B big-endian length prefix = 5B per
    message, carried inside an HTTP/2 DATA frame.

Every number printed below is produced by running this file; nothing is
hand-computed. Capture with:

    python3 realtime_protocols.py > realtime_protocols_output.txt 2>/dev/null
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared constants — deterministic so the JS gold-check reproduces identical
# values.
# ---------------------------------------------------------------------------

PAYLOAD_BYTES = 100              # per-event message body (bytes)
EVENT_RATE = 10                 # events/sec (medium frequency session)
SESSION_SEC = 60                # session duration (seconds)
EVENTS = EVENT_RATE * SESSION_SEC   # 600 events per session

BASE_RTT_MS = 50                # one round-trip time (ms)
RECONNECT_GAP_MS = 50           # long-polling gap between cycles (ms)
BURST_K = 10                    # events arriving in one burst

# Per-message framing overhead (bytes), EXCLUDING the payload itself.
PER_MSG_BYTES = {
    "websocket": 6,     # FIN/opcode + length + 4B mask (masked client frame)
    "sse": 50,          # id/event/data lines + blank-line terminator
    "long_polling": 800,   # full HTTP req+resp headers per message
    "grpc": 5,          # 1B compressed-flag + 4B length prefix (protobuf)
}

# One-time connection-handshake overhead (bytes). For long_polling this is
# NOT one-time — every message incurs a fresh handshake — so it is folded
# into PER_MSG_BYTES and treated as one-time=0 in session_overhead().
HANDSHAKE_BYTES = {
    "websocket": 800,     # HTTP Upgrade request + 101 Switching Protocols
    "sse": 400,           # HTTP GET + 200 response headers (text/event-stream)
    "long_polling": 800,  # full HTTP req+resp (repeats every poll cycle)
    "grpc": 100,          # HTTP/2 connection preface + SETTINGS (binary)
}

# Steady-state delivery latency (ms). Persistent connections push in ~1 RTT;
# long polling pays an extra reconnect gap between each request/response cycle.
LATENCY_MS = {
    "websocket": BASE_RTT_MS,
    "sse": BASE_RTT_MS,
    "grpc": BASE_RTT_MS,
    "long_polling": BASE_RTT_MS + RECONNECT_GAP_MS,   # 100ms
}

# Connection-lifecycle step count (handshake -> data -> teardown).
LIFECYCLE_STEPS = {
    "websocket": 5,   # Upgrade request, 101 response, data frames, ping/pong, close handshake
    "sse": 3,         # GET, 200 stream, auto-reconnect (Last-Event-ID)
    "long_polling": 2,   # GET, response (repeats forever)
    "grpc": 4,        # HTTP/2 preface, HEADERS, DATA frames, GOAWAY/trailers
}

# Directionality of each protocol.
DIRECTION = {
    "websocket": "bidirectional (full-duplex)",
    "sse": "server -> client (unidirectional)",
    "long_polling": "client -> server -> client (request/response)",
    "grpc": "bidirectional (full-duplex streams)",
}

# Exponential backoff for reconnection storms (ms). base * 2^attempt, capped.
BACKOFF_BASE_MS = 100
BACKOFF_CAP_MS = 8000
BACKOFF_ATTEMPTS = 8

# Scalability reference points (from the source material).
CONNS_PER_SERVER = 65_000        # default Linux, tunable to ~1,000,000
DISCORD_CONNS = 7_500_000
DISCORD_SERVERS = 160            # ~120-200 gateway servers
SLACK_MSGS_PER_DAY = 1_000_000_000
LONG_POLL_HANDSHAKES_SEC = 100_000   # 100K clients polling once/sec


# ---------------------------------------------------------------------------
# Derived helpers — pure functions; the JS gold-check reimplements these.
# ---------------------------------------------------------------------------

def is_persistent(proto: str) -> bool:
    """True if the protocol keeps one connection open for the whole session
    (WebSocket, SSE, gRPC). False for long polling, which opens a fresh
    HTTP request every cycle."""
    return proto != "long_polling"


def session_overhead(proto: str) -> int:
    """Total framing/handshake overhead (bytes) for one 60s session at the
    model event rate. Long polling has no one-time handshake — its per-
    message cost already includes the repeated HTTP headers."""
    one_time = HANDSHAKE_BYTES[proto] if is_persistent(proto) else 0
    return one_time + EVENTS * PER_MSG_BYTES[proto]


def payload_total() -> int:
    """Useful bytes delivered in one session (events * payload)."""
    return EVENTS * PAYLOAD_BYTES


def overhead_ratio(proto: str) -> float:
    """session_overhead / payload — how much wire overhead per useful byte."""
    return session_overhead(proto) / payload_total()


def burst_latency(proto: str) -> int:
    """Average delivery latency (ms) for a burst of BURST_K events.

    Persistent protocols multiplex all events on one connection, so every
    event arrives within BASE_RTT. Long polling can hold only ONE in-flight
    request per stream, so the K events drain one per reconnect cycle:
    the i-th event waits i reconnect gaps, and the mean adds (K-1)/2 gaps.
    """
    if is_persistent(proto):
        return BASE_RTT_MS
    return BASE_RTT_MS + (BURST_K - 1) * RECONNECT_GAP_MS // 2


def backoff_schedule() -> list[int]:
    """Deterministic exponential backoff: min(base * 2**a, cap) per attempt."""
    out = []
    for a in range(BACKOFF_ATTEMPTS):
        out.append(min(BACKOFF_BASE_MS * (2 ** a), BACKOFF_CAP_MS))
    return out


# ---------------------------------------------------------------------------
# Section 1 — WebSocket (full-duplex, connection lifecycle)
# ---------------------------------------------------------------------------

def section_websocket() -> None:
    print("=" * 72)
    print("=== WebSocket — full-duplex over a single TCP connection")
    print("=" * 72)
    print("  The ONLY browser-native bidirectional option. The client opens")
    print("  a normal HTTP/1.1 GET with an Upgrade: websocket header; the")
    print("  server replies 101 Switching Protocols; from then on the TCP")
    print("  connection carries bidirectional frames (NOT HTTP). A 2-14 byte")
    print("  frame header per message makes it the lowest-overhead browser")
    print("  option once the one-time handshake is paid.")
    print()
    print(f"  one-time handshake = {HANDSHAKE_BYTES['websocket']} bytes")
    print(f"  per-message frame  = {PER_MSG_BYTES['websocket']} bytes "
          "(masked client frame; range 2-14)")
    print(f"  direction          = {DIRECTION['websocket']}")
    print(f"  steady latency     = {LATENCY_MS['websocket']}ms (1 RTT, persistent)")
    print()

    lifecycle = [
        ("client -> server", "GET /ws/chat HTTP/1.1\\nUpgrade: websocket\\n"
                             "Sec-WebSocket-Key: dGhlIHNhbXBsZQ==\\n..."),
        ("server -> client", "HTTP/1.1 101 Switching Protocols\\n"
                             "Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo="),
        ("both",             "data frames (text/binary), 2-14 byte header each"),
        ("both",             "ping/pong heartbeat every 30s (detect dead TCP)"),
        ("either",           "close frame + ack (clean teardown handshake)"),
    ]
    print("  connection lifecycle:")
    for i, (who, desc) in enumerate(lifecycle, 1):
        print(f"    {i}. [{who:<14}] {desc}")
    print()

    print(f"  session (60s @ {EVENT_RATE}/s = {EVENTS} events):")
    print(f"    payload          = {payload_total():,} bytes "
          f"({EVENTS} x {PAYLOAD_BYTES}B)")
    print(f"    framing overhead = {session_overhead('websocket'):,} bytes "
          f"(handshake + {EVENTS} frames)")
    print(f"    overhead ratio   = {overhead_ratio('websocket')*100:.1f}% "
          "of payload")
    print()

    print("  TYPICAL USE: chat, multiplayer games, collaborative editors")
    print("  (Figma/Google Docs cursors), live trading dashboards, WebRTC")
    print("  signaling. Anywhere the CLIENT also sends data continuously.")
    print()

    ok_duplex = DIRECTION["websocket"].startswith("bidirectional")
    browser_msg = [PER_MSG_BYTES[p] for p in ("websocket", "sse", "long_polling")]
    ok_low = PER_MSG_BYTES["websocket"] == min(browser_msg)
    ok_lat = LATENCY_MS["websocket"] == BASE_RTT_MS
    print(f"  WebSocket is bidirectional (full-duplex)? "
          f"[check] {'OK' if ok_duplex else 'FAIL'}")
    print(f"  WebSocket has the lowest browser per-msg overhead? "
          f"[check] {'OK' if ok_low else 'FAIL'}")
    print(f"  WebSocket steady latency = 1 RTT (persistent)? "
          f"[check] {'OK' if ok_lat else 'FAIL'}")
    assert ok_duplex and ok_low and ok_lat
    print()
    print("  [check] OK   (WebSocket: full-duplex, ~6B frames, "
          "1-RTT latency after handshake)")
    print()
    print("  GOTCHA: the client->server frames are MASKED (4-byte key XOR'd")
    print("  into the payload) to defeat proxy-cache poisoning of")
    print("  intermediaries. Server->client frames are unmasked (2B header).")
    print("  GOTCHA: a TCP connection can silently die (NAT timeout after")
    print("  inactivity). Send a WebSocket ping every ~30s and drop the")
    print("  connection if no pong returns within a timeout.")
    print("  GOTCHA: not serverless-friendly. The gateway must be a")
    print("  long-lived process. On serverless, use a managed service")
    print("  (AWS API Gateway WebSocket, Ably, Pusher).")


# ---------------------------------------------------------------------------
# Section 2 — SSE (server-push, unidirectional)
# ---------------------------------------------------------------------------

def section_sse() -> None:
    print()
    print("=" * 72)
    print("=== SSE (Server-Sent Events) — server-push, one-way, HTTP-native")
    print("=" * 72)
    print("  The server opens ONE persistent HTTP response with the MIME")
    print("  type text/event-stream and pushes text frames down it forever.")
    print("  The browser's EventSource API auto-reconnects on disconnect and")
    print("  replays missed events via the Last-Event-ID header. Strictly")
    print("  server -> client: if the client must SEND, it uses a separate")
    print("  POST (an SSE/REST hybrid).")
    print()
    print(f"  one-time handshake = {HANDSHAKE_BYTES['sse']} bytes")
    print(f"  per-event frame    = {PER_MSG_BYTES['sse']} bytes "
          "(id:/event:/data: + blank line)")
    print(f"  direction          = {DIRECTION['sse']}")
    print(f"  steady latency     = {LATENCY_MS['sse']}ms (1 RTT, persistent)")
    print()

    print("  sample event frame (text/event-stream):")
    print("    id: 42")
    print("    event: price-tick")
    print(f"    data: {{\"sym\":\"AAPL\",\"px\":{178.34}}}   "
          "(the payload)")
    print("    <blank line>   <- the event terminator (\\\\n\\\\n)")
    print()

    lifecycle = [
        ("client -> server", "GET /events  Accept: text/event-stream"),
        ("server -> client", "HTTP/1.1 200 OK  Content-Type: text/event-stream"),
        ("server -> client", "event frames streamed until disconnect, then"),
        ("client",           "EventSource auto-reconnects (retries with backoff,"),
        ("client -> server", "resumes via Last-Event-ID: 42 header)"),
    ]
    print("  connection lifecycle:")
    for i, (who, desc) in enumerate(lifecycle, 1):
        print(f"    {i}. [{who:<14}] {desc}")
    print()

    print(f"  session (60s @ {EVENT_RATE}/s = {EVENTS} events):")
    print(f"    payload          = {payload_total():,} bytes")
    print(f"    framing overhead = {session_overhead('sse'):,} bytes")
    print(f"    overhead ratio   = {overhead_ratio('sse')*100:.1f}% "
          "of payload")
    print()

    print("  TYPICAL USE: live news/social feeds, stock tickers, token")
    print("  streaming (ChatGPT-style LLM output), push notifications,")
    print("  dashboards. Anything server-push-only where the client never")
    print("  streams data back.")
    print()

    ok_one_way = DIRECTION["sse"].startswith("server -> client")
    ok_reconnect = LIFECYCLE_STEPS["sse"] == 3
    ok_more = session_overhead("sse") > session_overhead("websocket")
    print(f"  SSE is server -> client only?           "
          f"[check] {'OK' if ok_one_way else 'FAIL'}")
    print(f"  SSE has built-in auto-reconnect (3-step lifecycle)? "
          f"[check] {'OK' if ok_reconnect else 'FAIL'}")
    print(f"  SSE per-msg overhead > WebSocket (text framing)? "
          f"[check] {'OK' if ok_more else 'FAIL'}")
    assert ok_one_way and ok_reconnect and ok_more
    print()
    print("  [check] OK   (SSE: unidirectional push, ~50B frames, "
          "auto-reconnect)")
    print()
    print("  GOTCHA: under HTTP/1.1 browsers cap at 6 persistent connections")
    print("  PER ORIGIN, and each SSE stream eats one slot. HTTP/2 multiplex-")
    print("  ing removes this limit (many SSE streams share one TCP).")
    print("  GOTCHA: SSE is text-only (UTF-8). Binary needs base64 (33% bloat)")
    print("  or a separate channel.")
    print("  GOTCHA: not serverless-friendly (long-lived response). Use a")
    print("  managed SSE/Pub-Sub service (Ably, Pusher) on serverless.")


# ---------------------------------------------------------------------------
# Section 3 — Long polling (request -> hold -> response)
# ---------------------------------------------------------------------------

def section_long_polling() -> None:
    print()
    print("=" * 72)
    print("=== Long Polling — request -> hold -> response (no persistent conn)")
    print("=" * 72)
    print("  The client issues a normal HTTP GET. Instead of answering")
    print("  immediately, the server HOLDS the request open until either")
    print("  (a) data is available, which it returns at once, or (b) a")
    print("  timeout (~30s) elapses, after which it returns an empty 304 and")
    print("  the client immediately re-GETs. Every message costs a FULL HTTP")
    print("  handshake. Stateless, proxy-friendly, works through anything.")
    print()
    print(f"  per-message cost   = {PER_MSG_BYTES['long_polling']} bytes "
          "(full req+resp headers; handshake repeats)")
    print(f"  direction          = {DIRECTION['long_polling']}")
    print(f"  steady latency     = {LATENCY_MS['long_polling']}ms "
          "(RTT + reconnect gap)")
    print(f"  burst latency ({BURST_K} events) = {burst_latency('long_polling')}ms "
          "(events drain one per cycle)")
    print()

    lifecycle = [
        ("client -> server", "GET /poll?since=41  (hold me open)"),
        ("server",           "no data yet -> sleep (do not reply)"),
        ("server -> client", "event arrives -> 200 OK with the payload"),
        ("client",           "immediately re-issue GET /poll?since=42  (repeat)"),
    ]
    print("  connection lifecycle (repeats forever):")
    for i, (who, desc) in enumerate(lifecycle, 1):
        print(f"    {i}. [{who:<14}] {desc}")
    print()

    print(f"  session (60s @ {EVENT_RATE}/s = {EVENTS} events):")
    print(f"    payload          = {payload_total():,} bytes")
    print(f"    framing overhead = {session_overhead('long_polling'):,} bytes")
    print(f"    overhead ratio   = {overhead_ratio('long_polling')*100:.1f}% "
          "of payload  (WORST by far)")
    print()

    print("  SCALE PENALTY: there is no persistent connection, so connection")
    print(f"  churn is proportional to event rate. At {LONG_POLL_HANDSHAKES_SEC:,}")
    print("  clients polling once/sec, the fleet handles ~100,000 HTTP")
    print(f"  handshakes/sec (near an nginx box's limit), vs {CONNS_PER_SERVER:,}")
    print("  idle persistent connections on a WebSocket/SSE/gRPC gateway.")
    print()

    print("  TYPICAL USE: legacy fallback when WebSocket/SSE are blocked by")
    print("  corporate proxies, low-frequency updates (<1/min), or serverless")
    print("  platforms that cannot hold a persistent process.")
    print()

    ok_repeat = not is_persistent("long_polling")
    ok_high = PER_MSG_BYTES["long_polling"] == max(PER_MSG_BYTES.values())
    ok_burst = burst_latency("long_polling") > LATENCY_MS["websocket"]
    print(f"  long polling repeats the handshake every message? "
          f"[check] {'OK' if ok_repeat else 'FAIL'}")
    print(f"  long polling has the highest per-msg overhead? "
          f"[check] {'OK' if ok_high else 'FAIL'}")
    print(f"  long polling burst latency > WebSocket steady latency? "
          f"[check] {'OK' if ok_burst else 'FAIL'}")
    assert ok_repeat and ok_high and ok_burst
    print()
    print("  [check] OK   (long polling: ~800B/msg, reconnect churn, "
          "proxy-friendly fallback)")
    print()
    print("  GOTCHA: the reconnect gap means bursty traffic queues — a burst")
    print(f"  of {BURST_K} events takes {burst_latency('long_polling')}ms avg to")
    print(f"  drain vs {LATENCY_MS['websocket']}ms on a persistent connection.")
    print("  WebSocket/SSE/gRPC multiplex all of them at once.")
    print("  GOTCHA: only 6 concurrent HTTP/1.1 connections per origin, and")
    print("  long polling occupies one continuously. Tab-heavy users stall.")
    print("  GOTCHA: each cycle is a fresh request — no built-in event replay.")
    print("  The client must track a cursor (since=N) and tolerate gaps.")


# ---------------------------------------------------------------------------
# Section 4 — gRPC streaming (bidirectional over HTTP/2)
# ---------------------------------------------------------------------------

def section_grpc() -> None:
    print()
    print("=" * 72)
    print("=== gRPC Streaming — bidirectional over HTTP/2, Protocol Buffers")
    print("=" * 72)
    print("  gRPC runs on a single long-lived HTTP/2 connection and")
    print("  multiplexes many concurrent RPCs over it. Each message is a")
    print("  length-prefixed protobuf: 1 byte compressed-flag + 4 bytes")
    print("  big-endian length + the binary payload. Three streaming modes")
    print("  map to one HTTP/2 stream each: server-streaming, client-")
    print("  streaming, and bidirectional-streaming.")
    print()
    print(f"  one-time handshake = {HANDSHAKE_BYTES['grpc']} bytes "
          "(HTTP/2 preface + SETTINGS)")
    print(f"  per-message frame  = {PER_MSG_BYTES['grpc']} bytes "
          "(1B flag + 4B length prefix)")
    print(f"  direction          = {DIRECTION['grpc']}")
    print(f"  steady latency     = {LATENCY_MS['grpc']}ms (1 RTT, multiplexed)")
    print()

    modes = [
        ("server-streaming",   "one request  -> stream of responses",
         "live price feed, large result set"),
        ("client-streaming",   "stream of requests -> one response",
         "upload, batch ingest, telemetry"),
        ("bidirectional",      "stream <-> stream (both send anytime)",
         "chat, sub-pub, interactive control plane"),
    ]
    print("  streaming modes (each is one RPC method signature):")
    for mode, flow, use in modes:
        print(f"    {mode:<20} {flow:<38} e.g. {use}")
    print()

    lifecycle = [
        ("client -> server", "HTTP/2 connection preface + SETTINGS (one-time)"),
        ("both",             "HEADERS frame: :path + :method + grpc encoding"),
        ("both",             "DATA frames: 5B length-prefix + protobuf payload"),
        ("server -> client", "trailers: grpc-status (0 = OK) / GOAWAY teardown"),
    ]
    print("  connection lifecycle (one HTTP/2 conn serves ALL RPCs):")
    for i, (who, desc) in enumerate(lifecycle, 1):
        print(f"    {i}. [{who:<14}] {desc}")
    print()

    print(f"  session (60s @ {EVENT_RATE}/s = {EVENTS} events):")
    print(f"    payload          = {payload_total():,} bytes")
    print(f"    framing overhead = {session_overhead('grpc'):,} bytes")
    print(f"    overhead ratio   = {overhead_ratio('grpc')*100:.1f}% "
          "of payload  (LOWEST)")
    print()

    print("  TYPICAL USE: microservice-to-microservice streaming (service")
    print("  mesh, control plane, observability pipelines), polyglot backends")
    print("  with a shared .proto contract. The inter-service winner.")
    print()

    ok_lowest = session_overhead("grpc") == min(
        session_overhead(p) for p in PER_MSG_BYTES)
    ok_duplex = DIRECTION["grpc"].startswith("bidirectional")
    ok_proto = PER_MSG_BYTES["grpc"] == 5
    print(f"  gRPC has the lowest session overhead of all four? "
          f"[check] {'OK' if ok_lowest else 'FAIL'}")
    print(f"  gRPC is bidirectional (bidi streaming)? "
          f"[check] {'OK' if ok_duplex else 'FAIL'}")
    print(f"  gRPC message prefix = 5 bytes (1B flag + 4B length)? "
          f"[check] {'OK' if ok_proto else 'FAIL'}")
    assert ok_lowest and ok_duplex and ok_proto
    print()
    print("  [check] OK   (gRPC: ~5B/msg, HTTP/2 multiplexed, "
          "inter-service standard)")
    print()
    print("  GOTCHA: NOT browser-native. Browsers cannot speak HTTP/2 trailers")
    print("  or the gRPC framing; you need grpc-web + an Envoy proxy, or a")
    print("  REST/Connect-JSON gateway. For browser-to-server realtime, use")
    print("  WebSocket or SSE instead.")
    print("  GOTCHA: protobuf is a strict schema. Adding a field is forward/")
    print("  backward-compatible, but changing a field TYPE or number is")
    print("  breaking. Evolve the contract carefully.")
    print("  GOTCHA: HTTP/2 multiplexing means one slow stream can head-of-")
    print("  line-block others on the same TCP connection under packet loss")
    print("  (the problem WebTransport/QUIC was designed to solve).")


# ---------------------------------------------------------------------------
# Section 5 — Comparison (latency, overhead, scalability, use cases)
# ---------------------------------------------------------------------------

def section_comparison() -> None:
    print()
    print("=" * 72)
    print("=== Comparison — latency, overhead, scalability, decision tree")
    print("=" * 72)
    print("  The same 60-second, 10-events/sec session replayed under all")
    print("  four protocols. The differences collapse to four axes: direction,")
    print("  per-message overhead, steady/burst latency, and how the")
    print("  connection is held. The session overhead ratio spans two orders")
    print("  of magnitude between the best (gRPC) and worst (long polling).")
    print()
    print(f"  traffic model: {EVENTS} events, {PAYLOAD_BYTES}B payload each "
          f"= {payload_total():,}B useful")
    print()

    order = ["websocket", "sse", "long_polling", "grpc"]
    labels = {
        "websocket": "WebSocket",
        "sse": "SSE",
        "long_polling": "Long Polling",
        "grpc": "gRPC Stream",
    }

    header = (f"  {'protocol':<14}{'direction':<26}{'handshake':>10}"
              f"{'per/msg':>9}{'session':>11}{'ratio':>8}{'lat':>6}"
              f"{'burst':>7}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    rows = []
    for k in order:
        so = session_overhead(k)
        rows.append((k, labels[k], so))
        print(f"  {labels[k]:<14}{DIRECTION[k]:<26}"
              f"{HANDSHAKE_BYTES[k]:>10}{PER_MSG_BYTES[k]:>9}"
              f"{so:>11,}{overhead_ratio(k)*100:>7.1f}%"
              f"{LATENCY_MS[k]:>5}ms{burst_latency(k):>6}ms")
    print()

    best = min(rows, key=lambda r: r[2])
    worst = max(rows, key=lambda r: r[2])
    ratio = worst[2] / best[2]
    print(f"  LOWEST overhead = {best[1]:<13} {best[2]:,} bytes "
          f"({overhead_ratio(best[0])*100:.1f}% of payload)")
    print(f"  HIGHEST overhead= {worst[1]:<13} {worst[2]:,} bytes "
          f"({overhead_ratio(worst[0])*100:.1f}% of payload)")
    print(f"  ratio           = {ratio:,.0f}x  (highest / lowest session overhead)")
    print()

    # Burst latency comparison.
    print("  BURST LATENCY (10 events in one burst, average delivery):")
    for k in order:
        bl = burst_latency(k)
        tag = "  <- queues one per cycle" if not is_persistent(k) else ""
        print(f"    {labels[k]:<14} {bl:>4}ms{tag}")
    print()

    # Decision tree.
    print("  DECISION TREE (pick the protocol by requirements):")
    print("    browser + client also streams (chat/game/cursors)  -> WEBSOCKET")
    print("    browser + server-push only (feeds/tokens/notifs)   -> SSE")
    print("    browser + restricted proxy / serverless / legacy   -> LONG POLLING")
    print("    microservice <-> microservice (typed, streaming)   -> GRPC")
    print("    need sub-10ms + packet-loss tolerance (2025+)      -> WEBTRANSPORT")
    print()

    # Scalability reference points.
    print("  SCALABILITY (persistent connections per gateway):")
    print(f"    ~{CONNS_PER_SERVER:,} concurrent TCP conns/server (default Linux,")
    print("       tunable to ~1,000,000)")
    print(f"    Discord: ~{DISCORD_CONNS:,} WebSocket conns across")
    print(f"       ~{DISCORD_SERVERS} gateway servers (with Redis/Kafka fan-out)")
    print(f"    Slack: >{SLACK_MSGS_PER_DAY:,} WebSocket messages/day")
    print(f"    long polling: {LONG_POLL_HANDSHAKES_SEC:,} clients x 1 poll/s =")
    print(f"       ~{LONG_POLL_HANDSHAKES_SEC:,} HTTP handshakes/sec (connection churn)")
    print()

    # Reconnection storm + backoff.
    sched = backoff_schedule()
    print("  RECONNECTION STORM (gateway crash -> all clients reconnect):")
    print("    exponential backoff with jitter spreads the thundering herd.")
    print(f"    delay = min(base * 2^attempt + jitter(0..1s), {BACKOFF_CAP_MS}ms)")
    print(f"    base = {BACKOFF_BASE_MS}ms, deterministic backoff schedule:")
    cum = 0
    for a, d in enumerate(sched):
        cum += d
        print(f"      attempt {a}: backoff = {d:>5}ms   cumulative = {cum:>6}ms")
    print("    SSE has BUILT-IN retry (EventSource retry: field + Last-Event-ID);")
    print("    WebSocket/gRPC require client-side backoff implementation.")
    print()

    ok_best = best[0] == "grpc"
    ok_worst = worst[0] == "long_polling"
    ok_ratio = ratio > 100
    ok_backoff = sched[0] == 100 and sched[-1] == BACKOFF_CAP_MS
    print(f"  gRPC has the lowest session overhead?     "
          f"[check] {'OK' if ok_best else 'FAIL'}")
    print(f"  long polling has the highest overhead?    "
          f"[check] {'OK' if ok_worst else 'FAIL'}")
    print(f"  worst/best session-overhead ratio > 100x? "
          f"[check] {'OK' if ok_ratio else 'FAIL'}")
    print(f"  backoff schedule 100ms -> {BACKOFF_CAP_MS}ms cap?  "
          f"[check] {'OK' if ok_backoff else 'FAIL'}")
    assert ok_best and ok_worst and ok_ratio and ok_backoff
    print()
    print("  [check] OK   (overhead spans ~155x across protocols)")
    print()
    print("  THE ONE IDEA: pick the protocol by DIRECTION and FREQUENCY first.")
    print("  Bidirectional and high-frequency -> WebSocket (browser) or gRPC")
    print("  (service). Server-push-only -> SSE. Restricted or serverless ->")
    print("  long polling. Everything else is optimization of overhead that")
    print("  only matters once you have chosen the right directionality.")


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    section_websocket()
    section_sse()
    section_long_polling()
    section_grpc()
    section_comparison()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
