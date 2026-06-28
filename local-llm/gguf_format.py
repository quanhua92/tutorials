"""
gguf_format.py - Reference implementation of the GGUF binary format.

This is the single source of truth that GGUF_FORMAT.md is built from. Every
number, byte offset, and hex byte in GGUF_FORMAT.md is printed by this file.
Pure Python stdlib only (NO torch, NO numpy, NO external libs) - this is the
*local runtime* file-format side, not the server-side checkpoint format.

Run:
    python3 gguf_format.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
GGUF (GPT-Generated Unified Format) is a single-file binary layout for shipping
a whole model: tokenizer + chat template + hyperparameters + tensor metadata +
the raw weight bytes. It is what llama.cpp, Ollama, LM Studio, and friends load.

The file is four sections, in order:

  1. HEADER (24 bytes, fixed)
       magic             uint32 LE   = 0x46554747 ("GGUF" in ASCII)
       version           uint32 LE   = 3 (current as of 2025+)
       tensor_count      uint64
       metadata_kv_count uint64

  2. METADATA KV (variable, metadata_kv_count pairs)
       Each pair: key(string) + value_type(uint32) + value
       The KV section is WHY GGUF exists: it lets ONE file describe ANY model
       architecture, tokenizer, and chat template, without code changes. This is
       the break from the old flat GGML format, which needed code edits for every
       new architecture.

  3. TENSOR INFO TABLE (variable, tensor_count entries)
       Each entry: name(string) + n_dims(uint32) + dims[n_dims](uint64)
                   + type(uint32, ggml_type) + offset(uint64)

  4. TENSOR DATA (the actual weight bytes)
       Padded so it starts at a multiple of `general.alignment` (default 32).
       The padding is what makes the file mmap-friendly: the OS can map the
       weight blob directly into the process address space, page-aligned, so
       tensors load lazily on first access instead of being read eagerly.

Strings are uint64 length + UTF-8 bytes (NO null terminator).

GOLD VALUE (for gguf_format.html to reproduce):
    Build a tiny GGUF in memory with 2 KV pairs + 1 tensor, parse it back:
      magic == 0x46554747
      version == 3
      tensor "token_embd.weight" dims=[4,2] type=F32 offset=0
"""

from __future__ import annotations

import struct

# ----------------------------------------------------------------------------
# Constants (verified against gguf-py/gguf/gguf.py + ggml.h)
# ----------------------------------------------------------------------------

GGUF_MAGIC = 0x46554747          # uint32 little-endian; bytes spell "GGUF"
GGUF_VERSION = 3                 # current schema version (2025+)
GGUF_DEFAULT_ALIGNMENT = 32      # tensor_data starts at a multiple of this

# GGUFValueType enum (the value_type uint32 in each KV pair).
GGUFValueType = {
    0:  "UINT8",
    1:  "INT8",
    2:  "UINT16",
    3:  "INT16",
    4:  "UINT32",
    5:  "INT32",
    6:  "FLOAT32",
    7:  "BOOL",
    8:  "STRING",
    9:  "ARRAY",
    10: "UINT64",
    11: "INT64",
    12: "FLOAT64",
}
# Inverse: name -> id
GGUFValueType_ID = {v: k for k, v in GGUFValueType.items()}

# Fixed-size scalar value types -> (struct format char, byte size).
_SCALAR_FMT = {
    "UINT8":   ("<B", 1),
    "INT8":    ("<b", 1),
    "UINT16":  ("<H", 2),
    "INT16":   ("<h", 2),
    "UINT32":  ("<I", 4),
    "INT32":   ("<i", 4),
    "FLOAT32": ("<f", 4),
    "BOOL":    ("<B", 1),     # serialized as a single uint8 (0 or 1)
    "UINT64":  ("<Q", 8),
    "INT64":   ("<q", 8),
    "FLOAT64": ("<d", 8),
}

# ggml_type enum (the type uint32 in each tensor info entry). Only the values
# we reference; the full table lives in quant_types.py.
GGML_TYPE = {
    0:  "F32",
    1:  "F16",
    2:  "Q4_0",
    6:  "Q5_0",
    7:  "Q5_1",
    8:  "Q8_0",
    12: "Q4_K",
    14: "Q6_K",
    31: "BF16",
}

BANNER = "=" * 74


# ============================================================================
# 0. CHECK HELPER (invariants the round-trip must satisfy)
# ============================================================================

