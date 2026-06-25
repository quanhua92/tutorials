"""
logical_vs_physical.py - Reference implementation of PostgreSQL Physical vs
Logical replication, and why they are NOT two flavors of the same thing.

This is the single source of truth that LOGICAL_VS_PHYSICAL.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 logical_vs_physical.py

============================================================================
THE INTUITION (read this first) - the photocopy vs the dictation
============================================================================
You run a warehouse (the PRIMARY). Every sale is written into a notebook (the
WAL - Write-Ahead Log) the instant it happens. Now you open a SECOND warehouse
(the STANDBY) across town and want it to mirror the first. Two ways to keep it
in sync:

  * PHYSICAL replication : you tear out each notebook page and FAX it over,
                           raw. The second warehouse pastes the page into its
                           OWN notebook, byte-for-byte. Identical handwriting,
                           identical ink, identical page numbers. But the two
                           warehouses MUST use the exact same notebook format
                           (same PG major version, same CPU architecture) or
                           the faxed page does not fit.

  * LOGICAL replication   : you read each notebook entry aloud over the phone
                           as a SENTENCE - "insert user Ada", "delete order
                           10", "update order 11 to amount 120". The second
                           warehouse writes it down in ITS OWN notebook format.
                           It can be a newer edition (cross-version), a
                           different language (cross-platform), or only care
                           about some shelves (selective/table-filtered).

THE REASON BOTH EXIST: physical is dumb, fast, and exact - but brittle (one
bit of format drift and the standby is corrupt). Logical is smart, flexible,
and schema-aware - but it must DECODE every raw WAL record into a logical
change (INSERT/UPDATE/DELETE on a named table), which costs CPU and loses
everything that is not a row change (DDL, sequences, large objects).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   WAL                 : Write-Ahead Log. The append-only, fsync'd byte stream
                          of every modification. The source of truth on disk.
                          🔗 Built and checkpointed in WAL_CHECKPOINT.md.
   LSN                 : Log Sequence Number. Monotonic id of a WAL record.
   record / RM_HEAP    : a WAL record produced by the heap resource manager.
                          Carries enough bytes to redo a page modification.
   physical streaming  : the primary ships raw WAL records; the standby parses
                          the bytes and writes them to its own heap pages.
   page layout         : the on-disk binary format of a heap/index page.
                          Physical replication REQUIRES identical layout on
                          both ends (same major version + architecture).
   logical decoding    : reading the WAL stream and turning raw records into
                          logical change records (table + op + old/new values).
                          Implemented by an OUTPUT PLUGIN (pgoutput is the
                          built-in one; test_decoding is the debugging one).
   output plugin       : the decoder. pgoutput emits a binary protocol of
                          relation-mapping + INSERT/UPDATE/DELETE messages.
   logical change      : { table, op(INSERT/UPDATE/DELETE), old_key, new_row }.
   publication         : a named set of tables (PG 15+: with optional column
                          and row filters) whose changes a publisher OFFERS.
   subscription        : a receiver-side object that connects to a publisher's
                          publication and applies the change stream locally.
   REPLICA IDENTITY    : how much of the OLD row is logged for UPDATE/DELETE so
                          logical decoding can emit the "old" values. Default
                          = PK (only the primary key). FULL = whole row.
   conflict            : on a logical subscriber, an incoming change cannot be
                          applied (e.g. INSERT of a row that already exists, or
                          DELETE of a row that is absent, or an FK violation).

============================================================================
THE LINEAGE (papers + docs)
============================================================================
   Physical streaming   PostgreSQL streaming replication, introduced 9.0 (2010).
                        src/backend/replication/walreceiver.c, walsender.c;
                        docs §27.2 "Log-Shipping Standby Servers", §27.3
                        "Streaming Replication".
   Logical decoding     PostgreSQL 9.4 (2015) added the logical decoding
                        interface; 10.0 (2017) added native logical replication
                        (PUBLICATION/SUBSCRIPTION). docs Ch.31 "Logical
                        Replication". src/backend/replication/logical/.
   pgoutput             the built-in output plugin (PG 10+). Emits the binary
                        "protocol" logical replication format.
   test_decoding        the contrib debugging output plugin (human readable).
   pglogical / Bucardo  third-party logical replication predating native
                        pub/sub; still used for advanced topologies.

KEY RULES (all asserted/printed in the sections below):
   physical fidelity    : standby heap bytes == primary heap bytes (byte-identical
                          pages). Requires same major version + architecture.
   physical constraint  : physical replication CANNOT cross a major-version
                          boundary (page format may change). Cannot cross
                          architecture (endianness / pointer width).
   logical fidelity     : subscriber visible ROWS == primary visible ROWS, but
                          byte layout may differ (different XIDs, offsets,
                          free-space). Only the logical content is preserved.
   logical decoding     : every row-change record can be decoded; non-row
                          changes (DDL, sequences, large objects, sequences)
                          CANNOT be decoded and are silently dropped.
   publication filter   : only changes on tables IN the publication, passing
                          the column + row filter, are sent to subscribers.
   conflict default     : on conflict the subscription STOPS (ERROR) until a
                          human fixes it. PG 17+ adds SKIPPING via a resolver.
   GOLD equivalence     : logical_decoded_state == physical_replayed_state for
                          every table the publication covers. Proven in Sec. G.

Conventions:
   LSNs are small deterministic integers (1..N).
   Two tables: users(id,name,email), orders(id,user_id,amount). relfilenodes
   16384 (users) and 16390 (orders). Ints are 8-byte big-endian; strings are
   length-prefixed UTF-8. WAL records are printed oldest -> newest.
"""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass

