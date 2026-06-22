"""
collections_basics.py — Bundle #3 (Phase 1).

GOAL (one line): show, by printing every value, how Python's five core
containers (list, tuple, dict, set, frozenset) differ in mutability, ordering,
uniqueness, and hashability — and why the hash/eq contract decides which of
them can be set elements or dict keys.

This is the GROUND TRUTH for COLLECTIONS_BASICS.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python collections_basics.py
"""

from __future__ import annotations

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers
# ----------------------------------------------------------------------------

def banner(title: str) -> None:
    """Print a clearly delimited section divider (the house style)."""
    print("\n" + BANNER)
    print(f"SECTION {title}")
    print(BANNER)


def check(description: str, condition: bool) -> None:
    """Assert an invariant and print a uniform [check] ... OK line."""
    assert condition, f"INVARIANT VIOLATED: {description}"
    print(f"[check] {description}: OK")


def is_hashable(obj: object) -> bool:
    """Return True if obj has a stable __hash__ (hash() does not raise)."""
    try:
        hash(obj)
        return True
    except TypeError:
        return False


def hash_or_raise(obj: object) -> str:
    """Return repr(hash(obj)) or the exact TypeError message raised."""
    try:
        return repr(hash(obj))
    except TypeError as exc:
        return f"TypeError: {exc}"


# ----------------------------------------------------------------------------
# Section A — the five containers + mutability/ordered/uniqueness table
# ----------------------------------------------------------------------------

def section_a_five_containers() -> None:
    banner("A — The five core containers: list, tuple, dict, set, frozenset")
    print("Python ships five everyday containers. Their traits — ordered,")
    print("mutable, unique, hashable — decide what each is good at. The table")
    print("below is the reference card; the checks beneath it PROVE each trait")
    print("by actually constructing and probing the type.\n")

    print(f"{'type':<12}{'ordered':<10}{'mutable':<10}{'unique':<10}{'hashable'}")
    print("-" * 50)
    rows = [
        ("list",      "yes", "yes", "no",   "no"),
        ("tuple",     "yes", "no",  "no",   "yes*"),
        ("dict",      "yes", "yes", "keys", "no"),
        ("set",       "no",  "yes", "yes",  "no"),
        ("frozenset", "no",  "no",  "yes",  "yes"),
    ]
    for name, ordered, mutable, unique, hashable in rows:
        print(f"{name:<12}{ordered:<10}{mutable:<10}{unique:<10}{hashable}")
    print("(* tuple is hashable only when ALL its elements are hashable.)\n")

    # ordered: list/tuple/dict preserve order; set/frozenset do not.
    check("list preserves order: [3,1,2][0] == 3", [3, 1, 2][0] == 3)
    check("tuple preserves order: (3,1,2)[0] == 3", (3, 1, 2)[0] == 3)

    # mutable: list/dict/set mutate in place; tuple/frozenset are fixed.
    lst = [1]
    lst.append(2)
    d = {"a": 1}
    d["a"] = 2
    s = {1}
    s.add(2)
    fs = frozenset({1})
    check("list is mutable (append works)", lst == [1, 2])
    check("dict is mutable (assign works)", d == {"a": 2})
    check("set is mutable (add works)", s == {1, 2})
    check("tuple length is fixed at construction", len((1, 2)) == 2)
    check("frozenset length is fixed at construction", len(fs) == 1)

    # unique: dict keys / set / frozenset dedup; list/tuple keep dups.
    check("set dedups: {1,1,2} == {1,2}", {1, 1, 2} == {1, 2})
    check("frozenset dedups: frozenset([1,1,2]) == frozenset({1,2})",
          frozenset([1, 1, 2]) == frozenset({1, 2}))
    check("dict keys dedup: {1:'a', 1:'b'} == {1:'b'}",
          {1: "a", 1: "b"} == {1: "b"})  # noqa: F601 - intentional dup demo
    check("list keeps dups: [1,1,2] has length 3", len([1, 1, 2]) == 3)


# ----------------------------------------------------------------------------
# Section B — the hashability contract: what hashes, what doesn't
# ----------------------------------------------------------------------------

