// database_drivers.ts — Phase 8 bundle (db/ member).
//
// GOAL (one line): show, by printing every value, the two layers of SQLite
// access in Node — the raw DRIVER (better-sqlite3: sync, native, prepared
// statements, transactions) and the ORM (drizzle-orm: schema-first, type-safe
// query builder, relational API) — pinning the SQL-injection payoff and the
// transaction all-or-nothing guarantee as check()'d invariants.
//
// This is the GROUND TRUTH for DATABASE_DRIVERS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): a database driver is the thinnest possible
// bridge between your program and the DB engine — you write SQL strings, it
// ships them and hands back rows. better-sqlite3 is a SYNCHRONOUS, native
// (C++) binding to SQLite: no event-loop hops, no Promises, just fast blocking
// calls (fine for SQLite, which is embedded and in-process). drizzle-orm sits
// ON TOP of that same connection: you declare a TS SCHEMA, and its query
// builder hands you TYPED rows while emitting plain SQL under the hood. The
// tradeoff is the whole story: raw = full control + max perf but ZERO type
// safety (rows are `unknown`); drizzle = type-safe + ergonomic SQL-like API
// but a schema + builder abstraction to learn. This is the JS analog of Go's
// sqlx (light mapper) vs gorm (heavy ORM) and Rust's sqlx (compile-time
// checked queries).
//
// DETERMINISM: the DB is a fresh IN-MEMORY database (":memory:") created per
// run — no file, no leftover state, fully reproducible. All values are fixed
// (no Math.random / Date.now). The connection is sqlite.close()'d before
// main() returns.
//
// Run:
//     pnpm exec tsx database_drivers.ts   (or: just run database_drivers)

import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import { sqliteTable, integer, text } from "drizzle-orm/sqlite-core";
import { eq, relations } from "drizzle-orm";

// better-sqlite3 ships `export = Database` (a CommonJS export assignment):
// `Database` is BOTH the constructor (a value) and a namespace of nested
// types. Used in TYPE position `Database` refers to the namespace, which is
// not itself a type — so we extract the INSTANCE type via InstanceType. (This
// is why the raw layer's rows are `unknown` and we hand-type RawUser: the
// driver has no schema to infer from.)
type SqliteDB = InstanceType<typeof Database>;

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// expectType: a COMPILE-TIME-ONLY probe (body is empty -> erased at runtime).
// tsc errors if the argument is NOT assignable to T. Pairing two calls in
// opposite directions (expectType<Expected>(actual) and expectType<Actual>
// (expectedValue)) proves the two types are IDENTICAL — this is how we prove
// drizzle's inferred row type is exactly { id: number; name: string }.
// (Leading underscore exempts the unused param from noUnusedParameters.)
function expectType<T>(_value: T): void {}

// rowsJson deterministically serializes a list of rows for printing: it SORTS
// by id first so output never depends on SQLite's unspecified row order.
function rowsJson<T extends { id: number }>(rows: T[]): string {
  const copy = [...rows].sort((x, y) => x.id - y.id);
  return JSON.stringify(copy);
}

// --- RAW layer: the exact shape of a row from the better-sqlite3 driver.
//    (The driver itself returns `unknown`; WE type it, because the raw layer
//    has no schema to infer from — that is precisely what the ORM fixes.)
interface RawUser {
  id: number;
  name: string;
}

// ============================================================================
// drizzle schema — a TS-side DESCRIPTION of the tables. NOTE: drizzle does NOT
// create these tables for you; they must already exist (here we create them
// with raw sqlite.exec in each section). The schema only drives type inference
// and SQL generation. Column-name args (integer("id"), text("email")) ARE the
// DB column names — pass them explicitly so they match the JS property keys.
// ============================================================================

const accounts = sqliteTable("accounts", {
  id: integer("id").primaryKey(),
  email: text("email").notNull(),
});

const authors = sqliteTable("authors", {
  id: integer("id").primaryKey(),
  name: text("name").notNull(),
});

