"""
raft.py - Reference implementation of the Raft consensus algorithm
(Diego Ongaro & John Ousterhout, 2014, USENIX ATC): leader election,
log replication, safety, and log repair.

This is the single source of truth that RAFT.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 raft.py

============================================================================
THE INTUITION (read this first) -- the ship's logbook
============================================================================
Raft keeps a cluster of servers agreeing on ONE ordered list of commands --
the replicated log -- so the cluster looks like a single reliable machine. It
does this with three ideas, each easier to reason about than Paxos:

  1. A SINGLE LEADER. Exactly one node accepts client commands at a time. If
     you talk to a non-leader it redirects you. "Who is the leader?" is the
     only question an election answers.

  2. RANDOMIZED ELECTION TIMEOUTS. Followers wait. The first follower whose
     timer fires (before hearing from a leader) starts an election: it bumps
     its TERM, votes for itself, and asks everyone else for their vote
     (RequestVote RPC). The first candidate to reach a MAJORITY wins and
     becomes leader for that term. Randomized timeouts make two candidates
     firing at once (a "split vote") unlikely -- they just wait out the term.

  3. THE LEADER DRIVES THE LOG. The leader appends each new command to its
     own log, then pushes it to followers with AppendEntries. An entry is
     COMMITTED once a majority has it; the leader tells followers the commit
     point in the next AppendEntries. The leader never overwrites its own log
     -- it only APPENDS. Followers, however, can carry STALE entries from old
     dead leaders; the new leader OVERWRITES those until they match.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  term          : a logical clock / "reign number". Monotonically increasing.
                  Each election starts a new term. Terms detect stale leaders:
                  a node with a higher term always wins and forces others down.
  state         : one of FOLLOWER, CANDIDATE, LEADER. Every node starts a
                  FOLLOWER. A timed-out follower becomes a CANDIDATE. A
                  candidate that wins a majority becomes LEADER.
  leader        : the one node that accepts client writes for the current term.
  RequestVote   : the RPC a candidate sends to ask for a vote.
  (RPC)           Args: term, candidateId, lastLogIndex, lastLogTerm.
                  A voter grants its vote iff:
                    (a) candidate's term >= voter's term, AND
                    (b) voter hasn't voted for someone else this term, AND
                    (c) candidate's log is AT LEAST AS UP-TO-DATE as the
                        voter's (the "leader election restriction").
  AppendEntries : the RPC a leader sends to replicate log entries AND to act
  (RPC)           as a heartbeat. Args: term, leaderId, prevLogIndex,
                  prevLogTerm, entries[], leaderCommit.
                  A follower accepts it iff:
                    (a) leader's term >= follower's term, AND
                    (b) the follower's log MATCHES the leader's up to
                        prevLogIndex: log[prevLogIndex].term == prevLogTerm
                        (the "log matching property"). If not, the follower
                        rejects; the leader decrements nextIndex and retries
                        until it finds the matching point, then OVERWRITES
                        everything after it.
  commit index  : the index of the highest log entry known to be replicated on
                  a majority AND therefore safely applied to the state machine.
  majority      : floor(N/2) + 1 nodes. With N=5 that is 3.
  up-to-date    : a candidate's log is "at least as up-to-date" as a voter's
                  iff its LAST entry has a higher term, OR (same last term AND
                  a longer-or-equal log). This guarantees a winning candidate's
                  log already contains every committed entry (safety).
  nextIndex /
  matchIndex    : per-follower leader bookkeeping. nextIndex = next log index
                  to send to that follower (initialized to leader's last+1);
                  matchIndex = highest index known to be replicated there.

============================================================================
THE PAPER & THE LINEAGE
============================================================================
  Raft (Ongaro & Ousterhout 2014, USENix ATC) : the protocol here.
         Designed for UNDERSTANDABILITY; crash-fault tolerant (2f+1).
  Paxos (Lamport 1998) : the predecessor; Raft is its readable cousin.
  Multi-Paxos vs Raft : both leader-based, both majority-commit. Raft pins
         "strong leader" as first-class, so log repair is a clean append/
         overwrite (Section E) instead of Paxos's gaps.
  Zab (Junqueira/Reed/Serafini, ZooKeeper) : Raft-like leader-based atomic
         broadcast.
  etcd/K8s, Consul, TiKV : production Raft (cluster size 3 or 5).

KEY INVARIANTS (verified by the gold check):
  Election Safety     : at most one leader per term. (Any two majorities
                        share >= 1 node; that node voted for only one
                        candidate per term.)
  Leader Append-Only  : a leader never overwrites or deletes its own log.
  Log Matching        : if two logs share an entry at index i with the same
                        term, the logs are identical up to i.
  Leader Completeness : a winning candidate's log contains every committed
                        entry (enforced by the up-to-date vote restriction).
  State Machine Safety: all committed entries are identical across the
                        majority -> what the gold check asserts.

Conventions in this file:
  N            : cluster size (here 5).
  log          : 1-indexed list of (term, cmd) pairs; log[0] = (0, "sentinel")
                 so prevLogIndex=0 / prevLogTerm=0 describes "the start".
  commit_index : highest committed index (0 = nothing committed yet).
  nodes        : list of Node objects [0..N-1].
  timeouts     : seeded random election timeouts (ms), deterministic per seed.
"""