BANNER = "=" * 72

# ============================================================================
# 1. THE CATALOG + BINARY ENCODING  (what both the physical record format and
#    the logical output plugin agree on)
# ============================================================================

# relation OID -> schema. Present on BOTH ends (physical standby inherits the
# same cluster; logical subscriber must CREATE the tables to match).
CATALOG: dict[int, dict] = {
    16384: {"table": "users",  "columns": ["id", "name", "email"],     "pk": "id"},
    16390: {"table": "orders", "columns": ["id", "user_id", "amount"], "pk": "id"},
}
TABLE_TO_REL = {v["table"]: k for k, v in CATALOG.items()}

# resource manager + info codes (mirrors src/include/catalog/pg_rewrite.h +
# src/backend/access/heap/heapam.c XLOG_HEAP_* constants, simplified)
RM_XACT = 1     # transaction manager (COMMIT records)
RM_HEAP = 10    # heap
INFO_INSERT, INFO_UPDATE, INFO_DELETE, INFO_COMMIT = 0x00, 0x10, 0x20, 0x90
OP_NAME = {INFO_INSERT: "INSERT", INFO_UPDATE: "UPDATE",
           INFO_DELETE: "DELETE", INFO_COMMIT: "COMMIT"}
INFO_BY_OP = {v: k for k, v in OP_NAME.items()}

# WAL record header = rm(1) info(1) xid(4) relfilenode(4) lsn(4) = 14 bytes
HDR = ">BBIII"
# heap tuple location inside a record = block(4) offset(2) = 6 bytes
LOC = ">IH"


def encode_value(v) -> bytes:
    """Deterministic binary encoding of one column value (tag byte + payload)."""
    if isinstance(v, bool):
        return b"b" + struct.pack(">?", v)
    if isinstance(v, int):
        return b"i" + struct.pack(">q", v)
    if isinstance(v, float):
        return b"f" + struct.pack(">d", v)
    b = str(v).encode("utf-8")
    return b"s" + struct.pack(">H", len(b)) + b


def _decode_value(buf: bytes, i: int):
    tag = buf[i:i + 1]
    i += 1
    if tag == b"i":
        v = struct.unpack(">q", buf[i:i + 8])[0]
        i += 8
    elif tag == b"f":
        v = struct.unpack(">d", buf[i:i + 8])[0]
        i += 8
    elif tag == b"s":
        n = struct.unpack(">H", buf[i:i + 2])[0]
        i += 2
        v = buf[i:i + n].decode("utf-8")
        i += n
    elif tag == b"b":
        v = struct.unpack(">?", buf[i:i + 1])[0]
        i += 1
    else:
        raise ValueError(f"bad value tag {tag!r}")
    return v, i


def encode_tuple(table: str, row: dict) -> bytes:
    """Pack a row (or a key subset) into a SELF-DELIMITING tuple byte image.

    A full INSERT/UPDATE row carries every catalog column; an UPDATE/DELETE
    *old* tuple carries only the REPLICA IDENTITY columns (default = PK). So a
    tuple is encoded as: 1-byte column count, then for each present column a
    1-byte index into the catalog column list + the tagged value. This lets two
    tuples concatenate and still split back out (decode_tuple consumes exactly
    its own bytes)."""
    cols_all = CATALOG[TABLE_TO_REL[table]]["columns"]
    idx = {c: k for k, c in enumerate(cols_all)}
    present = [c for c in cols_all if c in row]
    out = bytearray([len(present)])
    for c in present:
        out.append(idx[c])
        out += encode_value(row[c])
    return bytes(out)


def decode_tuple(table: str, buf: bytes, i: int = 0) -> tuple[dict, int]:
    """Inverse of encode_tuple. Returns (row, next_index). The output plugin
    uses this to recover a logical row (or key) from the raw tuple bytes."""
    cols_all = CATALOG[TABLE_TO_REL[table]]["columns"]
    n = buf[i]
    i += 1
    row: dict = {}
    for _ in range(n):
        name = cols_all[buf[i]]
        i += 1
        v, i = _decode_value(buf, i)
        row[name] = v
    return row, i


# ============================================================================
# 2. THE WAL RECORD + PHYSICAL BYTE ENCODING
#    A WalRecord is the logical unit of work; encode_physical() turns it into
#    the raw bytes a physical standby consumes verbatim.
# ============================================================================

@dataclass
class WalRecord:
    lsn: int
    xid: int
    op: str                       # INSERT / UPDATE / DELETE / COMMIT
    table: str | None = None
    old: dict | None = None       # old key (REPLICA IDENTITY) for UPDATE/DELETE
    new: dict | None = None       # new full row for INSERT/UPDATE
    block: int = 0                # assigned by the primary heap manager
    offset: int = 0

    @property
    def relfilenode(self) -> int:
        return TABLE_TO_REL[self.table] if self.table else 0


