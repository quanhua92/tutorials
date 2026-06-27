#!/usr/bin/env python3
"""
design_framework.py -- SOLID principles, design process, and tradeoff matrix.

A teaching ground-truth for the low-level-design interview framework. Three parts:

  PART I  -- SOLID before/after. For each of S, O, L, I, D a BAD smell and the
             GOOD refactor, with an assertion that behavior is preserved (or, for
             LSP, that the contract violation is removed). A green [check] OK
             follows each principle.
  PART II -- The 5-phase design process checklist (Understand Requirements ->
             Identify Entities -> Define Relationships -> Apply Patterns ->
             Review Tradeoffs) demonstrated on a Notification Service.
  PART III-- A weighted tradeoff analysis matrix that ranks design options
             (Email vs SMS vs Push) across cost, latency, reliability, reachability.

Pure stdlib. Run:  python3 design_framework.py
Companion guide:   lowleveldesign/DESIGN_FRAMEWORK.md
Interactive demo:  lowleveldesign/design_framework.html
"""

from __future__ import annotations

from abc import ABC, abstractmethod


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
banner("PART I  --  SOLID: five principles, each BAD vs GOOD")
print("    Each section shows a violation, then the refactor, then asserts the")
print("    observable behavior is preserved (LSP asserts the contract is restored).")
# ===========================================================================


# ===========================================================================
# S. SINGLE RESPONSIBILITY
# ===========================================================================
banner("S. SINGLE RESPONSIBILITY (SRP) -- BAD: one class, three jobs")

class BadEmployee:
    """BAD: payroll + persistence + presentation all change in the same class."""

    def __init__(self, name: str, hours: float, rate: float) -> None:
        self.name, self.hours, self.rate = name, hours, rate

    def calculate_pay(self) -> float:
        return self.hours * self.rate                     # payroll rule

    def save(self, db: dict[str, float]) -> None:
        db[self.name] = self.calculate_pay()              # storage rule

    def format_report(self) -> str:
        return f"{self.name}: ${self.calculate_pay():.1f}"  # presentation rule


db: dict[str, float] = {}
bad_emp = BadEmployee("Alice", 40, 25.0)
print(f"BadEmployee.calculate_pay()  -> {bad_emp.calculate_pay():.1f}")
bad_emp.save(db)
print(f"BadEmployee.save(db)         -> db={db}")
print(f"BadEmployee.format_report()  -> {bad_emp.format_report()}")


banner("S. SINGLE RESPONSIBILITY (SRP) -- GOOD: one reason to change per class")

class Employee:
    """Holds only employee data. Reason to change: data shape."""

    def __init__(self, name: str, hours: float, rate: float) -> None:
        self.name, self.hours, self.rate = name, hours, rate


class PayCalculator:
    """Reason to change: payroll rules."""

    def pay(self, emp: Employee) -> float:
        return emp.hours * emp.rate


class EmployeeRepository:
    """Reason to change: storage backend."""

    def __init__(self) -> None:
        self._db: dict[str, float] = {}

    def save(self, emp: Employee, amount: float) -> None:
        self._db[emp.name] = amount

    def snapshot(self) -> dict[str, float]:
        return dict(self._db)


class PayReporter:
    """Reason to change: presentation/format."""

    def line(self, emp: Employee, amount: float) -> str:
        return f"{emp.name}: ${amount:.1f}"


calc = PayCalculator()
repo = EmployeeRepository()
reporter = PayReporter()
emp = Employee("Alice", 40, 25.0)
good_pay = calc.pay(emp)
repo.save(emp, good_pay)
print(f"PayCalculator.pay(emp)       -> {good_pay:.1f}")
print(f"EmployeeRepository.save(..)  -> db={repo.snapshot()}")
print(f"PayReporter.line(emp, pay)   -> {reporter.line(emp, good_pay)}")

assert almost(bad_emp.calculate_pay(), good_pay), "SRP pay mismatch"
check("SRP split preserves pay (40 * 25.0 = 1000.0)")


# ===========================================================================
# O. OPEN/CLOSED
# ===========================================================================
banner("O. OPEN/CLOSED (OCP) -- BAD: add a tier = edit the function")

def bad_discount(amount: float, tier: str) -> float:
    if tier == "regular":                                # edit here for every new tier
        return amount
    if tier == "vip":
        return amount * 0.90
    if tier == "wholesale":
        return amount * 0.80
    return amount

print(f"bad_discount(100, 'regular')   -> {bad_discount(100, 'regular'):.1f}")
print(f"bad_discount(100, 'vip')       -> {bad_discount(100, 'vip'):.1f}")
print(f"bad_discount(100, 'wholesale') -> {bad_discount(100, 'wholesale'):.1f}")


