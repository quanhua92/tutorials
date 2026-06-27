#!/usr/bin/env python3
"""Shopping Cart & Checkout -- aggregate root, pricing rules engine,
cart state machine, idempotent checkout.

Ground-truth implementation. Pure Python stdlib only.

What this demonstrates:
  * Aggregate boundary -- Cart (mutable, short-lived) vs Order (immutable,
    permanent). Checkout COPIES line snapshots into a new Order; it never
    mutates the Cart into an Order ("just mark cart paid" is the #3
    not-hire mistake).
  * ProductSnapshot -- price frozen at add time. Catalog reprices cannot
    retroactively alter an open cart or a paid order (audit-safe pricing).
  * MoneyCents -- integer minor units; never float for money.
  * Pricing rules engine -- Strategy-pattern PromotionRule family
    (BuyOneGetOneFree, BulkDiscount, PercentOffCoupon, FixedAmountOffCoupon,
    FreeShippingThreshold) plugged into a PromotionEngine. The Cart knows
    zero promotion mechanics (SRP).
  * Cart state machine -- EMPTY -> ACTIVE -> CHECKOUT -> {PAID, ABANDONED}.
    Illegal transitions raise.
  * Inventory port -- advisory check on add; hard reserve at checkout submit.
  * Idempotent checkout -- IdempotentOrderFactory.create_once(key, body, build)
    returns the same Order for a repeated key; same key + different body errors
    (Stripe semantics).

Companion artifacts:
    SHOPPING_CART.md             -- design guide (UML, state machine, SOLID)
    shopping_cart.html           -- interactive simulator + state visualizer
    shopping_cart_output.txt     -- captured stdout

Bundle catalog entry #07 in lowleveldesign/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Tuple


# =========================================================================== #
#  Errors
# =========================================================================== #
class CartError(Exception):
    """Base for all cart-domain errors."""


class IllegalTransitionError(CartError):
    """A state-machine transition was attempted that is not in the table."""


class EmptyCartError(CartError):
    """An operation that requires items was run on an empty cart."""


class InsufficientInventoryError(CartError):
    """Stock was insufficient at add (advisory) or reserve (hard)."""


class CouponError(CartError):
    """Coupon was unknown, duplicate, or malformed."""


class IdempotencyConflictError(CartError):
    """An idempotency key was reused with a different request body."""


# =========================================================================== #
#  Money -- integer minor units. NEVER float.
# =========================================================================== #
class MoneyCents:
    """Immutable money in integer minor units (cents).

    Float money is the #1 not-hire mistake in cart interviews:
    0.10 + 0.20 == 0.30000000000000004 in IEEE-754. Over 1M orders that is a
    real ledger drift. MoneyCents(10).plus(MoneyCents(20)) == MoneyCents(30).
    """

    __slots__ = ("_cents",)

    def __init__(self, cents: int):
        if not isinstance(cents, int):
            raise TypeError(
                f"MoneyCents requires int, got {type(cents).__name__}")
        if cents < 0:
            raise ValueError(f"MoneyCents cannot be negative: {cents}")
        self._cents = cents

    @property
    def cents(self) -> int:
        return self._cents

    def plus(self, other: "MoneyCents") -> "MoneyCents":
        return MoneyCents(self._cents + other._cents)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MoneyCents) and self._cents == other._cents

    def __hash__(self) -> int:
        return hash(self._cents)

    def __repr__(self) -> str:
        return f"MoneyCents({self._cents})"

    def __str__(self) -> str:
        return fmt(self._cents)


def fmt(cents: int) -> str:
    """Format integer cents as $X.YY (display only; never compute on floats)."""
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}${c // 100}.{c % 100:02d}"


# =========================================================================== #
#  ProductSnapshot -- frozen price-at-add-time value object
# =========================================================================== #
class ProductSnapshot:
    """Immutable product snapshot captured at add-to-cart time.

    Why snapshot vs live Product reference: a LineItem that re-fetches the
    live catalog price at checkout shows the customer a different total than
    the shelf price they saw -- audit disputes, chargebacks, trust loss.
    The snapshot freezes unit_price so catalog reprices never rewrite open
    carts or paid orders.
    """

    __slots__ = ("product_id", "title", "unit_price", "currency")

    def __init__(self, product_id: str, title: str,
                 unit_price: MoneyCents, currency: str = "USD"):
        self.product_id = product_id
        self.title = title
        self.unit_price = unit_price
        self.currency = currency

    def __repr__(self) -> str:
        return (f"ProductSnapshot({self.product_id!r}, {self.title!r}, "
                f"{self.unit_price}, {self.currency!r})")


class ProductCatalog:
    """Live catalog. snapshot() returns a FROZEN copy, never a mutable
    reference -- callers cannot accidentally reprice the catalog by editing
    a line item's price field."""

    def __init__(self) -> None:
        self._products: Dict[str, Tuple[str, MoneyCents]] = {}

    def upsert(self, product_id: str, title: str, unit_price: MoneyCents) -> None:
        self._products[product_id] = (title, unit_price)

    def reprice(self, product_id: str, new_price: MoneyCents) -> None:
        if product_id not in self._products:
            raise KeyError(product_id)
        title, _ = self._products[product_id]
        self._products[product_id] = (title, new_price)

    def snapshot(self, product_id: str) -> ProductSnapshot:
        title, price = self._products[product_id]
        # MoneyCents is immutable, so this is effectively a frozen copy.
        return ProductSnapshot(product_id, title, price)

    def __contains__(self, product_id: str) -> bool:
        return product_id in self._products