def encode_physical(r: WalRecord) -> bytes:
    """Serialize a record into the byte image a physical standby ships/applies.

    Layout (deterministic, mirrors a real RM_HEAP record, simplified):
        header[14]  : rm info xid relfilenode lsn
        loc[6]      : block offset             (absent for COMMIT)
        paylen[2]   : length of the PAGE PAYLOAD (the bytes written to the heap)
        payload     : the new tuple image (INSERT/UPDATE) -- exactly what the
                      standby pastes onto the page at (block, offset)
        old_key?    : trailing replica-identity key (UPDATE/DELETE). The physical
                      standby IGNORES this; only the output plugin reads it, so
                      it can emit the "old" values for logical replication.
    Splitting the new-image (page payload) from the old-key (logical metadata)
    is what lets the standby stay a dumb byte-paster while logical decoding
    still recovers both halves.
    """
    rm = RM_XACT if r.op == "COMMIT" else RM_HEAP
    info = INFO_BY_OP[r.op]
    header = struct.pack(HDR, rm, info, r.xid, r.relfilenode, r.lsn)
    if r.op == "COMMIT":
        return header
    loc = struct.pack(LOC, r.block, r.offset)
    if r.op == "INSERT":
        pay = encode_tuple(r.table, r.new)
        return header + loc + struct.pack(">H", len(pay)) + pay
    if r.op == "UPDATE":
        pay = encode_tuple(r.table, r.new)          # written to the page
        oldk = encode_tuple(r.table, r.old)         # replica identity (metadata)
        return header + loc + struct.pack(">H", len(pay)) + pay + oldk
    if r.op == "DELETE":
        oldk = encode_tuple(r.table, r.old)
        return header + loc + struct.pack(">H", 0) + oldk
    raise ValueError(r.op)


# ============================================================================
# 3. THE STORES
# ============================================================================

class Heap:
    """The on-disk heap: relfilenode -> {block: {offset: tuple_bytes}}.
    A physical standby reproduces this BYTE-FOR-IDENTICAL-BYTE."""

    def __init__(self):
        self.pages: dict[int, dict[int, dict[int, bytes]]] = {}
        self.next_off: dict[int, int] = {}
        self.pk_loc: dict[int, dict] = {}      # rel -> {pk_value: (block, offset)}

    def insert(self, rel, pk, tb) -> tuple[int, int]:
        off = self.next_off.get(rel, 1)
        self.next_off[rel] = off + 1
        self.pages.setdefault(rel, {}).setdefault(0, {})[off] = tb
        self.pk_loc.setdefault(rel, {})[pk] = (0, off)
        return 0, off

    def update(self, rel, pk, tb) -> tuple[int, int]:
        block, off = self.pk_loc[rel][pk]
        self.pages[rel][block][off] = tb
        return block, off

    def delete(self, rel, pk) -> tuple[int, int]:
        block, off = self.pk_loc[rel].pop(pk)
        del self.pages[rel][block][off]
        return block, off

    def byte_fingerprint(self) -> str:
        """SHA-256 over the sorted (rel, block, offset, bytes) of every live
        slot. Two byte-identical heaps share this fingerprint."""
        items = []
        for rel in sorted(self.pages):
            for block in sorted(self.pages[rel]):
                for off in sorted(self.pages[rel][block]):
                    items.append((rel, block, off, self.pages[rel][block][off]))
        return hashlib.sha256(repr(items).encode()).hexdigest()[:16]


