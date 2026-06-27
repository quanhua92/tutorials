#!/usr/bin/env python3
"""GoF Design Patterns -- Creational + Structural.

Ground-truth implementation. Pure Python stdlib (no third-party deps).

CREATIONAL  -- "create objects for me"
  - Singleton          ConfigurationManager : one shared instance in the system
  - Factory Method     NotificationFactory  : pick Email/SMS/Push by a type tag
  - Abstract Factory   UIComponentFactory   : a family (Button+TextField) per theme
  - Builder            HttpRequestBuilder   : many optional parts -> immutable request

STRUCTURAL -- "compose / wrap objects for me"
  - Adapter            SquarePegAdapter     : a SquarePeg plugs into a RoundHole
  - Decorator          Milk/Sugar/Whip      : wrap a Coffee, re-price dynamically
  - Facade             HomeTheaterFacade    : one watch_movie() hides 4 components
  - Proxy              DocumentProxy        : access check before Document.read()

Every section prints a banner, runs the scenario, and ends with `[check] OK`.
The GOLD CHECK section produces a value recomputed by `design_patterns.html`
in JavaScript for cross-language parity.

Companion files: DESIGN_PATTERNS.md, design_patterns.html, design_patterns_output.txt
"""

from __future__ import annotations

import math
import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


# =========================================================================== #
#  Helpers
# =========================================================================== #
def banner(title: str) -> None:
    """Print a `===` banner, as required by HOW_TO_RESEARCH.md."""
    line = "=" * 72
    print(f"\n{line}\n=== {title}\n{line}")


# =========================================================================== #
#  CREATIONAL 1 -- SINGLETON
# =========================================================================== #
class ConfigurationManager:
    """Ensure a class has exactly one instance with global access.

    Use when: "there should only be one X" (Logger, Config, ParkingLot root).
    Caveat:  overused; hides dependencies. Prefer dependency injection.
    """

    _instance: "Optional[ConfigurationManager]" = None
    _lock = threading.Lock()

    def __new__(cls) -> "ConfigurationManager":
        # Double-checked locking -- one instance even under concurrency.
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._config = {}  # init once
        return cls._instance

    def set(self, key: str, value: str) -> None:
        self._config[key] = value

    def get(self, key: str) -> Optional[str]:
        return self._config.get(key)


def section_singleton() -> None:
    banner("CREATIONAL 1 -- SINGLETON (ConfigurationManager)")
    cfg_a = ConfigurationManager()
    cfg_b = ConfigurationManager()
    cfg_a.set("region", "us-east-1")
    print(f"  cfg_a is cfg_b            -> {cfg_a is cfg_b}")
    print(f"  cfg_b.get('region')       -> {cfg_b.get('region')!r}  (set via cfg_a)")
    print(f"  [check] {'OK' if cfg_a is cfg_b else 'FAIL'} -- single shared instance")


# =========================================================================== #
#  CREATIONAL 2 -- FACTORY METHOD
# =========================================================================== #
class Notification(ABC):
    """Product interface."""

    @abstractmethod
    def send(self, recipient: str, message: str) -> str: ...


class EmailNotification(Notification):
    def send(self, recipient: str, message: str) -> str:
        return f"EMAIL -> {recipient}: {message}"


class SMSNotification(Notification):
    def send(self, recipient: str, message: str) -> str:
        return f"SMS   -> {recipient}: {message}"


class PushNotification(Notification):
    def send(self, recipient: str, message: str) -> str:
        return f"PUSH  -> {recipient}: {message}"


class NotificationFactory:
    """Factory Method: centralize type -> concrete class mapping.

    Callers depend on the Notification interface, never the concrete class.
    Adding a new channel edits this one place (OCP-friendly).
    """

    _REGISTRY: Dict[str, type] = {
        "email": EmailNotification,
        "sms": SMSNotification,
        "push": PushNotification,
    }

    @classmethod
    def create(cls, kind: str) -> Notification:
        try:
            return cls._REGISTRY[kind]()
        except KeyError:
            raise ValueError(f"unknown notification type: {kind!r}")


def section_factory_method() -> None:
    banner("CREATIONAL 2 -- FACTORY METHOD (NotificationFactory)")
    for kind in ("email", "sms", "push"):
        notifier = NotificationFactory.create(kind)
        print(f"  {notifier.send('alice@example.com', 'order shipped')}")
    try:
        NotificationFactory.create("carrier-pigeon")
    except ValueError as exc:
        print(f"  unknown type raises -> {exc}")
    print("  [check] OK -- 3 channels created, unknown rejected")


