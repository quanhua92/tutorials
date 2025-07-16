# Key Abstractions: Lossless vs. Lossy and Encoding Dictionaries

## The Fundamental Dichotomy

Compression algorithms fall into two fundamental categories that represent different philosophical approaches to data representation:

- **Lossless Compression**: Perfect reconstruction - every bit of the original data can be recovered
- **Lossy Compression**: Approximate reconstruction - some information is deliberately discarded

This distinction shapes every aspect of compression system design and determines when and how different compression techniques should be applied.

## Lossless Compression: Perfect Fidelity

### The Guarantee of Exactness

Lossless compression provides a mathematical guarantee: `decompress(compress(data)) = data`. This perfect reconstruction property makes lossless compression essential for data where every bit matters.

```python
import gzip
import hashlib
from abc import ABC, abstractmethod

class LosslessCompressionDemo:
    """Demonstrate lossless compression properties"""
    
    def __init__(self):
        pass
    
    def verify_lossless_property(self, data, compression_func, decompression_func):
        """Verify that compression is truly lossless"""
        
        # Calculate original data hash
        original_hash = hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()
        
        # Compress and decompress
        compressed = compression_func(data)
        decompressed = decompression_func(compressed)
        
        # Calculate decompressed data hash
        decompressed_hash = hashlib.sha256(decompressed.encode() if isinstance(decompressed, str) else decompressed).hexdigest()
        
        # Verify perfect reconstruction
        is_lossless = (original_hash == decompressed_hash)
        
        return {
            "original_size": len(data),
            "compressed_size": len(compressed),
            "decompressed_size": len(decompressed),
            "compression_ratio": len(data) / len(compressed),
            "is_lossless": is_lossless,
            "original_hash": original_hash,
            "decompressed_hash": decompressed_hash
        }
    
    def demonstrate_lossless_guarantee(self):
        """Demonstrate lossless compression guarantee"""
        
        # Test data with different characteristics
        test_data = [
            ("Simple text", "Hello, World! " * 100),
            ("Binary data", bytes(range(256)) * 10),
            ("Structured data", '{"name": "John", "age": 30}' * 50),
            ("Code", "function test() { return 42; }" * 20),
            ("Random-like", "".join(chr(i % 256) for i in range(1000)))
        ]
        
        print("Lossless Compression Verification:")
        print("=" * 70)
        print(f"{'Data Type':<15} {'Original':<10} {'Compressed':<10} {'Ratio':<8} {'Lossless':<10}")
        print("-" * 70)
        
        for name, data in test_data:
            # Simple gzip compression
            def compress_gzip(data):
                if isinstance(data, str):
                    data = data.encode()
                return gzip.compress(data)
            
            def decompress_gzip(compressed):
                return gzip.decompress(compressed).decode()
            
            result = self.verify_lossless_property(data, compress_gzip, decompress_gzip)
            
            print(f"{name:<15} {result['original_size']:<10} {result['compressed_size']:<10} "
                  f"{result['compression_ratio']:<8.2f} {'✓' if result['is_lossless'] else '✗':<10}")
    
    def demonstrate_lossless_use_cases(self):
        """Show when lossless compression is essential"""
        
        use_cases = {
            "Database Records": {
                "data": "INSERT INTO users VALUES (1, 'John', 'john@example.com');",
                "why_lossless": "Data integrity is critical - any corruption would be catastrophic"
            },
            "Source Code": {
                "data": "def fibonacci(n): return n if n <= 1 else fibonacci(n-1) + fibonacci(n-2)",
                "why_lossless": "A single character change could break the program"
            },
            "Configuration Files": {
                "data": '{"database_host": "localhost", "port": 5432, "ssl": true}',
                "why_lossless": "Configuration errors could crash the system"
            },
            "Financial Data": {
                "data": "Transaction: $1,234.56 from Account A to Account B",
                "why_lossless": "Financial accuracy is legally required"
            },
            "Medical Records": {
                "data": "Patient: John Doe, Blood Type: O+, Allergies: Penicillin",
                "why_lossless": "Medical accuracy is life-critical"
            }
        }
        
        print("\nLossless Compression Use Cases:")
        print("=" * 80)
        
        for use_case, info in use_cases.items():
            print(f"\n{use_case}:")
            print(f"  Data: {info['data']}")
            print(f"  Why lossless: {info['why_lossless']}")
            
            # Show compression result
            compressed = gzip.compress(info['data'].encode())
            ratio = len(info['data']) / len(compressed)
            print(f"  Compression: {len(info['data'])} → {len(compressed)} bytes ({ratio:.2f}x)")

# Demonstrate lossless compression
lossless_demo = LosslessCompressionDemo()
lossless_demo.demonstrate_lossless_guarantee()
lossless_demo.demonstrate_lossless_use_cases()
```