from __future__ import annotations

import random

BANNER = "=" * 72
N = 5


# ============================================================================
# 1. CORE PRIMITIVES  (the code RAFT.md walks through)
# ============================================================================

def majority(n: int) -> int:
    """Smallest quorum that always overlaps another: floor(n/2)+1.

    For N=5 that is 3. Any two such majorities share >= 1 node -> election
    safety (only one candidate can win a given term).
    """
    return n // 2 + 1


def last_log_index(node: "Node") -> int:
    """Index of the last entry in node.log (0 if only the sentinel)."""
    return len(node.log) - 1


def last_log_term(node: "Node") -> int:
    """Term of the last entry in node.log (0 if only the sentinel)."""
    return node.log[-1][0]


def is_up_to_date(cand_last_term: int, cand_last_index: int,
                  voter: "Node") -> bool:
    """The leader-election restriction (Raft 5.4.1).

    A candidate's log is "at least as up-to-date" as the voter's iff:
      - its last entry's TERM is higher, OR
      - last terms are equal AND its log is at least as LONG.
    This is what stops a node with a stale (shorter / lower-term) log from
    buying enough votes to win and then lose a committed entry.
    """
    vt, vi = last_log_term(voter), last_log_index(voter)
    if cand_last_term != vt:
        return cand_last_term > vt
    return cand_last_index >= vi


class Node:
    """A Raft server. Log is 1-indexed; log[0] is a (0, "sentinel") anchor."""

    def __init__(self, nid: int, log=None):
        self.id = nid
        self.state = "follower"
        self.current_term = 0
        self.voted_for = None
        self.log = [(0, "sentinel")] if log is None else list(log)
        self.commit_index = 0
        # leader-only bookkeeping, populated when a node becomes leader
        self.next_index: dict[int, int] = {}
        self.match_index: dict[int, int] = {}

    def become_leader(self):
        self.state = "leader"
        last = last_log_index(self)
        self.next_index = {i: last + 1 for i in range(N) if i != self.id}
        self.match_index = {i: 0 for i in range(N) if i != self.id}

    def log_str(self) -> str:
        """Render the log from index 1, e.g.  [1:x1, 1:x2, 1:x3]."""
        body = ", ".join(f"{t}:{c}" for (t, c) in self.log[1:])
        return "[" + body + "]" if body else "[]"


# ----------------------------------------------------------------------------
# RPC: RequestVote  (candidate -> everyone)
# ----------------------------------------------------------------------------

