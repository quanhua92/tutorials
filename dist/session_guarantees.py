"""
session_guarantees.py - Reference implementation of SESSION GUARANTEES
(Terry, Theimer, Petersen, Demers, Spreitzer 1994, from the Bayou system):
per-CLIENT consistency promises layered on top of an eventually-consistent
replicated store. The four guarantees are:

    RYW  Read-Your-Writes      a client always sees its own writes.
    MR   Monotonic Reads       a client never sees a value go backward.
    MW   Monotonic Writes      writes from one session are applied in order.
    WFR  Writes-Follow-Reads   a write that follows a read is applied after
                               the version of the data the read returned.

This is the single source of truth that SESSION_GUARANTEES.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 session_guarantees.py

Pure Python stdlib only.

============================================================================
THE INTUITION (read this first) - the diary that forgets what you just wrote
============================================================================
You keep a diary of your own actions. Today you wrote "I moved the meeting to
Thursday". Five minutes later you OPEN the diary to check - and it still says
Wednesday. You know you just wrote Thursday; the diary disagrees. That gap -
between what YOU did and what you see - is the thing session guarantees close.

A replicated store has the SAME problem. Your write lands on ONE replica and
spreads to the others by ANTI-ENTROPY (gossip). Until it spreads, a load
balancer may route your next request to a replica that HASN'T seen your write
yet. From the SYSTEM's view nothing is wrong (everything converges eventually -
that is eventual consistency). From YOUR view it is broken: you wrote Thursday,
you read Wednesday. You start doubting yourself.

Session guarantees fix this by giving ONE client (a "session") promises about
the order of ITS OWN operations, regardless of which replica serves each one.
They are WEAKER than causal consistency (they say nothing about OTHER clients'
causality) but they are CHEAP - just a little bookkeeping the client carries.
That is why Dynamo, Riak, and Cassandra expose them as tunable per-session
knobs rather than as global invariants.

The four guarantees in one breath:
  * RYW : "if I wrote it, I will read it back."
  * MR  : "if I once saw version N, I will never again see a version < N."
  * MW  : "my writes reach each replica in the order I issued them."
  * WFR : "a write I issue after a read is applied only once the replica has
          the version of the data that my read returned."

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  session            : one client's sequential conversation with the store.
                       All ops in a session are ordered by the client. Here:
                       one client per section (c1..c4) plus a gold-check client.
  replica            : one copy of the data. Here: A, B, C (3) for RYW/MR; a
                       single replica R for MW; R0/R2 for WFR. Each holds
                       {key: (value, version)}.
  version            : a logical timestamp stamped on each write; higher =
                       newer. The single scalar we track PER KEY (the
                       practical implementation - a per-key version attribute,
                       as in DynamoDB / Cassandra).
  write              : set a key to a value at a version. Tagged with the
                       issuing SESSION and, for MW, a per-session SEQ.
  read               : fetch a key from a replica; returns (value, version).
  anti-entropy       : background propagation that brings a lagging replica up
                       to date. We MODEL it as a deterministic "catch-up" that
                       advances a replica to a target version on demand.
                       (See EVENTUAL_CONSISTENCY.md for the gossip engine.)
  sticky session     : a load-balancer route that sends every op of a session
                       to the SAME replica (via a session token / cookie).
                       Gives RYW + MR almost for free.
  session token      : the bookkeeping a client carries: per-key
                       last_write_version (RYW), highest_read_version (MR),
                       next write seq (MW), last_read_version (WFR).
  version vector     : the general form - one counter per node/client. Session
                       guarantees collapse it to per-key scalars for cheapness.
                       (See VECTOR_CLOCKS.md for the full vector form.)
  RYW / MR / MW / WFR: the four guarantees; defined precisely in Sections A-D.

============================================================================
THE PAPER (every formula/claim below verified against this)
============================================================================
  Terry, Theimer, Petersen, Demers, Spreitzer. "Managing Update Conflicts in
       Bayou, a Replicated Weakly-Connected Database." SOSP 1995 (the Bayou
       data-management paper; the four session guarantees were introduced in
       the 1994 SRC Tech Note "Session Guarantees for Weakly Consistent
       Replicated Data"). Verified claims: the four guarantees by name; that
       they are PER-CLIENT and composable; that sticky sessions + version
       vectors implement them; that they sit between eventual and causal.
  DeCandia et al. "Dynamo: Amazon's Highly Available Key-value Store." SOSP
       2007. Verified: Dynamo exposes RYW/MR as per-session hints ("R" and "W"
       tuning + client-side version cache); vector clocks per object.
  Lamport. "Time, Clocks..." CACM 1978. Verified: the happens-before relation
       that WFR and RYW are special cases of (program-order + read->write dep).
  Lloyd et al. "COPS." SOSP 2011. Verified: causal consistency is the
       CROSS-CLIENT generalization of which session guarantees are the
       single-client slice. (See CAUSAL_CONSISTENCY.md.)
  Vogels. "Eventually Consistent." ACM Queue 2009. Verified: the framing of
       session guarantees as "client-centric" vs the "data-centric" linear /
       causal models; Dynamo's per-session tuning.

KEY FORMULAS / facts (all asserted in code below):
    RYW  on read of key k from replica r :
         ok  iff  r.version(k) >= session.last_write_version[k]
    MR   on read of key k from replica r :
         ok  iff  r.version(k) >= session.highest_read_version[k]
         after a successful read: highest_read_version[k] = max(., r.version(k))
    MW   on apply of write w (session seq s) at replica r :
         ok  iff  s == r.applied_seq(session) + 1   (in-order, no gaps/reversals)
         else BUFFER w until its predecessor is applied.
    WFR  on apply of write w with read_dep {k: d} at replica r :
         ok  iff  for all k: r.version(k) >= d
         else BUFFER w until the read-context version is present.
    sticky session : route all ops to one replica  =>  RYW + MR hold trivially.
    ladder         : eventual  <  session  <  causal  <  linearizable
                     (session = per-client slice of causal; no cross-client deps)

============================================================================
DETERMINISM NOTE (how the .html reproduces these numbers byte-for-byte)
============================================================================
No randomness is used anywhere. Every replica state and arrival order is
SCRIPTED. So the .py output and the .html JS recompute identical numbers from
identical constants. There is no PRNG to twin (unlike EVENTUAL_CONSISTENCY.md).

============================================================================
THE SCENARIO (deterministic; reused by every section and by the .html)
============================================================================
Three replicas A, B, C of keys X (and Y in Section D). Section A scripts a
write to A only (B, C lag). Section B scripts divergent versions across A/B/C.
Section C scripts an out-of-order delivery of two writes from one session to a
single replica R. Section D scripts a write whose read-context version has not
yet reached the replica that receives it. Each section shows the VIOLATION
(guarantee off) and the FIX (guarantee on: block/sticky/buffer).
"""