### Lossless Compression Algorithms

```python
class LosslessAlgorithmsDemo:
    """Demonstrate different lossless compression algorithms"""
    
    def __init__(self):
        pass
    
    def run_length_encode(self, data):
        """Simple run-length encoding implementation"""
        if not data:
            return ""
        
        encoded = []
        current_char = data[0]
        count = 1
        
        for char in data[1:]:
            if char == current_char:
                count += 1
            else:
                if count > 1:
                    encoded.append(f"{current_char}{count}")
                else:
                    encoded.append(current_char)
                current_char = char
                count = 1
        
        # Handle last group
        if count > 1:
            encoded.append(f"{current_char}{count}")
        else:
            encoded.append(current_char)
        
        return "".join(encoded)
    
    def run_length_decode(self, encoded):
        """Decode run-length encoded data"""
        decoded = []
        i = 0
        
        while i < len(encoded):
            char = encoded[i]
            
            # Check if next characters are digits
            if i + 1 < len(encoded) and encoded[i + 1].isdigit():
                # Extract count
                count_str = ""
                j = i + 1
                while j < len(encoded) and encoded[j].isdigit():
                    count_str += encoded[j]
                    j += 1
                
                count = int(count_str)
                decoded.append(char * count)
                i = j
            else:
                decoded.append(char)
                i += 1
        
        return "".join(decoded)
    
    def simple_dictionary_encode(self, data):
        """Simple dictionary encoding"""
        
        # Find repeated patterns
        patterns = {}
        for length in range(2, 10):
            for i in range(len(data) - length + 1):
                pattern = data[i:i+length]
                if pattern in patterns:
                    patterns[pattern] += 1
                else:
                    patterns[pattern] = 1
        
        # Create dictionary for patterns that appear multiple times
        dictionary = {}
        code_counter = 0
        for pattern, count in patterns.items():
            if count > 1 and len(pattern) > 2:
                dictionary[pattern] = f"#{code_counter}#"
                code_counter += 1
        
        # Encode data
        encoded = data
        for pattern, code in dictionary.items():
            encoded = encoded.replace(pattern, code)
        
        return encoded, dictionary
    
    def simple_dictionary_decode(self, encoded, dictionary):
        """Decode dictionary-encoded data"""
        decoded = encoded
        
        for pattern, code in dictionary.items():
            decoded = decoded.replace(code, pattern)
        
        return decoded
    
    def huffman_encode_simple(self, data):
        """Simplified Huffman encoding demonstration"""
        from collections import Counter, heapq
        
        if not data:
            return "", {}
        
        # Count frequencies
        freq = Counter(data)
        
        # Build Huffman tree (simplified)
        heap = [[weight, char] for char, weight in freq.items()]
        heapq.heapify(heap)
        
        # Build codes (simplified - actual Huffman is more complex)
        codes = {}
        if len(heap) == 1:
            codes[heap[0][1]] = "0"
        else:
            # Simplified: assign codes based on frequency
            sorted_chars = sorted(freq.items(), key=lambda x: x[1], reverse=True)
            code_length = 1
            for i, (char, _) in enumerate(sorted_chars):
                codes[char] = format(i, f'0{code_length}b')
                if i >= 2**code_length - 1:
                    code_length += 1
        
        # Encode data
        encoded = "".join(codes[char] for char in data)
        
        return encoded, codes
    
    def huffman_decode_simple(self, encoded, codes):
        """Decode simplified Huffman encoded data"""
        if not encoded:
            return ""
        
        # Reverse code dictionary
        reverse_codes = {code: char for char, code in codes.items()}
        
        decoded = []
        i = 0
        
        while i < len(encoded):
            for code_len in range(1, len(encoded) - i + 1):
                code = encoded[i:i+code_len]
                if code in reverse_codes:
                    decoded.append(reverse_codes[code])
                    i += code_len
                    break
            else:
                # This shouldn't happen with valid input
                break
        
        return "".join(decoded)
    
    def compare_lossless_algorithms(self):
        """Compare different lossless compression algorithms"""
        
        test_data = [
            ("Repetitive", "aaaaaabbbbbbccccccdddddd"),
            ("Natural text", "The quick brown fox jumps over the lazy dog. " * 5),
            ("Structured", '{"name": "John", "age": 30, "city": "New York"}' * 10),
            ("Mixed", "abc123def456ghi789" * 20)
        ]
        
        print("\nLossless Algorithms Comparison:")
        print("=" * 90)
        print(f"{'Data Type':<15} {'Original':<10} {'RLE':<10} {'Dictionary':<12} {'Huffman':<10} {'GZip':<10}")
        print("-" * 90)
        
        for name, data in test_data:
            original_size = len(data)
            
            # Run-length encoding
            rle_encoded = self.run_length_encode(data)
            rle_decoded = self.run_length_decode(rle_encoded)
            rle_size = len(rle_encoded)
            rle_correct = rle_decoded == data
            
            # Dictionary encoding
            dict_encoded, dictionary = self.simple_dictionary_encode(data)
            dict_decoded = self.simple_dictionary_decode(dict_encoded, dictionary)
            dict_size = len(dict_encoded) + sum(len(k) + len(v) for k, v in dictionary.items())
            dict_correct = dict_decoded == data
            
            # Huffman encoding
            huffman_encoded, codes = self.huffman_encode_simple(data)
            huffman_decoded = self.huffman_decode_simple(huffman_encoded, codes)
            huffman_size = len(huffman_encoded) // 8 + sum(len(k) + len(v) for k, v in codes.items())
            huffman_correct = huffman_decoded == data
            
            # GZip
            gzip_compressed = gzip.compress(data.encode())
            gzip_size = len(gzip_compressed)
            
            print(f"{name:<15} {original_size:<10} {rle_size:<10} {dict_size:<12} "
                  f"{huffman_size:<10} {gzip_size:<10}")
            
            # Verify all are lossless
            if not all([rle_correct, dict_correct, huffman_correct]):
                print(f"  ⚠️  Verification failed!")

# Demonstrate lossless algorithms
lossless_algos = LosslessAlgorithmsDemo()
lossless_algos.compare_lossless_algorithms()
```

