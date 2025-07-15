# Self Query

> **Source**: [self-query](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/self-query)

This tutorial demonstrates how to build intelligent query systems that understand natural language and automatically convert complex queries into precise vector searches with metadata filters using LangChain's SelfQueryRetriever and Qdrant.

## Part 1: Core Concept - Why Self Query Matters

### The Natural Language Query Gap

Traditional vector search systems require users to think like databases:

- **Semantic queries**: Users can search for "fruity wines" (good for vector similarity)
- **Filter constraints**: Users must manually specify `country='Italy' AND price<30` (database syntax)
- **Cognitive burden**: Users need to understand both natural language and database filtering
- **Limited accessibility**: Non-technical users struggle with structured query syntax

**Example limitation**: A user wants "affordable Italian wines that taste fruity" but must separately perform a semantic search for "fruity wines" and then apply filters for country and price range.

### The Self-Query Solution

Self-query systems bridge this gap by using LLMs as intelligent query interpreters:

- **Natural language input**: "Show me fruity Italian wines under $30"
- **Automatic decomposition**: Separates semantic ("fruity") from filters ("Italian", "under $30")
- **Structured execution**: Converts to proper vector search + metadata filters
- **User-friendly**: No need to learn database query syntax

**What you'll build**: A wine recommendation system that understands complex natural language queries and automatically translates them into efficient vector searches with precise metadata filtering.

### Real-World Applications

- **E-commerce**: "Show me waterproof hiking boots under $150 with good reviews"
- **Content Discovery**: "Find recent articles about AI from reputable sources"
- **Real Estate**: "Modern 3-bedroom houses near schools under $500k"
- **Job Search**: "Remote software engineering jobs at startups paying over $120k"

## Part 2: Practical Walkthrough - Building Self-Query Systems

### Understanding the Query Decomposition Process

The system intelligently separates natural language queries into two components:

```
"Fruity Italian wines under $30" 
    ↓
Semantic: "fruity wines" → Vector Search
Filters: country='Italy' AND price<30 → Metadata Filter
    ↓
Combined Search → Precise Results
```

**Key insight**: LLMs excel at understanding intent and can map natural language to structured filters when given proper schema information.

### Setup and Dependencies

```python
# Core dependencies for self-query systems
!pip install langchain qdrant-client sentence-transformers openai datasets

import os
from typing import List, Dict, Any, Optional
import pandas as pd

from langchain.schema import Document
from langchain.vectorstores import Qdrant
from langchain.embeddings import SentenceTransformerEmbeddings
from langchain.retrievers.self_query.base import SelfQueryRetriever
from langchain.chains.query_constructor.base import AttributeInfo
from langchain.llms import OpenAI
from langchain.callbacks import StdOutCallbackHandler

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from datasets import load_dataset
```

**Key components:**
- `langchain`: Framework with SelfQueryRetriever
- `qdrant-client`: Vector database with metadata support
- `sentence-transformers`: Text embedding generation
- `openai`: LLM for query interpretation

### Initialize Services

```python
# Initialize Qdrant client
qdrant_client = QdrantClient("localhost", port=6333)

# Initialize embedding model
embeddings = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

# Set OpenAI API key for query interpretation
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"

print("Self-query system components initialized!")
```

### Stage 1: Dataset Preparation with Rich Metadata

#### Load and Prepare Wine Dataset

```python
def load_wine_dataset():
    """Load and prepare wine dataset with rich metadata"""
    
    # Load wine reviews dataset
    dataset = load_dataset("tolgacangoz/wine_reviews", split="train[:5000]")
    df = pd.DataFrame(dataset)
    
    # Clean and prepare data
    df = df.dropna(subset=['description', 'country', 'price', 'points'])
    df['price'] = pd.to_numeric(df['price'], errors='coerce')
    df['points'] = pd.to_numeric(df['points'], errors='coerce')
    
    # Remove outliers
    df = df[(df['price'] > 5) & (df['price'] < 500)]
    df = df[(df['points'] >= 80) & (df['points'] <= 100)]
    
    # Create structured documents
    documents = []
    for _, row in df.iterrows():
        doc = Document(
            page_content=row['description'],
            metadata={
                'country': row['country'],
                'price': float(row['price']),
                'points': int(row['points']),
                'variety': row.get('variety', 'Unknown'),
                'winery': row.get('winery', 'Unknown'),
                'province': row.get('province', 'Unknown')
            }
        )
        documents.append(doc)
    
    print(f"Prepared {len(documents)} wine documents")
    return documents

# Load wine dataset
wine_documents = load_wine_dataset()

# Display sample document
sample_doc = wine_documents[0]
print("Sample Document:")
print(f"Description: {sample_doc.page_content[:200]}...")
print(f"Metadata: {sample_doc.metadata}")
```