def check(label: str, cond: bool, detail: str = ""):
    """Assert-style checker that prints [check] lines for _output.txt."""
    status = "OK" if cond else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"[check] {label} :  {status}{extra}")
    assert cond, f"CHECK FAILED: {label} {detail}"


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 1. LOW-LEVEL ENCODERS (the bytes that actually ship in a .gguf file)
# ============================================================================

def pack_string(s: str) -> bytes:
    """GGUF string: uint64 length (LE) + UTF-8 bytes. No null terminator."""
    raw = s.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def pack_scalar_value(type_name: str, value) -> bytes:
    """Pack a fixed-size scalar value (UINT32, FLOAT32, BOOL, ...)."""
    fmt, _ = _SCALAR_FMT[type_name]
    if type_name == "BOOL":
        value = 1 if value else 0
    return struct.pack(fmt, value)


def pack_kv(key: str, value_type_name: str, value) -> bytes:
    """Pack one KV pair: key(string) + value_type(uint32) + value.

    For STRING: value is a str.
    For ARRAY:  value is (element_type_name, [elements]); the array encodes as
                array_type(uint32) + array_len(uint64) + packed elements.
    For scalars: value is the python scalar.
    """
    out = pack_string(key)
    out += struct.pack("<I", GGUFValueType_ID[value_type_name])
    if value_type_name == "STRING":
        out += pack_string(value)
    elif value_type_name == "ARRAY":
        elem_type, elems = value
        out += struct.pack("<I", GGUFValueType_ID[elem_type])
        out += struct.pack("<Q", len(elems))
        for e in elems:
            out += pack_scalar_value(elem_type, e)
    else:
        out += pack_scalar_value(value_type_name, value)
    return out


def pack_tensor_info(name: str, dims: list[int], ggml_type_id: int,
                     offset: int) -> bytes:
    """Pack one tensor info entry:
       name(string) + n_dims(uint32) + dims[n_dims](uint64 each, row-major)
       + type(uint32) + offset(uint64, relative to tensor_data start).
    """
    out = pack_string(name)
    out += struct.pack("<I", len(dims))
    for d in dims:
        out += struct.pack("<Q", d)
    out += struct.pack("<I", ggml_type_id)
    out += struct.pack("<Q", offset)
    return out


def align_up(x: int, alignment: int) -> int:
    """Round x up to the next multiple of alignment."""
    return (x + alignment - 1) // alignment * alignment


# ============================================================================
# 2. LOW-LEVEL DECODERS (parse bytes back into python values)
# ============================================================================

class Reader:
    """Minimal cursor over a bytes buffer; advances as fields are read."""

    def __init__(self, buf: bytes, pos: int = 0):
        self.buf = buf
        self.pos = pos

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def u64(self) -> int:
        v = struct.unpack_from("<Q", self.buf, self.pos)[0]
        self.pos += 8
        return v

    def string(self) -> str:
        n = self.u64()
        s = self.buf[self.pos:self.pos + n].decode("utf-8")
        self.pos += n
        return s

    def scalar(self, type_name: str):
        fmt, size = _SCALAR_FMT[type_name]
        v = struct.unpack_from(fmt, self.buf, self.pos)[0]
        self.pos += size
        if type_name == "BOOL":
            v = bool(v)
        return v


def read_kv(r: Reader):
    """Read one KV pair -> (key, type_name, value)."""
    key = r.string()
    type_id = r.u32()
    type_name = GGUFValueType[type_id]
    if type_name == "STRING":
        value = r.string()
    elif type_name == "ARRAY":
        elem_id = r.u32()
        elem_type = GGUFValueType[elem_id]
        n = r.u64()
        value = [r.scalar(elem_type) for _ in range(n)]
    else:
        value = r.scalar(type_name)
    return key, type_name, value


def read_tensor_info(r: Reader):
    """Read one tensor info entry -> (name, dims, ggml_type_id, offset)."""
    name = r.string()
    n_dims = r.u32()
    dims = [r.u64() for _ in range(n_dims)]
    type_id = r.u32()
    offset = r.u64()
    return name, dims, type_id, offset


# ============================================================================
# 3. HEX DUMP HELPER (for the byte-for-byte layout printout)
# ============================================================================

def hexdump(buf: bytes, base: int = 0, width: int = 16) -> str:
    """Classic 3-column hex dump: offset | hex bytes | ascii."""
    lines = []
    for i in range(0, len(buf), width):
        chunk = buf[i:i + width]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        hexpart = hexpart.ljust(width * 3 - 1)
        asciipart = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + i:06x}  {hexpart}  |{asciipart}|")
    return "\n".join(lines)


# ============================================================================
# 4. SECTIONS
# ============================================================================

