# Intelligent Medical RAG with DSPy: Building Trustworthy Healthcare Assistants

**Source Example:** [DSPy-medical-bot](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/DSPy-medical-bot)

## The Core Concept: Why This Example Exists

### The Problem
Medical information is critical, complex, and constantly evolving. Healthcare professionals need access to the latest research and evidence-based guidelines, but traditional search methods are inadequate for medical queries. A doctor asking "What are the latest treatments for lupus in immunocompromised patients?" needs more than keyword matching—they need semantic understanding, temporal filtering, specialty-specific results, and above all, trustworthy responses grounded in verified medical literature.

### The Solution
A medical RAG (Retrieval-Augmented Generation) system combines the precision of medical information retrieval with the natural language capabilities of modern LLMs. By integrating DSPy's structured prompting framework with Qdrant's multi-vector search capabilities, you can build systems that understand medical queries, retrieve relevant research, and provide evidence-based responses while maintaining strict guardrails to prevent harmful misinformation.

Qdrant's philosophy for medical AI: **Evidence-based responses through precise retrieval**. By storing medical literature with rich metadata and using both dense and late-interaction embeddings, you can build systems that provide accurate, contextual, and trustworthy medical information.

---

## Practical Walkthrough: Code Breakdown

### The Medical Dataset: MIRIAD for Evidence-Based Responses

The example uses the MIRIAD (Medical Information Retrieval for Intelligent Answer Generation) dataset:

```python
from datasets import load_dataset

# Load sample of medical research dataset
ds = load_dataset("mwitiderrick/miriad-1k", split="train")

# Dataset contains:
# - passage_text: Medical research excerpts
# - year: Publication year (1990-2021)
# - specialty: Medical specialization (50+ categories)
```

**Why MIRIAD matters:** This dataset contains curated medical research from peer-reviewed sources, providing the evidence-based foundation necessary for trustworthy medical AI. Each passage includes temporal and specialty metadata crucial for filtering current, relevant information.

### Dual Embedding Strategy: Dense + Late-Interaction

The system employs a sophisticated two-stage retrieval approach:

```python
from qdrant_client import models

# Generate dense embeddings for semantic similarity
dense_documents = [
    models.Document(text=doc, model="BAAI/bge-small-en")
    for doc in ds['passage_text']
]

# Generate ColBERT embeddings for precise reranking  
colbert_documents = [
    models.Document(text=doc, model="colbert-ir/colbertv2.0")
    for doc in ds['passage_text']
]
```

**The dual approach advantage:**
- **Dense embeddings (BGE):** Capture semantic meaning and medical concepts
- **ColBERT embeddings:** Provide token-level precision for medical terminology

This combination ensures both conceptual understanding and exact medical term matching.

### Multi-Vector Collection Architecture

The collection setup demonstrates advanced Qdrant capabilities for medical applications:

```python
collection_name = "medical_chat_bot"

client.create_collection(
    collection_name=collection_name,
    vectors_config={
        "dense": models.VectorParams(
            size=384, 
            distance=models.Distance.COSINE
        ),
        "colbert": models.VectorParams(
            size=128,
            distance=models.Distance.COSINE,
            multivector_config=models.MultiVectorConfig(
                comparator=models.MultiVectorComparator.MAX_SIM
            ),
            hnsw_config=models.HnswConfigDiff(m=0)  # No indexing for reranker
        )
    }
)

# Create payload indexes for fast filtering
client.create_payload_index(collection_name, "specialty", "keyword")
client.create_payload_index(collection_name, "year", "integer")
```

**Key architectural decisions:**
- **Dense vector indexing:** Enabled for fast semantic search
- **ColBERT vector storage:** Indexing disabled for reranking-only use
- **Payload indexes:** Enable rapid filtering by medical specialty and publication year

### Efficient Medical Data Upload

Medical datasets require careful batch processing due to ColBERT's high-dimensional output:

```python
BATCH_SIZE = 3  # Small batches due to ColBERT's ~1k vectors per document
points_batch = []

for i in range(len(ds['passage_text'])):
    point = models.PointStruct(
        id=i,
        vector={
            "dense": dense_documents[i],    # Single 384-dim vector
            "colbert": colbert_documents[i] # ~1000 128-dim vectors
        },
        payload={
            "passage_text": ds['passage_text'][i],
            "year": ds['year'][i],              # Critical for medical recency
            "specialty": ds['specialty'][i],    # Essential for domain filtering
        }
    )
    points_batch.append(point)

    if len(points_batch) == BATCH_SIZE:
        client.upsert(collection_name=collection_name, points=points_batch)
        points_batch = []
```