const posts = sqliteTable("posts", {
  id: integer("id").primaryKey(),
  title: text("title").notNull(),
  authorId: integer("author_id").notNull(),
});

// Relations are declared separately and power the db.query relational API.
const authorsRelations = relations(authors, ({ many }) => ({
  posts: many(posts),
}));
const postsRelations = relations(posts, ({ one }) => ({
  author: one(authors, { fields: [posts.authorId], references: [authors.id] }),
}));

const schema = {
  accounts,
  authors,
  posts,
  authorsRelations,
  postsRelations,
};

// Inferred TS row type for the accounts table — drizzle DERIVES this from the
// schema. primaryKey() => not-null number; text().notNull() => string.
type Account = typeof accounts.$inferSelect;

// ============================================================================
// Section A — better-sqlite3 raw: :memory:, exec, prepare/run/all/get
// ============================================================================

function sectionA(sqlite: SqliteDB): void {
  sectionBanner("A — better-sqlite3 raw: :memory:, exec, prepare/run/all/get");

  // exec() runs raw SQL (multiple statements OK); use it for DDL/migrations.
  sqlite.exec("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)");

  // A PREPARED STATEMENT is compiled ONCE then executed many times with bound
  // parameters. The generic <[string]> is the bind-parameter tuple (type-safe:
  // you cannot forget a param); <RawUser> is the row shape for .get()/.all().
  const insByName = sqlite.prepare<[string]>("INSERT INTO users (name) VALUES (?)");
  const byName = sqlite.prepare<[string], RawUser>(
    "SELECT id, name FROM users WHERE name = ? ORDER BY id",
  );

  // .run() executes a writer and returns { changes, lastInsertRowid }.
  const info = insByName.run("a");
  console.log(`insert.run('a')  -> changes=${info.changes} lastInsertRowid=${info.lastInsertRowid}`);
  check("insert.run() reports exactly 1 change", info.changes === 1);

  // .get() returns the FIRST matching row (or undefined); .all() returns all.
  const one: RawUser | undefined = byName.get("a");
  const all: RawUser[] = byName.all("a");
  console.log(`select.get('a') -> ${JSON.stringify(one)}`);
  console.log(`select.all('a') -> ${rowsJson(all)}`);
  check("round-trip: inserted 'a' is selectable by name", one !== undefined && one.name === "a");
  check(".get() row id is 1 (first insert)", one !== undefined && one.id === 1);
  check(".all() returns the single matching row", all.length === 1 && all[0]?.name === "a");

  // The driver returns the JS value types SQLite maps: INTEGER->number, TEXT->string.
  check("INTEGER column maps to JS number", typeof one?.id === "number");
  check("TEXT column maps to JS string", typeof one?.name === "string");
}

// ============================================================================
// Section B — prepared statements (THE injection payoff) + transactions
// ============================================================================

