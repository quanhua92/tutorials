# Collaborative Filtering with Sparse Vectors: Understanding User Preferences

**Source Example:** [collaborative-filtering](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/collaborative-filtering)

## The Core Concept: Why This Example Exists

### The Problem
Traditional recommendation systems face a fundamental challenge: how do you recommend items to users when you have millions of items but each user has only interacted with a tiny fraction? Content-based filtering requires detailed item metadata and struggles with the "cold start" problem. Rule-based systems become unwieldy at scale. How do you discover user preferences and find similar users efficiently when the data is incredibly sparse?

### The Solution
Collaborative filtering leverages the collective wisdom of user behavior—"users who liked similar things to you also enjoyed these items." By representing each user as a sparse vector of their preferences (ratings, purchases, clicks), you can find users with similar taste profiles and recommend items they've enjoyed. Sparse vectors are perfect for this because most users interact with only a small percentage of available items.

Qdrant's philosophy for collaborative filtering: **Similarity emerges from shared preferences**. By storing user preference vectors and using vector similarity search, you can discover taste communities and generate personalized recommendations at scale.

---

## Practical Walkthrough: Code Breakdown

### The Dataset: MovieLens at Scale

The example uses the comprehensive MovieLens dataset containing real user ratings:

```python
import pandas as pd
from collections import defaultdict

# Load the comprehensive MovieLens dataset
ratings_df = pd.read_csv('data/ratings.csv', low_memory=False)
movies_df = pd.read_csv('data/movies.csv', low_memory=False)
links = pd.read_csv('data/links.csv')

# Dataset statistics:
# - ~33,000,000 ratings
# - ~86,000 movies  
# - ~330,000 users
# - Rating scale: 0.5 to 5.0 stars
```

**Why MovieLens is perfect:** This dataset represents genuine user preferences over decades of movie consumption. The sparsity (each user rates <0.1% of movies) perfectly demonstrates the collaborative filtering challenge.

### Data Preprocessing: Normalization and Aggregation

Raw ratings need careful preprocessing for effective collaborative filtering:

```python
# Normalize ratings to zero mean, unit variance
ratings_df['rating'] = (ratings_df['rating'] - ratings_df['rating'].mean()) / ratings_df['rating'].std()

# Handle duplicate ratings (same user rating same movie multiple times)
ratings_agg_df = ratings_df.groupby(['userId', 'movieId']).rating.mean().reset_index()

# Convert movieId to string for consistency
ratings_df['movieId'] = ratings_df['movieId'].astype(str)
movies_df['movieId'] = movies_df['movieId'].astype(str)
```

**Why normalization matters:** Users have different rating behaviors—some are generous (average 4.5 stars), others are harsh critics (average 2.5 stars). Normalization ensures similarity is based on preference patterns rather than rating scales.

**Aggregation insight:** When users rate the same movie multiple times, taking the mean captures their evolving opinion while avoiding duplicate preference signals.

### Sparse Vector Representation: Efficient User Profiles

Each user becomes a sparse vector where dimensions represent movies and values represent preferences:

```python
# Convert user ratings to sparse vector format
user_sparse_vectors = defaultdict(lambda: {"values": [], "indices": []})

for row in ratings_agg_df.itertuples():
    user_sparse_vectors[row.userId]["values"].append(row.rating)
    user_sparse_vectors[row.userId]["indices"].append(int(row.movieId))

# Example user vector:
# User 123: {indices: [11, 603, 862], values: [1.2, -0.5, 0.8]}
# Means: User 123 loved movie 11, disliked movie 603, liked movie 862
```

**Sparse efficiency:** Instead of storing 86,000 dimensions (mostly zeros), we store only the movies each user rated. This reduces memory usage by ~99% while preserving all preference information.

### Collection Setup: Optimized for Sparse Similarity

Qdrant's sparse vector support is purpose-built for collaborative filtering:

```python
from qdrant_client import models, QdrantClient

qdrant_client.create_collection(
    collection_name="movies",
    vectors_config={},  # No dense vectors needed
    sparse_vectors_config={
        "ratings": models.SparseVectorParams()  # Sparse vectors for user preferences
    }
)
```

