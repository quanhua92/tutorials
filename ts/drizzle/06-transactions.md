# Transactions: `db.transaction`, all-or-nothing

**Doc Source**: [Drizzle — Transactions](https://orm.drizzle.team/docs/transactions)

## The Core Concept: Why This Example Exists

**The Problem:** Most real database writes are *multi-step*. "Transfer money" is two `UPDATE`s: debit one account, credit another. "Create order" is an `INSERT` for the order, then `INSERT`s for each line item, then a `UPDATE` to decrement stock. If step 2 fails after step 1 committed, your database now has a credited account with no matching debit (money appeared from nowhere), or an order with no items. Partial failure corrupts the invariants your application relies on.

**The Solution:** Database transactions group statements into a unit that is **atomic** — all commit, or none do. Drizzle exposes this through a single callback-based API: `db.transaction(async (tx) => {...})`. You run every statement of the unit against the `tx` handle; the callback's **return commits the transaction**, and any **throw rolls it back**. There is no manual `BEGIN`/`COMMIT`/`ROLLBACK` to forget, no "did I commit?" bug class. Nested calls to `tx.transaction(...)` map to SQL **savepoints**, so an inner failure can be recovered without aborting the whole unit.

This is the exact same ACID contract as Rust's SQLx (🔗 [`../rust/sqlx/06-postgres-transactions.md`](../rust/sqlx/06-postgres-transactions.md)) and Go's `database/sql` `db.Begin()`/`tx.Commit()` (🔗 [`../go/SQLX_GORM.md`](../go/SQLX_GORM.md)) — the differences are only in *ergonomics*. SQLx leans on RAII (drop-without-commit = rollback); Drizzle leans on **exceptions as the rollback signal**, which is idiomatic JS/TS. That throw-to-rollback behavior is precisely why this walkthrough cross-references the curriculum's 🔗 [`ERRORS_EXCEPTIONS`](../ERRORS_EXCEPTIONS.md) bundle: a thrown error inside the callback is not just caught-and-logged, it is the *transaction's abort instruction*.

> Transactions are the "all-or-nothing" guarantee covered in 🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) Section 4.2 ("Transactions: all-or-nothing — commit on return, rollback on throw"). The raw `better-sqlite3` `db.transaction()` shown there is the untyped primitive; `drizzle.transaction` is the typed, schema-aware wrapper over the same SQL `BEGIN`/`COMMIT`.

## Practical Walkthrough: Code Breakdown

### The atomic callback: `db.transaction`

The canonical Drizzle transaction is an `async` callback that receives a `tx` handle. Every statement runs against `tx` (never `db`):

```ts
const db = drizzle(...)

await db.transaction(async (tx) => {
  await tx.update(accounts).set({ balance: sql`${accounts.balance} - 100.00` }).where(eq(users.name, 'Dan'));
  await tx.update(accounts).set({ balance: sql`${accounts.balance} + 100.00` }).where(eq(users.name, 'Andrew'));
});
```

