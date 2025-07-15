# GraphRAG with Neo4j

> **Source**: [graphrag_neo4j](https://github.com/qdrant/examples/tree/b3c4b28f66c8cf2a9674bb4491f3f057a1e51237/graphrag_neo4j)

This tutorial demonstrates how to build a GraphRAG (Graph-enhanced Retrieval-Augmented Generation) system that combines vector search with graph databases to answer complex questions requiring multi-hop reasoning and relationship understanding.

## Part 1: Core Concept - Why GraphRAG Matters

### The Limitations of Traditional RAG

Standard RAG systems excel at finding semantically similar content but struggle with questions requiring complex reasoning:

- **Isolated retrieval**: Finds relevant chunks but misses important connections
- **Limited context**: Each retrieved document exists in isolation
- **Missing relationships**: Can't understand how entities relate to each other
- **Shallow reasoning**: Struggles with multi-step logical connections

**Example limitation**: "How did the invention of the steam engine affect industrial labor practices?" requires understanding causal chains and temporal relationships that simple similarity search can't capture.

### The GraphRAG Solution

GraphRAG solves these problems by combining two complementary technologies:

**Vector Search (Qdrant)**: Fast semantic similarity to find relevant starting points
**Graph Database (Neo4j)**: Structured relationship traversal to explore connections

**What you'll build**: A system that extracts knowledge graphs from text, stores them in Neo4j while maintaining vector embeddings in Qdrant, then uses hybrid retrieval to answer complex questions requiring relationship understanding.

### Real-World Applications

- **Research Analysis**: Connect findings across multiple papers and studies
- **Legal Discovery**: Trace relationships between entities, events, and regulations
- **Business Intelligence**: Understand how market events affect different company relationships
- **Medical Research**: Map disease patterns, treatments, and patient outcomes

## Part 2: Practical Walkthrough - Building GraphRAG

### Understanding the Dual-Database Architecture

The system uses two databases working in harmony:

```
Text → [LLM] → Graph Extraction → [Neo4j] (Relationships)
                                ↘
Text → [Embeddings] → Vector Storage → [Qdrant] (Similarity)
                                     ↗
Query → Vector Search → Graph Traversal → Answer Generation
```

**Key insight**: Qdrant finds "what" is relevant, Neo4j explores "how" it's connected.

### Setup and Dependencies

```python
# Core dependencies for GraphRAG
!pip install qdrant-client neo4j openai python-dotenv

import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from neo4j import GraphDatabase
import openai
import json
from typing import List, Dict, Any
```

**Key components:**
- `neo4j`: Graph database for relationship storage
- `qdrant-client`: Vector database for semantic search
- `openai`: LLM for graph extraction and answer generation
- `python-dotenv`: Environment variable management

### Initialize Services

```python
# Load environment variables
load_dotenv()

# Initialize OpenAI client
openai.api_key = os.getenv("OPENAI_API_KEY")

# Initialize Qdrant client
qdrant_client = QdrantClient("localhost", port=6333)

# Initialize Neo4j driver
neo4j_driver = GraphDatabase.driver(
    uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    auth=(
        os.getenv("NEO4J_USERNAME", "neo4j"),
        os.getenv("NEO4J_PASSWORD", "password")
    )
)

print("All services initialized successfully!")
```

### Stage 1: Knowledge Graph Extraction

#### LLM-Based Graph Extraction

```python
def extract_graph_components(text: str) -> Dict[str, Any]:
    """Extract entities and relationships from text using LLM"""
    
    # Define JSON schema for structured extraction
    extraction_schema = {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "description": {"type": "string"}
                    },
                    "required": ["id", "name", "type"]
                }
            },
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "type": {"type": "string"},
                        "description": {"type": "string"}
                    },
                    "required": ["source", "target", "type"]
                }
            }
        },
        "required": ["entities", "relationships"]
    }
    
    prompt = f"""
    Extract entities and relationships from the following text. 
    Return a JSON object with entities and relationships arrays.
    
    Entities should include:
    - id: unique identifier
    - name: entity name
    - type: entity category (person, organization, concept, event, etc.)
    - description: brief description
    
    Relationships should include:
    - source: source entity id
    - target: target entity id  
    - type: relationship type (affects, causes, works_for, etc.)
    - description: relationship description
    
    Text: {text}
    
    JSON Schema: {json.dumps(extraction_schema)}
    """
    
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert at extracting structured knowledge from text."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )
    
    try:
        return json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        print("Failed to parse LLM response as JSON")
        return {"entities": [], "relationships": []}

# Test graph extraction
sample_text = """
The industrial revolution transformed manufacturing in the 18th century. 
James Watt improved the steam engine in 1769, which revolutionized factory production. 
This led to the growth of industrial cities like Manchester and Birmingham. 
Factory owners accumulated wealth while workers faced harsh conditions.
The steam engine also transformed transportation through railways.
"""

extracted_graph = extract_graph_components(sample_text)
print("Extracted entities:", len(extracted_graph['entities']))
print("Extracted relationships:", len(extracted_graph['relationships']))
```

### Stage 2: Neo4j Graph Storage

#### Create Graph Database Schema

```python
def setup_neo4j_schema(driver):
    """Set up Neo4j constraints and indexes"""
    
    with driver.session() as session:
        # Create unique constraint on entity ID
        session.run("""
            CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
            FOR (e:Entity) REQUIRE e.id IS UNIQUE
        """)
        
        # Create index on entity name for fast searches
        session.run("""
            CREATE INDEX entity_name_index IF NOT EXISTS
            FOR (e:Entity) ON (e.name)
        """)
        
        print("Neo4j schema created successfully")

def ingest_to_neo4j(driver, graph_data: Dict[str, Any], source_text: str):
    """Ingest extracted graph into Neo4j"""
    
    with driver.session() as session:
        # Create entities
        for entity in graph_data['entities']:
            session.run("""
                MERGE (e:Entity {id: $id})
                SET e.name = $name,
                    e.type = $type,
                    e.description = $description,
                    e.source_text = $source_text
            """, 
            id=entity['id'],
            name=entity['name'],
            type=entity['type'],
            description=entity.get('description', ''),
            source_text=source_text
            )
        
        # Create relationships
        for rel in graph_data['relationships']:
            session.run("""
                MATCH (source:Entity {id: $source_id})
                MATCH (target:Entity {id: $target_id})
                MERGE (source)-[r:RELATIONSHIP {type: $rel_type}]->(target)
                SET r.description = $description
            """,
            source_id=rel['source'],
            target_id=rel['target'],
            rel_type=rel['type'],
            description=rel.get('description', '')
            )
        
        print(f"Ingested {len(graph_data['entities'])} entities and {len(graph_data['relationships'])} relationships")

# Setup and ingest
setup_neo4j_schema(neo4j_driver)
ingest_to_neo4j(neo4j_driver, extracted_graph, sample_text)
```

### Stage 3: Qdrant Vector Storage

#### Create Vector Collection and Link to Graph

```python
def setup_qdrant_collection(client, collection_name="graphrag_entities"):
    """Create Qdrant collection for entity embeddings"""
    
    # Delete existing collection if it exists
    try:
        client.delete_collection(collection_name)
    except:
        pass
    
    # Create new collection
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=1536,  # OpenAI text-embedding-ada-002 dimension
            distance=Distance.COSINE
        )
    )
    
    print(f"Created Qdrant collection '{collection_name}'")

def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """Generate embeddings using OpenAI"""
    
    response = openai.embeddings.create(
        model="text-embedding-ada-002",
        input=texts
    )
    
    return [embedding.embedding for embedding in response.data]

def ingest_to_qdrant(client, graph_data: Dict[str, Any], source_text: str, collection_name="graphrag_entities"):
    """Ingest entity embeddings to Qdrant with Neo4j ID linking"""
    
    points = []
    texts_to_embed = []
    
    # Prepare entity text for embedding
    for entity in graph_data['entities']:
        entity_text = f"{entity['name']} - {entity.get('description', '')}"
        texts_to_embed.append(entity_text)
    
    # Generate embeddings
    embeddings = generate_embeddings(texts_to_embed)
    
    # Create points linking to Neo4j entities
    for i, (entity, embedding) in enumerate(zip(graph_data['entities'], embeddings)):
        point = PointStruct(
            id=i,
            vector=embedding,
            payload={
                "neo4j_id": entity['id'],  # Critical link to Neo4j
                "name": entity['name'],
                "type": entity['type'],
                "description": entity.get('description', ''),
                "source_text": source_text
            }
        )
        points.append(point)
    
    # Upload to Qdrant
    client.upsert(collection_name=collection_name, points=points)
    print(f"Ingested {len(points)} entity embeddings to Qdrant")

# Setup and ingest to Qdrant
setup_qdrant_collection(qdrant_client)
ingest_to_qdrant(qdrant_client, extracted_graph, sample_text)
```

### Stage 4: Hybrid Retrieval System

#### Semantic Search with Graph Expansion

```python
class QdrantNeo4jRetriever:
    """Hybrid retriever combining Qdrant and Neo4j"""
    
    def __init__(self, qdrant_client, neo4j_driver, collection_name="graphrag_entities"):
        self.qdrant_client = qdrant_client
        self.neo4j_driver = neo4j_driver
        self.collection_name = collection_name
    
    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve relevant entities and their graph context"""
        
        # Step 1: Vector search in Qdrant
        query_embedding = generate_embeddings([query])[0]
        
        search_results = self.qdrant_client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=top_k
        )
        
        # Extract Neo4j entity IDs
        entity_ids = [result.payload['neo4j_id'] for result in search_results]
        
        # Step 2: Graph expansion in Neo4j
        expanded_context = self.fetch_related_graph(entity_ids)
        
        return {
            'vector_results': search_results,
            'graph_context': expanded_context,
            'entity_ids': entity_ids
        }
    
    def fetch_related_graph(self, entity_ids: List[str], max_hops: int = 2) -> List[Dict[str, Any]]:
        """Fetch subgraph around seed entities"""
        
        with self.neo4j_driver.session() as session:
            # Cypher query for 2-hop neighborhood
            query = """
            MATCH (seed:Entity)
            WHERE seed.id IN $entity_ids
            
            // Get seed entities
            WITH collect(seed) as seeds
            UNWIND seeds as seed
            
            // Expand to neighbors (1-hop)
            MATCH (seed)-[r1]-(n1:Entity)
            
            // Expand to neighbors of neighbors (2-hop)
            OPTIONAL MATCH (n1)-[r2]-(n2:Entity)
            
            // Return subgraph
            RETURN seed, r1, n1, r2, n2
            LIMIT 100
            """
            
            result = session.run(query, entity_ids=entity_ids)
            
            # Process results into structured format
            subgraph = {
                'nodes': set(),
                'relationships': []
            }
            
            for record in result:
                # Add seed entity
                if record['seed']:
                    subgraph['nodes'].add((
                        record['seed']['id'],
                        record['seed']['name'],
                        record['seed']['type']
                    ))
                
                # Add 1-hop entities and relationships
                if record['n1'] and record['r1']:
                    subgraph['nodes'].add((
                        record['n1']['id'],
                        record['n1']['name'],
                        record['n1']['type']
                    ))
                    
                    subgraph['relationships'].append({
                        'source': record['seed']['name'],
                        'target': record['n1']['name'],
                        'type': record['r1']['type'],
                        'description': record['r1'].get('description', '')
                    })
                
                # Add 2-hop entities and relationships
                if record['n2'] and record['r2']:
                    subgraph['nodes'].add((
                        record['n2']['id'],
                        record['n2']['name'],
                        record['n2']['type']
                    ))
                    
                    subgraph['relationships'].append({
                        'source': record['n1']['name'],
                        'target': record['n2']['name'],
                        'type': record['r2']['type'],
                        'description': record['r2'].get('description', '')
                    })
            
            # Convert nodes set to list for JSON serialization
            subgraph['nodes'] = [{'id': n[0], 'name': n[1], 'type': n[2]} for n in subgraph['nodes']]
            
            return subgraph

# Initialize retriever
retriever = QdrantNeo4jRetriever(qdrant_client, neo4j_driver)
```

### Stage 5: Answer Generation

#### Graph-Aware Response Generation

```python
def format_graph_context(subgraph: Dict[str, Any]) -> str:
    """Format graph data for LLM consumption"""
    
    context_parts = []
    
    # Format entities
    if subgraph['nodes']:
        context_parts.append("ENTITIES:")
        for node in subgraph['nodes']:
            context_parts.append(f"- {node['name']} ({node['type']})")
    
    # Format relationships
    if subgraph['relationships']:
        context_parts.append("\nRELATIONSHIPS:")
        for rel in subgraph['relationships']:
            desc = f" - {rel['description']}" if rel['description'] else ""
            context_parts.append(f"- {rel['source']} --[{rel['type']}]--> {rel['target']}{desc}")
    
    return "\n".join(context_parts)

def graphrag_answer(query: str, retriever: QdrantNeo4jRetriever) -> str:
    """Generate answer using GraphRAG pipeline"""
    
    print(f"Processing query: {query}")
    
    # Step 1: Hybrid retrieval
    retrieval_results = retriever.retrieve(query, top_k=5)
    
    # Step 2: Format context
    graph_context = format_graph_context(retrieval_results['graph_context'])
    
    # Step 3: Generate answer
    prompt = f"""
    Based on the following knowledge graph context, answer the user's question.
    Focus on the relationships and connections between entities.
    
    KNOWLEDGE GRAPH CONTEXT:
    {graph_context}
    
    QUESTION: {query}
    
    ANSWER:
    """
    
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert at analyzing knowledge graphs and providing insightful answers based on entity relationships."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    
    return response.choices[0].message.content

# Test GraphRAG system
test_questions = [
    "How did the steam engine affect industrial cities?",
    "What was the relationship between James Watt and factory production?",
    "How did the industrial revolution impact workers?",
    "What role did Manchester play in industrialization?"
]

for question in test_questions:
    answer = graphrag_answer(question, retriever)
    print(f"\n🔍 Question: {question}")
    print(f"📝 Answer: {answer}")
    print("-" * 80)
```

## Part 3: Mental Models & Deep Dives

### Understanding the GraphRAG Mental Model

**Think of GraphRAG like a detective investigating a complex case**:

**Traditional RAG**: Like searching individual witness statements
- Finds relevant testimony but misses connections
- Each statement stands alone
- Limited to surface-level similarity

**GraphRAG**: Like mapping the entire network of relationships
- Connects witness statements through relationships
- Reveals hidden patterns and indirect connections
- Enables multi-step reasoning and causal analysis

### The Dual-Database Strategy

**Mental Model**: Qdrant and Neo4j are like a library's card catalog and cross-reference system:

**Qdrant (Card Catalog)**:
- Fast lookup by topic/content
- "Show me all books about steam engines"
- Semantic similarity matching

**Neo4j (Cross-Reference System)**:
- Shows how topics connect
- "Steam engines → factories → labor conditions → social change"
- Structural relationship exploration

### Graph Extraction Mental Model

**LLM as Knowledge Archaeologist**:
```python
# The LLM transforms unstructured narrative...
text = "James Watt improved the steam engine, revolutionizing factory production"

# Into structured knowledge...
entities = [
    {"id": "james_watt", "name": "James Watt", "type": "person"},
    {"id": "steam_engine", "name": "Steam Engine", "type": "technology"},
    {"id": "factory_production", "name": "Factory Production", "type": "process"}
]

relationships = [
    {"source": "james_watt", "target": "steam_engine", "type": "improved"},
    {"source": "steam_engine", "target": "factory_production", "type": "revolutionized"}
]
```

### Advanced GraphRAG Patterns

#### Multi-Document Graph Building

```python
def build_comprehensive_graph(documents: List[str]):
    """Build knowledge graph from multiple documents"""
    
    all_entities = {}
    all_relationships = []
    
    for doc in documents:
        # Extract graph from each document
        graph = extract_graph_components(doc)
        
        # Merge entities (handle duplicates)
        for entity in graph['entities']:
            entity_key = entity['name'].lower()
            if entity_key in all_entities:
                # Merge descriptions
                existing = all_entities[entity_key]
                existing['description'] += f" {entity.get('description', '')}"
            else:
                all_entities[entity_key] = entity
        
        # Collect all relationships
        all_relationships.extend(graph['relationships'])
    
    return {
        'entities': list(all_entities.values()),
        'relationships': all_relationships
    }
```

#### Temporal Graph Queries

```python
def temporal_graph_analysis(driver, start_date: str, end_date: str):
    """Analyze how relationships evolved over time"""
    
    with driver.session() as session:
        query = """
        MATCH (e1:Entity)-[r:RELATIONSHIP]->(e2:Entity)
        WHERE r.date >= $start_date AND r.date <= $end_date
        RETURN e1.name, r.type, e2.name, r.date
        ORDER BY r.date
        """
        
        result = session.run(query, start_date=start_date, end_date=end_date)
        
        timeline = []
        for record in result:
            timeline.append({
                'date': record['r.date'],
                'source': record['e1.name'],
                'relationship': record['r.type'],
                'target': record['e2.name']
            })
        
        return timeline
```

#### Community Detection in Graphs

```python
def find_entity_communities(driver):
    """Identify clusters of related entities"""
    
    with driver.session() as session:
        # Use graph algorithms to find communities
        query = """
        CALL gds.louvain.stream('entity-graph')
        YIELD nodeId, communityId
        MATCH (e:Entity) WHERE id(e) = nodeId
        RETURN e.name, e.type, communityId
        ORDER BY communityId, e.name
        """
        
        result = session.run(query)
        
        communities = {}
        for record in result:
            comm_id = record['communityId']
            if comm_id not in communities:
                communities[comm_id] = []
            
            communities[comm_id].append({
                'name': record['e.name'],
                'type': record['e.type']
            })
        
        return communities
```

### Performance Optimization Strategies

#### Efficient Graph Traversal

```python
def optimized_subgraph_query(session, entity_ids: List[str], max_depth: int = 2):
    """Optimized query for large graphs"""
    
    # Use WITH clauses to control memory usage
    query = f"""
    MATCH (seed:Entity)
    WHERE seed.id IN $entity_ids
    
    WITH seed
    CALL {{
        WITH seed
        MATCH (seed)-[*1..{max_depth}]-(related:Entity)
        RETURN collect(DISTINCT related) as related_entities
    }}
    
    WITH seed, related_entities
    UNWIND related_entities as entity
    
    // Get relationships within this subgraph
    MATCH (entity)-[r]-(connected)
    WHERE connected IN related_entities
    
    RETURN entity, r, connected
    LIMIT 1000
    """
    
    return session.run(query, entity_ids=entity_ids)
```

#### Caching Strategies

```python
import functools
import hashlib
from typing import Tuple

def cache_graph_results(func):
    """Cache expensive graph operations"""
    cache = {}
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Create cache key from arguments
        key = hashlib.md5(str(args + tuple(kwargs.items())).encode()).hexdigest()
        
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        
        return cache[key]
    
    return wrapper

@cache_graph_results
def expensive_graph_operation(entity_ids: List[str]) -> Dict[str, Any]:
    """Expensive operation that benefits from caching"""
    # Complex graph analysis here
    pass
```

### Real-World Implementation Considerations

#### Handling Large-Scale Graphs

```python
def batch_graph_ingestion(documents: List[str], batch_size: int = 100):
    """Process large document collections efficiently"""
    
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        
        # Process batch
        batch_graph = build_comprehensive_graph(batch)
        
        # Ingest to databases
        ingest_to_neo4j(neo4j_driver, batch_graph, f"batch_{i}")
        ingest_to_qdrant(qdrant_client, batch_graph, f"batch_{i}")
        
        print(f"Processed batch {i//batch_size + 1}/{(len(documents) + batch_size - 1)//batch_size}")
```

#### Quality Control and Validation

```python
def validate_graph_quality(driver):
    """Check graph quality metrics"""
    
    with driver.session() as session:
        metrics = {}
        
        # Entity count
        result = session.run("MATCH (e:Entity) RETURN count(e) as entity_count")
        metrics['entity_count'] = result.single()['entity_count']
        
        # Relationship count
        result = session.run("MATCH ()-[r:RELATIONSHIP]->() RETURN count(r) as rel_count")
        metrics['relationship_count'] = result.single()['rel_count']
        
        # Isolated entities (no relationships)
        result = session.run("""
            MATCH (e:Entity)
            WHERE NOT (e)-[:RELATIONSHIP]-()
            RETURN count(e) as isolated_count
        """)
        metrics['isolated_entities'] = result.single()['isolated_count']
        
        # Average degree (connections per entity)
        result = session.run("""
            MATCH (e:Entity)
            RETURN avg(size((e)-[:RELATIONSHIP]-())) as avg_degree
        """)
        metrics['average_degree'] = result.single()['avg_degree']
        
        return metrics
```

This comprehensive GraphRAG system demonstrates how combining vector search with graph databases creates powerful question-answering capabilities that understand both semantic similarity and structural relationships in knowledge.