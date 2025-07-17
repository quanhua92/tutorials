# SQL Examples: Partitioning in Practice

This section provides complete, runnable SQL examples demonstrating various partitioning strategies across different database systems. Each example includes setup, data insertion, and performance verification.

## PostgreSQL: Range Partitioning by Date

### Complete Sales Data Example

```sql
-- Create parent table for sales data
CREATE TABLE sales (
    sale_id BIGSERIAL,
    customer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    sale_amount DECIMAL(10,2) NOT NULL,
    sale_date DATE NOT NULL,
    region VARCHAR(50),
    PRIMARY KEY (sale_id, sale_date)
) PARTITION BY RANGE (sale_date);

-- Create quarterly partitions for 2024
CREATE TABLE sales_2024_q1 PARTITION OF sales 
    FOR VALUES FROM ('2024-01-01') TO ('2024-04-01');

CREATE TABLE sales_2024_q2 PARTITION OF sales 
    FOR VALUES FROM ('2024-04-01') TO ('2024-07-01');

CREATE TABLE sales_2024_q3 PARTITION OF sales 
    FOR VALUES FROM ('2024-07-01') TO ('2024-10-01');

CREATE TABLE sales_2024_q4 PARTITION OF sales 
    FOR VALUES FROM ('2024-10-01') TO ('2025-01-01');

-- Add indexes to each partition
CREATE INDEX idx_sales_2024_q1_customer ON sales_2024_q1 (customer_id);
CREATE INDEX idx_sales_2024_q1_region ON sales_2024_q1 (region);

CREATE INDEX idx_sales_2024_q2_customer ON sales_2024_q2 (customer_id);
CREATE INDEX idx_sales_2024_q2_region ON sales_2024_q2 (region);

-- Continue for all partitions...

-- Insert sample data across quarters
INSERT INTO sales (customer_id, product_id, sale_amount, sale_date, region) VALUES
-- Q1 data
(1001, 501, 299.99, '2024-01-15', 'West'),
(1002, 502, 459.99, '2024-02-20', 'East'),
(1003, 503, 199.99, '2024-03-10', 'Central'),
-- Q2 data  
(1004, 501, 299.99, '2024-04-05', 'West'),
(1005, 504, 599.99, '2024-05-15', 'East'),
(1001, 502, 459.99, '2024-06-25', 'Central'),
-- Q3 data
(1002, 505, 799.99, '2024-07-08', 'West'),
(1006, 501, 299.99, '2024-08-12', 'East'),
(1003, 503, 199.99, '2024-09-20', 'Central');

-- Verify partition pruning
EXPLAIN (ANALYZE, BUFFERS) 
SELECT * FROM sales 
WHERE sale_date BETWEEN '2024-01-01' AND '2024-03-31';
-- Should only scan sales_2024_q1

-- Cross-partition query
EXPLAIN (ANALYZE, BUFFERS)
SELECT region, COUNT(*), AVG(sale_amount) 
FROM sales 
WHERE sale_date BETWEEN '2024-02-01' AND '2024-08-31'
GROUP BY region;
-- Should scan Q1, Q2, and Q3 partitions
```

## PostgreSQL: List Partitioning by Region

```sql
-- Create parent table partitioned by region
CREATE TABLE user_data (
    user_id BIGSERIAL,
    username VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL,
    region VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, region)
) PARTITION BY LIST (region);

-- Create regional partitions
CREATE TABLE user_data_us PARTITION OF user_data 
    FOR VALUES IN ('US', 'USA', 'United States');

CREATE TABLE user_data_eu PARTITION OF user_data 
    FOR VALUES IN ('UK', 'DE', 'FR', 'ES', 'IT');

CREATE TABLE user_data_asia PARTITION OF user_data 
    FOR VALUES IN ('JP', 'CN', 'IN', 'KR', 'SG');

CREATE TABLE user_data_other PARTITION OF user_data 
    DEFAULT;  -- Catch-all for unlisted regions

-- Insert test data
INSERT INTO user_data (username, email, region) VALUES
('john_doe', 'john@example.com', 'US'),
('marie_claire', 'marie@example.fr', 'FR'),
('tanaka_san', 'tanaka@example.jp', 'JP'),
('unknown_user', 'unknown@example.com', 'AU');  -- Goes to default partition

-- Query specific regions (single partition access)
SELECT * FROM user_data WHERE region = 'US';

-- Multi-region query (multiple partition access)
SELECT region, COUNT(*) FROM user_data 
WHERE region IN ('US', 'UK', 'JP') 
GROUP BY region;
```

