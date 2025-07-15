# Binary Quantization: Vector Compression Meets Search Speed

> **Source**: [binary-quantization-qdrant](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/binary-quantization-qdrant)

## Part 1: The Core Concept

### Why Binary Quantization Exists

Imagine you're trying to remember every detail of 100,000 faces. Your brain would quickly overflow. But what if instead of remembering every facial feature in perfect detail, you simplified each face to just a few key characteristics - "round or angular face", "light or dark hair", "tall or short"? You'd trade some precision for the ability to store and compare vastly more faces in your memory.

Binary Quantization does exactly this for vector embeddings. Instead of storing each dimension as a full 32-bit floating point number, it compresses each dimension to just 1 bit - either 0 or 1. This reduces memory usage by 32x while maintaining surprisingly good search accuracy.

### The Memory-Speed-Accuracy Triangle

Vector databases face a fundamental trade-off triangle:
- **Memory**: How much storage do we need?
- **Speed**: How fast can we search?
- **Accuracy**: How precise are our results?

Traditional approaches force you to pick two sides of this triangle. Binary Quantization cleverly threads the needle, giving you dramatic memory savings and speed improvements while keeping accuracy surprisingly high through smart techniques like oversampling and rescoring.

### When to Use Binary Quantization

Binary Quantization shines when:
- You have millions+ vectors to store
- Memory or storage costs are significant
- Search speed is critical
- You can tolerate small accuracy trade-offs
- Your embeddings have redundant information (most do)

## Part 2: Practical Walkthrough

### Core Implementation

```python
# Create collection with binary quantization
client.create_collection(
    collection_name="bq-evaluation",
    vectors_config=models.VectorParams(
        size=1536,
        distance=models.Distance.COSINE,
        on_disk=True  # Store full vectors on disk
    ),
    quantization_config=models.BinaryQuantization(
        binary=models.BinaryQuantizationConfig(always_ram=False),
    ),
)
```

**What's happening here?**
- `on_disk=True`: Stores full-precision vectors on disk to save memory
- `BinaryQuantization`: Creates compressed 1-bit representations in RAM
- `always_ram=False`: Allows flexible memory management

### Parameterized Search Strategy

```python
def parameterized_search(point, oversampling, rescore, exact):
    return client.query_points(
        collection_name=collection_name,
        query=point.vector,
        search_params=models.SearchParams(
            quantization=models.QuantizationSearchParams(
                ignore=False,
                rescore=rescore,        # Re-rank with full vectors
                oversampling=oversampling,  # Fetch extra candidates
            ),
            exact=exact,
        ),
        limit=limit,
    ).points
```

**The Two-Stage Process:**
1. **Binary Search**: Fast approximate search using 1-bit vectors
2. **Rescoring**: Refine top candidates using full-precision vectors

### Performance Evaluation Framework

```python
# Compare accuracy across parameter combinations
for oversampling in [1.0, 2.0, 3.0]:
    for rescore in [True, False]:
        for limit in [5, 10, 20, 50, 100]:
            exact_results = parameterized_search(exact=True)
            approx_results = parameterized_search(exact=False)
            
            accuracy = calculate_overlap(exact_results, approx_results)
```

This systematic evaluation reveals how different parameters affect the memory-speed-accuracy trade-off.

## Part 3: Mental Models & Deep Dives

### The Compression Intuition

Think of binary quantization like creating a "sketch" of your data:

**Original Vector (32-bit floats)**:
```
[0.742, -0.891, 0.234, -0.567, 0.123, ...]
```

**Binary Vector (1-bit)**:
```
[1, 0, 1, 0, 1, ...]  # 1 if positive, 0 if negative
```

Each dimension becomes a simple yes/no question. While we lose the magnitude information, we preserve the directional relationships that often matter most for similarity.

### The Oversampling Strategy

Oversampling compensates for quantization errors by being "generous" in the first stage:

- **Oversampling = 1.0**: Get exactly 10 candidates for top-10 search
- **Oversampling = 3.0**: Get 30 candidates, then rescore to find best 10

Think of it like casting a wider net to ensure you don't miss good matches due to quantization noise.

### The Rescoring Refinement

Rescoring is like having a two-stage interview process:

1. **Phone Screen (Binary)**: Quick filter using simplified criteria
2. **In-Person Interview (Full Vector)**: Detailed evaluation of promising candidates

The binary search gets you in the right neighborhood fast, then full-precision vectors provide the final ranking accuracy.

### Performance Characteristics

**Memory Savings**: 32x reduction in vector storage
```
1M vectors × 1536 dims × 4 bytes = 6.1 GB (original)
1M vectors × 1536 dims × 1 bit = 196 MB (binary)
```

**Speed Improvements**: 
- Binary operations use SIMD instructions for parallel processing
- Reduced memory bandwidth requirements
- Faster index traversal

**Accuracy Retention**:
- Without rescoring: ~85-95% accuracy
- With rescoring: ~95-99% accuracy
- Best with oversampling factor of 3.0

### The Disk Storage Strategy

Setting `on_disk=True` creates a hybrid approach:
- **In Memory**: Binary quantized vectors (fast search)
- **On Disk**: Full-precision vectors (accurate rescoring)

This maximizes both speed and accuracy while minimizing memory usage - like keeping a quick reference card in your pocket while storing the full manual on your desk.

### Advanced Considerations

**Embedding Compatibility**: Binary quantization works best with:
- High-dimensional vectors (768+ dimensions)
- Embeddings with distributed information across dimensions
- Models that create well-separated semantic clusters

**Parameter Tuning**:
- Start with oversampling=3.0, rescoring=True
- Reduce oversampling if speed is critical
- Disable rescoring only if accuracy requirements are very relaxed

**Production Deployment**:
- Monitor accuracy metrics during rollout
- A/B test different parameter combinations
- Consider workload-specific tuning based on query patterns

Binary Quantization represents a sophisticated approach to the eternal vector database challenge: how to make similarity search both fast and accurate at scale. By understanding when and how to apply these techniques, you can dramatically improve system efficiency while maintaining the search quality your applications demand.