#### Create Rich Metadata Schema

```python
def define_metadata_schema():
    """Define comprehensive metadata schema for self-query"""
    
    # Define available metadata fields for the LLM
    metadata_field_info = [
        AttributeInfo(
            name="country",
            description="The country where the wine was produced (e.g., Italy, France, US)",
            type="string"
        ),
        AttributeInfo(
            name="price",
            description="The price of the wine in US dollars",
            type="float"
        ),
        AttributeInfo(
            name="points",
            description="The rating score of the wine (80-100 scale)",
            type="integer"
        ),
        AttributeInfo(
            name="variety",
            description="The grape variety or wine type (e.g., Pinot Noir, Chardonnay)",
            type="string"
        ),
        AttributeInfo(
            name="winery",
            description="The name of the winery that produced the wine",
            type="string"
        ),
        AttributeInfo(
            name="province",
            description="The province or region where the wine was produced",
            type="string"
        )
    ]
    
    # Document content description
    document_content_description = "Wine tasting notes and descriptions including flavor profiles, aromas, and characteristics"
    
    return metadata_field_info, document_content_description

# Define metadata schema
metadata_fields, content_description = define_metadata_schema()

print("Metadata Schema Defined:")
for field in metadata_fields:
    print(f"- {field.name} ({field.type}): {field.description}")
```

### Stage 2: Vector Store Setup and Indexing

#### Create Qdrant Collection

```python
def setup_wine_collection(collection_name="wine_self_query"):
    """Create Qdrant collection for wine documents"""
    
    # Delete existing collection
    try:
        qdrant_client.delete_collection(collection_name)
    except:
        pass
    
    # Create new collection
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=384,  # all-MiniLM-L6-v2 dimension
            distance=Distance.COSINE
        )
    )
    
    print(f"Created collection: {collection_name}")
    return collection_name

# Setup collection
collection_name = setup_wine_collection()
```

#### Index Documents with Metadata

```python
def index_wine_documents(documents: List[Document], collection_name: str):
    """Index wine documents in Qdrant with metadata"""
    
    # Create Qdrant vector store
    vector_store = Qdrant(
        client=qdrant_client,
        collection_name=collection_name,
        embeddings=embeddings
    )
    
    # Add documents in batches
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        vector_store.add_documents(batch)
        print(f"Indexed batch {i//batch_size + 1}/{(len(documents) + batch_size - 1)//batch_size}")
    
    print(f"Successfully indexed {len(documents)} wine documents")
    return vector_store

# Index documents
wine_vector_store = index_wine_documents(wine_documents, collection_name)
```

### Stage 3: Baseline Search Comparison

#### Standard Vector Search

```python
def standard_vector_search(query: str, vector_store, k: int = 5):
    """Perform standard vector similarity search"""
    
    results = vector_store.similarity_search(query, k=k)
    
    print(f"Standard Vector Search: '{query}'")
    print("-" * 50)
    
    for i, doc in enumerate(results, 1):
        print(f"{i}. {doc.page_content[:150]}...")
        print(f"   Metadata: {doc.metadata}")
        print()
    
    return results

# Test standard search
standard_results = standard_vector_search("fruity red wine", wine_vector_store)
```

#### Manual Filtered Search