**Medical-specific considerations:** The metadata (year, specialty) is crucial for medical applications where information recency and domain expertise directly impact safety and accuracy.

### DSPy Integration: Structured Medical Reasoning

DSPy provides the framework for structured medical query processing:

```python
import dspy
from dspy_qdrant import QdrantRM

# Configure language model and retrieval
lm = dspy.LM("gpt-4", max_tokens=512, api_key=api_key)
rm = QdrantRM(
    qdrant_collection_name=collection_name,
    qdrant_client=client,
    vector_name="dense",           # Use dense vectors for initial retrieval
    document_field="passage_text", # Medical text content
    k=20                          # Retrieve 20 candidates for reranking
)

dspy.settings.configure(lm=lm, rm=rm)
```

**DSPy advantage:** The structured approach ensures consistent reasoning patterns while maintaining the flexibility to handle diverse medical queries.

### Advanced Reranking with Medical Filtering

The reranking function demonstrates sophisticated medical information retrieval:

```python
def rerank_with_colbert(query_text, min_year, max_year, specialty):
    from fastembed import TextEmbedding, LateInteractionTextEmbedding
    
    # Encode query with both embedding models
    dense_model = TextEmbedding("BAAI/bge-small-en")
    colbert_model = LateInteractionTextEmbedding("colbert-ir/colbertv2.0")
    
    dense_query = list(dense_model.embed(query_text))[0]
    colbert_query = list(colbert_model.embed(query_text))[0]
    
    # Two-stage retrieval: dense semantic search + ColBERT reranking
    results = client.query_points(
        collection_name=collection_name,
        prefetch=models.Prefetch(
            query=dense_query,
            using="dense"           # Stage 1: Semantic retrieval
        ),
        query=colbert_query,        # Stage 2: Token-level reranking
        using="colbert",
        limit=5,
        query_filter=Filter(
            must=[
                FieldCondition(key="specialty", match=MatchValue(value=specialty)),
                FieldCondition(key="year", range=models.Range(gte=min_year, lte=max_year))
            ]
        )
    )
    
    return [point.payload['passage_text'] for point in results.points]
```

**Medical filtering logic:**
- **Temporal filtering:** Ensures information recency (critical in fast-evolving medical fields)
- **Specialty filtering:** Focuses on domain-relevant expertise
- **Two-stage retrieval:** Balances recall (dense) with precision (ColBERT)

### Medical Query Signature and Guardrails

DSPy signatures define the structure of medical reasoning:

```python
class MedicalAnswer(dspy.Signature):
    question = dspy.InputField(desc="The medical question to answer")
    is_medical = dspy.OutputField(desc="Answer 'Yes' if question is medical, otherwise 'No'")
    min_year = dspy.InputField(desc="Minimum year of medical paper")
    max_year = dspy.InputField(desc="Maximum year of medical paper") 
    specialty = dspy.InputField(desc="Medical specialty of the paper")
    context = dspy.OutputField(desc="Retrieved medical context")
    final_answer = dspy.OutputField(desc="Evidence-based medical answer")

class MedicalGuardrail(dspy.Module):
    def forward(self, question):
        prompt = (
            "Is the following question a medical question? Answer with 'Yes' or 'No'.\n"
            f"Question: {question}\n"
            "Answer:"
        )
        response = dspy.settings.lm(prompt)
        return response[0].strip().lower().startswith("yes")
```

**Safety-first design:** The guardrail ensures the system only responds to medical queries, preventing inappropriate use for non-medical questions.

### Complete Medical RAG Implementation

The full system combines all components into a coherent medical assistant:

```python
class MedicalRAG(dspy.Module):
    def __init__(self):
        super().__init__()
        self.guardrail = MedicalGuardrail()
    
    def forward(self, question, min_year, max_year, specialty):
        # Safety check: Only answer medical questions
        if not self.guardrail.forward(question):
            class DummyResult:
                final_answer = "Sorry, I can only answer medical questions. Please ask a question related to medicine or healthcare."
            return DummyResult()
        
        # Retrieve relevant medical literature
        reranked_docs = rerank_with_colbert(question, min_year, max_year, specialty)
        context_str = "\n".join(reranked_docs)
        
        # Generate evidence-based response
        return dspy.ChainOfThought(MedicalAnswer)(
            question=question,
            min_year=min_year,
            max_year=max_year,
            specialty=specialty,
            context=context_str
        )
```

### Practical Medical Query Examples

The system handles diverse medical queries with appropriate specialization:

