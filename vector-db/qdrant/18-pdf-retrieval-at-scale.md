# PDF Retrieval at Scale

> **Source**: [pdf-retrieval-at-scale](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/pdf-retrieval-at-scale)

This tutorial demonstrates how to build a scalable PDF document retrieval system using Vision Language Models (ColPali/ColQwen2) and Qdrant, implementing optimized two-stage retrieval to handle large-scale document collections efficiently.

## Part 1: Core Concept - Why Scalable PDF Retrieval Matters

### The PDF Processing Challenge

PDF documents contain rich multimodal information that traditional text-based systems struggle to capture:

- **Visual layout**: Tables, charts, diagrams, and formatting carry semantic meaning
- **OCR limitations**: Text extraction often fails with complex layouts or poor scan quality
- **Context loss**: Breaking PDFs into text chunks loses spatial and visual relationships
- **Scale problems**: Processing thousands of PDFs with traditional methods is computationally prohibitive

**Example limitation**: A research paper with complex mathematical equations and diagrams would lose crucial visual context when converted to plain text for traditional vector search.

### The Vision Language Model Revolution

Modern VLMs like ColPali and ColQwen2 treat PDF pages as images, understanding both text and visual elements:

- **End-to-end processing**: No OCR required, handles any PDF layout
- **Visual understanding**: Comprehends charts, tables, diagrams, and spatial relationships
- **Multimodal embeddings**: Captures both textual and visual semantic information
- **High accuracy**: Superior performance on complex document types

**The scaling problem**: VLMs generate 700-1000+ vectors per PDF page, making direct indexing computationally expensive.

### The Two-Stage Solution

This tutorial shows how to scale VLM-based PDF retrieval using vector compression and two-stage search:

**Stage 1**: Fast retrieval using compressed vectors (mean pooling)
**Stage 2**: Precise reranking using full-resolution vectors

**What you'll build**: A production-ready PDF retrieval system that handles thousands of documents efficiently while maintaining the accuracy benefits of vision language models.

### Real-World Applications

- **Academic Research**: Search through thousands of research papers with complex figures
- **Legal Discovery**: Find relevant documents in massive legal document collections
- **Technical Documentation**: Navigate complex manuals with diagrams and schematics
- **Financial Analysis**: Search reports containing charts, tables, and financial data

## Part 2: Practical Walkthrough - Building Scalable PDF Retrieval

### Understanding the Scaling Architecture

The system balances speed and accuracy through strategic vector compression:

```
PDF Pages → [VLM] → Heavy Vectors (1000+ per page)
                         ↓
Heavy Vectors → [Mean Pooling] → Light Vectors (32 per page)
                                      ↓
Query → [Fast Search] → Candidates → [Heavy Rerank] → Results
```

**Key insight**: Use lightweight vectors for broad retrieval, heavyweight vectors for precise ranking.

### Setup and Dependencies

```python
# Core dependencies for PDF retrieval at scale
!pip install qdrant-client colpali-engine torch torchvision pdf2image pillow

import torch
from PIL import Image
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Tuple

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, NamedVector

# ColPali/ColQwen2 imports
from colpali_engine.models import ColPali, ColQwen2
from colpali_engine.utils.processing_utils import process_images, process_queries
```

**Key components:**
- `colpali-engine`: State-of-the-art vision language models for PDFs
- `qdrant-client`: Vector database with multi-vector support
- `pdf2image`: Convert PDF pages to images for VLM processing
- `torch`: Deep learning framework for model execution

### Initialize Vision Language Models

```python
# Initialize Qdrant client
qdrant_client = QdrantClient("localhost", port=6333)

# Load ColPali model (alternative: ColQwen2)
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")

# Choose model: ColPali or ColQwen2
MODEL_NAME = "vidore/colpali"  # or "vidore/colqwen2-v0.1"

if "colpali" in MODEL_NAME.lower():
    model = ColPali.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.bfloat16,
        device_map=device
    )
else:
    model = ColQwen2.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.bfloat16,
        device_map=device
    )

print(f"Loaded {MODEL_NAME} model")
```

### Stage 1: PDF Processing and Vector Generation

#### Convert PDFs to Images

