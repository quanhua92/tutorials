# Multimodal Search

> **Source**: [multimodal-search](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/multimodal-search)

This tutorial demonstrates how to build a multimodal search system using LlamaIndex and Qdrant that enables cross-modal queries, allowing users to search for images using text descriptions and find text captions using image queries.

## Part 1: Core Concept - Why Multimodal Search Matters

### The Single-Modality Limitation

Traditional search systems operate within a single modality, creating artificial barriers:

- **Text search**: Only finds text documents, even when visual content is more relevant
- **Image search**: Limited to reverse image lookups or metadata-based searches
- **Disconnected experiences**: Users can't search "show me pictures of cats" in a text-based system
- **Lost context**: Rich multimedia content remains siloed and unsearchable

**Example limitation**: A user searches for "mountain sunset" but the system can't find relevant photos because it only searches text descriptions, not the actual visual content.

### The Multimodal Solution

Multimodal search breaks down these barriers by understanding content across different formats:

- **Shared understanding**: Images and text are mapped to the same conceptual space
- **Cross-modal queries**: Search for images using text, or text using images
- **Semantic comprehension**: Understands that "airplane" (text) relates to ✈️ (image)
- **Natural interaction**: Users can query in whatever format feels most natural

**What you'll build**: A system that embeds both images and text into a shared vector space, enabling seamless cross-modal search where text queries find relevant images and image queries find relevant descriptions.

### Real-World Applications

- **E-commerce**: "Show me products that look like this" or "find images of blue dresses"
- **Content Management**: Search photo libraries using natural language descriptions
- **Educational Platforms**: Find diagrams, charts, or images to illustrate text concepts
- **Social Media**: Search posts by describing visual content or finding captions for images

## Part 2: Practical Walkthrough - Building Multimodal Search

### Understanding Shared Embedding Spaces

The key insight behind multimodal search is the shared embedding space:

```
Text: "red sports car" → [0.2, 0.8, 0.1, ...] (512 dims)
Image: 🏎️ (red car)     → [0.3, 0.7, 0.2, ...] (512 dims)  # Close vectors!
Text: "blue ocean"    → [0.9, 0.1, 0.5, ...] (512 dims)  # Distant vectors
```

**Key insight**: Multimodal models learn to place semantically similar content close together in vector space, regardless of modality.

### Setup and Dependencies

```python
# Core dependencies for multimodal search
!pip install llama-index qdrant-client torch torchvision pillow

import os
from typing import List, Dict, Any
from pathlib import Path

from llama_index.core import VectorStoreIndex, Document
from llama_index.core.storage.storage_context import StorageContext
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, NamedVector

from PIL import Image
import torch
```

**Key components:**
- `llama-index`: Framework for multimodal RAG applications
- `qdrant-client`: Vector database with multi-vector support
- `HuggingFaceEmbedding`: Multimodal embedding models
- `PIL`: Image processing and manipulation

### Initialize Services

```python
# Initialize Qdrant client
qdrant_client = QdrantClient("localhost", port=6333)

# Initialize multimodal embedding model
multimodal_model = HuggingFaceEmbedding(
    model_name="llamaindex/vdr-2b-multi-v1",  # Multimodal model
    trust_remote_code=True
)

print("Multimodal search services initialized!")
```

### Stage 1: Dataset Preparation

#### Prepare Image-Text Pairs

```python
def load_multimodal_dataset(data_dir="multimodal_data/"):
    """Load paired image and text data"""
    
    dataset = []
    data_path = Path(data_dir)
    
    # Sample dataset structure
    sample_data = [
        {
            "image_path": "airplane.jpg",
            "text": "A commercial airplane flying through cloudy skies",
            "category": "transportation"
        },
        {
            "image_path": "sunset.jpg", 
            "text": "Beautiful sunset over a mountain landscape",
            "category": "nature"
        },
        {
            "image_path": "city.jpg",
            "text": "Modern city skyline with tall skyscrapers at night",
            "category": "urban"
        },
        {
            "image_path": "beach.jpg",
            "text": "Tropical beach with palm trees and clear blue water",
            "category": "nature"
        },
        {
            "image_path": "food.jpg",
            "text": "Delicious pasta dish with fresh herbs and tomatoes",
            "category": "food"
        }
    ]
    
    for item in sample_data:
        # Check if image file exists
        image_path = data_path / item["image_path"]
        if image_path.exists():
            dataset.append({
                "id": len(dataset),
                "image_path": str(image_path),
                "text": item["text"],
                "category": item["category"]
            })
    
    print(f"Loaded {len(dataset)} image-text pairs")
    return dataset

# Load dataset
multimodal_dataset = load_multimodal_dataset()
```

