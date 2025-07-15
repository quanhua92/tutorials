# RAG with Qdrant and DeepSeek

> **Source**: [rag-with-qdrant-deepseek](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/rag-with-qdrant-deepseek)

This tutorial demonstrates how to build a Retrieval-Augmented Generation (RAG) system using Qdrant for knowledge retrieval and DeepSeek for intelligent response generation, showcasing how to enhance language models with custom knowledge bases.

## Part 1: Core Concept - Why RAG with DeepSeek Matters

### The Knowledge Gap Problem

Large Language Models like DeepSeek have vast knowledge from training, but face critical limitations:

- **Training cutoff**: Knowledge frozen at training time, can't access recent information
- **Domain gaps**: Limited knowledge in specialized or proprietary domains
- **Hallucination**: Generate plausible but incorrect information when uncertain
- **No source attribution**: Can't cite or verify where information came from

**Example problem**: Asking DeepSeek about your company's specific policies, recent product updates, or internal documentation will result in generic responses or hallucinations.

### The RAG Solution

RAG bridges this gap by combining retrieval and generation:

- **Custom knowledge**: Add any information to your vector database
- **Real-time updates**: Update knowledge base without retraining models
- **Source attribution**: Know exactly which documents informed the response
- **Reduced hallucination**: Model answers based on provided context, not speculation

**What you'll build**: A RAG system that uses Qdrant to retrieve relevant information from your knowledge base and DeepSeek to generate intelligent, contextual responses based on that information.

### Real-World Applications

- **Customer Support**: Answer questions using your knowledge base and documentation
- **Internal Q&A**: Employee queries answered from company policies and procedures
- **Research Assistance**: Query scientific papers and technical documentation
- **Product Information**: Provide accurate details about your products and services

## Part 2: Practical Walkthrough - Building RAG with DeepSeek

### Understanding the RAG Architecture

The system follows a simple but powerful pattern:

```
User Query → [Qdrant Search] → Relevant Context → [DeepSeek + Context] → Answer
```

**Key insight**: Qdrant finds the facts, DeepSeek interprets and explains them.

### Setup and Dependencies

```python
# Core dependencies for RAG with DeepSeek
!pip install qdrant-client[fastembed] requests

import requests
import json
import os
from typing import List, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
```

**Key components:**
- `qdrant-client[fastembed]`: Vector database with built-in embedding generation
- `requests`: HTTP client for DeepSeek API calls
- `json`: Handle API request/response formatting

### Initialize Services

```python
# Initialize Qdrant client (local or cloud)
qdrant_client = QdrantClient("localhost", port=6333)
# For Qdrant Cloud: QdrantClient(url="your-cluster-url", api_key="your-api-key")

# DeepSeek API configuration
DEEPSEEK_API_KEY = "your-deepseek-api-key"  # Get from https://platform.deepseek.com
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def query_deepseek(prompt: str, model: str = "deepseek-chat") -> str:
    """Send query to DeepSeek API and return response"""
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 1000
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        
        result = response.json()
        return result["choices"][0]["message"]["content"]
        
    except requests.exceptions.RequestException as e:
        return f"Error calling DeepSeek API: {e}"
    except KeyError as e:
        return f"Error parsing DeepSeek response: {e}"

print("RAG system components initialized!")
```

### Stage 1: Knowledge Base Creation

#### Create Qdrant Collection

```python
def setup_knowledge_base(collection_name="deepseek_knowledge"):
    """Create Qdrant collection for knowledge storage"""
    
    # Delete existing collection if it exists
    try:
        qdrant_client.delete_collection(collection_name)
    except:
        pass
    
    # Create new collection (fastembed will auto-determine vector size)
    qdrant_client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=384,  # BAAI/bge-small-en-v1.5 default
            distance=Distance.COSINE
        )
    )
    
    print(f"Created knowledge base collection: {collection_name}")
    return collection_name

# Setup knowledge base
collection_name = setup_knowledge_base()
```

#### Add Knowledge Documents

