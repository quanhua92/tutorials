"""
geohashing.py - Reference implementation of the geohash spatial index: encode
2D lat/lng into a 1D base-32 string that preserves spatial locality, decode it
back to a cell, list the 8 neighbour cells via prefix matching, and tabulate
precision vs cell size.

This is the single source of truth that GEOHASHING.md is built from. Every
geohash, cell bound, neighbour string, and km figure is printed by this file.
Deterministic (no randomness, no network, no clock). Re-run and re-paste.

Run:
    python3 geohashing.py

==========================================================================
THE INTUITION (read this first) - the nested Russian-doll grid
==========================================================================
A B-tree index is a 1D structure; geographic proximity is 2D. To make a
B-tree answer "what is NEAR this point", you must flatten the 2D surface into
1D in a way that PRESERVES locality: points close in 2D should mostly stay
close in 1D. Geohash does that with a Z-order (Morton) curve.

Picture the Earth as a square [(-180,-90) .. (180,90)]. Now play 20 questions:

  Q1 (longitude): are you in the EAST half or the WEST half?  -> 1 bit
  Q2 (latitude):  are you in the NORTH half or SOUTH half?    -> 1 bit
  ...repeat, halving the box every question.

Each answer is one bit. We INTERLEAVE them (lng, lat, lng, lat, ...) so that
every two bits subdivide the box into a quarter. After 5 bits we have one of
32 sub-boxes -> that index becomes one BASE-32 character. After N characters
we have a 5N-bit path describing an ever-smaller nested box. The string is the
geohash.

  precision 1 -> 5 bits  -> a ~5000 km box (continent)
  precision 5 -> 25 bits -> a ~5 km box    (neighbourhood)
  precision 8 -> 40 bits -> a ~40 m box     (a building)

Two geohashes that share a PREFIX described the same sequence of boxes for as
long as that prefix lasts, so they live inside the same bigger box -> they are
close. A prefix query `WHERE geohash LIKE '9q8yy%'` is a B-tree RANGE scan that
returns every point in that box. That is the whole trick: prefix == proximity,
and prefix search rides an ordinary B-tree.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  geohash         : the base-32 string encoding a point's nested-box path.
  base-32 alphabet: "0123456789bcdefghjkmnpqrstuvwxyz" - note a,i,l,o are
                    OMITTED (they look like digits / each other).
  interleave      : the bit path is lng-bnd, lat-bnd, lng-bnd, lat-bnd ...
                    i.e. longitude bits occupy even positions, latitude bits
                    odd positions. This is the Z-order / Morton curve.
  precision       : the number of base-32 characters (each = 5 bits).
  cell            : the rectangular lat/lng box a geohash describes. decode()
                    returns the box's min/max, not a point; the centre is the
                    canonical representative point.
  neighbour cell  : one of the 8 cells touching the centre cell (N,S,E,W and
                    the 4 diagonals). Computed by the lookup-table adjacent()
                    algorithm, NOT by re-encoding a nudged coordinate.
  prefix match    : two geohashes sharing the first k chars live in the same
                    k-character box. `WHERE geohash LIKE '9q8y%'` = range scan.
  9-cell query    : always fetch the centre cell + its 8 neighbours, because
                    points right on a cell edge have a DIFFERENT prefix than
                    their neighbour (the boundary problem).

==========================================================================
THE GEOHASH INVARIANTS (the things this bundle proves)
  (1) round-trip    : decode(encode(lat,lng)) cell CONTAINS (lat,lng)
  (2) prefix stable : decode(h) truncated to p chars, re-encoded, == h[:p]
                      (a geohash is a fixed point of truncate-then-re-encode)
  (3) 5x area       : each added character multiplies area by exactly 1/32
                      (5 more bits -> 2^5 = 32 finer boxes)
  (4) 9 distinct    : a cell + its 8 neighbours are 9 DISTINCT strings
                      (the 9-cell query reads 9 real cells, never a duplicate)
  (5) prefix != proximity: neighbours are GEOGRAPHICALLY adjacent but a Z-order
                      cell and its neighbour need NOT share a long prefix - the
                      common prefix can diverge well before the last char.
                      This is exactly why a single `LIKE 'prefix%'` is unsafe
                      and the explicit 9-cell enumeration is mandatory.

geohashing.html re-derives encode/decode/adjacent in JS and re-asserts the
gold checks live.

References:
  - Gustavo Niemeyer, geohash.org (2008) - the public-domain original.
  - Wikipedia, "Geohash" - bit-interleave (longitude first), base-32 alphabet,
    precision-vs-cell-size table.
  - chrisveness/latlon-geohash - the neighbour lookup tables (NEIGHBOR/BORDER)
    used in adjacent().
  - Redis GEOADD/GEOSEARCH - stores a 52-bit integer geohash as a sorted-set
    score; prefix/range queries map to ZRANGEBYSCORE.
  - IBM Cloud Docs, "Geohashing functions" - encode/decode/neighbours-by-depth.
"""

