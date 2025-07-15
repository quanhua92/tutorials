# Visual Similarity Search for Medical Diagnosis: When Pixels Hold Meaning

**Source Example:** [qdrant_101_image_data](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/qdrant_101_image_data)

## The Core Concept: Why This Example Exists

### The Problem
Medical diagnosis often relies on visual pattern recognition. A dermatologist examining a skin lesion draws upon years of experience seeing thousands of similar cases. But what happens when they encounter a rare condition, or need to compare their current patient with similar cases in medical literature? Traditional medical databases organize by text metadata (patient age, gender, location), but can't search by what the condition actually *looks like*.

### The Solution
Computer vision embeddings translate visual information into mathematical representations that capture what images *look like* rather than just what their metadata says. Two skin lesions with similar visual characteristics will have similar embeddings, even if they affect patients of different ages or appear on different body parts. This enables visual similarity search that mimics how doctors actually think—recognizing patterns in appearance.

Qdrant's philosophy for images: **Visual similarity transcends categorical boundaries**. By storing mathematical representations of visual content, medical professionals can find diagnostically relevant cases based on actual appearance rather than just structured data fields.

---

## Practical Walkthrough: Code Breakdown

### The Medical Dataset: Skin Cancer Classification

The example uses a curated medical dataset from Hugging Face:

```python
from datasets import load_dataset

dataset = load_dataset("marmal88/skin_cancer", split='train')
# 9,577 dermatoscopic images with clinical metadata:
# - image: 600x450 PIL images
# - dx: diagnosis (melanoma, melanocytic_nevi, basal_cell_carcinoma, etc.)
# - age, sex, localization: patient demographics
# - dx_type: diagnostic method (histo, consensus, follow_up, confocal)
```

**Why this dataset matters:** Each image represents a real medical case with expert diagnosis. The diversity of conditions (7 different skin cancer types) and rich metadata (age, gender, body location) makes it perfect for demonstrating how visual similarity can augment traditional medical data organization.

### Vision Transformers: Teaching Machines to See

The tutorial uses Facebook's DINO (self-DIstillation with NO labels) Vision Transformer:

```python
from transformers import ViTImageProcessor, ViTModel

# Load pre-trained vision transformer
processor = ViTImageProcessor.from_pretrained('facebook/dino-vits16')
model = ViTModel.from_pretrained('facebook/dino-vits16')

# Process a medical image
inputs = processor(images=image, return_tensors="pt")
# Result: tensor of shape [1, 3, 224, 224] - batch, RGB channels, height, width
```

**DINO's advantage:** Unlike supervised models trained on specific categories, DINO learns visual representations through self-supervision. It discovers visual patterns without being told what to look for, making it excellent for medical imagery where subtle visual differences matter more than obvious categorical distinctions.

### Understanding Vision Transformer Processing

```python
# Extract image embeddings
outputs = model(**inputs).last_hidden_state
# Shape: [batch_size, patches, dimensions] = [1, 197, 384]

# Each image is divided into 14x14 = 196 patches, plus 1 classification token
# 384 dimensions capture rich visual features for each patch
```

**The patch-based approach:** Vision Transformers break images into small patches (like jigsaw pieces), analyze each patch individually, then combine insights. For medical images, this means the model can focus on specific regions (the lesion boundary, color variations, texture patterns) while understanding the overall context.

### Temporal Aggregation: From Patches to Diagnosis

```python
def get_embeddings(batch):
    inputs = processor(images=batch['image'], return_tensors="pt")
    with torch.no_grad():
        # Mean pooling across patches to get single vector per image
        outputs = model(**inputs).last_hidden_state.mean(dim=1).cpu().numpy()
    batch['embeddings'] = outputs
    return batch

# Apply to entire dataset
dataset = dataset.map(get_embeddings, batched=True, batch_size=16)
```

**Why mean pooling works:** Medical diagnosis requires understanding the overall visual impression, not just individual patch details. Mean pooling creates a "summary embedding" that captures the essential visual characteristics while being manageable for similarity search.

### Creating the Medical Search Index

