# Multivector Representation

> **Source**: [multivector-representation](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/multivector-representation)

This tutorial demonstrates how to build a two-stage search system using both dense and multi-vector representations in Qdrant, combining the speed of dense vectors with the precision of ColBERT-style token-level matching.

## Part 1: Core Concept - Why Multivector Representation Matters

### The Single Vector Limitation

Traditional dense vector search represents entire documents as single points in vector space, which creates fundamental trade-offs:

- **Information compression**: Complex documents squeezed into fixed-size vectors lose nuanced details
- **Averaging effect**: Important specific terms get diluted by general document content
- **Matching granularity**: Can't identify which specific parts of a document are relevant
- **Query-document mismatch**: Relevant sections may be overshadowed by irrelevant content

**Example problem**: Searching for "machine learning algorithms" in a document about "AI and machine learning applications in healthcare" might miss the match because the dense vector is dominated by healthcare terminology.

### The Multivector Solution

Multivector representation solves this by maintaining multiple granular vectors per document:

- **Token-level precision**: Each word/phrase gets its own vector representation
- **Fine-grained matching**: Can identify exactly which parts of documents are relevant
- **MaxSim scoring**: Compares query tokens against all document tokens for best matches
- **Preserved context**: Maintains both local (token) and global (document) semantic information

**What you'll build**: A hybrid search system that uses fast dense vectors for initial retrieval and precise multivector representations for accurate reranking, all in a single efficient query.

### Real-World Applications

- **Legal Document Search**: Find specific clauses while considering overall document context
- **Scientific Literature**: Match precise technical terms within broader research papers
- **Code Search**: Locate specific functions while understanding overall codebase context
- **E-commerce**: Find products with specific features within general category descriptions

## Part 2: Practical Walkthrough - Building Multivector Search

### Understanding the Two-Stage Architecture

The system combines two complementary approaches:

```
Query → [Dense Search] → Top 100 candidates → [Multivector Rerank] → Top 10 results
```

**Stage 1 - Dense Prefetch**: Fast approximate search using single vectors
**Stage 2 - Multivector Rerank**: Precise scoring using token-level comparisons

**Key insight**: Use dense vectors for speed, multivectors for accuracy.

### Setup and Dependencies

```python
# Core dependencies for multivector search
!pip install qdrant-client fastembed numpy

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, 
    NamedVector, PrefetchQuery, Query
)
from fastembed import TextEmbedding, SparseTextEmbedding
import numpy as np
from typing import List, Dict, Any
```

**Key components:**
- `qdrant-client`: Vector database with multivector support
- `fastembed`: Efficient embedding generation for both dense and sparse vectors
- `numpy`: Array operations for vector computations

### Initialize Embedding Models

```python
# Initialize dense embedding model for fast retrieval
dense_model = TextEmbedding("BAAI/bge-small-en")

# Initialize ColBERT model for precise reranking
try:
    colbert_model = TextEmbedding("colbert-ir/colbertv2.0")
except:
    print("ColBERT model not available, using alternative...")
    # Alternative: simulate multivector with token-based embeddings
    colbert_model = None

print("Embedding models initialized!")
```

### Stage 1: Document Preparation and Embedding Generation

#### Prepare Sample Documents

