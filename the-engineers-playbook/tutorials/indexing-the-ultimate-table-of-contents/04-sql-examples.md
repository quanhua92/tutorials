# SQL Examples: Mastering Index Creation and Optimization

This section provides comprehensive, copy-paste-ready SQL examples for creating, optimizing, and managing indexes across different database systems. Each example includes the reasoning behind the index design and performance expectations.

## Database Setup

```mermaid
graph TD
    A[E-commerce Schema] --> B[users table]
    A --> C[products table]
    A --> D[orders table]
    A --> E[order_items table]
    
    B --> F[100K users]
    C --> G[Product catalog]
    D --> H[Order history]
    E --> I[Line items]
    
    F --> J[Login/Profile queries]
    G --> K[Search/Filter queries]
    H --> L[User order history]
    I --> M[Order detail queries]
    
    style A fill:#87CEEB
    style J fill:#90EE90
    style K fill:#90EE90
    style L fill:#90EE90
    style M fill:#90EE90
```

### Sample Schema

```sql
-- E-commerce database schema for examples
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    date_of_birth DATE,
    city VARCHAR(100),
    country VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    category_id INTEGER,
    price DECIMAL(10,2),
    stock_quantity INTEGER,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    order_number VARCHAR(50) UNIQUE NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    total_amount DECIMAL(12,2),
    shipping_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    shipped_at TIMESTAMP,
    delivered_at TIMESTAMP
);

CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2),
    total_price DECIMAL(12,2)
);

-- Sample data insertion
INSERT INTO users (email, username, first_name, last_name, city, country) 
SELECT 
    'user' || i || '@example.com',
    'user' || i,
    'First' || i,
    'Last' || i,
    CASE (i % 5) 
        WHEN 0 THEN 'New York'
        WHEN 1 THEN 'London'
        WHEN 2 THEN 'Tokyo'
        WHEN 3 THEN 'Paris'
        ELSE 'Berlin'
    END,
    CASE (i % 3)
        WHEN 0 THEN 'USA'
        WHEN 1 THEN 'UK'
        ELSE 'Germany'
    END
FROM generate_series(1, 100000) AS i;
```

## Essential Index Patterns

```mermaid
graph TD
    A[Index Patterns] --> B[Single Column]
    A --> C[Composite]
    A --> D[Covering]
    A --> E[Partial]
    
    B --> F[One column optimized<br/>Simple & efficient]
    C --> G[Multiple columns<br/>Order matters]
    D --> H[Include extra columns<br/>Avoid table lookups]
    E --> I[Subset of rows<br/>Space efficient]
    
    J[Performance Impact] --> K[Single: O(log n)]
    J --> L[Composite: O(log n) + selectivity]
    J --> M[Covering: Index-only scan]
    J --> N[Partial: Smaller footprint]
    
    style K fill:#90EE90
    style L fill:#90EE90
    style M fill:#87CEEB
    style N fill:#FFD700
```

### 1. Single Column Indexes

**Use Case**: Queries filtering by one column

```mermaid
sequenceDiagram
    participant Q as Query
    participant I as Index
    participant T as Table
    
    Q->>I: WHERE email = 'user123@example.com'
    I->>I: Binary search in B-tree
    I->>T: Direct pointer to row location
    T->>Q: Return row data
    
    Note over I: O(log n) performance
    Note over T: Single row fetch
```

```sql
-- Fast user lookup by email (login functionality)
CREATE INDEX idx_users_email ON users(email);

-- Query this optimizes:
SELECT * FROM users WHERE email = 'user123@example.com';

-- Performance expectation: O(log n) vs O(n) without index
-- Typical improvement: 100x faster for large tables
```

```sql
-- Product lookups by SKU (inventory management)
CREATE INDEX idx_products_sku ON products(sku);

-- Query this optimizes:
SELECT * FROM products WHERE sku = 'LAPTOP-15-001';
```

```sql
-- Order history by user (customer portal)
CREATE INDEX idx_orders_user_id ON orders(user_id);

-- Query this optimizes:
SELECT * FROM orders WHERE user_id = 12345 ORDER BY created_at DESC;
```

### 2. Composite Indexes

**Use Case**: Queries filtering by multiple columns