# =========================================================================== #
#  LineItem -- one row in the cart
# =========================================================================== #
class LineItem:
    """A cart line: ProductSnapshot + quantity.

    The line holds a SNAPSHOT, not a product_id, so the unit price is frozen
    regardless of later catalog changes.
    """

    __slots__ = ("line_id", "snapshot", "qty")

    def __init__(self, line_id: str, snapshot: ProductSnapshot, qty: int):
        if qty < 1:
            raise ValueError(f"qty must be >= 1, got {qty}")
        self.line_id = line_id
        self.snapshot = snapshot
        self.qty = qty

    @property
    def product_id(self) -> str:
        return self.snapshot.product_id

    @property
    def unit_cents(self) -> int:
        return self.snapshot.unit_price.cents

    @property
    def line_total_cents(self) -> int:
        return self.unit_cents * self.qty

    def __repr__(self) -> str:
        return (f"LineItem({self.line_id}, {self.snapshot.product_id}, "
                f"x{self.qty}, {fmt(self.line_total_cents)})")


# =========================================================================== #
#  PriceAdjustment -- output of the promotion engine
# =========================================================================== #
class PriceAdjustment:
    """A discount/shipping line produced by a PromotionRule.

    scope:
      "LINE" -> a per-line discount (subtracted from subtotal)
      "CART" -> a cart-wide discount (subtracted from subtotal after line disc)
      "SHIP" -> a shipping waiver (subtracted from the base shipping fee)
    amount_cents is always a positive magnitude; the scope decides the sign.
    """

    __slots__ = ("rule_name", "scope", "amount_cents", "line_id", "note")

    def __init__(self, rule_name: str, scope: str, amount_cents: int,
                 line_id: Optional[str] = None, note: str = ""):
        if scope not in ("LINE", "CART", "SHIP"):
            raise ValueError(f"unknown scope: {scope}")
        if amount_cents < 0:
            raise ValueError("adjustment amount must be >= 0")
        self.rule_name = rule_name
        self.scope = scope
        self.amount_cents = amount_cents
        self.line_id = line_id
        self.note = note

    def __repr__(self) -> str:
        tgt = self.line_id or "CART"
        return (f"PriceAdjustment({self.rule_name}, {self.scope}, {tgt}, "
                f"-{fmt(self.amount_cents)})")