## PostgreSQL: Hash Partitioning for Even Distribution

```sql
-- Create parent table with hash partitioning
CREATE TABLE session_data (
    session_id UUID DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL,
    session_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (session_id, user_id)
) PARTITION BY HASH (user_id);

-- Create 4 hash partitions for even distribution
CREATE TABLE session_data_hash_0 PARTITION OF session_data 
    FOR VALUES WITH (modulus 4, remainder 0);

CREATE TABLE session_data_hash_1 PARTITION OF session_data 
    FOR VALUES WITH (modulus 4, remainder 1);

CREATE TABLE session_data_hash_2 PARTITION OF session_data 
    FOR VALUES WITH (modulus 4, remainder 2);

CREATE TABLE session_data_hash_3 PARTITION OF session_data 
    FOR VALUES WITH (modulus 4, remainder 3);

-- Insert test data (will be distributed across partitions)
INSERT INTO session_data (user_id, session_data) 
SELECT 
    generate_series(1, 1000) as user_id,
    ('{"page": "home", "timestamp": "' || NOW() || '"}')::jsonb;

-- Check distribution across partitions
SELECT 'hash_0' as partition, COUNT(*) FROM session_data_hash_0
UNION ALL
SELECT 'hash_1' as partition, COUNT(*) FROM session_data_hash_1  
UNION ALL
SELECT 'hash_2' as partition, COUNT(*) FROM session_data_hash_2
UNION ALL
SELECT 'hash_3' as partition, COUNT(*) FROM session_data_hash_3;

-- Query by user_id (will hit specific partition)
EXPLAIN SELECT * FROM session_data WHERE user_id = 42;
```

## MySQL: Range Partitioning Example

```sql
-- MySQL range partitioning by year
CREATE TABLE orders_mysql (
    order_id INT AUTO_INCREMENT,
    customer_id INT NOT NULL,
    order_total DECIMAL(10,2),
    order_date DATE NOT NULL,
    PRIMARY KEY (order_id, order_date)
) 
PARTITION BY RANGE (YEAR(order_date)) (
    PARTITION p2022 VALUES LESS THAN (2023),
    PARTITION p2023 VALUES LESS THAN (2024),
    PARTITION p2024 VALUES LESS THAN (2025),
    PARTITION p2025 VALUES LESS THAN (2026),
    PARTITION p_future VALUES LESS THAN MAXVALUE
);

-- Insert sample data
INSERT INTO orders_mysql (customer_id, order_total, order_date) VALUES
(1, 100.00, '2022-06-15'),
(2, 250.50, '2023-08-20'),
(3, 75.25, '2024-01-10'),
(4, 300.00, '2024-12-05');

-- Check partition usage
SELECT 
    PARTITION_NAME,
    TABLE_ROWS 
FROM INFORMATION_SCHEMA.PARTITIONS 
WHERE TABLE_NAME = 'orders_mysql' AND TABLE_SCHEMA = DATABASE();

-- Query with partition elimination
EXPLAIN PARTITIONS 
SELECT * FROM orders_mysql 
WHERE order_date BETWEEN '2024-01-01' AND '2024-12-31';
```

## Advanced Example: Composite Partitioning