```python
# Initialize the medical RAG system
rag_chain = MedicalRAG()

# Example query: Lupus symptoms in Rheumatology
result = rag_chain.forward(
    "What are the most common symptoms of lupus?",
    min_year=1990,
    max_year=2021,
    specialty="Rheumatology"
)

print(result.reasoning)
# "The question is asking for symptoms of lupus, which falls under Rheumatology..."

print(result.final_answer)
# "The most common symptoms of lupus are fatigue, joint pain and swelling, 
#  skin rashes (particularly a butterfly-shaped rash), fever, chest pain..."
```

### Safety Validation: Non-Medical Query Handling

```python
# Test with non-medical query
non_medical_result = rag_chain.forward(
    "How is the weather today?",
    min_year=1990,
    max_year=2021,
    specialty="General Medicine"
)

print(non_medical_result.final_answer)
# "Sorry, I can only answer medical questions. Please ask a question related to medicine or healthcare."
```

---

## Mental Model: Thinking in Medical Knowledge Space

### The Medical Information Hierarchy

Medical knowledge exists in a complex hierarchy that the system must navigate:

```
Medical Knowledge Space

Temporal Dimension:
Recent Research ←→ Historical Knowledge
(2020-2024)        (1990-2010)

Specialty Dimension:
General Medicine ←→ Specialized Domains
                   (Cardiology, Neurology, etc.)

Evidence Dimension:
Research Papers ←→ Clinical Guidelines ←→ Case Studies
```

**The navigation challenge:** Medical queries require finding the intersection of temporal relevance, specialty expertise, and evidence quality.

### Understanding Multi-Vector Medical Search

The dual embedding approach captures different aspects of medical understanding:

```
Dense Embeddings (BGE):           ColBERT Embeddings:
Semantic Concepts                 Precise Medical Terms
                                 
"cardiac arrest" ←→ "heart failure"    "myocardial infarction" ≠ "cardiac arrest"
"diabetes" ←→ "hyperglycemia"          "Type 1" ≠ "Type 2"
"inflammation" ←→ "immune response"     "mg/dL" ≠ "mmol/L"
```

**The precision balance:** Dense embeddings ensure conceptual coverage while ColBERT embeddings provide the precision necessary for medical accuracy.

### DSPy's Structured Reasoning for Medical Queries

Traditional RAG lacks the structured thinking necessary for medical applications:

```
Traditional RAG:              DSPy Medical RAG:
Query → Retrieve → Generate   Query → Guardrail → Classify → Filter → Retrieve → Rerank → Reason → Generate
```

**The structured advantage:** Each step includes medical-specific logic, ensuring responses meet healthcare standards for accuracy and safety.

### Understanding Medical Filtering Logic

Temporal and specialty filtering are crucial for medical accuracy:

```
Query: "Latest treatment for Type 2 diabetes"

Without Filtering:           With Medical Filtering:
- Historical treatments      → Recent guidelines (2020-2024)
- General medicine          → Endocrinology specialty  
- Outdated protocols        → Current evidence-based care
```

**Why filtering matters:** Medical practice evolves rapidly. Outdated information can be dangerous, making temporal and specialty filtering essential for safety.

### The Guardrail Pattern for Medical AI

Medical AI systems require multiple safety layers:

```
Safety Architecture:
1. Input Validation: Is this a medical question?
2. Domain Filtering: Is this within scope?
3. Evidence Grounding: Is the response supported by retrieved literature?
4. Uncertainty Handling: When should the system decline to answer?
```

**Safety-first principle:** Medical AI should err on the side of caution, declining to answer when confidence is low or when queries fall outside medical domains.

### Real-World Medical AI Considerations

**Regulatory compliance:**
- HIPAA privacy requirements
- FDA guidance for AI/ML medical devices
- International medical AI standards

**Clinical integration:**
- EHR system compatibility
- Clinical decision support frameworks
- Provider workflow integration

**Quality assurance:**
- Medical expert validation
- Bias detection and mitigation
- Continuous performance monitoring

### Further Exploration

**Try this experiment:** Query the same medical condition using different specialties (e.g., lupus from Rheumatology vs. Dermatology perspectives). Notice how specialty filtering affects the type of evidence retrieved.

**Advanced features:** Production medical AI systems often include citation tracking, confidence scoring, and integration with medical ontologies (SNOMED, ICD-10) for enhanced precision.

**Ethical considerations:** Medical AI systems must handle uncertainty gracefully, provide appropriate disclaimers, and maintain clear boundaries between information provision and medical advice.

---

This tutorial demonstrates how to build responsible medical AI systems that combine the power of modern RAG techniques with the safety and precision required for healthcare applications. The integration of DSPy's structured reasoning with Qdrant's multi-vector capabilities creates a foundation for trustworthy medical AI assistants that can support healthcare professionals with evidence-based information while maintaining strict safety guardrails.