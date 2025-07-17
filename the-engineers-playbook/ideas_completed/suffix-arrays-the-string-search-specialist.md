# Suffix Arrays: The String Search Specialist 🔍


* **`01-concepts-01-the-core-problem.md`**: You need to find all occurrences of a pattern within a very large text. Suffix trees are powerful but can be memory-intensive. How can we achieve similar power with a simpler, smaller structure?
* **`01-concepts-02-the-guiding-philosophy.md`**: Sort all possible suffixes of the text. A suffix array is simply an array of all starting positions of suffixes of a text, sorted alphabetically. Finding a pattern is then reduced to a quick binary search on this sorted array.
* **`01-concepts-03-key-abstractions.md`**: The `suffix` and the sorted `array of indices`. Analogy: The ultimate index for a book. Imagine creating a list of every phrase in a book, starting from each word to the end, and then sorting that list alphabetically. To find "the quick brown fox," you'd just look in the "t" section of your massive, sorted suffix list.
* **`02-guides-01-building-a-simple-suffix-array.md`**: A guide that takes a small string like "banana", lists all its suffixes, sorts them, and creates the final suffix array. Then it demonstrates how to find the pattern "ana".
* **`03-deep-dive-01-building-suffix-arrays-efficiently.md`**: A naive sort of all suffixes is slow ($O(n^2 \log n)$). This deep dive introduces the idea behind more advanced $O(n \log n)$ or even $O(n)$ construction algorithms, which are crucial for practical use.

---
