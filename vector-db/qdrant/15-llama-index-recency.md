# LlamaIndex Recency

> **Source**: [llama_index_recency](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/llama_index_recency)

This tutorial demonstrates how to build time-aware Q&A systems using LlamaIndex and Qdrant that can provide up-to-date answers by understanding temporal context and prioritizing recent information.

## Part 1: Core Concept - Why Recency Matters in Q&A

### The Problem with Static Knowledge

Traditional Q&A systems treat all information as equally current, leading to outdated or incorrect answers:

- **Stale information**: "Who is the current US President?" might return 2020 data in 2024
- **Context collapse**: Facts change over time but systems don't understand "when"
- **Conflicting information**: Multiple answers for time-sensitive questions with no temporal ranking
- **User frustration**: Outdated responses damage trust and usability

**Example problem**: A user asks "What is Apple's stock price?" and gets data from 6 months ago instead of recent information.

### The Recency Solution

Time-aware Q&A systems solve this by incorporating temporal understanding:

- **Temporal metadata**: Store and track when information was published
- **Recency ranking**: Prioritize newer information for time-sensitive queries
- **Date filtering**: Answer questions about specific time periods accurately
- **Context awareness**: Understand when facts apply versus when they become outdated

**What you'll build**: A news Q&A system using LlamaIndex and Qdrant that understands publication dates and can answer both current events questions and historical queries with temporal accuracy.

### Real-World Applications

- **News and Media**: Current events, breaking news, market updates
- **Financial Services**: Stock prices, market conditions, regulatory changes
- **Healthcare**: Latest treatment guidelines, drug approvals, research findings
- **Legal**: Recent case law, regulation updates, policy changes

## Part 2: Practical Walkthrough - Building Time-Aware Q&A

### Understanding the Temporal Architecture

The system combines three key components for time awareness:

```
Documents + Timestamps → [LlamaIndex] → Vector Storage + Metadata
                                     ↓
Query → Retrieval → [Recency Post-processor] → [Re-ranker] → Answer
```

**Key insight**: Store temporal metadata alongside vectors, then use post-processing to apply recency logic.

### Setup and Dependencies

```python
# Core dependencies for temporal Q&A
!pip install llama-index qdrant-client cohere

import os
from datetime import datetime, timedelta
from pathlib import Path
import re

from llama_index.core import VectorStoreIndex, Document
from llama_index.core.storage.storage_context import StorageContext
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.core.postprocessor import FixedRecencyPostprocessor
from llama_index.postprocessor.cohere_rerank import CohereRerank
from llama_index.core.query_engine import RetrieverQueryEngine

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
```

**Key components:**
- `llama-index`: High-level framework for RAG applications
- `FixedRecencyPostprocessor`: Built-in temporal ranking
- `CohereRerank`: Advanced result re-ranking
- `qdrant-client`: Vector storage with metadata support

### Initialize Services

```python
# Initialize Qdrant client
qdrant_client = QdrantClient("localhost", port=6333)

# Set up API keys for enhanced features
os.environ["COHERE_API_KEY"] = "your-cohere-api-key"  # For re-ranking
os.environ["OPENAI_API_KEY"] = "your-openai-api-key"  # For embeddings and LLM
```

### Stage 1: Temporal Data Preparation

#### Load News Dataset with Temporal Information

```python
def load_news_with_dates(dataset_path="news_articles/"):
    """Load news articles with publication dates from filenames"""
    
    documents = []
    date_pattern = r'(\d{4}-\d{2}-\d{2})'  # Match YYYY-MM-DD format
    
    for file_path in Path(dataset_path).glob("*.txt"):
        # Extract date from filename
        filename = file_path.name
        date_match = re.search(date_pattern, filename)
        
        if date_match:
            publication_date = date_match.group(1)
            
            # Load article content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Create document with temporal metadata
            doc = Document(
                text=content,
                metadata={
                    "date": publication_date,
                    "source": filename,
                    "timestamp": datetime.strptime(publication_date, "%Y-%m-%d")
                }
            )
            documents.append(doc)
    
    # Sort by date for easier analysis
    documents.sort(key=lambda x: x.metadata["timestamp"])
    
    print(f"Loaded {len(documents)} documents")
    print(f"Date range: {documents[0].metadata['date']} to {documents[-1].metadata['date']}")
    
    return documents

# Load documents with temporal metadata
news_documents = load_news_with_dates()
```

