# String Matching: The Pattern Detective 🔍


* **`01-concepts-01-the-core-problem.md`**: Finding all occurrences of a pattern in a text using naive searching requires O(nm) comparisons. How can we search more efficiently, especially for multiple searches?
* **`01-concepts-02-the-guiding-philosophy.md`**: Preprocess the pattern to skip unnecessary comparisons. By analyzing the pattern structure, we can jump forward in the text when mismatches occur.
* **`01-concepts-03-key-abstractions.md`**: The `pattern`, `text`, and `failure function`. **Analogy**: Looking for a word in a book. Instead of checking every position letter by letter, you notice patterns - if "temperature" doesn't match at position 5, you can skip ahead knowing "temp" can't start in the next 3 positions.
* **`02-guides-01-implementing-kmp.md`**: Build the Knuth-Morris-Pratt algorithm, showing how the failure function enables linear-time string matching.
* **`03-deep-dive-01-finite-automata-approach.md`**: How string matching algorithms can be viewed as finite automata, and how this perspective leads to even more efficient algorithms for multiple pattern matching.

---
