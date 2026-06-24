//! box_rc_arc.rs — Phase 3 bundle #1 (Memory & Smart Pointers).
//!
//! GOAL (one line): show, by printing every value, how Rust's three heap smart
//! pointers split ownership three ways — `Box<T>` (ONE owner, on the heap),
//! `Rc<T>` (SHARED owners, single thread, non-atomic refcount), and `Arc<T>`
//! (SHARED owners, ANY thread, atomic refcount) — and how `Weak<T>` breaks the
//! reference cycles that would otherwise leak.
//!
//! This is the GROUND TRUTH for BOX_RC_ARC.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Several facts here are COMPILE-TIME properties that cannot live in a runnable
//! file (e.g. `Rc<T>` is `!Send`/`!Sync`). They are documented in BOX_RC_ARC.md
//! with the exact compiler error (`E0277`); where a property IS runnable, this
//! file proves it with a `check(...)` or a compile-time witness.
//!
//! Run:
//!     just run box_rc_arc   (== cargo run --bin box_rc_arc)

use std::cell::RefCell;
use std::rc::{Rc, Weak};
use std::sync::Arc;
use std::thread;

const BANNER_WIDTH: usize = 70;

fn banner(title: &str) {
    let bar: String = "=".repeat(BANNER_WIDTH);
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

/// Compile-time witness: this function only compiles if `T: Send + Sync`.
/// Calling `is_send_sync::<Arc<i32>>()` proves `Arc<i32>` is `Send + Sync`.
/// (Calling it with `Rc<i32>` would be a compile error — `E0277` — see Section E.)
fn is_send_sync<T: Send + Sync>() {}

// ── Section A: Box<T> — ONE owner of heap data; a pointer is all it is ───────

/// A recursive type needs indirection, or its size would be infinite. `Box<List>`
/// provides that indirection: a `Box` is one pointer, so `List` becomes finite.
enum List {
    Cons(i32, Box<List>),
    Nil,
}

use List::{Cons, Nil};

/// Recursively sum a cons list — borrows it (`&List`), takes no ownership.
fn list_sum(l: &List) -> i32 {
    match l {
        Cons(head, tail) => head + list_sum(tail),
        Nil => 0,
    }
}

trait Greet {
    fn greet(&self) -> String;
}

struct English;

impl Greet for English {
    fn greet(&self) -> String {
        String::from("hello")
    }
}

fn section_a() {
    banner("A — Box<T>: ONE owner of heap data; a pointer is all it is");
    // `Box::new` moves the value onto the HEAP; the stack holds only the pointer.
    let b: Box<u64> = Box::new(42);
    println!("  let b = Box::new(42_u64);");
    println!(
        "    *b = {}  (Deref: a Box<T> behaves like the value it owns)",
        b
    );

    // A Box is literally ONE pointer, so its size is one usize regardless of T.
    let box_u64 = std::mem::size_of::<Box<u64>>();
    let usize_sz = std::mem::size_of::<usize>();
    println!(
        "    size_of::<Box<u64>>() = {} == size_of::<usize>() = {}",
        box_u64, usize_sz
    );
    check(
        "Box<T> is one pointer: size_of::<Box<u64>>() == size_of::<usize>() == 8",
        box_u64 == usize_sz && box_u64 == 8,
    );
    check(
        "Box<T> owns the value: *b == 42 (Deref works like &T)",
        *b == 42,
    );

    // Recursive type: without the `Box`, `enum List { Cons(i32, List), Nil }`
    // has infinite size (E0072). The Box breaks the cycle -> a finite size.
    let list = Cons(1, Box::new(Cons(2, Box::new(Cons(3, Box::new(Nil))))));
    let sum = list_sum(&list);
    println!(
        "  Cons(1, Box(Cons(2, Box(Cons(3, Box(Nil)))))) ; list_sum = {}",
        sum
    );
    check(
        "Box enables a recursive type (the cons list sums to 6)",
        sum == 6,
    );

    // Trait object: `Box<dyn Greet>` sized-izes a DST (`dyn Greet` has no static
    // size). One Box here is a FAT pointer = data ptr + vtable ptr.
    let g: Box<dyn Greet> = Box::new(English);
    let word = g.greet();
    let box_dyn_sz = std::mem::size_of::<Box<dyn Greet>>();
    println!(
        "  let g: Box<dyn Greet> = Box::new(English); g.greet() = {:?}",
        word
    );
    println!(
        "    size_of::<Box<dyn Greet>>() = {} (data-ptr + vtable-ptr = 2 usizes)",
        box_dyn_sz
    );
    check(
        "Box<dyn Trait> is a fat pointer: 2 * usize == 16",
        box_dyn_sz == 2 * usize_sz,
    );
}

// ── Section B: Rc<T> — SHARED ownership, SINGLE thread (non-atomic refcount) ─

fn section_b() {
    banner("B — Rc<T>: SHARED ownership, SINGLE thread (non-atomic refcount)");
    // `Rc::new` creates the shared allocation; strong_count starts at 1.
    let a = Rc::new(String::from("shared"));
    let c1 = Rc::strong_count(&a);
    println!(
        "  let a = Rc::new(\"shared\");  Rc::strong_count(&a) = {}",
        c1
    );
    check("Rc::new -> strong_count == 1", c1 == 1);

    // `Rc::clone` does NOT deep-copy — it bumps the (non-atomic) refcount and
    // hands back another owner pointing at the SAME heap allocation.
    let b = Rc::clone(&a);
    let c2 = Rc::strong_count(&a);
    println!(
        "  let b = Rc::clone(&a);      Rc::strong_count(&a) = {}",
        c2
    );
    check("one Rc::clone -> strong_count == 2", c2 == 2);

    {
        // `_c` (underscore-prefixed) is intentionally unused but still OWNED,
        // so it lives to the block's `}` and drops there (NOT instant, like `_`).
        let _c = Rc::clone(&a);
        let c3 = Rc::strong_count(&a);
        println!(
            "  let _c = Rc::clone(&a);     Rc::strong_count(&a) = {}",
            c3
        );
        check("two Rc::clone -> strong_count == 3", c3 == 3);
    } // <- `_c` drops here: `Drop` decrements the refcount automatically.
    let c2b = Rc::strong_count(&a);
    println!(
        "  (inner `c` dropped at `}}`)  Rc::strong_count(&a) = {}",
        c2b
    );
    check(
        "dropping one clone decrements strong_count back to 2",
        c2b == 2,
    );

    // The two live owners see the SAME value (shared, read-only).
    println!("  a = {:?}, b = {:?}  (both owners, one allocation)", a, b);
    check("Rc shares data: both owners read the same value", a == b);
}

// ── Section C: Weak<T> — a non-owning reference (does not keep it alive) ──────

fn section_c() {
    banner("C — Weak<T>: a non-owning reference (does not keep the value alive)");
    let strong = Rc::new(99_i32);
    println!(
        "  let strong = Rc::new(99);  strong_count = {}, weak_count = {}",
        Rc::strong_count(&strong),
        Rc::weak_count(&strong)
    );

    // `Rc::downgrade` makes a Weak<T>: it bumps weak_count (NOT strong_count), so
    // it expresses NO ownership — the value can be freed while Weak refs exist.
    let weak: Weak<i32> = Rc::downgrade(&strong);
    println!(
        "  let weak = Rc::downgrade(&strong);  strong_count = {}, weak_count = {}",
        Rc::strong_count(&strong),
        Rc::weak_count(&strong)
    );
    check(
        "Rc::downgrade bumps weak_count, not strong_count",
        Rc::strong_count(&strong) == 1 && Rc::weak_count(&strong) == 1,
    );

    // While a strong ref is alive, `Weak::upgrade` returns Some(Rc<T>).
    let live: Option<i32> = weak.upgrade().as_deref().copied();
    println!("  weak.upgrade() while alive -> {:?}", live);
    check(
        "Weak::upgrade on a LIVE value -> Some(99)",
        live == Some(99),
    );

    // Drop ALL strong refs: the value is freed even though `weak` still exists.
    drop(strong);
    let dead: Option<i32> = weak.upgrade().as_deref().copied();
    println!("  after `drop(strong)`: weak.upgrade() -> {:?}", dead);
    check(
        "Weak::upgrade after all strong refs drop -> None (value freed)",
        dead.is_none(),
    );
}

// ── Section D: Arc<T> — ATOMIC refcount (shared ownership across THREADS) ────

fn section_d() {
    banner("D — Arc<T>: ATOMIC refcount — shared ownership across THREADS");
    // `Arc::new` is like `Rc::new`, but the refcount is updated with ATOMIC ops,
    // so the count stays correct even when many threads clone concurrently.
    let a = Arc::new(vec![10, 20, 30]);
    let c1 = Arc::strong_count(&a);
    println!("  let a = Arc::new(vec![10,20,30]);  strong_count = {}", c1);
    check("Arc::new -> strong_count == 1", c1 == 1);

    // Arc is `Send` (when T: Send + Sync), so we can MOVE a clone into a thread.
    // Cloning bumps the count to 2 (a + the clone); the clone then moves in.
    // The worker returns its result; we join before printing -> deterministic.
    let a_clone = Arc::clone(&a);
    let c2 = Arc::strong_count(&a);
    println!("  let a_clone = Arc::clone(&a);     strong_count = {}", c2);
    check("Arc::clone -> strong_count == 2", c2 == 2);

    let handle = thread::spawn(move || {
        let count_in_thread = Arc::strong_count(&a_clone);
        let sum: i32 = a_clone.iter().sum();
        (count_in_thread, sum)
    });
    let (count_in_thread, sum) = handle.join().expect("worker thread panicked");
    println!(
        "  spawned thread: strong_count seen inside = {}, sum = {}",
        count_in_thread, sum
    );
    check(
        "Arc crossed into a thread; worker saw strong_count == 2 (a + its clone)",
        count_in_thread == 2 && sum == 60,
    );

    // After the thread dropped its clone (closure return), count is back to 1.
    let c_after = Arc::strong_count(&a);
    println!(
        "  after thread joined (its clone dropped): strong_count = {}",
        c_after
    );
    check(
        "Arc count returns to 1 after the thread's clone drops",
        c_after == 1,
    );
}

// ── Section E: why Rc<T> is !Send / !Sync (documented; compile-proved) ───────

fn section_e() {
    banner("E — why Rc<T> is !Send / !Sync (documented; Arc proven Send+Sync)");
    // This is a COMPILE-TIME guarantee. The following does NOT compile, so it
    // cannot appear in a runnable file (shown verbatim in BOX_RC_ARC.md):
    //
    //   let r = std::rc::Rc::new(1);
    //   std::thread::spawn(move || { let _ = r; });
    //
    //   error[E0277]: `Rc<{integer}>` cannot be sent between threads safely
    //     --> the trait `Send` is not implemented for `Rc<{integer}>`
    //
    // WHY: Rc's refcount is a plain integer. Two threads doing Rc::clone / drop
    // at once would race that counter (lost increment -> double free or
    // use-after-free). The compiler forbids the move statically. Arc uses ATOMIC
    // increments, so it IS Send/Sync. Use Arc for any data crossing threads.

    // Runnable proof: the program compiles ONLY because Arc<i32>: Send + Sync.
    is_send_sync::<Arc<i32>>();
    println!("  is_send_sync::<Arc<i32>>() compiled -> Arc<i32>: Send + Sync.");
    println!("  (is_send_sync::<Rc<i32>>() would be E0277 -> Rc is !Send/!Sync.)");
    check(
        "Arc<i32> is Send + Sync (compile-time proved); Rc<i32> is not",
        true,
    );
}

// ── Section F: reference cycles LEAK; Weak<T> breaks them ────────────────────

/// A graph node for the cycle demo. The `next` link is behind
/// `RefCell<Option<Rc<Node>>>` so it can be re-pointed after construction
/// (interior mutability — see the INTERIOR_MUTABILITY bundle).
struct Node {
    value: i32,
    next: RefCell<Option<Rc<Node>>>,
}

/// A tree node for the "Weak breaks the cycle" demo: a parent OWNS its children
/// (strong `Rc`), while a child only borrows its parent (weak `Weak`).
struct TreeNode {
    value: i32,
    parent: RefCell<Weak<TreeNode>>,
    children: RefCell<Vec<Rc<TreeNode>>>,
}

fn section_f() {
    banner("F — reference cycles LEAK; Weak<T> breaks them");
    cycle_leak();
    cycle_broken_by_weak();
}

fn cycle_leak() {
    println!("\n  -- a cycle of two Rcs: LEAKS (refcount never hits 0) --");
    let a = Rc::new(Node {
        value: 1,
        next: RefCell::new(None),
    });
    let b = Rc::new(Node {
        value: 2,
        next: RefCell::new(Some(Rc::clone(&a))),
    });
    let weak_a: Weak<Node> = Rc::downgrade(&a); // observer: does NOT keep `a` alive
    // Close the loop: a.next -> b, b.next -> a (a -> b -> a -> ...).
    *a.next.borrow_mut() = Some(Rc::clone(&b));
    let a_strong = Rc::strong_count(&a);
    let b_strong = Rc::strong_count(&b);
    println!(
        "  after cycle: a strong_count = {}, b strong_count = {}",
        a_strong, b_strong
    );
    check(
        "cycle: a and b each have strong_count == 2 (each pointed at by the other)",
        a_strong == 2 && b_strong == 2,
    );

    // Drop both named handles. Their counts fall 2 -> 1, never 0 (each node is
    // still pointed at by the other's `next`), so BOTH allocations LEAK. The
    // leak is OBSERVABLE: weak_a still upgrades even with no named owner.
    drop(a);
    drop(b);
    let leaked: Option<i32> = weak_a.upgrade().map(|n| n.value);
    println!(
        "  after dropping both handles: weak_a.upgrade() -> {:?}",
        leaked
    );
    check(
        "Rc cycle LEAKS: node `a` survives with no named owner (weak_a still upgrades)",
        leaked == Some(1),
    );
    // NOTE: we never print the cyclic graph's Debug — a -> b -> a -> ... recurses
    // forever and overflows the stack (the Book warns about exactly this).
}

fn cycle_broken_by_weak() {
    println!("\n  -- same shape, but child->parent is Weak: NO leak --");
    // branch OWNS leaf (strong, in children); leaf -> branch is WEAK, so it does
    // not keep branch alive. When branch drops, branch frees; leaf's weak dies.
    let leaf = Rc::new(TreeNode {
        value: 3,
        parent: RefCell::new(Weak::new()),
        children: RefCell::new(vec![]),
    });
    let parent_before = leaf.parent.borrow().upgrade().is_some();
    println!(
        "  leaf.parent.upgrade() before branch exists -> {}",
        parent_before
    );

    {
        let branch = Rc::new(TreeNode {
            value: 5,
            parent: RefCell::new(Weak::new()),
            children: RefCell::new(vec![Rc::clone(&leaf)]),
        });
        *leaf.parent.borrow_mut() = Rc::downgrade(&branch);

        let leaf_strong = Rc::strong_count(&leaf);
        let branch_strong = Rc::strong_count(&branch);
        let branch_weak = Rc::weak_count(&branch);
        let branch_children = branch.children.borrow().len();
        println!(
            "  inside scope: leaf strong={}, branch strong={}, branch weak={}, branch children={}",
            leaf_strong, branch_strong, branch_weak, branch_children
        );
        check(
            "branch owns leaf (leaf strong=2, branch owns 1 child); leaf->branch is weak (branch weak=1)",
            leaf_strong == 2 && branch_strong == 1 && branch_weak == 1 && branch_children == 1,
        );
        let parent_live = leaf.parent.borrow().upgrade().is_some();
        println!(
            "  leaf.parent.upgrade() while branch alive -> {}",
            parent_live
        );
        check(
            "while branch is alive, leaf.parent.upgrade() -> Some",
            parent_live,
        );
    } // branch drops: strong_count 1 -> 0 -> branch FREED (weak_count ignored).

    let parent_dead = leaf.parent.borrow().upgrade().is_none();
    println!(
        "  after branch dropped: leaf.parent.upgrade() -> None? {} (branch FREED)",
        parent_dead
    );
    check(
        "Weak broke the cycle: branch was freed (leaf.parent.upgrade() -> None)",
        parent_dead,
    );
    check(
        "leaf still owned by its own handle (strong_count == 1), value still readable",
        Rc::strong_count(&leaf) == 1 && leaf.value == 3,
    );
}

fn main() {
    println!("box_rc_arc.rs — Phase 3 bundle #1 (Memory & Smart Pointers).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
