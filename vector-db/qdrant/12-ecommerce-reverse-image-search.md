# E-commerce Reverse Image Search

> **Source**: [ecommerce_reverse_image_search](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/ecommerce_reverse_image_search)

This tutorial demonstrates how to build a reverse image search system for an e-commerce product catalog using Qdrant and CLIP embeddings, enabling customers to find visually similar products by uploading images.

## Part 1: Core Concept - Why Reverse Image Search Matters

### The E-commerce Discovery Problem

Traditional e-commerce search relies on text queries, but shoppers often struggle to describe what they're looking for:

- **"I want a blue dress like the one I saw"** - Hard to describe style, cut, or exact shade
- **"Find me something similar to this"** - Customer has a reference image but no keywords
- **Visual browsing behavior** - Many customers are visual learners who think in images, not words
- **Cross-language barriers** - Product descriptions may not match customer's language

### The Power of Visual Search

Reverse image search solves these problems by understanding visual similarity:

- **Upload and find**: Customer uploads a photo, system finds visually similar products
- **Style matching**: Identify products with similar colors, patterns, shapes, and textures
- **Cross-category discovery**: Find similar items across different product categories
- **Inspiration shopping**: "Show me more like this" browsing experience

**What you'll build**: A complete reverse image search system that processes product images, generates embeddings using CLIP, stores them in Qdrant, and enables similarity search for visual product discovery.

### Real-World Impact

- **Increased conversion**: Visual search users convert 30% more than text search users
- **Reduced bounce rate**: Customers find relevant products faster
- **Enhanced discovery**: Exposes products customers wouldn't find through text search
- **Competitive advantage**: Provides modern shopping experience expected by users

## Part 2: Practical Walkthrough - Building the Search System

### Setup and Dependencies

The reverse image search system requires computer vision and vector database libraries:

```python
# Core dependencies for image search
!pip install qdrant-client sentence-transformers pandas requests pillow

import pandas as pd
import requests
from PIL import Image
import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
import numpy as np
```

**Key components:**
- `sentence-transformers`: CLIP model for image embeddings
- `qdrant-client`: Vector database for similarity search
- `PIL`: Image processing and manipulation
- `pandas`: Dataset handling and manipulation
- `requests`: Image downloading from URLs

### Initialize Core Services

```python
# Initialize Qdrant client
qdrant_client = QdrantClient("localhost", port=6333)

# Load CLIP model for image embeddings
model = SentenceTransformer('clip-ViT-B-32')
print(f"Model loaded. Embedding dimension: {model.get_sentence_embedding_dimension()}")
```

**Why CLIP?**
- **Multimodal**: Understands both images and text
- **Pre-trained**: Learned visual concepts from millions of image-text pairs
- **Semantic understanding**: Captures high-level visual concepts, not just pixels
- **Efficient**: Produces compact 512-dimensional embeddings

### Stage 1: Dataset Preparation and Image Acquisition

#### Load E-commerce Dataset

```python
# Load Amazon product dataset
dataset_url = "https://raw.githubusercontent.com/qdrant/examples/master/ecommerce-reverse-image-search/fashion_dataset.csv"
df = pd.read_csv(dataset_url)

print(f"Dataset shape: {df.shape}")
print(f"Columns: {df.columns.tolist()}")

# Examine sample data
print("\nSample products:")
print(df[['product_name', 'selling_price', 'image']].head())
```

#### Clean and Validate Image URLs

```python
def is_valid_image_url(url):
    """Check if URL points to a valid image"""
    if pd.isna(url) or not isinstance(url, str):
        return False
    
    # Check for image file extensions
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
    return any(url.lower().endswith(ext) for ext in image_extensions)

# Filter valid image URLs
df['valid_image'] = df['image'].apply(is_valid_image_url)
valid_df = df[df['valid_image']].copy()

print(f"Products with valid images: {len(valid_df)}")
print(f"Filtered out: {len(df) - len(valid_df)} products")
```

#### Download Product Images