```python
def create_sample_documents():
    """Create diverse sample documents for demonstration"""
    
    documents = [
        {
            "id": 1,
            "title": "Machine Learning in Healthcare",
            "content": "Machine learning algorithms are revolutionizing healthcare by enabling predictive diagnostics, personalized treatment plans, and drug discovery. Deep learning models can analyze medical images with unprecedented accuracy."
        },
        {
            "id": 2,
            "title": "Natural Language Processing Applications",
            "content": "Natural language processing techniques including transformers, BERT, and GPT models are transforming how computers understand and generate human language. These models excel at tasks like translation, summarization, and question answering."
        },
        {
            "id": 3,
            "title": "Computer Vision and Image Recognition",
            "content": "Computer vision systems using convolutional neural networks can identify objects, faces, and scenes in images and videos. Applications include autonomous vehicles, medical imaging, and augmented reality."
        },
        {
            "id": 4,
            "title": "Reinforcement Learning in Robotics",
            "content": "Reinforcement learning enables robots to learn complex behaviors through trial and error. Applications include robot navigation, manipulation tasks, and human-robot interaction in manufacturing environments."
        },
        {
            "id": 5,
            "title": "Big Data Analytics and Processing",
            "content": "Big data technologies like Apache Spark, Hadoop, and distributed computing frameworks enable processing of massive datasets. Machine learning algorithms can extract insights from petabytes of information."
        }
    ]
    
    return documents

# Create sample dataset
documents = create_sample_documents()
```

#### Generate Dense Embeddings

```python
def generate_dense_embeddings(documents, model):
    """Generate single dense vector per document"""
    
    dense_embeddings = []
    
    for doc in documents:
        # Combine title and content for embedding
        full_text = f"{doc['title']} {doc['content']}"
        
        # Generate dense embedding
        embedding = list(model.embed([full_text]))[0]
        
        dense_embeddings.append({
            "id": doc["id"],
            "text": full_text,
            "dense_vector": embedding.tolist(),
            "title": doc["title"],
            "content": doc["content"]
        })
    
    print(f"Generated dense embeddings for {len(dense_embeddings)} documents")
    return dense_embeddings

# Generate dense embeddings
dense_data = generate_dense_embeddings(documents, dense_model)
```

#### Generate Multivector Embeddings (ColBERT-style)

```python
def generate_multivector_embeddings(documents, model=None):
    """Generate multiple vectors per document (token-level)"""
    
    multivector_data = []
    
    for doc in documents:
        full_text = f"{doc['title']} {doc['content']}"
        
        if model:
            # Use actual ColBERT model if available
            multi_vectors = list(model.embed([full_text]))[0]
        else:
            # Simulate multivector by splitting into chunks
            words = full_text.split()
            chunks = []
            
            # Create overlapping chunks of 5 words
            chunk_size = 5
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                chunks.append(chunk)
            
            # Generate embedding for each chunk
            multi_vectors = []
            for chunk in chunks:
                chunk_embedding = list(dense_model.embed([chunk]))[0]
                multi_vectors.append(chunk_embedding.tolist())
        
        multivector_data.append({
            "id": doc["id"],
            "multi_vectors": multi_vectors,
            "chunks": chunks if not model else None
        })
    
    print(f"Generated multivector embeddings for {len(multivector_data)} documents")
    return multivector_data

# Generate multivector embeddings
multivector_data = generate_multivector_embeddings(documents, colbert_model)
```

### Stage 2: Qdrant Collection Setup

#### Create Collection with Multiple Vector Types

```python
def setup_multivector_collection(client, collection_name="multivector_search"):
    """Create Qdrant collection supporting both dense and multivector storage"""
    
    # Delete existing collection if it exists
    try:
        client.delete_collection(collection_name)
    except:
        pass
    
    # Get vector dimensions
    dense_size = len(dense_data[0]["dense_vector"])
    multi_size = len(multivector_data[0]["multi_vectors"][0])
    
    # Create collection with named vectors
    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            "dense": VectorParams(
                size=dense_size,
                distance=Distance.COSINE
            ),
            "multivector": VectorParams(
                size=multi_size,
                distance=Distance.COSINE,
                multivector_config={
                    "comparator": "max_sim"  # Use MaxSim for multivector comparison
                }
            )
        }
    )
    
    print(f"Created collection '{collection_name}' with dense ({dense_size}D) and multivector ({multi_size}D) support")
    return collection_name

# Initialize Qdrant client and create collection
qdrant_client = QdrantClient("localhost", port=6333)
collection_name = setup_multivector_collection(qdrant_client)
```