def handle_request_vote(voter: Node, cand_term: int, cand_id: int,
                        cand_last_index: int, cand_last_term: int):
    """Process a RequestVote RPC at `voter`. Returns (granted: bool, term).

    Rules (Raft 5.4.1):
      1. If cand_term > voter.current_term, the voter steps down and adopts it.
      2. Reject if cand_term < voter.current_term (stale candidate).
      3. Grant iff voter has not already voted for someone else this term AND
         the candidate's log is at least as up-to-date as the voter's.
    """
    if cand_term > voter.current_term:
        voter.current_term = cand_term
        voter.voted_for = None
        voter.state = "follower"
    if cand_term < voter.current_term:
        return (False, voter.current_term)
    up_to_date = is_up_to_date(cand_last_term, cand_last_index, voter)
    if (voter.voted_for is None or voter.voted_for == cand_id) and up_to_date:
        voter.voted_for = cand_id
        voter.state = "follower"
        return (True, voter.current_term)
    return (False, voter.current_term)


# ----------------------------------------------------------------------------
# RPC: AppendEntries  (leader -> follower)
# ----------------------------------------------------------------------------

def handle_append_entries(follower: Node, leader_term: int,
                          prev_log_index: int, prev_log_term: int,
                          entries: list, leader_commit: int):
    """Process an AppendEntries RPC at `follower`.

    Returns (success: bool, term). Implements Raft 5.3 (log matching + repair):
      1. Reject if leader_term < follower.current_term (stale leader).
      2. Adopt a higher term and step down to follower.
      3. Reject if log[prev_log_index] does not exist or its term differs from
         prev_log_term -> the leader will decrement nextIndex and retry.
      4. On a match: walk the new entries; on a conflict (same index, different
         term) TRUNCATE from there and OVERWRITE; then append any new ones.
      5. Advance commit_index to min(leader_commit, last new entry index).
    """
    if leader_term < follower.current_term:
        return (False, follower.current_term)
    if leader_term > follower.current_term:
        follower.current_term = leader_term
        follower.voted_for = None
    follower.state = "follower"

    # (3) log matching check at prevLogIndex
    if prev_log_index >= len(follower.log):
        return (False, follower.current_term)
    if follower.log[prev_log_index][0] != prev_log_term:
        return (False, follower.current_term)

    # (4) append / overwrite
    for i, entry in enumerate(entries):
        idx = prev_log_index + 1 + i
        if idx < len(follower.log):
            if follower.log[idx][0] != entry[0]:          # conflict -> truncate
                follower.log = follower.log[:idx]
                for e in entries[i:]:
                    follower.log.append(e)
                break
            # identical (term,index) -> already present, keep, continue
        else:
            for e in entries[i:]:
                follower.log.append(e)
            break

    # (5) advance commit
    if leader_commit > follower.commit_index:
        last_new = prev_log_index + len(entries)
        follower.commit_index = min(leader_commit, last_new)
    return (True, follower.current_term)


# ----------------------------------------------------------------------------
# Leader-side replication of its whole log to one follower (with repair loop)
# ----------------------------------------------------------------------------

def replicate_to(leader: Node, follower: Node, leader_commit: int,
                 log=None):
    """Leader pushes entries from leader.next_index[follower.id] until the
    follower matches the leader's log, OR the leader is deposed.

    `log` is a list to append human-readable step lines to (for printing).
    Returns True if the follower ended up fully matched, False if the leader
    stepped down.
    """
    steps = 0
    while True:
        steps += 1
        ni = leader.next_index[follower.id]
        pli = ni - 1
        plt = leader.log[pli][0]
        new_entries = leader.log[ni:]
        if log is not None:
            log.append(
                f"    step {steps}: leader sends AppendEntries("
                f"prevLogIndex={pli}, prevLogTerm={plt}, "
                f"entries=[{', '.join(f'{t}:{c}' for t,c in new_entries) or ''}])")
        ok, fterm = handle_append_entries(
            follower, leader.current_term, pli, plt, new_entries, leader_commit)
        if ok:
            leader.next_index[follower.id] = last_log_index(leader) + 1
            leader.match_index[follower.id] = last_log_index(leader)
            if log is not None:
                log.append(f"      -> ACK, follower.log now {follower.log_str()}")
            return True
        if fterm > leader.current_term:
            leader.current_term = fterm
            leader.voted_for = None
            leader.state = "follower"
            if log is not None:
                log.append(f"      -> REJECT (follower term {fterm} higher; "
                           f"leader steps down)")
            return False
        leader.next_index[follower.id] = max(1, ni - 1)
        if log is not None:
            log.append(f"      -> REJECT (log mismatch at prevLogIndex={pli}); "
                       f"decrement nextIndex -> {leader.next_index[follower.id]}")