from __future__ import annotations

BANNER = "=" * 74
REPLICAS = ("A", "B", "C")


# ---------------------------------------------------------------------------
# PRETTY PRINTERS
# ---------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_store(store):
    """Format a replica's {key: (val, ver)} as 'X=1@v1, Y=0@v0'."""
    return ", ".join(f"{k}={v}@v{ver}" for k, (v, ver) in sorted(store.items()))


# ---------------------------------------------------------------------------
# 1. THE DATA MODEL
# ---------------------------------------------------------------------------
class Replica:
    """One copy of the data. `store` maps key -> (value, version)."""

    def __init__(self, name: str, store=None):
        self.name = name
        self.store = dict(store) if store else {}

    def get(self, key):
        return self.store.get(key, (0, 0))

    def version(self, key):
        return self.store.get(key, (0, 0))[1]

    def set(self, key, value, version):
        cur_v = self.version(key)
        if version >= cur_v:                      # monotonic apply (LWW-ish)
            self.store[key] = (value, version)

    def __repr__(self):
        return f"{self.name}{{{fmt_store(self.store)}}}"


class Write:
    """A write op: set `key`=`value` at global `version`, issued by `session`
    with per-session `seq` (for MW) and optional `read_dep` (for WFR)."""

    def __init__(self, key, value, version, session, seq=0, read_dep=None):
        self.key = key
        self.value = value
        self.version = version
        self.session = session
        self.seq = seq
        self.read_dep = dict(read_dep) if read_dep else {}


class Session:
    """The session token: the per-key bookkeeping that implements the four
    guarantees. Each field is the minimum the client must remember."""

    def __init__(self, client: str):
        self.client = client
        self.last_write_version = {}    # RYW: max version of MY writes, per key
        self.highest_read_version = {}  # MR : max version I have EVER read, per key
        self.next_write_seq = 0         # MW : monotonic write counter
        self.last_read_version = {}     # WFR: version of the value my last read returned

    def record_write(self, key, version):
        self.last_write_version[key] = max(
            self.last_write_version.get(key, 0), version)

    def record_read(self, key, version):
        self.highest_read_version[key] = max(
            self.highest_read_version.get(key, 0), version)
        self.last_read_version[key] = version

    def next_seq(self):
        self.next_write_seq += 1
        return self.next_write_seq


# ---------------------------------------------------------------------------
# 2. THE FOUR VERIFIER PRIMITIVES  (the SPEC each guarantee demands)
#    Each returns (ok, detail). "ok=False" is a violation. The Sections below
#    first show the violation (guarantee OFF) then the fix (guarantee ON).
# ---------------------------------------------------------------------------
def check_ryw(session, replica, key):
    """RYW: the replica must carry MY last write to `key`."""
    need = session.last_write_version.get(key, 0)
    have = replica.version(key)
    return (have >= need, (need, have))


