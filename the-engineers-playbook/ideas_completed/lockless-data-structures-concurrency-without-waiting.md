# Lockless Data Structures: Concurrency Without Waiting 🚦


* **`01-concepts-01-the-core-problem.md`**: Traditional locking for protecting shared data in multi-threaded applications can be slow and lead to problems like deadlock and priority inversion. How can we allow multiple threads to safely work on the same data without ever having to wait for a lock?
* **`01-concepts-02-the-guiding-philosophy.md`**: Use atomic hardware instructions to make optimistic changes. The core idea is to attempt an update and then use a special CPU instruction like **Compare-And-Swap (CAS)** to commit it, but only if no other thread has changed the data in the meantime. If the data changed, you simply retry.
* **`01-concepts-03-key-abstractions.md`**: The `atomic operation`, `Compare-And-Swap (CAS)`, and the `retry loop`. Analogy: Two people trying to update the same cell in a shared spreadsheet. You read the value '5', decide to change it to '6', but before you save, you check: "Is the cell *still* 5?". If yes, you save '6'. If another person changed it to '7' in the meantime, your save fails, and you have to re-read the new value and try again.
* **`02-guides-01-implementing-a-lock-free-counter.md`**: A guide showing how to build a thread-safe counter using an atomic `fetch-and-add` instruction or a CAS loop, and comparing its performance to a lock-based implementation.
* **`03-deep-dive-01-the-aba-problem.md`**: Explores a subtle and famous bug in lock-free programming. A value is read as 'A', changes to 'B', then changes *back* to 'A'. A CAS loop will incorrectly think nothing has changed. This dive explains why it's a problem and how solutions like tagged pointers work.

---