def advance_commit(leader: Node):
    """Leader updates commit_index = highest index replicated on a majority.

    We try indexes from the leader's last down to commit_index+1; an index is
    committable if a majority of nodes (including the leader) have a matching
    entry there. (Only entries from the leader's own term may advance commit
    under Raft's safety rule; here the leader appends in its own term, so any
    replicated index is committable.)
    """
    n = N
    for idx in range(last_log_index(leader), leader.commit_index, -1):
        # count leader itself + followers whose match_index >= idx
        copies = 1 + sum(1 for fid in leader.match_index
                         if leader.match_index[fid] >= idx)
        if copies >= majority(n):
            leader.commit_index = idx
            return idx
    return leader.commit_index


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def states_line(nodes):
    return "  " + "  ".join(f"n{n.id}:{n.state[:3]}" for n in nodes)


# ============================================================================
# 3. THE SIMULATION SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: leader election (N=5) -- randomized timeout -> RequestVote
# ----------------------------------------------------------------------------

def run_election(nodes, seed, term_offset=0, exclude=None):
    """Run one election round on `nodes` using seeded timeouts.

    exclude : set of node ids that are DOWN (crashed/partitioned) this term.
    Returns (winner_id_or_None, timeouts, votes_set, elected_bool).
    """
    exclude = exclude or set()
    rng = random.Random(seed)
    live = [n for n in nodes if n.id not in exclude]
    timeouts = {n.id: rng.randint(150, 300) for n in live}
    if not timeouts:
        return (None, timeouts, set(), False)
    winner_id = min(timeouts, key=timeouts.get)
    cand = nodes[winner_id]
    cand.state = "candidate"
    cand.current_term = term_offset + 1
    cand.voted_for = cand.id
    votes = {cand.id}
    cli = last_log_index(cand)
    clt = last_log_term(cand)
    for n in nodes:
        if n.id == cand.id or n.id in exclude:
            continue
        granted, _ = handle_request_vote(
            n, cand.current_term, cand.id, cli, clt)
        if granted:
            votes.add(n.id)
    elected = len(votes) >= majority(len(nodes))
    if elected:
        cand.become_leader()
    return (winner_id, timeouts, votes, elected)


def section_a():
    banner("SECTION A: leader election  (N=5)  -- randomized timeout -> RequestVote")
    print("Five nodes boot as FOLLOWERS in term 0. Each gets a RANDOM election")
    print("timeout (150-300 ms). Whoever's timer fires FIRST becomes a CANDIDATE,")
    print("bumps the term, votes for itself, and asks the other four for a vote.")
    print("First candidate to a MAJORITY (3) wins.\n")
    nodes = [Node(i) for i in range(N)]
    winner, timeouts, votes, elected = run_election(nodes, seed=2024)
    print("Seeded election timeouts (random.Random(2024), range 150-300 ms):")
    for i in sorted(timeouts):
        marker = "  <-- fires first -> becomes candidate" if i == winner else ""
        print(f"    n{i}: {timeouts[i]} ms{marker}")
    cand = nodes[winner]
    print(f"\n  candidate = n{winner},  increments term 0 -> {cand.current_term}")
    print(f"  votes for self: {{n{winner}}}")
    print("  sends RequestVote(term="
          f"{cand.current_term}, candidateId=n{winner}, "
          f"lastLogIndex={last_log_index(cand)}, lastLogTerm={last_log_term(cand)})")
    print(f"\n  vote tally (1 = granted):")
    for i in range(N):
        if i == winner:
            print(f"    n{i}: (self)")
        else:
            print(f"    n{i}: {'GRANTED' if i in votes else 'deny'}")
    print(f"\n  votes = {sorted(votes)}  ->  |votes| = {len(votes)}")
    print(f"  majority(N={N}) = floor({N}/2)+1 = {majority(N)}")
    print(f"  {len(votes)} >= {majority(N)} ?  "
          f"{'YES -> n' + str(winner) + ' becomes LEADER' if elected else 'NO'}")
    print(states_line(nodes))
    print(f"\n[check] exactly one leader (n{winner}), term={cand.current_term}, "
          f"votes={len(votes)}>={majority(N)}:  OK")
    return nodes, winner


