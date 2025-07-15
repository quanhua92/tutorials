# Extractive Question Answering

> **Source**: [extractive_qa](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/extractive_qa)

This tutorial demonstrates how to build a complete extractive question answering system using a Retriever-Reader architecture with Qdrant for semantic search and transformer models for precise answer extraction.

## Part 1: Core Concept - Why Extractive QA Matters

### The Information Retrieval Problem

Modern applications handle massive amounts of textual data - documents, articles, support tickets, knowledge bases. Users need quick, precise answers to specific questions buried within this content:

- **Information overload**: Too much content to manually search through
- **Keyword limitations**: Traditional search misses semantically relevant content
- **Context requirements**: Answers need surrounding context to be meaningful
- **Precision demands**: Users want exact answers, not entire documents

### The Extractive QA Solution

Extractive Question Answering solves this by finding the exact text span that answers a question within a larger corpus. Unlike generative approaches that create new text, extractive QA:

- **Preserves accuracy**: Returns exact text from source documents
- **Maintains attribution**: You know exactly where the answer came from
- **Ensures reliability**: No hallucination or fabricated information
- **Provides context**: Returns surrounding text for verification

**What you'll build**: A two-stage system where a fast retriever finds relevant documents using vector search, and a precise reader extracts the exact answer span from those documents.

### Real-World Applications

- **Customer Support**: Find exact answers from documentation
- **Legal Research**: Extract specific clauses from legal documents
- **Medical Information**: Find precise medical facts from research papers
- **Educational Platforms**: Answer student questions from course materials

## Part 2: Practical Walkthrough - Building the QA System

### Understanding the Retriever-Reader Architecture

The system uses a two-stage approach optimized for both speed and accuracy:

```
Question → [Retriever] → Relevant Documents → [Reader] → Exact Answer
```

**Stage 1 - Retriever**: Fast semantic search to find potentially relevant documents
**Stage 2 - Reader**: Deep analysis to extract the precise answer span

### Setup and Dependencies

```python
# Core dependencies for extractive QA
!pip install qdrant-client transformers datasets torch fastembed

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from transformers import AutoTokenizer, AutoModelForQuestionAnswering, pipeline
from datasets import load_dataset
from fastembed import TextEmbedding
import torch
```

**Key components:**
- `qdrant-client`: Vector database for semantic retrieval
- `transformers`: BERT-based reader model for answer extraction
- `fastembed`: Efficient embedding generation for retrieval
- `datasets`: Access to question-answering datasets

### Initialize Core Services

```python
# Initialize Qdrant client (in-memory for tutorial)
qdrant_client = QdrantClient(":memory:")

# Initialize retriever model for semantic search
retriever_model = TextEmbedding("BAAI/bge-small-en-v1.5")
embedding_size = 384  # BGE-small embedding dimension

# Initialize reader model for answer extraction
qa_pipeline = pipeline(
    "question-answering",
    model="bert-large-uncased-whole-word-masking-finetuned-squad",
    tokenizer="bert-large-uncased-whole-word-masking-finetuned-squad"
)

print("Models loaded successfully!")
```

**Model selection rationale:**
- **BGE-small**: Fast, efficient embeddings for retrieval stage
- **BERT-large SQUAD**: High accuracy for answer extraction stage

### Stage 1: Document Corpus Preparation

#### Load and Explore Dataset

```python
# Load movie plots dataset for QA
dataset = load_dataset("duorc", "SelfRC", split="train[:1000]")

print(f"Dataset size: {len(dataset)}")
print(f"Sample entry: {dataset[0]}")

# Extract plots (contexts) and titles
documents = []
for item in dataset:
    if item['plot'] and len(item['plot'].strip()) > 50:  # Filter short plots
        documents.append({
            'text': item['plot'].strip(),
            'title': item['title'],
            'id': len(documents)
        })

print(f"Processed {len(documents)} movie plots")
```

#### Create Qdrant Collection

```python
# Create collection for document embeddings
collection_name = "movie_plots"

qdrant_client.create_collection(
    collection_name=collection_name,
    vectors_config=VectorParams(
        size=embedding_size,
        distance=Distance.COSINE
    )
)

print(f"Created collection '{collection_name}'")
```

#### Generate Embeddings and Index Documents