```python
def add_knowledge_documents(documents: List[Dict[str, str]], collection_name: str):
    """Add documents to the knowledge base"""
    
    points = []
    
    for i, doc in enumerate(documents):
        # Create point with text and metadata
        point = PointStruct(
            id=i,
            payload={
                "text": doc["content"],
                "title": doc.get("title", f"Document {i}"),
                "source": doc.get("source", "unknown")
            }
        )
        points.append(point)
    
    # Add documents to collection (fastembed auto-generates embeddings)
    qdrant_client.add(
        collection_name=collection_name,
        documents=[doc["content"] for doc in documents],
        metadata=[{
            "title": doc.get("title", f"Document {i}"),
            "source": doc.get("source", "unknown")
        } for i, doc in enumerate(documents)],
        ids=list(range(len(documents)))
    )
    
    print(f"Added {len(documents)} documents to knowledge base")

# Sample knowledge base documents
knowledge_documents = [
    {
        "title": "Company AI Policy",
        "content": "Our company AI policy requires all AI systems to be transparent, ethical, and aligned with company values. All AI deployments must be reviewed by the AI ethics committee before production release.",
        "source": "internal_policy"
    },
    {
        "title": "Customer Support Guidelines",
        "content": "Customer support agents should always be helpful, empathetic, and solution-focused. For technical issues, escalate to technical support team. For billing issues, transfer to billing department.",
        "source": "support_manual"
    },
    {
        "title": "Product Features - AI Assistant",
        "content": "Our AI Assistant features natural language processing, contextual understanding, and integration with company databases. It supports 15 languages and can handle complex multi-step queries.",
        "source": "product_docs"
    },
    {
        "title": "Security Protocols",
        "content": "All data must be encrypted in transit and at rest. Access to sensitive systems requires multi-factor authentication. Regular security audits are conducted quarterly.",
        "source": "security_manual"
    },
    {
        "title": "Remote Work Policy",
        "content": "Employees may work remotely up to 3 days per week. Remote workers must maintain secure internet connections and use company-approved VPN for accessing internal systems.",
        "source": "hr_policy"
    }
]

# Add documents to knowledge base
add_knowledge_documents(knowledge_documents, collection_name)
```

### Stage 2: Baseline Testing (Without RAG)

#### Test DeepSeek Without Context

```python
def test_baseline_knowledge(question: str) -> str:
    """Test DeepSeek's baseline knowledge without RAG"""
    
    print(f"🤖 Baseline DeepSeek Response (No RAG):")
    print(f"Question: {question}")
    
    response = query_deepseek(question)
    print(f"Answer: {response}")
    print("-" * 80)
    
    return response

# Test questions about our knowledge base
baseline_questions = [
    "What is our company's AI policy?",
    "How many days per week can employees work remotely?",
    "What languages does our AI Assistant support?",
    "What authentication is required for sensitive systems?"
]

print("Testing DeepSeek baseline knowledge (without RAG):")
print("=" * 80)

baseline_responses = {}
for question in baseline_questions:
    baseline_responses[question] = test_baseline_knowledge(question)
```

### Stage 3: RAG Implementation

#### Retrieve Relevant Context

```python
def retrieve_context(query: str, collection_name: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Retrieve relevant context from knowledge base"""
    
    # Search for relevant documents
    search_results = qdrant_client.query(
        collection_name=collection_name,
        query_text=query,
        limit=top_k
    )
    
    # Format results
    context_docs = []
    for result in search_results:
        context_docs.append({
            "text": result.payload["text"],
            "title": result.payload.get("title", "Unknown"),
            "source": result.payload.get("source", "unknown"),
            "score": result.score
        })
    
    return context_docs

# Test context retrieval
test_query = "What is our company's AI policy?"
context = retrieve_context(test_query, collection_name)

print(f"Retrieved context for: '{test_query}'")
for i, doc in enumerate(context, 1):
    print(f"{i}. Title: {doc['title']} (Score: {doc['score']:.3f})")
    print(f"   Content: {doc['text'][:100]}...")
    print(f"   Source: {doc['source']}")
    print()
```

#### Create RAG Prompt

```python
def create_rag_prompt(question: str, context_docs: List[Dict[str, Any]]) -> str:
    """Create enhanced prompt with retrieved context"""
    
    # Format context
    context_text = ""
    for i, doc in enumerate(context_docs, 1):
        context_text += f"Context {i} ({doc['source']}):\n"
        context_text += f"Title: {doc['title']}\n"
        context_text += f"Content: {doc['text']}\n\n"
    
    # Create RAG prompt
    rag_prompt = f"""Based on the following context information, please answer the question. Use only the information provided in the context. If the context doesn't contain enough information to answer the question, say so clearly.

CONTEXT:
{context_text}

QUESTION: {question}

ANSWER: Please provide a detailed answer based solely on the context provided above. Include relevant details and cite which context source(s) you're using."""
    
    return rag_prompt

# Test prompt creation
rag_prompt = create_rag_prompt(test_query, context)
print("Generated RAG Prompt:")
print("=" * 40)
print(rag_prompt)
print("=" * 40)
```