## Lossy Compression: Perceptual Optimization

### The Art of Acceptable Loss

Lossy compression makes a fundamental trade-off: **achieve higher compression ratios by discarding information that's perceptually less important**. This approach is revolutionary for media data where perfect reconstruction is less critical than efficient representation.

```python
import numpy as np
from PIL import Image
import io

class LossyCompressionDemo:
    """Demonstrate lossy compression concepts"""
    
    def __init__(self):
        pass
    
    def simulate_image_compression(self, image_array, quality_levels):
        """Simulate image compression at different quality levels"""
        
        results = []
        
        for quality in quality_levels:
            # Simulate lossy compression by quantizing values
            compressed = self.quantize_image(image_array, quality)
            
            # Calculate metrics
            mse = np.mean((image_array - compressed) ** 2)
            psnr = 20 * np.log10(255 / np.sqrt(mse)) if mse > 0 else float('inf')
            
            # Estimate compression ratio (simplified)
            compression_ratio = 100 / quality  # Simplified relationship
            
            results.append({
                "quality": quality,
                "compressed_data": compressed,
                "mse": mse,
                "psnr": psnr,
                "compression_ratio": compression_ratio
            })
        
        return results
    
    def quantize_image(self, image_array, quality):
        """Simulate image quantization"""
        # Quantization step based on quality
        quantization_step = max(1, int(255 * (100 - quality) / 100))
        
        # Quantize the image
        quantized = (image_array // quantization_step) * quantization_step
        
        return quantized.astype(np.uint8)
    
    def simulate_audio_compression(self, audio_data, bit_rates):
        """Simulate audio compression at different bit rates"""
        
        results = []
        
        for bit_rate in bit_rates:
            # Simulate lossy audio compression by reducing precision
            compressed = self.reduce_audio_precision(audio_data, bit_rate)
            
            # Calculate signal-to-noise ratio
            noise = audio_data - compressed
            snr = 10 * np.log10(np.mean(audio_data**2) / np.mean(noise**2))
            
            # Estimate compression ratio
            compression_ratio = 1411 / bit_rate  # CD quality is 1411 kbps
            
            results.append({
                "bit_rate": bit_rate,
                "compressed_data": compressed,
                "snr": snr,
                "compression_ratio": compression_ratio
            })
        
        return results
    
    def reduce_audio_precision(self, audio_data, bit_rate):
        """Simulate audio precision reduction"""
        # Reduce bit depth based on bit rate
        if bit_rate >= 320:
            precision = 16
        elif bit_rate >= 192:
            precision = 12
        elif bit_rate >= 128:
            precision = 10
        else:
            precision = 8
        
        # Quantize audio
        max_val = 2**(precision - 1) - 1
        quantized = np.round(audio_data * max_val) / max_val
        
        return quantized
    
    def demonstrate_lossy_trade_offs(self):
        """Demonstrate lossy compression trade-offs"""
        
        # Generate sample image data
        image_data = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        
        # Generate sample audio data
        audio_data = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 44100))  # 440 Hz sine wave
        
        print("Lossy Compression Trade-offs:")
        print("=" * 60)
        
        # Image compression analysis
        print("\nImage Compression:")
        print(f"{'Quality':<10} {'Compression':<12} {'MSE':<10} {'PSNR':<10}")
        print("-" * 45)
        
        image_results = self.simulate_image_compression(image_data, [95, 75, 50, 25, 10])
        
        for result in image_results:
            print(f"{result['quality']:<10} {result['compression_ratio']:<12.1f}x "
                  f"{result['mse']:<10.2f} {result['psnr']:<10.1f} dB")
        
        # Audio compression analysis
        print("\nAudio Compression:")
        print(f"{'Bit Rate':<10} {'Compression':<12} {'SNR':<10}")
        print("-" * 35)
        
        audio_results = self.simulate_audio_compression(audio_data, [320, 192, 128, 64, 32])
        
        for result in audio_results:
            print(f"{result['bit_rate']:<10} {result['compression_ratio']:<12.1f}x "
                  f"{result['snr']:<10.1f} dB")
    
    def demonstrate_lossy_use_cases(self):
        """Show when lossy compression is appropriate"""
        
        use_cases = {
            "Web Images": {
                "description": "JPEG compression for web photos",
                "acceptable_loss": "Visual artifacts barely noticeable",
                "compression_ratio": "10-20x",
                "why_lossy": "File size matters more than perfect quality"
            },
            "Streaming Video": {
                "description": "H.264/H.265 compression for Netflix",
                "acceptable_loss": "Compression artifacts during motion",
                "compression_ratio": "100-500x",
                "why_lossy": "Bandwidth limitations require aggressive compression"
            },
            "Music Streaming": {
                "description": "MP3/AAC compression for Spotify",
                "acceptable_loss": "High-frequency details removed",
                "compression_ratio": "10-12x",
                "why_lossy": "Storage and bandwidth costs with acceptable quality"
            },
            "Video Calls": {
                "description": "Real-time video compression",
                "acceptable_loss": "Pixelation and reduced frame rate",
                "compression_ratio": "50-200x",
                "why_lossy": "Real-time constraints require fast compression"
            },
            "Scientific Data": {
                "description": "Sensor data compression",
                "acceptable_loss": "Noise reduction preserves signal",
                "compression_ratio": "5-10x",
                "why_lossy": "Noise removal can improve data quality"
            }
        }
        
        print("\nLossy Compression Use Cases:")
        print("=" * 80)
        
        for use_case, info in use_cases.items():
            print(f"\n{use_case}:")
            print(f"  Description: {info['description']}")
            print(f"  Acceptable loss: {info['acceptable_loss']}")
            print(f"  Compression ratio: {info['compression_ratio']}")
            print(f"  Why lossy: {info['why_lossy']}")

# Demonstrate lossy compression
lossy_demo = LossyCompressionDemo()
lossy_demo.demonstrate_lossy_trade_offs()
lossy_demo.demonstrate_lossy_use_cases()
```

