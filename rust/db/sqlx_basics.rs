//! sqlx_basics.rs — Phase 8 bundle (db member).
//!
//! GOAL (one line): show, by running every query against an in-memory SQLite
//! database, how sqlx's async SQL toolkit works — a connection POOL, parameterized
//! `query`, mapped `query_as` + `FromRow`, single-row fetches, and TRANSACTIONS —
//! and to document (in SQLX_BASICS.md) the compile-time-checked `query!` macro that
//! this runnable file deliberately does NOT use (it uses runtime-checked queries so
//! it compiles with no DB at build time).
//!
//! This is the GROUND TRUTH for SQLX_BASICS.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run -> re-paste.
//! Never hand-compute.
//!
//! Run:
//!     just run sqlx_basics   (== cargo run --bin sqlx_basics)
//!
//! DETERMINISM: the database is a fresh in-memory SQLite DB with FIXED seed rows,
//! created per run. All multi-row SELECTs use `ORDER BY`, so output is byte-stable.
//! The pool uses the SHARED in-memory connect string (`sqlite::memory:?cache=shared`)
//! so every connection in the pool sees the SAME in-memory database (see Section A
//! for why the bare `sqlite::memory:` form is a trap).

use sqlx::FromRow;
use sqlx::sqlite::{SqlitePool, SqlitePoolOptions};

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

/// A row of `widgets`. `FromRow` (derived) is what lets `query_as` map a database
/// row into this struct field-by-field via `Row::try_get`. `Debug` lets us print it.
/// Field names match the column names verbatim (sqlx maps by name, not position).
#[derive(Debug, FromRow)]
struct Widget {
    id: i64,
    name: String,
}

// ── Section A: connect (a shared in-memory POOL) + CREATE TABLE ──────────────

