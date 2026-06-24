//go:build ignore

// sqlx_gorm.go — Phase 6 bundle (the ORM CONTRAST: sqlx vs gorm).
//
// GOAL (one line): show, by running the SAME operations through both a thin
// SQL wrapper (sqlx) and a full ORM (gorm) against in-memory sqlite, what each
// gives you, what each hides, and where each surprises you.
//
// This is the GROUND TRUTH for SQLX_GORM.md. Every row count, name, and error
// below is produced by this file; the .md guide pastes it verbatim. Nothing is
// hand-computed. Determinism is total: every query is seeded with fixed rows
// and every multi-row read is ORDER BY'd; there are no timestamp fields (the
// default gorm.Model would inject non-deterministic CreatedAt/UpdatedAt times).
//
// Run:
//
//	go run sqlx_gorm.go

package main

import (
	"errors"
	"fmt"
	"sort"
	"strings"

	"github.com/glebarez/sqlite"
	"github.com/jmoiron/sqlx"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

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

// --- shared model types ------------------------------------------------------

// SqlxProduct is scanned by sqlx using `db:"column"` tags. sqlx does NOT
// understand gorm tags — its MapperFunc (strings.ToLower by default) maps column
// names to struct fields, and the `db:` tag overrides that mapping. You still
// write every SQL statement yourself.
type SqlxProduct struct {
	ID    int    `db:"id"`
	Code  string `db:"code"`
	Name  string `db:"name"`
	Price int    `db:"price"`
}

// GormProduct is mapped by gorm using `gorm:"..."` tags. gorm infers column
// names (snake_case) and the primary key (field ID) by convention, so many of
// these tags are explicit-for-teaching rather than required. Two tags earn
// their keep: `autoIncrement` and `gorm:"-"` (skip the field entirely — it is
// never created in the schema and never scanned back). There are deliberately
// NO timestamp fields: embedding gorm.Model would auto-fill CreatedAt/UpdatedAt
// with wall-clock times and break byte-identical output across runs.
type GormProduct struct {
	ID    uint   `gorm:"column:id;primaryKey;autoIncrement"`
	Code  string `gorm:"column:code;size:16;not null"`
	Name  string `gorm:"column:name;size:64"`
	Price int    `gorm:"column:price"`
	Note  string `gorm:"-"` // ignored: not a column, not scanned
}

// GormUser has-many GormItem. gorm infers the foreign key column from the owner
// struct's name ("GormUserID" -> snake_case "gorm_user_id"); the explicit
// `foreignKey` tag pins it for clarity. Items is an ASSOCIATION — it is NOT a
// real column; gorm loads it only when you ask (Preload).
type GormUser struct {
	ID    uint `gorm:"primaryKey"`
	Name  string
	Items []GormItem `gorm:"foreignKey:GormUserID"`
}

// GormItem is the "many" side. GormUserID is the foreign key back to GormUser.
type GormItem struct {
	ID         uint `gorm:"primaryKey"`
	Name       string
	GormUserID uint // foreign key column (gorm_user_id)
}

// mustGorm opens a FRESH in-memory sqlite database via the pure-Go glebarez/sqlite
// dialector. Each call is an independent :memory: database, so every section
// starts from a clean slate. The logger is set to Silent so gorm never writes a
// (timestamped, non-deterministic) line to stderr — keeping `just out` output
// byte-stable. Panics on error so a wiring failure fails the sweep loudly.
func mustGorm() *gorm.DB {
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		panic(err)
	}
	return db
}

// namesOfSqlx / namesOfGorm flatten a product slice to "[a b c]" for terse,
// deterministic comparison. The caller has already ORDER BY'd the rows, so the
// printed bracketed list is stable.
func namesOfSqlx(ps []SqlxProduct) string {
	ns := make([]string, 0, len(ps))
	for _, p := range ps {
		ns = append(ns, p.Name)
	}
	return fmt.Sprint(ns)
}

func namesOfGorm(ps []GormProduct) string {
	ns := make([]string, 0, len(ps))
	for _, p := range ps {
		ns = append(ns, p.Name)
	}
	return fmt.Sprint(ns)
}

// --- sections ----------------------------------------------------------------

