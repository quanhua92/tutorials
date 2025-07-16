# Getting Started: Building a Web Crawler with Bloom Filters

## The Problem: Avoiding Duplicate URLs

Web crawlers face a classic challenge: avoiding crawling the same URL multiple times. A naive approach would store all seen URLs in a set, but this quickly becomes memory-intensive as the number of URLs grows into the millions.

In this guide, we'll build a web crawler that uses Bloom filters to efficiently track visited URLs, demonstrating practical Bloom filter usage from basic implementation to production-ready optimizations.

## The Traditional Approach (And Why It Fails)

### Memory Explosion

Let's start with the obvious solution and see why it doesn't scale:

```python
import requests
from urllib.parse import urljoin, urlparse
from collections import deque
import time

class NaiveCrawler:
    def __init__(self):
        self.visited_urls = set()  # This will explode in memory
        self.url_queue = deque()
        self.crawled_count = 0
    
    def crawl(self, start_url, max_pages=10000):
        self.url_queue.append(start_url)
        
        while self.url_queue and self.crawled_count < max_pages:
            url = self.url_queue.popleft()
            
            # Memory-intensive check
            if url in self.visited_urls:
                continue
                
            # This grows indefinitely
            self.visited_urls.add(url)
            
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    self.crawled_count += 1
                    print(f"Crawled {url} ({self.crawled_count}/{max_pages})")
                    
                    # Extract new URLs to crawl
                    new_urls = self.extract_links(response.text, url)
                    for new_url in new_urls:
                        if new_url not in self.visited_urls:
                            self.url_queue.append(new_url)
                            
            except Exception as e:
                print(f"Error crawling {url}: {e}")
    
    def extract_links(self, html, base_url):
        # Simplified link extraction
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        
        for link in soup.find_all('a', href=True):
            url = urljoin(base_url, link['href'])
            if self.is_valid_url(url):
                links.append(url)
        
        return links
    
    def is_valid_url(self, url):
        parsed = urlparse(url)
        return parsed.scheme in ['http', 'https']
    
    def memory_usage(self):
        import sys
        return sys.getsizeof(self.visited_urls)

# Test the naive approach
crawler = NaiveCrawler()
print(f"Starting memory usage: {crawler.memory_usage()} bytes")

# This will quickly consume massive amounts of memory
# crawler.crawl("https://example.com")
```

### The Memory Problem

Let's calculate the memory usage:

```python
def calculate_memory_usage():
    """Calculate memory usage for different numbers of URLs"""
    
    # Average URL length: 50 characters
    # Python string overhead: ~50 bytes
    # Set overhead: ~20 bytes per item
    bytes_per_url = 50 + 50 + 20  # 120 bytes per URL
    
    scenarios = [
        ("Small site", 1_000),
        ("Medium site", 10_000),
        ("Large site", 100_000),
        ("Very large site", 1_000_000),
        ("Massive site", 10_000_000)
    ]
    
    print("Memory usage for different crawl sizes:")
    print("-" * 50)
    
    for name, url_count in scenarios:
        memory_mb = (url_count * bytes_per_url) / (1024 * 1024)
        print(f"{name:20}: {url_count:>10,} URLs = {memory_mb:>8.1f} MB")
    
    print("\nProblem: Memory grows linearly with URLs!")
    print("Solution: Use Bloom filters for space-efficient duplicate detection")

calculate_memory_usage()
```

Output:
```
Memory usage for different crawl sizes:
--------------------------------------------------
Small site          :      1,000 URLs =      0.1 MB
Medium site         :     10,000 URLs =      1.1 MB
Large site          :    100,000 URLs =     11.4 MB
Very large site     :  1,000,000 URLs =    114.4 MB
Massive site        : 10,000,000 URLs =  1,144.4 MB

Problem: Memory grows linearly with URLs!
Solution: Use Bloom filters for space-efficient duplicate detection
```

## Basic Bloom Filter Implementation

### Simple Bloom Filter

Let's implement a basic Bloom filter for URL deduplication:

