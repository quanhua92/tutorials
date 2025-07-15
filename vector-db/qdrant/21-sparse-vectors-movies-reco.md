# Sparse Vectors Movies Recommendation

> **Source**: [sparse-vectors-movies-reco](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/sparse-vectors-movies-reco)

This tutorial demonstrates how to build a movie recommendation system using sparse vectors and collaborative filtering with Qdrant, showcasing how to efficiently represent user-item interactions for personalized recommendations.

## Part 1: Core Concept - Why Sparse Vectors for Recommendations

### The Recommendation Challenge

Traditional recommendation systems face the sparsity problem:

- **Massive item catalogs**: Millions of movies, products, or content items
- **Limited user interactions**: Each user rates/views only a tiny fraction of available items
- **High-dimensional spaces**: Vector representations become mostly zeros
- **Memory inefficiency**: Storing dense vectors wastes space on non-interactions

**Example problem**: Netflix has 15,000+ titles, but average users rate fewer than 100 movies. Dense vectors would be 99%+ zeros.

### The Sparse Vector Solution

Sparse vectors solve this by storing only meaningful interactions:

- **Explicit representation**: Each dimension represents a specific item (movie ID)
- **Efficient storage**: Only store non-zero values (actual ratings/interactions)
- **Direct interpretability**: Index 123 = Movie ID 123, Value = User's rating
- **Collaborative filtering**: Find users with similar sparse rating patterns

**What you'll build**: A movie recommendation system that uses sparse vectors to efficiently represent user ratings and find similar users through collaborative filtering, generating personalized movie suggestions.

### Sparse vs Dense Vectors for Recommendations

| Aspect | Sparse Vectors | Dense Vectors |
|--------|----------------|---------------|
| **Representation** | Explicit item IDs + ratings | Learned latent features |
| **Efficiency** | High (only store non-zeros) | Low (store all dimensions) |
| **Interpretability** | Direct (dimension = item) | Opaque (learned features) |
| **Use Case** | Collaborative filtering | Content-based filtering |

### Real-World Applications

- **Streaming Services**: Netflix, Spotify, YouTube content recommendations
- **E-commerce**: Amazon product recommendations based on purchase history
- **Social Media**: Friend suggestions, content feed personalization
- **News**: Article recommendations based on reading history

## Part 2: Practical Walkthrough - Building Sparse Vector Recommendations

### Understanding Collaborative Filtering

The system finds users with similar tastes and recommends items they liked:

```
User A: Loved Inception, Liked Interstellar, Hated Titanic
User B: Loved Inception, Liked Interstellar, Liked Dark Knight
         ↓
Similar users → Recommend Dark Knight to User A
```

**Key insight**: Sparse vectors efficiently encode these rating patterns for similarity search.

### Setup and Dependencies

```python
# Core dependencies for sparse vector recommendations
!pip install qdrant-client pandas numpy scikit-learn

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple
from collections import defaultdict

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, 
    SparseVector, Filter, FieldCondition, MatchValue
)
```

**Key components:**
- `qdrant-client`: Vector database with sparse vector support
- `pandas`: Data manipulation for MovieLens dataset
- `numpy`: Numerical operations for rating normalization
- `scikit-learn`: Additional ML utilities

### Initialize Services

```python
# Initialize Qdrant client (in-memory for tutorial)
qdrant_client = QdrantClient(":memory:")

print("Sparse vector recommendation system initialized!")
```

### Stage 1: Dataset Preparation

#### Load MovieLens Dataset