```python
def index_documents(documents, batch_size=32):
    """Index documents with embeddings in Qdrant"""
    
    points = []
    texts_to_embed = [doc['text'] for doc in documents]
    
    print("Generating embeddings...")
    # Generate embeddings in batches for efficiency
    embeddings = list(retriever_model.embed(texts_to_embed))
    
    print("Creating points for indexing...")
    for doc, embedding in zip(documents, embeddings):
        point = PointStruct(
            id=doc['id'],
            vector=embedding.tolist(),
            payload={
                "text": doc['text'],
                "title": doc['title']
            }
        )
        points.append(point)
        
        # Upload batch when ready
        if len(points) >= batch_size:
            qdrant_client.upsert(
                collection_name=collection_name,
                points=points
            )
            points = []
            print(f"Indexed {len(embeddings)} documents...")
    
    # Upload remaining points
    if points:
        qdrant_client.upsert(
            collection_name=collection_name,
            points=points
        )
    
    print(f"Successfully indexed {len(documents)} documents")

# Index all documents
index_documents(documents)
```

### Stage 2: Retrieval Implementation

#### Semantic Document Retrieval

```python
def retrieve_relevant_contexts(question, top_k=5):
    """Retrieve most relevant documents for a question"""
    
    # Generate embedding for question
    question_embedding = list(retriever_model.embed([question]))[0]
    
    # Search for similar documents
    search_results = qdrant_client.search(
        collection_name=collection_name,
        query_vector=question_embedding.tolist(),
        limit=top_k
    )
    
    # Extract contexts with metadata
    contexts = []
    for result in search_results:
        contexts.append({
            'text': result.payload['text'],
            'title': result.payload['title'],
            'score': result.score,
            'id': result.id
        })
    
    return contexts

# Test retrieval
question = "Who directed the movie about a robot?"
relevant_contexts = retrieve_relevant_contexts(question, top_k=3)

print("Retrieved contexts:")
for i, context in enumerate(relevant_contexts, 1):
    print(f"{i}. {context['title']} (Score: {context['score']:.3f})")
    print(f"   Text: {context['text'][:200]}...")
    print()
```

### Stage 3: Answer Extraction Implementation

#### Reader Model for Precise Extraction

```python
def extract_answer(question, contexts, max_contexts=3):
    """Extract answer from retrieved contexts using reader model"""
    
    best_answer = None
    best_confidence = 0
    source_context = None
    
    # Try each context until we find a confident answer
    for i, context in enumerate(contexts[:max_contexts]):
        try:
            # Use QA pipeline to extract answer
            result = qa_pipeline(
                question=question,
                context=context['text']
            )
            
            # Check confidence threshold
            if result['score'] > best_confidence and result['score'] > 0.1:
                best_confidence = result['score']
                best_answer = result['answer']
                source_context = {
                    'title': context['title'],
                    'text': context['text'],
                    'retrieval_score': context['score']
                }
                
        except Exception as e:
            print(f"Error processing context {i}: {e}")
            continue
    
    return {
        'answer': best_answer,
        'confidence': best_confidence,
        'source': source_context
    }

# Test answer extraction
answer_result = extract_answer(question, relevant_contexts)

if answer_result['answer']:
    print(f"Question: {question}")
    print(f"Answer: {answer_result['answer']}")
    print(f"Confidence: {answer_result['confidence']:.3f}")
    print(f"Source: {answer_result['source']['title']}")
else:
    print("No confident answer found")
```

### Stage 4: Complete QA System

#### End-to-End Question Answering

```python
def answer_question(question, top_k=5, min_confidence=0.1):
    """Complete QA pipeline: retrieve + extract"""
    
    print(f"Question: {question}")
    print("=" * 50)
    
    # Stage 1: Retrieve relevant contexts
    print("🔍 Retrieving relevant documents...")
    contexts = retrieve_relevant_contexts(question, top_k=top_k)
    
    if not contexts:
        return {"error": "No relevant documents found"}
    
    print(f"Found {len(contexts)} relevant contexts")
    
    # Stage 2: Extract answer
    print("📖 Extracting answer...")
    answer_result = extract_answer(question, contexts)
    
    if not answer_result['answer'] or answer_result['confidence'] < min_confidence:
        return {
            "answer": "No confident answer found",
            "confidence": 0,
            "retrieved_contexts": [ctx['title'] for ctx in contexts[:3]]
        }
    
    # Format response
    response = {
        "answer": answer_result['answer'],
        "confidence": answer_result['confidence'],
        "source_title": answer_result['source']['title'],
        "context_snippet": answer_result['source']['text'][:300] + "...",
        "retrieval_score": answer_result['source']['retrieval_score']
    }
    
    return response

# Test complete system
test_questions = [
    "Who directed the movie about a robot?",
    "What is the name of the space station?",
    "Who plays the main character in the thriller?",
    "What year did the adventure take place?"
]

for question in test_questions:
    result = answer_question(question)
    
    if "error" not in result and result['confidence'] > 0:
        print(f"❓ Question: {question}")
        print(f"✅ Answer: {result['answer']}")
        print(f"📊 Confidence: {result['confidence']:.3f}")
        print(f"📚 Source: {result['source_title']}")
        print(f"🎯 Context: {result['context_snippet']}")
    else:
        print(f"❓ Question: {question}")
        print(f"❌ No confident answer found")
    
    print("-" * 80)
```

