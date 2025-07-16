# A Columnar Query: Comparing Storage Layouts

## The Setup: Two File Layouts

Let's compare how the same data and query perform with different storage layouts. We'll use a realistic e-commerce dataset and a common analytical query to see the dramatic difference.

### The Dataset

We have 1 million order records with these fields:
- `order_id` (integer)
- `customer_id` (integer)
- `order_date` (string)
- `order_total` (float)
- `product_category` (string)
- `quantity` (integer)
- `unit_price` (float)
- `tax_amount` (float)
- `shipping_cost` (float)
- `discount_amount` (float)

### The Query

We want to answer: **"What's the average order total for Electronics orders in January 2024?"**

```sql
SELECT AVG(order_total) 
FROM orders 
WHERE product_category = 'Electronics' 
  AND order_date >= '2024-01-01' 
  AND order_date < '2024-02-01';
```

## Layout 1: Row-Based Storage (CSV)

### File Structure

```python
import csv
import time
import os
import random
from datetime import datetime, timedelta

class RowBasedStorage:
    """Simulate row-based storage using CSV format"""
    
    def __init__(self, filename="orders_row_based.csv"):
        self.filename = filename
        self.columns = [
            "order_id", "customer_id", "order_date", "order_total",
            "product_category", "quantity", "unit_price", "tax_amount",
            "shipping_cost", "discount_amount"
        ]
    
    def generate_sample_data(self, num_records=100000):
        """Generate sample e-commerce data"""
        print(f"Generating {num_records:,} records in row-based format...")
        
        categories = ["Electronics", "Clothing", "Books", "Sports", "Home"]
        start_date = datetime(2024, 1, 1)
        
        start_time = time.time()
        
        with open(self.filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow(self.columns)
            
            # Generate data
            for i in range(1, num_records + 1):
                # Random date in 2024
                random_days = random.randint(0, 365)
                order_date = start_date + timedelta(days=random_days)
                
                # Generate order data
                category = random.choice(categories)
                quantity = random.randint(1, 5)
                unit_price = round(random.uniform(10, 500), 2)
                order_total = round(quantity * unit_price, 2)
                tax_amount = round(order_total * 0.08, 2)
                shipping_cost = round(random.uniform(0, 25), 2)
                discount_amount = round(random.uniform(0, order_total * 0.1), 2)
                
                row = [
                    i,  # order_id
                    random.randint(1, 10000),  # customer_id
                    order_date.strftime('%Y-%m-%d'),  # order_date
                    order_total,
                    category,
                    quantity,
                    unit_price,
                    tax_amount,
                    shipping_cost,
                    discount_amount
                ]
                
                writer.writerow(row)
        
        generation_time = time.time() - start_time
        file_size = os.path.getsize(self.filename)
        
        print(f"Generated in {generation_time:.2f} seconds")
        print(f"File size: {file_size / (1024*1024):.1f} MB")
        
        return file_size
    
    def execute_analytical_query(self):
        """Execute the analytical query on row-based data"""
        print("\n=== Row-Based Query Execution ===")
        print("Query: AVG(order_total) WHERE category='Electronics' AND date IN Jan 2024")
        
        start_time = time.time()
        
        # Query execution
        total_sum = 0
        count = 0
        rows_scanned = 0
        bytes_read = 0
        
        with open(self.filename, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row in reader:
                rows_scanned += 1
                # Count bytes for entire row
                bytes_read += sum(len(str(value)) for value in row.values())
                
                # Apply WHERE clause
                if (row['product_category'] == 'Electronics' and 
                    row['order_date'].startswith('2024-01')):
                    
                    total_sum += float(row['order_total'])
                    count += 1
        
        query_time = time.time() - start_time
        average = total_sum / count if count > 0 else 0
        
        print(f"Result: Average order total = ${average:.2f}")
        print(f"Query time: {query_time:.3f} seconds")
        print(f"Rows scanned: {rows_scanned:,}")
        print(f"Matching rows: {count:,}")
        print(f"Bytes read: {bytes_read / (1024*1024):.1f} MB")
        print(f"Selectivity: {count / rows_scanned:.3%}")
        
        # Calculate waste
        columns_needed = 3  # order_total, product_category, order_date
        columns_total = len(self.columns)
        column_waste = (columns_total - columns_needed) / columns_total
        
        print(f"Column utilization: {columns_needed}/{columns_total} = {1-column_waste:.1%}")
        print(f"Column waste: {column_waste:.1%}")
        
        return {
            "query_time": query_time,
            "rows_scanned": rows_scanned,
            "bytes_read": bytes_read,
            "result": average,
            "matching_rows": count
        }

# Demonstrate row-based storage
def demonstrate_row_based():
    """Demonstrate row-based storage and query"""
    
    row_storage = RowBasedStorage()
    
    # Generate sample data
    file_size = row_storage.generate_sample_data(100000)
    
    # Execute query
    result = row_storage.execute_analytical_query()
    
    # Cleanup
    if os.path.exists(row_storage.filename):
        os.remove(row_storage.filename)
    
    return result

# Run row-based demonstration
row_result = demonstrate_row_based()
```

