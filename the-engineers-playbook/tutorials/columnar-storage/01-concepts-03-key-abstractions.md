# Key Abstractions: Column Chunks and Compression

## The Two Core Abstractions

Columnar storage is built on two fundamental abstractions that enable its performance advantages:

1. **Column Chunk**: A contiguous block of values from a single column
2. **Compression Scheme**: The method used to encode column chunks efficiently

These abstractions work together to create the foundation for high-performance analytical processing.

## The Column Chunk Abstraction

### What is a Column Chunk?

A column chunk is a contiguous block of values from a single column, typically containing thousands to millions of values. It's the fundamental storage unit in columnar systems.

```python
class ColumnChunk:
    """Represents a chunk of column data"""
    
    def __init__(self, column_name, data_type, values):
        self.column_name = column_name
        self.data_type = data_type
        self.values = values
        self.size = len(values)
        self.chunk_metadata = self._calculate_metadata()
    
    def _calculate_metadata(self):
        """Calculate metadata for the chunk"""
        if not self.values:
            return {}
        
        metadata = {
            "count": len(self.values),
            "null_count": sum(1 for v in self.values if v is None),
            "size_bytes": self._estimate_size(),
        }
        
        # Type-specific metadata
        if self.data_type in ["int", "float"]:
            numeric_values = [v for v in self.values if v is not None]
            if numeric_values:
                metadata.update({
                    "min_value": min(numeric_values),
                    "max_value": max(numeric_values),
                    "sum": sum(numeric_values),
                    "average": sum(numeric_values) / len(numeric_values)
                })
        elif self.data_type == "string":
            non_null_values = [v for v in self.values if v is not None]
            if non_null_values:
                metadata.update({
                    "min_length": min(len(v) for v in non_null_values),
                    "max_length": max(len(v) for v in non_null_values),
                    "unique_count": len(set(non_null_values)),
                    "most_frequent": self._find_most_frequent(non_null_values)
                })
        
        return metadata
    
    def _estimate_size(self):
        """Estimate size in bytes"""
        if self.data_type == "int":
            return len(self.values) * 8  # 64-bit integers
        elif self.data_type == "float":
            return len(self.values) * 8  # 64-bit floats
        elif self.data_type == "string":
            return sum(len(str(v)) for v in self.values if v is not None)
        else:
            return len(self.values) * 8  # Default estimate
    
    def _find_most_frequent(self, values):
        """Find most frequent value"""
        from collections import Counter
        return Counter(values).most_common(1)[0] if values else None
    
    def get_value(self, index):
        """Get value at specific index"""
        if 0 <= index < len(self.values):
            return self.values[index]
        return None
    
    def get_range(self, start, end):
        """Get range of values"""
        return self.values[start:end]
    
    def filter_values(self, predicate):
        """Filter values based on predicate"""
        return [v for v in self.values if predicate(v)]
    
    def aggregate(self, operation):
        """Perform aggregation operation"""
        non_null_values = [v for v in self.values if v is not None]
        
        if not non_null_values:
            return None
        
        if operation == "sum":
            return sum(non_null_values)
        elif operation == "avg":
            return sum(non_null_values) / len(non_null_values)
        elif operation == "min":
            return min(non_null_values)
        elif operation == "max":
            return max(non_null_values)
        elif operation == "count":
            return len(non_null_values)
        else:
            raise ValueError(f"Unknown operation: {operation}")
    
    def __str__(self):
        return f"ColumnChunk({self.column_name}, {self.data_type}, {self.size} values)"

# Demonstrate column chunk
def demonstrate_column_chunk():
    """Show column chunk characteristics"""
    
    # Create sample column chunks
    order_id_chunk = ColumnChunk("order_id", "int", list(range(1, 1001)))
    
    order_total_chunk = ColumnChunk("order_total", "float", 
                                   [round(50 + i * 0.99, 2) for i in range(1000)])
    
    category_chunk = ColumnChunk("category", "string", 
                               ["Electronics", "Clothing", "Books", "Sports", "Home"] * 200)
    
    chunks = [order_id_chunk, order_total_chunk, category_chunk]
    
    print("Column Chunk Demonstration:")
    print("=" * 40)
    
    for chunk in chunks:
        print(f"\n{chunk}")
        print(f"  Metadata: {chunk.chunk_metadata}")
        
        # Show sample operations
        if chunk.data_type in ["int", "float"]:
            print(f"  Sum: {chunk.aggregate('sum')}")
            print(f"  Average: {chunk.aggregate('avg'):.2f}")
            print(f"  Min: {chunk.aggregate('min')}")
            print(f"  Max: {chunk.aggregate('max')}")
        elif chunk.data_type == "string":
            print(f"  Unique values: {chunk.chunk_metadata['unique_count']}")
            print(f"  Most frequent: {chunk.chunk_metadata['most_frequent']}")

demonstrate_column_chunk()
```