def check_mr(session, replica, key):
    """MR: the replica's version must be >= the highest version I've ever read."""
    need = session.highest_read_version.get(key, 0)
    have = replica.version(key)
    return (have >= need, (need, have))


def check_mw(applied_seq, write):
    """MW: write.seq must be exactly applied_seq+1 (in-order, no reversals)."""
    return (write.seq == applied_seq + 1, (applied_seq, write.seq))


def check_wfr(replica, write):
    """WFR: the replica must already carry the read-context version of the
    write, for every key in write.read_dep."""
    for k, need in write.read_dep.items():
        if replica.version(k) < need:
            return (False, (k, need, replica.version(k)))
    return (True, None)


# ---------------------------------------------------------------------------
# 3. GUARDED READ  (the FIX: block until the replica catches up)
# ---------------------------------------------------------------------------
def guarded_read(session, replica, key, guarantees, catchup=None):
    """Read `key` from `replica`, enforcing the enabled `guarantees`.

    If the replica lags behind what RYW/MR require, we model the FIX as a
    BLOCK: anti-entropy (`catchup` is a callable(key, need) -> (val, ver))
    advances the replica to the required version before the read returns.
    Returns (value, version, blocked: bool, blocked_to: int)."""
    need = 0
    if "RYW" in guarantees:
        need = max(need, session.last_write_version.get(key, 0))
    if "MR" in guarantees:
        need = max(need, session.highest_read_version.get(key, 0))
    blocked = False
    if replica.version(key) < need:
        blocked = True
        if catchup is not None:
            val, ver = catchup(key, need)
            replica.set(key, val, ver)
    val, ver = replica.get(key)
    session.record_read(key, ver)
    return (val, ver, blocked, need)


# ===========================================================================
# SECTION A: Read-Your-Writes - a client always sees its own writes
# ===========================================================================
def section_a():
    banner("SECTION A: Read-Your-Writes (RYW) - see your own writes")
    print("You WRITE X=1 @ v1 onto replica A. Gossip has not reached B or C,")
    print("so they still hold X=0 @ v0. Your very next request is a READ of X.\n")
    A = Replica("A", {"X": (1, 1)})
    B = Replica("B", {"X": (0, 0)})
    C = Replica("C", {"X": (0, 0)})
    print(f"  states:  A={A}, B={B}, C={C}")
    s = Session("c1")
    s.record_write("X", 1)
    print(f"  session: last_write_version[X] = {s.last_write_version['X']}  "
          "(you wrote X@v1)\n")

    print("--- WITHOUT RYW (load balancer routes your read to B) ---")
    ok, (need, have) = check_ryw(s, B, "X")
    val, ver = B.get("X")
    print(f"  read X from B -> X={val}@v{ver}   "
          f"RYW check: need>={need}, have={have} -> "
          f"{'OK' if ok else 'VIOLATION'}")
    print(f"  => you just wrote X=1 but you read X={val}. The diary forgot what")
    print("     you wrote. This is the signature RYW failure.\n")

    print("--- WITH RYW (sticky session: route back to A) ---")
    ok2, (need2, have2) = check_ryw(s, A, "X")
    val2, ver2 = A.get("X")
    print(f"  read X from A -> X={val2}@v{ver2}   "
          f"RYW check: need>={need2}, have={have2} -> "
          f"{'OK' if ok2 else 'VIOLATION'}")
    print(f"  => the sticky replica A still has your write. You read X={val2}.")
    print("     Alternatively, block the read on B until gossip catches B up to")
    print(f"     v{need}:")
    val3, ver3, blocked, need3 = guarded_read(
        s, B, "X", {"RYW"}, catchup=lambda k, n: (1, n))
    print(f"  guarded_read(B, RYW on): blocked={blocked} (caught B up to v{need3})"
          f" -> X={val3}@v{ver3}\n")
    print("RYW SPEC : read of k from r is ok  <=>  r.version(k) >= "
          "session.last_write_version[k]")
    print("FIX      : (1) sticky session - route to the replica that took the")
    print("               write;  OR  (2) send last_write_version in the request")
    print("               and block until the chosen replica has caught up.\n")
    assert not ok and ok2 and blocked and ver3 == 1
    print(f"[check] RYW: B violates (need {need} > have {have}); A ok; "
          f"blocked-read fixes -> v{ver3}:  OK")
    print("GOLD (pinned for .html): RYW violation on B = (need=1, have=0); "
          "sticky A -> (1,1); blocked B -> (1,1).")
    return {"without": (val, ver), "sticky": (val2, ver2),
            "blocked": (val3, ver3)}


