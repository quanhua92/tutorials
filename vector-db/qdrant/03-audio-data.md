# Music Recommendation with Audio Embeddings: Beyond Metadata

**Source Example:** [qdrant_101_audio_data](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/qdrant_101_audio_data)

## The Core Concept: Why This Example Exists

### The Problem
Traditional music recommendation systems rely on metadata—genre labels, artist information, user ratings. But this approach misses the nuances of *how music actually sounds*. Two songs labeled "rock" might be completely different: one could be soft acoustic rock, another heavy metal. How do you recommend music based on the actual audio characteristics—rhythm, melody, timbre—rather than just text labels?

### The Solution
Audio embeddings capture the sonic essence of music in numerical vectors. By analyzing waveforms, frequency patterns, and acoustic features, machine learning models can encode what a song *sounds like* into high-dimensional space. Songs with similar beats, harmonies, or energy levels cluster together, enabling recommendations that match musical taste rather than genre categories.

Qdrant's philosophy for audio: **Sound tells the story that metadata cannot**. By storing representations of actual audio content, you can build recommendation systems that understand musical similarity at a perceptual level.

---

## Practical Walkthrough: Code Breakdown

### Dataset and Audio Loading

The example uses the Ludwig Music Dataset containing over 10,000 songs across genres:

```python
from datasets import load_dataset

# Load Latin music subset for this example
music_data = load_dataset(
    "audiofolder", 
    data_dir=join(data_path, "mp3", "latin"), 
    split="train", 
    drop_labels=True
)

# Each sample contains the audio data
sample = music_data[115]
# {'audio': {'path': '...', 'array': [...], 'sampling_rate': 44100}}
```

**Why audio arrays matter:** The `array` field contains the raw audio waveform—the actual sound data. This is what we'll transform into semantic embeddings. Unlike text or images, audio is inherently temporal, requiring models that understand sequences and frequencies.

### Extracting Audio Identifiers and Metadata

```python
# Extract unique song IDs from file paths
ids = [
    music_data[i]['audio']['path']
    .split("/")[-1]
    .replace(".mp3", '')
    for i in range(len(music_data))
]

# Join with rich metadata from labels.json
metadata = pd.read_json(label_path)
clean_metadata = metadata['tracks'].apply(extract_audio_metadata)
```

**Key insight:** The example carefully separates the audio content (what the song sounds like) from the metadata (artist, genre, year). This allows for comparisons: do songs that sound similar also share metadata characteristics?

## Audio Embedding Approaches: Three Pathways

The tutorial demonstrates three different approaches to creating audio embeddings, each with distinct advantages:

### Approach 1: OpenL3 - Purpose-Built Audio Embeddings

```python
import openl3

# Load specialized music model
model_kapre = openl3.models.load_audio_embedding_model(
    input_repr='mel128', 
    content_type='music', 
    embedding_size=512
)

def get_openl3_embeddings(batch):
    audio_arrays = [song['array'] for song in batch['audio']]
    sr_arrays = [song['sampling_rate'] for song in batch['audio']]
    embs_list, _ = openl3.get_audio_embedding(audio_arrays, sr_arrays, model=model_kapre)
    
    # Average over time to get one vector per song
    batch["open_embeddings"] = np.array([embedding.mean(axis=0) for embedding in embs_list])
    return batch
```

**OpenL3's strength:** Specifically designed for audio analysis. The `mel128` representation converts audio to mel-spectrograms (visual representations of frequency content over time), which the model then processes. The `content_type='music'` ensures the model is optimized for musical rather than speech content.

### Approach 2: PANNs Inference - Large-Scale Audio Classification

```python
from panns_inference import AudioTagging

# Load pre-trained model on AudioSet (YouTube's massive audio dataset)
at = AudioTagging(checkpoint_path=None, device='cuda')

def get_panns_embeddings(batch):
    # PANNs expects [batch, samples] format
    arrays = [torch.tensor(val['array'], dtype=torch.float64) for val in batch['audio']]
    inputs = torch.nn.utils.rnn.pad_sequence(arrays, batch_first=True, padding_value=0)
    
    _, embedding = at.inference(inputs)  # Returns (classification, embedding)
    batch['panns_embeddings'] = embedding
    return batch
```

