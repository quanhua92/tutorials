# SERDE_BASICS — `#[derive(Serialize, Deserialize)]` and the JSON Round-Trip

> **One-line goal:** annotate a struct with `#[derive(Serialize, Deserialize)]`
> and serde_json can turn it into a JSON string (`to_string`) and back into the
> same value (`from_str`); field attributes (`rename`/`default`/`skip`/
> `skip_serializing_if`) and `Option<T>` shape that JSON in precise, assertable
> ways.
>
> **Run:** `just run serde_basics` (== `cargo run --bin serde_basics`)
> **Member:** `serde` (deps: `serde` with the `derive` feature + `serde_json`).
> **Prerequisites:** [STRUCTS_ENUMS](../core/STRUCTS_ENUMS.md) (derive macros),
> [ERROR_HANDLING](../core/ERROR_HANDLING.md) (`Result`/`?`/`Error`).
> **Ground truth:** [`serde_basics.rs`](./serde_basics.rs); captured stdout:
> [`serde_basics_output.txt`](./serde_basics_output.txt).

---

## Why this exists (lineage)

Every non-trivial program crosses a format boundary: an HTTP body, a config
file, a database row, a message on a queue. The data is *text* on one side and
*typed values* on the other. Three strategies exist, and serde picks the third:

| Model | Example | Cost / problem |
|---|---|---|
| **Hand-rolled parsers** | switch on field names, `parse::<u32>()` each value | Tedious, error-prone, no schema; typos become runtime bugs. |
| **Reflection-driven mappers** (Java Jackson, Go `encoding/json`) | walk fields at *runtime* via reflection | Runtime reflection cost; panics on type mismatch you only learn about in production. |
| **Derive-driven codegen** (Rust `serde`) | a proc-macro emits the `Serialize`/`Deserialize` impl at *compile time* | Zero-cost: no reflection at runtime; the compiler checks every field; you learn about a missing/wrong field as a compile or `Result`-carried error, never a silent crash. |

serde is a **serialization framework**: `serde::Serialize`/`Deserialize` are
*traits*, and a generic API (`to_string<T: Serialize>`, `from_str<T:
Deserialize<'de>>`) lets **any** backend format — JSON, Bincode, TOML, Postcard,
MessagePack — target the **same** Rust type. `serde_json` is merely the JSON
backend. This bundle is the Rust analog of Go's `encoding/json` and Python's
`json` modules — **this IS the JSON bundle** for this folder.

```mermaid
graph TD
    Code["#[derive(Serialize, Deserialize)]<br/>on a Rust struct"] -->|proc-macro at COMPILE TIME| Impl["impl Serialize + impl Deserialize<br/>(generated, zero reflection)"]
    Impl -->|"serde_json::to_string(&v)"| JSONout["JSON text string<br/>{\"name\":\"Al\",\"age\":9}"]
    JSONout -->|"serde_json::from_str::&lt;T&gt;(s)"| Back["same struct value<br/>(round-trip == v)"]
    Attrs["field attributes shape the JSON"] --> Rename["rename: 'name' -> 'full_name'"]
    Attrs --> Skip["skip: field ABSENT in JSON<br/>(Default on the way back)"]
    Attrs --> Def["default: missing field -> Default"]
    Attrs --> SkipIf["skip_serializing_if: None omitted"]
    Opt["Option&lt;T&gt;"] --> Null["None -> JSON null (default)"]
    Opt --> Absent["None -> key omitted (with skip_serializing_if)"]
    Opt --> NoneIn["JSON null / absent -> None (deserialize)"]
    style Code fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style Impl fill:#fef9e7,stroke:#f1c40f,stroke-width:2px
    style JSONout fill:#eaf2f8,stroke:#2980b9,stroke-width:2px
```

---

## Section A — `#[derive(Serialize, Deserialize)]` + the round-trip

```rust
#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct User {
    name: String,   // NOTE: fields are PRIVATE — serde still works (see below)
    age: u32,
}

let u = User { name: "Al".to_string(), age: 9 };
let j = serde_json::to_string(&u)?;          // -> {"name":"Al","age":9}
let back: User = serde_json::from_str(&j)?;  // -> the same value
assert_eq!(back, u);                          // round-trip holds
```

