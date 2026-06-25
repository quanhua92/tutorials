//! collections.rs — Phase 5 bundle.
//!
//! GOAL (one line): show, by printing every value, what each
//! `std::collections` type does, how it performs, and — crucially — WHY a
//! `HashMap`'s iteration order is nondeterministic (SipHash random seed) so you
//! must sort keys before printing.
//!
//! This is the GROUND TRUTH for COLLECTIONS.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! DETERMINISM (the load-bearing rule here): `HashMap`/`HashSet` use a RANDOM
//! SipHash seed per process run, so their iteration order VARIES between runs.
//! This file NEVER prints a HashMap/HashSet in raw iteration order — it always
//! collects keys into a `Vec`, SORTS them, then prints (or uses a `BTreeMap`,
//! which is inherently sorted). `just out collections` is therefore
//! byte-identical on re-run. See `HOW_TO_RESEARCH.md` §4.2 rule 1.
//!
//! Run:
//!     just run collections   (== cargo run --bin collections)

use std::collections::{BTreeMap, BTreeSet, BinaryHeap, HashMap, HashSet, LinkedList, VecDeque};

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

// ── Section A: HashMap — O(1) avg lookup; keys must be SORTED to print ──────

fn section_a() {
    banner("A — HashMap: O(1)~ avg lookup; SORT keys before printing");
    let mut m: HashMap<&str, i32> = HashMap::new();
    m.insert("b", 2);
    m.insert("a", 1);
    m.insert("c", 3);
    println!("  let mut m: HashMap<&str,i32> = HashMap::new();");
    println!("  m.insert(\"b\",2); m.insert(\"a\",1); m.insert(\"c\",3);");
    println!("  m.get(\"a\") = {:?}   m.len() = {}", m.get("a"), m.len());

    // NEVER print raw iteration order (random per run). Collect + SORT + print.
    let mut keys: Vec<&str> = m.keys().copied().collect();
    keys.sort_unstable();
    println!("  keys collected into Vec, sorted = {:?}", keys);

    check("HashMap m.get(\"a\") == Some(1)", m.get("a") == Some(&1));
    check("HashMap len == 3 after three inserts", m.len() == 3);
    check(
        "HashMap sorted keys == [\"a\",\"b\",\"c\"] (we sorted; raw order varies)",
        keys == ["a", "b", "c"],
    );
}

// ── Section B: BTreeMap — ordered B-tree; iteration is ALREADY sorted ───────

fn section_b() {
    banner("B — BTreeMap: B-tree; iteration is ALREADY sorted by key");
    let mut bt: BTreeMap<&str, i32> = BTreeMap::new();
    bt.insert("charlie", 3);
    bt.insert("alpha", 1);
    bt.insert("bravo", 2);
    println!("  bt.insert(\"charlie\",3); bt.insert(\"alpha\",1); bt.insert(\"bravo\",2);");

    // BTreeMap yields keys in SORTED order with NO extra sort — deterministic.
    let first = bt.keys().next();
    println!(
        "  first key in iteration = {:?}  (smallest, despite insert order)",
        first
    );
    println!("  full iteration (already sorted, no sort needed):");
    for (k, v) in &bt {
        println!("    {k} -> {v}");
    }

    check(
        "BTreeMap iterates sorted: first key == \"alpha\" even though inserted 3rd",
        first == Some(&"alpha"),
    );
}

// ── Section C: the random-seed point — WHY we sort HashMap keys ─────────────

fn section_c() {
    banner("C — HashMap order is NONDETERMINISTIC (SipHash random seed)");
    // Same data every run, but HashMap re-seeds SipHash per process -> the raw
    // bucket order changes. We deliberately do NOT print the raw order here,
    // because it would make `_output.txt` differ on every run.
    let mut hm: HashMap<&str, i32> = HashMap::new();
    for (k, v) in [("delta", 4), ("alpha", 1), ("charlie", 3), ("bravo", 2)] {
        hm.insert(k, v);
    }

    let mut keys: Vec<&str> = hm.keys().copied().collect();
    println!("  built a HashMap of 4 entries; raw iteration order = (not printed: varies).");
    println!("  collecting keys into a Vec, then sorting them:");
    keys.sort_unstable();
    println!("    sorted keys = {:?}", keys);

    check(
        "sorted HashMap keys are STABLE across runs: [\"alpha\",\"bravo\",\"charlie\",\"delta\"]",
        keys == ["alpha", "bravo", "charlie", "delta"],
    );
}

// ── Section D: HashSet + BTreeSet — the set analogs (dedup) ─────────────────