#### Alternative: Create Synthetic Dataset

```python
def create_synthetic_multimodal_data():
    """Create synthetic multimodal dataset for demonstration"""
    
    # For tutorial purposes, create data without actual images
    synthetic_data = [
        {
            "id": 0,
            "image_description": "Red sports car on highway",
            "text": "A red Ferrari speeding down the highway",
            "category": "automotive"
        },
        {
            "id": 1,
            "image_description": "Golden retriever in park", 
            "text": "Happy golden retriever playing in the park",
            "category": "animals"
        },
        {
            "id": 2,
            "image_description": "Modern kitchen interior",
            "text": "Contemporary kitchen with marble countertops",
            "category": "interior"
        },
        {
            "id": 3,
            "image_description": "Mountain hiking trail",
            "text": "Scenic hiking trail through mountain forest",
            "category": "outdoor"
        }
    ]
    
    return synthetic_data

# Use synthetic data if no real images available
if not multimodal_dataset:
    multimodal_dataset = create_synthetic_multimodal_data()
```

### Stage 2: Multimodal Embedding Generation

#### Generate Embeddings for Both Modalities

```python
def generate_multimodal_embeddings(dataset, model):
    """Generate separate embeddings for images and text"""
    
    embeddings_data = []
    
    for item in dataset:
        try:
            # Generate text embedding
            text_embedding = model.get_text_embedding(item["text"])
            
            # Generate image embedding (if image file exists)
            if "image_path" in item and Path(item["image_path"]).exists():
                image = Image.open(item["image_path"]).convert("RGB")
                image_embedding = model.get_image_embedding(image)
            else:
                # For demo: use text description as proxy for image
                image_embedding = model.get_text_embedding(
                    item.get("image_description", item["text"])
                )
            
            embeddings_data.append({
                "id": item["id"],
                "text": item["text"],
                "text_embedding": text_embedding,
                "image_embedding": image_embedding,
                "category": item["category"],
                "image_path": item.get("image_path", "synthetic")
            })
            
        except Exception as e:
            print(f"Error processing item {item['id']}: {e}")
            continue
    
    print(f"Generated embeddings for {len(embeddings_data)} items")
    return embeddings_data

# Generate embeddings
embedding_data = generate_multimodal_embeddings(multimodal_dataset, multimodal_model)
```

### Stage 3: Multi-Vector Qdrant Setup

#### Create Collection with Multiple Vector Fields

```python
def setup_multimodal_collection(client, collection_name="multimodal_search"):
    """Create Qdrant collection supporting multiple vector types"""
    
    # Delete existing collection if it exists
    try:
        client.delete_collection(collection_name)
    except:
        pass
    
    # Create collection with named vectors for different modalities
    vector_size = len(embedding_data[0]["text_embedding"])  # Get embedding dimension
    
    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            "text": VectorParams(
                size=vector_size,
                distance=Distance.COSINE
            ),
            "image": VectorParams(
                size=vector_size,
                distance=Distance.COSINE
            )
        }
    )
    
    print(f"Created multimodal collection '{collection_name}' with {vector_size}D vectors")
    return collection_name

# Setup collection
collection_name = setup_multimodal_collection(qdrant_client)
```

#### Index Multimodal Data

```python
def index_multimodal_data(client, data, collection_name):
    """Index both text and image embeddings in Qdrant"""
    
    points = []
    
    for item in data:
        # Create point with named vectors for both modalities
        point = PointStruct(
            id=item["id"],
            vector={
                "text": item["text_embedding"],
                "image": item["image_embedding"]
            },
            payload={
                "text": item["text"],
                "category": item["category"],
                "image_path": item["image_path"]
            }
        )
        points.append(point)
    
    # Upload all points
    client.upsert(collection_name=collection_name, points=points)
    
    print(f"Indexed {len(points)} multimodal data points")

# Index the data
index_multimodal_data(qdrant_client, embedding_data, collection_name)
```

### Stage 4: Cross-Modal Search Implementation

#### Text-to-Image Search

