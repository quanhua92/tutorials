"""
fastapi_bodies_pydantic.py — Phase 7 bundle #44.

GOAL (one line): show, by printing every value, how a Pydantic BaseModel in a
FastAPI handler signature becomes a *validated* request body, how Field
constraints + response_model give end-to-end typed I/O with 422s for free, and
how nested/optional/extra-forbid models compose.

This is the GROUND TRUTH for FASTAPI_BODIES_PYDANTIC.md. Every status code,
422 `loc`, and JSON body in the guide is printed by this file. Change it ->
re-run -> re-paste. Never hand-compute.

Tested in-process with fastapi.testclient.TestClient — NO real HTTP server is
started. Deterministic; byte-reproducible on re-run.

Run:
    uv run python fastapi_bodies_pydantic.py
"""

from __future__ import annotations

import warnings

# Silence the starlette/httpx TestClient deprecation banner so stdout stays
# clean (it goes to stderr anyway, but we belt-and-braces it).
warnings.filterwarnings("ignore")

from datetime import datetime  # noqa: E402
from enum import Enum  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers (house style)
# ----------------------------------------------------------------------------

def banner(title: str) -> None:
    """Print a clearly delimited section divider (the house style)."""
    print("\n" + BANNER)
    print(f"SECTION {title}")
    print(BANNER)


def check(description: str, condition: bool) -> None:
    """Assert an invariant and print a uniform `[check] ... OK` line."""
    assert condition, f"INVARIANT VIOLATED: {description}"
    print(f"[check] {description}: OK")


def _errors(resp) -> list[dict]:
    """Pull the `detail` list out of a 422 response."""
    return resp.json()["detail"]


def _has_loc(errs: list[dict], *loc_path: str) -> bool:
    """True if some error's `loc` tuple equals `loc_path` exactly."""
    return any(list(e["loc"]) == list(loc_path) for e in errs)


# ----------------------------------------------------------------------------
# The app: one FastAPI instance, all models + routes declared up front.
# ----------------------------------------------------------------------------

app = FastAPI()


class Color(str, Enum):
    """A string-enum: serializes to its value, validates by name OR value."""

    red = "red"
    green = "green"


class Address(BaseModel):
    city: str
    zip_code: str = Field(pattern=r"^\d{5}$")


class User(BaseModel):
    name: str
    address: Address  # nested BaseModel — validated recursively
    tags: list[str] = Field(default_factory=list, max_length=3)


class Item(BaseModel):
    name: str = Field(min_length=2, max_length=8, examples=["widget"])
    price: float = Field(gt=0, le=100)
    sku: str = Field(pattern=r"^[A-Z]{3}\d+$")
    quantity: int = Field(ge=1, lt=1000)
    tag: str | None = None  # Optional: defaults to None, omitted from required


@app.post("/items")
def create_item(item: Item) -> dict:
    """A Pydantic model in the signature = the JSON body, parsed + validated."""
    return {"name": item.name, "price": item.price, "tag": item.tag}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str


@app.post("/strict")
def post_strict(m: Strict) -> Strict:
    return m


@app.post("/loose")
def post_loose(m: Loose) -> Loose:
    return m


class ItemOut(BaseModel):
    name: str
    price: float


@app.get("/filtered", response_model=ItemOut)
def filtered() -> dict:
    """Handler returns a dict with a `secret` field; response_model drops it."""
    return {"name": "widget", "price": 9.99, "secret": "do-not-leak"}


@app.put("/items/{item_id}")
def update_item(item_id: int, item: Item, q: str | None = None) -> dict:
    """Body (Item) + path (item_id) + query (q) — FastAPI disambiguates by type."""
    return {"item_id": item_id, "name": item.name, "q": q}


class Event(BaseModel):
    color: Color
    at: datetime


@app.post("/events")
def post_event(e: Event) -> dict:
    return {"color": e.color, "value": e.color.value, "at_iso": e.at.isoformat()}


client = TestClient(app)


