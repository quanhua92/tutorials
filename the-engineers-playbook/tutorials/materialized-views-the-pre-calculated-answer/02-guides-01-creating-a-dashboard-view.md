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

### Step-by-Step Guide: Complete Implementation

```mermaid
graph TD
    subgraph "Implementation Steps"
        A["📝 Step 1: Analyze Requirements"]
        A --> A1["Identify expensive queries"]
        A --> A2["Determine refresh frequency"]
        A --> A3["Assess data freshness needs"]
        A --> A4["Evaluate system capacity"]
        
        B["🔧 Step 2: Design View"]
        B --> B1["Write and test base query"]
        B --> B2["Add appropriate indexes"]
        B --> B3["Consider partitioning"]
        B --> B4["Plan storage requirements"]
        
        C["🚀 Step 3: Create View"]
        C --> C1["CREATE MATERIALIZED VIEW"]
        C --> C2["Initial data population"]
        C --> C3["Verify data accuracy"]
        C --> C4["Test query performance"]
        
        D["🔄 Step 4: Setup Refresh"]
        D --> D1["Choose refresh strategy"]
        D --> D2["Schedule refresh jobs"]
        D --> D3["Monitor refresh performance"]
        D --> D4["Handle refresh failures"]
        
        E["📊 Step 5: Monitor & Optimize"]
        E --> E1["Track query performance"]
        E --> E2["Monitor data freshness"]
        E --> E3["Analyze usage patterns"]
        E --> E4["Optimize as needed"]
        
        A --> B --> C --> D --> E
    end
    
    style A fill:#e3f2fd
    style A1 fill:#e3f2fd
    style A2 fill:#e3f2fd
    style A3 fill:#e3f2fd
    style A4 fill:#e3f2fd
    style B fill:#e8f5e8
    style B1 fill:#e8f5e8
    style B2 fill:#e8f5e8
    style B3 fill:#e8f5e8
    style B4 fill:#e8f5e8
    style C fill:#c8e6c9
    style C1 fill:#c8e6c9
    style C2 fill:#c8e6c9
    style C3 fill:#c8e6c9
    style C4 fill:#c8e6c9
    style D fill:#fff3e0
    style D1 fill:#fff3e0
    style D2 fill:#fff3e0
    style D3 fill:#fff3e0
    style D4 fill:#fff3e0
    style E fill:#f3e5f5
    style E1 fill:#f3e5f5
    style E2 fill:#f3e5f5
    style E3 fill:#f3e5f5
    style E4 fill:#f3e5f5
```

### Data Flow Visualization

```mermaid
graph TD
    subgraph "Materialized View Data Flow"
        A["💾 Source Tables"]
        A --> A1["📋 orders table"]
        A --> A2["📋 order_items table"]
        A --> A3["📋 products table"]
        A --> A4["📋 customers table"]
        
        B["🔍 Complex Query"]
        A1 --> B
        A2 --> B
        A3 --> B
        A4 --> B
        
        B --> B1["JOIN operations"]
        B --> B2["WHERE filtering"]
        B --> B3["GROUP BY aggregation"]
        B --> B4["ORDER BY sorting"]
        
        C["📊 Materialized View"]
        B1 --> C
        B2 --> C
        B3 --> C
        B4 --> C
        
        C --> C1["daily_sales_summary"]
        C --> C2["Indexed for fast reads"]
        C --> C3["Updated by refresh"]
        C --> C4["Queried by applications"]
        
        D["👤 Application Usage"]
        C1 --> D
        C2 --> D
        C3 --> D
        C4 --> D
        
        D --> D1["Dashboard queries"]
        D --> D2["Report generation"]
        D --> D3["API responses"]
        D --> D4["Analytics tools"]
    end
    
    style A fill:#e3f2fd
    style A1 fill:#e3f2fd
    style A2 fill:#e3f2fd
    style A3 fill:#e3f2fd
    style A4 fill:#e3f2fd
    style B fill:#ffcdd2
    style B1 fill:#ffcdd2
    style B2 fill:#ffcdd2
    style B3 fill:#ffcdd2
    style B4 fill:#ffcdd2
    style C fill:#c8e6c9
    style C1 fill:#c8e6c9
    style C2 fill:#c8e6c9
    style C3 fill:#c8e6c9
    style C4 fill:#c8e6c9
    style D fill:#fff3e0
    style D1 fill:#fff3e0
    style D2 fill:#fff3e0
    style D3 fill:#fff3e0
    style D4 fill:#fff3e0
```