#### Alternative: Synthetic News Data Generation

```python
def create_synthetic_news_data():
    """Create synthetic news data for demonstration"""
    
    documents = []
    
    # Sample news articles with different dates
    articles = [
        {
            "date": "2024-01-15",
            "content": "President Biden announces new climate initiative targeting 50% emission reduction by 2030. The comprehensive plan includes federal investments in renewable energy and electric vehicle infrastructure."
        },
        {
            "date": "2024-06-20", 
            "content": "Tech stocks surge as AI companies report strong quarterly earnings. NVIDIA leads gains with 15% increase following data center demand growth."
        },
        {
            "date": "2023-03-10",
            "content": "Federal Reserve raises interest rates by 0.25% to combat inflation. Chairman Powell signals continued monetary tightening may be necessary."
        },
        {
            "date": "2024-08-05",
            "content": "Summer Olympics in Paris conclude with record-breaking performances. USA tops medal count with 40 gold medals in swimming and athletics."
        },
        {
            "date": "2023-11-30",
            "content": "Cryptocurrency market experiences volatility as Bitcoin reaches $38,000. Regulatory uncertainty continues to impact digital asset prices."
        }
    ]
    
    for article in articles:
        doc = Document(
            text=article["content"],
            metadata={
                "date": article["date"],
                "timestamp": datetime.strptime(article["date"], "%Y-%m-%d"),
                "source": f"news_{article['date']}.txt"
            }
        )
        documents.append(doc)
    
    return documents

# Use synthetic data if no news dataset available
if not news_documents:
    news_documents = create_synthetic_news_data()
```

### Stage 2: Qdrant Integration with LlamaIndex

#### Set Up Vector Store with Temporal Metadata

```python
def setup_temporal_vector_store(collection_name="temporal_news"):
    """Create Qdrant collection optimized for temporal data"""
    
    # Delete existing collection if it exists
    try:
        qdrant_client.delete_collection(collection_name)
    except:
        pass
    
    # Create collection with appropriate vector size
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=1536,  # OpenAI text-embedding-ada-002 dimension
            distance=Distance.COSINE
        )
    )
    
    # Create LlamaIndex vector store wrapper
    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=collection_name
    )
    
    return vector_store

# Initialize vector store
vector_store = setup_temporal_vector_store()
storage_context = StorageContext.from_defaults(vector_store=vector_store)
```

#### Index Documents with Temporal Metadata

```python
def build_temporal_index(documents, vector_store, storage_context):
    """Build vector index preserving temporal metadata"""
    
    print("Building temporal vector index...")
    
    # Create index from documents
    index = VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        show_progress=True
    )
    
    print(f"Indexed {len(documents)} documents with temporal metadata")
    
    return index

# Build the temporal index
temporal_index = build_temporal_index(news_documents, vector_store, storage_context)
```

### Stage 3: Basic Query Engine

#### Standard Query Engine (No Recency)

```python
def create_basic_query_engine(index):
    """Create basic query engine without temporal awareness"""
    
    query_engine = index.as_query_engine(
        similarity_top_k=5,
        response_mode="compact"
    )
    
    return query_engine

# Test basic query engine
basic_engine = create_basic_query_engine(temporal_index)

# Test queries
test_query = "What are the latest developments in AI technology?"
basic_response = basic_engine.query(test_query)

print("Basic Query Response:")
print(basic_response.response)
print("\nSources:")
for node in basic_response.source_nodes:
    print(f"- Date: {node.metadata.get('date', 'Unknown')}")
    print(f"  Content: {node.text[:100]}...")
```

### Stage 4: Recency-Aware Query Engine

#### Implementing Temporal Post-Processing