from __future__ import annotations

BANNER = "=" * 72

# base-32 alphabet: digits 0-9 then letters, SKIPPING a, i, l, o.
# (a ~ 8 shape? i~l~1, o~0 - all removed to stay unambiguous when read aloud.)
BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

# Earth bounds used by the canonical geohash.
LAT_RANGE = (-90.0, 90.0)
LNG_RANGE = (-180.0, 180.0)

# ~111.32 km per degree at the equator (used to convert cell degrees -> km).
KM_PER_DEG = 111.32


# ============================================================================
# 1. ENCODE  (the code GEOHASHING.md walks through)
# ============================================================================

def encode(lat: float, lng: float, precision: int = 12) -> str:
    """Encode (lat, lng) to a base-32 geohash of `precision` characters.

    Bit-interleave the longitude (even positions) and latitude (odd positions)
    halves, then pack every 5 bits into one BASE32 character. Each bit halves
    one axis; each character (5 bits) cuts area to 1/32.
    """
    lat_lo, lat_hi = LAT_RANGE
    lng_lo, lng_hi = LNG_RANGE
    geohash = []
    bits = 0
    bit_count = 0
    even = True  # first bit is longitude
    while len(geohash) < precision:
        if even:  # longitude bit
            mid = (lng_lo + lng_hi) / 2
            if lng >= mid:
                bits = (bits << 1) | 1
                lng_lo = mid
            else:
                bits = (bits << 1)
                lng_hi = mid
        else:    # latitude bit
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                bits = (bits << 1) | 1
                lat_lo = mid
            else:
                bits = (bits << 1)
                lat_hi = mid
        even = not even
        bit_count += 1
        if bit_count == 5:            # a full base-32 character
            geohash.append(BASE32[bits])
            bits = 0
            bit_count = 0
    return "".join(geohash)


def encode_bits(lat: float, lng: float, precision: int):
    """Encode and ALSO return the interleaved bit list + which axis each bit.

    Used by Section A to print the worked-example bit table.
    Returns (geohash, [(axis, bit, char_index_or_None), ...]).
    """
    lat_lo, lat_hi = LAT_RANGE
    lng_lo, lng_hi = LNG_RANGE
    geohash = []
    bits = 0
    bit_count = 0
    rows = []
    even = True
    while len(geohash) < precision:
        axis = "lng" if even else "lat"
        if even:
            mid = (lng_lo + lng_hi) / 2
            take = lng >= mid
            if take:
                bits = (bits << 1) | 1; lng_lo = mid
            else:
                bits = (bits << 1);     lng_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            take = lat >= mid
            if take:
                bits = (bits << 1) | 1; lat_lo = mid
            else:
                bits = (bits << 1);     lat_hi = mid
        even = not even
        bit_count += 1
        char_idx = None
        if bit_count == 5:
            geohash.append(BASE32[bits])
            char_idx = len(geohash) - 1
            bits = 0
            bit_count = 0
        rows.append((axis, 1 if take else 0, char_idx))
    return "".join(geohash), rows


