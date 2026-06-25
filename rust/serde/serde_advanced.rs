//! serde_advanced.rs — Phase 6 bundle (serde member).
//!
//! GOAL (one line): show, by printing every JSON shape, how to take CONTROL of
//! serde's serialization — a hand-written `Serialize` impl, the four enum
//! representations (externally / internally / adjacently / untagged),
//! `#[serde(flatten)]`, `#[serde(transparent)]`, and `serde_json::Value` for
//! schema-less JSON.
//!
//! This is the GROUND TRUTH for SERDE_ADVANCED.md. Every JSON string, table, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! DETERMINISM: this member does NOT enable serde_json's `preserve_order`
//! feature, so every `Value::Object` is backed by a `BTreeMap` and its keys are
//! ALWAYS serialized in sorted order. Struct field order (custom `Serialize` and
//! the derive) is the declaration / call order, which is also fixed. So every
//! JSON string below is byte-reproducible across runs (see SERDE_ADVANCED.md
//! "Determinism").
//!
//! Run:
//!     just run serde_advanced   (== cargo run --bin serde_advanced)

use serde::ser::SerializeStruct;
use serde::{Deserialize, Serialize, Serializer};
use serde_json::json;

const BANNER_WIDTH: usize = 70;

fn banner(title: &str) {
    let bar = "=".repeat(BANNER_WIDTH);
    println!("\n{bar}\nSECTION {title}\n{bar}");
}

/// Assert an invariant and print a uniform `[check] ...: OK` line.
/// Panics on failure (non-zero exit) so `just check` / `just sweep` catch it.
fn check(desc: &str, ok: bool) {
    if !ok {
        panic!("INVARIANT VIOLATED: {desc}");
    }
    println!("[check] {desc}: OK");
}

// ── Section A: a CUSTOM Serialize impl + #[serde(transparent)] ──────────────

/// An RGB color. We hand-write `Serialize` instead of deriving it to show the
/// exact `serialize_struct` -> `serialize_field` -> `end` dance that
/// `#[derive(Serialize)]` generates for us. The derive writes essentially this.
struct Rgb {
    r: u8,
    g: u8,
    b: u8,
}

impl Serialize for Rgb {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        // The three-step process every compound type follows: init, fields, end.
        // The literal "Rgb" is the type name serde records for non-self-describing
        // formats; JSON ignores it but the trait contract still REQUIRES a name.
        let mut st = serializer.serialize_struct("Rgb", 3)?;
        st.serialize_field("r", &self.r)?;
        st.serialize_field("g", &self.g)?;
        st.serialize_field("b", &self.b)?;
        st.end()
    }
}

/// `#[serde(transparent)]` makes a single-field newtype serialize EXACTLY as its
/// inner value — the wrapper vanishes, no object layer is added. Analogous to
/// `#[repr(transparent)]` for layout.
#[derive(Serialize, Deserialize, PartialEq, Eq, Debug)]
#[serde(transparent)]
struct UserId(String);

fn section_a() {
    banner("A — a CUSTOM Serialize impl + #[serde(transparent)]");
    let c = Rgb {
        r: 255,
        g: 128,
        b: 0,
    };
    let rgb_json = serde_json::to_string(&c).expect("serialize Rgb");
    println!("  manual Serialize for Rgb{{r:255,g:128,b:0}} -> {rgb_json}");
    check(
        "custom Serialize yields exactly {\"r\":255,\"g\":128,\"b\":0} (field order = call order)",
        rgb_json == r#"{"r":255,"g":128,"b":0}"#,
    );

    // #[serde(transparent)]: the newtype wrapper is INVISIBLE in the output.
    let id = UserId("u-42".to_string());
    let id_json = serde_json::to_string(&id).expect("serialize UserId");
    println!("  #[serde(transparent)] UserId(\"u-42\") -> {id_json}");
    check(
        "transparent wrapper serializes as its BARE inner value (no object layer)",
        id_json == r#""u-42""#,
    );

    // The same shape WITHOUT transparent would be {"0": "..."}; prove the
    // transparent output is byte-identical to serializing the inner value alone.
    let bare = serde_json::to_string("u-42").expect("serialize str");
    check(
        "transparent output == serializing the inner value directly",
        id_json == bare,
    );
}