```python
from pdf2image import convert_from_path

def pdf_to_images(pdf_path: str, dpi: int = 200) -> List[Image.Image]:
    """Convert PDF pages to PIL Images"""
    
    try:
        images = convert_from_path(pdf_path, dpi=dpi)
        print(f"Converted {len(images)} pages from {pdf_path}")
        return images
    except Exception as e:
        print(f"Error converting {pdf_path}: {e}")
        return []

def process_pdf_directory(pdf_dir: str) -> Dict[str, List[Image.Image]]:
    """Process all PDFs in a directory"""
    
    pdf_path = Path(pdf_dir)
    pdf_images = {}
    
    for pdf_file in pdf_path.glob("*.pdf"):
        images = pdf_to_images(str(pdf_file))
        if images:
            pdf_images[pdf_file.stem] = images
    
    return pdf_images

# Process sample PDFs
pdf_directory = "sample_pdfs/"  # Your PDF directory
pdf_collections = process_pdf_directory(pdf_directory)

print(f"Processed {len(pdf_collections)} PDF documents")
for doc_name, images in pdf_collections.items():
    print(f"  {doc_name}: {len(images)} pages")
```

#### Generate Heavy Vector Embeddings

```python
def generate_heavy_embeddings(images: List[Image.Image], model) -> np.ndarray:
    """Generate full-resolution embeddings using VLM"""
    
    # Process images for the model
    processed_images = process_images(images)
    
    with torch.no_grad():
        # Generate embeddings
        embeddings = model(**processed_images)
        
        # Convert to numpy and handle batching
        if isinstance(embeddings, torch.Tensor):
            embeddings = embeddings.cpu().numpy()
        
        return embeddings

def process_document_embeddings(pdf_collections, model):
    """Generate heavy embeddings for all documents"""
    
    heavy_embeddings = {}
    
    for doc_name, images in pdf_collections.items():
        print(f"Processing embeddings for {doc_name}...")
        
        page_embeddings = []
        
        # Process each page
        for i, image in enumerate(images):
            try:
                # Generate embedding for single page
                page_embedding = generate_heavy_embeddings([image], model)
                page_embeddings.append(page_embedding)
                
                print(f"  Page {i+1}: {page_embedding.shape}")
                
            except Exception as e:
                print(f"  Error processing page {i+1}: {e}")
                continue
        
        heavy_embeddings[doc_name] = page_embeddings
    
    return heavy_embeddings

# Generate heavy embeddings for all documents
heavy_embeddings = process_document_embeddings(pdf_collections, model)
```

#### Vector Compression via Mean Pooling

```python
def apply_mean_pooling(heavy_vectors: np.ndarray, pool_type: str = "both") -> Dict[str, np.ndarray]:
    """Apply mean pooling to reduce vector dimensionality"""
    
    pooled_vectors = {}
    
    if heavy_vectors.ndim == 3:  # [patches_h, patches_w, embedding_dim]
        if pool_type in ["rows", "both"]:
            # Pool across rows (average vertically)
            pooled_vectors["mean_pooling_rows"] = np.mean(heavy_vectors, axis=0)
            
        if pool_type in ["columns", "both"]:
            # Pool across columns (average horizontally)  
            pooled_vectors["mean_pooling_columns"] = np.mean(heavy_vectors, axis=1)
            
        if pool_type == "both":
            # Also create full pooling
            pooled_vectors["mean_pooling_full"] = np.mean(heavy_vectors, axis=(0, 1))
    
    elif heavy_vectors.ndim == 2:  # [patches, embedding_dim]
        # Simple mean pooling for 2D vectors
        pooled_vectors["mean_pooling_simple"] = np.mean(heavy_vectors, axis=0)
    
    return pooled_vectors

def create_lightweight_vectors(heavy_embeddings):
    """Create compressed vectors for all documents"""
    
    lightweight_embeddings = {}
    
    for doc_name, page_embeddings in heavy_embeddings.items():
        lightweight_embeddings[doc_name] = []
        
        print(f"Creating lightweight vectors for {doc_name}...")
        
        for i, heavy_vector in enumerate(page_embeddings):
            # Apply mean pooling
            light_vectors = apply_mean_pooling(heavy_vector, pool_type="both")
            
            # Store both heavy and light vectors
            lightweight_embeddings[doc_name].append({
                "page_id": i,
                "heavy_vector": heavy_vector,
                "light_vectors": light_vectors
            })
            
            print(f"  Page {i+1}: Heavy {heavy_vector.shape} → Light {len(light_vectors)} vectors")
    
    return lightweight_embeddings

# Create lightweight vectors
all_embeddings = create_lightweight_vectors(heavy_embeddings)
```

