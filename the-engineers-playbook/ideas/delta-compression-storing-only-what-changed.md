# Delta Compression: Storing Only What Changed 📝


* **`01-concepts-01-the-core-problem.md`**: Storing multiple versions of the same file or object (e.g., in version control or backup systems) is incredibly inefficient if you store a full copy each time.
* **`01-concepts-02-the-guiding-philosophy.md`**: Store the difference, not the whole thing. Delta compression saves a base version and then, for subsequent versions, it only stores the "delta"—a compact description of what was added and removed.
* **`01-concepts-03-key-abstractions.md`**: The `base version`, the `delta` (or diff), and the `reconstruction` process. Analogy: How a collaborator reviews your document. They don't send you a whole new document back; they send you their "track changes" file (the delta), which you can apply to your original to see the new version.
* **`02-guides-01-simulating-git-deltas.md`**: A conceptual guide showing two text files. Generate a "diff" file that represents the changes between them. Then, show how you can take the first file and the diff file to perfectly reconstruct the second file.
* **`03-deep-dive-01-forward-vs-reverse-deltas.md`**: A deep dive into implementation strategy. **Forward deltas** are simple (v2 = v1 + delta), but getting the latest version can require applying many deltas. **Reverse deltas** (v1 = v2 - delta) are more complex but make accessing the most recent version extremely fast, which is why systems like Git use them.

---