```python
def text_to_image_search(query_text, client, collection_name, model, top_k=5):
    """Search for images using text query"""
    
    print(f"🔍 Text-to-Image Search: '{query_text}'")
    
    # Generate text embedding for query
    query_embedding = model.get_text_embedding(query_text)
    
    # Search against image vectors using text query
    search_results = client.search(
        collection_name=collection_name,
        query_vector=NamedVector(
            name="image",  # Search in image vector space
            vector=query_embedding
        ),
        limit=top_k
    )
    
    # Format results
    results = []
    for result in search_results:
        results.append({
            "score": result.score,
            "text": result.payload["text"],
            "category": result.payload["category"],
            "image_path": result.payload["image_path"]
        })
    
    return results

# Test text-to-image search
text_queries = [
    "red sports car",
    "mountain landscape", 
    "modern kitchen",
    "happy dog playing"
]

for query in text_queries:
    results = text_to_image_search(query, qdrant_client, collection_name, multimodal_model, top_k=3)
    
    print(f"Top results for '{query}':")
    for i, result in enumerate(results, 1):
        print(f"  {i}. Score: {result['score']:.3f}")
        print(f"     Text: {result['text']}")
        print(f"     Category: {result['category']}")
    print()
```

#### Image-to-Text Search

```python
def image_to_text_search(image_path, client, collection_name, model, top_k=5):
    """Search for text descriptions using image query"""
    
    print(f"🖼️ Image-to-Text Search: {image_path}")
    
    # Load and process image
    if Path(image_path).exists():
        image = Image.open(image_path).convert("RGB")
        query_embedding = model.get_image_embedding(image)
    else:
        # For demo: use text description as proxy
        print(f"Image not found, using text proxy")
        query_embedding = model.get_text_embedding("sample image description")
    
    # Search against text vectors using image query
    search_results = client.search(
        collection_name=collection_name,
        query_vector=NamedVector(
            name="text",  # Search in text vector space
            vector=query_embedding
        ),
        limit=top_k
    )
    
    # Format results
    results = []
    for result in search_results:
        results.append({
            "score": result.score,
            "text": result.payload["text"],
            "category": result.payload["category"]
        })
    
    return results

# Test image-to-text search
def demo_image_to_text_search():
    """Demo image-to-text search with synthetic data"""
    
    # Simulate image queries by using text descriptions
    image_descriptions = [
        "sports car image",
        "nature landscape photo",
        "kitchen interior image"
    ]
    
    for desc in image_descriptions:
        # Use text embedding as proxy for image embedding
        query_embedding = multimodal_model.get_text_embedding(desc)
        
        search_results = qdrant_client.search(
            collection_name=collection_name,
            query_vector=NamedVector(
                name="text",
                vector=query_embedding
            ),
            limit=3
        )
        
        print(f"🖼️ Image query (simulated): '{desc}'")
        print("Matching text descriptions:")
        for i, result in enumerate(search_results, 1):
            print(f"  {i}. Score: {result.score:.3f}")
            print(f"     Text: {result.payload['text']}")
        print()

# Run demo
demo_image_to_text_search()
```

#### Multilingual Cross-Modal Search

```python
def multilingual_multimodal_search(query, language="en", client=qdrant_client, 
                                 collection_name=collection_name, model=multimodal_model):
    """Demonstrate cross-lingual multimodal search"""
    
    print(f"🌍 Multilingual Search ({language}): '{query}'")
    
    # Generate embedding for query (model handles multiple languages)
    query_embedding = model.get_text_embedding(query)
    
    # Search against image vectors
    search_results = client.search(
        collection_name=collection_name,
        query_vector=NamedVector(
            name="image",
            vector=query_embedding
        ),
        limit=3
    )
    
    print("Results:")
    for i, result in enumerate(search_results, 1):
        print(f"  {i}. Score: {result.score:.3f}")
        print(f"     English: {result.payload['text']}")
        print(f"     Category: {result.payload['category']}")
    print()

# Test multilingual queries
multilingual_queries = [
    ("red car", "en"),
    ("coche rojo", "es"),  # Spanish
    ("voiture rouge", "fr"),  # French
    ("rotes Auto", "de")  # German
]

for query, lang in multilingual_queries:
    multilingual_multimodal_search(query, lang)
```

### Stage 5: Advanced Multimodal Features

#### Hybrid Search Combining Both Modalities