# ----------------------------------------------------------------------------
# Section A — BaseModel as a body: the create echoes
# ----------------------------------------------------------------------------

def section_a_basemodel_body() -> None:
    banner("A — A Pydantic model in the signature IS the JSON body")
    print("Posting JSON to /items; FastAPI parses it into a validated `Item`")
    print("instance and hands that to the handler. The handler echoes 3 fields.\n")
    payload = {"name": "widget", "price": 9.99,
               "sku": "ABC123", "quantity": 5}
    r = client.post("/items", json=payload)
    print(f"POST /items {payload}")
    print(f"  status: {r.status_code}")
    print(f"  body:   {r.json()}")
    print()
    check("status == 200 for valid body", r.status_code == 200)
    check("handler received typed Item (name echoed)", r.json()["name"] == "widget")
    check("price preserved as float", r.json()["price"] == 9.99)
    check("optional `tag` defaults to None", r.json()["tag"] is None)


# ----------------------------------------------------------------------------
# Section B — Validation -> 422 with a precise `loc`
# ----------------------------------------------------------------------------

def section_b_validation_422() -> None:
    banner("B — Missing required field -> 422 with loc=[body,<field>]")
    print("Posting {name:'ok'} with price/sku/quantity MISSING. Pydantic raises")
    print("ValidationError; FastAPI maps it to HTTP 422 with a `detail` list.\n")
    r = client.post("/items", json={"name": "ok"})
    print("POST /items {'name':'ok'}")
    print(f"  status: {r.status_code}")
    errs = _errors(r)
    print(f"  detail ({len(errs)} errors):")
    for e in errs:
        print(f"    type={e['type']:<10} loc={e['loc']}  msg={e['msg']!r}")
    print()
    check("status == 422 for invalid body", r.status_code == 422)
    check("loc points at body.price", _has_loc(errs, "body", "price"))
    check("loc points at body.sku", _has_loc(errs, "body", "sku"))
    check("loc points at body.quantity", _has_loc(errs, "body", "quantity"))
    check("every reported error is type 'missing'",
          all(e["type"] == "missing" for e in errs))


# ----------------------------------------------------------------------------
# Section C — Field constraints as 422 gates
# ----------------------------------------------------------------------------

def section_c_field_constraints() -> None:
    banner("C — Field(gt/lt/ge/le/min_length/max_length/pattern) -> 422 gates")
    print("Each Field(...) constraint becomes a validation gate; violating any")
    print("one yields 422 with a distinct `type` tag. Probing each gate:\n")
    base = {"name": "ok", "price": 1.0, "sku": "ABC123", "quantity": 5}

    probes = [
        ("price <= 0   (gt=0)", {"price": -1}, "greater_than", ["body", "price"]),
        ("price > 100  (le=100)", {"price": 200},
         "less_than_equal", ["body", "price"]),
        ("name 'a'     (min_length=2)", {"name": "a"},
         "string_too_short", ["body", "name"]),
        ("name too long(max_length=8)", {"name": "xxxxxxxxx"},
         "string_too_long", ["body", "name"]),
        ("sku 'abc123' (pattern)", {"sku": "abc123"},
         "string_pattern_mismatch", ["body", "sku"]),
        ("quantity 0   (ge=1)", {"quantity": 0},
         "greater_than_equal", ["body", "quantity"]),
        ("quantity 9999(lt=1000)", {"quantity": 9999},
         "less_than", ["body", "quantity"]),
    ]
    print(f"{'probe':<32}{'status':<9}{'type':<26}{'loc'}")
    print("-" * 78)
    for label, override, etype, eloc in probes:
        body = {**base, **override}
        r = client.post("/items", json=body)
        errs = _errors(r)
        first = errs[0] if errs else {"type": "?", "loc": []}
        print(f"{label:<32}{r.status_code:<9}{first['type']:<26}{first['loc']}")
        check(f"{label} -> 422 with {etype} at {eloc}",
              r.status_code == 422
              and any(e["type"] == etype and list(e["loc"]) == eloc
                      for e in errs))
    print()