```mermaid
graph TD
    A[Composite Index: country, city] --> B[Primary Sort: Country]
    B --> C[USA] --> D[Secondary Sort: City within USA]
    B --> E[UK] --> F[Secondary Sort: City within UK]
    
    D --> G[Boston, Chicago, New York]
    F --> H[London, Manchester]
    
    I[Query Efficiency] --> J[country = 'USA' ✅ Uses index]
    I --> K[country = 'USA' AND city = 'Boston' ✅ Uses full index]
    I --> L[city = 'Boston' ❌ Cannot use index]
    
    style J fill:#90EE90
    style K fill:#90EE90
    style L fill:#ff9999
```

```sql
-- User search by location (city + country)
CREATE INDEX idx_users_location ON users(country, city);

-- Efficient queries:
SELECT * FROM users WHERE country = 'USA' AND city = 'New York';
SELECT * FROM users WHERE country = 'USA';  -- Can use leftmost column

-- Inefficient query (cannot use index):
SELECT * FROM users WHERE city = 'New York';  -- Missing leftmost column
```

```sql
-- Order status tracking with date range
CREATE INDEX idx_orders_status_created ON orders(status, created_at);

-- Query this optimizes:
SELECT * FROM orders 
WHERE status = 'shipped' 
  AND created_at >= '2024-01-01' 
  AND created_at < '2024-02-01';
```

```sql
-- Product catalog filtering
CREATE INDEX idx_products_category_price ON products(category_id, price);

-- Efficient for:
SELECT * FROM products 
WHERE category_id = 5 
  AND price BETWEEN 100.00 AND 500.00;
```

### 3. Covering Indexes

**Use Case**: Include additional columns to avoid table lookups

```mermaid
sequenceDiagram
    participant Q as Query
    participant CI as Covering Index
    participant T as Table
    
    Note over Q: SELECT order_number, status, total_amount, created_at<br/>FROM orders WHERE user_id = 12345
    
    Q->>CI: user_id lookup
    CI->>CI: Find matching entries
    CI->>Q: Return all requested columns from index
    
    Note over T: Table never accessed!
    Note over CI: Index-only scan = faster
```

```sql
-- Order summary without touching main table
CREATE INDEX idx_orders_user_covering 
ON orders(user_id) 
INCLUDE (order_number, status, total_amount, created_at);

-- Query returns all needed data from index:
SELECT order_number, status, total_amount, created_at 
FROM orders 
WHERE user_id = 12345;
```

```sql
-- Product listing with minimal data
CREATE INDEX idx_products_active_covering 
ON products(is_active) 
INCLUDE (name, price) 
WHERE is_active = true;

-- Fast product catalog query:
SELECT name, price 
FROM products 
WHERE is_active = true;
```

### 4. Partial Indexes

**Use Case**: Index only relevant subset of data

```mermaid
graph TD
    A[Full Table: 1M users] --> B[Active: 800K users]
    A --> C[Inactive: 200K users]
    
    D[Full Index] --> E[Indexes all 1M users]
    E --> F[Size: 100MB]
    
    G[Partial Index] --> H[Only indexes active users]
    H --> I[Size: 80MB = 20% smaller]
    
    J[Query Patterns] --> K[Only query active users 95% of time]
    K --> L[Partial index covers 95% of queries]
    L --> M[Better cache utilization]
    
    style I fill:#90EE90
    style M fill:#90EE90
```

```sql
-- Index only active users
CREATE INDEX idx_users_active_email 
ON users(email) 
WHERE status = 'active';

-- Smaller index, faster for:
SELECT * FROM users 
WHERE email = 'user@example.com' 
  AND status = 'active';
```

```sql
-- Index only pending orders
CREATE INDEX idx_orders_pending_created 
ON orders(created_at) 
WHERE status = 'pending';

-- Efficient for order processing:
SELECT * FROM orders 
WHERE status = 'pending' 
  AND created_at < (NOW() - INTERVAL '1 hour');
```

```sql
-- Index only high-value orders
CREATE INDEX idx_orders_high_value 
ON orders(created_at) 
WHERE total_amount > 1000.00;

-- Fast VIP order tracking:
SELECT * FROM orders 
WHERE total_amount > 1000.00 
ORDER BY created_at DESC;
```

## Performance Optimization Examples