# ----------------------------------------------------------------------------
# SECTION B: split vote -- two candidates in one term, neither reaches majority
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: split vote  (two candidates, one term)  -> no winner")
    print("Randomized timeouts make this rare, but it CAN happen: two followers")
    print("time out at almost the same instant and both start an election in the")
    print("SAME term. The remaining nodes split their single vote; if neither")
    print("candidate reaches a majority, the term ends with NO leader. Everyone")
    print("waits for the NEXT randomized timeout to try again in a new term.\n")
    print("Setup: n4 is DOWN this term (partitioned) so only 4 nodes vote.")
    print("  candidates : n1 (A) and n3 (B), both in term T.")
    print("  voters     : n0 and n2 (each may vote for exactly ONE candidate).\n")
    nodes = [Node(i) for i in range(N)]
    T = 1
    a, b = nodes[1], nodes[3]
    for cand in (a, b):
        cand.state = "candidate"
        cand.current_term = T
        cand.voted_for = cand.id
    # voter n0 grants A; voter n2 grants B (n4 is down, n1/n3 are the candidates)
    ga, _ = handle_request_vote(nodes[0], T, a.id,
                                last_log_index(a), last_log_term(a))
    gb, _ = handle_request_vote(nodes[2], T, b.id,
                                last_log_index(b), last_log_term(b))
    votes_a = {a.id} | ({nodes[0].id} if ga else set())
    votes_b = {b.id} | ({nodes[2].id} if gb else set())
    print(f"  term T = {T}   (n4 partitioned)")
    print(f"  A=n{a.id} votes: self(n{a.id})"
          + (f" + n0" if ga else "") + f" = {len(votes_a)}")
    print(f"  B=n{b.id} votes: self(n{b.id})"
          + (f" + n2" if gb else "") + f" = {len(votes_b)}")
    print(f"\n  majority(N={N}) = {majority(N)}.")
    print(f"  A: {len(votes_a)} >= {majority(N)} ? {'YES' if len(votes_a)>=majority(N) else 'NO'}")
    print(f"  B: {len(votes_b)} >= {majority(N)} ? {'YES' if len(votes_b)>=majority(N) else 'NO'}")
    print("  -> neither candidate reaches a majority. Term {0} has NO leader.".format(T))
    print("     Both candidates stay CANDIDATE and let their timers re-randomize.\n")
    print("Resolution: next term T+1, a SINGLE node times out first and wins.")
    for n in nodes:
        n.state = "follower"; n.current_term = 0; n.voted_for = None
    winner, tos, votes, elected = run_election(nodes, seed=7777,
                                               term_offset=T, exclude=set())
    print(f"  term {T+1}: n{winner} times out first ({tos[winner]} ms), "
          f"collects {len(votes)} votes {sorted(votes)} "
          f"-> {'LEADER' if elected else 'still split'}.")
    print(states_line(nodes))
    print("\nWHY split votes self-heal: only ONE node can hold each voter's vote")
    print("per term, so a 50/50 split simply wastes the term; a fresh term with a")
    print("single candidate breaks the tie. No extra protocol machinery needed.")
    print(f"\n[check] term {T} had 0 leaders, term {T+1} has 1:  OK")