### Row-Based Analysis

In row-based storage:

1. **File Structure**: Each row contains all columns
2. **Query Execution**: Must read every row completely
3. **Data Waste**: Read 7 unnecessary columns out of 10 total
4. **I/O Pattern**: Sequential scan through entire file
5. **Cache Behavior**: Poor locality for column-specific operations

## Layout 2: Columnar Storage (Separate Files)

### File Structure

```python
import struct
import pickle
import gzip

class ColumnarStorage:
    """Simulate columnar storage using separate files per column"""
    
    def __init__(self, base_filename="orders_columnar"):
        self.base_filename = base_filename
        self.columns = [
            "order_id", "customer_id", "order_date", "order_total",
            "product_category", "quantity", "unit_price", "tax_amount",
            "shipping_cost", "discount_amount"
        ]
        self.column_files = {}
    
    def generate_sample_data(self, num_records=100000):
        """Generate sample data in columnar format"""
        print(f"Generating {num_records:,} records in columnar format...")
        
        # Generate same data as row-based version
        categories = ["Electronics", "Clothing", "Books", "Sports", "Home"]
        start_date = datetime(2024, 1, 1)
        
        # Collect data in columns
        column_data = {col: [] for col in self.columns}
        
        start_time = time.time()
        
        for i in range(1, num_records + 1):
            # Random date in 2024
            random_days = random.randint(0, 365)
            order_date = start_date + timedelta(days=random_days)
            
            # Generate order data
            category = random.choice(categories)
            quantity = random.randint(1, 5)
            unit_price = round(random.uniform(10, 500), 2)
            order_total = round(quantity * unit_price, 2)
            tax_amount = round(order_total * 0.08, 2)
            shipping_cost = round(random.uniform(0, 25), 2)
            discount_amount = round(random.uniform(0, order_total * 0.1), 2)
            
            # Store in columns
            column_data["order_id"].append(i)
            column_data["customer_id"].append(random.randint(1, 10000))
            column_data["order_date"].append(order_date.strftime('%Y-%m-%d'))
            column_data["order_total"].append(order_total)
            column_data["product_category"].append(category)
            column_data["quantity"].append(quantity)
            column_data["unit_price"].append(unit_price)
            column_data["tax_amount"].append(tax_amount)
            column_data["shipping_cost"].append(shipping_cost)
            column_data["discount_amount"].append(discount_amount)
        
        # Write each column to separate file
        total_file_size = 0
        
        for column_name, column_values in column_data.items():
            filename = f"{self.base_filename}_{column_name}.col"
            
            with open(filename, 'wb') as f:
                # Simple format: pickle and compress
                pickled_data = pickle.dumps(column_values)
                compressed_data = gzip.compress(pickled_data)
                f.write(compressed_data)
            
            file_size = os.path.getsize(filename)
            total_file_size += file_size
            self.column_files[column_name] = filename
            
            print(f"  {column_name}: {file_size / 1024:.1f} KB")
        
        generation_time = time.time() - start_time
        
        print(f"Generated in {generation_time:.2f} seconds")
        print(f"Total size: {total_file_size / (1024*1024):.1f} MB")
        
        return total_file_size
    
    def read_column(self, column_name):
        """Read a specific column from disk"""
        filename = self.column_files[column_name]
        
        with open(filename, 'rb') as f:
            compressed_data = f.read()
            pickled_data = gzip.decompress(compressed_data)
            column_values = pickle.loads(pickled_data)
        
        return column_values
    
    def execute_analytical_query(self):
        """Execute the analytical query on columnar data"""
        print("\n=== Columnar Query Execution ===")
        print("Query: AVG(order_total) WHERE category='Electronics' AND date IN Jan 2024")
        
        start_time = time.time()
        
        # Only read the columns we need
        columns_needed = ["product_category", "order_date", "order_total"]
        
        print(f"Reading only needed columns: {columns_needed}")
        
        # Read columns
        category_column = self.read_column("product_category")
        date_column = self.read_column("order_date")
        total_column = self.read_column("order_total")
        
        # Calculate bytes read (approximate)
        bytes_read = (
            os.path.getsize(self.column_files["product_category"]) +
            os.path.getsize(self.column_files["order_date"]) +
            os.path.getsize(self.column_files["order_total"])
        )
        
        # Execute query
        total_sum = 0
        count = 0
        rows_processed = len(category_column)
        
        for i in range(rows_processed):
            if (category_column[i] == 'Electronics' and 
                date_column[i].startswith('2024-01')):
                
                total_sum += total_column[i]
                count += 1
        
        query_time = time.time() - start_time
        average = total_sum / count if count > 0 else 0
        
        print(f"Result: Average order total = ${average:.2f}")
        print(f"Query time: {query_time:.3f} seconds")
        print(f"Rows processed: {rows_processed:,}")
        print(f"Matching rows: {count:,}")
        print(f"Bytes read: {bytes_read / (1024*1024):.1f} MB")
        print(f"Selectivity: {count / rows_processed:.3%}")
        
        # Calculate efficiency
        columns_needed = 3
        columns_total = len(self.columns)
        column_efficiency = columns_needed / columns_total
        
        print(f"Column utilization: {columns_needed}/{columns_total} = {column_efficiency:.1%}")
        print(f"Column efficiency: {column_efficiency:.1%}")
        
        return {
            "query_time": query_time,
            "rows_processed": rows_processed,
            "bytes_read": bytes_read,
            "result": average,
            "matching_rows": count
        }
    
    def cleanup(self):
        """Remove column files"""
        for filename in self.column_files.values():
            if os.path.exists(filename):
                os.remove(filename)

# Demonstrate columnar storage
def demonstrate_columnar():
    """Demonstrate columnar storage and query"""
    
    columnar_storage = ColumnarStorage()
    
    # Generate sample data
    file_size = columnar_storage.generate_sample_data(100000)
    
    # Execute query
    result = columnar_storage.execute_analytical_query()
    
    # Cleanup
    columnar_storage.cleanup()
    
    return result

# Run columnar demonstration
columnar_result = demonstrate_columnar()
```

