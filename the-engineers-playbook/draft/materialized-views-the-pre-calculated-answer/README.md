# Materialized Views: The Pre-Calculated Answer

Materialized views are a powerful database feature for optimizing the performance of complex, frequently executed queries. They work by pre-calculating the results of a query and storing them as a physical table, allowing applications to read the data much faster than re-running the original query.

This tutorial explores the core concepts, practical guides, and deep-dive topics related to materialized views.

## Table of Contents

*   **Core Concepts**
    *   [01-concepts-01-the-core-problem.md](./01-concepts-01-the-core-problem.md)
    *   [01-concepts-02-the-guiding-philosophy.md](./01-concepts-02-the-guiding-philosophy.md)
    *   [01-concepts-03-key-abstractions.md](./01-concepts-03-key-abstractions.md)
*   **Practical Guides**
    *   [02-guides-01-creating-a-dashboard-view.md](./02-guides-01-creating-a-dashboard-view.md)
*   **Deep Dives**
    *   [03-deep-dive-01-the-freshness-trade-off.md](./03-deep-dive-01-the-freshness-trade-off.md)
*   **Implementation**
    *   [04-sql-examples.md](./04-sql-examples.md)
