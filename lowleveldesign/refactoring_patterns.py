#!/usr/bin/env python3
"""
refactoring_patterns.py -- Code smells and the refactorings that kill them.

Each section runs a SMELLY version (the code smell -- it "works" but hurts) and a
CLEAN version (refactored via a Fowler technique), then asserts both produce the
same observable result, so the refactor is provably behavior-preserving. A green
``[check] OK`` follows.

Smells & refactorings covered
    00. Code Smells Catalog            -- the diagnostic table (Fowler)
    01. Long Method          -> Extract Method
    02. Divergent Change     -> Move Method              (Feature Envy)
    03. Switch Statements    -> Replace Conditional with Polymorphism
    04. Large Class          -> Extract Class
    05. Long Parameter List  -> Introduce Parameter Object

Pure stdlib. Run:  python3 refactoring_patterns.py
Companion guide:   lowleveldesign/REFACTORING_PATTERNS.md
Interactive demo:  lowleveldesign/refactoring_patterns.html
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


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
# 00. CODE SMELLS CATALOG -- the diagnostic table (Fowler's taxonomy)
# ===========================================================================
banner("00. CODE SMELLS CATALOG -- the diagnostic table (Fowler)")

SMELLS: list[tuple[str, str, str]] = [
    ("Long Method",          "Extract Method",                    "method > ~20 lines; comments narrate it"),
    ("Large Class",          "Extract Class",                     "one class, many unrelated fields/methods"),
    ("Long Parameter List",  "Introduce Parameter Object",        "4+ args; callers struggle to build them"),
    ("Divergent Change",     "Move Method / Extract Class",       "one class edited for many unrelated reasons"),
    ("Shotgun Surgery",      "Move Field / Inline Class",         "one change touches many classes"),
    ("Switch Statements",    "Replace Cond. w/ Polymorphism",     "repeated type-switch across methods"),
    ("Feature Envy",         "Move Method",                       "method uses another class more than its own"),
    ("Data Clumps",          "Extract Class / Param Object",      "same 3 args passed together everywhere"),
]
print(f"  {'Smell':<22}{'Refactoring':<36}Symptom")
print(f"  {'-' * 22}{'-' * 36}{'-' * 34}")
for smell, fix, symptom in SMELLS:
    print(f"  {smell:<22}{fix:<36}{symptom}")
check("catalog: 8 smells mapped to their refactoring technique")


# ===========================================================================
# 01. LONG METHOD -> EXTRACT METHOD
# ===========================================================================
banner("01. LONG METHOD -- BAD: one 20-line print_invoice does everything")

def bad_print_invoice(items: list[dict], discount: float, tax_rate: float) -> float:
    # validate (inlined)
    if not items:
        raise ValueError("empty cart")
    # subtotal (inlined)
    subtotal = 0.0
    for it in items:
        subtotal += it["price"] * it["qty"]
    # discount (inlined)
    after_discount = subtotal * (1 - discount)
    # tax (inlined)
    total = after_discount + after_discount * tax_rate
    # print lines (inlined)
    print(f"    SUBTOTAL   {subtotal:>8.2f}")
    print(f"    DISCOUNT  -{subtotal - after_discount:>8.2f}")
    print(f"    TAX        {after_discount * tax_rate:>8.2f}")
    print(f"    TOTAL      {total:>8.2f}")
    return total


bad_invoice_total = bad_print_invoice(
    [{"name": "Book", "price": 100.0, "qty": 2},
     {"name": "Pen",  "price": 150.0, "qty": 2}],
    discount=0.10, tax_rate=0.08,
)
print(f"bad_print_invoice(...)  -> {bad_invoice_total:.1f}")


banner("01. LONG METHOD -- GOOD: Extract Method -- orchestrator + named helpers")

def subtotal_of(items: list[dict]) -> float:
    if not items:
        raise ValueError("empty cart")
    return sum(it["price"] * it["qty"] for it in items)

def apply_discount(amount: float, discount: float) -> float:
    return amount * (1 - discount)

def apply_tax(amount: float, tax_rate: float) -> float:
    return amount + amount * tax_rate

def print_invoice(items: list[dict], discount: float, tax_rate: float) -> float:
    sub = subtotal_of(items)                          # extracted
    after_discount = apply_discount(sub, discount)    # extracted
    total = apply_tax(after_discount, tax_rate)       # extracted
    print(f"    SUBTOTAL   {sub:>8.2f}")
    print(f"    DISCOUNT  -{sub - after_discount:>8.2f}")
    print(f"    TAX        {after_discount * tax_rate:>8.2f}")
    print(f"    TOTAL      {total:>8.2f}")
    return total


good_invoice_total = print_invoice(
    [{"name": "Book", "price": 100.0, "qty": 2},
     {"name": "Pen",  "price": 150.0, "qty": 2}],
    discount=0.10, tax_rate=0.08,
)
print(f"print_invoice(...)      -> {good_invoice_total:.1f}")

assert almost(bad_invoice_total, good_invoice_total), "extract-method changed total"
check("Extract Method preserves total (500 * 0.9 * 1.08 = 486.0)")


# ===========================================================================
# 02. DIVERGENT CHANGE / FEATURE ENVY -> MOVE METHOD
# ===========================================================================
banner("02. DIVERGENT CHANGE -- BAD: Customer.early_termination_fee envies Contract")

class BadContract:
    def __init__(self, months_remaining: int, monthly_fee: float,
                 discount_rate: float) -> None:
        self.months_remaining = months_remaining
        self.monthly_fee = monthly_fee
        self.discount_rate = discount_rate


class BadCustomer:
    """BAD: reads 3 fields of Contract and 0 of its own (Feature Envy)."""

    def early_termination_fee(self, contract: BadContract) -> float:
        # every fee-rule change edits Customer; every discount change edits Customer too
        return (
            contract.months_remaining
            * contract.monthly_fee
            * (1 - contract.discount_rate)
        )


bad_fee = BadCustomer().early_termination_fee(BadContract(8, 50.0, 0.10))
print(f"BadCustomer.early_termination_fee(...) -> {bad_fee:.1f}")


banner("02. DIVERGENT CHANGE -- GOOD: Move Method -- fee lives on Contract")

class Contract:
    """Fee rules change here now; Customer is no longer touched for fee edits."""

    def __init__(self, months_remaining: int, monthly_fee: float,
                 discount_rate: float) -> None:
        self.months_remaining = months_remaining
        self.monthly_fee = monthly_fee
        self.discount_rate = discount_rate

    def early_termination_fee(self) -> float:
        return self.months_remaining * self.monthly_fee * (1 - self.discount_rate)


class Customer:
    """Customer changes for customer reasons; fee changes for fee reasons."""

    def __init__(self, name: str) -> None:
        self.name = name

    def early_termination_fee(self, contract: Contract) -> float:
        return contract.early_termination_fee()       # delegate after the move


good_fee = Customer("Alice").early_termination_fee(Contract(8, 50.0, 0.10))
print(f"Customer.early_termination_fee(...)     -> {good_fee:.1f}")

assert almost(bad_fee, good_fee), "move-method changed the fee"
check("Move Method preserves fee (8 * 50 * 0.9 = 360.0)")


# ===========================================================================
# 03. SWITCH STATEMENTS -> REPLACE CONDITIONAL WITH POLYMORPHISM
# ===========================================================================
banner("03. SWITCH STATEMENTS -- BAD: one function branches on employee type")

def bad_monthly_pay(emp_type: str, base: float, extra: float) -> float:
    # every new role edits this function; the same switch is duplicated elsewhere
    if emp_type == "engineer":
        return base                                # no commission
    if emp_type == "salesman":
        return base + extra                        # base + commission
    if emp_type == "manager":
        return base + extra * 2                    # base + double bonus
    raise ValueError(f"unknown type: {emp_type}")


bad_pays = [
    bad_monthly_pay("engineer", 3000.0, 500.0),
    bad_monthly_pay("salesman", 2000.0, 500.0),
    bad_monthly_pay("manager",  5000.0, 500.0),
]
print(f"bad engineer -> {bad_pays[0]:.1f}")
print(f"bad salesman -> {bad_pays[1]:.1f}")
print(f"bad manager  -> {bad_pays[2]:.1f}")
print(f"bad payroll  -> {sum(bad_pays):.1f}")


banner("03. SWITCH STATEMENTS -- GOOD: subclasses own one branch each (OCP)")

class Employee(ABC):
    """The type field is gone; each role is a class that knows its own pay rule."""

    def __init__(self, name: str, base: float, extra: float) -> None:
        self.name = name
        self.base = base
        self.extra = extra

    @abstractmethod
    def monthly_pay(self) -> float: ...


class Engineer(Employee):
    def monthly_pay(self) -> float:
        return self.base                            # was: if type == 'engineer'


class Salesman(Employee):
    def monthly_pay(self) -> float:
        return self.base + self.extra               # was: if type == 'salesman'


class Manager(Employee):
    def monthly_pay(self) -> float:
        return self.base + self.extra * 2           # was: if type == 'manager'


good_emps: list[Employee] = [
    Engineer("Sam", 3000.0, 500.0),
    Salesman("Jo",  2000.0, 500.0),
    Manager("Kay",  5000.0, 500.0),
]
good_pays = [e.monthly_pay() for e in good_emps]
print(f"good engineer -> {good_pays[0]:.1f}")
print(f"good salesman -> {good_pays[1]:.1f}")
print(f"good manager  -> {good_pays[2]:.1f}")
print(f"good payroll  -> {sum(good_pays):.1f}")

assert [round(p, 2) for p in bad_pays] == [round(p, 2) for p in good_pays], \
    "polymorphism changed pays"
check("Replace Conditional w/ Polymorphism: 3000 + 2500 + 6000 = 11500.0")


# ===========================================================================
# 04. LARGE CLASS -> EXTRACT CLASS
# ===========================================================================
banner("04. LARGE CLASS -- BAD: Person holds identity AND address AND formatting")

class BadPerson:
    """BAD: 6 fields spanning two responsibilities: who-you-are vs where-you-live."""

    def __init__(self, name: str, email: str, phone: str,
                 street: str, city: str, zip_code: str) -> None:
        self.name = name
        self.email = email
        self.phone = phone
        # --- address concerns mixed in ---
        self.street = street
        self.city = city
        self.zip_code = zip_code

    def format(self) -> str:
        return (f"{self.name} <{self.email}> | "
                f"{self.street}, {self.city} {self.zip_code}")

    def shipping_label(self) -> str:
        return f"{self.name}\n{self.street}\n{self.city}, {self.zip_code}"


bad_person = BadPerson("Alice", "alice@example.com", "555-0100",
                       "123 Main St", "Springfield", "62704")
print(f"BadPerson.format()         -> {bad_person.format()}")
print(f"BadPerson.shipping_label() -> {bad_person.shipping_label()!r}")


banner("04. LARGE CLASS -- GOOD: Extract Class -- Address owns fields & label")

class Address:
    """Reason to change: postal / address formatting rules."""

    def __init__(self, street: str, city: str, zip_code: str) -> None:
        self.street = street
        self.city = city
        self.zip_code = zip_code

    def one_line(self) -> str:
        return f"{self.street}, {self.city} {self.zip_code}"

    def label(self, name: str) -> str:
        return f"{name}\n{self.street}\n{self.city}, {self.zip_code}"


class Person:
    """Reason to change: identity (name/email/phone). Address is delegated."""

    def __init__(self, name: str, email: str, phone: str, address: Address) -> None:
        self.name = name
        self.email = email
        self.phone = phone
        self.address = address                      # the extracted class

    def format(self) -> str:
        return f"{self.name} <{self.email}> | {self.address.one_line()}"

    def shipping_label(self) -> str:
        return self.address.label(self.name)        # delegate


good_person = Person("Alice", "alice@example.com", "555-0100",
                     Address("123 Main St", "Springfield", "62704"))
print(f"Person.format()            -> {good_person.format()}")
print(f"Person.shipping_label()    -> {good_person.shipping_label()!r}")

assert bad_person.format() == good_person.format(), "extract-class changed format()"
assert bad_person.shipping_label() == good_person.shipping_label(), \
    "extract-class changed label()"
check("Extract Class preserves format() + shipping_label()")


# ===========================================================================
# 05. LONG PARAMETER LIST -> INTRODUCE PARAMETER OBJECT
# ===========================================================================
banner("05. LONG PARAMETER LIST -- BAD: 9 positional args, callers struggle")

def bad_place_order(user_id: str, cart_id: str, coupon: Optional[str],
                    shipping_street: str, shipping_city: str, shipping_zip: str,
                    payment_token: str, currency: str, express: bool) -> dict:
    # caller must remember arg #5 is city, #8 is currency -- no help from the compiler
    subtotal = 50.0                                 # pretend it came from cart_id
    after_coupon = subtotal * (0.9 if coupon else 1.0)
    shipping = 6.0 if express else 0.0
    tax = after_coupon * 0.08
    return {
        "user_id": user_id,
        "cart_id": cart_id,
        "currency": currency,
        "shipping_to": f"{shipping_street}, {shipping_city} {shipping_zip}",
        "total": round(after_coupon + shipping + tax, 2),
    }


bad_order = bad_place_order(
    "u1", "c1", "SAVE10",
    "123 Main St", "Springfield", "62704",
    "tok_abc", "USD", True,
)
print(f"bad_place_order(...) total  -> {bad_order['total']:.1f}")
print(f"bad shipping_to             -> {bad_order['shipping_to']}")


banner("05. LONG PARAMETER LIST -- GOOD: group related args into value objects")

@dataclass(frozen=True)
class ShippingAddress:
    """Parameter object: the 3 address args always travel together."""
    street: str
    city: str
    zip_code: str

    def one_line(self) -> str:
        return f"{self.street}, {self.city} {self.zip_code}"


@dataclass(frozen=True)
class OrderRequest:
    """Parameter object: 9 positional args collapse to one cohesive value."""
    user_id: str
    cart_id: str
    coupon: Optional[str]
    ship_to: ShippingAddress
    payment_token: str
    currency: str = "USD"
    express: bool = False


def place_order(req: OrderRequest) -> dict:
    subtotal = 50.0
    after_coupon = subtotal * (0.9 if req.coupon else 1.0)
    shipping = 6.0 if req.express else 0.0
    tax = after_coupon * 0.08
    return {
        "user_id": req.user_id,
        "cart_id": req.cart_id,
        "currency": req.currency,
        "shipping_to": req.ship_to.one_line(),
        "total": round(after_coupon + shipping + tax, 2),
    }


good_order = place_order(OrderRequest(
    user_id="u1", cart_id="c1", coupon="SAVE10",
    ship_to=ShippingAddress("123 Main St", "Springfield", "62704"),
    payment_token="tok_abc", currency="USD", express=True,
))
print(f"place_order(...) total      -> {good_order['total']:.1f}")
print(f"shipping_to                 -> {good_order['shipping_to']}")

assert bad_order == good_order, "parameter-object refactor changed the order"
check("Introduce Parameter Object: 45 + 6 + 3.6 = 54.6")


# ===========================================================================
banner("ALL FIVE REFACTORINGS: BAD == GOOD (behavior preserved), refactor safe")
print("    Long Method | Divergent Change | Switch | Large Class | Long Param List")
check("refactoring_patterns.py complete")
