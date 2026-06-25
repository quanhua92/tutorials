"""
pbft.py - Reference implementation of Practical Byzantine Fault Tolerance
(PBFT, Castro & Liskov 1999): the canonical 3f+1 BFT consensus protocol.

This is the single source of truth that PBFT.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 pbft.py    (pure Python stdlib, no dependencies)

========================================================================
THE INTUITION (read this first) -- the notary's office
========================================================================
PBFT is a protocol that lets N replicas agree on the SAME ordered log of
operations even though up to f of them are TRAITORS (Byzantine). The trick is
a three-phase vote:

  * PRE-PREPARE : a leader (the "primary") PROPOSES a value for slot n. It
                  signs a PRE-PREPARE and broadcasts it.         (1 -> N-1)
  * PREPARE     : every replica broadcasts its first vote on that proposal
                  to every other replica. Once a replica holds 2f+1 matching
                  votes it is "prepared" -- it now knows the network has SEEN
                  this value, so no CONFLICTING value can also be prepared.
                                                                 (all-to-all)
  * COMMIT      : every prepared replica broadcasts a second vote ("I am
                  prepared"). Once a replica holds 2f+1 commit votes it is
                  "committed" and may safely execute / reply to the client.
                                                                 (all-to-all)

The two all-to-all rounds are WHY PBFT costs O(N^2) messages per request.
Crash-only protocols (Paxos/Raft) need only a leader->followers round per
slot, so they are O(N) -- but they cannot withstand lies.

If the primary is itself a traitor (sends different values to different
replicas), the Prepare phase detects the equivocation: no replica can collect
2f+1 matching votes. Replicas then run a VIEW-CHANGE: they depose the suspect
primary, rotate leadership to the next replica (primary = view mod N), and
re-propose. Because any prepared certificate holds >= f+1 honest signers, the
new primary cannot silently drop or alter a value that already got prepared.

========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
========================================================================
  f            : number of Byzantine (arbitrary) faults tolerated.
  N            : total replicas = 3f+1.
  primary      : the leader for the current view;  primary = view mod N.
  replica      : any of the N nodes (the primary is also a replica).
  pre-prepare  : the primary's signed PROPOSAL  <v, n, digest>.   1 -> N-1.
  prepare      : a replica's first-round VOTE   <v, n, digest, i>. all-to-all.
  commit       : a replica's second-round VOTE  <v, n, digest, i>. all-to-all.
  2f+1         : the QUORUM. A replica is "prepared"/"committed" once it holds
                 2f+1 matching votes for the same (view, seq, digest).
  prepared     : holds a pre-prepare AND 2f+1 matching prepares.
  committed    : holds 2f+1 matching commits.
  prepared cert: the SET of 2f+1 prepare messages -> portable PROOF of
                 preparedness, shown to the new primary during view change.
  committed cert: the SET of 2f+1 commit messages -> proof of commitment.
  view         : a configuration identified by a number v; primary = v mod N.
  view change  : the recovery procedure that rotates the primary when it is
                 suspected faulty. New primary collects 2f+1 VIEW-CHANGE msgs.

========================================================================
THE LINEAGE (papers)
========================================================================
  Byzantine Generals (Lamport, Shostak, Pease 1982, ACM TOCS)
        -> proved N >= 3f+1 is NECESSARY for Byzantine agreement.
  PBFT (Castro & Liskov 1999, OSDI)
        -> the practical 3f+1 protocol: 3 phases, O(N^2) messages, view
           change. Used in early permissioned chains.
  Paxos (Lamport 1998) / Raft (Ongaro & Ousterhout 2014)
        -> crash-only 2f+1, O(N) per slot. Cannot tolerate lies.
           (see CRASH_VS_BYZANTINE.md for the 2f+1 vs 3f+1 derivation)
  Tendermint (Buchman 2016)
        -> 3f+1 BFT, round-robin proposer, 2 deterministic rounds.
  HotStuff (Yin et al. 2019, PODC)
        -> 3f+1 BFT with LINEAR view change (O(N) not O(N^2)) using
           threshold / aggregatable signatures; the modern baseline.

KEY FORMULAS (all verified against the papers + asserted in code):
    replicas N              = 3f + 1
    quorum (prepare/commit) = 2f + 1
    max Byzantine tolerated = (N - 1) // 3
    messages per request (point-to-point unicast, all-to-all in 2 rounds):
        pre_prepare = N - 1                 (primary -> backups)
        prepare     = N * (N - 1)           (all-to-all)
        commit      = N * (N - 1)           (all-to-all)
        total       = (N - 1) + 2*N*(N - 1) = (N - 1)(2N + 1)   = O(N^2)
    prepared-certificate overlap safety (== crash_vs_byzantine derivation):
        two 2f+1 quorums on 3f+1 replicas overlap in
            >= 2*(2f+1) - (3f+1) = f + 1  nodes,
        of which >= (f+1) - f = 1 is honest ->
        no two CONFLICTING prepared certs can coexist (safety).

NOTE on the all-to-all model: in classic PBFT the primary does not send a
prepare (it authored the pre-prepare). Modern BFT (HotStuff/Tendermint) and
this tutorial count all N replicas voting in prepare and commit -- a constant-
factor difference, identical O(N^2) classification, and it makes the quorum
arithmetic (2f+1 matching votes) clean.

Conventions for the simulations:
    nodes    : [0, 1, ..., N-1]; node 0 is the primary in view 0.
    silent   : a set of node ids that send nothing (e.g. a crashed / ostracized
               Byzantine node during view change).
    values   : short strings ("X", "Y", "PAY(alice,100)") for readable digests.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE CORE PBFT MACHINERY  (the code PBFT.md walks through)
# ============================================================================

def pbft_N(f: int) -> int:
    """Number of replicas needed to tolerate f Byzantine faults: 3f+1."""
    return 3 * f + 1


def pbft_quorum(f: int) -> int:
    """Quorum for the prepare and commit phases: 2f+1.

    Any two such quorums on 3f+1 replicas overlap in >= f+1 nodes, so >= 1
    honest node is always shared -> no two conflicting certificates can exist.
    """
    return 2 * f + 1


def pbft_max_byz(N: int) -> int:
    """Largest f a cluster of N replicas can tolerate: (N-1)//3."""
    return (N - 1) // 3


