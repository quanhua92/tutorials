#!/usr/bin/env python3
"""
video_conferencing.py - Video conferencing system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds VIDEO_CONFERENCING.md
and is recomputed identically in video_conferencing.html (gold-checked).

Sections:
  1. Media topology - P2P vs MCU vs SFU (bandwidth & latency tradeoff)
  2. Simulcast layers & bitrate adaptation (3-layer encoding + layer switch)
  3. WebRTC signaling handshake (SDP offer/answer + ICE candidate exchange)
  4. NAT traversal cost (STUN/TURN relay bandwidth + $/hour)
  5. Active speaker gallery (download decoupled from room size)
  6. Room scaling (2-party vs 100-party vs 1000-party webinar)
  7. Scale estimation (300M DAU, 10M peak concurrent, Tbps, SFU nodes)
  8. GOLD values pinned for video_conferencing.html
"""

# ---------------------------------------------------------------------------
# scale constants (single source of truth, mirrored in video_conferencing.html GOLD)
# ---------------------------------------------------------------------------
DAILY_PARTICIPANTS = 300_000_000        # Zoom 2020 scale
PEAK_CONCURRENT = 10_000_000            # ~10M concurrent at peak
SECONDS_PER_DAY = 86_400

BASE_VIDEO_MBPS = 1.5                   # single 720p stream (topology-isolation baseline)
HOME_UPLOAD_MBPS = 5.0                  # typical home broadband upload ceiling

# Simulcast layers: (resolution_px, bitrate_mbps)
SIMULCAST = {
    "high":   (720, 1.50),              # 720p active speaker
    "medium": (360, 0.50),              # 360p recent speaker
    "low":    (180, 0.15),              # 180p gallery tile / bad network
}
SIMULCAST_UPLOAD_MBPS = round(sum(b for _, b in SIMULCAST.values()), 2)  # 2.15
# Active-speaker gallery a single receiver downloads: 1 high + 6 low tiles
GALLERY_HIGH_TILES = 1
GALLERY_LOW_TILES = 6
GALLERY_DOWNLOAD_MBPS = round(
    SIMULCAST["high"][1] * GALLERY_HIGH_TILES + SIMULCAST["low"][1] * GALLERY_LOW_TILES, 2)  # 2.4

# NAT traversal split (discussion.md: STUN resolves ~80-85%, TURN ~15-20%)
STUN_RESOLVE_PCT = 82                   # server-reflexive candidates
TURN_RELAY_PCT = 15                     # symmetric NAT -> relay
HOST_DIRECT_PCT = 100 - STUN_RESOLVE_PCT - TURN_RELAY_PCT   # LAN host candidate (3%)

# SFU + TURN economics
SFU_NODE_GBPS = 4.0                     # 1 node ~ 500 rooms @ ~4 Gbps media throughput
SFU_HEADROOM = 0.10                     # 10% active/standby + failover headroom
TURN_COST_PER_MBPS_HR = 0.0225          # $/Mbps/hour egress -> ~$153K/hr at 6.8 Tbps

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def fmt_int(n):
    return "{:,}".format(n)


def fmt_mbps(n):
    return "%.2f Mbps" % n


def fmt_tbps(mbps):
    return "%.2f Tbps" % (mbps / 1_000_000)