```mermaid
graph TD
    A[Performance Optimization Strategies] --> B[Query-Specific Design]
    A --> C[Join Optimization]
    A --> D[Range Query Optimization]
    
    B --> E[Analyze query patterns]
    B --> F[Create targeted indexes]
    B --> G[Include covering columns]
    
    C --> H[Index foreign keys]
    C --> I[Covering indexes for joins]
    C --> J[Avoid nested loop joins]
    
    D --> K[Leading column for ranges]
    D --> L[Composite for filters + ranges]
    D --> M[Partial for date-based queries]
    
    style E fill:#87CEEB
    style F fill:#90EE90
    style H fill:#90EE90
    style K fill:#90EE90
```

### 5. Query-Specific Index Design

**Scenario**: Frequently run analytics query

```sql
-- Original slow query:
SELECT 
    country,
    COUNT(*) as user_count,
    AVG(EXTRACT(YEAR FROM AGE(date_of_birth))) as avg_age
FROM users 
WHERE status = 'active' 
GROUP BY country;

-- Optimized index:
CREATE INDEX idx_users_analytics 
ON users(status, country) 
INCLUDE (date_of_birth);

-- Query now uses index scan instead of table scan
-- Performance improvement: 10-50x faster
```

**Scenario**: Complex join query optimization

```sql
-- Original query joining orders and users:
SELECT 
    u.email,
    u.first_name,
    u.last_name,
    o.order_number,
    o.total_amount
FROM orders o
JOIN users u ON o.user_id = u.id
WHERE o.status = 'shipped'
  AND o.created_at >= '2024-01-01';

-- Required indexes for optimal performance:
CREATE INDEX idx_orders_status_date ON orders(status, created_at);
CREATE INDEX idx_orders_user_lookup ON orders(user_id) 
    INCLUDE (order_number, total_amount);
CREATE INDEX idx_users_contact_info ON users(id) 
    INCLUDE (email, first_name, last_name);
```

### 6. Range Query Optimization

```mermaid
graph LR
    A[Range Queries] --> B[Date Ranges]
    A --> C[Numeric Ranges]
    A --> D[Text Ranges]
    
    B --> E[created_at >= '2024-01-01'<br/>AND created_at < '2024-02-01']
    C --> F[price BETWEEN 50.00 AND 200.00]
    D --> G[name >= 'A' AND name < 'C']
    
    H[Index Strategy] --> I[Leading column must be range field]
    H --> J[Additional filters as trailing columns]
    H --> K[Consider partial indexes for common ranges]
    
    style I fill:#90EE90
    style J fill:#87CEEB
    style K fill:#FFD700
```

```sql
-- Date range queries (common in reporting)
CREATE INDEX idx_orders_date_range ON orders(created_at, status);

-- Efficient queries:
SELECT COUNT(*) FROM orders 
WHERE created_at >= '2024-01-01' 
  AND created_at < '2024-02-01';

SELECT * FROM orders 
WHERE created_at >= CURRENT_DATE - INTERVAL '7 days' 
  AND status IN ('pending', 'processing');
```

```sql
-- Numeric range optimization
CREATE INDEX idx_products_price_range ON products(price, category_id) 
WHERE is_active = true;

-- Fast price filtering:
SELECT * FROM products 
WHERE price BETWEEN 50.00 AND 200.00 
  AND is_active = true
ORDER BY price;
```

## Index Maintenance Examples

```mermaid
graph TD
    A[Index Health Monitoring] --> B[Usage Statistics]
    A --> C[Size Analysis]
    A --> D[Performance Metrics]
    
    B --> E[idx_tup_read: Read operations]
    B --> F[idx_tup_fetch: Tuple fetches]
    B --> G[Identify unused indexes]
    
    C --> H[Index size vs table size]
    C --> I[Bloat detection]
    C --> J[Storage optimization]
    
    D --> K[Query execution times]
    D --> L[Index scan vs seq scan]
    D --> M[Cache hit ratios]
    
    style G fill:#FFA500
    style I fill:#ff9999
    style M fill:#90EE90
```

### 7. Index Health Monitoring

```sql
-- PostgreSQL: Check index usage statistics
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_tup_read,
    idx_tup_fetch,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_tup_read DESC;
```

```sql
-- Find unused indexes (candidates for removal)
SELECT 
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as wasted_space
FROM pg_stat_user_indexes
WHERE idx_tup_read = 0 
  AND idx_tup_fetch = 0
  AND indexname NOT LIKE '%_pkey'  -- Exclude primary keys
ORDER BY pg_relation_size(indexrelid) DESC;
```

