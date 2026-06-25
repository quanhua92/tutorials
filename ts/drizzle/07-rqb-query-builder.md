# The Relational Query Builder (RQB): nested filters, `with` clauses

**Doc Source**: [Drizzle — Relational Queries](https://orm.drizzle.team/docs/rqb) · [Select (core query builder)](https://orm.drizzle.team/docs/select) · [`sql` operator](https://orm.drizzle.team/docs/sql)

## The Core Concept: Why This Example Exists

**The Problem:** Fetching "a user with their posts and each post's comments" in plain SQL means a multi-table `JOIN` that produces a flat denormalized row set, which you then hand-stitch back into a nested object graph in application code. Do this for three levels (`users → posts → comments → likes`) and you're writing a recursive group-by reducer for every query — fragile, repetitive, and the first place an N+1 bug hides. The core query builder (`db.select().from(...).leftJoin(...)`) is fully type-safe but still hands you flat rows.

**The Solution:** Drizzle layers a **Relational Query Builder (RQB)** on top of the schema and the core builder. You describe the shape of the result you want declaratively — `db.query.users.findMany({ with: { posts: { with: { comments: true } } } })` — and Drizzle (a) generates *exactly one* SQL statement (lateral joins of subqueries under the hood), (b) executes it, and (c) returns an already-nested object graph whose TypeScript type is inferred from the `with`/`columns`/`where` you wrote. You opt in by passing `schema` to `drizzle()`, and define `relations()` next to each table to declare which connections exist.

The RQB is the **ergonomic high-level API**: it trades a little SQL-shaped control for a lot of "I described the JSON I want and got it, typed." When you hit its ceiling (a `with` clause it can't express, a window function, a custom aggregate), the `sql` template-literal escape hatch and the core `db.select(...)` builder (🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) Section C) are always one import away. Think of RQB as Prisma's `include`/`select`, but compiling to real SQL rather than a proprietary query protocol.

> The relations the RQB traverses are the `db.query` API covered in 🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) Section D ("relations (`db.query`) + the N+1 problem"). This walkthrough goes deeper into `with`, `columns`, filters, and the `sql` escape hatch than that bundle's overview.

## Practical Walkthrough: Code Breakdown

### Opting in: schema + `relations()`

RQB only works if you hand Drizzle your schema and define relations. The docs' canonical multi-level schema:

```ts
import { type AnyPgColumn, boolean, integer, pgTable, primaryKey, serial, text, timestamp } from 'drizzle-orm/pg-core';
import { relations } from 'drizzle-orm';

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  verified: boolean('verified').notNull(),
  invitedBy: integer('invited_by').references((): AnyPgColumn => users.id),
});

export const usersRelations = relations(users, ({ one, many }) => ({
  invitee: one(users, { fields: [users.invitedBy], references: [users.id] }),
  usersToGroups: many(usersToGroups),
  posts: many(posts),
}));

export const posts = pgTable('posts', {
  id: serial('id').primaryKey(),
  content: text('content').notNull(),
  authorId: integer('author_id').references(() => users.id),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
});

export const postsRelations = relations(posts, ({ one, many }) => ({
  author: one(users, { fields: [posts.authorId], references: [users.id] }),
  comments: many(comments),
}));

export const comments = pgTable('comments', {
  id: serial('id').primaryKey(),
  content: text('content').notNull(),
  creator: integer('creator').references(() => users.id),
  postId: integer('post_id').references(() => posts.id),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
});

export const commentsRelations = relations(comments, ({ one, many }) => ({
  post: one(posts, { fields: [comments.postId], references: [posts.id] }),
  author: one(users, { fields: [comments.creator], references: [users.id] }),
  likes: many(commentLikes),
}));
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

Two things make the RQB work:

1. **Foreign keys in the table definitions** (`authorId: integer('author_id').references(() => users.id)`) — these are the real DB constraints.
2. **`relations()` declarations** — these name the connections (`posts`, `comments`, `author`) and disambiguate direction (`one` vs `many`). They don't emit SQL; they're metadata the RQB reads to know what `with: { ... }` keys are legal.

You then construct the client with schema, which mounts the `db.query` API:

```ts
import * as schema from './schema';
import { drizzle } from 'drizzle-orm/...';

const db = drizzle({ schema });

await db.query.users.findMany(...);
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

(Older docs and the v1 internals show this as `db._query`; the public entry point is `db.query`. Both refer to the same relational API.)

### `findMany` and `findFirst` — the two entry points

```ts
// all rows
const users = await db.query.users.findMany();
//   ^? { id: number; name: string; verified: boolean; invitedBy: number | null }[]
```

```ts
// first row only — findFirst appends `limit 1`
const user = await db.query.users.findFirst();
//   ^? { id: number; name: string; verified: boolean; invitedBy: number | null } | undefined
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

The result type is inferred straight from the table — note `invitedBy: number | null` reflects the column's nullability. `findMany` always returns an array; `findFirst` returns a single row or `undefined`.

### `with` — nested relations, to any depth

`with` is the whole point: pull related rows as nested arrays/objects, and the **type** carries the nesting:

```ts
const users = await db.query.users.findMany({
  with: {
    posts: {
      with: {
        comments: true,
      },
    },
  },
});
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

Each `with` value is either `true` ("give me everything, all columns") or a nested config object (`{ where, with, columns, orderBy, limit, extras }`) that recursively applies the same options. So you can filter at *every* level — "users, with posts created this month, each post with its top 5 comments":

```ts
await db.query.posts.findMany({
  where: (posts, { eq }) => (eq(posts.id, 1)),
  with: {
    comments: {
      where: (comments, { lt }) => lt(comments.createdAt, new Date()),
    },
  },
});
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

Drizzle generates a **single SQL statement** (lateral joins of subqueries) for this — not one query per level, so no N+1. (See 🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) Section 6.1 for the N+1 problem the RQB prevents.)

### `columns` — projection (include/exclude)

`columns` lets you pick which fields come back at each level. Drizzle projects at the SQL level — no extra data crosses the wire:

```ts
// include only id and content
const posts = await db.query.posts.findMany({
  columns: {
    id: true,
    content: true,
  },
  with: {
    comments: true,
  },
});
```

```ts
// exclude content (everything else included)
const posts = await db.query.posts.findMany({
  columns: {
    content: false,
  },
});
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

Two rules the docs are explicit about:

1. **`true` and `false` together → `false` is ignored.** If you include `name` and exclude `id`, the `id: false` is redundant: Drizzle switches to allow-list mode (only `true` columns survive). The docs spell this out to prevent confusion.
2. **Nested relations have their own `columns`** — projection is per-level:

```ts
const posts = await db.query.posts.findMany({
  columns: { id: true, content: true },
  with: {
    comments: {
      columns: { authorId: false },   // drop authorId from comments only
    },
  },
});
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

The result type reflects every projection — `columns: { id: true, content: true }` narrows the row to `{ id: number; content: string }` at compile time. (The full type-inference story is in 🔗 [`08-type-safety.md`](./08-type-safety.md).)

### `where`, `orderBy`, `limit` — filters and shaping

Filters use the same operator functions (`eq`, `lt`, `and`, `or`, …) as the core builder, with a **callback form** that hands you the table and operators so you don't need imports:

```ts
// imported form
import { eq } from 'drizzle-orm';
const users = await db.query.users.findMany({
  where: eq(users.id, 1),
});

// callback form (no imports needed)
const users = await db.query.users.findMany({
  where: (users, { eq }) => eq(users.id, 1),
});
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

`orderBy` and `limit` work the same way, and apply to **each level independently**:

```ts
await db.query.posts.findMany({
  orderBy: (posts, { asc }) => [asc(posts.id)],
  with: {
    comments: {
      orderBy: (comments, { desc }) => [desc(comments.id)],
    },
  },
});
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

One constraint the docs flag: **`offset` is only available at the top level**, not inside nested `with`. `limit` works at any level.

```ts
await db.query.posts.findMany({
  limit: 5,
  offset: 2, // ✅ top-level
  with: {
    comments: {
      limit: 3,     // ✅ nested limit
      // offset: 3, // ❌ not allowed inside with
    },
  },
});
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

### `extras` and the `sql` escape hatch

When you need a computed field the schema doesn't have (a lowercased name, a string length), `extras` injects a raw `sql` fragment — and the `sql` template literal is the general escape hatch for anything RQB can't express:

```ts
import { sql } from 'drizzle-orm';

await db.query.users.findMany({
  extras: {
    loweredName: sql`lower(${users.name})`.as('lowered_name'),
  },
});
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

The same `sql` operator is what the core builder uses for raw fragments (🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) Section C):

```ts
import { sql } from 'drizzle-orm';

await db.select().from(users).where(sql`${users.id} < 42`);
await db.select().from(users).where(sql`lower(${users.name}) = 'aaron'`);
```

*Source: [orm.drizzle.team/docs/select](https://orm.drizzle.team/docs/select)*

Every value interpolated into a `sql` template is **automatically parameterized** (`$1`, `$2`, …) — so `sql` is safe from injection by construction, the same way bound parameters protect the raw driver (🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) Section 4.1). You only reach for `sql` when the declarative API runs out; for everything else, `with`/`columns`/`where` is both shorter and typed.

### Prepared statements

RQB queries compose into prepared statements via `.prepare()` and `placeholder()`:

```ts
const prepared = db.query.users.findMany({
  where: ((users, { eq }) => eq(users.id, placeholder('id'))),
  with: {
    posts: {
      where: ((users, { eq }) => eq(users.id, placeholder('pid'))),
    },
  },
}).prepare('query_name');

const usersWithPosts = await prepared.execute({ id: 1 });
```

*Source: [orm.drizzle.team/docs/rqb](https://orm.drizzle.team/docs/rqb)*

Placeholders can appear in `where`, `limit`, and `offset`; `.execute()` supplies the bound values.

## Mental Model: Thinking in Relational Queries

### Declarative shape → one SQL statement

```
You write                         Drizzle compiles                You get
─────────                         ────────────────                ───────
db.query.users.findMany({         SELECT … FROM users            {
  with: {                           LEFT JOIN LATERAL (             id, name,
    posts: {                          SELECT … FROM posts            posts: [
      with: { comments: true }        WHERE author_id = users.id      { id, content,
    }                                 …                               comments: […] }
  }                                ) AS posts                     ]
})                                LEFT JOIN LATERAL ( … comments …) }
                                   …one round trip
```

You describe the **shape** (the JSON you want back); Drizzle picks the SQL (lateral subquery joins) and the post-processing (nesting) to produce it. The type of the result is inferred from the *same* shape description — change `with`, the type changes with no manual annotation.

### RQB vs core builder vs raw SQL

| Layer | When to reach for it | What you give up |
| --- | --- | --- |
| `db.query.<table>.findMany({...})` (RQB) | Nested relations, ergonomic reads, "give me this object graph." | Some SQL-shaped control; aggregations in `extras` are limited (use core queries for those). |
| `db.select({...}).from(...).leftJoin(...)` (core) | Joins where you want flat rows, custom projections, `groupBy`/aggregations, window functions. | You re-nest the rows yourself; more verbose for deep graphs. |
| `db.execute(sql\`...\`)` (raw) | Something Drizzle can't express yet (dialect-specific syntax, complex CTEs). | All type safety; you're back to `unknown`. |

They're a ladder, not competitors — RQB at the top (most ergonomic), raw `sql` at the bottom (most power). The `sql` operator lets you drop down a rung *inside* an RQB query (`extras`, custom `where`) without abandoning the layer above.

### Why relations are separate from foreign keys

```
Table (FK constraint)          relations() metadata
─────────────────────          ─────────────────────
posts.authorId ─refs→ users   postsRelations = { author: one(users, …) }
  (real DB column)              (names the edge for the RQB)
```

The FK is the *truth* (enforced by the DB). The `relations()` is the *naming* the RQB needs to expose that edge as a `with: { author }` key — and to disambiguate when two FKs point at the same table (e.g. `comments.creator` and `comments.postId` both need names: `author`, `post`). This is why RQB is "opt-in": without `relations()`, the FKs still work at the SQL level, but `db.query` has nothing to traverse.

## Pitfalls

- **`true` and `false` in `columns` don't combine.** Mixing include (`true`) and exclude (`false`) silently switches to allow-list mode and ignores the `false`s. Pick one strategy per level.
- **`offset` only at the top level.** Putting `offset` inside a nested `with` is a type error — nested pagination uses `limit` only.
- **RQB is read-focused.** It's a query API; for writes use `db.insert`/`update`/`delete` (the core builder), optionally inside a `db.transaction` (🔗 [`06-transactions.md`](./06-transactions.md)).
- **One SQL statement has caveats.** Because RQB emits a single statement (lateral joins), features that need multiple statements or dialect-specific syntax may be unsupported. PlanetScale historically didn't support lateral joins — hence the RQB's `mode: "planetscale"` toggle documented on the page. For unsupported shapes, drop to the core builder.
- **`extras` is not for aggregations.** The docs warn: aggregations aren't supported in `extras`; use core `db.select(...).groupBy(...)` instead.
- **Don't forget `.as('name')` on `extras`.** A `sql` fragment in `extras` without an explicit alias becomes a `DrizzleTypeError` and can't be referenced.
- **Schema must be passed to `drizzle({ schema })`.** Omit it and `db.query` is undefined. The `relations()` are only reachable through that mount point.

## Cross-references

- 🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) — Section D ("relations (`db.query`) + the N+1 problem") is the overview this walkthrough extends; Section 6.1 covers the N+1 problem the single-statement RQB prevents; Section C is the core `db.select()` builder you drop into when RQB runs out.
- 🔗 [`08-type-safety.md`](./08-type-safety.md) — how the result type of `findMany`/`findFirst` is inferred from the schema and narrowed by `columns`/`with`.
- 🔗 [`06-transactions.md`](./06-transactions.md) — `tx.query.*` runs the RQB inside a transaction so reads see uncommitted writes.
- 🔗 [`../rust/sqlx/07-postgres-query-files.md`](../rust/sqlx/07-postgres-query-files.md) — SQLx's `query_file!` + JOIN approach for the "flat rows, hand-nested" alternative Drizzle's RQB automates away.
- 🔗 [`../go/SQLX_GORM.md`](../go/SQLX_GORM.md) — GORM's `Preload`/`Joins` is the Go analog: declarative eager-loading of relations, same N+1-avoidance goal, different (struct-tag-driven) ergonomics.