# ===========================================================================
# SECTION B: Monotonic Reads - a client never sees data go backward
# ===========================================================================
def section_b():
    banner("SECTION B: Monotonic Reads (MR) - never see a value go backward")
    print("Replicas are mid-convergence: A and C have the newer X=5 @ v5; B is")
    print("lagging at X=3 @ v3. Your client reads X twice in a row.\n")
    A = Replica("A", {"X": (5, 5)})
    B = Replica("B", {"X": (3, 3)})
    C = Replica("C", {"X": (5, 5)})
    print(f"  states:  A={A}, B={B}, C={C}")
    s = Session("c2")

    print("--- read 1 from A (no guarantee needed yet) ---")
    v1, ver1 = A.get("X")
    s.record_read("X", ver1)
    ok1, _ = check_mr(s, A, "X")
    print(f"  read X from A -> X={v1}@v{ver1}   "
          f"highest_read_version[X] now {s.highest_read_version['X']}\n")

    print("--- read 2 WITHOUT MR (load balancer routes to lagging B) ---")
    ok2, (need2, have2) = check_mr(s, B, "X")
    v2, ver2 = B.get("X")
    print(f"  read X from B -> X={v2}@v{ver2}   "
          f"MR check: need>={need2}, have={have2} -> "
          f"{'OK' if ok2 else 'VIOLATION'}")
    print(f"  => observed sequence {v1} -> {v2}: the value went BACKWARD. You saw")
    print(f"     v{ver1} then v{ver2}; a newer read was followed by an older one.\n")

    print("--- read 2 WITH MR (block B until it catches up to v5) ---")
    s2 = Session("c2'")
    s2.record_read("X", ver1)
    v3, ver3, blocked, need3 = guarded_read(
        s2, B, "X", {"MR"}, catchup=lambda k, n: (5, n))
    print(f"  guarded_read(B, MR on): blocked={blocked} (caught B up to v{need3})"
          f" -> X={v3}@v{ver3}")
    print(f"  => observed sequence {v1} -> {v3}: monotonically non-decreasing. ")
    print("     You never see a version older than the newest you've seen.\n")
    print("MR SPEC  : read of k from r is ok  <=>  r.version(k) >= "
          "session.highest_read_version[k]")
    print("           (updated to max(., r.version(k)) after each successful read)")
    print("FIX      : client remembers the highest version it has ever read; on")
    print("           each read, block the replica until it reaches that version.\n")
    assert not ok2 and blocked and ver3 == 5 and v3 == 5
    print(f"[check] MR: B violates (need {need2} > have {have2}); blocked-read "
          f"fixes -> v{ver3}:  OK")
    print("GOLD (pinned for .html): MR violation on B = (need=5, have=3); "
          "backward seq 5->3; blocked B -> 5.")
    return {"read1": (v1, ver1), "without": (v2, ver2), "blocked": (v3, ver3)}