> **From serde_basics.rs Section A:**
> ```
> ======================================================================
> SECTION A — #[derive(Serialize, Deserialize)] + round-trip
> ======================================================================
>   let u = User { name: "Al", age: 9 };  (fields are PRIVATE; serde works anyway)
>   serde_json::to_string(&u) = {"name":"Al","age":9}
> [check] compact JSON is exactly {"name":"Al","age":9} (declaration order): OK
>   serde_json::from_str::<User>(&j) = User { name: "Al", age: 9 }
> [check] round-trip: from_str(to_string(u)) == u: OK
> ```

**What.** Two derive macros do all the work. `to_string(&u)` produces the exact
compact string `{"name":"Al","age":9}` — **byte-identical every run**, because
serde serializes fields in **declaration order** (`name` then `age`). The second
check proves the round-trip: `from_str(to_string(u)) == u`.

**Why (internals).**
- **A derive is a compile-time proc-macro, not reflection.** `#[derive(Serialize,
  Deserialize)]` causes `serde_derive` to *generate* an `impl Serialize for User`
  and `impl Deserialize<'de> for User` at compile time — code that calls
  `serializer.serialize_field(...)` once per field, in source order. There is no
  runtime reflection, no field-name table, no `Any`. This is why serde is "zero-
  cost" relative to hand-written serialization ([serde.rs/derive][serde-derive]).
- **Field declaration order is the JSON key order — and it is deterministic.**
  The generated code emits `serialize_field` calls in the order fields appear in
  the `struct`, so `to_string` always yields `{"name":...,"age":...}`, never the
  reverse. This is what makes the `_output.txt` byte-reproducible (see the
  DETERMINISM rule, `HOW_TO_RESEARCH.md` §4.2) and why the first `check` can
  compare against a pinned literal string.