#### Advanced QA with Context Ranking

```python
def advanced_answer_question(question, top_k=10, rerank_contexts=True):
    """Enhanced QA with context reranking"""
    
    # Retrieve more contexts initially
    contexts = retrieve_relevant_contexts(question, top_k=top_k)
    
    if rerank_contexts:
        # Rerank contexts based on question-context similarity
        reranked_contexts = rerank_by_question_similarity(question, contexts)
        contexts = reranked_contexts
    
    # Try multiple contexts and aggregate confidence
    all_answers = []
    
    for context in contexts[:5]:  # Test top 5 contexts
        try:
            result = qa_pipeline(question=question, context=context['text'])
            if result['score'] > 0.05:  # Lower threshold for collection
                all_answers.append({
                    'answer': result['answer'],
                    'confidence': result['score'],
                    'context': context,
                    'combined_score': result['score'] * context['score']  # Combine scores
                })
        except:
            continue
    
    if not all_answers:
        return {"answer": "No answer found", "confidence": 0}
    
    # Sort by combined score
    all_answers.sort(key=lambda x: x['combined_score'], reverse=True)
    best_answer = all_answers[0]
    
    return {
        'answer': best_answer['answer'],
        'confidence': best_answer['confidence'],
        'source': best_answer['context']['title'],
        'alternative_answers': [ans['answer'] for ans in all_answers[1:3]]
    }

def rerank_by_question_similarity(question, contexts):
    """Rerank contexts by semantic similarity to question"""
    
    # Generate question embedding
    question_embedding = list(retriever_model.embed([question]))[0]
    
    # Calculate similarity with each context
    for context in contexts:
        context_embedding = list(retriever_model.embed([context['text']]))[0]
        
        # Calculate cosine similarity
        similarity = torch.cosine_similarity(
            torch.tensor(question_embedding).unsqueeze(0),
            torch.tensor(context_embedding).unsqueeze(0)
        ).item()
        
        context['question_similarity'] = similarity
        context['reranked_score'] = context['score'] * similarity
    
    # Sort by reranked score
    return sorted(contexts, key=lambda x: x['reranked_score'], reverse=True)
```

## Part 3: Mental Models & Deep Dives

### Understanding the Two-Stage Architecture

**Mental Model**: Think of the system like a library with a librarian and a researcher.

**Stage 1 - The Librarian (Retriever)**:
- Quickly scans the entire library catalog
- Finds books that might contain relevant information
- Fast but broad - prioritizes recall over precision
- Uses semantic understanding: "robot movie" might find "android film"

**Stage 2 - The Researcher (Reader)**:
- Carefully reads through the selected books
- Finds the exact sentence that answers the question
- Slow but precise - prioritizes precision over speed
- Deep contextual understanding of language

### Vector Search Mental Model

**Embedding Space Visualization**:
```python
# Similar concepts cluster together in vector space
"Who directed Terminator?" → [0.2, 0.8, 0.1, ...]
"Terminator movie plot"    → [0.3, 0.7, 0.2, ...]  # Close vectors
"Recipe for cookies"       → [0.9, 0.1, 0.8, ...]  # Distant vectors
```

**Why cosine similarity works**:
- Measures angle between vectors, not magnitude
- Captures semantic relationship regardless of text length
- Normalizes for document length differences

### Answer Extraction Mental Model

**Think of BERT like a reading comprehension expert**:
- Reads the question and context simultaneously
- Identifies potential answer spans within the text
- Assigns confidence scores based on linguistic patterns
- Trained on thousands of question-answer pairs

**Confidence score interpretation**:
```python
# Confidence levels guide system decisions
score > 0.8  # Very confident - directly return answer
score > 0.5  # Confident - return with high confidence
score > 0.2  # Uncertain - return with warning
score < 0.2  # Not confident - try alternative contexts
```

### Optimizing the QA Pipeline

#### Retrieval Optimization Strategies

**Embedding model selection**:
```python
# Different models for different needs
models = {
    "speed": "all-MiniLM-L6-v2",        # Fast, smaller embeddings
    "quality": "BAAI/bge-large-en-v1.5", # Better semantic understanding
    "multilingual": "paraphrase-multilingual-MiniLM-L12-v2"
}
```