// sectionA — sqlx basics: connect :memory:, write the DDL by hand, insert fixed
// rows, then Select many rows into a []Struct. You own every SQL string.
func sectionA() {
	sectionBanner("A — sqlx: thin wrapper, manual SQL, struct scan")

	// sqlx.Connect wraps database/sql and pings. glebarez/sqlite registers the
	// "sqlite" driver name on import, so sqlx can open it like any sql driver.
	db := sqlx.MustConnect("sqlite", ":memory:")

	// You write the schema AND the inserts yourself — sqlx adds nothing here.
	db.MustExec(`CREATE TABLE products (
		id    INTEGER PRIMARY KEY,
		code  TEXT NOT NULL,
		name  TEXT NOT NULL,
		price INTEGER NOT NULL
	)`)
	db.MustExec(`INSERT INTO products (id, code, name, price) VALUES (1, 'A1', 'Alpha', 5)`)
	db.MustExec(`INSERT INTO products (id, code, name, price) VALUES (2, 'B2', 'Beta', 15)`)
	db.MustExec(`INSERT INTO products (id, code, name, price) VALUES (3, 'C3', 'Gamma', 25)`)

	// Select runs the query and StructScans every row into the slice via the
	// `db:` tags. This is the boilerplate sqlx removes: no rows.Next loop, no
	// per-field Scan. ORDER BY makes the output byte-stable.
	var products []SqlxProduct
	if err := db.Select(&products, `SELECT id, code, name, price FROM products ORDER BY name`); err != nil {
		panic(err)
	}
	fmt.Println("sqlx.Select(&[]SqlxProduct, \"... ORDER BY name\"):")
	for _, p := range products {
		fmt.Printf("  id=%-2d code=%-3s name=%-6s price=%d\n", p.ID, p.Code, p.Name, p.Price)
	}

	check("sqlx.Select returns 3 rows", len(products) == 3)
	check("sqlx.Select sorted names == [Alpha Beta Gamma]", namesOfSqlx(products) == "[Alpha Beta Gamma]")
	check("sqlx struct scan mapped the db: tags (id=1->Alpha)", products[0].ID == 1 && products[0].Name == "Alpha")
}

// sectionB — sqlx.Get (one row into a struct) + sqlx.NamedExec (bind struct
// fields to :name placeholders, no positional ? juggling).
func sectionB() {
	sectionBanner("B — sqlx.Get (one row) + sqlx.NamedExec (:name params)")

	db := sqlx.MustConnect("sqlite", ":memory:")
	db.MustExec(`CREATE TABLE products (id INTEGER PRIMARY KEY, code TEXT, name TEXT, price INTEGER)`)
	db.MustExec(`INSERT INTO products (id, code, name, price) VALUES (1, 'A1', 'Alpha', 5)`)
	db.MustExec(`INSERT INTO products (id, code, name, price) VALUES (2, 'B2', 'Beta', 15)`)

	// Get = QueryRow + StructScan for exactly one row. An empty result set is
	// returned as sql.ErrNoRows (documented in the .md).
	var one SqlxProduct
	if err := db.Get(&one, `SELECT id, code, name, price FROM products WHERE id = ?`, 1); err != nil {
		panic(err)
	}
	fmt.Printf("sqlx.Get(id=1) -> id=%d code=%s name=%s price=%d\n", one.ID, one.Code, one.Name, one.Price)

	// NamedExec binds the struct's FIELDS to :field placeholders by name —
	// order-independent, self-documenting, and refactor-safe (rename the column
	// once, in the query).
	delta := SqlxProduct{Code: "D4", Name: "Delta", Price: 35}
	res, err := db.NamedExec(
		`INSERT INTO products (code, name, price) VALUES (:code, :name, :price)`,
		delta,
	)
	if err != nil {
		panic(err)
	}
	rows, _ := res.RowsAffected()
	fmt.Printf("sqlx.NamedExec(\"...VALUES (:code,:name,:price)\", SqlxProduct{...}) -> RowsAffected=%d\n", rows)

	var all []SqlxProduct
	if err := db.Select(&all, `SELECT id, name, price FROM products ORDER BY name`); err != nil {
		panic(err)
	}
	fmt.Println("after NamedExec, products (ORDER BY name):")
	for _, p := range all {
		fmt.Printf("  id=%-2d name=%-6s price=%d\n", p.ID, p.Name, p.Price)
	}

	check("sqlx.Get(id=1) returns Alpha", one.Name == "Alpha" && one.ID == 1)
	check("sqlx.NamedExec affected 1 row", rows == 1)
	check("sqlx now holds 3 rows", len(all) == 3)
	check("sqlx NamedExec inserted Delta (sorted last)", all[len(all)-1].Name == "Delta")
}