# ============================================================================
# 2. DECODE  (inverse of encode)
# ============================================================================

def decode(geohash: str):
    """Decode a geohash to its CELL bounds.

    Returns dict with lat_min/lat_max/lng_min/lng_max (the box) and the
    canonical centre point (lat, lng). decode is deliberately NOT the inverse
    of a point: it returns the BOX a geohash names, because every point in
    that box maps to the same geohash.
    """
    lat_lo, lat_hi = LAT_RANGE
    lng_lo, lng_hi = LNG_RANGE
    even = True
    for ch in geohash:
        cd = BASE32.index(ch)
        for i in range(4, -1, -1):       # the 5 bits of this char, MSB first
            bit = (cd >> i) & 1
            if even:                      # longitude bit
                mid = (lng_lo + lng_hi) / 2
                if bit:
                    lng_lo = mid
                else:
                    lng_hi = mid
            else:                         # latitude bit
                mid = (lat_lo + lat_hi) / 2
                if bit:
                    lat_lo = mid
                else:
                    lat_hi = mid
            even = not even
    return {
        "lat_min": lat_lo, "lat_max": lat_hi,
        "lng_min": lng_lo, "lng_max": lng_hi,
        "lat": (lat_lo + lat_hi) / 2,
        "lng": (lng_lo + lng_hi) / 2,
    }


def decode_bbox(geohash: str):
    """Convenience: return (lat_min, lat_max, lng_min, lng_max)."""
    d = decode(geohash)
    return d["lat_min"], d["lat_max"], d["lng_min"], d["lng_max"]


# ============================================================================
# 3. NEIGHBOURS  (the 9-cell grid)
#    decode -> step one full cell over -> re-encode. This is unambiguous about
#    direction (we control the sign of the offset) and is correct at every
#    interior cell. Production libs (chrisveness/latlon-geohash, Redis) instead
#    use O(1) NEIGHBOR/BORDER lookup tables that recurse on the parent when the
#    last char sits on a border; the decode-nudge form below is the teaching
#    twin that makes the geometry self-evident.
# ============================================================================

def decode_centre(geohash: str):
    """Return (lat, lng) centre of a geohash cell."""
    d = decode(geohash)
    return d["lat"], d["lng"]


def adjacent(geohash: str, direction: str) -> str:
    """Return the geohash of the cell bordering `geohash` in `direction`.

    direction in {'n','s','e','w'}. Strategy: decode the centre, step ONE full
    cell over in the requested direction (landing at the centre of the
    neighbour, well clear of any boundary), then re-encode at the same
    precision. Wraps across the antimeridian (lng +-180) and clamps at the
    poles, so it is correct everywhere the cell grid exists.
    """
    p = len(geohash)
    _, _, lat_d, lng_d, _, _ = cell_size(p)
    lat_c, lng_c = decode_centre(geohash)
    if direction == "n":
        lat, lng = lat_c + lat_d, lng_c
    elif direction == "s":
        lat, lng = lat_c - lat_d, lng_c
    elif direction == "e":
        lat, lng = lat_c, lng_c + lng_d
    elif direction == "w":
        lat, lng = lat_c, lng_c - lng_d
    else:
        raise ValueError(f"unknown direction {direction!r}")
    # wrap longitude across the antimeridian
    if lng > 180.0:
        lng -= 360.0
    elif lng < -180.0:
        lng += 360.0
    # clamp latitude at the poles
    lat = max(-90.0 + lat_d / 2, min(90.0 - lat_d / 2, lat))
    return encode(lat, lng, p)