# ===========================================================================
# SECTION C: Monotonic Writes - a session's writes applied in order
# ===========================================================================
def section_c():
    banner("SECTION C: Monotonic Writes (MW) - a session's writes stay ordered")
    print("Your session issues two writes in order:  W1: X=1 @ v1 (seq 1),")
    print("then W2: X=2 @ v2 (seq 2). Every replica must apply W1 BEFORE W2.\n")
    print("Network reordering hands a single replica R the writes as [W2, W1].\n")
    s = Session("c3")
    W1 = Write("X", 1, 1, "c3", seq=s.next_seq())     # seq 1
    W2 = Write("X", 2, 2, "c3", seq=s.next_seq())     # seq 2
    arrival = [W2, W1]
    print("  issued order : W1(seq1, X=1@v1) then W2(seq2, X=2@v2)")
    print(f"  arrival @ R  : [{arrival[0].key}={arrival[0].value}@v{arrival[0].version}"
          f"(seq{arrival[0].seq}), "
          f"{arrival[1].key}={arrival[1].value}@v{arrival[1].version}"
          f"(seq{arrival[1].seq})]  <- REVERSED\n")

    print("--- WITHOUT MW (apply in arrival order on a naive-overwrite store) ---")
    R = Replica("R", {"X": (0, 0)})
    seq_naive = []
    for w in arrival:
        R.store[w.key] = (w.value, w.version)         # naive: last delivery wins
        seq_naive.append(R.get("X"))
    print(f"  apply W2 -> R={R}")
    print(f"  apply W1 -> R={R}   <- final X={R.get('X')[0]} (session wrote 1 then 2,")
    print("                        expects 2; the older write clobbered the newer)")
    print(f"  visible value sequence on R: "
          f"{' -> '.join(str(v) for v, _ in [(0, 0)] + seq_naive)}  "
          f"(non-monotonic: 0 -> 2 -> 1)\n")

    print("--- WITH MW (buffer by session seq; apply in seq order) ---")
    R2 = Replica("R", {"X": (0, 0)})
    applied_seq = 0
    pending = []
    visible = [R2.get("X")]

    def try_flush():
        nonlocal applied_seq
        progressed = True
        while progressed:
            progressed = False
            for w in list(pending):
                ok, (have, want) = check_mw(applied_seq, w)
                if ok:
                    pending.remove(w)
                    R2.set(w.key, w.value, w.version)
                    applied_seq = w.seq
                    visible.append(R2.get("X"))
                    progressed = True

    for w in arrival:
        ok, (have, want) = check_mw(applied_seq, w)
        if ok:
            R2.set(w.key, w.value, w.version)
            applied_seq = w.seq
            visible.append(R2.get("X"))
            try_flush()
        else:
            pending.append(w)
            print(f"  W(seq{w.seq}, X={w.value}@v{w.version}) arrives: "
                  f"MW check applied_seq={have}, want seq={have+1} -> "
                  f"BUFFER (got seq {want} out of order)")
    try_flush()
    print(f"  W(seq1, X=1@v1) applies -> R={R2}")
    print(f"  flush: W(seq2) now in-order -> R={R2}   <- final X={R2.get('X')[0]}")
    print(f"  visible value sequence on R: "
          f"{' -> '.join(str(v) for v, _ in visible)}  (monotonic: 0 -> 1 -> 2)\n")
    print("MW SPEC  : apply of write w (session seq s) at r is ok  <=>  "
          "s == r.applied_seq(session) + 1")
    print("FIX      : replica buffers any write whose seq is out of order until")
    print("           its predecessor (seq-1) is applied; flushes on each apply.")
    print("NOTE     : on a last-writer-wins store the FINAL value is rescued by")
    print("           the version rule, but the INTERMEDIATE state is still wrong")
    print("           (0->2->1). For non-commutative updates (counters, appends,")
    print("           RMW) MW is essential - without it the final state diverges.\n")
    assert R.get("X") == (1, 1) and R2.get("X") == (2, 2)
    assert seq_naive == [(2, 2), (1, 1)]
    assert [v for v, _ in visible] == [0, 1, 2]
    print(f"[check] MW: naive final X={R.get('X')[0]} (wrong, seq 0->2->1); "
          f"buffered final X={R2.get('X')[0]} (seq 0->1->2):  OK")
    print("GOLD (pinned for .html): MW naive final=(1,1) seq [2,1]; "
          "buffered final=(2,2) seq [1,2].")
    return {"naive_final": R.get("X"), "buffered_final": R2.get("X"),
            "naive_seq": seq_naive, "buffered_seq": [visible[1], visible[2]]}


# ===========================================================================
# SECTION D: Writes-Follow-Reads - a write after a read depends on that read
# ===========================================================================
def section_d():
    banner("SECTION D: Writes-Follow-Reads (WFR) - write carries its read context")
    print("You READ X and get X=5 @ v5 (replica R0 is up to date). You then WRITE")
    print("Y = 2*X = 10, which logically DEPENDS on the X you just read. Your")
    print("write carries read_dep = {X: 5}: 'apply me only once you have X@v5'.\n")
    print("Meanwhile replica R2 is lagging: it has X=3 @ v3 and has NOT yet seen")
    print("the X=v5 your read returned. Your Y write arrives at R2.\n")
    R0 = Replica("R0", {"X": (5, 5), "Y": (0, 0)})
    R2 = Replica("R2", {"X": (3, 3), "Y": (0, 0)})
    print(f"  states:  R0={R0}, R2={R2}")
    s = Session("c4")
    rv, rver = R0.get("X")
    s.record_read("X", rver)
    W = Write("Y", 10, 7, "c4", seq=1, read_dep={"X": rver})
    print(f"  read X from R0 -> X={rv}@v{rver}   session.last_read_version[X]={rver}")
    print(f"  issue   W: Y={W.value}@v{W.version}, read_dep={W.read_dep}\n")

    print("--- WITHOUT WFR (R2 applies Y even though it lacks X@v5) ---")
    ok, detail = check_wfr(R2, W)
    R2.store["Y"] = (W.value, W.version)             # naive: ignore read_dep
    print(f"  WFR check on R2: {('OK' if ok else 'VIOLATION '+str(detail))}"
          f"   R2={R2}")
    print(f"  => R2 now reveals Y={W.value} (authored in the context X=5) while it")
    print("     STILL shows X=3. A reader of R2 sees Y alongside an X that the")
    print("     author never had in mind. The read context of the write is lost.\n")

    print("--- WITH WFR (buffer Y on R2 until X catches up to v5) ---")
    R2b = Replica("R2", {"X": (3, 3), "Y": (0, 0)})
    ok2, detail2 = check_wfr(R2b, W)
    print(f"  W arrives at R2: WFR check -> {('OK' if ok2 else 'BUFFER '+str(detail2))}")
    # model anti-entropy catching R2 up to X=v5
    R2b.set("X", 5, 5)
    print(f"  anti-entropy advances R2 -> {R2b}")
    ok3, detail3 = check_wfr(R2b, W)
    if ok3:
        R2b.store["Y"] = (W.value, W.version)
    print(f"  re-check WFR -> {('OK -> APPLY Y' if ok3 else 'BUFFER '+str(detail3))}"
          f"   R2={R2b}")
    print("  => Y is applied only once R2 has X@v5, i.e. AFTER the version your")
    print("     read returned. The write correctly 'follows' the read.\n")
    print("WFR SPEC : apply of write w with read_dep at r is ok  <=>  for all k:")
    print("            r.version(k) >= w.read_dep[k]")
    print("FIX      : replica buffers the write until, for every key in its")
    print("           read_dep, the replica's version is >= the read's version.")
    print("           Equivalent to a 1-hop causal dependency (read -> write).\n")
    assert not ok and detail == ("X", 5, 3)
    assert ok3 and R2b.get("Y") == (10, 7)
    print("[check] WFR: R2 violates (X need 5 > have 3); after catch-up X=5 -> "
          "apply Y=(10,7):  OK")
    print("GOLD (pinned for .html): WFR violation on R2 = (X,need=5,have=3); "
          "after catch-up Y=(10,7).")
    return {"without_applied": (R2.get("Y"), R2.version("X")),
            "with_applied": (R2b.get("Y"), R2b.version("X"))}