```python
def load_movielens_data():
    """Load and prepare MovieLens 1M dataset"""
    
    # Download MovieLens 1M dataset
    # In practice, you would download from: https://grouplens.org/datasets/movielens/1m/
    
    # For tutorial, create sample data
    sample_users = pd.DataFrame({
        'user_id': range(1, 101),  # 100 users
        'gender': np.random.choice(['M', 'F'], 100),
        'age': np.random.choice([1, 18, 25, 35, 45, 50, 56], 100),
        'occupation': np.random.randint(0, 21, 100),
        'zip_code': [f'{np.random.randint(10000, 99999)}' for _ in range(100)]
    })
    
    sample_movies = pd.DataFrame({
        'movie_id': range(1, 201),  # 200 movies
        'title': [f'Movie_{i}' for i in range(1, 201)],
        'genres': [np.random.choice(['Action', 'Comedy', 'Drama', 'Thriller'], 
                                  np.random.randint(1, 4)) for _ in range(200)]
    })
    
    # Generate realistic ratings (most users rate few movies)
    ratings_data = []
    for user_id in range(1, 101):
        # Each user rates 10-50 movies
        num_ratings = np.random.randint(10, 51)
        rated_movies = np.random.choice(range(1, 201), num_ratings, replace=False)
        
        for movie_id in rated_movies:
            # Ratings follow normal distribution around 3.5
            rating = np.clip(np.random.normal(3.5, 1.2), 1, 5)
            rating = round(rating)
            
            ratings_data.append({
                'user_id': user_id,
                'movie_id': movie_id,
                'rating': rating,
                'timestamp': np.random.randint(1000000000, 1500000000)
            })
    
    sample_ratings = pd.DataFrame(ratings_data)
    
    print(f"Loaded dataset:")
    print(f"- Users: {len(sample_users)}")
    print(f"- Movies: {len(sample_movies)}")
    print(f"- Ratings: {len(sample_ratings)}")
    
    return sample_users, sample_movies, sample_ratings

# Load dataset
users_df, movies_df, ratings_df = load_movielens_data()

# Display sample data
print("\nSample ratings:")
print(ratings_df.head(10))
```

#### Normalize User Ratings

```python
def normalize_user_ratings(ratings_df):
    """Normalize ratings to have mean zero per user"""
    
    # Calculate user mean ratings
    user_means = ratings_df.groupby('user_id')['rating'].mean()
    
    # Normalize ratings by subtracting user mean
    normalized_ratings = ratings_df.copy()
    normalized_ratings['normalized_rating'] = (
        normalized_ratings['rating'] - 
        normalized_ratings['user_id'].map(user_means)
    )
    
    print("Rating normalization statistics:")
    print(f"Original ratings range: {ratings_df['rating'].min():.1f} to {ratings_df['rating'].max():.1f}")
    print(f"Normalized ratings range: {normalized_ratings['normalized_rating'].min():.2f} to {normalized_ratings['normalized_rating'].max():.2f}")
    print(f"Normalized ratings mean: {normalized_ratings['normalized_rating'].mean():.4f}")
    
    return normalized_ratings, user_means

# Normalize ratings
normalized_ratings_df, user_rating_means = normalize_user_ratings(ratings_df)
```

#### Convert to Sparse Vectors

```python
def create_sparse_vectors(normalized_ratings_df, users_df):
    """Convert user ratings to sparse vectors"""
    
    user_sparse_vectors = []
    
    for user_id in users_df['user_id']:
        # Get user's ratings
        user_ratings = normalized_ratings_df[normalized_ratings_df['user_id'] == user_id]
        
        if len(user_ratings) > 0:
            # Create sparse vector
            indices = user_ratings['movie_id'].tolist()
            values = user_ratings['normalized_rating'].tolist()
            
            # Get user metadata
            user_info = users_df[users_df['user_id'] == user_id].iloc[0]
            
            sparse_vector_data = {
                'user_id': user_id,
                'sparse_vector': SparseVector(
                    indices=indices,
                    values=values
                ),
                'metadata': {
                    'user_id': user_id,
                    'gender': user_info['gender'],
                    'age': user_info['age'],
                    'occupation': user_info['occupation'],
                    'num_ratings': len(indices),
                    'avg_rating': user_rating_means[user_id]
                }
            }
            
            user_sparse_vectors.append(sparse_vector_data)
    
    print(f"Created {len(user_sparse_vectors)} user sparse vectors")
    
    # Display sample sparse vector
    sample_vector = user_sparse_vectors[0]
    print(f"\nSample sparse vector for User {sample_vector['user_id']}:")
    print(f"- Rated {len(sample_vector['sparse_vector'].indices)} movies")
    print(f"- Movie IDs: {sample_vector['sparse_vector'].indices[:5]}...")
    print(f"- Normalized ratings: {[round(v, 2) for v in sample_vector['sparse_vector'].values[:5]]}...")
    
    return user_sparse_vectors

# Create sparse vectors
user_vectors = create_sparse_vectors(normalized_ratings_df, users_df)
```