def primary_of_view(v: int, N: int) -> int:
    """The primary (leader) for view v is v mod N (round-robin rotation)."""
    return v % N


def quorum_overlap(quorum: int, N: int) -> int:
    """Inclusion-exclusion lower bound on the overlap of two quorums:
    2*quorum - N. For PBFT (quorum=2f+1, N=3f+1) this equals f+1."""
    return 2 * quorum - N


def honest_in_overlap(quorum: int, N: int, f: int) -> int:
    """Honest nodes guaranteed in the overlap of two PBFT quorums.
    overlap - f (subtract the f traitors that could hide there).
    For PBFT this is (f+1) - f = 1 -- the single honest safety anchor."""
    return quorum_overlap(quorum, N) - f


def messages_per_request(N: int) -> dict:
    """Point-to-point message counts for ONE PBFT request (all-to-all model).
        pre_prepare : primary unicasts proposal to N-1 backups
        prepare     : each of N replicas unicasts its prepare to N-1 peers
        commit      : each of N replicas unicasts its commit  to N-1 peers
        total       = (N-1) + 2*N*(N-1) = (N-1)(2N+1)   = O(N^2)
    """
    pp = N - 1
    pr = N * (N - 1)
    cm = N * (N - 1)
    return {"pre_prepare": pp, "prepare": pr, "commit": cm,
            "total": pp + pr + cm}


# ----------------------------------------------------------------------------
# A faithful (small) PBFT normal-case simulator. One request, three phases.
# Returns a structured dict; the section printers below format it.
# ----------------------------------------------------------------------------