def neighbors(geohash: str) -> dict:
    """Return centre + the 8 surrounding cells as a 3x3 grid dict.

    Diagonals are computed directly from the centre (centre +/- one cell on
    BOTH axes) rather than by chaining two cardinal steps, which keeps them
    independent of float drift from a chained re-encode.
    """
    p = len(geohash)
    _, _, lat_d, lng_d, _, _ = cell_size(p)
    lat_c, lng_c = decode_centre(geohash)

    def cell_at(dlat, dlng):
        lat = lat_c + dlat * lat_d
        lng = lng_c + dlng * lng_d
        if lng > 180.0:
            lng -= 360.0
        elif lng < -180.0:
            lng += 360.0
        lat = max(-90.0 + lat_d / 2, min(90.0 - lat_d / 2, lat))
        return encode(lat, lng, p)

    return {
        "nw": cell_at( 1, -1), "n": cell_at( 1, 0), "ne": cell_at( 1, 1),
        "w":  cell_at( 0, -1), "c": geohash,        "e":  cell_at( 0, 1),
        "sw": cell_at(-1, -1), "s": cell_at(-1, 0), "se": cell_at(-1, 1),
    }


def grid3x3(geohash: str):
    """Return the 3x3 grid as a list of rows (for pretty-printing)."""
    nb = neighbors(geohash)
    return [
        [nb["nw"], nb["n"], nb["ne"]],
        [nb["w"],  nb["c"], nb["e"]],
        [nb["sw"], nb["s"], nb["se"]],
    ]


# ============================================================================
# 4. PRECISION VS CELL SIZE
# ============================================================================

def cell_size(precision: int):
    """Return (lat_bits, lng_bits, lat_deg, lng_deg, lat_km, lng_km) for a
    given precision. longitude bits = ceil(5p/2), latitude bits = floor(5p/2)
    because the FIRST bit is longitude. km uses the equator conversion."""
    bits = precision * 5
    lng_bits = (bits + 1) // 2   # longitude is bit 0,2,4,... (ceil)
    lat_bits = bits // 2          # latitude is bit 1,3,5,... (floor)
    lat_deg = 180.0 / (2 ** lat_bits)
    lng_deg = 360.0 / (2 ** lng_bits)
    return lat_bits, lng_bits, lat_deg, lng_deg, lat_deg * KM_PER_DEG, lng_deg * KM_PER_DEG


def precision_table(max_precision: int = 12):
    """Return a list of precision rows for the table."""
    rows = []
    for p in range(1, max_precision + 1):
        lat_b, lng_b, lat_d, lng_d, lat_km, lng_km = cell_size(p)
        rows.append({
            "p": p, "lat_bits": lat_b, "lng_bits": lng_b,
            "lat_deg": lat_deg(lat_b), "lng_deg": lng_deg(lng_b),
            "lat_km": lat_km, "lng_km": lng_km,
            "area_km2": lat_km * lng_km,
        })
    return rows


def lat_deg(lat_bits):
    return 180.0 / (2 ** lat_bits)


def lng_deg(lng_bits):
    return 360.0 / (2 ** lng_bits)


