# Columnar Storage: Querying at Ludicrous Speed 📊


* **`01-concepts-01-the-core-problem.md`**: Analytical queries (like `SUM` or `AVG`) on huge datasets are slow because traditional row-based databases have to read massive amounts of irrelevant data from disk.
* **`01-concepts-02-the-guiding-philosophy.md`**: Store data by column, not by row. If you only need to analyze three columns out of 100, a columnar database reads only those three columns, drastically reducing I/O.
* **`01-concepts-03-key-abstractions.md`**: The `column chunk` and `compression`. Analogy: Comparing two phone books. One is the standard "by name" book (row-store). The other is a weird phone book organized by street address, listing all people on that street (column-store). To find everyone on "Main St," the second book is vastly superior.
* **`02-guides-01-a-columnar-query.md`**: A conceptual guide comparing two file layouts. First, a CSV (row-store). Second, separate files for each column. Show how much less data you need to read to calculate the average of a single column in the second layout.
* **`03-deep-dive-01-the-compression-advantage.md`**: Why is columnar storage so good for compression? Storing similar data types together (e.g., a file of only integers) creates low-entropy data that compresses exceptionally well.

---