```python
import hashlib
import math

class BasicBloomFilter:
    def __init__(self, expected_items, false_positive_rate):
        """
        Initialize Bloom filter with expected items and false positive rate.
        
        Args:
            expected_items: Number of items you expect to add
            false_positive_rate: Desired false positive rate (e.g., 0.01 for 1%)
        """
        self.expected_items = expected_items
        self.false_positive_rate = false_positive_rate
        
        # Calculate optimal bit array size
        self.bit_array_size = self._calculate_bit_array_size()
        
        # Calculate optimal number of hash functions
        self.num_hash_functions = self._calculate_num_hash_functions()
        
        # Initialize bit array
        self.bit_array = [0] * self.bit_array_size
        
        # Track items added
        self.items_added = 0
        
        print(f"Bloom filter initialized:")
        print(f"  Expected items: {expected_items:,}")
        print(f"  False positive rate: {false_positive_rate:.1%}")
        print(f"  Bit array size: {self.bit_array_size:,} bits ({self.bit_array_size/8/1024:.1f} KB)")
        print(f"  Number of hash functions: {self.num_hash_functions}")
    
    def _calculate_bit_array_size(self):
        """Calculate optimal bit array size using the formula: m = -n*ln(p)/(ln(2)^2)"""
        n = self.expected_items
        p = self.false_positive_rate
        m = -(n * math.log(p)) / (math.log(2) ** 2)
        return int(m)
    
    def _calculate_num_hash_functions(self):
        """Calculate optimal number of hash functions using: k = (m/n)*ln(2)"""
        m = self.bit_array_size
        n = self.expected_items
        k = (m / n) * math.log(2)
        return int(k)
    
    def _hash(self, item):
        """Generate multiple hash values for an item"""
        # Convert item to string and encode as bytes
        item_bytes = str(item).encode('utf-8')
        
        # Generate multiple hash values using double hashing
        hash1 = int(hashlib.md5(item_bytes).hexdigest(), 16)
        hash2 = int(hashlib.sha1(item_bytes).hexdigest(), 16)
        
        hash_values = []
        for i in range(self.num_hash_functions):
            # Double hashing: h_i(x) = (h1(x) + i*h2(x)) mod m
            hash_value = (hash1 + i * hash2) % self.bit_array_size
            hash_values.append(hash_value)
        
        return hash_values
    
    def add(self, item):
        """Add an item to the Bloom filter"""
        hash_values = self._hash(item)
        
        for hash_value in hash_values:
            self.bit_array[hash_value] = 1
        
        self.items_added += 1
    
    def contains(self, item):
        """Check if an item might be in the Bloom filter"""
        hash_values = self._hash(item)
        
        for hash_value in hash_values:
            if self.bit_array[hash_value] == 0:
                return False  # Definitely not in set
        
        return True  # Probably in set
    
    def current_false_positive_rate(self):
        """Calculate current false positive rate"""
        if self.items_added == 0:
            return 0.0
        
        # Formula: (1 - e^(-k*n/m))^k
        k = self.num_hash_functions
        n = self.items_added
        m = self.bit_array_size
        
        rate = (1 - math.exp(-k * n / m)) ** k
        return rate
    
    def memory_usage(self):
        """Calculate current memory usage in bytes"""
        # Bit array memory (bits to bytes)
        bit_array_bytes = self.bit_array_size // 8
        
        # Object overhead (approximate)
        object_overhead = 200
        
        return bit_array_bytes + object_overhead
    
    def stats(self):
        """Print current statistics"""
        print(f"Bloom Filter Statistics:")
        print(f"  Items added: {self.items_added:,}")
        print(f"  Expected items: {self.expected_items:,}")
        print(f"  Current false positive rate: {self.current_false_positive_rate():.3%}")
        print(f"  Target false positive rate: {self.false_positive_rate:.1%}")
        print(f"  Memory usage: {self.memory_usage()/1024:.1f} KB")
        print(f"  Bits set: {sum(self.bit_array):,}/{self.bit_array_size:,} ({sum(self.bit_array)/self.bit_array_size:.1%})")

# Test the basic Bloom filter
print("Testing Basic Bloom Filter:")
bf = BasicBloomFilter(expected_items=10000, false_positive_rate=0.01)

# Add some URLs
test_urls = [
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3"
]

for url in test_urls:
    bf.add(url)
    print(f"Added: {url}")

# Test membership
print("\nTesting membership:")
for url in test_urls:
    result = bf.contains(url)
    print(f"Contains '{url}': {result}")

# Test false positive
test_url = "https://example.com/page4"
result = bf.contains(test_url)
print(f"Contains '{test_url}' (never added): {result}")

bf.stats()
```