**PANNs' advantage:** Trained on millions of YouTube audio clips covering every imaginable sound. The 2048-dimensional embeddings capture broad acoustic patterns. Since it's trained for audio event detection, it excels at recognizing rhythmic patterns, instrumental timbres, and energy levels.

**Key technical detail:** PANNs returns both classification outputs (527 audio event probabilities) and embeddings (2048-dimensional representations). We use the embeddings, which contain richer information than the classifications.

### Approach 3: Wav2Vec2 - Transformer Architecture for Audio

```python
from transformers import AutoModel, AutoFeatureExtractor

# Load speech pre-trained model (demonstrates transfer learning limits)
model = AutoModel.from_pretrained('facebook/wav2vec2-base')
feature_extractor = AutoFeatureExtractor.from_pretrained('facebook/wav2vec2-base')

def get_transformer_embeddings(batch):
    # Resample to 16kHz (Wav2Vec2 requirement)
    audio_arrays = [x["array"] for x in batch["audio"]]
    inputs = feature_extractor(
        audio_arrays, 
        sampling_rate=16_000, 
        return_tensors="pt", 
        padding=True,
        max_length=16_000, 
        truncation=True
    )
    
    with torch.no_grad():
        # Mean pool across time dimension
        pooled_embeds = model(**inputs).last_hidden_state.mean(dim=1)
    
    return {"transform_embeddings": pooled_embeds.cpu().numpy()}
```

**Wav2Vec2's limitation:** Designed for speech recognition, not music analysis. The example includes this to demonstrate that model choice matters—general-purpose models don't always transfer well to specialized domains.

### Understanding Temporal Aggregation

All three approaches face the same challenge: converting variable-length audio into fixed-size vectors.

```python
# Before aggregation: [time_steps, embedding_dim]
raw_embeddings.shape  # e.g., (150, 512) for a 5-second clip

# After mean pooling: [embedding_dim]
song_embedding = raw_embeddings.mean(axis=0)  # (512,)
```

**Why mean pooling works:** For music recommendation, we want to capture the overall character of a song rather than moment-by-moment details. Mean pooling creates a "summary embedding" that represents the song's average acoustic properties.

### Building the Audio Recommendation System

```python
# Create collection for 2048-dimensional PANNs embeddings
client.recreate_collection(
    collection_name="music_collection",
    vectors_config=models.VectorParams(size=2048, distance=models.Distance.COSINE)
)

# Upload audio embeddings with rich metadata
client.upsert(
    collection_name="music_collection",
    points=models.Batch(
        ids=music_data['index'],
        vectors=music_data['panns_embeddings'],  # The actual audio content
        payloads=metadata_payload  # Artist, genre, subgenre, file paths
    )
)
```

**Critical design choice:** Using 2048 dimensions from PANNs because it provides the richest audio representations. OpenL3 (512-dim) is more compact but potentially less expressive. Wav2Vec2 (768-dim) works for speech but misses musical nuances.

### Semantic Music Search in Action

```python
# Find songs similar to Celia Cruz's "Cuando Sali De Cuba"
celia_cruz_song_id = 150
results = client.search(
    collection_name="music_collection",
    query_vector=music_data[celia_cruz_song_id]['panns_embeddings'],
    limit=10
)

# Results show songs with similar acoustic properties:
# - Other salsa tracks (rhythm similarity)
# - Samba music (related Latin rhythms)
# - Cuban son (cultural/musical ancestry)
```

**What makes this "semantic":** The system finds songs that *sound* similar to Celia Cruz, not just songs with similar metadata. It discovers cross-genre connections (salsa-samba) that pure metadata filtering would miss.

### Advanced: Preference-Based Recommendations

```python
# User likes multiple Celia Cruz songs but dislikes Chayanne ballads
recommendations = client.recommend(
    collection_name="music_collection",
    positive=[178, 122, 459],    # Multiple Celia Cruz tracks
    negative=[385],              # Chayanne's "Yo Te Amo" (too ballad-y)
    limit=5
)
```

**The recommendation mathematics:** Qdrant computes the centroid (average) of positive examples, then finds vectors near that centroid but far from negative examples. This creates a "preference region" in embedding space.