```sql
-- Index bloat detection
SELECT 
    schemaname,
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as current_size,
    CASE 
        WHEN pg_relation_size(indexrelid) > 100 * 1024 * 1024 -- 100MB
        THEN 'Consider REINDEX'
        ELSE 'OK'
    END as recommendation
FROM pg_stat_user_indexes
WHERE schemaname = 'public';
```

### 8. Index Rebuilding and Maintenance

```mermaid
flowchart TD
    A[Index Maintenance Triggers] --> B[Fragmentation]
    A --> C[Bloat]
    A --> D[Statistics Outdated]
    
    B --> E[REINDEX INDEX]
    C --> F[REINDEX TABLE]
    D --> G[ANALYZE]
    
    H[Maintenance Strategy] --> I[Monitor bloat %]
    H --> J[Schedule during low traffic]
    H --> K[Use CONCURRENTLY when possible]
    
    E --> L[Rebuilds single index]
    F --> M[Rebuilds all table indexes]
    G --> N[Updates query planner stats]
    
    style K fill:#90EE90
    style L fill:#87CEEB
    style M fill:#FFA500
    style N fill:#FFD700
```

```sql
-- Rebuild fragmented index (PostgreSQL)
REINDEX INDEX idx_users_email;

-- Rebuild all indexes on a table
REINDEX TABLE users;

-- Update table statistics after bulk operations
ANALYZE users;
ANALYZE products;
ANALYZE orders;
```

```sql
-- MySQL equivalents
ALTER TABLE users DROP INDEX idx_users_email;
ALTER TABLE users ADD INDEX idx_users_email (email);

-- Update statistics
ANALYZE TABLE users;
```

### 9. Bulk Load Optimization

```mermaid
sequenceDiagram
    participant A as Application
    participant DB as Database
    participant I as Indexes
    participant T as Table
    
    A->>DB: BEGIN transaction
    DB->>I: DROP non-essential indexes
    A->>T: Bulk INSERT (fast - no index maintenance)
    DB->>I: CREATE indexes on populated data
    DB->>DB: ANALYZE to update statistics
    A->>DB: COMMIT
    
    Note over DB: 50% faster than loading with indexes
```

```sql
-- Strategy for large data imports
BEGIN;

-- 1. Drop non-essential indexes
DROP INDEX IF EXISTS idx_users_location;
DROP INDEX IF EXISTS idx_users_analytics;

-- 2. Perform bulk insert
INSERT INTO users (email, username, first_name, last_name, city, country)
SELECT ... FROM staging_table;

-- 3. Recreate indexes
CREATE INDEX idx_users_location ON users(country, city);
CREATE INDEX idx_users_analytics ON users(status, country) 
    INCLUDE (date_of_birth);

-- 4. Update statistics
ANALYZE users;

COMMIT;
```

## Advanced Index Techniques

```mermaid
graph TD
    A[Advanced Index Techniques] --> B[Functional Indexes]
    A --> C[Text Search Indexes]
    A --> D[JSON Indexes]
    
    B --> E[LOWER(email) for case-insensitive]
    B --> F[EXTRACT(YEAR FROM date) for year queries]
    B --> G[Complex expressions]
    
    C --> H[Full-text search]
    C --> I[GIN indexes for text]
    C --> J[Multiple language support]
    
    D --> K[JSONB column indexing]
    D --> L[Specific JSON field access]
    D --> M[JSON path expressions]
    
    style E fill:#87CEEB
    style H fill:#90EE90
    style K fill:#FFD700
```

### 10. Functional Indexes

```sql
-- Case-insensitive email search
CREATE INDEX idx_users_email_lower ON users(LOWER(email));

-- Query using the functional index:
SELECT * FROM users WHERE LOWER(email) = LOWER('User@Example.Com');
```

```sql
-- Date-based partitioning index
CREATE INDEX idx_orders_month ON orders(EXTRACT(YEAR FROM created_at), 
                                        EXTRACT(MONTH FROM created_at));

-- Monthly reporting queries:
SELECT COUNT(*), SUM(total_amount) 
FROM orders 
WHERE EXTRACT(YEAR FROM created_at) = 2024 
  AND EXTRACT(MONTH FROM created_at) = 1;
```

### 11. Text Search Indexes