```python
def hybrid_multimodal_search(text_query, weight_text=0.6, weight_image=0.4):
    """Combine text and image search results for better accuracy"""
    
    query_embedding = multimodal_model.get_text_embedding(text_query)
    
    # Search in both vector spaces
    text_results = qdrant_client.search(
        collection_name=collection_name,
        query_vector=NamedVector(name="text", vector=query_embedding),
        limit=10
    )
    
    image_results = qdrant_client.search(
        collection_name=collection_name, 
        query_vector=NamedVector(name="image", vector=query_embedding),
        limit=10
    )
    
    # Combine and rerank results
    combined_scores = {}
    
    # Add text search scores
    for result in text_results:
        combined_scores[result.id] = weight_text * result.score
    
    # Add image search scores
    for result in image_results:
        if result.id in combined_scores:
            combined_scores[result.id] += weight_image * result.score
        else:
            combined_scores[result.id] = weight_image * result.score
    
    # Sort by combined score
    sorted_ids = sorted(combined_scores.keys(), 
                       key=lambda x: combined_scores[x], reverse=True)
    
    # Get top results with metadata
    hybrid_results = []
    for point_id in sorted_ids[:5]:
        point = qdrant_client.retrieve(
            collection_name=collection_name,
            ids=[point_id]
        )[0]
        
        hybrid_results.append({
            "id": point_id,
            "combined_score": combined_scores[point_id],
            "text": point.payload["text"],
            "category": point.payload["category"]
        })
    
    return hybrid_results

# Test hybrid search
hybrid_query = "beautiful landscape"
hybrid_results = hybrid_multimodal_search(hybrid_query)

print(f"🔄 Hybrid Search Results for '{hybrid_query}':")
for result in hybrid_results:
    print(f"  Score: {result['combined_score']:.3f}")
    print(f"  Text: {result['text']}")
    print(f"  Category: {result['category']}")
    print()
```

## Part 3: Mental Models & Deep Dives

### Understanding Multimodal Embeddings

**Mental Model**: Think of multimodal embeddings like a universal translator for different types of content:

**Traditional approach**: Text and images live in separate worlds
```
Text World: "cat" → [0.1, 0.3, 0.8]
Image World: 🐱 → [0.9, 0.2, 0.1]  # Completely different spaces!
```

**Multimodal approach**: Everything maps to the same conceptual space
```
Shared Space: "cat" → [0.2, 0.7, 0.4]
              🐱   → [0.3, 0.6, 0.5]  # Close together!
```

### The Cross-Modal Bridge

**Mental Model**: Multimodal models are like polyglot translators who understand multiple languages (modalities) and can translate between them:

1. **Training**: Learn from millions of image-text pairs
2. **Alignment**: Map similar concepts close together regardless of modality
3. **Generalization**: Apply learned relationships to new content

### Vector Space Navigation

```python
# Conceptual vector space organization
vector_space = {
    # Transportation cluster
    "airplane": [0.1, 0.8, 0.2, ...],
    "✈️": [0.2, 0.7, 0.3, ...],        # Close to "airplane"
    
    # Nature cluster  
    "mountain": [0.7, 0.2, 0.8, ...],
    "🏔️": [0.8, 0.1, 0.7, ...],        # Close to "mountain"
    
    # Food cluster
    "pizza": [0.4, 0.5, 0.1, ...],
    "🍕": [0.5, 0.4, 0.2, ...]         # Close to "pizza"
}
```

### Advanced Multimodal Patterns

#### Semantic Hierarchy Search

```python
def hierarchical_multimodal_search(query, client, collection_name):
    """Search with semantic hierarchy understanding"""
    
    # First: broad category search
    broad_results = text_to_image_search(query, client, collection_name, multimodal_model, top_k=20)
    
    # Second: cluster by category
    category_clusters = {}
    for result in broad_results:
        category = result["category"]
        if category not in category_clusters:
            category_clusters[category] = []
        category_clusters[category].append(result)
    
    # Third: get best from each category
    diverse_results = []
    for category, results in category_clusters.items():
        # Take top result from each category
        diverse_results.append(results[0])
    
    return diverse_results
```

#### Multimodal Query Expansion