# =========================================================================== #
#  PromotionRule -- Strategy interface
# =========================================================================== #
class PromotionRule(ABC):
    """Strategy interface. The Cart knows nothing about specific rules."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def layer(self) -> str:
        """LINE rules run first; CART rules run on the post-line subtotal."""
        return "LINE"

    @property
    def code(self) -> Optional[str]:
        """Coupon code this rule honours, if any (None for auto-rules)."""
        return None

    @abstractmethod
    def evaluate(self, items: List[LineItem],
                 context: "PricingContext") -> List[PriceAdjustment]:
        ...


class PricingContext:
    """Carries running subtotal + applied coupons between rule layers.

    subtotal_after_line_cents is set by the engine BEFORE cart rules run, so
    every CART rule sees the same post-line base (parallel stacking, no
    cascading).
    """

    def __init__(self, coupons: Optional[List[str]] = None):
        self.coupons: List[str] = list(coupons or [])
        self.subtotal_after_line_cents: int = 0


# ---- Concrete LINE rules -------------------------------------------------- #
class BuyOneGetOneFree(PromotionRule):
    """Buy `buy_qty`, get `free_qty` free on a product.

    e.g. BOGO USB-CABLE buy1 get1: for 4 cables, 4 // (1+1) = 2 sets ->
    2 free units -> 2 * unit_cents discount.
    """

    def __init__(self, product_id: str, buy_qty: int, free_qty: int):
        if buy_qty < 1 or free_qty < 1:
            raise ValueError("buy_qty and free_qty must be >= 1")
        self.product_id = product_id
        self.buy_qty = buy_qty
        self.free_qty = free_qty

    @property
    def name(self) -> str:
        return f"BOGO({self.product_id},buy{self.buy_qty}get{self.free_qty})"

    def evaluate(self, items, context):
        out = []
        for it in items:
            if it.product_id != self.product_id:
                continue
            sets = it.qty // (self.buy_qty + self.free_qty)
            if sets <= 0:
                continue
            free_units = sets * self.free_qty
            out.append(PriceAdjustment(
                self.name, "LINE", free_units * it.unit_cents,
                line_id=it.line_id, note=f"{free_units} free units",
            ))
        return out


class BulkDiscount(PromotionRule):
    """`percent`% off a line when qty >= threshold."""

    def __init__(self, product_id: str, threshold: int, percent: int):
        if threshold < 1 or not (0 < percent < 100):
            raise ValueError("threshold >= 1 and 0 < percent < 100")
        self.product_id = product_id
        self.threshold = threshold
        self.percent = percent

    @property
    def name(self) -> str:
        return f"BulkDiscount({self.product_id},>={self.threshold},{self.percent}%)"

    def evaluate(self, items, context):
        out = []
        for it in items:
            if it.product_id != self.product_id or it.qty < self.threshold:
                continue
            disc = it.line_total_cents * self.percent // 100
            out.append(PriceAdjustment(
                self.name, "LINE", disc, line_id=it.line_id,
                note=f"{self.percent}% off bulk qty",
            ))
        return out


# ---- Concrete CART rules -------------------------------------------------- #
class PercentOffCoupon(PromotionRule):
    """Cart-level % off coupon. Runs on the post-line subtotal."""

    def __init__(self, code: str, percent: int):
        if not (0 < percent < 100):
            raise ValueError("0 < percent < 100")
        self._code = code
        self.percent = percent

    @property
    def name(self) -> str:
        return f"Coupon({self._code},-{self.percent}%)"

    @property
    def layer(self) -> str:
        return "CART"

    @property
    def code(self) -> str:
        return self._code

    def evaluate(self, items, context):
        if self._code not in context.coupons:
            return []
        base = context.subtotal_after_line_cents
        if base <= 0:
            return []
        disc = base * self.percent // 100
        return [PriceAdjustment(self.name, "CART", disc,
                                note=f"{self.percent}% off subtotal")]


class FixedAmountOffCoupon(PromotionRule):
    """Cart-level fixed-amount-off coupon. Cannot drop subtotal below zero."""

    def __init__(self, code: str, amount_cents: int):
        if amount_cents <= 0:
            raise ValueError("amount_cents must be > 0")
        self._code = code
        self.amount_cents = amount_cents

    @property
    def name(self) -> str:
        return f"Coupon({self._code},-{fmt(self.amount_cents)})"

    @property
    def layer(self) -> str:
        return "CART"

    @property
    def code(self) -> str:
        return self._code

    def evaluate(self, items, context):
        if self._code not in context.coupons:
            return []
        base = context.subtotal_after_line_cents
        disc = min(self.amount_cents, base)
        return [PriceAdjustment(self.name, "CART", disc, note="flat amount off")]


class FreeShippingThreshold(PromotionRule):
    """If post-line subtotal >= threshold, waive the base shipping fee.

    Modelled as a SHIP adjustment whose amount is the waived fee; the cart's
    breakdown subtracts SHIP adjustments from the base shipping fee.
    """

    BASE_SHIPPING_CENTS = 800

    def __init__(self, threshold_cents: int = 15000):
        self.threshold_cents = threshold_cents

    @property
    def name(self) -> str:
        return f"FreeShipping(>={fmt(self.threshold_cents)})"

    @property
    def layer(self) -> str:
        return "CART"

    def evaluate(self, items, context):
        base = context.subtotal_after_line_cents
        if base >= self.threshold_cents:
            return [PriceAdjustment(
                self.name, "SHIP", self.BASE_SHIPPING_CENTS,
                note="free shipping unlocked")]
        return []


# =========================================================================== #
#  PromotionEngine -- walks lines + coupons, returns ordered adjustments
# =========================================================================== #
class PromotionEngine:
    """Two-layer rule runner.

    Layer 1 (LINE): per-line rules (BOGO, BulkDiscount) -- independent.
    Layer 2 (CART): cart-wide rules (coupons, free shipping) -- run on the
    subtotal AFTER line discounts; every CART rule sees the SAME post-line
    base (parallel stacking, no cascading).

    The Cart calls engine.evaluate(items, coupons) and never knows what a
    BOGO is. SRP preserved.
    """

    def __init__(self, rules: Optional[List[PromotionRule]] = None):
        self.rules: List[PromotionRule] = list(rules or [])

    def add_rule(self, rule: PromotionRule) -> None:
        self.rules.append(rule)

    def known_coupon_codes(self) -> List[str]:
        return [r.code for r in self.rules if r.code is not None]

    def evaluate(self, items: List[LineItem],
                 coupons: Optional[List[str]] = None) -> List[PriceAdjustment]:
        ctx = PricingContext(coupons)
        line_rules = [r for r in self.rules if r.layer == "LINE"]
        cart_rules = [r for r in self.rules if r.layer == "CART"]

        adjustments: List[PriceAdjustment] = []
        line_disc = 0
        for r in line_rules:
            for a in r.evaluate(items, ctx):
                adjustments.append(a)
                line_disc += a.amount_cents

        subtotal = sum(it.line_total_cents for it in items)
        ctx.subtotal_after_line_cents = max(0, subtotal - line_disc)

        for r in cart_rules:
            adjustments.extend(r.evaluate(items, ctx))
        return adjustments


# =========================================================================== #
#  Cart breakdown -- the priced total
# =========================================================================== #
class CartBreakdown:
    """Priced cart: subtotal, discounts by scope, shipping, total."""

    __slots__ = ("subtotal", "line_discount", "cart_discount",
                 "shipping", "total", "adjustments")

    def __init__(self, subtotal: int, line_discount: int, cart_discount: int,
                 shipping: int, total: int,
                 adjustments: List[PriceAdjustment]):
        self.subtotal = subtotal
        self.line_discount = line_discount
        self.cart_discount = cart_discount
        self.shipping = shipping
        self.total = total
        self.adjustments = adjustments

    def signature(self) -> str:
        """Comma-joined (no spaces) -- parity-checked by shopping_cart.html."""
        return ",".join(str(x) for x in (
            self.subtotal, self.line_discount,
            self.cart_discount, self.shipping, self.total))


# =========================================================================== #
#  Cart state machine
# =========================================================================== #
EMPTY = "EMPTY"
ACTIVE = "ACTIVE"
CHECKOUT = "CHECKOUT"
PAID = "PAID"
ABANDONED = "ABANDONED"
ALL_STATES = [EMPTY, ACTIVE, CHECKOUT, PAID, ABANDONED]

# (from, to) -> event label
STATE_TRANSITIONS: Dict[Tuple[str, str], str] = {
    (EMPTY, ACTIVE):      "add_first_item",
    (ACTIVE, ACTIVE):     "add_or_update_item",
    (ACTIVE, CHECKOUT):   "begin_checkout",
    (CHECKOUT, PAID):     "payment_captured",
    (CHECKOUT, ACTIVE):   "cancel_checkout",
    (CHECKOUT, ABANDONED): "checkout_timeout",
    (ACTIVE, ABANDONED):  "session_expired",
    (ABANDONED, ACTIVE):  "recover_cart",
}


class CartStateMachine:
    """Table-driven state machine. Illegal transitions raise."""

    def __init__(self) -> None:
        self._state = EMPTY

    @property
    def state(self) -> str:
        return self._state

    def can(self, target: str) -> bool:
        return (self._state, target) in STATE_TRANSITIONS

    def transition(self, target: str) -> None:
        if (self._state, target) not in STATE_TRANSITIONS:
            raise IllegalTransitionError(
                f"illegal cart transition: {self._state} -> {target}")
        self._state = target

    def next_states(self) -> List[str]:
        return sorted({to for (frm, to) in STATE_TRANSITIONS if frm == self._state})


# =========================================================================== #
#  Cart -- aggregate root (mutable, short-lived)
# =========================================================================== #
class Cart:
    """Mutable working document. Keyed by (cart_id, customer_id, session_id).

    Invariants:
      * state == EMPTY  iff  items == []
      * every line qty >= 1
      * version increments on every mutation (optimistic concurrency)
    """

    BASE_SHIPPING_CENTS = 800

    def __init__(self, cart_id: str, customer_id: Optional[str],
                 session_id: str, catalog: ProductCatalog,
                 inventory: Optional["InventoryPort"] = None,
                 engine: Optional[PromotionEngine] = None) -> None:
        self.cart_id = cart_id
        self.customer_id = customer_id
        self.session_id = session_id
        self.catalog = catalog
        self.inventory = inventory
        self.engine = engine or PromotionEngine()
        self.items: List[LineItem] = []
        self.coupons: List[str] = []
        self.sm = CartStateMachine()
        self.version = 0

    # ---- queries ---- #
    @property
    def state(self) -> str:
        return self.sm.state

    def is_empty(self) -> bool:
        return len(self.items) == 0

    def find_line(self, product_id: str) -> Optional[LineItem]:
        for it in self.items:
            if it.product_id == product_id:
                return it
        return None

    # ---- mutations ---- #
    def add_item(self, product_id: str, qty: int = 1) -> LineItem:
        if qty < 1:
            raise ValueError(f"qty must be >= 1, got {qty}")
        if self.sm.state not in (EMPTY, ACTIVE):
            raise IllegalTransitionError(
                f"cannot add items in state {self.sm.state}")
        if product_id not in self.catalog:
            raise CartError(f"unknown product: {product_id}")
        if self.inventory:
            already = sum(it.qty for it in self.items
                          if it.product_id == product_id)
            if not self.inventory.available(product_id, already + qty):
                raise InsufficientInventoryError(
                    f"insufficient stock for {product_id} "
                    f"(want {already + qty} total)")
        snap = self.catalog.snapshot(product_id)           # frozen at add time
        existing = self.find_line(product_id)
        if existing:
            existing.qty += qty
            line = existing
        else:
            line = LineItem(f"L{len(self.items) + 1:02d}", snap, qty)
            self.items.append(line)
        if self.sm.state == EMPTY:
            self.sm.transition(ACTIVE)
        self.version += 1
        return line

    def update_qty(self, line_id: str, qty: int) -> None:
        if qty < 1:
            raise ValueError(f"qty must be >= 1, got {qty}")
        if self.sm.state != ACTIVE:
            raise IllegalTransitionError(
                f"cannot update line in state {self.sm.state}")
        for it in self.items:
            if it.line_id == line_id:
                it.qty = qty
                self.version += 1
                return
        raise CartError(f"unknown line_id: {line_id}")

    def remove_item(self, line_id: str) -> None:
        if self.sm.state != ACTIVE:
            raise IllegalTransitionError(
                f"cannot remove line in state {self.sm.state}")
        before = len(self.items)
        self.items = [it for it in self.items if it.line_id != line_id]
        if len(self.items) == before:
            raise CartError(f"unknown line_id: {line_id}")
        self.version += 1

    def apply_coupon(self, code: str) -> None:
        if self.sm.state not in (EMPTY, ACTIVE):
            raise IllegalTransitionError(
                f"cannot apply coupon in state {self.sm.state}")
        if code in self.coupons:
            raise CouponError(f"coupon already applied: {code}")
        if code not in self.engine.known_coupon_codes():
            raise CouponError(f"unknown coupon: {code}")
        self.coupons.append(code)
        self.version += 1

    def remove_coupon(self, code: str) -> None:
        if code not in self.coupons:
            raise CouponError(f"coupon not applied: {code}")
        self.coupons.remove(code)
        self.version += 1

    # ---- state transitions ---- #
    def begin_checkout(self) -> None:
        if self.is_empty():
            raise EmptyCartError("cannot checkout an empty cart")
        self.sm.transition(CHECKOUT)
        self.version += 1

    def cancel_checkout(self) -> None:
        self.sm.transition(ACTIVE)
        self.version += 1

    def mark_abandoned(self) -> None:
        if self.sm.state in (ACTIVE, CHECKOUT):
            self.sm.transition(ABANDONED)
            self.version += 1

    def recover(self) -> None:
        self.sm.transition(ACTIVE)
        self.version += 1

    def mark_paid(self) -> None:
        self.sm.transition(PAID)
        self.version += 1

    # ---- pricing ---- #
    def adjustments(self) -> List[PriceAdjustment]:
        return self.engine.evaluate(self.items, self.coupons)

    def breakdown(self) -> CartBreakdown:
        subtotal = sum(it.line_total_cents for it in self.items)
        adjs = self.adjustments()
        line_disc = sum(a.amount_cents for a in adjs if a.scope == "LINE")
        cart_disc = sum(a.amount_cents for a in adjs if a.scope == "CART")
        ship_waiver = sum(a.amount_cents for a in adjs if a.scope == "SHIP")
        shipping = max(0, self.BASE_SHIPPING_CENTS - ship_waiver)
        total = subtotal - line_disc - cart_disc + shipping
        return CartBreakdown(
            subtotal=subtotal, line_discount=line_disc,
            cart_discount=cart_disc, shipping=shipping, total=total,
            adjustments=adjs)


# =========================================================================== #
#  Inventory port -- advisory on add; reserve at checkout
# =========================================================================== #
class InventoryPort(ABC):
    """Port (interface). Swappable for SQL / Redis / a reservation service."""

    @abstractmethod
    def available(self, product_id: str, qty: int) -> bool:
        ...

    @abstractmethod
    def reserve(self, product_id: str, qty: int, hold_id: str) -> bool:
        ...

    @abstractmethod
    def commit(self, hold_id: str) -> None:
        ...


class InMemoryInventory(InventoryPort):
    """In-memory adapter. reserve() decrements immediately; commit() drops
    the hold bookkeeping (stock already gone). A real adapter would expire
    orphaned holds via a sweeper."""

    def __init__(self, stock: Optional[Dict[str, int]] = None) -> None:
        self._stock: Dict[str, int] = dict(stock or {})
        self._holds: Dict[str, Dict[str, int]] = {}

    def available(self, product_id: str, qty: int) -> bool:
        return self._stock.get(product_id, 0) >= qty

    def reserve(self, product_id: str, qty: int, hold_id: str) -> bool:
        if self._stock.get(product_id, 0) < qty:
            return False
        self._stock[product_id] -= qty
        holds = self._holds.setdefault(hold_id, {})
        holds[product_id] = holds.get(product_id, 0) + qty
        return True

    def commit(self, hold_id: str) -> None:
        self._holds.pop(hold_id, None)

    def stock_level(self, product_id: str) -> int:
        return self._stock.get(product_id, 0)


# =========================================================================== #
#  Order -- immutable post-checkout aggregate
# =========================================================================== #
class Order:
    """Immutable record. Created by CheckoutService; never mutated.

    Order receives COPIES of line snapshots so catalog changes never rewrite
    historical charges. Mutating any field after construction raises.
    """

    CREATED = "CREATED"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"

    def __init__(self, order_id: str, lines: List[LineItem],
                 breakdown: CartBreakdown, idempotency_key: str,
                 customer_id: Optional[str]) -> None:
        self.order_id = order_id
        self.lines: List[LineItem] = list(lines)        # shallow copy of the list
        self.breakdown = breakdown
        self.idempotency_key = idempotency_key
        self.customer_id = customer_id
        self.status = Order.PAID                        # set by factory post-capture
        self._frozen = True                             # must be last

    def __setattr__(self, key, value):
        if getattr(self, "_frozen", False):
            raise AttributeError(f"Order is immutable; cannot set {key!r}")
        super().__setattr__(key, value)

    def __repr__(self) -> str:
        return (f"Order({self.order_id}, {len(self.lines)} lines, "
                f"total={fmt(self.breakdown.total)}, status={self.status})")


# =========================================================================== #
#  IdempotentOrderFactory -- exactly-once Order creation
# =========================================================================== #
class IdempotentOrderFactory:
    """create_once(key, body, build_fn) -- exactly-once Order creation.

    Semantics (Stripe-style):
      * first call with key K + body B  -> runs build_fn(), stores K -> (B, Order)
      * repeat call with key K + body B  -> returns stored Order (no rebuild)
      * repeat call with key K + body B' -> raises IdempotencyConflictError

    The body is a hashable summary of the request (cart_id, version, coupons)
    so that a retry with a genuinely different cart is detected.
    """

    def __init__(self) -> None:
        self._done: Dict[str, Tuple[object, Order]] = {}

    def create_once(self, key: str, body,
                    build_fn: Callable[[], Order]) -> Order:
        if key in self._done:
            prev_body, prev_order = self._done[key]
            if prev_body != body:
                raise IdempotencyConflictError(
                    f"idempotency key {key!r} reused with different body")
            return prev_order
        order = build_fn()
        self._done[key] = (body, order)
        return order

    def __contains__(self, key: str) -> bool:
        return key in self._done

    def __len__(self) -> int:
        return len(self._done)


# =========================================================================== #
#  CheckoutService -- thin orchestrator with injected ports
# =========================================================================== #
class CheckoutService:
    """Validates cart -> reserves inventory -> builds Order -> captures payment.

    The Cart aggregate stays pure domain; all I/O goes through ports. The
    idempotency key guards against mobile-client double-tap and transport
    retries: build_fn() runs AT MOST ONCE per key.
    """

    def __init__(self, factory: IdempotentOrderFactory,
                 inventory: InventoryPort) -> None:
        self.factory = factory
        self.inventory = inventory

    def submit(self, cart: Cart, idempotency_key: str) -> Order:
        if cart.is_empty():
            raise EmptyCartError("cannot checkout an empty cart")

        # Body captures the REQUESTED contents (stable across replays).
        # We deliberately EXCLUDE cart.version: begin_checkout/mark_paid bump
        # it during the first build(), and a retry must produce the same body
        # to be recognized as a replay (not a conflict). Optimistic-concurrency
        # versioning is an orthogonal concern (a separate expected_version arg).
        body = (cart.cart_id,
                tuple((it.product_id, it.qty) for it in cart.items),
                tuple(sorted(cart.coupons)))

        def build() -> Order:
            cart.begin_checkout()
            hold_id = f"H-{cart.cart_id}"
            for it in cart.items:
                if not self.inventory.reserve(it.product_id, it.qty, hold_id):
                    raise InsufficientInventoryError(
                        f"cannot reserve {it.qty}x {it.product_id}")
            order = Order(
                order_id=f"ORD-{cart.cart_id}",
                lines=cart.items,
                breakdown=cart.breakdown(),
                idempotency_key=idempotency_key,
                customer_id=cart.customer_id,
            )
            # payment capture omitted (would call PaymentPort.charge(...))
            cart.mark_paid()
            self.inventory.commit(hold_id)
            return order

        return self.factory.create_once(idempotency_key, body, build)


# =========================================================================== #
#  Demo helpers
# =========================================================================== #
def banner(title: str) -> None:
    line = "=" * 78
    print(f"\n{line}\n{title}\n{line}")


def print_breakdown(bd: CartBreakdown) -> None:
    print(f"  subtotal             : {fmt(bd.subtotal):>10}  ({bd.subtotal} c)")
    for a in bd.adjustments:
        sign = "-" if a.scope in ("LINE", "CART") else "(waive)"
        tgt = a.line_id or "CART"
        print(f"    {a.rule_name:<38} [{a.scope}] {tgt:<5} "
              f"{sign}{fmt(a.amount_cents):>8}")
    print(f"  line discounts       : {fmt(bd.line_discount):>10}  (-)")
    print(f"  cart discounts       : {fmt(bd.cart_discount):>10}  (-)")
    print(f"  shipping             : {fmt(bd.shipping):>10}  (+)")
    print("  --------------------------------------------")
    print(f"  TOTAL                : {fmt(bd.total):>10}  ({bd.total} c)")


def build_demo_catalog() -> ProductCatalog:
    c = ProductCatalog()
    c.upsert("MOUSE",      "Wireless Mouse",   MoneyCents(5000))
    c.upsert("KEYBOARD",   "Mech Keyboard",    MoneyCents(7500))
    c.upsert("USB-CABLE",  "USB-C Cable 2m",   MoneyCents(1000))
    c.upsert("HEADPHONES", "Noise-Cancel HP",  MoneyCents(12000))
    return c


def build_demo_engine() -> PromotionEngine:
    return PromotionEngine([
        BuyOneGetOneFree("USB-CABLE", buy_qty=1, free_qty=1),
        BulkDiscount("MOUSE", threshold=2, percent=10),
        PercentOffCoupon("SAVE15", 15),
        FixedAmountOffCoupon("WELCOME5", 500),
        FreeShippingThreshold(15000),
    ])


# =========================================================================== #
#  Demo sections
# =========================================================================== #
def section_money_and_snapshot() -> None:
    banner("MONEY & PRODUCT SNAPSHOT -- integer cents + frozen price")

    print("""
  Money rule: store integer cents, NEVER float.
    In IEEE-754:  0.10 + 0.20 == 0.30000000000000004
    Over 1M orders that is a real ledger drift and a reconciliation headache.
    MoneyCents(10).plus(MoneyCents(20)) == MoneyCents(30), always.""")

    catalog = ProductCatalog()
    catalog.upsert("USB-CABLE", "USB-C Cable 2m", MoneyCents(1000))
    snap_at_add = catalog.snapshot("USB-CABLE")
    print(f"\n  snapshot at add time : unit_price = {snap_at_add.unit_price}")
    catalog.reprice("USB-CABLE", MoneyCents(1200))
    snap_after = catalog.snapshot("USB-CABLE")
    print(f"  catalog reprices to  : unit_price = {snap_after.unit_price}")
    print(f"  cart line still sees : unit_price = {snap_at_add.unit_price}  (frozen)")
    assert snap_at_add.unit_price.cents == 1000
    assert snap_after.unit_price.cents == 1200
    assert snap_at_add.unit_price.cents == 1000   # unchanged after reprice
    print("  [check] OK -- snapshot price is immutable across catalog reprices")


def section_state_machine() -> None:
    banner("CART STATE MACHINE -- Empty -> Active -> Checkout -> {Paid, Abandoned}")

    sm = CartStateMachine()
    print(f"\n  initial state        : {sm.state}")
    for label, target in [
        ("add first item",      ACTIVE),
        ("add another item",    ACTIVE),
        ("begin checkout",      CHECKOUT),
        ("payment captured",    PAID),
    ]:
        sm.transition(target)
        print(f"  {label:<20} -> {sm.state}")

    print("\n  full transition table:")
    for (frm, to), evt in STATE_TRANSITIONS.items():
        print(f"    {frm:<10} -> {to:<10}  on {evt}")

    sm2 = CartStateMachine()
    try:
        sm2.transition(PAID)               # EMPTY -> PAID is illegal
    except IllegalTransitionError as e:
        print("\n  illegal EMPTY -> PAID rejected:")
        print(f"    {e}")
    print("  [check] OK -- illegal transition raised IllegalTransitionError")


def section_pricing_rules() -> None:
    banner("PRICING RULES ENGINE -- BOGO, BulkDiscount, coupons, free shipping")

    catalog = build_demo_catalog()
    engine = build_demo_engine()
    items = [
        LineItem("L01", catalog.snapshot("MOUSE"),     2),    # 10000
        LineItem("L02", catalog.snapshot("USB-CABLE"), 4),    # 4000
    ]
    coupons = ["SAVE15", "WELCOME5"]

    print("\n  registered rules (Cart knows none of these -- engine owns them):")
    for r in engine.rules:
        layer_tag = "LINE" if r.layer == "LINE" else "CART"
        print(f"    [{layer_tag}] {r.name}")

    print(f"\n  items + coupons={coupons}:")
    for it in items:
        print(f"    {it}")

    adjs = engine.evaluate(items, coupons)
    subtotal = sum(it.line_total_cents for it in items)
    line_disc = sum(a.amount_cents for a in adjs if a.scope == "LINE")
    cart_disc = sum(a.amount_cents for a in adjs if a.scope == "CART")
    ship_w = sum(a.amount_cents for a in adjs if a.scope == "SHIP")
    shipping = max(0, 800 - ship_w)
    total = subtotal - line_disc - cart_disc + shipping

    print(f"\n  subtotal             : {fmt(subtotal):>10}")
    for a in adjs:
        sign = "-" if a.scope in ("LINE", "CART") else "(waive)"
        print(f"    {a.rule_name:<38} [{a.scope}] {sign}{fmt(a.amount_cents):>8}")
    print(f"  shipping             : {fmt(shipping):>10}")
    print(f"  TOTAL                : {fmt(total):>10}  ({total} c)")

    # Expected: BOGO 4//2*1*1000=2000; Bulk 10000*10//100=1000;
    # after_line=14000-3000=11000; SAVE15=11000*15//100=1650; WELCOME5=500;
    # post-line 11000 < 15000 -> shipping 800; total=11000-1650-500+800=9650
    assert total == 9650, f"expected 9650, got {total}"
    print("  [check] OK -- engine math matches hand-computed 9650")


def section_coupon_validation() -> None:
    banner("COUPON VALIDATION -- accept good, reject unknown + duplicate")

    catalog = build_demo_catalog()
    engine = build_demo_engine()
    cart = Cart("C1", None, "S1", catalog, engine=engine)
    cart.add_item("MOUSE", 1)

    cart.apply_coupon("SAVE15")
    print(f"  applied SAVE15       : coupons = {cart.coupons}")
    assert cart.coupons == ["SAVE15"]

    try:
        cart.apply_coupon("DOES_NOT_EXIST")
    except CouponError as e:
        print(f"  unknown coupon rejected: {e}")

    try:
        cart.apply_coupon("SAVE15")             # duplicate
    except CouponError as e:
        print(f"  duplicate coupon rejected: {e}")

    cart.remove_coupon("SAVE15")
    print(f"  removed SAVE15       : coupons = {cart.coupons}")
    assert cart.coupons == []
    print("  [check] OK -- coupon apply/remove/validation all enforced")


def section_inventory_and_state_guards() -> None:
    banner("INVENTORY PORT -- advisory on add, hard reserve at checkout")

    catalog = build_demo_catalog()
    inv = InMemoryInventory({"MOUSE": 2, "USB-CABLE": 100})
    cart = Cart("C2", None, "S2", catalog, inventory=inv, engine=build_demo_engine())

    cart.add_item("MOUSE", 2)
    print(f"  added 2x MOUSE       : stock left = {inv.stock_level('MOUSE')}")
    assert inv.stock_level("MOUSE") == 2        # advisory check does not decrement

    try:
        cart.add_item("MOUSE", 1)               # would need 3 total, only 2 in stock
    except InsufficientInventoryError as e:
        print(f"  advisory add blocked : {e}")

    # adding more than state allows is rejected by the state machine
    cart.begin_checkout()
    try:
        cart.add_item("USB-CABLE", 1)           # CHECKOUT state forbids add
    except IllegalTransitionError as e:
        print(f"  add in CHECKOUT blocked: {e}")
    cart.cancel_checkout()
    print(f"  cancelled checkout   : state = {cart.state}")
    print("  [check] OK -- inventory + state guards enforced")


def section_idempotent_checkout() -> None:
    banner("IDEMPOTENT CHECKOUT -- replay returns same Order; conflict raises")

    catalog = build_demo_catalog()
    inv = InMemoryInventory({"MOUSE": 100})
    factory = IdempotentOrderFactory()
    svc = CheckoutService(factory, inv)

    cart = Cart("C3", "cust-1", "S3", catalog, inventory=inv,
                engine=build_demo_engine())
    cart.add_item("MOUSE", 1)
    cart.apply_coupon("SAVE15")

    order1 = svc.submit(cart, "idem-abc")
    print(f"  submit #1            : {order1}")
    print(f"  factory size         : {len(factory)}")
    print(f"  cart state           : {cart.state}  (PAID)")

    order2 = svc.submit(cart, "idem-abc")       # replay, same key + same body
    print(f"  submit #2 (replay)   : {order2}")
    assert order1 is order2
    assert len(factory) == 1
    print(f"  factory size         : {len(factory)}  (no duplicate Order)")

    # same key but a different body -> conflict (Stripe semantics)
    cart2 = Cart("C4", "cust-2", "S4", catalog, inventory=inv,
                 engine=build_demo_engine())
    cart2.add_item("MOUSE", 3)
    try:
        svc.submit(cart2, "idem-abc")
    except IdempotencyConflictError as e:
        print(f"  key reuse w/ diff body rejected: {e}")
    print("  [check] OK -- exactly-once Order creation enforced")


def section_full_scenario() -> Cart:
    banner("FULL SCENARIO -- add items, apply coupons, price the cart")

    catalog = build_demo_catalog()
    inv = InMemoryInventory({
        "MOUSE": 50, "KEYBOARD": 50, "USB-CABLE": 200, "HEADPHONES": 50})
    cart = Cart("GOLD", "cust-1", "S-gold", catalog,
                inventory=inv, engine=build_demo_engine())

    print(f"\n  initial state        : {cart.state}")
    cart.add_item("MOUSE", 2)                   # 10000
    cart.add_item("KEYBOARD", 1)                #  7500
    cart.add_item("USB-CABLE", 4)               #  4000
    cart.add_item("HEADPHONES", 1)              # 12000
    print(f"  after adds           : state = {cart.state}, "
          f"{len(cart.items)} lines, version = {cart.version}")

    cart.apply_coupon("SAVE15")
    cart.apply_coupon("WELCOME5")
    print(f"  coupons applied      : {cart.coupons}")

    bd = cart.breakdown()
    print_breakdown(bd)
    return cart


def section_gold_check(gold_cart: Cart) -> None:
    banner("GOLD CHECK  (recomputed by shopping_cart.html in JS)")
    bd = gold_cart.breakdown()
    sig = bd.signature()
    gold_sig = "33500,3000,5075,0,25425"        # subtotal,line,cart,ship,total
    gold_total = 25425
    print(f"  breakdown.signature() = {sig}")
    print(f"  breakdown.total       = {bd.total} cents  ({fmt(bd.total)})")
    assert sig == gold_sig, f"signature mismatch: {sig} != {gold_sig}"
    assert bd.total == gold_total, f"total mismatch: {bd.total} != {gold_total}"
    print("  [check] OK")


# =========================================================================== #
if __name__ == "__main__":
    print("#" * 78)
    print("# SHOPPING CART & CHECKOUT -- aggregate, pricing engine, "
          "state machine, idempotent checkout")
    print("#" * 78)
    section_money_and_snapshot()
    section_state_machine()
    section_pricing_rules()
    section_coupon_validation()
    section_inventory_and_state_guards()
    section_idempotent_checkout()
    _gold = section_full_scenario()
    section_gold_check(_gold)
    print("\n[check] OK -- all sections ran")