fn section_d() {
    banner("D — HashSet & BTreeSet: the set analogs (dedup; BTreeSet sorted)");
    let mut hs: HashSet<i32> = HashSet::new();
    for x in [1, 1, 2, 2, 3] {
        hs.insert(x); // duplicates silently rejected
    }
    println!(
        "  HashSet::insert([1,1,2,2,3]) -> len = {}  (dups dropped)",
        hs.len()
    );

    check("HashSet dedups: len == 3 from [1,1,2,2,3]", hs.len() == 3);

    // BTreeSet = the sorted analog; iteration is deterministic, no sort needed.
    let bs: BTreeSet<i32> = [3, 1, 2].into_iter().collect();
    let ordered: Vec<i32> = bs.iter().copied().collect();
    println!(
        "  BTreeSet::from([3,1,2]) -> iter = {:?}  (sorted, no sort call)",
        ordered
    );

    check(
        "BTreeSet iterates sorted: [1,2,3] from input [3,1,2]",
        ordered == [1, 2, 3],
    );
}

// ── Section E: VecDeque — growable ring buffer; push/pop both ends ──────────

fn section_e() {
    banner("E — VecDeque: growable RING BUFFER; push/pop both ends");
    let mut dq: VecDeque<i32> = VecDeque::new();
    dq.push_front(1);
    dq.push_back(2);
    println!("  push_front(1); push_back(2); -> front..back = {:?}", dq);

    let front = dq.pop_front();
    let back = dq.pop_back();
    println!(
        "  pop_front() = {:?}; pop_back() = {:?}; now empty = {}",
        front,
        back,
        dq.is_empty()
    );

    check(
        "VecDeque pop_front returns the front-pushed value (1)",
        front == Some(1),
    );
    check(
        "VecDeque pop_back returns the back-pushed value (2)",
        back == Some(2),
    );
    check("VecDeque is empty after popping both ends", dq.is_empty());
}

// ── Section F: LinkedList — rarely the right choice (document why) ──────────

fn section_f() {
    banner("F — LinkedList: rarely the right choice (cache-unfriendly, no idx)");
    let mut ll: LinkedList<i32> = LinkedList::new();
    ll.push_back(1);
    ll.push_back(2);
    ll.push_front(0);
    println!("  push_back(1); push_back(2); push_front(0); -> front..back");
    println!("    front() = {:?}, back() = {:?}", ll.front(), ll.back());
    println!("  NOTE (std docs): \"It is almost always better to use Vec or VecDeque");
    println!("    because array-based containers are faster, more efficient, and");
    println!("    make better use of CPU cache.\" LinkedList is cache-unfriendly");
    println!("    (node pointers chase), and has NO O(1) random access.");

    check(
        "LinkedList: front==0 (push_front), back==2 (push_back)",
        ll.front() == Some(&0) && ll.back() == Some(&2),
    );
}

// ── Section G: the Entry API — atomic "insert if absent" (one lookup) ───────

fn section_g() {
    banner("G — Entry API: atomic upsert; avoids the double lookup");
    // `entry(k).or_insert(v)` does ONE lookup: if k is absent it inserts v and
    // returns a &mut V; if present it returns a &mut to the existing value.
    // Without the Entry API you'd do `if !contains { insert }` -> TWO lookups.
    let mut counts: HashMap<&str, i32> = HashMap::new();
    for k in ["a", "a", "b"] {
        *counts.entry(k).or_insert(0) += 1;
    }

    // HashMap again -> sort keys before printing for determinism.
    let mut keys: Vec<&str> = counts.keys().copied().collect();
    keys.sort_unstable();
    println!("  counts of [\"a\",\"a\",\"b\"] via entry().or_insert(0) += 1:");
    for k in &keys {
        println!("    {k} -> {}", counts.get(k).copied().unwrap_or(0));
    }

    check("Entry API counts 'a' twice", counts.get("a") == Some(&2));
    check("Entry API counts 'b' once", counts.get("b") == Some(&1));
}

// ── Section H: BinaryHeap — max-heap; pop yields the LARGEST first ──────────

fn section_h() {
    banner("H — BinaryHeap: MAX-heap; pop yields the largest first");
    let mut heap: BinaryHeap<i32> = BinaryHeap::new();
    heap.push(3);
    heap.push(1);
    heap.push(2);
    let peek = heap.peek().copied();
    println!(
        "  push(3); push(1); push(2);  peek() = {:?}  (root = max)",
        peek
    );

    let mut popped: Vec<i32> = Vec::new();
    while let Some(v) = heap.pop() {
        popped.push(v);
    }
    println!("  pop sequence = {:?}  (largest-first: a max-heap)", popped);

    check("BinaryHeap peek == 3 (max-heap root)", peek == Some(3));
    check(
        "BinaryHeap pops largest-first: [3,2,1]",
        popped == [3, 2, 1],
    );
}

fn main() {
    println!("collections.rs — Phase 5 bundle.");
    println!("Every value below is computed by this file.");
    println!("(HashMap/HashSet keys are ALWAYS sorted before printing.)\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    section_g();
    section_h();
    banner("DONE — all sections printed");
}