### Genre-Filtered Recommendations

```python
# Only recommend samba songs (even if other genres might be similar)
samba_filter = models.Filter(
    must=[models.FieldCondition(key="subgenres", match=models.MatchAny(any=['latin---samba']))]
)

samba_recommendations = client.recommend(
    collection_name="music_collection",
    query_filter=samba_filter,
    positive=[liked_song_ids],
    negative=[disliked_song_ids],
    limit=5
)
```

**Hybrid power:** This combines acoustic similarity (from embeddings) with categorical constraints (from metadata). You get songs that sound like your preferences AND match specific requirements.

---

## Mental Model: Thinking in Audio Space

### The Audio Embedding Landscape

Imagine a vast multidimensional space where each song occupies a point based on its acoustic properties:

```
    Acoustic Space Visualization
    
    High Energy          • Rock/Metal    • Electronic Dance
                        •  •           •  •
                       •                  •
    
    Mid Energy      • Latin/Salsa    • Pop/R&B
                   •  •  •          •  •
                  •                 •
    
    Low Energy   • Ambient        • Classical/Ballads
                •  •             •  •  •
               •                 •
    
         Rhythmic ←----------→ Melodic
```

**Distance in this space** correlates with perceptual similarity. Songs close together share acoustic properties that human ears recognize as similar.

### Why PANNs Embeddings Excel for Music

PANNs (Pre-trained Audio Neural Networks) were trained on AudioSet—millions of 10-second YouTube clips labeled with 527 audio event categories. This massive dataset includes:

- **Instrumental diversity**: Every instrument imaginable
- **Musical genres**: From classical to electronic to world music  
- **Production styles**: Studio recordings, live performances, amateur recordings
- **Acoustic environments**: Concert halls, clubs, street performances

This broad training enables PANNs to recognize subtle audio patterns that specialized music models might miss.

### Understanding Audio Temporal Dynamics

Unlike text (which processes left-to-right) or images (which process spatially), audio is inherently temporal:

```
Audio Timeline Processing:
[Beat] → [Melody] → [Harmony] → [Rhythm] → [Timbre] → ...
  ↓        ↓         ↓           ↓          ↓
Embedding captures patterns across time
```

**Mean pooling aggregation** creates a summary that maintains important characteristics while removing temporal specificity. This is why two songs with the same chord progression but different tempos can still be recognized as similar.

### Design Insight: The Embedding Size Trade-off

- **512 dimensions (OpenL3)**: Compact, efficient, good for basic similarity
- **768 dimensions (Wav2Vec2)**: Medium complexity, optimized for speech
- **2048 dimensions (PANNs)**: Rich representations, captures subtle audio nuances

**The sweet spot:** PANNs' 2048 dimensions provide enough capacity to encode complex musical relationships without becoming unwieldy for vector search.

### Transfer Learning Considerations

The example demonstrates an important principle: **model training objective matters more than architecture sophistication**.

- **OpenL3**: Trained specifically for audio content analysis → Good music recommendations
- **PANNs**: Trained on diverse audio events → Excellent music recommendations  
- **Wav2Vec2**: Trained for speech recognition → Poor music recommendations

This shows why choosing the right pre-trained model is crucial for domain-specific applications.

### Further Exploration

**Try this experiment:** Generate embeddings for the same song using all three approaches, then search for similar songs with each. Notice how PANNs finds more musically coherent results than Wav2Vec2, despite Wav2Vec2 being a more recent architecture.

**Real-world scaling:** Production music recommendation systems often combine multiple embedding approaches—audio content embeddings for sonic similarity, plus collaborative filtering for user behavior patterns, plus metadata features for explicit constraints.

**Performance consideration:** Audio embedding generation is computationally expensive (especially for large datasets), but once generated, vector similarity search in Qdrant is extremely fast, enabling real-time recommendations.

---

This tutorial demonstrates how to capture the essence of music in mathematical form, enabling recommendation systems that understand what songs *sound like* rather than just what their metadata says. The resulting system can discover musical connections that transcend traditional category boundaries, mimicking how humans actually experience musical similarity.