# ----------------------------------------------------------------------------
# Section D — Nested models: validation recurses
# ----------------------------------------------------------------------------

def section_d_nested_models() -> None:
    banner("D — Nested BaseModels validate recursively (loc has 3 segments)")
    print("User.address is an Address sub-model; errors inside it produce a")
    print("`loc` with THREE segments: body -> address -> <field>.\n")

    # Self-contained probe app: `User` is not wired onto the global `app`,
    # so this section exercises nesting on its own FastAPI instance.
    nested_app = FastAPI()

    @nested_app.post("/users")
    def mk(u: User) -> dict:
        return {"name": u.name, "city": u.address.city, "tags": len(u.tags)}

    nc = TestClient(nested_app)

    good = {"name": "ann", "address": {"city": "NYC", "zip_code": "10001"},
            "tags": ["a", "b"]}
    r = nc.post("/users", json=good)
    print(f"POST /users {good}")
    print(f"  status: {r.status_code}  body: {r.json()}")

    bad = {"name": "ann", "address": {"city": "NYC", "zip_code": "bad"}}
    r = nc.post("/users", json=bad)
    errs = _errors(r)
    print(f"\nPOST /users {bad}")
    print(f"  status: {r.status_code}")
    for e in errs:
        print(f"    loc={e['loc']}  msg={e['msg']!r}")
    print()
    check("valid nested body -> 200", nc.post("/users", json=good).status_code == 200)
    check("nested ok: name == 'ann'",
          nc.post("/users", json=good).json()["name"] == "ann")
    check("nested ok: city parsed from sub-model",
          nc.post("/users", json=good).json()["city"] == "NYC")
    check("invalid nested -> 422", r.status_code == 422)
    check("loc has 3 segments (body,address,zip_code)",
          _has_loc(errs, "body", "address", "zip_code"))


# ----------------------------------------------------------------------------
# Section E — Optional fields + extra='forbid' vs extra='ignore'
# ----------------------------------------------------------------------------

def section_e_extra_handling() -> None:
    banner("E — Optional `tag: str | None = None` + extra='forbid'/'ignore'")
    print("Default extra policy is 'ignore' (unknown fields silently dropped).")
    print("extra='forbid' REJECTS unknown fields with a 422 (loc=[body,<field>]).\n")

    # Default Optional: omitted -> None
    r = client.post("/items",
                    json={"name": "ok", "price": 1.0,
                          "sku": "ABC123", "quantity": 1})
    print(f"omit optional `tag` -> tag={r.json()['tag']!r}")
    check("optional field omitted -> None", r.json()["tag"] is None)

    # extra='ignore' (default behaviour): unknown field dropped, 200
    r = client.post("/loose", json={"name": "x", "bogus": 1})
    print("\nPOST /loose {'name':'x','bogus':1}  (extra='ignore')")
    print(f"  status: {r.status_code}  body: {r.json()}")
    check("extra='ignore' drops unknown field (200)", r.status_code == 200)
    check("extra='ignore' returned only `name`", r.json() == {"name": "x"})

    # extra='forbid': unknown field rejected with 422
    r = client.post("/strict", json={"name": "x", "bogus": 1})
    errs = _errors(r)
    print("\nPOST /strict {'name':'x','bogus':1}  (extra='forbid')")
    print(f"  status: {r.status_code}")
    for e in errs:
        print(f"    type={e['type']:<18} loc={e['loc']}  msg={e['msg']!r}")
    print()
    check("extra='forbid' rejects unknown field (422)", r.status_code == 422)
    check("extra='forbid' loc points at body.bogus",
          _has_loc(errs, "body", "bogus"))
    check("extra='forbid' error type is 'extra_forbidden'",
          errs[0]["type"] == "extra_forbidden")


# ----------------------------------------------------------------------------
# Section F — response_model filters the output
# ----------------------------------------------------------------------------

