# Replication: Don't Put All Your Eggs in One Basket 🧺


* **`01-concepts-01-the-core-problem.md`**: What happens if the server holding your data fails? Hardware fails, networks break. How do you ensure the system stays available and no data is lost?
* **`01-concepts-02-the-guiding-philosophy.md`**: Make copies. The core idea is to maintain identical copies (replicas) of the data on multiple independent servers. If one fails, the others can take over.
* **`01-concepts-03-key-abstractions.md`**: Defines `primary` (or leader), `secondary` (or follower), `replication lag`, and `failover`. Analogy: Having multiple, synchronized copies of a critical document stored in different safe deposit boxes.
* **`02-guides-01-setting-up-a-simple-replica.md`**: A guide using a database like PostgreSQL to configure a primary server and a read replica, demonstrating that writes to the primary appear on the replica.
* **`03-deep-dive-01-synchronous-vs-asynchronous-replication.md`**: Explores the fundamental trade-off between consistency and performance. Synchronous replication is safer but slower; asynchronous is faster but risks data loss on failure. This is a classic Consistency vs. Availability trade-off.

---