// sectionC — gorm.AutoMigrate builds the table from struct tags (no hand-written
// DDL); gorm.Create inserts rows (no hand-written INSERT). Note the gorm:"-"
// field is silently skipped in both directions.
func sectionC() {
	sectionBanner("C — gorm: AutoMigrate builds the table, Create inserts")

	db := mustGorm()

	// AutoMigrate derives the DDL from the struct: primary key, autoIncrement,
	// column sizes, NOT NULL — all from the tags. No CREATE TABLE string here.
	if err := db.AutoMigrate(&GormProduct{}); err != nil {
		panic(err)
	}
	fmt.Println("gorm.AutoMigrate(&GormProduct{}) -> table built from struct tags")
	fmt.Println("  tags: column:id primaryKey autoIncrement | code not null size:16 | Note gorm:\"-\" (skipped)")

	// Create: gorm writes the INSERT. The gorm:"-" Note is dropped on write; the
	// autoIncrement ID is back-filled into the struct after insert.
	db.Create(&GormProduct{Code: "A1", Name: "Alpha", Price: 5, Note: "hidden-1"})
	db.Create(&GormProduct{Code: "B2", Name: "Beta", Price: 15, Note: "hidden-2"})

	var products []GormProduct
	db.Order("name").Find(&products) // Find is a "finisher": it executes the query.
	fmt.Println("gorm.Find (Order name):")
	for _, p := range products {
		fmt.Printf("  id=%-2d code=%-3s name=%-6s price=%d  note=%q  (gorm:\"-\" -> empty on read)\n", p.ID, p.Code, p.Name, p.Price, p.Note)
	}

	check("gorm AutoMigrate+Create(2) -> Find returns 2 rows", len(products) == 2)
	check("gorm autoIncrement assigned IDs 1 and 2", products[0].ID == 1 && products[1].ID == 2)
	check("gorm gorm:\"-\" field never scanned back (note empty)", products[0].Note == "")
}

// sectionD — gorm.Where CHAINS build a query; nothing runs until a finisher
// (First/Find/...) is called. The contrast with sqlx: here we never type SQL.
func sectionD() {
	sectionBanner("D — gorm.Where chains build SQL; Find executes")

	db := mustGorm()
	db.AutoMigrate(&GormProduct{})
	db.Create(&GormProduct{Code: "A1", Name: "Alpha", Price: 5})
	db.Create(&GormProduct{Code: "B2", Name: "Beta", Price: 15})
	db.Create(&GormProduct{Code: "C3", Name: "Gamma", Price: 25})

	// Where + Order are CHAINABLE: they accumulate conditions; Find runs it.
	// The "?" is parameterized by gorm — same SQL-injection safety as sqlx.
	var pricey []GormProduct
	db.Where("price > ?", 10).Order("name").Find(&pricey)
	fmt.Println("gorm.Where(\"price > ?\", 10).Find (Order name):")
	for _, p := range pricey {
		fmt.Printf("  id=%-2d name=%-6s price=%d\n", p.ID, p.Name, p.Price)
	}

	check("gorm.Where price>10 returns 2 rows", len(pricey) == 2)
	check("gorm.Where filtered set sorted == [Beta Gamma]", namesOfGorm(pricey) == "[Beta Gamma]")
	check("gorm.Where excluded Alpha (price 5)", namesOfGorm(pricey) != "[Alpha Beta Gamma]")
}

// sectionE — gorm.Updates (update a field) and gorm.Delete; after delete, First
// returns the sentinel gorm.ErrRecordNotFound, reached via errors.Is (because
// gorm wraps its errors; == would miss a wrapped instance).
func sectionE() {
	sectionBanner("E — gorm.Updates + gorm.Delete -> ErrRecordNotFound")

	db := mustGorm()
	db.AutoMigrate(&GormProduct{})
	db.Create(&GormProduct{Code: "A1", Name: "Alpha", Price: 5})
	db.Create(&GormProduct{Code: "B2", Name: "Beta", Price: 15})

	// Update one column on rows matching a condition.
	db.Model(&GormProduct{}).Where("id = ?", 1).Update("price", 50)
	var got GormProduct
	db.First(&got, 1) // First(dest, id) is sugar for WHERE primary key = id.
	fmt.Printf("gorm.Update \"price\"=50 (id=1) -> id=%d name=%s price=%d\n", got.ID, got.Name, got.Price)
	check("gorm.Update set price to 50", got.Price == 50)

	// Delete by condition. The &GormProduct{} tells gorm WHICH table.
	db.Where("id = ?", 1).Delete(&GormProduct{})

	var afterDelete GormProduct
	err := db.First(&afterDelete, 1).Error
	fmt.Printf("gorm.Delete(id=1) then First(id=1) -> error = %v\n", err)
	check("gorm.Delete -> First returns ErrRecordNotFound (errors.Is)", errors.Is(err, gorm.ErrRecordNotFound))

	// The surviving row is still queryable.
	var rest []GormProduct
	db.Order("name").Find(&rest)
	fmt.Printf("gorm after delete, Find returns %d row(s): %s\n", len(rest), namesOfGorm(rest))
	check("gorm Delete left exactly 1 row (Beta)", len(rest) == 1 && rest[0].Name == "Beta")
}