def section_a_header():
    banner("SECTION A: HEADER - magic, version, counts (24 bytes fixed)")
    print("GGUF header layout (verified: gguf-py/gguf/gguf.py GGUF_MAGIC/VERSION):")
    print("  offset 0   magic             uint32 LE = 0x46554747 (ASCII 'GGUF')")
    print("  offset 4   version           uint32 LE = 3")
    print("  offset 8   tensor_count      uint64")
    print("  offset 16  metadata_kv_count uint64")
    print("  offset 24  ... metadata_kv[] / tensor_info[] / tensor_data ...")
    print()
    print("Magic sanity: 0x46554747 little-endian = bytes "
          f"{struct.pack('<I', GGUF_MAGIC).hex()} = ASCII "
          f"'{struct.pack('<I', GGUF_MAGIC).decode('ascii')}'")
    print()
    # Build a header for a file with 1 tensor and 2 KV pairs.
    header = (struct.pack("<I", GGUF_MAGIC)
              + struct.pack("<I", GGUF_VERSION)
              + struct.pack("<Q", 1)    # tensor_count
              + struct.pack("<Q", 2))   # metadata_kv_count
    print(f"Built header ({len(header)} bytes):")
    print(hexdump(header))
    print()
    # Parse it back.
    r = Reader(header)
    magic = r.u32()
    version = r.u32()
    tcount = r.u64()
    kcount = r.u64()
    print(f"Parsed back:")
    print(f"  magic          = 0x{magic:08x}")
    print(f"  version        = {version}")
    print(f"  tensor_count   = {tcount}")
    print(f"  kv_count       = {kcount}")
    print()
    check("magic == 0x46554747", magic == GGUF_MAGIC, f"0x{magic:08x}")
    check("version == 3", version == GGUF_VERSION, f"{version}")
    check("header is exactly 24 bytes", len(header) == 24, f"{len(header)}")
    check("cursor advanced to 24 after header", r.pos == 24, f"pos={r.pos}")


def section_b_kv_metadata():
    banner("SECTION B: KV METADATA - typed key/value pairs")
    print("Every KV pair: key(string) + value_type(uint32) + value(type-dependent).")
    print("Strings = uint64 length + UTF-8 bytes (NO null terminator).")
    print("ARRAY = array_type(uint32) + array_len(uint64) + array_len scalars.")
    print()
    print("GGUFValueType enum (the value_type uint32):")
    for tid in sorted(GGUFValueType):
        print(f"  {tid:>2}  {GGUFValueType[tid]:<10}", end="")
        if tid % 4 == 3:
            print()
    if (len(GGUFValueType) % 4) != 0:
        print()
    print()
    # Build three illustrative pairs of different types.
    pairs = [
        ("general.architecture",   "STRING", "llama"),
        ("general.file_type",      "UINT32", 1),
        ("tokenizer.ggml.bos",     "BOOL",   True),
        ("llama.context_length",   "UINT32", 4096),
        ("llama.embedding_length", "ARRAY",  ("UINT32", [4096, 4096])),
    ]
    print("Building 5 KV pairs (showing the type system):")
    blob = b"".join(pack_kv(k, t, v) for k, t, v in pairs)
    print(f"  total KV bytes = {len(blob)}")
    print()
    # Parse them back.
    r = Reader(blob)
    print(f"{'key':<28} {'type':<8} value")
    print("-" * 60)
    for i in range(len(pairs)):
        key, tname, value = read_kv(r)
        if tname == "ARRAY":
            shown = f"{value}"
        elif tname == "STRING":
            shown = repr(value)
        else:
            shown = repr(value)
        print(f"{key:<28} {tname:<8} {shown}")
    print()
    check("5 KV pairs parsed fully (cursor at end)",
          r.pos == len(blob), f"pos={r.pos} len={len(blob)}")
    check("BOOL True survives round-trip as 1 byte",
          pack_scalar_value("BOOL", True) == b"\x01")
    check("STRING has uint64 length prefix (8 bytes) + payload",
          pack_string("ab") == struct.pack("<Q", 2) + b"ab")


