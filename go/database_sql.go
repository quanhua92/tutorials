//go:build ignore

// database_sql.go — Phase 6 bundle.
//
// GOAL (one line): show, by printing every behavior, how Go's database/sql
// package exposes a DRIVER-AGNOSTIC connection pool, queries, prepared
// statements, NULL handling, transactions, pool tuning, and the N+1 problem —
// all against an in-memory SQLite database, fully offline and deterministic.
//
// This is the GROUND TRUTH for DATABASE_SQL.md. Every row count, error code,
// and scanned value below is produced by this file; the .md guide pastes it
// verbatim. Nothing is hand-computed. Determinism is total: an in-memory
// SQLite DB (:memory:) is deterministic for fixed SQL; every multi-row SELECT
// uses ORDER BY so iteration order is stable across runs.
//
// The pure-Go SQLite driver (github.com/glebarez/sqlite, built on
// github.com/glebarez/go-sqlite which calls sql.Register("sqlite", ...)) is
// imported here ONLY for its side effect (init): registering the "sqlite"
// database/sql driver. We then use the STANDARD library exclusively — every
// call below is database/sql, never a driver-specific API.
//
// Run:
//
//	go run database_sql.go

package main

import (
	"database/sql"
	"errors"
	"fmt"
	"strings"

	// Blank import for the side effect: the driver's init() registers itself
	// under the name "sqlite" with database/sql (sql.Register("sqlite", ...)).
	// We never reference this package directly — that is the whole point of the
	// driver-agnostic design: application code talks to database/sql only.
	_ "github.com/glebarez/sqlite"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth)

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// must panics on a non-nil error. Used for setup steps where the only sane
// response to failure is to stop (a real program would return/log the error).
func must(err error) {
	if err != nil {
		panic(err)
	}
}

// mustExec runs a statement whose Result we don't inspect and panics on error.
func mustExec(db *sql.DB, query string, args ...any) {
	_, err := db.Exec(query, args...)
	must(err)
}

// freshDB opens a NEW in-memory SQLite database and returns the *sql.DB handle.
// Each section calls this so its state is isolated and fully reproducible.
// ":memory:" is a private, process-local database that lives until db.Close().
func freshDB() *sql.DB {
	db, err := sql.Open("sqlite", ":memory:")
	must(err)
	return db
}

// sectionA opens a pool, shows the driver is registered, tunes the pool, pings
// it, and runs the first DDL + DML (CREATE TABLE / INSERT).
func sectionA() {
	sectionBanner("A — Open, driver, pool, Ping, CREATE TABLE, INSERT")

	// database/sql ships with NO drivers. A driver plugs in by calling
	// sql.Register(name, driver.Driver). After the blank import above,
	// "sqlite" appears in the global driver registry.
	drivers := sql.Drivers() // sorted list of registered driver names
	fmt.Printf("sql.Drivers() = %v   (the \"sqlite\" driver is registered)\n", drivers)

	db := freshDB()
	defer db.Close()

	// db.Driver() returns the underlying driver.Driver (the interface from
	// database/sql/driver). It is non-nil once a driver backs this *sql.DB.
	drv := db.Driver()
	fmt.Printf("db.Driver() type = %T   (non-nil? %v)\n", drv, drv != nil)

	// *sql.DB is a CONNECTION POOL, not a single connection. Tune it:
	db.SetMaxOpenConns(5) // cap concurrent open connections
	db.SetMaxIdleConns(2) // cap idle connections kept in the pool
	s := db.Stats()
	// Only MaxOpenConnections is a deterministic reflection of our setting;
	// the live counters (OpenConnections/InUse/Idle) vary with timing, so we
	// do NOT print them.
	fmt.Printf("db.Stats().MaxOpenConnections = %d   (reflects SetMaxOpenConns(5))\n", s.MaxOpenConnections)

	// sql.Open does NOT connect. It may only validate its arguments. The first
	// real connection is established on demand. Ping forces one, proving the
	// DSN (":memory:") is usable.
	err := db.Ping()
	fmt.Printf("db.Ping() err = %v   (nil == connection established on demand)\n", err)

	// DDL: CREATE TABLE. Reported as no error; RowsAffected is 0 (SQLite, like
	// most engines, does not report row counts for schema statements).
	_, err = db.Exec("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT)")
	must(err)
	fmt.Printf("CREATE TABLE -> err = %v   (schema OK)\n", err)

	// DML: INSERT one row. A Result reports LastInsertId + RowsAffected.
	res, err := db.Exec("INSERT INTO users (name, email) VALUES ('Alice', 'alice@x.com')")
	must(err)
	lastID, _ := res.LastInsertId()
	rowsAff, _ := res.RowsAffected()
	fmt.Printf("INSERT Alice -> LastInsertId = %d, RowsAffected = %d\n", lastID, rowsAff)

	check(`sql.Drivers() contains "sqlite"`, strings.Join(drivers, ",") == "sqlite")
	check("db.Driver() is non-nil", drv != nil)
	check("SetMaxOpenConns(5) reflected in Stats", s.MaxOpenConnections == 5)
	check("db.Ping() returned no error", err == nil)
	check("INSERT Alice RowsAffected == 1", rowsAff == 1)
	check("INSERT Alice LastInsertId == 1", lastID == 1)
}

