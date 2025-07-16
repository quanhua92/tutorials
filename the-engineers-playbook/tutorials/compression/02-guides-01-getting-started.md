# Getting Started: Your First Compression Implementation

## The Practical Foundation

Let's start with the most practical approach: using a standard library to compress and decompress data. We'll use Python's `zlib` library to demonstrate the core concepts, then build up to implementing our own compression algorithms.

## Basic Compression with zlib

### Your First Compression

```python
import zlib
import sys
import time

def basic_compression_demo():
    """Demonstrate basic compression with zlib"""
    
    # Sample data to compress
    original_data = """
    Data compression is the process of encoding information using fewer bits than 
    the original representation. Compression is useful because it helps reduce 
    resource usage, such as data storage space or transmission capacity. Because 
    compressed data must be decompressed to be used, this extra processing imposes 
    computational or other costs through decompression; this situation is far from 
    a free lunch. Data compression is subject to a space–time complexity trade-off.
    """ * 10  # Repeat for better compression demonstration
    
    print("Basic Compression Demonstration:")
    print("=" * 50)
    
    # Original data info
    original_bytes = original_data.encode('utf-8')
    original_size = len(original_bytes)
    
    print(f"Original data size: {original_size:,} bytes")
    print(f"Original data preview: {original_data[:100]}...")
    
    # Compress the data
    start_time = time.time()
    compressed_data = zlib.compress(original_bytes)
    compression_time = time.time() - start_time
    
    compressed_size = len(compressed_data)
    compression_ratio = original_size / compressed_size
    
    print(f"\nCompression Results:")
    print(f"  Compressed size: {compressed_size:,} bytes")
    print(f"  Compression ratio: {compression_ratio:.2f}x")
    print(f"  Space saved: {original_size - compressed_size:,} bytes ({((original_size - compressed_size) / original_size) * 100:.1f}%)")
    print(f"  Compression time: {compression_time:.4f} seconds")
    
    # Decompress the data
    start_time = time.time()
    decompressed_data = zlib.decompress(compressed_data)
    decompression_time = time.time() - start_time
    
    decompressed_string = decompressed_data.decode('utf-8')
    
    print(f"\nDecompression Results:")
    print(f"  Decompressed size: {len(decompressed_data):,} bytes")
    print(f"  Decompression time: {decompression_time:.4f} seconds")
    print(f"  Data integrity: {'✓ Verified' if decompressed_string == original_data else '✗ Failed'}")
    
    # Show that decompressed data is identical
    if decompressed_string == original_data:
        print(f"  Perfect reconstruction confirmed!")
    else:
        print(f"  ⚠️  Data corruption detected!")
    
    return {
        "original_size": original_size,
        "compressed_size": compressed_size,
        "compression_ratio": compression_ratio,
        "compression_time": compression_time,
        "decompression_time": decompression_time
    }

# Run the basic demonstration
result = basic_compression_demo()
```

### Different Compression Levels

```python
def compression_levels_demo():
    """Demonstrate different compression levels"""
    
    # Create test data with varying redundancy
    test_data = {
        "Highly Redundant": "A" * 1000 + "B" * 1000 + "C" * 1000,
        "Moderately Redundant": "The quick brown fox jumps over the lazy dog. " * 100,
        "Structured Data": '{"name": "John", "age": 30, "city": "New York"}' * 200,
        "Natural Text": """
        In the beginning was the Word, and the Word was with God, and the Word was God.
        All things were made through him, and without him was not any thing made that was made.
        In him was life, and the life was the light of men. The light shines in the darkness,
        and the darkness has not overcome it.
        """ * 50,
        "Random-like Data": "".join(chr(ord('A') + (i * 7) % 26) for i in range(5000))
    }
    
    print("\nCompression Levels Analysis:")
    print("=" * 80)
    print(f"{'Data Type':<20} {'Level':<6} {'Original':<10} {'Compressed':<12} {'Ratio':<8} {'Time':<10}")
    print("-" * 80)
    
    for data_name, data in test_data.items():
        data_bytes = data.encode('utf-8')
        original_size = len(data_bytes)
        
        # Test different compression levels (0-9)
        for level in [1, 6, 9]:  # Fast, default, best
            start_time = time.time()
            compressed = zlib.compress(data_bytes, level)
            compression_time = time.time() - start_time
            
            compressed_size = len(compressed)
            ratio = original_size / compressed_size
            
            level_name = {1: "Fast", 6: "Default", 9: "Best"}[level]
            
            print(f"{data_name:<20} {level_name:<6} {original_size:<10} {compressed_size:<12} "
                  f"{ratio:<8.2f}x {compression_time:<10.4f}s")
        
        print()  # Empty line between data types

compression_levels_demo()
```