def section_f_response_model() -> None:
    banner("F — response_model filters the output (drops undeclared fields)")
    print("Handler returns a dict with a `secret` key; response_model=ItemOut")
    print("(name, price only) strips `secret` from the serialized response.\n")
    r = client.get("/filtered")
    body = r.json()
    print("GET /filtered  (handler returns name+price+secret)")
    print(f"  status: {r.status_code}")
    print(f"  body:   {body}")
    print(f"  keys:   {sorted(body.keys())}")
    print()
    check("response_model route -> 200", r.status_code == 200)
    check("response_model keeps `name`", "name" in body)
    check("response_model keeps `price`", "price" in body)
    check("response_model DROPS `secret`", "secret" not in body)
    check("only declared fields survive", sorted(body.keys()) == ["name", "price"])


# ----------------------------------------------------------------------------
# Section G — Body + path + query in one signature
# ----------------------------------------------------------------------------

def section_g_body_path_query() -> None:
    banner("G — Body + path + query: FastAPI disambiguates by parameter TYPE")
    print("Rule: param matching {item_id} -> path; Pydantic model -> body;")
    print("singular scalar (int/str/...) with a default -> query.\n")
    body = {"name": "ok", "price": 1.0, "sku": "ABC123", "quantity": 1}
    r = client.put("/items/42?q=hello", json=body)
    print(f"PUT /items/42?q=hello  json={body}")
    print(f"  status: {r.status_code}  body: {r.json()}")
    print()
    check("mixed signature -> 200", r.status_code == 200)
    check("item_id parsed from PATH (int 42)", r.json()["item_id"] == 42)
    check("item.name parsed from BODY", r.json()["name"] == "ok")
    check("q parsed from QUERY ('hello')", r.json()["q"] == "hello")

    # Without ?q=... the query param falls back to its default None.
    r = client.put("/items/7", json=body)
    print(f"PUT /items/7  (no ?q=)  -> q={r.json()['q']!r}")
    check("q defaults to None when query absent", r.json()["q"] is None)


# ----------------------------------------------------------------------------
# Section H — Serialization: enums and datetimes round-trip as JSON
# ----------------------------------------------------------------------------

def section_h_serialization() -> None:
    banner("H — Enum & datetime serialize cleanly to JSON (round-trip)")
    print("Pydantic v2's serializer knows how to JSON-encode Enum (its value),")
    print("datetime (ISO 8601), date, UUID, etc. The handler doesn't do it.\n")
    payload = {"color": "red", "at": "2024-01-15T10:30:00"}
    r = client.post("/events", json=payload)
    body = r.json()
    print(f"POST /events {payload}")
    print(f"  status: {r.status_code}")
    print(f"  body:   {body}")
    print()

    # Bad enum value -> 422 with type='enum'
    r = client.post("/events", json={"color": "purple", "at": "2024-01-15T10:30:00"})
    errs = _errors(r)
    print("POST /events {'color':'purple',...}")
    print(f"  status: {r.status_code}")
    for e in errs:
        print(f"    type={e['type']:<8} loc={e['loc']}  msg={e['msg']!r}")
    print()
    check("valid enum + datetime -> 200", body["color"] == "red")
    check("enum serializes to its value", body["value"] == "red")
    check("datetime round-trips as ISO 8601",
          body["at_iso"] == "2024-01-15T10:30:00")
    check("invalid enum value -> 422", r.status_code == 422)
    check("invalid enum loc is body.color",
          _has_loc(errs, "body", "color"))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    import sys

    print("fastapi_bodies_pydantic.py — Phase 7 bundle #44.\n"
          "Every status code and JSON body below is produced in-process by\n"
          "fastapi.testclient.TestClient; NO real HTTP server is started.\n"
          f"Python {sys.version.split()[0]}  "
          f"FastAPI {__import__('fastapi').__version__}  "
          f"Pydantic {__import__('pydantic').__version__}.\n")
    section_a_basemodel_body()
    section_b_validation_422()
    section_c_field_constraints()
    section_d_nested_models()
    section_e_extra_handling()
    section_f_response_model()
    section_g_body_path_query()
    section_h_serialization()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