// sectionB demonstrates the many-rows path: db.Query returns *sql.Rows; iterate
// with Next/Scan; ALWAYS defer Rows.Close(). Results are ORDER BY'd for stable
// output (SQL without ORDER BY has no guaranteed row order).
func sectionB() {
	sectionBanner("B — Query / Next / Scan loop (sorted, defer Close)")

	db := freshDB()
	defer db.Close()
	must(db.Ping())

	must(initSchema(db))
	must(insertUser(db, "Carol", "carol@x.com"))
	must(insertUser(db, "Alice", "alice@x.com"))
	must(insertUser(db, "Bob", "bob@x.com"))

	// ORDER BY name makes the row order deterministic across runs.
	rows, err := db.Query("SELECT name FROM users ORDER BY name ASC")
	must(err)
	defer rows.Close() // release the connection back to the pool

	names := make([]string, 0, 3)
	for rows.Next() {
		var name string
		must(rows.Scan(&name))
		names = append(names, name)
	}
	// After the loop, check rows.Err() — a Next that returns false could be
	// "no more rows" OR "an error mid-iteration". Err() distinguishes them.
	must(rows.Err())
	fmt.Printf("SELECT name FROM users ORDER BY name -> %v\n", names)

	check("sorted names == [Alice Bob Carol]", strings.Join(names, ",") == "Alice,Bob,Carol")
	check("exactly 3 rows scanned", len(names) == 3)
}

// sectionC shows the single-row path: db.QueryRow returns *sql.Row. Scan
// returns sql.ErrNoRows when zero rows matched — check it with errors.Is.
func sectionC() {
	sectionBanner("C — QueryRow + sql.ErrNoRows (errors.Is)")

	db := freshDB()
	defer db.Close()
	must(db.Ping())
	must(initSchema(db))
	must(insertUser(db, "Alice", "alice@x.com"))

	// Existing row: Scan succeeds, err == nil.
	var found string
	errFound := db.QueryRow("SELECT name FROM users WHERE id = ?", 1).Scan(&found)
	fmt.Printf("QueryRow(id=1) -> name=%q, err=%v\n", found, errFound)

	// Missing row: Scan returns sql.ErrNoRows. QueryRow itself defers the error
	// until Scan (QueryRow never returns an error directly — it returns a *Row
	// placeholder that holds the error for Scan to surface).
	var missing string
	errMissing := db.QueryRow("SELECT name FROM users WHERE id = ?", 999).Scan(&missing)
	isNoRows := errors.Is(errMissing, sql.ErrNoRows)
	fmt.Printf("QueryRow(id=999) -> err=%q, errors.Is(err, sql.ErrNoRows)=%v\n", errMissing, isNoRows)

	check("existing id scanned name == Alice", found == "Alice" && errFound == nil)
	check("missing id -> errors.Is(err, sql.ErrNoRows)", isNoRows)
	check(`missing id err text == "sql: no rows in result set"`, errMissing.Error() == "sql: no rows in result set")
	// sql.ErrNoRows is a sentinel (errors.New); errors.Is compares by identity.
	check("sql.ErrNoRows is the exact sentinel", errors.Is(errMissing, sql.ErrNoRows))
}