#### Complete RAG Pipeline

```python
def rag_query(question: str, collection_name: str, top_k: int = 3) -> Dict[str, Any]:
    """Complete RAG pipeline: retrieve + augment + generate"""
    
    print(f"🔍 RAG System Processing: '{question}'")
    print("-" * 60)
    
    # Step 1: Retrieve relevant context
    print("Step 1: Retrieving context...")
    context_docs = retrieve_context(question, collection_name, top_k)
    
    if not context_docs:
        return {
            "question": question,
            "answer": "No relevant context found in knowledge base.",
            "context": [],
            "sources": []
        }
    
    # Step 2: Create RAG prompt
    print("Step 2: Creating enhanced prompt...")
    rag_prompt = create_rag_prompt(question, context_docs)
    
    # Step 3: Generate response with DeepSeek
    print("Step 3: Generating response with DeepSeek...")
    answer = query_deepseek(rag_prompt)
    
    # Step 4: Format response
    sources = [{"title": doc["title"], "source": doc["source"]} for doc in context_docs]
    
    result = {
        "question": question,
        "answer": answer,
        "context": context_docs,
        "sources": sources,
        "rag_prompt": rag_prompt  # For debugging
    }
    
    print(f"✅ RAG Response Generated")
    print("-" * 60)
    
    return result

# Test complete RAG system
rag_result = rag_query("What is our company's AI policy?", collection_name)

print("RAG SYSTEM RESULT:")
print(f"Question: {rag_result['question']}")
print(f"Answer: {rag_result['answer']}")
print(f"Sources Used: {[s['title'] for s in rag_result['sources']]}")
```

### Stage 4: Comprehensive Testing and Comparison

#### Compare Baseline vs RAG Responses

```python
def compare_responses(questions: List[str], collection_name: str):
    """Compare baseline DeepSeek vs RAG responses"""
    
    comparisons = []
    
    for question in questions:
        print(f"\n{'='*80}")
        print(f"QUESTION: {question}")
        print(f"{'='*80}")
        
        # Get baseline response
        print("\n🤖 BASELINE DEEPSEEK (No Context):")
        baseline_answer = query_deepseek(question)
        print(baseline_answer)
        
        # Get RAG response
        print(f"\n🔍 RAG SYSTEM (With Context):")
        rag_result = rag_query(question, collection_name)
        print(rag_result["answer"])
        
        print(f"\n📚 SOURCES: {[s['title'] for s in rag_result['sources']]}")
        
        comparisons.append({
            "question": question,
            "baseline": baseline_answer,
            "rag": rag_result["answer"],
            "sources": rag_result["sources"]
        })
    
    return comparisons

# Compare responses for all test questions
test_questions = [
    "What is our company's AI policy?",
    "How many days per week can employees work remotely?", 
    "What languages does our AI Assistant support?",
    "What security measures are required for sensitive systems?",
    "What should I do if I have a billing issue?"
]

comparison_results = compare_responses(test_questions, collection_name)
```

#### Test with Out-of-Domain Questions

```python
def test_knowledge_boundaries(collection_name: str):
    """Test how system handles questions outside knowledge base"""
    
    out_of_domain_questions = [
        "What is the weather like today?",
        "How do I cook pasta?",
        "What is the capital of France?",
        "How does quantum computing work?"
    ]
    
    print("\n" + "="*60)
    print("TESTING KNOWLEDGE BOUNDARIES")
    print("="*60)
    
    for question in out_of_domain_questions:
        print(f"\nQuestion: {question}")
        
        # Test RAG system
        rag_result = rag_query(question, collection_name, top_k=2)
        print(f"RAG Answer: {rag_result['answer']}")
        print(f"Context Found: {len(rag_result['context'])} documents")
        
        if rag_result['context']:
            print(f"Best Match Score: {rag_result['context'][0]['score']:.3f}")

# Test boundary cases
test_knowledge_boundaries(collection_name)
```

### Stage 5: Advanced RAG Features

#### Confidence Scoring