#### Index Documents with Both Vector Types

```python
def index_multivector_documents(client, dense_data, multivector_data, collection_name):
    """Index documents with both dense and multivector representations"""
    
    points = []
    
    for dense_doc, multi_doc in zip(dense_data, multivector_data):
        assert dense_doc["id"] == multi_doc["id"], "Document IDs must match"
        
        # Create point with both vector types
        point = PointStruct(
            id=dense_doc["id"],
            vector={
                "dense": dense_doc["dense_vector"],
                "multivector": multi_doc["multi_vectors"]
            },
            payload={
                "title": dense_doc["title"],
                "content": dense_doc["content"],
                "text": dense_doc["text"]
            }
        )
        points.append(point)
    
    # Upload all points
    client.upsert(collection_name=collection_name, points=points)
    
    print(f"Indexed {len(points)} documents with multivector representation")

# Index the documents
index_multivector_documents(qdrant_client, dense_data, multivector_data, collection_name)
```

### Stage 3: Two-Stage Search Implementation

#### Generate Query Embeddings

```python
def generate_query_embeddings(query_text, dense_model, colbert_model=None):
    """Generate both dense and multivector embeddings for query"""
    
    # Dense query embedding
    dense_query = list(dense_model.embed([query_text]))[0].tolist()
    
    # Multivector query embedding
    if colbert_model:
        multi_query = list(colbert_model.embed([query_text]))[0]
    else:
        # Simulate with chunks
        words = query_text.split()
        multi_query = []
        
        if len(words) <= 3:
            # Short query: use as single vector
            multi_query = [list(dense_model.embed([query_text]))[0].tolist()]
        else:
            # Longer query: split into overlapping chunks
            chunk_size = 3
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                chunk_embedding = list(dense_model.embed([chunk]))[0]
                multi_query.append(chunk_embedding.tolist())
    
    return {
        "dense": dense_query,
        "multivector": multi_query
    }

# Test query embedding generation
test_query = "machine learning algorithms for medical diagnosis"
query_embeddings = generate_query_embeddings(test_query, dense_model, colbert_model)

print(f"Query: '{test_query}'")
print(f"Dense embedding size: {len(query_embeddings['dense'])}")
print(f"Multivector embeddings: {len(query_embeddings['multivector'])} vectors")
```

#### Implement Two-Stage Search

```python
def two_stage_search(query_embeddings, client, collection_name, prefetch_limit=100, final_limit=5):
    """Perform two-stage search: dense prefetch + multivector rerank"""
    
    # Stage 1: Dense prefetch for fast candidate retrieval
    prefetch_query = PrefetchQuery(
        prefetch=[
            {
                "using": "dense",
                "query": query_embeddings["dense"],
                "limit": prefetch_limit
            }
        ]
    )
    
    # Stage 2: Multivector reranking for precision
    search_query = Query(
        query=query_embeddings["multivector"],
        using="multivector",
        limit=final_limit
    )
    
    # Execute combined query
    search_results = client.query_points(
        collection_name=collection_name,
        prefetch=[prefetch_query],
        query=search_query
    )
    
    return search_results.points

# Test two-stage search
results = two_stage_search(query_embeddings, qdrant_client, collection_name)

print(f"Two-stage search results for: '{test_query}'")
print(f"Found {len(results)} relevant documents")
print()

for i, result in enumerate(results, 1):
    print(f"{i}. Score: {result.score:.4f}")
    print(f"   Title: {result.payload['title']}")
    print(f"   Content: {result.payload['content'][:100]}...")
    print()
```

#### Compare with Dense-Only Search