### Stage 2: Optimized Qdrant Collection Setup

#### Create Multi-Vector Collection with Compression

```python
def setup_scalable_pdf_collection(client, collection_name="scalable_pdf_retrieval"):
    """Create Qdrant collection optimized for large-scale PDF retrieval"""
    
    # Delete existing collection
    try:
        client.delete_collection(collection_name)
    except:
        pass
    
    # Get vector dimensions from first document
    first_doc = next(iter(all_embeddings.values()))
    first_page = first_doc[0]
    
    heavy_vector = first_page["heavy_vector"]
    light_vectors = first_page["light_vectors"]
    
    # Determine dimensions
    if heavy_vector.ndim == 3:
        # 3D heavy vector: flatten for storage
        heavy_dim = heavy_vector.shape[0] * heavy_vector.shape[1] * heavy_vector.shape[2]
    else:
        heavy_dim = heavy_vector.shape[-1]
    
    # Light vector dimensions
    light_dims = {name: vec.shape[-1] for name, vec in light_vectors.items()}
    
    # Create vector configuration
    vectors_config = {
        "heavy": VectorParams(
            size=heavy_dim,
            distance=Distance.COSINE,
            # Disable HNSW for heavy vectors (only used for reranking)
            hnsw_config={"m": 0}  # Disable indexing
        )
    }
    
    # Add light vector configurations
    for light_name, dim in light_dims.items():
        vectors_config[light_name] = VectorParams(
            size=dim,
            distance=Distance.COSINE,
            # Enable HNSW for fast retrieval
            hnsw_config={"m": 16, "ef_construct": 100}
        )
    
    # Create collection
    client.create_collection(
        collection_name=collection_name,
        vectors_config=vectors_config
    )
    
    print(f"Created collection '{collection_name}' with:")
    print(f"  Heavy vectors: {heavy_dim}D (HNSW disabled)")
    for light_name, dim in light_dims.items():
        print(f"  {light_name}: {dim}D (HNSW enabled)")
    
    return collection_name

# Setup optimized collection
collection_name = setup_scalable_pdf_collection(qdrant_client)
```

#### Index Documents with Vector Compression

```python
def index_pdf_documents(client, embeddings_data, collection_name):
    """Index PDF documents with both heavy and light vectors"""
    
    points = []
    point_id = 0
    
    for doc_name, page_data in embeddings_data.items():
        for page_info in page_data:
            page_id = page_info["page_id"]
            heavy_vector = page_info["heavy_vector"]
            light_vectors = page_info["light_vectors"]
            
            # Prepare heavy vector (flatten if needed)
            if heavy_vector.ndim > 2:
                heavy_flat = heavy_vector.flatten()
            else:
                heavy_flat = heavy_vector.flatten() if heavy_vector.ndim == 2 else heavy_vector
            
            # Prepare vector dictionary
            vector_dict = {
                "heavy": heavy_flat.tolist()
            }
            
            # Add light vectors
            for light_name, light_vec in light_vectors.items():
                vector_dict[light_name] = light_vec.flatten().tolist()
            
            # Create point
            point = PointStruct(
                id=point_id,
                vector=vector_dict,
                payload={
                    "document_name": doc_name,
                    "page_id": page_id,
                    "total_pages": len(page_data)
                }
            )
            
            points.append(point)
            point_id += 1
    
    # Batch upload
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        client.upsert(collection_name=collection_name, points=batch)
        print(f"Uploaded batch {i//batch_size + 1}/{(len(points) + batch_size - 1)//batch_size}")
    
    print(f"Successfully indexed {len(points)} PDF pages")

# Index all documents
index_pdf_documents(qdrant_client, all_embeddings, collection_name)
```

### Stage 3: Two-Stage Query Implementation

#### Query Processing

```python
def process_query(query_text: str, model) -> Dict[str, np.ndarray]:
    """Process text query to generate embeddings"""
    
    # Generate query embedding using the VLM
    processed_query = process_queries([query_text])
    
    with torch.no_grad():
        query_embedding = model(**processed_query)
        
        if isinstance(query_embedding, torch.Tensor):
            query_embedding = query_embedding.cpu().numpy()
    
    # Create both heavy and light query vectors
    heavy_query = query_embedding
    light_queries = apply_mean_pooling(query_embedding, pool_type="both")
    
    return {
        "heavy": heavy_query,
        "light": light_queries
    }

# Test query processing
test_query = "machine learning algorithms for image recognition"
query_vectors = process_query(test_query, model)

print(f"Query: '{test_query}'")
print(f"Heavy query shape: {query_vectors['heavy'].shape}")
print(f"Light queries: {list(query_vectors['light'].keys())}")
```