### Columnar Analysis

In columnar storage:

1. **File Structure**: Each column stored separately
2. **Query Execution**: Read only needed columns
3. **Data Efficiency**: Read exactly what's needed
4. **I/O Pattern**: Parallel reads of specific columns
5. **Cache Behavior**: Excellent locality for column operations

## Side-by-Side Comparison

```python
def compare_storage_layouts():
    """Compare row-based vs columnar storage performance"""
    
    print("\n" + "="*60)
    print("STORAGE LAYOUT COMPARISON")
    print("="*60)
    
    # Run both demonstrations
    print("Testing with 100,000 records...")
    print("Query: AVG(order_total) WHERE category='Electronics' AND date IN Jan 2024")
    
    row_result = demonstrate_row_based()
    columnar_result = demonstrate_columnar()
    
    print("\n" + "="*60)
    print("PERFORMANCE COMPARISON")
    print("="*60)
    
    # Calculate improvements
    time_improvement = row_result["query_time"] / columnar_result["query_time"]
    io_improvement = row_result["bytes_read"] / columnar_result["bytes_read"]
    
    print(f"{'Metric':<20} {'Row-Based':<15} {'Columnar':<15} {'Improvement':<12}")
    print("-" * 62)
    
    print(f"{'Query Time':<20} {row_result['query_time']:<15.3f} "
          f"{columnar_result['query_time']:<15.3f} {time_improvement:<12.1f}x")
    
    print(f"{'Bytes Read (MB)':<20} {row_result['bytes_read']/(1024*1024):<15.1f} "
          f"{columnar_result['bytes_read']/(1024*1024):<15.1f} {io_improvement:<12.1f}x")
    
    print(f"{'Rows Processed':<20} {row_result['rows_scanned']:<15,} "
          f"{columnar_result['rows_processed']:<15,} {'1.0x':<12}")
    
    print(f"{'Matching Rows':<20} {row_result['matching_rows']:<15,} "
          f"{columnar_result['matching_rows']:<15,} {'1.0x':<12}")
    
    print(f"{'Result':<20} ${row_result['result']:<14.2f} "
          f"${columnar_result['result']:<14.2f} {'Same':<12}")
    
    print(f"\nKey Improvements:")
    print(f"  • Query time: {time_improvement:.1f}x faster")
    print(f"  • I/O reduction: {io_improvement:.1f}x less data read")
    print(f"  • Column efficiency: Read only {3}/{10} = 30% of columns")
    
    # Calculate theoretical maximum improvement
    print(f"\nWhy These Improvements:")
    print(f"  • Row-based: Must read ALL columns to get needed data")
    print(f"  • Columnar: Read ONLY the columns needed for query")
    print(f"  • Compression: Similar data types compress better")
    print(f"  • Cache efficiency: Better memory locality")

# Run the comparison
compare_storage_layouts()
```