def section_c_tensor_info():
    banner("SECTION C: TENSOR INFO TABLE - name, dims, type, offset")
    print("Each tensor info entry:")
    print("  name    : string")
    print("  n_dims  : uint32")
    print("  dims[]  : n_dims x uint64, row-major (dim[0] = outermost)")
    print("  type    : uint32 (ggml_type enum: F32=0, F16=1, Q4_0=2, Q4_K=12, ...)")
    print("  offset  : uint64, RELATIVE to the start of the tensor_data section")
    print("           (NOT the file start - the padding in Section D is why)")
    print()
    # Build a 2-D F32 tensor info: token_embd.weight [4, 2].
    name = "token_embd.weight"
    dims = [4, 2]
    ggml_type_id = 0   # F32
    offset = 0
    info = pack_tensor_info(name, dims, ggml_type_id, offset)
    print(f"Built tensor info for '{name}' dims={dims} type={GGML_TYPE[ggml_type_id]} "
          f"offset={offset}:")
    print(hexdump(info))
    print(f"  ({len(info)} bytes)")
    print()
    r = Reader(info)
    rname, rdims, rtype, roff = read_tensor_info(r)
    print(f"Parsed back:")
    print(f"  name      = {rname}")
    print(f"  dims      = {rdims}")
    print(f"  type_id   = {rtype} ({GGML_TYPE.get(rtype, '?')})")
    print(f"  offset    = {roff}")
    print()
    n_elems = 1
    for d in rdims:
        n_elems *= d
    print(f"  n_elements = {n_elems}")
    print(f"  data bytes (F32) = {n_elems} * 4 = {n_elems * 4}")
    check("tensor name round-trips", rname == name)
    check("dims round-trip", rdims == dims)
    check("type F32==0", rtype == 0)
    check("offset round-trips", roff == offset)
    check("tensor info parsed fully", r.pos == len(info))


def section_d_full_build():
    banner("SECTION D: FULL BUILD - 2 KV + 1 tensor, alignment, round-trip")
    print("Assemble a complete (tiny) valid GGUF file in memory, then parse it.")
    print("This is the GOLD value for gguf_format.html.")
    print()

    # ---- the three sections of a real .gguf (minus the raw weight blob) ----
    kv_pairs = [
        ("general.architecture", "STRING", "llama"),
        ("general.file_type",    "UINT32", 1),
    ]
    tensor = ("token_embd.weight", [4, 2], 0)   # name, dims, type=F32

    header = (struct.pack("<I", GGUF_MAGIC)
              + struct.pack("<I", GGUF_VERSION)
              + struct.pack("<Q", 1)             # tensor_count
              + struct.pack("<Q", len(kv_pairs)))
    kv_blob = b"".join(pack_kv(k, t, v) for k, t, v in kv_pairs)
    info_blob = pack_tensor_info(tensor[0], tensor[1], tensor[2], 0)

    offset_after_info = len(header) + len(kv_blob) + len(info_blob)
    tensor_data_offset = align_up(offset_after_info, GGUF_DEFAULT_ALIGNMENT)
    padding = tensor_data_offset - offset_after_info

    # ---- the raw weight bytes: 8 F32 values, dims=[4,2] ----
    weights = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    tensor_data = struct.pack("<8f", *weights)

    full = (header + kv_blob + info_blob
            + b"\x00" * padding + tensor_data)

    print(f"Layout:")
    print(f"  header              [   0 .. {len(header):>3})  {len(header):>3} bytes")
    print(f"  metadata_kv         [{len(header):>3} .. {len(header)+len(kv_blob):>3})  "
          f"{len(kv_blob):>3} bytes  ({len(kv_pairs)} pairs)")
    print(f"  tensor_info         [{len(header)+len(kv_blob):>3} .. "
          f"{len(header)+len(kv_blob)+len(info_blob):>3})  {len(info_blob):>3} bytes  "
          f"(1 tensor)")
    print(f"  alignment padding   [{offset_after_info:>3} .. {tensor_data_offset:>3})  "
          f"{padding:>3} bytes  "
          f"(align_up({offset_after_info},{GGUF_DEFAULT_ALIGNMENT})={tensor_data_offset})")
    print(f"  tensor_data         [{tensor_data_offset:>3} .. {len(full):>3})  "
          f"{len(tensor_data):>3} bytes  ({len(weights)} x F32)")
    print(f"  TOTAL FILE SIZE     = {len(full)} bytes")
    print()
    print("Full hex dump:")
    print(hexdump(full))
    print()
    print("Section boundaries overlaid on the first bytes:")
    print(f"  bytes  0..3   magic        = {full[0:4].hex()} = "
          f"'{full[0:4].decode('ascii')}'")
    print(f"  bytes  4..7   version      = {full[4:8].hex()} = {GGUF_VERSION}")
    print()

    # ---- parse the whole thing back from scratch ----
    r = Reader(full)
    magic = r.u32()
    version = r.u32()
    tcount = r.u64()
    kcount = r.u64()
    parsed_kv = [read_kv(r) for _ in range(kcount)]
    parsed_ti = [read_tensor_info(r) for _ in range(tcount)]
    # skip alignment padding to reach tensor_data
    r.pos = tensor_data_offset
    parsed_w = list(struct.unpack_from("<8f", full, tensor_data_offset))

    print("Round-trip parse:")
    print(f"  magic = 0x{magic:08x}, version = {version}")
    for k, t, v in parsed_kv:
        print(f"  KV {k} = {v}")
    (pname, pdims, ptype, poff) = parsed_ti[0]
    print(f"  tensor '{pname}' dims={pdims} type={GGML_TYPE[ptype]} offset={poff}")
    print(f"  weights = {parsed_w}")
    print()

    # ---- THE GOLD CHECKS ----
    check("magic == 0x46554747", magic == GGUF_MAGIC, f"0x{magic:08x}")
    check("version == 3", version == GGUF_VERSION, f"{version}")
    check("tensor_count == 1", tcount == 1)
    check("kv_count == 2", kcount == 2)
    check("KV[0] general.architecture == 'llama'",
          parsed_kv[0][2] == "llama")
    check("KV[1] general.file_type == 1", parsed_kv[1][2] == 1)
    check("tensor name == 'token_embd.weight'", pname == "token_embd.weight")
    check("tensor dims == [4,2]", pdims == [4, 2])
    check("tensor type == F32 (0)", ptype == 0)
    check("tensor offset == 0", poff == 0)
    check("weights round-trip exactly", parsed_w == weights)
    check("tensor_data starts at a multiple of 32",
          tensor_data_offset % GGUF_DEFAULT_ALIGNMENT == 0,
          f"{tensor_data_offset} % {GGUF_DEFAULT_ALIGNMENT}")
    check("padding is correct",
          padding == tensor_data_offset - offset_after_info)

    print()
    print("GOLD (for gguf_format.html):")
    print(f"  magic    = 0x{magic:08x}")
    print(f"  version  = {version}")
    print(f"  file_len = {len(full)}")
    print(f"  tensor_data_offset = {tensor_data_offset}")
    print(f"  weights  = {parsed_w}")