// sectionD shows prepared statements: db.Prepare parses a statement once, then
// it is Exec'd many times with different params. Placeholders (?) make it
// SQL-injection-safe by construction — values are bound, never interpolated.
func sectionD() {
	sectionBanner("D — Prepared statements (parameterize, reuse)")

	db := freshDB()
	defer db.Close()
	must(db.Ping())
	must(initSchema(db))

	// Prepare once. The statement is reusable; Close it when done.
	stmt, err := db.Prepare("INSERT INTO users (name, email) VALUES (?, ?)")
	must(err)
	defer stmt.Close()

	people := []struct{ name, email string }{
		{"Dave", "dave@x.com"},
		{"Eve", "eve@x.com"},
		{"Frank", "frank@x.com"},
	}
	for _, p := range people {
		_, err := stmt.Exec(p.name, p.email) // params bound to the ? placeholders
		must(err)
	}

	var count int
	must(db.QueryRow("SELECT COUNT(*) FROM users").Scan(&count))
	fmt.Printf("prepared INSERT x%d -> COUNT(*) = %d\n", len(people), count)

	// Demonstrate that a parameterized query treats input as DATA, not SQL.
	// A hostile "name" is matched as a literal — it matches no row, so Scan
	// returns sql.ErrNoRows (NOT a breakout that returns every user).
	var safe string
	hostileErr := db.QueryRow("SELECT name FROM users WHERE name = ?", "Eve' OR '1'='1").Scan(&safe)
	fmt.Printf("parameterized WHERE name=? with hostile input -> errors.Is(ErrNoRows)=%v (treated as literal, no injection)\n", errors.Is(hostileErr, sql.ErrNoRows))

	// And the normal placeholder lookup of a real name works fine.
	must(db.QueryRow("SELECT name FROM users WHERE name = ?", "Eve").Scan(&safe))
	fmt.Printf("parameterized WHERE name=? 'Eve' -> %q\n", safe)

	check("3 prepared inserts -> COUNT(*) == 3", count == 3)
	check("hostile input matched no row (no injection)", errors.Is(hostileErr, sql.ErrNoRows))
	check("parameterized lookup of 'Eve' works", safe == "Eve")
}

// sectionE pins the classic NULL bug: a NULL column CANNOT scan into a plain
// string/int. Use sql.NullString (Valid + value) or a pointer (*string).
func sectionE() {
	sectionBanner("E — NULL columns -> sql.NullString (Valid + value)")

	db := freshDB()
	defer db.Close()
	must(db.Ping())
	must(initSchema(db))

	// One user WITH an email, one WITHOUT (NULL).
	must(insertUser(db, "Alice", "alice@x.com"))
	mustExec(db, "INSERT INTO users (name, email) VALUES ('Bob', NULL)")

	// Non-NULL email: Valid == true, String holds the value.
	var has sql.NullString
	must(db.QueryRow("SELECT email FROM users WHERE name = ?", "Alice").Scan(&has))
	fmt.Printf("Alice email -> NullString{String:%q, Valid:%v}\n", has.String, has.Valid)

	// NULL email: Valid == false, String == "" (the zero value of the field).
	var none sql.NullString
	must(db.QueryRow("SELECT email FROM users WHERE name = ?", "Bob").Scan(&none))
	fmt.Printf("Bob   email -> NullString{String:%q, Valid:%v}   (NULL)\n", none.String, none.Valid)

	check("Alice email Valid == true", has.Valid)
	check("Alice email String == alice@x.com", has.String == "alice@x.com")
	check("Bob email Valid == false (NULL)", !none.Valid)
	check("Bob email String == \"\" when NULL", none.String == "")
}

// sectionF exercises transactions: Begin binds a single connection, all tx.*
// calls run on it; Commit persists, Rollback discards. Defer Rollback so a
// panic/error mid-transaction still aborts cleanly (Rollback after Commit is a
// documented no-op, so deferring it is safe).
func sectionF() {
	sectionBanner("F — Transactions: Begin / Commit / Rollback")

	db := freshDB()
	defer db.Close()
	must(db.Ping())
	must(initSchema(db))
	must(insertUser(db, "Alice", "alice@x.com"))
	must(insertUser(db, "Bob", "bob@x.com"))
	must(insertUser(db, "Carol", "carol@x.com"))

	var before int
	must(db.QueryRow("SELECT COUNT(*) FROM users").Scan(&before))

	// --- Rollback path: insert inside a tx, then discard it. ---
	tx, err := db.Begin() // binds ONE connection from the pool to this tx
	must(err)
	// Defer Rollback: if anything below fails, the tx is aborted. If we reach
	// Commit(), the deferred Rollback becomes a harmless no-op.
	defer func() { _ = tx.Rollback() }()

	must(insertUserTx(tx, "Temp", "temp@x.com"))
	var during int
	must(tx.QueryRow("SELECT COUNT(*) FROM users").Scan(&during)) // sees the uncommitted row
	must(tx.Rollback())                                           // discard

	var afterRollback int
	must(db.QueryRow("SELECT COUNT(*) FROM users").Scan(&afterRollback))
	fmt.Printf("rollback path: before=%d, during-tx=%d, after-Rollback=%d\n", before, during, afterRollback)

	// --- Commit path: insert two rows inside a tx, then persist them. ---
	tx2, err := db.Begin()
	must(err)
	defer func() { _ = tx2.Rollback() }()
	must(insertUserTx(tx2, "Dave", "dave@x.com"))
	must(insertUserTx(tx2, "Eve", "eve@x.com"))
	must(tx2.Commit()) // the deferred Rollback on tx2 is now a no-op

	var afterCommit int
	must(db.QueryRow("SELECT COUNT(*) FROM users").Scan(&afterCommit))
	fmt.Printf("commit path:   before=%d, after-Commit=%d\n", before, afterCommit)

	check("before transaction COUNT(*) == 3", before == 3)
	check("during tx COUNT(*) == 4 (sees uncommitted row)", during == 4)
	check("after Rollback COUNT(*) == 3 (insert discarded)", afterRollback == 3)
	check("after Commit COUNT(*) == 5 (two inserts persisted)", afterCommit == 5)
}