```python
from qdrant_client.models import Filter, FieldCondition, Range, MatchValue

def manual_filtered_search(query: str, vector_store, filters: Dict, k: int = 5):
    """Perform vector search with manual filters"""
    
    # Convert filters to Qdrant format
    qdrant_filter = Filter(must=[])
    
    for field, condition in filters.items():
        if isinstance(condition, dict):
            if 'gte' in condition or 'lte' in condition:
                # Range filter
                range_filter = {}
                if 'gte' in condition:
                    range_filter['gte'] = condition['gte']
                if 'lte' in condition:
                    range_filter['lte'] = condition['lte']
                
                qdrant_filter.must.append(
                    FieldCondition(key=field, range=Range(**range_filter))
                )
        else:
            # Exact match filter
            qdrant_filter.must.append(
                FieldCondition(key=field, match=MatchValue(value=condition))
            )
    
    # Perform filtered search
    results = vector_store.similarity_search(
        query, 
        k=k, 
        filter=qdrant_filter
    )
    
    print(f"Manual Filtered Search: '{query}'")
    print(f"Filters: {filters}")
    print("-" * 50)
    
    for i, doc in enumerate(results, 1):
        print(f"{i}. {doc.page_content[:150]}...")
        print(f"   Metadata: {doc.metadata}")
        print()
    
    return results

# Test manual filtered search
manual_filters = {
    "country": "Italy",
    "price": {"lte": 30},
    "points": {"gte": 88}
}

manual_results = manual_filtered_search(
    "fruity red wine", 
    wine_vector_store, 
    manual_filters
)
```

### Stage 4: Self-Query Implementation

#### Create Self-Query Retriever

```python
def create_self_query_retriever(vector_store, metadata_fields, content_description):
    """Create SelfQueryRetriever with metadata awareness"""
    
    # Initialize OpenAI LLM for query interpretation
    llm = OpenAI(temperature=0)
    
    # Create self-query retriever
    retriever = SelfQueryRetriever.from_llm(
        llm=llm,
        vectorstore=vector_store,
        document_contents=content_description,
        metadata_field_info=metadata_fields,
        verbose=True  # Enable detailed logging
    )
    
    print("Self-query retriever created successfully!")
    return retriever

# Create self-query retriever
self_query_retriever = create_self_query_retriever(
    wine_vector_store,
    metadata_fields,
    content_description
)
```

#### Test Natural Language Queries

```python
def test_self_query(query: str, retriever, k: int = 5):
    """Test self-query retriever with natural language"""
    
    print(f"🔍 Self-Query: '{query}'")
    print("=" * 60)
    
    # Enable tracing to see LLM reasoning
    callback_handler = StdOutCallbackHandler()
    
    try:
        # Execute self-query
        results = retriever.get_relevant_documents(
            query,
            callbacks=[callback_handler]
        )
        
        print(f"\n✅ Found {len(results)} results:")
        print("-" * 40)
        
        for i, doc in enumerate(results[:k], 1):
            print(f"{i}. {doc.page_content[:150]}...")
            print(f"   Country: {doc.metadata.get('country', 'N/A')}")
            print(f"   Price: ${doc.metadata.get('price', 'N/A')}")
            print(f"   Points: {doc.metadata.get('points', 'N/A')}")
            print(f"   Variety: {doc.metadata.get('variety', 'N/A')}")
            print()
        
        return results
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return []

# Test various natural language queries
test_queries = [
    "Show me fruity Italian wines under $30",
    "Find highly rated French wines over $50",
    "I want Pinot Noir from California with points above 90",
    "Affordable Spanish wines that taste earthy",
    "Premium Chardonnay from any country with excellent ratings"
]

query_results = {}
for query in test_queries:
    results = test_self_query(query, self_query_retriever)
    query_results[query] = results
    print("\n" + "="*80 + "\n")
```

### Stage 5: Advanced Self-Query Features

#### Query Validation and Error Handling