### Compression vs. Decompression Performance

```python
def performance_analysis():
    """Analyze compression vs decompression performance"""
    
    # Generate test data of different sizes
    test_sizes = [1024, 10240, 102400, 1024000]  # 1KB, 10KB, 100KB, 1MB
    
    print("Performance Analysis:")
    print("=" * 70)
    print(f"{'Size':<10} {'Compress':<12} {'Decompress':<12} {'Ratio':<8} {'Throughput':<15}")
    print("-" * 70)
    
    for size in test_sizes:
        # Create test data
        test_data = ("This is a test string for compression analysis. " * (size // 50))[:size]
        data_bytes = test_data.encode('utf-8')
        
        # Measure compression
        start_time = time.time()
        compressed = zlib.compress(data_bytes)
        compression_time = time.time() - start_time
        
        # Measure decompression
        start_time = time.time()
        decompressed = zlib.decompress(compressed)
        decompression_time = time.time() - start_time
        
        # Calculate metrics
        compression_ratio = len(data_bytes) / len(compressed)
        throughput = size / compression_time / 1024  # KB/s
        
        size_str = f"{size//1024}KB" if size >= 1024 else f"{size}B"
        
        print(f"{size_str:<10} {compression_time:<12.4f}s {decompression_time:<12.4f}s "
              f"{compression_ratio:<8.2f}x {throughput:<15.1f} KB/s")
    
    print(f"\nKey Observations:")
    print(f"  • Decompression is typically 3-10x faster than compression")
    print(f"  • Compression ratio depends heavily on data characteristics")
    print(f"  • Larger data sets often compress better (more patterns to exploit)")

performance_analysis()
```

## Building Your Own Simple Compression

### Run-Length Encoding Implementation

```python
class RunLengthEncoder:
    """Simple run-length encoding implementation"""
    
    def __init__(self):
        pass
    
    def encode(self, data):
        """Encode data using run-length encoding"""
        if not data:
            return ""
        
        encoded = []
        current_char = data[0]
        count = 1
        
        for char in data[1:]:
            if char == current_char and count < 255:  # Limit count to prevent overflow
                count += 1
            else:
                # Write the run
                if count > 1:
                    encoded.append(f"{current_char}{count}")
                else:
                    encoded.append(current_char)
                
                current_char = char
                count = 1
        
        # Handle the last run
        if count > 1:
            encoded.append(f"{current_char}{count}")
        else:
            encoded.append(current_char)
        
        return "".join(encoded)
    
    def decode(self, encoded_data):
        """Decode run-length encoded data"""
        if not encoded_data:
            return ""
        
        decoded = []
        i = 0
        
        while i < len(encoded_data):
            char = encoded_data[i]
            
            # Check if next characters form a number
            if i + 1 < len(encoded_data) and encoded_data[i + 1].isdigit():
                # Extract the count
                count_str = ""
                j = i + 1
                while j < len(encoded_data) and encoded_data[j].isdigit():
                    count_str += encoded_data[j]
                    j += 1
                
                count = int(count_str)
                decoded.append(char * count)
                i = j
            else:
                decoded.append(char)
                i += 1
        
        return "".join(decoded)
    
    def analyze_effectiveness(self, data):
        """Analyze how effective RLE is for given data"""
        encoded = self.encode(data)
        decoded = self.decode(encoded)
        
        # Verify correctness
        is_correct = decoded == data
        
        # Calculate metrics
        original_size = len(data)
        encoded_size = len(encoded)
        compression_ratio = original_size / encoded_size if encoded_size > 0 else 0
        
        return {
            "original_size": original_size,
            "encoded_size": encoded_size,
            "compression_ratio": compression_ratio,
            "is_correct": is_correct,
            "data_preview": data[:50] + "..." if len(data) > 50 else data,
            "encoded_preview": encoded[:50] + "..." if len(encoded) > 50 else encoded
        }

def demonstrate_run_length_encoding():
    """Demonstrate run-length encoding implementation"""
    
    rle = RunLengthEncoder()
    
    # Test data with different characteristics
    test_data = [
        ("High Repetition", "aaaaaaabbbbbbccccccddddddeeeeeee"),
        ("Medium Repetition", "aabbccddaabbccddaabbccdd"),
        ("Low Repetition", "abcdefghijklmnopqrstuvwxyz"),
        ("Mixed Content", "Hello, World!!! How are you??? Fine, thanks!!!"),
        ("Real Text", "The quick brown fox jumps over the lazy dog. " * 5)
    ]
    
    print("Run-Length Encoding Demonstration:")
    print("=" * 80)
    print(f"{'Data Type':<20} {'Original':<10} {'Encoded':<10} {'Ratio':<8} {'Correct':<8}")
    print("-" * 80)
    
    for name, data in test_data:
        result = rle.analyze_effectiveness(data)
        
        print(f"{name:<20} {result['original_size']:<10} {result['encoded_size']:<10} "
              f"{result['compression_ratio']:<8.2f}x {'✓' if result['is_correct'] else '✗':<8}")
    
    # Show detailed example
    print(f"\nDetailed Example (High Repetition):")
    detailed_result = rle.analyze_effectiveness("aaaaaaabbbbbbccccccddddddeeeeeee")
    print(f"  Original: {detailed_result['data_preview']}")
    print(f"  Encoded:  {detailed_result['encoded_preview']}")
    print(f"  Compression: {detailed_result['compression_ratio']:.2f}x")

demonstrate_run_length_encoding()
```