```python
from qdrant_client import QdrantClient
from qdrant_client import models

client = QdrantClient(host="localhost", port=6333)

# Create collection for 384-dimensional DINO embeddings
client.recreate_collection(
    collection_name="image_collection",
    vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE)
)

# Prepare clinical metadata
payload = dataset.select_columns([
    "image_id", 'dx', 'dx_type', 'age', 'sex', 'localization'
]).to_pandas().fillna({"age": 0}).to_dict(orient="records")

# Upload in batches for efficiency
batch_size = 1000
for i in range(0, dataset.num_rows, batch_size):
    client.upsert(
        collection_name="image_collection",
        points=models.Batch(
            ids=batch_ids,
            vectors=batch_embeddings,
            payloads=batch_payloads
        )
    )
```

**Production considerations:** The batch upload approach handles large medical datasets efficiently. The metadata preservation ensures that visual similarity search can be combined with clinical criteria (patient demographics, diagnostic methods).

### Medical Visual Search in Practice

```python
# Find visually similar skin lesions
melanoma_sample = dataset[8500]  # A confirmed melanoma case
results = client.search(
    collection_name="image_collection",
    query_vector=melanoma_sample['embeddings'],
    limit=10
)

# Results show cases with similar visual appearance:
# - Other melanomas (diagnostic consistency)
# - Difficult-to-diagnose lesions (differential diagnosis)
# - Benign lesions with melanoma-like features (false positive patterns)
```

**Clinical relevance:** The search returns visually similar cases regardless of their final diagnosis. This is medically valuable—it shows both confirmed cases of the same condition AND diagnostically challenging cases that *look* similar but have different diagnoses.

### Demographic-Filtered Medical Search

```python
# Search for visually similar cases in specific patient populations
female_older_filter = models.Filter(
    must=[
        models.FieldCondition(key="sex", match=models.MatchValue(value="female")),
    ],
    should=[
        models.FieldCondition(key="age", range=models.Range(gte=55.0))
    ]
)

similar_demographic_cases = client.search(
    collection_name="image_collection",
    query_vector=query_embedding,
    query_filter=female_older_filter,
    limit=10
)
```

**Medical utility:** This combines visual similarity with epidemiological factors. Certain skin conditions present differently in different demographic groups, so being able to filter by age and gender while maintaining visual similarity provides more relevant diagnostic comparisons.

### Quality Control with Similarity Thresholds

```python
# Only return high-confidence visual matches
high_confidence_results = client.search(
    collection_name="image_collection",
    query_vector=lesion_embedding,
    score_threshold=0.92,  # 92% similarity minimum
    limit=20
)
```

**Clinical safety:** In medical applications, low-similarity matches could be misleading. Setting similarity thresholds ensures that only genuinely visually similar cases are returned, reducing the risk of false diagnostic suggestions.

### Advanced: Differential Diagnosis Support

```python
# Exclude specific conditions to explore differential diagnosis
not_obvious_cancer_filter = models.Filter(
    must=[models.FieldCondition(
        key="dx", 
        match=models.MatchExcept(**{"except": ["melanoma", "actinic_keratoses"]})
    )],
    must_not=[models.FieldCondition(
        key="localization", 
        match=models.MatchAny(any=["face", "neck"])
    )]
)

differential_cases = client.search(
    collection_name="image_collection",
    query_vector=suspicious_lesion_embedding,
    query_filter=not_obvious_cancer_filter,
    limit=10
)
```

**Diagnostic reasoning:** This search helps with differential diagnosis—"What does this lesion look like if it's NOT cancer?" This is crucial for medical decision-making, as it shows benign conditions that might visually mimic malignant ones.

### Batch Queries for Medical Teams

```python
# Multiple doctors can submit queries simultaneously
query_1 = models.SearchRequest(
    vector=doctor_a_case_embedding,
    filter=chest_lesions_filter,
    limit=4
)

query_2 = models.SearchRequest(
    vector=doctor_b_case_embedding, 
    filter=exclude_benign_lesions_filter,
    limit=7
)

# Process multiple medical queries efficiently
batch_results = client.search_batch(
    collection_name="image_collection",
    requests=[query_1, query_2]
)
```

