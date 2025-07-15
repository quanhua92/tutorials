# Intelligent Code Search: Beyond Keyword Matching in Codebases

**Source Example:** [code-search](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/code-search)

## The Core Concept: Why This Example Exists

### The Problem
Developers spend enormous amounts of time searching through codebases—looking for function implementations, understanding how APIs work, or finding examples of specific patterns. Traditional code search relies on exact keyword matching: searching for "count" only finds code with that exact word. But what if you want to find functions that "calculate the number of items" or "determine collection size"? The semantic intent is the same, but the keywords differ.

### The Solution
Code search with vector embeddings understands the *meaning* behind code structures and natural language queries. Instead of matching exact tokens, it captures semantic relationships—understanding that "count points", "calculate size", and "determine length" all express similar computational concepts. This enables developers to search codebases using natural language descriptions of what they want to accomplish.

Qdrant's philosophy for code: **Intent transcends syntax**. By storing both semantic representations (what code does) and syntactic representations (how code looks), you can build search systems that understand developer intent regardless of specific programming language constructs or naming conventions.

---

## Practical Walkthrough: Code Breakdown

### The Codebase: Qdrant's Open Source Repository

The example works with pre-processed structures from Qdrant's own source code:

```python
import json

structures = []
with open("structures.jsonl", "r") as fp:
    for row in fp:
        entry = json.loads(row)
        structures.append(entry)

# Example structure: Function, Struct, Trait, etc.
structures[0]
```

Each structure contains rich metadata:

```python
{
    'name': 'InvertedIndexRam',
    'signature': 'pub struct InvertedIndexRam { ... }',
    'code_type': 'Struct', 
    'docstring': 'Inverted flatten index from dimension id to posting list',
    'line': 15,
    'context': {
        'module': 'inverted_index',
        'file_path': 'lib/sparse/src/index/inverted_index/inverted_index_ram.rs',
        'file_name': 'inverted_index_ram.rs',
        'snippet': '/// Inverted flatten index...\npub struct InvertedIndexRam {...}'
    }
}
```