## Bloom Filter Crawler Implementation

### Crawler with Bloom Filter

Now let's build a web crawler that uses our Bloom filter:

```python
import requests
from urllib.parse import urljoin, urlparse
from collections import deque
import time
from bs4 import BeautifulSoup

class BloomFilterCrawler:
    def __init__(self, expected_urls=100000, false_positive_rate=0.01):
        """
        Initialize crawler with Bloom filter for duplicate detection.
        
        Args:
            expected_urls: Expected number of URLs to crawl
            false_positive_rate: Acceptable false positive rate
        """
        self.bloom_filter = BasicBloomFilter(expected_urls, false_positive_rate)
        self.url_queue = deque()
        self.crawled_count = 0
        self.skipped_count = 0
        self.error_count = 0
        
        # Statistics
        self.start_time = None
        self.urls_per_second = 0
    
    def crawl(self, start_url, max_pages=1000, delay=1.0):
        """
        Crawl starting from start_url up to max_pages.
        
        Args:
            start_url: URL to start crawling from
            max_pages: Maximum number of pages to crawl
            delay: Delay between requests (seconds)
        """
        self.start_time = time.time()
        self.url_queue.append(start_url)
        
        print(f"Starting crawl from: {start_url}")
        print(f"Max pages: {max_pages}")
        print(f"Delay between requests: {delay}s")
        print("-" * 50)
        
        while self.url_queue and self.crawled_count < max_pages:
            url = self.url_queue.popleft()
            
            # Check if we've seen this URL before
            if self.bloom_filter.contains(url):
                self.skipped_count += 1
                print(f"SKIP: {url} (probably already crawled)")
                continue
            
            # Add URL to Bloom filter
            self.bloom_filter.add(url)
            
            try:
                # Crawl the URL
                response = requests.get(url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; BloomCrawler/1.0)'
                })
                
                if response.status_code == 200:
                    self.crawled_count += 1
                    print(f"CRAWL: {url} ({self.crawled_count}/{max_pages})")
                    
                    # Extract new URLs to crawl
                    new_urls = self.extract_links(response.text, url)
                    for new_url in new_urls[:10]:  # Limit to avoid queue explosion
                        if not self.bloom_filter.contains(new_url):
                            self.url_queue.append(new_url)
                    
                    # Update statistics
                    self.update_statistics()
                    
                    # Print periodic statistics
                    if self.crawled_count % 10 == 0:
                        self.print_statistics()
                
                else:
                    print(f"ERROR: {url} returned {response.status_code}")
                    self.error_count += 1
                    
            except Exception as e:
                print(f"ERROR: {url} - {e}")
                self.error_count += 1
            
            # Rate limiting
            time.sleep(delay)
        
        print("\nCrawl completed!")
        self.print_final_statistics()
    
    def extract_links(self, html, base_url):
        """Extract all valid links from HTML content"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            links = []
            
            for link in soup.find_all('a', href=True):
                url = urljoin(base_url, link['href'])
                if self.is_valid_url(url):
                    links.append(url)
            
            return links
            
        except Exception as e:
            print(f"Error extracting links: {e}")
            return []
    
    def is_valid_url(self, url):
        """Check if URL is valid for crawling"""
        try:
            parsed = urlparse(url)
            
            # Only HTTP/HTTPS
            if parsed.scheme not in ['http', 'https']:
                return False
            
            # Skip common non-page extensions
            skip_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.exe']
            if any(url.lower().endswith(ext) for ext in skip_extensions):
                return False
            
            # Skip fragments and common query parameters
            if '#' in url or 'javascript:' in url:
                return False
            
            return True
            
        except Exception:
            return False
    
    def update_statistics(self):
        """Update crawling statistics"""
        elapsed_time = time.time() - self.start_time
        if elapsed_time > 0:
            self.urls_per_second = self.crawled_count / elapsed_time
    
    def print_statistics(self):
        """Print current crawling statistics"""
        print(f"\n--- Statistics ---")
        print(f"Crawled: {self.crawled_count}")
        print(f"Skipped: {self.skipped_count}")
        print(f"Errors: {self.error_count}")
        print(f"Queue size: {len(self.url_queue)}")
        print(f"URLs/second: {self.urls_per_second:.2f}")
        print(f"Bloom filter false positive rate: {self.bloom_filter.current_false_positive_rate():.3%}")
        print(f"Bloom filter memory usage: {self.bloom_filter.memory_usage()/1024:.1f} KB")
        print("-" * 30)
    
    def print_final_statistics(self):
        """Print final crawling statistics"""
        elapsed_time = time.time() - self.start_time
        
        print(f"\n{'='*50}")
        print(f"FINAL STATISTICS")
        print(f"{'='*50}")
        print(f"Total time: {elapsed_time:.2f} seconds")
        print(f"URLs crawled: {self.crawled_count}")
        print(f"URLs skipped: {self.skipped_count}")
        print(f"Errors: {self.error_count}")
        print(f"Average speed: {self.urls_per_second:.2f} URLs/second")
        print(f"")
        
        # Bloom filter statistics
        self.bloom_filter.stats()
        
        # Memory comparison
        naive_memory = self.crawled_count * 120  # 120 bytes per URL
        bloom_memory = self.bloom_filter.memory_usage()
        memory_savings = naive_memory / bloom_memory if bloom_memory > 0 else 0
        
        print(f"\nMemory Comparison:")
        print(f"Naive set approach: {naive_memory/1024:.1f} KB")
        print(f"Bloom filter approach: {bloom_memory/1024:.1f} KB")
        print(f"Memory savings: {memory_savings:.1f}x")

# Example usage
if __name__ == "__main__":
    # Create crawler with Bloom filter
    crawler = BloomFilterCrawler(
        expected_urls=1000,
        false_positive_rate=0.01
    )
    
    # Start crawling (use a test site or your own)
    # crawler.crawl("https://example.com", max_pages=50, delay=1.0)
```