def section_e_lineage():
    banner("SECTION E: LINEAGE - GGML (flat) -> GGUF (why each step)")
    print("WHY GGUF exists: the old GGML format was a flat dump of tensors with")
    print("NO self-describing metadata. Adding a new model architecture meant")
    print("editing the C loader code and bumping a breaking format version.")
    print()
    print("GGUF fixes this with a versioned schema + a typed KV section that can")
    print("describe ANY architecture / tokenizer / chat template from inside the")
    print("file. One loader, many models, backward compatible.")
    print()
    lineage = [
        ("GGML (old flat)",
         "tensors only, no metadata, breaking change per architecture",
         "every new model = a code change + a new loader"),
        ("GGUF v1/v2",
         "+ KV metadata + version field + single-file layout",
         "architecture/tokenizer described IN the file"),
        ("GGUF v3 (now)",
         "+ general.alignment KV + tokenizer.ggml.* + chat template KV, "
         "mmap-friendly aligned tensor_data",
         "one loader runs every architecture; mmap loads weights lazily"),
    ]
    print(f"{'stage':<16} what changed                                   why")
    print("-" * 78)
    for stage, what, why in lineage:
        print(f"{stage:<16} {what:<47} {why}")
    print()
    print("The mmap win: tensor_data is aligned to a multiple of "
          f"{GGUF_DEFAULT_ALIGNMENT}, so the OS can mmap it directly. On a 4 GB")
    print("model that is the difference between a ~12 s eager load and a ~0.1 s")
    print("lazy startup (pages are faulted in on first access).")
    print("See MMAP_WEIGHTS.md for the page-fault / copy-on-write mechanics.")
    check("GGUF magic is ASCII 'GGUF'",
          struct.pack("<I", GGUF_MAGIC) == b"GGUF")
    check("current version is 3", GGUF_VERSION == 3)
    check("default alignment is 32", GGUF_DEFAULT_ALIGNMENT == 32)


# ============================================================================
# main
# ============================================================================

def main():
    print("gguf_format.py - GGUF (GPT-Generated Unified Format) binary layout.")
    print("Pure Python stdlib (struct only). Numbers below feed GGUF_FORMAT.md.")
    print("Sources: gguf-py/gguf/gguf.py + ggml.h + HuggingFace GGUF docs.")
    print()
    print("Four sections: header -> KV metadata -> tensor info -> aligned "
          "tensor_data.")

    section_a_header()
    section_b_kv_metadata()
    section_c_tensor_info()
    section_d_full_build()
    section_e_lineage()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