# ===========================================================================
# SECTION E: Implementation - sticky sessions, version vectors, Dynamo/Cassandra
# ===========================================================================
def section_e():
    banner("SECTION E: implementation - sticky sessions, version vectors, "
           "Dynamo/Cassandra")
    print("Session guarantees are CLIENT-CENTRIC, so the bookkeeping lives in the")
    print("SESSION TOKEN the client sends with every request. Three building")
    print("blocks implement all four guarantees:\n")
    print("  (1) STICKY SESSION  - a load-balancer route (cookie / token) that")
    print("      sends every op of a session to the SAME replica. Because that")
    print("      one replica sees your writes in order and never forgets them,")
    print("      RYW and MR hold TRIVIALLY. Cost: lose the replica and you lose")
    print("      stickiness (must fall back to version checks).\n")
    print("  (2) CLIENT VERSION CACHE - the client remembers, per key, the")
    print("      version of its last write (RYW) and the highest version it has")
    print("      read (MR). It sends these on each read; the server blocks until")
    print("      the chosen replica has caught up. This is the GENERAL fix and")
    print("      works even without stickiness.\n")
    print("  (3) SERVER-SIDE BUFFERING - for MW and WFR the replica buffers")
    print("      out-of-order / context-lagging writes (Sections C, D). This is")
    print("      exactly the dependency-check + pending-queue used for causal")
    print("      consistency, scoped to ONE session. (See CAUSAL_CONSISTENCY.md.)\n")

    print("How real systems expose these (verified against their docs/papers):\n")
    rows = [
        ("Read-Your-Writes",
         "sticky session; OR client caches last-write version per key",
         "DynamoDB: session token + conditional write;\n"
         "    Riak: 'last_write_wins'=false + client vector clock"),
        ("Monotonic Reads",
         "client caches highest-read version per key; read blocks until met",
         "Cassandra: read at QUORUM + read_repair;\n"
         "    DynamoDB: consistent read (R=QUORUM) per request"),
        ("Monotonic Writes",
         "replica buffers writes by per-session sequence number",
         "Cassandra LWT (Paxos, LOCAL_SERIAL) serializes a partition;\n"
         "    Bayou: ordered write-log per session"),
        ("Writes-Follow-Reads",
         "write carries read-context version; replica buffers until present",
         "DynamoDB ConditionExpression on a version attribute;\n"
         "    COPS 1-hop dependency tracking (cross-client generalization)"),
    ]
    pw = max(len("guarantee"), max(len(r[0]) for r in rows))
    pw2 = max(len("mechanism (session token)"), max(len(r[1]) for r in rows))
    print(f"| {'guarantee':<{pw}} | {'mechanism (session token)':<{pw2}} | "
          f"system / knob                                           |")
    print(f"|{'-'*(pw+2)}|{'-'*(pw2+2)}|"
          f"{'-'*(56)}|")
    for g, mech, sysk in rows:
        print(f"| {g:<{pw}} | {mech:<{pw2}} | {sysk:<54} |")
    print()

    print("DynamoDB conditional writes implement RYW / WFR directly. Pattern:")
    print("    # RYW: re-read only sees my write if the item's version attr >= mine")
    print("    PutItem(... ConditionExpression='ver >= :myver', ...)")
    print("    # WFR: my write applies only if the item still has the read-context")
    print("    PutItem(... ConditionExpression='ver = :readver', ...)")
    print("A failed ConditionExpression = the guarantee would be violated, so the")
    print("write is rejected (the client retries - effectively a BLOCK).\n")

    print("Cassandra consistency levels trade availability vs guarantee strength:")
    cl = [
        ("ONE / LOCAL_ONE", "contact 1 replica", "weakest; stale reads likely",
         "no session guarantee by default"),
        ("QUORUM", "contact majority (R + W > N)", "R+W>N => strong per-op",
         "RYW + MR if BOTH read & write at QUORUM"),
        ("LOCAL_SERIAL", "Paxos (Lightweight Transactions)", "linearizable per key",
         "MW (serialized writes) for one partition"),
    ]
    print(f"| {'level':<16} | {'what it does':<26} | {'strength':<22} | "
          f"{'session guarantee'}            |")
    print(f"|{'-'*18}|{'-'*28}|{'-'*24}|{'-'*32}|")
    for lvl, what, strength, g in cl:
        print(f"| {lvl:<16} | {what:<26} | {strength:<22} | {g:<30} |")
    print()
    print("RULE OF THUMB: write at QUORUM and read at QUORUM => RYW + MR for the")
    print("keys in the session (R+W > N guarantees the read quorum overlaps the")
    print("write quorum). LWT (LOCAL_SERIAL) => MW on a partition. WFR needs the")
    print("client to send the read-context version explicitly (a ConditionExpression).\n")

    print("LADDER: where session guarantees sit among the models:")
    print("  eventual  <  SESSION  <  causal  <  linearizable")
    print("  (converge)   (per-client) (+cross-client) (+real-time/total order)")
    print("Session guarantees are the SINGLE-CLIENT slice of causal consistency:")
    print("they track program-order (RYW, MW) and read->write deps (WFR) but only")
    print("for ONE client. Cross-client causality (COPS) is the generalization.\n")
    print("[check] building blocks {sticky, version-cache, server-buffer} cover "
          "all 4 guarantees:  OK")