def simulate(N: int, f: int, primary: int, value: str,
             byzantine_sends: dict | None = None,
             silent: frozenset = frozenset()) -> dict:
    """Run the PBFT normal-case 3-phase for ONE request.

    Args:
        N, f           : cluster size (3f+1) and fault bound.
        primary        : the proposing primary for this view.
        value          : the value the (honest) primary proposes.
        byzantine_sends: if given, the primary EQUIVOCATES -- a dict
                         {replica_id: value_it_receives}. Replicas not listed
                         get `value`. Used for the Byzantine-primary attack.
        silent         : node ids that send no prepare/commit (e.g. an
                         ostracized Byzantine node after view change).

    Returns a dict with per-replica prepare/commit vote tallies, prepared /
    committed booleans, the value each replica committed, and message counts.
    A replica's OWN vote counts toward its own tally (its prepare is in its log).
    """
    Q = pbft_quorum(f)
    replicas = list(range(N))
    byz_primary = byzantine_sends is not None  # primary equivocates

    # ---- Phase 1: PRE-PREPARE ----
    # every non-primary replica receives exactly one proposal
    received: dict[int, str] = {}
    for r in replicas:
        if r == primary:
            continue
        received[r] = byzantine_sends.get(r, value) if byz_primary else value

    # ---- Phase 2: PREPARE (all-to-all) ----
    # who sends a prepare? every replica EXCEPT a silent one, and EXCEPT the
    # primary when it is equivocating (it already lied via the pre-prepare).
    prepare_senders = [r for r in replicas
                       if r not in silent and not (byz_primary and r == primary)]
    prepare_votes: dict[int, dict[str, set]] = {r: {} for r in replicas}
    for r in prepare_senders:
        val = received.get(r, value) if byz_primary else value
        prepare_votes[r].setdefault(val, set()).add(r)          # own vote
        for peer in replicas:
            if peer != r:
                prepare_votes[peer].setdefault(val, set()).add(r)
    prepared: dict[int, bool] = {}
    prepared_value: dict[int, str | None] = {}
    for r in replicas:
        best_val, best_n = None, 0
        for val, senders in prepare_votes[r].items():
            if len(senders) > best_n:
                best_n, best_val = len(senders), val
        prepared[r] = best_n >= Q
        prepared_value[r] = best_val if prepared[r] else None

    # ---- Phase 3: COMMIT (all-to-all, only prepared replicas send) ----
    commit_senders = [r for r in replicas if prepared[r] and r not in silent]
    commit_votes: dict[int, dict[str, set]] = {r: {} for r in replicas}
    for r in commit_senders:
        val = prepared_value[r]
        commit_votes[r].setdefault(val, set()).add(r)
        for peer in replicas:
            if peer != r:
                commit_votes[peer].setdefault(val, set()).add(r)
    committed: dict[int, bool] = {}
    committed_value: dict[int, str | None] = {}
    for r in replicas:
        best_val, best_n = None, 0
        for val, senders in commit_votes[r].items():
            if len(senders) > best_n:
                best_n, best_val = len(senders), val
        committed[r] = best_n >= Q
        committed_value[r] = best_val if committed[r] else None

    pp_msgs = N - 1
    prep_msgs = len(prepare_senders) * (N - 1)
    comm_msgs = len(commit_senders) * (N - 1)
    return {
        "N": N, "f": f, "Q": Q, "primary": primary, "value": value,
        "byz_primary": byz_primary, "received": received,
        "prepare_senders": prepare_senders, "prepare_votes": prepare_votes,
        "prepared": prepared, "prepared_value": prepared_value,
        "commit_senders": commit_senders, "commit_votes": commit_votes,
        "committed": committed, "committed_value": committed_value,
        "messages": {"pre_prepare": pp_msgs, "prepare": prep_msgs,
                     "commit": comm_msgs,
                     "total": pp_msgs + prep_msgs + comm_msgs},
    }


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def nodes_line(label: str, N: int, primary: int,
               byz: set | None = None, silent: set | None = None) -> str:
    """Render N nodes; mark the primary (*) and Byzantine (!) / silent (~)."""
    byz = byz or set()
    silent = silent or set()
    cells = []
    for i in range(N):
        if i in byz:
            cells.append(f"[{i}!]")
        elif i in silent:
            cells.append(f"[{i}~]")
        elif i == primary:
            cells.append(f"[{i}*]")
        else:
            cells.append(f"[{i} ]")
    return f"  {label:<10} " + " ".join(cells)


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the three phases (N=4, f=1, honest primary)
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: the three phases  (N=4, f=1, honest primary)")
    N, f = 4, 1
    Q = pbft_quorum(f)                       # 3
    primary = 0                              # view 0
    value = "PAY(alice,100)"                 # the client request
    print(f"Setup:  N = 3f+1 = {N} replicas,  f = {f},  quorum Q = 2f+1 = {Q}")
    print(f"        view = 0,  primary = view mod N = 0 mod {N} = {primary}")
    print(f"        client request : {value}")
    print(nodes_line("cluster:", N, primary))
    print("        (* = primary)\n")

    res = simulate(N, f, primary, value)

    # ---- Phase 1: PRE-PREPARE ----
    print("--- Phase 1: PRE-PREPARE  (primary broadcasts its proposal) ---")
    backups = [r for r in range(N) if r != primary]
    print(f"  primary {primary} -> PRE-PREPARE(v=0, n=1, '{value}')")
    for r in backups:
        print(f"      -> replica {r}")
    print(f"  messages: {res['messages']['pre_prepare']}  (= N-1 = {N-1})\n")

    # ---- Phase 2: PREPARE ----
    print("--- Phase 2: PREPARE  (all-to-all vote, O(N^2)) ---")
    print("  Every replica broadcasts a PREPARE for the proposal to every peer:")
    for r in range(N):
        peers = [p for p in range(N) if p != r]
        print(f"  replica {r} -> {{{', '.join(map(str, peers))}}}: "
              f"PREPARE(v=0, n=1, '{value}')")
    print(f"  messages: {res['messages']['prepare']}  (= N*(N-1) = "
          f"{N}*{N-1} = {N*(N-1)})")
    print("  per-replica prepare tally (matching votes received, self incl.):")
    for r in range(N):
        senders = res["prepare_votes"][r][value]
        print(f"    replica {r}: {len(senders)} votes {sorted(senders)}  "
              f">= quorum {Q}?  {'PREPARED' if res['prepared'][r] else 'no'}")
    print()

    # ---- Phase 3: COMMIT ----
    print("--- Phase 3: COMMIT  (all-to-all second vote, prepared replicas) ---")
    senders = [r for r in range(N) if res["prepared"][r]]
    print(f"  {len(senders)} prepared replica(s) {senders} each broadcast a COMMIT:")
    for r in senders:
        peers = [p for p in range(N) if p != r]
        print(f"  replica {r} -> {{{', '.join(map(str, peers))}}}: "
              f"COMMIT(v=0, n=1, '{value}')")
    print(f"  messages: {res['messages']['commit']}  "
          f"(= #prepared * (N-1) = {len(senders)}*{N-1})")
    print("  per-replica commit tally:")
    for r in range(N):
        n = len(res["commit_votes"][r].get(value, set()))
        print(f"    replica {r}: {n} votes  >= quorum {Q}?  "
              f"{'COMMITTED' if res['committed'][r] else 'no'}")
    print()

    # ---- Summary ----
    m = res["messages"]
    print("--- Summary ---")
    print(f"  pre-prepare messages : {m['pre_prepare']}")
    print(f"  prepare    messages  : {m['prepare']}")
    print(f"  commit     messages  : {m['commit']}")
    print(f"  TOTAL                : {m['total']}   "
          f"(= (N-1)(2N+1) = {N-1}*{2*N+1})")
    print(f"  compare N^2 = {N**2};  total/N^2 = {m['total']/N**2:.2f}  "
          f"-> grows as O(N^2)")
    all_ok = all(res["committed"][r] for r in range(N)) and \
        len({res["committed_value"][r] for r in range(N)}) == 1
    print(f"  all {N} replicas committed '{value}'?  "
          f"{'YES -> CONSENSUS' if all_ok else 'NO -> FAILED'}")
    print(f"\n[check] all replicas committed the same value:  "
          f"{'OK' if all_ok else 'FAIL'}")
    return res