### Dictionary Compression Implementation

```python
class SimpleDictionaryCompressor:
    """Simple dictionary-based compression implementation"""
    
    def __init__(self):
        pass
    
    def build_dictionary(self, data, min_length=2, max_length=8):
        """Build a dictionary of repeated patterns"""
        from collections import Counter
        
        # Find all possible patterns
        patterns = []
        for length in range(min_length, min(max_length + 1, len(data) // 2)):
            for i in range(len(data) - length + 1):
                pattern = data[i:i+length]
                if len(pattern.strip()) > 0:  # Skip pure whitespace
                    patterns.append(pattern)
        
        # Count pattern frequencies
        pattern_counts = Counter(patterns)
        
        # Build dictionary for patterns that appear multiple times
        dictionary = {}
        code_counter = 0
        
        # Sort by savings potential (frequency * length)
        sorted_patterns = sorted(pattern_counts.items(), 
                               key=lambda x: x[1] * len(x[0]), 
                               reverse=True)
        
        for pattern, count in sorted_patterns:
            if count > 1:
                # Calculate potential savings
                original_cost = len(pattern) * count
                dictionary_cost = len(pattern) + 3  # Pattern + 3-char code
                code_cost = 3 * count  # 3-char code for each occurrence
                
                if original_cost > dictionary_cost + code_cost:
                    code = f"#{code_counter:02d}"
                    dictionary[pattern] = code
                    code_counter += 1
                    
                    # Limit dictionary size
                    if len(dictionary) >= 50:
                        break
        
        return dictionary
    
    def compress(self, data):
        """Compress data using dictionary approach"""
        
        # Build dictionary
        dictionary = self.build_dictionary(data)
        
        # Compress data by replacing patterns with codes
        compressed = data
        for pattern, code in dictionary.items():
            compressed = compressed.replace(pattern, code)
        
        return compressed, dictionary
    
    def decompress(self, compressed_data, dictionary):
        """Decompress data using dictionary"""
        
        decompressed = compressed_data
        
        # Replace codes with original patterns
        for pattern, code in dictionary.items():
            decompressed = decompressed.replace(code, pattern)
        
        return decompressed
    
    def analyze_compression(self, data):
        """Analyze compression effectiveness"""
        
        # Compress the data
        compressed, dictionary = self.compress(data)
        
        # Decompress to verify
        decompressed = self.decompress(compressed, dictionary)
        
        # Calculate sizes
        original_size = len(data)
        compressed_size = len(compressed)
        dictionary_size = sum(len(pattern) + len(code) for pattern, code in dictionary.items())
        total_size = compressed_size + dictionary_size
        
        # Calculate metrics
        compression_ratio = original_size / total_size if total_size > 0 else 0
        is_correct = decompressed == data
        
        return {
            "original_size": original_size,
            "compressed_size": compressed_size,
            "dictionary_size": dictionary_size,
            "total_size": total_size,
            "compression_ratio": compression_ratio,
            "dictionary_entries": len(dictionary),
            "is_correct": is_correct,
            "dictionary": dictionary
        }

def demonstrate_dictionary_compression():
    """Demonstrate dictionary compression implementation"""
    
    compressor = SimpleDictionaryCompressor()
    
    # Test data with different repetition patterns
    test_data = [
        ("Repeated Phrases", "The quick brown fox jumps over the lazy dog. " * 10),
        ("Code Structure", "function test() { return 42; } function main() { return test(); }" * 5),
        ("JSON Data", '{"name": "John", "age": 30, "city": "New York"}' * 15),
        ("HTML Content", "<div class='container'><p>Hello World</p></div>" * 8),
        ("Natural Text", """
        Data compression is a fundamental concept in computer science. 
        Data compression reduces the size of data. Data compression algorithms 
        exploit redundancy in data. Data compression can be lossless or lossy.
        """ * 3)
    ]
    
    print("\nDictionary Compression Demonstration:")
    print("=" * 90)
    print(f"{'Data Type':<20} {'Original':<10} {'Compressed':<12} {'Dictionary':<12} {'Ratio':<8} {'Entries':<8}")
    print("-" * 90)
    
    for name, data in test_data:
        result = compressor.analyze_compression(data)
        
        print(f"{name:<20} {result['original_size']:<10} {result['compressed_size']:<12} "
              f"{result['dictionary_size']:<12} {result['compression_ratio']:<8.2f}x "
              f"{result['dictionary_entries']:<8}")
    
    # Show detailed example
    print(f"\nDetailed Example (Repeated Phrases):")
    detailed_data = "The quick brown fox jumps over the lazy dog. " * 3
    detailed_result = compressor.analyze_compression(detailed_data)
    
    print(f"  Original size: {detailed_result['original_size']} characters")
    print(f"  Compressed size: {detailed_result['compressed_size']} characters")
    print(f"  Dictionary size: {detailed_result['dictionary_size']} characters")
    print(f"  Total size: {detailed_result['total_size']} characters")
    print(f"  Compression ratio: {detailed_result['compression_ratio']:.2f}x")
    print(f"  Dictionary entries: {detailed_result['dictionary_entries']}")
    
    print(f"\n  Dictionary contents:")
    for pattern, code in list(detailed_result['dictionary'].items())[:5]:
        print(f"    '{pattern}' → '{code}'")

demonstrate_dictionary_compression()
```