## Encoding Dictionaries: The Translation Tables

### The Dictionary Abstraction

An encoding dictionary is a mapping between original data patterns and their compressed representations. This abstraction is fundamental to many compression algorithms and provides the mechanism for exploiting redundancy.

```python
class EncodingDictionaryDemo:
    """Demonstrate encoding dictionary concepts"""
    
    def __init__(self):
        pass
    
    def create_frequency_dictionary(self, data):
        """Create dictionary based on character frequency"""
        from collections import Counter
        
        # Count character frequencies
        freq = Counter(data)
        
        # Assign shorter codes to more frequent characters
        sorted_chars = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        
        dictionary = {}
        code_length = 1
        
        for i, (char, frequency) in enumerate(sorted_chars):
            # Assign codes of increasing length
            if i >= 2**code_length:
                code_length += 1
            
            dictionary[char] = {
                "code": format(i, f'0{code_length}b'),
                "frequency": frequency,
                "savings": (8 - code_length) * frequency
            }
        
        return dictionary
    
    def create_pattern_dictionary(self, data, min_length=2, max_length=8):
        """Create dictionary based on repeated patterns"""
        from collections import Counter
        
        # Find all patterns
        patterns = []
        for length in range(min_length, min(max_length, len(data) // 2)):
            for i in range(len(data) - length + 1):
                pattern = data[i:i+length]
                patterns.append(pattern)
        
        # Count pattern frequencies
        pattern_freq = Counter(patterns)
        
        # Create dictionary for patterns that appear multiple times
        dictionary = {}
        code_num = 0
        
        for pattern, count in pattern_freq.items():
            if count > 1:
                # Calculate potential savings
                original_size = len(pattern) * count
                compressed_size = 2 * count + len(pattern)  # 2-byte code + dictionary entry
                
                if compressed_size < original_size:
                    dictionary[pattern] = {
                        "code": f"#{code_num}#",
                        "frequency": count,
                        "savings": original_size - compressed_size
                    }
                    code_num += 1
        
        return dictionary
    
    def analyze_dictionary_effectiveness(self, data, dictionary):
        """Analyze how effective a dictionary is for compression"""
        
        # Calculate original size
        original_size = len(data)
        
        # Calculate compressed size
        compressed_data = data
        dictionary_size = 0
        total_savings = 0
        
        for pattern, info in dictionary.items():
            code = info["code"]
            frequency = info["frequency"]
            
            # Replace pattern with code
            compressed_data = compressed_data.replace(pattern, code)
            
            # Add to dictionary size
            dictionary_size += len(pattern) + len(code)
            
            # Calculate savings
            total_savings += info.get("savings", 0)
        
        compressed_size = len(compressed_data)
        total_size = compressed_size + dictionary_size
        
        return {
            "original_size": original_size,
            "compressed_size": compressed_size,
            "dictionary_size": dictionary_size,
            "total_size": total_size,
            "compression_ratio": original_size / total_size,
            "dictionary_efficiency": total_savings / dictionary_size if dictionary_size > 0 else 0
        }
    
    def demonstrate_dictionary_types(self):
        """Demonstrate different types of encoding dictionaries"""
        
        # Test data with different characteristics
        test_data = {
            "Repetitive Characters": "aaaaaabbbbbbccccccdddddd",
            "Repetitive Patterns": "abcdefg" * 20,
            "Natural Text": "The quick brown fox jumps over the lazy dog. " * 10,
            "Structured Data": '{"name": "John", "age": 30}' * 15
        }
        
        print("Encoding Dictionary Analysis:")
        print("=" * 80)
        
        for name, data in test_data.items():
            print(f"\n{name}:")
            print(f"  Original size: {len(data)} characters")
            
            # Frequency-based dictionary
            freq_dict = self.create_frequency_dictionary(data)
            freq_analysis = self.analyze_dictionary_effectiveness(data, freq_dict)
            
            print(f"  Frequency Dictionary:")
            print(f"    Entries: {len(freq_dict)}")
            print(f"    Compression ratio: {freq_analysis['compression_ratio']:.2f}x")
            print(f"    Dictionary overhead: {freq_analysis['dictionary_size']} bytes")
            
            # Pattern-based dictionary
            pattern_dict = self.create_pattern_dictionary(data)
            pattern_analysis = self.analyze_dictionary_effectiveness(data, pattern_dict)
            
            print(f"  Pattern Dictionary:")
            print(f"    Entries: {len(pattern_dict)}")
            print(f"    Compression ratio: {pattern_analysis['compression_ratio']:.2f}x")
            print(f"    Dictionary overhead: {pattern_analysis['dictionary_size']} bytes")
            
            # Show top patterns
            if pattern_dict:
                top_patterns = sorted(pattern_dict.items(), 
                                    key=lambda x: x[1]['savings'], 
                                    reverse=True)[:3]
                print(f"    Top patterns:")
                for pattern, info in top_patterns:
                    print(f"      '{pattern}' → '{info['code']}' ({info['frequency']}x, saves {info['savings']})")

# Demonstrate encoding dictionaries
dict_demo = EncodingDictionaryDemo()
dict_demo.demonstrate_dictionary_types()
```

