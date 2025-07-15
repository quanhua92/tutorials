# Getting Started with Qdrant: Your First Vector Database Journey

**Source Example:** [qdrant_101_getting_started](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/qdrant_101_getting_started)

## The Core Concept: Why This Example Exists

### The Problem
Imagine you're building a music recommendation system. Traditional databases can store song metadata (artist, title, genre), but they can't understand the *similarity* between songs. How do you find songs that "sound similar" to a user's favorite track? String matching on genre tags gets you nowhere near the nuanced understanding humans have of musical similarity.

### The Solution
Qdrant solves this by storing numerical representations (vectors) that capture the essence of your data. Think of each song as a point in a 100-dimensional space where the distance between points represents similarity. Songs with similar tempo, mood, and style cluster together, making recommendations as simple as finding nearby neighbors.

Qdrant's philosophy: **vectors are first-class citizens**. Unlike traditional databases retrofitted for AI workloads, Qdrant was built from the ground up for similarity search.

---

## Practical Walkthrough: Code Breakdown

### Setting Up Your Vector Database

The example starts by establishing a connection to Qdrant. You have two deployment options:

```python
from qdrant_client import QdrantClient
from qdrant_client import models

# Option 1: Connect to Qdrant running in Docker
client = QdrantClient(host="localhost", port=6333)

# Option 2: Use in-memory database (great for development)
# client = QdrantClient(location=":memory:")
```

**Why these options matter:** The Docker approach gives you persistence and production-readiness, while `:memory:` mode offers lightning-fast experimentation without any setup overhead.

### Creating Your First Collection

```python
my_collection = "first_collection"

client.recreate_collection(
    collection_name=my_collection,
    vectors_config=models.VectorParams(size=100, distance=models.Distance.COSINE)
)
```

**This is where vector databases differ fundamentally.** Unlike SQL tables that grow columns dynamically, vector collections require upfront decisions:

- **`size=100`**: Every vector must have exactly 100 dimensions
- **`distance=models.Distance.COSINE`**: Defines how similarity is calculated

**Why Cosine Similarity?** It measures the angle between vectors, not their magnitude. Two songs might have different "intensity" (magnitude) but similar "character" (direction) - perfect for semantic similarity.

### Adding Points: The Heart of Vector Storage

```python
# Generate 1,000 dummy song vectors
data = np.random.uniform(low=-1.0, high=1.0, size=(1_000, 100))
index = list(range(len(data)))

# Upload to Qdrant
client.upsert(
    collection_name=my_collection,
    points=models.Batch(
        ids=index,
        vectors=data.tolist()  # Qdrant requires native Python lists
    )
)
```

**Key insight:** Each "point" contains three elements:
- **ID**: Unique identifier (like a primary key)
- **Vector**: The 100-dimensional numerical representation  
- **Payload**: Optional metadata (added next)

**Why `.tolist()`?** Qdrant's API expects pure Python data structures, not NumPy arrays. This design choice ensures compatibility across different programming languages.

### Enriching Data with Payloads

```python
# Create realistic metadata for each song
payload = []
for i in range(len(data)):
    payload.append({
        "artist": fake_something.name(),
        "song": " ".join(fake_something.words()),
        "url_song": fake_something.url(),
        "year": fake_something.year(),
        "country": fake_something.country()
    })

# Update points with metadata
client.upsert(
    collection_name=my_collection,
    points=models.Batch(
        ids=index,
        vectors=data.tolist(),
        payloads=payload  # JSON objects attached to each vector
    )
)
```

**This is where Qdrant shines.** Payloads let you combine vector similarity with traditional filtering. You can find "songs similar to this track" AND "from Australia" AND "released after 2000" in a single query.

### Similarity Search in Action

```python
# Create a new song vector (represents "Livin' la Vida Loca")
new_song = create_song()

# Find the 3 most similar songs
results = client.search(
    collection_name=my_collection,
    query_vector=new_song,
    limit=3
)
```

**What's happening:** Qdrant calculates the cosine similarity between your query vector and every stored vector, then returns the closest matches ranked by similarity score.

### Filtered Search: Combining Similarity with Logic

```python
# Only recommend Australian songs
aussie_filter = models.Filter(
    must=[models.FieldCondition(key="country", match=models.MatchValue(value="Australia"))]
)

results = client.search(
    collection_name=my_collection,
    query_vector=new_song,
    query_filter=aussie_filter,
    limit=2
)
```

**This demonstrates Qdrant's hybrid approach.** You're not choosing between similarity search OR structured queries - you get both simultaneously.

### Content-Based Recommendations

```python
# User liked song #17, disliked song #120
recommendations = client.recommend(
    collection_name=my_collection,
    positive=[17],        # Find songs similar to these
    negative=[120],       # But avoid songs similar to these
    limit=5
)
```

**The mental model:** Imagine vectors as points in space. `positive` examples pull recommendations toward certain regions, while `negative` examples push them away. The result? Sophisticated content-based filtering without machine learning complexity.

---

## Mental Model: Thinking in Vector Space

### The Vector Space Analogy

Picture a 3D room where each song is a floating point. Songs with similar tempo cluster in one corner, while classical pieces group in another. When you search, you're asking: "What's near this location?"

```
High Tempo    •  •     ← Electronic/Dance tracks
             •  •
            •

     • • •              ← Jazz pieces
    •   •

         •     •        ← Classical music
        •   •
```

But instead of 3 dimensions, Qdrant works in 100+ dimensional space, capturing nuances invisible to human intuition.

### Why Cosine Similarity?

Consider two vectors representing songs:
- **Song A**: [0.8, 0.6] (high energy, medium tempo)
- **Song B**: [0.4, 0.3] (proportionally similar but quieter)

**Euclidean distance** would see these as different (magnitude differs).
**Cosine similarity** recognizes they're the same type of song (direction is identical).

This is perfect for capturing "musical character" regardless of recording volume or mixing differences.

### Design Insight: Why Qdrant Requires Fixed Vector Sizes

Unlike traditional databases where you can add columns freely, vector collections demand fixed dimensions. Why this constraint?

**Mathematical necessity:** Similarity calculations require comparing like with like. You can't compute the angle between a 100-dimensional vector and a 50-dimensional one.

**Performance optimization:** Fixed sizes enable memory-efficient indexing structures that make searches lightning-fast even with millions of vectors.

### Further Exploration

**Try this experiment:** Generate two sets of vectors - one with values between -1 and 1, another between -100 and 100. Search both collections with the same query vector (scaled appropriately). Notice how Cosine similarity finds the same relationships regardless of magnitude.

**Real-world connection:** In practice, these vectors would come from embedding models (Word2Vec, CLIP, or custom neural networks) that compress complex data into dense numerical representations. The beauty of Qdrant is that it doesn't care how your vectors were created - it just finds the nearest neighbors efficiently.

---

This tutorial introduced you to vector database fundamentals through a concrete music recommendation example. You've seen how Qdrant combines mathematical similarity with practical query features, creating a foundation for modern AI applications that understand semantic relationships rather than just exact matches.