### Column Chunk Benefits

Column chunks provide several key benefits:

1. **Efficient Scanning**: Process thousands of values in a tight loop
2. **Metadata Acceleration**: Skip chunks that don't match query predicates
3. **Vectorized Processing**: Apply operations to entire chunks at once
4. **Compression Efficiency**: Similar values compress better together
5. **Memory Locality**: Contiguous memory layout improves cache performance

## The Compression Abstraction

### Why Compression is Critical

Compression in columnar storage isn't just about saving space—it's about performance. Better compression means:
- Less I/O (fewer bytes to read from disk)
- Better cache utilization (more data fits in memory)
- Faster query processing (less data to process)

### Common Compression Schemes

```python
import struct
import gzip
from collections import Counter
from typing import List, Any, Tuple

class CompressionScheme:
    """Base class for compression schemes"""
    
    def encode(self, values: List[Any]) -> bytes:
        """Encode values to compressed bytes"""
        raise NotImplementedError
    
    def decode(self, compressed_data: bytes) -> List[Any]:
        """Decode compressed bytes to values"""
        raise NotImplementedError
    
    def compression_ratio(self, original_size: int, compressed_size: int) -> float:
        """Calculate compression ratio"""
        return original_size / compressed_size if compressed_size > 0 else 0

class RunLengthEncoding(CompressionScheme):
    """Run-length encoding for repeated values"""
    
    def encode(self, values: List[Any]) -> bytes:
        """Encode using run-length encoding"""
        if not values:
            return b''
        
        runs = []
        current_value = values[0]
        current_count = 1
        
        for value in values[1:]:
            if value == current_value:
                current_count += 1
            else:
                runs.append((current_value, current_count))
                current_value = value
                current_count = 1
        
        runs.append((current_value, current_count))
        
        # Serialize runs
        result = []
        for value, count in runs:
            if isinstance(value, str):
                value_bytes = value.encode('utf-8')
                result.append(struct.pack('I', len(value_bytes)))
                result.append(value_bytes)
            else:
                result.append(struct.pack('d', float(value)))
            result.append(struct.pack('I', count))
        
        return b''.join(result)
    
    def decode(self, compressed_data: bytes) -> List[Any]:
        """Decode run-length encoded data"""
        if not compressed_data:
            return []
        
        values = []
        offset = 0
        
        while offset < len(compressed_data):
            # Read value (assuming float for simplicity)
            value = struct.unpack('d', compressed_data[offset:offset+8])[0]
            offset += 8
            
            # Read count
            count = struct.unpack('I', compressed_data[offset:offset+4])[0]
            offset += 4
            
            values.extend([value] * count)
        
        return values

class DictionaryEncoding(CompressionScheme):
    """Dictionary encoding for low-cardinality data"""
    
    def encode(self, values: List[Any]) -> bytes:
        """Encode using dictionary compression"""
        if not values:
            return b''
        
        # Build dictionary
        unique_values = list(set(values))
        value_to_id = {value: i for i, value in enumerate(unique_values)}
        
        # Encode dictionary
        dictionary_bytes = []
        for value in unique_values:
            if isinstance(value, str):
                value_bytes = value.encode('utf-8')
                dictionary_bytes.append(struct.pack('I', len(value_bytes)))
                dictionary_bytes.append(value_bytes)
            else:
                dictionary_bytes.append(struct.pack('d', float(value)))
        
        # Encode values as dictionary IDs
        encoded_values = [value_to_id[value] for value in values]
        
        # Determine ID size based on dictionary size
        if len(unique_values) <= 256:
            id_format = 'B'  # 1 byte
            id_size = 1
        elif len(unique_values) <= 65536:
            id_format = 'H'  # 2 bytes
            id_size = 2
        else:
            id_format = 'I'  # 4 bytes
            id_size = 4
        
        # Serialize
        result = []
        result.append(struct.pack('I', len(unique_values)))  # Dictionary size
        result.append(struct.pack('B', id_size))  # ID size
        result.extend(dictionary_bytes)
        
        for value_id in encoded_values:
            result.append(struct.pack(id_format, value_id))
        
        return b''.join(result)
    
    def decode(self, compressed_data: bytes) -> List[Any]:
        """Decode dictionary compressed data"""
        if not compressed_data:
            return []
        
        offset = 0
        
        # Read dictionary size
        dict_size = struct.unpack('I', compressed_data[offset:offset+4])[0]
        offset += 4
        
        # Read ID size
        id_size = struct.unpack('B', compressed_data[offset:offset+1])[0]
        offset += 1
        
        # Read dictionary (simplified - assumes float values)
        dictionary = []
        for _ in range(dict_size):
            value = struct.unpack('d', compressed_data[offset:offset+8])[0]
            offset += 8
            dictionary.append(value)
        
        # Read encoded values
        values = []
        id_format = {1: 'B', 2: 'H', 4: 'I'}[id_size]
        
        while offset < len(compressed_data):
            value_id = struct.unpack(id_format, compressed_data[offset:offset+id_size])[0]
            offset += id_size
            values.append(dictionary[value_id])
        
        return values

class DeltaEncoding(CompressionScheme):
    """Delta encoding for sequential data"""
    
    def encode(self, values: List[Any]) -> bytes:
        """Encode using delta compression"""
        if not values:
            return b''
        
        # Convert to numbers and calculate deltas
        numeric_values = [float(v) for v in values]
        deltas = [numeric_values[0]]  # First value as-is
        
        for i in range(1, len(numeric_values)):
            delta = numeric_values[i] - numeric_values[i-1]
            deltas.append(delta)
        
        # Serialize deltas
        result = []
        for delta in deltas:
            result.append(struct.pack('d', delta))
        
        return b''.join(result)
    
    def decode(self, compressed_data: bytes) -> List[Any]:
        """Decode delta compressed data"""
        if not compressed_data:
            return []
        
        # Read deltas
        deltas = []
        offset = 0
        while offset < len(compressed_data):
            delta = struct.unpack('d', compressed_data[offset:offset+8])[0]
            deltas.append(delta)
            offset += 8
        
        # Reconstruct values
        values = [deltas[0]]
        for i in range(1, len(deltas)):
            values.append(values[-1] + deltas[i])
        
        return values

class GeneralCompression(CompressionScheme):
    """General-purpose compression using gzip"""
    
    def encode(self, values: List[Any]) -> bytes:
        """Encode using general compression"""
        import pickle
        serialized = pickle.dumps(values)
        return gzip.compress(serialized)
    
    def decode(self, compressed_data: bytes) -> List[Any]:
        """Decode general compressed data"""
        import pickle
        decompressed = gzip.decompress(compressed_data)
        return pickle.loads(decompressed)

# Demonstrate compression schemes
def demonstrate_compression_schemes():
    """Show different compression schemes in action"""
    
    print("Compression Schemes Demonstration:")
    print("=" * 50)
    
    # Test data with different characteristics
    test_datasets = {
        "Sequential IDs": list(range(1, 1001)),
        "Repeated Categories": ["Electronics"] * 300 + ["Clothing"] * 200 + ["Books"] * 500,
        "Sequential Timestamps": [1609459200 + i * 86400 for i in range(365)],  # Daily for a year
        "Random Prices": [round(50 + i * 0.99, 2) for i in range(1000)]
    }
    
    compression_schemes = {
        "Run-Length": RunLengthEncoding(),
        "Dictionary": DictionaryEncoding(),
        "Delta": DeltaEncoding(),
        "General": GeneralCompression()
    }
    
    for data_name, data in test_datasets.items():
        print(f"\n{data_name} (sample: {data[:5]}...):")
        
        # Calculate original size
        import pickle
        original_size = len(pickle.dumps(data))
        
        best_scheme = None
        best_ratio = 0
        
        for scheme_name, scheme in compression_schemes.items():
            try:
                compressed = scheme.encode(data)
                compressed_size = len(compressed)
                ratio = scheme.compression_ratio(original_size, compressed_size)
                
                # Verify correctness
                decoded = scheme.decode(compressed)
                correct = decoded == data
                
                status = "✓" if correct else "✗"
                print(f"  {scheme_name:12}: {compressed_size:6} bytes, {ratio:5.2f}x {status}")
                
                if correct and ratio > best_ratio:
                    best_ratio = ratio
                    best_scheme = scheme_name
            except Exception as e:
                print(f"  {scheme_name:12}: Error - {e}")
        
        print(f"  Best scheme: {best_scheme} ({best_ratio:.2f}x)")

demonstrate_compression_schemes()
```