### Dynamic vs. Static Dictionaries

```python
class DictionaryManagementDemo:
    """Demonstrate static vs dynamic dictionary management"""
    
    def __init__(self):
        pass
    
    def static_dictionary_compression(self, data, dictionary):
        """Compress using a pre-built static dictionary"""
        
        # Apply dictionary transformations
        compressed = data
        for pattern, code in dictionary.items():
            compressed = compressed.replace(pattern, code)
        
        return compressed
    
    def dynamic_dictionary_compression(self, data, max_dict_size=100):
        """Compress while building dictionary dynamically"""
        
        dictionary = {}
        compressed_parts = []
        code_counter = 0
        
        # Process data in chunks
        chunk_size = 50
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i+chunk_size]
            
            # Find patterns in current chunk
            new_patterns = self.find_patterns_in_chunk(chunk)
            
            # Add promising patterns to dictionary
            for pattern, frequency in new_patterns.items():
                if (frequency > 1 and 
                    len(pattern) > 2 and 
                    pattern not in dictionary and
                    len(dictionary) < max_dict_size):
                    
                    dictionary[pattern] = f"#{code_counter}#"
                    code_counter += 1
            
            # Compress chunk using current dictionary
            compressed_chunk = chunk
            for pattern, code in dictionary.items():
                compressed_chunk = compressed_chunk.replace(pattern, code)
            
            compressed_parts.append(compressed_chunk)
        
        return "".join(compressed_parts), dictionary
    
    def find_patterns_in_chunk(self, chunk):
        """Find repeated patterns in a chunk"""
        from collections import Counter
        
        patterns = []
        for length in range(2, 8):
            for i in range(len(chunk) - length + 1):
                pattern = chunk[i:i+length]
                patterns.append(pattern)
        
        return Counter(patterns)
    
    def adaptive_dictionary_compression(self, data, adaptation_frequency=100):
        """Compress with adaptive dictionary management"""
        
        dictionary = {}
        compressed_parts = []
        code_counter = 0
        usage_stats = {}
        
        # Process data in chunks
        chunk_size = 50
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i+chunk_size]
            
            # Track dictionary usage
            for pattern, code in dictionary.items():
                if pattern in chunk:
                    usage_stats[pattern] = usage_stats.get(pattern, 0) + chunk.count(pattern)
            
            # Adapt dictionary periodically
            if i % adaptation_frequency == 0 and i > 0:
                dictionary = self.adapt_dictionary(dictionary, usage_stats)
                usage_stats = {}
            
            # Add new patterns
            new_patterns = self.find_patterns_in_chunk(chunk)
            for pattern, frequency in new_patterns.items():
                if (frequency > 1 and 
                    len(pattern) > 2 and 
                    pattern not in dictionary and
                    len(dictionary) < 50):
                    
                    dictionary[pattern] = f"#{code_counter}#"
                    code_counter += 1
            
            # Compress chunk
            compressed_chunk = chunk
            for pattern, code in dictionary.items():
                compressed_chunk = compressed_chunk.replace(pattern, code)
            
            compressed_parts.append(compressed_chunk)
        
        return "".join(compressed_parts), dictionary
    
    def adapt_dictionary(self, dictionary, usage_stats):
        """Adapt dictionary based on usage statistics"""
        
        # Remove unused patterns
        adapted_dict = {}
        for pattern, code in dictionary.items():
            if usage_stats.get(pattern, 0) > 0:
                adapted_dict[pattern] = code
        
        return adapted_dict
    
    def compare_dictionary_strategies(self):
        """Compare different dictionary management strategies"""
        
        # Test data that changes characteristics over time
        test_data = (
            "The quick brown fox jumps over the lazy dog. " * 10 +
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 10 +
            "function test() { return 42; } " * 10 +
            '{"name": "John", "age": 30, "city": "New York"}' * 10
        )
        
        print("Dictionary Management Strategies:")
        print("=" * 60)
        
        # Static dictionary (built from first part of data)
        static_dict = self.create_static_dictionary(test_data[:200])
        static_compressed = self.static_dictionary_compression(test_data, static_dict)
        
        # Dynamic dictionary
        dynamic_compressed, dynamic_dict = self.dynamic_dictionary_compression(test_data)
        
        # Adaptive dictionary
        adaptive_compressed, adaptive_dict = self.adaptive_dictionary_compression(test_data)
        
        print(f"{'Strategy':<15} {'Original':<10} {'Compressed':<12} {'Dict Size':<10} {'Ratio':<8}")
        print("-" * 60)
        
        strategies = [
            ("Static", static_compressed, static_dict),
            ("Dynamic", dynamic_compressed, dynamic_dict),
            ("Adaptive", adaptive_compressed, adaptive_dict)
        ]
        
        for name, compressed, dictionary in strategies:
            dict_size = sum(len(k) + len(v) for k, v in dictionary.items())
            total_size = len(compressed) + dict_size
            ratio = len(test_data) / total_size
            
            print(f"{name:<15} {len(test_data):<10} {len(compressed):<12} "
                  f"{dict_size:<10} {ratio:<8.2f}x")
        
        print(f"\nDictionary characteristics:")
        for name, _, dictionary in strategies:
            print(f"  {name}: {len(dictionary)} entries")
    
    def create_static_dictionary(self, sample_data):
        """Create static dictionary from sample data"""
        patterns = self.find_patterns_in_chunk(sample_data)
        
        dictionary = {}
        code_counter = 0
        
        for pattern, frequency in patterns.items():
            if frequency > 1 and len(pattern) > 2:
                dictionary[pattern] = f"#{code_counter}#"
                code_counter += 1
        
        return dictionary

# Demonstrate dictionary management
dict_mgmt = DictionaryManagementDemo()
dict_mgmt.compare_dictionary_strategies()
```