### Frequency-Based Compression

```python
class FrequencyCompressor:
    """Simple frequency-based compression (Huffman-like)"""
    
    def __init__(self):
        pass
    
    def build_frequency_table(self, data):
        """Build frequency table for characters"""
        from collections import Counter
        
        freq_table = Counter(data)
        
        # Sort by frequency (most frequent first)
        sorted_chars = sorted(freq_table.items(), key=lambda x: x[1], reverse=True)
        
        return dict(sorted_chars)
    
    def build_code_table(self, frequency_table):
        """Build variable-length codes based on frequency"""
        
        code_table = {}
        
        # Assign shorter codes to more frequent characters
        sorted_chars = list(frequency_table.keys())
        
        for i, char in enumerate(sorted_chars):
            # Simple variable-length encoding
            if i == 0:
                code_table[char] = "0"
            elif i == 1:
                code_table[char] = "10"
            elif i == 2:
                code_table[char] = "110"
            elif i == 3:
                code_table[char] = "1110"
            else:
                # For less frequent characters, use longer codes
                code_length = 4 + (i - 4) // 8
                code_table[char] = "1111" + format(i - 4, f'0{code_length}b')
        
        return code_table
    
    def compress(self, data):
        """Compress data using frequency-based encoding"""
        
        if not data:
            return "", {}, {}
        
        # Build frequency and code tables
        frequency_table = self.build_frequency_table(data)
        code_table = self.build_code_table(frequency_table)
        
        # Encode the data
        encoded_bits = []
        for char in data:
            encoded_bits.append(code_table[char])
        
        encoded_string = "".join(encoded_bits)
        
        return encoded_string, code_table, frequency_table
    
    def decompress(self, encoded_data, code_table):
        """Decompress frequency-encoded data"""
        
        if not encoded_data:
            return ""
        
        # Reverse the code table
        reverse_table = {code: char for char, code in code_table.items()}
        
        # Decode the data
        decoded_chars = []
        i = 0
        
        while i < len(encoded_data):
            # Try to match codes of increasing length
            for length in range(1, len(encoded_data) - i + 1):
                potential_code = encoded_data[i:i+length]
                if potential_code in reverse_table:
                    decoded_chars.append(reverse_table[potential_code])
                    i += length
                    break
            else:
                # This shouldn't happen with valid input
                break
        
        return "".join(decoded_chars)
    
    def analyze_compression(self, data):
        """Analyze frequency compression effectiveness"""
        
        # Compress the data
        encoded, code_table, frequency_table = self.compress(data)
        
        # Decompress to verify
        decoded = self.decompress(encoded, code_table)
        
        # Calculate sizes (in bits)
        original_size_bits = len(data) * 8  # 8 bits per character
        encoded_size_bits = len(encoded)
        
        # Calculate code table size
        code_table_size = sum(len(char) + len(code) for char, code in code_table.items()) * 8
        
        total_size_bits = encoded_size_bits + code_table_size
        
        # Calculate metrics
        compression_ratio = original_size_bits / total_size_bits if total_size_bits > 0 else 0
        is_correct = decoded == data
        
        return {
            "original_size_bits": original_size_bits,
            "encoded_size_bits": encoded_size_bits,
            "code_table_size_bits": code_table_size,
            "total_size_bits": total_size_bits,
            "compression_ratio": compression_ratio,
            "is_correct": is_correct,
            "frequency_table": frequency_table,
            "code_table": code_table
        }

def demonstrate_frequency_compression():
    """Demonstrate frequency-based compression"""
    
    compressor = FrequencyCompressor()
    
    # Test data with different frequency distributions
    test_data = [
        ("Skewed Distribution", "aaaaaaaaabbbbcccdde"),
        ("Uniform Distribution", "abcdefghijklmnopqrstuvwxyz"),
        ("Natural Text", "The quick brown fox jumps over the lazy dog"),
        ("Repeated Words", "hello world hello world hello world"),
        ("Mixed Content", "Hello, World! 123 Hello, World! 456")
    ]
    
    print("\nFrequency-Based Compression Demonstration:")
    print("=" * 80)
    print(f"{'Data Type':<20} {'Original':<10} {'Encoded':<10} {'Ratio':<8} {'Correct':<8}")
    print("-" * 80)
    
    for name, data in test_data:
        result = compressor.analyze_compression(data)
        
        original_chars = result['original_size_bits'] // 8
        encoded_chars = result['total_size_bits'] // 8
        
        print(f"{name:<20} {original_chars:<10} {encoded_chars:<10} "
              f"{result['compression_ratio']:<8.2f}x {'✓' if result['is_correct'] else '✗':<8}")
    
    # Show detailed example
    print(f"\nDetailed Example (Skewed Distribution):")
    detailed_data = "aaaaaaaaabbbbcccdde"
    detailed_result = compressor.analyze_compression(detailed_data)
    
    print(f"  Original: {detailed_data}")
    print(f"  Frequency table: {detailed_result['frequency_table']}")
    print(f"  Code table: {detailed_result['code_table']}")
    print(f"  Compression ratio: {detailed_result['compression_ratio']:.2f}x")

demonstrate_frequency_compression()
```

