# Semantic Search with Text Data: From Words to Vectors

**Source Example:** [qdrant_101_text_data](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/qdrant_101_text_data)

## The Core Concept: Why This Example Exists

### The Problem
Traditional search relies on exact keyword matching. If you search for "electric vehicle technology," you might miss relevant articles about "EV innovations" or "battery-powered automobiles." Human language is rich with synonyms, contexts, and implicit meanings that keyword-based systems cannot capture. How do you build search that understands *meaning* rather than just matching words?

### The Solution
Text embeddings transform human language into mathematical vectors that capture semantic meaning. Words and phrases with similar meanings end up close together in high-dimensional space. When you search for "electric vehicle," the system understands that "EV," "Tesla," and "battery car" are semantically related and includes them in results.

Qdrant's philosophy for text: **Meaning transcends syntax**. By storing semantic representations rather than just text strings, you can build search that works like human understanding—finding relevant content even when the exact words differ.

---

## Practical Walkthrough: Code Breakdown

### Loading and Exploring the AG News Dataset

The example begins with a real-world news dataset from Hugging Face:

```python
from datasets import load_dataset

dataset = load_dataset("ag_news", split="train")
# Dataset with 120,000 news articles across 4 categories:
# World, Sports, Business, Sci/Tech
```

**Why this dataset matters:** News articles are perfect for semantic search because they contain rich contextual information. Articles about the same topic use different vocabulary, making keyword search insufficient.

Let's examine the data distribution:

```python
# Visualize category balance
id2label = {str(i): label for i, label in enumerate(dataset.features["label"].names)}
dataset.select_columns('label')
       .to_pandas()
       .astype(str)['label']
       .map(id2label)
       .value_counts()
       .plot(kind="barh")
```

**Key insight:** The dataset is well-balanced across categories, which means our semantic search won't be biased toward any particular topic type.

### Creating Text Embeddings with GPT-2

The heart of semantic search is transforming text into vectors that capture meaning:

```python
from transformers import AutoModel, AutoTokenizer
import torch

# Load pre-trained GPT-2 for embeddings
tokenizer = AutoTokenizer.from_pretrained('gpt2')
model = AutoModel.from_pretrained('gpt2')

# Set padding token (GPT-2 doesn't have one by default)
tokenizer.pad_token = tokenizer.eos_token
```

**Why GPT-2?** While newer models exist, GPT-2 demonstrates the core concepts clearly. It's been trained on vast amounts of internet text, so it understands contextual relationships between words.

### Understanding Tokenization and Attention

```python
text = "What does a cow use to do math? A cow-culator."
inputs = tokenizer(text, padding=True, truncation=True, max_length=128, return_tensors="pt")

# View the tokenized result
toks = tokenizer.convert_ids_to_tokens(inputs.input_ids[0])
# ['What', 'Ġdoes', 'Ġa', 'Ġcow', 'Ġuse', 'Ġto', 'Ġdo', 'Ġmath', '?', ...]
```

**What's happening:** The tokenizer breaks text into subword pieces that the model can understand. The "Ġ" prefix indicates spaces in the original text. This subword approach allows the model to handle any word, even ones it hasn't seen before.

### From Multiple Token Vectors to Single Document Embedding

GPT-2 outputs one vector per token, but we need one vector per document:

```python
def mean_pooling(model_output, attention_mask):
    token_embeddings = model_output[0]
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
    sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
    return sum_embeddings / sum_mask

# Convert multiple token vectors to single document vector
with torch.no_grad():
    model_output = model(**inputs)
    
embedding = mean_pooling(model_output, inputs["attention_mask"])
# Shape: [1, 768] - one 768-dimensional vector per document
```

**The magic of mean pooling:** We're taking the average of all token embeddings, weighted by the attention mask. This creates a single vector that represents the entire document's meaning.

### Batch Processing for Efficiency

```python
def embed_text(examples):
    inputs = tokenizer(
        examples["text"], 
        padding=True, 
        truncation=True, 
        return_tensors="pt"
    )
    with torch.no_grad():
        model_output = model(**inputs)
    pooled_embeds = mean_pooling(model_output, inputs["attention_mask"])
    return {"embedding": pooled_embeds.cpu().numpy()}

# Process 1000 articles in batches
small_set = (
    dataset.shuffle(42)
           .select(range(1000))
           .map(embed_text, batched=True, batch_size=128)
)
```

**Efficiency insight:** Processing in batches leverages GPU parallelization and is much faster than one-by-one processing. The shuffle ensures we get a representative sample across categories.

### Building the Semantic Search Index