function sectionB(sqlite: SqliteDB): void {
  sectionBanner("B — parameterized queries (injection payoff) + transactions");

  const insByName = sqlite.prepare<[string]>("INSERT INTO users (name) VALUES (?)");
  const byName = sqlite.prepare<[string], RawUser>(
    "SELECT id, name FROM users WHERE name = ? ORDER BY id",
  );

  // THE PAYOFF — SQL injection is prevented by PARAMETER BINDING, not by
  // escaping strings. With prepare("... WHERE name = ?").get(input) the driver
  // sends the SQL template and the input as SEPARATE values: SQLite parses the
  // template once (the ? is a placeholder, never SQL), then binds the input as
  // a literal. There is no string concatenation, so an attacker cannot turn
  // their input into SQL syntax.
  const payload = "x' OR '1'='1"; // classic injection payload

  // DANGEROUS — string INTERPOLATION. We execute it ONLY because this DB is an
  // isolated in-memory database with throwaway data; it demonstrates the hole.
  // The payload becomes live SQL: ... WHERE name = 'x' OR '1'='1'  (always true).
  const dangerousSql = `SELECT id, name FROM users WHERE name = '${payload}'`;
  const leaked = sqlite.prepare<[], RawUser>(dangerousSql).all();
  console.log(`DANGEROUS interpolated SQL: ${dangerousSql}`);
  console.log(`  -> returned ${leaked.length} row(s)  (injection SUCCEEDED: OR '1'='1' is always true)`);
  check("interpolated query leaks rows (injection succeeded)", leaked.length >= 1);

  // SAFE — the SAME payload, but bound as a parameter. SQLite looks for a user
  // LITERALLY named x' OR '1'='1 — there is none, so it returns no row.
  const safe: RawUser | undefined = byName.get(payload);
  console.log(`SAFE parameterized .get('${payload}') -> ${JSON.stringify(safe)}`);
  check("parameterized query returns no row for the payload (injection PREVENTED)", safe === undefined);

  // --- transactions: all-or-nothing ---------------------------------------
  // db.transaction(fn) RETURNS a function. Invoking it BEGINs a transaction;
  // normal return -> COMMIT; a thrown exception -> ROLLBACK (then re-throw).
  const txCommit = sqlite.transaction(() => {
    insByName.run("tx-commit");
    return 42; // returned value passes through
  });
  const ret = txCommit();
  console.log(`transaction (commit) returned ${ret}; row present? ${byName.get("tx-commit") !== undefined}`);
  check("transaction returns the wrapped function's value", ret === 42);
  check("transaction COMMITTED on normal return (row present)", byName.get("tx-commit") !== undefined);

  const txRollback = sqlite.transaction(() => {
    insByName.run("tx-rollback");
    throw new Error("boom"); // forces a rollback
  });
  let propagated = false;
  try {
    txRollback();
  } catch {
    propagated = true;
  }
  console.log(`transaction (throw) re-threw? ${propagated}; rolled-back row present? ${byName.get("tx-rollback") !== undefined}`);
  check("throwing transaction re-throws the error (propagates)", propagated);
  check("throwing transaction ROLLED BACK (row absent)", byName.get("tx-rollback") === undefined);
}

// ============================================================================
// Section C — drizzle-orm: schema + type-safe CRUD (inferred row types)
// ============================================================================

function sectionC(sqlite: SqliteDB, db: BetterSQLite3Database<typeof schema>): void {
  sectionBanner("C — drizzle-orm: schema + type-safe CRUD (inferred row types)");

  // The table must exist (drizzle does not auto-create it). This DDL mirrors
  // the schema declared above; in a real app drizzle-kit generates it.
  sqlite.exec("CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE)");

  // INSERT — values are type-checked against the inferred INSERT shape.
  // (primaryKey() implies a default, so id is OPTIONAL on insert.)
  db.insert(accounts)
    .values([
      { id: 1, email: "ann@example.com" },
      { id: 2, email: "bob@example.com" },
    ])
    .run();
  console.log("drizzle insert: 2 accounts (ann, bob)");

  // SELECT — returns TYPED rows (Account[]). No casts, no `any`.
  const accRows = db.select().from(accounts).orderBy(accounts.id).all();
  console.log(`drizzle select().from(accounts) -> ${rowsJson(accRows)}`);
  check("drizzle select returns 2 typed rows", accRows.length === 2);

  // COMPILE-TIME proof (erased at runtime) that the inferred type is exactly
  // { id: number; email: string }. Both directions must compile => identical.
  const first: Account = accRows[0]!;
  expectType<{ id: number; email: string }>(first); // Account -> {id,email}
  expectType<Account>({ id: 9, email: "z" }); // {id,email} -> Account

  // SELECT with a type-safe WHERE (eq is the = operator; the column is typed).
  const ann = db.select().from(accounts).where(eq(accounts.email, "ann@example.com")).all();
  console.log(`drizzle select.where(eq(email,'ann@example.com')) -> ${rowsJson(ann)}`);
  check("drizzle where(eq) finds ann by email", ann.length === 1 && ann[0]?.id === 1);

  // UPDATE ... RETURNING the updated rows (typed).
  const upd = db
    .update(accounts)
    .set({ email: "ann2@example.com" })
    .where(eq(accounts.id, 1))
    .returning()
    .all();
  console.log(`drizzle update.set(email).where(id=1).returning() -> ${rowsJson(upd)}`);
  check("drizzle update.returning() yields the updated row", upd.length === 1 && upd[0]?.email === "ann2@example.com");

  // DELETE ... RETURNING the deleted rows (typed).
  const del = db.delete(accounts).where(eq(accounts.id, 2)).returning().all();
  console.log(`drizzle delete.where(id=2).returning() -> ${rowsJson(del)}`);
  check("drizzle delete.returning() yields the deleted row", del.length === 1 && del[0]?.id === 2);

  const remaining = db.select().from(accounts).orderBy(accounts.id).all();
  console.log(`drizzle select (after delete) -> ${rowsJson(remaining)}`);
  check("exactly one account remains after delete", remaining.length === 1);
  check("remaining account is the updated ann2", remaining[0]?.email === "ann2@example.com");
}