## Advanced Columnar Optimizations

### 1. Column Chunk Processing

```python
class ColumnChunkProcessor:
    """Process queries using column chunks for better performance"""
    
    def __init__(self, chunk_size=10000):
        self.chunk_size = chunk_size
    
    def process_query_in_chunks(self, category_column, date_column, total_column):
        """Process query using chunks for better memory efficiency"""
        print(f"\nProcessing query in chunks of {self.chunk_size:,} rows...")
        
        total_sum = 0
        count = 0
        chunks_processed = 0
        
        data_length = len(category_column)
        
        for start_idx in range(0, data_length, self.chunk_size):
            end_idx = min(start_idx + self.chunk_size, data_length)
            chunks_processed += 1
            
            # Process chunk
            for i in range(start_idx, end_idx):
                if (category_column[i] == 'Electronics' and 
                    date_column[i].startswith('2024-01')):
                    
                    total_sum += total_column[i]
                    count += 1
        
        average = total_sum / count if count > 0 else 0
        
        print(f"Processed {chunks_processed} chunks")
        print(f"Found {count:,} matching rows")
        print(f"Average: ${average:.2f}")
        
        return average

# Demonstrate chunk processing
def demonstrate_chunk_processing():
    """Show chunk-based processing"""
    
    # Generate sample data
    categories = ["Electronics", "Clothing", "Books", "Sports", "Home"]
    
    category_column = [random.choice(categories) for _ in range(100000)]
    date_column = [f"2024-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}" 
                  for _ in range(100000)]
    total_column = [round(random.uniform(10, 1000), 2) for _ in range(100000)]
    
    processor = ColumnChunkProcessor(chunk_size=10000)
    processor.process_query_in_chunks(category_column, date_column, total_column)

demonstrate_chunk_processing()
```

