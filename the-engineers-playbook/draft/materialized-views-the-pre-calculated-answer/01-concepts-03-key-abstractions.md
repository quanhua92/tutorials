# Key Abstractions: View Definition and Refresh Policy

Two key abstractions define how a materialized view works:

1.  **The View Definition:** This is the `SELECT` query that produces the data for the materialized view. It defines the structure and content of the pre-computed table. This is the "recipe" for the view.

2.  **The Refresh Policy:** This determines *how* and *when* the data in the materialized view is updated to reflect changes in the underlying base tables. This is the most critical aspect of using materialized views effectively.

## The Refresh Policy: Keeping the Data Useful

The refresh policy is where the real engineering decisions lie. Here are the common strategies:

*   **`ON DEMAND` (Manual Refresh):** The view is only updated when you explicitly tell it to. This gives you full control but requires an external mechanism (like a cron job) to trigger the refresh.
    *   **Use Case:** Nightly reports where the data only needs to be fresh once a day.

*   **`ON COMMIT` (Automatic Refresh):** The view is updated automatically every time a transaction that modifies the underlying data is committed.
    *   **Use Case:** When you need near real-time data, but this can slow down write operations on the base tables, as the refresh becomes part of the transaction.

*   **`ON SCHEDULE` (Scheduled Refresh):** The database automatically refreshes the view at a specified interval (e.g., every 15 minutes).
    *   **Use Case:** Dashboards that need reasonably fresh data but can tolerate some lag. This is a good compromise between `ON DEMAND` and `ON COMMIT`.

The choice of refresh policy is a direct trade-off between **data freshness** and the **computational cost** of the refresh. A more frequent refresh means fresher data but higher overhead.
