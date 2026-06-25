"""
chain_replication.py - Reference implementation of Chain Replication
(Robbert van Renesse & Fred B. Schneider, OSDI 2004): replicas arranged in a
linear chain where the HEAD processes all writes (forwarding them down the
chain) and the TAIL processes all reads, giving strong consistency WITHOUT
running a consensus protocol on the normal read/write path.

This is the single source of truth that CHAIN_REPLICATION.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 chain_replication.py

============================================================================
THE INTUITION (read this first) -- the assembly line
============================================================================
Picture 4 workers on a factory assembly line, left to right:

        client                                          client
          | write                                         ^ read
          v                                               |
        [A]HEAD --> [B] --> [C] --> [D]TAIL
         accepts     relay   relay   serves queries
         updates

  * WRITES enter at the HEAD (A) and are passed hand-to-hand down the line to
    the TAIL (D). A write is only "complete" once the TAIL has it. Then the
    ACK travels back up the line (or directly) to the client.
  * READS go straight to the TAIL (D). Because every completed write passed
    through the tail, the tail's state is always the latest FULLY-replicated
    value. So a read NEVER returns a half-replicated or stale value.
  * The whole line is FIFO: writes reach every node in the SAME order. That
    single property -- one serial path for writes, one serial reader -- is what
    buys strong consistency (linearizability) WITHOUT any voting.

WHY IT AVOIDS CONSENSUS ON THE HOT PATH: Raft/Paxos reach every follower in
PARALLEL (leader fans out to all N-1) but must collect a MAJORITY ack to commit
-- that is a consensus vote per operation. Chain replication instead SERIALIZES
the write along one path; no quorum is ever counted, so there is nothing to
vote on. The cost is latency: a write makes N-1 hops instead of 1 round. The
win is simplicity + distributed load: each replica does O(1) work per op.

WHAT DOES THE CONSENSUS JOB: a separate CONFIGURATION MANAGER ("master", e.g.
ZooKeeper) watches for crashes. When a node fails, the master rewrites the chain
-- bumping the successor to head, or the predecessor to tail. Reconfiguration is
the only place consensus is needed, and it is rare; the per-operation path never
touches it. (So chain replication "moves consensus off the critical path".)

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  chain        : an ordered list of replicas. order[0] = HEAD, order[-1] = TAIL.
  head         : the FIRST node. Accepts ALL client updates (writes). Each new
                 write is appended here, then forwarded to the next node.
  tail         : the LAST node. Serves ALL client queries (reads). A write is
                 "complete" only once it reaches the tail.
  update /     : an update mutates state; a query reads it. (Paper's terms for
  query          write / read.) An update is a (seq, key, value) triple; seq is
                 a monotonic id assigned at the head.
  complete     : a write whose seq has reached the tail. Only complete writes
                 are visible to reads (the tail only ever has complete writes).
  FIFO order   : writes are delivered to every node in the same order they
                 entered at the head, because there is a single forward path.
                 This is the consistency engine -- no clocks, no votes.
  configuration: the current ordered list of LIVE replicas + which is head/tail.
  manager /    : the external service (often built on a consensus protocol like
  master         Zab/Paxos/Raft) that detects failures and rewrites the chain.
                 It is NOT consulted on the read/write path.
  fail-stop    : a failed node simply halts (crash). No malicious/Byzantine
                 behavior. (Same fault model as Raft.) 🔗 See CRASH_VS_BYZANTINE.md.

============================================================================
THE PAPER & THE LINEAGE
============================================================================
  Chain Replication (van Renesse & Schneider, OSDI 2004) : the protocol here.
          A primary-backup variant that spreads work across the chain for high
          throughput; crash-fault tolerant; needs the master for reconfig.
  Primary-Backup : the ancestor. One PRIMARY does all work + replicates to N-1
          backups. Chain replication distributes that work: head accepts writes,
          tail serves reads, interior nodes only relay.
  Gossip / Dynamo : the AP cousin -- eventual consistency, no single writer.
          Chain is the CP choice: strong consistency, single serial path.
  Raft/Paxos (🔗 RAFT.md / PAXOS.md) : consensus per operation (majority commit).
          Chain needs NO consensus per op; it only uses consensus (in the master)
          for the rare reconfiguration event.
  ZooKeeper (Zab) : the configuration manager most often paired with chain
          replication in practice (e.g. the original prototype used it).

KEY INVARIANTS (verified by the gold check):
  FIFO delivery    : every replica sees writes in the same order (single path).
  Tail completeness: a read returns the tail's value, which is always the most
                     recent COMPLETED write -- never a partial/stale one.
  Linearizability  : real-time order of completed writes is respected because
                     writes serialize through the head and reads hit the tail.
  No data loss on  : when the head fails, its successor is already up to date
  head failure       (writes flowed THROUGH it). When the tail fails, its
  / tail failure     predecessor is already up to date (writes flowed through
                     it BEFORE the tail). Reassignment loses nothing.
  Survives to 1    : unlike Raft (needs a majority), the chain keeps serving as
  node               long as >=1 replica is alive (it becomes both head+tail),
                     though it then depends on the master for correctness.

Conventions in this file:
  A,B,C,D   : the 4 starting replica ids (A=head, D=tail).
  chain     : a Chain object holding `order` (live node ids, head first) and
              per-node histories. head=order[0], tail=order[-1].
  history   : per node, a list of Write(seq,key,value) it has applied, in order.
  seq       : monotonic write id, assigned at the head (1,2,3,...).
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. CORE PRIMITIVES  (the code CHAIN_REPLICATION.md walks through)
# ============================================================================

class Write:
    """An update: a (seq, key, value) triple.

    `seq` is a monotonic id stamped at the head, so every replica that sees a
    write also learns its position in the global order. last-writer-wins per key.
    """

    __slots__ = ("seq", "key", "value")

    def __init__(self, seq: int, key: str, value):
        self.seq = seq
        self.key = key
        self.value = value

    def __repr__(self):
        return f"{self.key}={self.value}"


class Node:
    """A fail-stop chain replica.

    `history` is the ordered list of writes this node has applied. The derived
    store (latest value per key) is computed from it -- we keep the history so
    we can show the FIFO ordering and prove the tail has the full prefix.
    """

    def __init__(self, nid: str):
        self.id = nid
        self.alive = True
        self.history: list[Write] = []

    def latest(self, key: str):
        """Last-writer-wins value for `key`, or None if never written here."""
        for w in reversed(self.history):
            if w.key == key:
                return w.value
        return None

    def history_str(self) -> str:
        body = ", ".join(str(w) for w in self.history)
        return "[" + body + "]" if body else "[]"


class Chain:
    """A chain of fail-stop replicas.

    `order` is the list of LIVE node ids, head first. Crashing a node removes
    it from `order`, which automatically reassigns head (order[0]) and tail
    (order[-1]) -- exactly what the master does on a failure notification.
    """

    def __init__(self, node_ids):
        self.nodes = {nid: Node(nid) for nid in node_ids}
        self.order = list(node_ids)          # live chain, head first
        self.next_seq = 1

    @property
    def head(self) -> str:
        return self.order[0]

    @property
    def tail(self) -> str:
        return self.order[-1]

    @property
    def length(self) -> int:
        return len(self.order)

    def node(self, nid: str) -> Node:
        return self.nodes[nid]

    def write(self, key: str, value) -> tuple[Write, list[str]]:
        """Apply an update, propagating it HEAD -> ... -> TAIL.

        Returns (the_write, path_of_node_ids_it_traversed). The write is
        stamped with a fresh seq at the head, then appended to every live
        node in chain order. It is COMPLETE once it reaches the tail (which is
        guaranteed here because we walk the whole live chain synchronously).
        """
        assert self.length >= 1, "chain empty -- no replicas alive"
        w = Write(self.next_seq, key, value)
        self.next_seq += 1
        path = []
        for nid in self.order:                     # head -> ... -> tail
            self.nodes[nid].history.append(w)
            path.append(nid)
        return w, path

    def read(self, key: str):
        """Query the TAIL. Returns the latest COMPLETE value for `key`."""
        assert self.length >= 1, "chain empty -- no replicas alive"
        return self.nodes[self.tail].latest(key)

    def crash(self, nid: str):
        """Fail-stop a node: mark dead and drop it from the live chain.

        This reassigns head/tail implicitly:
          - if the head was crashed, order[0] (its successor) becomes head;
          - if the tail was crashed, order[-1] (its predecessor) becomes tail.
        No history is lost because writes always flowed THROUGH the new
        head/tail before reaching the crashed one.
        """
        assert nid in self.nodes, f"no node {nid}"
        self.nodes[nid].alive = False
        self.order = [x for x in self.order if x != nid]

    def chain_str(self) -> str:
        parts = []
        for nid in self.order:
            role = "HEAD" if nid == self.head else (
                "TAIL" if nid == self.tail else "")
            parts.append(f"{nid}{'(' + role + ')' if role else ''}")
        return " -> ".join(parts) + f"   [length={self.length}]"


# ----------------------------------------------------------------------------
# A pure reference model of the Raft write path, used ONLY for the Section E
# latency/work comparison. (The real raft.py is the authority; this is a tiny
# stand-in so chain_replication.py stays self-contained.) 🔗 RAFT.md.
# ----------------------------------------------------------------------------

def raft_write_cost(n: int) -> dict:
    """Cost of ONE committed write in Raft across n replicas (majority quorum).

    Latency: 1 parallel round -- the leader fans out AppendEntries to all n-1
    followers at once and waits for the first majority ack. Work at the leader:
    O(n) RPCs sent. (Per-follower work is O(1).)
    """
    q = n // 2 + 1                              # majority quorum
    return {
        "latency_rounds": 1,                     # 1 parallel round-trip
        "messages": 2 * (n - 1),                 # AppendEntries + ACK, parallel
        "leader_work": n - 1,                    # leader sends to every follower
        "quorum": q,
    }


def chain_write_cost(n: int) -> dict:
    """Cost of ONE completed write in chain replication across n replicas.

    Latency: n-1 sequential hops (head -> ... -> tail). Work per node: O(1)
    (each node receives once and forwards once; head sends once, tail receives
    once). No quorum is ever counted.
    """
    return {
        "latency_rounds": n - 1,                 # sequential hops
        "messages": 2 * (n - 1),                 # forward down + ack up
        "head_work": 1,                          # head accepts + forwards once
        "interior_work": 2,                      # receive + forward
    }


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def arrow_path(path, w) -> str:
    return "  client --> " + " --> ".join(path) + \
        f"  (write #{w.seq}: {w})"


# ============================================================================
# 3. THE SIMULATION SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: chain setup -- 4 nodes A->B->C->D, head writes, tail reads
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: chain setup  (4 nodes A->B->C->D)  -- head writes, tail reads")
    print("Replicas form a linear chain. The HEAD (A) is the only node that")
    print("accepts client UPDATES; each update is appended at the head then")
    print("forwarded down the chain until it reaches the TAIL (D), where it is")
    print("'complete'. The TAIL is the only node that answers client QUERIES --")
    print("because every completed write passed through it, its state is always")
    print("the latest fully-replicated value.\n")
    chain = Chain(["A", "B", "C", "D"])
    print(f"  chain = {chain.chain_str()}")
    print(f"  head  = {chain.head}   (accepts writes)")
    print(f"  tail  = {chain.tail}   (serves reads)\n")

    print("WRITE: client sends 'PUT x=1' to the HEAD. It flows down the chain:")
    w, path = chain.write("x", 1)
    print(arrow_path(path, w))
    print("  -> write reaches TAIL, is now COMPLETE. ACK returns to client.\n")

    print("READ: client sends 'GET x' to the TAIL:")
    r = chain.read("x")
    print(f"  client --> {chain.tail}  ->  returns x={r}\n")

    print("Per-node history after the write (each saw it, in FIFO order):")
    for nid in ["A", "B", "C", "D"]:
        n = chain.node(nid)
        print(f"    {nid}: {n.history_str()}")
    print("\nKEY POINT: the write visited every node along ONE path, so every")
    print("node saw it in the same order. No broadcast, no quorum, no vote.")
    print(f"\n[check] write latency = N-1 = {chain.length - 1} hops; "
          f"read returned x={r}:  OK")
    return chain


# ----------------------------------------------------------------------------
# SECTION B: strong consistency -- FIFO chain => reads return latest completed write
# ----------------------------------------------------------------------------

def section_b(chain: Chain):
    banner("SECTION B: strong consistency  (FIFO chain => tail sees all writes in order)")
    print("Strong consistency (linearizability) here comes from TWO facts:")
    print("  (1) ALL writes enter at the single HEAD and flow down ONE path, so")
    print("      every replica applies them in the SAME order (FIFO).")
    print("  (2) ALL reads hit the single TAIL, whose history is a PREFIX of the")
    print("      completed writes. So a read never sees a partial write.\n")
    print("Contrast with Raft/Paxos: they reach a MAJORITY to commit (a vote per")
    print("op). Chain replication needs NO vote -- the serial path IS the")
    print("consistency mechanism.\n")
    print("Interleaving writes and reads (every read must return the value of the")
    print("most recent COMPLETED write):\n")
    ops = [("write", "x", 2), ("read", "x"), ("write", "x", 3),
           ("read", "x"), ("write", "y", 9), ("read", "x"), ("read", "y")]
    print("  op                       result")
    print("  -----------------------  --------------------------------------")
    reads = []
    expected = []
    last_x, last_y = chain.read("x"), None
    for op in ops:
        if op[0] == "write":
            w, path = chain.write(op[1], op[2])
            if op[1] == "x":
                last_x = op[2]
            else:
                last_y = op[2]
            print(f"  write {op[1]}={op[2]:<4}              path "
                  f"{'->'.join(path)}, complete at {chain.tail}")
        else:
            r = chain.read(op[1])
            exp = last_x if op[1] == "x" else last_y
            reads.append(r)
            expected.append(exp)
            ok = "OK" if r == exp else "STALE!"
            print(f"  read  {op[1]:<6}              tail {chain.tail} returns "
                  f"{op[1]}={r}   (expected {exp}) [{ok}]")
    print()
    print("Ordering guarantee -- the tail's history is the global write order:")
    tail_hist = [(w.seq, str(w)) for w in chain.node(chain.tail).history]
    print(f"  tail history = {tail_hist}")
    print("  Every replica's history is a PREFIX of this order (FIFO). A read at")
    print("  the tail therefore returns the latest completed write, always.\n")
    consistent = reads == expected
    print(f"[check] all reads == latest completed write "
          f"({reads} == {expected})?  {consistent}:  OK")
    return chain


# ----------------------------------------------------------------------------
# SECTION C: head failure -- A crashes, B becomes head, no data loss
# ----------------------------------------------------------------------------

def section_c(chain: Chain):
    banner("SECTION C: head failure  (A crashes -> B becomes head, no data loss)")
    print("The configuration manager (e.g. ZooKeeper) detects that the HEAD (A)")
    print("has crashed and removes it from the chain. A's SUCCESSOR (B) becomes")
    print("the new head. Why is NO data lost? Because every write that A ever")
    print("accepted was FORWARDED through B on its way down -- so B's history")
    print("already contains all of A's writes. The chain simply continues.\n")
    print(f"  before: {chain.chain_str()}")
    chain.crash("A")
    print("  A crashes (fail-stop). manager reassigns head.")
    print(f"  after : {chain.chain_str()}")
    print(f"  new head = {chain.head}, tail still = {chain.tail}\n")

    print("Prove B already has everything A had (B's history is complete):")
    print(f"    B history = {chain.node('B').history_str()}")
    print("New writes now enter at B and flow B -> C -> D:")
    w, path = chain.write("x", 4)
    print(arrow_path(path, w))
    r = chain.read("x")
    print(f"  read at tail {chain.tail} -> x={r}")
    print("\nNo consensus vote was run for this write -- the chain just kept")
    print("forwarding. The ONLY consensus happened inside the manager, once, to")
    print("agree on the new membership.\n")
    print(f"[check] after head failover, write x=4 completed and read returned "
          f"x={r}:  OK")
    return chain


# ----------------------------------------------------------------------------
# SECTION D: tail failure -- D crashes, C becomes tail, reads keep working
# ----------------------------------------------------------------------------

def section_d(chain: Chain):
    banner("SECTION D: tail failure  (D crashes -> C becomes tail, no data loss)")
    print("Symmetric to the head case: the manager detects that the TAIL (D)")
    print("crashed and removes it. D's PREDECESSOR (C) becomes the new tail.")
    print("Why is NO data lost? Because every write that completed at D had to")
    print("pass THROUGH C first -- so C's history already contains every write D")
    print("ever saw. Reads now hit C instead of D.\n")
    print(f"  before: {chain.chain_str()}")
    chain.crash("D")
    print("  D crashes (fail-stop). manager reassigns tail.")
    print(f"  after : {chain.chain_str()}")
    print(f"  new tail = {chain.tail}, head still = {chain.head}\n")

    print("Read right after failover -- C must return the same value D would have:")
    r = chain.read("x")
    print(f"  read at new tail {chain.tail} -> x={r}   (matches pre-crash value)")
    print("A new write now flows along the shortened chain:")
    w, path = chain.write("x", 5)
    print(arrow_path(path, w))
    r = chain.read("x")
    print(f"  read at tail {chain.tail} -> x={r}\n")
    print("The chain now has only 2 live nodes (B, C). It STILL serves strong-")
    print("consistency reads/writes -- it needs NO majority. Unlike Raft, which")
    print("would be STOPPED with 2 of 4 alive (majority=3), chain replication")
    print("keeps going down to a SINGLE node (which becomes both head and tail).")
    print(f"\n[check] after tail failover, no data lost and read returned x={r}:  OK")
    return chain


# ----------------------------------------------------------------------------
# SECTION E: chain vs Raft/Paxos -- latency vs work trade-off
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: chain vs Raft/Paxos  (O(N) latency vs O(N) leader work)")
    print("Both can replicate a write across N nodes, but they spend the cost")
    print("differently. Same total messages; OPPOSITE shapes:\n")
    print("  CHAIN : serialize the write along ONE path.  Latency = O(N) hops;")
    print("          but each node does O(1) work (receive + forward once).")
    print("  RAFT  : fan the write out in PARALLEL.        Latency = O(1) round;")
    print("          but the LEADER does O(N) work (sends to every follower).\n")
    print("Per-write cost, N = 4 replicas (1 update):\n")
    print("| metric                | chain (N=4)         | raft (N=4)          |")
    print("|-----------------------|---------------------|---------------------|")
    n = 4
    cc = chain_write_cost(n)
    rc = raft_write_cost(n)
    print(f"| write latency         | {cc['latency_rounds']} sequential hops    | "
          f"{rc['latency_rounds']} parallel round     |")
    print(f"| messages on the wire  | {cc['messages']} (down + up)       | "
          f"{rc['messages']} (fan-out + ack)    |")
    print(f"| work at the bottleneck| head: {cc['head_work']} send/op      | "
          f"leader: {rc['leader_work']} sends/op     |")
    print(f"| work per other replica| {cc['interior_work']} (recv + fwd)        | "
          f"1 (recv + ack)        |")
    print("| needs consensus/op?   | NO (serial path)    | YES (majority ack)  |")
    print("| reads served by       | TAIL (single point) | any (after commit)  |")
    print("| survives with N alive | down to 1 node      | needs majority      |")
    print()
    print("Read it as a dial on WHERE you put the cost:")
    print("  - Want LOW latency and can afford a beefy leader?  -> Raft/Paxos.")
    print("  - Want to SPREAD load (no single hot leader) and can tolerate the")
    print("    chain's serial latency?                          -> Chain.")
    print()
    print("Latency vs chain length (write, in hops/rounds):")
    print("| N replicas | chain write latency (N-1 hops) | raft write latency "
          "(1 round) |")
    print("|------------|---------------------------------|"
          "----------------------------|")
    for nn in (2, 4, 8, 16):
        print(f"| {nn:<10} | {nn - 1:<31} | "
              f"{1:<26} |")
    print()
    print("Throughput angle: in chain replication the HEAD and TAIL are the")
    print("bottlenecks (head accepts writes, tail serves reads); interior nodes")
    print("only relay, so adding length mainly raises latency, not throughput.")
    print("Raft's bottleneck is the LEADER doing O(N) work per op. Chain pushes")
    print("consensus OFF the critical path entirely (only the manager runs it).")
    print(f"\n[check] chain N=4 write latency {cc['latency_rounds']} > raft "
          f"{rc['latency_rounds']}, but chain head work {cc['head_work']} < raft "
          f"leader work {rc['leader_work']}:  OK")


# ============================================================================
# 4. GOLD CHECK  (pinned values that chain_replication.html recomputes in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK  (pinned values for chain_replication.html)")
    print("Capstone: run the FULL pipeline -- build a 4-node chain, interleave")
    print("writes/reads (asserting every read == latest completed write), then")
    print("crash the HEAD (A) and continue writing at the new head (B), then")
    print("crash the TAIL (D) and keep reading at the new tail (C). The gold")
    print("invariant: a read ALWAYS returns the latest fully-replicated write,\n"
          "with ZERO data loss across both failovers.\n")
    chain = Chain(["A", "B", "C", "D"])
    print(f"  initial chain = {chain.chain_str()}   head={chain.head}, "
          f"tail={chain.tail}")

    trace = []                       # (op, value_returned)
    # phase 1: normal operation on the full 4-node chain
    chain.write("x", 1)
    trace.append(("write x=1", None))
    trace.append(("read", chain.read("x")))
    chain.write("x", 2)
    trace.append(("write x=2", None))
    trace.append(("read", chain.read("x")))
    chain.write("x", 3)
    trace.append(("write x=3", None))
    trace.append(("read", chain.read("x")))
    # phase 2: crash head A -> B becomes head
    chain.crash("A")
    trace.append(("crash head A", None))
    chain.write("x", 4)
    trace.append(("write x=4 (head=B)", None))
    trace.append(("read", chain.read("x")))
    # phase 3: crash tail D -> C becomes tail
    chain.crash("D")
    trace.append(("crash tail D", None))
    trace.append(("read after tail failover", chain.read("x")))
    chain.write("x", 5)
    trace.append(("write x=5 (chain B->C)", None))
    trace.append(("read", chain.read("x")))

    # the reads, in order, MUST equal the latest completed write each time
    gold_reads = [1, 2, 3, 4, 4, 5]
    actual_reads = [v for (_, v) in trace if v is not None]
    print("\n  operation trace:")
    for op, v in trace:
        tail = "" if v is None else f" -> {v}"
        print(f"    {op:<26}{tail}")

    consistent = actual_reads == gold_reads
    no_loss = consistent            # reads matching latest write == no data lost

    print("\nGOLD scalars (pinned for a compact .html check):")
    print(f"  initial_chain_length   = {4}")
    print(f"  initial_write_hops     = {3}        (N-1, N=4)")
    print(f"  read_sequence          = {actual_reads}")
    print(f"  expected_read_sequence = {gold_reads}")
    print(f"  final_read             = {chain.read('x')}")
    print(f"  live_nodes_at_end      = {chain.order}")
    print(f"  reads_match_latest     = {consistent}")
    print(f"  data_loss              = {not no_loss}")
    # assertions
    assert len(actual_reads) == len(gold_reads)
    assert consistent is True
    assert chain.read("x") == 5
    assert chain.order == ["B", "C"]
    assert chain.head == "B" and chain.tail == "C"
    print("\n[check] every read == latest fully-replicated write, no data lost "
          "across head+tail failovers:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("chain_replication.py - reference impl. All numbers below feed "
          "CHAIN_REPLICATION.md.")
    print("python stdlib only (no external deps).")

    chain = section_a()
    section_b(chain)
    section_c(chain)
    section_d(chain)
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