## The Phone Book Analogy Revisited

### Traditional Phone Book (Row-Based)

```
Page 1: Adams, John     | 123 Main St    | 555-1234 | Plumber
        Adams, Mary     | 456 Oak Ave    | 555-5678 | Teacher
        ...
```

**Characteristics:**
- Each page contains complete records
- Good for: "Get all info for John Adams"
- Bad for: "List all plumbers"

### The Columnar Phone Book (Column-Based)

```
Names Volume:     | Addresses Volume:  | Phone Volume:    | Occupation Volume:
Adams, John       | 123 Main St        | 555-1234         | Plumber
Adams, Mary       | 456 Oak Ave        | 555-5678         | Teacher
Brown, Bob        | 789 Pine Rd        | 555-9012         | Doctor
Brown, Jane       | 321 Elm St         | 555-3456         | Lawyer
```

**Characteristics:**
- Each volume contains one type of information
- Good for: "List all plumbers" (only need Occupation Volume)
- Bad for: "Get all info for John Adams" (need all volumes)

### The Compression Advantage

In the columnar phone book:

**Names Volume** compresses well because:
- All entries are names (similar format)
- Common prefixes (Adams, Brown)
- Alphabetical order enables delta compression

**Addresses Volume** compresses well because:
- All entries are addresses (similar format)
- Common street names, city names
- Zip codes have locality patterns

