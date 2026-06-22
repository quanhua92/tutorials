"""
fastapi_routing_params.py — Bundle #43 (Phase 7).

GOAL (one line): show, by printing every value, how FastAPI maps URL path
{vars} + function parameters to typed, validated path/query params — a bad
type returns a structured HTTP 422, and the OpenAPI schema is generated for
free from the annotations.

This is the GROUND TRUTH for FASTAPI_ROUTING_PARAMS.md. Every status code,
JSON body, and schema snippet in the guide is printed by this file. Change
it -> re-run -> re-paste. Never hand-compute.

No uvicorn, no network. Everything is driven through `TestClient` so the run
is fully deterministic and byte-reproducible.

Run:
    uv run python fastapi_routing_params.py
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Path, Query
from fastapi.testclient import TestClient

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


# ----------------------------------------------------------------------------
# ONE FastAPI app — all routes declared up front
# ----------------------------------------------------------------------------

app = FastAPI()


@app.get("/items/{item_id}")
def read_item(item_id: int) -> dict[str, int]:
    # Section A/B: path param declared `int` -> FastAPI parses + validates it.
    return {"item_id": item_id}


@app.get("/search")
def search(q: str, limit: int = 10) -> dict[str, object]:
    # Section C: `q` (no default, not in path) = required query param;
    # `limit` (default) = optional query param. Both parsed by annotation.
    return {"q": q, "limit": limit}


@app.get("/req")
def required_vs_optional(required_q: str,
                         optional_q: str | None = None) -> dict[str, object]:
    # Section D: no-default -> required; `str | None = None` -> optional.
    return {"required_q": required_q, "optional_q": optional_q}


@app.get("/page")
def page(limit: Annotated[int, Query(ge=0, le=100)] = 10) -> dict[str, int]:
    # Section E: Annotated[int, Query(ge=0, le=100)] adds numeric constraints.
    return {"limit": limit}


@app.get("/note/{note_id}")
def read_note(note_id: Annotated[int, Path(ge=1)]) -> dict[str, int]:
    # Section F: path params can carry the same constraints via Path(...).
    return {"note_id": note_id}


@app.get("/users/{uid}/items/{iid}")
def user_item(uid: int, iid: int, detail: bool = False) -> dict[str, object]:
    # Section G: multiple path params + a query param — detected by name.
    return {"uid": uid, "iid": iid, "detail": detail}


client = TestClient(app)


# ----------------------------------------------------------------------------
# Section A — path params: {item_id} parsed to int
# ----------------------------------------------------------------------------

def section_a_path_params() -> None:
    banner("A — Path parameters: {item_id} parsed to int")
    print("A path operation declares a URL slot with {name}. FastAPI passes")
    print("the matched substring to a function parameter of the SAME name,")
    print("coerces it via the type annotation, and returns the parsed value.\n")

    response = client.get("/items/3")
    print(f"client.get('/items/3').status_code -> {response.status_code}")
    print(f"client.get('/items/3').json()      -> {response.json()}")
    print("Notice the function received 3 as a Python int, not the string")
    print("'3' from the URL.\n")

    check("GET /items/3 returns HTTP 200", response.status_code == 200)
    check("GET /items/3 body is {'item_id': 3}",
          response.json() == {"item_id": 3})
    check("item_id is parsed to int (not str)",
          isinstance(response.json()["item_id"], int))


# ----------------------------------------------------------------------------
# Section B — type validation: bad int -> structured 422
# ----------------------------------------------------------------------------

def section_b_type_validation_422() -> None:
    banner("B — Type validation: '/items/abc' -> HTTP 422 (structured)")
    print("When the path substring cannot be coerced to the declared type,")
    print("FastAPI short-circuits with 422 and a JSON body whose `detail`")
    print("list pinpoints the location and the Pydantic error type.\n")

    response = client.get("/items/abc")
    print(f"client.get('/items/abc').status_code -> {response.status_code}")
    print(f"client.get('/items/abc').json()      -> {response.json()}\n")

    error = response.json()["detail"][0]
    check("GET /items/abc returns HTTP 422", response.status_code == 422)
    check("error loc pinpoints ['path', 'item_id']",
          error["loc"] == ["path", "item_id"])
    check("error type is 'int_parsing' (Pydantic v2)",
          error["type"] == "int_parsing")


# ----------------------------------------------------------------------------
# Section C — query params: any function param NOT in the path
# ----------------------------------------------------------------------------

def section_c_query_params() -> None:
    banner("C — Query parameters: params NOT in the path")
    print("Any function parameter whose name does NOT appear as a {slot} in")
    print("the path is interpreted as a query parameter. Defaults make it")
    print("optional; the annotation still drives parsing + validation.\n")

    response = client.get("/search?q=cats&limit=5")
    print(f"client.get('/search?q=cats&limit=5').status_code -> "
          f"{response.status_code}")
    print(f"client.get('/search?q=cats&limit=5').json()      -> "
          f"{response.json()}\n")

    body = response.json()
    check("GET /search?q=cats&limit=5 returns HTTP 200",
          response.status_code == 200)
    check("q parsed verbatim as 'cats'", body["q"] == "cats")
    check("limit parsed as int 5 (not '5')", body["limit"] == 5)


# ----------------------------------------------------------------------------
# Section D — required vs optional (no default vs default/None)
# ----------------------------------------------------------------------------

def section_d_required_vs_optional() -> None:
    banner("D — Required vs optional: no-default vs default / `T | None`")
    print("For query params: no default -> REQUIRED (missing -> 422). A")
    print("default value (incl. `T | None = None`) -> OPTIONAL and uses the")
    print("default when the client omits it.\n")

    ok = client.get("/req?required_q=hi")
    print(f"client.get('/req?required_q=hi').status_code -> {ok.status_code}")
    print(f"client.get('/req?required_q=hi').json()      -> {ok.json()}")
    missing_required = client.get("/req")
    print(f"\nclient.get('/req').status_code -> "
          f"{missing_required.status_code}")
    print(f"client.get('/req').json()      -> {missing_required.json()}\n")

    check("optional param omitted -> 200, uses default None",
          ok.status_code == 200 and ok.json()["optional_q"] is None)
    check("required param missing -> HTTP 422",
          missing_required.status_code == 422)
    check("missing-required error type is 'missing'",
          missing_required.json()["detail"][0]["type"] == "missing")


# ----------------------------------------------------------------------------
# Section E — Query constraints: Annotated[int, Query(ge=0, le=100)]
# ----------------------------------------------------------------------------

def section_e_query_constraints() -> None:
    banner("E — Query constraints: Annotated[int, Query(ge=0, le=100)]")
    print("Wrapping the annotation in Annotated[T, Query(...)] attaches")
    print("numeric/string constraints. A value outside the range short-")
    print("circuits to 422 with a Pydantic error of the matching type.\n")

    valid = client.get("/page?limit=50")
    too_small = client.get("/page?limit=-1")
    print(f"client.get('/page?limit=50').status_code  -> {valid.status_code} "
          f"body={valid.json()}")
    print(f"client.get('/page?limit=-1').status_code  -> "
          f"{too_small.status_code}")
    print(f"client.get('/page?limit=-1').json()['detail'][0] -> "
          f"{too_small.json()['detail'][0]}\n")

    err = too_small.json()["detail"][0]
    check("limit=50 within [0,100] -> HTTP 200",
          valid.status_code == 200 and valid.json() == {"limit": 50})
    check("limit=-1 violates ge=0 -> HTTP 422", too_small.status_code == 422)
    check("error type is 'greater_than_equal'",
          err["type"] == "greater_than_equal")
    check("error ctx exposes the bound {'ge': 0}", err["ctx"] == {"ge": 0})


# ----------------------------------------------------------------------------
# Section F — Path constraints: Annotated[int, Path(ge=1)]
# ----------------------------------------------------------------------------

def section_f_path_constraints() -> None:
    banner("F — Path constraints: Annotated[int, Path(ge=1)]")
    print("Path(...) accepts the SAME validation/metadata kwargs as Query(...)")
    print("(both subclass fastapi.params.Param). Constraints on a path slot")
    print("behave identically: violation -> 422.\n")

    valid = client.get("/note/5")
    too_small = client.get("/note/0")
    print(f"client.get('/note/5').status_code -> {valid.status_code} "
          f"body={valid.json()}")
    print(f"client.get('/note/0').status_code -> {too_small.status_code} "
          f"type={too_small.json()['detail'][0]['type']}\n")

    check("note/5 satisfies ge=1 -> HTTP 200",
          valid.status_code == 200 and valid.json() == {"note_id": 5})
    check("note/0 violates ge=1 -> HTTP 422", too_small.status_code == 422)
    check("path-constraint error type is 'greater_than_equal'",
          too_small.json()["detail"][0]["type"] == "greater_than_equal")


# ----------------------------------------------------------------------------
# Section G — multiple path params + a query param
# ----------------------------------------------------------------------------

def section_g_multiple_path_and_query() -> None:
    banner("G — Multiple path params + query: /users/{uid}/items/{iid}")
    print("FastAPI detects which params are path vs query by NAME: any name")
    print("matching a {slot} is a path param, everything else is a query")
    print("param. Declaration order in the signature is irrelevant.\n")

    response = client.get("/users/7/items/3?detail=true")
    print(f"client.get('/users/7/items/3?detail=true').status_code -> "
          f"{response.status_code}")
    print(f"client.get('/users/7/items/3?detail=true').json()      -> "
          f"{response.json()}\n")

    body = response.json()
    check("GET nested route returns HTTP 200", response.status_code == 200)
    check("both path ints parsed (uid=7, iid=3)",
          body["uid"] == 7 and body["iid"] == 3)
    check("query 'detail=true' coerced to bool True", body["detail"] is True)


# ----------------------------------------------------------------------------
# Section H — the auto-generated OpenAPI schema
# ----------------------------------------------------------------------------

def section_h_openapi_schema() -> None:
    banner("H — The OpenAPI schema is generated from the annotations")
    print("FastAPI derives the OpenAPI (Swagger) document from the route")
    print("signatures. GET /openapi.json exposes it; each path lists its")
    print("params with `in` (path/query), required flag, type, and any")
    print("numeric bounds coming from Query/Path.\n")

    schema = client.get("/openapi.json").json()
    paths = sorted(schema["paths"].keys())
    print(f"openapi.json status -> {client.get('/openapi.json').status_code}")
    print(f"openapi.json paths  -> {paths}")
    nested_params = schema["paths"]["/users/{uid}/items/{iid}"]["get"][
        "parameters"]
    print(f"/users/{{uid}}/items/{{iid}} parameters -> {nested_params}\n")

    check("/openapi.json returns HTTP 200",
          client.get("/openapi.json").status_code == 200)
    check("every declared route is documented in the schema",
          set(paths) == {"/items/{item_id}", "/search", "/req", "/page",
                         "/note/{note_id}", "/users/{uid}/items/{iid}"})
    check("schema marks uid/iid as path params",
          all(p["in"] == "path" for p in nested_params[:2]))
    check("schema marks detail as a query param",
          nested_params[2]["in"] == "query")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    import fastapi
    import pydantic
    print(f"fastapi_routing_params.py — Phase 7 bundle #43.\n"
          "Every status/body/schema below is produced via TestClient against\n"
          "ONE in-process FastAPI app — no uvicorn, no network. The .md guide\n"
          "pastes it verbatim. Nothing is hand-computed.\n"
          f"fastapi {fastapi.__version__} / pydantic {pydantic.__version__} "
          f"on Python {__import__('sys').version.split()[0]}.")
    section_a_path_params()
    section_b_type_validation_422()
    section_c_query_params()
    section_d_required_vs_optional()
    section_e_query_constraints()
    section_f_path_constraints()
    section_g_multiple_path_and_query()
    section_h_openapi_schema()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