**Query expansion techniques**:
```python
def expand_query(question):
    """Enhance question with related terms"""
    # Add synonyms, related terms, alternative phrasings
    expansions = {
        "directed": ["made", "created", "filmed"],
        "movie": ["film", "picture", "cinema"],
        "robot": ["android", "cyborg", "machine"]
    }
    
    expanded_question = question
    for term, synonyms in expansions.items():
        if term in question.lower():
            expanded_question += " " + " ".join(synonyms)
    
    return expanded_question
```

#### Reader Model Optimization

**Context window management**:
```python
def split_long_context(context, max_length=512, overlap=50):
    """Split long documents into manageable chunks"""
    
    words = context.split()
    chunks = []
    
    for i in range(0, len(words), max_length - overlap):
        chunk = " ".join(words[i:i + max_length])
        chunks.append(chunk)
    
    return chunks

def process_long_document(question, long_context):
    """Handle documents longer than model's context window"""
    
    chunks = split_long_context(long_context)
    best_answer = None
    best_score = 0
    
    for chunk in chunks:
        result = qa_pipeline(question=question, context=chunk)
        if result['score'] > best_score:
            best_score = result['score']
            best_answer = result
    
    return best_answer
```

### Advanced Techniques

#### Multi-hop Question Answering

```python
def multi_hop_qa(question):
    """Handle questions requiring multiple reasoning steps"""
    
    # Example: "What year was the director of Titanic born?"
    # Step 1: Find who directed Titanic
    # Step 2: Find when that person was born
    
    # Decompose complex question
    sub_questions = decompose_question(question)
    
    intermediate_answers = []
    for sub_q in sub_questions:
        answer = answer_question(sub_q)
        intermediate_answers.append(answer)
    
    # Synthesize final answer
    final_answer = synthesize_answer(question, intermediate_answers)
    return final_answer
```

#### Answer Validation and Verification

```python
def validate_answer(question, answer, context):
    """Verify answer quality and relevance"""
    
    validations = {
        'length_check': len(answer.split()) < 20,  # Reasonable length
        'context_presence': answer.lower() in context.lower(),  # Actually in text
        'question_relevance': check_relevance(question, answer),
        'entity_consistency': validate_entities(answer, context)
    }
    
    confidence_adjustment = sum(validations.values()) / len(validations)
    return confidence_adjustment

def check_relevance(question, answer):
    """Check if answer type matches question type"""
    
    question_types = {
        'who': ['person', 'organization', 'character'],
        'when': ['date', 'time', 'year'],
        'where': ['location', 'place', 'country'],
        'what': ['thing', 'concept', 'object'],
        'how': ['method', 'process', 'manner']
    }
    
    question_word = question.lower().split()[0]
    expected_types = question_types.get(question_word, [])
    
    # Use NER or other techniques to check answer type
    answer_type = detect_entity_type(answer)
    
    return answer_type in expected_types
```

### Performance Monitoring and Improvement

#### Quality Metrics

```python
def evaluate_qa_system(test_questions_answers):
    """Evaluate system performance"""
    
    metrics = {
        'exact_match': 0,
        'partial_match': 0,
        'no_answer': 0,
        'avg_confidence': 0,
        'avg_retrieval_time': 0,
        'avg_extraction_time': 0
    }
    
    for qa_pair in test_questions_answers:
        question = qa_pair['question']
        expected = qa_pair['answer']
        
        start_time = time.time()
        result = answer_question(question)
        total_time = time.time() - start_time
        
        # Calculate metrics
        if result['answer'].lower() == expected.lower():
            metrics['exact_match'] += 1
        elif expected.lower() in result['answer'].lower():
            metrics['partial_match'] += 1
        
        metrics['avg_confidence'] += result['confidence']
        metrics['avg_retrieval_time'] += total_time
    
    # Normalize metrics
    for key in metrics:
        if 'avg_' in key:
            metrics[key] /= len(test_questions_answers)
    
    return metrics
```

#### Continuous Improvement Strategies

**Active learning for improvement**:
```python
def identify_improvement_opportunities():
    """Find questions where system performs poorly"""
    
    low_confidence_questions = []
    no_answer_questions = []
    
    # Analyze query logs
    for question in recent_questions:
        result = answer_question(question)
        
        if result['confidence'] < 0.3:
            low_confidence_questions.append(question)
        
        if not result['answer']:
            no_answer_questions.append(question)
    
    return {
        'need_more_data': no_answer_questions,
        'need_better_retrieval': low_confidence_questions
    }
```

This comprehensive extractive QA system demonstrates how combining semantic search with precise answer extraction creates powerful, accurate question-answering capabilities for any domain-specific corpus.