**Why this structure works:** Each code element is decomposed into semantic components (what it does), syntactic components (how it's written), and contextual components (where it lives). This multi-faceted representation enables sophisticated search strategies.

### Dual Embedding Strategy: General vs. Code-Specific

The tutorial demonstrates a crucial insight: different embedding models excel at different aspects of code understanding.

#### Strategy 1: Text Normalization for General Models

For general-purpose models like `all-MiniLM-L6-v2`, code must be converted to natural language:

```python
import inflection
import re

def textify(chunk):
    """Convert code structure to human-readable description"""
    # Transform camelCase/snake_case to readable text
    name = inflection.humanize(inflection.underscore(chunk["name"]))
    signature = inflection.humanize(inflection.underscore(chunk["signature"]))
    
    # Extract semantic meaning
    docstring = ""
    if chunk["docstring"]:
        docstring = f"that does {chunk['docstring']} "
    
    # Add contextual information
    context = f"module {chunk['context']['module']} file {chunk['context']['file_name']}"
    if chunk["context"]["struct_name"]:
        struct_name = inflection.humanize(inflection.underscore(chunk["context"]["struct_name"]))
        context = f"defined in struct {struct_name} {context}"
    
    # Combine into natural language
    text_representation = (
        f"{chunk['code_type']} {name} "
        f"{docstring}"
        f"defined as {signature} "
        f"{context}"
    )
    
    # Clean and tokenize
    tokens = re.split(r"\W", text_representation)
    tokens = filter(lambda x: x, tokens)
    return " ".join(tokens)

# Example transformation:
textify(structures[0])
# "Struct Inverted index ram that does Inverted flatten index from dimension id to posting list..."
```

**The normalization magic:** This transforms `InvertedIndexRam` into "Struct Inverted index ram that does..." - readable by models trained on natural language. The process preserves semantic meaning while making syntax accessible.

#### Strategy 2: Direct Code Processing for Specialized Models

For code-specific models like `jina-embeddings-v2-base-code`, use raw code directly:

```python
code_snippets = [
    structure["context"]["snippet"]
    for structure in structures
]

# Example raw code:
code_snippets[0]
```

```rust
/// Inverted flatten index from dimension id to posting list
#[derive(Debug, Clone, PartialEq)]
pub struct InvertedIndexRam {
    /// Posting lists for each dimension flattened (dimension id -> posting list)
    pub postings: Vec<PostingList>,
    /// Number of unique indexed vectors
    pub vector_count: usize,
}
```

**Why both approaches matter:** General models understand semantic relationships but struggle with syntax. Code-specific models handle syntax naturally but may miss broader conceptual connections. Using both provides comprehensive coverage.

### Named Vectors: Multi-Modal Code Understanding

Qdrant's named vectors feature enables storing multiple representations in a single point:

```python
from qdrant_client import QdrantClient, models

client.create_collection(
    "qdrant-sources",
    vectors_config={
        "text": models.VectorParams(
            size=384,  # all-MiniLM-L6-v2 dimensions
            distance=models.Distance.COSINE,
        ),
        "code": models.VectorParams(
            size=768,  # jina-embeddings-v2-base-code dimensions  
            distance=models.Distance.COSINE,
        ),
    }
)
```

**The multi-modal advantage:** Each code structure gets two embedding representations—one optimized for natural language understanding, another for syntactic code patterns. Search can leverage either or both depending on the query type.

### Efficient Batch Upload with Dual Embeddings

```python
import uuid

points = [
    models.PointStruct(
        id=uuid.uuid4().hex,
        vector={
            "text": models.Document(
                text=text_representation, 
                model="sentence-transformers/all-MiniLM-L6-v2"
            ),
            "code": models.Document(
                text=code_snippet, 
                model="jinaai/jina-embeddings-v2-base-code"
            ),
        },
        payload=structure  # All metadata preserved
    )
    for text_representation, code_snippet, structure in zip(
        text_representations, code_snippets, structures
    )
]

client.upload_points("qdrant-sources", points=points, batch_size=64)
```

**Performance insight:** The FastEmbed integration handles embedding generation automatically during upload. This eliminates the need to manage separate embedding pipelines and ensures consistency between text and code representations.

### Comparative Search: Understanding Model Differences

The tutorial demonstrates how different models handle the same query:

```python
query = "How do I count points in a collection?"

# Search using text-optimized embeddings
text_hits = client.query_points(
    "qdrant-sources",
    query=models.Document(text=query, model="sentence-transformers/all-MiniLM-L6-v2"),
    using="text",  # Use the 'text' named vector
    limit=5,
).points

# Search using code-optimized embeddings  
code_hits = client.query_points(
    "qdrant-sources", 
    query=models.Document(text=query, model="jinaai/jina-embeddings-v2-base-code"),
    using="code",  # Use the 'code' named vector
    limit=5,
).points
```

**Result analysis:**

**Text model results:** Finds functions with natural language descriptions like "Count Request - Counts the number of points which satisfy the given filter"

**Code model results:** Finds functions with code-specific patterns like `count_indexed_points()`, `total_point_count()`, focusing on naming conventions and structural patterns

This demonstrates that different models capture different aspects of semantic similarity in code.

### Unified Multi-Model Search

For comprehensive results, query both representations simultaneously:

```python
responses = client.query_batch_points(
    "qdrant-sources",
    requests=[
        models.QueryRequest(
            query=models.Document(text=query, model="sentence-transformers/all-MiniLM-L6-v2"),
            using="text",
            limit=5,
        ),
        models.QueryRequest(
            query=models.Document(text=query, model="jinaai/jina-embeddings-v2-base-code"),
            using="code", 
            limit=5,
        ),
    ]
)

# Combine and deduplicate results
all_results = [response.points for response in responses]
```

**The hybrid advantage:** This approach captures both semantic intent (from text model) and syntactic patterns (from code model), providing more comprehensive search results than either model alone.

### Advanced: Grouped Search for Diversity

To avoid results clustering in a single module, use Qdrant's grouping feature:

```python
results = client.query_points_groups(
    collection_name="qdrant-sources",
    using="code",
    query=models.Document(text=query, model="jinaai/jina-embeddings-v2-base-code"),
    group_by="context.module",  # Group by module name
    limit=5,      # 5 different modules
    group_size=1, # 1 result per module
)

for group in results.groups:
    for hit in group.hits:
        print(f"Module: {hit.payload['context']['module']}")
        print(f"Function: {hit.payload['signature']}")
```

**Diversity insight:** This ensures search results span different parts of the codebase rather than clustering in one area, providing broader architectural understanding.

---

## Mental Model: Thinking in Code Semantics

### The Dual-Space Architecture

Imagine code understanding as operating in two interconnected spaces:

```
Natural Language Space          Code Syntax Space
                               
"count items" ←→ "calculate size"     count() ←→ size()
      ↓              ↓                 ↓         ↓
"How many?" ←→ "determine length"    .len() ←→ .count()
                               
           ↓ Multi-Modal Bridge ↓
                               
        Combined Understanding:
     Intent + Implementation + Context
```

**The bridge insight:** Named vectors create connections between semantic intent and syntactic implementation, enabling search that understands both "what you want to do" and "how it's typically implemented."

### Why Code-Specific Models Matter

General language models understand concepts but struggle with programming patterns:

- **Language model sees:** "InvertedIndexRam" → "Inverted Index Ram" (words)
- **Code model sees:** "InvertedIndexRam" → data structure pattern, indexing concept, memory optimization

**Code models capture:**
- Naming conventions (camelCase, snake_case, Hungarian notation)
- Structural patterns (getters/setters, factory patterns, interfaces)
- Language-specific idioms (Rust ownership, Python decorators, Java generics)

### Understanding Query-Code Alignment

Different query types align better with different embedding spaces:

```
Query Type                 → Best Model        → Example Results
"How to count items?"     → Text embeddings   → Functions with descriptive docs
"find count() method"     → Code embeddings   → Actual count() implementations  
"size calculation logic"  → Both models       → Comprehensive coverage
```

This alignment guides which embedding space to search for optimal results.

### The Context Preservation Strategy

Code exists in rich hierarchical contexts:

```
File → Module → Struct/Class → Method/Function
 ↓       ↓         ↓              ↓
Context becomes part of searchable meaning
```

By including contextual information in embeddings, the system understands not just what a function does, but where it belongs in the larger system architecture.

### Design Insight: The Normalization Pipeline

The `textify()` function represents a crucial design pattern for code search:

1. **Syntactic normalization:** Convert programming conventions to natural language
2. **Semantic extraction:** Pull out docstrings and comments
3. **Context injection:** Add module, file, and structural information
4. **Token cleaning:** Remove programming-specific symbols

This pipeline bridges the gap between how code is written and how developers think about code.

### Real-World Scaling Considerations

**Large codebase deployment:**
- Parse code using Language Server Protocol (LSP) tools
- Batch process embeddings for entire repositories
- Update incrementally as code changes
- Implement relevance feedback loops

**Multi-language support:**
- Language-specific normalization functions
- Unified semantic concepts across languages
- Cross-language pattern recognition

### Further Exploration

**Try this experiment:** Search for the same concept using technical terms ("binary tree traversal") vs. natural language ("walk through tree structure"). Notice how text embeddings excel with natural language while code embeddings handle technical terminology better.

**Production enhancement:** Real systems often include git history, issue discussions, and code reviews as additional context for even richer semantic understanding.

**Performance optimization:** Use approximate search for large codebases, with exact rescoring for top candidates to balance speed and accuracy.

---

This tutorial demonstrates how semantic search can revolutionize developer productivity by enabling natural language queries over complex codebases. The dual-embedding approach captures both human intent and programming patterns, creating search experiences that feel intuitive while handling the technical complexity of modern software systems.