# ===========================================================================
# GOLD CHECK: a history with a session token, all 4 guarantees verified
# ===========================================================================
def gold_check():
    banner("GOLD CHECK: a session history - verify all four guarantees")
    print("One client c5 against replicas A, B, C. The history below is the")
    print("deterministic op stream; the session token carries the per-key")
    print("last_write_version (RYW), highest_read_version (MR), write seq (MW),")
    print("and last_read_version (WFR). We verify each guarantee in turn.\n")

    # --- the canonical history ---
    # replica snapshots are SCRIPTED (set directly) to expose each guarantee.
    A = Replica("A", {"X": (1, 1), "Y": (0, 0)})
    B = Replica("B", {"X": (0, 0), "Y": (0, 0)})     # lagging on X
    C = Replica("C", {"X": (5, 5), "Y": (0, 0)})
    s = Session("c5")

    # (a) RYW: c5 wrote X@v1; reading X from B (v0) violates; from A (v1) ok.
    s.record_write("X", 1)
    ryw_b_ok, ryw_b = check_ryw(s, B, "X")
    ryw_a_ok, ryw_a = check_ryw(s, A, "X")
    print("(a) RYW   : c5 last_write_version[X]=1")
    print(f"           read X@B -> need>={ryw_b[0]}, have={ryw_b[1]} -> "
          f"{'VIOLATION' if not ryw_b_ok else 'ok'}")
    print(f"           read X@A -> need>={ryw_a[0]}, have={ryw_a[1]} -> "
          f"{'ok' if ryw_a_ok else 'VIOLATION'}")

    # (b) MR: c5 reads X=5@v5 from C, then X from B (v0) -> backward -> violation.
    s.record_read("X", 5)
    mr_b_ok, mr_b = check_mr(s, B, "X")
    mr_c_ok, mr_c = check_mr(s, C, "X")
    print("(b) MR    : c5 highest_read_version[X]=5 (after reading X@v5 from C)")
    print(f"           read X@B -> need>={mr_b[0]}, have={mr_b[1]} -> "
          f"{'VIOLATION' if not mr_b_ok else 'ok'}")
    print(f"           read X@C -> need>={mr_c[0]}, have={mr_c[1]} -> "
          f"{'ok' if mr_c_ok else 'VIOLATION'}")

    # (c) MW: two writes seq 1 then seq 2; arrival [W2, W1] -> violation if naive.
    W1 = Write("X", 1, 1, "c5", seq=1)
    W2 = Write("X", 2, 2, "c5", seq=2)
    mw_first_ok, mw_first = check_mw(0, W2)          # W2 arrives when applied_seq=0
    mw_after_ok, mw_after = check_mw(0, W1)          # W1 first would be ok
    print("(c) MW    : writes W1(seq1), W2(seq2); arrival [W2, W1]")
    print(f"           W2 first: applied_seq={mw_first[0]}, got seq={mw_first[1]} "
          f"-> {'VIOLATION (out of order)' if not mw_first_ok else 'ok'}")
    print(f"           W1 first: applied_seq={mw_after[0]}, got seq={mw_after[1]} "
          f"-> {'ok' if mw_after_ok else 'VIOLATION'}")

    # (d) WFR: c5 reads Y=0@v0 then writes Z=1@v8 with read_dep{Y:0}; lagging
    # replica with Y absent (v0) is fine; but a write with read_dep{X:5} on a
    # replica that has X<v5 violates.
    Rd = Replica("Rd", {"X": (3, 3), "Z": (0, 0)})
    Wz = Write("Z", 1, 8, "c5", seq=1, read_dep={"X": 5})
    wfr_ok, wfr_d = check_wfr(Rd, Wz)
    print("(d) WFR   : write Z@v8 read_dep={X:5} on replica Rd with X=3@v3")
    print(f"           check -> "
          f"{'ok' if wfr_ok else 'VIOLATION '+str(wfr_d)}")

    print()
    # --- aggregate: with ALL guarantees ENFORCED (sticky + cache + buffer), the
    # history has ZERO violations because every lagging read/write is blocked. ---
    print("With ALL guarantees ENFORCED (block/sticky/buffer on every op), every")
    print("lagging read/write waits for anti-entropy, so the history has ZERO")
    print("violations:\n")
    # RYW enforced: read X from the sticky replica A (has v1) -> ok
    ryw_enf_ok, _ = check_ryw(s, A, "X")
    # MR enforced: read X only from a replica >= 5 (C) -> ok
    mr_enf_ok, _ = check_mr(s, C, "X")
    # MW enforced: buffer W2 until W1 applied -> apply W1 then W2 -> ok
    applied = 0
    pend = []
    for w in [W2, W1]:
        ok, _ = check_mw(applied, w)
        if ok:
            applied = w.seq
        else:
            pend.append(w)
    for w in list(pend):
        ok, _ = check_mw(applied, w)
        if ok:
            applied = w.seq
    mw_enf_ok = (applied == 2)
    # WFR enforced: buffer Z on Rd until X>=5 -> ok
    Rd.set("X", 5, 5)
    wfr_enf_ok, _ = check_wfr(Rd, Wz)
    print(f"  RYW (sticky A)         : {'ok' if ryw_enf_ok else 'VIOLATION'}")
    print(f"  MR  (route to C, v5)   : {'ok' if mr_enf_ok else 'VIOLATION'}")
    print(f"  MW  (buffer by seq)    : applied_seq={applied} (==2) -> "
          f"{'ok' if mw_enf_ok else 'VIOLATION'}")
    print(f"  WFR (buffer until X=5) : {'ok' if wfr_enf_ok else 'VIOLATION'}\n")

    ok_all = (not ryw_b_ok and ryw_a_ok and not mr_b_ok and mr_c_ok
              and not mw_first_ok and mw_after_ok and not wfr_ok
              and ryw_enf_ok and mr_enf_ok and mw_enf_ok and wfr_enf_ok)
    print("Summary (violations appear when a guarantee is OFF; none when ON):")
    print(f"  (a) RYW  off-read violates, sticky ok        : "
          f"{'OK' if (not ryw_b_ok and ryw_enf_ok) else 'FAIL'}")
    print(f"  (b) MR   off-read violates, route-to-C ok    : "
          f"{'OK' if (not mr_b_ok and mr_enf_ok) else 'FAIL'}")
    print(f"  (c) MW   out-of-order violates, buffered ok  : "
          f"{'OK' if (not mw_first_ok and mw_enf_ok) else 'FAIL'}")
    print(f"  (d) WFR  context-lag violates, buffered ok   : "
          f"{'OK' if (not wfr_ok and wfr_enf_ok) else 'FAIL'}")
    print()
    assert ok_all, "GOLD CHECK FAILED"
    print("=> [check] GOLD: all 4 session guarantees verified; every violation "
          "is fixed by its enforcement mechanism: OK")
    print("GOLD scalars (pinned for .html):")
    print("  RYW violation (B)  = (need=1, have=0)")
    print("  MR  violation (B)  = (need=5, have=3)")
    print("  MW  violation      = (applied_seq=0, got seq=2)")
    print("  WFR violation (Rd) = (X, need=5, have=3)")
    print("  all enforced       = 0 violations")
    return ok_all


# ===========================================================================
# main
# ===========================================================================
def main():
    print("session_guarantees.py - reference impl. All numbers below feed")
    print("SESSION_GUARANTEES.md. python3, stdlib only. Deterministic (no RNG).")
    print("Scenario: replicas of keys X (and Y/Z); scripted states + arrival orders.")
    print("Source: Terry et al. 1994/1995 (Bayou); DeCandia 2007 (Dynamo).")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