#### Two-Stage Retrieval Implementation

```python
def two_stage_pdf_search(
    query_vectors: Dict[str, np.ndarray],
    client: QdrantClient,
    collection_name: str,
    prefetch_limit: int = 100,
    final_limit: int = 10,
    light_vector_name: str = "mean_pooling_rows"
) -> List[Dict[str, Any]]:
    """Perform two-stage PDF retrieval: light prefetch + heavy rerank"""
    
    # Stage 1: Fast prefetch using light vectors
    light_query = query_vectors["light"][light_vector_name].flatten()
    
    prefetch_results = client.search(
        collection_name=collection_name,
        query_vector=NamedVector(
            name=light_vector_name,
            vector=light_query.tolist()
        ),
        limit=prefetch_limit
    )
    
    print(f"Stage 1: Retrieved {len(prefetch_results)} candidates using {light_vector_name}")
    
    # Stage 2: Precise reranking using heavy vectors
    if not prefetch_results:
        return []
    
    # Get candidate IDs
    candidate_ids = [result.id for result in prefetch_results]
    
    # Retrieve heavy vectors for candidates
    candidate_points = client.retrieve(
        collection_name=collection_name,
        ids=candidate_ids
    )
    
    # Rerank using heavy vector similarity
    heavy_query = query_vectors["heavy"].flatten()
    reranked_results = []
    
    for point in candidate_points:
        heavy_vector = np.array(point.vector["heavy"])
        
        # Calculate cosine similarity
        similarity = np.dot(heavy_query, heavy_vector) / (
            np.linalg.norm(heavy_query) * np.linalg.norm(heavy_vector)
        )
        
        reranked_results.append({
            "id": point.id,
            "score": similarity,
            "payload": point.payload
        })
    
    # Sort by similarity score
    reranked_results.sort(key=lambda x: x["score"], reverse=True)
    
    print(f"Stage 2: Reranked to top {min(final_limit, len(reranked_results))} results")
    
    return reranked_results[:final_limit]

# Test two-stage search
results = two_stage_pdf_search(
    query_vectors, 
    qdrant_client, 
    collection_name,
    prefetch_limit=50,
    final_limit=5
)

print(f"\nTop results for: '{test_query}'")
for i, result in enumerate(results, 1):
    print(f"{i}. Score: {result['score']:.4f}")
    print(f"   Document: {result['payload']['document_name']}")
    print(f"   Page: {result['payload']['page_id'] + 1}")
    print()
```

#### Advanced Query Strategies

```python
def adaptive_pdf_search(
    query_text: str,
    client: QdrantClient,
    collection_name: str,
    model
) -> Dict[str, List[Dict[str, Any]]]:
    """Try multiple light vector strategies and combine results"""
    
    query_vectors = process_query(query_text, model)
    strategies = ["mean_pooling_rows", "mean_pooling_columns"]
    
    all_results = {}
    
    for strategy in strategies:
        if strategy in query_vectors["light"]:
            results = two_stage_pdf_search(
                query_vectors,
                client,
                collection_name,
                light_vector_name=strategy,
                final_limit=10
            )
            all_results[strategy] = results
    
    return all_results

def combine_strategy_results(strategy_results: Dict[str, List[Dict]], top_k: int = 5):
    """Combine results from multiple strategies"""
    
    # Collect all unique results
    all_results = {}
    
    for strategy, results in strategy_results.items():
        for result in results:
            doc_page_key = f"{result['payload']['document_name']}_page_{result['payload']['page_id']}"
            
            if doc_page_key not in all_results:
                all_results[doc_page_key] = {
                    "id": result["id"],
                    "payload": result["payload"],
                    "scores": {}
                }
            
            all_results[doc_page_key]["scores"][strategy] = result["score"]
    
    # Calculate combined scores
    final_results = []
    for key, data in all_results.items():
        # Average scores across strategies
        avg_score = sum(data["scores"].values()) / len(data["scores"])
        
        final_results.append({
            "id": data["id"],
            "combined_score": avg_score,
            "strategy_scores": data["scores"],
            "payload": data["payload"]
        })
    
    # Sort by combined score
    final_results.sort(key=lambda x: x["combined_score"], reverse=True)
    
    return final_results[:top_k]

# Test adaptive search
adaptive_results = adaptive_pdf_search(
    "financial charts and data analysis",
    qdrant_client,
    collection_name,
    model
)

combined_results = combine_strategy_results(adaptive_results)

print("ADAPTIVE SEARCH RESULTS:")
for result in combined_results:
    print(f"Combined Score: {result['combined_score']:.4f}")
    print(f"Document: {result['payload']['document_name']}")
    print(f"Page: {result['payload']['page_id'] + 1}")
    print(f"Strategy Scores: {result['strategy_scores']}")
    print()
```