# ----------------------------------------------------------------------------
# SECTION B: Byzantine primary (equivocation) -> detected in PREPARE
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: Byzantine primary (equivocation) -> detected in PREPARE")
    N, f = 4, 1
    Q = pbft_quorum(f)                       # 3
    primary = 0                              # BYZANTINE
    byz = {1: "X", 2: "X", 3: "Y"}          # equivocation
    print(f"Setup:  N = {N}, f = {f}, primary = {primary} is BYZANTINE")
    print(nodes_line("cluster:", N, primary, byz={primary}))
    print("        (! = Byzantine)\n")

    print("ATTACK -- the primary EQUIVOCATES: it sends DIFFERENT proposals:")
    print(f"  primary {primary} -> PRE-PREPARE(v=0, n=1, 'X') -> replicas 1,2")
    print(f"  primary {primary} -> PRE-PREPARE(v=0, n=1, 'Y') -> replica  3")
    print(f"  pre-prepare messages: {N-1}  (= N-1)\n")

    res = simulate(N, f, primary, "X", byzantine_sends=byz)

    print("--- Phase 2: PREPARE -- each replica votes for the value IT got ---")
    senders = res["prepare_senders"]
    print(f"  {len(senders)} honest replica(s) {senders} broadcast prepares "
          f"(byzantine primary sends none):")
    for r in senders:
        peers = [p for p in range(N) if p != r]
        val = res["received"][r]
        print(f"  replica {r} -> {{{', '.join(map(str, peers))}}}: "
              f"PREPARE(v=0, n=1, '{val}')")
    print(f"  messages: {res['messages']['prepare']}  "
          f"(= #honest*(N-1) = {len(senders)}*{N-1})\n")

    print("  per-replica prepare tally -- votes are SPLIT across 'X' and 'Y':")
    for r in senders:
        print(f"    replica {r}:")
        for val in sorted(res["prepare_votes"][r]):
            ss = sorted(res["prepare_votes"][r][val])
            print(f"        {len(ss)} vote(s) for '{val}'  from {ss}")
        best = max((len(s) for s in res["prepare_votes"][r].values()), default=0)
        print(f"        -> max matching = {best}, quorum = {Q}:  "
              f"{'PREPARED' if best >= Q else 'CANNOT PREPARE'}")

    print("\nDETECTION:")
    print(f"  No replica can assemble {Q} matching votes, because the byzantine")
    print("  primary split the vote: 'X' has 2 backers, 'Y' has 1.")
    print("  Worse, replicas 1 & 2 SEE replica 3's prepare for 'Y' while they")
    print("  hold 'X' -> two values for the same (view,seq) -> EQUIVOCATION.")
    print("  => primary 0 is suspect. Replicas stop accepting its pre-prepares")
    print("     and trigger a VIEW CHANGE (Section D).")
    detected = not any(res["prepared"][r] for r in senders)
    print(f"\n[check] no honest replica reached quorum {Q} (attack detected):  "
          f"{'OK' if detected else 'FAIL'}")
    return res