### Stage 2: Qdrant Sparse Vector Setup

#### Create Sparse Vector Collection

```python
def setup_sparse_collection(collection_name="movie_recommendations"):
    """Create Qdrant collection for sparse vectors"""
    
    # Create collection with sparse vector configuration
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config={},  # No dense vectors
        sparse_vectors_config={
            "ratings": VectorParams(
                index={"on_disk": False},  # Keep in memory for speed
                modifier="idf"  # Use IDF modifier for better similarity
            )
        }
    )
    
    print(f"Created sparse vector collection: {collection_name}")
    return collection_name

# Setup collection
collection_name = setup_sparse_collection()
```

#### Index User Sparse Vectors

```python
def index_user_vectors(user_vectors, collection_name):
    """Index user sparse vectors in Qdrant"""
    
    points = []
    
    for i, user_data in enumerate(user_vectors):
        point = PointStruct(
            id=user_data['user_id'],
            vector={
                "ratings": user_data['sparse_vector']
            },
            payload=user_data['metadata']
        )
        points.append(point)
    
    # Upload points in batches
    batch_size = 50
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        qdrant_client.upsert(
            collection_name=collection_name,
            points=batch
        )
        print(f"Indexed batch {i//batch_size + 1}/{(len(points) + batch_size - 1)//batch_size}")
    
    print(f"Successfully indexed {len(points)} user vectors")

# Index user vectors
index_user_vectors(user_vectors, collection_name)
```

### Stage 3: Collaborative Filtering Implementation

#### Find Similar Users

```python
def find_similar_users(target_user_ratings: Dict[int, float], 
                      collection_name: str, 
                      top_k: int = 10) -> List[Dict]:
    """Find users with similar rating patterns"""
    
    # Create sparse vector from target user ratings
    indices = list(target_user_ratings.keys())
    values = list(target_user_ratings.values())
    
    query_vector = SparseVector(indices=indices, values=values)
    
    # Search for similar users
    search_results = qdrant_client.search(
        collection_name=collection_name,
        query_vector=("ratings", query_vector),
        limit=top_k + 1  # +1 to potentially exclude exact match
    )
    
    # Format results
    similar_users = []
    for result in search_results:
        similar_users.append({
            'user_id': result.payload['user_id'],
            'similarity': result.score,
            'gender': result.payload['gender'],
            'age': result.payload['age'],
            'num_ratings': result.payload['num_ratings'],
            'avg_rating': result.payload['avg_rating']
        })
    
    return similar_users

# Test with sample user
sample_user_ratings = {
    1: 1.2,    # Loved this movie (above their average)
    5: 0.8,    # Liked this movie
    10: -1.5,  # Disliked this movie (below their average)
    15: 0.3,   # Slightly liked
    20: -0.8   # Somewhat disliked
}

print("Sample user ratings (normalized):")
for movie_id, rating in sample_user_ratings.items():
    print(f"Movie {movie_id}: {rating:+.1f}")

similar_users = find_similar_users(sample_user_ratings, collection_name, top_k=5)

print(f"\nTop 5 similar users:")
for user in similar_users:
    print(f"User {user['user_id']}: similarity={user['similarity']:.3f}, "
          f"age={user['age']}, ratings={user['num_ratings']}")
```

#### Generate Movie Recommendations