```python
def enhanced_rag_query(question: str, collection_name: str, confidence_threshold: float = 0.5):
    """RAG with confidence scoring and quality checks"""
    
    # Retrieve context
    context_docs = retrieve_context(question, collection_name, top_k=5)
    
    if not context_docs:
        return {
            "answer": "No relevant information found in knowledge base.",
            "confidence": 0.0,
            "sources": []
        }
    
    # Calculate confidence based on retrieval scores
    avg_score = sum(doc["score"] for doc in context_docs) / len(context_docs)
    best_score = context_docs[0]["score"]
    
    # Combined confidence metric
    confidence = (avg_score + best_score) / 2
    
    if confidence < confidence_threshold:
        return {
            "answer": f"I found some potentially relevant information, but I'm not confident enough (confidence: {confidence:.2f}) to provide a reliable answer. Please rephrase your question or check if this information exists in the knowledge base.",
            "confidence": confidence,
            "sources": [doc["title"] for doc in context_docs[:2]]
        }
    
    # Generate high-confidence response
    rag_prompt = create_rag_prompt(question, context_docs[:3])
    answer = query_deepseek(rag_prompt)
    
    return {
        "answer": answer,
        "confidence": confidence,
        "sources": [{"title": doc["title"], "score": doc["score"]} for doc in context_docs[:3]]
    }

# Test confidence-aware RAG
confidence_questions = [
    "What is our AI policy?",  # Should be high confidence
    "What is our vacation policy?",  # Should be low confidence
    "How does our security system work?"  # Should be medium confidence
]

for question in confidence_questions:
    result = enhanced_rag_query(question, collection_name)
    print(f"\nQuestion: {question}")
    print(f"Confidence: {result['confidence']:.2f}")
    print(f"Answer: {result['answer'][:200]}...")
    print()
```

#### Context Filtering and Reranking

```python
def advanced_rag_query(question: str, collection_name: str):
    """Advanced RAG with context filtering and reranking"""
    
    # Retrieve more candidates initially
    initial_context = retrieve_context(question, collection_name, top_k=10)
    
    if not initial_context:
        return {"answer": "No relevant context found.", "sources": []}
    
    # Filter by relevance threshold
    filtered_context = [doc for doc in initial_context if doc["score"] > 0.3]
    
    if not filtered_context:
        return {"answer": "No sufficiently relevant context found.", "sources": []}
    
    # Rerank by source priority (internal policies > manuals > docs)
    source_priority = {
        "internal_policy": 3,
        "hr_policy": 3,
        "security_manual": 2,
        "support_manual": 2,
        "product_docs": 1
    }
    
    def rerank_score(doc):
        base_score = doc["score"]
        source_bonus = source_priority.get(doc["source"], 0) * 0.1
        return base_score + source_bonus
    
    reranked_context = sorted(filtered_context, key=rerank_score, reverse=True)[:3]
    
    # Generate response with reranked context
    rag_prompt = create_rag_prompt(question, reranked_context)
    answer = query_deepseek(rag_prompt)
    
    return {
        "answer": answer,
        "context_used": len(reranked_context),
        "sources": [{"title": doc["title"], "source": doc["source"], "score": doc["score"]} 
                   for doc in reranked_context]
    }

# Test advanced RAG
advanced_result = advanced_rag_query("What are our company policies?", collection_name)
print("ADVANCED RAG RESULT:")
print(f"Answer: {advanced_result['answer']}")
print(f"Contexts Used: {advanced_result['context_used']}")
print(f"Sources: {[s['title'] for s in advanced_result['sources']]}")
```

## Part 3: Mental Models & Deep Dives

### Understanding RAG Architecture

**Mental Model**: Think of RAG like a research assistant with a specialized library:

**Without RAG**: Like asking a smart person questions from memory alone
- Fast but limited to what they already know
- May give outdated or generic information
- No way to verify sources

**With RAG**: Like a research assistant with access to your specific library
- Looks up relevant documents first
- Provides answers based on current, specific information
- Can cite exact sources

### The Retrieval-Generation Pipeline

```python
# The RAG workflow visualization
user_question = "What is our AI policy?"

# Step 1: Vector search finds relevant docs
relevant_docs = vector_search(user_question, knowledge_base)
# → ["AI Policy Document", "Ethics Guidelines", "Implementation Guide"]

# Step 2: Context construction
enhanced_prompt = f"""
Based on these documents: {relevant_docs}
Question: {user_question}
Answer using only the provided context.
"""

# Step 3: LLM generates contextual response
answer = llm.generate(enhanced_prompt)
# → "According to our AI policy document, all AI systems must..."
```

### DeepSeek Integration Patterns

