# Append-Only Logs: The Immutable Ledger 📜


* **`01-concepts-01-the-core-problem.md`**: How can we write data as fast as possible, especially when writes are frequent and concurrent? Modifying data in place is slow and complex.
* **`01-concepts-02-the-guiding-philosophy.md`**: Never change the past. The core idea is to only ever add new information to the end of a file. This turns slow, random writes into fast, sequential writes.
* **`01-concepts-03-key-abstractions.md`**: Explains the `log`, `segments`, and `compaction`. Analogy: A diary where you only write on new pages. Eventually, you might summarize old entries into a new, condensed book (compaction).
* **`02-guides-01-getting-started.md`**: Implement a simple file-based event logger that only ever appends new lines to a `log.txt` file.
* **`03-deep-dive-01-from-log-to-state.md`**: How do you get the "current state" of the world from an append-only log? Explains replaying the log to reconstruct state in memory. This is the foundation of systems like Kafka and Git.

---