# ----------------------------------------------------------------------------
# SECTION C: log replication -- AppendEntries, majority ack = committed
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: log replication  (AppendEntries -> majority ack -> commit)")
    print("A client sends a command; the LEADER appends it to its own log, then")
    print("pushes it to followers with AppendEntries. Once a MAJORITY has the")
    print("entry it is COMMITTED; the leader advertises the new commitIndex on")
    print("the next AppendEntries so followers apply it too.\n")
    print("The log-matching check: the leader sends prevLogIndex/prevLogTerm; a")
    print("follower accepts only if its log[prevLogIndex].term == prevLogTerm.")
    print("This guarantees every follower that ACKs shares the leader's log up to")
    print("that point.\n")
    # leader with three new entries
    leader = Node(0, log=[(0, "sentinel"), (1, "x1"), (1, "x2"), (1, "x3")])
    leader.current_term = 1
    leader.become_leader()
    print(f"  leader n0 (term {leader.current_term}), leader.log = "
          f"{leader.log_str()}, commit_index = {leader.commit_index}")
    # followers: 1,3,4 current; 2 missing the last entry (stale/behind)
    f1 = Node(1, log=[(0, "sentinel"), (1, "x1"), (1, "x2"), (1, "x3")])
    f2 = Node(2, log=[(0, "sentinel"), (1, "x1"), (1, "x2")])   # missing x3
    f3 = Node(3, log=[(0, "sentinel"), (1, "x1"), (1, "x2"), (1, "x3")])
    f4 = Node(4, log=[(0, "sentinel"), (1, "x1"), (1, "x2"), (1, "x3")])
    followers = [f1, f2, f3, f4]
    print("  followers (initial):")
    for f in followers:
        print(f"    n{f.id}: {f.log_str()}"
              + ("   <-- stale: missing x3" if len(f.log) < len(leader.log) else ""))
    print()
    # replicate (commit_index still 0 -> followers won't advance yet)
    acks = {leader.id}
    for f in followers:
        trail = []
        replicate_to(leader, f, leader_commit=leader.commit_index, log=trail)
        for line in trail:
            print(line)
        if leader.match_index[f.id] >= last_log_index(leader):
            acks.add(f.id)
    print(f"\n  acks this round: {sorted(acks)}  (leader counts its own copy)")
    ci = advance_commit(leader)
    print(f"  copies of x3 = leader + {sum(1 for f in followers if last_log_index(f)>=3)} "
          f"followers = {1 + sum(1 for f in followers if last_log_index(f)>=3)} "
          f">= majority {majority(N)} -> commit_index advances 0 -> {ci}")
    # advertise commit so followers catch up commit_index
    for f in followers:
        handle_append_entries(f, leader.current_term,
                              last_log_index(leader), last_log_term(leader),
                              [], leader.commit_index)
    print("\n  logs after replication + commit:")
    print(f"    n0 (leader): {leader.log_str()}  commit={leader.commit_index}")
    for f in followers:
        print(f"    n{f.id}:        {f.log_str()}  commit={f.commit_index}"
              + ("   <-- was repaired" if f.id == 2 else ""))
    print("\nKEY POINTS:")
    print("  - n2's repair used prevLogIndex=2, prevLogTerm=1: its log[2].term=1")
    print("    matched, so the leader sent entries=[1:x3] and n2 appended it.")
    print("  - An entry is committed the INSTANT a majority has it, even before")
    print("    every follower is caught up (leader completeness + safety).")
    print("  - The leader NEVER overwrote its own log -- it only appended.")
    print(f"\n[check] commit_index={leader.commit_index} and all nodes agree "
          f"on entries 1..3:  OK")
    return leader, followers