banner("O. OPEN/CLOSED (OCP) -- GOOD: new tier = new class, no edit to engine")

class DiscountTier(ABC):
    """Extension point: a new tier is a new subclass; the engine never changes."""

    @abstractmethod
    def apply(self, amount: float) -> float: ...


class RegularTier(DiscountTier):
    def apply(self, amount: float) -> float:
        return amount


class VipTier(DiscountTier):
    def apply(self, amount: float) -> float:
        return amount * 0.90


class WholesaleTier(DiscountTier):
    def apply(self, amount: float) -> float:
        return amount * 0.80


class StudentTier(DiscountTier):                         # added WITHOUT touching engine
    def apply(self, amount: float) -> float:
        return amount * 0.85


class DiscountEngine:
    """Closed for modification: it only knows the DiscountTier interface."""

    def price(self, amount: float, tier: DiscountTier) -> float:
        return tier.apply(amount)


engine = DiscountEngine()
tiers = [RegularTier(), VipTier(), WholesaleTier(), StudentTier()]
prices = {t.__class__.__name__: engine.price(100, t) for t in tiers}
for name, p in prices.items():
    print(f"engine.price(100, {name:<13}) -> {p:.1f}")

assert almost(bad_discount(100, "regular"), engine.price(100, RegularTier()))
assert almost(bad_discount(100, "vip"), engine.price(100, VipTier()))
assert almost(bad_discount(100, "wholesale"), engine.price(100, WholesaleTier()))
check("OCP engine matches if/elif; StudentTier added with zero edits to engine")


# ===========================================================================
# L. LISKOV SUBSTITUTION
# ===========================================================================
banner("L. LISKOV SUBSTITUTION (LSP) -- BAD: Square breaks Rectangle's contract")

class BadRectangle:
    """Contract: width and height are independent dimensions."""

    def __init__(self, w: float, h: float) -> None:
        self._w, self._h = w, h

    @property
    def width(self) -> float:
        return self._w

    @width.setter
    def width(self, v: float) -> None:
        self._w = v                                      # only width moves

    @property
    def height(self) -> float:
        return self._h

    @height.setter
    def height(self, v: float) -> None:
        self._h = v                                      # only height moves

    def area(self) -> float:
        return self._w * self._h


class BadSquare(BadRectangle):
    """Overrides setters so both sides move together -- breaks the parent contract."""

    @property
    def width(self) -> float:
        return self._w

    @width.setter
    def width(self, v: float) -> None:
        self._w = self._h = v                            # height secretly changes too

    @property
    def height(self) -> float:
        return self._h

    @height.setter
    def height(self, v: float) -> None:
        self._w = self._h = v


def resize_to(rect: BadRectangle, w: float, h: float) -> float:
    """A client of BadRectangle: set width then height, expect area == w * h."""
    rect.width = w
    rect.height = h
    return rect.area()

rect = BadRectangle(2, 3)
print(f"resize_to(BadRectangle, 5, 10) -> area={resize_to(rect, 5, 10):.1f}   (5*10=50, OK)")
sq = BadSquare(2, 2)                                     # a BadSquare IS-A BadRectangle ...
print(f"resize_to(BadSquare,   5, 10) -> area={resize_to(sq, 5, 10):.1f}   (expected 50, got 100! LSP BROKEN)")


banner("L. LISKOV SUBSTITUTION (LSP) -- GOOD: shared Shape, no false is-a")

class Shape(ABC):
    """Anything with an area. Square and Rectangle are siblings, not parent/child."""

    @abstractmethod
    def area(self) -> float: ...


class GoodRectangle(Shape):
    def __init__(self, w: float, h: float) -> None:
        self._w, self._h = w, h

    def resize(self, w: float, h: float) -> None:
        self._w, self._h = w, h                          # both dimensions, explicit

    def area(self) -> float:
        return self._w * self._h


class GoodSquare(Shape):
    def __init__(self, side: float) -> None:
        self._side = side

    def resize(self, side: float) -> None:
        self._side = side                                # one dimension, by design

    def area(self) -> float:
        return self._side * self._side


def total_area(shapes: list[Shape]) -> float:
    """Every Shape subclass is substitutable here: only area() is used."""
    return sum(s.area() for s in shapes)

shapes = [GoodRectangle(5, 10), GoodSquare(7), GoodRectangle(2, 3)]
for s in shapes:
    print(f"{s.__class__.__name__:<14}.area() -> {s.area():.1f}")
print(f"total_area(shapes)              -> {total_area(shapes):.1f}")

assert GoodRectangle(5, 10).area() == 50.0
assert GoodSquare(7).area() == 49.0
assert resize_to(BadRectangle(2, 3), 5, 10) == 50.0      # rectangle alone is still fine
check("LSP fix: GoodSquare no longer pretends to be a Rectangle; Shape is the safe abstraction")