// ============================================================================
// Section D — relations (db.query relational API) + the N+1 problem
// ============================================================================

function sectionD(sqlite: SqliteDB, db: BetterSQLite3Database<typeof schema>): void {
  sectionBanner("D — relations (db.query) + the N+1 problem (and the JOIN fix)");

  sqlite.exec("CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL)");
  sqlite.exec(
    "CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT NOT NULL, author_id INTEGER NOT NULL REFERENCES authors(id))",
  );

  db.insert(authors)
    .values([
      { id: 1, name: "Ann" },
      { id: 2, name: "Bob" },
    ])
    .run();
  db.insert(posts)
    .values([
      { id: 10, title: "P1", authorId: 1 },
      { id: 11, title: "P2", authorId: 1 },
      { id: 12, title: "P3", authorId: 2 },
    ])
    .run();
  console.log("seeded: authors {Ann(1), Bob(2)}; posts {P1,P2 -> Ann; P3 -> Bob}");

  // Relational query API: db.query.authors.findMany({ with: { posts: true } })
  // fetches authors AND their posts in ONE go (drizzle emits a single SQL with
  // joins/mapping). In sync mode the result is obtained via .sync().
  const withPosts = db.query.authors.findMany({ with: { posts: true } }).sync();
  // Sort for deterministic output (by author id, then posts by id).
  const deterministic = [...withPosts]
    .sort((a, b) => a.id - b.id)
    .map((a) => ({
      id: a.id,
      name: a.name,
      posts: [...a.posts].sort((x, y) => x.id - y.id).map((p) => ({ id: p.id, title: p.title })),
    }));
  console.log(`relational findMany({with:{posts:true}}) -> ${JSON.stringify(deterministic)}`);
  check("relational query returns 2 authors", withPosts.length === 2);
  check("Ann has 2 posts via relational API", deterministic[0]?.posts.length === 2);
  check("Bob has 1 post via relational API", deterministic[1]?.posts.length === 1);

  // --- THE N+1 PROBLEM -----------------------------------------------------
  // BAD: load the parents, then run ONE query PER parent for its children.
  // For N authors this is 1 (parents) + N (children) = N+1 round-trips.
  const authorList = db.select().from(authors).orderBy(authors.id).all();
  let nPlus1Queries = 1; // the authors query above
  for (const a of authorList) {
    db.select().from(posts).where(eq(posts.authorId, a.id)).all();
    nPlus1Queries++;
  }
  console.log(`N+1 (BAD): ${nPlus1Queries} queries for ${authorList.length} authors (1 + N)`);
  check("N+1 fires 1+N queries (1 parents + 2 children)", nPlus1Queries === 1 + authorList.length);

  // GOOD: a single JOIN fetches everything in ONE query (1 round-trip).
  let joinQueries = 0;
  const joined = db
    .select({ authorName: authors.name, title: posts.title })
    .from(authors)
    .leftJoin(posts, eq(authors.id, posts.authorId))
    .all();
  joinQueries++;
  const joinedSorted = [...joined].sort((x, y) =>
    x.authorName === y.authorName ? (x.title ?? "").localeCompare(y.title ?? "") : x.authorName.localeCompare(y.authorName),
  );
  console.log(`JOIN (GOOD): ${joinQueries} query -> ${JSON.stringify(joinedSorted)}`);
  check("single JOIN is 1 query (fixes N+1)", joinQueries === 1);
  check("JOIN returns 3 author/post pairs", joined.length === 3);
}

