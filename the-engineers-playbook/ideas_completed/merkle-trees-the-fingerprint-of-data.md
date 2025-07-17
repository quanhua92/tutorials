# Merkle Trees: The Fingerprint of Data 🧬


* **`01-concepts-01-the-core-problem.md`**: You have two large collections of data on different machines. How can you quickly and efficiently verify if they are identical, or find exactly which parts are different, without transferring all the data?
* **`01-concepts-02-the-guiding-philosophy.md`**: Hash the data, then hash the hashes. A Merkle tree builds a tree of hashes. The leaves are hashes of individual data blocks. The nodes above them are hashes of their children's hashes, all the way up to a single root hash.
* **`01-concepts-03-key-abstractions.md`**: `Leaves` (data blocks), `nodes` (hashes), and the `Merkle Root`. Analogy: A company's organizational chart for verifying payroll. Instead of checking every employee's salary, the CEO can just ask two VPs for their divisions' total payroll. If the totals match, they assume the details are correct. If not, they drill down to the managers, and so on, quickly pinpointing the discrepancy. The Merkle Root is the CEO's total.
* **`02-guides-01-building-a-merkle-root.md`**: A guide to taking an array of strings, hashing each one, and then recursively hashing the hashes together to produce a single root hash.
* **`03-deep-dive-01-merkle-trees-in-git-and-bitcoin.md`**: Explains why this structure is fundamental to distributed systems. Git uses it to find changed objects efficiently, and Bitcoin uses it to verify that a transaction is included in a block without downloading the entire block.

---