## Advanced Bloom Filter Features

### Configurable Bloom Filter

Let's create a more flexible Bloom filter with additional features:

```python
import hashlib
import math
import json
from typing import List, Optional
import mmh3  # pip install mmh3

class AdvancedBloomFilter:
    def __init__(self, 
                 expected_items: int,
                 false_positive_rate: float = 0.01,
                 hash_functions: Optional[List[str]] = None):
        """
        Advanced Bloom filter with configurable hash functions.
        
        Args:
            expected_items: Number of items you expect to add
            false_positive_rate: Desired false positive rate
            hash_functions: List of hash function names to use
        """
        self.expected_items = expected_items
        self.false_positive_rate = false_positive_rate
        
        # Calculate optimal parameters
        self.bit_array_size = self._calculate_bit_array_size()
        self.num_hash_functions = self._calculate_num_hash_functions()
        
        # Initialize bit array
        self.bit_array = [0] * self.bit_array_size
        
        # Set up hash functions
        self.hash_functions = hash_functions or ['md5', 'sha1', 'mmh3']
        
        # Statistics
        self.items_added = 0
        self.false_positives_detected = 0
        
        self._validate_setup()
    
    def _validate_setup(self):
        """Validate the Bloom filter setup"""
        if self.expected_items <= 0:
            raise ValueError("Expected items must be positive")
        
        if not 0 < self.false_positive_rate < 1:
            raise ValueError("False positive rate must be between 0 and 1")
        
        if self.bit_array_size <= 0:
            raise ValueError("Bit array size must be positive")
        
        print(f"Advanced Bloom Filter Configuration:")
        print(f"  Expected items: {self.expected_items:,}")
        print(f"  False positive rate: {self.false_positive_rate:.1%}")
        print(f"  Bit array size: {self.bit_array_size:,} bits ({self.bit_array_size/8/1024:.1f} KB)")
        print(f"  Number of hash functions: {self.num_hash_functions}")
        print(f"  Hash functions: {self.hash_functions}")
    
    def _calculate_bit_array_size(self) -> int:
        """Calculate optimal bit array size"""
        n = self.expected_items
        p = self.false_positive_rate
        m = -(n * math.log(p)) / (math.log(2) ** 2)
        return int(m)
    
    def _calculate_num_hash_functions(self) -> int:
        """Calculate optimal number of hash functions"""
        m = self.bit_array_size
        n = self.expected_items
        k = (m / n) * math.log(2)
        return max(1, int(k))
    
    def _hash_md5(self, item: str) -> int:
        """MD5 hash function"""
        return int(hashlib.md5(item.encode()).hexdigest(), 16)
    
    def _hash_sha1(self, item: str) -> int:
        """SHA1 hash function"""
        return int(hashlib.sha1(item.encode()).hexdigest(), 16)
    
    def _hash_mmh3(self, item: str) -> int:
        """MurmurHash3 function"""
        return mmh3.hash(item)
    
    def _hash_fnv(self, item: str) -> int:
        """FNV hash function"""
        hash_value = 2166136261
        for byte in item.encode():
            hash_value ^= byte
            hash_value *= 16777619
        return hash_value
    
    def _get_hash_functions(self) -> List[callable]:
        """Get hash function implementations"""
        hash_map = {
            'md5': self._hash_md5,
            'sha1': self._hash_sha1,
            'mmh3': self._hash_mmh3,
            'fnv': self._hash_fnv
        }
        
        return [hash_map[name] for name in self.hash_functions if name in hash_map]
    
    def _hash(self, item: str) -> List[int]:
        """Generate multiple hash values for an item"""
        hash_functions = self._get_hash_functions()
        hash_values = []
        
        for i in range(self.num_hash_functions):
            # Use different hash functions in rotation
            hash_func = hash_functions[i % len(hash_functions)]
            
            # Apply different seeds for variation
            seeded_item = f"{item}_{i}"
            hash_value = hash_func(seeded_item) % self.bit_array_size
            hash_values.append(hash_value)
        
        return hash_values
    
    def add(self, item: str) -> None:
        """Add an item to the Bloom filter"""
        hash_values = self._hash(item)
        
        for hash_value in hash_values:
            self.bit_array[hash_value] = 1
        
        self.items_added += 1
    
    def contains(self, item: str) -> bool:
        """Check if an item might be in the Bloom filter"""
        hash_values = self._hash(item)
        
        for hash_value in hash_values:
            if self.bit_array[hash_value] == 0:
                return False
        
        return True
    
    def add_and_check(self, item: str) -> bool:
        """Add item and return True if it was already present"""
        was_present = self.contains(item)
        if not was_present:
            self.add(item)
        return was_present
    
    def current_false_positive_rate(self) -> float:
        """Calculate current false positive rate"""
        if self.items_added == 0:
            return 0.0
        
        k = self.num_hash_functions
        n = self.items_added
        m = self.bit_array_size
        
        return (1 - math.exp(-k * n / m)) ** k
    
    def memory_usage(self) -> int:
        """Calculate memory usage in bytes"""
        return (self.bit_array_size // 8) + 1000  # Bit array + object overhead
    
    def saturation_level(self) -> float:
        """Calculate how saturated the bit array is"""
        return sum(self.bit_array) / self.bit_array_size
    
    def save_to_file(self, filename: str) -> None:
        """Save Bloom filter to file"""
        data = {
            'expected_items': self.expected_items,
            'false_positive_rate': self.false_positive_rate,
            'bit_array_size': self.bit_array_size,
            'num_hash_functions': self.num_hash_functions,
            'hash_functions': self.hash_functions,
            'items_added': self.items_added,
            'bit_array': self.bit_array
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f)
    
    @classmethod
    def load_from_file(cls, filename: str) -> 'AdvancedBloomFilter':
        """Load Bloom filter from file"""
        with open(filename, 'r') as f:
            data = json.load(f)
        
        bf = cls(
            expected_items=data['expected_items'],
            false_positive_rate=data['false_positive_rate'],
            hash_functions=data['hash_functions']
        )
        
        bf.bit_array = data['bit_array']
        bf.items_added = data['items_added']
        
        return bf
    
    def stats(self) -> dict:
        """Return comprehensive statistics"""
        return {
            'expected_items': self.expected_items,
            'items_added': self.items_added,
            'false_positive_rate': self.false_positive_rate,
            'current_false_positive_rate': self.current_false_positive_rate(),
            'bit_array_size': self.bit_array_size,
            'num_hash_functions': self.num_hash_functions,
            'memory_usage_kb': self.memory_usage() / 1024,
            'saturation_level': self.saturation_level(),
            'bits_set': sum(self.bit_array),
            'hash_functions': self.hash_functions
        }
    
    def print_stats(self) -> None:
        """Print formatted statistics"""
        stats = self.stats()
        
        print(f"\nAdvanced Bloom Filter Statistics:")
        print(f"  Items added: {stats['items_added']:,} / {stats['expected_items']:,}")
        print(f"  False positive rate: {stats['current_false_positive_rate']:.3%} (target: {stats['false_positive_rate']:.1%})")
        print(f"  Memory usage: {stats['memory_usage_kb']:.1f} KB")
        print(f"  Saturation level: {stats['saturation_level']:.1%}")
        print(f"  Bits set: {stats['bits_set']:,} / {stats['bit_array_size']:,}")
        print(f"  Hash functions: {stats['hash_functions']}")
```