```python
def enhanced_self_query(query: str, retriever, max_price: float = 1000):
    """Enhanced self-query with validation and error handling"""
    
    print(f"🔍 Enhanced Self-Query: '{query}'")
    
    try:
        # Get documents with detailed tracing
        results = retriever.get_relevant_documents(query)
        
        # Validate results make sense
        valid_results = []
        for doc in results:
            metadata = doc.metadata
            
            # Basic validation
            if (metadata.get('price', 0) <= max_price and 
                metadata.get('points', 0) >= 80):
                valid_results.append(doc)
        
        print(f"✅ Valid results: {len(valid_results)}/{len(results)}")
        
        if not valid_results:
            print("🔄 No valid results found. Trying broader search...")
            # Fallback to semantic search only
            fallback_results = retriever.vectorstore.similarity_search(query, k=5)
            return fallback_results[:3]
        
        return valid_results[:5]
        
    except Exception as e:
        print(f"❌ Self-query failed: {e}")
        print("🔄 Falling back to standard vector search...")
        
        # Fallback to standard search
        return retriever.vectorstore.similarity_search(query, k=5)

# Test enhanced queries
enhanced_queries = [
    "Show me the best wines from New Zealand",
    "Find me wines that pair well with seafood under $25",
    "I need a special occasion wine from Bordeaux",
    "What are some good everyday drinking wines?"
]

for query in enhanced_queries:
    results = enhanced_self_query(query, self_query_retriever)
    print(f"Results: {len(results)} wines found\n")
```

#### Query Analysis and Debugging

```python
def analyze_query_decomposition(query: str, retriever):
    """Analyze how the LLM decomposes natural language queries"""
    
    print(f"🔬 Query Analysis: '{query}'")
    print("-" * 50)
    
    # Access the query constructor to see decomposition
    try:
        # This would show the internal LLM prompt and response
        # Note: Actual implementation may vary based on LangChain version
        
        print("Query decomposition process:")
        print("1. Original query:", query)
        print("2. LLM receives schema:", [f.name for f in metadata_fields])
        print("3. LLM identifies semantic vs filter components")
        print("4. Generates structured filter syntax")
        print("5. Executes combined vector + filter search")
        
        # Execute and show results
        results = retriever.get_relevant_documents(query)
        
        print(f"\nResult summary:")
        print(f"- Documents found: {len(results)}")
        if results:
            countries = set(doc.metadata.get('country') for doc in results)
            price_range = [doc.metadata.get('price') for doc in results if doc.metadata.get('price')]
            
            print(f"- Countries: {list(countries)}")
            if price_range:
                print(f"- Price range: ${min(price_range):.2f} - ${max(price_range):.2f}")
        
    except Exception as e:
        print(f"Analysis error: {e}")

# Analyze different query types
analysis_queries = [
    "Expensive wines from France",           # Price + Country
    "High scoring Pinot Noir",             # Points + Variety  
    "Italian wines between $20 and $40",   # Country + Price Range
    "Wines from Sonoma County over 95 points"  # Province + Points
]

for query in analysis_queries:
    analyze_query_decomposition(query, self_query_retriever)
    print("\n" + "="*60 + "\n")
```

#### Custom Query Templates

```python
def create_specialized_retriever(vector_store, domain: str = "wine"):
    """Create domain-specific retriever with custom templates"""
    
    if domain == "wine":
        # Wine-specific metadata schema
        specialized_fields = [
            AttributeInfo(
                name="price_tier",
                description="Price category: budget (under $20), mid-range ($20-50), premium (over $50)",
                type="string"
            ),
            AttributeInfo(
                name="rating_tier", 
                description="Quality tier: good (80-85), very good (86-90), excellent (91-95), outstanding (96-100)",
                type="string"
            ),
            AttributeInfo(
                name="style",
                description="Wine style: light, medium, full-bodied, sparkling, sweet, dry",
                type="string"
            )
        ]
        
        # Enhance documents with derived fields
        enhanced_docs = []
        for doc in wine_documents[:100]:  # Sample for demo
            metadata = doc.metadata.copy()
            
            # Add price tier
            price = metadata.get('price', 0)
            if price < 20:
                metadata['price_tier'] = 'budget'
            elif price < 50:
                metadata['price_tier'] = 'mid-range'
            else:
                metadata['price_tier'] = 'premium'
            
            # Add rating tier
            points = metadata.get('points', 80)
            if points < 86:
                metadata['rating_tier'] = 'good'
            elif points < 91:
                metadata['rating_tier'] = 'very good'
            elif points < 96:
                metadata['rating_tier'] = 'excellent'
            else:
                metadata['rating_tier'] = 'outstanding'
            
            enhanced_doc = Document(
                page_content=doc.page_content,
                metadata=metadata
            )
            enhanced_docs.append(enhanced_doc)
        
        # Create specialized retriever
        specialized_store = Qdrant(
            client=qdrant_client,
            collection_name="specialized_wine",
            embeddings=embeddings
        )
        
        # Index enhanced documents
        specialized_store.add_documents(enhanced_docs)
        
        # Create retriever with enhanced schema
        llm = OpenAI(temperature=0)
        specialized_retriever = SelfQueryRetriever.from_llm(
            llm=llm,
            vectorstore=specialized_store,
            document_contents="Wine tasting notes with enhanced categorization",
            metadata_field_info=specialized_fields,
            verbose=True
        )
        
        return specialized_retriever
    
    return None

# Test specialized retriever
specialized_retriever = create_specialized_retriever(wine_vector_store)

if specialized_retriever:
    specialized_queries = [
        "Show me budget wines with excellent ratings",
        "Find premium full-bodied wines",
        "I want mid-range wines that are very good quality"
    ]
    
    for query in specialized_queries:
        print(f"🍷 Specialized Query: '{query}'")
        results = specialized_retriever.get_relevant_documents(query)
        print(f"Found {len(results)} specialized matches\n")
```

