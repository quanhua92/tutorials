//! serde_basics.rs — Phase 6 bundle (serde + serde_json).
//!
//! GOAL (one line): show, by printing every value, that `#[derive(Serialize,
//! Deserialize)]` makes a struct round-trip through JSON via
//! `serde_json::to_string` / `from_str`, and that field attributes
//! (`rename`/`default`/`skip`/`skip_serializing_if`) and `Option<T>` shape that
//! JSON in precise, assertable ways.
//!
//! This is the GROUND TRUTH for SERDE_BASICS.md. Every number, JSON string, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Run:
//!     just run serde_basics   (== cargo run --bin serde_basics)

use serde::{Deserialize, Serialize};
use serde_json::Result as JsonResult;

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

// ── The shapes under test ────────────────────────────────────────────────────
//
// NOTE: none of these fields are `pub`. serde's derive generates its Serialize /
// Deserialize impl IN THE SAME MODULE as the struct, so it can read/write
// private fields. This is the "field visibility" fact: you do NOT need public
// fields to (de)serialize. (Round-trip equality needs Debug + PartialEq.)

#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct User {
    name: String,
    age: u32,
}

#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct Profile {
    #[serde(rename = "full_name")]
    name: String,
    #[serde(default)]
    age: u32,
    #[serde(skip)]
    token: String,
}

#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct Item {
    id: u32,
    // By default, `None` serializes as JSON `null`.
    note: Option<String>,
    // `skip_serializing_if` OMITS the key entirely when it is None.
    #[serde(skip_serializing_if = "Option::is_none")]
    tag: Option<String>,
}

#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct Address {
    city: String,
    zip: u32,
}

#[derive(Serialize, Deserialize, Debug, PartialEq)]
struct Order {
    id: u32,
    ship_to: Address,
    items: Vec<String>,
}

// ── Section A: derive + round-trip ──────────────────────────────────────────

fn section_a() {
    banner("A — #[derive(Serialize, Deserialize)] + round-trip");
    let u = User {
        name: "Al".to_string(),
        age: 9,
    };
    let j = serde_json::to_string(&u).expect("User serializes");
    println!(
        "  let u = User {{ name: \"Al\", age: 9 }};  (fields are PRIVATE; serde works anyway)"
    );
    println!("  serde_json::to_string(&u) = {j}");
    check(
        "compact JSON is exactly {\"name\":\"Al\",\"age\":9} (declaration order)",
        j == r#"{"name":"Al","age":9}"#,
    );

    let back: User = serde_json::from_str(&j).expect("User deserializes");
    println!("  serde_json::from_str::<User>(&j) = {back:?}");
    check("round-trip: from_str(to_string(u)) == u", back == u);
}

// ── Section B: rename / default / skip ──────────────────────────────────────