**API Best Practices**:
```python
def robust_deepseek_query(prompt: str, retries: int = 3):
    """Robust DeepSeek API call with error handling"""
    
    for attempt in range(retries):
        try:
            response = query_deepseek(prompt)
            return response
        except Exception as e:
            if attempt == retries - 1:
                return f"Failed to get response after {retries} attempts: {e}"
            time.sleep(2 ** attempt)  # Exponential backoff
```

### Advanced RAG Optimization

#### Chunk Size Optimization

```python
def optimize_document_chunking(documents: List[str], chunk_size: int = 512):
    """Optimize document chunking for better retrieval"""
    
    optimized_chunks = []
    
    for doc in documents:
        # Split by sentences first
        sentences = doc.split('. ')
        
        current_chunk = ""
        for sentence in sentences:
            if len(current_chunk + sentence) < chunk_size:
                current_chunk += sentence + ". "
            else:
                if current_chunk:
                    optimized_chunks.append(current_chunk.strip())
                current_chunk = sentence + ". "
        
        if current_chunk:
            optimized_chunks.append(current_chunk.strip())
    
    return optimized_chunks
```

#### Hybrid Search Strategies

```python
def hybrid_rag_search(question: str, collection_name: str):
    """Combine vector search with keyword matching"""
    
    # Vector search for semantic similarity
    vector_results = retrieve_context(question, collection_name, top_k=10)
    
    # Keyword search for exact matches
    query_words = question.lower().split()
    keyword_boost = {}
    
    for doc in vector_results:
        doc_text = doc["text"].lower()
        keyword_matches = sum(1 for word in query_words if word in doc_text)
        keyword_boost[doc["title"]] = keyword_matches / len(query_words)
    
    # Combine scores
    for doc in vector_results:
        semantic_score = doc["score"]
        keyword_score = keyword_boost.get(doc["title"], 0)
        doc["combined_score"] = semantic_score * 0.7 + keyword_score * 0.3
    
    # Re-sort by combined score
    vector_results.sort(key=lambda x: x["combined_score"], reverse=True)
    
    return vector_results[:3]
```

#### Query Expansion

```python
def expand_query(original_query: str) -> List[str]:
    """Generate related queries for better recall"""
    
    # Simple query expansion with synonyms
    expansions = {
        "policy": ["policy", "guideline", "rule", "procedure"],
        "AI": ["AI", "artificial intelligence", "machine learning", "automation"],
        "remote": ["remote", "work from home", "telecommute", "virtual"],
        "security": ["security", "protection", "safety", "authentication"]
    }
    
    expanded_queries = [original_query]
    
    for term, synonyms in expansions.items():
        if term.lower() in original_query.lower():
            for synonym in synonyms:
                if synonym != term:
                    expanded_query = original_query.replace(term, synonym)
                    expanded_queries.append(expanded_query)
    
    return expanded_queries[:3]  # Limit to avoid noise
```

### Production Considerations

#### Monitoring and Logging

```python
import logging
from datetime import datetime

def logged_rag_query(question: str, collection_name: str, user_id: str = None):
    """RAG query with comprehensive logging"""
    
    start_time = datetime.now()
    
    try:
        # Log query start
        logging.info(f"RAG Query Started - User: {user_id}, Question: {question}")
        
        # Execute RAG
        result = rag_query(question, collection_name)
        
        # Log success
        duration = (datetime.now() - start_time).total_seconds()
        logging.info(f"RAG Query Success - Duration: {duration}s, Sources: {len(result['sources'])}")
        
        return result
        
    except Exception as e:
        # Log error
        logging.error(f"RAG Query Failed - User: {user_id}, Error: {e}")
        return {"answer": "Sorry, I encountered an error processing your question.", "sources": []}
```

#### Caching Strategy

```python
import hashlib
from typing import Optional

rag_cache = {}

def cached_rag_query(question: str, collection_name: str, cache_ttl: int = 3600) -> Dict[str, Any]:
    """RAG query with result caching"""
    
    # Create cache key
    cache_key = hashlib.md5(f"{question}_{collection_name}".encode()).hexdigest()
    
    # Check cache
    if cache_key in rag_cache:
        cached_result, timestamp = rag_cache[cache_key]
        if (datetime.now().timestamp() - timestamp) < cache_ttl:
            return cached_result
    
    # Execute query and cache result
    result = rag_query(question, collection_name)
    rag_cache[cache_key] = (result, datetime.now().timestamp())
    
    return result
```

This comprehensive RAG system with DeepSeek demonstrates how to build intelligent, contextual AI applications that combine the reasoning capabilities of large language models with the precision and current knowledge of vector databases.