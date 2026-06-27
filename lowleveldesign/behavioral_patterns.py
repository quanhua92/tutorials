#!/usr/bin/env python3
"""Behavioral Design Patterns — Strategy, Observer, Command, State,
Template Method, Chain of Responsibility.

Ground-truth implementation. Pure Python stdlib only.

Companion artifacts:
    BEHAVIORAL_PATTERNS.md            — design guide (UML, SOLID, tradeoffs)
    behavioral_patterns.html          — interactive demos
    behavioral_patterns_output.txt    — captured stdout

Bundle catalog entry #02 in lowleveldesign/.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import deque
from typing import Dict, List, Optional


# =============================================================================
# 01 - STRATEGY  (algorithm family, swappable at runtime via composition)
# =============================================================================
# Signal: "Multiple ways to do X; switch at runtime without if/else chains."
# Decouples: algorithm from the context that uses it. Open/Closed compliant.
# =============================================================================

class SortStrategy(ABC):
    """Interface for a family of interchangeable sorting algorithms."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def sort(self, data: List[int]) -> List[int]:
        ...


class BubbleSort(SortStrategy):
    # O(n^2) - illustrative; production would never pick this for large data.
    @property
    def name(self) -> str:
        return "BubbleSort"

    def sort(self, data: List[int]) -> List[int]:
        arr = list(data)
        n = len(arr)
        for i in range(n):
            swapped = False
            for j in range(0, n - i - 1):
                if arr[j] > arr[j + 1]:
                    arr[j], arr[j + 1] = arr[j + 1], arr[j]
                    swapped = True
            if not swapped:
                break
        return arr