## Production-Ready Crawler

### Complete Implementation

Here's a production-ready crawler with all the features:

```python
import requests
import time
import logging
from urllib.parse import urljoin, urlparse
from collections import deque
from bs4 import BeautifulSoup
from typing import Set, List, Optional
import threading
from concurrent.futures import ThreadPoolExecutor
import signal
import sys

class ProductionCrawler:
    def __init__(self, 
                 expected_urls: int = 100000,
                 false_positive_rate: float = 0.01,
                 max_workers: int = 5,
                 request_delay: float = 1.0,
                 max_retries: int = 3):
        """
        Production-ready web crawler with Bloom filter duplicate detection.
        
        Args:
            expected_urls: Expected number of URLs to crawl
            false_positive_rate: Bloom filter false positive rate
            max_workers: Maximum number of concurrent workers
            request_delay: Delay between requests per worker
            max_retries: Maximum number of retries for failed requests
        """
        
        # Initialize Bloom filter
        self.bloom_filter = AdvancedBloomFilter(
            expected_items=expected_urls,
            false_positive_rate=false_positive_rate,
            hash_functions=['mmh3', 'fnv', 'md5']
        )
        
        # Crawler configuration
        self.max_workers = max_workers
        self.request_delay = request_delay
        self.max_retries = max_retries
        
        # State management
        self.url_queue = deque()
        self.crawled_urls = set()  # Small set for exact tracking of crawled URLs
        self.failed_urls = set()
        self.robots_cache = {}
        
        # Statistics
        self.stats = {
            'crawled': 0,
            'skipped': 0,
            'errors': 0,
            'false_positives': 0,
            'start_time': None,
            'end_time': None
        }
        
        # Threading
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock = threading.Lock()
        self.should_stop = False
        
        # Logging
        self.setup_logging()
        
        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; ProductionCrawler/1.0)'
        })
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def setup_logging(self):
        """Setup logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('crawler.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.should_stop = True
        self.executor.shutdown(wait=True)
        sys.exit(0)
    
    def crawl(self, start_urls: List[str], max_pages: int = 1000) -> None:
        """
        Start crawling from the given URLs.
        
        Args:
            start_urls: List of URLs to start crawling from
            max_pages: Maximum number of pages to crawl
        """
        self.stats['start_time'] = time.time()
        
        # Add start URLs to queue
        for url in start_urls:
            self.url_queue.append(url)
        
        self.logger.info(f"Starting crawl with {len(start_urls)} seed URLs")
        self.logger.info(f"Target: {max_pages} pages")
        self.logger.info(f"Workers: {self.max_workers}")
        
        # Submit worker tasks
        futures = []
        for worker_id in range(self.max_workers):
            future = self.executor.submit(self._worker, worker_id, max_pages)
            futures.append(future)
        
        # Wait for completion
        try:
            for future in futures:
                future.result()
        except KeyboardInterrupt:
            self.logger.info("Crawl interrupted by user")
        finally:
            self.stats['end_time'] = time.time()
            self._print_final_stats()
    
    def _worker(self, worker_id: int, max_pages: int) -> None:
        """Worker function that processes URLs from the queue"""
        self.logger.info(f"Worker {worker_id} started")
        
        while not self.should_stop and self.stats['crawled'] < max_pages:
            try:
                # Get URL from queue
                with self.lock:
                    if not self.url_queue:
                        time.sleep(0.1)
                        continue
                    url = self.url_queue.popleft()
                
                # Check if URL should be crawled
                if self._should_crawl(url):
                    self._crawl_url(url, worker_id)
                else:
                    with self.lock:
                        self.stats['skipped'] += 1
                
                # Rate limiting
                time.sleep(self.request_delay)
                
            except Exception as e:
                self.logger.error(f"Worker {worker_id} error: {e}")
        
        self.logger.info(f"Worker {worker_id} finished")
    
    def _should_crawl(self, url: str) -> bool:
        """Check if URL should be crawled"""
        # Check Bloom filter first (fast check)
        if self.bloom_filter.contains(url):
            # Potential duplicate - check exact set
            with self.lock:
                if url in self.crawled_urls:
                    return False  # Actual duplicate
                else:
                    # False positive detected
                    self.stats['false_positives'] += 1
                    self.logger.debug(f"False positive detected: {url}")
        
        # Check if URL is valid
        if not self._is_valid_url(url):
            return False
        
        # Check robots.txt (simplified)
        if not self._check_robots(url):
            return False
        
        return True
    
    def _crawl_url(self, url: str, worker_id: int) -> None:
        """Crawl a single URL"""
        try:
            # Add to Bloom filter and exact set
            self.bloom_filter.add(url)
            with self.lock:
                self.crawled_urls.add(url)
            
            # Make request
            response = self._make_request(url)
            
            if response and response.status_code == 200:
                with self.lock:
                    self.stats['crawled'] += 1
                    crawled_count = self.stats['crawled']
                
                self.logger.info(f"Worker {worker_id}: Crawled {url} ({crawled_count})")
                
                # Extract links
                new_urls = self._extract_links(response.text, url)
                
                # Add new URLs to queue
                with self.lock:
                    for new_url in new_urls[:20]:  # Limit to prevent queue explosion
                        if not self.bloom_filter.contains(new_url):
                            self.url_queue.append(new_url)
                
                # Print periodic stats
                if crawled_count % 100 == 0:
                    self._print_stats()
            
            else:
                with self.lock:
                    self.stats['errors'] += 1
                    self.failed_urls.add(url)
                
                self.logger.warning(f"Worker {worker_id}: Failed to crawl {url}")
        
        except Exception as e:
            with self.lock:
                self.stats['errors'] += 1
                self.failed_urls.add(url)
            
            self.logger.error(f"Worker {worker_id}: Error crawling {url}: {e}")
    
    def _make_request(self, url: str) -> Optional[requests.Response]:
        """Make HTTP request with retries"""
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    url,
                    timeout=10,
                    allow_redirects=True
                )
                return response
            
            except Exception as e:
                if attempt == self.max_retries - 1:
                    self.logger.error(f"Failed to fetch {url} after {self.max_retries} attempts: {e}")
                    return None
                else:
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        return None
    
    def _extract_links(self, html: str, base_url: str) -> List[str]:
        """Extract links from HTML content"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            links = []
            
            for link in soup.find_all('a', href=True):
                url = urljoin(base_url, link['href'])
                if self._is_valid_url(url):
                    links.append(url)
            
            return links
        
        except Exception as e:
            self.logger.error(f"Error extracting links from {base_url}: {e}")
            return []
    
    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid for crawling"""
        try:
            parsed = urlparse(url)
            
            # Only HTTP/HTTPS
            if parsed.scheme not in ['http', 'https']:
                return False
            
            # Skip binary files
            skip_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.exe', '.mp4', '.avi']
            if any(url.lower().endswith(ext) for ext in skip_extensions):
                return False
            
            # Skip fragments and javascript
            if '#' in url or 'javascript:' in url.lower():
                return False
            
            # Skip very long URLs
            if len(url) > 2000:
                return False
            
            return True
        
        except Exception:
            return False
    
    def _check_robots(self, url: str) -> bool:
        """Check robots.txt (simplified implementation)"""
        # In production, implement proper robots.txt parsing
        return True
    
    def _print_stats(self) -> None:
        """Print current statistics"""
        elapsed = time.time() - self.stats['start_time']
        crawl_rate = self.stats['crawled'] / elapsed if elapsed > 0 else 0
        
        print(f"\n--- Crawl Statistics ---")
        print(f"Crawled: {self.stats['crawled']:,}")
        print(f"Skipped: {self.stats['skipped']:,}")
        print(f"Errors: {self.stats['errors']:,}")
        print(f"False positives: {self.stats['false_positives']:,}")
        print(f"Queue size: {len(self.url_queue):,}")
        print(f"Crawl rate: {crawl_rate:.2f} URLs/sec")
        print(f"Bloom filter FP rate: {self.bloom_filter.current_false_positive_rate():.3%}")
        print(f"Memory usage: {self.bloom_filter.memory_usage()/1024:.1f} KB")
        print("-" * 30)
    
    def _print_final_stats(self) -> None:
        """Print final crawl statistics"""
        elapsed = self.stats['end_time'] - self.stats['start_time']
        
        print(f"\n{'='*60}")
        print(f"FINAL CRAWL STATISTICS")
        print(f"{'='*60}")
        print(f"Total time: {elapsed:.2f} seconds")
        print(f"URLs crawled: {self.stats['crawled']:,}")
        print(f"URLs skipped: {self.stats['skipped']:,}")
        print(f"Errors: {self.stats['errors']:,}")
        print(f"False positives: {self.stats['false_positives']:,}")
        print(f"Average crawl rate: {self.stats['crawled']/elapsed:.2f} URLs/sec")
        print(f"")
        
        # Bloom filter statistics
        self.bloom_filter.print_stats()
        
        # Memory comparison
        naive_memory = len(self.crawled_urls) * 120  # Approximate
        bloom_memory = self.bloom_filter.memory_usage()
        
        print(f"\nMemory Comparison:")
        print(f"Bloom filter: {bloom_memory/1024:.1f} KB")
        print(f"Naive approach: {naive_memory/1024:.1f} KB")
        print(f"Memory savings: {naive_memory/bloom_memory:.1f}x")
        
        # Save bloom filter
        self.bloom_filter.save_to_file('crawl_bloom_filter.json')
        print(f"Bloom filter saved to: crawl_bloom_filter.json")

# Example usage
if __name__ == "__main__":
    # Create production crawler
    crawler = ProductionCrawler(
        expected_urls=10000,
        false_positive_rate=0.01,
        max_workers=3,
        request_delay=1.0
    )
    
    # Start crawling
    start_urls = [
        "https://example.com",
        "https://httpbin.org"
    ]
    
    # crawler.crawl(start_urls, max_pages=100)
```