```python
def download_image(url, filename, max_retries=3):
    """Download image with retry logic"""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=10, stream=True)
            response.raise_for_status()
            
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"Attempt {attempt + 1} failed for {url}: {e}")
            if attempt == max_retries - 1:
                return False
    return False

# Create images directory
os.makedirs("product_images", exist_ok=True)

# Download images
successful_downloads = []
for idx, row in valid_df.iterrows():
    image_filename = f"product_images/product_{idx}.jpg"
    
    if download_image(row['image'], image_filename):
        successful_downloads.append({
            'index': idx,
            'filename': image_filename,
            'product_name': row['product_name'],
            'selling_price': row['selling_price'],
            'original_url': row['image']
        })
    
    # Progress indicator
    if len(successful_downloads) % 50 == 0:
        print(f"Downloaded {len(successful_downloads)} images...")

print(f"Successfully downloaded {len(successful_downloads)} images")
```

### Stage 2: Image Embedding Generation

#### Process Images and Generate Embeddings

```python
def load_and_preprocess_image(image_path):
    """Load and preprocess image for CLIP model"""
    try:
        image = Image.open(image_path).convert('RGB')
        # CLIP handles resizing internally
        return image
    except Exception as e:
        print(f"Error loading {image_path}: {e}")
        return None

# Generate embeddings for all downloaded images
embeddings_data = []
batch_size = 32  # Process in batches for efficiency

for i in range(0, len(successful_downloads), batch_size):
    batch = successful_downloads[i:i + batch_size]
    images = []
    valid_items = []
    
    # Load batch of images
    for item in batch:
        image = load_and_preprocess_image(item['filename'])
        if image is not None:
            images.append(image)
            valid_items.append(item)
    
    if images:
        # Generate embeddings for batch
        batch_embeddings = model.encode(images)
        
        # Store embeddings with metadata
        for embedding, item in zip(batch_embeddings, valid_items):
            embeddings_data.append({
                'embedding': embedding.tolist(),
                'product_name': item['product_name'],
                'selling_price': item['selling_price'],
                'image_path': item['filename'],
                'product_id': item['index']
            })
    
    print(f"Processed {len(embeddings_data)} products...")

print(f"Generated embeddings for {len(embeddings_data)} products")
```

### Stage 3: Vector Database Setup and Indexing

#### Create Qdrant Collection

```python
# Collection configuration
collection_name = "ecommerce_products"
embedding_size = 512  # CLIP ViT-B/32 embedding dimension

# Create collection
qdrant_client.recreate_collection(
    collection_name=collection_name,
    vectors_config=VectorParams(
        size=embedding_size,
        distance=Distance.COSINE  # Best for CLIP embeddings
    )
)

print(f"Created collection '{collection_name}' with {embedding_size}D vectors")
```

#### Upload Product Data to Qdrant

```python
# Prepare points for upload
points = []
for i, item in enumerate(embeddings_data):
    point = PointStruct(
        id=i,
        vector=item['embedding'],
        payload={
            "product_name": item['product_name'],
            "selling_price": float(item['selling_price']) if item['selling_price'] else 0.0,
            "image_path": item['image_path'],
            "product_id": item['product_id']
        }
    )
    points.append(point)

# Upload in batches
batch_size = 100
for i in range(0, len(points), batch_size):
    batch = points[i:i + batch_size]
    qdrant_client.upsert(
        collection_name=collection_name,
        points=batch
    )
    print(f"Uploaded batch {i//batch_size + 1}/{(len(points) + batch_size - 1)//batch_size}")

print(f"Successfully indexed {len(points)} products in Qdrant")
```

### Stage 4: Implementing Reverse Image Search

#### Search Function

```python
def search_similar_products(query_image_path, top_k=5):
    """Search for visually similar products"""
    
    # Load and encode query image
    query_image = load_and_preprocess_image(query_image_path)
    if query_image is None:
        return []
    
    # Generate embedding for query image
    query_embedding = model.encode([query_image])[0]
    
    # Search in Qdrant
    search_results = qdrant_client.search(
        collection_name=collection_name,
        query_vector=query_embedding.tolist(),
        limit=top_k
    )
    
    # Format results
    results = []
    for result in search_results:
        results.append({
            'product_name': result.payload['product_name'],
            'selling_price': result.payload['selling_price'],
            'similarity_score': result.score,
            'image_path': result.payload['image_path'],
            'product_id': result.payload['product_id']
        })
    
    return results

# Example search
query_image = "path/to/query/image.jpg"  # Replace with actual image path
similar_products = search_similar_products(query_image, top_k=10)

print("Similar products found:")
for i, product in enumerate(similar_products, 1):
    print(f"{i}. {product['product_name']}")
    print(f"   Price: ${product['selling_price']}")
    print(f"   Similarity: {product['similarity_score']:.3f}")
    print(f"   Image: {product['image_path']}")
    print()
```

