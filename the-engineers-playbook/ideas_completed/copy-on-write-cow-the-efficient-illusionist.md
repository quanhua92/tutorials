# Copy-on-Write (CoW): The Efficient Illusionist 🪄


* **`01-concepts-01-the-core-problem.md`**: Creating a full copy of a large object in memory is slow and wasteful, especially if the copy is rarely modified. How can we defer the cost of copying until it's absolutely necessary?
* **`01-concepts-02-the-guiding-philosophy.md`**: Share data until it's modified. The philosophy is to let a "copy" operation simply point to the original data. The actual, expensive duplication is only performed at the very last moment—when someone tries to write to the data.
* **`01-concepts-03-key-abstractions.md`**: `Shared data`, `private copy`, and `write trigger`. Analogy: Two people viewing the same Google Doc. They are both seeing the same single instance. The moment one of them types a character, Google Docs creates a private version for them to edit, leaving the original untouched for the other viewer.
* **`02-guides-01-simulating-cow.md`**: A Python guide showing a class that holds a large list. Its `copy()` method just returns a new object pointing to the *same* list. The `modify()` method first checks if the data is shared, and only then performs a deep copy before making the change.
* **`03-deep-dive-01-cow-in-the-wild.md`**: A deep dive into where CoW is critical: the `fork()` system call in Linux, database snapshots (like in ZFS or Btrfs), and string implementations in some programming languages.

---