```python
def create_recency_aware_engine(index, recency_days=90):
    """Create query engine with recency post-processing"""
    
    # Configure recency post-processor
    recency_postprocessor = FixedRecencyPostprocessor(
        date_key="date",  # Metadata field containing date
        service_context=index.service_context
    )
    
    # Build query engine with post-processor
    query_engine = index.as_query_engine(
        similarity_top_k=10,  # Get more candidates for post-processing
        node_postprocessors=[recency_postprocessor],
        response_mode="compact"
    )
    
    return query_engine

# Create recency-aware engine
recency_engine = create_recency_aware_engine(temporal_index)

# Test with same query
recency_response = recency_engine.query(test_query)

print("Recency-Aware Response:")
print(recency_response.response)
print("\nSources (should prioritize recent dates):")
for node in recency_response.source_nodes:
    print(f"- Date: {node.metadata.get('date', 'Unknown')}")
    print(f"  Content: {node.text[:100]}...")
```

#### Advanced Recency with Re-ranking

```python
def create_enhanced_temporal_engine(index):
    """Create query engine with both recency and semantic re-ranking"""
    
    # Set up post-processors
    recency_postprocessor = FixedRecencyPostprocessor(
        date_key="date"
    )
    
    # Cohere re-ranker for semantic relevance
    cohere_rerank = CohereRerank(
        api_key=os.environ["COHERE_API_KEY"],
        top_n=5  # Final number of results
    )
    
    # Combine post-processors (order matters!)
    query_engine = index.as_query_engine(
        similarity_top_k=15,  # More candidates for processing
        node_postprocessors=[
            recency_postprocessor,  # Apply recency first
            cohere_rerank           # Then semantic re-ranking
        ],
        response_mode="tree_summarize"  # Better for multiple sources
    )
    
    return query_engine

# Create enhanced engine
enhanced_engine = create_enhanced_temporal_engine(temporal_index)
```

### Stage 5: Temporal Query Patterns

#### Date-Specific Queries

```python
def query_with_date_context(engine, query, context_date=None):
    """Query with additional date context"""
    
    if context_date:
        # Add temporal context to query
        temporal_query = f"As of {context_date}: {query}"
    else:
        temporal_query = query
    
    response = engine.query(temporal_query)
    
    return response

# Test temporal queries
temporal_queries = [
    ("Who was the US President in 2020?", None),
    ("What is the current status of AI development?", "2024"),
    ("What were the latest market trends?", datetime.now().strftime("%Y-%m-%d")),
    ("What happened with cryptocurrency in 2023?", None)
]

for query, date_context in temporal_queries:
    print(f"\n🔍 Query: {query}")
    if date_context:
        print(f"📅 Context: {date_context}")
    
    response = query_with_date_context(enhanced_engine, query, date_context)
    print(f"📝 Answer: {response.response}")
    
    # Show source dates
    print("📚 Sources:")
    for node in response.source_nodes[:3]:
        print(f"   - {node.metadata.get('date', 'Unknown')}: {node.text[:80]}...")
```

#### Comparative Temporal Analysis

```python
def compare_temporal_engines(query, engines):
    """Compare responses from different temporal configurations"""
    
    results = {}
    
    for name, engine in engines.items():
        response = engine.query(query)
        results[name] = {
            'response': response.response,
            'source_dates': [node.metadata.get('date', 'Unknown') 
                           for node in response.source_nodes]
        }
    
    return results

# Create comparison engines
engines = {
    "Basic (No Recency)": basic_engine,
    "Recency-Aware": recency_engine,
    "Enhanced (Recency + Rerank)": enhanced_engine
}

# Compare results
comparison_query = "What are the recent developments in technology?"
comparison_results = compare_temporal_engines(comparison_query, engines)

print(f"Comparison for: '{comparison_query}'\n")
for engine_name, result in comparison_results.items():
    print(f"🔧 {engine_name}:")
    print(f"   Response: {result['response'][:150]}...")
    print(f"   Source Dates: {result['source_dates'][:3]}")
    print()
```