**Design choice:** Using only sparse vectors eliminates unnecessary memory overhead. Each user vector contains only their actual ratings, making similarity calculations extremely efficient.

### Efficient Data Upload with Generators

For large datasets, memory-efficient uploading is crucial:

```python
from qdrant_client.http.models import PointStruct, SparseVector

def data_generator():
    for user_id, sparse_vector in user_sparse_vectors.items():
        yield PointStruct(
            id=user_id,
            vector={"ratings": SparseVector(
                indices=sparse_vector["indices"],
                values=sparse_vector["values"]
            )},
            payload={
                "user_id": user_id, 
                "movie_id": sparse_vector["indices"]  # Movies this user rated
            }
        )

# Upload without loading everything into memory
qdrant_client.upload_points(
    collection_name="movies",
    points=data_generator()
)
```

**Generator advantage:** This processes millions of users without memory overflow. Each user vector is generated on-demand, uploaded, and immediately freed from memory.

### Creating User Preference Vectors

To get recommendations, express preferences as a sparse vector:

```python
# Example: My movie preferences
my_ratings = {
    603: 1,     # Matrix (loved it)
    13475: 1,   # Star Trek (loved it)  
    11: 1,      # Star Wars (loved it)
    1091: -1,   # The Thing (disliked)
    862: 1,     # Toy Story (loved it)
    597: -1,    # Titanic (disliked)
    680: -1,    # Pulp Fiction (disliked)
    13: 1,      # Forrest Gump (loved it)
    120: 1,     # Lord of the Rings (loved it)
    87: -1,     # Indiana Jones (disliked)
    562: -1     # Die Hard (disliked)
}

def to_vector(ratings):
    """Convert rating dictionary to sparse vector"""
    vector = SparseVector(values=[], indices=[])
    for movie_id, rating in ratings.items():
        vector.values.append(rating)
        vector.indices.append(movie_id)
    return vector

query_vector = to_vector(my_ratings)
```

**Preference encoding:** Positive values (1) indicate likes, negative values (-1) indicate dislikes. This captures both positive and negative preferences, providing richer similarity signals.

### Collaborative Filtering Search: Finding Similar Users

The magic happens in the similarity search:

```python
from qdrant_client.http.models import NamedSparseVector

# Find users with similar preferences
results = qdrant_client.search(
    collection_name="movies",
    query_vector=NamedSparseVector(
        name="ratings",
        vector=query_vector
    ),
    limit=20  # Top 20 most similar users
)

# Each result contains:
# - score: similarity to my preferences
# - payload: user_id and their rated movies
```

**Similarity mathematics:** Qdrant calculates cosine similarity between sparse vectors, measuring how aligned two users' preferences are. High scores indicate users who consistently like/dislike the same movies.

### Recommendation Generation: Aggregating User Preferences

Transform similar users into movie recommendations:

```python
def results_to_scores(results):
    """Aggregate recommendations from similar users"""
    movie_scores = defaultdict(lambda: 0)
    
    for result in results:
        # Weight each user's preferences by their similarity to me
        for movie_id in result.payload["movie_id"]:
            movie_scores[movie_id] += result.score
    
    return movie_scores

# Generate recommendations
movie_scores = results_to_scores(results)
top_movies = sorted(movie_scores.items(), key=lambda x: x[1], reverse=True)
```

**Aggregation strategy:** Movies liked by multiple similar users get higher scores. The scoring weights recommendations by user similarity—preferences from very similar users count more than those from moderately similar users.

### Rich Recommendation Display

Enhance recommendations with movie metadata:

```python
import requests

def get_movie_poster(imdb_id, api_key):
    """Fetch movie details from OMDB API"""
    url = f"https://www.omdbapi.com/?i={imdb_id}&apikey={api_key}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('Poster', 'No Poster Found'), data
    return 'No Poster Found'

# Display top recommendations with rich metadata
for movie_id, score in top_movies[:5]:
    imdb_id_row = links.loc[links['movieId'] == int(movie_id), 'imdbId']
    if not imdb_id_row.empty:
        imdb_id = imdb_id_row.values[0]
        poster_url, movie_info = get_movie_poster(imdb_id, omdb_api_key)
        print(f"{movie_info.get('Title', 'Unknown')}: Score {score:.2f}")
```

