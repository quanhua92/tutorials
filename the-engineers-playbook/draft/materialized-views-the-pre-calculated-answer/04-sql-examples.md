# Practical Implementation: SQL Examples

This file provides a set of SQL commands to demonstrate the creation, usage, and maintenance of materialized views. These examples use standard SQL syntax that is compatible with PostgreSQL, one of the most popular open-source relational databases.

### 1. Setup: Create Base Tables and Insert Data

First, let's create the tables that will be the source for our materialized view and populate them with some sample data.

```sql
-- Create a table for customer orders
CREATE TABLE orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL,
    order_date TIMESTAMPTZ NOT NULL
);

-- Create a table for the items within each order
CREATE TABLE order_items (
    item_id SERIAL PRIMARY KEY,
    order_id INT REFERENCES orders(order_id),
    product_id VARCHAR(50) NOT NULL,
    quantity INT NOT NULL,
    price DECIMAL(10, 2) NOT NULL
);

-- Insert some sample data
INSERT INTO orders (customer_id, order_date) VALUES
(101, '2023-10-01 10:00'),
(102, '2023-10-01 11:30'),
(101, '2023-10-02 14:00');

INSERT INTO order_items (order_id, product_id, quantity, price) VALUES
(1, 'prod_A', 2, 10.00),
(1, 'prod_B', 1, 25.00),
(2, 'prod_C', 5, 5.00),
(3, 'prod_A', 1, 10.00);
```

### 2. The Expensive Query

This is the query we want to optimize. Running this repeatedly would be inefficient.

```sql
-- Query to get total sales per day
SELECT
    o.order_date::date AS sale_date,
    SUM(oi.quantity * oi.price) AS total_sales
FROM
    orders o
JOIN
    order_items oi ON o.order_id = oi.order_id
GROUP BY
    sale_date
ORDER BY
    sale_date;
```

### 3. Create the Materialized View

Now, we create the materialized view. This executes the query and stores the result set.

```sql
-- Create the materialized view
CREATE MATERIALIZED VIEW daily_sales_summary AS
SELECT
    o.order_date::date AS sale_date,
    SUM(oi.quantity * oi.price) AS total_sales,
    COUNT(DISTINCT o.order_id) AS number_of_orders
FROM
    orders o
JOIN
    order_items oi ON o.order_id = oi.order_id
GROUP BY
    sale_date;
```
*Notice we've added another aggregation (`number_of_orders`) to make the view even more useful.*

### 4. Query the Materialized View

This is the fast query that your application's dashboard would run.

```sql
-- Query the materialized view (fast!)
SELECT * FROM daily_sales_summary ORDER BY sale_date;
```

### 5. Refreshing the Materialized View

Let's add a new order and see that the view is stale.

```sql
-- A new order comes in
INSERT INTO orders (customer_id, order_date) VALUES (103, '2023-10-02 15:00');
INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (4, 'prod_D', 1, 100.00);

-- Querying the view shows STALE data
SELECT * FROM daily_sales_summary ORDER BY sale_date;
-- The new order for 2023-10-02 is NOT reflected yet.

-- Refresh the view to update its data
REFRESH MATERIALIZED VIEW daily_sales_summary;

-- Querying the view again shows FRESH data
SELECT * FROM daily_sales_summary ORDER BY sale_date;
-- Now the total_sales for 2023-10-02 is updated.
```

### 6. Advanced: Concurrent Refresh

A standard `REFRESH` command will lock the materialized view, preventing reads while it is being updated. For large views, this can cause significant downtime for your application.

PostgreSQL offers a solution: `REFRESH CONCURRENTLY`. This command creates a new, temporary version of the view in the background. Once the new version is ready, it's swapped with the old one in a quick, non-blocking transaction.

To use `REFRESH CONCURRENTLY`, the materialized view must have a `UNIQUE` index.

```sql
-- Add a unique index to the materialized view
CREATE UNIQUE INDEX daily_sales_summary_date ON daily_sales_summary (sale_date);

-- Now you can refresh the view without locking it for reads
REFRESH MATERIALIZED VIEW CONCURRENTLY daily_sales_summary;
```

This example demonstrates the core lifecycle of a materialized view: create, query, and refresh. The key to using them effectively is to choose a refresh strategy that matches your application's needs, and to use `REFRESH CONCURRENTLY` when possible to minimize downtime.