## Comparing Your Implementations

### Performance Comparison

```python
def compare_compression_methods():
    """Compare different compression methods"""
    
    # Create test data
    test_data = {
        "Repetitive": "A" * 500 + "B" * 300 + "C" * 200,
        "Structured": '{"name": "John", "age": 30}' * 50,
        "Natural": "The quick brown fox jumps over the lazy dog. " * 20,
        "Code": "function test() { return 42; }" * 15
    }
    
    print("Compression Methods Comparison:")
    print("=" * 100)
    print(f"{'Data Type':<12} {'Method':<15} {'Original':<10} {'Compressed':<12} {'Ratio':<8} {'Time':<10}")
    print("-" * 100)
    
    # Initialize compressors
    rle = RunLengthEncoder()
    dict_comp = SimpleDictionaryCompressor()
    freq_comp = FrequencyCompressor()
    
    for data_name, data in test_data.items():
        original_size = len(data)
        
        # zlib compression
        start_time = time.time()
        zlib_compressed = zlib.compress(data.encode())
        zlib_time = time.time() - start_time
        zlib_ratio = original_size / len(zlib_compressed)
        
        # RLE compression
        start_time = time.time()
        rle_result = rle.analyze_effectiveness(data)
        rle_time = time.time() - start_time
        
        # Dictionary compression
        start_time = time.time()
        dict_result = dict_comp.analyze_compression(data)
        dict_time = time.time() - start_time
        
        # Frequency compression
        start_time = time.time()
        freq_result = freq_comp.analyze_compression(data)
        freq_time = time.time() - start_time
        
        # Print results
        methods = [
            ("zlib", len(zlib_compressed), zlib_ratio, zlib_time),
            ("RLE", rle_result['encoded_size'], rle_result['compression_ratio'], rle_time),
            ("Dictionary", dict_result['total_size'], dict_result['compression_ratio'], dict_time),
            ("Frequency", freq_result['total_size_bits'] // 8, freq_result['compression_ratio'], freq_time)
        ]
        
        for method_name, compressed_size, ratio, comp_time in methods:
            print(f"{data_name:<12} {method_name:<15} {original_size:<10} {compressed_size:<12} "
                  f"{ratio:<8.2f}x {comp_time:<10.6f}s")
        
        print()  # Empty line between data types

compare_compression_methods()
```