def section_b_hashability_contract() -> None:
    banner("B — The hashability contract: what hashes, what doesn't")
    print("An object is HASHABLE if it has a __hash__ whose value never changes")
    print("during its lifetime AND it can be compared with __eq__. The contract")
    print("(docs.python.org datamodel.html#object.__hash__): 'objects which")
    print("compare equal have the same hash value.' Mutable containers are")
    print("unhashable because their value — and thus their hash — could change")
    print("after insertion, corrupting the hash table. (str/bytes hashes are")
    print("randomized per process via PYTHONHASHSEED; int/tuple/frozenset hashes")
    print("of ints are stable across runs.)\n")

    print(f"{'expression':<30}{'result'}")
    print("-" * 64)
    rows = [
        ("hash(1)", hash(1)),
        ("hash(1.0)", hash(1.0)),
        ("hash(True)", hash(True)),
        ("hash(1) == hash(1.0)", hash(1) == hash(1.0)),
        ("hash(True) == hash(1)", hash(True) == hash(1)),
        ("type(hash('hello'))", type(hash("hello"))),
        ("type(hash((1, 2)))", type(hash((1, 2)))),
        ("hash((1, 2))", hash((1, 2))),
        ("hash(frozenset({1, 2}))", hash(frozenset({1, 2}))),
        ("hash([1, 2])", hash_or_raise([1, 2])),
        ("hash({1: 2})", hash_or_raise({1: 2})),
        ("hash({1, 2})", hash_or_raise({1, 2})),
        ("hash((1, [2]))", hash_or_raise((1, [2]))),
    ]
    for label, value in rows:
        print(f"{label:<30}{value!r}")
    print()

    check("hash(1) == hash(1.0) (equal values -> equal hashes)",
          hash(1) == hash(1.0))
    check("hash(True) == hash(1) (bool == int -> equal hashes)",
          hash(True) == hash(1))
    check("hash((1,2)) is an int (tuples of hashables hash)",
          isinstance(hash((1, 2)), int))
    check("hash(frozenset({1,2})) is an int (frozenset hashes)",
          isinstance(hash(frozenset({1, 2})), int))
    check("list is unhashable (mutable)", not is_hashable([1, 2]))
    check("dict is unhashable (mutable)", not is_hashable({1: 2}))
    check("set is unhashable (mutable)", not is_hashable({1, 2}))
    check("tuple of unhashable is unhashable: (1,[2])", not is_hashable((1, [2])))
    check("tuple of hashables is hashable: (1,2)", is_hashable((1, 2)))

    # The contract's payoff: hashability gates set-membership & dict-key use.
    # frozenset (hashable) CAN be a set element / dict key; set CANNOT.
    print("Consequence: hashability gates set-membership & dict-key use.\n")
    fs = frozenset({1, 2})
    print(f"frozenset({{1,2}}) as a set element: {{fs}} -> { {fs} }")
    print(f"frozenset({{1,2}}) as a dict key: {{fs:'v'}} -> { {fs: 'v'} }")
    check("frozenset can be a set element (it is hashable)",
          frozenset({1, 2}) in {frozenset({1, 2})})
    check("frozenset can be a dict key (it is hashable)",
          {frozenset({1, 2}): "v"}[frozenset({1, 2})] == "v")

    # set (unhashable) as a set element -> TypeError at construction.
    try:
        _ = { {1, 2} }  # set containing a set -> raises TypeError
    except TypeError as exc:
        set_of_set = f"TypeError: {exc}"
    else:  # pragma: no cover - should never happen
        set_of_set = "no error (unexpected!)"
    print("set {1,2} as a set element: { {1, 2} } -> " + set_of_set)
    check("set cannot be a set element (it is unhashable)",
          set_of_set.startswith("TypeError"))


# ----------------------------------------------------------------------------
# Section C — dict ordering & equality
# ----------------------------------------------------------------------------

def section_c_dict_ordering_and_equality() -> None:
    banner("C — Dict ordering & equality: insertion order since 3.7")
    print("Since Python 3.7 (CPython 3.6 as an implementation detail), dict")
    print("preserves INSERTION order: list(d.keys()) yields keys in the order")
    print("they were first added. Updating a value does NOT move the key;")
    print("deleting then re-inserting a key appends it to the END.\n")

    d = {"c": 1, "a": 2, "b": 3}
    print(f"d = {d}")
    print(f"list(d.keys())            = {list(d.keys())}")
    print(f"list(d.values())          = {list(d.values())}")
    print(f"list(d.items())           = {list(d.items())}")
    d["a"] = 99
    print("d['a'] = 99  (update existing key)")
    print(f"list(d.keys())            = {list(d.keys())}  (order unchanged)")
    del d["c"]
    d["c"] = 100
    print("del d['c']; d['c'] = 100  (delete + re-insert at end)")
    print(f"list(d.keys())            = {list(d.keys())}  ('c' moved to end)")
    print()

    check("dict preserves insertion order: keys == [c,a,b]",
          list({"c": 1, "a": 2, "b": 3}.keys()) == ["c", "a", "b"])
    check("updating a value does not reorder keys",
          list(d.keys()) == ["a", "b", "c"])
    # Equality on dicts is order-INSENSITIVE (values compared, not order).
    check("dict == is order-insensitive: {a:1,b:2} == {b:2,a:1}",
          {"a": 1, "b": 2} == {"b": 2, "a": 1})
    # 1 and 1.0 are the SAME dict key (equal hash + equal value).
    check("1 and 1.0 are the same dict key (equal hash + eq)",
          {1: "int", 1.0: "float"} == {1: "float"})  # noqa: F601 - intentional