**Hospital workflow:** Medical teams often need to research multiple cases simultaneously. Batch processing enables efficient resource utilization while supporting collaborative diagnosis.

---

## Mental Model: Thinking in Visual Medical Space

### The Diagnostic Similarity Landscape

Imagine a vast 384-dimensional space where each medical image occupies a position based on its visual characteristics:

```
Medical Visual Space
    
Melanoma Cluster          Benign Mole Cluster
    •  •  •                    •  •  •
   •    •                     •    •
  •      •                   •      •

         Basal Cell Cluster
             •  •  •
            •    •
           •      •
                 
   Keratosis Cluster           Vascular Lesion Cluster
      •  •  •                      •  •  •
     •    •                       •    •
    •      •                     •      •
```

**Distance = Visual Similarity:** Cases that cluster together share visual characteristics that might be diagnostically relevant, even across different condition categories.

### Why DINO Excels for Medical Imagery

Traditional supervised vision models learn to distinguish predefined categories (cat vs. dog). DINO learns visual representations through self-supervision—it discovers visual patterns without being told what categories matter.

**Medical advantage:** Skin conditions exist on spectrums, not in discrete categories. A model that learns visual similarity without categorical bias is better suited for medical diagnosis, where the same condition can look different or different conditions can look similar.

### Understanding Cosine Similarity in Medical Context

For medical images, cosine similarity measures the "diagnostic direction" rather than absolute appearance:

- **Lesion A**: [high_irregularity, dark_pigmentation, asymmetric_border, ...]
- **Lesion B**: [moderate_irregularity, dark_pigmentation, asymmetric_border, ...]

Even though Lesion B is less pronounced, both point in the same "suspicious" direction in feature space, correctly identifying them as similar for diagnostic purposes.

### The Patch-Based Medical Analysis

Vision Transformers analyze medical images like pathologists examine tissue samples:

1. **Detailed examination**: Each 16x16 pixel patch receives focused analysis
2. **Pattern recognition**: The model identifies textures, color variations, boundary characteristics
3. **Contextual integration**: All patch analyses combine to form overall diagnostic impression
4. **Feature extraction**: Complex visual patterns become mathematical representations

This mirrors how medical professionals scan an image systematically while forming an overall diagnostic impression.

### Design Insight: Why 384 Dimensions Matter

DINO's 384-dimensional embeddings capture multiple levels of visual information:
- **Low-level features**: Color, texture, basic shapes
- **Mid-level patterns**: Asymmetry, border irregularity, color variation
- **High-level concepts**: Overall lesion appearance, morphological patterns

This multi-scale representation enables both fine-grained similarity (exact visual matches) and conceptual similarity (diagnostically related appearances).

### Clinical Validation Considerations

The tutorial demonstrates technical capability, but real medical deployment requires:

1. **Expert validation**: Medical professionals must verify that visual similarity correlates with diagnostic relevance
2. **Bias assessment**: Ensuring the model doesn't perpetuate demographic or equipment biases present in training data
3. **Uncertainty quantification**: Understanding when the model is uncertain and shouldn't provide suggestions
4. **Integration protocols**: How visual similarity search fits into existing diagnostic workflows

### Further Exploration

**Try this medical experiment:** Take a confirmed melanoma case and search with different similarity thresholds (0.8, 0.9, 0.95). Notice how higher thresholds return more visually precise matches but potentially miss diagnostically relevant edge cases.

**Clinical workflow integration:** Real systems would integrate with PACS (Picture Archiving and Communication Systems), allowing radiologists and dermatologists to search their institutional databases based on visual similarity.

**Multi-modal extension:** Advanced systems might combine visual embeddings with clinical text notes, genetic markers, or temporal progression data for comprehensive diagnostic support.

---

This tutorial demonstrates how computer vision can augment medical expertise by enabling visual similarity search that transcends traditional categorical organization. The resulting system helps medical professionals find diagnostically relevant cases based on what conditions actually look like, supporting more informed clinical decision-making.