### Best Practices Summary

```python
def compression_best_practices():
    """Show compression best practices"""
    
    practices = {
        "Choose the Right Algorithm": {
            "RLE": "Best for data with long runs of repeated characters",
            "Dictionary": "Best for data with repeated patterns or phrases",
            "Frequency": "Best for data with skewed character distributions",
            "zlib/gzip": "Good general-purpose choice for most text data"
        },
        
        "Consider the Trade-offs": {
            "Compression Ratio": "How much space you save",
            "Speed": "How fast compression/decompression is",
            "Memory Usage": "How much RAM the algorithm needs",
            "Complexity": "How difficult the algorithm is to implement"
        },
        
        "Implementation Tips": {
            "Always verify": "Decompress and check that data is identical",
            "Handle edge cases": "Empty data, single characters, very large data",
            "Monitor performance": "Track compression ratios and speeds",
            "Use appropriate data structures": "Choose efficient data structures"
        },
        
        "When to Use Compression": {
            "Storage": "When disk space is limited or expensive",
            "Network": "When bandwidth is limited or costly",
            "Memory": "When RAM is constrained",
            "Processing": "When I/O time dominates CPU time"
        }
    }
    
    print("Compression Best Practices:")
    print("=" * 60)
    
    for category, items in practices.items():
        print(f"\n{category}:")
        for item, description in items.items():
            print(f"  {item}: {description}")

compression_best_practices()
```

## Key Takeaways

### What You've Learned

1. **Practical Implementation**: How to use standard libraries for compression
2. **Algorithm Understanding**: How different compression algorithms work
3. **Performance Analysis**: How to measure and compare compression effectiveness
4. **Trade-off Awareness**: Understanding the balance between ratio, speed, and complexity

### Next Steps

1. **Experiment** with different data types and see how they compress
2. **Profile** your compression implementations to identify bottlenecks
3. **Combine** techniques (e.g., RLE followed by frequency encoding)
4. **Explore** advanced algorithms like LZ77, LZ78, and Huffman coding

### The Fundamental Insight

Compression is about **finding and exploiting patterns in data**. Different algorithms excel at different types of patterns:

- **RLE**: Consecutive repetitions
- **Dictionary**: Repeated phrases or patterns
- **Frequency**: Skewed character distributions
- **Hybrid**: Complex combinations of patterns

The key is to **match the algorithm to the data characteristics** and **measure the results** to ensure you're getting the benefits you expect.

The next step is exploring the deep trade-offs between compression ratio, speed, and computational complexity—the fundamental space-time trade-off that shapes all compression decisions.