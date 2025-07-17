# LSM Trees: Making Writes Fast Again ✍️➡️🌳


* **`01-concepts-01-the-core-problem.md`**: Updating data on disk using traditional B-Trees requires slow, random I/O. How can we design a storage engine optimized for very high write throughput?
* **`01-concepts-02-the-guiding-philosophy.md`**: Never modify data on disk; just write new files. A Log-Structured Merge-Tree buffers writes in a fast in-memory table (`MemTable`) and flushes them to sorted, immutable files on disk (`SSTables`). It cleans up later.
* **`01-concepts-03-key-abstractions.md`**: The `MemTable`, `SSTable`, and the `compaction` process. Analogy: Tidying your desk. Instead of putting every paper away immediately (slow), you let them pile up in an "inbox" on your desk (MemTable). When the inbox is full, you sort the whole pile and put it in a neat folder in your filing cabinet (SSTable). Periodically, you merge old folders (compaction).
* **`02-guides-01-simulating-an-lsm-tree.md`**: A Python script showing the core loop: accept key-value pairs into a dictionary (MemTable), and when it reaches a certain size, write its sorted contents to a new timestamped file (SSTable).
* **`03-deep-dive-01-read-and-write-amplification.md`**: LSM-Trees trade one problem for another. This dive explains the costs: **Read Amplification** (a key might be in the MemTable or several SSTables) and **Write Amplification** (the same data gets rewritten multiple times during compaction).

---