## Key Takeaways

### Memory Efficiency

The Bloom filter provides dramatic memory savings:

```python
def memory_comparison():
    """Compare memory usage between approaches"""
    
    urls_crawled = [1000, 10000, 100000, 1000000]
    
    print("Memory Usage Comparison:")
    print("URLs Crawled | Naive Set | Bloom Filter | Savings")
    print("-" * 50)
    
    for count in urls_crawled:
        naive_memory = count * 120  # bytes
        bloom_memory = AdvancedBloomFilter(count, 0.01).memory_usage()
        savings = naive_memory / bloom_memory
        
        print(f"{count:10,} | {naive_memory/1024:8.1f} KB | {bloom_memory/1024:11.1f} KB | {savings:6.1f}x")

memory_comparison()
```

### Performance Benefits

1. **Constant lookup time**: O(1) regardless of items added
2. **Predictable memory usage**: Fixed size bit array
3. **No false negatives**: Never miss actual duplicates
4. **Configurable accuracy**: Tune false positive rate

### Best Practices

1. **Size your Bloom filter properly**: Use expected item count
2. **Choose appropriate false positive rate**: Balance accuracy vs. memory
3. **Monitor false positive rates**: Adjust if needed
4. **Use quality hash functions**: Ensure good distribution
5. **Consider persistence**: Save/load for long-running crawlers

This guide demonstrates how Bloom filters solve real-world duplicate detection problems with minimal memory usage and excellent performance characteristics.