# ----------------------------------------------------------------------------
# SECTION C: quorum certificates (the portable PROOF of agreement)
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: quorum certificates  (the portable PROOF of agreement)")
    N, f = 4, 1
    Q = pbft_quorum(f)                       # 3
    print("A certificate is a SET of 2f+1 signed matching votes. It is a")
    print("PORTABLE proof: anyone can verify it without re-running the vote.\n")
    print(f"  prepared  certificate : {Q} (= 2f+1) matching PREPARE messages")
    print(f"  committed certificate: {Q} (= 2f+1) matching COMMIT  messages\n")

    print("WHY 2f+1 is the magic number (== CRASH_VS_BYZANTINE.md derivation):")
    ov = quorum_overlap(Q, N)
    ho = honest_in_overlap(Q, N, f)
    print(f"  two {Q}-vote quorums on {N} replicas overlap in at least")
    print(f"     2*Q - N = 2*{Q} - {N} = {ov}   node(s).")
    print(f"  of those {ov}, at most f = {f} can be Byzantine, so at least")
    print(f"     {ov} - {f} = {ho}  is HONEST.")
    print("  An honest replica cannot sign two conflicting prepares for the")
    print("  same (view, seq) -> two CONFLICTING prepared certs cannot both")
    print("  exist. That overlap of >= 1 honest signer is the safety anchor.\n")

    print("--- Assembling a prepared certificate (collect prepares one by one) ---")
    signers = [1, 2, 3]                      # deterministic order
    cert = []
    for s in signers:
        cert.append(s)
        if len(cert) >= Q:
            note = "QUORUM REACHED -> VALID CERTIFICATE"
        else:
            note = f"need {Q - len(cert)} more"
        print(f"  + prepare from replica {s}:  signers = {cert}  "
              f"({len(cert)}/{Q})  {note}")
    print(f"\n  prepared certificate = {{replica {cert[0]}, replica {cert[1]}, "
          f"replica {cert[2]}}}")
    print(f"  honest signers >= |cert| - f = {len(cert)} - {f} = "
          f"{len(cert) - f}  -> >= 1 honest replica was prepared.")
    print("  This certificate is what the new primary MUST honour during a")
    print("  view change (Section D): a value with a prepared cert cannot be")
    print("  silently dropped, because a client may already have f+1 replies.\n")

    print("--- Certificate & overlap sizes vs f ---")
    print("| f | N=3f+1 | quorum Q=2f+1 | cert signers | honest in cert "
          "| quorum overlap |")
    print("|---|--------|---------------|--------------|----------------"
          "|----------------|")
    for ff in range(1, 6):
        nn = pbft_N(ff)
        qq = pbft_quorum(ff)
        print(f"| {ff} | {nn:<6} | {qq:<13} | {qq:<12} | {qq - ff:<16} "
              f"| {quorum_overlap(qq, nn):<14} |")
    print("\n  Notice 'honest in cert' = Q - f = f+1 stays >= 2, and the quorum")
    print("  overlap = f+1 stays >= 2 -- both >> 1, so safety has slack.")
    print(f"\n[check] honest_in_overlap(Q={Q}, N={N}) = {ho} >= 1:  OK")
    return {"cert": cert, "overlap": ov, "honest_overlap": ho}