// sectionF — the CONTRAST payoff. (1) The SAME insert+query task in sqlx (you
// write the SQL) vs gorm (you write none) returns identical data. (2) gorm
// associations are NOT transparently lazy-loaded: without Preload the slice is
// silently empty; Preload eager-loads it in one extra query (the N+1 fix).
func sectionF() {
	sectionBanner("F — the tradeoff: same task, sqlx (raw SQL) vs gorm (no SQL) + associations")

	// --- sqlx side: you own schema, inserts, and query ---------------------
	sdb := sqlx.MustConnect("sqlite", ":memory:")
	sdb.MustExec(`CREATE TABLE products (id INTEGER PRIMARY KEY, code TEXT, name TEXT, price INTEGER)`)
	sdb.MustExec(`INSERT INTO products (id, code, name, price) VALUES (1, 'A1', 'Alpha', 5)`)
	sdb.MustExec(`INSERT INTO products (id, code, name, price) VALUES (2, 'B2', 'Beta', 15)`)
	var sRows []SqlxProduct
	_ = sdb.Select(&sRows, `SELECT id, name FROM products ORDER BY name`)

	// --- gorm side: schema + inserts + query are method calls --------------
	gdb := mustGorm()
	gdb.AutoMigrate(&GormProduct{})
	gdb.Create(&GormProduct{Code: "A1", Name: "Alpha", Price: 5})
	gdb.Create(&GormProduct{Code: "B2", Name: "Beta", Price: 15})
	var gRows []GormProduct
	gdb.Order("name").Find(&gRows)

	fmt.Println("same insert+query, two tools (data is identical):")
	fmt.Printf("  sqlx  -> %s   (you wrote CREATE TABLE + INSERT + SELECT)\n", namesOfSqlx(sRows))
	fmt.Printf("  gorm  -> %s   (you wrote AutoMigrate + Create + Find; zero SQL)\n", namesOfGorm(gRows))
	check("sqlx and gorm return the same sorted names", namesOfSqlx(sRows) == namesOfGorm(gRows))

	// --- associations: the N+1 territory -----------------------------------
	gdb.AutoMigrate(&GormUser{}, &GormItem{})
	gdb.Create(&GormUser{Name: "U1"})
	gdb.Create(&GormUser{Name: "U2"})
	gdb.Create(&GormItem{Name: "I1", GormUserID: 1})
	gdb.Create(&GormItem{Name: "I2", GormUserID: 1})
	gdb.Create(&GormItem{Name: "I3", GormUserID: 2})

	// WITHOUT Preload: gorm does NOT lazy-load. Accessing .Items yields the zero
	// value (empty slice) — no query fires, no error. This silent-empty is a
	// footgun distinct from Rails-style transparent lazy loading.
	var usersNoPreload []GormUser
	gdb.Order("name").Find(&usersNoPreload)
	fmt.Println("associations WITHOUT Preload (gorm does NOT lazy-load):")
	for _, u := range usersNoPreload {
		fmt.Printf("  %s: %d items  (silently empty)\n", u.Name, len(u.Items))
	}

	// WITH Preload: gorm fires ONE extra query (SELECT ... WHERE user_id IN
	// (...)) and fills Items — eager loading, the N+1 fix.
	var usersPreload []GormUser
	gdb.Preload("Items").Order("name").Find(&usersPreload)
	fmt.Println("associations WITH Preload(\"Items\") (eager: one extra query):")
	for _, u := range usersPreload {
		names := make([]string, 0, len(u.Items))
		for _, it := range u.Items {
			names = append(names, it.Name)
		}
		sort.Strings(names) // sort for deterministic output
		fmt.Printf("  %s: %d items -> %s\n", u.Name, len(u.Items), names)
	}

	noPreloadAllEmpty := true
	for _, u := range usersNoPreload {
		if len(u.Items) != 0 {
			noPreloadAllEmpty = false
		}
	}
	check("without Preload every association is silently empty", noPreloadAllEmpty)
	check("Preload eager-loaded U1's 2 items", len(usersPreload[0].Items) == 2)
	check("Preload eager-loaded U2's 1 item", len(usersPreload[1].Items) == 1)
}

func main() {
	fmt.Println("sqlx_gorm.go — Phase 6 bundle (the ORM contrast: sqlx vs gorm).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Both tools run against in-memory sqlite (:memory:).")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