class QuickSort(SortStrategy):
    @property
    def name(self) -> str:
        return "QuickSort"

    def sort(self, data: List[int]) -> List[int]:
        if len(data) <= 1:
            return list(data)
        pivot = data[len(data) // 2]
        left = [x for x in data if x < pivot]
        mid = [x for x in data if x == pivot]
        right = [x for x in data if x > pivot]
        return self.sort(left) + mid + self.sort(right)


class DataProcessor:
    """Context. Holds a strategy and delegates work without knowing how it's done."""

    def __init__(self, strategy: SortStrategy) -> None:
        self._strategy = strategy

    def set_strategy(self, strategy: SortStrategy) -> None:
        # Swap at runtime - no if/else, no constructor change.
        self._strategy = strategy

    @property
    def strategy_name(self) -> str:
        return self._strategy.name

    def process(self, data: List[int]) -> List[int]:
        return self._strategy.sort(data)


# =============================================================================
# 02 - OBSERVER  (publish/subscribe, fan-out notification)
# =============================================================================
# Signal: "When X changes, multiple independent components should react."
# Decouples: Subject from its dependents. Subject knows only the Observer interface.
# Pitfall: forgotten subscriptions leak memory; snapshot the list before notifying.
# =============================================================================

class Observer(ABC):
    @abstractmethod
    def update(self, event: str, payload: dict) -> None:
        ...


class Subject:
    """Maintains a list of observers; notifies them on state change."""

    def __init__(self) -> None:
        self._observers: List[Observer] = []

    def subscribe(self, observer: Observer) -> None:
        if observer not in self._observers:
            self._observers.append(observer)

    def unsubscribe(self, observer: Observer) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    @property
    def subscriber_count(self) -> int:
        return len(self._observers)

    def _notify(self, event: str, payload: dict) -> None:
        # Snapshot guards against concurrent modification mid-iteration.
        for observer in list(self._observers):
            observer.update(event, payload)


class OrderService(Subject):
    """Concrete subject. A state change fans out to every subscriber."""

    def __init__(self) -> None:
        super().__init__()
        self._orders: Dict[str, dict] = {}

    def place_order(self, order_id: str, amount: float) -> None:
        self._orders[order_id] = {"amount": amount, "status": "PLACED"}
        self._notify("ORDER_PLACED", {"order_id": order_id, "amount": amount})


class EmailNotifier(Observer):
    def update(self, event: str, payload: dict) -> None:
        print(f"    [EmailNotifier]     event={event} -> send confirmation for {payload['order_id']}")


class InventoryService(Observer):
    def update(self, event: str, payload: dict) -> None:
        print(f"    [InventoryService]  event={event} -> reserve stock for {payload['order_id']}")


class FraudAnalyzer(Observer):
    def update(self, event: str, payload: dict) -> None:
        risk = "REVIEW" if payload["amount"] > 1000.0 else "OK"
        print(f"    [FraudAnalyzer]     event={event} -> risk={risk} amount={payload['amount']:.1f}")


# =============================================================================
# 03 - COMMAND  (encapsulate a request as an object; enables undo / queue / log)
# =============================================================================
# Signal: "Need to queue operations, support undo, or log all actions."
# Decouples: invoker from receiver. The command object knows the receiver.
# Replay guard: a Set of applied command ids makes re-execution idempotent.
# =============================================================================

class Command(ABC):
    @property
    @abstractmethod
    def id(self) -> str:
        """Stable id used by the history's idempotency guard."""

    @abstractmethod
    def execute(self) -> None:
        ...

    @abstractmethod
    def undo(self) -> None:
        ...


class TextDocument:
    """Receiver - knows how to perform the actual operations."""

    def __init__(self) -> None:
        self.text: str = ""

    def insert(self, position: int, text: str) -> None:
        self.text = self.text[:position] + text + self.text[position:]

    def delete(self, position: int, length: int) -> None:
        self.text = self.text[:position] + self.text[position + length:]


class InsertTextCommand(Command):
    def __init__(self, doc: TextDocument, position: int, text: str, cmd_id: str) -> None:
        self._doc = doc
        self._position = position
        self._text = text
        self._id = cmd_id

    @property
    def id(self) -> str:
        return self._id

    def execute(self) -> None:
        self._doc.insert(self._position, self._text)

    def undo(self) -> None:
        self._doc.delete(self._position, len(self._text))


class CommandHistory:
    """Invoker. Executes commands, tracks an undo stack, and guards replays."""

    def __init__(self) -> None:
        self._stack: "deque[Command]" = deque()
        self._applied: set = set()

    @property
    def depth(self) -> int:
        return len(self._stack)

    def execute(self, command: Command) -> None:
        if command.id in self._applied:
            print(f"    [replay-guard] skip duplicate command id={command.id}")
            return
        command.execute()
        self._applied.add(command.id)
        self._stack.append(command)

    def undo(self) -> None:
        if not self._stack:
            print("    [undo] nothing to undo")
            return
        command = self._stack.pop()
        command.undo()
        print(f"    [undo] reverted command id={command.id}")


# =============================================================================
# 04 - STATE  (behavior changes with internal state; object becomes a state machine)
# =============================================================================
# Signal: "Operations behave differently depending on the object's current status."
# Decouples: state-specific behavior from the object holding the state.
# Contrast: if every state has the SAME methods and only valid TRANSITIONS differ,
#           a transition table is simpler. Use State for polymorphic behavior.
# =============================================================================

class OrderState(ABC):
    """Each state implements every operation the order can receive."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def pay(self, order: "OrderContext") -> None:
        ...

    @abstractmethod
    def ship(self, order: "OrderContext") -> None:
        ...

    @abstractmethod
    def cancel(self, order: "OrderContext") -> None:
        ...


class CreatedState(OrderState):
    @property
    def name(self) -> str:
        return "CREATED"

    def pay(self, order: "OrderContext") -> None:
        order._transition(PaidState())

    def ship(self, order: "OrderContext") -> None:
        raise RuntimeError("cannot SHIP a CREATED order (not paid)")

    def cancel(self, order: "OrderContext") -> None:
        order._transition(CancelledState())


class PaidState(OrderState):
    @property
    def name(self) -> str:
        return "PAID"

    def pay(self, order: "OrderContext") -> None:
        print("    already paid - no transition")

    def ship(self, order: "OrderContext") -> None:
        order._transition(ShippedState())

    def cancel(self, order: "OrderContext") -> None:
        print("    refunding then cancelling")
        order._transition(CancelledState())


class ShippedState(OrderState):
    @property
    def name(self) -> str:
        return "SHIPPED"

    def pay(self, order: "OrderContext") -> None:
        print("    already paid - no transition")

    def ship(self, order: "OrderContext") -> None:
        print("    already shipped - no transition")

    def cancel(self, order: "OrderContext") -> None:
        raise RuntimeError("cannot CANCEL a SHIPPED order (in transit)")


class CancelledState(OrderState):
    @property
    def name(self) -> str:
        return "CANCELLED"

    def pay(self, order: "OrderContext") -> None:
        raise RuntimeError("cannot PAY a CANCELLED order")

    def ship(self, order: "OrderContext") -> None:
        raise RuntimeError("cannot SHIP a CANCELLED order")

    def cancel(self, order: "OrderContext") -> None:
        print("    already cancelled - no transition")


class OrderContext:
    """Holds a reference to the current state; delegates every op to it."""

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        self._state: OrderState = CreatedState()

    @property
    def state(self) -> OrderState:
        return self._state

    def _transition(self, state: OrderState) -> None:
        print(f"    {self._state.name} -> {state.name}")
        self._state = state

    def pay(self) -> None:
        self._state.pay(self)

    def ship(self) -> None:
        self._state.ship(self)

    def cancel(self) -> None:
        self._state.cancel(self)


# =============================================================================
# 05 - TEMPLATE METHOD  (algorithm skeleton in base class; steps overridden)
# =============================================================================
# Signal: "Same overall process, different specific steps."
# Decouples: skeleton from step implementations (inheritance-based).
# Hollywood Principle: "don't call us, we'll call you" - base calls subclass hooks.
# Rule: Template Method when the skeleton is stable; Strategy when it may swap.
# =============================================================================

class DataParser(ABC):
    """Skeleton: read -> parse -> validate -> save. Steps are extension points."""

    def parse(self, source: str) -> object:
        # template_method - final structure; subclasses do NOT override this.
        raw = self.read(source)
        data = self.do_parse(raw)
        self.validate(data)
        self.save(data)
        return data

    @abstractmethod
    def read(self, source: str) -> str:
        ...

    @abstractmethod
    def do_parse(self, raw: str) -> object:
        ...

    def validate(self, data: object) -> None:
        # hook with a default no-op; subclasses MAY override.
        pass

    def save(self, data: object) -> None:
        size = len(data) if hasattr(data, "__len__") else 1
        print(f"    [save] persisted {size} record(s) to db")


class CsvParser(DataParser):
    def read(self, source: str) -> str:
        print(f"    [CsvParser.read]     opened '{source}'")
        return "alice,30\nbob,25"

    def do_parse(self, raw: str) -> List[dict]:
        rows = [line.split(",") for line in raw.strip().splitlines()]
        records = [{"name": r[0], "age": int(r[1])} for r in rows]
        print(f"    [CsvParser.parse]    {len(records)} record(s)")
        return records

    def validate(self, data: List[dict]) -> None:
        if any(r["age"] < 0 for r in data):
            raise ValueError("negative age")
        print(f"    [CsvParser.validate] all ages non-negative")


class JsonParser(DataParser):
    def read(self, source: str) -> str:
        print(f"    [JsonParser.read]    GET {source}")
        return '{"users":[{"name":"carol","age":40}]}'

    def do_parse(self, raw: str) -> List[dict]:
        obj = json.loads(raw)
        print(f"    [JsonParser.parse]   parsed object keys={list(obj.keys())}")
        return obj["users"]

    def validate(self, data: List[dict]) -> None:
        for r in data:
            assert "name" in r and "age" in r, "missing field"
        print(f"    [JsonParser.validate] schema OK")


# =============================================================================
# 06 - CHAIN OF RESPONSIBILITY  (request passes through a linked pipeline)
# =============================================================================
# Signal: "Multiple handlers may process a request; add/remove at runtime."
# Decouples: sender from concrete handler. Each handler decides to handle or pass.
# Order matters: auth before rate-limit before business logic.
# =============================================================================

class HttpRequest:
    def __init__(self, path: str, token: Optional[str] = None, ip: str = "0.0.0.0") -> None:
        self.path = path
        self.token = token
        self.ip = ip
        self.status: int = 0
        self.logs: List[str] = []


class Handler(ABC):
    def __init__(self) -> None:
        self._next: Optional[Handler] = None

    def set_next(self, handler: "Handler") -> "Handler":
        self._next = handler
        return handler  # fluent: a.set_next(b).set_next(c)

    @abstractmethod
    def handle(self, request: HttpRequest) -> bool:
        """Return True to continue down the chain, False to short-circuit."""

    def _pass(self, request: HttpRequest) -> bool:
        if self._next is None:
            request.status = 200
            return True
        return self._next.handle(request)


class AuthHandler(Handler):
    def handle(self, request: HttpRequest) -> bool:
        if not request.token:
            request.status = 401
            request.logs.append("AuthHandler: missing token -> 401")
            return False
        request.logs.append("AuthHandler: token present")
        return self._pass(request)


class RateLimitHandler(Handler):
    def __init__(self, limit_per_ip: Dict[str, int]) -> None:
        super().__init__()
        self._limit = limit_per_ip

    def handle(self, request: HttpRequest) -> bool:
        remaining = self._limit.get(request.ip, 0)
        if remaining <= 0:
            request.status = 429
            request.logs.append(f"RateLimitHandler: ip={request.ip} exhausted -> 429")
            return False
        self._limit[request.ip] = remaining - 1
        request.logs.append(
            f"RateLimitHandler: ip={request.ip} remaining={self._limit[request.ip]}"
        )
        return self._pass(request)


class LogHandler(Handler):
    def handle(self, request: HttpRequest) -> bool:
        request.logs.append(f"LogHandler: {request.path} allowed")
        return self._pass(request)


# =============================================================================
# DEMO SCENARIOS
# =============================================================================

def _banner(title: str) -> None:
    line = "=" * 72
    print(f"\n{line}\n=== {title}\n{line}")


def demo_strategy() -> None:
    _banner("STRATEGY - interchangeable sorting algorithms")
    data = [5, 2, 8, 1, 9, 3]
    print(f"  data={data}")

    processor = DataProcessor(BubbleSort())
    print(f"  strategy={processor.strategy_name}  ->  {processor.process(data)}")

    # Swap at runtime - no if/else, no constructor change. Open/Closed.
    processor.set_strategy(QuickSort())
    print(f"  strategy={processor.strategy_name}  ->  {processor.process(data)}")

    bubble = BubbleSort().sort(data)
    quick = QuickSort().sort(data)
    assert bubble == quick == sorted(data), "strategies disagree!"
    print("[check] OK - both strategies sort identically")


def demo_observer() -> None:
    _banner("OBSERVER - fan-out on order placement")
    service = OrderService()
    email, inv, fraud = EmailNotifier(), InventoryService(), FraudAnalyzer()

    service.subscribe(email)
    service.subscribe(inv)
    service.subscribe(fraud)

    print(f"  subscribers={service.subscriber_count}")
    print("  place small order (3 subscribers):")
    service.place_order("ORD-1", amount=99.0)

    print("  unsubscribe InventoryService, place large order (2 subscribers):")
    service.unsubscribe(inv)
    service.place_order("ORD-2", amount=2500.0)

    # Gold-check: a fresh subject with exactly 2 subscribers fires exactly 2 updates.
    counter = {"n": 0}

    class Counter(Observer):
        def update(self, event: str, payload: dict) -> None:
            counter["n"] += 1

    probe = OrderService()
    probe.subscribe(Counter())
    probe.subscribe(Counter())
    probe.place_order("ORD-X", amount=10.0)
    assert counter["n"] == 2, f"expected 2 notifications, got {counter['n']}"
    print("[check] OK - 2 subscribers => 2 notifications")


def demo_command() -> None:
    _banner("COMMAND - text editor with undo + replay guard")
    doc = TextDocument()
    history = CommandHistory()

    history.execute(InsertTextCommand(doc, 0, "Hello", "c1"))
    print(f"  text='{doc.text}'  depth={history.depth}")

    history.execute(InsertTextCommand(doc, 5, ", World", "c2"))
    print(f"  text='{doc.text}'  depth={history.depth}")

    # Replay guard: same command id must be a no-op.
    history.execute(InsertTextCommand(doc, 0, "SHOULD-NOT-APPEAR", "c2"))
    print(f"  text after duplicate replay='{doc.text}'")

    history.undo()
    print(f"  text after 1 undo='{doc.text}'  depth={history.depth}")
    history.undo()
    print(f"  text after 2 undos='{doc.text}'  depth={history.depth}")

    assert doc.text == "", "undo should have restored the empty document"
    assert history.depth == 0, "history should be empty"
    print("[check] OK - undo restored empty doc, history empty")


def demo_state() -> None:
    _banner("STATE - order lifecycle (CREATED -> PAID -> SHIPPED)")
    order = OrderContext("ORD-42")
    print(f"  initial state: {order.state.name}")

    order.pay()
    print(f"  after pay():   {order.state.name}")

    # pay() again - PaidState handles gracefully (no transition, no exception).
    order.pay()
    print(f"  after pay():   {order.state.name}")

    order.ship()
    print(f"  after ship():  {order.state.name}")

    # ship() again - ShippedState is a no-op.
    order.ship()
    assert order.state.name == "SHIPPED"
    print("[check] OK - terminal state SHIPPED reached idempotently")


def demo_template_method() -> None:
    _banner("TEMPLATE METHOD - fixed skeleton, swappable steps")
    print("  -- CsvParser --")
    CsvParser().parse("users.csv")
    print("  -- JsonParser --")
    JsonParser().parse("https://api.example.com/users")

    # Verify the skeleton runs all 4 steps in order for any subclass.
    seen: List[str] = []

    class Tracer(DataParser):
        def read(self, source: str) -> str:
            seen.append("read")
            return ""

        def do_parse(self, raw: str) -> object:
            seen.append("parse")
            return []

        def validate(self, data: object) -> None:
            seen.append("validate")

        def save(self, data: object) -> None:
            seen.append("save")

    Tracer().parse("x")
    assert seen == ["read", "parse", "validate", "save"], f"step order wrong: {seen}"
    print(f"[check] OK - skeleton order={seen}")


def demo_chain() -> None:
    _banner("CHAIN OF RESPONSIBILITY - auth -> rate-limit -> log pipeline")
    limiter_state = {"1.2.3.4": 2}  # this IP gets 2 requests

    def build_chain() -> Handler:
        auth = AuthHandler()
        rate = RateLimitHandler(limiter_state)
        log = LogHandler()
        auth.set_next(rate).set_next(log)  # fluent linking
        return auth

    # Case 1: no token -> short-circuits at Auth (401), RateLimit untouched.
    r1 = HttpRequest(path="/api/orders")
    build_chain().handle(r1)
    print(f"  no-token request: status={r1.status}")
    for line in r1.logs:
        print(f"    {line}")

    # Case 2: valid token, three calls; third trips the rate limiter (429).
    auth = build_chain()
    statuses: List[int] = []
    for _ in range(3):
        req = HttpRequest(path="/api/orders", token="abc", ip="1.2.3.4")
        auth.handle(req)
        statuses.append(req.status)
    print(f"  with-token (3 calls): statuses={statuses}")

    assert statuses == [200, 200, 429], f"unexpected statuses={statuses}"
    print("[check] OK - first two pass, third is rate-limited")


def main() -> None:
    print("BEHAVIORAL DESIGN PATTERNS")
    print("Strategy | Observer | Command | State | Template Method | Chain of Responsibility")
    demo_strategy()
    demo_observer()
    demo_command()
    demo_state()
    demo_template_method()
    demo_chain()
    print("\n" + "=" * 72)
    print("[check] OK - all six behavioral patterns demonstrated and verified")
    print("=" * 72)


if __name__ == "__main__":
    main()