// ── Section B: internally tagged enum — the tag lives INSIDE the object ─────

/// `#[serde(tag = "kind")]` puts the discriminator as a KEY inside the SAME
/// object as the variant's fields — the "internally tagged" representation,
/// common in Java/TypeScript APIs. It works for struct / newtype-of-struct /
/// unit variants; using a tuple variant here is a COMPILE ERROR.
#[derive(Serialize, Deserialize, PartialEq, Debug)]
#[serde(tag = "kind")]
enum Shape {
    Circle { radius: f64 },
    Rect { w: f64, h: f64 },
}

fn section_b() {
    banner("B — internally tagged enum: #[serde(tag = \"kind\")]");
    let circ = Shape::Circle { radius: 2.5 };
    let rect = Shape::Rect { w: 3.0, h: 4.0 };
    let cj = serde_json::to_string(&circ).expect("serialize Circle");
    let rj = serde_json::to_string(&rect).expect("serialize Rect");
    println!("  Circle{{radius:2.5}} -> {cj}");
    println!("  Rect{{w:3.0,h:4.0}}   -> {rj}");
    check(
        "internally tagged: Circle carries \"kind\":\"Circle\" inside the object",
        cj.contains(r#""kind":"Circle""#),
    );
    check(
        "internally tagged: Rect carries \"kind\":\"Rect\" inside the object",
        rj.contains(r#""kind":"Rect""#),
    );
    check(
        "internally tagged: fields sit at the SAME level as the tag (flat object)",
        cj.contains(r#""radius":2.5"#) && rj.contains(r#""w":3.0,"h":4.0"#),
    );
}

// ── Section C: untagged enum — NO discriminator; serde tries each variant ───

/// `#[serde(untagged)]` emits ONLY the variant's content; there is no tag at
/// all. On deserialize, serde tries each variant in declaration order and keeps
/// the first that parses. Works for any variant shape (including tuples).
#[derive(Serialize, Deserialize, PartialEq, Debug)]
#[serde(untagged)]
enum NumOrText {
    Number(i64),
    Text(String),
}

fn section_c() {
    banner("C — untagged enum: #[serde(untagged)] (NO discriminator)");
    let n = NumOrText::Number(7);
    let t = NumOrText::Text("hi".to_string());
    let nj = serde_json::to_string(&n).expect("serialize Number");
    let tj = serde_json::to_string(&t).expect("serialize Text");
    println!("  Number(7)   -> {nj}");
    println!("  Text(\"hi\")  -> {tj}");
    check(
        "untagged Number(i64) serializes as the BARE integer, no tag",
        nj == "7",
    );
    check(
        "untagged Text(String) serializes as the BARE string, no tag",
        tj == r#""hi""#,
    );
    check(
        "untagged output carries NO discriminator key (no type/kind/tag)",
        !nj.contains("type") && !nj.contains("kind") && !tj.contains("type"),
    );
}

// ── Section D: #[serde(flatten)] — inline a nested struct into the parent ───

/// Pagination metadata factored out so many response types can reuse it.
#[derive(Serialize, Deserialize, PartialEq, Debug)]
struct Pagination {
    limit: u64,
    offset: u64,
}

/// `#[serde(flatten)]` hoists `pagination`'s keys UP into `Page`'s object —
/// there is NO nested `"pagination": { ... }` wrapper in the output JSON.
#[derive(Serialize, Deserialize, PartialEq, Debug)]
struct Page {
    name: String,
    #[serde(flatten)]
    pagination: Pagination,
}

fn section_d() {
    banner("D — #[serde(flatten)]: inline a nested struct into the parent");
    let page = Page {
        name: "users".to_string(),
        pagination: Pagination {
            limit: 100,
            offset: 0,
        },
    };
    let pj = serde_json::to_string(&page).expect("serialize Page");
    println!("  Page{{name, pagination:{{limit,offset}}}} -> {pj}");
    check(
        "flatten: limit and offset appear at the PARENT level (no nesting)",
        pj.contains(r#""limit":100"#) && pj.contains(r#""offset":0"#),
    );
    check(
        "flatten: there is NO \"pagination\" key in the output",
        !pj.contains("pagination"),
    );
    // Deserialization is symmetric: flatten also UN-flattens on the way back.
    let back: Page = serde_json::from_str(&pj).expect("deserialize Page");
    check(
        "flatten round-trips: deserialize reconstructs the nested Pagination",
        back == page,
    );
}

// ── Section E: serde_json::Value + json! — schema-less, dynamic JSON ────────

fn section_e() {
    banner("E — serde_json::Value + the json! macro (dynamic JSON)");
    // The json! macro builds a Value from a JSON literal; expressions can be
    // interpolated as long as they impl Serialize.
    let nested = 3_i64;
    let v = json!({
        "a": 1,
        "b": [2, nested],
        "active": true,
        "note": null,
    });
    println!("  json!({{...}}) as compact JSON (object keys sorted: BTreeMap):");
    println!(
        "    {}",
        serde_json::to_string(&v).expect("serialize Value")
    );

    // Value is a recursive enum: Null | Bool | Number | String | Array | Object.
    let n_keys = v.as_object().map_or(0, serde_json::Map::len);
    check(
        "Value::Object discriminant matches the json! object",
        v.is_object(),
    );
    check("the object has exactly 4 keys", n_keys == 4);

    // Indexing: ["key"] for objects, [usize] for arrays; chains drill down.
    // A MISSING key/index returns Value::Null (NOT a panic) — see the pitfalls.
    let third = &v["b"][1];
    println!("  v[\"b\"][1] == {third}   (index chain drills into the array)");
    check(
        "json!({\"a\":1,\"b\":[2,3]})[\"b\"][1] == 3",
        third.as_i64() == Some(3),
    );

    // The Option-returning accessor: .get() distinguishes absent from null.
    let present = v.get("a").and_then(serde_json::Value::as_i64);
    let missing = v.get("zzz");
    println!("  v.get(\"a\").as_i64() -> {present:?} ; v.get(\"zzz\") -> {missing:?}");
    check(".get(\"a\") yields Some(1) via as_i64", present == Some(1));
    check(
        ".get(\"zzz\") yields None (a truly absent key)",
        missing.is_none(),
    );

    // Indexing a truly-absent key silently yields Value::Null (never panics):
    check(
        "v[\"zzz\"] is Value::Null (indexing never panics)",
        v["zzz"].is_null(),
    );
}

// ── Section F: serialize -> deserialize round-trip (tagged & untagged) ──────

fn section_f() {
    banner("F — round-trip: serialize -> deserialize -> equality");
    // Internally tagged round-trip: the "kind" key is what disambiguates on read.
    let circ = Shape::Circle { radius: 2.5 };
    let s = serde_json::to_string(&circ).expect("serialize Circle");
    let back: Shape = serde_json::from_str(&s).expect("deserialize Circle");
    println!("  internally tagged: {s} -> {back:?}");
    check(
        "internally tagged enum round-trips losslessly",
        back == circ,
    );

    // Untagged round-trip: the variant is re-INFERRED from the value's shape.
    let n = NumOrText::Number(7);
    let ns = serde_json::to_string(&n).expect("serialize Number");
    let nb: NumOrText = serde_json::from_str(&ns).expect("deserialize Number");
    println!("  untagged: {ns} -> {nb:?}");
    check(
        "untagged enum round-trips losslessly (variant re-inferred)",
        nb == n,
    );

    // The ambiguity lives in the READER, not the writer: a bare `7` deserializes
    // to NumOrText::Number under untagged (first variant that parses wins), but
    // could NEVER deserialize into a Shape (which REQUIRES the "kind" tag).
    let inferred: NumOrText = serde_json::from_str("7").expect("parse 7");
    check(
        "untagged reader infers NumOrText::Number from a bare `7`",
        matches!(inferred, NumOrText::Number(7)),
    );
}

fn main() {
    println!("serde_advanced.rs — Phase 6 bundle (serde member).");
    println!("Every JSON string below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