## Part 3: Mental Models & Deep Dives

### Understanding Query Decomposition

**Mental Model**: Think of the LLM as a skilled librarian who understands both what you're looking for and where to find it:

**User Request**: "I want a fruity Italian wine under $30"

**Librarian's Thinking**:
1. **Content**: "fruity wine" → Search wine descriptions for flavor profiles
2. **Location**: "Italian" → Filter by country metadata  
3. **Budget**: "under $30" → Filter by price range
4. **Action**: Combine semantic search with precise filters

### The Schema-Driven Approach

**Mental Model**: AttributeInfo acts like a vocabulary lesson for the LLM:

```python
# Without schema - LLM guesses
"Italian wines" → Maybe searches for "Italian" in text?

# With schema - LLM knows exactly what to do  
AttributeInfo(name="country", description="Wine origin country", type="string")
"Italian wines" → Filter: country == "Italy"
```

### Self-Query vs Traditional Approaches

**Traditional Database Query**:
```sql
SELECT * FROM wines 
WHERE country = 'Italy' 
  AND price < 30 
  AND description LIKE '%fruity%'
```

**Self-Query Natural Language**:
```python
"Show me fruity Italian wines under $30"
# Automatically becomes: semantic search + structured filters
```

### Advanced Query Understanding Patterns

#### Query Complexity Handling

```python
def analyze_query_complexity(query: str) -> Dict[str, Any]:
    """Analyze natural language query complexity"""
    
    complexity_indicators = {
        "semantic_terms": [],      # Flavor, style descriptions
        "filter_terms": [],       # Country, price, ratings
        "comparison_operators": [], # Under, over, between
        "logical_connectors": []   # And, or, but
    }
    
    # Semantic indicators
    semantic_keywords = ["fruity", "dry", "sweet", "bold", "light", "crisp", "smooth"]
    for keyword in semantic_keywords:
        if keyword in query.lower():
            complexity_indicators["semantic_terms"].append(keyword)
    
    # Filter indicators  
    filter_keywords = ["country", "price", "points", "rating", "variety", "region"]
    for keyword in filter_keywords:
        if keyword in query.lower():
            complexity_indicators["filter_terms"].append(keyword)
    
    # Comparison operators
    comparison_keywords = ["under", "over", "above", "below", "between", "less than", "more than"]
    for keyword in comparison_keywords:
        if keyword in query.lower():
            complexity_indicators["comparison_operators"].append(keyword)
    
    return complexity_indicators

# Test complexity analysis
complex_queries = [
    "Simple fruity wine",  # Low complexity
    "Italian wines under $25",  # Medium complexity  
    "Full-bodied Cabernet from Napa Valley over 90 points but under $60"  # High complexity
]

for query in complex_queries:
    complexity = analyze_query_complexity(query)
    print(f"Query: {query}")
    print(f"Complexity: {complexity}")
    print()
```

#### Error Recovery Strategies