#### Advanced Search with Price Filtering

```python
from qdrant_client.models import Filter, Range, FieldCondition

def search_with_price_filter(query_image_path, min_price=0, max_price=1000, top_k=5):
    """Search with price range filtering"""
    
    query_image = load_and_preprocess_image(query_image_path)
    if query_image is None:
        return []
    
    query_embedding = model.encode([query_image])[0]
    
    # Create price filter
    price_filter = Filter(
        must=[
            FieldCondition(
                key="selling_price",
                range=Range(gte=min_price, lte=max_price)
            )
        ]
    )
    
    # Search with filter
    search_results = qdrant_client.search(
        collection_name=collection_name,
        query_vector=query_embedding.tolist(),
        query_filter=price_filter,
        limit=top_k
    )
    
    # Format and return results
    results = []
    for result in search_results:
        results.append({
            'product_name': result.payload['product_name'],
            'selling_price': result.payload['selling_price'],
            'similarity_score': result.score,
            'image_path': result.payload['image_path']
        })
    
    return results

# Search for similar products under $50
affordable_similar = search_with_price_filter(
    query_image, 
    min_price=0, 
    max_price=50, 
    top_k=5
)
```

## Part 3: Mental Models & Deep Dives

### Understanding CLIP Embeddings

**Mental Model**: Think of CLIP as a translator that converts images into a universal "visual language" where similar-looking items are clustered together.

**How CLIP works**:
- **Vision Transformer**: Breaks images into patches, understands spatial relationships
- **Semantic Understanding**: Learns concepts like "blue dress," "running shoes," "wooden table"
- **Cross-modal Training**: Trained on image-text pairs, understands both visual and semantic similarity

```python
# Visualizing the embedding space concept
# Similar products cluster together in 512-dimensional space
# Distance = visual similarity

Image A (red dress) → [0.1, 0.8, 0.3, ...] (512 dims)
Image B (red dress) → [0.2, 0.7, 0.4, ...] (512 dims)  # Close to A
Image C (blue car)  → [0.9, 0.1, 0.2, ...] (512 dims)  # Far from A,B
```

### The Similarity Search Mental Model

**Think of vector search like a multi-dimensional map**:
- Each product is a point in 512-dimensional space
- Similar products are nearby neighbors
- Search finds the closest neighbors to your query point

**Distance metrics explained**:
```python
# Cosine similarity (recommended for CLIP)
# Measures angle between vectors, ignores magnitude
# Perfect for normalized embeddings like CLIP

# Example: Two very similar dresses
dress_a = [0.8, 0.6, 0.2, ...]
dress_b = [0.9, 0.7, 0.1, ...]
# Small angle = high similarity score
```

### Optimizing Search Performance

#### Embedding Quality Strategies

**Image preprocessing for better embeddings**:
```python
def optimize_image_for_embedding(image_path):
    """Preprocessing to improve embedding quality"""
    image = Image.open(image_path).convert('RGB')
    
    # Remove background for fashion items (optional)
    # Focus on main product
    # Ensure good lighting and contrast
    
    return image
```

**Handling different image types**:
- **Product photos**: Clean, white background, good lighting
- **Lifestyle photos**: Products in context, may need cropping
- **User uploads**: Varying quality, may need preprocessing

#### Collection Organization Strategies

**Single collection vs. multiple collections**:
```python
# Option 1: Single collection with category filtering
collection_config = {
    "name": "all_products",
    "vectors": {"size": 512, "distance": "Cosine"},
    "payload_indexes": ["category", "price_range", "brand"]
}

# Option 2: Separate collections by category
collections = ["dresses", "shoes", "accessories", "electronics"]
# Pros: Better precision within category
# Cons: More complex search logic
```