# ===========================================================================
# I. INTERFACE SEGREGATION
# ===========================================================================
banner("I. INTERFACE SEGREGATION (ISP) -- BAD: fat interface forces dead stubs")

class BadWorker(ABC):
    """One interface for everything that works, eats, and sleeps."""

    @abstractmethod
    def work(self) -> str: ...

    @abstractmethod
    def eat(self) -> str: ...

    @abstractmethod
    def sleep(self) -> str: ...


class BadHuman(BadWorker):
    def work(self) -> str:
        return "coding"

    def eat(self) -> str:
        return "lunch"

    def sleep(self) -> str:
        return "zzz"


class BadRobot(BadWorker):
    def work(self) -> str:
        return "beep boop, working"

    def eat(self) -> str:
        raise NotImplementedError("robots do not eat")   # forced dead stub

    def sleep(self) -> str:
        raise NotImplementedError("robots do not sleep")  # forced dead stub

robot = BadRobot()
print(f"BadRobot.work() -> {robot.work()}")
try:
    robot.eat()
except NotImplementedError as exc:
    print(f"BadRobot.eat()  -> NotImplementedError: {exc}")


banner("I. INTERFACE SEGREGATION (ISP) -- GOOD: clients depend only on what they use")

class Workable(ABC):
    @abstractmethod
    def work(self) -> str: ...


class Eatable(ABC):
    @abstractmethod
    def eat(self) -> str: ...


class Sleepable(ABC):
    @abstractmethod
    def sleep(self) -> str: ...


class GoodHuman(Workable, Eatable, Sleepable):
    def work(self) -> str:
        return "coding"

    def eat(self) -> str:
        return "lunch"

    def sleep(self) -> str:
        return "zzz"


class GoodRobot(Workable):                               # implements ONLY what it can do
    def work(self) -> str:
        return "beep boop, working"


def run_shift(worker: Workable) -> str:                  # depends on the slim interface
    return worker.work()

print(f"run_shift(GoodHuman) -> {run_shift(GoodHuman())}")
print(f"run_shift(GoodRobot) -> {run_shift(GoodRobot())}")

assert run_shift(GoodHuman()) == "coding"
assert run_shift(GoodRobot()) == "beep boop, working"
assert BadHuman().work() == GoodHuman().work()
check("ISP: GoodRobot implements Workable only; no dead eat()/sleep() stubs")


# ===========================================================================
# D. DEPENDENCY INVERSION
# ===========================================================================
banner("D. DEPENDENCY INVERSION (DIP) -- BAD: high-level depends on low-level concrete")

class BadEmailSender:
    """Low-level detail: how a message leaves the building."""

    def send(self, message: str) -> str:
        return f"emailed: {message}"


class BadNotifier:
    """High-level policy, but it news up the concrete sender itself."""

    def __init__(self) -> None:
        self._sender = BadEmailSender()                  # hard-wired, untestable

    def notify(self, message: str) -> str:
        return self._sender.send(message)

print(f"BadNotifier.notify('deploy ok') -> {BadNotifier().notify('deploy ok')}")


banner("D. DEPENDENCY INVERSION (DIP) -- GOOD: both depend on an abstraction, injected")

class MessageSender(ABC):
    """Abstraction owned by the high-level policy."""

    @abstractmethod
    def send(self, message: str) -> str: ...


class EmailSender(MessageSender):
    def send(self, message: str) -> str:
        return f"emailed: {message}"


class SmsSender(MessageSender):
    def send(self, message: str) -> str:
        return f"sms: {message}"


class GoodNotifier:
    """High-level policy depends on the MessageSender abstraction, not a concrete."""

    def __init__(self, sender: MessageSender) -> None:
        self._sender = sender                            # injected; swappable; mockable

    def notify(self, message: str) -> str:
        return self._sender.send(message)

print(f"GoodNotifier(Email).notify('deploy ok') -> {GoodNotifier(EmailSender()).notify('deploy ok')}")
print(f"GoodNotifier(SMS).notify('deploy ok')   -> {GoodNotifier(SmsSender()).notify('deploy ok')}")

assert BadNotifier().notify("x") == GoodNotifier(EmailSender()).notify("x")
check("DIP: email result preserved; SMS swaps in with zero edits to GoodNotifier")


# ===========================================================================
banner("PART II  --  THE 5-PHASE DESIGN PROCESS CHECKLIST")
print("    Understand Requirements -> Identify Entities -> Define Relationships")
print("    -> Apply Patterns -> Review Tradeoffs   (the SEDIE shape)")
# ===========================================================================