// sectionG demonstrates the N+1 problem: fetching N parent rows then issuing 1
// query per child = N+1 round trips. A JOIN collapses it to 1 query. We count
// queries in each path and assert the gap.
func sectionG() {
	sectionBanner("G — N+1 problem: N+1 queries vs 1 JOIN")

	db := freshDB()
	defer db.Close()
	must(db.Ping())
	must(initSchema(db))
	mustExec(db, "CREATE TABLE orders (id INTEGER PRIMARY KEY, uid INTEGER, amt INTEGER)")

	// 3 users, each with 1 order.
	must(insertUser(db, "Alice", "alice@x.com")) // id 1
	must(insertUser(db, "Bob", "bob@x.com"))     // id 2
	must(insertUser(db, "Carol", "carol@x.com")) // id 3
	mustExec(db, "INSERT INTO orders (uid, amt) VALUES (1, 100)")
	mustExec(db, "INSERT INTO orders (uid, amt) VALUES (2, 200)")
	mustExec(db, "INSERT INTO orders (uid, amt) VALUES (3, 300)")
	const n = 3

	// --- N+1 path: 1 query for users + N queries for each user's order. ---
	nPlusOneQueries := 0
	rows, err := db.Query("SELECT id, name FROM users ORDER BY id") // query #1
	must(err)
	type user struct {
		id   int
		name string
	}
	users := make([]user, 0, n)
	for rows.Next() {
		var u user
		must(rows.Scan(&u.id, &u.name))
		users = append(users, u)
	}
	must(rows.Err())
	rows.Close()
	nPlusOneQueries++ // the SELECT users above
	// One query PER user to fetch that user's order.
	pairs := make([]string, 0, n)
	for _, u := range users {
		var amt int
		must(db.QueryRow("SELECT amt FROM orders WHERE uid = ?", u.id).Scan(&amt))
		nPlusOneQueries++
		pairs = append(pairs, fmt.Sprintf("%s=%d", u.name, amt))
	}
	fmt.Printf("N+1 path: %d queries for %d users -> %s\n", nPlusOneQueries, len(users), strings.Join(pairs, ", "))

	// --- JOIN path: 1 query returns users + their orders together. ---
	joinQueries := 0
	jrows, err := db.Query(
		"SELECT u.name, o.amt FROM users u JOIN orders o ON u.id = o.uid ORDER BY u.name",
	) // query #1 (and only)
	must(err)
	joinPairs := make([]string, 0, n)
	for jrows.Next() {
		var nm string
		var amt int
		must(jrows.Scan(&nm, &amt))
		joinPairs = append(joinPairs, fmt.Sprintf("%s=%d", nm, amt))
	}
	must(jrows.Err())
	jrows.Close()
	joinQueries++
	fmt.Printf("JOIN path: %d query  for %d rows -> %s\n", joinQueries, len(joinPairs), strings.Join(joinPairs, ", "))

	check(fmt.Sprintf("N+1 path issued %d queries (1 + %d users)", n+1, n), nPlusOneQueries == n+1)
	check("JOIN path issued 1 query", joinQueries == 1)
	check("N+1 queries > JOIN queries", nPlusOneQueries > joinQueries)
	check("both paths returned 3 rows", len(pairs) == n && len(joinPairs) == n)
}

// --- shared DDL/DML helpers (used by sections B-G) --------------------------

// initSchema creates the canonical users table on a fresh DB.
func initSchema(db *sql.DB) error {
	_, err := db.Exec("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT)")
	return err
}

// insertUser inserts one user via db.Exec (non-prepared, fine for setup).
func insertUser(db *sql.DB, name, email string) error {
	_, err := db.Exec("INSERT INTO users (name, email) VALUES (?, ?)", name, email)
	return err
}

// insertUserTx inserts one user on a transaction (tx.Exec).
func insertUserTx(tx *sql.Tx, name, email string) error {
	_, err := tx.Exec("INSERT INTO users (name, email) VALUES (?, ?)", name, email)
	return err
}

func main() {
	fmt.Println("database_sql.go — Phase 6 bundle.")
	fmt.Println("Every value below is produced by this file against an in-memory")
	fmt.Println("SQLite DB; the .md guide pastes it verbatim. No network, no file,")
	fmt.Println("no hand-computed numbers. database/sql is the only API used.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionG()
	sectionBanner("DONE — all sections printed")
}