**Phone Volume** compresses extremely well because:
- All entries are phone numbers (same format)
- Area codes repeat frequently
- Sequential number patterns

**Occupation Volume** compresses exceptionally well because:
- Very low cardinality (few unique values)
- Many repeated values
- Dictionary encoding is perfect

```python
class PhoneBookAnalogy:
    """Demonstrate the phone book analogy with compression"""
    
    def __init__(self):
        # Sample phone book data
        self.phone_book = [
            ("Adams, John", "123 Main St", "555-1234", "Plumber"),
            ("Adams, Mary", "456 Oak Ave", "555-5678", "Teacher"),
            ("Brown, Bob", "789 Pine Rd", "555-9012", "Doctor"),
            ("Brown, Jane", "321 Elm St", "555-3456", "Lawyer"),
            ("Davis, Tom", "159 Main St", "555-7890", "Plumber"),
            ("Davis, Sue", "753 Oak Ave", "555-2468", "Teacher"),
            ("Evans, Bill", "951 Pine Rd", "555-1357", "Doctor"),
            ("Evans, Lisa", "842 Elm St", "555-8642", "Plumber"),
        ]
    
    def analyze_row_based_query(self, query_type):
        """Analyze row-based query performance"""
        print(f"\nRow-Based Query: {query_type}")
        
        if query_type == "Get person details":
            # Need to scan rows to find specific person
            target = "Brown, Bob"
            rows_scanned = 0
            
            for row in self.phone_book:
                rows_scanned += 1
                if row[0] == target:
                    result = row
                    break
            
            print(f"  Rows scanned: {rows_scanned}")
            print(f"  Data read: {rows_scanned * 4} fields")
            print(f"  Result: {result}")
        
        elif query_type == "List all plumbers":
            # Must scan all rows, read all fields
            plumbers = []
            for row in self.phone_book:
                if row[3] == "Plumber":  # Occupation column
                    plumbers.append(row[0])  # Name column
            
            print(f"  Rows scanned: {len(self.phone_book)}")
            print(f"  Data read: {len(self.phone_book) * 4} fields")
            print(f"  Data needed: {len(self.phone_book) * 2} fields (name + occupation)")
            print(f"  Efficiency: {(len(self.phone_book) * 2) / (len(self.phone_book) * 4) * 100:.1f}%")
            print(f"  Result: {plumbers}")
    
    def analyze_columnar_query(self, query_type):
        """Analyze columnar query performance"""
        print(f"\nColumnar Query: {query_type}")
        
        # Extract columns
        names = [row[0] for row in self.phone_book]
        addresses = [row[1] for row in self.phone_book]
        phones = [row[2] for row in self.phone_book]
        occupations = [row[3] for row in self.phone_book]
        
        if query_type == "Get person details":
            # Need to find index in one column, then read from all columns
            target = "Brown, Bob"
            index = names.index(target)
            result = (names[index], addresses[index], phones[index], occupations[index])
            
            print(f"  Columns scanned: 1 (names)")
            print(f"  Data read: {len(names)} + 3 fields")
            print(f"  Result: {result}")
        
        elif query_type == "List all plumbers":
            # Only need to read occupation and name columns
            plumbers = []
            for i, occupation in enumerate(occupations):
                if occupation == "Plumber":
                    plumbers.append(names[i])
            
            print(f"  Columns read: 2 (names + occupations)")
            print(f"  Data read: {len(names) + len(occupations)} fields")
            print(f"  Data available: {len(self.phone_book) * 4} fields")
            print(f"  Efficiency: {(len(names) + len(occupations)) / (len(self.phone_book) * 4) * 100:.1f}%")
            print(f"  Result: {plumbers}")
    
    def demonstrate_compression_potential(self):
        """Show compression potential of each column"""
        print("\nCompression Analysis:")
        
        # Extract columns
        names = [row[0] for row in self.phone_book]
        addresses = [row[1] for row in self.phone_book]
        phones = [row[2] for row in self.phone_book]
        occupations = [row[3] for row in self.phone_book]
        
        columns = {
            "Names": names,
            "Addresses": addresses,
            "Phones": phones,
            "Occupations": occupations
        }
        
        for column_name, column_data in columns.items():
            unique_count = len(set(column_data))
            total_count = len(column_data)
            cardinality = unique_count / total_count
            
            print(f"\n{column_name}:")
            print(f"  Unique values: {unique_count}")
            print(f"  Total values: {total_count}")
            print(f"  Cardinality: {cardinality:.2f}")
            
            # Suggest best compression
            if cardinality < 0.1:
                print(f"  Best compression: Dictionary encoding")
            elif cardinality < 0.5:
                print(f"  Best compression: Run-length encoding")
            else:
                print(f"  Best compression: General compression")
    
    def compare_query_patterns(self):
        """Compare different query patterns"""
        print("Phone Book Query Pattern Analysis:")
        print("=" * 50)
        
        self.analyze_row_based_query("Get person details")
        self.analyze_columnar_query("Get person details")
        
        self.analyze_row_based_query("List all plumbers")
        self.analyze_columnar_query("List all plumbers")
        
        self.demonstrate_compression_potential()

# Demonstrate phone book analogy
analogy = PhoneBookAnalogy()
analogy.compare_query_patterns()
```