### Advanced Search Patterns

#### Multi-stage Search Pipeline

```python
def intelligent_search(query_image_path, user_context=None):
    """Multi-stage search with contextual understanding"""
    
    # Stage 1: Generate base embedding
    query_embedding = model.encode([load_and_preprocess_image(query_image_path)])[0]
    
    # Stage 2: Broad similarity search
    candidates = qdrant_client.search(
        collection_name=collection_name,
        query_vector=query_embedding.tolist(),
        limit=100  # Get more candidates
    )
    
    # Stage 3: Apply business logic filters
    filtered_results = apply_business_filters(candidates, user_context)
    
    # Stage 4: Re-rank based on additional criteria
    final_results = rerank_results(filtered_results, user_context)
    
    return final_results[:10]

def apply_business_filters(candidates, user_context):
    """Apply business rules and user preferences"""
    filtered = []
    for candidate in candidates:
        # Check inventory
        if is_in_stock(candidate.payload['product_id']):
            # Apply user preferences
            if matches_user_style(candidate, user_context):
                filtered.append(candidate)
    return filtered
```

#### Handling Edge Cases

**Query image quality issues**:
```python
def validate_query_image(image_path):
    """Check if query image is suitable for search"""
    image = Image.open(image_path)
    
    # Check image size
    if min(image.size) < 224:
        return False, "Image too small"
    
    # Check if image is mostly one color (likely not a product)
    if is_mostly_uniform_color(image):
        return False, "Image appears to be a solid color"
    
    # Check for blur or low quality
    if is_too_blurry(image):
        return False, "Image is too blurry"
    
    return True, "Image suitable for search"
```

**Handling no results scenarios**:
```python
def fallback_search_strategy(query_image_path):
    """When no good matches found, provide alternatives"""
    
    # Try broader search with lower threshold
    results = search_with_threshold(query_image_path, threshold=0.3)
    
    if not results:
        # Fall back to category-based recommendations
        detected_category = classify_image_category(query_image_path)
        results = get_popular_in_category(detected_category)
    
    return results
```

### Performance Optimization Strategies

#### Embedding Generation Optimization

```python
# Batch processing for efficiency
def generate_embeddings_batch(image_paths, batch_size=32):
    """Process multiple images efficiently"""
    all_embeddings = []
    
    for i in range(0, len(image_paths), batch_size):
        batch_paths = image_paths[i:i + batch_size]
        batch_images = [load_and_preprocess_image(path) for path in batch_paths]
        
        # Filter out failed loads
        valid_images = [img for img in batch_images if img is not None]
        
        if valid_images:
            # Single model call for entire batch
            batch_embeddings = model.encode(valid_images)
            all_embeddings.extend(batch_embeddings)
    
    return all_embeddings
```

#### Search Speed Optimization

```python
# Use approximate search for large collections
from qdrant_client.models import SearchParams

def fast_search(query_vector, collection_name):
    """Optimized search for large collections"""
    return qdrant_client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        search_params=SearchParams(
            hnsw_ef=128,  # Balance between speed and accuracy
            exact=False   # Use approximate search
        ),
        limit=10
    )
```

### Real-World Implementation Considerations

**Scalability planning**:
- **Millions of products**: Consider distributed Qdrant setup
- **High query volume**: Implement caching and load balancing  
- **Regular updates**: Design incremental indexing pipeline

**Quality monitoring**:
```python
def monitor_search_quality():
    """Track search performance metrics"""
    metrics = {
        'avg_similarity_score': calculate_avg_similarity(),
        'zero_results_rate': calculate_zero_results_rate(),
        'click_through_rate': get_search_ctr(),
        'user_satisfaction': get_satisfaction_scores()
    }
    return metrics
```

**A/B testing framework**:
```python
def ab_test_search_algorithm(query_image, user_id):
    """Test different search algorithms"""
    if user_id % 2 == 0:
        return search_algorithm_a(query_image)
    else:
        return search_algorithm_b(query_image)
```

This comprehensive reverse image search system enables e-commerce platforms to provide intuitive visual product discovery, significantly enhancing the shopping experience through advanced computer vision and vector search capabilities.