banner("Phase 1  UNDERSTAND REQUIREMENTS  -- name the boundary", char="-")
print("  Worked example: a Notification Service that fires on order events.")
print("  IN scope : send a message on order placed / shipped.")
print("  OUT scope: marketing campaigns, A/B delivery, template editor.")
print("  Actors   : OrderService (caller), end customer (receiver).")
print("  Use cases: notify(channel, message) -> delivery receipt.")
print("  Constraint: must swap channel (email/sms) without touching callers.")
print("  [x] boundary stated   [x] assumptions written   [x] alignment")

banner("Phase 2  IDENTIFY ENTITIES  -- nouns to candidates, filter the weak", char="-")
print("  Nouns (candidates): Notifier, Message, Channel, EmailSender, SmsSender, Receipt.")
print("  Verbs (methods)   : notify(), send(), format(), acknowledge().")
print("  Filter:")
print("    KEEP   Notifier (lifecycle + policy), MessageSender (varies), Receipt (value).")
print("    COLLAPSE 'Channel' -> enum/value object, not a class (no behavior).")
print("  Entity list: Notifier, MessageSender(ABC), EmailSender, SmsSender, Receipt.")

banner("Phase 3  DEFINE RELATIONSHIPS  -- is-a / has-a / uses-a", char="-")
print("  EmailSender  is-a  MessageSender   (true specialization, swap target)")
print("  SmsSender    is-a  MessageSender   (true specialization, swap target)")
print("  Notifier     has-a MessageSender   (composition; injected at construct)")
print("  Notifier    uses-a Message         (passed into notify(), not owned)")
print("  Receipt      value  (immutable record of one delivery)")

banner("Phase 4  APPLY PATTERNS  -- requirement signal -> SOLID -> pattern", char="-")
print("  Signal 'channel swaps at runtime'   -> OCP/DIP -> Strategy (MessageSender).")
print("  Signal 'caller must not know how'   -> DIP      -> inject the abstraction.")
print("  Signal 'one delivery record shape'  -> DRY      -> Receipt value object.")
print("  Code lives in PART I (DIP section): GoodNotifier(EmailSender()).")

banner("Phase 5  REVIEW TRADEOFFS  -- the weighted matrix (see PART III)", char="-")
print("  Pick the channel using the matrix below, not a gut call.")
print("  Then prove extensibility: a new PushSender subclass needs zero edits to Notifier.")

check("5-phase process: each phase left a visible artifact on the board")


# ===========================================================================
banner("PART III  --  TRADEOFF ANALYSIS MATRIX (weighted decision)")
# ===========================================================================

WEIGHTS = {
    "cost":         0.20,                                # lower cost scores higher
    "latency":      0.30,                                # faster scores higher
    "reliability":  0.30,                                # more reliable scores higher
    "reachability": 0.20,                                # more users reachable scores higher
}
# Scores 1..5 (5 = best on that criterion). Deterministic inputs, no hand-waving.
OPTIONS = {
    "Email": {"cost": 5, "latency": 2, "reliability": 4, "reachability": 4},
    "SMS":   {"cost": 2, "latency": 5, "reliability": 4, "reachability": 4},
    "Push":  {"cost": 5, "latency": 4, "reliability": 3, "reachability": 2},
}

crits = list(WEIGHTS)
assert almost(sum(WEIGHTS.values()), 1.0), "weights must total 1.0"

print("  criterion weights (5 = best, weights sum to 1.0):")
for c in crits:
    print(f"    {c:<13} {WEIGHTS[c]:.2f}")
print()
print(f"  {'option':<8}" + "".join(f"{c:>13}" for c in crits) + "      SCORE")
print("  " + "-" * 66)

scores: dict[str, float] = {}
for name, raw in OPTIONS.items():
    total = 0.0
    row = f"  {name:<8}"
    for c in crits:
        s = raw[c]
        w = WEIGHTS[c]
        total += s * w
        row += f"{s:>8}x{w:.2f}"
    total = round(total, 3)
    scores[name] = total
    row += f"   {total:5.2f}"
    print(row)

ranking = sorted(scores, key=lambda n: scores[n], reverse=True)
print()
print("  ranking (highest weighted score wins):")
for i, name in enumerate(ranking, 1):
    tag = "   <-- pick this" if i == 1 else ""
    print(f"    {i}. {name:<6} {scores[name]:.2f}{tag}")

assert ranking[0] == "SMS", "SMS should win given latency + reliability weight"
check("matrix deterministic: SMS 3.90 > Email 3.60 > Push 3.50")


# ===========================================================================
banner("ALL CHECKS PASSED -- SOLID + 5-phase process + tradeoff matrix")
print("    SRP | OCP | LSP | ISP | DIP   +   Understand -> Entities -> Relationships")
print("    -> Patterns -> Tradeoffs")
check("design_framework.py complete")