class LogicalStore:
    """The subscriber's logical view: table -> {pk: row}. Built by applying the
    decoded change records an output plugin (pgoutput) emits."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def apply(self, table: str, op: str, change: dict):
        pk_col = CATALOG[TABLE_TO_REL[table]]["pk"]
        store = self.rows.setdefault(table, {})
        if op == "INSERT":
            pk = change["new"][pk_col]
            if pk in store:
                raise ConflictError("duplicate key", table, pk, store[pk])
            store[pk] = dict(change["new"])
        elif op == "UPDATE":
            pk = change["new"][pk_col]
            if pk not in store:
                raise ConflictError("missing row for UPDATE", table, pk, None)
            store[pk] = dict(change["new"])
        elif op == "DELETE":
            pk = change["old"][pk_col]
            if pk not in store:
                raise ConflictError("missing row for DELETE", table, pk, None)
            del store[pk]

    def view(self, table: str) -> list[dict]:
        return list(self.rows.get(table, {}).values())


class ConflictError(Exception):
    def __init__(self, kind, table, pk, existing):
        self.kind, self.table, self.pk, self.existing = kind, table, pk, existing
        super().__init__(f"{kind} on {table} pk={pk}")


# ============================================================================
# 4. THE PRIMARY EXECUTOR + THE OUTPUT PLUGIN (LOGICAL DECODER)
# ============================================================================

def run_primary(heap: Heap, workload: list[dict]) -> list[WalRecord]:
    """Execute the workload on the primary, mutating its heap, and emit the
    WAL record stream (the single source both replicas consume)."""
    wal: list[WalRecord] = []
    for step in workload:
        op = step["op"]
        if op == "COMMIT":
            wal.append(WalRecord(lsn=step["lsn"], xid=step["xid"], op="COMMIT"))
            continue
        table = step["table"]
        rel = TABLE_TO_REL[table]
        pk_col = CATALOG[rel]["pk"]
        if op == "INSERT":
            pk = step["new"][pk_col]
            block, off = heap.insert(rel, pk, encode_tuple(table, step["new"]))
        elif op == "UPDATE":
            pk = step["new"][pk_col]
            block, off = heap.update(rel, pk, encode_tuple(table, step["new"]))
        elif op == "DELETE":
            pk = step["old"][pk_col]
            block, off = heap.delete(rel, pk)
        else:
            raise ValueError(op)
        wal.append(WalRecord(lsn=step["lsn"], xid=step["xid"], op=op, table=table,
                             old=step.get("old"), new=step.get("new"),
                             block=block, offset=off))
    return wal


def apply_physical(heap: Heap, record_bytes: list[bytes]):
    """The physical standby: parse each raw record's bytes and write the PAGE
    PAYLOAD to its own heap. It NEVER interprets SQL, never decodes the old
    replica-identity key - it pastes exactly the new-image bytes at
    (relfilenode, block, offset)."""
    for b in record_bytes:
        rm, info, xid, rel, lsn = struct.unpack(HDR, b[:14])
        if info == INFO_COMMIT:
            continue
        block, off = struct.unpack(LOC, b[14:20])
        slots = heap.pages.setdefault(rel, {}).setdefault(block, {})
        if info == INFO_INSERT or info == INFO_UPDATE:
            paylen = struct.unpack(">H", b[20:22])[0]
            slots[off] = b[22:22 + paylen]          # exactly the page payload
        elif info == INFO_DELETE:
            slots.pop(off, None)


def decode_logical(b: bytes, catalog: dict = CATALOG) -> dict:
    """The OUTPUT PLUGIN (pgoutput). Reads a raw WAL record's bytes, consults
    the catalog, and emits a logical change record. THIS is the 'decoding'
    that physical replication never does."""
    rm, info, xid, rel, lsn = struct.unpack(HDR, b[:14])
    if info == INFO_COMMIT:
        return {"lsn": lsn, "xid": xid, "op": "COMMIT"}
    meta = catalog[rel]
    table, op = meta["table"], OP_NAME[info]
    paylen = struct.unpack(">H", b[20:22])[0]
    payload = b[22:22 + paylen]                       # the new-image (page payload)
    tail = b[22 + paylen:]                            # trailing old-key (metadata)
    if op == "INSERT":
        new, _ = decode_tuple(table, payload)
        return {"lsn": lsn, "xid": xid, "table": table, "op": "INSERT", "new": new}
    if op == "UPDATE":
        new, _ = decode_tuple(table, payload)
        old, _ = decode_tuple(table, tail)
        return {"lsn": lsn, "xid": xid, "table": table, "op": "UPDATE",
                "old": old, "new": new}
    if op == "DELETE":
        old, _ = decode_tuple(table, tail)
        return {"lsn": lsn, "xid": xid, "table": table, "op": "DELETE", "old": old}
    raise ValueError(info)


def apply_logical(store: LogicalStore, change: dict):
    if change["op"] == "COMMIT":
        return
    store.apply(change["table"], change["op"], change)


def heap_view(heap: Heap, table: str) -> list[dict]:
    """Decode a physical heap's live slots back into logical rows (the visible
    table state). Used by the GOLD check to compare physical vs logical ends."""
    rel = TABLE_TO_REL[table]
    pk = CATALOG[rel]["pk"]
    rows = []
    for block in sorted(heap.pages.get(rel, {})):
        for off in sorted(heap.pages[rel][block]):
            rows.append(decode_tuple(table, heap.pages[rel][block][off])[0])
    rows.sort(key=lambda r: r[pk])
    return rows


def state_fingerprint(tables_state: dict[str, list[dict]]) -> tuple[str, str]:
    """Canonical string + short hash of a multi-table visible state. Identical
    layout in JS so logical_vs_physical.html can recompute and gold-check it."""
    parts = []
    for table in sorted(tables_state):
        cols = CATALOG[TABLE_TO_REL[table]]["columns"]
        pk = CATALOG[TABLE_TO_REL[table]]["pk"]
        rows = sorted(tables_state[table], key=lambda r: r[pk])
        row_strs = ["[" + ",".join(json.dumps(r[c]) for c in cols) + "]"
                    for r in rows]
        parts.append(f"{table}:[{','.join(row_strs)}]")
    canon = "|".join(parts)
    return hashlib.sha256(canon.encode()).hexdigest()[:16], canon


# ============================================================================
# 5. PUBLICATION / SUBSCRIPTION MODEL
# ============================================================================

@dataclass
class Publication:
    name: str
    tables: list[str]
    # PG 15+ filters (optional):
    column_filter: dict[str, list[str]] | None = None   # table -> columns to send
    row_filter: dict[str, str] | None = None            # table -> WHERE expr


@dataclass
class Subscription:
    name: str
    publisher_node: str
    publication: str


def publish_filter(pub: Publication, change: dict) -> dict | None:
    """Return the (possibly filtered) change a publication emits for `change`,
    or None if the publication does not carry that table / row.

    Mirrors CREATE PUBLICATION ... FOR TABLE t (col,col) WHERE (...)."""
    table = change.get("table")
    if table not in pub.tables:
        return None
    out = dict(change)
    if pub.column_filter and table in pub.column_filter:
        keep = set(pub.column_filter[table])
        for side in ("new", "old"):
            if side in out and out[side] is not None:
                out[side] = {c: v for c, v in out[side].items() if c in keep}
    if pub.row_filter and table in pub.row_filter:
        # toy evaluator: row_filter looks like "amount>100"; evaluate against new
        if not _eval_row_filter(pub.row_filter[table], out.get("new")):
            return None
    return out


def _eval_row_filter(expr: str, row: dict | None) -> bool:
    if row is None:
        return True
    import operator
    import re
    m = re.fullmatch(r"\s*(\w+)\s*(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)\s*", expr)
    if not m:
        return True
    col, op, num = m.group(1), m.group(2), float(m.group(3))
    ops = {">=": operator.ge, "<=": operator.le, ">": operator.gt,
           "<": operator.lt, "=": operator.eq}
    val = row.get(col)
    if val is None:
        return False
    return ops[op](float(val), num)


# ============================================================================
# 6. THE DETERMINISTIC WORKLOAD
#    Tiny enough to print every record, exercises INSERT/UPDATE/DELETE on two
#    tables plus COMMIT markers. Identical inputs in logical_vs_physical.html.
# ============================================================================

WORKLOAD: list[dict] = [
    {"lsn": 1,  "xid": 1001, "op": "INSERT", "table": "users",
     "new": {"id": 1, "name": "Ada",   "email": "ada@x.io"}},
    {"lsn": 2,  "xid": 1001, "op": "INSERT", "table": "users",
     "new": {"id": 2, "name": "Alan",  "email": "alan@x.io"}},
    {"lsn": 3,  "xid": 1001, "op": "INSERT", "table": "users",
     "new": {"id": 3, "name": "Grace", "email": "grace@x.io"}},
    {"lsn": 4,  "xid": 1002, "op": "INSERT", "table": "orders",
     "new": {"id": 10, "user_id": 1, "amount": 99}},
    {"lsn": 5,  "xid": 1002, "op": "INSERT", "table": "orders",
     "new": {"id": 11, "user_id": 2, "amount": 50}},
    {"lsn": 6,  "xid": 1003, "op": "UPDATE", "table": "users",
     "old": {"id": 2}, "new": {"id": 2, "name": "Alan T", "email": "alan@x.io"}},
    {"lsn": 7,  "xid": 1004, "op": "INSERT", "table": "orders",
     "new": {"id": 12, "user_id": 3, "amount": 250}},
    {"lsn": 8,  "xid": 1005, "op": "DELETE", "table": "users",
     "old": {"id": 1}},
    {"lsn": 9,  "xid": 1002, "op": "UPDATE", "table": "orders",
     "old": {"id": 10}, "new": {"id": 10, "user_id": 1, "amount": 120}},
    {"lsn": 10, "xid": 1001, "op": "COMMIT"},
    {"lsn": 11, "xid": 1002, "op": "COMMIT"},
    {"lsn": 12, "xid": 1003, "op": "COMMIT"},
    {"lsn": 13, "xid": 1004, "op": "COMMIT"},
    {"lsn": 14, "xid": 1005, "op": "COMMIT"},
]


# ============================================================================
# 7. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def hexdump(b: bytes, width = 16) -> str:
    out = []
    for i in range(0, len(b), width):
        chunk = b[i:i + width]
        hexs = " ".join(f"{x:02x}" for x in chunk)
        asc = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
        out.append(f"  {i:04x}  {hexs:<{width * 3}}  {asc}")
    return "\n".join(out)


def fmt_row(row: dict | None, table: str) -> str:
    if row is None:
        return "-"
    cols = CATALOG[TABLE_TO_REL[table]]["columns"]
    present = [c for c in cols if c in row]       # old keys are PK-only
    return "{" + ", ".join(f"{c}={row[c]!r}" for c in present) + "}"


# ============================================================================
# SECTION A: PHYSICAL REPLICATION - raw WAL byte stream, byte-for-byte apply
# ============================================================================

def section_a():
    banner("SECTION A: PHYSICAL replication - ship raw WAL bytes, apply verbatim")
    primary = Heap()
    wal = run_primary(primary, WORKLOAD)

    print("The primary executes the workload and emits a WAL record per change.")
    print("Physical replication streams the RAW BYTES of each record; the standby")
    print("writes them to the same (relfilenode, block, offset). It never reads")
    print("the catalog, never parses SQL - it pastes bytes.\n")

    print("First two non-commit records as raw bytes (what crosses the wire):\n")
    shown = 0
    for r in wal:
        if r.op == "COMMIT":
            continue
        b = encode_physical(r)
        print(f"  LSN {r.lsn:>2}  xid {r.xid}  {r.op:<6} {r.table:<6} "
              f"-> rel {r.relfilenode} block {r.block} offset {r.offset}  "
              f"({len(b)} bytes)")
        print(hexdump(b))
        print()
        shown += 1
        if shown >= 2:
            break

    # byte-level fidelity check
    standby = Heap()
    apply_physical(standby, [encode_physical(r) for r in wal])
    fp_primary = primary.byte_fingerprint()
    fp_standby = standby.byte_fingerprint()
    print("Byte-level fidelity (SHA-256 of every live heap slot):")
    print(f"  primary  heap fingerprint = {fp_primary}")
    print(f"  standby  heap fingerprint = {fp_standby}")
    ok = fp_primary == fp_standby
    print(f"  [check] byte-identical heaps? {ok}")
    assert ok, "physical standby must be byte-identical to primary"

    print("\nTHE CONSTRAINT - physical replication is brittle by construction:")
    print("  - same PG MAJOR version  (page layout, pg_control format must match)")
    print("  - same CPU ARCHITECTURE  (endianness, pointer width, alignment)")
    print("  - a single bit of format drift -> corrupt standby, no warning")
    compat = [
        ("PG 14 -> PG 14", "x86_64 -> x86_64", True),
        ("PG 14 -> PG 14", "x86_64 -> ARM64",  False),
        ("PG 14 -> PG 16", "x86_64 -> x86_64", False),
        ("PG 16 -> PG 16", "ARM64  -> ARM64",  True),
    ]
    print("\n  | publisher         | standby           | physical OK? |")
    print("  |-------------------|-------------------|--------------|")
    for pub, stand, okp in compat:
        print(f"  | {pub:<17} | {stand:<17} | "
              f"{'YES' if okp else 'NO (format drift)':<12} |")
    print("\n  Cross-version / cross-arch is IMPOSSIBLE over physical. That gap is")
    print("  exactly what logical replication (Section B) fills.")


# ============================================================================
# SECTION B: LOGICAL REPLICATION - WAL -> output plugin -> change records
# ============================================================================

def section_b():
    banner("SECTION B: LOGICAL replication - decode WAL into change records")
    primary = Heap()
    wal = run_primary(primary, WORKLOAD)

    print("The SAME WAL records, but now the output plugin (pgoutput) DECODES each")
    print("one into a logical change record: {table, op, old, new}. The subscriber")
    print("applies these as if it had run the SQL itself.\n")

    print("  | LSN | xid  | op     | table  | old            | new                    |")
    print("  |-----|------|--------|--------|----------------|------------------------|")
    for r in wal:
        b = encode_physical(r)
        ch = decode_logical(b)
        if ch["op"] == "COMMIT":
            print(f"  | {ch['lsn']:<3} | {ch['xid']:<4} | COMMIT | -      | -              | -                      |")
            continue
        old = fmt_row(ch.get("old"), ch["table"]) if ch["op"] in ("UPDATE", "DELETE") else "-"
        new = fmt_row(ch.get("new"), ch["table"]) if ch["op"] in ("INSERT", "UPDATE") else "-"
        print(f"  | {ch['lsn']:<3} | {ch['xid']:<4} | {ch['op']:<6} | {ch['table']:<6} | "
              f"{old:<14} | {new:<22} |")

    print("\nWhat the subscriber reconstructs (applying decoded changes):")
    sub = LogicalStore()
    for r in wal:
        apply_logical(sub, decode_logical(encode_physical(r)))
    for t in ("users", "orders"):
        print(f"\n  SELECT * FROM {t} ORDER BY pk;")
        for row in sorted(sub.view(t), key=lambda r: r[CATALOG[TABLE_TO_REL[t]]["pk"]]):
            print(f"    {fmt_row(row, t)}")

    print("\nKEY CONTRAST vs Section A:")
    print("  physical : consumer = a byte-paster. Needs identical page format.")
    print("  logical  : consumer = a SQL executor. Needs matching SCHEMA (column")
    print("             names/types), NOT matching byte layout. So PG 14 -> PG 16,")
    print("             x86 -> ARM, even PG -> a non-PG sink, all work.")


# ============================================================================
# SECTION C: PUBLICATION / SUBSCRIPTION model
# ============================================================================

def section_c():
    banner("SECTION C: PUBLICATION / SUBSCRIPTION - the logical topology")
    print("Logical replication is a pub/sub system layered on logical decoding:\n")
    print("  -- on the PUBLISHER (the source DB)")
    print("  CREATE PUBLICATION pub_all    FOR TABLE users, orders;")
    print("  CREATE PUBLICATION pub_users  FOR TABLE users;")
    print("  -- PG 15+: column + row filters")
    print("  CREATE PUBLICATION pub_big   FOR TABLE orders (id, amount) WHERE (amount > 100);\n")
    print("  -- on the SUBSCRIBER (the target DB)")
    print("  CREATE SUBSCRIPTION sub_all CONNECTION 'host=publisher dbname=shop'")
    print("                              PUBLICATION pub_all;\n")

    pubs = [
        Publication("pub_all",   ["users", "orders"]),
        Publication("pub_users", ["users"]),
        Publication("pub_big",   ["orders"],
                    column_filter={"orders": ["id", "amount"]},
                    row_filter={"orders": "amount > 100"}),
    ]
    subs = [
        Subscription("sub_all",   "publisher", "pub_all"),
        Subscription("sub_users", "publisher", "pub_users"),
        Subscription("sub_big",   "publisher", "pub_big"),
    ]

    primary = Heap()
    wal = run_primary(primary, WORKLOAD)
    changes = [decode_logical(encode_physical(r)) for r in wal
               if r.op != "COMMIT"]

    print("Topology (3 publications, 3 subscribers) and which of the "
          f"{len(changes)} row-changes each subscriber receives:\n")
    print("  | subscription | publication | carries tables      | # changes shipped |")
    print("  |--------------|-------------|---------------------|-------------------|")
    for s in subs:
        pub = next(p for p in pubs if p.name == s.publication)
        shipped = [c for c in changes if publish_filter(pub, c) is not None]
        print(f"  | {s.name:<12} | {pub.name:<11} | {','.join(pub.tables):<19} | "
              f"{len(shipped):<17} |")

    print("\nWorked filter demo - pub_big (orders, cols [id,amount], WHERE amount>100):")
    pub = pubs[2]
    for c in changes:
        if c["table"] != "orders":
            continue
        out = publish_filter(pub, c)
        tag = "SHIP " if out is not None else "DROP "
        detail = fmt_row(c.get("new"), "orders")
        if out is not None and out.get("new") != c.get("new"):
            detail += f"  -> columns filtered to {fmt_row(out['new'], 'orders')}"
        print(f"  {tag} LSN {c['lsn']:<2} {c['op']:<6} {detail}")
    print("\n  -> only order id=12 (amount 250 > 100) ships, and with the user_id")
    print("     column stripped. SELECTIVE replication is impossible over physical.")


# ============================================================================
# SECTION D: USE-CASE DECISION MATRIX
# ============================================================================

def section_d():
    banner("SECTION D: DECISION MATRIX - when to pick which")
    print("Pick by WHAT you need the replica for, not by preference.\n")
    rows = [
        ("byte-identical standby",        "YES", "no  (rows match, bytes differ)", "physical"),
        ("cross-major-version upgrade",   "no (format drift)",  "YES", "logical"),
        ("cross-architecture (x86->ARM)", "no",  "YES", "logical"),
        ("hot standby / read replica",    "YES", "YES (read-only)", "either"),
        ("PITR / point-in-time recovery", "YES (archive WAL)",  "no (row stream)",  "physical"),
        ("selective table replication",   "no (whole cluster)", "YES", "logical"),
        ("column / row filtering",        "no",  "YES (PG 15+)", "logical"),
        ("multi-master / bidirectional",  "no (single writer)", "YES (with care)", "logical"),
        ("data federation / fan-out",     "no",  "YES (1 -> N)", "logical"),
        ("change data capture (CDC)",     "no",  "YES",          "logical"),
        ("zero-downtime major upgrade",   "no",  "YES (pg_upgrade --link + logical cutover)", "logical"),
    ]
    print("  | need                                | physical        | logical                | pick    |")
    print("  |-------------------------------------|-----------------|------------------------|---------|")
    for need, p, logi, pick in rows:
        print(f"  | {need:<35} | {p:<15} | {logi:<22} | {pick:<7} |")
    print("\nRule of thumb:")
    print("  * need an EXACT clone or crash recovery    -> physical (fast, dumb, exact).")
    print("  * need flexibility, filtering, or version bridging -> logical (smart, schema-aware).")


# ============================================================================
# SECTION E: LIMITATIONS OF LOGICAL - what is NOT replicated
# ============================================================================

def section_e():
    banner("SECTION E: LIMITATIONS of logical - what is NOT shipped")
    print("Logical decoding only understands ROW changes. Everything else is silent:\n")
    limits = [
        ("DDL / schema changes",   "no",  "ALTER TABLE ADD COLUMN, CREATE INDEX, DROP TABLE are NOT decoded. Subscriber schema must be migrated by hand (or by a tool like pglogical/londiste). A column-type change can break decoding outright."),
        ("SEQUENCES",              "no",  "nextval/currval are not row changes. Subscribers must partition the sequence range (setval) or use a separate allocator, or they WILL collide on INSERT."),
        ("Large objects (lo_*)",   "no",  "pg_largeobject writes are not logical change records. (PG 16 added streaming of large objects, but default setups still skip them.)"),
        ("TRUNCATE (pre-PG 11)",   "no",  "Supported since PG 11 only; earlier versions silently dropped TRUNCATE."),
        ("REPLICA IDENTITY NONE tables", "no", "UPDATE/DELETE cannot be decoded without a replica identity (PK or FULL). INSERTs still work."),
        ("non-loggable tables",    "no",  "UNLOGGED and TEMP tables have no WAL -> nothing to decode."),
        ("storage-level details",  "n/a", "Physical byte layout differs by design: different XIDs, offsets, free space, hint bits. That is NOT a bug - it is the point."),
    ]
    print("  | object / change                       | replicated? | why / consequence")
    print("  |---------------------------------------|-------------|---------------------------")
    for what, rep, why in limits:
        print(f"  | {what:<37} | {rep:<11} | {why}")
    print("\nThe big one: SEQUENCES. If publisher and subscriber both auto-generate ids,")
    print("they will eventually hand out the SAME id -> duplicate-key conflict (Sec F).")
    print("Fix: on the subscriber, ALTER SEQUENCE ... INCREMENT BY <big> and setval so")
    print("the two ranges never overlap; or make the subscriber's columns NOT DEFAULT.")


# ============================================================================
# SECTION F: CONFLICT RESOLUTION on the subscriber
# ============================================================================

def section_f():
    banner("SECTION F: CONFLICTS - when the subscriber cannot apply a change")
    print("Physical standbys never conflict: they paste bytes, there is no logic to")
    print("fail. Logical subscribers RE-EXECUTE the change as SQL, so they CAN fail.\n")
    print("Three classic conflicts:\n")
    cases = [
        ("duplicate key",   "INSERT row that already exists on subscriber",
         "ERROR (default)", "subscription STOPS; fix the row, then resume"),
        ("missing row",     "UPDATE/DELETE of a row absent on subscriber",
         "ERROR (default)", "subscription STOPS; the row was deleted/changed locally"),
        ("FK violation",    "incoming row references a parent not yet on subscriber",
         "ERROR (default)", "ordering: replicate parent table BEFORE child table"),
        ("unique violation","local unique index rejects the incoming row",
         "ERROR (default)", "drop conflicting local index or dedupe first"),
    ]
    print("  | conflict          | trigger                                   |"
          " default action   | recovery                          |")
    print("  |-------------------|-------------------------------------------|"
          "------------------|-----------------------------------|")
    for name, trig, act, rec in cases:
        print(f"  | {name:<17} | {trig:<41} | {act:<16} | {rec:<33} |")

    print("\nResolution strategies (PG 17+ adds a native conflict detector; older")
    print("versions need pglogical or application-level handling):\n")
    strat = [
        ("error (default)", "stop the subscription, alert a human", "correctness first; never lose data silently"),
        ("skip",            "log the conflicting change, keep going", "best-effort sync; subscriber may permanently diverge"),
        ("last-writer-wins","apply with ON CONFLICT DO UPDATE", "needs a UNIQUE index + a resolver; bidirectional sync"),
        ("source-wins",     "DELETE local + INSERT incoming",         "re-converge to publisher state; discards local edits"),
    ]
    print("  | strategy          | what it does                         | when to use               |")
    print("  |-------------------|--------------------------------------|---------------------------|")
    for name, does, when in strat:
        print(f"  | {name:<17} | {does:<36} | {when:<25} |")

    print("\nConcrete conflict simulation:")
    sub = LogicalStore()
    # subscriber already has user id=2 (e.g. seeded locally, or sequence collision)
    sub.apply("users", "INSERT", {"new": {"id": 2, "name": "LOCAL", "email": "l@x"}})
    print(f"  subscriber already has: {fmt_row(sub.view('users')[0], 'users')}")
    print("  publisher ships logical change: INSERT users id=2 ...")
    try:
        sub.apply("users", "INSERT",
                  {"new": {"id": 2, "name": "Alan T", "email": "alan@x.io"}})
    except ConflictError as e:
        print(f"  -> ConflictError: {e.kind} on {e.table} pk={e.pk}")
        print(f"     existing row : {fmt_row(e.existing, 'users')}")
        print("     default action: subscription STOPS until resolved.")
    print("\n  This is WHY physical is the default for HA failover (it cannot conflict)")
    print("  and logical is chosen only when its flexibility outweighs this risk.")


# ============================================================================
# SECTION G: GOLD CHECK - logical decoded state == physical replayed state
# ============================================================================

def section_g():
    banner("SECTION G: GOLD CHECK - logical decoded state == physical replayed state")
    primary = Heap()
    wal = run_primary(primary, WORKLOAD)
    record_bytes = [encode_physical(r) for r in wal]

    # PHYSICAL path: standby replays raw bytes
    standby = Heap()
    apply_physical(standby, record_bytes)
    physical_state = {t: heap_view(standby, t) for t in ("users", "orders")}

    # LOGICAL path: output plugin decodes, subscriber applies
    sub = LogicalStore()
    for r in wal:
        apply_logical(sub, decode_logical(encode_physical(r)))
    logical_state = {t: sorted(sub.view(t),
                        key=lambda r: r[CATALOG[TABLE_TO_REL[t]]["pk"]]) for t in ("users", "orders")}

    print("Both paths start from the SAME WAL stream. The promise of logical")
    print("replication: the decoded change records reconstruct the SAME visible")
    print("table state as a byte-faithful physical replay.\n")

    for t in ("users", "orders"):
        print(f"  table {t}:")
        print(f"    physical replay rows = {len(physical_state[t])}")
        print(f"    logical  decoded rows = {len(logical_state[t])}")
        for prow, lrow in zip(physical_state[t], logical_state[t]):
            same = prow == lrow
            print(f"      [{'OK' if same else 'DIFF'}] phys {fmt_row(prow, t)}")
            if not same:
                print(f"            logi {fmt_row(lrow, t)}")
        print()

    gold_eq = physical_state == logical_state
    print(f"  [check] logical state == physical state (row-by-row)?  {gold_eq}")
    assert gold_eq, "logical decoded state must equal physical replayed state"

    # byte fidelity (physical-only property) still holds
    byte_ok = primary.byte_fingerprint() == standby.byte_fingerprint()
    print(f"  [check] physical standby byte-identical to primary?    {byte_ok}")
    assert byte_ok

    fp, canon = state_fingerprint(logical_state)
    print("\nGOLD values (pinned for logical_vs_physical.html):")
    print(f"  GOLD canonical state string = {canon}")
    print(f"  GOLD state sha256[:16]       = {fp}")
    n_users = len(logical_state["users"])
    n_orders = len(logical_state["orders"])
    sum_orders = sum(r["amount"] for r in logical_state["orders"])
    print(f"  GOLD users.rows              = {n_users}")
    print(f"  GOLD orders.rows             = {n_orders}")
    print(f"  GOLD orders.amount SUM       = {sum_orders}")
    print("\n  [check] gold self-consistency (recompute from .py state):  OK")
    assert n_users == 2 and n_orders == 3 and sum_orders == 420


# ============================================================================
# main
# ============================================================================

def main():
    print("logical_vs_physical.py - reference impl. All numbers below feed")
    print("LOGICAL_VS_PHYSICAL.md.")
    print("python ok, stdlib only (struct/hashlib/json/dataclasses).\n")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