- **Private fields ARE serializable.** The derive emits its `impl` **in the same
  module** as the struct, so it can read and write fields that are not `pub`. You
  do **not** need `pub` fields to (de)serialize — a frequent surprise coming from
  Go/Java reflection mappers that require exported/public fields. (For a remote
  type whose fields you can't reach, serde offers `#[serde(getter = "...")]` /
  remote derivation — that's SERDE_ADVANCED.)
- **`to_string` returns `Result<String, serde_json::Error>`.** Serialization can
  fail (e.g. a custom `Serialize` impl, or writing to a fallible sink), so the
  signature is `fn to_string<T: Serialize>(value: &T) -> Result<String, Error>`
  ([serde_json docs][serde-json]). The `.rs` uses `.expect(...)` because for these
  plain structs success is guaranteed. 🔗 [ERROR_HANDLING](../core/ERROR_HANDLING.md)
  for the `Result`/`?` model.

---

## Section B — Field attributes: `rename` / `default` / `skip`

```rust
#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct Profile {
    #[serde(rename = "full_name")]   // JSON key != Rust field name
    name: String,
    #[serde(default)]                // missing on input -> Default::default()
    age: u32,
    #[serde(skip)]                   // never serialized; Default on the way back
    token: String,
}
```

> **From serde_basics.rs Section B:**
> ```
> ======================================================================
> SECTION B — field attributes: rename / default / skip
> ======================================================================
>   Profile { name: "Bo", age: 4, token: "secret" }
>   to_string(&p) = {"full_name":"Bo","age":4}
> [check] rename: Rust field "name" -> JSON key "full_name": OK
> [check] skip: "token" field is ABSENT from the JSON: OK
>   from_str(r#"{"full_name":"Cy"}"#) = Profile { name: "Cy", age: 0, token: "" }
> [check] default: missing age field -> u32::default() = 0: OK
> [check] skip: deserialized token -> String::default() = "": OK
> ```

**What.** Four checks pin each behavior:
1. **`rename`** — the Rust field `name` becomes the JSON key `full_name` (and the
   original key `"name"` is **gone** from the output).
2. **`skip`** — the `token` field is **entirely absent** from the JSON.
3. **`default`** — deserializing `{"full_name":"Cy"}` (no `age`) fills `age` with
   `u32::default()` = `0`.
4. **`skip` on the way back** — deserializing any JSON fills `token` with
   `String::default()` = `""` (it is never read from input).

**Why (internals).** Each attribute changes one thing about the generated impl
([serde.rs field-attrs][serde-field-attrs]):

| Attribute | Serialize path | Deserialize path | Needs the field's type to |
|---|---|---|---|
| `rename = "X"` | emits key `"X"` | reads key `"X"` | — (rename is purely nominal) |
| `default` | (unchanged) | if key **absent** → `Default::default()` | implement `Default` |
| `skip` | field **omitted** | field never read → `Default::default()` | implement `Default` |
| `skip_serializing_if = "f"` | field omitted when `f(&field)` is true | (unchanged) | — |

- **`rename` is symmetric by default** — it renames for *both* directions at once.
  `#[serde(rename(serialize = "..", deserialize = ".."))]` lets you split them
  (e.g. a field that has a different wire name on read vs write). `#[serde(alias =
  "..")]` adds *extra* accepted names on deserialize only, without changing the
  serialized name.
- **`skip` ⇒ `Default`.** A skipped field is unknown to the wire format, so on
  deserialization serde must conjure a value — it uses `Default::default()`. This
  is why `#[serde(skip)]` *requires* the field type to implement `Default`. The
  same is true for any *absent* field that has `#[serde(default)]`. 🔗
  [COPY_CLONE](../core/COPY_CLONE.md) / the `Default` trait.
- **`skip` is not the same as `Option`!** `skip` makes a field **vanish from
  output unconditionally** (always omitted on serialize, always defaulted on
  deserialize). `Option<T>` makes it *conditionally* present (see Section C). A
  common mistake is reaching for `#[serde(skip)]` when you meant
  `skip_serializing_if = "Option::is_none"`.

---

## Section C — `Option<T>`: `null` vs absent

```rust
#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct Item {
    id: u32,
    note: Option<String>,                                  // None -> null
    #[serde(skip_serializing_if = "Option::is_none")]
    tag: Option<String>,                                   // None -> key omitted
}
```

> **From serde_basics.rs Section C:**
> ```
> ======================================================================
> SECTION C — Option<T>: null (default) vs absent (skip_serializing_if)
> ======================================================================
>   Item { id: 1, note: None, tag: None }
>   to_string = {"id":1,"note":null}
> [check] Option None -> JSON null by default (note = null): OK
> [check] skip_serializing_if omits tag entirely when None: OK
>   Item { id: 2, note: Some("hi"), tag: Some("vip") }
>   to_string = {"id":2,"note":"hi","tag":"vip"}
> [check] Option Some("hi") -> JSON "hi": OK
> [check] Some tag IS present in JSON: OK
>   from_str(r#"{"id":3,"note":null}"#) = Item { id: 3, note: None, tag: None }
> [check] JSON null deserializes to Option::None: OK
> [check] absent Option field deserializes to None (serde Option default): OK
> ```

**What.** Two `Option<String>` fields, two different on-the-wire shapes:
- `note` (no attribute): `None` → JSON `null`; `Some("hi")` → JSON `"hi"`.
- `tag` (`skip_serializing_if = "Option::is_none"`): `None` → the whole `"tag"`
  key is **omitted**; `Some("vip")` → present as `"vip"`.

And on the way back: JSON `null` → `None`, and an **absent** `Option` field →
`None` too (the last check deserializes `{"id":4}` into an `Item` with both
`note` and `tag` equal to `None`).

**Why (internals).**
- **`Option<T>` is serde's built-in notion of "this might not be there."** The
  `Serialize` impl for `Option` emits `null` for `None` and the inner value for
  `Some`. That is why `"note":null` appears in the output by default
  ([serde_json docs][serde-json]).
- **`skip_serializing_if = "Option::is_none"` is the idiomatic "emit only when
  present."** `skip_serializing_if` takes a `fn(&T) -> bool`; `Option::is_none`
  exactly matches that signature, so it is the canonical one-liner to *omit*
  rather than *null* a field. This is the standard fix for "my JSON is full of
  noisy `null`s" ([serde.rs field-attrs][serde-field-attrs]).
- **A *missing* `Option` field deserializes to `None` — no attribute needed.**
  This is a serde special case: unlike non-`Option` fields (which **error** if
  absent and have no `default`), an `Option` field absent from the input is
  silently treated as `None` in serde_json ([serde-rs/serde #2214][serde-2214];
  corroborated by the `optional-field` ecosystem). That is the load-bearing fact
  behind the final two checks. Consequence: **`Option<T>` and
  `#[serde(default)]` overlap** — for an `Option`, both make a missing field
  become `None`. They differ for non-`Option` fields, where only `default` works.
- **`null` ≠ absent on the Rust side, but they *collide* into `None`.** serde's
  `Option` cannot, by itself, distinguish "the key was `null`" from "the key was
  missing" — both become `None`. If you genuinely need three states (missing /
  null / present), use a wrapper enum like `#[serde(untagged)] enum
  TriField { Missing, Null, Some(T) }` or a dedicated crate — SERDE_ADVANCED.

---

## Section D — `to_string` (compact) vs `to_string_pretty`

> **From serde_basics.rs Section D:**
> ```
> ======================================================================
> SECTION D — to_string (compact) vs to_string_pretty
> ======================================================================
>   compact   = {"name":"Al","age":9}
>   pretty    =
> {
>   "name": "Al",
>   "age": 9
> }
> [check] compact JSON has NO newlines: OK
> [check] pretty JSON is multi-line (has newlines): OK
> [check] compact and pretty decode to the SAME User: OK
> ```

**What.** Same `User`, two serializations: compact (single line, no whitespace)
and pretty (2-space indentation, one key per line). Both decode to the identical
struct — the formatting is purely cosmetic, not semantic.

**Why (internals).**
- **Whitespace is the only difference.** `to_string` and `to_string_pretty` emit
  the **same** tokens (keys, values, punctuation) in the **same** order; the
  pretty variant just inserts `\n` and 2-space indents. A JSON parser treats
  whitespace between tokens as insignificant, so the third check holds: both
  deserialize to the same `User` ([serde_json docs][serde-json]).
- **Choose by audience.** `to_string` is for the wire (smaller payload, faster
  to transmit/parse — it is what you want in HTTP bodies and logs that machines
  consume). `to_string_pretty` is for humans (config files, debugging, error
  messages). The cost of pretty is only the extra whitespace bytes; the parser
  cost is negligible either way.

---

## Section E — `from_str`: malformed JSON / type mismatch → `Err`

> **From serde_basics.rs Section E:**
> ```
> ======================================================================
> SECTION E — from_str: malformed JSON / type mismatch -> Err
> ======================================================================
>   from_str("{not valid json") -> Err: "key must be a string at line 1 column 2"
> [check] malformed JSON -> Err(serde_json::Error): OK
>   from_str(age = "not a number") -> Err: "invalid type: string "not a number", expected u32 at line 1 column 33"
> [check] type mismatch (age expects u32, got string) -> Err: OK
> ```

**What.** Two distinct failure modes, both surfaced as `Result::Err` carrying a
`serde_json::Error`:
1. **Syntactically invalid JSON** — `{"not valid json"}` → `"key must be a string
   at line 1 column 2"`.
2. **Type mismatch** — structurally valid JSON, wrong value type:
   `{"name":"Al","age":"not a number"}` → `"invalid type: string \"not a
   number\", expected u32 at line 1 column 33"`.

**Why (internals).**
- **`from_str` is `fn from_str<T: Deserialize<'de>>(s: &str) -> Result<T,
  serde_json::Error>`.** It is the same function for untyped `Value` and strongly-
  typed `T`; the only difference is the type you ask for ([serde_json docs][serde-json]).
  Deserialization is where *all* the runtime errors live — serialization of a
  well-typed Rust value almost never fails, but arbitrary input text can be
  broken in countless ways.
- **The error is precise and positioned.** serde_json reports a human-readable
  category (`key must be a string`, `invalid type: … expected u32`,
  `EOF while parsing`, `trailing characters`, `missing field`, etc.) **and** a
  `line/column` pinpointing the offending byte. The column numbers are
  **deterministic** for a fixed input string (they are computed by the parser's
  position counter), which is why the `_output.txt` reproduces byte-for-byte —
  no addresses, no RNG.
- **`serde_json::Error` is a real `std::error::Error`.** It implements
  `std::error::Error` + `Display` + `source()`, so it composes with `?` and the
  `anyhow`/`thiserror` ecosystem. The `.rs` aliases `serde_json::Result` as
  `JsonResult` and returns it from the typed checks, exactly as the crate's own
  examples do. 🔗 [ERROR_HANDLING](../core/ERROR_HANDLING.md) for the `Result`/`?`/`Error` trinity, and for why
  `to_string`/`from_str` *return* `Result` rather than panicking.

---

## Section F — Nested struct + `Vec` round-trip

```rust
#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct Address { city: String, zip: u32 }

#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct Order {
    id: u32,
    ship_to: Address,        // nested struct -> nested JSON object
    items: Vec<String>,      // Vec           -> JSON array
}
```

> **From serde_basics.rs Section F:**
> ```
> ======================================================================
> SECTION F — nested struct + Vec round-trip
> ======================================================================
>   Order { id: 7, ship_to: Address{ city: "Rome", zip: 100 }, items: vec!["a","b"] }
>   to_string(&o) = {"id":7,"ship_to":{"city":"Rome","zip":100},"items":["a","b"]}
> [check] nested struct serialized as a nested JSON object: OK
> [check] Vec serialized as a JSON array: OK
>   from_str::<Order>(&j) = Order { id: 7, ship_to: Address { city: "Rome", zip: 100 }, items: ["a", "b"] }
> [check] nested + Vec round-trip: from_str(to_string(o)) == o: OK
> ```

**What.** A struct that *contains* a struct (`ship_to: Address`) and a `Vec`
(`items: Vec<String>`) serializes to nested JSON:
`{"id":7,"ship_to":{"city":"Rome","zip":100},"items":["a","b"]}`, and the whole
thing round-trips back to an equal `Order`.

**Why (internals).**
- **Composition is automatic and recursive.** serde's derive requires **every**
  field's type to itself implement `Serialize`/`Deserialize` (or be skipped). The
  generated `Order` impl calls `Address`'s impl for `ship_to` and `Vec<String>`'s
  impl for `items` — serde already ships impls for all stdlib containers
  (`Vec`, `HashMap`, `BTreeMap`, `Option`, tuples, arrays, primitives, `String`),
  so nesting "just works" with no extra attributes.
- **Rust type → JSON shape is fixed by the type.** A nested `struct` → a nested
  JSON **object**; a `Vec<T>`/array → a JSON **array**; a `HashMap`/`BTreeMap` →
  a JSON **object** keyed by the map's key (which must serialize to a string);
  `Option<T>` → value-or-null/absent; a tuple `(A,B,C)` → a JSON **array**.
- **Determinism warning for maps.** `serde_json` serializes a `Vec` in index
  order (deterministic), but a **`HashMap`** in its (random-seeded) iteration
  order — **non-reproducible run-to-run** (SipHash DoS-resistance). If a future
  bundle embeds a map in serialized output, use a **`BTreeMap`** (sorted keys)
  or sort the `Vec` of entries before serializing — see the DETERMINISM hard
  rule in `HOW_TO_RESEARCH.md` §4.2. 🔗 [ITERATORS](../core/ITERATORS.md) for
  the collect/sort step, and [COLLECTIONS](../core/COLLECTIONS.md) for
  `HashMap` vs `BTreeMap`.

---

## Pitfalls (the expert payoff)

| Trap | Symptom | Fix / why |
|---|---|---|
| **Forgetting `#[derive(Deserialize)]` (or `Serialize`)** | `the trait \`Deserialize\` is not implemented` / `Serialize` not implemented | The trait impls only exist if you derive them. Add `#[derive(Serialize, Deserialize)]`. A field whose type isn't serializable blocks the whole struct. |
| **Missing field on deserialize (non-`Option`, no `default`)** | `Err: missing field \`age\`` at runtime | Non-`Option` fields are **required**. Either make it `Option<T>`, add `#[serde(default)]`, or change the wire format. |
| **`null` in input for a non-`Option` field** | `Err: invalid type: null, expected u32` | `null` only maps to `Option`. For a required field that may be `null`, use `Option<T>` (or `#[serde(deserialize_with = …)]`). |
| **Expecting `#[serde(skip)]` to mean "optional"** | Field always vanishes, always defaults — even when you wanted it sometimes | `skip` is *unconditional*. For "present when Some, absent when None" use `skip_serializing_if = "Option::is_none"` on an `Option`. |
| **`HashMap<K,V>` makes output non-reproducible** | `_output.txt` differs every run | `HashMap` iterates in random order (SipHash seed). Use `BTreeMap` for sorted, deterministic JSON key order (see DETERMINISM, §4.2). |
| **Two owners of the JSON key order** | Tests flake depending on which field list you read | serde emits keys in **declaration order**, always. Don't reorder struct fields expecting wire stability to change elsewhere; pin the literal in a `check`. |
| **`to_string` on a type with a custom `Serialize` can fail** | "Why does `to_string` return `Result`?" | The signature is `Result<String, Error>` for all `T`. For plain structs it won't fail, but never assume it — propagate with `?` or `.expect("…")` deliberately. |
| **`rename` is symmetric by default** | You renamed for serialize and it broke deserialize (or vice versa) | `rename = "X"` affects *both* directions. To split, use `rename(serialize = "a", deserialize = "b")`; to add *extra* read names, use `alias`. |
| **Cannot distinguish `null` from "missing"** | Both become `None`; you lose information | serde `Option` collapses them. Need 3 states? Use a wrapper enum (`Missing`/`Null`/`Some`) or a dedicated crate (SERDE_ADVANCED). |
| **Extra/unknown fields silently ignored** | A typo'd JSON key is dropped, not flagged | By default serde **ignores** unknown fields. Add `#[serde(deny_unknown_fields)]` on the struct to make extras an error (SERDE_ADVANCED). |
| **Private fields? No problem** — but **remote** types are | "I can't derive on a type from another crate" | Derive only works on types *you* own (it needs field access). For foreign types, use serde's *remote* derivation (`#[serde(remote = "..")]`) or `serialize_with`/`deserialize_with`. |
| **`Debug`/`PartialEq` are NOT required for serde** | "Do I need `#[derive(Debug)]` to serialize?" | No — serde needs only `Serialize`/`Deserialize`. `Debug`+`PartialEq` are added here *only* so the `.rs` can print and `check` round-trip equality. |

---

## Cheat sheet

```rust
use serde::{Deserialize, Serialize};
// to_string / from_str return Result<_, serde_json::Error>; alias it:
use serde_json::Result as JsonResult;

#[derive(Serialize, Deserialize, Debug, PartialEq)]   // private fields OK
struct User { name: String, age: u32 }

// --- the round-trip ---
let j: String         = serde_json::to_string(&u)?;            // compact
let p: String         = serde_json::to_string_pretty(&u)?;     // 2-space indented
let back: User        = serde_json::from_str(&j)?;             // == u
// keys are in DECLARATION ORDER; deterministic; byte-reproducible.

// --- field attributes (shape the JSON) ---
#[derive(Serialize, Deserialize)]
struct Profile {
    #[serde(rename = "full_name")]                name: String,   // key rename
    #[serde(default)]                             age: u32,       // missing -> 0
    #[serde(skip)]                                token: String,  // ABSENT; "" back
    #[serde(skip_serializing_if = "Option::is_none")] opt: Option<u32>, // omit None
}

// --- Option<T> ---
//   None            -> null (default) ; with skip_serializing_if -> key omitted
//   Some(x)         -> x
//   JSON null       -> None  ;  ABSENT option field -> None (no attribute needed)

// --- nesting / containers ---
//   nested struct  -> nested object ; Vec<T>/array -> array ;
//   HashMap        -> object (RANDOM key order! use BTreeMap for determinism)

// --- errors ---
//   from_str is where runtime errors live. serde_json::Error is a std::error::Error
//   with Display + line/column. Categories: "key must be a string",
//   "invalid type: ... expected u32", "missing field `x`", "EOF while parsing", ...
//   Unknown fields are IGNORED by default -> #[serde(deny_unknown_fields)] to flag.
```

---

## Sources

Every claim above was web-verified in at least two authoritative places, and the
exact values are reproduced verbatim from `serde_basics_output.txt`.

- **serde.rs — Field attributes** (`rename`, `default`, `default = "path"`, `skip`,
  `skip_serializing`, `skip_deserializing`, `skip_serializing_if`, `alias`,
  `serialize_with`/`deserialize_with`, `getter`):
  https://serde.rs/field-attrs.html
- **serde.rs — Attributes overview** (derive requires a Rust compiler ≥1.15; the
  attributes customize the generated `Serialize`/`Deserialize` impls):
  https://serde.rs/attributes.html
- **docs.rs — `serde_json` crate docs** (`to_string`, `to_string_pretty`,
  `from_str`, `from_slice`, `from_reader`, `to_vec`/`to_writer`, `Value` enum,
  `Result` alias for `Result<T, serde_json::Error>`, the strongly-typed
  `Person`/`Address` derive examples, `json!` macro):
  https://docs.rs/serde_json/latest/serde_json/
- **serde-rs/serde issue #2214 — "A missing field is silently deserialized as
  None in serde_json"** (the authoritative confirmation that an absent `Option`
  field becomes `None` with no `#[serde(default)]` needed):
  https://github.com/serde-rs/serde/issues/2214
- **serde.rs — Default value for a field** (`#[serde(default)]` uses
  `Default::default()`; `#[serde(default = "path")]` calls a function;
  motivation for missing-field handling):
  https://serde.rs/attr-default.html
- **serde.rs — Derive** (`#[derive(Serialize, Deserialize)]` generates the impls
  at compile time — the codegen vs reflection story):
  https://serde.rs/derive.html
- **jsonconsole — "How do you handle missing or optional fields in serde_json?"**
  (independent corroboration: "Serde automatically treats Option fields as
  optional—missing fields deserialize to None"):
  https://jsonconsole.com/faq/questions/handle-missing-optional-fields-serde-json