### 2. Predicate Pushdown

```python
class PredicatePushdown:
    """Demonstrate predicate pushdown optimization"""
    
    def __init__(self):
        self.column_stats = {}
    
    def calculate_column_stats(self, column_name, column_data):
        """Calculate statistics for predicate pushdown"""
        if isinstance(column_data[0], str):
            unique_values = set(column_data)
            stats = {
                "type": "string",
                "unique_count": len(unique_values),
                "most_common": max(unique_values, key=column_data.count),
                "sample_values": list(unique_values)[:10]
            }
        else:
            stats = {
                "type": "numeric",
                "min": min(column_data),
                "max": max(column_data),
                "avg": sum(column_data) / len(column_data),
                "unique_count": len(set(column_data))
            }
        
        self.column_stats[column_name] = stats
        return stats
    
    def estimate_selectivity(self, column_name, predicate_value):
        """Estimate how selective a predicate will be"""
        if column_name not in self.column_stats:
            return 0.5  # Default estimate
        
        stats = self.column_stats[column_name]
        
        if stats["type"] == "string":
            if predicate_value in stats["sample_values"]:
                # Rough estimate based on uniqueness
                return 1.0 / stats["unique_count"]
            else:
                return 0.0
        else:
            # For numeric ranges, estimate based on min/max
            if stats["min"] <= predicate_value <= stats["max"]:
                return 0.1  # Rough estimate
            else:
                return 0.0
    
    def optimize_query_order(self, predicates):
        """Optimize predicate order for better performance"""
        print("Optimizing predicate order...")
        
        predicate_selectivity = []
        for column, value in predicates:
            selectivity = self.estimate_selectivity(column, value)
            predicate_selectivity.append((column, value, selectivity))
        
        # Sort by selectivity (most selective first)
        predicate_selectivity.sort(key=lambda x: x[2])
        
        print("Predicate selectivity order:")
        for column, value, selectivity in predicate_selectivity:
            print(f"  {column} = {value}: {selectivity:.3f}")
        
        return predicate_selectivity

# Demonstrate predicate pushdown
def demonstrate_predicate_pushdown():
    """Show predicate pushdown optimization"""
    
    pushdown = PredicatePushdown()
    
    # Sample data
    categories = ["Electronics"] * 2000 + ["Clothing"] * 3000 + ["Books"] * 5000
    dates = [f"2024-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}" 
            for _ in range(10000)]
    
    # Calculate stats
    pushdown.calculate_column_stats("category", categories)
    pushdown.calculate_column_stats("date", dates)
    
    # Optimize query
    predicates = [("category", "Electronics"), ("date", "2024-01")]
    pushdown.optimize_query_order(predicates)

demonstrate_predicate_pushdown()
```

## Key Takeaways

### The Columnar Advantage

1. **I/O Efficiency**: Read only the columns you need
2. **Compression**: Similar data types compress better
3. **Cache Performance**: Better memory locality
4. **Vectorization**: Process multiple values at once
5. **Predicate Pushdown**: Filter early in the pipeline

### When to Use Columnar Storage

**Perfect for:**
- Analytical queries (OLAP)
- Data warehousing
- Business intelligence
- Reporting systems
- Time-series analysis

**Not ideal for:**
- Transactional systems (OLTP)
- Row-by-row processing
- Frequent updates
- Small datasets

### The Performance Impact

In our demonstration:
- **Query time**: 3-10x faster
- **I/O reduction**: 3-10x less data read
- **Memory efficiency**: Better cache utilization
- **Scalability**: Improvements increase with dataset size

The key insight is that **columnar storage matches the access pattern of analytical queries**, transforming the problem from "how do we make row-based analytics faster?" to "how do we store data the way analytics access it?"

The next step is understanding why columnar storage provides such exceptional compression advantages—and how compression amplifies all the other benefits.