```python
from qdrant_client import QdrantClient
from qdrant_client import models

client = QdrantClient(location=":memory:")  # In-memory for this demo

# Create collection for 768-dimensional vectors
my_collection = "news_embeddings"
client.recreate_collection(
    collection_name=my_collection,
    vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE)
)

# Prepare metadata payloads
payloads = small_set.select_columns(["label_names", "text"]).to_pandas().to_dict(orient="records")

# Upload vectors with metadata
client.upsert(
    collection_name=my_collection,
    points=models.Batch(
        ids=small_set["idx"],
        vectors=small_set["embedding"],
        payloads=payloads
    )
)
```

**Critical design choice:** Cosine similarity works perfectly for text embeddings because it measures the angle between vectors, not their magnitude. Two articles about the same topic will have similar "directions" in embedding space.

### Semantic Search in Action

```python
# Find articles similar to a random news piece
query_article = dataset[choice(range(len(dataset)))]['text']
query_vector = embed_text({"text": query_article})['embedding'][0, :]

# Search for semantic similarity
results = client.search(
    collection_name=my_collection,
    query_vector=query_vector.tolist(),
    limit=5
)
```

**What makes this "semantic":** Even if the query article uses completely different words than the results, the embeddings capture underlying meaning. An article about "electric cars" might match with "Tesla production" or "battery technology."

### Advanced: Filtered Semantic Search

```python
# Only find Business articles semantically similar to our query
business_filter = models.Filter(
    must=[models.FieldCondition(key="label_names", match=models.MatchValue(value="Business"))]
)

business_results = client.search(
    collection_name=my_collection,
    query_vector=query_vector.tolist(),
    query_filter=business_filter,
    limit=5
)
```

**Powerful combination:** You get the best of both worlds—semantic understanding of content similarity AND structured filtering by metadata. This is impossible with traditional keyword search.

### Content-Based Recommendations

```python
# Recommend articles similar to liked ones, avoiding disliked content
recommendations = client.recommend(
    collection_name=my_collection,
    positive=[article_we_liked_id, another_liked_id],  # Pull toward these
    negative=[article_we_disliked_id],                 # Push away from this
    score_threshold=0.30,                              # Only high-quality matches
    limit=8
)
```

**The recommendation magic:** Qdrant finds the "center of gravity" of your positive examples and moves away from negative examples. This creates personalized content discovery based on semantic similarity.

---

## Mental Model: Thinking in Semantic Space

### The Text Embedding Landscape

Imagine a vast 768-dimensional landscape where every news article is a point. Articles about similar topics cluster together:

```
         Tech News Cluster
              •  •  •
           •        •
        •            •
  
   Sports Cluster        Business Cluster
     •  •  •               •  •  •
    •    •                •    •
   •                     •

              World News Cluster
                •  •  •  •
               •        •
              •          •
```

**Distance = Semantic Similarity:** Articles that are close in this space discuss similar topics, even if they use completely different words.

### Why Cosine Similarity Works for Text

Traditional Euclidean distance measures physical distance, but cosine similarity measures the *angle* between vectors:

- **"Tesla announces new battery"** → Vector pointing toward "tech/automotive"
- **"Electric vehicle breakthrough"** → Vector pointing in similar direction
- **"Recipe for chocolate cake"** → Vector pointing completely different direction

Even if one article is longer (higher magnitude), the directions are similar, so cosine similarity correctly identifies them as related.

### The Power of Mean Pooling

When you read a document, you don't remember every single word—you extract the overall meaning. Mean pooling does the same thing mathematically:

1. **Each token** contributes its understanding to the whole
2. **Attention weights** ensure important words have more influence  
3. **The average** represents the document's core semantic content

This is why a 1000-word article becomes a single 768-dimensional vector that captures its essence.

### Design Insight: Why Pre-trained Models Work

GPT-2 wasn't trained specifically for news similarity, yet it works excellently. Why?

**Language understanding transfers:** The model learned that "automobile," "car," and "vehicle" are semantically related from general internet text. This knowledge automatically applies to news articles without any additional training.

**Rich context awareness:** The transformer architecture captures relationships between words across the entire document, not just adjacent words.

### Further Exploration

**Try this experiment:** Take two articles about the same news event from different sources. Generate embeddings for both and calculate their cosine similarity. You'll find they're very close in embedding space despite using different journalistic styles and vocabulary.

**Real-world extension:** Modern systems often use specialized embedding models like Sentence-BERT or domain-specific models fine-tuned on news data. The principles remain the same, but performance improves dramatically.

**Performance consideration:** The example uses in-memory storage, but production systems would use persistent Qdrant instances with millions of articles, advanced indexing (HNSW), and potentially quantization for memory efficiency.

---

This tutorial demonstrates how mathematical representations of text can capture human-like understanding of meaning, enabling search and recommendation systems that work like we think—finding relevant content based on concepts and context rather than just keyword matching.