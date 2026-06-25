# Migrations: `drizzle-kit generate`/`migrate`

**Doc Source**: [Drizzle — Migrations fundamentals](https://orm.drizzle.team/docs/migrations) · [Drizzle Kit overview](https://orm.drizzle.team/docs/kit-overview) · [`drizzle-kit generate`](https://orm.drizzle.team/docs/drizzle-kit-generate) · [`drizzle-kit migrate`](https://orm.drizzle.team/docs/drizzle-kit-migrate)

## The Core Concept: Why This Example Exists

**The Problem:** SQL databases enforce a **strict schema** declared upfront. The moment you ship, the schema starts drifting — you add a column here, rename a field there, drop a table after a refactor. Without a discipline for evolving the schema, you get one of two failures: (a) every environment re-derives the schema by hand and they silently disagree, or (b) you `ALTER TABLE` directly on prod with no record of *what* changed, *when*, or *why*, so rollbacks are impossible and teammates can't reproduce your local DB.

**The Solution:** Drizzle treats the **TypeScript schema as the source of truth** and turns schema evolution into a *reviewable, version-controlled artifact*: plain `.sql` migration files. `drizzle-kit generate` diffs your current TS schema against the last known state and **emits a SQL migration file** (plus a `snapshot.json` so the next diff has a baseline); `drizzle-kit migrate` then reads those files, asks the database which ones it has already applied (via a `__drizzle_migrations__` history table), and applies only the missing ones. This is the same mental model as Rails' `db:migrate`, Alembic, or Flyway — but the *input* to the diff is a typed TS schema, not hand-written migration classes.

Drizzle's distinctive bet: **one schema definition, multiple deployment knobs.** The same `schema.ts` can be pushed directly (`drizzle-kit push`, for prototyping), generated into reviewable SQL files (`generate` + `migrate`, for production), or fed to an external tool like Atlas. You pick the workflow per environment without rewriting the schema. This mirrors how Rust's SQLx (🔗 [`../rust/sqlx/README.md`](../rust/sqlx/README.md)) uses a `migrations/` folder of timestamped `.sql` files and Go's `sqlx`+`golang-migrate` (🔗 [`../go/SQLX_GORM.md`](../go/SQLX_GORM.md)) does the same — but Drizzle *generates* the SQL from a typed schema rather than asking you to author it by hand.

> The schema that feeds `generate` is the very same `pgTable`/`sqliteTable` definition covered in the curriculum's 🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) (Section C — "drizzle-orm: schema + type-safe CRUD"). **The schema is the migration source**: you never write a migration that doesn't correspond to a typed table object.

## Practical Walkthrough: Code Breakdown

### The source of truth: `schema.ts`

Every migration begins from a typed Drizzle schema. This is the exact example the official migrations docs use as their running illustration:

```ts
// src/schema.ts
import * as p from "drizzle-orm/pg-core";

export const users = p.pgTable("users", {
  id: p.serial().primaryKey(),
  name: p.text(),
  email: p.text().unique(), // <--- added column
});
```

*Source: [orm.drizzle.team/docs/migrations](https://orm.drizzle.team/docs/migrations)*

The schema *is* the contract. When you later add `email`, the next `generate` sees the diff against the previous snapshot and produces an `ALTER TABLE` — you never type that `ALTER` by hand.

### `drizzle.config.ts` — telling the kit where to look

`drizzle-kit` reads a config file (or CLI params). At minimum it needs a SQL `dialect` and a `schema` path:

```ts
// drizzle.config.ts
import { defineConfig } from "drizzle-kit";

export default defineConfig({
  out: "./drizzle",
  dialect: "postgresql",
  schema: "./src/schema.ts",
});
```

*Source: [orm.drizzle.team/docs/kit-overview](https://orm.drizzle.team/docs/kit-overview)*

The `out` field is where generated migration folders land. An extended config adds `dbCredentials`, `tablesFilter`, `migrations: { prefix, table, schema }`, `strict`, `verbose`, and `breakpoints` — all documented on the overview page. You can pass multiple configs (`--config=drizzle-prod.config`) for multi-stage or multi-database projects.

### `drizzle-kit generate` — schema diff → SQL files

Running generate against the schema above produces this directory layout and SQL:

```
$ drizzle-kit generate
   📂 drizzle
   └ 📂 20242409125510_premium_mister_fear
     ├ 📜 snapshot.json
     └ 📜 migration.sql
```

```sql
-- drizzle/20242409125510_premium_mister_fear/migration.sql

CREATE TABLE "users" (
 "id" SERIAL PRIMARY KEY,
 "name" TEXT,
 "email" TEXT UNIQUE
);
```

*Source: [orm.drizzle.team/docs/migrations](https://orm.drizzle.team/docs/migrations) (Option 3)*

The generate flow does four things, as the docs enumerate:

1. **Read previous migration folders** (the `snapshot.json` of the latest one is the baseline).
2. **Find the diff** between the current TS schema and the previous snapshot.
3. **Prompt the developer for renames** when a column/table disappeared and a new one appeared (so Drizzle doesn't blindly `DROP` + `CREATE` and lose data).
4. **Generate SQL + persist** a new folder containing `migration.sql` and a fresh `snapshot.json`.

The `snapshot.json` is the *journal* — a serialized description of the schema at that migration point, so the next `generate` has a deterministic baseline to diff against. This is why migrations are **reviewable** (you read the `.sql` before it touches prod) and **reproducible** (anyone with the repo regenerates the same history).

### `drizzle-kit migrate` — apply against the database

```sh
$ drizzle-kit migrate
[✓] done!
```

The migrate flow, per the docs:

1. Read `migration.sql` files in the migrations folder.
2. **Fetch migration history from the database** (the `__drizzle_migrations__` table).
3. Pick previously-unapplied migrations.
4. Apply the new migrations to the database.

*Source: [orm.drizzle.team/docs/migrations](https://orm.drizzle.team/docs/migrations) (Option 3)*

Step 2 is the key: Drizzle records applied migrations *in the database itself*, so two developers or a CI pipeline and a prod box can't double-apply or skip a migration. This is identical to how `golang-migrate` and Flyway track a `schema_migrations` table.

### The runtime migrator — applying during deploy

For monoliths (zero-downtime deploy) or serverless (run migrations in a custom resource once during deploy), Drizzle ships a programmatic migrator:

```ts
// index.ts
import { drizzle } from "drizzle-orm/node-postgres"
import { migrate } from 'drizzle-orm/node-postgres/migrator';

const db = drizzle(process.env.DATABASE_URL);

await migrate(db);
```

*Source: [orm.drizzle.team/docs/migrations](https://orm.drizzle.team/docs/migrations) (Option 4)*

`await migrate(db)` does the same read-history → diff → apply dance as the CLI, but inside your process. This is what you call from a release script or a one-shot container on deploy.

### `generate`/`migrate` vs `push` — when to pick which

The docs are explicit that these are **two workflows for the same schema**, chosen per environment:

| Command | What it does | When to use it |
| --- | --- | --- |
| `drizzle-kit push` | Compute diff and apply **directly** to the DB, no files. | Rapid prototyping, local dev, fast iteration. The docs note many teams run this as their *primary* prod flow successfully. |
| `drizzle-kit generate` | Compute diff and write **reviewable `.sql` files**. | Anywhere you want an audit trail, code review, or rollback story. |
| `drizzle-kit migrate` | Apply previously-generated files. | The companion to `generate`: review the SQL, then apply. |
| `drizzle-kit pull` | Introspect the DB → write a TS schema. | "Database first" — the DB is the source of truth and you reflect it back to TS. |

`push` trades reviewability for speed; `generate`+`migrate` trades speed for safety. The payoff of `generate` is that **a schema change becomes a PR** — reviewers see the exact `ALTER TABLE`, you can `git revert` a migration file, and prod never sees a surprise DDL. SQLx's `migrations/` folder (🔗 [`../rust/sqlx/06-postgres-transactions.md`](../rust/sqlx/06-postgres-transactions.md) shows the same timestamped-`.sql`-on-disk discipline, just authored by hand) and Go's `golang-migrate` (🔗 [`../go/SQLX_GORM.md`](../go/SQLX_GORM.md)) sit at the same `generate`+`migrate` end of the spectrum but without Drizzle's schema-to-SQL synthesis.

## Mental Model: Thinking in Migrations

### Two sources of truth, one schema

```
Database-first                Codebase-first (Drizzle's default)
─────────────                 ─────────────────────────────────
DB is truth                   schema.ts is truth
   │                             │
   ▼                             ▼
drizzle-kit pull               drizzle-kit generate   →  .sql files (reviewed)
   │                             │                        │
   ▼                             ▼                        ▼
schema.ts (reflected)          drizzle-kit migrate    →   DB
                               (or drizzle-kit push   →   DB directly)
```

Drizzle supports both directions, but the typed-schema-first flow is the one that makes the 🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) Section C schema double as the migration source — no separate migration DSL to learn.

### The migration as a *commit*

```
schema.ts (state A)  ──generate──▶  0001_init/migration.sql  +  snapshot.json
       │                                                            │
   (edit: add email)                                                │
       ▼                                                            ▼
schema.ts (state B)  ──generate──▶  0002_add_email/migration.sql + snapshot.json
                                          (diffs A→B, knows email is new)
```

Each migration folder is a *commit*: a SQL patch plus the full schema state at that point (the snapshot). The snapshot is what makes the next diff deterministic — `generate` never re-reads your live database to know "where we were."

### Why `generate` exists at all (the reviewability payoff)

Without `generate`, every schema change is invisible — it hits the DB and disappears. With `generate`:

- **Code review:** the `ALTER TABLE` is a line in a PR. A reviewer catches the missing `NOT NULL` default before prod does.
- **Rollback:** `git revert` the migration file and re-run `migrate` (or write a `down` migration).
- **Reproducibility:** a new dev runs `migrate` and gets *exactly* your schema, in the same order, with the same history.
- **Audit:** `git log drizzle/` is a complete record of schema evolution.

`push` gives you none of this — it's atomic and unreviewable by design. That's the trade.

## Pitfalls

- **Don't hand-edit `migration.sql` after it's applied anywhere.** The `snapshot.json` won't reflect your edits, so the next `generate` diff will be wrong. If you need to change a migration, write a *new* one.
- **`generate` can't always infer renames.** When you rename a column, Drizzle sees "old column dropped, new column added" and *prompts* you to confirm it's a rename. If you run `generate` non-interactively (CI) and ignore the prompt, you may get a destructive `DROP` + `CREATE` that loses data.
- **`push` ≠ `generate`+`migrate` for teams.** `push` is stateless — it diffs against the live DB. In a team, two devs pushing conflicting schema changes can produce non-deterministic results. For shared codebases, prefer `generate` so the history is in git.
- **The `__drizzle_migrations__` table is authoritative.** If you delete a migration folder but the row is still in the history table, `migrate` won't re-apply it. Manual fiddling with either side desynchronizes them.
- **Column-ordering in `snapshot.json` matters for diffs.** Reordering columns in `schema.ts` without a real change can sometimes produce spurious diffs. Keep schema edits semantic.
- **Runtime `migrate(db)` needs the migrations folder at the resolved path** (default `./drizzle` relative to CWD). In bundled/serverless deploys, make sure the `.sql` files are included in the artifact — bundlers often strip them.

## Cross-references

- 🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) — Section C (schema as the typed migration source) and Section E (migrations end-to-end, including the raw-vs-drizzle-vs-Prisma comparison). The schema you `generate` from is defined here.
- 🔗 [`../rust/sqlx/06-postgres-transactions.md`](../rust/sqlx/06-postgres-transactions.md) — SQLx's `migrations/` folder of timestamped `.sql` files applied at startup. Same on-disk discipline, authored by hand rather than synthesized from a typed schema.
- 🔗 [`../go/SQLX_GORM.md`](../go/SQLX_GORM.md) — Go's `golang-migrate` + `sqlx`/GORM AutoMigrate. `golang-migrate` is the closest Go analog to `drizzle-kit generate`+`migrate`; GORM's `AutoMigrate` is closer to `drizzle-kit push` (convenience, less reviewable).
