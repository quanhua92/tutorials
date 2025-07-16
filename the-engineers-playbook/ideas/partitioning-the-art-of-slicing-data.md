# Partitioning: The Art of Slicing Data 🔪


* **`01-concepts-01-the-core-problem.md`**: A single, massive database table becomes slow and difficult to manage. Queries take too long, creating indexes is a nightmare, and backups are unwieldy. How can we break it up into more manageable pieces within the same database instance?
* **`01-concepts-02-the-guiding-philosophy.md`**: Divide a table into smaller tables based on a key. Partitioning splits one logical table into multiple physical sub-tables, but the database still treats it as a single table. The query planner is smart enough to only access the partitions it needs.
* **`01-concepts-03-key-abstractions.md`**: The `partition key`, `range partitioning`, `list partitioning`, and `hash partitioning`. Analogy: A filing cabinet for invoices. Instead of one giant drawer, you have twelve smaller drawers, one for each month (**range partitioning**). To find all invoices from June, you only need to open the "June" drawer.
* **`02-guides-01-setting-up-a-partitioned-table.md`**: A practical SQL guide showing how to create a partitioned `events` table in PostgreSQL, partitioned by month. Demonstrate that a query for a specific month only scans the relevant partition.
* **`03-deep-dive-01-partitioning-vs-sharding.md`**: A crucial distinction. **Partitioning** splits a table into multiple pieces on the *same* database server to improve manageability and query performance. **Sharding** splits a table across *multiple* database servers to improve scalability.

---