/// Build a POOL over a single SHARED in-memory SQLite database.
///
/// `sqlite::memory:?cache=shared` is the load-bearing detail: SQLite shared-cache
/// mode makes every connection opened by the pool talk to the SAME in-memory
/// database. The bare `sqlite::memory:` form gives each NEW (or recycled) pool
/// connection its OWN private empty database — a silent trap; see SQLX_BASICS.md.
async fn make_pool() -> Result<SqlitePool, sqlx::Error> {
    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect("sqlite::memory:?cache=shared")
        .await?;
    sqlx::query("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        .execute(&pool)
        .await?;
    Ok(pool)
}

async fn section_a(pool: &SqlitePool) -> Result<(), sqlx::Error> {
    banner("A — POOL + shared in-memory DB + CREATE TABLE");
    println!("  SqlitePoolOptions::new().max_connections(5)");
    println!("    .connect(\"sqlite::memory:?cache=shared\").await  -> POOL");
    println!(
        "  pool.size() = {},  num_idle() = {}",
        pool.size(),
        pool.num_idle()
    );
    println!("  query(\"CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT NOT NULL)\")");
    println!("    .execute(&pool).await  -> DDL applied (ok)");
    check("shared in-memory pool connects and applies DDL", true);
    Ok(())
}

// ── Section B: parameterized INSERT (SQL-injection-safe; `?` bind) ───────────

async fn section_b(pool: &SqlitePool) -> Result<(), sqlx::Error> {
    banner("B — parameterized INSERT (bind values, never concatenate SQL)");
    let names = ["alpha", "bravo", "charlie"];
    let mut rows_affected = 0u64;
    for name in names {
        let res = sqlx::query("INSERT INTO widgets (name) VALUES (?)")
            .bind(name)
            .execute(pool)
            .await?;
        rows_affected += res.rows_affected();
    }
    println!("  3 x query(\"INSERT INTO widgets (name) VALUES (?)\").bind(name)");
    println!("    .execute(&pool).await   (the `?` is a prepared-statement bind)");
    println!("  total rows_affected = {}", rows_affected);
    check(
        "3 parameterized inserts affected exactly 3 rows",
        rows_affected == 3,
    );
    let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM widgets")
        .fetch_one(pool)
        .await?;
    println!("  SELECT COUNT(*) FROM widgets  -> {count}");
    check("table holds exactly 3 rows after the inserts", count == 3);
    Ok(())
}

// ── Section C: query_as + FromRow -> Vec<Widget>, ORDER BY for determinism ───

async fn section_c(pool: &SqlitePool) -> Result<(), sqlx::Error> {
    banner("C — query_as + FromRow: map rows into Vec<Widget>");
    let widgets: Vec<Widget> = sqlx::query_as("SELECT id, name FROM widgets ORDER BY id")
        .fetch_all(pool)
        .await?;
    println!("  query_as::<_, Widget>(\"SELECT id, name FROM widgets ORDER BY id\")");
    println!(
        "    .fetch_all(&pool).await  -> Vec<Widget> ({} rows):",
        widgets.len()
    );
    for w in &widgets {
        println!("    {{ id: {}, name: {:?} }}", w.id, w.name);
    }
    check("query_as mapped all 3 rows", widgets.len() == 3);
    check(
        "ORDER BY id yields the deterministic sequence 1,2,3",
        widgets.iter().map(|w| w.id).eq([1, 2, 3]),
    );
    check(
        "FromRow mapped names in id order: alpha, bravo, charlie",
        widgets[0].name == "alpha" && widgets[1].name == "bravo" && widgets[2].name == "charlie",
    );
    Ok(())
}

// ── Section D: a single row — fetch_one (exactly one) vs fetch_optional (0..1) ─

async fn section_d(pool: &SqlitePool) -> Result<(), sqlx::Error> {
    banner("D — single row: fetch_one vs fetch_optional");
    let one: Widget = sqlx::query_as("SELECT id, name FROM widgets WHERE id = ?")
        .bind(1i64)
        .fetch_one(pool)
        .await?;
    println!(
        "  query_as(...WHERE id = 1).fetch_one(&pool).await  -> {{ id: {}, name: {:?} }}",
        one.id, one.name
    );
    check(
        "fetch_one found id 1 == alpha",
        one.id == 1 && one.name == "alpha",
    );

    let missing: Option<Widget> = sqlx::query_as("SELECT id, name FROM widgets WHERE id = ?")
        .bind(999i64)
        .fetch_optional(pool)
        .await?;
    println!(
        "  query_as(...WHERE id = 999).fetch_optional(&pool).await  -> {:?}",
        missing.as_ref().map(|w| &w.name)
    );
    check(
        "fetch_optional on a missing id returns None",
        missing.is_none(),
    );
    Ok(())
}

// ── Section E: a TRANSACTION — begin / commit, and the drop => rollback path ─

async fn section_e(pool: &SqlitePool) -> Result<(), sqlx::Error> {
    banner("E — TRANSACTION: begin + commit (kept), and drop => rollback (discarded)");

    // COMMIT path: two inserts inside one transaction, then commit.
    let mut tx = pool.begin().await?;
    sqlx::query("INSERT INTO widgets (name) VALUES (?)")
        .bind("delta")
        .execute(&mut *tx)
        .await?;
    sqlx::query("INSERT INTO widgets (name) VALUES (?)")
        .bind("echo")
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    println!("  pool.begin() -> insert delta, echo -> tx.commit().await  (kept)");
    let total: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM widgets")
        .fetch_one(pool)
        .await?;
    println!("  SELECT COUNT(*) FROM widgets  -> {total}  (3 base + 2 committed)");
    check("committed transaction added 2 rows -> total 5", total == 5);

    // ROLLBACK path: insert inside a transaction, then DROP it without committing.
    // Dropping a Transaction rolls it back (fire-and-forget; see SQLX_BASICS.md).
    {
        let mut tx = pool.begin().await?;
        sqlx::query("INSERT INTO widgets (name) VALUES (?)")
            .bind("foxtrot")
            .execute(&mut *tx)
            .await?;
        println!("  pool.begin() -> insert foxtrot -> DROP tx (no commit) => rollback");
    } // <- tx dropped here: the insert is rolled back
    let foxtrot: Option<String> = sqlx::query_scalar("SELECT name FROM widgets WHERE name = ?")
        .bind("foxtrot")
        .fetch_optional(pool)
        .await?;
    println!("  SELECT name ... WHERE name = 'foxtrot'  -> {:?}", foxtrot);
    check("rolled-back row 'foxtrot' is absent", foxtrot.is_none());
    Ok(())
}

// ── Section F: compile-time checking is DOCUMENTED (this file uses runtime checks) ─

async fn section_f() {
    banner("F — compile-time `query!` macro (DOCUMENTED, not used here)");
    println!("  sqlx offers TWO query APIs:");
    println!("    * runtime-checked : sqlx::query(..) / query_as(..)   <- THIS file");
    println!("    * compile-time    : sqlx::query!(..) / query_as!(..)  <- macro,");
    println!("                        checks SQL against a DB at BUILD time.");
    println!("  The macros need DATABASE_URL (or a committed `.sqlx` offline cache");
    println!("  from `cargo sqlx prepare`) at build time. This runnable bundle uses");
    println!("  the RUNTIME forms so it compiles with NO database at build time.");
    println!("  See SQLX_BASICS.md -> Section F for the full macro + offline workflow.");
    check(
        "bundle uses runtime-checked query/query_as (compiles offline)",
        true,
    );
}

#[tokio::main]
async fn main() -> Result<(), sqlx::Error> {
    println!("sqlx_basics.rs — Phase 8 bundle (db member).");
    println!("Every value below comes from a live in-memory SQLite database.\n");

    let pool = make_pool().await?;
    section_a(&pool).await?;
    section_b(&pool).await?;
    section_c(&pool).await?;
    section_d(&pool).await?;
    section_e(&pool).await?;
    section_f().await;
    pool.close().await; // graceful shutdown (Pool docs recommend .close().await)
    banner("DONE — all sections printed");
    Ok(())
}