```python
def dense_only_search(query_embeddings, client, collection_name, limit=5):
    """Perform dense-only search for comparison"""
    
    search_results = client.search(
        collection_name=collection_name,
        query_vector=NamedVector(
            name="dense",
            vector=query_embeddings["dense"]
        ),
        limit=limit
    )
    
    return search_results

# Compare search approaches
def compare_search_methods(query_text, client, collection_name):
    """Compare dense-only vs two-stage search"""
    
    print(f"Comparing search methods for: '{query_text}'")
    print("=" * 60)
    
    # Generate embeddings
    query_emb = generate_query_embeddings(query_text, dense_model, colbert_model)
    
    # Dense-only search
    dense_results = dense_only_search(query_emb, client, collection_name)
    
    # Two-stage search
    two_stage_results = two_stage_search(query_emb, client, collection_name)
    
    print("DENSE-ONLY SEARCH:")
    for i, result in enumerate(dense_results[:3], 1):
        print(f"  {i}. Score: {result.score:.4f} - {result.payload['title']}")
    
    print("\nTWO-STAGE SEARCH:")
    for i, result in enumerate(two_stage_results[:3], 1):
        print(f"  {i}. Score: {result.score:.4f} - {result.payload['title']}")
    
    print()

# Test different queries
test_queries = [
    "machine learning algorithms for medical diagnosis",
    "natural language processing transformers",
    "computer vision object detection",
    "reinforcement learning robotics applications"
]

for query in test_queries:
    compare_search_methods(query, qdrant_client, collection_name)
```

### Stage 4: Advanced Multivector Techniques

#### Custom MaxSim Implementation

```python
def calculate_maxsim_score(query_vectors, doc_vectors):
    """Calculate MaxSim score between query and document vectors"""
    
    max_scores = []
    
    # For each query vector, find the maximum similarity with any doc vector
    for q_vec in query_vectors:
        similarities = []
        for d_vec in doc_vectors:
            # Calculate cosine similarity
            q_norm = np.linalg.norm(q_vec)
            d_norm = np.linalg.norm(d_vec)
            
            if q_norm > 0 and d_norm > 0:
                similarity = np.dot(q_vec, d_vec) / (q_norm * d_norm)
                similarities.append(similarity)
        
        if similarities:
            max_scores.append(max(similarities))
    
    # Average the maximum similarities
    return sum(max_scores) / len(max_scores) if max_scores else 0

# Test MaxSim calculation
query_vecs = query_embeddings["multivector"]
doc_vecs = multivector_data[0]["multi_vectors"]  # First document

maxsim_score = calculate_maxsim_score(query_vecs, doc_vecs)
print(f"Custom MaxSim score: {maxsim_score:.4f}")
```

#### Hybrid Scoring Strategies

```python
def hybrid_multivector_search(query_text, client, collection_name, 
                            dense_weight=0.3, multivector_weight=0.7):
    """Combine dense and multivector scores with custom weighting"""
    
    query_emb = generate_query_embeddings(query_text, dense_model, colbert_model)
    
    # Get dense search results
    dense_results = dense_only_search(query_emb, client, collection_name, limit=20)
    
    # Get multivector results
    multi_results = two_stage_search(query_emb, client, collection_name, 
                                   prefetch_limit=20, final_limit=20)
    
    # Create combined scoring
    combined_scores = {}
    
    # Add dense scores
    for result in dense_results:
        combined_scores[result.id] = {
            "dense_score": result.score,
            "multi_score": 0,
            "payload": result.payload
        }
    
    # Add multivector scores
    for result in multi_results:
        if result.id in combined_scores:
            combined_scores[result.id]["multi_score"] = result.score
        else:
            combined_scores[result.id] = {
                "dense_score": 0,
                "multi_score": result.score,
                "payload": result.payload
            }
    
    # Calculate combined scores
    final_results = []
    for doc_id, scores in combined_scores.items():
        combined_score = (dense_weight * scores["dense_score"] + 
                         multivector_weight * scores["multi_score"])
        
        final_results.append({
            "id": doc_id,
            "combined_score": combined_score,
            "dense_score": scores["dense_score"],
            "multi_score": scores["multi_score"],
            "payload": scores["payload"]
        })
    
    # Sort by combined score
    final_results.sort(key=lambda x: x["combined_score"], reverse=True)
    
    return final_results[:5]

# Test hybrid search
hybrid_results = hybrid_multivector_search(
    "machine learning medical applications", 
    qdrant_client, 
    collection_name
)

print("HYBRID SEARCH RESULTS:")
for result in hybrid_results:
    print(f"Combined: {result['combined_score']:.4f} "
          f"(Dense: {result['dense_score']:.4f}, Multi: {result['multi_score']:.4f})")
    print(f"Title: {result['payload']['title']}")
    print()
```