```python
def recommend_movies(target_user_ratings: Dict[int, float],
                    collection_name: str,
                    movies_df: pd.DataFrame,
                    top_k_users: int = 20,
                    top_k_movies: int = 10) -> List[Dict]:
    """Generate movie recommendations based on similar users"""
    
    # Find similar users
    similar_users = find_similar_users(target_user_ratings, collection_name, top_k_users)
    
    # Get ratings from similar users
    similar_user_ids = [user['user_id'] for user in similar_users]
    
    # Aggregate movie scores from similar users
    movie_scores = defaultdict(list)
    
    # Get all ratings from similar users
    similar_user_ratings = normalized_ratings_df[
        normalized_ratings_df['user_id'].isin(similar_user_ids)
    ]
    
    # Exclude movies already rated by target user
    target_movie_ids = set(target_user_ratings.keys())
    
    for _, rating in similar_user_ratings.iterrows():
        movie_id = rating['movie_id']
        
        # Skip if target user already rated this movie
        if movie_id in target_movie_ids:
            continue
        
        # Find user similarity weight
        user_similarity = next(
            (u['similarity'] for u in similar_users if u['user_id'] == rating['user_id']), 
            0.0
        )
        
        # Weight the rating by user similarity
        weighted_score = rating['normalized_rating'] * user_similarity
        movie_scores[movie_id].append(weighted_score)
    
    # Calculate average weighted scores
    movie_recommendations = []
    for movie_id, scores in movie_scores.items():
        avg_score = np.mean(scores)
        confidence = len(scores)  # Number of similar users who rated this movie
        
        # Get movie info
        movie_info = movies_df[movies_df['movie_id'] == movie_id]
        if not movie_info.empty:
            movie_title = movie_info.iloc[0]['title']
            movie_genres = movie_info.iloc[0]['genres']
        else:
            movie_title = f"Movie {movie_id}"
            movie_genres = "Unknown"
        
        movie_recommendations.append({
            'movie_id': movie_id,
            'title': movie_title,
            'genres': movie_genres,
            'predicted_score': avg_score,
            'confidence': confidence
        })
    
    # Sort by predicted score and confidence
    movie_recommendations.sort(
        key=lambda x: (x['predicted_score'], x['confidence']), 
        reverse=True
    )
    
    return movie_recommendations[:top_k_movies]

# Generate recommendations
recommendations = recommend_movies(
    sample_user_ratings, 
    collection_name, 
    movies_df,
    top_k_users=15,
    top_k_movies=10
)

print("🎬 Movie Recommendations:")
print("=" * 50)
for i, rec in enumerate(recommendations, 1):
    print(f"{i}. {rec['title']}")
    print(f"   Predicted Score: {rec['predicted_score']:+.2f}")
    print(f"   Confidence: {rec['confidence']} similar users")
    print(f"   Genres: {rec['genres']}")
    print()
```

### Stage 4: Filtered Recommendations

#### Age-Based Filtering

```python
def recommend_movies_by_age(target_user_ratings: Dict[int, float],
                           collection_name: str,
                           target_age_group: int,
                           age_tolerance: int = 10) -> List[Dict]:
    """Generate recommendations filtering by user age"""
    
    # Create age filter
    age_filter = Filter(
        must=[
            FieldCondition(
                key="age",
                range={
                    "gte": target_age_group - age_tolerance,
                    "lte": target_age_group + age_tolerance
                }
            )
        ]
    )
    
    # Create query sparse vector
    indices = list(target_user_ratings.keys())
    values = list(target_user_ratings.values())
    query_vector = SparseVector(indices=indices, values=values)
    
    # Search with age filter
    search_results = qdrant_client.search(
        collection_name=collection_name,
        query_vector=("ratings", query_vector),
        query_filter=age_filter,
        limit=15
    )
    
    print(f"Found {len(search_results)} similar users in age group {target_age_group}±{age_tolerance}")
    
    # Process results similar to regular recommendations
    similar_users = []
    for result in search_results:
        similar_users.append({
            'user_id': result.payload['user_id'],
            'similarity': result.score,
            'age': result.payload['age']
        })
    
    return similar_users

# Test age-filtered recommendations
age_similar_users = recommend_movies_by_age(
    sample_user_ratings,
    collection_name,
    target_age_group=25,
    age_tolerance=5
)

print("Age-filtered similar users (20-30 years old):")
for user in age_similar_users[:5]:
    print(f"User {user['user_id']}: similarity={user['similarity']:.3f}, age={user['age']}")
```

#### Gender-Based Filtering