fn section_b() {
    banner("B — field attributes: rename / default / skip");
    let p = Profile {
        name: "Bo".to_string(),
        age: 4,
        token: "secret".to_string(),
    };
    let j = serde_json::to_string(&p).expect("Profile serializes");
    println!("  Profile {{ name: \"Bo\", age: 4, token: \"secret\" }}");
    println!("  to_string(&p) = {j}");
    check(
        "rename: Rust field \"name\" -> JSON key \"full_name\"",
        j.contains(r#""full_name":"Bo""#) && !j.contains("\"name\""),
    );
    check(
        "skip: \"token\" field is ABSENT from the JSON",
        !j.contains("token"),
    );

    // `#[serde(default)]` fills a MISSING field on the way in.
    let json_no_age = r#"{"full_name":"Cy"}"#;
    let p2: Profile = serde_json::from_str(json_no_age).expect("Profile deserializes");
    println!("  from_str(r#\"{{\"full_name\":\"Cy\"}}\"#) = {p2:?}");
    check(
        "default: missing age field -> u32::default() = 0",
        p2.age == 0,
    );
    check(
        "skip: deserialized token -> String::default() = \"\"",
        p2.token.is_empty(),
    );
}

// ── Section C: Option<T> — null vs absent ───────────────────────────────────

fn section_c() {
    banner("C — Option<T>: null (default) vs absent (skip_serializing_if)");
    let none_item = Item {
        id: 1,
        note: None,
        tag: None,
    };
    let j = serde_json::to_string(&none_item).expect("Item serializes");
    println!("  Item {{ id: 1, note: None, tag: None }}");
    println!("  to_string = {j}");
    check(
        "Option None -> JSON null by default (note = null)",
        j.contains(r#""note":null"#),
    );
    check(
        "skip_serializing_if omits tag entirely when None",
        !j.contains("tag"),
    );

    let some_item = Item {
        id: 2,
        note: Some("hi".to_string()),
        tag: Some("vip".to_string()),
    };
    let j2 = serde_json::to_string(&some_item).expect("Item serializes");
    println!("  Item {{ id: 2, note: Some(\"hi\"), tag: Some(\"vip\") }}");
    println!("  to_string = {j2}");
    check(
        "Option Some(\"hi\") -> JSON \"hi\"",
        j2.contains(r#""note":"hi""#),
    );
    check("Some tag IS present in JSON", j2.contains(r#""tag":"vip""#));

    // The way back: JSON null -> None.
    let back: Item = serde_json::from_str(r#"{"id":3,"note":null}"#).expect("Item deserializes");
    println!("  from_str(r#\"{{\"id\":3,\"note\":null}}\"#) = {back:?}");
    check(
        "JSON null deserializes to Option::None",
        back.note.is_none() && back.id == 3,
    );

    // An ABSENT Option field (no #[serde(default)] needed) -> None.
    let back2: Item = serde_json::from_str(r#"{"id":4}"#).expect("Item deserializes");
    check(
        "absent Option field deserializes to None (serde Option default)",
        back2.note.is_none() && back2.tag.is_none() && back2.id == 4,
    );
}

// ── Section D: pretty vs compact ────────────────────────────────────────────

fn section_d() {
    banner("D — to_string (compact) vs to_string_pretty");
    let u = User {
        name: "Al".to_string(),
        age: 9,
    };
    let compact = serde_json::to_string(&u).expect("compact serializes");
    let pretty = serde_json::to_string_pretty(&u).expect("pretty serializes");
    println!("  compact   = {compact}");
    println!("  pretty    =");
    println!("{pretty}");
    check("compact JSON has NO newlines", !compact.contains('\n'));
    check(
        "pretty JSON is multi-line (has newlines)",
        pretty.contains('\n'),
    );
    check(
        "compact and pretty decode to the SAME User",
        serde_json::from_str::<User>(&compact).expect("compact round-trips")
            == serde_json::from_str::<User>(&pretty).expect("pretty round-trips"),
    );
}

// ── Section E: from_str errors ──────────────────────────────────────────────

fn section_e() {
    banner("E — from_str: malformed JSON / type mismatch -> Err");
    let bad = r#"{not valid json"#;
    let res: JsonResult<User> = serde_json::from_str(bad);
    match &res {
        Ok(_) => println!("  from_str({bad:?}) -> Ok (UNEXPECTED)"),
        Err(e) => println!("  from_str({bad:?}) -> Err: \"{e}\""),
    }
    check("malformed JSON -> Err(serde_json::Error)", res.is_err());

    // A structurally-valid JSON whose value TYPE is wrong for the field.
    let wrong_type = r#"{"name":"Al","age":"not a number"}"#;
    let res2: JsonResult<User> = serde_json::from_str(wrong_type);
    match &res2 {
        Ok(_) => println!("  from_str(age = \"not a number\") -> Ok (UNEXPECTED)"),
        Err(e) => println!("  from_str(age = \"not a number\") -> Err: \"{e}\""),
    }
    check(
        "type mismatch (age expects u32, got string) -> Err",
        res2.is_err(),
    );
}

// ── Section F: nested struct + Vec ──────────────────────────────────────────

fn section_f() {
    banner("F — nested struct + Vec round-trip");
    let o = Order {
        id: 7,
        ship_to: Address {
            city: "Rome".to_string(),
            zip: 100,
        },
        items: vec!["a".to_string(), "b".to_string()],
    };
    let j = serde_json::to_string(&o).expect("Order serializes");
    println!(
        "  Order {{ id: 7, ship_to: Address{{ city: \"Rome\", zip: 100 }}, items: vec![\"a\",\"b\"] }}"
    );
    println!("  to_string(&o) = {j}");
    check(
        "nested struct serialized as a nested JSON object",
        j.contains(r#""ship_to":{"city":"Rome","zip":100}"#),
    );
    check(
        "Vec serialized as a JSON array",
        j.contains(r#""items":["a","b"]"#),
    );

    let back: Order = serde_json::from_str(&j).expect("Order round-trips");
    println!("  from_str::<Order>(&j) = {back:?}");
    check(
        "nested + Vec round-trip: from_str(to_string(o)) == o",
        back == o,
    );
}

fn main() {
    println!("serde_basics.rs — Phase 6 bundle (serde + serde_json).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