## Advanced Column Chunk Concepts

### Column Chunk Partitioning

```python
class ColumnChunkPartitioner:
    """Manage column chunks with smart partitioning"""
    
    def __init__(self, chunk_size=1000):
        self.chunk_size = chunk_size
        self.chunks = []
    
    def add_data(self, column_name, data_type, values):
        """Add data, creating chunks as needed"""
        for i in range(0, len(values), self.chunk_size):
            chunk_values = values[i:i + self.chunk_size]
            chunk = ColumnChunk(column_name, data_type, chunk_values)
            self.chunks.append(chunk)
    
    def query_with_predicate(self, column_name, predicate):
        """Query with predicate pushdown"""
        results = []
        chunks_scanned = 0
        chunks_skipped = 0
        
        for chunk in self.chunks:
            if chunk.column_name != column_name:
                continue
            
            # Check if chunk can be skipped using metadata
            if self._can_skip_chunk(chunk, predicate):
                chunks_skipped += 1
                continue
            
            chunks_scanned += 1
            # Scan chunk for matching values
            matching_values = chunk.filter_values(predicate)
            results.extend(matching_values)
        
        return {
            "results": results,
            "chunks_scanned": chunks_scanned,
            "chunks_skipped": chunks_skipped,
            "total_chunks": len([c for c in self.chunks if c.column_name == column_name])
        }
    
    def _can_skip_chunk(self, chunk, predicate):
        """Check if chunk can be skipped based on metadata"""
        metadata = chunk.chunk_metadata
        
        # For numeric comparisons, use min/max
        if chunk.data_type in ["int", "float"]:
            min_val = metadata.get("min_value")
            max_val = metadata.get("max_value")
            
            if min_val is not None and max_val is not None:
                # Test with sample values
                if not predicate(min_val) and not predicate(max_val):
                    # If both min and max fail, and predicate is monotonic, skip
                    return True
        
        return False

# Demonstrate chunk partitioning
def demonstrate_chunk_partitioning():
    """Show chunk partitioning and predicate pushdown"""
    
    partitioner = ColumnChunkPartitioner(chunk_size=100)
    
    # Add sample data
    order_totals = [round(10 + i * 0.5, 2) for i in range(1000)]
    partitioner.add_data("order_total", "float", order_totals)
    
    print("Column Chunk Partitioning Demonstration:")
    print("=" * 50)
    
    # Query with different predicates
    predicates = [
        ("order_total > 100", lambda x: x > 100),
        ("order_total > 500", lambda x: x > 500),
        ("order_total > 1000", lambda x: x > 1000),
    ]
    
    for predicate_name, predicate_func in predicates:
        print(f"\nQuery: {predicate_name}")
        result = partitioner.query_with_predicate("order_total", predicate_func)
        
        print(f"  Results found: {len(result['results'])}")
        print(f"  Chunks scanned: {result['chunks_scanned']}")
        print(f"  Chunks skipped: {result['chunks_skipped']}")
        print(f"  Total chunks: {result['total_chunks']}")
        print(f"  Efficiency: {result['chunks_skipped'] / result['total_chunks'] * 100:.1f}% chunks skipped")

demonstrate_chunk_partitioning()
```

## The Fundamental Insights

The key abstractions of columnar storage create a powerful foundation:

### Column Chunks Enable:
1. **Efficient Processing**: Tight loops over homogeneous data
2. **Metadata Acceleration**: Skip chunks that don't match queries
3. **Vectorized Operations**: Process multiple values simultaneously
4. **Cache Optimization**: Contiguous memory layout
5. **Parallel Processing**: Process chunks independently

### Compression Schemes Enable:
1. **I/O Reduction**: Less data to read from disk
2. **Memory Efficiency**: More data fits in cache
3. **Network Optimization**: Less data to transfer
4. **Storage Savings**: Reduced storage costs
5. **Processing Speed**: Less data to decompress and process

### The Synergy:
Column chunks and compression work together to create compound benefits:
- **Homogeneous data** in chunks compresses better
- **Compressed chunks** reduce I/O and improve cache efficiency
- **Metadata** enables skipping entire compressed chunks
- **Vectorized operations** work efficiently on decompressed chunks

The next step is seeing these abstractions in practice through a concrete example comparing row-based and columnar query execution.