```python
def robust_self_query(query: str, retriever, max_retries: int = 3):
    """Self-query with error recovery and query refinement"""
    
    for attempt in range(max_retries):
        try:
            results = retriever.get_relevant_documents(query)
            
            if results:
                return results
            
            # No results - try query refinement
            if attempt < max_retries - 1:
                print(f"No results found. Attempting query refinement...")
                
                # Simplify query by removing complex filters
                simplified_query = simplify_query(query)
                query = simplified_query
                print(f"Trying simplified query: {simplified_query}")
                
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            
            if attempt < max_retries - 1:
                # Try with more generic query
                query = extract_semantic_content(query)
                print(f"Trying semantic-only query: {query}")
    
    # Final fallback to basic search
    return retriever.vectorstore.similarity_search(query, k=5)

def simplify_query(query: str) -> str:
    """Remove complex filters from query"""
    # Remove price/rating constraints for broader search
    filters_to_remove = ["under", "over", "above", "below", "points", "$"]
    
    simplified = query
    for filter_term in filters_to_remove:
        # Remove phrases containing filter terms
        words = simplified.split()
        filtered_words = []
        skip_next = False
        
        for word in words:
            if skip_next:
                skip_next = False
                continue
                
            if filter_term in word.lower():
                skip_next = True  # Skip the number/value that follows
                continue
                
            filtered_words.append(word)
        
        simplified = " ".join(filtered_words)
    
    return simplified.strip()

def extract_semantic_content(query: str) -> str:
    """Extract only semantic search terms"""
    semantic_terms = ["fruity", "dry", "sweet", "bold", "light", "smooth", "crisp"]
    wine_varieties = ["pinot", "chardonnay", "cabernet", "merlot", "sauvignon"]
    
    words = query.lower().split()
    semantic_words = []
    
    for word in words:
        if any(term in word for term in semantic_terms + wine_varieties):
            semantic_words.append(word)
    
    return " ".join(semantic_words) or "wine"
```

### Performance Optimization

#### Caching and Efficiency

```python
import hashlib
from functools import lru_cache

class CachedSelfQueryRetriever:
    """Self-query retriever with result caching"""
    
    def __init__(self, base_retriever):
        self.base_retriever = base_retriever
        self.cache = {}
    
    def get_relevant_documents(self, query: str, **kwargs):
        # Create cache key
        cache_key = hashlib.md5(query.encode()).hexdigest()
        
        if cache_key in self.cache:
            print(f"Cache hit for query: {query}")
            return self.cache[cache_key]
        
        # Execute query
        results = self.base_retriever.get_relevant_documents(query, **kwargs)
        
        # Cache results
        self.cache[cache_key] = results
        
        return results

# Create cached retriever
cached_retriever = CachedSelfQueryRetriever(self_query_retriever)
```

#### Parallel Query Processing

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def parallel_self_queries(queries: List[str], retriever):
    """Process multiple queries in parallel"""
    
    def execute_query(query):
        try:
            return retriever.get_relevant_documents(query)
        except Exception as e:
            return f"Error: {e}"
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(executor, execute_query, query)
            for query in queries
        ]
        
        results = await asyncio.gather(*tasks)
        
        return dict(zip(queries, results))

# Test parallel processing
parallel_queries = [
    "Budget Italian wines",
    "Premium French Champagne", 
    "Organic Spanish reds"
]

# Run parallel queries
# results = asyncio.run(parallel_self_queries(parallel_queries, self_query_retriever))
```

### Production Deployment Considerations

#### Monitoring and Analytics

```python
def monitor_self_query_performance(retriever, queries: List[str]):
    """Monitor self-query system performance"""
    
    metrics = {
        "total_queries": len(queries),
        "successful_queries": 0,
        "failed_queries": 0,
        "avg_results_per_query": 0,
        "common_failure_types": {}
    }
    
    total_results = 0
    
    for query in queries:
        try:
            results = retriever.get_relevant_documents(query)
            metrics["successful_queries"] += 1
            total_results += len(results)
            
        except Exception as e:
            metrics["failed_queries"] += 1
            error_type = type(e).__name__
            metrics["common_failure_types"][error_type] = (
                metrics["common_failure_types"].get(error_type, 0) + 1
            )
    
    if metrics["successful_queries"] > 0:
        metrics["avg_results_per_query"] = total_results / metrics["successful_queries"]
    
    return metrics
```

This comprehensive self-query system demonstrates how to build intelligent, natural language interfaces that automatically translate user intent into precise vector searches with metadata filtering, making complex database queries accessible to anyone.