## The Compression Spectrum

### Understanding the Continuum

Compression exists on a spectrum between perfect reconstruction and maximum compression ratio. Understanding this spectrum helps choose the right approach for different use cases.

```python
class CompressionSpectrumDemo:
    """Demonstrate the compression spectrum"""
    
    def __init__(self):
        pass
    
    def analyze_compression_spectrum(self, data):
        """Analyze compression options across the spectrum"""
        
        spectrum_points = [
            {
                "name": "No Compression",
                "type": "None",
                "ratio": 1.0,
                "quality": "Perfect",
                "use_case": "Archives, legal documents"
            },
            {
                "name": "Lossless High",
                "type": "Lossless",
                "ratio": 2.0,
                "quality": "Perfect",
                "use_case": "Source code, databases"
            },
            {
                "name": "Lossless Medium",
                "type": "Lossless",
                "ratio": 4.0,
                "quality": "Perfect",
                "use_case": "Text files, structured data"
            },
            {
                "name": "Lossless Max",
                "type": "Lossless",
                "ratio": 8.0,
                "quality": "Perfect",
                "use_case": "Highly redundant data"
            },
            {
                "name": "Near-Lossless",
                "type": "Lossy",
                "ratio": 15.0,
                "quality": "99.9%",
                "use_case": "Medical images, scientific data"
            },
            {
                "name": "High Quality",
                "type": "Lossy",
                "ratio": 25.0,
                "quality": "95%",
                "use_case": "Professional media"
            },
            {
                "name": "Standard Quality",
                "type": "Lossy",
                "ratio": 50.0,
                "quality": "85%",
                "use_case": "Web content, streaming"
            },
            {
                "name": "Low Quality",
                "type": "Lossy",
                "ratio": 100.0,
                "quality": "60%",
                "use_case": "Previews, thumbnails"
            },
            {
                "name": "Maximum Compression",
                "type": "Lossy",
                "ratio": 500.0,
                "quality": "30%",
                "use_case": "Ultra-low bandwidth"
            }
        ]
        
        return spectrum_points
    
    def demonstrate_compression_spectrum(self):
        """Show the compression spectrum analysis"""
        
        print("Compression Spectrum Analysis:")
        print("=" * 80)
        print(f"{'Compression Level':<20} {'Type':<10} {'Ratio':<8} {'Quality':<8} {'Use Case':<25}")
        print("-" * 80)
        
        spectrum = self.analyze_compression_spectrum("dummy_data")
        
        for point in spectrum:
            print(f"{point['name']:<20} {point['type']:<10} {point['ratio']:<8.1f}x "
                  f"{point['quality']:<8} {point['use_case']:<25}")
        
        print(f"\nKey Insights:")
        print(f"  • Lossless compression: Perfect quality, limited ratios")
        print(f"  • Lossy compression: Higher ratios, quality trade-offs")
        print(f"  • Application determines optimal point on spectrum")
        print(f"  • No single solution fits all use cases")

# Demonstrate compression spectrum
spectrum_demo = CompressionSpectrumDemo()
spectrum_demo.demonstrate_compression_spectrum()
```