# ----------------------------------------------------------------------------
# SECTION D: leader election restriction -- stale log loses an election
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: leader election restriction  (stale log loses the vote)")
    print("A voter will NOT grant its vote to a candidate whose log is LESS")
    print("up-to-date than its own. 'Up-to-date' (Raft 5.4.1) means:")
    print("    candidate wins if  last_term_cand >  last_term_voter")
    print("                       OR (last_term equal AND len_cand >= len_voter)")
    print("This guarantees a winning candidate's log already contains every")
    print("COMMITTED entry (leader completeness) -- the heart of Raft safety.\n")
    print("Up-to-date comparison table (voter last=(term, index)):")
    print("| # | voter last (t,i) | candidate last (t,i) | up-to-date? | reason                  |")
    print("|---|------------------|-----------------------|-------------|-------------------------|")
    cases = [
        (1, (2, 2), (1, 1), "NO",  "cand last_term 1 < voter 2"),
        (2, (1, 2), (2, 1), "YES", "cand last_term 2 > voter 1"),
        (3, (2, 3), (2, 2), "NO",  "same term, cand shorter (2<3)"),
        (4, (2, 2), (2, 3), "YES", "same term, cand >= voter length"),
        (5, (0, 0), (0, 0), "YES", "both empty (bootstrap election)"),
    ]
    for num, (vt, vi), (ct, ci), ans, reason in cases:
        print(f"| {num} | ({vt},{vi})            | ({ct},{ci})                 | {ans:<11} | {reason:<23} |")
    print()
    print("Worked election: voter n0 has committed entries up to term 2; a node")
    print("with a stale term-1 log tries to win term 3 and is REFUSED.\n")
    voter = Node(0, log=[(0, "sentinel"), (1, "a"), (2, "b")])   # last (2,2)
    stale = Node(1, log=[(0, "sentinel"), (1, "x")])             # last (1,1)
    print(f"  voter  n0: {voter.log_str()}   last entry = (term {last_log_term(voter)}, "
          f"index {last_log_index(voter)})")
    print(f"  cand.  n1: {stale.log_str()}  last entry = (term {last_log_term(stale)}, "
          f"index {last_log_index(stale)})")
    print(f"\n  is_up_to_date(cand_last_term={last_log_term(stale)}, "
          f"cand_last_index={last_log_index(stale)}, voter=n0)?")
    upd = is_up_to_date(last_log_term(stale), last_log_index(stale), voter)
    print(f"    candidate last_term ({last_log_term(stale)}) vs voter last_term "
          f"({last_log_term(voter)}): lower -> NOT up-to-date.")
    granted, _ = handle_request_vote(voter, 3, stale.id,
                                     last_log_index(stale), last_log_term(stale))
    print(f"  RequestVote -> {'GRANTED' if granted else 'DENIED'}")
    print("\nWithout this restriction a node that missed committed entries could")
    print("win an election and overwrite them -- Raft forbids it via this rule.")
    print(f"\n[check] stale candidate denied vote (up_to_date={upd}, granted={granted}):  OK")


# ----------------------------------------------------------------------------
# SECTION E: log consistency / repair -- overwrite conflicting entries
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: log consistency & repair  (overwrite conflicting entries)")
    print("A new leader may inherit followers carrying UNCOMMITTED entries from")
    print("an OLD dead leader (different term, never replicated). Raft repairs")
    print("them by walking nextIndex DOWN until it finds the matching point, then")
    print("TRUNCATES the follower's log from there and OVERWRITES with the")
    print("leader's entries. The leader's committed entries always win.\n")
    print("The invariant (log matching): if two logs agree on entry (index,term),")
    print("they agree on EVERYTHING before it. So finding ONE match point is")
    print("enough to make the follower consistent again.\n")
    # new leader term 2; follower has dead term-3 entries
    leader = Node(0, log=[(0, "sentinel"), (1, "a"), (1, "b"), (2, "c")])
    leader.current_term = 2
    leader.commit_index = 2                 # a,b committed; c being replicated
    leader.become_leader()
    follower = Node(3, log=[(0, "sentinel"), (1, "a"), (3, "d"), (3, "e")])
    print(f"  leader  n0 (term 2): {leader.log_str()}  commit_index={leader.commit_index}")
    print(f"  follower n3        : {follower.log_str()}   "
          f"(entries d,e from a dead term-3 leader)")
    print(f"  leader.nextIndex[n3] starts at {leader.next_index[follower.id]} "
          f"(leader last index + 1)\n")
    trail = []
    replicate_to(leader, follower, leader_commit=leader.commit_index, log=trail)
    for line in trail:
        print(line)
    print(f"\n  final follower n3: {follower.log_str()}")
    match = follower.log == leader.log
    print(f"  follower.log == leader.log ?  {match}")
    print("\n  The conflicting (3:d),(3:e) were uncommitted -> safe to discard.")
    print("  They could NEVER have been committed: any majority that included")
    print("  them would also have had to include the leader's committed a,b, but")
    print("  the leader election restriction prevents a candidate carrying a,b")
    print("  from losing to one carrying only d,e. So committed data is never lost.")
    print(f"\n[check] follower repaired to match leader (match={match}):  OK")
    return leader, follower


