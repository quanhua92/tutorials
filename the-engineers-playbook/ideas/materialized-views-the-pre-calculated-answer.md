# Materialized Views: The Pre-Calculated Answer 🧾


* **`01-concepts-01-the-core-problem.md`**: Some queries, especially those used for reporting and analytics with many joins and aggregations, are very expensive to run. Executing them repeatedly for a dashboard is a huge waste of resources.
* **`01-concepts-02-the-guiding-philosophy.md`**: Compute once, read many times. A materialized view is essentially a query whose results are stored as a physical table. Instead of running the complex query, applications can just read from this simple, pre-computed table.
* **`01-concepts-03-key-abstractions.md`**: The `view definition` (the query) and the `refresh policy`. Analogy: The final box score of a baseball game. Instead of re-watching the entire game (running the query) to find out the final score, you can just look at the pre-calculated box score (the materialized view).
* **`02-guides-01-creating-a-dashboard-view.md`**: A SQL guide showing how to create a materialized view that calculates total monthly sales. Demonstrate that querying the view is orders of magnitude faster than running the original aggregation query.
* **`03-deep-dive-01-the-freshness-trade-off.md`**: Materialized views have one major drawback: the data can be stale. This deep dive explores the critical decision of *when* to refresh the view—on a schedule, on a trigger, or on demand—and the trade-offs between data freshness and refresh cost.

---
