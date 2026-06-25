# JSON: Reading and Writing Request/Response Bodies

**Doc Source**: [guides/json](https://crowcpp.org/master/guides/json/) · [examples/example.cpp](https://github.com/CrowCpp/Crow/blob/master/examples/example.cpp) · [examples/example_json_map.cpp](https://github.com/CrowCpp/Crow/blob/master/examples/example_json_map.cpp)

## The Core Concept: Why This Example Exists

**The Problem:** Modern web APIs speak JSON. A framework that makes you reach for a third-party parser (nlohmann/json, RapidJSON) for every endpoint is ergonomically dead on arrival. You need two operations, and they must be cheap: **read** an incoming body into a value you can index, and **write** a response value out to a JSON string — ideally with the `Content-Type` header set for you.

**The Solution:** Crow ships its own JSON engine with a clean read/write split mirroring the C++ const-correctness tradition:
1. **`crow::json::rvalue`** ("read value") — the immutable result of parsing. You index it, you read it, you cannot mutate it.
2. **`crow::json::wvalue`** ("write value") — the mutable builder. You assign keys, you serialize, and crucially **returning one from a handler auto-sets `Content-Type: application/json`**.

No template generics, no third-party dep, no schema codegen — just two types and a parse function.

## Practical Walkthrough: Code Breakdown

### The Type System

The docs enumerate the value types `rvalue`/`wvalue` can hold:

| JSON type | C++ source | Reader accessor |
|---|---|---|
| `False` / `True` | `bool` | `.b()` |
| `Number` (float) | `double` | `.d()` |
| `Number` (signed) | `int` / `std::int64_t` | `.i()` |
| `Number` (unsigned) | `unsigned` / `std::uint64_t` | `.u()` |
| `String` | `std::string` | `.s()` |
| `List` | `std::vector` | index `[n]` |
| `Object` | nested `wvalue`/`rvalue` | key `["k"]` |
| `Null` | `nullptr` | `has("k")` |

### Reading: `crow::json::load`

> "JSON read value, used for taking a JSON string and parsing it into `crow::json`."

`load` returns an `rvalue` whose truthiness tells you whether parsing succeeded. The canonical pattern, straight from `example.cpp`:

```cpp
CROW_ROUTE(app, "/add_json")
  .methods("POST"_method)([](const crow::request& req) {
      auto x = crow::json::load(req.body);
      if (!x)
          return crow::response(400);
      int64_t sum = x["a"].i() + x["b"].i();
      std::ostringstream os;
      os << sum;
      return crow::response{os.str()};
  });
```
*(source: [`examples/example.cpp`](https://github.com/CrowCpp/Crow/blob/master/examples/example.cpp))*

`curl -d '{"a":1,"b":2}' localhost:18080/add_json` returns `3`. Note the three-step recipe:
1. `crow::json::load(req.body)` → `rvalue x`
2. **Check truthiness** `if (!x) return crow::response(400);` — a malformed body sets the `rvalue` to a falsy error state.
3. Index + typed accessor: `x["a"].i()` returns the value as `int64_t`. Pick the accessor matching the JSON type (`.i()`, `.d()`, `.b()`, `.s()`).

To go deeper than one level, chain indexing: `x["user"]["address"]["city"].s()`.

### Writing: `crow::json::wvalue`

> "JSON write value, used for creating, editing and converting JSON to a string. … a `wvalue` can be returned directly inside a route handler, this will cause the `content-type` header to automatically be set to `Application/json`."

The simplest builder, from `example.cpp`:

```cpp
CROW_ROUTE(app, "/json")
([] {
    crow::json::wvalue x({{"message", "Hello, World!"}});
    x["message2"] = "Hello, World.. Again!";
    return x;
});
```
*(source: [`examples/example.cpp`](https://github.com/CrowCpp/Crow/blob/master/examples/example.cpp))*

You can construct from an **initializer list** *or* assign keys afterward — both mutate the same underlying `std::unordered_map`. The docs stress that assigning any key turns the `wvalue` into an Object:

> "setting a `wvalue` to object type can be done by simply assigning a value to whatever string key you like, something like `wval["key1"] = val1;`. Keep in mind that val1 can be any of the above types."

#### Initializer-list construction with all types

The most thorough example in the repo demonstrates how literal types map onto JSON types:

```cpp
CROW_ROUTE(app, "/json-initializer-list-constructor")
([] {
    return crow::json::wvalue({
      {"first", "Hello world!"},                     /* stores a char const* hence a json::type::String */
      {"second", std::string("How are you today?")}, /* stores a std::string hence a json::type::String. */
      {"third", std::int64_t(54)},                   /* stores a 64-bit int hence a std::int64_t. */
      {"fourth", std::uint64_t(54)},                 /* stores a 64-bit unsigned int hence a std::uint64_t. */
      {"fifth", 54},                                 /* stores an int (as 54 is an int literal) hence a std::int64_t. */
      {"sixth", 54u},                                /* stores an unsigned int (as 54u is a unsigned int literal) hence a std::uint64_t. */
      {"seventh", 2.f},                              /* stores a float (as 2.f is a float literal) hence a double. */
      {"eighth", 2.},                                /* stores a double (as 2. is a double literal) hence a double. */
      {"ninth", nullptr},                            /* stores a std::nullptr hence json::type::Null . */
      {"tenth", true}                                /* stores a bool hence json::type::True . */
    });
});
```
*(source: [`examples/example.cpp`](https://github.com/CrowCpp/Crow/blob/master/examples/example.cpp))*

This is the reference card for "what C++ literal produces what JSON type." The comments come straight from the Crow authors — pay attention to `54` (signed) vs `54u` (unsigned) vs `2.f` (float) vs `2.` (double).

#### Lists

A `wvalue` can also be a JSON array, via the `list(...)` factory:

```cpp
CROW_ROUTE(app, "/json_list")
([] {
    crow::json::wvalue x(crow::json::wvalue::list({1, 2, 3}));
    return x;
});
```
*(source: [`examples/example.cpp`](https://github.com/CrowCpp/Crow/blob/master/examples/example.cpp))*

You can index-assign into a list (`json[3] = 32`), but the docs warn: "this will remove the data in the value if it isn't of List type" — i.e., index assignment silently retypes an Object to a List.

### rvalue → wvalue

To *modify* parsed input, convert: `crow::json::wvalue wval (rval);`. The constructor deep-copies; from then on you can mutate freely.

### Configuration Macros

- **`#define CROW_JSON_USE_MAP`** — swap the backing container from `std::unordered_map` to `std::map`, giving you **sorted keys** in the serialized output (useful for deterministic tests / caching).
- **`#define CROW_JSON_NO_ERROR_CHECK`** — disable exception throwing on parse/access errors for speed. "This should increase the program speed with the drawback of having unexpected behaviour when used incorrectly."

> **Warning (NaN/Inf):** "JSON does not allow floating point values like `NaN` or `INF`, Crow will output `null` instead of `NaN` or `INF` when converting `wvalue` to a string." Don't rely on float sentinel values round-tripping.

## Mental Model: Thinking in Crow JSON

**The `rvalue`/`wvalue` Split as C++ `const` Propagation:** Think of `rvalue` as `const json` and `wvalue` as `json`. The parser hands you a `const` view (you can't accidentally mutate the wire data), and only the explicitly-constructed `wvalue` is mutable. This mirrors how `std::string_view` (read) relates to `std::string` (write): same data, different capabilities, deliberate friction at the conversion point so you think before copying.

```mermaid
graph LR
    W["wire body<br/>{&quot;a&quot;:1,&quot;b&quot;:2}"] -->|crow::json::load| RV["rvalue (immutable)<br/>x[&quot;a&quot;].i()"]
    RV -->|wvalue w(rval);<br/>deep copy| WV["wvalue (mutable)<br/>w[&quot;c&quot;]=3"]
    WV -->|return from handler| OUT["200 OK<br/>Content-Type: application/json<br/>{...}"]
    IL["initializer list<br/>{ {k,v}, ... }"] --> WV
    L["wvalue::list({...})"] --> WV
```

**Why It's Designed This Way:** A bespoke JSON engine (rather than wrapping nlohmann/json) buys Crow two things: (1) **zero external dependency** — `crow.h` stays genuinely standalone; and (2) a **type-stable ABI** between parse and serialize, so returning a `wvalue` from a handler can be inlined into the response writer without a conversion hop. The trade-off is a smaller feature set (no JSON Pointer, no JSON Patch, no schema validation) — but for the 95% case of "read two ints, return an object," it's the right call.

**Pitfalls:**
- **Always check `if (!x)`** after `load`. A parse failure leaves the `rvalue` in an error state; indexing it throws (unless `CROW_JSON_NO_ERROR_CHECK`).
- **Accessor/type mismatch** — calling `.i()` on a String value is undefined behavior territory; use `crow::utility::lexical_cast` if you need coercion, or check `.t()` for the runtime type.
- **Float sentinels die** — `NaN`/`INF` become `null` on output. Validate before assigning.
- **Return type matters** — returning `crow::json::wvalue` sets `application/json`; returning `std::string` from the *same* data leaves `text/plain`. If you build JSON as a string manually, set the header yourself.

**Further Exploration:**
- Build a `/users/<int>` endpoint that returns a nested `wvalue` object with a list of orders.
- Use `#define CROW_JSON_USE_MAP` and diff the response key order before/after to see deterministic sorting.
- Write a round-trip test: `load` a body, convert to `wvalue`, mutate, return, and assert the diff (see [06-testing.md](./06-testing.md) for the `app.handle(req, res)` pattern).

## 🔗 Cross-References

**Curriculum (this C++ tree):**
- [`../MOVE_SEMANTICS.md`](../MOVE_SEMANTICS.md) — `wvalue` is move-constructible; returning one from a handler is a cheap move, not a deep copy.
- [`../CONTAINERS_SEQUENCE.md`](../CONTAINERS_SEQUENCE.md) / [`../CONTAINERS_ASSOCIATIVE.md`](../CONTAINERS_ASSOCIATIVE.md) — the JSON list/object types map onto `std::vector` / `std::unordered_map`.

**Cross-language siblings:**
- [`../../rust/axum/03-extractors-and-responses.md`](../../rust/axum/03-extractors-and-responses.md) — axum's `Json<T>` extractor/response is the typed equivalent of `load`/`wvalue`, but backed by `serde` derive.
- [`../../ts/hono/03-context-helpers.md`](../../ts/hono/03-context-helpers.md) — Hono's `c.json({...})` and `c.req.json()` mirror the Crow pattern, natively typed via TS.
- [`../../python/FASTAPI_BODIES_PYDANTIC.md`](../../python/FASTAPI_BODIES_PYDANTIC.md) — FastAPI/Pydantic is the most ergonomic sibling; compare Crow's manual `.i()`/`.s()` accessors to Pydantic's auto-validated model.

**Next:** [04-middleware.md](./04-middleware.md) — the request/response interceptor chain.