## Part 3: Mental Models & Deep Dives

### Understanding Vector Compression

**Mental Model**: Think of vector compression like creating multiple views of the same photograph:

**Heavy Vector (Original Photo)**:
- Full resolution: 4K image with every detail
- Large file size: Takes time to load and compare
- Perfect accuracy: Shows everything

**Light Vector (Thumbnail)**:
- Compressed: Small file, loads instantly
- Good enough: Captures main features for quick recognition
- Fast comparison: Can quickly scan hundreds of thumbnails

### Two-Stage Search Strategy

**Mental Model**: Like a library with an efficient filing system:

**Stage 1 - Card Catalog (Light Vectors)**:
- Quick scan of index cards
- Broad topic matching
- Identifies "probably relevant" section

**Stage 2 - Detailed Reading (Heavy Vectors)**:
- Carefully examine the actual books
- Precise content analysis
- Final ranking by relevance

### Vision Language Model Understanding

**ColPali/ColQwen2 Processing**:
```python
# VLM sees PDF as image patches
pdf_page = [
    [patch_1_1, patch_1_2, patch_1_3],  # Top row
    [patch_2_1, patch_2_2, patch_2_3],  # Middle row  
    [patch_3_1, patch_3_2, patch_3_3]   # Bottom row
]

# Each patch gets an embedding
embeddings = [
    [emb_1_1, emb_1_2, emb_1_3],
    [emb_2_1, emb_2_2, emb_2_3],
    [emb_3_1, emb_3_2, emb_3_3]
]

# Mean pooling reduces dimensions
row_pooled = [mean(row_1), mean(row_2), mean(row_3)]      # 9 → 3 vectors
col_pooled = [mean(col_1), mean(col_2), mean(col_3)]      # 9 → 3 vectors
full_pooled = mean(all_patches)                           # 9 → 1 vector
```

### Advanced Optimization Techniques

#### Dynamic Pooling Strategies

```python
def adaptive_pooling(heavy_vector: np.ndarray, target_size: int) -> np.ndarray:
    """Adaptively pool vectors based on content density"""
    
    if heavy_vector.ndim == 3:
        h, w, d = heavy_vector.shape
        
        # Calculate patch importance (variance as proxy)
        importance = np.var(heavy_vector, axis=2)
        
        # Keep most important patches
        flat_importance = importance.flatten()
        top_indices = np.argsort(flat_importance)[-target_size:]
        
        # Extract top patches
        important_vectors = []
        for idx in top_indices:
            row, col = divmod(idx, w)
            important_vectors.append(heavy_vector[row, col])
        
        return np.array(important_vectors)
    
    return heavy_vector

def content_aware_compression(heavy_embeddings, compression_ratio=0.1):
    """Compress vectors based on content importance"""
    
    compressed_embeddings = {}
    
    for doc_name, page_data in heavy_embeddings.items():
        compressed_embeddings[doc_name] = []
        
        for page_info in page_data:
            heavy_vector = page_info["heavy_vector"]
            
            # Calculate target size
            if heavy_vector.ndim == 3:
                total_patches = heavy_vector.shape[0] * heavy_vector.shape[1]
            else:
                total_patches = heavy_vector.shape[0]
            
            target_size = max(1, int(total_patches * compression_ratio))
            
            # Apply adaptive pooling
            compressed_vector = adaptive_pooling(heavy_vector, target_size)
            
            compressed_embeddings[doc_name].append({
                "page_id": page_info["page_id"],
                "heavy_vector": heavy_vector,
                "compressed_vector": compressed_vector
            })
    
    return compressed_embeddings
```