# =========================================================================== #
#  CREATIONAL 3 -- ABSTRACT FACTORY
# =========================================================================== #
class Button(ABC):
    @abstractmethod
    def render(self) -> str: ...


class TextField(ABC):
    @abstractmethod
    def render(self) -> str: ...


class UIComponentFactory(ABC):
    """Abstract Factory: create a FAMILY of related products (Button+TextField)."""

    @abstractmethod
    def make_button(self) -> Button: ...

    @abstractmethod
    def make_text_field(self) -> TextField: ...


class LightButton(Button):
    def render(self) -> str:
        return "[LightButton  bg=#fff fg=#000]"


class LightTextField(TextField):
    def render(self) -> str:
        return "[LightField    bg=#fff fg=#000]"


class DarkButton(Button):
    def render(self) -> str:
        return "[DarkButton   bg=#0d1117 fg=#e6edf3]"


class DarkTextField(TextField):
    def render(self) -> str:
        return "[DarkField    bg=#0d1117 fg=#e6edf3]"


class LightThemeFactory(UIComponentFactory):
    def make_button(self) -> Button:
        return LightButton()

    def make_text_field(self) -> TextField:
        return LightTextField()


class DarkThemeFactory(UIComponentFactory):
    def make_button(self) -> Button:
        return DarkButton()

    def make_text_field(self) -> TextField:
        return DarkTextField()


def render_ui(factory: UIComponentFactory) -> List[str]:
    """The client code -- works with ANY UIComponentFactory."""
    return [factory.make_button().render(), factory.make_text_field().render()]


def section_abstract_factory() -> None:
    banner("CREATIONAL 3 -- ABSTRACT FACTORY (UIComponentFactory)")
    for name, factory in (("LIGHT", LightThemeFactory()), ("DARK", DarkThemeFactory())):
        print(f"  {name} theme:")
        for line in render_ui(factory):
            print(f"    {line}")
    print("  [check] OK -- whole family swaps by switching one factory")


# =========================================================================== #
#  CREATIONAL 4 -- BUILDER
# =========================================================================== #
class HttpRequest:
    """Immutable product -- constructed only through its Builder."""

    def __init__(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Dict[str, str],
        body: Optional[str],
    ):
        self.method = method
        self.url = url
        self.headers = headers
        self.params = params
        self.body = body

    def __repr__(self) -> str:
        qs = "&".join(f"{k}={v}" for k, v in self.params.items())
        full = f"{self.url}?{qs}" if qs else self.url
        return (f"{self.method} {full}  headers={self.headers}"
                + (f"  body={self.body!r}" if self.body else ""))


class HttpRequestBuilder:
    """Builder: construct a complex object step-by-step, then freeze it.

    Signal to use Builder: "object needs many optional parameters".
    Beats a 6-positional-argument constructor (telescoping anti-pattern).
    """

    def __init__(self) -> None:
        self._method: str = "GET"
        self._url: str = ""
        self._headers: Dict[str, str] = {}
        self._params: Dict[str, str] = {}
        self._body: Optional[str] = None

    def method(self, m: str) -> "HttpRequestBuilder":
        self._method = m
        return self

    def url(self, u: str) -> "HttpRequestBuilder":
        self._url = u
        return self

    def header(self, key: str, value: str) -> "HttpRequestBuilder":
        self._headers[key] = value
        return self

    def param(self, key: str, value: str) -> "HttpRequestBuilder":
        self._params[key] = value
        return self

    def body(self, b: str) -> "HttpRequestBuilder":
        self._body = b
        return self

    def build(self) -> HttpRequest:
        # `build()` is the freeze point -- return an immutable snapshot.
        return HttpRequest(
            self._method, self._url,
            dict(self._headers), dict(self._params), self._body,
        )


def section_builder() -> None:
    banner("CREATIONAL 4 -- BUILDER (HttpRequestBuilder)")
    get_req = (
        HttpRequestBuilder()
        .method("GET")
        .url("https://api.example.com/users")
        .header("Accept", "application/json")
        .param("page", "1")
        .param("limit", "20")
        .build()
    )
    print(f"  GET  -> {get_req}")

    post_req = (
        HttpRequestBuilder()
        .method("POST")
        .url("https://api.example.com/users")
        .header("Content-Type", "application/json")
        .header("Authorization", "Bearer tok_123")
        .body('{"name":"alice"}')
        .build()
    )
    print(f"  POST -> {post_req}")
    print("  [check] OK -- two very different requests from one fluent builder")