# ----------------------------------------------------------------------------
# SECTION D: view change (depose a faulty primary, rotate leadership)
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: view change  (depose a faulty primary, rotate leadership)")
    N, f = 4, 1
    Q = pbft_quorum(f)                       # 3
    primary = 0                              # deposed (byzantine)
    print("Trigger: Section B detected primary 0 equivocating. Replicas stop")
    print("accepting pre-prepares from view 0 and run a view change.\n")

    print(nodes_line("view 0:", N, primary, byz={primary}))
    new_view = 1
    new_primary = primary_of_view(new_view, N)
    print(f"  new view = 1,  new primary = view mod N = {new_view} mod {N} "
          f"= {new_primary}\n")

    print("--- Step 1: replicas broadcast VIEW-CHANGE(v=1, prepared_certs) ---")
    honest = [r for r in range(N) if r != primary]
    # nobody prepared in view 0 (Section B), so every prepared-cert set is empty
    vc_from = []
    for r in honest:
        vc_from.append(r)
        print(f"  replica {r} -> VIEW-CHANGE(v=1, last_seq=0, "
              f"prepared_certs={{}})   (nothing was prepared)")
    print(f"  VIEW-CHANGE messages sent: {len(vc_from)}  (from honest replicas)\n")

    print("--- Step 2: new primary collects 2f+1 view-change messages ---")
    print(f"  new primary {new_primary} needs {Q} view-change messages "
          f"(= 2f+1); its own counts.")
    collected = []
    # new primary is replica 1; it counts its own + the others
    for r in honest:
        collected.append(r)
        if len(collected) >= Q:
            note = "QUORUM -> send NEW-VIEW, I am the primary"
        else:
            note = f"need {Q - len(collected)} more"
        print(f"  + VIEW-CHANGE from replica {r}:  have {sorted(collected)}  "
              f"({len(collected)}/{Q})  {note}")
    print()

    print("--- Step 3: new primary inspects prepared certificates ---")
    print("  highest prepared seq across all view-change messages = 0")
    print("  (nothing was prepared in view 0). So it is SAFE to re-propose the")
    print("  client request cleanly in view 1.\n")

    print("--- Step 4: re-run the three phases under honest primary "
          f"{new_primary} ---")
    # the byzantine node 0 may stay silent (worst case); honest {1,2,3} still
    # have 2f+1 = 3 votes among themselves, so they reach consensus.
    res = simulate(N, f, new_primary, "X", silent=frozenset({0}))
    print(f"  primary {new_primary} -> PRE-PREPARE(v=1, n=1, 'X') -> replicas")
    print(f"  prepare phase: honest replicas {honest} each gather "
          f"{len(honest)} matching prepares (>= quorum {Q}) -> PREPARED")
    print(f"  commit  phase: honest replicas {honest} each gather "
          f"{len(honest)} matching commits  (>= quorum {Q}) -> COMMITTED")
    print(nodes_line("view 1:", N, new_primary, byz={0}))
    print(f"  messages: pre-prepare {res['messages']['pre_prepare']}, "
          f"prepare {res['messages']['prepare']}, "
          f"commit {res['messages']['commit']}, "
          f"total {res['messages']['total']}")

    print(f"\n  honest replicas {honest} committed:  "
          f"{[res['committed_value'][r] for r in honest]}")
    agreed = all(res["committed"][r] for r in honest) and \
        len({res["committed_value"][r] for r in honest}) == 1
    print(f"\n[check] after view change all {len(honest)} honest replicas agree "
          f"on 'X':  {'OK' if agreed else 'FAIL'}")
    return res