#### Caching and Performance Optimization

```python
import functools
import hashlib
from typing import LRU_Cache

# Cache for query embeddings
query_cache = {}

def cached_query_processing(func):
    """Cache query embeddings to avoid recomputation"""
    
    @functools.wraps(func)
    def wrapper(query_text, model):
        # Create cache key
        cache_key = hashlib.md5(query_text.encode()).hexdigest()
        
        if cache_key not in query_cache:
            query_cache[cache_key] = func(query_text, model)
        
        return query_cache[cache_key]
    
    return wrapper

@cached_query_processing
def cached_process_query(query_text: str, model):
    """Cached version of query processing"""
    return process_query(query_text, model)

# Batch processing for large document collections
def batch_pdf_processing(pdf_paths: List[str], model, batch_size: int = 5):
    """Process PDFs in batches to manage memory"""
    
    all_embeddings = {}
    
    for i in range(0, len(pdf_paths), batch_size):
        batch_paths = pdf_paths[i:i + batch_size]
        
        print(f"Processing batch {i//batch_size + 1}/{(len(pdf_paths) + batch_size - 1)//batch_size}")
        
        # Process batch
        batch_collections = {}
        for pdf_path in batch_paths:
            images = pdf_to_images(pdf_path)
            if images:
                batch_collections[Path(pdf_path).stem] = images
        
        # Generate embeddings for batch
        batch_embeddings = process_document_embeddings(batch_collections, model)
        
        # Create lightweight vectors
        batch_lightweight = create_lightweight_vectors(batch_embeddings)
        
        # Add to main collection
        all_embeddings.update(batch_lightweight)
        
        # Clear GPU memory
        torch.cuda.empty_cache()
    
    return all_embeddings
```

### Production Deployment Considerations

#### Monitoring and Metrics

```python
def monitor_retrieval_performance():
    """Monitor system performance metrics"""
    
    metrics = {
        "query_latency": {
            "stage_1_avg": 0.0,  # Light vector search time
            "stage_2_avg": 0.0,  # Heavy vector rerank time
            "total_avg": 0.0
        },
        "memory_usage": {
            "light_vectors_mb": 0.0,
            "heavy_vectors_mb": 0.0,
            "total_mb": 0.0
        },
        "accuracy_metrics": {
            "precision_at_5": 0.0,
            "recall_at_10": 0.0,
            "mrr": 0.0  # Mean Reciprocal Rank
        }
    }
    
    return metrics

def optimize_collection_parameters(client, collection_name):
    """Optimize Qdrant collection for better performance"""
    
    # Get collection info
    collection_info = client.get_collection(collection_name)
    
    # Optimize HNSW parameters based on collection size
    if collection_info.points_count > 10000:
        # Large collection: optimize for speed
        hnsw_config = {"m": 16, "ef_construct": 200}
    else:
        # Small collection: optimize for accuracy
        hnsw_config = {"m": 32, "ef_construct": 400}
    
    # Update collection configuration
    client.update_collection(
        collection_name=collection_name,
        vectors_config={
            "mean_pooling_rows": VectorParams(
                distance=Distance.COSINE,
                hnsw_config=hnsw_config
            )
        }
    )
```

#### Incremental Updates

```python
def incremental_pdf_update(
    new_pdf_path: str,
    client: QdrantClient,
    collection_name: str,
    model
):
    """Add new PDF to existing collection"""
    
    # Process new PDF
    images = pdf_to_images(new_pdf_path)
    if not images:
        return
    
    doc_name = Path(new_pdf_path).stem
    
    # Generate embeddings
    page_embeddings = []
    for image in images:
        embedding = generate_heavy_embeddings([image], model)
        page_embeddings.append(embedding)
    
    # Create lightweight vectors
    lightweight_data = create_lightweight_vectors({doc_name: page_embeddings})
    
    # Get current max ID
    collection_info = client.get_collection(collection_name)
    start_id = collection_info.points_count
    
    # Index new document
    index_pdf_documents(client, lightweight_data, collection_name)
    
    print(f"Added {doc_name} with {len(images)} pages to collection")
```

This comprehensive PDF retrieval system demonstrates how to build production-ready document search that scales to thousands of PDFs while maintaining the accuracy benefits of modern vision language models.