```python
def recommend_movies_by_demographics(target_user_ratings: Dict[int, float],
                                   collection_name: str,
                                   gender: str = None,
                                   min_ratings: int = 20) -> List[Dict]:
    """Generate recommendations with demographic filtering"""
    
    # Build filter conditions
    filter_conditions = []
    
    if gender:
        filter_conditions.append(
            FieldCondition(key="gender", match=MatchValue(value=gender))
        )
    
    if min_ratings:
        filter_conditions.append(
            FieldCondition(
                key="num_ratings",
                range={"gte": min_ratings}
            )
        )
    
    # Create filter
    demo_filter = Filter(must=filter_conditions) if filter_conditions else None
    
    # Create query vector
    indices = list(target_user_ratings.keys())
    values = list(target_user_ratings.values())
    query_vector = SparseVector(indices=indices, values=values)
    
    # Search with demographic filter
    search_results = qdrant_client.search(
        collection_name=collection_name,
        query_vector=("ratings", query_vector),
        query_filter=demo_filter,
        limit=10
    )
    
    # Format results
    similar_users = []
    for result in search_results:
        similar_users.append({
            'user_id': result.payload['user_id'],
            'similarity': result.score,
            'gender': result.payload['gender'],
            'age': result.payload['age'],
            'num_ratings': result.payload['num_ratings']
        })
    
    return similar_users

# Test demographic filtering
demo_similar_users = recommend_movies_by_demographics(
    sample_user_ratings,
    collection_name,
    gender="F",
    min_ratings=25
)

print("Demographic-filtered similar users (Female, 25+ ratings):")
for user in demo_similar_users[:5]:
    print(f"User {user['user_id']}: similarity={user['similarity']:.3f}, "
          f"gender={user['gender']}, ratings={user['num_ratings']}")
```

### Stage 5: Advanced Sparse Vector Techniques

#### Hybrid Dense + Sparse Recommendations

```python
def create_hybrid_collection(collection_name="hybrid_recommendations"):
    """Create collection supporting both dense and sparse vectors"""
    
    try:
        qdrant_client.delete_collection(collection_name)
    except:
        pass
    
    # Create collection with both vector types
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config={
            "content": VectorParams(size=128, distance=Distance.COSINE)  # Content-based features
        },
        sparse_vectors_config={
            "ratings": VectorParams(modifier="idf")  # Collaborative filtering
        }
    )
    
    print(f"Created hybrid collection: {collection_name}")
    return collection_name

def generate_content_features(movies_df, embedding_dim=128):
    """Generate mock content-based features for movies"""
    
    content_features = {}
    
    for _, movie in movies_df.iterrows():
        # Generate mock content embedding based on genres
        # In practice, this would be derived from movie descriptions, cast, etc.
        np.random.seed(movie['movie_id'])  # Consistent random features
        content_vector = np.random.normal(0, 1, embedding_dim)
        content_features[movie['movie_id']] = content_vector.tolist()
    
    return content_features

# Create hybrid system
hybrid_collection = create_hybrid_collection()
movie_content_features = generate_content_features(movies_df)

def hybrid_recommendation(target_user_ratings: Dict[int, float],
                         target_content_preferences: List[float],
                         collection_name: str,
                         collaborative_weight: float = 0.7) -> List[Dict]:
    """Generate recommendations using both collaborative and content-based filtering"""
    
    # Collaborative filtering component
    collab_users = find_similar_users(target_user_ratings, collection_name, top_k=10)
    
    # Content-based component (simplified)
    # In practice, you'd search for movies with similar content features
    content_similar_movies = []
    
    # Combine results (simplified approach)
    recommendations = []
    
    # Weight collaborative filtering results
    for user in collab_users[:5]:
        recommendations.append({
            'type': 'collaborative',
            'score': user['similarity'] * collaborative_weight,
            'source': f"Similar to User {user['user_id']}"
        })
    
    return recommendations

print("Hybrid recommendation system created!")
```

#### Real-Time Recommendation Updates