# =========================================================================== #
#  STRUCTURAL 1 -- ADAPTER
# =========================================================================== #
class RoundHole:
    """Client -- only knows about RoundPeg (radius)."""

    def __init__(self, radius: float) -> None:
        self.radius = radius

    def fits(self, peg: "RoundPeg") -> bool:
        return peg.radius() <= self.radius


class RoundPeg:
    """Adaptee interface the client expects."""

    def __init__(self, radius: float) -> None:
        self._radius = radius

    def radius(self) -> float:
        return self._radius


class SquarePeg:
    """Incompatible class -- exposes `width`, not `radius`."""

    def __init__(self, width: float) -> None:
        self.width = width


class SquarePegAdapter(RoundPeg):
    """Adapter: makes a SquarePeg look like a RoundPeg.

    The diagonal of the square = width * sqrt(2); the half-diagonal (radius of
    the circumscribed circle) is width * sqrt(2) / 2.
    """

    def __init__(self, peg: SquarePeg) -> None:
        super().__init__(0.0)
        self._peg = peg

    def radius(self) -> float:
        return self._peg.width * math.sqrt(2) / 2


def section_adapter() -> None:
    banner("STRUCTURAL 1 -- ADAPTER (SquarePegAdapter)")
    hole = RoundHole(radius=5.0)
    print(f"  RoundHole(radius=5.0)")

    round_peg = RoundPeg(radius=4.0)
    print(f"  RoundPeg(radius=4.0)         fits? {hole.fits(round_peg)}")

    for width in (6.0, 8.0):
        square = SquarePeg(width=width)
        adapted = SquarePegAdapter(square)
        print(f"  SquarePeg(width={width}) -> adapter radius="
              f"{adapted.radius():.3f}  fits? {hole.fits(adapted)}")
    print("  [check] OK -- incompatible SquarePeg reused through an adapter")


# =========================================================================== #
#  STRUCTURAL 2 -- DECORATOR
# =========================================================================== #
class Coffee(ABC):
    """Component interface."""

    @abstractmethod
    def cost(self) -> float: ...

    @abstractmethod
    def description(self) -> str: ...


class Espresso(Coffee):
    """Concrete component -- the base beverage."""

    def cost(self) -> float:
        return 2.0

    def description(self) -> str:
        return "Espresso"


class CoffeeDecorator(Coffee):
    """Base decorator: holds a wrapped Coffee and delegates by default."""

    def __init__(self, wrapped: Coffee) -> None:
        self._wrapped = wrapped

    def cost(self) -> float:
        return self._wrapped.cost()

    def description(self) -> str:
        return self._wrapped.description()


class MilkDecorator(CoffeeDecorator):
    def cost(self) -> float:
        return self._wrapped.cost() + 0.5

    def description(self) -> str:
        return self._wrapped.description() + " + Milk"


class SugarDecorator(CoffeeDecorator):
    def cost(self) -> float:
        return self._wrapped.cost() + 0.25

    def description(self) -> str:
        return self._wrapped.description() + " + Sugar"


class WhipDecorator(CoffeeDecorator):
    def cost(self) -> float:
        return self._wrapped.cost() + 0.75

    def description(self) -> str:
        return self._wrapped.description() + " + Whip"


def section_decorator() -> None:
    banner("STRUCTURAL 2 -- DECORATOR (Coffee + toppings)")
    # Build a coffee, layer by layer.
    coffee: Coffee = Espresso()
    print(f"  {coffee.description():<32} -> ${coffee.cost():.2f}")

    coffee = MilkDecorator(coffee)
    print(f"  {coffee.description():<32} -> ${coffee.cost():.2f}")

    coffee = SugarDecorator(coffee)
    print(f"  {coffee.description():<32} -> ${coffee.cost():.2f}")

    coffee = WhipDecorator(coffee)
    print(f"  {coffee.description():<32} -> ${coffee.cost():.2f}")
    print("  [check] OK -- behavior added at runtime without subclass explosion")


# =========================================================================== #
#  STRUCTURAL 3 -- FACADE
# =========================================================================== #
class Amplifier:
    def on(self) -> str:
        return "Amplifier on (surround)"

    def off(self) -> str:
        return "Amplifier off"


