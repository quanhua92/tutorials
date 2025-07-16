# Inverted Indexes: The Heart of Search Engines ❤️‍🔥


* **`01-concepts-01-the-core-problem.md`**: Across billions of web pages or documents, how can a system find all documents containing the word "Gemini" in milliseconds? Scanning each document at query time is impossible.
* **`01-concepts-02-the-guiding-philosophy.md`**: Map words to documents, not documents to words. Instead of storing a list of words for each document, an inverted index stores a list of documents for each word.
* **`01-concepts-03-key-abstractions.md`**: The `term` (word), `document`, and the `postings list` (the list of documents containing a term). Analogy: The index at the back of a textbook. The book itself maps page numbers to words (Document -> Words). The index maps words to page numbers (Word -> Documents).
* **`02-guides-01-building-a-mini-search-engine.md`**: A practical guide to creating an inverted index from a few text files. It shows how to tokenize text and build a hash map where keys are words and values are lists of document IDs.
* **`03-deep-dive-01-beyond-presence-ranking-with-tf-idf.md`**: An inverted index tells you *what* documents match. How do you find the *best* match? This deep dive explains how real search engines store term frequency (TF) and use inverse document frequency (IDF) within the index to rank results by relevance.

---