*Source: [orm.drizzle.team/docs/transactions](https://orm.drizzle.team/docs/transactions)*

The contract:

- **Return normally → `COMMIT`.** Both `UPDATE`s persist together.
- **Throw (from either `UPDATE` failing, or any `throw` in the body) → `ROLLBACK`.** Neither `UPDATE` survives. The throw propagates to the caller, so you handle it like any other rejected promise.

There is no `tx.commit()` / `tx.rollback()` you must remember to call on the happy path — return value *is* the commit. Contrast SQLx (🔗 [`../rust/sqlx/06-postgres-transactions.md`](../rust/sqlx/06-postgres-transactions.md)) where you must explicitly `transaction.commit().await?` and the type system enforces rollback-on-drop; Drizzle instead uses the JS exception channel, which is the natural fit for a promise-based API.

### Explicit rollback with `tx.rollback()`

You can force a rollback from inside the callback — useful when business logic detects an invalid state *without* an underlying SQL error:

```ts
await db.transaction(async (tx) => {
  const [account] = await tx.select({ balance: accounts.balance }).from(accounts).where(eq(users.name, 'Dan'));
  if (account.balance < 100) {
    // This throws an exception that rollbacks the transaction.
    tx.rollback()
  }

  await tx.update(accounts).set({ balance: sql`${accounts.balance} - 100.00` }).where(eq(users.name, 'Dan'));
  await tx.update(accounts).set({ balance: sql`${accounts.balance} + 100.00` }).where(eq(users.name, 'Andrew'));
});
```

*Source: [orm.drizzle.team/docs/transactions](https://orm.drizzle.team/docs/transactions)*

`tx.rollback()` **throws** — that throw is the rollback signal, and it propagates out of `db.transaction` like any rejection. This is why it composes naturally with `try/catch` and the error-handling patterns in 🔗 [`ERRORS_EXCEPTIONS`](../ERRORS_EXCEPTIONS.md): the caller can `catch` the rollback and treat it as a normal "transaction aborted" outcome, distinguishable by error type if you wrap it.

### Returning a value from the transaction

The callback's return value is the resolved value of the outer promise — so a transaction is also a typed query:

```ts
const newBalance: number = await db.transaction(async (tx) => {
  await tx.update(accounts).set({ balance: sql`${accounts.balance} - 100.00` }).where(eq(users.name, 'Dan'));
  await tx.update(accounts).set({ balance: sql`${accounts.balance} + 100.00` }).where(eq(users.name, 'Andrew'));

  const [account] = await tx.select({ balance: accounts.balance }).from(accounts).where(eq(users.name, 'Dan'));
  return account.balance;
});
```

*Source: [orm.drizzle.team/docs/transactions](https://orm.drizzle.team/docs/transactions)*

The type annotation `: number` here is real — Drizzle infers the result type of `tx.select(...)` (see 🔗 [`08-type-safety.md`](./08-type-safety.md)), so `account.balance` is already `number`, and the transaction's return type follows.

### Nested transactions → SAVEPOINTs

Drizzle maps nested `tx.transaction(...)` calls to SQL savepoints, giving you **partial rollback** within a larger unit:

```ts
await db.transaction(async (tx) => {
  await tx.update(accounts).set({ balance: sql`${accounts.balance} - 100.00` }).where(eq(users.name, 'Dan'));
  await tx.update(accounts).set({ balance: sql`${accounts.balance} + 100.00` }).where(eq(users.name, 'Andrew'));

  await tx.transaction(async (tx2) => {
    await tx2.update(users).set({ name: "Mr. Dan" }).where(eq(users.name, "Dan"));
  });
});
```

*Source: [orm.drizzle.team/docs/transactions](https://orm.drizzle.team/docs/transactions)*

Under the hood this emits `SAVEPOINT`, runs the inner statements, and `RELEASE SAVEPOINT` on success (or `ROLLBACK TO SAVEPOINT` if `tx2`'s callback throws). The outer transaction is unaffected by an inner savepoint's rollback — you can try a risky sub-operation, catch its failure, and continue the outer unit.

### Relational queries inside a transaction

The high-level relational query builder (🔗 [`07-rqb-query-builder.md`](./07-rqb-query-builder.md)) works on `tx` too, so reads inside a transaction see the transaction's own uncommitted writes:

```ts
const db = drizzle({ schema })

await db.transaction(async (tx) => {
  await tx.query.users.findMany({
    with: {
      accounts: true
    }
  });
});
```

*Source: [orm.drizzle.team/docs/transactions](https://orm.drizzle.team/docs/transactions)*

This is how you do a "read-modify-write" cycle safely — the `findMany` reflects prior writes in the same `tx`, and no other connection can interleave a change between your read and your write (depending on isolation level).

### Dialect-specific transaction configuration

The second argument to `db.transaction` configures the underlying `BEGIN`. Each dialect exposes its own options interface. For PostgreSQL:

```ts
await db.transaction(
  async (tx) => {
    await tx.update(accounts).set({ balance: sql`${accounts.balance} - 100.00` }).where(eq(users.name, "Dan"));
    await tx.update(accounts).set({ balance: sql`${accounts.balance} + 100.00` }).where(eq(users.name, "Andrew"));
  }, {
    isolationLevel: "read committed",
    accessMode: "read write",
    deferrable: true,
  }
);

interface PgTransactionConfig {
  isolationLevel?:
    | "read uncommitted"
    | "read committed"
    | "repeatable read"
    | "serializable";
  accessMode?: "read only" | "read write";
  deferrable?: boolean;
}
```

*Source: [orm.drizzle.team/docs/transactions](https://orm.drizzle.team/docs/transactions)*

MySQL offers `withConsistentSnapshot`, SQLite offers `behavior: 'deferred' | 'immediate' | 'exclusive'`, MSSQL adds a `'snapshot'` isolation level, etc. — all documented on the same page. These map 1:1 to the dialect's native `SET TRANSACTION` syntax.

## Mental Model: Thinking in Transactions

### The transaction boundary, Drizzle-flavored

```
Outside tx:        [shared, committed state]
                            │
              db.transaction(async (tx) => {   ◀── BEGIN
                            │
Inside tx:         [isolated, uncommitted state]
                            │
            ┌───────────────┴───────────────┐
        return                          throw
        (or resolve)                  (or tx.rollback())
            │                               │
        COMMIT                        ROLLBACK
            │                               │
Outside tx:    [updated state]        [unchanged state]
```

Everything inside the callback is isolated until the callback resolves; the resolution *is* the commit decision.

### Exceptions *are* the rollback channel

```
db.transaction(async (tx) => {
   await step1(tx);        // ok
   await step2(tx);        // throws  ──┐
   await step3(tx);        // skipped    │
})                                      ▼
                          ROLLBACK, and the throw propagates
                          to the caller as a rejected promise
```

This is the JS-idiomatic mirror of Rust's `?` operator pattern (🔗 [`../rust/sqlx/06-postgres-transactions.md`](../rust/sqlx/06-postgres-transactions.md)):

```rust
// SQLx: ? propagates the error, drop rolls back
let mut tx = pool.begin().await?;
risky_operation(&mut tx).await?;   // auto-rollback on error
tx.commit().await?;
```

Same "fail-fast, abort the unit" semantics; Drizzle uses the promise rejection chain, SQLx uses `Result` + RAII. The curriculum's 🔗 [`ERRORS_EXCEPTIONS`](../ERRORS_EXCEPTIONS.md) bundle is the foundation here — the throw is not swallowed by `db.transaction`, it is *re-thrown* after the rollback completes.

### ACID in one paragraph

- **Atomicity** — the callback is the unit; return commits all, throw rolls back all.
- **Consistency** — constraints (FK, unique, check) are evaluated; a violation throws → rollback.
- **Isolation** — set via `isolationLevel`; concurrent `tx`s see each other's writes only per the level.
- **Durability** — once the callback resolves (commit returned), the writes survive crashes.

## Pitfalls

- **Run every statement on `tx`, not `db`.** A statement issued on `db` inside the callback is *outside* the transaction — it commits independently and can't see the tx's uncommitted writes. The docs show all queries going through `tx`/`tx2`.
- **Don't swallow the throw inside the callback.** If you `catch` an error and return normally, the transaction **commits** the partial work — the exact corruption transactions exist to prevent. Let throws propagate, or call `tx.rollback()` explicitly.
- **`tx.rollback()` throws — it does not "cancel quietly".** If you wrap the callback body in `try/catch` and accidentally catch the rollback's own throw, you'll mask the abort. Treat rollback as terminal.
- **Connection lifetime.** The `tx` handle is bound to one connection for the callback's lifetime; don't stash it and use it after `db.transaction` resolves (it's been released to the pool).
- **Savepoints aren't free.** Each `tx.transaction(...)` inside another transaction is a real `SAVEPOINT`; deep nesting can stress some databases. Use it for recoverable sub-units, not as a loop primitive.
- **Isolation level defaults differ by dialect.** PostgreSQL defaults to `read committed`; don't assume serializable semantics without setting it explicitly.
- **Relational queries on `tx` require schema on the `db`.** `db.transaction` inherits the `db`'s schema config, so `tx.query.*` only works if you constructed `drizzle({ schema })`.

## Cross-references

- 🔗 [`DATABASE_DRIVERS`](../DATABASE_DRIVERS.md) — Section 4.2 ("Transactions: all-or-nothing") for the raw `better-sqlite3` primitive Drizzle wraps; Section D for the relational queries that run inside `tx`.
- 🔗 [`ERRORS_EXCEPTIONS`](../ERRORS_EXCEPTIONS.md) — `throw` *is* the rollback instruction. The promise-rejection semantics that make `db.transaction` work are the same error channel covered here.
- 🔗 [`../rust/sqlx/06-postgres-transactions.md`](../rust/sqlx/06-postgres-transactions.md) — SQLx transactions: RAII rollback-on-drop, explicit `commit()`. The compile-time-enforced cousin; same ACID contract, different ergonomics.
- 🔗 [`../go/SQLX_GORM.md`](../go/SQLX_GORM.md) — Go `database/sql`'s `db.Begin()`/`tx.Commit()`/`tx.Rollback()` and GORM's `db.Transaction(func(tx *gorm.DB) error {...})`, which uses the same return-nil=commit / return-err=rollback convention as Drizzle.