## Part 3: Mental Models & Deep Dives

### Understanding Temporal Ranking

**Mental Model**: Think of recency processing like a news editor prioritizing stories:

**Without Recency**: All stories treated equally regardless of when they happened
- "Stock market reaches new high" (from 2020) ranks equally with recent news
- Users get outdated information thinking it's current

**With Recency**: Recent stories get priority, but relevance still matters
- Recent + relevant = highest priority
- Recent + less relevant = medium priority  
- Old + very relevant = lower priority
- Old + less relevant = lowest priority

### The Post-Processing Pipeline

**Mental Model**: Think of post-processors as a series of filters and sorters:

```python
# Vector search finds semantically similar content
raw_results = vector_search(query)  # 15 results

# Recency post-processor reorders by temporal relevance
recency_filtered = apply_recency_boost(raw_results)  # Same 15, reordered

# Re-ranker applies deeper semantic understanding
final_results = semantic_rerank(recency_filtered, top_k=5)  # Best 5
```

### Temporal Metadata Strategy

**Effective temporal metadata design**:
```python
# Good metadata structure
metadata = {
    "date": "2024-03-15",           # Human-readable date
    "timestamp": datetime_object,    # For calculations
    "date_precision": "day",         # How precise is the date?
    "temporal_scope": "current",     # Is this about current events?
    "expiry_date": "2024-12-31"     # When does this info become stale?
}
```

### Advanced Temporal Techniques

#### Time Decay Functions

```python
def calculate_time_decay_score(doc_date, query_date, decay_factor=0.1):
    """Calculate time-based relevance decay"""
    
    days_old = (query_date - doc_date).days
    
    # Exponential decay: newer = higher score
    decay_score = math.exp(-decay_factor * days_old / 365)
    
    return decay_score

def apply_custom_recency_scoring(nodes, query_date=None):
    """Apply custom time decay to search results"""
    
    if query_date is None:
        query_date = datetime.now()
    
    scored_nodes = []
    for node in nodes:
        doc_date = node.metadata.get("timestamp")
        if doc_date:
            time_score = calculate_time_decay_score(doc_date, query_date)
            # Combine with original relevance score
            combined_score = node.score * (1 + time_score)
            node.score = combined_score
        
        scored_nodes.append(node)
    
    # Re-sort by combined score
    return sorted(scored_nodes, key=lambda x: x.score, reverse=True)
```

#### Temporal Query Classification

```python
def classify_temporal_intent(query):
    """Classify if query requires recent vs historical information"""
    
    # Keywords indicating recency preference
    recent_indicators = [
        "current", "latest", "recent", "now", "today",
        "this year", "2024", "upcoming", "new"
    ]
    
    # Keywords indicating historical query
    historical_indicators = [
        "was", "were", "in 2020", "last decade", 
        "history of", "originally", "first"
    ]
    
    query_lower = query.lower()
    
    recent_score = sum(1 for indicator in recent_indicators 
                      if indicator in query_lower)
    historical_score = sum(1 for indicator in historical_indicators 
                          if indicator in query_lower)
    
    if recent_score > historical_score:
        return "recent"
    elif historical_score > recent_score:
        return "historical"
    else:
        return "neutral"

# Example usage
def adaptive_temporal_query(query, index):
    """Adapt retrieval strategy based on temporal intent"""
    
    intent = classify_temporal_intent(query)
    
    if intent == "recent":
        # Strong recency preference
        return create_recency_aware_engine(index, recency_days=30)
    elif intent == "historical":
        # Disable recency bias
        return create_basic_query_engine(index)
    else:
        # Balanced approach
        return create_enhanced_temporal_engine(index)
```

#### Multi-Temporal Indexing