## Key Insights

### The Fundamental Trade-offs

The key abstractions of compression reveal fundamental trade-offs:

1. **Lossless vs. Lossy**: Perfect reconstruction vs. higher compression ratios
2. **Static vs. Dynamic**: Simplicity vs. adaptability
3. **Dictionary Size**: Compression ratio vs. overhead
4. **Complexity**: Better compression vs. computational cost

### The Decision Matrix

Choosing between lossless and lossy compression depends on:

- **Data criticality**: Can any information be lost?
- **Usage patterns**: How will the data be used?
- **Storage constraints**: How much space is available?
- **Bandwidth limitations**: How fast must data transfer?
- **Quality requirements**: What level of fidelity is needed?

### The Encoding Philosophy

Encoding dictionaries represent the heart of compression philosophy:
- **Pattern recognition**: Identifying redundancy in data
- **Efficient representation**: Mapping patterns to shorter codes
- **Adaptive learning**: Improving compression as more data is processed
- **Trade-off management**: Balancing dictionary size with compression gains

The fundamental insight is that **compression is about finding the right abstractions for representing information efficiently**. Different data types, use cases, and constraints require different approaches, but the core principles remain constant: exploit redundancy, manage trade-offs, and adapt to data characteristics.

The next step is seeing these abstractions in practice through hands-on implementation and real-world usage examples.