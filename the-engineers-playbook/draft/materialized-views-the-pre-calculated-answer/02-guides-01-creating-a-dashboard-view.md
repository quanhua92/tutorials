# Guide: Creating a Materialized View for a Sales Dashboard

In this guide, we'll walk through a practical example of creating a materialized view to power a sales dashboard. We'll use SQL, which is the standard language for interacting with relational databases.

## The Scenario

We have two tables: `orders` and `order_items`.

```mermaid
flowchart TD
    subgraph "Base Tables"
        A[orders] --> B[order_items];
    end

    subgraph "Expensive Query"
        C{JOIN and GROUP BY} --> D[Calculated Results];
    end

    subgraph "Materialized View"
        E[daily_sales_summary];
    end

    A --> C;
    B --> C;
    D -- "Stored in" --> E

    style A fill:#f9f,stroke:#333,stroke-width:2px
    style B fill:#f9f,stroke:#333,stroke-width:2px
    style E fill:#caffbf,stroke:#333,stroke-width:2px
```

**`orders` table:**
| order_id | customer_id | order_date |
|----------|-------------|------------|
| 1        | 101         | 2023-10-01 |
| 2        | 102         | 2023-10-01 |
| 3        | 101         | 2023-10-02 |

**`order_items` table:**
| item_id | order_id | product_id | quantity | price |
|---------|----------|------------|----------|-------|
| 1       | 1        | 'prod_A'   | 2        | 10.00 |
| 2       | 1        | 'prod_B'   | 1        | 25.00 |
| 3       | 2        | 'prod_C'   | 5        | 5.00  |
| 4       | 3        | 'prod_A'   | 1        | 10.00 |

Our goal is to create a summary of total sales per day.

## The Expensive Query

Without a materialized view, we would run this query every time we load the dashboard:

```sql
SELECT
    o.order_date,
    SUM(oi.quantity * oi.price) AS total_sales
FROM
    orders o
JOIN
    order_items oi ON o.order_id = oi.order_id
GROUP BY
    o.order_date
ORDER BY
    o.order_date;
```

On a large dataset, this query can be slow due to the `JOIN` and `GROUP BY` operations.

## Creating the Materialized View

Now, let's create a materialized view to pre-calculate this result. The syntax is straightforward:

```sql
CREATE MATERIALIZED VIEW daily_sales_summary AS
SELECT
    o.order_date,
    SUM(oi.quantity * oi.price) AS total_sales
FROM
    orders o
JOIN
    order_items oi ON o.order_id = oi.order_id
GROUP BY
    o.order_date;
```

The database will execute this query once and store the results in a new object called `daily_sales_summary`.

## Querying the Materialized View

Now, instead of running the complex query, our dashboard can run a much simpler and faster one:

```sql
SELECT * FROM daily_sales_summary ORDER BY order_date;
```

This query is incredibly fast because it's just reading from a simple, pre-computed table.

## Refreshing the Data

The data in `daily_sales_summary` is a snapshot. If new orders come in, the view will be stale. To update it, we need to refresh it:

```sql
REFRESH MATERIALIZED VIEW daily_sales_summary;
```

After running this command, the view will be updated with the latest data from the `orders` and `order_items` tables. How and when you run this `REFRESH` command is the central trade-off of using materialized views.