```python
def update_user_rating(user_id: int, movie_id: int, new_rating: float, 
                      collection_name: str):
    """Update user's sparse vector with new rating"""
    
    # Retrieve current user vector
    user_point = qdrant_client.retrieve(
        collection_name=collection_name,
        ids=[user_id]
    )
    
    if user_point:
        current_vector = user_point[0].vector["ratings"]
        
        # Update sparse vector with new rating
        updated_indices = list(current_vector.indices)
        updated_values = list(current_vector.values)
        
        # Add or update the rating
        if movie_id in updated_indices:
            # Update existing rating
            idx = updated_indices.index(movie_id)
            updated_values[idx] = new_rating
        else:
            # Add new rating
            updated_indices.append(movie_id)
            updated_values.append(new_rating)
        
        # Create updated sparse vector
        updated_vector = SparseVector(
            indices=updated_indices,
            values=updated_values
        )
        
        # Update point in collection
        qdrant_client.upsert(
            collection_name=collection_name,
            points=[
                PointStruct(
                    id=user_id,
                    vector={"ratings": updated_vector},
                    payload=user_point[0].payload
                )
            ]
        )
        
        print(f"Updated User {user_id}'s rating for Movie {movie_id}: {new_rating}")
    else:
        print(f"User {user_id} not found in collection")

# Test real-time update
# update_user_rating(1, 999, 1.5, collection_name)
print("Real-time update capability demonstrated!")
```

## Part 3: Mental Models & Deep Dives

### Understanding Sparse Vector Efficiency

**Mental Model**: Think of sparse vectors like a personal library card:

**Dense Vector (Traditional)**:
```
[0, 0, 0, 4, 0, 0, 5, 0, 0, 0, 3, 0, 0, 0, ...]  # 10,000 dimensions
```

**Sparse Vector (Efficient)**:
```
indices: [3, 6, 10]     # Only positions with values
values:  [4, 5, 3]      # Corresponding ratings
```

**Storage**: 3 values vs 10,000 → 99.97% space saving!

### Collaborative Filtering Mental Model

**Think of collaborative filtering like movie night with friends**:

1. **Find similar friends**: Who likes the same movies you do?
2. **Trust their recommendations**: If they loved a movie you haven't seen, you might too
3. **Weight by similarity**: Closer friends' opinions matter more
4. **Aggregate recommendations**: Combine suggestions from multiple similar friends

### Sparse Vector Similarity

**Cosine similarity with sparse vectors**:
```python
# Two users with overlapping movie preferences
User A: {movie_1: 1.2, movie_5: -0.8, movie_10: 0.9}
User B: {movie_1: 1.0, movie_5: -0.9, movie_12: 1.5}

# Similarity calculated only on overlapping dimensions (1, 5)
# Movies 10 and 12 don't affect similarity calculation
```

### Advanced Sparse Vector Techniques

#### Temporal Decay

```python
def apply_temporal_decay(ratings_df, decay_factor=0.95):
    """Apply temporal decay to older ratings"""
    
    # Calculate days since rating
    current_time = ratings_df['timestamp'].max()
    ratings_df['days_ago'] = (current_time - ratings_df['timestamp']) / (24 * 60 * 60)
    
    # Apply exponential decay
    ratings_df['decayed_rating'] = (
        ratings_df['normalized_rating'] * 
        (decay_factor ** (ratings_df['days_ago'] / 365))  # Decay per year
    )
    
    return ratings_df
```

#### Matrix Factorization Integration

```python
def sparse_matrix_factorization(user_vectors, n_factors=50):
    """Integrate sparse vectors with matrix factorization"""
    
    from scipy.sparse import csr_matrix
    from sklearn.decomposition import TruncatedSVD
    
    # Convert sparse vectors to scipy sparse matrix
    max_movie_id = max(
        max(uv['sparse_vector'].indices) 
        for uv in user_vectors 
        if uv['sparse_vector'].indices
    )
    
    # Build user-item matrix
    rows, cols, values = [], [], []
    for i, user_data in enumerate(user_vectors):
        user_ratings = user_data['sparse_vector']
        for movie_id, rating in zip(user_ratings.indices, user_ratings.values):
            rows.append(i)
            cols.append(movie_id - 1)  # 0-indexed
            values.append(rating)
    
    sparse_matrix = csr_matrix(
        (values, (rows, cols)), 
        shape=(len(user_vectors), max_movie_id)
    )
    
    # Apply matrix factorization
    svd = TruncatedSVD(n_components=n_factors)
    user_factors = svd.fit_transform(sparse_matrix)
    
    return user_factors, svd
```