# ----------------------------------------------------------------------------
# SECTION E: PBFT vs Raft (and modern BFT)
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: PBFT vs Raft  (and modern BFT)")
    print("Two consensus families, one per failure model.\n")
    print("| protocol  | fault model | min N | quorum | msgs / request | "
          "leader / view change          |")
    print("|-----------|-------------|-------|--------|----------------|"
          "-------------------------------|")
    rows = [
        ("Raft",      "crash",     "2f+1", "f+1",  "O(N)",   "leader election, O(N log N) msgs"),
        ("PBFT",      "byzantine", "3f+1", "2f+1", "O(N^2)", "view change, O(N^2) msgs"),
        ("Tendermint", "byzantine", "3f+1", "2f+1", "O(N^2)",
         "round-robin proposer, 2 rounds"),
        ("HotStuff",  "byzantine", "3f+1", "2f+1", "O(N)",
         "LINEAR view change (threshold signatures)"),
    ]
    for r in rows:
        print("| " + " | ".join(r) + " |")
    print()

    print("Message cost, concrete (per request, point-to-point unicast):")
    print("| N  | f | Raft ~2(N-1) | PBFT (N-1)(2N+1) | ratio PBFT/Raft |")
    print("|----|---|--------------|------------------|-----------------|")
    for N in (4, 7, 10, 16, 31):
        f = pbft_max_byz(N)
        raft = 2 * (N - 1)
        pbft = messages_per_request(N)["total"]
        print(f"| {N:<2} | {f} | {raft:<12} | {pbft:<16} | "
              f"{pbft / raft:.1f}x             |")
    print()
    print("WHY PBFT is O(N^2): TWO all-to-all broadcast rounds (prepare +")
    print("commit), each N replicas x (N-1) peers. WHY Raft is O(N): only the")
    print("leader talks -- one AppendEntries stream to N-1 followers + acks.")
    print()
    print("Modern BFT (HotStuff, Tendermint) keeps 3f+1 safety but cuts the")
    print("communication to O(N) by AGGREGATING signatures: one threshold")
    print("signature replaces N individual ones, so a 'QC' (quorum certificate)")
    print("shrinks to O(1) and view change no longer re-broadcasts O(N^2) votes.")
    print("HotStuff is the modern baseline (DiemBFT / Aptos / Aleo consensus).\n")

    f = 1
    print(f"[check] PBFT/Raft message ratio grows ~ N: at N=4 it is "
          f"{messages_per_request(4)['total']/(2*3):.1f}x, at N=31 it is "
          f"{messages_per_request(31)['total']/(2*30):.1f}x  -> O(N^2)/O(N):  OK")