**User experience insight:** Rich recommendations with posters, descriptions, and metadata help users understand why items were recommended and make informed decisions.

---

## Mental Model: Thinking in Preference Space

### The Collaborative Filtering Landscape

Imagine a vast multidimensional space where each user occupies a position based on their preferences:

```
Movie Preference Space (Simplified 2D View)

   Love Action Movies
        ^
        |
   User A • ← Likes Matrix, Star Wars, Die Hard
        |     Similar users cluster here
   User B •
        |
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━→
Love Comedy                     Love Drama
        |
   User C • ← Likes Toy Story, Forrest Gump  
        |     Different cluster
   User D •
        |
        v
   Love Romance Movies
```

**Distance = Taste Similarity:** Users close in this space have similar preferences and will enjoy recommendations from each other.

### Why Sparse Vectors Excel for Collaborative Filtering

Traditional dense vectors waste enormous space and computation:

```
Dense approach (86K dimensions):
User A: [0, 0, 0, 4.5, 0, 0, 0, 3.2, 0, 0, ..., 0] (mostly zeros)

Sparse approach:
User A: indices=[3, 7], values=[4.5, 3.2] (only ratings)
```

**Efficiency gains:**
- **Memory:** 99%+ reduction (store only actual ratings)
- **Computation:** Similarity calculations skip zero overlaps
- **Accuracy:** No noise from "unrated" vs "disliked" confusion

### Understanding Collaborative Filtering Mathematics

The recommendation process relies on mathematical similarity:

1. **Cosine Similarity:** Measures angle between preference vectors
   - Values from -1 (opposite preferences) to +1 (identical preferences)
   - Handles different rating scales naturally

2. **Weighted Aggregation:** Similar users vote on recommendations
   - More similar users = higher voting weight
   - Popular items among similar users = strong recommendations

3. **Preference Amplification:** Shared likes/dislikes increase similarity
   - Users who agree on many movies have high similarity scores
   - Disagreements (one likes, other dislikes) decrease similarity

### The Cold Start vs. Rich Profile Trade-off

Collaborative filtering effectiveness depends on preference data richness:

```
New User (5 ratings):     Established User (500 ratings):
- Limited similarity data  - Rich preference profile
- General recommendations  - Highly personalized recommendations  
- Relies on popular items  - Discovers niche content
```

**System evolution:** As users rate more items, recommendations become increasingly personalized and accurate.

### Design Insight: The Sparsity Advantage

Real user behavior creates natural sparsity that collaborative filtering exploits:

- **Users rate <1%** of available items
- **Popular items** get many ratings (good for similarity)
- **Niche items** get fewer ratings (but from passionate users)
- **Rating patterns** reveal deep preference structures

This sparsity isn't a limitation—it's the foundation that makes collaborative filtering mathematically tractable and computationally efficient.

### Real-World Scaling Considerations

**Million-user deployment:**
- Batch process user updates
- Implement incremental similarity updates
- Use approximate nearest neighbor search for speed
- Cache popular recommendations

**Cross-domain recommendations:**
- Combine movie, book, music preferences
- Learn shared taste factors across domains
- Handle domain-specific rating behaviors

### Further Exploration

**Try this experiment:** Create preference vectors for users with completely opposite tastes (horror vs. romance fans). Notice how similarity search correctly identifies users as dissimilar, preventing poor recommendations.

**Advanced techniques:** Modern systems combine collaborative filtering with content-based features, creating hybrid recommenders that capture both taste similarities and item characteristics.

**Temporal dynamics:** Real systems track how user preferences evolve over time, giving more weight to recent ratings while preserving long-term preference signals.

---

This tutorial demonstrates how sparse vector similarity can power personalized recommendations at massive scale. By representing users as sparse preference vectors, collaborative filtering discovers taste communities and generates recommendations that feel intuitively right—because they're based on the collective wisdom of users with similar preferences.