## Part 3: Mental Models & Deep Dives

### Understanding Multivector Representation

**Mental Model**: Think of multivector representation like having both a bird's-eye view and a microscope:

**Dense Vector (Bird's-eye view)**:
- Sees the overall landscape quickly
- Good for broad categorization
- Fast but may miss details

**Multivector (Microscope)**:
- Examines every detail carefully
- Finds precise matches
- Slower but highly accurate

### The MaxSim Scoring Mental Model

**Traditional dense similarity**: 
```
Document average: [0.5, 0.3, 0.8]
Query: [0.4, 0.7, 0.2]
Score: single cosine similarity
```

**MaxSim multivector similarity**:
```
Query token: "machine" → [0.8, 0.2, 0.1]
Doc tokens: "medical" → [0.7, 0.3, 0.2]  # High similarity!
            "learning" → [0.1, 0.9, 0.3]  # Low similarity
            "healthcare" → [0.2, 0.1, 0.8]  # Medium similarity

MaxSim: Take the BEST match (0.7 similarity with "medical")
```

### Two-Stage Search Strategy

**Mental Model**: Like a library search system with two phases:

**Phase 1 - Card Catalog (Dense Prefetch)**:
- Quick scan of all books by general topic
- Returns "probably relevant" pile of 100 books
- Fast but approximate

**Phase 2 - Detailed Reading (Multivector Rerank)**:
- Carefully examine each page of the 100 books
- Find exact paragraphs that answer the question
- Slow but precise

### Advanced Multivector Patterns

#### Dynamic Vector Weighting

```python
def adaptive_multivector_search(query_text, client, collection_name):
    """Adapt search strategy based on query characteristics"""
    
    # Analyze query to determine best strategy
    words = query_text.split()
    
    if len(words) <= 2:
        # Short query: dense search is sufficient
        strategy = "dense_only"
        dense_weight, multi_weight = 1.0, 0.0
    elif len(words) <= 5:
        # Medium query: balanced approach
        strategy = "balanced"
        dense_weight, multi_weight = 0.4, 0.6
    else:
        # Long query: multivector excels
        strategy = "multivector_heavy"
        dense_weight, multi_weight = 0.2, 0.8
    
    print(f"Query strategy: {strategy}")
    
    return hybrid_multivector_search(
        query_text, client, collection_name,
        dense_weight, multi_weight
    )
```

#### Token-Level Analysis

```python
def analyze_token_contributions(query_embeddings, search_results, client, collection_name):
    """Analyze which query tokens contribute most to matches"""
    
    token_contributions = {}
    
    # For each result, analyze token-level matches
    for result in search_results[:3]:
        doc_id = result.id
        
        # Retrieve document vectors
        doc_point = client.retrieve(collection_name=collection_name, ids=[doc_id])[0]
        doc_multivectors = doc_point.vector["multivector"]
        
        # Calculate contribution of each query token
        query_tokens = query_embeddings["multivector"]
        
        for i, q_token in enumerate(query_tokens):
            max_sim = 0
            best_doc_token = 0
            
            for j, d_token in enumerate(doc_multivectors):
                sim = np.dot(q_token, d_token) / (np.linalg.norm(q_token) * np.linalg.norm(d_token))
                if sim > max_sim:
                    max_sim = sim
                    best_doc_token = j
            
            token_contributions[f"query_token_{i}"] = {
                "similarity": max_sim,
                "matched_doc_token": best_doc_token
            }
    
    return token_contributions
```

### Performance Optimization

#### Efficient Prefetch Strategies

```python
def optimized_prefetch_search(query_embeddings, client, collection_name):
    """Optimize prefetch parameters based on collection size and query type"""
    
    # Get collection info
    collection_info = client.get_collection(collection_name)
    total_points = collection_info.points_count
    
    # Adaptive prefetch sizing
    if total_points < 1000:
        prefetch_limit = min(50, total_points // 2)
    elif total_points < 10000:
        prefetch_limit = 100
    else:
        prefetch_limit = 200
    
    # Execute optimized search
    return two_stage_search(
        query_embeddings, client, collection_name,
        prefetch_limit=prefetch_limit, final_limit=10
    )
```

#### Batch Multivector Processing

```python
def batch_multivector_indexing(documents, client, collection_name, batch_size=50):
    """Efficiently index large datasets with multivector representation"""
    
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        
        # Generate embeddings for batch
        batch_dense = generate_dense_embeddings(batch, dense_model)
        batch_multi = generate_multivector_embeddings(batch, colbert_model)
        
        # Index batch
        index_multivector_documents(client, batch_dense, batch_multi, collection_name)
        
        print(f"Indexed batch {i//batch_size + 1}")
```

### Real-World Implementation Considerations

#### Quality Monitoring

```python
def evaluate_multivector_performance(test_queries, ground_truth, client, collection_name):
    """Evaluate multivector search quality"""
    
    metrics = {
        "dense_only": {"precision": [], "recall": []},
        "two_stage": {"precision": [], "recall": []}
    }
    
    for query_data in test_queries:
        query = query_data["query"]
        expected_ids = set(query_data["relevant_docs"])
        
        query_emb = generate_query_embeddings(query, dense_model, colbert_model)
        
        # Test dense-only
        dense_results = dense_only_search(query_emb, client, collection_name, limit=5)
        dense_ids = set(r.id for r in dense_results)
        
        # Test two-stage
        two_stage_results = two_stage_search(query_emb, client, collection_name, final_limit=5)
        two_stage_ids = set(r.id for r in two_stage_results)
        
        # Calculate metrics
        for method, result_ids in [("dense_only", dense_ids), ("two_stage", two_stage_ids)]:
            relevant_retrieved = len(expected_ids & result_ids)
            precision = relevant_retrieved / len(result_ids) if result_ids else 0
            recall = relevant_retrieved / len(expected_ids) if expected_ids else 0
            
            metrics[method]["precision"].append(precision)
            metrics[method]["recall"].append(recall)
    
    # Average metrics
    for method in metrics:
        for metric in metrics[method]:
            metrics[method][metric] = sum(metrics[method][metric]) / len(metrics[method][metric])
    
    return metrics
```

#### Cost-Benefit Analysis

```python
def analyze_search_costs():
    """Analyze computational costs of different search strategies"""
    
    costs = {
        "dense_only": {
            "storage": "1x (single vector per doc)",
            "query_time": "Fast (single vector comparison)",
            "accuracy": "Good for general queries"
        },
        "multivector_only": {
            "storage": "10-50x (multiple vectors per doc)",
            "query_time": "Slow (many comparisons)",
            "accuracy": "Excellent for specific queries"
        },
        "two_stage": {
            "storage": "11-51x (both vector types)",
            "query_time": "Medium (fast prefetch + precise rerank)",
            "accuracy": "Best of both worlds"
        }
    }
    
    return costs
```

This comprehensive multivector search system demonstrates how to build sophisticated retrieval systems that balance speed and precision, enabling both broad discovery and exact matching within a single, efficient architecture.