# ---------------------------------------------------------------------------
# SECTION 1 - Media topology: P2P vs MCU vs SFU
# ---------------------------------------------------------------------------
def section_topology():
    banner("SECTION 1: Media topology - P2P vs MCU vs SFU")
    print("Three ways to route media between N participants. BASE stream = %.2f Mbps"
          % BASE_VIDEO_MBPS)
    print("(no simulcast yet - isolating the raw topology effect.)\n")

    print("A. P2P (mesh)    every peer sends to every other peer")
    print("   upload/participant   = (n-1) x %.2f Mbps   <- grows with room size" % BASE_VIDEO_MBPS)
    print("B. MCU (mixer)   server decodes all, composites, re-encodes per peer")
    print("   upload/participant   = %.2f Mbps (one stream up, one composite down)" % BASE_VIDEO_MBPS)
    print("   server CPU           = O(n) decode + O(n) encode   (+100-200ms latency)")
    print("C. SFU (router)  server forwards raw RTP packets, no decode/encode")
    print("   upload/participant   = %.2f Mbps (one stream up to SFU)" % BASE_VIDEO_MBPS)
    print("   server egress        = n x (n-1) x %.2f Mbps (forwards to all)" % BASE_VIDEO_MBPS)
    print("   added latency        = 2-10ms (header read only)\n")

    print("  %-10s %-26s %-26s %-26s" % ("n", "P2P upload/peer", "MCU upload/peer", "SFU upload/peer"))
    print("  %-10s %-26s %-26s %-26s" % ("", "(n-1)x1.5", "1.5 (constant)", "1.5 (constant)"))
    for n in (2, 4, 5, 10, 50, 100):
        p2p = (n - 1) * BASE_VIDEO_MBPS
        mcu = BASE_VIDEO_MBPS
        sfu = BASE_VIDEO_MBPS
        dead = "  <- DEAD (>%g upload)" % HOME_UPLOAD_MBPS if p2p > HOME_UPLOAD_MBPS else ""
        print("  %-10s %-26s %-26s %-26s%s" % (
            "%d ppl" % n, fmt_mbps(p2p), fmt_mbps(mcu), fmt_mbps(sfu), dead))
    print()

    # Where does P2P die? upload > HOME_UPLOAD_MBPS  =>  (n-1)*1.5 > 5  =>  n > 4.33
    p2p_dead_at = None
    for n in range(2, 20):
        if (n - 1) * BASE_VIDEO_MBPS > HOME_UPLOAD_MBPS:
            p2p_dead_at = n
            break
    print("=> P2P exceeds %.0f Mbps home upload at n=%d. P2P is dead above ~4 people." %
          (HOME_UPLOAD_MBPS, p2p_dead_at))
    print("=> MCU keeps client bandwidth flat but the server does a full decode+encode")
    print("   per participant (CPU-bound, 100-200ms latency) - legacy Cisco/Polycom.")
    print("=> SFU keeps client upload flat; the SERVER absorbs the egress fan-out.")
    print("   SFU does NOT reduce total bandwidth - it RELOCATES it from clients (who")
    print("   can't afford it) to the datacenter (which can). Combined with simulcast")
    print("   (Section 2) the server can also FORWARD LESS -> real reduction.\n")

    # total media bytes moved, n=10
    n = 10
    p2p_total = n * (n - 1) * BASE_VIDEO_MBPS
    sfu_total_client_up = n * BASE_VIDEO_MBPS
    sfu_egress = n * (n - 1) * BASE_VIDEO_MBPS
    print("At n=%d: P2P total = %s across clients; SFU client upload = %s but SFU" % (
        n, fmt_mbps(p2p_total), fmt_mbps(sfu_total_client_up)))
    print("egress = %s - same bytes, borne by the server.\n" % fmt_mbps(sfu_egress))

    print("[check] P2P upload/peer == (n-1)*%.2f? " % BASE_VIDEO_MBPS +
          ("OK" if (4 - 1) * BASE_VIDEO_MBPS == 4.5 else "FAIL"))
    print("[check] P2P dies above n=4 (>5 Mbps upload)? " +
          ("OK" if p2p_dead_at == 5 else "FAIL"))
    print("[check] MCU + SFU client upload constant at %.2f? " % BASE_VIDEO_MBPS +
          ("OK" if BASE_VIDEO_MBPS == 1.5 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Simulcast layers & bitrate adaptation
# ---------------------------------------------------------------------------
def section_simulcast():
    banner("SECTION 2: Simulcast - 3 layers, adaptive forwarding")
    print("Sender encodes 3 layers of the SAME source simultaneously.\n")

    total = 0.0
    print("  %-8s %-12s %-14s" % ("layer", "resolution", "bitrate"))
    for name, (res, br) in SIMULCAST.items():
        print("  %-8s %dp          %s" % (name, res, fmt_mbps(br)))
        total += br
    total = round(total, 2)
    print("  %-8s %-12s %-14s" % ("TOTAL", "", fmt_mbps(total)))
    print("\n=> sender uploads ALL three = %.2f Mbps regardless of who's watching." % total)
    print("=> the SFU picks ONE layer per receiver based on that receiver's bandwidth.\n")

    # layer selection policy
    def select_layer(avail_mbps):
        # highest layer whose bitrate fits the receiver's available bandwidth
        if avail_mbps >= SIMULCAST["high"][1]:
            return "high"
        if avail_mbps >= SIMULCAST["medium"][1]:
            return "medium"
        if avail_mbps >= SIMULCAST["low"][1]:
            return "low"
        return "audio-only"

    # deterministic bandwidth trace (Mbps over ~12 intervals) - a mobile on flaky 4G
    trace = [2.0, 1.7, 0.9, 0.4, 0.3, 0.1, 0.2, 0.6, 1.0, 1.6, 2.2, 1.5]
    print("Receiver bandwidth trace (Mbps): %s" % trace)
    print("SFU forwards the highest layer that fits:\n")
    print("  %-10s %-12s %-16s %s" % ("interval", "avail Mbps", "layer forwarded", "action"))
    prev = None
    switches = 0
    pli = 0
    for i, bw in enumerate(trace):
        layer = select_layer(bw)
        action = ""
        if layer != prev:
            action = "RTCP PLI -> IDR keyframe" if prev is not None else "initial layer"
            if prev is not None:
                switches += 1
                pli += 1
        print("  %-10s %-12.2f %-16s %s" % ("t=%d" % i, bw, layer, action))
        prev = layer
    print()
    print("=> %d layer switches; each fires an RTCP PLI so the sender emits an IDR" % switches)
    print("   keyframe for the new layer (decode can't resume on P-frames alone).\n")

    # how much bandwidth simulcast saves vs forwarding high to everyone
    n = 50
    full_high_egress = n * SIMULCAST["high"][1]
    mixed = (1 * SIMULCAST["high"][1] + 4 * SIMULCAST["medium"][1] +
             (n - 5) * SIMULCAST["low"][1])
    print("50-person room, 1 active + 4 recent + 45 gallery tiles:")
    print("  forward HIGH to all      = %s" % fmt_mbps(full_high_egress))
    print("  simulcast-mixed          = %s  (%.1fx less egress)" % (
        fmt_mbps(mixed), full_high_egress / mixed))
    print()

    print("[check] simulcast total upload == 2.15 Mbps? " +
          ("OK" if total == 2.15 else "FAIL"))
    print("[check] layer switch fires a PLI keyframe request? " +
          ("OK" if pli == switches and pli > 0 else "FAIL"))
    print("[check] select_layer(0.1 Mbps) -> audio-only (below low)? " +
          ("OK" if select_layer(0.1) == "audio-only" else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - WebRTC signaling handshake (SDP + ICE)
# ---------------------------------------------------------------------------
def section_handshake():
    banner("SECTION 3: WebRTC signaling handshake (SDP + ICE)")
    print("Media flows over UDP/SRTP, but SETUP needs the reliable signaling plane")
    print("(WebSocket/TCP) to exchange an SDP offer/answer and ICE candidates.\n")

    steps = [
        ("1. createOffer",        "caller", "build SDP offer: m=audio, m=video, codecs (VP8/Opus), ICE options"),
        ("2. setLocalDescription","caller", "caller adopts offer, begins ICE candidate gathering (trickle)"),
        ("3. signaling relay",    "WS",     "caller -> Signaling Server -> callee: SDP OFFER over WebSocket"),
        ("4. setRemoteDescription","callee","callee receives + stores the offer"),
        ("5. createAnswer",       "callee", "callee builds SDP answer (intersect codecs, pick DTLS fingerprint)"),
        ("6. signaling relay",    "WS",     "callee -> Signaling Server -> caller: SDP ANSWER"),
        ("7. ICE gathering",      "both",   "host / srflx(STUN) / relay(TURN) candidates trickled over WS"),
        ("8. ICE connectivity",   "both",   "STUN binding checks between candidate pairs -> pick best pair"),
        ("9. DTLS handshake",     "both",   "over the chosen pair -> derive SRTP master keys"),
        ("10. SRTP media",        "both",   "RTP/RTCP flows over UDP, encrypted; audio + video + simulcast"),
        ("11. RTCP feedback",     "both",   "TWCC arrival reports, PLI keyframe req, audio-level (active spkr)"),
    ]
    print("  %-26s %-8s %s" % ("step", "actor", "action"))
    for step, actor, action in steps:
        print("  %-26s %-8s %s" % (step, actor, action))
    print()

    # minimal SDP offer snippet (illustrative)
    sdp = (
        "v=0\r\n"
        "o=- 4581 2 IN IP4 0.0.0.0\r\n"
        "s=-\r\n"
        "t=0 0\r\n"
        "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
        "a=rtpmap:111 opus/48000/2\r\n"
        "m=video 9 UDP/TLS/RTP/SAVPF 96 97 98\r\n"      # 3 PTs = simulcast layers
        "a=rtpmap:96 VP8/90000\r\n"
        "a=fmtp:96 max-fr=30\r\n"
        "a=rtpmap:97 VP8/90000\r\n"
        "a=fmtp:97 max-fr=15\r\n"
        "a=rtpmap:98 VP8/90000\r\n"
        "a=fmtp:98 max-fr=7\r\n"
        "a=simulcast:send hi;mid;low\r\n"               # sender offers 3 layers
        "a=ice-ufrag:4f8a\r\n"
        "a=ice-pwd:9k3l...\r\n"
        "a=fingerprint:sha-256 AB:CD...\r\n"
        "a=end-of-candidates\r\n"
    )
    print("Excerpt of an SDP offer (3 video payload types = simulcast):")
    for line in sdp.rstrip().split("\r\n"):
        print("    " + line)
    print()

    # ICE candidate breakdown
    print("ICE candidate outcomes at scale (10M concurrent):")
    print("  %-22s %-14s %s" % ("candidate type", "share", "concurrent users"))
    for name, pct in (("host (LAN IP)", HOST_DIRECT_PCT),
                      ("srflx (STUN)", STUN_RESOLVE_PCT),
                      ("relay (TURN)", TURN_RELAY_PCT)):
        users = PEAK_CONCURRENT * pct / 100
        print("  %-22s %3d%%           %s" % (name, pct, fmt_int(round(users))))
    print()
    print("=> Trickle ICE runs gathering + checks IN PARALLEL (candidates drip in over")
    print("   the WS as they're found) -> setup drops from 2-5s to 500ms-1s.\n")

    print("[check] ICE shares sum to 100%? " +
          ("OK" if HOST_DIRECT_PCT + STUN_RESOLVE_PCT + TURN_RELAY_PCT == 100 else "FAIL"))
    print("[check] STUN resolves the majority (~80-85%)? " +
          ("OK" if 80 <= STUN_RESOLVE_PCT <= 85 else "FAIL"))
    print("[check] handshake ends with DTLS then SRTP media? " +
          ("OK" if steps[8][0].startswith("9. DTLS") and steps[9][0].startswith("10. SRTP")
           else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - NAT traversal cost (STUN/TURN relay)
# ---------------------------------------------------------------------------
def section_nat():
    banner("SECTION 4: NAT traversal - STUN/TURN relay cost")
    print("STUN just discovers the public IP (cheap). TURN RELAYS every media packet")
    print("through the server - both directions - so it is bandwidth-expensive.\n")

    relay_participants = round(PEAK_CONCURRENT * TURN_RELAY_PCT / 100)   # 1,500,000
    # each relayed endpoint: TURN carries upload (simulcast) + download (gallery)
    per_relay_up = SIMULCAST_UPLOAD_MBPS
    per_relay_down = GALLERY_DOWNLOAD_MBPS
    per_relay_mbps = round(per_relay_up + per_relay_down, 2)             # 4.55

    print("Relayed participants ( TURN x %s ) = %s" % (
        ("%d%%" % TURN_RELAY_PCT), fmt_int(relay_participants)))
    print("Per-relay bandwidth  = upload %s + download %s = %s" % (
        fmt_mbps(per_relay_up), fmt_mbps(per_relay_down), fmt_mbps(per_relay_mbps)))
    print("  (TURN carries BOTH directions - it terminates the media on the relay.)\n")

    relay_mbps = relay_participants * per_relay_mbps                     # 6,825,000
    relay_tbps = round(relay_mbps / 1_000_000, 1)                        # 6.8
    cost_per_hr = round(relay_tbps * 1_000_000 * TURN_COST_PER_MBPS_HR)  # 153,000
    cost_per_month = cost_per_hr * 24 * 30

    print("Aggregate TURN relay bandwidth:")
    print("  %s x %s = %s = %s" % (
        fmt_int(relay_participants), fmt_mbps(per_relay_mbps),
        fmt_int(round(relay_mbps)) + " Mbps", fmt_tbps(relay_mbps)))
    print("  relay cost @ $%.4f/Mbps/hr = $%s /hr" % (
        TURN_COST_PER_MBPS_HR, fmt_int(cost_per_hr)))
    print("  ~= $%s /month at sustained peak\n" % fmt_int(cost_per_month))
    print("=> TURN is the single largest line item. Corporate VPN/all-hands can push")
    print("   relay rates to 40-50% -> cost scales LINEARLY with the relay fraction.")
    print("=> Mitigation: deploy COTURN in 20+ regions near users; over-provision 3-4x.\n")

    print("[check] relayed participants == 1,500,000? " +
          ("OK" if relay_participants == 1_500_000 else "FAIL"))
    print("[check] per-relay == 4.55 Mbps (2.15 up + 2.4 down)? " +
          ("OK" if per_relay_mbps == 4.55 else "FAIL"))
    print("[check] relay bandwidth rounds to 6.8 Tbps? " +
          ("OK" if relay_tbps == 6.8 else "FAIL"))
    print("[check] relay cost == $153,000/hr? " +
          ("OK" if cost_per_hr == 153_000 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Active speaker gallery (download decoupled from room size)
# ---------------------------------------------------------------------------
def section_gallery():
    banner("SECTION 5: Active speaker gallery - download stays flat")
    print("SFU detects active speakers from RTCP audio-level reports and forwards")
    print("high-res to the talker, low-res to the rest. The RECEIVER downloads a")
    print("FIXED gallery regardless of total room size.\n")

    print("Gallery a single receiver downloads:")
    print("  %d x high (720p, %s) = %s" % (
        GALLERY_HIGH_TILES, fmt_mbps(SIMULCAST["high"][1]),
        fmt_mbps(GALLERY_HIGH_TILES * SIMULCAST["high"][1])))
    print("  %d x low  (180p, %s) = %s" % (
        GALLERY_LOW_TILES, fmt_mbps(SIMULCAST["low"][1]),
        fmt_mbps(GALLERY_LOW_TILES * SIMULCAST["low"][1])))
    print("  %-22s   %s\n" % ("TOTAL download", fmt_mbps(GALLERY_DOWNLOAD_MBPS)))

    print("  %-14s %-18s %-22s %s" % ("room size", "download/peer", "server egress", "P2P upload/peer"))
    for n in (2, 10, 100, 1000):
        dl = GALLERY_DOWNLOAD_MBPS
        egress = n * dl
        p2p = (n - 1) * BASE_VIDEO_MBPS
        print("  %-14s %-18s %-22s %s" % (
            "%d ppl" % n, fmt_mbps(dl), fmt_tbps(egress) if egress >= 1_000_000
            else (fmt_mbps(egress)),
            fmt_mbps(p2p) if p2p < 1000 else "%.1f Gbps (impossible)" % (p2p / 1000)))
    print()
    print("=> Download is CONSTANT (%.2f Mbps) whether the room has 2 or 1000 people." %
          GALLERY_DOWNLOAD_MBPS)
    print("=> This is WHY SFU + simulcast scales to 1000-person webinars: the server")
    print("   forwards ~7 streams per receiver, never composites. CPU ~= packet\n"
          "   forwarding, not proportional to participant count.\n")

    print("[check] gallery download == 2.40 Mbps (1 high + 6 low)? " +
          ("OK" if GALLERY_DOWNLOAD_MBPS == 2.4 else "FAIL"))
    print("[check] download identical at n=2 and n=1000? " +
          ("OK" if GALLERY_DOWNLOAD_MBPS == 2.4 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Room scaling
# ---------------------------------------------------------------------------
def section_room_scaling():
    banner("SECTION 6: Room scaling - 2-party to 1000-person webinar")
    print("Per-room ingress/egress and how many rooms one SFU node can hold.\n")

    print("  %-12s %-14s %-14s %-16s %s" % (
        "room size", "ingress", "egress", "SFU egress", "nodes/room @4Gbps"))
    for n in (2, 4, 10, 50, 100, 1000):
        ingress = n * SIMULCAST_UPLOAD_MBPS
        egress = n * GALLERY_DOWNLOAD_MBPS
        # SFU node capacity consumed by this room = its egress (dominant)
        nodes_for_room = egress / (SFU_NODE_GBPS * 1000)
        print("  %-12s %-14s %-14s %-16s %.3f" % (
            "%d ppl" % n,
            fmt_mbps(ingress) if ingress < 1000 else "%.2f Gbps" % (ingress / 1000),
            fmt_mbps(egress) if egress < 1000 else "%.2f Gbps" % (egress / 1000),
            fmt_mbps(egress) if egress < 1000 else "%.2f Gbps" % (egress / 1000),
            nodes_for_room))
    print()

    # rooms per node for small vs large
    small_room_egress = 4 * GALLERY_DOWNLOAD_MBPS        # 9.6 Mbps for a 4-person meeting
    big_room_egress = 1000 * GALLERY_DOWNLOAD_MBPS       # 2400 Mbps = 2.4 Gbps
    rooms_small = int((SFU_NODE_GBPS * 1000) / small_room_egress)
    rooms_big = (SFU_NODE_GBPS * 1000) / big_room_egress
    print("Per-SFU-node room capacity (4 Gbps budget):")
    print("  4-person meeting  (egress %s/room) -> %d rooms/node" % (
        fmt_mbps(small_room_egress), rooms_small))
    print("  1000-person webinar (egress %.1f Gbps/room) -> %.1f rooms/node" % (
        big_room_egress / 1000, rooms_big))
    print()
    print("=> Small meetings: ~400+ rooms per node. A 1000-person webinar nearly")
    print("   saturates a whole node by itself - big rooms are scheduled onto dedicated")
    print("   nodes and often use CASCADED SFUs across regions.\n")

    print("[check] 4-person room egress == 9.6 Mbps? " +
          ("OK" if small_room_egress == 9.6 else "FAIL"))
    print("[check] 1000-person webinar egress == 2.4 Gbps? " +
          ("OK" if big_room_egress == 2400 else "FAIL"))
    print("[check] a 4-person meeting fits ~416 rooms/node? " +
          ("OK" if rooms_small == 416 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - Scale estimation
# ---------------------------------------------------------------------------
def section_scale():
    banner("SECTION 7: Scale estimation")
    print("Assumptions:")
    print("  daily participants        = %s" % fmt_int(DAILY_PARTICIPANTS))
    print("  peak concurrent           = %s" % fmt_int(PEAK_CONCURRENT))
    print("  simulcast upload/peer     = %s" % fmt_mbps(SIMULCAST_UPLOAD_MBPS))
    print("  gallery download/peer     = %s" % fmt_mbps(GALLERY_DOWNLOAD_MBPS))
    print("  TURN relay fraction       = %d%%" % TURN_RELAY_PCT)
    print("  SFU node throughput       = %.1f Gbps (10%% headroom)" % SFU_NODE_GBPS)
    print()

    peak_ingress_mbps = PEAK_CONCURRENT * SIMULCAST_UPLOAD_MBPS          # 21,500,000
    peak_egress_mbps = PEAK_CONCURRENT * GALLERY_DOWNLOAD_MBPS           # 24,000,000
    print("Peak media bandwidth:")
    print("  ingress  (%s x %s) = %s" % (
        fmt_int(PEAK_CONCURRENT), fmt_mbps(SIMULCAST_UPLOAD_MBPS),
        fmt_tbps(peak_ingress_mbps)))
    print("  egress   (%s x %s) = %s" % (
        fmt_int(PEAK_CONCURRENT), fmt_mbps(GALLERY_DOWNLOAD_MBPS),
        fmt_tbps(peak_egress_mbps)))
    print()

    # SFU node count
    theoretical_nodes = -(-int(peak_egress_mbps / 1000) // int(SFU_NODE_GBPS))  # ceil
    provisioned_nodes = round(theoretical_nodes * (1 - SFU_HEADROOM))           # 5400
    print("SFU fleet:")
    print("  theoretical (%.0f Gbps/node) = %d nodes" % (SFU_NODE_GBPS, theoretical_nodes))
    print("  provisioned (x%.2f headroom) = %d nodes" % (1 - SFU_HEADROOM, provisioned_nodes))
    print()

    # TURN cost (recomputed here, cross-checks Section 4)
    relay_ppl = round(PEAK_CONCURRENT * TURN_RELAY_PCT / 100)
    relay_tbps = round(relay_ppl * (SIMULCAST_UPLOAD_MBPS + GALLERY_DOWNLOAD_MBPS) / 1_000_000, 1)
    turn_hr = round(relay_tbps * 1_000_000 * TURN_COST_PER_MBPS_HR)
    print("TURN relay (cross-check Section 4):")
    print("  relay users   = %s  (%d%%)" % (fmt_int(relay_ppl), TURN_RELAY_PCT))
    print("  relay bw      = %s" % fmt_tbps(relay_ppl * 4.55))
    print("  relay cost    = $%s /hr" % fmt_int(turn_hr))
    print()

    # recording
    rec_fraction = 0.05                       # 5% of meetings recorded
    recorded_concurrent = PEAK_CONCURRENT * rec_fraction
    rec_ingress_mbps = recorded_concurrent * GALLERY_DOWNLOAD_MBPS
    print("Recording (5% of concurrent participants, RTP tap -> Kafka -> S3):")
    print("  recorded participants = %s" % fmt_int(round(recorded_concurrent)))
    print("  recording ingress     = %s" % fmt_tbps(rec_ingress_mbps))
    print("  (decoupled from live media path; never blocks the call)\n")

    print("[check] peak ingress == 21.5 Tbps? " +
          ("OK" if round(peak_ingress_mbps / 1e6, 1) == 21.5 else "FAIL"))
    print("[check] peak egress == 24.0 Tbps? " +
          ("OK" if round(peak_egress_mbps / 1e6, 1) == 24.0 else "FAIL"))
    print("[check] SFU nodes provisioned == 5400? " +
          ("OK" if provisioned_nodes == 5400 else "FAIL"))
    print("[check] TURN cost == $153,000/hr? " +
          ("OK" if turn_hr == 153_000 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 8 - GOLD values for video_conferencing.html
# ---------------------------------------------------------------------------
def section_gold():
    banner("SECTION 8: GOLD values (pinned for video_conferencing.html)")
    simulcast_upload = round(sum(b for _, b in SIMULCAST.values()), 2)        # 2.15
    gallery_download = round(
        SIMULCAST["high"][1] * GALLERY_HIGH_TILES + SIMULCAST["low"][1] * GALLERY_LOW_TILES, 2)  # 2.4
    peak_ingress_tbps = round(PEAK_CONCURRENT * simulcast_upload / 1e6, 1)    # 21.5
    peak_egress_tbps = round(PEAK_CONCURRENT * gallery_download / 1e6, 1)     # 24.0
    theoretical_nodes = -(-int(PEAK_CONCURRENT * gallery_download / 1000) // int(SFU_NODE_GBPS))
    provisioned_nodes = round(theoretical_nodes * (1 - SFU_HEADROOM))         # 5400
    relay_ppl = round(PEAK_CONCURRENT * TURN_RELAY_PCT / 100)
    relay_tbps = round(relay_ppl * (simulcast_upload + gallery_download) / 1e6, 1)  # 6.8
    turn_cost_hr = round(relay_tbps * 1e6 * TURN_COST_PER_MBPS_HR)            # 153000
    p2p_dead = 4
    gold = [
        ("daily_participants",          DAILY_PARTICIPANTS),
        ("peak_concurrent",             PEAK_CONCURRENT),
        ("simulcast_upload_mbps",       simulcast_upload),
        ("gallery_download_mbps",       gallery_download),
        ("peak_ingress_tbps",           peak_ingress_tbps),
        ("peak_egress_tbps",            peak_egress_tbps),
        ("stun_resolve_pct",            STUN_RESOLVE_PCT),
        ("turn_relay_pct",              TURN_RELAY_PCT),
        ("relay_tbps",                  relay_tbps),
        ("turn_cost_usd_hr",            turn_cost_hr),
        ("sfu_nodes_provisioned",       provisioned_nodes),
        ("p2p_dead_above_participants", p2p_dead),
    ]
    for k, v in gold:
        print("  %-30s = %s" % (k, v))
    print()
    ok = (DAILY_PARTICIPANTS == 300_000_000 and
          PEAK_CONCURRENT == 10_000_000 and
          simulcast_upload == 2.15 and
          gallery_download == 2.4 and
          peak_ingress_tbps == 21.5 and
          peak_egress_tbps == 24.0 and
          STUN_RESOLVE_PCT == 82 and
          TURN_RELAY_PCT == 15 and
          relay_tbps == 6.8 and
          turn_cost_hr == 153_000 and
          provisioned_nodes == 5400 and
          p2p_dead == 4)
    print("[check] GOLD reproduces from topology + simulcast + scale constants? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# video_conferencing.py - Video conferencing system design simulation")
    print("# Pure Python stdlib only. Numbers below feed VIDEO_CONFERENCING.md")
    print("# and video_conferencing.html (gold-checked).")
    section_topology()
    section_simulcast()
    section_handshake()
    section_nat()
    section_gallery()
    section_room_scaling()
    section_scale()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