```mermaid
graph LR
    A[Full-Text Search Process] --> B[Text Parsing]
    B --> C[Tokenization]
    C --> D[Stemming]
    D --> E[GIN Index Storage]
    
    F[Query: 'laptop gaming'] --> G[Parse Query Terms]
    G --> H[Match Against Index]
    H --> I[Rank Results by Relevance]
    
    style E fill:#90EE90
    style I fill:#87CEEB
```

```sql
-- PostgreSQL full-text search
CREATE INDEX idx_products_fulltext ON products 
USING gin(to_tsvector('english', name || ' ' || description));

-- Full-text search query:
SELECT * FROM products 
WHERE to_tsvector('english', name || ' ' || description) 
      @@ to_tsquery('english', 'laptop & gaming');
```

### 12. JSON Column Indexing

```mermaid
graph TD
    A[JSONB Column] --> B[{'theme': 'dark', 'lang': 'en'}]
    
    C[Index Types] --> D[GIN Index on entire column]
    C --> E[Index on specific field: theme]
    C --> F[Index on nested path]
    
    G[Query Patterns] --> H[preferences->>'theme' = 'dark']
    G --> I[preferences @> {'theme': 'dark'}]
    G --> J[Complex JSON path queries]
    
    style D fill:#87CEEB
    style E fill:#90EE90
    style H fill:#90EE90
```

```sql
-- JSON column with user preferences
ALTER TABLE users ADD COLUMN preferences JSONB;

-- Index specific JSON fields
CREATE INDEX idx_users_preferences_theme 
ON users USING gin((preferences->'theme'));

-- Query JSON data efficiently:
SELECT * FROM users 
WHERE preferences->>'theme' = 'dark';
```

## Best Practices Summary

```mermaid
flowchart TD
    A[Index Best Practices] --> B[Before Creating]
    A --> C[During Creation]
    A --> D[After Creation]
    
    B --> E[Analyze query patterns]
    B --> F[Check existing indexes]
    B --> G[Estimate impact]
    
    C --> H[Use EXPLAIN ANALYZE]
    C --> I[Consider composite vs single]
    C --> J[Choose appropriate type]
    
    D --> K[Monitor usage]
    D --> L[Track performance]
    D --> M[Regular maintenance]
    
    style E fill:#87CEEB
    style H fill:#90EE90
    style K fill:#FFD700
```

### Index Creation Checklist

```sql
-- 1. Analyze query patterns first
EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'test@example.com';

-- 2. Create targeted index
CREATE INDEX idx_users_email ON users(email);

-- 3. Verify improvement
EXPLAIN ANALYZE SELECT * FROM users WHERE email = 'test@example.com';

-- 4. Monitor usage over time
SELECT * FROM pg_stat_user_indexes WHERE indexname = 'idx_users_email';
```

### Common Anti-Patterns to Avoid

```mermaid
graph TD
    A[Index Anti-Patterns] --> B[Over-Indexing]
    A --> C[Redundant Indexes]
    A --> D[Wrong Column Order]
    
    B --> E[Index every column]
    B --> F[No selectivity analysis]
    B --> G[Ignore write overhead]
    
    C --> H[Duplicate single + composite]
    C --> I[Multiple similar indexes]
    C --> J[Unused indexes]
    
    D --> K[Non-selective columns first]
    D --> L[Ignore query patterns]
    D --> M[Wrong leftmost prefix]
    
    style E fill:#ff9999
    style H fill:#ff9999
    style K fill:#ff9999
```

```sql
-- DON'T: Index every column
-- This creates unnecessary overhead
CREATE INDEX idx_users_first_name ON users(first_name);  -- Low selectivity
CREATE INDEX idx_users_last_name ON users(last_name);    -- Low selectivity
CREATE INDEX idx_users_city ON users(city);              -- Low selectivity

-- DO: Create composite index for actual query patterns
CREATE INDEX idx_users_search ON users(last_name, first_name, city);
```

```sql
-- DON'T: Duplicate indexes
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_login ON users(email, status);  -- email part is redundant

-- DO: Use covering index that serves multiple purposes
CREATE INDEX idx_users_login_optimized ON users(email) INCLUDE (status);
```

These examples provide a comprehensive foundation for implementing effective indexing strategies in production systems. Remember to always measure before and after creating indexes to ensure they provide the expected performance benefits.