```sql
-- PostgreSQL: Range partitioning by date, then list partitioning by region
CREATE TABLE sales_advanced (
    sale_id BIGSERIAL,
    customer_id INTEGER,
    sale_amount DECIMAL(10,2),
    sale_date DATE NOT NULL,
    region VARCHAR(20) NOT NULL,
    PRIMARY KEY (sale_id, sale_date, region)
) PARTITION BY RANGE (sale_date);

-- Create yearly partitions
CREATE TABLE sales_2024 PARTITION OF sales_advanced 
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01')
    PARTITION BY LIST (region);

-- Sub-partition 2024 by region
CREATE TABLE sales_2024_us PARTITION OF sales_2024 
    FOR VALUES IN ('US');
CREATE TABLE sales_2024_eu PARTITION OF sales_2024 
    FOR VALUES IN ('EU');
CREATE TABLE sales_2024_asia PARTITION OF sales_2024 
    FOR VALUES IN ('ASIA');

-- Insert data
INSERT INTO sales_advanced (customer_id, sale_amount, sale_date, region) VALUES
(1001, 299.99, '2024-06-15', 'US'),
(1002, 459.99, '2024-07-20', 'EU'),
(1003, 199.99, '2024-08-10', 'ASIA');

-- Query will target specific sub-partition
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM sales_advanced 
WHERE sale_date BETWEEN '2024-06-01' AND '2024-06-30' 
  AND region = 'US';
-- Should only access sales_2024_us partition
```

## Partition Maintenance Examples

```sql
-- Add new partition for next quarter
CREATE TABLE sales_2025_q1 PARTITION OF sales 
    FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');

-- Drop old partition (removes data!)
DROP TABLE sales_2023_q1;

-- Detach partition for archival (preserves data)
ALTER TABLE sales DETACH PARTITION sales_2023_q2;

-- Move detached partition to archive schema
ALTER TABLE sales_2023_q2 SET SCHEMA archive;

-- Attach existing table as new partition
CREATE TABLE sales_2025_q2 (LIKE sales INCLUDING ALL);
ALTER TABLE sales ATTACH PARTITION sales_2025_q2 
    FOR VALUES FROM ('2025-04-01') TO ('2025-07-01');
```

## Performance Monitoring Queries

```sql
-- Check partition sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size
FROM pg_tables 
WHERE tablename LIKE 'sales_%'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Monitor partition pruning effectiveness
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
SELECT COUNT(*) FROM sales 
WHERE sale_date >= '2024-01-01';

-- Check constraint exclusion settings
SHOW constraint_exclusion;
-- Should be 'on' or 'partition' for partition pruning
```

## Testing Partition Pruning

```sql
-- Create test function to verify pruning
CREATE OR REPLACE FUNCTION test_partition_pruning()
RETURNS TABLE(query_text TEXT, partitions_scanned INTEGER) AS $$
BEGIN
    -- Test 1: Single quarter query
    RETURN QUERY
    WITH query_plan AS (
        SELECT plan FROM (
            EXPLAIN (FORMAT JSON) 
            SELECT * FROM sales WHERE sale_date BETWEEN '2024-01-01' AND '2024-03-31'
        ) AS t(plan)
    )
    SELECT 
        'Q1 2024 query'::TEXT,
        (SELECT COUNT(*) FROM jsonb_array_elements(plan->'Plans') WHERE value->>'Node Type' = 'Seq Scan')::INTEGER
    FROM query_plan;
    
    -- Test 2: Multi-quarter query  
    RETURN QUERY
    WITH query_plan AS (
        SELECT plan FROM (
            EXPLAIN (FORMAT JSON)
            SELECT * FROM sales WHERE sale_date BETWEEN '2024-01-01' AND '2024-09-30'
        ) AS t(plan)
    )
    SELECT 
        'Q1-Q3 2024 query'::TEXT,
        (SELECT COUNT(*) FROM jsonb_array_elements(plan->'Plans') WHERE value->>'Node Type' = 'Seq Scan')::INTEGER
    FROM query_plan;
END;
$$ LANGUAGE plpgsql;

-- Run partition pruning test
SELECT * FROM test_partition_pruning();
```

These examples demonstrate practical partitioning implementations you can adapt for your specific use cases. Each example includes verification steps to ensure partitioning is working effectively.