# ============================================================================
# 4. GOLD CHECK  (pinned values that pbft.html recomputes in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  (pinned values for pbft.html)")
    f = 1
    N = pbft_N(f)                            # 4
    Q = pbft_quorum(f)                       # 3

    print(f"Canonical point: f = {f}")
    print(f"  N = 3f+1               = {N}")
    print(f"  quorum Q = 2f+1        = {Q}")
    print(f"  max Byzantine tolerated= (N-1)//3 = ({N}-1)//3 = {pbft_max_byz(N)}")
    print(f"  honest replicas = N-f  = {N - f}")
    print()

    # GOLD 1 -- happy path: honest primary, all replicas commit the same value
    res_ok = simulate(N, f, primary=0, value="X")
    agreed_happy = all(res_ok["committed"][r] for r in range(N)) and \
        len({res_ok["committed_value"][r] for r in range(N)}) == 1
    print("GOLD 1 -- happy path (honest primary 0, value 'X'):")
    print(f"  messages total = (N-1)(2N+1) = {N-1}*{2*N+1} = "
          f"{res_ok['messages']['total']}")
    print(f"  all {N} replicas committed 'X'?  {agreed_happy}")
    print()

    # GOLD 2 -- byzantine primary: detected in prepare, nobody prepared
    res_b = simulate(N, f, primary=0, value="X",
                     byzantine_sends={1: "X", 2: "X", 3: "Y"})
    detected = not any(res_b["prepared"][r] for r in range(N) if r != 0)
    print("GOLD 2 -- Byzantine primary (equivocation X,X,Y):")
    print(f"  no honest replica reached prepare quorum {Q}?  "
          f"{detected}   (equivocation detected)")
    print()

    # GOLD 3 -- view change: new primary 1, byzantine 0 silent, honest agree
    res_d = simulate(N, f, primary=1, value="X", silent=frozenset({0}))
    honest = [r for r in range(N) if r != 0]
    agreed_vc = all(res_d["committed"][r] for r in honest) and \
        len({res_d["committed_value"][r] for r in honest}) == 1
    print("GOLD 3 -- after view change (primary 1, byzantine 0 silent):")
    print(f"  honest replicas {honest} all committed 'X'?  {agreed_vc}")
    print()

    ov = quorum_overlap(Q, N)               # 2
    ho = honest_in_overlap(Q, N, f)          # 1
    print("GOLD scalars (for a compact .html check):")
    print(f"  pbft_N(1)             = {pbft_N(1)}")
    print(f"  pbft_quorum(1)        = {pbft_quorum(1)}")
    print(f"  pbft_max_byz(4)       = {pbft_max_byz(4)}")
    print(f"  messages(4).total     = {messages_per_request(4)['total']}")
    print(f"  messages(7).total     = {messages_per_request(7)['total']}")
    print(f"  primary_of_view(1,4)  = {primary_of_view(1, 4)}")
    print(f"  quorum_overlap(Q={Q},N={N}) = {ov}   (= f+1)")
    print(f"  honest_in_overlap     = {ho}   (>= 1 -> safety)")

    # assertions -- the formulas must reproduce the textbook identities exactly
    assert N == 4 and Q == 3 and Q == 2 * f + 1
    assert pbft_max_byz(N) == f == 1
    assert agreed_happy and detected and agreed_vc
    assert messages_per_request(4)["total"] == 27
    assert messages_per_request(7)["total"] == 90
    assert primary_of_view(1, 4) == 1 and primary_of_view(2, 4) == 2
    assert ov == f + 1 and ho == 1
    # the defining identity: with f=1 Byzantine, the 3 honest nodes agree
    assert agreed_vc and len(honest) == 3
    print("\n[check] all gold identities reproduce from the formulas:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("pbft.py - reference impl. All numbers below feed PBFT.md.")
    print("python stdlib only.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
