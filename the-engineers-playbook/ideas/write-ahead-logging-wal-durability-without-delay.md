# Write-Ahead Logging (WAL): Durability without Delay ✍️


* **`01-concepts-01-the-core-problem.md`**: How can a database guarantee that a committed transaction will survive a crash, without waiting for slow disk writes to finish for every single change?
* **`01-concepts-02-the-guiding-philosophy.md`**: First, write your intention to a log. Before modifying the actual data files (which can be slow and complex), the database writes a description of the change to a simple, append-only log on disk. This sequential log write is very fast.
* **`01-concepts-03-key-abstractions.md`**: The `log`, `commit record`, and `recovery`. Analogy: Before performing complex surgery, a surgeon first writes down the entire procedure in their notes. If they are interrupted, another surgeon can read the notes and complete the procedure safely.
* **`02-guides-01-simulating-wal.md`**: A simplified Python script that shows the principle: write an "intent" to a text file (`wal.log`), then update an in-memory dictionary. A second script shows how to "recover" the dictionary's state from the log after a simulated crash.
* **`03-deep-dive-01-wal-and-transactional-guarantees.md`**: How does WAL provide the "D" (Durability) in ACID? A deep dive into how `fsync` calls and log sequence numbers (LSNs) work together to provide crash safety.

---