#### Cold Start Handling

```python
def handle_cold_start_user(new_user_ratings: Dict[int, float],
                          collection_name: str,
                          popularity_weight: float = 0.3):
    """Handle recommendations for users with very few ratings"""
    
    if len(new_user_ratings) < 5:  # Cold start threshold
        print("Cold start user detected - using popularity-based recommendations")
        
        # Get most popular movies from similar ratings
        popular_movies = get_popular_movies_by_genre(new_user_ratings)
        
        # Combine with limited collaborative filtering
        if len(new_user_ratings) > 0:
            collab_recs = find_similar_users(new_user_ratings, collection_name, top_k=5)
            return combine_popularity_and_collaborative(popular_movies, collab_recs)
        else:
            return popular_movies
    
    else:
        # Standard collaborative filtering
        return find_similar_users(new_user_ratings, collection_name)

def get_popular_movies_by_genre(user_ratings: Dict[int, float]):
    """Get popular movies from genres the user seems to like"""
    
    # Analyze user's preferred genres from their ratings
    positive_ratings = {k: v for k, v in user_ratings.items() if v > 0}
    
    # Get genres of liked movies
    liked_movie_ids = list(positive_ratings.keys())
    liked_movies = movies_df[movies_df['movie_id'].isin(liked_movie_ids)]
    
    # Find popular movies in those genres
    # This is a simplified approach - in practice you'd have genre-based popularity rankings
    
    return []  # Placeholder implementation
```

### Performance Optimization

#### Batch Processing

```python
def batch_similarity_search(user_queries: List[Dict[int, float]], 
                           collection_name: str,
                           batch_size: int = 10):
    """Process multiple similarity searches efficiently"""
    
    results = {}
    
    for i in range(0, len(user_queries), batch_size):
        batch = user_queries[i:i + batch_size]
        
        # Process batch in parallel (simplified)
        batch_results = []
        for user_ratings in batch:
            similar_users = find_similar_users(user_ratings, collection_name)
            batch_results.append(similar_users)
        
        # Store results
        for j, result in enumerate(batch_results):
            results[i + j] = result
    
    return results
```

#### Memory Optimization

```python
def optimize_sparse_storage(user_vectors, min_rating_threshold=0.1):
    """Optimize sparse vectors by removing low-confidence ratings"""
    
    optimized_vectors = []
    
    for user_data in user_vectors:
        sparse_vector = user_data['sparse_vector']
        
        # Filter out low-magnitude ratings
        filtered_indices = []
        filtered_values = []
        
        for idx, value in zip(sparse_vector.indices, sparse_vector.values):
            if abs(value) >= min_rating_threshold:
                filtered_indices.append(idx)
                filtered_values.append(value)
        
        # Create optimized sparse vector
        optimized_vector = SparseVector(
            indices=filtered_indices,
            values=filtered_values
        )
        
        user_data['sparse_vector'] = optimized_vector
        optimized_vectors.append(user_data)
    
    return optimized_vectors
```

### Production Deployment Considerations

#### Scalability Monitoring

```python
def monitor_recommendation_system():
    """Monitor recommendation system performance"""
    
    metrics = {
        "avg_sparse_vector_size": 0,
        "recommendation_latency": 0,
        "similarity_search_performance": 0,
        "user_coverage": 0,
        "item_coverage": 0
    }
    
    # Calculate average sparse vector size
    vector_sizes = [len(uv['sparse_vector'].indices) for uv in user_vectors]
    metrics["avg_sparse_vector_size"] = np.mean(vector_sizes)
    
    # Monitor recommendation quality
    # - Diversity of recommendations
    # - Novelty vs popularity balance
    # - User engagement metrics
    
    return metrics

# Monitor system
system_metrics = monitor_recommendation_system()
print(f"System Metrics: {system_metrics}")
```

This comprehensive sparse vector recommendation system demonstrates how to efficiently build collaborative filtering systems that scale to millions of users and items while maintaining fast, personalized recommendations.