// ============================================================================
// Section E — migrations (drizzle-kit, documented) + raw vs drizzle vs Prisma
// ============================================================================

function sectionE(sqlite: SqliteDB): void {
  sectionBanner("E — migrations (drizzle-kit) + raw vs drizzle vs Prisma + cross-language");

  // drizzle-kit generates VERSIONED SQL migrations FROM your schema and applies
  // them. We DOCUMENT it here (we do not shell out — it writes files and needs
  // a drizzle.config.ts, out of scope for a single in-memory bundle):
  //   pnpm dlx drizzle-kit generate   -> emits SQL under ./drizzle/migrations
  //   pnpm dlx drizzle-kit migrate    -> applies pending migrations
  console.log("drizzle-kit generate  -> emits versioned SQL migrations from the TS schema");
  console.log("drizzle-kit migrate   -> applies pending migrations (idempotent)");

  // Choosing a DB-access layer (fixed decision matrix, deterministic):
  const matrix: ReadonlyArray<readonly [string, string, string]> = [
    ["raw better-sqlite3", "full control, max perf, zero deps-overhead", "no type safety; hand-written SQL"],
    ["drizzle-orm", "type-safe, SQL-like, lightweight (no engine)", "schema + builder to learn"],
    ["Prisma", "heavy ORM, migrations + codegen, great DX", "runtime query engine; heaviest abstraction"],
  ];
  console.log("\n  layer                 | pros                                   | cons");
  console.log("  ----------------------|----------------------------------------|----------------------------------------");
  for (const [name, pros, cons] of matrix) {
    console.log(`  ${name.padEnd(21)} | ${pros.padEnd(38)} | ${cons}`);
  }
  check("three DB-access layers compared", matrix.length === 3);

  // Connection pooling: SQLite is EMBEDDED (a file or :memory:) and accessed
  // via ONE in-process handle — there is nothing to pool. Pooling matters for
  // CLIENT/SERVER databases (Postgres, MySQL) where each connection is a TCP
  // session with a per-connection worker; there you use a pool (e.g. pg-pool,
  // mysql2 promise pool) to amortize connection setup.
  console.log(`\n  SQLite is embedded -> db.memory = ${sqlite.memory} (no connection pool needed)`);
  check("SQLite is embedded/in-memory (no pool)", sqlite.memory === true);

  // CROSS-LANGUAGE (the headline this bundle mirrors):
  //   Go:   sqlx (light mapper) vs gorm (heavy ORM)   -- the exact light/heavy split
  //   Rust: sqlx (COMPILE-TIME-checked queries via macros) -- strongest type safety
  console.log("  cross-language: Go sqlx(light)/gorm(heavy); Rust sqlx(compile-time-checked)");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("database_drivers.ts — Phase 8 bundle (db/ member).");
  console.log("Every value below is computed against a FRESH in-memory SQLite database;");
  console.log("the .md guide pastes it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Two layers: the raw DRIVER (better-sqlite3, sync, native) and the ORM");
  console.log("(drizzle-orm, schema-first, type-safe). Same connection; fresh :memory:.");

  // ONE fresh in-memory database per run -> fully deterministic. The drizzle
  // client wraps THIS SAME connection (it does not open a second one).
  const sqlite = new Database(":memory:");
  const db = drizzle(sqlite, { schema });

  sectionA(sqlite);
  sectionB(sqlite);
  sectionC(sqlite, db);
  sectionD(sqlite, db);
  sectionE(sqlite);

  sqlite.close(); // release the native handle before main() returns
  check("database closed before exit", sqlite.open === false);
  sectionBanner("DONE — all sections printed");
}

main();