# ----------------------------------------------------------------------------
# Section D — set algebra: | & - ^ and frozenset-as-element
# ----------------------------------------------------------------------------

def section_d_set_algebra() -> None:
    banner("D — Set algebra: | & - ^ and frozenset-as-element")
    print("Sets implement mathematical set algebra: union |, intersection &,")
    print("difference -, symmetric_difference ^. Each returns a NEW set; the")
    print("operands are unchanged. `in` membership is O(1) average (hash-table")
    print("lookup) vs O(n) for a list (linear scan). frozenset, being immutable")
    print("& hashable, can be a set ELEMENT or dict KEY; set cannot.\n")

    a = {1, 2, 3, 4}
    b = {3, 4, 5, 6}
    print(f"a = {a}")
    print(f"b = {b}")
    print(f"a | b  (union)             = {a | b}")
    print(f"a & b  (intersection)      = {a & b}")
    print(f"a - b  (difference)        = {a - b}")
    print(f"a ^ b  (symmetric diff)    = {a ^ b}")
    print(f"a after operations         = {a}  (unchanged)")
    print()

    check("union |", a | b == {1, 2, 3, 4, 5, 6})
    check("intersection &", a & b == {3, 4})
    check("difference -", a - b == {1, 2})
    check("symmetric_difference ^", a ^ b == {1, 2, 5, 6})
    check("set ops do not mutate operands", a == {1, 2, 3, 4})

    # membership semantics: 1 and 1.0 are the same element (hash + eq).
    s = {1, 2, 3}
    print(f"s = {s}")
    print(f"1 in s      = {1 in s}")
    print(f"1.0 in s    = {1.0 in s}  (1 == 1.0 -> same element)")
    print(f"len({{1, 1.0, 2}}) = {len({1, 1.0, 2})}  (1 and 1.0 collapse)")
    print()
    check("1 in {1,2,3} is True (O(1) avg hash lookup)", 1 in {1, 2, 3})
    check("1.0 in {1,2,3} is True (1 == 1.0, equal hashes)",
          1.0 in {1, 2, 3})
    check("{1, 1.0, 2} has length 2 (1 and 1.0 collapse)",
          len({1, 1.0, 2}) == 2)

    # frozenset as set element / dict key.
    fs1 = frozenset({1, 2})
    fs2 = frozenset({3, 4})
    set_of_fs = {fs1, fs2}
    dict_keyed_by_fs = {fs1: "pair", fs2: "pair"}
    print("frozenset is hashable, so it can be a set element / dict key:")
    print(f"{{fs1, fs2}}              = {set_of_fs}")
    print(f"{{fs1:'pair', fs2:'pair'}} = {dict_keyed_by_fs}")
    print()
    check("frozenset can be a set element", fs1 in {fs1, fs2})
    check("frozenset can be a dict key",
          dict_keyed_by_fs[fs1] == "pair")


# ----------------------------------------------------------------------------
# Section E — which container wins when? (decision table)
# ----------------------------------------------------------------------------

def section_e_decision_table() -> None:
    banner("E — Which container wins when? (decision table)")
    print("Pick the container from the NEED, not from habit.\n")

    print(f"{'if you need...':<36}{'reach for':<22}{'why'}")
    print("-" * 82)
    decisions = [
        ("ordered + index access",        "list / tuple",   "O(1) by position"),
        ("immutable ordered sequence",    "tuple",          "hashable; fixed; safe default"),
        ("key -> value mapping",          "dict",           "O(1) lookup by key"),
        ("uniqueness + fast membership",  "set",            "O(1) avg `in`; auto-dedup"),
        ("a set of sets / hashable set",  "frozenset",      "immutable -> hashable"),
    ]
    for need, pick, why in decisions:
        print(f"{need:<36}{pick:<22}{why}")
    print()

    # Worked example: dedup a list while keeping FIRST-seen order.
    raw = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5]
    deduped = list(dict.fromkeys(raw))
    print(f"raw     = {raw}")
    print(f"deduped = {deduped}  (dict.fromkeys: order + uniqueness)")
    print()
    check("dict.fromkeys dedups AND preserves first-seen order",
          list(dict.fromkeys([3, 1, 4, 1, 5])) == [3, 1, 4, 5])

    # Worked example: membership — set vs list agree on the answer.
    big_list = list(range(1000))
    big_set = set(range(1000))
    check("'in set'  returns True for a present value", 999 in big_set)
    check("'in list' returns True for a present value", 999 in big_list)
    check("set and list agree on membership (same answer)",
          (999 in big_list) == (999 in big_set))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("collections_basics.py — Phase 1 bundle #3.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    section_a_five_containers()
    section_b_hashability_contract()
    section_c_dict_ordering_and_equality()
    section_d_set_algebra()
    section_e_decision_table()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