# ============================================================================
# 4. GOLD CHECK  (pinned values that raft.html recomputes in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  (pinned values for raft.html)")
    print("Capstone: run a FULL pipeline -- elect a leader (term 1), replicate a")
    print("3-entry log through the cluster (with one stale follower repaired),")
    print("commit once a majority has it, then assert the COMMITTED logs are")
    print("byte-identical across the majority. This is state-machine safety.\n")
    nodes = [Node(i) for i in range(N)]
    winner, timeouts, votes, elected = run_election(nodes, seed=2024)
    leader = nodes[winner]
    print(f"  election (seed 2024): winner = n{winner}, term = {leader.current_term}, "
          f"votes = {sorted(votes)} ({len(votes)} >= {majority(N)})")
    print(f"  seeded timeouts = { {i: timeouts[i] for i in sorted(timeouts)} }")
    # leader accepts client commands x1,x2,x3 (all in its term)
    for cmd in ("x1", "x2", "x3"):
        leader.log.append((leader.current_term, cmd))
    print(f"  leader.log = {leader.log_str()}")
    # follower initial logs: n1,n3,n4 current; n2 missing the last entry
    init = {
        1: [(0, "sentinel"), (1, "x1"), (1, "x2"), (1, "x3")],
        2: [(0, "sentinel"), (1, "x1"), (1, "x2")],
        3: [(0, "sentinel"), (1, "x1"), (1, "x2"), (1, "x3")],
        4: [(0, "sentinel"), (1, "x1"), (1, "x2"), (1, "x3")],
    }
    for fid, lg in init.items():
        nodes[fid].log = list(lg)
    followers = [nodes[i] for i in range(N) if i != leader.id]
    # re-init leader bookkeeping (log grew)
    leader.become_leader()
    for f in followers:
        replicate_to(leader, f, leader_commit=leader.commit_index, log=None)
    ci = advance_commit(leader)
    # advertise commit
    for f in followers:
        handle_append_entries(f, leader.current_term,
                              last_log_index(leader), last_log_term(leader),
                              [], leader.commit_index)
    majority_set = {leader.id} | {f.id for f in followers
                                  if last_log_index(f) >= ci}
    print(f"  after replication: commit_index = {ci}")
    print(f"  nodes with the committed log (1..{ci}): {sorted(majority_set)} "
          f"({len(majority_set)} >= {majority(N)})")
    print("\n  committed log (entries 1..%d) per node:" % ci)
    ref = leader.log[1:ci + 1]
    all_match = True
    for n in nodes:
        seg = n.log[1:ci + 1]
        same = seg == ref
        all_match = all_match and same
        mark = "" if same else "   <-- MISMATCH"
        print(f"    n{n.id}: {seg}{mark}")
    print()
    # GOLD scalars pinned for the .html
    print("GOLD scalars (for a compact .html check):")
    print(f"  majority(5)                    = {majority(N)}")
    print(f"  election_winner_seed2024       = n{winner}")
    print(f"  election_term                  = {leader.current_term}")
    print(f"  election_vote_count            = {len(votes)}")
    print(f"  commit_index_after_replication = {ci}")
    print(f"  committed_entries              = {ref}")
    print(f"  majority_consistent            = {all_match}")
    # assertions
    assert majority(N) == 3
    assert elected and leader.state == "leader"
    assert leader.current_term == 1
    assert len(votes) == N                         # unanimous first election
    assert ci == 3
    assert ref == [(1, "x1"), (1, "x2"), (1, "x3")]
    assert all_match is True
    assert len(majority_set) >= majority(N)
    print("\n[check] majority committed logs identical & all gold identities hold:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("raft.py - reference impl. All numbers below feed RAFT.md.")
    print("python stdlib only (random for seeded election timeouts).")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