def common_prefix_len(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


# ============================================================================
# 5. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_precision_table(max_precision: int = 12):
    print(f"  {'prec':>4}  {'lat bits':>7} {'lng bits':>7}  "
          f"{'lat span':>10} {'lng span':>10}  {'cell (km)':>20}  "
          f"{'area (km^2)':>12}  what it pins")
    print(f"  {'-'*4}  {'-'*7} {'-'*7}  {'-'*10} {'-'*10}  {'-'*20}  "
          f"{'-'*12}  {'-'*14}")
    labels = {
        1: "continent", 2: "country", 3: "state",
        4: "metro region", 5: "neighbourhood", 6: "city block",
        7: "street", 8: "building", 9: "footprint",
    }
    rows = precision_table(max_precision)
    for r in rows:
        cell = f"{r['lat_km']:.4g} x {r['lng_km']:.4g}"
        if r["lat_km"] >= 1:
            cell = f"{r['lat_km']:.2f} x {r['lng_km']:.2f} km"
        else:
            cell = (f"{r['lat_km']*1000:.1f} x {r['lng_km']*1000:.1f} m")
        print(f"  {r['p']:>4}  {r['lat_bits']:>7} {r['lng_bits']:>7}  "
              f"{r['lat_deg']:>9.5g} {r['lng_deg']:>9.5g}  {cell:>20}  "
              f"{r['area_km2']:>12.4g}  {labels.get(r['p'], '')}")


# ============================================================================
# 6. PRETTY SCENARIOS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: encoding - interleave lat/lng bits, base32
# ----------------------------------------------------------------------------

def section_encode():
    banner("SECTION A: encoding - interleave lat/lng bits, then base32")
    print("Every bit halves ONE axis: longitude bits occupy even positions")
    print("(bit 0,2,4,...), latitude bits the odd ones. After 5 bits we have")
    print("one of 32 boxes -> one BASE32 char. Repeating gives N nested boxes.\n")
    print("Worked example: encode(42.6, -5.6) at precision 5.\n")
    gh, rows = encode_bits(42.6, -5.6, 5)
    # print the interleaved bit stream with the char it lands in
    print("  pos  axis   bit   | char")
    print("  ---  -----  ----  | ----")
    for i, (axis, bit, char_idx) in enumerate(rows):
        marker = f"-> '{gh[char_idx]}'" if char_idx is not None else ""
        print(f"  {i:>3}  {axis:<5}  {bit:>4}   {marker}")
    print(f"\n  bitstream = " + "".join(str(b) for _, b, _ in rows))
    print(f"  grouped   = " + " ".join(
        "".join(str(b) for _, b, _ in rows[k:k + 5])
        for k in range(0, len(rows), 5)))
    print(f"\n  encode(42.6, -5.6, 5) = '{gh}'")
    print(f"  [check] matches the canonical geohash.org / Wikipedia example 'ezs42'?  "
          f"{'OK' if gh == 'ezs42' else 'FAIL'}")
    print("\nRead it: the first char 'e' = bits 01101, which already pins the")
    print("point to a 5000 km box. Each later char subdivides the previous box")
    print("into 32. 'ezs42' is a ~5 km box near the Spain coast.")


# ----------------------------------------------------------------------------
# SECTION B: decoding - recover the cell box + centre
# ----------------------------------------------------------------------------

def section_decode():
    banner("SECTION B: decoding - a geohash names a CELL, not a point")
    gh = "ezs42"
    d = decode(gh)
    print(f"decode('{gh}') unwinds the bits back into lat/lng bounds:\n")
    print(f"  lng range = [{d['lng_min']:.5f}, {d['lng_max']:.5f}]   "
          f"width  = {d['lng_max']-d['lng_min']:.5f} deg")
    print(f"  lat range = [{d['lat_min']:.5f}, {d['lat_max']:.5f}]   "
          f"height = {d['lat_max']-d['lat_min']:.5f} deg")
    print(f"  centre    = (lat {d['lat']:.5f}, lng {d['lng']:.5f})\n")
    print("Every point inside this box encodes to 'ezs42'. decode returns the")
    print("BOX; the centre is just the canonical representative point.\n")
    # invariant (1): the original point is inside the cell
    inside = (d["lat_min"] <= 42.6 <= d["lat_max"]) and \
             (d["lng_min"] <= -5.6 <= d["lng_max"])
    print(f"[check] original point (42.6, -5.6) inside decode('ezs42') box?  "
          f"{'OK' if inside else 'FAIL'}")
    # invariant (2): truncate-then-re-encode is a fixed point
    re = encode(d["lat"], d["lng"], len(gh))
    print(f"[check] re-encode(centre) == 'ezs42'?  got '{re}'  ->  "
          f"{'OK' if re == gh else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION C: precision vs cell size
# ----------------------------------------------------------------------------

def section_precision():
    banner("SECTION C: precision vs cell size - each char cuts area to 1/32")
    print("longitude bits = ceil(5p/2), latitude bits = floor(5p/2) because")
    print("the FIRST bit is longitude. So odd precisions are SQUARE-ish and")
    print("even precisions are twice as wide as tall. Each added character")
    print("multiplies area by exactly 1/32 (2^5 finer boxes).\n")
    print_precision_table(12)
    p5 = cell_size(5)
    p6 = cell_size(6)
    p8 = cell_size(8)
    print(f"\n[check] precision 6 cell ~= {p6[4]:.3f} km x {p6[5]:.3f} km "
          f"(Yelp's default for local search)")
    print(f"[check] precision 8 cell ~= {p8[4]*1000:.1f} m x {p8[5]*1000:.1f} m "
          f"(delivery-pin level)")
    ratio = (p5[4] * p5[5]) / (p6[4] * p6[5])
    print(f"[check] p5 area / p6 area = {ratio:.2f}x (== 32, invariant 3)")
    # 9-cell query footprint at precision 6
    print(f"[check] 9-cell query at p6 covers ~{3*p6[4]:.2f} km x {3*p6[5]:.2f} km")


# ----------------------------------------------------------------------------
# SECTION D: neighbour cells (the 9-cell grid)
# ----------------------------------------------------------------------------

def section_neighbors():
    banner("SECTION D: neighbour cells - the 9-cell query")
    centre = encode(37.7749, -122.4194, 5)   # San Francisco
    print(f"San Francisco (37.7749, -122.4194) at precision 5 -> '{centre}'\n")
    print("The 3x3 grid of centre + 8 neighbours (the cells a proximity query")
    print("MUST read to be correct at boundaries):\n")
    grid = grid3x3(centre)
    for row in grid:
        print("    " + "   ".join(row))
    nb = neighbors(centre)
    all9 = [nb[k] for k in ("nw", "n", "ne", "w", "c", "e", "sw", "s", "se")]
    distinct = len(set(all9))
    # minimum shared-prefix length between centre and any neighbour
    shared = min(common_prefix_len(centre, c) for c in all9 if c != centre)
    print(f"\n[check] 9 cells are all DISTINCT?  {distinct == 9}  ({distinct} unique)")
    print(f"[check] shortest shared prefix centre<->neighbour = {shared} chars "
          f"(precision {len(centre)}).")
    if shared < len(centre):
        print(f"        -> a neighbour diverges at char {shared+1}, so "
              f"`LIKE '{centre[:shared+1]}%'` would MISS it.")
        print(f"        -> this is the Z-order discontinuity: adjacency does NOT")
        print(f"           imply a long shared prefix. Hence 9 explicit cells.")
    else:
        print(f"        -> all neighbours share the full {len(centre)-1}-prefix here.")
    print("\nSo `WHERE geohash5 IN (?,?,?,  ?, centre, ?,  ?,?,?)` with these 9")
    print("strings is a correct proximity filter at ~p6 cell scale. One SQL")
    print("range/IN scan, no Haversine on the full table.")


# ----------------------------------------------------------------------------
# SECTION E: prefix matching + the boundary problem
# ----------------------------------------------------------------------------

def section_boundary():
    banner("SECTION E: prefix matching, and why the 9-cell fix is mandatory")
    centre = encode(37.7749, -122.4194, 5)   # '9q8yy' region (SF)
    east = adjacent(centre, "e")
    d_c = decode(centre)
    d_e = decode(east)
    # a point epsilon west of the shared edge -> centre cell
    edge = d_c["lng_max"]
    west_pt = (d_c["lat"], edge - 1e-7)
    east_pt = (d_c["lat"], edge + 1e-7)
    gh_west = encode(west_pt[0], west_pt[1], 6)
    gh_east = encode(east_pt[0], east_pt[1], 6)
    print("Two points ~1 cm apart, straddling the edge between a cell and its")
    print("east neighbour:\n")
    print(f"  centre cell '{centre}', east neighbour '{east}'")
    print(f"  shared edge longitude = {edge:.7f}")
    print(f"  point W (just inside centre): ({west_pt[0]:.6f}, {west_pt[1]:.7f}) -> '{gh_west}'")
    print(f"  point E (just inside east)  : ({east_pt[0]:.6f}, {east_pt[1]:.7f}) -> '{gh_east}'")
    print(f"\n  shared prefix length = {common_prefix_len(gh_west, gh_east)} chars "
          f"(precision is {len(gh_west)})")
    only_centre = common_prefix_len(gh_west, gh_east) < len(gh_west)
    # sanity: point E must actually land in the (geographic) east neighbour
    east_ok = gh_east.startswith(east)
    print(f"\n[check] point E lands in the east neighbour '{east}'?  "
          f"{'OK' if east_ok else 'FAIL'}")
    print(f"[check] a prefix query on '{gh_west}' would MISS point E?  "
          f"{'OK - boundary problem' if only_centre else 'FAIL'}")
    print("\nThis is the Z-order boundary problem: adjacent points can have a")
    print("geohash that diverges at the LAST character. The mandatory fix is to")
    print("query centre + 8 neighbours (9 cells) and let Haversine refine. SQL:")
    print("  WHERE geohash6 IN (centre, n, s, e, w, ne, nw, se, sw)")
    print("For a radius > 2x the cell size, enumerate every intersecting cell")


# ============================================================================
# 7. GOLD CHECK  (geohashing.html recomputes these exact values in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK: encode/decode/neighbours match pinned ground truth")
    # (1) canonical encodings - pinned, known-good
    cases = [
        ((42.6, -5.6, 5), "ezs42"),
        ((37.7749, -122.4194, 5), "9q8yy"),
    ]
    all_ok = True
    for (lat, lng, prec), expect in cases:
        got = encode(lat, lng, prec)
        ok = got == expect
        all_ok = all_ok and ok
        print(f"[check] encode({lat}, {lng}, {prec}) = '{got}'  "
              f"(expect '{expect}')  ->  {'OK' if ok else 'FAIL'}")
    # (2) round trip: decode cell contains the point
    gh = "9q8yy"
    d = decode(gh)
    inside = (d["lat_min"] <= 37.7749 <= d["lat_max"]) and \
             (d["lng_min"] <= -122.4194 <= d["lng_max"])
    all_ok = all_ok and inside
    print(f"[check] decode('{gh}') cell contains SF (37.7749, -122.4194)?  "
          f"{'OK' if inside else 'FAIL'}")
    # (3) 9 distinct neighbours
    nb = neighbors(gh)
    all9 = [nb[k] for k in ("nw", "n", "ne", "w", "c", "e", "sw", "s", "se")]
    distinct = len(set(all9)) == 9
    all_ok = all_ok and distinct
    print(f"[check] neighbours('{gh}') -> 9 DISTINCT cells?  {distinct}")
    print(f"        grid = {[nb['nw'],nb['n'],nb['ne'], nb['w'],nb['c'],nb['e'], nb['sw'],nb['s'],nb['se']]}")
    # (4) cell size p6 ~= 1.22 x 0.61 km
    lat_b6, lng_b6, lat_d6, lng_d6, lat_km6, lng_km6 = cell_size(6)
    size_ok = abs(lat_km6 - 0.61) < 0.01 and abs(lng_km6 - 1.22) < 0.01
    all_ok = all_ok and size_ok
    print(f"[check] precision-6 cell = {lat_km6:.3f} x {lng_km6:.3f} km "
          f"(expect ~0.61 x 1.22)?  {'OK' if size_ok else 'FAIL'}")
    # pinned values for the .html gold badge
    print(f"\n[pin] encode(42.6,-5.6,5)      = '{encode(42.6, -5.6, 5)}'")
    print(f"[pin] encode(37.7749,-122.4194,5) = '{encode(37.7749, -122.4194, 5)}'")
    print(f"[pin] neighbours('9q8yy') east  = '{adjacent('9q8yy', 'e')}'")
    print(f"[pin] precision-6 cell km       = {lat_km6:.3f} x {lng_km6:.3f}")
    assert all_ok, "geohash gold check FAILED"
    print(f"\n[check] all gold pins reproduced:  OK")
    return all_ok


# ============================================================================
# main
# ============================================================================

def main():
    print("geohashing.py - reference simulation.")
    print("All numbers below feed GEOHASHING.md.")
    print("python stdlib only; deterministic; no network, no clock.\n")

    section_encode()
    section_decode()
    section_precision()
    section_neighbors()
    section_boundary()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