```python
def create_temporal_buckets(documents):
    """Organize documents into temporal buckets for efficient filtering"""
    
    buckets = {
        "current": [],      # Last 30 days
        "recent": [],       # Last 6 months
        "historical": []    # Older than 6 months
    }
    
    cutoff_recent = datetime.now() - timedelta(days=30)
    cutoff_historical = datetime.now() - timedelta(days=180)
    
    for doc in documents:
        doc_date = doc.metadata.get("timestamp")
        if not doc_date:
            buckets["historical"].append(doc)
        elif doc_date >= cutoff_recent:
            buckets["current"].append(doc)
        elif doc_date >= cutoff_historical:
            buckets["recent"].append(doc)
        else:
            buckets["historical"].append(doc)
    
    return buckets

def query_temporal_bucket(query, buckets, bucket_priority=["current", "recent", "historical"]):
    """Query temporal buckets in priority order"""
    
    for bucket_name in bucket_priority:
        bucket_docs = buckets[bucket_name]
        if bucket_docs:
            # Create temporary index for this bucket
            bucket_index = VectorStoreIndex.from_documents(bucket_docs)
            engine = bucket_index.as_query_engine()
            
            response = engine.query(query)
            
            # If we get a good response, return it
            if len(response.source_nodes) > 0:
                return response, bucket_name
    
    return None, None
```

### Performance Optimization for Temporal Systems

#### Caching Strategies

```python
from functools import lru_cache
import hashlib

def cache_temporal_queries(func):
    """Cache temporal query results with date awareness"""
    cache = {}
    
    def wrapper(query, date_context=None):
        # Create cache key including date
        cache_key = hashlib.md5(
            f"{query}_{date_context}_{datetime.now().date()}".encode()
        ).hexdigest()
        
        if cache_key not in cache:
            cache[cache_key] = func(query, date_context)
        
        return cache[cache_key]
    
    return wrapper

@cache_temporal_queries
def cached_temporal_query(query, date_context=None):
    """Cached temporal query execution"""
    return enhanced_engine.query(query)
```

#### Incremental Updates

```python
def update_temporal_index(index, new_documents):
    """Efficiently update index with new documents"""
    
    # Add new documents to existing index
    for doc in new_documents:
        index.insert(doc)
    
    # Optionally remove very old documents
    current_date = datetime.now()
    cutoff_date = current_date - timedelta(days=365*2)  # 2 years
    
    # This would require custom implementation based on your needs
    remove_outdated_documents(index, cutoff_date)

def remove_outdated_documents(index, cutoff_date):
    """Remove documents older than cutoff date"""
    # Implementation depends on your specific requirements
    # Could involve filtering the vector store based on metadata
    pass
```

### Real-World Implementation Considerations

#### Handling Different Time Zones

```python
import pytz

def normalize_temporal_metadata(documents, target_timezone="UTC"):
    """Normalize all dates to a consistent timezone"""
    
    target_tz = pytz.timezone(target_timezone)
    
    for doc in documents:
        if "timestamp" in doc.metadata:
            timestamp = doc.metadata["timestamp"]
            
            # If timestamp is naive, assume UTC
            if timestamp.tzinfo is None:
                timestamp = pytz.utc.localize(timestamp)
            
            # Convert to target timezone
            normalized = timestamp.astimezone(target_tz)
            doc.metadata["timestamp"] = normalized
            doc.metadata["date"] = normalized.strftime("%Y-%m-%d")
    
    return documents
```

#### Quality Monitoring

```python
def monitor_temporal_performance(engine, test_queries):
    """Monitor how well the temporal system performs"""
    
    metrics = {
        "recency_accuracy": 0,
        "temporal_consistency": 0,
        "response_relevance": 0
    }
    
    for query in test_queries:
        response = engine.query(query["question"])
        
        # Check if sources match expected time period
        expected_period = query.get("expected_period")
        if expected_period:
            source_dates = [node.metadata.get("date") for node in response.source_nodes]
            period_match = check_period_match(source_dates, expected_period)
            metrics["recency_accuracy"] += period_match
    
    # Normalize metrics
    for key in metrics:
        metrics[key] /= len(test_queries)
    
    return metrics
```

This comprehensive temporal Q&A system demonstrates how to build intelligent, time-aware applications that provide accurate, up-to-date information while maintaining the ability to answer historical questions with appropriate temporal context.