```python
def expand_multimodal_query(original_query, model):
    """Generate related queries for broader search"""
    
    # Generate embedding for original query
    original_embedding = model.get_text_embedding(original_query)
    
    # Related terms (could be generated by LLM)
    related_terms = {
        "car": ["automobile", "vehicle", "sedan", "coupe"],
        "dog": ["puppy", "canine", "pet", "animal"],
        "house": ["home", "building", "residence", "property"]
    }
    
    expanded_queries = [original_query]
    
    # Add related terms if found
    for base_term, synonyms in related_terms.items():
        if base_term in original_query.lower():
            for synonym in synonyms:
                expanded_queries.append(original_query.replace(base_term, synonym))
    
    return expanded_queries

def multi_query_search(query, client, collection_name, model):
    """Search using multiple related queries"""
    
    expanded_queries = expand_multimodal_query(query, model)
    all_results = []
    
    for exp_query in expanded_queries:
        results = text_to_image_search(exp_query, client, collection_name, model, top_k=3)
        all_results.extend(results)
    
    # Deduplicate and rerank
    unique_results = {}
    for result in all_results:
        result_id = result["text"]  # Use text as unique identifier
        if result_id not in unique_results or result["score"] > unique_results[result_id]["score"]:
            unique_results[result_id] = result
    
    return list(unique_results.values())[:5]
```

#### Temporal Multimodal Search

```python
def temporal_multimodal_search(query, time_period, client, collection_name):
    """Search with temporal constraints"""
    
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    
    # Create temporal filter
    temporal_filter = Filter(
        must=[
            FieldCondition(
                key="timestamp",
                range={"gte": time_period["start"], "lte": time_period["end"]}
            )
        ]
    )
    
    query_embedding = multimodal_model.get_text_embedding(query)
    
    # Search with temporal constraints
    results = client.search(
        collection_name=collection_name,
        query_vector=NamedVector(name="image", vector=query_embedding),
        query_filter=temporal_filter,
        limit=5
    )
    
    return results
```

### Performance Optimization

#### Batch Processing for Large Datasets

```python
def batch_multimodal_indexing(dataset, client, collection_name, batch_size=100):
    """Efficiently process large multimodal datasets"""
    
    for i in range(0, len(dataset), batch_size):
        batch = dataset[i:i + batch_size]
        
        # Process batch
        batch_embeddings = []
        for item in batch:
            text_emb = multimodal_model.get_text_embedding(item["text"])
            image_emb = multimodal_model.get_image_embedding(item["image"])  # If available
            
            batch_embeddings.append({
                "id": item["id"],
                "text_embedding": text_emb,
                "image_embedding": image_emb,
                "payload": item
            })
        
        # Create points
        points = []
        for emb_data in batch_embeddings:
            point = PointStruct(
                id=emb_data["id"],
                vector={
                    "text": emb_data["text_embedding"],
                    "image": emb_data["image_embedding"]
                },
                payload=emb_data["payload"]
            )
            points.append(point)
        
        # Upload batch
        client.upsert(collection_name=collection_name, points=points)
        print(f"Processed batch {i//batch_size + 1}")
```

#### Caching for Repeated Queries

```python
import hashlib
from functools import lru_cache

def cache_multimodal_queries(func):
    """Cache multimodal search results"""
    cache = {}
    
    def wrapper(query, *args, **kwargs):
        # Create cache key
        cache_key = hashlib.md5(f"{query}_{str(args)}_{str(kwargs)}".encode()).hexdigest()
        
        if cache_key not in cache:
            cache[cache_key] = func(query, *args, **kwargs)
        
        return cache[cache_key]
    
    return wrapper

@cache_multimodal_queries
def cached_multimodal_search(query, client, collection_name, model):
    """Cached version of multimodal search"""
    return text_to_image_search(query, client, collection_name, model)
```

### Real-World Implementation Considerations

#### Quality Assessment

```python
def evaluate_multimodal_search_quality(test_queries, ground_truth):
    """Evaluate multimodal search performance"""
    
    metrics = {
        "precision_at_k": [],
        "cross_modal_accuracy": [],
        "semantic_relevance": []
    }
    
    for query_data in test_queries:
        query = query_data["query"]
        expected_results = query_data["expected_ids"]
        
        # Perform search
        results = text_to_image_search(query, qdrant_client, collection_name, multimodal_model)
        actual_ids = [r["id"] for r in results]
        
        # Calculate precision@k
        relevant_found = len(set(actual_ids) & set(expected_results))
        precision = relevant_found / len(results) if results else 0
        metrics["precision_at_k"].append(precision)
    
    # Average metrics
    for key in metrics:
        metrics[key] = sum(metrics[key]) / len(metrics[key])
    
    return metrics
```

This comprehensive multimodal search system demonstrates how to bridge the gap between different content types, enabling natural and intuitive search experiences that understand both visual and textual content semantically.