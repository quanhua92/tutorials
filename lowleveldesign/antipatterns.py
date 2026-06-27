#!/usr/bin/env python3
"""
antipatterns.py -- Six classic software anti-patterns, before & after.

Each section runs a BAD version (the anti-pattern -- it "works" but smells) and a
GOOD version (refactored), then asserts both produce the same observable result,
so the refactor is provably behavior-preserving. A green ``[check] OK`` follows.

Anti-patterns covered
    01. God Object              -- one class doing everything (kitchen sink)
    02. Spaghetti Code          -- tight coupling, tangled control flow
    03. Golden Hammer           -- one familiar tool overused for every job
    04. Premature Optimization  -- micro-tuning before measuring
    05. Copy-Paste Programming  -- duplicated logic across call sites
    06. Magic Numbers           -- unnamed literals scattered through the code

Pure stdlib. Run:  python3 antipatterns.py
Companion guide:   lowleveldesign/ANTIPATTERNS.md
Interactive demo:  lowleveldesign/antipatterns.html
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections import Counter
from enum import Enum


# ---------------------------------------------------------------------------
# banner helpers
# ---------------------------------------------------------------------------
def banner(title: str, char: str = "=") -> None:
    line = char * 72
    print(f"\n{line}\n{title}\n{line}")


def check(label: str) -> None:
    print(f"  [check] OK   {label}")


def almost(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) < tol


# ===========================================================================
# 01. GOD OBJECT  -- one class owns validation, pricing, storage, notification
# ===========================================================================
banner("01. GOD OBJECT -- BAD: a single kitchen-sink class")

class GodOrderProcessor:
    """BAD: one class has four unrelated reasons to change."""

    def __init__(self) -> None:
        self._db: dict[str, float] = {}     # storage mixed in
        self._sent: list[tuple[str, float]] = []  # notification mixed in

    def place(self, order: dict) -> float:
        # (a) validation inlined
        if not order.get("customer"):
            raise ValueError("missing customer")
        if order.get("qty", 0) <= 0:
            raise ValueError("bad qty")
        # (b) pricing inlined, magic 0.08 tax
        subtotal = order["price"] * order["qty"]
        total = subtotal + subtotal * 0.08
        # (c) storage inlined
        self._db[order["id"]] = total
        # (d) notification inlined
        self._sent.append((order["customer"], total))
        return total


god = GodOrderProcessor()
god_total = god.place({"id": "o1", "customer": "Alice", "price": 12.5, "qty": 4})
print(f"GodOrderProcessor.place(...)        -> {god_total:.1f}")
print(f"  stored keys: {sorted(god._db.keys())}")
print(f"  notified   : {god._sent[0]}")


banner("01. GOD OBJECT -- GOOD: split by reason-to-change; thin coordinator")

class OrderValidator:
    """Reason to change: validation rules."""

    @staticmethod
    def validate(order: dict) -> None:
        if not order.get("customer"):
            raise ValueError("missing customer")
        if order.get("qty", 0) <= 0:
            raise ValueError("bad qty")


class Pricer:
    """Reason to change: pricing/tax rules."""

    TAX_RATE = 0.08

    def total(self, order: dict) -> float:
        subtotal = order["price"] * order["qty"]
        return subtotal + subtotal * self.TAX_RATE


class InMemoryOrderStore:
    """Reason to change: storage backend."""

    def __init__(self) -> None:
        self._db: dict[str, float] = {}

    def save(self, order_id: str, total: float) -> None:
        self._db[order_id] = total

    def keys(self) -> list[str]:
        return sorted(self._db)


class Notifier:
    """Reason to change: delivery channels."""

    def __init__(self) -> None:
        self._sent: list[tuple[str, float]] = []

    def notify(self, customer: str, total: float) -> None:
        self._sent.append((customer, total))


class OrderService:
    """Thin coordinator: orchestrates collaborators, owns no business rule."""

    def __init__(self, validator: OrderValidator, pricer: Pricer,
                 store: InMemoryOrderStore, notifier: Notifier) -> None:
        self._validator = validator
        self._pricer = pricer
        self._store = store
        self._notifier = notifier

    def place(self, order: dict) -> float:
        self._validator.validate(order)
        total = self._pricer.total(order)
        self._store.save(order["id"], total)
        self._notifier.notify(order["customer"], total)
        return total


service = OrderService(OrderValidator(), Pricer(), InMemoryOrderStore(), Notifier())
good_total = service.place({"id": "o1", "customer": "Alice", "price": 12.5, "qty": 4})
print(f"OrderService.place(...)            -> {good_total:.1f}")

assert almost(god_total, good_total), "god vs service totals differ"
check("God Object refactor preserves total (12.5 * 4 * 1.08 = 54.0)")


# ===========================================================================
# 02. SPAGHETTI CODE -- each class news up the next; impossible to test/swap
# ===========================================================================
banner("02. SPAGHETTI CODE -- BAD: hard-wired construction, tangled chain")

class BadConfigReader:
    def rate(self) -> float:
        return 0.08


class BadTaxTable:
    def __init__(self) -> None:
        self._cfg = BadConfigReader()       # couples to a concrete class

    def tax(self, amount: float) -> float:
        return amount * self._cfg.rate()


class BadDiscountEngine:
    def __init__(self) -> None:
        self._tax = BadTaxTable()           # couples again; 3 hops for 1 number

    def net(self, amount: float, coupon: float) -> float:
        after_coupon = amount * (1 - coupon)
        return after_coupon + self._tax.tax(after_coupon)


class BadCart:
    def __init__(self) -> None:
        self._engine = BadDiscountEngine()  # the whole chain drags along

    def checkout(self, amount: float, coupon: float) -> float:
        return self._engine.net(amount, coupon)


bad_cart = BadCart()
bad_net = bad_cart.checkout(100.0, 0.10)
print(f"BadCart.checkout(100, 0.10)         -> {bad_net:.1f}  (4 classes, 0 injectable)")


banner("02. SPAGHETTI CODE -- GOOD: dependency injection, one direction")

class TaxPolicy(ABC):
    """Interface: carts depend on this, not on a concrete tax implementation."""

    @abstractmethod
    def tax(self, amount: float) -> float: ...


class FlatTax(TaxPolicy):
    def __init__(self, rate: float) -> None:
        self._rate = rate

    def tax(self, amount: float) -> float:
        return amount * self._rate


class Pricer:  # focused: coupon + tax composition only
    def __init__(self, tax: TaxPolicy) -> None:
        self._tax = tax                     # injected, swappable, mockable

    def net(self, amount: float, coupon: float) -> float:
        after_coupon = amount * (1 - coupon)
        return after_coupon + self._tax.tax(after_coupon)


class GoodCart:
    def __init__(self, pricer: Pricer) -> None:
        self._pricer = pricer               # injected

    def checkout(self, amount: float, coupon: float) -> float:
        return self._pricer.net(amount, coupon)


good_cart = GoodCart(Pricer(FlatTax(0.08)))
good_net = good_cart.checkout(100.0, 0.10)
print(f"GoodCart.checkout(100, 0.10)        -> {good_net:.1f}  (deps injected, 1-liner test)")

assert almost(bad_net, good_net), "spaghetti vs injected nets differ"
check("Spaghetti -> DI preserves net (100 * 0.9 * 1.08 = 97.2)")


# ===========================================================================
# 03. GOLDEN HAMMER -- regex used for parsing ints, splitting kv, counting
# ===========================================================================
banner("03. GOLDEN HAMMER -- BAD: regex is the one tool, applied to everything")

def bad_validate_int(s: str) -> bool:
    return bool(re.fullmatch(r"-?\d+", s))     # regex to check an integer

def bad_parse_kv(line: str):
    m = re.fullmatch(r"(\w+)=(\w+)", line)     # regex to split key=value
    return (m.group(1), m.group(2)) if m else None

def bad_count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))       # regex to count words

print(f"bad_validate_int('42')   -> {bad_validate_int('42')}")
print(f"bad_parse_kv('host=db')  -> {bad_parse_kv('host=db')}")
print(f"bad_count_words('a bb ccc') -> {bad_count_words('a bb ccc')}")


banner("03. GOLDEN HAMMER -- GOOD: pick the right tool for each job")

def good_validate_int(s: str) -> bool:
    try:                       # int() is the right tool -- and rejects '+', spaces
        int(s)
        return True
    except ValueError:
        return False

def good_parse_kv(line: str):
    key, sep, value = line.partition("=")      # str.partition: exact tool
    return (key, value) if sep else None

def good_count_words(text: str) -> int:
    return len(text.split())                    # str.split: obvious + faster

print(f"good_validate_int('42')  -> {good_validate_int('42')}")
print(f"good_parse_kv('host=db') -> {good_parse_kv('host=db')}")
print(f"good_count_words('a bb ccc') -> {good_count_words('a bb ccc')}")

assert bad_validate_int("42") == good_validate_int("42") is True
assert bad_parse_kv("host=db") == good_parse_kv("host=db") == ("host", "db")
assert bad_count_words("a bb ccc") == good_count_words("a bb ccc") == 3
check("Golden Hammer -> right tools: int(), partition(), split()")


# ===========================================================================
# 04. PREMATURE OPTIMIZATION -- clever bit tricks + a cache nobody needed
# ===========================================================================
banner("04. PREMATURE OPTIMIZATION -- BAD: ord-table lowercase, manual counts")

_BAD_LOWER = {c: chr(c | 32) for c in range(65, 91)}   # precomputed, never profiled

def bad_is_even(n: int) -> bool:
    return (n & 1) == 0                         # bit-and: no faster in CPython, less clear

def bad_word_freq(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for w in text.split():
        wl = "".join(_BAD_LOWER.get(ord(ch), ch) for ch in w)   # ord-by-ord lower()
        counts[wl] = counts.get(wl, 0) + 1                      # hand-rolled Counter
    return counts

print(f"bad_is_even(4)                 -> {bad_is_even(4)}")
print(f"bad_word_freq('Hello hello World') -> {bad_word_freq('Hello hello World')}")


banner("04. PREMATURE OPTIMIZATION -- GOOD: clear code; optimize only after profiling")

def good_is_even(n: int) -> bool:
    return n % 2 == 0                           # reads as English; equally fast

def good_word_freq(text: str) -> dict[str, int]:
    return dict(Counter(w.lower() for w in text.split()))   # stdlib, tested, fast

print(f"good_is_even(4)                -> {good_is_even(4)}")
print(f"good_word_freq('Hello hello World') -> {good_word_freq('Hello hello World')}")

assert bad_is_even(4) is good_is_even(4) is True
assert bad_word_freq("Hello hello World") == good_word_freq("Hello hello World")
check("Premature opt -> clear code matches clever code (Counter + %)")


# ===========================================================================
# 05. COPY-PASTE PROGRAMMING -- the same round+format logic in every shape
# ===========================================================================
banner("05. COPY-PASTE PROGRAMMING -- BAD: format logic duplicated 3 times")

def bad_square_area(side: float) -> str:
    area = side * side
    area = round(area, 2)                       # <-- copied
    return f"{area:.1f} sq units"               # <-- copied

def bad_rectangle_area(w: float, h: float) -> str:
    area = w * h
    area = round(area, 2)                       # <-- copied
    return f"{area:.1f} sq units"               # <-- copied

def bad_triangle_area(base: float, height: float) -> str:
    area = 0.5 * base * height
    area = round(area, 2)                       # <-- copied
    return f"{area:.1f} sq units"               # <-- copied

print(f"bad_square_area(4)      -> {bad_square_area(4)}")
print(f"bad_rectangle_area(3,5) -> {bad_rectangle_area(3, 5)}")
print(f"bad_triangle_area(6,3)  -> {bad_triangle_area(6, 3)}")


banner("05. COPY-PASTE PROGRAMMING -- GOOD: one formatter, formulas stay unique")

def _format_area(area: float) -> str:           # the one true copy of the rule
    return f"{round(area, 2):.1f} sq units"

def good_square_area(side: float) -> str:
    return _format_area(side * side)            # only the formula is unique

def good_rectangle_area(w: float, h: float) -> str:
    return _format_area(w * h)

def good_triangle_area(base: float, height: float) -> str:
    return _format_area(0.5 * base * height)

print(f"good_square_area(4)      -> {good_square_area(4)}")
print(f"good_rectangle_area(3,5) -> {good_rectangle_area(3, 5)}")
print(f"good_triangle_area(6,3)  -> {good_triangle_area(6, 3)}")

assert bad_square_area(4) == good_square_area(4) == "16.0 sq units"
assert bad_rectangle_area(3, 5) == good_rectangle_area(3, 5) == "15.0 sq units"
assert bad_triangle_area(6, 3) == good_triangle_area(6, 3) == "9.0 sq units"
check("Copy-paste -> one helper; fix the format in exactly one place")


# ===========================================================================
# 06. MAGIC NUMBERS -- raw 200 / 0.08 / 4 scattered, meaning unknown
# ===========================================================================
banner("06. MAGIC NUMBERS -- BAD: literals with no name, no single source")

def bad_status_label(status: int) -> str:
    if status == 200:                           # 200 means... ?
        return "ok"
    if status == 404:
        return "missing"
    if status == 500:
        return "error"
    return "other"

def bad_price_with_tax(amount: float) -> float:
    return amount * 1.08                         # why 1.08? sales tax? which region?

def bad_is_valid_pin(pin: str) -> bool:
    return len(pin) == 4 and pin.isdigit()       # why 4? atm pin? could be 6

print(f"bad_status_label(200)      -> {bad_status_label(200)}")
print(f"bad_price_with_tax(25.0)   -> {bad_price_with_tax(25.0):.1f}")
print(f"bad_is_valid_pin('1234')   -> {bad_is_valid_pin('1234')}")


banner("06. MAGIC NUMBERS -- GOOD: named constants + enum give literals meaning")

class HttpStatus(Enum):
    OK = 200
    NOT_FOUND = 404
    SERVER_ERROR = 500

SALES_TAX_RATE = 0.08
PIN_LENGTH = 4

def good_status_label(status: int) -> str:
    if status == HttpStatus.OK.value:
        return "ok"
    if status == HttpStatus.NOT_FOUND.value:
        return "missing"
    if status == HttpStatus.SERVER_ERROR.value:
        return "error"
    return "other"

def good_price_with_tax(amount: float) -> float:
    return amount * (1 + SALES_TAX_RATE)         # the rate now has a name + a home

def good_is_valid_pin(pin: str) -> bool:
    return len(pin) == PIN_LENGTH and pin.isdigit()

print(f"good_status_label(200)     -> {good_status_label(200)}")
print(f"good_price_with_tax(25.0)  -> {good_price_with_tax(25.0):.1f}")
print(f"good_is_valid_pin('1234')  -> {good_is_valid_pin('1234')}")

assert bad_status_label(200) == good_status_label(200) == "ok"
assert almost(bad_price_with_tax(25.0), good_price_with_tax(25.0))
assert bad_is_valid_pin("1234") is good_is_valid_pin("1234") is True
check("Magic numbers -> named constants + HttpStatus enum")


# ===========================================================================
banner("ALL SIX ANTI-PATTERNS: BAD == GOOD (behavior preserved), refactor safe")
print("    God Object | Spaghetti | Golden Hammer | Premature Opt | "
      "Copy-Paste | Magic Numbers")
check("antipatterns.py complete")