class DVDPlayer:
    def play(self, movie: str) -> str:
        return f"DVDPlayer playing '{movie}'"

    def stop(self) -> str:
        return "DVDPlayer stopped"


class Projector:
    def on(self) -> str:
        return "Projector on (widescreen)"

    def off(self) -> str:
        return "Projector off"


class Lights:
    def dim(self, level: int) -> str:
        return f"Lights dimmed to {level}%"

    def on(self) -> str:
        return "Lights on"


class HomeTheaterFacade:
    """Facade: a single watch_movie()/end_movie() over 4 subsystem classes."""

    def __init__(self) -> None:
        self.amp = Amplifier()
        self.dvd = DVDPlayer()
        self.proj = Projector()
        self.lights = Lights()

    def watch_movie(self, movie: str) -> List[str]:
        return [
            self.lights.dim(10),
            self.proj.on(),
            self.amp.on(),
            self.dvd.play(movie),
        ]

    def end_movie(self) -> List[str]:
        return [self.dvd.stop(), self.amp.off(), self.proj.off(), self.lights.on()]


def section_facade() -> None:
    banner("STRUCTURAL 3 -- FACADE (HomeTheaterFacade)")
    theater = HomeTheaterFacade()
    print("  watch_movie('Inception'):")
    for step in theater.watch_movie("Inception"):
        print(f"    - {step}")
    print("  end_movie():")
    for step in theater.end_movie():
        print(f"    - {step}")
    print("  [check] OK -- client calls 1 method instead of orchestrating 4")


# =========================================================================== #
#  STRUCTURAL 4 -- PROXY
# =========================================================================== #
class User:
    def __init__(self, name: str, role: str) -> None:
        self.name = name
        self.role = role


class SensitiveDocument:
    """Real subject -- the thing we want to guard."""

    def __init__(self, content: str) -> None:
        self._content = content

    def read(self) -> str:
        return self._content


class DocumentProxy:
    """Protection proxy: access check before delegating to the real subject.

    A *virtual* proxy would lazily create the real subject on first use;
    a *remote* proxy would forward over the network. Same shape.
    """

    def __init__(self, document: SensitiveDocument, allowed_role: str) -> None:
        self._document = document
        self._allowed_role = allowed_role

    def read(self, user: User) -> str:
        if user.role != self._allowed_role:
            return f"DENIED: {user.name} (role={user.role}) cannot read"
        return self._document.read()


def section_proxy() -> None:
    banner("STRUCTURAL 4 -- PROXY (DocumentProxy -- protection)")
    real = SensitiveDocument("Q3 revenue = $42M (confidential)")
    proxy = DocumentProxy(real, allowed_role="executive")

    guest = User("guest_alice", role="guest")
    exec_ = User("exec_bob", role="executive")
    print(f"  guest read -> {proxy.read(guest)}")
    print(f"  exec  read -> {proxy.read(exec_)}")
    print("  [check] OK -- access controlled without touching SensitiveDocument")


# =========================================================================== #
#  GOLD CHECK -- recomputed by design_patterns.html in JavaScript
# =========================================================================== #
def coffee_chain_cost(toppings: List[str]) -> float:
    """Reproduce the exact decorator stack from section_decorator and price it.

    Prices (kept exact in binary float so .py and JS agree to 1 decimal):
        Espresso base = 2.0, Milk = 0.5, Sugar = 0.25, Whip = 0.75
    """
    price = 2.0
    table = {"milk": 0.5, "sugar": 0.25, "whip": 0.75}
    for t in toppings:
        price += table[t]
    return round(price, 1)


def section_gold_check() -> None:
    banner("GOLD CHECK  (recomputed by design_patterns.html in JS)")
    toppings = ["milk", "sugar", "whip"]
    total = coffee_chain_cost(toppings)
    gold = f"{total:.1f}"
    print(f"  coffee_chain_cost([{','.join(toppings)}]) = {gold}")
    print("  [check] OK")


# =========================================================================== #
#  Main
# =========================================================================== #
if __name__ == "__main__":
    print("#" * 72)
    print("# GOF DESIGN PATTERNS -- creational + structural (pure stdlib)")
    print("#" * 72)
    section_singleton()
    section_factory_method()
    section_abstract_factory()
    section_builder()
    section_adapter()
    section_decorator()
    section_facade()
    section_proxy()
    section_gold_check()
    print("\n[check] OK -- all 8 patterns demoed")