### Performance Comparison

```mermaid
graph LR
    subgraph "Before vs After Performance"
        A["❌ Original Query"]
        A --> A1["Execution time: 45 seconds"]
        A --> A2["CPU usage: 80%"]
        A --> A3["Memory: 2GB"]
        A --> A4["I/O: 500MB"]
        A --> A5["Blocks other queries"]
        
        B["✅ Materialized View"]
        B --> B1["Execution time: 50ms"]
        B --> B2["CPU usage: 2%"]
        B --> B3["Memory: 10MB"]
        B --> B4["I/O: 1MB"]
        B --> B5["No blocking"]
        
        C["📈 Improvement"]
        C --> C1["900x faster"]
        C --> C2["40x less CPU"]
        C --> C3["200x less memory"]
        C --> C4["500x less I/O"]
        C --> C5["No contention"]
        
        D["🔄 Refresh Cost"]
        D --> D1["Runs once every 15 min"]
        D --> D2["45 seconds every 15 min"]
        D --> D3["= 5% of time"]
        D --> D4["vs 100% continuous load"]
    end
    
    style A fill:#ffcdd2
    style A1 fill:#ffcdd2
    style A2 fill:#ffcdd2
    style A3 fill:#ffcdd2
    style A4 fill:#ffcdd2
    style A5 fill:#ffcdd2
    style B fill:#c8e6c9
    style B1 fill:#c8e6c9
    style B2 fill:#c8e6c9
    style B3 fill:#c8e6c9
    style B4 fill:#c8e6c9
    style B5 fill:#c8e6c9
    style C fill:#e3f2fd
    style C1 fill:#e3f2fd
    style C2 fill:#e3f2fd
    style C3 fill:#e3f2fd
    style C4 fill:#e3f2fd
    style C5 fill:#e3f2fd
    style D fill:#fff3e0
    style D1 fill:#fff3e0
    style D2 fill:#fff3e0
    style D3 fill:#fff3e0
    style D4 fill:#fff3e0
```

### Best Practices Checklist

```mermaid
graph TD
    subgraph "Materialized View Best Practices"
        A["📝 Design Phase"]
        A --> A1["✓ Profile expensive queries"]
        A --> A2["✓ Analyze data access patterns"]
        A --> A3["✓ Consider data freshness needs"]
        A --> A4["✓ Plan for data growth"]
        
        B["🔧 Implementation Phase"]
        B --> B1["✓ Test query performance"]
        B --> B2["✓ Add appropriate indexes"]
        B --> B3["✓ Consider partitioning"]
        B --> B4["✓ Plan refresh strategy"]
        
        C["📊 Monitoring Phase"]
        C --> C1["✓ Track query performance"]
        C --> C2["✓ Monitor refresh times"]
        C --> C3["✓ Alert on failures"]
        C --> C4["✓ Measure data freshness"]
        
        D["🔄 Maintenance Phase"]
        D --> D1["✓ Regular performance reviews"]
        D --> D2["✓ Optimize refresh schedules"]
        D --> D3["✓ Update statistics"]
        D --> D4["✓ Plan for scaling"]
    end
    
    style A fill:#e3f2fd
    style A1 fill:#e3f2fd
    style A2 fill:#e3f2fd
    style A3 fill:#e3f2fd
    style A4 fill:#e3f2fd
    style B fill:#e8f5e8
    style B1 fill:#e8f5e8
    style B2 fill:#e8f5e8
    style B3 fill:#e8f5e8
    style B4 fill:#e8f5e8
    style C fill:#c8e6c9
    style C1 fill:#c8e6c9
    style C2 fill:#c8e6c9
    style C3 fill:#c8e6c9
    style C4 fill:#c8e6c9
    style D fill:#fff3e0
    style D1 fill:#fff3e0
    style D2 fill:#fff3e0
    style D3 fill:#fff3e0
    style D4 fill:#fff3e0
```
